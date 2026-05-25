"""
TradeAI — ICT Backtesting Engine  (Phase 4.5)
Fetches 180 days of 15M + 1H candles from Binance and runs ICT signal logic
bar-by-bar to estimate historical win rate.

Strategy: ICT Liquidity Sweep + Market Structure Shift + FVG Retracement
Primary resolution: 15M (matches ICT signal timeframe).
1H data used for directional bias + TP swing levels.

Run:    python backtest.py
Output: data/backtest_results.json  +  DB entry in data/signals.db

Note: VPN required (Binance blocked in Philippines).
"""
import argparse
import bisect
import io
import math
import os
import sys
import requests
import time
import json
import tempfile
import sqlite3
from datetime import datetime, timezone
from collections import defaultdict
from statistics import NormalDist

# Load .env / .env.vault BEFORE crypto_alert.py imports config (which reads env).
# Idempotent — safe even if crypto_alert.py runs it first.
from secrets_loader import load_env as _load_env
_load_env()

from backtest_checkpoint import (
    clear_checkpoint, compute_config_hash, describe_checkpoint,
    load_checkpoint, save_checkpoint,
)
from labeling import (
    triple_barrier_label, bootstrap_wr_ci, bootstrap_sharpe_ci,
    label_outcome_aliases,
)
# Phase A.2 (LIVE_BACKTEST_PARITY_ROADMAP.md):
# Realistic execution model. Activated via env var REALISTIC_EXECUTION=1.
# Default is OFF — when off, this import is a no-op and backtest behavior is
# byte-identical to pre-A.2. See docs/exec_model_calibration.md for tuning.
import execution  # type: ignore


class _Tee:
    """Write to both original stdout and an internal buffer simultaneously."""
    def __init__(self, original):
        self._orig = original
        self._buf  = io.StringIO()
    def write(self, s):
        self._orig.write(s)
        self._buf.write(s)
    def flush(self):
        self._orig.flush()
    def getvalue(self):
        return self._buf.getvalue()
    def __getattr__(self, name):
        return getattr(self._orig, name)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Import ICT logic + constants from main bot ───────────
from crypto_alert import (
    detect_regime,
    BINANCE_BASE, HEADERS, BINANCE_TOKENS,
    MIN_SL_PCT, MAX_SL_PCT, MAX_BREAKEVEN_WR, MIN_TP1_MULT,
    ROUND_TRIP_COST_PCT, TOKEN_RT_COST,
    # ICT detection functions
    find_ict_swings, find_eqh_eql_clusters, detect_ict_sweep, detect_ict_displacement,
    compute_ict_trade_plan,
    # Tasks 6/7/8: quality-scored detection + entry reaction
    score_ict_mss, score_ict_fvg, detect_fvg_entry_reaction,
    # Tasks 9/10: liquidity targets + SMT divergence
    compute_liquidity_targets, detect_smt_divergence,
    # ICT parameters
    ICT_SWING_N, ICT_SWEEP_LOOKBACK, ICT_DISP_MAX_LOOK,
    ICT_MSS_HORIZON, ICT_FVG_MIN_GAP, ICT_IFVG_LOOKBACK,
    ICT_FVG_SIZE_BONUS_THRESHOLD, ICT_SMT_LOOKBACK, ICT_SMT_REF_HORIZON, ICT_MIN_RR_GATE,
    ICT_IFVG_PROXIMITY_PCT, ICT_MAX_SETUP_AGE_BARS, ICT_MSS_DISP_MAX_GAP, ENTRY_REACTION_LOOKBACK,
    # Phase 4.2B: 4H bias + IFVG (single source of truth)
    get_ict_4h_bias, detect_ict_ifvg,
    # Phase 4.7: 5M iFVG precision entry
    detect_5m_ifvg_entry,
    # Task 5: dealing range context
    compute_dealing_range, DEALING_RANGE_LOOKBACK,
    # Phase I-3/4: version tag for report header
    STRATEGY_VERSION,
    # Phase 5A: safety layer constants for backtest simulation
    EXECUTION_MODE,
    TEMPLATE_MIN_SAMPLE, CIRCUIT_BREAKER_LOOKBACK, CIRCUIT_BREAKER_MIN_WR,
    TIER_DAILY_LIVE_CAPS, BLOCK_RANGING_LIVE, BLOCK_RANGING_TEMPLATES,
)
from strategy_engine import BACKTEST_CONFIG, LIVE_CONFIG, StrategyConfig, evaluate_setup, meets_quality, QUALITY_RANK
from strategy_templates import evaluate_confluences_vs_templates
from adaptive_engine import (
    _utc_to_session, label_sample_size, SAMPLE_N_OBSERVE, weight_engine,
    _QUALITY_SCORE, _SESSION_SCORE, DEFAULT_WEIGHTS as AE_DEFAULT_WEIGHTS,
)


# ── Diagnostic: gate-off config — raw ICT pattern with minimal filtering ──────
GATE_OFF_CONFIG = StrategyConfig(
    enable_buy          = True,
    enable_sell         = True,
    bias_4h_gate        = "loose",   # only blocks opposite direction (BEARISH blocks BUY, BULLISH blocks SELL)
    trend_1h_gate       = "loose",   # only blocks opposite direction
    dealing_range_gate  = False,
    mss_min_quality     = "LOW",
    fvg_min_quality     = "LOW",
    smt_gate            = False,
    blocked_regimes     = ("HIGH_VOLATILITY", "LIQUIDATION"),  # only extreme/dangerous regimes
)

# ── Diagnostic: counter-trend config — no direction filtering at all ──────────
COUNTER_TREND_CONFIG = StrategyConfig(
    enable_buy          = True,
    enable_sell         = True,
    bias_4h_gate        = "none",    # allow BUY in BEARISH 4H, SELL in BULLISH 4H
    trend_1h_gate       = "none",    # allow all 1H trends regardless of direction
    dealing_range_gate  = False,
    mss_min_quality     = "LOW",
    fvg_min_quality     = "LOW",
    smt_gate            = False,
    blocked_regimes     = ("HIGH_VOLATILITY", "LIQUIDATION"),
)

# ── Diagnostic: 4H neutral + 1H opposite trend allowed ───────────────────────
NEUTRAL_4H_CONFIG = StrategyConfig(
    enable_buy           = True,
    enable_sell          = True,
    bias_4h_gate         = "loose",   # allows NEUTRAL 4H; still blocks BEARISH→BUY, BULLISH→SELL
    trend_1h_gate        = "none",    # allows all 1H trends incl. pullbacks (SELL in BULL, BUY in BEAR)
    dealing_range_gate   = False,
    mss_min_quality      = "LOW",
    fvg_min_quality      = "LOW",
    smt_gate             = False,
    blocked_regimes      = ("CHOPPY", "HIGH_VOLATILITY", "LIQUIDATION", "LOW_VOLATILITY_CHOP", "TRENDING_BEAR"),
    sell_allowed_regimes = {"TRENDING_BEAR"},
)

# ── Active strategy config ────────────────────────────────────────────────────
# Change this ONE line to switch modes:
#   ACTIVE_CONFIG = BACKTEST_CONFIG      → research phase (BUY+SELL, strict gates) ← USE THIS NOW
#   ACTIVE_CONFIG = NEUTRAL_4H_CONFIG    → diagnostic: 4H neutral + 1H opposite trend
#   ACTIVE_CONFIG = GATE_OFF_CONFIG      → diagnostic: raw ICT pattern, minimal filtering
#   ACTIVE_CONFIG = COUNTER_TREND_CONFIG → diagnostic: counter-trend/pullback setups
#   ACTIVE_CONFIG = LIVE_CONFIG          → pre-live validation (BUY-only, loose gates)
ACTIVE_CONFIG = BACKTEST_CONFIG  # learning phase mirror — BUY+SELL, LOW quality, loose gates

_ROOT      = os.path.dirname(os.path.abspath(__file__))
BT_DB_PATH = os.path.join(_ROOT, "data", "signals.db")

def _connect():
    conn = sqlite3.connect(BT_DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn

# ── Config ──────────────────────────────────────────────────
CACHE_DIR      = os.path.join(os.path.dirname(__file__), "data", "ohlcv_cache")
BACKTEST_DAYS  = 365    # Z-0 REVERT 2026-05-23: D-1 730d reversed (Session 4 prior art docs/optimization_experiments.md L249-273; Run 111 730d=49.5%WR/0%DSR confirms 2024 dead-zone). 365d is only valid edge window.
                        # fold cycles for parameter-stability validation. WF_OOS_START_DATE stays
                        # locked at 2025-11-03 (no data snooping). IS grows from ~5.5mo to ~17.5mo;
                        # OOS sample unchanged (~18 signals). POL/MATIC rename Sept 2024 may cause
                        # partial-history for POL pre-rename — accepted gracefully (other 8 tokens
                        # get full 730d coverage).
WARMUP_BARS    = 210    # 5M bars before first signal (~17.5H warmup)
FORWARD_BARS   = 288    # 5M bars to look ahead for TP/SL = 24H  (extended for 2.0R targets)
REGIME_WINDOW  = 360    # 5M bars for rolling regime = 30H window (was 120×15M)
COOLDOWN_BARS  = 8      # rollback: F-8/F-9/F-10 reverted to F-4 level (40min); quality config
ENTRY_WINDOW   = 72     # P-3 ACCEPTED: 48→72 (4H→6H); E-1 (72→96) rejected — 0 new signals
OUTPUT_FILE    = os.path.join(_ROOT, "data", "backtest_results.json")

# Locked OOS start date — set once before optimization, never moved.
# All signals with ts >= this date form the out-of-sample set.
# Derived from the Run 60 quality config 60/40 split on 2026-05-21 (365-day window).
# Do NOT change this value to fit a new experiment — that defeats the purpose.
# STATISTICAL LIMITATION: at ~34 signals/year under the quality config, the 40% OOS
# portion of a 365-day window yields only ~14 signals. The 95% CI on OOS WR spans
# approximately ±18-26pp at that sample size — a single outcome swing changes the
# interpretation. Meaningful WR inference requires n≥30 OOS signals, achievable by
# extending BACKTEST_DAYS beyond 365 or relaxing quality gates. Until then, treat
# the reported WF gap as directional evidence only, not statistical validation.
WF_OOS_START_DATE = "2025-11-03"

# ── Cost model ───────────────────────────────────────────────
# ROUND_TRIP_COST_PCT / TOKEN_RT_COST imported from crypto_alert; TOKEN_RT_COST used per-token
SLIPPAGE_PCT   = 0.0005  # 0.05% per side (already included in ROUND_TRIP_COST_PCT; used for eff_price only)
FEE_PCT        = 0.001   # 0.10% per side (Binance taker)


# ══════════════════════════════════════════════════════════
# OGD WEIGHT LOADER
# ══════════════════════════════════════════════════════════
def load_backtest_ogd_weights() -> dict:
    """Load per-token OGD weights from backtest_token_weights table.

    Returns dict[token][feature] -> weight.  Falls back to AE_DEFAULT_WEIGHTS
    for any token/feature not present in the DB (table may not exist yet if
    bootstrap_from_backtest() has never been run).
    """
    weights: dict = {}
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT token, feature, weight FROM backtest_token_weights"
        ).fetchall()
        conn.close()
        for token, feature, weight in rows:
            if token not in weights:
                weights[token] = {}
            weights[token][feature] = weight
    except Exception as e:
        print(f"[BACKTEST] backtest_token_weights unavailable ({e}) — using AE_DEFAULT_WEIGHTS")
    return weights


# ══════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════
def _valid_candle(c):
    """Return True if the raw Binance kline c has a structurally valid OHLCV.
    Invariant: h > 0 and l > 0 and l <= o <= h and l <= cl <= h.
    Mirrors the validation in crypto_alert.py fetch_binance_candles()."""
    try:
        o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
        if h > 0 and l > 0 and l <= o <= h and l <= cl <= h:
            return True
        print(f"[BACKTEST OHLCV] Skipping malformed candle ts={c[0]} "
              f"o={c[1]} h={c[2]} l={c[3]} cl={c[4]}")
        return False
    except (ValueError, IndexError) as e:
        print(f"[BACKTEST OHLCV] Skipping unparseable candle: {e}")
        return False


_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000,
    "1d": 86_400_000, "3d": 259_200_000, "1w": 604_800_000,
}

def _interval_to_ms(interval: str) -> int:
    """Binance interval string → milliseconds. 0 for unknown (skip forming-bar drop)."""
    return _INTERVAL_MS.get(interval, 0)


def fetch_historical(symbol, interval, days):
    """Fetch full history for `days` days via paginated Binance klines."""
    start_ms = int((time.time() - (days + 5) * 86400) * 1000)
    all_raw  = []
    while True:
        try:
            r = requests.get(f"{BINANCE_BASE}/klines",
                params={"symbol": symbol, "interval": interval,
                        "startTime": start_ms, "limit": 1000},
                headers=HEADERS, timeout=15)
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            if hasattr(e, 'response') and getattr(e.response, 'status_code', None) == 429:
                _wait = int(getattr(e.response, 'headers', {}).get("Retry-After", 60))
                print(f"  [FETCH 429] {symbol} {interval}: rate limited — sleeping {_wait}s")
                time.sleep(_wait); continue
            print(f"  [FETCH ERROR] {symbol} {interval}: {e}"); break
        if not batch:
            break
        all_raw.extend(batch)
        if len(batch) < 1000:
            break
        start_ms = batch[-1][0] + 1
        time.sleep(0.25)
    all_raw = [c for c in all_raw if _valid_candle(c)]
    if not all_raw:
        return {}
    # WARN-1 (data-pipeline-validator 2026-05-23): drop the most-recent
    # candle if its open_time + interval has not elapsed — i.e., it is still
    # forming. Caching a forming bar would freeze a partial price/volume
    # snapshot into a "closed" candle on subsequent runs.
    _interval_ms = _interval_to_ms(interval)
    if _interval_ms > 0 and all_raw:
        _now_ms = int(time.time() * 1000)
        if all_raw[-1][0] + _interval_ms > _now_ms:
            all_raw = all_raw[:-1]
        if not all_raw:
            return {}
    return {
        "opens":   [float(c[1]) for c in all_raw],
        "highs":   [float(c[2]) for c in all_raw],
        "lows":    [float(c[3]) for c in all_raw],
        "closes":  [float(c[4]) for c in all_raw],
        "volumes": [float(c[5]) for c in all_raw],
        "times":   [int(c[0])   for c in all_raw],
    }


# ── OHLCV Cache ──────────────────────────────────────────────
# Cache key = symbol + interval + BACKTEST_DAYS → auto-invalidates when days changes.
# Cache hardening (data-pipeline-validator audit 2026-05-23):
#   CRIT-1: TTL enforced via fetched_at epoch in the blob (default 24h)
#   CRIT-2: atomic write — tempfile + os.replace (mirrors state_store.py pattern)
#   CRIT-3: schema validation on load — all 6 keys present + same length
#   WARN-1: forming candle dropped before save in fetch_historical()
# Use `python backtest.py --fresh` to force a refetch even within TTL.
_OHLCV_USE_CACHE = True  # set to False by --fresh flag at startup

_CACHE_SCHEMA_VERSION = 1
_CACHE_MAX_AGE_SECONDS = 24 * 3600  # 24h — prevents silent stale-data bias
_CACHE_REQUIRED_KEYS = ("opens", "highs", "lows", "closes", "volumes", "times")


def _cache_path(symbol: str, interval: str, days: int) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{symbol}_{interval}_{days}d.json")


def _cache_load(symbol: str, interval: str, days: int) -> dict | None:
    """Load cached OHLCV. Returns None on missing, stale, malformed, or
    schema-mismatched cache — caller falls through to a live fetch."""
    path = _cache_path(symbol, interval, days)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            blob = json.load(f)
    except Exception:
        return None
    if not isinstance(blob, dict):
        return None

    # CRIT-1: TTL check.
    # Future-timestamp guard (bias-detector follow-up #6): if NTP corrects
    # the clock backward after a cache write, fetched_at can be > now and
    # the cache would otherwise be treated as perpetually fresh.
    fetched_at = blob.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return None  # legacy/unstamped blob — refetch
    age = time.time() - fetched_at
    if age < 0 or age > _CACHE_MAX_AGE_SECONDS:
        return None  # stale or future-stamped — refetch

    # Schema version check (forward-compat for future format changes)
    if blob.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None

    payload = blob.get("data")
    if not isinstance(payload, dict):
        return None

    # CRIT-3: schema validation.
    # Type check on list ELEMENTS (bias-detector follow-up #3): a list of
    # strings or dicts would pass the bare isinstance(list) check but blow
    # up downstream in float arithmetic. Sample the first element of each
    # array — full-list scan is O(n*6) and unnecessary for trust.
    for k in _CACHE_REQUIRED_KEYS:
        if k not in payload or not isinstance(payload[k], list):
            return None
    lengths = {len(payload[k]) for k in _CACHE_REQUIRED_KEYS}
    if len(lengths) != 1:
        return None  # array-length mismatch
    n = next(iter(lengths))
    if n == 0:
        return None  # empty cache treated as miss
    for k in _CACHE_REQUIRED_KEYS:
        first = payload[k][0]
        if not isinstance(first, (int, float)) or isinstance(first, bool):
            return None  # non-numeric element → reject so caller refetches

    return payload


def _cache_save(data: dict, symbol: str, interval: str, days: int) -> None:
    """Atomic JSON write (CRIT-2): tempfile + fsync + os.replace.
    Mirrors state_store._atomic_write_json. Never raises — caching is
    best-effort, the backtest must still succeed if the disk is full."""
    if not data or not all(k in data for k in _CACHE_REQUIRED_KEYS):
        return
    target = _cache_path(symbol, interval, days)
    blob = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "fetched_at":     time.time(),
        "symbol":         symbol,
        "interval":       interval,
        "days":           days,
        "data":           data,
    }
    target_dir = os.path.dirname(target)
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(target) + ".",
            suffix=".tmp",
            dir=target_dir,
        )
    except OSError as e:
        print(f"[CACHE] WARNING: failed to create tempfile for {symbol}/{interval}: {e}")
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(blob, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception as e:
        print(f"[CACHE] WARNING: failed to save cache for {symbol}/{interval}: {e}")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def fetch_cached(symbol: str, interval: str, days: int) -> dict:
    """fetch_historical() with transparent disk cache. Bypass with --fresh."""
    if _OHLCV_USE_CACHE:
        cached = _cache_load(symbol, interval, days)
        if cached:
            return cached
    data = fetch_historical(symbol, interval, days)
    if data and _OHLCV_USE_CACHE:
        _cache_save(data, symbol, interval, days)
    return data


# ══════════════════════════════════════════════════════════
# PRE-COMPUTED INDICATOR SERIES  (all O(n))
# ══════════════════════════════════════════════════════════
def _ema_series(values, period):
    """EMA series seeded with SMA of first `period` bars — matches indicators.py ema()."""
    if not values or period <= 0:
        return [0.0] * len(values)
    n = len(values)
    if n < period:
        return [values[-1]] * n
    alpha = 2.0 / (period + 1)
    seed  = sum(values[:period]) / period
    out   = [seed] * period
    for v in values[period:]:
        out.append(out[-1] + alpha * (v - out[-1]))
    return out


def _atr_series(highs, lows, closes, period=14):
    n = len(closes)
    if n < 2:
        return [0.0] * n
    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i]  - closes[i - 1]),
            abs(lows[i]   - closes[i - 1]),
        ))
    atr = sum(trs[:period]) / period
    out = [0.0] * period + [atr]
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
        out.append(atr)
    return out[:n]


def _trend_from_ema(close, e50, e200):
    if close > e50 and e50 > e200: return "STRONG_BULL"
    if close > e50:                return "BULL"
    if close < e50 and e50 < e200: return "STRONG_BEAR"
    if close < e50:                return "BEAR"
    return "NEUTRAL"


def precompute_tf(candles):
    """Pre-compute EMA50 + EMA200 + ATR for a timeframe.
    Returns full OHLC arrays so ICT swing detection can use rolling slices."""
    closes = candles["closes"]
    return {
        "ema50":  _ema_series(closes, 50),
        "ema200": _ema_series(closes, 200),
        "atr":    _atr_series(candles["highs"], candles["lows"], closes),
        "times":  candles["times"],
        "closes": closes,
        "highs":  candles["highs"],
        "lows":   candles["lows"],
        "opens":  candles.get("opens", closes),
    }


def _lookup_trend(ind, ts_ms, min_bars=200):
    idx = bisect.bisect_right(ind["times"], ts_ms - 1) - 1
    if idx < min_bars:
        return "NEUTRAL"
    return _trend_from_ema(ind["closes"][idx], ind["ema50"][idx], ind["ema200"][idx])


def _lookup_4h_bias(ind4h, ts_ms, min_bars=200):
    """Binary-search the pre-computed 4H series for the most recently closed 4H bar
    at ts_ms, then compute ICT 4H bias from the last min_bars of that slice."""
    idx = bisect.bisect_right(ind4h["times"], ts_ms - 1) - 1
    if idx < min_bars:
        return "NEUTRAL"
    _N   = min(idx + 1, 210)
    i0   = idx + 1 - _N
    return get_ict_4h_bias(
        ind4h["closes"][i0 : idx + 1],
        ind4h["highs"][i0  : idx + 1],
        ind4h["lows"][i0   : idx + 1],
    )


# ══════════════════════════════════════════════════════════
# OUTCOME DETECTION
# ══════════════════════════════════════════════════════════
def check_outcome(signal, sl, tp1, tp2, tp3, future_bars):
    """
    Scan forward 5M candles to determine signal outcome.
    For BUY: checks high for TP hits, low for SL.
    For SELL: checks low for TP hits, high for SL.
    Returns: (outcome_str, tp_level_reached)
    """
    tp1_hit = tp2_hit = tp3_hit = sl_hit = False
    for bar in future_bars:
        h, l = bar["h"], bar["l"]
        if signal == "BUY":
            if not sl_hit and not tp1_hit and l <= sl: sl_hit = True; break
            if not tp1_hit and h >= tp1:               tp1_hit = True
            if tp1_hit and not tp2_hit and h >= tp2:   tp2_hit = True
            if tp2_hit and not tp3_hit and h >= tp3:   tp3_hit = True
        else:
            if not sl_hit and not tp1_hit and h >= sl: sl_hit = True; break
            if not tp1_hit and l <= tp1:               tp1_hit = True
            if tp1_hit and not tp2_hit and l <= tp2:   tp2_hit = True
            if tp2_hit and not tp3_hit and l <= tp3:   tp3_hit = True

    if sl_hit:   return "LOSS",        0
    if tp3_hit:  return "WIN",         3
    if tp2_hit:  return "PARTIAL_TP2", 2
    if tp1_hit:  return "PARTIAL_TP1", 1
    return "EXPIRED",                  0


def compute_excursions(direction, entry_price, sl, tp1, future_bars):
    """
    Phase I-4: Track MFE and MAE over the same forward window as check_outcome.
    Scanning stops when SL or TP1 is hit (same logic as check_outcome).

    BUY:  MFE = max_high - entry   |  MAE = entry - min_low
    SELL: MFE = entry - min_low    |  MAE = max_high - entry

    Returns (mfe_pct, mae_pct) as percentages of entry_price.
    Both values are always >= 0.0.
    Safety: returns (0.0, 0.0) on any missing or zero-price input.
    """
    if not future_bars or not entry_price or entry_price <= 0:
        return 0.0, 0.0
    if sl is None or tp1 is None:
        return 0.0, 0.0

    max_high = entry_price
    min_low  = entry_price

    for bar in future_bars:
        h, l = bar["h"], bar["l"]
        if h > max_high:
            max_high = h
        if l < min_low:
            min_low = l
        # Stop at same boundary as check_outcome
        if direction == "BUY":
            if l <= sl:   break   # SL hit
            if h >= tp1:  break   # TP1 hit
        else:
            if h >= sl:   break   # SL hit
            if l <= tp1:  break   # TP1 hit

    scale = 100.0 / entry_price
    if direction == "BUY":
        mfe_pct = max(0.0, (max_high - entry_price) * scale)
        mae_pct = max(0.0, (entry_price - min_low)  * scale)
    else:
        mfe_pct = max(0.0, (entry_price - min_low)  * scale)
        mae_pct = max(0.0, (max_high - entry_price)  * scale)

    return round(mfe_pct, 6), round(mae_pct, 6)


def _calc_realized_r(outcome, net_tp1_pct, net_sl_pct, sl_pct,
                     net_tp2_pct=None, net_tp3_pct=None):
    """
    Phase I-4 + Cycle 6 Fix #16 (2026-05-22): R-multiples under split-exit model.

    Canonical 50/50 partial close at TP1 with BE-stop runner:
        LOSS         : net_sl_pct / risk  (~ -1.0)
        PARTIAL_TP1  : 0.5 × net_tp1_pct / risk  (half at TP1, runner BE = 0)
        PARTIAL_TP2  : (0.5 × net_tp1_pct + 0.5 × net_tp2_pct) / risk
        WIN          : (0.5 × net_tp1_pct + 0.5 × net_tp3_pct) / risk
        EXPIRED      : 0.0
        NO_FILL/0    : 0.0

    sl_pct is stored NEGATIVE in compute_ict_trade_plan; we use abs() for risk.
    Backwards-compat: if net_tp2/tp3 absent (legacy callers), falls back to the
    pre-Cycle-6 conservative all-TP1 credit for PARTIAL_TP2/WIN.
    """
    risk = abs(sl_pct) if sl_pct is not None else 0.0
    if not risk or risk <= 0:
        return 0.0
    if outcome in ("EXPIRED", "NO_FILL"):
        return 0.0
    if outcome in ("LOSS", "SL_HIT"):
        return round(net_sl_pct / risk, 4)
    if outcome == "PARTIAL_TP1":
        return round(0.5 * net_tp1_pct / risk, 4)
    if outcome == "PARTIAL_TP2":
        if net_tp2_pct is None: return round(net_tp1_pct / risk, 4)  # legacy
        return round((0.5 * net_tp1_pct + 0.5 * net_tp2_pct) / risk, 4)
    if outcome == "WIN":
        if net_tp3_pct is None: return round(net_tp1_pct / risk, 4)  # legacy
        return round((0.5 * net_tp1_pct + 0.5 * net_tp3_pct) / risk, 4)
    return 0.0


# ══════════════════════════════════════════════════════════
# SIGNAL SIMULATION  (15M primary — ICT)
# ══════════════════════════════════════════════════════════
def run_backtest_token(token, c5m, c1h, c4h, btc_c1h=None, btc_c5m=None, config=None, ogd_weights=None):
    """Simulate ICT signal logic bar-by-bar on 5M historical data (Phase 4.8).

    TF alignment: 4H bias | 1H trend + TP levels | 5M sweep/displacement/FVG/MSS

    Flow per bar:
      1. Session filter (liquid hours)
      2. Regime gate via 1H candles (matches live bot)
      3. find_ict_swings + detect_ict_sweep on last 300 closed 5M bars (lookback=30)
      4. 4H bias gate
      5. 1H trend gate
      6. detect_ict_displacement on 5M (max_look=9 bars = 45min)
      7. score_ict_fvg on 5M
      8. score_ict_mss on 5M (horizon=30 bars = 2.5H)
      9. detect_ict_ifvg on 5M — metadata/confidence only
     10. Entry scan: next 48 5M bars whose open falls inside 5M FVG (4H window)
     11. BTC hard BLOCK filter
     12. Cooldown (12 bars = 60min per direction)
     13. 1H swing levels → compute_ict_trade_plan (structural SL + 1H liquidity TP)
     14. Forward scan: 144 5M bars = 12H outcome window
    """
    if config is None:
        config = ACTIVE_CONFIG
    n = len(c5m["closes"])
    min_bars_needed = WARMUP_BARS + FORWARD_BARS + ENTRY_WINDOW + 5
    if n < min_bars_needed:
        print(f"  [{token}] Not enough 5M data ({n} bars, need {min_bars_needed}) — skipping")
        return []

    ind1h     = precompute_tf(c1h)
    ind4h     = precompute_tf(c4h) if c4h else None
    btc_ind   = precompute_tf(btc_c1h)  if btc_c1h  else None
    btc5m_ind = precompute_tf(btc_c5m)  if btc_c5m  else None

    signals          = []
    rejection_counts = {}
    last_signal_dir  = None
    last_signal_bar  = -(COOLDOWN_BARS + 1)
    # Consumed sweeps — maps (absolute_bar_idx, round(level,6)) → True.
    # Persists across bar iterations so the same structural sweep cannot fire twice.
    # Mirrors live bot's state["consumed_sweeps"] per-token set (crypto_alert.py:215).
    consumed_sweeps_abs: dict = {}

    for i in range(WARMUP_BARS, n - FORWARD_BARS - ENTRY_WINDOW - 1):
        ts_ms = c5m["times"][i]
        ts    = datetime.utcfromtimestamp(ts_ms / 1000)

        # ── Session filter ───────────────────────────────────────────────────
        if ts.hour not in config.liquid_hours:
            continue

        # Day-of-week gate is now handled centrally by evaluate_setup() via BACKTEST_CONFIG.blocked_weekdays

        # ── Regime via 1H candles ─────────────────────────────────────────────
        # INTENTIONAL STATIC THRESHOLDS: detect_regime() is called with Python
        # defaults (adx_trend=25.0, adx_range=20.0, adx_choppy=15.0). The live
        # bot uses DriftDetector-adjusted adx_trend = clamp(rolling_mean*0.85,
        # 18, 35) per adaptive_engine.py:827-832. Retrofitting that drift state
        # into the backtest would require replaying the full ADX observation
        # history — introducing lookahead bias from the final persisted window.
        # Static thresholds are the correct conservative choice here.
        # MONITOR: crypto_alert.py main() emits [DRIFT-GATE] console/Telegram
        # warnings if live adx_trend diverges >±5.0 from the 25.0 baseline.
        # FORMING-BAR NOTE: bisect_right(..., ts_ms - 1) - 1 returns the 1H bar
        # that opened at or before the current 5M bar — the forming (unclosed) 1H bar.
        # detect_regime() consumes closes[-1] of that bar (= most recent 5M close).
        # The live bot (crypto_alert.py:1568) passes state["candles"]["1h"] which
        # also contains the forming bar in real time. Paths are symmetric — this is
        # NOT lookahead bias. Filtering to the prior closed bar would create a
        # live/backtest divergence in the opposite direction.
        idx_1h_reg = bisect.bisect_right(ind1h["times"], ts_ms - 1) - 1
        if idx_1h_reg < 40:
            continue
        _w1 = max(0, idx_1h_reg - 120)
        regime = detect_regime(
            ind1h["closes"][_w1 : idx_1h_reg + 1],
            ind1h["highs"][_w1  : idx_1h_reg + 1],
            ind1h["lows"][_w1   : idx_1h_reg + 1],
        )
        # ── ICT detection on last 300 CLOSED 5M bars ─────────────────────
        # BIAS-FIX: slice ends at i (exclusive) so bar i (the forming bar whose
        # close is not yet known at signal-detection time) is never used for
        # sweep detection, MSS confirmation, or FVG construction.
        # Entry search starts at i+1 (next bar's open) — unchanged.
        _N   = min(i, 300)
        idx0 = i - _N
        h5   = c5m["highs"][idx0  : i]
        l5   = c5m["lows"][idx0   : i]
        c5   = c5m["closes"][idx0 : i]
        o5   = c5m["opens"][idx0  : i]

        sh_5m, sl_5m = find_ict_swings(h5, l5)
        # EQH/EQL clustering (Fix #9 2026-05-22) — cluster_size flows through sweep
        # dict and feeds a quality bonus in strategy_templates.py.
        sh_clust, sl_clust = find_eqh_eql_clusters(sh_5m, sl_5m)
        # Build slice-relative consumed set from absolute indices, pruning entries
        # outside the current window. Mirrors live bot's timestamp→index remapping.
        _cs = {(abs_i - idx0, lvl)
               for (abs_i, lvl) in consumed_sweeps_abs
               if abs_i >= idx0}
        sweep = detect_ict_sweep(h5, l5, c5, sh_5m, sl_5m, lookback=ICT_SWEEP_LOOKBACK,
                                 consumed=_cs,
                                 sh_clusters=sh_clust, sl_clusters=sl_clust)
        if not sweep:
            continue
        # Recency guard: full chain (sweep→disp→FVG→MSS) must complete within 2H.
        # ICT: a setup is only valid within its originating killzone/session.
        # sweep["bar"] is slice-relative; len(c5)-1 is the latest closed bar index.
        if (len(c5) - 1) - sweep["bar"] > ICT_MAX_SETUP_AGE_BARS:
            rejection_counts["Setup too old (>ICT_MAX_SETUP_AGE_BARS)"] = (
                rejection_counts.get("Setup too old (>ICT_MAX_SETUP_AGE_BARS)", 0) + 1)
            continue

        direction = "BUY" if sweep["type"] == "SSL" else "SELL"

        # ── 4H bias + 1H trend (inputs for strategy gate) ──
        bias_4h  = _lookup_4h_bias(ind4h, ts_ms) if ind4h else "NEUTRAL"
        trend_1h = _lookup_trend(ind1h, ts_ms)

        # ── Strategy gate — single source of truth (strategy_engine.py) ──
        # All gate logic lives here; no gate checks outside this call.
        gate = evaluate_setup(
            direction, ts.hour, regime["regime"],
            bias_4h, trend_1h, config,
            weekday=ts.weekday(),
        )
        if not gate.accepted:
            rejection_counts[gate.rejection_reason] = (
                rejection_counts.get(gate.rejection_reason, 0) + 1
            )
            continue

        # ── Displacement candle on 5M (max_look=9 bars = 45min) ─
        disp_bar = detect_ict_displacement(
            sweep["bar"], o5, h5, l5, c5, sweep["type"], max_look=ICT_DISP_MAX_LOOK)
        if disp_bar is None or disp_bar + 1 >= len(c5):
            continue

        # ── FVG on 5M ────────────────────────────────────
        fvg = score_ict_fvg(disp_bar, h5, l5, o5, c5)
        if not fvg or fvg["direction"] != direction:
            continue
        if not meets_quality(fvg.get("quality", "NONE"), config.fvg_min_quality):
            rejection_counts["FVG quality too low"] = (
                rejection_counts.get("FVG quality too low", 0) + 1)
            continue
        rejection_counts["[DIAG] fvg_ok"] = rejection_counts.get("[DIAG] fvg_ok", 0) + 1

        # ── 4H dealing range context — use FVG directional edge as entry price proxy ──
        # (matches live: crypto_alert.py uses entry_bottom for BUY, entry_top for SELL)
        _n4h      = bisect.bisect_right(ind4h["times"], ts_ms - 1) if ind4h and ind4h.get("times") else 0
        _entry_ref = fvg["bottom"] if direction == "BUY" else fvg["top"]
        if ind4h and min(_n4h, DEALING_RANGE_LOOKBACK) >= 10:
            dr_4h = compute_dealing_range(
                ind4h["highs"][:_n4h], ind4h["lows"][:_n4h], _entry_ref
            )
        else:
            dr_4h = {"range_high": None, "range_low": None, "midpoint": None, "location": "UNKNOWN"}
        if config.dealing_range_gate:
            # EQUILIBRIUM: no HTF directional anchor — block both directions.
            # BUY in PREMIUM: price extended above midpoint — no discount available.
            # SELL in DISCOUNT: price below midpoint — no premium available.
            # UNKNOWN: pass through (soft-penalised by OGD 0.0 DR score).
            _dr_loc = dr_4h["location"]
            _dr_blocked = (
                _dr_loc == "EQUILIBRIUM"
                or (direction == "BUY"  and _dr_loc == "PREMIUM")
                or (direction == "SELL" and _dr_loc == "DISCOUNT")
            )
            if _dr_blocked:
                _key = f"4H DR: {_dr_loc} ({direction} misaligned)"
                rejection_counts[_key] = rejection_counts.get(_key, 0) + 1
                continue

        # ── MSS on 5M (horizon=30 bars = 2.5H) ──────────
        mss_result = score_ict_mss(
            sweep["bar"], c5, o5, h5, l5, sh_5m, sl_5m, sweep["type"], horizon=ICT_MSS_HORIZON)
        if not mss_result["confirmed"]:
            _sw = sweep["bar"]
            if sweep["type"] == "SSL":
                _in_win = [p for p in sh_5m if _sw - ICT_SWEEP_LOOKBACK <= p[0] < _sw]
                if not _in_win:
                    rejection_counts["[MSS] SSL: no recent SH"] = rejection_counts.get("[MSS] SSL: no recent SH", 0) + 1
                else:
                    rejection_counts["[MSS] SSL: CHoCH failed"] = rejection_counts.get("[MSS] SSL: CHoCH failed", 0) + 1
            else:
                _in_win = [p for p in sl_5m if _sw - ICT_SWEEP_LOOKBACK <= p[0] < _sw]
                if not _in_win:
                    rejection_counts["[MSS] BSL: no recent SL"] = rejection_counts.get("[MSS] BSL: no recent SL", 0) + 1
                else:
                    rejection_counts["[MSS] BSL: CHoCH failed"] = rejection_counts.get("[MSS] BSL: CHoCH failed", 0) + 1
            continue
        # ICT sequence: MSS must fire AFTER the sweep bar (logical minimum).
        # MSS-T1 BUG FIX: original mss_bar<=disp_bar+1 was over-strict.
        # In fast ICT setups, the displacement candle IS the CHoCH — mss_bar=disp_bar is valid.
        # Only block truly impossible pre-sweep MSS (mss_bar <= sweep["bar"]).
        if mss_result["mss_bar"] <= sweep["bar"]:
            rejection_counts["MSS sequence (fired before sweep — impossible)"] = (
                rejection_counts.get("MSS sequence (fired before sweep — impossible)", 0) + 1)
            continue
        # Fix #10 (2026-05-22): require MSS to confirm within ICT_MSS_DISP_MAX_GAP bars
        # of the displacement bar. >6 bars (30min on 5M) means the FVG built on disp_bar
        # is structurally stale by the time MSS confirms — weakest ICT pattern.
        if mss_result["mss_bar"] - disp_bar > ICT_MSS_DISP_MAX_GAP:
            rejection_counts[f"FVG stale vs MSS (gap > {ICT_MSS_DISP_MAX_GAP} bars)"] = (
                rejection_counts.get(f"FVG stale vs MSS (gap > {ICT_MSS_DISP_MAX_GAP} bars)", 0) + 1)
            continue
        if not meets_quality(mss_result.get("quality", "NONE"), config.mss_min_quality):
            rejection_counts["MSS quality too low"] = (
                rejection_counts.get("MSS quality too low", 0) + 1)
            continue

        # ── SMT divergence — use BTC 5M (matches setup TF) ──
        _smt_ref = btc5m_ind if btc5m_ind else btc_ind
        if _smt_ref:
            _idx_smt  = bisect.bisect_right(_smt_ref["times"], ts_ms - 1) - 1
            _n_smt    = min(_idx_smt + 1, ICT_SMT_LOOKBACK + ICT_SMT_REF_HORIZON)
            if _n_smt >= ICT_SMT_LOOKBACK + ICT_SMT_REF_HORIZON:
                i0_smt  = _idx_smt + 1 - _n_smt
                smt_result = detect_smt_divergence(
                    sweep["type"],
                    ref_h=_smt_ref["highs"][i0_smt : _idx_smt + 1],
                    ref_l=_smt_ref["lows"][i0_smt  : _idx_smt + 1],
                    lookback=ICT_SMT_LOOKBACK, reference_horizon=ICT_SMT_REF_HORIZON,
                )
            else:
                smt_result = {"smt_confirmed": False, "smt_type": "NONE",
                              "reason": "insufficient BTC data"}
        else:
            smt_result = {"smt_confirmed": False, "smt_type": "NONE",
                          "reason": "no BTC reference"}
        if config.smt_gate and not smt_result["smt_confirmed"]:
            rejection_counts["SMT not confirmed"] = (
                rejection_counts.get("SMT not confirmed", 0) + 1)
            continue

        # ── iFVG on 5M — metadata + precision entry zone ────────────────────
        ifvg_meta    = detect_ict_ifvg(h5, l5, c5, direction)
        ifvg_5m_meta = detect_5m_ifvg_entry(h5, l5, c5, fvg["top"], fvg["bottom"], direction)

        # Always use full FVG entry zone — 5M iFVG precision entry reduced WR by 10.3pp (Run 41)
        entry_top    = fvg["top"]
        entry_bottom = fvg["bottom"]

        # ── Entry: first 5M bar inside FVG with prior reaction (P1-A gate) ──
        # Require MIDPOINT_RECLAIM or REACTION_CONFIRMED on the closed bars
        # immediately before the candidate entry bar. ZONE_TOUCH (no bullish/
        # bearish reaction at the zone) is skipped — those entries have 17.9% WR.
        entry_bar      = None
        entry_price    = None
        entry_reaction = {"entry_type": "ZONE_TOUCH"}
        for j in range(i + 1, min(i + 1 + ENTRY_WINDOW, n)):
            o = c5m["opens"][j]
            if not (entry_bottom <= o <= entry_top):
                continue
            _r_start = max(0, j - ENTRY_REACTION_LOOKBACK)
            _react   = (detect_fvg_entry_reaction(
                            c5m["highs"][_r_start  : j],
                            c5m["lows"][_r_start   : j],
                            c5m["opens"][_r_start  : j],
                            c5m["closes"][_r_start : j],
                            entry_top, entry_bottom, direction,
                        ) if j > _r_start else {"entry_type": "ZONE_TOUCH"})
            if _react["entry_type"] == "ZONE_TOUCH":
                rejection_counts["Entry: no FVG reaction"] = (
                    rejection_counts.get("Entry: no FVG reaction", 0) + 1)
                continue
            entry_bar      = j
            entry_price    = o
            entry_reaction = _react
            break
        if entry_bar is None:
            continue

        # ── Phase A.2: Realistic execution model ─────────────────────────
        # Off by default (REALISTIC_EXECUTION=0). When on, the model overrides
        # entry_price with the simulated fill price and may reject the signal
        # entirely (no_fill / stale_move) or assign a partial fill (50% size).
        # Default OFF preserves byte-identical backtest output vs pre-A.2.
        # See docs/exec_model_calibration.md.
        fill_size_pct       = 1.0     # full fill by default
        realistic_cost_pct  = None    # None → plan uses default TOKEN_RT_COST
        if os.environ.get("REALISTIC_EXECUTION", "0") == "1":
            # ATR(14) on last 14 closed 5M bars — needed for stale-move reject.
            _atr_n = min(14, len(h5) - 1)
            if _atr_n >= 2:
                _tr_sum = 0.0
                for _k in range(1, _atr_n + 1):
                    _hh = h5[-_k]; _ll = l5[-_k]; _pc = c5[-_k - 1]
                    _tr_sum += max(_hh - _ll, abs(_hh - _pc), abs(_ll - _pc))
                _atr_5m_abs = _tr_sum / _atr_n
            else:
                _atr_5m_abs = (abs(h5[-1] - l5[-1])
                               if h5 else max(entry_price * 0.005, 1e-6))
            _atr_ratio_val = float(regime.get("atr_ratio", 1.0))
            _seed = execution.derive_seed(ts, token, direction)
            _er = execution.simulate_execution(
                signal_ts=ts,
                signal_price=c5[-1],
                next_bar_open=o,
                token=token,
                direction=direction,
                regime=regime["regime"],
                atr_5m=_atr_5m_abs,
                atr_ratio=_atr_ratio_val,
                seed=_seed,
            )
            if _er.status == "REJECTED":
                _reject_key = f"Execution: {_er.reason}"
                rejection_counts[_reject_key] = rejection_counts.get(_reject_key, 0) + 1
                continue
            entry_price        = _er.fill_price
            fill_size_pct      = _er.fill_size_pct
            realistic_cost_pct = _er.total_cost_pct

        ts_entry_ms = c5m["times"][entry_bar]

        # ── EV gate (C-N2 KNOWN STRUCTURAL — see CROSS_REF.md) ─────────────────────
        # Live `compute_ev_score` (crypto_alert.py:2400-2422) blocks signals with
        # NEGATIVE expected-value in their (token, regime, sweep_type, dr_location,
        # mss_quality, fvg_quality) bucket once sample_n ≥ SAMPLE_N_USABLE.
        # Backtest does NOT replicate this gate today. Currently inert in live too
        # (N_closed_live = 0). Re-validate this divergence after paper trading
        # produces ≥30 closed signals per (regime, sweep_type) bucket. Until then,
        # backtest WR is an upper bound on live WR by the amount this gate would
        # filter once active. See CROSS_REF.md row C-N2 for activation conditions.
        # TODO(post-paper): implement compute_backtest_ev_score() querying
        # backtest_signals with ts < ts_entry_ms AND run_id != current_run_id.

        # ── BTC correlation filter (C-N1 HARMONIZED 2026-05-22) ────────────────────
        # Live `get_btc_filter` (crypto_alert.py:1596-1644) BLOCKS only when:
        #   feed_unavailable OR (btc_bear AND dom_dir == "RISING")
        # Otherwise it returns CAUTION/-1 conf for counter-trend, ALLOW/+1 for aligned.
        # Backtest cannot replicate the dom_dir gate (no historical CoinGecko dominance
        # series), so the unconditional `if btc_bear: continue` previously here was
        # STRICTER than live in BOTH directions — backtest rejected signals live
        # ALLOWED with a -1 conf penalty. That created bidirectional WR bias.
        # Resolution: no BTC-trend BLOCK in backtest. This matches live's behavior in
        # the common case (~75% of bearish-BTC time when dom is not RISING). Backtest
        # remains slightly looser than live during the rare BTC-bear + dom-rising
        # windows (typically heavy alt-bleed days, when no one should be long alts
        # anyway). Net effect: backtest signal population ≈ live's signal population.
        # The conf_bonus path (-1 for counter-trend) is not modeled in backtest today;
        # this is a separate divergence (CF-1 KNOWN STRUCTURAL).
        # if btc_ind:
        #     btc_trend = _lookup_trend(btc_ind, ts_entry_ms)
        #     btc_bear  = btc_trend in ("BEAR", "STRONG_BEAR")
        #     btc_bull  = btc_trend in ("BULL", "STRONG_BULL")
        #     if direction == "BUY"  and btc_bear: continue
        #     if direction == "SELL" and btc_bull: continue

        # ── Cooldown (per-direction, 15M bar index) ───────
        # Anchor to detection bar i (matches live: now captured at detection time).
        if last_signal_dir == direction and (i - last_signal_bar) < COOLDOWN_BARS:
            continue

        last_signal_dir = direction
        last_signal_bar = i
        # Mark this sweep consumed so it cannot re-fire on subsequent bars.
        # sweep["bar"] is slice-relative; convert to absolute by adding idx0.
        consumed_sweeps_abs[(idx0 + sweep["bar"], round(sweep["level"], 6))] = True

        # ── 1H swing levels for TP (look back 200 1H bars) ─
        idx_1h = bisect.bisect_right(ind1h["times"], ts_entry_ms - 1)
        _N1    = min(idx_1h, 200)
        if _N1 < 5:
            continue
        sh_1h_raw, sl_1h_raw = find_ict_swings(
            ind1h["highs"][idx_1h - _N1 : idx_1h],
            ind1h["lows"][idx_1h  - _N1 : idx_1h],
        )
        sh_1h_lvl = [lev for _, lev in sh_1h_raw[-20:]]
        sl_1h_lvl = [lev for _, lev in sl_1h_raw[-20:]]

        # ROUND_TRIP_COST_PCT (0.30%) already includes 0.05%/side slippage — no separate adjustment.
        eff_price  = entry_price

        # ── Liquidity target pool for TP (Task 9) ─────────
        _n4h_tp = bisect.bisect_right(ind4h["times"], ts_entry_ms - 1) if ind4h else 0
        extra_liq_bt = compute_liquidity_targets(
            eff_price, direction, sh_1h_lvl, sl_1h_lvl,
            highs_4h=ind4h["highs"][:_n4h_tp] if ind4h else (),
            lows_4h=ind4h["lows"][:_n4h_tp]   if ind4h else (),
            highs_1h=ind1h["highs"][:idx_1h],
            lows_1h=ind1h["lows"][:idx_1h],
            dr_4h=dr_4h,
            utc_hour=datetime.utcfromtimestamp(ts_entry_ms / 1000).hour,
        )

        # ── ICT trade plan (structural SL, liquidity-pool TP) ─
        sweep_wick = sweep["sweep_low"] if direction == "BUY" else sweep["sweep_high"]
        plan = compute_ict_trade_plan(
            eff_price, direction, sweep_wick, sh_1h_lvl, sl_1h_lvl,
            extra_liq=extra_liq_bt, token=token)
        if not plan:
            continue
        if plan["rr1"] < ICT_MIN_RR_GATE:
            rejection_counts[f"R:R {plan['rr1']}x < {ICT_MIN_RR_GATE}x minimum"] = (
                rejection_counts.get(f"R:R {plan['rr1']}x < {ICT_MIN_RR_GATE}x minimum", 0) + 1)
            continue

        # ── Phase A.2: apply realistic-execution cost delta to plan ──────────
        # If simulate_execution gave us a token-and-time-specific cost different
        # from the default TOKEN_RT_COST baked into the plan, subtract the
        # delta from all net_* fields. Price levels (sl/tp1/tp2/tp3) unchanged;
        # only the net P&L scales. No-op when realistic_cost_pct is None.
        if realistic_cost_pct is not None:
            _baseline_cost = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT)
            _delta_pct = (realistic_cost_pct - _baseline_cost) * 100  # plan uses pct (0-100)
            if _delta_pct:
                plan = dict(plan)  # avoid mutating shared returned dict
                plan["net_tp1_pct"] = round(plan["net_tp1_pct"] - _delta_pct, 4)
                if plan.get("net_tp2_pct") is not None:
                    plan["net_tp2_pct"] = round(plan["net_tp2_pct"] - _delta_pct, 4)
                if plan.get("net_tp3_pct") is not None:
                    plan["net_tp3_pct"] = round(plan["net_tp3_pct"] - _delta_pct, 4)
                plan["net_sl_pct"] = round(plan["net_sl_pct"] - _delta_pct, 4)
                # Recompute net_rr1 with adjusted values; guard against /0.
                _abs_net_sl = abs(plan["net_sl_pct"])
                if _abs_net_sl > 1e-9:
                    plan["net_rr1"] = round(abs(plan["net_tp1_pct"] / plan["net_sl_pct"]), 2)

        # ── Confidence — OGD-weighted ICT quality score (aligned with live formula) ─
        fvg_size_pct  = (fvg["top"] - fvg["bottom"]) / max(eff_price, 1e-10) * 100
        _ifvg_spatially_valid = False
        if ifvg_meta.get("ifvg_present"):
            _ifvg_mid = (ifvg_meta.get("ifvg_top", 0.0) + ifvg_meta.get("ifvg_bottom", 0.0)) / 2
            _fvg_mid  = (fvg["top"] + fvg["bottom"]) / 2
            _ifvg_spatially_valid = abs(_ifvg_mid - _fvg_mid) / max(_fvg_mid, 1e-10) <= ICT_IFVG_PROXIMITY_PCT
        ifvg_bonus    = +1 if _ifvg_spatially_valid else 0  # Run 44 + spatial gate: iFVG within 3% of FVG mid
        # C-E (audit 2026-05-25): flipped from penalty to bonus. Strategy templates
        # already award +0.10 SMT_bonus per Run #85 finding (SMT=True 78.8% WR vs
        # 66.7% without). Confidence integer path was missed in Fix #31 — see
        # CROSS_REF.md TPL-SMT entry (now PARTIAL FIX → resolved).
        smt_bonus     = +1 if smt_result.get("smt_confirmed") else 0
        # SESSION-FIX: use signal DETECTION bar (ts.hour) — not entry bar — so
        # template matching and the stored "session" field are consistent.
        # The stored field at line ~736 uses ts.hour; using entry bar here caused
        # a mismatch where template Tier was assigned to a different session bucket.
        _bt_session   = _utc_to_session(ts.hour)
        _dr_loc       = dr_4h.get("location", "UNKNOWN")
        if direction == "BUY":
            _trend_score = {"STRONG_BULL": 1.0, "BULL": 0.65, "NEUTRAL": 0.25,
                            "BEAR": 0.0, "STRONG_BEAR": 0.0}.get(trend_1h, 0.25)
            _dr_score    = {"DISCOUNT": 1.0, "EQUILIBRIUM": 0.5,
                            "PREMIUM": 0.0, "UNKNOWN": 0.25}.get(_dr_loc, 0.25)
        else:
            _trend_score = {"STRONG_BEAR": 1.0, "BEAR": 0.65, "NEUTRAL": 0.25,
                            "BULL": 0.0, "STRONG_BULL": 0.0}.get(trend_1h, 0.25)
            _dr_score    = {"PREMIUM": 1.0, "EQUILIBRIUM": 0.5,
                            "DISCOUNT": 0.0, "UNKNOWN": 0.25}.get(_dr_loc, 0.25)
        _raw_scores   = {
            "fvg_quality":    _QUALITY_SCORE.get(fvg.get("quality", "NONE"), 0.0),
            "mss_quality":    _QUALITY_SCORE.get(mss_result.get("quality", "NONE"), 0.0),
            "session":        _SESSION_SCORE.get(_bt_session, 0.0),
            "trend_strength": _trend_score,
            "dr_location":    _dr_score,
        }
        # Always use AE_DEFAULT_WEIGHTS for backtest confidence scoring.
        # Loading prior OGD weights from backtest_token_weights would make confidence
        # scores dependent on prior optimizer run history (inter-run contamination).
        # The bootstrap at end of each run still writes to backtest_token_weights for
        # paper trading warm-start — that path is unaffected by this change.
        _feat_w       = {f: AE_DEFAULT_WEIGHTS.get(f, 0.0) for f in _raw_scores}
        _w_total      = sum(_feat_w.values())
        _ogd_qual     = (sum(_raw_scores[f] * _feat_w[f] for f in _raw_scores) / _w_total
                         if _w_total > 0 else 0.5)
        confidence    = max(5, min(int(5 + _ogd_qual * 5) + ifvg_bonus + smt_bonus, 10))
        # Confidence floor check — backtest uses the static initial floor (5).
        # Live applies adaptive increments from load_performance_state() (_conf_floor,
        # _signal_threshold_adj, _wr_extra). Those adaptive layers are KNOWN STRUCTURAL
        # divergence: they only activate after live signals accumulate, so backtest
        # (which has no live history) correctly models the bot's fresh-start behavior.
        if confidence < 5:
            rejection_counts["confidence below floor"] = (
                rejection_counts.get("confidence below floor", 0) + 1)
            continue

        ts_str = datetime.utcfromtimestamp(ts_entry_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

        # ── Strategy Variant Tagging (Phase I-2) ──────────────────────────────
        _vf = {
            "direction":     direction,
            "mss_quality":   mss_result.get("quality", "NONE"),
            "fvg_quality":   fvg.get("quality",        "NONE"),
            "session":       _bt_session,
            "dr_location":   dr_4h["location"],
            "smt_confirmed": smt_result.get("smt_confirmed", False),
            "entry_type":    entry_reaction.get("entry_type", "ZONE_TOUCH"),
            "bias_4h":       bias_4h,
            "ifvg_present":  _ifvg_spatially_valid,
            "sweep_cluster_size": sweep.get("cluster_size", 1),  # Fix #9: EQH/EQL bonus
        }
        _vm           = evaluate_confluences_vs_templates(_vf)
        _best_vm      = next((m for m in _vm if m.is_match), None)
        _bt_tmpl_id   = _best_vm.template_id if _best_vm else "NONE"
        _bt_tmpl_scr  = json.dumps({m.template_id: round(m.score, 4) for m in _vm})

        # ── Forward scan on 5M bars (12H = 144 bars) ──────
        future = [
            {"h": c5m["highs"][j], "l": c5m["lows"][j]}
            for j in range(entry_bar + 1, min(entry_bar + 1 + FORWARD_BARS, n))
        ]
        outcome, tp_reached = check_outcome(
            direction, plan["sl"], plan["tp1"], plan["tp2"], plan["tp3"], future)

        # Phase A item #2: triple-barrier label (de Prado AFML §3.4).
        # Honest ternary label keyed on the SAME forward window and SAME SL/TP1
        # as check_outcome — guarantees label-consistency for downstream CPCV.
        _tb = triple_barrier_label(
            direction, eff_price, plan["sl"], plan["tp1"],
            future, t1_bars=FORWARD_BARS,
        )

        # Phase I-4: excursion metrics
        _mfe_pct, _mae_pct = compute_excursions(
            direction, eff_price, plan["sl"], plan["tp1"], future)
        _real_r = _calc_realized_r(
            outcome, plan["net_tp1_pct"], plan["net_sl_pct"], plan["sl_pct"],
            net_tp2_pct=plan.get("net_tp2_pct"),
            net_tp3_pct=plan.get("net_tp3_pct"))

        # ── Phase A.2: scale realized R by realized fill size ────────────────
        # A 50% partial fill produces 50% of the full-fill P&L impact (in either
        # direction — WIN, PARTIAL_TP1/TP2, LOSS, or EXPIRED). REJECTED signals
        # were filtered above, so fill_size_pct here is always in {0.5, 1.0}.
        if fill_size_pct < 1.0 and _real_r is not None:
            _real_r = round(_real_r * fill_size_pct, 4)

        signals.append({
            "token":        token,
            "signal":       direction,
            "price":        round(eff_price, 6),
            "ts":           ts_str,
            "regime":       regime["regime"],
            "confidence":   confidence,
            "wscore":       round(fvg_size_pct, 3),  # FVG size % (replaces weighted score)
            "margin":       round(plan["rr1"], 2),    # gross R:R (replaces margin)
            "conflict":     "LOW",
            "tp1_pct":      plan["tp1_pct"],
            "sl_pct":       plan["sl_pct"],
            "rr1":          plan["rr1"],
            "net_tp1_pct":  plan["net_tp1_pct"],
            "net_tp2_pct":  plan.get("net_tp2_pct"),  # Fix #16: split-exit model
            "net_tp3_pct":  plan.get("net_tp3_pct"),  # Fix #16: split-exit model
            "net_sl_pct":   plan["net_sl_pct"],
            "net_rr1":      plan["net_rr1"],
            "breakeven_wr": plan["breakeven_wr"],
            "tp_reached":   tp_reached,
            "outcome":      outcome,
            "sweep_type":   sweep["type"],
            "fvg_pct":      round(fvg_size_pct, 3),
            "trend_1h":     trend_1h,
            "bias_4h":      bias_4h,
            "ifvg_present":   int(_ifvg_spatially_valid),
            "ifvg_direction":  ifvg_meta["ifvg_direction"] or "",
            "ifvg_age_bars":   ifvg_meta["ifvg_age_bars"],
            "ifvg_5m_used":    int(ifvg_5m_meta["ifvg_5m_found"]),
            "dr4h_location":   dr_4h["location"],
            "mss_quality":     mss_result.get("quality", "NONE"),
            "fvg_quality":     fvg.get("quality", "NONE"),
            "entry_type":      entry_reaction.get("entry_type", "ZONE_TOUCH"),
            "smt_confirmed":   int(smt_result.get("smt_confirmed", False)),
            "smt_type":        smt_result.get("smt_type", "NONE"),
            "tp1_target_type": plan.get("tp1_target_type", ""),
            "tp2_target_type": plan.get("tp2_target_type", ""),
            # Task 12: session awareness
            "session":         _utc_to_session(ts.hour),
            "day_of_week":     ts.weekday(),   # 0=Mon … 6=Sun
            "hour_utc":        ts.hour,
            # Phase I-2: strategy variant tagging
            "matched_template_id":  _bt_tmpl_id,
            "template_scores_json": _bt_tmpl_scr,
            # Phase I-4: excursion tracking
            "mfe_pct":    _mfe_pct,
            "mae_pct":    _mae_pct,
            "realized_r": _real_r,
            # Phase A item #2: triple-barrier label (de Prado canonical)
            "tb_bin":     _tb["bin"],
            "tb_touch":   _tb["touch"],
            "tb_ret":     _tb["ret"],
            "tb_t1":      _tb["t1"],
        })

    if rejection_counts:
        top = sorted(rejection_counts.items(), key=lambda x: -x[1])[:20]
        print(f"  Gate rejections: " + " | ".join(f"{r}×{n}" for r, n in top))

    return signals


# ══════════════════════════════════════════════════════════
# REPORT
# ══════════════════════════════════════════════════════════
def is_win(outcome):
    return outcome in ("WIN", "PARTIAL_TP2", "PARTIAL_TP1")

def wr(sigs):
    if not sigs: return 0.0
    return sum(1 for s in sigs if is_win(s["outcome"])) / len(sigs) * 100

def _wilson_ci(n: int, wins: int, z: float = 1.96) -> tuple:
    """Wilson score 95% CI for a proportion. Returns (lo_pct, hi_pct).

    Fix #15 (Cycle 5, 2026-05-22): added to backtest reports so the noise level
    is visible alongside every WR figure. Prevents acting on statistically
    meaningless sub-group differences (e.g. 'Thu 91.7% WR on n=12' has Wilson
    CI ≈ [64%, 99%] — half the range is consistent with a coin flip).
    Mirrors the implementation in tracker.py:720.
    """
    if n <= 0:
        return (0.0, 100.0)
    p      = wins / n
    denom  = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    lo = max(0.0,   round((centre - margin) / denom * 100, 1))
    hi = min(100.0, round((centre + margin) / denom * 100, 1))
    return (lo, hi)

def _wr_with_ci(sigs) -> str:
    """Return 'WR XX.X% [lo-hi%]' suitable for inline display."""
    n = len(sigs)
    if n == 0:
        return "0.0% [n=0]"
    w = sum(1 for s in sigs if is_win(s["outcome"]))
    pct = w / n * 100
    lo, hi = _wilson_ci(n, w)
    return f"{pct:.1f}% [{lo:.0f}-{hi:.0f}%]"


def _realized_pnl_pct(s: dict) -> float:
    """Cycle 6 Fix #16 (2026-05-22): Compute realized P&L under the canonical ICT
    split-exit model — half-position closes at TP1, runner trails with BE stop.

    Outcomes:
      LOSS        : full -|net_sl_pct| (SL hits before any TP — full position)
      PARTIAL_TP1 : 0.5 × net_tp1_pct  (half at TP1, runner exits at BE = 0)
      PARTIAL_TP2 : 0.5 × net_tp1_pct + 0.5 × net_tp2_pct
      WIN         : 0.5 × net_tp1_pct + 0.5 × net_tp3_pct
      EXPIRED     : 0  (window expired, no fill anywhere; BE never hit either)
      NO_FILL     : 0

    Previously every WIN/PARTIAL was credited net_tp1_pct on the FULL position
    — understated TP3 wins and overstated PARTIAL_TP1. This function is the
    central P&L calculation used by all aggregation sites (_net_exp, OVERALL
    display, cumulative drawdown, profit factor, per-token table, etc.)

    Backwards-compat: signals from prior DB rows without net_tp2/tp3 fall back
    to the old all-TP1 credit, so historical comparisons still load.
    """
    outcome = s.get("outcome", "")
    n_tp1 = s.get("net_tp1_pct", 0.0) or 0.0
    n_sl  = s.get("net_sl_pct",  0.0) or 0.0
    n_tp2 = s.get("net_tp2_pct", None)
    n_tp3 = s.get("net_tp3_pct", None)
    if outcome == "LOSS":
        return n_sl
    if outcome == "PARTIAL_TP1":
        return 0.5 * n_tp1
    if outcome == "PARTIAL_TP2":
        if n_tp2 is None: return n_tp1  # legacy fallback
        return 0.5 * n_tp1 + 0.5 * n_tp2
    if outcome == "WIN":
        if n_tp3 is None: return n_tp1  # legacy fallback
        return 0.5 * n_tp1 + 0.5 * n_tp3
    return 0.0  # EXPIRED, NO_FILL


def _net_exp(sigs):
    """Net expectancy %/trade for a subset of signals.
    Cycle 6 Fix #16: uses split-exit P&L per outcome via _realized_pnl_pct().
    Previously used wr_f × avg_net_tp1_pct + (1-wr_f) × avg_net_sl_pct, which
    credited all wins at TP1's value — now each outcome contributes its actual
    realized P&L under the 50/50 split + BE-stop model.
    """
    if not sigs: return 0.0
    return sum(_realized_pnl_pct(s) for s in sigs) / len(sigs)

def _z_score(sigs):
    """One-sample z-test: observed WR vs average BEW (null = BEW, no-edge)."""
    n = len(sigs)
    if n < 2: return 0.0
    p = sum(s["breakeven_wr"] for s in sigs) / n   # BEW fraction
    w = sum(1 for s in sigs if is_win(s["outcome"])) / n
    if p <= 0 or p >= 1: return 0.0
    return (w - p) / math.sqrt(p * (1 - p) / n)

def _wf_gap_sub(sigs):
    """Walk-forward gap for an arbitrary subset.
    Always uses WF_OOS_START_DATE boundary — returns nan if subset has no signals
    on one side (incomparable WF gaps across subsets with different boundaries)."""
    if len(sigs) < 5: return float("nan")
    if WF_OOS_START_DATE:
        train = [s for s in sigs if s["ts"] < WF_OOS_START_DATE]
        test  = [s for s in sigs if s["ts"] >= WF_OOS_START_DATE]
        if not train or not test:
            return float("nan")
        return round(_wr(train) - _wr(test), 1)
    # Fallback when no date boundary is set
    train, test, _ = walk_forward_split(sigs)
    if not test: return float("nan")
    return round(_wr(train) - _wr(test), 1)

def print_report(all_signals):
    if not all_signals:
        print("\nNo signals generated — check VPN / Binance connection.")
        return

    _cfg  = ACTIVE_CONFIG
    _dirs = ("BUY+SELL" if (_cfg.enable_buy and _cfg.enable_sell)
             else "BUY-only" if _cfg.enable_buy else "SELL-only")
    _mode = "LIVE MIRROR" if _cfg is LIVE_CONFIG else "RESEARCH"
    div = "=" * 68
    print(f"\n{div}")
    print(f"  ICT BACKTEST REPORT — Last {BACKTEST_DAYS} Days  (5M resolution)")
    print(f"  Mode     : {_mode} | Directions: {_dirs}")
    _rpt_sell_ok = sorted(_cfg.sell_allowed_regimes) if _cfg.sell_allowed_regimes else []
    _rpt_sok_str = f" | SELL-ok: {', '.join(_rpt_sell_ok)}" if _rpt_sell_ok else ""
    print(f"  Gates    : 4H={_cfg.bias_4h_gate} | 1H={_cfg.trend_1h_gate} | Blocked: {', '.join(sorted(_cfg.blocked_regimes))}{_rpt_sok_str}")
    print(f"  Strategy : Liquidity Sweep + MSS + FVG + 5M iFVG Precision")
    print(f"  Entry    : 5M open inside entry zone (up to {ENTRY_WINDOW} bar window = 4H)")
    print(f"  Outcome  : {FORWARD_BARS} × 5M bars = {FORWARD_BARS//12}H window | TP = 1H swing levels")
    print(f"  Costs    : Fee {FEE_PCT*100:.2f}%/side + Slip {SLIPPAGE_PCT*100:.3f}%/side "
          f"({ROUND_TRIP_COST_PCT*100:.2f}% RT) | MaxSL {MAX_SL_PCT*100:.0f}% | BEW≤{MAX_BREAKEVEN_WR:.0%}")
    print(f"  NOTE(M11): Portfolio limits (MAX_OPEN_POSITIONS=4, MAX_SAME_DIRECTION=2) not simulated.")
    print(f"             Non-binding at current signal rate (~3-4/month). Re-evaluate if rate >8/month.")
    print(div)

    by_token = defaultdict(list)
    for s in all_signals:
        by_token[s["token"]].append(s)

    header = (f"{'Token':<6} {'#Sigs':>5} {'Win':>5} {'P-TP2':>6} {'P-TP1':>6} "
              f"{'Loss':>5} {'Exp':>5} {'WR%':>6} {'AvgRR':>7} {'AvgFVG%':>8}")
    print(f"\n{header}")
    print("-" * 68)
    for token in sorted(by_token):
        sigs    = by_token[token]
        total   = len(sigs)
        wins    = sum(1 for s in sigs if s["outcome"] == "WIN")
        pt2     = sum(1 for s in sigs if s["outcome"] == "PARTIAL_TP2")
        pt1     = sum(1 for s in sigs if s["outcome"] == "PARTIAL_TP1")
        losses  = sum(1 for s in sigs if s["outcome"] == "LOSS")
        expired = sum(1 for s in sigs if s["outcome"] == "EXPIRED")
        rr_vals = [s["net_rr1"] for s in sigs if s.get("net_rr1", 0) > 0]
        avg_rr  = sum(rr_vals) / len(rr_vals) if rr_vals else 0
        fvg_v   = [s.get("fvg_pct", 0) for s in sigs]
        avg_fvg = sum(fvg_v) / len(fvg_v) if fvg_v else 0
        win_pct = wr(sigs)
        print(f"{token:<6} {total:>5} {wins:>5} {pt2:>6} {pt1:>6} {losses:>5} {expired:>5} "
              f"{win_pct:>5.1f}% {avg_rr:>6.2f}x {avg_fvg:>7.3f}%")

    by_regime = defaultdict(list)
    for s in all_signals:
        by_regime[s["regime"]].append(s)
    print(f"\n--- Win Rate by Regime ---")
    for regime in sorted(by_regime, key=lambda r: -wr(by_regime[r])):
        sigs  = by_regime[regime]
        total = len(sigs)
        w_pct = wr(sigs)
        bar   = "#" * round(w_pct / 5)
        print(f"  {regime:<20} {total:>4} sigs  WR:{w_pct:>5.1f}%  {bar}")

    by_sweep = defaultdict(list)
    for s in all_signals:
        by_sweep[s.get("sweep_type", "?")].append(s)
    print(f"\n--- Win Rate by Sweep Type (BSL=SELL, SSL=BUY) ---")
    for stype in sorted(by_sweep):
        sigs  = by_sweep[stype]
        total = len(sigs)
        w_pct = wr(sigs)
        bar   = "#" * round(w_pct / 5)
        print(f"  {stype:<6} {total:>4} sigs  WR:{w_pct:>5.1f}%  {bar}")

    by_trend = defaultdict(list)
    for s in all_signals:
        by_trend[s.get("trend_1h", "NEUTRAL")].append(s)
    print(f"\n--- Win Rate by 1H Trend at Entry ---")
    for trend in sorted(by_trend, key=lambda t: -wr(by_trend[t])):
        sigs  = by_trend[trend]
        total = len(sigs)
        w_pct = wr(sigs)
        bar   = "#" * round(w_pct / 5)
        print(f"  {trend:<15} {total:>4} sigs  WR:{w_pct:>5.1f}%  {bar}")

    by_bias4h = defaultdict(list)
    for s in all_signals:
        by_bias4h[s.get("bias_4h", "NEUTRAL")].append(s)
    print(f"\n--- Win Rate by 4H Bias at Setup ---")
    for bias in sorted(by_bias4h, key=lambda b: -wr(by_bias4h[b])):
        sigs  = by_bias4h[bias]
        total = len(sigs)
        w_pct = wr(sigs)
        bar   = "#" * round(w_pct / 5)
        print(f"  {bias:<10} {total:>4} sigs  WR:{w_pct:>5.1f}%  {bar}")

    ifvg_yes = [s for s in all_signals if s.get("ifvg_present")]
    ifvg_no  = [s for s in all_signals if not s.get("ifvg_present")]
    print(f"\n--- Win Rate: IFVG Present vs Absent ---")
    print(f"  IFVG=YES:  {len(ifvg_yes):>4} sigs  WR:{wr(ifvg_yes):>5.1f}%")
    print(f"  IFVG=NO:   {len(ifvg_no):>4} sigs  WR:{wr(ifvg_no):>5.1f}%")

    i5m_used  = [s for s in all_signals if s.get("ifvg_5m_used")]
    i5m_fall  = [s for s in all_signals if not s.get("ifvg_5m_used")]
    hit_pct   = len(i5m_used) / max(len(all_signals), 1) * 100
    print(f"\n--- Win Rate: 5M iFVG Precision Entry vs FVG Fallback ---")
    print(f"  5M-iFVG used: {len(i5m_used):>4} sigs ({hit_pct:.1f}% hit)  WR:{wr(i5m_used):>5.1f}%")
    print(f"  FVG fallback: {len(i5m_fall):>4} sigs               WR:{wr(i5m_fall):>5.1f}%")

    # Task 5: dealing range context breakdown
    dr_locs = {"PREMIUM": [], "DISCOUNT": [], "EQUILIBRIUM": [], "UNKNOWN": []}
    for s in all_signals:
        loc = s.get("dr4h_location", "UNKNOWN")
        dr_locs.setdefault(loc, []).append(s)
    print(f"\n--- Win Rate by 4H Dealing Range Location ---")
    for loc in ("DISCOUNT", "EQUILIBRIUM", "PREMIUM", "UNKNOWN"):
        sigs = dr_locs.get(loc, [])
        if sigs:
            print(f"  {loc:<12}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%")

    # Task 6: MSS quality breakdown
    mss_q_buckets: dict = {}
    for s in all_signals:
        q = s.get("mss_quality", "NONE")
        mss_q_buckets.setdefault(q, []).append(s)
    print(f"\n--- Win Rate by MSS Quality ---")
    for q in ("HIGH", "MEDIUM", "LOW", "NONE"):
        sigs = mss_q_buckets.get(q, [])
        if sigs:
            print(f"  {q:<8}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%")

    # Task 7: FVG quality breakdown
    fvg_q_buckets: dict = {}
    for s in all_signals:
        q = s.get("fvg_quality", "NONE")
        fvg_q_buckets.setdefault(q, []).append(s)
    print(f"\n--- Win Rate by FVG Quality ---")
    for q in ("HIGH", "MEDIUM", "LOW", "NONE"):
        sigs = fvg_q_buckets.get(q, [])
        if sigs:
            print(f"  {q:<8}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%")

    # Task 8: entry reaction type breakdown
    etype_buckets: dict = {}
    for s in all_signals:
        et = s.get("entry_type", "ZONE_TOUCH")
        etype_buckets.setdefault(et, []).append(s)
    print(f"\n--- Win Rate by Entry Reaction Type ---")
    for et in ("MIDPOINT_RECLAIM", "REACTION_CONFIRMED", "ZONE_TOUCH"):
        sigs = etype_buckets.get(et, [])
        if sigs:
            print(f"  {et:<20}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%")

    # Task 9: TP1 target type breakdown
    tp1_buckets: dict = {}
    for s in all_signals:
        t = s.get("tp1_target_type", "UNKNOWN")
        tp1_buckets.setdefault(t, []).append(s)
    print(f"\n--- Win Rate by TP1 Liquidity Target Type ---")
    for t in sorted(tp1_buckets):
        sigs = tp1_buckets[t]
        print(f"  {t:<18}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%")

    # Task 10: SMT divergence breakdown
    smt_yes = [s for s in all_signals if s.get("smt_confirmed")]
    smt_no  = [s for s in all_signals if not s.get("smt_confirmed")]
    print(f"\n--- Win Rate by SMT Divergence (BTC reference) ---")
    if smt_yes: print(f"  SMT confirmed    : {len(smt_yes):>4} sigs  WR:{wr(smt_yes):>5.1f}%")
    if smt_no:  print(f"  SMT not confirmed: {len(smt_no):>4} sigs  WR:{wr(smt_no):>5.1f}%")
    smt_type_bkt: dict = {}
    for s in all_signals:
        st = s.get("smt_type", "NONE")
        smt_type_bkt.setdefault(st, []).append(s)
    for st in ("BULLISH", "BEARISH", "NONE"):
        sigs = smt_type_bkt.get(st, [])
        if sigs:
            print(f"  {st:<18}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%")

    # Task 12: session breakdown
    DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    by_session = defaultdict(list)
    for s in all_signals:
        by_session[s.get("session", "UNKNOWN")].append(s)
    print(f"\n--- Win Rate by Session (M2: ICT Kill Zones) ---")
    # New ICT KZ labels + legacy labels for old DB entries
    for sess in ("ASIA_KZ", "LONDON_KZ", "NY_AM_KZ", "OVERNIGHT",
                 "ASIA", "LONDON", "NY", "LATE_US", "UNKNOWN"):
        sigs = by_session.get(sess, [])
        if sigs:
            flag = " *low-sample*" if len(sigs) < SAMPLE_N_OBSERVE else ""
            print(f"  {sess:<12}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%{flag}")

    by_dow = defaultdict(list)
    for s in all_signals:
        by_dow[s.get("day_of_week", -1)].append(s)
    print(f"\n--- Win Rate by Day of Week (Task 12) ---")
    for d in range(7):
        sigs = by_dow.get(d, [])
        if sigs:
            flag = " *low-sample*" if len(sigs) < SAMPLE_N_OBSERVE else ""
            print(f"  {DAY_NAMES[d]}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%{flag}")

    by_hour = defaultdict(list)
    for s in all_signals:
        by_hour[s.get("hour_utc", -1)].append(s)
    print(f"\n--- Win Rate by UTC Hour (Task 12) ---")
    for h in sorted(by_hour):
        sigs = by_hour[h]
        flag = " *low-sample*" if len(sigs) < SAMPLE_N_OBSERVE else ""
        bar  = "#" * round(wr(sigs) / 5)
        print(f"  H{h:02d}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%  {bar}{flag}")

    # Task 13/15: EV status breakdown
    ev_status_bkt: dict = {}
    for s in all_signals:
        st = s.get("ev_status", "INSUFFICIENT_DATA")
        ev_status_bkt.setdefault(st, []).append(s)
    print(f"\n--- Win Rate by EV Status (Task 13) ---")
    for st in ("POSITIVE", "NEGATIVE", "INSUFFICIENT_DATA"):
        sigs = ev_status_bkt.get(st, [])
        if sigs:
            avg_ev = sum(s.get("ev_score", 0.0) or 0.0 for s in sigs) / len(sigs)
            print(f"  {st:<22}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%  AvgEV:{avg_ev:>+7.3f}%")

    ev_tier_bkt: dict = {}
    for s in all_signals:
        n = s.get("ev_sample_n", 0) or 0
        tier = label_sample_size(n)
        ev_tier_bkt.setdefault(tier, []).append(s)
    print(f"\n--- Win Rate by EV Sample-Size Tier (Task 15) ---")
    for tier in ("STRONG", "USABLE", "WEAK", "OBSERVE", "NONE"):
        sigs = ev_tier_bkt.get(tier, [])
        if sigs:
            avg_n = int(sum(s.get("ev_sample_n", 0) or 0 for s in sigs) / len(sigs))
            print(f"  {tier:<8}: {len(sigs):>4} sigs  WR:{wr(sigs):>5.1f}%  AvgN:{avg_n:>4}")

    print(f"\n--- EV Score vs Confidence Correlation (Task 13) ---")
    ev_conf_bkt: dict = {}
    for s in all_signals:
        c   = s.get("confidence", 0)
        evs = s.get("ev_score", None)
        if evs is not None:
            ev_conf_bkt.setdefault(c, []).append(evs)
    for c in sorted(ev_conf_bkt):
        vals   = ev_conf_bkt[c]
        avg_ev = sum(vals) / len(vals)
        bar    = "#" * round(abs(avg_ev) / 0.5) if abs(avg_ev) >= 0.1 else ""
        print(f"  Conf {c:>2}: {len(vals):>4} sigs  AvgEV:{avg_ev:>+7.3f}%  {bar}")

    by_conf = defaultdict(list)
    for s in all_signals:
        by_conf[s["confidence"]].append(s)
    print(f"\n--- Win Rate by Confidence Level ---")
    for conf in sorted(by_conf):
        sigs  = by_conf[conf]
        total = len(sigs)
        w_pct = wr(sigs)
        bar   = "#" * round(w_pct / 5)
        print(f"  Conf {conf:>2}:  {total:>4} sigs  WR:{w_pct:>5.1f}%  {bar}")

    buy_sigs  = [s for s in all_signals if s["signal"] == "BUY"]
    sell_sigs = [s for s in all_signals if s["signal"] == "SELL"]
    buy_z     = _z_score(buy_sigs)
    sell_z    = _z_score(sell_sigs)
    buy_ne    = _net_exp(buy_sigs)
    sell_ne   = _net_exp(sell_sigs)
    print(f"\n--- BUY vs SELL (Phase 4.6: 4H-aligned) ---")
    print(f"  BUY:  {len(buy_sigs):>4} signals  WR:{_wr_with_ci(buy_sigs):<22}  "
          f"NetE:{buy_ne:>+7.3f}%  z:{buy_z:>+5.2f}")
    print(f"  SELL: {len(sell_sigs):>4} signals  WR:{_wr_with_ci(sell_sigs):<22}  "
          f"NetE:{sell_ne:>+7.3f}%  z:{sell_z:>+5.2f}")

    total_all  = len(all_signals)
    overall_wr = wr(all_signals)
    wr_frac    = overall_wr / 100
    net_rr_all = [s["net_rr1"] for s in all_signals if s.get("net_rr1", 0) > 0]
    avg_net_rr = sum(net_rr_all) / len(net_rr_all) if net_rr_all else 0
    med_net_rr = sorted(net_rr_all)[len(net_rr_all)//2] if net_rr_all else 0
    # Cycle 6 Fix #16: use split-exit realized P&L for expectancy, gross_wins,
    # gross_losses, and equity-curve drawdown — previously all used net_tp1_pct
    # which credited every win at TP1's value (understated TP3 wins, overstated
    # PARTIAL_TP1 outcomes).
    expectancy = _net_exp(all_signals)
    bew_all    = [s["breakeven_wr"] for s in all_signals]
    avg_bew    = sum(bew_all) / len(bew_all) if bew_all else 0
    overall_z  = _z_score(all_signals)

    # Task 19: Quant metrics — split-exit P&L
    _per_trade_pnl = [_realized_pnl_pct(s) for s in all_signals]
    gross_wins   = sum(p for p in _per_trade_pnl if p > 0)
    gross_losses = abs(sum(p for p in _per_trade_pnl if p < 0))
    profit_factor = round(gross_wins / gross_losses, 3) if gross_losses > 0 else float("inf")
    # Running drawdown (cumulative P&L sequence, split-exit)
    sorted_sigs = sorted(all_signals, key=lambda s: s["ts"])
    cum_pnl = 0.0; peak = 0.0; max_dd = 0.0
    for s in sorted_sigs:
        cum_pnl += _realized_pnl_pct(s)
        if cum_pnl > peak: peak = cum_pnl
        dd = peak - cum_pnl
        if dd > max_dd: max_dd = dd
    # Max loss streak
    max_streak = cur_streak = 0
    for s in sorted_sigs:
        if is_win(s["outcome"]): cur_streak = 0
        else:
            cur_streak += 1
            if cur_streak > max_streak: max_streak = cur_streak
    # TP1 before SL rate
    tp1_rate = sum(1 for s in all_signals if s.get("tp_reached",0) >= 1) / total_all * 100 if total_all else 0

    _overall_ci_str = _wr_with_ci(all_signals)
    print(f"\n{div}")
    print(f"  OVERALL: {total_all} signals | WR: {_overall_ci_str} | "
          f"Net R:R avg:{avg_net_rr:.2f}x med:{med_net_rr:.2f}x | Net E: {expectancy:+.4f}%/trade")
    print(f"  TP1 rate: {tp1_rate:.1f}% | Profit Factor: {profit_factor:.3f} | "
          f"Max DD: {max_dd:.3f}% | Max Loss Streak: {max_streak}")
    print(f"  BEW avg: {avg_bew:.1%} | z-score: {overall_z:+.2f} | Need WR > BEW to profit")
    print(div)

    # ── Phase A item #2: Honest-label section (triple-barrier + bootstrap CIs)
    _tb_signals = [s for s in all_signals if s.get("tb_touch") and s.get("tb_touch") != "INVALID"]
    if _tb_signals:
        _tp_n = sum(1 for s in _tb_signals if s.get("tb_touch") == "TP")
        _sl_n = sum(1 for s in _tb_signals if s.get("tb_touch") == "SL")
        _to_n = sum(1 for s in _tb_signals if s.get("tb_touch") == "TIMEOUT")
        _denom = max(1, len(_tb_signals))
        _wr_ci = bootstrap_wr_ci([s["outcome"] for s in all_signals], n_iter=5000, ci=0.95)
        _r_values = [s.get("realized_r") for s in all_signals if isinstance(s.get("realized_r"), (int, float))]
        _sh_ci = bootstrap_sharpe_ci(_r_values, n_iter=5000, ci=0.95)
        print(f"\n  HONEST-LABEL METRICS (de Prado triple-barrier + 5k bootstrap CI 95%)")
        print(f"  Triple-barrier first-touch: TP={_tp_n} ({_tp_n/_denom*100:.1f}%) | "
              f"SL={_sl_n} ({_sl_n/_denom*100:.1f}%) | TIMEOUT={_to_n} ({_to_n/_denom*100:.1f}%)")
        print(f"  Bootstrap WR    : {_wr_ci['wr']:.2f}% [{_wr_ci['lo']:.2f}–{_wr_ci['hi']:.2f}%]  (n={_wr_ci['n']})")
        print(f"  Bootstrap Sharpe: {_sh_ci['sharpe']:+.4f}  [{_sh_ci['lo']:+.4f}–{_sh_ci['hi']:+.4f}]  "
              f"(per-trade R; ×√N_per_yr for calendar)")
        print(div)

    # Task 19: Failure reason breakdown (backtest losses)
    losses_only = [s for s in all_signals if s["outcome"] in ("LOSS", "EXPIRED")]
    if losses_only:
        fail_bkt: dict = {}
        for s in losses_only:
            # Use field mappings available in backtest signals dict
            regime_s     = s.get("regime", "")
            mss_q        = s.get("mss_quality", "")
            fvg_q        = s.get("fvg_quality", "")
            smt_s        = s.get("smt_type", "NONE")
            entry_s      = s.get("entry_type", "ZONE_TOUCH")
            dr_s         = s.get("dr4h_location", "")
            direction_s  = s.get("signal", "")
            # Mirror compute_failure_reason logic for backtest signals
            if regime_s in ("LIQUIDATION",):       fr = "news_or_liquidation_spike"
            elif regime_s in ("CHOPPY","LOW_VOLATILITY_CHOP"): fr = "chop_regime"
            elif regime_s == "HIGH_VOLATILITY":    fr = "news_or_liquidation_spike"
            elif mss_q == "LOW":                   fr = "low_quality_MSS"
            elif smt_s == "NONE":                  fr = "no_SMT"
            elif fvg_q == "LOW":                   fr = "FVG_invalidated"
            elif dr_s == "EQUILIBRIUM":            fr = "entered_in_equilibrium"
            elif direction_s == "BUY"  and dr_s == "PREMIUM":  fr = "buy_in_premium_zone"
            elif direction_s == "SELL" and dr_s == "DISCOUNT": fr = "sell_in_discount_zone"
            elif entry_s == "ZONE_TOUCH":          fr = "entry_too_early"
            elif s["outcome"] == "EXPIRED":        fr = "swept_again_after_entry"
            else:                                  fr = "unclassified_loss"
            fail_bkt.setdefault(fr, []).append(s)
        print(f"\n--- Failure Classification (Task 17/19) — {len(losses_only)} losses ---")
        for fr in sorted(fail_bkt, key=lambda x: -len(fail_bkt[x])):
            cnt = len(fail_bkt[fr])
            pct = cnt / len(losses_only) * 100
            print(f"  {fr:<28}: {cnt:>4} ({pct:>5.1f}%)")

    # ── Phase 4.6 filter analysis ─────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  PHASE 4.6 FILTER ANALYSIS — Subset tests (4H-aligned BUY+SELL)")
    print(f"  Paper-trade threshold: n>=30 + WR>BEW + z>=1.28 + WFgap<10% + NetE>0")
    print(f"{'=' * 80}")
    hdr = (f"  {'Filter':<34} {'n':>4} {'WR%':>6} {'BEW%':>6} "
           f"{'NetE%':>8} {'z':>6} {'WFGap%':>8}  Flag")
    print(hdr)
    print("  " + "-" * 80)

    subsets_46 = [
        ("All signals (baseline)",
            all_signals),
        ("BUY only (4H BULLISH + 1H BULL/SBULL)",
            buy_sigs),
        ("SELL only (4H BEARISH + 1H BEAR/SBEAR)",
            sell_sigs),
        ("RANGING regime only",
            [s for s in all_signals if s["regime"] == "RANGING"]),
        ("TRENDING_BULL regime only",
            [s for s in all_signals if s["regime"] == "TRENDING_BULL"]),
        ("TRENDING_BEAR regime only",
            [s for s in all_signals if s["regime"] == "TRENDING_BEAR"]),
        ("Exclude BTC",
            [s for s in all_signals if s["token"] != "BTC"]),
        ("Exclude SOL",
            [s for s in all_signals if s["token"] != "SOL"]),
        ("Exclude BTC + SOL",
            [s for s in all_signals if s["token"] not in ("BTC", "SOL")]),
        ("Exclude LINK",
            [s for s in all_signals if s["token"] != "LINK"]),
        ("HBAR only",
            [s for s in all_signals if s["token"] == "HBAR"]),
        ("IFVG as hard filter",
            [s for s in all_signals if s.get("ifvg_present")]),
        ("BUY + IFVG present",
            [s for s in buy_sigs if s.get("ifvg_present")]),
        ("SELL + IFVG present",
            [s for s in sell_sigs if s.get("ifvg_present")]),
        ("5M iFVG precision (used)",
            [s for s in all_signals if s.get("ifvg_5m_used")]),
        ("BUY + 5M iFVG precision",
            [s for s in buy_sigs  if s.get("ifvg_5m_used")]),
        ("SELL + 5M iFVG precision",
            [s for s in sell_sigs if s.get("ifvg_5m_used")]),
    ]

    # Bonferroni correction: k simultaneous tests at family α=0.10
    _k   = len(subsets_46)
    _z_bf = NormalDist().inv_cdf(1 - 0.10 / _k)
    print(f"  NOTE: {_k} simultaneous tests; Bonferroni z ≥ {_z_bf:.2f} for CANDIDATE flag (α=0.10 family-wise; FWER≈10%)")
    print(f"  (Raw z ≥ 1.28 shown in brackets if unadjusted threshold passes but Bonferroni does not)")
    print("  " + "-" * 80)

    for label, sigs in subsets_46:
        n_s   = len(sigs)
        w_s   = wr(sigs)
        bew_s = (sum(s["breakeven_wr"] for s in sigs) / n_s * 100) if n_s else 0.0
        ne_s  = _net_exp(sigs)
        z_s   = _z_score(sigs)
        gap_s = _wf_gap_sub(sigs)
        gap_str = f"{gap_s:+.1f}%" if not math.isnan(gap_s) else "   n/a"
        _base_ok = (n_s >= 30 and w_s > bew_s and not math.isnan(gap_s)
                    and abs(gap_s) < 10 and ne_s > 0)
        passes_bf  = _base_ok and z_s >= _z_bf
        passes_raw = _base_ok and z_s >= 1.28
        flag = (" *** CANDIDATE ***" if passes_bf
                else (" [z≥1.28 unadjusted]" if passes_raw else ""))
        print(f"  {label:<34} {n_s:>4} {w_s:>5.1f}% {bew_s:>5.1f}% "
              f"{ne_s:>+8.3f}% {z_s:>+6.2f} {gap_str:>8}{flag}")

    print(f"{'=' * 80}\n")


# ══════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════
def init_backtest_db():
    conn = _connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS backtest_runs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date        TEXT NOT NULL,
        days            INTEGER DEFAULT 90,
        total_signals   INTEGER DEFAULT 0,
        overall_wr      REAL    DEFAULT 0,
        avg_rr          REAL    DEFAULT 0,
        status          TEXT    DEFAULT 'DONE',
        summary         TEXT,
        recommendations TEXT
    )""")
    # FIX 1 (2026-05-23): add config_hash column for honest DSR n_trials counting.
    # Same-config re-runs should NOT inflate the selection-bias penalty — only
    # DISTINCT param configurations count as separate trials per Bailey/LdP 2014.
    # Idempotent ALTER TABLE: legacy rows get NULL → collectively count as 1 trial.
    try:
        conn.execute("ALTER TABLE backtest_runs ADD COLUMN config_hash TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.execute("""CREATE TABLE IF NOT EXISTS backtest_signals (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     INTEGER REFERENCES backtest_runs(id),
        token      TEXT, signal TEXT, price REAL, ts TEXT,
        regime     TEXT, confidence INTEGER, wscore REAL,
        margin     REAL, conflict TEXT,
        tp1_pct    REAL, sl_pct REAL, rr1 REAL,
        tp_reached INTEGER DEFAULT 0, outcome TEXT
    )""")
    for col, typ in [
        ("net_tp1_pct",    "REAL"), ("net_sl_pct",    "REAL"),
        ("net_rr1",        "REAL"), ("breakeven_wr",  "REAL"),
        ("sweep_type",     "TEXT"), ("fvg_pct",       "REAL"),
        ("trend_1h",       "TEXT"),
        # Phase 4.2B
        ("bias_4h",        "TEXT"), ("ifvg_present",  "INTEGER"),
        ("ifvg_direction", "TEXT"), ("ifvg_age_bars", "INTEGER"),
        # Phase 4.7
        ("ifvg_5m_used",   "INTEGER"),
        # Audit fixes: ICT quality + session metadata
        ("session",        "TEXT"), ("hour_utc",      "INTEGER"),
        ("day_of_week",    "INTEGER"),
        ("dr_location",    "TEXT"), ("mss_quality",   "TEXT"),
        ("fvg_quality",    "TEXT"), ("smt_type",      "TEXT"),
        ("smt_confirmed",  "INTEGER"), ("entry_type", "TEXT"),
        # Phase I-2: strategy variant tagging
        ("matched_template_id",  "TEXT"),
        ("template_scores_json", "TEXT"),
        # Phase I-4: excursion tracking
        ("mfe_pct",   "REAL"),
        ("mae_pct",   "REAL"),
        ("realized_r","REAL"),
        # Cycle 6 Fix #16: split-exit P&L model
        ("net_tp2_pct", "REAL"),
        ("net_tp3_pct", "REAL"),
        # Phase A item #2: triple-barrier honest-label columns
        ("tb_bin",    "INTEGER"),
        ("tb_touch",  "TEXT"),
        ("tb_ret",    "REAL"),
        ("tb_t1",     "INTEGER"),
    ]:
        try:
            conn.execute(f"ALTER TABLE backtest_signals ADD COLUMN {col} {typ}")
        except Exception:
            pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bt_signals_run_id ON backtest_signals(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bt_signals_token ON backtest_signals(token)")
    conn.commit(); conn.close()


def _wr(sigs):
    if not sigs: return 0.0
    w = sum(1 for s in sigs if s["outcome"] in ("WIN", "PARTIAL_TP2", "PARTIAL_TP1"))
    return round(w / len(sigs) * 100, 1)


def build_summary(all_signals):
    by_token   = defaultdict(list)
    by_regime  = defaultdict(list)
    by_conf    = defaultdict(list)
    by_dir     = defaultdict(list)
    by_sweep   = defaultdict(list)
    by_trend   = defaultdict(list)
    by_session = defaultdict(list)
    for s in all_signals:
        by_token[s["token"]].append(s)
        by_regime[s["regime"]].append(s)
        by_conf[s["confidence"]].append(s)
        by_dir[s["signal"]].append(s)
        by_sweep[s.get("sweep_type", "?")].append(s)
        by_trend[s.get("trend_1h", "NEUTRAL")].append(s)
        by_session[s.get("session", "OVERNIGHT")].append(s)

    def tok_entry(sigs):
        total   = len(sigs)
        rr_v    = [s["net_rr1"] for s in sigs if s.get("net_rr1", 0) > 0]
        # Cycle 6 Fix #16: split-exit expectancy per token
        exp     = _net_exp(sigs)
        fvg_v   = [s.get("fvg_pct", 0) for s in sigs]
        return {
            "signals":        total,
            "wins":           sum(1 for s in sigs if s["outcome"] == "WIN"),
            "partial":        sum(1 for s in sigs if "PARTIAL" in s["outcome"]),
            "losses":         sum(1 for s in sigs if s["outcome"] == "LOSS"),
            "expired":        sum(1 for s in sigs if s["outcome"] == "EXPIRED"),
            "wr":             _wr(sigs),
            "avg_net_rr":     round(sum(rr_v) / len(rr_v), 2) if rr_v else 0,
            "net_expectancy": round(exp, 4),
            "avg_conf":       round(sum(s["confidence"] for s in sigs) / total, 1) if total else 0,
            "avg_fvg_pct":    round(sum(fvg_v) / len(fvg_v), 3) if fvg_v else 0,
        }

    def simple_entry(sigs):
        return {
            "signals": len(sigs),
            "wins":    sum(1 for s in sigs if s["outcome"] == "WIN"),
            "partial": sum(1 for s in sigs if "PARTIAL" in s["outcome"]),
            "wr":      _wr(sigs),
        }

    return {
        "by_token":   {k: tok_entry(v)         for k, v in by_token.items()},
        "by_regime":  {k: simple_entry(v)       for k, v in by_regime.items()},
        "by_conf":    {str(k): simple_entry(v)  for k, v in by_conf.items()},
        "by_dir":     {k: simple_entry(v)       for k, v in by_dir.items()},
        "by_sweep":   {k: simple_entry(v)       for k, v in by_sweep.items()},
        "by_trend":   {k: simple_entry(v)       for k, v in by_trend.items()},
        "by_session": {k: simple_entry(v)       for k, v in by_session.items()},
        "cost_model": {
            "slippage_pct":     round(SLIPPAGE_PCT * 100, 3),
            "fee_per_side_pct": round(FEE_PCT * 100, 2),
            "rt_total_pct":     round(ROUND_TRIP_COST_PCT * 100, 2),
            "min_sl_pct":       round(MIN_SL_PCT * 100, 2),
            "max_sl_pct":       round(MAX_SL_PCT * 100, 2),
            "max_breakeven_wr": MAX_BREAKEVEN_WR,
            "timeframe":        "5m",
            "strategy":         "ICT_SWEEP_MSS_FVG",
        },
    }


def walk_forward_split(all_signals, train_frac=0.60):
    if not all_signals:
        return [], [], ""
    sorted_sigs = sorted(all_signals, key=lambda s: s["ts"])
    if WF_OOS_START_DATE:
        train  = [s for s in sorted_sigs if s["ts"] < WF_OOS_START_DATE]
        test   = [s for s in sorted_sigs if s["ts"] >= WF_OOS_START_DATE]
        cutoff = WF_OOS_START_DATE
        if not train or not test:
            # Boundary falls outside data range — fall back to count-based split
            cut = max(1, int(len(sorted_sigs) * train_frac))
            train, test, cutoff = sorted_sigs[:cut], sorted_sigs[cut:], sorted_sigs[cut]["ts"]
    else:
        cut = max(1, int(len(sorted_sigs) * train_frac))
        train, test, cutoff = sorted_sigs[:cut], sorted_sigs[cut:], sorted_sigs[cut]["ts"]
    return train, test, cutoff


def run_rolling_walk_forward(all_signals, train_days=90, test_days=30, step_days=30):
    """Task 14: Rolling walk-forward validation.

    Rolls a train/test window across the backtest period in step_days increments.
    For each window: compute train WR, test WR, net expectancy, profit factor,
    max drawdown, and trade count.

    Returns list of window result dicts.
    """
    if not all_signals:
        return []

    sorted_sigs = sorted(all_signals, key=lambda s: s["ts"])
    if not sorted_sigs:
        return []

    def _parse_ts(s):
        return datetime.strptime(s["ts"], "%Y-%m-%d %H:%M:%S")

    def _window_stats(sigs):
        if not sigs:
            return {"n":0, "wr":0, "ne":0, "pf":0, "max_dd":0, "z":0}
        n    = len(sigs)
        w_r  = wr(sigs)
        ne   = _net_exp(sigs)
        z    = _z_score(sigs)
        # Cycle 6 Fix #16: split-exit PF + DD using _realized_pnl_pct
        per_trade = [_realized_pnl_pct(s) for s in sigs]
        wins_pnl  = sum(p for p in per_trade if p > 0)
        loss_pnl  = abs(sum(p for p in per_trade if p < 0))
        pf        = round(wins_pnl / loss_pnl, 3) if loss_pnl > 0 else float("inf")
        cum = 0.0; peak = 0.0; dd_max = 0.0
        for p in per_trade:
            cum += p
            if cum > peak: peak = cum
            dd = peak - cum
            if dd > dd_max: dd_max = dd
        return {"n": n, "wr": w_r, "ne": ne, "pf": pf, "max_dd": dd_max, "z": z}

    first_ts = _parse_ts(sorted_sigs[0])
    last_ts  = _parse_ts(sorted_sigs[-1])
    total_days = (last_ts - first_ts).days

    results = []
    offset  = 0
    from datetime import timedelta as _td
    # M3: removed `+ step_days` — that extra term allowed an empty-test-window iteration
    while offset + train_days + test_days <= total_days:
        train_start = first_ts + _td(days=offset)
        train_end   = train_start + _td(days=train_days)
        test_end    = train_end   + _td(days=test_days)

        train_sigs = [s for s in sorted_sigs
                      if train_start <= _parse_ts(s) < train_end]
        test_sigs  = [s for s in sorted_sigs
                      if train_end  <= _parse_ts(s) < test_end]

        if not train_sigs and not test_sigs:
            offset += step_days; continue

        tr_stat = _window_stats(train_sigs)
        te_stat = _window_stats(test_sigs)
        if te_stat["n"] == 0:  # M3: skip windows with no test-set data
            offset += step_days; continue
        results.append({
            "window":      f"{train_start.strftime('%Y-%m-%d')} → {test_end.strftime('%Y-%m-%d')}",
            "train_start": train_start.strftime('%Y-%m-%d'),
            "test_start":  train_end.strftime('%Y-%m-%d'),
            "test_end":    test_end.strftime('%Y-%m-%d'),
            "train":       tr_stat,
            "test":        te_stat,
            "overfit_gap": round(tr_stat["wr"] - te_stat["wr"], 1),
        })
        offset += step_days

    return results


def print_rolling_wf_report(wf_results):
    """Task 14: Print the rolling walk-forward results table."""
    if not wf_results:
        print("\n[Walk-Forward] Not enough signals for rolling windows.")
        return
    print(f"\n{'=' * 96}")
    print(f"  ROLLING WALK-FORWARD VALIDATION (Task 14)")
    print(f"  Train window: 90 days | Test window: 30 days | Step: 30 days")
    print(f"  Threshold: test WR > train BEW | z >= 1.28 | overfit gap < 10%")
    print(f"{'=' * 96}")
    hdr = (f"  {'Window':<40} {'Tr-N':>4} {'Tr-WR%':>7} {'Te-N':>4} {'Te-WR%':>7} "
           f"{'Te-NE%':>8} {'Te-PF':>6} {'Te-DD%':>7} {'Gap':>6}  Flag")
    print(hdr)
    print("  " + "-" * 96)

    consistent = 0
    for r in wf_results:
        tr = r["train"]; te = r["test"]
        gap_ok   = abs(r["overfit_gap"]) < 10
        te_pos   = te["ne"] > 0
        te_n_ok  = te["n"] >= 10
        passes   = gap_ok and te_pos and te_n_ok
        flag     = " *** CONSISTENT ***" if passes else ""
        if passes: consistent += 1
        pf_s = f"{te['pf']:.2f}" if te["pf"] != float("inf") else " inf"
        print(f"  {r['window']:<40} {tr['n']:>4} {tr['wr']:>6.1f}% "
              f"{te['n']:>4} {te['wr']:>6.1f}% "
              f"{te['ne']:>+8.3f}% {pf_s:>6} {te['max_dd']:>6.3f}% "
              f"{r['overfit_gap']:>+5.1f}%{flag}")

    print(f"\n  Consistent windows: {consistent}/{len(wf_results)} "
          f"({consistent/len(wf_results)*100:.0f}%)")
    print(f"{'=' * 96}\n")


# ══════════════════════════════════════════════════════════
# PHASE I-3 — ICT STRATEGY VARIANT LEARNER — TEMPLATE HARNESS
# ══════════════════════════════════════════════════════════

_N_WARN      = 30    # sample size: unreliable below this
_N_RELI      = 50    # sample size: reliable at or above this
_CONC_THRESH = 0.70  # concentration warning threshold (70%)


def _tier_stats(sigs):
    """Compute stats dict for a list of signals. Returns None if sigs is empty."""
    if not sigs:
        return None
    n       = len(sigs)
    wins    = sum(1 for s in sigs if is_win(s["outcome"]))
    partial = sum(1 for s in sigs if s["outcome"] == "PARTIAL_TP1")
    losses  = sum(1 for s in sigs if s["outcome"] in ("LOSS", "SL_HIT"))
    expired = sum(1 for s in sigs if s["outcome"] in ("EXPIRED", "NO_FILL"))
    wr_pct  = round(wins / n * 100, 1)
    conf_sum = sum(s.get("wscore", s.get("confidence", 5)) for s in sigs)
    if conf_sum > 0:
        wwr = round(
            sum(s.get("wscore", s.get("confidence", 5)) / conf_sum
                for s in sigs if is_win(s["outcome"])) * 100, 1)
    else:
        wwr = wr_pct
    # Cycle 6 Fix #16: split-exit AvgPnL + DD via _realized_pnl_pct
    avg_pnl  = round(sum(_realized_pnl_pct(s) for s in sigs) / n, 4)
    avg_conf = round(sum(s.get("confidence", 0) for s in sigs) / n, 1)
    rr_vals  = [s["rr1"] for s in sigs if s["rr1"] > 0]
    avg_rr   = round(sum(rr_vals) / len(rr_vals), 2) if rr_vals else 0.0
    running = peak = max_dd = 0.0
    for s in sigs:
        running += _realized_pnl_pct(s)
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # Phase I-4: excursion and realized-R metrics
    mfe_vals = [s["mfe_pct"]    for s in sigs if s.get("mfe_pct")    is not None]
    mae_vals = [s["mae_pct"]    for s in sigs if s.get("mae_pct")    is not None]
    rr_real  = [s["realized_r"] for s in sigs if s.get("realized_r") is not None]
    avg_mfe  = round(sum(mfe_vals) / len(mfe_vals), 4) if mfe_vals else None
    avg_mae  = round(sum(mae_vals) / len(mae_vals), 4) if mae_vals else None
    avg_real_r = round(sum(rr_real) / len(rr_real), 4) if rr_real else None
    if rr_real:
        _s = sorted(rr_real)
        mid = len(_s) // 2
        med_real_r = round((_s[mid] if len(_s) % 2 else (_s[mid-1] + _s[mid]) / 2), 4)
    else:
        med_real_r = None

    return {
        "n": n, "wins": wins, "partial": partial, "losses": losses,
        "expired": expired, "wr": wr_pct, "wwr": wwr,
        "avg_pnl": avg_pnl, "avg_conf": avg_conf, "avg_rr": avg_rr,
        "max_dd": round(max_dd, 4),
        # Phase I-4
        "avg_mfe":    avg_mfe,
        "avg_mae":    avg_mae,
        "avg_real_r": avg_real_r,
        "med_real_r": med_real_r,
    }


def _holdout_split(all_signals, train_frac=0.80):
    """Chronological train/holdout split aligned with WF_OOS_START_DATE boundary.
    Falls back to count-based split if boundary falls outside the signal date range."""
    if not all_signals:
        return [], [], ""
    sorted_sigs = sorted(all_signals, key=lambda s: s["ts"])
    if WF_OOS_START_DATE:
        train   = [s for s in sorted_sigs if s["ts"] < WF_OOS_START_DATE]
        holdout = [s for s in sorted_sigs if s["ts"] >= WF_OOS_START_DATE]
        if train and holdout:
            return train, holdout, WF_OOS_START_DATE
    # Fallback: count-based split when WF boundary is outside the data range
    cut_idx = int(len(sorted_sigs) * train_frac)
    train   = sorted_sigs[:cut_idx]
    holdout = sorted_sigs[cut_idx:]
    cutoff  = holdout[0]["ts"] if holdout else ""
    return train, holdout, cutoff


def _reconstruct_variant_features(s):
    """Rebuild variant features dict from a backtest signal dict."""
    return {
        "direction":     s.get("signal", "BUY"),
        "mss_quality":   s.get("mss_quality", "NONE"),
        "fvg_quality":   s.get("fvg_quality", "NONE"),
        "session":       s.get("session", "OVERNIGHT"),
        "dr_location":   s.get("dr4h_location", "UNKNOWN"),
        "smt_confirmed": bool(s.get("smt_confirmed", 0)),
        "entry_type":    s.get("entry_type", "ZONE_TOUCH"),
        "bias_4h":       s.get("bias_4h", "NEUTRAL"),
        "ifvg_present":  bool(s.get("ifvg_present", 0)),
    }


def _overfitting_warnings(tier_id, sigs, dim_name=None, dim_val=None):
    """Return list of warning strings for a given signal slice."""
    warns  = []
    n      = len(sigs)
    prefix = f"[{tier_id}]" + (f"[{dim_name}={dim_val}]" if dim_name else "")
    if n < _N_WARN:
        warns.append(f"{prefix} n={n} - insufficient sample (<{_N_WARN}), treat as noise")
    if n > 0:
        by_regime = defaultdict(int)
        by_sess   = defaultdict(int)
        for s in sigs:
            by_regime[s["regime"]] += 1
            by_sess[s.get("session", "OVERNIGHT")] += 1
        top_r, top_rc = max(by_regime.items(), key=lambda x: x[1])
        # Skip regime concentration check when already grouped by regime (would always be 100%)
        if top_rc / n >= _CONC_THRESH and (not dim_name or dim_name.lower() not in ("regime",)):
            warns.append(f"{prefix} regime concentration: {top_rc}/{n} "
                         f"({top_rc/n*100:.0f}%) in '{top_r}' - may not generalize")
        top_s, top_sc = max(by_sess.items(), key=lambda x: x[1])
        # Skip session concentration check when already grouped by session (would always be 100%)
        if top_sc / n >= _CONC_THRESH and (not dim_name or dim_name.lower() not in ("session",)):
            warns.append(f"{prefix} session concentration: {top_sc}/{n} "
                         f"({top_sc/n*100:.0f}%) in '{top_s}' - session-dependent edge")
    return warns


def _dim_table(sigs, dim_key, tier_id, dim_label=None):
    """
    Per-dimension breakdown. Returns list of (val, stats_dict, warnings_list)
    sorted by WR desc. dim_key: key on signal dict; use 'direction' for signal col,
    'dr_location' for dr4h_location.
    """
    groups = defaultdict(list)
    for s in sigs:
        if dim_key == "direction":
            val = s.get("signal", "?")
        elif dim_key == "dr_location":
            val = s.get("dr4h_location", "UNKNOWN")
        else:
            val = s.get(dim_key, "?")
        groups[val].append(s)
    rows = []
    for val, grp in sorted(groups.items()):
        st = _tier_stats(grp)
        if st is None:
            continue
        w = _overfitting_warnings(tier_id, grp, dim_label or dim_key, val)
        rows.append((val, st, w))
    rows.sort(key=lambda r: (-r[1]["wr"], -r[1]["n"]))
    return rows


def template_comparison_report(all_signals):
    """
    Phase I-3 main analytics. Returns structured report dict used by
    print_template_report() and write_template_performance_md().
    """
    if not all_signals:
        return None

    train_sigs, holdout_sigs, holdout_cutoff = _holdout_split(all_signals, 0.80)

    def _group_by_tier(sigs):
        by_tier = defaultdict(list)
        for s in sigs:
            tid = s.get("matched_template_id", "NONE") or "NONE"
            by_tier[tid].append(s)
        return by_tier

    def _group_all_matched(sigs):
        by_tier = defaultdict(list)
        for s in sigs:
            vf      = _reconstruct_variant_features(s)
            matches = evaluate_confluences_vs_templates(vf)
            matched = False
            for m in matches:
                if m.is_match:
                    by_tier[m.template_id].append(s)
                    matched = True
            if not matched:
                by_tier["NONE"].append(s)
        return by_tier

    train_best   = _group_by_tier(train_sigs)
    holdout_best = _group_by_tier(holdout_sigs)
    all_best     = _group_by_tier(all_signals)
    train_all    = _group_all_matched(train_sigs)
    holdout_all  = _group_all_matched(holdout_sigs)

    dimensions = [
        ("direction",  "Direction"),
        ("regime",     "Regime"),
        ("session",    "Session"),
        ("fvg_quality","FVG Quality"),
        ("mss_quality","MSS Quality"),
        ("dr_location","DR Location"),
        ("entry_type", "Entry Type"),
    ]

    tier_reports = {}
    all_warnings = []

    for tid in ["TIER_A", "TIER_B", "TIER_C", "NONE"]:
        t_grp  = train_best.get(tid, [])
        h_grp  = holdout_best.get(tid, [])
        a_grp  = all_best.get(tid, [])
        t_stat = _tier_stats(t_grp)
        h_stat = _tier_stats(h_grp)

        tier_warns = []
        if t_stat and h_stat:
            wf_gap = round(t_stat["wr"] - h_stat["wr"], 1)
            if wf_gap > 10:
                tier_warns.append(
                    f"[{tid}] WF gap {wf_gap:+.1f}% (train WR minus holdout WR) - possible overfit")
        elif t_stat and not h_stat:
            tier_warns.append(f"[{tid}] No holdout signals - cannot validate generalization")
        tier_warns.extend(_overfitting_warnings(tid, a_grp))
        all_warnings.extend(tier_warns)

        dim_breakdowns = {}
        for dim_key, dim_label in dimensions:
            dim_breakdowns[dim_key] = _dim_table(t_grp, dim_key, tid, dim_label) if t_grp else []

        tier_reports[tid] = {
            "train":          t_stat,
            "holdout":        h_stat,
            "overall":        _tier_stats(a_grp),
            "dim_breakdowns": dim_breakdowns,
            "warnings":       tier_warns,
            "n_train":        len(t_grp),
            "n_holdout":      len(h_grp),
        }

    all_matched_reports = {}
    for tid in ["TIER_A", "TIER_B", "TIER_C"]:
        am_tr = train_all.get(tid, [])
        am_ho = holdout_all.get(tid, [])
        am_dim = {}
        for dim_key, dim_label in dimensions:
            am_dim[dim_key] = _dim_table(am_tr, dim_key, tid + "_AM", dim_label) if am_tr else []
        all_matched_reports[tid] = {
            "train":          _tier_stats(am_tr),
            "holdout":        _tier_stats(am_ho),
            "dim_breakdowns": am_dim,
            "n_train":        len(am_tr),
            "n_holdout":      len(am_ho),
        }

    # Phase I-4: pass training signals per tier so the MD writer can build excursion tables
    _tier_train_sigs = {tid: train_best.get(tid, []) for tid in ["TIER_A", "TIER_B", "TIER_C", "NONE"]}

    return {
        "total_signals":    len(all_signals),
        "n_train":          len(train_sigs),
        "n_holdout":        len(holdout_sigs),
        "holdout_cutoff":   holdout_cutoff,
        "tier_reports":     tier_reports,
        "all_matched":      all_matched_reports,
        "all_warnings":     all_warnings,
        "dimensions":       dimensions,
        "_tier_train_sigs": _tier_train_sigs,
        "_all_signals":     all_signals,   # Phase 5A: safety layer simulation
    }


def _fmt_stats_line(st, label=""):
    if st is None:
        return f"  {label:<20} n=0  (no signals)"
    rel  = "RELIABLE" if st["n"] >= _N_RELI else ("CAUTION" if st["n"] >= _N_WARN else "INSUF")
    mfe  = f"{st['avg_mfe']:+.4f}%" if st.get("avg_mfe") is not None else "N/A"
    mae  = f"{st['avg_mae']:+.4f}%" if st.get("avg_mae") is not None else "N/A"
    rr_r = f"{st['avg_real_r']:+.4f}R" if st.get("avg_real_r") is not None else "N/A"
    return (f"  {label:<20} n={st['n']:<4}  WR={st['wr']:.1f}%  "
            f"wWR={st['wwr']:.1f}%  AvgPnL={st['avg_pnl']:+.4f}%  "
            f"AvgConf={st['avg_conf']:.1f}  AvgRR={st['avg_rr']:.2f}  "
            f"MaxDD={st['max_dd']:.4f}%  MFE={mfe}  MAE={mae}  realR={rr_r}  [{rel}]")


def print_template_report(report):
    """Print Phase I-3 template comparison report to console."""
    if not report:
        print("\n[PHASE I-3] No signals - template report skipped.")
        return
    div = "=" * 96
    sep = "-" * 88
    print(f"\n{div}")
    print("  PHASE I-3 - ICT STRATEGY VARIANT LEARNER - TEMPLATE COMPARISON REPORT")
    print(f"  Total: {report['total_signals']} signals  |  "
          f"Train: {report['n_train']} (80%)  |  Holdout: {report['n_holdout']} (20%)")
    if report["holdout_cutoff"]:
        print(f"  Holdout from: {report['holdout_cutoff']}")
    print(div)

    tier_labels = {
        "TIER_A": "Tier A - Strict (4/5 required, live allowed)",
        "TIER_B": "Tier B - Balanced (3/5 required, live allowed)",
        "TIER_C": "Tier C - Exploratory (2/2 required, paper-only)",
        "NONE":   "No Template Match",
    }
    for tid in ["TIER_A", "TIER_B", "TIER_C", "NONE"]:
        tr = report["tier_reports"][tid]
        print(f"\n  {sep}")
        print(f"  {tier_labels[tid]}")
        print(f"  {sep}")
        print(_fmt_stats_line(tr["train"],   "Train (80%)"))
        print(_fmt_stats_line(tr["holdout"], "Holdout (20%)"))
        if tr["train"] and tr["holdout"]:
            wf_gap = round(tr["train"]["wr"] - tr["holdout"]["wr"], 1)
            flag   = "  *** POSSIBLE OVERFIT ***" if wf_gap > 10 else "  OK"
            print(f"  {'WF Gap':<20} {wf_gap:+.1f}%{flag}")
        for w in tr["warnings"]:
            print(f"  WARN: {w}")

    print(f"\n{div}")
    print("  ALL-WARNINGS SUMMARY")
    print(div)
    if report["all_warnings"]:
        for w in report["all_warnings"]:
            print(f"  WARN: {w}")
    else:
        print("  No overfitting warnings detected.")
    print(f"{div}\n")


def _excursion_section(a, sigs, dim_key, dim_label, tier_id):
    """Append an MFE/MAE/realized_R breakdown table for one dimension."""
    groups = defaultdict(list)
    for s in sigs:
        if dim_key == "session":
            val = s.get("session", "OVERNIGHT")
        elif dim_key == "fvg_quality":
            val = s.get("fvg_quality", "NONE")
        elif dim_key == "mss_quality":
            val = s.get("mss_quality", "NONE")
        else:
            val = s.get(dim_key, "?")
        groups[val].append(s)

    if not groups:
        return

    a(f"##### {dim_label}\n\n")
    a("| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |\n")
    a("|-------|---|----------|----------|-----------|-----------|-----|\n")
    for val in sorted(groups):
        grp = groups[val]
        mfe_v = [s["mfe_pct"]    for s in grp if s.get("mfe_pct")    is not None]
        mae_v = [s["mae_pct"]    for s in grp if s.get("mae_pct")    is not None]
        rr_v  = [s["realized_r"] for s in grp if s.get("realized_r") is not None]
        mfe_s = f"{sum(mfe_v)/len(mfe_v):+.4f}%" if mfe_v else "—"
        mae_s = f"{sum(mae_v)/len(mae_v):+.4f}%" if mae_v else "—"
        if rr_v:
            avg_rr_s = f"{sum(rr_v)/len(rr_v):+.4f}R"
            _sr = sorted(rr_v)
            mid = len(_sr) // 2
            med = (_sr[mid] if len(_sr) % 2 else (_sr[mid-1] + _sr[mid]) / 2)
            med_rr_s = f"{med:+.4f}R"
        else:
            avg_rr_s = med_rr_s = "—"
        wr_s  = f"{sum(1 for s in grp if is_win(s['outcome'])) / len(grp) * 100:.1f}%"
        flag  = " ⚠" if len(grp) < _N_WARN else ""
        a(f"| {val} | {len(grp)}{flag} | {mfe_s} | {mae_s} | {avg_rr_s} | {med_rr_s} | {wr_s} |\n")
    a("\n")


def write_template_performance_md(report, out_dir):
    """Write Phase I-3/4 template performance markdown to out_dir."""
    import os as _os
    _os.makedirs(out_dir, exist_ok=True)
    path = _os.path.join(out_dir, "template_performance_report.md")

    if not report:
        with open(path, "w", encoding="utf-8") as f:
            f.write("# ICT Strategy Variant Learner — Template Performance Report\n\n"
                    "No signals available for this run.\n")
        return path

    from datetime import datetime as _dt
    lines = []
    a = lines.append

    tier_labels = {
        "TIER_A": "Tier A — Strict",
        "TIER_B": "Tier B — Balanced",
        "TIER_C": "Tier C — Exploratory (paper-only)",
        "NONE":   "No Template Match",
    }
    tier_desc = {
        "TIER_A": "4/5 required confluences — live trading allowed",
        "TIER_B": "3/5 required confluences — live trading allowed",
        "TIER_C": "2/2 required confluences — paper/backtest only",
        "NONE":   "Signals that matched no ICT template",
    }

    def _f(v, fmt, suffix="", na="—"):
        return f"{v:{fmt}}{suffix}" if v is not None else na

    a("# ICT Strategy Variant Learner — Template Performance Report\n\n")
    a(f"**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}  \n")
    a(f"**Strategy Version:** {STRATEGY_VERSION}  \n")
    a(f"**Total signals:** {report['total_signals']} "
      f"(Train: {report['n_train']}, Holdout: {report['n_holdout']})  \n")
    if report["holdout_cutoff"]:
        a(f"**Holdout from:** {report['holdout_cutoff']}  \n")
    a("\n> Grouping: **Best Match Only** — each signal assigned to its highest-tier matching template.\n\n")
    a("> Phase I-4: MFE/MAE/realized_R now populated from forward-scan excursion tracking.\n\n")
    a("> **Expected: Tier C = 0 in Best-Match View.** Every signal produced by this bot satisfies "
      "at least 3/5 Tier B confluences, so all Tier C candidates are superseded by Tier B in "
      "best-match assignment. Use the All-Matched View to see raw Tier C coverage.\n\n")
    a("---\n\n")

    # ── Quick summary ──────────────────────────────────────
    a("## Quick Summary\n\n")
    a("| Template | N (all) | Train WR% | Holdout WR% | WF Gap | Avg MFE% | Avg MAE% | Avg realR | Status |\n")
    a("|----------|---------|-----------|-------------|--------|----------|----------|-----------|--------|\n")
    for tid in ["TIER_A", "TIER_B", "TIER_C", "NONE"]:
        tr    = report["tier_reports"][tid]
        n_all = tr["n_train"] + tr["n_holdout"]
        st    = tr["train"]
        wr_tr = f"{st['wr']:.1f}%"            if st else "—"
        wr_ho = f"{tr['holdout']['wr']:.1f}%" if tr["holdout"] else "—"
        mfe_s = _f(st.get("avg_mfe")    if st else None, "+.4f", "%")
        mae_s = _f(st.get("avg_mae")    if st else None, "+.4f", "%")
        rr_s  = _f(st.get("avg_real_r") if st else None, "+.4f", "R")
        if tr["train"] and tr["holdout"]:
            gap   = round(tr["train"]["wr"] - tr["holdout"]["wr"], 1)
            gap_s = f"{gap:+.1f}%"
            stat  = "OVERFIT" if gap > 10 else "OK"
        else:
            gap_s = stat = "—"
        a(f"| {tier_labels[tid]} | {n_all} | {wr_tr} | {wr_ho} | {gap_s} | {mfe_s} | {mae_s} | {rr_s} | {stat} |\n")
    a("\n---\n\n")

    # ── Per-tier detail ────────────────────────────────────
    for tid in ["TIER_A", "TIER_B", "TIER_C", "NONE"]:
        tr = report["tier_reports"][tid]
        a(f"## {tier_labels[tid]}\n\n")
        a(f"_{tier_desc[tid]}_\n\n")

        # Main stats table — includes excursion columns
        a("| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |\n")
        a("|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|\n")
        for lbl, st in [("Train (80%)", tr["train"]), ("Holdout (20%)", tr["holdout"])]:
            if st:
                rel   = "Reliable" if st["n"] >= _N_RELI else ("Caution" if st["n"] >= _N_WARN else "Insufficient")
                mfe_s = _f(st.get("avg_mfe"),    "+.4f", "%")
                mae_s = _f(st.get("avg_mae"),    "+.4f", "%")
                rra_s = _f(st.get("avg_real_r"), "+.4f", "R")
                rrm_s = _f(st.get("med_real_r"), "+.4f", "R")
                a(f"| {lbl} | {st['n']} | {st['wr']:.1f}% | {st['wwr']:.1f}% | "
                  f"{st['avg_pnl']:+.4f}% | {st['avg_rr']:.2f} | {st['max_dd']:.4f}% | "
                  f"{mfe_s} | {mae_s} | {rra_s} | {rrm_s} | {rel} |\n")
            else:
                a(f"| {lbl} | 0 | — | — | — | — | — | — | — | — | — | — |\n")
        a("\n")

        if tr["warnings"]:
            a("### Warnings\n\n")
            for w in tr["warnings"]:
                a(f"> **WARN:** {w}\n")
            a("\n")

        if tr["n_train"] > 0:
            a("### Dimension Breakdowns (Training Set)\n\n")
            for dim_key, dim_label in report["dimensions"]:
                rows = tr["dim_breakdowns"].get(dim_key, [])
                if not rows:
                    continue
                a(f"#### {dim_label}\n\n")
                a("| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |\n")
                a("|-------|---|-----|----------|----------|--------|----------|----------|----------|\n")
                for val, st, row_warns in rows:
                    flag  = " ⚠" if st["n"] < _N_WARN else ""
                    mfe_s = _f(st.get("avg_mfe"),    "+.4f", "%")
                    mae_s = _f(st.get("avg_mae"),    "+.4f", "%")
                    rr_s  = _f(st.get("avg_real_r"), "+.4f", "R")
                    a(f"| {val} | {st['n']}{flag} | {st['wr']:.1f}% | "
                      f"{st['avg_pnl']:+.4f}% | {st['avg_conf']:.1f} | {st['avg_rr']:.2f} | "
                      f"{mfe_s} | {mae_s} | {rr_s} |\n")
                dim_warns = [w for _, _, rw in rows for w in rw]
                if dim_warns:
                    a("\n")
                    for w in dim_warns:
                        a(f"> **WARN:** {w}\n")
                a("\n")

            # Phase I-4: Dedicated MFE/MAE breakdown by Session / FVG quality / MSS quality
            # Pull training signals for this tier
            _tr_sigs = report.get("_tier_train_sigs", {}).get(tid, [])
            if _tr_sigs:
                a("### Excursion Analysis (MFE / MAE / realized_R by Dimension)\n\n")
                a("> MFE = max favorable move from entry (before SL/TP1).  \n")
                a("> MAE = max adverse move from entry (before SL/TP1).  \n")
                a("> realR = result in R-multiples (WIN/PARTIAL uses TP1 exit).  \n\n")
                for dim_key, dim_label in [("session", "Session"),
                                           ("fvg_quality", "FVG Quality"),
                                           ("mss_quality", "MSS Quality")]:
                    _excursion_section(a, _tr_sigs, dim_key, dim_label, tid)

        a("---\n\n")

    # ── All-matched view ───────────────────────────────────
    a("## All-Matched View\n\n")
    a("> Each signal is counted in **every** template it satisfies (overlapping counts).\n\n")
    a("> **Note:** If Tier B and Tier C show identical N and metrics, this is expected — "
      "every signal that qualifies for Tier C (MSS≥LOW + FVG≥LOW) also qualifies for Tier B "
      "(MSS≥MEDIUM + FVG≥LOW + session check), because the bot's entry gates already ensure "
      "MSS≥MEDIUM and an active killzone session on every generated signal. "
      "This is not a bug; it confirms that Tier C adds no additional coverage beyond Tier B.\n\n")
    a("| Template | Train N | Train WR% | Holdout N | Holdout WR% | Avg MFE% | Avg MAE% | Avg realR |\n")
    a("|----------|---------|-----------|-----------|-------------|----------|----------|----------|\n")
    for tid in ["TIER_A", "TIER_B", "TIER_C"]:
        am    = report["all_matched"].get(tid, {})
        st_tr = am.get("train")
        wr_tr = f"{st_tr['wr']:.1f}%"           if st_tr else "—"
        wr_ho = f"{am['holdout']['wr']:.1f}%"   if am.get("holdout") else "—"
        mfe_s = _f(st_tr.get("avg_mfe")    if st_tr else None, "+.4f", "%")
        mae_s = _f(st_tr.get("avg_mae")    if st_tr else None, "+.4f", "%")
        rr_s  = _f(st_tr.get("avg_real_r") if st_tr else None, "+.4f", "R")
        a(f"| {tier_labels[tid]} | {am.get('n_train',0)} | {wr_tr} | "
          f"{am.get('n_holdout',0)} | {wr_ho} | {mfe_s} | {mae_s} | {rr_s} |\n")
    a("\n---\n\n")

    # ── Overfitting warnings ───────────────────────────────
    a("## Overfitting & Data Quality Warnings\n\n")
    if report["all_warnings"]:
        for w in report["all_warnings"]:
            a(f"- **WARN:** {w}\n")
    else:
        a("No overfitting warnings detected.\n")
    a(f"\n_Sample size thresholds: n < {_N_WARN} = insufficient | "
      f"n >= {_N_RELI} = reliable_  \n")
    a(f"_Concentration threshold: >= {int(_CONC_THRESH * 100)}% of signals "
      f"in one regime or session_\n")
    a("\n---\n\n")

    # ── Phase I-4 notes ────────────────────────────────────
    a("## Phase I-4 Excursion Tracking Notes\n\n")
    a("| Field | Formula | Notes |\n")
    a("|-------|---------|-------|\n")
    a("| mfe_pct | BUY: (max_high - entry) / entry * 100 | Stops at SL or TP1 hit |\n")
    a("| mfe_pct | SELL: (entry - min_low) / entry * 100 | Stops at SL or TP1 hit |\n")
    a("| mae_pct | BUY: (entry - min_low) / entry * 100 | Stops at SL or TP1 hit |\n")
    a("| mae_pct | SELL: (max_high - entry) / entry * 100 | Stops at SL or TP1 hit |\n")
    a("| realized_r | WIN/PARTIAL: net_tp1_pct / abs(sl_pct) | Conservative — uses TP1 as exit |\n")
    a("| realized_r | LOSS: net_sl_pct / abs(sl_pct) | ~= -1.0 (slightly worse due to fees) |\n")
    a("| realized_r | EXPIRED: 0.0 | No P&L |\n")
    a("\n> **Note on sl_pct sign:** `compute_ict_trade_plan()` stores `sl_pct` as a "
      "**negative** value (e.g. `-0.85` for a 0.85% SL distance). "
      "Always use `abs(sl_pct)` as the denominator in R-multiple calculations.\n")
    a("\n> **Note on Median realR = 0.0:** A median realized_R of exactly 0.0 does **not** mean "
      "the strategy breaks even. It typically means EXPIRED trades (realR = 0.0 by definition) "
      "occupy the median position in the sorted distribution. Check `expired` count in the stats "
      "table to confirm. If expired > 25% of N, the median is driven by time-out exits, "
      "not true breakeven results.\n")
    a("\n")

    # ── Phase 5A safety layer simulation ──────────────────────
    a("---\n\n## Phase 5A — Template Safety Layer Simulation\n\n")
    a("> **Informational only.** This section simulates how many backtest signals would be "
      "blocked by each Phase 5A safety rule. It does **not** enforce any live gate. "
      "Rules requiring live DB state (sample gate, circuit breaker) are noted as "
      "requiring live data.\n\n")
    a(f"**Active configuration:**  \n"
      f"- `EXECUTION_MODE` = `{EXECUTION_MODE}` (set in crypto_alert.py)\n"
      f"- `TEMPLATE_MIN_SAMPLE` = {TEMPLATE_MIN_SAMPLE} closed trades  \n"
      f"- `CIRCUIT_BREAKER_LOOKBACK` = {CIRCUIT_BREAKER_LOOKBACK} trades, "
      f"min WR = {CIRCUIT_BREAKER_MIN_WR:.0%}  \n"
      f"- `BLOCK_RANGING_LIVE` = {BLOCK_RANGING_LIVE}, templates = {sorted(BLOCK_RANGING_TEMPLATES)}  \n"
      f"- `TIER_DAILY_LIVE_CAPS` = {TIER_DAILY_LIVE_CAPS}\n\n")

    _all_sigs = report.get("_all_signals", [])
    _n_all    = len(_all_sigs)

    # Rule 1: PAPER_ONLY — Tier C always blocked
    _tier_c_n = sum(1 for s in _all_sigs if s.get("matched_template_id") == "TIER_C")

    # Rule 2: PAPER_ONLY — daily cap = 0 for any tier
    _cap_zero_tiers = [tid for tid, cap in TIER_DAILY_LIVE_CAPS.items() if cap == 0]
    _cap_zero_n     = sum(1 for s in _all_sigs
                          if s.get("matched_template_id") in _cap_zero_tiers
                          and s.get("matched_template_id") != "TIER_C")  # don't double-count

    # Rule 3: BLOCKED_BY_REGIME_SAFETY
    _ranging_block_n = 0
    if BLOCK_RANGING_LIVE:
        _ranging_block_n = sum(
            1 for s in _all_sigs
            if s.get("regime", "") == "RANGING"
            and s.get("matched_template_id", "NONE") in BLOCK_RANGING_TEMPLATES
            and s.get("matched_template_id") not in _cap_zero_tiers
            and s.get("matched_template_id") != "TIER_C"
        )

    # Rules 4-5 require live DB state — count signals needing live check
    _needs_live_check = sum(
        1 for s in _all_sigs
        if s.get("matched_template_id") not in (["TIER_C"] + _cap_zero_tiers)
    )

    _total_simulated_blocks = _tier_c_n + _cap_zero_n + _ranging_block_n
    _pct = _total_simulated_blocks / max(_n_all, 1) * 100

    a("| Safety Rule | Trigger Condition | Signals Blocked | % of All |\n")
    a("|------------|-------------------|-----------------|----------|\n")
    a(f"| PAPER_ONLY — Tier C | `matched_template_id == TIER_C` | {_tier_c_n} | "
      f"{_tier_c_n / max(_n_all,1) * 100:.1f}% |\n")
    if _cap_zero_tiers:
        a(f"| PAPER_ONLY — cap=0 | Tier {_cap_zero_tiers} daily cap = 0 | {_cap_zero_n} | "
          f"{_cap_zero_n / max(_n_all,1) * 100:.1f}% |\n")
    if BLOCK_RANGING_LIVE:
        a(f"| BLOCKED_BY_REGIME_SAFETY | RANGING + template in {sorted(BLOCK_RANGING_TEMPLATES)} | "
          f"{_ranging_block_n} | {_ranging_block_n / max(_n_all,1) * 100:.1f}% |\n")
    a(f"| INSUFFICIENT_SAMPLE | < {TEMPLATE_MIN_SAMPLE} closed trades per template | "
      f"**requires live DB** | — |\n")
    a(f"| PAUSED_BY_CIRCUIT_BREAKER | Rolling {CIRCUIT_BREAKER_LOOKBACK}-trade WR "
      f"< {CIRCUIT_BREAKER_MIN_WR:.0%} | **requires live DB** | — |\n")
    a(f"| DAILY_CAP_REACHED | Daily live count ≥ cap per tier | **requires live DB** | — |\n")
    a(f"\n**Subtotal (simulatable rules):** {_total_simulated_blocks} / {_n_all} signals "
      f"({_pct:.1f}%) would be blocked before reaching live execution.\n\n")

    # Regime safety breakdown
    if BLOCK_RANGING_LIVE:
        a("### Regime Safety — RANGING Breakdown by Template\n\n")
        a("| Template | RANGING Signals | RANGING WR% | Would Block? |\n")
        a("|----------|-----------------|-------------|-------------|\n")
        for tid in ["TIER_A", "TIER_B", "TIER_C", "NONE"]:
            _t_sigs   = [s for s in _all_sigs if s.get("matched_template_id") == tid]
            _r_sigs   = [s for s in _t_sigs   if s.get("regime","") == "RANGING"]
            _r_n      = len(_r_sigs)
            if _r_n == 0:
                continue
            _wins     = sum(1 for s in _r_sigs
                            if s.get("outcome","") in ("WIN","PARTIAL_TP1","PARTIAL_TP2"))
            _r_wr     = _wins / _r_n * 100
            _blocked  = "YES" if BLOCK_RANGING_LIVE and tid in BLOCK_RANGING_TEMPLATES else "NO"
            a(f"| {tier_labels.get(tid,tid)} | {_r_n} | {_r_wr:.1f}% | {_blocked} |\n")
        a("\n")

    a(f"_Phase 5A constants defined in `crypto_alert.py`. "
      f"Set `EXECUTION_MODE = \"LIVE\"` to activate live blocking.\n")
    a("\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return path


def generate_recommendations(all_signals, _train_sigs=None):
    if not all_signals: return []
    src = _train_sigs if _train_sigs is not None else all_signals
    recs      = []
    by_regime = defaultdict(list)
    by_conf   = defaultdict(list)
    by_token  = defaultdict(list)
    by_dir    = defaultdict(list)
    by_sweep  = defaultdict(list)
    by_trend  = defaultdict(list)
    for s in src:
        by_regime[s["regime"]].append(s)
        by_conf[s["confidence"]].append(s)
        by_token[s["token"]].append(s)
        by_dir[s["signal"]].append(s)
        by_sweep[s.get("sweep_type","?")].append(s)
        by_trend[s.get("trend_1h","NEUTRAL")].append(s)

    for regime, sigs in by_regime.items():
        if len(sigs) < 3: continue
        w = _wr(sigs)
        if w < 45:
            recs.append({"type": "WARNING", "area": "Regime",
                "title":  f"{regime} underperforming",
                "detail": f"{len(sigs)} signals → {w}% WR",
                "action": f"Consider blocking {regime} in REGIME_RULES"})
        elif w >= 70:
            recs.append({"type": "STRENGTH", "area": "Regime",
                "title":  f"{regime} is best regime",
                "detail": f"{len(sigs)} signals → {w}% WR",
                "action": "Prioritize this regime — settings work well here"})

    for sweep_type, sigs in by_sweep.items():
        if len(sigs) < 3: continue
        w = _wr(sigs)
        label = f"{'BSL (SELL)' if sweep_type == 'BSL' else 'SSL (BUY)'}"
        if w < 45:
            recs.append({"type": "WARNING", "area": "Sweep Type",
                "title":  f"{label} sweep underperforming",
                "detail": f"{len(sigs)} signals → {w}% WR",
                "action": f"Tighten entry criteria for {sweep_type} sweeps"})
        elif w >= 70:
            recs.append({"type": "STRENGTH", "area": "Sweep Type",
                "title":  f"{label} sweep is the edge",
                "detail": f"{len(sigs)} signals → {w}% WR",
                "action": f"Focus on {sweep_type} setups — clearest structural edge"})

    for trend, sigs in by_trend.items():
        if len(sigs) < 3: continue
        w = _wr(sigs)
        if w >= 70 and trend in ("STRONG_BULL", "STRONG_BEAR"):
            recs.append({"type": "STRENGTH", "area": "1H Bias",
                "title":  f"Trend-confirmed {trend} entries win more",
                "detail": f"{len(sigs)} signals → {w}% WR",
                "action": "Strong trend alignment is the top signal quality filter"})

    lo = [s for s in all_signals if s["confidence"] <= 5]
    hi = [s for s in all_signals if s["confidence"] >= 7]
    if lo and _wr(lo) < 50:
        recs.append({"type": "WARNING", "area": "Confidence",
            "title":  "Low-confidence signals drag WR",
            "detail": f"Conf 1–5: {_wr(lo)}% WR ({len(lo)} sigs)",
            "action": "Only take Conf 7+ signals in live trading"})
    if hi and _wr(hi) >= 65:
        recs.append({"type": "STRENGTH", "area": "Confidence",
            "title":  "High-confidence signals are reliable",
            "detail": f"Conf 7–10: {_wr(hi)}% WR ({len(hi)} sigs)",
            "action": "Prioritize Conf 7+ — ICT quality score working"})

    bsigs = by_dir.get("BUY",  [])
    ssigs = by_dir.get("SELL", [])
    if len(bsigs) >= 3 and len(ssigs) >= 3 and abs(_wr(bsigs) - _wr(ssigs)) >= 20:
        worse = "SELL" if _wr(bsigs) > _wr(ssigs) else "BUY"
        recs.append({"type": "INFO", "area": "Direction",
            "title":  f"{worse} signals weaker",
            "detail": f"BUY: {_wr(bsigs)}% ({len(bsigs)}) | SELL: {_wr(ssigs)}% ({len(ssigs)})",
            "action": f"Be more selective with {worse} setups"})

    for token, sigs in by_token.items():
        if len(sigs) < 5: continue
        w = _wr(sigs)
        if w < 45:
            recs.append({"type": "WARNING", "area": "Token",
                "title":  f"{token} consistently underperforms",
                "detail": f"{len(sigs)} signals → {w}% WR",
                "action": f"Consider excluding {token} or raising entry quality bar"})

    ow = _wr(src)  # use IS-only WR for verdict; avoids IS+OOS blending masking overfit
    ow_label = f"IS WR {ow}% ({len(src)} sigs)" if src is not all_signals else f"{ow}% WR ({len(all_signals)} sigs)"
    if ow >= 55:
        recs.append({"type": "STRENGTH", "area": "Overall",
            "title":  "ICT strategy shows positive edge",
            "detail": f"Overall: {ow_label}",
            "action": "Continue paper trading — need N≥30 OOS signals before live deployment"})
    elif ow < 48:
        recs.append({"type": "WARNING", "area": "Overall",
            "title":  "Below BEW — strategy needs redesign",
            "detail": f"Overall: {ow_label}",
            "action": "Try Design B (drop MSS requirement) or widen FVG min gap filter"})

    return recs


def save_to_db(all_signals, days=90, config_hash=None):
    """Insert one backtest_runs row + N backtest_signals rows.

    Parameters
    ----------
    config_hash : str, optional
        SHA-256 hash of the parameter configuration that produced these signals.
        Stored on the backtest_runs row so n_trials_for_dsr can count DISTINCT
        param configurations rather than raw row count (FIX 1, 2026-05-23).
        If None, row is stored with NULL config_hash and counted in the legacy
        bucket (all NULL rows collectively count as 1 trial).
    """
    if not all_signals: return None
    try:
        init_backtest_db()
        conn    = _connect()
        rr_vals = [s["rr1"] for s in all_signals if s["rr1"] > 0]
        avg_rr  = round(sum(rr_vals) / len(rr_vals), 2) if rr_vals else 0

        train_sigs, test_sigs, cutoff = walk_forward_split(all_signals, train_frac=0.60)
        train_wr    = _wr(train_sigs)
        test_wr     = _wr(test_sigs)
        overfit_gap = round(train_wr - test_wr, 1)
        # Fix #15 (Cycle 5, 2026-05-22): add Wilson 95% CIs to IS/OOS WR so the
        # noise level is visible in the same place the WF gap is computed. At
        # n≈14 OOS, the CI typically spans ±20pp — a WF gap of 4-10pp is well
        # inside that noise band and should not be interpreted as edge validation.
        _is_w = sum(1 for s in train_sigs if is_win(s["outcome"]))
        _os_w = sum(1 for s in test_sigs  if is_win(s["outcome"]))
        _is_lo, _is_hi = _wilson_ci(len(train_sigs), _is_w)
        _os_lo, _os_hi = _wilson_ci(len(test_sigs),  _os_w)
        print(f"\n[WALK-FORWARD VALIDATION] Fixed OOS boundary: {WF_OOS_START_DATE} (locked wall-clock split)")
        print(f"  Cutoff          : {cutoff}")
        print(f"  IN-SAMPLE       : WR {train_wr:.1f}% [{_is_lo:.0f}-{_is_hi:.0f}%]  ({len(train_sigs)} sigs)")
        print(f"  OUT-OF-SAMPLE   : WR {test_wr:.1f}% [{_os_lo:.0f}-{_os_hi:.0f}%]  ({len(test_sigs)} sigs)")
        print(f"  WF gap          : {overfit_gap:+.1f}%  "
              + ("⚠ WARNING: possible overfit (>10%)" if overfit_gap > 10 else "OK (<10%)"))
        if len(test_sigs) < _N_WARN:
            import math as _math
            _n_oos = len(test_sigs)
            _p_oos = test_wr / 100.0
            _se    = _math.sqrt(_p_oos * (1 - _p_oos) / max(_n_oos, 1))
            _margin = 1.96 * _se * 100
            _lo    = max(0.0, _p_oos * 100 - _margin)
            _hi    = min(100.0, _p_oos * 100 + _margin)
            print(f"  ⚠ STAT WARNING  : OOS n={_n_oos} < {_N_WARN} — 95% CI on OOS WR ≈ "
                  f"[{_lo:.0f}%, {_hi:.0f}%] (±{_margin:.0f}pp). "
                  f"WF gap of {overfit_gap:+.1f}% is within noise at this sample size. "
                  f"Do not interpret as validated edge.")

        summary = build_summary(all_signals)
        summary["config_mode"]  = "live_mirror" if ACTIVE_CONFIG is LIVE_CONFIG else "research"
        _cfg_sd = ACTIVE_CONFIG
        summary["config_dirs"]  = ("BUY+SELL" if (_cfg_sd.enable_buy and _cfg_sd.enable_sell)
                                   else "BUY-only" if _cfg_sd.enable_buy else "SELL-only")
        summary["walk_forward"] = {
            "train_wr":    train_wr,
            "test_wr":     test_wr,
            "overfit_gap": overfit_gap,
            "n_train":     len(train_sigs),
            "n_test":      len(test_sigs),
            "cutoff":      cutoff,
        }
        recs   = generate_recommendations(all_signals, _train_sigs=train_sigs)
        cur    = conn.execute(
            """INSERT INTO backtest_runs
               (run_date,days,total_signals,overall_wr,avg_rr,status,summary,recommendations,config_hash)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), days,
             len(all_signals), _wr(all_signals), avg_rr, "DONE",
             json.dumps(summary), json.dumps(recs), config_hash))
        run_id = cur.lastrowid
        for s in all_signals:
            conn.execute(
                """INSERT INTO backtest_signals
                   (run_id,token,signal,price,ts,regime,confidence,wscore,margin,
                    conflict,tp1_pct,sl_pct,rr1,
                    net_tp1_pct,net_tp2_pct,net_tp3_pct,net_sl_pct,net_rr1,breakeven_wr,
                    sweep_type,fvg_pct,trend_1h,
                    bias_4h,ifvg_present,ifvg_direction,ifvg_age_bars,ifvg_5m_used,
                    session,hour_utc,day_of_week,
                    dr_location,mss_quality,fvg_quality,smt_type,smt_confirmed,entry_type,
                    tp_reached,outcome,matched_template_id,template_scores_json,
                    mfe_pct,mae_pct,realized_r,
                    tb_bin,tb_touch,tb_ret,tb_t1)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, s["token"], s["signal"], s["price"], s["ts"],
                 s["regime"], s["confidence"], s["wscore"], s["margin"],
                 s["conflict"], s["tp1_pct"], s["sl_pct"], s["rr1"],
                 s["net_tp1_pct"], s.get("net_tp2_pct"), s.get("net_tp3_pct"),  # Fix #16
                 s["net_sl_pct"], s["net_rr1"], s["breakeven_wr"],
                 s.get("sweep_type","?"), s.get("fvg_pct", 0.0), s.get("trend_1h","NEUTRAL"),
                 s.get("bias_4h","NEUTRAL"), s.get("ifvg_present",0),
                 s.get("ifvg_direction",""), s.get("ifvg_age_bars", 0),
                 s.get("ifvg_5m_used", 0),
                 s.get("session","OVERNIGHT"), s.get("hour_utc",0), s.get("day_of_week",0),
                 s.get("dr4h_location","UNKNOWN"),  # signal dict key: dr4h_location → DB column: dr_location
                 s.get("mss_quality","NONE"),
                 s.get("fvg_quality","NONE"), s.get("smt_type","NONE"),
                 s.get("smt_confirmed", 0),
                 s.get("entry_type","ZONE_TOUCH"),
                 s["tp_reached"], s["outcome"],
                 s.get("matched_template_id", "NONE"),
                 s.get("template_scores_json", None),
                 s.get("mfe_pct",    None),
                 s.get("mae_pct",    None),
                 s.get("realized_r", None),
                 s.get("tb_bin",   None),
                 s.get("tb_touch", None),
                 s.get("tb_ret",   None),
                 s.get("tb_t1",    None)))
        conn.commit(); conn.close()
        print(f"\n[DB] Run #{run_id} saved — {len(all_signals)} signals, {_wr(all_signals)}% WR")
        return run_id
    except Exception as e:
        print(f"[DB ERROR] save_to_db: {e}"); return None


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
def _compute_run_config_hash() -> str:
    """Hash everything that affects signal output for checkpoint invalidation.

    Any change here means a checkpoint written by a previous run cannot be
    safely resumed — the new run will start fresh.
    """
    return compute_config_hash({
        "ACTIVE_CONFIG":          ACTIVE_CONFIG,
        "BINANCE_TOKENS":         dict(BINANCE_TOKENS),
        "BACKTEST_DAYS":          BACKTEST_DAYS,
        "WARMUP_BARS":            WARMUP_BARS,
        "FORWARD_BARS":           FORWARD_BARS,
        "REGIME_WINDOW":          REGIME_WINDOW,
        "COOLDOWN_BARS":          COOLDOWN_BARS,
        "ENTRY_WINDOW":           ENTRY_WINDOW,
        "ICT_SWING_N":            ICT_SWING_N,
        "ICT_SWEEP_LOOKBACK":     ICT_SWEEP_LOOKBACK,
        "ICT_DISP_MAX_LOOK":      ICT_DISP_MAX_LOOK,
        "ICT_MSS_HORIZON":        ICT_MSS_HORIZON,
        "ICT_FVG_MIN_GAP":        ICT_FVG_MIN_GAP,
        "ICT_MAX_SETUP_AGE_BARS": ICT_MAX_SETUP_AGE_BARS,
        "ICT_MSS_DISP_MAX_GAP":   ICT_MSS_DISP_MAX_GAP,
        "ENTRY_REACTION_LOOKBACK": ENTRY_REACTION_LOOKBACK,
        "ROUND_TRIP_COST_PCT":    ROUND_TRIP_COST_PCT,
        "FEE_PCT":                FEE_PCT,
        "SLIPPAGE_PCT":           SLIPPAGE_PCT,
        "STRATEGY_VERSION":       STRATEGY_VERSION,
    })


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="TradeAI backtest engine (Phase A-3: checkpointed)",
        allow_abbrev=False,
    )
    p.add_argument("--no-resume", action="store_true",
                   help="Ignore any existing checkpoint and start fresh")
    p.add_argument("--clear-checkpoint", action="store_true",
                   help="Delete the checkpoint file and exit (no backtest run)")
    p.add_argument("--fresh", action="store_true",
                   help="Ignore OHLCV cache and re-fetch all data from Binance")
    p.add_argument("--clear-cache", action="store_true",
                   help="Delete all cached OHLCV files and exit (no backtest run)")
    return p.parse_args()


def main():
    global _OHLCV_USE_CACHE
    args = _parse_args()

    if args.clear_checkpoint:
        clear_checkpoint()
        print("[CKPT] checkpoint cleared — exiting")
        return

    if args.clear_cache:
        import shutil
        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)
            print(f"[CACHE] cleared — {CACHE_DIR} deleted")
        else:
            print("[CACHE] nothing to clear — cache directory does not exist")
        return

    if args.fresh:
        _OHLCV_USE_CACHE = False
        print("[CACHE] --fresh: ignoring cache, re-fetching all data from Binance")

    os.makedirs(os.path.join(_ROOT, "data"), exist_ok=True)
    _tee = _Tee(sys.stdout)
    sys.stdout = _tee
    _cfg  = ACTIVE_CONFIG
    _dirs = ("BUY+SELL" if (_cfg.enable_buy and _cfg.enable_sell)
             else "BUY-only" if _cfg.enable_buy else "SELL-only")
    _mode = "LIVE mirror" if _cfg is LIVE_CONFIG else "Research"
    print("=" * 68)
    print("  TRADEAI — ICT BACKTESTING ENGINE  (Phase 4.7)")
    print(f"  Mode      : {_mode} ({_dirs})")
    print(f"  Strategy  : Liquidity Sweep + MSS + FVG + 5M iFVG Precision")
    print(f"  Period    : Last {BACKTEST_DAYS} days")
    print(f"  TF Stack  : 4H bias | 1H TP levels | 5M sweep/MSS/FVG (Phase 4.8)")
    print(f"  Entry win : {ENTRY_WINDOW}×5M = 4H  |  Outcome: {FORWARD_BARS}×5M = {FORWARD_BARS//12}H")
    _sell_ok     = sorted(_cfg.sell_allowed_regimes) if _cfg.sell_allowed_regimes else []
    _sell_ok_str = f" | SELL-ok: {', '.join(_sell_ok)}" if _sell_ok else ""
    print(f"  Gates     : 4H={_cfg.bias_4h_gate} | 1H={_cfg.trend_1h_gate} | Blocked: {', '.join(sorted(_cfg.blocked_regimes))}{_sell_ok_str}")
    print(f"  Fees      : RT={ROUND_TRIP_COST_PCT*100:.2f}% ({FEE_PCT*100:.2f}%/side fee + {SLIPPAGE_PCT*100:.2f}%/side slippage)")
    print(f"  Tokens    : {', '.join(BINANCE_TOKENS.keys())}")
    print("=" * 68)
    print("\nNote: VPN required (Binance blocked in Philippines)\n")

    init_backtest_db()
    _bt_ogd_weights = load_backtest_ogd_weights()
    if _bt_ogd_weights:
        print(f"[OGD] Loaded backtest weights for {len(_bt_ogd_weights)} token(s): "
              f"{', '.join(sorted(_bt_ogd_weights))}")
    else:
        print("[OGD] No backtest_token_weights found — using AE_DEFAULT_WEIGHTS for all tokens")

    # ── Phase A-3: checkpoint-aware resume ───────────────────
    _run_config_hash = _compute_run_config_hash()
    _ckpt_exists, _ckpt_summary = describe_checkpoint()
    if _ckpt_exists:
        print(f"[CKPT] {_ckpt_summary}")
    all_signals: list = []
    completed_tokens: set = set()
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not args.no_resume:
        _resumed = load_checkpoint(_run_config_hash)
        if _resumed is not None:
            all_signals = list(_resumed.get("all_signals", []))
            completed_tokens = set(_resumed.get("completed_tokens", []))
            started_at = _resumed.get("started_at", started_at)
            print(f"[CKPT] RESUMING — skipping {len(completed_tokens)} completed tokens "
                  f"({', '.join(sorted(completed_tokens))}); "
                  f"{len(all_signals)} signals carried over")
        elif _ckpt_exists:
            print("[CKPT] checkpoint exists but config has changed — starting fresh "
                  "(use --clear-checkpoint to remove the stale file)")
    elif _ckpt_exists:
        print("[CKPT] --no-resume set — ignoring existing checkpoint (not deleted)")

    btc_c1h_ref: dict = {}
    btc_c5m_ref: dict = {}
    btc_c4h_ref: dict = {}

    for token, symbol in BINANCE_TOKENS.items():
        # On resume, every subsequent token needs BTC reference candles for
        # SMT divergence — always refetch BTC if it's the first token or if we
        # resumed past it (one extra fetch ~ <30s, vs hours of resimulation).
        if token in completed_tokens and token != "BTC":
            print(f"[{token}] SKIP — already in checkpoint")
            continue
        if token in completed_tokens and token == "BTC":
            # Refetch BTC reference data for downstream tokens, but don't resimulate
            print(f"[BTC] checkpoint hit — refetching reference candles only (no resim)...",
                  end=" ", flush=True)
            btc_c4h_ref = fetch_cached(symbol, "4h", BACKTEST_DAYS) or {}
            btc_c1h_ref = fetch_cached(symbol, "1h", BACKTEST_DAYS) or {}
            btc_c5m_ref = fetch_cached(symbol, "5m", BACKTEST_DAYS) or {}
            print(f"{len(btc_c5m_ref.get('closes', []))} 5M | "
                  f"{len(btc_c1h_ref.get('closes', []))} 1H | "
                  f"{len(btc_c4h_ref.get('closes', []))} 4H bars (reference only)")
            continue

        _cached_label = "(cached)" if _OHLCV_USE_CACHE and _cache_load(symbol, "5m", BACKTEST_DAYS) else "(live fetch)"
        print(f"[{token}] Fetching {BACKTEST_DAYS}d history... {_cached_label}", end=" ", flush=True)
        c4h  = fetch_cached(symbol, "4h",  BACKTEST_DAYS)
        c1h  = fetch_cached(symbol, "1h",  BACKTEST_DAYS)
        c5m  = fetch_cached(symbol, "5m",  BACKTEST_DAYS)
        if not c1h or not c5m:
            print("FAILED — no data"); continue
        n4h = len(c4h["closes"]) if c4h else 0
        n5m = len(c5m["closes"]) if c5m else 0
        print(f"{n5m} 5M | {len(c1h['closes'])} 1H | {n4h} 4H bars")

        if token == "BTC":
            btc_c1h_ref = c1h
            btc_c5m_ref = c5m
            btc_c4h_ref = c4h

        print(f"[{token}] Simulating ICT signals...", end=" ", flush=True)
        sigs = run_backtest_token(
            token, c5m, c1h, c4h,
            btc_c1h=None if token == "BTC" else btc_c1h_ref,
            btc_c5m=None if token == "BTC" else btc_c5m_ref,
            config=ACTIVE_CONFIG,
            ogd_weights=_bt_ogd_weights,
        )
        print(f"{len(sigs)} signals generated")
        all_signals.extend(sigs)
        completed_tokens.add(token)
        # Persist progress after every token so a kill mid-run loses at most one token's work.
        if save_checkpoint(_run_config_hash, completed_tokens, all_signals, started_at=started_at):
            print(f"[CKPT] saved — {len(completed_tokens)} tokens done, {len(all_signals)} signals")
        time.sleep(0.5)

    print_report(all_signals)
    wf_results = run_rolling_walk_forward(all_signals, train_days=90, test_days=30, step_days=30)
    print_rolling_wf_report(wf_results)

    # Sprint 3 item 4 / Top-10 #5: CPCV + Deflated Sharpe — honest metrics
    # alongside the single-split walk-forward above. Skipped silently if the
    # module is missing so this never breaks the existing backtest flow.
    try:
        from validation import cpcv_summary, cpcv_text_report
        # FIX 1 (2026-05-23): count DISTINCT config_hash values, not raw rows.
        # Same-config re-runs are NOT independent trials per Bailey/LdP 2014 — the
        # selection-bias correction counts distinct PARAM CONFIGURATIONS tested.
        # Legacy rows (config_hash IS NULL) collectively count as 1 historical
        # trial (the pre-FIX-1 era) to remain conservative.
        _n_trials_dsr = None
        _sr_trial_std_honest = None  # FIX 1 Part 2 (2026-05-23): honest cross-config std
        try:
            import sqlite3 as _sqlite3
            _conn = _sqlite3.connect(BT_DB_PATH)
            _distinct = _conn.execute(
                "SELECT COUNT(DISTINCT config_hash) FROM backtest_runs "
                "WHERE config_hash IS NOT NULL"
            ).fetchone()[0] or 0
            _has_legacy = _conn.execute(
                "SELECT 1 FROM backtest_runs WHERE config_hash IS NULL LIMIT 1"
            ).fetchone() is not None
            # FIX 1 Part 2: read persisted cross-config sr_trial_std from bot_state.
            # Computed by scripts/compute_cross_config_sr_std.py. Bypasses the
            # within-fold proxy used as anti-conservative fallback. Honest per
            # Bailey/LdP 2014 — std of OOS Sharpes across distinct configs.
            try:
                _row = _conn.execute(
                    "SELECT value FROM bot_state WHERE key = 'cross_config_sr_trial_std'"
                ).fetchone()
                if _row and _row[0]:
                    _blob = json.loads(_row[0])
                    _cand = _blob.get("value")
                    if isinstance(_cand, (int, float)) and _cand > 0:
                        _sr_trial_std_honest = float(_cand)
            except Exception:
                _sr_trial_std_honest = None
            # C-D (audit 2026-05-25): read cumulative_min_trials seed so a DB wipe
            # doesn't reset the selection-bias denominator. Without this, post-wipe
            # n_trials_for_dsr drops to ~2 instead of the historic ~27, weakening
            # the DSR multiple-testing correction by ~75%.
            _cumulative_min_trials = 0
            try:
                _row2 = _conn.execute(
                    "SELECT value FROM bot_state WHERE key = 'cumulative_min_trials'"
                ).fetchone()
                if _row2 and _row2[0]:
                    _blob2 = json.loads(_row2[0])
                    _cm = _blob2.get("value")
                    if isinstance(_cm, int) and _cm > 0:
                        _cumulative_min_trials = _cm
            except Exception:
                _cumulative_min_trials = 0
            _conn.close()
            # Add 1 to represent the entire legacy bucket as a single historical trial.
            # Add 1 more to count THIS pending run (not yet saved when CPCV runs).
            _candidate = _distinct + (1 if _has_legacy else 0) + 1
            # C-D: take max with cumulative seed so DB wipe can't artificially
            # lower the selection-bias correction below the honest historic count.
            _candidate = max(_candidate, _cumulative_min_trials)
            if _candidate > 1:
                _n_trials_dsr = int(_candidate)
        except Exception:
            _n_trials_dsr = None
        _cpcv = cpcv_summary(
            all_signals,
            n_trials_for_dsr=_n_trials_dsr,
            sr_trial_std_for_dsr=_sr_trial_std_honest,  # None falls back to proxy
        )
        if _sr_trial_std_honest is not None:
            print(f"\n[CPCV] Using HONEST cross-config sr_trial_std={_sr_trial_std_honest:.4f} "
                  f"(FIX 1 Part 2; bypasses within-fold proxy)")
        print("\n" + cpcv_text_report(_cpcv))
    except Exception as _cpcv_exc:
        print(f"\n[CPCV] skipped — {type(_cpcv_exc).__name__}: {_cpcv_exc}")

    tmpl_report    = template_comparison_report(all_signals)
    print_template_report(tmpl_report)
    _tmpl_out_dir  = os.path.join(_ROOT, "docs", "ict_strategy_variant_learner")
    _tmpl_md_path  = write_template_performance_md(tmpl_report, _tmpl_out_dir)
    print(f"[PHASE I-3] Template report → {_tmpl_md_path}")

    run_id = save_to_db(all_signals, BACKTEST_DAYS, config_hash=_run_config_hash)

    # Restore stdout and save the full run output to backtest_reports/
    sys.stdout = _tee._orig
    _rpt_dir = os.path.join(_ROOT, "backtest_reports")
    os.makedirs(_rpt_dir, exist_ok=True)
    _ts = datetime.now().strftime("%Y%m%d_%H%M")
    _rpt_name = f"Run{run_id}_{_ts}.txt" if run_id else f"Run_unsaved_{_ts}.txt"
    _rpt_path = os.path.join(_rpt_dir, _rpt_name)
    with open(_rpt_path, "w", encoding="utf-8") as f:
        f.write(_tee.getvalue())
    print(f"[REPORT] Saved → backtest_reports/{_rpt_name}")

    # Bootstrap OGD warm-start weights from ALL historical backtest signals.
    # run_id=None uses the full backtest_signals history (~43k rows) giving
    # meaningful per-token priors (H6 fix isolates scoring from bootstrap — no contamination).
    # Single-run bootstrap (~38 signals / ≤10 per token) produces near-default weights.
    if run_id:
        print(f"\n[ADAPTIVE] Bootstrapping weights from full backtest history (current run #{run_id} included)...")
        weight_engine.bootstrap_from_backtest(run_id=None, verbose=True)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_signals, f, indent=2)
    print(f"Full results saved → {OUTPUT_FILE}")
    # Phase A-3: clear the checkpoint only after the full pipeline (report,
    # walk-forward, template comparison, DB save, OGD bootstrap) completes.
    # If any of the above raises, the checkpoint stays in place so the next
    # invocation can resume without re-simulating every token.
    clear_checkpoint()
    print("[CKPT] cleared — run completed end-to-end")
    print("(Run monthly to track ICT edge over time)\n")


if __name__ == "__main__":
    main()
