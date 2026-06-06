# EXIT MODEL COMPARISON — V_ENTRY (live scaled) vs V_FULLTP2 (full → TP2, single exit)

**Phase:** C-Breakout · **Type:** structural exit-model comparison (NOT a gate-pass search)
**Date:** 2026-06-05 · **Branch:** `breakout-thesis` (worktree `/home/tradeai/breakout-work`)
**Mode:** backtest-only, in-memory (NO DB writes) · friction ON · 720d (2024-06-10 → 2026-05-31)
**Universe:** 12 tokens · Config 14 knobs locked · TF_A = 5M/4H (soak A) · **TF_B = 5M/1H (soak B = PRIMARY)**

**Isolation honored:** running soaks A (PID 522562) and B (PID 522561) left UNTOUCHED — they keep
the live V_ENTRY model. `run_tf_grid.py`'s V_ENTRY logic (`check_outcome` / `_calc_realized_r`) was
NOT modified; V_FULLTP2 was added as two NEW additive functions. fade / `signals.db` / Run-3704 /
`main` untouched. Branch not pushed. DB backed up to `data/breakout.db.exitcmp_bak.012126`.

---

## 0. TL;DR — VERDICT

**On the primary TF_B (5M/1H), the two exit models are a statistical tie. V_FULLTP2 has a
marginally higher in-sample avg_R (+0.3843 vs +0.3750, Δ +0.0093R/signal) but V_ENTRY wins on
WR, PF, max-drawdown AND out-of-sample test R. NEITHER model clears +0.40 on TF_B.**

The operator's stated premise — that partial scaling "incurs multiple exit fees" and a single
full-TP2 exit saves them — **is NOT supported by the validated friction engine: the in-model fee
delta is EXACTLY ZERO** (+0.0000 R on both TFs). The friction engine already charges one
proportional round-trip per position regardless of how many partial legs book it.

What V_FULLTP2 actually does is **redistribute the outcome distribution** (fewer, larger wins +
more breakevens in place of many small TP1-partial wins) — exactly as pre-stated. On random-walk
tokens this reshuffles where the same edge lands without materially moving expectancy on TF_B.

**Recommendation:** keep V_ENTRY in the running soak. Do NOT adopt V_FULLTP2 — a forward reset is
not justified for a sub-gate, OOS-neutral-to-worse change on the primary TF. **However**, V_FULLTP2
is cleanly better AND simpler on the secondary TF_A (4H reference) and removes a genuine liability
(the post-TP2 runner give-back) — note it as a **candidate exit design for any future strategy**,
not for this soak.

---

## 1. The two models (precise definitions, with friction)

Everything identical except the forward-walk classification and the realized-R formula. Both run on
the **same detected setups, same entry (mss_abs+1 open), same SL/TP1/TP2/TP3 levels, and the same
execution fill** (one `simulate_execution` roll per setup → identical fill_price / fill_size /
total_cost_pct for both models). This isolates ONLY the exit-design difference.

Config 14: TP1_RR = 2.0, TP2_RR = 3.0, TP3_RR = 4.0. Friction = round-trip spread + adverse
selection (`execution.simulate_execution`), charged once per leg as a full proportional round-trip
(the harness convention — see §4). R is normalized so a pre-TP1 stop = exactly −1.0R (risk unit =
|net_sl|, which already absorbs the entry+exit round-trip).

### V_ENTRY (current / LIVE — `check_outcome` + `_calc_realized_r`, `hold_entry`)
50/50 split. TP1 → book half (+1R-ish locked), stop → entry. TP2 → book more, stop stays at entry.
TP3 → WIN. Runner exists. Tiers: `LOSS / PARTIAL_TP1 / PARTIAL_TP2_BE / PARTIAL_TP2 / WIN / EXPIRED`.

### V_FULLTP2 (proposed — `check_outcome_fulltp2` + `_calc_realized_r_fulltp2`)
FULL position, single target = TP2. No partial at TP1, no TP3, no runner. BE-after-TP1 KEPT.
Exact R for each outcome (single exit ⇒ ONE round-trip friction):

| Outcome | Condition | R (with friction) |
|---|---|---|
| **LOSS** | SL hit before TP1 | `net_sl / risk` = **−1.0** (− friction absorbed in risk unit) |
| **WIN** | full position touches TP2 | `net_tp2 / risk` = **TP2_RR − single-exit friction** (≈ +2.48 at rt 0.30%, risk 2.3%) |
| **BREAKEVEN** | TP1 touched, returns to entry (BE stop) | `−rt_cost / risk` ≈ **0 − one round-trip** (≈ −0.13) |
| **EXPIRED_BE** | TP1 touched, hangs between entry & TP2 at window end | priced as **BREAKEVEN** (close at entry = where the BE stop sits — conservative symmetric choice vs V_ENTRY's end-of-window PARTIAL_TP1) |
| **EXPIRED** | never reaches TP1, no SL, window ends | **R = 0** (flat / mark-to-flat — mirrors V_ENTRY EXPIRED exactly) |

---

## 2. Unit verification (`verify_fulltp2_unit.py` — ALL PASS)

Synthetic BUY, entry 100 / SL 98 (1R = 2%) / TP1 104 (2R) / TP2 106 (3R) / TP3 108 (4R), rt 0.30%
(nets: net_tp1 = 3.7, net_tp2 = 5.7, net_tp3 = 7.7, net_sl = −2.3, risk = 2.3%):

| Path | V_FULLTP2 outcome | F2 R | F2 exits | V_ENTRY outcome | ENTRY R | EN exits |
|---|---|---:|---:|---|---:|---:|
| SL before TP1 | LOSS | −1.000 | 1 | LOSS | −1.000 | 1 |
| TP1 → back to entry (BE) | BREAKEVEN | −0.130 | 1 | PARTIAL_TP1 | **+0.739** | 2 |
| TP1 → TP2 (then reverses, no TP3) | **WIN** | **+2.478** | 1 | PARTIAL_TP2 | +2.043 | 2 |
| TP1 → hangs entry↔TP2 → expiry | EXPIRED_BE | −0.130 | 1 | PARTIAL_TP1 | +0.739 | 2 |
| never TP1 → expiry | EXPIRED | 0.000 | 0 | EXPIRED | 0.000 | 0 |
| never TP1 → SL late | LOSS | −1.000 | 1 | LOSS | −1.000 | 1 |

**The two economically-decisive contrasts:**

- **Full-win at the ceiling is IDENTICAL.** On a path that reaches TP3, V_ENTRY books
  `0.5·net_tp1 + 0.5·net_tp3 = +2.478`; V_FULLTP2 books `net_tp2 = +2.478`. Because TP2 is the exact
  midpoint of TP1 and TP3 (2R, 3R, 4R), the scaled blend equals the full-TP2 lock. **Removing the
  TP3 runner gives up ZERO expectancy on TP3-reachers.** (Confirmed live: WIN avg_R +1.364 V_ENTRY
  vs +1.369 V_FULLTP2 on TF_B — essentially equal.)
- **The partial lock-in is where the models diverge.** On TP1-touch-then-reverse, V_ENTRY locks
  +0.739 (half at TP1); V_FULLTP2 gives that up for a −0.130 breakeven. This is V_FULLTP2's *cost*.
- **The runner give-back is where V_FULLTP2 wins.** On TP2-touch-then-reverse, V_ENTRY's runner runs
  back to entry → it books only the TP1 half (PARTIAL_TP2_BE, +0.18–0.20 avg); V_FULLTP2 had already
  locked the FULL position at TP2 (+2.48). This is V_FULLTP2's *gain*.

**Exit count:** V_ENTRY books 2 exits on every TP1-touched path; V_FULLTP2 books 1. (The fee
consequence of that count is §4 — spoiler: zero in the model.)

---

## 3. Headline results — 720d, friction ON

### TF_B — 5M/1H — **PRIMARY (soak B)**

| Metric | V_ENTRY (live) | V_FULLTP2 (proposed) | Winner |
|---|---:|---:|:--|
| n | 12,083 | 12,083 | — |
| **avg_R** | **+0.3750** | **+0.3843** | V_FULLTP2 (+0.0093) |
| WR | 70.0% | 53.2% | V_ENTRY |
| PF | 2.37 | 2.12 | V_ENTRY |
| maxDD (R) | 22.4 | 23.1 | V_ENTRY |
| sum_R | +4531.1 | +4643.1 | V_FULLTP2 (+112) |
| train (IS 70%) | +0.384 | +0.402 | V_FULLTP2 |
| **test (OOS 30%)** | **+0.353** | **+0.344** | **V_ENTRY** |
| **Clears +0.40?** | **NO** | **NO** | — |

### TF_A — 5M/4H — secondary (soak A)

| Metric | V_ENTRY | V_FULLTP2 | Winner |
|---|---:|---:|:--|
| n | 4,746 | 4,746 | — |
| **avg_R** | +0.3709 | **+0.3986** | V_FULLTP2 (+0.0277) |
| WR | 67.7% | 57.1% | V_ENTRY |
| PF | 2.23 | 2.15 | V_ENTRY |
| maxDD (R) | 20.9 | 21.7 | V_ENTRY |
| sum_R | +1760.4 | +1891.9 | V_FULLTP2 (+131) |
| train (IS 70%) | +0.367 | +0.398 | V_FULLTP2 |
| **test (OOS 30%)** | +0.379 | **+0.401** | **V_FULLTP2** |
| Clears +0.40? | NO | NO (+0.3986, just short) | — |

**OOS robustness is split:** V_ENTRY holds up better OOS on the primary TF_B; V_FULLTP2 holds up
better OOS on the secondary TF_A. The IS→OOS decay is larger for V_FULLTP2 on TF_B
(+0.402 → +0.344, −0.058) than for V_ENTRY (+0.384 → +0.353, −0.031) — i.e. V_FULLTP2's tiny IS
edge on TF_B does not survive OOS.

---

## 4. THE FEE DELTA — quantified (the core of the operator's premise)

**In-model fee delta = EXACTLY ZERO (+0.0000 R) on both TFs.**

The validated friction engine (`execution.py` + `_calc_realized_r`) charges each exit leg a FULL
proportional round-trip on its share of the position. For V_ENTRY's two half-legs this sums back to
**one round-trip for the whole position** — identical to V_FULLTP2's single full-position exit:

```
V_ENTRY WIN friction  = 0.5·rt (TP1 half) + 0.5·rt (runner half) = 1·rt   ← one round trip
V_FULLTP2 WIN friction = 1·rt (full position)                     = 1·rt   ← one round trip
```

Measured directly: total in-model friction paid = **+4678.16 R for BOTH models** on TF_B
(**+1941.48 R for both** on TF_A). The partial-exit count (2 vs 1) does **not** multiply fees because
crypto fees and spread are proportional to notional, not per-order.

**The operator's "multiple exit fees" premise only bites under a NON-proportional cost** — a fixed
per-order fee (rare on the venues used), order-book impact at size (negligible at operator size on
liquid majors), or per-discrete-manual-exit slippage. A pessimistic *upper bound* on the latter
(charging the 2nd manual exit a fresh quarter-round-trip on its half-position) would be ~0.07R/signal
— **but that would DOUBLE-COUNT the per-leg round-trip the engine already applies**, so the
realistic, parity-consistent fee saving is **≈ 0**. It is reported here only to bound the claim;
even at the inflated upper bound it does not flip the OOS ranking on TF_B.

> **Bottom line on fees:** the fee-efficiency motivation does not materialize. The reason to prefer
> (or not) V_FULLTP2 is the outcome redistribution in §5, not fee savings.

---

## 5. THE UPSIDE GIVEN UP & THE REAL TRADEOFF — outcome decomposition (TF_B)

The LOSS bucket is **identical** in both models (n=3372, sum_R −3296) — pre-TP1 logic is shared.
Everything else is a redistribution of the TP1-touched population:

| Bucket (TF_B) | V_ENTRY | → V_FULLTP2 | ΔsumR |
|---|---|---|---:|
| **Reaches TP2** (TP3-reachers + TP2-reversers) | WIN n5152 (+7029) + PARTIAL_TP2_BE n1231 (+248) + PARTIAL_TP2 n41 (+62) = **+7339 on 6424** | **WIN n6424 (+8797)** | **+1458** |
| **TP1-touched then reverses** | PARTIAL_TP1 n2264 (**+488**, avg +0.215) | BREAKEVEN n2240 (−854) + EXPIRED_BE n24 (−5) = **−859** | **−1347** |
| **Net** | | | **+111** ≈ +0.009/signal |

Two clean findings:

1. **Removing the TP3 runner gives up essentially NOTHING.** On TP3-reachers the scaled blend already
   equals full-TP2 (WIN avg +1.364 ≈ +1.369). Worse, the runner is a **liability**: on the 1,272
   TP2-then-reverse paths it gives profit back to ~+0.20R, where locking the full position at TP2
   would have booked ~+1.37R. V_FULLTP2 reclaims that → **+1458 R**.
2. **The price V_FULLTP2 pays is the TP1 partial lock-in.** The 2,264 TP1-touch-then-reverse paths
   drop from +0.215 avg (half locked at TP1) to a −0.38 breakeven → **−1347 R**.

On TF_B these nearly cancel (+111 R net). On TF_A the TP2-reversal population is proportionally
larger (PARTIAL_TP2_BE / PARTIAL_TP1 = 0.71 vs TF_B 0.54), so the gain dominates more decisively
(+470 vs −339 = +131 R net, +0.028/signal). This is *why* V_FULLTP2 looks better on TF_A than TF_B.

**The WR collapse (70% → 53%) is cosmetic:** it reflects trading ~2,264 small +0.2R "TP1 wins" for
~2,240 ~0R breakevens, while converting ~1,272 give-backs into full wins. Expectancy barely moves;
the WR number just stops counting the small TP1-locks as wins.

---

## 6. Per-regime (avg_R)

| Regime | TF_B V_ENTRY | TF_B V_FULLTP2 | TF_A V_ENTRY | TF_A V_FULLTP2 |
|---|---:|---:|---:|---:|
| BULL | +0.347 (n4167) | +0.361 | +0.367 (n1684) | +0.395 |
| BEAR | +0.409 (n3912) | +0.412 | +0.332 (n1477) | +0.349 |
| RANGE | +0.371 (n4004) | +0.382 | +0.411 (n1585) | +0.448 |

V_FULLTP2 is uniformly ~+0.01–0.04 higher per regime (most in RANGE, where price chops back through
entry → the runner give-back it fixes is most common). No regime flips the ranking; no regime clears
+0.40 on TF_B for either model.

---

## 7. DSR (deflated for the 2-model selection)

| TF | Model | Sharpe | DSR (n_trials=2) |
|---|---|---:|---:|
| TF_A | V_ENTRY | +0.3659 | 1.0000 |
| TF_A | V_FULLTP2 | +0.3676 | 1.0000 |
| TF_B | V_ENTRY | +0.3759 | 1.0000 |
| TF_B | V_FULLTP2 | +0.3501 | 1.0000 |

At n > 12k with near-identical Sharpes, the 2-trial deflation is trivially passed and **uninformative
for this choice** — both "survive" because the per-trade Sharpe is stable at scale, not because
either exit design is distinguishably better. Honest read: **DSR does not separate the models here**;
the decision rests on OOS test R + PF + maxDD (all of which favor V_ENTRY on the primary TF_B).
Note TF_B V_FULLTP2's Sharpe (0.350) is the lowest of the four despite its higher avg_R — its
all-or-nothing WIN/BE distribution is more volatile per unit of return.

---

## 8. VERDICT (plain)

- **Better model on the primary TF_B:** **a tie that leans V_ENTRY.** V_FULLTP2's avg_R edge is
  +0.0093R/signal in-sample and **evaporates out-of-sample** (V_ENTRY +0.353 vs V_FULLTP2 +0.344);
  V_ENTRY also wins PF (2.37 vs 2.12) and maxDD (22.4 vs 23.1). For a forward-traded soak, the more
  robust, higher-PF, lower-DD model is V_ENTRY.
- **Does either clear +0.40 on TF_B?** **No.** V_ENTRY +0.3750, V_FULLTP2 +0.3843. (TF_A V_FULLTP2
  reaches +0.3986 — still short.) As pre-stated, the tokens are random-walk; the exit model
  redistributes the outcome distribution but does not manufacture headline edge above +0.40.
- **Fee efficiency (the stated motivation):** **not realized.** In-model fee delta = exactly 0. The
  proportional friction engine charges one round-trip per position whether it exits in 1 or 2 legs.
- **What V_FULLTP2 genuinely does well:** it removes the post-TP2 runner give-back (a real liability)
  and is simpler (binary WIN/BE/LOSS). On the 4H-reference TF_A it is cleanly better both IS and OOS
  (+0.3986 / OOS +0.401). The runner adds no expectancy on TP3-reachers and costs on TP2-reversers.

**Frame:** this is a **fee-efficiency / exit-design finding, NOT a gate pass.**

**Action:** **Do NOT adopt into the running soak.** Keep V_ENTRY (no forward reset for a sub-gate,
OOS-neutral-to-worse change on the primary TF). **Record V_FULLTP2 as a candidate exit design** for
any future strategy — particularly on a 4H reference TF, and as the cleaner way to eliminate the
post-TP2 runner give-back — to be re-evaluated only with its own pre-registered forward test if a
new strategy is built. The soaks (A 522562, B 522561) remain on V_ENTRY, untouched.

---

## 9. Reproduce / artifacts

```bash
cd /home/tradeai/breakout-work
python3 verify_fulltp2_unit.py            # synthetic-path unit verification (ALL PASS)
python3 run_exit_model_comparison.py      # 720d TF_A+TF_B, friction ON, in-memory
# → data/exit_model_comparison_results.json
```

- V_FULLTP2 engine: `run_tf_grid.py` → `check_outcome_fulltp2()` + `_calc_realized_r_fulltp2()`
  (additive; V_ENTRY `check_outcome`/`_calc_realized_r` unchanged).
- DB backup: `data/breakout.db.exitcmp_bak.012126`.
- No DB writes, no soak edits, branch not pushed.
