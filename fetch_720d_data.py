"""Fetch missing-year 5m + 4h OHLCV from Binance for 12 breakout tokens.

PHASE C-BREAKOUT 720D EXTENSION (2026-06-03).

Window:    2024-06-10 → 2025-06-01 (covers the gap left of the existing 365d cache).
Cache out: /home/tradeai/breakout-work/data/ohlcv_cache_720d/<TOKEN>USDT_<TF>_720d.json
           — a merged 720d file (concatenated with the existing 365d cache,
             deduped by timestamp). The existing
             /home/tradeai/TradeAI/data/ohlcv_cache/*_365d.json is read-only.

Per-token coverage report is printed and written to
data/ohlcv_cache_720d/_coverage_report.json.

Rate-limit policy: 5 requests/second hard cap; klines weight=2 → 600 weight/sec
(well below Binance's 1200 weight/minute ceiling). No API key required (public).
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path


BREAKOUT_DIR = Path("/home/tradeai/breakout-work")
EXIST_CACHE  = Path("/home/tradeai/TradeAI/data/ohlcv_cache")
OUT_CACHE    = BREAKOUT_DIR / "data" / "ohlcv_cache_720d"
OUT_CACHE.mkdir(parents=True, exist_ok=True)

TOKENS = ["BTC", "ETH", "XRP", "HBAR", "AVAX", "LINK", "BNB", "ADA", "POL",
          "TON", "ATOM", "BCH"]
TFS = ["5m", "4h"]  # we skip 1m (only the soak's 90d cache uses it; TF_C is excluded)

# Window — fetch this gap, then merge with existing 365d
END_FETCH   = datetime(2025, 6, 1, tzinfo=timezone.utc)   # one day past last bar of existing 365d ≈ 2026-05-30 backref
START_FETCH = datetime(2024, 6, 10, tzinfo=timezone.utc)  # 720d back from 2026-05-31
END_MS_FINAL = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)

# Binance config
BINANCE_BASE = "https://api.binance.com/api/v3/klines"
USER_AGENT = "TradeAI-Phase-C-720D-Fetch/1.0"
LIMIT_PER_REQ = 1000
INTERVAL_MS = {"5m": 5 * 60 * 1000, "4h": 4 * 60 * 60 * 1000}
SLEEP_BETWEEN_REQ = 0.20  # seconds → 5 req/sec → 10 weight/sec → 600/min (50% of cap)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _log(msg):
    print(f"[{_now_iso()}] {msg}", flush=True)


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch klines from Binance in chunks of <= LIMIT_PER_REQ. Returns raw rows."""
    out: list = []
    cur = start_ms
    bar_ms = INTERVAL_MS[interval]
    span_ms = LIMIT_PER_REQ * bar_ms
    while cur < end_ms:
        chunk_end = min(cur + span_ms, end_ms)
        url = (f"{BINANCE_BASE}?symbol={symbol}&interval={interval}&limit={LIMIT_PER_REQ}"
               f"&startTime={cur}&endTime={chunk_end}")
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                    timeout=20) as resp:
                if resp.status != 200:
                    _log(f"    HTTP {resp.status} for {symbol} {interval} at cur={cur}; retrying once")
                    time.sleep(1.0)
                    continue
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            _log(f"    fetch error: {e!r}; sleeping 2s and retrying")
            time.sleep(2.0)
            continue
        if not raw:
            # No data in this window — token may not have existed yet
            # Advance cursor by one chunk to avoid infinite loop
            cur = chunk_end
            time.sleep(SLEEP_BETWEEN_REQ)
            continue
        out.extend(raw)
        # Advance cursor past the LAST returned open-time + bar_ms
        last_open_ms = int(raw[-1][0])
        cur = last_open_ms + bar_ms
        time.sleep(SLEEP_BETWEEN_REQ)
    return out


def rows_to_columns(rows: list) -> dict:
    """Binance row schema: [open_time, open, high, low, close, vol, close_time, ...]"""
    times  = [int(r[0]) for r in rows]
    opens  = [float(r[1]) for r in rows]
    highs  = [float(r[2]) for r in rows]
    lows   = [float(r[3]) for r in rows]
    closes = [float(r[4]) for r in rows]
    return {"times": times, "opens": opens, "highs": highs, "lows": lows, "closes": closes}


def merge_caches(new_cols: dict, existing_cols: dict) -> dict:
    """Merge two column-oriented caches by timestamp; dedup; sort."""
    by_ts: dict = {}
    for src in (new_cols, existing_cols):
        for i, t in enumerate(src["times"]):
            by_ts[t] = (src["opens"][i], src["highs"][i], src["lows"][i], src["closes"][i])
    sorted_ts = sorted(by_ts)
    return {
        "times":  sorted_ts,
        "opens":  [by_ts[t][0] for t in sorted_ts],
        "highs":  [by_ts[t][1] for t in sorted_ts],
        "lows":   [by_ts[t][2] for t in sorted_ts],
        "closes": [by_ts[t][3] for t in sorted_ts],
    }


def integrity_check(cols: dict, interval: str) -> dict:
    """Verify: monotone increasing timestamps, no duplicates, contiguous bars
    (allowing token-not-yet-listed gap at the start)."""
    times = cols["times"]
    n = len(times)
    bar_ms = INTERVAL_MS[interval]
    dupes = sum(1 for i in range(1, n) if times[i] == times[i-1])
    monotonic = all(times[i] > times[i-1] for i in range(1, n))
    # Detect large gaps (> 2× bar) and where they cluster
    gaps = []
    for i in range(1, n):
        gap = times[i] - times[i-1]
        if gap > 2 * bar_ms:
            gaps.append({"ts": times[i-1], "gap_bars": gap // bar_ms - 1,
                         "after_date": datetime.fromtimestamp(times[i-1]/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")})
    return {"n": n, "monotonic": monotonic, "dupes": dupes,
            "gaps_count": len(gaps), "gaps_sample": gaps[:5],
            "first_date": datetime.fromtimestamp(times[0]/1000, tz=timezone.utc).strftime("%Y-%m-%d") if n else None,
            "last_date":  datetime.fromtimestamp(times[-1]/1000, tz=timezone.utc).strftime("%Y-%m-%d") if n else None}


def main():
    _log("=" * 78)
    _log("PHASE C-BREAKOUT 720D — fetch missing year + build merged caches")
    _log("=" * 78)
    _log(f"  Fetch window: {START_FETCH.date()} → {END_FETCH.date()}")
    _log(f"  Output cache: {OUT_CACHE}")
    _log("")

    start_ms = int(START_FETCH.timestamp() * 1000)
    end_ms   = int(END_FETCH.timestamp() * 1000)

    coverage_report: dict = {}

    for tok in TOKENS:
        symbol = f"{tok}USDT"
        coverage_report[tok] = {}
        for tf in TFS:
            _log(f"  → {tok}/{tf}: fetching 2024 gap...")
            rows = fetch_klines(symbol, tf, start_ms, end_ms)
            if not rows:
                _log(f"     no data returned (token may not have existed in 2024 window)")
                coverage_report[tok][tf] = {"new_bars": 0, "status": "NO_2024_DATA"}
                continue
            new_cols = rows_to_columns(rows)

            # Load existing 365d cache for this (token, tf)
            exist_path = EXIST_CACHE / f"{symbol}_{tf}_365d.json"
            if exist_path.exists():
                with open(exist_path) as f:
                    exist_blob = json.load(f)
                exist_cols = exist_blob["data"]
                _log(f"     fetched {len(rows)} new bars; existing 365d has {len(exist_cols['times'])} bars")
                merged = merge_caches(new_cols, exist_cols)
            else:
                _log(f"     fetched {len(rows)} new bars; NO existing 365d cache to merge")
                merged = new_cols

            # Integrity report
            ic = integrity_check(merged, tf)
            coverage_report[tok][tf] = {
                "new_bars": len(rows),
                "merged_bars": ic["n"],
                "first_date": ic["first_date"],
                "last_date":  ic["last_date"],
                "monotonic":  ic["monotonic"],
                "dupes":      ic["dupes"],
                "gaps_count": ic["gaps_count"],
                "gaps_sample": ic["gaps_sample"],
                "status": "OK" if (ic["monotonic"] and ic["dupes"] == 0) else "INTEGRITY_FAIL",
            }
            _log(f"     merged: n={ic['n']:>7} ({ic['first_date']} → {ic['last_date']})  "
                 f"monotonic={ic['monotonic']} dupes={ic['dupes']} gaps={ic['gaps_count']}")

            # Write merged cache
            out_path = OUT_CACHE / f"{symbol}_{tf}_720d.json"
            blob = {
                "schema_version": 1,
                "fetched_at": time.time(),
                "symbol": symbol,
                "interval": tf,
                "days": 720,
                "fetch_window_start": START_FETCH.isoformat(),
                "fetch_window_end":   END_FETCH.isoformat(),
                "data": merged,
            }
            with open(out_path, "w") as f:
                json.dump(blob, f)
            _log(f"     wrote {out_path.name} ({out_path.stat().st_size//1024} KB)")
        _log("")

    # Write coverage report
    cov_path = OUT_CACHE / "_coverage_report.json"
    with open(cov_path, "w") as f:
        json.dump(coverage_report, f, indent=2)
    _log(f"  Coverage report: {cov_path}")

    # Summarize
    _log("")
    _log("  --- COVERAGE SUMMARY ---")
    for tok in TOKENS:
        for tf in TFS:
            d = coverage_report[tok].get(tf, {})
            _log(f"    {tok:<5}/{tf}: status={d.get('status','?'):<18} "
                 f"n={d.get('merged_bars','?'):>7} "
                 f"span={d.get('first_date','?')}→{d.get('last_date','?')}")
    _log("")
    _log("Done.")


if __name__ == "__main__":
    main()
