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

Per-soak BACKTEST REFERENCE (informational, NOT a gate; authoritative 720d
V_ENTRY hold-at-entry run, run_posttp2_backtests.py 2026-06-05):
    A: clean +0.4830 / friction +0.3623 avg_R (TF_A 720d)
    B: clean +0.4818 / friction +0.3765 avg_R (TF_B 720d)
    Both friction numbers are BELOW the +0.40 gate (validated-negative). The soak
    writes CLEAN realized_r; the verdict's avg_R criterion is evaluated on the
    FRICTION-ADJUSTED value (clean × friction/clean haircut) so the live verdict
    matches the honest friction-basis conclusion (GATE-BASIS FIX, audit #8).

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
# V1 (2026-06-05): NO live price fetch. urllib.request/error removed — the viewer
# reads ONLY breakout.db (mode=ro) + process checks (os.kill/ /proc). No outbound
# price API call exists in this file.

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
# GATE-BASIS FIX (2026-06-05, BREAKOUT_FULL_AUDIT finding #8, option b):
# The soak writes CLEAN realized_r (baseline rt_cost only, no execution Monte-Carlo).
# The honest validated-negative conclusion is on the FRICTION basis. To make the live
# verdict match that honest conclusion, the avg_R gate is evaluated on a FRICTION-ADJUSTED
# value: avg_R_friction_adj = clean_avg_R * friction_haircut.
#
# friction_haircut = measured FRICTION/CLEAN avg_R ratio from the authoritative 720d
# clean-vs-friction backtest (run_posttp2_backtests.py, V_ENTRY hold-at-entry, 2026-06-05):
#     A (5M/4H): friction +0.3623 / clean +0.4830 = 0.7501
#     B (5M/1H): friction +0.3765 / clean +0.4818 = 0.7815
# Per-soak (not a single magic number) because the two TFs degrade differently under
# friction. ONLY avg_R is haircut: PF / WR / maxDD already pass on BOTH bases, so they
# need no adjustment for the verdict to be honest. This is VIEWER-SIDE ONLY — the soak
# still writes clean realized_r unchanged.
SOAKS = [
    {
        "key":             "A",
        "label":           "Soak A — 5M / 4H",
        "soak_label":      "H4_BREAKOUT_PAPER_SOAK",
        "heartbeat":       _BREAKOUT_DIR / "data" / "breakout_soak_heartbeat.json",
        "pid_file":        _BREAKOUT_DIR / "data" / "breakout_soak.pid",
        "ref_avg_R":       0.3623,  # friction ref, V_ENTRY hold-at-entry 720d — BELOW +0.40 gate
        "ref_avg_R_clean": 0.4830,  # clean ref (== soak realized_r basis), 720d
        "friction_haircut": round(0.3623 / 0.4830, 4),  # = 0.7501 (friction/clean, 720d)
        "ref_source":      "run_posttp2_backtests.py (720d clean vs friction)",
    },
    {
        "key":             "B",
        "label":           "Soak B — 5M / 1H",
        "soak_label":      "H4_BREAKOUT_PAPER_SOAK_B",
        "heartbeat":       _BREAKOUT_DIR / "data" / "breakout_soak_B_heartbeat.json",
        "pid_file":        _BREAKOUT_DIR / "data" / "breakout_soak_B.pid",
        "ref_avg_R":       0.3765,  # friction ref, V_ENTRY hold-at-entry 720d — BELOW +0.40 gate
        "ref_avg_R_clean": 0.4818,  # clean ref (== soak realized_r basis), 720d
        "friction_haircut": round(0.3765 / 0.4818, 4),  # = 0.7815 (friction/clean, 720d)
        "ref_source":      "run_posttp2_backtests.py (720d clean vs friction)",
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


# Static FRICTION-ON backtest reference (Config 14, 720d NEW BE-after-TP1 model).
# Computed read-only from backtest_signals run 56 (TF_A) / run 58 (TF_B); these
# are immutable historical rows. DSR from PHASE_C_FULL_AUDIT_V2.md. NOT a gate —
# this is the convergence target the forward soak is measured against.
# POST-TP2 HOLD-AT-ENTRY model (V_ENTRY, adopted 2026-06-04 — POSTTP2_STOP_COMPARISON.md).
# 720d friction. NOTE: BOTH are BELOW the +0.40 avg_R gate floor — the backtest reference does
# not clear the gate; the forward soak is expected to confirm marginal/fail. (Prior trail model
# was A=0.3376 / B=0.3644; V_ENTRY lets post-TP2 runners that only dipped to TP1 ride to TP3.)
BACKTEST_REFERENCE = {
    "A": {"tf": "5M/4H", "n": 4744,  "avg_R": 0.3623, "wr_pct": 67.7, "pf": 2.21, "dsr": 1.0},
    "B": {"tf": "5M/1H", "n": 12090, "avg_R": 0.3765, "wr_pct": 70.0, "pf": 2.38, "dsr": 1.0},
}


def _exit_reason_of(row: dict) -> str:
    """Map a closed signal to its exit model bucket (display-only, from DB flags).

    WIN_TP3 (full TP1/TP2/TP3) · PARTIAL_TP2 · PARTIAL_TP1_BE (TP1 then BE-stop) ·
    FULL_SL (SL with no TP1) · EXPIRED · OTHER. Mirrors the soak's outcome labels;
    never affects the gate.
    """
    res = row.get("result")
    if res == "WIN":
        return "WIN_TP3"
    if res == "PARTIAL_TP2_BE":
        return "PARTIAL_TP2_BE"   # V_ENTRY: TP2 reached, runner ran back to entry (breakeven)
    if res == "PARTIAL_TP2":
        return "PARTIAL_TP2"
    if res == "PARTIAL_TP1":
        return "PARTIAL_TP1_BE"
    if res == "EXPIRED":
        return "EXPIRED"
    if res == "LOSS":
        return "FULL_SL" if not row.get("tp1_hit") else "LOSS_AFTER_TP1"
    return "OTHER"


def _dashboard_aggregates(closed: list) -> dict:
    """Read-only display aggregates for the Dashboard/Reports tabs.

    Pure function of the (already source-filtered) closed-signal list. Adds NOTHING
    to gate math — every value here is observational display only. Crucially it
    surfaces the correlated-burst structure (same opened_ts across multiple tokens
    = ONE directional bet, not N) so aggregate stats are read with honest weight.
    """
    # Outcome + direction + extremes
    outcome_counts = {}
    direction = {"BUY": {"n": 0, "sum_R": 0.0, "wins": 0},
                 "SELL": {"n": 0, "sum_R": 0.0, "wins": 0}}
    exit_reasons = {}
    rs_all = []
    for r in closed:
        res = r.get("result") or "?"
        outcome_counts[res] = outcome_counts.get(res, 0) + 1
        exit_reasons_key = _exit_reason_of(r)
        exit_reasons[exit_reasons_key] = exit_reasons.get(exit_reasons_key, 0) + 1
        rv = r.get("realized_r") or 0.0
        rs_all.append(rv)
        d = r.get("direction")
        if d in direction:
            direction[d]["n"] += 1
            direction[d]["sum_R"] += rv
            if rv > 0:
                direction[d]["wins"] += 1
    for d in direction.values():
        d["sum_R"] = round(d["sum_R"], 3)

    # Day-by-day R (by signal OPENED day — the day the bet was placed; this is the
    # correlated-burst framing where a same-day burst is one directional decision).
    by_day_map = {}
    for r in closed:
        day = str(r.get("opened_ts") or "")[:10]
        if not day:
            continue
        e = by_day_map.setdefault(day, {"day": day, "n": 0, "sum_R": 0.0})
        e["n"] += 1
        e["sum_R"] += (r.get("realized_r") or 0.0)
    by_day = [dict(v, sum_R=round(v["sum_R"], 3)) for v in
              sorted(by_day_map.values(), key=lambda x: x["day"])]

    # Correlated bursts: signals opened on the SAME bar (same opened_ts) across ≥2
    # tokens = ONE bet. independent_event_count collapses each same-bar group to 1.
    group_map = {}
    for r in closed:
        ts = r.get("opened_ts")
        group_map.setdefault(ts, []).append(r)
    bursts = []
    for ts, grp in group_map.items():
        if len(grp) < 2:
            continue
        dirs = sorted({g.get("direction") for g in grp})
        s_r = round(sum((g.get("realized_r") or 0.0) for g in grp), 3)
        bursts.append({
            "ts": ts,
            "dir": dirs[0] if len(dirs) == 1 else "MIXED",
            "n": len(grp),
            "sum_R": s_r,
            "tokens": [g.get("token") for g in grp],
        })
    bursts.sort(key=lambda b: b["ts"])
    # Flag the largest positive and largest negative bursts + any n>=5.
    if bursts:
        max_b = max(bursts, key=lambda b: b["sum_R"])
        min_b = min(bursts, key=lambda b: b["sum_R"])
        for b in bursts:
            b["big"] = (b is max_b or b is min_b or b["n"] >= 5)
    independent_event_count = len(group_map)
    burst_signal_count = sum(b["n"] for b in bursts)

    # Equity series ordered by close time (matches gate/drift ordering). Each point
    # is tagged with its opened_ts burst group so the curve can mark burst-driven
    # steps — a run of adjacent same-burst points is ONE entry decision, not many.
    equity_series = []
    cum = 0.0
    multi_bars = {ts for ts, grp in group_map.items() if len(grp) >= 2}
    for i, r in enumerate(closed, start=1):
        cum += (r.get("realized_r") or 0.0)
        ts = r.get("opened_ts")
        equity_series.append({
            "i": i,
            "closed_at": r.get("closed_at"),
            "opened_ts": ts,
            "token": r.get("token"),
            "dir": r.get("direction"),
            "r": round(r.get("realized_r") or 0.0, 3),
            "cum_R": round(cum, 3),
            "burst": ts if ts in multi_bars else None,
        })

    rs_sorted = sorted(rs_all)
    return {
        "outcome_counts": outcome_counts,
        "direction": direction,
        "exit_reasons": exit_reasons,
        "by_day": by_day,
        "bursts": bursts,
        "independent_event_count": independent_event_count,
        "burst_signal_count": burst_signal_count,
        "best_R": round(rs_sorted[-1], 3) if rs_sorted else None,
        "worst_R": round(rs_sorted[0], 3) if rs_sorted else None,
        "equity_series": equity_series,
    }


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


# ── Process-liveness checks (READ-ONLY; os.kill(pid,0) + /proc, NO signals) ──
# V1 isolation: the viewer learns whether a process is running ONLY via a
# zero-signal liveness probe and /proc reads. It NEVER opens signals.db and
# NEVER fetches live prices. (The previous _compute_open_tier_status Binance
# fetch was REMOVED for V1 — open positions show no live tier/price.)
def _proc_alive(pid):
    """True if PID is alive (os.kill(pid, 0) sends NO signal — pure liveness)."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True  # exists but owned by another user — still 'alive'


def _proc_cmdline(pid):
    """Read /proc/<pid>/cmdline (read-only). Returns '' if unavailable."""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            return f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except (OSError, ValueError):
        return ""


def _proc_age_seconds(pid):
    """Best-effort process age from /proc/<pid> dir mtime (read-only). None if NA."""
    try:
        return round(max(0.0, _time.time() - os.stat(f"/proc/{int(pid)}").st_mtime), 0)
    except (OSError, ValueError):
        return None


def _process_status(pid, cmd_substr=""):
    """Read-only process descriptor: running/stopped + cmdline-match + age."""
    alive = _proc_alive(pid)
    cmd = _proc_cmdline(pid) if alive else ""
    matches = (cmd_substr in cmd) if (alive and cmd_substr) else None
    return {
        "pid": int(pid) if pid else None,
        "running": alive,
        "cmd_match": matches,           # True/False/None(unknown) vs expected cmd
        "age_seconds": _proc_age_seconds(pid) if alive else None,
        "status": "running" if alive else "stopped",
    }


# OBSERVATIONAL session tagging (display-only). Maps a signal's OPENED UTC
# timestamp to a standard crypto/FX trading session. NOT a gate, NOT a filter,
# NOT a verdict input — purely a tracking dimension to accumulate over many days.
# Boundaries (UTC, [start, end)):
#   ASIAN              00:00–08:00   (Tokyo/Sydney; lower volume, more rangy)
#   LONDON             08:00–13:00   (European open)
#   LONDON_NY_OVERLAP  13:00–16:00   (highest liquidity)
#   NY                 16:00–21:00   (US session)
#   LATE_US            21:00–24:00   (US close / transition to Asia)
SESSION_ORDER = ["ASIAN", "LONDON", "LONDON_NY_OVERLAP", "NY", "LATE_US"]


def _session_of(opened_ts: str) -> str:
    """Return the standard session label for an OPENED UTC 'YYYY-MM-DD HH:MM:SS'."""
    try:
        hour = int(str(opened_ts)[11:13])
    except (ValueError, TypeError, IndexError):
        return "UNKNOWN"
    if hour < 8:
        return "ASIAN"
    if hour < 13:
        return "LONDON"
    if hour < 16:
        return "LONDON_NY_OVERLAP"
    if hour < 21:
        return "NY"
    return "LATE_US"


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
        "per_session": [],     # observational session tagging, not part of verdict
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
            # V1: NO live price fetch. Open-position tier-hit state requires walking
            # fresh 5m bars (a network call), which is forbidden in V1. Leave tier
            # flags null — the open-trades table shows entry geometry only, no live
            # P&L / current-price / tier coloring (stated in the UI).
            d["tp1_hit"] = d["tp2_hit"] = d["tp3_hit"] = None
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
        n_wins_p2 = sum(1 for r in closed if r["result"] in ("WIN", "PARTIAL_TP2", "PARTIAL_TP2_BE"))  # kept for n_wins display
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
        # GATE-BASIS FIX (audit #8, option b): the verdict's avg_R criterion is
        # evaluated on the FRICTION-ADJUSTED value (honest basis), not the raw clean
        # avg_R the soak writes. avg_r (clean) is preserved for display/reference.
        friction_haircut = spec.get("friction_haircut", 1.0)
        avg_r_friction   = round(avg_r * friction_haircut, 4)
        avg_r_pass  = avg_r_friction >= GATE_AVG_R_MIN      # honest (friction) basis
        out["metrics"]["avg_R_friction_adj"] = avg_r_friction   # gated value (display)
        out["metrics"]["friction_haircut"]   = friction_haircut
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

        # OBSERVATIONAL per-session breakdown (display-only — NOT a gate criterion).
        # Computed live from each closed signal's opened_ts; same source-filtered
        # `closed` list as per_token, so source isolation is preserved. WR uses the
        # same positive-R-close definition as the rest of the viewer.
        per_session_map = {}
        for r in closed:
            sess = _session_of(r.get("opened_ts"))
            per_session_map.setdefault(sess, []).append(r["realized_r"])
        per_session_rows = []
        sess_keys = [s for s in SESSION_ORDER if s in per_session_map] + \
                    [s for s in sorted(per_session_map) if s not in SESSION_ORDER]
        for sess in sess_keys:
            rs = per_session_map[sess]
            n_sess = len(rs)
            sess_wins = sum(1 for v in rs if (v or 0) > 0)
            sess_wr = sess_wins / n_sess if n_sess else 0.0
            sess_pf = _profit_factor(rs)
            per_session_rows.append({
                "session": sess, "n": n_sess,
                "wr":      round(sess_wr, 4),
                "avg_R":   round(sum(rs) / n_sess, 4) if n_sess else 0.0,
                "sum_R":   round(sum(rs), 3),
                "pf":      round(sess_pf, 4) if sess_pf != float("inf") else None,
            })
        out["per_session"] = per_session_rows

        out["gate_eval"] = {
            # avg_R is GATED on the friction-adjusted value (honest basis). The raw
            # clean avg_R is carried as value_clean for reference/display only.
            "avg_R":         {"value": avg_r_friction, "value_clean": round(avg_r, 4),
                              "threshold": GATE_AVG_R_MIN,
                              "basis": "friction-adjusted",
                              "haircut": friction_haircut,
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

        # Display-only Dashboard/Reports aggregates (read-only, NOT gate inputs).
        out["dashboard"] = _dashboard_aggregates(closed)
        out["backtest_ref"] = BACKTEST_REFERENCE.get(spec["key"], {})
    finally:
        conn.close()

    return out


# Map the soak_label stored in exec_quality_log back to the display key (A/B).
_SOAK_LABEL_TO_KEY = {s["soak_label"]: s["key"] for s in SOAKS}


def collect_exec_quality(limit: int = 50) -> dict:
    """READ-ONLY display aggregates for the Execution Quality Monitor panel.

    SELECTs from `exec_quality_log` ONLY. Never writes, never gates. The
    `would_skip` flag is DISPLAY-ONLY here, exactly as it is logging-only in the
    soak — this function surfaces it for monitoring and CANNOT enable gating.
    Renders cleanly when the table is absent or has 0 rows (empty state).
    """
    out = {
        "mode": "Observation only / No gating",
        "trade_affected": "NO",          # static — the flag never affects trading
        "table_present": False,
        "total": 0, "fetch_ok": 0, "fetch_failed": 0,
        "would_skip_count": 0,
        "would_skip_rate": None,          # None → UI shows "—" (guards divide-by-zero)
        "latest": None,
        "recent": [],
    }
    try:
        conn = _open_ro_conn()
    except Exception as e:
        out["error"] = str(e)
        return out
    try:
        t = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='exec_quality_log'"
        ).fetchone()
        if not t:
            return out  # table not yet created — empty state, no error
        out["table_present"] = True
        agg = conn.execute(
            "SELECT COUNT(*) AS n, "
            "       SUM(CASE WHEN fetch_status='ok'           THEN 1 ELSE 0 END) AS ok, "
            "       SUM(CASE WHEN fetch_status='fetch_failed' THEN 1 ELSE 0 END) AS failed, "
            "       SUM(CASE WHEN would_skip=1                THEN 1 ELSE 0 END) AS ws "
            "FROM exec_quality_log"
        ).fetchone()
        total = agg["n"] or 0
        out["total"] = total
        out["fetch_ok"] = agg["ok"] or 0
        out["fetch_failed"] = agg["failed"] or 0
        out["would_skip_count"] = agg["ws"] or 0
        out["would_skip_rate"] = (round(100.0 * out["would_skip_count"] / total, 1)
                                  if total > 0 else None)
        rows = conn.execute(
            "SELECT ts_utc, soak_label, token, direction, spread_pct, est_slippage_pct, "
            "       exec_side_depth_01pct_usd, position_usd, would_skip, tripped_rules, "
            "       fetch_status "
            "FROM exec_quality_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        recent = []
        for r in rows:
            ok = (r["fetch_status"] == "ok")
            depth_ratio = None
            if ok and r["position_usd"] and r["exec_side_depth_01pct_usd"] is not None:
                depth_ratio = round(r["exec_side_depth_01pct_usd"] / r["position_usd"], 1)
            recent.append({
                "ts_utc": r["ts_utc"],
                "soak": _SOAK_LABEL_TO_KEY.get(r["soak_label"], r["soak_label"]),
                "token": r["token"],
                "direction": r["direction"],
                "spread_pct": r["spread_pct"] if ok else None,
                "est_slippage_pct": r["est_slippage_pct"] if ok else None,
                "depth_ratio": depth_ratio,
                "would_skip": (int(r["would_skip"]) if r["would_skip"] is not None else None),
                "tripped_rules": (r["tripped_rules"] or "") if ok else "",
                "fetch_status": r["fetch_status"],
            })
        out["recent"] = recent
        if recent:
            out["latest"] = recent[0]
    finally:
        conn.close()
    return out


# Production fade descriptor — V1 surfaces process LIVENESS ONLY (no signals.db read).
# PID 512666 is the known fade process; if it's dead the viewer detects 'stopped'.
FADE_PROC = {
    "key":        "FADE",
    "label":      "Production Fade",
    "mode":       "LIVE",
    "known_pid":  512666,
    "cmd_substr": "crypto_alert.py",
}


def collect_processes() -> dict:
    """READ-ONLY process liveness for fade + both soaks (os.kill/proc, no DB writes,
    no signals.db). Soak PIDs come from their own pid files in breakout-work/data."""
    procs = {}
    # Fade: known PID + cmdline match (process check only).
    procs["FADE"] = dict(_process_status(FADE_PROC["known_pid"], FADE_PROC["cmd_substr"]),
                         label=FADE_PROC["label"], mode=FADE_PROC["mode"])
    # Soaks: read pid from each soak's pid file (breakout.db side only).
    for spec in SOAKS:
        pid = None
        try:
            pf = spec["pid_file"]
            if pf.exists():
                pid = int(pf.read_text().strip())
        except (ValueError, OSError):
            pid = None
        procs[spec["key"]] = dict(_process_status(pid, "breakout_paper_soak"),
                                  label=spec["label"], mode="PAPER")
    return procs


def _overall_status(state: dict) -> dict:
    """Derive HEALTHY / WARNING / ERROR from process liveness + DB read + soak errors.
    Read-only; no thresholds touched. ERROR > WARNING > HEALTHY."""
    reasons = []
    level = "HEALTHY"
    # DB read failure on either soak → ERROR
    for k, s in state.get("soaks", {}).items():
        if s.get("error"):
            level = "ERROR"; reasons.append(f"Soak {k}: {s['error']}")
    # Breakout soak processes down → ERROR (their data would go stale)
    procs = state.get("processes", {})
    for k in ("A", "B"):
        if not procs.get(k, {}).get("running"):
            level = "ERROR"; reasons.append(f"Breakout soak {k} process stopped")
    # Fade process down → WARNING (monitored separately; not this dashboard's data)
    if not procs.get("FADE", {}).get("running") and level != "ERROR":
        level = "WARNING"; reasons.append("Production fade process not detected")
    # Stale soak heartbeats → WARNING
    for k in ("A", "B"):
        hb = state.get("soaks", {}).get(k, {}).get("soak_health", {})
        if hb.get("status") == "STALE" and level == "HEALTHY":
            level = "WARNING"; reasons.append(f"Soak {k} heartbeat stale")
    if not reasons:
        reasons.append("All monitored processes running; DB read OK.")
    return {"level": level, "reasons": reasons}


def collect_state() -> dict:
    """Top-level — soaks + exec-quality + process liveness + overall status.
    READ-ONLY: breakout.db (mode=ro) + process checks. signals.db is NEVER opened."""
    state = {
        "ts_unix": _time.time(),
        "ts_utc":  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "db_read_only": True,           # _open_ro_conn() uses ?mode=ro (writes raise)
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
    # Execution Quality Monitor — read-only, display-only (Type-A observation data).
    try:
        state["exec_quality"] = collect_exec_quality()
    except Exception as e:
        state["exec_quality"] = {"error": str(e), "mode": "Observation only / No gating",
                                 "total": 0, "recent": [], "would_skip_rate": None}
    # Process liveness (fade + soaks) — process checks only.
    try:
        state["processes"] = collect_processes()
    except Exception as e:
        state["processes"] = {"error": str(e)}
    state["overall"] = _overall_status(state)
    return state




HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>TradeAI Bot Control Dashboard</title>
<style>
  :root { --bg:#0a0d12; --panel:#11161d; --card:#161b22; --bd:#2a313c; --bd2:#1f2630;
          --tx:#e6edf3; --mut:#8b949e; --grn:#3fb950; --grnbg:#11301a; --yel:#d29922;
          --yelbg:#332810; --red:#f85149; --redbg:#3a1515; --gry:#6e7681; --blu:#58a6ff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--tx); font:15px/1.5 -apple-system,
         BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; padding:0 0 60px; }
  .wrap { max-width:1280px; margin:0 auto; padding:0 16px; }
  h1 { font-size:20px; margin:16px 0 2px; }
  h2 { font-size:16px; margin:26px 0 8px; padding-bottom:5px; border-bottom:1px solid var(--bd2); }
  .sub { color:var(--mut); font-size:12px; }
  .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  .muted { color:var(--mut); }
  a { color:var(--blu); }

  /* status bar */
  .statusbar { position:sticky; top:0; z-index:10; background:var(--panel);
               border-bottom:1px solid var(--bd); padding:10px 16px; }
  .statusbar .inner { max-width:1280px; margin:0 auto; display:flex; flex-wrap:wrap;
                      align-items:center; gap:12px; }
  .bigpill { font-size:15px; font-weight:700; padding:5px 14px; border-radius:6px; }
  .procline { display:flex; gap:14px; flex-wrap:wrap; font-size:13px; }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px;
         vertical-align:middle; }
  .dot.green{background:var(--grn);} .dot.red{background:var(--red);}
  .dot.yellow{background:var(--yel);} .dot.gray{background:var(--gry);}

  .lvl-HEALTHY,.lvl-PASS,.lvl-running,.ok { background:var(--grnbg); color:var(--grn); }
  .lvl-WARNING,.lvl-PENDING,.warn { background:var(--yelbg); color:var(--yel); }
  .lvl-ERROR,.lvl-FAIL,.lvl-stopped,.err { background:var(--redbg); color:var(--red); }
  .lvl-INFO,.info { background:#1c2128; color:var(--mut); }

  .grid { display:grid; gap:14px; }
  .g4 { grid-template-columns:repeat(4,1fr); }
  .g2 { grid-template-columns:repeat(2,1fr); }
  @media (max-width:980px){ .g4{grid-template-columns:repeat(2,1fr);} .g2{grid-template-columns:1fr;} }
  @media (max-width:560px){ .g4{grid-template-columns:1fr;} }

  .card { background:var(--card); border:1px solid var(--bd); border-radius:8px; padding:12px 14px; }
  .card h3 { margin:0 0 8px; font-size:14px; display:flex; justify-content:space-between; align-items:center; }
  .kv { display:flex; justify-content:space-between; font-size:13px; padding:2px 0; }
  .kv .k { color:var(--mut); } .kv .v { font-weight:600; }
  .pill { display:inline-block; padding:1px 8px; border-radius:5px; font-size:12px; font-weight:700; }

  .panel { background:var(--panel); border:1px solid var(--bd); border-radius:8px; padding:14px 16px; }
  .decision { border-left:4px solid var(--yel); }
  .decision.HEALTHY { border-left-color:var(--grn); }
  .decision.ERROR { border-left-color:var(--red); }
  .decision .action { font-size:15px; font-weight:700; margin-top:8px; }

  table { width:100%; border-collapse:collapse; font-size:13px; margin-top:4px; }
  th,td { padding:7px 9px; text-align:left; border-bottom:1px solid var(--bd2); }
  th { color:var(--mut); font-size:11px; text-transform:uppercase; letter-spacing:.4px; font-weight:600; }
  td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
  tr:hover td { background:#0e141b; }
  .scroll { max-height:420px; overflow:auto; border:1px solid var(--bd2); border-radius:6px; }
  .scroll table { margin:0; } .scroll thead th { position:sticky; top:0; background:var(--panel); }

  .warnbox { background:var(--yelbg); border:1px solid #4a3a10; border-radius:6px;
             padding:8px 12px; color:var(--yel); font-size:13px; margin:8px 0; }
  .chartwrap { background:var(--card); border:1px solid var(--bd); border-radius:8px; padding:12px; }
  .toggle button { background:var(--card); color:var(--tx); border:1px solid var(--bd);
                   border-radius:5px; padding:4px 12px; cursor:pointer; font-size:13px; }
  .toggle button.active { background:#1f6feb33; border-color:var(--blu); color:var(--blu); }
  canvas { width:100%; height:240px; display:block; }
  details { background:var(--card); border:1px solid var(--bd); border-radius:8px; padding:10px 14px; margin-top:10px; }
  summary { cursor:pointer; font-weight:600; font-size:14px; }
  .foot { color:var(--mut); font-size:12px; margin-top:24px; text-align:center; }
  .na { color:var(--gry); }
</style>
</head>
<body>

<!-- 1. TOP SYSTEM STATUS BAR -->
<div class="statusbar"><div class="inner" id="statusbar">Loading…</div></div>

<div class="wrap">
  <h1>TradeAI Bot Control Dashboard <span class="sub">— V1 · read-only · breakout.db + process checks only</span></h1>

  <!-- 2. STRATEGY CARDS -->
  <h2>Strategies</h2>
  <div class="grid g4" id="cards">Loading…</div>

  <!-- 3. MAIN DECISION PANEL -->
  <h2>What's happening — recommended action</h2>
  <div id="decision">Loading…</div>

  <!-- 4. GATE CHECKLIST -->
  <h2>Gate checklist <span class="sub">— breakout soaks · avg_R on friction-adjusted (honest) basis</span></h2>
  <div id="gate">Loading…</div>

  <!-- 5. PERFORMANCE SUMMARY -->
  <h2>Performance summary</h2>
  <div id="perf">Loading…</div>

  <!-- 6. EQUITY CHART -->
  <h2>Equity curve <span class="sub">— cumulative R (breakout soaks only)</span></h2>
  <div class="chartwrap">
    <div class="toggle" id="eqtoggle" style="margin-bottom:8px;display:flex;gap:6px">
      <button data-eq="B" class="active">Breakout B</button>
      <button data-eq="A">Breakout A</button>
      <button data-eq="ALL">All</button>
    </div>
    <canvas id="equity" width="1200" height="240"></canvas>
    <div class="sub" id="eqnote" style="margin-top:6px"></div>
  </div>

  <!-- 7. RECENT ACTIVITY -->
  <h2>Recent activity</h2>
  <div id="recent">Loading…</div>

  <!-- 8. OPEN TRADES -->
  <h2>Open trades <span class="sub">— entry geometry only · live P&amp;L not shown in V1</span></h2>
  <div id="open">Loading…</div>

  <!-- 9. EXEC QUALITY -->
  <h2>Execution quality observer</h2>
  <div id="exec">Loading…</div>

  <!-- 10. SAMPLE QUALITY / BURST -->
  <h2>Sample quality / correlated bursts</h2>
  <div id="burst">Loading…</div>

  <!-- 11. ERRORS / HEALTH -->
  <h2>Errors / health</h2>
  <div id="health">Loading…</div>

  <!-- 12. ADVANCED DIAGNOSTICS (collapsed) -->
  <h2>Advanced diagnostics</h2>
  <div id="advanced">Loading…</div>

  <div class="foot" id="foot"></div>
</div>

<script>
let LAST=null, EQ_VIEW="B";

function fmt(x,dp){ if(x===null||x===undefined||(typeof x==="number"&&isNaN(x))) return '<span class="na">—</span>';
  return (typeof x==="number")? x.toFixed(dp===undefined?2:dp) : String(x); }
function sgn(x,dp){ if(x===null||x===undefined) return '<span class="na">—</span>';
  return (x>=0?"+":"")+x.toFixed(dp===undefined?3:dp); }
function pct(x){ return (x===null||x===undefined)?'<span class="na">—</span>':(x*100).toFixed(1)+"%"; }
function pctR(x){ return (x===null||x===undefined)?'<span class="na">—</span>':x.toFixed(1)+"%"; }
function pill(cls,txt){ return `<span class="pill lvl-${cls}">${txt}</span>`; }
function dot(c){ return `<span class="dot ${c}"></span>`; }
function ago(s){ if(s===null||s===undefined) return "—"; s=Math.round(s);
  if(s<90) return s+"s"; if(s<5400) return Math.round(s/60)+"m"; if(s<172800) return Math.round(s/3600)+"h"; return Math.round(s/86400)+"d"; }

// 1. STATUS BAR
function renderStatusBar(s){
  const o=s.overall||{level:"INFO",reasons:[]}; const p=s.processes||{};
  const procDot=(x)=> x&&x.running? dot("green") : dot("red");
  const line=(k,lbl)=>{const x=p[k]||{}; return `<span>${procDot(x)}${lbl} <span class="muted">(${x.pid??"—"} · ${x.status||"—"})</span></span>`;};
  const lvlcls = o.level==="HEALTHY"?"green":o.level==="WARNING"?"yellow":"red";
  document.getElementById("statusbar").innerHTML =
    `<span class="bigpill lvl-${o.level}">${dot(lvlcls)}SYSTEM ${o.level}</span>`
    + `<div class="procline">${line("FADE","Fade")} ${line("A","Breakout A")} ${line("B","Breakout B")}</div>`
    + `<span style="margin-left:auto" class="sub mono">${s.db_read_only?"DB mode=ro ✓":"DB ?"} · `
    + `${s.ts_utc} UTC · refresh 30s</span>`;
}

// 2. STRATEGY CARDS
function strategyCard(title,mode,modeCls,body,statusPill){
  return `<div class="card"><h3><span>${title}</span>${statusPill||""}</h3>`
    + `<div class="kv"><span class="k">mode</span><span class="v">${pill(modeCls,mode)}</span></div>${body}</div>`;
}
function renderCards(s){
  const p=s.processes||{}, soaks=s.soaks||{}, eq=s.exec_quality||{};
  let html="";
  // Fade — process status only, all perf "—" by design
  const f=p.FADE||{};
  html += strategyCard("Production Fade","LIVE","INFO",
    `<div class="kv"><span class="k">PID</span><span class="v mono">${f.pid??"—"}</span></div>`
    +`<div class="kv"><span class="k">process</span><span class="v">${f.running?"running":"stopped"}</span></div>`
    +`<div class="kv"><span class="k">age</span><span class="v">${ago(f.age_seconds)}</span></div>`
    +`<div class="kv"><span class="k">N / avg_R / R</span><span class="v na">— not available in V1</span></div>`
    +`<div class="sub" style="margin-top:6px">Monitored separately (no signals.db read in V1).</div>`,
    f.running?pill("running","RUNNING"):pill("stopped","STOPPED"));
  // Soaks A + B
  for(const k of ["A","B"]){
    const so=soaks[k]||{}, m=so.metrics||{}, hb=so.soak_health||{}, pr=p[k]||{};
    const vc=so.verdict_overall||"PENDING";
    html += strategyCard("Breakout Soak "+k,"PAPER","INFO",
      `<div class="kv"><span class="k">PID</span><span class="v mono">${pr.pid??hb.pid??"—"} ${pr.running?"":'<span class="err">stopped</span>'}</span></div>`
      +`<div class="kv"><span class="k">open / closed</span><span class="v">${m.n_open??0} / ${m.n_closed??0}</span></div>`
      +`<div class="kv"><span class="k">total R</span><span class="v">${sgn(m.sum_R)}</span></div>`
      +`<div class="kv"><span class="k">last cycle</span><span class="v">${ago(hb.heartbeat_age_s)} ago</span></div>`
      +`<div class="kv"><span class="k">last signal</span><span class="v mono" style="font-size:11px">${hb.last_signal_ts??"—"}</span></div>`
      +`<div class="sub" style="margin-top:6px">${plainSoak(so)}</div>`,
      pill(vc==="PASS"?"PASS":vc==="FAIL"?"FAIL":"PENDING",vc));
  }
  // Exec quality observer
  html += strategyCard("Execution Quality","OBSERVATION","INFO",
    `<div class="kv"><span class="k">snapshots</span><span class="v">${eq.total??0}</span></div>`
    +`<div class="kv"><span class="k">fetch ok / failed</span><span class="v">${eq.fetch_ok??0} / ${eq.fetch_failed??0}</span></div>`
    +`<div class="kv"><span class="k">would_skip</span><span class="v">${eq.would_skip_count??0} (${eq.would_skip_rate==null?"—":eq.would_skip_rate+"%"})</span></div>`
    +`<div class="kv"><span class="k">trade affected</span><span class="v ok" style="padding:0 6px;border-radius:4px">NO</span></div>`,
    pill("INFO","OBSERVE"));
  document.getElementById("cards").innerHTML=html;
}
function plainSoak(so){
  const m=so.metrics||{}, vc=so.verdict_overall;
  if(so.error) return "DB error: "+so.error;
  if((m.n_closed||0)===0) return "Running in paper mode. No closed trades yet.";
  if(vc==="PENDING") return `Paper mode. ${m.n_closed}/30 closed — gate PENDING until n≥30.`;
  if(vc==="FAIL") return "Gate FAIL on friction-adjusted basis — consistent with validated-negative.";
  if(vc==="PASS") return "Gate PASS on friction-adjusted basis (review before any action).";
  return "Paper mode.";
}

// 3. DECISION PANEL
function renderDecision(s){
  const o=s.overall||{}, soaks=s.soaks||{}, eq=s.exec_quality||{};
  let msgs=[], action="OBSERVE ONLY — no live arming.", cls=o.level||"HEALTHY";
  // process health
  if(o.level==="ERROR"){ action="INVESTIGATE — a monitored process is down or DB read failed."; }
  else if(o.level==="WARNING"){ action="CHECK — a process or heartbeat needs attention; data may be stale."; }
  // gate framing
  const verds=["A","B"].map(k=>(soaks[k]||{}).verdict_overall);
  const nB=((soaks.B||{}).metrics||{}).n_closed||0, nA=((soaks.A||{}).metrics||{}).n_closed||0;
  if(verds.every(v=>v==="PENDING")){
    msgs.push(`Breakout soaks running in paper mode. Gate PENDING (A n=${nA}, B n=${nB}; need n≥30 closed each).`);
    msgs.push("On the friction-adjusted (honest) basis the backtest avg_R is below +0.40 — consistent with the validated-negative finding. Action: observe only; no live arming.");
  } else if(verds.includes("FAIL")){
    msgs.push("At least one breakout soak reads FAIL on the friction-adjusted basis — consistent with the validated-negative conclusion. No live arming.");
  } else if(verds.includes("PASS")){
    msgs.push("A breakout soak reads PASS on the friction-adjusted basis. Review the gate table + sample quality before considering anything; this dashboard does not arm anything.");
  }
  // exec quality
  const tot=eq.total||0;
  if(tot===0) msgs.push("Exec-quality logging active but no snapshots yet (first row appears on the next breakout signal).");
  else if(tot<30) msgs.push(`Exec-quality logging active; ${tot} snapshot(s) so far — too few for analysis yet (need n≥30–60).`);
  else msgs.push(`Exec-quality has ${tot} snapshots (would_skip ${eq.would_skip_rate??"—"}%). Ready for a separate would_skip-vs-outcome analysis.`);
  document.getElementById("decision").innerHTML =
    `<div class="panel decision ${cls}">`
    + msgs.map(m=>`<div>• ${m}</div>`).join("")
    + `<div class="action">Recommended: ${action}</div></div>`;
}

// 4. GATE CHECKLIST
function gcell(ge){ if(!ge) return '<span class="na">—</span>';
  const st=ge.status||"PENDING";
  return pill(st==="PASS"?"PASS":st==="FAIL"?"FAIL":"PENDING",st); }
function renderGate(s){
  const A=s.soaks.A||{}, B=s.soaks.B||{};
  const gA=A.gate_eval||{}, gB=B.gate_eval||{}, mA=A.metrics||{}, mB=B.metrics||{};
  const nrow=(lbl,req,va,vb,sa,sb)=>`<tr><td>${lbl}</td><td>${req}</td>`
    +`<td class="num">${va}</td><td>${gcell(sa)}</td>`
    +`<td class="num">${vb}</td><td>${gcell(sb)}</td></tr>`;
  const avgCell=(g)=> g.avg_R? `${sgn(g.avg_R.value)} <span class="sub">(clean ${sgn(g.avg_R.value_clean)} ×${g.avg_R.haircut})</span>` : "—";
  const nstat=(m)=>({status:(m.n_closed||0)>=30?"PASS":"PENDING"});
  let html=`<div class="warnbox">avg_R gate is evaluated on the FRICTION-ADJUSTED value (clean × friction/clean haircut), so the live verdict matches the honest validated-negative conclusion. Clean avg_R shown for reference.</div>`;
  html+=`<table><thead><tr><th>Metric</th><th>Required</th><th class="num">Soak A</th><th>A</th><th class="num">Soak B</th><th>B</th></tr></thead><tbody>`;
  html+=nrow("Closed signals","n ≥ 30",mA.n_closed??0,mB.n_closed??0,nstat(mA),nstat(mB));
  html+=nrow("avg_R (friction-adj)","≥ +0.40",avgCell(gA),avgCell(gB),gA.avg_R,gB.avg_R);
  html+=nrow("Win rate","≥ 58%",pctR((gA.win_rate||{}).value*100),pctR((gB.win_rate||{}).value*100),gA.win_rate,gB.win_rate);
  html+=nrow("Profit factor","≥ 2.0",fmt((gA.profit_factor||{}).value),fmt((gB.profit_factor||{}).value),gA.profit_factor,gB.profit_factor);
  html+=nrow("Max drawdown","≤ 20 R",fmt((gA.max_drawdown||{}).value),fmt((gB.max_drawdown||{}).value),gA.max_drawdown,gB.max_drawdown);
  html+=nrow("DSR","live ≥ 0.95",'<span class="na">— not live-computed</span>','<span class="na">— not live-computed</span>',null,null);
  html+=nrow("Burst warning","no large burst",burstFlag(A),burstFlag(B),burstStat(A),burstStat(B));
  html+=`</tbody></table>`;
  html+=`<div class="grid g2" style="margin-top:10px">`
    +`<div class="card"><h3>Soak A verdict ${pill(A.verdict_overall==="PASS"?"PASS":A.verdict_overall==="FAIL"?"FAIL":"PENDING",A.verdict_overall||"PENDING")}</h3><div class="sub">${plainSoak(A)}</div></div>`
    +`<div class="card"><h3>Soak B verdict ${pill(B.verdict_overall==="PASS"?"PASS":B.verdict_overall==="FAIL"?"FAIL":"PENDING",B.verdict_overall||"PENDING")}</h3><div class="sub">${plainSoak(B)}</div></div></div>`;
  document.getElementById("gate").innerHTML=html;
}
function burstFlag(so){ const d=so.dashboard||{}; const b=(d.bursts||[]).length; return b?`${b} burst(s)`:"none"; }
function burstStat(so){ const d=so.dashboard||{}; const big=(d.bursts||[]).some(x=>x.big); return {status: big?"PENDING":"PASS"}; }

// 5. PERFORMANCE SUMMARY
function renderPerf(s){
  const rows=[];
  const f=s.processes.FADE||{};
  rows.push(`<tr><td>Production Fade</td><td>${pill("INFO","LIVE")}</td>`
    +`<td class="num na">—</td><td class="num na">—</td><td class="num na">—</td><td class="num na">—</td>`
    +`<td class="num na">—</td><td class="num na">—</td><td class="num na">—</td>`
    +`<td>${f.running?pill("running","running"):pill("stopped","stopped")}</td></tr>`);
  for(const k of ["A","B"]){
    const so=s.soaks[k]||{}, m=so.metrics||{}, g=so.gate_eval||{};
    const avg = g.avg_R? `${sgn(g.avg_R.value)} <span class="sub">clean ${sgn(g.avg_R.value_clean)}</span>` : sgn(m.avg_R);
    rows.push(`<tr><td>Breakout ${k}</td><td>${pill("INFO","PAPER")}</td>`
      +`<td class="num">${m.n_closed??0}</td><td class="num">${avg}</td>`
      +`<td class="num">${sgn(m.sum_R)}</td><td class="num">${pct(m.win_rate)}</td>`
      +`<td class="num">${fmt(m.profit_factor)}</td><td class="num">${fmt(m.max_drawdown_R)}</td>`
      +`<td class="num">${m.n_open??0}</td>`
      +`<td>${pill(so.verdict_overall==="PASS"?"PASS":so.verdict_overall==="FAIL"?"FAIL":"PENDING",so.verdict_overall||"PENDING")}</td></tr>`);
  }
  document.getElementById("perf").innerHTML=
    `<div class="scroll"><table><thead><tr><th>Strategy</th><th>Mode</th><th class="num">N</th>`
    +`<th class="num">avg_R</th><th class="num">sum_R</th><th class="num">WR</th><th class="num">PF</th>`
    +`<th class="num">maxDD</th><th class="num">Open</th><th>Status</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    +`<div class="sub" style="margin-top:6px">Breakout avg_R shows friction-adjusted (gated) with clean below. Fade metrics are not available in V1 (no signals.db read).</div>`;
}

// 6. EQUITY CHART
function eqSeries(so){ return ((so.dashboard||{}).equity_series||[]).map(p=>p.cum_R); }
function renderEquity(s){
  const cv=document.getElementById("equity"), ctx=cv.getContext("2d");
  const W=cv.width=cv.clientWidth*2, H=cv.height=480; ctx.scale(1,1);
  ctx.clearRect(0,0,W,H);
  const sets=[];
  if(EQ_VIEW==="A"||EQ_VIEW==="ALL") sets.push({d:eqSeries(s.soaks.A),c:"#58a6ff",n:"A"});
  if(EQ_VIEW==="B"||EQ_VIEW==="ALL") sets.push({d:eqSeries(s.soaks.B),c:"#3fb950",n:"B"});
  let allv=[].concat(...sets.map(x=>x.d));
  const note=document.getElementById("eqnote");
  if(!allv.length){ ctx.fillStyle="#6e7681"; ctx.font="24px sans-serif";
    ctx.fillText("No closed trades yet — equity curve appears as trades close.",30,H/2);
    note.textContent=""; return; }
  const maxN=Math.max(...sets.map(x=>x.d.length),1);
  let lo=Math.min(0,...allv), hi=Math.max(0,...allv); if(hi===lo)hi=lo+1;
  const pad=44, x=(i)=>pad+(W-2*pad)*(maxN<=1?0.5:i/(maxN-1)), y=(v)=>H-pad-(H-2*pad)*(v-lo)/(hi-lo);
  // zero line
  ctx.strokeStyle="#30363d"; ctx.lineWidth=2; ctx.beginPath(); ctx.moveTo(pad,y(0)); ctx.lineTo(W-pad,y(0)); ctx.stroke();
  ctx.fillStyle="#8b949e"; ctx.font="20px sans-serif"; ctx.fillText("0R",6,y(0)+6);
  ctx.fillText(hi.toFixed(1)+"R",6,y(hi)+14); ctx.fillText(lo.toFixed(1)+"R",6,y(lo)-2);
  for(const set of sets){
    if(!set.d.length) continue;
    ctx.strokeStyle=set.c; ctx.lineWidth=3; ctx.beginPath();
    set.d.forEach((v,i)=>{ const px=x(i),py=y(v); i?ctx.lineTo(px,py):ctx.moveTo(px,py); });
    ctx.stroke();
  }
  note.innerHTML = sets.map(x=>`<span style="color:${x.c}">●</span> Soak ${x.n} (${x.d.length} closes, end ${x.d.length?sgn(x.d[x.d.length-1]):"—"}R)`).join("  ·  ");
}

// 7. RECENT ACTIVITY
function renderRecent(s){
  let evs=[];
  for(const k of ["A","B"]){
    const so=s.soaks[k]||{};
    (so.closed||[]).forEach(c=>evs.push({ts:c.closed_at||c.opened_ts,strat:"Breakout "+k,token:c.token,dir:c.direction,
      event:"close",outcome:c.result,r:c.realized_r,note:""}));
    (so.open||[]).forEach(o=>evs.push({ts:o.opened_ts,strat:"Breakout "+k,token:o.token,dir:o.direction,
      event:"open",outcome:"OPEN",r:null,note:"open"}));
  }
  (s.exec_quality.recent||[]).forEach(x=>evs.push({ts:x.ts_utc,strat:"ExecQual "+(x.soak||""),token:x.token,dir:x.direction,
    event:"exec_snapshot",outcome:x.fetch_status,r:null,note:(x.would_skip===1?("would_skip: "+x.tripped_rules):"")}));
  evs=evs.filter(e=>e.ts).sort((a,b)=>(a.ts<b.ts?1:-1)).slice(0,30);
  if(!evs.length){ document.getElementById("recent").innerHTML='<div class="panel muted">No activity yet.</div>'; return; }
  const rows=evs.map(e=>`<tr><td class="mono" style="font-size:11px">${e.ts}</td><td>${e.strat}</td><td>${e.token}</td>`
    +`<td>${e.dir||"—"}</td><td>${e.event}</td><td>${outc(e.outcome)}</td>`
    +`<td class="num">${e.r==null?'<span class="na">—</span>':sgn(e.r)}</td><td class="sub">${e.note}</td></tr>`).join("");
  document.getElementById("recent").innerHTML=
    `<div class="scroll"><table><thead><tr><th>Timestamp (UTC)</th><th>Strategy</th><th>Token</th><th>Dir</th>`
    +`<th>Event</th><th>Outcome</th><th class="num">R</th><th>Note</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function outc(o){ if(!o) return "—";
  if(["WIN","PARTIAL_TP2","PARTIAL_TP2_BE","ok"].includes(o)) return `<span class="ok" style="padding:0 5px;border-radius:3px">${o}</span>`;
  if(["LOSS","fetch_failed"].includes(o)) return `<span class="err" style="padding:0 5px;border-radius:3px">${o}</span>`;
  return o; }

// 8. OPEN TRADES
function renderOpen(s){
  let rows=[];
  for(const k of ["A","B"]){
    (s.soaks[k]||{}).open?.forEach(o=>{
      rows.push(`<tr><td>Breakout ${k}</td><td>${o.token}</td><td>${o.direction}</td>`
        +`<td class="mono" style="font-size:11px">${o.opened_ts}</td><td class="num mono">${fmt(o.entry_price,6)}</td>`
        +`<td class="mono">SL ${fmt(o.sl,6)} / TP1 ${fmt(o.tp1,6)} / TP3 ${fmt(o.tp3,6)}</td>`
        +`<td class="num">${o.age_minutes==null?"—":Math.round(o.age_minutes)+"m"}</td><td>${pill("INFO","OPEN")}</td></tr>`);
    });
  }
  if(!rows.length){ document.getElementById("open").innerHTML='<div class="panel muted">No open trades.</div>'; return; }
  document.getElementById("open").innerHTML=
    `<div class="scroll"><table><thead><tr><th>Strategy</th><th>Token</th><th>Dir</th><th>Entry time</th>`
    +`<th class="num">Entry</th><th>TP/SL levels</th><th class="num">Age</th><th>Status</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    +`<div class="sub" style="margin-top:6px">Live current price and unrealized R are not shown in V1 (no live price fetch).</div>`;
}

// 9. EXEC QUALITY
function renderExec(s){
  const e=s.exec_quality||{};
  const lt=e.latest;
  let html=`<div class="warnbox">Observation only. would_skip is logged for future analysis and does <b>not</b> affect entries/exits.</div>`;
  html+=`<div class="grid g4">`
    +card2("Mode",e.mode||"—")+card2("Snapshots",e.total??0)
    +card2("Fetch ok / failed",(e.fetch_ok??0)+" / "+(e.fetch_failed??0))
    +card2("would_skip",`${e.would_skip_count??0} (${e.would_skip_rate==null?"—":e.would_skip_rate+"%"})`)+`</div>`;
  if(lt){
    html+=`<div class="card" style="margin-top:10px"><h3>Latest snapshot <span class="sub">${lt.ts_utc} · soak ${lt.soak}</span></h3>`
      +`<div class="grid g4">`
      +card2("Token / dir",(lt.token||"—")+" "+(lt.direction||""))
      +card2("Spread",lt.spread_pct==null?"—":lt.spread_pct.toFixed(3)+"%")
      +card2("Exp. slippage",lt.est_slippage_pct==null?"—":lt.est_slippage_pct.toFixed(3)+"%")
      +card2("Depth ratio",lt.depth_ratio==null?"—":lt.depth_ratio.toFixed(1)+"×")
      +card2("would_skip",lt.would_skip===1?pill("FAIL","YES"):pill("PASS","NO"))
      +card2("Reasons",lt.tripped_rules||"—")
      +card2("Fetch",lt.fetch_status)
      +card2("Trade affected",'<span class="ok" style="padding:0 6px;border-radius:4px">NO</span>')+`</div></div>`;
  } else {
    html+=`<div class="panel muted" style="margin-top:10px">No snapshots yet — first row appears on the next breakout signal.</div>`;
  }
  document.getElementById("exec").innerHTML=html;
}
function card2(k,v){ return `<div class="card"><div class="kv"><span class="k">${k}</span></div><div class="v" style="font-size:16px">${v}</div></div>`; }

// 10. BURST
function renderBurst(s){
  let html=`<div class="grid g2">`;
  for(const k of ["A","B"]){
    const d=(s.soaks[k]||{}).dashboard||{};
    const ind=d.independent_event_count, bsig=d.burst_signal_count, bursts=d.bursts||[];
    const big=bursts.length?bursts.reduce((a,b)=>Math.abs(b.sum_R)>Math.abs(a.sum_R)?b:a):null;
    html+=`<div class="card"><h3>Soak ${k}</h3>`
      +`<div class="kv"><span class="k">closed trades</span><span class="v">${((s.soaks[k]||{}).metrics||{}).n_closed??0}</span></div>`
      +`<div class="kv"><span class="k">independent events</span><span class="v">${ind??"—"}</span></div>`
      +`<div class="kv"><span class="k">burst groups (≥2 same bar)</span><span class="v">${bursts.length}</span></div>`
      +`<div class="kv"><span class="k">signals in bursts</span><span class="v">${bsig??0}</span></div>`
      +`<div class="kv"><span class="k">largest burst</span><span class="v">${big?(big.n+" sigs, "+sgn(big.sum_R)+"R"):"—"}</span></div>`
      +`<div class="sub" style="margin-top:6px">${bursts.length?"Some trades occurred in the same market burst, so the independent sample is smaller than the trade count.":"No correlated bursts detected."}</div></div>`;
  }
  html+=`</div>`;
  document.getElementById("burst").innerHTML=html;
}

// 11. ERRORS / HEALTH
function renderHealth(s){
  const o=s.overall||{}; let rows=[];
  for(const k of ["A","B"]){
    const so=s.soaks[k]||{}, hb=so.soak_health||{}, pr=(s.processes||{})[k]||{};
    rows.push(`<tr><td>Breakout ${k}</td><td>${pr.running?pill("running","running"):pill("stopped","stopped")}</td>`
      +`<td class="mono" style="font-size:11px">${hb.heartbeat_ts_utc??"—"}</td><td>${ago(hb.heartbeat_age_s)} ago</td>`
      +`<td>${hb.status==="STALE"?pill("WARNING","STALE"):pill("PASS",hb.status||"—")}</td>`
      +`<td>${so.error?('<span class="err">'+so.error+'</span>'):"—"}</td></tr>`);
  }
  const f=(s.processes||{}).FADE||{};
  rows.push(`<tr><td>Production Fade</td><td>${f.running?pill("running","running"):pill("stopped","stopped")}</td>`
    +`<td colspan="3" class="muted">heartbeat not read in V1 (process check only)</td><td>—</td></tr>`);
  document.getElementById("health").innerHTML=
    `<div class="panel ${o.level==="HEALTHY"?"":"decision "+o.level}"><b>Overall: ${pill(o.level,o.level)}</b>`
    +(o.reasons||[]).map(r=>`<div>• ${r}</div>`).join("")
    +`<div class="kv" style="margin-top:6px"><span class="k">DB read</span><span class="v">${s.db_read_only?"OK (mode=ro)":"?"}</span></div>`
    +`<div class="kv"><span class="k">exec fetch failures</span><span class="v">${(s.exec_quality||{}).fetch_failed??0}</span></div></div>`
    +`<table style="margin-top:10px"><thead><tr><th>Process</th><th>State</th><th>Last heartbeat</th><th>Age</th><th>HB status</th><th>Last error</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

// 12. ADVANCED (collapsed)
function renderAdvanced(s){
  let html="";
  for(const k of ["A","B"]){
    const d=(s.soaks[k]||{}).dashboard||{}, oc=d.outcome_counts||{}, er=d.exit_reasons||{}, bursts=d.bursts||[];
    const ocrows=Object.entries(oc).sort((a,b)=>b[1]-a[1]).map(([x,n])=>`<tr><td>${x}</td><td class="num">${n}</td></tr>`).join("")||'<tr><td class="muted" colspan=2>none</td></tr>';
    const errows=Object.entries(er).sort((a,b)=>b[1]-a[1]).map(([x,n])=>`<tr><td>${x}</td><td class="num">${n}</td></tr>`).join("")||'<tr><td class="muted" colspan=2>none</td></tr>';
    const brows=bursts.slice(-12).map(b=>`<tr><td class="mono" style="font-size:11px">${b.ts}</td><td>${b.dir}</td><td class="num">${b.n}</td><td class="num">${sgn(b.sum_R)}</td><td class="sub">${(b.tokens||[]).join(",")}</td></tr>`).join("")||'<tr><td class="muted" colspan=5>none</td></tr>';
    html+=`<details><summary>Soak ${k} — exit-reason &amp; burst detail</summary>`
      +`<div class="grid g2" style="margin-top:8px"><div><b>Outcome counts</b><table><tbody>${ocrows}</tbody></table></div>`
      +`<div><b>Exit reasons</b><table><tbody>${errows}</tbody></table></div></div>`
      +`<b>Burst groups (last 12)</b><table><thead><tr><th>bar (UTC)</th><th>dir</th><th class="num">n</th><th class="num">sum_R</th><th>tokens</th></tr></thead><tbody>${brows}</tbody></table>`
      +`<div class="sub" style="margin-top:6px">best_R ${sgn(d.best_R)} · worst_R ${sgn(d.worst_R)}</div></details>`;
  }
  html+=`<details><summary>Backtest reference (720d, informational — NOT a gate)</summary>`
    +`<table><thead><tr><th>Soak</th><th>clean avg_R</th><th>friction avg_R</th><th>haircut</th></tr></thead><tbody>`
    +["A","B"].map(k=>{const g=((s.soaks[k]||{}).gate_eval||{}).avg_R||{};const m=(s.soaks[k]||{}).metrics||{};
       return `<tr><td>${k}</td><td class="num na">backtest: see docs</td><td class="num">${(s.soaks[k]||{}).ref_avg_R??"—"}</td><td class="num">${m.friction_haircut??"—"}</td></tr>`;}).join("")
    +`</tbody></table><div class="sub">Both friction refs are below +0.40 (validated-negative). Near-miss analysis is not available in V1 (requires a price fetch).</div></details>`;
  document.getElementById("advanced").innerHTML=html;
}

function renderAll(){
  if(!LAST) return;
  try{ renderStatusBar(LAST); renderCards(LAST); renderDecision(LAST); renderGate(LAST);
    renderPerf(LAST); renderEquity(LAST); renderRecent(LAST); renderOpen(LAST);
    renderExec(LAST); renderBurst(LAST); renderHealth(LAST); renderAdvanced(LAST);
    document.getElementById("foot").textContent="Last refresh: "+LAST.ts_utc+" UTC · read-only · breakout.db (mode=ro) + process checks · no live price fetch · no signals.db read";
  }catch(e){ document.getElementById("foot").textContent="render error: "+e.message; }
}
document.querySelectorAll("#eqtoggle button").forEach(b=>b.onclick=()=>{
  EQ_VIEW=b.dataset.eq;
  document.querySelectorAll("#eqtoggle button").forEach(x=>x.classList.toggle("active",x===b));
  if(LAST) renderEquity(LAST);
});
async function refresh(){
  try{ const r=await fetch("/api/state",{cache:"no-store"});
    if(!r.ok){ document.getElementById("foot").textContent="FETCH ERROR "+r.status; return; }
    LAST=await r.json(); renderAll();
  }catch(e){ document.getElementById("foot").textContent="FETCH ERROR: "+e.message; }
}
window.addEventListener("resize",()=>{ if(LAST) renderEquity(LAST); });
refresh(); setInterval(refresh,30000);
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
        # V1: /api/nearmiss REMOVED — it required a live Binance price fetch, which
        # is forbidden in V1. Only /api/state (read-only DB + process checks) remains.
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
    # SO_REUSEADDR: allow immediate rebind over a TIME_WAIT/closed socket left by
    # a just-killed viewer (fixes spurious "Address already in use" on relaunch).
    # This does NOT permit two *actively listening* viewers on the same port — a
    # genuinely-running viewer still makes the second bind fail loudly.
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((HOST, PORT), ViewerHandler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n  shutdown.")


if __name__ == "__main__":
    main()
