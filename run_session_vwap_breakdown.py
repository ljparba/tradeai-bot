"""run_session_vwap_breakdown.py — DESCRIPTIVE per-session + per-VWAP analysis (in-memory).

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B. Buckets EXISTING signals by
UTC session and by entry-vs-VWAP. NO signal blocked, NO filter, NO DB writes.

VWAP (causal, anchor stated): SESSION-ANCHORED at 00:00 UTC daily reset. At each 5m bar:
  typical = (H+L+C)/3 ; running VWAP = sum(typical*vol)/sum(vol) from the 00:00 anchor up to
  AND INCLUDING the entry bar (no forward bars). VWAP is anchor-sensitive — a different anchor
  (e.g. London open, weekly) could move results; flagged.
SESSION (UTC, from entry ts): ASIAN 00-08 / LONDON 08-13 / LONDON_NY_OVERLAP 13-16 /
  NY 16-21 / LATE_US 21-24.
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

# Per-token: VWAP-by-time (daily 00:00 reset) + vol-by-time (for confound) -----------
MODEL={}
def get_model(tok):
    if tok in MODEL: return MODEL[tok]
    pc=load_cached(tok,"5m")
    vp=VOL_DIR/f"{tok}USDT_vol.json"
    if pc is None or not vp.exists(): MODEL[tok]=None; return None
    vd=json.load(open(vp)); voltimes=vd["times"]; vols=vd["vols"]
    volmap=dict(zip(voltimes,vols))
    vwap_by_t={}; vol_by_t=volmap
    num=den=0.0; cur_day=None
    for t,h,l,c in zip(pc["times"],pc["highs"],pc["lows"],pc["closes"]):
        v=volmap.get(t)
        if v is None: continue
        day=datetime.fromtimestamp(t/1000,timezone.utc).strftime("%Y-%m-%d")
        if day!=cur_day: num=den=0.0; cur_day=day
        typ=(h+l+c)/3.0; num+=typ*v; den+=v
        if den>0: vwap_by_t[t]=num/den
    # vol ratio series: need sorted vol times for prior-N
    vt_sorted=sorted(voltimes)
    MODEL[tok]=(vwap_by_t, vol_by_t, vt_sorted)
    return MODEL[tok]

def vwap_at(tok,entry_ms):
    m=get_model(tok)
    return None if m is None else m[0].get(entry_ms)
def volratio(tok,entry_ms):
    m=get_model(tok)
    if m is None: return None
    _,vol_by_t,vt=m
    mss=entry_ms-300000; i=bisect.bisect_left(vt,mss)
    if i>=len(vt) or vt[i]!=mss or i<N_LB: return None
    prior=[vol_by_t[vt[j]] for j in range(i-N_LB,i)]
    avg=sum(prior)/len(prior)
    return None if avg<=0 else vol_by_t[mss]/avg

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
    h=int(ts[11:13])
    return "ASIAN" if h<8 else "LONDON" if h<13 else "LDN_NY_OVL" if h<16 else "NY" if h<21 else "LATE_US"
def stat(rs):
    n=len(rs); pos=sum(1 for r in rs if r>0)
    return n,(pos/n if n else 0),(sum(rs)/n if n else 0),sum(rs)
def split(sg):
    d={dd:[x["realized_r"] for x in sg if x["signal"]==dd] for dd in ("BUY","SELL")}
    return " ".join(f"{dd}:n{len(d[dd])} avg{(sum(d[dd])/len(d[dd])):+.3f}" if d[dd] else f"{dd}:n0" for dd in ("BUY","SELL"))

SORD=["ASIAN","LONDON","LDN_NY_OVL","NY","LATE_US"]
print("="*104)
print("SESSION + VWAP BREAKDOWN — 720d, Config 14, post-TP2 model, friction (in-memory, CAUSAL)")
print("VWAP = daily-00:00-anchored, typical(H+L+C)/3 * vol, up to & incl entry bar")
print("="*104)
for cfg in CFGS:
    clean=[]; cache={}
    for tok in G.TOKENS:
        clean+=G.run_one_token(tok,cfg,detect,compute_sl_tp,compute_econ,TOKEN_RT_COST,ROUND_TRIP_COST_PCT)
        cache[tok]=G.load_cached(tok,cfg["entry_tf"])
    fric=G.apply_friction(clean,cfg,cache,derive_seed,simulate_execution)
    for s in fric:
        ets=int(datetime.strptime(s["ts"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()*1000)
        s["_sess"]=sess(s["ts"])
        vw=vwap_at(s["token"],ets)
        if vw is None: s["_vwap"]="UNKNOWN"; s["_vwalign"]="UNKNOWN"
        else:
            above=s["price"]>vw
            s["_vwap"]="ABOVE" if above else "BELOW"
            s["_vwalign"]="ALIGNED" if (s["signal"]=="BUY")==above else "AGAINST"
        s["_vr"]=volratio(s["token"],ets)
    N=len(fric); overall=sum(x["realized_r"] for x in fric)/N
    print(f"\n############ {cfg['id']}  (total n={N}, overall avg_R={overall:+.4f})")

    print("  -- 1. PER-SESSION (n, %, WR, avg_R, sum_R, BUY/SELL) --")
    by=defaultdict(list)
    for s in fric: by[s["_sess"]].append(s)
    for b in SORD:
        sg=by.get(b,[])
        if not sg: continue
        n,wr,avg,sm=stat([x["realized_r"] for x in sg])
        flag=" <-- NY" if b=="NY" else ""
        print(f"    {b:<11}n{n:<6}{100*n/N:>5.1f}%  WR{wr*100:>5.1f}%  avg{avg:+.4f}  sum{sm:+8.1f}   {split(sg)}{flag}")
    nyavg=stat([x['realized_r'] for x in by.get('NY',[])])[2]
    print(f"    >>> NY avg_R {nyavg:+.4f} vs overall {overall:+.4f}  ({'ABOVE' if nyavg>overall else 'BELOW'} mean by {abs(nyavg-overall):.4f})")

    print("  -- 2. PER-VWAP (ABOVE/BELOW + ALIGNED/AGAINST) --")
    for keyf,labs in [("_vwap",["ABOVE","BELOW","UNKNOWN"]),("_vwalign",["ALIGNED","AGAINST","UNKNOWN"])]:
        bb=defaultdict(list)
        for s in fric: bb[s[keyf]].append(s)
        for b in labs:
            sg=bb.get(b,[])
            if not sg: continue
            n,wr,avg,sm=stat([x["realized_r"] for x in sg])
            print(f"    {b:<9}n{n:<6}{100*n/N:>5.1f}%  WR{wr*100:>5.1f}%  avg{avg:+.4f}  sum{sm:+8.1f}   {split(sg)}")

    print("  -- 3. SESSION x VWAP (NY+ALIGNED vs others) --")
    for b in ["NY","ALL"]:
        for va in ["ALIGNED","AGAINST"]:
            sg=[s for s in fric if s["_vwalign"]==va and (b=="ALL" or s["_sess"]==b)]
            if not sg: continue
            n,wr,avg,sm=stat([x["realized_r"] for x in sg])
            print(f"    {b:<4} x {va:<8} n{n:<6} WR{wr*100:>5.1f}% avg{avg:+.4f} sum{sm:+8.1f}")

    print("  -- 4. CONFOUNDS --")
    print("    session x REGIME (avg_R,n):")
    for b in SORD:
        d=defaultdict(list)
        for s in by.get(b,[]): d[REGIME.get(s["ts"][:10],"RANGE")].append(s["realized_r"])
        print(f"      {b:<11}"+"  ".join(f"{rg}:{(sum(v)/len(v)):+.3f}(n{len(v)})" for rg,v in sorted(d.items())))
    print("    VWAP x VOLUME bucket (mean vol_ratio, share HIGH-vol):")
    for b in ["ABOVE","BELOW"]:
        sg=[s for s in fric if s["_vwap"]==b and s["_vr"] is not None]
        if not sg: continue
        mvr=sum(s["_vr"] for s in sg)/len(sg); hi=sum(1 for s in sg if s["_vr"]>1.5)/len(sg)
        print(f"      {b:<9} mean_vol_ratio={mvr:.2f}  %HIGH-vol={hi*100:.1f}%")

    print("  -- 5. STABILITY OOS 70/30 (train->test) --")
    print("    NY session:")
    sg=sorted(by.get("NY",[]),key=lambda s:s["ts"]); cut=int(len(sg)*0.7)
    if cut>5:
        tr=[x["realized_r"] for x in sg[:cut]]; te=[x["realized_r"] for x in sg[cut:]]
        print(f"      NY  train n{len(tr)} avg{(sum(tr)/len(tr)):+.4f} -> test n{len(te)} avg{(sum(te)/len(te)):+.4f}")
    for keyf,labs in [("_vwap",["ABOVE","BELOW"]),("_vwalign",["ALIGNED","AGAINST"])]:
        bb=defaultdict(list)
        for s in fric: bb[s[keyf]].append(s)
        for b in labs:
            sg=sorted(bb.get(b,[]),key=lambda s:s["ts"]); cut=int(len(sg)*0.7)
            if cut<5: continue
            tr=[x["realized_r"] for x in sg[:cut]]; te=[x["realized_r"] for x in sg[cut:]]
            print(f"      {b:<9} train n{len(tr)} avg{(sum(tr)/len(tr)):+.4f} -> test n{len(te)} avg{(sum(te)/len(te)):+.4f}")
print("\nDone.")
