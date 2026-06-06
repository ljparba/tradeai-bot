"""run_mean_reversion.py — DESCRIPTIVE mean-reversion property measurement (in-memory).

Read-only. Measures a STATISTICAL PROPERTY only — NO strategy, NO entry/exit rules.
720d, 12 tokens. (1) Lo-MacKinlay variance ratio + return autocorrelation on 5m & 1h
log returns. (2) Post-breakout reversion: of existing breakout signals, how often price
reverts to the broken level vs continues to TP3, within N bars; near-miss reversion rate.
(3) Regime-conditional. NO DB writes.

Variance Ratio VR(q) = Var(q-bar log return) / (q * Var(1-bar log return)).
  VR < 1  -> mean-reverting (negative return autocorrelation)
  VR ~ 1  -> random walk
  VR > 1  -> trending / momentum
"""
import os, sys, json, bisect, importlib, math, statistics
from collections import defaultdict
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
TOKENS=G.TOKENS

def load_cached(tok,tf):
    p=WIN["dir"]/f"{tok}USDT_{tf}_{WIN['suf']}.json"
    if not p.exists(): return None
    inner=(json.load(open(p)) or {}).get("data")
    if not inner: return None
    t=inner["times"]; i0=bisect.bisect_left(t,WIN["start"]); i1=bisect.bisect_right(t,WIN["end"])
    if i1-i0<30: return None
    return {k:inner[k][i0:i1] for k in ("opens","highs","lows","closes")}|{"times":t[i0:i1]}
G.load_cached=load_cached

def log_returns(closes):
    out=[]
    for i in range(1,len(closes)):
        if closes[i-1]>0 and closes[i]>0: out.append(math.log(closes[i]/closes[i-1]))
    return out

def variance_ratio(rets, q):
    # non-overlapping q-bar returns variance ratio
    n=len(rets)
    if n < q*4: return None
    var1=statistics.pvariance(rets)
    if var1<=0: return None
    qsum=[sum(rets[i:i+q]) for i in range(0, n-q+1, q)]
    if len(qsum)<2: return None
    varq=statistics.pvariance(qsum)
    return varq/(q*var1)

def autocorr(rets, lag):
    n=len(rets)
    if n<=lag+2: return None
    m=sum(rets)/n
    num=sum((rets[i]-m)*(rets[i-lag]-m) for i in range(lag,n))
    den=sum((r-m)**2 for r in rets)
    return num/den if den>0 else None

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

print("="*100)
print("MEAN-REVERSION EXPLORATION — 720d, 12 tokens (read-only, descriptive property only)")
print("="*100)

# ── (2) Variance ratio + autocorrelation per token ──
QS=[2,4,8,16]
print("\n### CORE STAT: Variance Ratio (VR<1 mean-revert, ~1 random walk, >1 trend) + return autocorr")
for tf in ("5m","1h"):
    print(f"\n  -- {tf} log returns --")
    print(f"    {'token':<7}" + "".join(f"VR{q:<6}" for q in QS) + f"{'ac1':>8}{'ac5':>8}{'ac10':>8}")
    agg={q:[] for q in QS}; aagg={1:[],5:[],10:[]}
    for tok in TOKENS:
        c=load_cached(tok,tf)
        if c is None: continue
        rets=log_returns(c["closes"])
        vrs=[variance_ratio(rets,q) for q in QS]
        acs=[autocorr(rets,l) for l in (1,5,10)]
        for q,v in zip(QS,vrs):
            if v is not None: agg[q].append(v)
        for l,a in zip((1,5,10),acs):
            if a is not None: aagg[l].append(a)
        print(f"    {tok:<7}" + "".join(f"{(v if v is not None else 0):<8.3f}" for v in vrs) +
              "".join(f"{(a if a is not None else 0):>8.4f}" for a in acs))
    print(f"    {'MEAN':<7}" + "".join(f"{statistics.mean(agg[q]):<8.3f}" if agg[q] else f"{'-':<8}" for q in QS) +
          "".join(f"{statistics.mean(aagg[l]):>8.4f}" if aagg[l] else f"{'-':>8}" for l in (1,5,10)))

# ── (1)+(3) Post-breakout reversion using existing signals ──
print("\n### POST-BREAKOUT REVERSION (existing breakout signals)")
os.environ.update(G.LOCKED_KNOBS)
import breakout_engine as _be
importlib.reload(_be)
detect=_be.detect_h4_breakout; compute_sl_tp=_be.compute_breakout_sl_tp
CFGS=[c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h","B_5m_1h")]
NS=[12,30,60]

for cfg in CFGS:
    sigs=[]
    px={}
    for tok in TOKENS:
        sigs += G.run_one_token(tok,cfg,detect,compute_sl_tp,compute_econ,TOKEN_RT_COST,ROUND_TRIP_COST_PCT)
        px[tok]=load_cached(tok,"5m")
    # build per-token time index
    tidx={tok:px[tok]["times"] for tok in px if px[tok]}
    counters={N:{"revert":0,"tp3":0,"nearmiss_rev":0,"total":0} for N in NS}
    reg_rev={N:defaultdict(lambda:[0,0]) for N in NS}  # regime -> [revert, total]
    for s in sigs:
        tok=s["token"]; c=px.get(tok)
        if c is None: continue
        ets=int(datetime.strptime(s["ts"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()*1000)
        ti=tidx[tok]; i=bisect.bisect_left(ti,ets)
        if i>=len(ti) or ti[i]!=ets: continue
        entry=s["price"]; d=s["signal"]; tp1p=s["tp1_pct"]; slp=s["sl_pct"]
        if d=="BUY":
            sl=entry*(1+slp/100); tp1=entry*(1+tp1p/100); tp3=entry*(1+tp1p*2/100)
            half=entry+0.5*(tp1-entry)
        else:
            sl=entry*(1-slp/100); tp1=entry*(1-tp1p/100); tp3=entry*(1-tp1p*2/100)
            half=entry-0.5*(entry-tp1)
        reg=REGIME.get(s["ts"][:10],"RANGE")
        hh=c["highs"]; ll=c["lows"]
        for N in NS:
            reverted=False; hit_tp3=False; reached_half=False; nm=False
            for j in range(i+1, min(i+1+N, len(hh))):
                h=hh[j]; l=ll[j]
                if d=="BUY":
                    if not reached_half and h>=half: reached_half=True
                    if h>=tp3: hit_tp3=True
                    if l<=sl:
                        reverted=True
                        if reached_half: nm=True
                        break
                    if l<=sl: pass
                else:
                    if not reached_half and l<=half: reached_half=True
                    if l<=tp3: hit_tp3=True
                    if h>=sl:
                        reverted=True
                        if reached_half: nm=True
                        break
            cc=counters[N]; cc["total"]+=1
            if reverted: cc["revert"]+=1
            if hit_tp3: cc["tp3"]+=1
            if nm: cc["nearmiss_rev"]+=1
            reg_rev[N][reg][1]+=1
            if reverted: reg_rev[N][reg][0]+=1
    print(f"\n  ## {cfg['id']}  (n_signals={counters[NS[0]]['total']})")
    print(f"    {'within':<8}{'%revert-to-broken-level':>26}{'%reached-TP3':>15}{'%near-miss-revert':>20}")
    for N in NS:
        cc=counters[N]; t=cc["total"] or 1
        print(f"    {N:>3} bars {100*cc['revert']/t:>24.1f}%{100*cc['tp3']/t:>14.1f}%{100*cc['nearmiss_rev']/t:>19.1f}%")
    print("    revert-rate by REGIME (within 30 bars):")
    for reg,v in sorted(reg_rev[30].items()):
        print(f"      {reg:<8} {100*v[0]/(v[1] or 1):.1f}%  (n{v[1]})")
print("\nDone.")
