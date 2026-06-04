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
import urllib.error
import urllib.request
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
        "ref_avg_R":    0.3376,  # friction backtest ref, POST-TP2 TRAIL model 720d (2026-06-04); was 0.4536 pre-trail
        "ref_source":   "POST-TP2 trail sweep (run_posttp2_backtests.py)",
    },
    {
        "key":          "B",
        "label":        "Soak B — 5M / 1H",
        "soak_label":   "H4_BREAKOUT_PAPER_SOAK_B",
        "heartbeat":    _BREAKOUT_DIR / "data" / "breakout_soak_B_heartbeat.json",
        "pid_file":     _BREAKOUT_DIR / "data" / "breakout_soak_B.pid",
        "ref_avg_R":    0.3644,  # friction backtest ref, POST-TP2 TRAIL model 720d (2026-06-04); was 0.4840 pre-trail
        "ref_source":   "POST-TP2 trail sweep (run_posttp2_backtests.py)",
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
# POST-TP2 TRAIL model (2026-06-04). Pre-trail numbers were avg_R A=0.4536 / B=0.4840;
# the trail-to-TP1 caps post-TP2 reversals, lowering avg_R ~0.12 while WR is ~unchanged
# (reclassified WIN->PARTIAL_TP2_T1 trades stay positive-R). Recomputed via run_posttp2_backtests.py.
BACKTEST_REFERENCE = {
    "A": {"tf": "5M/4H", "n": 4744,  "avg_R": 0.3376, "wr_pct": 68.25, "pf": 2.125, "dsr": 1.0},
    "B": {"tf": "5M/1H", "n": 12090, "avg_R": 0.3644, "wr_pct": 70.63, "pf": 2.334, "dsr": 1.0},
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
    if res == "PARTIAL_TP2_T1":
        return "PARTIAL_TP2_T1"   # POST-TP2 TRAIL FIX: TP2 reached, trailed out at TP1
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


# ── Open-position tier-status computation (DISPLAY-ONLY) ─────────────────
# Mirrors the soak's resolve_open_signals BE-after-TP1 walk EXACTLY, so the
# tier coloring shown for open positions matches what the soak would classify
# at the same moment. This is computed READ-ONLY in the viewer (the soak
# doesn't persist tp_hit flags for OPEN signals — only at terminal close).
#
# DOES NOT enter gate math or verdict logic. DOES NOT write anything.
# Graceful degradation: if the Binance fetch fails, returns (None, None, None)
# and the cells render un-tinted (no false "tier hit" indication).
_BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
_VIEWER_USER_AGENT = "TradeAI-BreakoutViewer/1.0"
_TIER_FETCH_TIMEOUT = 8  # seconds — keep page-responsive on transient Binance hiccups


def _compute_open_tier_status(token: str, direction: str,
                                entry: float, sl: float,
                                tp1: float, tp2: float, tp3: float,
                                entry_ts_ms: int, now_ms: int) -> tuple:
    """Walk 5m bars from entry_ts+5min to now under the BE-after-TP1 model.

    Returns (tp1_hit, tp2_hit, tp3_hit) as ints (1 or 0) for direct
    .tpN_hit === 1 comparison in the JS render. Returns (None, None, None)
    on any fetch failure or empty result (graceful — no tint applied).
    """
    start_ms = entry_ts_ms + 5 * 60 * 1000
    if now_ms <= start_ms:
        return (0, 0, 0)  # too new — no forward bars yet, treat as no-tier-hit
    symbol = f"{token}USDT"
    url = (f"{_BINANCE_KLINE_URL}?symbol={symbol}&interval=5m&limit=1000&"
           f"startTime={start_ms}&endTime={now_ms}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _VIEWER_USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIER_FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                return (None, None, None)
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return (None, None, None)
    if not raw or not isinstance(raw, list):
        return (None, None, None)

    # MIRROR the soak's resolve_open_signals walk EXACTLY
    # (breakout_paper_soak_B.py:293-318 / breakout_paper_soak.py:339-378 under
    # the BE-after-TP1 / RUNNER-EXIT FIX 2026-06-03 model).
    tp1_hit = tp2_hit = tp3_hit = sl_hit = be_stopped = False
    t1_trail_stopped = False   # POST-TP2 TRAIL FIX parity with the soak resolver
    for bar in raw:
        h_p = float(bar[2])
        l_p = float(bar[3])
        if direction == "BUY":
            if not tp1_hit and not sl_hit and l_p <= sl:
                sl_hit = True
                break
            if not tp1_hit and h_p >= tp1:
                tp1_hit = True
                continue
            if tp1_hit and not tp2_hit and not be_stopped and l_p <= entry:
                be_stopped = True
                break
            if tp1_hit and not tp2_hit and h_p >= tp2:
                tp2_hit = True
                if h_p >= tp3:                 # same-bar TP2->TP3 strong bar = WIN
                    tp3_hit = True
                    break
                continue                       # defer TP1-trail (TP2-fills-first)
            # POST-TP2 TRAIL FIX (2026-06-04): stop trails to TP1 once TP2 hit.
            # Mirror the soak resolver EXACTLY so the open-position tier display
            # never implies a runner that the soak has already trail-closed.
            if tp2_hit and not tp3_hit and l_p <= tp1:
                t1_trail_stopped = True
                break
            if tp2_hit and not tp3_hit and h_p >= tp3:
                tp3_hit = True
                break
        else:  # SELL — mirror
            if not tp1_hit and not sl_hit and h_p >= sl:
                sl_hit = True
                break
            if not tp1_hit and l_p <= tp1:
                tp1_hit = True
                continue
            if tp1_hit and not tp2_hit and not be_stopped and h_p >= entry:
                be_stopped = True
                break
            if tp1_hit and not tp2_hit and l_p <= tp2:
                tp2_hit = True
                if l_p <= tp3:                 # same-bar TP2->TP3 strong bar = WIN
                    tp3_hit = True
                    break
                continue                       # defer TP1-trail (TP2-fills-first)
            if tp2_hit and not tp3_hit and h_p >= tp1:
                t1_trail_stopped = True
                break
            if tp2_hit and not tp3_hit and l_p <= tp3:
                tp3_hit = True
                break
    return (1 if tp1_hit else 0, 1 if tp2_hit else 0, 1 if tp3_hit else 0)


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
            # Compute current tier-hit status under BE-after-TP1 model (DISPLAY-ONLY).
            # Mirrors the soak's resolve_open_signals walk EXACTLY. Reads nothing
            # from the DB beyond the SELECT above; fetches fresh 5m bars from
            # Binance per open position. Failures → (None, None, None) → cells
            # render un-tinted (graceful degradation).
            try:
                entry_dt = datetime.strptime(d["opened_ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                entry_ts_ms = int(entry_dt.timestamp() * 1000)
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                tier_t1, tier_t2, tier_t3 = _compute_open_tier_status(
                    d["token"], d["direction"],
                    d["entry_price"], d["sl"], d["tp1"], d["tp2"], d["tp3"],
                    entry_ts_ms, now_ms,
                )
                d["tp1_hit"] = tier_t1
                d["tp2_hit"] = tier_t2
                d["tp3_hit"] = tier_t3
            except (ValueError, TypeError, KeyError):
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
        n_wins_p2 = sum(1 for r in closed if r["result"] in ("WIN", "PARTIAL_TP2", "PARTIAL_TP2_T1"))  # kept for n_wins display
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

        # Display-only Dashboard/Reports aggregates (read-only, NOT gate inputs).
        out["dashboard"] = _dashboard_aggregates(closed)
        out["backtest_ref"] = BACKTEST_REFERENCE.get(spec["key"], {})
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


# ── Near-miss analysis (LAZY, cached, button-triggered) ──────────────────────
# For every FULL_SL (LOSS with no TP1), reconstruct how far price travelled toward
# TP1 before reversing to SL (MFE fraction). This needs the price path, which the
# DB does NOT store (results.mfe_pct is empty) — so we fetch 5m bars from Binance.
# Because that is a network operation, it is NEVER run on the 30s auto-refresh; the
# Reports tab calls /api/nearmiss only when the operator clicks "Load near-miss".
# Results are cached by signal_id (closed signals are immutable) so a second click
# is instant. Graceful: a failed fetch marks that signal "unknown", never crashes.
# DISPLAY-ONLY — distinguishes choppy-stopout (near-miss) from wrong-direction.
_NEARMISS_CACHE = {}  # sid -> {"frac": float|None, "day": str, "token": str}


def _nearmiss_frac(token, direction, entry, tp1, opened_ts, closed_at):
    """MFE fraction toward TP1 over [opened, closed]; None if unavailable."""
    try:
        o_dt = datetime.strptime(opened_ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        c_dt = datetime.strptime(closed_at[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    start_ms = int(o_dt.timestamp() * 1000)
    end_ms = int(c_dt.timestamp() * 1000)
    symbol = f"{token}USDT"
    url = (f"{_BINANCE_KLINE_URL}?symbol={symbol}&interval=5m&limit=1000&"
           f"startTime={start_ms}&endTime={end_ms}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _VIEWER_USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIER_FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if not raw or not isinstance(raw, list) or entry == tp1:
        return None
    if direction == "BUY":
        mfe = max(float(b[2]) for b in raw)          # highest high
        frac = (mfe - entry) / (tp1 - entry)
    else:
        mfe = min(float(b[3]) for b in raw)          # lowest low
        frac = (entry - mfe) / (entry - tp1)
    return max(0.0, frac)


def compute_nearmiss(soak_key: str) -> dict:
    spec = next((s for s in SOAKS if s["key"] == soak_key), None)
    if spec is None:
        return {"error": f"unknown soak {soak_key}"}
    try:
        conn = _open_ro_conn()
    except FileNotFoundError:
        return {"error": "breakout.db missing"}
    try:
        rows = list(conn.execute(
            "SELECT s.id AS sid, s.token, s.signal AS direction, s.timestamp AS opened_ts, "
            "       s.entry_price, s.tp1, r.closed_at "
            "FROM signals s JOIN results r ON r.signal_id = s.id "
            "WHERE s.source = ? AND s.status = 'CLOSED' AND r.result = 'LOSS' "
            "      AND (r.tp1_hit = 0 OR r.tp1_hit IS NULL) "
            "ORDER BY s.timestamp", (spec["soak_label"],)))
    finally:
        conn.close()

    buckets = {"near_miss": 0, "mid": 0, "wrong_dir": 0, "unknown": 0}
    by_day = {}
    details = []
    for r in rows:
        sid = r["sid"]
        if sid not in _NEARMISS_CACHE:
            frac = _nearmiss_frac(r["token"], r["direction"], r["entry_price"],
                                  r["tp1"], r["opened_ts"], r["closed_at"])
            _NEARMISS_CACHE[sid] = {"frac": frac, "day": str(r["opened_ts"])[:10],
                                    "token": r["token"]}
        c = _NEARMISS_CACHE[sid]
        frac = c["frac"]
        if frac is None:
            bucket = "unknown"
        elif frac >= 0.5:
            bucket = "near_miss"
        elif frac < 0.25:
            bucket = "wrong_dir"
        else:
            bucket = "mid"
        buckets[bucket] += 1
        day = c["day"]
        d = by_day.setdefault(day, {"day": day, "full_sl": 0, "near_miss": 0})
        d["full_sl"] += 1
        if bucket == "near_miss":
            d["near_miss"] += 1
        details.append({"sid": sid, "token": r["token"], "dir": r["direction"],
                        "frac": round(frac, 3) if frac is not None else None,
                        "bucket": bucket})
    return {
        "soak": soak_key,
        "total_full_sl": len(rows),
        "buckets": buckets,
        "by_day": sorted(by_day.values(), key=lambda x: x["day"]),
        "details": details,
        "note": ("Near-miss = FULL_SL that reached >=50% of the way to TP1 before "
                 "reversing to SL (choppy stop-out). wrong_dir = <25% (signal wrong "
                 "from the start). Reconstructed from Binance 5m bars; DISPLAY-ONLY."),
    }


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

  /* ── Tabs ───────────────────────────────────────────────────────────── */
  .tabs { display: flex; gap: 4px; border-bottom: 1px solid #30363d; margin: 12px 0 16px 0; flex-wrap: wrap; }
  .tab-btn { background: #161b22; color: #7d8590; border: 1px solid #30363d; border-bottom: none;
             border-radius: 6px 6px 0 0; padding: 7px 16px; font-size: 12px; font-weight: 600;
             cursor: pointer; letter-spacing: 0.3px; }
  .tab-btn:hover { color: #e6edf3; }
  .tab-btn.active { background: #0d1117; color: #fff; border-color: #30363d; position: relative; top: 1px; }
  .tab-btn .dot { font-size: 9px; vertical-align: middle; margin-left: 5px; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  /* ── Dashboard controls ─────────────────────────────────────────────── */
  .controls { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; margin-bottom: 14px; }
  .seg { display: inline-flex; border: 1px solid #30363d; border-radius: 6px; overflow: hidden; }
  .seg button { background: #161b22; color: #7d8590; border: none; padding: 5px 12px; font-size: 11px;
                font-weight: 600; cursor: pointer; }
  .seg button.active { background: #1f6feb; color: #fff; }
  .seg-label { font-size: 10px; color: #6e7681; text-transform: uppercase; letter-spacing: 0.5px; margin-right: 6px; }
  /* ── KPI cards (R-based) ────────────────────────────────────────────── */
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin-bottom: 14px; }
  .kpi { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 11px 13px; }
  .kpi .k-label { color: #7d8590; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
  .kpi .k-value { color: #fff; font-size: 22px; font-weight: 700; margin-top: 4px; }
  .kpi .k-sub { font-size: 10px; color: #6e7681; margin-top: 3px; }
  .kpi.pass { border-color: #2ea043; } .kpi.fail { border-color: #da3633; } .kpi.pending { border-color: #9e6a03; }
  .kpi .k-value.pos { color: #3fb950; } .kpi .k-value.neg { color: #f85149; }
  /* ── Gate verdict banner ────────────────────────────────────────────── */
  .banner { border-radius: 10px; padding: 14px 18px; margin-bottom: 16px; border: 2px solid; }
  .banner.pass    { background: #0f2417; border-color: #2ea043; }
  .banner.fail    { background: #2a1213; border-color: #da3633; }
  .banner.pending { background: #241c08; border-color: #9e6a03; }
  .banner .b-verdict { font-size: 24px; font-weight: 800; letter-spacing: 1px; }
  .banner .b-verdict.pass { color: #3fb950; } .banner .b-verdict.fail { color: #f85149; } .banner .b-verdict.pending { color: #d29922; }
  .banner .b-caption { font-size: 12px; color: #c9d1d9; margin-top: 6px; line-height: 1.45; }
  .banner .b-crit { display: inline-flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
  .banner .b-chip { font-size: 10px; padding: 3px 8px; border-radius: 4px; background: #0d1117; border: 1px solid #30363d; }
  .banner .b-chip.pass { border-color: #2ea043; color: #3fb950; }
  .banner .b-chip.fail { border-color: #da3633; color: #f85149; }
  .banner .b-chip.pending { border-color: #9e6a03; color: #d29922; }
  /* ── Charts ─────────────────────────────────────────────────────────── */
  .chart-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
  .chart-box { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 12px; flex: 1 1 280px; }
  .chart-box .c-title { font-size: 11px; color: #7d8590; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
  .chart-box .c-note { font-size: 9px; color: #6e7681; margin-top: 6px; }
  .legend { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; font-size: 10px; color: #c9d1d9; }
  .legend .lg { display: inline-flex; align-items: center; gap: 4px; }
  .legend .sw { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
  .honest { background: #241c08; border: 1px dashed #9e6a03; border-radius: 6px; padding: 8px 12px;
            margin-bottom: 14px; font-size: 11px; color: #e3b341; line-height: 1.5; }
  .ref-card { background: #0c1a2e; border: 1px solid #1f4d8a; border-radius: 8px; padding: 12px 16px; }
  .ref-card .rc-title { color: #58a6ff; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
  .burst-big td { background: rgba(210,153,34,0.12); }
  .btn { background: #1f6feb; color: #fff; border: none; border-radius: 6px; padding: 7px 14px;
         font-size: 11px; font-weight: 600; cursor: pointer; }
  .btn:disabled { background: #30363d; color: #7d8590; cursor: default; }
</style>
</head>
<body>
<h1>BREAKOUT PAPER SOAKS — Read-only viewer</h1>
<div class="small mono">port 8890 · DB read-only · refresh 30s · gate stays avg_R≥0.40 · WR≥0.58 · PF≥2.0 · maxDD≤20R · n≥30 (per-soak, never blended)</div>

<div class="tabs" id="tabs">
  <button class="tab-btn active" data-tab="dashboard">Dashboard</button>
  <button class="tab-btn" data-tab="soakB">Soak B (Primary)</button>
  <button class="tab-btn" data-tab="soakA">Soak A (bg)</button>
  <button class="tab-btn" data-tab="reports">Reports</button>
</div>

<div class="tab-panel active" id="panel-dashboard"><div id="dash-body">Loading…</div></div>
<div class="tab-panel" id="panel-soakB"><div class="soak-col" id="col-B"><h3>Loading…</h3></div></div>
<div class="tab-panel" id="panel-soakA"><div class="soak-col" id="col-A"><h3>Loading…</h3></div></div>
<div class="tab-panel" id="panel-reports"><div id="reports-body">Loading…</div></div>

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
         // Tier-progression tints — DISPLAY-ONLY. Computed server-side per render
         // by walking 5m bars under the BE-after-TP1 model (see _compute_open_
         // tier_status). null = fetch failed / no tier data → no tint.
         const tp1Cls = (o.tp1_hit === 1) ? "tp1-hit" : "";
         const tp2Cls = (o.tp2_hit === 1) ? "tp2-hit" : "";
         const tp3Cls = (o.tp3_hit === 1) ? "tp3-hit" : "";
         return `<tr class="${rowCls}"><td>#${o.id}</td><td>${o.token}</td>` +
                `<td class="mono small tv-symbol">${tvSymbol}</td>` +
                `<td>${o.direction}</td>` +
                `<td class="mono small">${o.opened_ts ?? "—"}</td>` +
                `<td class="mono small">${o.expires_at ?? "—"}</td>` +
                `<td>${o.age_minutes ?? "—"}m</td>` +
                `<td class="mono">${fmt(o.entry_price,6)}</td>` +
                `<td class="mono">${fmt(o.sl,6)}</td>` +
                `<td class="mono ${tp1Cls}">${fmt(o.tp1,6)}</td>` +
                `<td class="mono ${tp2Cls}">${fmt(o.tp2,6)}</td>` +
                `<td class="mono ${tp3Cls}">${fmt(o.tp3,6)}</td>` +
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

  // Per-session table — OBSERVATIONAL / tracking-only. NOT a gate criterion.
  // Session derived live from each closed signal's opened UTC timestamp.
  const psHtml = (s.per_session || []).length
    ? `<table><thead><tr><th>session (UTC)</th><th>n</th><th>WR</th><th>avg R</th><th>sum R</th><th>PF</th></tr></thead><tbody>` +
       s.per_session.map(t => `<tr><td>${t.session}</td><td>${t.n}</td>` +
                            `<td>${(t.wr*100).toFixed(1)}%</td><td>${fmt(t.avg_R,3,true)}</td>` +
                            `<td>${fmt(t.sum_R,2,true)}</td><td>${t.pf==null?'∞':t.pf.toFixed(2)}</td></tr>`).join("") +
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
           "WIN":            "outcome-win",
           "PARTIAL_TP2":    "outcome-partial2",
           "PARTIAL_TP2_T1": "outcome-partial2",
           "PARTIAL_TP1":    "outcome-partial1",
           "LOSS":           "outcome-loss",
           "EXPIRED":        "outcome-expired",
         };
         const OUTCOME_ROW_CLS = {
           "WIN":            "row-win",
           "PARTIAL_TP2":    "row-partial2",
           "PARTIAL_TP2_T1": "row-partial2",
           "PARTIAL_TP1":    "row-partial1",
           "LOSS":           "row-loss",
           "EXPIRED":        "row-expired",
         };
         const outcomeCellCls = OUTCOME_CELL_CLS[c.result] || "";
         const outcomeRowCls  = OUTCOME_ROW_CLS[c.result] || "";
         // Legacy generic "win"/"loss" class for compat with existing td.outcome rule
         const legacyCls = (c.result==="WIN"||c.result==="PARTIAL_TP2"||c.result==="PARTIAL_TP2_T1") ? "win"
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

    <h2>Per-session <span class="small">— OBSERVATIONAL tracking only, NOT a gate criterion</span></h2>
    <div class="sanity-info">Session is tagged from each signal's <b>opened UTC</b> time (ASIAN 00–08, LONDON 08–13, LONDON_NY_OVERLAP 13–16, NY 16–21, LATE_US 21–24). This table is <b>display-only</b> — it does <b>NOT</b> enter the gate verdict (gate stays avg_R≥0.40, WR≥0.58, PF≥2.0, maxDD≤20R, n≥30). One-day samples are dominated by correlated bursts; session patterns need <b>many days</b> of accumulation before they mean anything. Do not exclude any session based on early data.</div>
    ${psHtml}

    <h2>Open positions <span class="small">— entry / SL / TP geometry + TradingView mapping</span></h2>
    <div class="tv-hint">TradingView mapping: paste the <b>TV symbol</b> column into TV's symbol search, set the chart timeframe to <b>5M</b> (signal entry TF), and set the chart's <b>timezone to UTC</b>. The <b>opened (UTC)</b> column is the entry candle's open time; scroll to it and draw SL / TP1 / TP2 / TP3 horizontal lines at the listed prices. The <b>expires (UTC)</b> column is the 48-hour deadline.</div>
    <div class="sanity-info">Sanity flags (right column) are <b>display-only</b> — they do <b>NOT</b> affect the locked verdict. Thresholds: SL ≤ 3.0%, TP1 R:R ≥ 1.3, direction/level consistency.</div>
    ${openHtml}

    <h2>Recent closed (${(s.closed || []).length} total) <span class="small">— with geometry, newest first</span></h2>
    <div class="closed-scroll">${closedHtml}</div>
  `;
}

// ═══════════════════════════════════════════════════════════════════════
// DASHBOARD + REPORTS — display-only. The locked gate VERDICT always comes
// from the server (gate_eval / verdict_overall); these views only DISPLAY it.
// ═══════════════════════════════════════════════════════════════════════
const OUTCOME_COLORS = { WIN:"#1a5b1a", PARTIAL_TP2:"#4ade80", PARTIAL_TP2_T1:"#22c55e", PARTIAL_TP1:"#86efac", LOSS:"#7f1d1d", EXPIRED:"#374151" };
const DIR_COLORS = { BUY:"#1f6feb", SELL:"#d29922" };
const SESSION_COLORS = { ASIAN:"#8957e5", LONDON:"#1f6feb", LONDON_NY_OVERLAP:"#2ea043", NY:"#db6d28", LATE_US:"#6e7681", UNKNOWN:"#484f58" };
let LAST_STATE = null;
let DASH_SOAK = "B";   // Soak B = PRIMARY default
let DASH_RANGE = "ALL";

function clsOf(v){ return v==="PASS"?"pass":v==="FAIL"?"fail":"pending"; }
function tsToMs(t){ if(!t) return null; const p=String(t).replace(" ","T")+"Z"; const d=Date.parse(p); return isNaN(d)?null:d; }

function filterByRange(arr, range){
  if(range==="ALL") return arr;
  const days = range==="30D"?30:90;
  const cut = Date.now() - days*86400000;
  return arr.filter(c => { const ms=tsToMs(c.closed_at); return ms===null||ms>=cut; });
}
function computeKPIs(arr){
  const n=arr.length; let wins=0,sum=0,gp=0,gl=0,best=null,worst=null,cum=0,peak=0,mdd=0;
  for(const c of arr){ const r=c.realized_r||0; sum+=r; if(r>0){wins++;gp+=r;} if(r<0)gl+=Math.abs(r);
    if(best===null||r>best)best=r; if(worst===null||r<worst)worst=r;
    cum+=r; if(cum>peak)peak=cum; if(peak-cum>mdd)mdd=peak-cum; }
  const pf = gl>0 ? gp/gl : (gp>0?null:0);   // null => no losses yet => "n/a"
  return { n, wins, wr:n?wins/n:0, sum_R:sum, pf, noLoss:gl<=0&&gp>0, avg_R:n?sum/n:0, best, worst, maxDD:mdd };
}

// ── inline-SVG charts (no external deps) ────────────────────────────────
function svgDonut(segs, size){
  size=size||120; const r=size/2-10, cx=size/2, cy=size/2, C=2*Math.PI*r;
  const total=segs.reduce((a,s)=>a+s.value,0);
  if(total<=0) return `<div class="small">(no data)</div>`;
  let off=0, circles="";
  for(const s of segs){ if(s.value<=0) continue; const len=C*s.value/total;
    circles += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}" stroke-width="14" `+
               `stroke-dasharray="${len.toFixed(2)} ${(C-len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" `+
               `transform="rotate(-90 ${cx} ${cy})"></circle>`; off+=len; }
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${circles}`+
         `<text x="${cx}" y="${cy+4}" text-anchor="middle" fill="#e6edf3" font-size="14" font-weight="700">${total}</text></svg>`;
}
function legend(segs){ return `<div class="legend">`+segs.filter(s=>s.value>0).map(s=>
  `<span class="lg"><span class="sw" style="background:${s.color}"></span>${s.label} ${s.value}</span>`).join("")+`</div>`; }

function svgLine(series, opts){
  // series: [{pts:[{x,y}], color, dots:bool, dotColorFn?}] ; opts:{w,h,refs:[{y,color,label}],ymin,ymax}
  const w=opts.w||520, h=opts.h||180, pl=42, pr=12, pt=12, pb=22;
  let ys=[], xs=[];
  series.forEach(s=>s.pts.forEach(p=>{ys.push(p.y);xs.push(p.x);}));
  (opts.refs||[]).forEach(r=>ys.push(r.y));
  if(!ys.length) return `<div class="small">(no data)</div>`;
  let ymin=opts.ymin!==undefined?opts.ymin:Math.min(...ys), ymax=opts.ymax!==undefined?opts.ymax:Math.max(...ys);
  if(ymin===ymax){ymin-=1;ymax+=1;} const xmin=Math.min(...xs), xmax=Math.max(...xs)||1;
  const X=x=>pl+(xmax===xmin?0:(x-xmin)/(xmax-xmin))*(w-pl-pr);
  const Y=y=>pt+(1-(y-ymin)/(ymax-ymin))*(h-pt-pb);
  let svg=`<svg width="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">`;
  // zero line
  if(ymin<0&&ymax>0){ svg+=`<line x1="${pl}" y1="${Y(0)}" x2="${w-pr}" y2="${Y(0)}" stroke="#30363d" stroke-dasharray="2 2"></line>`; }
  // ref lines
  (opts.refs||[]).forEach(r=>{ svg+=`<line x1="${pl}" y1="${Y(r.y)}" x2="${w-pr}" y2="${Y(r.y)}" stroke="${r.color}" stroke-dasharray="4 3"></line>`+
    `<text x="${w-pr}" y="${Y(r.y)-3}" text-anchor="end" fill="${r.color}" font-size="9">${r.label}</text>`; });
  // y axis labels
  svg+=`<text x="4" y="${Y(ymax)+4}" fill="#6e7681" font-size="9">${ymax.toFixed(2)}</text>`+
       `<text x="4" y="${Y(ymin)+4}" fill="#6e7681" font-size="9">${ymin.toFixed(2)}</text>`;
  series.forEach(s=>{ if(!s.pts.length) return;
    const d=s.pts.map((p,i)=>`${i?'L':'M'}${X(p.x).toFixed(1)} ${Y(p.y).toFixed(1)}`).join(" ");
    svg+=`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.8"></path>`;
    if(s.dots){ s.pts.forEach(p=>{ const c=s.dotColorFn?s.dotColorFn(p):s.color; if(!c) return;
      svg+=`<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="${p.big?3.5:2}" fill="${c}"></circle>`; }); }
  });
  return svg+`</svg>`;
}
function svgBars(items, opts){
  // items:[{label,value,color?}] ; pos green / neg red default
  const w=opts.w||520, h=opts.h||160, pl=36, pr=10, pt=10, pb=40;
  if(!items.length) return `<div class="small">(no data)</div>`;
  const vals=items.map(i=>i.value); let vmax=Math.max(0,...vals), vmin=Math.min(0,...vals);
  if(vmax===vmin){vmax+=1;vmin-=1;} const Y=v=>pt+(1-(v-vmin)/(vmax-vmin))*(h-pt-pb);
  const bw=(w-pl-pr)/items.length*0.66, gap=(w-pl-pr)/items.length;
  let svg=`<svg width="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">`;
  svg+=`<line x1="${pl}" y1="${Y(0)}" x2="${w-pr}" y2="${Y(0)}" stroke="#30363d"></line>`;
  items.forEach((it,i)=>{ const x=pl+i*gap+gap*0.17; const y0=Y(0),y1=Y(it.value);
    const col=it.color||(it.value>=0?"#3fb950":"#f85149");
    svg+=`<rect x="${x.toFixed(1)}" y="${Math.min(y0,y1).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.abs(y1-y0).toFixed(1)}" fill="${col}"></rect>`+
         `<text x="${(x+bw/2).toFixed(1)}" y="${(it.value>=0?y1-3:y1+10).toFixed(1)}" text-anchor="middle" fill="#c9d1d9" font-size="9">${fmt(it.value,2,true)}</text>`+
         `<text x="${(x+bw/2).toFixed(1)}" y="${h-pb+12}" text-anchor="middle" fill="#7d8590" font-size="8" transform="rotate(20 ${(x+bw/2).toFixed(1)} ${h-pb+12})">${it.label}</text>`; });
  return svg+`</svg>`;
}

function dashSoakBlock(s){
  if(!s||s.error) return `<div class="small">Soak ${s?s.label:''}: ${s&&s.error?s.error:'no data'}</div>`;
  const dash=s.dashboard||{}, ge=s.gate_eval||{}, bref=s.backtest_ref||{};
  const allClosed=s.closed||[];
  const arr=filterByRange(allClosed, DASH_RANGE);
  const k=computeKPIs(arr);
  const v=s.verdict_overall||"PENDING", vc=clsOf(v);
  const ref=(bref.avg_R||s.ref_avg_R||0).toFixed(4);
  const indep=dash.independent_event_count!=null?dash.independent_event_count:"?";
  const days=(s.tracking&&s.tracking.days_elapsed!=null)?s.tracking.days_elapsed:"?";
  // KPI cards — values reflect the selected range; gate pills are the SERVER-side
  // locked-verdict statuses (full sample), shown only when range = ALL.
  const showPills = (DASH_RANGE==="ALL");
  const pfStr = k.pf===null?`n/a`:fmt(k.pf,2);
  const cardsHtml = `<div class="kpi-grid">`+
    cardN("Closed n", k.n, k.n>=30?"gate n≥30 met":"need ≥30", k.n>=30?"pass":"pending")+
    cardN("WR (pos-R)", (k.wr*100).toFixed(1)+"%", "gate ≥58%", showPills?clsOf(ge.win_rate&&ge.win_rate.status):"")+
    cardN("Sum R", fmt(k.sum_R,2,true), "tracking (not a gate)", "", k.sum_R>=0?"pos":"neg")+
    cardN("PF", pfStr, k.pf===null?"no losses yet":"gate ≥2.0", showPills&&k.pf!==null?clsOf(ge.profit_factor&&ge.profit_factor.status):"")+
    cardN("Avg R", fmt(k.avg_R,3,true), `gate ≥+0.40 · ref +${ref}`, showPills?clsOf(ge.avg_R&&ge.avg_R.status):"", k.avg_R>=0?"pos":"neg")+
    cardN("Best / Worst R", fmt(k.best,2,true)+" / "+fmt(k.worst,2,true), "extremes (not a gate)", "")+
    cardN("Max DD (R)", fmt(k.maxDD,2), "gate ≤20R", showPills?clsOf(ge.max_drawdown&&ge.max_drawdown.status):"")+
  `</div>`;
  // Gate banner (authoritative server verdict)
  const critChips = ["avg_R","win_rate","profit_factor","max_drawdown","blowup"].map(key=>{
    const g=ge[key]||{}; const nm={avg_R:"avg_R",win_rate:"WR",profit_factor:"PF",max_drawdown:"maxDD",blowup:"blowup"}[key];
    let val = key==="win_rate"?((g.value!=null)?(g.value*100).toFixed(1)+"%":"—")
            : key==="blowup"?(g.value?"FLAGGED":"none")
            : (g.value!=null?fmt(g.value,2):"—");
    const thr={avg_R:"≥+0.40",win_rate:"≥58%",profit_factor:"≥2.0",max_drawdown:"≤20",blowup:"none"}[key];
    return `<span class="b-chip ${clsOf(g.status)}">${nm} ${val} (${thr}) ${g.status||''}</span>`;
  }).join("");
  const caption = `n=${k.n} over ~${days}d, correlated-burst-heavy (${indep} independent same-bar events for ${k.n} signals) — `+
                  `watching for convergence toward backtest +${ref}; currently <b>${v}</b>.`;
  const banner = `<div class="banner ${vc}"><span class="b-verdict ${vc}">GATE: ${v}</span>`+
    `<div class="b-caption">${caption}</div><div class="b-crit">${critChips}</div></div>`;
  // Donuts
  const oc=dash.outcome_counts||{};
  const outSeg=["WIN","PARTIAL_TP2","PARTIAL_TP2_T1","PARTIAL_TP1","LOSS","EXPIRED"].map(o=>({label:o,value:oc[o]||0,color:OUTCOME_COLORS[o]}));
  const dir=dash.direction||{};
  const dirSeg=[{label:"BUY",value:(dir.BUY&&dir.BUY.n)||0,color:DIR_COLORS.BUY},{label:"SELL",value:(dir.SELL&&dir.SELL.n)||0,color:DIR_COLORS.SELL}];
  const sessSeg=(s.per_session||[]).map(p=>({label:p.session,value:p.n,color:SESSION_COLORS[p.session]||"#484f58"}));
  const donuts = `<div class="chart-row">`+
    `<div class="chart-box"><div class="c-title">Outcomes</div>${svgDonut(outSeg)}${legend(outSeg)}</div>`+
    `<div class="chart-box"><div class="c-title">Direction</div>${svgDonut(dirSeg)}${legend(dirSeg)}`+
       `<div class="c-note">BUY sumR ${fmt(dir.BUY&&dir.BUY.sum_R,2,true)} · SELL sumR ${fmt(dir.SELL&&dir.SELL.sum_R,2,true)}</div></div>`+
    `<div class="chart-box"><div class="c-title">Session <span class="small">(observational only — not a gate criterion)</span></div>${svgDonut(sessSeg)}${legend(sessSeg)}</div>`+
  `</div>`;
  // Equity curve (close-ordered) with burst points annotated
  const eq=(dash.equity_series||[]);
  const eqPts=eq.map(p=>({x:p.i,y:p.cum_R,big:false}));
  const eqDots=eq.map(p=>({x:p.i,y:p.cum_R,big:!!p.burst}));
  const peakV=Math.max(0,...eqPts.map(p=>p.y));
  const equity = `<div class="chart-box" style="flex:1 1 100%"><div class="c-title">Equity curve — cumulative R (close-ordered) · amber = same-bar burst point</div>`+
    svgLine([
      {pts:eqPts,color:"#58a6ff"},
      {pts:eqDots,color:"#58a6ff",dots:true,dotColorFn:p=>p.big?"#d29922":null}
    ],{w:760,h:200})+
    `<div class="legend"><span class="lg"><span class="sw" style="background:#58a6ff"></span>cum R</span>`+
    `<span class="lg"><span class="sw" style="background:#d29922"></span>burst point (same-bar multi-token = ONE bet)</span>`+
    `<span class="lg">peak +${peakV.toFixed(2)}R · maxDD ${fmt(k.maxDD,2)}R</span></div>`+
    `<div class="c-note">Adjacent same-burst points are one entry decision resolving over time — not N independent moves.</div></div>`;
  // Correlated-burst panel
  const bursts=dash.bursts||[];
  const burstRows = bursts.length ? bursts.map(b=>
    `<tr class="${b.big?'burst-big':''}"><td class="mono small">${b.ts}</td><td>${b.dir}</td><td>${b.n}</td>`+
    `<td class="${b.sum_R>=0?'r-positive':'r-negative'}">${fmt(b.sum_R,2,true)}</td>`+
    `<td class="small">${(b.tokens||[]).join(", ")}</td><td>${b.big?'★':''}</td></tr>`).join("")
    : `<tr><td colspan="6" class="small">(no multi-token same-bar bursts yet)</td></tr>`;
  const burstPanel = `<div class="honest"><b>Correlated-burst panel (first-class honest read).</b> `+
    `${k.n} signals collapse to <b>${indep} independent same-bar events</b> (${dash.burst_signal_count||0} of the signals fired in `+
    `${bursts.length} multi-token bursts). Same opened_ts across tokens = ONE directional bet — aggregate sum_R/equity above carry the weight of `+
    `~${indep} bets, not ${k.n}. ★ = the largest +/- bursts.</div>`+
    `<div class="chart-row"><div class="chart-box" style="flex:1 1 340px"><div class="c-title">Bursts (same-bar, ≥2 tokens)</div>`+
    `<table><thead><tr><th>opened (UTC)</th><th>dir</th><th>n</th><th>combined R</th><th>tokens</th><th></th></tr></thead><tbody>${burstRows}</tbody></table></div>`+
    `<div class="chart-box" style="flex:1 1 340px"><div class="c-title">Day-by-day R <span class="small">(by opened-day — surfaces day-level skew)</span></div>`+
    svgBars((dash.by_day||[]).map(d=>({label:d.day.slice(5)+" (n"+d.n+")",value:d.sum_R})),{w:380,h:170})+`</div></div>`;

  return `<div class="soak-head"><h2 style="border:none">${s.label} — Dashboard</h2></div>`+
         banner+cardsHtml+donuts+`<div class="chart-row">${equity}</div>`+burstPanel;
}
function cardN(label, value, sub, statusCls, valCls){
  return `<div class="kpi ${statusCls||''}"><div class="k-label">${label}</div>`+
         `<div class="k-value ${valCls||''}">${value}</div><div class="k-sub">${sub||''}</div></div>`;
}
function pillJs(status){ return pill(status); }

function renderDashboard(){
  const soaks=(LAST_STATE&&LAST_STATE.soaks)||{};
  let html = `<div class="controls">`+
    `<div><span class="seg-label">Range</span><span class="seg" id="seg-range">`+
      ["30D","90D","ALL"].map(r=>`<button data-range="${r}" class="${DASH_RANGE===r?'active':''}">${r}</button>`).join("")+`</span></div>`+
    `<div><span class="seg-label">Soak</span><span class="seg" id="seg-soak">`+
      [["B","Soak B (primary)"],["A","Soak A (bg)"],["Both","Both"]].map(([k,lbl])=>`<button data-soak="${k}" class="${DASH_SOAK===k?'active':''}">${lbl}</button>`).join("")+`</span></div>`+
    `<div class="small">Range filters the KPI/chart view; the locked GATE verdict banner is always full-sample, per-soak, never blended.</div>`+
  `</div>`;
  if(DASH_SOAK==="Both"){ html += dashSoakBlock(soaks.B) + `<hr style="border-color:#30363d;margin:22px 0">` + dashSoakBlock(soaks.A); }
  else { html += dashSoakBlock(soaks[DASH_SOAK]); }
  document.getElementById("dash-body").innerHTML = html;
  wireDashControls();
}
function wireDashControls(){
  document.querySelectorAll('#seg-range button').forEach(b=>b.onclick=()=>{DASH_RANGE=b.dataset.range;renderDashboard();});
  document.querySelectorAll('#seg-soak button').forEach(b=>b.onclick=()=>{DASH_SOAK=b.dataset.soak;renderDashboard();});
}

// ── Reports tab ─────────────────────────────────────────────────────────
function reportsBlock(s){
  if(!s||s.error) return `<div class="small">${s?s.label:''}: ${s&&s.error?s.error:'no data'}</div>`;
  const dash=s.dashboard||{}, bref=s.backtest_ref||{};
  const drift=s.drift||[];
  // Convergence: forward cum-avg-R vs backtest ref + gate floor
  const convPts=drift.map(d=>({x:d.n,y:d.cum_avg_R}));
  const conv = `<div class="chart-box" style="flex:1 1 100%"><div class="c-title">Convergence — forward cumulative avg_R vs backtest reference</div>`+
    svgLine([{pts:convPts,color:"#58a6ff"}],{w:760,h:200,refs:[
      {y:bref.avg_R||0.484,color:"#3fb950",label:"backtest +"+(bref.avg_R||0.484).toFixed(3)},
      {y:0.40,color:"#d29922",label:"gate +0.40"}]})+
    `<div class="c-note">Is forward avg_R trending toward the backtest reference, or staying negative-toward-zero? Needs many days — currently burst-dominated.</div></div>`;
  // Exit-reason distribution
  const er=dash.exit_reasons||{};
  const erOrder=["WIN_TP3","PARTIAL_TP2","PARTIAL_TP2_T1","PARTIAL_TP1_BE","FULL_SL","LOSS_AFTER_TP1","EXPIRED","OTHER"];
  const erItems=erOrder.filter(k=>er[k]).map(k=>({label:k,value:er[k],
    color:k==="WIN_TP3"?"#1a5b1a":k==="PARTIAL_TP2"?"#4ade80":k==="PARTIAL_TP2_T1"?"#22c55e":k==="PARTIAL_TP1_BE"?"#86efac":k==="FULL_SL"?"#7f1d1d":"#374151"}));
  const exitDist = `<div class="chart-box" style="flex:1 1 420px"><div class="c-title">Exit-reason distribution</div>`+
    svgBars(erItems.map(i=>({label:i.label,value:i.value,color:i.color})),{w:420,h:180})+`</div>`;
  // Near-miss (lazy)
  const nm = `<div class="chart-box" style="flex:1 1 300px"><div class="c-title">Near-miss analysis <span class="small">(FULL_SL that reached ≥50% to TP1)</span></div>`+
    `<button class="btn" id="nm-btn" onclick="loadNearMiss('${s.key}')">Load near-miss (fetches price paths)</button>`+
    `<div id="nm-result" class="small" style="margin-top:8px">Not loaded — network reconstruction, runs only on click (never on auto-refresh).</div></div>`;
  // Backtest reference card
  const refCard = `<div class="ref-card"><div class="rc-title">Backtest reference — Config 14 (720d, friction, BE-after-TP1)</div>`+
    `<table><tr><th></th><th>TF</th><th>n</th><th>avg_R</th><th>WR</th><th>PF</th><th>DSR</th></tr>`+
    `<tr><td>This soak (${s.key})</td><td>${bref.tf||'—'}</td><td>${bref.n||'—'}</td><td>+${(bref.avg_R||0).toFixed(4)}</td>`+
    `<td>${bref.wr_pct||'—'}%</td><td>${bref.pf||'—'}</td><td>${bref.dsr||'—'}</td></tr></table>`+
    `<div class="c-note">Forward soak is measured against this. avg_R/WR/PF computed read-only from backtest_signals (run 56 TF_A / 58 TF_B); DSR per PHASE_C_FULL_AUDIT_V2.md.</div></div>`;
  return `<h2 style="border:none">${s.label} — Reports</h2><div class="chart-row">${conv}</div>`+
         `<div class="chart-row">${exitDist}${nm}</div><div class="chart-row"><div style="flex:1 1 100%">${refCard}</div></div>`;
}
async function loadNearMiss(key){
  const btn=document.getElementById("nm-btn"), out=document.getElementById("nm-result");
  if(btn){btn.disabled=true;btn.textContent="Loading…";}
  if(out)out.textContent="Fetching price paths from Binance (cached after first run)…";
  try{
    const resp=await fetch("/api/nearmiss?soak="+key,{cache:"no-store"});
    const d=await resp.json();
    if(d.error){ if(out)out.textContent="Error: "+d.error; }
    else{
      const b=d.buckets||{};
      const tot=d.total_full_sl||0;
      const rate=tot?((b.near_miss/tot)*100).toFixed(0):"0";
      const byday=(d.by_day||[]).map(x=>`${x.day.slice(5)}: ${x.near_miss}/${x.full_sl}`).join(" · ");
      if(out)out.innerHTML=`<b>${tot}</b> FULL_SL · near-miss(≥50%) <b>${b.near_miss||0}</b> (${rate}%) · `+
        `mid(25-50%) ${b.mid||0} · wrong-dir(<25%) ${b.wrong_dir||0}`+(b.unknown?` · unknown ${b.unknown}`:``)+
        `<br><span class="small">High near-miss rate = choppy stop-outs, not wrong-direction. By opened-day: ${byday||'—'}</span>`;
    }
  }catch(e){ if(out)out.textContent="Fetch error: "+e.message; }
  if(btn){btn.disabled=false;btn.textContent="Reload near-miss";}
}
function renderReports(){
  const soaks=(LAST_STATE&&LAST_STATE.soaks)||{};
  document.getElementById("reports-body").innerHTML = reportsBlock(soaks.B) + `<hr style="border-color:#30363d;margin:22px 0">` + reportsBlock(soaks.A);
}

// ── Tab navigation ──────────────────────────────────────────────────────
let ACTIVE_TAB="dashboard";
function showTab(tab){
  ACTIVE_TAB=tab;
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.toggle('active', p.id==='panel-'+tab));
  renderActive();
}
function renderActive(){
  if(!LAST_STATE) return;
  const soaks=LAST_STATE.soaks||{};
  if(ACTIVE_TAB==="dashboard") renderDashboard();
  else if(ACTIVE_TAB==="reports") renderReports();
  else if(ACTIVE_TAB==="soakB") document.getElementById("col-B").innerHTML=renderSoak(soaks.B);
  else if(ACTIVE_TAB==="soakA") document.getElementById("col-A").innerHTML=renderSoak(soaks.A);
}
document.querySelectorAll('.tab-btn').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));

async function refresh() {
  try {
    const resp = await fetch("/api/state", { cache: "no-store" });
    if (!resp.ok) {
      document.getElementById("fetch-ts").textContent = "FETCH ERROR " + resp.status;
      return;
    }
    LAST_STATE = await resp.json();
    renderActive();
    document.getElementById("fetch-ts").textContent = LAST_STATE.ts_utc + " UTC";
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
        if p.path == "/api/nearmiss":
            # LAZY, read-only, button-triggered. Never on auto-refresh.
            from urllib.parse import parse_qs
            soak_key = (parse_qs(p.query).get("soak", ["B"])[0] or "B").upper()
            try:
                self._send_json(compute_nearmiss(soak_key))
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
