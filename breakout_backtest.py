"""
breakout_backtest.py — Standalone backtest harness for the breakout thesis.

PHASE C-BREAKOUT minimal harness — DELIBERATELY independent of backtest.py
so the fade-era machinery (OGD bootstrap, CPCV write-back, baseline_pin
reads, blend warnings) cannot contaminate the fresh-thesis measurement.

What this harness DOES:
  - Loads OHLCV from the existing cache READ-ONLY (data/ohlcv_cache/*.json)
  - Sweeps a sliding H4 window and calls breakout_engine.detect_h4_breakout
  - For each setup: applies SL/TP via compute_breakout_sl_tp, runs
    forward-bar outcome simulation (same logic as backtest.check_outcome),
    computes realized R and net %.
  - Writes one row per signal to data/breakout.db (the new empty DB
    we created in /home/tradeai/breakout-work/data/)
  - Writes one row per run config to backtest_runs in the same DB.

What this harness DOES NOT do:
  - Read or write data/signals.db (the live soak DB) — strictly off-limits.
  - Touch the live token_weights or backtest_token_weights tables (OGD off).
  - Apply the fade engine's economics gates beyond what crt_engine.
    compute_crt_trade_economics already enforces (which is direction-
    agnostic: fees_kill, MAX_SL_PCT, breakeven_wr).
  - Apply Wyckoff, funding-rate, BTC-correlation overlays.
  - Persist any CPCV verdict to bot_state (that contaminates the live
    learning gate). All metrics computed in-memory in compute_metrics.py.

OHLCV cache contract (verified):
    {
      "schema_version": 1,
      "symbol":    "BTCUSDT",
      "interval":  "4h",
      "days":      365,
      "data": {
          "opens":  [...],
          "highs":  [...],
          "lows":   [...],
          "closes": [...],
          "volumes":[...],
          "times":  [...]    # milliseconds since epoch
      }
    }
"""
from __future__ import annotations

import bisect
import hashlib
import json
import os
import sqlite3
import sys
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Path setup: prefer breakout-work modules, fall back to TradeAI for shared
# read-only modules (ict_engine, config, etc.).
_BREAKOUT_DIR = Path(__file__).resolve().parent
_TRADEAI_DIR  = Path("/home/tradeai/TradeAI")
if str(_BREAKOUT_DIR) not in sys.path:
    sys.path.insert(0, str(_BREAKOUT_DIR))
if str(_TRADEAI_DIR) not in sys.path:
    sys.path.insert(0, str(_TRADEAI_DIR))

# Critical: do NOT import anything that triggers data/signals.db connections.
# Specifically AVOID: crypto_alert (opens live DB), backtest (opens live DB).
import breakout_engine  # noqa: E402
from breakout_engine import (  # noqa: E402
    detect_h4_breakout,
    compute_breakout_sl_tp,
    H4_BREAKOUT_C2_LOOKBACK,
    H4_BREAKOUT_CLOSE_BUFFER_PCT,
    H4_BREAKOUT_MSS_HORIZON,
    BREAKOUT_TP1_RR,
    BREAKOUT_TP2_RR,
    BREAKOUT_TP3_RR,
)
from crt_engine import compute_crt_trade_economics, crt_trade_rejection_reason  # noqa: E402
from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT  # noqa: E402

OHLCV_CACHE_DIR = _TRADEAI_DIR / "data" / "ohlcv_cache"
BREAKOUT_DB_PATH = _BREAKOUT_DIR / "data" / "breakout.db"

# 12-token universe — same as the soak (config.py BINANCE_TOKENS)
TOKENS = ["BTC", "ETH", "XRP", "HBAR", "AVAX", "LINK", "BNB",
          "ADA", "POL", "TON", "ATOM", "BCH"]

# H4 / 5M scan-window parameters (kept inline to avoid backtest.py imports)
H4_WINDOW_BUFFER     = 4    # extra H4 bars beyond C2_LOOKBACK for context
CRT_5M_WINDOW_SIZE   = 300  # 5M bars in the per-step sub-window
H4_BAR_DURATION_MS   = 4 * 60 * 60 * 1000  # 4h in ms
FORWARD_BARS         = 576  # 48h outcome window (same as fade CRT default)


def load_ohlcv(symbol: str, interval: str) -> Optional[dict]:
    """Read one cached OHLCV file as the canonical {opens/highs/...} dict."""
    fp = OHLCV_CACHE_DIR / f"{symbol}USDT_{interval}_365d.json"
    if not fp.exists():
        return None
    with open(fp, "r") as f:
        d = json.load(f)
    inner = d.get("data") if isinstance(d, dict) else None
    if not inner:
        return None
    return inner


def check_outcome(direction: str, sl: float, tp1: float, tp2: float, tp3: float,
                   future_bars: list):
    """Same outcome semantics as backtest.check_outcome — copied here so we
    don't import backtest.py (which would open the live DB).

    Returns (outcome_str, tp_level_reached).
    """
    tp1_hit = tp2_hit = tp3_hit = sl_hit = False
    for bar in future_bars:
        h, l = bar["h"], bar["l"]
        if direction == "BUY":
            if not sl_hit and not tp1_hit and l <= sl:
                sl_hit = True
                break
            if not tp1_hit and h >= tp1:
                tp1_hit = True
            if tp1_hit and not tp2_hit and h >= tp2:
                tp2_hit = True
            if tp2_hit and not tp3_hit and h >= tp3:
                tp3_hit = True
        else:
            if not sl_hit and not tp1_hit and h >= sl:
                sl_hit = True
                break
            if not tp1_hit and l <= tp1:
                tp1_hit = True
            if tp1_hit and not tp2_hit and l <= tp2:
                tp2_hit = True
            if tp2_hit and not tp3_hit and l <= tp3:
                tp3_hit = True

    if sl_hit:
        return "LOSS", 0
    if tp3_hit:
        return "WIN", 3
    if tp2_hit:
        return "PARTIAL_TP2", 2
    if tp1_hit:
        return "PARTIAL_TP1", 1
    return "EXPIRED", 0


def compute_excursions(direction: str, entry_price: float, sl: float, tp1: float,
                        future_bars: list):
    """MFE / MAE over forward window (stops at SL or TP1 hit, same as backtest.py)."""
    if not future_bars or not entry_price or entry_price <= 0 or sl is None or tp1 is None:
        return 0.0, 0.0
    max_high = entry_price
    min_low = entry_price
    for bar in future_bars:
        h, l = bar["h"], bar["l"]
        if h > max_high:
            max_high = h
        if l < min_low:
            min_low = l
        if direction == "BUY":
            if l <= sl or h >= tp1:
                break
        else:
            if h >= sl or l <= tp1:
                break
    scale = 100.0 / entry_price
    if direction == "BUY":
        mfe_pct = max(0.0, (max_high - entry_price) * scale)
        mae_pct = max(0.0, (entry_price - min_low) * scale)
    else:
        mfe_pct = max(0.0, (entry_price - min_low) * scale)
        mae_pct = max(0.0, (max_high - entry_price) * scale)
    return round(mfe_pct, 6), round(mae_pct, 6)


def _calc_realized_r(outcome: str, net_tp1_pct: float, net_sl_pct: float,
                      net_tp2_pct: Optional[float] = None,
                      net_tp3_pct: Optional[float] = None) -> float:
    """50/50 split-exit at TP1 with BE-stop runner.

    LOSS         : net_sl_pct  / risk
    PARTIAL_TP1  : 0.5 * net_tp1_pct / risk  (half at TP1, runner BE = 0)
    PARTIAL_TP2  : (0.5 * net_tp1_pct + 0.5 * net_tp2_pct) / risk
    WIN          : (0.5 * net_tp1_pct + 0.5 * net_tp3_pct) / risk
    EXPIRED      : 0.0
    """
    risk = abs(net_sl_pct) if net_sl_pct else 0.0001
    if outcome == "LOSS":
        return round(net_sl_pct / risk, 4)
    if outcome == "PARTIAL_TP1":
        return round((0.5 * net_tp1_pct) / risk, 4)
    if outcome == "PARTIAL_TP2":
        n2 = net_tp2_pct if net_tp2_pct is not None else net_tp1_pct
        return round((0.5 * net_tp1_pct + 0.5 * n2) / risk, 4)
    if outcome == "WIN":
        n3 = net_tp3_pct if net_tp3_pct is not None else net_tp1_pct
        return round((0.5 * net_tp1_pct + 0.5 * n3) / risk, 4)
    return 0.0


# ── Per-token backtest loop ────────────────────────────────────────────────
def run_breakout_token(token: str, c5m: dict, c4h: dict) -> list[dict]:
    """Run the breakout scanner across a token's full 365d cache.

    Returns list of signal dicts (matching backtest_signals columns).
    """
    if not c4h or not c5m:
        return []
    n5 = len(c5m["closes"])
    n4 = len(c4h["closes"])
    if n5 < FORWARD_BARS + 100 or n4 < 20:
        return []

    signals = []
    consumed: set = set()
    h4_window = H4_BREAKOUT_C2_LOOKBACK + H4_WINDOW_BUFFER
    rt_cost_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100

    for h4_end in range(h4_window, n4):
        h4_start = h4_end - h4_window
        c4h_win = {
            "opens":  c4h["opens"][h4_start:h4_end],
            "highs":  c4h["highs"][h4_start:h4_end],
            "lows":   c4h["lows"][h4_start:h4_end],
            "closes": c4h["closes"][h4_start:h4_end],
            "times":  c4h["times"][h4_start:h4_end],
        }
        # Anchor 5M sub-window to the H4 bar's CLOSE time (no lookahead)
        h4_open_time_ms  = c4h["times"][h4_end - 1]
        h4_close_time_ms = h4_open_time_ms + H4_BAR_DURATION_MS
        c5m_end_idx = bisect.bisect_right(c5m["times"], h4_close_time_ms)
        c5m_end_idx = min(c5m_end_idx + H4_BREAKOUT_MSS_HORIZON + 10, n5)
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

        # Translate sub-window MSS bar back to absolute c5m index
        mss_bar_abs = c5m_start_idx + setup["mss_bar_5m"]
        if mss_bar_abs >= n5 - FORWARD_BARS - 1:
            continue
        entry_bar = mss_bar_abs + 1
        if entry_bar >= n5 - FORWARD_BARS - 1:
            continue
        entry_price = c5m["opens"][entry_bar]
        direction = setup["direction"]

        # SL + TP cascade
        sl_tp = compute_breakout_sl_tp(
            direction, entry_price, setup["sl_anchor"],
            setup["c1_high"], setup["c1_low"],
        )
        if sl_tp is None:
            continue
        sl_price, tp1_price, tp2_price, tp3_price = sl_tp

        # Forward outcome
        future = [
            {"h": c5m["highs"][j], "l": c5m["lows"][j]}
            for j in range(entry_bar + 1, min(entry_bar + 1 + FORWARD_BARS, n5))
        ]
        if not future:
            continue
        outcome, tp_reached = check_outcome(
            direction, sl_price, tp1_price, tp2_price, tp3_price, future,
        )
        mfe_pct, mae_pct = compute_excursions(
            direction, entry_price, sl_price, tp1_price, future,
        )

        # Economics — direction-agnostic, same gates as fade
        econ = compute_crt_trade_economics(
            direction, entry_price, sl_price,
            tp1_price, tp2_price, tp3_price,
            outcome, rt_cost_pct,
        )
        if econ is None:
            continue

        # Realized R via split-exit model
        realized_r = _calc_realized_r(
            outcome, econ["net_tp1"], econ["net_sl"],
            econ["net_tp2"], econ["net_tp3"],
        )

        ts = datetime.utcfromtimestamp(c5m["times"][entry_bar] / 1000)
        # Session bucket — tagging only, per §2 of the prompt
        h = ts.hour
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

        signals.append({
            "token":           token,
            "signal":          direction,
            "price":           round(entry_price, 6),
            "ts":              ts.strftime("%Y-%m-%d %H:%M:%S"),
            "confidence":      6 + (2 if setup["confluence"]["type"] == "OB" else 1),
            "sweep_type":      setup["type"],   # BSL_BREAKOUT or SSL_BREAKOUT
            "session":         session,
            "hour_utc":        h,
            "day_of_week":     ts.weekday(),
            "mss_quality":     setup["mss_quality"],
            "fvg_quality":     (setup["confluence"]["details"].get("quality", "NONE")
                                if setup["confluence"]["type"] == "FVG" else "NONE"),
            "entry_type":      f"H4_BREAKOUT_{setup['confluence']['type']}",
            "tp1_pct":         round(econ["gross_tp1"], 3),
            "sl_pct":          round(econ["gross_sl"], 3),
            "net_tp1_pct":     econ["net_tp1"],
            "net_tp2_pct":     econ["net_tp2"],
            "net_tp3_pct":     econ["net_tp3"],
            "net_sl_pct":      econ["net_sl"],
            "rr1":             econ["rr1"],
            "net_rr1":         econ["net_rr1"],
            "breakeven_wr":    econ["breakeven_wr"],
            "tp_reached":      tp_reached,
            "outcome":         outcome,
            "realized_r":      realized_r,
            "mfe_pct":         mfe_pct,
            "mae_pct":         mae_pct,
            "source":          "H4_BREAKOUT",
        })

    return signals


# ── DB persistence ──────────────────────────────────────────────────────────
def open_breakout_db():
    """Open data/breakout.db with safe WAL mode (no contention with anything
    since this DB is the only consumer)."""
    conn = sqlite3.connect(str(BREAKOUT_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def compute_config_hash(config: dict) -> str:
    """Stable hash over the config dict for backtest_runs.config_hash."""
    s = json.dumps(config, sort_keys=True).encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def persist_run(conn, config: dict, signals_by_token: dict[str, list[dict]],
                 elapsed_sec: float) -> int:
    """Persist a single run to backtest_runs + backtest_signals tables."""
    all_signals = [s for sigs in signals_by_token.values() for s in sigs]
    n = len(all_signals)
    n_wins = sum(1 for s in all_signals if s["outcome"] in ("WIN", "PARTIAL_TP2"))
    n_partial1 = sum(1 for s in all_signals if s["outcome"] == "PARTIAL_TP1")
    overall_wr = (n_wins + 0.5 * n_partial1) / n if n > 0 else 0.0
    avg_rr = (sum(s["rr1"] for s in all_signals) / n) if n > 0 else 0.0
    config_hash = compute_config_hash(config)
    run_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    summary = json.dumps({
        "config":             config,
        "n_signals":          n,
        "overall_wr":         round(overall_wr, 4),
        "avg_rr":             round(avg_rr, 4),
        "avg_realized_r":     round(sum(s["realized_r"] for s in all_signals) / n, 4) if n else 0,
        "sum_net_pct":        round(sum(s["realized_r"] * abs(s["net_sl_pct"]) for s in all_signals), 4),
        "by_token":           {tok: len(sigs) for tok, sigs in signals_by_token.items()},
        "elapsed_sec":        round(elapsed_sec, 2),
    }, sort_keys=True)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO backtest_runs (run_date, days, total_signals, overall_wr, "
        "avg_rr, status, summary, config_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_date, 365, n, overall_wr, avg_rr, "DONE", summary, config_hash),
    )
    run_id = cur.lastrowid

    for s in all_signals:
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


def run_one_config(config: dict, conn) -> dict:
    """Run a single backtest config across all 12 tokens, persist, return summary."""
    # Apply env overrides for this config
    for k, v in config.items():
        os.environ[k] = str(v)

    # Reload module constants so the new env vars take effect
    import importlib
    import breakout_engine as _be
    importlib.reload(_be)
    # Re-import names into our globals
    global detect_h4_breakout, compute_breakout_sl_tp
    detect_h4_breakout = _be.detect_h4_breakout
    compute_breakout_sl_tp = _be.compute_breakout_sl_tp

    t0 = _time.time()
    signals_by_token: dict[str, list[dict]] = {}
    for tok in TOKENS:
        symbol = tok  # cache key matches token name
        c5m = load_ohlcv(symbol, "5m")
        c4h = load_ohlcv(symbol, "4h")
        if c5m is None or c4h is None:
            signals_by_token[tok] = []
            continue
        sigs = run_breakout_token(tok, c5m, c4h)
        signals_by_token[tok] = sigs

    elapsed = _time.time() - t0
    run_id = persist_run(conn, config, signals_by_token, elapsed)

    n_total = sum(len(s) for s in signals_by_token.values())
    print(f"  Config {config} → run_id={run_id} | n={n_total} | "
          f"elapsed={elapsed:.1f}s")
    return {
        "run_id":           run_id,
        "config":           config,
        "n_signals":        n_total,
        "by_token":         {t: len(s) for t, s in signals_by_token.items()},
        "elapsed_sec":      elapsed,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("BREAKOUT BACKTEST HARNESS — PHASE C-BREAKOUT")
    print("=" * 70)
    print(f"  Breakout DB:    {BREAKOUT_DB_PATH}")
    print(f"  OHLCV cache:    {OHLCV_CACHE_DIR} (read-only)")
    print(f"  Tokens:         {TOKENS}")
    print(f"  Outcome window: {FORWARD_BARS} 5M bars ({FORWARD_BARS*5/60:.0f}h)")
    print()

    # Smoke test: one config, default knobs
    conn = open_breakout_db()
    smoke_config = {
        "H4_BREAKOUT_C2_LOOKBACK":      8,
        "H4_BREAKOUT_CLOSE_BUFFER_PCT": 0.0,
        "H4_BREAKOUT_MSS_HORIZON":      30,
        "BREAKOUT_TP1_RR":              1.5,
        "BREAKOUT_TP2_RR":              2.5,
        "BREAKOUT_TP3_RR":              3.5,
    }
    print("SMOKE TEST: running default config...")
    result = run_one_config(smoke_config, conn)
    print(f"\n  → SMOKE RESULT: {result['n_signals']} signals, "
          f"{result['elapsed_sec']:.1f}s")
    conn.close()
