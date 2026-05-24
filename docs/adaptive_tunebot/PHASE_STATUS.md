# Adaptive TuneBot — Phase Status Registry

**Last audited:** 2026-05-23 (refreshed post-Sprint-3)
**Audited by:** phase-implementation-planner agent (initial); refreshed during cross-reference audit
**Purpose:** Single source of truth for all agents and skills. Read this before working on any TuneBot, adaptive learning, or backtest-to-live tuning feature.

---

## Quick Summary

| Phase | Status | Blocker |
|---|---|---|
| Phase 0 — DB Schema + Baseline | COMPLETE | — |
| Phase 1 — Adaptive Foundation | COMPLETE | — |
| Phase 2 Step 1 — Walk-Forward Validation | COMPLETE | — |
| TuneBot Hardening | COMPLETE | — |
| Phase 3 — Dashboard + UI | COMPLETE | — |
| **Phase 2 Step 2 — OGD Retraining** | **NOT STARTED** | Needs 30+ closed live trades |
| **P2-3 — OGD Hyperparameter Tuning** | **NOT STARTED** | Needs 200+ live signals |

**Overall:** 5 of 7 phases complete. 2 remaining phases are DATA-GATED — not code-gated.  
No code work should be done on Phase 2 Step 2 or P2-3 until live signal data accumulates.

---

## Phase Detail

### Phase 0 — DB Schema + Baseline Tables
**STATUS: COMPLETE**  
**Key files:**
- `signals.db` schema: `signals`, `results`, `backtest_runs`, `tune_history`, `token_weights`, `weight_history`, `bot_state`, `live_training_records` VIEW
- `tracker.py`: `_init_ae_tables()`, `_init_backtest_tables()`, `_init_tune_tables()`

---

### Phase 1 — Adaptive Foundation
**STATUS: COMPLETE**  
**Key files:**
- `adaptive_engine.py` — `AdaptiveWeightEngine` class; OGD learning with per-token, per-feature weights
- `adaptive_engine.py` — `decay_toward_default()` with 7-day suppression (skip decay if token updated within 7 days)
- `adaptive_engine.py` — `_load_all()` parses `updated_at` from DB for decay guard across restarts
- `crypto_alert.py` — `_trigger_weight_update()` called on WIN/LOSS/PARTIAL signals
- `crypto_alert.py` — `bootstrap_from_backtest()` warms OGD weights from backtest history at startup
- `tracker.py` — `get_ogd_stats()`, `get_weight_history()` for UI display

**Implementation report:** `docs/adaptive_tunebot/PHASE_1_ADAPTIVE_FOUNDATION_IMPLEMENTATION_REPORT.md`  
**Validation report:** `docs/adaptive_tunebot/PHASE_1_ADAPTIVE_VALIDATION_REPORT.md`

---

### Phase 2 Step 1 — Walk-Forward Validation
**STATUS: COMPLETE**  
**Key functions in `tracker.py`:**
- `calculate_tune_preview()` — analyzes latest backtest, proposes ICT gate changes
- `_wilson_ci()` — 95% Wilson score confidence interval for WR estimates
- `_tune_wr()`, `_quality_wr_from_raw()`, `_session_wr_from_raw()`, `_conf_wr_from_raw()`
- `_holdout_split()` — 80/20 train/test split for walk-forward validation
- Walk-forward gap warning: flags if train WR > test WR by > 15pp (overfitting signal)
- Wilson CI in session and confidence bucket notes (FVG/MSS notes now also include CI)

**Key functions in `tracker.py`:**
- `apply_tune_adjustments()` — whitelist-validated write to `strategy_engine.py` LIVE_CONFIG
- Guards: whitelist, no-op detection, BACKTEST_CONFIG anchor, max 2 APPLIED entries
- `rollback_tune_adjustment()` — restores old_val from backup

**Key functions in `tracker.py`:**
- `update_tune_history_post_apply()` — sets VERIFIED_BETTER / VERIFIED_WORSE after 30 post-apply signals
- `load_performance_state()` — background perf check; sends VERIFIED_WORSE Telegram alert

**Implementation report:** `docs/adaptive_tunebot/PHASE_2_STEP1_VALIDATION_REPORT.md`  
**Diagnostic audit:** `docs/adaptive_tunebot/PHASE_2_STEP1_DIAGNOSTIC_AUDIT_REPORT.md`

---

### TuneBot Hardening
**STATUS: COMPLETE**  
**What was hardened:**
- Frequency gate: min 14 days + 20 new signals between tune applications
- Walk-forward holdout: min 40 signals per half before tuning
- Whitelist enforcement: only `FVG_MIN_QUALITY`, `MSS_MIN_QUALITY`, `SESSION_LIQUID_HOURS`, `CONF_FLOOR_RAISE`
- Backup-before-write guarantee in `apply_tune_adjustments()`
- No-op detection (reject if new_val == current_val)
- `BACKTEST_CONFIG` anchor isolation: edits never touch BACKTEST_CONFIG block
- `strategy_version` bumped on every apply
- Max 2 APPLIED guard: blocks 3rd apply until one is verified or rolled back

**Implementation report:** `docs/adaptive_tunebot/TUNEBOT_HARDENING_REPORT.md`

---

### Phase 3 — Dashboard + UI
**STATUS: COMPLETE**  
**Key UI features in `tracker_html.py`:**
- Tune Bot panel: `openTunePanel()`, `loadTunePreview()`, `renderTunePreview()`
- Walk-forward gap warning banner in panel and confirm overlay
- Frequency gate indicator (`tuneGateInfo`)
- Confirm overlay: `confirmTune()`, `closeConfirm()` with OGD health warning
- Tune Bot History table: pagination (10/page), status summary bar, param search, Post WR column, expandable detail rows
- Backtest Run History: paginated (10/page)
- Rollback button with guard (status must be APPLIED)

**Tune Bot History columns:** applied_at, status, param, old→new, test_wr, Post WR (post_apply_wr + n), expandable detail (signals_at_apply, backtest_run_id, backup_file, notes)

---

### Phase 2 Step 2 — OGD Retraining from Live Data
**STATUS: NOT STARTED**  
**Blocked by:** N = 0 live closed trades. Minimum gate is 30 closed signals before OGD retraining produces statistically meaningful weight adjustments.

**Do NOT implement until ~12 months of paper trading have run.**

**What needs to be built (when data is ready):**
- `retrain_ogd_from_live()` in `adaptive_engine.py`: re-runs OGD updates over all closed live signals in date order
- `bootstrap_from_live()` variant: replaces bootstrap-from-backtest weights with weights trained on real live outcomes
- Trigger: monthly (cron) or manual via tracker dashboard
- Guard: N ≥ 30 closed live signals before first retrain
- Validation: compare WR before/after retrain on held-out last 10 signals

**Complexity:** MEDIUM — 1 to 2 sessions

---

### P2-3 — OGD Hyperparameter Tuning
**STATUS: NOT STARTED**  
**Blocked by:** N = 0 live signals. Requires 200+ live signals for reliable hyperparameter estimation.

**What needs to be built (when data is ready):**
- Grid search over `learning_rate` (0.01–0.1), `decay_rate` (0.85–0.99), `window` (20–100)
- Cross-validation using live signal outcomes (time-ordered, no shuffling)
- Best params written to `bot_state` table as `ogd_lr`, `ogd_decay`, `ogd_window`
- `adaptive_engine.py` reads these at startup (fallback to current defaults)

**Priority:** LOW — do not prioritize until 200+ live signals exist

---

## What to Do Next (in order)

1. **Rotate Telegram token** — user action, BotFather UI, 5 min
2. **Run fresh backtest** — VPN required; Run 60 WR=85.3% is pre-fix and invalid
3. **Start bot in PAPER mode** — every day without signals delays Phase 2 Step 2
4. **Set up Task Scheduler** — auto-restart command documented in `docs/comprehensive/FIX_LOG.md`
5. **Monitor paper signals for N ≥ 30 closed trades** — ~12 months at current signal frequency
6. **Implement Phase 2 Step 2** — only after live signal data exists

---

## Known Risks

| Risk | Severity | Notes |
|---|---|---|
| OGD data starvation | HIGH | At 34 sigs/year, N=30 closed live may take 12+ months |
| 76 test-cycle tune_history rows with status=APPLIED | MEDIUM | Max-2-APPLIED guard filters by signals_at_apply > 0 to exclude test rows |
| Walk-forward gap false confidence | MEDIUM | Small backtest n (<40/half) can show large gap from sampling noise |
| Telegram token not yet rotated | CRITICAL | Old tokens still valid; revoke via BotFather before starting live collection |

---

## Agent Instructions

**If you are working on TuneBot or adaptive learning code:**
- Read `adaptive_engine.py` for OGD implementation (learning rate, decay, bootstrap)
- Read `tracker.py:calculate_tune_preview()` for walk-forward validation logic
- Read `tracker.py:apply_tune_adjustments()` for the 5-phase write guard
- Do NOT implement Phase 2 Step 2 or P2-3 until live signals exist — check DB first
- The 7-day decay suppression in `adaptive_engine.py:decay_toward_default()` is intentional — do NOT remove it

**If you are adding a new TuneBot feature:**
- Update this file's phase table
- Add an implementation report to `docs/adaptive_tunebot/`
- Cross-reference in `docs/comprehensive/CROSS_REF.md` if the change touches signal logic or weight updates

---

## Dependency Graph

```
Phase 0 — DB schema (complete)
  └── Phase 1 — OGD adaptive engine (complete)
        └── Phase 2 Step 1 — walk-forward tuning (complete)
              └── TuneBot Hardening (complete)
                    └── Phase 3 — dashboard UI (complete)
                          └── LIVE paper collection ← START HERE
                                └── N ≥ 30 closed live signals
                                      └── Phase 2 Step 2 — OGD retrain from live
                                            └── N ≥ 200 live signals
                                                  └── P2-3 — hyperparameter tuning
```
