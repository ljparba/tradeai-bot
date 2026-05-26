"""
Tests for walk_forward.py — Phase C WFV + held-out lockbox.

Uses unittest (not pytest — pytest not installed on the VPS per the
2026-05-25 audit footnote). Run with:
    python3 -m unittest tests.test_walk_forward -v
"""

import unittest
from datetime import datetime, timedelta, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import walk_forward as wf  # noqa: E402


def _make_signals(n: int, pattern: list, *, start=None, hours_apart: int = 6) -> list:
    """Build n synthetic signals with deterministic timestamps + outcomes."""
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        outcome = pattern[i % len(pattern)]
        out.append({
            "ts":      (start + timedelta(hours=i * hours_apart)).isoformat(),
            "outcome": outcome,
            "realized_r": 1.5 if outcome in ("WIN", "PARTIAL_TP1", "PARTIAL_TP2") else -1.0,
        })
    return out


class TestWalkForwardBasic(unittest.TestCase):

    def test_empty_signals_returns_insufficient(self):
        out = wf.walk_forward([], n_windows=12)
        self.assertEqual(out["verdict"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(out["n_signals"], 0)

    def test_stationary_wr_no_decay(self):
        # 200 signals with 70% WR throughout — no decay
        sigs = _make_signals(200, ["WIN"] * 7 + ["LOSS"] * 3)
        out = wf.walk_forward(sigs, n_windows=10, min_train_signals=5)
        self.assertGreaterEqual(out["n_valid_windows"], 5)
        self.assertFalse(out["decay_detected"], "stationary WR should not trigger decay flag")
        self.assertEqual(out["verdict"], "ROBUST")
        self.assertAlmostEqual(out["test_wr_mean"], 70.0, delta=15.0)

    def test_decay_detected_when_wr_falls(self):
        # First half all-WIN, second half all-LOSS → strong decay
        sigs = _make_signals(100, ["WIN"]) + _make_signals(100, ["LOSS"],
            start=datetime(2024, 4, 1, tzinfo=timezone.utc))
        out = wf.walk_forward(sigs, n_windows=10, min_train_signals=5,
                              decay_threshold_pp=10.0)
        self.assertTrue(out["decay_detected"], f"slope={out['decay_slope_pp']}")
        self.assertEqual(out["verdict"], "DECAYING")
        self.assertLess(out["decay_slope_pp"], 0.0)


class TestWalkForwardMinTrain(unittest.TestCase):

    def test_insufficient_train_flags_windows(self):
        sigs = _make_signals(20, ["WIN", "LOSS"], hours_apart=24)
        out = wf.walk_forward(sigs, n_windows=12, min_train_signals=50)
        # Almost every window's train will be < 50 → most flagged insufficient
        n_insufficient = sum(1 for w in out["windows"] if w["insufficient_train"])
        self.assertGreater(n_insufficient, 5)

    def test_n_valid_windows_excludes_insufficient(self):
        sigs = _make_signals(30, ["WIN"])
        out = wf.walk_forward(sigs, n_windows=6, min_train_signals=10)
        # Sum of valid_windows + insufficient_windows must equal n_windows - 1
        # (first index 0 is skipped because train empty)
        total = sum(1 for w in out["windows"])
        self.assertEqual(total, 5)  # n_windows-1 = 5
        self.assertLessEqual(out["n_valid_windows"], 5)


class TestSplitHeldOut(unittest.TestCase):

    def test_zero_held_out_days_returns_all_as_tuning(self):
        sigs = _make_signals(10, ["WIN"])
        split = wf.split_held_out(sigs, held_out_days=0)
        self.assertEqual(len(split["tuning"]), 10)
        self.assertEqual(len(split["held_out"]), 0)

    def test_held_out_takes_chronologically_last_signals(self):
        # 100 signals spaced 1 day apart, ending today
        now = datetime.now(timezone.utc)
        sigs = []
        for i in range(100):
            sigs.append({
                "ts": (now - timedelta(days=99 - i)).isoformat(),
                "outcome": "WIN",
            })
        split = wf.split_held_out(sigs, held_out_days=10, now_utc=now)
        # Held-out should contain ~last 10 days' worth
        self.assertGreaterEqual(len(split["held_out"]), 9)
        self.assertLessEqual(len(split["held_out"]), 11)
        # Cutoff iso must be ~10 days before now
        cutoff_dt = datetime.fromisoformat(split["cutoff_iso"])
        delta_days = (now - cutoff_dt).total_seconds() / 86400.0
        self.assertAlmostEqual(delta_days, 10.0, delta=0.1)


class TestHeldOutSummary(unittest.TestCase):

    def test_empty_held_out_is_insufficient(self):
        out = wf.held_out_summary([])
        self.assertEqual(out["verdict"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(out["n"], 0)

    def test_robust_verdict_high_wr_low_gap(self):
        # 80% WR over n=20, tuning_wr=78% → gap=2pp, robust
        sigs = _make_signals(20, ["WIN"] * 4 + ["LOSS"])  # 80%
        out = wf.held_out_summary(sigs, tuning_wr=78.0, max_gap_pp=8.0, min_wr_pct=58.0)
        self.assertEqual(out["wins"], 16)
        self.assertEqual(out["losses"], 4)
        self.assertAlmostEqual(out["wr_pct"], 80.0, delta=0.1)
        self.assertEqual(out["verdict"], "ROBUST")

    def test_overfit_verdict_when_low_wr(self):
        # 40% WR over n=20 → below 58% floor → OVERFIT
        sigs = _make_signals(20, ["WIN"] * 2 + ["LOSS"] * 3)  # 40%
        out = wf.held_out_summary(sigs, tuning_wr=80.0)
        self.assertEqual(out["verdict"], "OVERFIT")

    def test_borderline_verdict_when_gap_grows(self):
        # 60% WR, tuning=66% → gap=6pp (between max_gap/2 and max_gap)
        # 12 wins + 8 losses = 60%
        sigs = _make_signals(20, ["WIN"] * 3 + ["LOSS"] * 2)
        out = wf.held_out_summary(sigs, tuning_wr=66.0, max_gap_pp=8.0, min_wr_pct=58.0)
        self.assertEqual(out["verdict"], "BORDERLINE")

    def test_wilson_ci_brackets_wr(self):
        # 7/10 wins → 70%, Wilson CI should bracket 70 and have nontrivial width
        sigs = _make_signals(10, ["WIN"] * 7 + ["LOSS"] * 3, hours_apart=24)
        out = wf.held_out_summary(sigs)
        self.assertAlmostEqual(out["wr_pct"], 70.0, delta=0.1)
        self.assertLess(out["wilson_lo_pct"], 70.0)
        self.assertGreater(out["wilson_hi_pct"], 70.0)
        # CI width should be substantial at n=10
        self.assertGreater(out["wilson_hi_pct"] - out["wilson_lo_pct"], 20.0)


if __name__ == "__main__":
    unittest.main()
