# SL_ANATOMY — anatomy of FULL_SL losses (DESCRIPTIVE / read-only)

**Phase C-Breakout · pure observation · NO code/SL/entry change · NO DB writes · no merge/push.**
720d (2024-06-10 → 2026-05-31) · Config 14 `LOCKED_KNOBS` · friction ON · post-TP2 = **V_ENTRY**
(`hold_entry`, live soak model) · TF_A (5M/4H) + TF_B (5M/1H).

Harness: `run_sl_anatomy.py` (in-memory, read-only). Loss set = signals that survive friction
and that `G.check_outcome` labels `LOSS` under the live model. All anatomy fields are **causal**
(forward bars only — the same bars the trade itself sees; no look-ahead). Soaks A 522562 / B
522561 + fade 512666 alive and untouched; signals.db + Run-3704 unchanged; main untouched; branch
not pushed.

> **Framing (carried from `FIB_PULLBACK_ENTRY_TEST.md`):** delaying entry / structural-SL
> placement does **not** create expectancy in these random-walk tokens — it redistributes
> WR-vs-R. This document explains the loss *structure*; it is **not** a path to a fix. Even where
> losses look "fixable" (near-misses), the entry/SL experiment already proved no profitable
> adjustment exists. **No entry or SL change is proposed.**

---

## 0. What ">1.5" means here (interpretation confirmed)

Segment dimension `>1.5` = the operator's **vol_ratio** = `volume[MSS bar] / mean(volume of the
prior 20 5m bars)`, **HIGH** bucket `>1.5` — the exact causal definition used in
`VOLUME_BREAKDOWN.md` (LOW <0.8 · NORMAL 0.8–1.5 · HIGH >1.5). It is *volume expansion at the
MSS confirmation bar*, not an R-multiple (rr1 is fixed ≈2.0 for every breakout signal, so an
R-multiple split is degenerate) and not a Kaufman efficiency ratio (not computed in this engine).
vol_ratio was known for **100%** of losses on both TFs (5m grid → exact MSS-bar match).

---

## 1. Stop-out timing — how fast do losses hit SL?

| bucket | TF_A 5M/4H | TF_B 5M/1H |
|--------|-----------:|-----------:|
| immediate (1–3 bars) | **586 (40.3%)** | 758 (22.4%) |
| fast (4–12 bars) | 409 (28.1%) | 521 (15.4%) |
| slow (13+ bars) | 460 (31.6%) | **2102 (62.2%)** |
| **median bars-to-SL** | **5** | **28** |

- **TF_A: stops are FAST** — 40% hit within 3 bars (15 min), median 5 bars. When a 4H-framed
  breakout is wrong, it is wrong almost immediately.
- **TF_B: stops are SLOW** — 62% hit only after 13+ bars, median 28 bars (≈2.3h). 1H-framed
  setups drift the right way first, then reverse into the stop much later.

---

## 2. Max favorable excursion before the stop — REVERSE vs PULLBACK (the core question)

Fraction of the entry→TP1 distance reached before the SL was hit (MFE; 0 = pure reversal,
1 = tagged TP1):

| bucket | TF_A 5M/4H | TF_B 5M/1H |
|--------|-----------:|-----------:|
| REVERSED (<10%) | **648 (44.5%)** | 730 (21.6%) |
| SHALLOW (10–50%) | 399 (27.4%) | 991 (29.3%) |
| NEAR-MISS (50–90%) | 336 (23.1%) | **1333 (39.4%)** |
| EXTREME-NEAR-MISS (90–100%) | 72 (4.9%) | 327 (9.7%) |
| **median MFE fraction** | **0.166** | **0.490** |
| REVERSED share | **44.5%** | 21.6% |
| NEAR-MISS+ share | 28.0% | **49.1%** |

**The two timeframes give opposite loss anatomies:**

- **TF_A losses are dominated by GENUINE REVERSALS.** 44.5% barely moved toward TP1 (<10%) before
  going to the stop; the median loss reached only **16.6%** of the way to TP1. These are
  wrong-direction trades, **not** a tight-SL / wiggle problem.
- **TF_B losses are dominated by NEAR-MISSES.** 49.1% reached ≥50% of the way to TP1 (median
  **49.0%**) before reversing into the stop. Price went the *right* way, then the slower 1H
  structure dragged it back.

This is the descriptive twin of the fib-test inversion: TF_A "wrong fast" vs TF_B "right then
wiggled back" — same engine, only the reference candle (4H vs 1H) differs.

---

## 3. The two hypotheses (descriptive only — both already shown random-walk-neutral)

### 3a. "Early entry" — would a later (pullback) entry have survived?
**Cross-reference, not re-built:** `FIB_PULLBACK_ENTRY_TEST.md` already tested exactly this — wait
for a 0.5–0.618 pullback before entering. Result: on the primary TF the pullback entry
**redistributes WR-vs-R without raising expectancy**, and the apparent TF_A gain **inverted on
TF_B (0/12 tokens)** — i.e. it was selection, not a shield. So "enter later" does not convert
these near-misses into net profit. Not re-derived here.

### 3b. "Tight SL" — how much wider would the SL have needed to be to survive?
No-SL counterfactual on the **near-miss losses** (MFE ≥ 50%): ignoring the stop, did price later
reach TP1 within the 48h window, and how deep was the dip first?

| | TF_A 5M/4H | TF_B 5M/1H |
|---|-----------:|-----------:|
| near-miss losses (MFE≥50%) | 408 (28.0% of losses) | 1660 (49.1% of losses) |
| of those, price LATER reached TP1 (no-SL) | 307 / 408 (**75.2%**) | 1052 / 1660 (**63.4%**) |
| required SL widening to survive → TP1 (median) | **1.73R** | **2.19R** |
| … p75 / p90 | 2.79R / 4.24R | 3.77R / 6.05R |
| **deepest adverse over full window, ALL losses (median / p90)** | **1.79R / 5.03R** | **2.51R / 11.14R** |

Reading this honestly:
- Yes, most near-miss losses *would* eventually have tagged TP1 with a wider stop — but the SL
  would have had to sit a **median 1.7–2.2R away** (p90 4–6R) to survive the dip.
- The **deepest-adverse row is the catch:** across *all* losses, price runs a median **1.8R
  (TF_A) / 2.5R (TF_B)** past the 1R stop, with a p90 of **5R / 11R**. You cannot place a stop
  wide enough to rescue the recoveries without converting a large mass of 1R losses into
  2–11R losses.
- **FLAG (the random-walk WR-vs-R tradeoff):** widening the SL to *k·R* mechanically scales
  R-per-trade by ~`1/k` (risk is the denominator of every R). A "wider SL would have saved it"
  finding therefore describes geometry — it does **not** imply higher expectancy. This is the
  exact symmetry the fib experiment confirmed empirically.

---

## 4. Segment by vol_ratio (>1.5 HIGH vs ≤1.5)

| TF | segment | n | REVERSED | NEAR-MISS+ | immediate(1–3) | median MFE |
|----|---------|--:|---------:|-----------:|---------------:|-----------:|
| A 5M/4H | HIGH vol >1.5 | 791 | 42.2% | 31.2% | 38.6% | 0.198 |
| A 5M/4H | NORMAL/LOW ≤1.5 | 664 | 47.3% | 24.2% | 42.3% | 0.128 |
| B 5M/1H | HIGH vol >1.5 | 2054 | 18.3% | 49.9% | 17.0% | 0.499 |
| B 5M/1H | NORMAL/LOW ≤1.5 | 1327 | 26.8% | 47.9% | 30.8% | 0.473 |

- On **both** TFs the HIGH-vol losses are *slightly* more near-miss and *slightly* less
  immediate-reversal than the low-vol losses (more favorable travel before stopping). The effect
  is **modest** (a few points), not a regime split.
- This is consistent with `VOLUME_BREAKDOWN.md`'s finding that HIGH-vol signals were the *higher
  total-R but lower avg-R* bucket — their losses get further toward target before failing, but
  not in a way that the volume tag could be turned into a profitable filter.

---

## 5. Interpretation (descriptive — no fix proposed)

**Are losses dominated by genuine REVERSALS or by NEAR-MISSES? It depends on the reference TF —
and that is the finding:**

- **TF_A (5M/4H, the validated config): REVERSALS dominate.** 44.5% reversed, median MFE 16.6%,
  40% stopped within 3 bars. Most losses are wrong-direction trades that fail fast. A tight-SL /
  early-entry story does **not** fit TF_A — there is little favorable travel to "protect."
- **TF_B (5M/1H): NEAR-MISSES dominate.** 49.1% reached ≥50% toward TP1, median MFE 49%, 62%
  stopped only after 13+ bars. These *look* like a tight-SL / early-entry problem — price went
  the right way, then drifted back.

**Crucially, the near-miss-heavy TF_B does NOT imply a profitable fix exists.** Two independent
pieces of evidence from this very dataset say otherwise:

1. The **no-SL counterfactual** shows the "recoverable" near-misses need a median 1.7–2.2R wider
   stop, while *all* losses run a median 1.8–2.5R (p90 5–11R) past the stop — so any widening
   that rescues the near-misses pays for it with a heavier loss tail. It's a redistribution, not
   a gain (§3b FLAG).
2. The **fib-pullback experiment** (`FIB_PULLBACK_ENTRY_TEST.md`) already implemented the "enter
   later / structural SL below a level" idea and found it **WR-vs-R-neutral on the primary TF and
   sign-inverting across TFs** — the signature of random-walk tokens with no intrinsic
   support/shield property.

**Bottom line:** the anatomy explains *why* stops are hit — fast wrong-direction reversals on
4H-framed setups, slow right-then-back near-misses on 1H-framed setups, mildly modulated by
volume expansion — but it confirms rather than contradicts the random-walk conclusion. The
near-miss appearance on TF_B is real geometry, not a free profit lever. **No entry or SL change
is recommended; this is understanding, not a prescription.**

---

### Isolation confirmation
Read-only; in-memory (zero `breakout.db` / `signals.db` writes — `breakout.db` mtime unchanged at
11:30). Soaks A 522562 + B 522561 + fade 512666 alive and untouched; Run-3704 pin unchanged; main
untouched; branch `breakout-thesis` not pushed. **Report and STOP.**
