"""
Promote a backtest run as the new canonical baseline.

What it does:
1. Reads the given backtest_runs row for the target run_id.
2. Writes data/baseline_pin.json with that run's metrics + current code-state settings.
3. Inserts a tune_history row tagged with the run_id so the dashboard's
   Tune Bot History reflects the promotion (with Run-X label).
4. Optionally takes a snapshot of signals.db via scripts/snapshot_baseline.py.

Usage:
    python scripts/promote_baseline.py --run-id 168 \\
        --label "F-8 + P-2b + TP-2-b (stacked)" \\
        --param TREND_1H_GATE --old loose --new strict \\
        --notes "Tier-2 TP-2-b grid winner"

    # Backfill an old promotion (no tune_history insert needed):
    python scripts/promote_baseline.py --run-id 128 --no-tune-history \\
        --label "F-8 (bias_4h_gate strict->none)"
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH   = os.path.join(_ROOT, "data", "signals.db")
PIN_PATH  = os.path.join(_ROOT, "data", "baseline_pin.json")


def _current_settings() -> dict:
    """Snapshot the live param values from config + ict_engine at promote time."""
    sys.path.insert(0, _ROOT)
    import config as cfg
    import ict_engine as ict
    return {
        "bias_4h_gate":              cfg.LIVE_BIAS_4H_GATE,
        "trend_1h_gate":             cfg.LIVE_TREND_1H_GATE,
        "dealing_range_gate_live":   cfg.LIVE_DEALING_RANGE_GATE,
        "dealing_range_gate_backtest": cfg.BACKTEST_DEALING_RANGE_GATE,
        "mss_min_quality":           cfg.LIVE_MSS_MIN_QUALITY,
        "fvg_min_quality":           cfg.LIVE_FVG_MIN_QUALITY,
        "ict_sweep_lookback":        ict.ICT_SWEEP_LOOKBACK,
        "ict_swing_n":               ict.ICT_SWING_N,
        "ict_mss_horizon":           ict.ICT_MSS_HORIZON,
        "ict_fvg_min_gap":           ict.ICT_FVG_MIN_GAP,
        "ict_eqh_tolerance":         ict.ICT_EQH_TOLERANCE,
    }


def _fetch_run(run_id: int) -> dict:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT id, run_date, total_signals, overall_wr, config_hash, summary "
        "FROM backtest_runs WHERE id=?", (run_id,)
    )
    row = cur.fetchone()
    con.close()
    if not row:
        raise SystemExit(f"Run-{run_id} not found in backtest_runs")
    summary = json.loads(row[5]) if row[5] else {}
    wf      = summary.get("walk_forward", {})
    return {
        "id":             row[0],
        "run_date":       row[1],
        "n":              row[2],
        "wr":             row[3],
        "config_hash":    row[4],
        "train_wr":       wf.get("train_wr"),
        "test_wr":        wf.get("test_wr"),
    }


def _write_pin(run: dict, label: str, notes: str, settings: dict,
               cpcv_mean=None, cpcv_std=None, sharpe=None, dsr=None, cpcv_q05=None):
    # Derive q05 if caller didn't supply it but cpcv_mean+std are present
    if cpcv_q05 is None and cpcv_mean is not None and cpcv_std is not None:
        cpcv_q05 = round(cpcv_mean - 1.645 * cpcv_std, 2)
    pin = {
        "run_id":      run["id"],
        "config_hash": run["config_hash"],
        "label":       label,
        "promoted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "expected": {
            "n":                 run["n"],
            "wr_pct":            run["wr"],
            "cpcv_wr_mean_pct":  cpcv_mean,
            "cpcv_wr_std_pct":   cpcv_std,
            "cpcv_wr_q05_pct":   cpcv_q05,
            "cpcv_sharpe_mean":  sharpe,
            "dsr_pct":           dsr,
        },
        "key_settings": settings,
        "notes":         notes or "",
    }
    with open(PIN_PATH, "w", encoding="utf-8") as f:
        json.dump(pin, f, indent=2)
    print(f"[promote] wrote {PIN_PATH} → Run-{run['id']}")


def _insert_tune_history(run: dict, param: str, old_val: str, new_val: str,
                          notes: str, status: str = "APPLIED"):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """INSERT INTO tune_history
           (applied_at, param, old_val, new_val, signals_at_apply,
            backtest_run_id, train_wr, test_wr, status, notes)
           VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            param, str(old_val), str(new_val),
            run["id"], run["train_wr"], run["test_wr"],
            status,
            notes or "Promoted as baseline",
        )
    )
    con.commit()
    con.close()
    print(f"[promote] tune_history row inserted (status={status}, param={param}, Run-{run['id']})")


def rollback_to_run(target_run_id: int):
    """Roll baseline_pin.json back to a prior run_id. Inserts ROLLED_BACK
    row in tune_history for audit trail. Operator path only — never invoked
    by the autonomous explorer."""
    # Capture the CURRENT pin's run_id before overwriting (for the tune_history
    # audit row's old_val). Falls back to "<unknown>" if pin can't be read.
    prev_pin_run = "<unknown>"
    try:
        with open(PIN_PATH, "r", encoding="utf-8") as f:
            prev_pin_run = f"Run-{json.load(f).get('run_id') or '?'}"
    except Exception:
        pass

    run = _fetch_run(target_run_id)
    settings = _current_settings()
    _write_pin(run, label=f"Rollback to Run-{target_run_id}",
               notes=f"Manual rollback by operator on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
               settings=settings)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """INSERT INTO tune_history
           (applied_at, param, old_val, new_val, signals_at_apply,
            backtest_run_id, train_wr, test_wr, status, notes)
           VALUES (?, 'BASELINE_PIN', ?, ?, 0, ?, ?, ?, 'ROLLED_BACK', ?)""",
        (
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            prev_pin_run,
            f"Run-{target_run_id}",
            run["id"], run["train_wr"], run["test_wr"],
            f"Operator rolled baseline pin from {prev_pin_run} back to Run-{target_run_id}",
        )
    )
    con.commit()
    con.close()
    print(f"[rollback] baseline pin reverted from {prev_pin_run} to Run-{target_run_id}")


def _check_held_out_gate(run_id: int, held_out_days: int,
                          max_gap_pp: float, min_wr_pct: float) -> dict:
    """Phase C gate: pull the run's signals, run cpcv_summary_split, return
    the verdict + key metrics. Used by auto-promotion to block configs that
    pass tuning-CPCV but fail held-out generalization.

    S-2a/b fix (cycle-4 audit 2026-05-26):
    - SELECT now includes all PnL columns required by validation's default
      pnl_func (was: only ts/outcome/realized_r → silent zero-Sharpe).
    - cpcv_summary_split call now passes n_trials_for_dsr +
      sr_trial_std_for_dsr from bot_state (was: dsr=None → silent
      verdict=MARGINAL bypass of multiple-testing correction).

    Returns dict with keys:
        verdict       "ROBUST" | "BORDERLINE" | "OVERFIT" | "INSUFFICIENT_SAMPLE"
        held_out_wr   headline WR on held-out signals
        gap_pp        |tuning_wr - held_out_wr|
        n_held_out
        cutoff_iso
        tuning_dsr    DSR on the tuning-only CPCV (after C-NEW-1 fix)
        pass_gate     True iff verdict in ("ROBUST", "BORDERLINE")
    """
    sys.path.insert(0, _ROOT)
    from validation import cpcv_summary_split
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT ts, outcome, realized_r, net_tp1_pct, net_sl_pct, net_tp2_pct, tb_t1 "
        "FROM backtest_signals WHERE run_id=? ORDER BY ts",
        (run_id,),
    )
    rows = cur.fetchall()
    # Read honest DSR pool parameters from bot_state (same path as
    # backtest.py:3140-3164 — keeps CPCV + held-out gate consistent).
    n_trials_for_dsr = None
    sr_trial_std = None
    try:
        distinct = con.execute(
            "SELECT COUNT(DISTINCT config_hash) FROM backtest_runs "
            "WHERE config_hash IS NOT NULL"
        ).fetchone()[0] or 0
        has_legacy = con.execute(
            "SELECT 1 FROM backtest_runs WHERE config_hash IS NULL LIMIT 1"
        ).fetchone() is not None
        cumulative = 0
        row = con.execute(
            "SELECT value FROM bot_state WHERE key='cumulative_min_trials'"
        ).fetchone()
        if row and row[0]:
            cumulative = int(json.loads(row[0]).get("value") or 0)
        candidate = distinct + (1 if has_legacy else 0) + 1
        candidate = max(candidate, cumulative)
        if candidate > 1:
            n_trials_for_dsr = int(candidate)
        row = con.execute(
            "SELECT value FROM bot_state WHERE key='cross_config_sr_trial_std'"
        ).fetchone()
        if row and row[0]:
            v = json.loads(row[0]).get("value")
            if isinstance(v, (int, float)) and v > 0:
                sr_trial_std = float(v)
    except Exception:
        pass
    # NF-1 fix (cycle-5 audit 2026-05-26): derive closed_at from tb_t1
    # (triple-barrier exit bar × 5min) so CPCV purging in the promotion
    # gate uses real label windows instead of falling back to the median-
    # horizon heuristic. Matches the H-A pattern already applied in
    # scripts/compute_cross_config_sr_std.py.
    sigs = []
    for r in rows:
        ts, outcome, realized_r, n_tp1, n_sl, n_tp2, tb_t1 = r
        if tb_t1 is not None and tb_t1 > 0:
            closed_at_row = con.execute(
                "SELECT datetime(?, '+' || ? || ' minutes')",
                (ts, int(tb_t1) * 5),
            ).fetchone()
            closed_at = closed_at_row[0] if closed_at_row else ts
        else:
            closed_at_row = con.execute(
                "SELECT datetime(?, '+24 hours')", (ts,),
            ).fetchone()
            closed_at = closed_at_row[0] if closed_at_row else ts
        sigs.append({
            "ts": ts, "outcome": outcome, "realized_r": realized_r,
            "closed_at": closed_at,
            "net_tp1_pct": n_tp1, "net_sl_pct": n_sl, "net_tp2_pct": n_tp2,
        })
    con.close()
    summary = cpcv_summary_split(
        sigs,
        held_out_days=held_out_days,
        n_trials_for_dsr=n_trials_for_dsr,
        sr_trial_std_for_dsr=sr_trial_std,
        max_gap_pp=max_gap_pp,
        min_held_out_wr_pct=min_wr_pct,
    )
    verdict = summary["verdict_dual"]
    held = summary["held_out"]
    return {
        "verdict":     verdict,
        "held_out_wr": held.get("wr_pct", 0.0),
        "gap_pp":      held.get("gap_pp"),
        "n_held_out":  summary["n_held_out"],
        "cutoff_iso":  summary["cutoff_iso"],
        "tuning_dsr":  summary["tuning"].get("dsr"),
        "pass_gate":   verdict in ("ROBUST", "BORDERLINE"),
    }


def main():
    ap = argparse.ArgumentParser(description="Promote a backtest run as canonical baseline")
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--label",  type=str, default="")
    ap.add_argument("--notes",  type=str, default="")
    ap.add_argument("--param",  type=str, default=None, help="e.g. TREND_1H_GATE")
    ap.add_argument("--old",    type=str, default=None, help="prior value, e.g. loose")
    ap.add_argument("--new",    type=str, default=None, help="new value, e.g. strict")
    ap.add_argument("--cpcv-mean", type=float, default=None)
    ap.add_argument("--cpcv-std",  type=float, default=None)
    ap.add_argument("--sharpe",    type=float, default=None)
    ap.add_argument("--dsr",       type=float, default=None)
    ap.add_argument("--no-tune-history", action="store_true",
                    help="Skip tune_history insert (for backfilling old promotions)")
    ap.add_argument("--auto", action="store_true",
                    help="Tag tune_history row as AUTO_PROMOTED (called by autonomous explorer)")
    ap.add_argument("--rollback-to-run", type=int, default=None,
                    help="Roll baseline_pin.json back to this prior run_id (operator path)")
    # Phase C (2026-05-26): held-out gate (default 0 = disabled for backward compat)
    ap.add_argument("--held-out-days", type=int, default=int(os.environ.get("HELD_OUT_DAYS", "0") or "0"),
                    help="Phase C: enforce held-out PASS gate over the final N days. "
                         "Auto-promotion is BLOCKED if the held-out verdict is OVERFIT.")
    ap.add_argument("--held-out-max-gap-pp", type=float, default=8.0,
                    help="Phase C: max |tuning_wr - held_out_wr| for ROBUST/BORDERLINE (default 8.0)")
    ap.add_argument("--held-out-min-wr-pct", type=float, default=58.0,
                    help="Phase C: held-out WR floor for ROBUST/BORDERLINE (default 58.0)")
    args = ap.parse_args()

    if args.rollback_to_run is not None:
        rollback_to_run(args.rollback_to_run); return

    if args.run_id is None:
        ap.error("--run-id is required (unless using --rollback-to-run)")

    # Phase C gate: check held-out BEFORE any promotion writes happen.
    if args.held_out_days > 0:
        gate = _check_held_out_gate(
            args.run_id, args.held_out_days,
            args.held_out_max_gap_pp, args.held_out_min_wr_pct,
        )
        print(f"[promote/held-out] verdict={gate['verdict']} "
              f"n_held_out={gate['n_held_out']} "
              f"wr={gate['held_out_wr']:.2f}% "
              f"gap_pp={gate['gap_pp'] if gate['gap_pp'] is not None else 'n/a'} "
              f"cutoff={gate['cutoff_iso']}")
        if args.auto and not gate["pass_gate"]:
            print(f"[promote/held-out] BLOCKED auto-promotion: held-out verdict={gate['verdict']}")
            sys.exit(2)
        if not gate["pass_gate"]:
            print(f"[promote/held-out] WARNING — manual promotion proceeding "
                  f"despite held-out verdict={gate['verdict']}")

    run = _fetch_run(args.run_id)
    settings = _current_settings()
    _write_pin(run, args.label, args.notes, settings,
               cpcv_mean=args.cpcv_mean, cpcv_std=args.cpcv_std,
               sharpe=args.sharpe, dsr=args.dsr)
    if not args.no_tune_history and args.param:
        status = "AUTO_PROMOTED" if args.auto else "APPLIED"
        _insert_tune_history(run, args.param, args.old or "?", args.new or "?",
                              args.notes, status=status)


if __name__ == "__main__":
    main()
