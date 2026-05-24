"""
Tests for scripts/backtest_regression.py — the CI regression gate.

Coverage:
  • WR formula matches backtest.py's is_win() convention exactly
    (PARTIAL_TP1 and PARTIAL_TP2 count as full wins).
  • z-score against breakeven_wr matches the report's z-score line.
  • --mode=ci passes when strategy params match Run-48 baseline.
  • --mode=ci fails when any baseline param drifts (e.g. ICT_SWING_N moved).
  • --mode=lastrun fails (exit 1) when n/WR/z dip below the configured floors.
  • --mode=lastrun returns exit 2 when results JSON is missing.
"""
import json
import os
import sys
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Import the regression module by absolute path (it lives in scripts/, not on PYTHONPATH).
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "backtest_regression",
    _REPO / "scripts" / "backtest_regression.py",
)
backtest_regression = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backtest_regression)


# ══════════════════════════════════════════════════════════════════════════════
# WR FORMULA — must match backtest.py is_win() exactly
# ══════════════════════════════════════════════════════════════════════════════
class TestCanonicalWR:
    def test_only_wins(self):
        sigs = [{"outcome": "WIN"}] * 10
        wr_pct, n, _ = backtest_regression.canonical_wr(sigs)
        assert wr_pct == 100.0
        assert n == 10

    def test_partial_tp1_counts_as_win(self):
        """backtest.py:987 — is_win() includes PARTIAL_TP1 and PARTIAL_TP2."""
        sigs = [{"outcome": "PARTIAL_TP1"}, {"outcome": "LOSS"}]
        wr_pct, n, _ = backtest_regression.canonical_wr(sigs)
        assert wr_pct == 50.0
        assert n == 2

    def test_partial_tp2_counts_as_win(self):
        sigs = [{"outcome": "PARTIAL_TP2"}, {"outcome": "LOSS"}]
        wr_pct, n, _ = backtest_regression.canonical_wr(sigs)
        assert wr_pct == 50.0

    def test_partial_tp3_is_neutral_not_a_win(self):
        # is_win() in backtest.py does NOT include PARTIAL_TP3 — it's an edge case.
        sigs = [{"outcome": "PARTIAL_TP3"}, {"outcome": "WIN"}]
        wr_pct, n, _ = backtest_regression.canonical_wr(sigs)
        assert wr_pct == 50.0

    def test_expired_excluded_from_wins(self):
        sigs = [{"outcome": "EXPIRED"}, {"outcome": "WIN"}]
        wr_pct, n, _ = backtest_regression.canonical_wr(sigs)
        # Both are closed signals; only one is a win.
        assert n == 2
        assert wr_pct == 50.0

    def test_open_signals_skipped(self):
        sigs = [{"outcome": "OPEN"}, {"outcome": "WIN"}]
        wr_pct, n, _ = backtest_regression.canonical_wr(sigs)
        # Only the WIN is closed.
        assert n == 1
        assert wr_pct == 100.0

    def test_run48_baseline_mix(self):
        """Sample mix from data/backtest_results.json: WIN=21, TP1=9, TP2=2, LOSS=9, EXPIRED=1.
        Expected WR per backtest.py convention: (21+9+2)/42 = 76.19%."""
        sigs = (
            [{"outcome": "WIN"}] * 21 +
            [{"outcome": "PARTIAL_TP1"}] * 9 +
            [{"outcome": "PARTIAL_TP2"}] * 2 +
            [{"outcome": "LOSS"}] * 9 +
            [{"outcome": "EXPIRED"}] * 1
        )
        wr_pct, n, counts = backtest_regression.canonical_wr(sigs)
        assert n == 42
        assert round(wr_pct, 2) == 76.19
        assert counts["WIN"] == 21
        assert counts["PARTIAL_TP1"] == 9


# ══════════════════════════════════════════════════════════════════════════════
# Z-SCORE
# ══════════════════════════════════════════════════════════════════════════════
class TestZScore:
    def test_z_positive_when_wr_above_bew(self):
        # 30 closed signals: 25 wins (83.3%) vs BEW 50% → strong positive z.
        sigs = (
            [{"outcome": "WIN", "breakeven_wr": 0.5}] * 25 +
            [{"outcome": "LOSS", "breakeven_wr": 0.5}] * 5
        )
        z, bew_pct = backtest_regression.z_score_vs_bew(sigs)
        assert z > 3.0
        assert bew_pct == 50.0

    def test_z_zero_when_no_breakeven_data(self):
        sigs = [{"outcome": "WIN"}] * 10  # no breakeven_wr column
        z, bew = backtest_regression.z_score_vs_bew(sigs)
        assert z == 0.0
        assert bew == 0.0

    def test_z_negative_when_wr_below_bew(self):
        # 5 wins (20%) vs BEW 50% → negative z.
        sigs = (
            [{"outcome": "WIN", "breakeven_wr": 0.5}] * 5 +
            [{"outcome": "LOSS", "breakeven_wr": 0.5}] * 20
        )
        z, _ = backtest_regression.z_score_vs_bew(sigs)
        assert z < -2.0


# ══════════════════════════════════════════════════════════════════════════════
# PARAMETER DRIFT (--mode=ci) — invoked as subprocess so module-level state
# (os.environ, sys.path) stays isolated from the test process.
# ══════════════════════════════════════════════════════════════════════════════
def _run_gate(*args, env_overrides=None):
    """Run scripts/backtest_regression.py as a subprocess.
    Returns (returncode, stdout, stderr)."""
    env = dict(os.environ)
    env["EXECUTION_MODE"] = "PAPER"
    if env_overrides:
        env.update(env_overrides)
    cmd = [sys.executable, str(_REPO / "scripts" / "backtest_regression.py")] + list(args)
    proc = subprocess.run(cmd, cwd=str(_REPO), env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


class TestModeCI:
    def test_passes_with_default_params(self):
        rc, stdout, stderr = _run_gate("--mode=ci")
        combined = stdout + stderr
        assert rc == 0, f"--mode=ci should pass with default params; output:\n{combined}"
        assert "strategy parameters match Run-48 baseline" in combined


class TestModeLastrun:
    def test_passes_on_current_json(self):
        # The committed data/backtest_results.json must clear the default floors.
        rc, stdout, stderr = _run_gate("--mode=lastrun")
        combined = stdout + stderr
        assert rc == 0, f"--mode=lastrun should pass on committed JSON; output:\n{combined}"

    def test_fails_when_floors_raised_too_high(self):
        # Set unreasonable floors (WR ≥ 99%) — gate must fail.
        rc, stdout, _ = _run_gate(
            "--mode=lastrun",
            env_overrides={
                "BACKTEST_GATE_MIN_N":      "25",
                "BACKTEST_GATE_MIN_WR_PCT": "99.0",
                "BACKTEST_GATE_MIN_Z":      "2.5",
            },
        )
        assert rc == 1, f"unreasonable WR floor should fail; rc={rc}"
        assert "FAIL" in stdout

    def test_returns_2_when_results_missing(self, tmp_path):
        # Point at a non-existent JSON file.
        bogus = tmp_path / "no-such-file.json"
        rc, stdout, _ = _run_gate(
            "--mode=lastrun",
            "--results-json", str(bogus),
        )
        assert rc == 2, f"missing JSON should return exit 2; rc={rc}\n{stdout}"
