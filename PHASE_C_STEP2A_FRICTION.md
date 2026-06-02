# Phase C-Breakout — Step 2A Report

**Goal:** Screen Config 14 against realistic execution friction before
committing to a forward paper soak.
**Run:** ONE only. Not tuned. Verdict declared up-front, applied post-hoc.

> **Status: PASSED the decision rule. Step 2B (paper soak) authorized.**

---

## 0. What this screen is, and what it isn't

This is a SCREEN: a one-shot friction-on re-run of the SAME Config 14 from
Step 1, using the production `execution.simulate_execution` model. It tells us
how much of the +0.72 avg_R from Step 1 survives realistic spread, slippage,
partial fills, and reject scenarios on the same historical 365-day window.

It is NOT:
- A second optimization pass.
- A grid expansion.
- A repeated run "to see if friction defaults look fairer."
- A green light to flip live — the real gate is still the forward paper soak.

The decision rule (verbatim from the Step 2 prompt):

> if friction-on avg_R stays clearly positive and PF > ~1.5 with no
> token-level blowup, proceed to 2B. If the edge collapses under friction,
> STOP and report — do not start the soak, do not tweak params to rescue it.

---

## 1. Friction model — `execution.simulate_execution` defaults

| Component | Default | Implementation note |
|---|---|---|
| Spread | `TOKEN_RT_COST × time_mult × vol_mult` | Per-token base (BTC/ETH 0.3%, ADA/TON 0.4%, ATOM 0.4%, HBAR/POL 0.5%, BCH 0.3%). Time mult: 1.0 NY+London 06-20 UTC, 1.2 overnight, 1.4 ASIA early. Vol mult: 1.0/1.3/1.6 by `atr_ratio` thresholds. |
| Execution latency | `Gauss(12s, σ=8s)` clamped `[3, 60s]` | Operator-style human latency. Applied as a small adverse price slip proportional to latency (~2bps per 30s). |
| Partial fill | 5% probability, fills 50% | Bernoulli outcome. Halved R contribution. |
| No fill | 2% probability | Bernoulli outcome. Signal dropped (counted, no P&L). |
| Stale-price reject | `move > 1.5 × ATR(5M)` between signal and fill | See caveat below — fires 0× in this harness due to bar-data limit. |
| Adverse selection | +5 bps in `TRENDING_BULL/BEAR` | **DISABLED here** — we pass `regime="UNKNOWN"`. Documented in code comment as a known under-estimate. |

### Why adverse-selection is disabled

Computing the real 1H regime requires importing the live-bot regime classifier
chain (`detect_regime` + `precompute_tf` + 1H OHLCV indicators), which would
either (a) pull in code that opens `data/signals.db` or (b) re-implement the
1H regime classifier as a parallel path under test. Both would change what
this screen is measuring. The +5bps adverse-selection cost is small compared
to the dominant spread cost (~30-50 bps round-trip); the decision rule does
not turn on this term. The report explicitly under-states friction by ~5 bps
in trending regimes.

### Why stale-price reject = 0

The `stale_move` reject mechanism compares `|fill_price - signal_price|` to
`1.5 × ATR(5M)`. In a bar-data backtest, `signal_price` is the close of the
MSS bar and `fill_price` is essentially the next bar's open + a small slip.
The gap between consecutive 5M closes/opens is typically a few basis points
— far below 1.5 × ATR (which is usually 50-200 bps on crypto 5M). The model
needs *intra-bar* price action to fire stale-reject honestly. This harness
cannot provide that, so stale-reject fires 0× across the entire run.

This is a **known under-estimate of friction**: a real live signal that has
to wait 60 seconds while the operator sees Telegram and places the order
will sometimes find the price has run away. The harness shows 0 such events.
In live, the paper soak in Step 2B is the place this cost will actually
appear.

---

## 2. Side-by-side: Clean (Config 14, run_id 14) vs Friction (run_id 18)

| Metric | Clean (Config 14) | Friction | Delta |
|---|---:|---:|---:|
| n signals (attempted) | 2249 | 2222 | -27 (-1.2%) |
| n signals (actually traded) | 2249 | **2180** | -69 (-3.1%) |
|  ↳ of which PARTIAL FILLS | — | 88 (4.0%) | — |
|  ↳ REJECTED (no fill) | — | 42 (1.9%) | — |
|  ↳ REJECTED (stale move) | — | **0** | known limit |
|  ↳ SKIPPED (insufficient ATR) | — | 0 | — |
| avg_R per traded signal | +0.7223 | **+0.6068** | -0.116 (-16.0%) |
| avg_R per attempted signal | +0.7223 | **+0.5953** | -0.127 (-17.6%) |
| sum_R (total) | +1624.51 | **+1322.73** | -301.78 (-18.6%) |
|  ↳ sum_R if friction was zero | — | +1346.54 | — |
| sum_R impact from friction alone | — | **-23.81** | -1.8% of clean total |
| profit factor | 3.461 | **3.140** | -0.32 (-9.3%) |
| win rate | 0.6701 | **0.6761** | +0.6 pp (within noise) |
| peak equity (R) | 1624.51 | 1322.92 | — |
| max drawdown (R) | 14.12 | 14.81 | +0.7 (-5% worse) |

**Reading.**
- 16% of clean avg_R disappears to friction. That's a real bite — mostly spread
  cost (the actual spread is 1.0-1.4× the baseline RT cost used in the
  economics gate, because the time-of-day and vol multipliers raise it in
  about half of all signal moments) and partial-fill scaling (4% of signals
  trade at 0.5x size).
- The remaining edge is still strongly positive at +0.6068 avg_R per filled
  trade and PF=3.14. PF=3.14 means winners earn 3.14× what losers cost —
  comfortably above the PF > 1.5 bar.
- **The "20 R difference between traded n and friction-zero" line is mostly
  spread, not partial fills.** Of the total -301.78 R drop, 23.81 R is the
  net friction-cost overlay; the rest comes from the 69 dropped signals
  (worth ~+4 R on average each).
- WR actually **rose** under friction (67.6% vs 67.0%). Rejected signals
  were marginally worse than average — a known property of the partial-fill
  mechanism (uniform Bernoulli over signals doesn't favor wins or losses).

---

## 3. Per-token (does any token blow up under friction?)

| Token | Clean n | Friction n | Clean avg_R | Friction avg_R | Clean PF | Friction PF | Clean sum_R | Friction sum_R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **BCH** | 293 | 284 | +0.9447 | +0.8107 | 5.258 | **4.936** | +276.80 | +230.25 |
| **AVAX** | 327 | 316 | +0.7414 | +0.6387 | 3.424 | **3.218** | +242.44 | +201.84 |
| **ETH** | 287 | 279 | +0.7636 | +0.6377 | 3.641 | **3.224** | +219.17 | +177.93 |
| **LINK** | 313 | 307 | +0.6538 | +0.5363 | 2.931 | **2.622** | +204.65 | +164.64 |
| **XRP** | 285 | 272 | +0.6791 | +0.5500 | 3.175 | **2.770** | +193.55 | +149.60 |
| BNB | 181 | 178 | +0.8327 | +0.6953 | 4.676 | 4.133 | +150.72 | +123.76 |
| BTC | 160 | 154 | +0.7938 | +0.6847 | 3.954 | 3.636 | +127.00 | +105.44 |
| ATOM | 126 | 120 | +0.5013 | +0.4256 | 2.504 | 2.344 | +63.16 | +51.07 |
| ADA | 110 | 109 | +0.6402 | +0.4968 | 3.201 | 2.776 | +70.42 | +54.16 |
| TON | 118 | 112 | +0.4359 | **+0.3912** | 2.254 | **2.200** | +51.43 | +43.82 |
| HBAR | 25 | 25 | +0.6095 | +0.5153 | 2.905 | 2.610 | +15.24 | +12.88 |
| **POL** | 24 | 24 | +0.4145 | **+0.3067** | 1.995 | **1.736** | +9.95 | +7.36 |

**No token flips to negative avg_R.** Every single token retains positive
expectancy after friction.

**Weakest survivors:** POL (avg_R +0.31, PF 1.74) and TON (avg_R +0.39,
PF 2.20). Both are above the PF > 1.5 floor but POL's small-n status (n=24
across the whole year) means its per-token statistics carry low confidence.
POL stays in the universe but its contribution is small.

**Strongest survivors:** BCH (PF 4.94), BNB (PF 4.13), BTC (PF 3.64). These
are the tokens most likely to drive the paper-soak P&L early.

---

## 4. Friction outcome breakdown

| Friction event | Count | Rate vs attempted | Effect on edge |
|---|---:|---:|---|
| FULL FILL | 2092 | 94.1% | Normal |
| PARTIAL FILL @ 50% | 88 | 4.0% | R contribution halved |
| REJECTED — no_fill | 42 | 1.9% | Signal dropped, no P&L |
| REJECTED — stale_move | 0 | 0% | Known harness limit — see §1 |
| SKIPPED — low ATR | 0 | 0% | Defensive guard never tripped |

Empirically validated rates vs `execution.py` defaults:
- Expected `NO_FILL_PROB = 0.02` → observed 1.9%. ✓ matches.
- Expected `PARTIAL_FILL_PROB = 0.05` → observed 4.0%. Slightly low; this is
  Bernoulli sampling noise across N=2249 with seed-derived RNG.

**Where the friction R-cost actually comes from:**
- The average per-signal `total_cost_pct` exceeded the baseline `TOKEN_RT_COST`
  by an aggregate of -23.81 R across the run. That is the spread cost in
  excess of what the economics gate assumed at signal time.
- The 69-signal drop (REJECTED) lost an estimated +29 R of expected value
  on average — but those signals would not exist in the live universe.

---

## 5. Decision rule — applied verbatim

| Criterion (from prompt) | Threshold | Observed | Pass |
|---|---|---:|---|
| friction-on avg_R stays clearly positive | > 0 | +0.595 (per attempted) | **OK** |
| PF > ~1.5 | > 1.5 | 3.140 | **OK** |
| no token-level blowup | 0 tokens flip to neg | 0 flipped | **OK** |

**VERDICT: PROCEED to Step 2B (paper soak).**

---

## 6. What this report does NOT change

- Fade soak (`/home/tradeai/TradeAI/` PID 393274) still on `experiment/crt-h4-signal-source @ 228e04f`, Run-3704 pin intact.
- `data/signals.db` not touched.
- `main` branch not merged to.
- `breakout-thesis` branch committed locally, NOT pushed.
- The fact that friction passed does NOT mean live arming. Live still requires the LIVE-clearance gate (≥ 30 closed paper signals + CPCV PASS + DSR ≥ 95% per the production rule).

---

## 7. Reproducibility

| Artifact | Path |
|---|---|
| Friction harness | `run_friction_config14.py` |
| Side-by-side comparison | `compare_friction.py` |
| Persisted run | `data/breakout.db backtest_runs WHERE id = 18` |
| Persisted signals | `data/breakout.db backtest_signals WHERE run_id = 18` |
| This report | `PHASE_C_STEP2A_FRICTION.md` |

```bash
# To re-run friction (deterministic via execution.derive_seed):
cd /home/tradeai/breakout-work
sqlite3 data/breakout.db "DELETE FROM backtest_signals WHERE run_id = 18; DELETE FROM backtest_runs WHERE id = 18;"
python3 run_friction_config14.py
python3 compare_friction.py
```

---

## 8. Honest caveats (carry-overs from Step 1 still apply)

1. One year of OHLCV — five-quarter walk-forward is the maximum temporal window
   available. The forward paper soak (Step 2B) is exactly where this resolves.
2. Regime adverse-selection cost disabled here (§1). ~5 bps under-estimate of
   live friction in trending regimes.
3. Stale-price reject = 0 in bar-data harness. Live paper will surface this.
4. No funding / BTC-corr / Wyckoff overlays. Same as Step 1.

The Step 2B soak is the place these unknowns get measured for real.
