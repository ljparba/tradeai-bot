"""
TradeAI — Shared Strategy Gate Engine
======================================
Single source of truth for ALL gate/filter decisions.

Both crypto_alert.py (live) and backtest.py import evaluate_setup() and a config
(LIVE_CONFIG or BACKTEST_CONFIG). Given identical candle-derived inputs and the
same config, both modes return the same gate decision — eliminating live/backtest
divergence (Task 1 of PRIORITY_FIX_PLAN).

Gate order: direction → session → regime → 4H bias → 1H trend.

To change a gate (e.g. promote SELL in live): update LIVE_CONFIG only — no logic
changes needed anywhere else.
"""

__all__ = [
    "StrategyConfig", "GateResult",
    "evaluate_setup",
    "LIVE_CONFIG", "BACKTEST_CONFIG",
    "QUALITY_RANK", "meets_quality",
]

QUALITY_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}

def meets_quality(quality: str, min_quality: str) -> bool:
    """Return True if quality >= min_quality (e.g. meets_quality('HIGH', 'MEDIUM') → True)."""
    return QUALITY_RANK.get(quality, 0) >= QUALITY_RANK.get(min_quality, 1)


class StrategyConfig:
    """Immutable gate configuration. Passed to evaluate_setup() to control trading logic."""

    __slots__ = (
        "enable_buy", "enable_sell",
        "liquid_hours", "blocked_regimes", "sell_allowed_regimes",
        "bias_4h_gate", "trend_1h_gate",
        "dealing_range_gate",
        "mss_min_quality", "fvg_min_quality",
        "smt_gate",
        "blocked_weekdays",
    )

    def __init__(
        self,
        enable_buy          = True,
        enable_sell         = False,
        liquid_hours        = None,       # iterable of UTC hours; default = ICT kill zones
        blocked_regimes     = None,       # iterable of regime labels to block
        sell_allowed_regimes = None,      # regimes to un-block for SELL only (still require 4H/1H alignment)
        bias_4h_gate        = "loose",    # "strict" | "loose" | "none"
        trend_1h_gate       = "loose",    # "strict" | "loose" | "none"
        dealing_range_gate  = False,      # True → block BUY in premium / SELL in discount
        mss_min_quality     = "LOW",      # "LOW"|"MEDIUM"|"HIGH" — minimum MSS quality gate
        fvg_min_quality     = "LOW",      # "LOW"|"MEDIUM"|"HIGH" — minimum FVG quality gate
        smt_gate            = False,      # True → require SMT divergence for reversal signals
        blocked_weekdays    = None,       # iterable of weekday ints (0=Mon…6=Sun) to block
    ):
        if bias_4h_gate not in ("strict", "loose", "none"):
            raise ValueError(f"bias_4h_gate must be 'strict', 'loose', or 'none', got {bias_4h_gate!r}")
        if trend_1h_gate not in ("strict", "loose", "none"):
            raise ValueError(f"trend_1h_gate must be 'strict', 'loose', or 'none', got {trend_1h_gate!r}")

        self.enable_buy         = enable_buy
        self.enable_sell        = enable_sell
        self.liquid_hours       = frozenset(
            liquid_hours if liquid_hours is not None
            # M2: ICT kill zones — ASIA_KZ(20-23) + LONDON_KZ(2-4) + NY_AM_KZ(13-15)
            else [20, 21, 22, 23, 2, 3, 4, 13, 14, 15]
        )
        self.blocked_regimes    = frozenset(
            blocked_regimes if blocked_regimes is not None
            # Task 11: LOW_VOLATILITY_CHOP (dead market) and LIQUIDATION (cascade) added
            # Run 44: RANGING blocked — 33.3% WR on 15 sigs (no institutional direction → fake sweeps)
            else ("CHOPPY", "HIGH_VOLATILITY", "TRENDING_BEAR",
                  "LOW_VOLATILITY_CHOP", "LIQUIDATION", "RANGING")
        )
        self.sell_allowed_regimes = frozenset(sell_allowed_regimes) if sell_allowed_regimes else frozenset()
        self.bias_4h_gate       = bias_4h_gate
        self.trend_1h_gate      = trend_1h_gate
        self.dealing_range_gate = dealing_range_gate
        self.mss_min_quality    = mss_min_quality
        self.fvg_min_quality    = fvg_min_quality
        self.smt_gate           = smt_gate
        # 1=Tue, 2=Wed, 5=Sat: confirmed poor-WR days; W-1 (Run 68) showed Wed WR=0% (0/4) — re-blocked
        self.blocked_weekdays   = frozenset(
            blocked_weekdays if blocked_weekdays is not None else (1, 2, 5)
        )

    def __repr__(self):
        return (
            f"StrategyConfig("
            f"enable_buy={self.enable_buy}, enable_sell={self.enable_sell}, "
            f"bias_4h_gate={self.bias_4h_gate!r}, trend_1h_gate={self.trend_1h_gate!r}, "
            f"dealing_range_gate={self.dealing_range_gate}, "
            f"blocked_regimes={sorted(self.blocked_regimes)}, "
            f"liquid_hours={sorted(self.liquid_hours)})"
        )


class GateResult:
    """Result of evaluate_setup(). Accepted or rejected with reason + full audit log."""

    __slots__ = ("accepted", "rejection_reason", "log")

    def __init__(self, accepted, rejection_reason, log):
        self.accepted         = accepted          # bool
        self.rejection_reason = rejection_reason  # str | None (None if accepted)
        self.log              = log               # list of (filter_name, passed, detail)

    def __repr__(self):
        if self.accepted:
            return "GateResult(ACCEPTED)"
        return f"GateResult(REJECTED: {self.rejection_reason})"


# ── Standard configs ──────────────────────────────────────────────────────────
# Constructor kwargs sourced from config.py (Phase A item #4 — centralized config).
# Defaults match the post-A-9 Run-48 baseline (WR=81.1%, n=37, z=+4.15) verbatim.
# Override any value via env var (see config.py header). To promote SELL to live:
# set LIVE_BIAS_4H_GATE=strict in env.
from config import LIVE_CONFIG_KWARGS, BACKTEST_CONFIG_KWARGS

LIVE_CONFIG     = StrategyConfig(**LIVE_CONFIG_KWARGS)
BACKTEST_CONFIG = StrategyConfig(**BACKTEST_CONFIG_KWARGS)


# ── Gate evaluation ───────────────────────────────────────────────────────────

def evaluate_setup(direction, hour, regime, bias_4h, trend_1h, config, weekday=None):
    """
    Evaluate all strategy gates in order. Returns on the FIRST failure.

    Parameters
    ----------
    direction : "BUY" or "SELL"
    hour      : UTC hour 0-23 (use datetime.now(timezone.utc).hour in live;
                ts.hour in backtest)
    regime    : regime label string, e.g. "TRENDING_BULL"
    bias_4h   : "BULLISH" | "BEARISH" | "NEUTRAL"
    trend_1h  : "BULL" | "STRONG_BULL" | "BEAR" | "STRONG_BEAR" | "NEUTRAL"
    config    : StrategyConfig instance (LIVE_CONFIG or BACKTEST_CONFIG)
    weekday   : int 0-6 (0=Mon…6=Sun), or None to skip weekday gate

    Returns
    -------
    GateResult
        .accepted         — True if all gates pass
        .rejection_reason — first failure description, or None if accepted
        .log              — list of (filter_name, passed_bool, detail_str)
                           for every gate evaluated (including the failing one)
    """
    log = []

    # 0. Weekday gate — block structurally poor days (1=Tue, 2=Wed, 5=Sat per backtest data)
    if weekday is not None and config.blocked_weekdays and weekday in config.blocked_weekdays:
        log.append(("weekday", False, f"weekday={weekday} blocked"))
        return GateResult(False, f"weekday={weekday} blocked", log)
    if weekday is not None:
        log.append(("weekday", True, f"weekday={weekday}"))

    # 1. Direction gate — controlled by config, never hardcoded in caller
    if direction == "BUY" and not config.enable_buy:
        log.append(("direction", False, "BUY disabled by config"))
        return GateResult(False, "BUY disabled", log)
    if direction == "SELL" and not config.enable_sell:
        log.append(("direction", False, "SELL disabled by config"))
        return GateResult(False, "SELL disabled", log)
    log.append(("direction", True, f"{direction} enabled"))

    # 2. Session gate — liquid hours only
    if hour not in config.liquid_hours:
        log.append(("session", False, f"hour={hour} outside liquid hours"))
        return GateResult(False, f"hour={hour} illiquid", log)
    log.append(("session", True, f"hour={hour}"))

    # 3. Regime gate — blocked regimes produce no signal
    #    sell_allowed_regimes lets specific regimes through for SELL; 4H/1H gates still apply
    if regime in config.blocked_regimes:
        if direction == "SELL" and regime in config.sell_allowed_regimes:
            log.append(("regime", True, f"{regime} allowed for SELL"))
        else:
            log.append(("regime", False, f"{regime} blocked"))
            return GateResult(False, f"regime={regime} blocked", log)
    else:
        log.append(("regime", True, f"regime={regime}"))

    # 4. 4H bias gate
    #    strict: BUY requires BULLISH; SELL requires BEARISH; NEUTRAL blocks both
    #    loose:  BUY blocks BEARISH only; SELL blocks BULLISH only; NEUTRAL allowed
    #    none:   no direction filtering — counter-trend setups allowed
    if config.bias_4h_gate == "none":
        log.append(("4h_bias", True, f"bias_4h={bias_4h} (gate disabled)"))
    elif config.bias_4h_gate == "strict":
        if direction == "BUY" and bias_4h != "BULLISH":
            log.append(("4h_bias", False, f"strict: {bias_4h} != BULLISH"))
            return GateResult(False, f"4H={bias_4h} blocks BUY (strict)", log)
        if direction == "SELL" and bias_4h != "BEARISH":
            log.append(("4h_bias", False, f"strict: {bias_4h} != BEARISH"))
            return GateResult(False, f"4H={bias_4h} blocks SELL (strict)", log)
        log.append(("4h_bias", True, f"bias_4h={bias_4h}"))
    else:  # loose
        if direction == "BUY" and bias_4h == "BEARISH":
            log.append(("4h_bias", False, "loose: BEARISH blocks BUY"))
            return GateResult(False, "4H=BEARISH blocks BUY", log)
        if direction == "SELL" and bias_4h == "BULLISH":
            log.append(("4h_bias", False, "loose: BULLISH blocks SELL"))
            return GateResult(False, "4H=BULLISH blocks SELL", log)
        log.append(("4h_bias", True, f"bias_4h={bias_4h}"))

    # 5. 1H trend gate
    #    strict: BUY requires BULL/STRONG_BULL; SELL requires BEAR/STRONG_BEAR; NEUTRAL blocks both
    #    loose:  BUY blocks BEAR/STRONG_BEAR only; SELL blocks BULL/STRONG_BULL only
    #    none:   no direction filtering — counter-trend setups allowed
    if config.trend_1h_gate == "none":
        log.append(("1h_trend", True, f"trend_1h={trend_1h} (gate disabled)"))
    elif config.trend_1h_gate == "strict":
        if direction == "BUY" and trend_1h not in ("BULL", "STRONG_BULL"):
            log.append(("1h_trend", False, f"strict: {trend_1h} not BULL/STRONG_BULL"))
            return GateResult(False, f"1H={trend_1h} blocks BUY (strict)", log)
        if direction == "SELL" and trend_1h not in ("BEAR", "STRONG_BEAR"):
            log.append(("1h_trend", False, f"strict: {trend_1h} not BEAR/STRONG_BEAR"))
            return GateResult(False, f"1H={trend_1h} blocks SELL (strict)", log)
        log.append(("1h_trend", True, f"trend_1h={trend_1h}"))
    else:  # loose
        if direction == "BUY" and trend_1h in ("STRONG_BEAR", "BEAR"):
            log.append(("1h_trend", False, f"loose: {trend_1h} blocks BUY"))
            return GateResult(False, f"1H={trend_1h} blocks BUY", log)
        if direction == "SELL" and trend_1h in ("STRONG_BULL", "BULL"):
            log.append(("1h_trend", False, f"loose: {trend_1h} blocks SELL"))
            return GateResult(False, f"1H={trend_1h} blocks SELL", log)
        log.append(("1h_trend", True, f"trend_1h={trend_1h}"))

    return GateResult(True, None, log)
