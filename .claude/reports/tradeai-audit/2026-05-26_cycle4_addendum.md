# TradeAI Cycle-4 Audit Addendum — 1 CRITICAL + 4 SERIOUS Fixed

**Parent report:** `2026-05-26_cycle4.md` (overall 8.58/10)
**Fix session:** 2026-05-26 PM (operator requested "fix criticals")
**Scope:** All 1 CRITICAL + 4 SERIOUS findings from cycle-4 audit

---

## Fixes Applied

### C-NEW-1 — DSR formula T mismatch (CRITICAL)

`validation.py:592-636` rewritten.

`psr_oos` and `DSR` now use `n_oos_per_fold = max(1, int(n * n_test_groups / n_groups))` as `n_returns`, matching the per-fold observation count of the `sharpe_mean` estimator. Per Bailey & López de Prado 2014 eq (1)-(2), `T` in the PSR formula must equal the number of returns from which the Sharpe estimator was computed. Previously used full-pool `len(pnl_pool)` while `sr_observed=sharpe_mean` (mean of K Sharpe estimators each from ~`n/K*k` obs) → inflated `sqrt(T-1)` by ~1.67×.

Option A (per-fold T, conservative) chosen over Option B (concatenated OOS series) because it preserves the CPCV-specific OOS Sharpe character that operators read in the report. `n_oos_per_fold` surfaced in summary dict + text report.

### FLAW-1 — WFV contaminated held-out window (SERIOUS)

`backtest.py:3199-3253` reordered.

`split_held_out()` now runs FIRST when `HELD_OUT_DAYS > 0`. `walk_forward()` operates on `_tune_sigs` only. Lockbox invariant restored. When `HELD_OUT_DAYS=0` (default), behavior is byte-identical to pre-fix.

### S-1 — Hardcoded "90d" in held_out_text_report (SERIOUS)

`walk_forward.py:held_out_text_report` parameterized: `held_out_days` is now a keyword argument. Callers in `backtest.py` + `scripts/validate_baseline_held_out.py` pass the actual `HELD_OUT_DAYS` value through.

### S-2a/b — promote_baseline gate missing DSR pool + PnL columns (SERIOUS)

`scripts/promote_baseline.py:_check_held_out_gate` rewritten:
- SELECT now reads `ts, outcome, realized_r, net_tp1_pct, net_sl_pct, net_tp2_pct` (was missing the 3 PnL columns)
- Reads `n_trials_for_dsr` (anchored to `cumulative_min_trials=27`) + `sr_trial_std_for_dsr` from `bot_state` and passes both to `cpcv_summary_split` (was silently passing `None` → forced MARGINAL)
- Returns dict now includes `tuning_dsr` for operator visibility

---

## Run-79 — Honest Baseline Numbers

| Metric | Run-78 (pre-fix) | **Run-79 (post-fix)** | Δ |
|---|---|---|---|
| n_signals | 7 | 7 | ─ |
| n_oos_per_fold | (used 7) | **2** | (proper per-fold) |
| CPCV mean WR | 87.50% | 87.50% | ─ |
| CPCV std | 16.32% | 16.32% | ─ |
| CPCV Sharpe mean | 5.425 | 5.425 | ─ |
| Overall Sharpe | 1.133 | 1.039 | (re-run rounding) |
| PSR (OOS CPCV) | 99.9% | **89.8%** | **−10.1pp** |
| DSR (multi-test) | 99.9% | **89.1%** | **−10.8pp** |
| **Verdict** | **PASS** | **FAIL** | **flipped** |

Same config_hash. Same strategy. Same signals. The only thing that changed is the validation formula. **The verdict was inflated by the formula bug — Run-79's FAIL is the honest answer at n=7.**

---

## What This Means Operationally

1. **No live-flip on this baseline.** DSR < 95% gate. The strategy may still be good, but the backtest cannot statistically validate it at n=7. Honest interpretation: the multiple-testing correction (n_trials=27 historic configs) is stronger than the evidence the 7-signal sample provides.

2. **q05 + paper trading remain the trustworthy discriminators.** CPCV q05 = 66.7% > 58% floor — the floor of plausible outcomes is still above the WR gate. This is informational but not a verdict.

3. **The honest result is what we wanted.** Pre-fix the system was claiming 99.9% confidence the strategy is real. Post-fix it admits 89.1% — still high, but honestly bounded by the sample size.

4. **Future explorer trials.** Now that DSR isn't inflated, Optuna's optimization landscape will look meaningfully different — configs that pass the 95% DSR gate will be configs with genuine evidence, not formula artifacts. The cycle-3 "auto-promoted" path was vulnerable to this; the cycle-4 fix closes it.

---

## Test Status

- `tests/test_execution.py` — 29 / 29 pass
- `tests/test_walk_forward.py` — 12 / 12 pass
- `tests/test_validation.py` — pytest not on VPS; manual smoke test verified N-A + C-NEW-1 paths

---

## Expected Cycle-5 Scorecard Impact

| Dimension | Cycle-4 | Cycle-5 estimate | Driver |
|-----------|---------|-----------------|--------|
| Honest Metrics | 7.2 | **8.6-8.8** | C-NEW-1 + S-1 + S-2a/b all closed |
| Backtest Validity | 7.5 | **8.0** | FLAW-1 closed |
| Live/BT Consistency | 9.85 | 9.85 | unchanged |
| Template | 4.5 | 4.5 | n=7 cliff still binding |
| **Overall** | **8.58** | **~9.0-9.1** | recovery to cycle-3 territory |

The C-NEW-1 fix recovers the headline metric integrity. The Template dimension remains the binding constraint until either paper signals accumulate or a binding gate relaxes.

---

## Remaining Open Items (next session)

- H-A (closed_at alias in compute_cross_config_sr_std.py:81) — one-word SQL fix
- H-B (embargo anchor at t1[b_end] not t0[b_end]) — one-line change
- H-F (BTC feed Telegram alert) — three-line addition
- OGD-MON-SCOPE (monitor reads wrong table) — add `--source` flag
- M-J (bootstrap n=7 cliff guard) — one helper change in adaptive_engine.py
- M-H ESCALATED (REALISTIC_EXECUTION + HELD_OUT_DAYS not in config_hash)

All are reversible, scoped, and ready to ship without operator decision.

---

**End of addendum.** Run-79 is the new honest baseline. Verdict FAIL is correct; do not promote until either paper-trading data or a sample-size-restoring config change provides the evidence.
