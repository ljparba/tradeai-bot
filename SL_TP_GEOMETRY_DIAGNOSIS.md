# SL/TP Geometry Diagnosis — read-only

**Anomaly reported:** all 3 closed B-soak signals show identical SL/TP %s
(0.5 / 1.0 / 1.5 / 2.0) across different tokens at very different prices.
**Verdict in one line:** **NEITHER engine bug NOR viewer display bug.**
The flat distances are the expected output of the `MIN_SL_PCT = 0.5%` floor
clamp interacting with breakout setups whose structural SL would have been
tighter than 0.5%. **This is the SAME behavior the backtest produced
(80.7% of the validated 2249 backtest signals also had exactly 0.5% SL),
so the soak is correctly running the strategy that produced +0.72 avg_R.
No restart needed. No fix proposed.**

---

## 1. RAW DB values — confirms it's NOT a viewer display bug

Read directly from `breakout.db` via `file:...?mode=ro`:

| id | token | dir | entry | sl | tp1 | tp2 | tp3 |
|---|---|---|---:|---:|---:|---:|---:|
| 1 | LINK | SELL | 8.95400000 | 8.99877000 | 8.86446000 | 8.81969000 | 8.77492000 |
| 2 | BCH  | SELL | 289.70000000 | 291.14850000 | 286.80300000 | 285.35450000 | 283.90600000 |
| 3 | BCH  | SELL | 289.30000000 | 290.74650000 | 286.40700000 | 284.96050000 | 283.51400000 |

Independent geometric reconstruction from these raw prices:

| id | SL dist | TP1 dist | TP2 dist | TP3 dist | R:R TP1 |
|---|---:|---:|---:|---:|---:|
| 1 | 0.5000 % | 1.0000 % | 1.5000 % | 2.0000 % | 2.000 |
| 2 | 0.5000 % | 1.0000 % | 1.5000 % | 2.0000 % | 2.000 |
| 3 | 0.5000 % | 1.0000 % | 1.5000 % | 2.0000 % | 2.000 |

The DB itself contains these flat values. **The viewer is reading them
correctly.** This rules out hypothesis 2 (viewer bug).

---

## 2. Engine code — `compute_breakout_sl_tp` is well-defined

**`breakout_engine.py:430-452`** (the SELL branch is the relevant one here):

```python
elif direction == "SELL":
    sl_struct = sl_anchor * (1.0 + BREAKOUT_SL_INSIDE_BUFFER_PCT)
    sl = max(sl_struct, entry_price * (1.0 + MIN_SL_PCT))         # ← LINE 445
    sl_pct = (sl - entry_price) / entry_price
    if sl_pct > MAX_SL_PCT:
        return None
    risk_dist = sl - entry_price
    tp1 = entry_price - BREAKOUT_TP1_RR * risk_dist               # ← R-multiple
    tp2 = entry_price - BREAKOUT_TP2_RR * risk_dist
    tp3 = entry_price - BREAKOUT_TP3_RR * risk_dist
```

| Constant | Value | Source |
|---|---|---|
| `BREAKOUT_SL_INSIDE_BUFFER_PCT` | 0.001 | `breakout_engine.py:107` |
| `MIN_SL_PCT` | **0.005** (0.5%) | `config.py` |
| `MAX_SL_PCT` | 0.030 (3.0%) | `config.py` |
| `BREAKOUT_TP1_RR` | 2.0 | env from Config 14 |
| `BREAKOUT_TP2_RR` | 3.0 | env from Config 14 |
| `BREAKOUT_TP3_RR` | 4.0 | env from Config 14 |

**The function's intent (per its docstring at lines 412-428):**

> SL placement (back inside the broken level):
>   ... Subject to `MIN_SL_PCT` floor and `MAX_SL_PCT` ceiling — **if the
>   structural SL would be too tight we widen to the floor**; if too wide
>   we return None (caller skips).

This is exactly what's happening: the structural SL is too tight, so it's
being widened to the `MIN_SL_PCT` floor (0.5%).

**TPs are TRUE R-multiples** — the variables are named `risk_dist` and the
TP prices are `entry ± k × risk_dist`. They are NOT computed as fixed %.
They only LOOK like fixed % because the SL got clamped to 0.5%, and 2.0R
off a 0.5% SL IS exactly 1.0%.

---

## 3. Per-signal reconstruction — verifies the engine produced the stored values

Computing what the engine would produce given each signal's recorded `c1_low`
(from `feature_scores_json.c1_zone_key`):

| id | tok | entry | c1_low | sl_struct (=c1_low×1.001) | entry×1.005 | chosen | stored | match |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | LINK | 8.9540 | 8.9680 | 8.9770 | 8.9988 | **8.9988** | 8.99877 | ✓ |
| 2 | BCH  | 289.70 | 290.70 | 290.9907 | 291.1485 | **291.1485** | 291.1485 | ✓ |
| 3 | BCH  | 289.30 | 288.60 | 288.8886 | 290.7465 | **290.7465** | 290.7465 | ✓ |

All 3 stored SLs match the engine's `max(sl_struct, entry × 1.005)` formula
bit-exactly. **The engine is computing what the docstring says it computes.**

For each signal, the MIN_SL_PCT floor (entry × 1.005) was further from
entry than the structural SL (c1_low × 1.001), so `max()` correctly picked
the floor. The structural SL would have been:
- Signal #1: 0.26 % from entry — below the 0.5 % floor → floor wins
- Signal #2: 0.45 % from entry — below the 0.5 % floor → floor wins
- Signal #3: structural SL was BELOW entry (wrong side for SELL) → floor wins by safety

---

## 4. **The decisive cross-check: the BACKTEST produced exactly the same pattern**

This is the key data point that proves the soak is NOT diverging from what
was validated.

### Backtest run_id = 19 — TF comparison A 5M/4H 90-day clean (n = 410):

| SL distance bucket | n | % |
|---|---:|---:|
| **EXACTLY 0.5 % (MIN_SL_PCT clamp fired)** | **329** | **80.2 %** |
| 0.50-0.55 % | 5 | 1.2 % |
| 0.55-1.00 % | 48 | 11.7 % |
| 1.00-2.00 % | 24 | 5.9 % |
| 2.00-3.00 % | 4 | 1.0 % |

### Backtest run_id = 14 — Original Config 14 / 365-day clean (n = 2249):

| SL distance bucket | n | % |
|---|---:|---:|
| **EXACTLY 0.5 % (MIN_SL_PCT clamp fired)** | **1815** | **80.7 %** |
| 0.50-1.00 % | 283 | 12.6 % |
| 1.00-2.00 % | 122 | 5.4 % |
| 2.00-3.00 % | 29 | 1.3 % |

**~80 % of the validated backtest signals had exactly 0.5 % SL — the same
clamp behavior as the soak.** The remaining 20 % spread across 0.5-3.0 %
where the structural SL was wider than the MIN floor.

**The 3 closed soak signals are in the 80 % bucket. This is the modal
behavior of the strategy as backtested.**

The +0.72 / +0.66 / +0.64 avg_R results from Step 1 + the TF comparison
were computed on a population where 80 % of signals had exactly 0.5 % SL.
The soak is not testing a different strategy.

---

## 5. What this reveals about the strategy's actual shape

The strategy as VALIDATED is effectively **two modes, both intentional**:

| Mode | When it fires | What the geometry looks like |
|---|---|---|
| **A — Structural floor (~80 % of signals)** | When c1_high / c1_low is within ~0.5 % of entry, OR when entry is on the wrong side of the broken level (re-claim before MSS confirmation) | SL exactly **0.5 %**, TPs exactly **1.0 % / 1.5 % / 2.0 %**, R-cascade 2 / 3 / 4 |
| **B — True structural (~20 % of signals)** | When the broken level is meaningfully far from entry (strong break with no recovery) | SL = `c1_level × (1 ± 0.001)` (varies 0.5-3 %), TPs are R-multiples off that — yields varying %s |

The docstring describes mode B (the intent), but in practice mode A
dominates because breakout entries on this universe tend to land close to
the broken level (the MSS-confirm step happens ~minutes after the H4
break, and price typically retraces toward the broken level before
continuation).

**The +0.72 avg_R IS the strategy's edge in this mixed mode, and the
soak is correctly reproducing it.**

---

## 6. Verdict (the format the user asked for)

**HYPOTHESIS 1 (engine bug): REJECTED.**
- The engine code is well-defined and matches its docstring.
- The stored SL values match `max(sl_struct, entry × 1.005)` bit-exactly.
- The TPs ARE true R-multiples — they just look like fixed % because
  the SL got clamped to a fixed value first.
- The BACKTEST that produced +0.72 avg_R used the SAME formula and saw
  the SAME 80 / 20 split. There is no soak-vs-backtest divergence.

**HYPOTHESIS 2 (viewer bug): REJECTED.**
- The viewer reads the stored values verbatim.
- Independent geometric reconstruction from the raw prices produces
  the same SL %, TP %, and R:R that the viewer displays.

**ACTUAL EXPLANATION:** the `MIN_SL_PCT = 0.5 %` floor in `config.py`
overrides the structural SL whenever the structural SL would be tighter
than 0.5 %. This happens for ~80 % of signals on this 12-token / Config 14
universe. The TPs are then R-multiples off the floored SL, producing the
flat 1.0 % / 1.5 % / 2.0 % pattern. The soak's 3 closed signals happen to
all be in the 80 % clamp bucket. As the soak accumulates more signals,
~20 % will exhibit varying structural SLs (0.5-3 %).

---

## 7. What this does NOT propose

- ❌ A fix to the soak (none needed — it's running the validated strategy)
- ❌ A change to `MIN_SL_PCT` (would invalidate Config 14's backtest evidence)
- ❌ A change to the SL formula in `breakout_engine.py` (same)
- ❌ A change to the viewer (the geometry is correctly displayed)
- ❌ A restart of either soak

The 3 closed signals are valid Config-14 outputs. Both soaks continue to
accumulate toward their independent ≥ 30 gates.

---

## 8. What this MIGHT prompt (operator-side considerations — observational only)

These are NOT proposed actions; just food-for-thought the operator might
want to reflect on once forward data accumulates:

1. **Re-read the strategy honestly.** This is a "fixed-percent" strategy
   80 % of the time, with structural SL acting as a tightening for narrow-
   range setups. The strategy is approximately:
   > "Enter breakouts in the trade direction at the next 5M open after MSS.
   > SL at 0.5 % beyond entry (or further if the broken level is more than
   > 0.5 % away). TPs at 1, 1.5, 2 R-multiples (which is 1, 1.5, 2 % when
   > the SL is at the 0.5 % floor)."
2. **The MIN_SL_PCT floor is doing real work.** It prevents absurdly tight
   stops that would be killed by noise. Without it, ~80 % of these signals
   would have sl_pct < 0.5 % and would either get stopped out immediately
   by execution slippage or fail the breakeven-WR economics gate.
3. **If you ever explore an alt-config**, lowering `MIN_SL_PCT` would shift
   more signals to mode-B (structural), at the cost of more sub-0.5 % SLs
   that face higher noise-kill risk. Raising `MIN_SL_PCT` would push more
   signals out via the breakeven-WR economics gate (since tighter TPs at
   higher fee % start failing the gate).
4. **This is NOT urgent.** No action proposed. Just an honest description
   of what the strategy is doing.

---

## 9. Isolation re-check (read-only throughout)

| Item | State |
|---|---|
| All DB queries | `file:...?mode=ro` URI; no writes possible |
| Soak A | PID 458923 cycle 136, 0 errors, alive |
| Soak B | PID 465237 cycle 67, 3 closed (data this diagnosis read), alive |
| Fade soak | PID 393274, alive |
| `signals.db` (fade) | 5,492,736 bytes — **unchanged** |
| Run-3704 pin | mtime 2026-05-30 14:31:11 — **unchanged** |
| `breakout.db` writers | only the two soak PIDs |
| `origin/main` | `af331b9` — **not touched** |
| `origin/breakout-thesis` | `70852df` — **not advanced** |
| Code change in this diagnosis | **NONE** — pure read-only |
