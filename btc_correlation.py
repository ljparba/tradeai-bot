"""
btc_correlation.py — Rolling BTC↔token correlation (T1.3 / ENHANCEMENT_ROADMAP.md)
================================================================================

WHY THIS EXISTS
---------------
When BTC pumps 3% in an hour, ALT tokens tend to follow. The CRT scanner
currently uses BTC bias as a hard gate but doesn't model the STRENGTH of the
correlation as a tunable signal-quality factor.

Adding rolling BTC-correlation as a tag + optional confidence overlay opens
new search dimensions for the explorer:
  - BTC_CORR_WINDOW_MIN          (default 60 = 1h on 5M candles)
  - BTC_CORR_HIGH_THRESH         (default 0.7 = strong positive corr)
  - BTC_CORR_LOW_THRESH          (default 0.3 = weak corr → token-specific edge)
  - BTC_CORR_BONUS_PCT           (default 0.0 = disabled; tune via explorer)
  - BTC_CORR_GATE_ENABLED        (0/1)

ARCHITECTURE
------------
Pure-function correlation calculator. No I/O, no caching — all data passed in
by caller (avoids the live/backtest divergence trap that funding has).

Live uses the same 5M closes already fetched for the CRT scan. Backtest uses
the historical 5M closes from the cached OHLCV. Identical computation in both
paths = perfect parity.

CORRELATION DEFINITION
----------------------
Pearson correlation between BTC log-returns and token log-returns over the
last `window` bars (typically 60 × 5M = 5h).

Per ICT/practical-trading literature, the most useful correlation window for
short-term setups is 1-6 hours. Day-level (288 × 5M) is too smooth; minute-
level (12 × 5M = 1h) is too noisy.

USAGE
-----
    from btc_correlation import (
        compute_btc_correlation, classify_btc_corr,
        btc_corr_confidence_bonus,
    )

    corr = compute_btc_correlation(btc_closes, token_closes, window=60)
    cls = classify_btc_corr(corr, signal_dir="BUY", btc_trend="STRONG_BULL")
    bonus = btc_corr_confidence_bonus(corr, signal_dir, btc_trend)
"""

from __future__ import annotations

import math
import os
from typing import List, Optional


# ── Tunable knobs (env-overridable for explorer search) ──────────────────────
BTC_CORR_WINDOW_MIN: int = int(os.environ.get("BTC_CORR_WINDOW_MIN", "60"))
BTC_CORR_HIGH_THRESH: float = float(os.environ.get("BTC_CORR_HIGH_THRESH", "0.7"))
BTC_CORR_LOW_THRESH: float = float(os.environ.get("BTC_CORR_LOW_THRESH", "0.3"))
BTC_CORR_BONUS_PCT: float = float(os.environ.get("BTC_CORR_BONUS_PCT", "0.0"))
BTC_CORR_GATE_ENABLED: int = int(os.environ.get("BTC_CORR_GATE_ENABLED", "1"))


def _log_returns(closes: List[float]) -> List[float]:
    """Convert price series to log returns. Skips zero/negative prices."""
    out: List[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev <= 0 or curr <= 0:
            continue
        try:
            out.append(math.log(curr / prev))
        except (ValueError, ZeroDivisionError):
            continue
    return out


def _pearson_corr(xs: List[float], ys: List[float]) -> Optional[float]:
    """Sample Pearson correlation, no NaN handling for the caller.

    Returns None when input lengths mismatch, n<3, or variance is zero.
    """
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx <= 0 or dy <= 0:
        return None
    return num / (dx * dy)


def compute_btc_correlation(
    btc_closes: List[float],
    token_closes: List[float],
    window: Optional[int] = None,
) -> Optional[float]:
    """Compute rolling Pearson correlation between BTC and token log-returns.

    Parameters
    ----------
    btc_closes   : recent BTC 5M closes (oldest → newest)
    token_closes : recent token 5M closes, same length & alignment as btc_closes
    window       : how many trailing bars to use (defaults to BTC_CORR_WINDOW_MIN)

    Returns
    -------
    Pearson r ∈ [-1, +1], or None if input is insufficient/degenerate.
    """
    if not btc_closes or not token_closes:
        return None
    win = window if window is not None else BTC_CORR_WINDOW_MIN
    # Ensure both series align on the trailing window. If either is shorter
    # than `window+1` (need one extra bar for the return), bail.
    needed = win + 1
    if len(btc_closes) < needed or len(token_closes) < needed:
        return None
    btc_tail = btc_closes[-needed:]
    tok_tail = token_closes[-needed:]
    btc_rets = _log_returns(btc_tail)
    tok_rets = _log_returns(tok_tail)
    # Returns might be shorter than win if some bars had zero prices
    n = min(len(btc_rets), len(tok_rets))
    if n < 3:
        return None
    return _pearson_corr(btc_rets[-n:], tok_rets[-n:])


def classify_btc_corr(
    corr: Optional[float],
    signal_dir: str,
    btc_trend: str,
) -> str:
    """Classify the BTC↔token correlation strength + alignment vs signal.

    Returns one of:
      ALIGNED_HIGH    — corr ≥ HIGH and signal direction matches BTC trend
      ALIGNED_LOW     — corr ≤ LOW (decoupled), token-specific edge expected
      DIVERGENT       — high corr but signal counters BTC trend (risky)
      AMBIGUOUS       — corr in mid band [LOW, HIGH]
      UNKNOWN         — corr is None
      DISABLED        — BTC_CORR_GATE_ENABLED=0
    """
    if not BTC_CORR_GATE_ENABLED:
        return "DISABLED"
    if corr is None:
        return "UNKNOWN"
    sig = (signal_dir or "").upper()
    btc = (btc_trend or "").upper()
    # H-CY12-2 fix (audit 2026-05-29): accept BOTH the canonical EMA-trend
    # vocabulary ("STRONG_BULL"/"BULL"/"STRONG_BEAR"/"BEAR" from indicators.get_trend)
    # AND the ICT-bias vocabulary ("BULLISH"/"BEARISH" from ict_engine.get_ict_4h_bias
    # and crypto_alert.get_mtf_bias). Pre-fix the call sites at crypto_alert.py:1157
    # and backtest.py:1481 passed `bias_4h` (BULLISH vocab) which never matched the
    # STRONG_BULL/BULL whitelist — making ALIGNED_HIGH and DIVERGENT mathematically
    # unreachable. At high correlation (>=BTC_CORR_HIGH_THRESH=0.7) the token's 4h
    # bias is empirically aligned with BTC's trend (that's what "correlated" means
    # for crypto pairs), so the two vocabularies converge in the regime that matters.
    # NEUTRAL in either vocab still falls through to AMBIGUOUS correctly.
    btc_aligns_buy = btc in ("STRONG_BULL", "BULL", "BULLISH")
    btc_aligns_sell = btc in ("STRONG_BEAR", "BEAR", "BEARISH")
    high_corr = corr >= BTC_CORR_HIGH_THRESH
    low_corr = corr <= BTC_CORR_LOW_THRESH
    if high_corr:
        if (sig == "BUY" and btc_aligns_buy) or (sig == "SELL" and btc_aligns_sell):
            return "ALIGNED_HIGH"
        if (sig == "BUY" and btc_aligns_sell) or (sig == "SELL" and btc_aligns_buy):
            return "DIVERGENT"
        return "AMBIGUOUS"
    if low_corr:
        return "ALIGNED_LOW"
    return "AMBIGUOUS"


def btc_corr_confidence_bonus(
    corr: Optional[float],
    signal_dir: str,
    btc_trend: str,
) -> float:
    """Return the confidence bonus to add based on BTC correlation alignment.

    Bonus magnitudes (in confidence-point fractional units, multiplied by 10
    at the call site to reach the [0..10] confidence scale):
      ALIGNED_HIGH  → +BTC_CORR_BONUS_PCT   (BTC trend + corr support signal)
      ALIGNED_LOW   → +BTC_CORR_BONUS_PCT/2 (decoupled; token-specific edge)
      DIVERGENT     → -BTC_CORR_BONUS_PCT   (signal counters BTC trend at high corr)
      AMBIGUOUS / UNKNOWN / DISABLED → 0.0
    """
    cls = classify_btc_corr(corr, signal_dir, btc_trend)
    if cls == "ALIGNED_HIGH":
        return +BTC_CORR_BONUS_PCT
    if cls == "ALIGNED_LOW":
        return +BTC_CORR_BONUS_PCT * 0.5
    if cls == "DIVERGENT":
        return -BTC_CORR_BONUS_PCT
    return 0.0


__all__ = [
    "compute_btc_correlation",
    "classify_btc_corr",
    "btc_corr_confidence_bonus",
    "BTC_CORR_WINDOW_MIN",
    "BTC_CORR_HIGH_THRESH",
    "BTC_CORR_LOW_THRESH",
    "BTC_CORR_BONUS_PCT",
    "BTC_CORR_GATE_ENABLED",
]
