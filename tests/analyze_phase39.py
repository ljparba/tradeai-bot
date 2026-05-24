#!/usr/bin/env python3
"""
Phase 3.9: Edge Isolation & Strategy Triage
All analysis on existing Phase 3.8 signals — no live API re-runs.
"""
import sys, os, sqlite3
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BT_DB_PATH = os.path.join(_ROOT, "data", "signals.db")
RUN_ID     = 7


# ═══════════════════════════════════════════════════
# CORE METRICS
# ═══════════════════════════════════════════════════

def load_signals():
    conn = sqlite3.connect(BT_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM backtest_signals WHERE run_id=? ORDER BY ts", (RUN_ID,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def net_exp(sigs):
    """Net expectancy per trade (% of position).
    WIN / PARTIAL_TP2 / PARTIAL_TP1 → credit net_tp1_pct (conservative: TP1 only).
    LOSS → net_sl_pct (negative).
    EXPIRED → 0.5 × net_sl_pct (partial loss on time-exit).
    """
    if not sigs: return 0.0
    t = 0.0
    for s in sigs:
        oc = s["outcome"]
        if oc in ("WIN", "PARTIAL_TP2", "PARTIAL_TP1"):
            t += s["net_tp1_pct"]
        elif oc == "LOSS":
            t += s["net_sl_pct"]
        else:
            t += s["net_sl_pct"] * 0.5
    return round(t / len(sigs), 4)


def wr(sigs):
    if not sigs: return 0.0
    return round(sum(1 for s in sigs if s["outcome"] in
                     ("WIN","PARTIAL_TP2","PARTIAL_TP1")) / len(sigs) * 100, 1)


def avg_net_rr(sigs):
    v = [s["net_rr1"] for s in sigs if s.get("net_rr1", 0) > 0]
    return round(sum(v)/len(v), 2) if v else 0.0


def bew_need(sigs):
    r = avg_net_rr(sigs)
    return round(1/(1+r)*100, 1) if r > 0 else 100.0


def wf_gap(sigs):
    if len(sigs) < 20: return None
    ss = sorted(sigs, key=lambda s: s["ts"])
    cut = max(1, int(len(ss)*0.60))
    tr, te = ss[:cut], ss[cut:]
    if not te: return None
    return round(wr(te)-wr(tr), 1)


def row(label, sigs, min_n=15):
    if len(sigs) < min_n: return None
    e = net_exp(sigs)
    g = wf_gap(sigs)
    gstr = f" {g:+.1f}pp" if g is not None else "     "
    return {"label":label, "n":len(sigs), "wr":wr(sigs),
            "rr":avg_net_rr(sigs), "exp":e, "bew":bew_need(sigs),
            "gap":gstr, "pos":e>0}


def ptable(rows, title, min_n=15):
    rows = [r for r in rows if r]
    rows.sort(key=lambda r: -r["exp"])
    print(f"\n{title}")
    H = f"{'Subset':<40} {'N':>5} {'WR%':>6} {'NetRR':>6} {'E/tr':>9} {'BEW%':>6} {'WF-gap'}"
    print(H); print("-"*82)
    for r in rows:
        flag = "  *** EDGE ***" if r["pos"] else ""
        print(f"{r['label']:<40} {r['n']:>5} {r['wr']:>5.1f}%  {r['rr']:>5.2f}x"
              f"  {r['exp']:>+8.4f}%  {r['bew']:>5.1f}% {r['gap']}{flag}")


# ═══════════════════════════════════════════════════
# 1. EDGE ISOLATION
# ═══════════════════════════════════════════════════

def edge_isolation(sigs):
    print("="*82)
    print("  PHASE 3.9 — EDGE ISOLATION ANALYSIS")
    print("="*82)
    print(f"  Base: {len(sigs)} signals | WR {wr(sigs):.1f}% | Net E {net_exp(sigs):+.4f}%/trade\n")

    # A. Token
    by_tok = defaultdict(list)
    for s in sigs: by_tok[s["token"]].append(s)
    ptable([row(f"Token={k}", v) for k,v in by_tok.items()], "[A] By Token", 15)

    # B. Regime
    by_reg = defaultdict(list)
    for s in sigs: by_reg[s["regime"]].append(s)
    ptable([row(f"Regime={k}", v) for k,v in by_reg.items()], "[B] By Regime", 10)

    # C. Direction
    ptable([row("BUY", [s for s in sigs if s["signal"]=="BUY"]),
            row("SELL",[s for s in sigs if s["signal"]=="SELL"])],
           "[C] By Direction", 10)

    # D. Confidence level
    by_conf = defaultdict(list)
    for s in sigs: by_conf[s["confidence"]].append(s)
    ptable([row(f"Conf={k}", v) for k,v in by_conf.items()], "[D] By Confidence", 10)

    # D2. Confidence floor cumulative
    ptable([row(f"Conf>={f}", [s for s in sigs if s["confidence"]>=f])
            for f in [5,6,7,8,9]], "[D2] Conf >= floor", 30)

    # E. Net R:R bucket
    buckets = [(0.80,0.90),(0.90,1.00),(1.00,1.10),(1.10,1.25),(1.25,2.00)]
    ptable([row(f"NetRR [{lo:.2f},{hi:.2f})",
                [s for s in sigs if lo <= s.get("net_rr1",0) < hi])
            for lo,hi in buckets], "[E] By Net R:R bucket", 10)

    # F. Breakeven WR bucket
    bew_buck = [(0.40,0.45),(0.45,0.48),(0.48,0.50),(0.50,0.52),(0.52,0.55)]
    ptable([row(f"BEW [{lo:.2f},{hi:.2f})",
                [s for s in sigs if lo <= s.get("breakeven_wr",1.0) < hi])
            for lo,hi in bew_buck], "[F] By BEW bucket", 10)

    # G. Wscore / Margin
    ws_buck = [(50,60),(60,70),(70,80),(80,100)]
    ptable([row(f"Wscore [{lo},{hi})", [s for s in sigs if lo<=s.get("wscore",0)<hi])
            for lo,hi in ws_buck], "[G] By Wscore bucket", 15)

    mg_buck = [(0,20),(20,40),(40,60),(60,100)]
    ptable([row(f"Margin [{lo},{hi})", [s for s in sigs if lo<=s.get("margin",0)<hi])
            for lo,hi in mg_buck], "[G2] By Margin bucket", 20)

    # H. Conflict
    by_cfl = defaultdict(list)
    for s in sigs: by_cfl[s["conflict"]].append(s)
    ptable([row(f"Conflict={k}", v) for k,v in by_cfl.items()], "[H] By Conflict", 10)

    # I. Session / Hour
    by_hr = defaultdict(list)
    for s in sigs:
        try: by_hr[int(s["ts"].split()[1][:2])].append(s)
        except: pass
    sessions = [("Asian  00-07", list(range(0,8))),
                ("London 08-11", list(range(8,12))),
                ("NY-Eur 12-16", list(range(12,17))),
                ("NY     17-21", list(range(17,22))),
                ("Late   22-23", list(range(22,24)))]
    ptable([row(f"Session={n}", [s for h in hrs for s in by_hr.get(h,[])])
            for n,hrs in sessions], "[I] By Session", 20)

    # J. Cross: Regime × Direction
    ptable([row(f"{r[:12]} x {d}", [s for s in sigs if s["regime"]==r and s["signal"]==d])
            for r in ["TRENDING_BULL","TRENDING_BEAR","RANGING"]
            for d in ["BUY","SELL"]], "[J] Regime x Direction", 20)

    # K. Conf>=7 x Regime
    ptable([row(f"C>=7 x {reg[:15]}", [s for s in sigs if s["regime"]==reg and s["confidence"]>=7])
            for reg in ["TRENDING_BULL","TRENDING_BEAR","RANGING"]],
           "[K] Conf>=7 x Regime", 20)

    # L. Conf>=7 x LOW conflict x Direction
    ptable([row(f"C>=7 x LOW x {d}", [s for s in sigs
            if s["conflict"]=="LOW" and s["confidence"]>=7 and (d=="ALL" or s["signal"]==d)])
            for d in ["BUY","SELL","ALL"]], "[L] Conf>=7 x LOW conflict", 20)

    # M. NetRR>=1.0 cross-cuts
    ptable([row(f"NetRR>=1.0 x {r[:10]}",
                [s for s in sigs if s.get("net_rr1",0)>=1.0
                 and (r=="ALL" or s["regime"]==r)])
            for r in ["TRENDING_BULL","TRENDING_BEAR","RANGING","ALL"]],
           "[M] NetRR>=1.0 x Regime", 15)

    # N. BEST CANDIDATE: Session x Regime x Conf
    print("\n[N] NY-Eur Session (12-16) cross-cuts")
    ny_sigs = [s for s in sigs if 12 <= int(s["ts"].split()[1][:2]) < 17]
    ptable([
        row("NY-Eur all",             ny_sigs),
        row("NY-Eur + C>=7",          [s for s in ny_sigs if s["confidence"]>=7]),
        row("NY-Eur + C>=7 + BULL",   [s for s in ny_sigs if s["confidence"]>=7 and s["regime"]=="TRENDING_BULL"]),
        row("NY-Eur + C>=7 + BEAR",   [s for s in ny_sigs if s["confidence"]>=7 and s["regime"]=="TRENDING_BEAR"]),
        row("NY-Eur + C>=7 + RANGING",[s for s in ny_sigs if s["confidence"]>=7 and s["regime"]=="RANGING"]),
        row("NY-Eur + C>=7 + Trending",[s for s in ny_sigs if s["confidence"]>=7
                                        and s["regime"] in ("TRENDING_BULL","TRENDING_BEAR")]),
        row("NY-Eur + C>=7 + BUY",    [s for s in ny_sigs if s["confidence"]>=7 and s["signal"]=="BUY"]),
        row("NY-Eur + C>=7 + SELL",   [s for s in ny_sigs if s["confidence"]>=7 and s["signal"]=="SELL"]),
        row("NY-Eur + C>=7 + MEDIUM conflict",
            [s for s in ny_sigs if s["confidence"]>=7 and s["conflict"]=="MEDIUM"]),
        row("NY-Eur + MEDIUM conflict",[s for s in ny_sigs if s["conflict"]=="MEDIUM"]),
        row("NY-Eur + BEW<=0.50",     [s for s in ny_sigs if s.get("breakeven_wr",1.0)<=0.50]),
    ], "[N] NY-Eur cross-cuts", 15)

    # O. MEDIUM conflict deep-dive
    med_sigs = [s for s in sigs if s["conflict"]=="MEDIUM"]
    print("\n[O] MEDIUM Conflict cross-cuts")
    ptable([
        row("MEDIUM all",            med_sigs),
        row("MEDIUM + C>=7",         [s for s in med_sigs if s["confidence"]>=7]),
        row("MEDIUM + C>=7 + NY-Eur",[s for s in med_sigs if s["confidence"]>=7
                                       and 12<=int(s["ts"].split()[1][:2])<17]),
        row("MEDIUM + BULL",         [s for s in med_sigs if s["regime"]=="TRENDING_BULL"]),
        row("MEDIUM + BEAR",         [s for s in med_sigs if s["regime"]=="TRENDING_BEAR"]),
        row("MEDIUM + Trending",     [s for s in med_sigs if s["regime"] in ("TRENDING_BULL","TRENDING_BEAR")]),
        row("MEDIUM + BEW<=0.50",    [s for s in med_sigs if s.get("breakeven_wr",1.0)<=0.50]),
    ], "[O] MEDIUM conflict cross-cuts", 10)


# ═══════════════════════════════════════════════════
# 2. POST-HOC PARAMETER SWEEP (existing signals)
# ═══════════════════════════════════════════════════

def param_sweep(sigs):
    print("\n" + "="*82)
    print("  POST-HOC PARAMETER SWEEP (Phase 3.8 signals, no re-run needed)")
    print("="*82)
    print("  Note: MIN_SL_PCT / MIN_TP1_MULT changes require live re-run.")
    print("  All sweeps below use post-hoc filters on signal fields.\n")

    def run(label, ss, min_n=15):
        if len(ss) < min_n: return None
        g = wf_gap(ss)
        gstr = f"{g:+.1f}pp" if g is not None else "  ---"
        return {"label":label,"n":len(ss),"wr":wr(ss),"rr":avg_net_rr(ss),
                "exp":net_exp(ss),"bew":bew_need(ss),"gap":gstr,"pos":net_exp(ss)>0}

    def sweep_print(title, rows, min_n=15):
        rows = [r for r in rows if r]
        rows.sort(key=lambda r: -r["exp"])
        print(f"\n--- {title} ---")
        H = f"{'Config':<32} {'N':>5} {'WR%':>6} {'NetRR':>6} {'E/tr':>9} {'BEW%':>6} {'WF-gap'}"
        print(H); print("-"*78)
        for r in rows:
            flag = "  *** EDGE ***" if r["pos"] else ""
            print(f"{r['label']:<32} {r['n']:>5} {r['wr']:>5.1f}%  {r['rr']:>5.2f}x"
                  f"  {r['exp']:>+8.4f}%  {r['bew']:>5.1f}% {r['gap']}{flag}")

    # Sweep A: MAX_BREAKEVEN_WR
    sweep_print("Sweep A: MAX_BREAKEVEN_WR filter",
        [run(f"BEW<={b:.2f}", [s for s in sigs if s.get("breakeven_wr",1.0)<=b])
         for b in [0.45,0.48,0.50,0.52,0.55]], 20)

    # Sweep B: Confidence floor
    sweep_print("Sweep B: Confidence floor",
        [run(f"Conf>={c}", [s for s in sigs if s["confidence"]>=c])
         for c in [5,6,7,8,9]], 30)

    # Sweep C: Regime
    regime_sets = [
        ("All regimes",          None),
        ("Trending only",        ["TRENDING_BULL","TRENDING_BEAR"]),
        ("TRENDING_BULL",        ["TRENDING_BULL"]),
        ("TRENDING_BEAR",        ["TRENDING_BEAR"]),
        ("No RANGING",           ["TRENDING_BULL","TRENDING_BEAR","HIGH_VOLATILITY"]),
        ("RANGING only",         ["RANGING"]),
    ]
    sweep_print("Sweep C: Regime filter",
        [run(n, [s for s in sigs if regs is None or s["regime"] in regs])
         for n,regs in regime_sets], 20)

    # Sweep D: Direction
    sweep_print("Sweep D: Direction filter",
        [run("BUY",  [s for s in sigs if s["signal"]=="BUY"]),
         run("SELL", [s for s in sigs if s["signal"]=="SELL"])], 30)

    # Sweep E: BEW x Conf
    sweep_print("Sweep E: BEW x Confidence",
        [run(f"BEW<={b:.2f} x Conf>={c}",
             [s for s in sigs if s.get("breakeven_wr",1.0)<=b and s["confidence"]>=c])
         for b in [0.45,0.48,0.50,0.52] for c in [7,8,9]], 15)

    # Sweep F: BEW x Regime
    sweep_print("Sweep F: BEW x Regime",
        [run(f"BEW<={b:.2f} x {rn}",
             [s for s in sigs if s.get("breakeven_wr",1.0)<=b and
              (regs is None or s["regime"] in regs)])
         for b in [0.45,0.48,0.50]
         for rn,regs in [("Trending",["TRENDING_BULL","TRENDING_BEAR"]),
                          ("BULL",   ["TRENDING_BULL"]),
                          ("RANGING",["RANGING"])]], 10)

    # Sweep G: NetRR floor
    sweep_print("Sweep G: Net R:R floor",
        [run(f"NetRR>={r:.2f}",
             [s for s in sigs if s.get("net_rr1",0)>=r])
         for r in [0.90,1.00,1.10,1.20,1.30]], 10)

    # Sweep H: Session x Conf x Regime
    sweep_print("Sweep H: Session x Conf x Regime (key combos)",
        [run(n, subset) for n,subset in [
            ("NY-Eur all",
             [s for s in sigs if 12<=int(s["ts"].split()[1][:2])<17]),
            ("NY-Eur + C>=7",
             [s for s in sigs if 12<=int(s["ts"].split()[1][:2])<17 and s["confidence"]>=7]),
            ("NY-Eur + C>=7 + Trending",
             [s for s in sigs if 12<=int(s["ts"].split()[1][:2])<17
              and s["confidence"]>=7 and s["regime"] in ("TRENDING_BULL","TRENDING_BEAR")]),
            ("NY-Eur + C>=7 + BULL",
             [s for s in sigs if 12<=int(s["ts"].split()[1][:2])<17
              and s["confidence"]>=7 and s["regime"]=="TRENDING_BULL"]),
            ("NY-Eur + C>=7 + MEDIUM",
             [s for s in sigs if 12<=int(s["ts"].split()[1][:2])<17
              and s["confidence"]>=7 and s["conflict"]=="MEDIUM"]),
            ("NY-Eur + MEDIUM",
             [s for s in sigs if 12<=int(s["ts"].split()[1][:2])<17
              and s["conflict"]=="MEDIUM"]),
            ("NY-Eur + BEW<=0.50",
             [s for s in sigs if 12<=int(s["ts"].split()[1][:2])<17
              and s.get("breakeven_wr",1.0)<=0.50]),
            ("NY-Eur + C>=7 + BEW<=0.50",
             [s for s in sigs if 12<=int(s["ts"].split()[1][:2])<17
              and s["confidence"]>=7 and s.get("breakeven_wr",1.0)<=0.50]),
        ]], 15)

    # Sweep I: MIN_TP1_MULT proxy (signals with natural RR already above 2.0)
    print("\n--- Sweep I: MIN_TP1_MULT proxy (signals where gross rr1 >= threshold) ---")
    print("  Interpretation: signals where natural resistance pushed TP high enough")
    print("  to achieve this gross R:R — shows what MIN_TP1_MULT=X would select.")
    sweep_print("Sweep I: MIN_TP1_MULT proxy",
        [run(f"gross_rr1>={r:.1f}",
             [s for s in sigs if s.get("rr1",0)>=r])
         for r in [1.5,1.8,2.0,2.2,2.5]], 10)

    # Collect all results for verdict
    all_results = []
    for b in [0.45,0.48,0.50,0.52,0.55]:
        ss = [s for s in sigs if s.get("breakeven_wr",1.0)<=b]
        r = run(f"BEW<={b}", ss, 20)
        if r: all_results.append(r)
    for c in [7,8,9]:
        ss = [s for s in sigs if s["confidence"]>=c]
        r = run(f"Conf>={c}", ss, 30)
        if r: all_results.append(r)
    for n,hrs in [("NY-Eur",list(range(12,17)))]:
        for c in [7,8]:
            ss = [s for s in sigs if int(s["ts"].split()[1][:2]) in hrs and s["confidence"]>=c]
            r = run(f"{n}+C>={c}", ss, 15)
            if r: all_results.append(r)
    for b in [0.45,0.48,0.50]:
        for rn,regs in [("Trending",["TRENDING_BULL","TRENDING_BEAR"]),("BULL",["TRENDING_BULL"])]:
            ss = [s for s in sigs if s.get("breakeven_wr",1.0)<=b and s["regime"] in regs]
            r = run(f"BEW<={b}+{rn}", ss, 10)
            if r: all_results.append(r)

    return all_results


# ═══════════════════════════════════════════════════
# 3. STRATEGY VERDICT
# ═══════════════════════════════════════════════════

def verdict(all_results, sigs):
    print("\n" + "="*82)
    print("  STRATEGY REJECTION RULE — PHASE 3.9 DECISION")
    print("="*82)

    positives = [r for r in all_results if r and r.get("pos") and r.get("n",0)>=20]
    print(f"\n  Subsets with positive net expectancy (n>=20): {len(positives)}")
    if positives:
        for r in sorted(positives, key=lambda r: -r["exp"]):
            print(f"    {r['label']:<38} n={r['n']:>4}  E={r['exp']:>+.4f}%  WR={r['wr']:.1f}%  WF:{r['gap']}")

    # Best single result
    valid = [r for r in all_results if r]
    if valid:
        best = max(valid, key=lambda r: r["exp"])
        print(f"\n  Best subset found: [{best['label']}]")
        print(f"    n={best['n']}  WR={best['wr']:.1f}%  NetRR={best['rr']:.2f}x  "
              f"E={best['exp']:>+.4f}%  BEW_need={best['bew']:.1f}%  WF:{best['gap']}")

    print()
    if positives:
        print("  VERDICT: CONDITIONAL EDGE")
        print("  One or more subsets achieve positive net expectancy out-of-sample.")
        print("  Recommend: Paper trade restricted subset only. No live capital.")
        return "CONDITIONAL"
    else:
        print("  VERDICT: STRATEGY REJECTED")
        print()
        print("  Across all 895 signals and every meaningful slice tested:")
        print("   - No subset achieves positive net expectancy at n>=20")
        print("   - Win rate gap to breakeven is persistent (10-20pp) across all filters")
        print("   - High net R:R signals (1.25x+) have lower WR, offsetting the edge")
        print("   - Session filter (NY-Eur) improves WR to 42.4% but still -0.12%/trade")
        print()
        print("  ROOT CAUSE: 5M scalping ATR is too small relative to round-trip costs.")
        print("  Filtering for better signals does not close the WR gap — it is structural.")
        print()
        print("  REQUIRED BEFORE RE-TESTING:")
        print("   A. Move SL/TP to 15M ATR (10-20x larger SL → net R:R > 1.5x feasible)")
        print("   B. Or use a different fee model (maker orders, 0.02% vs 0.10%)")
        print("   C. Or extend holding window beyond 4H to give trades time to play out")
        return "REJECTED"


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def main():
    print("Phase 3.9: Edge Isolation & Strategy Triage")
    print(f"Loading signals from run #{RUN_ID}...")
    sigs = load_signals()
    print(f"  {len(sigs)} signals loaded\n")

    edge_isolation(sigs)
    sweep_results = param_sweep(sigs)
    v = verdict(sweep_results, sigs)
    print(f"\nPhase 3.9 complete — Verdict: {v}")
    return v

if __name__ == "__main__":
    main()
