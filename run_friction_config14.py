"""
run_friction_config14.py — Phase C-Breakout Step 2A.

Re-runs the WINNING grid configuration (Config 14:
tp=2.0/3.0/4.0R, c2=4, mss=30, buf=0.001) with execution.py's friction model
wired in. SAME config, SAME data, SAME detection logic — only adds:
  - spread (time-of-day + vol-conditioned)
  - execution latency (12s ± 8s, clamped [3, 60s])
  - partial fills (2% NO_FILL, 5% PARTIAL@50%, 93% FULL)
  - stale-price reject (>1.5× ATR move between signal and fill)
  - adverse selection (+5bps in TRENDING regimes)

Deterministic seed per signal via execution.derive_seed so the result is
reproducible. SAME `signals.db` is NEVER touched — friction results land in
the SAME data/breakout.db as Step 1, as a new backtest_run row.

DECISION DISCIPLINE — this is a SCREEN, not an optimization. ONE run.
Report whatever it shows. If the edge survives clearly, proceed to Step 2B
(paper soak). If it collapses, STOP — do not tune to rescue.

Regime classification: this harness defaults regime="UNKNOWN" which DISABLES
the +5bps adverse-selection cost. Reason: the full 1H regime detection chain
(detect_regime → ADX/efficiency/ATR-ratio) requires importing strategy modules
that open the live DB. Substituting a lightweight EMA-based regime classifier
here would itself be a new code path under test. We accept the slight friction
UNDER-estimate (+5bps is small vs the dominant spread + slip costs) and call
it out explicitly in the report. The decision rule does not depend on the
adverse-selection term.
"""
from __future__ import annotations

import bisect
import importlib
import json
import os
import sqlite3
import sys
import time as _time
from datetime import datetime
from pathlib import Path

_BREAKOUT_DIR = Path(__file__).resolve().parent
_TRADEAI_DIR  = Path("/home/tradeai/TradeAI")
sys.path.insert(0, str(_BREAKOUT_DIR))
sys.path.insert(0, str(_TRADEAI_DIR))

# Apply Config 14 BEFORE importing breakout_engine (env constants read at import)
CONFIG_14 = {
    "H4_BREAKOUT_CLOSE_BUFFER_PCT": 0.001,
    "BREAKOUT_TP1_RR":              2.0,
    "BREAKOUT_TP2_RR":              3.0,
    "BREAKOUT_TP3_RR":              4.0,
    "H4_BREAKOUT_C2_LOOKBACK":      4,
    "H4_BREAKOUT_MSS_HORIZON":      30,
}
for k, v in CONFIG_14.items():
    os.environ[k] = str(v)

import breakout_engine  # noqa: E402
from breakout_engine import detect_h4_breakout, compute_breakout_sl_tp  # noqa: E402
import breakout_backtest  # noqa: E402
from breakout_backtest import (  # noqa: E402
    load_ohlcv, check_outcome, compute_excursions, _calc_realized_r,
    open_breakout_db, compute_config_hash,
    TOKENS, FORWARD_BARS, H4_WINDOW_BUFFER, CRT_5M_WINDOW_SIZE,
    H4_BAR_DURATION_MS,
)
from crt_engine import compute_crt_trade_economics  # noqa: E402
from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT  # noqa: E402
from execution import simulate_execution, derive_seed  # noqa: E402


# ── ATR helpers (computed inline, no strategy-module imports) ─────────────
def _atr_14(highs, lows, closes, end_idx: int, n: int = 14) -> float:
    """Simple ATR over the last n bars ending at end_idx (exclusive of forward)."""
    if end_idx < n:
        return 0.0
    trs = []
    for i in range(end_idx - n, end_idx):
        if i <= 0:
            continue
        h, l, prev_c = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def _atr_ratio(highs, lows, closes, end_idx: int) -> float:
    """Current ATR / rolling 50-bar avg ATR. Returns 1.0 on insufficient data."""
    cur = _atr_14(highs, lows, closes, end_idx, n=14)
    if cur <= 0:
        return 1.0
    # Average of 4 historical ATR(14) windows ending at end_idx-15, -30, -45, -60
    longs = []
    for offset in (15, 30, 45, 60):
        long_atr = _atr_14(highs, lows, closes, max(0, end_idx - offset), n=14)
        if long_atr > 0:
            longs.append(long_atr)
    if not longs:
        return 1.0
    long_avg = sum(longs) / len(longs)
    if long_avg <= 0:
        return 1.0
    return cur / long_avg


# ── Per-token loop with friction ──────────────────────────────────────────
def run_breakout_token_friction(token: str, c5m: dict, c4h: dict) -> dict:
    """Run detection + outcome with execution.simulate_execution layered on.

    Returns dict with:
      signals_filled     : list of filled-and-traded signals
      signals_skipped    : count REJECTED by friction (no_fill + stale_move)
      signals_partial    : count PARTIAL (50% fill)
      n_attempted        : count of would-be signals before friction
      total_friction_R   : sum of "friction cost in R units" = (spread_pct - baseline_rt) / abs(net_sl_pct)
      stale_rejects      : count of stale_move rejections specifically
      no_fill_rejects    : count of no_fill rejections specifically
    """
    out = {
        "signals_filled":   [],
        "signals_skipped":  0,
        "signals_partial":  0,
        "n_attempted":      0,
        "total_friction_R": 0.0,
        "stale_rejects":    0,
        "no_fill_rejects":  0,
        "low_atr_skipped":  0,
    }
    if not c4h or not c5m:
        return out
    n5 = len(c5m["closes"])
    n4 = len(c4h["closes"])
    if n5 < FORWARD_BARS + 100 or n4 < 20:
        return out

    consumed: set = set()
    h4_window = breakout_engine.H4_BREAKOUT_C2_LOOKBACK + H4_WINDOW_BUFFER
    baseline_rt_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100  # in %

    for h4_end in range(h4_window, n4):
        h4_start = h4_end - h4_window
        c4h_win = {
            "opens":  c4h["opens"][h4_start:h4_end],
            "highs":  c4h["highs"][h4_start:h4_end],
            "lows":   c4h["lows"][h4_start:h4_end],
            "closes": c4h["closes"][h4_start:h4_end],
            "times":  c4h["times"][h4_start:h4_end],
        }
        h4_open_time_ms  = c4h["times"][h4_end - 1]
        h4_close_time_ms = h4_open_time_ms + H4_BAR_DURATION_MS
        c5m_end_idx = bisect.bisect_right(c5m["times"], h4_close_time_ms)
        c5m_end_idx = min(c5m_end_idx + breakout_engine.H4_BREAKOUT_MSS_HORIZON + 10, n5)
        c5m_start_idx = max(0, c5m_end_idx - CRT_5M_WINDOW_SIZE)
        if c5m_end_idx - c5m_start_idx < 30:
            continue
        c5m_win = {
            "opens":  c5m["opens"][c5m_start_idx:c5m_end_idx],
            "highs":  c5m["highs"][c5m_start_idx:c5m_end_idx],
            "lows":   c5m["lows"][c5m_start_idx:c5m_end_idx],
            "closes": c5m["closes"][c5m_start_idx:c5m_end_idx],
            "times":  c5m["times"][c5m_start_idx:c5m_end_idx],
        }

        setup = detect_h4_breakout(c4h_win, c5m_win, token=token, consumed=consumed)
        if setup is None:
            continue
        consumed.add(setup["key"])

        mss_bar_abs = c5m_start_idx + setup["mss_bar_5m"]
        if mss_bar_abs >= n5 - FORWARD_BARS - 1:
            continue
        entry_bar = mss_bar_abs + 1
        if entry_bar >= n5 - FORWARD_BARS - 1:
            continue
        intended_entry = c5m["opens"][entry_bar]
        direction = setup["direction"]

        # Compute SL/TP with intended entry (the bot's plan)
        sl_tp = compute_breakout_sl_tp(
            direction, intended_entry, setup["sl_anchor"],
            setup["c1_high"], setup["c1_low"],
        )
        if sl_tp is None:
            continue
        sl_price, tp1_price, tp2_price, tp3_price = sl_tp

        # APPLY THE SAME BEW / fees_kill / MAX_SL_PCT GATE the grid applied
        # at signal time (compute_crt_trade_economics). The bot would NOT have
        # emitted this signal if the gate didn't pass at intended_entry. We
        # need this here so n_attempted is the same population the original
        # Config 14 produced.
        rt_baseline_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
        gate_econ = compute_crt_trade_economics(
            direction, intended_entry, sl_price,
            tp1_price, tp2_price, tp3_price,
            outcome=None, rt_cost_pct=rt_baseline_pct,
        )
        if gate_econ is None:
            continue  # Same rejection path as the original grid

        out["n_attempted"] += 1

        # Compute ATR for the execution model
        atr_5m = _atr_14(c5m["highs"], c5m["lows"], c5m["closes"], mss_bar_abs, n=14)
        if atr_5m <= 0:
            out["low_atr_skipped"] += 1
            continue
        atr_r = _atr_ratio(c5m["highs"], c5m["lows"], c5m["closes"], mss_bar_abs)

        # Signal time = close of MSS bar (when the bot would emit the alert)
        signal_ts = datetime.utcfromtimestamp(c5m["times"][mss_bar_abs] / 1000)
        signal_price = c5m["closes"][mss_bar_abs]
        next_bar_open = c5m["opens"][entry_bar]
        seed = derive_seed(signal_ts, token, direction)

        # Apply execution friction.
        # Regime="UNKNOWN" disables +5bps adverse-selection (under-estimate;
        # documented in module docstring).
        exec_result = simulate_execution(
            signal_ts=signal_ts,
            signal_price=signal_price,
            next_bar_open=next_bar_open,
            token=token,
            direction=direction,
            regime="UNKNOWN",
            atr_5m=atr_5m,
            atr_ratio=atr_r,
            seed=seed,
        )
        if exec_result.status == "REJECTED":
            out["signals_skipped"] += 1
            if exec_result.reason == "no_fill":
                out["no_fill_rejects"] += 1
            elif exec_result.reason == "stale_move":
                out["stale_rejects"] += 1
            continue
        if exec_result.status == "PARTIAL":
            out["signals_partial"] += 1

        actual_entry = exec_result.fill_price
        fill_size = exec_result.fill_size_pct
        total_cost_pct = exec_result.total_cost_pct * 100  # convert fraction→pct
        # Friction cost as PCT (spread + adverse_sel), comparable to baseline_rt_pct
        # Baseline rt was already counted in compute_crt_trade_economics; here we
        # use total_cost_pct as the ACTUAL friction (which may be higher than baseline).

        # Forward outcome from actual fill — SL/TP price levels unchanged.
        future = [
            {"h": c5m["highs"][j], "l": c5m["lows"][j]}
            for j in range(entry_bar + 1, min(entry_bar + 1 + FORWARD_BARS, n5))
        ]
        if not future:
            continue
        outcome, tp_reached = check_outcome(
            direction, sl_price, tp1_price, tp2_price, tp3_price, future,
        )

        # Recompute gross %s from ACTUAL fill (not intended entry).
        if direction == "BUY":
            gross_tp1 = (tp1_price - actual_entry) / actual_entry * 100
            gross_tp2 = (tp2_price - actual_entry) / actual_entry * 100
            gross_tp3 = (tp3_price - actual_entry) / actual_entry * 100
            gross_sl  = (sl_price  - actual_entry) / actual_entry * 100
        else:
            gross_tp1 = (actual_entry - tp1_price) / actual_entry * 100
            gross_tp2 = (actual_entry - tp2_price) / actual_entry * 100
            gross_tp3 = (actual_entry - tp3_price) / actual_entry * 100
            gross_sl  = (actual_entry - sl_price)  / actual_entry * 100

        # net = gross - friction_cost (using execution model's cost, not baseline)
        net_tp1 = round(gross_tp1 - total_cost_pct, 3)
        net_tp2 = round(gross_tp2 - total_cost_pct, 3)
        net_tp3 = round(gross_tp3 - total_cost_pct, 3)
        net_sl  = round(gross_sl  - total_cost_pct, 2)

        # R-multiple realised under split-exit, then scaled by fill_size_pct
        realized_r_clean = _calc_realized_r(outcome, net_tp1, net_sl, net_tp2, net_tp3)
        realized_r = realized_r_clean * fill_size  # half-size partial = half R contribution

        # Account for the friction COST in R units (for reporting)
        friction_cost_R = (total_cost_pct - baseline_rt_pct) / abs(net_sl) if net_sl else 0.0
        out["total_friction_R"] += friction_cost_R

        ts_str = signal_ts.strftime("%Y-%m-%d %H:%M:%S")
        h_hour = signal_ts.hour
        if 13 <= h_hour < 17:
            session = "NY_AM_KZ"
        elif 2 <= h_hour < 6:
            session = "LONDON_KZ"
        elif 20 <= h_hour < 24:
            session = "ASIA_KZ"
        elif 0 <= h_hour < 6:
            session = "ASIA_EARLY"
        else:
            session = "OVERNIGHT"

        # NOTE: do NOT pass through compute_crt_trade_economics' BEW gate —
        # the bot already passed that at signal generation; the friction
        # affects realized economics, not the gate at signal time.
        rr1 = round(abs(gross_tp1 / gross_sl), 2) if gross_sl != 0 else 0
        net_rr1 = round(net_tp1 / abs(net_sl), 2) if net_sl != 0 else 0

        out["signals_filled"].append({
            "token":              token,
            "signal":             direction,
            "price":              round(actual_entry, 6),
            "intended_entry":     round(intended_entry, 6),
            "slip_pct":           round((actual_entry - intended_entry) / intended_entry * 100, 4),
            "ts":                 ts_str,
            "confidence":         6 + (2 if setup["confluence"]["type"] == "OB" else 1),
            "sweep_type":         setup["type"],
            "session":            session,
            "hour_utc":           h_hour,
            "day_of_week":        signal_ts.weekday(),
            "mss_quality":        setup["mss_quality"],
            "fvg_quality":        (setup["confluence"]["details"].get("quality", "NONE")
                                   if setup["confluence"]["type"] == "FVG" else "NONE"),
            "entry_type":         f"H4_BREAKOUT_{setup['confluence']['type']}_FRICTION",
            "tp1_pct":            round(gross_tp1, 3),
            "sl_pct":             round(gross_sl, 3),
            "net_tp1_pct":        net_tp1,
            "net_tp2_pct":        net_tp2,
            "net_tp3_pct":        net_tp3,
            "net_sl_pct":         net_sl,
            "rr1":                rr1,
            "net_rr1":            net_rr1,
            "breakeven_wr":       0.0,  # not re-computed under friction
            "tp_reached":         tp_reached,
            "outcome":            outcome,
            "realized_r":         round(realized_r, 4),
            "realized_r_clean":   round(realized_r_clean, 4),  # what it WOULD have been at full size
            "fill_size_pct":      fill_size,
            "exec_status":        exec_result.status,
            "exec_latency_sec":   round(exec_result.latency_sec, 1),
            "exec_total_cost_pct": round(total_cost_pct, 4),
            "exec_friction_cost_R": round(friction_cost_R, 4),
            "mfe_pct":            0.0,
            "mae_pct":            0.0,
            "source":             "H4_BREAKOUT_FRICTION",
        })

    return out


def persist_friction_run(conn, config: dict, per_token: dict, elapsed_sec: float) -> int:
    """Persist friction run as a backtest_run row + per-signal backtest_signals rows."""
    all_filled = [s for d in per_token.values() for s in d["signals_filled"]]
    n_filled = len(all_filled)
    n_attempted = sum(d["n_attempted"] for d in per_token.values())
    n_rejected = sum(d["signals_skipped"] for d in per_token.values())
    n_partial = sum(d["signals_partial"] for d in per_token.values())
    n_stale = sum(d["stale_rejects"] for d in per_token.values())
    n_no_fill = sum(d["no_fill_rejects"] for d in per_token.values())
    n_low_atr = sum(d["low_atr_skipped"] for d in per_token.values())

    n_wins = sum(1 for s in all_filled if s["outcome"] in ("WIN", "PARTIAL_TP2"))
    n_p1   = sum(1 for s in all_filled if s["outcome"] == "PARTIAL_TP1")
    overall_wr = (n_wins + 0.5 * n_p1) / n_filled if n_filled else 0.0
    avg_rr = (sum(s["rr1"] for s in all_filled) / n_filled) if n_filled else 0.0
    config_hash = compute_config_hash(config)
    run_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    sum_R = sum(s["realized_r"] for s in all_filled)
    sum_R_clean = sum(s["realized_r_clean"] for s in all_filled)
    summary = json.dumps({
        "config":             config,
        "label":              "FRICTION_CONFIG_14",
        "n_attempted":        n_attempted,
        "n_filled":           n_filled,
        "n_partial":          n_partial,
        "n_rejected_total":   n_rejected,
        "n_rejected_no_fill": n_no_fill,
        "n_rejected_stale":   n_stale,
        "n_skipped_low_atr":  n_low_atr,
        "overall_wr":         round(overall_wr, 4),
        "avg_rr":             round(avg_rr, 4),
        "avg_R_per_filled":   round(sum_R / n_filled, 4) if n_filled else 0,
        "avg_R_per_attempted": round(sum_R / n_attempted, 4) if n_attempted else 0,
        "sum_R":              round(sum_R, 4),
        "sum_R_if_no_friction": round(sum_R_clean, 4),
        "avg_friction_cost_R": round(sum(d["total_friction_R"] for d in per_token.values()) / n_filled, 4) if n_filled else 0,
        "by_token":           {tok: d["n_attempted"] for tok, d in per_token.items()},
        "elapsed_sec":        round(elapsed_sec, 2),
    }, sort_keys=True)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO backtest_runs (run_date, days, total_signals, overall_wr, "
        "avg_rr, status, summary, config_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_date, 365, n_filled, overall_wr, avg_rr, "DONE", summary, config_hash),
    )
    run_id = cur.lastrowid

    for s in all_filled:
        cur.execute(
            "INSERT INTO backtest_signals "
            "(run_id, token, signal, price, ts, confidence, "
            " tp1_pct, sl_pct, rr1, tp_reached, outcome, "
            " net_tp1_pct, net_sl_pct, net_rr1, breakeven_wr, "
            " sweep_type, session, hour_utc, day_of_week, mss_quality, "
            " fvg_quality, entry_type, mfe_pct, mae_pct, realized_r, "
            " net_tp2_pct, net_tp3_pct, source) "
            "VALUES (?, ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?, "
            "        ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?, ?, "
            "        ?, ?, ?)",
            (run_id, s["token"], s["signal"], s["price"], s["ts"], s["confidence"],
             s["tp1_pct"], s["sl_pct"], s["rr1"], s["tp_reached"], s["outcome"],
             s["net_tp1_pct"], s["net_sl_pct"], s["net_rr1"], s["breakeven_wr"],
             s["sweep_type"], s["session"], s["hour_utc"], s["day_of_week"], s["mss_quality"],
             s["fvg_quality"], s["entry_type"], s["mfe_pct"], s["mae_pct"], s["realized_r"],
             s["net_tp2_pct"], s["net_tp3_pct"], s["source"]),
        )
    conn.commit()
    return run_id


def main():
    print("=" * 78)
    print("PHASE C-BREAKOUT STEP 2A — FRICTION RE-RUN (Config 14)")
    print("=" * 78)
    print(f"  Config: {CONFIG_14}")
    print(f"  Friction defaults from execution.py (all env-overridable):")
    print(f"    NO_FILL_PROB        = 2%")
    print(f"    PARTIAL_FILL_PROB   = 5% @ 50% size")
    print(f"    LATENCY_MEAN_SEC    = 12 (sigma 8, clamped [3, 60])")
    print(f"    STALE_ATR_MULT      = 1.5 (signal-to-fill move > 1.5x ATR → reject)")
    print(f"    ADVERSE_SELECT_COST = 0.05% (DISABLED here via regime=UNKNOWN)")
    print(f"    Spread = TOKEN_RT_COST × time_mult × vol_mult")
    print()

    conn = open_breakout_db()
    t0 = _time.time()
    per_token = {}
    for tok in TOKENS:
        c5m = load_ohlcv(tok, "5m")
        c4h = load_ohlcv(tok, "4h")
        if c5m is None or c4h is None:
            per_token[tok] = {
                "signals_filled": [], "signals_skipped": 0,
                "signals_partial": 0, "n_attempted": 0,
                "total_friction_R": 0, "stale_rejects": 0,
                "no_fill_rejects": 0, "low_atr_skipped": 0,
            }
            continue
        per_token[tok] = run_breakout_token_friction(tok, c5m, c4h)
        d = per_token[tok]
        print(f"  {tok:>5}: attempted={d['n_attempted']:>4}  filled={len(d['signals_filled']):>4}  "
              f"partial={d['signals_partial']:>2}  reject_no_fill={d['no_fill_rejects']:>2}  "
              f"reject_stale={d['stale_rejects']:>2}")

    elapsed = _time.time() - t0

    run_id = persist_friction_run(conn, CONFIG_14, per_token, elapsed)
    conn.close()

    print(f"\n  Persisted run_id={run_id}, elapsed={elapsed:.1f}s")
    print("\nNext: python3 compare_friction.py")


if __name__ == "__main__":
    main()
