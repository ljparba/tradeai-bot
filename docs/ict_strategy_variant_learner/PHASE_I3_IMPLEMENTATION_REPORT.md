# Phase I-3 Implementation Report — Backtest Multi-Template Comparison Harness

**Date:** 2026-05-20  
**Author:** Claude (Sonnet 4.6)  
**Scope:** Reporting/analytics only — no live gate changes, no adaptive learning modifications, no per-template OGD, no Tier C enforcement.

---

## Overview

Phase I-3 adds a Backtest Multi-Template Comparison Harness to `backtest.py`. Every time the backtest runs, it produces a per-tier statistical breakdown of signal performance, a holdout validation split, overfitting warnings, and a markdown report saved to `docs/ict_strategy_variant_learner/template_performance_report.md`.

---

## Files Changed

### `backtest.py`

**New section added** between `print_rolling_wf_report()` and `generate_recommendations()`:

```
# PHASE I-3 — ICT STRATEGY VARIANT LEARNER — TEMPLATE HARNESS
```

**New constants:**
- `_N_WARN = 30` — sample size below which results are flagged as insufficient
- `_N_RELI = 50` — sample size at or above which results are flagged as reliable
- `_CONC_THRESH = 0.70` — concentration warning threshold (70%)

**New functions:**

| Function | Purpose |
|----------|---------|
| `_tier_stats(sigs)` | Compute n, wins, partial, losses, expired, WR%, weighted WR%, avg P&L, avg confidence, avg RR, max drawdown for a signal list |
| `_holdout_split(all_signals, train_frac=0.80)` | Chronological 80/20 split — distinct from existing 60/40 `walk_forward_split` |
| `_reconstruct_variant_features(s)` | Rebuild features dict from backtest signal dict (handles `dr4h_location` key, int `smt_confirmed`) |
| `_overfitting_warnings(tier_id, sigs, dim_name, dim_val)` | Return warning strings for n < 30, regime concentration ≥ 70%, session concentration ≥ 70% |
| `_dim_table(sigs, dim_key, tier_id, dim_label)` | Per-dimension breakdown grouped by a signal field, sorted by WR desc |
| `template_comparison_report(all_signals)` | Main analytics function — returns structured report dict |
| `_fmt_stats_line(st, label)` | Format a stats dict to a single console line |
| `print_template_report(report)` | Print formatted report to console |
| `write_template_performance_md(report, out_dir)` | Write markdown report to `docs/ict_strategy_variant_learner/template_performance_report.md` |

**Integration in `main()`** (after `print_rolling_wf_report(wf_results)`):
```python
tmpl_report   = template_comparison_report(all_signals)
print_template_report(tmpl_report)
_tmpl_out_dir = os.path.join(_ROOT, "docs", "ict_strategy_variant_learner")
_tmpl_md_path = write_template_performance_md(tmpl_report, _tmpl_out_dir)
print(f"[PHASE I-3] Template report → {_tmpl_md_path}")
```

---

## Report Structure

### Best-Match View (primary)
Each signal is assigned to its **highest-tier** matching template (`matched_template_id` stored in signal dict from Phase I-2). Groups: `TIER_A`, `TIER_B`, `TIER_C`, `NONE`.

For each tier:
- Train (80%) stats and Holdout (20%) stats
- WF gap (train WR − holdout WR) with OVERFIT flag if > 10%
- Dimension breakdowns on training set: Direction, Regime, Session, FVG Quality, MSS Quality, DR Location, Entry Type

### All-Matched View (secondary)
Each signal is re-evaluated via `evaluate_confluences_vs_templates()` and counted in **every** template it satisfies (overlapping). Provides raw template fitness independent of tier priority.

### Overfitting Warnings
- **Insufficient sample:** n < 30 per group
- **Regime concentration:** ≥ 70% of tier signals in one regime
- **Session concentration:** ≥ 70% of tier signals in one session
- **WF gap:** train WR − holdout WR > 10%

---

## Key Implementation Notes

### `dr4h_location` vs `dr_location`
Backtest signal dicts store the DR location under key `dr4h_location` (not `dr_location`). `_reconstruct_variant_features()` and `_dim_table()` both handle this mapping explicitly.

### `smt_confirmed` type
Stored as `int` (0/1) in backtest signal dicts. `_reconstruct_variant_features()` converts to `bool` for `evaluate_confluences_vs_templates()`.

### Holdout split is chronological
`_holdout_split()` sorts by `ts` then takes the last 20% as holdout — same principle as the existing 60/40 WF split but with an 80/20 ratio to give more training data for dimension breakdowns.

### Dimension breakdowns on training set only
Overfitting warnings and dimension tables use only the training portion of signals. Holdout is used only for the top-level WR comparison.

### No signals edge case
All functions handle empty signal lists gracefully: `_tier_stats` returns `None`, `template_comparison_report` returns `None`, `write_template_performance_md` writes a placeholder file.

### No existing behavior changed
- No live gates modified
- No adaptive learning (OGD) changes
- No Tier C live enforcement added
- No per-template config auto-adjustment
- Entire Phase I-3 block is analytics-only; failure of any new function does not affect signal generation, DB writes, or the adaptive learning bootstrap

---

## Output Files

| File | Generated when |
|------|----------------|
| `docs/ict_strategy_variant_learner/template_performance_report.md` | Every backtest run |
| `docs/ict_strategy_variant_learner/PHASE_I3_IMPLEMENTATION_REPORT.md` | One-time (this file) |

---

## Rollback

To disable Phase I-3 without removing code, comment out the 4-line integration block in `main()` (search for `tmpl_report = template_comparison_report`). The new functions are self-contained and unused when not called from `main()`.

---

## Next Phases (not implemented here)

| Phase | Scope |
|-------|-------|
| I-4 | MFE/MAE/realized_r tracking (DB columns already added in Phase I-2, now NULL) |
| I-5 | Tier C live gating — enforce `live_allowed=False` as a hard gate |
| I-6 | Per-template OGD adaptive learning — confidence weight adjustment per tier |

---

## Post-Fix Update (Phase 1–4 QA Audit — 2026-05-20)

**Phase I-4 is now complete.** The "MFE/MAE shown as N/A" note in this report referred to the
pre-I-4 placeholder state. After Phase I-4 implementation:

- `mfe_pct`, `mae_pct`, and `realized_r` are computed by `compute_excursions()` and
  `_calc_realized_r()` for every signal in `run_backtest_token()`.
- All three fields are stored in `backtest_signals` and displayed in
  `template_performance_report.md`.
- The excursion breakdown by session, FVG quality, and MSS quality is now generated in the
  `_excursion_section()` helper.

See `PHASE_I4_IMPLEMENTATION_REPORT.md` for full details.
