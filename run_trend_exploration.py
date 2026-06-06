"""run_trend_exploration.py — DESCRIPTIVE trend-property measurement (read-only).

Extends the variance-ratio method (MEAN_REVERSION_EXPLORATION, 5m/1h) to 4H / 12H / DAILY.
NO strategy, NO rules. Measures: (1) VR(q) + autocorr at 4h/12h/daily; (2) Kaufman efficiency
ratio + daily return autocorr lags 1-10; (3) trend-direction NULL test (daily MA-state forward
return, pre-friction); (4) per-token + time-window variation. NO DB writes.

VR(q) = Var(q-bar log return)/(q*Var(1-bar)): >1 trend, ~1 random walk, <1 mean-revert.
Higher-TF bars built from the 4H cache by UTC calendar grouping (daily = last 4h close of the
day; 12H = last 4h close of each half-day).
"""
import sys, json, bisect, math, statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_BD = Path(__file__).resolve().parent
WINs, WINe = (int(datetime(2024,6,10,tzinfo=timezone.utc).timestamp()*1000),
              int(datetime(2026,5,31,tzinfo=timezone.utc).timestamp()*1000))
CDIR = _BD/"data"/"ohlcv_cache_720d"
TOKENS = ["BTC","ETH","XRP","HBAR","AVAX","LINK","BNB","ADA","POL","TON","ATOM","BCH"]

def load4h(tok):
    p = CDIR/f"{tok}USDT_4h_720d.json"
    if not p.exists(): return None
    inner = (json.load(open(p)) or {}).get("data")
    t = inner["times"]; i0=bisect.bisect_left(t,WINs); i1=bisect.bisect_right(t,WINe)
    return {"times":t[i0:i1],"closes":inner["closes"][i0:i1]}

def resample(times, closes, mode):
    # mode "4h" -> as-is; "12h" -> last close per half-day; "1d" -> last close per UTC day
    if mode == "4h":
        return closes[:]
    buckets = {}
    for t, c in zip(times, closes):
        dt = datetime.fromtimestamp(t/1000, timezone.utc)
        key = dt.strftime("%Y-%m-%d") + ("_PM" if (mode=="12h" and dt.hour>=12) else "_AM" if mode=="12h" else "")
        buckets[key] = c  # last close in the bucket wins (times are sorted)
    return [buckets[k] for k in sorted(buckets)]

def logret(closes):
    return [math.log(closes[i]/closes[i-1]) for i in range(1,len(closes)) if closes[i-1]>0 and closes[i]>0]

def vr(rets, q):
    n=len(rets)
    if n < q*4: return None
    v1=statistics.pvariance(rets)
    if v1<=0: return None
    qs=[sum(rets[i:i+q]) for i in range(0,n-q+1,q)]
    if len(qs)<2: return None
    return statistics.pvariance(qs)/(q*v1)

def autocorr(rets, lag):
    n=len(rets)
    if n<=lag+2: return None
    m=sum(rets)/n
    num=sum((rets[i]-m)*(rets[i-lag]-m) for i in range(lag,n))
    den=sum((r-m)**2 for r in rets)
    return num/den if den>0 else None

def efficiency_ratio(closes, N):
    # Kaufman ER over rolling N; return mean ER
    ers=[]
    for i in range(N, len(closes)):
        net=abs(closes[i]-closes[i-N])
        path=sum(abs(closes[j]-closes[j-1]) for j in range(i-N+1,i+1))
        if path>0: ers.append(net/path)
    return statistics.mean(ers) if ers else None

print("="*100)
print("TREND EXPLORATION — 720d, 12 tokens, 4H/12H/DAILY (read-only, descriptive property only)")
print("VR>1 trend, ~1 random walk, <1 mean-revert")
print("="*100)

# ── (1) Variance ratio across timeframes ──
DATA={}
for tok in TOKENS:
    c=load4h(tok)
    if c: DATA[tok]={m:resample(c["times"],c["closes"],m) for m in ("4h","12h","1d")}
for mode,QS,label in [("4h",[2,4,8,16],"4H"),("12h",[2,4,8,16],"12H"),("1d",[2,4,8],"DAILY")]:
    print(f"\n### VARIANCE RATIO — {label} bars")
    print(f"  {'token':<7}{'nbars':>6}"+"".join(f"VR{q:<6}" for q in QS)+f"{'ac1':>9}{'ac3':>9}")
    agg={q:[] for q in QS}; a1=[]; a3=[]
    for tok in TOKENS:
        if tok not in DATA: continue
        closes=DATA[tok][mode]; rets=logret(closes)
        vrs=[vr(rets,q) for q in QS]; ac1=autocorr(rets,1); ac3=autocorr(rets,3)
        for q,v in zip(QS,vrs):
            if v is not None: agg[q].append(v)
        if ac1 is not None: a1.append(ac1)
        if ac3 is not None: a3.append(ac3)
        print(f"  {tok:<7}{len(closes):>6}"+"".join(f"{(v if v else 0):<8.3f}" for v in vrs)+
              f"{(ac1 if ac1 else 0):>9.4f}{(ac3 if ac3 else 0):>9.4f}")
    print(f"  {'MEAN':<7}{'':>6}"+"".join(f"{statistics.mean(agg[q]):<8.3f}" if agg[q] else f"{'-':<8}" for q in QS)+
          f"{statistics.mean(a1):>9.4f}{statistics.mean(a3):>9.4f}")

# ── (2) Efficiency ratio + daily autocorr lags 1-10 ──
print("\n### DAILY trend-strength: Kaufman efficiency ratio (N=20) + return autocorr lags 1-10")
print(f"  {'token':<7}{'ER20':>7}   daily-return autocorr lag1..lag10")
ers=[]; acmat=defaultdict(list)
for tok in TOKENS:
    if tok not in DATA: continue
    closes=DATA[tok]["1d"]; rets=logret(closes)
    er=efficiency_ratio(closes,20);
    if er is not None: ers.append(er)
    acs=[autocorr(rets,l) for l in range(1,11)]
    for l,a in zip(range(1,11),acs):
        if a is not None: acmat[l].append(a)
    print(f"  {tok:<7}{(er if er else 0):>7.3f}   "+" ".join(f"{(a if a else 0):+.3f}" for a in acs))
print(f"  {'MEAN':<7}{statistics.mean(ers):>7.3f}   "+" ".join(f"{statistics.mean(acmat[l]):+.3f}" if acmat[l] else "  -  " for l in range(1,11)))
print("  (ER ~0.0-0.3 chop, ~0.3-0.5 mixed, >0.5 clean trend; daily autocorr >0 persistent=trend)")

# ── (3) Trend-direction NULL test (daily MA state -> forward return; PRE-friction) ──
print("\n### TREND-DIRECTION NULL TEST (daily, pre-friction, NOT a strategy)")
print("  state = long if close>MA else short; forward = next-day log return.")
print("  signal = mean(state * forward_return): >0 trend-direction carries info, ~0 coin-flip, <0 mean-revert")
for MAN in (20,50):
    print(f"  -- {MAN}-day MA --")
    print(f"    {'token':<7}{'hit%':>7}{'avgFwd|long':>13}{'avgFwd|short':>14}{'signal(state*fwd)':>19}")
    sigs=[]; hits=[]
    for tok in TOKENS:
        if tok not in DATA: continue
        C=DATA[tok]["1d"]
        if len(C)<MAN+5: continue
        states=[]; fwds=[]
        for i in range(MAN, len(C)-1):
            ma=sum(C[i-MAN+1:i+1])/MAN
            st=1 if C[i]>ma else -1
            fr=math.log(C[i+1]/C[i]) if C[i]>0 and C[i+1]>0 else 0.0
            states.append(st); fwds.append(fr)
        if not states: continue
        longf=[fwds[i] for i in range(len(states)) if states[i]>0]
        shortf=[fwds[i] for i in range(len(states)) if states[i]<0]
        hit=sum(1 for i in range(len(states)) if (states[i]>0 and fwds[i]>0) or (states[i]<0 and fwds[i]<0))/len(states)
        sig=sum(states[i]*fwds[i] for i in range(len(states)))/len(states)
        hits.append(hit); sigs.append(sig)
        al=statistics.mean(longf) if longf else 0; ash=statistics.mean(shortf) if shortf else 0
        print(f"    {tok:<7}{hit*100:>6.1f}%{al:>+13.5f}{ash:>+14.5f}{sig:>+19.6f}")
    print(f"    {'MEAN':<7}{statistics.mean(hits)*100:>6.1f}%{'':>13}{'':>14}{statistics.mean(sigs):>+19.6f}")

# ── (4) Time-window variation: ER first-half vs second-half ──
print("\n### TIME VARIATION — daily ER(20) first-half vs second-half of 720d")
print(f"  {'token':<7}{'ER_1stHalf':>11}{'ER_2ndHalf':>11}")
for tok in TOKENS:
    if tok not in DATA: continue
    C=DATA[tok]["1d"]; h=len(C)//2
    e1=efficiency_ratio(C[:h],20); e2=efficiency_ratio(C[h:],20)
    print(f"  {tok:<7}{(e1 if e1 else 0):>11.3f}{(e2 if e2 else 0):>11.3f}")
print("\nDone.")
