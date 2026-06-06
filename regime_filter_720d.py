"""Apply a CAUSAL regime filter to the 720d backtest signals.

PHASE C-BREAKOUT REGIME-FILTER VARIANT (2026-06-03).

PRE-REGISTERED RULE — frozen before any code execution:
  - Macro proxy: BTC 4h closes (from data/ohlcv_cache_720d/BTCUSDT_4h_720d.json)
  - MA window: N=50 (4h bars ≈ 8.33 days)
  - Neutral band: X=±2% around MA
  - At signal time t, use the LATEST 4h bar with close_time <= t (the most
    recently CLOSED bar) and its 50 prior closed bars to compute MA50. NO
    look-ahead — the current 4h bar's close (which is in the future at t) is
    NEVER used.
  - Classification:
        BULL    : btc_close > MA50 * 1.02   → keep BUY only,  reject SELL
        BEAR    : btc_close < MA50 * 0.98   → keep SELL only, reject BUY
        NEUTRAL : 0.98*MA50 <= btc_close <= 1.02*MA50  → keep both

Input sources (read existing 720d backtest rows; do NOT re-run the engine):
  H4_BREAKOUT_TF_A_5m_4h_CLEAN_720D     → write H4_BREAKOUT_TF_A_5m_4h_CLEAN_REGIME
  H4_BREAKOUT_TF_A_5m_4h_FRICTION_720D  → write H4_BREAKOUT_TF_A_5m_4h_FRICTION_REGIME
  H4_BREAKOUT_TF_B_5m_1h_CLEAN_720D     → write H4_BREAKOUT_TF_B_5m_1h_CLEAN_REGIME
  H4_BREAKOUT_TF_B_5m_1h_FRICTION_720D  → write H4_BREAKOUT_TF_B_5m_1h_FRICTION_REGIME

Output: filtered rows in backtest_signals with the new _REGIME source tag,
preserving every other column. The original _720D rows are NOT modified.

Reads:  breakout.db (writes new rows; existing rows untouched).
"""
from __future__ import annotations
import bisect
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("/home/tradeai/breakout-work/data/breakout.db")
CACHE_4H = Path("/home/tradeai/breakout-work/data/ohlcv_cache_720d/BTCUSDT_4h_720d.json")

# === PRE-REGISTERED PARAMETERS ===
MA_PERIOD = 50           # bars
NEUTRAL_BAND_PCT = 0.02  # ±2%
BAR_DUR_MS = 4 * 60 * 60 * 1000  # 4h

SRC_PAIRS = [
    ("H4_BREAKOUT_TF_A_5m_4h_CLEAN_720D",    "H4_BREAKOUT_TF_A_5m_4h_CLEAN_REGIME"),
    ("H4_BREAKOUT_TF_A_5m_4h_FRICTION_720D", "H4_BREAKOUT_TF_A_5m_4h_FRICTION_REGIME"),
    ("H4_BREAKOUT_TF_B_5m_1h_CLEAN_720D",    "H4_BREAKOUT_TF_B_5m_1h_CLEAN_REGIME"),
    ("H4_BREAKOUT_TF_B_5m_1h_FRICTION_720D", "H4_BREAKOUT_TF_B_5m_1h_FRICTION_REGIME"),
]


def load_btc_4h():
    with open(CACHE_4H) as f:
        blob = json.load(f)
    d = blob["data"]
    return d["times"], d["closes"]


def regime_at(times, closes, signal_ts_ms):
    """Classify BTC's regime at signal time using only CLOSED bars.

    Returns: ("BULL"|"BEAR"|"NEUTRAL"|"INSUFFICIENT", btc_close, ma50)
    """
    # Most recent bar whose close_time <= signal_ts_ms
    # times[i] = open_time of bar i; close_time = times[i] + BAR_DUR_MS
    # We want the largest i such that times[i] + BAR_DUR_MS <= signal_ts_ms
    #   <=> times[i] <= signal_ts_ms - BAR_DUR_MS
    cutoff = signal_ts_ms - BAR_DUR_MS
    i = bisect.bisect_right(times, cutoff) - 1
    if i < MA_PERIOD - 1:
        return ("INSUFFICIENT", None, None)
    window = closes[i - (MA_PERIOD - 1): i + 1]  # 50 bars including bar i
    ma = sum(window) / MA_PERIOD
    btc_close = closes[i]
    upper = ma * (1.0 + NEUTRAL_BAND_PCT)
    lower = ma * (1.0 - NEUTRAL_BAND_PCT)
    if btc_close > upper:
        return ("BULL", btc_close, ma)
    if btc_close < lower:
        return ("BEAR", btc_close, ma)
    return ("NEUTRAL", btc_close, ma)


def keep_signal(regime: str, direction: str) -> bool:
    if regime == "BULL":    return direction == "BUY"
    if regime == "BEAR":    return direction == "SELL"
    if regime == "NEUTRAL": return True
    return False   # INSUFFICIENT — drop (cold-start safety)


def main():
    times_4h, closes_4h = load_btc_4h()
    first = datetime.fromtimestamp(times_4h[0]/1000, tz=timezone.utc).date()
    last  = datetime.fromtimestamp(times_4h[-1]/1000, tz=timezone.utc).date()
    print(f"BTC 4h cache: {len(times_4h)} bars, {first} → {last}")
    print(f"PRE-REGISTERED rule: MA={MA_PERIOD} bars (~{MA_PERIOD*4/24:.1f}d), neutral band=±{NEUTRAL_BAND_PCT*100:.0f}%")
    print(f"Causal: signal time t uses LAST closed 4h bar (no look-ahead)")
    print()

    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA journal_mode=WAL")
    cur = con.cursor()

    # Detect column list of backtest_signals so we can copy every column except id
    cols = [r[1] for r in cur.execute("PRAGMA table_info(backtest_signals)")]
    cols_no_id = [c for c in cols if c != "id"]
    cols_csv = ", ".join(cols_no_id)
    placeholders = ", ".join(["?"] * len(cols_no_id))

    for src_in, src_out in SRC_PAIRS:
        # Wipe any prior _REGIME rows under this output tag (idempotent rerun safety)
        n_existing = cur.execute("DELETE FROM backtest_signals WHERE source=?", (src_out,)).rowcount
        if n_existing:
            print(f"  ({src_out}: cleared {n_existing} pre-existing rows)")

        rows = list(cur.execute(f"SELECT {cols_csv} FROM backtest_signals WHERE source=?", (src_in,)))
        n_in = len(rows)
        if not n_in:
            print(f"  {src_in}: 0 rows — skipping")
            continue

        # Map column names to indexes for ts and signal lookup
        idx_ts     = cols_no_id.index("ts")
        idx_dir    = cols_no_id.index("signal")
        idx_source = cols_no_id.index("source")

        kept, dropped_bear_buy, dropped_bull_sell, dropped_insuf = 0, 0, 0, 0
        regime_count = {"BULL":0, "BEAR":0, "NEUTRAL":0, "INSUFFICIENT":0}
        new_rows = []
        for r in rows:
            ts_str = r[idx_ts]
            signal_ts_ms = int(datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                                .replace(tzinfo=timezone.utc).timestamp() * 1000)
            regime, _, _ = regime_at(times_4h, closes_4h, signal_ts_ms)
            regime_count[regime] += 1
            direction = r[idx_dir]
            if not keep_signal(regime, direction):
                if regime == "BULL" and direction == "SELL": dropped_bull_sell += 1
                elif regime == "BEAR" and direction == "BUY": dropped_bear_buy += 1
                elif regime == "INSUFFICIENT": dropped_insuf += 1
                continue
            # Keep — re-emit with new source tag
            new_row = list(r)
            new_row[idx_source] = src_out
            new_rows.append(tuple(new_row))
            kept += 1

        # Insert kept rows in one batch
        cur.executemany(f"INSERT INTO backtest_signals ({cols_csv}) VALUES ({placeholders})", new_rows)

        # Also write a backtest_runs row for accounting
        cur.execute(
            "INSERT INTO backtest_runs (run_date, days, total_signals, overall_wr, "
            " avg_rr, status, summary, config_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), 720, kept, 0.0, 0.0,
             "DONE", f"REGIME-FILTERED variant of {src_in}",
             f"REGIME_MA{MA_PERIOD}_BAND{int(NEUTRAL_BAND_PCT*100)}"),
        )
        con.commit()

        keep_pct = kept/n_in*100 if n_in else 0
        print(f"  {src_in} → {src_out}")
        print(f"     IN:   n={n_in:>5} | regimes: BULL={regime_count['BULL']:>5} BEAR={regime_count['BEAR']:>5} NEUTRAL={regime_count['NEUTRAL']:>5} INSUF={regime_count['INSUFFICIENT']:>3}")
        print(f"     OUT:  kept={kept:>5} ({keep_pct:.1f}% of input)")
        print(f"     DROPPED: BULL/SELL={dropped_bull_sell}, BEAR/BUY={dropped_bear_buy}, INSUF={dropped_insuf}")
        print()

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
