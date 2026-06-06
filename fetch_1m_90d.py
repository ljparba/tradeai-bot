"""
Fetch 90 days of 1-minute klines for the 12-token universe from Binance REST.

Output: /home/tradeai/breakout-work/data/cache_1m_90d/{SYMBOL}_1m_90d.json
Format identical to /home/tradeai/TradeAI/data/ohlcv_cache/*.json:
    {"schema_version": 1, "symbol": "BTCUSDT", "interval": "1m",
     "days": 90, "data": {"opens":[...], "highs":[...], "lows":[...],
                          "closes":[...], "volumes":[...], "times":[...]}}

Rate limiting: Binance klines endpoint with limit=1500 costs weight=10.
6000-weight/min ceiling → 600 such req/min theoretical. Safe cap: 300/min
(=200ms between requests).

90 days × 24 × 60 = 129,600 1M bars per token. At limit=1500 per fetch,
that's 87 fetches per token × 12 = 1044 total. At 300/min → ~3.5 min.
"""
from __future__ import annotations

import json
import os
import sys
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TOKENS = ["BTC", "ETH", "XRP", "HBAR", "AVAX", "LINK", "BNB",
          "ADA", "POL", "TON", "ATOM", "BCH"]
SYMBOL_OF = {t: f"{t}USDT" for t in TOKENS}

BINANCE = "https://api.binance.com/api/v3/klines"
LIMIT_PER_REQ = 1000   # Binance kline endpoint max
INTERVAL = "1m"
DAYS = 90

OUT_DIR = Path(__file__).resolve().parent / "data" / "cache_1m_90d"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# End at the cache freeze date so the comparison aligns with existing 5M/1H/4H caches
END_MS = int(datetime(2026, 5, 31, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
START_MS = END_MS - DAYS * 24 * 60 * 60 * 1000


def _sleep_for_rate(prev_ts: float, min_gap: float = 0.2) -> float:
    """Sleep so requests come no faster than `min_gap` apart. Returns new ts."""
    now = _time.time()
    elapsed = now - prev_ts
    if elapsed < min_gap:
        _time.sleep(min_gap - elapsed)
    return _time.time()


def fetch_chunk(symbol: str, start_ms: int, end_ms: int) -> list:
    """Fetch one paginated chunk of klines. Returns raw kline rows."""
    params = {
        "symbol":    symbol,
        "interval":  INTERVAL,
        "startTime": start_ms,
        "endTime":   end_ms,
        "limit":     LIMIT_PER_REQ,
    }
    url = f"{BINANCE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "TradeAI-TFcompare/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    _time.sleep(2 ** attempt)
                    continue
                body = resp.read()
                return json.loads(body.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"    [{symbol}] retry {attempt+1}: {e!r}", flush=True)
            _time.sleep(1.5 ** attempt)
    return []


def fetch_token(symbol: str) -> dict:
    """Fetch all 1M bars in [START_MS, END_MS) for one symbol. Paginates."""
    opens, highs, lows, closes, vols, times = [], [], [], [], [], []
    cursor = START_MS
    prev_ts = 0.0
    page = 0
    while cursor < END_MS:
        prev_ts = _sleep_for_rate(prev_ts)
        chunk = fetch_chunk(symbol, cursor, END_MS)
        if not chunk:
            print(f"    [{symbol}] empty chunk at {cursor}, stopping", flush=True)
            break
        for row in chunk:
            opens.append(float(row[1]))
            highs.append(float(row[2]))
            lows.append(float(row[3]))
            closes.append(float(row[4]))
            vols.append(float(row[5]))
            times.append(int(row[0]))
        # advance cursor past the last bar in this chunk
        last_open = chunk[-1][0]
        cursor = int(last_open) + 60 * 1000  # +1 minute
        page += 1
        if page % 20 == 0:
            done = (cursor - START_MS) / (END_MS - START_MS) * 100
            print(f"    [{symbol}] page {page}, {len(times):>6} bars, {done:.0f}%", flush=True)
        # NOTE: do NOT break on chunk_size < LIMIT_PER_REQ — Binance can return
        # a short chunk mid-stream (rate-limit smoothing, gap-fill). Loop until
        # cursor reaches END_MS OR an empty chunk signals the live edge.
        if len(chunk) == 0:
            break
    return {
        "opens":   opens, "highs":  highs, "lows":   lows,
        "closes":  closes, "volumes": vols, "times":  times,
    }


def main():
    print(f"=== 1M fetch — 12 tokens, {DAYS} days ending {datetime.fromtimestamp(END_MS/1000, timezone.utc):%Y-%m-%d %H:%M} ===")
    print(f"  output dir: {OUT_DIR}")
    print()
    t0 = _time.time()
    for tok in TOKENS:
        symbol = SYMBOL_OF[tok]
        out_path = OUT_DIR / f"{symbol}_1m_90d.json"
        if out_path.exists():
            existing = json.load(open(out_path))
            n = len(existing.get("data", {}).get("times", []))
            print(f"  {tok:>5}: cached n={n}, skipping (delete file to refetch)")
            continue
        print(f"  {tok:>5}: fetching from Binance…")
        data = fetch_token(symbol)
        n = len(data["times"])
        if n == 0:
            print(f"    [{symbol}] no data fetched — skipping")
            continue
        first = datetime.fromtimestamp(data["times"][0]/1000, timezone.utc).strftime('%Y-%m-%d %H:%M')
        last  = datetime.fromtimestamp(data["times"][-1]/1000, timezone.utc).strftime('%Y-%m-%d %H:%M')
        payload = {
            "schema_version": 1,
            "symbol":   symbol,
            "interval": INTERVAL,
            "days":     DAYS,
            "data":     data,
        }
        tmp = out_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, out_path)
        print(f"    [{symbol}] done — {n} bars, {first} → {last} ({out_path.stat().st_size//1024} KB)")
    print(f"\n  Total elapsed: {_time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
