# ICT Strategy Variant Learner — Template Performance Report

**Generated:** 2026-05-24 21:07  
**Strategy Version:** v2  
**Total signals:** 46 (Train: 24, Holdout: 22)  
**Holdout from:** 2025-11-03  

> Grouping: **Best Match Only** — each signal assigned to its highest-tier matching template.

> Phase I-4: MFE/MAE/realized_R now populated from forward-scan excursion tracking.

> **Expected: Tier C = 0 in Best-Match View.** Every signal produced by this bot satisfies at least 3/5 Tier B confluences, so all Tier C candidates are superseded by Tier B in best-match assignment. Use the All-Matched View to see raw Tier C coverage.

---

## Quick Summary

| Template | N (all) | Train WR% | Holdout WR% | WF Gap | Avg MFE% | Avg MAE% | Avg realR | Status |
|----------|---------|-----------|-------------|--------|----------|----------|-----------|--------|
| Tier A — Strict | 19 | 66.7% | 71.4% | -4.7% | +3.8370% | +0.7416% | +0.9770R | OK |
| Tier B — Balanced | 27 | 75.0% | 86.7% | -11.7% | +2.1464% | +0.6139% | +0.9678R | OK |
| Tier C — Exploratory (paper-only) | 0 | — | — | — | — | — | — | — |
| No Template Match | 0 | — | — | — | — | — | — | — |

---

## Tier A — Strict

_4/5 required confluences — live trading allowed_

| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |
|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|
| Train (80%) | 12 | 66.7% | 70.8% | +1.6225% | 1.73 | 3.9900% | +3.8370% | +0.7416% | +0.9770R | +1.9871R | Insufficient |
| Holdout (20%) | 7 | 71.4% | 73.9% | +1.4550% | 1.83 | 2.2200% | +2.2194% | +1.1967% | +0.5818R | +0.9226R | Insufficient |

### Warnings

> **WARN:** [TIER_A] n=19 - insufficient sample (<30), treat as noise

### Dimension Breakdowns (Training Set)

#### Direction

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| SELL | 4 ⚠ | 100.0% | +3.1800% | 8.5 | 1.50 | +7.5975% | +0.1963% | +2.0164R |
| BUY | 8 ⚠ | 50.0% | +0.8438% | 8.6 | 1.85 | +1.9568% | +1.0143% | +0.4573R |

> **WARN:** [TIER_A][Direction=SELL] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Direction=SELL] regime concentration: 4/4 (100%) in 'TRENDING_BEAR' - may not generalize
> **WARN:** [TIER_A][Direction=BUY] n=8 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Direction=BUY] regime concentration: 8/8 (100%) in 'TRENDING_BULL' - may not generalize

#### Regime

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| TRENDING_BEAR | 4 ⚠ | 100.0% | +3.1800% | 8.5 | 1.50 | +7.5975% | +0.1963% | +2.0164R |
| TRENDING_BULL | 8 ⚠ | 50.0% | +0.8438% | 8.6 | 1.85 | +1.9568% | +1.0143% | +0.4573R |

> **WARN:** [TIER_A][Regime=TRENDING_BEAR] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Regime=TRENDING_BULL] n=8 - insufficient sample (<30), treat as noise

#### Session

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| LONDON_KZ | 4 ⚠ | 100.0% | +3.7063% | 8.5 | 1.68 | +8.2348% | +0.3422% | +2.1446R |
| ASIA_KZ | 1 ⚠ | 100.0% | +1.8450% | 9.0 | 1.50 | +1.4701% | +0.2393% | +1.9421R |
| OVERNIGHT | 3 ⚠ | 66.7% | +1.1750% | 8.0 | 1.77 | +2.3194% | +0.7958% | +1.0085R |
| NY_AM_KZ | 4 ⚠ | 25.0% | -0.1812% | 9.0 | 1.82 | +1.1691% | +1.2260% | -0.4556R |

> **WARN:** [TIER_A][Session=LONDON_KZ] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Session=ASIA_KZ] n=1 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Session=ASIA_KZ] regime concentration: 1/1 (100%) in 'TRENDING_BEAR' - may not generalize
> **WARN:** [TIER_A][Session=OVERNIGHT] n=3 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Session=NY_AM_KZ] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Session=NY_AM_KZ] regime concentration: 4/4 (100%) in 'TRENDING_BULL' - may not generalize

#### FVG Quality

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| HIGH | 12 ⚠ | 66.7% | +1.6225% | 8.6 | 1.73 | +3.8370% | +0.7416% | +0.9770R |

> **WARN:** [TIER_A][FVG Quality=HIGH] n=12 - insufficient sample (<30), treat as noise

#### MSS Quality

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| HIGH | 12 ⚠ | 66.7% | +1.6225% | 8.6 | 1.73 | +3.8370% | +0.7416% | +0.9770R |

> **WARN:** [TIER_A][MSS Quality=HIGH] n=12 - insufficient sample (<30), treat as noise

#### DR Location

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| DISCOUNT | 4 ⚠ | 100.0% | +3.1800% | 8.5 | 1.50 | +7.5975% | +0.1963% | +2.0164R |
| PREMIUM | 8 ⚠ | 50.0% | +0.8438% | 8.6 | 1.85 | +1.9568% | +1.0143% | +0.4573R |

> **WARN:** [TIER_A][DR Location=DISCOUNT] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][DR Location=DISCOUNT] regime concentration: 4/4 (100%) in 'TRENDING_BEAR' - may not generalize
> **WARN:** [TIER_A][DR Location=PREMIUM] n=8 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][DR Location=PREMIUM] regime concentration: 8/8 (100%) in 'TRENDING_BULL' - may not generalize

#### Entry Type

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| REACTION_CONFIRMED | 4 ⚠ | 75.0% | +1.3425% | 8.2 | 1.70 | +2.1071% | +0.6567% | +1.2419R |
| MIDPOINT_RECLAIM | 8 ⚠ | 62.5% | +1.7625% | 8.8 | 1.75 | +4.7020% | +0.7841% | +0.8445R |

> **WARN:** [TIER_A][Entry Type=REACTION_CONFIRMED] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Entry Type=REACTION_CONFIRMED] session concentration: 3/4 (75%) in 'OVERNIGHT' - session-dependent edge
> **WARN:** [TIER_A][Entry Type=MIDPOINT_RECLAIM] n=8 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Entry Type=MIDPOINT_RECLAIM] regime concentration: 6/8 (75%) in 'TRENDING_BULL' - may not generalize

### Excursion Analysis (MFE / MAE / realized_R by Dimension)

> MFE = max favorable move from entry (before SL/TP1).  
> MAE = max adverse move from entry (before SL/TP1).  
> realR = result in R-multiples (WIN/PARTIAL uses TP1 exit).  

##### Session

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| ASIA_KZ | 1 ⚠ | +1.4701% | +0.2393% | +1.9421R | +1.9421R | 100.0% |
| LONDON_KZ | 4 ⚠ | +8.2348% | +0.3422% | +2.1446R | +2.1117R | 100.0% |
| NY_AM_KZ | 4 ⚠ | +1.1691% | +1.2260% | -0.4556R | -1.2679R | 25.0% |
| OVERNIGHT | 3 ⚠ | +2.3194% | +0.7958% | +1.0085R | +1.9000R | 66.7% |

##### FVG Quality

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| HIGH | 12 ⚠ | +3.8370% | +0.7416% | +0.9770R | +1.9871R | 66.7% |

##### MSS Quality

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| HIGH | 12 ⚠ | +3.8370% | +0.7416% | +0.9770R | +1.9871R | 66.7% |

---

## Tier B — Balanced

_3/5 required confluences — live trading allowed_

| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |
|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|
| Train (80%) | 12 | 75.0% | 75.8% | +1.3396% | 1.59 | 1.9400% | +2.1464% | +0.6139% | +0.9678R | +1.9078R | Insufficient |
| Holdout (20%) | 15 | 86.7% | 90.7% | +2.4507% | 1.73 | 1.3400% | +3.3116% | +0.8834% | +1.2346R | +1.4589R | Insufficient |

### Warnings

> **WARN:** [TIER_B] n=27 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B] session concentration: 20/27 (74%) in 'OVERNIGHT' - session-dependent edge

### Dimension Breakdowns (Training Set)

#### Direction

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| SELL | 8 ⚠ | 75.0% | +1.4575% | 7.4 | 1.64 | +2.2684% | +0.5341% | +1.0449R |
| BUY | 4 ⚠ | 75.0% | +1.1038% | 8.0 | 1.50 | +1.9023% | +0.7737% | +0.8135R |

> **WARN:** [TIER_B][Direction=SELL] n=8 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][Direction=SELL] regime concentration: 8/8 (100%) in 'TRENDING_BEAR' - may not generalize
> **WARN:** [TIER_B][Direction=SELL] session concentration: 8/8 (100%) in 'OVERNIGHT' - session-dependent edge
> **WARN:** [TIER_B][Direction=BUY] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][Direction=BUY] regime concentration: 4/4 (100%) in 'TRENDING_BULL' - may not generalize
> **WARN:** [TIER_B][Direction=BUY] session concentration: 3/4 (75%) in 'OVERNIGHT' - session-dependent edge

#### Regime

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| TRENDING_BEAR | 8 ⚠ | 75.0% | +1.4575% | 7.4 | 1.64 | +2.2684% | +0.5341% | +1.0449R |
| TRENDING_BULL | 4 ⚠ | 75.0% | +1.1038% | 8.0 | 1.50 | +1.9023% | +0.7737% | +0.8135R |

> **WARN:** [TIER_B][Regime=TRENDING_BEAR] n=8 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][Regime=TRENDING_BEAR] session concentration: 8/8 (100%) in 'OVERNIGHT' - session-dependent edge
> **WARN:** [TIER_B][Regime=TRENDING_BULL] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][Regime=TRENDING_BULL] session concentration: 3/4 (75%) in 'OVERNIGHT' - session-dependent edge

#### Session

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| LONDON_KZ | 1 ⚠ | 100.0% | +0.9850% | 10.0 | 1.50 | +2.2910% | +1.4257% | +0.6523R |
| OVERNIGHT | 11 ⚠ | 72.7% | +1.3718% | 7.4 | 1.60 | +2.1333% | +0.5402% | +0.9964R |

> **WARN:** [TIER_B][Session=LONDON_KZ] n=1 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][Session=LONDON_KZ] regime concentration: 1/1 (100%) in 'TRENDING_BULL' - may not generalize
> **WARN:** [TIER_B][Session=OVERNIGHT] n=11 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][Session=OVERNIGHT] regime concentration: 8/11 (73%) in 'TRENDING_BEAR' - may not generalize

#### FVG Quality

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| HIGH | 12 ⚠ | 75.0% | +1.3396% | 7.6 | 1.59 | +2.1464% | +0.6139% | +0.9678R |

> **WARN:** [TIER_B][FVG Quality=HIGH] n=12 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][FVG Quality=HIGH] session concentration: 11/12 (92%) in 'OVERNIGHT' - session-dependent edge

#### MSS Quality

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| HIGH | 12 ⚠ | 75.0% | +1.3396% | 7.6 | 1.59 | +2.1464% | +0.6139% | +0.9678R |

> **WARN:** [TIER_B][MSS Quality=HIGH] n=12 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][MSS Quality=HIGH] session concentration: 11/12 (92%) in 'OVERNIGHT' - session-dependent edge

#### DR Location

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| UNKNOWN | 1 ⚠ | 100.0% | +0.9850% | 10.0 | 1.50 | +2.2910% | +1.4257% | +0.6523R |
| DISCOUNT | 8 ⚠ | 75.0% | +1.4575% | 7.4 | 1.64 | +2.2684% | +0.5341% | +1.0449R |
| PREMIUM | 3 ⚠ | 66.7% | +1.1433% | 7.3 | 1.50 | +1.7728% | +0.5564% | +0.8672R |

> **WARN:** [TIER_B][DR Location=UNKNOWN] n=1 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][DR Location=UNKNOWN] regime concentration: 1/1 (100%) in 'TRENDING_BULL' - may not generalize
> **WARN:** [TIER_B][DR Location=UNKNOWN] session concentration: 1/1 (100%) in 'LONDON_KZ' - session-dependent edge
> **WARN:** [TIER_B][DR Location=DISCOUNT] n=8 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][DR Location=DISCOUNT] regime concentration: 8/8 (100%) in 'TRENDING_BEAR' - may not generalize
> **WARN:** [TIER_B][DR Location=DISCOUNT] session concentration: 8/8 (100%) in 'OVERNIGHT' - session-dependent edge
> **WARN:** [TIER_B][DR Location=PREMIUM] n=3 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][DR Location=PREMIUM] regime concentration: 3/3 (100%) in 'TRENDING_BULL' - may not generalize
> **WARN:** [TIER_B][DR Location=PREMIUM] session concentration: 3/3 (100%) in 'OVERNIGHT' - session-dependent edge

#### Entry Type

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| MIDPOINT_RECLAIM | 12 ⚠ | 75.0% | +1.3396% | 7.6 | 1.59 | +2.1464% | +0.6139% | +0.9678R |

> **WARN:** [TIER_B][Entry Type=MIDPOINT_RECLAIM] n=12 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][Entry Type=MIDPOINT_RECLAIM] session concentration: 11/12 (92%) in 'OVERNIGHT' - session-dependent edge

### Excursion Analysis (MFE / MAE / realized_R by Dimension)

> MFE = max favorable move from entry (before SL/TP1).  
> MAE = max adverse move from entry (before SL/TP1).  
> realR = result in R-multiples (WIN/PARTIAL uses TP1 exit).  

##### Session

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| LONDON_KZ | 1 ⚠ | +2.2910% | +1.4257% | +0.6523R | +0.6523R | 100.0% |
| OVERNIGHT | 11 ⚠ | +2.1333% | +0.5402% | +0.9964R | +1.9360R | 72.7% |

##### FVG Quality

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| HIGH | 12 ⚠ | +2.1464% | +0.6139% | +0.9678R | +1.9078R | 75.0% |

##### MSS Quality

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| HIGH | 12 ⚠ | +2.1464% | +0.6139% | +0.9678R | +1.9078R | 75.0% |

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
| Tier A — Strict | 12 | 66.7% | 7 | 71.4% | +3.8370% | +0.7416% | +0.9770R |
| Tier B — Balanced | 24 | 70.8% | 22 | 81.8% | +2.9917% | +0.6778% | +0.9724R |
| Tier C — Exploratory (paper-only) | 24 | 70.8% | 22 | 81.8% | +2.9917% | +0.6778% | +0.9724R |

---

## Overfitting & Data Quality Warnings

- **WARN:** [TIER_A] n=19 - insufficient sample (<30), treat as noise
- **WARN:** [TIER_B] n=27 - insufficient sample (<30), treat as noise
- **WARN:** [TIER_B] session concentration: 20/27 (74%) in 'OVERNIGHT' - session-dependent edge
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
- `BLOCK_RANGING_LIVE` = True, templates = ['NONE', 'TIER_B']  
- `TIER_DAILY_LIVE_CAPS` = {'TIER_A': 3, 'TIER_B': 2, 'TIER_C': 0, 'NONE': 1}

| Safety Rule | Trigger Condition | Signals Blocked | % of All |
|------------|-------------------|-----------------|----------|
| PAPER_ONLY — Tier C | `matched_template_id == TIER_C` | 0 | 0.0% |
| PAPER_ONLY — cap=0 | Tier ['TIER_C'] daily cap = 0 | 0 | 0.0% |
| BLOCKED_BY_REGIME_SAFETY | RANGING + template in ['NONE', 'TIER_B'] | 0 | 0.0% |
| INSUFFICIENT_SAMPLE | < 50 closed trades per template | **requires live DB** | — |
| PAUSED_BY_CIRCUIT_BREAKER | Rolling 20-trade WR < 55% | **requires live DB** | — |
| DAILY_CAP_REACHED | Daily live count ≥ cap per tier | **requires live DB** | — |

**Subtotal (simulatable rules):** 0 / 46 signals (0.0%) would be blocked before reaching live execution.

### Regime Safety — RANGING Breakdown by Template

| Template | RANGING Signals | RANGING WR% | Would Block? |
|----------|-----------------|-------------|-------------|

_Phase 5A constants defined in `crypto_alert.py`. Set `EXECUTION_MODE = "LIVE"` to activate live blocking.

