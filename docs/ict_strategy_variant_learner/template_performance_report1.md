# ICT Strategy Variant Learner — Template Performance Report

**Generated:** 2026-05-20 14:02  
**Strategy Version:** v2  
**Total signals:** 276 (Train: 220, Holdout: 56)  
**Holdout from:** 2026-03-10 19:20:00  

> Grouping: **Best Match Only** — each signal assigned to its highest-tier matching template.

> Phase I-4: MFE/MAE/realized_R now populated from forward-scan excursion tracking.

---

## Quick Summary

| Template | N (all) | Train WR% | Holdout WR% | WF Gap | Avg MFE% | Avg MAE% | Avg realR | Status |
|----------|---------|-----------|-------------|--------|----------|----------|-----------|--------|
| Tier A — Strict | 28 | 43.5% | 40.0% | +3.5% | +1.3533% | +0.7511% | +0.0000R | OK |
| Tier B — Balanced | 248 | 36.0% | 29.4% | +6.6% | +1.2515% | +0.9366% | +0.0000R | OK |
| Tier C — Exploratory (paper-only) | 0 | — | — | — | — | — | — | — |
| No Template Match | 0 | — | — | — | — | — | — | — |

---

## Tier A — Strict

_4/5 required confluences — live trading allowed_

| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |
|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|
| Train (80%) | 23 | 43.5% | 48.0% | -0.0548% | 1.67 | 6.3600% | +1.3533% | +0.7511% | +0.0000R | +0.0000R | Insufficient |
| Holdout (20%) | 5 | 40.0% | 19.8% | -0.6340% | 1.58 | 5.0400% | +1.7741% | +0.4392% | +0.0000R | +0.0000R | Insufficient |

### Warnings

> **WARN:** [TIER_A] n=28 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A] regime concentration: 23/28 (82%) in 'RANGING' - may not generalize

### Dimension Breakdowns (Training Set)

#### Direction

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| SELL | 11 ⚠ | 63.6% | +0.6964% | 8.3 | 1.63 | +1.6930% | +0.6365% | +0.0000R |
| BUY | 12 ⚠ | 25.0% | -0.7433% | 8.1 | 1.71 | +1.0419% | +0.8561% | +0.0000R |

> **WARN:** [TIER_A][Direction=SELL] n=11 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Direction=SELL] session concentration: 8/11 (73%) in 'NY_AM_KZ' - session-dependent edge
> **WARN:** [TIER_A][Direction=BUY] n=12 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Direction=BUY] regime concentration: 11/12 (92%) in 'RANGING' - may not generalize

#### Regime

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| RANGING | 18 ⚠ | 50.0% | +0.1583% | 8.2 | 1.70 | +1.3542% | +0.6212% | +0.0000R |
| TRENDING_BEAR | 4 ⚠ | 25.0% | -0.4950% | 8.0 | 1.57 | +1.4241% | +1.0639% | +0.0000R |
| TRENDING_BULL | 1 ⚠ | 0.0% | -2.1300% | 8.0 | 1.50 | +1.0528% | +1.8368% | +0.0000R |

> **WARN:** [TIER_A][Regime=RANGING] n=18 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Regime=RANGING] regime concentration: 18/18 (100%) in 'RANGING' - may not generalize
> **WARN:** [TIER_A][Regime=TRENDING_BEAR] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Regime=TRENDING_BEAR] regime concentration: 4/4 (100%) in 'TRENDING_BEAR' - may not generalize
> **WARN:** [TIER_A][Regime=TRENDING_BULL] n=1 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Regime=TRENDING_BULL] regime concentration: 1/1 (100%) in 'TRENDING_BULL' - may not generalize
> **WARN:** [TIER_A][Regime=TRENDING_BULL] session concentration: 1/1 (100%) in 'NY_AM_KZ' - session-dependent edge

#### Session

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| NY_AM_KZ | 15 ⚠ | 66.7% | +0.5973% | 8.1 | 1.59 | +1.6715% | +0.5251% | +0.0000R |
| LONDON_KZ | 5 ⚠ | 0.0% | -1.3900% | 8.2 | 1.92 | +1.0188% | +1.1091% | +0.0000R |
| ASIA_KZ | 3 ⚠ | 0.0% | -1.0900% | 8.3 | 1.63 | +0.3197% | +1.2843% | +0.0000R |

> **WARN:** [TIER_A][Session=NY_AM_KZ] n=15 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Session=NY_AM_KZ] regime concentration: 12/15 (80%) in 'RANGING' - may not generalize
> **WARN:** [TIER_A][Session=NY_AM_KZ] session concentration: 15/15 (100%) in 'NY_AM_KZ' - session-dependent edge
> **WARN:** [TIER_A][Session=LONDON_KZ] n=5 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Session=LONDON_KZ] regime concentration: 5/5 (100%) in 'RANGING' - may not generalize
> **WARN:** [TIER_A][Session=LONDON_KZ] session concentration: 5/5 (100%) in 'LONDON_KZ' - session-dependent edge
> **WARN:** [TIER_A][Session=ASIA_KZ] n=3 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Session=ASIA_KZ] session concentration: 3/3 (100%) in 'ASIA_KZ' - session-dependent edge

#### FVG Quality

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| HIGH | 4 ⚠ | 75.0% | +0.9625% | 8.0 | 1.73 | +2.5751% | +0.5202% | +0.0000R |
| MEDIUM | 19 ⚠ | 36.8% | -0.2689% | 8.2 | 1.66 | +1.0961% | +0.7997% | +0.0000R |

> **WARN:** [TIER_A][FVG Quality=HIGH] n=4 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][FVG Quality=HIGH] regime concentration: 3/4 (75%) in 'RANGING' - may not generalize
> **WARN:** [TIER_A][FVG Quality=HIGH] session concentration: 3/4 (75%) in 'NY_AM_KZ' - session-dependent edge
> **WARN:** [TIER_A][FVG Quality=MEDIUM] n=19 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][FVG Quality=MEDIUM] regime concentration: 15/19 (79%) in 'RANGING' - may not generalize

#### MSS Quality

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| HIGH | 23 ⚠ | 43.5% | -0.0548% | 8.2 | 1.67 | +1.3533% | +0.7511% | +0.0000R |

> **WARN:** [TIER_A][MSS Quality=HIGH] n=23 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][MSS Quality=HIGH] regime concentration: 18/23 (78%) in 'RANGING' - may not generalize

#### DR Location

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| PREMIUM | 7 ⚠ | 71.4% | +0.8614% | 8.1 | 1.70 | +1.7084% | +0.4805% | +0.0000R |
| DISCOUNT | 13 ⚠ | 38.5% | -0.3338% | 8.2 | 1.68 | +1.3619% | +0.8495% | +0.0000R |
| EQUILIBRIUM | 3 ⚠ | 0.0% | -0.9833% | 8.3 | 1.57 | +0.4871% | +0.9557% | +0.0000R |

> **WARN:** [TIER_A][DR Location=PREMIUM] n=7 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][DR Location=PREMIUM] regime concentration: 7/7 (100%) in 'RANGING' - may not generalize
> **WARN:** [TIER_A][DR Location=PREMIUM] session concentration: 6/7 (86%) in 'NY_AM_KZ' - session-dependent edge
> **WARN:** [TIER_A][DR Location=DISCOUNT] n=13 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][DR Location=EQUILIBRIUM] n=3 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][DR Location=EQUILIBRIUM] regime concentration: 3/3 (100%) in 'RANGING' - may not generalize

#### Entry Type

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| MIDPOINT_RECLAIM | 10 ⚠ | 60.0% | +0.2900% | 8.2 | 1.71 | +1.6846% | +0.6139% | +0.0000R |
| REACTION_CONFIRMED | 13 ⚠ | 30.8% | -0.3200% | 8.2 | 1.64 | +1.0984% | +0.8566% | +0.0000R |

> **WARN:** [TIER_A][Entry Type=MIDPOINT_RECLAIM] n=10 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_A][Entry Type=MIDPOINT_RECLAIM] regime concentration: 9/10 (90%) in 'RANGING' - may not generalize
> **WARN:** [TIER_A][Entry Type=MIDPOINT_RECLAIM] session concentration: 8/10 (80%) in 'NY_AM_KZ' - session-dependent edge
> **WARN:** [TIER_A][Entry Type=REACTION_CONFIRMED] n=13 - insufficient sample (<30), treat as noise

### Excursion Analysis (MFE / MAE / realized_R by Dimension)

> MFE = max favorable move from entry (before SL/TP1).  
> MAE = max adverse move from entry (before SL/TP1).  
> realR = result in R-multiples (WIN/PARTIAL uses TP1 exit).  

##### Session

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| ASIA_KZ | 3 ⚠ | +0.3197% | +1.2843% | +0.0000R | +0.0000R | 0.0% |
| LONDON_KZ | 5 ⚠ | +1.0188% | +1.1091% | +0.0000R | +0.0000R | 0.0% |
| NY_AM_KZ | 15 ⚠ | +1.6715% | +0.5251% | +0.0000R | +0.0000R | 66.7% |

##### FVG Quality

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| HIGH | 4 ⚠ | +2.5751% | +0.5202% | +0.0000R | +0.0000R | 75.0% |
| MEDIUM | 19 ⚠ | +1.0961% | +0.7997% | +0.0000R | +0.0000R | 36.8% |

##### MSS Quality

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| HIGH | 23 ⚠ | +1.3533% | +0.7511% | +0.0000R | +0.0000R | 43.5% |

---

## Tier B — Balanced

_3/5 required confluences — live trading allowed_

| Set | N | WR% | wWR% | Avg P&L% | Avg RR | Max DD% | Avg MFE% | Avg MAE% | Avg realR | Med realR | Reliability |
|-----|---|-----|------|----------|--------|---------|----------|----------|-----------|-----------|-------------|
| Train (80%) | 197 | 36.0% | 44.7% | -0.3090% | 1.77 | 66.1900% | +1.2515% | +0.9366% | +0.0000R | +0.0000R | Reliable |
| Holdout (20%) | 51 | 29.4% | 31.2% | -0.5808% | 1.71 | 30.5900% | +1.1258% | +0.8744% | +0.0000R | +0.0000R | Reliable |

### Dimension Breakdowns (Training Set)

#### Direction

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| SELL | 111 | 39.6% | -0.1984% | 7.3 | 1.75 | +1.4471% | +0.9073% | +0.0000R |
| BUY | 86 | 31.4% | -0.4517% | 7.3 | 1.79 | +0.9990% | +0.9743% | +0.0000R |

#### Regime

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| TRENDING_BEAR | 59 | 45.8% | +0.1369% | 7.3 | 1.81 | +1.7186% | +0.9294% | +0.0000R |
| TRENDING_BULL | 42 | 40.5% | -0.2890% | 7.3 | 1.74 | +1.2099% | +1.0612% | +0.0000R |
| RANGING | 96 | 28.1% | -0.5918% | 7.3 | 1.76 | +0.9826% | +0.8865% | +0.0000R |

> **WARN:** [TIER_B][Regime=TRENDING_BEAR] regime concentration: 59/59 (100%) in 'TRENDING_BEAR' - may not generalize
> **WARN:** [TIER_B][Regime=TRENDING_BULL] regime concentration: 42/42 (100%) in 'TRENDING_BULL' - may not generalize
> **WARN:** [TIER_B][Regime=RANGING] regime concentration: 96/96 (100%) in 'RANGING' - may not generalize

#### Session

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| LONDON_KZ | 46 | 45.7% | -0.1093% | 7.4 | 1.72 | +1.6335% | +0.9219% | +0.0000R |
| NY_AM_KZ | 63 | 33.3% | -0.3844% | 7.3 | 1.75 | +1.2115% | +0.9345% | +0.0000R |
| ASIA_KZ | 88 | 33.0% | -0.3593% | 7.2 | 1.81 | +1.0804% | +0.9458% | +0.0000R |

> **WARN:** [TIER_B][Session=LONDON_KZ] session concentration: 46/46 (100%) in 'LONDON_KZ' - session-dependent edge
> **WARN:** [TIER_B][Session=NY_AM_KZ] session concentration: 63/63 (100%) in 'NY_AM_KZ' - session-dependent edge
> **WARN:** [TIER_B][Session=ASIA_KZ] session concentration: 88/88 (100%) in 'ASIA_KZ' - session-dependent edge

#### FVG Quality

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| HIGH | 34 | 55.9% | +0.3076% | 7.7 | 1.61 | +1.9966% | +1.1221% | +0.0000R |
| LOW | 83 | 36.1% | -0.4077% | 6.9 | 1.80 | +1.1126% | +0.8194% | +0.0000R |
| MEDIUM | 80 | 27.5% | -0.4686% | 7.5 | 1.80 | +1.0789% | +0.9793% | +0.0000R |

#### MSS Quality

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| HIGH | 174 | 37.4% | -0.2243% | 7.3 | 1.76 | +1.1944% | +0.8909% | +0.0000R |
| MEDIUM | 22 ⚠ | 27.3% | -0.9159% | 7.0 | 1.83 | +1.7554% | +1.2564% | +0.0000R |
| LOW | 1 ⚠ | 0.0% | -1.7000% | 7.0 | 1.80 | +0.1006% | +1.8563% | +0.0000R |

> **WARN:** [TIER_B][MSS Quality=MEDIUM] n=22 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][MSS Quality=LOW] n=1 - insufficient sample (<30), treat as noise
> **WARN:** [TIER_B][MSS Quality=LOW] regime concentration: 1/1 (100%) in 'RANGING' - may not generalize
> **WARN:** [TIER_B][MSS Quality=LOW] session concentration: 1/1 (100%) in 'ASIA_KZ' - session-dependent edge

#### DR Location

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| EQUILIBRIUM | 10 ⚠ | 40.0% | -0.4590% | 7.6 | 1.78 | +1.6037% | +0.9060% | +0.0000R |
| DISCOUNT | 111 | 37.8% | -0.2306% | 7.3 | 1.77 | +1.3881% | +0.9490% | +0.0000R |
| PREMIUM | 76 | 32.9% | -0.4037% | 7.3 | 1.77 | +1.0056% | +0.9224% | +0.0000R |

> **WARN:** [TIER_B][DR Location=EQUILIBRIUM] n=10 - insufficient sample (<30), treat as noise

#### Entry Type

| Value | N | WR% | Avg P&L% | Avg Conf | Avg RR | Avg MFE% | Avg MAE% | Avg realR |
|-------|---|-----|----------|----------|--------|----------|----------|----------|
| REACTION_CONFIRMED | 38 | 36.8% | -0.4237% | 6.9 | 1.66 | +1.2856% | +1.0400% | +0.0000R |
| MIDPOINT_RECLAIM | 159 | 35.8% | -0.2816% | 7.4 | 1.80 | +1.2434% | +0.9119% | +0.0000R |

### Excursion Analysis (MFE / MAE / realized_R by Dimension)

> MFE = max favorable move from entry (before SL/TP1).  
> MAE = max adverse move from entry (before SL/TP1).  
> realR = result in R-multiples (WIN/PARTIAL uses TP1 exit).  

##### Session

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| ASIA_KZ | 88 | +1.0804% | +0.9458% | +0.0000R | +0.0000R | 33.0% |
| LONDON_KZ | 46 | +1.6335% | +0.9219% | +0.0000R | +0.0000R | 45.7% |
| NY_AM_KZ | 63 | +1.2115% | +0.9345% | +0.0000R | +0.0000R | 33.3% |

##### FVG Quality

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| HIGH | 34 | +1.9966% | +1.1221% | +0.0000R | +0.0000R | 55.9% |
| LOW | 83 | +1.1126% | +0.8194% | +0.0000R | +0.0000R | 36.1% |
| MEDIUM | 80 | +1.0789% | +0.9793% | +0.0000R | +0.0000R | 27.5% |

##### MSS Quality

| Value | N | Avg MFE% | Avg MAE% | Avg realR | Med realR | WR% |
|-------|---|----------|----------|-----------|-----------|-----|
| HIGH | 174 | +1.1944% | +0.8909% | +0.0000R | +0.0000R | 37.4% |
| LOW | 1 ⚠ | +0.1006% | +1.8563% | +0.0000R | +0.0000R | 0.0% |
| MEDIUM | 22 ⚠ | +1.7554% | +1.2564% | +0.0000R | +0.0000R | 27.3% |

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

| Template | Train N | Train WR% | Holdout N | Holdout WR% | Avg MFE% | Avg MAE% | Avg realR |
|----------|---------|-----------|-----------|-------------|----------|----------|----------|
| Tier A — Strict | 32 | 43.8% | 5 | 40.0% | +1.3243% | +0.7769% | +0.0000R |
| Tier B — Balanced | 220 | 36.8% | 56 | 30.4% | +1.2621% | +0.9172% | +0.0000R |
| Tier C — Exploratory (paper-only) | 220 | 36.8% | 56 | 30.4% | +1.2621% | +0.9172% | +0.0000R |

---

## Overfitting & Data Quality Warnings

- **WARN:** [TIER_A] n=28 - insufficient sample (<30), treat as noise
- **WARN:** [TIER_A] regime concentration: 23/28 (82%) in 'RANGING' - may not generalize
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
| realized_r | WIN/PARTIAL: net_tp1_pct / sl_pct | Conservative — uses TP1 as exit |
| realized_r | LOSS: net_sl_pct / sl_pct | ~= -1.0 (slightly worse due to fees) |
| realized_r | EXPIRED: 0.0 | No P&L |

