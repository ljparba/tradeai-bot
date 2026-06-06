"""run_tpgeo_experiment.py — PRE-REGISTERED TP-geometry experiment (in-memory).

5 pre-registered TP-RR variants x {TF_A, TF_B} on the 720d window, friction-on,
under the POST-TP2 trail-to-TP1 exit model. NO DB writes (strictly safer than row
tags). For each: n, WR, avg_R, sum_R, PF, maxDD, outcome dist, OOS 70/30,
per-regime avg_R, whole-sample Sharpe, CPCV wr_mean, DSR deflated for 5 trials with
the REAL cross-variant trial std. Decision rule applied at the end.
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
from validation import (cpcv_summary, sharpe_ratio, deflated_sharpe_ratio, _moments)

def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)

WIN = {"start": ms(2024, 6, 10), "end": ms(2026, 5, 31),
       "dir": _BD / "data" / "ohlcv_cache_720d", "suf": "720d"}
G.START_MS = WIN["start"]; G.END_MS = WIN["end"]

def load_cached(tok, tf):
    p = WIN["dir"] / f"{tok}USDT_{tf}_{WIN['suf']}.json"
    if not p.exists():
        return None
    inner = (json.load(open(p)) or {}).get("data")
    if not inner:
        return None
    t = inner["times"]; i0 = bisect.bisect_left(t, WIN["start"]); i1 = bisect.bisect_right(t, WIN["end"])
    if i1 - i0 < 30:
        return None
    return {k: inner[k][i0:i1] for k in ("opens", "highs", "lows", "closes")} | {"times": t[i0:i1]}
G.load_cached = load_cached

CFGS = [c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h", "B_5m_1h")]
VARIANTS = [
    ("V0", 2.0, 3.0, 4.0, "BASELINE (Config 14)"),
    ("V1", 2.0, 3.0, 3.5, "TP3 closer"),
    ("V2", 2.5, 4.0, 6.0, "wider spacing"),
    ("V3", 1.5, 2.5, 3.5, "tighter all tiers"),
    ("V4", 2.0, 4.0, 6.0, "TP1 same, TP2/TP3 stretched"),
]

# ── BTC daily regime map (from 4h cache): close vs 30d SMA, +/-3% band ──
def build_regime_map():
    c = load_cached("BTC", "4h")
    by_day = {}
    for t, cl in zip(c["times"], c["closes"]):
        d = datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")
        by_day[d] = cl  # last 4h close of the day wins
    days = sorted(by_day)
    closes = [by_day[d] for d in days]
    regime = {}
    for i, d in enumerate(days):
        if i < 30:
            regime[d] = "RANGE"; continue
        sma = sum(closes[i-30:i]) / 30
        c0 = closes[i]
        regime[d] = "BULL" if c0 > sma * 1.03 else "BEAR" if c0 < sma * 0.97 else "RANGE"
    return regime
REGIME = build_regime_map()

def maxdd(rs):
    cum = peak = mdd = 0.0
    for r in rs:
        cum += r; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    return mdd

def metrics(sigs):
    rs = [s["realized_r"] for s in sigs]
    n = len(rs)
    pos = sum(1 for r in rs if r > 0)
    gp = sum(r for r in rs if r > 0); gl = sum(-r for r in rs if r < 0)
    oc = Counter(s["outcome"] for s in sigs)
    # OOS 70/30 chronological
    ss = sorted(sigs, key=lambda s: s["ts"])
    cut = int(len(ss) * 0.7)
    tr = [s["realized_r"] for s in ss[:cut]]; te = [s["realized_r"] for s in ss[cut:]]
    # per-regime
    reg = defaultdict(list)
    for s in sigs:
        reg[REGIME.get(s["ts"][:10], "RANGE")].append(s["realized_r"])
    sk, ku = _moments(rs)[2], _moments(rs)[3]
    return {
        "n": n, "wr": pos / n if n else 0, "avg_R": sum(rs)/n if n else 0,
        "sum_R": sum(rs), "pf": (gp/gl) if gl > 0 else float("inf"),
        "maxdd": maxdd([s["realized_r"] for s in ss]),
        "oc": oc, "rs": rs, "skew": sk, "kurt": ku,
        "train": sum(tr)/len(tr) if tr else 0, "test": sum(te)/len(te) if te else 0,
        "regime": {k: (sum(v)/len(v), len(v)) for k, v in reg.items()},
    }

RESULTS = {}  # (variant, cfg) -> metrics
for vid, r1, r2, r3, desc in VARIANTS:
    os.environ.update(G.LOCKED_KNOBS)
    os.environ["BREAKOUT_TP1_RR"] = str(r1)
    os.environ["BREAKOUT_TP2_RR"] = str(r2)
    os.environ["BREAKOUT_TP3_RR"] = str(r3)
    import breakout_engine as _be
    importlib.reload(_be)
    detect = _be.detect_h4_breakout; compute_sl_tp = _be.compute_breakout_sl_tp
    for cfg in CFGS:
        clean = []; cache = {}
        for tok in G.TOKENS:
            clean += G.run_one_token(tok, cfg, detect, compute_sl_tp, compute_econ, TOKEN_RT_COST, ROUND_TRIP_COST_PCT)
            cache[tok] = G.load_cached(tok, cfg["entry_tf"])
        fric = G.apply_friction(clean, cfg, cache, derive_seed, simulate_execution)
        m = metrics(fric)
        # CPCV on realized_r
        try:
            cp = cpcv_summary(fric, pnl_func=lambda s: s["realized_r"],
                              is_win_func=lambda s: s["realized_r"] > 0)
            m["cpcv_wr"] = cp.get("wr_mean")
        except Exception as e:
            m["cpcv_wr"] = None; m["cpcv_err"] = str(e)
        m["sharpe"] = sharpe_ratio(m["rs"], 1.0)
        RESULTS[(vid, cfg["id"])] = m
        print(f"[done] {vid} {cfg['id']}: n={m['n']} avg_R={m['avg_R']:+.4f} test={m['test']:+.4f}")

# DSR deflated for 5 trials, using REAL cross-variant Sharpe std (per TF)
for cfgid in ("A_5m_4h", "B_5m_1h"):
    sharpes = [RESULTS[(v[0], cfgid)]["sharpe"] for v in VARIANTS]
    sr_std = statistics.pstdev(sharpes) if len(sharpes) > 1 else 0.0
    for v in VARIANTS:
        m = RESULTS[(v[0], cfgid)]
        m["sr_trial_std"] = sr_std
        m["dsr5"] = (deflated_sharpe_ratio(m["sharpe"], m["n"], 5, sr_std,
                                           skew=m["skew"], kurtosis=m["kurt"])
                     if sr_std > 0 else 1.0)

# Persist a slim summary so an expensive run is never lost to a report-time bug.
slim = {}
for (vid, cfgid), m in RESULTS.items():
    slim[f"{vid}|{cfgid}"] = {k: (v if not isinstance(v, Counter) else dict(v))
                              for k, v in m.items() if k != "rs"}
json.dump(slim, open(_BD / "data" / "tpgeo_results.json", "w"), indent=2, default=str)
print("[saved] data/tpgeo_results.json")

# ── Report ──
print("\n" + "=" * 110)
print("TP-GEOMETRY EXPERIMENT — 720d friction, post-TP2 trail model (in-memory, no DB writes)")
print("=" * 110)
for cfgid in ("A_5m_4h", "B_5m_1h"):
    print(f"\n### {cfgid}")
    hdr = f"{'var':<4}{'RR(1/2/3)':<14}{'n':>6}{'WR%':>7}{'avg_R':>8}{'sumR':>9}{'PF':>6}{'maxDD':>7}{'train':>8}{'test':>8}{'CPCVwr':>8}{'DSR5':>7}"
    print(hdr)
    for vid, r1, r2, r3, desc in VARIANTS:
        m = RESULTS[(vid, cfgid)]
        pf = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
        cw = f"{m['cpcv_wr']:.1f}" if m.get("cpcv_wr") is not None else "—"
        print(f"{vid:<4}{f'{r1}/{r2}/{r3}':<14}{m['n']:>6}{m['wr']*100:>6.1f}%{m['avg_R']:>+8.4f}{m['sum_R']:>+9.1f}{pf:>6}{m['maxdd']:>7.1f}{m['train']:>+8.4f}{m['test']:>+8.4f}{cw:>8}{m['dsr5']:>7.3f}")
    print("  outcome dist (WIN/PT2/PT2_T1/PT1/LOSS) + per-regime avg_R:")
    for vid, *_ in [(v[0],) for v in VARIANTS]:
        m = RESULTS[(vid, cfgid)]
        oc = m["oc"]
        od = "/".join(str(oc.get(k, 0)) for k in ["WIN", "PARTIAL_TP2", "PARTIAL_TP2_T1", "PARTIAL_TP1", "LOSS"])
        rg = "  ".join(f"{k}:{v[0]:+.3f}(n{v[1]})" for k, v in sorted(m["regime"].items()))
        print(f"    {vid}: [{od}]  regime[{rg}]")
print("\nDone.")
