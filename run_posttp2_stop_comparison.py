"""run_posttp2_stop_comparison.py — V_TP1 (trail) vs V_ENTRY (hold-at-entry) post-TP2 stop.
720d, Config 14, friction, TF_A+TF_B. In-memory, NO DB writes. Identical signal set per mode
(post_tp2_mode does not affect detection/economics) → per-signal comparison."""
import os, sys, json, bisect, importlib, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
_BD=Path(__file__).resolve().parent; sys.path.insert(0,str(_BD)); sys.path.insert(0,"/home/tradeai/TradeAI")
import run_tf_grid as G
from crt_engine import compute_crt_trade_economics as compute_econ
from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT
from execution import simulate_execution, derive_seed
from validation import sharpe_ratio, deflated_sharpe_ratio, _moments
def ms(y,m,d): return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)
WIN={"start":ms(2024,6,10),"end":ms(2026,5,31),"dir":_BD/"data"/"ohlcv_cache_720d","suf":"720d"}
G.START_MS=WIN["start"]; G.END_MS=WIN["end"]
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
ORIG_CHECK=G.check_outcome
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
def maxdd(rs):
    cum=peak=mdd=0.0
    for r in rs:
        cum+=r; peak=max(peak,cum); mdd=max(mdd,peak-cum)
    return mdd
def metrics(sigs):
    rs=[s["realized_r"] for s in sigs]; n=len(rs); pos=sum(1 for r in rs if r>0)
    gp=sum(r for r in rs if r>0); gl=sum(-r for r in rs if r<0)
    ss=sorted(sigs,key=lambda s:s["ts"]); cut=int(len(ss)*0.7)
    tr=[s["realized_r"] for s in ss[:cut]]; te=[s["realized_r"] for s in ss[cut:]]
    sk,ku=_moments(rs)[2],_moments(rs)[3]
    reg=defaultdict(list)
    for s in sigs: reg[REGIME.get(s["ts"][:10],"RANGE")].append(s["realized_r"])
    return {"n":n,"wr":pos/n,"avg":sum(rs)/n,"sum":sum(rs),"pf":(gp/gl) if gl>0 else float("inf"),
            "mdd":maxdd([s["realized_r"] for s in ss]),"oc":Counter(s["outcome"] for s in sigs),
            "train":sum(tr)/len(tr) if tr else 0,"test":sum(te)/len(te) if te else 0,
            "sharpe":sharpe_ratio(rs,1.0),"skew":sk,"kurt":ku,
            "regime":{k:(sum(v)/len(v),len(v)) for k,v in reg.items()},"rs":rs}

RESULTS={}; PERSIG={}
for cfg in CFGS:
    for mode in ("trail_tp1","hold_entry"):
        G.check_outcome=lambda d,e,sl,t1,t2,t3,fut,_m=mode: ORIG_CHECK(d,e,sl,t1,t2,t3,fut,post_tp2_mode=_m)
        clean=[]; cache={}
        for tok in G.TOKENS:
            clean+=G.run_one_token(tok,cfg,detect,compute_sl_tp,compute_econ,TOKEN_RT_COST,ROUND_TRIP_COST_PCT)
            cache[tok]=G.load_cached(tok,cfg["entry_tf"])
        fric=G.apply_friction(clean,cfg,cache,derive_seed,simulate_execution)
        RESULTS[(cfg["id"],mode)]=metrics(fric)
        PERSIG[(cfg["id"],mode)]={(s["token"],s["ts"]):s for s in fric}
        print(f"[done] {cfg['id']} {mode}: n={len(fric)} avg_R={RESULTS[(cfg['id'],mode)]['avg']:+.4f}")
G.check_outcome=ORIG_CHECK

print("\n"+"="*100)
print("POST-TP2 STOP COMPARISON — V_TP1 (trail) vs V_ENTRY (hold-at-entry), 720d friction")
print("="*100)
for cfg in CFGS:
    cid=cfg["id"]
    vt=RESULTS[(cid,"trail_tp1")]; ve=RESULTS[(cid,"hold_entry")]
    # DSR deflated for 2 variants
    sr_std=statistics.pstdev([vt["sharpe"],ve["sharpe"]])
    for v in (vt,ve):
        v["dsr2"]=deflated_sharpe_ratio(v["sharpe"],v["n"],2,sr_std,skew=v["skew"],kurtosis=v["kurt"]) if sr_std>0 else 1.0
    print(f"\n### {cid}  (n={vt['n']}, sr_trial_std={sr_std:.4f})")
    print(f"  {'variant':<10}{'avg_R':>9}{'WR%':>7}{'PF':>7}{'maxDD':>8}{'sum_R':>9}{'train':>8}{'test':>8}{'DSR2':>7}")
    for nm,v in (("V_TP1",vt),("V_ENTRY",ve)):
        print(f"  {nm:<10}{v['avg']:>+9.4f}{v['wr']*100:>6.1f}%{v['pf']:>7.2f}{v['mdd']:>8.1f}{v['sum']:>+9.1f}{v['train']:>+8.4f}{v['test']:>+8.4f}{v['dsr2']:>7.3f}")
    print(f"  delta V_ENTRY-V_TP1: avg_R {ve['avg']-vt['avg']:+.4f}  sum_R {ve['sum']-vt['sum']:+.1f}  test {ve['test']-vt['test']:+.4f}")
    # Reclassification (per-signal)
    pt=PERSIG[(cid,"trail_tp1")]; pe=PERSIG[(cid,"hold_entry")]
    changed=[(k,pt[k]["outcome"],pe[k]["outcome"],pe[k]["realized_r"]-pt[k]["realized_r"]) for k in pt if k in pe and pt[k]["outcome"]!=pe[k]["outcome"]]
    print(f"  reclassified: {len(changed)} signals; net R delta {sum(c[3] for c in changed):+.1f}")
    trans=Counter((c[1],c[2]) for c in changed)
    for (a,b),n in trans.most_common():
        rd=sum(c[3] for c in changed if c[1]==a and c[2]==b)
        print(f"     {a} -> {b}: {n}  (R delta {rd:+.1f})")
    print(f"  outcome mix V_TP1 : {dict(vt['oc'])}")
    print(f"  outcome mix V_ENTRY: {dict(ve['oc'])}")
    print("  per-regime avg_R (V_TP1 -> V_ENTRY):")
    for rg in sorted(vt["regime"]):
        a=vt["regime"][rg][0]; b=ve["regime"].get(rg,(0,0))[0]
        print(f"     {rg:<8} {a:+.3f} -> {b:+.3f}  (n{vt['regime'][rg][1]})")
print("\nDone.")
