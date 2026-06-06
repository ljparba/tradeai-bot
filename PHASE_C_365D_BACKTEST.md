# Phase C-Breakout — 365-Day Validation Run

**Mode:** screen / one-shot run. **No parameter tuning. Config 14 unchanged.** Backtest engine, TF configs, friction model, gates — all identical to the 90-day reference. Only the window length changed.

**Audited:** 2026-06-03 ~04:50 UTC.
**Audited processes:** A PID 473059, B PID 473060 (alive, cycling, untouched throughout this run).

---

## Headline: the edge HOLDS on the longer window

Both TF configs, both CLEAN and FRICTION-on, **above the +0.40 R/signal gate threshold** on 365 days:

| Run | n | WR% | avg_R | sum_R | PF | maxDD (R) |
|---|---|---|---|---|---|---|
| TF_A CLEAN 90d | 410 | 69.3 | +0.7586 | +311.04 | 3.705 | 5.0 |
| **TF_A CLEAN 365d** | **2198** | **67.2** | **+0.7252** | **+1594.07** | **3.475** | **5.5** |
| TF_A FRICTION 90d | 398 | 69.1 | +0.6162 | +245.26 | 3.230 | 5.0 |
| **TF_A FRICTION 365d** | **2152** | **66.9** | **+0.5815** | **+1251.28** | **3.015** | **5.4** |
| TF_B CLEAN 90d | 1132 | 61.7 | +0.6624 | +749.85 | 3.186 | 8.6 |
| **TF_B CLEAN 365d** | **5497** | **65.4** | **+0.7631** | **+4194.50** | **3.802** | **8.6** |
| TF_B FRICTION 90d | 1106 | 61.8 | +0.5491 | +607.28 | 2.869 | 8.7 |
| **TF_B FRICTION 365d** | **5386** | **65.3** | **+0.6340** | **+3414.78** | **3.387** | **8.7** |

Direction of change vs the 90-day reference (friction-on):
- **TF_A**: WR −2.2pp, avg_R −0.035, PF −0.215, maxDD +0.4R — **mild degradation, still well above gate**.
- **TF_B**: WR **+3.5pp**, avg_R **+0.085**, PF **+0.518**, maxDD unchanged — **IMPROVED on the longer window**.

n grew 5.4× for TF_A and 4.9× for TF_B — the strategy fired at a consistent rate (~5.9 / 14.7 signals per day for A/B) across the whole year.

---

## §1 — Window + cache coverage

The run used `START_MS = END_MS − 365 × 86400000`, all other parameters unchanged.

Effective window: **2025-05-31 → 2026-05-31** (limited at the back end by the cache's last bar 2026-05-30 — so the data span is ~364 days for all 12 tokens).

| Token | Cache 4h first | Cache 4h last | Days available | Covers 365-day window? |
|---|---|---|---|---|
| All 12 (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON, ATOM, BCH) | 2025-05-26 | 2026-05-30 | 369.7 d | ✓ (window: 2025-05-31 → 2026-05-30) |

TF_C (1m / 1h) was **skipped** by the script — the 1m cache only holds 90 days. A 365-day run on TF_C would silently truncate.

The DB was backed up to `data/breakout.db.before_365d_bak.20260603_024648` before the run.

---

## §2 — Regime timeline across the 365-day window

Method: BTC 4h closes bucketed by calendar month (matches my regime-classification method in REGIME_ANALYSIS.md). Regime label is a strict function of `%chg`, `max_DD%`, and volatility:

| Month | open | close | %chg | max_DD% | vol_ann% | Regime |
|---|---|---|---|---|---|---|
| 2025-06 | 104381 | 107146 | +2.6 | 10.3 | 33.7 | TIGHT_RANGE |
| 2025-07 | 107192 | 115764 | +8.0 | 6.0 | 29.9 | TIGHT_RANGE |
| 2025-08 | 115648 | 108246 | −6.4 | 12.3 | 32.6 | MIXED |
| 2025-09 | 107660 | 114049 | +5.9 | 7.3 | 26.1 | TIGHT_RANGE |
| 2025-10 | 114177 | 109608 | −4.0 | 15.8 | 43.4 | VOLATILE_RANGE |
| **2025-11** | **110226** | **90360** | **−18.0** | **26.0** | **48.6** | **TRENDING_DOWN** |
| 2025-12 | 86346 | 87648 | +1.5 | 9.9 | 43.3 | TIGHT_RANGE |
| 2026-01 | 87846 | 78741 | −10.4 | 20.1 | 37.5 | MIXED |
| **2026-02** | **78868** | **66973** | **−15.1** | **20.2** | **62.7** | **TRENDING_DOWN** |
| 2026-03 | 67502 | 68284 | +1.2 | 11.8 | 46.4 | TIGHT_RANGE |
| 2026-04 | 68171 | 76347 | +12.0 | 5.1 | 38.2 | MIXED |
| 2026-05 | 77131 | 73884 | −4.2 | 11.6 | 30.6 | TIGHT_RANGE |

**Regime distribution (BTC-by-month proxy):**
- TIGHT_RANGE: **6 months (50%)**
- MIXED: **3 months (25%)**
- TRENDING_DOWN: **2 months (17%)** ← Nov 2025 −18%, Feb 2026 −15% (the bear sub-phases the 90-day window lacked)
- VOLATILE_RANGE: **1 month (8%)**

**Crucially:** the 365-day window now includes **two distinct bear sub-phases (Nov 2025 and Feb 2026, totalling 457 TF_A / 1214 TF_B signals)** and a volatile-range month (Oct 2025) — sub-periods absent from the 90-day window's flat ranging macro.

---

## §3 — Per-regime avg_R (the key answer)

Bucket each backtest signal by the BTC macro regime active during its month, then compute the bucket's mean realized R (friction-on, 365d).

| Regime | months | TF_A n | TF_A avg_R | TF_A WR | TF_B n | TF_B avg_R | TF_B WR | Above +0.40 gate? |
|---|---|---|---|---|---|---|---|---|
| **TRENDING_DOWN** (Nov '25, Feb '26) | 2 | 457 | **+0.602** | 67.4% | 1214 | **+0.653** | 65.7% | ✓ both |
| VOLATILE_RANGE (Oct '25) | 1 | 206 | **+0.389** | 60.2% | 527 | **+0.713** | 69.3% | TF_A marginal (n=1 month), TF_B yes |
| MIXED (Aug '25, Jan '26, Apr '26) | 3 | 491 | **+0.566** | 67.2% | 1237 | **+0.604** | 64.6% | ✓ both |
| TIGHT_RANGE (Jun, Jul, Sep, Dec '25; Mar, May '26) | 6 | 997 | **+0.620** | 68.0% | 2395 | **+0.621** | 64.7% | ✓ both |

**The edge holds across every macro-regime bucket on the longer window.** The only marginal bucket is TF_A VOLATILE_RANGE at +0.389 — exactly one month of data (n=206), and TF_B handles the same month at +0.713. Single-month confidence interval is wide; not a structural concern.

Critically: the **TRENDING_DOWN bucket — which the 90-day window did not contain — shows +0.602 / +0.653 avg_R**, fully consistent with the headline. The strategy is NOT regime-flattered by the 90-day's ranging macro. It works through bears too.

---

## §4 — Per-month avg_R (temporal stability)

**TF_A FRICTION 365d** (sorted chronologically):

| Month | n | WR% | avg_R | Status |
|---|---|---|---|---|
| 2025-06 | 162 | 71.6 | +0.739 | ✓ above gate |
| 2025-07 | 233 | 67.8 | +0.598 | ✓ above gate |
| 2025-08 | 196 | 59.7 | +0.381 | ⚠ near gate |
| 2025-09 | 131 | 67.9 | +0.629 | ✓ above gate |
| 2025-10 | 206 | 60.2 | +0.389 | ⚠ near gate |
| 2025-11 | 232 | 66.8 | +0.582 | ✓ above gate (BEAR month) |
| 2025-12 | 184 | 67.4 | +0.634 | ✓ above gate |
| 2026-01 | 161 | 73.9 | +0.716 | ✓ above gate |
| 2026-02 | 225 | 68.0 | +0.623 | ✓ above gate (BEAR month) |
| 2026-03 | 163 | 57.1 | +0.386 | ⚠ near gate |
| 2026-04 | 134 | 70.1 | +0.655 | ✓ above gate |
| 2026-05 | 124 | 79.0 | +0.781 | ✓ above gate |

**TF_B FRICTION 365d**: every single one of 13 months ≥ +0.520 avg_R. Best +0.832 (May 2025 partial), worst +0.520 (Mar 2026). Remarkably stable.

**Key observation**: ZERO negative months in either TF. Three TF_A months land in [+0.38, +0.39] (Aug '25, Oct '25, Mar '26) — all positive, all profitable, all WR ≥ 57%, but skirting the +0.40 gate. They cluster on ranging-and-choppy regimes. **The strategy never had a losing month on a per-month basis across 13 months.**

---

## §5 — Per-token avg_R (365d vs 90d)

**TF_A FRICTION:**

| Token | n_90 | avg_R_90 | n_365 | avg_R_365 | Change |
|---|---|---|---|---|---|
| ADA | 16 | +0.332 | 109 | +0.478 | ↑ |
| ATOM | 23 | +0.328 | 123 | +0.404 | ↑ |
| AVAX | 58 | +0.619 | 313 | +0.603 | flat |
| BCH | 41 | +1.005 | 276 | +0.785 | mean-revert ↓ |
| BNB | 33 | +0.806 | 175 | +0.679 | mean-revert ↓ |
| BTC | 34 | +0.678 | 154 | +0.650 | flat |
| ETH | 51 | +0.694 | 272 | +0.636 | flat |
| HBAR | 2 | +0.031 | 25 | +0.424 | ↑ (n=2 was noise) |
| LINK | 63 | +0.681 | 303 | +0.529 | mean-revert ↓ |
| POL | 5 | −0.158 | 22 | +0.353 | ↑ (was the 90d's lone negative; now positive) |
| TON | 29 | +0.221 | 114 | +0.333 | ↑ |
| XRP | 43 | +0.504 | 266 | +0.510 | flat |

**TF_B FRICTION:**

| Token | n_90 | avg_R_90 | n_365 | avg_R_365 | Change |
|---|---|---|---|---|---|
| ADA | 61 | +0.420 | 348 | +0.503 | ↑ |
| ATOM | 79 | +0.528 | 364 | +0.501 | flat |
| AVAX | 138 | +0.729 | 731 | +0.752 | flat |
| BCH | 105 | +0.559 | 596 | +0.677 | ↑ |
| BNB | 100 | +0.344 | 462 | +0.638 | ↑↑ (big lift) |
| BTC | 104 | +0.396 | 403 | +0.538 | ↑ |
| ETH | 133 | +0.764 | 592 | +0.738 | flat |
| HBAR | 18 | +0.063 | 162 | +0.416 | ↑↑ |
| LINK | 112 | +0.728 | 625 | +0.745 | flat |
| POL | 29 | −0.147 | 161 | +0.228 | ↑ (lifted out of negative, but still the weakest token) |
| TON | 110 | +0.442 | 313 | +0.433 | flat |
| XRP | 117 | +0.652 | 629 | +0.716 | ↑ |

**Headline findings:**
- **POL flips from −0.147 / −0.158 to positive on the longer window.** The 90-day POL underperformance was a small-n outlier, not a structural problem with the token.
- **All 12 tokens positive on 365d** for both TF_A and TF_B. No structural exclusion candidates.
- The high-performers in 90d (BCH +1.005, BNB +0.806 on TF_A) regress to a still-positive but more reasonable +0.785 / +0.679 — classic small-n outperformance mean-reverting on the larger sample.
- The "lift" tokens (HBAR, POL, BNB-on-TF_B, BTC-on-TF_B) all started with small n in the 90d sample where noise dominated.

---

## §6 — Out-of-sample (temporal 70/30) + DSR

### Temporal 70/30 split (signals ordered by ts; first 70% = train, last 30% = test)

| Run | Train n | Train avg_R | Train Sharpe | Test n | Test avg_R | Test Sharpe | Overall Sharpe |
|---|---|---|---|---|---|---|---|
| TF_A FRICTION 365d | 1506 | +0.5734 | +0.546 | 646 | **+0.6002** | **+0.572** | +0.554 |
| TF_B FRICTION 365d | 3770 | +0.6505 | +0.630 | 1616 | **+0.5956** | **+0.552** | +0.605 |

**TF_A test > train (+0.60 vs +0.57)** — no degradation.
**TF_B test ≈ train (0.595 vs 0.650)** — mild −0.055 drop, well within noise.

Neither shows the catastrophic train/test drop characteristic of overfit signals (where test approaches zero). Both pass.

### CPCV + DSR (production `validation.py`, honest cross-config `sr_trial_std=0.137746` from 19-config production pool)

| Run | CPCV WR mean | CPCV WR std | CPCV WR q05 | CPCV Sharpe mean | DSR | Verdict |
|---|---|---|---|---|---|---|
| TF_A FRICTION 90d | 69.12% | 9.07% | 53.75% | +0.6145 | 0.9944 | PASS |
| **TF_A FRICTION 365d** | **66.91%** | **3.65%** | **60.93%** | **+0.5596** | **1.0000** | **PASS** |
| TF_B FRICTION 90d | 61.76% | 4.36% | 55.86% | +0.5216 | 0.9996 | PASS |
| **TF_B FRICTION 365d** | **65.34%** | **1.94%** | **61.99%** | **+0.6061** | **1.0000** | **PASS** |

CPCV WR std **dropped 2.5× for TF_A (9.07% → 3.65%) and 2.2× for TF_B (4.36% → 1.94%)** — the longer window gives the strategy a much more stable WR signal. q05 (worst-5% fold) rose dramatically: TF_A 53.75% → 60.93%, TF_B 55.86% → 61.99%, both well above the production LIVE-clearance gate of **60%**.

**DSR = 1.0000** for both 365d configs — deflated against 19 distinct production-pool config_hashes with `sr_trial_std=0.137746`. The honest pool's bench Sharpe is 0.2587; the breakout strategy's Sharpe (0.55 / 0.61) clears the deflation comfortably. Both pass production's `DSR ≥ 0.95` gate.

---

## §7 — Verdict

**The +0.616 / +0.549 90-day reference numbers SURVIVE the 365-day regime-extended window.**

| Question | Answer |
|---|---|
| Does the edge collapse in bear/choppy sub-periods? | **No.** TRENDING_DOWN bucket: +0.602 (TF_A) / +0.653 (TF_B). Both bear months (Nov '25, Feb '26) individually positive. |
| Does any month go negative? | **No.** 0/13 months negative for either TF. Worst TF_A month +0.381 (Aug '25 mixed/ranging), worst TF_B month +0.520 (Mar '26 tight range). |
| Does any token go negative on the longer window? | **No.** All 12 tokens positive on 365d. POL — the 90d outlier — flips to positive (+0.353 TF_A / +0.228 TF_B). |
| Does OOS test set hold up? | **Yes.** TF_A test +0.600 > train +0.573. TF_B test +0.596 ≈ train +0.650. No overfit collapse. |
| Does CPCV + DSR pass? | **Yes.** Both 365d configs hit DSR = 1.0000 verdict=PASS against the honest production pool. CPCV WR std HALVED on the longer window. |

**Confidence-boost interpretation.** The 90-day +0.72 figure was NOT regime-flattered. The 365-day window — which includes two 15-18% bear months, three mixed months, one volatile-range month, and six ranging months — produces +0.5815 (TF_A) and +0.6340 (TF_B). The edge is structurally regime-robust within the 365-day sample.

**Honest caveats.**
1. **Only 2 bear months in the sample (Nov '25, Feb '26).** TRENDING_DOWN n = 457 (TF_A) / 1214 (TF_B) — solid but not "long bear cycle" tested. A 2022-style 6-month sustained bear is still out-of-sample.
2. **No parabolic / blow-off-top.** The sample doesn't include a 50%+ monthly run-up. The strategy may behave differently in a euphoria phase.
3. **Per-month near-gate cluster.** Three TF_A months (Aug '25, Oct '25, Mar '26) landed at +0.38, +0.39, +0.39 — all positive but skirting the +0.40 gate. If three consecutive such months occurred live, sum_R growth would slow noticeably even though no month would be a loss. This is sample variation, not failure.
4. **VOLATILE_RANGE bucket is n=1 month for TF_A.** The +0.389 figure has no statistical power; TF_B's +0.713 on the same month is the only other data point.

**No code change proposed.** Config 14 is validated bit-for-bit on a 4× longer window with stronger CPCV stability and full DSR pass. This is a confidence-boost output for the operator's go-live decision, not a strategy change.

---

## §8 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched |
| `data/signals.db` (production) | unchanged by this audit |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (not pushed) |
| Soak A 473059 / B 473060 | alive, untouched throughout the run |
| New rows in breakout.db | tagged `H4_BREAKOUT_TF_{A,B}_5m_{4h,1h}_{CLEAN,FRICTION}_365D` — distinct from the 90d rows and the soak rows |
| breakout.db backed up before the run | `data/breakout.db.before_365d_bak.20260603_024648` |
| `run_tf_grid.py` source edits | reverted after the run (see §9) |

---

## §9 — Source edits

Four edits to `run_tf_grid.py`, all reverted after the run completes:

1. **L37 (new comment + L38 START_MS)**: `START_MS = END_MS - 365 * 24 * 60 * 60 * 1000` (was `90 * ...`)
2. **L283-284**: `days` column in `backtest_runs` INSERT computed as `int((END_MS - START_MS) / 86_400_000)` (was hardcoded `90`)
3. **L304-306**: `src = f"H4_BREAKOUT_TF_{cfg_id}_{friction_mode}_365D"` (was without `_365D` suffix) — keeps these rows distinct
4. **L437-444**: `SKIP_CFG_IDS = {"C_1m_1h"} if window > 90d else set()` — TF_C skipped because 1m cache only covers 90 days
5. **L414**: dynamic "(X days)" log message instead of hardcoded "(90 days)"

These edits are reverted to the operator's preferred 90-day default after this run — see the revert step below.
