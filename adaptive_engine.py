"""
TradeAI — Adaptive Learning Engine  (Phase 3 Architecture)

Replaces the 3-scalar bolt-on feedback loop with a genuine continuous learning
layer that survives restarts and updates in real-time on signal close events.

Components
──────────
AdaptiveWeightEngine   — per-token Online Gradient Descent weights, DB-persisted
DriftDetector          — rolling Z-score concept drift + dynamic threshold recalibration
PortfolioRiskLayer     — exposure cap, correlation guard, drawdown halt
save/load_scalar_state — persists _conf_floor + _signal_threshold_adj across restarts
extract_ict_feature_scores — computes ICT feature contributions from signal conditions

All DB writes use the shared signals.db (WAL mode — concurrent-safe with bot + tracker).
"""

import os
import math
import json
import sqlite3
from datetime import datetime, timezone
from collections import deque
from typing import Dict, Optional, Tuple

_ROOT   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_ROOT, "data", "signals.db")

# ── Sample-size tiers (Task 15) ───────────────────────────
# Used by EV scoring, adaptive updates, and report flagging.
SAMPLE_N_OBSERVE = 30    # observe only — no filter decisions below this
SAMPLE_N_WEAK    = 50    # weak evidence — display EV but don't block signals
SAMPLE_N_USABLE  = 100   # usable — block signals with confirmed negative EV
SAMPLE_N_STRONG  = 200   # statistically confident

# ── OGD hyperparameters ───────────────────────────────────
LEARNING_RATE_INIT = 0.06  # initial (high) learning rate for fast early adaptation
LEARNING_RATE_FLOOR = 0.01 # minimum learning rate after decay (stability floor)
LEARNING_RATE_DECAY = 100  # decay half-life in signal count: LR = FLOOR + (INIT-FLOOR)/(1+n/DECAY)
LEARNING_RATE    = LEARNING_RATE_INIT  # current default; overridden per-token in update()
MOMENTUM         = 0.85   # exponential decay on velocity (prevents oscillation)
WEIGHT_MIN       = 0.05   # per-feature floor — no feature ever goes silent
WEIGHT_MAX       = 0.50   # per-feature ceiling — no feature dominates completely
# Post-renorm degenerate threshold. With 6 features and WEIGHT_MAX=0.50/WEIGHT_MIN=0.05
# the mathematical maximum post-renorm is 0.50/(0.50+5*0.05)=0.667. Previously 0.60
# (only 7pp below the math ceiling) let through cases like ETH/HBAR/LINK dr_location
# ≈ 0.53 with 4 features pinned at WEIGHT_MIN — visibly collapsed onto a single
# feature even though no single value reached 0.60. Tightened to 0.45 on 2026-05-22
# (audit fix #5): catches the 6/7 near-degenerate bootstrap states identified by the
# ogd-weight-inspector while still allowing legitimate concentration up to ~3× default.
# Fix #36 (2026-05-22 cycle 9 audit): tightened further to 0.40 — AVAX bootstrap
# at 0.448 was skimming under the previous 0.45 bar (3.2× default for fvg_quality).
# At 0.40 (2.4× default) the bar still permits genuine learned concentration but
# catches AVAX-class near-collapse so the runtime fallback at crypto_alert.py:2007
# correctly defaults rather than feeding a marginal bootstrap into live scoring.
DEGENERATE_THRESHOLD = 0.40
MAX_WEIGHT_STEP  = 0.04   # Task 16: max velocity magnitude per update (hard cap)
OGD_MIN_SAMPLES  = 10  # OGD reaches FULL learning rate at this sample count
OGD_WARMUP_FLOOR = 3   # R2 fix (master audit 2026-05-26): below this, no update
                       # fires; between WARMUP_FLOOR and MIN_SAMPLES the LR is
                       # ramped linearly from 0 → full. Replaces the sharp
                       # n=10 cliff (signals 1-9 contributed zero gradient,
                       # signal 10 got full LR). Now gradient kicks in gently
                       # at n=4, scales up to full at n=OGD_MIN_SAMPLES.

# ── Sample-size utilities (Task 15) ──────────────────────
def label_sample_size(n: int) -> str:
    """Return a human-readable sample-size tier label for reports and Telegram."""
    if n >= SAMPLE_N_STRONG:  return f"n={n} [STRONG]"
    if n >= SAMPLE_N_USABLE:  return f"n={n} [USABLE]"
    if n >= SAMPLE_N_WEAK:    return f"n={n} [WEAK]"
    if n >= SAMPLE_N_OBSERVE: return f"n={n} [OBSERVE]"
    return f"n={n} [INSUFFICIENT]"


# ── Session classifier (M2: ICT kill zone hours) ──────────────────────────
def _utc_to_session(hour: int) -> str:
    """Map UTC hour → ICT kill zone session label.

    ICT kill zones (UTC):
      ASIA_KZ   — 20:00-23:59 (Asia late session; sets liquidity London reverses)
      LONDON_KZ — 02:00-04:59 (pre-London manipulation / Judas Swing zone)
      NY_AM_KZ  — 13:00-15:59 (NY morning open / London-NY overlap, highest volume)
      OVERNIGHT — all other hours (dead / no institutional order flow)

    Prior labels conflated kill zones with dead periods:
      Old ASIA (0-7) included dead hours 4-7; old LONDON (8-12) missed the true
      pre-London manipulation window (02-04 UTC). Now each label is a clean KZ.
    """
    if hour >= 20: return "ASIA_KZ"  # M2: removed hours 0-1; docstring says 20:00-23:59 only
    if 2 <= hour <= 4:          return "LONDON_KZ"
    if 13 <= hour <= 15:        return "NY_AM_KZ"
    return "OVERNIGHT"


# ── ICT feature weights (replaces legacy RSI/trend/sr/mtf/volume/momentum) ────
DEFAULT_WEIGHTS: Dict[str, float] = {
    "fvg_quality":    0.25,
    "mss_quality":    0.20,
    "session":        0.15,
    "confidence":     0.20,
    "trend_strength": 0.15,
    "dr_location":    0.05,
}
FEATURES = list(DEFAULT_WEIGHTS.keys())

# Score lookup tables for extract_ict_feature_scores()
_QUALITY_SCORE = {"HIGH": 1.0, "MEDIUM": 0.75, "LOW": 0.50, "NONE": 0.0}
_SESSION_SCORE = {"NY_AM_KZ": 1.0, "LONDON_KZ": 0.85, "ASIA_KZ": 0.5, "OVERNIGHT": 0.0}
# Minimum contribution for any feature in OGD gradient computation.
# Prevents zero-score features from receiving zero gradient — which causes passive weight
# inflation via renormalisation whenever non-zero features are penalised on LOSS.
# Example: SELL at DISCOUNT → dr_score=0 → no penalty on LOSS → dr_location drifts up.
# Floor of 0.05 gives every feature a small gradient signal regardless of alignment.
_SCORE_FLOOR = 0.05

# ── Drift detection ───────────────────────────────────────
DRIFT_WINDOW      = 200   # rolling window for baseline statistics
DRIFT_Z_THRESHOLD = 2.5   # Z-score beyond which drift is flagged
DRIFT_MIN_SAMPLES = 20    # activate drift detection only after this many data points

# ── Portfolio limits — scaled by execution mode to protect real capital in LIVE mode ──
# EXECUTION_MODE env var is set by crypto_alert.py's environment; adaptive_engine reads it
# independently to avoid circular imports.
_EXEC_MODE = os.environ.get("EXECUTION_MODE", "PAPER").upper()
if _EXEC_MODE == "LIVE":
    MAX_OPEN_POSITIONS     = 4      # live: max 4 concurrent open positions
    MAX_SAME_DIRECTION     = 2      # live: max 2 buys or 2 sells at once
    MAX_PORTFOLIO_RISK_PCT = 0.03   # M18: lowered from 0.15 — at 1%/trade max reachable was 4%, making 15% a dead gate; 3% fires on the 4th position attempt (4% > 3%), independent of the position-count gate
    MAX_DRAWDOWN_PCT       = 0.10   # live: halt at 10% drawdown (tighter)
else:
    MAX_OPEN_POSITIONS     = 20     # paper: effectively unlimited (max 9 real tokens)
    MAX_SAME_DIRECTION     = 10     # paper: effectively unlimited
    MAX_PORTFOLIO_RISK_PCT = 1.0    # paper: effectively unlimited
    MAX_DRAWDOWN_PCT       = 0.20   # paper: halt at 20% drawdown

# ── Scalper-mode signal thresholds (mirror crypto_alert.py — keep in sync) ───
# Direct import is not possible: crypto_alert imports this module at load time.
_VOLUME_SPIKE      = 1.2    # crypto_alert.VOLUME_SPIKE  (was swing: 1.4)
_ROC_BUY_THRESHOLD = -1.5   # crypto_alert: roc < -1.5   (was swing: -3.0)
_ROC_SELL_THRESHOLD =  3.0  # crypto_alert: roc >  3.0   (was swing:  8.0)
# Fix #33 (2026-05-22 cycle 9 audit): read mirrors from env so operator overrides
# of RISK_PER_TRADE_PCT / MAX_POSITION_PCT in config.py / .env actually reach
# adaptive_engine.py — previously hardcoded literals silently desynchronised the
# drawdown gate (adaptive_engine.py:1051) from the live position sizer.
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
_RISK_PER_TRADE_PCT = _env_float("RISK_PER_TRADE_PCT", 0.01)
_MAX_POSITION_PCT   = _env_float("MAX_POSITION_PCT",   0.20)
_RSI_OVERSOLD      = 45.0   # crypto_alert.RSI_OVERSOLD  (was swing: 38.0)
_RSI_OVERBOUGHT    = 55.0   # crypto_alert.RSI_OVERBOUGHT (was swing: 62.0)


# ══════════════════════════════════════════════════════════
# SHARED DB CONNECTION
# ══════════════════════════════════════════════════════════
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_adaptive_tables():
    """Create adaptive engine tables if they don't exist. Idempotent.

    Also runs one-time migrations:
    - Deletes legacy feature rows (rsi/trend/sr/mtf/volume/momentum) left from
      pre-ICT adaptive engine — these used wrong features and must be cleared.
    - Removes test_key debug entry from bot_state.
    """
    conn = _connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS token_weights (
        token      TEXT NOT NULL,
        feature    TEXT NOT NULL,
        weight     REAL NOT NULL DEFAULT 0.1667,
        velocity   REAL          DEFAULT 0.0,
        n_updates  INTEGER       DEFAULT 0,
        updated_at TEXT,
        PRIMARY KEY (token, feature)
    )""")
    # Backtest bootstrap weights stored separately to avoid contaminating live OGD state.
    # Live engine never writes here; bootstrap_from_backtest() is the only writer.
    conn.execute("""CREATE TABLE IF NOT EXISTS backtest_token_weights (
        token        TEXT NOT NULL,
        feature      TEXT NOT NULL,
        weight       REAL NOT NULL DEFAULT 0.1667,
        velocity     REAL          DEFAULT 0.0,
        n_bootstrap  INTEGER       DEFAULT 0,
        updated_at   TEXT,
        PRIMARY KEY (token, feature)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS bot_state (
        key   TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS market_stats (
        token        TEXT NOT NULL,
        stat_name    TEXT NOT NULL,
        values_json  TEXT,
        rolling_mean REAL DEFAULT 0,
        rolling_std  REAL DEFAULT 1,
        n_samples    INTEGER DEFAULT 0,
        updated_at   TEXT,
        PRIMARY KEY (token, stat_name)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS tune_history (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        applied_at       TEXT    NOT NULL,
        param            TEXT    NOT NULL,
        old_val          TEXT    NOT NULL,
        new_val          TEXT    NOT NULL,
        signals_at_apply INTEGER NOT NULL,
        backtest_run_id  INTEGER,
        train_wr         REAL,
        test_wr          REAL,
        post_apply_wr    REAL,
        post_apply_n     INTEGER,
        status           TEXT    DEFAULT 'APPLIED',
        backup_file      TEXT,
        notes            TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS weight_history (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        recorded_at   TEXT    NOT NULL,
        token         TEXT    NOT NULL,
        trigger       TEXT    NOT NULL,
        feature       TEXT    NOT NULL,
        weight_before REAL    NOT NULL,
        weight_after  REAL    NOT NULL,
        n_updates     INTEGER NOT NULL,
        run_id        INTEGER
    )""")
    # Migration: purge legacy feature rows and debug state
    conn.execute("""DELETE FROM token_weights WHERE feature NOT IN
        ('fvg_quality','mss_quality','session','confidence','trend_strength','dr_location')""")
    conn.execute("DELETE FROM bot_state WHERE key='test_key'")
    # R4 + R7 fixes (master audit 2026-05-26): add forensic + regime columns.
    # ALTER IDEMPOTENTLY — IF NOT EXISTS clause via try/except for each new
    # column so old DBs migrate forward without dropping data.
    for _col, _ddl in (
        ("reward",      "REAL"),           # R4: signed reward used in the OGD step
        ("gradient_l1", "REAL"),           # R4: sum(|w_after - w_before|) across features
        ("profit_pct",  "REAL"),           # R4: realised PnL fraction passed to update()
        ("regime",      "TEXT"),           # R7: regime label at update time (observation-only)
    ):
        try:
            conn.execute(f"ALTER TABLE weight_history ADD COLUMN {_col} {_ddl}")
        except sqlite3.OperationalError:
            # Column already exists — safe to ignore
            pass
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
# ADAPTIVE WEIGHT ENGINE — Online Gradient Descent
# ══════════════════════════════════════════════════════════
class AdaptiveWeightEngine:
    """
    Per-token Online Gradient Descent weight updater.

    Triggered immediately when a signal closes (WIN / LOSS / EXPIRED).
    Weights are persisted to DB after every update — no state loss on restart.

    Gradient approximation (policy gradient style):
        reward   =  +1.0  (WIN)  |  +0.4 (PARTIAL)  |  -1.0 (LOSS)  |  -0.25 (EXPIRED)
        gradient =  reward × feature_contribution_fraction
        velocity =  MOMENTUM × velocity_prev + LEARNING_RATE × gradient
        weight   =  weight_prev + velocity
        → clip to [WEIGHT_MIN, WEIGHT_MAX]
        → renormalise so all weights sum to 1.0

    With LEARNING_RATE=0.03 and MOMENTUM=0.85, a single extreme outcome shifts
    each weight by ~0.03, requiring ~10 consistent signals to move a weight by
    a meaningful 0.3 — appropriate for the sample sizes this bot sees.
    """

    def __init__(self):
        self._weights:          Dict[str, Dict[str, float]] = {}
        self._velocity:         Dict[str, Dict[str, float]] = {}
        self._n:                Dict[str, int]               = {}  # closed-signal count per token
        # OGD-PHASEA (cycle-4 audit 2026-05-26): track effective sample count
        # alongside raw n. Each update contributes |reward| ∈ [0, 1] to
        # n_effective. Phase A's stale-reject raised PARTIAL_TP1 share from
        # 18.6% → 28.6%; each PARTIAL contributes 0.4 vs WIN's 1.0 to the
        # gradient. n_effective < raw_n at PARTIAL-heavy distributions —
        # exposed for operator visibility + future gating refinement.
        # In-memory only (no schema change); logged each OGD update.
        self._n_effective:      Dict[str, float]             = {}
        self._last_update_time: Dict[str, float]             = {}  # epoch of last OGD update
        _init_adaptive_tables()
        self._load_all()

    # ── Init ─────────────────────────────────────────────
    def _default_weights(self) -> Dict[str, float]:
        return dict(DEFAULT_WEIGHTS)

    def _default_velocity(self) -> Dict[str, float]:
        return {f: 0.0 for f in FEATURES}

    def _ensure_token(self, token: str):
        if token not in self._weights:
            self._weights[token]          = self._default_weights()
            self._velocity[token]         = self._default_velocity()
            self._n[token]                = 0
            self._n_effective[token]      = 0.0
            self._last_update_time[token] = 0.0

    def _load_all(self):
        rows = []
        try:
            conn  = _connect()
            rows  = conn.execute(
                "SELECT token, feature, weight, velocity, n_updates, updated_at FROM token_weights"
            ).fetchall()
            conn.close()
        except Exception as e:
            print(f"[ADAPTIVE STARTUP ALERT] Failed to load live token_weights from DB: {e}. "
                  f"All tokens will start from default weights — live learning state is lost.")

        feature_set = set(FEATURES)
        for token, feature, weight, velocity, n_updates, updated_at in rows:
            if feature not in feature_set:
                continue  # skip any surviving legacy rows
            self._ensure_token(token)
            self._weights[token][feature]  = float(weight)
            self._velocity[token][feature] = float(velocity or 0.0)
            self._n[token]                 = max(self._n.get(token, 0), int(n_updates or 0))
            # Populate last_update_time from DB so 7-day decay suppression survives restarts.
            if updated_at:
                try:
                    dt = datetime.strptime(str(updated_at), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    epoch = dt.timestamp()
                    self._last_update_time[token] = max(self._last_update_time.get(token, 0.0), epoch)
                except Exception:
                    pass

        # For tokens with no live updates yet, warm-start from backtest bootstrap weights.
        # This preserves OGD benefit without contaminating live n_updates count.
        try:
            conn = _connect()
            bt_rows = conn.execute(
                "SELECT token, feature, weight, velocity FROM backtest_token_weights"
            ).fetchall()
            conn.close()
            for token, feature, weight, velocity in bt_rows:
                if feature not in feature_set:
                    continue
                if self._n.get(token, 0) == 0:
                    self._ensure_token(token)
                    self._weights[token][feature]  = float(weight)
                    self._velocity[token][feature] = float(velocity or 0.0)
        except Exception:
            pass  # backtest table may not have data yet — not a failure

        loaded = list(self._weights.keys())
        if loaded:
            live_tokens = [t for t in loaded if self._n.get(t, 0) > 0]
            bt_tokens   = [t for t in loaded if self._n.get(t, 0) == 0]
            if live_tokens:
                print(f"[ADAPTIVE] Live weights loaded for: {', '.join(sorted(live_tokens))}")
            if bt_tokens:
                print(f"[ADAPTIVE] Bootstrap-initialized (no live data yet): {', '.join(sorted(bt_tokens))}")

    # ── Public API ───────────────────────────────────────
    def get_weights(self, token: str) -> Dict[str, float]:
        """Return current normalised weights for token (falls back to defaults)."""
        self._ensure_token(token)
        return dict(self._weights[token])

    def get_sample_count(self, token: str) -> int:
        return self._n.get(token, 0)

    def update(self, token: str, outcome: str,
               feature_scores: Dict[str, float], persist: bool = True,
               profit_pct: float = None, regime: str = None,
               snapshot: bool = False):
        """
        Apply OGD update immediately on signal close.

        outcome:        'WIN' | 'PARTIAL' | 'LOSS' | 'EXPIRED'
        feature_scores: {feature: fractional_contribution} — from extract_ict_feature_scores()
        profit_pct:     actual P&L % (signed; e.g. +0.015 = +1.5%, -0.012 = -1.2%).
                        When provided, reward is scaled proportionally to real P&L rather than
                        using discrete outcome buckets — larger wins earn more gradient signal.
        regime:         R7 fix (master audit 2026-05-26) — observation-only regime label at
                        update time (e.g. "TRENDING_BULL", "RANGING"). NOT used to condition
                        learning — purely persisted to weight_history for future analysis.
        snapshot:       R4 fix (master audit 2026-05-26) — when True, also write a
                        weight_history row (trigger='signal_close') tagged with the reward /
                        gradient_l1 / profit_pct / regime metadata for forensic queries.
                        Default False to preserve back-compat — callers (crypto_alert.py
                        _trigger_weight_update) opt in.
        """
        self._ensure_token(token)
        n = self._n.get(token, 0)
        w_before_snapshot = dict(self._weights[token]) if snapshot else None

        _base_reward = {"WIN": +1.0, "PARTIAL_TP2": +0.6, "PARTIAL": +0.4, "PARTIAL_TP1": +0.4,
                        "LOSS": -1.0, "EXPIRED": -0.25}.get(outcome, 0.0)
        # Scale by actual P&L magnitude when available (capped at ±2.0 to prevent extremes).
        # profit_pct must arrive as a fraction (e.g. -0.0085 for -0.85% P&L).
        # Dividing by 0.01 scales fraction → reward units: 1% P&L → reward 1.0.
        # The caller (crypto_alert.py) converts DB percentage-points to fraction before passing here.
        # Do NOT remove the caller's /100 or this /0.01 — both are load-bearing.
        if profit_pct is not None and _base_reward != 0.0:
            _pnl_scaled = max(-2.0, min(2.0, profit_pct / 0.01))
            # Blend: 50% discrete outcome + 50% proportional P&L signal
            reward = 0.5 * _base_reward + 0.5 * _pnl_scaled
        else:
            reward = _base_reward

        # R8 fix (master audit 2026-05-26): alert when reward magnitude is
        # unusually large. The blended reward CAN reach ±1.5 (base ±1.0 +
        # PnL-scaled ±2.0, mean = ±1.5 in extreme cases). Magnitudes above
        # 1.2 indicate either (a) an unusually large trade outcome — fine,
        # operator should know — or (b) `profit_pct` arriving in wrong
        # units (% instead of fraction, missing /100 conversion). The
        # caller's contract is `profit_pct as fraction` per the comment
        # above; this alert catches contract violations silently corrupting
        # the gradient signal.
        if abs(reward) > 1.2:
            print(f"[ADAPTIVE] WARN reward magnitude {reward:+.3f} on {token} "
                  f"outcome={outcome} profit_pct={profit_pct} — verify "
                  f"profit_pct is a fraction (e.g. -0.0085 for -0.85% P&L), "
                  f"NOT a percentage. See _compute_reward docstring.")

        if reward == 0.0:
            self._n[token] = n + 1
            if persist:
                self._persist_token(token)
            return

        # R2 fix (master audit 2026-05-26): replace the sharp n=10 cliff with
        # a linear ramp from OGD_WARMUP_FLOOR (n=3, ramp_scale=0) to
        # OGD_MIN_SAMPLES (n=10, ramp_scale=1). Below WARMUP_FLOOR no update
        # fires (need minimum data); within the ramp window, the LR is scaled
        # to reflect partial confidence. Eliminates the discontinuity where
        # signal 10 suddenly carries full gradient while signal 9 carried zero.
        if n < OGD_WARMUP_FLOOR:
            self._n[token] = n + 1
            if persist:
                self._persist_token(token)
                print(f"[ADAPTIVE] {token} — accumulating samples ({n+1}/{OGD_WARMUP_FLOOR}) "
                      f"before OGD warmup activates")
            return
        if n < OGD_MIN_SAMPLES:
            # Soft warmup ramp: scale LR from 0 (at WARMUP_FLOOR) to 1 (at MIN_SAMPLES)
            ramp_scale = (n - OGD_WARMUP_FLOOR) / max(1, OGD_MIN_SAMPLES - OGD_WARMUP_FLOOR)
            print(f"[ADAPTIVE] {token} — warmup ramp n={n}/{OGD_MIN_SAMPLES} "
                  f"lr_scale={ramp_scale:.2f} (OGD partially active)")
        else:
            ramp_scale = 1.0

        w     = self._weights[token]
        v     = self._velocity[token]
        w_old = dict(w)   # snapshot for logging

        # Decaying learning rate: high early (fast adaptation), low later (stability).
        # LR = FLOOR + (INIT - FLOOR) / (1 + n / DECAY)
        _lr = LEARNING_RATE_FLOOR + (LEARNING_RATE_INIT - LEARNING_RATE_FLOOR) / (
            1.0 + n / max(LEARNING_RATE_DECAY, 1))
        # R2: soft-ramp LR scaling during warmup window
        _lr = _lr * ramp_scale

        for feat in FEATURES:
            score   = feature_scores.get(feat, 1.0 / len(FEATURES))
            grad    = reward * score
            v[feat] = MOMENTUM * v[feat] + _lr * grad
            # Task 16: hard-cap velocity so a single extreme event can't spike weights
            v[feat] = max(-MAX_WEIGHT_STEP, min(MAX_WEIGHT_STEP, v[feat]))
            w[feat] = w[feat] + v[feat]

        # Clip to [WEIGHT_MIN, WEIGHT_MAX]
        for feat in FEATURES:
            w[feat] = max(WEIGHT_MIN, min(WEIGHT_MAX, w[feat]))

        # Renormalise → sum = 1.0
        total = sum(w.values())
        if total > 0:
            for feat in FEATURES:
                w[feat] = round(w[feat] / total, 6)

        self._weights[token]  = w
        self._velocity[token] = v
        self._n[token]        = n + 1
        # OGD-PHASEA fix: accumulate |reward| / 1.0 as effective sample
        # weight (capped at 1.0). At PARTIAL-heavy distributions the
        # gradient signal is weaker per update; this exposes the gap
        # between raw count and effective contribution.
        self._n_effective[token] = self._n_effective.get(token, 0.0) + min(1.0, abs(reward))

        if persist:
            self._persist_token(token)

        # Task 16: detailed per-update log — old->new weight, delta, sample size.
        # OGD-PHASEA: log shows raw n + effective n so operator can see the gap.
        if persist:  # suppress per-update log during batch bootstrap
            changed = [(f, w_old[f], w[f]) for f in FEATURES if abs(w[f] - w_old[f]) > 0.001]
            change_str = "  ".join(f"{f}:{wo:.3f}->{wn:.3f}" for f, wo, wn in changed) or "no change"
            total_delta = sum(abs(w[f] - w_old[f]) for f in FEATURES)
            n_eff = self._n_effective.get(token, 0.0)
            print(f"[ADAPTIVE] {token} OGD #{n+1} outcome={outcome} "
                  f"reward={reward:+.2f} delta={total_delta:.4f} "
                  f"n={n+1}/{OGD_MIN_SAMPLES}+ n_eff={n_eff:.1f} "
                  f"| {change_str}")

        # R4 + R7 fix: forensic snapshot to weight_history when caller opts in
        # (live closes pass snapshot=True; bootstrap path uses _snapshot_weights
        # directly with bootstrap_before/after triggers).
        if snapshot:
            self._snapshot_weights(
                trigger="signal_close",
                weights_before={token: w_before_snapshot} if w_before_snapshot else None,
                reward=reward,
                profit_pct=profit_pct,
                regime=regime,
                token_filter=token,
            )

    # ── Persistence ──────────────────────────────────────
    def _persist_token(self, token: str):
        try:
            conn = _connect()
            w    = self._weights[token]
            v    = self._velocity[token]
            n    = self._n.get(token, 0)
            now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            for feat in FEATURES:
                conn.execute("""INSERT OR REPLACE INTO token_weights
                    (token, feature, weight, velocity, n_updates, updated_at)
                    VALUES (?,?,?,?,?,?)""",
                    (token, feat, w[feat], v.get(feat, 0.0), n, now))
            conn.commit()
            conn.close()
            self._last_update_time[token] = datetime.now(timezone.utc).timestamp()
        except Exception as e:
            print(f"[ADAPTIVE] persist error {token}: {e}")

    def _persist_all(self):
        """Write all in-memory token weights to DB in a single transaction."""
        try:
            conn = _connect()
            now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            for token in self._weights:
                w = self._weights[token]
                v = self._velocity[token]
                n = self._n.get(token, 0)
                for feat in FEATURES:
                    conn.execute("""INSERT OR REPLACE INTO token_weights
                        (token, feature, weight, velocity, n_updates, updated_at)
                        VALUES (?,?,?,?,?,?)""",
                        (token, feat, w[feat], v.get(feat, 0.0), n, now))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ADAPTIVE] _persist_all error: {e}")

    def bootstrap_from_backtest(self, run_id: int = None, verbose: bool = True) -> Dict[str, int]:
        """Warm-start OGD weights from historical backtest_signals.

        Runs OGD in an ISOLATED scratch engine — results are saved to
        backtest_token_weights only, never to token_weights (live state).
        Live _weights/_n/_velocity are completely unaffected.

        On next startup, _load_all() warm-starts any token with zero live updates
        from backtest_token_weights, preserving the benefit without contamination.

        M14 NOTE: The primary bootstrap bias risk is NOT directional imbalance
        (BUY/SELL ratio) but anti-aligned DR conditions (SELL@DISCOUNT or
        BUY@PREMIUM dominating the signal mix). These produce near-zero dr_location
        scores on every update, allowing dr_location weight to inflate via
        renormalisation even without the zero-floor bug. An alignment-balance
        warning fires when anti-aligned DR signals exceed 60% of a token's set.
        A soft-threshold alert fires when any feature weight exceeds 3× its default.

        NOTE: backtest_token_weights may be empty in practice if a DB maintenance
        step clears it or if the runtime DB path differs from the backtest DB path.
        In that case this warm-start path is inactive and _load_all() uses
        DEFAULT_WEIGHTS for all tokens with zero live updates.

        Args:
            run_id:  restrict to a specific run (None = all runs)
            verbose: print per-token weight summary after bootstrap
        Returns:
            {token: n_signals_processed}
        """
        try:
            conn  = _connect()
            query = """
                SELECT token, signal, outcome, fvg_quality, mss_quality,
                       session, confidence, trend_1h, dr_location
                FROM backtest_signals
                WHERE outcome IS NOT NULL AND outcome != ''
                  AND fvg_quality IS NOT NULL AND fvg_quality NOT IN ('', 'NONE')
            """
            params: tuple = ()
            if run_id is not None:
                query  += " AND run_id = ?"
                params  = (run_id,)
            query += " ORDER BY ts ASC"
            rows  = conn.execute(query, params).fetchall()
            conn.close()
        except Exception as e:
            print(f"[ADAPTIVE] bootstrap_from_backtest DB error: {e}")
            return {}

        # M14: Alignment-balance warning — anti-aligned DR conditions (SELL@DISCOUNT /
        # BUY@PREMIUM) produce near-zero dr_location scores every update, allowing
        # dr_location weight to inflate via renormalisation.  Warn when > 60% of a
        # token's bootstrap set is anti-aligned so the operator can investigate the
        # signal mix before live warm-start.
        from collections import defaultdict as _dd
        _anti_cnt: dict = _dd(int)
        _total_cnt: dict = _dd(int)
        for _r in rows:
            _rtok, _rdir, _roc, _rdr = _r[0], _r[1], _r[2], _r[8]
            if _roc and _roc not in ("", "NONE"):
                _total_cnt[_rtok] += 1
                if (_rdir == "SELL" and _rdr == "DISCOUNT") or (_rdir == "BUY" and _rdr == "PREMIUM"):
                    _anti_cnt[_rtok] += 1
        for _rtok in _total_cnt:
            if _total_cnt[_rtok] > 0:
                _apct = _anti_cnt[_rtok] / _total_cnt[_rtok]
                if _apct > 0.60:
                    _amsg = (f"[ADAPTIVE] bootstrap alignment-bias WARNING: {_rtok} "
                             f"anti-aligned DR signals = {_anti_cnt[_rtok]}/{_total_cnt[_rtok]} "
                             f"({_apct:.0%}) — dr_location weight may inflate during bootstrap")
                    print(_amsg)

        valid_outcomes = {"WIN", "PARTIAL_TP2", "PARTIAL_TP1", "PARTIAL", "LOSS", "EXPIRED"}
        n_processed: Dict[str, int] = {}

        # ── Scratch engine — isolated from live state ─────────────────────────
        scratch_w:  Dict[str, Dict[str, float]] = {}
        scratch_v:  Dict[str, Dict[str, float]] = {}
        scratch_n:  Dict[str, int]               = {}

        def _ensure(token):
            if token not in scratch_w:
                scratch_w[token] = dict(DEFAULT_WEIGHTS)
                scratch_v[token] = {f: 0.0 for f in FEATURES}
                scratch_n[token] = 0

        self._snapshot_weights(trigger="bootstrap_before", run_id=run_id)

        for row in rows:
            token, direction, outcome, fvg_q, mss_q, session, conf, trend_1h, dr_loc = row
            if outcome not in valid_outcomes:
                continue
            _ensure(token)
            scores = extract_ict_feature_scores(
                signal=direction or "BUY",
                fvg_quality=fvg_q or "NONE",
                mss_quality=mss_q or "NONE",
                session=session or "OVERNIGHT",
                confidence=int(conf or 5),
                trend_1h=trend_1h or "NEUTRAL",
                dr_location=dr_loc or "UNKNOWN",
            )
            reward = {"WIN": +1.0, "PARTIAL_TP2": +0.6, "PARTIAL": +0.4, "PARTIAL_TP1": +0.4,
                      "LOSS": -1.0, "EXPIRED": -0.25}.get(outcome, 0.0)
            n = scratch_n[token]
            if reward != 0.0 and n >= OGD_MIN_SAMPLES:
                w = scratch_w[token]; v = scratch_v[token]
                _lr = LEARNING_RATE_FLOOR + (LEARNING_RATE_INIT - LEARNING_RATE_FLOOR) / (
                    1.0 + n / max(LEARNING_RATE_DECAY, 1))
                for feat in FEATURES:
                    score   = scores.get(feat, 1.0 / len(FEATURES))
                    grad    = reward * score
                    v[feat] = MOMENTUM * v[feat] + _lr * grad
                    v[feat] = max(-MAX_WEIGHT_STEP, min(MAX_WEIGHT_STEP, v[feat]))
                    w[feat] = w[feat] + v[feat]
                for feat in FEATURES:
                    w[feat] = max(WEIGHT_MIN, min(WEIGHT_MAX, w[feat]))
                total = sum(w.values())
                if total > 0:
                    for feat in FEATURES:
                        w[feat] = round(w[feat] / total, 6)
            scratch_n[token] = n + 1
            n_processed[token] = n_processed.get(token, 0) + 1

        # ── Degenerate-reject guard (audit 2026-05-25, C-F follow-up) ────────
        # Tokens with thin bootstrap data can produce lopsided weight distributions
        # (e.g. TON post-onboarding 2026-05-24: session=43.9% > DEGENERATE_THRESHOLD 0.40).
        # Without intervention, these degenerate distributions would persist in
        # backtest_token_weights and cold-start contaminate live token_weights.
        # Live runtime has a degenerate-block guard that falls back to DEFAULT_WEIGHTS
        # at scoring time, but the dashboard still flags CRIT and the table stores
        # noise. Cleaner to refuse the import at the source: when a token's
        # bootstrap output is degenerate, substitute uniform DEFAULT_WEIGHTS so the
        # persisted row is clean. Live OGD updates will diverge organically once
        # closed paper signals accumulate. This is data-quality enforcement at the
        # bootstrap layer, not a behavioral change at scoring time.
        _rejected_tokens: list = []
        _thin_tokens: list = []
        # M-J fix (cycle-4 audit 2026-05-26): tokens with thin bootstrap data
        # (e.g. n < BOOTSTRAP_MIN_N_PER_TOKEN, default 5) cannot honestly
        # support a learned weight vector. Run-78/79 produced n=7 total →
        # tokens with 0-1 sample retained DEFAULT_WEIGHTS but masqueraded
        # as `_has_bootstrap=True` if any feature-weight drift survived
        # rounding. Refuse the import for these tokens at the source —
        # substitute uniform DEFAULT_WEIGHTS and force n_bootstrap=0 so the
        # downstream `_has_bootstrap` predicate in crypto_alert.py:2031
        # correctly reads "not bootstrapped yet".
        _BOOTSTRAP_MIN_N_PER_TOKEN = int(
            __import__("os").environ.get("BOOTSTRAP_MIN_N_PER_TOKEN", "5") or "5"
        )
        for _tok in list(scratch_w.keys()):
            _n_for_tok = scratch_n.get(_tok, 0)
            if _n_for_tok < _BOOTSTRAP_MIN_N_PER_TOKEN:
                scratch_w[_tok] = dict(DEFAULT_WEIGHTS)
                scratch_v[_tok] = {f: 0.0 for f in FEATURES}
                scratch_n[_tok] = 0  # force n_bootstrap=0 so _has_bootstrap reads False
                _thin_tokens.append((_tok, _n_for_tok))
                print(f"[ADAPTIVE] bootstrap THIN {_tok} — "
                      f"n_bootstrap={_n_for_tok} < {_BOOTSTRAP_MIN_N_PER_TOKEN} "
                      f"(substituted uniform DEFAULT_WEIGHTS + n_bootstrap=0; live OGD "
                      f"will learn organically once paper signals close)")
                continue
            _is_degen, _worst_feat, _worst_val = self._check_degenerate(scratch_w[_tok])
            if _is_degen:
                scratch_w[_tok] = dict(DEFAULT_WEIGHTS)
                scratch_v[_tok] = {f: 0.0 for f in FEATURES}
                _rejected_tokens.append((_tok, _worst_feat, _worst_val))
                print(f"[ADAPTIVE] bootstrap REJECTED {_tok} — "
                      f"{_worst_feat}={_worst_val:.3f} > {DEGENERATE_THRESHOLD} "
                      f"(substituted uniform DEFAULT_WEIGHTS; live OGD will learn organically "
                      f"once paper signals close)")

        # ── Persist to backtest_token_weights only — never touches token_weights ──
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = _connect()
            for token, w in scratch_w.items():
                v = scratch_v[token]
                n = scratch_n[token]
                for feat in FEATURES:
                    conn.execute("""INSERT OR REPLACE INTO backtest_token_weights
                        (token, feature, weight, velocity, n_bootstrap, updated_at)
                        VALUES (?,?,?,?,?,?)""",
                        (token, feat, w[feat], v.get(feat, 0.0), n, now))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ADAPTIVE] bootstrap persist to backtest_token_weights error: {e}")

        self._snapshot_weights(trigger="bootstrap_after", run_id=run_id)

        # M-I fix (cycle-4 audit 2026-05-26): seed _last_update_time for every
        # token that received a non-default bootstrap weight. Without this,
        # newly-bootstrapped tokens with _last_update_time=0 cause the 7-day
        # decay-suppression guard at line 722 (`_time.time() - last < 7*86400`)
        # to read effectively "never updated" → guard is inactive from minute
        # one, so bootstrap weights silently decay every cycle until the first
        # live close. Now seeded to bootstrap time so the 7-day guard activates
        # from the moment bootstrap completes.
        _bootstrap_now = datetime.now(timezone.utc).timestamp()
        for _seed_tok in scratch_w.keys():
            # Skip tokens that were thinned (n=0) — they aren't truly bootstrapped.
            if scratch_n.get(_seed_tok, 0) > 0:
                self._last_update_time[_seed_tok] = _bootstrap_now

        if _rejected_tokens:
            print(f"[ADAPTIVE] bootstrap degenerate-reject summary: "
                  f"{len(_rejected_tokens)} token(s) substituted with uniform defaults: "
                  f"{', '.join(f'{t}({f}={v:.2f})' for t, f, v in _rejected_tokens)}")
        if _thin_tokens:
            print(f"[ADAPTIVE] bootstrap thin-sample summary (M-J fix): "
                  f"{len(_thin_tokens)} token(s) below n_bootstrap floor of "
                  f"{_BOOTSTRAP_MIN_N_PER_TOKEN}: "
                  f"{', '.join(f'{t}(n={n})' for t, n in _thin_tokens)}")

        # M14: Soft-threshold alert — warn when any feature weight exceeds 3× its
        # default (e.g., dr_location > 0.15 given default 0.05).  Does not block;
        # flags potential inflation for manual review before warm-start is applied.
        for _tok, _w in scratch_w.items():
            for _sfeat, _swval in _w.items():
                _sthresh = 3.0 * DEFAULT_WEIGHTS.get(_sfeat, 1.0 / len(FEATURES))
                if _swval > _sthresh:
                    _stmsg = (f"[ADAPTIVE] bootstrap soft-threshold WARNING: {_tok} "
                              f"feature '{_sfeat}' weight={_swval:.4f} > 3× default "
                              f"({_sthresh:.4f}) — inspect bootstrap signal mix")
                    print(_stmsg)

        total = sum(n_processed.values())
        scope = f"run_id={run_id}" if run_id is not None else "all runs"
        print(f"[ADAPTIVE] Bootstrap complete ({scope}) — {total} signals, {len(n_processed)} tokens → "
              f"saved to backtest_token_weights (live token_weights untouched)")
        if verbose:
            for tok in sorted(n_processed):
                w     = scratch_w.get(tok, {})
                n     = scratch_n.get(tok, 0)
                w_str = "  ".join(f"{f[:3]}:{v:.3f}" for f, v in w.items())
                print(f"  {tok:<5} n={n:>4}  {w_str}")
        return n_processed

    @staticmethod
    def _check_degenerate(weights: dict) -> tuple:
        """Return (is_degenerate, worst_feature, worst_value) for a feature-weight dict.

        A weight is degenerate when one feature holds > DEGENERATE_THRESHOLD of the
        post-renorm budget. Single source of truth — use this everywhere instead of
        inline max(weights.values()) > DEGENERATE_THRESHOLD comparisons.
        """
        if not weights:
            return False, "", 0.0
        worst_feat = max(weights, key=weights.get)
        worst_val  = weights[worst_feat]
        return worst_val > DEGENERATE_THRESHOLD, worst_feat, worst_val

    def decay_toward_default(self, token: str, decay_rate: float = 0.0004) -> None:
        """Task 16: gently pull weights toward defaults to prevent long-term divergence.
        Called every 30 min (~48×/day). At decay_rate=0.0004, ~82% of learned deviation
        survives the ~514-call gap between signals (34 signals/year). Previously 0.002
        erased 64% per inter-signal gap — see H9 fix. Option B (per-trade decay) deferred.
        LOW #4: suppressed for 7 days after a live OGD update to protect freshly learned weights."""
        self._ensure_token(token)
        import time as _time
        if _time.time() - self._last_update_time.get(token, 0.0) < 7 * 86400:
            return  # recently updated — skip decay to protect fresh OGD learning
        w   = self._weights[token]
        dw  = DEFAULT_WEIGHTS
        any_change = False
        for feat in FEATURES:
            delta   = decay_rate * (dw[feat] - w[feat])
            w[feat] = round(w[feat] + delta, 6)
            if abs(delta) > 0.0001:
                any_change = True
        if any_change:
            self._persist_token(token)

    # ── Diagnostics ──────────────────────────────────────
    def summary(self) -> str:
        lines = ["[ADAPTIVE WEIGHTS — current per-token]"]
        for token in sorted(self._weights):
            w   = self._weights[token]
            n   = self._n.get(token, 0)
            row = "  ".join(f"{f[:3]}:{v:.3f}" for f, v in w.items())
            lines.append(f"  {token:<5} n={n:>4}  {row}")
        if len(lines) == 1:
            lines.append("  (no tokens updated yet — using defaults)")
        return "\n".join(lines)

    # ── P1-4: OGD health status ──────────────────────────
    def health_check(self) -> Dict[str, dict]:
        """Return per-token health dict for dashboard and Tune Bot guardrails.

        Fields per token:
            max_weight    — largest feature weight (>DEGENERATE_THRESHOLD = degenerate)
            is_degenerate — bool
            n_updates     — total OGD updates received
            weight_entropy — -sum(w * log(w)); low = collapsed distribution
            last_updated  — updated_at timestamp from DB (or None)
        """
        import math as _math
        result: Dict[str, dict] = {}
        try:
            conn = _connect()
            db_rows = conn.execute(
                "SELECT token, MAX(n_updates), MAX(updated_at) FROM token_weights GROUP BY token"
            ).fetchall()
            conn.close()
            last_upd = {r[0]: r[2] for r in db_rows}
        except Exception:
            last_upd = {}

        for token, w in self._weights.items():
            vals = list(w.values())
            max_w = max(vals, default=0.0)
            is_degen, _, _ = self._check_degenerate(w)
            # Shannon entropy; clamp to avoid log(0)
            entropy = -sum(v * _math.log(max(v, 1e-12)) for v in vals)
            result[token] = {
                "max_weight":    round(max_w, 4),
                "is_degenerate": is_degen,
                "n_updates":     self._n.get(token, 0),
                "weight_entropy": round(entropy, 4),
                "last_updated":  last_upd.get(token),
            }
        return result

    # ── P1-5: weight snapshot helper ─────────────────────
    def _snapshot_weights(self, trigger: str, run_id: int = None,
                          weights_before: "Dict[str, Dict[str, float]]" = None,
                          reward: float = None,
                          profit_pct: float = None,
                          regime: str = None,
                          token_filter: str = None) -> None:
        """Write snapshot rows to weight_history for all loaded tokens.

        weights_before: optional mapping {token: {feature: weight}} representing
            the weights that were in effect BEFORE the triggering event.
            If omitted, the current in-memory weight is used for both columns
            (single-point snapshot — weight_before == weight_after).
            Must be passed for bootstrap_after so the before/after delta is meaningful.

        reward / profit_pct: R4 fix (master audit 2026-05-26) — persisted to
            weight_history per row. Enables forensic queries like "which OGD
            update had the largest gradient impact?" without fragile joins to
            the `results` table.

        regime: R7 fix (master audit 2026-05-26) — observation-only regime
            label captured at update time (e.g. "TRENDING_BULL", "RANGING").
            NOT used to condition learning — pure data for future
            regime-aware analysis (Phase D.x).

        token_filter: when set, only writes rows for that single token
            (used by per-signal `update()` to avoid persisting all tokens
            on every close).
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = _connect()
            for token, w in self._weights.items():
                if token_filter is not None and token != token_filter:
                    continue
                n        = self._n.get(token, 0)
                # Resolve the "before" source: explicit dict > current in-memory weight
                w_before = (weights_before.get(token, w)
                            if weights_before is not None else w)
                # R4: per-update gradient_l1 = sum of |w_after - w_before|.
                # Captures the magnitude of the actual learning step in a
                # single scalar — easier to plot than 6-feature deltas.
                gradient_l1 = sum(abs(w.get(f, 0.0) - w_before.get(f, 0.0))
                                  for f in FEATURES)
                for feat in FEATURES:
                    default  = DEFAULT_WEIGHTS.get(feat, 0.0)
                    before   = w_before.get(feat, default)
                    after    = w.get(feat, default)
                    conn.execute(
                        """INSERT INTO weight_history
                           (recorded_at, token, trigger, feature,
                            weight_before, weight_after, n_updates, run_id,
                            reward, gradient_l1, profit_pct, regime)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (now, token, trigger, feat, before, after, n, run_id,
                         reward, gradient_l1, profit_pct, regime)
                    )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ADAPTIVE] _snapshot_weights error: {e}")

    # ── P1-6: weight reset ────────────────────────────────
    def reset_token(self, token: str) -> None:
        """Reset a token's OGD weights to DEFAULT_WEIGHTS and clear velocity/n.

        Writes a 'reset' trigger row to weight_history. Required for rollback path:
        when Tune Bot worsens performance, old weights learned under the previous
        config must be erased before re-bootstrapping.
        """
        self._ensure_token(token)
        old_w = dict(self._weights[token])
        self._weights[token]  = self._default_weights()
        self._velocity[token] = self._default_velocity()
        self._n[token]        = 0
        # Persist reset to DB
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = _connect()
            conn.execute("DELETE FROM token_weights WHERE token=?", (token,))
            n = 0
            for feat in FEATURES:
                conn.execute(
                    """INSERT INTO token_weights
                       (token, feature, weight, velocity, n_updates, updated_at)
                       VALUES (?,?,?,?,?,?)""",
                    (token, feat, DEFAULT_WEIGHTS[feat], 0.0, n, now)
                )
            for feat in FEATURES:
                conn.execute(
                    """INSERT INTO weight_history
                       (recorded_at, token, trigger, feature,
                        weight_before, weight_after, n_updates, run_id)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (now, token, "reset", feat,
                     old_w.get(feat, DEFAULT_WEIGHTS[feat]),
                     DEFAULT_WEIGHTS[feat], 0, None)
                )
            conn.commit()
            conn.close()
            print(f"[ADAPTIVE] reset_token({token}) — weights restored to defaults")
        except Exception as e:
            print(f"[ADAPTIVE] reset_token error {token}: {e}")


# ══════════════════════════════════════════════════════════
# CONCEPT DRIFT DETECTOR — Rolling Z-Score
# ══════════════════════════════════════════════════════════
class DriftDetector:
    """
    Tracks rolling distributions of ADX, ATR ratio, and RSI per token.

    When the current value is more than DRIFT_Z_THRESHOLD standard deviations
    from the rolling baseline, drift is flagged and thresholds are recalibrated:

    - adx_trend_threshold: raised in high-ADX environments, lowered when muted
    - rsi_oversold / rsi_overbought: widened in high-volatility, narrowed when calm
    - atr_highvol_mult: scales with rolling ATR baseline

    All rolling windows are persisted to DB so the baseline survives restarts.
    """

    _STATS = ("adx", "atr_ratio", "rsi")

    def __init__(self):
        self._windows: Dict[str, Dict[str, deque]] = {}
        _init_adaptive_tables()
        self._load_from_db()

    def _load_from_db(self):
        try:
            conn = _connect()
            rows = conn.execute(
                "SELECT token, stat_name, values_json FROM market_stats"
            ).fetchall()
            conn.close()
        except Exception:
            rows = []

        for token, stat_name, values_json in rows:
            if token not in self._windows:
                self._windows[token] = {s: deque(maxlen=DRIFT_WINDOW) for s in self._STATS}
            try:
                vals = json.loads(values_json) if values_json else []
                self._windows[token][stat_name] = deque(vals, maxlen=DRIFT_WINDOW)
            except Exception:
                pass

        if self._windows:
            print(f"[DRIFT] Loaded baselines for: {', '.join(sorted(self._windows.keys()))}")

    def _ensure_token(self, token: str):
        if token not in self._windows:
            self._windows[token] = {s: deque(maxlen=DRIFT_WINDOW) for s in self._STATS}

    def update(self, token: str, adx: float, atr_ratio: float, rsi: float):
        """Feed one observation. Call once per token per check cycle."""
        self._ensure_token(token)
        self._windows[token]["adx"].append(float(adx))
        self._windows[token]["atr_ratio"].append(float(atr_ratio))
        self._windows[token]["rsi"].append(float(rsi))

    def persist(self, token: str):
        """Persist rolling windows to DB. Call every few cycles (not every bar)."""
        if token not in self._windows:
            return
        try:
            conn = _connect()
            now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            for stat_name, dq in self._windows[token].items():
                vals = list(dq)
                mean = sum(vals) / len(vals) if vals else 0.0
                std  = (math.sqrt(sum((x - mean) ** 2 for x in vals) / len(vals))
                        if len(vals) > 1 else 1.0)
                conn.execute("""INSERT OR REPLACE INTO market_stats
                    (token, stat_name, values_json, rolling_mean, rolling_std,
                     n_samples, updated_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (token, stat_name, json.dumps(vals[-DRIFT_WINDOW:]),
                     round(mean, 4), round(std, 4), len(vals), now))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[DRIFT] persist error {token}: {e}")

    def z_score(self, token: str, stat_name: str, current: float) -> float:
        """Z-score of current vs rolling baseline. Returns 0.0 if insufficient data."""
        if token not in self._windows:
            return 0.0
        dq = self._windows[token].get(stat_name, deque())
        if len(dq) < DRIFT_MIN_SAMPLES:
            return 0.0
        vals = list(dq)
        mean = sum(vals) / len(vals)
        std  = math.sqrt(sum((x - mean) ** 2 for x in vals) / len(vals))
        return round((current - mean) / std, 2) if std > 0.001 else 0.0

    def get_dynamic_thresholds(self, token: str,
                                current_adx: float = 0.0,
                                current_atr: float = 0.0) -> Dict:
        """
        Return dynamically recalibrated thresholds for this token.

        Logic:
          ADX threshold  — track rolling ADX baseline; raise threshold in
                           high-ADX environments (everything looks trending),
                           lower it in low-ADX environments.
          RSI extremes   — widen when ATR is elevated (wider swings needed
                           to be meaningful), narrow in calm markets.
          Drift flag     — True when any Z-score > DRIFT_Z_THRESHOLD.
        """
        defaults = {
            "adx_trend_threshold": 25.0,
            "rsi_oversold":        _RSI_OVERSOLD,    # scalper default (was swing: 38.0)
            "rsi_overbought":      _RSI_OVERBOUGHT,  # scalper default (was swing: 62.0)
            "atr_highvol_mult":    2.5,
            "drift_detected":      False,
            "drift_z_adx":         0.0,
            "drift_z_atr":         0.0,
        }

        self._ensure_token(token)

        adx_dq = self._windows[token].get("adx", deque())
        atr_dq = self._windows[token].get("atr_ratio", deque())

        # ── ADX threshold recalibration ───────────────────
        if len(adx_dq) >= DRIFT_MIN_SAMPLES:
            adx_vals = list(adx_dq)
            adx_mean = sum(adx_vals) / len(adx_vals)
            # 85% of rolling mean; clamped to sane range
            defaults["adx_trend_threshold"] = round(
                max(18.0, min(35.0, adx_mean * 0.85)), 1)

        # ── RSI recalibration based on ATR volatility ─────
        if len(atr_dq) >= DRIFT_MIN_SAMPLES:
            atr_vals = list(atr_dq)
            atr_mean = sum(atr_vals) / len(atr_vals)
            # Higher rolling ATR → widen RSI extremes (±3 per 1% ATR).
            # Scalper base: oversold=45, overbought=55 (was swing: 38/62).
            # Clamps keep thresholds within scalper-appropriate ranges.
            vol_adj = round(min(atr_mean * 3.0, 8.0), 1)
            defaults["rsi_oversold"]   = round(max(35.0, min(50.0, _RSI_OVERSOLD  - vol_adj)), 1)
            defaults["rsi_overbought"] = round(max(50.0, min(65.0, _RSI_OVERBOUGHT + vol_adj)), 1)

        # ── Drift detection ───────────────────────────────
        z_adx = self.z_score(token, "adx",       current_adx)
        z_atr = self.z_score(token, "atr_ratio",  current_atr)
        drift = abs(z_adx) > DRIFT_Z_THRESHOLD or abs(z_atr) > DRIFT_Z_THRESHOLD

        if drift:
            print(f"[DRIFT] {token} — drift detected  Z_adx={z_adx:+.2f}  Z_atr={z_atr:+.2f}  "
                  f"adx_thr={defaults['adx_trend_threshold']}  "
                  f"rsi=[{defaults['rsi_oversold']},{defaults['rsi_overbought']}]")

        defaults["drift_detected"] = drift
        defaults["drift_z_adx"]    = z_adx
        defaults["drift_z_atr"]    = z_atr
        return defaults


# ══════════════════════════════════════════════════════════
# PORTFOLIO RISK LAYER
# ══════════════════════════════════════════════════════════
class PortfolioRiskLayer:
    """
    Enforces portfolio-level risk constraints before any signal fires.

    Guards (checked in order — first failure returns block):
      1. MAX_OPEN_POSITIONS   — total concurrent open signals
      2. MAX_SAME_DIRECTION   — max BUY or SELL positions simultaneously
      3. MAX_PORTFOLIO_RISK   — sum of all open SL exposures vs capital
      4. MAX_DRAWDOWN         — halt if recent P&L implies >20% drawdown
      5. Correlation warning  — more than 2 correlated alts in same direction

    Returns (allowed: bool, reason: str, warnings: list[str])
    """

    # Tokens that move together in BTC-driven markets — opening 3+ same direction
    # concentrates risk as a single leveraged BTC position.
    # Fix #34 (2026-05-22 cycle 9 audit): added XRP and ADA — both exhibit >0.65
    # Pearson correlation with BTC during 2024-2025 stress events. HBAR/POL remain
    # outside the set (genuinely lower-beta majors). SOL excluded from live (T-1).
    CORRELATED = frozenset({"BTC", "ETH", "BNB", "AVAX", "XRP", "ADA"})

    def check(self, token: str, signal: str,
              risk_per_trade_pct: float) -> Tuple[bool, str, list]:
        warnings = []
        try:
            conn = _connect()

            # 1. Open position counts
            row = conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN signal='BUY'  THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN signal='SELL' THEN 1 ELSE 0 END) "
                "FROM signals WHERE status='OPEN'"
            ).fetchone()
            total_open = int(row[0] or 0)
            buy_open   = int(row[1] or 0)
            sell_open  = int(row[2] or 0)

            if total_open >= MAX_OPEN_POSITIONS:
                conn.close()
                return (False,
                        f"Portfolio full ({total_open}/{MAX_OPEN_POSITIONS} open positions)",
                        [])

            if signal == "BUY" and buy_open >= MAX_SAME_DIRECTION:
                conn.close()
                return (False,
                        f"Max BUY positions reached ({buy_open}/{MAX_SAME_DIRECTION})",
                        [])

            if signal == "SELL" and sell_open >= MAX_SAME_DIRECTION:
                conn.close()
                return (False,
                        f"Max SELL positions reached ({sell_open}/{MAX_SAME_DIRECTION})",
                        [])

            # 2. Portfolio risk check — with risk-based sizing each position
            # risks exactly risk_per_trade_pct of capital
            existing_risk = total_open * risk_per_trade_pct
            this_risk     = risk_per_trade_pct
            total_risk    = existing_risk + this_risk

            if total_risk > MAX_PORTFOLIO_RISK_PCT:
                conn.close()
                return (False,
                        (f"Portfolio risk {total_risk:.1%} exceeds "
                         f"limit {MAX_PORTFOLIO_RISK_PCT:.0%} "
                         f"(existing {existing_risk:.1%} + this {this_risk:.1%})"),
                        [])

            # 3. Drawdown check — true peak-to-trough equity curve (H11 fix).
            # Replays all closed trades chronologically; tracks running equity peak.
            # Drawdown = (peak_equity - current_equity) / peak_equity.
            # Previous LIMIT 20 rolling window failed when wins diluted a losing streak.
            dd_rows = conn.execute(
                """SELECT r.profit_pct
                   FROM results r
                   JOIN signals s ON s.id = r.signal_id
                   WHERE r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
                     AND r.profit_pct IS NOT NULL
                   ORDER BY COALESCE(r.closed_at, s.timestamp) ASC"""
            ).fetchall()
            if len(dd_rows) >= 5:
                # CRIT-2 fix (Cycle 4, 2026-05-22): proper capital-impact math.
                # profit_pct is in percent units (e.g. -1.5 = -1.5% price move). Capital
                # impact per trade = profit_pct / 100 × notional_fraction. With
                # MAX_POSITION_PCT cap binding on all current SL sizes, notional_fraction
                # = MAX_POSITION_PCT. Previously multiplied by _RISK_PER_TRADE_PCT (0.01)
                # which is the WRONG multiplier and overstated drawdown by 5× — same
                # dimensional inconsistency as CRIT-1 in crypto_alert.py:966.
                equity = 1.0
                peak   = 1.0
                for row in dd_rows:
                    equity += (row[0] or 0.0) / 100.0 * _MAX_POSITION_PCT
                    if equity > peak:
                        peak = equity
                drawdown = (peak - equity) / peak if peak > 0 else 0.0
                if drawdown >= MAX_DRAWDOWN_PCT:
                    conn.close()
                    return (False,
                            (f"Drawdown protection: {drawdown * 100:.1f}% peak-to-trough "
                             f"over {len(dd_rows)} trades "
                             f"(limit {MAX_DRAWDOWN_PCT * 100:.0f}%)"),
                            [])

            # 4. Correlation gate (Cycle 4 Fix #13, 2026-05-22):
            #   WARN at 2 correlated same-direction positions (was warning-only before).
            #   BLOCK at 3+ — a BTC-led liquidation cascade would trigger all 3 SLs
            #   within minutes; 3 × 1% nominal risk = 3% capital impact but with high
            #   correlation the effective drawdown is closer to 3% in one event.
            #   This is the worst clustered-exposure scenario the previous warning-only
            #   guard let through silently. Promoted to BLOCK per the 2026-05-21 audit's
            #   "make correlation guard blocking" recommendation.
            if token in self.CORRELATED:
                # Fix #34b (2026-05-22 cycle 10): build the IN-clause from
                # self.CORRELATED so expanding the set propagates to the SQL
                # automatically. Previously the SQL hardcoded the original
                # 4-token list ('BTC','ETH','BNB','AVAX') — Fix #34 added XRP
                # and ADA to the frozenset but the SQL kept the old literal,
                # so XRP/ADA were checked at the trigger but never counted.
                _corr_placeholders = ",".join("?" * len(self.CORRELATED))
                corr_row = conn.execute(
                    f"SELECT COUNT(*) FROM signals "
                    f"WHERE status='OPEN' AND signal=? "
                    f"AND token IN ({_corr_placeholders})",
                    (signal, *sorted(self.CORRELATED))
                ).fetchone()
                corr_count = int(corr_row[0] or 0)
                if corr_count >= 3:
                    conn.close()
                    return (False,
                            (f"Correlation block: {corr_count} correlated alts "
                             f"already {signal} — clustered BTC-led exposure"),
                            [])
                if corr_count >= 2:
                    warnings.append(
                        f"Correlation risk: {corr_count} correlated alts "
                        f"already {signal} — clustered exposure")

            conn.close()

            summary = (f"Portfolio OK: {total_open+1}/{MAX_OPEN_POSITIONS} pos | "
                       f"risk {total_risk:.1%}/{MAX_PORTFOLIO_RISK_PCT:.0%}")
            return True, summary, warnings

        except Exception as e:
            print(f"[PORTFOLIO] CRITICAL check error — blocking for safety: {e}")
            return False, f"portfolio risk check failed ({e}) — blocking signal", []

    def get_status(self) -> dict:
        try:
            conn = _connect()
            row  = conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN signal='BUY'  THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN signal='SELL' THEN 1 ELSE 0 END) "
                "FROM signals WHERE status='OPEN'"
            ).fetchone()
            conn.close()
            n = int(row[0] or 0)
            return {
                "total_open":        n,
                "buy_open":          int(row[1] or 0),
                "sell_open":         int(row[2] or 0),
                "total_sl_exposure": round(n * _RISK_PER_TRADE_PCT, 4),
            }
        except Exception:
            return {"total_open": 0, "buy_open": 0, "sell_open": 0, "total_sl_exposure": 0}


# ══════════════════════════════════════════════════════════
# PERSISTENT SCALAR STATE
# ══════════════════════════════════════════════════════════
def save_scalar_state(key: str, value) -> None:
    """Persist a named scalar to bot_state table."""
    try:
        _init_adaptive_tables()
        conn = _connect()
        conn.execute("INSERT OR REPLACE INTO bot_state VALUES (?,?)",
                     (key, str(value)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[STATE] save {key}: {e}")


def load_scalar_state(key: str, default=None):
    """Load a named scalar from bot_state. Returns default if missing."""
    try:
        conn = _connect()
        row  = conn.execute("SELECT value FROM bot_state WHERE key=?",
                            (key,)).fetchone()
        conn.close()
        if row and row[0] is not None:
            return type(default)(row[0]) if default is not None else row[0]
    except Exception:
        pass
    return default


# ══════════════════════════════════════════════════════════
# ICT FEATURE SCORE EXTRACTOR
# Computes per-feature fractional contributions from ICT signal conditions.
# Used by OGD to credit/penalize the right features at signal close time.
# ══════════════════════════════════════════════════════════
def extract_ict_feature_scores(
    signal: str,
    fvg_quality: str,
    mss_quality: str,
    session: str,
    confidence: int,
    trend_1h: str,
    dr_location: str,
) -> Dict[str, float]:
    """Compute fractional ICT feature contribution scores for OGD gradient updates.

    Each score reflects how strongly that condition supported the signal quality.
    Scores are normalized so they sum to 1.0.

    Parameters
    ----------
    signal      : "BUY" or "SELL"
    fvg_quality : "HIGH" | "MEDIUM" | "LOW" | "NONE"
    mss_quality : "HIGH" | "MEDIUM" | "LOW" | "NONE"
    session     : "NY_AM_KZ" | "LONDON_KZ" | "ASIA_KZ" | "OVERNIGHT"
    confidence  : 0–10 composite confidence score
    trend_1h    : "STRONG_BULL" | "BULL" | "NEUTRAL" | "BEAR" | "STRONG_BEAR"
    dr_location : "PREMIUM" | "DISCOUNT" | "EQUILIBRIUM" | "UNKNOWN"
    """
    if signal == "BUY":
        trend_score = {"STRONG_BULL": 1.0, "BULL": 0.65, "NEUTRAL": 0.25,
                       "BEAR": 0.0, "STRONG_BEAR": 0.0}.get(trend_1h, 0.25)
        dr_score    = {"DISCOUNT": 1.0, "EQUILIBRIUM": 0.5,
                       "PREMIUM": 0.0, "UNKNOWN": 0.25}.get(dr_location, 0.25)
    else:
        trend_score = {"STRONG_BEAR": 1.0, "BEAR": 0.65, "NEUTRAL": 0.25,
                       "BULL": 0.0, "STRONG_BULL": 0.0}.get(trend_1h, 0.25)
        dr_score    = {"PREMIUM": 1.0, "EQUILIBRIUM": 0.5,
                       "DISCOUNT": 0.0, "UNKNOWN": 0.25}.get(dr_location, 0.25)

    raw: Dict[str, float] = {
        "fvg_quality":    max(_SCORE_FLOOR, _QUALITY_SCORE.get(fvg_quality, 0.0)),
        "mss_quality":    max(_SCORE_FLOOR, _QUALITY_SCORE.get(mss_quality, 0.0)),
        "session":        max(_SCORE_FLOOR, _SESSION_SCORE.get(session, 0.0)),
        # M13 KNOWN LIMITATION: confidence is derived from the 5 structural features above.
        # Including it here causes second-order double-counting: structural weights drive
        # confidence, which re-enters this gradient pipeline, modulating those same weights'
        # normalised shares. The direct loop (w_confidence → confidence integer) is correctly
        # broken in crypto_alert.py. This indirect loop is accepted given low signal frequency
        # (~34/year), hard weight caps (MAX=0.50, STEP=0.04), and degenerate protection (0.60).
        # Fix A (remove confidence from FEATURES entirely) deferred to post-live evaluation.
        "confidence":     max(_SCORE_FLOOR, max(0.0, min(1.0, (int(confidence) - 5) / 5.0))),
        "trend_strength": max(_SCORE_FLOOR, trend_score),
        "dr_location":    max(_SCORE_FLOOR, dr_score),
    }
    total = sum(raw.values())
    if total <= 0:
        return {f: round(1.0 / len(FEATURES), 4) for f in FEATURES}
    return {f: round(raw[f] / total, 4) for f in FEATURES}


# ══════════════════════════════════════════════════════════
# EV SCORING ENGINE (Task 13)
# ══════════════════════════════════════════════════════════
_EV_BASE_SQL = """
    SELECT
        COUNT(*) AS n,
        AVG(CASE WHEN r.result IN ('WIN','PARTIAL_TP2','PARTIAL_TP1','PARTIAL')
                 THEN 1.0 ELSE 0.0 END)                                    AS win_rate,
        AVG(CASE WHEN r.result IN ('WIN','PARTIAL_TP2','PARTIAL_TP1','PARTIAL')
                 THEN COALESCE(r.profit_pct, 0.0) ELSE 0.0 END)            AS avg_win_pct,
        AVG(CASE WHEN r.result IN ('LOSS','EXPIRED')
                 THEN COALESCE(r.profit_pct, 0.0) ELSE 0.0 END)            AS avg_loss_pct
    FROM signals s
    JOIN results r ON s.id = r.signal_id
    WHERE r.result IN ('WIN','PARTIAL_TP1','PARTIAL_TP2','PARTIAL','LOSS','EXPIRED')
    AND s.signal = ?
"""

# Bucket levels — most specific (L1) to broadest (L5).
# Each entry: (level_label, extra_WHERE, extra_params_from_args)
# Params are appended after the base signal param.
_EV_BUCKET_LEVELS = [
    ("L1", " AND s.token=? AND s.market_regime=? AND s.sweep_type=? AND s.dr_location=? AND s.mss_quality=? AND s.fvg_quality=?",
     lambda t, r, sw, dr, mq, fq: (t, r, sw, dr, mq, fq)),
    ("L2", " AND s.token=? AND s.market_regime=? AND s.sweep_type=? AND s.dr_location=?",
     lambda t, r, sw, dr, mq, fq: (t, r, sw, dr)),
    ("L3", " AND s.market_regime=? AND s.sweep_type=? AND s.dr_location=?",
     lambda t, r, sw, dr, mq, fq: (r, sw, dr)),
    ("L4", " AND s.market_regime=? AND s.sweep_type=?",
     lambda t, r, sw, dr, mq, fq: (r, sw)),
    ("L5", " AND s.market_regime=?",
     lambda t, r, sw, dr, mq, fq: (r,)),
]


def compute_ev_score(
    signal: str,
    token: str,
    regime: str,
    sweep_type: str,
    dr_location: str,
    mss_quality: str = "MEDIUM",
    fvg_quality:  str = "MEDIUM",
    min_n: int = SAMPLE_N_OBSERVE,
    strategy_version: str = None,  # H5: filter out pre-gate signals from EV population
) -> dict:
    """Hierarchical expected-value lookup from live signal history.

    Tries the most-specific bucket first; broadens if sample < min_n.

    Gate rule (enforced by caller in generate_signal):
      ev_status == "NEGATIVE" and sample_n >= SAMPLE_N_USABLE → reject signal.

    Returns
    -------
    ev_score     : net expectancy % per trade (positive = edge)
    ev_status    : "POSITIVE" | "NEGATIVE" | "INSUFFICIENT" | "NO_DATA"
    sample_n     : closed trades matched in the bucket
    bucket_level : "L1" .. "L5"
    win_rate, avg_win_pct, avg_loss_pct : raw stats
    label        : display string for Telegram / reports
    """
    _empty = {
        "ev_score": 0.0, "ev_status": "NO_DATA", "sample_n": 0,
        "bucket_level": "L0", "win_rate": 0.0,
        "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
        "label": "EV: NO_DATA",
    }
    try:
        conn = _connect()
        # H5: version_clause filters out pre-gate signals that skew EV population.
        version_clause  = " AND s.strategy_version = ?" if strategy_version else ""
        version_params  = (strategy_version,) if strategy_version else ()
        base_sql = _EV_BASE_SQL + version_clause
        for level, where_extra, params_fn in _EV_BUCKET_LEVELS:
            extra_params = params_fn(token, regime, sweep_type, dr_location,
                                     mss_quality, fvg_quality)
            row = conn.execute(
                base_sql + where_extra,
                (signal,) + version_params + extra_params,
            ).fetchone()
            n = int(row[0] or 0)
            if n >= min_n:
                wr   = float(row[1] or 0.0)
                awp  = float(row[2] or 0.0)
                alp  = float(row[3] or 0.0)
                ev   = round(wr * awp + (1 - wr) * alp, 4)
                if n < SAMPLE_N_OBSERVE:
                    status = "INSUFFICIENT"
                elif ev > 0:
                    status = "POSITIVE"
                else:
                    status = "NEGATIVE"
                conn.close()
                return {
                    "ev_score":     ev,
                    "ev_status":    status,
                    "sample_n":     n,
                    "bucket_level": level,
                    "win_rate":     round(wr, 3),
                    "avg_win_pct":  round(awp, 4),
                    "avg_loss_pct": round(alp, 4),
                    "label":        f"EV:{ev:+.3f}% {label_sample_size(n)} [{level}]",
                }
        conn.close()
        return _empty
    except Exception as e:
        print(f"[EV] compute_ev_score error: {e}")
        return _empty


# ══════════════════════════════════════════════════════════
# MODULE-LEVEL SINGLETONS (imported by crypto_alert.py)
# ══════════════════════════════════════════════════════════
weight_engine   = AdaptiveWeightEngine()
drift_detector  = DriftDetector()
portfolio_layer = PortfolioRiskLayer()
