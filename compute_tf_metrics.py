"""
Compute the locked metrics for the 6 TF comparison runs.

Reads from data/breakout.db, computes:
  - per-config: n, WR strict, avg_R, sum_R, PF, max_DD
  - CPCV: wr_mean / std / q05 / verdict (validation.cpcv_summary)
  - PSR (vs SR=0), DSR (deflated by n_trials=3)
  - 70/30 temporal OOS split
  - walk-forward by month (90d = 3 months)
  - per-token expectancy + blowup flag
Output: data/tf_metrics_results.json + console summary
"""
from __future__ import annotations
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

_BD = Path(__file__).resolve().parent
sys.path.insert(0, str(_BD))
sys.path.insert(0, "/home/tradeai/TradeAI")

from validation import (cpcv_summary, deflated_sharpe_ratio,
                         probabilistic_sharpe_ratio, sharpe_ratio)

DB = _BD / "data" / "breakout.db"
OUT = _BD / "data" / "tf_metrics_results.json"

# 3 trial-deflation for the comparison (3 distinct configs)
N_TRIALS = 3

# Pre-registered locked thresholds (informational, NOT verdict gates for this comparison)
# We use CPCV's verdict but treat overall result as informational, not pass/fail.

RUNS = [
    # (run_id, label, friction_mode)
    # Filled by query below
]


def fetch_runs(conn) -> list:
    rows = list(conn.execute(
        "SELECT id, summary FROM backtest_runs WHERE config_hash LIKE '%_CLEAN' "
        "OR config_hash LIKE '%_FRICTION' ORDER BY id"))
    out = []
    for r in rows:
        s = json.loads(r["summary"])
        out.append({"run_id": r["id"], "cfg_id": s["tf_config_id"],
                    "friction_mode": s["friction_mode"], "label": s["label"]})
    return out


def fetch_signals(conn, run_id: int) -> list:
    rows = list(conn.execute(
        "SELECT token, signal, outcome, realized_r, net_tp1_pct, net_sl_pct, "
        " ts, hour_utc, sweep_type FROM backtest_signals WHERE run_id = ? ORDER BY ts",
        (run_id,)))
    return [dict(r) for r in rows]


def profit_factor(signals):
    w = sum(s["realized_r"] for s in signals if s["realized_r"] > 0)
    l = sum(abs(s["realized_r"]) for s in signals if s["realized_r"] < 0)
    if l <= 0:
        return float("inf") if w > 0 else 0.0
    return w / l


def max_dd_R(signals):
    cum, peak, mdd = 0.0, 0.0, 0.0
    for s in signals:
        cum += s["realized_r"]
        if cum > peak: peak = cum
        if peak - cum > mdd: mdd = peak - cum
    return mdd, cum, peak


def _is_win(s): return s.get("outcome") in ("WIN", "PARTIAL_TP2")
def _ws(s):
    if s.get("outcome") == "WIN": return 1.0
    if s.get("outcome") == "PARTIAL_TP2": return 1.0
    if s.get("outcome") == "PARTIAL_TP1": return 0.5
    return 0.0
def _pnl(s): return float(s.get("realized_r") or 0.0)


def temporal_70_30(signals):
    s = sorted(signals, key=lambda x: x["ts"])
    cut = int(len(s)*0.70)
    return s[:cut], s[cut:]


def walk_forward_monthly(signals):
    months = defaultdict(list)
    for s in signals:
        try:
            dt = datetime.fromisoformat(s["ts"])
            key = f"{dt.year}-{dt.month:02d}"
            months[key].append(s)
        except ValueError:
            continue
    out = []
    for k in sorted(months.keys()):
        sigs = months[k]
        if not sigs: continue
        n = len(sigs)
        wins = sum(1 for s in sigs if _is_win(s))
        out.append({
            "month": k, "n": n, "wr": round(wins/n, 4),
            "avg_R": round(mean(s["realized_r"] for s in sigs), 4),
            "sum_R": round(sum(s["realized_r"] for s in sigs), 2),
            "pf": round(profit_factor(sigs), 3) if profit_factor(sigs) != float("inf") else None,
        })
    return out


def per_token(signals):
    by = defaultdict(list)
    for s in signals: by[s["token"]].append(s)
    out = []
    any_blow = False
    for tok in sorted(by.keys()):
        ss = by[tok]
        n = len(ss)
        wins = sum(1 for s in ss if _is_win(s))
        wr = wins/n if n else 0.0
        avg = mean(s["realized_r"] for s in ss) if ss else 0.0
        blow = n >= 5 and wr <= 0.35 and avg < 0
        if blow: any_blow = True
        out.append({"token": tok, "n": n, "wr": round(wr, 4),
                     "avg_R": round(avg, 4),
                     "sum_R": round(sum(s["realized_r"] for s in ss), 2),
                     "blowup": blow})
    return out, any_blow


def main():
    print("=" * 78)
    print("TF COMPARISON METRICS — 6 runs (3 configs × clean/friction)")
    print("=" * 78)
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    runs = fetch_runs(conn)
    print(f"  Loaded {len(runs)} runs.")

    # For DSR — need per-config Sharpe std across the 3 CLEAN configs
    clean_sharpes = []
    results = []
    for r in runs:
        sigs = fetch_signals(conn, r["run_id"])
        n = len(sigs)
        if n == 0:
            results.append({**r, "n": 0})
            continue
        rs = [s["realized_r"] for s in sigs]
        wins = sum(1 for s in sigs if _is_win(s))
        wr = wins / n
        avg_r = sum(rs) / n
        sum_r = sum(rs)
        pf = profit_factor(sigs)
        mdd, cum, peak = max_dd_R(sigs)
        sr = sharpe_ratio(rs, periods_per_year=1.0)
        psr = probabilistic_sharpe_ratio(sr_observed=sr, n_returns=n,
                                          skew=0.0, kurtosis=3.0,
                                          sr_benchmark=0.0)
        train, test = temporal_70_30(sigs)
        tw = sum(1 for s in train if _is_win(s)) / len(train) if train else 0
        te = sum(1 for s in test if _is_win(s)) / len(test) if test else 0
        ta = mean(s["realized_r"] for s in train) if train else 0
        ea = mean(s["realized_r"] for s in test) if test else 0
        wf = walk_forward_monthly(sigs)
        pt, blowup = per_token(sigs)
        cpcv = None
        if n >= 60:
            try:
                cpcv = cpcv_summary(sigs, n_groups=10, n_test_groups=2,
                                     embargo_pct=0.01,
                                     is_win_func=_is_win, score_func=_ws,
                                     pnl_func=_pnl, n_trials_for_dsr=N_TRIALS)
            except Exception as e:
                cpcv = {"error": str(e)}
        if r["friction_mode"] == "CLEAN":
            clean_sharpes.append(sr)
        results.append({
            **r, "n": n, "wr": round(wr, 4),
            "avg_R": round(avg_r, 4), "sum_R": round(sum_r, 3),
            "profit_factor": round(pf, 3) if pf != float("inf") else None,
            "max_dd_R": round(mdd, 3), "peak_R": round(peak, 3),
            "sharpe_per_trade": round(sr, 4),
            "psr": round(psr, 4) if psr is not None else None,
            "train_avg_R": round(ta, 4), "test_avg_R": round(ea, 4),
            "train_wr": round(tw, 4), "test_wr": round(te, 4),
            "walk_forward_monthly": wf, "per_token": pt, "blowup_flag": blowup,
            "cpcv": cpcv,
        })

    # DSR per CLEAN config (using cross-config std of the 3 clean Sharpes)
    sr_std = pstdev(clean_sharpes) if len(clean_sharpes) > 1 else 0.0
    for r in results:
        if r.get("n", 0) >= 30 and sr_std > 0:
            try:
                d = deflated_sharpe_ratio(
                    sr_observed=r["sharpe_per_trade"], n_returns=r["n"],
                    n_trials=N_TRIALS, sr_trial_std=sr_std,
                    skew=0.0, kurtosis=3.0,
                )
                r["dsr"] = round(d, 4)
            except Exception:
                r["dsr"] = None
        else:
            r["dsr"] = None
    conn.close()

    # Save JSON
    out = {"n_trials_dsr": N_TRIALS, "sr_std_clean_configs": round(sr_std, 4),
           "runs": results}
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Wrote: {OUT}")

    # Console summary
    print()
    print("─" * 100)
    print(f"{'cfg':<12} {'mode':<10} {'n':>5} {'WR':>6} {'avg_R':>7} {'sum_R':>8} {'PF':>6} "
          f"{'maxDD':>6} {'SR':>6} {'PSR':>5} {'DSR':>5} {'CPCV verd':>9} "
          f"{'train→test':>12} {'blowup':>7}")
    print("─" * 100)
    for r in sorted(results, key=lambda x: (x["cfg_id"], x["friction_mode"])):
        cpcv_v = (r.get("cpcv") or {}).get("verdict", "—") if r.get("cpcv") else "—"
        psr_s = f"{r.get('psr', 0):.2f}" if r.get("psr") is not None else "—"
        dsr_s = f"{r.get('dsr', 0):.2f}" if r.get("dsr") is not None else "—"
        pf_s  = f"{r.get('profit_factor', 0):.2f}" if r.get("profit_factor") is not None else "inf"
        tt = f"{r.get('train_avg_R',0):+.2f}→{r.get('test_avg_R',0):+.2f}"
        bl = "⚠" if r.get("blowup_flag") else "no"
        print(f"{r['cfg_id']:<12} {r['friction_mode']:<10} {r.get('n',0):>5} "
              f"{r.get('wr',0):.3f} {r.get('avg_R',0):>+7.3f} "
              f"{r.get('sum_R',0):>+8.1f} {pf_s:>6} {r.get('max_dd_R',0):>6.1f} "
              f"{r.get('sharpe_per_trade',0):>+6.2f} {psr_s:>5} {dsr_s:>5} "
              f"{cpcv_v:>9} {tt:>12} {bl:>7}")
    print()
    print(f"cross-config Sharpe std (CLEAN only) = {sr_std:.4f}")


if __name__ == "__main__":
    main()
