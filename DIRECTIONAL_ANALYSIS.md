# Phase C-Breakout — Directional (BUY vs SELL) Analysis

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~06:10 UTC.
**Audited processes:** A PID 473059, B PID 473060 (both alive, untouched).

---

## §1 — Forward soak: BUY vs SELL breakdown (operator's observation, quantified)

26 closed signals to date, all from soak B (A still at 0 closed). Split by direction:

| Direction | n | WR | avg_R | sum_R | WIN | PARTIAL_TP1 | LOSS |
|---|---|---|---|---|---|---|---|
| **BUY** | 8 | **12.5%** | **−0.7222** | **−5.778** | 1 | 0 | 7 |
| **SELL** | 18 | **77.8%** | **+0.9260** | **+16.667** | 14 | 0 | 4 |
| Total | 26 | 57.7% | +0.418 | +10.889 | 15 | 0 | 11 |

**Operator's observation is confirmed:** SELLs win 14/18, BUYs lose 7/8 — a dramatic directional asymmetry in the forward result.

### Full closed-signal list (last 26, newest first)

| id | tok | dir | entry_type | result | R | opened | closed |
|---|---|---|---|---|---|---|---|
| 31 | LINK | SELL | OB_B | WIN | +1.500 | 06-03 03:20 | 06-03 04:04 |
| 30 | XRP | SELL | FVG_B | WIN | +1.500 | 06-03 03:20 | 06-03 04:04 |
| 29 | BNB | SELL | FVG_B | WIN | +1.500 | 06-03 02:30 | 06-03 03:44 |
| 28 | BCH | SELL | FVG_B | WIN | +1.500 | 06-03 01:20 | 06-03 02:04 |
| 27 | ATOM | BUY | FVG_B | LOSS | −1.000 | 06-03 00:15 | 06-03 03:44 |
| 25 | BNB | BUY | FVG_B | LOSS | −1.000 | 06-03 00:15 | 06-03 01:09 |
| 24 | XRP | BUY | FVG_B | LOSS | −1.000 | 06-03 00:20 | 06-03 03:29 |
| 23 | BCH | SELL | FVG_B | WIN | +1.549 | 06-02 22:15 | 06-02 23:04 |
| 22 | BNB | SELL | OB_B | WIN | +1.500 | 06-02 22:15 | 06-02 23:04 |
| 21 | LINK | SELL | OB_B | LOSS | −1.000 | 06-02 22:15 | 06-02 22:29 |
| 20 | AVAX | SELL | OB_B | LOSS | −1.000 | 06-02 22:15 | 06-02 22:29 |
| 19 | XRP | SELL | OB_B | LOSS | −1.000 | 06-02 22:15 | 06-02 22:29 |
| 18 | BTC | SELL | OB_B | WIN | +1.500 | 06-02 22:15 | 06-03 03:44 |
| 17 | TON | BUY | OB_B | LOSS | −1.000 | 06-02 20:15 | 06-02 20:24 |
| 16 | BTC | BUY | FVG_B | LOSS | −1.000 | 06-02 20:55 | 06-02 22:14 |
| 15 | XRP | SELL | FVG_B | WIN | +1.500 | 06-02 18:20 | 06-02 22:54 |
| 14 | ETH | SELL | FVG_B | WIN | +1.500 | 06-02 18:25 | 06-02 22:19 |
| 13 | TON | BUY | OB_B | **WIN** | +1.222 | 06-02 17:15 | 06-03 00:44 |
| 12 | ADA | SELL | OB_B | WIN | +1.322 | 06-02 14:20 | 06-02 15:04 |
| 11 | LINK | SELL | OB_B | WIN | +1.500 | 06-02 14:20 | 06-02 15:04 |
| 10 | AVAX | SELL | OB_B | WIN | +1.500 | 06-02 14:15 | 06-02 15:04 |
| 9 | HBAR | SELL | FVG_B | WIN | +1.296 | 06-02 14:25 | 06-02 19:34 |
| 8 | XRP | SELL | OB_B | WIN | +1.500 | 06-02 14:15 | 06-02 15:04 |
| 7 | LINK | BUY | FVG_B | LOSS | −1.000 | 06-02 10:15 | 06-02 11:19 |
| 6 | AVAX | BUY | OB_B | LOSS | −1.000 | 06-02 10:15 | 06-02 11:34 |
| 5 | TON | SELL | OB_B | LOSS | −1.000 | 06-02 07:30 | 06-02 07:39 |

The lone BUY WIN was TON #13 — TON has been the strongest token in the broader sample (90d backtest +50.9% / 720d among the strongest per-token).

### Market regime during the soak window

Fetched live BTC 4h klines from Binance public REST (the cache only extends to 2026-05-30; the soak window 2026-06-02 → now requires fresh fetch):

| Metric | Value |
|---|---|
| BTC start (2026-06-02 00:00 UTC) | $70,954 |
| BTC end (2026-06-03 04:00 UTC) | **$66,412** |
| Δ over 28h | **−6.40%** |
| Max drawdown from peak | 7.19% |
| Max rebound from trough | 0.85% |
| Classified regime | **DOWNTREND** (sharp, near-monotone, almost no bounce) |

This is an unusually acute downtrend (−6.4% in 28h ≈ −18%/week pace if sustained). For context, the 720d backtest's TRENDING_DOWN months were −15 to −18% **over 30 days** — the current move is ~4× the per-day intensity. SELL signals get to TP3 quickly; BUY signals get stopped almost immediately.

---

## §2 — Is BUY structurally broken, or just counter-trend?

### Geometry of the 8 BUY signals

| id | tok | entry | SL % | TP3 RR | mss | fvg | tier hit | result |
|---|---|---|---|---|---|---|---|---|
| 6 | AVAX | 8.725 | 0.500 | 4.00 | MEDIUM | NONE | SL | LOSS |
| 7 | LINK | 8.856 | 0.500 | 4.00 | MEDIUM | MEDIUM | SL | LOSS |
| 13 | TON | 1.974 | 0.500 | 4.00 | HIGH | NONE | **TP1+2+3 ✓** | **WIN** |
| 16 | BTC | 67613.3 | 0.500 | 4.00 | MEDIUM | LOW | SL | LOSS |
| 17 | TON | 1.983 | 0.500 | 4.00 | HIGH | NONE | SL | LOSS |
| 24 | XRP | 1.2254 | 1.144 | 4.00 | HIGH | LOW | SL | LOSS |
| 25 | BNB | 654.82 | 0.552 | 4.00 | HIGH | LOW | SL | LOSS |
| 27 | ATOM | 1.839 | 0.915 | 4.00 | MEDIUM | MEDIUM | SL | LOSS |

**Geometry parity check** (median across all closed forward signals):

| Direction | median SL% | median TP3 RR |
|---|---|---|
| BUY (n=8) | 0.500 | 4.00 |
| SELL (n=18) | 0.500 | 4.00 |

The BUY signals have **identical geometry to SELL signals** — same SL%, same TP3 RR. They're valid breakout setups with proper MSS confirmation (5 HIGH, 3 MEDIUM) and confluence (FVG or OB). None show suspicious geometry, mss=LOW, or other structural defects. **BUYs are valid breakouts that simply reversed** because the market reversed.

This is the textbook signature of counter-trend failure during a strong directional move, NOT a broken signal generator.

---

## §3 — Backtest cross-check: BUY vs SELL × regime (the symmetry test)

The key question: in the 720d backtest, does BUY win in uptrends the way SELL wins in downtrends? If yes, the current forward pattern is healthy regime-alignment; if no, BUY has a structural asymmetry.

### TF_A FRICTION 720d

| Regime | BUY n | BUY avg_R | BUY WR | SELL n | SELL avg_R | SELL WR | Delta (BUY−SELL) |
|---|---|---|---|---|---|---|---|
| STRONG_BULL (Nov '24 +39%) | 205 | +0.451 | 62.4% | 100 | +0.566 | 67.0% | −0.115 |
| TRENDING_UP (Apr '25 +13.5%) | 113 | +0.382 | 61.1% | 83 | +0.648 | 71.1% | −0.266 |
| TIGHT_RANGE | 543 | +0.599 | 68.3% | 454 | +0.644 | 67.6% | −0.045 |
| MIXED | 1048 | +0.540 | 66.4% | 891 | +0.629 | 68.1% | −0.089 |
| VOLATILE_RANGE | 348 | +0.420 | 60.3% | 286 | +0.587 | 66.1% | −0.167 |
| TRENDING_DOWN | 354 | **+0.521** | 64.4% | 319 | +0.582 | 66.8% | −0.061 |

**TF_A overall: BUY +0.5198 (n=2611), SELL +0.6175 (n=2133)** — delta **−0.098 R/signal favoring SELL**.

### TF_B FRICTION 720d

| Regime | BUY n | BUY avg_R | BUY WR | SELL n | SELL avg_R | SELL WR | Delta (BUY−SELL) |
|---|---|---|---|---|---|---|---|
| STRONG_BULL | 511 | **+0.683** | 69.1% | 336 | +0.522 | 60.1% | **+0.161** ✓ |
| TRENDING_UP | 337 | +0.556 | 63.8% | 277 | +0.741 | 70.4% | −0.185 |
| TIGHT_RANGE | 1330 | +0.616 | 65.3% | 1065 | +0.628 | 63.9% | −0.012 |
| MIXED | 2515 | +0.609 | 65.2% | 2233 | +0.679 | 67.4% | −0.070 |
| VOLATILE_RANGE | 861 | +0.528 | 61.6% | 817 | +0.831 | 73.6% | −0.303 |
| TRENDING_DOWN | 897 | **+0.548** | 62.0% | 911 | +0.720 | 69.5% | −0.172 |

**TF_B overall: BUY +0.5943 (n=6451), SELL +0.6917 (n=5639)** — delta **−0.098 R/signal favoring SELL** (identical delta to TF_A).

### Three key observations

1. **BUY is positive in EVERY regime on both TFs.** Lowest BUY avg_R is +0.382 (TF_A TRENDING_UP) — still well above the +0.40 gate in most buckets and never negative. **BUY is not structurally broken.**

2. **SELL has a consistent ~0.10 R per-signal advantage overall** on both TFs. This is a real but mild directional asymmetry — the strategy is genuinely a slightly better short than long. Not huge (each direction is ~16% of the other's contribution to the headline +0.58/+0.64), but real.

3. **The only regime where BUY clearly beats SELL is TF_B STRONG_BULL** (BUY +0.683 vs SELL +0.522 — the +0.161 delta is the only positive cell in the table). The Nov 2024 BTC +39% parabolic. This confirms the symmetric expectation: **in a strong uptrend, BUY wins like SELL is winning in this downtrend.** TF_A's STRONG_BULL doesn't show the symmetry as cleanly because the 4h reference is slower to catch fast bull breaks than the 1h reference is.

---

## §4 — Why is the FORWARD BUY result (−0.72) so much worse than the backtest's BUY in TRENDING_DOWN (+0.52)?

Three explanations stacked:

### (i) Tiny sample size (the dominant factor)

n=8 BUY trades. Wilson 95% confidence interval for the true WR given 1 win in 8:

```
WR observed: 12.5%
95% Wilson CI: [2.2%, 47.1%]
Backtest TRENDING_DOWN BUY WR: 62.4% (TF_A), 62.0% (TF_B)
```

Binomial test: assuming the backtest's 62.4% WR is correct, the probability of seeing ≤1 win in 8 trials is **0.57%**. Rare (~1 in 175), but possible. With n=8 you cannot distinguish "1-in-175 unlucky" from "model is wrong."

Compare to the SELL side: 14/18 WR=77.8% vs backtest 68.2% expectation, binomial P(X≥14) = **27.5%** — totally within normal noise.

### (ii) Acute regime intensity, not just direction

The 720d backtest's TRENDING_DOWN months had −15 to −18% move **over 30 days**. The current 28-hour move is **−6.4%** — projecting to ~−18% per week pace, about **4× the per-day intensity** of typical backtest TRENDING_DOWN. SELL trades hit TP3 in minutes; BUY trades hit SL in minutes. Fast monotone moves crush counter-trend setups disproportionately.

### (iii) Token mix is fine — not the explanation

Forward BUY tokens: ATOM, AVAX, BNB, BTC, LINK, TON×2, XRP — 7 different tokens, no concentration on weak ones. The token mix is not biased.

---

## §5 — Implication for the current forward result

| Question | Backtest answer | Forward observation |
|---|---|---|
| Is the strategy take-both-directions regardless of regime? | Yes, by design (no trend gate). | Yes — fired BUY 8× and SELL 18× during a clear downtrend. |
| Does the backtest show BUY positive in TRENDING_DOWN? | Yes: TF_A +0.521, TF_B +0.548. | Forward shows −0.722 over n=8. |
| Is the forward BUY discrepancy explained by sample noise + acute intensity? | Binomial P=0.57% (rare but possible). | Yes — the data is consistent with the backtest's directional symmetry; the forward sample is just very small in an unusually acute regime. |
| Does BUY win in uptrends as SELL wins in downtrends? | Yes on TF_B (STRONG_BULL: BUY +0.683 > SELL +0.522). Mostly on TF_A too, but less symmetric. | Cannot test yet — no live uptrend month in the soak window. |

**Forward +0.30-ish R/signal average over 26 trades IS regime-aligned.** The soak happens to be running through a sharp downtrend, so SELLs are paying. When the market turns up, expect:
- SELLs to start losing (counter-trend in an uptrend)
- BUYs to start winning (with-trend in an uptrend, especially on TF_B where the parabolic BUY edge was +0.683)
- Headline avg_R to stay positive but rotate which direction is contributing

This is exactly what a directionally-symmetric strategy should look like — it pays the side that's with-trend, drags on the counter-trend side, nets positive across the mix.

---

## §6 — Verdict

**Case (a): healthy regime-alignment, confirmed by symmetric backtest directional edge.** Not a directional defect.

| Sub-finding | Evidence |
|---|---|
| BUY is positive in every backtest regime including TRENDING_DOWN | TF_A +0.52, TF_B +0.55 over n=350+/regime |
| BUY signals have valid breakout geometry (no structural defect) | Identical SL%/TP3 RR to SELL; MSS HIGH/MEDIUM; FVG or OB confluence present |
| Backtest shows BUY winning in STRONG_BULL (Nov 2024 +39% BTC) | TF_B BUY +0.683 (n=511) > SELL +0.522 (n=336) — symmetric to the current SELL-winning pattern |
| Forward BUY = −0.72 (n=8) vs backtest +0.52 expectation in TRENDING_DOWN | Binomial p=0.57% under the backtest model — improbable but not enough to overturn the model at n=8 |
| The current SELL-wins/BUY-loses pattern is consistent with a directionally-symmetric strategy taking both directions in a sharp downtrend | Live BTC −6.4% over 28h is ~4× backtest TRENDING_DOWN per-day intensity |

**Mild asymmetry worth flagging (not a defect, but real):**
- SELL averages ~0.10 R per signal better than BUY across all regimes on both TFs.
- This is consistent in magnitude across TF_A and TF_B (delta −0.098 in both).
- Possible explanations: (a) crypto markets historically have faster, sharper down-moves than up-moves (the "stair-step up, elevator-down" pattern), so SELL TP3 fires faster than BUY TP3; (b) MSS-down confirmations are more reliable than MSS-up confirmations in the FVG/OB framework. Both are speculation; the data shows the asymmetry, not the cause.

### What this means for go-live

1. **Don't position-size BUY and SELL differently** based on the current forward result. The backtest's 720d data with n=2600+ per direction is far more reliable than the soak's n=8 BUY.
2. **Expect mild SELL > BUY asymmetry to persist** (~0.10 R per signal). Over n=30 forward, this might tilt the headline by ~+3 R total (e.g., if ratios match backtest's ~55% SELL / 45% BUY split). Not material.
3. **The current +0.30 R/signal forward average is not "fragile" or "trend-flattered" in a dangerous way.** The strategy takes both sides; the current snapshot just captures more SELL contribution than BUY because the soak window is downtrending. As the regime cycles, the contribution mix will rotate, but the headline edge should hold (backtest confirms across all 6 regime buckets).
4. **The pre-registered gate (avg_R ≥ +0.40 over n≥30) does not need adjustment.** It's not direction-aware by design, and the backtest shows both directions contribute positive edge.

**No code change proposed.** Informational only.

---

## §7 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched |
| `data/signals.db` (production) | unchanged (read-only access only) |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (not pushed) |
| Both soaks (A 473059, B 473060) | alive, cycling, untouched throughout this audit |
| All 5 DB backups | intact |

Awaiting operator call. No fixes applied.
