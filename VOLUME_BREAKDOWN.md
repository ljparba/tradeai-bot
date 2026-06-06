# VOLUME_BREAKDOWN — descriptive, causal (read-only)

**Bottom line: breakout-bar volume DOES carry information — and it is INVERTED vs the classic
thesis.** Across both timeframes, **lower** MSS-bar volume → **higher** avg_R, monotonically,
and the ordering **holds out-of-sample**. On primary TF_B: LOW-vol +0.469, NORMAL +0.421,
**HIGH-vol +0.297**. So "breakouts need volume" is *not* supported here — high-volume breakouts
under-perform (plausibly climactic/exhaustion moves that mean-revert). **BUT HIGH-vol is still
+0.30 R net-profitable and is the majority of signals (53%) and the single largest sum_R bucket
(+1902 R)** — so this is the avg_R-vs-sum_R / regime-filter trap again, not a filter case.
**Descriptive only — no filter proposed, no signal blocked, nothing changed.**

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B, in-memory (NO DB writes; volume
cached to files). Every signal that fired stays in the analysis — only grouped by volume.
Soaks A=515231, B=515230 + fade=512666 alive and untouched.

### Volume definition (causal, stated explicitly)
`vol_ratio = volume[MSS bar] / mean(volume of the prior 20 5m bars before the MSS bar)`.
MSS bar = the 5m confirmation bar (entry bar − 1). Uses only the MSS bar + 20 bars before it —
**no forward/outcome bars**. Buckets: **LOW < 0.8 · NORMAL 0.8–1.5 · HIGH > 1.5**. (The 720d 5m
price cache had no volume; volume was fetched fresh from Binance for this window. Every signal
got a causal ratio — vol-known n = total n.)

---

## 1. Per-volume-bucket breakdown (720d friction)

### TF_B (5M/1H) — PRIMARY (n=12090)
| bucket | n | % | WR | avg_R | sum_R | outcome [WIN/PT2/PT2_T1/PT1/LOSS] |
|--------|----|----|-----|-------|-------|----|
| LOW (<0.8) | 2245 | 18.6% | 76.2% | **+0.4685** | +1052 | 841/1/557/351/494 |
| NORMAL (0.8–1.5) | 3446 | 28.5% | 74.3% | **+0.4213** | +1452 | 1158/2/811/640/833 |
| HIGH (>1.5) | 6399 | 52.9% | 66.7% | **+0.2972** | **+1902** | 1716/5/1343/1263/2054 |

### TF_A (5M/4H) (n=4744)
| bucket | n | % | WR | avg_R | sum_R |
|--------|----|----|-----|-------|-------|
| LOW | 947 | 20.0% | 71.5% | **+0.3952** | +374 |
| NORMAL | 1401 | 29.5% | 70.2% | **+0.3832** | +537 |
| HIGH | 2396 | 50.5% | 65.8% | **+0.2883** | **+691** |

**Pattern: clean MONOTONIC but INVERTED — LOW > NORMAL > HIGH on both TFs.** avg_R falls as
breakout-bar volume rises (B gap LOW−HIGH = **+0.171**; A = +0.107). WR follows the same
inversion (B: 76.2% → 74.3% → 66.7%). HIGH-vol shows proportionally more LOSS and PT2_T1
(wider, more volatile ranges trail out before TP3). **Note: HIGH-vol still has the LARGEST
sum_R** (+1902 on B) purely because it is the biggest bucket (53%).

---

## 2. Confound checks

**Vol × DIRECTION — direction effect present but vol pattern survives.** SELL > BUY in every
bucket (e.g. B LOW: BUY +0.443 / SELL +0.503; HIGH: BUY +0.257 / SELL +0.341). But within each
direction, HIGH is still the worst — so the inversion is not just a direction-mix artifact.

**Vol × CONFLUENCE (FVG/OB) — partly concentrated in OB.** HIGH-vol OB is especially weak
(B HIGH OB **+0.076** vs FVG +0.358; A HIGH OB +0.186 vs FVG +0.427). The HIGH-vol penalty is
heaviest on OB-confluence trades. **CAVEAT (FVG_MITIGATION_CHECK.md): known FVG/OB label drift —
the confluence split is itself biased, so read this as directional only.**

**Vol × REGIME — NOT a regime artifact.** HIGH is the worst bucket inside *every* regime
(B HIGH: BEAR +0.328 / BULL +0.259 / RANGE +0.308 — all well below LOW/NORMAL's ~0.44–0.49).
The inversion holds controlling for regime.

**Vol × TOKEN — mild mix difference.** HIGH-vol leans slightly more large-cap (B HIGH includes
ETH n756), LOW/NORMAL spread across alts, but the same top tokens (AVAX/LINK/BCH/XRP) appear in
all buckets. Not a token artifact.

---

## 3. Stability (OOS 70/30) — does the inversion hold out-of-sample?

### TF_B
| bucket | train avg_R | test avg_R |
|--------|-------------|------------|
| LOW | +0.4935 | +0.4100 |
| NORMAL | +0.4051 | +0.4591 |
| HIGH | +0.3142 | **+0.2576** |

### TF_A
| bucket | train avg_R | test avg_R |
|--------|-------------|------------|
| LOW | +0.3841 | +0.4209 |
| NORMAL | +0.3541 | +0.4510 |
| HIGH | +0.2792 | **+0.3093** |

→ **HIGH-vol is the worst bucket in BOTH train and test on BOTH timeframes** — the inversion is
**OOS-robust** (the most consistent of all the descriptive breakdowns: MSS quality flipped OOS;
trend held only on B; volume holds on both). LOW vs NORMAL swap rank between splits (NORMAL edges
LOW in the test sets), but both sit clearly *above* HIGH every time. The signal is "HIGH-vol
under-performs," robustly.

---

## 4. Interpretation (descriptive only — explicitly NOT a filter proposal)

**Does breakout-bar volume discriminate performance, and does it hold OOS?**
- **Yes — and inverted.** Lower MSS-bar volume → higher avg_R, monotonically, OOS-robust on
  both timeframes and within every regime. The classic "breakouts need volume" thesis is **not**
  supported by this data; the opposite holds (high-volume breakouts plausibly being late /
  climactic / exhaustion moves that mean-revert — stated descriptively, not as a proven mechanism).

**Heavy caveats (why this is orientation, not action):**
- (a) **HIGH-vol is still net-profitable (+0.30 R)** and is **53% of all signals** and the
  **largest sum_R contributor (+1902 R on B)**. Filtering it would keep the best *avg_R* while
  discarding the most *total profit* — the avg_R-vs-sum_R trap, and the same failure mode as the
  regime filter (which cut sum_R −28%).
- (b) **Crypto volume is noisy and exchange-dependent** — this is single-exchange (Binance) 5m
  volume; the ratio is sensitive to the lookback and to per-token/listing-age volume regimes
  (POL/TON have shorter histories). A different volume definition could move the cuts.
- (c) The penalty is **confounded with confluence** (heaviest on HIGH-vol OB, itself label-drift-biased).
- (d) **Acting would require a separate pre-registered OOS experiment** with its own decision
  rule (like the TP-geometry test) — not a change inferred from this descriptive pass.

**No volume filter is recommended or proposed.** Volume carries *real, OOS-robust, inverted*
information (low-vol breakouts out-earn high-vol ones), which is genuinely interesting and
counter to the textbook thesis — but because the under-performing HIGH bucket is still profitable
and carries the majority of signals and total R, this is not a filtering case. Reporting what the
data shows; proposing nothing, blocking nothing.

---

**Isolation honored:** read-only descriptive bucketing; in-memory (0 DB rows written; volume
fetched to cache files, not the DB); both soaks (A 515231, B 515230) + fade (512666) alive and
untouched; signals.db + Run-3704 pin unchanged; main untouched; branch not pushed. No filter, no
change, no signal blocked. STOP.
