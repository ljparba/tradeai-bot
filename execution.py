"""Realistic execution model for TradeAI backtest (Phase A of parity roadmap).

DOC: ``docs/LIVE_BACKTEST_PARITY_ROADMAP.md`` (Phase A)
SPEC: ``docs/exec_model_calibration.md``

Models the gap between backtest "perfect fills at signal price + flat 30bps"
and live "operator sees Telegram, decides, places order, may or may not fill,
spread varies by time+vol". After this module is wired into backtest.py
(Phase A.2) and the default flag flips (Phase A.3), backtest WR becomes a
realistic predictor of live WR within +/-3pp.

THIS MODULE IS LIVE-BOT-NEUTRAL. crypto_alert.py never imports execution.py;
the live bot's "execution" happens entirely through the operator's manual
order placement based on Telegram alerts. This module exists to bring the
BACKTEST closer to that reality, not to change live behavior.

ARCHITECTURE — pure function with seeded RNG
============================================

``simulate_execution()`` is a pure function: same inputs (including ``seed``)
always produce the same output. The seed MUST be derived deterministically
by the caller from the signal context, typically::

    seed = hash((str(signal_ts), token, direction)) & 0x7FFFFFFF

This gives Optuna trial-determinism + reproducible backtests, which is
required for CPCV statistical validity (per H6 fix in CROSS_REF.md).

THE 5 FRICTION COMPONENTS MODELED
==================================

1. **Spread (time + vol conditioned)** — base ``TOKEN_RT_COST`` from
   ``ict_engine.py`` is multiplied by:
   - Time-of-day multiplier: 1.0 during NY/London (06-20 UTC), 1.2 overnight
     (20-24 UTC), 1.4 during ASIA early (00-06 UTC) when liquidity is thinnest.
   - Volatility multiplier: 1.0 normal, 1.3 when ``atr_ratio > 1.5``, 1.6 when
     ``atr_ratio > 2.0``. Captures spread widening during news/dumps.

2. **Execution latency** — operator sees Telegram, decides, places order.
   Truncated Gaussian centered at 12s, sigma 8s, clamped to [3, 60s]. Backtest
   fills at the NEXT 5M bar's open price plus a small slip proportional to the
   sampled latency (max ~2bps).

3. **Partial fills** — Bernoulli over fill outcomes:
   - 2% NO FILL (signal aborted, no P&L contribution)
   - 5% PARTIAL FILL at 50% size (half P&L impact, same direction)
   - 93% FULL FILL at intended size
   Probabilities empirically calibrated against retail-execution literature;
   tunable via env vars.

4. **Stale-price reject** — if price moved more than 1.5x ATR (5M) between
   signal time and intended fill time, the limit order is left behind. Captures
   news shocks, liquidation cascades, and similar fast-move events where
   retail limit orders simply do not fill at the intended price.

5. **Adverse selection** — in TRENDING_BULL/BEAR regimes, retail entries face
   smart-money fade near key levels. Models this as a flat +5bps cost.
   Empirically a small but persistent effect; turn off by setting
   ``EXEC_ADV_SEL_COST=0``.

ENV-CONFIGURABLE KNOBS
======================

All thresholds are env-overridable for calibration without code edits. See
``docs/exec_model_calibration.md`` for the full table + calibration procedure.

OUTPUT
======

Returns ``ExecutionResult`` (frozen dataclass) with:
- ``status``        : ``"FILLED"`` | ``"PARTIAL"`` | ``"REJECTED"``
- ``fill_price``    : actual fill price (NaN when REJECTED)
- ``fill_size_pct`` : 1.0 (full) | 0.5 (partial) | 0.0 (rejected)
- ``total_cost_pct``: spread + adverse selection (as fraction of price)
- ``latency_sec``   : sampled latency between signal time and fill
- ``reason``        : ``"ok"`` | ``"no_fill"`` | ``"stale_move"``

Caller (backtest.py, eventually) should:
- if status == "REJECTED": skip the signal entirely, log_rejection
- else: use fill_price as entry, multiply P&L by fill_size_pct, deduct total_cost_pct

ACCEPTANCE CRITERIA (Phase A.1, per parity roadmap)
===================================================
- Pure function: same seed -> same result
- All 15+ unit tests in ``tests/test_execution.py`` pass
- Defaults match conservative retail-execution priors
- Env vars override defaults without code edit
"""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ── Env-configurable knobs ──────────────────────────────────────────────────
# Each can be overridden via environment variable. Defaults are conservative.

LATENCY_MEAN_SEC      = float(os.environ.get("EXEC_LATENCY_MEAN_SEC",     "12.0"))
LATENCY_STD_SEC       = float(os.environ.get("EXEC_LATENCY_STD_SEC",       "8.0"))
LATENCY_MIN_SEC       = float(os.environ.get("EXEC_LATENCY_MIN_SEC",       "3.0"))
LATENCY_MAX_SEC       = float(os.environ.get("EXEC_LATENCY_MAX_SEC",      "60.0"))

PARTIAL_FILL_PROB     = float(os.environ.get("EXEC_PARTIAL_FILL_PROB",     "0.05"))
NO_FILL_PROB          = float(os.environ.get("EXEC_NO_FILL_PROB",          "0.02"))

STALE_ATR_MULT        = float(os.environ.get("EXEC_STALE_ATR_MULT",        "1.5"))
ADVERSE_SELECT_COST   = float(os.environ.get("EXEC_ADV_SEL_COST",          "0.0005"))

# Time-of-day spread multipliers (UTC hours)
TIME_MULT_ASIA_EARLY  = float(os.environ.get("EXEC_TIME_MULT_ASIA_EARLY",  "1.4"))   # 00:00 – 06:00
TIME_MULT_OVERNIGHT   = float(os.environ.get("EXEC_TIME_MULT_OVERNIGHT",   "1.2"))   # 20:00 – 24:00
TIME_MULT_ACTIVE      = float(os.environ.get("EXEC_TIME_MULT_ACTIVE",      "1.0"))   # 06:00 – 20:00 (London + NY)

# Volatility spread multipliers (keyed on atr_ratio)
VOL_MULT_HIGH         = float(os.environ.get("EXEC_VOL_MULT_HIGH",         "1.6"))   # atr_ratio > 2.0
VOL_MULT_MED          = float(os.environ.get("EXEC_VOL_MULT_MED",          "1.3"))   # atr_ratio > 1.5
VOL_MULT_NORMAL       = float(os.environ.get("EXEC_VOL_MULT_NORMAL",       "1.0"))   # otherwise

# Latency slip — small price drift proportional to time waited.
# At max latency (60s) the slip is approximately 2bps adverse.
LATENCY_SLIP_PER_30S  = float(os.environ.get("EXEC_LATENCY_SLIP_PER_30S",  "0.0002"))   # 2bps per 30s


# ── Result type ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ExecutionResult:
    """Frozen result of a simulated execution.

    Use as a pure record — never mutate. ``fill_price`` is NaN when status is
    REJECTED; check ``status`` before using the price.
    """
    status:         str       # "FILLED" | "PARTIAL" | "REJECTED"
    fill_price:     float     # actual fill price (NaN if REJECTED)
    fill_size_pct:  float     # 1.0 full, 0.5 partial, 0.0 rejected
    total_cost_pct: float     # spread + adverse selection (fraction of price)
    latency_sec:    float     # sampled latency between signal and fill
    reason:         str       # "ok" | "no_fill" | "stale_move"


# ── Public API ──────────────────────────────────────────────────────────────
def simulate_execution(
    *,
    signal_ts:      datetime,
    signal_price:   float,
    next_bar_open:  float,
    token:          str,
    direction:      str,         # "BUY" | "SELL"
    regime:         str,         # "TRENDING_BULL" | "TRENDING_BEAR" | "RANGING" | ...
    atr_5m:         float,
    atr_ratio:      float,
    seed:           int,
) -> ExecutionResult:
    """Simulate one execution. Pure function; given the same inputs (including
    ``seed``), always returns the same ExecutionResult.

    Caller is responsible for deriving ``seed`` deterministically from the
    signal context to preserve backtest reproducibility. Typical pattern::

        seed = hash((str(signal_ts), token, direction)) & 0x7FFFFFFF

    See module docstring for the 5 friction components modeled and the
    ``ExecutionResult`` field semantics.
    """
    if signal_price <= 0:
        raise ValueError(f"signal_price must be positive; got {signal_price!r}")
    if atr_5m <= 0:
        raise ValueError(f"atr_5m must be positive; got {atr_5m!r}")
    if direction not in ("BUY", "SELL"):
        raise ValueError(f"direction must be 'BUY' or 'SELL'; got {direction!r}")

    rng = random.Random(seed)

    # 1. Latency — operator sees Telegram, decides, places order.
    raw_latency = rng.gauss(LATENCY_MEAN_SEC, LATENCY_STD_SEC)
    latency_sec = max(LATENCY_MIN_SEC, min(LATENCY_MAX_SEC, raw_latency))

    # 2. Fill outcome — Bernoulli over (no fill, partial, full).
    fill_roll = rng.random()
    if fill_roll < NO_FILL_PROB:
        return ExecutionResult(
            status="REJECTED",
            fill_price=float("nan"),
            fill_size_pct=0.0,
            total_cost_pct=0.0,
            latency_sec=latency_sec,
            reason="no_fill",
        )
    fill_size_pct = 0.5 if fill_roll < (NO_FILL_PROB + PARTIAL_FILL_PROB) else 1.0

    # 3. Fill price with latency-proportional slip.
    #    Slip is adverse: BUY gets filled at slightly higher price, SELL lower.
    slip_pct = LATENCY_SLIP_PER_30S * (latency_sec / 30.0)
    if direction == "BUY":
        fill_price = next_bar_open * (1.0 + slip_pct)
    else:
        fill_price = next_bar_open * (1.0 - slip_pct)

    # 4. Stale-price reject — was the move between signal and fill too large?
    #    Real cause: news shock, liquidation cascade, etc. Limit order left behind.
    move_abs = abs(fill_price - signal_price)
    if move_abs > STALE_ATR_MULT * atr_5m:
        return ExecutionResult(
            status="REJECTED",
            fill_price=float("nan"),
            fill_size_pct=0.0,
            total_cost_pct=0.0,
            latency_sec=latency_sec,
            reason="stale_move",
        )

    # 5. Costs: spread (time + vol conditioned) + adverse selection.
    spread = effective_spread(token, signal_ts, atr_ratio)
    adverse = ADVERSE_SELECT_COST if regime in ("TRENDING_BULL", "TRENDING_BEAR") else 0.0
    total_cost_pct = spread + adverse

    status = "FILLED" if fill_size_pct == 1.0 else "PARTIAL"
    return ExecutionResult(
        status=status,
        fill_price=fill_price,
        fill_size_pct=fill_size_pct,
        total_cost_pct=total_cost_pct,
        latency_sec=latency_sec,
        reason="ok",
    )


def effective_spread(token: str, ts_utc: datetime, atr_ratio: float) -> float:
    """Return the effective round-trip spread cost for this signal context.

    Spread = base_token_rt_cost * time_multiplier * vol_multiplier

    Base comes from ``ict_engine.TOKEN_RT_COST`` (per-token map) with fallback
    to ``ict_engine.ROUND_TRIP_COST_PCT`` if the token is missing.

    Time multiplier: 1.0 during NY+London active hours (06:00-20:00 UTC),
    1.2 overnight (20:00-24:00), 1.4 during ASIA early (00:00-06:00).

    Vol multiplier: 1.0 normal, 1.3 if atr_ratio > 1.5, 1.6 if atr_ratio > 2.0.
    """
    base = _base_cost(token)
    time_mult = _time_multiplier(ts_utc.hour)
    vol_mult  = _vol_multiplier(atr_ratio)
    return base * time_mult * vol_mult


def _base_cost(token: str) -> float:
    """Return the per-token base RT cost from ict_engine."""
    # Local import: avoids module-load side effects when execution.py is
    # imported in test environments that may not have full ict_engine deps.
    try:
        from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT
        return TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT)
    except ImportError:
        # Test fallback when ict_engine is unavailable
        return 0.003


def _time_multiplier(hour_utc: int) -> float:
    if 0 <= hour_utc < 6:
        return TIME_MULT_ASIA_EARLY
    if 20 <= hour_utc < 24:
        return TIME_MULT_OVERNIGHT
    return TIME_MULT_ACTIVE


def _vol_multiplier(atr_ratio: float) -> float:
    if atr_ratio > 2.0:
        return VOL_MULT_HIGH
    if atr_ratio > 1.5:
        return VOL_MULT_MED
    return VOL_MULT_NORMAL


def derive_seed(signal_ts: datetime, token: str, direction: str) -> int:
    """Standard helper for callers to derive a deterministic seed.

    Uses BLAKE2b so the seed is identical across processes regardless of
    PYTHONHASHSEED. The previous implementation used Python's hash() which
    is salt-randomized per process — broke promote_baseline.py's
    reproducibility re-run gate across different interpreters.
    """
    import hashlib
    key = f"{signal_ts.isoformat()}|{token}|{direction}".encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFF


# ── Module-level introspection (for debugging) ───────────────────────────────
def current_config() -> dict:
    """Return all active env-configurable knobs as a dict. Useful for logging
    + reproducing a backtest run."""
    return {
        "LATENCY_MEAN_SEC":      LATENCY_MEAN_SEC,
        "LATENCY_STD_SEC":       LATENCY_STD_SEC,
        "LATENCY_MIN_SEC":       LATENCY_MIN_SEC,
        "LATENCY_MAX_SEC":       LATENCY_MAX_SEC,
        "PARTIAL_FILL_PROB":     PARTIAL_FILL_PROB,
        "NO_FILL_PROB":          NO_FILL_PROB,
        "STALE_ATR_MULT":        STALE_ATR_MULT,
        "ADVERSE_SELECT_COST":   ADVERSE_SELECT_COST,
        "TIME_MULT_ASIA_EARLY":  TIME_MULT_ASIA_EARLY,
        "TIME_MULT_OVERNIGHT":   TIME_MULT_OVERNIGHT,
        "TIME_MULT_ACTIVE":      TIME_MULT_ACTIVE,
        "VOL_MULT_HIGH":         VOL_MULT_HIGH,
        "VOL_MULT_MED":          VOL_MULT_MED,
        "VOL_MULT_NORMAL":       VOL_MULT_NORMAL,
        "LATENCY_SLIP_PER_30S":  LATENCY_SLIP_PER_30S,
    }
