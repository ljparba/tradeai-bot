# BCH LOSS Outcome Diagnosis — read-only

**Operator's observation:** 3 BCH SELL signals all recorded LOSS −1.0 R,
but chart shows BCH price moved DOWN (favorable direction for SELL) after
entry. Did SL spike up first (correct LOSS) or did TPs hit first
(mis-recorded as LOSS = bug)?

> **VERDICT: 2 of 3 BCH "LOSSES" ARE BUGS — the actual forward
> outcomes are PARTIAL_TP2 (winners), not LOSS. Only BCH #4 is a
> genuine LOSS. The recorded LOSSES are an EXTENSION of the timezone
> bug from `LINK_OUTCOME_DIAGNOSIS.md` — the soak's `resolve_open_signals`
> read PRE-entry bars for these signals too. The bug is now revealed to
> be HIDING REAL WINS, not just inflating noise.**

> **Net impact across all 4 B-soak closed signals: recorded total
> −2.56 R vs actual forward ≈ +3.0 R — a >5 R discrepancy in just
> 4 trades. The strategy's edge appears INTACT in forward data; the
> bug is making it look catastrophic.**

> **No fix proposed. Awaiting operator call.**

---

## 1. Per-signal forward reconstruction

For each signal, I fetched fresh 5M BCH klines from Binance starting at
the REAL entry time (`opened_ts` from the DB) and walked them with the
exact intrabar rule the soak uses (SL checked first; `break` on SL hit;
TPs accumulate left-to-right).

### BCH #2 — entry 04:15 UTC, sl 291.1485, tp1/2/3 286.803 / 285.355 / 283.906

```
bar(UTC)       high    low    action
04:20         290.00 289.50
04:25         290.40 289.70
04:30         290.30 289.60   ← high 290.4 max so far; still −0.83% from SL @291.15
04:35         290.10 289.70
04:40         290.30 289.90
04:45         289.90 289.10
[quiet bars elided — price drifting between 287-290]
06:10         288.50 286.70   ← TP1 HIT (low 286.70 ≤ tp1 286.803) ← 1 h 55 min after entry
06:55         285.80 285.10   ← TP2 HIT (low 285.10 ≤ tp2 285.355) ← 2 h 40 min after entry
[continues toward but never reaches tp3 283.906]
07:25         288.20 286.40   ← bounce, but NOT to SL @291.15
```

**Actual forward outcome: PARTIAL_TP2** (TP1 + TP2 hit, SL never touched
in the 3.2 h elapsed since entry).
**SL never spiked above entry +0.50 % at any point.** Max high in the
forward window was 290.40 = +0.24 % above entry — well below the 0.50 %
SL.
**Should have been recorded as: PARTIAL_TP2 ≈ +2.5 R** (split-exit: 0.5 ×
1.0 R + 0.5 × 1.5 R / 0.5 R risk = +2.5 R, modulo fees).
**Stored as: LOSS −1.0 R.**
**ERROR: ≈ −3.5 R per signal.**

### BCH #3 — entry 05:25 UTC, sl 290.7465, tp1/2/3 286.407 / 284.961 / 283.514

```
bar(UTC)       high    low    action
05:30         289.60 288.60
05:35         289.40 288.90
05:40         289.10 288.50
05:45         288.90 288.30
05:50         288.50 287.90
05:55         288.20 287.80
[quiet bars elided]
06:15         287.60 286.20   ← TP1 HIT (low 286.20 ≤ tp1 286.407) ← 50 min after entry
07:00         286.10 284.40   ← TP2 HIT (low 284.40 ≤ tp2 284.961) ← 1 h 35 min after entry
[continues toward but never reaches tp3 283.514]
07:25         288.20 286.40   ← bounce, but NOT to SL @290.75
```

**Actual forward outcome: PARTIAL_TP2** (TP1 + TP2 hit, SL never touched
in the 2.1 h elapsed since entry).
**SL never spiked above entry +0.50 % at any point.** Max high was 289.60
= +0.10 % above entry.
**Should have been: PARTIAL_TP2 ≈ +2.5 R.**
**Stored as: LOSS −1.0 R.**
**ERROR: ≈ −3.5 R per signal.**

### BCH #4 — entry 06:15 UTC, sl 288.5355, tp1/2/3 284.229 / 282.794 / 281.358

```
bar(UTC)       high    low    action
06:20         286.60 285.90
06:25         286.40 286.00
06:30         286.70 286.10
06:35         287.00 286.40
06:40         286.90 286.00
06:45         286.40 285.40
[quiet bars elided]
07:15         288.90 287.30   ← SL HIT (h 288.90 ≥ sl 288.5355, spike +0.627% above entry,
                                 60 min after entry); BREAK — no further bars examined
```

**Actual forward outcome: LOSS** (SL hit at 07:15, 60 minutes after
entry, via a +0.627 % spike above entry. No TP was reached first.)
**Stored as: LOSS −1.0 R.**
**The R-value happens to match by coincidence** — both pre-entry buggy
window AND forward reality produced LOSS, just for different reasons.

---

## 2. The SL-before-TP intrabar rule (irrelevant for these signals — confirmed identical anyway)

`breakout_paper_soak_B.py:288-303` (SELL branch):

```python
if not sl_hit and not tp1_hit and h_p >= sl: sl_hit = True; break
if not tp1_hit and l_p <= tp1: tp1_hit = True
if tp1_hit and not tp2_hit and l_p <= tp2: tp2_hit = True
if tp2_hit and not tp3_hit and l_p <= tp3: tp3_hit = True
```

`run_tf_grid.py:127-135` (the TF-backtest harness):

```python
if direction == "BUY":
    if not sl_hit and not tp1_hit and l <= sl:
        sl_hit = True
        break
    if not tp1_hit and h >= tp1: tp1_hit = True
    ...
```

(SELL mirror is the same shape.)

**Identical SL-first conservative rule.** If a single bar's high ≥ SL
AND low ≤ TP1, the SL is awarded first (the `break` exits the loop with
no further TP checks).

**In none of the 3 BCH bars where TP hits happened did the same bar
also touch the SL.** The intrabar ambiguity rule was NOT tested on
these signals. For example BCH #2 at 06:10: high = 288.50, low = 286.70
— the SL @291.15 is 2.65 % above the bar's high, no ambiguity. Same
pattern for BCH #3 at 06:15. So intrabar conservatism is not the
issue here.

---

## 3. The 0.5 % stop angle — only BCH #4 even brushed the SL

For each signal, the maximum high above entry within the forward window:

| signal | entry | max forward high | max above entry | SL at +0.5 % | did SL trigger? |
|---|---:|---:|---:|---:|---|
| BCH #2 | 289.70 | 290.40 | **+0.24 %** | 291.15 | NO (max +0.24 % < +0.50 %) |
| BCH #3 | 289.30 | 289.60 | **+0.10 %** | 290.75 | NO |
| BCH #4 | 287.10 | 288.90 | **+0.627 %** | 288.54 | YES (spike at 07:15) |

Only BCH #4 had a price spike against the SELL position large enough
to trigger the 0.5 % stop. BCH #2 and #3 never came close to their SLs
— they moved cleanly in the SELL direction and reached PARTIAL_TP2.

**The 0.5 % stop is NOT chronically getting noise-hit on these BCH
signals.** Only 1 of 3 BCH signals saw the SL hit in forward.

The "characteristic" the operator was worried about (0.5 % stop too
tight for BCH noise) is partially true — BCH #4's SL hit was a +0.627 %
spike that retraced 30 minutes later. But for BCH #2 and #3, the
strategy worked exactly as intended on forward data: clean move down,
TP1 + TP2 reached in 50-115 minutes.

---

## 4. The reconciliation table

| sig | recorded outcome | recorded R | **forward actual outcome** | **forward R (approx)** | ERROR per signal |
|---|---|---:|---|---:|---:|
| #1 LINK | PARTIAL_TP1 | **+0.44** | LOSS (SL spike 04:35) | **−1.00** | −1.44 R (over-credited) |
| #2 BCH  | LOSS | **−1.00** | **PARTIAL_TP2** (06:10/06:55) | **+2.50** | **+3.50 R** (under-credited!!) |
| #3 BCH  | LOSS | **−1.00** | **PARTIAL_TP2** (06:15/07:00) | **+2.50** | **+3.50 R** (under-credited!!) |
| #4 BCH  | LOSS | **−1.00** | LOSS (SL spike 07:15) | **−1.00** | 0 (coincidence) |
| TOTAL | mixed | **−2.56** | mixed | **≈ +3.00** | **>5.5 R discrepancy in 4 trades** |

**The bug is HIDING REAL WINS.** The strategy looks like it lost −2.56 R
across 4 trades; the actual forward result is closer to +3.00 R.

This INVERTS the picture from the LINK diagnosis. There I noted "the
strategy looks LESS BAD than it is" because LINK was over-credited.
The BCH signals show the OPPOSITE — the strategy is much better than
the bogus stored outcomes suggest, because winners are being
mis-recorded as losses.

---

## 5. Why does the bug invert direction across these signals?

The bug fetches pre-entry bars from [entry_ts − 2 h + 5 min, now − 2 h]
and walks them with the SL-first intrabar rule. What gets recorded as
the outcome depends entirely on what BCH/LINK happened to be doing in
the −2 h window:

- **LINK pre-entry window (02:20-03:05 UTC)**: BCH price was DECLINING
  toward 8.85 area → bar low 8.849 was ≤ TP1 (8.864) → bogus PARTIAL_TP1
  recorded. Actual forward: price spiked UP through SL → LOSS.
- **BCH #2/#3 pre-entry windows (02:20-02:35 UTC, 03:20-03:35 UTC)**:
  BCH price was DRIFTING UP back toward the H4 range → a small bar high
  was ≥ SL → bogus LOSS recorded. Actual forward: price moved DOWN to
  TP1 and TP2 → real PARTIAL_TP2.
- **BCH #4 pre-entry window (04:20-04:25 UTC)**: bar highs in 290-290.4
  area → bogus SL "hit" recorded. Actual forward: price slowly drifted
  down then spiked up at 07:15 → real SL hit → real LOSS. Coincidental
  match.

So the bug is essentially RANDOMIZING the outcome based on whatever
arbitrary historical bar pattern is in the −2 h window. It produces:
- Coincidental matches when forward direction matches that 2-hour-old
  pattern (BCH #4)
- Inverted false positives when historical bars touched a level the
  forward bars didn't (LINK got bogus TP1, BCH #2/#3 got bogus SL)

**The strategy itself looks fine on the 4 forward-validated signals
(+3 R, 50 % WR with 2 strong PARTIAL_TP2 + 2 LOSS).** This is broadly
consistent with the Config 14 backtest expectation
(+0.549 friction-on avg_R per signal × 4 ≈ +2.2 R), within sampling
noise.

---

## 6. Per-signal verdict

| signal | verdict |
|---|---|
| **LINK #1** | **BUG** — over-credited PARTIAL_TP1 +0.44 R when actual was LOSS −1.0 R |
| **BCH #2** | **BUG** — recorded LOSS −1.0 R when actual was PARTIAL_TP2 ≈+2.5 R |
| **BCH #3** | **BUG** — recorded LOSS −1.0 R when actual was PARTIAL_TP2 ≈+2.5 R |
| **BCH #4** | LOSS CORRECT (forward also LOSS — but for unrelated reasons; outcome happened to match by regime coincidence) |

**3 of 4 closed signals carry the wrong R-value. 1 of 4 happens to match
forward by coincidence.**

---

## 7. Severity — confirms `LINK_OUTCOME_DIAGNOSIS.md` plus an additional twist

The prior diagnosis flagged the timezone bug as CRITICAL. This BCH
diagnosis adds a NEW observation:

**The bug doesn't just produce noise — it actively MISDIRECTS the
strategy's apparent edge.**

If the strategy's forward edge had been +0 R or negative, the bogus
stored outcomes would have been catastrophic enough that the operator
could just "wait it out and see." But because the bug is HIDING real
WINS (BCH #2 and #3 should have been +2.5 R each), running the soak
to n = 30 with the bug active would produce a profoundly misleading
verdict — likely a soak-FAIL on the locked gate when the actual forward
data was clearing the gate handily.

**Specifically, with 50 % bogus-LOSS rate and 25 % bogus-TP rate
(extrapolating from this 4-signal sample), the soak would converge
to an apparent WR much lower than 67 % and an apparent avg_R much
lower than the +0.549 friction-on backtest expectation. The gate would
likely FAIL even though the strategy is performing as expected
forward.**

---

## 8. What this diagnosis does NOT propose

- ❌ Fix the timezone bug (proposed in sketch form in `LINK_OUTCOME_DIAGNOSIS.md`
   §9 but NOT applied)
- ❌ Delete or rewrite the 4 bogus DB rows
- ❌ Restart either soak
- ❌ Change any threshold

---

## 9. What the operator now knows

1. The timezone bug is REAL and is CRITICAL.
2. The bug is producing **directional misclassification**, not just noise.
   It can both **inflate** outcomes (LINK +0.44 R when actual was −1.0 R)
   AND **hide wins** (BCH #2/#3 LOSS when actual was PARTIAL_TP2).
3. The strategy's actual forward performance on these 4 signals is
   ≈ +3 R (1 LOSS, 1 LOSS-coincidence, 2 PARTIAL_TP2) — broadly
   consistent with the backtest's +0.549 avg_R expectation
   (4 × 0.549 = +2.2 R expected).
4. The 0.5 % stop is NOT chronically getting noise-hit. Only 1 of 3
   BCH signals saw a SL spike in forward (and that one was a +0.627 %
   bounce 60 min after entry). The other 2 moved cleanly to TP1+TP2.
5. The locked ≥30-signal gate cannot be evaluated honestly until the
   timezone bug is fixed AND new clean-data signals accumulate.

---

## 10. Isolation re-check

| Item | State |
|---|---|
| All queries this diagnosis | `file:...?mode=ro` URI; **no writes** |
| Soak A | PID 458923 alive, cycling |
| Soak B | PID 465237 alive, cycling |
| Fade soak | PID 393274, alive, unaffected |
| `signals.db` (fade) | 5,492,736 bytes — **unchanged** |
| Run-3704 pin | mtime 2026-05-30 14:31:11 — **unchanged** |
| `breakout.db` writers | only the two soak PIDs |
| `origin/main` | `af331b9` — **not touched** |
| `origin/breakout-thesis` | `70852df` — **not advanced** |
| Code change this session | **NONE** — pure read-only |
