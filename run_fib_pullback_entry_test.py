"""run_fib_pullback_entry_test.py — V_CURRENT (MSS-bar+1 market entry) vs
V_FIB (wait for 0.5-0.618 pullback, limit entry, SL below the fib zone).

PHASE C-BREAKOUT entry-timing test. 720d, Config 14 LOCKED_KNOBS, friction,
TF_A (5M/4H) + TF_B (5M/1H), post-TP2 = V_ENTRY (hold_entry, the live model).

IN-MEMORY ONLY — no breakout.db writes, no signals.db, no main. Reuses
run_tf_grid (G) for: 720d load, detection scaffold, check_outcome (hold_entry),
_calc_realized_r, apply_friction, and validation DSR.

PRE-REGISTERED V_FIB design (stated BEFORE running — not tuned post-hoc):
  - Both variants share the SAME detected setups (identical detect() call +
    consumed logic). Only the ENTRY differs → clean per-setup pairing.
  - V_CURRENT: enter at mss_bar+1 open (the live entry). [baseline]
  - V_FIB impulse-leg anchor (CAUSAL — uses only bars <= mss_bar):
      BUY  : leg_low  = C1.low (structural base of the broken candle range)
             leg_high = max(entry-TF highs over [sweep_5m_idx .. mss_bar])
      SELL : leg_high = C1.high (structural top of the broken candle range)
             leg_low  = min(entry-TF lows  over [sweep_5m_idx .. mss_bar])
      leg  = leg_high - leg_low   (require > 0)
  - Fib retracement zone = 0.5 .. 0.618 of that leg:
      BUY  : fib_0.5 = leg_high - 0.5*leg   (upper, touched first on a pullback)
             fib_618 = leg_high - 0.618*leg (lower)
      SELL : fib_0.5 = leg_low  + 0.5*leg   (lower, touched first)
             fib_618 = leg_low  + 0.618*leg (upper)
  - ENTRY = FIRST TOUCH of the 0.5 level (pending limit at fib_0.5):
      BUY  fills on the first forward bar whose LOW  <= fib_0.5
      SELL fills on the first forward bar whose HIGH >= fib_0.5
  - SL = just beyond the 0.618 level (BREAKOUT_SL_INSIDE_BUFFER_PCT buffer):
      BUY  SL = fib_618 * (1 - buf)   (BELOW the zone)
      SELL SL = fib_618 * (1 + buf)   (ABOVE the zone)
    then MIN_SL_PCT floor / MAX_SL_PCT ceiling applied (mirrors
    compute_breakout_sl_tp). Floor-overrides counted (erode the shield).
  - TP1/2/3 = LOCKED BREAKOUT_TP*_RR (2/3/4 R) from the fib entry.
  - PULLBACK WINDOW = H4_BREAKOUT_MSS_HORIZON (30) entry-TF bars forward from
    mss_bar. No touch in the window -> NO TRADE (signal skipped).
  - Intrabar: limit fills at fib_0.5; if the SAME fill bar also pierces SL,
    it's an immediate LOSS (entry-fills-first-then-SL). Else outcome runs from
    fill_bar+1 over forward_entry_bars.
  - NO LOOK-AHEAD: fib levels from bars <= mss_bar; pullback detected bar-by-bar
    going forward; fill_bar > mss_bar always (asserted).

PRE-COMMITTED DECISION RULE: V_FIB is a real improvement ONLY IF its OOS-test
avg_R >= +0.40 AND the gain over V_CURRENT holds OOS AND across regimes AND DSR
passes. Else: fib zone has no shield/edge property (random-walk non-event).
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


# ── 720d window + cache override (identical to posttp2 comparison) ───────────
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
    t = inner["times"]
    i0 = bisect.bisect_left(t, WIN["start"]); i1 = bisect.bisect_right(t, WIN["end"])
    if i1 - i0 < 30:
        return None
    return {k: inner[k][i0:i1] for k in ("opens", "highs", "lows", "closes")} | {"times": t[i0:i1]}


G.load_cached = load_cached

# Lock Config 14 + reload engine so constants pick up env
os.environ.update(G.LOCKED_KNOBS)
import breakout_engine as _be
importlib.reload(_be)
detect = _be.detect_h4_breakout
compute_sl_tp = _be.compute_breakout_sl_tp
TP1_RR = _be.BREAKOUT_TP1_RR; TP2_RR = _be.BREAKOUT_TP2_RR; TP3_RR = _be.BREAKOUT_TP3_RR
SL_BUF = _be.BREAKOUT_SL_INSIDE_BUFFER_PCT

CFGS = [c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h", "B_5m_1h")]

# ── Pre-registered fib constants ─────────────────────────────────────────────
FIB_A = 0.5      # entry-level retracement (first touch)
FIB_B = 0.618    # SL-anchor retracement
PULLBACK_WINDOW = 30   # = H4_BREAKOUT_MSS_HORIZON, entry-TF bars forward


# ── Regime map (BTC 4h SMA30, identical to posttp2 comparison) ───────────────
def regime_map():
    c = load_cached("BTC", "4h"); by = {}
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
    wins_r = [r for r in rs if r > 0]; loss_r = [r for r in rs if r < 0]
    gp = sum(wins_r); gl = sum(-r for r in loss_r)
    ss = sorted(sigs, key=lambda s: s["ts"]); cut = int(len(ss) * 0.7)
    tr = [s["realized_r"] for s in ss[:cut]]; te = [s["realized_r"] for s in ss[cut:]]
    sk, ku = _moments(rs)[2], _moments(rs)[3]
    reg = defaultdict(list)
    for s in sigs:
        reg[REGIME.get(s["ts"][:10], "RANGE")].append(s["realized_r"])
    return {"n": n, "wr": pos / n, "avg": sum(rs) / n, "sum": sum(rs),
            "pf": (gp / gl) if gl > 0 else float("inf"),
            "mdd": maxdd([s["realized_r"] for s in ss]),
            "oc": Counter(s["outcome"] for s in sigs),
            "avg_win": (sum(wins_r) / len(wins_r)) if wins_r else 0.0,
            "avg_loss": (sum(loss_r) / len(loss_r)) if loss_r else 0.0,
            "train": sum(tr) / len(tr) if tr else 0, "test": sum(te) / len(te) if te else 0,
            "sharpe": sharpe_ratio(rs, 1.0), "skew": sk, "kurt": ku,
            "regime": {k: (sum(v) / len(v), len(v)) for k, v in reg.items()}}


# ── Fib SL/TP (mirror compute_breakout_sl_tp, anchor = fib_0.618) ────────────
def fib_sl_tp(direction, entry, sl_raw):
    """Return (sl, tp1, tp2, tp3, floored) or None. `floored`=True when the
    MIN_SL_PCT floor widened SL beyond the fib_0.618 anchor (shield eroded)."""
    if direction == "BUY":
        floored = sl_raw > entry * (1.0 - MIN_SL_PCT)
        sl = min(sl_raw, entry * (1.0 - MIN_SL_PCT))
        if sl <= 0:
            return None
        sl_pct = (entry - sl) / entry
        if sl_pct > MAX_SL_PCT:
            return None
        rd = entry - sl
        return sl, entry + TP1_RR * rd, entry + TP2_RR * rd, entry + TP3_RR * rd, floored
    else:
        floored = sl_raw < entry * (1.0 + MIN_SL_PCT)
        sl = max(sl_raw, entry * (1.0 + MIN_SL_PCT))
        sl_pct = (sl - entry) / entry
        if sl_pct > MAX_SL_PCT:
            return None
        rd = sl - entry
        return sl, entry - TP1_RR * rd, entry - TP2_RR * rd, entry - TP3_RR * rd, floored


def _econ_nets(direction, entry, sl, tp1, tp2, tp3, outcome, rt_cost_pct):
    """Gross %s + net %s + realized_r via G._calc_realized_r (split-exit)."""
    if direction == "BUY":
        g1 = (tp1 - entry) / entry * 100; g2 = (tp2 - entry) / entry * 100
        g3 = (tp3 - entry) / entry * 100; gs = (sl - entry) / entry * 100
    else:
        g1 = (entry - tp1) / entry * 100; g2 = (entry - tp2) / entry * 100
        g3 = (entry - tp3) / entry * 100; gs = (entry - sl) / entry * 100
    n1 = round(g1 - rt_cost_pct, 3); n2 = round(g2 - rt_cost_pct, 3)
    n3 = round(g3 - rt_cost_pct, 3); ns = round(gs - rt_cost_pct, 2)
    r = G._calc_realized_r(outcome, n1, ns, n2, n3, rt_cost_pct)
    return g1, gs, n1, n2, n3, ns, r


def _sig_dict(token, direction, entry, ts, g1, gs, n1, n2, n3, ns, outcome,
              tp_reached, realized_r, entry_bar):
    return {
        "token": token, "signal": direction, "price": round(entry, 8),
        "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "tp1_pct": round(g1, 3), "sl_pct": round(gs, 3),
        "net_tp1_pct": n1, "net_tp2_pct": n2, "net_tp3_pct": n3, "net_sl_pct": ns,
        "rr1": round(abs(g1 / gs), 2) if gs else 0,
        "tp_reached": tp_reached, "outcome": outcome, "realized_r": realized_r,
        "hour_utc": ts.hour, "day_of_week": ts.weekday(),
        "entry_bar_idx": entry_bar,
    }


# ── Paired run: ONE detection pass, emits V_CURRENT + V_FIB per setup ─────────
def run_paired(token, cfg):
    c_entry = G.load_cached(token, cfg["entry_tf"])
    c_ref = G.load_cached(token, cfg["ref_tf"])
    if c_entry is None or c_ref is None:
        return [], [], []
    n_entry = len(c_entry["closes"]); n_ref = len(c_ref["closes"])
    fwd = G.FORWARD_MINUTES // (cfg["entry_bar_duration_ms"] // 60_000)
    if n_entry < fwd + 100 or n_ref < 20:
        return [], [], []
    rt = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
    he = c_entry["highs"]; le = c_entry["lows"]; oe = c_entry["opens"]
    ref_window = 4 + G.H4_WINDOW_BUFFER
    ref_dur = cfg["ref_bar_duration_ms"]

    cur_sigs, fib_sigs, pairs = [], [], []
    consumed = set()
    for ref_end in range(ref_window, n_ref):
        ref_start = ref_end - ref_window
        ref_sub = {k: c_ref[k][ref_start:ref_end] for k in c_ref}
        ref_open_t = c_ref["times"][ref_end - 1]; ref_close_t = ref_open_t + ref_dur
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

        mss_abs = e_start + setup["mss_bar_5m"]
        sweep_abs = e_start + setup["sweep_5m_idx"]
        if mss_abs >= n_entry - fwd - 1 or sweep_abs > mss_abs:
            continue
        direction = setup["direction"]
        c1_high = setup["c1_high"]; c1_low = setup["c1_low"]
        pair = {"token": token, "dir": direction, "ts_ref": setup["c2_time"],
                "cur": None, "fib": None, "fib_skip": None}

        # ── V_CURRENT: market entry at mss+1 open ────────────────────────────
        e_bar = mss_abs + 1
        if e_bar < n_entry - fwd - 1:
            ep = oe[e_bar]
            st = compute_sl_tp(direction, ep, setup["sl_anchor"], c1_high, c1_low)
            if st is not None:
                sl, t1, t2, t3 = st
                if compute_econ(direction, ep, sl, t1, t2, t3, None, rt) is not None:
                    future = [{"h": he[j], "l": le[j]}
                              for j in range(e_bar + 1, min(e_bar + 1 + fwd, n_entry))]
                    if future:
                        oc, tpr = G.check_outcome(direction, ep, sl, t1, t2, t3, future)
                        g1, gs, n1, n2, n3, ns, rr = _econ_nets(direction, ep, sl, t1, t2, t3, oc, rt)
                        ts = datetime.fromtimestamp(c_entry["times"][e_bar] / 1000, timezone.utc)
                        d = _sig_dict(token, direction, ep, ts, g1, gs, n1, n2, n3, ns, oc, tpr, rr, e_bar)
                        cur_sigs.append(d); pair["cur"] = (oc, rr)

        # ── V_FIB: wait for 0.5-0.618 pullback, limit entry, SL below zone ───
        if direction == "BUY":
            leg_low = c1_low
            leg_high = max(he[sweep_abs:mss_abs + 1])
            leg = leg_high - leg_low
            if leg > 0:
                fib05 = leg_high - FIB_A * leg
                fib618 = leg_high - FIB_B * leg
                fill_bar = -1
                scan_end = min(mss_abs + 1 + PULLBACK_WINDOW, n_entry)
                for j in range(mss_abs + 1, scan_end):
                    if le[j] <= fib05:
                        fill_bar = j; break
                if fill_bar < 0:
                    pair["fib_skip"] = "no_pullback"
                elif fill_bar >= n_entry - fwd - 1:
                    pair["fib_skip"] = "no_room"
                else:
                    assert fill_bar > mss_abs  # causality
                    ep = fib05
                    st = fib_sl_tp("BUY", ep, fib618 * (1.0 - SL_BUF))
                    if st is None:
                        pair["fib_skip"] = "geometry"
                    else:
                        sl, t1, t2, t3, floored = st
                        if compute_econ("BUY", ep, sl, t1, t2, t3, None, rt) is None:
                            pair["fib_skip"] = "econ"
                        else:
                            # same-bar SL pierce after limit fill -> immediate LOSS
                            if le[fill_bar] <= sl:
                                oc, tpr = "LOSS", 0
                            else:
                                future = [{"h": he[k], "l": le[k]}
                                          for k in range(fill_bar + 1, min(fill_bar + 1 + fwd, n_entry))]
                                oc, tpr = G.check_outcome("BUY", ep, sl, t1, t2, t3, future) if future else ("EXPIRED", 0)
                            g1, gs, n1, n2, n3, ns, rr = _econ_nets("BUY", ep, sl, t1, t2, t3, oc, rt)
                            ts = datetime.fromtimestamp(c_entry["times"][fill_bar] / 1000, timezone.utc)
                            d = _sig_dict(token, "BUY", ep, ts, g1, gs, n1, n2, n3, ns, oc, tpr, rr, fill_bar)
                            d["floored"] = floored
                            fib_sigs.append(d); pair["fib"] = (oc, rr)
        else:  # SELL
            leg_high = c1_high
            leg_low = min(le[sweep_abs:mss_abs + 1])
            leg = leg_high - leg_low
            if leg > 0:
                fib05 = leg_low + FIB_A * leg
                fib618 = leg_low + FIB_B * leg
                fill_bar = -1
                scan_end = min(mss_abs + 1 + PULLBACK_WINDOW, n_entry)
                for j in range(mss_abs + 1, scan_end):
                    if he[j] >= fib05:
                        fill_bar = j; break
                if fill_bar < 0:
                    pair["fib_skip"] = "no_pullback"
                elif fill_bar >= n_entry - fwd - 1:
                    pair["fib_skip"] = "no_room"
                else:
                    assert fill_bar > mss_abs
                    ep = fib05
                    st = fib_sl_tp("SELL", ep, fib618 * (1.0 + SL_BUF))
                    if st is None:
                        pair["fib_skip"] = "geometry"
                    else:
                        sl, t1, t2, t3, floored = st
                        if compute_econ("SELL", ep, sl, t1, t2, t3, None, rt) is None:
                            pair["fib_skip"] = "econ"
                        else:
                            if he[fill_bar] >= sl:
                                oc, tpr = "LOSS", 0
                            else:
                                future = [{"h": he[k], "l": le[k]}
                                          for k in range(fill_bar + 1, min(fill_bar + 1 + fwd, n_entry))]
                                oc, tpr = G.check_outcome("SELL", ep, sl, t1, t2, t3, future) if future else ("EXPIRED", 0)
                            g1, gs, n1, n2, n3, ns, rr = _econ_nets("SELL", ep, sl, t1, t2, t3, oc, rt)
                            ts = datetime.fromtimestamp(c_entry["times"][fill_bar] / 1000, timezone.utc)
                            d = _sig_dict(token, "SELL", ep, ts, g1, gs, n1, n2, n3, ns, oc, tpr, rr, fill_bar)
                            d["floored"] = floored
                            fib_sigs.append(d); pair["fib"] = (oc, rr)
        pairs.append(pair)
    return cur_sigs, fib_sigs, pairs


# ── Run both TF configs ──────────────────────────────────────────────────────
RES = {}; PAIRS = {}; FLOOR = {}
for cfg in CFGS:
    cid = cfg["id"]
    cur_all, fib_all, pair_all, cache = [], [], [], {}
    for tok in G.TOKENS:
        c, f, p = run_paired(tok, cfg)
        cur_all += c; fib_all += f; pair_all += p
        cache[tok] = G.load_cached(tok, cfg["entry_tf"])
    floored_n = sum(1 for s in fib_all if s.get("floored"))
    cur_fric = G.apply_friction(cur_all, cfg, cache, derive_seed, simulate_execution)
    fib_fric = G.apply_friction(fib_all, cfg, cache, derive_seed, simulate_execution)
    RES[(cid, "V_CURRENT")] = metrics(cur_fric)
    RES[(cid, "V_FIB")] = metrics(fib_fric)
    RES[(cid, "V_CURRENT")]["_fric"] = cur_fric
    RES[(cid, "V_FIB")]["_fric"] = fib_fric
    PAIRS[cid] = pair_all
    FLOOR[cid] = (floored_n, len(fib_all))
    print(f"[done] {cid}: detected_setups={len(pair_all)} "
          f"V_CURRENT n={len(cur_fric)} avg={RES[(cid,'V_CURRENT')].get('avg',0):+.4f} | "
          f"V_FIB n={len(fib_fric)} avg={RES[(cid,'V_FIB')].get('avg',0):+.4f}")

# ── Report ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 100)
print("FIB-PULLBACK ENTRY TEST — V_CURRENT (market mss+1) vs V_FIB (0.5-0.618 pullback limit)")
print("720d, Config 14, friction, post-TP2=V_ENTRY(hold_entry)")
print("=" * 100)

for cfg in CFGS:
    cid = cfg["id"]
    vc = RES[(cid, "V_CURRENT")]; vf = RES[(cid, "V_FIB")]
    pr = PAIRS[cid]
    n_det = len(pr)
    n_pull = sum(1 for p in pr if p["fib"] is not None)
    skip = Counter(p["fib_skip"] for p in pr if p["fib_skip"] is not None)
    floored_n, fib_pre_fric = FLOOR[cid]

    # DSR for 2-variant comparison
    sr_std = statistics.pstdev([vc.get("sharpe", 0), vf.get("sharpe", 0)])
    for v in (vc, vf):
        if v.get("n", 0) > 0:
            v["dsr2"] = (deflated_sharpe_ratio(v["sharpe"], v["n"], 2, sr_std,
                                               skew=v["skew"], kurtosis=v["kurt"])
                         if sr_std > 0 else 1.0)
        else:
            v["dsr2"] = 0.0

    print(f"\n### {cid}  ({cfg['label']})")
    print(f"  detected setups: {n_det}")
    print(f"  saw a 0.5-0.618 pullback & traded (V_FIB): {n_pull} "
          f"({100*n_pull/n_det:.1f}% of detected)")
    print(f"  V_FIB skips: {dict(skip)}  "
          f"(no_pullback = breakout never retraced into the zone within {PULLBACK_WINDOW} bars)")
    print(f"  MIN_SL_PCT floor widened SL past 0.618 anchor: {floored_n}/{fib_pre_fric} fib setups "
          f"(shield erosion rate {100*floored_n/fib_pre_fric:.1f}%)" if fib_pre_fric else "  (no fib setups)")
    print(f"  {'variant':<11}{'n':>5}{'avg_R':>9}{'WR%':>7}{'PF':>7}{'maxDD':>8}{'sum_R':>9}"
          f"{'avgWin':>8}{'avgLoss':>9}{'train':>8}{'test':>8}{'DSR2':>7}")
    for nm, v in (("V_CURRENT", vc), ("V_FIB", vf)):
        if v.get("n", 0) == 0:
            print(f"  {nm:<11}{0:>5}  (no signals)"); continue
        print(f"  {nm:<11}{v['n']:>5}{v['avg']:>+9.4f}{v['wr']*100:>6.1f}%{v['pf']:>7.2f}"
              f"{v['mdd']:>8.1f}{v['sum']:>+9.1f}{v['avg_win']:>+8.3f}{v['avg_loss']:>+9.3f}"
              f"{v['train']:>+8.4f}{v['test']:>+8.4f}{v['dsr2']:>7.3f}")
    if vc.get("n") and vf.get("n"):
        print(f"  delta V_FIB - V_CURRENT: avg_R {vf['avg']-vc['avg']:+.4f}  "
              f"test {vf['test']-vc['test']:+.4f}  WR {100*(vf['wr']-vc['wr']):+.1f}pp")
        print(f"  outcome mix V_CURRENT: {dict(vc['oc'])}")
        print(f"  outcome mix V_FIB    : {dict(vf['oc'])}")
        print("  per-regime avg_R (V_CURRENT -> V_FIB):")
        for rg in sorted(set(list(vc['regime']) + list(vf['regime']))):
            a = vc['regime'].get(rg, (0, 0)); b = vf['regime'].get(rg, (0, 0))
            print(f"     {rg:<8} {a[0]:+.3f}(n{a[1]}) -> {b[0]:+.3f}(n{b[1]})")

    # ── SHIELD ANALYSIS: of V_CURRENT FULL_SL losses, what did V_FIB do? ─────
    cur_losses = [p for p in pr if p["cur"] is not None and p["cur"][0] == "LOSS"]
    avoided = sum(1 for p in cur_losses if p["fib"] is None)         # never pulled back / not taken
    took_lost = sum(1 for p in cur_losses if p["fib"] is not None and p["fib"][0] == "LOSS")
    took_saved = sum(1 for p in cur_losses if p["fib"] is not None and p["fib"][0] != "LOSS")
    nL = len(cur_losses)
    print(f"  SHIELD: V_CURRENT FULL_SL losses = {nL}")
    if nL:
        print(f"     V_FIB AVOIDED (no trade)        : {avoided}/{nL} ({100*avoided/nL:.1f}%)")
        print(f"     V_FIB took & STILL lost (SL hit): {took_lost}/{nL} ({100*took_lost/nL:.1f}%)")
        print(f"     V_FIB took & SAVED (not a loss) : {took_saved}/{nL} ({100*took_saved/nL:.1f}%)")
    # Also: of V_CURRENT WINS, how many did V_FIB skip (entry-timing cost)?
    cur_wins = [p for p in pr if p["cur"] is not None and p["cur"][1] > 0]
    win_skipped = sum(1 for p in cur_wins if p["fib"] is None)
    print(f"  WIN-SKIP COST: V_CURRENT positive-R trades = {len(cur_wins)}; "
          f"V_FIB skipped {win_skipped} of them ({100*win_skipped/len(cur_wins):.1f}%)"
          if cur_wins else "  (no V_CURRENT wins)")

    # ── Stop-size confound: median risk % (V_FIB tiny fib-zone -> 0.5% floor) ─
    def _med(xs):
        xs = sorted(xs); return xs[len(xs) // 2] if xs else 0.0
    cur_risk = [abs(s["net_sl_pct"]) for s in vc["_fric"]]
    fib_risk = [abs(s["net_sl_pct"]) for s in vf["_fric"]]
    print(f"  STOP SIZE (median |net_sl| %): V_CURRENT={_med(cur_risk):.3f}%  "
          f"V_FIB={_med(fib_risk):.3f}%   (V_FIB hugs the {100*MIN_SL_PCT:.1f}% MIN_SL floor)")

    # ── Per-token concentration of V_FIB (robustness / is it a few tokens?) ──
    by_tok = defaultdict(list)
    for s in vf["_fric"]:
        by_tok[s["token"]].append(s["realized_r"])
    print("  V_FIB per-token avg_R (robustness):")
    line = "     " + "  ".join(f"{t}:{sum(v)/len(v):+.2f}(n{len(v)})"
                               for t, v in sorted(by_tok.items(), key=lambda x: -sum(x[1]) / len(x[1])))
    print(line)
    pos_tok = sum(1 for t, v in by_tok.items() if sum(v) / len(v) > 0.40)
    print(f"     tokens with V_FIB avg_R > +0.40: {pos_tok}/{len(by_tok)}")

print("\nDone. (in-memory only; no DB writes)")
