"""
TradeAI — Signal Tracker Dashboard
Run:  python tracker.py
Open: http://localhost:8888
"""
import sqlite3, json, os, threading, subprocess, sys, re, shutil, ast
from typing import Any, Dict, List
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime, timedelta, timezone

try:
    from adaptive_engine import (
        weight_engine as _weight_engine,
        save_scalar_state as _save_scalar,
        load_scalar_state as _load_scalar,
        _init_adaptive_tables as _init_ae_tables,
        DEGENERATE_THRESHOLD as _DEGENERATE_THRESHOLD,
        MAX_OPEN_POSITIONS as _MAX_OPEN,
        MAX_SAME_DIRECTION as _MAX_SAME_DIR,
        MAX_PORTFOLIO_RISK_PCT as _MAX_RISK_PCT,
    )
except Exception:
    _weight_engine        = None
    _save_scalar          = lambda k, v: None
    _load_scalar          = lambda k, d=None: d
    _init_ae_tables       = lambda: None
    _DEGENERATE_THRESHOLD = 0.40  # Fix #36 (2026-05-22 cycle 9): mirror adaptive_engine 0.45→0.40
    _MAX_OPEN             = 20    # PAPER defaults — safe fallback
    _MAX_SAME_DIR         = 10
    _MAX_RISK_PCT         = 1.0

_ROOT   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_ROOT, "data", "signals.db")
PORT    = 8888

BACKTEST_STATUS = {"status":"IDLE","started":None,"message":"Ready","progress":0,"error_log":""}
_bt_lock = threading.Lock()

# ── Adaptive-metrics cache (avoids DB hammering on dashboard polls) ────────────
_adaptive_cache: dict = {}
_adap_lock = threading.Lock()
_ADAP_TTL = 15   # seconds — weights/drift change slowly; cache keeps tracker CPU low

def _cached_adaptive(key: str, fn):
    """Return cached result if fresh, else call fn() and cache it."""
    with _adap_lock:
        entry = _adaptive_cache.get(key)
        if entry and (datetime.now() - entry["ts"]).total_seconds() < _ADAP_TTL:
            return entry["data"]
    data = fn()
    with _adap_lock:
        _adaptive_cache[key] = {"data": data, "ts": datetime.now()}
    return data

def _connect():
    """WAL mode + 10s busy timeout + foreign keys — mirrors crypto_alert.py._connect()."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def query_db(sql, params=()):
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] Query error: {e}")
        return []

def _canonical_wr(wins, partial, losses, expired):
    """Single authoritative win-rate formula used everywhere in this file.
    PARTIAL counts as 0.5 wins (TP1 hit but trade not fully resolved).
    Total = all closed results (WIN + PARTIAL + LOSS + EXPIRED)."""
    total = wins + partial + losses + expired
    return round((wins + 0.5 * partial) / total * 100, 1) if total > 0 else 0.0

def get_stats():
    try:
        conn = _connect()
        total   = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        wins    = conn.execute("SELECT COUNT(*) FROM results WHERE result='WIN'").fetchone()[0]
        losses  = conn.execute("SELECT COUNT(*) FROM results WHERE result='LOSS'").fetchone()[0]
        partial = conn.execute("SELECT COUNT(*) FROM results WHERE result IN ('PARTIAL','PARTIAL_TP1','PARTIAL_TP2')").fetchone()[0]
        expired = conn.execute("SELECT COUNT(*) FROM results WHERE result='EXPIRED'").fetchone()[0]
        opens   = conn.execute("SELECT COUNT(*) FROM signals WHERE status='OPEN'").fetchone()[0]
        avg_rr  = conn.execute("SELECT AVG(rr1) FROM signals WHERE rr1 IS NOT NULL").fetchone()[0]
        best    = conn.execute("SELECT MAX(profit_pct) FROM results WHERE result='WIN'").fetchone()[0]
        worst   = conn.execute("SELECT MIN(profit_pct) FROM results WHERE result='LOSS'").fetchone()[0]
        # Profit factor = sum of winning P&L / abs(sum of losing P&L)
        gross_win  = conn.execute(
            "SELECT SUM(profit_pct) FROM results WHERE result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2') AND profit_pct > 0"
        ).fetchone()[0] or 0.0
        gross_loss = conn.execute(
            "SELECT SUM(profit_pct) FROM results WHERE result='LOSS' AND profit_pct < 0"
        ).fetchone()[0] or 0.0
        profit_factor = round(gross_win / abs(gross_loss), 2) if gross_loss < 0 else None
        # Drawdown: sum of all closed P&L to find running peak and trough
        pnl_rows = conn.execute(
            "SELECT profit_pct FROM results WHERE result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED') "
            "ORDER BY id ASC"
        ).fetchall()
        _equity = _peak_eq = _dd = 0.0
        for (p,) in pnl_rows:
            _equity  += (p or 0.0)
            _peak_eq  = max(_peak_eq, _equity)
            _dd       = min(_dd, _equity - _peak_eq)
        conn.close()
        wr = _canonical_wr(wins, partial, losses, expired)
        return {"total":total,"wins":wins,"losses":losses,"partial":partial,"expired":expired,
                "opens":opens,"win_rate":wr,
                "avg_rr":round(avg_rr,1) if avg_rr else 0,
                "best_trade":round(best,2) if best else 0,
                "worst_trade":round(worst,2) if worst else 0,
                "profit_factor":profit_factor,
                "max_drawdown_pct":round(_dd, 2),
                "db_ok":True}
    except Exception as e:
        print(f"[DB] Stats error: {e}")
        return {"total":0,"wins":0,"losses":0,"partial":0,"opens":0,
                "win_rate":0,"avg_rr":0,"best_trade":0,"worst_trade":0,
                "profit_factor":None,"max_drawdown_pct":0,"db_ok":False}

def get_equity_curve(limit_days: int = 90):
    """Return cumulative P&L over time for the equity curve chart (C1, 2026-05-22 tracker audit).

    Returns a list of {ts, pnl, cum_pnl} ordered by closed_at ASC. `cum_pnl` is the
    running sum of profit_pct over closed signals only (open positions excluded).
    Limited to the last `limit_days` of closed signals to keep the payload light.
    """
    try:
        conn = _connect()
        rows = conn.execute(
            """SELECT s.timestamp, r.closed_at, r.profit_pct, s.token, s.signal, r.result
               FROM results r
               JOIN signals s ON r.signal_id = s.id
               WHERE r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED')
                 AND r.profit_pct IS NOT NULL
                 AND COALESCE(r.closed_at, s.timestamp) >= datetime('now', ?)
               ORDER BY COALESCE(r.closed_at, s.timestamp) ASC""",
            (f"-{int(limit_days)} days",)
        ).fetchall()
        conn.close()
        cum = 0.0
        out = []
        for ts, closed_at, pnl, tok, sig, res in rows:
            cum += float(pnl or 0.0)
            out.append({
                "ts":      closed_at or ts,
                "token":   tok,
                "signal":  sig,
                "result":  res,
                "pnl":     round(float(pnl or 0.0), 3),
                "cum_pnl": round(cum, 3),
            })
        # Headroom + drawdown stats for the chart annotation
        peak = max((p["cum_pnl"] for p in out), default=0.0)
        trough_after_peak = 0.0
        running_peak = 0.0
        max_dd = 0.0
        for p in out:
            running_peak = max(running_peak, p["cum_pnl"])
            max_dd = min(max_dd, p["cum_pnl"] - running_peak)
        return {
            "ok": True,
            "points": out,
            "summary": {
                "n":        len(out),
                "final":    round(cum, 3),
                "peak":     round(peak, 3),
                "max_dd":   round(max_dd, 3),
                "days":     limit_days,
            }
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "points": [], "summary": {}}

def get_rolling_wf(run_id: int = None, train_days: int = 90, test_days: int = 30, step_days: int = 30):
    """Rolling walk-forward train/test WR series for the backtest WF chart (C6, 2026-05-22).

    Reads from `backtest_signals` for the requested run_id (defaults to most recent).
    Returns list of {window, train_end_ts, train_wr, train_n, test_wr, test_n}.
    """
    from datetime import datetime, timedelta
    try:
        conn = _connect()
        if run_id is None:
            row = conn.execute("SELECT MAX(run_id) FROM backtest_signals").fetchone()
            run_id = int(row[0] or 0)
        sigs = conn.execute(
            """SELECT ts, outcome FROM backtest_signals
               WHERE run_id = ? AND outcome IS NOT NULL
               ORDER BY ts ASC""", (run_id,)
        ).fetchall()
        conn.close()
        if not sigs:
            return {"ok": True, "run_id": run_id, "windows": [],
                    "summary": {"n_windows": 0, "mean_gap": 0.0}}
        def _parse(s):
            try:    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            except: return datetime.strptime(s, "%Y-%m-%d")
        def _wr_subset(subset):
            if not subset: return 0.0
            w = sum(1 for o in subset if o == "WIN")
            p = sum(1 for o in subset if o in ("PARTIAL","PARTIAL_TP1","PARTIAL_TP2"))
            l = sum(1 for o in subset if o == "LOSS")
            e = sum(1 for o in subset if o == "EXPIRED")
            tot = w + p + l + e
            return round((w + 0.5*p) / tot * 100, 1) if tot else 0.0
        first_ts = _parse(sigs[0][0]);  last_ts = _parse(sigs[-1][0])
        total_days = (last_ts - first_ts).days
        windows = []
        offset = 0; widx = 0
        while offset + train_days + test_days <= total_days:
            t_start = first_ts + timedelta(days=offset)
            t_end   = t_start  + timedelta(days=train_days)
            x_end   = t_end    + timedelta(days=test_days)
            train = [o for ts, o in sigs if t_start <= _parse(ts) < t_end]
            test  = [o for ts, o in sigs if t_end   <= _parse(ts) < x_end]
            if train or test:
                widx += 1
                windows.append({
                    "window": widx,
                    "train_end_ts": t_end.strftime("%Y-%m-%d"),
                    "train_wr": _wr_subset(train),
                    "test_wr":  _wr_subset(test),
                    "train_n":  len(train),
                    "test_n":   len(test),
                })
            offset += step_days
        # Summary
        diffs = [w["test_wr"] - w["train_wr"] for w in windows if w["train_n"] >= 3 and w["test_n"] >= 3]
        mean_gap = round(sum(diffs) / len(diffs), 1) if diffs else 0.0
        consistent = sum(1 for w in windows
                         if w["test_wr"] >= 55 and w["train_n"] >= 3 and w["test_n"] >= 3)
        return {
            "ok": True, "run_id": run_id, "windows": windows,
            "summary": {
                "n_windows":  len(windows),
                "mean_gap":   mean_gap,
                "consistent": consistent,
            }
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "windows": [], "summary": {}}

def get_adaptive_forensic(limit_per_token: int = 10):
    """R10 forensic panel (master audit 2026-05-26): per-token recent OGD
    update history with the R4 forensic columns (reward, gradient_l1,
    profit_pct) + R7 regime label. Joins with current token_weights for
    health flags + n_updates.

    Returns:
      {
        ok: bool,
        tokens: {
          "BTC": {
            n_updates: int,
            last_update_iso: str,
            current_weights: {feature: float},
            health_flags: ["DEGENERATE", "FROZEN", "STALE", ...],
            recent_updates: [
              {ts, trigger, regime, reward, gradient_l1, profit_pct,
               weight_after: {feature: float}},
              ...
            ]
          },
          ...
        },
        global: {
          freeze_state: bot_state.learning_freeze_state blob (or null),
          dsr_verdict: bot_state.latest_cpcv_verdict (or null),
          last_decay_times: {token: epoch} (or null),
        }
      }
    """
    from datetime import datetime as _dt, timezone as _tz
    out = {"ok": False, "tokens": {}, "global": {}}
    try:
        conn = _connect()
        # Live token_weights wins for tokens that have updates; fall back to
        # the bootstrap pool (backtest_token_weights) for the remaining
        # tokens. This guarantees all 10 active tokens appear in the panel
        # even when live OGD has only touched a subset.
        live_rows = conn.execute(
            "SELECT token, feature, weight, n_updates, updated_at FROM token_weights"
        ).fetchall()
        live_tokens = {r[0] for r in live_rows}
        bt_rows = conn.execute(
            "SELECT token, feature, weight, n_bootstrap, updated_at "
            "FROM backtest_token_weights"
        ).fetchall()
        # Filter bootstrap rows to tokens NOT already in live (avoids
        # duplicates — live weights win for any token with live updates)
        bt_rows = [r for r in bt_rows if r[0] not in live_tokens]
        cur_rows = list(live_rows) + bt_rows
        tokens: Dict[str, Dict[str, Any]] = {}
        for token, feat, w, n_u, ts in cur_rows:
            entry = tokens.setdefault(token, {
                "n_updates": 0, "last_update_iso": None,
                "current_weights": {}, "health_flags": [],
                "recent_updates": [],
            })
            entry["current_weights"][feat] = round(float(w or 0), 4)
            entry["n_updates"] = max(entry["n_updates"], int(n_u or 0))
            if ts and (entry["last_update_iso"] is None or str(ts) > entry["last_update_iso"]):
                entry["last_update_iso"] = str(ts)

        # Recent forensic rows per token (R4 + R7 columns from weight_history)
        for token in tokens:
            rows = conn.execute(
                """SELECT recorded_at, trigger, regime, reward, gradient_l1,
                          profit_pct, feature, weight_after, n_updates
                   FROM weight_history
                   WHERE token = ?
                   ORDER BY id DESC
                   LIMIT ?""",
                (token, limit_per_token * 6 + 10)   # 6 features × limit + slack
            ).fetchall()
            # Group by (recorded_at, trigger) into update events
            events: List[Dict[str, Any]] = []
            seen_keys: set = set()
            cur_event = None
            for ts, trig, regime, reward, grad_l1, profit_pct, feat, w_a, n_u in rows:
                key = (ts, trig)
                if key not in seen_keys:
                    if cur_event is not None and len(events) >= limit_per_token:
                        break
                    cur_event = {
                        "ts":          str(ts),
                        "trigger":     trig,
                        "regime":      regime,
                        "reward":      None if reward is None else round(float(reward), 4),
                        "gradient_l1": None if grad_l1 is None else round(float(grad_l1), 6),
                        "profit_pct":  None if profit_pct is None else round(float(profit_pct), 6),
                        "n_updates":   int(n_u or 0),
                        "weight_after": {},
                    }
                    events.append(cur_event)
                    seen_keys.add(key)
                if cur_event is not None and feat:
                    cur_event["weight_after"][feat] = round(float(w_a or 0), 4)
            tokens[token]["recent_updates"] = events[:limit_per_token]

            # Health flags
            cw = tokens[token]["current_weights"]
            if cw:
                max_w = max(cw.values())
                min_w = min(cw.values())
                if max_w > 0.40:
                    tokens[token]["health_flags"].append("DEGENERATE")
                pinned = [f for f, v in cw.items() if abs(v - 0.05) <= 0.015]
                if len(pinned) >= 3:
                    tokens[token]["health_flags"].append("FLOOR-PINNED")
                if tokens[token]["last_update_iso"]:
                    try:
                        dt = _dt.strptime(str(tokens[token]["last_update_iso"]),
                                          "%Y-%m-%d %H:%M:%S").replace(tzinfo=_tz.utc)
                        age_days = (_dt.now(_tz.utc) - dt).total_seconds() / 86400.0
                        if age_days > 21:
                            tokens[token]["health_flags"].append(f"STALE-{int(age_days)}d")
                    except Exception:
                        pass

        # Global state (freeze, dsr verdict, decay times)
        global_state: Dict[str, Any] = {}
        for key in ("learning_freeze_state", "latest_cpcv_verdict", "last_decay_times"):
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key=?", (key,)
            ).fetchone()
            if row and row[0]:
                try:
                    global_state[key] = json.loads(row[0])
                except Exception:
                    global_state[key] = None
            else:
                global_state[key] = None
        # Layer freeze status onto per-token flags
        fs = global_state.get("learning_freeze_state") or {}
        if fs.get("frozen"):
            for tok in tokens:
                tokens[tok]["health_flags"].append("FROZEN")

        conn.close()
        out["ok"] = True
        out["tokens"] = tokens
        out["global"] = global_state
        return out
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out


def get_ogd_weight_history(limit_per_series: int = 30):
    """Per-token, per-feature weight trajectory for sparklines (C3, 2026-05-22).

    Returns {token: {feature: [{ts, w, n}]}}. Trajectories are limited to the
    most recent `limit_per_series` non-test snapshots per (token, feature).
    Test triggers (test_*) are excluded so the sparkline reflects real bootstrap
    and live-update history only.
    """
    try:
        conn = _connect()
        rows = conn.execute(
            """SELECT recorded_at, token, feature, weight_after, n_updates
               FROM weight_history
               WHERE trigger NOT LIKE 'test_%'
               ORDER BY token, feature, id DESC"""
        ).fetchall()
        conn.close()
        # Group by (token, feature); take most recent `limit_per_series` then reverse
        series = {}
        last_key = None
        bucket = []
        def _flush(key, buf):
            if not key: return
            tok, feat = key
            series.setdefault(tok, {})[feat] = list(reversed(buf[:limit_per_series]))
        for ts, tok, feat, w, n in rows:
            key = (tok, feat)
            if key != last_key:
                _flush(last_key, bucket); bucket = []; last_key = key
            bucket.append({"ts": ts, "w": round(float(w or 0), 4), "n": int(n or 0)})
        _flush(last_key, bucket)
        return {"ok": True, "series": series}
    except Exception as e:
        return {"ok": False, "error": str(e), "series": {}}

def get_hour_day_heatmap():
    """Return WR matrix indexed by [day_of_week 0-6][hour_utc 0-23] (C2, 2026-05-22).

    Each cell: {n, wr, wins, partial, losses, expired}. Empty cells are omitted —
    frontend treats missing cells as no-data (dim gray).
    """
    try:
        conn = _connect()
        rows = conn.execute(
            """SELECT s.day_of_week, s.hour_utc,
                      SUM(CASE WHEN r.result='WIN' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN r.result IN ('PARTIAL','PARTIAL_TP1','PARTIAL_TP2') THEN 1 ELSE 0 END),
                      SUM(CASE WHEN r.result='LOSS' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN r.result='EXPIRED' THEN 1 ELSE 0 END),
                      COUNT(*)
               FROM results r JOIN signals s ON r.signal_id = s.id
               WHERE r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED')
                 AND s.day_of_week IS NOT NULL AND s.hour_utc IS NOT NULL
               GROUP BY s.day_of_week, s.hour_utc"""
        ).fetchall()
        conn.close()
        cells = {}
        for dow, hr, w, p, l, e, n in rows:
            wr = _canonical_wr(int(w or 0), int(p or 0), int(l or 0), int(e or 0))
            cells[f"{int(dow)}_{int(hr)}"] = {
                "dow": int(dow), "hour": int(hr),
                "n": int(n or 0), "wr": wr,
                "wins": int(w or 0), "partial": int(p or 0),
                "losses": int(l or 0), "expired": int(e or 0),
            }
        # Summary: best/worst cells with n >= 2
        usable = [c for c in cells.values() if c["n"] >= 2]
        best  = max(usable, key=lambda c: c["wr"], default=None)
        worst = min(usable, key=lambda c: c["wr"], default=None)
        return {
            "ok": True, "cells": cells,
            "summary": {
                "n_cells_populated": len(cells),
                "n_cells_usable":    len(usable),
                "best":  best,
                "worst": worst,
            }
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "cells": {}, "summary": {}}

def get_intelligence():
    try:
        conn = _connect()
        def q1(sql, p=()): return conn.execute(sql, p).fetchone()[0]

        # ── Closed signal counts — use _canonical_wr (PARTIAL=0.5, matches get_stats) ──
        _wins    = q1("SELECT COUNT(*) FROM results WHERE result='WIN'")
        _partial = q1("SELECT COUNT(*) FROM results WHERE result IN ('PARTIAL','PARTIAL_TP1','PARTIAL_TP2')")
        _losses  = q1("SELECT COUNT(*) FROM results WHERE result='LOSS'")
        _expired = q1("SELECT COUNT(*) FROM results WHERE result='EXPIRED'")
        total_closed = _wins + _partial + _losses + _expired
        overall_wr   = _canonical_wr(_wins, _partial, _losses, _expired)
        avg_conf     = q1("SELECT AVG(confidence) FROM signals WHERE confidence IS NOT NULL")
        avg_conf     = round(avg_conf, 1) if avg_conf else 0
        avg_rr       = q1("SELECT AVG(rr1) FROM signals WHERE rr1 IS NOT NULL")
        avg_rr       = round(avg_rr, 2) if avg_rr else 0

        # ── High-confidence WR (7-10) ─────────────────────────
        hi_total = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                         WHERE s.confidence>=7 AND r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED')""")
        hi_wins  = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                         WHERE s.confidence>=7 AND r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2')""")
        hi_wr    = round(hi_wins / hi_total * 100, 1) if hi_total else 0

        # ── Low-confidence WR (1-4) ───────────────────────────
        lo_total = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                         WHERE s.confidence<=4 AND r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED')""")
        lo_wins  = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                         WHERE s.confidence<=4 AND r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2')""")
        lo_wr    = round(lo_wins / lo_total * 100, 1) if lo_total else 0

        # ── Per-confidence-level breakdown ────────────────────
        # C4 (2026-05-22 tracker audit): also break down by outcome class
        # (WIN / PARTIAL / LOSS / EXPIRED) so the stacked bar chart can render.
        conf_levels = []
        for c in range(1, 11):
            row = conn.execute(
                """SELECT
                       SUM(CASE WHEN r.result='WIN' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN r.result IN ('PARTIAL','PARTIAL_TP1','PARTIAL_TP2') THEN 1 ELSE 0 END),
                       SUM(CASE WHEN r.result='LOSS' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN r.result='EXPIRED' THEN 1 ELSE 0 END)
                   FROM results r JOIN signals s ON r.signal_id=s.id
                   WHERE s.confidence=?""", (c,)).fetchone()
            wins_c = int(row[0] or 0); partials_c = int(row[1] or 0)
            losses_c = int(row[2] or 0); expired_c = int(row[3] or 0)
            ct = wins_c + partials_c + losses_c + expired_c
            cw = wins_c + partials_c   # legacy "any payout" count (back-compat)
            total_at_c = q1("SELECT COUNT(*) FROM signals WHERE confidence=?", (c,))
            if total_at_c > 0:
                conf_levels.append({
                    "level":   c,
                    "wr":      _canonical_wr(wins_c, partials_c, losses_c, expired_c),
                    "count":   total_at_c,
                    "closed":  ct,
                    # C4 outcome split for stacked bar
                    "wins":    wins_c,
                    "partial": partials_c,
                    "losses":  losses_c,
                    "expired": expired_c,
                })
        best_conf = max((x for x in conf_levels if x["closed"]>=2),
                        key=lambda x: x["wr"], default=None)

        # ── Token performance ─────────────────────────────────
        _OGD_MIN = 30
        token_rows = conn.execute(
            "SELECT DISTINCT token FROM signals ORDER BY token").fetchall()
        tokens = []
        for (tok,) in token_rows:
            tot = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                        WHERE s.token=? AND r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED')""", (tok,))
            # Fix #18 (2026-05-22, audit cycle 7 REGRESSION-D): split WIN vs PARTIAL counts
            # so WR matches _canonical_wr (PARTIAL=0.5). Previously `w` was COUNT() of
            # WIN+PARTIAL+PARTIAL_TP1+PARTIAL_TP2, which double-counts partials as full wins.
            _w_full = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                            WHERE s.token=? AND r.result='WIN'""", (tok,))
            _p_full = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                            WHERE s.token=? AND r.result IN ('PARTIAL','PARTIAL_TP1','PARTIAL_TP2')""", (tok,))
            _l_full = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                            WHERE s.token=? AND r.result='LOSS'""", (tok,))
            _e_full = q1("""SELECT COUNT(*) FROM results r JOIN signals s ON r.signal_id=s.id
                            WHERE s.token=? AND r.result='EXPIRED'""", (tok,))
            w   = _w_full + _p_full  # legacy: any-payout count for back-compat callers
            # C5 (2026-05-22 tracker audit): Wilson 95% CI for the token bar chart
            # error whiskers. Treat each PARTIAL as 0.5 wins (matches _canonical_wr).
            _eq_wins = round(_w_full + 0.5 * _p_full)
            _wlo, _whi = _wilson_ci(tot, _eq_wins) if tot > 0 else (0.0, 0.0)
            ac  = q1("SELECT AVG(confidence) FROM signals WHERE token=? AND confidence IS NOT NULL",(tok,))
            ar  = q1("SELECT AVG(rr1) FROM signals WHERE token=? AND rr1 IS NOT NULL", (tok,))
            ts  = q1("SELECT COUNT(*) FROM signals WHERE token=?", (tok,))
            # Fix 1 & Fix 3: OGD blend status and recent WR for gate visibility
            ogd_n = q1("SELECT MAX(n_updates) FROM token_weights WHERE token=?", (tok,)) or 0
            blend_pct = round(min(0.70, max(0.0, (ogd_n - _OGD_MIN) / 170)) * 100) if ogd_n >= _OGD_MIN else 0
            wr30_rows = conn.execute(
                """SELECT result FROM results r JOIN signals s ON r.signal_id=s.id
                   WHERE s.token=? AND r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
                   ORDER BY r.id DESC LIMIT 30""", (tok,)).fetchall()
            recent_wr = None
            if len(wr30_rows) >= 5:
                # Fix #18: include PARTIAL_TP1/TP2 in partial-weight bucket
                _PARTIAL_SET = ("PARTIAL", "PARTIAL_TP1", "PARTIAL_TP2")
                recent_wr = round(
                    sum(1.0 if r == "WIN" else (0.5 if r in _PARTIAL_SET else 0.0)
                        for (r,) in wr30_rows) / len(wr30_rows), 3)
            tokens.append({"token":tok,"signals":ts,"closed":tot,"wins":w,
                           "losses":tot-w,"wr":_canonical_wr(_w_full, _p_full, _l_full, _e_full),
                           "wr_lo":_wlo, "wr_hi":_whi,   # C5: Wilson 95% CI
                           "avg_conf":round(ac,1) if ac else 0,
                           "avg_rr":round(ar,2) if ar else 0,
                           "ogd_n":int(ogd_n),"blend_pct":blend_pct,
                           "recent_wr":recent_wr,"wr30_n":len(wr30_rows)})
        tokens.sort(key=lambda x: (x["closed"], x["wr"]), reverse=True)

        # ── Bot Health Score (0-100) ──────────────────────────
        wr_score  = min(round(overall_wr/70*40), 40)
        rr_score  = min(round(avg_rr/2.5*20), 20)
        hc_score  = min(round(hi_wr/80*20), 20) if hi_total >= 3 else 0
        sel_score = min(round((1-lo_wr/100)*20), 20) if lo_total >= 2 else 10
        bot_score = wr_score + rr_score + hc_score + sel_score

        # ── Adaptive gate scalars (Fix 2 & Fix 3 visibility) ─
        bs_rows = conn.execute("SELECT key, value FROM bot_state").fetchall()
        bs      = {k: v for k, v in bs_rows}
        conf_floor     = int(float(bs.get("conf_floor", 1)))
        threshold_adj  = int(float(bs.get("threshold_adj", 0)))
        ranging_floor_raise = max(0, threshold_adj) // 3

        conn.close()
        return {"ok":True,"avg_conf":avg_conf,"hi_wr":hi_wr,"hi_total":hi_total,
                "lo_wr":lo_wr,"lo_total":lo_total,"best_conf":best_conf,
                "conf_levels":conf_levels,"tokens":tokens,"bot_score":bot_score,
                "bot_parts":{"wr":wr_score,"rr":rr_score,"hc":hc_score,"sel":sel_score},
                "total_closed":total_closed,
                "conf_floor":conf_floor,"threshold_adj":threshold_adj,
                "ranging_floor_raise":ranging_floor_raise}
    except Exception as e:
        print(f"[DB] Intelligence error: {e}")
        return {"ok":False,"avg_conf":0,"hi_wr":0,"hi_total":0,"lo_wr":0,"lo_total":0,
                "best_conf":None,"conf_levels":[],"tokens":[],"bot_score":0,
                "bot_parts":{"wr":0,"rr":0,"hc":0,"sel":0},"total_closed":0}

_ADAP_FEATURES  = ["fvg_quality", "mss_quality", "session", "confidence", "trend_strength", "dr_location"]
_ADAP_DEFAULT_W = round(1.0 / len(_ADAP_FEATURES), 4)   # 0.1667
_RISK_PER_TRADE_PCT = 0.01  # mirrors RISK_PER_TRADE_PCT in crypto_alert.py
# _MAX_OPEN, _MAX_SAME_DIR, _MAX_RISK_PCT imported from adaptive_engine above (mode-aware)

def _get_adaptive_weights_raw():
    """Read per-token OGD weight matrix from token_weights, falling back to
    backtest_token_weights (bootstrap pool) for tokens with no live row.

    C-2 fix (tracker audit 2026-05-26 cycle-6): previously read only from
    `token_weights` (the live OGD pool). At PAPER-mode startup that table
    typically has at most 1 row (the most-recently-seeded token, currently
    TON), so the Adaptive tab silently rendered weights for 1 token when the
    bootstrap pool actually carries full priors for all 10 tokens in
    `backtest_token_weights`. Operator wrongly believed the bot had no
    learning state for BTC/ETH/XRP/HBAR/AVAX/LINK/BNB/ADA/POL.

    Each token now carries a `source` field: "live" if from token_weights,
    "bootstrap" if from backtest_token_weights (uses the most recent run's
    seeded weights). The frontend can render a BOOTSTRAP badge accordingly.
    """
    _OGD_MIN = 10  # mirrors OGD_MIN_SAMPLES in adaptive_engine (not SAMPLE_N_OBSERVE=30)
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT token, feature, weight, velocity, n_updates, updated_at "
            "FROM token_weights ORDER BY token, feature"
        ).fetchall()
        tokens: dict = {}
        for token, feature, weight, velocity, n_updates, updated_at in rows:
            if token not in tokens:
                tokens[token] = {f: _ADAP_DEFAULT_W for f in _ADAP_FEATURES}
                tokens[token]["n_updates"] = 0
                tokens[token]["updated_at"] = updated_at or ""
                tokens[token]["source"] = "live"
            if feature in _ADAP_FEATURES:
                tokens[token][feature] = round(float(weight or _ADAP_DEFAULT_W), 6)
                tokens[token]["n_updates"] = max(tokens[token]["n_updates"],
                                                 int(n_updates or 0))
                if updated_at:
                    tokens[token]["updated_at"] = updated_at

        # C-2 fallback: for any token NOT in token_weights, read the bootstrap
        # row from backtest_token_weights. Schema (no run_id column): each
        # (token, feature) is updated in-place by adaptive_engine's bootstrap
        # path, so a single SELECT returns the current state. Mark with
        # source="bootstrap" so the frontend can distinguish from live updates.
        try:
            bs_rows = conn.execute(
                "SELECT token, feature, weight, n_bootstrap, updated_at "
                "FROM backtest_token_weights ORDER BY token, feature"
            ).fetchall()
            for token, feature, weight, n_bootstrap, recorded_at in bs_rows:
                if token in tokens:
                    continue  # already have a live row — live takes precedence
                if token not in tokens:
                    tokens[token] = {f: _ADAP_DEFAULT_W for f in _ADAP_FEATURES}
                    tokens[token]["n_updates"] = 0
                    tokens[token]["updated_at"] = recorded_at or ""
                    tokens[token]["source"] = "bootstrap"
                if feature in _ADAP_FEATURES:
                    tokens[token][feature] = round(float(weight or _ADAP_DEFAULT_W), 6)
                    tokens[token]["n_updates"] = max(tokens[token]["n_updates"],
                                                     int(n_bootstrap or 0))
                    if recorded_at:
                        tokens[token]["updated_at"] = recorded_at
        except Exception:
            # Bootstrap fallback is best-effort; live-only path remains correct
            # if the bootstrap table is unavailable.
            pass
        # Attach OGD blend %, per-token recent win rate, degenerate flag, orphan flag
        for tok in tokens:
            n = tokens[tok]["n_updates"]
            blend = min(0.70, max(0.0, (n - _OGD_MIN) / 170)) if n >= _OGD_MIN else 0.0
            tokens[tok]["blend_pct"] = round(blend * 100)
            wr_rows = conn.execute(
                """SELECT result FROM results r
                   JOIN signals s ON r.signal_id = s.id
                   WHERE s.token = ? AND r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
                   ORDER BY r.id DESC LIMIT 30""", (tok,)
            ).fetchall()
            if len(wr_rows) >= 5:
                # Fix #18 (2026-05-22, audit cycle 7 REGRESSION-D): include
                # PARTIAL_TP1/PARTIAL_TP2 — previous predicate `r in ("WIN","PARTIAL")`
                # silently dropped TP1/TP2 partials to 0 weight.
                _PARTIAL_SET = ("PARTIAL", "PARTIAL_TP1", "PARTIAL_TP2")
                wins = sum(1.0 if r == "WIN" else (0.5 if r in _PARTIAL_SET else 0.0)
                           for (r,) in wr_rows)
                tokens[tok]["recent_wr"] = round(wins / len(wr_rows), 3)
            else:
                tokens[tok]["recent_wr"] = None
            tokens[tok]["wr_n"] = len(wr_rows)
            _feat_weights = {f: tokens[tok].get(f, 0.0) for f in _ADAP_FEATURES}
            _is_degen, _, _ = (_weight_engine._check_degenerate(_feat_weights)
                               if _weight_engine is not None
                               else (max(_feat_weights.values(), default=0.0) > _DEGENERATE_THRESHOLD, "", 0.0))
            tokens[tok]["is_degenerate"] = _is_degen
            tokens[tok]["orphan"] = n == 0
        conn.close()
        return {"ok": True, "tokens": tokens, "feature_order": _ADAP_FEATURES,
                "default_weight": _ADAP_DEFAULT_W, "ogd_min_samples": _OGD_MIN}
    except Exception as e:
        return {"ok": False, "tokens": {}, "feature_order": _ADAP_FEATURES,
                "default_weight": _ADAP_DEFAULT_W, "ogd_min_samples": _OGD_MIN,
                "error": str(e)}

def _get_portfolio_state_raw():
    """Compute current portfolio exposure from open signals."""
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN signal='BUY'  THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN signal='SELL' THEN 1 ELSE 0 END)"
            " FROM signals WHERE status='OPEN'"
        ).fetchone()
        conn.close()
        total  = int(row[0] or 0)
        buys   = int(row[1] or 0)
        sells  = int(row[2] or 0)
        risk_used = round(total * _RISK_PER_TRADE_PCT, 4)
        return {
            "ok":            True,
            "open_count":    total,
            "buy_count":     buys,
            "sell_count":    sells,
            "max_open":      _MAX_OPEN,
            "max_same_dir":  _MAX_SAME_DIR,
            "max_risk_pct":  _MAX_RISK_PCT,
            "risk_used_pct": risk_used,
            "slots_free":    max(0, _MAX_OPEN - total),
            "buy_slots_free":  max(0, _MAX_SAME_DIR - buys),
            "sell_slots_free": max(0, _MAX_SAME_DIR - sells),
        }
    except Exception as e:
        return {"ok": False, "open_count": 0, "buy_count": 0, "sell_count": 0,
                "max_open": _MAX_OPEN, "max_same_dir": _MAX_SAME_DIR,
                "max_risk_pct": _MAX_RISK_PCT, "risk_used_pct": 0.0,
                "slots_free": _MAX_OPEN, "buy_slots_free": _MAX_SAME_DIR,
                "sell_slots_free": _MAX_SAME_DIR, "error": str(e)}

def _get_drift_state_raw():
    """Read rolling baseline stats from market_stats table — no live data needed."""
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT token, stat_name, rolling_mean, rolling_std, n_samples, updated_at "
            "FROM market_stats ORDER BY token, stat_name"
        ).fetchall()
        conn.close()
        tokens: dict = {}
        for token, stat_name, mean, std, n_samples, updated_at in rows:
            if token not in tokens:
                tokens[token] = {"n_samples": 0, "updated_at": updated_at or "",
                                 "active": False}
            tokens[token][stat_name + "_mean"] = round(float(mean or 0), 2)
            tokens[token][stat_name + "_std"]  = round(float(std or 0), 3)
            tokens[token]["n_samples"] = max(tokens[token]["n_samples"],
                                             int(n_samples or 0))
            if updated_at:
                tokens[token]["updated_at"] = updated_at
        for tok, d in tokens.items():
            d["active"] = d["n_samples"] >= 20
            # Derive dynamic thresholds (mirrors DriftDetector.get_dynamic_thresholds)
            adx_mean = d.get("adx_mean", 25.0)
            atr_mean = d.get("atr_ratio_mean", 0.8)
            d["adx_threshold"]   = round(max(18.0, min(35.0, adx_mean * 0.85)), 1)
            vol_adj              = round(min(atr_mean * 3.0, 8.0), 1)
            d["rsi_oversold"]    = round(max(35.0, min(48.0, 45.0 - vol_adj)), 1)
            d["rsi_overbought"]  = round(max(52.0, min(65.0, 55.0 + vol_adj)), 1)
        return {"ok": True, "tokens": tokens}
    except Exception as e:
        return {"ok": False, "tokens": {}, "error": str(e)}

def _get_bot_scalar_state_raw():
    """Read persisted scalar tuning state from bot_state table."""
    try:
        conn = _connect()
        rows = conn.execute("SELECT key, value FROM bot_state").fetchall()
        conn.close()
        state = {k: v for k, v in rows}
        threshold_adj = int(float(state.get("threshold_adj", 0)))
        conf_floor    = int(float(state.get("conf_floor", 1)))
        # Last bot activity — most recent signal timestamp
        conn2 = _connect()
        last_sig = conn2.execute(
            "SELECT timestamp FROM signals ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn2.close()
        last_ts = last_sig[0] if last_sig else None
        # bot_active: True if a cycle completed within the last 5 minutes (last_cycle_ts),
        # OR a signal was generated within the last 6 hours (fallback for bots without the key).
        bot_active = False
        cycle_ts = state.get("last_cycle_ts")
        if cycle_ts:
            try:
                bot_active = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.strptime(cycle_ts[:19], "%Y-%m-%d %H:%M:%S")) < timedelta(minutes=5)
            except Exception:
                pass
        if not bot_active and last_ts:
            try:
                last_dt = datetime.strptime(last_ts[:19], "%Y-%m-%d %H:%M:%S")
                bot_active = (datetime.now(timezone.utc).replace(tzinfo=None) - last_dt) < timedelta(hours=6)
            except Exception:
                pass
        return {"ok": True, "threshold_adj": threshold_adj,
                "conf_floor": conf_floor, "last_signal_ts": last_ts,
                "bot_active": bot_active}
    except Exception as e:
        return {"ok": False, "threshold_adj": 0, "conf_floor": 1,
                "last_signal_ts": None, "bot_active": False, "error": str(e)}

def get_adaptive_summary():
    """Single combined endpoint for the Adaptive Learning tab — 15s cached."""
    weights   = _cached_adaptive("weights",   lambda: _get_adaptive_weights_raw())
    portfolio = _cached_adaptive("portfolio", lambda: _get_portfolio_state_raw())
    drift     = _cached_adaptive("drift",     lambda: _get_drift_state_raw())
    bot_state = _cached_adaptive("bot_state", lambda: _get_bot_scalar_state_raw())
    with _adap_lock:
        entry = _adaptive_cache.get("weights")
        cache_age = round((datetime.now() - entry["ts"]).total_seconds()) if entry else 0
    return {
        "ok":       True,
        "weights":  weights,
        "portfolio": portfolio,
        "drift":    drift,
        "bot_state": bot_state,
        "cache_age_sec": cache_age,
    }

def get_adaptive_health():
    """Per-token OGD health status for the dashboard health badge row.

    Returns is_degenerate, max_weight, n_updates, weight_entropy per token.
    Delegates to weight_engine.health_check() and augments with degenerate_threshold.
    """
    if _weight_engine is None:
        return {"ok": False, "error": "adaptive_engine not loaded", "tokens": {}}
    try:
        health = _weight_engine.health_check()
        return {
            "ok":                  True,
            "tokens":              health,
            "degenerate_threshold": _DEGENERATE_THRESHOLD,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "tokens": {}}


def get_tune_history():
    """Return all tune_history rows ordered newest-first for the dashboard table."""
    try:
        _init_ae_tables()
        conn = _connect()
        rows = conn.execute(
            """SELECT id, applied_at, param, old_val, new_val, signals_at_apply,
                      backtest_run_id, train_wr, test_wr, post_apply_wr, post_apply_n,
                      status, notes, backup_file
               FROM tune_history ORDER BY id DESC LIMIT 500"""
        ).fetchall()
        conn.close()
        keys = ["id", "applied_at", "param", "old_val", "new_val", "signals_at_apply",
                "backtest_run_id", "train_wr", "test_wr", "post_apply_wr", "post_apply_n",
                "status", "notes", "backup_file"]
        return {"ok": True, "history": [dict(zip(keys, r)) for r in rows]}
    except Exception as e:
        return {"ok": False, "error": str(e), "history": []}


def init_backtest_db():
    try:
        conn = _connect()
        conn.execute("""CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL, days INTEGER DEFAULT 90,
            total_signals INTEGER DEFAULT 0, overall_wr REAL DEFAULT 0,
            avg_rr REAL DEFAULT 0, status TEXT DEFAULT 'DONE',
            summary TEXT, recommendations TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS backtest_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER REFERENCES backtest_runs(id),
            token TEXT, signal TEXT, price REAL, ts TEXT,
            regime TEXT, confidence INTEGER, wscore REAL,
            margin REAL, conflict TEXT,
            tp1_pct REAL, sl_pct REAL, rr1 REAL,
            tp_reached INTEGER DEFAULT 0, outcome TEXT
        )""")
        for col, typ in [
            ("net_tp1_pct",    "REAL"),  ("net_sl_pct",   "REAL"),
            ("net_rr1",        "REAL"),  ("breakeven_wr", "REAL"),
            ("sweep_type",     "TEXT"),  ("fvg_pct",      "REAL"),
            ("trend_1h",       "TEXT"),  ("bias_4h",      "TEXT"),
            ("ifvg_present",   "INTEGER"), ("ifvg_direction", "TEXT"),
            ("ifvg_age_bars",  "INTEGER"), ("ifvg_5m_used", "INTEGER"),
            ("session",        "TEXT"),  ("hour_utc",     "INTEGER"),
            ("day_of_week",    "INTEGER"),
            ("dr_location",    "TEXT"),  ("mss_quality",  "TEXT"),
            ("fvg_quality",    "TEXT"),  ("smt_type",     "TEXT"),
            ("entry_type",     "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE backtest_signals ADD COLUMN {col} {typ}")
            except Exception:
                pass
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[DB] backtest init error: {e}")

def get_backtest_results(run_id=None):
    try:
        conn = _connect(); conn.row_factory = sqlite3.Row
        if run_id:
            row = conn.execute("SELECT * FROM backtest_runs WHERE id=?", (run_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
        if not row: conn.close(); return {"ok":False,"error":"No runs yet"}
        data = dict(row)
        data["summary"]         = json.loads(data["summary"])         if data["summary"]         else {}
        data["recommendations"] = json.loads(data["recommendations"]) if data["recommendations"] else []
        conn.close(); return {"ok":True, **data}
    except Exception as e:
        return {"ok":False, "error":str(e)}

def get_backtest_history():
    """Return last 20 backtest runs for the history dropdown.

    2026-05-27: Added `config_hash` so the Backtest tab can disambiguate
    runs differing only on CRT-Pro / Wyckoff / ENABLE_5M_SWEEP env knobs.
    Runs sharing a hash share an identical knob configuration; runs with
    different hashes are honest-DSR distinct.
    """
    try:
        conn = _connect(); conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id,run_date,days,total_signals,overall_wr,avg_rr,status,config_hash "
            "FROM backtest_runs ORDER BY id DESC LIMIT 20"
        ).fetchall()
        conn.close(); return {"ok":True,"runs":[dict(r) for r in rows]}
    except Exception as e:
        return {"ok":False,"error":str(e),"runs":[]}

# ── Tune Bot file targets (Phase A item #4 — config.py is the source of truth) ──
# The Tune Bot edits config.py's per-field constants (e.g. LIVE_FVG_MIN_QUALITY = ...).
# strategy_engine.py builds StrategyConfig(**LIVE_CONFIG_KWARGS); editing it has no effect.
CONFIG_PATH = os.path.join(_ROOT, "config.py")

# Anchors — fail loud if missing so we never silently corrupt config.py.
_LIVE_ANCHOR     = "# ── LIVE_CONFIG — per-field constants"
_BACKTEST_ANCHOR = "# ── BACKTEST_CONFIG — per-field constants"


def _slice_config_blocks(content: str):
    """Return (live_block_text, backtest_block_text, full_text) — raises on missing anchor.

    The two blocks are scanned by Tune Bot regexes; each block is from the
    section header to the next 'section header / KWARGS dict' boundary. Caller
    is responsible for the read-only contract (no mutation through this view)."""
    live_idx = content.find(_LIVE_ANCHOR)
    bt_idx   = content.find(_BACKTEST_ANCHOR)
    if live_idx == -1:
        raise ValueError(
            f"Cannot find '{_LIVE_ANCHOR}' in config.py. File structure changed — manual edit required."
        )
    if bt_idx == -1:
        raise ValueError(
            f"Cannot find '{_BACKTEST_ANCHOR}' in config.py. "
            "Refusing to modify file — BACKTEST_CONFIG isolation cannot be guaranteed."
        )
    kwargs_idx = content.find("LIVE_CONFIG_KWARGS", bt_idx)
    live_block = content[live_idx:bt_idx]
    bt_block   = content[bt_idx:kwargs_idx] if kwargs_idx != -1 else content[bt_idx:]
    return live_block, bt_block, content


def read_bot_values():
    """Read current LIVE_CONFIG values from config.py per-field constants."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        live_block, _, _ = _slice_config_blocks(content)

        def _str_param(env_name, default):
            # Matches e.g.: LIVE_FVG_MIN_QUALITY:      str  = _env_choice("LIVE_FVG_MIN_QUALITY", "HIGH"
            m = re.search(
                rf'{re.escape(env_name)}\s*:\s*str\s*=\s*_env_choice\("{re.escape(env_name)}",\s*"(\w+)"',
                live_block,
            )
            return m.group(1) if m else default

        def _bool_param(env_name, default):
            # Matches e.g.: LIVE_DEALING_RANGE_GATE:   bool = _env_bool("LIVE_DEALING_RANGE_GATE", True)
            m = re.search(
                rf'{re.escape(env_name)}\s*:\s*bool\s*=\s*_env_bool\("{re.escape(env_name)}",\s*(True|False)',
                live_block,
            )
            return (m.group(1) == "True") if m else default

        return {
            "ok":                 True,
            "fvg_min_quality":    _str_param("LIVE_FVG_MIN_QUALITY",  "HIGH"),
            "mss_min_quality":    _str_param("LIVE_MSS_MIN_QUALITY",  "LOW"),
            "bias_4h_gate":       _str_param("LIVE_BIAS_4H_GATE",     "none"),
            "trend_1h_gate":      _str_param("LIVE_TREND_1H_GATE",    "loose"),
            "dealing_range_gate": _bool_param("LIVE_DEALING_RANGE_GATE", True),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def read_backtest_config_values() -> dict:
    """Read current BACKTEST_CONFIG values from config.py per-field constants."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        _, bt_block, _ = _slice_config_blocks(content)

        def _str_p(env_name, default):
            m = re.search(
                rf'{re.escape(env_name)}\s*:\s*str\s*=\s*_env_choice\("{re.escape(env_name)}",\s*"(\w+)"',
                bt_block,
            )
            return m.group(1) if m else default

        def _bool_p(env_name, default):
            m = re.search(
                rf'{re.escape(env_name)}\s*:\s*bool\s*=\s*_env_bool\("{re.escape(env_name)}",\s*(True|False)',
                bt_block,
            )
            return (m.group(1) == "True") if m else default

        return {
            "ok":                 True,
            "fvg_min_quality":    _str_p("BACKTEST_FVG_MIN_QUALITY",  "HIGH"),
            "mss_min_quality":    _str_p("BACKTEST_MSS_MIN_QUALITY",  "LOW"),
            "bias_4h_gate":       _str_p("BACKTEST_BIAS_4H_GATE",     "none"),
            "trend_1h_gate":      _str_p("BACKTEST_TREND_1H_GATE",    "loose"),
            "dealing_range_gate": _bool_p("BACKTEST_DEALING_RANGE_GATE", False),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tune_status() -> dict:
    """Return full TuneBot status. Read-only — no side effects.

    Shows: current LIVE_CONFIG values, BACKTEST_CONFIG values, strategy_version,
    last apply, last rollback, frequency gate state, and whether a new apply is safe.
    """
    result: dict = {
        "ok":                  True,
        "live_config":         None,
        "backtest_config":     None,
        "strategy_version":    None,
        "last_apply":          None,
        "last_rollback":       None,
        "frequency_gate":      None,
        "can_apply":           False,
        "cannot_apply_reason": None,
    }

    result["live_config"]     = read_bot_values()
    result["backtest_config"] = read_backtest_config_values()

    try:
        result["strategy_version"] = int(_load_scalar("strategy_version", 1))
    except Exception:
        result["strategy_version"] = None

    # Last apply and last rollback from tune_history
    try:
        conn = _connect()
        la = conn.execute(
            "SELECT id, applied_at, param, old_val, new_val, status, backup_file "
            "FROM tune_history WHERE status != 'ROLLED_BACK' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if la:
            result["last_apply"] = {
                "id": la[0], "applied_at": la[1], "param": la[2],
                "old_val": la[3], "new_val": la[4],
                "status": la[5], "backup_file": la[6],
            }
        lr = conn.execute(
            "SELECT id, applied_at, param, old_val, new_val, status "
            "FROM tune_history WHERE status='ROLLED_BACK' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if lr:
            result["last_rollback"] = {
                "id": lr[0], "applied_at": lr[1], "param": lr[2],
                "old_val": lr[3], "new_val": lr[4], "status": lr[5],
            }
        conn.close()
    except Exception as e:
        result["tune_history_error"] = str(e)

    # Frequency gate
    _last_at = _load_scalar("tune_last_applied_at")
    _last_n  = int(_load_scalar("tune_signals_at_last_apply", 0) or 0)
    if _last_at:
        try:
            _now       = datetime.now(timezone.utc).replace(tzinfo=None)
            _last_dt   = (datetime.fromisoformat(_last_at.replace("Z", "+00:00"))
                          if "T" in _last_at
                          else datetime.strptime(_last_at, "%Y-%m-%d %H:%M:%S"))
            _days      = (_now - _last_dt).days
            _conn      = _connect()
            _cur_n     = _conn.execute(
                "SELECT COUNT(*) FROM results WHERE result IN "
                "('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')"
            ).fetchone()[0] or 0
            _conn.close()
            _new_sigs  = max(0, _cur_n - _last_n)
            _need_days = max(0, 14 - _days)
            _need_sigs = max(0, 50 - _new_sigs)
            gate_ok    = _need_days == 0 or _need_sigs == 0
            result["frequency_gate"] = {
                "last_applied_at":  _last_at,
                "days_since_apply": _days,
                "new_signals":      _new_sigs,
                "need_days":        _need_days,
                "need_signals":     _need_sigs,
                "passed":           gate_ok,
            }
            if not gate_ok:
                result["cannot_apply_reason"] = (
                    f"Frequency gate: need {_need_sigs} more signals "
                    f"OR {_need_days} more days since last apply"
                )
            else:
                result["can_apply"] = True
        except Exception as e:
            result["frequency_gate"] = {"error": str(e)}
    else:
        result["frequency_gate"] = {
            "passed": True,
            "note":   "No previous apply recorded — frequency gate not yet active",
        }
        result["can_apply"] = True

    return result


def _tune_wr(sigs):
    """Win rate for a list of raw backtest signal dicts (outcome strings).
    PARTIAL_TP1/TP2 count as 0.5 wins, consistent with _canonical_wr()."""
    if not sigs: return 0.0
    closed = [s for s in sigs if s["outcome"] in ("WIN", "LOSS", "PARTIAL_TP1", "PARTIAL_TP2", "EXPIRED")]
    if not closed: return 0.0
    wins = sum(
        1.0 if s["outcome"] == "WIN"
        else 0.5 if s["outcome"] in ("PARTIAL_TP1", "PARTIAL_TP2")
        else 0.0
        for s in closed
    )
    return round(wins / len(closed) * 100, 1)

def _load_raw_bt_signals(run_id):
    """Load individual signal rows for a backtest run — needed for train/test split."""
    try:
        conn = _connect()
        rows = conn.execute(
            """SELECT ts, regime, confidence, outcome,
                      session, mss_quality, fvg_quality, smt_type, dr_location, signal
               FROM backtest_signals WHERE run_id=? ORDER BY ts""",
            (run_id,)).fetchall()
        conn.close()
        return [{"ts": r[0], "regime": r[1], "confidence": r[2], "outcome": r[3],
                 "session": r[4] or "OVERNIGHT", "mss_quality": r[5] or "NONE",
                 "fvg_quality": r[6] or "NONE", "smt_type": r[7] or "NONE",
                 "dr_location": r[8] or "UNKNOWN", "signal": r[9] or "BUY"}
                for r in rows]
    except Exception:
        return []

def _split_by_time(raw_sigs, train_pct=0.60):
    """Split raw signals into train (first train_pct%) and test (remainder) by timestamp."""
    if not raw_sigs:
        return [], []
    n = len(raw_sigs)
    split = max(1, int(n * train_pct))
    return raw_sigs[:split], raw_sigs[split:]

def _wilson_ci(n: int, wins: int, z: float = 1.96) -> tuple:
    """Wilson score 95% CI for a proportion. Returns (lo_pct, hi_pct)."""
    if n <= 0:
        return (0.0, 100.0)
    p      = wins / n
    denom  = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    lo = max(0.0, round((centre - margin) / denom * 100, 1))
    hi = min(100.0, round((centre + margin) / denom * 100, 1))
    return (lo, hi)

def _regime_wr_from_raw(raw_sigs, regime):
    subset = [s for s in raw_sigs if s["regime"] == regime]
    return _tune_wr(subset), len(subset)

def _quality_wr_from_raw(raw_sigs, field, value):
    subset = [s for s in raw_sigs if s.get(field) == value]
    return _tune_wr(subset), len(subset)

def _session_wr_from_raw(raw_sigs, session):
    subset = [s for s in raw_sigs if s.get("session") == session]
    return _tune_wr(subset), len(subset)

def _conf_wr_from_raw(raw_sigs, conf):
    subset = [s for s in raw_sigs if s.get("confidence") == conf]
    return _tune_wr(subset), len(subset)

def calculate_tune_preview():
    """Analyze latest backtest and propose ICT LIVE_CONFIG gate changes.

    Targets real gate parameters in strategy_engine.py:
      fvg_min_quality, mss_min_quality — quality gates for ICT signals
    A change is only recommended when the finding holds in BOTH train AND test halves.
    Session and regime breakdowns are reported as validation_notes (informational).
    """
    try:
        bt = get_backtest_results()
        if not bt.get("ok"):
            return {"ok": False, "error": "No backtest data — run backtest first"}
        cur = read_bot_values()
        if not cur.get("ok"):
            return {"ok": False, "error": "Cannot read strategy_engine.py: " + cur.get("error", "")}

        # ── P1-8: Frequency gate — min 50 new closed signals OR 14 days since last apply ──
        _last_at  = _load_scalar("tune_last_applied_at")
        _last_n   = int(_load_scalar("tune_signals_at_last_apply", 0) or 0)
        if _last_at:
            try:
                _now         = datetime.now(timezone.utc).replace(tzinfo=None)
                _last_dt     = datetime.fromisoformat(_last_at.replace("Z", "+00:00")) if "T" in _last_at else datetime.strptime(_last_at, "%Y-%m-%d %H:%M:%S")
                _days_since  = (_now - _last_dt).days
                _conn        = _connect()
                _cur_n       = _conn.execute(
                    "SELECT COUNT(*) FROM results WHERE result IN "
                    "('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')"
                ).fetchone()[0] or 0
                _conn.close()
                _new_sigs    = max(0, _cur_n - _last_n)
                _need_days   = max(0, 14 - _days_since)
                _need_sigs   = max(0, 50 - _new_sigs)
                if _need_days > 0 and _need_sigs > 0:
                    return {
                        "ok": False,
                        "error": (
                            f"Frequency gate: {_new_sigs} new closed signals since last tune "
                            f"({_days_since} days ago). "
                            f"Need {_need_sigs} more signals OR {_need_days} more days."
                        ),
                        "frequency_gate": {
                            "days_since":   _days_since,
                            "new_signals":  _new_sigs,
                            "need_days":    _need_days,
                            "need_signals": _need_sigs,
                        },
                    }
            except Exception as _ge:
                print(f"[TUNE] frequency gate error (skipping): {_ge}")

        overall_wr = bt.get("overall_wr", 0)
        total_sigs = bt.get("total_signals", 0)
        run_id     = bt.get("id")

        MIN_TOTAL = 30
        if total_sigs < MIN_TOTAL:
            ci = round(100 / (2 * (total_sigs ** 0.5)), 0) if total_sigs > 0 else 99
            return {
                "ok": False,
                "error": (
                    f"Only {total_sigs} backtest signals — need {MIN_TOTAL} minimum. "
                    f"95% CI on WR is ±{ci:.0f}pp — any change would be noise."
                ),
            }

        raw_sigs = _load_raw_bt_signals(run_id) if run_id else []
        # Filter to ICT-quality signals only (fvg_quality set and non-NONE)
        ict_sigs = [s for s in raw_sigs if s.get("fvg_quality") not in ("NONE", "")]
        train_sigs, test_sigs = _split_by_time(ict_sigs)
        has_split = len(train_sigs) >= 10 and len(test_sigs) >= 10

        adjustments    = []
        validation_notes = []

        if ict_sigs:
            validation_notes.append(
                f"ICT-quality signals: {len(ict_sigs)} of {total_sigs} total "
                f"({len(train_sigs)} train / {len(test_sigs)} test)"
            )
        else:
            validation_notes.append(
                "No ICT-quality signals found (fvg_quality is NULL for all rows) — "
                "run a new backtest to generate quality metadata."
            )
            return {
                "ok": True, "adjustments": [], "current": cur,
                "backtest_wr": overall_wr, "total_signals": total_sigs,
                "run_date": bt.get("run_date", ""), "validation_notes": validation_notes,
            }

        MIN_N = 20  # minimum per quality bucket to trust the WR

        # ── FVG QUALITY GATE ──────────────────────────────────────────────
        cur_fvg = cur.get("fvg_min_quality", "MEDIUM")
        fvg_rows = {}
        for q in ("HIGH", "MEDIUM", "LOW"):
            wr, n = _quality_wr_from_raw(ict_sigs, "fvg_quality", q)
            fvg_rows[q] = (wr, n)

        high_wr, high_n = fvg_rows["HIGH"]
        med_wr,  med_n  = fvg_rows["MEDIUM"]
        low_wr,  low_n  = fvg_rows["LOW"]

        # Build FVG notes with Wilson CI
        fvg_note_parts = []
        for q, (wr, n) in fvg_rows.items():
            if n > 0:
                lo, hi = _wilson_ci(n, round(wr * n / 100))
                fvg_note_parts.append(f"{q}: {wr:.0f}% [{lo:.0f}-{hi:.0f}%] (n={n})")
        if fvg_note_parts:
            validation_notes.append("FVG quality breakdown: " + " | ".join(fvg_note_parts))

        if (cur_fvg in ("LOW", "MEDIUM") and high_n >= MIN_N and med_n >= MIN_N
                and (high_wr - med_wr) >= 15):
            # Verify in both halves
            hi_tr, hi_tr_n = _quality_wr_from_raw(train_sigs, "fvg_quality", "HIGH")
            hi_te, hi_te_n = _quality_wr_from_raw(test_sigs,  "fvg_quality", "HIGH")
            me_tr, me_tr_n = _quality_wr_from_raw(train_sigs, "fvg_quality", "MEDIUM")
            me_te, me_te_n = _quality_wr_from_raw(test_sigs,  "fvg_quality", "MEDIUM")
            high_beats_in_train = (hi_tr - me_tr) >= 12 and hi_tr_n >= 8 and me_tr_n >= 8
            high_beats_in_test  = (hi_te - me_te) >= 12 and hi_te_n >= 8 and me_te_n >= 8
            if high_beats_in_train and high_beats_in_test:
                adjustments.append({
                    "param":   "FVG_MIN_QUALITY",
                    "old_val": cur_fvg,
                    "new_val": "HIGH",
                    "delta":   f"{cur_fvg} -> HIGH",
                    "reason":  (
                        f"FVG HIGH outperforms MEDIUM in both halves: "
                        f"train ({hi_tr:.0f}% vs {me_tr:.0f}%, n={hi_tr_n}/{me_tr_n}) "
                        f"and test ({hi_te:.0f}% vs {me_te:.0f}%, n={hi_te_n}/{me_te_n})"
                    ),
                })
            elif high_beats_in_train and not high_beats_in_test:
                validation_notes.append(
                    f"FVG quality: HIGH > MEDIUM in train ({hi_tr:.0f}% vs {me_tr:.0f}%) "
                    f"but NOT in test ({hi_te:.0f}% vs {me_te:.0f}%) — in-sample noise, suppressed"
                )

        elif cur_fvg == "HIGH" and med_n >= MIN_N and low_n >= MIN_N and med_wr >= (high_wr - 5):
            # HIGH gate may be too strict — MEDIUM is nearly as good
            validation_notes.append(
                f"FVG quality: HIGH gate is active but MEDIUM WR is {med_wr:.0f}% vs HIGH {high_wr:.0f}% "
                f"(gap < 5pp) — consider relaxing to MEDIUM for more signals"
            )

        # ── MSS QUALITY GATE ─────────────────────────────────────────────
        cur_mss = cur.get("mss_min_quality", "MEDIUM")
        mss_rows = {}
        for q in ("HIGH", "MEDIUM", "LOW"):
            wr, n = _quality_wr_from_raw(ict_sigs, "mss_quality", q)
            mss_rows[q] = (wr, n)

        mss_note_parts = []
        for q, (wr, n) in mss_rows.items():
            if n > 0:
                lo, hi = _wilson_ci(n, round(wr * n / 100))
                mss_note_parts.append(f"{q}: {wr:.0f}% [{lo:.0f}-{hi:.0f}%] (n={n})")
        if mss_note_parts:
            validation_notes.append("MSS quality breakdown: " + " | ".join(mss_note_parts))

        mss_hi_wr, mss_hi_n = mss_rows["HIGH"]
        mss_me_wr, mss_me_n = mss_rows["MEDIUM"]
        if (cur_mss in ("LOW", "MEDIUM") and mss_hi_n >= MIN_N and mss_me_n >= MIN_N
                and (mss_hi_wr - mss_me_wr) >= 15):
            mh_tr, mh_tr_n = _quality_wr_from_raw(train_sigs, "mss_quality", "HIGH")
            mh_te, mh_te_n = _quality_wr_from_raw(test_sigs,  "mss_quality", "HIGH")
            mm_tr, mm_tr_n = _quality_wr_from_raw(train_sigs, "mss_quality", "MEDIUM")
            mm_te, mm_te_n = _quality_wr_from_raw(test_sigs,  "mss_quality", "MEDIUM")
            high_beats_in_train = (mh_tr - mm_tr) >= 12 and mh_tr_n >= 8 and mm_tr_n >= 8
            high_beats_in_test  = (mh_te - mm_te) >= 12 and mh_te_n >= 8 and mm_te_n >= 8
            if high_beats_in_train and high_beats_in_test:
                adjustments.append({
                    "param":   "MSS_MIN_QUALITY",
                    "old_val": cur_mss,
                    "new_val": "HIGH",
                    "delta":   f"{cur_mss} -> HIGH",
                    "reason":  (
                        f"MSS HIGH outperforms MEDIUM in both halves: "
                        f"train ({mh_tr:.0f}% vs {mm_tr:.0f}%) "
                        f"and test ({mh_te:.0f}% vs {mm_te:.0f}%)"
                    ),
                })
            elif high_beats_in_train and not high_beats_in_test:
                validation_notes.append(
                    f"MSS quality: HIGH > MEDIUM in train ({mh_tr:.0f}% vs {mm_tr:.0f}%) "
                    f"but NOT in test ({mh_te:.0f}% vs {mm_te:.0f}%) — suppressed"
                )

        # ── SESSION TUNING (P2-1) ─────────────────────────────────────────
        _SESSION_HOURS = {
            "NY_AM_KZ":  [13, 14, 15],
            "LONDON_KZ": [2, 3, 4],
            "ASIA_KZ":   [20, 21, 22, 23],
        }
        sessions   = ["NY_AM_KZ", "LONDON_KZ", "ASIA_KZ", "OVERNIGHT"]
        sess_parts = []
        for sess in sessions:
            wr, n = _session_wr_from_raw(ict_sigs, sess)
            if n > 0:
                lo, hi = _wilson_ci(n, round(wr * n / 100))
                sess_parts.append(f"{sess.replace('_KZ','')}: {wr:.0f}% [{lo:.0f}-{hi:.0f}%] (n={n})")
            if sess in _SESSION_HOURS and has_split:
                tr_wr, tr_n = _session_wr_from_raw(train_sigs, sess)
                te_wr, te_n = _session_wr_from_raw(test_sigs,  sess)
                if tr_n >= 30 and te_n >= 30 and tr_wr < 38 and te_wr < 38:
                    adjustments.append({
                        "param":   "SESSION_LIQUID_HOURS",
                        "old_val": "all",
                        "new_val": json.dumps(_SESSION_HOURS[sess]),
                        "delta":   f"remove {sess} hours {_SESSION_HOURS[sess]}",
                        "reason":  (
                            f"{sess} WR below 38% in both halves: "
                            f"train {tr_wr:.0f}% (n={tr_n}), test {te_wr:.0f}% (n={te_n})"
                        ),
                    })
        if sess_parts:
            validation_notes.append("Session WR: " + " | ".join(sess_parts))

        # ── CONFIDENCE FLOOR TUNING (P2-2) ────────────────────────────────
        low_conf_sigs  = [s for s in ict_sigs if s.get("confidence", 10) <= 6]
        high_conf_sigs = [s for s in ict_sigs if s.get("confidence", 0)  >= 8]
        cur_conf_floor = int(float(_load_scalar("conf_floor", 1)) or 1)
        if low_conf_sigs:
            lc_n  = len(low_conf_sigs)
            lc_wr = _tune_wr(low_conf_sigs)
            lo, hi = _wilson_ci(lc_n, round(lc_wr * lc_n / 100))
            validation_notes.append(
                f"Low-conf signals (<=6): {lc_wr:.0f}% WR [{lo:.0f}-{hi:.0f}%] (n={lc_n})"
            )
            if has_split and cur_conf_floor < 7:
                lc_tr = [s for s in train_sigs if s.get("confidence", 10) <= 6]
                lc_te = [s for s in test_sigs  if s.get("confidence", 10) <= 6]
                tr_lc = _tune_wr(lc_tr)
                te_lc = _tune_wr(lc_te)
                if len(lc_tr) >= 25 and len(lc_te) >= 25 and tr_lc < 40 and te_lc < 40:
                    adjustments.append({
                        "param":   "CONF_FLOOR_RAISE",
                        "old_val": str(cur_conf_floor),
                        "new_val": "7",
                        "delta":   f"conf_floor: {cur_conf_floor} -> 7",
                        "reason":  (
                            f"Low-conf signals (<=6) WR below 40% in both halves: "
                            f"train {tr_lc:.0f}% (n={len(lc_tr)}), test {te_lc:.0f}% (n={len(lc_te)})"
                        ),
                    })
        if high_conf_sigs:
            hc_n  = len(high_conf_sigs)
            hc_wr = _tune_wr(high_conf_sigs)
            lo, hi = _wilson_ci(hc_n, round(hc_wr * hc_n / 100))
            validation_notes.append(
                f"High-conf signals (>=8): {hc_wr:.0f}% WR [{lo:.0f}-{hi:.0f}%] (n={hc_n})"
            )

        # ── WALK-FORWARD GAP ──────────────────────────────────────────────
        train_wr_val     = _tune_wr(train_sigs) if has_split else None
        test_wr_val      = _tune_wr(test_sigs)  if has_split else None
        walk_forward_gap = None
        if train_wr_val is not None and test_wr_val is not None:
            walk_forward_gap = round(train_wr_val - test_wr_val, 1)
            if walk_forward_gap > 15:
                validation_notes.append(
                    f"Walk-forward gap: train {train_wr_val:.0f}% vs test {test_wr_val:.0f}% "
                    f"(gap={walk_forward_gap:.1f}pp) — possible overfitting, treat adjustments with caution"
                )

        if not has_split:
            validation_notes.append(
                "Train/test split skipped — need >=10 ICT signals in each period. "
                "Gate changes disabled until more data accumulates."
            )

        return {
            "ok":                True,
            "adjustments":       adjustments,
            "current":           cur,
            "backtest_wr":       overall_wr,
            "total_signals":     total_sigs,
            "run_date":          bt.get("run_date", ""),
            "validation_notes":  validation_notes,
            "walk_forward_gap":  walk_forward_gap,
            "train_wr":          train_wr_val,
            "test_wr":           test_wr_val,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

_TUNE_VALID_PARAMS   = {"FVG_MIN_QUALITY", "MSS_MIN_QUALITY", "SESSION_LIQUID_HOURS", "CONF_FLOOR_RAISE"}
_TUNE_QUALITY_VALUES = {"LOW", "MEDIUM", "HIGH"}

def _validate_tune_adjustment(adj):
    """Strict whitelist validation — raises ValueError on any violation.
    Called before the file is opened. Nothing touches disk if validation fails."""
    p   = adj.get("param")
    val = adj.get("new_val")

    if p not in _TUNE_VALID_PARAMS:
        raise ValueError(
            f"Unknown param '{p}'. Accepted: {sorted(_TUNE_VALID_PARAMS)}"
        )

    if p in ("FVG_MIN_QUALITY", "MSS_MIN_QUALITY"):
        if val not in _TUNE_QUALITY_VALUES:
            raise ValueError(
                f"{p} must be one of {sorted(_TUNE_QUALITY_VALUES)}, got {val!r}"
            )
    elif p == "SESSION_LIQUID_HOURS":
        try:
            hours = json.loads(val)
            if not isinstance(hours, list) or not all(isinstance(h, int) and 0 <= h <= 23 for h in hours):
                raise ValueError()
        except Exception:
            raise ValueError(f"SESSION_LIQUID_HOURS new_val must be a JSON int-list of hours 0-23, got {val!r}")
    elif p == "CONF_FLOOR_RAISE":
        try:
            floor = int(val)
            if not (1 <= floor <= 10):
                raise ValueError()
        except Exception:
            raise ValueError(f"CONF_FLOOR_RAISE new_val must be an integer 1-10, got {val!r}")

_TUNE_FIELD_MAP = {
    "FVG_MIN_QUALITY": "fvg_min_quality",
    "MSS_MIN_QUALITY": "mss_min_quality",
}

def apply_tune_adjustments(adjustments, run_id=None, train_wr=None, test_wr=None):
    """Write validated ICT gate changes to config.py LIVE_* per-field constants. Backs up first.

    Phase A item #4 / Audit Adopt 3: config.py is the single source of truth.
    strategy_engine.py builds StrategyConfig(**LIVE_CONFIG_KWARGS) from those
    constants, so editing strategy_engine.py has no effect on live config —
    Tune Bot must target config.py.

    Guards (all checked before any file is opened):
      - Whitelist param + value validation
      - No-op detection (new_val == current_val)
      - BACKTEST_CONFIG anchor present (isolation guarantee)
      - LIVE_CONFIG anchor present
      - Parameter appears exactly once in LIVE_CONFIG block
    Backup is only created after all in-memory changes succeed.
    Backup failure aborts the write — never writes without a backup.
    """
    try:
        if not adjustments:
            return {"ok": False, "error": "No adjustments provided"}

        # ── Phase 1: whitelist validation (param + value) ─────────────────
        for adj in adjustments:
            _validate_tune_adjustment(adj)   # raises ValueError on any violation

        cfg_path = CONFIG_PATH

        with open(cfg_path, "r", encoding="utf-8") as f:
            content = f.read()

        # ── Phase 2: verify file structure anchors ────────────────────────
        split_idx = content.find(_BACKTEST_ANCHOR)
        if split_idx == -1:
            return {
                "ok":    False,
                "error": (
                    f"Cannot find {_BACKTEST_ANCHOR!r} in config.py. "
                    "Refusing to modify file — BACKTEST_CONFIG isolation cannot be guaranteed."
                ),
            }
        live_part  = content[:split_idx]
        after_part = content[split_idx:]

        live_anchor = live_part.find(_LIVE_ANCHOR)
        if live_anchor == -1:
            return {
                "ok":    False,
                "error": (
                    f"Cannot find {_LIVE_ANCHOR!r} in config.py. "
                    "File structure changed — manual edit required."
                ),
            }

        # ── Phase 3: no-op detection + signal count ──────────────────────
        cur = read_bot_values()
        if not cur.get("ok"):
            return {"ok": False, "error": f"Cannot read current LIVE_CONFIG: {cur.get('error', '?')}"}
        for adj in adjustments:
            if adj["param"] in _TUNE_FIELD_MAP:
                field_key = _TUNE_FIELD_MAP[adj["param"]]
                cur_val   = cur.get(field_key)
                if cur_val is not None and cur_val == adj["new_val"]:
                    return {
                        "ok":    False,
                        "error": (
                            f"No-op: {adj['param']} is already {adj['new_val']!r} in LIVE_CONFIG. "
                            "No change needed."
                        ),
                    }

        try:
            _conn      = _connect()
            _sig_count = _conn.execute(
                "SELECT COUNT(*) FROM results WHERE result IN "
                "('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')"
            ).fetchone()[0] or 0
            _conn.close()
        except Exception:
            _sig_count = 0

        # ── Phase 3.5: max 2 APPLIED guard ───────────────────────────────
        # Count only entries from live runs (signals_at_apply > 0) to exclude
        # test-cycle rows which carry status=APPLIED but no real live signals.
        try:
            _ga_conn  = _connect()
            _applied_live = _ga_conn.execute(
                "SELECT COUNT(*) FROM tune_history WHERE status='APPLIED' AND signals_at_apply > 0"
            ).fetchone()[0] or 0
            _ga_conn.close()
        except Exception:
            _applied_live = 0
        if _applied_live >= 2:
            return {
                "ok":    False,
                "error": (
                    "Max 2 APPLIED tune history entries reached. "
                    "Verify or roll back an existing entry before applying new changes."
                ),
            }

        # ── Phase 4: apply changes ────────────────────────────────────────
        applied = []
        for adj in adjustments:
            p   = adj["param"]
            val = adj["new_val"]

            # CONF_FLOOR_RAISE — scalar write only, no file edit
            if p == "CONF_FLOOR_RAISE":
                new_floor = int(val)
                _save_scalar("conf_floor", new_floor)
                applied.append({**adj})
                continue

            # SESSION_LIQUID_HOURS — edit _DEFAULT_LIQUID_HOURS literal in config.py.
            # That constant lives ABOVE the LIVE_ANCHOR but BEFORE the BACKTEST_ANCHOR;
            # it is shared by both LIVE and BACKTEST kwargs (mirrors prior behavior).
            if p == "SESSION_LIQUID_HOURS":
                hours_to_remove = set(json.loads(val))
                # _DEFAULT_LIQUID_HOURS is in live_part because live_anchor is downstream.
                lh_match = re.search(
                    r'(_DEFAULT_LIQUID_HOURS\s*=\s*)(list\(range\(24\)\)|\[[^\]]*\])',
                    live_part,
                )
                if not lh_match:
                    return {"ok": False, "error": "_DEFAULT_LIQUID_HOURS not found in config.py."}
                cur_expr = lh_match.group(2)
                try:
                    if "range(24)" in cur_expr:
                        cur_hours = set(range(24))
                    else:
                        cur_hours = set(ast.literal_eval(cur_expr))
                except Exception:
                    cur_hours = set(range(24))
                new_hours = sorted(cur_hours - hours_to_remove)
                new_live  = live_part[:lh_match.start(2)] + repr(new_hours) + live_part[lh_match.end(2):]
                if new_live == live_part:
                    return {"ok": False, "error": "_DEFAULT_LIQUID_HOURS substitution had no effect"}
                live_part = new_live
                applied.append({**adj, "old_val": cur_expr})
                continue

            # FVG_MIN_QUALITY / MSS_MIN_QUALITY — write the per-field literal in config.py.
            # Format: LIVE_FVG_MIN_QUALITY:      str  = _env_choice("LIVE_FVG_MIN_QUALITY", "HIGH", ...)
            #                                                                                ^^^^^^ default literal — what we edit
            short_field = _TUNE_FIELD_MAP[p]            # e.g. "fvg_min_quality"
            env_name    = "LIVE_" + p                   # e.g. "LIVE_FVG_MIN_QUALITY"
            pre_live    = live_part[:live_anchor]
            cfg_part    = live_part[live_anchor:]

            literal_re = (
                rf'({re.escape(env_name)}\s*:\s*str\s*=\s*_env_choice\("{re.escape(env_name)}",\s*)'
                r'"(\w+)"'
            )
            matches = re.findall(literal_re, cfg_part)
            if len(matches) == 0:
                return {"ok": False, "error": f"Parameter '{env_name}' not found in LIVE_CONFIG block."}
            if len(matches) > 1:
                return {
                    "ok":    False,
                    "error": (
                        f"Parameter '{env_name}' found {len(matches)} times in LIVE_CONFIG block "
                        "(expected exactly 1). Cannot apply safely."
                    ),
                }

            old_val = matches[0][1] if isinstance(matches[0], tuple) else matches[0]
            new_cfg = re.sub(literal_re, rf'\1"{val}"', cfg_part, count=1)
            if new_cfg == cfg_part:
                return {"ok": False, "error": f"Regex substitution had no effect for '{env_name}'"}

            live_part = pre_live + new_cfg
            applied.append({**adj, "old_val": old_val})

        if not applied:
            return {"ok": False, "error": "No changes were produced"}

        # Check if any file changes are needed (scalar-only params skip file write)
        _needs_file_write = any(a["param"] != "CONF_FLOOR_RAISE" for a in applied)

        # ── Phase 5: backup BEFORE writing (failure aborts write) ─────────
        backup     = None
        backup_rel = None
        if _needs_file_write:
            backup = os.path.join(_ROOT, "backups",
                                  f"config.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
            os.makedirs(os.path.join(_ROOT, "backups"), exist_ok=True)
            try:
                shutil.copy2(cfg_path, backup)
            except Exception as e:
                return {"ok": False, "error": f"Backup creation failed: {e}. File not modified."}
            backup_rel = os.path.relpath(backup, _ROOT)

            # ── Phase 6: write production file ────────────────────────────
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(live_part + after_part)

        # ── Phase 7: persist tune_history, scalar state, strategy_version ─
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        tune_ids   = []
        try:
            _init_ae_tables()
            _conn = _connect()
            for a in applied:
                row = _conn.execute(
                    """INSERT INTO tune_history
                       (applied_at, param, old_val, new_val, signals_at_apply,
                        backtest_run_id, train_wr, test_wr, status, backup_file)
                       VALUES (?,?,?,?,?,?,?,?,'APPLIED',?)""",
                    (now_utc, a["param"], a["old_val"], a["new_val"],
                     _sig_count, run_id, train_wr, test_wr, backup_rel)
                )
                tune_ids.append(row.lastrowid)
            _conn.commit()
            _conn.close()
        except Exception as e:
            print(f"[TUNE] tune_history write error: {e}")

        _save_scalar("tune_last_applied_at",       now_utc)
        _save_scalar("tune_signals_at_last_apply", _sig_count)
        _cur_ver = int(_load_scalar("strategy_version", 1))
        _save_scalar("strategy_version", _cur_ver + 1)
        print(f"[TUNE] Applied {len(applied)} change(s), strategy_version -> {_cur_ver + 1}")

        return {
            "ok":            True,
            "applied_count": len(applied),
            "backup":        backup_rel,
            "tune_ids":      tune_ids,
        }

    except ValueError as e:
        return {"ok": False, "error": f"Validation failed: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def update_tune_history_post_apply(min_post_sigs: int = 30):
    """P1-10: For each tune_history row with status='APPLIED', measure post-apply WR.

    Reads closed signals from the live results table whose signal closed AFTER
    the applied_at timestamp. If >= min_post_sigs are available, computes WR and
    sets status to VERIFIED_BETTER or VERIFIED_WORSE relative to the test_wr at apply time.
    Called from load_performance_state() in crypto_alert.py.
    """
    try:
        _init_ae_tables()
        conn = _connect()
        pending = conn.execute(
            "SELECT id, applied_at, test_wr FROM tune_history WHERE status='APPLIED'"
        ).fetchall()
        if not pending:
            conn.close()
            return

        for row_id, applied_at, test_wr in pending:
            wins = conn.execute(
                """SELECT COUNT(*) FROM results r
                   JOIN signals s ON s.id = r.signal_id
                   WHERE r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2')
                     AND s.timestamp > ?""",
                (applied_at,)
            ).fetchone()[0] or 0
            total = conn.execute(
                """SELECT COUNT(*) FROM results r
                   JOIN signals s ON s.id = r.signal_id
                   WHERE r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
                     AND s.timestamp > ?""",
                (applied_at,)
            ).fetchone()[0] or 0
            if total < min_post_sigs:
                continue
            post_wr = round(wins / total * 100, 1) if total > 0 else 0.0
            # Verdict: compare to test_wr at apply time (fallback to 45% break-even)
            baseline  = test_wr if (test_wr is not None) else 45.0
            status    = "VERIFIED_BETTER" if post_wr >= baseline else "VERIFIED_WORSE"
            conn.execute(
                """UPDATE tune_history
                   SET post_apply_wr=?, post_apply_n=?, status=?,
                       notes=?
                   WHERE id=?""",
                (post_wr, total, status,
                 f"Post-apply WR {post_wr:.1f}% vs baseline {baseline:.1f}% (n={total}) -> {status}",
                 row_id)
            )
            conn.commit()
            print(f"[TUNE] tune_history#{row_id}: post-apply WR={post_wr:.1f}% "
                  f"(n={total}) -> {status}")
        conn.close()
    except Exception as e:
        print(f"[TUNE] update_tune_history_post_apply error: {e}")


def rollback_tune_adjustment(tune_history_id: int):
    """P1-9: Revert a Tune Bot application by restoring old_val to strategy_engine.py.

    Guards:
      - tune_history row must exist and not already be ROLLED_BACK
      - BACKTEST_CONFIG anchor present (isolation guarantee)
      - LIVE_CONFIG anchor present
      - Parameter appears exactly once in LIVE_CONFIG block
      - Backup created before any write — failure aborts write
    """
    try:
        _init_ae_tables()
        conn = _connect()
        row  = conn.execute(
            "SELECT param, old_val, new_val, status FROM tune_history WHERE id=?",
            (tune_history_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"ok": False, "error": f"tune_history id={tune_history_id} not found"}
        param, old_val, new_val, status = row
        if status == "ROLLED_BACK":
            return {"ok": False, "error": f"tune_history#{tune_history_id} already rolled back"}
        if param not in _TUNE_VALID_PARAMS:
            return {"ok": False, "error": f"Cannot rollback unknown param {param!r}"}

        # CONF_FLOOR_RAISE — rollback via scalar write
        if param == "CONF_FLOOR_RAISE":
            try:
                _save_scalar("conf_floor", int(old_val))
            except Exception as e:
                return {"ok": False, "error": f"conf_floor scalar rollback failed: {e}"}
            conn = _connect()
            conn.execute("UPDATE tune_history SET status='ROLLED_BACK' WHERE id=?", (tune_history_id,))
            conn.commit(); conn.close()
            return {"ok": True, "rolled_back": tune_history_id, "note": "conf_floor scalar restored"}

        field = _TUNE_FIELD_MAP.get(param)
        if not field and param != "SESSION_LIQUID_HOURS":
            return {"ok": False, "error": f"No regex mapping for param {param!r}"}

        cfg_path = CONFIG_PATH
        with open(cfg_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Verify both structural anchors are present (config.py now owns this state)
        split_idx = content.find(_BACKTEST_ANCHOR)
        if split_idx == -1:
            return {
                "ok":    False,
                "error": (
                    f"Cannot find {_BACKTEST_ANCHOR!r} in config.py. "
                    "Refusing to rollback — BACKTEST_CONFIG isolation cannot be guaranteed."
                ),
            }
        live_part  = content[:split_idx]
        after_part = content[split_idx:]

        live_anchor = live_part.find(_LIVE_ANCHOR)
        if live_anchor == -1:
            return {"ok": False, "error": f"Cannot find {_LIVE_ANCHOR!r} in config.py"}

        pre_live = live_part[:live_anchor]
        cfg_part = live_part[live_anchor:]

        # SESSION_LIQUID_HOURS rollback — restore old_val expression on _DEFAULT_LIQUID_HOURS
        if param == "SESSION_LIQUID_HOURS":
            lh_match = re.search(
                r'(_DEFAULT_LIQUID_HOURS\s*=\s*)(list\(range\(24\)\)|\[[^\]]*\])',
                live_part,
            )
            if not lh_match:
                return {"ok": False, "error": "_DEFAULT_LIQUID_HOURS not found in config.py for rollback"}
            new_live = live_part[:lh_match.start(2)] + old_val + live_part[lh_match.end(2):]
            if new_live == live_part:
                return {"ok": False, "error": "_DEFAULT_LIQUID_HOURS rollback substitution had no effect"}
            live_part = new_live
        else:
            env_name   = "LIVE_" + param
            literal_re = (
                rf'({re.escape(env_name)}\s*:\s*str\s*=\s*_env_choice\("{re.escape(env_name)}",\s*)'
                r'"(\w+)"'
            )
            matches = re.findall(literal_re, cfg_part)
            if len(matches) == 0:
                return {"ok": False, "error": f"Parameter '{env_name}' not found in LIVE_CONFIG block"}
            if len(matches) > 1:
                return {
                    "ok":    False,
                    "error": (
                        f"Parameter '{env_name}' found {len(matches)} times in LIVE_CONFIG block "
                        "(expected exactly 1). Refusing rollback."
                    ),
                }

            new_cfg  = re.sub(literal_re, rf'\1"{old_val}"', cfg_part, count=1)
            new_live = pre_live + new_cfg
            if new_live == live_part:
                return {"ok": False, "error": f"Regex found no match for '{env_name}' in LIVE_CONFIG"}
            live_part = new_live

        # Backup before writing — failure aborts the write
        backup = os.path.join(_ROOT, "backups",
                              f"config.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
        os.makedirs(os.path.join(_ROOT, "backups"), exist_ok=True)
        try:
            shutil.copy2(cfg_path, backup)
        except Exception as e:
            return {"ok": False, "error": f"Backup creation failed: {e}. File not modified."}

        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(live_part + after_part)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn    = _connect()
        conn.execute(
            "UPDATE tune_history SET status='ROLLED_BACK', backup_file=? WHERE id=?",
            (os.path.relpath(backup, _ROOT), tune_history_id)
        )
        conn.commit()
        conn.close()

        _cur_ver = int(_load_scalar("strategy_version", 1))
        _save_scalar("strategy_version", _cur_ver + 1)
        print(f"[TUNE] Rolled back tune_history#{tune_history_id} "
              f"({param}: {new_val}->{old_val}), strategy_version -> {_cur_ver + 1}")

        return {
            "ok":       True,
            "param":    param,
            "reverted": f"{new_val} -> {old_val}",
            "backup":   os.path.relpath(backup, _ROOT),
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


def manual_close_signal(signal_id, exit_price):
    """
    Manually close an open signal at a user-specified exit price.
    Calculates real P&L, classifies result, stamps close_reason='MANUAL'.
    Result tiers:
      WIN     — exit P&L >= tp1_pct  (reached or exceeded the TP1 target)
      PARTIAL — exit P&L > 0 but < tp1_pct  (profitable but early exit)
      LOSS    — exit P&L <= 0
    """
    try:
        conn = _connect()
        row  = conn.execute(
            "SELECT signal, entry_price, tp1_pct, status FROM signals WHERE id=?",
            (signal_id,)).fetchone()
        if not row:
            conn.close()
            return {"ok": False, "error": f"Signal #{signal_id} not found"}
        direction, entry, tp1_pct, status = row
        if status != "OPEN":
            conn.close()
            return {"ok": False, "error": f"Signal #{signal_id} is already {status}"}

        entry      = float(entry or 0)
        tp1_pct    = float(tp1_pct or 0)
        exit_price = float(exit_price)

        if entry <= 0 or exit_price <= 0:
            conn.close()
            return {"ok": False, "error": "Invalid entry or exit price"}

        # P&L from trade direction
        if direction == "BUY":
            pnl_pct = round((exit_price - entry) / entry * 100, 2)
        else:
            pnl_pct = round((entry - exit_price) / entry * 100, 2)

        # Result classification
        if pnl_pct >= tp1_pct:
            result = "WIN"
        elif pnl_pct > 0:
            result = "PARTIAL"
        else:
            result = "LOSS"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE signals SET status='CLOSED' WHERE id=?", (signal_id,))
        conn.execute("""UPDATE results SET
            result=?, profit_pct=?, closed_at=?, exit_price=?, close_reason='MANUAL'
            WHERE signal_id=?""", (result, pnl_pct, now, exit_price, signal_id))
        conn.commit()
        # Read feature scores before closing connection — needed for OGD update
        fs_row = conn.execute(
            "SELECT token, feature_scores_json FROM signals WHERE id=?",
            (signal_id,)).fetchone()
        conn.close()

        sign = "+" if pnl_pct >= 0 else ""
        print(f"[MANUAL CLOSE] #{signal_id} {direction} exit=${exit_price} "
              f"P&L:{sign}{pnl_pct}% -> {result}")

        # Trigger OGD weight update so manually closed trades feed adaptive learning.
        # T-MANUAL-PNL (2026-05-22): pass profit_pct=pnl_pct/100.0 (fraction) so the
        # gradient sees the realized P&L magnitude, matching the auto-close path at
        # crypto_alert.py:1196-1197. Previously the manual path passed only the
        # discrete WIN/LOSS label and lost the proportional reward signal.
        if _weight_engine is not None and fs_row and fs_row[1]:
            try:
                _pct = float(pnl_pct) / 100.0 if pnl_pct is not None else None
                _weight_engine.update(fs_row[0], result, json.loads(fs_row[1]), profit_pct=_pct)
            except Exception as e:
                print(f"[ADAPTIVE] manual_close OGD #{signal_id}: {e}")

        return {"ok": True, "result": result, "pnl_pct": pnl_pct, "direction": direction}
    except Exception as e:
        print(f"[DB ERROR] manual_close: {e}")
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────────────────
# HONEST METRICS — Sprint 3 + post-F-8 dashboard surface
# (Surfaces CPCV mean WR, honest DSR, monitoring.py alert,
#  cross-config sr_trial_std, macro filter status, bot
#  version, latest audit score, paper-trade progress.)
# ──────────────────────────────────────────────────────────

BOT_VERSION_TAG = "v13 ICT MODE"  # mirrors README.md current state

def _parse_honest_metrics_from_report(report_path: str) -> dict:
    """Extract HONEST METRICS section fields from a backtest report .txt.
    Returns None for any missing fields (e.g., older runs without the section)."""
    out = {"cpcv_wr_mean": None, "cpcv_wr_std": None, "cpcv_wr_q05": None,
           "overall_sharpe": None, "psr_oos": None, "dsr": None,
           "dsr_proxy_used": None, "verdict": None, "n_signals": None}
    try:
        if not os.path.exists(report_path):
            return out
        with open(report_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        return out
    import re as _re
    # Tolerant regex — match the printed lines in cpcv_text_report()
    def _m(pat, key, cast=float):
        m = _re.search(pat, text)
        if m:
            try:
                out[key] = cast(m.group(1))
            except Exception:
                pass
    _m(r"n_signals\s*=\s*(\d+)", "n_signals", int)
    _m(r"WR \(CPCV\)\s+mean=([\d\.]+)%", "cpcv_wr_mean")
    _m(r"std=([\d\.]+)%", "cpcv_wr_std")
    _m(r"q05=([\d\.]+)%", "cpcv_wr_q05")
    _m(r"Overall Sharpe\s*=\s*([\-\d\.]+)", "overall_sharpe")
    _m(r"PSR \(OOS CPCV\)\s*=\s*([\d\.]+)%", "psr_oos")
    _m(r"DSR \(multi-test\)\s*=\s*([\d\.]+)%", "dsr")
    if "ANTI-CONSERVATIVE" in text or "within-run fold-Sharpe std as proxy" in text:
        out["dsr_proxy_used"] = True
    elif out["dsr"] is not None:
        out["dsr_proxy_used"] = False
    vm = _re.search(r"VERDICT:\s*(\w+)", text)
    if vm:
        out["verdict"] = vm.group(1)
    return out


def _latest_audit_score() -> dict:
    """Pull latest overall score + date from .claude/reports/tradeai-audit/*.md."""
    out = {"score": None, "date": None, "path": None}
    try:
        audit_dir = os.path.join(_ROOT, ".claude", "reports", "tradeai-audit")
        if not os.path.isdir(audit_dir):
            return out
        files = sorted([f for f in os.listdir(audit_dir) if f.endswith(".md")])
        if not files:
            return out
        latest = files[-1]
        path = os.path.join(audit_dir, latest)
        out["path"] = latest
        out["date"] = latest.split(".")[0]
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read(8192)  # only need the top section
        import re as _re
        # Find the "Overall" scorecard row, then take the LAST score
        # mentioned on that line (rightmost = most recent column).
        for line in text.splitlines():
            if "Overall" not in line:
                continue
            matches = _re.findall(r"(\d+\.\d+)\s*/\s*10", line)
            if matches:
                out["score"] = float(matches[-1])
                break
    except Exception:
        pass
    return out


def _macro_filter_status() -> dict:
    """Read macro filter flags from config.py directly."""
    out = {"enabled": None, "advisory_only": None}
    try:
        import config as _cfg
        out["enabled"] = bool(getattr(_cfg, "MACRO_FILTER_ENABLED", False))
        out["advisory_only"] = bool(getattr(_cfg, "MACRO_ADVISORY_ONLY", True))
    except Exception:
        pass
    return out


def get_explorer_status() -> dict:
    """Read explorer session.json + PID liveness + summary counts."""
    out = {
        "ok":            False,
        "state":         "NO_SESSION",
        "session":       None,
        "pid_alive":     False,
        "explorer_db":   False,
    }
    sess_path = os.path.join(_ROOT, "data", "explorer_session.json")
    pid_path  = os.path.join(_ROOT, "data", "explorer.pid")
    learn_db  = os.path.join(_ROOT, "data", "explorer_learning.db")
    out["explorer_db"] = os.path.exists(learn_db)
    try:
        with open(sess_path, "r", encoding="utf-8") as f:
            out["session"] = json.load(f)
            out["ok"] = True
    except FileNotFoundError:
        return out
    except Exception as e:
        out["error"] = str(e); return out
    # PID liveness
    try:
        with open(pid_path) as f:
            pid = int(f.read().strip())
        if sys.platform == "win32":
            try:
                import ctypes
                h = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                if h:
                    out["pid_alive"] = True
                    ctypes.windll.kernel32.CloseHandle(h)
            except Exception:
                pass
        else:
            try: os.kill(pid, 0); out["pid_alive"] = True
            except OSError: pass
    except Exception:
        pass
    if out["pid_alive"]:
        out["state"] = "RUNNING"
    elif (out["session"] or {}).get("pause_reason"):
        out["state"] = "PAUSED"
    elif (out["session"] or {}).get("ended_at"):
        out["state"] = "FINISHED"
    else:
        out["state"] = "UNKNOWN"
    return out


def get_explorer_pareto() -> dict:
    path = os.path.join(_ROOT, "data", "pareto_archive.json")
    try:
        with open(path) as f:
            return {"ok": True, "archive": json.load(f)}
    except FileNotFoundError:
        return {"ok": True, "archive": []}
    except Exception as e:
        return {"ok": False, "error": str(e), "archive": []}


def get_explorer_promotions() -> dict:
    path = os.path.join(_ROOT, "data", "promotion_log.json")
    try:
        with open(path) as f:
            log = json.load(f)
        return {"ok": True, "promotions": log[-20:]}
    except FileNotFoundError:
        return {"ok": True, "promotions": []}
    except Exception as e:
        return {"ok": False, "error": str(e), "promotions": []}


def get_explorer_trials(limit: int = 50) -> dict:
    learn_db = os.path.join(_ROOT, "data", "explorer_learning.db")
    if not os.path.exists(learn_db):
        return {"ok": True, "trials": [], "totals": {}}
    try:
        con = sqlite3.connect(f"file:{learn_db}?mode=ro", uri=True)
        rows = con.execute(
            """SELECT trial_id, study_name, optuna_trial_no, started_at,
                      walltime_s, n, wr, cpcv_mean, cpcv_std, cpcv_q05,
                      sharpe, dsr, dsr_proxy_used, verdict, reject_reason
               FROM trials ORDER BY trial_id DESC LIMIT ?""", (limit,)
        ).fetchall()
        totals = {}
        for v in ("PASS", "FAIL", "ERROR"):
            totals[v] = con.execute(
                "SELECT COUNT(*) FROM trials WHERE verdict=?", (v,)
            ).fetchone()[0]
        n_studies = con.execute(
            "SELECT COUNT(DISTINCT study_name) FROM trials"
        ).fetchone()[0]
        con.close()
        cols = ["trial_id", "study_name", "optuna_trial_no", "started_at",
                "walltime_s", "n", "wr", "cpcv_mean", "cpcv_std", "cpcv_q05",
                "sharpe", "dsr", "dsr_proxy_used", "verdict", "reject_reason"]
        trials = [dict(zip(cols, r)) for r in rows]
        return {"ok": True, "trials": trials,
                "totals": totals, "n_studies": n_studies}
    except Exception as e:
        return {"ok": False, "error": str(e), "trials": []}


def get_baseline_pin() -> dict:
    """Return canonical baseline + match status against the latest DB run.

    Source of truth: data/baseline_pin.json. Edit that file when a new
    baseline is promoted so the dashboard shows the right reference.
    """
    pin_path = os.path.join(_ROOT, "data", "baseline_pin.json")
    pin = {}
    try:
        with open(pin_path, "r", encoding="utf-8") as f:
            pin = json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"pin file unreadable: {e}"}

    expected_run = int(pin.get("run_id") or 0)
    expected_hash = pin.get("config_hash") or ""
    expected = pin.get("expected") or {}

    latest = {"id": None, "n": None, "wr": None, "hash": None, "date": None}
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT id, total_signals, overall_wr, config_hash, run_date "
            "FROM backtest_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            latest = {"id": row[0], "n": row[1], "wr": row[2],
                      "hash": row[3], "date": row[4]}
        conn.close()
    except Exception:
        pass

    match_id   = (latest["id"]   == expected_run)
    match_hash = (latest["hash"] == expected_hash) if expected_hash else None
    match_wr   = (latest["wr"] is not None and abs(latest["wr"] - (expected.get("wr_pct") or 0)) < 0.1)

    if match_id and (match_hash is None or match_hash):
        status = "ok"
        message = f"Latest backtest is the pinned baseline (Run-{expected_run})."
    elif match_hash:
        status = "ok"
        message = f"Latest is Run-{latest['id']} but matches the pinned config_hash — same as baseline."
    elif latest["id"] and latest["id"] > expected_run:
        status = "drift"
        message = f"Latest is Run-{latest['id']} (newer than pinned Run-{expected_run}). Verify it is intended."
    else:
        status = "mismatch"
        message = f"Latest is Run-{latest['id']} (does NOT match pinned Run-{expected_run})."

    return {
        "ok":        True,
        "status":    status,
        "message":   message,
        "pin":       pin,
        "latest":    latest,
        "matches":   {"id": match_id, "hash": match_hash, "wr": match_wr},
    }


def _paper_progress() -> dict:
    """Closed paper signals toward LIVE-clearance target N≥30.

    ETA is adaptive: prefers measured live fire-rate over the last 30 days;
    falls back to the most recent backtest's signals-per-day (Run-168 = 43/365d).
    """
    target = 30
    closed = 0
    rate_per_month = None
    rate_source = "default"
    try:
        conn = _connect()
        # C-1 fix (tracker audit 2026-05-26 cycle-6): crypto_alert.py:687
        # writes an `INSERT INTO results (signal_id) VALUES (?)` row with
        # `result='OPEN'` at signal-fire time. The previous EXISTS clause
        # therefore matched every OPEN signal as "closed", inflating the
        # LIVE-clearance `closed/30` countdown the moment any signal fires.
        # The correct closed-set predicate mirrors what _canonical_wr uses
        # everywhere else in this file: result in the terminal outcomes.
        row = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE status='CLOSED' OR EXISTS ("
            "  SELECT 1 FROM results r WHERE r.signal_id=signals.id "
            "    AND r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')"
            ")"
        ).fetchone()
        if row and row[0]:
            closed = int(row[0])

        live_30d = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE timestamp >= datetime('now','-30 days')"
        ).fetchone()
        live_30d_count = int(live_30d[0]) if live_30d and live_30d[0] else 0

        if live_30d_count >= 5:
            rate_per_month = float(live_30d_count)
            rate_source = "live_30d"
        else:
            bt = conn.execute(
                "SELECT total_signals, days FROM backtest_runs "
                "WHERE status='DONE' AND total_signals IS NOT NULL "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if bt and bt[0] and bt[1]:
                rate_per_month = round(bt[0] * 30.0 / bt[1], 2)
                rate_source = f"backtest_run_latest"
        conn.close()
    except Exception:
        pass

    if not rate_per_month or rate_per_month <= 0:
        rate_per_month = 4.0
        rate_source = "fallback_default"

    pct = round(min(100.0, closed / target * 100), 1) if target > 0 else 0
    remaining = max(0, target - closed)
    eta_months = round(remaining / rate_per_month, 1)
    return {
        "closed":         closed,
        "target":         target,
        "pct":            pct,
        "eta_months":     eta_months,
        "rate_per_month": round(rate_per_month, 2),
        "rate_source":    rate_source,
        "remaining":      remaining,
    }


def _ogd_health_snapshot() -> dict:
    """Call monitoring.generate_report() in-process. Read-only on signals.db.

    2026-05-27: also surfaces `tokens_alt_pool` (the bootstrap pool count)
    so the Honest Metrics tab can show "live=1 / bootstrap=10" — making it
    clear that a sparse live pool is the expected pre-paper state, not a
    real health alert.
    """
    out = {"global_alert": "UNKNOWN", "tokens": 0, "tokens_alt_pool": 0,
           "alt_pool_table": None, "degenerate": 0,
           "low_entropy": 0, "pinned": 0, "stale": 0,
           "cross_token_l1": None, "homogeneity_alert": None, "error": None}
    try:
        import monitoring
        report = monitoring.generate_report(DB_PATH)
        s = report.get("summary", {})
        ct = report.get("cross_token", {})
        out["global_alert"]      = s.get("global_alert_level", "UNKNOWN")
        out["tokens"]            = s.get("tokens_monitored", 0)
        out["tokens_alt_pool"]   = s.get("tokens_alt_pool", 0)
        out["alt_pool_table"]    = s.get("alt_pool_table")
        out["degenerate"]        = s.get("tokens_degenerate", 0)
        out["low_entropy"]       = s.get("tokens_low_entropy", 0)
        out["pinned"]            = s.get("tokens_pinned", 0)
        out["stale"]             = s.get("tokens_stale", 0)
        out["cross_token_l1"]    = ct.get("avg_pairwise_l1", None)
        out["homogeneity_alert"] = ct.get("homogeneity_alert", None)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _cross_config_sr_trial_std() -> dict:
    """Read the persisted honest sr_trial_std blob (FIX 1 Part 2)."""
    out = {"value": None, "n_configs": None, "computed_at": None,
           "mean_oos_sharpe": None, "note": None}
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key='cross_config_sr_trial_std'"
        ).fetchone()
        conn.close()
        if row and row[0]:
            blob = json.loads(row[0])
            out["value"]           = blob.get("value")
            out["n_configs"]       = blob.get("n_configs")
            out["computed_at"]     = blob.get("computed_at")
            out["mean_oos_sharpe"] = blob.get("mean_oos_sharpe")
            out["note"]            = "honest cross-config (Bailey/LdP 2014); bypasses within-fold proxy"
    except Exception:
        pass
    return out


def get_honest_metrics() -> dict:
    """One-shot snapshot for the dashboard's Honest Metrics tab.

    Aggregates everything Sprint 3 + FIX 1 Parts 1+2 ship to make visible:
      - Latest backtest run's CPCV mean WR / DSR / verdict
      - OGD health via monitoring.py (in-process call)
      - Cross-config sr_trial_std (honest, post-FIX-1-part-2)
      - Macro filter config flag state
      - Bot version tag
      - Latest audit score + date
      - Paper trading progress toward N≥30 LIVE-clearance gate
    """
    # 1. Latest backtest summary fields + parse the report file for HONEST METRICS
    # CRT v1 (2026-05-27): also fetch per-source signal counts so the frontend
    # can show a "blend warning" banner — CPCV/DSR currently average across
    # 5M_SWEEP + H4_CRT signals invisibly, which misleads the LIVE-clearance
    # judgement when one scanner is silently dragging the other down.
    latest_run = {"id": None, "date": None, "n": None, "wr": None, "report": None,
                  "n_5m_sweep": 0, "n_h4_crt": 0, "blended": False}
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT id, run_date, total_signals, overall_wr "
            "FROM backtest_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            latest_run["id"]   = row[0]
            latest_run["date"] = row[1]
            latest_run["n"]    = row[2]
            latest_run["wr"]   = row[3]
            # Per-source split from backtest_signals
            try:
                src_rows = conn.execute(
                    "SELECT source, COUNT(*) FROM backtest_signals "
                    "WHERE run_id = ? GROUP BY source", (row[0],)
                ).fetchall()
                _counts = {r[0] or "5M_SWEEP": r[1] for r in src_rows}
                latest_run["n_5m_sweep"] = _counts.get("5M_SWEEP", 0)
                latest_run["n_h4_crt"]   = _counts.get("H4_CRT", 0)
                latest_run["blended"]    = (latest_run["n_5m_sweep"] > 0
                                            and latest_run["n_h4_crt"] > 0)
            except Exception:
                pass
        conn.close()
    except Exception:
        pass

    # Find the matching backtest_reports/RunNN_*.txt
    # M-1 fix (tracker audit cycle-7 2026-05-26): fallback dict must mirror
    # the FULL schema returned by `_parse_honest_metrics_from_report()` (9
    # keys). Previously only 3 keys were set; frontend `toFixed()` on the
    # missing 6 keys threw `undefined.toFixed is not a function` and crashed
    # the whole Honest Metrics tab on a fresh install (no backtest_runs row).
    honest = {"cpcv_wr_mean": None, "cpcv_wr_std": None, "cpcv_wr_q05": None,
              "overall_sharpe": None, "psr_oos": None, "dsr": None,
              "dsr_proxy_used": None, "verdict": None, "n_signals": None}
    if latest_run["id"] is not None:
        try:
            rpt_dir = os.path.join(_ROOT, "backtest_reports")
            if os.path.isdir(rpt_dir):
                prefix = f"Run{latest_run['id']}_"
                matches = [f for f in os.listdir(rpt_dir) if f.startswith(prefix)]
                if matches:
                    latest_run["report"] = sorted(matches)[-1]
                    honest = _parse_honest_metrics_from_report(
                        os.path.join(rpt_dir, latest_run["report"])
                    )
        except Exception:
            pass

    # C-3 fix (tracker audit 2026-05-26 cycle-6): surface the real execution
    # mode so the Honest Metrics tab can stop hardcoding "PAPER mode". Prefer
    # heartbeat.json (authoritative — written by the running bot each cycle)
    # and fall back to the env var, then to "UNKNOWN" if neither is available.
    execution_mode = "UNKNOWN"
    try:
        hb_path = os.path.join(_ROOT, "data", "heartbeat.json")
        if os.path.isfile(hb_path):
            with open(hb_path, "r") as _hb_fh:
                _hb = json.load(_hb_fh)
            _mode = _hb.get("execution_mode")
            if isinstance(_mode, str) and _mode:
                execution_mode = _mode.upper()
    except Exception:
        pass
    if execution_mode == "UNKNOWN":
        _env_mode = os.environ.get("EXECUTION_MODE", "").strip()
        if _env_mode:
            execution_mode = _env_mode.upper()

    return {
        "ok": True,
        "bot_version":       BOT_VERSION_TAG,
        "execution_mode":    execution_mode,
        "latest_run":        latest_run,
        "honest_metrics":    honest,
        "ogd_health":        _ogd_health_snapshot(),
        "cross_config_std":  _cross_config_sr_trial_std(),
        "macro_filter":      _macro_filter_status(),
        "audit":             _latest_audit_score(),
        "paper_progress":    _paper_progress(),
    }


def _run_backtest_bg():
    with _bt_lock:
        BACKTEST_STATUS.update({"status":"RUNNING","started":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "message":"Starting backtest...","progress":5})
    try:
        bt_dir = os.path.dirname(os.path.abspath(__file__))
        bt_script = os.path.join(bt_dir, "backtest.py")
        proc = subprocess.Popen([sys.executable, bt_script, "--fresh"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            cwd=bt_dir)
        tok_done = 0
        all_lines = []
        for line in proc.stdout:
            line = line.strip()
            if not line: continue
            all_lines.append(line)
            with _bt_lock:
                BACKTEST_STATUS["message"] = line
                if "Fetching" in line:
                    tok_done += 1
                    BACKTEST_STATUS["progress"] = min(10 + int(tok_done / 7 * 70), 80)
                elif "Simulating" in line:
                    BACKTEST_STATUS["progress"] = min(BACKTEST_STATUS["progress"] + 3, 85)
                elif "[DB] Run #" in line:
                    BACKTEST_STATUS["progress"] = 95
        proc.wait()
        if proc.returncode == 0:
            with _bt_lock:
                BACKTEST_STATUS.update({"status":"DONE","message":"Backtest complete — results saved","progress":100,"error_log":""})
        else:
            error_tail = " | ".join(all_lines[-5:]) if all_lines else "No output captured"
            with _bt_lock:
                BACKTEST_STATUS.update({"status":"FAILED","message":f"Error: {error_tail}","error_log":"\n".join(all_lines)})
    except Exception as e:
        with _bt_lock:
            BACKTEST_STATUS.update({"status":"FAILED","message":str(e)})

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        if self.path == "/api/signals":
            rows = query_db("""
                SELECT s.*,
                       r.tp1_hit, r.tp2_hit, r.tp3_hit, r.sl_hit,
                       r.result  AS outcome,
                       r.profit_pct, r.closed_at
                FROM   signals s
                LEFT JOIN results r ON r.signal_id = s.id
                ORDER  BY s.timestamp DESC
                LIMIT  500
            """)
            self.send_json(rows)
        elif self.path == "/api/stats":
            self.send_json(get_stats())
        elif self.path == "/api/open":
            rows = query_db("""
                SELECT s.*,
                       r.tp1_hit, r.tp2_hit, r.tp3_hit, r.sl_hit,
                       r.result  AS outcome,
                       r.profit_pct
                FROM   signals s
                LEFT JOIN results r ON r.signal_id = s.id
                WHERE  s.status = 'OPEN'
                ORDER  BY s.timestamp DESC
            """)
            self.send_json(rows)
        elif self.path == "/api/intelligence":
            self.send_json(get_intelligence())
        elif self.path == "/api/hour-day-heatmap":
            # C2 (2026-05-22 tracker audit): WR by hour-of-day × day-of-week
            self.send_json(get_hour_day_heatmap())
        elif self.path == "/api/ogd-weight-history":
            # C3 (2026-05-22 tracker audit): trajectory data for sparklines
            self.send_json(get_ogd_weight_history())
        elif self.path == "/api/rolling-wf" or self.path.startswith("/api/rolling-wf?"):
            # C6 (2026-05-22 tracker audit): rolling walk-forward per-fold WR
            _rid = None
            if "?" in self.path:
                try:
                    from urllib.parse import urlparse, parse_qs
                    _qs = parse_qs(urlparse(self.path).query)
                    if "run_id" in _qs: _rid = int(_qs["run_id"][0])
                except Exception:
                    _rid = None
            self.send_json(get_rolling_wf(run_id=_rid))
        elif self.path == "/api/equity-curve" or self.path.startswith("/api/equity-curve?"):
            # C1 (2026-05-22 tracker audit): cumulative P&L for the Open Positions chart.
            # Optional ?days=N query (default 90, clamped 7..365).
            _days = 90
            if "?" in self.path:
                try:
                    from urllib.parse import urlparse, parse_qs
                    _qs = parse_qs(urlparse(self.path).query)
                    _days = max(7, min(365, int(_qs.get("days", ["90"])[0])))
                except Exception:
                    _days = 90
            self.send_json(get_equity_curve(limit_days=_days))
        elif self.path == "/api/backtest/status":
            with _bt_lock:
                self.send_json(dict(BACKTEST_STATUS))
        elif self.path == "/api/backtest/results":
            self.send_json(get_backtest_results())
        elif self.path == "/api/backtest/history":
            self.send_json(get_backtest_history())
        elif self.path == "/api/backtest/tune-preview":
            self.send_json(calculate_tune_preview())
        elif self.path == "/api/tune/status":
            self.send_json(tune_status())
        elif self.path == "/api/health":
            ok = os.path.exists(DB_PATH)
            self.send_json({"db_exists": ok, "db_path": DB_PATH,
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        elif self.path == "/api/adaptive/summary":
            self.send_json(get_adaptive_summary())
        elif self.path == "/api/adaptive/forensic" or self.path.startswith("/api/adaptive/forensic?"):
            # R10 forensic panel (master audit 2026-05-26)
            self.send_json(get_adaptive_forensic())
        elif self.path == "/api/adaptive/health":
            self.send_json(get_adaptive_health())
        elif self.path == "/api/honest-metrics":
            data = get_honest_metrics()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache"); self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        elif self.path == "/api/quantstats" or self.path.startswith("/api/quantstats?"):
            src, rid = "paper", None
            if "?" in self.path:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                src = (q.get("source", ["paper"])[0]).lower()
                try: rid = int(q.get("run_id", ["0"])[0]) or None
                except Exception: rid = None
            try:
                import quantstats_report as _qr
                self.send_json(_qr.get_summary(src, rid))
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})

        elif self.path == "/api/quantstats/tearsheet" or self.path.startswith("/api/quantstats/tearsheet?"):
            src, rid = "paper", None
            if "?" in self.path:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                src = (q.get("source", ["paper"])[0]).lower()
                try: rid = int(q.get("run_id", ["0"])[0]) or None
                except Exception: rid = None
            try:
                import quantstats_report as _qr
                html = _qr.get_tearsheet_html(src, rid)
                if html is None:
                    self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
                    self.wfile.write(b"<html><body style='font-family:sans-serif;padding:40px'><h2>No data yet</h2><p>QuantStats tearsheet requires at least 2 closed signals. Once trades close, this page will render the full report.</p></body></html>")
                    return
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache"); self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                self.send_response(500); self.send_header("Content-Type", "text/html"); self.end_headers()
                self.wfile.write(f"<html><body><h2>Tearsheet error</h2><pre>{e}</pre></body></html>".encode())

        elif self.path == "/api/backtest/tune-history":
            self.send_json(get_tune_history())
        elif self.path == "/api/baseline-pin":
            self.send_json(get_baseline_pin())
        elif self.path == "/api/explorer/status":
            self.send_json(get_explorer_status())
        elif self.path == "/api/explorer/pareto":
            self.send_json(get_explorer_pareto())
        elif self.path == "/api/explorer/promotions":
            self.send_json(get_explorer_promotions())
        elif self.path == "/api/explorer/trials" or self.path.startswith("/api/explorer/trials?"):
            _n = 50
            if "?" in self.path:
                try:
                    from urllib.parse import urlparse, parse_qs
                    _q = parse_qs(urlparse(self.path).query)
                    _n = max(1, min(500, int(_q.get("limit", ["50"])[0])))
                except Exception:
                    pass
            self.send_json(get_explorer_trials(limit=_n))
        elif self.path == "/":
            self.send_html()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == "/api/backtest/run":
            with _bt_lock:
                if BACKTEST_STATUS["status"] == "RUNNING":
                    self.send_json({"ok":False,"error":"Backtest already running"}); return
            t = threading.Thread(target=_run_backtest_bg, daemon=True)
            t.start()
            self.send_json({"ok":True,"message":"Backtest started"})
        elif self.path == "/api/backtest/tune-apply":
            length = int(self.headers.get("Content-Length",0))
            body   = json.loads(self.rfile.read(length)) if length else {}
            self.send_json(apply_tune_adjustments(
                body.get("adjustments", []),
                run_id   = body.get("run_id"),
                train_wr = body.get("train_wr"),
                test_wr  = body.get("test_wr"),
            ))
        elif self.path == "/api/backtest/tune-rollback":
            length = int(self.headers.get("Content-Length",0))
            body   = json.loads(self.rfile.read(length)) if length else {}
            tid    = body.get("tune_history_id")
            if not tid:
                self.send_json({"ok": False, "error": "tune_history_id required"})
            else:
                self.send_json(rollback_tune_adjustment(int(tid)))
        elif self.path == "/api/close_position":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length)) if length else {}
            sig_id     = body.get("signal_id")
            exit_price = body.get("exit_price")
            if sig_id is None or exit_price is None:
                self.send_json({"ok": False, "error": "signal_id and exit_price required"})
                return
            try:
                exit_price = float(exit_price)
                if exit_price <= 0:
                    raise ValueError("exit_price must be positive")
            except (TypeError, ValueError) as e:
                self.send_json({"ok": False, "error": str(e)}); return
            self.send_json(manual_close_signal(int(sig_id), exit_price))
        else:
            self.send_response(404); self.end_headers()

    def send_json(self, data):
        try:
            body = json.dumps(data, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected before response completed

    def send_html(self):
        try:
            html = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            self.wfile.write(html)
        except (BrokenPipeError, ConnectionResetError):
            pass

from tracker_html import HTML

if __name__=="__main__":
    os.makedirs(os.path.join(_ROOT, "data"), exist_ok=True)
    if not os.path.exists(DB_PATH):
        print("[WARNING] data/signals.db not found — run crypto_alert.py first")
    init_backtest_db()
    server = ThreadedHTTPServer(("localhost", PORT), Handler)
    print(f"TradeAI Tracker  ->  http://localhost:{PORT}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTracker stopped.")
