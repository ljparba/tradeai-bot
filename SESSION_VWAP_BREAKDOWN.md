# SESSION_VWAP_BREAKDOWN — descriptive, causal (read-only)

**Bottom line:**
- **NY session is NOT a standout edge.** On primary TF_B it sits only +0.042 above the overall
  mean and **decays OOS to ~the mean** (train +0.425 → test +0.362). The genuinely weak session
  is **ASIAN** (+0.285) — but it is still net-profitable. LONDON is the *best* session, not NY.
  The forward-soak "Asian −8→+7.32 flip" was burst-driven; the 720d view shows Asian is simply
  the structurally weakest (yet profitable) session.
- **VWAP-relationship carries real, OOS-robust information — and it is INVERTED.** Signals
  **AGAINST** VWAP (BUY *below* VWAP / SELL *above* VWAP) **out-earn** VWAP-aligned ones
  (B: +0.437 vs +0.347; A: +0.562 vs +0.291), the gap holds within each direction, holds
  out-of-sample, and is **not** confounded with volume. The stated "aligned should outperform"
  hypothesis is *rejected* — the opposite holds (mirrors the inverted volume finding).
- **Neither is a filter case:** every session is profitable and NY is only ~22% of signals;
  VWAP-aligned is still +0.35 R and is **80.8%** of signals / the bulk of sum_R. Filtering to
  NY-only or AGAINST-only is the avg_R-vs-sum_R / regime-filter trap. **Descriptive only — no
  filter proposed, no signal blocked, nothing changed.**

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B, in-memory (NO DB writes).
Soaks A=515231, B=515230 + fade=512666 alive and untouched.

### Definitions (causal, stated explicitly)
- **VWAP — SESSION-ANCHORED at 00:00 UTC daily reset.** At each 5m bar `typical=(H+L+C)/3`;
  running `VWAP = Σ(typical·vol) / Σ(vol)` from the 00:00 anchor **up to and including the entry
  bar** (no forward bars). **VWAP is anchor-sensitive** — a London-open or weekly anchor could
  move these results; flagged. ALIGNED = (BUY & entry>VWAP) or (SELL & entry<VWAP); AGAINST = opposite.
- **Session** from entry-ts UTC hour: ASIAN 00–08 · LONDON 08–13 · LDN_NY_OVL 13–16 · NY 16–21 · LATE_US 21–24.

---

## 1. Per-session breakdown

### TF_B (5M/1H) — PRIMARY (n=12090, overall avg_R +0.3644)
| session | n | % | WR | avg_R | sum_R | BUY / SELL avg_R |
|---------|----|----|-----|-------|-------|----|
| ASIAN | 3829 | 31.7% | 68.5% | **+0.2850** | +1091 | +0.236 / +0.347 |
| LONDON | 2287 | 18.9% | 71.8% | **+0.4208** | +962 | +0.407 / +0.436 |
| LDN_NY_OVL | 2033 | 16.8% | 72.3% | +0.4163 | +846 | +0.419 / +0.414 |
| **NY (16–21)** | 2632 | 21.8% | 71.5% | **+0.4059** | +1069 | +0.344 / +0.474 |
| LATE_US | 1309 | 10.8% | 70.4% | +0.3337 | +437 | +0.317 / +0.356 |

→ Ranking: LONDON > LDN_NY_OVL > **NY** > overall > LATE_US > ASIAN. **NY is +0.042 above the
overall mean** — decent but *not the best* (London/overlap beat it). ASIAN is the clear weak
spot (−0.079 below mean) but still +0.285 net-profitable.

### TF_A (5M/4H) (n=4744, overall avg_R +0.3376)
ASIAN **+0.2629** · LONDON +0.3951 · LDN_NY_OVL +0.3049 · **NY +0.3478** · LATE_US +0.5032 (n=182, tiny).
→ NY only **+0.010 above mean** (marginal). ASIAN weakest again; LONDON strong; LATE_US highest
but n=182 (noise).

**NY highlight:** above the overall mean on both TFs, but by a small and TF-dependent margin
(B +0.042, A +0.010) — not a standout.

---

## 2. Per-VWAP-relationship breakdown

### TF_B (primary)
| bucket | n | % | WR | avg_R | sum_R |
|--------|----|----|-----|-------|-------|
| ABOVE_VWAP | 6329 | 52.3% | 68.9% | +0.3413 | +2160 |
| BELOW_VWAP | 5761 | 47.7% | 72.5% | +0.3897 | +2245 |
| **ALIGNED** (BUY>VWAP / SELL<VWAP) | 9764 | 80.8% | 69.7% | **+0.3470** | +3388 |
| **AGAINST** (BUY<VWAP / SELL>VWAP) | 2326 | 19.2% | 74.5% | **+0.4373** | +1017 |

→ **AGAINST out-earns ALIGNED (+0.437 vs +0.347).** Holds within each direction:
BUY above(aligned) +0.312 vs below(against) **+0.398**; SELL below(aligned) +0.387 vs
above(against) **+0.481** — so it is *not* a BUY/SELL-mix artifact.

### TF_A
ALIGNED **+0.2914** (82.9%) vs AGAINST **+0.5619** (17.1%) — an even larger inversion (+0.27 gap).

**The "VWAP-aligned outperforms" hypothesis is rejected.** Against-VWAP breakouts (price on the
"wrong" side of the day's average) out-earn the aligned ones on both TFs.

---

## 3. Session × VWAP combined

| | TF_B | TF_A |
|---|---|---|
| NY × ALIGNED | n1947, +0.3910 | n959, +0.2904 |
| NY × AGAINST | n685, **+0.4483** | n273, **+0.5491** |
| ALL × ALIGNED | n9764, +0.3470 | n3933, +0.2914 |
| ALL × AGAINST | n2326, **+0.4373** | n811, **+0.5619** |

→ The VWAP-AGAINST effect dominates and is **not specific to NY** — AGAINST beats ALIGNED both
inside NY and overall, by similar margins. NY does not add edge on top of the VWAP relationship;
the VWAP relationship is the carrier.

---

## 4. Confounds + stability

### Confounds
- **Session × REGIME — ASIAN weakness is not a regime artifact:** ASIAN is the weakest session in
  *every* regime (B: BEAR +0.285 / BULL +0.262 / RANGE +0.310 — all below the other sessions'
  ~0.40–0.55). It is a genuine session-of-day weakness (still profitable).
- **VWAP × VOLUME — NOT confounded.** ABOVE and BELOW VWAP have nearly identical mean vol_ratio
  (B 3.00 vs 2.81) and %HIGH-vol (≈53% both). So the VWAP-relationship edge is *independent* of
  the volume effect — it carries information beyond volume.

### Stability (OOS 70/30)
| bucket | TF_B train→test | TF_A train→test |
|--------|------------------|------------------|
| NY session | +0.4250 → **+0.3616** (decays to ~mean) | +0.3375 → +0.3718 |
| ABOVE_VWAP | +0.3466 → +0.3289 | +0.2910 → +0.3105 |
| BELOW_VWAP | +0.4090 → +0.3448 | +0.3609 → +0.4433 |
| **ALIGNED** | +0.3539 → +0.3309 | +0.2883 → +0.2986 |
| **AGAINST** | +0.4537 → **+0.3989** | +0.5371 → **+0.6196** |

→ **NY's above-mean edge decays OOS** on the primary TF_B (test +0.362 ≈ overall mean) — not
robust. **VWAP-AGAINST > ALIGNED HOLDS OOS on both timeframes** (B test +0.399 vs +0.331; A test
+0.620 vs +0.299) — a robust inverted signal, like volume.

**Where session/VWAP land vs prior breakdowns:** MSS-quality flipped OOS (noise); trend held on
B only; volume held on both (inverted); **session (NY) decays OOS — weak; VWAP-relationship holds
OOS on both — inverted, like volume.**

---

## 5. Interpretation (descriptive only — explicitly NOT a filter proposal)

- **NY session: no real, OOS-robust edge.** It is modestly above mean (B +0.042, A +0.010) but
  decays out-of-sample to ~the mean on the primary TF. The structurally weak session is ASIAN
  (still profitable). The forward Asian −8→+7.32 flip was burst/small-n; the 720d view shows
  Asian is simply the weakest session, not a flip.
- **VWAP-relationship: real, OOS-robust — and inverted.** Against-VWAP breakouts out-earn aligned
  ones on both TFs, within direction, holding OOS, independent of volume. Counter to the textbook
  "trade with VWAP" idea — same flavor as the inverted volume finding (the "obvious" / late
  setups under-perform the quieter ones).

**Heavy caveats (why this is orientation, not action):**
- (a) **NY's edge does not hold OOS;** session is largely noise on the primary TF.
- (b) **VWAP is anchor-sensitive** — daily 00:00 anchor here; a London-open/weekly anchor could
  move the cuts. The inversion's *magnitude* should not be over-trusted.
- (c) **Every session is profitable and VWAP-ALIGNED is +0.35 R / 80.8% of signals / the bulk of
  sum_R (+3388 R).** Filtering to NY-only (~22%) or AGAINST-only (~19%) would keep the better
  *avg_R* while discarding most *total profit* — the avg_R-vs-sum_R trap, same failure as the
  regime filter (−28% sum_R).
- (d) **The operator's 9 pm-PH (NY) window is an OPERATIONAL fact, not a market edge** — it is
  when the operator is awake to execute manually. If the bot is auto-traded on Bybit, session-of-
  day is irrelevant to it.
- (e) **Acting would require a separate pre-registered OOS experiment** with its own decision
  rule — not a change inferred from this descriptive pass.

**No session or VWAP filter is recommended or proposed.** NY carries little reliable information
(decays OOS); the VWAP relationship carries real OOS-robust *inverted* information, but the
under-performing aligned bucket is profitable and is the large majority of signals/R, so it is
not a filtering case. Reporting what the data shows; proposing nothing, blocking nothing.

---

**Isolation honored:** read-only descriptive bucketing, causal VWAP; in-memory (0 DB rows
written); both soaks (A 515231, B 515230) + fade (512666) alive and untouched; signals.db +
Run-3704 pin unchanged; main untouched; branch not pushed. No filter, no change, no signal
blocked. STOP.
