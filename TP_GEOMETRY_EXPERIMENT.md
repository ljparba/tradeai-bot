# TP_GEOMETRY_EXPERIMENT — pre-registered, anti-overfit (720d, post-TP2 trail model)

**Verdict up front: NO variant qualifies.** Two variants (V2, V4) clear the OOS bar on
**TF_A only**; on the **primary TF_B every variant fails OOS test avg_R ≥ +0.40** (best
0.3956), with OOS degradation (test < train) on B. Adopting a TF_A-only result would be
the exact timeframe cherry-pick the pre-committed rule forbids. Per the rule's "no edge"
branch: **the strategy does not show sufficient OOS edge ≥ +0.40 under realistic post-TP2
geometry on the primary timeframe → NO geometry change adopted, and we do NOT sweep more.**
The wider-spacing *direction* is suggestive (see below) but is not OOS-confirmed on the
primary. **No live/soak change proposed.**

Backtest-only, in-memory (NO DB writes — strictly safer than row-tagging). Running soaks
A=515231, B=515230 + fade=512666 untouched and alive; signals.db + Run-3704 unchanged;
DB backed up (`breakout.db.tpgeo_bak.070534`); main untouched; branch not pushed.

---

## Pre-registered setup (frozen before any run)

5 TP-RR variants × {TF_A 5M/4H, TF_B 5M/1H}, full 720d window (2024-06-10→2026-05-31),
friction-on, **post-TP2 trail-to-TP1 exit model**, everything else EXACTLY Config 14
(c2=4, mss=30, buf=0.001, 12 tokens). Only TP1_RR/TP2_RR/TP3_RR change. Each run once.

| id | RR (1/2/3) | thesis |
|----|-----------|--------|
| V0 | 2.0/3.0/4.0 | BASELINE (current Config 14, +0.34 ref) |
| V1 | 2.0/3.0/3.5 | TP3 closer (Interp. A: catch runner before retrace) |
| V2 | 2.5/4.0/6.0 | wider spacing (Interp. B: bigger band, harder to trail out) |
| V3 | 1.5/2.5/3.5 | tighter all tiers (faster to bank) |
| V4 | 2.0/4.0/6.0 | TP1 same, TP2/TP3 stretched (widen post-TP1 band only) |

### PRE-COMMITTED DECISION RULE (written before interpreting results)
A variant is a candidate **only if ALL**: (1) OOS test avg_R ≥ +0.40, (2) deflated DSR
(5 trials) ≥ 0.95, (3) improvement holds across **all** regime buckets, (4) test ≈ train.
If multiple qualify → pick the **simplest/most-standard** geometry (NOT highest avg_R).
If none clear +0.40 OOS with passing DSR → **no edge, no change, no further sweeping**
("no edge" is an accepted outcome). A qualifier is NOT adopted — it becomes a candidate
for its **own fresh forward soak from zero**, never a live/soak change here.

---

## Results — 720d friction

### TF_A (5M / 4H)
| var | RR | n | WR% | avg_R | sum_R | PF | maxDD | train | **test** | DSR5 |
|-----|----|----|-----|-------|-------|----|----|-------|------|------|
| V0 | 2/3/4 | 4744 | 68.3 | +0.3376 | +1602 | 2.13 | 23.4 | +0.330 | +0.355 | 1.000 |
| V1 | 2/3/3.5 | 4744 | 68.3 | +0.3240 | +1537 | 2.08 | 23.4 | +0.320 | +0.334 | 1.000 |
| **V2** | 2.5/4/6 | 7152 | 64.6 | +0.4136 | +2958 | 2.24 | 27.1 | +0.405 | **+0.434** | 1.000 |
| V3 | 1.5/2.5/3.5 | 587 | 64.6 | +0.1801 | +106 | 1.54 | 15.5 | +0.186 | +0.166 | 0.996 |
| **V4** | 2/4/6 | 4744 | 67.7 | +0.4111 | +1951 | 2.37 | 21.3 | +0.397 | **+0.444** | 1.000 |

### TF_B (5M / 1H) — PRIMARY
| var | RR | n | WR% | avg_R | sum_R | PF | maxDD | train | **test** | DSR5 |
|-----|----|----|-----|-------|-------|----|----|-------|------|------|
| V0 | 2/3/4 | 12090 | 70.6 | +0.3644 | +4405 | 2.33 | 17.7 | +0.375 | +0.340 | 1.000 |
| V1 | 2/3/3.5 | 12090 | 70.6 | +0.3551 | +4293 | 2.30 | 18.0 | +0.366 | +0.329 | 1.000 |
| V2 | 2.5/4/6 | 16688 | 66.5 | +0.4257 | +7103 | 2.37 | 28.8 | +0.439 | +0.396 | 1.000 |
| V3 | 1.5/2.5/3.5 | 3181 | 67.1 | +0.2202 | +701 | 1.71 | 15.0 | +0.229 | +0.200 | 1.000 |
| V4 | 2/4/6 | 12090 | 70.0 | +0.4004 | +4840 | 2.46 | 22.8 | +0.412 | +0.373 | 1.000 |

### Outcome distribution (WIN / PT2 / PT2_T1 / PT1 / LOSS) + per-regime avg_R
**TF_A:**
- V0 [1658/0/1041/584/1455] BEAR +0.303 · BULL +0.327 · RANGE +0.381
- V1 [2053/0/646/584/1455] BEAR +0.284 · BULL +0.318 · RANGE +0.368
- V2 [1896/5/1751/1046/2440] BEAR +0.405 · BULL +0.398 · RANGE +0.438
- V3 [132/1/111/138/200] BEAR +0.227 · BULL +0.145 · RANGE +0.165
- V4 [1347/9/925/1002/1455] BEAR +0.398 · BULL +0.388 · RANGE +0.448

**TF_B:**
- V0 [3715/8/2711/2254/3381] BEAR +0.393 · BULL +0.338 · RANGE +0.363
- V1 [4698/5/1731/2254/3381] BEAR +0.379 · BULL +0.332 · RANGE +0.355
- V2 [3843/35/4013/3445/5301] BEAR +0.472 · BULL +0.394 · RANGE +0.414
- V3 [734/6/622/792/1020] BEAR +0.249 · BULL +0.173 · RANGE +0.238
- V4 [2853/44/2279/3512/3381] BEAR +0.434 · BULL +0.363 · RANGE +0.406

### Degeneracy / confound notes (pre-registered to watch)
- **V3 is starved/degenerate.** The economics gate (EV/RR admission) rejects most tight
  setups → n collapses (A: 4744→587, B: 12090→3181) and avg_R falls to +0.18/+0.22.
  Tighter geometry is clearly worse; not a viable direction.
- **V2 has an n-inflation confound.** Raising TP1_RR to 2.5 makes the economics gate admit
  ~50% MORE signals (A 4744→7152, B 12090→16688). So V2's higher avg_R is partly a
  **different signal population**, not a pure exit improvement. V2 is NOT a clean geometry
  test.
- **V4 is the clean test:** TP1_RR stays 2.0 → identical signal population (n=4744 / 12090,
  same as V0) → its avg_R lift is attributable purely to the wider TP2/TP3 placement.

---

## Honest-metrics caveats (do not let the metrics over-claim)
- **DSR is non-discriminating at this sample size.** Per-trade Sharpe over 5k–17k trades is
  statistically overwhelming; after 5-trial deflation (real cross-variant Sharpe std) the
  DSR is ≈1.000 for *every* variant — including the degenerate V3 (0.996). DSR therefore
  does NOT separate good from bad geometry here. The **binding criterion is OOS test
  avg_R**, exactly as the rule intends. (Reported honestly; not used to wave anything through.)
- **CPCV WR in this run is anomalous** (per-split test WR 33–49% vs raw positive-R WR
  64–71%) — a scoring mismatch between the custom realized_r win-function and cpcv_summary's
  internal WR scorer. It is therefore NOT used as a decision input; the rule relies on OOS
  test avg_R + DSR + regime breadth + train≈test, all computed directly from realized_r.

---

## Decision rule applied — criterion by criterion

| variant | (1) OOS test ≥ 0.40 | (2) DSR5 ≥ 0.95 | (3) regime-broad improvement | (4) test ≈ train | candidate? |
|---|---|---|---|---|---|
| **TF_A** | | | | | |
| V0 | ✗ 0.355 | ✓ | (baseline) | ✓ | no |
| V1 | ✗ 0.334 | ✓ | ✗ (worse all regimes) | ✓ | no |
| V2 | ✓ 0.434 | ✓ | ✓ (all 3 improve) | ✓ (0.405/0.434) | **yes** |
| V3 | ✗ 0.166 | ✓* | ✗ (worse) | ✓ | no |
| V4 | ✓ 0.444 | ✓ | ✓ (all 3 improve) | ✓ (0.397/0.444) | **yes** |
| **TF_B (primary)** | | | | | |
| V0 | ✗ 0.340 | ✓ | (baseline) | ✓ | no |
| V1 | ✗ 0.329 | ✓ | ✗ | ✓ | no |
| V2 | ✗ 0.396 | ✓ | ✓ | ✗ (0.439→0.396 OOS drop) | **no** |
| V3 | ✗ 0.200 | ✓ | ✗ | ✓ | no |
| V4 | ✗ 0.373 | ✓ | ✓ | ✗ (0.412→0.373 OOS drop) | **no** |

\* DSR non-discriminating (see caveat) — passes even for degenerate V3.

**Reading of the rule.** A geometry change applies to the shared Config 14 used by BOTH
soaks; the operator designates **B as PRIMARY**. The rule's candidate gate (OOS test ≥
+0.40) is met by V2/V4 on **TF_A only** and by **no variant on TF_B**. On B, the two
otherwise-promising variants (V2, V4) additionally show OOS degradation (test < train,
falling below 0.40) — a mild overfit signature on the primary. Selecting the timeframe
where a variant happens to clear is the precise selection bias the pre-registration forbids.

**Tiebreaker (documented, not an adoption):** among the TF_A qualifiers, the rule says pick
the **simplest/most-standard, NOT highest avg_R**. That is **V4 (2/4/6)** — integer RRs,
TP1 unchanged at the round 2.0, and the *clean* same-population test — over V2 (2.5/4/6,
non-round, n-inflated). So if a TF_A-only path were ever pursued, V4 would be the candidate
— but the primary-timeframe failure means this is **not adopted**.

---

## VERDICT

**No qualifying geometry — the strategy's edge is insufficient (< +0.40 OOS) on the primary
timeframe under the realistic post-TP2 exit.** No geometry change is adopted; no further
variants will be swept.

What the data DOES say honestly (direction, not adoption):
- **Interpretation A is rejected.** Pulling TP3 closer (V1) made avg_R *worse* on both TFs —
  cutting the runner short hurts; the trail-outs are not fixed by a nearer TP3.
- **Interpretation B (wider spacing) is directionally supported** but not OOS-confirmed on
  the primary. V2/V4 raise full-sample avg_R above baseline on BOTH TFs, regime-broadly,
  and even clear +0.40 *full-sample*; the gap is specifically the **OOS test split on B**
  (V2 0.3956, V4 0.3728) falling just short of the pre-committed +0.40 bar. "Promising
  full-sample, not OOS-proven on the primary" = **not adopted** under the strict rule.
- **Tighter geometry (V3) is degenerate** (economics-gate-starved) — not a direction.

Per the rule, a qualifier (here only TF_A-conditional V4) becomes a candidate for its **own
fresh forward soak from zero**, compared against the frozen Config 14 — **never** a live or
in-soak change from this backtest. Given the primary-TF failure, **I propose no such soak
and no change.** Backtest success on one timeframe ≠ forward proof.

**Isolation honored:** backtest-only, in-memory (0 DB rows written); soaks A 515231 +
B 515230 + fade 512666 alive and untouched; signals.db + Run-3704 unchanged; DB backed up;
main untouched; branch not pushed. STOP.
