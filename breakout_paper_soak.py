"""
breakout_paper_soak.py — Phase C-Breakout Step 2B.

A SEPARATE-PROCESS paper soak for the breakout thesis. Runs entirely
independently of the fade soak in /home/tradeai/TradeAI/.

Isolation invariants (verified at startup; refuses to start if any fail):
  - Binds its own PID file at data/breakout_soak.pid
  - Writes signals + results ONLY to data/breakout.db (never signals.db)
  - Has its own heartbeat file (data/breakout_soak_heartbeat.json)
  - Has its own log (logs/breakout_soak.log)
  - Does NOT import crypto_alert.py, backtest.py, adaptive_engine.py
  - Does NOT touch token_weights or bot_state in either DB

Detection contract (locked at Config 14 — pre-registered, do not tune mid-soak):
  ENABLE breakout: detect_h4_breakout from breakout_engine
  H4_BREAKOUT_CLOSE_BUFFER_PCT = 0.001
  BREAKOUT_TP1_RR              = 2.0
  BREAKOUT_TP2_RR              = 3.0
  BREAKOUT_TP3_RR              = 4.0
  H4_BREAKOUT_C2_LOOKBACK      = 4
  H4_BREAKOUT_MSS_HORIZON      = 30
  Wyckoff filter, funding overlay, BTC-corr overlay, OGD: ALL OFF.
  ICT_MIN_RR_GATE, MIN_SL_PCT, MAX_SL_PCT: inherited from config.py
                                            (1.3 / 0.5% / 3.0%).

Scan cycle (every CHECK_INTERVAL = 120 seconds):
  1. For each token: fetch latest OHLCV from Binance REST (5m + 4h)
  2. Run detect_h4_breakout — emit signal if any
  3. Resolve OPEN signals — check if TP1/TP2/TP3/SL hit since open
  4. Write heartbeat

Outcome resolution: signals stay OPEN until either:
  - TP1/TP2/TP3 or SL hits (based on current bars vs SL/TP levels)
  - 48h have elapsed from entry (EXPIRED)

Restart-safe: on restart, the `consumed_h4_crt`-style mitigation set is
rebuilt from the OPEN+CLOSED signals already in breakout.db so we don't
re-fire the same C1 zone after a process restart.

To start (detached, survives SSH disconnect):
  cd /home/tradeai/breakout-work
  nohup python3 breakout_paper_soak.py > logs/breakout_soak.log 2>&1 &
  echo $! > data/breakout_soak.pid

To stop gracefully:
  kill -TERM "$(cat data/breakout_soak.pid)"
"""
from __future__ import annotations

import bisect
import json
import os
import signal as signal_module
import sqlite3
import sys
import time as _time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ── Path setup (no live DB imports) ─────────────────────────────────────────
_BREAKOUT_DIR = Path(__file__).resolve().parent
_TRADEAI_DIR  = Path("/home/tradeai/TradeAI")
sys.path.insert(0, str(_BREAKOUT_DIR))
sys.path.insert(0, str(_TRADEAI_DIR))

# Lock Config 14 BEFORE importing breakout_engine
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
from breakout_engine import (  # noqa: E402
    detect_h4_breakout, compute_breakout_sl_tp,
    H4_BREAKOUT_C2_LOOKBACK,
)
from crt_engine import compute_crt_trade_economics  # noqa: E402
from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────
TOKENS = ["BTC", "ETH", "XRP", "HBAR", "AVAX", "LINK", "BNB",
          "ADA", "POL", "TON", "ATOM", "BCH"]
SYMBOL_MAP = {t: f"{t}USDT" for t in TOKENS}

BINANCE_BASE = "https://api.binance.com/api/v3/klines"
USER_AGENT   = "TradeAI-BreakoutSoak/1.0"

CHECK_INTERVAL_SEC = 120      # 2-minute scan cadence
FORWARD_BARS_5M    = 576      # 48h expiry window
OHLCV_5M_LIMIT     = 500      # fetch 500 5m bars (~41h)
OHLCV_4H_LIMIT     = 300      # fetch 300 4h bars (~50d)

DB_PATH       = _BREAKOUT_DIR / "data" / "breakout.db"
PID_PATH      = _BREAKOUT_DIR / "data" / "breakout_soak.pid"
HEARTBEAT_PATH = _BREAKOUT_DIR / "data" / "breakout_soak_heartbeat.json"
LOG_DIR       = _BREAKOUT_DIR / "logs"

# Soak label used to mark signals/results in DB
SOAK_LABEL = "H4_BREAKOUT_PAPER_SOAK"


# ── Signal handling for graceful shutdown ──────────────────────────────────
_RUNNING = True


def _sigterm_handler(signum, frame):
    global _RUNNING
    _log(f"Received signal {signum} — finishing current cycle and exiting.")
    _RUNNING = False


# ── Logging ────────────────────────────────────────────────────────────────
def _log(msg: str):
    """Stdout + flush (caller redirects to log file with nohup)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── Binance fetcher ────────────────────────────────────────────────────────
def fetch_klines(symbol: str, interval: str, limit: int) -> Optional[dict]:
    """Fetch klines from Binance REST and convert to the canonical dict shape.

    Returns:
        {"opens": [...], "highs": [...], "lows": [...], "closes": [...],
         "times": [...]}  with the most recent CLOSED bar last, OR None on
        error.

    Honors a small retry budget on transient failure.
    """
    url = f"{BINANCE_BASE}?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    _log(f"  [{symbol} {interval}] HTTP {resp.status}, retrying")
                    _time.sleep(2 * (attempt + 1))
                    continue
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            _log(f"  [{symbol} {interval}] fetch error: {e!r}, retrying")
            _time.sleep(2 * (attempt + 1))
            continue

        if not raw or not isinstance(raw, list):
            return None

        # Each kline is [open_time, open, high, low, close, vol, close_time, ...]
        # The LAST kline may still be forming; we drop it so all bars are CLOSED.
        opens, highs, lows, closes, times = [], [], [], [], []
        for row in raw[:-1]:
            opens.append(float(row[1]))
            highs.append(float(row[2]))
            lows.append(float(row[3]))
            closes.append(float(row[4]))
            times.append(int(row[0]))
        return {"opens": opens, "highs": highs, "lows": lows,
                "closes": closes, "times": times}
    return None


# ── DB helpers ─────────────────────────────────────────────────────────────
def open_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def load_consumed_set(conn) -> set:
    """Rebuild the (c1_time, c1_high, c1_low) one-shot set from prior signals.

    Restart-safe: we never re-fire a signal on a C1 zone we've already used.
    The key is encoded in `entry_type` field as 'H4_BREAKOUT_<conf>_<c1_key>'
    OR we look at sweep_type + tp/sl as proxy. For simplicity we'll persist
    the c1 key in the `feature_scores_json` column (we never use it for OGD).
    """
    consumed = set()
    rows = conn.execute(
        "SELECT feature_scores_json FROM signals WHERE source = ?",
        (SOAK_LABEL,),
    ).fetchall()
    for row in rows:
        blob = row[0]
        if not blob:
            continue
        try:
            d = json.loads(blob)
            key = d.get("c1_zone_key")
            if key and isinstance(key, list) and len(key) == 3:
                consumed.add((key[0], key[1], key[2]))
        except (json.JSONDecodeError, KeyError):
            continue
    return consumed


def persist_signal(conn, token: str, setup: dict, entry_price: float,
                    sl_price: float, tp1: float, tp2: float, tp3: float,
                    econ: dict, signal_ts: datetime) -> int:
    """Insert into signals + return new signal id."""
    cur = conn.cursor()
    direction = setup["direction"]
    expires_ts = (signal_ts + timedelta(minutes=FORWARD_BARS_5M * 5)).strftime("%Y-%m-%d %H:%M:%S")
    ts_str = signal_ts.strftime("%Y-%m-%d %H:%M:%S")
    h = signal_ts.hour
    if 13 <= h < 17:
        session = "NY_AM_KZ"
    elif 2 <= h < 6:
        session = "LONDON_KZ"
    elif 20 <= h < 24:
        session = "ASIA_KZ"
    elif 0 <= h < 6:
        session = "ASIA_EARLY"
    else:
        session = "OVERNIGHT"

    confluence_type = setup["confluence"]["type"]
    fvg_q = (setup["confluence"]["details"].get("quality", "NONE")
             if confluence_type == "FVG" else "NONE")
    mss_q = setup.get("mss_quality", "NONE")

    # Encode the c1 zone key inside feature_scores_json for restart-safety.
    # Convert tuple to list so JSON can serialize it.
    feat_blob = json.dumps({
        "c1_zone_key": list(setup["key"]),
        "config":      "config_14",
    })

    cur.execute(
        "INSERT INTO signals (token, signal, entry_price, sl, tp1, tp2, tp3, "
        " sl_pct, tp1_pct, tp2_pct, tp3_pct, rr1, rr2, rr3, "
        " confidence, timestamp, status, expires_at, "
        " sweep_type, session, mss_quality, fvg_quality, entry_type, "
        " hour_utc, day_of_week, source, feature_scores_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, "
        "        ?, ?, ?, ?, ?, ?, ?, "
        "        ?, ?, ?, ?, "
        "        ?, ?, ?, ?, ?, "
        "        ?, ?, ?, ?)",
        (token, direction, round(entry_price, 6),
         round(sl_price, 6), round(tp1, 6), round(tp2, 6), round(tp3, 6),
         round(econ["gross_sl"], 3), round(econ["gross_tp1"], 3),
         round(econ["gross_tp2"], 3), round(econ["gross_tp3"], 3),
         econ["rr1"],
         round(econ["gross_tp2"] / abs(econ["gross_sl"]), 2) if econ["gross_sl"] else 0,
         round(econ["gross_tp3"] / abs(econ["gross_sl"]), 2) if econ["gross_sl"] else 0,
         6 + (2 if confluence_type == "OB" else 1),
         ts_str, "OPEN", expires_ts,
         setup["type"], session, mss_q, fvg_q,
         f"H4_BREAKOUT_{confluence_type}",
         h, signal_ts.weekday(), SOAK_LABEL, feat_blob),
    )
    conn.commit()
    return cur.lastrowid


def resolve_open_signals(conn) -> int:
    """Check all OPEN soak signals against current OHLCV cache.

    Strategy: for each open signal, fetch 5m klines from its entry timestamp
    forward. Walk them via check_outcome-style logic. If outcome is
    determinable (TP/SL hit OR expiry passed), close the signal and write
    to results table.
    """
    open_rows = list(conn.execute(
        "SELECT id, token, signal, entry_price, sl, tp1, tp2, tp3, "
        " timestamp, expires_at FROM signals "
        "WHERE source = ? AND status = 'OPEN'", (SOAK_LABEL,),
    ))
    if not open_rows:
        return 0

    closed_count = 0
    # TZ-FIX (2026-06-02): keep tz-aware. Stripping tzinfo and then calling
    # .timestamp() on a naive datetime is interpreted by Python as LOCAL time
    # (CEST = UTC+2 on this server), shifting the Binance fetch window −2h
    # to PRE-entry bars. See LINK_OUTCOME_DIAGNOSIS.md / BCH_LOSS_DIAGNOSIS.md.
    now_utc = datetime.now(timezone.utc)

    for row in open_rows:
        sig_id = row["id"]
        token = row["token"]
        symbol = SYMBOL_MAP.get(token)
        if not symbol:
            continue
        direction = row["signal"]
        entry = row["entry_price"]
        sl = row["sl"]
        tp1 = row["tp1"]
        tp2 = row["tp2"]
        tp3 = row["tp3"]
        try:
            # TZ-FIX (2026-06-02): parse as UTC-aware so .timestamp() below
            # returns the correct UTC unix value (not −2h shifted as LOCAL).
            entry_dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            expiry_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        # Fetch 5m bars covering [entry_dt + 5min, min(now, expiry)]
        start_ms = int(entry_dt.timestamp() * 1000) + 5 * 60 * 1000
        end_ms = int(min(now_utc, expiry_dt).timestamp() * 1000)
        if end_ms <= start_ms:
            continue
        # Limited window — fetch up to 1000 5m bars (84h)
        url = (f"{BINANCE_BASE}?symbol={symbol}&interval=5m&limit=1000&"
               f"startTime={start_ms}&endTime={end_ms}")
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                    timeout=15) as resp:
                if resp.status != 200:
                    continue
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        if not raw:
            continue

        # Walk bars — RUNNER-EXIT FIX (2026-06-03, see RUNNER_EXIT_GAP.md):
        # The post-TP1 runner now has an active BE stop at ENTRY price. This
        # matches what live (Bybit) auto-trade execution does when the operator
        # moves the SL to entry after TP1 fills. Previously the post-TP1 SL was
        # ignored ("ride to TP3 or expiry"), which corresponds to the "no stop"
        # live scenario — catastrophic in real money. The new logic is the
        # closest live-portable match.
        tp1_hit = tp2_hit = tp3_hit = sl_hit = be_stopped = False
        entry_stopped_post_tp2 = False   # POST-TP2 HOLD-AT-ENTRY (V_ENTRY 2026-06-04): stop stays at entry after TP2
        last_bar_ts = entry_dt
        for bar in raw:
            h_p = float(bar[2])
            l_p = float(bar[3])
            last_bar_ts = datetime.fromtimestamp(int(bar[6]) / 1000, tz=timezone.utc).replace(tzinfo=None)  # F3-FIX
            if direction == "BUY":
                # Pre-TP1: original SL active
                if not tp1_hit and not sl_hit and l_p <= sl:
                    sl_hit = True; break
                # TP1 hit on this bar — defer BE check to NEXT bar (intrabar TP1-fills-first assumption)
                if not tp1_hit and h_p >= tp1:
                    tp1_hit = True; continue
                # Post-TP1 BE stop (active until TP2 reached)
                if tp1_hit and not tp2_hit and not be_stopped and l_p <= entry:
                    be_stopped = True; break
                # TP2 / TP3 progression
                if tp1_hit and not tp2_hit and h_p >= tp2:
                    tp2_hit = True
                    if h_p >= tp3: tp3_hit = True; break   # same-bar TP2->TP3 strong bar = WIN
                    continue                                # defer post-TP2 stop (TP2-fills-first; a same-bar
                                                            # low below entry is the pre-breakout low, not a retrace)
                # POST-TP2 HOLD-AT-ENTRY (V_ENTRY): stop STAYS at entry (not trailed to TP1).
                # A dip to TP1 does NOT terminate; only a return to ENTRY exits at breakeven.
                if tp2_hit and not tp3_hit and l_p <= entry: entry_stopped_post_tp2 = True; break
                if tp2_hit and not tp3_hit and h_p >= tp3: tp3_hit = True; break
            else:  # SELL — mirror
                if not tp1_hit and not sl_hit and h_p >= sl:
                    sl_hit = True; break
                if not tp1_hit and l_p <= tp1:
                    tp1_hit = True; continue
                if tp1_hit and not tp2_hit and not be_stopped and h_p >= entry:
                    be_stopped = True; break
                if tp1_hit and not tp2_hit and l_p <= tp2:
                    tp2_hit = True
                    if l_p <= tp3: tp3_hit = True; break   # same-bar TP2->TP3 strong bar = WIN
                    continue                                # defer post-TP2 stop (TP2-fills-first)
                # POST-TP2 HOLD-AT-ENTRY (SELL mirror): stop stays at entry (price rising back to entry)
                if tp2_hit and not tp3_hit and h_p >= entry: entry_stopped_post_tp2 = True; break
                if tp2_hit and not tp3_hit and l_p <= tp3: tp3_hit = True; break

        # Determine outcome under NEW runner-exit model:
        #   LOSS         : SL hit pre-TP1                      (terminal, runner never armed)
        #   WIN          : TP3 hit                              (terminal, runner exits at TP3)
        #   PARTIAL_TP1  : TP1 hit, then BE-stop OR window expired with runner above BE
        #                  (in both sub-cases the runner exits at entry with friction —
        #                   the R formula is identical, so they collapse into one label)
        #   PARTIAL_TP2  : TP1 + TP2 hit, no TP3, window expired
        #                  (runner deemed to have locked at TP2 — assumes a TP2 limit on
        #                   broker, or operator monitors and exits at TP2 retroactively)
        #   EXPIRED      : no TP1, no SL, window expired       (entire position rolled off)
        if sl_hit:
            outcome = "LOSS"; tp_reached = 0
        elif tp3_hit:
            outcome = "WIN"; tp_reached = 3
        elif entry_stopped_post_tp2:
            outcome = "PARTIAL_TP2_BE"; tp_reached = 2   # TP2 reached, ran back to entry (breakeven)
        elif be_stopped:
            outcome = "PARTIAL_TP1"; tp_reached = 1
        elif now_utc >= expiry_dt:
            if tp2_hit:
                outcome = "PARTIAL_TP2"; tp_reached = 2
            elif tp1_hit:
                outcome = "PARTIAL_TP1"; tp_reached = 1
            else:
                outcome = "EXPIRED"; tp_reached = 0
        else:
            continue  # still open — runner alive between TP1 and TP2 or TP2 and TP3

        # Compute realized R via 50/50 split-exit
        rt_cost_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
        if direction == "BUY":
            gross_tp1 = (tp1 - entry) / entry * 100
            gross_tp2 = (tp2 - entry) / entry * 100
            gross_tp3 = (tp3 - entry) / entry * 100
            gross_sl  = (sl - entry) / entry * 100
        else:
            gross_tp1 = (entry - tp1) / entry * 100
            gross_tp2 = (entry - tp2) / entry * 100
            gross_tp3 = (entry - tp3) / entry * 100
            gross_sl  = (entry - sl) / entry * 100
        net_tp1 = round(gross_tp1 - rt_cost_pct, 3)
        net_tp2 = round(gross_tp2 - rt_cost_pct, 3)
        net_tp3 = round(gross_tp3 - rt_cost_pct, 3)
        net_sl  = round(gross_sl - rt_cost_pct, 2)
        risk = abs(net_sl) or 0.001

        if outcome == "LOSS":
            realized_r = round(net_sl / risk, 4)
            profit_pct = net_sl
        elif outcome == "PARTIAL_TP1":
            # RUNNER-EXIT FIX (2026-06-03): runner exits at entry-with-friction
            # (not clean BE). 50% locked at TP1 + 50% paying rt_cost on the BE leg.
            realized_r = round((0.5 * net_tp1 + 0.5 * (-rt_cost_pct)) / risk, 4)
            profit_pct = round(0.5 * net_tp1 + 0.5 * (-rt_cost_pct), 3)
        elif outcome == "PARTIAL_TP2_BE":
            # POST-TP2 HOLD-AT-ENTRY (V_ENTRY 2026-06-04): TP2 reached, runner ran back to entry.
            # First half at TP1 + runner half at entry-with-friction (= PARTIAL_TP1 R).
            realized_r = round((0.5 * net_tp1 + 0.5 * (-rt_cost_pct)) / risk, 4)
            profit_pct = round(0.5 * net_tp1 + 0.5 * (-rt_cost_pct), 3)
        elif outcome == "PARTIAL_TP2":
            realized_r = round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
            profit_pct = round(0.5 * net_tp1 + 0.5 * net_tp2, 3)
        elif outcome == "WIN":
            realized_r = round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
            profit_pct = round(0.5 * net_tp1 + 0.5 * net_tp3, 3)
        else:  # EXPIRED (no TP1)
            realized_r = 0.0
            profit_pct = 0.0

        closed_at = last_bar_ts.strftime("%Y-%m-%d %H:%M:%S")

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO results (signal_id, tp1_hit, tp2_hit, tp3_hit, "
            " sl_hit, result, profit_pct, closed_at, realized_r) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sig_id, int(tp1_hit), int(tp2_hit), int(tp3_hit), int(sl_hit),
             outcome, profit_pct, closed_at, realized_r),
        )
        cur.execute(
            "UPDATE signals SET status = 'CLOSED' WHERE id = ?", (sig_id,),
        )
        conn.commit()
        closed_count += 1
        _log(f"  CLOSED #{sig_id} {token} {direction} → {outcome} R={realized_r:+.2f}")
    return closed_count


def scan_token(conn, token: str, consumed: set) -> bool:
    """One token scan cycle. Returns True if a new signal was emitted."""
    symbol = SYMBOL_MAP.get(token)
    if not symbol:
        return False

    c5m = fetch_klines(symbol, "5m", OHLCV_5M_LIMIT)
    c4h = fetch_klines(symbol, "4h", OHLCV_4H_LIMIT)
    if c5m is None or c4h is None:
        _log(f"  {token}: fetch failed, skipping cycle")
        return False
    if len(c4h["closes"]) < H4_BREAKOUT_C2_LOOKBACK + 5:
        return False

    setup = detect_h4_breakout(c4h, c5m, token=token, consumed=consumed)
    if setup is None:
        return False
    # F4-FIX (2026-06-02): mark consumed AFTER persist commits, not before.
    # Old order (consumed.add → ... → persist_signal) had a crash gap: if the
    # process died after add but before persist_signal's conn.commit(), the
    # in-memory mark was lost, the DB had no row, and load_consumed_set on
    # restart would not block re-firing the same C1 zone. New order: emit + persist
    # first; only if persist returns a sig_id do we mark consumed. Behavior change:
    # zones that fail downstream gates (mss_bar OOB, stale, sl_tp None, econ None)
    # are now retry-eligible next cycle — acceptable because the H4_BREAKOUT_C2_LOOKBACK
    # window scrolls them out within a bounded number of bars.

    # Pick entry as the next 5M bar's open at signal time. In a live setting
    # we'd wait for the next 5M close, but since we run every 2 min on a
    # 5M bar source, we approximate "entry = the bar we just observed close".
    # Specifically: setup["mss_bar_5m"] is within the 5m window; entry =
    # opens[mss_bar_5m + 1] if it exists, else the most recent close.
    mss_bar = setup["mss_bar_5m"]
    if mss_bar + 1 >= len(c5m["opens"]):
        # Not enough bars after MSS — wait for next cycle
        return False
    entry_price = c5m["opens"][mss_bar + 1]

    # Time of the entry bar (we use the entry bar's open time)
    entry_ts_ms = c5m["times"][mss_bar + 1]
    signal_ts = datetime.fromtimestamp(entry_ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None)  # F3-FIX: replaces deprecated datetime.utcfromtimestamp (output identical naive-UTC)
    # Guard against backtests of stale data — entry_ts must be < 60 min old
    age_sec = (datetime.now(timezone.utc).replace(tzinfo=None) - signal_ts).total_seconds()
    if age_sec > 3600:
        _log(f"  {token}: signal too stale ({age_sec:.0f}s old), skipping")
        return False

    sl_tp = compute_breakout_sl_tp(
        setup["direction"], entry_price, setup["sl_anchor"],
        setup["c1_high"], setup["c1_low"],
    )
    if sl_tp is None:
        return False
    sl_price, tp1, tp2, tp3 = sl_tp

    rt_cost_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
    econ = compute_crt_trade_economics(
        setup["direction"], entry_price, sl_price, tp1, tp2, tp3,
        outcome=None, rt_cost_pct=rt_cost_pct,
    )
    if econ is None:
        return False

    sig_id = persist_signal(conn, token, setup, entry_price,
                              sl_price, tp1, tp2, tp3, econ, signal_ts)
    consumed.add(setup["key"])  # F4-FIX: post-persist mark — crash-safe
    _log(f"  NEW SIGNAL #{sig_id} {token} {setup['direction']} entry={entry_price:.6f} "
         f"sl={sl_price:.6f} tp1={tp1:.6f} tp2={tp2:.6f} tp3={tp3:.6f} "
         f"({setup['confluence']['type']}, mss={setup.get('mss_quality')})")
    return True


def write_heartbeat(cycle: int, n_open: int, n_closed: int,
                     last_signal_ts: Optional[str]):
    payload = {
        "ts_unix":     _time.time(),
        "ts_utc":      datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "pid":         os.getpid(),
        "cycle":       cycle,
        "config":      "config_14",
        "soak_label":  SOAK_LABEL,
        "open_signals":   n_open,
        "closed_signals": n_closed,
        "last_signal_ts": last_signal_ts,
    }
    tmp = HEARTBEAT_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, HEARTBEAT_PATH)


def check_isolation():
    """Hard-fail if anything looks wrong before the soak starts."""
    # 1. PID file race
    if PID_PATH.exists():
        try:
            other_pid = int(PID_PATH.read_text().strip())
            try:
                os.kill(other_pid, 0)
                # PID alive — another soak is already running
                _log(f"FATAL: another breakout soak is running at PID {other_pid}. "
                     f"Kill it first with: kill -TERM {other_pid}")
                sys.exit(1)
            except ProcessLookupError:
                _log(f"  Stale PID file ({other_pid} dead) — overwriting.")
        except (ValueError, OSError):
            _log(f"  Stale PID file unreadable — overwriting.")
    # 2. Verify DB exists
    if not DB_PATH.exists():
        _log(f"FATAL: breakout DB missing at {DB_PATH}")
        sys.exit(1)
    # 3. Verify schema has signals table
    conn = sqlite3.connect(str(DB_PATH))
    has_signals = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
    ).fetchone()
    conn.close()
    if not has_signals:
        _log(f"FATAL: breakout DB has no `signals` table")
        sys.exit(1)
    # 4. Confirm fade soak's DB exists but we never touch it
    fade_db = Path("/home/tradeai/TradeAI/data/signals.db")
    if not fade_db.exists():
        _log(f"WARNING: fade soak DB not found at {fade_db} — that's surprising "
             f"but we don't touch it anyway.")


def main():
    LOG_DIR.mkdir(exist_ok=True)
    _log("=" * 70)
    _log("BREAKOUT PAPER SOAK — Phase C-Breakout Step 2B")
    _log("=" * 70)
    _log(f"  PID:         {os.getpid()}")
    _log(f"  Config:      {CONFIG_14}")
    _log(f"  Tokens:      {TOKENS}")
    _log(f"  DB:          {DB_PATH}")
    _log(f"  Heartbeat:   {HEARTBEAT_PATH}")
    _log(f"  PID file:    {PID_PATH}")
    _log(f"  Cycle every: {CHECK_INTERVAL_SEC}s")

    check_isolation()

    # Write own PID
    PID_PATH.write_text(str(os.getpid()))
    signal_module.signal(signal_module.SIGTERM, _sigterm_handler)
    signal_module.signal(signal_module.SIGINT,  _sigterm_handler)

    conn = open_db()
    consumed = load_consumed_set(conn)
    _log(f"  Restart-safe: loaded {len(consumed)} previously-consumed C1 zones.")

    cycle = 0
    while _RUNNING:
        cycle += 1
        cycle_start = _time.time()
        n_new = 0
        try:
            # 1) Detection scan
            for tok in TOKENS:
                if not _RUNNING:
                    break
                try:
                    if scan_token(conn, tok, consumed):
                        n_new += 1
                except Exception as e:
                    _log(f"  {tok}: scan error: {e!r}")
                    traceback.print_exc()

            # 2) Outcome resolution for OPEN signals
            n_closed_this_cycle = 0
            try:
                n_closed_this_cycle = resolve_open_signals(conn)
            except Exception as e:
                _log(f"  resolution error: {e!r}")
                traceback.print_exc()

            # 3) Heartbeat
            n_open = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE source = ? AND status = 'OPEN'",
                (SOAK_LABEL,),
            ).fetchone()[0]
            n_closed_total = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE source = ? AND status = 'CLOSED'",
                (SOAK_LABEL,),
            ).fetchone()[0]
            last_sig_row = conn.execute(
                "SELECT timestamp FROM signals WHERE source = ? "
                "ORDER BY id DESC LIMIT 1", (SOAK_LABEL,),
            ).fetchone()
            last_sig_ts = last_sig_row[0] if last_sig_row else None
            write_heartbeat(cycle, n_open, n_closed_total, last_sig_ts)

            elapsed = _time.time() - cycle_start
            _log(f"  cycle {cycle}: new={n_new}, closed_this_cycle={n_closed_this_cycle}, "
                 f"open={n_open}, closed_total={n_closed_total}, elapsed={elapsed:.1f}s")
        except Exception as e:
            _log(f"  cycle {cycle}: FATAL error: {e!r}")
            traceback.print_exc()

        # Sleep to next cycle (respect shutdown signal)
        wait = max(1.0, CHECK_INTERVAL_SEC - (_time.time() - cycle_start))
        slept = 0.0
        while slept < wait and _RUNNING:
            _time.sleep(min(1.0, wait - slept))
            slept += 1.0

    _log("Graceful shutdown — removing PID file.")
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass
    conn.close()


if __name__ == "__main__":
    main()
