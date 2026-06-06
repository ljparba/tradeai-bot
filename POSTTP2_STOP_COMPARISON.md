# POSTTP2_STOP_COMPARISON — trail-to-TP1 vs hold-at-entry (backtest-only)

**Bottom line: V_ENTRY (hold the stop at ENTRY after TP2) is the better post-TP2 design — but
only marginally, and neither variant clears +0.40.** On the primary TF_B, V_ENTRY beats the
current frozen V_TP1 (trail-to-TP1) by **avg_R +0.0121** (+0.3644 → +0.3765), holds OOS
(test +0.3403 → +0.3552), improves PF and every regime bucket, and is **more live-portable**
(a single breakeven stop, vs moving the stop a second time to TP1). The improvement is real and
OOS-robust but **small**, and **V_ENTRY's +0.3765 is still below the +0.40 gate floor** — exactly
as expected for random-walk-at-1H tokens. This is a **risk-management design finding, not a
gate-passing attempt**. **No change adopted into the running soaks.**

Backtest-only, in-memory (NO DB writes). The live soaks (A 515231, B 515230) keep running the
**unchanged frozen trail-to-TP1 model** — only `run_tf_grid.py` got a backtest-only
`post_tp2_mode` parameter (default `trail_tp1`, existing callers byte-unchanged); the soak files
were not touched. Fade (512666) alive. DB backed up.

### The two variants (everything else EXACTLY Config 14, post-TP2 model, friction, 720d)
- **V_TP1 (current / live):** after TP2 the stop trails UP to TP1; a return to TP1 →
  `PARTIAL_TP2_T1`, both halves at TP1 → **R = net_tp1/risk** (+0.875 XRP geometry).
- **V_ENTRY (alternative):** after TP2 the stop stays at ENTRY; a return to ENTRY →
  `PARTIAL_TP2_BE`, runner exits at breakeven-with-friction → **R = (0.5·net_tp1 + 0.5·(−rt))/risk**
  (+0.25 XRP — identical to `PARTIAL_TP1`). Between TP2 and entry there is **no stop**, so a dip
  to TP1 does **not** terminate — it can resume to TP3 or expire as `PARTIAL_TP2`. Stop path is
  SL → entry (after TP1) → stays at entry — still **monotonic-up**, one fewer step than V_TP1.

### Unit verification (synthetic XRP geometry, all pass)
| path | V_TP1 | V_ENTRY |
|---|---|---|
| TP1→TP2→back to entry | PARTIAL_TP2_T1 (+0.875) | **PARTIAL_TP2_BE (+0.25)** |
| **TP1→TP2→dip to TP1-only→TP3** | PARTIAL_TP2_T1 (+0.875) | **WIN (+1.5)** ← the key behavioral difference |
| TP1→TP2→TP3 | WIN | WIN |
| monotonic-up | SL→entry→TP1 | SL→entry (never below entry) |
R(PARTIAL_TP2_BE) = +0.25 = R(PARTIAL_TP1) confirmed. Default (no mode arg) = trail_tp1 confirmed.

---

## Headline comparison (720d, friction)

### TF_B (5M/1H) — PRIMARY (n=12090)
| variant | avg_R | WR | PF | maxDD (R) | sum_R | train | test | DSR(2) |
|---------|-------|-----|-----|-----------|-------|-------|------|--------|
| V_TP1 (trail) | +0.3644 | 70.6% | 2.33 | 17.7 | +4405.2 | +0.3747 | +0.3403 | 1.000 |
| **V_ENTRY (hold)** | **+0.3765** | 70.0% | 2.38 | 18.7 | +4551.8 | +0.3856 | +0.3552 | 1.000 |
| **Δ (ENTRY−TP1)** | **+0.0121** | −0.6pp | +0.05 | +1.0 | **+146.6** | +0.0109 | **+0.0149** | — |

### TF_A (5M/4H) (n=4744)
| variant | avg_R | WR | PF | maxDD | sum_R | train | test |
|---------|-------|-----|-----|-------|-------|-------|------|
| V_TP1 | +0.3376 | 68.3% | 2.13 | 23.4 | +1601.8 | +0.3302 | +0.3551 |
| **V_ENTRY** | **+0.3623** | 67.7% | 2.21 | 23.6 | +1718.8 | +0.3558 | +0.3776 |
| **Δ** | **+0.0247** | −0.6pp | +0.08 | +0.2 | +117.0 | +0.0256 | +0.0225 |

→ V_ENTRY is higher avg_R on **both** TFs, **holds OOS** (test Δ +0.015 B, +0.022 A), better PF;
costs a slightly higher maxDD (+1.0 R on B) and a marginally lower WR (−0.6pp — some
`PARTIAL_TP2_BE` exits round to ≤0 on high-friction tokens). DSR is non-discriminating at this n.

---

## The trade-off, quantified (which force dominates)

Only the post-TP2 bucket changes (everything before TP2 is identical). All reclassified signals
were `PARTIAL_TP2_T1` under V_TP1:

### TF_B — 2708 signals reclassified, **net +147.8 R**
| transition | n | R delta | meaning |
|---|---|---|---|
| PARTIAL_TP2_T1 → **WIN** | 1460 | **+855.4** | dipped to TP1 but NOT entry, then **resumed to TP3** — V_ENTRY captured the full win that V_TP1 stopped at TP1 |
| PARTIAL_TP2_T1 → **PARTIAL_TP2_BE** | 1217 | **−718.8** | dipped to TP1 then **continued down to entry** — V_ENTRY gave back to BE the +0.875 V_TP1 protected |
| PARTIAL_TP2_T1 → PARTIAL_TP2 | 31 | +11.2 | dipped to TP1, expired above entry |

### TF_A — 1041 reclassified, **net +117.0 R** (623 →WIN +354.9 ; 415 →BE −239.2 ; 3 →PARTIAL_TP2 +1.2)

**Which force dominates:** the **upside-capture** force wins. Per signal the two forces are nearly
symmetric (each →WIN ≈ +0.59 R, each →BE ≈ −0.59 R), but **more runners resume to TP3 than
collapse to entry** (B: 1460 vs 1217; A: 623 vs 415). After reaching TP2, price is empirically
slightly more likely to push on to TP3 than to retrace the full ~1R back to entry — so removing
the tight TP1 trail nets positive. (Mild post-TP2 continuation / survivorship, on top of the
broadly random-walk 1H behaviour — consistent with `MEAN_REVERSION_EXPLORATION.md`.)

---

## Per-regime + OOS

**Per-regime avg_R (V_TP1 → V_ENTRY) — V_ENTRY better in EVERY regime, both TFs:**
- TF_B: BEAR +0.393→+0.408 · BULL +0.338→+0.348 · RANGE +0.363→+0.375
- TF_A: BEAR +0.303→+0.327 · BULL +0.327→+0.358 · RANGE +0.381→+0.400

**OOS 70/30:** V_ENTRY's test avg_R exceeds V_TP1's on both TFs (B +0.3552 vs +0.3403; A +0.3776
vs +0.3551). The improvement is consistent in train and test — it does not disappear OOS.

---

## VERDICT

**On the primary TF_B, hold-at-entry (V_ENTRY) is the better post-TP2 stop placement, by avg_R
+0.0121 (+0.3644 → +0.3765), holding OOS and improving every regime.** On TF_A the edge is larger
(+0.0247). The mechanism is the trade-off the operator described: V_ENTRY lets the ~1460 (B)
post-TP2 runners that only dipped to TP1 ride on to TP3 (+855 R), and the upside dominates the
~1217 that give back to breakeven (−719 R), netting **+148 R**.

- **Neither variant clears +0.40.** V_ENTRY TF_B = +0.3765 full / +0.3552 OOS-test — still below
  the gate floor. As pre-stated, this stop-placement choice **shifts the PARTIAL_TP2 bucket's R
  but does not move the headline above +0.40**. It is a risk-management refinement, not an
  edge-creator. The gate-failing conclusion stands.
- **V_ENTRY is also more live-portable:** it is the classic "move SL to breakeven after TP1, then
  let the runner go" — a single resting stop, monotonic-up (SL→entry), trivial to implement on
  Bybit. V_TP1's trail-to-TP1 requires moving the stop a *second* time after TP2.
- **Cost:** slightly higher maxDD (+1.0 R on B) and a hair lower WR (−0.6pp) — V_ENTRY trades a
  little more variance for the higher mean.

**Recommendation (design only, NOT adopted now):** for any **future** breakout strategy or a
**fresh** forward soak from zero, **hold-at-entry is the preferred post-TP2 design** — marginally
higher avg_R, OOS-robust, regime-broad, and simpler/more live-portable. **Do NOT adopt it into the
currently-running soaks** — that would re-tag and reset the forward count again (as the post-TP2
switch already did), and the +0.012 gain on B does not justify discarding the accumulating
forward sample. Adopt only if/when the operator commits to starting a fresh soak from zero.

---

**Isolation honored:** backtest-only, in-memory (0 DB rows written); only `run_tf_grid.py` changed
(added a default-`trail_tp1` `post_tp2_mode` param — soak files untouched, live model unchanged);
running soaks A 515231 + B 515230 + fade 512666 alive and untouched; signals.db + Run-3704 pin
unchanged; DB backed up (`breakout.db.posttp2cmp_bak.*`); main untouched; branch not pushed. STOP.
