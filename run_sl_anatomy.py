"""run_sl_anatomy.py — DESCRIPTIVE anatomy of FULL_SL losses (read-only, in-memory).

PHASE C-BREAKOUT. 720d, Config 14 LOCKED_KNOBS, friction, post-TP2 = V_ENTRY
(hold_entry, live model), TF_A (5M/4H) + TF_B (5M/1H). NO code/SL/entry change,
NO DB writes, NO filter. Pure observation of WHY stops are hit.

For every FULL_SL loss (matching G.check_outcome under the live model) it records,
CAUSALLY (forward bars only, no look-ahead beyond what the trade itself sees):
  1. bars_to_sl  — bars after entry until the SL was hit (immediate/fast/slow).
  2. mfe_frac    — max favorable move toward TP1 BEFORE the stop, as a fraction of
                   the entry->TP1 distance (REVERSED / SHALLOW / NEAR-MISS / EXTREME).
  3. counterfactual "no-SL" recovery — ignoring the SL, did price later reach TP1
     within the 48h window? and how much WIDER (in R) would the SL have needed to be
     to survive the deepest dip before that TP1 touch? (the "tight SL" question).
Segmentation axis ">1.5" = operator's vol_ratio (volume[MSS bar] / mean prior-20 5m
bars), HIGH bucket >1.5 — same causal definition as VOLUME_BREAKDOWN.md.

IMPORTANT FRAMING (carried from FIB_PULLBACK_ENTRY_TEST.md): later entry / structural
SL placement does NOT create expectancy in these random-walk tokens — it redistributes
WR-vs-R. So this anatomy is for UNDERSTANDING the loss structure only; a near-miss-heavy
result does NOT imply a profitable entry/SL fix exists. NO fix is proposed.
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


def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


WIN = {"start": ms(2024, 6, 10), "end": ms(2026, 5, 31),
       "dir": _BD / "data" / "ohlcv_cache_720d", "suf": "720d"}
G.START_MS = WIN["start"]; G.END_MS = WIN["end"]
VOL_DIR = _BD / "data" / "vol_cache_720d"
N_LB = 20


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
os.environ.update(G.LOCKED_KNOBS)
import breakout_engine as _be
importlib.reload(_be)
detect = _be.detect_h4_breakout
compute_sl_tp = _be.compute_breakout_sl_tp
CFGS = [c for c in G.TF_CONFIGS if c["id"] in ("A_5m_4h", "B_5m_1h")]

VOL = {}


def get_vol(tok):
    if tok not in VOL:
        fp = VOL_DIR / f"{tok}USDT_vol.json"
        VOL[tok] = (json.load(open(fp)) if fp.exists() else None)
        if VOL[tok] is not None:
            d = VOL[tok]; VOL[tok] = (d["times"], d["vols"])
    return VOL[tok]


def vol_ratio(tok, entry_ts_ms):
    m = get_vol(tok)
    if m is None:
        return None
    times, vols = m
    mss_ms = entry_ts_ms - 300000
    i = bisect.bisect_left(times, mss_ms)
    if i >= len(times) or times[i] != mss_ms or i < N_LB:
        return None
    prior = vols[i - N_LB:i]
    avg = sum(prior) / len(prior)
    return vols[i] / avg if avg > 0 else None


# ── Loss anatomy on a single trade (forward bars are the entry-TF highs/lows) ─
def loss_anatomy(direction, entry, sl, tp1, highs, lows, e0, e_last):
    """e0 = first forward bar idx (entry_bar+1); e_last = exclusive end.
    Returns dict or None if not a FULL_SL loss (tp1 reached first / never stopped).
    """
    risk = abs(entry - sl)
    tp1_dist = abs(tp1 - entry)
    if risk <= 0 or tp1_dist <= 0:
        return None
    sl_bar = -1                      # bars after entry (1-based) when SL hit
    mfe_before = 0.0                 # best favorable price-excursion before the stop bar
    run_extreme = entry             # running favorable extreme (high for BUY / low for SELL)
    for k, j in enumerate(range(e0, e_last), start=1):
        h, l = highs[j], lows[j]
        if direction == "BUY":
            # SL checked first intrabar (pessimistic, matches G.check_outcome)
            if l <= sl:
                sl_bar = k; break
            if h >= tp1:
                return None          # reached TP1 first -> not a FULL_SL loss
            run_extreme = max(run_extreme, h)
        else:
            if h >= sl:
                sl_bar = k; break
            if l <= tp1:
                return None
            run_extreme = min(run_extreme, l)
    if sl_bar < 0:
        return None                  # never stopped in window -> not a FULL_SL loss
    # MFE before the stop bar (strictly prior bars' favorable extreme)
    if direction == "BUY":
        mfe_before = max(0.0, run_extreme - entry)
    else:
        mfe_before = max(0.0, entry - run_extreme)
    mfe_frac = mfe_before / tp1_dist   # in [0,1) since TP1 never reached

    # ── Counterfactual: ignore the SL, walk the FULL window. Did price reach TP1?
    # required wider-SL distance (in R) = deepest adverse before the TP1 touch.
    recovered = False
    widen_R = None                    # how many R the SL needed to be to survive to TP1
    deepest_full_R = 0.0              # deepest adverse over full window (in R)
    adverse_extreme = entry
    for j in range(e0, e_last):
        h, l = highs[j], lows[j]
        if direction == "BUY":
            adverse_extreme = min(adverse_extreme, l)
            deepest_full_R = max(deepest_full_R, (entry - adverse_extreme) / risk)
            if h >= tp1:
                recovered = True
                widen_R = (entry - adverse_extreme) / risk   # dip seen up to the TP1 touch
                break
        else:
            adverse_extreme = max(adverse_extreme, h)
            deepest_full_R = max(deepest_full_R, (adverse_extreme - entry) / risk)
            if l <= tp1:
                recovered = True
                widen_R = (adverse_extreme - entry) / risk
                break
    if not recovered:
        # complete the deepest-adverse scan over the whole window
        for j in range(e0, e_last):
            if direction == "BUY":
                adverse_extreme = min(adverse_extreme, lows[j])
            else:
                adverse_extreme = max(adverse_extreme, highs[j])
        deepest_full_R = ((entry - adverse_extreme) / risk if direction == "BUY"
                          else (adverse_extreme - entry) / risk)
    return {"bars_to_sl": sl_bar, "mfe_frac": mfe_frac,
            "recovered": recovered, "widen_R": widen_R,
            "deepest_full_R": deepest_full_R}


# ── Per-token V_CURRENT pass, capturing loss anatomy on the clean signal set ──
def run_token(token, cfg):
    c_entry = G.load_cached(token, cfg["entry_tf"])
    c_ref = G.load_cached(token, cfg["ref_tf"])
    if c_entry is None or c_ref is None:
        return []
    n_entry = len(c_entry["closes"]); n_ref = len(c_ref["closes"])
    fwd = G.FORWARD_MINUTES // (cfg["entry_bar_duration_ms"] // 60_000)
    if n_entry < fwd + 100 or n_ref < 20:
        return []
    rt = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
    he = c_entry["highs"]; le = c_entry["lows"]; oe = c_entry["opens"]
    ref_window = 4 + G.H4_WINDOW_BUFFER
    ref_dur = cfg["ref_bar_duration_ms"]
    sigs = []; consumed = set()
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
        if mss_abs >= n_entry - fwd - 1:
            continue
        e_bar = mss_abs + 1
        if e_bar >= n_entry - fwd - 1:
            continue
        ep = oe[e_bar]; direction = setup["direction"]
        st = compute_sl_tp(direction, ep, setup["sl_anchor"], setup["c1_high"], setup["c1_low"])
        if st is None:
            continue
        sl, t1, t2, t3 = st
        if compute_econ(direction, ep, sl, t1, t2, t3, None, rt) is None:
            continue
        future = [{"h": he[j], "l": le[j]} for j in range(e_bar + 1, min(e_bar + 1 + fwd, n_entry))]
        if not future:
            continue
        outcome, _ = G.check_outcome(direction, ep, sl, t1, t2, t3, future)
        # gross %s for friction recompute (mirror run_one_token)
        if direction == "BUY":
            g1 = (t1 - ep) / ep * 100; gs = (sl - ep) / ep * 100
        else:
            g1 = (ep - t1) / ep * 100; gs = (ep - sl) / ep * 100
        ts = datetime.fromtimestamp(c_entry["times"][e_bar] / 1000, timezone.utc)
        rec = {
            "token": token, "signal": direction, "price": round(ep, 8),
            "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "tp1_pct": round(g1, 3), "sl_pct": round(gs, 3),
            "net_tp1_pct": round(g1 - rt, 3), "net_tp2_pct": round(g1 - rt, 3),
            "net_tp3_pct": round(g1 - rt, 3), "net_sl_pct": round(gs - rt, 2),
            "rr1": round(abs(g1 / gs), 2) if gs else 0,
            "outcome": outcome, "realized_r": 0.0,
            "hour_utc": ts.hour, "day_of_week": ts.weekday(),
            "entry_bar_idx": e_bar,
            "vol_ratio": vol_ratio(token, c_entry["times"][e_bar]),
        }
        if outcome == "LOSS":
            anat = loss_anatomy(direction, ep, sl, t1, he, le, e_bar + 1,
                                min(e_bar + 1 + fwd, n_entry))
            rec["anat"] = anat
        sigs.append(rec)
    return sigs


# ── Run + friction (so the loss set matches the live soak's surviving trades) ─
def bucket_timing(b):
    return "immediate(1-3)" if b <= 3 else "fast(4-12)" if b <= 12 else "slow(13+)"


def bucket_mfe(f):
    return ("REVERSED(<10%)" if f < 0.10 else "SHALLOW(10-50%)" if f < 0.50
            else "NEAR-MISS(50-90%)" if f < 0.90 else "EXTREME-NEAR-MISS(90-100%)")


TIMING_ORDER = ["immediate(1-3)", "fast(4-12)", "slow(13+)"]
MFE_ORDER = ["REVERSED(<10%)", "SHALLOW(10-50%)", "NEAR-MISS(50-90%)", "EXTREME-NEAR-MISS(90-100%)"]


def pct(x, n):
    return f"{100*x/n:.1f}%" if n else "—"


def med(xs):
    xs = sorted(xs); return xs[len(xs) // 2] if xs else 0.0


print("=" * 96)
print("SL ANATOMY — FULL_SL loss structure (720d, Config 14, friction, post-TP2=V_ENTRY)")
print("Segmentation '>1.5' = vol_ratio HIGH (volume[MSS]/mean prior-20 5m bars) per VOLUME_BREAKDOWN.md")
print("=" * 96)

for cfg in CFGS:
    cid = cfg["id"]
    clean = []; cache = {}
    for tok in G.TOKENS:
        clean += run_token(tok, cfg)
        cache[tok] = G.load_cached(tok, cfg["entry_tf"])
    fric = G.apply_friction(clean, cfg, cache, derive_seed, simulate_execution)
    losses = [s for s in fric if s["outcome"] == "LOSS" and s.get("anat")]
    n_all = len(fric); n_loss = len(losses)
    print(f"\n{'='*96}\n### {cid}  ({cfg['label']})")
    print(f"  total signals (friction): {n_all} | FULL_SL losses: {n_loss} "
          f"({pct(n_loss, n_all)} of all signals)")
    if not losses:
        continue

    # 1. TIMING
    tcnt = Counter(bucket_timing(s["anat"]["bars_to_sl"]) for s in losses)
    print("\n  [1] STOP-OUT TIMING (bars after entry until SL hit):")
    for b in TIMING_ORDER:
        print(f"      {b:<16} {tcnt.get(b,0):>5}  ({pct(tcnt.get(b,0), n_loss)})")
    print(f"      median bars_to_sl = {med([s['anat']['bars_to_sl'] for s in losses])}")

    # 2. MFE toward TP1 before the stop
    mcnt = Counter(bucket_mfe(s["anat"]["mfe_frac"]) for s in losses)
    print("\n  [2] MAX FAVORABLE EXCURSION toward TP1 before the stop (reverse vs pullback):")
    for b in MFE_ORDER:
        print(f"      {b:<26} {mcnt.get(b,0):>5}  ({pct(mcnt.get(b,0), n_loss)})")
    print(f"      median mfe_frac = {med([s['anat']['mfe_frac'] for s in losses]):.3f}  "
          f"(0 = pure reversal, 1 = tagged TP1)")
    rev = mcnt['REVERSED(<10%)']
    nearish = mcnt['NEAR-MISS(50-90%)'] + mcnt['EXTREME-NEAR-MISS(90-100%)']
    print(f"      => REVERSED share = {pct(rev, n_loss)} | NEAR-MISS+ share = {pct(nearish, n_loss)}")

    # 3a. EARLY-ENTRY (cross-ref fib test) + 3b. TIGHT-SL counterfactual
    near = [s for s in losses if s["anat"]["mfe_frac"] >= 0.50]
    recov = [s for s in near if s["anat"]["recovered"]]
    print("\n  [3] TWO HYPOTHESES (descriptive; both already shown random-walk-neutral by fib test):")
    print(f"      near-miss losses (mfe>=50%): {len(near)}  ({pct(len(near), n_loss)} of losses)")
    print(f"      [3a EARLY ENTRY] cross-ref FIB_PULLBACK_ENTRY_TEST.md: later/pullback entry "
          f"redistributes WR-vs-R, no expectancy gain on primary TF. Not re-built here.")
    print(f"      [3b TIGHT SL] of near-miss losses, price LATER reached TP1 (no-SL counterfactual): "
          f"{len(recov)}/{len(near)} ({pct(len(recov), len(near))})")
    if recov:
        wr = sorted(s["anat"]["widen_R"] for s in recov)
        print(f"          required SL widening to survive to TP1: median {med(wr):.2f}R, "
              f"p75 {wr[int(len(wr)*0.75)]:.2f}R, p90 {wr[int(len(wr)*0.90)]:.2f}R  "
              f"(actual SL = 1.00R)")
        print(f"          FLAG: widening SL to k·R lowers R-per-trade ~1/k (WR-vs-R tradeoff) "
              f"=> a wider SL 'saving' these does NOT raise expectancy.")
    allwide = sorted(s["anat"]["deepest_full_R"] for s in losses)
    print(f"      deepest adverse excursion over full 48h window (all losses): "
          f"median {med(allwide):.2f}R, p90 {allwide[int(len(allwide)*0.90)]:.2f}R "
          f"(how far beyond the 1R stop price ran)")

    # 4. SEGMENT by vol_ratio >1.5
    known = [s for s in losses if s.get("vol_ratio") is not None]
    hi = [s for s in known if s["vol_ratio"] > 1.5]
    lo = [s for s in known if s["vol_ratio"] <= 1.5]
    print(f"\n  [4] SEGMENT by vol_ratio (>1.5 HIGH vs <=1.5):  vol-known losses {len(known)}/{n_loss}")
    for label, grp in (("HIGH vol >1.5", hi), ("NORMAL/LOW <=1.5", lo)):
        if not grp:
            continue
        ng = len(grp)
        revg = sum(1 for s in grp if s["anat"]["mfe_frac"] < 0.10)
        neag = sum(1 for s in grp if s["anat"]["mfe_frac"] >= 0.50)
        immg = sum(1 for s in grp if s["anat"]["bars_to_sl"] <= 3)
        print(f"      {label:<18} n={ng:<5} REVERSED={pct(revg,ng):<7} "
              f"NEAR-MISS+={pct(neag,ng):<7} immediate={pct(immg,ng):<7} "
              f"med_mfe={med([s['anat']['mfe_frac'] for s in grp]):.3f}")

print("\nDone. (read-only; no DB writes, no code/SL/entry change)")
