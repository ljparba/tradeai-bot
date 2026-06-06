# FIB_PULLBACK_ENTRY_TEST — V_CURRENT (market entry) vs V_FIB (0.5–0.618 pullback shield)

**Phase C-Breakout · pre-registered · backtest-only · in-memory (no DB writes)**
Window: 720d (2024-06-10 → 2026-05-31) · Config 14 `LOCKED_KNOBS` · friction ON ·
post-TP2 = **V_ENTRY** (`hold_entry`, the live soak model) · TF_A (5M/4H) + TF_B (5M/1H).

Harness: `run_fib_pullback_entry_test.py` (reuses `run_tf_grid` detection scaffold,
`check_outcome` hold_entry, `apply_friction`, `validation` DSR). One detection pass
per setup emits BOTH variants → exact per-setup pairing. Soaks A 522562 / B 522561 +
fade 512666 untouched · signals.db + Run-3704 unchanged · main untouched · branch not
pushed · `data/breakout.db` backed up (`*.fibtest_bak.142556`). **No adoption proposed.**

---

## 0. The hypothesis & the pre-stated expectation (honesty anchor)

**Operator's structural hypothesis (from TradingView mapping):** the live strategy enters
at the MSS-bar+1 open (immediate market entry, no pullback wait). Many losses were
near-miss stop-outs where price clipped a close SL during normal retracement. If the
strategy instead **waits for a pullback into the fib 0.5–0.618 zone** with the SL **below
that zone**, the entry is at a better price and the SL sits below a *structural* level — so
a stop-out means a *real structural failure*, not noise. The fib zone is a **"shield."**

**Pre-stated expectation (written before the run):** the tokens look random-walk at all
scales (TREND + MEAN_REVERSION exploration). If the fib zone has no intrinsic support
property, the "shield" is an illusion — price passes fib levels at random, so the pullback
entry mostly **redistributes WR-vs-R without improving expectancy**, and the effect should
not be robust. *Either result accepted.*

---

## 1. Pre-registered V_FIB definition (stated BEFORE seeing results — not tuned)

Everything except the entry is EXACTLY Config 14. Both variants share the **same detected
setups** (identical `detect_h4_breakout` + consumed logic); only the entry differs.

| Element | Pre-registered choice |
|---|---|
| **Impulse-leg anchor (BUY)** | `leg_low = C1.low` (structural base of the broken candle range); `leg_high = max(entry-TF highs over [sweep_5m_idx .. mss_bar])` |
| **Impulse-leg anchor (SELL)** | `leg_high = C1.high`; `leg_low = min(entry-TF lows over [sweep_5m_idx .. mss_bar])` |
| **Fib zone** | 0.5 .. 0.618 retracement of that leg |
| **Entry level** | **first touch of 0.5** (pending limit at `fib_0.5`): BUY fills when a forward bar's LOW ≤ `fib_0.5`; SELL when HIGH ≥ `fib_0.5` |
| **SL** | just beyond 0.618: BUY `SL = fib_0.618·(1−buf)` (BELOW zone), SELL `SL = fib_0.618·(1+buf)` (ABOVE zone), `buf = BREAKOUT_SL_INSIDE_BUFFER_PCT = 0.001`; then `MIN_SL_PCT=0.5%` floor / `MAX_SL_PCT=3%` ceiling (mirrors `compute_breakout_sl_tp`) |
| **TP1/2/3** | LOCKED `BREAKOUT_TP*_RR` = 2.0 / 3.0 / 4.0 R from the fib entry |
| **Pullback window** | `H4_BREAKOUT_MSS_HORIZON = 30` entry-TF bars forward from mss_bar. No touch → **NO TRADE (skipped)** |
| **Intrabar** | limit fills at `fib_0.5`; if that SAME fill bar also pierces SL → immediate LOSS (entry-fills-first-then-SL); else outcome from fill_bar+1 |

**Causality / no look-ahead (verified):** fib levels use only bars ≤ `mss_bar`; the pullback
is detected bar-by-bar going forward; `fill_bar > mss_bar` is asserted in code (run passed).
The 30-bar pullback scan and the 576-bar (48h) outcome window are disjoint and forward-only.

**Pre-committed decision rule (verbatim):** V_FIB is a real improvement ONLY IF (1) OOS-test
avg_R ≥ +0.40, AND (2) the gain over V_CURRENT holds OOS, AND (3) it holds across regimes,
AND (4) DSR passes. The +0.40 floor is absolute. A qualifier becomes a **separate fresh-soak
candidate only — never adopted here.**

---

## 2. Headline results (720d, friction, post-TP2 = V_ENTRY)

| TF | variant | n | avg_R | WR% | PF | maxDD | sum_R | avgWin | avgLoss | train | **test (OOS)** | DSR₂ |
|----|---------|---:|------:|----:|---:|------:|------:|-------:|--------:|------:|------:|-----:|
| **A** 5M/4H | V_CURRENT | 4744 | +0.362 | 67.7 | 2.21 | 23.6 | +1718.8 | +0.979 | −0.933 | +0.356 | +0.378 | 1.000 |
| **A** 5M/4H | **V_FIB** | **691** | **+0.824** | **83.6** | **6.48** | **3.0** | +569.3 | +1.165 | −0.920 | +0.785 | **+0.913** | 1.000 |
| **B** 5M/1H | V_CURRENT | 12090 | +0.377 | 70.0 | 2.38 | 18.7 | +4551.8 | +0.929 | −0.917 | +0.386 | +0.355 | 1.000 |
| **B** 5M/1H | **V_FIB** | **2080** | **+0.088** | **54.3** | **1.20** | **43.7** | +183.0 | +0.955 | −0.941 | +0.078 | **+0.111** | 0.653 |

**The two timeframes give OPPOSITE verdicts from identical fib logic:**

- **TF_A:** V_FIB **+0.913 OOS** (vs V_CURRENT +0.378) — clears +0.40 decisively, +0.535 OOS gain, DSR₂=1.0.
- **TF_B:** V_FIB **+0.111 OOS** (vs V_CURRENT +0.355) — fails +0.40, is **−0.244 WORSE** than baseline, DSR₂=0.653.

---

## 3. How often does a breakout actually pull back? (V_FIB takes far fewer trades)

| TF | detected setups | saw 0.5–0.618 pullback & traded | skipped: no_pullback | skipped: econ-gate |
|----|---:|---:|---:|---:|
| A 5M/4H | 7322 | **711 (9.7%)** | 6200 (84.7%) | 411 |
| B 5M/1H | 17131 | **2125 (12.4%)** | 13784 (80.5%) | 1221 |

Only **~10–12% of breakouts retrace into the 0.5–0.618 zone within 30 bars.** The other
~85% run away (or fail) without offering a fib entry → **no trade.** V_FIB is, mechanically,
a **massive trade-rejection filter**, not a better fill on the same trades. After friction n
collapses 4744→691 (TF_A) and 12090→2080 (TF_B).

---

## 4. WR-vs-R tradeoff — was the pre-stated "pure redistribution" right?

The pre-stated expectation was that a better entry would *redistribute* WR↑ / R-per-win↓ at
constant expectancy. **That simple prediction was WRONG on TF_A and irrelevant on TF_B:**

- **TF_A:** V_FIB has BOTH higher WR (83.6% vs 67.7%) **and** higher avg_win (+1.165 vs
  +0.979). It is **not** a redistribution — it is a *different, smaller, selected population*
  with genuinely higher expectancy (+0.46 avg_R). avgLoss is unchanged (−0.92 vs −0.93).
- **TF_B:** WR is LOWER (54.3% vs 70.0%) and avg_win barely higher (+0.955 vs +0.929) →
  net expectancy collapses to +0.09. Here it is worse on both counts.

**Stop-size confound — REFUTED.** Median net risk (`|net_sl|`) is essentially identical
across variants: TF_A V_CURRENT **0.910%** vs V_FIB **0.890%**; TF_B 0.920% vs 0.890%. So
despite the 85–88% MIN_SL-floor-override flag, the *realized* per-trade risk is the same
~0.9% net for both variants — the floor binds on the structural fraction but friction
dominates the net stop, and V_CURRENT's inside-C1 stop lands at the same size. **R units are
directly comparable; the TF_A gain is NOT a tight-stop geometry artifact.**

---

## 5. The SHIELD test (operator's specific observation)

Of V_CURRENT's FULL_SL losses, what did V_FIB do? (per-setup paired)

| TF | V_CURRENT FULL_SL losses | V_FIB **AVOIDED** (no trade) | V_FIB took & **still lost** | V_FIB took & **saved** |
|----|---:|---:|---:|---:|
| A 5M/4H | 1479 | **1001 (67.7%)** | 89 (6.0%) | 389 (26.3%) |
| B 5M/1H | 3436 | **2314 (67.3%)** | 538 (15.7%) | 584 (17.0%) |

**The shield mechanism the operator hypothesized is NOT what reduces losses — selection is.**
On BOTH timeframes, **~67–68% of current losses are "avoided" simply because price never
pulled back into the zone, so V_FIB never traded them.** That is a *trade-rejection* effect,
not an SL-sitting-below-a-structural-level effect (§4 shows the SL is the same ~0.9% size).

When V_FIB *did* enter a setup V_CURRENT lost, the better fill helped on TF_A (389 saved /
478 taken = **81% saved**) but was a coin-flip on TF_B (584 / 1122 = **52% saved**). Same
mechanism, opposite outcome — the "better-entry save rate" is **not a stable property.**

**And it skips winners just as aggressively** (the cost of the filter):

| TF | V_CURRENT positive-R trades | V_FIB **skipped** of them |
|----|---:|---:|
| A 5M/4H | 3358 | **3165 (94.3%)** |
| B 5M/1H | 8871 | **8007 (90.3%)** |

V_FIB discards **90–94% of V_CURRENT's winners.** The surviving residue is favorable on
TF_A and unfavorable on TF_B — the hallmark of **selection variance, not a structural edge.**

---

## 6. Robustness — the decisive evidence

**Per-token V_FIB avg_R** (does the TF_A result generalize, or is it a few tokens?):

- **TF_A (5M/4H):** BTC +1.18, XRP +0.95, BNB +0.92, AVAX +0.92, ETH +0.91, BCH +0.88,
  LINK +0.74, ATOM +0.46, TON +0.42, ADA +0.34, (HBAR +0.66 n3, POL −0.56 n3) →
  **10/12 tokens > +0.40.** Broad within TF_A.
- **TF_B (5M/1H):** best is BNB +0.26; BTC +0.21, BCH +0.21, LINK +0.18, ETH +0.17,
  then XRP/AVAX/ATOM/ADA/TON ≤ +0.06, several negative → **0/12 tokens > +0.40.**

**Per-regime avg_R (V_CURRENT → V_FIB):**

| regime | TF_A V_CURRENT → V_FIB | TF_B V_CURRENT → V_FIB |
|--------|------------------------|------------------------|
| BEAR | +0.327 → **+0.840** | +0.408 → +0.059 |
| BULL | +0.358 → **+0.830** | +0.348 → +0.114 |
| RANGE | +0.400 → **+0.802** | +0.375 → +0.092 |

On TF_A every regime improves and OOS-test (+0.913) exceeds train (+0.785). On TF_B every
regime degrades. **The fib logic is byte-for-byte identical between the two runs — the only
difference is whether the breakout's C1/C2 was defined on a 4H or a 1H candle.** A fib level
with a genuine *intrinsic* support property would help (or hurt) regardless of the reference
candle that framed the breakout. **It strongly helps 4H-framed setups and strongly hurts
1H-framed setups → the effect is NOT a property of the fib level; it is a fragile interaction
with the 4H breakout structure + the fixed 30-bar (≈2.5h) pullback window.**

---

## 7. Decision-rule scorecard

| Gate | TF_A (5M/4H) | TF_B (5M/1H) |
|------|:---:|:---:|
| (1) OOS-test avg_R ≥ +0.40 | ✅ +0.913 | ❌ +0.111 |
| (2) gain over V_CURRENT holds OOS | ✅ +0.535 | ❌ −0.244 |
| (3) holds across regimes | ✅ 3/3 | ❌ 0/3 |
| (4) DSR passes | ✅ 1.000 | ❌ 0.653 |
| **Robustness across the two pre-registered TFs** | ❌ **inverts on TF_B** | ❌ |

TF_A passes all four *numeric* gates; TF_B fails all four. **The experiment does NOT clear
the bar as a whole because the same logic inverts across the two pre-registered timeframes.**

---

## 8. VERDICT

**Waiting for the fib pullback does NOT create a real, robust edge, and the fib zone is NOT
a real support level — it is a random-walk-compatible non-event dressed up by selection.**

- The operator's **"shield" claim is refuted as a mechanism.** V_FIB's loss reduction is
  **67–68% pure trade-rejection** (price never pulled back, so no trade), *not* an SL parked
  below a protective structural level — the net stop is the same ~0.9% as V_CURRENT (§4, §5).
  When V_FIB does enter a current-loss setup, the "save rate" is 81% on TF_A but 52% on TF_B:
  not a stable property.
- The simple **"pure WR-vs-R redistribution at equal expectancy" prediction was wrong on
  TF_A** — there V_FIB genuinely posts higher expectancy (+0.91 OOS, 10/12 tokens, all
  regimes, DSR 1.0, with matched stop size). I report that plainly rather than forcing it
  into the expected box.
- **But that TF_A number is a selected-subsample effect, not a shield.** It rests on trading
  only the ~10% of breakouts that retrace-and-resume, discarding 94% of winners, and — the
  decisive tell — **it completely inverts on TF_B (0/12 tokens, −0.24 vs baseline).** A real
  intrinsic support property of a fib level cannot flip sign because the breakout was framed
  on a 1H instead of a 4H candle. The cross-TF inversion is exactly the **non-robust,
  config-dependent signature of a random-walk artifact**, consistent with the pre-stated
  expectation at the level that matters (no intrinsic edge).

**Is V_FIB's expectancy materially different from V_CURRENT, or the same number via a
different WR/R split?** TF_A: materially different (+0.46 avg_R) but via a *different, smaller
selected population*, not a redistribution — and not reproducible on TF_B. TF_B: materially
WORSE (−0.29 avg_R). Across both pre-registered TFs there is **no consistent expectancy gain.**

---

## 9. Recommendation

**NO adoption. NO fresh-soak candidate at this time.** Per the operator's own discipline, a
qualifier graduates to a separate fresh-soak only if it clears the bar robustly. TF_A clears
the *numeric* gates but **fails the robustness test** (TF_B inversion, 0/12 tokens) and the
*causal* claim (shield = selection, not protection). Promoting the TF_A number to a soak
would be chasing the favorable half of a high-variance, config-dependent split — exactly the
selection-bias trap the methodology exists to prevent.

**No further entry-variant / fib-shield sweeping is warranted.** The entry-timing hypothesis
is not supported as a generalizable edge. The live MSS-bar+1 market entry (V_CURRENT) remains
the correct entry: it is robust across both TFs (+0.36 / +0.38), trades the full setup
population, and does not depend on an arbitrary reference-TF choice.

*(If the operator ever wants to revisit: the ONLY defensible next step would be a dedicated
mechanism-isolating re-test — vary the pullback window and the leg anchor, and explain the
4H-vs-1H inversion FIRST — not a forward soak. Stated for completeness; not recommended.)*

---

### Isolation confirmation
Backtest-only; in-memory (zero `breakout.db` / `signals.db` writes). Soaks A 522562 + B
522561 + fade 512666 alive and untouched; Run-3704 unchanged; main untouched; branch
`breakout-thesis` not pushed; `data/breakout.db` backed up before the run. **Report and STOP.**
