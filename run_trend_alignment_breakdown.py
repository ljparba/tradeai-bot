"""run_trend_alignment_breakdown.py — DESCRIPTIVE per-trend-alignment analysis (in-memory).

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B. For each backtest signal,
CAUSALLY compute the token's own 1H-trend and 4H-trend at signal time (only bars fully
closed BEFORE the entry timestamp — no forward/outcome bars), then bucket WITH / AGAINST /
NEUTRAL. Reports 1H, 4H, combined, confounds (regime), and OOS 70/30 stability. NO DB writes.

TREND DEFINITION (simple, standard, stated explicitly):
  Per ref TF (1H, 4H) on the TOKEN's own bars:
    EMA period = 50; slope lookback = 10 bars.
    UP    if close[last_closed] > EMA[last_closed] AND EMA rising  (EMA[i] > EMA[i-10])
    DOWN  if close[last_closed] < EMA[last_closed] AND EMA falling (EMA[i] < EMA[i-10])
    NEUTRAL otherwise (price/EMA disagree with slope, or flat).
  "last_closed" = the most recent bar whose CLOSE time <= signal entry time (causal).
  Alignment: WITH = BUY&UP or SELL&DOWN ; AGAINST = BUY&DOWN or SELL&UP ; NEUTRAL = trend flat.
"""
import os, sys, json, bisect, importlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_BD = Path(__file__).resolve().parent
sys.path.insert(0, str(_BD)); sys.path.insert(0, "/home/tradeai/TradeAI")

import run_tf_grid as G
from crt_engine import compute_crt_trade_economics as compute_econ
from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT
from execution import simulate_execution, derive_seed

def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
WIN = {"start": ms(2024, 6, 10), "end": ms(2026, 5, 31), "dir": _BD/"data"/"ohlcv_cache_720d", "suf": "720d"}
G.START_MS = WIN["start"]; G.END_MS = WIN["end"]

def load_cached(tok, tf):
    p = WIN["dir"]/f"{tok}USDT_{tf}_{WIN['suf']}.json"
    if not p.exists(): return None
    inner = (json.load(open(p)) or {}).get("data")
    if not inner: return None
    t = inner["times"]; i0 = bisect.bisect_left(t, WIN["start"]); i1 = bisect.bisect_right(t, WIN["end"])
    if i1 - i0 < 30: return None
    return {k: inner[k][i0:i1] for k in ("opens","highs","lows","closes")} | {"times": t[i0:i1]}
G.load_cached = load_cached

os.environ.update(G.LOCKED_KNOBS)
import breakout_engine as _be
importlib.reload(_be)
detect = _be.detect_h4_breakout; compute_sl_tp = _be.compute_breakout_sl_tp
CFGS = [c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h", "B_5m_1h")]
EMA_N, SLOPE_K = 50, 10
TF_DUR_MS = {"1h": 3600_000, "4h": 4*3600_000}

def ema_series(closes, n):
    a = 2.0/(n+1); out = []; e = closes[0]
    for c in closes:
        e = a*c + (1-a)*e; out.append(e)
    return out

# Per-token causal trend model for 1h + 4h
TREND = {}  # (token, tf) -> (times, closes, ema)
def get_trend_model(tok, tf):
    key = (tok, tf)
    if key not in TREND:
        c = load_cached(tok, tf)
        TREND[key] = None if c is None else (c["times"], c["closes"], ema_series(c["closes"], EMA_N))
    return TREND[key]

def trend_state(tok, tf, entry_ts_ms):
    m = get_trend_model(tok, tf)
    if m is None: return "NEUTRAL"
    times, closes, ema = m
    # last bar fully CLOSED before entry: open_time + dur <= entry  -> open_time <= entry - dur
    i = bisect.bisect_right(times, entry_ts_ms - TF_DUR_MS[tf]) - 1
    if i < SLOPE_K: return "NEUTRAL"
    up = closes[i] > ema[i] and ema[i] > ema[i-SLOPE_K]
    dn = closes[i] < ema[i] and ema[i] < ema[i-SLOPE_K]
    return "UP" if up else "DOWN" if dn else "NEUTRAL"

def align(direction, st):
    if st == "NEUTRAL": return "NEUTRAL"
    with_ = (direction == "BUY" and st == "UP") or (direction == "SELL" and st == "DOWN")
    return "WITH" if with_ else "AGAINST"

def regime_map():
    c = load_cached("BTC", "4h"); by = {}
    for t, cl in zip(c["times"], c["closes"]):
        by[datetime.fromtimestamp(t/1000, timezone.utc).strftime("%Y-%m-%d")] = cl
    ds = sorted(by); cs = [by[d] for d in ds]; r = {}
    for i, d in enumerate(ds):
        if i < 30: r[d] = "RANGE"; continue
        sma = sum(cs[i-30:i])/30; c0 = cs[i]
        r[d] = "BULL" if c0 > sma*1.03 else "BEAR" if c0 < sma*0.97 else "RANGE"
    return r
REGIME = regime_map()

def st(rs):
    n = len(rs); pos = sum(1 for r in rs if r > 0)
    return n, (pos/n if n else 0), (sum(rs)/n if n else 0), sum(rs)

print("="*100)
print("TREND-ALIGNMENT BREAKDOWN — 720d, Config 14, post-TP2 model, friction (in-memory, CAUSAL)")
print(f"trend = EMA{EMA_N} + slope({SLOPE_K}) on token's own 1H/4H bars, cutoff = last bar closed before entry")
print("="*100)
for cfg in CFGS:
    clean = []; cache = {}
    for tok in G.TOKENS:
        clean += G.run_one_token(tok, cfg, detect, compute_sl_tp, compute_econ, TOKEN_RT_COST, ROUND_TRIP_COST_PCT)
        cache[tok] = G.load_cached(tok, cfg["entry_tf"])
    fric = G.apply_friction(clean, cfg, cache, derive_seed, simulate_execution)
    # tag each signal
    for s in fric:
        ets = int(datetime.strptime(s["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()*1000)
        s["_1h"] = align(s["signal"], trend_state(s["token"], "1h", ets))
        s["_4h"] = align(s["signal"], trend_state(s["token"], "4h", ets))
    N = len(fric)
    print(f"\n############ {cfg['id']}  (total n={N})")

    def bucket_report(keyfn, title, order):
        print(f"  -- {title} --")
        print(f"    {'bucket':<14}{'n':>6}{'%':>7}{'WR%':>7}{'avg_R':>8}{'sum_R':>9}   outcome[WIN/PT2/PT2_T1/PT1/LOSS]")
        by = defaultdict(list)
        for s in fric: by[keyfn(s)].append(s)
        for b in order:
            sg = by.get(b, [])
            if not sg: print(f"    {b:<14}{0:>6}"); continue
            rs = [x["realized_r"] for x in sg]; n, wr, avg, sm = st(rs)
            oc = Counter(x["outcome"] for x in sg)
            od = "/".join(str(oc.get(k,0)) for k in ["WIN","PARTIAL_TP2","PARTIAL_TP2_T1","PARTIAL_TP1","LOSS"])
            print(f"    {b:<14}{n:>6}{100*n/N:>6.1f}%{wr*100:>6.1f}%{avg:>+8.4f}{sm:>+9.1f}   [{od}]")
        return by

    bucket_report(lambda s: s["_1h"], "1H-TREND alignment", ["WITH","AGAINST","NEUTRAL"])
    bucket_report(lambda s: s["_4h"], "4H-BIAS alignment", ["WITH","AGAINST","NEUTRAL"])

    def combo(s):
        a1, a4 = s["_1h"], s["_4h"]
        if a1=="WITH" and a4=="WITH": return "with-both"
        if a1=="WITH" and a4!="WITH": return "with-1H-only"
        if a4=="WITH" and a1!="WITH": return "with-4H-only"
        if a1=="AGAINST" and a4=="AGAINST": return "against-both"
        return "other(neutral-mix)"
    bucket_report(combo, "COMBINED 1H+4H", ["with-both","with-1H-only","with-4H-only","against-both","other(neutral-mix)"])

    # Confound: alignment x regime (1H)
    print("  -- confound: 1H-alignment x REGIME (avg_R, n) --")
    for b in ["WITH","AGAINST","NEUTRAL"]:
        d = defaultdict(list)
        for s in fric:
            if s["_1h"]==b: d[REGIME.get(s["ts"][:10],"RANGE")].append(s["realized_r"])
        parts = "  ".join(f"{rg}:{(sum(v)/len(v)):+.3f}(n{len(v)})" for rg,v in sorted(d.items()))
        print(f"    {b:<8} {parts}")

    # Stability OOS 70/30 per 1H + 4H bucket
    for label, kf in [("1H", lambda s:s["_1h"]), ("4H", lambda s:s["_4h"])]:
        print(f"  -- STABILITY {label}: OOS 70/30 (train avg_R -> test avg_R) --")
        by = defaultdict(list)
        for s in fric: by[kf(s)].append(s)
        for b in ["WITH","AGAINST","NEUTRAL"]:
            sg = sorted(by.get(b, []), key=lambda s: s["ts"])
            if len(sg) < 10: print(f"    {b:<8} n<10"); continue
            cut = int(len(sg)*0.7); tr=[x["realized_r"] for x in sg[:cut]]; te=[x["realized_r"] for x in sg[cut:]]
            print(f"    {b:<8} train n{len(tr)} avg{(sum(tr)/len(tr)):+.4f}  ->  test n{len(te)} avg{(sum(te)/len(te)):+.4f}")
print("\nDone.")
