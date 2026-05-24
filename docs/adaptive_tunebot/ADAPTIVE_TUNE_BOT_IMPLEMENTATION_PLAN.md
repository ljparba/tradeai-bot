# ADAPTIVE TUNE BOT — IMPLEMENTATION PLAN

**Document date:** 2026-05-19  
**Based on:** ADAPTIVE_LEARNING_READINESS_AUDIT.md  
**Current readiness score:** 4/10 (pre-fix) → ~6/10 (post-fix, this session)  
**Target readiness score:** 9/10 (after all phases complete)

---

## Status Snapshot — What This Session Already Fixed

The following audit findings were resolved in the same session as this plan. They are **done** and do not require further work.

| Item | Fix Applied |
|---|---|
| OGD weight collapse (dr_location=0.667) | Degenerate guard (>0.45 → fallback) + `decay_toward_default()` every 30 min |
| Tune Bot targeting dead parameters | Rewired to `FVG_MIN_QUALITY` + `MSS_MIN_QUALITY` in `strategy_engine.py` |
| Bootstrap re-processing all runs | Now scoped to `run_id` of current run only |
| Dead code (`calculate_weighted_score`, `count_confirmations`, `dyn_weights`) | Removed |
| RSI drift thresholds (swing 38/62 vs scalper 45/55) | Fixed in `tracker.py` |
| DB indexes missing | Added to `init_db()` and `init_backtest_db()` |
| `smt_confirmed` missing from schema | ALTER TABLE + INSERT updated |
| `_ADAP_FEATURES` legacy keys in tracker | Updated to ICT feature names |
| PARTIAL_TP1/PARTIAL_TP2 not in bootstrap | Added to `valid_outcomes` and reward table |
| `mark_expired()` naive datetime | Fixed to `datetime.now(timezone.utc)` |

**Remaining work starts below.**

---

## Section 1 — What Must Be Fixed Before Tune Bot Can Safely Optimize Anything

These are hard blockers. The Tune Bot must not apply any live config change until every item in this section is satisfied.

### 1.1 — Live Trading Data (BLOCKER — No Workaround)

**Problem:** The `signals` table has 0 rows. Every adaptive subsystem is running on defaults:
- EV scoring returns `NO_DATA` for every token/regime/session combination
- Per-token WR gate uses a fallback of `None` (no blocking)
- Dynamic `_conf_floor` is at its default of `5` (minimum possible)
- `_signal_threshold_adj` is `0` (no adjustment)

**Minimum data threshold before Tune Bot is trusted:**
- **30 closed live signals per token** — minimum for OGD activation
- **100 closed live signals per setup type** — minimum for EV gate to block
- **50 closed live signals total** — minimum for session/FVG quality WR comparisons to be statistically meaningful (CI < ±14pp)

**What to do:** Run the bot live with conservative `LIVE_CONFIG` (BUY-only, current gates) and accumulate at least 30 closed signals before triggering any Tune Bot application. This cannot be simulated — backtest data has different confidence values than live data because the formulas diverged.

### 1.2 — Backtest Confidence Formula Divergence (BLOCKER for walk-forward trust)

**Problem:** `backtest.py` L548-559 computes confidence using hardcoded binary bonuses (`trend_bonus`, `fvg_q_bonus`, `session_bonus`). `crypto_alert.py` uses the OGD-weighted ICT quality score. As OGD learns from live trades, the two formulas diverge. Walk-forward WR in the backtest will measure the static formula — not the adaptive formula that actually runs live.

**Consequence:** The Tune Bot's train/test split validation uses backtest data computed with the old formula. A session or FVG gate recommended by backtest WR analysis may not transfer to live where confidence scores are different.

**Required fix:** Align backtest confidence formula with the live OGD-weighted formula. The backtest should call `extract_ict_feature_scores()` + apply `DEFAULT_WEIGHTS` (not learned OGD weights — those are live-specific). This makes backtest WR statistics computed on the same confidence distribution as live signals.

**File:** `backtest.py` lines 543-559  
**Function:** `run_backtest_token()` — confidence block

### 1.3 — No Weight Versioning or Rollback (BLOCKER for safe apply)

**Problem:** When Tune Bot applies a gate change (e.g. `fvg_min_quality: MEDIUM → HIGH`), there is no record of:
- What the value was before
- What the WR was at time of change
- Whether performance improved or worsened after change
- How to revert

A file backup is created (`strategy_engine.bak.YYYYMMDD_HHMMSS.py`) but there is no database record, no UI rollback button, and no automated performance-based revert.

**Required:** A `tune_history` database table and a rollback endpoint. See Section 2.

### 1.4 — No Frequency Gate on Tune Bot Application

**Problem:** Nothing prevents the user from clicking Apply 10 times in a row on insufficient data. Each application changes `strategy_engine.py` without any cooldown, minimum-signals-since-last-change check, or improvement verification.

**Required:** Enforce a minimum number of NEW closed signals since the last Tune Bot application before another change is allowed. Proposed: 50 new signals minimum, or 14 calendar days, whichever is longer.

---

## Section 2 — Required Database Schema Changes

### 2.1 — `tune_history` Table (NEW)

Tracks every Tune Bot preview and application event. Required for rollback, improvement measurement, and frequency gating.

```sql
CREATE TABLE IF NOT EXISTS tune_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    applied_at      TEXT    NOT NULL,          -- UTC timestamp
    param           TEXT    NOT NULL,          -- 'FVG_MIN_QUALITY', 'MSS_MIN_QUALITY', etc.
    old_val         TEXT    NOT NULL,          -- previous value (serialized)
    new_val         TEXT    NOT NULL,          -- new value applied
    signals_at_apply INTEGER NOT NULL,        -- total closed signals at time of apply
    backtest_run_id  INTEGER,                  -- run_id that triggered the recommendation
    train_wr         REAL,                     -- WR of train split at time of apply
    test_wr          REAL,                     -- WR of test split at time of apply
    post_apply_wr    REAL,                     -- measured WR of new signals AFTER this change (filled later)
    post_apply_n     INTEGER,                  -- how many signals used to measure post_apply_wr
    status          TEXT    DEFAULT 'APPLIED', -- 'APPLIED' | 'ROLLED_BACK' | 'VERIFIED_BETTER' | 'VERIFIED_WORSE'
    backup_file     TEXT,                      -- path to strategy_engine.bak.* created at apply time
    notes           TEXT                       -- human notes or auto-verdict
)
```

**Written by:** `apply_tune_adjustments()` in `tracker.py`  
**Read by:** rollback endpoint, Tune Bot frequency gate, performance verification

### 2.2 — `weight_history` Table (NEW)

Tracks OGD weight snapshots over time. Required to detect drift, measure learning progress, and support weight rollback.

```sql
CREATE TABLE IF NOT EXISTS weight_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at     TEXT    NOT NULL,          -- UTC timestamp
    token           TEXT    NOT NULL,
    trigger         TEXT    NOT NULL,          -- 'bootstrap' | 'live_update' | 'decay' | 'reset'
    feature         TEXT    NOT NULL,
    weight_before   REAL    NOT NULL,
    weight_after    REAL    NOT NULL,
    n_updates       INTEGER NOT NULL,
    run_id          INTEGER                    -- backtest run_id if trigger='bootstrap'
)
```

**Written by:** `AdaptiveWeightEngine.update()` (sampled every N updates, not every update) and `bootstrap_from_backtest()` (before/after snapshot)  
**Read by:** adaptive weights dashboard tab

### 2.3 — `backtest_signals` — Missing `ifvg_direction` Metadata (MEDIUM)

Current schema already has `ifvg_present` and `ifvg_direction` as ALTER TABLE additions, but they are only populated in runs 27+ (ICT-aware runs). No action needed for schema — data is already being saved correctly in new runs.

### 2.4 — `bot_state` — Add Tune Bot Frequency Key

Add two new scalar state keys to `bot_state`:
- `tune_last_applied_at` — UTC timestamp of last Tune Bot application
- `tune_signals_at_last_apply` — closed signal count at last apply

**Written by:** `apply_tune_adjustments()`  
**Read by:** `calculate_tune_preview()` to enforce frequency gate

### 2.5 — `strategy_version` on `signals` Table

The `signals` table already has a `strategy_version` column (added in H5). The Tune Bot must **increment the strategy version** after every configuration change so that EV scoring isolates results by strategy generation. If version is not bumped, EV computed from pre-change signals will dilute EV from post-change signals.

**Action:** When Tune Bot applies a change, call `save_scalar_state("strategy_version", new_version)` and update `STRATEGY_VERSION` in `crypto_alert.py`.

---

## Section 3 — Required Backtest Result Metadata

The following columns must be present and populated in `backtest_signals` for the Tune Bot to compute meaningful WR splits. Most are already present in runs 27+.

| Column | Type | Purpose | Status |
|---|---|---|---|
| `fvg_quality` | TEXT | FVG quality gate analysis | Present (runs 27+) |
| `mss_quality` | TEXT | MSS quality gate analysis | Present (runs 27+) |
| `session` | TEXT | Session performance split | Present (runs 27+) |
| `hour_utc` | INTEGER | Intra-session performance | Present (runs 27+) |
| `regime` | TEXT | Regime performance split | Present (all runs) |
| `confidence` | INTEGER | Confidence level breakdown | Present (all runs) |
| `outcome` | TEXT | WIN/LOSS/PARTIAL_TP1/PARTIAL_TP2/EXPIRED | Present (all runs) |
| `net_tp1_pct` | REAL | Net expectancy calculation | Present (runs 27+) |
| `net_sl_pct` | REAL | Net expectancy calculation | Present (runs 27+) |
| `net_rr1` | REAL | Risk/reward validation | Present (runs 27+) |
| `sweep_type` | TEXT | BSL vs SSL breakdown | Present (runs 27+) |
| `trend_1h` | TEXT | HTF alignment analysis | Present (runs 27+) |
| `bias_4h` | TEXT | 4H bias alignment analysis | Present (runs 27+) |
| `ifvg_present` | INTEGER | IFVG impact analysis | Present (runs 27+) |
| `smt_confirmed` | INTEGER | SMT divergence analysis | Fixed this session |
| `dr_location` | TEXT | Dealing range analysis | Present (runs 27+) |
| `entry_type` | TEXT | Entry reaction analysis | Present (runs 27+) |
| `breakeven_wr` | REAL | Break-even WR for net expectancy gate | Present (runs 27+) |

**Missing / Not Yet Implemented:**
- `rr2`, `rr3` — second and third TP risk/reward ratios — not stored in backtest
- `ifvg_quality` — quality score for iFVG itself (currently only `ifvg_present` is stored)
- `signal_latency_ms` — time from sweep detection to entry (execution quality metric)

The first two are research-level additions and are not needed for Tune Bot Phase 1. The third requires timer instrumentation in the backtest loop.

---

## Section 4 — Required Adaptive Learning Persistence Changes

### 4.1 — Weight Snapshot on Bootstrap (implement in `adaptive_engine.py`)

Before and after `bootstrap_from_backtest()` runs, write a before/after snapshot to `weight_history` for each token. This gives a diff of what the bootstrap changed.

```python
# In bootstrap_from_backtest() — before OGD updates:
_snapshot_weights_before(run_id)

# After _persist_all():
_snapshot_weights_after(run_id)
```

### 4.2 — Weight Reset Command (implement in `adaptive_engine.py`)

Add a `reset_token(token)` method that:
1. Deletes the token's rows from `token_weights`
2. Re-initializes to `DEFAULT_WEIGHTS`
3. Resets `_n[token]` to 0 and `_velocity[token]` to zero vector
4. Writes to `weight_history` with `trigger='reset'`

This is required for the rollback path: if Tune Bot worsens performance, OGD weights that were learned under the old config need to be reset before re-bootstrapping under the new config.

### 4.3 — OGD Health Status (implement in `adaptive_engine.py`)

Add a `health_check()` method that returns a per-token health dict:

```python
def health_check(self) -> Dict[str, dict]:
    # For each token:
    # - max_weight: max feature weight
    # - is_degenerate: bool (max > 0.45)
    # - n_updates: total updates received
    # - last_updated: timestamp from DB
    # - weight_entropy: -sum(w * log(w)) — low entropy = collapsed state
```

This powers the health indicator in the adaptive weights dashboard tab.

### 4.4 — Live OGD Update Counter

When `_trigger_weight_update()` fires from a live signal close, write the update timestamp to `bot_state` as `ogd_last_live_update`. The `decay_toward_default()` call in the main loop should only fire if the token has not had a live update in > 7 days (prevents decay from fighting valid recent learning).

---

## Section 5 — Required Dashboard Changes (tracker_html.py + tracker.py)

### 5.1 — Adaptive Weights Tab — OGD Health Indicators

**Current state:** Shows feature weight bars per token.  
**Required additions:**
- Health badge per token: `HEALTHY` (green) / `DEGENERATE` (red) / `LEARNING` (yellow)
- Weight entropy bar: shows how evenly spread weights are (low entropy = collapsed)
- `n_updates` counter with "OGD active" vs "using defaults" indicator
- Last updated timestamp
- Weight trend: sparkline or arrow showing if weights are moving toward or away from defaults

**Files:** `tracker_html.py` (JavaScript rendering), `tracker.py` (`_get_adaptive_weights_raw()`)

### 5.2 — Tune Bot Panel — Evidence Display

**Current state:** Shows param name, old → new value, reason text.  
**Required additions:**
- Sample size confidence interval displayed per finding (e.g. "n=23 → ±21pp CI — borderline")
- WR comparison table: HIGH vs MEDIUM vs LOW for each quality gate, with n shown
- Session breakdown table: all sessions with WR and n
- Walk-forward gap prominently displayed ("Train WR 58% vs Test WR 44% — potential overfit")
- Warning banner if n < 50 for the winning bucket
- Explicit "This will modify strategy_engine.py LIVE_CONFIG" warning before Apply button

**Files:** `tracker_html.py` (renderTunePreview function)

### 5.3 — Tune Bot Panel — Manual Approval Flow

The current UI has a single "Apply Changes" button. Replace with a two-step confirmation:

**Step 1 — Preview:** User sees evidence panel with all statistics. "Apply" button is labeled "Review & Confirm".

**Step 2 — Confirm:** A confirmation overlay appears showing:
- Exact line that will change in `strategy_engine.py`
- Current vs proposed value
- Evidence summary (WR comparison, n, CI)
- Warning: "Bot must be restarted after applying"
- Checkbox: "I understand this changes live gate logic and I have reviewed the evidence"
- Final "Confirm Apply" button (only active when checkbox is checked)

**Files:** `tracker_html.py` (new `confirmTune()` function replacing `applyTune()`)

### 5.4 — Tune Bot Panel — History and Rollback

Add a "Tune History" section below the preview panel:

```
| Date | Param | Change | Signals After | WR After | Status | Action |
| 2026-05-20 | FVG_MIN_QUALITY | MEDIUM→HIGH | 47 | 52% | VERIFIED_BETTER | — |
| 2026-06-01 | MSS_MIN_QUALITY | LOW→MEDIUM  | 12 | 38% | NEEDS_REVIEW    | [Rollback] |
```

**Rollback button** calls `POST /api/backtest/tune-rollback` with the `tune_history.id`. The endpoint:
1. Reads the `old_val` from `tune_history`
2. Writes it back to `strategy_engine.py` LIVE_CONFIG (regex replace)
3. Updates `tune_history.status = 'ROLLED_BACK'`
4. Records a new backup file

**Files:** `tracker_html.py` (history table), `tracker.py` (new `rollback_tune_adjustment()` function + `/api/backtest/tune-rollback` endpoint)

### 5.5 — Frequency Gate Display

Show in the Tune Bot panel footer:
- "Next tune available: in 12 days or after 38 more closed signals (whichever comes first)"
- Grays out the "Open Tune Preview" button if frequency gate blocks it

---

## Section 6 — Anti-Overfitting Guardrails

These are hard statistical gates. A Tune Bot proposal that fails any of them must not be applied, even if the user tries to override via the UI.

### 6.1 — Minimum Sample Size per Bucket

| Change Type | Minimum n (winning bucket) | Minimum n (losing bucket) |
|---|---|---|
| FVG_MIN_QUALITY raise | 30 signals at HIGH quality | 20 signals at MEDIUM quality |
| MSS_MIN_QUALITY raise | 30 signals at HIGH quality | 20 signals at MEDIUM quality |
| Session removal | 30 signals in that session | n/a |
| Conf floor increase | 25 signals at conf <= threshold | n/a |

### 6.2 — Train/Test Agreement (already implemented)

A gate change is only proposed if the finding holds in BOTH the first 60% AND last 40% of backtest signals sorted by timestamp. If train shows HIGH > MEDIUM but test does not, the change is suppressed and the conflict logged to `validation_notes`.

**Do not relax this gate.** With n=16 signals (Run #37), the entire test set has 6-7 signals — statistically meaningless. The gate correctly refuses to fire in this regime.

### 6.3 — Walk-Forward Gap Warning

If the backtest walk-forward overfit gap (train WR - test WR) exceeds **15 percentage points**, display a prominent warning: "High overfit risk — train/test gap is {X}pp. Recommendations may not transfer to live." Do not block the preview but block Apply if gap > 25pp.

### 6.4 — Confidence Interval Display

Compute and display the 95% Wilson confidence interval on WR for each bucket. Do not recommend a gate change if the CI of the winning bucket overlaps with the CI of the losing bucket.

Formula: Wilson CI, n = sample size, p = win rate fraction.

```python
import math
def wilson_ci(n, wins, z=1.96):
    if n == 0: return (0.0, 1.0)
    p = wins / n
    center = (p + z**2 / (2*n)) / (1 + z**2 / n)
    margin = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / (1 + z**2/n)
    return round(max(0, center - margin), 3), round(min(1, center + margin), 3)
```

### 6.5 — No More Than 2 Active Tune Bot Changes

Track in `tune_history` how many changes are currently in `APPLIED` status (not yet verified). If 2 or more changes are awaiting performance verification, block new Apply requests with: "Two changes are already pending verification. Wait for performance data before tuning again."

### 6.6 — OGD Weight Sanity Check Before Apply

Before any Tune Bot application, check `weight_engine.health_check()`. If any token has `is_degenerate=True`, display a warning: "OGD weights for {token} are in a degenerate state. Confidence scores may be unreliable. Consider running a new backtest first to seed fresh weights." Allow Apply but require checkbox acknowledgment.

### 6.7 — Strategy Version Isolation

All future EV scores and WR measurements must be computed from signals generated under the same strategy version. When Tune Bot increments the strategy version, old signals from prior versions are excluded from quality analysis (they used different gates). This prevents contamination between pre-change and post-change performance data.

---

## Section 7 — Manual Approval Flow Before Live Config Changes

The full approval sequence, end to end:

```
User clicks "Open Tune Preview"
         |
         v
GET /api/backtest/tune-preview
   [calculate_tune_preview()]
         |
         +---> Frequency gate check (min signals, min days since last apply)
         |     FAIL: show "Not enough data yet — X signals needed, Y days remaining"
         |
         +---> Load most recent backtest run (run_id)
         |
         +---> Filter to ICT-quality signals (fvg_quality != NONE)
         |     < 30 signals: show "Need X more ICT signals"
         |
         +---> Compute WR by FVG quality, MSS quality, session, confidence
         |
         +---> Check train/test agreement for each proposed change
         |
         +---> Compute Wilson CI for each bucket
         |
         +---> Check CI overlap — if overlapping, do not propose change
         |
         v
PREVIEW panel rendered
   - Evidence table (WR by quality, session)
   - Train/test split agreement results
   - Walk-forward gap warning (if > 15pp)
   - CI ranges per bucket
   - Proposed changes list (empty if no safe changes found)
         |
         v (only if changes proposed)
User clicks "Review & Confirm"
         |
         v
CONFIRMATION overlay
   - Exact file diff: strategy_engine.py LIVE_CONFIG
   - Old value highlighted in red, new value in green
   - Evidence summary (1-line per change)
   - OGD health warning (if any token is degenerate)
   - Warning: "Bot must be manually restarted after applying"
   - Checkbox: "I confirm I have reviewed the evidence and accept the change"
         |
         v (checkbox checked)
"Confirm Apply" button becomes active
         |
User clicks "Confirm Apply"
         |
         v
POST /api/backtest/tune-apply
   [apply_tune_adjustments()]
         |
         +---> Validate all params (whitelist check)
         |
         +---> Re-read live signal count (ensures no race condition since preview)
         |
         +---> Create backup: strategy_engine.bak.YYYYMMDD_HHMMSS.py
         |
         +---> Apply regex change to strategy_engine.py LIVE_CONFIG block only
         |
         +---> Write to tune_history table
         |
         +---> Update bot_state: tune_last_applied_at, tune_signals_at_last_apply
         |
         +---> Increment strategy_version in bot_state
         |
         v
SUCCESS response
   - "Applied. Restart the bot to activate new config."
   - Backup file location shown
   - tune_history row ID shown for rollback reference
```

---

## Section 8 — Exact File-by-File Implementation Tasks

Tasks are ordered within each phase. Do not start a phase until the previous phase is verified complete.

---

### PHASE 0 — Already Complete (Verify Only)

| Task | File | Verify By |
|---|---|---|
| P0-1: Degenerate weight guard | `crypto_alert.py` | `grep "_max_w > 0.45"` |
| P0-2: decay_toward_default() called | `crypto_alert.py` | `grep "decay_toward_default"` |
| P0-3: Bootstrap scoped to run_id | `backtest.py` | `grep "run_id=run_id"` |
| P0-4: Tune Bot targets FVG/MSS quality | `tracker.py` | `grep "FVG_MIN_QUALITY"` |
| P0-5: apply_tune writes strategy_engine.py | `tracker.py` | `grep "strategy_engine.py"` |
| P0-6: DB indexes created | `backtest.py`, `crypto_alert.py` | `grep "CREATE INDEX"` |
| P0-7: smt_confirmed in schema | `backtest.py` | `grep "smt_confirmed.*INTEGER"` |

---

### PHASE 1 — Foundation for Safe Tuning

These tasks do not require live data. Do before first live run.

**P1-1: Align backtest confidence formula with live OGD formula**  
- **File:** `backtest.py` lines 543-559  
- **Change:** Replace hardcoded `trend_bonus + fvg_q_bonus + ...` block with a call to `extract_ict_feature_scores()` + `DEFAULT_WEIGHTS`-weighted quality score (same math as `generate_signal()`, minus the OGD lookup which is not applicable in backtest)  
- **Why:** Makes walk-forward WR statistics computed on the same confidence distribution as live signals. Without this, a 58% WR in backtest may correspond to a different confidence distribution than 58% WR live.  
- **Risk:** May shift confidence values and change signal counts in future backtest runs. Accept this — accuracy of comparison is worth it.

**P1-2: Add `tune_history` table to database init**  
- **File:** `adaptive_engine.py` `_init_adaptive_tables()` OR new `init_tune_db()` in `tracker.py`  
- **Change:** Add `CREATE TABLE IF NOT EXISTS tune_history (...)` per schema in Section 2.1  
- **Why:** Required for rollback, frequency gate, and performance verification.

**P1-3: Add `weight_history` table to database init**  
- **File:** `adaptive_engine.py` `_init_adaptive_tables()`  
- **Change:** Add `CREATE TABLE IF NOT EXISTS weight_history (...)` per schema in Section 2.2  
- **Why:** Required to track OGD drift, detect collapse early, and support weight rollback.

**P1-4: Add OGD health_check() method**  
- **File:** `adaptive_engine.py` — add method to `AdaptiveWeightEngine`  
- **Change:** Returns `{token: {max_weight, is_degenerate, n_updates, weight_entropy, last_updated}}`  
- **Why:** Powers health badges in dashboard; required for P1-5.

**P1-5: Add weight snapshot to bootstrap**  
- **File:** `adaptive_engine.py` `bootstrap_from_backtest()`  
- **Change:** Call `_snapshot_weights(trigger='bootstrap', run_id=run_id)` before and after OGD updates; write rows to `weight_history`  
- **Why:** Bootstrap is the primary source of weight changes right now; must be tracked.

**P1-6: Add `reset_token()` method to AdaptiveWeightEngine**  
- **File:** `adaptive_engine.py`  
- **Change:** New method that resets a token's weights to `DEFAULT_WEIGHTS`, zeroes velocity and n, deletes from DB, writes `weight_history` entry with `trigger='reset'`  
- **Why:** Required for rollback path when Tune Bot worsens performance.

**P1-7: Write tune_history on apply**  
- **File:** `tracker.py` `apply_tune_adjustments()`  
- **Change:** After successful file write, `INSERT INTO tune_history (...)` with all fields except `post_apply_wr`/`post_apply_n` (filled later)  
- **Also:** Write `tune_last_applied_at` and `tune_signals_at_last_apply` to `bot_state`

**P1-8: Frequency gate in calculate_tune_preview()**  
- **File:** `tracker.py` `calculate_tune_preview()`  
- **Change:** Read `tune_last_applied_at` and `tune_signals_at_last_apply` from `bot_state`. Read current closed signal count. If `(now - last_applied) < 14 days AND new_signals_since < 50`, return `{"ok": False, "error": "Frequency gate: need 50 new signals or 14 days since last tune..."}`.

**P1-9: Add rollback endpoint and function**  
- **File:** `tracker.py`  
- **Change:** New `rollback_tune_adjustment(tune_history_id)` function + `POST /api/backtest/tune-rollback` handler  
- **Logic:** Read `old_val` from `tune_history`, regex-write back to `strategy_engine.py`, update `status='ROLLED_BACK'`, create backup, write to `bot_state`.

**P1-10: Post-apply WR measurement**  
- **File:** `tracker.py`  
- **Change:** New `update_tune_history_post_apply()` that reads closed signals created AFTER `applied_at` from the live `results` table, computes WR, updates `tune_history.post_apply_wr` and `post_apply_n`, and sets `status` to `VERIFIED_BETTER` or `VERIFIED_WORSE`  
- **When called:** In `load_performance_state()` in `crypto_alert.py` — check if any `tune_history` rows with `status='APPLIED'` have enough post-apply signals (>= 30) to compute WR verdict.

---

### PHASE 2 — Expanded Tune Bot Parameters

Only start after Phase 1 is complete and bot has run live for at least 2 weeks.

**P2-1: Add `SESSION_LIQUID_HOURS` tuning**  
- **File:** `tracker.py` `calculate_tune_preview()`  
- **Change:** If session WR < 38% in BOTH train AND test with n >= 30, propose removing that session's hours from `LIVE_CONFIG.liquid_hours`.  
- **File:** `tracker.py` `apply_tune_adjustments()`  
- **Change:** Add `SESSION_LIQUID_HOURS` param handler; regex-edit `LIVE_CONFIG.liquid_hours` list in `strategy_engine.py`.  
- **Validation:** Verify the resulting `liquid_hours` list always has >= 4 hours (minimum trading window — never allow all sessions to be blocked).

**P2-2: Add confidence floor tuning via `bot_state`**  
- **File:** `tracker.py`  
- **Change:** If `conf <= 6` signals show WR < 40% with n >= 25 in BOTH halves, propose `CONF_FLOOR_RAISE`. Apply by writing `save_scalar_state("conf_floor", new_value)`.  
- **No file edit needed** — `_conf_floor` is read from `bot_state` at startup.  
- **Validation:** Must be integer in [5, 8] (max floor 8, or bot generates almost no signals).

**P2-3: Add OGD hyperparameter tuning**  
- **File:** `adaptive_engine.py` — expose `LEARNING_RATE` and `MOMENTUM` as class-level config  
- **File:** `tracker.py` — add `OGD_LEARNING_RATE` and `OGD_MOMENTUM` params  
- **Apply by:** writing to `bot_state`; reading at `AdaptiveWeightEngine.__init__()` via `load_scalar_state()`  
- **Validation:** `LEARNING_RATE` in [0.001, 0.02]; `MOMENTUM` in [0.5, 0.95]  
- **Note:** This is low-priority and optional. OGD convergence is robust to hyperparameter choice in this regime.

---

### PHASE 3 — Dashboard Completions

**P3-1: OGD health badges in adaptive weights tab**  
- **File:** `tracker_html.py` — `renderAdaptiveWeights()` function  
- **Change:** For each token, call `GET /api/adaptive/health` to get health status. Display `HEALTHY` / `DEGENERATE` / `LEARNING` badge next to token name.  
- **File:** `tracker.py` — new `GET /api/adaptive/health` endpoint calling `weight_engine.health_check()`

**P3-2: Two-step confirmation overlay**  
- **File:** `tracker_html.py`  
- **Change:** Replace `applyTune()` → `confirmTune()` that shows overlay with file diff, evidence summary, checkbox, and final confirm button.

**P3-3: Tune history table**  
- **File:** `tracker_html.py` — add history table below Tune Bot preview panel  
- **File:** `tracker.py` — new `GET /api/backtest/tune-history` endpoint  
- **Change:** Display all `tune_history` rows with status badges and optional Rollback button for `APPLIED` rows.

**P3-4: Frequency gate UI indicator**  
- **File:** `tracker_html.py`  
- **Change:** In Tune Bot footer, show "Next tune available in X days / Y signals" based on frequency gate response.

**P3-5: Walk-forward gap warning banner**  
- **File:** `tracker_html.py`  
- **Change:** If `validation_notes` contains a walk-forward gap > 15pp, show a yellow warning banner at the top of the Tune Bot panel.

---

## Section 9 — Testing Checklist

### 9.1 — Pre-Live Checklist (run before starting live trading)

- [ ] `python -m py_compile crypto_alert.py adaptive_engine.py backtest.py tracker.py strategy_engine.py` — all pass
- [ ] `python backtest.py` — completes without error; `init_backtest_db()` creates `smt_confirmed` column; index on `run_id` created
- [ ] After backtest: `weight_history` table has before/after rows for the bootstrap run
- [ ] `python crypto_alert.py` dry-run: `init_db()` creates `signals`, `results`, `rejections` tables; indexes created; `weight_engine` loads 7 tokens from `token_weights`
- [ ] Degenerate weight guard test: manually set a token weight to 0.8 in DB, verify `[ADAPTIVE] degenerate weights` message appears and defaults are used
- [ ] `decay_toward_default()` test: run 10 cycles manually, verify token weights move toward `DEFAULT_WEIGHTS`
- [ ] `read_bot_values()` test: returns `fvg_min_quality=MEDIUM`, `mss_min_quality=MEDIUM` from current `strategy_engine.py`
- [ ] Tune Bot preview test with < 30 signals: confirm `{"ok": false, "error": "Only X backtest signals..."}` returned
- [ ] `apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": "HIGH"}])`: verify `strategy_engine.py` LIVE_CONFIG changed; BACKTEST_CONFIG unchanged; backup file created
- [ ] Rollback test: after applying, call rollback; verify `strategy_engine.py` reverts; `tune_history.status = ROLLED_BACK`

### 9.2 — Post-Live-Data Checklist (run after 30+ closed signals)

- [ ] EV scoring: `compute_ev_score()` returns non-`NO_DATA` for at least one token/regime combo
- [ ] Per-token WR gate: `STATE[token]["recent_wr"]` is non-None for tokens with >= 30 closed results
- [ ] `_conf_floor` has moved from default `5` to at least `6` if WR is below threshold
- [ ] Tune Bot preview with live data: FVG quality WR table populated with real live signal data (not backtest proxy)
- [ ] Frequency gate: try to Apply twice within 14 days with < 50 new signals — confirm blocked
- [ ] `tune_history` table: verify row written after Apply; `post_apply_wr` updated after 30+ post-apply signals
- [ ] Weight history sparkline: visible in adaptive weights dashboard tab showing drift over time

### 9.3 — Regression Checklist (run after any Tune Bot application)

- [ ] `python -m py_compile strategy_engine.py` — passes
- [ ] `evaluate_setup()` unit test with the changed parameter (e.g., if `fvg_min_quality` raised to HIGH, verify that a MEDIUM FVG signal is now rejected by `evaluate_setup()` with the new LIVE_CONFIG)
- [ ] `python backtest.py` — runs cleanly with the new `LIVE_CONFIG` loaded (backtest uses BACKTEST_CONFIG, but the import must not break)
- [ ] Dashboard loads: `GET /api/health` → 200; `GET /api/backtest/history` → 200 with backtest list; `GET /api/adaptive/weights` → 200 with 7 tokens
- [ ] Signal is generated by the live bot at least once within 48 hours (confirms gate is not over-tight)

---

## Section 10 — Rollback Plan if Tuning Worsens Performance

### Trigger Conditions

A rollback should be considered when any of the following are observed after a Tune Bot application:

| Metric | Rollback Threshold | How to Measure |
|---|---|---|
| Post-apply WR | Drops > 10pp vs pre-apply WR | `tune_history.post_apply_wr` vs `train_wr` |
| Signal frequency | Drops > 50% | Signals per week before vs after |
| EV score | Goes NEGATIVE for the changed parameter bucket | `compute_ev_score()` for that FVG/MSS quality level |
| Consecutive losses | 5+ losses in a row post-apply | `results` table ordered by `closed_at` |
| Kill switch fired | Daily loss limit hit 2x in 7 days post-apply | `bot_state.daily_loss_count` history |

### Automated Detection

In `load_performance_state()` (runs every 30 minutes):
1. Read `tune_history` rows with `status='APPLIED'`
2. For each, query results since `applied_at`
3. If `n >= 30` and `post_apply_wr < pre_apply_wr - 10`: update `status='VERIFIED_WORSE'`; send Telegram alert: "⚠ Tune Bot: {param} change may be hurting performance. WR {post_apply_wr}% vs pre-apply {pre_apply_wr}%. Consider rollback."
4. If `n >= 30` and `post_apply_wr >= pre_apply_wr - 5`: update `status='VERIFIED_BETTER'`

### Manual Rollback Procedure

**Step 1 — Via Dashboard (fastest):**
1. Open dashboard → Backtest tab → Tune History section
2. Find the row with `status='VERIFIED_WORSE'` or `status='APPLIED'`
3. Click "Rollback" button
4. Confirm in the overlay
5. **Restart the bot** — strategy_engine.py is re-loaded on restart only

**Step 2 — Via File (if dashboard is down):**
1. Find the backup file path from `tune_history.backup_file`
2. `copy backups\strategy_engine.bak.YYYYMMDD_HHMMSS.py strategy_engine.py`
3. Restart the bot

**Step 3 — OGD weight rollback (if weights also need resetting):**
After rolling back `strategy_engine.py`, run in Python:
```python
from adaptive_engine import weight_engine
for token in ["BTC", "ETH", "SOL", "XRP", "HBAR", "LINK", "AVAX"]:
    weight_engine.reset_token(token)
print("All weights reset to defaults")
```
Then run a new backtest to re-seed weights under the reverted config.

### What Is NOT a Rollback Trigger

- WR drops in first 5-10 signals after apply (expected variance — not enough data)
- Missing signals for 12-24 hours (normal for strict gates)
- Single large loss event (covered by existing risk management, not a tuning failure)

---

## Implementation Priority Order

```
CRITICAL NOW — before first live run:
  P0 verification (confirm this session's fixes are in place)
  P1-1  Align backtest confidence formula
  P1-2  tune_history table
  P1-3  weight_history table
  P1-4  OGD health_check()
  P1-5  Weight snapshot on bootstrap
  P1-6  reset_token() method
  P1-7  Write tune_history on apply
  P1-8  Frequency gate

HIGH — start live trading then implement:
  P1-9  Rollback endpoint
  P1-10 Post-apply WR measurement
  P3-1  OGD health badges

MEDIUM — after 50+ live signals:
  P2-1  Session liquid_hours tuning
  P2-2  Confidence floor tuning
  P3-2  Two-step confirmation overlay
  P3-3  Tune history table UI
  P3-4  Frequency gate UI indicator
  P3-5  Walk-forward gap warning banner

LOW — after 200+ live signals:
  P2-3  OGD hyperparameter tuning
  P3-5  Full CI display in Tune Bot panel
```

---

## Readiness Score Projection

| After Phase | Score | Blocking Issue |
|---|---|---|
| Current (post-fix, 0 live signals) | 6/10 | No live data; no tune_history; no rollback |
| After Phase 1 | 7.5/10 | No live data yet |
| After 30 live signals + Phase 1 | 8.5/10 | EV + WR gate now active |
| After 100 live signals + Phase 2 | 9/10 | Full Tune Bot operational |
| After 200 live signals + Phase 3 | 9.5/10 | Full UI + safety infrastructure |
