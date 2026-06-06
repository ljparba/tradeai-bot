# Phase C-Breakout — Timeframe Comparison Report

**Mode:** Backtest comparison only. Read-only on production. No soak changes.
**Date:** 2026-06-02
**Branch:** `breakout-thesis @ 70852df` (uncommitted output files)
**Pre-registration:** `TF_COMPARISON_PRE_REGISTER.md` — written BEFORE any backtest run.

> **Headline finding:**
> **All three timeframe configurations show statistically significant edge that
> survives CPCV + DSR deflation.** They differ materially in their trade-off
> between per-signal quality and total throughput:
>
> - **A (5M / 4H)** — highest per-trade quality (avg_R +0.76, PF 3.71), lowest
>   signal count (410). Modest absolute total expectancy (+311 R).
> - **B (5M / 1H)** — **highest total expectancy by a wide margin** (+750 R
>   sum_R clean, +607 R friction-on). 2.8× more signals than A. Lower per-trade
>   avg_R (+0.66) but the breadth compensates.
> - **C (1M / 1H)** — middle ground (625 signals, +397 R). avg_R between A and
>   B but the OOS train→test edge slightly degrades (+0.65 → +0.60). Less
>   robust forward momentum than A or B in walk-forward.
>
> **POL is a chronic blowup in all three configs.** No timeframe rescues it.
>
> **No recommendation made on switching the live soak.** Any timeframe switch
> would require its own fresh forward soak from zero — same discipline that
> applied to the breakout thesis itself in Step 2.

---

## 0. Pre-registered locked parameters (recap)

| Constant | Value |
|---|---|
| `H4_BREAKOUT_CLOSE_BUFFER_PCT` | 0.001 |
| `BREAKOUT_TP1_RR / TP2_RR / TP3_RR` | 2.0 / 3.0 / 4.0 |
| `H4_BREAKOUT_C2_LOOKBACK` (bars) | 4 |
| `H4_BREAKOUT_MSS_HORIZON` (bars) | 30 |
| `H4_BREAKOUT_OB_SCAN_LOOKBACK` | 20 |
| `H4_BREAKOUT_FVG_PROBE_WIDTH` | 3 |
| `BREAKOUT_SL_INSIDE_BUFFER_PCT` | 0.001 |
| `MIN_SL_PCT / MAX_SL_PCT` | 0.005 / 0.030 |
| `MAX_BREAKEVEN_WR` | 0.60 |
| `ICT_MIN_RR_GATE` | 1.3 |
| Forward outcome window | 48 hours wall-clock |
| Universe | 12 tokens (matches soak) |
| Data span | **90 days, 2026-03-02 → 2026-05-31 UTC** (same window for all 3) |

### TF-scaling rule (LOCKED)

I held `H4_BREAKOUT_C2_LOOKBACK` and `H4_BREAKOUT_MSS_HORIZON` at the SAME bar
count for all three configs. This means the wall-clock windows differ per TF:

| Config | C2 lookback wall-clock | MSS horizon wall-clock |
|---|---|---|
| A (5M/4H) | 16 hours | 150 minutes |
| B (5M/1H) | 4 hours | 150 minutes |
| C (1M/1H) | 4 hours | **30 minutes** |

This is the honest choice (the engine's structural intent is in bars, not
clocks), but it means C examines a much tighter post-sweep window than A/B.

---

## 1. Headline side-by-side table

### Clean (frictionless)

| Cfg | n | WR | **avg_R** | sum_R | **PF** | max_DD R | per-trade Sharpe | PSR | **DSR** | CPCV verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **A 5M/4H** | 410 | 69.3 % | **+0.759** | +311.0 | **3.71** | 14.1 | +0.68 | 1.00 | 1.00 | PASS |
| **B 5M/1H** | 1132 | 61.8 % | +0.662 | **+749.9** | 3.19 | 11.8 | +0.58 | 1.00 | 1.00 | PASS |
| **C 1M/1H** | 625 | 64.2 % | +0.635 | +397.2 | 3.09 | 8.0 | +0.57 | 1.00 | 1.00 | PASS |

### Friction-on (execution.simulate_execution defaults, same as Step 2A)

| Cfg | n filled | drop | WR | **avg_R** | sum_R | PF | max_DD R | Friction degradation on avg_R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **A 5M/4H** | 398 | 12 (-2.9%) | 69.1% | **+0.616** | +245.3 | 3.23 | 13.3 | **-18.8%** |
| **B 5M/1H** | 1106 | 26 (-2.3%) | 61.8% | +0.549 | **+607.3** | 2.87 | 10.4 | -17.0% |
| **C 1M/1H** | 606 | 19 (-3.0%) | 64.4% | +0.532 | +322.7 | 2.81 | 8.0 | -16.2% |

**Friction-sensitivity ranking** (least → most R lost to friction): **C < B < A**.

This was a surprise to me — I had expected 1M to lose more to friction, not less.
Reading the per-signal records: the BEW economics gate (`MAX_BREAKEVEN_WR=0.60`)
filters out the tightest-stop setups regardless of TF. On 1M, the setups that
SURVIVE the gate happen to be the wider-stop ones (because TP1 is fixed at 2R
of structural distance, the surviving 1M setups need larger structural distances
to hit BEW < 0.60), so their gross % returns are proportionally larger and the
fixed-fee spread eats a smaller fraction. The 1M signals that DID pass the gate
look — economically speaking — much like the 5M signals.

`cross-config Sharpe std (CLEAN only) = 0.0467` (used for DSR deflation with
`n_trials = 3`).

---

## 2. Train → Test 70/30 temporal split (OOS robustness)

| Cfg | train avg_R | test avg_R | OOS delta | Reading |
|---|---:|---:|---:|---|
| **A 5M/4H** clean | +0.64 | **+1.03** | **+0.39 OOS** | Edge STRENGTHENS in held-out 30%. Strongest forward momentum signature. |
| A 5M/4H friction | +0.54 | +0.80 | +0.26 | Same direction, friction-attenuated. |
| **B 5M/1H** clean | +0.62 | +0.76 | +0.14 OOS | Edge STRENGTHENS. Solid. |
| B 5M/1H friction | +0.50 | +0.66 | +0.16 | Same direction. |
| **C 1M/1H** clean | +0.65 | +0.60 | **-0.05** | Edge slightly DEGRADES OOS. Worst of the three. |
| C 1M/1H friction | +0.54 | +0.51 | -0.03 | Same direction. |

**A and B both show forward-OOS edge strengthening — a strong signature of
genuine signal. C is essentially flat-to-slightly-down OOS, which is consistent
with sample noise but also with mild overfitting to the in-sample window.**

---

## 3. Walk-forward by calendar month (90 days = 3 months max)

### A 5M/4H clean

| Month | n | WR | avg_R | sum_R | PF |
|---|---:|---:|---:|---:|---:|
| 2026-03 | 141 | 58.9% | +0.52 | +73 | 2.38 |
| 2026-04 | 138 | 70.3% | +0.80 | +110 | 4.05 |
| 2026-05 | 131 | **79.4%** | **+0.98** | +128 | **5.92** |

A is **strengthening month-over-month**. May (the most recent slice) has the
best WR, avg_R, and PF — a forward-momentum signature.

### B 5M/1H clean

| Month | n | WR | avg_R | sum_R | PF |
|---|---:|---:|---:|---:|---:|
| 2026-03 | 396 | 60.1% | +0.64 | +252 | 3.02 |
| 2026-04 | 351 | 61.3% | +0.66 | +232 | 3.25 |
| 2026-05 | 385 | 63.9% | +0.69 | +265 | 3.31 |

B is **stable with gentle improvement**. Every metric ticks slightly up each
month. No single-month outliers.

### C 1M/1H clean

| Month | n | WR | avg_R | sum_R | PF |
|---|---:|---:|---:|---:|---:|
| 2026-03 | 245 | 62.9% | +0.62 | +153 | 3.02 |
| 2026-04 | 179 | 65.9% | +0.70 | +126 | 3.62 |
| 2026-05 | 201 | 64.2% | +0.59 | +118 | **2.79** |

C shows a **dip in May** — both avg_R and PF retreat from April's peak. May
remains profitable but is the weakest of C's three months. Combined with the
slight OOS train→test degradation (§2), this points to C being more sensitive
to short-term regime shifts than A or B.

---

## 4. Per-token expectancy — clean configs

### Tokens shared across all three configs

| Token | A: n / WR / avg_R / sum_R | B: n / WR / avg_R / sum_R | C: n / WR / avg_R / sum_R |
|---|---|---|---|
| BTC | 34 / 70.6% / +0.82 / +27.7 | 106 / 57.6% / +0.54 / +57.4 | 50 / 64.0% / +0.65 / +32.6 |
| ETH | 52 / 69.2% / +0.75 / +39.2 | 139 / 68.3% / +0.87 / +120.6 | 77 / **77.9%** / **+0.98** / **+75.7** |
| XRP | 45 / 64.4% / +0.68 / +30.6 | 122 / 63.9% / +0.73 / +88.6 | 69 / **75.4%** / **+0.95** / **+65.5** |
| HBAR | 2 / — / — / — | 18 / 50.0% / +0.23 / +4.2 | 2 / — / — / — |
| AVAX | 60 / 70.0% / +0.76 / +45.8 | **140** / 70.0% / **+0.89** / **+124.6** | 94 / 61.7% / +0.57 / +54.0 |
| LINK | 64 / 73.4% / +0.87 / +55.7 | 116 / 66.4% / +0.81 / +94.2 | 88 / 68.2% / +0.83 / +72.9 |
| BNB | 34 / 70.6% / +0.92 / +31.3 | 102 / 52.9% / +0.45 / +45.6 | 45 / 51.1% / +0.28 / +12.7 |
| ADA | 17 / 64.7% / +0.52 / +8.9 | 62 / 61.3% / +0.59 / +36.5 | 27 / 63.0% / +0.52 / +14.1 |
| **POL** | 6 / 33.3% / **-0.24** / -1.5 ⚠ | 29 / 27.6% / **-0.10** / -2.9 ⚠ | 5 / **0.0%** / **-0.38** / -1.9 ⚠ |
| TON | 29 / 55.2% / +0.39 / +11.3 | 110 / 58.2% / +0.54 / +59.1 | 56 / 58.9% / +0.37 / +20.8 |
| ATOM | 23 / 65.2% / +0.43 / +9.8 | 80 / 63.7% / +0.61 / +48.7 | 45 / 57.8% / +0.33 / +14.7 |
| **BCH** | 44 / **84.1%** / **+1.18** / +51.9 | 108 / 61.1% / +0.68 / +73.4 | 67 / 58.2% / +0.54 / +35.9 |

### Reading

- **POL flashes a per-token blowup in all three configs** — `n ≥ 5 AND
  WR ≤ 35% AND avg_R < 0`. Strategy-agnostic. This is consistent with the
  fade soak's CRT pin where POL was already the weakest token (per the
  Step 1 BREAKOUT_REPORT, POL was the weakest 46% WR / +0.38 R survivor of
  the friction screen). **POL doesn't belong in any of these three configs.**
- **BCH is A's standout** at 84% WR / +1.18 R / +52 sum_R. BCH performs much
  better at 4H reference than 1H, suggesting BCH's structural patterns play
  out over longer wall-clock windows.
- **ETH/XRP shine at C's 1M/1H** — both jump to ~75-78% WR with strong avg_R.
  These tokens may be the 1M's specific value-add: high-liquidity pairs where
  finer entry timing captures more of the move before it reverts.
- **AVAX is B's headline** — 140 signals at 70% WR / +0.89 = +125 sum_R, the
  single best per-token cell in the entire grid.
- **BNB degrades sharply at finer TFs:** A=70.6% WR → B=52.9% → C=51.1%. BNB's
  edge appears to come from the H4 setup specifically.

---

## 5. Friction-sensitivity diagnostic

Counting the % of CLEAN avg_R that survives friction-on:

| Config | clean avg_R | friction avg_R | % survives |
|---|---:|---:|---:|
| A 5M/4H | +0.759 | +0.616 | **81.2%** |
| B 5M/1H | +0.662 | +0.549 | 83.0% |
| C 1M/1H | +0.635 | +0.532 | **83.8%** |

Three reads of this result:

1. **A loses the most fractional avg_R to friction** despite being structurally
   the wider-timeframe config. Reason: A's clean avg_R is the highest, so the
   fixed-cost friction overlay is a higher fraction of the upside.
2. **C survives friction best in fractional terms.** I had expected 1M to suffer
   more from friction; the BEW economics gate at signal time pre-filters the
   1M setups in a way that lets only wide-stop survivors through, and those
   look like 5M setups in economics terms. The 1M's "fast entry" advantage
   doesn't get diluted by friction as much as expected.
3. **All three friction-survival ratios fall in the 81-84% range.** That's
   tight enough that friction sensitivity is NOT a major differentiator
   between these configurations.

---

## 6. CPCV / PSR / DSR verdicts

All 6 runs (3 configs × clean/friction) **PASS** CPCV with `wr_mean ≥ 58%`
and `wr_q05 ≥ 50%`. PSR = 1.00 across the board (per-trade Sharpe is large
enough that the null hypothesis SR=0 is overwhelmingly rejected). DSR
deflated by `n_trials = 3` (cross-config Sharpe std = 0.0467) is also 1.00 —
the configs are strongly correlated (they share the underlying breakout
thesis) so DSR's selection-bias correction is very mild in this comparison.

**Statistical interpretation:** the per-trade Sharpe + n_signals product is so
high in every run that PSR/DSR can't differentiate them. Discrimination has to
come from EXPECTANCY metrics (avg_R, PF, sum_R) and OOS behavior (train→test,
walk-forward) — not from these p-style metrics.

---

## 7. Honest finding

**A (5M/4H) has the strongest per-trade quality and OOS strengthening
trajectory.** Highest avg_R (+0.76 clean / +0.62 friction). Highest PF (3.71
/ 3.23). Walk-forward: May at 79% WR / +0.98 R / PF 5.9. Train→test +0.39
OOS gain. This is the cleanest "edge survives forward" signature in the grid.

**B (5M/1H) has the strongest total expectancy by a wide margin.** sum_R
+750 / +607 (more than 2.4× A's total). High signal count (1132 clean) at
solid 61.8% WR. Stable walk-forward (60→61→64% WR month-over-month). The
breadth comes at the price of per-trade R (~13% lower than A clean).

**C (1M/1H) does not have a clear value-add over A or B.** It produces 1.5×
more signals than A but less than half of B's. Per-trade avg_R sits between
A and B. Critically, C is the ONLY config where OOS train→test edge slightly
DEGRADES (+0.65 → +0.60) AND May is C's weakest month. The 1M-entry's
expected benefit (faster reaction to MSS) does not show up as superior
per-trade R in this 90-day sample. The 1M data infrastructure cost in a live
soak (60× more bars to fetch each cycle, more Binance rate-limit pressure,
more disk write churn) is non-trivial and would buy uncertain edge.

**POL is broken in all three configs.** Same WR ≤ 35% AND avg_R < 0 pattern
that appeared in the fade era. Whatever the strategy, POL is unreliable.

---

## 8. What this report does NOT do

- ❌ Recommend switching the live soak from A to B (or to C).
- ❌ Treat B's higher sum_R as proof B is "better" — it could be that the
  shorter 1H reference simply produces more setups in this 90-day window
  (which has been steadily bullish for most of it). A different 90 days
  might invert the ranking.
- ❌ Treat A's +0.39 OOS gain as a robust forecast — n=410 over 90 days is
  modest and any single trade outlier (BCH had a particularly strong run)
  can swing the avg_R notably.
- ❌ Decide for the operator. The trade-off is:
  - quality (A) vs throughput (B) vs neither-clearly-better (C)
  - and the live operator's MANUAL execution discipline matters more for
    a high-frequency config (B) than a sparse one (A).

---

## 9. What WOULD need to happen to make a switch decision

If the operator wants to consider switching:

1. **Run the same 3 configs on a different 90-day window** (e.g.
   2025-12-01 → 2026-03-01) and check that the ranking is preserved. If
   B beats A on every window, the throughput edge is robust. If A
   sometimes wins, the choice depends on regime.
2. **Stand up a parallel paper soak on the candidate config** (B is the
   most interesting candidate given the +750 R total). 30+ closed signals
   needed, same gate criteria as the current breakout soak. Run alongside
   the existing 5M/4H soak; the two soaks share OHLCV but isolate at the
   signal / DB level.
3. **The decision NEVER skips the forward-soak gate.** Backtests over 90
   days are a screen. Until 30+ paper signals close, no merge.

This report explicitly does NOT advance to step 2 or 3. It only ENABLES the
operator to decide whether step 2 is worth doing.

---

## 10. Limitations and caveats

1. **90 days is a SHORTER span than the 365-day window that originally
   validated A.** This comparison is fair (same span for all three) but
   weaker statistical power than Step 1's grid had. CPCV PASS is reassuring
   but the per-month n is small (~130 for A).
2. **1M data is fresh-fetched from Binance for the 90-day window.** Older
   1M data (>90 days) is harder to fetch in bulk; this comparison only
   covers a recent quarter. If the 1M edge depends on a specific recent
   regime, the result for C could revert in a different period.
3. **The TF-scaling rule (same bar count) means C examines a SHORTER
   wall-clock context (4h ref lookback, 30min MSS horizon) than A.** This
   IS a property of moving to 1M entry — there's no "fair" way to scale
   that doesn't change the engine's structural intent in some way. I chose
   "same bar count" because the engine's intent is in bars, not clocks.
4. **Friction model applied identically across all 3 configs.** That's
   conservative for 1M (which might face more real-world latency in live
   trading because operator reaction to a Telegram alert on a 1m bar is
   proportionally a larger fraction of the bar). The Step 2A caveat (stale-
   move rejection is 0 in bar-data harness) applies equally to all three.
5. **DSR=1.00 across all 6 runs** is honest given the data but provides
   no discrimination. The configs are all "in the same family" so the
   deflation is mild.
6. **POL is broken across all three — but I did not remove it from any
   config.** Keeping POL in keeps the comparison apples-to-apples.

---

## 11. Reproducibility

Every number in this report can be reproduced from `data/breakout.db` and
the JSON summaries:

```bash
cd /home/tradeai/breakout-work

# Run grid (~25s)
python3 run_tf_grid.py

# Compute metrics (~5s)
python3 compute_tf_metrics.py
```

Files generated by this study:
- `data/cache_1m_90d/*.json` — 12 tokens × 90 days of 1m OHLCV (~80 MB, gitignored)
- `data/breakout.db backtest_runs id=19..24` — the 6 backtest rows
- `data/breakout.db backtest_signals source LIKE 'H4_BREAKOUT_TF_%'`
- `data/tf_grid_results.json` — run summary
- `data/tf_metrics_results.json` — per-run honest metrics

---

## 12. Isolation check (end-of-run)

| Item | State |
|---|---|
| Fade soak alive | PID 393274 cycle 8248, 0 errors |
| Breakout soak alive | PID 458923 cycle 59, 0 open / 0 closed |
| `signals.db` size | 5,492,736 bytes — unchanged |
| Run-3704 pin | unchanged |
| `breakout.db` writes from this study | only the 6 new run rows + their signals (tagged `H4_BREAKOUT_TF_*`) |
| `main` | untouched |
| `breakout-thesis` | `70852df` on origin — NOT advanced by this study |
| All caches read | read-only from JSON files |
| 1M data persisted to | `data/cache_1m_90d/` (gitignored) |
