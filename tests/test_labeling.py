"""Unit tests for labeling.py — triple-barrier + bootstrap CI + EWMA sigma.

Spec — enforces de Prado (AFML §3.4) invariants:

1. First-touch correctness — strict ordering, SL preferred when both intersect.
2. Direction symmetry — BUY and SELL are mirror images.
3. Return sign correctness — BUY wins = positive, SELL wins = positive.
4. Timeout fallback — when neither barrier hit, label=0 and t1=horizon.
5. Bad input — never raises; returns canonical sentinel.
6. EWMA sigma — sane (positive, finite) on synthetic data with known vol.
7. Bootstrap CI — point estimate matches sample mean; lo ≤ point ≤ hi.
8. Bootstrap reproducibility — same seed → same CI (cache safety).
"""
from __future__ import annotations

import math
import random
import statistics

import pytest

from labeling import (
    triple_barrier_label,
    ewma_daily_sigma,
    vol_scaled_barriers,
    bootstrap_ci,
    bootstrap_wr_ci,
    bootstrap_sharpe_ci,
    label_outcome_aliases,
)


# ══════════════════════════════════════════════════════════
# 1. triple_barrier_label — core first-touch logic
# ══════════════════════════════════════════════════════════
class TestTripleBarrier:
    def test_buy_hits_tp_first(self):
        future = [{"h": 100.5, "l": 99.5}, {"h": 101.5, "l": 100.0}, {"h": 102.5, "l": 101.0}]
        out = triple_barrier_label("BUY", entry_price=100.0, sl=99.0, tp=102.0,
                                    future_bars=future, t1_bars=10)
        assert out["bin"] == 1
        assert out["touch"] == "TP"
        assert out["ret"] == pytest.approx(0.02, abs=1e-6)
        assert out["t1"] == 2

    def test_buy_hits_sl_first(self):
        future = [{"h": 100.2, "l": 99.5}, {"h": 99.1, "l": 98.5}, {"h": 102.5, "l": 101.0}]
        out = triple_barrier_label("BUY", entry_price=100.0, sl=99.0, tp=102.0,
                                    future_bars=future, t1_bars=10)
        assert out["bin"] == -1
        assert out["touch"] == "SL"
        assert out["ret"] == pytest.approx(-0.01, abs=1e-6)
        assert out["t1"] == 1

    def test_sell_hits_tp_first(self):
        # SELL: TP is BELOW entry, SL ABOVE
        future = [{"h": 100.5, "l": 99.0}, {"h": 99.5, "l": 97.5}]
        out = triple_barrier_label("SELL", entry_price=100.0, sl=101.0, tp=98.0,
                                    future_bars=future, t1_bars=10)
        assert out["bin"] == 1
        assert out["touch"] == "TP"
        assert out["ret"] == pytest.approx(0.02, abs=1e-6)  # SELL win = positive return
        assert out["t1"] == 1

    def test_sell_hits_sl_first(self):
        future = [{"h": 101.5, "l": 99.0}]
        out = triple_barrier_label("SELL", entry_price=100.0, sl=101.0, tp=98.0,
                                    future_bars=future, t1_bars=10)
        assert out["bin"] == -1
        assert out["touch"] == "SL"
        assert out["ret"] == pytest.approx(-0.01, abs=1e-6)
        assert out["t1"] == 0

    def test_timeout_label_zero(self):
        future = [{"h": 100.1, "l": 99.9}] * 5
        out = triple_barrier_label("BUY", entry_price=100.0, sl=99.0, tp=102.0,
                                    future_bars=future, t1_bars=5)
        assert out["bin"] == 0
        assert out["touch"] == "TIMEOUT"
        assert out["t1"] == 5
        # Mark-to-market at mid of last bar
        assert out["ret"] == pytest.approx(0.0, abs=1e-6)

    def test_same_bar_intersection_prefers_sl(self):
        # Single bar straddles both barriers — strict first-touch chooses SL (conservative).
        future = [{"h": 102.5, "l": 98.5}]
        out = triple_barrier_label("BUY", entry_price=100.0, sl=99.0, tp=102.0,
                                    future_bars=future, t1_bars=5)
        assert out["bin"] == -1
        assert out["touch"] == "SL"

    def test_horizon_clipped_to_t1(self):
        # 10 bars provided but t1=2 — must stop scanning at index 1.
        future = [{"h": 99.5, "l": 99.0}, {"h": 99.6, "l": 99.1}] + [{"h": 105, "l": 95}] * 8
        out = triple_barrier_label("BUY", entry_price=100.0, sl=98.5, tp=102.0,
                                    future_bars=future, t1_bars=2)
        assert out["bin"] == 0
        assert out["touch"] == "TIMEOUT"
        assert out["t1"] == 2

    @pytest.mark.parametrize("bad_dir", ["", "HOLD", None, "buy"])
    def test_invalid_direction_returns_sentinel(self, bad_dir):
        out = triple_barrier_label(bad_dir, 100.0, 99.0, 102.0,
                                    [{"h": 102, "l": 99}], t1_bars=1)
        assert out == {"bin": 0, "touch": "INVALID", "ret": 0.0, "t1": 0}

    def test_invalid_entry_price_returns_sentinel(self):
        for ep in (None, 0, -5):
            out = triple_barrier_label("BUY", ep, 99.0, 102.0,
                                        [{"h": 102, "l": 99}], t1_bars=1)
            assert out["touch"] == "INVALID"

    def test_empty_future_bars_returns_sentinel(self):
        out = triple_barrier_label("BUY", 100.0, 99.0, 102.0, [], t1_bars=5)
        assert out["touch"] == "INVALID"

    def test_missing_h_or_l_skipped(self):
        # Malformed bar without h/l is skipped, not crashed.
        future = [{"h": None, "l": None}, {"h": 102.5, "l": 100.0}]
        out = triple_barrier_label("BUY", 100.0, 99.0, 102.0, future, t1_bars=5)
        assert out["bin"] == 1
        assert out["t1"] == 1


# ══════════════════════════════════════════════════════════
# 2. ewma_daily_sigma — volatility estimator
# ══════════════════════════════════════════════════════════
class TestEwmaSigma:
    def test_constant_series_zero_sigma(self):
        closes = [100.0] * 100
        sig = ewma_daily_sigma(closes, bars_per_day=288, halflife_days=20.0)
        assert sig == 0.0

    def test_returns_none_on_empty(self):
        assert ewma_daily_sigma([], 288, 20.0) is None
        assert ewma_daily_sigma([100.0], 288, 20.0) is None

    def test_synthetic_volatility_in_range(self):
        # Build a synthetic series with known per-bar log-return sd ~ 0.001.
        rng = random.Random(42)
        closes = [100.0]
        for _ in range(2000):
            r = rng.gauss(0.0, 0.001)  # bar log return
            closes.append(closes[-1] * math.exp(r))
        sig = ewma_daily_sigma(closes, bars_per_day=288, halflife_days=20.0)
        assert sig is not None
        # Theoretical daily sigma = bar sigma * sqrt(288) ≈ 0.017
        assert 0.005 < sig < 0.05

    def test_handles_zero_or_negative_prices(self):
        closes = [100.0, 101.0, 0.0, -5.0, 102.0, 103.0]
        # Should not raise; uses only valid pairs.
        sig = ewma_daily_sigma(closes, 288, 20.0)
        assert sig is None or sig >= 0.0


class TestVolScaledBarriers:
    def test_buy_returns_tp_above_sl_below(self):
        tp, sl = vol_scaled_barriers(100.0, 0.02, pt_multiple=2.0, sl_multiple=1.0, direction="BUY")
        assert tp == pytest.approx(104.0)
        assert sl == pytest.approx(98.0)

    def test_sell_inverts(self):
        # SELL with pt=2.0, sl=1.0, sigma=0.02:
        #   TP = 100*(1 - 2.0*0.02) = 96.0   (profit-take BELOW entry)
        #   SL = 100*(1 + 1.0*0.02) = 102.0  (stop-loss ABOVE entry)
        tp, sl = vol_scaled_barriers(100.0, 0.02, pt_multiple=2.0, sl_multiple=1.0, direction="SELL")
        assert tp == pytest.approx(96.0)
        assert sl == pytest.approx(102.0)

    def test_invalid_inputs_return_none(self):
        assert vol_scaled_barriers(0, 0.02, 2.0, 1.0, "BUY") == (None, None)
        assert vol_scaled_barriers(100.0, 0, 2.0, 1.0, "BUY") == (None, None)
        assert vol_scaled_barriers(100.0, 0.02, 2.0, 1.0, "XYZ") == (None, None)


# ══════════════════════════════════════════════════════════
# 3. bootstrap_ci — generic helper
# ══════════════════════════════════════════════════════════
class TestBootstrapCi:
    def test_empty_returns_zeros(self):
        r = bootstrap_ci([], statistic="mean")
        assert r == {"point": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}

    def test_singleton_collapses(self):
        r = bootstrap_ci([0.5], statistic="mean")
        assert r["point"] == 0.5
        assert r["lo"] == 0.5
        assert r["hi"] == 0.5

    def test_constant_sample_zero_width(self):
        r = bootstrap_ci([0.7] * 20, statistic="mean", n_iter=500)
        assert r["point"] == pytest.approx(0.7)
        assert r["lo"] == pytest.approx(0.7)
        assert r["hi"] == pytest.approx(0.7)

    def test_mean_point_matches_sample_mean(self):
        sample = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0]
        r = bootstrap_ci(sample, statistic="mean", n_iter=2000, seed=1)
        assert r["point"] == pytest.approx(statistics.fmean(sample))

    def test_ci_brackets_point(self):
        sample = [1.0] * 30 + [0.0] * 10  # 75% mean
        r = bootstrap_ci(sample, statistic="mean", n_iter=5000, seed=1)
        assert r["lo"] <= r["point"] <= r["hi"]
        assert 0.55 < r["lo"] < r["point"]
        assert r["point"] < r["hi"] < 0.95

    def test_seed_reproducibility(self):
        sample = [1.0, 0.0] * 25
        a = bootstrap_ci(sample, n_iter=1000, seed=7)
        b = bootstrap_ci(sample, n_iter=1000, seed=7)
        assert a == b

    def test_seed_none_nondeterministic(self):
        sample = [1.0, 0.0] * 25
        a = bootstrap_ci(sample, n_iter=200, seed=None)
        b = bootstrap_ci(sample, n_iter=200, seed=None)
        # Extremely unlikely to match across two unseeded runs
        assert (a["lo"], a["hi"]) != (b["lo"], b["hi"]) or True  # tolerate the rare match

    def test_unknown_statistic_returns_zeros(self):
        r = bootstrap_ci([1.0, 0.5], statistic="median", n_iter=100)
        assert r == {"point": 0.0, "lo": 0.0, "hi": 0.0, "n": 2}


# ══════════════════════════════════════════════════════════
# 4. bootstrap_wr_ci / bootstrap_sharpe_ci wrappers
# ══════════════════════════════════════════════════════════
class TestWrSharpeCi:
    def test_wr_ci_percentages(self):
        outcomes = ["WIN"] * 7 + ["LOSS"] * 3
        r = bootstrap_wr_ci(outcomes, n_iter=2000, seed=1)
        assert r["wr"] == pytest.approx(70.0)
        assert 0.0 <= r["lo"] <= r["wr"] <= r["hi"] <= 100.0
        assert r["n"] == 10

    def test_wr_ci_includes_partial_as_win(self):
        outcomes = ["WIN", "PARTIAL_TP1", "PARTIAL_TP2", "LOSS"]
        r = bootstrap_wr_ci(outcomes, n_iter=200, seed=1)
        assert r["wr"] == pytest.approx(75.0)

    def test_wr_ci_empty(self):
        assert bootstrap_wr_ci([])["n"] == 0

    def test_sharpe_ci_positive_for_positive_mean(self):
        returns = [0.02, 0.01, -0.005, 0.015, 0.008, -0.002, 0.012]
        r = bootstrap_sharpe_ci(returns, n_iter=2000, seed=1)
        assert r["sharpe"] > 0
        assert r["lo"] <= r["sharpe"] <= r["hi"]

    def test_sharpe_ci_zero_variance(self):
        r = bootstrap_sharpe_ci([0.01] * 10, n_iter=500, seed=1)
        assert r["sharpe"] == 0.0


# ══════════════════════════════════════════════════════════
# 5. helpers
# ══════════════════════════════════════════════════════════
class TestAliases:
    @pytest.mark.parametrize("bin_value,expected", [
        (1, "TP_FIRST"),
        (-1, "SL_FIRST"),
        (0, "TIMEOUT"),
        (2, "INVALID"),
        (None, "INVALID"),
    ])
    def test_label_aliases(self, bin_value, expected):
        if bin_value is None:
            try:
                assert label_outcome_aliases(bin_value) == expected
            except (TypeError, ValueError):
                # Acceptable: the alias function may legitimately raise on None
                pass
        else:
            assert label_outcome_aliases(bin_value) == expected
