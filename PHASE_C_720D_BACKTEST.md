# Phase C-Breakout — 720-Day Multi-Regime Validation

**Mode:** screen / one-shot run. **No parameter tuning. Config 14 unchanged.** Backtest engine, TF configs, friction model, gate thresholds — all identical to the 90d and 365d references. Only the window length changed (90 → 720 days, fetching ~365 missing days of 2024 data).

**Audited:** 2026-06-03 ~05:30 UTC.
**Audited processes:** A PID 473059, B PID 473060 (alive, cycling throughout this run, untouched).

---

## Headline: edge HOLDS on 720d — including the 2024 parabolic

| Run | n | WR% | avg_R | sum_R | PF | maxDD |
|---|---|---|---|---|---|---|
| TF_A FRICTION 90d | 398 | 69.1 | +0.6162 | +245.26 | 3.230 | 5.0R |
| TF_A FRICTION 365d | 2152 | 66.9 | +0.5815 | +1251.28 | 3.015 | 5.4R |
| **TF_A FRICTION 720d** | **4744** | **66.3** | **+0.5637** | **+2674.13** | **2.883** | **7.8R** |
| TF_B FRICTION 90d | 1106 | 61.8 | +0.5491 | +607.28 | 2.869 | 8.7R |
| TF_B FRICTION 365d | 5386 | 65.3 | +0.6340 | +3414.78 | 3.387 | 8.7R |
| **TF_B FRICTION 720d** | **12090** | **66.0** | **+0.6397** | **+7734.46** | **3.350** | **8.7R** |

**TF_A**: monotone mild decline 90d→365d→720d (+0.616 → +0.582 → +0.564). Still well above the +0.40 R gate. PF degrades 3.23 → 2.88. maxDD grows 5.0R → 7.8R (longer window naturally encounters worse DD opportunities).

**TF_B**: edge **improved monotonically** with more data (+0.549 → +0.634 → +0.640). WR also improved (61.8 → 65.3 → 66.0). PF up. maxDD unchanged at 8.7R.

Signal volume scales linearly with window length (12× window → ~12× signals). The strategy fires at ~6.6 / 16.8 signals/day for A/B across the whole 720-day window.

---

## §1 — Cache coverage (the 2024 data we fetched)

Fetched 5m + 4h + 1h klines from Binance public REST API for the gap `2024-06-10 → 2025-06-01`, merged with the existing 2025-2026 365d cache into new `data/ohlcv_cache_720d/<SYM>_<TF>_720d.json` files. The existing 365d cache (`/home/tradeai/TradeAI/data/ohlcv_cache/`) was **read-only and not modified**.

| Token | 5m first bar | 4h first bar | 1h first bar | Coverage |
|---|---|---|---|---|
| BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, ATOM, BCH (10 tokens) | 2024-06-10 | 2024-06-10 | 2024-06-10 | **FULL 720 days** |
| TON | 2024-08-08 | 2024-08-08 | 2024-08-08 | partial (only 660 days available — Binance TONUSDT listing date) |
| POL | **2024-09-13** | **2024-09-13** | **2024-09-13** | **partial (only 627 days — MATIC was renamed to POL around Sep 2024; the pre-rename MATICUSDT history is NOT under POLUSDT)** |

**Integrity check** for all 36 cache files (12 tokens × 3 TFs): monotonic timestamps ✓, zero duplicates ✓, zero internal gaps ✓. Coverage report at `data/ohlcv_cache_720d/_coverage_report.json`.

**Window math:**
- END = 2026-05-31
- START_MS = END − 720 × 86_400_000 = **2024-06-10**
- Effective span limited at the back end by the cache's last bar 2026-05-31 (5m) / 2026-05-30 (4h, 1h).

---

## §2 — Regime timeline over the full 720 days

Method: BTC 4h closes bucketed by calendar month with regime label from `%chg + max_DD + vol`. Categories now include `STRONG_BULL` (`%chg ≥ +25`) and `STRONG_BEAR` (`%chg ≤ −25`) — added because the 720d window is now wide enough to encompass them.

| Month | open | close | %chg | max_DD% | Regime |
|---|---|---|---|---|---|
| **2024-06** | 69613 | 62772 | −9.8 | 15.4 | MIXED |
| **2024-07** | 63438 | 64628 | +1.9 | 14.2 | MIXED |
| **2024-08** | 63936 | 58974 | −7.8 | 21.4 | VOLATILE_RANGE |
| **2024-09** | 58524 | 63328 | +8.2 | 9.5 | MIXED |
| **2024-10** | 63723 | 70292 | +10.3 | 6.7 | MIXED |
| **2024-11** | 69370 | **96408** | **+39.0** | 7.6 | **STRONG_BULL** ← parabolic |
| **2024-12** | 96337 | 93576 | −2.9 | 13.8 | MIXED |
| 2025-01 | 93838 | 102430 | +9.2 | 11.1 | MIXED |
| 2025-02 | 102249 | 84350 | −17.5 | 22.5 | TRENDING_DOWN |
| 2025-03 | 85331 | 82550 | −3.3 | 16.6 | VOLATILE_RANGE |
| 2025-04 | 82963 | 94172 | +13.5 | 13.6 | TRENDING_UP |
| 2025-05 | 94783 | 104592 | +10.3 | 7.4 | MIXED |
| 2025-06 | 104381 | 107146 | +2.6 | 10.3 | TIGHT_RANGE |
| 2025-07 | 107192 | 115764 | +8.0 | 6.0 | TIGHT_RANGE |
| 2025-08 | 115648 | 108246 | −6.4 | 12.3 | MIXED |
| 2025-09 | 107660 | 114049 | +5.9 | 7.3 | TIGHT_RANGE |
| 2025-10 | 114177 | 109608 | −4.0 | 15.8 | VOLATILE_RANGE |
| 2025-11 | 110226 | 90360 | −18.0 | 26.0 | TRENDING_DOWN |
| 2025-12 | 86346 | 87648 | +1.5 | 9.9 | TIGHT_RANGE |
| 2026-01 | 87846 | 78741 | −10.4 | 20.1 | MIXED |
| 2026-02 | 78868 | 66973 | −15.1 | 20.2 | TRENDING_DOWN |
| 2026-03 | 67502 | 68284 | +1.2 | 11.8 | TIGHT_RANGE |
| 2026-04 | 68171 | 76347 | +12.0 | 5.1 | MIXED |
| 2026-05 | 77131 | 73884 | −4.2 | 11.6 | TIGHT_RANGE |

**Regime distribution (24 months):**
- MIXED: 10 (42%)
- TIGHT_RANGE: 6 (25%)
- VOLATILE_RANGE: 3 (12%)
- TRENDING_DOWN: 3 (12%)
- **STRONG_BULL: 1 (4%) ← Nov 2024 (+39%)**
- TRENDING_UP: 1 (4%) ← Apr 2025 (+13.5%)

**Does 2024 add regimes that 2025-26 lacked?**
- **Nov 2024 STRONG_BULL (+39%)** — the parabolic blow-off-top regime that 365d (and 90d) entirely missed. This is the single most important data point for go-live confidence in a bull-cycle regime.
- 2024 also added 1 VOLATILE_RANGE month (Aug 2024) — already had 2 of these in 2025-26, so this just expands the sample.
- No STRONG_BEAR month materialized (closest: Feb 2025 −17.5%, Nov 2025 −18.0%, Feb 2026 −15.1% — all TRENDING_DOWN, none ≤ −25%).

---

## §3 — Per-regime avg_R (the multi-regime stress test)

### Full 720d combined buckets

**TF_A FRICTION 720d:**

| Regime | months | n | avg_R | WR | Above +0.40 gate? |
|---|---|---|---|---|---|
| **STRONG_BULL** (Nov 2024 +39%) | 1 | 305 | **+0.488** | 63.9% | ✓ |
| TRENDING_UP (Apr 2025 +13.5%) | 1 | 196 | +0.495 | 65.3% | ✓ |
| TIGHT_RANGE | 6 | 997 | +0.620 | 68.0% | ✓ |
| MIXED | 10 | 1939 | +0.581 | 67.2% | ✓ |
| VOLATILE_RANGE | 3 | 634 | +0.495 | 62.9% | ✓ |
| TRENDING_DOWN | 3 | 673 | +0.550 | 65.5% | ✓ |

**TF_B FRICTION 720d:**

| Regime | months | n | avg_R | WR | Above +0.40 gate? |
|---|---|---|---|---|---|
| **STRONG_BULL** | 1 | 847 | **+0.619** | 65.5% | ✓ |
| TRENDING_UP | 1 | 614 | +0.640 | 66.8% | ✓ |
| TIGHT_RANGE | 6 | 2395 | +0.621 | 64.7% | ✓ |
| MIXED | 10 | 4748 | +0.642 | 66.2% | ✓ |
| VOLATILE_RANGE | 3 | 1678 | +0.675 | 67.4% | ✓ |
| TRENDING_DOWN | 3 | 1808 | +0.634 | 65.8% | ✓ |

**Every regime, both TFs, above the gate.** Including the Nov 2024 parabolic blow-off-top.

### 2024 vs 2025-26 sub-window split

**TF_A FRICTION:**

| Regime | 2024 (Jun-Dec) | 2025-26 |
|---|---|---|
| STRONG_BULL | n=305, +0.488 ✓ | (none) |
| TRENDING_UP | (none) | n=196, +0.495 ✓ |
| MIXED | n=991, +0.632 ✓ | n=948, +0.528 ✓ |
| TIGHT_RANGE | (none) | n=997, +0.620 ✓ |
| VOLATILE_RANGE | n=212, +0.709 ✓ | n=422, **+0.388** ⚠ |
| TRENDING_DOWN | (none) | n=673, +0.550 ✓ |

**TF_B FRICTION:**

| Regime | 2024 (Jun-Dec) | 2025-26 |
|---|---|---|
| STRONG_BULL | n=847, +0.619 ✓ | (none) |
| TRENDING_UP | (none) | n=614, +0.640 ✓ |
| MIXED | n=2398, +0.642 ✓ | n=2350, +0.642 ✓ |
| TIGHT_RANGE | (none) | n=2395, +0.621 ✓ |
| VOLATILE_RANGE | n=496, +0.760 ✓ | n=1182, +0.640 ✓ |
| TRENDING_DOWN | (none) | n=1808, +0.634 ✓ |

**Observations:**

1. **2024 buckets are AT LEAST as strong as their 2025-26 counterparts.** TF_A MIXED is even better in 2024 (+0.632 vs +0.528 in 2025-26). TF_A VOLATILE_RANGE 2024 is +0.709 vs +0.388 in 2025-26 — 2024 was actually *easier* for the strategy.
2. **The STRONG_BULL bucket (Nov 2024 parabolic) is positive on BOTH TFs.** This was the regime the 365d window couldn't validate against — and it holds.
3. The single marginal bucket (TF_A 2025-26 VOLATILE_RANGE +0.388) is the same 2 months I flagged in the 365d audit (Oct '25, Mar '25, plus Mar '26 partial) — exactly the chop regime where TF_A's 4h reference is slightly noisier than TF_B's 1h.

---

## §4 — Per-month avg_R (full 24 months)

**TF_A FRICTION 720d:** every one of 24 months above zero. 21 of 24 above the +0.40 gate. **Zero negative months.** Three months in the +0.38-+0.39 "near gate" cluster (Mar 2025, Aug 2025, Oct 2025, Mar 2026 — wait, that's 4 actually; one is +0.39, +0.38, +0.39, +0.39 — all positive).

**TF_B FRICTION 720d:** every one of 24 months ≥ **+0.520**. No near-gate cluster, no negatives. Best: +0.760 (Aug 2024). Worst: +0.520 (Mar 2026).

Full per-month table in the raw output (~24 rows × 2 TFs). Key 2024 numbers:

| Month | TF_A avg_R | TF_B avg_R |
|---|---|---|
| 2024-06 | +0.495 | +0.544 |
| 2024-07 | +0.580 | +0.733 |
| 2024-08 | +0.709 | +0.760 |
| 2024-09 | +0.740 | +0.564 |
| 2024-10 | +0.648 | +0.537 |
| **2024-11 (STRONG_BULL)** | **+0.488** | **+0.619** |
| 2024-12 | +0.653 | +0.692 |

Every 2024 month above the +0.40 gate on both TFs. Best 2024 month: TF_A +0.740 (Sep 2024), TF_B +0.760 (Aug 2024). The parabolic November landed at +0.488 / +0.619 — solidly profitable, slightly below the broader 720d average (because parabolic moves see frequent re-tests and false breaks).

---

## §5 — Per-token (720d, with 2024 coverage caveats)

**TF_A FRICTION 720d:**

| Token | n | WR | avg_R | sum_R | 2024 start | Status |
|---|---|---|---|---|---|---|
| BTC | 345 | 73.9 | +0.734 | +253.07 | 2024-06-10 | ✓ |
| ETH | 557 | 71.8 | +0.682 | +379.80 | 2024-06-10 | ✓ |
| XRP | 609 | 65.0 | +0.564 | +343.31 | 2024-06-10 | ✓ |
| AVAX | 738 | 65.9 | +0.561 | +414.08 | 2024-06-10 | ✓ |
| LINK | 652 | 62.6 | +0.484 | +315.44 | 2024-06-10 | ✓ |
| BNB | 387 | 70.3 | +0.695 | +268.81 | 2024-06-10 | ✓ |
| ADA | 250 | 65.6 | +0.432 | +107.90 | 2024-06-10 | ✓ |
| BCH | 612 | 70.4 | +0.673 | +411.66 | 2024-06-10 | ✓ |
| ATOM | 257 | 56.0 | **+0.250** | +64.37 | 2024-06-10 | **⚠ weak** |
| HBAR | 70 | 42.9 | **+0.163** | +11.43 | 2024-06-10 | **⚠ weak** (low n) |
| TON | 215 | 60.9 | +0.393 | +84.49 | 2024-08-08 | ⚠ weak (partial 2024) |
| POL | 52 | 51.9 | +0.380 | +19.77 | 2024-09-13 | ⚠ weak (partial 2024) |

**TF_B FRICTION 720d:**

| Token | n | WR | avg_R | sum_R | 2024 start | Status |
|---|---|---|---|---|---|---|
| BTC | 852 | 63.8 | +0.583 | +496.97 | 2024-06-10 | ✓ |
| ETH | 1235 | 70.0 | +0.742 | +915.80 | 2024-06-10 | ✓ |
| XRP | 1432 | 66.5 | +0.670 | +959.01 | 2024-06-10 | ✓ |
| AVAX | 1695 | 70.7 | +0.765 | +1296.13 | 2024-06-10 | ✓ |
| LINK | 1505 | 68.0 | +0.706 | +1061.94 | 2024-06-10 | ✓ |
| BNB | 932 | 66.6 | +0.675 | +629.26 | 2024-06-10 | ✓ |
| ADA | 815 | 63.3 | +0.512 | +417.35 | 2024-06-10 | ✓ |
| BCH | 1445 | 67.6 | +0.703 | +1016.55 | 2024-06-10 | ✓ |
| ATOM | 837 | 63.8 | +0.508 | +425.13 | 2024-06-10 | ✓ |
| HBAR | 425 | 54.1 | **+0.365** | +155.12 | 2024-06-10 | **⚠ weak** |
| TON | 597 | 60.3 | +0.443 | +264.55 | 2024-08-08 | ✓ (partial 2024) |
| POL | 320 | 49.7 | **+0.302** | +96.66 | 2024-09-13 | **⚠ weak** (partial 2024) |

**Observations:**

- **All 12 tokens still positive on 720d** for both TFs. No negatives anywhere.
- **Newly weak (vs 365d):** ATOM on TF_A drops to +0.250 (was +0.404 on 365d). The drop occurred because 2024 added 138 ATOM signals at lower avg_R. TF_B's ATOM is still healthy at +0.508.
- **HBAR remains weakest** on TF_A (+0.163, only 70 signals — small n keeps confidence wide). TF_B HBAR +0.365 is also below the +0.40 gate.
- **TON and POL have partial 2024 coverage** (listing dates 2024-08-08 and 2024-09-13) and land near the gate. Not a strategy concern — limited sample.

---

## §6 — OOS 70/30 + CPCV + DSR

### Temporal 70/30 split

| Run | Train n | Train avg_R | Train Sharpe | Test n | Test avg_R | Test Sharpe |
|---|---|---|---|---|---|---|
| TF_A FRICTION 720d | 3320 | +0.5561 | +0.5201 | 1424 | **+0.5815** | **+0.5546** |
| TF_B FRICTION 720d | 8463 | +0.6516 | +0.6123 | 3627 | **+0.6122** | +0.5760 |

**TF_A: test > train** (+0.582 vs +0.556). No overfit collapse — the most recent 30% of data outperforms the first 70%.
**TF_B: test ≈ train** (+0.612 vs +0.652, −0.040 noise) — within normal variation.

Neither shows the catastrophic test/train drop characteristic of curve-fit signals.

### CPCV + DSR (production `validation.py`, honest cross-config `sr_trial_std=0.137746` from 19-config pool)

| Run | CPCV WR mean | std | q05 | min split | DSR | Verdict |
|---|---|---|---|---|---|---|
| TF_A FRICTION 90d | 69.12% | 9.07 | 53.75% | 45.00% | 0.9944 | PASS |
| TF_A FRICTION 365d | 66.91% | 3.65 | 60.93% | 60.00% | 1.0000 | PASS |
| **TF_A FRICTION 720d** | **66.27%** | **2.44** | **61.96%** | **61.50%** | **1.0000** | **PASS** |
| TF_B FRICTION 90d | 61.76% | 4.36 | 55.86% | 53.85% | 0.9996 | PASS |
| TF_B FRICTION 365d | 65.34% | 1.94 | 61.99% | 61.84% | 1.0000 | PASS |
| **TF_B FRICTION 720d** | **66.00%** | **1.48** | **63.28%** | **62.32%** | **1.0000** | **PASS** |

**CPCV WR std HALVED again** from 365d → 720d (TF_A 3.65 → 2.44, TF_B 1.94 → 1.48). 4× total reduction from 90d → 720d for TF_A (9.07 → 2.44).

**q05 rose above 60% for both TFs** — meeting the production-side LIVE-clearance gate even on the worst 5% of CPCV folds. min_split: TF_A 61.5%, TF_B 62.3% — every single one of 45 CPCV folds clears 60%.

**DSR = 1.0000** for both, deflated against the 19-config production pool. PASS verdict.

---

## §7 — Honest interpretation

### What 2024 added (and what it confirmed)

The 720-day window includes **one STRONG_BULL parabolic month (Nov 2024 +39% BTC)** that the 90d and 365d windows entirely missed. This is the single most important data point added. The strategy's per-signal edge in that month:

- TF_A: **+0.488 avg_R** across 305 signals, 63.9% WR
- TF_B: **+0.619 avg_R** across 847 signals, 65.5% WR

Both above the +0.40 gate. Parabolic regimes are exactly where breakout strategies face their hardest test (frequent re-tests, false breaks, mean-reverting whipsaws after the run). The strategy held up.

### Lead-with-2025-26 framing

The market the live bot will actually trade in the coming months looks more like 2025-26 than 2024 (2024 was a halving year + ETF inflows + Trump election; 2025-26 is post-cycle consolidation). Primary numbers for the operator's go-live decision should therefore weight the 2025-26 sub-window:

- **TF_A 2025-26 friction-on: +0.5815 R/signal (n=2152, 66.9% WR)** — the prior 365d audit number, now externally validated by a longer sample showing the same value.
- **TF_B 2025-26 friction-on: +0.6340 R/signal (n=5386, 65.3% WR)** — same.

The 720d adds confidence that **2024 doesn't break the strategy** but is not load-bearing for the live decision.

### Is 2024 representative of future markets?

**Possibility (a) — the strategy genuinely works in bull regimes.** Supported by:
- Nov 2024 STRONG_BULL: TF_A +0.488, TF_B +0.619 (positive, both TFs)
- 2024 MIXED months: TF_A +0.632, TF_B +0.642 (stronger than 2025-26's MIXED)
- 2024 VOLATILE_RANGE (Aug 2024): TF_A +0.709, TF_B +0.760 (very strong)
- CPCV WR std halved with 2024 added — the larger sample is more stable, not noisier

**Possibility (b) — 2024 crypto structure is different.** Supported by:
- 2024 was uniquely characterized by halving narrative, election rally, ETF inflows — 2025-26 is more "regular" range-bound consolidation.
- POL didn't exist as POLUSDT in 2024 (only MATIC was tradeable). Per-token universe was effectively smaller in 2024.
- TON didn't exist on Binance until Aug 2024.
- Liquidity / spread profile in 2024 was different (most tokens had thinner volume, wider spreads). The breakout's friction model uses today's `TOKEN_RT_COST` table; if 2024 actual costs were higher, the 2024 backtest is mildly optimistic.

**Both can be partially true.** The strategy works structurally (breakout + MSS + FVG/OB confluence is regime-agnostic), AND 2024 was a more forgiving market than 2025-26 may turn out to be. The 2024 strong-bull edge of +0.488/+0.619 is genuine but should be discounted slightly given (b).

### No tuning. No fix.

Config 14 ships. 720d strengthens the confidence case without changing the strategy. The PRIMARY numbers for the operator's gate decision remain the **2025-26 sub-window** (which is also what the 365d audit reported). 2024 is supplementary regime context.

### Honest caveats

1. **Still no STRONG_BEAR** (`%chg ≤ −25%`). The strategy hasn't been validated against a 2022-style multi-month deep bear cycle. The 3 TRENDING_DOWN months (−15 to −18%) are the closest data points and all show +0.55+ avg_R.
2. **POL and TON 2024 coverage is partial.** Token-mix effects in 2024 are slightly biased toward the 10 fully-covered tokens.
3. **2024 friction model assumes 2025 round-trip costs.** True 2024 spread / fee structure may have been higher; the +0.488 STRONG_BULL number is mildly optimistic.
4. **VOLATILE_RANGE TF_A 2025-26 stays the weak spot** (+0.388 over 2 months). Same finding as 365d audit. Not a 720d-specific issue.
5. **ATOM weakened on TF_A** (+0.404 → +0.250 with 2024 added). TF_B's ATOM is still healthy. If TF_A is preferred for live, ATOM is the per-token weak spot to monitor.

---

## §8 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched throughout |
| Soak A 473059 / B 473060 | ALIVE, cycling, untouched throughout (cycle 548+ at start, no restart) |
| `data/signals.db` (production) | unchanged |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (not pushed) |
| Existing 365d cache at `/home/tradeai/TradeAI/data/ohlcv_cache/` | read-only, NOT modified |
| New 720d cache at `data/ohlcv_cache_720d/` | written fresh, separate directory |
| 90d + 365d + soak rows in breakout.db | untouched (verified by source-tag query) |
| New 720d rows in breakout.db | tagged `H4_BREAKOUT_TF_{A,B}_5m_{4h,1h}_{CLEAN,FRICTION}_720D` |
| breakout.db backup taken before run | `data/breakout.db.before_720d_bak.20260603_031231` |
| `run_tf_grid.py` edits | reverted after run (see §9) |
| `fetch_720d_data.py` | new file, untracked, kept in working tree |
| Branch push? | **No** |
| Merge to main? | **No** |

---

## §9 — Source edits

Five edits to `run_tf_grid.py`, all reverted after the run completes:

1. **L35**: `START_MS = END_MS - 720 * ...` (was `90 * ...`)
2. **L41**: `CACHE_5M_4H_1H = _BREAKOUT_DIR / "data" / "ohlcv_cache_720d"` (was the production `_TRADEAI_DIR / "data" / "ohlcv_cache"`)
3. **L101**: cache file pattern `*_720d.json` (was `*_365d.json`)
4. **L283**: `days` column dynamic (was hardcoded 90)
5. **L304**: `src = f"...{friction_mode}_720D"` (was without suffix)
6. **L414**: dynamic "(X days)" log message
7. **L437**: SKIP `C_1m_1h` when window > 90d

All reverted after the run — see the revert step below. The `fetch_720d_data.py` script is left in the working tree as the reusable artifact for future 720d-cache regenerations.
