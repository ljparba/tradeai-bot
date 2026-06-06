# MSS_QUALITY_BREAKDOWN — descriptive per-quality analysis (read-only)

**Bottom line: the MSS quality tag is NOT a reliable performance discriminator.** The
in-sample avg_R spread across HIGH/MEDIUM/LOW is small (~0.04–0.05 R), **non-monotonic**
(MEDIUM edges HIGH on TF_A; LOW beats MEDIUM on TF_B), confounded with direction and
confluence mix, and — the decisive check — **does not hold out-of-sample** (the ordering
fully flips on TF_A train→test). Descriptively interesting, **not actionable**. This is a
pure observation; **no filter is proposed, nothing is changed.**

720d, Config 14 (post-TP2 trail model, friction), TF_A + TF_B, in-memory (NO DB writes).
Config 14 tags MSS quality but does **not** gate on it — all confirmed MSS are accepted.
Soaks A=515231, B=515230 + fade=512666 alive and untouched.

---

## 1. Per-quality breakdown (720d friction)

### TF_B (5M/1H) — PRIMARY (total n=12090)
| tier | n | % | WR | avg_R | sum_R | PF | outcome [WIN/PT2/PT2_T1/PT1/LOSS] |
|------|----|----|-----|-------|-------|----|----|
| HIGH | 8378 | 69.3% | 71.3% | **+0.3781** | +3168 | 2.42 | 2601/3/1878/1593/2292 |
| MEDIUM | 3574 | 29.6% | 68.9% | **+0.3320** | +1187 | 2.15 | 1075/5/799/629/1056 |
| LOW | 138 | 1.1% | 73.9% | **+0.3677** | +51 | 2.55 | 39/0/34/32/33 |

→ ordering HIGH > **LOW** > MEDIUM. **Non-monotonic** — LOW (tiny n=138) sits *above*
MEDIUM. HIGH beats MEDIUM by +0.046, but the "ladder" is broken by LOW.

### TF_A (5M/4H) (total n=4744)
| tier | n | % | WR | avg_R | sum_R | PF | outcome [WIN/PT2/PT2_T1/PT1/LOSS] |
|------|----|----|-----|-------|-------|----|----|
| HIGH | 2440 | 51.4% | 68.0% | **+0.3377** | +824 | 2.11 | 878/0/512/293/756 |
| MEDIUM | 2132 | 44.9% | 68.7% | **+0.3402** | +725 | 2.16 | 728/0/479/277/643 |
| LOW | 172 | 3.6% | 66.3% | **+0.3047** | +52 | 1.97 | 52/0/50/14/56 |

→ ordering **MEDIUM ≈ HIGH** > LOW. **MEDIUM slightly *beats* HIGH** (+0.3402 vs +0.3377).
The total spread (best−worst) is only ~0.035 R. No monotonic HIGH>MEDIUM>LOW pattern.

**Spread summary:** the gap between tiers is ~0.04–0.05 R on both timeframes, with the
*direction of the ordering inconsistent between TFs* (HIGH-top on B, MEDIUM-top on A).

---

## 2. Confound checks (so the descriptive result isn't misread)

**Quality × DIRECTION — confounded.** SELL consistently out-earns BUY in *every* tier, so
tier differences partly reflect direction mix, not quality:
- TF_B HIGH: BUY +0.333 / SELL +0.430 · MEDIUM: BUY +0.317 / SELL +0.349 · LOW: BUY +0.347 / SELL +0.391
- TF_A HIGH: BUY +0.309 / SELL +0.374 · MEDIUM: BUY +0.301 / SELL +0.386 · **LOW: BUY +0.041 / SELL +0.594**
  → TF_A LOW's whole result is carried by a SELL skew (n=82 SELL @ +0.594 vs n=90 BUY @ +0.041).
  (Echoes the known counter-intuitive "+0.575-class" case — low-quality trades can be strongly
  profitable; the tag does not isolate the loss-makers.)

**Quality × CONFLUENCE (FVG/OB) — confounded.** FVG-tagged trades out-earn OB in nearly
every tier, and HIGH-MSS carries a heavier FVG share:
- TF_B HIGH: FVG n5684 +0.401 / OB n2694 +0.329 · MEDIUM: FVG +0.387 / OB +0.255 · LOW: FVG +0.528 / OB +0.147
- TF_A HIGH: FVG +0.489 / OB +0.280 · MEDIUM: FVG +0.407 / OB +0.313
- **CAVEAT (FVG_MITIGATION_CHECK.md):** there is a known FVG/OB label drift — the confluence
  split is itself biased, so this confound is directional evidence only; **do not over-read it.**

**Quality × REGIME — noisy, no clean pattern.** No tier dominates a regime consistently;
LOW's per-regime cells are tiny-n (e.g. TF_B LOW BULL n47 +0.183 vs RANGE n49 +0.511) and
swing widely. Not a structural confound, just low-n noise in the LOW tier.

**Quality × SL% / TOKEN — NOT confounded.** Mean |SL| is essentially flat across tiers
(TF_B 0.69/0.68/0.63%; TF_A 0.60/0.59/0.56%) and the top tokens are the same set
(AVAX/LINK/XRP/BCH) in every tier. So the tier differences are *not* an SL-width or
token-mix artifact.

---

## 3. Stability check (OOS 70/30) — the decisive honesty test

Does the quality ordering survive out-of-sample?

### TF_A — ordering FULLY FLIPS (noise signature)
| tier | train avg_R | test avg_R |
|------|-------------|------------|
| HIGH | +0.3167 | **+0.3868** |
| MEDIUM | +0.3329 | +0.3574 |
| LOW | **+0.3579** | **+0.1820** |

In **train** the order is **LOW > MEDIUM > HIGH** (inverted!). In **test** it is
**HIGH > MEDIUM > LOW**. The ordering completely reverses across the split, and LOW
collapses from best (+0.358) to worst (+0.182). This is the textbook signature of **noise**,
not a real edge.

### TF_B — HIGH>MEDIUM survives but the gap halves; LOW erratic
| tier | train avg_R | test avg_R |
|------|-------------|------------|
| HIGH | +0.3903 | +0.3497 |
| MEDIUM | +0.3356 | +0.3235 |
| LOW | +0.3837 | +0.3310 |

HIGH > MEDIUM holds in both splits, but the HIGH−MEDIUM gap shrinks from +0.055 (train) to
+0.026 (test). LOW is 2nd in both splits yet on n=96→42 (noise-dominated). So even where a
weak HIGH>MEDIUM signal exists, it **decays out-of-sample** and is contradicted by LOW
sitting above MEDIUM.

**Verdict on stability:** the quality ordering does **not** hold reliably OOS — it inverts on
TF_A and weakens/breaks-monotonicity on TF_B.

---

## 4. Interpretation (descriptive only — explicitly NOT a filter proposal)

**Is MSS quality a meaningful performance discriminator? No — not reliably.**
- The in-sample spread is small (~0.04–0.05 R) and **non-monotonic** (MEDIUM ≥ HIGH on A;
  LOW > MEDIUM on B).
- It is **confounded** with direction (SELL>BUY) and confluence (FVG>OB, itself label-drift-biased).
- It **does not hold OOS** — the ordering fully flips on TF_A and the modest HIGH>MEDIUM edge
  on TF_B halves out-of-sample while LOW (tiny n) stays above MEDIUM.
- The only consistent thing is that **HIGH is never the *worst*** — but "HIGH ≈ MEDIUM, LOW
  noisy" is not a usable quality ladder.

**Heavy caveats (why this is orientation, not action):**
- (a) Any in-sample tier difference may not hold OOS — and here it demonstrably does not.
- (b) LOW is only 1–4% of signals and can be strongly net-profitable (TF_A LOW SELL +0.594;
  the +0.575-class counter-intuitive trades). Filtering LOW would cut profitable signals and
  shrink an already small-n forward soak for no proven gain.
- (c) Acting on this would require a **separate pre-registered OOS experiment** with its own
  decision rule — exactly like the TP-geometry test — not a change inferred from this descriptive pass.

**No MSS-quality gate is recommended.** The tag carries little-to-no reliable performance
information beyond a weak, OOS-decaying HIGH-vs-MEDIUM tilt on TF_B that is confounded and
non-monotonic. Reporting what the data shows; proposing nothing.

---

**Isolation honored:** read-only descriptive analysis; in-memory (0 DB rows written); both
soaks (A 515231, B 515230) + fade (512666) alive and untouched; signals.db + Run-3704 pin
unchanged; main untouched; branch not pushed. No filter, no change, no recommendation. STOP.
