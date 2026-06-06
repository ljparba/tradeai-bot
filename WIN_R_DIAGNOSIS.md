# Phase C-Breakout — WIN-Outcome / R-Value Diagnosis

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-02 ~19:30 UTC.
**Trigger:** ENTRY_TYPE_AUDIT.md claimed "5 WINs = TP3 reached" but stored `realized_r` ≈ +1.5, not the +3.0 that `(0.5×TP1_RR) + (0.5×TP3_RR) = (0.5×2.0) + (0.5×4.0)` would suggest.

---

## §1 — The five WIN rows

Pulled from `breakout.db` read-only.

| id | tok | dir | entry | sl | tp1 | tp2 | tp3 | tp1_hit | tp2_hit | tp3_hit | sl_hit | result | realized_r | opened (UTC) | closed (UTC) | entry_type |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | XRP | SELL | 1.2585 | 1.264792 | 1.245915 | 1.239623 | 1.23333 | 1 | 1 | 1 | 0 | WIN | **1.5000** | 14:15:00 | 15:04:59 | `H4_BREAKOUT_OB_B` |
| 9 | HBAR | SELL | 0.08926 | 0.08986 | 0.08806 | 0.087461 | 0.086861 | 1 | 1 | 1 | 0 | WIN | **1.2957** | 14:25:00 | 19:34:59 | `H4_BREAKOUT_FVG_B` |
| 10 | AVAX | SELL | 8.668 | 8.71134 | 8.58132 | 8.53798 | 8.49464 | 1 | 1 | 1 | 0 | WIN | **1.5000** | 14:15:00 | 15:04:59 | `H4_BREAKOUT_OB_B` |
| 11 | LINK | SELL | 8.791 | 8.834955 | 8.70309 | 8.659135 | 8.61518 | 1 | 1 | 1 | 0 | WIN | **1.5000** | 14:20:00 | 15:04:59 | `H4_BREAKOUT_OB_B` |
| 12 | ADA | SELL | 0.2215 | 0.222722 | 0.219055 | 0.217833 | 0.21661 | 1 | 1 | 1 | 0 | WIN | **1.3221** | 14:20:00 | 15:04:59 | `H4_BREAKOUT_OB_B` |

Every WIN row has `tp1_hit=tp2_hit=tp3_hit=1` and `sl_hit=0` — the soak's stored flags say all three TP levels were crossed and no SL was triggered.

---

## §2 — Forward bar-by-bar reconstruction (independent verify)

Fetched live 5M klines from Binance for each WIN's forward window and applied the backtest's `check_outcome` walk (intrabar SL-first with `not tp1_hit` guard). Each WIN's first TP-touching bars:

| Signal | Walk bars | TP1 first hit | TP2 first hit | TP3 first hit | SL hit |
|---|---|---|---|---|---|
| XRP #8 | 10 × 5M | bar 0 (14:20, low=1.2400 ≤ 1.245915) | bar 1 (14:25, low=1.2278) | **bar 1 (14:25, low=1.2278 ≤ 1.23333)** | no |
| HBAR #9 | 62 × 5M | bar 12 (15:30, low=0.087620 ≤ 0.08806) | bar 52 (18:50, low=0.087260) | **bar 60 (19:30, low=0.086460 ≤ 0.086861)** | no |
| AVAX #10 | 10 × 5M | bar 0 (14:20, low=8.514) | bar 0 (14:20, low=8.514 ≤ 8.53798) | **bar 1 (14:25, low=8.400 ≤ 8.49464)** | no |
| LINK #11 | 9 × 5M | bar 0 (14:25, low=8.580 ≤ 8.70309) | bar 0 (14:25, low=8.580 ≤ 8.659135) | **bar 0 (14:25, low=8.580 ≤ 8.61518)** | no |
| ADA #12 | 9 × 5M | bar 0 (14:25, low=0.2165 ≤ 0.219055) | bar 0 (14:25, low=0.2165 ≤ 0.217833) | **bar 0 (14:25, low=0.2165 ≤ 0.21661)** | no |

**Verdict:** all 5 signals genuinely reached TP3 in the forward window. The WIN label is correct. The `tp_reached=3` and `result='WIN'` are not mislabelled.

---

## §3 — R-value computation

### The soak's WIN formula

[`breakout_paper_soak_B.py:354-356`](breakout_paper_soak_B.py#L354-L356):

```python
elif outcome == "WIN":
    realized_r = round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
```

Where:
- `gross_tp1 = (entry - tp1)/entry * 100` (SELL direction, [B:339](breakout_paper_soak_B.py#L339))
- `gross_tp3 = (entry - tp3)/entry * 100`
- `gross_sl  = (entry - sl)/entry * 100`
- `rt_cost_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100` (round-trip cost in percent)
- `net_tp1 = round(gross_tp1 - rt_cost_pct, 3)` ([B:344](breakout_paper_soak_B.py#L344))
- `net_tp3 = round(gross_tp3 - rt_cost_pct, 3)` ([B:346](breakout_paper_soak_B.py#L346))
- `net_sl  = round(gross_sl - rt_cost_pct, 2)` ([B:347](breakout_paper_soak_B.py#L347)) — note 2-decimal rounding (F1 finding, intentional)
- `risk = abs(net_sl) or 0.001`

This is **friction-inclusive realized R**: friction is subtracted from BOTH the numerator (profit) and the denominator's gross magnitude.

### Reproduction from first principles (all 5 WINs)

Using token round-trip costs from [`ict_engine.py:68-84`](../TradeAI/ict_engine.py#L68-L84) — XRP/AVAX/LINK = 0.3%, HBAR = 0.5%, ADA = 0.4%:

| id | tok | rt% | gross_tp1% | gross_tp3% | gross_sl% | net_tp1 | net_tp3 | net_sl | computed R | stored R | match |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | XRP | 0.30 | 1.000 | 2.000 | -0.500 | 0.7 | 1.7 | -0.8 | **1.5000** | 1.5000 | ✓ |
| 9 | HBAR | 0.50 | 1.344 | 2.688 | -0.672 | 0.844 | 2.188 | -1.17 | **1.2957** | 1.2957 | ✓ |
| 10 | AVAX | 0.30 | 1.000 | 2.000 | -0.500 | 0.7 | 1.7 | -0.8 | **1.5000** | 1.5000 | ✓ |
| 11 | LINK | 0.30 | 1.000 | 2.000 | -0.500 | 0.7 | 1.7 | -0.8 | **1.5000** | 1.5000 | ✓ |
| 12 | ADA | 0.40 | 1.104 | 2.208 | -0.552 | 0.704 | 1.808 | -0.95 | **1.3221** | 1.3221 | ✓ |

**Every stored value reproduces bit-for-bit from the soak's formula given the token's friction.**

### Why is it +1.5 and not +3.0?

The +3.0 figure assumes **gross / frictionless** R-multiples:
- gross WIN R = `(0.5 × TP1_RR) + (0.5 × TP3_RR) = 0.5×2.0 + 0.5×4.0 = +3.0`

The +1.5 figure is the **friction-adjusted realized** R:

For XRP #8 specifically (gross SL = -0.5%, gross TP1 = +1.0%, gross TP3 = +2.0%, RT cost = 0.3% per leg per trade):

| Component | Frictionless | With 0.3% friction | Effect |
|---|---|---|---|
| Numerator: `0.5×TP1 + 0.5×TP3` | `0.5×1.0 + 0.5×2.0 = +1.5%` | `0.5×0.7 + 0.5×1.7 = +1.2%` | **shrinks by 0.3%** (friction on both half-units) |
| Denominator: risk = abs(SL) | `0.5%` | `0.8%` | **grows by 0.3%** (friction added to risk) |
| Realized R | `1.5 / 0.5 = +3.0` | `1.2 / 0.8 = +1.5` | **R drops 2×** |

The XRP case is dramatic because the gross SL was only 0.5% — friction is 60% of risk. A wider-SL token like HBAR (gross SL ≈ 0.67%) shows a less extreme drop (+1.296 vs gross +3.0).

### Frictionless vs friction-inclusive R per tier (XRP #8 example)

| Tier | Frictionless R | Friction-inclusive R (stored) |
|---|---|---|
| LOSS | −1.0 | **−1.0** |
| PARTIAL_TP1 | +1.0 | **+0.4375** |
| PARTIAL_TP2 | +2.5 | **+1.1875** |
| WIN (TP3) | +3.0 | **+1.5** |

The PARTIAL_TP1 drop is the worst (+1.0 → +0.4375 — a 56% drop) because at TP1 the gross profit is exactly 1× the gross risk, so friction eats nearly half. WIN (TP3) drops 50% (3.0 → 1.5) under the +0.3% / -0.5% friction-to-risk ratio.

---

## §4 — Soak vs backtest R-formula parity

### Side-by-side

**Soak (both A and B, identical):**
```python
risk = abs(net_sl) or 0.001  # B uses 0.001, A uses or 0.001
if outcome == "LOSS":         realized_r = round(net_sl / risk, 4)
elif outcome == "PARTIAL_TP1": realized_r = round((0.5 * net_tp1) / risk, 4)
elif outcome == "PARTIAL_TP2": realized_r = round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
elif outcome == "WIN":         realized_r = round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
else:                          realized_r = 0.0  # EXPIRED
```

**Backtest [`run_tf_grid.py:151-161`](run_tf_grid.py#L151-L161):**
```python
def _calc_realized_r(outcome, net_tp1, net_sl, net_tp2, net_tp3):
    risk = abs(net_sl) or 0.0001  # ← only difference: 0.0001 floor vs soak's 0.001
    if outcome == "LOSS":         return round(net_sl / risk, 4)
    if outcome == "PARTIAL_TP1":  return round((0.5 * net_tp1) / risk, 4)
    if outcome == "PARTIAL_TP2":  return round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
    if outcome == "WIN":          return round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
    return 0.0
```

### Per-tier reproduction (XRP #8 friction-on inputs)

| Tier | Soak R | Backtest R | Match? |
|---|---|---|---|
| LOSS | −1.0000 | −1.0000 | ✓ |
| PARTIAL_TP1 | +0.4375 | +0.4375 | ✓ |
| PARTIAL_TP2 | +1.1875 | +1.1875 | ✓ |
| WIN | **+1.5000** | **+1.5000** | ✓ |

Bit-for-bit identical. The only formula-level difference is the zero-divide guard floor (soak 0.001 vs backtest 0.0001) — both are so small they never affect any real signal (`net_sl` is always ≥ −0.30% with friction; risk floor never kicks in).

### Sanity: does this explain the backtest's avg_R?

If a backtest's average +0.55 R were under the frictionless formula (where every WIN is +3.0), the typical signal would have to be near LOSS to bring the mean down — but the WR is 61.8% in TF_B FRICTION. Avg with frictionless +3.0 WINs and ~60% WR would land near +1.8 R, not +0.55. The +0.55 figure is consistent with the friction-adjusted model where WINs ≈ +1.5 and LOSSes = −1.0:
- ~60% WIN-like × ~+1.0 R (mix of WIN/PARTIAL) + ~40% LOSS × −1.0 = ~+0.20 to +0.60
- Right in range of +0.549 / +0.616 the operator already documented.

The backtest's reference avg_R values that the soak's gate compares against were ALREADY computed under this friction-inclusive formula. **Apples-to-apples.**

---

## §5 — Verdict

**Case (c) is true: +1.5 R is the CORRECT realized R for a TP3-reaching WIN, and the audit's "TP3 reached" claim was also correct. The mismatch is in the operator's interpretation of the expected R value — the +3.0 calculation assumes frictionless half-RR math, but the soak (and the backtest) use friction-adjusted realized R.**

Sub-verdicts:

| Hypothesis | Status |
|---|---|
| (a) R-formula is wrong (computes +1.5 for a true TP3 WIN) | **FALSE** — formula is correct under friction-inclusive realized-R semantics; matches backtest bit-for-bit. |
| (b) Outcome label is wrong (these are actually PARTIAL_TP1, not WIN — TP3 never reached) | **FALSE** — bar-by-bar reconstruction confirms TP3 was crossed in all 5 signals. tp3_hit=1 is accurate. |
| (c) +1.5 is correct, +3.0 was a frictionless ideal | **TRUE** — the gap is 100% explained by round-trip cost being subtracted from net_tp1/net_tp3 (numerator shrinks) AND added to risk via net_sl (denominator grows). |

### What this means for the gate

The pre-registered gate threshold (`avg_R ≥ +0.40`) was set against the SAME friction-inclusive backtest reference (TF_A `+0.616`, TF_B `+0.549`). The live soak emits friction-inclusive realized R via the same formula. The gate math is therefore self-consistent: **no corruption, no divergence.**

B's current 8 closed signals: 5 WINs (avg ~+1.4 R each) + 3 LOSSes (-1.0 R) = sum_R ≈ 4.10 (DB reports +4.12). Per-signal avg ≈ +0.515 R. That's already above the +0.40 gate threshold; the question is whether it holds across n≥30.

### What this does NOT mean

- It does NOT mean the audit's "TP3 reached" wording was wrong — it was correct.
- It does NOT mean the gate is too lenient or too strict — it's calibrated to the same friction model.
- It does NOT mean the formula should change. Changing to frictionless R would CREATE divergence vs backtest and invalidate the +0.616 / +0.549 reference points.

### Recommendation (operator decision)

Two non-bugs worth noting in the post-soak documentation:
1. **Communication clarity** — when reporting WINs as "TP3 reached," include the friction-adjusted realized R rather than the gross RR multiple, to avoid the +3.0 vs +1.5 confusion. A WIN that crosses TP3 means tier=3, not R=+3.0.
2. **The verbal gate ladder** is: LOSS=−1, PARTIAL_TP1≈+0.4, PARTIAL_TP2≈+1.2, WIN≈+1.5 (per-signal, friction-on, low-fee tokens like XRP/AVAX/LINK). Wider-SL or higher-fee tokens land slightly different (HBAR/ADA reach +1.30, +1.32 on WINs).

**No code fix proposed.** Awaiting operator call.

---

## §6 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched |
| signals.db / Run-3704 pin | unchanged (read-only access only) |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (F3/F4 fix, not pushed) |
| Both soaks (A 473059, B 473060) | ALIVE, untouched by this audit |
| All 3 DB backups | intact (`prefix_bak`, `exitfix_bak`, `lowfix_bak`) |

No fixes applied. Read-only throughout.
