"""run_posttp2_backtests.py — NEW post-TP2-trail model backtest sweep (in-memory).

Drives run_tf_grid's engine (which now contains the POST-TP2 TRAIL FIX) over the
SAME windows/caches that produced the stored reference runs, WITHOUT writing any
backtest rows to breakout.db. Reports new outcome distribution + avg_R for
TF_A / TF_B × clean/friction × 90d/365d/720d, and the PARTIAL_TP2 -> PARTIAL_TP2_T1
reclassification. Read/compare only.
"""
import os, sys, json, bisect, importlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_BD = Path(__file__).resolve().parent
sys.path.insert(0, str(_BD)); sys.path.insert(0, "/home/tradeai/TradeAI")

import run_tf_grid as G
for k, v in G.LOCKED_KNOBS.items():
    os.environ[k] = v
import breakout_engine as _be
importlib.reload(_be)
detect = _be.detect_h4_breakout
compute_sl_tp = _be.compute_breakout_sl_tp
from crt_engine import compute_crt_trade_economics as compute_econ
from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT
from execution import simulate_execution, derive_seed

def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)

WINDOWS = [
    {"name": "90d",  "start": ms(2026, 3, 2),  "end": ms(2026, 5, 31), "dir": Path("/home/tradeai/TradeAI/data/ohlcv_cache"), "suf": "365d"},
    {"name": "365d", "start": ms(2025, 5, 31), "end": ms(2026, 5, 31), "dir": Path("/home/tradeai/TradeAI/data/ohlcv_cache"), "suf": "365d"},
    {"name": "720d", "start": ms(2024, 6, 10), "end": ms(2026, 5, 31), "dir": _BD / "data" / "ohlcv_cache_720d", "suf": "720d"},
]
CFGS = [c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h", "B_5m_1h")]

def make_loader(win):
    def load_cached(tok, tf):
        path = win["dir"] / f"{tok}USDT_{tf}_{win['suf']}.json"
        if not path.exists():
            return None
        inner = (json.load(open(path)) or {}).get("data")
        if not inner:
            return None
        times = inner["times"]
        i0 = bisect.bisect_left(times, win["start"]); i1 = bisect.bisect_right(times, win["end"])
        if i1 - i0 < 30:
            return None
        return {kk: inner[kk][i0:i1] for kk in ("opens", "highs", "lows", "closes")} | {"times": times[i0:i1]}
    return load_cached

def agg(sigs):
    if not sigs:
        return (0, 0.0, Counter(), 0.0, 0.0)
    c = Counter(s["outcome"] for s in sigs)
    rs = [s["realized_r"] for s in sigs]
    avg = sum(rs) / len(rs)
    npos = sum(1 for r in rs if r > 0)
    gp = sum(r for r in rs if r > 0); gl = sum(-r for r in rs if r < 0)
    wr = npos / len(rs)
    pf = (gp / gl) if gl > 0 else float("inf")
    return (len(sigs), round(avg, 4), c, round(wr, 4), round(pf, 3))

OLD = {  # (window, cfg) -> friction avg_R reference from DB runs
    ("90d", "A_5m_4h"): 0.5185, ("90d", "B_5m_1h"): 0.4020,
    ("365d", "A_5m_4h"): 0.4705, ("365d", "B_5m_1h"): 0.4750,
    ("720d", "A_5m_4h"): 0.4536, ("720d", "B_5m_1h"): 0.4840,
}

print("=" * 96)
print("POST-TP2 TRAIL MODEL — backtest sweep (in-memory, no DB writes)")
print("=" * 96)
for win in WINDOWS:
    G.START_MS = win["start"]; G.END_MS = win["end"]; G.load_cached = make_loader(win)
    # coverage probe
    probe = G.load_cached("ETH", "5m")
    cov = "MISSING"
    if probe:
        f = lambda x: datetime.fromtimestamp(x / 1000, timezone.utc).strftime("%Y-%m-%d")
        cov = f"{f(probe['times'][0])}->{f(probe['times'][-1])} n={len(probe['times'])}"
    print(f"\n### WINDOW {win['name']}  (ETH 5m coverage: {cov})")
    for cfg in CFGS:
        clean = []
        cache = {}
        for tok in G.TOKENS:
            clean += G.run_one_token(tok, cfg, detect, compute_sl_tp, compute_econ, TOKEN_RT_COST, ROUND_TRIP_COST_PCT)
            cache[tok] = G.load_cached(tok, cfg["entry_tf"])
        fric = G.apply_friction(clean, cfg, cache, derive_seed, simulate_execution)
        nc, ac, cc, wrc, pfc = agg(clean); nf, af, cf, wrf, pff = agg(fric)
        oldf = OLD.get((win["name"], cfg["id"]))
        delta = f"{af-oldf:+.4f}" if oldf is not None else "n/a"
        print(f"  {cfg['id']:<8} CLEAN  n={nc:<6} avg_R={ac:+.4f}   "
              f"FRICTION n={nf:<6} avg_R={af:+.4f}  WR={wrf*100:.2f}%  PF={pff}  (old {oldf}  delta {delta})")
        print(f"           FRICTION outcomes: " +
              " ".join(f"{k}={cf.get(k,0)}" for k in
                       ["WIN", "PARTIAL_TP2", "PARTIAL_TP2_T1", "PARTIAL_TP1", "LOSS", "EXPIRED"]))
print("\nDone.")
