#!/usr/bin/env python3
"""Phase A backfill — best-effort populate limit_fillable for pre-Phase-A signals.

Context (2026-05-28): Phase A added 4 columns to signals table:
  actual_entry_price, slippage_pct, limit_fillable, fillable_check_at

Signals that fired BEFORE the schema migration ran (5 CRT signals from
2026-05-27 17:02-23:30 UTC: LINK#1, TON#2/3/4, AVAX#5) have NULL for all
4 columns. We can recover limit_fillable from Binance's historical 5M
klines (price history is canonical/queryable). We CANNOT recover
actual_entry_price honestly — that would require the live tick value
captured AT save_signal time, which wasn't persisted. Left as NULL.

What this script does:
  1. For each signal with limit_fillable IS NULL AND age >= CRT_LIMIT_FILL_WINDOW_MIN
  2. Fetch 5M klines for the token covering [signal_ts, signal_ts + window]
  3. SELL: check if any high  >= entry_price  →  FILLED (1)
     BUY:  check if any low   <= entry_price  →  FILLED (1)
  4. If no retouch within window → MISSED (0)
  5. Set fillable_check_at = "backfill_2026-05-28" (audit trail)

Usage:
    python3 scripts/backfill_phase_a.py
    python3 scripts/backfill_phase_a.py --dry-run    # print what would change, don't write

Read-only by default unless --apply is set. Defaults to dry-run for safety.
"""

import argparse
import os
import sys
import sqlite3
import time
from datetime import datetime, timezone, timedelta

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_ROOT, "data", "signals.db")
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
DEFAULT_WINDOW_MIN = 30  # mirrors config.CRT_LIMIT_FILL_WINDOW_MIN default


def _binance_5m_klines(token: str, start_ms: int, end_ms: int) -> list:
    """Fetch 5M klines for [start_ms, end_ms]. Returns list of [t,o,h,l,c,v,...]."""
    symbol = f"{token}USDT"
    params = {
        "symbol":    symbol,
        "interval":  "5m",
        "startTime": start_ms,
        "endTime":   end_ms,
        "limit":     50,
    }
    try:
        r = requests.get(BINANCE_KLINES, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] Binance fetch failed for {token}: {e}")
        return []


def main():
    ap = argparse.ArgumentParser(description="Phase A backfill — limit_fillable")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write changes (default: dry-run, read-only)")
    ap.add_argument("--window-min", type=int, default=DEFAULT_WINDOW_MIN,
                    help=f"Fill window in minutes (default {DEFAULT_WINDOW_MIN})")
    args = ap.parse_args()
    is_dry = not args.apply

    print(f"[Phase-A Backfill] DB: {DB_PATH}")
    print(f"                   Window: {args.window_min} min")
    print(f"                   Mode:   {'DRY-RUN (read-only)' if is_dry else 'APPLY (writing changes)'}")
    print()

    if not os.path.exists(DB_PATH):
        print(f"[ERROR] DB not found: {DB_PATH}")
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Verify the new columns exist (Phase A migration must have run)
    cols = [c[1] for c in conn.execute("PRAGMA table_info(signals)").fetchall()]
    required = {"limit_fillable", "fillable_check_at", "actual_entry_price", "slippage_pct"}
    missing = required - set(cols)
    if missing:
        print(f"[ERROR] Phase A schema not migrated yet — missing columns: {missing}")
        print(f"        Restart the bot first to trigger init_db schema migration.")
        sys.exit(3)

    # Pick signals: NULL limit_fillable AND age >= window
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=args.window_min)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT id, token, signal, entry_price, timestamp "
        "FROM signals "
        "WHERE limit_fillable IS NULL AND timestamp <= ? "
        "ORDER BY id",
        (cutoff,)
    ).fetchall()

    if not rows:
        print("[Phase-A Backfill] Nothing to backfill — all signals already have limit_fillable set "
              "OR they're within the active fill window (monitor_open_signals will set them).")
        return

    print(f"[Phase-A Backfill] Found {len(rows)} signal(s) to evaluate:")
    print()

    updates = []
    for r in rows:
        sig_id     = r["id"]
        token      = r["token"]
        direction  = r["signal"]
        entry      = r["entry_price"]
        ts_str     = r["timestamp"]
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception as e:
            print(f"  #{sig_id} {token}: bad timestamp '{ts_str}' — SKIP")
            continue

        start_ms = int(ts.timestamp() * 1000)
        end_ms   = int((ts + timedelta(minutes=args.window_min)).timestamp() * 1000)

        klines = _binance_5m_klines(token, start_ms, end_ms)
        if not klines:
            print(f"  #{sig_id} {token} {direction} @ ${entry:.4f}: NO KLINES — SKIP")
            continue

        retouched = False
        for kl in klines:
            high = float(kl[2])
            low  = float(kl[3])
            if direction == "SELL" and high >= entry:
                retouched = True; break
            if direction == "BUY"  and low  <= entry:
                retouched = True; break

        result = 1 if retouched else 0
        badge  = "✅ FILLED" if retouched else "❌ MISSED"
        print(f"  #{sig_id} {token} {direction} @ ${entry:.4f} "
              f"(fired {ts_str} UTC, checked {len(klines)} klines) → {badge}")
        updates.append((sig_id, result))
        time.sleep(0.2)  # be polite to Binance

    if not updates:
        print("\n[Phase-A Backfill] No updates to apply.")
        return

    print()
    fill_count = sum(1 for _, r in updates if r == 1)
    miss_count = sum(1 for _, r in updates if r == 0)
    print(f"[Phase-A Backfill] Summary: {len(updates)} signals processed")
    print(f"                   {fill_count} would-be FILLED ({fill_count/len(updates)*100:.0f}%)")
    print(f"                   {miss_count} would-be MISSED ({miss_count/len(updates)*100:.0f}%)")

    if is_dry:
        print()
        print("[Phase-A Backfill] DRY-RUN — no changes written. Re-run with --apply to commit.")
        return

    print()
    print("[Phase-A Backfill] Writing updates...")
    check_at = "backfill_" + now.strftime("%Y-%m-%d_%H:%M:%S")
    for sig_id, fillable in updates:
        conn.execute(
            "UPDATE signals SET limit_fillable=?, fillable_check_at=? WHERE id=?",
            (fillable, check_at, sig_id)
        )
    conn.commit()
    print(f"[Phase-A Backfill] DONE — {len(updates)} rows updated. fillable_check_at='{check_at}'")


if __name__ == "__main__":
    main()
