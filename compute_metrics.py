"""
compute_metrics.py — Honest metrics over the PHASE C-BREAKOUT grid.

Reads from data/breakout.db, computes per-config and across-grid statistics:
  - Per config: n, avg_R, sum_R, profit_factor, max drawdown, equity curve
  - Per config: CPCV (WR per fold, Sharpe per fold)
  - Per config: PSR, DSR (deflated by n_trials=16)
  - Per config: temporal 70/30 OOS split
  - Per config: walk-forward by calendar quarter
  - Per-token expectancy (across all 16 configs)
  - Blended grid-level statistics

Outputs:
  - data/metrics_results.json (full structured)
  - prints a console summary

Lead-with-expectancy discipline (per §2 of prompt):
  - Every per-config row reports avg_R / sum_R / PF / equity DD FIRST
  - WR appears AFTER expectancy fields
  - DSR / CPCV are corrective overlays, not the headline
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev

_BREAKOUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BREAKOUT_DIR))
sys.path.insert(0, "/home/tradeai/TradeAI")

from validation import (  # noqa: E402
    cpcv_summary,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)

DB_PATH = _BREAKOUT_DIR / "data" / "breakout.db"
OUT_PATH = _BREAKOUT_DIR / "data" / "metrics_results.json"

N_TRIALS = 16  # grid size — DSR deflation factor


def load_all_runs() -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    runs = []
    for row in conn.execute("SELECT id, total_signals, overall_wr, summary FROM backtest_runs ORDER BY id"):
        summary = json.loads(row["summary"])
        runs.append({
            "run_id":        row["id"],
            "config":        summary["config"],
            "n_signals":     row["total_signals"],
            "overall_wr":    row["overall_wr"],
            "summary":       summary,
        })
    conn.close()
    return runs


def load_signals_for_run(conn, run_id: int) -> list[dict]:
    rows = list(conn.execute(
        "SELECT token, signal, ts, outcome, realized_r, "
        " net_tp1_pct, net_tp2_pct, net_tp3_pct, net_sl_pct, "
        " tp1_pct, sl_pct, rr1, session, hour_utc, sweep_type "
        "FROM backtest_signals WHERE run_id = ? ORDER BY ts",
        (run_id,),
    ))
    return [dict(r) for r in rows]


# ── Expectancy / equity helpers ─────────────────────────────────────────────
def profit_factor(signals: list[dict]) -> float:
    """Sum of winning $ / sum of losing $ (in R units)."""
    wins = sum(s["realized_r"] for s in signals if s["realized_r"] > 0)
    losses = sum(abs(s["realized_r"]) for s in signals if s["realized_r"] < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def equity_curve_r(signals: list[dict]) -> tuple[list[float], float, float]:
    """Cumulative R curve. Returns (curve, max_R, max_drawdown_R)."""
    if not signals:
        return [], 0.0, 0.0
    sorted_sigs = sorted(signals, key=lambda s: s["ts"])
    curve = []
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for s in sorted_sigs:
        cum += s["realized_r"]
        curve.append(cum)
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return curve, peak, max_dd


def temporal_70_30(signals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split signals chronologically into first 70% (train) and last 30% (OOS test)."""
    if not signals:
        return [], []
    sorted_sigs = sorted(signals, key=lambda s: s["ts"])
    cut = int(len(sorted_sigs) * 0.70)
    return sorted_sigs[:cut], sorted_sigs[cut:]


def walk_forward_quarterly(signals: list[dict]) -> list[dict]:
    """Group signals by calendar quarter (YYYY-Qn). Returns list of per-quarter rows."""
    quarters = defaultdict(list)
    for s in signals:
        ts = s["ts"]
        try:
            dt = datetime.fromisoformat(ts.replace("Z", ""))
            q = (dt.month - 1) // 3 + 1
            key = f"{dt.year}-Q{q}"
        except (ValueError, KeyError):
            continue
        quarters[key].append(s)
    out = []
    for k in sorted(quarters.keys()):
        sigs = quarters[k]
        if not sigs:
            continue
        n = len(sigs)
        wins = sum(1 for s in sigs if s["outcome"] in ("WIN", "PARTIAL_TP2"))
        avg_r = mean(s["realized_r"] for s in sigs) if sigs else 0.0
        sum_r = sum(s["realized_r"] for s in sigs)
        pf = profit_factor(sigs)
        out.append({
            "quarter":  k,
            "n":        n,
            "wr":       round(wins / n, 4),
            "avg_R":    round(avg_r, 3),
            "sum_R":    round(sum_r, 2),
            "pf":       round(pf, 3) if pf != float("inf") else None,
        })
    return out


# ── PnL extractors for validation.cpcv_summary ─────────────────────────────
def _breakout_is_win(s: dict) -> bool:
    """WIN / PARTIAL_TP2 → win; PARTIAL_TP1 / LOSS / EXPIRED → loss-or-flat."""
    return s.get("outcome") in ("WIN", "PARTIAL_TP2")


def _breakout_win_score(s: dict) -> float:
    """0..1 score for WR computation — same as is_win for breakout."""
    if s.get("outcome") == "WIN":
        return 1.0
    if s.get("outcome") == "PARTIAL_TP2":
        return 1.0
    if s.get("outcome") == "PARTIAL_TP1":
        return 0.5
    return 0.0


def _breakout_pnl(s: dict) -> float:
    """Realized R as PnL units (already computed by harness)."""
    return float(s.get("realized_r") or 0.0)


# ── Main analysis loop ──────────────────────────────────────────────────────
def analyze():
    print("=" * 78)
    print("PHASE C-BREAKOUT HONEST METRICS")
    print("=" * 78)
    print(f"  DB:        {DB_PATH}")
    print(f"  N_TRIALS:  {N_TRIALS} (DSR deflation factor)")
    print()

    runs = load_all_runs()
    print(f"  Loaded {len(runs)} runs.")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # First pass: gather per-config Sharpe + R series for DSR
    config_sharpes = []   # per-config whole-sample Sharpe
    config_results = []

    for run in runs:
        signals = load_signals_for_run(conn, run["run_id"])
        n = len(signals)
        c = run["config"]
        cfg_label = (f"buf={c['H4_BREAKOUT_CLOSE_BUFFER_PCT']:.3f} "
                     f"tp={c['BREAKOUT_TP1_RR']}/{c['BREAKOUT_TP2_RR']}/{c['BREAKOUT_TP3_RR']}R "
                     f"c2={c['H4_BREAKOUT_C2_LOOKBACK']} mss={c['H4_BREAKOUT_MSS_HORIZON']}")

        # Expectancy metrics
        avg_r  = mean(s["realized_r"] for s in signals) if signals else 0.0
        sum_r  = sum(s["realized_r"] for s in signals)
        pf     = profit_factor(signals)
        wr_raw = sum(1 for s in signals if _breakout_is_win(s)) / n if n else 0.0
        curve, peak, max_dd = equity_curve_r(signals)
        max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0.0

        # Per-trade Sharpe (periods_per_year=1.0 — no annualization, since
        # signal arrivals are event-driven not equally-spaced). This matches
        # validation.py's docstring guidance and López de Prado convention.
        r_series = [s["realized_r"] for s in signals]
        sr_whole = sharpe_ratio(r_series, periods_per_year=1.0) if r_series else 0.0
        config_sharpes.append(sr_whole)

        # 70/30 temporal OOS split
        train, test = temporal_70_30(signals)
        train_avg_r = mean(s["realized_r"] for s in train) if train else 0.0
        test_avg_r  = mean(s["realized_r"] for s in test) if test else 0.0
        train_wr    = sum(1 for s in train if _breakout_is_win(s)) / len(train) if train else 0.0
        test_wr     = sum(1 for s in test if _breakout_is_win(s)) / len(test) if test else 0.0
        train_pf    = profit_factor(train)
        test_pf     = profit_factor(test)

        # Walk-forward quarterly
        wf = walk_forward_quarterly(signals)

        # CPCV (skip if too few signals)
        cpcv = None
        if n >= 60:
            try:
                cpcv = cpcv_summary(
                    signals,
                    n_groups=10,
                    n_test_groups=2,
                    embargo_pct=0.01,
                    is_win_func=_breakout_is_win,
                    score_func=_breakout_win_score,
                    pnl_func=_breakout_pnl,
                    n_trials_for_dsr=N_TRIALS,
                )
            except Exception as e:
                cpcv = {"error": str(e)}

        # PSR vs SR=0 — fixed kwarg names (skew/kurtosis, not skewness/excess_kurtosis)
        psr = None
        if r_series and n >= 2:
            try:
                psr = probabilistic_sharpe_ratio(
                    sr_observed=sr_whole, n_returns=n,
                    skew=0.0, kurtosis=3.0, sr_benchmark=0.0,
                )
            except Exception as e:
                psr = None

        config_results.append({
            "run_id":             run["run_id"],
            "config":             c,
            "config_label":       cfg_label,
            "n":                  n,
            "avg_R":              round(avg_r, 4),
            "sum_R":              round(sum_r, 2),
            "profit_factor":      round(pf, 3) if pf != float("inf") else None,
            "max_drawdown_R":     round(max_dd, 2),
            "max_drawdown_pct":   round(max_dd_pct, 2),
            "equity_peak_R":      round(peak, 2),
            "wr":                 round(wr_raw, 4),
            "sharpe_whole":       round(sr_whole, 4),
            "psr":                round(psr, 4) if psr is not None else None,
            "train_avg_R":        round(train_avg_r, 4),
            "test_avg_R":         round(test_avg_r, 4),
            "train_wr":           round(train_wr, 4),
            "test_wr":            round(test_wr, 4),
            "train_pf":           round(train_pf, 3) if train_pf != float("inf") else None,
            "test_pf":            round(test_pf, 3) if test_pf != float("inf") else None,
            "n_train":            len(train),
            "n_test":             len(test),
            "walk_forward":       wf,
            "cpcv":               cpcv,
            "equity_curve_R":     curve,
        })

    # Compute honest DSR: deflate by n_trials=16 with std of config Sharpes
    sr_std_cross_config = pstdev(config_sharpes) if len(config_sharpes) > 1 else 0.0
    for r in config_results:
        sr_obs = r["sharpe_whole"]
        n = r["n"]
        if n >= 30 and sr_std_cross_config > 0:
            try:
                dsr = deflated_sharpe_ratio(
                    sr_observed=sr_obs, n_returns=n,
                    n_trials=N_TRIALS, sr_trial_std=sr_std_cross_config,
                    skew=0.0, kurtosis=3.0,
                )
                r["dsr"] = round(dsr, 4)
            except Exception as e:
                r["dsr"] = None
        else:
            r["dsr"] = None

    # ── Per-token expectancy (across all 16 configs) ────────────────────
    per_token = defaultdict(lambda: {"n": 0, "wins": 0, "sum_R": 0.0, "by_config": {}})
    for row in conn.execute("SELECT run_id, token, outcome, realized_r FROM backtest_signals"):
        d = dict(row)
        per_token[d["token"]]["n"] += 1
        if d["outcome"] in ("WIN", "PARTIAL_TP2"):
            per_token[d["token"]]["wins"] += 1
        per_token[d["token"]]["sum_R"] += d["realized_r"]

    per_token_rows = []
    for tok, info in sorted(per_token.items(), key=lambda x: -x[1]["sum_R"]):
        per_token_rows.append({
            "token":  tok,
            "n":      info["n"],
            "wr":     round(info["wins"] / info["n"], 4) if info["n"] else 0.0,
            "avg_R":  round(info["sum_R"] / info["n"], 4) if info["n"] else 0.0,
            "sum_R":  round(info["sum_R"], 2),
        })

    conn.close()

    # ── Output ─────────────────────────────────────────────────────────
    out = {
        "n_trials_for_dsr":        N_TRIALS,
        "sr_std_cross_config":     round(sr_std_cross_config, 4),
        "n_configs":               len(config_results),
        "total_signals_in_grid":   sum(r["n"] for r in config_results),
        "config_results":          config_results,
        "per_token":               per_token_rows,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n  Wrote: {OUT_PATH}")

    # ── Console summary ────────────────────────────────────────────────
    print()
    print("─" * 78)
    print("PER-CONFIG RESULTS — sorted by sum_R (total expectancy)")
    print("─" * 78)
    sorted_results = sorted(config_results, key=lambda r: -r["sum_R"])
    print(f"  {'#':>2}  {'n':>4}  {'avg_R':>6}  {'sum_R':>6}  {'PF':>5}  "
          f"{'maxDD':>5}  {'WR':>5}  {'Sh':>5}  {'PSR':>5}  {'DSR':>5}  "
          f"{'tr→te avg_R':>13}  cfg")
    print("  " + "─" * 100)
    for r in sorted_results:
        cfg = r["config"]
        cfg_short = (f"tp={cfg['BREAKOUT_TP1_RR']:.1f}R c2={cfg['H4_BREAKOUT_C2_LOOKBACK']} "
                     f"mss={cfg['H4_BREAKOUT_MSS_HORIZON']} buf={cfg['H4_BREAKOUT_CLOSE_BUFFER_PCT']:.3f}")
        pf_str  = f"{r['profit_factor']:.2f}" if r['profit_factor'] is not None else "inf"
        psr_str = f"{r['psr']:.2f}" if r['psr'] is not None else "  - "
        dsr_str = f"{r['dsr']:.2f}" if r['dsr'] is not None else "  - "
        train_test = f"{r['train_avg_R']:+.2f}→{r['test_avg_R']:+.2f}"
        print(f"  {r['run_id']:>2}  {r['n']:>4}  {r['avg_R']:>+6.3f}  "
              f"{r['sum_R']:>+6.1f}  {pf_str:>5}  {r['max_drawdown_R']:>5.1f}  "
              f"{r['wr']:.3f}  {r['sharpe_whole']:>+5.2f}  "
              f"{psr_str:>5}  {dsr_str:>5}  {train_test:>13}  {cfg_short}")

    print()
    print("─" * 78)
    print("PER-TOKEN (across all 16 configs)")
    print("─" * 78)
    print(f"  {'token':>6}  {'n':>5}  {'WR':>5}  {'avg_R':>6}  {'sum_R':>7}")
    print(f"  {'─'*6}  {'─'*5}  {'─'*5}  {'─'*6}  {'─'*7}")
    for r in per_token_rows:
        print(f"  {r['token']:>6}  {r['n']:>5}  {r['wr']:>.3f}  "
              f"{r['avg_R']:>+6.3f}  {r['sum_R']:>+7.1f}")

    print()
    print(f"  cross-config sr_std = {sr_std_cross_config:.4f} "
          f"(used for DSR deflation, n_trials={N_TRIALS})")
    print()
    print("Metrics complete.")


if __name__ == "__main__":
    analyze()
