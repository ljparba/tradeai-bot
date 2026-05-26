"""
TradeAI — Centralized Configuration
====================================
Single source of truth for ALL tunable constants used by the bot.

Roadmap reference:
  • Phase A item #4 of docs/ENTERPRISE_ROADMAP.md
  • Adopt 3 of docs/TRADINGAGENTS_INVESTIGATION_AUDIT.md
  • Resolved overlap per docs/ROADMAP_AUDIT_CROSSCHECK.md §"Soft Overlaps":
    config.py owns non-secret tunables; .env / .env.vault owns secrets.

Scope:
  • All top-level numeric / string / dict / set constants from crypto_alert.py
    (signal cadence, RSI/ATR/ROC params, risk limits, kill switches, template
    safety caps, exit intelligence, regime rules, weighted scoring, etc.).
  • LIVE_CONFIG_KWARGS and BACKTEST_CONFIG_KWARGS — full StrategyConfig
    constructor arg dicts consumed by strategy_engine.py.
  • EXECUTION_MODE — validated here so every importer sees the same value.

Out of scope (intentionally):
  • ICT engine parameters (ICT_SWING_N, ICT_SWEEP_LOOKBACK, …) — owned by
    ict_engine.py because that module's constants are tightly coupled to its
    detection logic and changing them via env var would silently break the
    live-vs-backtest invariant (CROSS_REF.md C4 KNOWN STRUCTURAL).
  • Backtest-only constants (BACKTEST_DAYS, COOLDOWN_BARS, ENTRY_WINDOW,
    WARMUP_BARS, FORWARD_BARS) — owned by backtest.py for the same reason.
  • Adaptive learning hyperparameters (LEARNING_RATE, MOMENTUM, …) —
    owned by adaptive_engine.py.
  • Operational URLs / HEADERS — not tunable, would never want env override.

Env-var overrides:
  Every scalar below can be overridden by setting an env var of the same name
  before import. Type coercion is handled by the _env_* helpers; an unparseable
  value raises ValueError immediately rather than silently falling back to the
  default (fail-loud per Audit §4.1 risk #3 "silent failure modes").

Examples:
    set MAX_SL_PCT=0.025          # raise stop ceiling for one run
    set SIGNAL_COOLDOWN=20        # 20-min cooldown for stress test
    set CHECK_INTERVAL=60         # faster cycles in paper mode

Importing this module DOES NOT load any .env file. That is handled by
secrets_loader.load_env() which must run BEFORE config.py is first imported
(crypto_alert.py and backtest.py both invoke the loader at top of file).
"""
import os
from typing import Any, Callable, Optional


# ── env-var override helpers ──────────────────────────────────────────────────
# Each helper returns `default` if the env var is unset OR empty. Empty values
# treated as "unset" so a blank `set FOO=` line in env.bat doesn't crash imports.

def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"config: env var {name}={raw!r} is not a valid int") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"config: env var {name}={raw!r} is not a valid float") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    truthy = ("1", "true", "yes", "on", "y", "t")
    falsy  = ("0", "false", "no", "off", "n", "f")
    norm = raw.strip().lower()
    if norm in truthy:
        return True
    if norm in falsy:
        return False
    raise ValueError(
        f"config: env var {name}={raw!r} is not a valid bool (use 1/0, true/false, yes/no)"
    )


def _env_choice(name: str, default: str, choices: tuple) -> str:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    norm = raw.strip().upper() if all(c.isupper() for c in choices[0]) else raw.strip()
    if norm not in choices:
        raise ValueError(
            f"config: env var {name}={raw!r} not in allowed values {choices}"
        )
    return norm


# ── EXECUTION MODE (validated here, imported by everything) ───────────────────
# Set EXECUTION_MODE in env.bat / .env — never edit this line directly.
# "PAPER" = signal-only with status labels in Telegram. "LIVE" = real-money mode.
EXECUTION_MODE: str = _env_choice("EXECUTION_MODE", "PAPER", ("PAPER", "LIVE"))


# ── BINANCE / DATA SOURCE INFRASTRUCTURE ──────────────────────────────────────
BINANCE_BASE: str    = "https://api.binance.com/api/v3"
COINGECKO_GLOBAL: str = "https://api.coingecko.com/api/v3/global"
HEADERS: dict        = {"User-Agent": "Mozilla/5.0 CryptoAlertBot/1.0"}
BTC_SYMBOL: str      = "BTCUSDT"

# Token universe — 9 tokens post Run-60 (SOL excluded T-1, DOT/NEAR removed Run 47).
# Comments preserved verbatim from crypto_alert.py for traceability.
BINANCE_TOKENS: dict = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    # SOL removed: T-1 (Run 55, WR=42.9% n=7). Re-evaluated T-2 (Run 69, 2026-05-21, post-fix):
    # WR=27.3% n=11 (3W/8L) — confirmed chronic underperformer below BEW. Do not re-add.
    "XRP":  "XRPUSDT",
    "HBAR": "HBARUSDT",
    "AVAX": "AVAXUSDT",
    "LINK": "LINKUSDT",
    # Run 46-47 expansion — BNB/ADA/POL added; DOT/NEAR removed (DOT 40% WR, NEAR 28.6% — below BEW)
    # D-pilot (2026-05-24) re-evaluated DOT/NEAR against Run-168 baseline (F-8+P-2b+TP-2-b gates):
    #   DOT  Run 169: n=8, WR=37.5%, Net E=-0.26 — still bad. Overall WR drops 79.1->72.5% (-6.6pp).
    #   NEAR Run 170: n=9, WR=11.1% (1W/8L), Net E=-1.06 — WORSE than original. Overall 79.1->67.3% (-11.8pp).
    # Verdict: Both confirmed chronic underperformers across multiple gate configurations. Do not re-add.
    "BNB":  "BNBUSDT",   # Binance exchange token — top-5, massive institutional liquidity
    "ADA":  "ADAUSDT",   # Cardano — top-10, oldest alt, clean altcoin-cycle trends, 75% WR Run 47
    "POL":  "POLUSDT",   # Polygon — ETH L2 (MATIC renamed to POL Sep 2024, MATICUSDT no longer exists)
    # LTC removed: A-3 REJECTED (n=2, WR=50% — below 55% floor, insufficient sample)
    # SUI removed: B-2 REJECTED (n=3, WR=0.0% - zero win rate, fails 60% threshold)
    "TON":  "TONUSDT",   # B-4: top-9 by market cap, strong trend-following behavior (Session 4)
}

TIMEFRAMES: dict = {
    "4h":  {"interval": "4h",  "limit": 400},  # C5: EMA200 needs ~4× period to converge
    "1h":  {"interval": "1h",  "limit": 600},  # C-N3: EMA200 needs ~4× period; backtest has 8760 1H bars
    "15m": {"interval": "15m", "limit": 210},  # ICT entry timeframe
    "5m":  {"interval": "5m",  "limit": 500},  # primary ICT setup TF (Phase 4.8)
}


# ── STRATEGY VERSIONING / CADENCE ─────────────────────────────────────────────
STRATEGY_VERSION: str = _env_str("STRATEGY_VERSION", "v2")  # H5: EV scoring version tag
CHECK_INTERVAL: int   = _env_int("CHECK_INTERVAL", 90)      # seconds between cycles


# ── INDICATOR PARAMETERS ──────────────────────────────────────────────────────
RSI_PERIOD: int       = _env_int("RSI_PERIOD", 14)
RSI_OVERSOLD: int     = _env_int("RSI_OVERSOLD", 45)        # was 38 — wider zone catches intraday dips
RSI_OVERBOUGHT: int   = _env_int("RSI_OVERBOUGHT", 55)      # was 62 — wider zone catches intraday peaks
ATR_PERIOD: int       = _env_int("ATR_PERIOD", 14)
ATR_SL_MULT: float    = _env_float("ATR_SL_MULT", 1.0)      # was 1.5 — tighter SL on 15m candles
ROC_PERIOD: int       = _env_int("ROC_PERIOD", 10)
VOLUME_SPIKE: float   = _env_float("VOLUME_SPIKE", 1.2)     # was 1.4 — more sensitive volume confirm


# ── SIGNAL CADENCE / SAFETY ───────────────────────────────────────────────────
SIGNAL_COOLDOWN: int = _env_int("SIGNAL_COOLDOWN", 40)      # minutes — matches COOLDOWN_BARS=8×5min
NEAR_LEVEL_PROX: float = _env_float("NEAR_LEVEL_PROX", 0.025)  # fixed 2.5% S/R proximity
SR_LOOKBACK: int     = _env_int("SR_LOOKBACK", 50)
STALE_CANDLE_THRESHOLD: int = _env_int("STALE_CANDLE_THRESHOLD", CHECK_INTERVAL * 3)  # alert > 3 cycles old

EXPIRY_BY_REGIME: dict = {
    "TRENDING_BULL":      12,
    "TRENDING_BEAR":      12,
    "RANGING":            12,
    "HIGH_VOLATILITY":    12,
    "CHOPPY":             12,
    "LOW_VOLATILITY_CHOP": 6,
    "LIQUIDATION":         4,
    "UNKNOWN":            12,
}


# ── POSITION SIZING / RISK ────────────────────────────────────────────────────
RISK_PER_TRADE_PCT: float = _env_float("RISK_PER_TRADE_PCT", 0.01)  # 1% capital risk
MAX_POSITION_PCT: float   = _env_float("MAX_POSITION_PCT", 0.20)    # 20% notional cap (H14)
# Fix #37 (2026-05-22 cycle 11 audit): SL ceiling/floor migrated from
# ict_engine.py to config.py so operator can tighten the stop ceiling via env
# var for one run without editing source. ict_engine.py now imports these.
MAX_SL_PCT: float         = _env_float("MAX_SL_PCT", 0.030)         # ICT structural SL ceiling (3%)
MIN_SL_PCT: float         = _env_float("MIN_SL_PCT", 0.005)         # SL floor (0.5%) — must be meaningful


# ── DAILY / WEEKLY KILL SWITCHES (Task 4) ─────────────────────────────────────
MAX_DAILY_LOSS_PCT: float  = _env_float("MAX_DAILY_LOSS_PCT", 0.03)   # halt day at 3% capital loss
MAX_WEEKLY_LOSS_PCT: float = _env_float("MAX_WEEKLY_LOSS_PCT", 0.06)  # halt week at 6% capital loss
MAX_DAILY_LOSSES: int      = _env_int("MAX_DAILY_LOSSES", 3)          # halt day after N LOSS/EXPIRED
MAX_CONSECUTIVE_LOSSES: int = _env_int("MAX_CONSECUTIVE_LOSSES", 3)   # pause after N consecutive losses
SYMBOL_LOSS_COOLDOWN_H: int = _env_int("SYMBOL_LOSS_COOLDOWN_H", 2)   # hours to block a token after SL


# ── OPERATIONAL INTERVALS ─────────────────────────────────────────────────────
PERF_CHECK_INTERVAL: int = _env_int("PERF_CHECK_INTERVAL", 1800)  # 30 min between WR DB reads
HEARTBEAT_INTERVAL: int  = _env_int("HEARTBEAT_INTERVAL", 3600)   # 1 hour between liveness msgs
API_RETRIES: int         = _env_int("API_RETRIES", 2)             # H15: 3→2
API_DELAY: int           = _env_int("API_DELAY", 3)               # H15: 10s→3s
DOM_FETCH_INTERVAL: int  = _env_int("DOM_FETCH_INTERVAL", 1800)   # 30 min between dominance fetches
DOM_THRESHOLD: float     = _env_float("DOM_THRESHOLD", 0.3)       # % dominance change to flag


# ── PHASE 5A — TEMPLATE SAFETY CONTROLS ───────────────────────────────────────
TEMPLATE_MIN_SAMPLE: int       = _env_int("TEMPLATE_MIN_SAMPLE", 50)        # min closes before live exec
CIRCUIT_BREAKER_LOOKBACK: int  = _env_int("CIRCUIT_BREAKER_LOOKBACK", 20)   # rolling window for WR check
CIRCUIT_BREAKER_MIN_WR: float  = _env_float("CIRCUIT_BREAKER_MIN_WR", 0.55) # M17: raised from 0.35
BLOCK_RANGING_LIVE: bool       = _env_bool("BLOCK_RANGING_LIVE", True)      # regime safety layer

TIER_DAILY_LIVE_CAPS: dict = {  # max ACTIVE signals per template per UTC day
    "TIER_A": 3,
    "TIER_B": 2,
    "TIER_C": 0,   # hard zero — Tier C is paper/backtest only; never live
    "NONE":   1,
}
BLOCK_RANGING_TEMPLATES: set = {"TIER_B", "NONE"}  # block live exec in RANGING regime


# ── MACRO EVENT FILTER (Sprint 3 / Phase A item #4 completion) ───────────────
# Gate in generate_signal() blocks signals near FOMC/CPI/NFP windows.
# Default: disabled (advisory logging only when enabled).
# To enable blocking:  set MACRO_FILTER_ENABLED=true  MACRO_ADVISORY_ONLY=false
MACRO_FILTER_ENABLED: bool = _env_bool("MACRO_FILTER_ENABLED", False)
MACRO_ADVISORY_ONLY: bool  = _env_bool("MACRO_ADVISORY_ONLY",  True)
MACRO_PRE_WINDOW_H: int    = _env_int("MACRO_PRE_WINDOW_H",  2)   # hours before event
MACRO_POST_WINDOW_H: int   = _env_int("MACRO_POST_WINDOW_H", 1)   # hours after event


# ── EXIT INTELLIGENCE (Phase 1) ───────────────────────────────────────────────
EXIT_SUGGESTION_COOLDOWN_H: int = _env_int("EXIT_SUGGESTION_COOLDOWN_H", 6)
EXIT_MIN_COVERAGE_PCT: int      = _env_int("EXIT_MIN_COVERAGE_PCT", 35)
EXIT_PARTIAL_COVERAGE_PCT: int  = _env_int("EXIT_PARTIAL_COVERAGE_PCT", 60)
EXIT_STRONG_COVERAGE_PCT: int   = _env_int("EXIT_STRONG_COVERAGE_PCT", 82)


# ── WEIGHTED SCORING + SIGNAL THRESHOLD ───────────────────────────────────────
WEIGHTS: dict = {
    "rsi":      0.20,
    "trend":    0.25,
    "sr":       0.15,
    "mtf":      0.20,
    "volume":   0.10,
    "momentum": 0.10,
}
SIGNAL_THRESHOLD: int = _env_int("SIGNAL_THRESHOLD", 35)  # was 48 — lowered for scalp frequency


# ── REGIME RULES (signal generation behavior per market regime) ───────────────
REGIME_RULES: dict = {
    "TRENDING_BULL":       {"BUY":"ALLOW",   "SELL":"CAUTION", "min_confirms":2, "conf_bonus":1},
    "TRENDING_BEAR":       {"BUY":"CAUTION", "SELL":"ALLOW",   "min_confirms":2, "conf_bonus":1},
    "RANGING":             {"BUY":"ALLOW",   "SELL":"ALLOW",   "min_confirms":2, "conf_bonus":1},
    "HIGH_VOLATILITY":     {"BUY":"CAUTION", "SELL":"CAUTION", "min_confirms":3, "conf_bonus":0},
    "CHOPPY":              {"BUY":"BLOCK",   "SELL":"BLOCK",   "min_confirms":99,"conf_bonus":-2},
    "LOW_VOLATILITY_CHOP": {"BUY":"BLOCK",   "SELL":"BLOCK",   "min_confirms":99,"conf_bonus":-3},
    "LIQUIDATION":         {"BUY":"BLOCK",   "SELL":"BLOCK",   "min_confirms":99,"conf_bonus":-3},
    "UNKNOWN":             {"BUY":"CAUTION", "SELL":"CAUTION", "min_confirms":3, "conf_bonus":0},
}


# ── STRATEGY ENGINE GATE CONFIGS ──────────────────────────────────────────────
# Each StrategyConfig field is declared as a top-level constant so the Tune Bot
# (tracker.py) can regex-target it cleanly. The KWARGS dicts at the bottom just
# reference these names — they exist so strategy_engine.py can do **KWARGS without
# remembering every field name.
#
# Reference: Run 60 / post-A-9 baseline (WR=81.1%, n=37, z=+4.15).
# To change FVG quality in live, either edit the literal default below OR set
# env LIVE_FVG_MIN_QUALITY=MEDIUM. Tune Bot edits the default literal in-place.

# Task 11 + Run 44 — full regime block list (shared between LIVE and BACKTEST).
_DEFAULT_BLOCKED_REGIMES = (
    "CHOPPY", "HIGH_VOLATILITY", "TRENDING_BEAR",
    "LOW_VOLATILITY_CHOP", "LIQUIDATION", "RANGING",
)
# 1=Tue, 5=Sat - confirmed poor-WR days; Wed unblocked B-1 (Run 68 sample n=4-6, below 30-signal floor).
_DEFAULT_BLOCKED_WEEKDAYS = (1, 2, 5)

# liquid_hours default expression is kept as `list(range(24))` literal so the
# existing Tune Bot SESSION_LIQUID_HOURS regex (which matches `list(range(24))`
# or `[..]`) keeps working. Override via env LIQUID_HOURS=13,14,15.
_DEFAULT_LIQUID_HOURS = list(range(24))


def _liquid_hours_from_env() -> list:
    """LIQUID_HOURS=13,14,15 → [13,14,15]; unset/empty → _DEFAULT_LIQUID_HOURS."""
    raw = os.environ.get("LIQUID_HOURS")
    if raw is None or raw == "":
        return list(_DEFAULT_LIQUID_HOURS)
    hours = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            h = int(tok)
        except ValueError as exc:
            raise ValueError(f"config: LIQUID_HOURS contains non-int {tok!r}") from exc
        if not (0 <= h <= 23):
            raise ValueError(f"config: LIQUID_HOURS hour {h} not in 0..23")
        hours.append(h)
    return hours


# ── LIVE_CONFIG — per-field constants (Tune Bot anchors on these literals) ────
LIVE_ENABLE_BUY:           bool = _env_bool("LIVE_ENABLE_BUY", True)
LIVE_ENABLE_SELL:          bool = _env_bool("LIVE_ENABLE_SELL", True)     # learning phase
LIVE_BIAS_4H_GATE:         str  = _env_choice("LIVE_BIAS_4H_GATE", "none", ("strict", "loose", "none"))
LIVE_TREND_1H_GATE:        str  = _env_choice("LIVE_TREND_1H_GATE", "strict", ("strict", "loose", "none"))  # TP-2-b PROMOTED 2026-05-24 (stacked on F-8 + P-2b): loose->strict. CPCV mean 77.78->79.11%, CPCV std 7.86->5.40% (tighter), Sharpe 0.870->0.933, n=45->43.
LIVE_DEALING_RANGE_GATE:   bool = _env_bool("LIVE_DEALING_RANGE_GATE", False)  # Phase B revert 2026-05-26 (after D2 finding): true->false. The DR gate was structurally killing the strategy — 98.5% of post-FVG/post-MSS signals were blocked because ICT FVG-retrace entries sit in PREMIUM for BUY (and DISCOUNT for SELL) of the post-displacement dealing range. Live had 0/30 paper signals after weeks for this exact reason. DR-1 returns to KNOWN STRUCTURAL with documented evidence (cycle-5 D2 diagnostic at backtest.py:1378+).
LIVE_MSS_MIN_QUALITY:      str  = _env_choice("LIVE_MSS_MIN_QUALITY", "LOW", ("LOW", "MEDIUM", "HIGH"))
LIVE_FVG_MIN_QUALITY:      str  = _env_choice("LIVE_FVG_MIN_QUALITY", "HIGH", ("LOW", "MEDIUM", "HIGH"))
LIVE_SMT_GATE:             bool = _env_bool("LIVE_SMT_GATE", False)

# ── BACKTEST_CONFIG — per-field constants ─────────────────────────────────────
BACKTEST_ENABLE_BUY:           bool = _env_bool("BACKTEST_ENABLE_BUY", True)
BACKTEST_ENABLE_SELL:          bool = _env_bool("BACKTEST_ENABLE_SELL", True)
BACKTEST_BIAS_4H_GATE:         str  = _env_choice("BACKTEST_BIAS_4H_GATE", "none", ("strict", "loose", "none"))  # F-8 (2026-05-23): strict->none. D-2 reversal: 365d bias=strict over-filters (n=37, CPCV std=15.56%); bias=none restores Run-110 baseline (n=46, CPCV std=8.85%, q05=63.2%).
BACKTEST_TREND_1H_GATE:        str  = _env_choice("BACKTEST_TREND_1H_GATE", "strict", ("strict", "loose", "none"))  # TP-2-b PROMOTED 2026-05-24 — mirrors LIVE_TREND_1H_GATE for live/BT parity
BACKTEST_DEALING_RANGE_GATE:   bool = _env_bool("BACKTEST_DEALING_RANGE_GATE", False)  # Phase B revert 2026-05-26 (after D2 finding): true->false. Restored to pre-Phase-B.1 state. Both gates now OFF; DR-1 is documented KNOWN STRUCTURAL (symmetric absence preserves parity). The cycle-5 D2 diagnostic at print_report showed DR gate was blocking 98.5% of post-FVG/post-MSS signals — fundamental geometry mismatch between ICT entry pattern and dealing-range location semantics.
BACKTEST_MSS_MIN_QUALITY:      str  = _env_choice("BACKTEST_MSS_MIN_QUALITY", "LOW", ("LOW", "MEDIUM", "HIGH"))
BACKTEST_FVG_MIN_QUALITY:      str  = _env_choice("BACKTEST_FVG_MIN_QUALITY", "HIGH", ("LOW", "MEDIUM", "HIGH"))
BACKTEST_SMT_GATE:             bool = _env_bool("BACKTEST_SMT_GATE", False)


# ── KWARGS dicts consumed by strategy_engine.py ───────────────────────────────
# DO NOT inline literal values here — the per-field constants above are the
# single source of truth. Tune Bot anchors on the literals above, not here.
LIVE_CONFIG_KWARGS: dict = {
    "enable_buy":           LIVE_ENABLE_BUY,
    "enable_sell":          LIVE_ENABLE_SELL,
    "bias_4h_gate":         LIVE_BIAS_4H_GATE,
    "trend_1h_gate":        LIVE_TREND_1H_GATE,
    "dealing_range_gate":   LIVE_DEALING_RANGE_GATE,
    "mss_min_quality":      LIVE_MSS_MIN_QUALITY,
    "fvg_min_quality":      LIVE_FVG_MIN_QUALITY,
    "sell_allowed_regimes": {"TRENDING_BEAR"},  # SELL allowed when market is actually bearish
    "smt_gate":             LIVE_SMT_GATE,
    "liquid_hours":         _liquid_hours_from_env(),
    "blocked_weekdays":     _DEFAULT_BLOCKED_WEEKDAYS,
    # L-B / M-1 fix (cycle-6 audit 2026-05-26): explicitly wire the canonical
    # _DEFAULT_BLOCKED_REGIMES constant so edits here actually take effect.
    # Previously, the constant at line 281 was dead — runtime defaults came
    # from strategy_engine.py:71-77 (a different literal that coincidentally
    # matched). Classic M24-class silent-default trap.
    "blocked_regimes":      _DEFAULT_BLOCKED_REGIMES,
}

BACKTEST_CONFIG_KWARGS: dict = {
    "enable_buy":           BACKTEST_ENABLE_BUY,
    "enable_sell":          BACKTEST_ENABLE_SELL,
    "bias_4h_gate":         BACKTEST_BIAS_4H_GATE,
    "trend_1h_gate":        BACKTEST_TREND_1H_GATE,
    "dealing_range_gate":   BACKTEST_DEALING_RANGE_GATE,
    "mss_min_quality":      BACKTEST_MSS_MIN_QUALITY,
    "fvg_min_quality":      BACKTEST_FVG_MIN_QUALITY,
    "sell_allowed_regimes": {"TRENDING_BEAR"},
    "smt_gate":             BACKTEST_SMT_GATE,
    "liquid_hours":         _liquid_hours_from_env(),
    "blocked_weekdays":     _DEFAULT_BLOCKED_WEEKDAYS,
    # L-B / M-1 fix (cycle-6) — mirror live so both sides consume the same
    # canonical constant. Symmetry is the M24-prevention invariant.
    "blocked_regimes":      _DEFAULT_BLOCKED_REGIMES,
}


# ── Public API ────────────────────────────────────────────────────────────────
__all__ = [
    # mode + universe
    "EXECUTION_MODE", "BINANCE_BASE", "COINGECKO_GLOBAL", "HEADERS",
    "BTC_SYMBOL", "BINANCE_TOKENS", "TIMEFRAMES",
    # cadence
    "STRATEGY_VERSION", "CHECK_INTERVAL", "STALE_CANDLE_THRESHOLD",
    # indicators
    "RSI_PERIOD", "RSI_OVERSOLD", "RSI_OVERBOUGHT",
    "ATR_PERIOD", "ATR_SL_MULT", "ROC_PERIOD", "VOLUME_SPIKE",
    # signal safety
    "SIGNAL_COOLDOWN", "NEAR_LEVEL_PROX", "SR_LOOKBACK", "EXPIRY_BY_REGIME",
    # risk
    "RISK_PER_TRADE_PCT", "MAX_POSITION_PCT",
    "MAX_DAILY_LOSS_PCT", "MAX_WEEKLY_LOSS_PCT",
    "MAX_DAILY_LOSSES", "MAX_CONSECUTIVE_LOSSES", "SYMBOL_LOSS_COOLDOWN_H",
    # ops intervals
    "PERF_CHECK_INTERVAL", "HEARTBEAT_INTERVAL",
    "API_RETRIES", "API_DELAY", "DOM_FETCH_INTERVAL", "DOM_THRESHOLD",
    # template safety
    "TEMPLATE_MIN_SAMPLE", "CIRCUIT_BREAKER_LOOKBACK", "CIRCUIT_BREAKER_MIN_WR",
    "TIER_DAILY_LIVE_CAPS", "BLOCK_RANGING_LIVE", "BLOCK_RANGING_TEMPLATES",
    # macro event filter
    "MACRO_FILTER_ENABLED", "MACRO_ADVISORY_ONLY",
    "MACRO_PRE_WINDOW_H", "MACRO_POST_WINDOW_H",
    # exit
    "EXIT_SUGGESTION_COOLDOWN_H", "EXIT_MIN_COVERAGE_PCT",
    "EXIT_PARTIAL_COVERAGE_PCT", "EXIT_STRONG_COVERAGE_PCT",
    # weighted scoring + regime rules
    "WEIGHTS", "SIGNAL_THRESHOLD", "REGIME_RULES",
    # gate config kwargs (consumed by strategy_engine.py)
    "LIVE_CONFIG_KWARGS", "BACKTEST_CONFIG_KWARGS",
]
