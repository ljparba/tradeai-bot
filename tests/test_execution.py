"""Tests for execution.py (Phase A.1 of LIVE_BACKTEST_PARITY_ROADMAP).

Coverage:
  - Determinism: same seed always produces same result
  - Each of the 5 friction components individually:
      1. Spread time-of-day + vol multipliers
      2. Latency distribution
      3. Partial fill / no fill probabilities
      4. Stale-price reject
      5. Adverse selection (TRENDING regimes only)
  - Env-var override mechanism
  - Buy/sell symmetry
  - Edge cases (NaN price, invalid direction, etc.)

Acceptance: all 15+ tests must pass. Test framework is stdlib unittest +
pytest-compatible (per `tests/test_validation.py` convention in this repo).
"""
from __future__ import annotations

import math
import os
import unittest
from datetime import datetime, timezone
from importlib import reload

# Import the module under test
import execution


# ── Helpers ─────────────────────────────────────────────────────────────────

def _ts(hour_utc: int = 12) -> datetime:
    """Build a fixed datetime at the given UTC hour for tests."""
    return datetime(2026, 5, 25, hour_utc, 30, 0, tzinfo=timezone.utc)


def _call(**overrides) -> execution.ExecutionResult:
    """Default ``simulate_execution`` call with optional overrides."""
    defaults = dict(
        signal_ts=_ts(),
        signal_price=100.0,
        next_bar_open=100.0,
        token="BTC",
        direction="BUY",
        regime="RANGING",
        atr_5m=0.5,
        atr_ratio=1.0,
        seed=42,
    )
    defaults.update(overrides)
    return execution.simulate_execution(**defaults)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestDeterminism(unittest.TestCase):
    """The execution model MUST be deterministic given (inputs, seed) — this
    is what makes backtests reproducible + Optuna trials independent."""

    def test_same_seed_same_result(self):
        r1 = _call(seed=12345)
        r2 = _call(seed=12345)
        self.assertEqual(r1, r2)

    def test_different_seeds_diverge(self):
        results = {_call(seed=s) for s in range(50)}
        # 50 unique seeds should produce >5 distinct ExecutionResult tuples
        # (different latencies, occasional partials, etc.)
        self.assertGreater(len(results), 5)

    def test_derive_seed_deterministic(self):
        ts = _ts()
        s1 = execution.derive_seed(ts, "BTC", "BUY")
        s2 = execution.derive_seed(ts, "BTC", "BUY")
        self.assertEqual(s1, s2)

    def test_derive_seed_differs_by_inputs(self):
        ts = _ts()
        # Different inputs should map to different seeds (collisions are rare
        # but possible; we accept >=2/3 distinct as a probabilistic check)
        seeds = {
            execution.derive_seed(ts, "BTC", "BUY"),
            execution.derive_seed(ts, "BTC", "SELL"),
            execution.derive_seed(ts, "ETH", "BUY"),
        }
        self.assertGreaterEqual(len(seeds), 2)


class TestNoFillProbability(unittest.TestCase):
    """About 2% of signals should result in REJECTED with reason=no_fill."""

    def test_no_fill_rate_approximately_2pct(self):
        n_no_fill = 0
        n_trials = 5000
        for s in range(n_trials):
            r = _call(seed=s, signal_price=100.0, next_bar_open=100.0, atr_5m=1000.0)
            # atr_5m is huge so stale-reject never triggers — isolates no_fill
            if r.status == "REJECTED" and r.reason == "no_fill":
                n_no_fill += 1
        rate = n_no_fill / n_trials
        self.assertAlmostEqual(rate, execution.NO_FILL_PROB, delta=0.01)


class TestPartialFillProbability(unittest.TestCase):
    """About 5% of FILLED+PARTIAL signals should be PARTIAL at 50% size."""

    def test_partial_rate_approximately_5pct(self):
        n_partial = 0
        n_trials = 5000
        for s in range(n_trials):
            r = _call(seed=s, signal_price=100.0, next_bar_open=100.0, atr_5m=1000.0)
            if r.status == "PARTIAL":
                n_partial += 1
        rate = n_partial / n_trials
        self.assertAlmostEqual(rate, execution.PARTIAL_FILL_PROB, delta=0.01)

    def test_partial_fill_size_is_half(self):
        # Force a partial: find one across many seeds
        for s in range(10000):
            r = _call(seed=s, atr_5m=1000.0)
            if r.status == "PARTIAL":
                self.assertEqual(r.fill_size_pct, 0.5)
                return
        self.fail("No PARTIAL found in 10000 trials — probability too low?")


class TestLatencyDistribution(unittest.TestCase):
    """Latency should be ~truncated-normal(mu=12, sigma=8), clamped [3, 60]."""

    def test_latency_mean(self):
        latencies = [_call(seed=s).latency_sec for s in range(5000)]
        mean = sum(latencies) / len(latencies)
        # Mean of TRUNCATED Gaussian is slightly different from theoretical mu;
        # accept anything within 1s of the configured mu
        self.assertAlmostEqual(mean, execution.LATENCY_MEAN_SEC, delta=1.5)

    def test_latency_bounds(self):
        for s in range(5000):
            r = _call(seed=s)
            self.assertGreaterEqual(r.latency_sec, execution.LATENCY_MIN_SEC)
            self.assertLessEqual(r.latency_sec, execution.LATENCY_MAX_SEC)


class TestStaleReject(unittest.TestCase):
    """Large move between signal_price and next_bar_open should REJECT."""

    def test_large_move_triggers_stale_reject(self):
        # 5% price move with tiny ATR is way over the 1.5x threshold
        r = _call(seed=42, signal_price=100.0, next_bar_open=105.0, atr_5m=0.3)
        self.assertEqual(r.status, "REJECTED")
        self.assertEqual(r.reason, "stale_move")
        self.assertEqual(r.fill_size_pct, 0.0)
        self.assertTrue(math.isnan(r.fill_price))

    def test_small_move_no_reject(self):
        # Move smaller than 1.5x ATR — should fill normally
        r = _call(seed=42, signal_price=100.0, next_bar_open=100.5, atr_5m=1.0)
        self.assertIn(r.status, ("FILLED", "PARTIAL"))


class TestAdverseSelection(unittest.TestCase):
    """TRENDING regimes add +5bps; RANGING/other add 0bps."""

    def test_trending_bull_adds_5bps(self):
        r = _call(seed=42, regime="TRENDING_BULL", atr_5m=1000.0)
        r_ref = _call(seed=42, regime="RANGING", atr_5m=1000.0)
        # The two should differ by exactly ADVERSE_SELECT_COST in total_cost_pct
        # (everything else identical given the same seed + inputs)
        diff = r.total_cost_pct - r_ref.total_cost_pct
        self.assertAlmostEqual(diff, execution.ADVERSE_SELECT_COST, places=6)

    def test_trending_bear_also_adds_adverse(self):
        r = _call(seed=42, regime="TRENDING_BEAR", atr_5m=1000.0)
        r_ref = _call(seed=42, regime="RANGING", atr_5m=1000.0)
        diff = r.total_cost_pct - r_ref.total_cost_pct
        self.assertAlmostEqual(diff, execution.ADVERSE_SELECT_COST, places=6)

    def test_ranging_no_adverse(self):
        r = _call(seed=42, regime="RANGING", atr_5m=1000.0, atr_ratio=1.0)
        # Cost should equal pure spread (no adverse component)
        expected_spread = execution.effective_spread("BTC", _ts(), 1.0)
        self.assertAlmostEqual(r.total_cost_pct, expected_spread, places=6)


class TestSpreadVariability(unittest.TestCase):
    """Spread varies by hour-of-day + vol regime."""

    def test_asia_early_higher_than_active(self):
        s_asia   = execution.effective_spread("BTC", _ts(hour_utc=2),  1.0)
        s_active = execution.effective_spread("BTC", _ts(hour_utc=12), 1.0)
        self.assertGreater(s_asia, s_active)

    def test_overnight_between_asia_and_active(self):
        s_overnight = execution.effective_spread("BTC", _ts(hour_utc=22), 1.0)
        s_active    = execution.effective_spread("BTC", _ts(hour_utc=12), 1.0)
        self.assertGreater(s_overnight, s_active)

    def test_high_vol_widens_spread(self):
        s_normal = execution.effective_spread("BTC", _ts(hour_utc=12), 1.0)
        s_high   = execution.effective_spread("BTC", _ts(hour_utc=12), 2.5)
        self.assertGreater(s_high, s_normal)

    def test_med_vol_widens_modestly(self):
        s_normal = execution.effective_spread("BTC", _ts(hour_utc=12), 1.0)
        s_med    = execution.effective_spread("BTC", _ts(hour_utc=12), 1.6)
        self.assertGreater(s_med, s_normal)
        s_high   = execution.effective_spread("BTC", _ts(hour_utc=12), 2.5)
        self.assertLess(s_med, s_high)


class TestEnvVarOverride(unittest.TestCase):
    """Env vars must override module defaults after reload."""

    def test_override_latency_mean(self):
        # Save current value
        prev = execution.LATENCY_MEAN_SEC
        try:
            os.environ["EXEC_LATENCY_MEAN_SEC"] = "30.0"
            reload(execution)
            self.assertEqual(execution.LATENCY_MEAN_SEC, 30.0)
        finally:
            os.environ.pop("EXEC_LATENCY_MEAN_SEC", None)
            reload(execution)
            self.assertEqual(execution.LATENCY_MEAN_SEC, prev)

    def test_override_partial_fill_prob(self):
        prev = execution.PARTIAL_FILL_PROB
        try:
            os.environ["EXEC_PARTIAL_FILL_PROB"] = "0.20"
            reload(execution)
            self.assertEqual(execution.PARTIAL_FILL_PROB, 0.20)
        finally:
            os.environ.pop("EXEC_PARTIAL_FILL_PROB", None)
            reload(execution)
            self.assertEqual(execution.PARTIAL_FILL_PROB, prev)


class TestBuySellSymmetry(unittest.TestCase):
    """Slip should be equal magnitude in both directions, just opposite sign."""

    def test_slip_symmetric(self):
        r_buy  = _call(seed=42, direction="BUY",  signal_price=100.0,
                       next_bar_open=100.0, atr_5m=1000.0)
        r_sell = _call(seed=42, direction="SELL", signal_price=100.0,
                       next_bar_open=100.0, atr_5m=1000.0)
        # Both same seed → same latency → same slip magnitude, opposite sign
        if r_buy.status != "REJECTED" and r_sell.status != "REJECTED":
            diff_buy  = r_buy.fill_price  - 100.0     # positive (adverse)
            diff_sell = 100.0 - r_sell.fill_price     # positive (adverse)
            self.assertAlmostEqual(diff_buy, diff_sell, places=6)


class TestEdgeCases(unittest.TestCase):
    """Defensive checks."""

    def test_invalid_direction_raises(self):
        with self.assertRaises(ValueError):
            _call(direction="LONG")

    def test_zero_price_raises(self):
        with self.assertRaises(ValueError):
            _call(signal_price=0.0)

    def test_negative_atr_raises(self):
        with self.assertRaises(ValueError):
            _call(atr_5m=-1.0)

    def test_status_values_constrained(self):
        for s in range(200):
            r = _call(seed=s)
            self.assertIn(r.status, ("FILLED", "PARTIAL", "REJECTED"))

    def test_reasons_documented(self):
        for s in range(500):
            r = _call(seed=s, atr_5m=1000.0)
            self.assertIn(r.reason, ("ok", "no_fill", "stale_move"))

    def test_full_fill_size_is_one(self):
        for s in range(500):
            r = _call(seed=s, atr_5m=1000.0)
            if r.status == "FILLED":
                self.assertEqual(r.fill_size_pct, 1.0)


class TestConfigSnapshot(unittest.TestCase):
    """`current_config()` should return all active knobs."""

    def test_current_config_returns_all_knobs(self):
        cfg = execution.current_config()
        required_keys = {
            "LATENCY_MEAN_SEC", "LATENCY_STD_SEC", "LATENCY_MIN_SEC", "LATENCY_MAX_SEC",
            "PARTIAL_FILL_PROB", "NO_FILL_PROB",
            "STALE_ATR_MULT", "ADVERSE_SELECT_COST",
            "TIME_MULT_ASIA_EARLY", "TIME_MULT_OVERNIGHT", "TIME_MULT_ACTIVE",
            "VOL_MULT_HIGH", "VOL_MULT_MED", "VOL_MULT_NORMAL",
            "LATENCY_SLIP_PER_30S",
        }
        self.assertEqual(set(cfg.keys()), required_keys)


class TestPureFunction(unittest.TestCase):
    """simulate_execution must not modify any global state."""

    def test_no_module_state_mutation(self):
        cfg_before = execution.current_config()
        for s in range(100):
            _call(seed=s)
        cfg_after = execution.current_config()
        self.assertEqual(cfg_before, cfg_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
