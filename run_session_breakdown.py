"""run_session_breakdown.py — DESCRIPTIVE per-session analysis (in-memory).

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B. Buckets EXISTING signals by
UTC session. NO signal blocked, NO filter, NO DB writes. Adds outcome dist, session x volume
confound (does a 'NY edge' just re-surface the inverted-volume effect?), per-session OOS 70/30.

Session (UTC, from entry ts): ASIAN 00-08 / LONDON 08-13 / LDN_NY_OVL 13-16 / NY 16-21 / LATE_US 21-24.
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

def ms(y,m,d): return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)
WIN={"start":ms(2024,6,10),"end":ms(2026,5,31),"dir":_BD/"data"/"ohlcv_cache_720d","suf":"720d"}
G.START_MS=WIN["start"]; G.END_MS=WIN["end"]
VOL_DIR=_BD/"data"/"vol_cache_720d"; N_LB=20

def load_cached(tok,tf):
    p=WIN["dir"]/f"{tok}USDT_{tf}_{WIN['suf']}.json"
    if not p.exists(): return None
    inner=(json.load(open(p)) or {}).get("data")
    if not inner: return None
    t=inner["times"]; i0=bisect.bisect_left(t,WIN["start"]); i1=bisect.bisect_right(t,WIN["end"])
    if i1-i0<30: return None
    return {k:inner[k][i0:i1] for k in ("opens","highs","lows","closes")}|{"times":t[i0:i1]}
G.load_cached=load_cached
os.environ.update(G.LOCKED_KNOBS)
import breakout_engine as _be
importlib.reload(_be)
detect=_be.detect_h4_breakout; compute_sl_tp=_be.compute_breakout_sl_tp
CFGS=[c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h","B_5m_1h")]

VOLC={}
def get_vol(tok):
    if tok not in VOLC:
        fp=VOL_DIR/f"{tok}USDT_vol.json"
        VOLC[tok]=None if not fp.exists() else (lambda d:(d["times"],d["vols"]))(json.load(open(fp)))
    return VOLC[tok]
def volratio(tok,ets):
    m=get_vol(tok)
    if m is None: return None
    times,vols=m; mss=ets-300000; i=bisect.bisect_left(times,mss)
    if i>=len(times) or times[i]!=mss or i<N_LB: return None
    avg=sum(vols[i-N_LB:i])/N_LB
    return None if avg<=0 else vols[i]/avg

def regime_map():
    c=load_cached("BTC","4h"); by={}
    for t,cl in zip(c["times"],c["closes"]):
        by[datetime.fromtimestamp(t/1000,timezone.utc).strftime("%Y-%m-%d")]=cl
    ds=sorted(by); cs=[by[d] for d in ds]; r={}
    for i,d in enumerate(ds):
        if i<30: r[d]="RANGE"; continue
        sma=sum(cs[i-30:i])/30; c0=cs[i]
        r[d]="BULL" if c0>sma*1.03 else "BEAR" if c0<sma*0.97 else "RANGE"
    return r
REGIME=regime_map()
def sess(ts):
    h=int(ts[11:13]); return "ASIAN" if h<8 else "LONDON" if h<13 else "LDN_NY_OVL" if h<16 else "NY" if h<21 else "LATE_US"
def stat(rs):
    n=len(rs); pos=sum(1 for r in rs if r>0); return n,(pos/n if n else 0),(sum(rs)/n if n else 0),sum(rs)
def split(sg):
    d={dd:[x["realized_r"] for x in sg if x["signal"]==dd] for dd in ("BUY","SELL")}
    return " ".join(f"{dd}:n{len(d[dd])} avg{(sum(d[dd])/len(d[dd])):+.3f}" if d[dd] else f"{dd}:n0" for dd in ("BUY","SELL"))
SORD=["ASIAN","LONDON","LDN_NY_OVL","NY","LATE_US"]

print("="*104)
print("SESSION BREAKDOWN — 720d, Config 14, post-TP2 model, friction (in-memory)")
print("="*104)
for cfg in CFGS:
    clean=[]; cache={}
    for tok in G.TOKENS:
        clean+=G.run_one_token(tok,cfg,detect,compute_sl_tp,compute_econ,TOKEN_RT_COST,ROUND_TRIP_COST_PCT)
        cache[tok]=G.load_cached(tok,cfg["entry_tf"])
    fric=G.apply_friction(clean,cfg,cache,derive_seed,simulate_execution)
    for s in fric:
        ets=int(datetime.strptime(s["ts"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()*1000)
        s["_sess"]=sess(s["ts"]); s["_vr"]=volratio(s["token"],ets)
    N=len(fric); overall=sum(x["realized_r"] for x in fric)/N
    by=defaultdict(list)
    for s in fric: by[s["_sess"]].append(s)
    print(f"\n############ {cfg['id']}  (total n={N}, overall avg_R={overall:+.4f})")
    print("  -- 1. PER-SESSION --")
    print(f"    {'session':<11}{'n':>6}{'%':>6}{'WR%':>7}{'avg_R':>8}{'sum_R':>9}   outcome[WIN/PT2/PT2_T1/PT1/LOSS]   BUY/SELL")
    for b in SORD:
        sg=by.get(b,[])
        if not sg: continue
        n,wr,avg,sm=stat([x["realized_r"] for x in sg])
        oc=Counter(x["outcome"] for x in sg)
        od="/".join(str(oc.get(k,0)) for k in ["WIN","PARTIAL_TP2","PARTIAL_TP2_T1","PARTIAL_TP1","LOSS"])
        flag=" <-- NY" if b=="NY" else ""
        print(f"    {b:<11}{n:>6}{100*n/N:>5.1f}%{wr*100:>6.1f}%{avg:>+8.4f}{sm:>+9.1f}   [{od}]   {split(sg)}{flag}")
    nyavg=stat([x['realized_r'] for x in by.get('NY',[])])[2]
    print(f"    >>> NY avg_R {nyavg:+.4f} vs overall {overall:+.4f} ({'ABOVE' if nyavg>overall else 'BELOW'} by {abs(nyavg-overall):.4f})")

    print("  -- 2. CONFOUNDS --")
    print("    session x REGIME (avg_R, n):")
    for b in SORD:
        d=defaultdict(list)
        for s in by.get(b,[]): d[REGIME.get(s["ts"][:10],"RANGE")].append(s["realized_r"])
        print(f"      {b:<11}"+"  ".join(f"{rg}:{(sum(v)/len(v)):+.3f}(n{len(v)})" for rg,v in sorted(d.items())))
    print("    session x VOLUME (mean vol_ratio, %HIGH-vol>1.5) -- is a 'session edge' just the inverted-volume effect?")
    for b in SORD:
        sg=[s for s in by.get(b,[]) if s["_vr"] is not None]
        if not sg: continue
        mvr=sum(s["_vr"] for s in sg)/len(sg); hi=sum(1 for s in sg if s["_vr"]>1.5)/len(sg)
        print(f"      {b:<11}mean_vol_ratio={mvr:.2f}  %HIGH-vol={hi*100:.1f}%")

    print("  -- 3. STABILITY OOS 70/30 (train -> test) --")
    for b in SORD:
        sg=sorted(by.get(b,[]),key=lambda s:s["ts"]); cut=int(len(sg)*0.7)
        if cut<5: print(f"      {b:<11}n<10"); continue
        tr=[x["realized_r"] for x in sg[:cut]]; te=[x["realized_r"] for x in sg[cut:]]
        print(f"      {b:<11}train n{len(tr)} avg{(sum(tr)/len(tr)):+.4f} -> test n{len(te)} avg{(sum(te)/len(te)):+.4f}")
print("\nDone.")
