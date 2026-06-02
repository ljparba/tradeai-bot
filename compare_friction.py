"""
compare_friction.py — Side-by-side: Config 14 frictionless vs friction-on.

Reads from data/breakout.db: original Config 14 run + the FRICTION run.
Reports the expected and friction-on numbers side by side, breaks down
the friction outcome counts, and identifies any per-token blowup.

Decision rule (from the STEP 2 prompt):
  if friction-on avg_R stays clearly positive and PF > ~1.5 with no
  token-level blowup → proceed to 2B.
  Otherwise → STOP, no soak, no tuning.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

_BREAKOUT_DIR = Path(__file__).resolve().parent
DB_PATH = _BREAKOUT_DIR / "data" / "breakout.db"


def fetch_run(conn, run_id: int):
    row = conn.execute(
        "SELECT id, total_signals, overall_wr, avg_rr, summary FROM backtest_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "run_id":         row[0],
        "total_signals":  row[1],
        "overall_wr":     row[2],
        "avg_rr":         row[3],
        "summary":        json.loads(row[4]),
    }


def fetch_signals(conn, run_id: int):
    rows = list(conn.execute(
        "SELECT token, signal, outcome, realized_r, net_tp1_pct, net_sl_pct, rr1 "
        "FROM backtest_signals WHERE run_id = ? ORDER BY ts",
        (run_id,),
    ))
    return [{"token": r[0], "signal": r[1], "outcome": r[2],
             "realized_r": r[3], "net_tp1_pct": r[4],
             "net_sl_pct": r[5], "rr1": r[6]} for r in rows]


def profit_factor(signals):
    wins = sum(s["realized_r"] for s in signals if s["realized_r"] > 0)
    losses = sum(abs(s["realized_r"]) for s in signals if s["realized_r"] < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def equity_dd(signals):
    if not signals:
        return 0.0, 0.0, 0.0
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for s in signals:
        cum += s["realized_r"]
        if cum > peak:
            peak = cum
        if peak - cum > max_dd:
            max_dd = peak - cum
    return cum, peak, max_dd


def per_token(signals):
    by_tok = defaultdict(list)
    for s in signals:
        by_tok[s["token"]].append(s)
    out = []
    for tok in sorted(by_tok.keys()):
        sigs = by_tok[tok]
        n = len(sigs)
        n_wins = sum(1 for s in sigs if s["outcome"] in ("WIN", "PARTIAL_TP2"))
        wr = n_wins / n if n else 0.0
        avg_r = sum(s["realized_r"] for s in sigs) / n if n else 0.0
        sum_r = sum(s["realized_r"] for s in sigs)
        pf = profit_factor(sigs)
        out.append({"token": tok, "n": n, "wr": wr, "avg_R": avg_r,
                    "sum_R": sum_r, "pf": pf if pf != float("inf") else None})
    return out


def main():
    conn = sqlite3.connect(str(DB_PATH))
    # Config 14 is run_id=14 in the grid; friction run_id was returned by run_friction_config14
    clean = fetch_run(conn, 14)
    friction = fetch_run(conn, 18)
    if not clean or not friction:
        print(f"  ERROR: missing run (clean=14 present={clean is not None}, "
              f"friction=18 present={friction is not None})")
        sys.exit(1)

    print("=" * 78)
    print("PHASE C-BREAKOUT STEP 2A — FRICTION vs CLEAN COMPARISON")
    print("=" * 78)
    print(f"  Both runs use Config 14: "
          f"tp=2.0/3.0/4.0R, c2=4, mss=30, buf=0.001")
    print(f"  Clean run_id:    14")
    print(f"  Friction run_id: 18")
    print()

    clean_sigs = fetch_signals(conn, 14)
    fric_sigs = fetch_signals(conn, 18)

    # Aggregate metrics
    c_n = len(clean_sigs)
    f_n = len(fric_sigs)
    f_summary = friction["summary"]
    n_attempted = f_summary.get("n_attempted", f_n)
    n_no_fill = f_summary.get("n_rejected_no_fill", 0)
    n_stale = f_summary.get("n_rejected_stale", 0)
    n_partial = f_summary.get("n_partial", 0)
    n_low_atr = f_summary.get("n_skipped_low_atr", 0)

    c_wins_p2 = sum(1 for s in clean_sigs if s["outcome"] in ("WIN", "PARTIAL_TP2"))
    f_wins_p2 = sum(1 for s in fric_sigs if s["outcome"] in ("WIN", "PARTIAL_TP2"))
    c_wr = c_wins_p2 / c_n if c_n else 0
    f_wr = f_wins_p2 / f_n if f_n else 0

    c_avg_r = mean(s["realized_r"] for s in clean_sigs) if clean_sigs else 0
    f_avg_r = mean(s["realized_r"] for s in fric_sigs) if fric_sigs else 0
    f_avg_r_attempted = sum(s["realized_r"] for s in fric_sigs) / n_attempted if n_attempted else 0

    c_sum_r = sum(s["realized_r"] for s in clean_sigs)
    f_sum_r = sum(s["realized_r"] for s in fric_sigs)
    f_sum_r_clean = f_summary.get("sum_R_if_no_friction", 0)

    c_pf = profit_factor(clean_sigs)
    f_pf = profit_factor(fric_sigs)

    _, c_peak, c_dd = equity_dd(sorted(clean_sigs, key=lambda s: id(s)))
    _, f_peak, f_dd = equity_dd(sorted(fric_sigs, key=lambda s: id(s)))

    # ── Side-by-side table ────────────────────────────────────────────
    print("─" * 78)
    print("HEADLINE COMPARISON")
    print("─" * 78)
    print(f"  {'Metric':<35} {'Clean (Config 14)':>20} {'Friction':>18}")
    print(f"  {'─'*35} {'─'*20} {'─'*18}")
    print(f"  {'n signals (attempted)':<35} {c_n:>20} {n_attempted:>18}")
    print(f"  {'n signals (actually traded)':<35} {c_n:>20} {f_n:>18}")
    print(f"  {'  of which PARTIAL FILLS':<35} {'-':>20} {n_partial:>18}")
    print(f"  {'  REJECTED (no fill)':<35} {'-':>20} {n_no_fill:>18}")
    print(f"  {'  REJECTED (stale move)':<35} {'-':>20} {n_stale:>18}")
    print(f"  {'  SKIPPED (insufficient ATR)':<35} {'-':>20} {n_low_atr:>18}")
    print()
    print(f"  {'avg_R per traded signal':<35} {c_avg_r:>+20.4f} {f_avg_r:>+18.4f}")
    print(f"  {'avg_R per attempted signal':<35} {c_avg_r:>+20.4f} {f_avg_r_attempted:>+18.4f}")
    print(f"  {'sum_R (total)':<35} {c_sum_r:>+20.2f} {f_sum_r:>+18.2f}")
    print(f"  {'  sum_R if friction was zero':<35} {'-':>20} {f_sum_r_clean:>+18.2f}")
    print(f"  {'sum_R delta from friction':<35} {'-':>20} {f_sum_r - f_sum_r_clean:>+18.2f}")
    print(f"  {'profit factor':<35} {c_pf:>20.3f} {f_pf:>18.3f}")
    print(f"  {'win rate':<35} {c_wr:>20.4f} {f_wr:>18.4f}")
    print(f"  {'peak equity (R)':<35} {c_peak:>20.2f} {f_peak:>18.2f}")
    print(f"  {'max drawdown (R)':<35} {c_dd:>20.2f} {f_dd:>18.2f}")
    print()

    # ── Per-token comparison ─────────────────────────────────────────
    print("─" * 78)
    print("PER-TOKEN COMPARISON")
    print("─" * 78)
    c_per_tok = {t["token"]: t for t in per_token(clean_sigs)}
    f_per_tok = {t["token"]: t for t in per_token(fric_sigs)}
    tokens = sorted(set(c_per_tok.keys()) | set(f_per_tok.keys()))
    print(f"  {'token':>5}  {'CLEAN n':>7}  {'FRIC n':>6}  "
          f"{'CLEAN avg_R':>11}  {'FRIC avg_R':>10}  "
          f"{'CLEAN PF':>8}  {'FRIC PF':>7}  {'CLEAN sum_R':>11}  {'FRIC sum_R':>10}  flag")
    print(f"  {'─'*5}  {'─'*7}  {'─'*6}  {'─'*11}  {'─'*10}  "
          f"{'─'*8}  {'─'*7}  {'─'*11}  {'─'*10}  ────")
    flipped_negative = []
    for tok in tokens:
        c = c_per_tok.get(tok, {"n": 0, "avg_R": 0, "pf": None, "sum_R": 0})
        f = f_per_tok.get(tok, {"n": 0, "avg_R": 0, "pf": None, "sum_R": 0})
        c_pf_str = f"{c['pf']:.3f}" if c['pf'] is not None else "  -  "
        f_pf_str = f"{f['pf']:.3f}" if f['pf'] is not None else "  -  "
        # Flag: did this token go from positive avg_R to negative?
        flag = ""
        if c["avg_R"] > 0 and f["avg_R"] <= 0:
            flag = "FLIP→NEG"
            flipped_negative.append(tok)
        elif f["sum_R"] < 0:
            flag = "NEG sum_R"
        print(f"  {tok:>5}  {c['n']:>7}  {f['n']:>6}  "
              f"{c['avg_R']:>+11.4f}  {f['avg_R']:>+10.4f}  "
              f"{c_pf_str:>8}  {f_pf_str:>7}  {c['sum_R']:>+11.2f}  {f['sum_R']:>+10.2f}  {flag}")

    print()
    if flipped_negative:
        print(f"  ⚠ Tokens that flipped to negative avg_R: {flipped_negative}")
    else:
        print(f"  No tokens flipped to negative avg_R.")
    print()

    # ── Decision rule output ─────────────────────────────────────────
    print("─" * 78)
    print("DECISION RULE — auto-evaluated, NOT tuned")
    print("─" * 78)
    print(f"  Rule from prompt: 'friction-on avg_R stays clearly positive AND")
    print(f"                     PF > ~1.5 AND no token-level blowup → 2B.'")
    print()
    avg_r_attempted_ok = f_avg_r_attempted > 0
    pf_ok = f_pf > 1.5
    no_blowup = len(flipped_negative) == 0
    print(f"  friction avg_R per attempted = {f_avg_r_attempted:+.4f}  ({'OK' if avg_r_attempted_ok else 'FAIL'})")
    print(f"  friction PF                  = {f_pf:.3f}  ({'OK' if pf_ok else 'FAIL'})")
    print(f"  no per-token flip-to-neg     = {no_blowup}  ({'OK' if no_blowup else 'FAIL'})")
    print()
    if avg_r_attempted_ok and pf_ok and no_blowup:
        print("  >>> VERDICT: PROCEED to Step 2B (paper soak).")
    else:
        print("  >>> VERDICT: STOP. Edge does not clearly survive friction. Do not start soak.")
    print()


if __name__ == "__main__":
    main()
