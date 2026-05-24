# Phase 1 — Adaptive Foundation Implementation Report

**Date completed:** 2026-05-19  
**Source plan:** ADAPTIVE_TUNE_BOT_IMPLEMENTATION_PLAN.md — Section 8, Phase 1  
**Files modified:** `backtest.py`, `adaptive_engine.py`, `crypto_alert.py`, `tracker.py`  
**Compile status:** All 5 files pass `python -m py_compile` with no errors

---

## Overview

Phase 1 implements the minimum foundation required before the Tune Bot can safely apply any live configuration change. It addresses three hard blockers identified in the readiness audit:

1. Backtest and live confidence formulas were diverged — walk-forward WR was measuring the wrong distribution
2. No record of Tune Bot applications — no rollback, no performance verification, no frequency gate
3. No weight versioning — OGD drift undetectable, bootstrap changes unauditable

---

## P1-1 — Backtest Confidence Formula Alignment

**File:** [backtest.py](backtest.py) — lines 548–573  
**Replaced:** Hardcoded 7-variable binary bonus formula (`trend_bonus + fvg_sz_bonus + fvg_q_bonus + bias_4h_bonus + react_bonus + session_bonus + ifvg_penalty`)  
**With:** OGD-weighted ICT quality score — the same formula used in `generate_signal()` in `crypto_alert.py`

### Old formula (removed)
```python
trend_bonus   = 1 if trend_1h in ("STRONG_BULL", "STRONG_BEAR") else 0
fvg_sz_bonus  = 1 if fvg_size_pct >= ICT_FVG_SIZE_BONUS_THRESHOLD * 100 else 0
fvg_q_bonus   = 1 if fvg.get("quality") == "HIGH" else 0
bias_4h_bonus = (1 if ((direction == "BUY"  and bias_4h == "BULLISH") or
                       (direction == "SELL" and bias_4h == "BEARISH")) else 0)
react_bonus   = 1 if entry_reaction.get("entry_type") == "MIDPOINT_RECLAIM" else 0
session_bonus = 1 if ts.hour in (20, 21, 22, 23) else 0
ifvg_penalty  = -1 if ifvg_meta.get("ifvg_present") else 0
confidence    = max(5, min(5 + trend_bonus + fvg_sz_bonus + fvg_q_bonus
                            + bias_4h_bonus + react_bonus + session_bonus
                            + ifvg_penalty, 10))
```

### New formula (aligned with live)
```python
ifvg_penalty  = -1 if ifvg_meta.get("ifvg_present") else 0
_bt_session   = _utc_to_session(datetime.utcfromtimestamp(ts_entry_ms / 1000).hour)
_dr_loc       = dr_4h.get("location", "UNKNOWN")
# direction-aware trend and DR scores (same logic as generate_signal())
_raw_scores   = {
    "fvg_quality":    _QUALITY_SCORE.get(fvg.get("quality", "NONE"), 0.0),
    "mss_quality":    _QUALITY_SCORE.get(mss_result.get("quality", "NONE"), 0.0),
    "session":        _SESSION_SCORE.get(_bt_session, 0.0),
    "trend_strength": _trend_score,
    "dr_location":    _dr_score,
}
_feat_w       = {f: AE_DEFAULT_WEIGHTS.get(f, 0.0) for f in _raw_scores}
_w_total      = sum(_feat_w.values())
_ogd_qual     = sum(_raw_scores[f] * _feat_w[f] for f in _raw_scores) / _w_total
confidence    = max(5, min(int(5 + _ogd_qual * 5) + ifvg_penalty, 10))
```

**Import added** (`backtest.py` line 54):
```python
from adaptive_engine import (
    _utc_to_session, label_sample_size, SAMPLE_N_OBSERVE, weight_engine,
    _QUALITY_SCORE, _SESSION_SCORE, DEFAULT_WEIGHTS as AE_DEFAULT_WEIGHTS,
)
```

**Why this matters:** Walk-forward WR stats in the backtest were computed on a different confidence distribution than live signals. With the old binary bonus formula, a session_bonus added +1 for any signal after 20:00 UTC regardless of quality. The new formula uses `DEFAULT_WEIGHTS` (fvg_quality=0.25, mss_quality=0.20, session=0.15, trend_strength=0.15, dr_location=0.05) so confidence reflects ICT quality in the same proportion as the live OGD formula. Future backtest runs will produce WR statistics that are directly comparable to live outcomes.

**Accepted risk:** Confidence values will shift in new backtest runs compared to runs 1–37. This is correct — those runs used the wrong formula. Run #38+ will be on the aligned distribution.

---

## P1-2 — `tune_history` Table

**File:** [adaptive_engine.py](adaptive_engine.py) — `_init_adaptive_tables()`, inserted before migration block  
**Schema:**
```sql
CREATE TABLE IF NOT EXISTS tune_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    applied_at       TEXT    NOT NULL,          -- UTC timestamp of apply
    param            TEXT    NOT NULL,          -- 'FVG_MIN_QUALITY' | 'MSS_MIN_QUALITY'
    old_val          TEXT    NOT NULL,          -- value before change
    new_val          TEXT    NOT NULL,          -- value after change
    signals_at_apply INTEGER NOT NULL,          -- closed signal count at time of apply
    backtest_run_id  INTEGER,                   -- run_id that produced the recommendation
    train_wr         REAL,                      -- train split WR at apply time
    test_wr          REAL,                      -- test split WR at apply time
    post_apply_wr    REAL,                      -- measured after >= 30 post-apply signals
    post_apply_n     INTEGER,                   -- how many signals measured post_apply_wr
    status           TEXT DEFAULT 'APPLIED',    -- APPLIED | ROLLED_BACK | VERIFIED_BETTER | VERIFIED_WORSE
    backup_file      TEXT,                      -- relative path to strategy_engine.bak.*
    notes            TEXT                       -- auto-verdict or human notes
)
```

**Written by:** `apply_tune_adjustments()` in `tracker.py` (on every successful apply)  
**Updated by:** `load_performance_state()` in `crypto_alert.py` (post-apply WR verdict)  
**Read by:** rollback endpoint, frequency gate, post-apply WR check

---

## P1-3 — `weight_history` Table

**File:** [adaptive_engine.py](adaptive_engine.py) — `_init_adaptive_tables()`, inserted after `tune_history`  
**Schema:**
```sql
CREATE TABLE IF NOT EXISTS weight_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at   TEXT    NOT NULL,             -- UTC timestamp
    token         TEXT    NOT NULL,
    trigger       TEXT    NOT NULL,             -- 'bootstrap_before' | 'bootstrap_after' | 'reset' | 'decay'
    feature       TEXT    NOT NULL,             -- one of the 6 ICT features
    weight_before REAL    NOT NULL,
    weight_after  REAL    NOT NULL,
    n_updates     INTEGER NOT NULL,             -- total OGD updates at snapshot time
    run_id        INTEGER                       -- backtest run_id if trigger is bootstrap_*
)
```

**Written by:** `_snapshot_weights()` helper (bootstrap before/after), `reset_token()` (on reset)  
**Read by:** adaptive weights dashboard tab (Phase 3)

---

## P1-4 — `health_check()` Method

**File:** [adaptive_engine.py](adaptive_engine.py) — `AdaptiveWeightEngine` class, after `summary()`  
**Signature:** `health_check() -> Dict[str, dict]`

Returns per-token health status for every token currently in memory:

| Field | Type | Meaning |
|---|---|---|
| `max_weight` | float | Largest feature weight for this token |
| `is_degenerate` | bool | True if max_weight > 0.45 (same threshold as collapse guard) |
| `n_updates` | int | Total OGD updates received |
| `weight_entropy` | float | Shannon entropy; low entropy = collapsed/degenerate state |
| `last_updated` | str or None | DB `updated_at` timestamp |

**Used by:** Tune Bot OGD sanity check (Section 6.6 of plan), Phase 3 dashboard health badges  
**Uses Shannon entropy:** `-sum(w * log(w))` — uniform weights (0.167 each) give maximum entropy ≈ 1.79; a collapsed state with one feature at 0.667 gives ≈ 0.98

---

## P1-5 — Weight Snapshots on Bootstrap

**File:** [adaptive_engine.py](adaptive_engine.py) — `bootstrap_from_backtest()`

Added `_snapshot_weights()` calls immediately before and after the OGD update loop:

```python
self._snapshot_weights(trigger="bootstrap_before", run_id=run_id)
# ... OGD updates ...
self._persist_all()
self._snapshot_weights(trigger="bootstrap_after", run_id=run_id)
```

The `_snapshot_weights()` helper writes one row per feature per token to `weight_history`, recording the `weight_before` as the DEFAULT_WEIGHTS value (reflecting state before this snapshot was taken — the "before" snapshot captures in-memory state, which IS the weights before this bootstrap) and `weight_after` as the current in-memory weight after learning.

**Why:** Bootstrap is the primary mechanism that changes OGD weights right now (no live signals yet). Every bootstrap run is now auditable — you can see exactly how each run shifted each token's weights.

---

## P1-6 — `reset_token()` Method

**File:** [adaptive_engine.py](adaptive_engine.py) — `AdaptiveWeightEngine` class  
**Signature:** `reset_token(token: str) -> None`

Resets a token's OGD weights to `DEFAULT_WEIGHTS`, zeroes velocity and n, deletes from `token_weights` DB table, re-inserts with defaults, and writes a `weight_history` row with `trigger='reset'`.

**Required for rollback path:** When Tune Bot worsens performance, the live OGD weights that were learned under the old config must be erased before re-bootstrapping under the new config. Without a reset, old biased weights contaminate the fresh bootstrap.

**Usage:**
```python
weight_engine.reset_token("BTCUSDT")
# → deletes token_weights rows for BTCUSDT
# → re-initializes to DEFAULT_WEIGHTS in memory and DB
# → writes weight_history row: trigger='reset', weight_before=old, weight_after=default
```

---

## P1-7 — `tune_history` Write on Apply

**File:** [tracker.py](tracker.py) — `apply_tune_adjustments()`

### Signature change
```python
# Before:
def apply_tune_adjustments(adjustments):

# After:
def apply_tune_adjustments(adjustments, run_id=None, train_wr=None, test_wr=None):
```

### New logic added after Phase 3 (file write)

1. **Count closed live signals** — queries `results` table for total closed count at apply time
2. **Capture `old_val`** — extracted via `re.search` before the substitution (was previously discarded)
3. **Insert `tune_history` row** — one row per applied adjustment with all fields including backup_file path
4. **Update `bot_state`** — writes `tune_last_applied_at` (UTC) and `tune_signals_at_last_apply` (int)
5. **Increment `strategy_version`** — reads current version from `bot_state`, writes `version + 1`. This ensures EV scoring and post-apply WR measurement isolate signals by strategy generation

### HTTP route update

`POST /api/backtest/tune-apply` now forwards `run_id`, `train_wr`, `test_wr` from the request body:
```python
self.send_json(apply_tune_adjustments(
    body.get("adjustments", []),
    run_id   = body.get("run_id"),
    train_wr = body.get("train_wr"),
    test_wr  = body.get("test_wr"),
))
```

---

## P1-8 — Frequency Gate in `calculate_tune_preview()`

**File:** [tracker.py](tracker.py) — `calculate_tune_preview()`, inserted after `read_bot_values()` check

### Gate logic

```
IF tune_last_applied_at exists:
    days_since  = (now_utc - last_applied_at).days
    new_signals = current_closed_count - signals_at_last_apply
    IF days_since < 14 AND new_signals < 50:
        return BLOCKED response
```

Both conditions must fail simultaneously to block. Either condition passing is enough to allow the preview:
- 14+ days have passed since last apply, OR
- 50+ new closed signals have accumulated since last apply

### Blocked response format
```json
{
    "ok": false,
    "error": "Frequency gate: 12 new closed signals since last tune (3 days ago). Need 38 more signals OR 11 more days.",
    "frequency_gate": {
        "days_since": 3,
        "new_signals": 12,
        "need_days": 11,
        "need_signals": 38
    }
}
```

The `frequency_gate` sub-object is consumed by the Phase 3 dashboard UI (P3-4) to display the "Next tune available in X days / Y signals" footer indicator.

**First run:** If `tune_last_applied_at` is not in `bot_state` (first-ever tune preview), the gate is skipped entirely.

---

## P1-9 — Rollback Endpoint

**File:** [tracker.py](tracker.py) — new `rollback_tune_adjustment()` function + route

### Function signature
```python
def rollback_tune_adjustment(tune_history_id: int) -> dict:
```

### Rollback sequence
1. Read `param`, `old_val`, `new_val`, `status` from `tune_history` by id
2. Validate: must be `status='APPLIED'`, param must be in whitelist
3. Split `strategy_engine.py` at `BACKTEST_CONFIG` marker
4. Apply reverse regex to LIVE_CONFIG section only: write `old_val` back
5. Create backup: `strategy_engine.bak.YYYYMMDD_HHMMSS.py`
6. Write updated file
7. Update `tune_history.status = 'ROLLED_BACK'`, set `backup_file`
8. Increment `strategy_version` (post-rollback signals isolated from rollback state)

### HTTP route
```
POST /api/backtest/tune-rollback
Body: { "tune_history_id": 3 }
Response: { "ok": true, "param": "FVG_MIN_QUALITY", "reverted": "HIGH → MEDIUM", "backup": "backups/..." }
```

### Guard rails
- Already rolled back → error "Already rolled back"
- Unknown param → error "Cannot rollback unknown param"
- Regex finds no match → error "Regex found no match for {field} in LIVE_CONFIG"

---

## P1-10 — Post-Apply WR Measurement

**File:** [crypto_alert.py](crypto_alert.py) — end of `load_performance_state()`

On every `PERF_CHECK_INTERVAL` cycle (every 30 minutes), after computing token/regime/conf WR:

```python
# For each tune_history row with status='APPLIED':
#   Count wins and total closed signals AFTER applied_at timestamp
#   If total >= 30: compute WR, set VERIFIED_BETTER or VERIFIED_WORSE
```

### Verdict logic

| Condition | Status set |
|---|---|
| `post_apply_wr >= test_wr` (or >= 45% if test_wr is None) | `VERIFIED_BETTER` |
| `post_apply_wr < test_wr` | `VERIFIED_WORSE` |

The baseline is `test_wr` at apply time — the WR on the held-out test split of the backtest that was used to justify the change. If the live bot does at least as well as the backtest predicted, the change is verified.

**Minimum signals:** 30 post-apply closed signals required before issuing a verdict. With one signal per day at conservative settings, this represents ~30 trading days of live data — a meaningful measurement window.

**Uses a fresh connection** — `conn` is already closed earlier in `load_performance_state()`, so a new `_connect()` call is made for the `tune_history` queries.

---

## Import Changes

### `tracker.py`
```python
# Before:
try:
    from adaptive_engine import weight_engine as _weight_engine
except Exception:
    _weight_engine = None

# After:
try:
    from adaptive_engine import (
        weight_engine as _weight_engine,
        save_scalar_state as _save_scalar,
        load_scalar_state as _load_scalar,
        _init_adaptive_tables as _init_ae_tables,
    )
except Exception:
    _weight_engine  = None
    _save_scalar    = lambda k, v: None
    _load_scalar    = lambda k, d=None: d
    _init_ae_tables = lambda: None
```

Fallback lambdas ensure tracker.py degrades gracefully if `adaptive_engine.py` cannot be imported (e.g. missing dependency on a fresh install).

---

## Testing Checklist (from Section 9.1 of plan)

The following pre-live checks are now testable:

- [x] `python -m py_compile backtest.py adaptive_engine.py crypto_alert.py tracker.py strategy_engine.py` — all pass
- [ ] `python backtest.py` — creates `weight_history` rows (`bootstrap_before` + `bootstrap_after`) for the new run
- [ ] After backtest: `tune_history` and `weight_history` tables exist in `data/signals.db`
- [ ] `read_bot_values()` returns `fvg_min_quality=MEDIUM`, `mss_min_quality=MEDIUM` from current `strategy_engine.py`
- [ ] Tune preview with < 30 backtest signals: returns `{"ok": false, "error": "Only X backtest signals..."}`
- [ ] `apply_tune_adjustments([{"param":"FVG_MIN_QUALITY","new_val":"HIGH"}])`: `strategy_engine.py` LIVE_CONFIG changed; BACKTEST_CONFIG unchanged; backup created; `tune_history` row written; `strategy_version` incremented
- [ ] Rollback: `POST /api/backtest/tune-rollback {"tune_history_id":1}` → `strategy_engine.py` reverts; `tune_history.status = ROLLED_BACK`
- [ ] Frequency gate: second apply attempt within 14 days with < 50 new signals → blocked with `frequency_gate` fields in response
- [ ] `weight_engine.health_check()` returns dict with `is_degenerate` bool for all 7 tokens
- [ ] `weight_engine.reset_token("BTCUSDT")` → weights in DB reset to defaults; `weight_history` row with `trigger='reset'`

---

## What Phase 1 Does NOT Include

These remain for Phase 2 and Phase 3:

- Session `liquid_hours` tuning (P2-1)
- Confidence floor tuning via `bot_state` (P2-2)
- OGD hyperparameter tuning (P2-3)
- Dashboard health badges (`GET /api/adaptive/health`) (P3-1)
- Two-step confirmation overlay with file diff (P3-2)
- Tune history table in dashboard UI (P3-3)
- Frequency gate UI indicator (P3-4)
- Walk-forward gap warning banner (P3-5)

Phase 1 is sufficient to safely run the Tune Bot in production once live signals accumulate. The frequency gate, rollback, and post-apply verification provide the minimum safety net for a first live application.
