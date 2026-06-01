# ICT Strategy Variant Learner — Template Performance Report

**Generated:** 2026-05-31 16:25  
**Strategy Version:** v2  
**Total signals:** 65 (Train: 29, Holdout: 36)  
**Holdout from:** 2025-11-03  

> Grouping: **Best Match Only** — each signal assigned to its highest-tier matching template.

> Phase I-4: MFE/MAE/realized_R now populated from forward-scan excursion tracking.

> **Expected: Tier C = 0 in Best-Match View.** Every signal produced by this bot satisfies at least 3/5 Tier B confluences, so all Tier C candidates are superseded by Tier B in best-match assignment. Use the All-Matched View to see raw Tier C coverage.

---

## Quick Summary

| Template | N (all) | Train WR% | Holdout WR% | WF Gap | Avg MFE% | Avg MAE% | Avg realR | Status |
|----------|---------|-----------|-------------|--------|----------|----------|-----------|--------|
| Tier A — Strict | 0 | — | — | — | — | — | — | — |
| Tier B — Balanced | 0 | — | — | — | — | — | — | — |
| Tier C — Exploratory (paper-only) | 0 | — | — | — | — | — | — | — |
| No Template Match | 0 | — | — | — | — | — | — | — |

---

## Tier A — Strict

_4/5 required confluences — live trading allowed_

| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |
|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|
| Train (80%) | 0 | — | — | — | — | — | — | — | — | — | — |
| Holdout (20%) | 0 | — | — | — | — | — | — | — | — | — | — |

### Warnings

> **WARN:** [TIER_A] n=0 - insufficient sample (<30), treat as noise

---

## Tier B — Balanced

_3/5 required confluences — live trading allowed_

| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |
|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|
| Train (80%) | 0 | — | — | — | — | — | — | — | — | — | — |
| Holdout (20%) | 0 | — | — | — | — | — | — | — | — | — | — |

### Warnings

> **WARN:** [TIER_B] n=0 - insufficient sample (<30), treat as noise

---

## Tier C — Exploratory (paper-only)

_2/2 required confluences — paper/backtest only_

| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |
|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|
| Train (80%) | 0 | — | — | — | — | — | — | — | — | — | — |
| Holdout (20%) | 0 | — | — | — | — | — | — | — | — | — | — |

### Warnings

> **WARN:** [TIER_C] n=0 - insufficient sample (<30), treat as noise

---

## No Template Match

_Signals that matched no ICT template_

| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |
|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|
| Train (80%) | 0 | — | — | — | — | — | — | — | — | — | — |
| Holdout (20%) | 0 | — | — | — | — | — | — | — | — | — | — |

### Warnings

> **WARN:** [NONE] n=0 - insufficient sample (<30), treat as noise

---

## All-Matched View

> Each signal is counted in **every** template it satisfies (overlapping counts).

> **Note:** If Tier B and Tier C show identical N and metrics, this is expected — every signal that qualifies for Tier C (MSS≥LOW + FVG≥LOW) also qualifies for Tier B (MSS≥MEDIUM + FVG≥LOW + session check), because the bot's entry gates already ensure MSS≥MEDIUM and an active killzone session on every generated signal. This is not a bug; it confirms that Tier C adds no additional coverage beyond Tier B.

| Template | Train N | Train WR% | Holdout N | Holdout WR% | Avg MFE% | Avg MAE% | Avg realR |
|----------|---------|-----------|-----------|-------------|----------|----------|----------|
| Tier A — Strict | 0 | — | 0 | — | — | — | — |
| Tier B — Balanced | 5 | 80.0% | 6 | 100.0% | +3.6452% | +1.3054% | +1.1240R |
| Tier C — Exploratory (paper-only) | 3 | 66.7% | 4 | 100.0% | +1.9177% | +0.6758% | +0.6133R |

---

## Overfitting & Data Quality Warnings

- **WARN:** [TIER_A] n=0 - insufficient sample (<30), treat as noise
- **WARN:** [TIER_B] n=0 - insufficient sample (<30), treat as noise
- **WARN:** [TIER_C] n=0 - insufficient sample (<30), treat as noise
- **WARN:** [NONE] n=0 - insufficient sample (<30), treat as noise

_Sample size thresholds: n < 30 = insufficient | n >= 50 = reliable_  
_Concentration threshold: >= 70% of signals in one regime or session_

---

## Phase I-4 Excursion Tracking Notes

| Field | Formula | Notes |
|-------|---------|-------|
| mfe_pct | BUY: (max_high - entry) / entry * 100 | Stops at SL or TP1 hit |
| mfe_pct | SELL: (entry - min_low) / entry * 100 | Stops at SL or TP1 hit |
| mae_pct | BUY: (entry - min_low) / entry * 100 | Stops at SL or TP1 hit |
| mae_pct | SELL: (max_high - entry) / entry * 100 | Stops at SL or TP1 hit |
| realized_r | WIN/PARTIAL: net_tp1_pct / abs(sl_pct) | Conservative — uses TP1 as exit |
| realized_r | LOSS: net_sl_pct / abs(sl_pct) | ~= -1.0 (slightly worse due to fees) |
| realized_r | EXPIRED: 0.0 | No P&L |

> **Note on sl_pct sign:** `compute_ict_trade_plan()` stores `sl_pct` as a **negative** value (e.g. `-0.85` for a 0.85% SL distance). Always use `abs(sl_pct)` as the denominator in R-multiple calculations.

> **Note on Median realR = 0.0:** A median realized_R of exactly 0.0 does **not** mean the strategy breaks even. It typically means EXPIRED trades (realR = 0.0 by definition) occupy the median position in the sorted distribution. Check `expired` count in the stats table to confirm. If expired > 25% of N, the median is driven by time-out exits, not true breakeven results.

---

## Phase 5A — Template Safety Layer Simulation

> **Informational only.** This section simulates how many backtest signals would be blocked by each Phase 5A safety rule. It does **not** enforce any live gate. Rules requiring live DB state (sample gate, circuit breaker) are noted as requiring live data.

**Active configuration:**  
- `EXECUTION_MODE` = `PAPER` (set in crypto_alert.py)
- `TEMPLATE_MIN_SAMPLE` = 50 closed trades  
- `CIRCUIT_BREAKER_LOOKBACK` = 20 trades, min WR = 55%  
- `BLOCK_RANGING_LIVE` = True, templates = ['CRT_B_FVG_RELAXED', 'CRT_B_OB_HIGH_MSS', 'NONE', 'TIER_B']  
- `TIER_DAILY_LIVE_CAPS` = {'TIER_A': 3, 'TIER_B': 2, 'TIER_C': 0, 'NONE': 1, 'CRT_A_FVG_ALIGNED': 3, 'CRT_B_OB_HIGH_MSS': 2, 'CRT_B_FVG_RELAXED': 2, 'CRT_C_OB_DEFAULT': 0}

| Safety Rule | Trigger Condition | Signals Blocked | % of All |
|------------|-------------------|-----------------|----------|
| PAPER_ONLY — Tier C | `matched_template_id == TIER_C` | 0 | 0.0% |
| PAPER_ONLY — cap=0 | Tier ['TIER_C', 'CRT_C_OB_DEFAULT'] daily cap = 0 | 7 | 10.8% |
| BLOCKED_BY_REGIME_SAFETY | RANGING + template in ['CRT_B_FVG_RELAXED', 'CRT_B_OB_HIGH_MSS', 'NONE', 'TIER_B'] | 30 | 46.2% |
| INSUFFICIENT_SAMPLE | < 50 closed trades per template | **requires live DB** | — |
| PAUSED_BY_CIRCUIT_BREAKER | Rolling 20-trade WR < 55% | **requires live DB** | — |
| DAILY_CAP_REACHED | Daily live count ≥ cap per tier | **requires live DB** | — |

**Subtotal (simulatable rules):** 37 / 65 signals (56.9%) would be blocked before reaching live execution.

### Regime Safety — RANGING Breakdown by Template

| Template | RANGING Signals | RANGING WR% | Would Block? |
|----------|-----------------|-------------|-------------|

_Phase 5A constants defined in `crypto_alert.py`. Set `EXECUTION_MODE = "LIVE"` to activate live blocking.

