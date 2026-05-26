"""
FIX 1 Part 2 — Cross-Config sr_trial_std Computation
======================================================
2026-05-23

WHY THIS EXISTS
---------------
FIX 1 (2026-05-23) fixed the n_trials counting bug — DSR no longer over-counts
re-runs of the same config. But validation.py still uses an ANTI-CONSERVATIVE
proxy for `sr_trial_std`: within-run CPCV fold-Sharpe std instead of the true
cross-trial std across DISTINCT parameter configurations.

The Bailey/Lopez de Prado (2014) selection-bias correction needs the std of
the Sharpe ratios produced by ALL distinct configurations ever tested — that
quantifies how much the BEST result is inflated by trying many things.

The within-fold proxy is always smaller than the true cross-config std, which
makes reported DSR optimistic.

WHAT THIS SCRIPT DOES
---------------------
1. Query backtest_runs for all DISTINCT config_hash values
2. For each distinct config, find its MOST RECENT run (latest snapshot)
3. Load that run's signals from backtest_signals
4. Run validation.cpcv_summary to get the OOS CPCV mean Sharpe
5. Compute std across those OOS Sharpes = the honest sr_trial_std
6. Persist to bot_state['cross_config_sr_trial_std'] for backtest.py to read

WHAT BACKTEST.PY DOES WITH IT
------------------------------
Next time backtest.py runs, it reads the persisted value from bot_state and
passes it to cpcv_summary as `sr_trial_std_for_dsr=value`. This bypasses the
within-fold proxy entirely. The resulting DSR is HONEST cross-trial.

The dsr_proxy_used flag becomes False, and the anti-conservative warning
in the report disappears (because there's no anti-conservatism anymore).

WHEN TO RE-RUN THIS SCRIPT
--------------------------
- After every new DISTINCT config_hash gets persisted to backtest_runs
- Quarterly minimum (the std stabilizes as more configs are tested)
- Before any pre-LIVE decision (you want the freshest honest figure)
- After any optimizer cycle that promotes a new config

USAGE
-----
    python scripts/compute_cross_config_sr_std.py
    python scripts/compute_cross_config_sr_std.py --min-signals 25   # default 30
    python scripts/compute_cross_config_sr_std.py --dry-run          # compute, don't persist
    python scripts/compute_cross_config_sr_std.py --show             # read current persisted value

OUTPUT
------
Prints per-config CPCV mean Sharpe, then the aggregate std, then writes to
bot_state. The persisted blob includes provenance (n_configs, computed_at,
mean_sharpe, min/max Sharpe) so future readers know whether it's stale.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from validation import cpcv_summary, _safe_std

_DB_PATH = _ROOT / "data" / "signals.db"
_BOT_STATE_KEY = "cross_config_sr_trial_std"


def _load_signals_for_run(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """Load signals for a given backtest run_id, formatted for cpcv_summary().

    H-A fix (cycle-4 audit 2026-05-26): `closed_at` is now derived from
    the triple-barrier exit bar `tb_t1` (number of 5M bars to exit) +
    the entry timestamp. Previously aliased `ts as closed_at` → zero-length
    label window → CPCV purging silently disabled → cross-config
    sr_trial_std computed on contaminated splits → downstream DSR
    optimistic. When `tb_t1` is NULL (legacy rows or unfilled triple-barrier),
    falls back to a 24h sentinel (matches validation.py's fallback at
    line 511).
    """
    rows = conn.execute(
        """SELECT ts, outcome, tb_t1,
                  net_tp1_pct, net_sl_pct, net_tp2_pct, net_tp3_pct
           FROM backtest_signals WHERE run_id = ?""",
        (run_id,),
    ).fetchall()
    out = []
    for r in rows:
        ts, outcome, tb_t1, n_tp1, n_sl, n_tp2, n_tp3 = r
        # 5-minute bars: closed_at = ts + tb_t1 * 5min
        if tb_t1 is not None and tb_t1 > 0:
            # SQLite datetime modifier needs minutes
            closed_at_row = conn.execute(
                "SELECT datetime(?, '+' || ? || ' minutes')",
                (ts, int(tb_t1) * 5),
            ).fetchone()
            closed_at = closed_at_row[0] if closed_at_row else ts
        else:
            # Fallback: 24h horizon (matches validation.py:511 default)
            closed_at_row = conn.execute(
                "SELECT datetime(?, '+24 hours')", (ts,),
            ).fetchone()
            closed_at = closed_at_row[0] if closed_at_row else ts
        out.append({
            "ts":          ts,
            "outcome":     outcome,
            "closed_at":   closed_at,
            "net_tp1_pct": n_tp1 or 0.0,
            "net_sl_pct":  n_sl or 0.0,
            "net_tp2_pct": n_tp2,
            "net_tp3_pct": n_tp3,
        })
    return out


def _list_distinct_configs(conn: sqlite3.Connection, min_signals: int) -> list[tuple[str, int, int]]:
    """Return [(config_hash, latest_run_id, n_signals), ...] sorted by run_id DESC.

    Uses LATEST run per hash (MAX(id)) to get the freshest snapshot of that config.
    """
    rows = conn.execute(
        """
        SELECT br.config_hash, MAX(br.id) AS latest_run_id
        FROM backtest_runs br
        WHERE br.config_hash IS NOT NULL
        GROUP BY br.config_hash
        """
    ).fetchall()

    result = []
    for cfg_hash, latest_id in rows:
        n = conn.execute(
            "SELECT COUNT(*) FROM backtest_signals WHERE run_id = ?",
            (latest_id,),
        ).fetchone()[0]
        if n >= min_signals:
            result.append((cfg_hash, latest_id, n))
    # Sort latest first
    result.sort(key=lambda r: r[1], reverse=True)
    return result


def compute_and_persist(min_signals: int = 30, dry_run: bool = False) -> dict:
    """Compute cross-config sr_trial_std and (optionally) persist to bot_state.

    Returns the result blob (whether or not it was persisted).
    """
    if not _DB_PATH.exists():
        print(f"[ERROR] DB not found at {_DB_PATH}")
        sys.exit(2)

    conn = sqlite3.connect(str(_DB_PATH))
    configs = _list_distinct_configs(conn, min_signals=min_signals)

    if len(configs) < 2:
        print(f"[ERROR] Need >= 2 distinct configs with >= {min_signals} signals; found {len(configs)}")
        conn.close()
        sys.exit(3)

    print(f"Computing CPCV mean Sharpe across {len(configs)} distinct configs "
          f"(min_signals={min_signals})...\n")

    sharpes: list[float] = []
    per_config_rows: list[dict] = []

    for cfg_hash, run_id, n in configs:
        sigs = _load_signals_for_run(conn, run_id)
        summary = cpcv_summary(sigs)
        sr = summary.get("sharpe_mean", 0.0)
        sharpes.append(sr)
        per_config_rows.append({
            "config_hash":     cfg_hash[:10] + "...",
            "latest_run_id":   run_id,
            "n_signals":       n,
            "oos_sharpe_mean": round(sr, 4),
            "cpcv_wr_mean":    round(summary.get("wr_mean", 0.0), 2),
        })
        print(f"  hash={cfg_hash[:10]}...  run_id={run_id:4d}  n={n:3d}  "
              f"OOS_sharpe={sr:.4f}  CPCV_WR={summary.get('wr_mean', 0):.2f}%")

    conn.close()

    sr_std  = _safe_std(sharpes)
    sr_mean = sum(sharpes) / len(sharpes)
    sr_min  = min(sharpes)
    sr_max  = max(sharpes)

    result = {
        "value":             round(sr_std, 6),
        "n_configs":         len(sharpes),
        "min_signals_floor": min_signals,
        "computed_at":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mean_oos_sharpe":   round(sr_mean, 4),
        "min_oos_sharpe":    round(sr_min, 4),
        "max_oos_sharpe":    round(sr_max, 4),
        "per_config":        per_config_rows,
        "note": (
            "Cross-config sr_trial_std (FIX 1 Part 2, 2026-05-23). "
            "Std of OOS CPCV mean Sharpe across all distinct config_hash entries "
            "in backtest_runs with >= min_signals_floor signals. Use as the honest "
            "Bailey/LdP 2014 sr_trial_std input — bypasses the within-fold proxy."
        ),
    }

    print(f"\nCROSS-CONFIG STATISTICS")
    print(f"  n_distinct_configs   : {len(sharpes)}")
    print(f"  mean OOS Sharpe      : {sr_mean:.4f}")
    print(f"  min  OOS Sharpe      : {sr_min:.4f}")
    print(f"  max  OOS Sharpe      : {sr_max:.4f}")
    print(f"  std  OOS Sharpe      : {sr_std:.4f}   <-- sr_trial_std")

    if dry_run:
        print("\n[DRY RUN] Not persisting to bot_state.")
        return result

    # Persist
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
            (_BOT_STATE_KEY, json.dumps(result, indent=2)),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"\n[PERSISTED] bot_state.{_BOT_STATE_KEY} written.")
    print(f"            Next backtest.py run will use this value via cpcv_summary's "
          f"sr_trial_std_for_dsr= argument, bypassing the within-fold proxy.")
    return result


def show_current() -> None:
    """Print the currently persisted blob, if any."""
    if not _DB_PATH.exists():
        print(f"[ERROR] DB not found at {_DB_PATH}")
        sys.exit(2)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (_BOT_STATE_KEY,)
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()

    if not row:
        print(f"[INFO] No persisted value yet. Run without --show to compute and persist.")
        return
    blob = json.loads(row[0])
    print(json.dumps(blob, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Compute cross-config sr_trial_std (FIX 1 Part 2)",
        allow_abbrev=False,
    )
    p.add_argument("--min-signals", type=int, default=30,
                   help="Minimum signals per config to include (default: 30)")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute and print, but don't persist to bot_state")
    p.add_argument("--show", action="store_true",
                   help="Print the currently persisted value and exit")
    args = p.parse_args()

    if args.show:
        show_current()
        return 0

    compute_and_persist(min_signals=args.min_signals, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
