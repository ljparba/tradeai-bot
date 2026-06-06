"""fetch_vol_720d.py — fetch 5m VOLUME for the 720d window (the price cache lacks it).
Resume-safe: skips tokens already cached. Cache files only (NOT a DB write)."""
import json, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

_BD = Path(__file__).resolve().parent
OUT = _BD / "data" / "vol_cache_720d"
OUT.mkdir(exist_ok=True)
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
START, END = ms(2024, 6, 10), ms(2026, 5, 31)
TOKENS = ["BTC","ETH","XRP","HBAR","AVAX","LINK","BNB","ADA","POL","TON","ATOM","BCH"]

def fetch_page(sym, start):
    url = (f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=5m"
           f"&limit=1000&startTime={start}&endTime={END}")
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vol-fetch/1"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                time.sleep(2 * (attempt + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1); continue
    return []

for tok in TOKENS:
    fp = OUT / f"{tok}USDT_vol.json"
    if fp.exists():
        print(f"[skip] {tok} cached"); continue
    sym = f"{tok}USDT"; times = []; vols = []; cur = START
    while cur < END:
        page = fetch_page(sym, cur)
        if not page:
            break
        for k in page:
            t = int(k[0])
            if t > END: break
            times.append(t); vols.append(float(k[5]))
        cur = int(page[-1][0]) + 300000
        if len(page) < 1000:
            break
        time.sleep(0.12)
    json.dump({"times": times, "vols": vols}, open(fp, "w"))
    f = lambda x: datetime.fromtimestamp(x/1000, timezone.utc).strftime("%Y-%m-%d")
    print(f"[done] {tok}: n={len(times)} {f(times[0])}->{f(times[-1])}" if times else f"[empty] {tok}")
print("ALL DONE")
