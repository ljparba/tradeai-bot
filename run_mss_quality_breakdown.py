"""run_mss_quality_breakdown.py — DESCRIPTIVE per-MSS-quality analysis (in-memory).

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B. Breaks the backtest
signals down by MSS quality tier (HIGH/MEDIUM/LOW): n, %, WR, avg_R, sum_R, PF,
outcome dist; confounds (quality x direction / confluence / regime / token / SL%);
OOS 70/30 stability per tier. NO DB writes. Descriptive only.
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

# Config 14 (== LOCKED_KNOBS) + post-TP2 model (already in code)
os.environ.update(G.LOCKED_KNOBS)
import breakout_engine as _be
importlib.reload(_be)
detect = _be.detect_h4_breakout; compute_sl_tp = _be.compute_breakout_sl_tp
CFGS = [c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h", "B_5m_1h")]

# BTC daily regime (close vs 30d SMA, +/-3%)
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

def conf_of(s):
    et = s.get("entry_type", "")
    return "FVG" if "_FVG_" in et else "OB" if "_OB_" in et else "?"

def stats(rs):
    n = len(rs); pos = sum(1 for r in rs if r > 0)
    gp = sum(r for r in rs if r > 0); gl = sum(-r for r in rs if r < 0)
    return n, (pos/n if n else 0), (sum(rs)/n if n else 0), sum(rs), (gp/gl if gl > 0 else float("inf"))

print("="*100)
print("MSS-QUALITY BREAKDOWN — 720d, Config 14, post-TP2 trail model, friction (in-memory)")
print("="*100)
QORDER = ["HIGH", "MEDIUM", "LOW"]
for cfg in CFGS:
    clean = []; cache = {}
    for tok in G.TOKENS:
        clean += G.run_one_token(tok, cfg, detect, compute_sl_tp, compute_econ, TOKEN_RT_COST, ROUND_TRIP_COST_PCT)
        cache[tok] = G.load_cached(tok, cfg["entry_tf"])
    fric = G.apply_friction(clean, cfg, cache, derive_seed, simulate_execution)
    N = len(fric)
    byq = defaultdict(list)
    for s in fric: byq[s.get("mss_quality", "NONE")].append(s)
    print(f"\n############ {cfg['id']}  (total n={N})")
    print(f"{'tier':<8}{'n':>6}{'%tot':>7}{'WR%':>7}{'avg_R':>8}{'sum_R':>9}{'PF':>6}   outcome[WIN/PT2/PT2_T1/PT1/LOSS]")
    for q in QORDER:
        sg = byq.get(q, [])
        if not sg: print(f"{q:<8}{0:>6}"); continue
        rs = [s["realized_r"] for s in sg]; n, wr, avg, sm, pf = stats(rs)
        oc = Counter(s["outcome"] for s in sg)
        od = "/".join(str(oc.get(k,0)) for k in ["WIN","PARTIAL_TP2","PARTIAL_TP2_T1","PARTIAL_TP1","LOSS"])
        pfs = "inf" if pf == float("inf") else f"{pf:.2f}"
        print(f"{q:<8}{n:>6}{100*n/N:>6.1f}%{wr*100:>6.1f}%{avg:>+8.4f}{sm:>+9.1f}{pfs:>6}   [{od}]")

    # ── Confounds ──
    print("  -- confound: quality x DIRECTION (n, avg_R) --")
    for q in QORDER:
        sg = byq.get(q, [])
        d = {dd: [s["realized_r"] for s in sg if s["signal"] == dd] for dd in ("BUY","SELL")}
        parts = " ".join(f"{dd}:n{len(d[dd])} avg{(sum(d[dd])/len(d[dd])):+.3f}" if d[dd] else f"{dd}:n0" for dd in ("BUY","SELL"))
        print(f"    {q:<7} {parts}")
    print("  -- confound: quality x CONFLUENCE (FVG/OB) [NOTE: FVG/OB label drift — do not over-read] --")
    for q in QORDER:
        sg = byq.get(q, [])
        d = {cc: [s["realized_r"] for s in sg if conf_of(s) == cc] for cc in ("FVG","OB")}
        parts = " ".join(f"{cc}:n{len(d[cc])} avg{(sum(d[cc])/len(d[cc])):+.3f}" if d[cc] else f"{cc}:n0" for cc in ("FVG","OB"))
        print(f"    {q:<7} {parts}")
    print("  -- confound: quality x REGIME (avg_R, n) --")
    for q in QORDER:
        sg = byq.get(q, [])
        d = defaultdict(list)
        for s in sg: d[REGIME.get(s["ts"][:10], "RANGE")].append(s["realized_r"])
        parts = "  ".join(f"{rg}:{(sum(v)/len(v)):+.3f}(n{len(v)})" for rg, v in sorted(d.items()))
        print(f"    {q:<7} {parts}")
    print("  -- confound: quality x SL% (mean |sl_pct|) + top tokens --")
    for q in QORDER:
        sg = byq.get(q, [])
        if not sg: continue
        msl = statistics.mean(abs(s["sl_pct"]) for s in sg)
        tk = Counter(s["token"] for s in sg).most_common(4)
        print(f"    {q:<7} mean|SL|={msl:.3f}%  topTokens={tk}")

    # ── Stability: OOS 70/30 per tier ──
    print("  -- STABILITY: OOS 70/30 per tier (train avg_R -> test avg_R) --")
    for q in QORDER:
        sg = sorted(byq.get(q, []), key=lambda s: s["ts"])
        if len(sg) < 10: print(f"    {q:<7} n<10, skip"); continue
        cut = int(len(sg)*0.7)
        tr = [s["realized_r"] for s in sg[:cut]]; te = [s["realized_r"] for s in sg[cut:]]
        print(f"    {q:<7} train n{len(tr)} avg{(sum(tr)/len(tr)):+.4f}  ->  test n{len(te)} avg{(sum(te)/len(te)):+.4f}")
print("\nDone.")
