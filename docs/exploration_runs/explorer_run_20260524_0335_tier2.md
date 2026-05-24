# Backtest Explorer — Tier 2 Paired Grids Started 2026-05-24 03:35 UTC

**Continues from:** Cycle 1c continuation (`explorer_run_20260523_2155_cont.md`) — all 6 single-param probes either NO-OP or FAIL. Run-144 confirmed Pareto-optimal under single-param search.

**Goal:** Execute Tier 2 paired-parameter grids from `backtest-optimizer.md`. Priority: TP-1 (FVG × MSS quality), then TP-2 (4H bias × 1H trend) if TP-1 surfaces a candidate.

**Approach:** Use env-var overrides instead of file edits — config.py reads `BACKTEST_*` via `_env_choice()`/`_env_bool()`. This means zero code-state changes during the cycle; no revert risk.

**Baseline snapshot (Run 144):** `data/snapshots/signals_baseline_run144_20260523_2152_p2b_honest_dsr.db`

```
n=45 | WR=77.8% | CPCV WR mean=77.78% (std=7.86%) | Sharpe 0.870
PSR (OOS)=100% | DSR=100% [n_trials=16, sr_trial_std=0.0777 HONEST]
Active gates: FVG=HIGH × MSS=LOW × bias=none × trend=loose × DR=False × SMT=False
```

**ACCEPT thresholds** (per backtest-optimizer.md §Phase 3 Step 7):
1. `n ≥ 30` (365d window)
2. `cpcv_wr_mean ≥ 60%`
3. `cpcv_wr_q05 ≥ 50%`
4. monitoring.py exit 0
5. `delta_dsr ≥ -0.05`

## TP-1 — FVG × MSS quality grid (9 cells, 8 new)

| Cell | FVG | MSS | Run | n | WR | CPCV mean | CPCV std | Sharpe | DSR | Verdict |
|------|-----|-----|-----|---|-----|-----------|----------|--------|-----|---------|
| baseline | HIGH | LOW | 144 | 45 | 77.8% | 77.78% | 7.86% | 0.870 | 100% | Reference |
| TP-1-a | LOW | LOW | 151 | 264 | 42.0% | 42.04% | 3.29% | 0.020 | 2.0% | **FAIL** — both gates open = noise. |
| TP-1-b | LOW | MEDIUM | 152 | 263 | 42.2% | 42.19% | 3.74% | 0.023 | 2.2% | **FAIL** — FVG=LOW fatal. |
| TP-1-c | LOW | HIGH | 153 | 235 | 42.1% | 42.13% | 3.52% | — | 1.7% | **FAIL** — FVG=LOW fatal even with strict MSS. |
| TP-1-d | MEDIUM | LOW | 154 | 174 | 44.3% | 44.25% | 4.46% | 0.090 | 22.2% | **FAIL** — better than LOW but still coin-flip. |
| TP-1-e | MEDIUM | MEDIUM | 155 | 173 | 44.5% | 44.49% | 4.16% | 0.093 | 23.5% | **FAIL** |
| TP-1-f | MEDIUM | HIGH | 156 | 157 | 44.6% | 44.61% | 5.53% | 0.095 | 25.6% | **FAIL** |
| TP-1-g | HIGH | MEDIUM | 157 | 45 | 77.8% | 77.78% | 7.86% | 0.870 | 100% | **TIE-NO-OP** — bit-identical to baseline. MSS gate at MEDIUM rejects 0 signals that FVG=HIGH already passes. |
| TP-1-h | HIGH | HIGH | 158 | 44 | 77.3% | 77.25% | 8.04% | 0.855 | 100% | **NEAR-TIE** — n−1, WR −0.5pp. Pareto-equivalent but slightly worse on every dim. |

### TP-1 verdict (8/8 cells executed)
- **0 promotions / 6 FAILs / 1 TIE-NO-OP / 1 NEAR-TIE.**
- **FVG=HIGH is the binding gate**; everything below it is noise.
- **MSS_MIN_QUALITY is structurally inert at FVG=HIGH** — confirmed by TP-1-g bit-identity.
- Baseline (HIGH × LOW) remains Pareto-optimal.

## TP-2 — 4H bias × 1H trend grid (9 cells, 8 new)

| Cell | 4H | 1H | Run | n | WR | CPCV mean | CPCV std | Sharpe | DSR | Verdict |
|------|----|----|-----|---|-----|-----------|----------|--------|-----|---------|
| baseline | none | loose | 144 | 45 | 77.8% | 77.78% | 7.86% | 0.870 | 100% | Reference |
| TP-2-a | none | none | 159 | 49 | 71.4% | 71.32% | 8.11% | 0.673 | 100% | **REGRESS** — loosening 1H adds 4 signals at WR −6.4pp. |
| TP-2-b | none | strict | 160 | **43** | **79.1%** | **79.11%** | **5.40%** | **0.933** | **100%** | **PROMOTE** ✨ Pareto improvement on every dim except n (−2). |
| TP-2-c | loose | none | 161 | 49 | 71.4% | 71.32% | 8.11% | 0.673 | 100% | = TP-2-a (4H=loose bit-identical to 4H=none). |
| TP-2-d | loose | loose | 162 | 45 | 77.8% | 77.78% | 7.86% | 0.870 | 100% | = baseline. |
| TP-2-e | loose | strict | 163 | 43 | 79.1% | 79.11% | 5.40% | 0.933 | 100% | = TP-2-b. Confirms 4H gate at loose ≡ none. |
| TP-2-f | strict | none | 164 | 37 | 75.7% | 75.83% | 15.56% | 0.919 | 100% | D-2 fingerprint: high variance, fewer signals. REJECT (consistent with F-8 reversal). |
| TP-2-g | strict | loose | 165 | 37 | 75.7% | 75.83% | 15.56% | 0.919 | 100% | = TP-2-f. |
| TP-2-h | strict | strict | 166 | 37 | 75.7% | 75.83% | 15.56% | 0.919 | 100% | = TP-2-f. 4H=strict dominates and produces the high-variance Run-127 fingerprint. |

### TP-2 verdict (8/8 cells executed) — **1 PROMOTION**

**TP-2-b PROMOTED → Run-168 baseline (honest DSR refreshed):**
- Applied: `LIVE_TREND_1H_GATE` loose→strict at `config.py:314`
- Applied: `BACKTEST_TREND_1H_GATE` loose→strict at `config.py:324` (parity)
- Snapshot: `data/snapshots/signals_baseline_run168_20260524_0826_tp2b_promoted_honest.db` (14.9 MB)
- Cross-config std refreshed: 0.0777 → 0.0836 (n_configs 13 → 24)
- Run-168 OOS Sharpe 0.9327 is the new pool maximum

**Structural insights:**
1. **4H bias gate at "loose" is bit-identical to "none"** across all 1H levels — the gate filter never binds at current data.
2. **4H=strict consistently produces the D-2 fingerprint** (n=37, std=15.6%) — already documented as anti-pattern.
3. **Best Pareto corner: 4H=none × 1H=strict** — tighter 1H trend filter raises WR and *lowers* CPCV variance simultaneously.


