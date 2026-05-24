# ICT Strategy Variant Learner — Phase Status Registry

**Last audited:** 2026-05-23 (refreshed post-Sprint-3)
**Audited by:** phase-implementation-planner agent (initial); refreshed during cross-reference audit
**Purpose:** Single source of truth for all agents and skills. Read this before working on any template, adaptive, or signal-variant feature.

---

## Quick Summary

| Phase | Status | Blocker |
|---|---|---|
| I-1 Investigation Report | COMPLETE | — |
| I-2 Template Registry + DB Schema | COMPLETE | — |
| I-3 Backtest Multi-Template Harness | COMPLETE | — |
| I-4 MFE / MAE / Realized-R Tracking | COMPLETE | — |
| QA (Phase 1-4 audit fixes) | COMPLETE | — |
| I-5A Template Safety Controls | COMPLETE | — |
| I-5C Tier C Hard Gate | COMPLETE (inside I-5A) | — |
| **I-5B Per-Template OGD** | **NOT STARTED** | Needs N ≥ 30 live signals per template |
| **I-6 Full Learning Pipeline** | **NOT STARTED** | Same scope as I-5B |
| LIVE Paper Collection | READY TO START | C1 token rotation DONE 2026-05-22 (CROSS_REF.md line 21). Operator must start the bot in PAPER mode with VPN active. |

**Overall:** 7 of 9 phases complete. 2 remaining phases are DATA-GATED — not code-gated. No code work should be done on I-5B/I-6 until paper signals accumulate. **LIVE Paper Collection is now operator-startable** — all prior blockers cleared.

---

## Phase Detail

### I-1 — Strategy Investigation Report
**STATUS: COMPLETE**  
**Evidence:** `docs/ict_strategy_variant_learner/STRATEGY_INVESTIGATION_REPORT_AND_ICT_STRATEGY_VARIANT_LEARNER.md`  
14-section report covering signal flow map, required BUY/SELL conditions, confluence sequence validation, logging gaps, strategy variant feasibility, implementation plan.

---

### I-2 — Template Registry + DB Schema + Signal Tagging
**STATUS: COMPLETE**  
**Key files:**
- `strategy_templates.py` — `TemplateMatch` dataclass, `TEMPLATE_REGISTRY` (Tier A/B/C), `evaluate_confluences_vs_templates()`, `seed_templates_table()`, `validate_tier_hierarchy()`
- `crypto_alert.py:53-54` — imports wired
- `crypto_alert.py` — evaluation called in `generate_signal()` and `save_signal()`
- `backtest.py` — evaluation called in `run_backtest_token()` and `save_to_db()`
- DB: `templates`, `signal_variant_matches`, `matched_template_id`, `template_scores_json` columns on signals; `mfe_pct`, `mae_pct`, `realized_r` reserved on results

**Implementation report:** `docs/ict_strategy_variant_learner/PHASE_I2_IMPLEMENTATION_REPORT.md`

---

### I-3 — Backtest Multi-Template Comparison Harness
**STATUS: COMPLETE**  
**Key functions in `backtest.py`:**
- `_tier_stats()`, `_holdout_split()`, `_reconstruct_variant_features()`, `_overfitting_warnings()`
- `_dim_table()`, `template_comparison_report()`, `print_template_report()`
- `_excursion_section()`, `write_template_performance_md()`
- Integration in `main()` at line 2541

**Output:** `docs/ict_strategy_variant_learner/template_performance_report.md`  
**Implementation report:** `docs/ict_strategy_variant_learner/PHASE_I3_IMPLEMENTATION_REPORT.md`

---

### I-4 — MFE / MAE / Realized-R Tracking
**STATUS: COMPLETE**  
**Key functions in `backtest.py`:**
- `compute_excursions()` at line 368
- `_calc_realized_r()` at line 413 — uses `abs(sl_pct)` sign convention
- Called in `run_backtest_token()` at line 841-844
- DB columns `mfe_pct`, `mae_pct`, `realized_r` on `backtest_signals` (idempotent migrations)

**Implementation report:** `docs/ict_strategy_variant_learner/PHASE_I4_IMPLEMENTATION_REPORT.md`

---

### QA — Phase 1-4 Audit Fixes
**STATUS: COMPLETE**  
All 12 audit issues resolved. Both C-class critical fixes (formula error, STRATEGY_VERSION NameError) and all H/M/L items.  
**Report:** `docs/ict_strategy_variant_learner/PHASE_1_4_FIX_REPORT.md`

---

### I-5A — Template Safety Controls and Regime Safety Layer
**STATUS: COMPLETE**  
**Constants in `crypto_alert.py:138-158`:**
- `TEMPLATE_MIN_SAMPLE=50`, `CIRCUIT_BREAKER_LOOKBACK=20`, `CIRCUIT_BREAKER_MIN_WR=0.55`
- `TIER_DAILY_LIVE_CAPS`, `BLOCK_RANGING_LIVE`, `BLOCK_RANGING_TEMPLATES`

**Functions in `crypto_alert.py`:**
- `_tmpl_closed_count()`, `_tmpl_rolling_wr()`, `_tmpl_daily_live_count()`, `evaluate_template_status()`
- All 7 check stages: UNKNOWN_TEMPLATE → PAPER_ONLY → BLOCKED_BY_REGIME_SAFETY → INSUFFICIENT_SAMPLE → PAUSED_BY_CIRCUIT_BREAKER → DAILY_CAP_REACHED → ACTIVE
- Called in `generate_signal()` at line 2573
- Telegram suppression at line 3101: `if EXECUTION_MODE == "LIVE" and not result.get("template_live_allowed", 0)`

**Note:** `CIRCUIT_BREAKER_MIN_WR` intentionally raised from spec's 0.35 → 0.55 (M17 audit fix). `CIRCUIT_BREAKER_LOOKBACK` raised from 10 → 20. These are correct calibrations, not regressions.

**Implementation report:** `docs/ict_strategy_variant_learner/PHASE_I5A_IMPLEMENTATION_REPORT.md`

---

### I-5C — Tier C Hard Live Gate
**STATUS: COMPLETE (subsumed by I-5A)**  
Enforced via two independent mechanisms:
1. `evaluate_template_status()` check 2: `if template_id == "TIER_C": return ("PAPER_ONLY", False, ...)`
2. `TIER_DAILY_LIVE_CAPS["TIER_C"] = 0`

No separate code needed.

---

### I-5B — Per-Template OGD Adaptive Learning
**STATUS: NOT STARTED**  
**Blocked by:** N = 0 live signals. Minimum gate is 30 closed signals per template before weights diverge from global defaults (50 per template before reaching ACTIVE live status).

**Do NOT implement until paper trading has run for ~12 months.**

**What needs to be built (when data is ready):**
- `AdaptiveWeightEngine`: add `self._tmpl_weights: Dict[str, Dict[str, Dict[str, float]]]` keyed `[template_id][token][feature]`
- `update_template(template_id, token, outcome, features)` method
- `get_template_weights(template_id, token)` method — falls back to global token weights if n < 30
- Minimum 30-outcome gate before per-template weights diverge from token defaults
- Weight bound: per-template feature weight capped at 2× global default for that feature
- Circuit-breaker reset: if template rolling WR drops below 40% over 20 consecutive signals, revert weights to global defaults
- New DB table: `template_token_weights(template_id TEXT, token TEXT, feature TEXT, weight REAL, velocity REAL, n_updates INT, updated_at TEXT)`
- `crypto_alert.py` `generate_signal()`: apply per-template weights when `matched_template_id` is known and n ≥ 30
- `crypto_alert.py` `_trigger_weight_update()`: call `update_template()` in addition to existing `update()`
- `backtest.py` `bootstrap_from_backtest()`: also populate `template_token_weights` table

**Complexity:** LARGE — 3 to 4 sessions

---

### I-6 — Full Per-Template Learning Pipeline
**STATUS: NOT STARTED**  
Same scope as I-5B. The original roadmap named it I-6 in some documents and I-5B in others. There is no distinction in the codebase — it is one body of work.

---

### LIVE Paper Collection
**STATUS: NOT STARTED**  
**Blocker:** Telegram token rotation (C1 — user must revoke old tokens via BotFather and paste new token into env.bat).

**Infrastructure is ready.** When paper collection starts:
1. OGD bootstrap weights from `bootstrap_from_backtest(run_id=None)` will warm-start all tokens
2. `evaluate_template_status()` will correctly return INSUFFICIENT_SAMPLE until N ≥ 50 per template
3. TIER_C will always be PAPER_ONLY regardless of signal count
4. Kill switches are active in PAPER mode (C6 fix)

---

## Dependency Graph

```
I-1 (complete)
  └── I-2 (complete)
        └── I-3 (complete)
              └── I-4 (complete)
                    └── QA (complete)
                          └── I-5A (complete)
                                ├── I-5C (complete — inside I-5A)
                                └── LIVE paper collection ← START HERE
                                      └── N ≥ 30 signals/template
                                            └── I-5B / I-6 per-template OGD
                                                  └── N ≥ 50 signals/template
                                                        └── LIVE mode promotion
```

---

## What to Do Next (in order)

1. **Rotate Telegram token** — user action, BotFather UI, 5 min
2. **Run fresh backtest** — VPN required; Run 60 WR=85.3% is pre-fix and invalid
3. **Start bot in PAPER mode** — every day without signals delays I-5B
4. **Set up Task Scheduler** — auto-restart command documented in `docs/comprehensive/FIX_LOG.md`
5. **Monitor paper signals for N ≥ 30 per template** — ~12 months at current signal frequency
6. **Implement I-5B / I-6** — only after signal data exists

---

## Known Risks

| Risk | Severity | Notes |
|---|---|---|
| WR=85.3% from Run 60 is pre-fix | HIGH | Need fresh backtest; all 76 bugs affect signal count and/or WR |
| DR gate (M5) may cut signal volume 30-45% | MEDIUM | Fresh backtest will reveal true n; if n < 20/year, consider relaxing DR gate |
| Per-template OGD data starvation | HIGH | At 34 sigs/year total, N=50 per template may take 2-3 years |
| Telegram token not yet rotated | CRITICAL | Old tokens still valid; revoke via BotFather before starting live collection |

---

## Agent Instructions

**If you are working on template-related code:**
- Read `strategy_templates.py` for the template registry and scoring functions
- Read `crypto_alert.py:760-830` for `evaluate_template_status()` (the live gate)
- Do NOT modify `CIRCUIT_BREAKER_MIN_WR` (it was intentionally raised from 0.35 to 0.55)
- Do NOT implement I-5B/I-6 until paper signals exist — check DB first

**If you are adding a new ICT phase:**
- Update this file's phase table and dependency graph
- Add an implementation report to `docs/ict_strategy_variant_learner/`
- Cross-reference in `docs/comprehensive/CROSS_REF.md` if the change touches signal logic
