"""
run_grid.py — Pre-registered grid runner for PHASE C-BREAKOUT.

GRID (locked here BEFORE running anything — printed at top of every run):

  break_close_buffer_pct: {0.000, 0.001}   # close-beyond-level buffer (0%, 0.1%)
  tp_scheme:              {"1.5/2.5/3.5R", "2.0/3.0/4.0R"}
  c2_lookback:            {4, 8}
  mss_horizon:            {15, 30}

Total configs: 2 × 2 × 2 × 2 = 16

CLEARED DB at start so the grid sits cleanly at run_ids 1..16.

Outputs:
  - data/breakout.db backtest_runs rows (16 new)
  - data/breakout.db backtest_signals rows (one per signal across all 16 runs)
  - data/grid_results.json — summary table for the report

Honesty discipline (per §2 + §3 of the prompt):
  - Grid declared up front, run ONCE, all results reported regardless of outcome.
  - NO re-tuning, NO secondary grids, NO knob lowering to rescue.
  - Lead with EXPECTANCY (avg_R, sum_R, net %), not WR.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time as _time
from itertools import product
from pathlib import Path

_BREAKOUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BREAKOUT_DIR))
sys.path.insert(0, "/home/tradeai/TradeAI")

import breakout_backtest  # noqa: E402

# ── Pre-registered grid (LOCKED — do not modify) ───────────────────────────
GRID = {
    "H4_BREAKOUT_CLOSE_BUFFER_PCT": [0.0, 0.001],
    "TP_SCHEME":                     [(1.5, 2.5, 3.5), (2.0, 3.0, 4.0)],
    "H4_BREAKOUT_C2_LOOKBACK":       [4, 8],
    "H4_BREAKOUT_MSS_HORIZON":       [15, 30],
}


def cartesian_grid():
    """Expand GRID into a list of (config_id, config_dict)."""
    axes = []
    names = []
    for k, vals in GRID.items():
        names.append(k)
        axes.append(vals)
    configs = []
    for i, tup in enumerate(product(*axes), start=1):
        cfg = dict(zip(names, tup))
        # Unpack TP_SCHEME into 3 separate env knobs
        tp = cfg.pop("TP_SCHEME")
        cfg["BREAKOUT_TP1_RR"] = tp[0]
        cfg["BREAKOUT_TP2_RR"] = tp[1]
        cfg["BREAKOUT_TP3_RR"] = tp[2]
        cfg["TP_SCHEME_LABEL"] = f"{tp[0]}/{tp[1]}/{tp[2]}R"
        configs.append((i, cfg))
    return configs


def clear_breakout_db():
    """Delete all rows from backtest_runs + backtest_signals so the grid
    sits at run_ids 1..N cleanly. Schema preserved."""
    db_path = breakout_backtest.BREAKOUT_DB_PATH
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("DELETE FROM backtest_signals")
    cur.execute("DELETE FROM backtest_runs")
    cur.execute("DELETE FROM sqlite_sequence WHERE name='backtest_runs'")
    cur.execute("DELETE FROM sqlite_sequence WHERE name='backtest_signals'")
    conn.commit()
    conn.close()


def main():
    configs = cartesian_grid()
    print("=" * 78)
    print("PHASE C-BREAKOUT PRE-REGISTERED GRID")
    print("=" * 78)
    print(f"  Total configs: {len(configs)}")
    print()
    print("  Grid axes:")
    print("    H4_BREAKOUT_CLOSE_BUFFER_PCT : {0.0, 0.001}")
    print("    TP_SCHEME                    : {1.5/2.5/3.5R, 2.0/3.0/4.0R}")
    print("    H4_BREAKOUT_C2_LOOKBACK      : {4, 8}")
    print("    H4_BREAKOUT_MSS_HORIZON      : {15, 30}")
    print()
    print("  Configs:")
    for cid, cfg in configs:
        # Pretty print the config tuple
        print(f"    [{cid:2d}] buf={cfg['H4_BREAKOUT_CLOSE_BUFFER_PCT']:.3f} "
              f"tp={cfg['TP_SCHEME_LABEL']:<13s} "
              f"c2_lookback={cfg['H4_BREAKOUT_C2_LOOKBACK']:2d} "
              f"mss_horizon={cfg['H4_BREAKOUT_MSS_HORIZON']:2d}")
    print()

    print("Clearing breakout.db (preserving schema)…")
    clear_breakout_db()
    conn = breakout_backtest.open_breakout_db()

    print("\n" + "─" * 78)
    print("RUNNING GRID")
    print("─" * 78)
    t0 = _time.time()
    results = []
    for cid, cfg in configs:
        # Strip the human label before passing — env values are env-string-coerced
        env_cfg = {k: v for k, v in cfg.items() if k != "TP_SCHEME_LABEL"}
        result = breakout_backtest.run_one_config(env_cfg, conn)
        result["config_id"] = cid
        result["tp_scheme_label"] = cfg["TP_SCHEME_LABEL"]
        results.append(result)
    total_elapsed = _time.time() - t0

    conn.close()
    print(f"\n  GRID COMPLETE in {total_elapsed:.1f}s")

    # Write a grid_results.json summary
    out_path = _BREAKOUT_DIR / "data" / "grid_results.json"
    out = {
        "grid":          {k: (list(v) if not isinstance(v, list) else v) for k, v in GRID.items()},
        "n_configs":     len(configs),
        "total_elapsed": round(total_elapsed, 2),
        "results":       [
            {
                "config_id":       r["config_id"],
                "run_id":          r["run_id"],
                "config":          r["config"],
                "tp_scheme_label": r["tp_scheme_label"],
                "n_signals":       r["n_signals"],
                "by_token":        r["by_token"],
                "elapsed_sec":     round(r["elapsed_sec"], 2),
            }
            for r in results
        ],
    }
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  Wrote: {out_path}")
    print()

    print("─" * 78)
    print("PER-CONFIG SUMMARY")
    print("─" * 78)
    print(f"  {'#':>2}  {'buf':>5}  {'TP':>11}  {'C2':>2}  {'MSS':>3}  "
          f"{'n':>4}  {'sec':>5}")
    print(f"  {'─'*2}  {'─'*5}  {'─'*11}  {'─'*2}  {'─'*3}  {'─'*4}  {'─'*5}")
    for r in results:
        c = r["config"]
        print(f"  {r['config_id']:>2}  {c['H4_BREAKOUT_CLOSE_BUFFER_PCT']:>5.3f}  "
              f"{r['tp_scheme_label']:>11}  {c['H4_BREAKOUT_C2_LOOKBACK']:>2}  "
              f"{c['H4_BREAKOUT_MSS_HORIZON']:>3}  {r['n_signals']:>4}  "
              f"{r['elapsed_sec']:>5.1f}")
    print()
    print("Grid complete. Run compute_metrics.py next.")


if __name__ == "__main__":
    main()
