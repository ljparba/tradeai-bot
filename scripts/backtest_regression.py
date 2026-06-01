"""
TradeAI — Backtest Regression Gate
====================================
Phase A roadmap item #4 (and Audit Adopt 3 sub-item per ROADMAP_AUDIT_CROSSCHECK.md
§"Soft Overlaps") — fail merges that regress the backtest baseline.

Baseline reference: post-A-9 / Run-60-equivalent.
    n_signals = 37     (≥25 acceptable — frequency floor)
    WR        = 81.1%  (≥WR_FLOOR — quality floor)
    z-score   = +4.15  (≥Z_FLOOR  — statistical significance floor)

Run modes
---------
  --mode=full    Fetch fresh candles + run full backtest, then verify metrics.
                 Requires Binance access (VPN if in restricted jurisdictions).
                 Use locally before opening a PR.
  --mode=lastrun Read data/backtest_results.json (last completed backtest's
                 signal list) and verify the recorded metrics. No network.
  --mode=ci      No backtest run, no JSON read. Only verifies that strategy
                 PARAMETER values match the Run-48 baseline (CI-safe).

Exit codes
----------
  0   All baseline thresholds met.
  1   Regression detected.
  2   Missing inputs (no backtest_results.json in --mode=lastrun).

Override thresholds via env (defaults shown):
  BACKTEST_GATE_MIN_N       = 25
  BACKTEST_GATE_MIN_WR_PCT  = 72.0
  BACKTEST_GATE_MIN_Z       = 2.5

Acceptance: when run against the current data/backtest_results.json (or a
fresh full backtest preserving Run-48 logic), this script exits 0.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

# Make `import secrets_loader, config` work from any cwd.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── BASELINE (Run-48 post-A-9 reference) ──────────────────────────────────────
# These are the FLOORS — actual baseline numbers are higher. Crossing below any
# floor is a regression. Tune the floors via env vars; the burn-in defaults are
# ~10pp below the actual Run-48 baseline, which catches major regressions while
# tolerating the per-run stochasticity that an ICT model with n≈30-40 signals
# inherently has.
_DEFAULT_MIN_N      = int(os.environ.get("BACKTEST_GATE_MIN_N",     "25"))
_DEFAULT_MIN_WR_PCT = float(os.environ.get("BACKTEST_GATE_MIN_WR_PCT", "72.0"))
_DEFAULT_MIN_Z      = float(os.environ.get("BACKTEST_GATE_MIN_Z",   "2.5"))

# Expected strategy parameter values (Run-48 baseline). Mode `--mode=ci` checks
# these without running a backtest — guards against parameter drift from PRs
# that touch config.py or backtest.py.
_EXPECTED_PARAMS: Dict[str, Any] = {
    "BACKTEST_DAYS":   730,   # Fix #38 (2026-05-22 cycle 13): bumped 365→730 for rolling-WF stability
    # COOLDOWN_BARS removed from fixed-expectation guard (cycle-15-loop, 2026-05-30):
    # backtest.py:265 now derives COOLDOWN_BARS from SIGNAL_COOLDOWN env to match live cadence.
    # The value legitimately varies with the operator's pin choice — it is no longer
    # a fixed constant to drift-guard against. Live↔BT cadence is now enforced
    # structurally rather than via a stale numeric snapshot here.
    "ENTRY_WINDOW":    72,
    "ICT_SWING_N":     2,
    "MIN_TP1_MULT":    1.5,
    "MIN_SL_PCT":      0.005,
    "MAX_SL_PCT":      0.030,
    # 9 tokens — SOL excluded T-1.
    "BINANCE_TOKEN_KEYS": ("BTC", "ETH", "XRP", "HBAR", "AVAX", "LINK", "BNB", "ADA", "POL"),
}


# ── WR convention — MUST match backtest.py is_win() / wr() exactly ────────────
# backtest.py:987 — PARTIAL_TP1 and PARTIAL_TP2 are FULL wins (not half-credit).
# tracker.py's canonical_wr uses 0.5 for partials — different convention used
# for live PnL display. The CI gate uses the backtest convention so the report
# numbers in project_state.md (WR=81.1%) match what the gate reads.
_WIN_OUTCOMES     = {"WIN", "PARTIAL_TP1", "PARTIAL_TP2"}
_PARTIAL_OUTCOMES = {"PARTIAL", "PARTIAL_TP3"}  # buckets we count separately but not as wins
_LOSS_OUTCOMES    = {"LOSS"}
_EXPIRED_OUTCOMES = {"EXPIRED"}
_ALL_CLOSED       = _WIN_OUTCOMES | _PARTIAL_OUTCOMES | _LOSS_OUTCOMES | _EXPIRED_OUTCOMES


def canonical_wr(signals: List[Dict[str, Any]]) -> Tuple[float, int, Dict[str, int]]:
    """Compute WR% using backtest.py's is_win() convention exactly.
    Returns (wr_pct, n_closed, breakdown). PARTIAL_TP1/TP2 count as full wins."""
    counts: Dict[str, int] = {
        "WIN": 0, "PARTIAL_TP1": 0, "PARTIAL_TP2": 0,
        "PARTIAL_TP3": 0, "LOSS": 0, "EXPIRED": 0, "OPEN": 0,
    }
    wins = 0
    n_closed = 0
    for sig in signals:
        out = (sig.get("outcome") or "").upper()
        if out in counts:
            counts[out] += 1
        if out in _ALL_CLOSED:
            n_closed += 1
            if out in _WIN_OUTCOMES:
                wins += 1
        elif out not in counts:
            counts["OPEN"] += 1
    if n_closed == 0:
        return 0.0, 0, counts
    return (wins / n_closed) * 100.0, n_closed, counts


def z_score_vs_bew(signals: List[Dict[str, Any]]) -> Tuple[float, float]:
    """One-proportion z-test against per-signal breakeven WR. Returns (z, bew_pct).
    Mirrors the report's z-score line. Uses backtest.py's win convention."""
    bews: List[float] = []
    wins = 0
    n = 0
    for sig in signals:
        out = (sig.get("outcome") or "").upper()
        if out not in _ALL_CLOSED:
            continue
        bew = sig.get("breakeven_wr")
        if bew is None:
            continue
        try:
            bews.append(float(bew))
        except (TypeError, ValueError):
            continue
        n += 1
        if out in _WIN_OUTCOMES:
            wins += 1
    if n == 0 or not bews:
        return 0.0, 0.0
    p_obs = wins / n
    p_exp = sum(bews) / len(bews)
    if p_exp <= 0 or p_exp >= 1:
        return 0.0, p_exp * 100.0
    se = math.sqrt(p_exp * (1.0 - p_exp) / n)
    if se == 0:
        return 0.0, p_exp * 100.0
    return (p_obs - p_exp) / se, p_exp * 100.0


# ── Parameter-drift check (--mode=ci) ─────────────────────────────────────────
def check_strategy_params() -> List[str]:
    """Verify backtest.py / config.py constants haven't drifted from baseline.
    Returns a list of human-readable violation strings (empty = pass)."""
    import backtest  # noqa: WPS433 — imported late so secrets_loader runs first
    import config

    violations: List[str] = []
    for name, expected in _EXPECTED_PARAMS.items():
        if name == "BINANCE_TOKEN_KEYS":
            actual = tuple(backtest.BINANCE_TOKENS.keys())
            if actual != expected:
                violations.append(
                    f"BINANCE_TOKEN_KEYS drift: expected {expected}, got {actual}"
                )
            continue
        actual = getattr(backtest, name, None)
        if actual is None:
            actual = getattr(config, name, None)
        if actual != expected:
            violations.append(f"{name} drift: expected {expected!r}, got {actual!r}")

    # Strategy gate values (the things Tune Bot can change).
    if backtest.ACTIVE_CONFIG.fvg_min_quality != "HIGH":
        violations.append(
            f"BACKTEST_CONFIG.fvg_min_quality drift: expected 'HIGH', "
            f"got {backtest.ACTIVE_CONFIG.fvg_min_quality!r}"
        )
    if backtest.ACTIVE_CONFIG.bias_4h_gate != "none":
        violations.append(
            f"BACKTEST_CONFIG.bias_4h_gate drift: expected 'none', "
            f"got {backtest.ACTIVE_CONFIG.bias_4h_gate!r}"
        )
    if 24 != len(backtest.ACTIVE_CONFIG.liquid_hours):
        violations.append(
            f"BACKTEST_CONFIG.liquid_hours drift: expected 24-hour all, "
            f"got {len(backtest.ACTIVE_CONFIG.liquid_hours)} hours"
        )
    return violations


# ── --mode=full: run the actual backtest ──────────────────────────────────────
def run_full_backtest() -> int:
    """Invoke backtest.py as a subprocess so its argparse + logging works."""
    cmd = [sys.executable, str(_ROOT / "backtest.py")]
    print(f"[gate] running: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(_ROOT))
    return proc.returncode


# ── Reporting ─────────────────────────────────────────────────────────────────
def _emit(label: str, value: str, ok: bool) -> None:
    badge = "OK " if ok else "FAIL"
    print(f"[gate] {badge}  {label:18s} {value}")


def evaluate(
    n: int,
    wr_pct: float,
    z: float,
    bew_pct: float,
    breakdown: Dict[str, int],
    min_n: int,
    min_wr_pct: float,
    min_z: float,
) -> bool:
    """Print a regression summary; return True if all floors met."""
    ok_n  = n >= min_n
    ok_wr = wr_pct >= min_wr_pct
    ok_z  = z >= min_z

    print()
    print("─" * 72)
    print(f"  Backtest Regression Gate — baseline floors: "
          f"n≥{min_n}, WR≥{min_wr_pct:.1f}%, z≥{min_z:.2f}")
    print("─" * 72)
    _emit("n_signals",    f"{n}",                                ok_n)
    _emit("WR%",          f"{wr_pct:6.2f}  (BEW {bew_pct:5.2f})", ok_wr)
    _emit("z_score",      f"{z:+.3f}",                           ok_z)
    print(f"[gate] breakdown:  WIN={breakdown['WIN']}  TP1={breakdown['PARTIAL_TP1']}  "
          f"TP2={breakdown['PARTIAL_TP2']}  TP3={breakdown['PARTIAL_TP3']}  "
          f"LOSS={breakdown['LOSS']}  EXPIRED={breakdown['EXPIRED']}  OPEN={breakdown['OPEN']}")
    print("─" * 72)
    return ok_n and ok_wr and ok_z


# ── Entry point ───────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("full", "lastrun", "ci"),
        default="lastrun",
        help="full: fetch+run backtest; lastrun: read JSON; ci: param-drift only",
    )
    parser.add_argument(
        "--results-json",
        default=str(_ROOT / "data" / "backtest_results.json"),
        help="path to backtest_results.json (modes full/lastrun)",
    )
    parser.add_argument(
        "--min-n", type=int, default=_DEFAULT_MIN_N,
        help=f"min signal count (default {_DEFAULT_MIN_N})",
    )
    parser.add_argument(
        "--min-wr-pct", type=float, default=_DEFAULT_MIN_WR_PCT,
        help=f"min WR%% (default {_DEFAULT_MIN_WR_PCT})",
    )
    parser.add_argument(
        "--min-z", type=float, default=_DEFAULT_MIN_Z,
        help=f"min z-score (default {_DEFAULT_MIN_Z})",
    )
    args = parser.parse_args(argv)

    # All modes verify parameter drift — cheap and catches the M24-class bug
    # where a config value silently reverts and tanks signal count to zero.
    violations = check_strategy_params()
    if violations:
        print("[gate] FAIL strategy-parameter drift detected:")
        for v in violations:
            print(f"         - {v}")
        return 1
    print("[gate] OK   strategy parameters match Run-48 baseline")

    if args.mode == "ci":
        # CI runs param-drift only — full backtest is too slow / network-fragile.
        print("[gate] mode=ci — skipping numerical baseline check (use --mode=lastrun locally)")
        return 0

    if args.mode == "full":
        rc = run_full_backtest()
        if rc != 0:
            print(f"[gate] FAIL backtest.py exited {rc}")
            return rc

    json_path = Path(args.results_json)
    if not json_path.is_file():
        print(f"[gate] FAIL backtest results not found at {json_path}")
        return 2
    try:
        signals = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[gate] FAIL cannot parse {json_path}: {exc}")
        return 2
    if not isinstance(signals, list):
        print(f"[gate] FAIL expected JSON list at {json_path}, got {type(signals).__name__}")
        return 2

    wr_pct, n, breakdown = canonical_wr(signals)
    z, bew_pct           = z_score_vs_bew(signals)
    passed = evaluate(n, wr_pct, z, bew_pct, breakdown,
                      args.min_n, args.min_wr_pct, args.min_z)
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
