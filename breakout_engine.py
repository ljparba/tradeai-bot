"""
breakout_engine.py — H4 Candle Range Breakout / Continuation detector.

PHASE C-BREAKOUT — INVERSE of the existing CRT fade thesis in crt_engine.py.

CRT fade (existing, ACTIVE in soak):
    C2.low  < C1.low  → BUY  (expect reversal back UP into C1's range)
    C2.high > C1.high → SELL (expect reversal back DOWN into C1's range)

Breakout / continuation (THIS MODULE):
    C2.close < C1.low  - buffer → SELL (continuation DOWN with the break)
    C2.close > C1.high + buffer → BUY  (continuation UP with the break)

Critical differences vs detect_h4_crt:
  1. Direction mapping is INVERTED — we trade WITH the break, not against it.
  2. Trigger is C2's CLOSE (not just the wick). The fade engine accepts a
     wick-only sweep ("flexible" school); breakout requires the break to be
     committed by close.
  3. The 5M MSS must be a CONTINUATION shift in the SAME direction as the H4
     break — for a SELL breakdown we need a BSL-style MSS on 5M (close below
     a prior swing low → market structure shift DOWN). For a BUY breakout we
     need a SSL-style MSS (close above a prior swing high → structure shift UP).
     This is the OPPOSITE mapping from the fade engine (which uses BSL on H4
     sweep-high → BUY MSS waiting for reversal).
  4. Confluence (FVG or OB) is required in the BREAKOUT direction at the
     entry site — institutional defense of the new trend, not a retracement
     reversal zone.
  5. SL is placed back INSIDE C1's range (broken level acts as new S/R). For
     a BUY breakout, SL = C1.high - buffer (or wider of mid-of-C1 + buffer).
     For a SELL breakdown, SL = C1.low + buffer.
  6. TP cascade is FIXED R-multiples (no C1-opposite cap). Breakouts need
     room to run; capping at the opposite extreme would defeat the thesis.

What is reused VERBATIM from existing modules (per §1 of the C-BREAKOUT prompt):
  - find_ict_swings    (ict_engine.py)
  - score_ict_mss      (ict_engine.py) — with sweep_type INVERTED per direction
  - score_ict_fvg      (ict_engine.py)
  - detect_ict_order_block + order_block_overlaps_range (ict_engine.py)
  - compute_crt_trade_economics (crt_engine.py) — the economics gates are
    direction-agnostic; fees_kill + MAX_SL_PCT + breakeven_wr work for both.
  - compute_ote_overlay (crt_engine.py) — tag-only Fibonacci retrace zone.
  - dual-extreme sweep skip — same chaos guard as fade engine.
  - consumed-zone mitigation — one-shot per (c1_time, high, low) key.

Operator gates that are EXPLICITLY OMITTED for this fresh-thesis re-validation:
  - Wyckoff phase filter (off by default in the live config anyway).
  - Quality gates (CRT_APPLY_QUALITY_GATES — empirically harmful for fade).
  - Funding-rate / BTC-correlation overlays (live confidence bonuses — would
    contaminate the fresh expectancy measurement). These can be reintroduced
    post-validation if the raw thesis shows edge.
  - Adaptive / OGD scoring — explicitly OFF per §0 + §2.

H6 isolation invariant: this module IMPORTS from ict_engine + crt_engine but
DOES NOT modify them. The fade engine continues to run unchanged in the soak.

Env-overridable constants (read at import):
  H4_BREAKOUT_C2_LOOKBACK       — H4 bars to scan back for C1 candidate (default 8)
  H4_BREAKOUT_CLOSE_BUFFER_PCT  — buffer beyond C1 level for break confirm (default 0.0)
  H4_BREAKOUT_MSS_HORIZON       — 5M bars for continuation MSS detect (default 30)
  H4_BREAKOUT_OB_SCAN_LOOKBACK  — bars for H4 OB scan (default 20)
  BREAKOUT_TP1_RR / TP2_RR / TP3_RR — fixed R cascade (default 1.5 / 2.5 / 3.5)
  BREAKOUT_SL_INSIDE_BUFFER_PCT — buffer for SL placement inside C1 (default 0.001)
"""
import bisect as _bisect
import os as _os
from typing import Optional

from ict_engine import (
    find_ict_swings,
    score_ict_mss,
    score_ict_fvg,
    detect_ict_order_block,
    order_block_overlaps_range,
    ICT_MIN_RR_GATE,
    MAX_BREAKEVEN_WR,
)
from config import MIN_SL_PCT, MAX_SL_PCT


def _env_int(name: str, default: int) -> int:
    try:
        return int(_os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_os.environ[name])
    except (KeyError, ValueError):
        return default


# ── Module constants (env-overridable) ──────────────────────────────────────
H4_BREAKOUT_C2_LOOKBACK       = _env_int("H4_BREAKOUT_C2_LOOKBACK", 8)
H4_BREAKOUT_CLOSE_BUFFER_PCT  = _env_float("H4_BREAKOUT_CLOSE_BUFFER_PCT", 0.0)
H4_BREAKOUT_MSS_HORIZON       = _env_int("H4_BREAKOUT_MSS_HORIZON", 30)
H4_BREAKOUT_OB_SCAN_LOOKBACK  = _env_int("H4_BREAKOUT_OB_SCAN_LOOKBACK", 20)
H4_BREAKOUT_FVG_PROBE_WIDTH   = _env_int("H4_BREAKOUT_FVG_PROBE_WIDTH", 3)

BREAKOUT_TP1_RR               = _env_float("BREAKOUT_TP1_RR", 1.5)
BREAKOUT_TP2_RR               = _env_float("BREAKOUT_TP2_RR", 2.5)
BREAKOUT_TP3_RR               = _env_float("BREAKOUT_TP3_RR", 3.5)

# SL placement: distance INSIDE C1's broken level. Default 0.1% — leaves the
# stop just inside the level so a re-break of the broken level invalidates.
BREAKOUT_SL_INSIDE_BUFFER_PCT = _env_float("BREAKOUT_SL_INSIDE_BUFFER_PCT", 0.001)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _find_5m_bar_after(c5m_times, target_time) -> int:
    """Index of the first 5M bar whose timestamp > target_time, or -1."""
    n = len(c5m_times)
    if n == 0:
        return -1
    idx = _bisect.bisect_right(c5m_times, target_time)
    return idx if idx < n else -1


def _check_breakout_confluence(direction: str,
                                c1_high: float, c1_low: float,
                                entry_zone_high: float, entry_zone_low: float,
                                mss_bar_5m: int, c5m: dict, ob_cached,
                                sweep_5m_idx: int = -1):
    """Return a confluence dict if EITHER an FVG OR an OB supports the
    BREAKOUT in `direction`. Otherwise None.

    Breakout confluence semantics (opposite of fade):
      - For a BUY breakout (price broke ABOVE C1.high), we want demand-side
        evidence: a BUY-direction FVG at/near the entry (institutional gap
        UP), or a BULLISH OB sitting below the entry (last bearish candle
        before the bullish displacement leg → demand zone defending the new
        uptrend on retest).
      - For a SELL breakdown, mirror — SELL-direction FVG near entry, or
        BEARISH OB above the entry.

    Probe zone for FVG/OB overlap is the BREAKOUT side of C1:
      BUY  breakout → zone is ABOVE c1_high (the new continuation territory)
      SELL breakdown → zone is BELOW c1_low

    Args:
        entry_zone_high / entry_zone_low: bounds of the "continuation zone"
            (above c1_high for BUY, below c1_low for SELL — derived by caller).
        mss_bar_5m: index of 5M continuation MSS bar within the c5m window.
        ob_cached:  pre-computed H4 OB from detect_ict_order_block.
        sweep_5m_idx: index of the first 5M bar after C2's close (pre-FVG
            guard so we don't pick up stale FVGs from before the breakout).

    Returns:
        {"type": "FVG"|"OB", "details": dict}  on confluence match
        None on no qualifying confluence
    """
    h5 = c5m["highs"]
    l5 = c5m["lows"]
    o5 = c5m["opens"]
    c5 = c5m["closes"]

    # 1. FVG confluence — probe a few bars around the MSS for displacement.
    if 0 <= mss_bar_5m < len(c5):
        _probe_start = mss_bar_5m - (H4_BREAKOUT_FVG_PROBE_WIDTH - 1)
        _probe_end_inclusive = mss_bar_5m
        for d in range(_probe_start, _probe_end_inclusive + 1):
            if d < 1 or d + 1 >= len(c5):
                continue
            # Exclude FVGs that formed BEFORE the C2 break (pre-displacement).
            if sweep_5m_idx >= 0 and d < sweep_5m_idx:
                continue
            fvg = score_ict_fvg(d, h5, l5, o5, c5,
                                max_post_d_bars=H4_BREAKOUT_MSS_HORIZON)
            if fvg is None:
                continue
            # FVG direction must match BREAKOUT direction
            if fvg["direction"] != direction:
                continue
            # FVG must overlap the continuation zone (above c1_high for BUY,
            # below c1_low for SELL — leaves the broken level as the anchor).
            if not (fvg["bottom"] > entry_zone_high or fvg["top"] < entry_zone_low):
                return {"type": "FVG", "details": fvg}

    # 2. OB confluence — institutional defense block on the BREAKOUT side.
    # For BUY breakout: BULLISH OB (a bearish candle before bullish disp)
    #   sitting ABOVE c1_high (in the new territory) means there's a defense
    #   zone that will rebuy on first pullback. We accept OB whose direction
    #   matches the breakout direction AND whose zone overlaps the continuation.
    if ob_cached is not None and ob_cached["direction"] == direction:
        if order_block_overlaps_range(ob_cached, entry_zone_high, entry_zone_low):
            return {"type": "OB", "details": ob_cached}

    return None


# ── Main detection ──────────────────────────────────────────────────────────
def detect_h4_breakout(c4h: dict, c5m: dict, token: str = "",
                       consumed: Optional[set] = None) -> Optional[dict]:
    """Detect an H4 Candle Range BREAKOUT / continuation setup.

    Walks H4 candles most-recent-first looking for a C1 reference candle
    followed by a C2 that CLOSED beyond C1's range (committed break, not
    just a wick). Confirms via 5M continuation MSS in the SAME direction
    as the break + (FVG OR OB) confluence in the breakout direction.

    Args:
        c4h: dict with 'opens','highs','lows','closes','times' (>=20 H4 bars)
        c5m: dict with same keys (>=30 5M bars covering the H4 window)
        token: token symbol (passed through to caller, no blacklist here)
        consumed: set of (c1_time, round(c1_high,6), round(c1_low,6)) tuples
                  the caller passes — mutated by caller after generating a
                  signal. Same one-shot semantics as the fade engine.

    Returns:
        Setup dict on valid setup, None otherwise. Shape mirrors
        detect_h4_crt's output for caller compatibility:

        {
          "source":          "H4_BREAKOUT",
          "type":            "BSL_BREAKOUT" | "SSL_BREAKOUT",
              # BSL_BREAKOUT = price broke ABOVE C1.high (BUY direction)
              # SSL_BREAKOUT = price broke BELOW C1.low (SELL direction)
          "direction":       "BUY" | "SELL",
          "c1_idx":          int,
          "c1_high":         float,
          "c1_low":          float,
          "c2_idx":          int,
          "c2_time":         time-of-C2-open (same unit as c4h["times"]),
          "c2_close":        float,
          "broken_level":    float,   # c1_high for BUY, c1_low for SELL
          "sweep_5m_idx":    int,
          "mss_bar_5m":      int,
          "mss_quality":     "HIGH"|"MEDIUM"|"LOW",
          "confluence":      {"type": "FVG"|"OB", "details": dict},
          "sl_anchor":       float,   # the C1 level for SL calc by caller
          "key":             tuple,   # mitigation key (caller adds to consumed)
        }
    """
    if consumed is None:
        consumed = set()

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
    c5m_opens = c5m["opens"]
    h5 = c5m["highs"]
    l5 = c5m["lows"]
    if len(c5m_closes) < 30:
        return None

    # Time-unit cross-check (mirror crt_engine guard)
    try:
        if type(h4_times[0]) is not type(c5m_times[0]):
            return None
    except IndexError:
        return None

    # Build 5M swings once per call (cheap, reused per candidate)
    sh_5m, sl_5m = find_ict_swings(h5, l5)

    # Pre-compute H4 Order Block ONCE per call (mirror crt_engine pattern)
    ob_cached = detect_ict_order_block(
        c4h["opens"], h4_highs, h4_lows, h4_closes,
        lookback=H4_BREAKOUT_OB_SCAN_LOOKBACK,
    )

    # Walk most-recent H4 candles first — first valid breakout wins
    end = n_h4 - 1
    start = max(1, n_h4 - H4_BREAKOUT_C2_LOOKBACK)

    for c2_idx in range(end, start - 1, -1):
        c1_idx = c2_idx - 1
        if c1_idx < 0:
            continue

        c1_high = h4_highs[c1_idx]
        c1_low = h4_lows[c1_idx]
        c2_high = h4_highs[c2_idx]
        c2_low = h4_lows[c2_idx]
        c2_close = h4_closes[c2_idx]
        c2_time = h4_times[c2_idx]
        c1_time = h4_times[c1_idx]

        key = (c1_time, round(c1_high, 6), round(c1_low, 6))
        if key in consumed:
            continue

        # Dual-extreme wick — too chaotic to classify a clean break
        if c2_low < c1_low and c2_high > c1_high:
            continue

        # ── BUY breakout (C2 CLOSED above C1.high + buffer) ─────────────
        buy_threshold = c1_high * (1.0 + H4_BREAKOUT_CLOSE_BUFFER_PCT)
        if c2_close > buy_threshold:
            sweep_5m_idx = _find_5m_bar_after(c5m_times, c2_time)
            if sweep_5m_idx < 0:
                continue
            # CONTINUATION MSS: for a BUY breakout we want a 5M structure
            # shift UP, which is what score_ict_mss returns when sweep_type
            # == "SSL" (it looks for closes ABOVE a recent swing high). The
            # *name* "SSL" is from the fade engine's perspective (a sweep
            # of SSL → BUY reversal); here we reuse the same predicate for
            # CONTINUATION confirmation (close above a recent swing high).
            mss = score_ict_mss(
                sweep_bar=sweep_5m_idx,
                closes=c5m_closes,
                opens=c5m_opens,
                highs=h5,
                lows=l5,
                sh=sh_5m,
                sl=sl_5m,
                sweep_type="SSL",  # continuation UP confirmer
                horizon=H4_BREAKOUT_MSS_HORIZON,
            )
            if not mss["confirmed"]:
                continue
            mss_bar = mss["mss_bar"]
            # Continuation zone = above c1_high (where price is now running)
            confluence = _check_breakout_confluence(
                "BUY", c1_high, c1_low,
                entry_zone_high=c1_high * 1.02,   # a 2% headroom band above broken level
                entry_zone_low=c1_high,
                mss_bar_5m=mss_bar, c5m=c5m, ob_cached=ob_cached,
                sweep_5m_idx=sweep_5m_idx,
            )
            if confluence is None:
                continue
            return {
                "source":        "H4_BREAKOUT",
                "type":          "BSL_BREAKOUT",
                "direction":     "BUY",
                "c1_idx":        c1_idx,
                "c1_high":       round(c1_high, 6),
                "c1_low":        round(c1_low, 6),
                "c2_idx":        c2_idx,
                "c2_time":       c2_time,
                "c2_close":      round(c2_close, 6),
                "broken_level":  round(c1_high, 6),
                "sweep_5m_idx":  sweep_5m_idx,
                "mss_bar_5m":    mss_bar,
                "mss_quality":   mss["quality"],
                "confluence":    confluence,
                "sl_anchor":     round(c1_high, 6),
                "key":           key,
            }

        # ── SELL breakdown (C2 CLOSED below C1.low - buffer) ────────────
        sell_threshold = c1_low * (1.0 - H4_BREAKOUT_CLOSE_BUFFER_PCT)
        if c2_close < sell_threshold:
            sweep_5m_idx = _find_5m_bar_after(c5m_times, c2_time)
            if sweep_5m_idx < 0:
                continue
            # CONTINUATION MSS DOWN — close below a recent swing low. In
            # score_ict_mss's vocabulary that's sweep_type="BSL" (the helper
            # returns confirmed when closes[j] < mss_level, which is a
            # bearish CHoCH).
            mss = score_ict_mss(
                sweep_bar=sweep_5m_idx,
                closes=c5m_closes,
                opens=c5m_opens,
                highs=h5,
                lows=l5,
                sh=sh_5m,
                sl=sl_5m,
                sweep_type="BSL",  # continuation DOWN confirmer
                horizon=H4_BREAKOUT_MSS_HORIZON,
            )
            if not mss["confirmed"]:
                continue
            mss_bar = mss["mss_bar"]
            confluence = _check_breakout_confluence(
                "SELL", c1_high, c1_low,
                entry_zone_high=c1_low,
                entry_zone_low=c1_low * 0.98,   # 2% band below broken level
                mss_bar_5m=mss_bar, c5m=c5m, ob_cached=ob_cached,
                sweep_5m_idx=sweep_5m_idx,
            )
            if confluence is None:
                continue
            return {
                "source":        "H4_BREAKOUT",
                "type":          "SSL_BREAKOUT",
                "direction":     "SELL",
                "c1_idx":        c1_idx,
                "c1_high":       round(c1_high, 6),
                "c1_low":        round(c1_low, 6),
                "c2_idx":        c2_idx,
                "c2_time":       c2_time,
                "c2_close":      round(c2_close, 6),
                "broken_level":  round(c1_low, 6),
                "sweep_5m_idx":  sweep_5m_idx,
                "mss_bar_5m":    mss_bar,
                "mss_quality":   mss["quality"],
                "confluence":    confluence,
                "sl_anchor":     round(c1_low, 6),
                "key":           key,
            }

    return None


# ── Trade economics — fixed R cascade (no C1-opposite cap) ──────────────────
def compute_breakout_sl_tp(direction: str, entry_price: float,
                           sl_anchor: float, c1_high: float, c1_low: float):
    """Compute SL + TP1/TP2/TP3 prices for a breakout setup.

    SL placement (back inside the broken level):
      BUY  breakout (broke above c1_high): SL = c1_high * (1 - buffer)
      SELL breakdown (broke below c1_low): SL = c1_low  * (1 + buffer)

    The buffer pushes the stop a small distance INSIDE the broken level so a
    clean re-break (back below c1_high for a BUY, back above c1_low for SELL)
    invalidates and exits. Subject to MIN_SL_PCT floor and MAX_SL_PCT ceiling
    — if the structural SL would be too tight we widen to the floor; if too
    wide we return None (caller skips).

    TP cascade: FIXED R-multiples from entry, no liquidity-pool cap. Breakouts
    need room; capping at C1's opposite extreme defeats the thesis.

    Returns (sl_price, tp1_price, tp2_price, tp3_price) or None on bad geometry.
    """
    if direction == "BUY":
        # Structural SL just below the broken level
        sl_struct = sl_anchor * (1.0 - BREAKOUT_SL_INSIDE_BUFFER_PCT)
        # Apply MIN_SL_PCT floor (widen SL if too tight)
        sl = min(sl_struct, entry_price * (1.0 - MIN_SL_PCT))
        if sl <= 0:
            return None
        sl_pct = (entry_price - sl) / entry_price
        if sl_pct > MAX_SL_PCT:
            return None
        risk_dist = entry_price - sl
        tp1 = entry_price + BREAKOUT_TP1_RR * risk_dist
        tp2 = entry_price + BREAKOUT_TP2_RR * risk_dist
        tp3 = entry_price + BREAKOUT_TP3_RR * risk_dist
    elif direction == "SELL":
        sl_struct = sl_anchor * (1.0 + BREAKOUT_SL_INSIDE_BUFFER_PCT)
        sl = max(sl_struct, entry_price * (1.0 + MIN_SL_PCT))
        sl_pct = (sl - entry_price) / entry_price
        if sl_pct > MAX_SL_PCT:
            return None
        risk_dist = sl - entry_price
        tp1 = entry_price - BREAKOUT_TP1_RR * risk_dist
        tp2 = entry_price - BREAKOUT_TP2_RR * risk_dist
        tp3 = entry_price - BREAKOUT_TP3_RR * risk_dist
    else:
        return None

    return (sl, tp1, tp2, tp3)
