# Held-Out Lockbox Protocol (Phase C)

**Status:** SHIPPED 2026-05-26
**Owner:** Operator (Cebu, Philippines)
**Module:** `walk_forward.py` (pure logic), `validation.py` (CPCV integration), `scripts/validate_baseline_held_out.py` (one-shot tool)
**Closes:** CROSS_REF C2 (no true walk-forward hold-out) — RESOLVED

---

## 1. What it is

The most-recent `HELD_OUT_DAYS` (default 90) of historical signals are RESERVED. They are NEVER touched during tuning, parameter search, Optuna trials, or the autonomous explorer. They exist for ONE PURPOSE: a single end-of-cycle verdict that asks the only honest question — *does this baseline survive on data it has never seen?*

The protocol is industry-standard quant practice. It exists because of the C2 KNOWN STRUCTURAL: every historical Optuna trial, every manual backtest, and every explorer cycle has touched the full 365 days of data. CPCV alone cannot detect overfit-to-the-full-window because every fold mixes train and test bars across the same time period. WFV (in this codebase via `walk_forward.walk_forward()`) detects parameter decay but not overfit-by-search.

The held-out lockbox is the missing third leg: a fixed, unseen, end-of-data window used for one-shot validation.

---

## 2. The unbreakable rule

> **Once a held-out window is locked, it is touched ONE time per promotion candidate. That's it. No "let me check again," no "run it twice to be sure," no "let me retry with a different gate."**

Repeat-querying the held-out is **data snooping**. Every additional touch effectively trains on it and destroys its validation power. The Phase C value comes precisely from the rarity of access.

Acceptable access patterns:
1. **At promotion time**: `python3 scripts/validate_baseline_held_out.py` once per candidate, then act on the verdict.
2. **At paper-trading-window rollover** (planned future): when the held-out window has fully "aged out" into the past and become tuning data, re-lock a new held-out at the new tail.
3. **At LIVE clearance**: one final check against the operator-pinned baseline before EXECUTION_MODE flips.

Unacceptable:
- Running it before every backtest "for context"
- Querying it during Optuna trials
- Re-running it after a tweak "to see if the verdict improved"
- Reporting it on the dashboard for monitoring

If you find yourself reaching for the held-out outside the three acceptable moments above, stop. The verdict you're seeking is no longer honest.

---

## 3. The three verdicts

Per `walk_forward.held_out_summary()`:

| Verdict | Condition | What it means | Operator action |
|---------|-----------|---------------|-----------------|
| **ROBUST** | held-out WR ≥ `min_wr_pct` (default 58%) AND \|gap\| < `max_gap_pp/2` (default 4pp) | Baseline generalizes. Held-out within tight tolerance of tuning. | Promote / proceed |
| **BORDERLINE** | held-out WR ≥ `min_wr_pct` AND \|gap\| < `max_gap_pp` (default 8pp) | Some drift but still tradeable. | Promote BUT plan rebuild within 2 months |
| **OVERFIT** | otherwise (held-out below floor OR gap too large) | Baseline does not generalize. | Block promotion; investigate; rollback to prior baseline if already promoted |
| INSUFFICIENT_SAMPLE | n_held_out < 5 | Cannot validate. | Defer; rerun after more data accrues |

The thresholds (`min_wr_pct`, `max_gap_pp`) are configurable via CLI flags or env vars. Defaults match the Phase A exit criteria (CPCV mean WR ≥ 58%, ±8pp gap as the "good enough" generalization band).

---

## 4. Integration with auto-promotion

`scripts/promote_baseline.py --auto` enforces the held-out gate when `--held-out-days N` (or `HELD_OUT_DAYS=N` env) is set:

```bash
# Auto-promotion path (autonomous explorer)
python3 scripts/promote_baseline.py --run-id <id> --auto \
    --held-out-days 90 --label "..."
```

Behavior:
- If verdict is **ROBUST** or **BORDERLINE**: promotion proceeds.
- If verdict is **OVERFIT**: process exits with code 2; baseline_pin.json is NOT updated; tune_history is NOT inserted.
- If verdict is **INSUFFICIENT_SAMPLE**: a warning is printed but promotion proceeds (sample-size cliff is not the same as failure).

Manual promotion (no `--auto`) prints the gate result but does NOT block. The operator decides.

---

## 5. Honesty caveats

### 5a. C2 contamination is acknowledged, not erased

When we lock the first held-out (2026-05-26 onward), the prior history (back to 2025-05-26) was already touched by hundreds of explorer trials + manual backtests. The held-out lockbox restores forward-looking honesty — from this point forward, the explorer cannot peek at the most-recent 90 days — but it does NOT retroactively cleanse the historical contamination of the tuning portion.

This is documented in `docs/comprehensive/CROSS_REF.md` C2: the "real" forward generalization will be answered by LIVE paper trading, where every signal is genuinely out-of-sample. Phase C is the best in-sample approximation; LIVE is the ground truth.

### 5b. The n=7 baseline complication

Post-Phase-B.1 baseline (Run-78) has n=7 total signals. At 365d, the chronological split of n=7 across tune/held-out is statistically meaningless — likely n_held_out < 5, triggering INSUFFICIENT_SAMPLE. This is the **honest result** at the current strategy selectivity. The Phase C infrastructure is deployed and ready; the validation becomes statistically meaningful as the strategy generates more signals (either through accumulated live paper data, or future relaxation of one of the binding gates).

Treat Phase C now as **infrastructure that will pay off later**, not an immediate verdict on the current baseline.

### 5c. WFV is informational, not a verdict gate

`walk_forward.walk_forward()` runs every backtest (no env flag required) and reports the decay slope. Decay detection is a yellow flag, not a hard block. The verdict gates are:
- **CPCV + DSR** (multiple-testing correction; gate at `validation.py:646-659`)
- **Held-out** (one-shot generalization; gate at `promote_baseline.py:_check_held_out_gate`)

WFV is a third signal the operator considers when reading the report.

---

## 6. Files / Reference Points

- `walk_forward.py` — `walk_forward()`, `split_held_out()`, `held_out_summary()`, text-report helpers
- `tests/test_walk_forward.py` — 12 unit tests (basic, decay, split, summary, Wilson CI)
- `validation.py:cpcv_summary_split()` — dual-pool convenience wrapper
- `backtest.py:HELD_OUT_DAYS` — opt-in env var (default 0 = backward compatible)
- `scripts/promote_baseline.py:_check_held_out_gate()` — auto-promotion gate
- `scripts/validate_baseline_held_out.py` — one-shot operator tool
- `docs/LIVE_BACKTEST_PARITY_ROADMAP.md` — Phase C section
- `docs/comprehensive/CROSS_REF.md` — C2 entry (RESOLVED)

---

## 7. Quick-reference commands

```bash
# Run a backtest with held-out reporting (opt-in)
HELD_OUT_DAYS=90 python3 backtest.py

# One-shot validation of the current baseline
python3 scripts/validate_baseline_held_out.py

# Same, as machine-readable JSON
python3 scripts/validate_baseline_held_out.py --json

# Override the run_id (e.g. validate a candidate before promoting)
python3 scripts/validate_baseline_held_out.py --run-id 200

# Auto-promotion with held-out gate
python3 scripts/promote_baseline.py --auto --held-out-days 90 \
    --run-id <id> --label "..." --param X --old Y --new Z
```

---

**End of held-out protocol. The lockbox is locked.**
