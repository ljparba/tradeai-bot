# Phase I-4 Implementation Report — MFE, MAE, and realized_R Tracking

**Date:** 2026-05-20  
**Author:** Claude (Sonnet 4.6)  
**Scope:** Outcome quality tracking only. No live gate changes, no adaptive learning modifications, no per-template OGD, no Tier C enforcement.

---

## Overview

Phase I-4 adds Maximum Favorable Excursion (MFE), Maximum Adverse Excursion (MAE), and realized R-multiple tracking to every backtest signal. Values are computed during the forward scan in `run_backtest_token()`, stored in `backtest_signals`, and surfaced in the Phase I-3/I-4 template performance report.

---

## Files Changed

### `backtest.py`

**1. `init_backtest_db()` — DB migration**

Three new columns added to the `ALTER TABLE` migration list:

```python
("mfe_pct",    "REAL"),
("mae_pct",    "REAL"),
("realized_r", "REAL"),
```

These are safe, idempotent migrations — `try/except` swallows the error if the column already exists.

---

**2. `compute_excursions()` — new function** (inserted after `check_outcome`)

```python
def compute_excursions(direction, entry_price, sl, tp1, future_bars):
```

**Formulas:**

| Direction | MFE | MAE |
|-----------|-----|-----|
| BUY | `(max_high - entry) / entry * 100` | `(entry - min_low) / entry * 100` |
| SELL | `(entry - min_low) / entry * 100` | `(max_high - entry) / entry * 100` |

**Scanning rules:**
- Scans the same `future_bars` list used by `check_outcome`
- Stops scanning when SL or TP1 is hit (identical boundary to `check_outcome`)
- Values are always >= 0.0 (clamped with `max(0.0, ...)`)

**Safety checks:**
- Returns `(0.0, 0.0)` if `future_bars` is empty
- Returns `(0.0, 0.0)` if `entry_price` is None or <= 0
- Returns `(0.0, 0.0)` if `sl` or `tp1` is None

---

**3. `_calc_realized_r()` — new function**

```python
def _calc_realized_r(outcome, net_tp1_pct, net_sl_pct, sl_pct):
```

**Formula:**

| Outcome | realized_R |
|---------|-----------|
| WIN, PARTIAL_TP1, PARTIAL_TP2 | `net_tp1_pct / abs(sl_pct)` (conservative — uses TP1 exit for all wins) |
| LOSS, SL_HIT | `net_sl_pct / abs(sl_pct)` (approximately -1.0, slightly more negative due to fees) |
| EXPIRED, NO_FILL | `0.0` |
| sl_pct is None or risk == 0 | `0.0` |

> **Critical: `sl_pct` sign convention.** `compute_ict_trade_plan()` in `ict_engine.py` stores
> `sl_pct` as a **negative** value: `"sl_pct": round(-risk, 2)` (e.g. `-0.85` for a 0.85% SL).
> The implementation uses `risk = abs(sl_pct)` as the denominator — **never divide by `sl_pct`
> directly**, as the value is negative and the guard `if sl_pct <= 0` would incorrectly return
> `0.0` for every trade. This was the root cause of the original realized_R = 0.0 bug.

`net_tp1_pct` and `net_sl_pct` are already net of round-trip fees (imported from `crypto_alert`).

---

**4. `run_backtest_token()` — excursion computation**

Inserted after `check_outcome` call:

```python
_mfe_pct, _mae_pct = compute_excursions(
    direction, eff_price, plan["sl"], plan["tp1"], future)
_real_r = _calc_realized_r(
    outcome, plan["net_tp1_pct"], plan["net_sl_pct"], plan["sl_pct"])
```

Signal dict extended:
```python
"mfe_pct":    _mfe_pct,
"mae_pct":    _mae_pct,
"realized_r": _real_r,
```

---

**5. `save_to_db()` — DB write**

Column list extended (now 41 columns):
```sql
...tp_reached, outcome, matched_template_id, template_scores_json,
mfe_pct, mae_pct, realized_r
```

Values use `.get()` with `None` as default so old signals without these fields save cleanly.

---

**6. `_tier_stats()` — Phase I-4 metrics**

Four new fields added to the stats dict:

```python
"avg_mfe":    avg_mfe,    # float or None if no signals have mfe_pct
"avg_mae":    avg_mae,    # float or None
"avg_real_r": avg_real_r, # float or None
"med_real_r": med_real_r, # float or None (median of realized_r)
```

`None` is returned for any metric when the source values are all missing — prevents crashes when processing signals from before Phase I-4 was deployed.

---

**7. `template_comparison_report()` — training signals per tier**

The report dict now includes:
```python
"_tier_train_sigs": {tid: [signals...] for tid in ["TIER_A","TIER_B","TIER_C","NONE"]}
```

This lets `write_template_performance_md` build per-tier MFE/MAE excursion tables without re-grouping.

---

**8. `_excursion_section()` — new helper**

Generates a markdown excursion breakdown table for one dimension (session, FVG quality, MSS quality):

```
| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
```

Appended inside the "Excursion Analysis" subsection of each tier's training breakdown.

---

**9. `_fmt_stats_line()` — updated console output**

Now shows MFE, MAE, and realR on each stats line:
```
Train (80%)          n=48  WR=52.1%  wWR=51.3%  ...  MFE=+1.23%  MAE=+0.87%  realR=+1.02R  [CAUTION]
```

---

**10. `write_template_performance_md()` — updated report**

Changes:
- Quick Summary table: adds Avg MFE%, Avg MAE%, Avg realR columns
- Per-tier stats table: adds Avg MFE%, Avg MAE%, Avg realR, Med realR columns
- Dimension Breakdowns table: adds Avg MFE%, Avg MAE%, Avg realR columns
- New "Excursion Analysis" section per tier: MFE/MAE by Session, FVG Quality, MSS Quality
- All-Matched View: adds MFE%, MAE%, realR columns
- New "Phase I-4 Excursion Tracking Notes" section with formula reference

---

## SQL Verification Queries

```sql
-- Check that new columns exist and have values (after one backtest run)
SELECT COUNT(*), AVG(mfe_pct), AVG(mae_pct), AVG(realized_r)
FROM backtest_signals
WHERE mfe_pct IS NOT NULL;

-- MFE/MAE by template tier
SELECT matched_template_id,
       COUNT(*) as n,
       ROUND(AVG(mfe_pct), 4) as avg_mfe,
       ROUND(AVG(mae_pct), 4) as avg_mae,
       ROUND(AVG(realized_r), 4) as avg_realized_r,
       ROUND(100.0 * SUM(CASE WHEN outcome IN ('WIN','PARTIAL_TP2','PARTIAL_TP1') THEN 1 ELSE 0 END) / COUNT(*), 1) as wr_pct
FROM backtest_signals
GROUP BY matched_template_id
ORDER BY avg_realized_r DESC;

-- MFE by session
SELECT session,
       COUNT(*) as n,
       ROUND(AVG(mfe_pct), 4) as avg_mfe,
       ROUND(AVG(mae_pct), 4) as avg_mae,
       ROUND(AVG(realized_r), 4) as avg_realized_r
FROM backtest_signals
WHERE mfe_pct IS NOT NULL
GROUP BY session;

-- MFE by FVG quality
SELECT fvg_quality,
       COUNT(*) as n,
       ROUND(AVG(mfe_pct), 4) as avg_mfe,
       ROUND(AVG(mae_pct), 4) as avg_mae,
       ROUND(AVG(realized_r), 4) as avg_realized_r
FROM backtest_signals
WHERE mfe_pct IS NOT NULL
GROUP BY fvg_quality
ORDER BY avg_realized_r DESC;

-- MFE by MSS quality
SELECT mss_quality,
       COUNT(*) as n,
       ROUND(AVG(mfe_pct), 4) as avg_mfe,
       ROUND(AVG(mae_pct), 4) as avg_mae,
       ROUND(AVG(realized_r), 4) as avg_realized_r
FROM backtest_signals
WHERE mfe_pct IS NOT NULL
GROUP BY mss_quality
ORDER BY avg_realized_r DESC;

-- Verify no NULL-crash risk in old signals
SELECT COUNT(*) as old_signals_without_excursions
FROM backtest_signals
WHERE mfe_pct IS NULL;
```

---

## Sample Output

### Console (per tier)
```
  Train (80%)          n=148  WR=54.1%  wWR=53.8%  AvgPnL=+0.12%  AvgConf=6.7
                               AvgRR=2.31  MaxDD=4.23%  MFE=+1.45%  MAE=+0.87%
                               realR=+1.02R  [RELIABLE]
```

### Markdown (Quick Summary table)
```
| Template    | N (all) | Train WR% | Holdout WR% | WF Gap | Avg MFE% | Avg MAE% | Avg realR | Status |
|-------------|---------|-----------|-------------|--------|----------|----------|-----------|--------|
| Tier A      | 120     | 57.3%     | 51.2%       | +6.1%  | +1.89%   | +0.76%   | +1.12R    | OK     |
| Tier B      | 95      | 48.2%     | 45.1%       | +3.1%  | +1.34%   | +1.12%   | +0.76R    | OK     |
```

### Excursion section (by session)
```
##### Session

| Value       | N  | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR%   |
|-------------|----|----------|----------|-----------|-----------|-------|
| LONDON_KZ   | 45 | +1.92%   | +0.73%   | +1.18R    | +0.94R    | 58.2% |
| NY_AM_KZ    | 38 | +1.67%   | +0.89%   | +0.97R    | +0.84R    | 52.6% |
| OVERNIGHT   | 22 | +1.21%   | +1.34%   | +0.41R    | +0.28R    | 43.2% |
```

---

## Key Design Decisions

**Why stop MFE/MAE at SL/TP1?**  
Tracking excursions past the trade's natural close would misrepresent what the trade actually experienced. Stopping at the same boundary as `check_outcome` ensures MFE/MAE reflect only the price action the trader was exposed to.

**Why use TP1 for all wins in realized_R?**  
TP2 and TP3 prices are not stored in the signal dict (only `tp1_pct` and `tp2_target_type`). Using TP1 conservatively understates wins but ensures the formula is always computable without additional data. This will be improved in Phase I-5 once TP2/TP3 prices are stored.

**Why `None` default instead of `0.0`?**  
Using `None` in the DB allows the analytics layer to distinguish "trade had zero excursion" from "excursion not yet computed" (e.g., live signals before Phase I-4). The `.get("mfe_pct") is not None` filter in `_tier_stats` handles both cases correctly.

---

## Rollback Steps

1. The three new DB columns (`mfe_pct`, `mae_pct`, `realized_r`) are optional — existing code continues working with `NULL` values; analytics show "N/A" where these are absent.
2. To stop computing excursions: comment out the 4-line block in `run_backtest_token` starting with `# Phase I-4: excursion metrics`.
3. To remove from DB writes: remove the three lines (`mfe_pct`, `mae_pct`, `realized_r`) from the INSERT column list and value tuple in `save_to_db`.
4. `_tier_stats` is backwards-compatible — filters on `is not None` so old signal dicts without these fields return `avg_mfe=None` etc. without crashing.

---

## What is NOT Changed

- Live trading gates (no changes to `strategy_engine.py` or `crypto_alert.py`)
- Adaptive learning / OGD weights (`adaptive_engine.py` untouched)
- Tier C live enforcement (still paper-only by convention, not by gate)
- Signal generation logic (no changes to ICT detection)
- Existing backtest performance metrics (WR%, net expectancy, WF gap)

---

## Post-Fix Corrections (Phase 1–4 QA Audit — 2026-05-20)

The following issues were identified in the Phase 1–4 QA audit and corrected after initial implementation:

### C-1: realized_R formula documented incorrectly (FIXED)

**Original documentation** (this report, formula table above) showed:
```
WIN/PARTIAL: net_tp1_pct / sl_pct
LOSS:        net_sl_pct / sl_pct
```

**Correct formula** (matches code):
```
WIN/PARTIAL: net_tp1_pct / abs(sl_pct)
LOSS:        net_sl_pct / abs(sl_pct)
```

**Root cause:** `ict_engine.py` stores `sl_pct` as a negative value (`round(-risk, 2)`). The
original formula table failed to reflect the `abs()` call in `_calc_realized_r()`. This caused
the formula table in `write_template_performance_md()` to also document the wrong formula.

**Files fixed:**
- `PHASE_I4_IMPLEMENTATION_REPORT.md` — formula table updated (this section)
- `backtest.py` — formula table in `write_template_performance_md()` corrected
- `ict_engine.py` line 672 — inline comment added documenting the negative sign convention

### C-2: STRATEGY_VERSION NameError on first run (FIXED during implementation)

`STRATEGY_VERSION` was used in `write_template_performance_md()` but not imported into
`backtest.py`. Fixed by adding it to the `from crypto_alert import (...)` block. This fix
was applied during the initial implementation session before the audit was conducted.

### Status after fixes

All Phase I-4 features are confirmed functional. Two successful backtest runs completed after
all fixes, with 277 signals and correct MFE/MAE/realized_R values in the DB and report.
