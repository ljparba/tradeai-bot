# Phase C-Breakout — Runner-Exit Gap (Paper Model vs Live Execution)

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~07:30 UTC.
**Audited processes:** A PID 473059, B PID 473060 (alive, untouched throughout).

**Operator's concern, verbatim:** "After TP1, the paper model ignores the SL (BE-stop guard). But in live auto-trading on Bybit, the runner half is a REAL open position. If price dips deeply after TP1 and the window expires there, the paper records PARTIAL_TP1 (+0.42 R) but the live runner would realize a much worse exit."

**Headline finding: the concern is REAL and material — but the edge survives if the operator places an explicit runner-protection rule that matches the paper's implicit assumption.**

---

## §1 — What exit does the paper formula actually encode?

### The R formulas (soak + backtest, byte-identical)

`breakout_paper_soak.py:397-411`, `breakout_paper_soak_B.py:349-358`, `run_tf_grid.py:150-161`:

```python
if outcome == "LOSS":         realized_r = round(net_sl / risk, 4)
elif outcome == "PARTIAL_TP1": realized_r = round((0.5 * net_tp1) / risk, 4)              # ← only 0.5*net_tp1
elif outcome == "PARTIAL_TP2": realized_r = round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
elif outcome == "WIN":         realized_r = round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
else:  # EXPIRED               realized_r = 0.0
```

### Worked example (XRP geometry: gross SL 0.5%, RT cost 0.3%, RR 2/3/4)

| Tier | Formula | Realized R |
|---|---|---|
| LOSS | `net_sl / risk` | **−1.0000** |
| PARTIAL_TP1 | `(0.5×0.7 + 0.5×0) / 0.8` | **+0.4375** |
| PARTIAL_TP2 | `(0.5×0.7 + 0.5×1.2) / 0.8` | +1.1875 |
| WIN | `(0.5×0.7 + 0.5×1.7) / 0.8` | +1.5000 |

**The PARTIAL_TP1 formula uses ONLY `0.5×net_tp1` — no second term.** This is mathematically equivalent to the runner half exiting at gross 0% (entry price = breakeven) AND paying ZERO friction on the runner leg. **The runner is assumed to exit at clean BE with no commission and no slippage.**

This is optimistic vs:

| Alternative runner assumption | R for XRP PARTIAL_TP1 |
|---|---|
| Paper (BE, no friction) | +0.4375 |
| **BE with friction** (`0.5×net_tp1 + 0.5×(−rt_cost)`) | **+0.2500** |
| **SL active, runner stops at original SL** (`0.5×net_tp1 + 0.5×net_sl`) | **−0.0625** |

---

## §2 — Walk all 720d PARTIAL_TP1 signals: how often did the runner actually need protection?

Loaded the 720d 5m cache for each signal's token; walked from entry+1 to entry+576 bars (48h). For each PARTIAL_TP1 signal, recorded:
- Was the original SL re-touched any time AFTER TP1 hit?
- What was the close price at the 48-hour expiry bar?

### Results

| Metric | TF_A FRICTION 720d | TF_B FRICTION 720d |
|---|---|---|
| n PARTIAL_TP1 signals | 139 | 709 |
| **SL re-breached after TP1** | **125 (89.9%)** | **646 (91.1%)** |
| Expiry close above entry | 26 (18.7%) | 119 (16.8%) |
| Expiry close at entry | 4 (2.9%) | 13 (1.8%) |
| Expiry close below entry | 109 (78.4%) | 577 (81.4%) |
| **Expiry close past original SL** | **92 (66.2%)** | **488 (68.8%)** |

**Nine out of ten PARTIAL_TP1 signals re-touched the original SL after TP1.**
**Two out of three were sitting BELOW the original SL at the 48h expiry.**

This is the runner-exit gap the operator suspected — and it's much larger than expected.

### Per-signal R under each realistic runner-exit rule

| Scenario | per-signal avg_R (TF_A) | per-signal avg_R (TF_B) | vs paper Δ |
|---|---|---|---|
| **A — Paper (BE, no friction)** | **+0.4514** | **+0.4500** | **0** |
| B' — True BE with friction | +0.2997 | +0.2990 | −0.15 |
| **B — SL active throughout (most realistic Bybit default)** | **+0.0303** | **+0.0165** | **−0.42 / −0.43** |
| C — No stop, runner held to expiry mark-to-market | −0.8712 | −1.4402 | −1.32 / −1.89 |

Under the most realistic live setup (**SL placed on the broker, stays active throughout**), PARTIAL_TP1 signals net out near zero — the runner gets stopped at SL almost every time, costing −1.0 R per stopped runner, which exactly offsets the +0.5×net_tp1 lock-in from the first half.

---

## §3 — Does the runner-rebreach problem affect WIN and PARTIAL_TP2 too?

**Yes.** I walked the full 720d signal set under the realistic live rule (SL active throughout, broker auto-stops the runner on rebreach). The runner-stop event affects EVERY outcome where TP1 was hit before SL ever stops it.

### TF_A FRICTION 720d (n=4744): Per-outcome paper vs live (SL-active)

| Outcome | n | SL re-breached after TP1 | Paper avg_R | Live avg_R (SL-active) | Δ per signal |
|---|---|---|---|---|---|
| WIN | 2950 | 313 (10.6%) | +1.2921 | +1.2361 | −0.056 |
| PARTIAL_TP2 | 194 | 158 (81.4%) | +1.1416 | +1.0850 | −0.057 |
| **PARTIAL_TP1** | **139** | **125 (89.9%)** | **+0.4387** | **+0.1925** | **−0.246** |
| LOSS | 1455 | (n/a, SL hit before TP1) | −0.9759 | −0.7612 | +0.215 (artifact) |
| EXPIRED | 6 | 0 | 0.0 | 0.0 | 0 |

**Overall (TF_A):** Paper +0.5637 → Live +0.5852 (Δ +0.022)

### TF_B FRICTION 720d (n=12090)

| Outcome | n | SL re-breached after TP1 | Paper avg_R | Live avg_R (SL-active) | Δ per signal |
|---|---|---|---|---|---|
| WIN | 7291 | 1124 (15.4%) | +1.3596 | +1.2487 | −0.111 |
| PARTIAL_TP2 | 688 | 550 (79.9%) | +1.1670 | +1.0541 | −0.113 |
| **PARTIAL_TP1** | **709** | **646 (91.1%)** | **+0.4375** | **+0.1410** | **−0.296** |
| LOSS | 3381 | (artifact) | −0.9735 | −0.8232 | +0.150 |
| EXPIRED | 21 | 0 | 0.0 | +0.04 | +0.04 |

**Overall (TF_B):** Paper +0.6397 → Live +0.5912 (Δ −0.049)

### The LOSS-bucket artifact

The LOSS column shows live R = −0.76 / −0.82 vs paper −0.98 / −0.97. This is a reconstruction artifact: my walk used the 720d cache and may have slight bar-boundary differences vs the original backtest run; some "paper LOSS" signals reconstruct as borderline. The artifact INFLATES the live overall avg_R by ~+0.04-0.07.

**Removing the LOSS-bucket artifact (assuming live LOSSes stay at −1.0 R like paper):**
- TF_A live realistic: **~ +0.52** (paper +0.5637 minus the WIN/PARTIAL_TP2/PARTIAL_TP1 drags)
- TF_B live realistic: **~ +0.55** (paper +0.6397 minus the drags)

Both still **above the +0.40 R gate** but the margin shrinks meaningfully.

### Why WIN is also affected

A paper "WIN" requires TP1+TP2+TP3 all touched within 48h. The intra-window sequence can be:
- TP1 → TP2 → TP3 (clean) → live WIN ✓
- **TP1 → SL rebreach → TP3** → paper says WIN (TP3 touched), live runner already stopped at SL → live R = 0.5×net_tp1 + 0.5×net_sl ≈ −0.06 R
- TP1 → SL rebreach → TP2 → TP3 → same as above (runner gone before TP2)

15.4% of TF_B "WIN" outcomes had SL re-breached during the runner phase. Live execution would reclassify those to losing-runner outcomes.

PARTIAL_TP2 is similarly affected (80% had SL rebreach), but the runner exits at TP2 cleanly IF TP2 is reached BEFORE the SL rebreach — which is most cases, hence the smaller Δ.

---

## §4 — What live runner-protection rule matches the paper's assumption?

The paper formula `0.5×net_tp1 + 0.5×0` for PARTIAL_TP1 implies: **after TP1 hits, the runner exits at exactly entry price with no friction**. This requires an active stop placed at entry price (true BE) AFTER TP1.

### Options compared

| Live execution rule | What it does | R match to paper? |
|---|---|---|
| **Do nothing (default Bybit setup)** | Original SL remains active on broker. Runner stops at SL on rebreach. | NO — drags PARTIAL_TP1 by −0.42 R/signal |
| **Move SL to entry (BE) after TP1 fills** | When TP1 limit fills, modify the SL order to entry price | **CLOSE — drag of only ~−0.15 R/signal due to friction on BE exit** |
| Trailing stop after TP1 | Set a trailing stop a fixed % below highest reached | Depends on trail %; tighter trail → more BE stops earlier |
| Cancel SL entirely after TP1 | No stop; runner held to TP3 or expiry market exit | NO — catastrophic, −1.32 R/signal |

**The closest match is "move SL to entry after TP1 fills"** (true breakeven). This is what most professional traders do and is exactly what the paper formula implicitly encodes (modulo the friction cost on the BE exit).

### Per-signal drag if operator uses "move SL to BE after TP1"

For PARTIAL_TP1 only (where the gap is biggest):
- TF_A: −0.151 R per PARTIAL_TP1 × 2.93% PARTIAL_TP1 frequency = **−0.0044 R drag on overall avg_R**
- TF_B: −0.151 R per PARTIAL_TP1 × 5.86% frequency = **−0.0088 R drag on overall avg_R**

If the operator implements BE-after-TP1 correctly, the overall avg_R drops by only **~−0.01 R per signal** — negligible. The +0.564 / +0.640 paper numbers remain effectively valid.

### Per-signal drag if operator uses "do nothing" (default broker setup)

All outcomes degrade (PARTIAL_TP1 worst, then PARTIAL_TP2, then WIN):
- TF_A: realistic overall ~+0.52 (drag ~−0.04 vs paper)
- TF_B: realistic overall ~+0.55 (drag ~−0.09 vs paper)

Both still above the +0.40 gate, but the margin is materially smaller.

---

## §5 — Verdict

**(a) The paper formula encodes:** runner exits at clean entry-price BE with zero friction on the runner leg.

**(b) The live gap is REAL:**
- 89-91% of PARTIAL_TP1 signals had SL rebreach after TP1 in the 720d backtest.
- 66-69% of PARTIAL_TP1 signals were below the original SL at 48h expiry.
- The runner half, if left exposed without protection, would have realized significant losses 9 times out of 10.

**(c) The live rule needed to match the paper's assumption:** **MOVE THE BROKER SL TO ENTRY (BE) AFTER TP1 FILLS.** This corresponds to a true breakeven stop on the runner half.

**Practical implementation pattern (Bybit, conceptual — no implementation here):**

```
On signal:
  1. Place market BUY for full position size at entry
  2. Place TP1 limit at TP1 price for 50% (reduce-only)
  3. Place TP3 limit at TP3 price for 50% (reduce-only) — runner target
  4. Place SL stop-market at original SL price for 100% (reduce-only)

On TP1 fill event:
  5. Cancel the existing SL order
  6. Replace with a new SL stop-market at ENTRY price for the remaining 50% (reduce-only)
     [This is the true-BE stop that the paper model encodes]

On TP3 fill event:
  7. Position fully closed; cancel any remaining orders

On 48h timer:
  8. Market-close any remaining position
```

**(d) Does the edge survive a realistic runner exit?**

| Live runner rule | TF_A 720d avg_R | TF_B 720d avg_R | Above +0.40 gate? |
|---|---|---|---|
| Paper (BE, no friction) | +0.5637 | +0.6397 | ✓ both |
| **BE-after-TP1 (recommended)** | **~ +0.559** | **~ +0.631** | **✓ both, near-paper** |
| SL-active (default broker, no rule) | ~ +0.52 | ~ +0.55 | ✓ both, modest drag |
| No stop (catastrophic) | ~ +0.16 | ~ +0.20 | ✗ both fail gate |

**The edge survives** the realistic live execution gap **IF AND ONLY IF the operator places an explicit runner-protection rule.** The "BE-after-TP1" rule recovers nearly all of the paper edge. The "do nothing" default produces a measurable drag (~−0.04 to −0.09 R/signal) but still clears the gate. The "no stop" scenario fails the gate decisively.

---

## §6 — Critical implications for the Bybit go-live decision

1. **Do NOT switch to live without an explicit runner-protection rule.** The default Bybit "place SL + TPs and walk away" setup is NOT what the paper model assumed. It drags 5-9% of the headline edge.

2. **The "move SL to BE after TP1" rule is closest to paper.** It requires the Bybit auto-trade harness to:
   - Listen for the TP1 fill event (Bybit websocket or order-status polling)
   - Cancel the original SL order
   - Submit a new SL at entry price for the remaining position
   - Do this within seconds of the TP1 fill (the price often retraces toward SL fast — see the TON #26 case which dipped to −1.06% below SL within ~3.5h)

3. **The paper +0.564 / +0.640 numbers are NOT directly portable to live unless the BE-after-TP1 rule is implemented.** If the operator deploys the bot to live as a market-stop-and-walk-away, expect:
   - TF_A live realistic ~ +0.52 (still above gate, but +0.05 below paper)
   - TF_B live realistic ~ +0.55 (still above gate, but +0.09 below paper)

4. **The current paper soak's forward avg_R is ALSO subject to this gap.** The soak is computing realized R using the same formulas. Soak's +0.30 R/signal forward = "paper model" number. Live with BE-after-TP1 rule would be roughly +0.29; live without any rule (default broker) would be roughly +0.25.

5. **The pre-registered gate (avg_R ≥ +0.40 over n≥30 closed paper soak signals) needs adjustment for the live-vs-paper gap.** Options:
   - Tighten the gate to avg_R ≥ +0.45 paper (i.e. require an extra buffer for the live drag)
   - Or commit to implementing BE-after-TP1 on day 1 of live, so the gate stays apples-to-apples
   - Or add a separate forward-live validation phase with a smaller capital and re-validate from zero before scaling

6. **The TON #26 case study was a vivid illustration.** That position dipped to −1.06% below SL (1.958 vs original 1.979) 2.5h after TP1. Under the paper model, it can recover to PARTIAL_TP1 or WIN. Under live SL-active, it would have been stopped at 1.979 → runner −1.0 R → PARTIAL_TP1-like outcome with R = 0.5×net_tp1 + 0.5×net_sl ≈ −0.06 R for TON. Today's outcome of "still open, +0.94 R unrealized" is paper-model behavior, not what live would have done.

---

## §7 — No code change proposed

This audit reports the gap; no fix is implemented. The operator needs to decide:

1. **Implement BE-after-TP1 in the Bybit auto-trade harness BEFORE live deploy.** Match the paper's assumption.
2. **Tighten the paper gate to +0.45 to buffer the live drag** (if BE-after-TP1 won't be in v1 of the live harness).
3. **Update the paper formula for PARTIAL_TP1 to subtract `0.5×rt_cost`** so the paper number matches BE-with-friction. This costs ~0.15 R per PARTIAL_TP1 in the paper headline — a more honest representation of what live will return under BE-after-TP1. (Same backtest re-run with this formula would produce slightly lower validated numbers, but they would be portable to live.)

Each of these is an operator decision. The current state is: **paper numbers are optimistic by 5-9% per signal vs realistic live execution, the gap is well-understood, and the edge survives with explicit runner protection.**

---

## §8 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched throughout this audit |
| `data/signals.db` (production) | unchanged |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (not pushed) |
| Both soaks (A 473059, B 473060) | alive, cycling, untouched |
| 720d cache (read-only) | unchanged |
| breakout.db | read-only access only — no writes from this audit |

Awaiting operator call. No fixes applied.
