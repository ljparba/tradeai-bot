# Phase C-Breakout — Regime-Filtered Variant: Honest Screen

**Mode:** new strategy variant screened against the validated 720d Config 14 baseline. **Pre-registered rule, single trial, no parameter sweep, run ONCE.**

**Audited:** 2026-06-03 ~06:40 UTC.
**Audited processes:** A PID 473059, B PID 473060 (alive, untouched throughout).

---

## §0 — Pre-registered rule (frozen before any code execution)

| Parameter | Value | Justification |
|---|---|---|
| Macro proxy | BTC 4h closes | Same proxy used in all prior regime audits — consistency |
| MA window N | **50 bars (~8.33 days)** | Common round number for medium-term 4h crypto trend. Chosen a priori — NOT swept |
| Neutral band X | **±2% around MA** | Typical noise-band threshold. Chosen a priori — NOT swept |

**Decision rule:**

| BTC vs MA50 | Regime | Direction kept |
|---|---|---|
| `close > MA × 1.02` | BULL | BUY only (reject SELL) |
| `close < MA × 0.98` | BEAR | SELL only (reject BUY) |
| `0.98 × MA ≤ close ≤ 1.02 × MA` | NEUTRAL | both directions |

**Causal lookup (verified):** at signal time `t`, find the latest 4h bar whose close_time ≤ `t`. Use that bar and its 49 prior bars (50 closed bars) to compute MA50. The current bar — which is OPEN at signal time — is NEVER read. Implementation: [`regime_filter_720d.py:62`](regime_filter_720d.py#L62) — `cutoff = signal_ts_ms - BAR_DUR_MS; i = bisect.bisect_right(times, cutoff) - 1`.

**Trial count for DSR deflation: 1 single trial** (this pre-registered rule). DSR honestly deflated against the production 19-config pool as before.

---

## §1 — Filter cuts ~30% of signals, evenly across counter-trend buckets

Applied as a causal post-filter to the existing 720d backtest rows (does NOT re-run the engine; the new rows preserve every column of the originals except `source` which gets the `_REGIME` suffix).

| Source | Input n | Kept n (% of input) | Dropped: BULL/SELL | Dropped: BEAR/BUY | Dropped: INSUF |
|---|---|---|---|---|---|
| TF_A 5m/4h CLEAN | 4,843 | 3,442 (71.1%) | 576 | 767 | 58 |
| TF_A 5m/4h FRICTION | 4,744 | 3,375 (71.1%) | 562 | 751 | 56 |
| TF_B 5m/1h CLEAN | 12,330 | 8,611 (69.8%) | 1,555 | 2,033 | 131 |
| TF_B 5m/1h FRICTION | 12,090 | 8,429 (69.7%) | 1,526 | 2,007 | 128 |

The filter cut **~28-30% of all signals** — half BULL/SELL rejections, half BEAR/BUY rejections, plus a tiny INSUF tail from the first MA-bootstrapping days. The filter is doing what it's supposed to do mechanically.

---

## §2 — Head-to-head: REGIME-FILTERED vs UNFILTERED 720d

| Variant | n | WR | avg_R | sum_R | PF | maxDD | Sharpe |
|---|---|---|---|---|---|---|---|
| TF_A CLEAN base | 4843 | 66.5% | +0.7042 | **+3410.20** | 3.306 | 8.6R | +0.610 |
| TF_A CLEAN regime | 3442 | 66.9% | +0.7213 | **+2482.55** | 3.399 | 7.0R | +0.625 |
| Δ | −1401 | +0.4pp | **+0.0171** | **−927.65** | +0.093 | −1.6R | +0.015 |
| TF_A FRICTION base | 4744 | 66.3% | +0.5637 | **+2674.13** | 2.883 | 7.8R | +0.530 |
| TF_A FRICTION regime | 3375 | 66.6% | +0.5763 | **+1945.08** | 2.955 | 7.3R | +0.543 |
| Δ | −1369 | +0.4pp | **+0.0126** | **−729.05** | +0.072 | −0.5R | +0.013 |
| TF_B CLEAN base | 12330 | 66.1% | +0.7683 | **+9473.13** | 3.757 | 8.6R | +0.672 |
| TF_B CLEAN regime | 8611 | 66.7% | +0.7864 | **+6771.87** | 3.900 | 7.8R | +0.693 |
| Δ | −3719 | +0.6pp | **+0.0181** | **−2701.26** | +0.143 | −0.8R | +0.021 |
| TF_B FRICTION base | 12090 | 66.0% | +0.6397 | **+7734.46** | 3.350 | 8.7R | +0.601 |
| TF_B FRICTION regime | 8429 | 66.5% | +0.6551 | **+5522.01** | 3.473 | 7.7R | +0.621 |
| Δ | −3661 | +0.5pp | **+0.0154** | **−2212.45** | +0.123 | −1.0R | +0.020 |

**Critical numbers:** per-signal `avg_R` improves by only **+0.013 to +0.018 R** (tiny). Total `sum_R` drops by **27-29% across all 4 configs** because 30% of signals are removed and they were positive-edge on average.

PF improves modestly (+0.07 to +0.14). maxDD improves modestly (−0.5 to −1.6 R). Sharpe improves +0.013 to +0.021.

The hypothesis ("counter-trend trades drag the edge — filtering them will substantially improve avg_R") **does not hold up**. The improvement is barely measurable per-signal.

---

## §3 — Why doesn't filtering counter-trend trades help much?

Per-direction × monthly-macro breakdown on TF_B FRICTION:

**BASE (unfiltered):**

| Monthly macro | BUY n | BUY avg_R | SELL n | SELL avg_R |
|---|---|---|---|---|
| BULL | 848 | +0.632 | 613 | +0.621 |
| RANGE | 4706 | +0.596 | 4115 | +0.696 |
| BEAR | 897 | +0.548 | 911 | +0.720 |

**FILTERED:**

| Monthly macro | BUY n | BUY avg_R | SELL n | SELL avg_R |
|---|---|---|---|---|
| BULL | 691 (−157) | +0.630 | 248 (−365) | +0.690 |
| RANGE | 3372 (−1334) | +0.609 | 2924 (−1191) | +0.709 |
| BEAR | 332 (−565) | +0.496 | 862 (−49) | +0.726 |

(Note: signal-time regime ≠ monthly macro. Signals during a NEUTRAL bar within a BULL month are kept regardless of direction.)

### The implied avg_R of the REJECTED signals

From the deltas in BEAR months:
- BASE BUYs in BEAR months: 897 signals at +0.548 avg_R
- KEPT BUYs in BEAR (during NEUTRAL signal-time bars): 332 at +0.496
- **REJECTED BUYs in BEAR: 565 signals at implied avg_R ≈ (897×0.548 − 332×0.496) / 565 = +0.578**

From the deltas in BULL months:
- BASE SELLs in BULL months: 613 at +0.621
- KEPT SELLs in BULL: 248 at +0.690
- **REJECTED SELLs in BULL: 365 signals at implied avg_R ≈ +0.575**

**The signals the filter REJECTS average +0.57 R — they are PROFITABLE, just slightly less profitable than the with-trend signals.** Removing them loses ~+0.57 R per rejected signal while improving the kept-pool average by only ~+0.015 R per kept signal. The math doesn't work in favor of filtering.

**Why does counter-trend not lose?** A breakout system fires only on committed C2 closes beyond C1 (a directional break in the local 4h structure) plus 5M continuation MSS plus FVG/OB confluence. By the time the trigger fires, the LOCAL flow is already aligned with the signal direction — the macro regime is irrelevant. A BUY breakout during a BEAR macro is still a clean local upmove with structural support. It just happens to fight the macro tide, so the win rate is slightly lower and the R is slightly lower, but it still nets profitable on average.

---

## §4 — OOS 70/30 + CPCV + DSR (the overfit check)

| Run | Train avg_R | Test avg_R | CPCV WR mean | CPCV WR std | q05 | DSR | Verdict |
|---|---|---|---|---|---|---|---|
| TF_A FRICTION BASE 720d | +0.5561 | +0.5815 | 66.27% | 2.44 | 61.96% | **1.0000** | PASS |
| TF_A FRICTION REGIME | +0.5683 | **+0.5950** | 66.64% | 2.20 | 62.87% | **1.0000** | PASS |
| TF_B FRICTION BASE 720d | +0.6516 | +0.6122 | 66.00% | 1.48 | 63.28% | **1.0000** | PASS |
| TF_B FRICTION REGIME | +0.6695 | +0.6215 | 66.54% | 1.87 | 63.76% | **1.0000** | PASS |

**Both variants PASS DSR at 1.0000 with verdict=PASS.** The filter does not gain a DSR advantage despite the deflation context being identical.

**OOS test set:**
- TF_A REGIME test +0.5950 > train +0.5683 → no overfit signature; consistent slight gain over the base's +0.5815 test (+0.014, matching the in-sample delta).
- TF_B REGIME test +0.6215 > base test +0.6122 (+0.009).

The filter's tiny per-signal improvement survives OOS — it's not curve-fit. But the improvement is small enough that it doesn't justify adding the complexity.

---

## §5 — Detection lag at major regime flips

**Major regime flips (persisted ≥ 5 days each) over 720 days: 31 flips.** Roughly **one major flip every 23 days**.

### MA-lag at each flip — BTC had already moved BEFORE the MA detected it

| Flip date | Flipped to | BTC at flip | BTC 7d earlier | Change in prior 7d |
|---|---|---|---|---|
| 2024-11-06 | BULL | 74349 | 72234 | +2.93% (BTC up 2.9% before MA agreed) |
| 2025-02-24 | BEAR | 94324 | 95659 | −1.40% (BTC down 1.4% before MA agreed) |
| 2025-04-21 | BULL | 87206 | 84566 | +3.12% |
| 2025-11-03 | BEAR | 107937 | **114959** | **−6.11%** (already down 6%!) |
| 2025-11-13 | BEAR | 98682 | 101389 | −2.67% |
| 2026-01-29 | BEAR | 84934 | 89000 | −4.57% |
| 2026-04-13 | BULL | 73323 | 69740 | +5.14% |

**The MA detects regime flips AFTER the price has already moved 1-6% in the new direction.** The filter is reactive — by the time it says "BEAR — keep only SELLs", much of the easy SELL move has already happened, and the imminent bounce-back BUYs are about to fire. This is a known structural weakness of MA-based regime classifiers.

### Whipsaw count

**329 round-trip transitions within 5 days** (BULL → NEUTRAL → BULL, or BEAR → NEUTRAL → BEAR, completed inside 5 days). The MA50 ± 2% rule whipsaws frequently when BTC chops near the MA, flipping the filter's direction permissions every few hours and creating short BULL → NEUTRAL → BEAR → NEUTRAL → BULL cycles. Each round-trip is a moment when the filter changed its mind about which direction to take — adding noise to the live decision boundary.

This whipsaw count is so high because the band (±2%) and the MA (50 bars) are sized for medium-term context, but BTC's intraday vol is comparable to the band width. Widening the band would reduce whipsaws but also reduce the filter's hit-rate on real regime changes — classic bias/variance trade-off.

---

## §6 — VERDICT (honest, no rescue)

**The pre-registered regime filter does NOT meaningfully beat the unfiltered Config 14 baseline.** Recommendation: **stick with the simpler unfiltered Config 14**.

### Numerical verdict

| Dimension | Base 720d | Regime 720d | Winner |
|---|---|---|---|
| avg_R per signal (TF_A FRICTION) | +0.5637 | +0.5763 | regime (+0.013) |
| avg_R per signal (TF_B FRICTION) | +0.6397 | +0.6551 | regime (+0.015) |
| **sum_R total (TF_A FRICTION)** | **+2674** | **+1945** | **base by +729 R (+27%)** |
| **sum_R total (TF_B FRICTION)** | **+7734** | **+5522** | **base by +2212 R (+29%)** |
| Sharpe (per-signal) | +0.530 / +0.601 | +0.543 / +0.621 | regime by +0.01–0.02 |
| DSR | 1.0000 | 1.0000 | tie |
| Signal density (per year) | ~6 / day | ~4 / day | base |
| Failure modes added | none | MA lag, whipsaw (329 round-trips) | base |
| Complexity | causal H4 break only | + BTC 4h MA50 ±2% real-time classifier | base |

### Why it doesn't win

1. **Counter-trend signals ARE profitable.** The signals the filter REJECTS average +0.575 R — not loss-makers, just slightly less profitable than with-trend (+0.620 R). Removing them drops total profit by 27-29%, far more than the per-signal lift compensates for.

2. **MA detection lags the price by 1-6%.** By the time the filter says "BEAR, sell only", BTC has already dropped 1-6% over the prior week. The easy with-trend SELL move is partially gone; the imminent bounce-BUYs are about to fire. The lag eats into the with-trend advantage the filter is trying to capture.

3. **329 whipsaws over 720 days** (BULL→NEUTRAL→BULL or BEAR→NEUTRAL→BEAR within 5 days). In live mode, the filter would flip-flop direction permissions repeatedly, creating noise at the decision boundary.

4. **DSR is unchanged.** Both base and regime variants PASS at 1.0000 against the production pool. The filter doesn't add statistical confidence — just complexity.

### What if we tuned the parameters?

The pre-registered rule used `MA=50, band=2%`. Could a different choice (e.g. `MA=20, band=1%` or `MA=100, band=3%`) win cleanly? Possibly — but **that path is overfitting**. The strategy already works without a filter. Adding a filter that needs careful parameter tuning to barely match the unfiltered baseline is the textbook signature of curve-fitting.

The honest call: the breakout strategy is **directionally symmetric enough that filtering by macro regime doesn't pay**. The take-both-directions design captures local breakouts wherever they appear and nets positive across macro regimes (validated in `PHASE_C_720D_BACKTEST.md` per-regime table). A macro filter is a solution to a problem that doesn't exist for this strategy.

### If the operator still wants to test this filter live

The regime variant DOES pass the DSR gate and shows a tiny positive lift. If the operator chooses to forward-test it anyway as a **separate** soak (NOT replacing the base soak), the validation discipline should be:

1. New soak C (5m/1h, regime-filtered). Source tag `H4_BREAKOUT_PAPER_SOAK_C` (or similar).
2. Validate from zero — same n≥30, avg_R≥+0.40, PF≥2.0, etc. gate as A and B.
3. Compare forward results against soak B (its unfiltered twin) head-to-head over the same window.
4. Pre-register a comparison gate: regime variant must beat unfiltered B by ≥ +0.10 R/signal over n≥30 to justify the added complexity. Below that threshold, prefer the simpler design.

**This is NOT a recommendation to start that soak.** It's only the discipline that would apply IF the operator chose to.

### What this rules out

- "BUY-in-downtrend is structurally broken" → **disproven**. BUY-in-BEAR averages +0.578 R in the 720d backtest.
- "Adding a macro trend filter is a free improvement" → **disproven**. The improvement is +0.015 R/signal and costs −28% sum_R.
- "The current forward soak's +0.30 R/signal is regime-flattered" → **partially supported**. The base strategy DOES rely on capturing both directions across regime cycles. The current downtrend is over-weighting SELL contributions, but as `DIRECTIONAL_ANALYSIS.md` showed, the backtest confirms both directions contribute positive edge over the full cycle.

---

## §7 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched throughout |
| Soak A 473059 / B 473060 | ALIVE, cycling, untouched throughout |
| `data/signals.db` (production) | unchanged (read-only access only — none in this audit) |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (not pushed) |
| Existing 90d + 365d + 720d backtest rows in breakout.db | untouched (verified by source-tag query) |
| New _REGIME rows in breakout.db | added, distinct source tag from 90d/365d/720d/soak |
| 720d cache at `data/ohlcv_cache_720d/` | read-only, unchanged |
| Existing 365d cache at `/home/tradeai/TradeAI/data/ohlcv_cache/` | unchanged |
| breakout.db backup before this run | `data/breakout.db.before_regime_bak.20260603_043906` (20 MB — captures all prior runs) |
| New artifact in working tree | `regime_filter_720d.py` (uncommitted, kept for re-runnability) |
| `run_tf_grid.py` | NOT touched in this audit — the filter operates on existing rows |

**STOP.** No tuning. No merge. No push. No live arm. The pre-registered filter ran once, the result is what it is.
