# Phase 1–4 QA Fix Report

**Date:** 2026-05-20  
**Author:** Claude (Sonnet 4.6)  
**Role:** Senior Python Trading-System Architect & QA Engineer  
**Scope:** Resolve all issues identified in the Phase 1–4 QA Audit before Phase 5A begins

---

## Executive Summary

All Phase 1–4 QA audit findings have been reviewed against the actual code. Every confirmed
issue has been fixed. One audit finding (L-1) was rejected as incorrect — the function in
question was already documented. No new strategy features were added; all changes are
documentation corrections, defensive code comments, and noise-reduction improvements to the
report generation logic.

After fixes, both modified Python files (`backtest.py`, `ict_engine.py`) pass AST syntax
checks, and the two core logic fixes (`_calc_realized_r`, `_overfitting_warnings`) pass
isolated smoke tests with verified expected outputs.

**Final decision: GO for Phase 5A.**

---

## Audit Issues Reviewed

| ID | Severity | Summary | Decision |
|----|----------|---------|---------|
| C-1 | Critical | realized_R formula table documented wrong (`/ sl_pct` instead of `/ abs(sl_pct)`) | FIXED |
| C-2 | Critical | STRATEGY_VERSION NameError on first run | FIXED (during implementation, pre-audit) |
| H-1 | High | sl_pct negative sign convention undocumented in ict_engine.py | FIXED |
| H-2 | High | Tier C = 0 in best-match unexplained | FIXED |
| H-3 | High | All-Matched Tier B = Tier C counts unexplained | FIXED |
| M-1 | Medium | Med realR = 0.0 misleading (EXPIRED trades at median) | FIXED |
| M-2 | Medium | Session concentration warnings fire tautologically | FIXED (also fixed regime) |
| M-3 | Medium | Rollback Steps reference net_sl_pct / sl_pct | FIXED (subsumed by C-1 doc fix) |
| M-4 | Medium | _fmt_stats_line() produces >200-char console lines | ACCEPTED AS KNOWN LIMITATION |
| L-1 | Low | _excursion_section() absent from Phase I-4 New Functions table | REJECTED — function IS listed as item 8 |
| L-2 | Low | Phase I-3 report "N/A" note now stale after I-4 | FIXED |
| L-3 | Low | DB column dr_location vs signal dict key dr4h_location mismatch | DOCUMENTED (comment added; column rename deferred) |

---

## Issues Fixed

### C-1 — realized_R Formula Documentation (Critical)

**Problem:** The formula table in `write_template_performance_md()` and in
`PHASE_I4_IMPLEMENTATION_REPORT.md` both showed `net_tp1_pct / sl_pct` and
`net_sl_pct / sl_pct`. This is wrong.

**Root cause:** `compute_ict_trade_plan()` in `ict_engine.py` stores `sl_pct` as a negative
value (`round(-risk, 2)`). The actual code in `_calc_realized_r()` correctly uses
`risk = abs(sl_pct)` as the denominator. The formula tables documented the pre-bug version
of the formula and were never updated after the bug was fixed.

**Files changed:**

1. **`backtest.py`** — `write_template_performance_md()` formula table (lines ~1982–1987):
   - Changed `/ sl_pct` → `/ abs(sl_pct)` in both WIN/PARTIAL and LOSS rows
   - Added explanatory note: "sl_pct is stored as a negative value; always use abs()"

2. **`docs/ict_strategy_variant_learner/PHASE_I4_IMPLEMENTATION_REPORT.md`** — formula table:
   - Same correction
   - Added a "Critical" callout box explaining the sign convention and the original bug

**Smoke test result:**
```
_calc_realized_r('WIN', 0.85, -0.92, -0.50)  → +1.7R    (was 0.0 before bug fix)
_calc_realized_r('LOSS', 0.85, -0.92, -0.50) → -1.84R
_calc_realized_r('EXPIRED', ...)              →  0.0
_calc_realized_r('WIN', ..., sl_pct=None)     →  0.0
```

---

### C-2 — STRATEGY_VERSION NameError (Critical, pre-audit fix)

**Problem:** `STRATEGY_VERSION` was used in `write_template_performance_md()` but was not
in the `from crypto_alert import (...)` block in `backtest.py`. This caused a `NameError`
on the first post-Phase-I-3 backtest run, aborting the report generation and DB save.

**Fix:** Added `STRATEGY_VERSION,` to the import block in `backtest.py`.

**Status:** Fixed during the initial Phase I-4 implementation session, before the audit was
conducted. The fix was confirmed in the second successful backtest run.

---

### H-1 — sl_pct Negative Sign Convention Undocumented (High)

**Problem:** `ict_engine.py` line 672 silently stores `sl_pct` as a negative value with no
comment. Any developer writing new code that divides by `sl_pct` (for R-multiples, risk
sizing, or analytics) would reproduce the realized_R = 0.0 bug without knowing why.

**Fix:** Added an inline comment at `ict_engine.py` line 672:
```python
"sl_pct":round(-risk,2), ...  # sl_pct is NEGATIVE (e.g. -0.85); use abs(sl_pct) as denominator in R-multiple calculations
```

---

### H-2 — Tier C = 0 in Best-Match Unexplained (High)

**Problem:** Every backtest run shows Tier C = 0 and No Template Match = 0 in the best-match
view. Without an explanation, readers assume the classification is broken.

**Root cause (expected behavior):** Every signal this bot generates satisfies at least 3/5
Tier B confluences (MSS≥MEDIUM + FVG≥LOW + active killzone session), which supersedes Tier C
in best-match assignment. Tier C = 0 is correct, not a bug.

**Fix:** Added an explanatory blockquote to the header of `write_template_performance_md()`,
immediately after the Phase I-4 note:
```
> Expected: Tier C = 0 in Best-Match View. Every signal produced by this bot satisfies
> at least 3/5 Tier B confluences, so all Tier C candidates are superseded by Tier B...
```

---

### H-3 — All-Matched Tier B = Tier C Counts Unexplained (High)

**Problem:** The All-Matched View shows Tier B and Tier C with identical N, WR, MFE, MAE, and
realR. Readers could think this is a duplication bug.

**Root cause (expected behavior):** Every signal matching Tier C (MSS≥LOW + FVG≥LOW) also
matches Tier B because the bot's entry gates already enforce MSS≥MEDIUM and an active killzone
on every generated signal. Tier C provides zero additional coverage.

**Fix:** Added an explanatory note to the All-Matched View section of
`write_template_performance_md()`:
```
> Note: If Tier B and Tier C show identical N and metrics, this is expected...
> This is not a bug; it confirms that Tier C adds no additional coverage beyond Tier B.
```

---

### M-1 — Median realR = 0.0 Misleading (Medium)

**Problem:** Tier A training median realR showed `+0.0000R`, which appears to mean "breakeven"
but actually means EXPIRED trades are occupying the median position in the sorted distribution.

**Fix:** Added a note to the Phase I-4 Excursion Tracking Notes section:
```
> Note on Median realR = 0.0: A median realized_R of exactly 0.0 does NOT mean the strategy
> breaks even. It typically means EXPIRED trades (realR = 0.0 by definition) occupy the median
> position. Check expired count in the stats table to confirm.
```

---

### M-2 — Tautological Concentration Warnings (Medium)

**Problem:** `_overfitting_warnings()` checked for session concentration even when the signal
group was already filtered to a single session value (e.g., when called from `_dim_table` with
`dim_key="session"`). Result: every dimension breakdown produced a spurious 100% session
concentration warning that added noise and obscured real warnings.

The same problem existed for regime concentration when grouping by regime.

**Fix:** Added `dim_name` guard conditions to both concentration checks in
`_overfitting_warnings()`:
```python
# Skip regime concentration check when already grouped by regime
if top_rc / n >= _CONC_THRESH and (not dim_name or dim_name.lower() not in ("regime",)):
    warns.append(...)

# Skip session concentration check when already grouped by session
if top_sc / n >= _CONC_THRESH and (not dim_name or dim_name.lower() not in ("session",)):
    warns.append(...)
```

**Smoke test result:**
```
_overfitting_warnings('TIER_B', sigs35, 'Session', 'LONDON_KZ')
  → no session-conc warning  ✓
  → regime-conc warning fires (correctly, TRENDING=100%)  ✓

_overfitting_warnings('TIER_B', sigs35, 'Regime', 'TRENDING')
  → no regime-conc warning  ✓
  → session-conc warning fires (correctly, LONDON_KZ=100%)  ✓

_overfitting_warnings('TIER_B', sigs25)  [no dim_name — top-level call]
  → insufficient-sample warning fires  ✓
  → regime-conc warning fires  ✓
  → session-conc warning fires  ✓
```

---

### M-3 — Rollback Steps reference wrong formula (Medium)

Subsumed by C-1: updating the formula table in `PHASE_I4_IMPLEMENTATION_REPORT.md` corrects
all occurrences of the wrong formula in that document.

---

### L-2 — Phase I-3 "N/A" Note Now Stale (Low)

**Problem:** `PHASE_I3_IMPLEMENTATION_REPORT.md` stated that MFE/MAE would show "N/A" (not
yet populated). This was accurate at Phase I-3 time but is now superseded by Phase I-4.

**Fix:** Added a "Post-Fix Update" section to the end of `PHASE_I3_IMPLEMENTATION_REPORT.md`
noting that Phase I-4 is complete and pointing to `PHASE_I4_IMPLEMENTATION_REPORT.md`.

---

### L-3 — DB Column / Signal Dict Key Name Mismatch (Low)

**Problem:** The `backtest_signals` DB column is named `dr_location`, but the signal dict uses
key `dr4h_location`. The mapping is handled correctly in `save_to_db()`, but a developer
writing direct SQL would encounter confusion.

**Decision:** Column rename deferred. Renaming an SQLite column requires `ALTER TABLE ... RENAME
COLUMN` (SQLite 3.25+) and would invalidate any existing queries or saved reports that
reference `dr_location`. The mapping is already correct in code.

**Fix applied:** Added a mapping comment in `save_to_db()` at the `dr4h_location` line:
```python
s.get("dr4h_location","UNKNOWN"),  # signal dict key: dr4h_location → DB column: dr_location
```

**Remaining known limitation:** SQL analysts must query `dr_location` (DB column name), not
`dr4h_location` (Python dict key). This is documented in the fix report.

---

## Issues Rejected as Not Valid

### L-1 — _excursion_section() Absent from Phase I-4 New Functions Table

**Audit claim:** `_excursion_section()` is not given its own row in the "New Functions" table.

**Finding after code review:** The function IS documented as item 8 in
`PHASE_I4_IMPLEMENTATION_REPORT.md`:
```
**8. `_excursion_section()` — new helper**
Generates a markdown excursion breakdown table for one dimension...
```

**Decision:** Rejected. No change needed.

---

## Issues Accepted as Known Limitations (No Fix)

### M-4 — _fmt_stats_line() Produces >200-Character Console Lines

**Problem:** Phase I-4 additions push each stats line well past 200 characters, which wraps
on narrow terminals.

**Decision:** Accepted as known limitation. Shortening requires breaking the line into two
print calls or abbreviating labels, which reduces readability in wide terminals. No functional
impact. Deferred to a future cleanup pass if terminal readability becomes a real concern.

---

## Files Changed

| File | Change Type | Change Summary |
|------|-------------|----------------|
| `backtest.py` | Bug fix (doc) | Formula table in `write_template_performance_md()`: `/ sl_pct` → `/ abs(sl_pct)` + sl_pct sign note |
| `backtest.py` | Logic fix | `_overfitting_warnings()`: skip session/regime concentration when already grouped by that dimension |
| `backtest.py` | Clarity | `write_template_performance_md()`: add Tier C = 0 expected-behavior note in header |
| `backtest.py` | Clarity | `write_template_performance_md()`: add Tier B = Tier C expected-behavior note in All-Matched section |
| `backtest.py` | Clarity | `write_template_performance_md()`: add EXPIRED-at-median note in Phase I-4 Notes |
| `backtest.py` | Clarity | `save_to_db()`: add mapping comment `dr4h_location → dr_location` |
| `ict_engine.py` | Clarity | Line 672: add inline comment documenting sl_pct negative sign convention |
| `docs/ict_strategy_variant_learner/PHASE_I4_IMPLEMENTATION_REPORT.md` | Doc fix | Formula table corrected: `/ sl_pct` → `/ abs(sl_pct)`; critical sign-convention callout added; Post-Fix Corrections section added |
| `docs/ict_strategy_variant_learner/PHASE_I3_IMPLEMENTATION_REPORT.md` | Doc update | Post-Fix Update section added noting Phase I-4 supersedes N/A placeholder |

---

## DB / Schema Changes

**None.** All DB schema for Phase 1–4 was already correct. The three excursion columns
(`mfe_pct`, `mae_pct`, `realized_r`) were added via idempotent `ALTER TABLE` migrations in
Phase I-4 and contain live data. No new migrations required.

---

## Tests / Checks Performed

| Check | Method | Result |
|-------|--------|--------|
| `backtest.py` syntax | `python -c "import ast; ast.parse(open('backtest.py').read())"` | PASS |
| `ict_engine.py` syntax | `python -c "import ast; ast.parse(open('ict_engine.py').read())"` | PASS |
| `_calc_realized_r` logic | Isolated unit test (WIN, LOSS, EXPIRED, None sl_pct) | PASS |
| `_overfitting_warnings` tautology fix | Isolated unit test (3 scenarios) | PASS |
| Formula table grep | `grep "realized_r.*abs\|abs.*sl_pct"` in backtest.py | 3 matches ✓ |
| Tautology fix grep | `grep "dim_name.lower"` in backtest.py | 2 matches at correct lines ✓ |
| Tier C note grep | `grep "Expected.*Tier C"` in backtest.py | 1 match ✓ |
| ict_engine comment grep | `grep "sl_pct is NEGATIVE"` in ict_engine.py | 1 match ✓ |

---

## Remaining Risks

| Risk | Severity | Notes |
|------|----------|-------|
| DB column name `dr_location` vs dict key `dr4h_location` | Low | Mapping correct in code; SQL analysts must use `dr_location` |
| Console line length >200 chars | Low | No functional impact; cosmetic only |
| Tier A sample size (n=28 train) | Medium | Below _N_RELI=50; results should be treated as directional, not statistically reliable |
| RANGING regime performance (27.8% WR, 49% of Tier B) | Medium | Regime filtering is the highest-leverage improvement; addressed in Phase 5A design |
| Strategy at breakeven (Tier B WR 35.9% vs BEW 36.1%) | High | Tracking only; not in scope for Phase 1–4 cleanup. Phase 5A must address. |

---

## Final Go / No-Go Decision for Phase 5A

**GO.**

**Rationale:**

1. All Critical and High audit findings are resolved (code correct, documentation accurate).
2. Both Python files pass AST syntax checks.
3. Core logic fixes (`_calc_realized_r`, `_overfitting_warnings`) pass isolated smoke tests.
4. The Phase 1–4 implementation is complete, functional, and correctly documented.
5. No regressions introduced — all changes are additive or documentation-only.

**Phase 5A design constraint (strategic, not a code bug):**  
Live data from 277 backtest signals shows RANGING regime is the dominant performance drag
(49% of Tier B signals, 27.8% WR vs overall 35.9% WR). Phase 5A gate changes should
prioritize **regime filtering** before or alongside Tier C live enforcement. Blocking RANGING
in live trading has higher expected impact per change than enforcing the Tier C gate on a bucket
that already has zero best-match signals.

---

## Current Final Status of Phase 1–4

| Phase | Feature | Status |
|-------|---------|--------|
| I-1 | Investigation & audit report | Complete |
| I-2 | Template registry (strategy_templates.py) | Complete |
| I-2 | DB schema — templates + signal_variant_matches tables | Complete |
| I-2 | Template tagging in generate_signal() and save_signal() | Complete |
| I-2 | Template tagging in backtest (matched_template_id) | Complete |
| I-3 | Backtest multi-template comparison harness | Complete |
| I-3 | 80/20 holdout split + WF gap + dimension breakdowns | Complete |
| I-3 | Overfitting warnings (sample size, concentration, WF gap) | Complete (tautology fixed) |
| I-3 | Markdown report — template_performance_report.md | Complete |
| I-4 | MFE/MAE forward-scan computation | Complete |
| I-4 | realized_R calculation with correct abs(sl_pct) denominator | Complete |
| I-4 | DB columns mfe_pct, mae_pct, realized_r | Complete |
| I-4 | Excursion breakdown by session/FVG/MSS in report | Complete |
| I-4 | Phase I-4 Excursion Tracking Notes with correct formulas | Complete (fixed) |
| QA | Phase 1–4 audit findings resolved | Complete (this report) |
