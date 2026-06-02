"""
breakout_paper_soak_B.py — Phase C-Breakout Step 2B-PARALLEL — Config B (5M/1H).

A SECOND independent paper-soak process running Config B (5M entry / 1H ref)
in parallel with the existing A soak (5M/4H, PID 458923) and the fade soak.
Every isolation invariant from the A soak is preserved, with all state files
renamed for B so the two soaks share NO mutable state.

Differences vs A:
  - Reference timeframe: 1H instead of 4H
  - Reference-bar duration (for sub-window anchoring): 1h * 60min * 60sec * 1000ms
  - Source tag in DB: 'H4_BREAKOUT_PAPER_SOAK_B'
  - PID file: data/breakout_soak_B.pid
  - Heartbeat file: data/breakout_soak_B_heartbeat.json
  - Log file: logs/breakout_soak_B.log
  - Binance kline fetch: interval=1h instead of 4h (5m entry unchanged)

EVERYTHING ELSE matches A: locked Config 14 knobs (TP cascade, C2 lookback,
MSS horizon, OB scan, FVG probe), same 12-token universe, same staleness
guard, same economics gate.

Cross-soak guarantees:
  - SQLite WAL mode permits A's writer + B's writer + viewer's reader
    concurrently. Per-statement commits keep each transaction short.
  - Each soak rebuilds its consumed-zone set ONLY from its own source tag.
    A's writes can never pollute B's mitigation set.
  - Verified at startup: refuses to run if another B-tagged process holds
    the PID file (no double-start).
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

# Lock Config 14 BEFORE importing breakout_engine — IDENTICAL to A.
# (The TF difference is in the data we feed the detector, not in the knobs.)
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
USER_AGENT   = "TradeAI-BreakoutSoak-B/1.0"

CHECK_INTERVAL_SEC = 120      # 2-minute scan cadence — matches A
FORWARD_BARS_5M    = 576      # 48 h expiry window — matches A
OHLCV_5M_LIMIT     = 500      # entry-TF fetch — matches A
OHLCV_1H_LIMIT     = 300      # reference-TF fetch — was 4H=300 in A, now 1H=300
                              # (=12.5d coverage; enough for the 4+4-buffer = 8-bar window
                              #  with comfortable history for ATR / freshness checks)

DB_PATH       = _BREAKOUT_DIR / "data" / "breakout.db"
PID_PATH      = _BREAKOUT_DIR / "data" / "breakout_soak_B.pid"
HEARTBEAT_PATH = _BREAKOUT_DIR / "data" / "breakout_soak_B_heartbeat.json"
LOG_DIR       = _BREAKOUT_DIR / "logs"

# DISTINCT source tag — viewer's gate math filters by this string
SOAK_LABEL = "H4_BREAKOUT_PAPER_SOAK_B"

# Reference-TF bar duration in milliseconds. This is the ONLY structural
# constant that changes between A (=4h) and B (=1h).
REF_BAR_DURATION_MS = 1 * 60 * 60 * 1000

# Reference-TF Binance interval string
REF_TF_INTERVAL = "1h"


# ── Graceful shutdown ──────────────────────────────────────────────────────
_RUNNING = True


def _sigterm_handler(signum, frame):
    global _RUNNING
    _log(f"Received signal {signum} — finishing current cycle and exiting.")
    _RUNNING = False


def _log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── Binance fetcher (identical contract to A) ──────────────────────────────
def fetch_klines(symbol: str, interval: str, limit: int) -> Optional[dict]:
    """Fetch klines from Binance REST, drop the forming (last) bar.

    Returns:
        {"opens": [...], "highs": [...], "lows": [...], "closes": [...],
         "times": [...]}  with the most recent CLOSED bar last, OR None on error.
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
        opens, highs, lows, closes, times = [], [], [], [], []
        for row in raw[:-1]:   # drop forming bar — same as A
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
    """Rebuild consumed-zone set from B's own signal rows only (NOT A's).

    Filters by SOAK_LABEL so A's writes never pollute B's mitigation set.
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
    """Insert into signals with the B-specific source tag."""
    cur = conn.cursor()
    direction = setup["direction"]
    expires_ts = (signal_ts + timedelta(minutes=FORWARD_BARS_5M * 5)).strftime("%Y-%m-%d %H:%M:%S")
    ts_str = signal_ts.strftime("%Y-%m-%d %H:%M:%S")
    h = signal_ts.hour
    if 13 <= h < 17:   session = "NY_AM_KZ"
    elif 2 <= h < 6:   session = "LONDON_KZ"
    elif 20 <= h < 24: session = "ASIA_KZ"
    elif 0 <= h < 6:   session = "ASIA_EARLY"
    else:              session = "OVERNIGHT"

    confluence_type = setup["confluence"]["type"]
    fvg_q = (setup["confluence"]["details"].get("quality", "NONE")
             if confluence_type == "FVG" else "NONE")
    mss_q = setup.get("mss_quality", "NONE")

    feat_blob = json.dumps({
        "c1_zone_key": list(setup["key"]),
        "config":      "config_14_B_5m_1h",   # explicit so any future audit knows
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
         f"H4_BREAKOUT_{confluence_type}_B",   # entry_type tagged with _B for analyzability
         h, signal_ts.weekday(), SOAK_LABEL, feat_blob),
    )
    conn.commit()
    return cur.lastrowid


def resolve_open_signals(conn) -> int:
    """Outcome resolution — only on B-tagged OPEN signals."""
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
        tp1, tp2, tp3 = row["tp1"], row["tp2"], row["tp3"]
        try:
            # TZ-FIX (2026-06-02): parse as UTC-aware so .timestamp() below
            # returns the correct UTC unix value (not −2h shifted as LOCAL).
            entry_dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            expiry_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        start_ms = int(entry_dt.timestamp() * 1000) + 5 * 60 * 1000
        end_ms = int(min(now_utc, expiry_dt).timestamp() * 1000)
        if end_ms <= start_ms:
            continue
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
        tp1_hit = tp2_hit = tp3_hit = sl_hit = False
        last_bar_ts = entry_dt
        for bar in raw:
            h_p = float(bar[2])
            l_p = float(bar[3])
            last_bar_ts = datetime.utcfromtimestamp(int(bar[6]) / 1000)
            if direction == "BUY":
                if not sl_hit and not tp1_hit and l_p <= sl: sl_hit = True; break
                if not tp1_hit and h_p >= tp1: tp1_hit = True
                if tp1_hit and not tp2_hit and h_p >= tp2: tp2_hit = True
                if tp2_hit and not tp3_hit and h_p >= tp3: tp3_hit = True
            else:
                if not sl_hit and not tp1_hit and h_p >= sl: sl_hit = True; break
                if not tp1_hit and l_p <= tp1: tp1_hit = True
                if tp1_hit and not tp2_hit and l_p <= tp2: tp2_hit = True
                if tp2_hit and not tp3_hit and l_p <= tp3: tp3_hit = True
        if sl_hit:        outcome, tp_reached = "LOSS", 0
        elif tp3_hit:     outcome, tp_reached = "WIN", 3
        elif tp2_hit:     outcome, tp_reached = "PARTIAL_TP2", 2
        elif tp1_hit:     outcome, tp_reached = "PARTIAL_TP1", 1
        elif now_utc >= expiry_dt:
                          outcome, tp_reached = "EXPIRED", 0
        else:
            continue
        rt_cost_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
        if direction == "BUY":
            gross_tp1 = (tp1 - entry)/entry * 100
            gross_tp2 = (tp2 - entry)/entry * 100
            gross_tp3 = (tp3 - entry)/entry * 100
            gross_sl  = (sl - entry)/entry * 100
        else:
            gross_tp1 = (entry - tp1)/entry * 100
            gross_tp2 = (entry - tp2)/entry * 100
            gross_tp3 = (entry - tp3)/entry * 100
            gross_sl  = (entry - sl)/entry * 100
        net_tp1 = round(gross_tp1 - rt_cost_pct, 3)
        net_tp2 = round(gross_tp2 - rt_cost_pct, 3)
        net_tp3 = round(gross_tp3 - rt_cost_pct, 3)
        net_sl  = round(gross_sl - rt_cost_pct, 2)
        risk = abs(net_sl) or 0.001
        if outcome == "LOSS":
            realized_r = round(net_sl / risk, 4); profit_pct = net_sl
        elif outcome == "PARTIAL_TP1":
            realized_r = round((0.5 * net_tp1) / risk, 4)
            profit_pct = round(0.5 * net_tp1, 3)
        elif outcome == "PARTIAL_TP2":
            realized_r = round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
            profit_pct = round(0.5 * net_tp1 + 0.5 * net_tp2, 3)
        elif outcome == "WIN":
            realized_r = round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
            profit_pct = round(0.5 * net_tp1 + 0.5 * net_tp3, 3)
        else:
            realized_r = 0.0; profit_pct = 0.0
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
    """One token scan cycle. Uses 1H reference instead of 4H — only delta vs A."""
    symbol = SYMBOL_MAP.get(token)
    if not symbol:
        return False
    c5m = fetch_klines(symbol, "5m", OHLCV_5M_LIMIT)
    c1h = fetch_klines(symbol, REF_TF_INTERVAL, OHLCV_1H_LIMIT)
    if c5m is None or c1h is None:
        _log(f"  {token}: fetch failed, skipping cycle")
        return False
    if len(c1h["closes"]) < H4_BREAKOUT_C2_LOOKBACK + 5:
        return False

    # The detector takes (ref_TF_data, entry_TF_data). Naming convention says
    # `c4h` for the reference and `c5m` for the entry, but the function does
    # NOT actually care about the timeframe — it just walks the arrays.
    setup = detect_h4_breakout(c1h, c5m, token=token, consumed=consumed)
    if setup is None:
        return False
    consumed.add(setup["key"])

    mss_bar = setup["mss_bar_5m"]
    if mss_bar + 1 >= len(c5m["opens"]):
        return False
    entry_price = c5m["opens"][mss_bar + 1]
    entry_ts_ms = c5m["times"][mss_bar + 1]
    signal_ts = datetime.utcfromtimestamp(entry_ts_ms / 1000)
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
    _log(f"  NEW B-SIGNAL #{sig_id} {token} {setup['direction']} entry={entry_price:.6f} "
         f"sl={sl_price:.6f} tp1={tp1:.6f} tp2={tp2:.6f} tp3={tp3:.6f} "
         f"({setup['confluence']['type']}, mss={setup.get('mss_quality')})")
    return True


def write_heartbeat(cycle: int, n_open: int, n_closed: int,
                     last_signal_ts: Optional[str]):
    payload = {
        "ts_unix":   _time.time(),
        "ts_utc":    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "pid":       os.getpid(),
        "cycle":     cycle,
        "config":    "config_14_B_5m_1h",
        "soak_label": SOAK_LABEL,
        "ref_tf":    REF_TF_INTERVAL,
        "entry_tf":  "5m",
        "open_signals":   n_open,
        "closed_signals": n_closed,
        "last_signal_ts": last_signal_ts,
    }
    tmp = HEARTBEAT_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, HEARTBEAT_PATH)


def check_isolation():
    """Hard-fail if anything looks wrong before B starts."""
    # 1. PID race — but ONLY for B's PID file (don't touch A's at all)
    if PID_PATH.exists():
        try:
            other_pid = int(PID_PATH.read_text().strip())
            try:
                os.kill(other_pid, 0)
                _log(f"FATAL: another B soak is running at PID {other_pid}. "
                     f"Kill it first with: kill -TERM {other_pid}")
                sys.exit(1)
            except ProcessLookupError:
                _log(f"  Stale B PID file ({other_pid} dead) — overwriting.")
        except (ValueError, OSError):
            _log(f"  Stale B PID file unreadable — overwriting.")
    # 2. DB
    if not DB_PATH.exists():
        _log(f"FATAL: breakout DB missing at {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    has_signals = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
    ).fetchone()
    conn.close()
    if not has_signals:
        _log(f"FATAL: breakout DB has no `signals` table")
        sys.exit(1)
    # 3. Confirm A soak's PID file is INTACT — we don't want to accidentally
    # collide with its state.
    a_pid_path = _BREAKOUT_DIR / "data" / "breakout_soak.pid"
    if a_pid_path.exists():
        try:
            a_pid = int(a_pid_path.read_text().strip())
            os.kill(a_pid, 0)   # raises ProcessLookupError if dead
            _log(f"  A soak detected alive at PID {a_pid}. B will run in parallel.")
        except ProcessLookupError:
            _log(f"  A soak PID file present but PID {a_pid} is dead — not our problem.")
        except (ValueError, OSError):
            pass
    else:
        _log(f"  No A soak PID file detected at {a_pid_path}. B will run independently.")


def main():
    LOG_DIR.mkdir(exist_ok=True)
    _log("=" * 70)
    _log("BREAKOUT PAPER SOAK — Phase C-Breakout Config B (5M/1H)")
    _log("=" * 70)
    _log(f"  PID:         {os.getpid()}")
    _log(f"  Config:      {CONFIG_14}")
    _log(f"  Entry TF:    5m")
    _log(f"  Reference TF: {REF_TF_INTERVAL}")
    _log(f"  Tokens:      {TOKENS}")
    _log(f"  DB:          {DB_PATH}")
    _log(f"  Heartbeat:   {HEARTBEAT_PATH}")
    _log(f"  PID file:    {PID_PATH}")
    _log(f"  Source tag:  {SOAK_LABEL}")
    _log(f"  Cycle every: {CHECK_INTERVAL_SEC}s")

    check_isolation()
    PID_PATH.write_text(str(os.getpid()))
    signal_module.signal(signal_module.SIGTERM, _sigterm_handler)
    signal_module.signal(signal_module.SIGINT,  _sigterm_handler)

    conn = open_db()
    consumed = load_consumed_set(conn)
    _log(f"  Restart-safe: loaded {len(consumed)} previously-consumed B C1 zones.")

    cycle = 0
    while _RUNNING:
        cycle += 1
        cycle_start = _time.time()
        n_new = 0
        try:
            for tok in TOKENS:
                if not _RUNNING:
                    break
                try:
                    if scan_token(conn, tok, consumed):
                        n_new += 1
                except Exception as e:
                    _log(f"  {tok}: scan error: {e!r}")
                    traceback.print_exc()
            n_closed_this_cycle = 0
            try:
                n_closed_this_cycle = resolve_open_signals(conn)
            except Exception as e:
                _log(f"  resolution error: {e!r}")
                traceback.print_exc()
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
        wait = max(1.0, CHECK_INTERVAL_SEC - (_time.time() - cycle_start))
        slept = 0.0
        while slept < wait and _RUNNING:
            _time.sleep(min(1.0, wait - slept))
            slept += 1.0

    _log("Graceful shutdown — removing B PID file.")
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass
    conn.close()


if __name__ == "__main__":
    main()
