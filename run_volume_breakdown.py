"""run_volume_breakdown.py — DESCRIPTIVE per-volume analysis (in-memory).

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B. Buckets EXISTING signals
by breakout/MSS-bar volume ratio (causal). NO signal blocked, NO filter, NO DB writes.

VOL DEFINITION (causal, no look-ahead):
  vol_ratio = volume[MSS bar] / mean(volume of the prior N=20 5m bars before the MSS bar).
  MSS bar = the 5m confirmation bar (entry bar - 1). Uses only the MSS bar + 20 bars before
  it — no forward/outcome bars. Buckets: LOW <0.8, NORMAL 0.8-1.5, HIGH >1.5.
"""
import os, sys, json, bisect, importlib, statistics
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
WIN = {"start": ms(2024,6,10), "end": ms(2026,5,31), "dir": _BD/"data"/"ohlcv_cache_720d", "suf": "720d"}
G.START_MS = WIN["start"]; G.END_MS = WIN["end"]
VOL_DIR = _BD / "data" / "vol_cache_720d"
N_LB = 20

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
CFGS = [c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h","B_5m_1h")]

VOL = {}  # token -> (times, vols)
def get_vol(tok):
    if tok not in VOL:
        fp = VOL_DIR / f"{tok}USDT_vol.json"
        if not fp.exists(): VOL[tok] = None
        else:
            d = json.load(open(fp)); VOL[tok] = (d["times"], d["vols"])
    return VOL[tok]

def vol_ratio(tok, entry_ts_ms):
    m = get_vol(tok)
    if m is None: return None
    times, vols = m
    mss_ms = entry_ts_ms - 300000  # MSS bar opens one 5m before entry bar
    i = bisect.bisect_left(times, mss_ms)
    if i >= len(times) or times[i] != mss_ms: return None  # exact 5m-grid match
    if i < N_LB: return None
    prior = vols[i-N_LB:i]
    avg = sum(prior)/len(prior)
    if avg <= 0: return None
    return vols[i]/avg

def regime_map():
    c = load_cached("BTC","4h"); by = {}
    for t, cl in zip(c["times"], c["closes"]):
        by[datetime.fromtimestamp(t/1000, timezone.utc).strftime("%Y-%m-%d")] = cl
    ds = sorted(by); cs = [by[d] for d in ds]; r = {}
    for i,d in enumerate(ds):
        if i < 30: r[d]="RANGE"; continue
        sma=sum(cs[i-30:i])/30; c0=cs[i]
        r[d]="BULL" if c0>sma*1.03 else "BEAR" if c0<sma*0.97 else "RANGE"
    return r
REGIME = regime_map()

def conf_of(s):
    et = s.get("entry_type",""); return "FVG" if "_FVG_" in et else "OB" if "_OB_" in et else "?"
def vbucket(vr):
    if vr is None: return "UNKNOWN"
    return "LOW" if vr < 0.8 else "NORMAL" if vr <= 1.5 else "HIGH"
def stat(rs):
    n=len(rs); pos=sum(1 for r in rs if r>0)
    return n,(pos/n if n else 0),(sum(rs)/n if n else 0),sum(rs)

print("="*100)
print("VOLUME BREAKDOWN — 720d, Config 14, post-TP2 model, friction (in-memory, CAUSAL)")
print(f"vol_ratio = MSS-bar vol / mean(prior {N_LB} 5m bars); buckets LOW<0.8 NORMAL0.8-1.5 HIGH>1.5")
print("="*100)
ORDER = ["LOW","NORMAL","HIGH","UNKNOWN"]
for cfg in CFGS:
    clean=[]; cache={}
    for tok in G.TOKENS:
        clean += G.run_one_token(tok, cfg, detect, compute_sl_tp, compute_econ, TOKEN_RT_COST, ROUND_TRIP_COST_PCT)
        cache[tok] = G.load_cached(tok, cfg["entry_tf"])
    fric = G.apply_friction(clean, cfg, cache, derive_seed, simulate_execution)
    for s in fric:
        ets = int(datetime.strptime(s["ts"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()*1000)
        s["_vr"] = vol_ratio(s["token"], ets); s["_vb"] = vbucket(s["_vr"])
    N = len(fric); known = [s for s in fric if s["_vr"] is not None]
    vrs = sorted(s["_vr"] for s in known)
    terc = (vrs[len(vrs)//3], vrs[2*len(vrs)//3]) if vrs else (0,0)
    print(f"\n############ {cfg['id']}  (total n={N}, vol-known n={len(known)}; tercile cuts ~{terc[0]:.2f}/{terc[1]:.2f})")
    by = defaultdict(list)
    for s in fric: by[s["_vb"]].append(s)
    print(f"  {'bucket':<9}{'n':>6}{'%':>7}{'WR%':>7}{'avg_R':>8}{'sum_R':>9}   outcome[WIN/PT2/PT2_T1/PT1/LOSS]")
    for b in ORDER:
        sg = by.get(b, [])
        if not sg: continue
        rs=[x["realized_r"] for x in sg]; n,wr,avg,sm = stat(rs)
        oc = Counter(x["outcome"] for x in sg)
        od = "/".join(str(oc.get(k,0)) for k in ["WIN","PARTIAL_TP2","PARTIAL_TP2_T1","PARTIAL_TP1","LOSS"])
        print(f"  {b:<9}{n:>6}{100*n/N:>6.1f}%{wr*100:>6.1f}%{avg:>+8.4f}{sm:>+9.1f}   [{od}]")
    # Confounds
    print("  -- confound: vol-bucket x DIRECTION (n, avg_R) --")
    for b in ["LOW","NORMAL","HIGH"]:
        d = {dd:[x["realized_r"] for x in by.get(b,[]) if x["signal"]==dd] for dd in ("BUY","SELL")}
        print(f"    {b:<7} " + " ".join(f"{dd}:n{len(d[dd])} avg{(sum(d[dd])/len(d[dd])):+.3f}" if d[dd] else f"{dd}:n0" for dd in ("BUY","SELL")))
    print("  -- confound: vol-bucket x CONFLUENCE (FVG/OB) [FVG/OB label drift — don't over-read] --")
    for b in ["LOW","NORMAL","HIGH"]:
        d = {cc:[x["realized_r"] for x in by.get(b,[]) if conf_of(x)==cc] for cc in ("FVG","OB")}
        print(f"    {b:<7} " + " ".join(f"{cc}:n{len(d[cc])} avg{(sum(d[cc])/len(d[cc])):+.3f}" if d[cc] else f"{cc}:n0" for cc in ("FVG","OB")))
    print("  -- confound: vol-bucket x REGIME (avg_R, n) --")
    for b in ["LOW","NORMAL","HIGH"]:
        d = defaultdict(list)
        for x in by.get(b,[]): d[REGIME.get(x["ts"][:10],"RANGE")].append(x["realized_r"])
        print(f"    {b:<7} " + "  ".join(f"{rg}:{(sum(v)/len(v)):+.3f}(n{len(v)})" for rg,v in sorted(d.items())))
    print("  -- confound: vol-bucket x TOKEN (top 4) --")
    for b in ["LOW","NORMAL","HIGH"]:
        print(f"    {b:<7} {Counter(x['token'] for x in by.get(b,[])).most_common(4)}")
    # Stability
    print("  -- STABILITY: OOS 70/30 (train avg_R -> test avg_R) --")
    for b in ["LOW","NORMAL","HIGH"]:
        sg = sorted(by.get(b,[]), key=lambda s:s["ts"])
        if len(sg)<10: print(f"    {b:<7} n<10"); continue
        cut=int(len(sg)*0.7); tr=[x["realized_r"] for x in sg[:cut]]; te=[x["realized_r"] for x in sg[cut:]]
        print(f"    {b:<7} train n{len(tr)} avg{(sum(tr)/len(tr)):+.4f}  ->  test n{len(te)} avg{(sum(te)/len(te)):+.4f}")
print("\nDone.")
