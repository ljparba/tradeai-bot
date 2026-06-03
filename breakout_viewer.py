"""
breakout_viewer.py — Read-only side-by-side dashboard for the Breakout paper soaks.

Renders BOTH:
  - Soak A (5M / 4H) — source='H4_BREAKOUT_PAPER_SOAK', heartbeat data/breakout_soak_heartbeat.json
  - Soak B (5M / 1H) — source='H4_BREAKOUT_PAPER_SOAK_B', heartbeat data/breakout_soak_B_heartbeat.json

Both columns show: gate progress (n vs 30), each of the 5 locked criteria
PASS/FAIL/PENDING, soak health, n-vs-expectancy drift, per-token table,
open positions, recent closed signals.

For each soak the locked gate is IDENTICAL (the operator chose to apply the
same five criteria to both):
    avg_R per closed signal ≥ +0.40
    profit factor ≥ 2.0
    WR strict ≥ 58%  (positive-R-close rate; recalibrated 2026-06-03 for BE-after-TP1 model)
    max drawdown ≤ 20 R
    no per-token blowup
    n closed ≥ 30 before any verdict (PENDING until then)

Per-soak FRICTION-ON BACKTEST REFERENCE (informational, NOT a gate; updated
2026-06-03 to the NEW BE-after-TP1 model — PHASE_C_FULL_AUDIT_V2.md):
    A: +0.4536 avg_R (TF_A 720d FRICTION NEW)
    B: +0.4840 avg_R (TF_B 720d FRICTION NEW)
    (the old +0.616 / +0.549 numbers were under the prior "ignore-SL-after-TP1"
     model and are not portable to live execution.)

For B specifically, also displays tracking-only metrics (sum_R, R/day) clearly
marked as NOT part of the verdict, so the operator can judge B's
volume-based profile fairly even if WR underperforms (see
TF_B_SOAK_PRE_REGISTER.md §4 caveat).

INVARIANTS:
  - Opens both DB connections with file:...?mode=ro (write attempts raise at
    the SQLite C level).
  - Localhost-only bind, port 8890.
  - Fresh connection per request.
  - HTTP write methods → 405.
  - Filters by source label per soak; A and B never blend in the gate math.

To run:
    cd /home/tradeai/breakout-work
    python3 breakout_viewer.py
    # → http://127.0.0.1:8890
    # Ctrl+C to stop.

If a previous viewer is already running on 8890, kill it first:
    pkill -f "python3 breakout_viewer.py"
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import sqlite3
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

_BREAKOUT_DIR = Path(__file__).resolve().parent
DB_PATH = _BREAKOUT_DIR / "data" / "breakout.db"

HOST = "127.0.0.1"
PORT = 8890

# Locked thresholds — IDENTICAL for both A and B
GATE_N_TARGET           = 30
GATE_AVG_R_MIN          = 0.40
GATE_PF_MIN             = 2.0
GATE_WR_MIN             = 0.58    # RECALIBRATED 2026-06-03 for BE-after-TP1 model.
                                  # New WR def: positive-R-close rate (counts PARTIAL_TP1_BE as win since R>0).
                                  # Backtest WR under new def: TF_A 68.25%, TF_B 70.63% (avg 69.44%).
                                  # Original buffer: 11pp below backtest (old WR 0.55 vs old avg 66%).
                                  # Applied: 69.44% - 11pp = 58.44% → 0.58 (clean round).
                                  # TF_A effective buffer: 10.25pp, TF_B: 12.63pp — within original principle.
GATE_MAX_DD_R           = 20.0
GATE_PER_TOKEN_MIN_N    = 5
GATE_PER_TOKEN_BLOWUP_WR = 0.35

# Sanity-check thresholds — DISPLAY-ONLY (NOT verdict-affecting).
# Pulled from config.py defaults (MAX_SL_PCT=0.03) and ict_engine.py defaults
# (ICT_MIN_RR_GATE=1.3). If a signal's geometry violates these, the viewer
# tags it with a visual flag so the operator can eyeball it. The gate at
# signal-emit time SHOULD have rejected such setups (the soak calls
# compute_crt_trade_economics which enforces these); a flag here would
# indicate a possible geometry bug worth investigating.
SANITY_MAX_SL_PCT       = 0.030   # structural SL ceiling (3% of entry)
SANITY_MIN_TP1_RR       = 1.3     # ICT_MIN_RR_GATE — TP1 must be ≥1.3× SL distance

# Per-soak descriptors. Order = display order (left → right).
SOAKS = [
    {
        "key":          "A",
        "label":        "Soak A — 5M / 4H",
        "soak_label":   "H4_BREAKOUT_PAPER_SOAK",
        "heartbeat":    _BREAKOUT_DIR / "data" / "breakout_soak_heartbeat.json",
        "pid_file":     _BREAKOUT_DIR / "data" / "breakout_soak.pid",
        "ref_avg_R":    0.4536,  # friction-on backtest reference (NEW model, NOT a gate; 2026-06-03)
        "ref_source":   "PHASE_C_STEP2A_FRICTION.md",
    },
    {
        "key":          "B",
        "label":        "Soak B — 5M / 1H",
        "soak_label":   "H4_BREAKOUT_PAPER_SOAK_B",
        "heartbeat":    _BREAKOUT_DIR / "data" / "breakout_soak_B_heartbeat.json",
        "pid_file":     _BREAKOUT_DIR / "data" / "breakout_soak_B.pid",
        "ref_avg_R":    0.4840,  # friction-on backtest reference (NEW model, NOT a gate; 2026-06-03)
        "ref_source":   "PHASE_C_TIMEFRAME_COMPARISON.md",
    },
]


def _open_ro_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"breakout.db missing at {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _profit_factor(rs):
    w = sum(r for r in rs if r and r > 0)
    l = sum(abs(r) for r in rs if r and r < 0)
    if l <= 0:
        return float("inf") if w > 0 else 0.0
    return w / l


def _max_drawdown_R(rs):
    cum, peak, mdd = 0.0, 0.0, 0.0
    for r in rs:
        if r is None: continue
        cum += r
        if cum > peak: peak = cum
        if peak - cum > mdd: mdd = peak - cum
    return mdd, cum, peak


def _cumulative_avg_R_series(rs):
    out, cum = [], 0.0
    for i, r in enumerate(rs, start=1):
        if r is None: r = 0.0
        cum += r
        out.append({"n": i, "cum_R": round(cum, 3),
                     "cum_avg_R": round(cum / i, 4)})
    return out


def _gate_status(threshold_check: bool, n_signals: int) -> str:
    if n_signals < GATE_N_TARGET:
        return "PENDING"
    return "PASS" if threshold_check else "FAIL"


def _enrich_geometry(d: dict) -> dict:
    """Add SL/TP distance %, R:R, and sanity-check flags to a signal dict.

    DISPLAY-ONLY. The flags are observational; they do NOT affect the locked
    verdict. They surface geometry that SHOULD have been caught by the
    soak's compute_crt_trade_economics gate at signal-emit time.

    Computes (all signed by direction):
      sl_dist_pct  : |SL − entry| / entry × 100   (always ≥0; magnitude)
      tp1_dist_pct : |TP1 − entry| / entry × 100
      tp2_dist_pct : |TP2 − entry| / entry × 100
      tp3_dist_pct : |TP3 − entry| / entry × 100
      rr_tp1       : tp1_dist_pct / sl_dist_pct  (None if sl_dist_pct ≤ 0)
      rr_tp2 / rr_tp3 same shape

    Sanity flags (each True/False; the dict also has a comma-joined
    `sanity_flags_str` for compact display):
      sl_too_wide          : sl_dist_pct > SANITY_MAX_SL_PCT × 100
      tp1_rr_below_floor   : rr_tp1 < SANITY_MIN_TP1_RR
      direction_inconsistent : BUY with SL above entry, or BUY with TP below
                              entry, or SELL with SL below entry, or SELL
                              with TP above entry — geometry bug indicator
    """
    entry = d.get("entry_price")
    sl = d.get("sl")
    tp1 = d.get("tp1")
    tp2 = d.get("tp2")
    tp3 = d.get("tp3")
    direction = d.get("direction")

    out = dict(d)  # don't mutate the input
    flags = []

    if not entry or entry <= 0 or sl is None or tp1 is None:
        # Degenerate — can't compute geometry; just return original
        out["sl_dist_pct"] = None
        out["tp1_dist_pct"] = None
        out["tp2_dist_pct"] = None
        out["tp3_dist_pct"] = None
        out["rr_tp1"] = None
        out["rr_tp2"] = None
        out["rr_tp3"] = None
        out["sanity_flags"] = []
        out["sanity_flags_str"] = ""
        return out

    sl_dist_pct = abs(sl - entry) / entry * 100
    tp1_dist_pct = abs(tp1 - entry) / entry * 100 if tp1 is not None else None
    tp2_dist_pct = abs(tp2 - entry) / entry * 100 if tp2 is not None else None
    tp3_dist_pct = abs(tp3 - entry) / entry * 100 if tp3 is not None else None

    rr_tp1 = tp1_dist_pct / sl_dist_pct if (sl_dist_pct > 0 and tp1_dist_pct is not None) else None
    rr_tp2 = tp2_dist_pct / sl_dist_pct if (sl_dist_pct > 0 and tp2_dist_pct is not None) else None
    rr_tp3 = tp3_dist_pct / sl_dist_pct if (sl_dist_pct > 0 and tp3_dist_pct is not None) else None

    # ── Sanity flags ─────────────────────────────────────────────────────
    if sl_dist_pct > SANITY_MAX_SL_PCT * 100:
        flags.append("sl_too_wide")

    if rr_tp1 is not None and rr_tp1 < SANITY_MIN_TP1_RR:
        flags.append("tp1_rr_below_floor")

    # Direction/level consistency: for BUY, SL must be BELOW entry, TPs ABOVE
    # entry. For SELL, SL must be ABOVE entry, TPs BELOW entry. Any other
    # arrangement is a geometry bug.
    if direction == "BUY":
        if sl >= entry:
            flags.append("buy_sl_above_entry")
        if tp1 is not None and tp1 <= entry:
            flags.append("buy_tp1_below_entry")
        if tp2 is not None and tp2 <= entry:
            flags.append("buy_tp2_below_entry")
        if tp3 is not None and tp3 <= entry:
            flags.append("buy_tp3_below_entry")
    elif direction == "SELL":
        if sl <= entry:
            flags.append("sell_sl_below_entry")
        if tp1 is not None and tp1 >= entry:
            flags.append("sell_tp1_above_entry")
        if tp2 is not None and tp2 >= entry:
            flags.append("sell_tp2_above_entry")
        if tp3 is not None and tp3 >= entry:
            flags.append("sell_tp3_above_entry")

    # Tier-vs-outcome sanity (closed rows only — open rows have no tp_hit/result).
    # With the F-exit-fix in place the SL-after-TP1 BE-stop guard means a runner
    # that reached TP2 then reversed stays PARTIAL_TP2; it cannot become LOSS.
    # If this combination ever appears, it's a logic inconsistency between the
    # tier flags and the outcome label — display-only flag, never affects verdict.
    tp1_hit = d.get("tp1_hit")
    tp2_hit = d.get("tp2_hit")
    tp3_hit = d.get("tp3_hit")
    result_label = d.get("result")
    if result_label == "LOSS" and (tp2_hit == 1 or tp3_hit == 1):
        flags.append("tier_outcome_inconsistent")
    if result_label == "LOSS" and tp1_hit == 1:
        flags.append("tp1_hit_but_loss")

    out["sl_dist_pct"] = round(sl_dist_pct, 4)
    out["tp1_dist_pct"] = round(tp1_dist_pct, 4) if tp1_dist_pct is not None else None
    out["tp2_dist_pct"] = round(tp2_dist_pct, 4) if tp2_dist_pct is not None else None
    out["tp3_dist_pct"] = round(tp3_dist_pct, 4) if tp3_dist_pct is not None else None
    out["rr_tp1"] = round(rr_tp1, 3) if rr_tp1 is not None else None
    out["rr_tp2"] = round(rr_tp2, 3) if rr_tp2 is not None else None
    out["rr_tp3"] = round(rr_tp3, 3) if rr_tp3 is not None else None
    out["sanity_flags"] = flags
    out["sanity_flags_str"] = ",".join(flags)
    return out


def _days_elapsed_since(ts_str):
    """Days elapsed from a 'YYYY-MM-DD HH:MM:SS' UTC string to now."""
    if not ts_str:
        return 0.0
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return max(0.001, (datetime.now(timezone.utc).replace(tzinfo=None) - dt).total_seconds() / 86400)
    except (ValueError, TypeError):
        return 0.001


def collect_one_soak(spec: dict) -> dict:
    """Build a state snapshot for ONE soak. Filtered to its source label only."""
    out = {
        "key":       spec["key"],
        "label":     spec["label"],
        "soak_label": spec["soak_label"],
        "ref_avg_R": spec["ref_avg_R"],
        "ref_source": spec["ref_source"],
        "gate": {
            "n_target":              GATE_N_TARGET,
            "avg_R_min":             GATE_AVG_R_MIN,
            "pf_min":                GATE_PF_MIN,
            "wr_min":                GATE_WR_MIN,
            "max_dd_R_cap":          GATE_MAX_DD_R,
            "per_token_min_n":       GATE_PER_TOKEN_MIN_N,
            "per_token_blowup_wr":   GATE_PER_TOKEN_BLOWUP_WR,
        },
        "soak_health": {},
        "metrics":     {},
        "gate_eval":   {},
        "per_token":   [],
        "drift":       [],
        "open":        [],
        "closed":      [],
        "tracking":    {},     # observational, not part of verdict
        "verdict_overall": "PENDING",
    }

    # Heartbeat
    try:
        hb_path = spec["heartbeat"]
        if hb_path.exists():
            hb = json.loads(hb_path.read_text())
            age_s = max(0.0, _time.time() - float(hb.get("ts_unix") or 0))
            out["soak_health"] = {
                "heartbeat_ts_utc": hb.get("ts_utc"),
                "heartbeat_age_s":  round(age_s, 1),
                "pid":              hb.get("pid"),
                "cycle":            hb.get("cycle"),
                "open_signals":     hb.get("open_signals"),
                "closed_signals":   hb.get("closed_signals"),
                "last_signal_ts":   hb.get("last_signal_ts"),
                "ref_tf":           hb.get("ref_tf"),
                "entry_tf":         hb.get("entry_tf"),
                "status":           "STALE" if age_s > 300 else "OK",
            }
        else:
            out["soak_health"] = {"status": "NO_HEARTBEAT"}
    except (json.JSONDecodeError, ValueError) as e:
        out["soak_health"] = {"status": f"HEARTBEAT_ERROR: {e!r}"}
    try:
        pf = spec["pid_file"]
        out["soak_health"]["pid_file"] = int(pf.read_text().strip()) if pf.exists() else None
    except (ValueError, OSError):
        out["soak_health"]["pid_file"] = None

    # DB
    try:
        conn = _open_ro_conn()
    except FileNotFoundError:
        out["error"] = "breakout.db missing"
        return out

    try:
        label = spec["soak_label"]

        closed_rows = list(conn.execute(
            "SELECT s.id AS sid, s.token, s.signal AS direction, "
            "       s.timestamp AS opened_ts, s.entry_price, s.sl, s.tp1, s.tp2, s.tp3, "
            "       s.sweep_type, s.session, s.entry_type, "
            "       r.result, r.realized_r, r.closed_at, r.profit_pct, "
            # Tier-progression flags (DISPLAY-ONLY — read straight from results table).
            "       r.tp1_hit, r.tp2_hit, r.tp3_hit, r.sl_hit "
            "FROM signals s JOIN results r ON r.signal_id = s.id "
            "WHERE s.source = ? AND s.status = 'CLOSED' "
            "ORDER BY r.closed_at", (label,),
        ))
        # _enrich_geometry adds sl_dist_pct / tp{1,2,3}_dist_pct / rr_tp{1,2,3}
        # + sanity_flags (DISPLAY-ONLY, never affects verdict).
        closed = [_enrich_geometry(dict(r)) for r in closed_rows]
        out["closed"] = closed

        open_rows = list(conn.execute(
            "SELECT id, token, signal AS direction, entry_price, sl, tp1, tp2, tp3, "
            "       timestamp AS opened_ts, expires_at, sweep_type, session, entry_type "
            "FROM signals WHERE source = ? AND status = 'OPEN' "
            "ORDER BY timestamp", (label,),
        ))
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        open_sigs = []
        for r in open_rows:
            d = dict(r)
            try:
                ts = datetime.strptime(d["opened_ts"], "%Y-%m-%d %H:%M:%S")
                d["age_minutes"] = round((now_utc - ts).total_seconds() / 60, 1)
            except (ValueError, TypeError):
                d["age_minutes"] = None
            # Add geometry detail + sanity flags (DISPLAY-ONLY)
            d = _enrich_geometry(d)
            open_sigs.append(d)
        out["open"] = open_sigs

        n = len(closed)
        realized_rs = [r["realized_r"] for r in closed]
        # WR DEFINITION (2026-06-03, BE-after-TP1 model):
        # Win = any close with positive realized_R (counts WIN, PARTIAL_TP2, AND
        # PARTIAL_TP1_BE because the BE-stop runner with friction-positive R is
        # a profitable close under the new exit model). LOSS and EXPIRED(R≤0)
        # and any rare R-zero / R-negative PARTIAL_TP1 (extreme friction edge
        # cases) are NOT wins. See PHASE_C_FULL_AUDIT_V2.md §7.3 for derivation.
        n_pos     = sum(1 for r in closed if (r["realized_r"] or 0) > 0)
        n_wins_p2 = sum(1 for r in closed if r["result"] in ("WIN", "PARTIAL_TP2"))  # kept for n_wins display
        n_p1      = sum(1 for r in closed if r["result"] == "PARTIAL_TP1")
        wr_raw    = n_pos / n if n else 0.0
        avg_r     = sum(realized_rs) / n if n else 0.0
        sum_r     = sum(realized_rs)
        pf        = _profit_factor(realized_rs)
        mdd, cum, peak = _max_drawdown_R(realized_rs)

        out["metrics"] = {
            "n_closed":       n,
            "n_open":         len(open_sigs),
            "avg_R":          round(avg_r, 4),
            "sum_R":          round(sum_r, 3),
            "profit_factor":  round(pf, 4) if pf != float("inf") else None,
            "win_rate":       round(wr_raw, 4),
            "max_drawdown_R": round(mdd, 3),
            "equity_peak_R":  round(peak, 3),
            "equity_curve_R": round(cum, 3),
            "n_wins":         n_wins_p2,
            "n_partial_tp1":  n_p1,
            "n_losses":       sum(1 for r in closed if r["result"] == "LOSS"),
            "n_expired":      sum(1 for r in closed if r["result"] == "EXPIRED"),
            "progress_pct":   round(n / GATE_N_TARGET * 100, 1),
        }

        # Tracking-only metrics (NOT in verdict)
        first_signal_ts = None
        first_rows = list(conn.execute(
            "SELECT timestamp FROM signals WHERE source = ? "
            "ORDER BY id ASC LIMIT 1", (label,)))
        if first_rows:
            first_signal_ts = first_rows[0]["timestamp"]
        days_elapsed = _days_elapsed_since(first_signal_ts) if first_signal_ts else 0.001
        out["tracking"] = {
            "sum_R":              round(sum_r, 3),
            "R_per_day":          round(sum_r / days_elapsed, 4) if days_elapsed else 0,
            "days_elapsed":       round(days_elapsed, 2),
            "first_signal_ts":    first_signal_ts,
            "ref_avg_R_friction": spec["ref_avg_R"],
            "ref_source":         spec["ref_source"],
            "note": "Observational only — NOT part of verdict. See TF_B_SOAK_PRE_REGISTER.md §4 (B) and PHASE_C_STEP2B_SOAK_STARTED.md §1 (A).",
        }

        # Gate eval
        avg_r_pass  = avg_r >= GATE_AVG_R_MIN
        pf_pass     = (pf >= GATE_PF_MIN) if pf != float("inf") else True
        wr_pass     = wr_raw >= GATE_WR_MIN
        max_dd_pass = mdd <= GATE_MAX_DD_R

        per_token_map = {}
        for r in closed:
            per_token_map.setdefault(r["token"], []).append(r["realized_r"])
        per_token_rows = []
        any_blowup = False
        for tok in sorted(per_token_map.keys()):
            rs = per_token_map[tok]
            n_tok = len(rs)
            # WR DEFINITION (2026-06-03): positive-R-close rate (see overall WR comment).
            tok_wins = sum(1 for r in closed
                            if r["token"] == tok and (r["realized_r"] or 0) > 0)
            tok_wr = tok_wins / n_tok if n_tok else 0.0
            tok_avg = sum(rs) / n_tok if n_tok else 0.0
            tok_sum = sum(rs)
            tok_pf = _profit_factor(rs)
            blowup = (n_tok >= GATE_PER_TOKEN_MIN_N
                       and tok_wr <= GATE_PER_TOKEN_BLOWUP_WR
                       and tok_avg < 0)
            if blowup: any_blowup = True
            per_token_rows.append({
                "token":  tok, "n": n_tok,
                "wr":     round(tok_wr, 4), "avg_R": round(tok_avg, 4),
                "sum_R":  round(tok_sum, 3),
                "pf":     round(tok_pf, 4) if tok_pf != float("inf") else None,
                "blowup": blowup,
            })
        out["per_token"] = per_token_rows
        blowup_pass = not any_blowup

        out["gate_eval"] = {
            "avg_R":         {"value": round(avg_r, 4),  "threshold": GATE_AVG_R_MIN,
                              "status": _gate_status(avg_r_pass, n)},
            "profit_factor": {"value": round(pf, 4) if pf != float("inf") else None,
                              "threshold": GATE_PF_MIN,
                              "status": _gate_status(pf_pass, n)},
            "win_rate":      {"value": round(wr_raw, 4), "threshold": GATE_WR_MIN,
                              "status": _gate_status(wr_pass, n)},
            "max_drawdown":  {"value": round(mdd, 3), "threshold": GATE_MAX_DD_R,
                              "status": _gate_status(max_dd_pass, n)},
            "blowup":        {"value": any_blowup, "threshold": False,
                              "status": _gate_status(blowup_pass, n)},
        }

        if n < GATE_N_TARGET:
            out["verdict_overall"] = "PENDING"
        elif avg_r_pass and pf_pass and wr_pass and max_dd_pass and blowup_pass:
            out["verdict_overall"] = "PASS"
        else:
            out["verdict_overall"] = "FAIL"

        out["drift"] = _cumulative_avg_R_series(realized_rs)
    finally:
        conn.close()

    return out


def collect_state() -> dict:
    """Top-level — collect both soaks."""
    state = {
        "ts_unix": _time.time(),
        "ts_utc":  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "soaks":   {},
    }
    for spec in SOAKS:
        try:
            state["soaks"][spec["key"]] = collect_one_soak(spec)
        except Exception as e:
            state["soaks"][spec["key"]] = {
                "key": spec["key"], "label": spec["label"],
                "error": str(e),
                "verdict_overall": "ERROR",
            }
    return state


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Breakout Soaks Viewer — A vs B</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0d1117; color: #e6edf3; margin: 0; padding: 16px; }
  h1 { font-size: 18px; margin: 0 0 4px 0; color: #fff; }
  h2 { font-size: 12px; margin: 16px 0 6px 0; color: #7d8590; text-transform: uppercase;
       letter-spacing: 0.5px; border-bottom: 1px solid #30363d; padding-bottom: 3px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  @media (max-width: 1100px) { .grid2 { grid-template-columns: 1fr; } }
  .soak-col { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 14px 18px; }
  .soak-col h3 { margin: 0 0 6px 0; font-size: 15px; color: #fff; }
  .soak-col .sublabel { font-size: 11px; color: #7d8590; margin-bottom: 12px; }
  .row { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 6px;
          padding: 10px 12px; flex: 1 1 130px; min-width: 130px; }
  .card .label { color: #7d8590; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { color: #fff; font-size: 18px; font-weight: 600; margin-top: 3px; }
  .card .threshold { color: #6e7681; font-size: 11px; margin-top: 3px; }
  .status-pill { display: inline-block; padding: 1px 7px; border-radius: 4px;
                 font-size: 10px; font-weight: 600; text-transform: uppercase; }
  .status-pill.ok      { background: #1f3d22; color: #3fb950; }
  .status-pill.fail    { background: #4d1717; color: #f85149; }
  .status-pill.pending { background: #4a3a10; color: #d29922; }
  .verdict-pass    { color: #3fb950; font-weight: 700; }
  .verdict-fail    { color: #f85149; font-weight: 700; }
  .verdict-pending { color: #d29922; font-weight: 700; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; font-size: 11px; }
  th, td { padding: 4px 6px; text-align: left; border-bottom: 1px solid #21262d; }
  th { color: #7d8590; font-weight: 500; font-size: 10px; text-transform: uppercase; }
  tr.win  td.outcome { color: #3fb950; }
  tr.loss td.outcome { color: #f85149; }
  tr.blowup { background: #2d1213; }
  /* DISPLAY-ONLY outcome color-coding for Recent Closed cells. Does NOT
     affect verdict/gate math — purely cosmetic visual cue. Text labels are
     always present (accessibility); color is additive. */
  td.outcome.outcome-win        { color: #ffffff; background: #1a5b1a; font-weight: 700; padding: 4px 8px; border-radius: 3px; }
  td.outcome.outcome-partial2   { color: #1a3b1a; background: #4ade80; font-weight: 600; padding: 4px 8px; border-radius: 3px; }
  td.outcome.outcome-partial1   { color: #1a3b1a; background: #86efac; font-weight: 500; padding: 4px 8px; border-radius: 3px; }
  td.outcome.outcome-loss       { color: #ffffff; background: #7f1d1d; font-weight: 600; padding: 4px 8px; border-radius: 3px; }
  td.outcome.outcome-expired    { color: #d1d5db; background: #374151; font-weight: 500; padding: 4px 8px; border-radius: 3px; }
  /* Subtle row tint (faint background) for tier separation */
  tr.row-win        { background: rgba(63, 185, 80, 0.08); }
  tr.row-partial2   { background: rgba(74, 222, 128, 0.06); }
  tr.row-partial1   { background: rgba(134, 239, 172, 0.04); }
  tr.row-loss       { background: rgba(248, 81, 73, 0.08); }
  tr.row-expired    { background: rgba(156, 163, 175, 0.05); }
  /* R-value tint (secondary cue) */
  td.r-positive  { color: #3fb950; font-weight: 600; }
  td.r-negative  { color: #f85149; font-weight: 600; }
  td.r-zero      { color: #9ca3af; font-weight: 500; }
  /* Sanity-warn rows are darker amber and override outcome row tint */
  tr.sanity-warn.row-win, tr.sanity-warn.row-partial2, tr.sanity-warn.row-partial1,
  tr.sanity-warn.row-loss, tr.sanity-warn.row-expired { background: #2d1f08; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
  .small { color: #7d8590; font-size: 10px; }
  .tracking { background: #1f1a0e; border: 1px dashed #4a3a10; border-radius: 6px; padding: 8px 12px; margin-top: 8px; }
  .tracking .label { color: #d29922; font-size: 10px; text-transform: uppercase; }
  .tracking .value { color: #fff; font-size: 14px; font-weight: 600; }
  /* Sanity-check styling — DISPLAY-ONLY (does NOT affect verdict) */
  tr.sanity-warn { background: #2d1f08; }
  tr.sanity-warn.win  td.outcome { color: #3fb950; }
  tr.sanity-warn.loss td.outcome { color: #f85149; }
  .sanity-pill {
    display: inline-block; padding: 1px 5px; border-radius: 3px;
    font-size: 9px; font-weight: 600;
    background: #4a3a10; color: #d29922;
    margin-right: 2px; margin-bottom: 1px;
  }
  .sanity-pill.crit { background: #4d1717; color: #f85149; }
  .sanity-pill.warn { background: #4a3a10; color: #d29922; }
  /* DISPLAY-ONLY tier-progression tints for the EXISTING TP1/TP2/TP3 price
     cells in Recent Closed. A tier-reached cell is tinted; a non-reached cell
     keeps the normal table-cell background. Greens match the existing outcome
     cell shades (light → medium → strong = TP1 → TP2 → TP3) so visually a WIN
     row's three price cells echo the deep green of the WIN outcome badge.
     Cosmetic only — does NOT enter gate math or verdict logic. Text color is
     darkened on hit cells for contrast against the light green backgrounds. */
  td.mono.tp1-hit { background: #86efac; color: #14301a; font-weight: 600; }   /* light green = partial1 shade */
  td.mono.tp2-hit { background: #4ade80; color: #102a14; font-weight: 600; }   /* medium green = partial2 shade */
  td.mono.tp3-hit { background: #1a5b1a; color: #ffffff; font-weight: 700; }   /* deep green = win shade */
  /* DISPLAY-ONLY scroll container for the Recent Closed table. Bounded
     height prevents the page from growing unbounded as n accumulates past
     the n>=30 gate. Sticky header keeps column labels visible while
     scrolling. Cosmetic only — does NOT affect gate math or verdict. */
  .closed-scroll  { max-height: 520px; overflow-y: auto; overflow-x: auto;
                    border: 1px solid #2a2a2a; border-radius: 4px; }
  .closed-scroll table         { margin: 0; }
  .closed-scroll thead th      { position: sticky; top: 0; background: #1a1a1a;
                                  z-index: 2; box-shadow: 0 1px 0 #2a2a2a; }
  .sanity-info { background: #1f1a0e; border: 1px dashed #4a3a10; border-radius: 6px;
                 padding: 4px 10px; margin: 6px 0; font-size: 10px; color: #d29922; }
  /* DISPLAY-ONLY TradingView mapping helper for the Open Positions table.
     Lets the operator copy the BINANCE:TOKENUSDT symbol verbatim and shows
     UTC timestamp expectations. Does NOT enter gate math or verdict logic. */
  .tv-hint    { background: #0c1a2e; border: 1px dashed #1f4d8a; border-radius: 6px;
                padding: 4px 10px; margin: 6px 0; font-size: 10px; color: #58a6ff; }
  .tv-symbol  { color: #58a6ff; user-select: all; }   /* one click selects the whole symbol for copy */
  /* DISPLAY-ONLY explanatory note above the gate table — documents the WR redefinition.
     Does NOT enter gate math (the math is in the Python side). */
  .wr-note    { background: #1f2030; border: 1px dashed #3a3a55; border-radius: 6px;
                padding: 6px 10px; margin: 6px 0; font-size: 10px; color: #b1b1cf; }
  .wr-note code { background: #2a2a3a; padding: 1px 4px; border-radius: 3px; color: #d1d1f0; }
  #footer { margin-top: 20px; color: #6e7681; font-size: 10px; text-align: center; }
  details summary { cursor: pointer; color: #58a6ff; font-size: 11px; padding: 3px 0; }
  .hb-ok    { color: #3fb950; }
  .hb-stale { color: #d29922; }
  .hb-dead  { color: #f85149; }
</style>
</head>
<body>
<h1>BREAKOUT PAPER SOAKS — Read-only viewer (A vs B)</h1>
<div class="small mono">port 8890 · DB read-only · refresh 30s · auto-PENDING until each soak hits n≥30 independently</div>

<div class="grid2" id="grid">
  <div class="soak-col" id="col-A"><h3>Loading…</h3></div>
  <div class="soak-col" id="col-B"><h3>Loading…</h3></div>
</div>

<div id="footer">Last refresh: <span id="fetch-ts">…</span></div>

<script>
function fmt(x, dp=4, sign=false) {
  if (x === null || x === undefined) return "—";
  if (typeof x === "number") {
    let s = x.toFixed(dp);
    if (sign && x > 0) s = "+" + s;
    return s;
  }
  return String(x);
}
function pill(status) {
  const cls = status === "PASS" || status === "OK" ? "ok"
            : status === "FAIL" || status === "STALE" || status === "DEAD" ? "fail"
            : "pending";
  return `<span class="status-pill ${cls}">${status||"—"}</span>`;
}

// Sanity-check flags — DISPLAY-ONLY annotations, NOT verdict-affecting.
// 'crit' = potential geometry bug; 'warn' = soft sanity threshold breach.
const FLAG_SEVERITY = {
  // Direction/level inconsistencies — never should happen; geometry bug if so
  "buy_sl_above_entry":  "crit",
  "buy_tp1_below_entry": "crit",
  "buy_tp2_below_entry": "crit",
  "buy_tp3_below_entry": "crit",
  "sell_sl_below_entry": "crit",
  "sell_tp1_above_entry":"crit",
  "sell_tp2_above_entry":"crit",
  "sell_tp3_above_entry":"crit",
  // Soft thresholds
  "sl_too_wide":         "warn",
  "tp1_rr_below_floor":  "warn",
  // Tier-vs-outcome inconsistency — display-only, NEVER affects verdict.
  // Under the F-exit-fix's BE-stop guard, a runner that hit TP2/TP3 cannot
  // become a LOSS; if this flag fires, the stored flags disagree with the label.
  "tier_outcome_inconsistent": "crit",
  // TP1 hit but labelled LOSS — same class of inconsistency, milder (TP1 is
  // the breakeven boundary). Display-only.
  "tp1_hit_but_loss":          "crit",
};
function renderFlags(flags) {
  if (!flags || flags.length === 0) return "";
  return flags.map(f => `<span class="sanity-pill ${FLAG_SEVERITY[f]||'warn'}">${f}</span>`).join("");
}

function renderSoak(s) {
  if (!s) return "<h3>(no data)</h3>";
  if (s.error) return `<h3>${s.label}</h3><div class="small">ERROR: ${s.error}</div>`;
  const m = s.metrics || {};
  const ge = s.gate_eval || {};
  const hb = s.soak_health || {};
  const tr = s.tracking || {};

  const verdictClass = s.verdict_overall === "PASS" ? "verdict-pass"
                       : s.verdict_overall === "FAIL" ? "verdict-fail"
                       : "verdict-pending";

  // Gate-row table
  const rows = [
    ["avg_R per closed", ge.avg_R, "≥ +0.40"],
    ["Profit factor", ge.profit_factor, "≥ 2.0"],
    ["WR (positive-R)", ge.win_rate, "≥ 58%"],
    ["Max DD (R)", ge.max_drawdown, "≤ 20"],
    ["Per-token blowup", ge.blowup, "no token ≤35%WR & <0R over ≥5"],
  ];
  let gateRowsHtml = rows.map(r => {
    const v = r[1] || {};
    let valStr = "—";
    if (r[0] === "WR (positive-R)") {
      valStr = v.value !== null && v.value !== undefined ? (v.value * 100).toFixed(1) + "%" : "—";
    } else if (r[0] === "Per-token blowup") {
      valStr = v.value === false ? "none" : v.value === true ? "FLAGGED" : "—";
    } else {
      valStr = v.value !== null && v.value !== undefined ? fmt(v.value, 3, r[0].startsWith("avg_R")) : "—";
    }
    return `<tr><td>${r[0]}</td><td>${valStr}</td><td class="small">${r[2]}</td><td>${pill(v.status||"PENDING")}</td></tr>`;
  }).join("");

  // Open table — DETAILED: entry / SL / TP1-3 prices, distances, R:R, sanity flags
  // PLUS TradingView mapping helpers (pair symbol, opened UTC, expires UTC)
  // so the operator can locate the exact 5M entry candle on TV with UTC clock.
  const openHtml = (s.open || []).length
    ? `<table><thead><tr>
         <th>id</th><th>tok</th><th>TV symbol</th><th>dir</th>
         <th>opened (UTC)</th><th>expires (UTC)</th><th>age</th>
         <th>entry</th><th>SL</th><th>TP1</th><th>TP2</th><th>TP3</th>
         <th>SL %</th><th>TP1 %</th><th>TP2 %</th><th>TP3 %</th>
         <th>R:R TP1</th><th>R:R TP2</th><th>R:R TP3</th>
         <th>entry_type</th><th>flags</th>
       </tr></thead><tbody>` +
       s.open.map(o => {
         const flagsHtml = renderFlags(o.sanity_flags);
         const rowCls = (o.sanity_flags && o.sanity_flags.length) ? "sanity-warn" : "";
         const tvSymbol = `BINANCE:${o.token}USDT`;
         return `<tr class="${rowCls}"><td>#${o.id}</td><td>${o.token}</td>` +
                `<td class="mono small tv-symbol">${tvSymbol}</td>` +
                `<td>${o.direction}</td>` +
                `<td class="mono small">${o.opened_ts ?? "—"}</td>` +
                `<td class="mono small">${o.expires_at ?? "—"}</td>` +
                `<td>${o.age_minutes ?? "—"}m</td>` +
                `<td class="mono">${fmt(o.entry_price,6)}</td>` +
                `<td class="mono">${fmt(o.sl,6)}</td>` +
                `<td class="mono">${fmt(o.tp1,6)}</td>` +
                `<td class="mono">${fmt(o.tp2,6)}</td>` +
                `<td class="mono">${fmt(o.tp3,6)}</td>` +
                `<td class="mono">${fmt(o.sl_dist_pct,3)}%</td>` +
                `<td class="mono">${fmt(o.tp1_dist_pct,3)}%</td>` +
                `<td class="mono">${fmt(o.tp2_dist_pct,3)}%</td>` +
                `<td class="mono">${fmt(o.tp3_dist_pct,3)}%</td>` +
                `<td class="mono">${fmt(o.rr_tp1,2)}</td>` +
                `<td class="mono">${fmt(o.rr_tp2,2)}</td>` +
                `<td class="mono">${fmt(o.rr_tp3,2)}</td>` +
                `<td class="small">${o.entry_type ?? "—"}</td>` +
                `<td>${flagsHtml}</td></tr>`;
       }).join("") +
       `</tbody></table>`
    : '<div class="small">(no open positions)</div>';

  // Per-token table
  const ptHtml = (s.per_token || []).length
    ? `<table><thead><tr><th>token</th><th>n</th><th>WR</th><th>avg R</th><th>sum R</th><th>flag</th></tr></thead><tbody>` +
       s.per_token.map(t => `<tr class="${t.blowup?'blowup':''}"><td>${t.token}</td><td>${t.n}</td>` +
                            `<td>${(t.wr*100).toFixed(1)}%</td><td>${fmt(t.avg_R,3,true)}</td>` +
                            `<td>${fmt(t.sum_R,2,true)}</td><td>${t.blowup?'⚠':''}</td></tr>`).join("") +
       `</tbody></table>`
    : '<div class="small">(empty)</div>';

  // Closed table — DETAILED: entry / SL / TP1-3 + distances + sanity flags.
  // Show ALL closed rows newest-first, wrapped in a fixed-height scroll
  // container so the page doesn't grow unbounded as n accumulates. DB query
  // already returns all CLOSED rows for this source; we just reverse here.
  // At soak signal frequency (~tens per week) the all-rows fetch + render
  // stays sub-100ms — pagination would only matter past a few hundred rows.
  const recentClosed = (s.closed || []).slice().reverse();
  const closedHtml = recentClosed.length
    ? `<table><thead><tr>
         <th>id</th><th>tok</th><th>dir</th>
         <th>outcome</th><th>R</th>
         <th>entry</th><th>SL</th><th>TP1</th><th>TP2</th><th>TP3</th>
         <th>SL %</th><th>TP1 %</th><th>TP2 %</th><th>TP3 %</th>
         <th>R:R TP1</th>
         <th>opened</th><th>closed</th>
         <th>flags</th>
       </tr></thead><tbody>` +
       recentClosed.map(c => {
         // DISPLAY-ONLY outcome color-coding. Color is ADDITIVE — the text label
         // (WIN / PARTIAL_TP2 / ...) is always present. Does NOT affect verdict.
         const OUTCOME_CELL_CLS = {
           "WIN":          "outcome-win",
           "PARTIAL_TP2":  "outcome-partial2",
           "PARTIAL_TP1":  "outcome-partial1",
           "LOSS":         "outcome-loss",
           "EXPIRED":      "outcome-expired",
         };
         const OUTCOME_ROW_CLS = {
           "WIN":          "row-win",
           "PARTIAL_TP2":  "row-partial2",
           "PARTIAL_TP1":  "row-partial1",
           "LOSS":         "row-loss",
           "EXPIRED":      "row-expired",
         };
         const outcomeCellCls = OUTCOME_CELL_CLS[c.result] || "";
         const outcomeRowCls  = OUTCOME_ROW_CLS[c.result] || "";
         // Legacy generic "win"/"loss" class for compat with existing td.outcome rule
         const legacyCls = (c.result==="WIN"||c.result==="PARTIAL_TP2") ? "win"
                   : (c.result==="LOSS") ? "loss" : "";
         const flagsHtml = renderFlags(c.sanity_flags);
         const rowCls = [outcomeRowCls, legacyCls,
                          (c.sanity_flags && c.sanity_flags.length) ? "sanity-warn" : ""
                         ].filter(Boolean).join(" ");
         // R-value tint (secondary cue, NEVER replaces the numeric)
         const r = c.realized_r;
         const rCls = (r > 0) ? "r-positive" : (r < 0) ? "r-negative" : "r-zero";
         // Tier-progression background tints — DISPLAY-ONLY. Read tp{1,2,3}_hit
         // from the results table verbatim. The TP{1,2,3} PRICE cells are tinted
         // green if that tier was reached; neutral if not. Same green shades as
         // the outcome label cells (light → medium → strong). Price numbers stay
         // visible; only the cell background changes. Does NOT enter gate math
         // or verdict logic.
         const tp1Cls = (c.tp1_hit === 1) ? "tp1-hit" : "";
         const tp2Cls = (c.tp2_hit === 1) ? "tp2-hit" : "";
         const tp3Cls = (c.tp3_hit === 1) ? "tp3-hit" : "";
         return `<tr class="${rowCls}"><td>#${c.sid}</td><td>${c.token}</td><td>${c.direction}</td>` +
                `<td class="outcome ${outcomeCellCls}">${c.result}</td>` +
                `<td class="${rCls}">${fmt(r,3,true)}</td>` +
                `<td class="mono">${fmt(c.entry_price,6)}</td>` +
                `<td class="mono">${fmt(c.sl,6)}</td>` +
                `<td class="mono ${tp1Cls}">${fmt(c.tp1,6)}</td>` +
                `<td class="mono ${tp2Cls}">${fmt(c.tp2,6)}</td>` +
                `<td class="mono ${tp3Cls}">${fmt(c.tp3,6)}</td>` +
                `<td class="mono">${fmt(c.sl_dist_pct,3)}%</td>` +
                `<td class="mono">${fmt(c.tp1_dist_pct,3)}%</td>` +
                `<td class="mono">${fmt(c.tp2_dist_pct,3)}%</td>` +
                `<td class="mono">${fmt(c.tp3_dist_pct,3)}%</td>` +
                `<td class="mono">${fmt(c.rr_tp1,2)}</td>` +
                `<td class="mono small">${c.opened_ts ?? "—"}</td>` +
                `<td class="mono small">${c.closed_at ?? "—"}</td>` +
                `<td>${flagsHtml}</td></tr>`;
       }).join("") +
       `</tbody></table>`
    : '<div class="small">(no closed signals yet)</div>';

  // Drift (sample max ~20 pts)
  const drift = s.drift || [];
  const stride = Math.max(1, Math.floor(drift.length / 12));
  const driftPts = drift.filter((d, i) => i === drift.length-1 || i % stride === 0);
  const driftHtml = driftPts.length
    ? `<table><tr><th>n</th><th>cum R</th><th>cum avg R</th></tr>` +
      driftPts.map(p => `<tr><td>${p.n}</td><td>${fmt(p.cum_R,2,true)}</td><td>${fmt(p.cum_avg_R,3,true)}</td></tr>`).join("") + `</table>`
    : '<div class="small">(none)</div>';

  // Heartbeat
  const hbCls = hb.status === "OK" ? "hb-ok" : hb.status === "STALE" ? "hb-stale" : "hb-dead";

  return `
    <h3>${s.label} <span class="status-pill ${s.verdict_overall==='PASS'?'ok':s.verdict_overall==='FAIL'?'fail':'pending'}">${s.verdict_overall}</span></h3>
    <div class="sublabel">source: <code>${s.soak_label}</code> · ref friction avg_R = +${(s.ref_avg_R||0).toFixed(3)} <span class="small">(${s.ref_source})</span></div>

    <div class="row">
      <div class="card"><div class="label">Closed</div><div class="value">${m.n_closed ?? 0}</div><div class="threshold">target ≥ 30</div></div>
      <div class="card"><div class="label">Open</div><div class="value">${m.n_open ?? 0}</div><div class="threshold">in market</div></div>
      <div class="card"><div class="label">Progress</div><div class="value">${(m.progress_pct ?? 0).toFixed(0)}%</div><div class="threshold">${m.n_closed ?? 0} / 30</div></div>
      <div class="card"><div class="label">Verdict</div><div class="value ${verdictClass}">${s.verdict_overall}</div><div class="threshold">PENDING until n≥30</div></div>
    </div>

    <h2>Locked thresholds vs observed</h2>
    <div class="wr-note">WR definition: <b>positive-R-close rate</b> — counts any close with realized_R&nbsp;&gt;&nbsp;0 (WIN, PARTIAL_TP2, AND PARTIAL_TP1_BE since the BE-stop runner pays only friction and stays positive). LOSS, EXPIRED, and rare R&nbsp;≤&nbsp;0 PARTIAL_TP1 (extreme-friction edge cases) are NOT wins. Threshold derived 2026-06-03 from the original 11pp buffer below the new BE-after-TP1 model backtest WR (avg 69.4%); see <code>PHASE_C_FULL_AUDIT_V2.md §7.3</code>.</div>
    <table>
      <thead><tr><th>Criterion</th><th>Observed</th><th>Threshold</th><th>Status</th></tr></thead>
      <tbody>${gateRowsHtml}</tbody>
    </table>

    <div class="tracking">
      <div class="label">Tracking-only (NOT in verdict)</div>
      <div class="row" style="margin-top:6px;margin-bottom:0">
        <div class="card" style="background:transparent;border:1px solid #4a3a10"><div class="label">sum_R</div><div class="value">${fmt(tr.sum_R,2,true)}</div></div>
        <div class="card" style="background:transparent;border:1px solid #4a3a10"><div class="label">R / day</div><div class="value">${fmt(tr.R_per_day,3,true)}</div></div>
        <div class="card" style="background:transparent;border:1px solid #4a3a10"><div class="label">Days elapsed</div><div class="value">${fmt(tr.days_elapsed,1)}</div></div>
        <div class="card" style="background:transparent;border:1px solid #4a3a10"><div class="label">Friction-on ref</div><div class="value">+${(tr.ref_avg_R_friction||0).toFixed(3)}</div></div>
      </div>
    </div>

    <h2>Soak health</h2>
    <div class="row">
      <div class="card"><div class="label">PID</div><div class="value">${hb.pid ?? "—"}</div></div>
      <div class="card"><div class="label">Cycle</div><div class="value">${hb.cycle ?? "—"}</div></div>
      <div class="card"><div class="label">Heartbeat age</div><div class="value ${hbCls}">${hb.heartbeat_age_s !== undefined ? hb.heartbeat_age_s + "s" : "—"}</div></div>
      <div class="card"><div class="label">Last signal</div><div class="value mono" style="font-size:11px">${hb.last_signal_ts ?? "(none)"}</div></div>
    </div>

    <h2>n-vs-expectancy drift</h2>
    ${driftHtml}

    <h2>Per-token</h2>
    ${ptHtml}

    <h2>Open positions <span class="small">— entry / SL / TP geometry + TradingView mapping</span></h2>
    <div class="tv-hint">TradingView mapping: paste the <b>TV symbol</b> column into TV's symbol search, set the chart timeframe to <b>5M</b> (signal entry TF), and set the chart's <b>timezone to UTC</b>. The <b>opened (UTC)</b> column is the entry candle's open time; scroll to it and draw SL / TP1 / TP2 / TP3 horizontal lines at the listed prices. The <b>expires (UTC)</b> column is the 48-hour deadline.</div>
    <div class="sanity-info">Sanity flags (right column) are <b>display-only</b> — they do <b>NOT</b> affect the locked verdict. Thresholds: SL ≤ 3.0%, TP1 R:R ≥ 1.3, direction/level consistency.</div>
    ${openHtml}

    <h2>Recent closed (${(s.closed || []).length} total) <span class="small">— with geometry, newest first</span></h2>
    <div class="closed-scroll">${closedHtml}</div>
  `;
}

async function refresh() {
  try {
    const resp = await fetch("/api/state", { cache: "no-store" });
    if (!resp.ok) {
      document.getElementById("fetch-ts").textContent = "FETCH ERROR " + resp.status;
      return;
    }
    const s = await resp.json();
    const soaks = s.soaks || {};
    document.getElementById("col-A").innerHTML = renderSoak(soaks.A);
    document.getElementById("col-B").innerHTML = renderSoak(soaks.B);
    document.getElementById("fetch-ts").textContent = s.ts_utc + " UTC";
  } catch (e) {
    document.getElementById("fetch-ts").textContent = "FETCH ERROR: " + e.message;
  }
}
refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""


class ViewerHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send_html(self, body: str, status: int = 200):
        b = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _send_json(self, obj, status: int = 200):
        b = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index", "/index.html"):
            self._send_html(HTML_PAGE)
            return
        if p.path == "/api/state":
            try:
                self._send_json(collect_state())
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return
        self.send_response(404); self.end_headers()

    def do_POST(self):   self.send_error(405)
    def do_PUT(self):    self.send_error(405)
    def do_DELETE(self): self.send_error(405)
    def do_PATCH(self):  self.send_error(405)


def main():
    try:
        c = _open_ro_conn(); c.close()
    except Exception as e:
        print(f"FATAL: cannot open breakout.db read-only: {e!r}", file=sys.stderr)
        sys.exit(1)
    print(f"Breakout viewer A+B on http://{HOST}:{PORT}")
    print(f"  DB: {DB_PATH} (read-only)")
    print(f"  Soak A heartbeat: {SOAKS[0]['heartbeat']}")
    print(f"  Soak B heartbeat: {SOAKS[1]['heartbeat']}")
    print(f"  Ctrl+C to stop.")
    socketserver.TCPServer.allow_reuse_address = False
    with socketserver.TCPServer((HOST, PORT), ViewerHandler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n  shutdown.")


if __name__ == "__main__":
    main()
