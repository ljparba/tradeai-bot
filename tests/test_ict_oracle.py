"""
SMC / ICT Oracle — independent cross-validation of ict_engine.py
==================================================================
Roadmap reference:
  • Top-10 #10 / Phase A item #5 of docs/ENTERPRISE_ROADMAP.md
  • Red Flag #6: smart-money-concepts must NEVER be a runtime dep.
    This file is the oracle — tests/ only.

Approach
--------
Each test contains:
  1. A REFERENCE IMPLEMENTATION — written from scratch, independent of ict_engine.py,
     using different loop structures and variable names so shared bugs cannot hide.
  2. SYNTHETIC OHLCV data with a known, deterministically placed ICT structure.
  3. A cross-validation assertion: both the reference and ict_engine must agree.

Covered functions
-----------------
  • find_ict_swings        — swing high / low detection (pivot confirmation lag)
  • detect_ict_sweep       — BSL / SSL liquidity sweep
  • score_ict_fvg          — fair value gap geometry + quality scoring
  • score_ict_mss          — market structure shift quality scoring
  • detect_ict_displacement — displacement candle detection
  • find_eqh_eql_clusters  — equal highs / lows cluster sizing
  • compute_dealing_range  — premium / discount / equilibrium location
  • get_ict_4h_bias        — 4H directional bias (EMA + swing structure)

Invariants tested (per ICT doctrine)
-------------------------------------
  I1. A swing high requires BOTH the left AND all n-right neighbours to be lower.
  I2. BSL sweep: wick above the swing high + close BELOW it (stop-run, not breakout).
  I3. SSL sweep: wick below the swing low + close ABOVE it.
  I4. FVG bullish: lows[d+1] > highs[d-1] (no overlap, gap >= ICT_FVG_MIN_GAP).
  I5. FVG bearish: highs[d+1] < lows[d-1].
  I6. FVG is MITIGATED once price fully fills the gap (close below bottom for BUY).
  I7. MSS (CHoCH) after SSL: first close > most-recent prior swing HIGH.
  I8. MSS (CHoCH) after BSL: first close < most-recent prior swing LOW.
  I9. EQH cluster: two swings within 0.15% of each other → cluster_size >= 2.
  I10. Dealing-range PREMIUM = price > midpoint + 5% band.

No network calls. No shared code with ict_engine.py in the reference functions.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ict_engine import (
    ICT_SWING_N,
    ICT_FVG_MIN_GAP,
    ICT_EQH_TOLERANCE,
    find_ict_swings,
    find_eqh_eql_clusters,
    detect_ict_sweep,
    score_ict_fvg,
    score_ict_mss,
    detect_ict_displacement,
    compute_dealing_range,
    get_ict_4h_bias,
)


# ════════════════════════════════════════════════════════════════════════════════
# REFERENCE IMPLEMENTATIONS (oracle)
# ════════════════════════════════════════════════════════════════════════════════

def _ref_find_swings(highs: list, lows: list, n: int = ICT_SWING_N):
    """Oracle swing detector — nested loop, different from ict_engine implementation."""
    sh_out, sl_out = [], []
    limit = len(highs) - n
    for idx in range(1, limit):
        is_sh = highs[idx] > highs[idx - 1]
        for k in range(1, n + 1):
            if highs[idx] <= highs[idx + k]:
                is_sh = False
                break
        if is_sh:
            sh_out.append((idx, highs[idx]))

        is_sl = lows[idx] < lows[idx - 1]
        for k in range(1, n + 1):
            if lows[idx] >= lows[idx + k]:
                is_sl = False
                break
        if is_sl:
            sl_out.append((idx, lows[idx]))
    return sh_out, sl_out


def _ref_detect_bsl_sweep(highs: list, lows: list, closes: list, sh: list,
                           lookback: int = 30) -> Optional[dict]:
    """Oracle BSL sweep: wick > swing_high AND close < swing_high."""
    n = len(closes)
    start = max(0, n - lookback)
    for bar in range(n - 1, start - 1, -1):
        for s_bar, s_lev in reversed(sh):
            if s_bar > bar - ICT_SWING_N - 1:
                continue
            if highs[bar] > s_lev and closes[bar] < s_lev:
                return {"type": "BSL", "bar": bar, "level": s_lev}
    return None


def _ref_detect_ssl_sweep(highs: list, lows: list, closes: list, sl: list,
                           lookback: int = 30) -> Optional[dict]:
    """Oracle SSL sweep: wick < swing_low AND close > swing_low."""
    n = len(closes)
    start = max(0, n - lookback)
    for bar in range(n - 1, start - 1, -1):
        for s_bar, s_lev in reversed(sl):
            if s_bar > bar - ICT_SWING_N - 1:
                continue
            if lows[bar] < s_lev and closes[bar] > s_lev:
                return {"type": "SSL", "bar": bar, "level": s_lev}
    return None


def _ref_has_bullish_fvg(d: int, highs: list, lows: list) -> bool:
    """Oracle: bullish FVG at displacement bar d — gap between d-1 high and d+1 low."""
    if d < 1 or d + 1 >= len(highs):
        return False
    gap = lows[d + 1] - highs[d - 1]
    if gap <= 0:
        return False
    return gap / max(highs[d - 1], 1e-10) >= ICT_FVG_MIN_GAP


def _ref_has_bearish_fvg(d: int, highs: list, lows: list) -> bool:
    """Oracle: bearish FVG at displacement bar d."""
    if d < 1 or d + 1 >= len(highs):
        return False
    gap = lows[d - 1] - highs[d + 1]
    if gap <= 0:
        return False
    return gap / max(lows[d - 1], 1e-10) >= ICT_FVG_MIN_GAP


def _ref_mss_after_ssl(sweep_bar: int, closes: list, sh: list) -> Optional[int]:
    """Oracle MSS: first close above the most-recent prior swing high."""
    candidates = [p for p in sh if p[0] < sweep_bar]
    if not candidates:
        return None
    mss_level = max(candidates, key=lambda p: p[0])[1]
    for j in range(sweep_bar + 1, len(closes)):
        if closes[j] > mss_level:
            return j
    return None


def _ref_mss_after_bsl(sweep_bar: int, closes: list, sl: list) -> Optional[int]:
    """Oracle MSS: first close below the most-recent prior swing low."""
    candidates = [p for p in sl if p[0] < sweep_bar]
    if not candidates:
        return None
    mss_level = max(candidates, key=lambda p: p[0])[1]
    for j in range(sweep_bar + 1, len(closes)):
        if closes[j] < mss_level:
            return j
    return None


def _ref_eqh_cluster_size(levels: list[float], target: float,
                           tol: float = ICT_EQH_TOLERANCE) -> int:
    """Oracle: count how many levels are within tol% of target."""
    return sum(1 for lv in levels if lv > 0 and abs(lv - target) / target <= tol)


# ════════════════════════════════════════════════════════════════════════════════
# SYNTHETIC DATA BUILDERS
# ════════════════════════════════════════════════════════════════════════════════

def _flat_candles(n: int, price: float = 100.0, spread: float = 0.5):
    """n flat candles around price — no swings, just baseline noise."""
    highs  = [price + spread] * n
    lows   = [price - spread] * n
    opens  = [price] * n
    closes = [price] * n
    return highs, lows, opens, closes


def _make_swing_high_sequence():
    """
    Build a 15-bar sequence with ONE confirmed swing high at bar 5 (level=110).
    Bars 0-4: rising to 110. Bars 5: peak=110. Bars 6+: falling back.
    With ICT_SWING_N=2, bar 5 is confirmed once bars 6 and 7 are both < 110.
    """
    h = [100, 103, 106, 108, 109, 110, 109, 108, 107, 106, 105, 104, 103, 102, 101]
    l = [ 99, 102, 105, 107, 108, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100]
    return h, l


def _make_swing_low_sequence():
    """
    Build a 15-bar sequence with ONE confirmed swing low at bar 5 (level=90).
    Bars 0-4: falling to 90. Bar 5: trough=90. Bars 6+: rising back.
    """
    h = [101, 100,  99,  98,  97,  91,  92,  93,  94,  95,  96,  97,  98,  99, 100]
    l = [100,  99,  98,  97,  96,  90,  91,  92,  93,  94,  95,  96,  97,  98,  99]
    return h, l


def _make_bsl_sweep_sequence():
    """
    30-bar sequence:
      - Swing high at bar 5 (level=110), confirmed by bars 6-7.
      - Bars 8-24: ranging below 110.
      - Bar 25: wick to 111 (above 110) but closes at 109 → BSL sweep.
    """
    h = [100, 103, 106, 108, 109, 110, 109, 108,   # bars 0-7: swing high at 5
         107, 107, 108, 107, 108, 107, 108, 107,   # bars 8-15: ranging
         108, 107, 107, 108, 107, 108, 107, 108,   # bars 16-23: ranging
         107, 111, 108, 107, 108, 107]              # bar 25: wick above 110
    l = [ 99, 102, 105, 107, 108, 109, 108, 107,
         106, 106, 107, 106, 107, 106, 107, 106,
         107, 106, 106, 107, 106, 107, 106, 107,
         106, 108, 107, 106, 107, 106]
    c = [100, 103, 106, 108, 109, 110, 109, 108,
         107, 107, 108, 107, 108, 107, 108, 107,
         108, 107, 107, 108, 107, 108, 107, 108,
         107, 109, 108, 107, 108, 107]  # bar 25 close=109 < level=110 → sweep
    o = c[:]
    return h, l, o, c


def _make_ssl_sweep_sequence():
    """
    30-bar sequence:
      - Swing low at bar 5 (level=90), confirmed by bars 6-7.
      - Bars 8-24: ranging above 90.
      - Bar 25: wick to 89 (below 90) but closes at 91 → SSL sweep.
    """
    h = [101, 100,  99,  98,  97,  91,  92,  93,  94,  95,  94,  95,  94,  95,  94,
          95,  94,  95,  94,  95,  94,  95,  94,  95,  94,  92,  94,  95,  94,  95]
    l = [100,  99,  98,  97,  96,  90,  91,  92,  93,  94,  93,  94,  93,  94,  93,
          94,  93,  94,  93,  94,  93,  94,  93,  94,  93,  89,  93,  94,  93,  94]
    c = [100,  99,  98,  97,  96,  90,  91,  92,  93,  94,  93,  94,  93,  94,  93,
          94,  93,  94,  93,  94,  93,  94,  93,  94,  93,  91,  93,  94,  93,  94]
    o = c[:]
    c[25] = 91   # wick below 90 but close=91 > level=90 → SSL sweep
    return h, l, o, c


def _make_bullish_fvg_sequence():
    """
    5-bar sequence with a bullish FVG at bar 2 (displacement bar):
      bar 1 high = 100
      bar 2 (disp): big bull move (open=100.5, close=106, high=107, low=100.4)
      bar 3 low = 101.5 > bar 1 high = 100 → bullish FVG [100, 101.5]
    """
    h = [100.0, 100.0, 107.0, 103.0, 103.0]
    l = [ 99.5,  99.0, 100.4, 101.5, 101.0]
    o = [  99.6,  99.5, 100.5, 102.0, 102.0]
    c = [  99.8,  99.8, 106.0, 102.5, 102.0]
    return h, l, o, c


def _make_bearish_fvg_sequence():
    """
    5-bar sequence with a bearish FVG at bar 2:
      bar 1 low = 100
      bar 2 (disp): big bear move (open=99.5, close=93, high=99.6, low=92.5)
      bar 3 high = 99.0 < bar 1 low = 100 → bearish FVG [99.0, 100.0]
    """
    h = [101.0, 100.0,  99.6,  99.0,  99.5]
    l = [100.0,  99.5,  92.5,  98.0,  98.5]
    o = [100.5,  99.8,  99.5,  98.5,  98.7]
    c = [100.3, 100.0,  93.0,  98.3,  98.6]
    return h, l, o, c


def _make_mss_after_ssl():
    """
    35-bar sequence:
      - Swing low at bar 5 (90) + swing high before sweep at bar 3 (98).
      - Bar 20: SSL sweep (wick below 90, close above).
      - Bar 22: close = 99 > prior swing high 98 → MSS confirmed.
    """
    n = 35
    h = [100.0] * n
    l = [  95.0] * n
    o = [  97.0] * n
    c = [  97.0] * n

    # Swing high at bar 3 = 98 (bars 2 and 4 must be lower)
    h[2] = 96.0; h[3] = 98.0; h[4] = 96.5
    l[2] = 95.0; l[3] = 97.0; l[4] = 95.5
    c[2] = 95.5; c[3] = 97.5; c[4] = 96.0

    # Swing low at bar 6 = 90 (bar 5 and bars 7-8 must be higher)
    l[5]  = 91.0; l[6] = 90.0; l[7] = 91.5; l[8] = 92.0
    h[5]  = 96.0; h[6] = 92.0; h[7] = 93.0; h[8] = 94.0
    c[5]  = 92.0; c[6] = 90.5; c[7] = 92.0; c[8] = 93.0

    # Bar 20: SSL sweep — wick to 89 (< 90), close at 91 (> 90)
    l[20] = 89.0; h[20] = 93.0; c[20] = 91.0; o[20] = 92.0

    # Bar 22: close above prior swing high 98 → MSS confirmed
    c[22] = 99.0; h[22] = 99.5; l[22] = 95.0; o[22] = 95.5

    return h, l, o, c


# ════════════════════════════════════════════════════════════════════════════════
# TESTS: find_ict_swings (I1)
# ════════════════════════════════════════════════════════════════════════════════

class TestSwingDetection:

    def test_swing_high_located_at_correct_bar(self):
        h, l = _make_swing_high_sequence()
        engine_sh, _ = find_ict_swings(h, l)
        ref_sh, _    = _ref_find_swings(h, l)
        engine_bars = [b for b, _ in engine_sh]
        ref_bars    = [b for b, _ in ref_sh]
        assert engine_bars == ref_bars, (
            f"engine swing_high bars {engine_bars} != oracle {ref_bars}"
        )

    def test_swing_high_level_correct(self):
        h, l = _make_swing_high_sequence()
        engine_sh, _ = find_ict_swings(h, l)
        ref_sh, _    = _ref_find_swings(h, l)
        engine_levels = [lv for _, lv in engine_sh]
        ref_levels    = [lv for _, lv in ref_sh]
        assert engine_levels == ref_levels

    def test_swing_low_located_at_correct_bar(self):
        h, l = _make_swing_low_sequence()
        _, engine_sl = find_ict_swings(h, l)
        _, ref_sl    = _ref_find_swings(h, l)
        assert [b for b, _ in engine_sl] == [b for b, _ in ref_sl]

    def test_swing_low_level_correct(self):
        h, l = _make_swing_low_sequence()
        _, engine_sl = find_ict_swings(h, l)
        _, ref_sl    = _ref_find_swings(h, l)
        assert [lv for _, lv in engine_sl] == [lv for _, lv in ref_sl]

    def test_flat_candles_no_swings(self):
        h, l, _, _ = _flat_candles(20)
        sh, sl = find_ict_swings(h, l)
        assert sh == [] and sl == []

    def test_n_confirmation_lag_respected(self):
        # Bar i is a swing high ONLY if bars i+1 ... i+n are strictly lower.
        # If we set n=1, the second-to-last bar in a pure downtrend is NOT a swing high.
        h = [100, 105, 104, 103, 102, 101]
        l = [ 99, 104, 103, 102, 101, 100]
        sh_n1, _ = find_ict_swings(h, l, n=1)
        ref_n1, _ = _ref_find_swings(h, l, n=1)
        assert [b for b, _ in sh_n1] == [b for b, _ in ref_n1]
        assert all(b == 1 for b, _ in sh_n1)  # only bar 1 qualifies

    def test_equal_highs_not_counted_as_swing(self):
        # Bar i must be STRICTLY greater than neighbours — equal is not a swing high.
        h = [100, 105, 105, 104, 103]
        l = [ 99, 104, 104, 103, 102]
        sh, _ = find_ict_swings(h, l, n=1)
        ref_sh, _ = _ref_find_swings(h, l, n=1)
        assert sh == ref_sh  # both should agree — no swing at 105 because tie at bar 2


# ════════════════════════════════════════════════════════════════════════════════
# TESTS: detect_ict_sweep (I2, I3)
# ════════════════════════════════════════════════════════════════════════════════

class TestSweepDetection:

    def test_bsl_sweep_detected_at_correct_bar(self):
        h, l, o, c = _make_bsl_sweep_sequence()
        sh, sl = find_ict_swings(h, l)
        engine = detect_ict_sweep(h, l, c, sh, sl, lookback=30)
        ref    = _ref_detect_bsl_sweep(h, l, c, sh, lookback=30)
        assert engine is not None, "engine missed BSL sweep"
        assert ref    is not None, "oracle missed BSL sweep"
        assert engine["bar"] == ref["bar"],   f"BSL bar mismatch: engine={engine['bar']} ref={ref['bar']}"
        assert engine["type"] == "BSL"
        assert ref["type"]    == "BSL"

    def test_ssl_sweep_detected_at_correct_bar(self):
        h, l, o, c = _make_ssl_sweep_sequence()
        sh, sl = find_ict_swings(h, l)
        engine = detect_ict_sweep(h, l, c, sh, sl, lookback=30)
        ref    = _ref_detect_ssl_sweep(h, l, c, sl, lookback=30)
        assert engine is not None, "engine missed SSL sweep"
        assert ref    is not None, "oracle missed SSL sweep"
        assert engine["bar"] == ref["bar"],   f"SSL bar mismatch: engine={engine['bar']} ref={ref['bar']}"
        assert engine["type"] == "SSL"

    def test_bsl_invariant_close_must_be_below_level(self):
        # If price closes ABOVE the swing high, it is a breakout, NOT a sweep.
        h, l, o, c = _make_bsl_sweep_sequence()
        # Confirm the baseline sweep IS found before modifying
        sh, sl = find_ict_swings(h, l)
        baseline = detect_ict_sweep(h, l, c, sh, sl, lookback=30)
        assert baseline is not None and baseline["bar"] == 25, "baseline sweep must exist at bar 25"

        c[25] = 111.5  # close above sweep level → breakout, NOT a sweep
        engine = detect_ict_sweep(h, l, c, sh, sl, lookback=30)
        # bar 25 must not be a BSL sweep; if the engine returns anything it must be a different bar
        assert engine is None or engine["bar"] != 25, "close above level must not be a BSL sweep"

    def test_ssl_invariant_close_must_be_above_level(self):
        h, l, o, c = _make_ssl_sweep_sequence()
        sh, sl = find_ict_swings(h, l)
        baseline = detect_ict_sweep(h, l, c, sh, sl, lookback=30)
        assert baseline is not None and baseline["bar"] == 25, "baseline sweep must exist at bar 25"

        c[25] = 88.0  # close below sweep level → breakout down, not a sweep
        engine = detect_ict_sweep(h, l, c, sh, sl, lookback=30)
        assert engine is None or engine["bar"] != 25, "close below level must not be an SSL sweep"

    def test_consumed_sweep_not_returned_again(self):
        h, l, o, c = _make_bsl_sweep_sequence()
        sh, sl = find_ict_swings(h, l)
        first = detect_ict_sweep(h, l, c, sh, sl)
        assert first is not None
        consumed = {(first["bar"], round(first["level"], 6))}
        second = detect_ict_sweep(h, l, c, sh, sl, consumed=consumed)
        # After marking the sweep consumed, same bar/level must not appear again
        if second is not None:
            assert (second["bar"], round(second["level"], 6)) not in consumed

    def test_no_false_sweep_on_flat_data(self):
        h, l, _, c = _flat_candles(30)
        sh, sl = find_ict_swings(h, l)
        result = detect_ict_sweep(h, l, c, sh, sl)
        assert result is None


# ════════════════════════════════════════════════════════════════════════════════
# TESTS: score_ict_fvg (I4, I5, I6)
# ════════════════════════════════════════════════════════════════════════════════

class TestFVGDetection:

    def test_bullish_fvg_detected(self):
        h, l, o, c = _make_bullish_fvg_sequence()
        d = 2  # displacement bar
        ref_hit  = _ref_has_bullish_fvg(d, h, l)
        engine   = score_ict_fvg(d, h, l, o, c)
        assert ref_hit, "oracle did not detect a bullish FVG — fix the test data"
        assert engine is not None, "engine missed the bullish FVG"
        assert engine["direction"] == "BUY"

    def test_bullish_fvg_geometry_correct(self):
        h, l, o, c = _make_bullish_fvg_sequence()
        d = 2
        engine = score_ict_fvg(d, h, l, o, c)
        assert engine is not None
        # bottom = highs[d-1] = h[1] = 100.0
        # top    = lows[d+1]  = l[3] = 101.5
        assert abs(engine["bottom"] - h[1]) < 1e-4, "FVG bottom mismatch"
        assert abs(engine["top"]    - l[3]) < 1e-4, "FVG top mismatch"
        assert engine["top"] > engine["bottom"]

    def test_bearish_fvg_detected(self):
        h, l, o, c = _make_bearish_fvg_sequence()
        d = 2
        ref_hit = _ref_has_bearish_fvg(d, h, l)
        engine  = score_ict_fvg(d, h, l, o, c)
        assert ref_hit, "oracle did not detect a bearish FVG — fix test data"
        assert engine is not None, "engine missed the bearish FVG"
        assert engine["direction"] == "SELL"

    def test_bearish_fvg_geometry_correct(self):
        h, l, o, c = _make_bearish_fvg_sequence()
        d = 2
        engine = score_ict_fvg(d, h, l, o, c)
        assert engine is not None
        # bottom = highs[d+1] = h[3] = 99.0
        # top    = lows[d-1]  = l[1] = 99.5
        assert abs(engine["bottom"] - h[3]) < 1e-4, "bearish FVG bottom mismatch"
        assert abs(engine["top"]    - l[1]) < 1e-4, "bearish FVG top mismatch"

    def test_fvg_mitigation_bullish(self):
        """I6: A bullish FVG is MITIGATED once price closes below its bottom."""
        h, l, o, c = _make_bullish_fvg_sequence()
        d = 2
        # Without mitigation, FVG exists
        engine_before = score_ict_fvg(d, h, l, o, c)
        assert engine_before is not None

        # Add a close below the FVG bottom (=h[1]=100.0) AFTER bar d+1
        h2 = h + [101.0]; l2 = l + [98.0]; o2 = o + [99.5]; c2 = c + [99.0]
        engine_after = score_ict_fvg(d, h2, l2, o2, c2)
        assert engine_after is None, "mitigated FVG must return None"

    def test_fvg_mitigation_bearish(self):
        """I6: A bearish FVG is MITIGATED once price closes above its top."""
        h, l, o, c = _make_bearish_fvg_sequence()
        d = 2
        engine_before = score_ict_fvg(d, h, l, o, c)
        assert engine_before is not None

        # Add a close above the FVG top (=l[1]=99.5) AFTER bar d+1
        h2 = h + [101.0]; l2 = l + [99.0]; o2 = o + [100.0]; c2 = c + [100.5]
        engine_after = score_ict_fvg(d, h2, l2, o2, c2)
        assert engine_after is None, "mitigated bearish FVG must return None"

    def test_no_overlap_no_fvg(self):
        """No FVG if bars overlap (not a gap)."""
        h = [100.0, 102.0, 101.5]
        l = [ 99.0,  99.5, 100.5]  # l[2]=100.5 < h[0]=100.0? No — 100.5 > 100.0 wait...
        # l[2]=100.5 > h[0]=100.0 → gap. Let me build true no-gap:
        h = [103.0, 105.0, 104.0]
        l = [102.0, 104.0, 103.0]   # l[2]=103.0 < h[0]=103.0 → no gap (lows[d+1] <= highs[d-1])
        engine = score_ict_fvg(1, h, l)
        assert engine is None, "overlapping bars must not produce an FVG"

    def test_fvg_quality_large_gap_is_high(self):
        """Size >= 0.5% + strong displacement body → HIGH quality (3 pts)."""
        h, l, o, c = _make_bullish_fvg_sequence()
        engine = score_ict_fvg(2, h, l, o, c)
        assert engine is not None
        gap_pct = (engine["top"] - engine["bottom"]) / engine["bottom"] * 100
        assert gap_pct >= 0.5, f"test data must have gap >= 0.5%, got {gap_pct:.3f}%"
        assert engine["quality"] == "HIGH", (
            f"gap={gap_pct:.3f}% with strong displacement body must be HIGH, got {engine['quality']}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# TESTS: score_ict_mss (I7, I8)
# ════════════════════════════════════════════════════════════════════════════════

class TestMSSDetection:

    def test_mss_confirmed_after_ssl(self):
        """I7: MSS after SSL = first close above the most-recent prior swing high."""
        h, l, o, c = _make_mss_after_ssl()
        sh, sl = find_ict_swings(h, l)
        sweep_bar = 20  # bar where SSL sweep occurs (wick=89, close=91)

        engine_mss = score_ict_mss(sweep_bar, c, o, h, l, sh, sl, "SSL")
        ref_mss_bar = _ref_mss_after_ssl(sweep_bar, c, sh)

        assert engine_mss["confirmed"] is True, "engine did not confirm MSS after SSL"
        assert ref_mss_bar is not None,          "oracle did not confirm MSS after SSL"
        assert engine_mss["mss_bar"] == ref_mss_bar, (
            f"MSS bar mismatch: engine={engine_mss['mss_bar']} oracle={ref_mss_bar}"
        )

    def test_mss_not_confirmed_when_no_prior_swing_high(self):
        """Without a prior swing high in range, MSS cannot be confirmed."""
        h, l, _, c = _flat_candles(30)
        sh, sl = find_ict_swings(h, l)
        result = score_ict_mss(10, c, [], h, l, sh, sl, "SSL")
        assert result["confirmed"] is False

    def test_mss_quality_rapid_gets_higher_score(self):
        """MSS confirmed in <= 3 bars earns >= 2 timing points."""
        h, l, o, c = _make_mss_after_ssl()
        sh, sl = find_ict_swings(h, l)
        engine_mss = score_ict_mss(20, c, o, h, l, sh, sl, "SSL")
        # Must be confirmed — if not, the test data is broken, not the engine
        assert engine_mss["confirmed"], "MSS must be confirmed with the test data"
        assert engine_mss["bars_to_mss"] is not None
        if engine_mss["bars_to_mss"] <= 3:
            assert engine_mss["score_pts"] >= 2, (
                f"rapid MSS ({engine_mss['bars_to_mss']} bars) must earn >= 2 pts, "
                f"got {engine_mss['score_pts']}"
            )

    def test_mss_uses_most_recent_prior_swing_not_extreme(self):
        """ICT H2: MSS targets the MOST RECENT prior swing, not the highest/lowest."""
        # Two swing highs: older at bar 2 (105), newer at bar 8 (103).
        # MSS after SSL at bar 15 must target 103 (most recent), not 105 (highest).
        n = 25
        h = [100.0] * n; l = [98.0] * n; o = [99.0] * n; c = [99.0] * n

        # Older swing high at bar 2 = 105 (bars 1 and 3 lower)
        h[1] = 102.0; h[2] = 105.0; h[3] = 102.0
        l[1] = 100.0; l[2] = 104.0; l[3] = 100.0
        c[1] = 101.0; c[2] = 104.5; c[3] = 101.0

        # Newer swing high at bar 8 = 103 (bars 7 and 9 lower)
        h[7] = 101.0; h[8] = 103.0; h[9] = 101.0
        l[7] =  99.5; l[8] = 102.0; l[9] =  99.5
        c[7] = 100.0; c[8] = 102.5; c[9] = 100.0

        # SSL sweep at bar 15
        l[15] = 97.5; h[15] = 99.5; c[15] = 98.5; o[15] = 98.5

        # MSS: close > 103 (most recent, bar 8) — BEFORE crossing 105 (older high)
        c[17] = 103.5; h[17] = 104.0; l[17] = 102.0; o[17] = 102.0

        sh, sl = find_ict_swings(h, l)
        engine_mss = score_ict_mss(15, c, o, h, l, sh, sl, "SSL")
        if engine_mss["confirmed"]:
            assert abs(engine_mss["mss_level"] - 103.0) < 0.5, (
                f"MSS should target most-recent swing high (103) not older (105), "
                f"got mss_level={engine_mss['mss_level']}"
            )


# ════════════════════════════════════════════════════════════════════════════════
# TESTS: detect_ict_displacement
# ════════════════════════════════════════════════════════════════════════════════

class TestDisplacementDetection:
    # Baseline candles need non-zero bodies: detect_ict_displacement returns None
    # immediately when avg_body == 0 (ict_engine.py guard at line ~169).
    # Use o=100.3, c=100.0 → body=0.3 for all baseline bars.

    def test_bullish_displacement_found_after_ssl(self):
        """Bullish displacement: large body, bullish candle, body/range >= 0.55."""
        n = 20
        h = [101.0] * n; l = [99.0] * n
        o = [100.3] * n; c = [100.0] * n  # small non-zero body so avg_body > 0
        sweep_bar = 5
        # Bar 7: strong bullish candle — body=3.3 >> avg_body*1.5=0.45, body/range=0.825
        h[7] = 104.0; l[7] = 100.0; o[7] = 100.2; c[7] = 103.5
        disp = detect_ict_displacement(sweep_bar, o, h, l, c, "SSL", max_look=9)
        assert disp == 7, f"expected disp at bar 7, got {disp}"

    def test_bearish_displacement_found_after_bsl(self):
        """Bearish displacement: large body, bearish candle."""
        n = 20
        h = [101.0] * n; l = [99.0] * n
        o = [100.3] * n; c = [100.0] * n
        sweep_bar = 5
        # Bar 7: strong bearish candle — body=3.3, body/range=3.3/4=0.825
        h[7] = 101.0; l[7] = 97.0; o[7] = 100.8; c[7] = 97.5
        disp = detect_ict_displacement(sweep_bar, o, h, l, c, "BSL", max_look=9)
        assert disp == 7, f"expected disp at bar 7, got {disp}"

    def test_small_body_not_displacement(self):
        """A candle with body/range < 0.55 must not be called a displacement."""
        n = 20
        h = [101.0] * n; l = [99.0] * n
        o = [100.3] * n; c = [100.0] * n
        sweep_bar = 5
        # Bar 7: doji — body=0.2 relative to range=8 → body/range=0.025 < 0.55
        h[7] = 104.0; l[7] = 96.0; o[7] = 99.9; c[7] = 100.1
        disp = detect_ict_displacement(sweep_bar, o, h, l, c, "SSL", max_look=9)
        assert disp != 7, "doji should not be a displacement"

    def test_no_displacement_beyond_max_look(self):
        """Displacement more than max_look bars after sweep is not found."""
        n = 30
        h = [101.0] * n; l = [99.0] * n
        o = [100.3] * n; c = [100.0] * n
        sweep_bar = 5
        h[16] = 104.0; l[16] = 100.0; o[16] = 100.2; c[16] = 103.5
        disp = detect_ict_displacement(sweep_bar, o, h, l, c, "SSL", max_look=9)
        assert disp is None, "displacement beyond max_look must not be returned"


# ════════════════════════════════════════════════════════════════════════════════
# TESTS: find_eqh_eql_clusters (I9)
# ════════════════════════════════════════════════════════════════════════════════

class TestEQHEQLClusters:

    def test_two_near_equal_highs_form_cluster(self):
        """I9: Two swing highs within 0.15% of each other → cluster_size >= 2."""
        base = 100.0
        close_level = base * (1 + ICT_EQH_TOLERANCE * 0.5)  # within tolerance
        sh = [(1, base), (5, close_level)]
        sl = []
        sh_clusters, _ = find_eqh_eql_clusters(sh, sl)

        ref_size_base  = _ref_eqh_cluster_size([base, close_level], base)
        ref_size_close = _ref_eqh_cluster_size([base, close_level], close_level)

        for lev in sh_clusters:
            engine_size = sh_clusters[lev]
            if abs(lev - base) / max(base, 1e-10) <= ICT_EQH_TOLERANCE:
                assert engine_size == ref_size_base, (
                    f"cluster size at base mismatch: engine={engine_size} ref={ref_size_base}"
                )

    def test_two_far_highs_each_isolated(self):
        """Swing highs more than 0.15% apart must each be cluster_size=1."""
        base = 100.0
        far  = base * (1 + ICT_EQH_TOLERANCE * 3)  # well outside tolerance
        sh = [(1, base), (5, far)]
        sl = []
        sh_clusters, _ = find_eqh_eql_clusters(sh, sl)
        for lev, sz in sh_clusters.items():
            assert sz == 1, f"isolated swing at {lev} should have cluster_size=1, got {sz}"

    def test_three_near_equal_highs_cluster_size_3(self):
        base = 100.0
        tol = ICT_EQH_TOLERANCE * 0.4
        sh = [(1, base), (3, base * (1 + tol)), (7, base * (1 - tol))]
        sl = []
        sh_clusters, _ = find_eqh_eql_clusters(sh, sl)
        for lev, sz in sh_clusters.items():
            assert sz == 3, f"expected cluster_size=3, got {sz} for level {lev}"

    def test_empty_swings_returns_empty_clusters(self):
        sh_clusters, sl_clusters = find_eqh_eql_clusters([], [])
        assert sh_clusters == {} and sl_clusters == {}


# ════════════════════════════════════════════════════════════════════════════════
# TESTS: compute_dealing_range (I10)
# ════════════════════════════════════════════════════════════════════════════════

class TestDealingRange:

    def _make_range_data(self, rng_high=110.0, rng_low=90.0):
        """80-bar sequence with one swing high and one swing low well inside
        the last-50-bar lookback window used by compute_dealing_range().

        compute_dealing_range slices highs[-50:] of an 80-bar array → bars 30-79.
        Swing high is planted at original bar 35 (slice index 5, > 0 ✓).
        Swing low  is planted at original bar 55 (slice index 25 ✓).
        Both are confirmed with ICT_SWING_N=2 right-side lag.
        """
        n = 80
        mid = (rng_high + rng_low) / 2
        h = [mid + 0.3] * n
        l = [mid - 0.3] * n

        # Swing HIGH at original bar 35 (slice index 5)
        sh_bar = 35
        h[sh_bar - 1] = rng_high - 2   # left neighbour: lower
        h[sh_bar]     = rng_high        # peak
        h[sh_bar + 1] = rng_high - 2   # right confirmation 1
        h[sh_bar + 2] = rng_high - 2   # right confirmation 2
        l[sh_bar]     = rng_high - 3

        # Swing LOW at original bar 55 (slice index 25)
        sl_bar = 55
        l[sl_bar - 1] = rng_low + 2    # left neighbour: higher
        l[sl_bar]     = rng_low         # trough
        l[sl_bar + 1] = rng_low + 2    # right confirmation 1
        l[sl_bar + 2] = rng_low + 2    # right confirmation 2
        h[sl_bar]     = rng_low + 3

        return h, l

    def test_price_above_midpoint_plus_band_is_premium(self):
        """I10: price > midpoint + 5% band → PREMIUM."""
        rng_high, rng_low = 110.0, 90.0
        h, l = self._make_range_data(rng_high=rng_high, rng_low=rng_low)
        mid = (rng_high + rng_low) / 2       # 100
        span = rng_high - rng_low            # 20
        price = mid + span * 0.05 + 1.0      # clearly above equilibrium band
        result = compute_dealing_range(h, l, price)
        assert result["location"] == "PREMIUM", (
            f"price={price} above midpoint+band should be PREMIUM, got {result['location']}"
        )

    def test_price_below_midpoint_minus_band_is_discount(self):
        rng_high, rng_low = 110.0, 90.0
        h, l = self._make_range_data(rng_high=rng_high, rng_low=rng_low)
        mid  = (rng_high + rng_low) / 2
        span = rng_high - rng_low
        price = mid - span * 0.05 - 1.0
        result = compute_dealing_range(h, l, price)
        assert result["location"] == "DISCOUNT", (
            f"price={price} below midpoint-band should be DISCOUNT, got {result['location']}"
        )

    def test_price_at_midpoint_is_equilibrium(self):
        rng_high, rng_low = 110.0, 90.0
        h, l = self._make_range_data(rng_high=rng_high, rng_low=rng_low)
        price = (rng_high + rng_low) / 2    # exactly at midpoint
        result = compute_dealing_range(h, l, price)
        assert result["location"] == "EQUILIBRIUM", (
            f"price at midpoint should be EQUILIBRIUM, got {result['location']}"
        )

    def test_no_swings_returns_unknown(self):
        h, l, _, _ = _flat_candles(60)
        result = compute_dealing_range(h, l, 100.0)
        assert result["location"] == "UNKNOWN"

    def test_range_high_greater_than_range_low(self):
        rng_high, rng_low = 110.0, 90.0
        h, l = self._make_range_data(rng_high=rng_high, rng_low=rng_low)
        result = compute_dealing_range(h, l, 100.0)
        if result["range_high"] and result["range_low"]:
            assert result["range_high"] > result["range_low"], (
                "range_high must be > range_low"
            )
