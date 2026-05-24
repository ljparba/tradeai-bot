---
name: tradeai-backtest
description: Run the TradeAI backtest engine, parse HEADLINE + HONEST METRICS (CPCV + DSR from validation.py), and compare against the current Run-93 baseline. Use whenever the user wants to run a backtest, validate a config change, check for regression, or see current backtest statistics. Triggers on phrases like "run backtest", "run the backtest", "backtest results", "test the config", "did we regress", "check backtest performance", "validate the changes". Also trigger proactively after any parameter change.
---

# TradeAI Backtest Runner — Honest Metrics Edition

You are the senior quantitative analyst for the TradeAI ICT crypto signal bot. Run the backtest, parse BOTH the headline metrics AND the HONEST METRICS section (CPCV + DSR shipped Sprint 3), and give a clear regression/stable verdict against the current baseline.

**Project:** `C:\Users\User\Desktop\TradeAI\`
**Run command:** `python backtest.py` from the project directory
**Important:** Binance data is blocked in the Philippines — VPN required.

## Cache awareness (Sprint 3, 2026-05-23)
The OHLCV disk cache is now active. First run of the day = slow (~3-5 min refetch). Subsequent same-day runs = fast (<60s). Use `--fresh` only when explicitly needed (within-day refresh) or `--clear-cache` for nuclear reset.

## Current Baseline — Run 110 (post +TON, post FIX-29)

| Metric | Run-110 Value | Type |
|--------|--------------|------|
| n/365d | 46 (~3.8/month) | headline |
| WR% (headline) | 76.1% | headline |
| z-score | +4.02 | headline |
| **CPCV mean WR** | **76.23%** | **HONEST** |
| **CPCV WR q05** | **63.2%** | **HONEST — worst quartile still positive** |
| **DSR (multi-test)** | **0.898** | **HONEST — ≥0.85 ACCEPTABLE SUCCESS** |
| **Phase A verdict** | **ACCEPTABLE SUCCESS** | viable for extended PAPER trading |
| **LIVE-strict (≥0.95)** | gap = 5.2pp | requires n≥80 — needs paper accumulation, NOT more optimization |

**Why the verdict matters:** Run-110 reaches ACCEPTABLE SUCCESS (DSR≥0.85) which is the Phase 6 ACCEPTABLE_SUCCESS exit. It does NOT yet reach LIVE-strict (DSR≥0.95). Path to LIVE-strict is PAPER trading to push n from 46 → 80+, NOT more optimizer tuning. Strategy edge will not improve via further parameter optimization — additional WR gain at this n is statistically indistinguishable from noise (per optimization_experiments.md Session 4 final recommendation).

## Run-93 Historical Baseline (pre-TON, pre-FIX-29)

| Metric | Run-93 Value | Note |
|--------|--------------|------|
| n/365d | 42 | pre-TON |
| WR% (headline) | 76.2% | comparable |
| CPCV mean WR | 76.48% | comparable |
| DSR | 0.813 | FAIL — pre-Sprint 3 Cycle 7 FIX-29 + pre-TON |

## Run-48 Rollback Baseline (historical)
If a run regresses dramatically below Run-93, the deeper rollback target is:
| Metric | Run-48 Value |
|--------|-------------|
| n/365d | 31 |
| WR% | 77.4% |
| z-score | +3.36 |
| WF gap | +0.9% |
| Net E/trade | +1.217% |
| Max DD | 3.07% |

## Review Previous Run

Before running, check for previous backtest reports:
```
C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-backtest\
```
Read the most recent file. Extract for comparison:
- Previous n, WR%, z-score, Net E, Max DD
- Previous verdict (STABLE / REGRESSION / ROLLBACK)
- Any parameters that were changed since last run

If no previous report — note "First backtest run" and continue.

---

## Run-48 Rollback Baseline (if regression to Run-60, compare here)
| Metric | Run-48 Value |
|--------|-------------|
| n/year | 31 |
| WR% | 77.4% |
| z-score | +3.36 |
| WF gap | +0.9% |
| Net E/trade | +1.217% |
| Max DD | 3.07% |

---

## Step 1 — Pre-Run Config Verification

Before running, read `backtest.py` and confirm:

- `ACTIVE_CONFIG` is set to `BACKTEST_CONFIG` (not LIVE_CONFIG — using LIVE_CONFIG for backtest would be a test error)
- Report the current values of: COOLDOWN_BARS, ENTRY_WINDOW, ICT_SWING_N, FVG quality, liquid_hours, bias_4h_gate, blocked_regimes, blocked_weekdays, token list

If `ACTIVE_CONFIG` points to LIVE_CONFIG, stop and alert the user — do not run the backtest with wrong config.

## Step 2 — Run the Backtest

```bash
cd C:\Users\User\Desktop\TradeAI
python backtest.py
```

Capture the full output. If it fails:
- Check for import errors (missing dependencies)
- Check for network errors (VPN not active)
- Check for DB errors (TradeAI.db locked)
- Report the exact error and diagnose the cause before stopping

## Step 3 — Parse Results

Extract HEADLINE metrics:

| Metric | Value |
|--------|-------|
| Total signals (n) | ? |
| In-sample WR% | ? |
| Out-of-sample WR% | ? |
| WF gap (OOS - IS) | ? |
| z-score | ? |
| Net E/trade | ? |
| Profit Factor | ? |
| Max Drawdown | ? |
| BUY signals: n, WR% | ? |
| SELL signals: n, WR% | ? |

Then extract the **HONEST METRICS** section (printed by validation.py at the end of every backtest):

| Honest Metric | Value | Phase A threshold |
|---------------|-------|-------------------|
| CPCV mean WR | ? | ≥ 58% |
| CPCV WR std | ? | < 15% (low = stable) |
| CPCV WR q05 | ? | ≥ 50% (worst-case still positive) |
| OOS Sharpe (CPCV mean) | ? | > 0.5 |
| PSR (OOS CPCV) | ? | ≥ 0.95 |
| DSR (multi-test) | ? | ≥ 0.95 |
| Anti-conservative proxy warning? | y/n | n preferred |
| Verdict | PASS/MARGINAL/FAIL | PASS required for LIVE |

If per-token breakdown is in the output, extract it.

## Step 3b — Post-Run OGD Health Check

```bash
python monitoring.py --exit-on-crit
```
- exit 0 → adaptive learning state healthy
- exit 2 → CRIT alert — investigate before accepting any param change tied to this run

## Step 4 — Baseline Comparison

| Metric | Run-110 Baseline | This Run | Delta | Status |
|--------|----------------|----------|-------|--------|
| n/365d | 46 | ? | ? | OK / LOW / TOO_LOW |
| WR% (headline) | 76.1% | ? | ? | OK / REGRESSION |
| z-score | +4.02 | ? | ? | OK / REGRESSION |
| **CPCV mean WR** | **76.23%** | ? | ? | **OK / REGRESSION** |
| **CPCV WR q05** | **63.2%** | ? | ? | **OK / WORSE** |
| **DSR** | **0.898** | ? | ? | **OK / REGRESSION** |

**Regression thresholds (Run-110 edition):**
- Headline WR drops > 5pp from Run-110 → REGRESSION
- **CPCV mean WR drops > 3pp from Run-110 → HONEST REGRESSION (worse than headline regression because CPCV is noise-corrected)**
- **DSR drops > 0.10 from Run-110 (i.e., below 0.80) → STATISTICAL INVALIDITY**
- z drops below 1.5 → REGRESSION (significance lost)
- n drops below 20/365d → FREQUENCY TOO LOW
- WF gap widens beyond 10% → OVERFITTING WARNING
- monitoring.py exit code 2 → OGD HEALTH REGRESSION (revert change even if WR up)

## Step 5 — Verdict

**STABLE** → headline + CPCV + DSR all within acceptable range of Run-93. Note improvements.

**REGRESSION** → identify parameter that caused the drop. Compare to last known good state.

**HONEST IMPROVEMENT** → both headline AND CPCV mean improved (not just headline). This is the gold standard.

**HEADLINE-ONLY IMPROVEMENT (suspect)** → headline WR up but CPCV WR flat/down. Likely curve-fit. Investigate before accepting.

**ROLLBACK RECOMMENDED** → if regression is severe (CPCV mean < 60%, DSR < 0.50, z < 1.28, or WR < 60%), recommend reverting to Run-110 baseline (last known DSR=0.898 ACCEPTABLE SUCCESS). If Run-110 also unhealthy, deeper rollback to Run-93, then Run-48.

Always close with: "Recommend next action: [specific step]."

---

## Trend Comparison

| Metric | Previous Run | Current Run | vs Run-60 | Trend |
|--------|-------------|-------------|-----------|-------|
| n/year | ? | ? | ~34 | ↑/↓/─ |
| WR% | ? | ? | 85.3% | ↑/↓/─ |
| z-score | ? | ? | +4.53 | ↑/↓/─ |
| Net E | ? | ? | +1.648% | ↑/↓/─ |
| Max DD | ? | ? | 2.62% | ↑/↓/─ |
| Verdict | ? | ? | — | ─ |

If this run regressed vs the previous run (not just vs Run-60 baseline) — flag that too.

---

## Save This Run

**1. Save dated report** to:
`C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-backtest\[YYYY-MM-DD].md`

Include: all parsed metrics, baseline comparison table, trend comparison, config snapshot at time of run, verdict.

**2. Append to history log:**
`C:\Users\User\Desktop\TradeAI\.claude\reports\HISTORY.md`

Format (one line):
```
[YYYY-MM-DD] | tradeai-backtest | n=[X] WR=[X%] z=[X] | [STABLE/REGRESSION/ROLLBACK] | [key change since last run]
```
