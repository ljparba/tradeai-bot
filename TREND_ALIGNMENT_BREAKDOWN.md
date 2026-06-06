# TREND_ALIGNMENT_BREAKDOWN — descriptive, causal (read-only)

**Bottom line: trend alignment DOES carry information — but it confirms the failed-regime-
filter lesson, not a filter case.** On the primary TF_B, WITH-trend signals out-earn
AGAINST-trend by ~+0.09–0.11 R in-sample and **~+0.05–0.07 R out-of-sample** (the ordering
*holds* OOS, and holds *within each regime* — unlike the MSS-quality tag, which was noise).
**BUT the AGAINST-trend bucket is still solidly net-profitable (+0.30–0.32 R)** — counter-
trend signals make money, just less. So the signal is "with-trend earns MORE," **not**
"counter-trend loses." Filtering AGAINST would cut ~40% of signals averaging +0.30 R — the
exact failure mode of the regime filter (+0.575 R counter-trend, −28% sum_R). On TF_A the
effect is weak/unstable (no in-sample separation). **Descriptive only — no filter proposed,
nothing changed.**

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B, in-memory (NO DB writes).
Soaks A=515231, B=515230 + fade=512666 alive and untouched.

### Trend definition (causal, stated explicitly)
Per ref TF (1H, 4H) on **the token's own bars**: `EMA period = 50`, `slope lookback = 10 bars`.
At the most recent bar **fully closed BEFORE the signal's entry time** (no forward/outcome bars):
**UP** if `close > EMA AND EMA[i] > EMA[i−10]`; **DOWN** if `close < EMA AND EMA[i] < EMA[i−10]`;
**NEUTRAL** otherwise. Alignment: **WITH** = BUY&UP or SELL&DOWN; **AGAINST** = BUY&DOWN or
SELL&UP; **NEUTRAL** = trend flat. (Config 14 does not tag this — computed retroactively, causally.)

---

## 1–2. Per-alignment breakdown (720d friction)

### TF_B (5M/1H) — PRIMARY (n=12090)
**1H-trend:**
| bucket | n | % | WR | avg_R | sum_R |
|--------|----|----|-----|-------|-------|
| WITH | 5377 | 44.5% | 72.2% | **+0.4152** | +2233 |
| AGAINST | 5189 | 42.9% | 68.7% | **+0.3074** | +1595 |
| NEUTRAL | 1524 | 12.6% | 71.6% | +0.3790 | +578 |

**4H-bias:**
| bucket | n | % | WR | avg_R | sum_R |
|--------|----|----|-----|-------|-------|
| WITH | 5099 | 42.2% | 72.2% | **+0.4108** | +2095 |
| AGAINST | 5432 | 44.9% | 69.3% | **+0.3231** | +1755 |
| NEUTRAL | 1559 | 12.9% | 70.1% | +0.3562 | +555 |

→ WITH > NEUTRAL > AGAINST on both. WITH−AGAINST gap = **+0.108 (1H)**, **+0.088 (4H)**.
**Every bucket is net-positive** (AGAINST ≥ +0.307).

### TF_A (5M/4H) (n=4744)
**1H-trend:** WITH +0.3530 (n2003) · AGAINST +0.3222 (n2175) · NEUTRAL +0.3423 (n566)
**4H-bias:** WITH +0.3437 (n1989) · AGAINST +0.3151 (n2152) · **NEUTRAL +0.3981** (n603)

→ Much weaker. WITH−AGAINST gap only ~+0.03; on 4H **NEUTRAL is the highest** bucket
(non-monotonic). Every bucket still net-positive (AGAINST ≥ +0.315).

---

## 3. Combined 1H + 4H (does aligning with BOTH matter more?)

### TF_B (primary)
| bucket | n | % | avg_R |
|--------|----|----|-------|
| with-both | 3710 | 30.7% | **+0.4362** |
| with-1H-only | 1667 | 13.8% | +0.3687 |
| with-4H-only | 1389 | 11.5% | +0.3432 |
| against-both | 3711 | 30.7% | **+0.3023** |
| other (neutral-mix) | 1613 | 13.3% | +0.3558 |

→ Clean gradient: **with-both (+0.436) > one-only (~+0.35) > against-both (+0.302)**. Aligning
with both is the best bucket; gap with-both − against-both = **+0.134**. **against-both is still
+0.30 R net-profitable.**

### TF_A
with-both +0.3557 · with-1H-only +0.3470 · with-4H-only +0.3154 · against-both +0.3092 ·
neutral-mix **+0.3827** (highest). Gradient is shallow (~+0.046 with-both vs against-both) and
the neutral-mix bucket tops it — no clean ladder.

---

## 4. Confound + stability

### Confound — alignment × REGIME (does it hold *within* regime, or is it just a regime artifact?)
**TF_B 1H, avg_R per regime:**
| | BEAR | BULL | RANGE |
|---|---|---|---|
| WITH | +0.478 (n1661) | +0.389 (n1935) | +0.385 (n1781) |
| AGAINST | +0.304 (n1753) | +0.283 (n1694) | +0.335 (n1742) |
| NEUTRAL | +0.421 (n507) | +0.332 (n521) | +0.386 (n496) |

→ **WITH > AGAINST holds inside EVERY regime bucket** (BEAR +0.478 vs +0.304; BULL +0.389 vs
+0.283; RANGE +0.385 vs +0.335). So the WITH−AGAINST gap is **not merely a regime artifact** —
it survives controlling for regime (strongest in BEAR = trend-following shorts). This is the
key difference from the MSS-quality result.

### Stability — OOS 70/30 (does WITH > AGAINST hold out-of-sample?)
**TF_B 1H:** WITH train +0.4308 → **test +0.3788** · AGAINST train +0.3082 → **test +0.3053** ·
NEUTRAL +0.4001 → +0.3299.
→ **WITH > AGAINST HOLDS OOS** (test 0.379 vs 0.305, gap +0.074). The gap shrinks (+0.123→+0.074)
but the direction is preserved — the most OOS-robust signal seen across these descriptive passes.

**TF_B 4H:** WITH +0.4335 → +0.3580 · AGAINST +0.3197 → **+0.3309** · NEUTRAL +0.3741 → +0.3147.
→ WITH > AGAINST holds in sign (0.358 vs 0.331) but the gap nearly vanishes OOS (+0.114 → **+0.027**);
AGAINST actually *rises* out-of-sample. The 4H edge is fragile.

**TF_A 1H:** WITH +0.3248 → +0.4190 · AGAINST +0.3203 → +0.3268 · NEUTRAL +0.3359 → +0.3571.
**TF_A 4H:** WITH +0.3163 → +0.4074 · AGAINST +0.3139 → +0.3181 · NEUTRAL +0.4063 → +0.3792.
→ On TF_A there is **no in-sample separation** (WITH ≈ AGAINST ≈ NEUTRAL in train); a WITH gap
only appears in the test split. With no train signal, the TF_A "edge" is not stable/real.

### Cross-check vs the regime-filter finding
The AGAINST-trend bucket is **net-profitable in every cut** (TF_B 1H +0.307, 4H +0.323,
against-both +0.302; TF_A +0.315–0.322; OOS test AGAINST +0.305/+0.331). This is fully
consistent with the prior regime-filter finding (counter-trend +0.575 R; filtering cut
sum_R −28%). The explicit-trend view shows the **same thing**, not something different:
counter-trend signals make money — they just make *less* than with-trend.

---

## 5. Interpretation (descriptive only — explicitly NOT a filter proposal)

**Does trend alignment discriminate performance, and does it hold OOS?**
- **Yes, on TF_B (1H especially): WITH-trend earns ~+0.09–0.11 R more than AGAINST in-sample,
  ~+0.07 R OOS, and the ordering holds within every regime.** This is a *real, modest* signal —
  notably more robust than the MSS-quality tag (which was pure noise / OOS-flipping).
- The 4H edge is weaker and nearly disappears OOS (+0.027). The whole effect is **weak/absent
  on TF_A** (no in-sample separation).

**Heavy caveats (why this is orientation, not action):**
- (a) **It may not generalize:** strong on TF_B 1H, fragile on 4H, absent on TF_A.
- (b) **It echoes the already-FAILED regime filter.** The information is "with-trend earns more,"
  NOT "counter-trend loses." AGAINST is +0.30 R net-profitable everywhere.
- (c) **Filtering AGAINST would cut ~40–45% of signals averaging +0.30 R** — a large slice of
  positive sum_R (with-trend +2233 R but against-trend still +1595 R on B-1H). That is precisely
  why the regime filter cut sum_R −28%. Removing profitable trades to raise avg_R is the trap.
- (d) **Acting would require a separate pre-registered OOS experiment** with its own decision
  rule (like the TP-geometry test) — not a change inferred from this descriptive pass.

**No 1H/4H trend or bias gate is recommended.** Trend alignment carries *real but modest*
information on the primary timeframe (more R when aligned), but the counter-trend bucket is
itself profitable, so this is not a filtering case — it is the same lesson the regime filter
already taught. Reporting what the data shows; proposing nothing.

---

**Isolation honored:** read-only causal analysis; in-memory (0 DB rows written); both soaks
(A 515231, B 515230) + fade (512666) alive and untouched; signals.db + Run-3704 pin unchanged;
main untouched; branch not pushed. No filter, no change, no recommendation. STOP.
