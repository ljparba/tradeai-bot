# FIB_TIMEFRAME_ROBUSTNESS — is the 5M/4H V_FIB edge reference-TF-driven or a selection artifact?

**Phase C-Breakout · pre-registered · backtest-only · in-memory (no DB writes).**
Adjudicates the inversion in `FIB_PULLBACK_ENTRY_TEST.md` (V_FIB +0.913 OOS on 5M/4H, +0.111 on
5M/1H — identical logic). Same pre-registered V_FIB definition (0.5–0.618 pullback, limit at 0.5,
SL below 0.618, 30-entry-bar pullback window, TP 2/3/4R, post-TP2 = V_ENTRY hold_entry, friction).
**Only the (entry_TF / reference_TF) pair changes per combo.** Harness:
`run_fib_tf_robustness.py`. Soaks A 522562 / B 522561 + fade 512666 alive and untouched;
signals.db + Run-3704 unchanged; `breakout.db` mtime unchanged (11:30); main untouched; branch
not pushed; DB backed up (`*.tfrobust_bak.153909`). **No adoption proposed.**

---

## 0. Data availability (stated plainly — no fabrication)

The 720d cache holds **only 5m / 1h / 4h**. Therefore:

- **15M and 12H are built by EXACT aggregation** (15m = 3×5m, 12h = 3×4h — lossless coarsening,
  not fabrication). Valid for an entry TF (15m) and a reference TF (12h).
- **1M exists ONLY at 90d** (`data/cache_1m_90d`, 2026-03-02 → 2026-05-31). So the operator's
  **C3 (1M/1H) and C4 (1M/4H) CANNOT run at 720d.** 1M is **NOT** resampled from 5M (that would
  fabricate sub-5M structure and destroy the entry-timing test).

| pre-reg combo | runnable at 720d? | where |
|---|---|---|
| C1 5M/1H | ✅ | PRIMARY (720d) |
| C2 5M/4H | ✅ | PRIMARY (720d) |
| C5 15M/4H | ✅ (15m = agg 5m) | PRIMARY (720d) |
| C6 5M/12H | ✅ (12h = agg 4h) | PRIMARY (720d) |
| C3 1M/1H | ❌ no 720d 1m | SECONDARY (90d only) |
| C4 1M/4H | ❌ no 720d 1m | SECONDARY (90d only) |

To still answer the 1M-entry idea, a **SECONDARY 90d panel** (the only window with 1m) runs
5M/1H, 5M/4H, 1M/1H, 1M/4H — *clearly labelled separate*; its n's are tiny and its window is a
different regime, so it is corroborative only, not decisive.

---

## 1. PRIMARY PANEL (720d) — the decisive evidence

| combo | entry/ref | n | avg_R | WR% | PF | maxDD | train | **test (OOS)** | DSR₆ | tok>+0.40 | pullback% |
|-------|-----------|--:|------:|----:|---:|------:|------:|------:|-----:|:---------:|----------:|
| **C1** | 5M / **1H** | 2080 | +0.088 | 54.3 | 1.20 | 43.7 | +0.078 | +0.111 | 0.000 | **0/12** | 12.4 |
| **C2** | 5M / **4H** | 691 | **+0.824** | 83.6 | 6.48 | 3.0 | +0.785 | **+0.913** | 1.000 | **10/12** | 9.7 |
| **C5** | **15M** / 4H | 1522 | +0.117 | 53.9 | 1.27 | 24.2 | +0.109 | +0.137 | 0.000 | **0/12** | 18.8 |
| **C6** | 5M / **12H** | 322 | **+0.674** | 77.3 | 4.18 | 6.9 | +0.618 | **+0.805** | 0.998 | **9/12** | 12.4 |

**The pattern is NOT "higher reference TF = better." It is "5M fine entry AND reference candle
much longer than the pullback window."** Read the two axes:

- **Reference height alone does NOT decide it.** C5 (15M/4H) holds the reference at **4H** — the
  exact TF the operator says carries "true direction" — and the edge **collapses to +0.117
  (0/12 tokens, DSR 0).** Same 4H reference as the passing C2, only the entry granularity changed
  (5M→15M). **If 4H "showed the real direction," a 15M entry on that same 4H structure could not
  be a coin flip. It is.** → C5 is the clean refutation of the operator's mechanism.
- **Entry granularity + window/reference ratio decides it.** The clean separator across all four
  primary cells is the ratio of the 30-bar pullback window to the reference-candle length:

| combo | pullback window (30 entry bars) | ref candle | ratio | result |
|-------|--------------------------------:|-----------:|------:|:------:|
| C2 5M/4H | 2.5 h | 4 h | **0.63** | PASS |
| C6 5M/12H | 2.5 h | 12 h | **0.21** | PASS |
| C5 15M/4H | 7.5 h | 4 h | 1.88 | FAIL |
| C1 5M/1H | 2.5 h | 1 h | 2.50 | FAIL |

Both passing cells have **window ≪ reference candle** (ratio < 1); both failing cells have
**window ≥ reference candle** (ratio > 1). The "edge" is the V_FIB *selection* mechanism — it only
trades the ~10% of breakouts that retrace 50–62% and resume — parameterised by how much of the
fresh reference candle the pullback window can see. When the window is a small slice of a large
fresh breakout (C2/C6), it selects a "quick shallow retrace then resume" subset that was
favourable over 720d; when the window spans the reference candle (C1/C5), the selection is
different and null. **This is selection, not direction.** *(This ratio explanation is post-hoc /
exploratory — flagged as such; it is itself an unvalidated hypothesis, not a pre-registered
result.)*

**Per-regime (passing cells are broad; failing cells are flat):**

| combo | BULL | BEAR | RANGE |
|-------|-----:|-----:|------:|
| C2 5M/4H | +0.830 | +0.840 | +0.802 |
| C6 5M/12H | +0.608 | +0.764 | +0.666 |
| C1 5M/1H | +0.114 | +0.059 | +0.092 |
| C5 15M/4H | +0.197 | +0.056 | +0.081 |

**Shield breakdown (consistent across ALL combos — it's always selection):** of V_CURRENT's
FULL_SL losses, V_FIB "avoids" 56–68% simply by *not trading* (price never pulled back), on
passing and failing cells alike (C2 68%, C6 66%, C1 67%, C5 56%). The loss reduction is
trade-rejection, never a structural SL shield — identical to the conclusion in `SL_ANATOMY.md`.

---

## 2. SECONDARY PANEL (90d — corroborative only, tiny n, different regime)

| combo | entry/ref | n | avg_R | WR% | test | DSR₆ | tok>+0.40 |
|-------|-----------|--:|------:|----:|-----:|-----:|:---------:|
| S1 | 5M / 1H | 163 | +0.308 | 67.5 | +0.440 | 0.000 | 4/12 |
| S2 | 5M / 4H | 61 | +1.010 | 90.2 | +1.120 | 0.992 | 9/12 |
| S3 | 1M / 1H | 54 | +0.775 | 81.5 | +0.736 | 0.884 | 8/12 |
| S4 | 1M / 4H | 22 | +0.979 | 90.9 | +1.155 | 0.939 | 9/12 |

The 90d panel **does not corroborate the operator's hypothesis — it undermines robustness**:

- **The same combo wanders with the window.** 5M/1H is +0.088 over 720d (C1, 0/12) but +0.308
  over the last 90d (S1, 4/12). 1M/1H (S3) is +0.775 — a **1H-reference** cell scoring far above
  the 720d 1H cells. If reference height were the driver, a 1H-ref cell could not lead. The
  numbers move with the sample slice → window-dependence, the signature of selection variance.
- **The 1M cells are statistically empty.** S3 n=54 (per-token n=2–9), S4 n=22 (per-token n=1–6).
  "9/12 tokens >+0.40" on tokens with n=1–4 is noise, not breadth. These cannot adjudicate C3/C4.

---

## 3. The pre-registered DECISIVE TEST, applied

> *"Does C4 (1M/4H) and C6 (5M/12H) — both higher-ref — clear +0.40 OOS with broad per-token
> support the SAME way C2 did? If YES across ALL high-ref cells → alignment supported. If NO
> (high-ref cells scatter) → TF_A was the lucky cell."*

High-reference (≥4H) cells and their verdicts:

| high-ref cell | avg_R | tok>+0.40 | DSR₆ | verdict |
|---|---:|:---:|---:|:---:|
| C2 5M/4H (720d) | +0.824 | 10/12 | 1.000 | PASS |
| C6 5M/12H (720d) | +0.674 | 9/12 | 0.998 | PASS |
| **C5 15M/4H (720d)** | **+0.117** | **0/12** | **0.000** | **FAIL** |
| S2 5M/4H (90d) | +1.010 | 9/12 (n=61) | 0.992 | pass (small n) |
| S4 1M/4H (90d, =C4) | +0.979 | 9/12 (n=22) | 0.939 | inconclusive (n=22) |

**The high-reference cells do NOT all pass — they SCATTER.** C5 (15M/4H) is a high-reference cell
that fails outright. Per the pre-registered rule, **scatter among high-ref cells = the alignment
hypothesis is NOT supported by a clean reference-TF main effect.** The cells that pass all share a
5M entry; the one high-ref cell with a coarser entry fails. The deciding variable is the
entry×window interaction, not reference-TF height.

A caveat in the *other* direction, stated honestly: C2 and C6 are **not** independent
confirmations — 12H breakouts are a coarsening of largely the same market moves as 4H breakouts
over the **same 720d window**, so "it reproduces at 12H" is partly redundant, not a second
independent draw. The one structurally independent variation (C5, different entry granularity)
breaks it, and the one out-of-window check (90d) shifts the numbers around. So the passing result
is **narrower and less robust than two independent confirmations would imply.**

---

## 4. VERDICT — adjudicating the operator's hypothesis directly

**The operator's hypothesis — "higher reference TF = truer direction; 5M/4H works because 4H
shows real direction, 5M/1H fails because 1H is unreliable" — is NOT supported. It is refuted by
the data.**

1. **C5 (15M/4H) is the decisive refutation.** Same 4H reference, only a coarser entry (15M), and
   the +0.82 edge collapses to +0.12 with **0/12 tokens**. Direction-at-4H cannot be the cause if
   a 15M entry reading that same 4H direction is a coin flip.
2. **The corroborating evidence the operator cited holds:** `TREND_EXPLORATION` found 4H *and*
   daily are both random walk (VR≈1.00, efficiency 0.22, MA-direction coin-flip) — there is no
   "true direction" at 4H for V_FIB to exploit. C5 is exactly what that predicts.
3. **The 5M/4H result is not a single isolated lucky cell, but it is also not a reference-TF
   effect.** It reproduces at one correlated neighbour (C6 5M/12H, same window, overlapping moves)
   and breaks at the one independent structural variation (C5). What actually travels is the
   V_FIB **selection** mechanism under "fine entry + pullback window ≪ reference candle" — the same
   WR-vs-R / trade-rejection effect `FIB_PULLBACK_ENTRY_TEST.md` and `SL_ANATOMY.md` already
   identified, now shown to be tuned by the entry/window-to-reference ratio rather than by
   directional information.
4. **Robustness is weak.** The magnitudes wander with the sample window (5M/1H: +0.088 over 720d
   vs +0.308 over 90d; a 1H-ref cell S3 leads the 90d panel), which is the fingerprint of
   selection variance in random-walk tokens, not a stable directional edge.

**Plainly: TF_A was not "the 4H reference revealing true direction." It was the favourable corner
of a heavily-selected V_FIB subsample whose sign depends on the entry-TF × pullback-window × ref
interaction, not on reference-TF height. The high-reference cells scatter (C5 fails), so the
alignment hypothesis is rejected; the passing cells are the selection mechanism, not a shield.**

---

## 5. Recommendation

**NO adoption from this run** (as pre-committed). The operator's stated mechanism is refuted, so
there is nothing to forward-test under that framing.

A *separate* pre-registered experiment is **only** justifiable for the **corrected, narrower**
hypothesis the data suggests — "5M fine entry with a pullback window much shorter than the
reference candle selects a favourable quick-retrace subset" — and even then with strong caveats:
it must (a) be stated as the entry/window-to-reference-ratio effect, **not** ref-TF direction;
(b) forward-validate on a genuinely out-of-sample window (the 90d wander is a warning sign);
(c) carry an independent-cell control like C5 to prove it is not the same correlated draw; and
(d) reckon with the prior finding that the whole effect is WR-vs-R selection with no expectancy
edge. Given (d) and the C5 refutation, my read is that such an experiment would most likely
confirm "selection, not edge" — so I do **not** recommend prioritising it. The live V_CURRENT
(MSS+1 market entry) remains correct: robust across every TF combo tested (+0.21 to +0.42, no
sign inversion), trading the full setup population.

---

### Isolation confirmation
Backtest-only; in-memory (zero `breakout.db` / `signals.db` writes — `breakout.db` mtime unchanged
at 11:30). Soaks A 522562 + B 522561 + fade 512666 alive and untouched; Run-3704 pin unchanged;
main untouched; branch `breakout-thesis` not pushed; DB backed up before the run. **Report and STOP.**
