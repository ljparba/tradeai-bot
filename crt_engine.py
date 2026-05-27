"""
crt_engine.py — Candle Range Theory (CRT) detection module.

H4 reference candle + 5M entry timeframe per the operator-confirmed spec
in docs/exploration_runs/CRT_RESEARCH_2026_05_27.md (v1).

Architecture:
  - Wyckoff/flexible validation school: LTF (5M) MSS confirmation is
    accepted in lieu of waiting for the H4 C3 close (article author's
    explicit recommendation; allows reuse of ict_engine.detect_ict_mss).
  - Hybrid entry: 5M MSS within sweep window (~30 min after H4 C2 close)
    rather than article-aggressive (immediate at C2 wick) or article-
    conservative (full H4 C3 close ~4 hours later).
  - Confluence: requires (FVG OR Order Block) overlap with the C1 range
    or with the MSS bar's local envelope. Order Block highlighted by the
    Trading Wyckoff article as the PRIMARY confluence (more significant
    than FVG alone).
  - One-shot mitigation per C1 range — first valid touch only.

This module DOES NOT modify ict_engine.py's existing detection logic. It
reuses find_ict_swings, detect_ict_mss, score_ict_fvg, and the new
detect_ict_order_block / order_block_overlaps_range functions.

Env-overridable constants:
  ENABLE_H4_CRT           — master toggle (default 0 = OFF, no signals emitted)
  H4_CRT_DISABLED_TOKENS  — comma-separated blacklist (default empty)
  H4_CRT_C2_LOOKBACK      — H4 bars to scan for sweep candle (default 10)
  H4_CRT_MSS_HORIZON      — 5M bars after H4 sweep for MSS confirmation (default 30)
  H4_CRT_OB_SCAN_LOOKBACK — bars to scan for OB on the H4 candle stream (default 20)

H6 isolation: shared by crypto_alert.py (live) AND backtest.py (backtest)
via the same module — guarantees live/backtest parity by construction.
"""
import os as _os

from ict_engine import (
    ICT_MSS_HORIZON,
    find_ict_swings,
    detect_ict_mss,
    score_ict_fvg,
    detect_ict_order_block,
    order_block_overlaps_range,
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(_os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_str(name: str, default: str) -> str:
    return _os.environ.get(name, default)


# ── Module constants (env-overridable) ──────────────────────────────────────
ENABLE_H4_CRT = _env_int("ENABLE_H4_CRT", 0) == 1
H4_CRT_DISABLED_TOKENS = {
    t.strip().upper()
    for t in _env_str("H4_CRT_DISABLED_TOKENS", "").split(",")
    if t.strip()
}
H4_CRT_C2_LOOKBACK = _env_int("H4_CRT_C2_LOOKBACK", 10)
H4_CRT_MSS_HORIZON = _env_int("H4_CRT_MSS_HORIZON", ICT_MSS_HORIZON)
H4_CRT_OB_SCAN_LOOKBACK = _env_int("H4_CRT_OB_SCAN_LOOKBACK", 20)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _find_5m_bar_after(c5m_times, target_time) -> int:
    """Return the index of the first 5M bar whose timestamp > target_time.

    Used to anchor the 5M MSS-confirmation window to the H4 C2 (sweep)
    candle's close. Returns -1 if no later 5M bar exists in the cache.
    """
    for i, t in enumerate(c5m_times):
        if t > target_time:
            return i
    return -1


def _approx_mss_bar(sweep_5m_idx: int, c5m_closes, sh_5m, sl_5m,
                    sweep_type: str, horizon: int) -> int:
    """Re-derive the bar at which MSS confirmed, since detect_ict_mss returns
    only bool. Walks the same window and returns the first bar where the
    structural break is satisfied.

    Returns -1 if not found within `horizon` bars.
    """
    n = len(c5m_closes)
    end = min(n, sweep_5m_idx + horizon + 1)
    if sweep_type == "SSL":
        # Bullish — first close above the most-recent swing high prior to sweep
        target = None
        for sh_idx, sh_lev in reversed(sh_5m):
            if sh_idx < sweep_5m_idx:
                target = sh_lev
                break
        if target is None:
            return -1
        for k in range(sweep_5m_idx + 1, end):
            if c5m_closes[k] > target:
                return k
    elif sweep_type == "BSL":
        # Bearish — first close below the most-recent swing low prior to sweep
        target = None
        for sl_idx, sl_lev in reversed(sl_5m):
            if sl_idx < sweep_5m_idx:
                target = sl_lev
                break
        if target is None:
            return -1
        for k in range(sweep_5m_idx + 1, end):
            if c5m_closes[k] < target:
                return k
    return -1


def _check_confluence(direction: str, c1_high: float, c1_low: float,
                      mss_bar_5m: int, c4h: dict, c5m: dict):
    """Return a confluence dict if EITHER an FVG OR an Order Block overlaps
    the C1 range or the MSS bar's local envelope. Otherwise None.

    direction: "BUY" or "SELL"
    Returns:
        {"type": "FVG"|"OB", "details": <dict>}  on overlap
        None on no qualifying confluence
    """
    h5 = c5m["highs"]
    l5 = c5m["lows"]
    o5 = c5m["opens"]
    c5 = c5m["closes"]

    # 1. Check for FVG near the MSS bar (5M displacement creates FVG)
    if 0 <= mss_bar_5m < len(c5) - 1:
        for d in (mss_bar_5m - 1, mss_bar_5m, mss_bar_5m + 1):
            if d < 1 or d + 1 >= len(c5):
                continue
            fvg = score_ict_fvg(d, h5, l5, o5, c5)
            if fvg is None or fvg["direction"] != direction:
                continue
            # FVG must overlap C1 range — confirms institutional zone alignment
            if not (fvg["bottom"] > c1_high or fvg["top"] < c1_low):
                return {"type": "FVG", "details": fvg}

    # 2. Fall back to Order Block detection on H4 stream
    h4_opens = c4h["opens"]
    h4_highs = c4h["highs"]
    h4_lows = c4h["lows"]
    h4_closes = c4h["closes"]
    ob = detect_ict_order_block(
        h4_opens, h4_highs, h4_lows, h4_closes,
        lookback=H4_CRT_OB_SCAN_LOOKBACK,
    )
    if ob is not None and ob["direction"] == direction:
        if order_block_overlaps_range(ob, c1_high, c1_low):
            return {"type": "OB", "details": ob}

    return None


# ── Main detection ──────────────────────────────────────────────────────────
def detect_h4_crt(c4h: dict, c5m: dict, token: str = "",
                  consumed: set = None) -> dict:
    """Detect an H4 Candle Range Theory setup with 5M LTF MSS confirmation.

    Per the Wyckoff/flexible school — the sweep candle's BODY close
    position is NOT the decisive factor. What confirms the setup is the
    subsequent control change, detected here via 5M MSS within
    H4_CRT_MSS_HORIZON bars after C2's close.

    Args:
        c4h: dict with keys 'opens','highs','lows','closes','times' (~30 H4 bars)
        c5m: dict with same keys (~300 5M bars covering the H4 window)
        token: token symbol for blacklist check (case-insensitive)
        consumed: set of (c1_idx, round(c1_high,6), round(c1_low,6)) tuples
                  representing C1 ranges already used by a prior signal.
                  Caller mutates the set after generating a signal to mark
                  the range mitigated. None → fresh empty set per call.

    Returns:
        Signal dict on valid setup, None otherwise.

        {
          "source":          "H4_CRT",
          "type":            "SSL_CRT" | "BSL_CRT",
          "direction":       "BUY" | "SELL",
          "c1_idx":          int,        # H4 bar index of parent candle
          "c1_high":         float,
          "c1_low":          float,
          "c2_idx":          int,        # H4 bar index of sweep candle
          "c2_time":         <time>,     # close time of C2 (for downstream timing)
          "sweep_wick":      float,      # the actual wicked extreme (SL anchor)
          "sweep_5m_idx":    int,        # first 5M bar after C2 close
          "mss_bar_5m":      int,        # 5M bar where MSS confirmed (entry anchor)
          "confluence":      {"type": "FVG"|"OB", "details": dict},
          "tp1":             float,      # opposite extreme of C1 (universal CRT TP)
          "sl":              float,      # below/above C2 wick (universal CRT SL)
          "key":             tuple,      # mitigation key for caller to add to consumed
        }
    """
    if not ENABLE_H4_CRT:
        return None
    if token and token.upper() in H4_CRT_DISABLED_TOKENS:
        return None
    if consumed is None:
        consumed = set()

    # Defensive: required dict shape
    required_keys = {"opens", "highs", "lows", "closes", "times"}
    if not required_keys.issubset(c4h.keys()) or not required_keys.issubset(c5m.keys()):
        return None

    h4_highs = c4h["highs"]
    h4_lows = c4h["lows"]
    h4_closes = c4h["closes"]
    h4_times = c4h["times"]
    n_h4 = len(h4_closes)
    if n_h4 < 3:
        return None

    c5m_times = c5m["times"]
    c5m_closes = c5m["closes"]
    h5 = c5m["highs"]
    l5 = c5m["lows"]
    if len(c5m_closes) < 30:
        return None

    # Build 5M swings once per call (cheap to compute, reused per candidate)
    sh_5m, sl_5m = find_ict_swings(h5, l5)

    # Walk most-recent H4 candles first — first valid CRT setup wins
    end = n_h4 - 1
    start = max(1, n_h4 - H4_CRT_C2_LOOKBACK)

    for c2_idx in range(end, start - 1, -1):
        c1_idx = c2_idx - 1
        if c1_idx < 0:
            continue

        c1_high = h4_highs[c1_idx]
        c1_low = h4_lows[c1_idx]
        c2_high = h4_highs[c2_idx]
        c2_low = h4_lows[c2_idx]
        c2_time = h4_times[c2_idx]

        # Mitigation check (one-shot per C1 range)
        key = (c1_idx, round(c1_high, 6), round(c1_low, 6))
        if key in consumed:
            continue

        # ── Bullish CRT (SSL sweep of C1.low) ────────────────────────────
        if c2_low < c1_low:
            sweep_5m_idx = _find_5m_bar_after(c5m_times, c2_time)
            if sweep_5m_idx < 0:
                continue
            mss_confirmed = detect_ict_mss(
                sweep_bar=sweep_5m_idx,
                closes=c5m_closes,
                sh=sh_5m,
                sl=sl_5m,
                sweep_type="SSL",
                horizon=H4_CRT_MSS_HORIZON,
            )
            if not mss_confirmed:
                continue
            mss_bar = _approx_mss_bar(
                sweep_5m_idx, c5m_closes, sh_5m, sl_5m,
                "SSL", H4_CRT_MSS_HORIZON,
            )
            if mss_bar < 0:
                continue
            confluence = _check_confluence(
                "BUY", c1_high, c1_low, mss_bar, c4h, c5m,
            )
            if confluence is None:
                continue
            return {
                "source":        "H4_CRT",
                "type":          "SSL_CRT",
                "direction":     "BUY",
                "c1_idx":        c1_idx,
                "c1_high":       round(c1_high, 6),
                "c1_low":        round(c1_low, 6),
                "c2_idx":        c2_idx,
                "c2_time":       c2_time,
                "sweep_wick":    round(c2_low, 6),
                "sweep_5m_idx":  sweep_5m_idx,
                "mss_bar_5m":    mss_bar,
                "confluence":    confluence,
                "tp1":           round(c1_high, 6),
                "sl":            round(c2_low, 6),
                "key":           key,
            }

        # ── Bearish CRT (BSL sweep of C1.high) ───────────────────────────
        if c2_high > c1_high:
            sweep_5m_idx = _find_5m_bar_after(c5m_times, c2_time)
            if sweep_5m_idx < 0:
                continue
            mss_confirmed = detect_ict_mss(
                sweep_bar=sweep_5m_idx,
                closes=c5m_closes,
                sh=sh_5m,
                sl=sl_5m,
                sweep_type="BSL",
                horizon=H4_CRT_MSS_HORIZON,
            )
            if not mss_confirmed:
                continue
            mss_bar = _approx_mss_bar(
                sweep_5m_idx, c5m_closes, sh_5m, sl_5m,
                "BSL", H4_CRT_MSS_HORIZON,
            )
            if mss_bar < 0:
                continue
            confluence = _check_confluence(
                "SELL", c1_high, c1_low, mss_bar, c4h, c5m,
            )
            if confluence is None:
                continue
            return {
                "source":        "H4_CRT",
                "type":          "BSL_CRT",
                "direction":     "SELL",
                "c1_idx":        c1_idx,
                "c1_high":       round(c1_high, 6),
                "c1_low":        round(c1_low, 6),
                "c2_idx":        c2_idx,
                "c2_time":       c2_time,
                "sweep_wick":    round(c2_high, 6),
                "sweep_5m_idx":  sweep_5m_idx,
                "mss_bar_5m":    mss_bar,
                "confluence":    confluence,
                "tp1":           round(c1_low, 6),
                "sl":            round(c2_high, 6),
                "key":           key,
            }

    return None
