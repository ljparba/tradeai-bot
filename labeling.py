"""TradeAI honest-label suite — Phase A item #2 (ENTERPRISE_ROADMAP).

Three responsibilities, all stdlib-only (no pandas, no numpy, no mlfinlab):

1. **Triple-barrier labeling** (Lopez de Prado, AFML §3.4) — every signal gets
   a first-touch ternary label ``{-1, 0, +1}`` plus the realized return at
   first touch and the vertical-barrier index. This is the canonical input
   downstream consumers (CPCV, meta-labeling, DSR, Monte Carlo) expect.

2. **Volatility scaling** — exponentially weighted daily sigma estimator (de
   Prado §3.1). Used to scale barriers so labels are comparable across regimes,
   not biased toward low-vol periods.

3. **Bootstrap confidence intervals** — non-parametric Monte Carlo CI for win
   rate and Sharpe ratio. Required reading for any sub-50-trade backtest.

Design constraints:

* No external deps — must work with the bot's stdlib + ``requests`` posture.
* All RNG paths are seeded so CI rebuilds are reproducible.
* Functions are pure: they never log, never raise into the caller on bad data,
  and always return a sentinel rather than crash the backtest loop.
* Schema is forward-compatible with mlfinlab's ``TripleBarrier`` if we ever
  promote — same column names (``bin``, ``ret``, ``t1``).

See ``tests/test_labeling.py`` for the spec — each function has a corresponding
unit test enforcing the de Prado invariants.
"""
from __future__ import annotations

import math
import random
import statistics
from typing import Dict, List, Optional, Sequence, Tuple


# ══════════════════════════════════════════════════════════
# 1. TRIPLE-BARRIER LABELING
# ══════════════════════════════════════════════════════════
def triple_barrier_label(
    direction: str,
    entry_price: float,
    sl: float,
    tp: float,
    future_bars: Sequence[Dict[str, float]],
    t1_bars: int,
) -> Dict[str, float]:
    """First-touch ternary label per Lopez de Prado, AFML §3.4.

    Parameters
    ----------
    direction : "BUY" | "SELL"
        Trade direction. Determines which barrier is "up" vs "down".
    entry_price : float
        Fill price. Used to convert touches into return percentages.
    sl : float
        Stop-loss absolute price.
    tp : float
        Profit-take absolute price. Use the **first** profit target (TP1) — de
        Prado's triple-barrier is single-target by construction; the bot's
        multi-tier TP1/TP2/TP3 belong to the realized-R model, not the label.
    future_bars : list of {"h": float, "l": float}
        Forward candles to scan. The vertical barrier is at index ``t1_bars - 1``.
    t1_bars : int
        Vertical barrier index (timeout in bars from entry).

    Returns
    -------
    dict with keys::

        bin   : int   — first-touch label: +1 (tp), -1 (sl), 0 (timeout)
        touch : str   — "TP" | "SL" | "TIMEOUT"
        ret   : float — realized return at first touch as decimal (e.g. 0.012)
        t1    : int   — bar index of first touch (or t1_bars on timeout)

    Sentinel values returned on bad input (``{"bin": 0, "touch": "INVALID",
    "ret": 0.0, "t1": 0}``) — never raises.

    Invariants:
        * Strict first-touch: if both SL and TP intersect the same bar, the
          label is SL (conservative — matches existing ``check_outcome``).
        * Returns are direction-aware (BUY: +up, SELL: +down).
        * Timeout returns the **mark-to-market** P&L at the vertical barrier
          (last bar close approximated as ``(h+l)/2`` since we don't store closes
          in the future_bars dict the bot uses elsewhere).
    """
    if direction not in ("BUY", "SELL"):
        return _invalid_label()
    if entry_price is None or entry_price <= 0:
        return _invalid_label()
    if sl is None or tp is None:
        return _invalid_label()
    if not future_bars or t1_bars <= 0:
        return _invalid_label()

    horizon = min(t1_bars, len(future_bars))

    for i in range(horizon):
        bar = future_bars[i]
        h, l = bar.get("h"), bar.get("l")
        if h is None or l is None:
            continue
        if direction == "BUY":
            sl_hit = l <= sl
            tp_hit = h >= tp
        else:
            sl_hit = h >= sl
            tp_hit = l <= tp

        # Strict first-touch SL preference on the same bar (matches check_outcome).
        if sl_hit:
            ret = (sl - entry_price) / entry_price if direction == "BUY" else (entry_price - sl) / entry_price
            return {"bin": -1, "touch": "SL", "ret": round(ret, 6), "t1": i}
        if tp_hit:
            ret = (tp - entry_price) / entry_price if direction == "BUY" else (entry_price - tp) / entry_price
            return {"bin": 1, "touch": "TP", "ret": round(ret, 6), "t1": i}

    # Vertical-barrier hit — mark-to-market at last seen bar.
    last = future_bars[horizon - 1]
    mid = ((last.get("h") or entry_price) + (last.get("l") or entry_price)) / 2.0
    ret = (mid - entry_price) / entry_price if direction == "BUY" else (entry_price - mid) / entry_price
    return {"bin": 0, "touch": "TIMEOUT", "ret": round(ret, 6), "t1": horizon}


def _invalid_label() -> Dict[str, float]:
    return {"bin": 0, "touch": "INVALID", "ret": 0.0, "t1": 0}


# ══════════════════════════════════════════════════════════
# 2. VOLATILITY-SCALED BARRIERS
# ══════════════════════════════════════════════════════════
def ewma_daily_sigma(
    closes: Sequence[float],
    bars_per_day: int = 288,
    halflife_days: float = 20.0,
) -> Optional[float]:
    """Exponentially weighted **daily** return volatility, per AFML §3.1.

    Parameters
    ----------
    closes : list[float]
        Bar closes, most recent last.
    bars_per_day : int
        288 = 5-minute bars per 24h crypto day (matches FORWARD_BARS scale).
    halflife_days : float
        Decay halflife. 20 days is de Prado's canonical choice.

    Returns
    -------
    float
        Estimated daily sigma as a decimal (e.g. 0.025 = 2.5%/day). Returns
        ``None`` if there is not enough data (<2 returns).

    Implementation notes:
        * Computes bar-to-bar log returns, then scales by ``sqrt(bars_per_day)``
          to lift to a daily estimate.
        * EWMA recursion: ``var = lam·var + (1−lam)·r²`` where
          ``lam = exp(−ln2/halflife_bars)``.
    """
    if not closes or len(closes) < 2:
        return None
    try:
        log_returns: List[float] = []
        for i in range(1, len(closes)):
            prev, curr = closes[i - 1], closes[i]
            if prev is None or curr is None or prev <= 0 or curr <= 0:
                continue
            log_returns.append(math.log(curr / prev))
        if len(log_returns) < 2:
            return None
        halflife_bars = max(1.0, halflife_days * bars_per_day)
        lam = math.exp(-math.log(2.0) / halflife_bars)
        # Seed variance with the unweighted variance of the first ~halflife_bars window
        seed_window = log_returns[: min(len(log_returns), int(halflife_bars))]
        var = statistics.pvariance(seed_window) if len(seed_window) >= 2 else 0.0
        for r in log_returns[len(seed_window):]:
            var = lam * var + (1.0 - lam) * (r * r)
        bar_sigma = math.sqrt(max(0.0, var))
        daily_sigma = bar_sigma * math.sqrt(bars_per_day)
        return daily_sigma
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def vol_scaled_barriers(
    entry_price: float,
    sigma_daily: float,
    pt_multiple: float = 2.0,
    sl_multiple: float = 1.0,
    direction: str = "BUY",
) -> Tuple[Optional[float], Optional[float]]:
    """Volatility-scaled (TP, SL) absolute prices.

    Returns ``(None, None)`` if inputs invalid. Used by CPCV/meta-labeling pipes
    where comparable-across-regime labels are required. The bot's live TP/SL
    remain ICT-structural; this function exists for the honest-label column only.
    """
    if entry_price is None or entry_price <= 0:
        return None, None
    if sigma_daily is None or sigma_daily <= 0:
        return None, None
    if direction not in ("BUY", "SELL"):
        return None, None
    if direction == "BUY":
        tp = entry_price * (1.0 + pt_multiple * sigma_daily)
        sl = entry_price * (1.0 - sl_multiple * sigma_daily)
    else:  # SELL — TP below, SL above; each uses its OWN multiplier
        tp = entry_price * (1.0 - pt_multiple * sigma_daily)
        sl = entry_price * (1.0 + sl_multiple * sigma_daily)
    return tp, sl


# ══════════════════════════════════════════════════════════
# 3. MONTE CARLO BOOTSTRAP CI
# ══════════════════════════════════════════════════════════
def bootstrap_ci(
    values: Sequence[float],
    statistic: str = "mean",
    n_iter: int = 10000,
    ci: float = 0.95,
    seed: Optional[int] = 42,
) -> Dict[str, float]:
    """Non-parametric bootstrap confidence interval for a statistic.

    Parameters
    ----------
    values : list[float]
        Sample. Wins (1) and losses (0) for WR; per-trade R-multiples for Sharpe.
    statistic : "mean" | "sharpe"
        ``mean`` returns point/lo/hi of the sample mean. ``sharpe`` returns the
        annualized Sharpe ratio assuming `values` are per-trade returns (the
        annualization scalar is conservatively set to 1.0 — caller multiplies
        by sqrt(N_trades_per_year) if they want a calendar-Sharpe).
    n_iter : int
        Bootstrap draws. 10000 is the AFML-canonical default.
    ci : float
        Confidence level (0.95 → 95% CI).
    seed : int | None
        RNG seed for reproducibility. Set ``None`` for true random.

    Returns
    -------
    dict
        ``{"point": float, "lo": float, "hi": float, "n": int}``. Returns all
        zeros when ``values`` is empty or constant. Never raises.
    """
    n = len(values)
    if n == 0:
        return {"point": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
    if statistic not in ("mean", "sharpe"):
        return {"point": 0.0, "lo": 0.0, "hi": 0.0, "n": n}

    point = _point_estimate(values, statistic)
    if n == 1:
        return {"point": round(point, 6), "lo": round(point, 6), "hi": round(point, 6), "n": 1}

    rng = random.Random(seed)
    draws: List[float] = []
    for _ in range(max(1, int(n_iter))):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        draws.append(_point_estimate(sample, statistic))
    draws.sort()
    lo_idx = max(0, int(math.floor((1.0 - ci) / 2.0 * len(draws))))
    hi_idx = min(len(draws) - 1, int(math.ceil((1.0 + ci) / 2.0 * len(draws))) - 1)
    return {
        "point": round(point, 6),
        "lo": round(draws[lo_idx], 6),
        "hi": round(draws[hi_idx], 6),
        "n": n,
    }


def _point_estimate(values: Sequence[float], statistic: str) -> float:
    if not values:
        return 0.0
    if statistic == "mean":
        return statistics.fmean(values)
    if statistic == "sharpe":
        if len(values) < 2:
            return 0.0
        # NEW-M-6 fix (cycle-6 audit 2026-05-26): use sample std (n-1 ddof)
        # to match validation.py:_safe_std + sharpe_ratio(). Previously this
        # used statistics.pstdev (population n divisor), making the bootstrap
        # CI Sharpe upward-biased relative to the CPCV Sharpe by ~sqrt(n/(n-1))
        # — about 3.8% at n=14 (typical per-fold count at Run-81 sample size).
        # Bootstrap CI is informational only (not gated), but the inconsistency
        # was latent technical debt across two honest-metric estimators.
        mu = statistics.fmean(values)
        sd = statistics.stdev(values)  # n-1 ddof
        if sd == 0.0:
            return 0.0
        return mu / sd
    return 0.0


def bootstrap_wr_ci(
    outcomes: Sequence[str],
    win_set: Tuple[str, ...] = ("WIN", "PARTIAL_TP1", "PARTIAL_TP2"),
    n_iter: int = 10000,
    ci: float = 0.95,
    seed: Optional[int] = 42,
) -> Dict[str, float]:
    """Convenience wrapper: pass the bot's outcome strings, get a WR CI.

    Returns ``{"wr": float, "lo": float, "hi": float, "n": int}`` where all
    rates are expressed as percentages (0–100).
    """
    if not outcomes:
        return {"wr": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
    win_flags = [1.0 if o in win_set else 0.0 for o in outcomes]
    result = bootstrap_ci(win_flags, statistic="mean", n_iter=n_iter, ci=ci, seed=seed)
    return {
        "wr": round(result["point"] * 100.0, 2),
        "lo": round(result["lo"] * 100.0, 2),
        "hi": round(result["hi"] * 100.0, 2),
        "n": result["n"],
    }


def bootstrap_sharpe_ci(
    per_trade_returns: Sequence[float],
    n_iter: int = 10000,
    ci: float = 0.95,
    seed: Optional[int] = 42,
) -> Dict[str, float]:
    """Non-parametric Sharpe CI from per-trade returns (R-multiples or %).

    Returns ``{"sharpe": float, "lo": float, "hi": float, "n": int}``.
    Caller multiplies ``sharpe`` by ``sqrt(N_trades_per_year)`` for a
    calendar-Sharpe estimate — left to the caller to avoid baking in a fixed
    annualization that doesn't match every backtest window.
    """
    result = bootstrap_ci(per_trade_returns, statistic="sharpe", n_iter=n_iter, ci=ci, seed=seed)
    return {
        "sharpe": round(result["point"], 4),
        "lo": round(result["lo"], 4),
        "hi": round(result["hi"], 4),
        "n": result["n"],
    }


# ══════════════════════════════════════════════════════════
# 4. PUBLIC HELPERS
# ══════════════════════════════════════════════════════════
def label_outcome_aliases(bin_value: int) -> str:
    """Map the integer label to a readable string for reports."""
    return {1: "TP_FIRST", -1: "SL_FIRST", 0: "TIMEOUT"}.get(int(bin_value), "INVALID")
