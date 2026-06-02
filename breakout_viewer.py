"""
breakout_viewer.py — Read-only local dashboard for the breakout paper soak.

PHASE C-BREAKOUT — monitoring tool. Display only. Does NOT control the soak.

HARD INVARIANTS:
  - Opens data/breakout.db with `file:...?mode=ro` URI (sqlite3 read-only).
    The soak process holds the only writer. WAL mode lets us read without
    blocking it.
  - Fresh connection per request — no long-lived locks.
  - Filters all queries by source = 'H4_BREAKOUT_PAPER_SOAK'. The backtest
    grid + friction runs live in `backtest_signals` (different table) so
    they never appear here anyway, but the source filter is the defensive
    final guard.
  - Localhost only (127.0.0.1). Never binds 0.0.0.0.
  - Port 8890 (fade tracker is on 8888; we never collide).
  - Reads `data/breakout_soak_heartbeat.json` for soak health.
  - Reads `data/breakout_soak.pid` to confirm soak's PID (without touching it).

WHAT THIS VIEWER SHOWS:
  - Progress toward the locked ≥ 30 closed-signal gate.
  - Running net avg_R, profit factor, WR, max drawdown on closed soak signals.
  - n-vs-expectancy drift (cumulative avg_R as n grows).
  - Per-token table with the per-token blowup flag (WR ≤ 35% AND avg_R < 0
    over ≥ 5 signals).
  - Currently open positions in the soak (token, side, entry, age).
  - Soak health: heartbeat ts, current cycle, last signal time.

NOT IN THIS VIEWER:
  - No control actions (no start/stop/tune buttons).
  - No editing.
  - No write paths anywhere — every connection is read-only by URI.
  - No Telegram, no email, no external network.

To run (manual):
  cd /home/tradeai/breakout-work
  python3 breakout_viewer.py
  # then browse to http://127.0.0.1:8890 (via SSH tunnel if remote)
  # Ctrl+C to stop.

To run detached:
  nohup python3 breakout_viewer.py > logs/breakout_viewer.log 2>&1 &
  # Kill:
  pkill -f "python3 breakout_viewer.py"

The locked gate thresholds (matched to PHASE_C_STEP2B_SOAK_STARTED.md):
  avg_R per closed signal ≥ +0.40
  profit factor           ≥ 2.0
  win rate                ≥ 55%
  max drawdown (R)        ≤ 20
  per-token blowup        no token at WR ≤ 35% AND avg_R < 0 over ≥ 5 signals
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
DB_PATH       = _BREAKOUT_DIR / "data" / "breakout.db"
HEARTBEAT_PATH = _BREAKOUT_DIR / "data" / "breakout_soak_heartbeat.json"
PID_PATH      = _BREAKOUT_DIR / "data" / "breakout_soak.pid"

HOST = "127.0.0.1"
PORT = 8890
SOAK_LABEL = "H4_BREAKOUT_PAPER_SOAK"

# Locked thresholds (from PHASE_C_STEP2B_SOAK_STARTED.md §1)
GATE_N_TARGET           = 30
GATE_AVG_R_MIN          = 0.40
GATE_PF_MIN             = 2.0
GATE_WR_MIN             = 0.55
GATE_MAX_DD_R           = 20.0
GATE_PER_TOKEN_MIN_N    = 5
GATE_PER_TOKEN_BLOWUP_WR = 0.35


# ── Read-only DB helpers ──────────────────────────────────────────────────
def _open_ro_conn() -> sqlite3.Connection:
    """Open the DB with URI mode=ro. Fresh per call (no long-lived locks)."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"breakout.db missing at {DB_PATH}")
    # mode=ro ensures: cannot write, cannot create. URI required for ?mode=ro.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _profit_factor(realized_rs):
    wins = sum(r for r in realized_rs if r and r > 0)
    losses = sum(abs(r) for r in realized_rs if r and r < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def _max_drawdown_R(realized_rs):
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for r in realized_rs:
        if r is None:
            continue
        cum += r
        if cum > peak:
            peak = cum
        if peak - cum > max_dd:
            max_dd = peak - cum
    return max_dd, cum, peak


def _cumulative_avg_R_series(realized_rs):
    """Return list of {n, cum_R, cum_avg_R} for drift display."""
    out, cum = [], 0.0
    for i, r in enumerate(realized_rs, start=1):
        if r is None:
            r = 0.0
        cum += r
        out.append({
            "n":         i,
            "cum_R":     round(cum, 3),
            "cum_avg_R": round(cum / i, 4),
        })
    return out


def _gate_status(threshold_check: bool, n_signals: int) -> str:
    """Return PASS / FAIL / PENDING.

    Until n >= GATE_N_TARGET, every threshold returns PENDING — we don't
    declare a verdict on partial samples.
    """
    if n_signals < GATE_N_TARGET:
        return "PENDING"
    return "PASS" if threshold_check else "FAIL"


# ── Data assembly ─────────────────────────────────────────────────────────
def collect_state() -> dict:
    """Build the full snapshot of soak state for the JSON endpoint."""
    state = {
        "ts_unix":         _time.time(),
        "ts_utc":          datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "soak_label":      SOAK_LABEL,
        "gate":            {
            "n_target":              GATE_N_TARGET,
            "avg_R_min":             GATE_AVG_R_MIN,
            "pf_min":                GATE_PF_MIN,
            "wr_min":                GATE_WR_MIN,
            "max_dd_R_cap":          GATE_MAX_DD_R,
            "per_token_min_n":       GATE_PER_TOKEN_MIN_N,
            "per_token_blowup_wr":   GATE_PER_TOKEN_BLOWUP_WR,
        },
        "soak_health":     {},
        "closed":          [],
        "open":            [],
        "metrics":         {},
        "per_token":       [],
        "drift":           [],
        "verdict_overall": "PENDING",
    }

    # Soak heartbeat
    try:
        if HEARTBEAT_PATH.exists():
            hb = json.loads(HEARTBEAT_PATH.read_text())
            age_sec = max(0.0, _time.time() - float(hb.get("ts_unix") or 0))
            state["soak_health"] = {
                "heartbeat_ts_utc": hb.get("ts_utc"),
                "heartbeat_age_s":  round(age_sec, 1),
                "pid":              hb.get("pid"),
                "cycle":            hb.get("cycle"),
                "open_signals":     hb.get("open_signals"),
                "closed_signals":   hb.get("closed_signals"),
                "last_signal_ts":   hb.get("last_signal_ts"),
                "status":           "STALE" if age_sec > 300 else "OK",
            }
        else:
            state["soak_health"] = {
                "heartbeat_ts_utc": None,
                "status":           "NO_HEARTBEAT",
            }
    except (json.JSONDecodeError, ValueError) as e:
        state["soak_health"] = {"status": f"HEARTBEAT_ERROR: {e!r}"}

    # PID file presence (read-only check; we don't touch the running PID)
    try:
        if PID_PATH.exists():
            state["soak_health"]["pid_file"] = int(PID_PATH.read_text().strip())
        else:
            state["soak_health"]["pid_file"] = None
    except (ValueError, OSError):
        state["soak_health"]["pid_file"] = None

    # DB-derived state
    try:
        conn = _open_ro_conn()
    except FileNotFoundError:
        state["error"] = "breakout.db missing"
        return state

    try:
        # CLOSED signals + their results — ordered by close time
        closed_rows = list(conn.execute(
            "SELECT s.id AS sid, s.token, s.signal AS direction, "
            "       s.timestamp AS opened_ts, "
            "       s.entry_price, s.sl, s.tp1, s.tp2, s.tp3, "
            "       s.sweep_type, s.session, s.entry_type, "
            "       r.result, r.realized_r, r.closed_at, r.profit_pct "
            "FROM signals s JOIN results r ON r.signal_id = s.id "
            "WHERE s.source = ? AND s.status = 'CLOSED' "
            "ORDER BY r.closed_at",
            (SOAK_LABEL,),
        ))
        closed = [dict(r) for r in closed_rows]
        state["closed"] = closed

        # OPEN signals
        open_rows = list(conn.execute(
            "SELECT id, token, signal AS direction, entry_price, "
            "       sl, tp1, tp2, tp3, timestamp AS opened_ts, expires_at, "
            "       sweep_type, session, entry_type "
            "FROM signals WHERE source = ? AND status = 'OPEN' "
            "ORDER BY timestamp",
            (SOAK_LABEL,),
        ))
        open_sigs = []
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        for r in open_rows:
            d = dict(r)
            try:
                ts = datetime.strptime(d["opened_ts"], "%Y-%m-%d %H:%M:%S")
                age_min = round((now_utc - ts).total_seconds() / 60, 1)
                d["age_minutes"] = age_min
            except (ValueError, TypeError):
                d["age_minutes"] = None
            open_sigs.append(d)
        state["open"] = open_sigs

        # ── Aggregate metrics on CLOSED signals only ──────────────────
        n = len(closed)
        realized_rs = [r["realized_r"] for r in closed]
        n_wins_p2 = sum(1 for r in closed if r["result"] in ("WIN", "PARTIAL_TP2"))
        n_p1      = sum(1 for r in closed if r["result"] == "PARTIAL_TP1")
        wr_raw    = n_wins_p2 / n if n else 0.0
        avg_r     = sum(realized_rs) / n if n else 0.0
        sum_r     = sum(realized_rs)
        pf        = _profit_factor(realized_rs)
        max_dd, cum, peak = _max_drawdown_R(realized_rs)

        state["metrics"] = {
            "n_closed":        n,
            "n_open":          len(open_sigs),
            "avg_R":           round(avg_r, 4),
            "sum_R":           round(sum_r, 3),
            "profit_factor":   round(pf, 4) if pf != float("inf") else None,
            "win_rate":        round(wr_raw, 4),
            "max_drawdown_R":  round(max_dd, 3),
            "equity_peak_R":   round(peak, 3),
            "equity_curve_R":  round(cum, 3),
            "n_wins":          n_wins_p2,
            "n_partial_tp1":   n_p1,
            "n_losses":        sum(1 for r in closed if r["result"] == "LOSS"),
            "n_expired":       sum(1 for r in closed if r["result"] == "EXPIRED"),
            "progress_pct":    round(n / GATE_N_TARGET * 100, 1),
        }

        # ── Gate evaluation (PASS / FAIL / PENDING per criterion) ────
        avg_r_pass    = avg_r >= GATE_AVG_R_MIN
        pf_pass       = (pf >= GATE_PF_MIN) if pf != float("inf") else True
        wr_pass       = wr_raw >= GATE_WR_MIN
        max_dd_pass   = max_dd <= GATE_MAX_DD_R

        # Per-token + blowup flag
        per_token_map = {}
        for r in closed:
            tok = r["token"]
            per_token_map.setdefault(tok, []).append(r["realized_r"])

        per_token_rows = []
        any_blowup = False
        for tok in sorted(per_token_map.keys()):
            rs = per_token_map[tok]
            n_tok = len(rs)
            tok_wins = sum(1 for r in closed
                            if r["token"] == tok and r["result"] in ("WIN", "PARTIAL_TP2"))
            tok_wr = tok_wins / n_tok if n_tok else 0.0
            tok_avg = sum(rs) / n_tok if n_tok else 0.0
            tok_sum = sum(rs)
            tok_pf = _profit_factor(rs)
            blowup = (n_tok >= GATE_PER_TOKEN_MIN_N
                       and tok_wr <= GATE_PER_TOKEN_BLOWUP_WR
                       and tok_avg < 0)
            if blowup:
                any_blowup = True
            per_token_rows.append({
                "token":   tok,
                "n":       n_tok,
                "wr":      round(tok_wr, 4),
                "avg_R":   round(tok_avg, 4),
                "sum_R":   round(tok_sum, 3),
                "pf":      round(tok_pf, 4) if tok_pf != float("inf") else None,
                "blowup":  blowup,
            })
        state["per_token"] = per_token_rows
        blowup_pass = not any_blowup

        state["gate_eval"] = {
            "avg_R":         {"value": round(avg_r, 4),  "threshold": GATE_AVG_R_MIN,
                              "status": _gate_status(avg_r_pass, n)},
            "profit_factor": {"value": round(pf, 4) if pf != float("inf") else None,
                              "threshold": GATE_PF_MIN,
                              "status": _gate_status(pf_pass, n)},
            "win_rate":      {"value": round(wr_raw, 4), "threshold": GATE_WR_MIN,
                              "status": _gate_status(wr_pass, n)},
            "max_drawdown":  {"value": round(max_dd, 3),  "threshold": GATE_MAX_DD_R,
                              "status": _gate_status(max_dd_pass, n)},
            "blowup":        {"value": any_blowup,        "threshold": False,
                              "status": _gate_status(blowup_pass, n)},
        }

        # Overall verdict: PENDING until n>=GATE_N_TARGET; then PASS only if every criterion is OK
        if n < GATE_N_TARGET:
            state["verdict_overall"] = "PENDING"
        elif (avg_r_pass and pf_pass and wr_pass and max_dd_pass and blowup_pass):
            state["verdict_overall"] = "PASS"
        else:
            state["verdict_overall"] = "FAIL"

        # ── Drift: cumulative avg R as n grows ──
        state["drift"] = _cumulative_avg_R_series(realized_rs)

    finally:
        conn.close()  # always release

    return state


# ── HTML page (single string — vanilla JS, no framework) ─────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Breakout Soak Viewer</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0d1117; color: #e6edf3; margin: 0; padding: 20px; }
  h1 { font-size: 18px; margin: 0 0 8px 0; color: #fff; }
  h2 { font-size: 14px; margin: 24px 0 8px 0; color: #7d8590; text-transform: uppercase;
       letter-spacing: 0.5px; border-bottom: 1px solid #30363d; padding-bottom: 4px; }
  .row { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 6px;
          padding: 14px 18px; flex: 1 1 200px; min-width: 200px; }
  .card .label { color: #7d8590; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { color: #fff; font-size: 22px; font-weight: 600; margin-top: 4px; }
  .card .threshold { color: #6e7681; font-size: 12px; margin-top: 4px; }
  .ok      { color: #3fb950; }
  .fail    { color: #f85149; }
  .pending { color: #d29922; }
  .status-pill {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    margin-left: 8px;
  }
  .status-pill.ok      { background: #1f3d22; color: #3fb950; }
  .status-pill.fail    { background: #4d1717; color: #f85149; }
  .status-pill.pending { background: #4a3a10; color: #d29922; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
  th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #21262d; }
  th { color: #7d8590; font-weight: 500; font-size: 11px; text-transform: uppercase;
       background: #0d1117; position: sticky; top: 0; }
  tr.win  td.outcome { color: #3fb950; }
  tr.loss td.outcome { color: #f85149; }
  tr.blowup { background: #2d1213; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  .small { color: #7d8590; font-size: 11px; }
  #footer { margin-top: 32px; color: #6e7681; font-size: 11px; text-align: center; }
  .verdict-pass    { color: #3fb950; font-size: 16px; font-weight: 700; }
  .verdict-fail    { color: #f85149; font-size: 16px; font-weight: 700; }
  .verdict-pending { color: #d29922; font-size: 16px; font-weight: 700; }
  .heartbeat-ok    { color: #3fb950; }
  .heartbeat-stale { color: #d29922; }
  .heartbeat-dead  { color: #f85149; }
  details summary { cursor: pointer; color: #58a6ff; font-size: 12px; padding: 4px 0; }
</style>
</head>
<body>
<h1>BREAKOUT PAPER SOAK — Read-only viewer
  <span id="overall-verdict-pill" class="status-pill">…</span></h1>
<div class="small mono">port 8890 · DB read-only · refresh every 30s</div>

<h2>Gate progress · ≥ 30 closed signals</h2>
<div class="row">
  <div class="card">
    <div class="label">Closed signals</div>
    <div class="value" id="n-closed">…</div>
    <div class="threshold">target ≥ 30</div>
  </div>
  <div class="card">
    <div class="label">Progress</div>
    <div class="value" id="progress-pct">…%</div>
    <div class="threshold" id="progress-bar-text">…</div>
  </div>
  <div class="card">
    <div class="label">Open positions</div>
    <div class="value" id="n-open">…</div>
    <div class="threshold">currently in market</div>
  </div>
  <div class="card">
    <div class="label">Verdict</div>
    <div class="value" id="overall-verdict">PENDING</div>
    <div class="threshold">(LOCKED until n ≥ 30)</div>
  </div>
</div>

<h2>Locked thresholds vs observed</h2>
<div class="row">
  <div class="card">
    <div class="label">avg_R per closed</div>
    <div class="value" id="g-avg_R">…</div>
    <div class="threshold">≥ +0.40 → <span id="g-avg_R-status" class="status-pill">…</span></div>
  </div>
  <div class="card">
    <div class="label">Profit factor</div>
    <div class="value" id="g-pf">…</div>
    <div class="threshold">≥ 2.0 → <span id="g-pf-status" class="status-pill">…</span></div>
  </div>
  <div class="card">
    <div class="label">Win rate</div>
    <div class="value" id="g-wr">…</div>
    <div class="threshold">≥ 55% → <span id="g-wr-status" class="status-pill">…</span></div>
  </div>
  <div class="card">
    <div class="label">Max DD (R)</div>
    <div class="value" id="g-dd">…</div>
    <div class="threshold">≤ 20 R → <span id="g-dd-status" class="status-pill">…</span></div>
  </div>
  <div class="card">
    <div class="label">Per-token blowup</div>
    <div class="value" id="g-blow">…</div>
    <div class="threshold">no token WR≤35% AND avg_R&lt;0 over ≥5 sigs → <span id="g-blow-status" class="status-pill">…</span></div>
  </div>
</div>

<h2>Soak health</h2>
<div class="row">
  <div class="card">
    <div class="label">Heartbeat age</div>
    <div class="value" id="hb-age">…</div>
    <div class="threshold" id="hb-status">status</div>
  </div>
  <div class="card">
    <div class="label">Soak PID</div>
    <div class="value" id="hb-pid">…</div>
    <div class="threshold">from heartbeat.json</div>
  </div>
  <div class="card">
    <div class="label">Cycle</div>
    <div class="value" id="hb-cycle">…</div>
    <div class="threshold">soak scan cycle</div>
  </div>
  <div class="card">
    <div class="label">Last signal ts</div>
    <div class="value mono" id="hb-last-sig" style="font-size: 14px;">…</div>
    <div class="threshold">most recent emit</div>
  </div>
</div>

<h2>n-vs-expectancy drift (cumulative avg R as n grows)</h2>
<div class="mono small" id="drift-text">(no closed signals yet — chart will populate once results arrive)</div>

<h2>Per-token</h2>
<table id="per-token-table">
  <thead><tr><th>Token</th><th>n</th><th>WR</th><th>avg R</th><th>sum R</th><th>PF</th><th>flag</th></tr></thead>
  <tbody><tr><td colspan="7" class="small">(empty — no closed soak signals yet)</td></tr></tbody>
</table>

<h2>Open positions</h2>
<table id="open-table">
  <thead><tr><th>ID</th><th>Token</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP1</th><th>TP3</th><th>Setup</th><th>Opened (UTC)</th><th>Age (min)</th></tr></thead>
  <tbody><tr><td colspan="10" class="small">(no open soak positions)</td></tr></tbody>
</table>

<h2>Closed signals (most recent 25)</h2>
<table id="closed-table">
  <thead><tr><th>ID</th><th>Token</th><th>Dir</th><th>Outcome</th><th>R</th><th>Profit %</th><th>Opened (UTC)</th><th>Closed (UTC)</th><th>Setup</th></tr></thead>
  <tbody><tr><td colspan="9" class="small">(no closed signals yet)</td></tr></tbody>
</table>

<div id="footer">
  Last refresh: <span id="fetch-ts">…</span> · auto-refresh every 30s · Ctrl+Shift+R for manual
</div>

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
function statusClass(s) {
  if (s === "PASS" || s === "OK") return "ok";
  if (s === "FAIL" || s === "STALE" || s === "DEAD") return "fail";
  return "pending";
}
function setPill(el, status) {
  if (!el) return;
  el.className = "status-pill " + statusClass(status).toLowerCase();
  el.textContent = status;
}

async function refresh() {
  try {
    const resp = await fetch("/api/state", { cache: "no-store" });
    if (!resp.ok) {
      document.getElementById("fetch-ts").textContent = "FETCH ERROR " + resp.status;
      return;
    }
    const s = await resp.json();

    // Gate progress
    const m = s.metrics || {};
    document.getElementById("n-closed").textContent = m.n_closed ?? "0";
    document.getElementById("n-open").textContent   = m.n_open ?? "0";
    document.getElementById("progress-pct").textContent = (m.progress_pct ?? 0) + "%";
    document.getElementById("progress-bar-text").textContent = (m.n_closed ?? 0) + " / " + s.gate.n_target;

    document.getElementById("overall-verdict").textContent = s.verdict_overall;
    document.getElementById("overall-verdict").className =
      "value " + (s.verdict_overall === "PASS" ? "verdict-pass"
                : s.verdict_overall === "FAIL" ? "verdict-fail"
                                                : "verdict-pending");
    setPill(document.getElementById("overall-verdict-pill"), s.verdict_overall);

    // Locked thresholds
    const ge = s.gate_eval || {};
    document.getElementById("g-avg_R").textContent = fmt(ge.avg_R?.value, 4, true);
    setPill(document.getElementById("g-avg_R-status"), ge.avg_R?.status);
    document.getElementById("g-pf").textContent = fmt(ge.profit_factor?.value, 3);
    setPill(document.getElementById("g-pf-status"), ge.profit_factor?.status);
    document.getElementById("g-wr").textContent = ge.win_rate?.value !== null
        ? (ge.win_rate.value * 100).toFixed(1) + "%" : "—";
    setPill(document.getElementById("g-wr-status"), ge.win_rate?.status);
    document.getElementById("g-dd").textContent = fmt(ge.max_drawdown?.value, 2);
    setPill(document.getElementById("g-dd-status"), ge.max_drawdown?.status);
    document.getElementById("g-blow").textContent = ge.blowup?.value === false ? "none" : "FLAGGED";
    setPill(document.getElementById("g-blow-status"), ge.blowup?.status);

    // Soak health
    const hb = s.soak_health || {};
    const hbAge = hb.heartbeat_age_s;
    document.getElementById("hb-age").textContent = hbAge !== undefined ? hbAge + " s" : "—";
    document.getElementById("hb-pid").textContent = hb.pid ?? "—";
    document.getElementById("hb-cycle").textContent = hb.cycle ?? "—";
    document.getElementById("hb-last-sig").textContent = hb.last_signal_ts ?? "(none yet)";
    const hbStatusEl = document.getElementById("hb-status");
    hbStatusEl.textContent = hb.status ?? "—";
    hbStatusEl.className = "threshold " + (
      hb.status === "OK" ? "heartbeat-ok" :
      hb.status === "STALE" ? "heartbeat-stale" : "heartbeat-dead"
    );

    // Per-token
    const ptBody = document.querySelector("#per-token-table tbody");
    if (s.per_token && s.per_token.length > 0) {
      ptBody.innerHTML = s.per_token.map(t => `
        <tr class="${t.blowup ? 'blowup' : ''}">
          <td>${t.token}</td>
          <td>${t.n}</td>
          <td>${(t.wr * 100).toFixed(1)}%</td>
          <td>${fmt(t.avg_R, 4, true)}</td>
          <td>${fmt(t.sum_R, 3, true)}</td>
          <td>${fmt(t.pf, 3)}</td>
          <td>${t.blowup ? '⚠ BLOWUP' : ''}</td>
        </tr>
      `).join("");
    } else {
      ptBody.innerHTML = '<tr><td colspan="7" class="small">(empty — no closed soak signals yet)</td></tr>';
    }

    // Open
    const openBody = document.querySelector("#open-table tbody");
    if (s.open && s.open.length > 0) {
      openBody.innerHTML = s.open.map(o => `
        <tr>
          <td>#${o.id}</td>
          <td>${o.token}</td>
          <td>${o.direction}</td>
          <td class="mono">${fmt(o.entry_price, 6)}</td>
          <td class="mono">${fmt(o.sl, 6)}</td>
          <td class="mono">${fmt(o.tp1, 6)}</td>
          <td class="mono">${fmt(o.tp3, 6)}</td>
          <td class="small">${o.entry_type ?? '—'}</td>
          <td class="mono small">${o.opened_ts}</td>
          <td>${o.age_minutes ?? '—'}</td>
        </tr>
      `).join("");
    } else {
      openBody.innerHTML = '<tr><td colspan="10" class="small">(no open soak positions)</td></tr>';
    }

    // Closed (most recent 25)
    const closedRows = (s.closed || []).slice(-25).reverse();
    const closedBody = document.querySelector("#closed-table tbody");
    if (closedRows.length > 0) {
      closedBody.innerHTML = closedRows.map(c => {
        const cls = (c.result === "WIN" || c.result === "PARTIAL_TP2") ? "win"
                  : (c.result === "LOSS") ? "loss" : "";
        return `<tr class="${cls}">
          <td>#${c.sid}</td>
          <td>${c.token}</td>
          <td>${c.direction}</td>
          <td class="outcome">${c.result}</td>
          <td>${fmt(c.realized_r, 3, true)}</td>
          <td>${fmt(c.profit_pct, 3, true)}</td>
          <td class="mono small">${c.opened_ts}</td>
          <td class="mono small">${c.closed_at}</td>
          <td class="small">${c.entry_type ?? '—'}</td>
        </tr>`;
      }).join("");
    } else {
      closedBody.innerHTML = '<tr><td colspan="9" class="small">(no closed signals yet)</td></tr>';
    }

    // Drift text view
    const drift = s.drift || [];
    if (drift.length > 0) {
      // Show every Nth so the text doesn't get unbearable
      const stride = Math.max(1, Math.floor(drift.length / 30));
      const points = drift.filter((d, i) => i === drift.length - 1 || i % stride === 0);
      document.getElementById("drift-text").innerHTML =
        "<table style='font-size:11px'><tr><th>n</th><th>cum_R</th><th>cum_avg_R</th></tr>" +
        points.map(p => `<tr><td>${p.n}</td><td>${fmt(p.cum_R, 3, true)}</td><td>${fmt(p.cum_avg_R, 4, true)}</td></tr>`).join("") +
        "</table>";
    }

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


# ── HTTP handler ──────────────────────────────────────────────────────────
class ViewerHandler(http.server.BaseHTTPRequestHandler):
    # Stay quiet — only log errors. Default verbose access logs would spam the
    # operator's console when auto-refresh is firing every 30s.
    def log_message(self, format, *args):
        return

    def _send_html(self, body: str, status: int = 200):
        body_b = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_b)

    def _send_json(self, obj, status: int = 200):
        body_b = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_b)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index", "/index.html"):
            self._send_html(HTML_PAGE)
            return
        if parsed.path == "/api/state":
            try:
                state = collect_state()
                self._send_json(state)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return
        # Refuse anything else (no static files, no other endpoints)
        self.send_response(404)
        self.end_headers()

    # Block all writes
    def do_POST(self):    self.send_error(405)
    def do_PUT(self):     self.send_error(405)
    def do_DELETE(self):  self.send_error(405)
    def do_PATCH(self):   self.send_error(405)


def main():
    # Verify we can open the DB in read-only mode before binding the port
    try:
        conn = _open_ro_conn()
        conn.close()
    except Exception as e:
        print(f"FATAL: cannot open breakout.db in read-only mode: {e!r}", file=sys.stderr)
        sys.exit(1)

    print(f"Breakout viewer starting on http://{HOST}:{PORT}", flush=True)
    print(f"  DB:        {DB_PATH}  (read-only URI mode)", flush=True)
    print(f"  Heartbeat: {HEARTBEAT_PATH}", flush=True)
    print(f"  Soak label: {SOAK_LABEL}", flush=True)
    print(f"  Ctrl+C to stop.", flush=True)

    # Make connection refusal explicit if the port is taken
    socketserver.TCPServer.allow_reuse_address = False
    with socketserver.TCPServer((HOST, PORT), ViewerHandler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n  shutdown.", flush=True)


if __name__ == "__main__":
    main()
