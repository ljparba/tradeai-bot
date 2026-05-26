"""
One-shot held-out validation against the current baseline.

Per LIVE_BACKTEST_PARITY_ROADMAP.md Phase C: the "hard moment" gate.
Reads the run_id from data/baseline_pin.json, pulls its signals from the
DB, splits the final HELD_OUT_DAYS chronologically, reports the verdict.

Usage:
    python3 scripts/validate_baseline_held_out.py
    python3 scripts/validate_baseline_held_out.py --held-out-days 90
    python3 scripts/validate_baseline_held_out.py --run-id 78

Outcomes (per the roadmap):
    ROBUST     held-out WR within max_gap_pp/2 of tuning AND >= 58%
    BORDERLINE held-out WR within max_gap_pp of tuning AND >= 58%
    OVERFIT    otherwise — baseline may not generalize; operator review required
    INSUFFICIENT_SAMPLE  n_held_out < 5 (typical when explorer trial uses very
                         restrictive gates or BACKTEST_DAYS is shorter than expected)

This script is INFORMATIONAL — it does NOT auto-rollback the baseline.
The operator must read the verdict and decide. The "promise to honor the result"
clause from the roadmap lives in the human, not in code.
"""
import argparse
import json
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from validation import cpcv_summary_split, cpcv_text_report      # noqa: E402
from walk_forward import held_out_text_report                    # noqa: E402

DB_PATH  = os.path.join(_ROOT, "data", "signals.db")
PIN_PATH = os.path.join(_ROOT, "data", "baseline_pin.json")


def _read_baseline_run_id() -> int:
    with open(PIN_PATH, "r", encoding="utf-8") as f:
        pin = json.load(f)
    rid = pin.get("run_id")
    if not rid:
        raise SystemExit(f"baseline_pin.json has no run_id: {PIN_PATH}")
    return int(rid)


def _fetch_signals(run_id: int) -> list:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT ts, outcome, realized_r FROM backtest_signals "
        "WHERE run_id=? ORDER BY ts",
        (run_id,),
    )
    rows = cur.fetchall()
    con.close()
    # backtest_signals has no closed_at column; CPCV falls back to the
    # median-horizon heuristic in validation.py:507 when t1 is missing.
    return [
        {"ts": r[0], "outcome": r[1], "realized_r": r[2]}
        for r in rows
    ]


def _fetch_n_trials_for_dsr(con: sqlite3.Connection) -> int:
    distinct = con.execute(
        "SELECT COUNT(DISTINCT config_hash) FROM backtest_runs "
        "WHERE config_hash IS NOT NULL"
    ).fetchone()[0] or 0
    has_legacy = con.execute(
        "SELECT 1 FROM backtest_runs WHERE config_hash IS NULL LIMIT 1"
    ).fetchone() is not None
    cumulative = 0
    try:
        row = con.execute(
            "SELECT value FROM bot_state WHERE key='cumulative_min_trials'"
        ).fetchone()
        if row and row[0]:
            cumulative = int(json.loads(row[0]).get("value") or 0)
    except Exception:
        pass
    n = distinct + (1 if has_legacy else 0)
    return max(n, cumulative, 2)


def _fetch_sr_trial_std(con: sqlite3.Connection):
    try:
        row = con.execute(
            "SELECT value FROM bot_state WHERE key='cross_config_sr_trial_std'"
        ).fetchone()
        if row and row[0]:
            v = json.loads(row[0]).get("value")
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser(description="Phase C held-out validation against baseline")
    ap.add_argument("--run-id", type=int, default=None,
                    help="Override the run_id (default: read baseline_pin.json)")
    ap.add_argument("--held-out-days", type=int, default=90,
                    help="Days to reserve as held-out from end of data (default 90)")
    ap.add_argument("--max-gap-pp", type=float, default=8.0,
                    help="Verdict threshold for |tuning_wr - held_out_wr|")
    ap.add_argument("--min-wr-pct", type=float, default=58.0,
                    help="Held-out WR floor for ROBUST/BORDERLINE")
    ap.add_argument("--json", action="store_true",
                    help="Print machine-readable JSON summary instead of text report")
    args = ap.parse_args()

    run_id = args.run_id or _read_baseline_run_id()
    sigs = _fetch_signals(run_id)
    if not sigs:
        raise SystemExit(f"No signals found for run_id={run_id}")

    con = sqlite3.connect(DB_PATH)
    n_trials = _fetch_n_trials_for_dsr(con)
    sr_std = _fetch_sr_trial_std(con)
    con.close()

    summary = cpcv_summary_split(
        sigs,
        held_out_days=args.held_out_days,
        n_trials_for_dsr=n_trials,
        sr_trial_std_for_dsr=sr_std,
        max_gap_pp=args.max_gap_pp,
        min_held_out_wr_pct=args.min_wr_pct,
    )

    if args.json:
        # Slim copy: don't print every CPCV split, just the headlines.
        slim = {
            "run_id":        run_id,
            "cutoff_iso":    summary["cutoff_iso"],
            "n_tuning":      summary["n_tuning"],
            "n_held_out":    summary["n_held_out"],
            "tuning_wr_mean": summary["tuning"].get("wr_mean"),
            "tuning_dsr":    summary["tuning"].get("dsr"),
            "held_out_wr":   summary["held_out"].get("wr_pct"),
            "held_out_gap_pp": summary["held_out"].get("gap_pp"),
            "verdict_dual":  summary["verdict_dual"],
        }
        print(json.dumps(slim, indent=2))
        return

    print(f"\n[VALIDATE-HELD-OUT] Baseline Run-{run_id}")
    print(f"  total signals     : {len(sigs)}")
    print(f"  cutoff (ISO UTC)  : {summary['cutoff_iso']}")
    print(f"  tuning n          : {summary['n_tuning']}")
    print(f"  held_out n        : {summary['n_held_out']}")
    print(f"  n_trials_for_dsr  : {n_trials}")
    print(f"  sr_trial_std      : {sr_std if sr_std is not None else 'fallback proxy'}")

    print("\n[CPCV on tuning-only pool]")
    print(cpcv_text_report(summary["tuning"]))

    print("\n" + held_out_text_report(
        summary["held_out"],
        tuning_wr=summary["tuning"].get("wr_mean"),
        held_out_days=args.held_out_days,
    ))

    verdict = summary["verdict_dual"]
    print(f"\n[PHASE C VERDICT] {verdict}")
    if verdict == "ROBUST":
        print("  Baseline generalizes — held-out within tolerance + above floor.")
    elif verdict == "BORDERLINE":
        print("  Some drift detected. Baseline tradeable but plan rebuild within 2 months.")
    elif verdict == "OVERFIT":
        print("  *** OVERFIT *** held-out fails the floor or gap threshold.")
        print("  Operator must decide: rollback, restart Optuna on tuning-only, or accept risk.")
    else:
        print("  Held-out sample too small to validate. Re-run after more data accrues.")


if __name__ == "__main__":
    main()
