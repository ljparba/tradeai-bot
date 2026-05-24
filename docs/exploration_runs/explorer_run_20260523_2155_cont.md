# Backtest Explorer — Cycle 1c CONTINUATION Started 2026-05-23 21:55 UTC

**Continuation of:** `docs/exploration_runs/explorer_run_20260523_2044.md` (Cycle 1c — only P-2b ran)

**Why this cycle:** Cycle 1c v2 agent quit after 1/7 experiments. Operator promoted P-2b inline → Run-144. This continuation hand-runs the 6 deferred experiments against the **new** Run-144 baseline (ICT_SWEEP_LOOKBACK=20, honest DSR baked in).

**Baseline snapshot:** `data/snapshots/signals_baseline_run144_20260523_2152_p2b_honest_dsr.db` (run 144)
**Code state hash (start):** `bf1a1db0f391b3d95b8a34df0e2af57dd95f52637a5c73b48adeb1916676dc1e` is **OLD** (Run-128 era). New start hash recorded below.

## Baseline reference — Run 144 (P-2b promoted, honest DSR)

```
n=45 | WR=77.8% (TP/SL/TIMEOUT) | BEW~0.30
CPCV WR mean=77.78% (std=7.86%)
CPCV Sharpe mean=0.870 (std=0.219)
PSR OOS=100.0% | DSR=100.0% [n_trials=16, bench_SR=0.140, SR_trial_std=0.0777 HONEST]
Walk-forward: train 73.9% (n=23), test 81.8% (n=22), overfit_gap=-7.9%
```

Active gates:
- BACKTEST_BIAS_4H_GATE=`none` (F-8) | BACKTEST_TREND_1H_GATE=`loose`
- BACKTEST_DEALING_RANGE_GATE=`False` | BACKTEST_MSS_MIN_QUALITY=`LOW`
- BACKTEST_FVG_MIN_QUALITY=`HIGH` | BACKTEST_SMT_GATE=`False`

ICT constants (start values — POST-P-2b):
- ICT_SWING_N=2 | **ICT_SWEEP_LOOKBACK=20** (P-2b) | ICT_MSS_HORIZON=30
- ICT_FVG_MIN_GAP=0.001 | ICT_FVG_SIZE_BONUS_THRESHOLD=0.003
- DEALING_RANGE_LOOKBACK=50 | ICT_EQH_TOLERANCE=0.0015

## Adapted queue (6 experiments)

Original Cycle 1c queue had TP-5c (SWING_N=3 + SWEEP_LOOKBACK=45) and TP-8b (MIN_GAP=0.001 + SIZE_BONUS=0.005) paired with what is now baseline. Adapted:
- TP-5c′: SWING_N=3 alone (SWEEP_LOOKBACK=45 conflicts with baseline=20)
- TP-8b′: SIZE_BONUS=0.005 alone (MIN_GAP=0.001 IS baseline)
- TP-8c remains a true paired test (MIN_GAP=0.0015 + SIZE_BONUS=0.005)

## Result Table

| Exp  | Hypothesis | Param change | Run | n | dn | WR | dWR | CPCV WR mean | dCPCV | DSR | Notes |
|------|-----------|--------------|-----|---|-----|-----|------|--------------|-------|-----|-------|
| 0    | Baseline (Run 144) | — | 144 | 45 | 0 | 77.8% | — | 77.78% | — | 100.0% | Reference |
| P-3b | Shorter MSS window | ICT_MSS_HORIZON 30→15 | 145 | 45 | 0 | 77.8% | 0 | 77.78% | 0 | 100.0% | **NO-OP** — identical to baseline. MSS window doesn't bind at current gates. |
| P-4b | Tighter FVG gap | ICT_FVG_MIN_GAP 0.001→0.0015 | 146 | 45 | 0 | 77.8% | 0 | 77.78% | 0 | 100.0% | **NO-OP** — FVG=HIGH gate already filters. |
| P-6b | Tighter EQH cluster tol | ICT_EQH_TOLERANCE 0.0015→0.001 | 147 | 45 | 0 | 77.8% | 0 | 77.78% | 0 | 100.0% | **NO-OP** — config_hash matches baseline (not in hash). EQH bonus inert. |
| TP-5c′ | Stricter swing confirmation | ICT_SWING_N 2→3 | 148 | 46 | +1 | **73.9%** | **−3.9pp** | **74.04%** | **−3.74pp** | 100.0% | **FAIL** — Sharpe 0.800 (−0.07), std 10.14% (worse variance). Confirms anti-pattern (matches Cycle 1b P-1). |
| TP-8b′ | Stricter size-bonus threshold | ICT_FVG_SIZE_BONUS_THRESHOLD 0.003→0.005 | 149 | 45 | 0 | 77.8% | 0 | 77.78% | 0 | 100.0% | **NO-OP** — config_hash matches baseline. Bonus threshold not in hash; signal generation unaffected. |
| TP-8c | Paired tighter gap + bonus | MIN_GAP=0.0015 + SIZE_BONUS=0.005 | 150 | 45 | 0 | 77.8% | 0 | 77.78% | 0 | 100.0% | **NO-OP** — hash matches P-4b (SIZE_BONUS dimension truly inert). Pairing didn't unbind. |

## Cycle 1c CONTINUATION verdict (2026-05-24 03:30 UTC)

**6/6 deferred experiments executed. 0 promotions. 5 NO-OPs + 1 FAIL.**

**Code-state hash:** END = `0318f8ad69badf4deca8804c33c9a44f3a4075cc8bc09415a89a81ae98b60434` ✅ matches START. All reverts clean.

### Confirmed anti-patterns
- **ICT_SWING_N ≥ 3** → −3.9pp WR / −0.07 Sharpe (TP-5c′ replicates Cycle 1b P-1)

### Confirmed inert parameters at current gate set
- `ICT_MSS_HORIZON` (30 vs 15) — both produce identical signals
- `ICT_FVG_MIN_GAP` (0.001 vs 0.0015) — FVG=HIGH gate dominates
- `ICT_EQH_TOLERANCE` (0.0015 vs 0.001) — not in config_hash; bonus inert
- `ICT_FVG_SIZE_BONUS_THRESHOLD` (0.003 vs 0.005) — not in config_hash; bonus inert

### Discovery
The honest cross-config hash mechanism revealed that **5 of the 7 ICT constants tested across Cycle 1c are not part of the config_hash signature** (only ICT_SWING_N and ICT_FVG_MIN_GAP changed the hash). Future hypothesis design should focus on parameters that actually enter the hash — confirmed via `monitoring.py` or by checking the hash changes after the edit.

### Pareto status
**Run-144 (P-2b on F-8) remains the verified Pareto-optimal single-param baseline.**

The cycle reinforces that single-param sweeps on the bound knobs at the current gate configuration are exhausted. Future progress comes from:
1. Paper trading to grow OOS n and shift OGD state
2. New hypothesis classes (Half-Kelly, Coinglass features — Phase B)
3. Re-evaluating after the 365d window has rolled past the 2024 dead-zone (~Q3 2026)
