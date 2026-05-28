"""
Tests for validation.py (Sprint 3 item 4 / Top-10 #5: CPCV + DSR).

Coverage:
  • CPCV index generator
      - Correct number of splits = C(K, k)
      - Train ∩ Test == ∅ for every split
      - Train ∪ Test ⊆ {0..n-1}
      - Purging removes training events whose label window overlaps test
      - Embargo removes training events too close in time after test block
      - Degenerate inputs handled (n < K, k > K)
  • Sharpe / PSR / DSR formulas
      - sharpe_ratio: known values
      - expected_max_sharpe: monotone in n_trials
      - PSR: increases with sample size for the same observed SR
      - DSR: lower than PSR when n_trials > 1
      - Selection-bias intuition: DSR penalises large n_trials
  • Full cpcv_summary integration
      - Returns expected schema
      - Verdict logic (PASS / MARGINAL / FAIL)
      - Insufficient-sample edge case
  • Text report contains required headers
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import validation as v


# ── CPCV index generator ──────────────────────────────────────────────────────

class TestCPCVIndexGenerator:

    def test_split_count_equals_combinations(self):
        # C(5, 2) = 10
        n = 50
        splits = list(v.combinatorial_purged_kfold(n, n_groups=5, n_test_groups=2,
                                                    embargo_pct=0))
        assert len(splits) == 10

    def test_no_train_test_overlap(self):
        n = 40
        for train, test in v.combinatorial_purged_kfold(n, n_groups=5,
                                                        n_test_groups=2,
                                                        embargo_pct=0):
            assert set(train).isdisjoint(set(test)), \
                f"train/test overlap: {set(train) & set(test)}"

    def test_indices_within_range(self):
        n = 30
        for train, test in v.combinatorial_purged_kfold(n, n_groups=5,
                                                        n_test_groups=2,
                                                        embargo_pct=0):
            for i in train + test:
                assert 0 <= i < n

    def test_test_size_predictable(self):
        # K=5, k=2 over n=50 → groups of 10 each, test set ≈ 20
        n = 50
        for train, test in v.combinatorial_purged_kfold(n, n_groups=5,
                                                        n_test_groups=2,
                                                        embargo_pct=0):
            assert len(test) == 20

    def test_small_sample_fallback(self):
        # n < n_groups → fallback to single 60/40 split
        n = 3
        splits = list(v.combinatorial_purged_kfold(n, n_groups=5, n_test_groups=2,
                                                    embargo_pct=0))
        assert len(splits) == 1
        train, test = splits[0]
        assert len(train) + len(test) == n

    def test_purging_removes_overlapping_train(self):
        # Train event with [t0=0, t1=15] overlaps test event with [t0=10, t1=20]
        # → must be purged.
        n = 10
        # All events at integer times 0..9 with label horizon = 5 bars
        t0 = list(range(n))
        t1 = [t + 5 for t in t0]
        all_splits = list(v.combinatorial_purged_kfold(
            n, n_groups=5, n_test_groups=1,
            t0=t0, t1=t1, embargo_pct=0
        ))
        # 5 single-group test splits
        assert len(all_splits) == 5
        for train, test in all_splits:
            # No training event's [t0, t1] should overlap any test [t0, t1]
            for i in train:
                for j in test:
                    overlap = t0[i] <= t1[j] and t0[j] <= t1[i]
                    assert not overlap, (
                        f"train index {i} [{t0[i]},{t1[i]}] overlaps "
                        f"test index {j} [{t0[j]},{t1[j]}]"
                    )

    def test_purging_keeps_non_overlapping(self):
        # Tight zero-length label windows (t0 == t1) → no purging needed
        n = 10
        t0 = list(range(n))
        t1 = list(range(n))
        for train, test in v.combinatorial_purged_kfold(
            n, n_groups=5, n_test_groups=1,
            t0=t0, t1=t1, embargo_pct=0
        ):
            assert len(train) + len(test) == n  # nothing purged

    def test_embargo_removes_train_after_test_block(self):
        # 20 events at times 0..19, embargo 10% = 1.9 time units.
        # If test = group {[8,9]}, training events with t0 in (9, 9+1.9] = {10,11}
        # must be removed.
        n = 20
        t0 = [float(i) for i in range(n)]
        t1 = list(t0)
        # Use n_groups=10, k=1 so groups are 2 elements each
        splits = list(v.combinatorial_purged_kfold(
            n, n_groups=10, n_test_groups=1,
            t0=t0, t1=t1, embargo_pct=0.10,
        ))
        # The split where test = group 4 (indices [8, 9]) — confirm
        for train, test in splits:
            if test == [8, 9]:
                # t0 at test end (index 9) = 9.0; embargo = 1.9 → forbidden t0 in (9, 10.9]
                # So indices 10 (t0=10) and 11 (t0=10.9? no t0=11.0 > 10.9 → kept)
                # Actually 10 falls in (9, 10.9] → excluded; 11 = 11.0 → kept
                assert 10 not in train, \
                    "embargo should have excluded index 10 (t0=10 within forbidden window)"
                break
        else:
            pytest.skip("no split with test=[8,9] generated — group balancing may differ")

    def test_zero_groups_returns_nothing(self):
        splits = list(v.combinatorial_purged_kfold(10, n_groups=0,
                                                    n_test_groups=1,
                                                    embargo_pct=0))
        # n < n_groups (0) — fallback yields one split
        assert len(splits) <= 1

    def test_k_greater_than_K_returns_empty(self):
        splits = list(v.combinatorial_purged_kfold(20, n_groups=5,
                                                    n_test_groups=6,
                                                    embargo_pct=0))
        assert splits == []


# ── Sharpe ratio ──────────────────────────────────────────────────────────────

class TestSharpeRatio:

    def test_sharpe_known_values(self):
        # Mean=0.10, std=0.20 → SR = 0.5 (no annualisation)
        returns = [0.10, 0.30, -0.10, 0.30, -0.10, 0.30, -0.10, 0.30, -0.10, 0.10]
        sr = v.sharpe_ratio(returns)
        mean = sum(returns) / len(returns)
        std = (sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
        assert math.isclose(sr, mean / std, rel_tol=1e-6)

    def test_sharpe_zero_std(self):
        assert v.sharpe_ratio([0.05, 0.05, 0.05]) == 0.0

    def test_sharpe_empty(self):
        assert v.sharpe_ratio([]) == 0.0

    def test_sharpe_single_value(self):
        assert v.sharpe_ratio([0.05]) == 0.0


# ── Expected max Sharpe ───────────────────────────────────────────────────────

class TestExpectedMaxSharpe:

    def test_monotone_in_n_trials(self):
        # More trials → higher expected max
        e1   = v.expected_max_sharpe(10,    1.0)
        e2   = v.expected_max_sharpe(100,   1.0)
        e3   = v.expected_max_sharpe(1000,  1.0)
        assert e1 < e2 < e3

    def test_scales_with_sr_std(self):
        e1 = v.expected_max_sharpe(100, 1.0)
        e2 = v.expected_max_sharpe(100, 2.0)
        assert math.isclose(e2, 2 * e1, rel_tol=1e-6)

    def test_zero_trials(self):
        assert v.expected_max_sharpe(0, 1.0) == 0.0
        assert v.expected_max_sharpe(1, 1.0) == 0.0  # single trial → no selection

    def test_zero_std(self):
        assert v.expected_max_sharpe(100, 0.0) == 0.0

    def test_n_100_sr_std_1_matches_known_approx(self):
        # For N=100, sr_std=1: gamma ≈ 0.5772
        # p_a = 1 - 1/100 = 0.99 → Z⁻¹(0.99) ≈ 2.3263
        # p_b = 1 - 1/(100*e) ≈ 1 - 0.00368 = 0.99632 → Z⁻¹(0.99632) ≈ 2.683
        # E[max] = 1.0 × ((1-0.5772)·2.3263 + 0.5772·2.683)
        #        = 0.4228·2.3263 + 0.5772·2.683
        #        ≈ 0.9836 + 1.549
        #        ≈ 2.53
        result = v.expected_max_sharpe(100, 1.0)
        assert 2.4 < result < 2.7, f"E[max SR] for N=100 should be ~2.53, got {result:.3f}"


# ── PSR ───────────────────────────────────────────────────────────────────────

class TestPSR:

    def test_psr_at_benchmark_is_50pct(self):
        # SR_observed == SR_benchmark → z=0 → Φ(0)=0.5
        psr = v.probabilistic_sharpe_ratio(sr_observed=1.0, n_returns=100,
                                            sr_benchmark=1.0)
        assert math.isclose(psr, 0.5, abs_tol=1e-6)

    def test_psr_above_benchmark_gt_50pct(self):
        psr = v.probabilistic_sharpe_ratio(sr_observed=2.0, n_returns=100,
                                            sr_benchmark=0.0)
        assert psr > 0.5

    def test_psr_below_benchmark_lt_50pct(self):
        psr = v.probabilistic_sharpe_ratio(sr_observed=0.0, n_returns=100,
                                            sr_benchmark=1.0)
        assert psr < 0.5

    def test_psr_increases_with_sample_size(self):
        # Same SR, more observations → more confidence → higher PSR
        psr_small = v.probabilistic_sharpe_ratio(sr_observed=1.0, n_returns=30,
                                                  sr_benchmark=0.0)
        psr_large = v.probabilistic_sharpe_ratio(sr_observed=1.0, n_returns=300,
                                                  sr_benchmark=0.0)
        assert psr_large > psr_small

    def test_psr_degenerate_returns_half(self):
        assert v.probabilistic_sharpe_ratio(1.0, n_returns=0) == 0.5
        assert v.probabilistic_sharpe_ratio(1.0, n_returns=1) == 0.5


# ── DSR ───────────────────────────────────────────────────────────────────────

class TestDSR:

    def test_dsr_lower_than_psr_when_many_trials(self):
        # With n_trials >> 1, benchmark > 0 → DSR < PSR vs SR=0
        psr = v.probabilistic_sharpe_ratio(sr_observed=2.0, n_returns=100,
                                            sr_benchmark=0.0)
        dsr = v.deflated_sharpe_ratio(sr_observed=2.0, n_returns=100,
                                       n_trials=100, sr_trial_std=1.0)
        assert dsr < psr, \
            f"DSR ({dsr:.4f}) should be lower than PSR ({psr:.4f}) with selection bias"

    def test_dsr_higher_observed_sr_higher_dsr(self):
        # All else equal, higher observed SR → higher DSR
        dsr_low  = v.deflated_sharpe_ratio(1.5, n_returns=100,
                                            n_trials=50, sr_trial_std=1.0)
        dsr_high = v.deflated_sharpe_ratio(3.0, n_returns=100,
                                            n_trials=50, sr_trial_std=1.0)
        assert dsr_high > dsr_low

    def test_dsr_more_trials_lower_dsr(self):
        # Same observed SR, more trials → DSR drops (multiple-testing penalty)
        dsr_few  = v.deflated_sharpe_ratio(2.0, n_returns=100,
                                            n_trials=10, sr_trial_std=1.0)
        dsr_many = v.deflated_sharpe_ratio(2.0, n_returns=100,
                                            n_trials=1000, sr_trial_std=1.0)
        assert dsr_many < dsr_few


# ── cpcv_summary integration ──────────────────────────────────────────────────

def _make_signal(ts: str, outcome: str, tp1=2.5, sl=-1.5, tp2=4.0, tp3=6.0
                 ) -> dict:
    return {
        "ts": ts,
        "outcome": outcome,
        "closed_at": ts,
        "net_tp1_pct": tp1,
        "net_sl_pct": sl,
        "net_tp2_pct": tp2,
        "net_tp3_pct": tp3,
        "breakeven_wr": 0.45,
    }


def _make_signals_stream(n: int, outcomes: list[str]) -> list[dict]:
    """Build n signals at evenly spaced timestamps. outcomes cycles through."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    sigs = []
    for i in range(n):
        ts = (base + timedelta(hours=i * 6)).strftime("%Y-%m-%d %H:%M:%S")
        sigs.append(_make_signal(ts, outcomes[i % len(outcomes)]))
    return sigs


class TestCPCVSummary:

    def test_empty_signals(self):
        out = v.cpcv_summary([])
        assert out["n_signals"] == 0
        assert out["verdict"] == "INSUFFICIENT_SAMPLE"

    def test_returns_required_schema(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS", "PARTIAL_TP1"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        for key in ("n_signals", "n_splits", "wr_mean", "wr_std",
                    "sharpe_mean", "sharpe_std", "psr", "verdict",
                    "wr_per_split", "sharpe_per_split", "splits"):
            assert key in out

    def test_perfect_wins_verdict_pass(self):
        sigs = _make_signals_stream(40, ["WIN"])  # 100% WR
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        assert out["wr_mean"] == 100.0
        # M-5 fix (cycle-9 audit 2026-05-28): the C-B verdict cap (cycle-2)
        # downgrades PASS → MARGINAL when DSR isn't honestly computed
        # (no n_trials_for_dsr supplied → within-fold proxy used). 100%-WR
        # streams correctly land on MARGINAL under that cap. Relaxed to
        # accept either non-FAIL verdict — intent preserved.
        assert out["verdict"] in ("PASS", "MARGINAL")

    def test_all_losses_verdict_fail(self):
        sigs = _make_signals_stream(40, ["LOSS"])  # 0% WR
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        assert out["wr_mean"] == 0.0
        assert out["verdict"] == "FAIL"

    def test_n_splits_matches_combinations(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        # C(5,2) = 10
        assert out["n_splits"] == 10
        assert len(out["wr_per_split"]) == 10

    def test_dsr_computed_when_n_trials_supplied(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS", "WIN"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2,
                              n_trials_for_dsr=50)
        assert out["dsr"] is not None or out.get("dsr_note") is not None

    def test_dsr_none_when_n_trials_omitted(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS", "WIN"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        assert out["dsr"] is None

    def test_train_test_size_balance_with_purging(self):
        """When closed_at == ts, the median-horizon fallback (Fix #6) applies a
        24h label window so some purging at split boundaries is EXPECTED.
        _make_signals_stream spaces events 6h apart, so a 24h horizon purges
        roughly 4 events on each side of each test-group boundary (≈16 events
        total for k=2 test groups of K=5). Verify it stays bounded above 60%."""
        n = 50
        sigs = _make_signals_stream(n, ["WIN", "LOSS"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2, embargo_pct=0.0)
        for split in out["splits"]:
            total = split["n_train"] + split["n_test"]
            assert total >= int(n * 0.60), \
                f"split lost too many events to purging: {total}/{n}"
            assert total <= n  # never double-count

    def test_no_purging_when_label_windows_zero(self):
        """If we explicitly pass non-overlapping closed_at = ts windows AND
        all durations are zero (all valid_durations empty), Fix #6 still
        applies the 24h default. To get NO purging, the test events must be
        sparse enough that 24h horizons don't overlap. Spacing them 48h apart
        guarantees no overlap."""
        from datetime import datetime, timezone, timedelta
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        # 48h spacing so 24h label windows do not touch
        sigs = []
        for i in range(50):
            ts = (base + timedelta(hours=i * 48)).strftime("%Y-%m-%d %H:%M:%S")
            sigs.append(_make_signal(ts, "WIN" if i % 2 else "LOSS"))
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2, embargo_pct=0.0)
        for split in out["splits"]:
            # With 48h spacing and 24h horizon, only adjacent events at the
            # train/test boundary could be purged — at most 2 per split.
            total = split["n_train"] + split["n_test"]
            assert total >= 48, f"expected >=48, got {total}"


# ── Text report ───────────────────────────────────────────────────────────────

class TestVerdictGate:
    """Per backtest-bias-detector audit Fix #3: MARGINAL must enforce DSR gate."""

    def test_marginal_blocked_by_failing_dsr(self):
        # Construct a summary manually so we can force DSR=0.0 < 0.95
        # Strategy: 56% WR (above MARGINAL floor of 55%) but DSR fails.
        sigs = _make_signals_stream(50, ["WIN", "WIN", "WIN", "WIN", "WIN",
                                          "LOSS", "LOSS", "LOSS", "LOSS"])
        # 5/9 = 55.6% WR per cycle ≈ in MARGINAL band
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2,
                              n_trials_for_dsr=10_000)  # large N forces low DSR
        # DSR should be very low with 10k trials; MARGINAL must NOT trigger
        # when dsr < 0.95
        if out["dsr"] is not None and out["dsr"] < 0.95:
            assert out["verdict"] == "FAIL", (
                f"WR={out['wr_mean']:.1f}% DSR={out['dsr']:.3f} — "
                f"MARGINAL must be blocked by DSR gate, got {out['verdict']}"
            )

    def test_pass_requires_both_wr_and_dsr(self):
        # C-B fix (audit 2026-05-25): when DSR is None (no honest cross-config
        # std + n_trials_for_dsr default), the verdict is capped at MARGINAL —
        # PASS now requires dsr_present AND dsr >= 0.95. This protects against
        # selection-bias-uncorrected configs slipping through as PASS.
        sigs = _make_signals_stream(40, ["WIN"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        assert out["dsr"] is None
        assert out["verdict"] == "MARGINAL", (
            f"DSR=None must cap verdict at MARGINAL (C-B fix); got {out['verdict']}"
        )
        assert out["dsr_gate_applied"] is False


class TestOOSPSR:
    """Per audit Fix #5: PSR must be reported on both in-sample and CPCV-OOS."""

    def test_summary_has_both_psr_values(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS", "WIN", "WIN"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        assert "psr_is" in out
        assert "psr_oos" in out
        # Back-compat alias points to the OOS one
        assert out["psr"] == out["psr_oos"]


class TestProxyWarning:
    """Per audit Fix #2: dsr_proxy_used flag must be set when std is auto-estimated."""

    def test_proxy_flag_set_when_std_omitted(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2,
                              n_trials_for_dsr=50)
        if out["dsr"] is not None:
            assert out["dsr_proxy_used"] is True
            assert "ANTI-CONSERVATIVE" in out.get("dsr_note", "")

    def test_proxy_flag_unset_when_std_supplied(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2,
                              n_trials_for_dsr=50,
                              sr_trial_std_for_dsr=0.5)
        if out["dsr"] is not None:
            assert out["dsr_proxy_used"] is False


class TestLabelWindowFallback:
    """Per audit Fix #6: missing closed_at must NOT silently disable purging."""

    def test_default_horizon_applied_when_closed_at_missing(self):
        # All signals with closed_at == ts (zero-length window).
        # The Fix #6 fallback should apply a 24h default horizon so purging
        # is not silently disabled.
        from datetime import datetime, timezone, timedelta
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        # Tight 30min spacing — 24h label windows will heavily overlap.
        sigs = []
        for i in range(40):
            ts = (base + timedelta(minutes=i * 30)).strftime("%Y-%m-%d %H:%M:%S")
            s = _make_signal(ts, "WIN" if i % 2 else "LOSS")
            sigs.append(s)
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2, embargo_pct=0.0)
        # With 30min spacing × 40 events = 20h span < 24h default horizon →
        # every train event overlaps every test event → train fully purged
        # OR at minimum a substantial fraction must be purged.
        purged_any = any(split["n_train"] < 32 for split in out["splits"])
        assert purged_any, (
            "Fix #6 broken: missing closed_at left label window zero-length, "
            "purging silently disabled"
        )


class TestTextReport:

    def test_text_report_has_required_sections(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS", "PARTIAL_TP1"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        text = v.cpcv_text_report(out)
        for hdr in ("HONEST METRICS - CPCV", "WR (CPCV)",
                    "Sharpe (CPCV)", "PSR (in-sample)",
                    "PSR (OOS CPCV)", "VERDICT"):
            assert hdr in text

    def test_text_report_with_dsr_shows_n_trials(self):
        sigs = _make_signals_stream(40, ["WIN", "LOSS"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2,
                              n_trials_for_dsr=42)
        text = v.cpcv_text_report(out)
        assert "DSR" in text


# ── Realism check: known CPCV behaviour on synthetic edge case ───────────────

class TestRealismChecks:

    def test_random_50pct_wr_dsr_near_50pct(self):
        """A coin-flip strategy with no edge should not pass DSR."""
        # 50/50 split — half wins, half losses, alternating
        sigs = _make_signals_stream(40, ["WIN", "LOSS"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2,
                              n_trials_for_dsr=50)
        # WR ≈ 50% so verdict should NOT be PASS
        assert out["verdict"] in ("MARGINAL", "FAIL")

    def test_strong_edge_passes(self):
        # 4 wins per loss → 80% WR
        sigs = _make_signals_stream(40, ["WIN", "WIN", "WIN", "WIN", "LOSS"])
        out = v.cpcv_summary(sigs, n_groups=5, n_test_groups=2)
        assert out["wr_mean"] >= 70.0
        # M-5 fix (cycle-9 audit 2026-05-28): see test_perfect_wins_verdict_pass.
        # 80%-WR streams land on MARGINAL under the C-B verdict cap when DSR
        # isn't honestly computed. Intent (non-FAIL on strong edge) preserved.
        assert out["verdict"] in ("PASS", "MARGINAL")
