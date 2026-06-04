"""
Phase C-Breakout — TF comparison harness.

Runs the breakout detection on 3 (entry_TF, reference_TF) pairs over a fixed
90-day window. Saves all signals to data/breakout.db tagged with the config.

The breakout engine is hardcoded to "c4h" / "c5m" naming but doesn't actually
care about TF — it's all just (reference candle dict) + (entry candle dict) +
time arrays in ms. We adapt by:
  1. Passing the right candle dicts as c4h/c5m.
  2. Telling the harness the reference-TF bar duration (in ms) so sub-window
     anchoring works correctly.
  3. Holding the engine's bar-count knobs identical (C2_LOOKBACK=4,
     MSS_HORIZON=30) — pre-registered fairness rule.
"""
from __future__ import annotations

import bisect
import importlib
import json
import os
import sqlite3
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path

_BREAKOUT_DIR = Path(__file__).resolve().parent
_TRADEAI_DIR  = Path("/home/tradeai/TradeAI")
sys.path.insert(0, str(_BREAKOUT_DIR))
sys.path.insert(0, str(_TRADEAI_DIR))

# 90-day window — locked
END_MS   = int(datetime(2026, 5, 31, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
START_MS = END_MS - 90 * 24 * 60 * 60 * 1000

TOKENS = ["BTC", "ETH", "XRP", "HBAR", "AVAX", "LINK", "BNB",
          "ADA", "POL", "TON", "ATOM", "BCH"]

# Cache locations
CACHE_5M_4H_1H = _TRADEAI_DIR / "data" / "ohlcv_cache"   # existing
CACHE_1M       = _BREAKOUT_DIR / "data" / "cache_1m_90d"  # fetched fresh

# Forward outcome window in MINUTES (48h matches the soak / Config 14)
FORWARD_MINUTES = 48 * 60

# DB
DB_PATH = _BREAKOUT_DIR / "data" / "breakout.db"

# Locked Config 14 fingerprint
LOCKED_KNOBS = {
    "H4_BREAKOUT_CLOSE_BUFFER_PCT": "0.001",
    "BREAKOUT_TP1_RR":              "2.0",
    "BREAKOUT_TP2_RR":              "3.0",
    "BREAKOUT_TP3_RR":              "4.0",
    "H4_BREAKOUT_OB_SCAN_LOOKBACK": "20",
    "H4_BREAKOUT_FVG_PROBE_WIDTH":  "3",
    "BREAKOUT_SL_INSIDE_BUFFER_PCT": "0.001",
    "H4_BREAKOUT_C2_LOOKBACK":      "4",
    "H4_BREAKOUT_MSS_HORIZON":      "30",
}

# 3 TF configs — pre-registered
TF_CONFIGS = [
    {
        "id": "A_5m_4h",
        "entry_tf": "5m",
        "ref_tf":   "4h",
        "ref_bar_duration_ms": 4 * 60 * 60 * 1000,
        "entry_bar_duration_ms": 5 * 60 * 1000,
        "label": "5M / 4H (current validated config)",
    },
    {
        "id": "B_5m_1h",
        "entry_tf": "5m",
        "ref_tf":   "1h",
        "ref_bar_duration_ms": 1 * 60 * 60 * 1000,
        "entry_bar_duration_ms": 5 * 60 * 1000,
        "label": "5M / 1H (same entry, shorter ref)",
    },
    {
        "id": "C_1m_1h",
        "entry_tf": "1m",
        "ref_tf":   "1h",
        "ref_bar_duration_ms": 1 * 60 * 60 * 1000,
        "entry_bar_duration_ms": 1 * 60 * 1000,
        "label": "1M / 1H (finer entry, same ref)",
    },
]

# Sub-window sizing (mirrors breakout_backtest.py constants but parameterized)
H4_WINDOW_BUFFER = 4  # extra ref bars beyond C2_LOOKBACK
ENTRY_WINDOW_SIZE = 300  # entry-TF bars in the per-step sub-window


def load_cached(tok: str, tf: str) -> dict | None:
    """Load OHLCV cache for token+TF, slice to the 90-day window."""
    if tf == "1m":
        path = CACHE_1M / f"{tok}USDT_1m_90d.json"
    else:
        path = CACHE_5M_4H_1H / f"{tok}USDT_{tf}_365d.json"
    if not path.exists():
        return None
    blob = json.load(open(path))
    inner = blob.get("data") if isinstance(blob, dict) else None
    if not inner:
        return None
    times = inner["times"]
    # Slice to [START_MS, END_MS]
    i_start = bisect.bisect_left(times, START_MS)
    i_end   = bisect.bisect_right(times, END_MS)
    if i_end - i_start < 30:
        return None
    return {
        "opens":  inner["opens"][i_start:i_end],
        "highs":  inner["highs"][i_start:i_end],
        "lows":   inner["lows"][i_start:i_end],
        "closes": inner["closes"][i_start:i_end],
        "times":  times[i_start:i_end],
    }


def check_outcome(direction: str, entry: float, sl: float,
                   tp1: float, tp2: float, tp3: float,
                   future_bars: list, post_tp2_mode: str = "hold_entry"):
    """Walk forward bars under the RUNNER-EXIT FIX (2026-06-03) model:
       BE-active runner after TP1 (matches live Bybit move-SL-to-entry rule).

    `post_tp2_mode` selects the post-TP2 stop placement:
      "hold_entry" (DEFAULT, = LIVE soak model V_ENTRY, adopted 2026-06-04): after
                   TP2 the stop STAYS at ENTRY; a return to ENTRY → PARTIAL_TP2_BE
                   (runner exits at breakeven). Between TP2 and entry there is NO
                   stop — so a dip to TP1 does NOT terminate; it can resume to TP3
                   or expire as PARTIAL_TP2.
      "trail_tp1"  (retired reference): after TP2 the stop trails UP to TP1; a
                   return to TP1 → PARTIAL_TP2_T1 (locks TP1 on both halves). Kept
                   only for the POSTTP2_STOP_COMPARISON reference.

    Returns (outcome, tp_reached). Outcomes:
      LOSS / WIN / PARTIAL_TP1 / PARTIAL_TP2 / EXPIRED (as before) plus
      PARTIAL_TP2_T1 (trail_tp1 mode) or PARTIAL_TP2_BE (hold_entry mode).
    """
    tp1_hit = tp2_hit = tp3_hit = sl_hit = be_stopped = False
    t1_trail_stopped = False      # post-TP2 trail-to-TP1 (trail_tp1 mode)
    entry_stopped_post_tp2 = False  # post-TP2 hold-at-entry (hold_entry mode)
    for bar in future_bars:
        h, l = bar["h"], bar["l"]
        if direction == "BUY":
            # Pre-TP1 SL
            if not tp1_hit and not sl_hit and l <= sl:
                sl_hit = True; break
            # TP1: defer BE check to next bar (intrabar TP1-fills-first)
            if not tp1_hit and h >= tp1:
                tp1_hit = True; continue
            # Post-TP1 BE stop (entry price), active until TP2 reached
            if tp1_hit and not tp2_hit and not be_stopped and l <= entry:
                be_stopped = True; break
            # TP2/TP3 progression
            if tp1_hit and not tp2_hit and h >= tp2:
                tp2_hit = True
                if h >= tp3:                      # same-bar TP2->TP3 strong bar = WIN
                    tp3_hit = True; break
                continue                          # defer post-TP2 stop (TP2-fills-first; a same-bar
                                                  # low is the pre-breakout low, not a retrace)
            # POST-TP2 STOP: trail_tp1 stops at TP1; hold_entry stops at ENTRY.
            if tp2_hit and not tp3_hit:
                if post_tp2_mode == "trail_tp1" and l <= tp1:
                    t1_trail_stopped = True; break
                if post_tp2_mode == "hold_entry" and l <= entry:
                    entry_stopped_post_tp2 = True; break
            if tp2_hit and not tp3_hit and h >= tp3:
                tp3_hit = True; break
        else:  # SELL — mirror
            if not tp1_hit and not sl_hit and h >= sl:
                sl_hit = True; break
            if not tp1_hit and l <= tp1:
                tp1_hit = True; continue
            if tp1_hit and not tp2_hit and not be_stopped and h >= entry:
                be_stopped = True; break
            if tp1_hit and not tp2_hit and l <= tp2:
                tp2_hit = True
                if l <= tp3:                      # same-bar TP2->TP3 strong bar = WIN
                    tp3_hit = True; break
                continue                          # defer post-TP2 stop (TP2-fills-first)
            # POST-TP2 STOP (SELL mirror): trail_tp1 at TP1 (price RISING), hold_entry at ENTRY
            if tp2_hit and not tp3_hit:
                if post_tp2_mode == "trail_tp1" and h >= tp1:
                    t1_trail_stopped = True; break
                if post_tp2_mode == "hold_entry" and h >= entry:
                    entry_stopped_post_tp2 = True; break
            if tp2_hit and not tp3_hit and l <= tp3:
                tp3_hit = True; break

    if sl_hit:                 return "LOSS",           0
    if tp3_hit:                return "WIN",            3
    if t1_trail_stopped:       return "PARTIAL_TP2_T1", 2   # trail_tp1: trailed out at TP1
    if entry_stopped_post_tp2: return "PARTIAL_TP2_BE", 2   # hold_entry: ran back to entry (BE)
    if be_stopped:             return "PARTIAL_TP1",    1
    # Window walked to the end without terminal hit — classify by tier reached
    if tp2_hit:      return "PARTIAL_TP2", 2
    if tp1_hit:      return "PARTIAL_TP1", 1
    return "EXPIRED",                       0


def _calc_realized_r(outcome: str, net_tp1: float, net_sl: float,
                     net_tp2: float, net_tp3: float,
                     rt_cost_pct: float) -> float:
    """RUNNER-EXIT FIX (2026-06-03): PARTIAL_TP1 now charges friction on the
    runner's BE exit. Other tiers unchanged."""
    risk = abs(net_sl) or 0.0001
    if outcome == "LOSS":
        return round(net_sl / risk, 4)
    if outcome == "PARTIAL_TP1":
        # runner exits at entry with friction → contributes -rt_cost_pct on the runner leg
        return round((0.5 * net_tp1 + 0.5 * (-rt_cost_pct)) / risk, 4)
    if outcome == "PARTIAL_TP2_T1":
        # POST-TP2 TRAIL FIX (2026-06-04): TP2 reached, runner trailed out at TP1.
        # Both halves exit at TP1 (friction already inside net_tp1) → R = net_tp1/risk.
        return round((0.5 * net_tp1 + 0.5 * net_tp1) / risk, 4)
    if outcome == "PARTIAL_TP2_BE":
        # V_ENTRY (hold_entry): TP2 reached, runner ran back to ENTRY (breakeven).
        # First half at TP1 + runner half at entry-with-friction → identical to
        # PARTIAL_TP1: R = (0.5*net_tp1 + 0.5*(-rt_cost_pct)) / risk.
        return round((0.5 * net_tp1 + 0.5 * (-rt_cost_pct)) / risk, 4)
    if outcome == "PARTIAL_TP2":
        return round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
    if outcome == "WIN":
        return round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
    return 0.0


def run_one_token(token: str, cfg: dict, detect, compute_sl_tp,
                  compute_econ, token_rt_cost: dict, fallback_rt: float) -> list:
    """Run the parametric backtest on one (token, config)."""
    c_entry = load_cached(token, cfg["entry_tf"])
    c_ref   = load_cached(token, cfg["ref_tf"])
    if c_entry is None or c_ref is None:
        return []
    n_entry = len(c_entry["closes"])
    n_ref   = len(c_ref["closes"])
    # Need enough forward bars beyond entry for outcome
    forward_entry_bars = FORWARD_MINUTES // (cfg["entry_bar_duration_ms"] // 60_000)
    if n_entry < forward_entry_bars + 100 or n_ref < 20:
        return []

    rt_cost_pct = token_rt_cost.get(token, fallback_rt) * 100
    signals = []
    consumed: set = set()
    # Use Config 14's C2 lookback (=4) as the bar-count
    c2_lookback = 4
    ref_window = c2_lookback + H4_WINDOW_BUFFER
    ref_bar_dur_ms = cfg["ref_bar_duration_ms"]
    mss_horizon_entry_bars = 30  # also from locked knobs

    for ref_end in range(ref_window, n_ref):
        ref_start = ref_end - ref_window
        ref_sub = {k: c_ref[k][ref_start:ref_end] for k in c_ref}
        # Anchor entry sub-window to the ref bar's CLOSE time
        ref_open_t  = c_ref["times"][ref_end - 1]
        ref_close_t = ref_open_t + ref_bar_dur_ms
        entry_end_idx = bisect.bisect_right(c_entry["times"], ref_close_t)
        entry_end_idx = min(entry_end_idx + mss_horizon_entry_bars + 10, n_entry)
        entry_start_idx = max(0, entry_end_idx - ENTRY_WINDOW_SIZE)
        if entry_end_idx - entry_start_idx < 30:
            continue
        entry_sub = {k: c_entry[k][entry_start_idx:entry_end_idx] for k in c_entry}

        setup = detect(ref_sub, entry_sub, token=token, consumed=consumed)
        if setup is None:
            continue
        consumed.add(setup["key"])

        mss_bar_abs = entry_start_idx + setup["mss_bar_5m"]  # field named for legacy
        if mss_bar_abs >= n_entry - forward_entry_bars - 1:
            continue
        entry_bar = mss_bar_abs + 1
        if entry_bar >= n_entry - forward_entry_bars - 1:
            continue
        entry_price = c_entry["opens"][entry_bar]
        direction = setup["direction"]

        sl_tp = compute_sl_tp(direction, entry_price, setup["sl_anchor"],
                                setup["c1_high"], setup["c1_low"])
        if sl_tp is None:
            continue
        sl_price, tp1, tp2, tp3 = sl_tp

        # Same BEW / fees_kill / MAX_SL_PCT gate as Config 14
        econ_gate = compute_econ(direction, entry_price, sl_price,
                                  tp1, tp2, tp3, outcome=None,
                                  rt_cost_pct=rt_cost_pct)
        if econ_gate is None:
            continue

        future = [
            {"h": c_entry["highs"][j], "l": c_entry["lows"][j]}
            for j in range(entry_bar + 1, min(entry_bar + 1 + forward_entry_bars, n_entry))
        ]
        if not future:
            continue
        outcome, tp_reached = check_outcome(direction, entry_price, sl_price, tp1, tp2, tp3, future)

        # Compute realized R via split-exit on actual entry (clean = intended)
        if direction == "BUY":
            gross_tp1 = (tp1 - entry_price) / entry_price * 100
            gross_tp2 = (tp2 - entry_price) / entry_price * 100
            gross_tp3 = (tp3 - entry_price) / entry_price * 100
            gross_sl  = (sl_price - entry_price) / entry_price * 100
        else:
            gross_tp1 = (entry_price - tp1) / entry_price * 100
            gross_tp2 = (entry_price - tp2) / entry_price * 100
            gross_tp3 = (entry_price - tp3) / entry_price * 100
            gross_sl  = (entry_price - sl_price) / entry_price * 100
        net_tp1 = round(gross_tp1 - rt_cost_pct, 3)
        net_tp2 = round(gross_tp2 - rt_cost_pct, 3)
        net_tp3 = round(gross_tp3 - rt_cost_pct, 3)
        net_sl  = round(gross_sl  - rt_cost_pct, 2)
        realized_r = _calc_realized_r(outcome, net_tp1, net_sl, net_tp2, net_tp3, rt_cost_pct)

        ts = datetime.fromtimestamp(c_entry["times"][entry_bar]/1000, timezone.utc)
        h_hour = ts.hour
        signals.append({
            "token":  token, "signal": direction,
            "price":  round(entry_price, 8), "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "tp1_pct": round(gross_tp1, 3), "sl_pct": round(gross_sl, 3),
            "net_tp1_pct": net_tp1, "net_tp2_pct": net_tp2, "net_tp3_pct": net_tp3,
            "net_sl_pct": net_sl,
            "rr1": round(abs(gross_tp1/gross_sl), 2) if gross_sl else 0,
            "tp_reached": tp_reached, "outcome": outcome,
            "realized_r": realized_r,
            "hour_utc": h_hour, "day_of_week": ts.weekday(),
            "sweep_type": setup["type"],
            "mss_quality": setup.get("mss_quality", "NONE"),
            "fvg_quality": (setup["confluence"]["details"].get("quality", "NONE")
                            if setup["confluence"]["type"] == "FVG" else "NONE"),
            "entry_type": f"H4_BREAKOUT_{setup['confluence']['type']}_TF",
            "confidence": 7,
            "intended_entry_for_friction": entry_price,
            "atr_5m_at_signal": 0.0,  # filled by friction stage
            "entry_bar_idx": entry_bar,
        })

    return signals


def persist_run(conn, cfg_id: str, friction_mode: str, signals: list,
                 elapsed: float, label: str) -> int:
    n = len(signals)
    n_wins = sum(1 for s in signals if s["outcome"] in ("WIN", "PARTIAL_TP2", "PARTIAL_TP2_T1", "PARTIAL_TP2_BE"))
    wr = n_wins / n if n else 0.0
    sum_r = sum(s["realized_r"] for s in signals)
    avg_r = sum_r / n if n else 0.0
    config_hash = f"{cfg_id}_{friction_mode}"
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    summary = json.dumps({
        "tf_config_id": cfg_id, "friction_mode": friction_mode,
        "label": label, "n": n, "wr": wr, "avg_R": avg_r, "sum_R": sum_r,
        "elapsed_sec": elapsed,
        "window_start": datetime.fromtimestamp(START_MS/1000, timezone.utc).strftime('%Y-%m-%d'),
        "window_end":   datetime.fromtimestamp(END_MS/1000, timezone.utc).strftime('%Y-%m-%d'),
    }, sort_keys=True)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO backtest_runs (run_date, days, total_signals, overall_wr, "
        "avg_rr, status, summary, config_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_date, 90, n, wr, sum(s["rr1"] for s in signals)/n if n else 0,
         "DONE", summary, config_hash),
    )
    run_id = cur.lastrowid
    src = f"H4_BREAKOUT_TF_{cfg_id}_{friction_mode}"
    for s in signals:
        cur.execute(
            "INSERT INTO backtest_signals "
            "(run_id, token, signal, price, ts, tp1_pct, sl_pct, rr1, tp_reached, outcome, "
            " net_tp1_pct, net_sl_pct, net_rr1, breakeven_wr, "
            " sweep_type, hour_utc, day_of_week, mss_quality, fvg_quality, entry_type, "
            " net_tp2_pct, net_tp3_pct, source, realized_r) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?, "
            "        ?, ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?)",
            (run_id, s["token"], s["signal"], s["price"], s["ts"],
             s["tp1_pct"], s["sl_pct"], s["rr1"], s["tp_reached"], s["outcome"],
             s["net_tp1_pct"], s["net_sl_pct"], 0, 0,
             s["sweep_type"], s["hour_utc"], s["day_of_week"], s["mss_quality"],
             s["fvg_quality"], s["entry_type"],
             s["net_tp2_pct"], s["net_tp3_pct"], src, s["realized_r"]),
        )
    conn.commit()
    return run_id


def _atr_n(highs, lows, closes, end_idx, n: int) -> float:
    if end_idx < n + 1:
        return 0.0
    trs = []
    for i in range(end_idx - n, end_idx):
        if i <= 0:
            continue
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return sum(trs)/len(trs) if trs else 0.0


def apply_friction(signals: list, cfg: dict, c_entry_by_token: dict,
                    derive_seed_fn, simulate_exec_fn) -> list:
    """Layer execution friction onto a clean signals list.
    Returns the new list with REJECTED dropped + per-signal R adjusted."""
    out = []
    for s in signals:
        tok = s["token"]
        c_entry = c_entry_by_token.get(tok)
        if not c_entry:
            continue
        entry_bar = s["entry_bar_idx"]
        if entry_bar - 1 < 0 or entry_bar >= len(c_entry["opens"]):
            continue
        # signal_ts = close of MSS bar = entry_bar - 1's close timestamp + bar_dur
        mss_bar = entry_bar - 1
        # ATR on entry TF
        atr = _atr_n(c_entry["highs"], c_entry["lows"], c_entry["closes"], mss_bar, n=14)
        if atr <= 0:
            continue
        # atr_ratio: current ATR vs ~50-bar trailing avg
        long_atr = _atr_n(c_entry["highs"], c_entry["lows"], c_entry["closes"],
                           max(0, mss_bar - 50), n=14)
        atr_ratio = (atr / long_atr) if long_atr > 0 else 1.0
        ts_dt = datetime.strptime(s["ts"], "%Y-%m-%d %H:%M:%S")
        seed = derive_seed_fn(ts_dt, tok, s["signal"])
        signal_price = c_entry["closes"][mss_bar]
        next_bar_open = c_entry["opens"][entry_bar]
        try:
            res = simulate_exec_fn(
                signal_ts=ts_dt, signal_price=signal_price,
                next_bar_open=next_bar_open, token=tok,
                direction=s["signal"], regime="UNKNOWN",
                atr_5m=atr, atr_ratio=atr_ratio, seed=seed,
            )
        except Exception:
            continue
        if res.status == "REJECTED":
            continue
        actual_entry = res.fill_price
        fill_size = res.fill_size_pct
        total_cost_pct = res.total_cost_pct * 100  # fraction → %
        # Recompute realized_r from actual_entry with the friction cost
        if s["signal"] == "BUY":
            sl = actual_entry * (1 + s["sl_pct"]/100)  # sl_pct is negative
            tp1 = actual_entry * (1 + (s["sl_pct"]/100)*(-2.0))  # 2R away
            # Easier: scale s's gross numbers by ratio
            ratio = s["price"] / actual_entry if actual_entry else 1.0
            # Use stored gross_tp1/sl percentages but with new cost
            gross_tp1 = s["tp1_pct"] * ratio  # tight approximation
            gross_sl  = s["sl_pct"] * ratio
        else:
            ratio = actual_entry / s["price"] if s["price"] else 1.0
            gross_tp1 = s["tp1_pct"] * ratio
            gross_sl  = s["sl_pct"] * ratio
        # Friction-aware nets — use total_cost_pct (potentially > baseline)
        # Approximation: take stored gross values, deduct full friction cost
        net_tp1 = round(s["tp1_pct"] - total_cost_pct, 3)
        net_tp2 = round((s["net_tp2_pct"] + (s["tp1_pct"] - s["net_tp1_pct"])) - total_cost_pct, 3)  # approx
        net_tp3 = round((s["net_tp3_pct"] + (s["tp1_pct"] - s["net_tp1_pct"])) - total_cost_pct, 3)
        net_sl  = round(s["sl_pct"] - total_cost_pct, 2)
        rr = _calc_realized_r(s["outcome"], net_tp1, net_sl, net_tp2, net_tp3, total_cost_pct)
        adj = dict(s)
        adj["realized_r"] = round(rr * fill_size, 4)  # half-size partial = half R
        adj["net_tp1_pct"] = net_tp1
        adj["net_tp2_pct"] = net_tp2
        adj["net_tp3_pct"] = net_tp3
        adj["net_sl_pct"] = net_sl
        out.append(adj)
    return out


def main():
    print("=" * 78)
    print("PHASE C-BREAKOUT — TF COMPARISON HARNESS")
    print("=" * 78)
    window_start = datetime.fromtimestamp(START_MS/1000, timezone.utc).strftime('%Y-%m-%d')
    window_end   = datetime.fromtimestamp(END_MS/1000, timezone.utc).strftime('%Y-%m-%d')
    print(f"  Window: {window_start} → {window_end}  (90 days)")
    print(f"  Tokens: {TOKENS}")
    print(f"  Configs: 3 (A: 5M/4H, B: 5M/1H, C: 1M/1H)")
    print()

    # Set locked knobs in environment
    for k, v in LOCKED_KNOBS.items():
        os.environ[k] = v
    # Force reload of breakout_engine so constants pick up env
    import breakout_engine as _be
    importlib.reload(_be)
    detect = _be.detect_h4_breakout
    compute_sl_tp = _be.compute_breakout_sl_tp
    from crt_engine import compute_crt_trade_economics as compute_econ
    from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT
    from execution import simulate_execution, derive_seed

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    all_results = []
    for cfg in TF_CONFIGS:
        print(f"\n  Config {cfg['id']}: {cfg['label']}")
        # ── CLEAN backtest ──
        t0 = _time.time()
        clean_signals = []
        c_entry_cache = {}
        for tok in TOKENS:
            sigs = run_one_token(tok, cfg, detect, compute_sl_tp,
                                  compute_econ, TOKEN_RT_COST,
                                  ROUND_TRIP_COST_PCT)
            clean_signals.extend(sigs)
            # Cache entry data for friction stage
            c_entry_cache[tok] = load_cached(tok, cfg["entry_tf"])
            print(f"    {tok:>5}: {len(sigs)} clean signals")
        elapsed = _time.time() - t0
        run_id = persist_run(conn, cfg["id"], "CLEAN", clean_signals,
                              elapsed, cfg["label"])
        print(f"  → {cfg['id']} CLEAN run_id={run_id}: n={len(clean_signals)}, "
              f"elapsed={elapsed:.1f}s")

        # ── FRICTION backtest ──
        t0 = _time.time()
        fric_signals = apply_friction(clean_signals, cfg, c_entry_cache,
                                        derive_seed, simulate_execution)
        elapsed_f = _time.time() - t0
        run_id_f = persist_run(conn, cfg["id"], "FRICTION", fric_signals,
                                elapsed_f, cfg["label"])
        print(f"  → {cfg['id']} FRICTION run_id={run_id_f}: n={len(fric_signals)} "
              f"(dropped {len(clean_signals)-len(fric_signals)}), "
              f"elapsed={elapsed_f:.1f}s")
        all_results.append({
            "config_id": cfg["id"],
            "clean_run_id": run_id, "clean_n": len(clean_signals),
            "friction_run_id": run_id_f, "friction_n": len(fric_signals),
        })

    conn.close()
    out_path = _BREAKOUT_DIR / "data" / "tf_grid_results.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Wrote: {out_path}")
    print("Done.")


if __name__ == "__main__":
    main()
