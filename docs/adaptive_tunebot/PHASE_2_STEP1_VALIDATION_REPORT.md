# Phase 2 Step 1 — Live Data Collection & Readiness Validation Report

**Date:** 2026-05-20  
**Validator:** Claude Sonnet 4.6 acting as Senior Quantitative AI Engineer / ML Architect  
**Scope:** Phase 2 Step 1 — safe live trade collection, per-record validation, readiness gating, and training dataset reporting. OGD retraining was explicitly NOT enabled.

---

## Executive Summary

Phase 2 Step 1 is **complete and tested**. The system can now collect, validate, and audit live closed trade outcomes, and can determine objectively when the dataset is ready for balanced OGD retraining. One latent crash bug was found and fixed as a prerequisite (`feature_scores_json` pollution in `crypto_alert.py`). All 25 tests pass. Current retraining status: **NOT READY** (0 live closed signals).

---

## Files Changed

| File | Changes |
|------|---------|
| `phase2_data.py` | **New module.** Live training data extraction, per-record validation, readiness gate evaluation, and human-readable reporting. |
| `crypto_alert.py` | **Bug fix (prerequisite):** `generate_signal()` was polluting `feature_scores_json` by overwriting float OGD scores with text strings. Fixed by capturing `_ogd_scores` before metadata update. |
| `tests/test_phase2_data.py` | **New test suite.** 25 tests covering validation, readiness gates, report generation, and real DB integration. |

---

## Prerequisite Bug Fixed: feature_scores_json Pollution

**Location:** `crypto_alert.py` — `generate_signal()`  
**Severity:** Critical (latent — would crash OGD on first token reaching 30 live closed trades)

**Root cause:** `live_feature_scores = extract_ict_feature_scores(...)` returned clean float scores, then `live_feature_scores.update({..., "mss_quality": mss_result["quality"], "fvg_quality": fvg["quality"], "session": session, ...})` overwrote 3 of the 6 OGD float keys with text strings (`"HIGH"`, `"NY_AM_KZ"`, etc.). The polluted dict was then serialised as `feature_scores_json`.

**Why this was masked:** OGD requires `n >= OGD_MIN_SAMPLES = 30` closed trades per token. Live signals = 0, so the OGD update path (`reward * score` where `score = "HIGH"`) was never reached. The TypeError would only trigger when the first production token accumulated 30 closed trades.

**Fix:** Captured `_ogd_scores` from `extract_ict_feature_scores()` before the metadata `update()` call. The metadata blob continues to use `live_feature_scores` internally (for `send_signal_msg`). Only `_ogd_scores` (clean floats) is stored in `feature_scores_json`.

---

## New Module: phase2_data.py

### Design Principles

- **No OGD triggering.** The module is purely read/analyse/report. It does not call any OGD update functions.
- **No strategy modification.** Live trading decision logic is unchanged.
- **Separation of live from backtest data.** Queries only the `signals` + `results` tables (live data). Backtest data lives in `backtest_signals` (separate table, never joined here).
- **Test token exclusion.** Any token whose name begins with `_` is rejected. Prevents test artefacts (e.g., `_TEST_SNAP_`) from contaminating the training distribution.
- **Legacy format tolerance.** Pre-fix records stored `fvg_quality`, `mss_quality`, `session` as text strings in `feature_scores_json`. The `_parse_feature_scores()` sanitiser converts them using the same lookup tables as the live signal engine, so older records are not silently discarded.

### Public API

| Function | Purpose |
|----------|---------|
| `validate_record(row)` | Per-record eligibility check. Returns `(True, "")` or `(False, reason)`. |
| `get_training_records(strategy_version, min_date, db_path)` | Extract + validate all live closed trades. Returns `(valid_list, rejected_list)`. |
| `check_readiness(records, db_path)` | Evaluate all 6 quality gates. Returns full gate report dict. |
| `training_report(records, db_path)` | Human-readable dataset quality report (per-token, distributions, gate table). |
| `ensure_live_training_view(db_path)` | Create `live_training_records` SQL VIEW in DB (for dashboard use). |

### SQL VIEW: live_training_records

Created in `signals.db` by `ensure_live_training_view()`. Joins `signals + results` with `r_multiple` pre-computed:

```sql
CREATE VIEW IF NOT EXISTS live_training_records AS
SELECT s.id, s.token, s.signal AS direction, s.confidence, s.trend_1h,
       s.session, s.dr_location, s.mss_quality, s.fvg_quality,
       s.sl_pct, s.tp1_pct, s.feature_scores_json, s.strategy_version,
       s.timestamp AS entry_time, s.hour_utc,
       r.result AS outcome, r.profit_pct,
       r.closed_at AS close_time,
       CASE WHEN s.sl_pct > 0
            THEN ROUND(r.profit_pct / s.sl_pct, 3)
            ELSE NULL END AS r_multiple
FROM signals s
JOIN results r ON s.id = r.signal_id
WHERE s.status = 'CLOSED'
  AND r.result IN ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED')
  AND r.closed_at IS NOT NULL
  AND SUBSTR(s.token, 1, 1) != '_'
```

---

## Minimum Retraining Quality Gates

All 6 gates must pass for `check_readiness()` to return `ok=True`. Gates are calibrated against the root cause of Phase 1's OGD weight collapse (all-SELL bootstrap + single-feature domination).

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| `min_total` | >= 30 records | Matches `OGD_MIN_SAMPLES`; below this, gradient estimates are noisy |
| `min_tokens` | >= 2 tokens each with >= 10 records | Prevents single-token overfitting |
| `min_loss_fraction` | >= 20% LOSS + EXPIRED | OGD must see negative examples to avoid pure-win gradient collapse |
| `buy_sell_balance` | minority direction >= 10% | Prevents directional gradient bias (Phase 1 root cause was all-SELL) |
| `session_diversity` | no single session > 90% | Prevents session-specific overfitting |
| `fvg_diversity` | no single FVG quality > 90% | Prevents FVG-quality gradient domination |

---

## Per-Record Validation Rules

`validate_record()` rejects a record if any of the following conditions are true:

| Condition | Rejection reason |
|-----------|-----------------|
| Token starts with `_` | `test_token:{token}` |
| `direction` / `signal` not in `{BUY, SELL}` | `invalid_direction:{val}` |
| `outcome` / `result` not in valid set | `invalid_outcome:{val}` |
| `fvg_quality` not in `{HIGH, MEDIUM, LOW}` | `invalid_fvg_quality:{val}` — NONE excluded |
| `mss_quality` not in `{HIGH, MEDIUM, LOW}` | `invalid_mss_quality:{val}` |
| `session` not in known sessions | `invalid_session:{val}` |
| `dr_location` not in `{PREMIUM, DISCOUNT, EQUILIBRIUM, UNKNOWN}` | `invalid_dr_location:{val}` |
| `confidence` not an integer in [0, 10] | `confidence_out_of_range` / `confidence_not_integer` |
| `sl_pct` <= 0 | `sl_pct_zero_or_negative` |
| No `close_time` or `closed_at` | `not_closed` |
| `feature_scores_json` missing or unparseable | `missing_feature_scores_json` / `feature_scores_json_parse_error` |
| Any of 6 OGD features missing from JSON | `missing_feature:{feat}` |
| Float feature score outside [0.0, 1.0] | `feature_score_out_of_range:{feat}={val}` |
| Unrecognised text value for sanitisable feature | `unrecognised_feature_value:{feat}={val}` |

---

## Test Results

```
==============================================================
  Phase 2 Step 1 Test Suite
==============================================================
PASS V1:  valid record accepted
PASS V2:  test token rejected
PASS V3:  missing direction rejected
PASS V4:  invalid fvg_quality rejected
PASS V5:  invalid mss_quality rejected
PASS V6:  invalid session rejected
PASS V7:  invalid dr_location rejected
PASS V8:  sl_pct=0 rejected
PASS V9:  open trade rejected
PASS V10: missing feature_scores_json rejected
PASS V11: legacy text feature_scores_json sanitised and accepted
PASS V12: out-of-range feature score rejected
PASS V13: 'signal' key accepted as direction
PASS G1:  empty list -> all 6 gates failed, ok=False
PASS G2:  insufficient total -> min_total fails
PASS G3:  single token -> min_tokens fails
PASS G4:  no losses -> min_loss_fraction fails
PASS G5:  all BUY -> buy_sell_balance fails
PASS G6:  single session -> session_diversity fails
PASS G7:  single FVG quality -> fvg_diversity fails
PASS G8:  balanced dataset (n=32, BTC+ETH) passes all 6 gates
PASS R1:  training_report with empty records runs without error
PASS R2:  training_report contains all expected sections
PASS R3:  ready tokens listed correctly in report
PASS DB1: get_training_records against real DB returns (0, 0) without error

  25 passed  |  0 failed
==============================================================
```

---

## Current Retraining Status (as of 2026-05-20)

```
==============================================================
  LIVE TRAINING DATASET - Phase 2 Step 1 Report
  Generated: 2026-05-19 21:33 UTC
==============================================================

  Valid records:    0
  Rejected records: 0

  No valid training records found.
  The bot must generate and close live signals before
  OGD retraining can be evaluated.

  Retraining status: NOT READY
==============================================================
```

**Blockers:** All 6 gates fail due to zero live closed signals. The signals.db `results` table contains 0 rows. The system must go live, generate signals, and accumulate closed trade outcomes before Phase 2 Step 2 (OGD retraining) can begin.

---

## Remaining Blockers Before Enabling OGD Retraining

| ID | Blocker | Resolution |
|----|---------|-----------|
| P2-DATA-1 | 0 live closed signals | Run bot live; close at least 30 trades across 2+ tokens |
| P2-DATA-2 | Unknown BUY/SELL balance (live strategy may favour one direction) | Monitor `training_report()` output as signals accumulate |
| P2-DATA-3 | Unknown session distribution (Philippines timezone may concentrate signals in Asia session) | Monitor session_diversity gate |
| OGD-DEGENERATE | 6/8 tokens have collapsed weights from SELL-only bootstrap | Live balanced data + Phase 2 Step 2 re-bootstrap with balanced set |

---

## What Does NOT Change in This Phase

- Live trading decision logic (`generate_signal()`, `crypto_alert.py` signal path) — unchanged except the `feature_scores_json` pollution fix
- OGD weight update logic (`adaptive_engine.py`) — no changes
- Strategy parameters (`strategy_engine.py`, `LIVE_CONFIG`, `BACKTEST_CONFIG`) — unchanged
- The Tune Bot (`tracker.py`) — unchanged
- No automatic retraining is triggered by any code path in `phase2_data.py`

---

## Phase 2 Step 2 Prerequisites (Not Yet Implemented)

When `check_readiness()` returns `ok=True`, Phase 2 Step 2 will:

1. Run balanced re-bootstrap using `get_training_records()` output
2. Call `adaptive_engine.bootstrap_from_backtest()` with live data only
3. Monitor post-bootstrap weight entropy to detect new collapse
4. Compare pre/post live WR using `tune_history` post-apply tracking

Phase 2 Step 2 should only begin after the system has operated live for sufficient time to meet all 6 quality gates.
