"""
TradeAI — Crypto Signal Bot v11
Signal-only bot: analysis sent to Telegram, no auto-execution.

SETUP:
  1. Set env vars (see env.example.bat in scripts/):
       CMD:        set TELEGRAM_TOKEN=your_token
       PowerShell: $env:TELEGRAM_TOKEN="your_token"
  2. Run bot:     python crypto_alert.py
  3. Run tracker: python tracker.py  →  http://localhost:8888

Project layout:
  crypto_alert.py   — main bot (this file)
  backtest.py       — backtesting engine
  tracker.py        — web dashboard
  data/             — signals.db + backtest_results.json
  backups/          — auto-generated .bak files from Tune Bot
  docs/             — CLAUDE_CONTEXT.md, LEARNING_SYSTEM_AUDIT.md
  scripts/          — start_bot.bat, start_tracker.bat
"""
import os, sqlite3, requests, time, json, logging, html, re
import signal as _sig_module  # M-C fix (cycle-4): SIGTERM handler for graceful shutdown
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
from typing import Optional


def _h(value) -> str:
    """HTML-escape a value for safe inclusion in Telegram HTML messages.

    Telegram HTML mode (parse_mode='HTML') requires '<', '>', '&' to be
    escaped when they appear in dynamic content. Wrapping every interpolated
    f-string value with _h() prevents the API from misparsing the message
    and falling back to plain text (which would lose <pre> alignment).
    """
    return html.escape(str(value))

# Visual section divider used across all Telegram messages (signal, exit
# suggestion, heartbeat, startup). Same width everywhere for consistency.
_TG_HR = "━" * 22

# CY12-SIGNAL-SMTP fix (full audit 2026-05-29 resilience M-RES-1):
# module-global signal alerter, initialized to None and set to the
# MultiChannelAlerter instance in main(). When set, send_signal_msg
# routes through the alerter so SMTP fallback catches Telegram outages
# on actual signals (heartbeats already had this). When None (early
# startup, tests), falls back to direct send_telegram. The alerter
# self-tests both channels every ~24h.
_signal_alerter = None

# Load .env / .env.vault BEFORE any other module reads os.environ.
# secrets_loader is the bot's centralized secrets entry point (Phase A item #4).
from secrets_loader import load_env as _load_env
_load_env()

# ── Structured file logging ───────────────────────────────────
_LOG_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_LOG_PATH = os.path.join(_LOG_DIR, "bot.log")
os.makedirs(_LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        RotatingFileHandler(_LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("tradeai")
from heartbeat import Heartbeat, MultiChannelAlerter
from state_store import StateStore, PidFile
from adaptive_engine import (
    weight_engine, drift_detector, portfolio_layer,
    save_scalar_state, load_scalar_state, extract_ict_feature_scores,
    FEATURES as AE_FEATURES,
    DEFAULT_WEIGHTS as AE_DEFAULT_WEIGHTS, _QUALITY_SCORE, _SESSION_SCORE,
    DEGENERATE_THRESHOLD,
    # Task 13: EV scoring
    compute_ev_score, _utc_to_session,
    # Task 15: sample-size utilities
    label_sample_size, SAMPLE_N_OBSERVE, SAMPLE_N_USABLE, SAMPLE_N_WEAK, SAMPLE_N_STRONG, OGD_MIN_SAMPLES,
    MAX_OPEN_POSITIONS,
)
from strategy_engine import LIVE_CONFIG, evaluate_setup, meets_quality
from strategy_templates import (evaluate_confluences_vs_templates, seed_templates_table,
                                validate_tier_hierarchy,
                                # Phase B (2026-05-28) — CRT tier classifier
                                evaluate_crt_templates, CRT_TEMPLATE_IDS)
from indicators import (
    ema, calculate_rsi, calculate_atr, calculate_roc,
    get_trend, get_macd, detect_regime,
)
from ict_engine import (
    ICT_SWING_N, ICT_SWEEP_LOOKBACK, ICT_DISP_MAX_LOOK, ICT_MSS_HORIZON,
    ICT_FVG_MIN_GAP, ICT_IFVG_LOOKBACK, ICT_IFVG_PROXIMITY_PCT, ICT_MAX_SETUP_AGE_BARS,
    ICT_MSS_DISP_MAX_GAP, ENTRY_REACTION_LOOKBACK,
    ICT_FVG_SIZE_BONUS_THRESHOLD, ICT_SMT_LOOKBACK, ICT_SMT_REF_HORIZON, ICT_MIN_RR_GATE,
    DEALING_RANGE_LOOKBACK, MIN_TP1_MULT, MAX_SL_PCT, MIN_SL_PCT,
    ROUND_TRIP_COST_PCT, TOKEN_RT_COST, MAX_BREAKEVEN_WR,
    find_ict_swings, find_eqh_eql_clusters, detect_ict_sweep, detect_ict_displacement,
    score_ict_fvg, score_ict_mss,
    detect_fvg_entry_reaction, get_ict_4h_bias, compute_dealing_range,
    compute_liquidity_targets, detect_smt_divergence, detect_ict_ifvg,
    detect_5m_ifvg_entry, compute_ict_trade_plan,
    # CRT v1 Session 3 (audit cycle-7 2026-05-27): SL buffer used by CRT
    # scanner — must match backtest's ICT_SL_BUFFER_PCT exactly.
    ICT_SL_BUFFER_PCT,
)

# CRT v1 Session 3 (audit cycle-7 2026-05-27): live H4-CRT signal source.
# Default OFF (ENABLE_H4_CRT=0 in crt_engine.py). When enabled, the per-token
# scan loop runs a SECOND detection pass via crt_engine.detect_h4_crt() and
# emits signals tagged source='H4_CRT' alongside the canonical 5M sweep
# signals tagged source='5M_SWEEP'.
#
# Live/backtest parity by construction: ALL helpers + constants imported
# from crt_engine, NOT redefined here. Backtest's run_backtest_token_h4_crt
# uses the same imports — guaranteed byte-identical signal generation for
# identical OHLCV inputs.
from crt_engine import (
    detect_h4_crt, ENABLE_H4_CRT, H4_CRT_DISABLED_TOKENS,
    H4_CRT_C2_LOOKBACK, H4_CRT_MSS_HORIZON,
    compute_crt_trade_economics, crt_quality_to_confidence,
    crt_trade_rejection_reason,
    CRT_TP2_RR, CRT_TP3_RR,
    # v2 Wyckoff phase context (Option KK, audit cycle-7 2026-05-27)
    detect_wyckoff_context, is_crt_phase_aligned, WYCKOFF_PHASE_FILTER,
    # CRT Pro v1.1 — TP1 mode + 1H trend gate (2026-05-27)
    adjust_crt_tp1, CRT_TP1_MODE, CRT_REQUIRE_1H_TREND,
    # M-NEW-9 fix (cycle-9 audit 2026-05-28): import CRT_FORWARD_BARS so the
    # live expiry tracks the backtest outcome window (was hardcoded 48h).
    CRT_FORWARD_BARS,
    # OTE overlay (2026-05-28) — tagging only, no gate.
    compute_ote_overlay,
    # Cycle-12 unexplored axes (2026-05-29): FVG probe width + mitigation TTL.
    H4_CRT_FVG_PROBE_WIDTH, H4_CRT_MITIGATION_TTL_H,
    prune_consumed_zones,
)
# T1.2 — Funding rate overlay (2026-05-29, ENHANCEMENT_ROADMAP.md)
from funding_rate_client import (
    get_funding_rate,
    classify_funding_extreme,
    funding_confidence_bonus,
    is_funding_fetch_failed,
    FUNDING_BONUS_PCT as _FUNDING_BONUS_PCT,
)
# T1.3 — BTC correlation overlay (2026-05-29, ENHANCEMENT_ROADMAP.md)
from btc_correlation import (
    compute_btc_correlation,
    classify_btc_corr,
    btc_corr_confidence_bonus,
    BTC_CORR_WINDOW_MIN as _BTC_CORR_WIN,
)

_ROOT = os.path.dirname(os.path.abspath(__file__))

# Secrets — TELEGRAM_TOKEN / CHAT_ID — sourced via secrets_loader (Phase A #4 dotenv-vault).
# secrets_loader.load_env() is invoked at the very top of this file (above) so
# os.environ already reflects values from .env / .env.vault by the time we run.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
YOUR_CAPITAL   = float(os.environ.get("YOUR_CAPITAL", "1000.0"))
DB_PATH        = os.path.join(_ROOT, "data", "signals.db")

# Tunable constants — single source of truth lives in config.py. Imported here so
# every "from crypto_alert import X" path still works for backtest.py, tests,
# tracker.py, etc.; new code should prefer "from config import X" directly.
from config import (
    # universe + cadence
    BINANCE_TOKENS, TIMEFRAMES, STRATEGY_VERSION, CHECK_INTERVAL,
    STALE_CANDLE_THRESHOLD, BTC_STALE_FEED_S,
    # indicator params
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    ATR_PERIOD, ATR_SL_MULT, ROC_PERIOD, VOLUME_SPIKE,
    # signal safety
    SIGNAL_COOLDOWN, NEAR_LEVEL_PROX, SR_LOOKBACK, EXPIRY_BY_REGIME,
    # risk + kill switches
    RISK_PER_TRADE_PCT, MAX_POSITION_PCT,
    MAX_DAILY_LOSS_PCT, MAX_WEEKLY_LOSS_PCT,
    MAX_DAILY_LOSSES, MAX_CONSECUTIVE_LOSSES, SYMBOL_LOSS_COOLDOWN_H,
    # ops intervals
    PERF_CHECK_INTERVAL, HEARTBEAT_INTERVAL,
    API_RETRIES, API_DELAY, DOM_FETCH_INTERVAL, DOM_THRESHOLD,
    # template safety (Phase 5A)
    EXECUTION_MODE,
    # per-scanner kill switches (2026-05-27)
    ENABLE_5M_SWEEP,
    # Phase A — Limit-order fill window + slippage thresholds (2026-05-28)
    CRT_LIMIT_FILL_WINDOW_MIN, CRT_SLIPPAGE_WARN_PCT, CRT_SLIPPAGE_CRIT_PCT,
    TEMPLATE_MIN_SAMPLE, CIRCUIT_BREAKER_LOOKBACK, CIRCUIT_BREAKER_MIN_WR,
    TIER_DAILY_LIVE_CAPS, BLOCK_RANGING_LIVE, BLOCK_RANGING_TEMPLATES,
    # exit intelligence
    EXIT_SUGGESTION_COOLDOWN_H, EXIT_MIN_COVERAGE_PCT,
    EXIT_PARTIAL_COVERAGE_PCT, EXIT_STRONG_COVERAGE_PCT,
    # weighted scoring + regime rules
    WEIGHTS, SIGNAL_THRESHOLD, REGIME_RULES,
    # macro event filter
    MACRO_FILTER_ENABLED, MACRO_ADVISORY_ONLY,
    MACRO_PRE_WINDOW_H, MACRO_POST_WINDOW_H,
    # infra URLs / headers
    BINANCE_BASE, HEADERS, BTC_SYMBOL, COINGECKO_GLOBAL,
)
from event_calendar import is_macro_window as _is_macro_window

def new_state():
    return {
        "candles": {
            "4h":  {"opens":[],"highs":[],"lows":[],"closes":[],"volumes":[]},
            "1h":  {"opens":[],"highs":[],"lows":[],"closes":[],"volumes":[]},
            "15m": {"opens":[],"highs":[],"lows":[],"closes":[],"volumes":[]},
            "5m":  {"opens":[],"highs":[],"lows":[],"closes":[],"volumes":[]},
        },
        "avg_volume":        0.0,
        "last_signal_times": {"BUY": None, "SELL": None},  # per-direction cooldown timestamps
        "total_signals":     0,
        "last_regime":       "UNKNOWN",
        "recent_wr":         0.50,   # rolling win rate from DB; updated every 30 min
        "last_24h":          {},     # cached 24h price/volume data from last fetch
        "last_fetched_at":    0.0,   # unix timestamp of last successful candle refresh (any TF)
        "last_5m_fetched_at": 0.0,  # unix timestamp of last successful 5m candle refresh
        # M-NEW-5 fix (cycle-9 audit 2026-05-28): per-TF stale tracking. The
        # CRT scanner consumes 4H candles directly — without this tracker, a
        # silent stale-4H scenario (5M fetches succeed, 4H fetches fail) would
        # let the bot generate CRT signals from a frozen H4 candle range. The
        # generic last_fetched_at is updated when ANY TF succeeds, masking
        # per-TF failure modes.
        "last_4h_fetched_at": 0.0,  # unix timestamp of last successful 4h candle refresh
        "last_1h_fetched_at": 0.0,  # unix timestamp of last successful 1h candle refresh
        "consumed_sweeps":   set(),  # (bar_idx, round(level,6)) pairs already used for signals
        # CRT v1 Session 3 (LBC-H-2 close): one-shot mitigation set for H4 CRT.
        # Keyed on (c1_time, round(c1_high, 6), round(c1_low, 6)) — c1_time is
        # the H4 candle's TIMESTAMP so the entry survives cache rotation and
        # bot restart (persisted to state_store every cycle below).
        "consumed_h4_crt":   set(),
        "data_gap_bars":     0,      # H19: worst-case 5M gap bars from last fetch; >=3 skips signal
        "data_gap_bars_1h":  0,      # LOW #5: worst-case 1H gap bars; >=2 skips signal (2h blind spot)
        "data_gap_bars_4h":  0,      # LOW #5: worst-case 4H gap bars; >=1 skips signal (4h blind spot)
    }

STATE = {t: new_state() for t in BINANCE_TOKENS}
last_summary_date = None

BTC_STATE = {
    "candles":           {"1h": {}, "15m": {}, "5m": {}},
    "trend_1h":          "NEUTRAL",
    "trend_15m":         "NEUTRAL",
    "dominance":         0.0,
    "dom_dir":           "NEUTRAL",
    "last_candle_fetch": 0,
    "last_dom_fetch":    0,
    "feed_ok":           False,   # H18: False until first successful 1H candle fetch
    "feed_alert_ts":     0.0,     # H-F (cycle-4): last Telegram-alert epoch for feed-down dedup
}

# Performance state — updated by load_performance_state() every 30 min
REGIME_WR             = {}   # regime name → recent win rate (float 0-1)
CONF_WR               = {}   # confidence level (int) → {"wr": float, "count": int}
_conf_floor           = 1    # dynamic minimum confidence; signals below this are blocked
_signal_threshold_adj = 0    # dynamic offset for SIGNAL_THRESHOLD; steps ±1 per PERF_CHECK

# ══════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════
def _connect():
    """
    Open DB with WAL journal mode + 10s busy timeout + foreign key enforcement.
    WAL allows the tracker and bot to read/write concurrently without locking.
    busy_timeout makes writers wait up to 10s instead of immediately raising
    OperationalError: database is locked.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _connect()
    # Main signals table — includes regime columns
    conn.execute("""CREATE TABLE IF NOT EXISTS signals (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        token           TEXT    NOT NULL,
        signal          TEXT    NOT NULL,
        entry_price     REAL    NOT NULL,
        sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
        sl_pct REAL, tp1_pct REAL, tp2_pct REAL, tp3_pct REAL,
        rr1 REAL, rr2 REAL, rr3 REAL,
        confidence      INTEGER,
        mtf_bias        TEXT,
        mtf_conf        INTEGER,
        rsi             REAL,
        trend_4h        TEXT,
        trend_1h        TEXT,
        trend_5m        TEXT,
        confirms        INTEGER,
        atr             REAL,
        roc             REAL,
        vol_ratio       REAL,
        reasons         TEXT,
        timestamp       TEXT    NOT NULL,
        status          TEXT    DEFAULT 'OPEN',
        market_regime   TEXT,
        regime_adx      REAL,
        regime_eff      REAL,
        regime_atr_r    REAL,
        regime_conf     INTEGER,
        btc_bias        TEXT,
        btc_dom_dir     TEXT,
        wscore_buy      REAL,
        wscore_sell     REAL,
        conflict_level      TEXT,
        candle_pattern      TEXT,
        expires_at          TEXT,
        feature_scores_json TEXT,
        sweep_type          TEXT,
        session             TEXT,
        dr_location         TEXT,
        mss_quality         TEXT,
        fvg_quality         TEXT,
        smt_type            TEXT,
        entry_type          TEXT,
        ev_score            REAL,
        ev_sample_n         INTEGER,
        ev_status           TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS results (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id   INTEGER REFERENCES signals(id),
        tp1_hit     INTEGER DEFAULT 0,
        tp2_hit     INTEGER DEFAULT 0,
        tp3_hit     INTEGER DEFAULT 0,
        sl_hit      INTEGER DEFAULT 0,
        result      TEXT    DEFAULT 'OPEN',
        profit_pct  REAL    DEFAULT 0.0,
        closed_at   TEXT
    )""")
    # Task 18: Rejection log — stores ICT setups that found a sweep but failed a later gate
    conn.execute("""CREATE TABLE IF NOT EXISTS rejections (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        token           TEXT    NOT NULL,
        direction       TEXT    NOT NULL,
        timestamp       TEXT    NOT NULL,
        failed_filter   TEXT,
        rejection_reason TEXT,
        sweep_type      TEXT,
        sweep_level     REAL,
        regime          TEXT,
        session         TEXT,
        hour_utc        INTEGER,
        day_of_week     INTEGER,
        bias_4h         TEXT,
        trend_1h        TEXT,
        dr_location     TEXT,
        mss_quality     TEXT,
        fvg_quality     TEXT,
        smt_confirmed   INTEGER,
        confidence      INTEGER,
        ev_score        REAL,
        ev_status       TEXT,
        metadata_json   TEXT
    )""")
    # Phase I-2: strategy template registry
    conn.execute("""CREATE TABLE IF NOT EXISTS templates (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        tier        TEXT NOT NULL,
        description TEXT,
        live_allowed INTEGER DEFAULT 1,
        created_at  TEXT
    )""")
    # Phase I-2: per-signal variant match detail
    conn.execute("""CREATE TABLE IF NOT EXISTS signal_variant_matches (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id              INTEGER REFERENCES signals(id),
        template_id            TEXT    REFERENCES templates(id),
        match_score            REAL,
        confluences_matched_json TEXT,
        is_best_match          INTEGER DEFAULT 0
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_svm_signal_id ON signal_variant_matches(signal_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_svm_template_id ON signal_variant_matches(template_id)")
    # Seed canonical templates (idempotent — INSERT OR IGNORE)
    seed_templates_table(conn)

    # Migrate: add regime columns to existing DB if missing
    existing = [r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()]
    for col, typ in [("market_regime","TEXT"),("regime_adx","REAL"),
                     ("regime_eff","REAL"),("regime_atr_r","REAL"),("regime_conf","INTEGER"),
                     ("btc_bias","TEXT"),("btc_dom_dir","TEXT"),
                     ("wscore_buy","REAL"),("wscore_sell","REAL"),
                     ("conflict_level","TEXT"),("candle_pattern","TEXT"),
                     ("expires_at","TEXT"),
                     ("feature_scores_json","TEXT"),
                     # Phase 4.2B: ICT 4H bias + IFVG
                     ("ict_bias_4h","TEXT"),
                     ("ifvg_present","INTEGER"),
                     ("ifvg_direction","TEXT"),
                     ("ifvg_top","REAL"),
                     ("ifvg_bottom","REAL"),
                     ("ifvg_age_bars","INTEGER"),
                     # Tasks 9-10: ICT bucket dimensions
                     ("sweep_type","TEXT"),
                     ("session","TEXT"),
                     ("dr_location","TEXT"),
                     ("mss_quality","TEXT"),
                     ("fvg_quality","TEXT"),
                     ("smt_type","TEXT"),
                     ("entry_type","TEXT"),
                     # Task 13: EV score
                     ("ev_score","REAL"),
                     ("ev_sample_n","INTEGER"),
                     ("ev_status","TEXT"),
                     # Task 12: session awareness
                     ("day_of_week","INTEGER"),   # 0=Mon … 6=Sun
                     ("hour_utc","INTEGER"),
                     ("dist_daily_open_pct","REAL"),
                     ("dist_weekly_open_pct","REAL"),
                     ("strategy_version","TEXT"),    # H5: EV scoring version isolation
                     # Phase I-2: strategy variant tagging
                     ("matched_template_id","TEXT"),
                     ("template_scores_json","TEXT"),
                     # Phase 5A: template safety status
                     ("template_status",       "TEXT"),
                     ("template_live_allowed", "INTEGER"),
                     ("template_block_reason", "TEXT"),
                     # CRT v1 Session 3 (audit cycle-7 2026-05-27): source tag
                     # parity with backtest. Default '5M_SWEEP' so all
                     # historical signals back-fill correctly. H4-CRT signals
                     # from crt_engine.detect_h4_crt carry source='H4_CRT'
                     # for independent per-source attribution. LBC-H-1 close.
                     ("source",                "TEXT DEFAULT '5M_SWEEP'"),
                     # Phase A — Slippage + Fillability tracking (2026-05-28)
                     # Operator chose Option 1 (limit orders at entry_price) as
                     # the live execution discipline. These columns measure:
                     #   actual_entry_price   — live market tick at save_signal time
                     #                          (vs `entry_price` which is the bot's
                     #                          theoretical entry from MSS-bar open)
                     #   slippage_pct         — (entry - actual_entry) / actual_entry * 100
                     #                          NEGATIVE = market filled WORSE than bot's ref
                     #   limit_fillable       — NULL=⏳WAITING, 1=✅FILLED, 0=❌MISSED
                     #                          1 = price retouched entry within window
                     #                          0 = window closed without retrace
                     #   fillable_check_at    — UTC timestamp when window evaluated
                     ("actual_entry_price",    "REAL"),
                     ("slippage_pct",          "REAL"),
                     ("limit_fillable",        "INTEGER"),
                     ("fillable_check_at",     "TEXT"),
                     # OTE overlay (2026-05-28) — Optimal Trade Entry tag.
                     # Tagging only, no gate. ote_zone ∈ {IN_OTE, BELOW_OTE,
                     # ABOVE_OTE, OTE_UNDEFINED}. ote_fib_pct = retracement
                     # percentage of entry within the C2-wick → MSS-extreme
                     # leg (0.0 = at wick, 1.0 = at MSS extreme).
                     ("ote_zone",              "TEXT"),
                     ("ote_fib_pct",           "REAL"),
                     # T1.2 — Funding rate overlay (2026-05-29) — captures
                     # the 8h-funding-rate at signal time and the classification
                     # vs signal direction. Tagging + optional confidence
                     # bonus controlled by FUNDING_BONUS_PCT env var.
                     # funding_rate_pct = float fraction × 100 (display-friendly).
                     # funding_classification ∈ {
                     #   EXTREME_COUNTER_LONG, EXTREME_COUNTER_SHORT,
                     #   EXTREME_AGAINST, NEUTRAL, DISABLED
                     # }
                     ("funding_rate_pct",      "REAL"),
                     ("funding_classification","TEXT"),
                     # T1.3 — BTC correlation overlay (2026-05-29) — rolling
                     # Pearson r between BTC and token log-returns over
                     # BTC_CORR_WINDOW_MIN 5M bars. Classification + optional
                     # confidence bonus via BTC_CORR_BONUS_PCT.
                     # btc_corr_strength ∈ [-1.0, +1.0] or NULL if insufficient data.
                     # btc_corr_classification ∈ {
                     #   ALIGNED_HIGH, ALIGNED_LOW, DIVERGENT, AMBIGUOUS,
                     #   UNKNOWN, DISABLED
                     # }
                     ("btc_corr_strength",      "REAL"),
                     ("btc_corr_classification","TEXT"),
                     # H-CY13-1 fix (audit cycle-13 2026-05-29): cycle-12
                     # promised bonus-attribution parity between live and
                     # backtest, but only the backtest_signals schema got
                     # the 3 columns. Live signals built the keys in the
                     # `result` dict at crypto_alert.py:1299-1301 but the
                     # migration + INSERT silently dropped them — so the
                     # tracker Reports tab + any explorer post-hoc analysis
                     # couldn't compute live bonus attribution. Now matched.
                     # confidence_base = pre-bonus confidence (0-10 integer)
                     # confidence_funding_bonus = funding overlay contribution
                     #   to the final confidence (rounded float, signed)
                     # confidence_btc_corr_bonus = BTC correlation overlay
                     #   contribution to the final confidence (rounded float,
                     #   signed)
                     ("confidence_base",            "INTEGER"),
                     ("confidence_funding_bonus",   "REAL"),
                     ("confidence_btc_corr_bonus",  "REAL")]:

        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {typ}")
                print(f"[DB] Added column: {col}")
            except sqlite3.OperationalError as e:
                print(f"[DB ERROR] Failed to add column {col}: {e}")
    # Migrate: add columns to results table if missing
    existing_r = [r[1] for r in conn.execute("PRAGMA table_info(results)").fetchall()]
    for col, typ in [("failure_reason",           "TEXT"),
                     ("exit_suggestion_sent_at",   "TEXT"),
                     ("exit_price",                "REAL"),
                     ("close_reason",              "TEXT"),
                     # Phase I-2: excursion + R tracking
                     ("mfe_pct",                   "REAL"),
                     ("mae_pct",                   "REAL"),
                     ("realized_r",                "REAL")]:
        if col not in existing_r:
            try:
                conn.execute(f"ALTER TABLE results ADD COLUMN {col} {typ}")
                print(f"[DB] Added column: results.{col}")
            except sqlite3.OperationalError as e:
                print(f"[DB ERROR] Failed to add column results.{col}: {e}")
    # Indexes for frequent lookup patterns
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_token_status ON signals(token, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_signal_id ON results(signal_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_expires_at ON signals(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_closed_at  ON results(closed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_status      ON signals(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_result      ON results(result)")
    conn.commit(); conn.close()
    print(f"[DB] Ready: {DB_PATH}")
    # Phase 5A: verify template tier hierarchy invariant (A ⊇ B ⊇ C) at startup
    _hier_violations = validate_tier_hierarchy()
    if _hier_violations:
        print(f"[PHASE5A] WARNING — {len(_hier_violations)} tier hierarchy violation(s):")
        for _v in _hier_violations:
            print(f"  {_v}")
    else:
        print("[PHASE5A] Tier hierarchy OK — A ⊇ B ⊇ C holds for all bot-realistic signals")

def _weighted_wr(rows, col=0) -> float:
    """Win rate with fractional PARTIAL credit.

    WIN=1.0, PARTIAL=0.5, LOSS/EXPIRED=0.0.
    PARTIAL is TP1-hit-but-not-closed — crediting it as a full win inflates WR
    and causes the threshold/floor adaptation to stay too loose.
    """
    if not rows:
        return 0.0
    score = sum(
        1.0 if r[col] == "WIN" else 0.5 if r[col] in ("PARTIAL", "PARTIAL_TP1", "PARTIAL_TP2") else 0.0
        for r in rows
    )
    return round(score / len(rows), 2)

def get_actual_win_rate():
    """Return actual win rate from last 50 closed signals. Falls back to 0.50."""
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT result FROM results "
            "WHERE result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED') "
            "ORDER BY id DESC LIMIT 50"
        ).fetchall()
        conn.close()
        if len(rows) < 5: return 0.50
        return _weighted_wr(rows)
    except:
        return 0.50

def restore_cooldowns():
    """Restore per-direction cooldown timestamps from DB after a restart.
    Each direction (BUY/SELL) is stored independently so restoring one
    cannot overwrite the other — fixes the single-slot overwrite bug."""
    try:
        conn = _connect()
        restored = 0
        for token in BINANCE_TOKENS:
            for direction in ("BUY", "SELL"):
                row = conn.execute(
                    "SELECT timestamp FROM signals "
                    "WHERE token=? AND signal=? ORDER BY timestamp DESC LIMIT 1",
                    (token, direction)).fetchone()
                if row:
                    t = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - t).total_seconds() < SIGNAL_COOLDOWN * 60:
                        STATE[token]["last_signal_times"][direction] = t
                        restored += 1
        conn.close()
        if restored:
            active = [(tok, d, STATE[tok]["last_signal_times"][d].strftime("%H:%M"))
                      for tok in BINANCE_TOKENS
                      for d in ("BUY", "SELL")
                      if STATE[tok]["last_signal_times"][d]]
            for tok, d, ts in active:
                print(f"  [COOLDOWN] {tok} {d} last sent {ts} — still in cooldown window")
            print(f"[DB] Cooldown restored: {restored} active direction(s)")
    except Exception as e:
        print(f"[DB] restore_cooldowns: {e}")

def load_performance_state():
    """Read per-token, per-regime, and per-confidence win rates from DB.
    Updates STATE[token]['recent_wr'], REGIME_WR, CONF_WR, and _conf_floor.
    Called at startup and every PERF_CHECK_INTERVAL seconds."""
    global _conf_floor, _signal_threshold_adj
    try:
        conn = _connect()

        # ── Per-token win rates ──────────────────────────────
        tok_updates = []
        for token in BINANCE_TOKENS:
            rows = conn.execute(
                """SELECT r.result FROM results r
                   JOIN signals s ON r.signal_id = s.id
                   WHERE s.token = ?
                   AND r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
                   ORDER BY r.id DESC LIMIT 30""",
                (token,)).fetchall()
            if len(rows) >= 5:
                STATE[token]["recent_wr"] = _weighted_wr(rows)
            tok_updates.append(f"{token}:{STATE[token]['recent_wr']:.0%}")
        print(f"[PERF] Token WR   — {' | '.join(tok_updates)}")

        # ── Per-regime win rates (Issue #12) ─────────────────
        reg_updates = []
        for regime_name in REGIME_RULES:
            rows = conn.execute(
                """SELECT r.result FROM results r
                   JOIN signals s ON r.signal_id = s.id
                   WHERE s.market_regime = ?
                   AND r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
                   ORDER BY r.id DESC LIMIT 50""",
                (regime_name,)).fetchall()
            if len(rows) >= 5:
                REGIME_WR[regime_name] = _weighted_wr(rows)
            if regime_name in REGIME_WR:
                label = regime_name.replace("TRENDING_", "T")
                reg_updates.append(f"{label}:{REGIME_WR[regime_name]:.0%}")
        if reg_updates:
            print(f"[PERF] Regime WR  — {' | '.join(reg_updates)}")

        # ── Per-confidence win rates → dynamic floor (Issue #11) ──
        all_rows = conn.execute(
            """SELECT s.confidence, r.result FROM results r
               JOIN signals s ON r.signal_id = s.id
               WHERE r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
               ORDER BY r.id DESC LIMIT 200""").fetchall()
        by_conf = {}
        for conf, res in all_rows:
            if conf is None: continue
            lvl = int(conf)
            if lvl not in by_conf: by_conf[lvl] = []
            by_conf[lvl].append(res)
        CONF_WR.clear()
        for lvl, results in by_conf.items():
            CONF_WR[lvl] = {"wr": _weighted_wr([(r,) for r in results]), "count": len(results)}
        # Floor = one above the highest losing level (WR < 40%, count >= 10)
        floor = 1
        for lvl in range(1, 8):
            d = CONF_WR.get(lvl, {})
            if d.get("count", 0) >= 10 and d.get("wr", 1.0) < 0.40:
                floor = lvl + 1
        floor = max(5, floor)  # confidence formula always yields >= 5; floor < 5 is a dead zone
        if floor != _conf_floor:
            print(f"[PERF] Conf floor — {_conf_floor} → {floor}"
                  + (f" (conf {floor-1} WR:{CONF_WR.get(floor-1,{}).get('wr',0):.0%} on "
                     f"{CONF_WR.get(floor-1,{}).get('count',0)} signals)" if floor > 1 else ""))
        _conf_floor = floor

        # ── Dynamic SIGNAL_THRESHOLD — regime-aware ───────────────
        # Evaluate only signals fired in regime-neutral conditions (RANGING / UNKNOWN).
        # Losses in HIGH_VOLATILITY or CHOPPY regimes are handled by the regime gate
        # and should not tighten the global threshold — doing so conflates regime risk
        # with signal quality and creates a self-defeating feedback loop.
        neutral_rows = conn.execute(
            """SELECT r.result FROM results r
               JOIN signals s ON r.signal_id = s.id
               WHERE s.market_regime IN ('RANGING', 'UNKNOWN')
               AND r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
               ORDER BY r.id DESC LIMIT 40""").fetchall()

        if len(neutral_rows) >= 15:
            neutral_wr = _weighted_wr(neutral_rows)
            # Narrower adjustment band (±7) prevents threshold from drifting so high
            # that no signals fire, which starves the feedback loop of new data.
            if neutral_wr > 0.72:   target_adj = -4
            elif neutral_wr > 0.62: target_adj = -2
            elif neutral_wr < 0.30: target_adj =  7
            elif neutral_wr < 0.40: target_adj =  4
            else:                   target_adj =  0
            if _signal_threshold_adj < target_adj:   _signal_threshold_adj += 1
            elif _signal_threshold_adj > target_adj: _signal_threshold_adj -= 1
            eff = SIGNAL_THRESHOLD + _signal_threshold_adj
            print(f"[PERF] Threshold  — regime-neutral WR:{neutral_wr:.0%} "
                  f"n={len(neutral_rows)} adj:{_signal_threshold_adj:+d} "
                  f"eff:{eff}% (target:{target_adj:+d})")
        else:
            # Insufficient regime-neutral history — hold current adjustment.
            # Common during early operation or when market has been trending for weeks.
            eff = SIGNAL_THRESHOLD + _signal_threshold_adj
            print(f"[PERF] Threshold  — regime-neutral data insufficient "
                  f"({len(neutral_rows)} sigs, need 15) "
                  f"— holding adj:{_signal_threshold_adj:+d} eff:{eff}%")

        # ── Top failure reasons ───────────────────────────────
        fail_rows = conn.execute(
            """SELECT failure_reason, COUNT(*) as cnt FROM results
               WHERE failure_reason IS NOT NULL
               AND result IN ('LOSS','EXPIRED')
               ORDER BY cnt DESC LIMIT 5""").fetchall()
        if fail_rows:
            parts = [f"{r[0]}:{r[1]}" for r in fail_rows if r[0]]
            if parts:
                print(f"[PERF] Fail tags  — {' | '.join(parts)}")

        conn.close()

        # ── Persist scalar state so it survives restarts (Phase 3) ──
        save_scalar_state("threshold_adj", _signal_threshold_adj)
        save_scalar_state("conf_floor",    _conf_floor)

        # ── P1-10: Post-apply WR verdict for tune_history rows ────────────
        # For each 'APPLIED' row with enough post-apply signals, set VERIFIED_BETTER/WORSE.
        # Uses a fresh connection since conn is already closed above.
        try:
            _th_conn = _connect()
            _th_rows = _th_conn.execute(
                "SELECT id, applied_at, test_wr FROM tune_history WHERE status='APPLIED'"
            ).fetchall()
            for _tid, _applied_at, _test_wr in _th_rows:
                _wins = _th_conn.execute(
                    """SELECT COUNT(*) FROM results r JOIN signals s ON s.id=r.signal_id
                       WHERE r.result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2')
                         AND s.timestamp > ?""", (_applied_at,)
                ).fetchone()[0] or 0
                _tot  = _th_conn.execute(
                    """SELECT COUNT(*) FROM results r JOIN signals s ON s.id=r.signal_id
                       WHERE r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
                         AND s.timestamp > ?""", (_applied_at,)
                ).fetchone()[0] or 0
                if _tot < 30:
                    continue
                _post_wr  = round(_wins / _tot * 100, 1)
                _baseline = _test_wr if _test_wr is not None else 45.0
                _verdict  = "VERIFIED_BETTER" if _post_wr >= _baseline else "VERIFIED_WORSE"
                _th_conn.execute(
                    """UPDATE tune_history
                       SET post_apply_wr=?, post_apply_n=?, status=?, notes=?
                       WHERE id=?""",
                    (_post_wr, _tot, _verdict,
                     f"Post-apply WR {_post_wr:.1f}% vs baseline {_baseline:.1f}% "
                     f"(n={_tot}) → {_verdict}", _tid)
                )
                _th_conn.commit()
                print(f"[PERF] tune_history#{_tid}: {_post_wr:.1f}% WR (n={_tot}) → {_verdict}")
                if _verdict == "VERIFIED_WORSE":
                    try:
                        send_telegram(
                            "<b>Tune Bot  -  VERIFIED_WORSE</b>\n\n"
                            "<pre>"
                            f"Tune #     {_h(_tid)}\n"
                            f"Post-WR    {_post_wr:.1f}%\n"
                            f"Baseline   {_baseline:.1f}%\n"
                            f"Sample n   {_h(_tot)} signals"
                            "</pre>\n"
                            "Post-apply WR is below baseline. Consider rolling back\n"
                            "via the Tune Bot dashboard."
                        )
                    except Exception:
                        pass
            _th_conn.close()
        except Exception as _pe:
            print(f"[PERF] tune_history post-apply check: {_pe}")

    except Exception as e:
        print(f"[PERF] load_performance_state: {e}")

def save_signal(token, price, result, plan, regime):
    if not plan: return -1
    try:
        conn = _connect()
        _now = datetime.now(timezone.utc)
        # Phase A (2026-05-28) — capture live market tick + compute slippage.
        # For CRT signals, `price` is the theoretical entry from a 5M bar that
        # closed 5-15 min before this call. The live current market may be
        # significantly different. Compare to STATE[token]'s freshest tick
        # (set by update_token_state each scan cycle).
        # Fallback: if STATE missing, slippage_pct=0 (treat `price` as the
        # live tick — preserves 5M_SWEEP-era behavior where `price` IS live).
        _live_tick = STATE.get(token, {}).get("last_24h", {}).get("price", price) or price
        try:
            _slippage_pct = round((price - _live_tick) / _live_tick * 100, 4) if _live_tick else 0.0
        except (TypeError, ZeroDivisionError):
            _slippage_pct = 0.0
        cur  = conn.execute("""INSERT INTO signals
            (token,signal,entry_price,sl,tp1,tp2,tp3,
             sl_pct,tp1_pct,tp2_pct,tp3_pct,rr1,rr2,rr3,
             confidence,mtf_bias,mtf_conf,rsi,
             trend_4h,trend_1h,trend_5m,confirms,
             atr,roc,vol_ratio,reasons,timestamp,
             market_regime,regime_adx,regime_eff,regime_atr_r,regime_conf,
             btc_bias,btc_dom_dir,wscore_buy,wscore_sell,
             conflict_level,candle_pattern,expires_at,feature_scores_json,
             sweep_type,session,dr_location,mss_quality,fvg_quality,
             smt_type,entry_type,ev_score,ev_sample_n,ev_status,
             day_of_week,hour_utc,dist_daily_open_pct,dist_weekly_open_pct,
             strategy_version,matched_template_id,template_scores_json,
             template_status,template_live_allowed,template_block_reason,
             source,
             actual_entry_price,slippage_pct,limit_fillable,fillable_check_at,
             ote_zone,ote_fib_pct,
             funding_rate_pct,funding_classification,
             btc_corr_strength,btc_corr_classification,
             confidence_base,confidence_funding_bonus,confidence_btc_corr_bonus)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (token,result["signal"],price,
             plan["sl"],plan["tp1"],plan["tp2"],plan["tp3"],
             plan["sl_pct"],plan["tp1_pct"],plan["tp2_pct"],plan["tp3_pct"],
             plan["rr1"],plan["rr2"],plan["rr3"],
             result["confidence"],result["mtf_bias"],result["mtf_conf"],
             result["rsi"],result["trend_4h"],result["trend_1h"],
             result["trend_5m"],result["confirms"],
             result["atr"],result["roc"],result["vol_ratio"],
             json.dumps(result["reasons"]),
             _now.strftime("%Y-%m-%d %H:%M:%S"),
             regime.get("regime","UNKNOWN"),
             regime.get("adx",0),regime.get("efficiency",0),
             regime.get("atr_ratio",0),regime.get("confidence",0),
             result.get("btc_trend_4h","NEUTRAL"),result.get("btc_dom_dir","NEUTRAL"),
             result.get("wscore_buy",0.0),result.get("wscore_sell",0.0),
             result.get("conflict_level","LOW"),result.get("candle_pattern","NONE"),
             # H-2 fix (audit cycle-8 2026-05-27) + M-NEW-9 fix (cycle-9
             # audit 2026-05-28): CRT signals need an expiry window matching
             # the backtest outcome window so trades that reach TP between
             # the old 12h default and the real window aren't logged as
             # EXPIRED (-0.25R) instead of WIN.
             # Pre-M-NEW-9: hardcoded 48h that drifted from CRT_FORWARD_BARS
             # the moment the explorer tuned the latter to 288 (24h) or
             # 864 (72h). Now derived from CRT_FORWARD_BARS (5min bars × 5 ÷ 60).
             # 5M_SWEEP path keeps its regime-aware expiry.
             (_now+timedelta(
                 hours=(
                     (CRT_FORWARD_BARS * 5 / 60.0) if (result.get("source") == "H4_CRT")
                     else EXPIRY_BY_REGIME.get(regime.get("regime","UNKNOWN"),12)
                 )
             )).strftime("%Y-%m-%d %H:%M:%S"),
             result.get("feature_scores_json", None),
             result.get("sr_type",""),
             result.get("session","UNKNOWN"),
             result.get("dr_4h",{}).get("location","UNKNOWN"),
             result.get("mss_result",{}).get("quality",""),
             result.get("ict_fvg",{}).get("quality",""),
             result.get("smt_result",{}).get("smt_type","NONE"),
             result.get("entry_type","ZONE_TOUCH"),
             result.get("ev_score",None),
             result.get("ev_sample_n",None),
             result.get("ev_status",None),
             _now.weekday(),
             _now.hour,
             result.get("dist_daily_open_pct", None),
             result.get("dist_weekly_open_pct", None),
             STRATEGY_VERSION,
             result.get("matched_template_id", "NONE"),
             result.get("template_scores_json", None),
             result.get("template_status", "UNKNOWN_TEMPLATE"),
             result.get("template_live_allowed", 0),
             result.get("template_block_reason", None),
             # CRT v1 Session 3 (audit cycle-7 2026-05-27): source tag. Default
             # '5M_SWEEP' for back-compat — pre-Session-3 callers don't set this
             # key and must still write the canonical signal source.
             result.get("source", "5M_SWEEP"),
             # Phase A (2026-05-28) — Slippage + Fillability tracking.
             # For CRT signals: `price` arg is the THEORETICAL entry (5M-bar
             # open from MSS confirmation), which can be 5-15 min stale vs
             # live market. _live_tick captures the actual current market
             # price at save_signal time, so slippage_pct exposes the gap
             # between bot's claimed entry and what would actually fill.
             # For 5M_SWEEP signals: `price` IS the live tick (passed by main
             # loop from current_prices), so slippage is naturally 0%.
             _live_tick,
             _slippage_pct,
             None,   # limit_fillable: NULL = ⏳ WAITING (set by monitor cycle)
             None,   # fillable_check_at: NULL until 30-min window evaluated
             # OTE overlay (2026-05-28) — tagging only, no gate.
             result.get("ote_zone", "OTE_UNDEFINED"),
             result.get("ote_fib_pct", None),
             # T1.2 — funding rate overlay (2026-05-29)
             result.get("funding_rate_pct", None),
             result.get("funding_classification", "NEUTRAL"),
             # T1.3 — BTC correlation overlay (2026-05-29)
             result.get("btc_corr_strength", None),
             result.get("btc_corr_classification", "UNKNOWN"),
             # H-CY13-1 fix (audit cycle-13 2026-05-29): write the 3
             # attribution columns matching backtest_signals so the
             # tracker Reports tab + explorer post-hoc analysis can
             # decompose confidence into base + funding bonus + BTC-
             # corr bonus. The live `result` dict has built these keys
             # since the cycle-12 wave; only the persistence layer was
             # half-shipped.
             result.get("confidence_base", result.get("confidence", 0)),
             result.get("confidence_funding_bonus", 0.0),
             result.get("confidence_btc_corr_bonus", 0.0)))
        sig_id   = cur.lastrowid
        exp_h    = EXPIRY_BY_REGIME.get(regime.get("regime","UNKNOWN"), 12)
        conn.execute("INSERT INTO results (signal_id) VALUES (?)", (sig_id,))
        # Phase I-2: persist per-template match detail.
        # CY12-SVM-DICT-OR-OBJ fix (full audit 2026-05-29 OGD HIGH-1 + adaptive
        # M2): pre-fix the loop accessed `_tm.template_id` directly, which
        # works for 5M_SWEEP path (TemplateMatch dataclass objects) but
        # raised AttributeError for CRT path (which stores list-of-DICTS
        # at crypto_alert.py:1366 with keys "id"/"score"/"matched").
        # The exception was caught by the outer try/except, signal_variant_matches
        # stayed empty for 100% of CRT signals → Phase 5B per-template OGD
        # had zero learning substrate despite 5 closed CRT signals. Helper
        # below duck-types both shapes so the table is populated for BOTH
        # scanner paths.
        _best_tmpl_id = result.get("matched_template_id", "NONE")
        def _svm_extract(tm):
            """Return (template_id, score, confluences_matched, is_match)
            tuple regardless of whether tm is a TemplateMatch dataclass
            (5M_SWEEP) or a dict (CRT path)."""
            if isinstance(tm, dict):
                # CRT shape — keys: "id", "score", "matched"
                return (tm.get("id", "NONE"),
                        float(tm.get("score", 0.0)),
                        tm.get("confluences_matched", {}),
                        bool(tm.get("matched", False)))
            # TemplateMatch dataclass — attribute access
            return (getattr(tm, "template_id", "NONE"),
                    float(getattr(tm, "score", 0.0)),
                    getattr(tm, "confluences_matched", {}),
                    bool(getattr(tm, "is_match", False)))
        for _tm in result.get("template_matches", []):
            _tm_id, _tm_score, _tm_conf, _tm_match = _svm_extract(_tm)
            conn.execute(
                """INSERT INTO signal_variant_matches
                   (signal_id, template_id, match_score,
                    confluences_matched_json, is_best_match)
                   VALUES (?, ?, ?, ?, ?)""",
                (sig_id, _tm_id, _tm_score,
                 json.dumps(_tm_conf),
                 1 if _tm_id == _best_tmpl_id and _tm_match else 0))
        conn.commit(); conn.close()
        print(f"[DB] Saved ID:{sig_id} {token} {result['signal']} "
              f"[{regime.get('regime','?')}] expires {exp_h}H")
        return sig_id
    except Exception as e:
        print(f"[DB ERROR] save: {e}"); return -1


# ══════════════════════════════════════════════════════════
# CRT v1 — LIVE H4 SCANNER (Session 3, audit cycle-7 2026-05-27)
# ══════════════════════════════════════════════════════════
#
# Parallel to generate_signal() — uses the SAME c5m/c4h candle cache the
# main loop already maintains, the SAME shared helpers from crt_engine.py
# that backtest.py uses, and the SAME signal-write/Telegram pipeline.
# Live/backtest parity by construction (LBC-H-3 close).
#
# Default-OFF: returns None immediately when ENABLE_H4_CRT=0 (the canonical
# deployment state). Operator enables via ENABLE_H4_CRT=1 in env.
#
# H6 isolation: live OGD weights are NOT applied to CRT signals in this v1
# (CRT signals carry their own confidence via crt_quality_to_confidence).
# This matches the backtest's H6 isolation discipline.

def scan_h4_crt_for_token(token, c5m, c4h, consumed, trend_1h="NEUTRAL",
                           btc_c5m=None):
    """Detect H4 CRT setup + build live signal result dict for the existing
    save_signal / send_signal_msg pipeline. Mirrors backtest.py's
    run_backtest_token_h4_crt economics + signal-dict construction.

    Args:
        token: token symbol (uppercase)
        c5m, c4h: candle dicts (opens, highs, lows, closes, times in ms)
        consumed: per-token mitigation set (mutated on signal emit)
        trend_1h: optional 1H trend label (NEUTRAL / BULL / BEAR / STRONG_*)
        btc_c5m: optional BTC 5M candle dict for SMT divergence detection.
            When None (or missing highs/lows), SMT defaults to "NONE/False"
            with reason "no BTC reference" — same fallback as 5M_SWEEP path.
            Added 2026-05-28 to close ict-logic-validator finding F-1 (SMT
            was permanently dormant in CRT — hardcoded stub).

    Returns:
        (result, plan, rej_reason) tuple. `result` and `plan` are non-None
        on successful CRT setup; `rej_reason` is a string from the gate
        that fired ("default_off", "blacklisted", "no_setup",
        "outside_killzone", "bias_gate_blocked", "economics_*"). Caller
        treats result=None as "skip this scan cycle for CRT."
    """
    if not ENABLE_H4_CRT:
        return None, None, "default_off"
    if token.upper() in H4_CRT_DISABLED_TOKENS:
        return None, None, "blacklisted"

    # Mitigation TTL — re-eligible zones whose C1 is older than the configured
    # TTL. Default 0 = no-op (Run-1749 baseline preserved). Live uses wall-
    # clock time; backtest path passes its current-bar time for parity.
    if H4_CRT_MITIGATION_TTL_H > 0 and consumed:
        try:
            _now_ms_live = time.time() * 1000.0
            _pruned = prune_consumed_zones(consumed, _now_ms_live,
                                            H4_CRT_MITIGATION_TTL_H)
            if _pruned:
                print(f"[CRT-TTL] {token}: pruned {_pruned} consumed zones "
                      f"older than {H4_CRT_MITIGATION_TTL_H}h")
        except Exception:
            pass

    # Detection — uses shared module, identical to backtest path
    setup = detect_h4_crt(c4h, c5m, token=token, consumed=consumed)
    if setup is None:
        return None, None, "no_setup"

    # ── Entry timing ──────────────────────────────────────────────────────
    # Entry = next 5M bar's open after MSS. In LIVE, that bar may not have
    # closed yet — use the LATEST close as the entry price (the operator
    # places the trade at the price the alert is sent at).
    mss_bar_5m = setup["mss_bar_5m"]
    n5 = len(c5m["closes"])
    if mss_bar_5m + 1 >= n5:
        return None, None, "no_post_mss_bar"  # MSS at very last bar — wait next cycle
    entry_bar = mss_bar_5m + 1
    entry_price = c5m["opens"][entry_bar]
    direction = setup["direction"]
    ts = datetime.utcfromtimestamp(c5m["times"][entry_bar] / 1000)

    # ── Killzone filter (parity with backtest H-CRT2-3) ───────────────────
    # LIVE_CONFIG.liquid_hours is the shared set — both live (here) and
    # backtest path apply the same filter at the same place in the pipeline.
    # CRITICAL-1 fix (config audit 2026-05-27): the previous import
    # `from config import LIVE_LIQUID_HOURS` referenced a symbol that
    # does NOT exist in config.py — would have ImportError'd the first
    # time a CRT setup was detected, then crash-looped the bot. Replaced
    # with the canonical pattern used elsewhere in crypto_alert.py:2069.
    _liquid_hours = LIVE_CONFIG.liquid_hours
    if _liquid_hours and ts.hour not in _liquid_hours:
        return None, None, "outside_killzone"

    # ── 4H bias gate (parity with backtest H-CRT2-4) ──────────────────────
    # MEDIUM-1 fix (config audit 2026-05-27): slice to the last 210 bars
    # before calling get_ict_4h_bias, matching backtest._lookup_4h_bias
    # exactly. Previously the live path passed the full c4h cache (which
    # can grow beyond 210 bars under the live fetcher's rolling window),
    # producing a slightly different EMA50/200 result than the backtest's
    # 210-bar slice — a silent live↔BT divergence on CRT setups.
    _closes_full = c4h.get("closes", [])
    if len(_closes_full) >= 200:
        _N = min(len(_closes_full), 210)  # mirror _lookup_4h_bias slice size
        bias_4h = get_ict_4h_bias(
            _closes_full[-_N:],
            c4h["highs"][-_N:],
            c4h["lows"][-_N:],
        )
    else:
        bias_4h = "NEUTRAL"
    # MEDIUM-3 fix (config audit 2026-05-27): the stale comment claimed
    # the backtest default for bias_4h_gate was 'loose' — actual default
    # is 'none' (config.py:317). Comment removed to avoid future confusion.
    from config import LIVE_BIAS_4H_GATE as _bias_gate
    _want = "BULLISH" if direction == "BUY" else "BEARISH"
    if _bias_gate == "strict" and bias_4h != _want:
        consumed.add(setup["key"])  # mark zone consumed — bias gate is structural
        return None, None, "bias_gate_blocked"
    if _bias_gate == "loose" and bias_4h not in ("NEUTRAL", _want):
        consumed.add(setup["key"])
        return None, None, "bias_gate_blocked"

    # ── CRT Pro v1.1 — optional 1H trend gate (2026-05-27) ────────────────
    # When CRT_REQUIRE_1H_TREND=1, mirror 5M_SWEEP's trend_1h_gate logic.
    # Default NEUTRAL when caller omits trend → gate is a no-op (NEUTRAL
    # passes both directions). Mirrors backtest behavior at backtest.py
    # for parity.
    if CRT_REQUIRE_1H_TREND:
        _bull_ok = trend_1h in ("BULL", "STRONG_BULL", "NEUTRAL")
        _bear_ok = trend_1h in ("BEAR", "STRONG_BEAR", "NEUTRAL")
        if (direction == "BUY" and not _bull_ok) or (direction == "SELL" and not _bear_ok):
            consumed.add(setup["key"])
            return None, None, "1h_trend_blocked"

    # ── v2 Wyckoff phase filter (Option KK, audit cycle-7 2026-05-27) ─────
    # Same logic as backtest path — phase context computed unconditionally
    # (for entry_type tagging), phase-aligned check enforced only when the
    # WYCKOFF_PHASE_FILTER env knob is "loose" or "strict".
    wyckoff_context = detect_wyckoff_context(c4h)
    if WYCKOFF_PHASE_FILTER != "off":
        if not is_crt_phase_aligned(wyckoff_context, direction):
            consumed.add(setup["key"])  # mark zone consumed — phase gate is structural
            return None, None, f"wyckoff_{wyckoff_context.lower()}"

    # ── Trade plan: SL = sweep wick ± buffer, TP1 = (per CRT_TP1_MODE), TP2/3 = RR cascade ──
    # Parity with backtest H-CRT2-1 (SL buffer) and CRT_TP2_RR/CRT_TP3_RR ladder.
    raw_wick = setup["sl"]
    if direction == "BUY":
        sl_price = raw_wick * (1.0 - ICT_SL_BUFFER_PCT)
        # F-4 fix (ict-logic-validator audit 2026-05-28): WIDEN too-tight SL
        # to MIN_SL_PCT floor — mirrors compute_ict_trade_plan at
        # ict_engine.py:768. Pre-F-4 the economics gate REJECTED setups
        # with sub-floor SL while the 5M_SWEEP path admitted the same setup
        # with a widened SL. H-NEW-3 commit comment claimed "Mirrors
        # 5M_SWEEP" — that's now actually true.
        sl_price = min(sl_price, entry_price * (1.0 - MIN_SL_PCT))
    else:
        sl_price = raw_wick * (1.0 + ICT_SL_BUFFER_PCT)
        sl_price = max(sl_price, entry_price * (1.0 + MIN_SL_PCT))
    # CRT Pro TP1 override (2026-05-27): apply CRT_TP1_MODE policy.
    # mode=dynamic (default) preserves the original C1 opposite logic; this
    # call is a no-op then. fixed_1r and min_1r let us empirically test
    # whether uncapping TP1 above the C1 opposite improves avg_R.
    tp1_price = adjust_crt_tp1(
        direction=direction,
        entry_price=entry_price,
        sl_price=sl_price,
        c1_high=setup["c1_high"],
        c1_low=setup["c1_low"],
    )
    risk_dist = abs(entry_price - sl_price)
    if risk_dist <= 0:
        return None, None, "zero_risk_dist"
    if direction == "BUY":
        tp2_price = entry_price + CRT_TP2_RR * risk_dist
        tp3_price = entry_price + CRT_TP3_RR * risk_dist
    else:
        tp2_price = entry_price - CRT_TP2_RR * risk_dist
        tp3_price = entry_price - CRT_TP3_RR * risk_dist

    # ── Economics (shared helper from crt_engine) ─────────────────────────
    rt_cost = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
    econ = compute_crt_trade_economics(
        direction, entry_price, sl_price, tp1_price, tp2_price, tp3_price,
        outcome=None,  # outcome unknown live — realized_r stays None
        rt_cost_pct=rt_cost,
    )
    if econ is None:
        _reason = crt_trade_rejection_reason(
            direction, entry_price, sl_price, tp1_price, rt_cost,
        )
        consumed.add(setup["key"])  # mark zone consumed — gate is structural
        return None, None, f"economics_{_reason}"

    # ── Build the live result dict (save_signal contract) ─────────────────
    # CRT-specific fields use sensible defaults; the 5M-sweep-specific
    # fields default to NEUTRAL/0/NONE so downstream queries don't break.
    _mss_q = setup.get("mss_quality", "NONE")
    _fvg_q = (setup["confluence"]["details"].get("quality", "NONE")
              if setup["confluence"]["type"] == "FVG" else "NONE")
    confidence = crt_quality_to_confidence(_mss_q, _fvg_q)

    # CRT OGD feature scoring (2026-05-27 — closes the adaptive-learning gap).
    # Without these scores, _trigger_weight_update() bails out at "no
    # feature_scores_json stored" and the per-token OGD weights freeze when
    # ENABLE_5M_SWEEP=0. With them, every CRT trade close feeds the same
    # 6-feature gradient pipeline the 5M_SWEEP path uses. Imported lazily
    # from crt_engine to avoid a top-of-file circular import.
    from crt_engine import compute_crt_feature_scores
    from adaptive_engine import _utc_to_session
    _crt_session = _utc_to_session(ts.hour)

    # ── OTE overlay (2026-05-28) — Optimal Trade Entry tag ───────────────
    # Impulse leg: C2 wick (sweep extreme) → MSS-bar extreme on 5M.
    # For BUY  (SSL_CRT): wick=C2 low, MSS extreme = highest 5M high in
    #          [sweep_5m_idx, mss_bar_5m] inclusive.
    # For SELL (BSL_CRT): wick=C2 high, MSS extreme = lowest 5M low in
    #          same window. Tagging only, no gate effect.
    try:
        _sweep_5m_idx = setup["sweep_5m_idx"]
        _mss_bar_5m   = setup["mss_bar_5m"]
        if direction == "BUY":
            _mss_extreme = max(c5m["highs"][_sweep_5m_idx:_mss_bar_5m + 1])
        else:
            _mss_extreme = min(c5m["lows"][_sweep_5m_idx:_mss_bar_5m + 1])
        _ote = compute_ote_overlay(
            direction=direction,
            sweep_wick=setup["sweep_wick"],
            mss_extreme=_mss_extreme,
            entry_price=entry_price,
        )
    except Exception:
        _ote = {"ote_zone": "OTE_UNDEFINED", "ote_fib_pct": None}

    # ── T1.2 Funding rate overlay (2026-05-29) ──────────────────────────
    # Tag every CRT signal with the live 8h-funding rate + classification.
    # Per ENHANCEMENT_ROADMAP.md T1.2: metadata + optional confidence bonus,
    # NOT a direct OGD feature (preserves existing trained weights).
    # Fetch is cached 5 min so this is cheap per scan cycle.
    try:
        _funding_rate = get_funding_rate(token)
        # Pass the fetch_failed flag so classify can return FETCH_FAILED instead
        # of NEUTRAL when the underlying API errored (LOW finding from T1.2 review).
        _funding_failed = is_funding_fetch_failed(token)
        _funding_cls  = classify_funding_extreme(
            _funding_rate, direction, fetch_failed=_funding_failed,
        )
        _funding_bonus = funding_confidence_bonus(_funding_rate, direction)
    except Exception as _fund_e:
        _funding_rate = 0.0
        _funding_cls  = "FETCH_FAILED"
        _funding_bonus = 0.0
        print(f"[FUNDING] {token} fetch error (continuing without overlay): {_fund_e}")

    # ── T1.3 BTC correlation overlay (2026-05-29) ───────────────────────
    # Compute rolling Pearson r between BTC and token 5M log-returns over
    # the last BTC_CORR_WINDOW_MIN bars. Identical computation in live +
    # backtest = perfect parity (no historical-data lookup divergence).
    # Skipped when token == BTC (self-correlation is meaningless).
    _btc_corr = None
    _btc_corr_cls = "UNKNOWN"
    _btc_corr_bonus = 0.0
    try:
        if (token.upper() != "BTC" and btc_c5m
                and btc_c5m.get("closes") and btc_c5m.get("times")):
            _tok_closes = c5m.get("closes", [])
            _tok_times  = c5m.get("times", [])
            _btc_closes = btc_c5m.get("closes", [])
            _btc_times  = btc_c5m.get("times", [])
            # HIGH-CY13-1 fix (audit cycle-13 2026-05-29): pre-fix this
            # function applied `[:-1]` to BOTH sides — but the caller at
            # crypto_alert.py:4595 passes `_c5m_closed` (the output of
            # `_crt_closed_only`) which has ALREADY had the forming bar
            # stripped. Double-slicing the token series therefore lost the
            # latest CLOSED bar, leaving the token series exactly 1 bar
            # shorter than the BTC series. With `BTC_CORR_BONUS_PCT=0.0`
            # default this produced no signal corruption, but the
            # ALIGNED_HIGH / DIVERGENT classification used a misaligned
            # window — explorer Pareto promotions involving non-zero
            # bonus values would have been INVALID. Now the token side
            # is left untouched (c5m is already closed-only) while BTC
            # side keeps its single strip (btc_c5m is raw / forming-bar-
            # included; see CY12-BTC-CORR-KEY at crypto_alert.py:4740).
            _tok_closed = _tok_closes
            _btc_closed = _btc_closes[:-1] if len(_btc_closes) > 1 else _btc_closes
            # Defensive timestamp alignment (LOW review item, 2026-05-29).
            # Live's normal case has both series ending at the same wall-clock
            # tick — trailing-window in compute_btc_correlation handles
            # length differences correctly because both arrays end at "now."
            # But if BTC's last 5M close ts != token's last 5M close ts
            # (e.g., one series got a stale-fetch fallback), the trailing
            # window would correlate misaligned timestamps. Truncate both
            # series at the MIN of their last-closed-bar timestamps.
            if _tok_times and _btc_times and len(_tok_closed) > 1 and len(_btc_closed) > 1:
                _tok_end_ts = _tok_times[len(_tok_closed) - 1]
                _btc_end_ts = _btc_times[len(_btc_closed) - 1]
                if _tok_end_ts != _btc_end_ts:
                    import bisect as _bisect
                    _common_end_ts = min(_tok_end_ts, _btc_end_ts)
                    # Truncate each series to last index whose ts <= common end
                    _tok_idx = _bisect.bisect_right(_tok_times[:len(_tok_closed)], _common_end_ts) - 1
                    _btc_idx = _bisect.bisect_right(_btc_times[:len(_btc_closed)], _common_end_ts) - 1
                    if _tok_idx >= 0 and _btc_idx >= 0:
                        _tok_closed = _tok_closed[:_tok_idx + 1]
                        _btc_closed = _btc_closed[:_btc_idx + 1]
            _btc_corr = compute_btc_correlation(
                _btc_closed, _tok_closed, window=_BTC_CORR_WIN,
            )
            _btc_corr_cls = classify_btc_corr(_btc_corr, direction, bias_4h)
            _btc_corr_bonus = btc_corr_confidence_bonus(
                _btc_corr, direction, bias_4h,
            )
    except Exception as _bc_e:
        _btc_corr = None
        _btc_corr_cls = "UNKNOWN"
        _btc_corr_bonus = 0.0
        print(f"[BTC-CORR] {token} compute error (continuing without overlay): {_bc_e}")

    # ── F-1 fix (ict-logic-validator audit 2026-05-28): SMT divergence ──
    # Pre-fix the CRT path hardcoded smt_result = {NONE, False} → the
    # +0.10 SMT bonus in tier scoring was permanently dead code (95/95
    # signals in Run #146 had smt_confirmed=0). Now compute real SMT
    # from BTC 5M reference. setup["type"] is "SSL_CRT" or "BSL_CRT" —
    # strip the suffix for detect_smt_divergence's "SSL"/"BSL" contract.
    _sweep_for_smt = setup["type"].replace("_CRT", "")
    _smt_result = {"smt_confirmed": False, "smt_type": "NONE",
                   "reason": "no BTC reference"}
    if btc_c5m and btc_c5m.get("highs") and btc_c5m.get("lows"):
        _btc_h5 = btc_c5m["highs"][:-1]  # exclude forming bar
        _btc_l5 = btc_c5m["lows"][:-1]
        _Nbtc = min(len(_btc_h5), ICT_SMT_LOOKBACK + ICT_SMT_REF_HORIZON)
        if _Nbtc >= ICT_SMT_LOOKBACK + 2:
            _smt_result = detect_smt_divergence(
                _sweep_for_smt,
                ref_h=_btc_h5[-_Nbtc:], ref_l=_btc_l5[-_Nbtc:],
                lookback=ICT_SMT_LOOKBACK, reference_horizon=ICT_SMT_REF_HORIZON,
            )
        else:
            _smt_result = {"smt_confirmed": False, "smt_type": "NONE",
                           "reason": "insufficient BTC data"}

    # ── ict-logic-validator F-2 / dr_location wiring (2026-05-28) ──
    # Pre-fix dr_4h was hardcoded {location: UNKNOWN}. CRT path already
    # has full c4h cache; computing DR location is informational (no
    # gate) and gives the OGD adaptive engine a 6th real feature back
    # (was dead in CRT-only mode).
    _dr_4h_full = {"location": "UNKNOWN", "midpoint": 0.0}
    try:
        _c4h_highs = c4h.get("highs", [])
        _c4h_lows  = c4h.get("lows",  [])
        if _c4h_highs and _c4h_lows and entry_price > 0:
            _dr_4h_full = compute_dealing_range(_c4h_highs, _c4h_lows, entry_price)
    except Exception as _dr_exc:
        print(f"[CRT-DR] {token}: compute_dealing_range failed — {_dr_exc}")

    _crt_ogd_scores = compute_crt_feature_scores(
        direction=direction,
        mss_quality=_mss_q,
        fvg_quality=_fvg_q,
        confidence=confidence,
        session=_crt_session,
        trend_1h=trend_1h,
        dr_location=_dr_4h_full.get("location", "UNKNOWN"),
    )

    plan = {
        "sl":          round(sl_price, 8),
        "tp1":         round(tp1_price, 8),
        "tp2":         round(tp2_price, 8),
        "tp3":         round(tp3_price, 8),
        "sl_pct":      round(econ["gross_sl"], 2),
        "tp1_pct":     round(econ["gross_tp1"], 2),
        "tp2_pct":     round(econ["gross_tp2"], 2),
        "tp3_pct":     round(econ["gross_tp3"], 2),
        "rr1":         econ["rr1"],
        "rr2":         round(CRT_TP2_RR, 1),
        "rr3":         round(CRT_TP3_RR, 1),
        # CRITICAL B-0 fix (telegram audit 2026-05-27): the Telegram renderer
        # at crypto_alert.py:3192-3194 reads plan['net_tp1_pct'],
        # plan['breakeven_wr'], plan['net_rr1'] directly (NOT via .get) — would
        # KeyError on every CRT signal, falling into the outer cycle handler
        # which sends "Bot ERROR" to operator instead of the signal alert.
        # After 15 such errors, bot self-stops. Propagating econ -> plan now.
        "net_tp1_pct": round(econ["net_tp1"], 2),
        "net_rr1":     econ["net_rr1"],
        "breakeven_wr": econ["breakeven_wr"],
    }
    result = {
        "signal":           direction,
        # Live integration needs the entry price separately from the plan
        # for save_signal's `price` positional arg + Telegram alert formatting
        "entry_price":      round(entry_price, 8),
        # T1.2 + T1.3 confidence overlays applied to base. Clamped to [0, 10].
        # Bonus magnitudes controlled by FUNDING_BONUS_PCT (default 0.05 → 0.5
        # point swing) and BTC_CORR_BONUS_PCT (default 0.0 → disabled, explorer
        # tunes via tier feedback). Both stored separately for attribution.
        "confidence":       max(0, min(10, int(round(
                                confidence + 10 * (_funding_bonus + _btc_corr_bonus))))),
        "confidence_base":  confidence,  # pre-bonus, for attribution
        "confidence_funding_bonus":  round(10 * _funding_bonus, 2),
        "confidence_btc_corr_bonus": round(10 * _btc_corr_bonus, 2),
        "mtf_bias":         bias_4h,
        "mtf_conf":         0,
        "rsi":              50.0,
        "trend_4h":         bias_4h,
        "trend_1h":         trend_1h,   # use real 1H trend passed by caller (was stub NEUTRAL)
        "trend_5m":         "NEUTRAL",
        # HIGH B-1 fix (telegram audit 2026-05-27): the renderer at
        # crypto_alert.py:3102-3103 reads `ict_trend_1h` / `ict_bias_4h`
        # (5M_SWEEP-era key names). Without these, CRT alerts always
        # showed "4H NEUTRAL / 1H NEUTRAL" even when the bias gate
        # explicitly required BULLISH/BEARISH alignment — confusing the
        # operator. Mirror the canonical key shape.
        "ict_trend_1h":     trend_1h,
        "ict_bias_4h":      bias_4h,
        "confirms":         0,
        "atr":              0.0,
        "roc":              0.0,
        "vol_ratio":        1.0,
        "reasons":          [f"H4_CRT_{setup['confluence']['type']}",
                             f"MSS={_mss_q}", f"FVG={_fvg_q}",
                             f"bias_4h={bias_4h}",
                             f"wyckoff={wyckoff_context}"],
        "plan":             plan,
        # CRT OGD feature score vector — populated 2026-05-27 to enable
        # adaptive learning on CRT signal closes. _trigger_weight_update()
        # reads this JSON and passes it to weight_engine.update().
        "feature_scores_json": json.dumps(_crt_ogd_scores),
        # CRT-specific fields surfaced via existing schema.
        # 2026-05-28: append EQH/EQL cluster tag when C1's swept extreme was
        # part of a >=2-swing cluster (canonical ICT strong liquidity pool).
        # Tagging only — no gate effect. Schema query path
        # `sweep_type LIKE '%EQ%'` now lights up for clustered CRT setups.
        "sr_type":          setup["type"] + (
            f"_{setup.get('c1_cluster_type')}"
            if (setup.get("c1_cluster_size") or 1) >= 2 else ""
        ),
        "c1_cluster_size":  setup.get("c1_cluster_size", 1),
        # OTE overlay (2026-05-28) — tag only, no gate.
        "ote_zone":         _ote.get("ote_zone", "OTE_UNDEFINED"),
        "ote_fib_pct":      _ote.get("ote_fib_pct"),
        # T1.2 — Funding rate overlay (2026-05-29). funding_rate_pct stored
        # as float fraction × 100 for human readability (0.01 = 0.01%/8h).
        "funding_rate_pct":  round(_funding_rate * 100, 4),
        "funding_classification": _funding_cls,
        "_funding_bonus":   _funding_bonus,  # consumed below if confidence is set
        # T1.3 — BTC correlation overlay (2026-05-29).
        # btc_corr_strength stored as Pearson r ∈ [-1, +1], or None when
        # token is BTC itself or insufficient data (<window+1 bars).
        "btc_corr_strength":      (round(_btc_corr, 4) if _btc_corr is not None else None),
        "btc_corr_classification": _btc_corr_cls,
        "_btc_corr_bonus":        _btc_corr_bonus,
        "session":          _crt_session,      # was UNKNOWN — now proper KZ label
        # F-2 / DR wiring (2026-05-28): real 4H DR location replaces
        # the hardcoded UNKNOWN stub. Informational, no gate.
        "dr_4h":            _dr_4h_full,
        "mss_result":       {"quality": _mss_q},
        "ict_fvg":          {"quality": _fvg_q},
        # F-1 fix (2026-05-28): real SMT divergence replaces the dead stub.
        # Enables the +0.10 SMT bonus in tier scoring + dashboard SMT column.
        "smt_result":       _smt_result,
        # Encode Wyckoff context into entry_type — parity with backtest path
        "entry_type":       f"H4_CRT_{setup['confluence']['type']}_{wyckoff_context}",
        "ev_score":         None,
        "ev_sample_n":      None,
        "ev_status":        "OBSERVE",
        # Template tagging — Phase B (2026-05-28) replaces the pre-existing
        # "always NONE" stub with real CRT tier classification. Live behavior
        # is still gated by EXECUTION_MODE — flipping to LIVE will Telegram
        # only Tier A / Tier B CRT signals; Tier C is paper-only.
        # Set below from evaluate_crt_templates() result.
        # KEY tag for per-source attribution (LBC-H-1 parity)
        "source":           "H4_CRT",
    }

    # ── Phase B (2026-05-28): classify CRT signal into Tier A/B/C ─────────
    _crt_tmpl_features = {
        "direction":       direction,
        "confluence_type": setup['confluence']['type'],   # "FVG" | "OB"
        "mss_quality":     _mss_q,
        "wyckoff_phase":   wyckoff_context,
        "bias_4h":         bias_4h,
        "session":         _crt_session,
    }
    _crt_matches = evaluate_crt_templates(_crt_tmpl_features)
    _crt_best    = next((m for m in _crt_matches if m.is_match), None)
    if _crt_best:
        result["matched_template_id"]  = _crt_best.template_id
        result["template_status"]      = "PROVISIONAL"  # Phase B = no historical WR yet
        result["template_live_allowed"] = 1 if _crt_best.live_allowed else 0
        result["template_block_reason"] = "" if _crt_best.live_allowed else "crt_tier_c_paper_only"
        result["template_matches"]     = [
            {"id": m.template_id, "score": m.score, "matched": m.is_match}
            for m in _crt_matches
        ]
        result["template_scores_json"] = json.dumps(
            {m.template_id: round(m.score, 4) for m in _crt_matches}
        )
    else:
        # No tier matched — keep legacy "NONE" defaults so the renderer
        # behaves identically to pre-Phase-B for unclassifiable setups.
        result["matched_template_id"]  = "NONE"
        result["template_status"]      = "UNKNOWN_TEMPLATE"
        result["template_live_allowed"] = 0
        result["template_block_reason"] = "crt_no_tier_match"
        result["template_matches"]     = []
    # RISK-GAP-NEW-2 fix (cycle-10 audit 2026-05-28): attach position-sizing
    # recommendation to the CRT result dict — was empty pre-fix, causing
    # the dashboard to show $0 notional for CRT signals and leaving the
    # operator without a system-recommended size at LIVE flip time. Mirrors
    # the 5M_SWEEP call at line 3013 exactly.
    try:
        _sl_pct_abs_crt = abs(entry_price - sl_price) / entry_price
        result["sizing"] = compute_position_size(
            YOUR_CAPITAL, RISK_PER_TRADE_PCT, _sl_pct_abs_crt, token=token,
        )
    except Exception as _sz_exc:
        print(f"[CRT-SIZING] {token}: compute_position_size failed — {_sz_exc}")
        result["sizing"] = {}
    # Mark mitigated AFTER constructing result so a downstream failure
    # doesn't leave a half-consumed zone. Caller commits via consumed.add().
    consumed.add(setup["key"])
    return result, plan, "ok"


# ══════════════════════════════════════════════════════════
# PHASE 5A — TEMPLATE SAFETY CONTROLS
# ══════════════════════════════════════════════════════════

# Phase B (2026-05-28): widened to include CRT-specific tier IDs from
# strategy_templates.CRT_TEMPLATE_IDS so Phase 5A validation accepts them.
_KNOWN_TEMPLATES = {"TIER_A", "TIER_B", "TIER_C", "NONE"} | CRT_TEMPLATE_IDS

def _tmpl_closed_count(conn, template_id: str) -> int:
    """Count all closed results for signals matched to this template."""
    row = conn.execute("""
        SELECT COUNT(*) FROM results r
        JOIN signals s ON r.signal_id = s.id
        WHERE s.matched_template_id = ?
          AND r.result IN ('WIN', 'PARTIAL', 'PARTIAL_TP1', 'PARTIAL_TP2', 'LOSS', 'EXPIRED')
    """, (template_id,)).fetchone()
    return row[0] if row else 0


def _tmpl_rolling_wr(conn, template_id: str, lookback: int) -> float:
    """Weighted WR over the last `lookback` closed results for this template.
    Returns 1.0 (pass) when no data exists to avoid false-triggering the breaker."""
    rows = conn.execute("""
        SELECT r.result FROM results r
        JOIN signals s ON r.signal_id = s.id
        WHERE s.matched_template_id = ?
          AND r.result IN ('WIN', 'PARTIAL', 'PARTIAL_TP1', 'PARTIAL_TP2', 'LOSS', 'EXPIRED')
        ORDER BY r.closed_at DESC
        LIMIT ?
    """, (template_id, lookback)).fetchall()
    if not rows:
        return 1.0
    score = sum(1.0 if r[0] == "WIN" else 0.5 if r[0] in ("PARTIAL", "PARTIAL_TP1", "PARTIAL_TP2") else 0.0
                for r in rows)
    return round(score / len(rows), 3)


def _tmpl_daily_live_count(conn, template_id: str) -> int:
    """Count today's LIVE-eligible signals for this template (UTC calendar day).

    H-CY11-3 fix (audit 2026-05-28 cycle-11): include PROVISIONAL+live_allowed=1
    signals alongside ACTIVE. The CRT path saves with template_status='PROVISIONAL'
    because Phase 5A evaluation runs AFTER save_signal() in the CRT LIVE block
    (crypto_alert.py:~4509) and never writes the status back. Pre-fix, the
    daily cap query strictly matched 'ACTIVE' and was therefore DEAD for every
    CRT signal — a Tier A CRT signal could fire 6-10× per UTC day in LIVE
    instead of the configured cap of 3. The (status='PROVISIONAL' AND
    template_live_allowed=1) branch captures CRT signals where Phase 5A passed
    but template_status stayed PROVISIONAL; 5M_SWEEP signals continue to be
    counted via the ACTIVE branch unchanged.
    """
    row = conn.execute("""
        SELECT COUNT(*) FROM signals
        WHERE matched_template_id = ?
          AND (
            template_status = 'ACTIVE'
            OR (template_status = 'PROVISIONAL' AND template_live_allowed = 1)
          )
          AND date(timestamp) = date('now', 'utc')
    """, (template_id,)).fetchone()
    return row[0] if row else 0


def evaluate_template_status(conn, template_id: str, regime: str):
    """
    Phase 5A: Compute (status, live_allowed, block_reason) for a generated signal.

    Check order — first failure wins:
      1. UNKNOWN_TEMPLATE  — template_id not in the known set
      2. PAPER_ONLY        — Tier C (live_allowed=False in registry) or daily cap = 0
      3. BLOCKED_BY_REGIME_SAFETY — RANGING + template in BLOCK_RANGING_TEMPLATES
      4. INSUFFICIENT_SAMPLE — fewer than TEMPLATE_MIN_SAMPLE closed trades
      5. PAUSED_BY_CIRCUIT_BREAKER — rolling WR < CIRCUIT_BREAKER_MIN_WR
      6. DAILY_CAP_REACHED — today's ACTIVE count >= TIER_DAILY_LIVE_CAPS[template_id]
      7. ACTIVE            — all checks passed

    Returns (status: str, live_allowed: bool, block_reason: str | None).
    On any exception returns (UNKNOWN_TEMPLATE, False, str(exc)) — never raises.
    """
    try:
        # 1. Unknown template
        if template_id not in _KNOWN_TEMPLATES:
            return ("UNKNOWN_TEMPLATE", False,
                    f"Unrecognised template_id: {template_id!r}")

        # 2. Tier C — always paper only (registry live_allowed = False)
        if template_id == "TIER_C":
            return ("PAPER_ONLY", False,
                    "Tier C is paper/backtest only (live_allowed=False in template registry)")

        # 2b. Daily cap = 0 means this tier is never live
        if TIER_DAILY_LIVE_CAPS.get(template_id, 0) == 0:
            return ("PAPER_ONLY", False,
                    f"{template_id} daily live cap = 0 (blocked by TIER_DAILY_LIVE_CAPS)")

        # 3. Regime safety layer
        if BLOCK_RANGING_LIVE and regime == "RANGING" and template_id in BLOCK_RANGING_TEMPLATES:
            return ("BLOCKED_BY_REGIME_SAFETY", False,
                    f"RANGING regime blocked for {template_id} "
                    f"(BLOCK_RANGING_LIVE=True, template in BLOCK_RANGING_TEMPLATES)")

        # 4. Minimum sample gate
        n_closed = _tmpl_closed_count(conn, template_id)
        if n_closed < TEMPLATE_MIN_SAMPLE:
            return ("INSUFFICIENT_SAMPLE", False,
                    f"{template_id} has {n_closed}/{TEMPLATE_MIN_SAMPLE} closed trades "
                    f"— minimum sample not yet reached for live execution")

        # 5. Circuit breaker
        rolling_wr = _tmpl_rolling_wr(conn, template_id, CIRCUIT_BREAKER_LOOKBACK)
        if rolling_wr < CIRCUIT_BREAKER_MIN_WR:
            return ("PAUSED_BY_CIRCUIT_BREAKER", False,
                    f"{template_id} rolling WR {rolling_wr:.0%} < "
                    f"{CIRCUIT_BREAKER_MIN_WR:.0%} over last {CIRCUIT_BREAKER_LOOKBACK} trades")

        # 6. Daily live cap
        cap   = TIER_DAILY_LIVE_CAPS.get(template_id, 0)
        today = _tmpl_daily_live_count(conn, template_id)
        if today >= cap:
            return ("DAILY_CAP_REACHED", False,
                    f"{template_id} daily live cap reached ({today}/{cap} signals today)")

        # 7. All checks passed
        return ("ACTIVE", True, None)

    except Exception as exc:
        return ("UNKNOWN_TEMPLATE", False, f"Safety eval exception: {exc}")


def log_rejection(token, direction, failed_filter, rejection_reason, metadata: dict):
    """Task 18: Persist a rejected ICT setup to the rejections table for auditability.
    Called from generate_signal() when a sweep is found but a subsequent gate fails."""
    try:
        _now = datetime.now(timezone.utc)
        conn = _connect()
        conn.execute("""INSERT INTO rejections
            (token,direction,timestamp,failed_filter,rejection_reason,
             sweep_type,sweep_level,regime,session,hour_utc,day_of_week,
             bias_4h,trend_1h,dr_location,mss_quality,fvg_quality,
             smt_confirmed,confidence,ev_score,ev_status,metadata_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (token, direction, _now.strftime("%Y-%m-%d %H:%M:%S"),
             failed_filter, rejection_reason,
             metadata.get("sweep_type",""),
             metadata.get("sweep_level", None),
             metadata.get("regime",""),
             _utc_to_session(_now.hour), _now.hour, _now.weekday(),
             metadata.get("bias_4h",""),
             metadata.get("trend_1h",""),
             metadata.get("dr_location",""),
             metadata.get("mss_quality",""),
             metadata.get("fvg_quality",""),
             int(metadata.get("smt_confirmed", 0)),
             metadata.get("confidence", None),
             metadata.get("ev_score", None),
             metadata.get("ev_status",""),
             json.dumps({k: v for k, v in metadata.items()
                         if k not in ("sweep_type","sweep_level","regime","bias_4h",
                                      "trend_1h","dr_location","mss_quality","fvg_quality",
                                      "smt_confirmed","confidence","ev_score","ev_status")})))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[DB] log_rejection error: {e}")


def get_open_signals():
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM signals WHERE status='OPEN' ORDER BY timestamp DESC"
        ).fetchall()
        conn.close(); return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB ERROR] open: {e}"); return []

def has_open_signal(token, direction):
    """Return True if there is already an OPEN signal for this token in the same direction."""
    try:
        conn = _connect()
        row  = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE token=? AND signal=? AND status='OPEN'",
            (token, direction)
        ).fetchone()
        conn.close()
        return (row[0] > 0) if row else False
    except Exception as e:
        print(f"[DB ERROR] has_open: {e}"); return False

def check_kill_switches(token):
    """Check daily/weekly loss limits, consecutive-loss pause, and symbol cooldown.

    Returns (allowed: bool, reason: str | None).
    Fails CLOSED on DB errors — a lock during a loss streak blocks trading, not permits it.
    All kill switches are active in PAPER mode — they are behavioral gates, not dollar-protection
    filters. Bypassing them inflates paper WR relative to what live would produce.
    """
    try:
        now = datetime.now(timezone.utc)  # C2: align with UTC timestamps stored by save_signal()
        today_str = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).strftime("%Y-%m-%d %H:%M:%S")
        week_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=now.weekday())
        week_str = week_start.strftime("%Y-%m-%d %H:%M:%S")

        conn = _connect()

        # 1. Daily losses — count and actual capital %
        # H13 + CRIT-1 fix (Cycle 4, 2026-05-22):
        #   profit_pct in DB is in percent units (e.g. -1.5 means -1.5% adverse move on price).
        #   ACTUAL capital impact = profit_pct% × notional_fraction. Position sizing caps
        #   notional at MAX_POSITION_PCT × capital (binds for all SL in (0.005, 0.05)).
        #   With MAX_SL_PCT=0.030 < 0.05, the cap ALWAYS binds in practice, so:
        #       capital_impact_fraction = abs(profit_pct) / 100 × MAX_POSITION_PCT
        #   Previously used `abs(profit_pct) * RISK_PER_TRADE_PCT` which conflated SL-distance%
        #   with capital-impact% and overstated daily loss by ~5×. Triggered kill switch
        #   far too early on large-SL trades. Now mathematically correct.
        #   If MAX_POSITION_PCT or MAX_SL_PCT ever change such that the cap doesn't bind
        #   (sl > risk_pct/MAX_POSITION_PCT), this formula must be revisited.
        _d_row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(profit_pct), 0.0) FROM results "
            "WHERE result IN ('LOSS','EXPIRED') AND closed_at >= ?",
            (today_str,)
        ).fetchone()
        n_daily        = int(_d_row[0] or 0)
        daily_loss_pct = abs(float(_d_row[1] or 0.0)) / 100.0 * MAX_POSITION_PCT
        if n_daily >= MAX_DAILY_LOSSES:
            conn.close()
            return False, (f"Daily loss limit: {n_daily}/{MAX_DAILY_LOSSES} losses "
                           f"({daily_loss_pct:.1%} of capital)")
        if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
            conn.close()
            return False, (f"Daily loss % limit: {daily_loss_pct:.1%} "
                           f">= {MAX_DAILY_LOSS_PCT:.0%}")

        # 2. Weekly capital loss % — same actual-P&L approach (CRIT-1 fix mirror)
        _w_row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(profit_pct), 0.0) FROM results "
            "WHERE result IN ('LOSS','EXPIRED') AND closed_at >= ?",
            (week_str,)
        ).fetchone()
        weekly_loss_pct = abs(float(_w_row[1] or 0.0)) / 100.0 * MAX_POSITION_PCT
        if weekly_loss_pct >= MAX_WEEKLY_LOSS_PCT:
            conn.close()
            return False, (f"Weekly loss % limit: {weekly_loss_pct:.1%} "
                           f">= {MAX_WEEKLY_LOSS_PCT:.0%}")

        # 3. Consecutive losses — last MAX_CONSECUTIVE_LOSSES closed results
        consec = conn.execute(
            "SELECT result FROM results "
            "WHERE result IN ('WIN','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED') "
            "ORDER BY id DESC LIMIT ?",
            (MAX_CONSECUTIVE_LOSSES,)
        ).fetchall()
        if (len(consec) >= MAX_CONSECUTIVE_LOSSES and
                all(r[0] in ("LOSS", "EXPIRED") for r in consec)):
            conn.close()
            return False, (f"Consecutive loss pause: {MAX_CONSECUTIVE_LOSSES} "
                           f"losses in a row")

        # 4. Symbol cooldown after loss
        cooldown_cutoff = (
            now - timedelta(hours=SYMBOL_LOSS_COOLDOWN_H)
        ).strftime("%Y-%m-%d %H:%M:%S")
        recent_loss = conn.execute(
            "SELECT r.closed_at FROM results r "
            "JOIN signals s ON s.id = r.signal_id "
            "WHERE s.token = ? AND r.result IN ('LOSS','EXPIRED') "
            "AND r.closed_at >= ? "
            "ORDER BY r.closed_at DESC LIMIT 1",
            (token, cooldown_cutoff)
        ).fetchone()
        conn.close()

        if recent_loss:
            return False, (f"{token} symbol cooldown — SL hit at {recent_loss[0]} "
                           f"(wait {SYMBOL_LOSS_COOLDOWN_H}h)")

        return True, None

    except Exception as e:
        _ks_err = f"[KILL SWITCH] DB check error — failing closed: {e}"
        print(_ks_err)
        send_telegram(
            "<b>KILL SWITCH  -  DB ERROR</b>\n\n"
            "<pre>"
            f"{_h(_ks_err)}"
            "</pre>\n"
            "All signal generation is blocked until the DB error clears.\n"
            "Check: <code>journalctl -u tradeai -n 50</code>"
        )
        return False, f"Kill switch DB error — failing closed to protect capital"  # C3: fail-closed

def update_signal_result(sig_id, price, tp1, tp2, tp3, sl, signal,
                         candle_high=None, candle_low=None):
    # Use candle extremes for TP/SL detection; fall back to last price when unavailable.
    hi = candle_high if (candle_high and candle_high > 0) else price
    lo = candle_low  if (candle_low  and candle_low  > 0) else price
    try:
        conn = _connect()
        row  = conn.execute(
            "SELECT tp1_hit,tp2_hit,tp3_hit,sl_hit,result FROM results WHERE signal_id=?",
            (sig_id,)).fetchone()
        if not row: conn.close(); return
        t1, t2, t3, s, prev_res = row
        if signal == "BUY":
            nt1 = 1 if hi >= tp1 else t1
            nt2 = 1 if hi >= tp2 else t2
            nt3 = 1 if hi >= tp3 else t3
            ns  = 1 if lo <= sl  else s
        else:
            nt1 = 1 if lo <= tp1 else t1
            nt2 = 1 if lo <= tp2 else t2
            nt3 = 1 if lo <= tp3 else t3
            ns  = 1 if hi >= sl  else s
        failure_reason = None
        # C6: SL priority — if SL fires AND TP1 was NOT already confirmed in a prior cycle,
        # record LOSS. Mirrors backtest check_outcome() which checks SL first and breaks.
        # Using t1 (prior state) not nt1 (current) so simultaneous TP1+SL wicks → LOSS.
        if ns and not t1:
            sp  = conn.execute("SELECT sl_pct FROM signals WHERE id=?", (sig_id,)).fetchone()[0]
            res = "LOSS"; profit = sp; closed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE signals SET status='CLOSED' WHERE id=?", (sig_id,))
            failure_reason = compute_failure_reason(sig_id, "LOSS")
        elif nt3:
            pp  = conn.execute("SELECT tp3_pct FROM signals WHERE id=?", (sig_id,)).fetchone()[0]
            res = "WIN"; profit = pp; closed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE signals SET status='CLOSED' WHERE id=?", (sig_id,))
        elif nt2:
            pp  = conn.execute("SELECT tp2_pct FROM signals WHERE id=?", (sig_id,)).fetchone()[0]
            res = "PARTIAL_TP2"; profit = pp; closed = None
        elif nt1:
            pp  = conn.execute("SELECT tp1_pct FROM signals WHERE id=?", (sig_id,)).fetchone()[0]
            res = "PARTIAL_TP1"; profit = pp; closed = None
        else:
            res = "OPEN"; profit = 0.0; closed = None
        conn.execute("""UPDATE results SET
            tp1_hit=?,tp2_hit=?,tp3_hit=?,sl_hit=?,result=?,profit_pct=?,closed_at=?,failure_reason=?
            WHERE signal_id=?""", (nt1,nt2,nt3,ns,res,profit,closed,failure_reason,sig_id))
        conn.commit(); conn.close()
        # Trigger OGD update only when the result actually changes — prevents
        # PARTIAL (TP1 hit, still open) from firing multiple updates each cycle.
        if res in ("WIN", "LOSS", "PARTIAL_TP1", "PARTIAL_TP2") and res != prev_res:
            _trigger_weight_update(sig_id, res)
    except Exception as e: print(f"[DB ERROR] update: {e}")


def _check_limit_fill(sig: dict, live_price: float,
                       candle_high=None, candle_low=None) -> None:
    """Phase A (2026-05-28) — Check whether a limit order at the bot's
    entry_price would have filled within CRT_LIMIT_FILL_WINDOW_MIN.

    Called once per scan cycle for each open signal. Logic:
      1. Skip if limit_fillable IS NOT NULL (already evaluated).
      2. Compute signal age in minutes.
      3. Detect retouch — check live_price + this cycle's 15M candle extremes:
           SELL signal: any high  >= entry_price → filled
           BUY signal:  any low   <= entry_price → filled
         (Cached 15M extremes mirror the same logic update_signal_result uses
          for TP/SL detection — same source of truth.)
      4. State transition:
           retouched=True               → limit_fillable=1, set fillable_check_at
           retouched=False, age<window  → leave NULL (still ⏳ WAITING)
           retouched=False, age>=window → limit_fillable=0, set fillable_check_at
    """
    # M10-12 fix (cycle-10 audit 2026-05-28): wrap all SQLite work in
    # try/finally so an exception between _connect() and conn.close()
    # cannot leak a file descriptor. Pre-fix each early-return path
    # called conn.close() manually but raised exceptions on the UPDATE
    # path or anywhere mid-function would leak. Single guard, deterministic.
    sig_id     = sig.get("id")
    entry      = sig.get("entry_price")
    signal_dir = sig.get("signal", "")
    ts_str     = sig.get("timestamp")
    if entry is None or not ts_str or not signal_dir:
        return
    conn = None
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT limit_fillable FROM signals WHERE id=?", (sig_id,)
        ).fetchone()
        if not row:
            return
        if row[0] is not None:
            return  # already FILLED (1) or MISSED (0) — done

        # Signal age in minutes
        now = datetime.now(timezone.utc)
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return
        age_min = (now - ts).total_seconds() / 60.0

        # The live monitor only inspects this cycle's candle extremes, so it
        # can only honestly judge retouch while the signal's fill window is
        # still recent. Beyond `window + grace`, the actual fill window has
        # long since rolled past — checking current high/low at that point
        # would produce a garbage verdict (we'd be measuring "did price
        # retouch entry hours later," not "in the 30 min after the signal").
        # Leave such rows NULL and let scripts/backfill_phase_a.py handle them
        # using historical klines that cover the real window.
        _grace = 15  # one extra 15M bar of slack for cycle timing / cold-starts
        if age_min > (CRT_LIMIT_FILL_WINDOW_MIN + _grace):
            return

        # Detect retouch
        hi = candle_high if (candle_high and candle_high > 0) else live_price
        lo = candle_low  if (candle_low  and candle_low  > 0) else live_price
        if signal_dir == "SELL":
            retouched = hi >= entry  # price came back UP to entry → limit SELL fills
        else:  # BUY
            retouched = lo <= entry  # price came back DOWN to entry → limit BUY fills

        # State transition
        if retouched:
            conn.execute(
                "UPDATE signals SET limit_fillable=1, fillable_check_at=? WHERE id=?",
                (now.strftime("%Y-%m-%d %H:%M:%S"), sig_id)
            )
            conn.commit()
            print(f"[FILL] #{sig_id} {sig.get('token','?')} {signal_dir} "
                  f"@ ${entry:.4f} → LIMIT FILLED (age {age_min:.1f} min)")
        elif age_min >= CRT_LIMIT_FILL_WINDOW_MIN:
            conn.execute(
                "UPDATE signals SET limit_fillable=0, fillable_check_at=? WHERE id=?",
                (now.strftime("%Y-%m-%d %H:%M:%S"), sig_id)
            )
            conn.commit()
            print(f"[FILL] #{sig_id} {sig.get('token','?')} {signal_dir} "
                  f"@ ${entry:.4f} → MISSED ({age_min:.1f}min elapsed, never retraced)")
        # else: still WAITING — leave NULL, will re-check next cycle
    except Exception as e:
        print(f"[FILL] _check_limit_fill #{sig_id or '?'}: {e}")
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


def mark_expired(sig_id, token):
    """Close an open signal that has passed its expiry time.
    OPEN result → EXPIRED. PARTIAL result → kept as PARTIAL (TP1 was real)."""
    try:
        conn = _connect()
        row  = conn.execute(
            "SELECT result FROM results WHERE signal_id=?", (sig_id,)).fetchone()
        if row:
            current = row[0]
            new_res  = "EXPIRED" if current == "OPEN" else current
            closed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            failure_reason = compute_failure_reason(sig_id, "EXPIRED") if current == "OPEN" else None
            conn.execute(
                "UPDATE results SET result=?,closed_at=?,failure_reason=? WHERE signal_id=?",
                (new_res, closed_at, failure_reason, sig_id))
        conn.execute("UPDATE signals SET status='CLOSED' WHERE id=?", (sig_id,))
        conn.commit(); conn.close()
        label = row[0] if row else "?"
        print(f"[EXPIRE] #{sig_id} {token} closed — was {label}")
        # Trigger immediate OGD weight update on expiry (OPEN→EXPIRED = mild penalty)
        if label == "OPEN":
            _trigger_weight_update(sig_id, "EXPIRED")
    except Exception as e:
        print(f"[DB ERROR] expire: {e}")

def compute_failure_reason(sig_id, outcome):
    """Categorize why a signal resulted in a LOSS or EXPIRED.
    Task 17: Uses ICT-specific columns (mss_quality, fvg_quality, smt_type,
    entry_type, dr_location, sweep_type) for targeted failure classification.
    Returns a category string for the failure_reason column."""
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT signal, market_regime, btc_bias, mtf_bias, conflict_level, "
            "candle_pattern, vol_ratio, confidence, "
            "mss_quality, fvg_quality, smt_type, entry_type, dr_location, sweep_type "
            "FROM signals WHERE id=?",
            (sig_id,)).fetchone()
        conn.close()
        if not row:
            return "unclassified_loss"
        (sig, regime, btc_bias, mtf_bias, conflict, pattern, vol_ratio, conf,
         mss_quality, fvg_quality, smt_type, entry_type, dr_location, sweep_type) = row
    except:
        return "unclassified_loss"

    # Regime-based failures (Task 11 new regimes included)
    if regime in ("LIQUIDATION",):
        return "news_or_liquidation_spike"
    if regime in ("CHOPPY", "LOW_VOLATILITY_CHOP"):
        return "chop_regime"
    if regime == "HIGH_VOLATILITY":
        return "news_or_liquidation_spike"

    # Dealing range location failure (check before ICT quality — DR is the primary structural gate)
    # M1: Each DR failure mode has a distinct label for accurate failure breakdown analysis.
    if dr_location == "EQUILIBRIUM":
        return "entered_in_equilibrium"
    if sig == "BUY"  and dr_location == "PREMIUM":
        return "entered_in_premium_zone"
    if sig == "SELL" and dr_location == "DISCOUNT":
        return "entered_in_discount_zone"

    # BTC divergence / MTF conflict (external confirmation failures rank above quality)
    if btc_bias:
        if sig == "BUY"  and "BEAR" in btc_bias.upper(): return "BTC_reversed"
        if sig == "SELL" and "BULL" in btc_bias.upper(): return "BTC_reversed"
    if mtf_bias:
        if sig == "BUY"  and "BEAR" in mtf_bias.upper(): return "MSS_failed"
        if sig == "SELL" and "BULL" in mtf_bias.upper(): return "MSS_failed"

    # Entry timing
    if entry_type == "ZONE_TOUCH":
        return "entry_too_early"

    # ICT-specific quality failures (checked after context — avoids swamping log with LOW during learning phase)
    if mss_quality == "LOW":
        return "low_quality_MSS"
    if smt_type == "NONE" or not smt_type:
        return "no_SMT"
    if fvg_quality == "LOW":
        return "FVG_invalidated"

    if outcome == "EXPIRED":
        return "swept_again_after_entry"
    return "unclassified_loss"


def _trigger_weight_update(sig_id: int, outcome: str):
    """
    Immediately update per-token OGD weights when a signal closes.
    Reads the feature score vector and actual profit_pct that was persisted at signal
    creation/close time — passes actual P&L to weight_engine.update() for proportional reward.
    Called from update_signal_result() and mark_expired().
    """
    try:
        conn = _connect()
        # R7 fix (master audit 2026-05-26): also fetch market_regime to label
        # the OGD update with the active regime at signal-creation time. The
        # regime is observation-only — NOT used to condition learning — and
        # is persisted to weight_history via update(snapshot=True) for future
        # regime-aware analysis.
        #
        # M-NEW-1 fix (cycle-9 audit 2026-05-28): also fetch limit_fillable to
        # gate OGD learning on real-money fillability. Pre-fix, a signal that
        # never retraced to entry within the LIMIT window (limit_fillable=0)
        # would still feed its outcome into OGD — but the outcome belongs to a
        # phantom trade that no operator could have actually entered. Trains
        # the weights on a fictional signal stream and biases learning.
        row  = conn.execute(
            "SELECT s.token, s.feature_scores_json, r.profit_pct, "
            "s.market_regime, s.limit_fillable "
            "FROM signals s LEFT JOIN results r ON r.signal_id = s.id "
            "WHERE s.id=?",
            (sig_id,)
        ).fetchone()
        conn.close()
        if not row:
            return
        token, fs_json, profit_pct, regime, limit_fillable = row

        # M-NEW-1: skip OGD learning when the LIMIT order would have missed.
        # NULL = pre-Phase-A signal OR still inside fill window — both OK to
        # train on (legacy signals have no fillability data; in-window signals
        # haven't been evaluated yet but didn't miss). Only an explicit 0
        # ("missed") suppresses learning.
        if limit_fillable == 0:
            print(f"[ADAPTIVE] #{sig_id} {token} — LIMIT order missed "
                  f"(limit_fillable=0); skipping OGD update (phantom-trade gate)")
            return

        if not fs_json:
            print(f"[ADAPTIVE] #{sig_id} — no feature_scores_json stored; skipping OGD update")
            return

        feature_scores = json.loads(fs_json)
        # Convert DB percentage-points to fraction as required by adaptive_engine.update()
        # (e.g. -0.85 pp → -0.0085 fraction). update() then divides by 0.01 to scale
        # 1% P&L → reward 1.0. Both conversions are intentional — do not remove either.
        _pct = float(profit_pct) / 100.0 if profit_pct is not None else None
        # R4 + R7 fix: pass regime + snapshot=True so weight_history captures
        # reward/gradient_l1/profit_pct/regime per OGD update (forensic queries
        # no longer require fragile joins to the results table).
        weight_engine.update(token, outcome, feature_scores,
                             profit_pct=_pct, regime=regime, snapshot=True)

    except Exception as e:
        print(f"[ADAPTIVE] _trigger_weight_update #{sig_id}: {e}")


# ══════════════════════════════════════════════════════════
# EXIT INTELLIGENCE — AI Take Profit Suggestion System
# ══════════════════════════════════════════════════════════

def assess_exit_conditions(sig, price, closes_5m):
    """
    Assess whether current market conditions warrant a take-profit suggestion
    for an open signal.  Runs 4 independent checks:
      1. Coverage    — how far price has moved toward TP1 (gate: ≥35%)
      2. RSI         — momentum exhaustion at current price
      3. MACD        — histogram reversal against trade direction
      4. ROC         — price velocity flipping against trade
      5. Time        — lifespan % consumed while in profit
    Returns an assessment dict, or None if conditions don't warrant a message.
    """
    direction = sig["signal"]
    entry     = float(sig["entry_price"] or 0)
    tp1       = float(sig["tp1"] or 0)
    tp2       = float(sig["tp2"] or 0)

    if entry <= 0 or tp1 <= 0:
        return None

    # ── 1. Coverage ───────────────────────────────────────
    if direction == "BUY":
        tp1_dist    = tp1 - entry
        price_moved = price - entry
    else:
        tp1_dist    = entry - tp1
        price_moved = entry - price

    if tp1_dist <= 0:
        return None

    coverage_pct  = round((price_moved / tp1_dist) * 100, 1)
    float_pnl_pct = round((price_moved / entry) * 100, 2)

    # Hard gate — nothing worth saying below minimum coverage
    if coverage_pct < EXIT_MIN_COVERAGE_PCT:
        return None

    # ── 2. Time remaining ─────────────────────────────────
    time_remaining_h = None
    time_pct_used    = 0.0
    exp_str = sig.get("expires_at")
    ts_str  = sig.get("timestamp")
    if exp_str and ts_str:
        try:
            created  = datetime.strptime(ts_str,  "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            expires  = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            now      = datetime.now(timezone.utc)
            total_h  = (expires - created).total_seconds() / 3600
            left_h   = (expires - now).total_seconds()    / 3600
            time_remaining_h = round(max(left_h, 0), 1)
            time_pct_used    = round(min((1 - left_h / total_h) * 100, 100), 1) if total_h > 0 else 100.0
        except:
            pass

    signals_firing = []

    # ── 3. RSI momentum exhaustion ────────────────────────
    rsi_v = None
    if len(closes_5m) >= RSI_PERIOD + 1:
        rsi_v = calculate_rsi(closes_5m)
        if direction == "SELL" and rsi_v < 35:
            signals_firing.append(f"RSI {rsi_v} — oversold, bearish momentum exhausted")
        elif direction == "BUY" and rsi_v > 65:
            signals_firing.append(f"RSI {rsi_v} — overbought, bullish momentum exhausted")

    # ── 4. MACD reversal ──────────────────────────────────
    if len(closes_5m) >= 35:
        macd = get_macd(closes_5m)
        if macd and macd.get("valid"):
            hist = macd.get("histogram", 0)
            if direction == "SELL" and macd.get("bullish"):
                signals_firing.append(
                    f"MACD turned bullish (hist:{hist:+.5f}) — bearish momentum reversing")
            elif direction == "BUY" and macd.get("bearish"):
                signals_firing.append(
                    f"MACD turned bearish (hist:{hist:+.5f}) — bullish momentum reversing")

    # ── 5. ROC velocity flip ──────────────────────────────
    if len(closes_5m) >= ROC_PERIOD + 1:
        roc_v = calculate_roc(closes_5m)
        if direction == "SELL" and roc_v > 0.6:
            signals_firing.append(f"ROC +{roc_v:.1f}% — price velocity shifted upward")
        elif direction == "BUY" and roc_v < -0.6:
            signals_firing.append(f"ROC {roc_v:.1f}% — price velocity shifted downward")

    # ── 6. Time pressure while in profit ──────────────────
    if time_remaining_h is not None and time_pct_used >= 70 and float_pnl_pct > 0.5:
        signals_firing.append(
            f"{time_pct_used:.0f}% of signal lifespan used — {time_remaining_h}h left, "
            f"+{float_pnl_pct:.2f}% at risk of expiring")

    # ── Verdict ───────────────────────────────────────────
    n = len(signals_firing)
    if coverage_pct >= EXIT_STRONG_COVERAGE_PCT:
        verdict = "TAKE_PROFIT"          # deep in TP1 zone — lock it in
    elif coverage_pct >= EXIT_PARTIAL_COVERAGE_PCT and n >= 1:
        verdict = "CONSIDER_PARTIAL"     # good coverage + at least one signal
    elif coverage_pct >= EXIT_MIN_COVERAGE_PCT and n >= 2:
        verdict = "CONSIDER_PARTIAL"     # moderate coverage but multiple signals
    elif n >= 2:
        verdict = "WATCH"                # signals present but coverage thin
    else:
        return None                      # not enough evidence

    return {
        "verdict":          verdict,
        "coverage_pct":     coverage_pct,
        "float_pnl_pct":    float_pnl_pct,
        "signals_firing":   signals_firing,
        "signal_count":     n,
        "time_remaining_h": time_remaining_h,
        "time_pct_used":    time_pct_used,
        "rsi":              rsi_v,
        "tp1":              tp1,
        "tp2":              tp2,
    }


def _exit_suggestion_cooldown_active(sig_id):
    """True if a suggestion was sent within the last EXIT_SUGGESTION_COOLDOWN_H hours."""
    try:
        conn = _connect()
        row  = conn.execute(
            "SELECT exit_suggestion_sent_at FROM results WHERE signal_id=?",
            (sig_id,)).fetchone()
        conn.close()
        if not row or not row[0]:
            return False
        last_sent = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last_sent).total_seconds() < EXIT_SUGGESTION_COOLDOWN_H * 3600
    except:
        return False


def _record_exit_suggestion(sig_id):
    try:
        conn = _connect()
        conn.execute(
            "UPDATE results SET exit_suggestion_sent_at=? WHERE signal_id=?",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), sig_id))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[DB ERROR] exit_suggestion stamp: {e}")


def send_exit_suggestion(sig, assessment, price):
    """Format and fire the AI exit suggestion Telegram alert."""
    token     = sig["token"]
    sig_id    = sig["id"]
    direction = sig["signal"]
    entry     = sig["entry_price"]
    conf      = sig.get("confidence", "?")
    regime    = sig.get("market_regime", "UNKNOWN")

    verdict     = assessment["verdict"]
    coverage    = assessment["coverage_pct"]
    pnl         = assessment["float_pnl_pct"]
    signals     = assessment["signals_firing"]
    time_rem    = assessment["time_remaining_h"]
    tp1         = assessment["tp1"]
    tp2         = assessment["tp2"]

    dir_arrow = "UP" if direction == "BUY" else "DOWN"
    pnl_sign  = "+" if pnl >= 0 else ""

    # 2026-05-28 redesign — match the clean signal-alert visual style.
    # Drop Conf/Regime (on dashboard), drop <pre> tables, use emoji bullets.
    if verdict == "TAKE_PROFIT":
        header_emoji = "\U0001F4B0"  # 💰
        header_text  = "TAKE PROFIT"
        note   = (f"Price reached <b>{coverage:.0f}%</b> of TP1 — strong exit zone. "
                  f"Consider closing the full position or majority here.")
    elif verdict == "CONSIDER_PARTIAL":
        header_emoji = "✂️"  # ✂️
        header_text  = "PARTIAL CLOSE"
        note   = (f"Take <b>30-50%</b> off the table here. "
                  f"Let the remainder run toward TP1 (${tp1:.4f}).")
    else:
        header_emoji = "\U0001F440"  # 👀
        header_text  = "WATCH CLOSELY"
        note   = "No action required yet — conditions shifting. Monitor the next few candles."

    msg = (
        f"{header_emoji} <b>{_h(header_text)} — {_h(token)} "
        f"{_h(direction)} #{_h(sig_id)}</b>\n"
        f"\n{_TG_HR}\n"
        f"\n\U0001F3AF <b>Entry:</b> ${entry:.4f}"
        f"\n\U0001F4CA <b>Now:</b> ${price:.4f}"
        f"\n\U0001F4C8 <b>Floating P&amp;L:</b> {pnl_sign}{pnl:.2f}%"
        f"\n\U0001F4CD <b>TP1 coverage:</b> {coverage:.0f}%"
    )
    if time_rem is not None:
        msg += f"\n⏰ <b>Expires in:</b> {_h(time_rem)}h"

    if signals:
        msg += f"\n\n{_TG_HR}\n\n⚠️ <b>Exit signals firing ({_h(len(signals))}):</b>"
        for s in signals:
            msg += f"\n• {_h(s)}"
    else:
        msg += f"\n\n{_TG_HR}\n\n<i>No reversal signals — purely coverage-based.</i>"

    msg += (
        f"\n\n{_TG_HR}\n"
        f"\n✅ <b>Verdict:</b>\n{note}"
        f"\n\n{_TG_HR}\n"
        f"\n\U0001F3AF <b>TP1:</b> ${tp1:.4f}"
        f"\n\U0001F3AF <b>TP2:</b> ${tp2:.4f}"
        "\n\n<i>Analysis only. Your call.</i>"
    )

    if len(msg) > 4000:
        msg = msg[:3980] + "...[trimmed]"

    send_telegram(msg)
    _record_exit_suggestion(sig_id)
    print(f"[EXIT] #{sig_id} {token} {direction} — {verdict} "
          f"coverage:{coverage:.0f}% pnl:{pnl_sign}{pnl:.2f}% "
          f"signals:{len(signals)}")


# ══════════════════════════════════════════════════════════
# DATA FETCHING
# ══════════════════════════════════════════════════════════
_INTERVAL_MS = {"1m":60000,"3m":180000,"5m":300000,"15m":900000,"30m":1800000,
                "1h":3600000,"2h":7200000,"4h":14400000,"1d":86400000}
_GAP_TOLERANCE = 2  # allow up to 2 missing candles before alerting

def fetch_binance_candles(symbol, interval, limit):
    for attempt in range(1, API_RETRIES+1):
        try:
            r = requests.get(f"{BINANCE_BASE}/klines",
                params={"symbol":symbol,"interval":interval,"limit":limit},
                headers=HEADERS, timeout=10)
            # M-CY13-1 Data fix (audit cycle-13 2026-05-29): proactive
            # 418/429 detection BEFORE raise_for_status, mirroring the
            # funding_rate_client.py pattern. Pre-fix the same handler
            # caught both via the except path, but if `requests.HTTPError`
            # was raised by a wrapping library (SSL interceptor, proxy)
            # `e.response` could be None, hiding the 418 from the alert
            # logic. Now status_code is the explicit precondition.
            _sc = getattr(r, "status_code", 0)
            if _sc == 418:
                print(f"[BINANCE-418] {symbol} {interval}: IP BANNED — aborting fetch")
                try:
                    send_telegram(
                        f"<b>[BINANCE 418 BAN]</b>\n"
                        f"<code>{symbol} {interval}</code> rejected with IP-ban "
                        f"(418). Bot stops fetching this token until ban lifts."
                    )
                except Exception:
                    pass
                return {}
            if _sc == 429:
                _wait = min(
                    int(getattr(r, "headers", {}).get("Retry-After", 30) or 30), 60,
                )
                print(f"[BINANCE-429] {symbol} {interval}: rate-limited, "
                      f"sleeping {_wait}s before retry")
                time.sleep(_wait)
                continue
            r.raise_for_status(); raw=r.json()
            if not raw: return {}
            # M-NEW-6 fix (cycle-9 audit 2026-05-28): Binance can return HTTP
            # 200 OK with a JSON error body (e.g. {"code": -1121, "msg":
            # "Invalid symbol."}). raise_for_status() only catches 4xx/5xx
            # so the error body slips past, the for-loop below silently
            # skips every "candle" (each "c" is a dict key string), and we
            # return {} with no diagnostic. Log the error code/message so
            # the operator can see WHICH symbol/interval Binance rejected.
            if isinstance(raw, dict):
                _code = raw.get("code", "?")
                _msg  = raw.get("msg", str(raw))[:200]
                print(f"[BINANCE-ERR] {symbol} {interval}: HTTP 200 with error "
                      f"body code={_code} msg={_msg!r} — treating as no-data")
                return {}
            # OHLCV field validation — reject candles with zero or invalid prices
            validated = []
            for c in raw:
                try:
                    o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
                    v, ts = float(c[5]), int(c[0])
                    if o <= 0 or h <= 0 or l <= 0 or cl <= 0 or h < l or h < o or l > o or cl > h or cl < l:
                        continue  # skip malformed candle
                    validated.append(c)
                except (ValueError, IndexError):
                    continue
            if not validated:
                return {}
            # M19: Short-fetch warning — Binance may return fewer candles than requested
            # (new listing, OHLCV validation culls, or transient partial response).
            # Silent truncation causes EMA200 to fall back to NEUTRAL with no operator
            # visibility. Warn and continue; never hard-fail.
            _got = len(validated)
            if _got < limit:
                print(f"[WARN-THIN] {symbol} {interval}: requested {limit} candles, got {_got} after validation")
                if _got < 200:
                    print(f"[WARN-THIN] {symbol} {interval}: {_got} bars < 200 — EMA200 convergence at risk, trend forced NEUTRAL")
            # Candle gap detection — warn and record worst-case gap for downstream skip
            ts_list  = [int(c[0]) for c in validated]
            iv_ms    = _INTERVAL_MS.get(interval, 0)
            max_gap_bars = 0
            if iv_ms > 0 and len(ts_list) > 1:
                gaps = [(i, ts_list[i] - ts_list[i-1]) for i in range(1, len(ts_list))
                        if ts_list[i] - ts_list[i-1] > iv_ms * (1 + _GAP_TOLERANCE)]
                if gaps:
                    max_gap_bars = max(d // iv_ms for _, d in gaps)
                    print(f"[GAP] {symbol} {interval}: {len(gaps)} gaps, worst={max_gap_bars} bars missing")
                # M22: Sub-tolerance gaps (1-2 missing candles) pass the threshold silently.
                # Log them as [WARN-GAP] so the operator can monitor — do not skip signals.
                # A gap of exactly _GAP_TOLERANCE candles is also silent (strict >) so we
                # catch anything with delta > iv_ms (i.e. at least 1 candle missing).
                sub_gaps = [(i, ts_list[i] - ts_list[i-1]) for i in range(1, len(ts_list))
                            if iv_ms < ts_list[i] - ts_list[i-1] <= iv_ms * (1 + _GAP_TOLERANCE)]
                if sub_gaps:
                    _worst_sub = max(d // iv_ms for _, d in sub_gaps) - 1  # missing candle count
                    print(f"[WARN-GAP] {symbol} {interval}: {len(sub_gaps)} sub-tolerance gap(s), "
                          f"worst={_worst_sub} candle(s) missing — within tolerance, proceeding")
            return {"opens":      [float(c[1]) for c in validated],
                    "highs":      [float(c[2]) for c in validated],
                    "lows":       [float(c[3]) for c in validated],
                    "closes":     [float(c[4]) for c in validated],
                    "volumes":    [float(c[5]) for c in validated],
                    "timestamps": [int(c[0])   for c in validated],
                    "max_gap_bars": max_gap_bars}
        except Exception as e:
            _resp = getattr(e, 'response', None)
            _sc   = getattr(_resp, 'status_code', None)
            if _sc == 418:
                print(f"[BINANCE] {symbol} {interval}: IP BANNED (418) — aborting fetch")
                # L-A fix (cycle-4 audit 2026-05-26): emit Telegram alert with
                # 1-per-hour dedup. Previously silent: bot just stopped fetching
                # without operator notification. With the watchdog providing
                # partial coverage (no heartbeat → alert), the direct 418 alert
                # closes the reaction-time gap.
                _now = time.time()
                _last_alert = globals().get("_BINANCE_418_ALERT_TS", 0.0)
                if (_now - _last_alert) >= 3600.0:
                    globals()["_BINANCE_418_ALERT_TS"] = _now
                    try:
                        send_telegram(
                            "<b>[BINANCE 418 — IP BANNED]</b>\n"
                            f"Symbol: <code>{html.escape(str(symbol))}</code> "
                            f"interval: <code>{html.escape(str(interval))}</code>\n\n"
                            "Binance returned HTTP 418 — IP-level ban. Fetches "
                            "are silently aborting. Check VPN status + Binance "
                            "API console for active bans.\n\n"
                            "<i>This alert auto-suppresses for 1 hour while the "
                            "ban persists.</i>"
                        )
                    except Exception:
                        pass
                return {}
            if _sc == 429:
                _wait = min(int(getattr(_resp, 'headers', {}).get("Retry-After", 30)), 30)
                print(f"[BINANCE] {symbol} {interval} attempt {attempt}: rate limited (429) — sleeping {_wait}s")
                time.sleep(_wait)
            else:
                print(f"[BINANCE] {symbol} {interval} attempt {attempt}: {e}")
                if attempt < API_RETRIES: time.sleep(API_DELAY)
    return {}

def fetch_binance_price(symbol):
    for attempt in range(1, API_RETRIES + 1):
        try:
            r = requests.get(f"{BINANCE_BASE}/ticker/24hr",
                    params={"symbol":symbol}, headers=HEADERS, timeout=10)
            r.raise_for_status(); d=r.json()
            return {"price":float(d.get("lastPrice",0)),
                    "change_24h":float(d.get("priceChangePercent",0)),
                    "volume_24h":float(d.get("quoteVolume",0))}
        except Exception as e:
            print(f"[BINANCE PRICE] {symbol} attempt {attempt}: {e}")
            if attempt < API_RETRIES: time.sleep(API_DELAY)
    return {}

def update_token_state(token):
    symbol=BINANCE_TOKENS[token]; state=STATE[token]
    any_ok = False
    for tf,cfg in TIMEFRAMES.items():
        data=fetch_binance_candles(symbol,cfg["interval"],cfg["limit"])
        if data:
            state["candles"][tf]=data
            any_ok = True
            if tf=="5m":
                vols=data["volumes"]
                state["avg_volume"]=sum(vols[-20:])/len(vols[-20:]) if vols else 1.0
                # H19: propagate worst-case 5M gap so generate_signal() can skip on bad data
                state["data_gap_bars"] = data.get("max_gap_bars", 0)
                state["last_5m_fetched_at"] = time.time()
            elif tf=="1h":
                state["data_gap_bars_1h"] = data.get("max_gap_bars", 0)
                state["last_1h_fetched_at"] = time.time()  # M-NEW-5
            elif tf=="4h":
                state["data_gap_bars_4h"] = data.get("max_gap_bars", 0)
                state["last_4h_fetched_at"] = time.time()  # M-NEW-5
        time.sleep(0.3)
    if any_ok:
        state["last_fetched_at"] = time.time()
    else:
        age = time.time() - state["last_fetched_at"]
        print(f"[STALE] {token}: all candle fetches failed — data is {age:.0f}s old")
    pd = fetch_binance_price(symbol)
    state["last_24h"] = pd   # cache so main loop doesn't refetch for ch24/vol
    return pd

# ══════════════════════════════════════════════════════════
# BTC CORRELATION FILTER (NEW in v9)
# ══════════════════════════════════════════════════════════
def fetch_btc_state():
    """Refresh BTC candles + CoinGecko dominance every cycle.
    H17: removed 600s BTC_FETCH_INTERVAL gate — when BTC is a monitored token,
    STATE candles are already fresh every 90s cycle so the gate only added staleness.
    get_trend() is CPU-only (no network), so recomputing every cycle is free."""
    now = time.time()
    if "BTC" in STATE and STATE["BTC"]["candles"]["1h"].get("closes"):
        c1h  = STATE["BTC"]["candles"]["1h"]["closes"]
        c15m = STATE["BTC"]["candles"]["15m"].get("closes", [])
        BTC_STATE["candles"]["5m"] = STATE["BTC"]["candles"].get("5m", {})
        # CY12-BTC-STALE-GATE-IFBRANCH fix (round-2 audit 2026-05-29: 2 agents
        # convergent — resilience N-RES-1 + data-pipeline NEW-1). Pre-fix
        # the round-1 patch ONLY set last_candle_fetch_ok in the else-branch
        # (BTC not monitored), so the operator's production config (BTC IS
        # monitored) left the timestamp at 0.0 forever → stale gate's
        # `_last_ok > 0` precondition stayed False → the gate was inert in
        # the path that actually runs. Now we derive freshness from the
        # per-token fetcher's already-tracked `last_1h_fetched_at` scalar
        # (set at line 2387 by the main scan loop). If that timestamp is
        # within STALE_CANDLE_THRESHOLD, the BTC cache is genuinely fresh
        # and we record it; otherwise we leave last_candle_fetch_ok at its
        # previous value so the stale gate downstream can fire correctly.
        _btc_1h_fresh_ts = STATE["BTC"].get("last_1h_fetched_at", 0.0)
        if _btc_1h_fresh_ts > 0 and (now - _btc_1h_fresh_ts) <= STALE_CANDLE_THRESHOLD:
            BTC_STATE["last_candle_fetch_ok"] = now
    else:
        # CY12-BTC-STALE-GATE fix (full audit 2026-05-29 resilience M-RES-2):
        # track whether AT LEAST ONE TF fetched fresh data. Pre-fix the
        # BTC_STATE["candles"][tf] dict was only OVERWRITTEN on a truthy
        # `data` (line 2382-2383), so a 418/429 response that returned {}
        # from fetch_binance_candles silently kept the previous cached
        # payload — c1h stayed non-empty, feed_ok stayed True, no alert
        # fired, and alt signals continued using stale BTC trend FOR HOURS.
        # The fix flips an _any_fetch_ok flag only when ≥1 TF succeeds.
        _any_fetch_ok = False
        for tf, limit in [("1h", 200), ("15m", 100), ("5m", 100)]:
            data = fetch_binance_candles(BTC_SYMBOL, tf, limit)
            if data:
                BTC_STATE["candles"][tf] = data
                _any_fetch_ok = True
            time.sleep(0.3)
        if _any_fetch_ok:
            BTC_STATE["last_candle_fetch_ok"] = now
        c1h  = BTC_STATE["candles"]["1h"].get("closes", [])
        c15m = BTC_STATE["candles"]["15m"].get("closes", [])
    BTC_STATE["trend_1h"]  = get_trend(c1h)  if c1h  else "NEUTRAL"
    BTC_STATE["trend_15m"] = get_trend(c15m) if c15m else "NEUTRAL"
    BTC_STATE["last_candle_fetch"] = now
    # CY12-BTC-STALE-GATE part 2: even if c1h is non-empty (cached), check
    # whether the cache is stale (>10min since last successful fetch).
    # When BTC is a monitored token the STATE["BTC"] branch above is taken
    # and fetch_binance_candles is called from the per-token scan loop;
    # the "stale BTC cache" risk is therefore primarily for the else-branch
    # (BTC not in monitored set). Defensive check both paths anyway.
    # M-CY13-2/3 fix (audit cycle-13 2026-05-29): now reads from config.py
    # so a single env knob controls the BTC-stale-cache threshold across
    # all data-pipeline gates. Pre-fix this was a hardcoded local 600s.
    _STALE_BTC_CACHE_S = BTC_STALE_FEED_S
    _last_ok = BTC_STATE.get("last_candle_fetch_ok", 0.0)
    if c1h and _last_ok > 0 and (now - _last_ok) > _STALE_BTC_CACHE_S:
        # Silent stale-cache window — flip feed_ok off so downstream
        # consumers treat BTC trend as unreliable. Alert path below
        # already handles the operator notification with 1-hour dedup.
        was_ok = BTC_STATE.get("feed_ok", True)
        BTC_STATE["feed_ok"] = False
        if was_ok:
            print(f"[BTC FEED STALE] BTC candles cache is {(now - _last_ok)/60:.1f}min old "
                  f"(>{_STALE_BTC_CACHE_S/60:.0f}min threshold) — flipping feed_ok=False")
            _now_ts = now
            _last_alert = BTC_STATE.get("feed_alert_ts", 0.0)
            if _now_ts - _last_alert >= 3600.0:
                BTC_STATE["feed_alert_ts"] = _now_ts
                try:
                    send_telegram(
                        "<b>[BTC FEED STALE]</b>\n"
                        f"BTC candles haven't refreshed in {(now - _last_ok)/60:.1f} minutes "
                        "(Binance likely rate-limiting or banning). Macro filter is now "
                        "BLOCKING all alt signals.\n\n"
                        "<i>This alert auto-suppresses for 1 hour. Re-alerts if the feed "
                        "recovers and goes stale again.</i>"
                    )
                except Exception:
                    pass
        # Treat as empty c1h for the downstream branch
        c1h = []
    if not c1h:
        was_ok = BTC_STATE.get("feed_ok", True)
        BTC_STATE["feed_ok"] = False
        print(f"[BTC FEED FAIL] BTC 1H candles empty — macro filter BLOCKED. "
              f"Alt signals suppressed until BTC data recovers.")
        # H-F fix (cycle-4 audit 2026-05-26): emit a Telegram alert when
        # the BTC feed transitions from healthy → failed, with a 1-per-hour
        # rate limit while the outage persists. Operator was previously
        # blind to BTC feed outages — only saw the symptom (no alt signals)
        # hours later. Rate-limit ensures alert is not spammed during
        # extended outages.
        _now_ts = time.time()
        _last_alert = BTC_STATE.get("feed_alert_ts", 0.0)
        if was_ok or (_now_ts - _last_alert >= 3600.0):
            BTC_STATE["feed_alert_ts"] = _now_ts
            try:
                send_telegram(
                    "<b>[BTC FEED DOWN]</b>\n"
                    "BTC 1H candles empty — macro filter is now BLOCKING all alt signals.\n\n"
                    "<i>This alert auto-suppresses for 1 hour while the outage persists. "
                    "A new alert will fire if the feed recovers and fails again.</i>"
                )
            except Exception:
                pass
    else:
        if not BTC_STATE.get("feed_ok", True):
            # Recovered — clear the dedup timer so a future outage re-alerts.
            BTC_STATE["feed_alert_ts"] = 0.0
        BTC_STATE["feed_ok"] = True
    print(f"[BTC] 1H:{BTC_STATE['trend_1h']} 15M:{BTC_STATE['trend_15m']} feed_ok={BTC_STATE['feed_ok']}")
    # [ACTIVITY] feed — BTC macro context appears once per cycle in the
    # dashboard's live AI feed so the operator knows the overall regime.
    # Includes BTC dominance + direction (CoinGecko, refreshed every
    # DOM_FETCH_INTERVAL ≈ 30 min) so the operator sees the market-wide
    # rotation signal alongside BTC's own trend.
    _dom_pct  = BTC_STATE.get("dominance", 0.0) or 0.0
    _dom_dir  = BTC_STATE.get("dom_dir", "NEUTRAL")
    _dom_str  = f"Dom {_dom_pct:.1f}% {_dom_dir}" if _dom_pct > 0 else "Dom (pending)"
    print(f"[ACTIVITY] BTC macro: 1H trend {BTC_STATE['trend_1h']}, "
          f"15M trend {BTC_STATE['trend_15m']}, {_dom_str}")

    if now - BTC_STATE["last_dom_fetch"] >= DOM_FETCH_INTERVAL:
        try:
            r = requests.get(COINGECKO_GLOBAL, headers=HEADERS, timeout=10)
            r.raise_for_status()
            dom = r.json().get("data", {}).get("market_cap_percentage", {}).get("btc", 0.0)
            if dom > 0:
                prev = BTC_STATE["dominance"]
                BTC_STATE["dominance"] = round(dom, 2)
                if prev > 0:
                    diff = dom - prev
                    if diff > DOM_THRESHOLD:     BTC_STATE["dom_dir"] = "RISING"
                    elif diff < -DOM_THRESHOLD:  BTC_STATE["dom_dir"] = "FALLING"
                    else:                        BTC_STATE["dom_dir"] = "NEUTRAL"
                BTC_STATE["last_dom_fetch"] = now
                print(f"[BTC] Dom:{BTC_STATE['dominance']:.1f}% dir:{BTC_STATE['dom_dir']}")
        except Exception as e:
            print(f"[BTC DOM] {e}")
            _stale = now - BTC_STATE["last_dom_fetch"]
            if BTC_STATE["last_dom_fetch"] > 0 and _stale > 3 * DOM_FETCH_INTERVAL:
                BTC_STATE["dom_dir"] = "NEUTRAL"
                print(f"[BTC DOM] dom_dir forced NEUTRAL — CoinGecko unreachable for {_stale/3600:.1f}h")

def get_btc_filter(signal):
    """
    Check BTC trend/dominance against the pending alt signal.
    Primary timeframe is now 1H (was 4H) to match scalper profile.
    trend_4h key kept for DB backward compatibility — stores 1H BTC trend.
    trend_1h key kept for DB backward compatibility — stores 15m BTC trend.

    Rules:
      BUY  + BTC BEAR + Dom RISING  → BLOCK   (worst case: alts bleed hard)
      BUY  + BTC BEAR                → CAUTION, -1 conf
      BUY  + BTC BULL                → ALLOW,   +1 conf
      SELL + BTC BULL                → CAUTION, -1 conf
      SELL + BTC BEAR                → ALLOW,   +1 conf
      BTC NEUTRAL / no data          → ALLOW,    0  (documented but feed_ok=False overrides)
    """
    # H18: block all alt signals when BTC feed is unavailable — NEUTRAL would silently ALLOW.
    if not BTC_STATE.get("feed_ok", False):
        return {"action": "BLOCK", "conf_bonus": 0,
                "reason": "BTC feed unavailable — macro filter inactive",
                "trend_4h": "UNKNOWN", "trend_1h": "UNKNOWN",
                "dominance": BTC_STATE["dominance"], "dom_dir": BTC_STATE["dom_dir"]}
    t1h  = BTC_STATE["trend_1h"]   # primary — replaces old 4H
    t15m = BTC_STATE["trend_15m"]  # secondary — replaces old 1H
    dom     = BTC_STATE["dominance"]
    dom_dir = BTC_STATE["dom_dir"]

    btc_bull = t1h in ("BULL", "STRONG_BULL")
    btc_bear = t1h in ("BEAR", "STRONG_BEAR")

    if signal == "BUY":
        if btc_bear and dom_dir == "RISING":
            return {"action":"BLOCK",   "conf_bonus": 0, "reason":f"BTC 1H {t1h} + dom rising {dom:.1f}%",
                    "trend_4h":t1h,"trend_1h":t15m,"dominance":dom,"dom_dir":dom_dir}
        elif btc_bear:
            return {"action":"CAUTION", "conf_bonus":-1, "reason":f"BTC 1H {t1h} (counter-trend buy)",
                    "trend_4h":t1h,"trend_1h":t15m,"dominance":dom,"dom_dir":dom_dir}
        elif btc_bull:
            return {"action":"ALLOW",   "conf_bonus": 1, "reason":f"BTC 1H {t1h} aligned",
                    "trend_4h":t1h,"trend_1h":t15m,"dominance":dom,"dom_dir":dom_dir}
    else:  # SELL
        if btc_bull:
            return {"action":"CAUTION", "conf_bonus":-1, "reason":f"BTC 1H {t1h} (counter-trend sell)",
                    "trend_4h":t1h,"trend_1h":t15m,"dominance":dom,"dom_dir":dom_dir}
        elif btc_bear:
            return {"action":"ALLOW",   "conf_bonus": 1, "reason":f"BTC 1H {t1h} aligned",
                    "trend_4h":t1h,"trend_1h":t15m,"dominance":dom,"dom_dir":dom_dir}

    return {"action":"ALLOW", "conf_bonus":0, "reason":"",
            "trend_4h":t1h,"trend_1h":t15m,"dominance":dom,"dom_dir":dom_dir}

def get_regime_for_token(token, adx_trend: float = 25.0) -> dict:
    """Get regime using 1H candles — best balance of signal vs noise.

    adx_trend is the drift-adjusted trend threshold from DriftDetector.
    adx_range and adx_choppy are derived proportionally so the relative
    spacing (trend → range → choppy) scales with the environment.
    """
    state = STATE[token]
    c1h   = state["candles"]["1h"]
    cl    = c1h.get("closes",[])
    hi    = c1h.get("highs", [])
    lo    = c1h.get("lows",  [])
    if len(cl) < 40:
        return {"regime":"UNKNOWN","adx":0,"atr_ratio":0,
                "efficiency":0,"confidence":0,"bullish":False,"bearish":False}
    adx_range  = round(adx_trend * 0.80, 1)   # 20.0 at default trend=25
    adx_choppy = round(adx_trend * 0.60, 1)   # 15.0 at default trend=25
    regime = detect_regime(cl, hi, lo,
                           adx_trend=adx_trend,
                           adx_range=adx_range,
                           adx_choppy=adx_choppy)
    state["last_regime"] = regime["regime"]
    return regime

# ══════════════════════════════════════════════════════════
# MTF BIAS
# ══════════════════════════════════════════════════════════
def get_mtf_bias(token):
    state=STATE[token]; bull={"BULL","STRONG_BULL"}; bear={"BEAR","STRONG_BEAR"}
    # Fetch all three TFs so trend_5m is available in the return dict for display,
    # but exclude 5M from the scoring weights — 5M trend is already scored in the
    # 'trend' component (25% weight) so including it here would double-count it.
    trends={tf:get_trend(state["candles"][tf].get("closes",[])) for tf in ["1h","15m","5m"]}
    w={"1h":3,"15m":2}   # total weight = 5; was 6 (included "5m":1)
    sb =sum(w[tf] for tf in w if trends[tf] in bull)
    sb2=sum(w[tf] for tf in w if trends[tf] in bear)
    if sb==sb2: return {"bias":"NEUTRAL","confidence":0,"aligned":False,"trends":trends}
    if sb>sb2: return {"bias":"BULLISH","confidence":round(sb/5*100),
                       "aligned":trends["1h"] in bull and trends["15m"] in bull,"trends":trends}
    return {"bias":"BEARISH","confidence":round(sb2/5*100),
            "aligned":trends["1h"] in bear and trends["15m"] in bear,"trends":trends}

def mtf_allows(signal,mtf):
    if signal=="BUY": return mtf["bias"] in ("BULLISH","NEUTRAL")
    return mtf["bias"] in ("BEARISH","NEUTRAL")

# ══════════════════════════════════════════════════════════
# AUTO S/R
# ══════════════════════════════════════════════════════════
def find_auto_levels(closes,highs,lows):
    cur=closes[-1] if closes else 1.0
    if len(closes)<SR_LOOKBACK:
        return {"supports":    [round(cur*0.92,8),round(cur*0.96,8),round(cur*0.98,8)],
                "resistances": [round(cur*1.05,8),round(cur*1.10,8),round(cur*1.15,8)]}
    rh=highs[-SR_LOOKBACK:]; rl=lows[-SR_LOOKBACK:]
    raw_r=[rh[i] for i in range(1,len(rh)-1) if rh[i]>rh[i-1] and rh[i]>rh[i+1]]
    raw_s=[rl[i] for i in range(1,len(rl)-1) if rl[i]<rl[i-1] and rl[i]<rl[i+1]]
    def dedup(lvls,thr=0.015):
        if not lvls: return []
        lvls=sorted(set(round(x,8) for x in lvls)); r=[lvls[0]]
        for lv in lvls[1:]:
            if abs(lv-r[-1])/r[-1]>thr: r.append(lv)
        return r
    sups=sorted([s for s in dedup(raw_s) if s<cur*1.01])
    ress=sorted([r for r in dedup(raw_r) if r>cur*1.02])
    while len(sups)<3:
        base=sups[0] if sups else cur; sups.insert(0,round(base*0.95,8))
    while len(ress)<3:
        base=ress[-1] if ress else cur; ress.append(round(base*1.06,8))
    return {"supports":[round(s,8) for s in sups[-3:]],
            "resistances":[round(r,8) for r in ress[:3]]}

def near_level(price,levels,prox=0.04):
    best=None; bd=float("inf")
    for lv in levels:
        if lv<=0: continue
        d=abs(price-lv)/lv
        if d<=prox and d<bd: best=lv; bd=d
    return best

def validate_sr_interaction(price, signal, closes, highs, lows, vol_ratio,
                             supports, resistances, near_sup, near_res):
    """
    Validate price action quality at S/R levels.
    Returns: (valid: bool, sr_type: str, reason: str)

    BUY near support  → must have closed ABOVE it (bounce confirmed).
    BUY breakout      → must close above resistance with volume.
    SELL near resist  → must have closed BELOW it (rejection confirmed).
    SELL breakdown    → must close below support with volume.
    No level nearby   → pass through (other indicators carry the signal).
    """
    if len(closes) < 2:
        return True, "NONE", ""
    last_c = closes[-1]; prev_c = closes[-2]
    last_h = highs[-1];  last_l = lows[-1]

    if signal == "BUY":
        if near_sup is not None:
            if last_c < near_sup * 1.001:
                return False, "NONE", f"Closed at/below support ${near_sup:.4f} — failed bounce"
            tested = last_l <= near_sup * 1.012
            label  = f"Bounced off ${near_sup:.4f}" if tested else f"Above support ${near_sup:.4f}"
            return True, "BOUNCE", label
        for res in sorted(resistances):
            if res <= 0: continue
            if prev_c < res and last_c > res * 1.002:
                if vol_ratio >= 1.2:
                    return True, "BREAKOUT", f"Breakout ${res:.4f} vol confirmed"
                return False, "NONE", f"Breakout ${res:.4f} — low volume fakeout risk"
        return True, "NONE", ""

    else:  # SELL
        if near_res is not None:
            if last_c > near_res * 0.999:
                return False, "NONE", f"Closed at/above resistance ${near_res:.4f} — failed rejection"
            tested = last_h >= near_res * 0.988
            label  = f"Rejected at ${near_res:.4f}" if tested else f"Below resistance ${near_res:.4f}"
            return True, "REJECTION", label
        for sup in sorted(supports, reverse=True):
            if sup <= 0: continue
            if prev_c > sup and last_c < sup * 0.998:
                if vol_ratio >= 1.2:
                    return True, "BREAKDOWN", f"Breakdown ${sup:.4f} vol confirmed"
                return False, "NONE", f"Breakdown ${sup:.4f} — low volume fakeout risk"
        return True, "NONE", ""

def is_liquid_session():
    return datetime.now(timezone.utc).hour in LIVE_CONFIG.liquid_hours


def get_dynamic_weights(adx_val):
    """Shift weights based on ADX. High ADX = trend rules. Low ADX = mean-reversion rules."""
    w = {k: v for k, v in WEIGHTS.items()}
    if adx_val >= 30:
        shift = 0.07
        w["trend"]    = min(w["trend"]    + shift,       0.40)
        w["momentum"] = min(w["momentum"] + shift * 0.5, 0.18)
        w["rsi"]      = max(w["rsi"]      - shift,       0.08)
        w["sr"]       = max(w["sr"]       - shift * 0.5, 0.07)
    elif adx_val < 20:
        shift = 0.07
        w["rsi"]      = min(w["rsi"]      + shift,       0.30)
        w["sr"]       = min(w["sr"]       + shift * 0.5, 0.22)
        w["trend"]    = max(w["trend"]    - shift,       0.12)
        w["momentum"] = max(w["momentum"] - shift * 0.5, 0.05)
    total = sum(w.values())
    return {k: round(v / total, 4) for k, v in w.items()}


# ══════════════════════════════════════════════════════════
# CANDLE STRUCTURE ANALYSIS (NEW v11)
# ══════════════════════════════════════════════════════════
def detect_candle_pattern(opens, highs, lows, closes, signal, near_sup, near_res):
    """Detect last 5M candle price action pattern for the signal direction.
    Returns: (pattern_name or None, score 0-1.0, reason string)"""
    if len(closes) < 3 or not opens:
        return None, 0.0, ""
    c_o, c_h, c_l, c_c = opens[-1], highs[-1], lows[-1], closes[-1]
    p_o, p_h, p_l, p_c = opens[-2], highs[-2], lows[-2], closes[-2]
    c_range = c_h - c_l
    p_range = p_h - p_l
    if c_range < c_c * 0.0005 or p_range == 0:
        return None, 0.0, ""
    c_body       = abs(c_c - c_o)
    p_body       = abs(p_c - p_o)
    c_upper_wick = c_h - max(c_o, c_c)
    c_lower_wick = min(c_o, c_c) - c_l
    min_ref      = max(c_body, c_range * 0.05)   # avoids doji false-positives

    if signal == "BUY":
        if (p_c < p_o and c_c > c_o and p_body > 0 and c_body > 0
                and c_c >= p_o and c_o <= p_c and c_body >= p_body * 0.8):
            return "Bullish Engulfing", 1.0, "Bullish engulfing candle"
        if (c_lower_wick >= min_ref * 2.0
                and c_lower_wick >= c_upper_wick * 2.0
                and c_body <= c_range * 0.40):
            return "Hammer", 0.85, "Hammer/pin bar"
        if (c_c > c_o and c_body > 0
                and c_c >= c_l + c_range * 0.75
                and c_body >= c_range * 0.50):
            return "Strong Bull Close", 0.75, "Strong bullish close"
        if (near_sup is not None and c_lower_wick > 0
                and c_lower_wick >= min_ref * 1.5
                and c_lower_wick >= c_range * 0.30):
            return "Support Rejection", 0.65, "Wick rejection at support"
    else:
        if (p_c > p_o and c_c < c_o and p_body > 0 and c_body > 0
                and c_c <= p_o and c_o >= p_c and c_body >= p_body * 0.8):
            return "Bearish Engulfing", 1.0, "Bearish engulfing candle"
        if (c_upper_wick >= min_ref * 2.0
                and c_upper_wick >= c_lower_wick * 2.0
                and c_body <= c_range * 0.40):
            return "Shooting Star", 0.85, "Shooting star/bearish pin bar"
        if (c_c < c_o and c_body > 0
                and c_c <= c_l + c_range * 0.25
                and c_body >= c_range * 0.50):
            return "Strong Bear Close", 0.75, "Strong bearish close"
        if (near_res is not None and c_upper_wick > 0
                and c_upper_wick >= min_ref * 1.5
                and c_upper_wick >= c_range * 0.30):
            return "Resistance Rejection", 0.65, "Wick rejection at resistance"
    return None, 0.0, ""

def calculate_conflict_score(signal, rsi_val, trend_5m, macd, mtf,
                              vol_ratio, ch24, btc_action, weights):
    """Count how many indicators actively oppose the signal. Uses dynamic weights.
    Returns: (level LOW/MEDIUM/HIGH, score 0-1.0, conflict list)"""
    conflicts = []; score = 0.0
    w = weights
    if signal == "BUY":
        if rsi_val >= RSI_OVERBOUGHT:
            conflicts.append(f"RSI overbought {rsi_val:.0f}"); score += w["rsi"]
        if trend_5m in ("BEAR", "STRONG_BEAR"):
            conflicts.append(f"5M {trend_5m}"); score += w["trend"]
        if macd["valid"] and macd["bearish"]:
            conflicts.append("MACD bearish"); score += w["momentum"] * 0.5
        if mtf["bias"] == "BEARISH":
            conflicts.append("MTF bearish"); score += w["mtf"]
        if vol_ratio >= VOLUME_SPIKE and ch24 < 0:
            conflicts.append("Vol spike red"); score += w["volume"]
        if btc_action == "BLOCK":
            conflicts.append("BTC blocked"); score += 0.15
        elif btc_action == "CAUTION":
            conflicts.append("BTC caution"); score += 0.07
    else:
        if rsi_val <= RSI_OVERSOLD:
            conflicts.append(f"RSI oversold {rsi_val:.0f}"); score += w["rsi"]
        if trend_5m in ("BULL", "STRONG_BULL"):
            conflicts.append(f"5M {trend_5m}"); score += w["trend"]
        if macd["valid"] and macd["bullish"]:
            conflicts.append("MACD bullish"); score += w["momentum"] * 0.5
        if mtf["bias"] == "BULLISH":
            conflicts.append("MTF bullish"); score += w["mtf"]
        if vol_ratio >= VOLUME_SPIKE and ch24 > 0:
            conflicts.append("Vol spike green"); score += w["volume"]
        if btc_action == "BLOCK":
            conflicts.append("BTC blocked"); score += 0.15
        elif btc_action == "CAUTION":
            conflicts.append("BTC caution"); score += 0.07
    score = round(score, 3)
    level = "HIGH" if score >= 0.40 else "MEDIUM" if score >= 0.20 else "LOW"
    return level, score, conflicts

def calculate_trade_plan(price, signal, atr_v, supports, resistances):
    if atr_v <= 0 or price <= 0: return None
    sups = sorted([s for s in supports    if s > 0])
    ress = sorted([r for r in resistances if r > 0])
    if signal == "BUY":
        below = [s for s in sups if s < price]
        if below:
            sl_sup = below[-1] * 0.97
            # Support-based SL with 3% buffer; fall back to ATR if support is too far
            # (scalper cap 1.5% — support*0.97 almost always exceeds this in real markets)
            sl = sl_sup if (price - sl_sup) / price <= MAX_SL_PCT else (price - atr_v * ATR_SL_MULT)
        else:
            sl = price - atr_v * ATR_SL_MULT
        sl = min(sl, price * (1 - MIN_SL_PCT))   # floor: SL at least MIN_SL_PCT from price
        if sl <= 0 or (price - sl) / price > MAX_SL_PCT:
            return None
        risk_dist = price - sl
        above = [r for r in ress if r > price]

        # ATR-based TP1: ~1.5×ATR target, snapped to nearest resistance when within 3×ATR.
        # rr_floor ensures a minimum 1.5R risk:reward regardless of ATR size.
        atr_tp1  = price + atr_v * 1.5
        rr_floor = price + risk_dist * MIN_TP1_MULT
        if above and above[0] <= price + atr_v * 3.0:
            tp1 = max(above[0], rr_floor)
        else:
            tp1 = max(atr_tp1, rr_floor)

        # TP2/TP3: next S/R levels beyond TP1; fallback steps equal the TP1 distance.
        # Cap TP3 at 3× TP1 distance so ancient S/R levels don't produce unreachable targets.
        sr_above_tp1 = [r for r in ress if r > tp1]
        tp1_dist = tp1 - price
        tp2 = sr_above_tp1[0] if sr_above_tp1           else tp1 + tp1_dist
        tp3_raw = sr_above_tp1[1] if len(sr_above_tp1) > 1  else tp2 + tp1_dist
        tp3 = min(tp3_raw, price + tp1_dist * 2.5)  # was 3x — tighter scalp cap

        at_sup = any(abs(price-s)/s <= 0.02 for s in sups if s > 0)
        entry  = "At support - buy now" if at_sup else \
                 (f"Wait for ${below[-1]:.4f}" if below else "Signal confirmed")
    else:
        above = [r for r in ress if r > price]
        if above:
            sl_res = above[0] * 1.03
            # Resistance-based SL with 3% buffer; fall back to ATR if resistance is too far
            sl = sl_res if (sl_res - price) / price <= MAX_SL_PCT else (price + atr_v * ATR_SL_MULT)
        else:
            sl = price + atr_v * ATR_SL_MULT
        sl = max(sl, price * (1 + MIN_SL_PCT))   # floor: SL at least MIN_SL_PCT from price
        if (sl - price) / price > MAX_SL_PCT:
            return None
        risk_dist = sl - price
        below = sorted([s for s in sups if s < price], reverse=True)

        # ATR-based TP1: ~1.5×ATR target downward, snapped to nearest support when within 3×ATR.
        # rr_max is the deepest TP1 must reach to satisfy the 1.5R minimum.
        atr_tp1 = price - atr_v * 1.5
        rr_max  = price - risk_dist * MIN_TP1_MULT
        if below and below[0] >= price - atr_v * 3.0:
            tp1 = min(below[0], rr_max)
        else:
            tp1 = min(atr_tp1, rr_max)

        # TP2/TP3: next S/R levels beyond TP1; fallback steps equal the TP1 distance.
        # Cap TP3 at 3× TP1 distance so ancient S/R levels don't produce unreachable targets.
        sr_below_tp1 = sorted([s for s in sups if s < tp1], reverse=True)
        tp1_dist = price - tp1
        tp2 = sr_below_tp1[0] if sr_below_tp1           else tp1 - tp1_dist
        tp3_raw = sr_below_tp1[1] if len(sr_below_tp1) > 1  else tp2 - tp1_dist
        tp3 = max(tp3_raw, price - tp1_dist * 2.5)  # was 3x — tighter scalp cap

        entry = "Sell confirmed"

    risk = abs(price-sl)/price*100
    def pct(t): return round(((t-price)/price*100 if signal=="BUY" else (price-t)/price*100), 2)
    def rr(t):  return round(abs(pct(t))/risk, 1) if risk > 0 else 0.0
    rt_cost     = ROUND_TRIP_COST_PCT * 100          # 0.20 percentage points
    tp1_gross   = pct(tp1)
    net_tp1_pct = round(tp1_gross - rt_cost, 3)
    if net_tp1_pct <= 0:
        return None                                  # TP1 wiped out by fees
    bew = (risk + rt_cost) / (tp1_gross + risk)      # net breakeven win rate
    if bew > MAX_BREAKEVEN_WR:
        return None                                  # fee drag makes edge too thin
    net_rr1 = round(net_tp1_pct / (risk + rt_cost), 2)
    return {"sl":round(sl,8),"tp1":round(tp1,8),"tp2":round(tp2,8),"tp3":round(tp3,8),
            "sl_pct":round(-risk,2),"tp1_pct":tp1_gross,"tp2_pct":pct(tp2),"tp3_pct":pct(tp3),
            "rr1":rr(tp1),"rr2":rr(tp2),"rr3":rr(tp3),
            "net_tp1_pct":net_tp1_pct,"net_sl_pct":round(-(risk+rt_cost),2),
            "net_rr1":net_rr1,"breakeven_wr":round(bew,4),"entry_note":entry}

def compute_position_size(capital, risk_pct, sl_pct_abs, token=""):
    """Return risk-based position sizing.

    sl_pct_abs: SL distance as a fraction (e.g. 0.015 for 1.5% SL).
    token: used to look up TOKEN_RT_COST for the fees_usd display field.
    Returns dict: notional_usd, account_risk_pct, max_loss_usd, fees_usd.
    """
    if sl_pct_abs <= 0 or capital <= 0:
        return {"notional_usd": 0.0, "account_risk_pct": 0.0,
                "max_loss_usd": 0.0, "fees_usd": 0.0}
    notional = min((capital * risk_pct) / sl_pct_abs,
                   capital * MAX_POSITION_PCT)
    return {
        "notional_usd":    round(notional, 2),
        "account_risk_pct": round(risk_pct * 100, 2),
        "max_loss_usd":    round(notional * sl_pct_abs, 2),
        "fees_usd":        round(notional * TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT), 2),
    }

def calculate_compound(capital, tp_pct, sl_pct_abs, wr, trades=10):
    if capital <= 0 or tp_pct <= 0 or sl_pct_abs <= 0: return []
    results = []; bal = capital
    for _ in range(trades):
        sizing  = compute_position_size(bal, RISK_PER_TRADE_PCT, sl_pct_abs)
        notional = sizing["notional_usd"]
        profit   = notional * (tp_pct / 100) * wr
        loss     = notional * sl_pct_abs * (1 - wr)
        bal      = round(bal + profit - loss, 2); results.append(bal)
    return results

# ══════════════════════════════════════════════════════════
# SIGNAL ENGINE (v8 — regime-aware)
# ══════════════════════════════════════════════════════════
def generate_signal(token, price, change_24h, volume_24h):  # noqa: C901
    """ICT Liquidity Sweep + MSS + FVG Retracement signal generator (Phase 4.1).
    Replaces weighted-score scalper. Entry philosophy: momentum after confirmed
    liquidity event, NOT mean-reversion at indicators."""
    # H10: injection-proof kill switch — blocks LIVE signals from any call site,
    # not just main(). When switching to LIVE, upgrade to module-flag (Option A).
    if EXECUTION_MODE == "LIVE":
        _confirmed = os.environ.get("LIVE_MODE_CONFIRMED", "").strip().upper()
        if _confirmed != "YES":
            raise RuntimeError(
                "generate_signal() called in LIVE mode without LIVE_MODE_CONFIRMED=YES. "
                "Set the env var or switch EXECUTION_MODE to PAPER."
            )
    state = STATE[token]; c15m = state["candles"]["15m"]
    if len(c15m.get("closes", [])) < 30:
        print(f"[{token}] Warming up"); return None, {}
    # H19: skip ICT analysis when 5M data has significant gaps (>=3 bars = 25+ min missing)
    if state.get("data_gap_bars", 0) >= 3:
        print(f"[SKIP-GAP] {token}: 5M data gap {state['data_gap_bars']} bars — skipping signal this cycle")
        return None, {}
    # LOW #5: skip when 1H or 4H trend data has significant gaps (bias/regime unreliable)
    if state.get("data_gap_bars_1h", 0) >= 2:
        print(f"[SKIP-GAP] {token}: 1H data gap {state['data_gap_bars_1h']} bars — skipping signal this cycle")
        return None, {}
    if state.get("data_gap_bars_4h", 0) >= 1:
        print(f"[SKIP-GAP] {token}: 4H data gap {state['data_gap_bars_4h']} bars — skipping signal this cycle")
        return None, {}

    # Exclude the currently-forming (incomplete) 15m bar from all indicators.
    # Signals must be based on closed candles to match backtest semantics.
    # ── Closed-bar slices — forming candle always excluded ─
    closes  = c15m["closes"][:-1]
    highs   = c15m["highs"][:-1]
    lows    = c15m["lows"][:-1]
    volumes = c15m["volumes"][:-1]
    opens   = c15m.get("opens", closes)[:-1]   # fallback to closes if opens absent
    if len(closes) < 20:
        return None, {}

    # ── Indicators — kept for OGD + logging ───────────────
    rsi_val  = calculate_rsi(closes)
    macd     = get_macd(closes)
    atr_v    = calculate_atr(highs, lows, closes)
    roc      = calculate_roc(closes)
    trend_5m = get_trend(closes)
    vol_avg  = sum(volumes[-20:]) / max(len(volumes[-20:]), 1)
    vol_ratio= volumes[-1] / vol_avg if vol_avg > 0 else 1.0

    # ── Regime (drift-adjusted) ────────────────────────────
    prior_drift   = drift_detector.get_dynamic_thresholds(token)
    drift_adx_thr = prior_drift["adx_trend_threshold"]
    regime        = get_regime_for_token(token, adx_trend=drift_adx_thr)
    drift_detector.update(token, regime["adx"], regime["atr_ratio"], rsi_val)

    # Use OGD-learned ICT weights if bootstrap weights are loaded OR n >= OGD_MIN_SAMPLES.
    # Bootstrap weights (from backtest) are trusted immediately; live OGD activates at n=10.
    # SAMPLE_N_OBSERVE (30) is the EV-filtering ladder gate — unrelated to OGD activation.
    _n_ogd = weight_engine.get_sample_count(token)
    eff_weights = weight_engine.get_weights(token)
    _has_bootstrap = eff_weights != dict(AE_DEFAULT_WEIGHTS)
    if _n_ogd >= OGD_MIN_SAMPLES or _has_bootstrap:
        _degen, _degen_feat, _degen_val = weight_engine._check_degenerate(eff_weights)
        if _degen:
            # Degenerate state: one feature holds >60% of weight budget — fall back to defaults
            print(f"[ADAPTIVE] {token} degenerate weights ({_degen_feat}={_degen_val:.3f}>{DEGENERATE_THRESHOLD}) — using defaults")
            eff_weights = dict(AE_DEFAULT_WEIGHTS)
        else:
            print(f"[ADAPTIVE] {token} OGD n={_n_ogd} bootstrap={_has_bootstrap} "
                  f"({', '.join(f'{k}:{v:.3f}' for k,v in eff_weights.items())})")
    else:
        eff_weights = dict(AE_DEFAULT_WEIGHTS)

    # Early exits — mirrors evaluate_setup() logic; TRENDING_BEAR exempt when it appears in
    # sell_allowed_regimes so SELL signals can still fire in that regime
    if regime["regime"] in LIVE_CONFIG.blocked_regimes:
        if regime["regime"] not in LIVE_CONFIG.sell_allowed_regimes:
            return None, regime
    if not is_liquid_session():
        return None, regime

    # Day-of-week gate is now handled centrally by evaluate_setup() via LIVE_CONFIG.blocked_weekdays

    # ── Kill switches — daily/weekly loss limits, consecutive-loss pause, symbol cooldown
    _ks_ok, _ks_reason = check_kill_switches(token)
    if not _ks_ok:
        print(f"[{datetime.now().strftime('%H:%M')}] {token} KILL SWITCH — {_ks_reason}")
        return None, regime

    # ── Macro event gate (Sprint 3 / Phase A item #4) ─────
    if MACRO_FILTER_ENABLED:
        _in_window, _event_name = _is_macro_window(
            datetime.now(timezone.utc),
            pre_hours=MACRO_PRE_WINDOW_H,
            post_hours=MACRO_POST_WINDOW_H,
        )
        if _in_window:
            if MACRO_ADVISORY_ONLY:
                print(f"[MACRO-ADVISORY] {token}: near {_event_name} — signal allowed (advisory mode)")
            else:
                print(f"[MACRO-BLOCK] {token}: blocked near {_event_name}")
                return None, regime

    # ── MTF for logging ────────────────────────────────────
    mtf = get_mtf_bias(token)

    # ── 5M candles — primary ICT setup timeframe (Phase 4.8) ─
    # Alignment: 4H bias → 1H trend → 5M setup → entry at 5M FVG
    # (was 15M setup; 5M→1H is the correct adjacent-level ICT chain)
    c5m_raw = state["candles"]["5m"]
    h5_all  = c5m_raw.get("highs",      [])[:-1]
    l5_all  = c5m_raw.get("lows",       [])[:-1]
    o5_all  = c5m_raw.get("opens",      [])[:-1]
    c5_all  = c5m_raw.get("closes",     [])[:-1]
    t5_all  = c5m_raw.get("timestamps", [])[:-1]
    if len(c5_all) < 30:
        return None, {}

    # Last 300 closed 5M bars (~25H) for ICT analysis
    _N5 = min(len(c5_all), 300)
    h5 = h5_all[-_N5:]; l5 = l5_all[-_N5:]; c5 = c5_all[-_N5:]; o5 = o5_all[-_N5:]
    t5 = t5_all[-_N5:]  # absolute timestamps (ms) aligned 1-to-1 with h5/l5/c5

    # ── ICT: confirmed swing highs/lows on 5M ─────────────
    sh_5m, sl_5m = find_ict_swings(h5, l5)

    # ── ICT: EQH/EQL clusters (Fix #9 2026-05-22) ─────────
    # Two or more near-equal swing highs/lows form an EQH/EQL stop-cluster
    # — a canonical ICT high-quality sweep target. Cluster size flows through
    # detect_ict_sweep → sweep dict → templates as a tier scoring bonus.
    sh_clust, sl_clust = find_eqh_eql_clusters(sh_5m, sl_5m)

    # ── ICT: sweep on 5M (lookback=30 bars = 2.5H) ────────
    # consumed_sweeps stores (timestamp_ms, level) pairs so that slice shifts between
    # bot cycles (as new candles arrive) do not invalidate stored entries.
    # Prune entries whose timestamp is older than the oldest bar in the current slice.
    _cs_stored = state["consumed_sweeps"]
    _oldest_ts = t5[0] if t5 else 0
    state["consumed_sweeps"] = {(ts, lv) for ts, lv in _cs_stored if ts >= _oldest_ts}
    # Translate stored timestamps → current slice bar indices for engine comparison.
    _ts_to_bar = {ts: i for i, ts in enumerate(t5)}
    _cs_for_engine = {(_ts_to_bar[ts], lv)
                      for ts, lv in state["consumed_sweeps"] if ts in _ts_to_bar}
    sweep = detect_ict_sweep(h5, l5, c5, sh_5m, sl_5m, lookback=ICT_SWEEP_LOOKBACK,
                             consumed=_cs_for_engine,
                             sh_clusters=sh_clust, sl_clusters=sl_clust)
    if not sweep:
        return None, regime
    # Recency guard: full chain (sweep→disp→FVG→MSS) must complete within 2H.
    # ICT: a setup is only valid within its originating killzone/session.
    if (len(c5) - 1) - sweep["bar"] > ICT_MAX_SETUP_AGE_BARS:
        return None, regime

    signal = "BUY" if sweep["type"] == "SSL" else "SELL"
    now    = datetime.now(timezone.utc)

    # ── 4H higher-timeframe bias ────────────────────────────
    c4h_state = state["candles"]["4h"]
    closes_4h = c4h_state.get("closes", [])[:-1]
    highs_4h  = c4h_state.get("highs",  [])[:-1]
    lows_4h   = c4h_state.get("lows",   [])[:-1]
    bias_4h   = (get_ict_4h_bias(closes_4h, highs_4h, lows_4h)
                 if len(closes_4h) >= 200 else "NEUTRAL")

    # ── 1H directional bias ─────────────────────────────────
    c1h       = state["candles"]["1h"]
    closes_1h = c1h.get("closes", [])[:-1]
    trend_1h  = get_trend(closes_1h) if len(closes_1h) >= 50 else "NEUTRAL"

    # ── Strategy gate — single source of truth (strategy_engine.py) ──
    gate = evaluate_setup(
        signal, datetime.now(timezone.utc).hour, regime["regime"],
        bias_4h, trend_1h, LIVE_CONFIG,
        weekday=datetime.now(timezone.utc).weekday(),
    )
    if not gate.accepted:
        print(f"[{now.strftime('%H:%M')}] {token} {signal} GATE: {gate.rejection_reason}")
        log_rejection(token, signal, "strategy_gate", gate.rejection_reason,
                      {"sweep_type": sweep["type"], "sweep_level": sweep["level"],
                       "regime": regime["regime"], "bias_4h": bias_4h, "trend_1h": trend_1h})
        return None, regime

    # dr_4h is computed after entry_top/entry_bottom are established (below) so the
    # FVG entry edge — not spot price — is used as the reference. ICT requires classifying
    # where the ENTRY sits in the range, not where the current ticker sits.

    print(f"[{now.strftime('%H:%M')}] {token} ICT {sweep['type']} sweep @ {sweep['level']:.4f} "
          f"— checking 5M displacement/FVG/MSS")

    # ── ICT: displacement candle on 5M (max_look=9 bars = 45min) ─
    disp_bar = detect_ict_displacement(
        sweep["bar"], o5, h5, l5, c5, sweep["type"], max_look=ICT_DISP_MAX_LOOK)
    if disp_bar is None or disp_bar + 1 >= len(c5):
        return None, regime

    # ── ICT: FVG on 5M with quality score ─────────────────
    fvg = score_ict_fvg(disp_bar, h5, l5, o5, c5)
    if not fvg or fvg["direction"] != signal:
        return None, regime
    if not meets_quality(fvg["quality"], LIVE_CONFIG.fvg_min_quality):
        print(f"[{now.strftime('%H:%M')}] {token} {signal} FVG quality={fvg['quality']} "
              f"< {LIVE_CONFIG.fvg_min_quality} — skipped")
        log_rejection(token, signal, "fvg_quality_gate",
                      f"FVG quality={fvg['quality']} < {LIVE_CONFIG.fvg_min_quality}",
                      {"sweep_type": sweep["type"], "sweep_level": sweep["level"],
                       "regime": regime["regime"], "bias_4h": bias_4h, "trend_1h": trend_1h,
                       "fvg_quality": fvg["quality"]})
        return None, regime

    # ── ICT: MSS on 5M with quality score (horizon=30 bars = 2.5H) ─
    mss_result = score_ict_mss(
        sweep["bar"], c5, o5, h5, l5, sh_5m, sl_5m, sweep["type"], horizon=ICT_MSS_HORIZON)
    if not mss_result["confirmed"]:
        return None, regime
    # ICT sequence: MSS must fire AFTER sweep bar (logical minimum — MSS-T1 fix).
    # Displacement bar IS often the CHoCH in fast setups; mss_bar=disp_bar is valid ICT.
    if mss_result["mss_bar"] <= sweep["bar"]:
        print(f"[{now.strftime('%H:%M')}] {token} {signal} REJECTED — MSS at bar {mss_result['mss_bar']} "
              f"fired before sweep at bar {sweep['bar']} (impossible sequence)")
        log_rejection(token, signal, "mss_sequence_gate",
                      f"MSS bar {mss_result['mss_bar']} <= sweep bar {sweep['bar']}",
                      {"sweep_type": sweep["type"], "disp_bar": disp_bar,
                       "mss_bar": mss_result["mss_bar"]})
        return None, regime
    # Fix #10 (2026-05-22): canonical ICT requires FVG built ON or NEAR the MSS
    # displacement bar. If MSS confirms >6 bars (30min on 5M) after displacement,
    # the FVG is structurally stale. Allows: M < D, M = D, M = D+1..D+6.
    # Rejects: M > D + ICT_MSS_DISP_MAX_GAP (slow-grind MSS).
    if mss_result["mss_bar"] - disp_bar > ICT_MSS_DISP_MAX_GAP:
        print(f"[{now.strftime('%H:%M')}] {token} {signal} REJECTED — MSS at bar {mss_result['mss_bar']} "
              f"confirmed {mss_result['mss_bar'] - disp_bar} bars after displacement bar {disp_bar} "
              f"(> {ICT_MSS_DISP_MAX_GAP}, FVG stale)")
        log_rejection(token, signal, "fvg_stale_vs_mss",
                      f"mss_bar={mss_result['mss_bar']} disp_bar={disp_bar} gap={mss_result['mss_bar']-disp_bar}>{ICT_MSS_DISP_MAX_GAP}",
                      {"sweep_type": sweep["type"], "disp_bar": disp_bar,
                       "mss_bar": mss_result["mss_bar"]})
        return None, regime
    if not meets_quality(mss_result["quality"], LIVE_CONFIG.mss_min_quality):
        print(f"[{now.strftime('%H:%M')}] {token} {signal} MSS quality={mss_result['quality']} "
              f"< {LIVE_CONFIG.mss_min_quality} — skipped")
        log_rejection(token, signal, "mss_quality_gate",
                      f"MSS quality={mss_result['quality']} < {LIVE_CONFIG.mss_min_quality}",
                      {"sweep_type": sweep["type"], "sweep_level": sweep["level"],
                       "regime": regime["regime"], "bias_4h": bias_4h, "trend_1h": trend_1h,
                       "mss_quality": mss_result["quality"]})
        return None, regime

    # ── iFVG on 5M — metadata + precision entry zone ─────────────────────
    ifvg_meta = detect_ict_ifvg(h5, l5, c5, signal)
    ifvg_5m   = detect_5m_ifvg_entry(h5, l5, c5, fvg["top"], fvg["bottom"], signal)

    # Always use full FVG entry zone — 5M iFVG precision entry reduced WR by 10.3pp in Run 41
    entry_top    = fvg["top"]
    entry_bottom = fvg["bottom"]

    # ── 4H dealing range context — classify FVG entry edge, not spot price ────
    # ICT: premium = upper 50% of DR (sell/short entries), discount = lower 50% (buy entries).
    # Using spot price here was wrong — price may have moved 0.3-0.8% from the FVG edge
    # during displacement, causing systematic DISCOUNT→EQUILIBRIUM misclassification.
    # Backtest already uses fvg["bottom"/"top"] — this aligns live to match.
    _entry_ref = entry_bottom if signal == "BUY" else entry_top
    dr_4h = compute_dealing_range(highs_4h, lows_4h, _entry_ref)

    # ── Dealing range gate ────────────────────────────────────────────────────
    # EQUILIBRIUM: no HTF directional anchor — block both directions.
    # BUY in PREMIUM: price already extended above midpoint — no discount available.
    # SELL in DISCOUNT: price already below midpoint — no premium available.
    # UNKNOWN: insufficient 4H structure — pass through (soft-penalised by OGD 0.0 DR score).
    if LIVE_CONFIG.dealing_range_gate:
        _dr_loc = dr_4h["location"]
        _dr_blocked = (
            _dr_loc == "EQUILIBRIUM"
            or (signal == "BUY"  and _dr_loc == "PREMIUM")
            or (signal == "SELL" and _dr_loc == "DISCOUNT")
        )
        if _dr_blocked:
            print(f"[{now.strftime('%H:%M')}] {token} {signal} BLOCKED — 4H DR={_dr_loc} "
                  f"(EQUILIBRIUM / BUY-in-PREMIUM / SELL-in-DISCOUNT)")
            log_rejection(token, signal, "dealing_range_gate", f"4H DR={_dr_loc}",
                          {"sweep_type": sweep["type"], "sweep_level": sweep["level"],
                           "regime": regime["regime"], "bias_4h": bias_4h, "trend_1h": trend_1h,
                           "dr_location": _dr_loc})
            return None, regime

    # ── Price inside 5M FVG entry zone ────────────────────
    if not (entry_bottom <= price <= entry_top):
        return None, regime

    # ── Entry reaction gate (P1-A) ─────────────────────────
    # Require MIDPOINT_RECLAIM or REACTION_CONFIRMED on recent closed 5M bars.
    # ZONE_TOUCH = price entered zone but no bullish/bearish confirmation candle → skip.
    _N5_react = min(len(c5_all), ENTRY_REACTION_LOOKBACK)
    entry_reaction = (detect_fvg_entry_reaction(
                          h5_all[-_N5_react:], l5_all[-_N5_react:],
                          o5_all[-_N5_react:], c5_all[-_N5_react:],
                          entry_top, entry_bottom, signal)
                      if _N5_react >= 2
                      else {"entry_type": "ZONE_TOUCH"})
    if entry_reaction["entry_type"] == "ZONE_TOUCH":
        log_rejection(token, signal, "entry_reaction_gate",
                      "ZONE_TOUCH — no prior FVG reaction candle",
                      {"sweep_type": sweep["type"], "regime": regime["regime"],
                       "bias_4h": bias_4h, "trend_1h": trend_1h,
                       "fvg_top": fvg["top"], "fvg_bottom": fvg["bottom"]})
        return None, regime

    # ── BTC correlation filter ─────────────────────────────
    if token != "BTC":
        btc_f = get_btc_filter(signal)
        if btc_f["action"] == "BLOCK":
            print(f"[{now.strftime('%H:%M')}] {token} {signal} BLOCKED BTC:{btc_f['trend_4h']}")
            return None, regime
        btc_caution = btc_f["action"] == "CAUTION"
    else:
        btc_f = {"action":"ALLOW","conf_bonus":0,"reason":"",
                 "trend_4h":BTC_STATE["trend_1h"],"trend_1h":BTC_STATE["trend_15m"],
                 "dominance":BTC_STATE["dominance"],"dom_dir":BTC_STATE["dom_dir"]}
        btc_caution = False

    # ── Cooldown ───────────────────────────────────────────
    last_t = state["last_signal_times"].get(signal)
    if last_t and (now - last_t).total_seconds() / 60 < SIGNAL_COOLDOWN:
        return None, regime

    # ── Duplicate open signal guard — active in LIVE mode, disabled in PAPER (data collection)
    if EXECUTION_MODE == "LIVE" and has_open_signal(token, signal):
        return None, regime

    # ── SMT divergence check (Task 10) ─────────────────────
    # BTC 5M candles: prefer STATE["BTC"] (if BTC is monitored) else BTC_STATE fallback.
    # 5M matches the backtest SMT resolution; 8-bar lookback = 40min in both environments.
    _btc_5m_c = (STATE["BTC"]["candles"].get("5m", {})
                 if "BTC" in STATE and STATE["BTC"]["candles"].get("5m", {}).get("highs")
                 else BTC_STATE.get("candles", {}).get("5m", {}))
    _btc_h5 = _btc_5m_c.get("highs", [])[:-1]
    _btc_l5 = _btc_5m_c.get("lows",  [])[:-1]
    # C4: need lookback(8) + reference_horizon(40) = 48 bars minimum for two-horizon test
    _Nbtc = min(len(_btc_h5), ICT_SMT_LOOKBACK + ICT_SMT_REF_HORIZON)
    if _Nbtc >= ICT_SMT_LOOKBACK + 2:
        smt_result = detect_smt_divergence(
            sweep["type"],
            ref_h=_btc_h5[-_Nbtc:], ref_l=_btc_l5[-_Nbtc:],
            lookback=ICT_SMT_LOOKBACK, reference_horizon=ICT_SMT_REF_HORIZON,
        )
    else:
        smt_result = {"smt_confirmed": False, "smt_type": "NONE",
                      "reason": "no BTC 5M data"}
    if LIVE_CONFIG.smt_gate and not smt_result["smt_confirmed"]:
        print(f"[{now.strftime('%H:%M')}] {token} {signal} SMT not confirmed "
              f"— {smt_result['reason']}")
        log_rejection(token, signal, "smt_gate",
                      f"SMT not confirmed — {smt_result['reason']}",
                      {"sweep_type": sweep["type"], "sweep_level": sweep["level"],
                       "regime": regime["regime"], "bias_4h": bias_4h, "trend_1h": trend_1h,
                       "smt_confirmed": False, "smt_type": smt_result.get("smt_type","NONE")})
        return None, regime

    # ── 1H swing levels for TP ─────────────────────────────
    highs_1h = c1h.get("highs", [])[:-1];  lows_1h = c1h.get("lows", [])[:-1]
    _N1 = min(len(highs_1h), 200)
    sh_1h, sl_1h = find_ict_swings(highs_1h[-_N1:], lows_1h[-_N1:])
    sh_1h_lvl = [lev for _, lev in sh_1h[-20:]]
    sl_1h_lvl = [lev for _, lev in sl_1h[-20:]]

    # ── Liquidity target pool (Task 9) ─────────────────────
    extra_liq = compute_liquidity_targets(
        price, signal, sh_1h_lvl, sl_1h_lvl,
        highs_4h=highs_4h, lows_4h=lows_4h,
        highs_1h=highs_1h[-_N1:], lows_1h=lows_1h[-_N1:],
        dr_4h=dr_4h,
        utc_hour=datetime.now(timezone.utc).hour,
    )

    # ── ICT trade plan (structural SL, liquidity-pool TP) ──
    sweep_wick = sweep["sweep_low"] if signal == "BUY" else sweep["sweep_high"]
    plan = compute_ict_trade_plan(price, signal, sweep_wick, sh_1h_lvl, sl_1h_lvl,
                                  extra_liq=extra_liq, token=token)
    if not plan:
        print(f"[{now.strftime('%H:%M')}] {token} {signal} SKIPPED — ICT plan rejected")
        return None, regime
    if plan["rr1"] < ICT_MIN_RR_GATE:
        print(f"[{now.strftime('%H:%M')}] {token} {signal} SKIPPED — R:R {plan['rr1']}x < {ICT_MIN_RR_GATE}x minimum")
        log_rejection(token, signal, "min_rr_gate", f"R:R {plan['rr1']}x below {ICT_MIN_RR_GATE}x floor",
                      {"rr1": plan["rr1"], "regime": regime["regime"]})
        return None, regime

    # ── Position sizing (risk-based) ───────────────────────
    sl_pct_abs = abs(plan["sl_pct"]) / 100   # e.g. plan sl_pct=-1.5 → 0.015
    sizing = compute_position_size(YOUR_CAPITAL, RISK_PER_TRADE_PCT, sl_pct_abs, token=token)

    # ── Portfolio risk layer ───────────────────────────────
    port_ok, port_reason, port_warnings = portfolio_layer.check(
        token, signal, RISK_PER_TRADE_PCT)
    if not port_ok:
        print(f"[{now.strftime('%H:%M')}] {token} {signal} BLOCKED — {port_reason}")
        return None, regime
    for w in port_warnings:
        print(f"[{now.strftime('%H:%M')}] [PORTFOLIO WARN] {token}: {w}")

    # ── Session label + distance from daily/weekly open (Task 12) ────
    _utc_now  = datetime.now(timezone.utc)
    session   = _utc_to_session(_utc_now.hour)
    # Distance from daily open: first 15M close of today UTC
    _c15m_cls = STATE[token]["candles"]["15m"].get("closes", [])
    _c15m_ts  = STATE[token]["candles"]["15m"].get("timestamps", [])
    _today_start = _utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
    _daily_open = None
    for _ti, _ts_ms in enumerate(_c15m_ts):
        _bar_dt = datetime.utcfromtimestamp(_ts_ms / 1000).replace(tzinfo=timezone.utc)
        if _bar_dt >= _today_start and _ti < len(_c15m_cls):
            _daily_open = _c15m_cls[_ti]; break
    # Distance from weekly open: first bar of current Mon UTC
    _week_start  = _today_start - timedelta(days=_utc_now.weekday())
    _weekly_open = None
    for _ti, _ts_ms in enumerate(_c15m_ts):
        _bar_dt = datetime.utcfromtimestamp(_ts_ms / 1000).replace(tzinfo=timezone.utc)
        if _bar_dt >= _week_start and _ti < len(_c15m_cls):
            _weekly_open = _c15m_cls[_ti]; break
    _dist_daily  = round((price - _daily_open)  / _daily_open  * 100, 3) if _daily_open  else None
    _dist_weekly = round((price - _weekly_open) / _weekly_open * 100, 3) if _weekly_open else None

    # ── EV scoring (Task 13) ───────────────────────────────
    ev = compute_ev_score(
        signal=signal,
        token=token,
        regime=regime["regime"],
        sweep_type=sweep["type"],
        dr_location=dr_4h["location"],
        mss_quality=mss_result["quality"],
        fvg_quality=fvg["quality"],
        strategy_version=STRATEGY_VERSION,  # H5: only include same-strategy signals in EV population
    )
    # Block only when sample is large enough and EV is confirmed negative
    if ev["ev_status"] == "NEGATIVE" and ev["sample_n"] >= SAMPLE_N_USABLE:
        print(f"[{now.strftime('%H:%M')}] {token} {signal} BLOCKED — negative EV "
              f"{ev['ev_score']:+.4f}% {ev['label']}")
        log_rejection(token, signal, "ev_gate",
                      f"Negative EV {ev['ev_score']:+.4f}% n={ev['sample_n']}",
                      {"sweep_type": sweep["type"], "sweep_level": sweep["level"],
                       "regime": regime["regime"], "bias_4h": bias_4h, "trend_1h": trend_1h,
                       "mss_quality": mss_result["quality"], "fvg_quality": fvg["quality"],
                       "smt_confirmed": smt_result.get("smt_confirmed", False),
                       "dr_location": dr_4h["location"],
                       "ev_score": ev["ev_score"], "ev_status": ev["ev_status"]})
        return None, regime

    # ── Confidence — OGD-weighted ICT quality score ───────
    fvg_size     = (fvg["top"] - fvg["bottom"]) / max(price, 1e-10)
    # iFVG bonus requires spatial proximity: iFVG midpoint must be within ICT_IFVG_PROXIMITY_PCT of FVG mid.
    # Prevents iFVGs from remote bars adding false confidence. Constant lives in ict_engine.py.
    _ifvg_spatially_valid = False
    if ifvg_meta.get("ifvg_present"):
        _ifvg_mid = (ifvg_meta.get("ifvg_top", 0.0) + ifvg_meta.get("ifvg_bottom", 0.0)) / 2
        _fvg_mid  = (fvg["top"] + fvg["bottom"]) / 2
        _ifvg_spatially_valid = abs(_ifvg_mid - _fvg_mid) / max(_fvg_mid, 1e-10) <= ICT_IFVG_PROXIMITY_PCT
    ifvg_bonus   = +1 if _ifvg_spatially_valid else 0  # Run 44: IFVG=YES 60.5% WR — spatial gate added
    # SMT bonus (C-E fix, cycle-2 audit 2026-05-25): per Run #85, SMT-confirmed
    # signals are +12pp predictive. Strategy templates award +0.10 SMT_bonus
    # in all three tiers; confidence-integer path here adds +1 so both
    # scoring layers agree. M-G (cycle-4 audit 2026-05-26): removed stale
    # "anti-predictive" Run-41/42 commentary that contradicted the C-E flip.
    # See CROSS_REF.md TPL-SMT / C-E for the verification trail.
    smt_bonus    = +1 if smt_result.get("smt_confirmed") else 0
    # OGD-weighted quality score — 5 structural features (confidence excluded to avoid circularity)
    _cur_session = _utc_to_session(datetime.now(timezone.utc).hour)
    _dr_loc      = dr_4h.get("location", "UNKNOWN")
    if signal == "BUY":
        _trend_score = {"STRONG_BULL": 1.0, "BULL": 0.65, "NEUTRAL": 0.25,
                        "BEAR": 0.0, "STRONG_BEAR": 0.0}.get(trend_1h, 0.25)
        _dr_score    = {"DISCOUNT": 1.0, "EQUILIBRIUM": 0.5,
                        "PREMIUM": 0.0, "UNKNOWN": 0.25}.get(_dr_loc, 0.25)
    else:
        _trend_score = {"STRONG_BEAR": 1.0, "BEAR": 0.65, "NEUTRAL": 0.25,
                        "BULL": 0.0, "STRONG_BULL": 0.0}.get(trend_1h, 0.25)
        _dr_score    = {"PREMIUM": 1.0, "EQUILIBRIUM": 0.5,
                        "DISCOUNT": 0.0, "UNKNOWN": 0.25}.get(_dr_loc, 0.25)
    _raw_scores  = {
        "fvg_quality":    _QUALITY_SCORE.get(fvg["quality"], 0.0),
        "mss_quality":    _QUALITY_SCORE.get(mss_result["quality"], 0.0),
        "session":        _SESSION_SCORE.get(_cur_session, 0.0),
        "trend_strength": _trend_score,
        "dr_location":    _dr_score,
    }
    _feat_w      = {f: eff_weights.get(f, AE_DEFAULT_WEIGHTS.get(f, 0.0)) for f in _raw_scores}
    _w_total     = sum(_feat_w.values())
    _ogd_quality = (sum(_raw_scores[f] * _feat_w[f] for f in _raw_scores) / _w_total
                    if _w_total > 0 else 0.5)
    confidence   = max(5, min(int(5 + _ogd_quality * 5) + ifvg_bonus + smt_bonus, 10))
    if confidence < _conf_floor:  # C7/M7: enforce dynamic floor computed by load_performance_state()
        return None, regime
    # Fix 2: enforce _signal_threshold_adj in regime-neutral conditions.
    # adj > 0 means ranging/unknown signals have been losing; we demand higher confidence.
    # Maps adj 0-2→+0, 3-5→+1, 6-7→+2 extra points on top of _conf_floor.
    if regime["regime"] in ("RANGING", "UNKNOWN") and _signal_threshold_adj > 0:
        _ranging_floor = _conf_floor + _signal_threshold_adj // 3
        if confidence < _ranging_floor:
            log_rejection(token, signal, "threshold_adj",
                          f"ranging conf floor +{_signal_threshold_adj // 3} "
                          f"(adj={_signal_threshold_adj:+d}, conf={confidence})", regime)
            return None, regime
    # Fix 3: per-token win rate gate — tighten floor when a token is in a losing streak.
    # recent_wr defaults to 0.50 (neutral) and is only lowered after >= 5 closed results.
    _tok_wr = state["recent_wr"]
    if _tok_wr < 0.35:
        _wr_extra = 2 if _tok_wr < 0.25 else 1
        if confidence < _conf_floor + _wr_extra:
            log_rejection(token, signal, "token_wr",
                          f"conf floor +{_wr_extra} for low token WR "
                          f"({_tok_wr:.0%}, conf={confidence})", regime)
            return None, regime
    strength    = "STRONG" if confidence >= 8 else "MODERATE"

    state["last_signal_times"][signal] = now
    state["total_signals"] += 1
    # Mark sweep as consumed using its absolute timestamp so slice shifts don't invalidate it.
    _sweep_ts = t5[sweep["bar"]] if sweep["bar"] < len(t5) else 0
    state["consumed_sweeps"].add((_sweep_ts, round(sweep["level"], 6)))

    # ── OGD feature scores (ICT features — fvg/mss/session/confidence/trend/dr) ─
    n_samples = _n_ogd  # computed earlier during OGD weight blend
    # Capture pure float scores BEFORE metadata update overwrites mss_quality,
    # fvg_quality, and session keys with text strings. feature_scores_json must
    # contain only the 6 normalised floats — _trigger_weight_update() passes this
    # dict directly to weight_engine.update() which expects numeric scores.
    # M13 KNOWN LIMITATION: confidence passed here is derived from the 5 structural
    # OGD features (see lines ~2386-2397 where w_confidence is correctly excluded from
    # the confidence computation). Re-injecting confidence as a 6th gradient dimension
    # creates a second-order indirect loop. Accepted under current hyperparameters;
    # Fix A (remove confidence from FEATURES) deferred to post-live evaluation.
    _ogd_scores = extract_ict_feature_scores(
        signal=signal,
        fvg_quality=fvg["quality"],
        mss_quality=mss_result["quality"],
        session=_utc_to_session(datetime.now(timezone.utc).hour),
        confidence=confidence,
        trend_1h=trend_1h,
        dr_location=dr_4h["location"],
    )
    # Metadata blob for send_signal_msg internals — NOT stored in feature_scores_json
    live_feature_scores = dict(_ogd_scores)
    live_feature_scores.update({
        "ict_sweep_type":  sweep["type"],
        "ict_sweep_level": round(sweep["level"], 6),
        "ict_fvg_bottom":  round(fvg["bottom"],  6),
        "ict_fvg_top":     round(fvg["top"],     6),
        "ict_trend_1h":    trend_1h,
        "ict_bias_4h":     bias_4h,
        "ifvg_present":    int(_ifvg_spatially_valid),
        "ifvg_direction":  ifvg_meta["ifvg_direction"] or "",
        "ifvg_top":        ifvg_meta["ifvg_top"],
        "ifvg_bottom":     ifvg_meta["ifvg_bottom"],
        "ifvg_age_bars":   ifvg_meta["ifvg_age_bars"],
        "ifvg_5m_found":   int(ifvg_5m["ifvg_5m_found"]),
        "ifvg_5m_top":     ifvg_5m["ifvg_5m_top"],
        "ifvg_5m_bottom":  ifvg_5m["ifvg_5m_bottom"],
        # Task 5: 4H dealing range context
        "dr4h_range_high":  dr_4h["range_high"],
        "dr4h_range_low":   dr_4h["range_low"],
        "dr4h_midpoint":    dr_4h["midpoint"],
        "dr4h_location":    dr_4h["location"],
        # Task 6: MSS quality
        "mss_quality":      mss_result["quality"],
        "mss_score_pts":    mss_result["score_pts"],
        "mss_bars_to_mss":  mss_result["bars_to_mss"],
        "mss_reasons":      ",".join(mss_result["reasons"]),
        # Task 7: FVG quality
        "fvg_quality":      fvg["quality"],
        "fvg_score_pts":    fvg["score_pts"],
        "fvg_size_pct":     fvg["size_pct"],
        # Task 8: entry reaction type
        "entry_type":       entry_reaction["entry_type"],
        # Task 9: TP target types
        "tp1_target_type":  plan.get("tp1_target_type", ""),
        "tp2_target_type":  plan.get("tp2_target_type", ""),
        # Task 10: SMT divergence
        "smt_confirmed":    int(smt_result["smt_confirmed"]),
        "smt_type":         smt_result["smt_type"],
        "smt_reason":       smt_result["reason"],
        # Task 13: EV score
        "ev_score":         ev["ev_score"],
        "ev_status":        ev["ev_status"],
        "ev_sample_n":      ev["sample_n"],
        "ev_label":         ev["label"],
        # Task 15: session
        "session":          session,
    })

    # ── Strategy Variant Tagging (Phase I-2) ──────────────────────────────────
    # Runs after ALL ICT features are known. Purely informational — never blocks.
    _variant_features = {
        "direction":     signal,
        "mss_quality":   mss_result["quality"],
        "fvg_quality":   fvg["quality"],
        "session":       session,
        "dr_location":   dr_4h["location"],
        "smt_confirmed": smt_result.get("smt_confirmed", False),
        "entry_type":    entry_reaction["entry_type"],
        "bias_4h":       bias_4h,
        "ifvg_present":  _ifvg_spatially_valid,
        "sweep_cluster_size": sweep.get("cluster_size", 1),  # Fix #9: EQH/EQL bonus
    }
    _variant_matches  = evaluate_confluences_vs_templates(_variant_features)
    _best_match       = next((m for m in _variant_matches if m.is_match), None)
    _best_template_id = _best_match.template_id if _best_match else "NONE"
    _template_scores  = {m.template_id: round(m.score, 4) for m in _variant_matches}
    _tier_tag = _best_template_id if _best_match else "UNMATCHED"
    _score_tag = f" score={_best_match.score:.3f}" if _best_match else ""
    print(f"[TEMPLATES] {token} {signal} → {_tier_tag}{_score_tag} "
          f"({', '.join(_best_match.confluences_matched) if _best_match else 'no match'})")

    # ── Phase 5A: Template safety evaluation ──────────────────────────────────
    try:
        _conn_5a = _connect()
        _tmpl_status, _tmpl_live_ok, _tmpl_block_reason = evaluate_template_status(
            _conn_5a, _best_template_id, regime.get("regime", "UNKNOWN"))
        _conn_5a.close()
    except Exception as _e5a:
        _tmpl_status       = "UNKNOWN_TEMPLATE"
        _tmpl_live_ok      = False
        _tmpl_block_reason = f"Safety eval exception: {_e5a}"
    _live_tag = "LIVE-OK" if _tmpl_live_ok else "PAPER"
    print(f"[PHASE5A] {token} {signal} → {_best_template_id} "
          f"status={_tmpl_status} exec={_live_tag}"
          + (f" | {_tmpl_block_reason}" if _tmpl_block_reason else ""))

    ifvg_str = (f"IFVG [{ifvg_meta['ifvg_bottom']:.5f}–{ifvg_meta['ifvg_top']:.5f}]"
                if ifvg_meta["ifvg_present"] else "IFVG: None")
    _tp1_lbl = plan.get("tp1_target_type", "")
    reasons = [
        f"ICT {sweep['type']} Sweep @ {sweep['level']:.5f}",
        f"Displacement +{disp_bar - sweep['bar']} bar(s)",
        f"FVG [{fvg['bottom']:.5f} — {fvg['top']:.5f}] gap {fvg_size*100:.2f}%",
        f"MSS confirmed ({mss_result['quality']}) | 4H: {bias_4h} | 1H: {trend_1h}",
        f"SMT: {smt_result['smt_type']} — {smt_result['reason']}",
        f"TP1 target: {_tp1_lbl}",
        f"{ifvg_str}",
        f"BTC: {btc_f['trend_4h']} Dom: {BTC_STATE['dom_dir']}",
        f"Regime: {regime['regime']} (ADX:{regime['adx']})",
    ]

    return {
        "signal":signal,"strength":strength,"confidence":confidence,"confirms":4,
        "rsi":rsi_val,
        "trend_4h":mtf["trends"].get("1h","NEUTRAL"),  # DB col label
        "trend_1h":mtf["trends"].get("15m","NEUTRAL"), # DB col label
        "trend_5m":trend_5m,"mtf_bias":mtf["bias"],"mtf_conf":mtf["confidence"],
        "mtf_aligned":mtf["aligned"],"macd":macd["value"],"atr":atr_v,"roc":roc,
        "vol_ratio":vol_ratio,"reasons":reasons,"supports":[],"resistances":[],
        "btc_trend_4h":btc_f["trend_4h"],"btc_trend_1h":btc_f["trend_1h"],
        "btc_dom":btc_f["dominance"],"btc_dom_dir":btc_f["dom_dir"],
        "btc_action":btc_f["action"],
        "wscore_buy":  round(fvg_size*100,1) if signal=="BUY"  else 0.0,
        "wscore_sell": round(fvg_size*100,1) if signal=="SELL" else 0.0,
        "conflict_level":"LOW","conflict_score":0.0,
        "candle_pattern":"ICT_FVG","sr_type":sweep["type"],
        "margin":round(fvg_size*100,1),
        "eff_weights":eff_weights,
        "drift_detected":False,"port_reason":port_reason,"ogd_samples":n_samples,
        "feature_scores_json":json.dumps(_ogd_scores),
        "plan":plan,"sizing":sizing,
        # ICT-specific — used by send_signal_msg
        "ict_sweep":sweep,"ict_fvg":fvg,"ict_trend_1h":trend_1h,
        "ict_bias_4h":bias_4h,
        "ict_ifvg":ifvg_meta,"ict_ifvg_5m":ifvg_5m,
        "dr_4h":dr_4h,
        "mss_result":mss_result,"entry_type":entry_reaction["entry_type"],
        "smt_result":smt_result,
        "tp1_target_type": plan.get("tp1_target_type", ""),
        "tp2_target_type": plan.get("tp2_target_type", ""),
        # Task 13/15: EV score + session
        "ev_score":    ev["ev_score"],
        "ev_status":   ev["ev_status"],
        "ev_sample_n": ev["sample_n"],
        "ev_label":    ev["label"],
        "session":     session,
        # Task 12: distance from daily/weekly open
        "dist_daily_open_pct":  _dist_daily,
        "dist_weekly_open_pct": _dist_weekly,
        # Phase I-2: strategy variant tagging
        "matched_template_id":  _best_template_id,
        "template_matches":     _variant_matches,
        "template_scores_json": json.dumps(_template_scores),
        # Phase 5A: template safety status
        "template_status":       _tmpl_status,
        "template_live_allowed": int(_tmpl_live_ok),
        "template_block_reason": _tmpl_block_reason or "",
    }, regime

# ══════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════
def _md(s: str) -> str:
    """L6: Escape underscores for Telegram Markdown v1 to prevent accidental italic pairs."""
    return str(s).replace("_", "\\_")

def send_telegram(message, _retries=3, _delay=5):
    """Send Telegram message with exponential-backoff retry.

    Uses HTML parse-mode (Telegram supports <b>, <i>, <code>, <pre>, <a>).
    On parse error (400 'can't parse entities'), retries once with the HTML
    tags stripped — protects against unescaped < or & in dynamic content.
    Tries up to _retries times. On total failure, logs to console so no signal
    is ever silently dropped — caller always gets True/False back."""
    if not TELEGRAM_TOKEN: return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    parse_mode = "HTML"
    text = message
    for attempt in range(1, _retries + 1):
        try:
            payload = {"chat_id": CHAT_ID, "text": text}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            r = requests.post(url, json=payload, timeout=10)
            r.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            body = (e.response.text or "").lower() if e.response is not None else ""
            if parse_mode and ("can't parse entities" in body or "parse" in body):
                print(f"[TG] HTML parse error — retrying as plain text")
                text = re.sub(r"<[^>]+>", "", message)
                parse_mode = None
                continue
            wait = _delay * attempt
            if attempt < _retries:
                print(f"[TG] attempt {attempt}/{_retries} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"[TG FAILED] All {_retries} attempts failed. Last error: {e}")
                print(f"[TG FAILED] Message was: {message[:120]}...")
        except Exception as e:
            wait = _delay * attempt          # 5s, 10s, 15s
            if attempt < _retries:
                print(f"[TG] attempt {attempt}/{_retries} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"[TG FAILED] All {_retries} attempts failed. Last error: {e}")
                print(f"[TG FAILED] Message was: {message[:120]}...")
    return False

def send_signal_msg(token,price,ch24,result,plan,sig_id,regime):
    signal=result["signal"]; conf=result["confidence"]
    bar="X"*round(conf/2)+"_"*(5-round(conf/2))
    wr_live = get_actual_win_rate()
    comp = (calculate_compound(YOUR_CAPITAL, abs(plan["tp1_pct"]),
                               abs(plan["sl_pct"]) / 100, wr_live)
            if plan else [])
    reasons="\n".join(f"  - {r}" for r in result["reasons"])
    reg=regime.get("regime","?"); reg_adx=regime.get("adx",0)
    reg_eff=regime.get("efficiency",0); reg_conf=regime.get("confidence",0)

    reg_emoji={"TRENDING_BULL":"📈","TRENDING_BEAR":"📉","RANGING":"↔️",
               "HIGH_VOLATILITY":"⚡","CHOPPY":"🌀","UNKNOWN":"❓"}.get(reg,"❓")

    sizing     = result.get("sizing", {})
    btc_t4h    = result.get("btc_trend_4h","N/A")
    btc_t1h    = result.get("btc_trend_1h","N/A")
    btc_dom    = result.get("btc_dom",0.0)
    btc_dom_dir= result.get("btc_dom_dir","NEUTRAL")
    btc_action = result.get("btc_action","ALLOW")
    dom_arrow  = {"RISING":"↑","FALLING":"↓","NEUTRAL":"→"}.get(btc_dom_dir,"→")
    btc_status = {"ALLOW":"ALIGNED","CAUTION":"CAUTION","BLOCK":"BLOCKED"}.get(btc_action,"OK")

    # ICT-specific fields
    sweep       = result.get("ict_sweep",    {})
    fvg         = result.get("ict_fvg",      {})
    ifvg_r      = result.get("ict_ifvg",     {})
    ifvg_5m_r   = result.get("ict_ifvg_5m",  {})
    dr_4h_r     = result.get("dr_4h",        {})
    mss_r       = result.get("mss_result",   {})
    smt_r       = result.get("smt_result",   {})
    trend_1h    = result.get("ict_trend_1h", "NEUTRAL")
    bias_4h     = result.get("ict_bias_4h",  "NEUTRAL")
    dr_location = dr_4h_r.get("location", "UNKNOWN")
    dr_mid      = dr_4h_r.get("midpoint", 0.0)
    mss_qual    = mss_r.get("quality", "?")
    fvg_qual    = fvg.get("quality", "?")
    entry_tp    = result.get("entry_type", "ZONE_TOUCH")
    smt_type    = smt_r.get("smt_type", "NONE")
    smt_ok      = "✓" if smt_r.get("smt_confirmed") else "✗"
    tp1_lbl     = result.get("tp1_target_type", "")
    ev_score    = result.get("ev_score",    None)
    ev_status   = result.get("ev_status",   "UNKNOWN")
    ev_sample_n = result.get("ev_sample_n", 0)
    ev_label    = result.get("ev_label",    "")
    session_lbl = result.get("session",     "UNKNOWN")
    sweep_type  = sweep.get("type","?")
    sweep_lev   = sweep.get("level", 0.0)
    fvg_bot     = fvg.get("bottom", 0.0)
    fvg_top     = fvg.get("top",    0.0)
    fvg_size_pct = (fvg_top - fvg_bot) / max(price, 1e-10) * 100
    # Note: 2026-05-28 redesign — entry_zone_line / entry_label / ifvg_line
    # and template diagnostic fields (_tmpl_id, _tmpl_status, _exec_tag) were
    # removed from the Telegram template per operator request. The data is
    # still surfaced on the dashboard. Template + ICT raw fields above remain
    # extracted so future template-tier work (Phase B) can reuse them.

    # ── 2026-05-28 redesign (operator request): clean Telegram template.
    # Keep only what's actionable for manual execution: pair, timeframe,
    # entry, SL, TP1-3, 3-5 confluences, execution discipline, dashboard
    # pointer. Everything else (ICT raw detail, BTC context, Regime/ADX,
    # Size/Risk/Fees, Net economics, full reasons list, compound projection,
    # template diagnostics) is on the dashboard and just clutters the
    # Telegram alert at decision time.
    #
    # Parse source so we can label timeframe correctly and assemble the
    # right confluences list for each scanner.
    _src     = (result.get("source") or "5M_SWEEP").upper()
    _et_full = str(result.get("entry_type") or "")
    _is_crt  = _src == "H4_CRT" or _et_full.startswith("H4_CRT")
    if _is_crt:
        # Parse "H4_CRT_<FVG|OB>_<PHASE>"; default ? on missing parts
        _parts = _et_full.split("_")
        _conf  = _parts[2] if len(_parts) >= 3 else "?"
        _phase = "_".join(_parts[3:]) if len(_parts) >= 4 else "?"
        _timeframe_lbl = "H4 CRT"
    else:
        _conf  = ""
        _phase = ""
        _timeframe_lbl = "5M SWEEP"

    # ── Title ──
    # Phase B (2026-05-28): prefix CRT tier label so operator sees quality
    # bucket at the top of every alert. Tier A/B = LIVE-eligible (subject to
    # EXECUTION_MODE), Tier C = paper-only.
    _tmpl_id = result.get("matched_template_id", "NONE")
    _tier_badge = ""
    if _tmpl_id.startswith("CRT_A_"):
        _tier_badge = "  •  \U0001F947 <b>TIER A</b>"     # gold medal
    elif _tmpl_id.startswith("CRT_B_"):
        _tier_badge = "  •  \U0001F948 <b>TIER B</b>"     # silver medal
    elif _tmpl_id.startswith("CRT_C_"):
        _tier_badge = "  •  \U0001F949 <b>TIER C</b>  <i>(paper-only)</i>"  # bronze medal
    msg = f"\U0001F4E2 <b>POTENTIAL {_h(signal)} SIGNAL</b>  #{_h(sig_id)}{_tier_badge}\n"

    # ── Header block ──
    msg += (
        f"\n\U0001F504 <b>Pair:</b> {_h(token)}/USDT"
        f"\n⏰ <b>Timeframe:</b> {_h(_timeframe_lbl)}"
    )

    # ── Trade plan (Entry / SL / TP1-3) ──
    if plan:
        msg += (
            f"\n\n{_TG_HR}\n"
            f"\n\U0001F4CD <b>Entry:</b> ${price:.4f}"
            f"\n\U0001F6D1 <b>Stop Loss:</b> ${plan['sl']:.4f}   ({plan['sl_pct']:+.2f}%)"
            f"\n\U0001F3AF <b>TP1:</b> ${plan['tp1']:.4f}   "
            f"({plan['tp1_pct']:+.2f}% · R:R {plan['rr1']})"
            f"\n\U0001F3AF <b>TP2:</b> ${plan['tp2']:.4f}   "
            f"({plan['tp2_pct']:+.2f}% · R:R {plan['rr2']})"
            f"\n\U0001F3AF <b>TP3:</b> ${plan['tp3']:.4f}   "
            f"({plan['tp3_pct']:+.2f}% · R:R {plan['rr3']})"
        )

    # ── Confluences (scanner-aware) ──
    # Keep to 4-5 bullets — the most decision-relevant features for each
    # scanner. The dashboard carries the full reasons list, ICT raw data,
    # and EV diagnostics for deeper review.
    _conflu_lines = []
    if _is_crt:
        _conflu_lines.append(f"H4 CRT — {_h(_conf)} confluence")
        if bias_4h and bias_4h != "?":
            _conflu_lines.append(f"4H bias: {_h(bias_4h)}")
        if mss_qual and mss_qual not in ("", "NONE"):
            _conflu_lines.append(f"MSS quality: {_h(mss_qual)}")
        if _phase and _phase != "?":
            _conflu_lines.append(f"Wyckoff phase: {_h(_phase)}")
    else:  # 5M_SWEEP
        if sweep_type and sweep_type != "?":
            _conflu_lines.append(f"Sweep: {_h(sweep_type)}")
        if fvg_qual and fvg_qual not in ("", "NONE"):
            _conflu_lines.append(f"FVG quality: {_h(fvg_qual)}")
        if mss_qual and mss_qual not in ("", "NONE"):
            _conflu_lines.append(f"MSS quality: {_h(mss_qual)}")
        if bias_4h and bias_4h != "?":
            _conflu_lines.append(f"4H bias: {_h(bias_4h)}")
        if trend_1h and trend_1h != "?":
            _conflu_lines.append(f"1H trend: {_h(trend_1h)}")
    if session_lbl and session_lbl not in ("", "UNKNOWN"):
        _conflu_lines.append(f"Session: {_h(session_lbl)}")
    if _conflu_lines:
        msg += f"\n\n{_TG_HR}\n\n✅ <b>Confluences:</b>"
        for _c in _conflu_lines[:5]:  # cap at 5 bullets — keep it scannable
            msg += f"\n• {_c}"

    # ── Execution discipline (LIMIT order, 30-min window) ──
    if plan:
        msg += (
            f"\n\n{_TG_HR}\n"
            f"\n\U0001F4CB <b>LIMIT {_h(signal)} @ ${price:.4f}</b> "
            f"— cancel if not filled in 30 min"
        )

    # ── Footer ──
    msg += f"\n\n{_TG_HR}\n"
    msg += "\n\U0001F4CC Full details on the dashboard."
    msg += "\n<i>Analysis only. Your call.</i>"

    if len(msg) > 4000:
        msg = msg[:3980] + "...[trimmed]"
    # CY12-SIGNAL-SMTP fix (full audit 2026-05-29 resilience M-RES-1):
    # route through MultiChannelAlerter (heartbeat already uses it) so
    # SMTP secondary channel catches Telegram outages on the actual
    # signal alert — not just heartbeats. Operator-monetary-impact gap:
    # pre-fix, a Telegram outage during signal emit meant the operator
    # NEVER saw the signal even though the DB row was saved. The
    # falls-back path (when _signal_alerter is None — e.g. tests, early
    # startup, replay) is the same send_telegram() the function used
    # before, so existing call sites keep working.
    if _signal_alerter is not None:
        try:
            _signal_alerter.send("Signal", msg)
        except Exception:
            # Defensive — never let alert routing kill the bot loop.
            # Fall back to the bare telegram path if the alerter raises.
            try:
                send_telegram(msg)
            except Exception:
                pass
    else:
        send_telegram(msg)
    ifvg_tag    = " IFVG" if ifvg_r.get("ifvg_present") else ""
    ifvg_5m_tag = " 5M-iFVG" if ifvg_5m_r.get("ifvg_5m_found") else ""
    print(f"[SIGNAL] {token} {signal} ${price:.4f} "
          f"Sweep:{sweep_type} FVG:{fvg_size_pct:.2f}%[{fvg_qual}]{ifvg_tag}{ifvg_5m_tag} "
          f"MSS:[{mss_qual}] Entry:{entry_tp} "
          f"4H:{bias_4h} 1H:{trend_1h} Conf:{conf}/10 Regime:{reg}")

# ══════════════════════════════════════════════════════════
# MONITOR & SUMMARY
# ══════════════════════════════════════════════════════════
def monitor_open_signals(prices):
    now = datetime.now(timezone.utc)
    for sig in get_open_signals():
        exp_str = sig.get("expires_at")
        if exp_str:
            try:
                if now > datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc):
                    mark_expired(sig["id"], sig["token"])
                    continue
            except Exception as e:
                print(f"[EXPIRE] parse error #{sig['id']}: {e}")
        else:
            # Safety net: signals with no expiry set that are older than 48h
            # are auto-expired to prevent permanent blocking of the duplicate guard.
            try:
                created = datetime.strptime(sig["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if (now - created).total_seconds() > 48 * 3600:
                    print(f"[EXPIRE] #{sig['id']} {sig['token']} — no expiry, age >{48}h, auto-expiring")
                    mark_expired(sig["id"], sig["token"])
                    continue
            except Exception as e:
                print(f"[EXPIRE] age-check error #{sig['id']}: {e}")
        token = sig["token"]
        price = prices.get(token, 0.0)
        if price > 0:
            # H16: suppress stale candle extremes — live price is always valid but the
            # cached 15m candle slice can lag a full cycle if fetch failed this iteration.
            # Pass None for candle_high/low when stale; update_signal_result() falls back
            # to live price only (see line 1009: hi = candle_high if candle_high > 0 else price).
            _tok_age = time.time() - STATE.get(token, {}).get("last_fetched_at", 0.0)
            _candles_stale = STATE.get(token, {}).get("last_fetched_at", 0.0) > 0 and _tok_age > STALE_CANDLE_THRESHOLD
            if _candles_stale:
                print(f"[STALE-MONITOR] {token}: candles {_tok_age:.0f}s old — using live price only for TP/SL")
                candle_high = candle_low = None
            else:
                # 15m candle extremes for TP/SL touch detection (matches signal entry TF).
                #
                # 2026-05-28 latency fix (operator-flagged LINK#1 case): pre-fix
                # the monitor read ONLY the last closed 15M candle (`[-2]`) — so
                # a TP hit in the first minute of the forming 15M candle wasn't
                # detected until that candle closed (~14 min later) plus the
                # next bot cycle (~70s). Worst-case detection latency: ~16 min.
                #
                # Fix: take the most extreme of three sources — closed 15M
                # extreme, forming 15M extreme, and the live tick price. Lows
                # don't unpaint within a forming bar (a printed low can only
                # go lower or stay the same), so this is SAFE: it only
                # accelerates detection of TPs that price genuinely touched;
                # it never invents fake hits.
                #
                # SL detection is C6-protected: `if ns and not t1: LOSS` uses
                # the PRIOR tp1_hit state, so a forming-bar dip through SL
                # after TP1 was already booked correctly preserves the WIN.
                candles_15m = STATE.get(token, {}).get("candles", {}).get("15m", {})
                highs       = candles_15m.get("highs", [])
                lows        = candles_15m.get("lows",  [])
                _hi_candidates = [price]
                _lo_candidates = [price]
                if len(highs) >= 2:
                    _hi_candidates.append(highs[-2])  # last closed
                    if highs[-1] is not None:
                        _hi_candidates.append(highs[-1])  # forming (running high)
                if len(lows) >= 2:
                    _lo_candidates.append(lows[-2])
                    if lows[-1] is not None:
                        _lo_candidates.append(lows[-1])
                candle_high = max(_hi_candidates) if _hi_candidates else None
                candle_low  = min(_lo_candidates) if _lo_candidates else None
            update_signal_result(sig["id"], price,
                sig["tp1"], sig["tp2"], sig["tp3"], sig["sl"], sig["signal"],
                candle_high=candle_high, candle_low=candle_low)

            # Phase A (2026-05-28) — Limit-order fillability check.
            # For signals with limit_fillable=NULL (still in the 30-min waiting
            # window), determine if the bot's entry_price has been retouched.
            # If yes → mark FILLED (1). If 30+ min elapsed without retouch →
            # mark MISSED (0). This measures the empirical fill rate of the
            # operator's chosen limit-order discipline (Option 1).
            _check_limit_fill(sig, price, candle_high, candle_low)

            # Exit intelligence — closed 5m bars only ([:-1] excludes the forming candle,
            # matching the convention used in the entry path at lines 2056-2060).
            closes_5m = STATE.get(token, {}).get("candles", {}).get("5m", {}).get("closes", [])[:-1]
            if closes_5m and not _exit_suggestion_cooldown_active(sig["id"]):
                assessment = assess_exit_conditions(sig, price, closes_5m)
                if assessment:
                    send_exit_suggestion(sig, assessment, price)

def maybe_send_daily_summary(prices):
    global last_summary_date
    now=datetime.now(timezone.utc)  # L5: use UTC so summary fires at 08:00 UTC, not local time
    if not (now.hour==8 and now.minute<10): return
    if last_summary_date==now.date(): return
    last_summary_date=now.date()
    try:
        conn=_connect()
        total   =conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        wins    =conn.execute("SELECT COUNT(*) FROM results WHERE result='WIN'").fetchone()[0]
        partial =conn.execute("SELECT COUNT(*) FROM results WHERE result IN ('PARTIAL','PARTIAL_TP1','PARTIAL_TP2')").fetchone()[0]
        losses  =conn.execute("SELECT COUNT(*) FROM results WHERE result='LOSS'").fetchone()[0]
        expired =conn.execute("SELECT COUNT(*) FROM results WHERE result='EXPIRED'").fetchone()[0]
        opens   =conn.execute("SELECT COUNT(*) FROM signals WHERE status='OPEN'").fetchone()[0]
        conn.close()
        closed=wins+partial+losses+expired
        wr=round((wins + 0.5*partial)/closed*100) if closed>0 else 0
        db_line=f"{total} signals | {wins}W/{partial}P/{losses}L/{expired}E ({wr}% WR) | {opens} open"
    except: db_line="DB unavailable"
    # Fallback regime per token — read last known regime from DB for tokens
    # whose in-memory state is still UNKNOWN (e.g. bot just restarted).
    db_regimes = {}
    try:
        conn2 = _connect()
        for token in BINANCE_TOKENS:
            row = conn2.execute(
                "SELECT market_regime FROM signals WHERE token=? AND market_regime IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1", (token,)).fetchone()
            if row and row[0]:
                db_regimes[token] = row[0]
        conn2.close()
    except: pass

    # 2026-05-28 redesign — match the clean Telegram style used across the
    # rest of the bot (signal alert, exit suggestion, heartbeat, watchdog,
    # explorer). Drops <pre> blocks (no copy button), uses emoji-bulleted
    # fields with ━━━ section dividers.
    token_rows = []
    for token in BINANCE_TOKENS:
        price = prices.get(token, 0.0)
        if price <= 0:
            continue
        closes = STATE[token]["candles"]["15m"].get("closes", [])[:-1]  # exclude forming bar
        rsi_v  = calculate_rsi(closes) if closes else 50.0
        mtf    = get_mtf_bias(token)
        reg    = STATE[token]["last_regime"]
        if reg == "UNKNOWN":
            reg = db_regimes.get(token, "UNKNOWN")
        # Emoji prefix per MTF bias for at-a-glance scan
        _mtf_b = mtf['bias']
        _mtf_emoji = ("\U0001F4C8" if _mtf_b == "BULLISH"
                      else "\U0001F4C9" if _mtf_b == "BEARISH"
                      else "↔️")  # NEUTRAL or other
        token_rows.append(
            f"• <b>{_h(token)}</b>  ${price:.4f}  ·  RSI {_h(int(rsi_v))}  ·  "
            f"{_mtf_emoji} {_h(_mtf_b)}  ·  {_h(reg)}"
        )

    # Parse db_line into structured fields for the header card.
    # Format: "{total} signals | {W}W/{P}P/{L}L/{E}E ({WR}% WR) | {opens} open"
    try:
        _stats_summary = (
            f"\U0001F4CA <b>Signals:</b> {_h(total)} total · "
            f"{_h(wins)}W / {_h(partial)}P / {_h(losses)}L / {_h(expired)}E"
            f"\n\U0001F3AF <b>Win rate:</b> {_h(wr)}%"
            f"\n\U0001F4CD <b>Open:</b> {_h(opens)}"
        )
    except Exception:
        # Fallback to the parsed db_line if individual fields are missing
        _stats_summary = f"\U0001F4CA {_h(db_line)}"

    msg = (
        f"\U0001F4C5 <b>Daily Summary — {_h(now.strftime('%Y-%m-%d'))}</b>\n"
        f"\n{_TG_HR}\n"
        f"\n{_stats_summary}"
        f"\n\n{_TG_HR}\n"
        f"\n\U0001F4CB <b>Per-Token Snapshot:</b>\n"
        + "\n".join(token_rows)
        + f"\n\n{_TG_HR}\n"
        + "\n<i>Analysis only. Your call.</i>"
    )
    send_telegram(msg); print("[DAILY SUMMARY SENT]")

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
# M-C fix (cycle-4 audit 2026-05-26): graceful SIGTERM handler. systemctl
# restart sends SIGTERM; without a handler the Python process exits
# uncaught mid-cycle → in-flight Telegram sends may truncate, atomic
# DB writes survive but the operator gets no "shutting down" notice.
# Now: SIGTERM sets _SHUTDOWN_REQUESTED so the main loop exits cleanly
# at the next safe point (between cycles) + sends a final Telegram alert.
_SHUTDOWN_REQUESTED = False


def _on_shutdown(signum, frame):
    global _SHUTDOWN_REQUESTED
    _SHUTDOWN_REQUESTED = True
    print(f"\n[SIGTERM] graceful shutdown requested (signal {signum}); "
          f"will exit at next safe point.")


def main():
    # M-C fix: install SIGTERM handler. SIGINT (Ctrl+C) already raises
    # KeyboardInterrupt which the main loop catches at line 3311.
    try:
        _sig_module.signal(_sig_module.SIGTERM, _on_shutdown)
    except (ValueError, OSError) as _e:
        # ValueError: not in main thread; OSError: signal not available
        print(f"[BOOT] SIGTERM handler not installed: {_e}")

    if not TELEGRAM_TOKEN:
        print("ERROR: Set TELEGRAM_TOKEN first")
        print("  CMD:        set TELEGRAM_TOKEN=your_token")
        print("  PowerShell: $env:TELEGRAM_TOKEN='your_token'"); return
    if not CHAT_ID:
        print("ERROR: Set CHAT_ID first")
        print("  CMD:        set CHAT_ID=your_chat_id")
        print("  PowerShell: $env:CHAT_ID='your_chat_id'"); return

    # ── LIVE mode kill switch ──────────────────────────────────
    # Prevents accidental live trading. To go LIVE you must explicitly set:
    #   CMD:        set LIVE_MODE_CONFIRMED=YES
    #   PowerShell: $env:LIVE_MODE_CONFIRMED="YES"
    if EXECUTION_MODE == "LIVE":
        _confirmed = os.environ.get("LIVE_MODE_CONFIRMED", "").strip().upper()
        if _confirmed != "YES":
            print("=" * 58)
            print("  LIVE MODE BLOCKED — explicit confirmation required")
            print("  EXECUTION_MODE=LIVE is set but LIVE_MODE_CONFIRMED is not.")
            print("  To proceed with real-money trading, set:")
            print("    CMD:        set LIVE_MODE_CONFIRMED=YES")
            print("    PowerShell: $env:LIVE_MODE_CONFIRMED=\"YES\"")
            print("  Then restart the bot.")
            print("=" * 58)
            return
        logger.warning("LIVE MODE ACTIVE — trading with real capital. LIVE_MODE_CONFIRMED=YES")
        # YOUR_CAPITAL guard — must be set explicitly before LIVE trading.
        # The default $1000 produces wrong position sizes for any other account size.
        _raw_capital = os.environ.get("YOUR_CAPITAL")
        if _raw_capital is None or float(_raw_capital) == 1000.0:
            print("=" * 58)
            print("  LIVE GUARD: YOUR_CAPITAL is unset or still the default $1000.")
            print("  Set YOUR_CAPITAL in env.bat to your actual account size.")
            print("  Example:  set YOUR_CAPITAL=5000")
            print("=" * 58)
            logger.error("[LIVE GUARD] YOUR_CAPITAL not configured — refusing to start in LIVE mode.")
            return

    # ── Single-instance PID guard (Phase A-2) ────────────
    # Prevents two bot processes from updating the same DB concurrently.
    # supervisord auto-restart makes this real: the supervisor may launch a
    # second instance before the OS has fully reaped the first.
    _pid_guard = PidFile()
    try:
        _pid_guard.acquire()
    except RuntimeError as _pe:
        print(f"[STARTUP] {_pe}")
        logger.error(f"[STARTUP] {_pe}")
        return
    import atexit as _atexit
    _atexit.register(_pid_guard.release)

    # CY12-INIT-DB-WRAP fix (full audit 2026-05-29 resilience M-RES-3):
    # pre-fix init_db() / restore_cooldowns() raised on disk-full or
    # permission errors with NO Telegram alert — systemd Restart=always
    # then crash-looped silently and the operator never knew until the
    # watchdog freeze alert fired (10+ min). Now any boot-time DB failure
    # emits a CRITICAL Telegram before the process exits, so the operator
    # has actionable diagnosis instead of "bot stopped, no idea why".
    try:
        init_db()
        restore_cooldowns()
    except Exception as _init_e:
        _crit_msg = (f"<b>BOT BOOT FAILURE</b>\n\n"
                     f"init_db() or restore_cooldowns() raised: "
                     f"<code>{_h(type(_init_e).__name__)}</code>\n"
                     f"<code>{_h(str(_init_e)[:300])}</code>\n\n"
                     f"<i>Bot cannot start. Common causes: disk full, "
                     f"signals.db corrupt, file permissions wrong, "
                     f"WAL lock not released. systemd will Restart=always, "
                     f"which will crash-loop until you fix the underlying "
                     f"problem. ssh to VPS and check `df -h`, "
                     f"`ls -la data/signals.db*`, and journalctl -u tradeai.</i>")
        try:
            send_telegram(_crit_msg)
        except Exception:
            pass
        # Re-raise so systemd sees the non-zero exit + journalctl shows it
        raise

    # H24: LIVE MODE alert moved to after init_db() + restore_cooldowns() so the operator
    # is only notified when the bot is fully ready — not before DB init can fail.
    if EXECUTION_MODE == "LIVE":
        send_telegram(
            "<b>LIVE MODE ACTIVATED</b>\n\n"
            "Real-money trading is now running.\n\n"
            "To return to paper trading, set "
            "<code>EXECUTION_MODE=PAPER</code> and restart the bot."
        )

    # ── Restore persisted scalar state (Phase 3) ─────────
    global _signal_threshold_adj, _conf_floor
    _signal_threshold_adj = load_scalar_state("threshold_adj", default=0)
    _conf_floor           = load_scalar_state("conf_floor",    default=1)
    if _signal_threshold_adj != 0 or _conf_floor != 1:
        print(f"[STATE] Restored — threshold_adj={_signal_threshold_adj:+d}  "
              f"conf_floor={_conf_floor}")

    # ── [DRIFT-GATE] DriftDetector ADX threshold divergence monitor ──────
    # Warn if any token's live adx_trend has drifted >±5.0 from the backtest
    # static baseline of 25.0. This is NOT a block — visibility only.
    # Backtest always uses static thresholds (see backtest.py detect_regime()).
    _BACKTEST_ADX_BASELINE = 25.0
    _DRIFT_GATE_TOLERANCE  = 5.0
    _drift_warnings = []
    for _tok in BINANCE_TOKENS:
        try:
            _thr = drift_detector.get_dynamic_thresholds(_tok)
            _live_adx = _thr["adx_trend_threshold"]
            _delta = _live_adx - _BACKTEST_ADX_BASELINE
            if abs(_delta) > _DRIFT_GATE_TOLERANCE:
                _msg = (f"[DRIFT-GATE] {_tok}: live adx_trend={_live_adx} "
                        f"(delta {_delta:+.1f} from backtest baseline 25.0) — "
                        f"regime classification may diverge from backtest")
                logger.warning(_msg)
                print(_msg)
                # Mirror the warning into the dashboard activity feed so
                # the operator sees the startup drift state alongside the
                # cycle activity, in plain English. Fired once per restart;
                # never spams during normal cycles.
                _trend_note = "calmer" if _delta < 0 else "trendier"
                print(f"[ACTIVITY] {_tok}: regime drift — market is {_trend_note} "
                      f"than backtest baseline (ADX delta {_delta:+.1f})")
                _drift_warnings.append(f"{_tok}: adx_trend={_live_adx} ({_delta:+.1f})")
        except Exception as _e:
            logger.warning(f"[DRIFT-GATE] Could not read threshold for {_tok}: {_e}")
    _drift_note = ""
    if _drift_warnings:
        # 2026-05-28 — translate jargon into plain operator-readable English.
        # ADX < baseline = markets calmer/less-trending than the historical
        # period the strategy was tuned on. Not a block, just FYI.
        _avg_delta = sum(float(w.split('(')[1].split(')')[0]) for w in _drift_warnings) / len(_drift_warnings)
        if _avg_delta < 0:
            _drift_note = (f"Markets are quieter than usual right now "
                           f"(avg ADX {_avg_delta:+.1f} vs the historical baseline of 25). "
                           f"Expect fewer/slower signals — not a problem, just heads-up.")
        else:
            _drift_note = (f"Markets are more volatile than usual right now "
                           f"(avg ADX {_avg_delta:+.1f} vs the historical baseline of 25). "
                           f"Expect more/faster signals — not a problem, just heads-up.")

    print("="*58)
    print("  CRYPTO SIGNAL BOT v13 — ICT MODE")
    print("  Phase 4.1 ICT Liquidity Sweep + MSS + FVG")
    print("="*58)
    print(f"  Tokens:    {', '.join(BINANCE_TOKENS.keys())}")
    print(f"  Profile:   Active Day Trader / Scalper")
    print(f"  TF Stack:  1H trend → 15M entry → 5M confirm")
    print(f"  Targets:   SL ≤1.5% | TP scalp zones | Expiry 2-4H")
    print(f"  Scoring:   Weighted 0-100% (threshold {SIGNAL_THRESHOLD}%)")
    print(f"  Cooldown:  {SIGNAL_COOLDOWN} min per direction per token")
    print(f"  DB:        {DB_PATH}")
    print("="*58)
    print(weight_engine.summary())
    _tokens_str = " ".join(BINANCE_TOKENS.keys())
    _drift_note_clean = _drift_note.strip()
    # CRT-aware startup message (telegram audit 2026-05-27 — C-1 followup):
    # The old "ICT mode" title + 5M_SWEEP-only strategy line was misleading
    # under the operator's current CRT-only config. Now reflects which
    # scanner(s) are actually active so the operator's startup notification
    # matches the bot's runtime behavior.
    _5m_on  = bool(ENABLE_5M_SWEEP)
    _crt_on = bool(ENABLE_H4_CRT)
    if _5m_on and _crt_on:
        _mode_title    = "DUAL mode (5M_SWEEP + H4_CRT)"
        _strategy_line = "5M_SWEEP + H4_CRT (parallel scanners)"
    elif _crt_on and not _5m_on:
        _mode_title    = "CRT-only mode"
        _strategy_line = "H4 Candle Range Theory (CRT)"
    elif _5m_on and not _crt_on:
        _mode_title    = "ICT mode (5M_SWEEP)"
        _strategy_line = "ICT sweep + MSS + FVG retracement"
    else:
        # Both off — bot will emit zero signals; surface this as a warning
        _mode_title    = "ALL SCANNERS DISABLED"
        _strategy_line = "WARNING: ENABLE_5M_SWEEP=0 AND ENABLE_H4_CRT=0 — no signals will fire"

    # ── 2026-05-28 STARTED-message redesign (operator request) ──
    # Replace the dense <pre> table + raw DRIFT-GATE warnings with a clean,
    # operator-readable status card. Keep only what's useful at startup:
    # mode/scanner state, position + WR continuity, adaptive learning
    # health, the most-tuned CRT knobs, and a plain-English market note.

    # Adaptive learning health — count live-weighted vs bootstrap tokens
    try:
        _w_keys = list(weight_engine._weights.keys())
        _w_live = sorted(t for t in _w_keys if weight_engine._n.get(t, 0) > 0)
        _w_boot = sorted(t for t in _w_keys if weight_engine._n.get(t, 0) == 0)
    except Exception:
        _w_live, _w_boot = [], []

    # State continuity at restart — open positions + WR resumed
    try:
        _port_st  = portfolio_layer.get_status()
        _open_now = _port_st.get("total_open", 0)
    except Exception:
        _open_now = 0
    try:
        _wr_live = get_actual_win_rate()
        _closed_n = _wr_live and 1  # placeholder for closed-count if we have it
    except Exception:
        _wr_live = 0.0
    try:
        import sqlite3 as _sql
        _c = _sql.connect(DB_PATH); _c.row_factory = _sql.Row
        _closed_n = _c.execute(
            "SELECT COUNT(*) FROM results WHERE result IN "
            "('WIN','LOSS','PARTIAL_TP1','PARTIAL_TP2','PARTIAL_TP3')"
        ).fetchone()[0]
        _c.close()
    except Exception:
        _closed_n = 0

    # CRT key knobs — only when CRT is the active source
    _crt_summary = ""
    if _crt_on:
        try:
            from crt_engine import CRT_TP1_MODE as _ctm, WYCKOFF_PHASE_FILTER as _wpf
            _bias = getattr(__import__('config'), 'LIVE_BIAS_4H_GATE', 'none')
            _crt_summary = (
                "\n\n⚙️ <b>Active CRT settings:</b>"
                f"\n• TP1 mode: <b>{_h(_ctm)}</b>"
                f"\n• Wyckoff filter: <b>{_h(_wpf)}</b>"
                f"\n• 4H bias gate: <b>{_h(_bias)}</b>"
            )
        except Exception:
            pass

    _adaptive_line = ""
    if _w_live or _w_boot:
        _adaptive_line = "\n\n\U0001F9E0 <b>Adaptive learning:</b>"
        if _w_live:
            _adaptive_line += (
                f"\n• Live ({len(_w_live)}): {_h(', '.join(_w_live))}"
            )
        if _w_boot:
            _adaptive_line += (
                f"\n• Warming up ({len(_w_boot)}): {_h(', '.join(_w_boot))}"
            )

    _wr_line = (
        f"\n\U0001F3AF <b>Win rate so far:</b> {_wr_live:.0%}  "
        f"({_closed_n} closed signal{'s' if _closed_n != 1 else ''})"
        if _closed_n > 0 else
        "\n\U0001F3AF <b>Win rate so far:</b> waiting for first closed signal"
    )

    # 2026-05-28 — operator template (image reference): card-style with
    # unicode-line dividers between sections, emoji + bold section headers,
    # 2-column token grid in <pre> (monospace alignment unavailable elsewhere
    # in Telegram HTML — small block, not a dense data table).

    _hr = _TG_HR  # shared divider — see module-level _TG_HR definition

    # Token list — single comma-separated line (matches the Adaptive Learning
    # "Live (n): A, B, C" style). Drops both the <pre> copy affordance and
    # the 10-line vertical bullet list per operator preference (2026-05-28).
    _tokens_inline = ", ".join(BINANCE_TOKENS.keys())

    # Adaptive learning block — render as bullets under a section header
    _adaptive_block = ""
    if _w_live or _w_boot:
        _adaptive_block = f"\n\n{_hr}\n\n\U0001F48E <b>Adaptive Learning</b>\n"
        if _w_live:
            _adaptive_block += (
                f"\n✅ <b>Live ({len(_w_live)}):</b> {_h(', '.join(_w_live))}"
            )
        if _w_boot:
            _adaptive_block += (
                f"\n⏳ <b>Warming Up ({len(_w_boot)}):</b> "
                f"{_h(', '.join(_w_boot))}"
            )

    # Status section — open positions + WR + closed-signal count
    _status_block = (
        f"\n\n{_hr}\n\n\U0001F4CA <b>Status</b>\n"
        f"\n\U0001F4CB <b>Open Positions Resumed:</b> {_h(_open_now)} / "
        f"{_h(MAX_OPEN_POSITIONS)}"
    )
    if _closed_n > 0:
        _status_block += (
            f"\n\U0001F3AF <b>Win Rate So Far:</b> {_wr_live:.0%}"
            f"\n\U0001F4CC <b>Closed Signals:</b> {_h(_closed_n)}"
        )
    else:
        _status_block += (
            "\n\U0001F3AF <b>Win Rate So Far:</b> waiting for first closed signal"
        )

    # CRT settings section — only when CRT is the active source
    _crt_block = ""
    if _crt_on:
        try:
            from crt_engine import CRT_TP1_MODE as _ctm, WYCKOFF_PHASE_FILTER as _wpf
            _bias = getattr(__import__('config'), 'LIVE_BIAS_4H_GATE', 'none')
            _crt_block = (
                f"\n\n{_hr}\n\n⚙️ <b>Active CRT Settings</b>\n"
                f"\n• <b>TP1 Mode:</b> {_h(_ctm)}"
                f"\n• <b>Wyckoff Filter:</b> {_h(str(_wpf).upper())}"
                f"\n• <b>4H Bias Gate:</b> {_h(str(_bias).upper())}"
            )
        except Exception:
            pass

    # Market notice — translated DRIFT-GATE warning
    _notice_block = ""
    if _drift_note_clean:
        _notice_block = (
            f"\n\n{_hr}\n\n⚠️ <b>Market Notice</b>\n"
            f"\n<i>{_h(_drift_note_clean)}</i>"
        )

    send_telegram(
        f"\U0001F680 <b>BOT STARTED — {_h(_mode_title)}</b>\n"
        f"\n⚙️ <b>Mode:</b> {_h(EXECUTION_MODE)}"
        f"\n\U0001F300 <b>Strategy:</b> {_h(_strategy_line)}"
        f"\n\n{_hr}\n\n\U0001F4D4 <b>Tokens Watched ({_h(len(BINANCE_TOKENS))}):</b>\n"
        + _h(_tokens_inline)
        + _adaptive_block
        + _status_block
        + _crt_block
        + _notice_block
    )
    load_performance_state()
    # M26: Pre-flight Binance connectivity check — abort before entering the main loop
    # if the API is unreachable. Without this, the stale-gate bypasses when
    # last_fetched_at==0.0, generate_signal() runs on empty STATE, and the hourly
    # heartbeat fires "Bot alive" throughout a total outage.
    try:
        _pf = requests.get(f"{BINANCE_BASE}/ping", headers=HEADERS, timeout=5)
        _pf.raise_for_status()
        print("[PREFLIGHT] Binance connectivity OK")
    except Exception as _pfe:
        _pf_msg_plain = f"TradeAI STARTUP FAILED - Binance unreachable: {_pfe}"
        print(f"[PREFLIGHT] {_pf_msg_plain}")
        try:
            send_telegram(
                "<b>TradeAI STARTUP FAILED</b>\n\n"
                "Cannot reach Binance API. The bot will exit.\n\n"
                "<pre>"
                f"Error: {_h(_pfe)}"
                "</pre>\n"
                "Check VPN, network, or Binance API status, then restart with:\n"
                "<code>sudo systemctl restart tradeai</code>"
            )
        except Exception:
            pass
        return
    # ── Dead-man's switch (Phase A-1) ────────────────────
    # Heartbeat file + multi-channel alerter. The bot writes a liveness file
    # every cycle; an external watchdog (scripts/watchdog.py) polls it and
    # alerts on staleness. The MultiChannelAlerter falls back to SMTP if the
    # primary Telegram path fails, and self-tests both channels every ~24h.
    _hb_alerter = MultiChannelAlerter(primary_send=send_telegram)
    _heartbeat = Heartbeat(
        alerter=_hb_alerter,
        load_counter=lambda: load_scalar_state("hb_selftest_counter", default=0),
        save_counter=lambda v: save_scalar_state("hb_selftest_counter", v),
    )
    # CY12-SIGNAL-SMTP fix: wire the alerter as the module-global so
    # send_signal_msg can route through it (SMTP fallback for signals).
    global _signal_alerter
    _signal_alerter = _hb_alerter
    if not _hb_alerter.secondary_configured:
        logger.warning(
            "[ALERT] SMTP secondary channel not configured — "
            "operator only has Telegram (set SMTP_HOST/PORT/USER/PASS/TO env vars to enable)."
        )

    # ── Atomic process-state store (Phase A-2) ───────────
    # Persists cycle counter, consecutive-error count, and heartbeat timestamps
    # so a crash + supervisord restart resumes with correct counters instead of
    # cold-zeroed values (which would, for example, suppress the next error alert).
    _state_store = StateStore()
    _persisted = _state_store.load(defaults={
        "cycle": 0,
        "consecutive_errors": 0,
        "last_heartbeat_ts": 0.0,
        "last_cycle_ts_unix": 0.0,
        "restart_count": 0,
        # CRT v1 Session 3 (LBC-H-2 fix): per-token consumed_h4_crt sets
        # serialized as {token: [[c1_time, c1_high, c1_low], ...]}. Reloaded
        # into STATE[token]["consumed_h4_crt"] below so mitigation memory
        # survives bot restart.
        "consumed_h4_crt": {},
    })
    _persisted["restart_count"] = int(_persisted.get("restart_count", 0)) + 1
    _state_store.save(_persisted)
    if _persisted["cycle"] > 0:
        print(f"[STATE] Resumed from previous run — cycle={_persisted['cycle']} "
              f"consecutive_errors={_persisted['consecutive_errors']} "
              f"restart#{_persisted['restart_count']}")

    # CRT v1 Session 3 (LBC-H-2 fix): rehydrate per-token consumed_h4_crt sets
    # from the state_store snapshot. Stored as lists of 3-tuples; converted
    # back to sets of tuples here. Bad/missing entries fail silently to empty
    # set per token — defensive against state_store corruption.
    _ch4 = _persisted.get("consumed_h4_crt", {}) or {}
    for _tok, _entries in _ch4.items():
        if _tok in STATE and isinstance(_entries, list):
            try:
                STATE[_tok]["consumed_h4_crt"] = {
                    tuple(e) for e in _entries
                    if isinstance(e, (list, tuple)) and len(e) == 3
                }
            except Exception:
                STATE[_tok]["consumed_h4_crt"] = set()
    _rehydrated = sum(len(STATE[t].get("consumed_h4_crt", set()))
                      for t in BINANCE_TOKENS)
    if _rehydrated > 0:
        print(f"[STATE] Rehydrated {_rehydrated} mitigated CRT zones across "
              f"{sum(1 for t in BINANCE_TOKENS if STATE[t].get('consumed_h4_crt'))} tokens")

    current_prices={}
    cycle = int(_persisted.get("cycle", 0))
    _last_perf_load=time.time()
    _consecutive_errors = int(_persisted.get("consecutive_errors", 0))
    _DRIFT_PERSIST_EVERY = 6  # persist drift windows every 6 cycles (~30 min)
    # Resume last_heartbeat from disk so restart-storms don't spam the operator
    # with hourly heartbeats. If never persisted, fall back to firing on cycle 1.
    _persisted_hb = float(_persisted.get("last_heartbeat_ts", 0.0))
    _last_heartbeat = _persisted_hb if _persisted_hb > 0 else time.time() - HEARTBEAT_INTERVAL
    while True:
        try:
            start=time.time(); cycle+=1
            _tokens_scanned = len(BINANCE_TOKENS)
            _tokens_fetched_ok = 0   # M-CY15-3: per-cycle fetch attestation
            print(f"\n[{datetime.now().strftime('%H:%M')}] === Cycle {cycle} ===")
            print(f"[ACTIVITY] === Cycle {cycle} start — scanning {_tokens_scanned} tokens for setups ===")
            if time.time() - _last_perf_load >= PERF_CHECK_INTERVAL:
                load_performance_state(); _last_perf_load = time.time()
                # R6 fix (master audit 2026-05-26): event-driven decay replaces
                # the prior wall-clock cron (which decayed every 30 min whether
                # or not signals were happening). `apply_decay_if_due()` scales
                # decay to actual elapsed time, is rate-limited internally
                # (default 30-min min_interval), respects the 7-day post-OGD
                # suppression guard, and persists last_decay_time to bot_state
                # so restart survival is correct.
                for _decay_tok in BINANCE_TOKENS:
                    weight_engine.apply_decay_if_due(_decay_tok)
                print(weight_engine.summary())
            for token in BINANCE_TOKENS:
                print(f"  Fetching {token}...")
                pd=update_token_state(token)
                if pd.get("price"):
                    current_prices[token]=pd["price"]
                    _tokens_fetched_ok += 1   # M-CY15-3: count successful fetch
                # Persist drift windows periodically
                if cycle % _DRIFT_PERSIST_EVERY == 0:
                    drift_detector.persist(token)
            print("  Fetching BTC filter data...")
            fetch_btc_state()
            maybe_send_daily_summary(current_prices)
            monitor_open_signals(current_prices)
            _consecutive_errors = 0   # reset on successful cycle
            # ── Dead-man's switch liveness file (Phase A-1) ───────
            # Written every cycle so the external watchdog (scripts/watchdog.py)
            # can detect process death within HEARTBEAT_STALENESS_SEC.
            try:
                _port_st = portfolio_layer.get_status()
                _heartbeat.beat(
                    cycle=cycle,
                    open_signals=_port_st["total_open"],
                    threshold_adj=_signal_threshold_adj,
                    consecutive_errors=_consecutive_errors,
                    # M-CY15-3: per-cycle token-fetch attestation. Without this,
                    # silent geo-blocking of a few symbols (Binance regional ban
                    # mid-session) would never trigger the watchdog because the
                    # heartbeat would keep updating from the surviving fetches.
                    tokens_scanned=_tokens_scanned,
                    tokens_fetched_ok=_tokens_fetched_ok,
                )
            except Exception as _hbe:
                logger.error(f"[HEARTBEAT] beat failed: {_hbe}")

            # ── Hourly Telegram heartbeat (operator-visible) ──────
            if time.time() - _last_heartbeat >= HEARTBEAT_INTERVAL:
                wr_live  = get_actual_win_rate()
                port_st  = portfolio_layer.get_status()
                open_cnt = port_st["total_open"]
                eff_thr  = SIGNAL_THRESHOLD + _signal_threshold_adj
                # CRT-aware heartbeat (telegram audit 2026-05-27 — C-1 followup):
                # surface scanner state so operator sees at a glance which
                # source(s) the bot is currently watching for signals.
                _hb_scanners = (
                    ("5M_SWEEP" if ENABLE_5M_SWEEP else "") +
                    (("+" if ENABLE_5M_SWEEP and ENABLE_H4_CRT else "") +
                     ("H4_CRT" if ENABLE_H4_CRT else ""))
                ) or "DISABLED"
                _hb_alerter.send(
                    "Heartbeat",
                    "\U0001F49A <b>Heartbeat BOT ALIVE</b>\n"
                    f"\n{_TG_HR}\n"
                    f"\n⏰ <b>Time:</b> {_h(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'))} UTC"
                    f"\n\U0001F501 <b>Cycle:</b> {_h(cycle)}"
                    f"\n⚙️ <b>Mode:</b> {_h(EXECUTION_MODE)}"
                    f"\n\U0001F4E1 <b>Scanners:</b> {_h(_hb_scanners)}"
                    f"\n\U0001F4CA <b>Open positions:</b> {_h(open_cnt)} / {_h(MAX_OPEN_POSITIONS)}"
                    f"\n\U0001F3AF <b>Win rate:</b> {wr_live:.0%}"
                    f"\n\U0001F6AA <b>Threshold:</b> {_h(eff_thr)}%",
                )
                _last_heartbeat = time.time()
            for token in BINANCE_TOKENS:
                price=current_prices.get(token,0.0)
                if price<=0: continue
                _age = time.time() - STATE[token].get("last_fetched_at", 0.0)
                _5m_age = time.time() - STATE[token].get("last_5m_fetched_at", 0.0)
                if STATE[token].get("last_fetched_at", 0.0) > 0 and _age > STALE_CANDLE_THRESHOLD:
                    print(f"[STALE] {token}: candles {_age:.0f}s old (>{STALE_CANDLE_THRESHOLD}s) — skipping signal")
                    continue
                if STATE[token].get("last_5m_fetched_at", 0.0) > 0 and _5m_age > STALE_CANDLE_THRESHOLD:
                    print(f"[STALE-5M] {token}: 5m candles {_5m_age:.0f}s old (>{STALE_CANDLE_THRESHOLD}s) — skipping signal")
                    continue
                pd=STATE[token].get("last_24h", {})   # reuse cached data — no extra fetch
                ch24=pd.get("change_24h",0.0); vol24=pd.get("volume_24h",0.0)
                # ── 5M_SWEEP scanner (Run-168 canonical baseline) ─────────
                # Per-scanner kill switch: ENABLE_5M_SWEEP=0 (env) disables
                # the original 5M-sweep detection path so operator can run
                # CRT-only paper trades. Default ON. The CRT scanner below
                # is gated independently by ENABLE_H4_CRT.
                if ENABLE_5M_SWEEP:
                    result,regime=generate_signal(token,price,ch24,vol24)
                    if result:
                        plan=result["plan"]
                        sig_id=save_signal(token,price,result,plan,regime)
                        if sig_id < 0:
                            print(f"[ERROR] {token} signal DB save failed — no Telegram sent")
                            continue
                        # Phase 5A: suppress Telegram in LIVE mode when template blocks live execution
                        if EXECUTION_MODE == "LIVE" and not result.get("template_live_allowed", 0):
                            print(f"[PHASE5A] LIVE BLOCK: {token} {result['signal']} "
                                  f"template={result.get('matched_template_id','NONE')} "
                                  f"status={result.get('template_status','?')} "
                                  f"reason={result.get('template_block_reason','')} — signal saved, no Telegram")
                        else:
                            send_signal_msg(token,price,ch24,result,plan,sig_id,regime)

                # CRT v1 Session 3 (audit cycle-7 2026-05-27): parallel H4-CRT
                # scan path. No-op when ENABLE_H4_CRT=0 (default — production
                # behavior unchanged). When enabled, emits source='H4_CRT'
                # signals alongside the canonical 5M_SWEEP path above.
                # Uses STATE[token]["consumed_h4_crt"] (persisted across
                # restarts via state_store) for one-shot mitigation.
                if ENABLE_H4_CRT:
                    # M-NEW-5 fix (cycle-9 audit 2026-05-28): per-TF stale
                    # guard for the CRT path. The 5M scanner already has its
                    # stale gate at line 3996; the CRT path consumes 4H +
                    # 1H directly so it needs its own. Without this, a frozen
                    # 4H candle stream (5M fetches succeed, 4H fails) would
                    # still let CRT signals fire from stale H4 data.
                    _4h_age = time.time() - STATE[token].get("last_4h_fetched_at", 0.0)
                    if STATE[token].get("last_4h_fetched_at", 0.0) > 0 and _4h_age > STALE_CANDLE_THRESHOLD:
                        print(f"[STALE-4H] {token}: 4h candles {_4h_age:.0f}s old "
                              f"(>{STALE_CANDLE_THRESHOLD}s) — skipping CRT scan")
                        continue
                    # M10-8 fix (cycle-10 audit 2026-05-28): 4H candle gap
                    # guard. The 5M_SWEEP path has this at line 2663; CRT
                    # did not. Without it, a 4H fetch that returned with
                    # gaps (e.g. Binance partial response) would feed CRT
                    # detection a discontinuous H4 stream → false C1/C2
                    # relationships. ≥1 bar gap is enough to corrupt the
                    # 2-bar CRT pattern.
                    if STATE[token].get("data_gap_bars_4h", 0) >= 1:
                        print(f"[SKIP-GAP-4H] {token}: 4H data gap "
                              f"{STATE[token]['data_gap_bars_4h']} bars — skipping CRT scan")
                        continue
                    # M-CY11-3 fix (audit 2026-05-28 cycle-11): 1H stale +
                    # gap guard for CRT scan path. CRT_REQUIRE_1H_TREND=1 is
                    # active in operator's Run-338 .env, making 1H trend a
                    # live signal gate. Pre-fix the CRT scan trusted whatever
                    # was in c1h_live without a freshness check; a stale or
                    # gap-corrupted 1H stream silently produced NEUTRAL (the
                    # gate's permissive default), letting signals through
                    # that should have been blocked. Mirrors the 4H guards
                    # immediately above and the 5M_SWEEP path's 1H guards
                    # at crypto_alert.py:2714.
                    _1h_age = time.time() - STATE[token].get("last_1h_fetched_at", 0.0)
                    if STATE[token].get("last_1h_fetched_at", 0.0) > 0 and _1h_age > STALE_CANDLE_THRESHOLD:
                        print(f"[STALE-1H] {token}: 1h candles {_1h_age:.0f}s old "
                              f"(>{STALE_CANDLE_THRESHOLD}s) — skipping CRT scan")
                        continue
                    if STATE[token].get("data_gap_bars_1h", 0) >= 2:
                        print(f"[SKIP-GAP-1H] {token}: 1H data gap "
                              f"{STATE[token]['data_gap_bars_1h']} bars — skipping CRT scan")
                        continue
                    _c5m = STATE[token]["candles"]["5m"]
                    _c4h = STATE[token]["candles"]["4h"]
                    _c1h_live = STATE[token]["candles"].get("1h", {})
                    if _c5m and _c4h and len(_c5m.get("closes", [])) > 30 \
                            and len(_c4h.get("closes", [])) > H4_CRT_C2_LOOKBACK + 2:
                        # CRITICAL P1 fix (audit 2026-05-27 cycle-8):
                        #   C-1: candle-key shape mismatch (3 agents converged).
                        #        fetch_binance_candles returns dict keyed "timestamps"
                        #        (plural). crt_engine.detect_h4_crt requires "times"
                        #        (singular) and silently returns None on mismatch.
                        #        Result: 0 CRT signals fired in 28h+ of paper soak.
                        #   C-2: forming-bar repaint. 5M_SWEEP path applies [:-1] to
                        #        drop the in-progress bar (crypto_alert.py:2450-2454);
                        #        CRT path passed the raw STATE candles → the live
                        #        4H + 5M arrays included a non-closed bar at [-1] →
                        #        repaint violation + live/BT divergence.
                        # Build NEW dicts (don't mutate STATE — other code paths may
                        # rely on it). Strip forming bar from all OHLCV+time arrays.
                        def _crt_closed_only(src_dict):
                            """Return a copy keyed for crt_engine ('times' present)
                            with the trailing forming bar removed from every series."""
                            if not src_dict:
                                return {}
                            # Source candles use 'timestamps'; crt_engine wants 'times'
                            _ts_src = src_dict.get("times") or src_dict.get("timestamps") or []
                            return {
                                "opens":  src_dict.get("opens",  [])[:-1],
                                "highs":  src_dict.get("highs",  [])[:-1],
                                "lows":   src_dict.get("lows",   [])[:-1],
                                "closes": src_dict.get("closes", [])[:-1],
                                "times":  list(_ts_src)[:-1],
                            }
                        _c5m_closed = _crt_closed_only(_c5m)
                        _c4h_closed = _crt_closed_only(_c4h)
                        # Initialize defensive defaults so the downstream
                        # `if _crt_result is not None:` is safe even if the
                        # post-slice length check below skips the scan call.
                        _crt_result, _crt_plan, _crt_reason = None, None, "skipped_short_candles"
                        # Re-verify length AFTER the [:-1] slice so we don't fall
                        # under the inner detect_h4_crt's >=30 / >H4_CRT_C2_LOOKBACK
                        # floor with the forming-bar removed.
                        if (len(_c5m_closed["closes"]) > 30
                                and len(_c4h_closed["closes"]) > H4_CRT_C2_LOOKBACK + 2):
                            # H-3 fix (audit cycle-8 2026-05-27): compute
                            # per-token 1H trend directly from the cached
                            # 1H candles. Previously read STATE[token]["trend_1h"]
                            # which is ONLY populated by the 5M_SWEEP path
                            # (generate_signal) — when ENABLE_5M_SWEEP=0 the
                            # value defaulted to "NEUTRAL" forever, breaking
                            # both the CRT_REQUIRE_1H_TREND gate AND OGD's
                            # trend_strength feature attribution.
                            # L-NEW-3 fix (cycle-9 audit 2026-05-28): exclude
                            # the forming 1H bar before calling get_trend.
                            # Pre-fix the in-progress bar (which can repaint
                            # at any tick) was included, so during the first
                            # ~10 min of each H1 the trend could flip BULL↔BEAR
                            # mid-cycle. Mirrors the [:-1] discipline used
                            # everywhere else closed-only logic is required.
                            _c1h_closes = _c1h_live.get("closes", []) if _c1h_live else []
                            _c1h_closed_only = _c1h_closes[:-1] if len(_c1h_closes) > 1 else _c1h_closes
                            _crt_trend_1h = get_trend(_c1h_closed_only) if _c1h_closed_only else "NEUTRAL"
                            # Cache it back to STATE so other code paths
                            # (e.g. dashboard, Telegram render) see the real
                            # value too (was None / missing).
                            STATE[token]["trend_1h"] = _crt_trend_1h
                            # F-1 (2026-05-28): pass BTC 5M cache so SMT
                            # divergence is computed for CRT signals (was
                            # hardcoded NONE/False pre-fix).
                            #
                            # M10-2 fix (cycle-10 audit 2026-05-28): when
                            # `token == 'BTC'` pass None — SMT divergence
                            # against self is meaningless and produces
                            # spurious confirmations. Mirrors the backtest
                            # guard at backtest.py:3788.
                            if token == "BTC":
                                _btc_c5m_for_smt = None
                            else:
                                _btc_c5m_raw = (
                                    STATE["BTC"]["candles"].get("5m", {})
                                    if "BTC" in STATE
                                       and STATE["BTC"]["candles"].get("5m", {}).get("highs")
                                    else BTC_STATE.get("candles", {}).get("5m", {})
                                )
                                # CY12-BTC-CORR-KEY fix (full audit 2026-05-29
                                # data-pipeline HIGH): fetch_binance_candles
                                # returns dict keyed "timestamps" (plural).
                                # Downstream BTC-correlation guard at line ~1143
                                # checks `.get("times")` (singular). Pre-fix the
                                # guard ALWAYS returned falsy → live T1.3
                                # correlation overlay silently inert
                                # (_btc_corr=None, _btc_corr_cls="UNKNOWN",
                                # bonus=0.0). Zero impact today at
                                # BTC_CORR_BONUS_PCT=0.0 but creates a
                                # live↔backtest parity gap the moment the
                                # explorer tunes the bonus non-zero. Mirror
                                # _crt_closed_only's translation: add a "times"
                                # alias pointing at the same list. NEW dict
                                # (don't mutate shared STATE).
                                if _btc_c5m_raw and "times" not in _btc_c5m_raw:
                                    _btc_ts = _btc_c5m_raw.get("timestamps", [])
                                    _btc_c5m_for_smt = dict(_btc_c5m_raw)
                                    _btc_c5m_for_smt["times"] = list(_btc_ts)
                                else:
                                    _btc_c5m_for_smt = _btc_c5m_raw
                            _crt_result, _crt_plan, _crt_reason = scan_h4_crt_for_token(
                                token, _c5m_closed, _c4h_closed,
                                consumed=STATE[token]["consumed_h4_crt"],
                                trend_1h=_crt_trend_1h,
                                btc_c5m=_btc_c5m_for_smt,
                            )
                            # [ACTIVITY] feed — plain-English per-token milestone print.
                            # Tracker dashboard tails bot.log for "[ACTIVITY]" lines and
                            # renders them in the Open Positions tab's live feed. Skip
                            # the most common silent case ("no_setup") so the rolling
                            # buffer fills with actionable events, not noise.
                            if _crt_reason and _crt_reason != "no_setup":
                                _act_msg = _crt_reason
                                if _crt_reason == "outside_killzone":
                                    _act_msg = "outside killzone (off-hours) — skipped"
                                elif _crt_reason == "bias_gate_blocked":
                                    _act_msg = f"setup found but 4H bias against direction — skipped"
                                elif _crt_reason == "1h_trend_blocked":
                                    _act_msg = "setup found but 1H trend against direction — skipped"
                                elif _crt_reason == "no_post_mss_bar":
                                    _act_msg = "trend shift at last 5M bar — waiting for next cycle"
                                elif _crt_reason.startswith("economics_"):
                                    _act_msg = f"setup found but risk/reward too weak ({_crt_reason[10:]}) — skipped"
                                elif _crt_reason.startswith("wyckoff_"):
                                    _act_msg = f"setup found but Wyckoff phase mismatch ({_crt_reason[8:]}) — skipped"
                                elif _crt_reason == "blacklisted":
                                    _act_msg = "token blacklisted from CRT — skipped"
                                print(f"[ACTIVITY] {token}: {_act_msg}")
                        if _crt_result is not None:
                            # GAP-CRT-2 fix (cycle-9 audit 2026-05-28):
                            # per-direction time cooldown. Mirrors the
                            # 5M_SWEEP gate at line 2854. Pre-fix: 2 TON SELL
                            # CRT signals fired 3 min apart (audit empirical
                            # evidence) because CRT didn't consult
                            # last_signal_times. Now matches the 30-min
                            # default + per-token per-direction granularity.
                            _crt_dir = _crt_result.get("signal")
                            _crt_last_t = STATE[token]["last_signal_times"].get(_crt_dir)
                            if _crt_last_t and (datetime.now(timezone.utc)
                                                - _crt_last_t).total_seconds() / 60 < SIGNAL_COOLDOWN:
                                print(f"[{datetime.now().strftime('%H:%M')}] "
                                      f"{token} CRT {_crt_dir} cooldown active "
                                      f"({SIGNAL_COOLDOWN}min from last) — skipping")
                                print(f"[ACTIVITY] {token}: signal cooldown active "
                                      f"({SIGNAL_COOLDOWN}min from last {_crt_dir}) — skipped")
                                continue
                            # H-1 fix (audit cycle-8 2026-05-27): apply the
                            # SAME risk gates the 5M_SWEEP path enforces at
                            # crypto_alert.py:2435 (kill switches) and
                            # crypto_alert.py:2742 (portfolio risk layer).
                            # Pre-fix: CRT signals bypassed BOTH gates →
                            # daily-loss circuit breaker, per-symbol post-loss
                            # cooldown, MAX_OPEN_POSITIONS, MAX_PORTFOLIO_RISK_PCT,
                            # and correlation guard all SILENTLY ignored for CRT.
                            # Silent in PAPER today; DANGEROUS the moment
                            # template_live_allowed=1 is ever flipped for CRT.
                            # Note: scan_h4_crt_for_token already added the
                            # zone's `key` to consumed (crypto_alert.py:1027)
                            # before returning result — so if these gates
                            # reject, the zone is ALREADY mitigated and won't
                            # re-fire on subsequent cycles.
                            #
                            # M-NEW-4 fix (cycle-9 audit 2026-05-28): also apply
                            # the macro event gate. Pre-fix, the CRT path
                            # never consulted MACRO_FILTER_ENABLED while the
                            # 5M_SWEEP path did at crypto_alert.py:2578 —
                            # FOMC/CPI/NFP windows would silently allow CRT
                            # signals through. Backtest asymmetry is
                            # intentional: backtest has no macro calendar
                            # lookup yet — see docs/LIVE_BACKTEST_PARITY_ROADMAP.md.
                            if MACRO_FILTER_ENABLED:
                                _macro_in, _macro_name = _is_macro_window(
                                    datetime.now(timezone.utc),
                                    pre_hours=MACRO_PRE_WINDOW_H,
                                    post_hours=MACRO_POST_WINDOW_H,
                                )
                                if _macro_in:
                                    if MACRO_ADVISORY_ONLY:
                                        print(f"[MACRO-ADVISORY] {token} CRT: near {_macro_name} — signal allowed (advisory mode)")
                                        print(f"[ACTIVITY] {token}: macro event {_macro_name} nearby — signal allowed (advisory)")
                                    else:
                                        print(f"[MACRO-BLOCK] {token} CRT: blocked near {_macro_name}")
                                        print(f"[ACTIVITY] {token}: macro event {_macro_name} nearby — signal blocked")
                                        continue
                            _crt_ks_ok, _crt_ks_reason = check_kill_switches(token)
                            if not _crt_ks_ok:
                                print(f"[{datetime.now().strftime('%H:%M')}] {token} CRT KILL SWITCH — {_crt_ks_reason}")
                                print(f"[ACTIVITY] {token}: safety kill switch fired — {_crt_ks_reason}")
                                continue
                            _crt_port_ok, _crt_port_reason, _crt_port_warnings = portfolio_layer.check(
                                token, _crt_result["signal"], RISK_PER_TRADE_PCT,
                            )
                            if not _crt_port_ok:
                                print(f"[{datetime.now().strftime('%H:%M')}] {token} CRT {_crt_result['signal']} BLOCKED — {_crt_port_reason}")
                                print(f"[ACTIVITY] {token}: portfolio risk gate blocked — {_crt_port_reason}")
                                continue
                            for _w in _crt_port_warnings:
                                print(f"[{datetime.now().strftime('%H:%M')}] [PORTFOLIO WARN] {token}: {_w}")
                            _crt_entry = _crt_result["entry_price"]
                            # CY12-REGIME fix (post explorer audit 2026-05-29):
                            # compute the real market regime BEFORE save_signal
                            # so the persisted CRT row has proper RANGING /
                            # TRENDING_BULL / TRENDING_BEAR / UNKNOWN classification.
                            # Pre-fix, every CRT signal was tagged regime=UNKNOWN
                            # at save time even though the M-CY11-1 fix had
                            # already plumbed a real-regime computation below
                            # (for Phase 5A only). Tracker's WIN RATE BY REGIME
                            # panel + AI Recommendations regime slicer collapsed
                            # all CRT into one bucket as a result. The compute
                            # is now lifted above save_signal and the same value
                            # is reused for Phase 5A — single source of truth.
                            try:
                                _crt_prior_drift = drift_detector.get_dynamic_thresholds(token)
                                _crt_drift_adx_thr = _crt_prior_drift["adx_trend_threshold"]
                                _crt_regime_full = get_regime_for_token(token, adx_trend=_crt_drift_adx_thr)
                                _crt_regime_lbl = _crt_regime_full.get("regime", "UNKNOWN")
                                _crt_regime_payload = {
                                    "regime":     _crt_regime_lbl,
                                    "adx":        _crt_regime_full.get("adx", 0),
                                    "efficiency": _crt_regime_full.get("efficiency", 0),
                                    "atr_ratio":  _crt_regime_full.get("atr_ratio", 0),
                                    "confidence": _crt_regime_full.get("confidence", 0),
                                }
                            except Exception:
                                _crt_regime_full = {}
                                _crt_drift_adx_thr = 25.0
                                _crt_regime_lbl = "UNKNOWN"
                                _crt_regime_payload = {
                                    "regime": "UNKNOWN", "adx": 0, "efficiency": 0,
                                    "atr_ratio": 0, "confidence": 0,
                                }
                            _crt_sig_id = save_signal(
                                token, _crt_entry,
                                _crt_result, _crt_plan,
                                _crt_regime_payload,
                            )
                            if _crt_sig_id < 0:
                                print(f"[ERROR] {token} H4-CRT signal DB save failed — no Telegram sent")
                            else:
                                # GAP-CRT-2 fix (cycle-9 audit 2026-05-28):
                                # update last_signal_times for cooldown so
                                # the next scan respects the gate at
                                # crypto_alert.py:~4180. Mirrors the
                                # 5M_SWEEP write at line 3045.
                                STATE[token]["last_signal_times"][_crt_dir] = datetime.now(timezone.utc)
                                # Phase B (2026-05-28): CRT now has tier
                                # classification, so the LIVE-block check
                                # mirrors the 5M_SWEEP path's
                                # template_live_allowed semantics. Tier A/B
                                # carries live_allowed=1; Tier C is paper-only.
                                # LIVE flip is still gated by EXECUTION_MODE
                                # (operator's manual env switch) and N≥30
                                # paper soak discipline.
                                #
                                # RISK-GAP-NEW-1 fix (cycle-10 audit
                                # 2026-05-28): pre-fix CRT only read the
                                # static template_live_allowed bit, BYPASSING
                                # Phase 5A's INSUFFICIENT_SAMPLE /
                                # CIRCUIT_BREAKER / DAILY_CAP gates that the
                                # 5M_SWEEP path enforces at line 3238. Now
                                # call evaluate_template_status() for CRT too
                                # so a LIVE flip with 0 closed CRT trades
                                # can't fire untested-tier signals.
                                _tmpl_id  = _crt_result.get("matched_template_id", "NONE")
                                # M-CY11-1 fix (audit 2026-05-28 cycle-11):
                                # actual regime now computed BEFORE save_signal
                                # by the CY12-REGIME fix (above) — Phase 5A
                                # reuses the same value via _crt_regime_lbl,
                                # single source of truth. Pre-CY12-REGIME this
                                # block re-computed regime separately, leaving
                                # the saved DB row at hardcoded UNKNOWN.
                                try:
                                    _conn_5a_crt = _connect()
                                    _crt_tmpl_status, _crt_tmpl_live_ok, _crt_tmpl_block_reason = \
                                        evaluate_template_status(_conn_5a_crt, _tmpl_id, _crt_regime_lbl)
                                    _conn_5a_crt.close()
                                except Exception as _e_5a_crt:
                                    _crt_tmpl_status       = "UNKNOWN_TEMPLATE"
                                    _crt_tmpl_live_ok      = False
                                    _crt_tmpl_block_reason = f"Phase 5A eval exception: {_e_5a_crt}"
                                print(f"[CRT-Phase5A] {token} {_crt_result['signal']} → {_tmpl_id} "
                                      f"status={_crt_tmpl_status} live_ok={_crt_tmpl_live_ok}"
                                      + (f" | {_crt_tmpl_block_reason}" if _crt_tmpl_block_reason else ""))
                                if EXECUTION_MODE == "LIVE" and not _crt_tmpl_live_ok:
                                    print(f"[CRT-Phase-B] LIVE BLOCK: {token} {_crt_result['signal']} "
                                          f"template={_tmpl_id} status={_crt_tmpl_status} "
                                          f"({_crt_tmpl_block_reason or 'paper-only'}) "
                                          f"— signal saved (sig_id={_crt_sig_id}), no Telegram")
                                else:
                                    # CY12-REGIME-TG fix (full audit 2026-05-29):
                                    # pre-fix the Telegram render was passed a
                                    # hardcoded UNKNOWN even though save_signal
                                    # received the real _crt_regime_payload —
                                    # operator's alert message showed UNKNOWN
                                    # while the DB had the correct regime. The
                                    # audit (3 agents convergent) flagged this
                                    # as the operator-visible defect of the
                                    # CY12-REGIME fix. Now the alert renders
                                    # whatever was persisted (RANGING /
                                    # TRENDING_BULL / TRENDING_BEAR / CHOPPY /
                                    # UNKNOWN per get_regime_for_token).
                                    send_signal_msg(token, price, ch24, _crt_result,
                                                    _crt_plan, _crt_sig_id,
                                                    _crt_regime_payload)
                                print(f"[CRT] EMIT {token} {_crt_result['signal']} "
                                      f"tier={_tmpl_id} ({_crt_result['sr_type']}, "
                                      f"conf={_crt_result['confidence']}) sig_id={_crt_sig_id}")
                                print(f"[ACTIVITY] {token}: SIGNAL FIRED — "
                                      f"{_crt_result['signal']} @ ${_crt_entry:.4f}, "
                                      f"confidence {_crt_result['confidence']}/10, "
                                      f"tier {_tmpl_id}")
            # [ACTIVITY] per-cycle compact snapshot — all 10 tokens on one line.
            # Replaces the always-empty "no setup" silence with a state-rich view.
            # Format: TOKEN(1H/4H/zones)  where:
            #   1H trend  — sBULL / BULL / NEUT / BEAR / sBEAR  (STATE[tok]["trend_1h"])
            #   4H bias   — BULL / BEAR / NEUT (computed on-the-fly from cached candles)
            #   zones     — consumed CRT mitigation set size (0 = no zones consumed)
            # Computed at end of cycle when STATE has the latest values from BOTH
            # scanners. Best-effort — never raises into the loop.
            try:
                _trend_short = {
                    "STRONG_BULL": "sBULL", "BULL": "BULL", "NEUTRAL": "NEUT",
                    "BEAR": "BEAR", "STRONG_BEAR": "sBEAR",
                }
                _bias_short = {"BULLISH": "BULL", "BEARISH": "BEAR", "NEUTRAL": "NEUT"}
                _tok_parts = []
                for _tok in BINANCE_TOKENS:
                    _tr1h = STATE[_tok].get("trend_1h", "NEUTRAL")
                    _tr1h_s = _trend_short.get(_tr1h, _tr1h[:5])
                    # 4H bias from cached candles (mirror live's scan_h4_crt_for_token
                    # 210-bar slice for live↔BT parity)
                    _c4h_closes = STATE[_tok]["candles"].get("4h", {}).get("closes", [])
                    if len(_c4h_closes) >= 200:
                        _N = min(len(_c4h_closes), 210)
                        _b4h = get_ict_4h_bias(
                            _c4h_closes[-_N:],
                            STATE[_tok]["candles"]["4h"]["highs"][-_N:],
                            STATE[_tok]["candles"]["4h"]["lows"][-_N:],
                        )
                    else:
                        _b4h = "NEUTRAL"
                    _b4h_s = _bias_short.get(_b4h, _b4h[:4])
                    _zones = len(STATE[_tok].get("consumed_h4_crt", set()))
                    _tok_parts.append(f"{_tok}({_tr1h_s}/{_b4h_s}/{_zones})")
                print(f"[ACTIVITY] Tokens: {' '.join(_tok_parts)}")
            except Exception as _act_e:
                # Snapshot is observability-only — never let it kill the cycle
                print(f"[ACTIVITY] (snapshot failed: {_act_e})")

            # [ACTIVITY] market-overlay summary — aggregates per-token funding
            # rate classification + BTC correlation classification across the
            # 10 tokens so the operator sees which structural overlays the
            # CRT engine considered this cycle. These values are already
            # computed inside scan_h4_crt_for_token at signal-emit time but
            # are silent on the no-setup path. Recompute here from the
            # cached funding (5-min TTL) + already-cached BTC candles —
            # cheap enough at end-of-cycle, never touches the hot loop.
            try:
                from funding_rate_client import (
                    get_funding_rate, classify_funding_extreme,
                    is_funding_fetch_failed,
                )
                from btc_correlation import (
                    compute_btc_correlation, classify_btc_corr,
                )
                _btc_raw_c5m = (
                    STATE["BTC"]["candles"].get("5m", {})
                    if "BTC" in STATE
                       and STATE["BTC"]["candles"].get("5m", {}).get("closes")
                    else BTC_STATE.get("candles", {}).get("5m", {})
                )
                _btc_5m_closes = _btc_raw_c5m.get("closes", [])
                _btc_5m_times  = (_btc_raw_c5m.get("times")
                                  or _btc_raw_c5m.get("timestamps") or [])
                # Strip BTC's forming bar to match the live BTC-corr path
                if len(_btc_5m_closes) > 1:
                    _btc_5m_closed = _btc_5m_closes[:-1]
                else:
                    _btc_5m_closed = _btc_5m_closes
                # Bucket-counts so the line stays compact
                _fund_buckets = {"EXTREME": 0, "NEUT": 0, "FAIL": 0, "DIS": 0}
                _corr_buckets = {"ALIGNED_H": 0, "ALIGNED_L": 0, "DIVERG": 0,
                                 "AMBIG": 0, "UNK": 0}
                for _tok in BINANCE_TOKENS:
                    # Funding side — cached 5min so re-call is essentially free
                    try:
                        _fr = get_funding_rate(_tok)
                        _ff = is_funding_fetch_failed(_tok)
                        _fc = classify_funding_extreme(_fr, "BUY",
                                                        fetch_failed=_ff)
                        # Aggregate the 5 raw classifications into 4 buckets
                        if _fc.startswith("EXTREME"):
                            _fund_buckets["EXTREME"] += 1
                        elif _fc == "FETCH_FAILED":
                            _fund_buckets["FAIL"] += 1
                        elif _fc == "DISABLED":
                            _fund_buckets["DIS"] += 1
                        else:
                            _fund_buckets["NEUT"] += 1
                    except Exception:
                        _fund_buckets["FAIL"] += 1
                    # BTC correlation side — skip BTC vs itself
                    if _tok == "BTC":
                        continue
                    try:
                        _tok_c5m = STATE[_tok]["candles"].get("5m", {})
                        _tok_closes = _tok_c5m.get("closes", [])
                        if _tok_closes and _btc_5m_closed:
                            _corr = compute_btc_correlation(
                                _btc_5m_closed, _tok_closes, window=60,
                            )
                            _tr1h_tok = STATE[_tok].get("trend_1h", "NEUTRAL")
                            _cc = classify_btc_corr(_corr, "BUY", _tr1h_tok)
                            if _cc == "ALIGNED_HIGH":
                                _corr_buckets["ALIGNED_H"] += 1
                            elif _cc == "ALIGNED_LOW":
                                _corr_buckets["ALIGNED_L"] += 1
                            elif _cc == "DIVERGENT":
                                _corr_buckets["DIVERG"] += 1
                            elif _cc == "AMBIGUOUS":
                                _corr_buckets["AMBIG"] += 1
                            else:
                                _corr_buckets["UNK"] += 1
                        else:
                            _corr_buckets["UNK"] += 1
                    except Exception:
                        _corr_buckets["UNK"] += 1
                # Render only buckets with >0 count for compactness
                _fund_txt = " ".join(f"{k}:{v}"
                                     for k, v in _fund_buckets.items() if v > 0)
                _corr_txt = " ".join(f"{k}:{v}"
                                     for k, v in _corr_buckets.items() if v > 0)
                print(f"[ACTIVITY] Overlays: funding[{_fund_txt}]  "
                      f"BTC-corr[{_corr_txt}]")
            except Exception as _ov_e:
                print(f"[ACTIVITY] (overlay summary failed: {_ov_e})")

            elapsed=time.time()-start
            sleep_t=max(0,CHECK_INTERVAL-elapsed)
            save_scalar_state("last_cycle_ts", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
            # Phase A-2: snapshot in-process counters to disk so crash/restart
            # resumes with correct state. Best-effort — never raises into the loop.
            # CRT v1 Session 3 (LBC-H-2 fix): serialize per-token consumed_h4_crt
            # sets as lists of 3-element lists (JSON-safe — tuples and sets
            # don't survive JSON round-trip). Rehydration on startup converts
            # back to sets of tuples. Empty sets pruned to keep snapshot small.
            _crt_state = {
                t: [list(k) for k in STATE[t].get("consumed_h4_crt", set())]
                for t in BINANCE_TOKENS
                if STATE[t].get("consumed_h4_crt")
            }
            _state_store.save({
                "cycle": cycle,
                "consecutive_errors": _consecutive_errors,
                "last_heartbeat_ts": _last_heartbeat,
                "last_cycle_ts_unix": time.time(),
                "restart_count": _persisted.get("restart_count", 1),
                "consumed_h4_crt": _crt_state,
            })
            print(f"[{datetime.now().strftime('%H:%M')}] Done {elapsed:.0f}s — sleep {sleep_t:.0f}s")
            # M-C fix: check shutdown flag between cycles; honor SIGTERM
            # without waiting through a full sleep.
            if _SHUTDOWN_REQUESTED:
                print("[SHUTDOWN] SIGTERM received — exiting main loop cleanly.")
                try:
                    _now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M') + ' UTC'
                    send_telegram(
                        "\U0001F6D1 <b>BOT STOPPED</b>\n"
                        f"\n⏰ <b>Time:</b> {_h(_now)}"
                        "\n\U0001F4DD <b>Reason:</b> Graceful shutdown (likely a systemctl restart)"
                        "\n\n<i>Watchdog will alert if the bot doesn't come back within 5 min.</i>"
                    )
                except Exception:
                    pass
                break
            time.sleep(sleep_t)
        except KeyboardInterrupt:
            print("\n[STOPPED]")
            try:
                _now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M') + ' UTC'
                send_telegram(
                    "\U0001F6D1 <b>BOT STOPPED</b>\n"
                    f"\n⏰ <b>Time:</b> {_h(_now)}"
                    "\n\U0001F4DD <b>Reason:</b> Keyboard interrupt (manual stop)"
                )
            except Exception:
                pass
            break
        except Exception as e:
            _consecutive_errors += 1
            print(f"[LOOP ERROR #{_consecutive_errors}] {e}")
            # Alert user on first error and every 5th thereafter
            if _consecutive_errors == 1 or _consecutive_errors % 5 == 0:
                send_telegram(
                    f"<b>Bot ERROR  -  cycle failure #{_h(_consecutive_errors)}</b>\n\n"
                    "<pre>"
                    f"{_h(str(e)[:300])}"
                    "</pre>\n"
                    "Bot is retrying. Investigate if this persists:\n"
                    "<code>journalctl -u tradeai -n 50</code>"
                )
            # M-CY13-1 Resilience fix (audit cycle-13 2026-05-29): lowered
            # break threshold from 15 → 8 consecutive errors. At 15× backoff
            # (max 300s/cycle) the bot would silently degrade for up to
            # ~75 minutes before stopping; systemd's Restart=always would
            # then re-launch with fresh state. 8× backoff = ~30 min max,
            # which preserves recovery from transient outages (a 15-min
            # Binance hiccup recovers cleanly) but stops the broken process
            # earlier so systemd can take over with a clean PID.
            if _consecutive_errors >= 8:
                send_telegram(
                    "<b>Bot CRITICAL  -  STOPPING</b>\n\n"
                    "8 consecutive cycle failures. The bot has stopped.\n\n"
                    "Investigate before restarting:\n"
                    "<code>journalctl -u tradeai -n 100</code>"
                )
                break
            time.sleep(min(60 * _consecutive_errors, 300))

if __name__=="__main__":
    main()
