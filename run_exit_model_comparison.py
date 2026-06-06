"""run_exit_model_comparison.py — V_ENTRY (live scaled) vs V_FULLTP2 (proposed).

PHASE C-BREAKOUT exit-model comparison. Backtest-only. In-memory; NO DB writes.
Soaks A/B + fade + signals.db + main untouched.

Both models run on the SAME detected setups, SAME entry (mss_abs+1 open), SAME
SL/TP1/TP2/TP3 levels, and the SAME execution fill (one simulate_execution roll
per setup → identical fill_price / fill_size / total_cost_pct for both). ONLY the
forward-walk classification and the realized-R formula differ:

  V_ENTRY   : G.check_outcome (hold_entry) + G._calc_realized_r  — 50/50 split,
              TP1 partial + runner, BE-after-TP1, post-TP2 hold-at-entry.
  V_FULLTP2 : G.check_outcome_fulltp2 + G._calc_realized_r_fulltp2 — full position,
              single target TP2, BE-after-TP1, no TP3/runner.

Config 14 knobs, friction ON, 720d (2024-06-10 → 2026-05-31). TF_A = 5M/4H
(soak A), TF_B = 5M/1H (soak B = primary).
"""
import os, sys, json, bisect, importlib, statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_BD = Path(__file__).resolve().parent
sys.path.insert(0, str(_BD)); sys.path.insert(0, "/home/tradeai/TradeAI")

import run_tf_grid as G
from crt_engine import compute_crt_trade_economics as compute_econ
from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT
from execution import simulate_execution, derive_seed
from validation import sharpe_ratio, deflated_sharpe_ratio, _moments


def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


WIN720 = {"start": ms(2024, 6, 10), "end": ms(2026, 5, 31)}
CACHE720 = _BD / "data" / "ohlcv_cache_720d"
DUR = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000}

os.environ.update(G.LOCKED_KNOBS)
import breakout_engine as _be
importlib.reload(_be)
detect = _be.detect_h4_breakout
compute_sl_tp = _be.compute_breakout_sl_tp


# ── 720d loader (5m/1h/4h are native in the 720d cache) ──────────────────────
def load_720(tok, tf):
    p = CACHE720 / f"{tok}USDT_{tf}_720d.json"
    if not p.exists():
        return None
    inner = (json.load(open(p)) or {}).get("data")
    if not inner:
        return None
    t = inner["times"]
    i0 = bisect.bisect_left(t, WIN720["start"]); i1 = bisect.bisect_right(t, WIN720["end"])
    if i1 - i0 < 30:
        return None
    return {k: inner[k][i0:i1] for k in ("opens", "highs", "lows", "closes")} | {"times": t[i0:i1]}


# ── BTC-4h-SMA30 regime map over 720d ────────────────────────────────────────
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
    """sigs: list of dicts each carrying realized_r, ts, token, outcome, fee_paid_R."""
    rs = [s["realized_r"] for s in sigs]; n = len(rs)
    if n == 0:
        return {"n": 0}
    pos = sum(1 for r in rs if r > 0)
    wins = [r for r in rs if r > 0]; loss = [r for r in rs if r < 0]
    gp = sum(wins); gl = sum(-r for r in loss)
    ss = sorted(sigs, key=lambda s: s["ts"]); cut = int(len(ss) * 0.7)
    tr = [s["realized_r"] for s in ss[:cut]]; te = [s["realized_r"] for s in ss[cut:]]
    mm = _moments(rs)
    reg = defaultdict(list); bt = defaultdict(list); oc = defaultdict(int)
    oc_sumr = defaultdict(float)
    for s in sigs:
        reg[REGIME.get(s["ts"][:10], "RANGE")].append(s["realized_r"])
        bt[s["token"]].append(s["realized_r"])
        oc[s["outcome"]] += 1
        oc_sumr[s["outcome"]] += s["realized_r"]
    return {"n": n, "wr": pos / n, "avg": sum(rs) / n, "sum": sum(rs),
            "pf": (gp / gl) if gl > 0 else float("inf"),
            "mdd": maxdd([s["realized_r"] for s in ss]),
            "train": sum(tr) / len(tr) if tr else 0, "test": sum(te) / len(te) if te else 0,
            "sharpe": sharpe_ratio(rs, 1.0), "skew": mm[2], "kurt": mm[3],
            "fee_R": sum(s["fee_paid_R"] for s in sigs),
            "regime": {k: (sum(v) / len(v), len(v)) for k, v in reg.items()},
            "by_tok": {k: (sum(v) / len(v), len(v)) for k, v in bt.items()},
            "outcomes": dict(oc),
            "outcome_sumr": {k: (oc_sumr[k], oc[k], oc_sumr[k]/oc[k] if oc[k] else 0) for k in oc}}


def _nets(direction, entry, sl, t1, t2, t3, rt):
    if direction == "BUY":
        g1 = (t1 - entry) / entry * 100; g2 = (t2 - entry) / entry * 100
        g3 = (t3 - entry) / entry * 100; gs = (sl - entry) / entry * 100
    else:
        g1 = (entry - t1) / entry * 100; g2 = (entry - t2) / entry * 100
        g3 = (entry - t3) / entry * 100; gs = (entry - sl) / entry * 100
    n1 = round(g1 - rt, 3); n2 = round(g2 - rt, 3); n3 = round(g3 - rt, 3); ns = round(gs - rt, 2)
    return g1, g2, g3, gs, n1, n2, n3, ns


# Per-side exit fee for the "honest extra-exit-fee" sensitivity (real-world model).
# total_cost_pct is round-trip; one EXIT side ≈ total_cost_pct/2. V_ENTRY's second
# partial exit acts on HALF the position, so the fee V_FULLTP2 SAVES per TP1-touched
# signal ≈ 0.5 * (total_cost_pct/2) = total_cost_pct/4 (in price-% of full notional).
def extra_exit_fee_R(ventry_outcome, total_cost_pct, risk):
    two_leg = ventry_outcome in ("PARTIAL_TP1", "PARTIAL_TP2", "PARTIAL_TP2_BE", "WIN")
    if not two_leg:
        return 0.0
    return (total_cost_pct / 4.0) / risk if risk else 0.0


def run_paired(token, cfg):
    """Return parallel lists (same length, same setups) of V_ENTRY + V_FULLTP2
    signal dicts, post-friction. None entries dropped consistently from both."""
    c_entry = load_720(token, cfg["entry_tf"]); c_ref = load_720(token, cfg["ref_tf"])
    if c_entry is None or c_ref is None:
        return [], [], {"detected": 0, "gated": 0, "rejected": 0}
    n_entry = len(c_entry["closes"]); n_ref = len(c_ref["closes"])
    fwd = G.FORWARD_MINUTES // (cfg["entry_bar_duration_ms"] // 60_000)
    if n_entry < fwd + 100 or n_ref < 20:
        return [], [], {"detected": 0, "gated": 0, "rejected": 0}
    rt = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
    he = c_entry["highs"]; le = c_entry["lows"]; oe = c_entry["opens"]; ce = c_entry["closes"]
    ref_window = 4 + G.H4_WINDOW_BUFFER; ref_dur = cfg["ref_bar_duration_ms"]
    ven, vf2 = [], []
    consumed = set(); det = gated = rej = 0
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
        det += 1
        mss_abs = e_start + setup["mss_bar_5m"]
        if mss_abs >= n_entry - fwd - 1:
            continue
        e_bar = mss_abs + 1
        if e_bar >= n_entry - fwd - 1:
            continue
        direction = setup["direction"]; ep = oe[e_bar]
        st = compute_sl_tp(direction, ep, setup["sl_anchor"], setup["c1_high"], setup["c1_low"])
        if st is None:
            continue
        sl, t1, t2, t3 = st
        if compute_econ(direction, ep, sl, t1, t2, t3, None, rt) is None:
            continue
        gated += 1
        fut = [{"h": he[j], "l": le[j]} for j in range(e_bar + 1, min(e_bar + 1 + fwd, n_entry))]
        if not fut:
            continue

        # ── identical execution fill for BOTH models ──
        mss_bar = e_bar - 1
        atr = G._atr_n(he, le, ce, mss_bar, 14)
        if atr <= 0:
            continue
        long_atr = G._atr_n(he, le, ce, max(0, mss_bar - 50), 14)
        atr_ratio = (atr / long_atr) if long_atr > 0 else 1.0
        ts_dt = datetime.fromtimestamp(c_entry["times"][e_bar] / 1000, timezone.utc)
        seed = derive_seed(ts_dt, token, direction)
        try:
            res = simulate_execution(signal_ts=ts_dt, signal_price=ce[mss_bar],
                                     next_bar_open=ep, token=token, direction=direction,
                                     regime="UNKNOWN", atr_5m=atr, atr_ratio=atr_ratio, seed=seed)
        except Exception:
            continue
        if res.status == "REJECTED":
            rej += 1
            continue
        actual_entry = res.fill_price; fill_size = res.fill_size_pct
        tcost = res.total_cost_pct * 100  # → %
        ratio = (ep / actual_entry) if direction == "BUY" else (actual_entry / ep)
        if ratio <= 0:
            ratio = 1.0

        # gross levels rescaled by fill ratio (mirror apply_friction approximation)
        g1, g2, g3, gs, *_ = _nets(direction, ep, sl, t1, t2, t3, rt)
        g1 *= ratio; g2 *= ratio; g3 *= ratio; gs *= ratio
        n1 = round(g1 - tcost, 3); n2 = round(g2 - tcost, 3)
        n3 = round(g3 - tcost, 3); ns = round(gs - tcost, 2)
        risk = abs(ns) or 0.0001

        # ── V_ENTRY ──
        oc1, _ = G.check_outcome(direction, ep, sl, t1, t2, t3, fut)
        r1 = G._calc_realized_r(oc1, n1, ns, n2, n3, tcost) * fill_size
        fee1 = _fee_paid_R(oc1, n1, n2, n3, ns, g1, g2, g3, gs, risk, "ventry")
        ts_str = ts_dt.strftime("%Y-%m-%d %H:%M:%S")
        ven.append({"token": token, "ts": ts_str, "outcome": oc1, "realized_r": round(r1, 4),
                    "fee_paid_R": fee1, "tcost": tcost, "risk": risk,
                    "extra_exit_fee_R": extra_exit_fee_R(oc1, tcost, risk) * fill_size})

        # ── V_FULLTP2 ──
        oc2, _ = G.check_outcome_fulltp2(direction, ep, sl, t1, t2, t3, fut)
        r2 = G._calc_realized_r_fulltp2(oc2, n2, ns, tcost) * fill_size
        fee2 = _fee_paid_R(oc2, n1, n2, n3, ns, g1, g2, g3, gs, risk, "vfull")
        vf2.append({"token": token, "ts": ts_str, "outcome": oc2, "realized_r": round(r2, 4),
                    "fee_paid_R": fee2, "tcost": tcost, "risk": risk, "extra_exit_fee_R": 0.0})

    return ven, vf2, {"detected": det, "gated": gated, "rejected": rej}


def _fee_paid_R(outcome, n1, n2, n3, ns, g1, g2, g3, gs, risk, model):
    """In-model friction actually paid, in R. In this harness's normalization the
    blended-net formula deducts exactly ONE round-trip cost (tcost) for ANY
    non-expired outcome — the half-weighted legs sum the friction back to a single
    round trip regardless of partial-exit count. So:
        non-expired  → tcost/risk  (one round trip)
        expired/flat → 0
    tcost is reconstructed from the gross-vs-net gap on the SL leg (= tcost)."""
    tcost = abs(gs - ns)  # gross_sl - net_sl == one round-trip cost (%)
    if model == "ventry":
        expired = outcome in ("EXPIRED",)
    else:
        expired = outcome in ("EXPIRED",)  # V_FULLTP2 EXPIRED (never-TP1) is flat
    return 0.0 if expired else round(tcost / risk, 4)


def run_cfg(cfg):
    ven_all, vf2_all, agg = [], [], {"detected": 0, "gated": 0, "rejected": 0}
    for tok in G.TOKENS:
        v, f, st = run_paired(tok, cfg)
        ven_all += v; vf2_all += f
        for k in agg:
            agg[k] += st[k]
    return metrics(ven_all), metrics(vf2_all), agg, ven_all, vf2_all


CFGS = [
    {"id": "TF_A_5m_4h", "entry_tf": "5m", "ref_tf": "4h",
     "ref_bar_duration_ms": DUR["4h"], "entry_bar_duration_ms": DUR["5m"],
     "label": "5M / 4H  (soak A)"},
    {"id": "TF_B_5m_1h", "entry_tf": "5m", "ref_tf": "1h",
     "ref_bar_duration_ms": DUR["1h"], "entry_bar_duration_ms": DUR["5m"],
     "label": "5M / 1H  (soak B = PRIMARY)"},
]


def fmt(m):
    if m.get("n", 0) == 0:
        return "  (no signals)"
    return (f"n={m['n']:>4}  avg_R={m['avg']:+.4f}  WR={m['wr']*100:5.1f}%  PF={m['pf']:.2f}  "
            f"maxDD={m['mdd']:6.1f}  sum_R={m['sum']:+8.2f}  train={m['train']:+.3f}  test={m['test']:+.3f}")


print("=" * 100)
print("EXIT MODEL COMPARISON — V_ENTRY (live scaled) vs V_FULLTP2 (full→TP2, single exit)")
print("Config 14, friction ON, 720d 2024-06-10→2026-05-31, in-memory only")
print("=" * 100)

RESULTS = {}
for cfg in CFGS:
    print(f"\n### {cfg['id']}: {cfg['label']}")
    mv, mf, agg, ven_all, vf2_all = run_cfg(cfg)
    RESULTS[cfg["id"]] = {"ventry": mv, "vfull": mf, "agg": agg,
                          "ven_all": ven_all, "vf2_all": vf2_all}
    print(f"  detected={agg['detected']}  gated={agg['gated']}  exec_rejected={agg['rejected']}")
    print(f"  V_ENTRY  : {fmt(mv)}")
    print(f"  V_FULLTP2: {fmt(mf)}")
    if mv.get("n", 0):
        print(f"  outcomes V_ENTRY : {mv['outcomes']}")
        print(f"  outcomes V_FULLTP2: {mf['outcomes']}")
        print("  per-outcome (count, sum_R, avg_R):")
        for nm, m in (("V_ENTRY", mv), ("V_FULLTP2", mf)):
            parts = [f"{k}:n{c},sumR{sr:+.0f},avg{ar:+.3f}" for k, (sr, c, ar) in
                     sorted(m["outcome_sumr"].items(), key=lambda x: -x[1][0])]
            print(f"      {nm:<10} " + "  ".join(parts))
        # fee accounting
        fee_v = sum(s["fee_paid_R"] for s in ven_all)
        fee_f = sum(s["fee_paid_R"] for s in vf2_all)
        extra = sum(s["extra_exit_fee_R"] for s in ven_all)
        print(f"  in-model friction paid (R): V_ENTRY={fee_v:+.3f}  V_FULLTP2={fee_f:+.3f}  "
              f"delta(V_ENTRY-extra)={fee_v-fee_f:+.4f}")
        print(f"  honest extra-exit-fee V_ENTRY would pay (2nd partial exit), R: {extra:+.4f} "
              f"(= {extra/mv['n']*1000:+.3f} milli-R/signal) — this is the real fee V_FULLTP2 saves")
        # per-regime
        print("  per-regime avg_R:")
        for rg in ("BULL", "BEAR", "RANGE"):
            a1, c1 = mv["regime"].get(rg, (0, 0)); a2, c2 = mf["regime"].get(rg, (0, 0))
            print(f"      {rg:<6} V_ENTRY {a1:+.3f}(n{c1})   V_FULLTP2 {a2:+.3f}(n{c2})")
        # per-token avg_R
        print("  per-token avg_R (V_ENTRY -> V_FULLTP2):")
        toks = sorted(mv["by_tok"].keys())
        cells = []
        for t in toks:
            a1, n1 = mv["by_tok"].get(t, (0, 0)); a2, _ = mf["by_tok"].get(t, (0, 0))
            cells.append(f"{t}:{a1:+.2f}->{a2:+.2f}(n{n1})")
        for i in range(0, len(cells), 4):
            print("      " + "   ".join(cells[i:i+4]))

# DSR deflated for the 2-model comparison (n_trials=2), per TF.
print("\n" + "=" * 100)
print("DSR (deflated for 2-model selection) — per TF")
print("=" * 100)
for cfg in CFGS:
    R = RESULTS[cfg["id"]]
    mv, mf = R["ventry"], R["vfull"]
    if mv.get("n", 0) == 0:
        continue
    sr_std = statistics.pstdev([mv["sharpe"], mf["sharpe"]])
    for name, m in (("V_ENTRY", mv), ("V_FULLTP2", mf)):
        dsr = (deflated_sharpe_ratio(m["sharpe"], m["n"], 2, sr_std,
                                     skew=m["skew"], kurtosis=m["kurt"]) if sr_std > 0 else 1.0)
        print(f"  {cfg['id']:<12} {name:<10} sharpe={m['sharpe']:+.4f}  DSR(2-trial)={dsr:.4f}")

# Persist results json for the report
out = {}
for cid, R in RESULTS.items():
    out[cid] = {"ventry": {k: v for k, v in R["ventry"].items() if k != "by_tok"},
                "vfull": {k: v for k, v in R["vfull"].items() if k != "by_tok"},
                "agg": R["agg"],
                "ventry_by_tok": R["ventry"].get("by_tok", {}),
                "vfull_by_tok": R["vfull"].get("by_tok", {})}
with open(_BD / "data" / "exit_model_comparison_results.json", "w") as f:
    json.dump(out, f, indent=2, default=str)
print("\nWrote data/exit_model_comparison_results.json")
print("Done. (in-memory only; no DB writes)")
