"""run_fib_tf_robustness.py — V_FIB across multiple (entry_TF / ref_TF) combos.

PHASE C-BREAKOUT. Adjudicates the TF_A-vs-TF_B inversion from
FIB_PULLBACK_ENTRY_TEST.md: is the +0.913 on 5M/4H part of a consistent
REFERENCE-TF-driven pattern (operator's alignment hypothesis) or an isolated
lucky cell (random-walk selection artifact)?

Same pre-registered V_FIB definition as FIB_PULLBACK_ENTRY_TEST.md (0.5-0.618
pullback, limit at 0.5, SL below 0.618, 30-entry-bar pullback window, TP 2/3/4R,
post-TP2 = V_ENTRY hold_entry, friction). ONLY the TF pair changes per combo.

DATA REALITY (verified before running):
  - 720d cache has ONLY 5m / 1h / 4h. 15m and 12h are built by EXACT aggregation
    (15m = 3x5m, 12h = 3x4h — coarsening, lossless, NOT fabrication).
  - 1m exists ONLY at 90d (data/cache_1m_90d). So C3 (1M/1H) and C4 (1M/4H) CANNOT
    run at 720d. 1M is NOT resampled from 5M (would destroy the entry-timing test).
  - PRIMARY panel (720d): C1 5M/1H, C2 5M/4H, C5 15M/4H, C6 5M/12H.
  - SECONDARY panel (90d, shorter window, labelled separately): 5M/1H, 5M/4H,
    1M/1H, 1M/4H — the only window where 1m exists, to still answer C3/C4.

IN-MEMORY ONLY — no DB writes. Soaks + fade + signals.db + main untouched.
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
from validation import sharpe_ratio, deflated_sharpe_ratio, _moments
from config import MIN_SL_PCT, MAX_SL_PCT


def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


WIN720 = {"start": ms(2024, 6, 10), "end": ms(2026, 5, 31)}
CACHE720 = _BD / "data" / "ohlcv_cache_720d"
DUR = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
       "1h": 3_600_000, "4h": 14_400_000, "12h": 43_200_000}
AGG_BASE = {"15m": ("5m", 900_000), "12h": ("4h", 43_200_000)}

os.environ.update(G.LOCKED_KNOBS)
import breakout_engine as _be
importlib.reload(_be)
detect = _be.detect_h4_breakout
compute_sl_tp = _be.compute_breakout_sl_tp
TP1_RR = _be.BREAKOUT_TP1_RR; TP2_RR = _be.BREAKOUT_TP2_RR; TP3_RR = _be.BREAKOUT_TP3_RR
SL_BUF = _be.BREAKOUT_SL_INSIDE_BUFFER_PCT
FIB_A, FIB_B, PULLBACK_WINDOW = 0.5, 0.618, 30


# ── Loaders ──────────────────────────────────────────────────────────────────
def _read_720(tok, tf):
    p = CACHE720 / f"{tok}USDT_{tf}_720d.json"
    if not p.exists():
        return None
    return (json.load(open(p)) or {}).get("data")


def _aggregate(inner, bucket_ms):
    o, h, l, c, t = inner["opens"], inner["highs"], inner["lows"], inner["closes"], inner["times"]
    O = H = L = C = T = None
    ro, rh, rl, rc, rt = [], [], [], [], []
    cur = None
    for i in range(len(t)):
        b = (t[i] // bucket_ms) * bucket_ms
        if cur is None or b != cur:
            if cur is not None:
                ro.append(O); rh.append(H); rl.append(L); rc.append(C); rt.append(cur)
            cur = b; O = o[i]; H = h[i]; L = l[i]; C = c[i]
        else:
            if h[i] > H: H = h[i]
            if l[i] < L: L = l[i]
            C = c[i]
    if cur is not None:
        ro.append(O); rh.append(H); rl.append(L); rc.append(C); rt.append(cur)
    return {"opens": ro, "highs": rh, "lows": rl, "closes": rc, "times": rt}


def load_720(tok, tf):
    """720d loader. 15m/12h built by exact aggregation from 5m/4h."""
    if tf in AGG_BASE:
        base_tf, bucket = AGG_BASE[tf]
        base = _read_720(tok, base_tf)
        if not base:
            return None
        inner = _aggregate(base, bucket)
    else:
        inner = _read_720(tok, tf)
        if not inner:
            return None
    t = inner["times"]
    i0 = bisect.bisect_left(t, WIN720["start"]); i1 = bisect.bisect_right(t, WIN720["end"])
    if i1 - i0 < 30:
        return None
    return {k: inner[k][i0:i1] for k in ("opens", "highs", "lows", "closes")} | {"times": t[i0:i1]}


# SECONDARY 90d loader = run_tf_grid native (5m/1h/4h from 365d cache, 1m from cache_1m_90d)
load_90 = G.load_cached  # G.START_MS/END_MS left at their 90d defaults


# ── Regime map (BTC 4h SMA30 over 720d; date-keyed, covers 90d subset too) ───
def regime_map():
    c = load_720("BTC", "4h"); by = {}
    for t, cl in zip(c["times"], c["closes"]):
        by[datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")] = cl
    ds = sorted(by); cs = [by[d] for d in ds]; r = {}
    for i, d in enumerate(ds):
        if i < 30:
            r[d] = "RANGE"; continue
        sma = sum(cs[i - 30:i]) / 30; c0 = cs[i]
        r[d] = "BULL" if c0 > sma * 1.03 else "BEAR" if c0 < sma * 0.97 else "RANGE"
    return r


REGIME = regime_map()


def maxdd(rs):
    cum = peak = mdd = 0.0
    for r in rs:
        cum += r; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    return mdd


def metrics(sigs):
    rs = [s["realized_r"] for s in sigs]; n = len(rs)
    if n == 0:
        return {"n": 0}
    pos = sum(1 for r in rs if r > 0)
    wins = [r for r in rs if r > 0]; loss = [r for r in rs if r < 0]
    gp = sum(wins); gl = sum(-r for r in loss)
    ss = sorted(sigs, key=lambda s: s["ts"]); cut = int(len(ss) * 0.7)
    tr = [s["realized_r"] for s in ss[:cut]]; te = [s["realized_r"] for s in ss[cut:]]
    sk, ku = _moments(rs)[2], _moments(rs)[3]
    reg = defaultdict(list)
    for s in sigs:
        reg[REGIME.get(s["ts"][:10], "RANGE")].append(s["realized_r"])
    bt = defaultdict(list)
    for s in sigs:
        bt[s["token"]].append(s["realized_r"])
    return {"n": n, "wr": pos / n, "avg": sum(rs) / n, "sum": sum(rs),
            "pf": (gp / gl) if gl > 0 else float("inf"),
            "mdd": maxdd([s["realized_r"] for s in ss]),
            "train": sum(tr) / len(tr) if tr else 0, "test": sum(te) / len(te) if te else 0,
            "sharpe": sharpe_ratio(rs, 1.0), "skew": sk, "kurt": ku,
            "regime": {k: (sum(v) / len(v), len(v)) for k, v in reg.items()},
            "by_tok": {k: (sum(v) / len(v), len(v)) for k, v in bt.items()}}


def fib_sl_tp(direction, entry, sl_raw):
    if direction == "BUY":
        sl = min(sl_raw, entry * (1.0 - MIN_SL_PCT))
        if sl <= 0:
            return None
        if (entry - sl) / entry > MAX_SL_PCT:
            return None
        rd = entry - sl
        return sl, entry + TP1_RR * rd, entry + TP2_RR * rd, entry + TP3_RR * rd
    else:
        sl = max(sl_raw, entry * (1.0 + MIN_SL_PCT))
        if (sl - entry) / entry > MAX_SL_PCT:
            return None
        rd = sl - entry
        return sl, entry - TP1_RR * rd, entry - TP2_RR * rd, entry - TP3_RR * rd


def _nets(direction, entry, sl, t1, t2, t3, outcome, rt):
    if direction == "BUY":
        g1 = (t1 - entry) / entry * 100; g2 = (t2 - entry) / entry * 100
        g3 = (t3 - entry) / entry * 100; gs = (sl - entry) / entry * 100
    else:
        g1 = (entry - t1) / entry * 100; g2 = (entry - t2) / entry * 100
        g3 = (entry - t3) / entry * 100; gs = (entry - sl) / entry * 100
    n1 = round(g1 - rt, 3); n2 = round(g2 - rt, 3); n3 = round(g3 - rt, 3); ns = round(gs - rt, 2)
    r = G._calc_realized_r(outcome, n1, ns, n2, n3, rt)
    return g1, gs, n1, n2, n3, ns, r


# ── Paired V_CURRENT + V_FIB run for one (token, cfg, loader) ────────────────
def run_paired(token, cfg, loader):
    c_entry = loader(token, cfg["entry_tf"]); c_ref = loader(token, cfg["ref_tf"])
    if c_entry is None or c_ref is None:
        return [], [], []
    n_entry = len(c_entry["closes"]); n_ref = len(c_ref["closes"])
    fwd = G.FORWARD_MINUTES // (cfg["entry_bar_duration_ms"] // 60_000)
    if n_entry < fwd + 100 or n_ref < 20:
        return [], [], []
    rt = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
    he = c_entry["highs"]; le = c_entry["lows"]; oe = c_entry["opens"]
    ref_window = 4 + G.H4_WINDOW_BUFFER; ref_dur = cfg["ref_bar_duration_ms"]
    cur_sigs, fib_sigs, pairs = [], [], []
    consumed = set()
    for ref_end in range(ref_window, n_ref):
        ref_sub = {k: c_ref[k][ref_end - ref_window:ref_end] for k in c_ref}
        ref_close_t = c_ref["times"][ref_end - 1] + ref_dur
        e_end = bisect.bisect_right(c_entry["times"], ref_close_t)
        e_end = min(e_end + 30 + 10, n_entry)
        e_start = max(0, e_end - G.ENTRY_WINDOW_SIZE)
        if e_end - e_start < 30:
            continue
        entry_sub = {k: c_entry[k][e_start:e_end] for k in c_entry}
        setup = detect(ref_sub, entry_sub, token=token, consumed=consumed)
        if setup is None:
            continue
        consumed.add(setup["key"])
        mss_abs = e_start + setup["mss_bar_5m"]; sweep_abs = e_start + setup["sweep_5m_idx"]
        if mss_abs >= n_entry - fwd - 1 or sweep_abs > mss_abs:
            continue
        direction = setup["direction"]; c1_high = setup["c1_high"]; c1_low = setup["c1_low"]
        pair = {"cur": None, "fib": None}

        # V_CURRENT
        e_bar = mss_abs + 1
        if e_bar < n_entry - fwd - 1:
            ep = oe[e_bar]
            st = compute_sl_tp(direction, ep, setup["sl_anchor"], c1_high, c1_low)
            if st is not None:
                sl, t1, t2, t3 = st
                if compute_econ(direction, ep, sl, t1, t2, t3, None, rt) is not None:
                    fut = [{"h": he[j], "l": le[j]} for j in range(e_bar + 1, min(e_bar + 1 + fwd, n_entry))]
                    if fut:
                        oc, tpr = G.check_outcome(direction, ep, sl, t1, t2, t3, fut)
                        g1, gs, n1, n2, n3, ns, rr = _nets(direction, ep, sl, t1, t2, t3, oc, rt)
                        ts = datetime.fromtimestamp(c_entry["times"][e_bar] / 1000, timezone.utc)
                        cur_sigs.append({"token": token, "signal": direction, "price": round(ep, 8),
                                         "ts": ts.strftime("%Y-%m-%d %H:%M:%S"), "tp1_pct": round(g1, 3),
                                         "sl_pct": round(gs, 3), "net_tp1_pct": n1, "net_tp2_pct": n2,
                                         "net_tp3_pct": n3, "net_sl_pct": ns, "outcome": oc,
                                         "realized_r": rr, "entry_bar_idx": e_bar})
                        pair["cur"] = (oc, rr)

        # V_FIB
        if direction == "BUY":
            leg_low = c1_low; leg_high = max(he[sweep_abs:mss_abs + 1]); leg = leg_high - leg_low
            if leg > 0:
                fib05 = leg_high - FIB_A * leg; fib618 = leg_high - FIB_B * leg
                fb = -1
                for j in range(mss_abs + 1, min(mss_abs + 1 + PULLBACK_WINDOW, n_entry)):
                    if le[j] <= fib05:
                        fb = j; break
                if fb >= 0 and fb < n_entry - fwd - 1:
                    st = fib_sl_tp("BUY", fib05, fib618 * (1.0 - SL_BUF))
                    if st and compute_econ("BUY", fib05, *st, None, rt) is not None:
                        sl, t1, t2, t3 = st
                        if le[fb] <= sl:
                            oc, tpr = "LOSS", 0
                        else:
                            fut = [{"h": he[k], "l": le[k]} for k in range(fb + 1, min(fb + 1 + fwd, n_entry))]
                            oc, tpr = G.check_outcome("BUY", fib05, sl, t1, t2, t3, fut) if fut else ("EXPIRED", 0)
                        g1, gs, n1, n2, n3, ns, rr = _nets("BUY", fib05, sl, t1, t2, t3, oc, rt)
                        ts = datetime.fromtimestamp(c_entry["times"][fb] / 1000, timezone.utc)
                        fib_sigs.append({"token": token, "signal": "BUY", "price": round(fib05, 8),
                                         "ts": ts.strftime("%Y-%m-%d %H:%M:%S"), "tp1_pct": round(g1, 3),
                                         "sl_pct": round(gs, 3), "net_tp1_pct": n1, "net_tp2_pct": n2,
                                         "net_tp3_pct": n3, "net_sl_pct": ns, "outcome": oc,
                                         "realized_r": rr, "entry_bar_idx": fb})
                        pair["fib"] = (oc, rr)
        else:
            leg_high = c1_high; leg_low = min(le[sweep_abs:mss_abs + 1]); leg = leg_high - leg_low
            if leg > 0:
                fib05 = leg_low + FIB_A * leg; fib618 = leg_low + FIB_B * leg
                fb = -1
                for j in range(mss_abs + 1, min(mss_abs + 1 + PULLBACK_WINDOW, n_entry)):
                    if he[j] >= fib05:
                        fb = j; break
                if fb >= 0 and fb < n_entry - fwd - 1:
                    st = fib_sl_tp("SELL", fib05, fib618 * (1.0 + SL_BUF))
                    if st and compute_econ("SELL", fib05, *st, None, rt) is not None:
                        sl, t1, t2, t3 = st
                        if he[fb] >= sl:
                            oc, tpr = "LOSS", 0
                        else:
                            fut = [{"h": he[k], "l": le[k]} for k in range(fb + 1, min(fb + 1 + fwd, n_entry))]
                            oc, tpr = G.check_outcome("SELL", fib05, sl, t1, t2, t3, fut) if fut else ("EXPIRED", 0)
                        g1, gs, n1, n2, n3, ns, rr = _nets("SELL", fib05, sl, t1, t2, t3, oc, rt)
                        ts = datetime.fromtimestamp(c_entry["times"][fb] / 1000, timezone.utc)
                        fib_sigs.append({"token": token, "signal": "SELL", "price": round(fib05, 8),
                                         "ts": ts.strftime("%Y-%m-%d %H:%M:%S"), "tp1_pct": round(g1, 3),
                                         "sl_pct": round(gs, 3), "net_tp1_pct": n1, "net_tp2_pct": n2,
                                         "net_tp3_pct": n3, "net_sl_pct": ns, "outcome": oc,
                                         "realized_r": rr, "entry_bar_idx": fb})
                        pair["fib"] = (oc, rr)
        pairs.append(pair)
    return cur_sigs, fib_sigs, pairs


# ── Combo definitions ────────────────────────────────────────────────────────
def mkcfg(cid, etf, rtf, label):
    return {"id": cid, "entry_tf": etf, "ref_tf": rtf,
            "ref_bar_duration_ms": DUR[rtf], "entry_bar_duration_ms": DUR[etf], "label": label}


PRIMARY = [
    mkcfg("C1_5m_1h", "5m", "1h", "5M / 1H  (failing TF_B anchor)"),
    mkcfg("C2_5m_4h", "5m", "4h", "5M / 4H  (passing TF_A anchor)"),
    mkcfg("C5_15m_4h", "15m", "4h", "15M / 4H (slower entry, 4H ref)"),
    mkcfg("C6_5m_12h", "5m", "12h", "5M / 12H (even higher ref)"),
]
SECONDARY = [
    mkcfg("S1_5m_1h", "5m", "1h", "5M / 1H  (90d anchor)"),
    mkcfg("S2_5m_4h", "5m", "4h", "5M / 4H  (90d anchor)"),
    mkcfg("S3_1m_1h", "1m", "1h", "1M / 1H  (=C3 faster entry)"),
    mkcfg("S4_1m_4h", "1m", "4h", "1M / 4H  (=C4 faster entry, higher ref)"),
]


def run_panel(name, cfgs, loader, window_label):
    print(f"\n{'#'*100}\n# {name}  ({window_label})\n{'#'*100}")
    res = {}; pairs_by = {}
    for cfg in cfgs:
        cur_all, fib_all, pair_all, cache = [], [], [], {}
        for tok in G.TOKENS:
            c, f, p = run_paired(tok, cfg, loader)
            cur_all += c; fib_all += f; pair_all += p
            cache[tok] = loader(tok, cfg["entry_tf"])
        cur_fric = G.apply_friction(cur_all, cfg, cache, derive_seed, simulate_execution)
        fib_fric = G.apply_friction(fib_all, cfg, cache, derive_seed, simulate_execution)
        res[cfg["id"]] = {"cur": metrics(cur_fric), "fib": metrics(fib_fric),
                          "n_det": len(pair_all)}
        pairs_by[cfg["id"]] = pair_all
        print(f"  [done] {cfg['id']}: det={len(pair_all)} "
              f"V_CUR n={res[cfg['id']]['cur'].get('n',0)} avg={res[cfg['id']]['cur'].get('avg',0):+.3f} | "
              f"V_FIB n={res[cfg['id']]['fib'].get('n',0)} avg={res[cfg['id']]['fib'].get('avg',0):+.3f}")

    # DSR deflated across the panel's V_FIB combos (n_trials=6 per pre-registration intent)
    fib_sharpes = [res[c["id"]]["fib"].get("sharpe", 0) for c in cfgs if res[c["id"]]["fib"].get("n", 0) > 0]
    sr_std = statistics.pstdev(fib_sharpes) if len(fib_sharpes) > 1 else 0.0

    print(f"\n  {'combo':<12}{'ref':>5}{'n':>7}{'avg_R':>9}{'WR%':>7}{'PF':>7}{'maxDD':>8}"
          f"{'train':>8}{'test':>8}{'DSR6':>7}{'tok>.40':>9}{'pull%':>7}")
    for cfg in cfgs:
        r = res[cfg["id"]]; vf = r["fib"]
        if vf.get("n", 0) == 0:
            print(f"  {cfg['id']:<12}{cfg['ref_tf']:>5}      0   (no V_FIB signals)"); continue
        dsr = (deflated_sharpe_ratio(vf["sharpe"], vf["n"], 6, sr_std, skew=vf["skew"],
                                     kurtosis=vf["kurt"]) if sr_std > 0 else 1.0)
        ntok = sum(1 for t, (a, nn) in vf["by_tok"].items() if a > 0.40)
        pull = 100 * (vf["n"] if False else r["fib"]["n"]) / r["n_det"]  # post-friction proxy
        # use detected -> traded fraction from pairs
        n_pull = sum(1 for p in pairs_by[cfg["id"]] if p["fib"] is not None)
        pull = 100 * n_pull / r["n_det"] if r["n_det"] else 0
        print(f"  {cfg['id']:<12}{cfg['ref_tf']:>5}{vf['n']:>7}{vf['avg']:>+9.3f}{vf['wr']*100:>6.1f}%"
              f"{vf['pf']:>7.2f}{vf['mdd']:>8.1f}{vf['train']:>+8.3f}{vf['test']:>+8.3f}"
              f"{dsr:>7.3f}{ntok:>6}/12{pull:>6.1f}%")
        res[cfg["id"]]["dsr"] = dsr; res[cfg["id"]]["ntok"] = ntok; res[cfg["id"]]["pull"] = pull

    # Detail per combo: per-token, per-regime, shield
    for cfg in cfgs:
        r = res[cfg["id"]]; vf = r["fib"]; pr = pairs_by[cfg["id"]]
        if vf.get("n", 0) == 0:
            continue
        print(f"\n  --- {cfg['id']} ({cfg['label']}) ---")
        toks = sorted(vf["by_tok"].items(), key=lambda x: -x[1][0])
        print("    per-token avg_R: " + "  ".join(f"{t}:{a:+.2f}(n{nn})" for t, (a, nn) in toks))
        print("    per-regime avg_R: " + "  ".join(
            f"{rg}:{vf['regime'].get(rg,(0,0))[0]:+.3f}(n{vf['regime'].get(rg,(0,0))[1]})"
            for rg in ("BULL", "BEAR", "RANGE")))
        cl = [p for p in pr if p["cur"] is not None and p["cur"][0] == "LOSS"]
        av = sum(1 for p in cl if p["fib"] is None)
        sv = sum(1 for p in cl if p["fib"] is not None and p["fib"][0] != "LOSS")
        tl = sum(1 for p in cl if p["fib"] is not None and p["fib"][0] == "LOSS")
        if cl:
            print(f"    shield: V_CUR losses={len(cl)} -> V_FIB avoided(no trade)={av} "
                  f"({100*av/len(cl):.0f}%), saved(better entry)={sv} ({100*sv/len(cl):.0f}%), "
                  f"took&lost={tl} ({100*tl/len(cl):.0f}%)")
    return res


print("=" * 100)
print("FIB TIMEFRAME ROBUSTNESS — does the 5M/4H V_FIB edge generalize by reference-TF height?")
print("=" * 100)
RES_PRIMARY = run_panel("PRIMARY PANEL", PRIMARY, load_720, "720d  2024-06-10 -> 2026-05-31")
RES_SECONDARY = run_panel("SECONDARY PANEL", SECONDARY, load_90, "90d  (only window with 1m data)")
print("\nDone. (in-memory only; no DB writes)")
