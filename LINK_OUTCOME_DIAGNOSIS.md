# LINK Signal Outcome Diagnosis — read-only

**Operator's observation:** LINK SELL recorded as PARTIAL_TP1 (+0.4375 R)
closed 03:04:59 UTC; chart shows price later reached TP2 level.
**Question:** correct or bug?

> **VERDICT: CRITICAL OUTCOME-TRACKING BUG in BOTH A and B soaks.**
> The PARTIAL_TP1 outcome is **wrong** — the soak resolved the signal
> using bars from BEFORE the signal was even emitted, not forward bars.
> The actual forward outcome for LINK is **LOSS (-1.0 R)** — the price
> spiked through SL just 20 minutes after entry. **All 4 recorded B-soak
> outcomes are bogus.** Root cause: `datetime.timestamp()` called on
> naive datetimes is interpreted as LOCAL time by Python, and the server
> is CEST (UTC+2). Every fetch window is shifted by −2 h, pointing at
> pre-entry historical bars instead of forward bars. **No fix proposed
> — awaiting operator call.**

---

## 1. The temporal smoking gun (DB read-only)

| id | token | dir | opened_ts | closed_at | gap | result | recorded R |
|---|---|---|---|---|---|---|---:|
| 1 | LINK | SELL | 2026-06-02 04:15:00 | 2026-06-02 03:04:59 | **−1 h 10 min** | PARTIAL_TP1 | +0.4375 |
| 2 | BCH  | SELL | 2026-06-02 04:15:00 | 2026-06-02 02:34:59 | **−1 h 40 min** | LOSS | −1.0 |
| 3 | BCH  | SELL | 2026-06-02 05:25:00 | 2026-06-02 03:34:59 | **−1 h 50 min** | LOSS | −1.0 |
| 4 | BCH  | SELL | 2026-06-02 06:15:00 | 2026-06-02 04:24:59 | **−1 h 50 min** | LOSS | −1.0 |

**Every single closed signal has `closed_at` BEFORE `opened_ts`** — a temporal
impossibility. The soak is "resolving" signals using bars that closed before
the signal even emitted.

---

## 2. Root cause — Python timezone interaction in resolve_open_signals

`breakout_paper_soak_B.py:263-268`:

```python
entry_dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
expiry_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
...
start_ms = int(entry_dt.timestamp() * 1000) + 5 * 60 * 1000
end_ms = int(min(now_utc, expiry_dt).timestamp() * 1000)
```

`breakout_paper_soak_B.py:259`:

```python
now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
```

`breakout_paper_soak.py` (A soak) has the **identical** lines at 286, 301-302,
307-308. **Both soaks share this bug.**

### The Python gotcha

`datetime.strptime("2026-06-02 04:15:00", ...)` produces a NAIVE datetime.
Per the Python docs:

> *"`datetime.timestamp()` ... If `self` is naive, it is presumed to represent
> time in the system timezone."*

The system timezone is CEST (UTC+2), verified:

```
Tue Jun  2 09:19:10 CEST 2026
Tue Jun  2 07:19:10 UTC 2026
time.tzname:   ('CET', 'CEST')
time.timezone: -3600s
```

So when the soak does `entry_dt.timestamp()` on the naive UTC value
"04:15:00", Python interprets it as **04:15 CEST = 02:15 UTC**, and returns
the unix ms for 02:15 UTC — **−2 h offset**.

`now_utc = datetime.now(timezone.utc).replace(tzinfo=None)` is also a NAIVE
datetime (the `.replace(tzinfo=None)` strips the tz info). `now_utc.timestamp()`
gets the same −2 h treatment.

Verified empirically:

```
Stored as: '2026-06-02 04:15:00' (intended as UTC)
naive.timestamp() = 1780366500.0  (interpreted as LOCAL by Python)
utcfromtimestamp(ts) = 2026-06-02 02:15:00  ← actual UTC clock time
delta = -2.00 h
```

Both `start_ms` and `end_ms` are shifted by exactly −2 h. The Binance kline
API receives unix ms (UTC) and returns bars whose `openTime` is in that
range — which is **−2 h before the actual entry time**, in the past.

---

## 3. Bar-by-bar evidence — LINK signal

### What the BUGGY soak fetched (PRE-entry window 02:20-03:10 UTC):

```
open_time              high     low    triggers
2026-06-02 02:20:00   8.9050  8.8490  TP1 (low ≤ 8.86446)
2026-06-02 02:25:00   8.9330  8.8940
2026-06-02 02:30:00   8.9360  8.9230
2026-06-02 02:35:00   8.9540  8.9210
2026-06-02 02:40:00   8.9220  8.8910
2026-06-02 02:45:00   8.9330  8.8920
2026-06-02 02:50:00   8.9390  8.9220
2026-06-02 02:55:00   8.9910  8.9280
2026-06-02 03:00:00   8.9890  8.9680   ← last bar evaluated (closed_at 03:04:59)
2026-06-02 03:05:00   9.0170  8.9870   (would-trigger-SL, but bar wasn't reached)
```

The 02:20 bar's low (8.849) **triggered the bogus TP1 hit** before the SELL
signal even existed (signal was emitted with entry time 04:15 UTC, so the
position didn't conceptually exist yet at 02:20 UTC). The recorded PARTIAL_TP1
+0.4375 R came from this pre-entry coincidence.

### What ACTUALLY happened forward (real entry 04:15 UTC onwards):

Re-fetched fresh from Binance just now:

```
open_time              high     low    status
2026-06-02 04:20:00   8.9840  8.9610
2026-06-02 04:25:00   8.9920  8.9600
2026-06-02 04:30:00   8.9980  8.9680
2026-06-02 04:35:00   9.0040  8.9910   ← SL HIT (high 9.004 ≥ sl 8.99877)
```

**The ACTUAL forward outcome was: LOSS (-1.0 R)** at the 04:35 bar — 20
minutes after entry. TP1, TP2, TP3 were NEVER reached forward. The chart
the operator saw with "TP2 level reached" must have been from a DIFFERENT
time window, possibly the pre-entry data the buggy soak used, OR price
levels touched after the position would have already been stopped out at
04:35.

**Recorded outcome: PARTIAL_TP1 +0.4375 R (wrong)**
**Actual outcome: LOSS −1.0 R**
**Error: +1.4375 R per signal (~1.5 R credit for what should be a full loss)**

---

## 4. Bar-by-bar evidence — BCH #4 (sanity-check on a LOSS-recorded signal)

### Recorded: LOSS at 04:24:59 UTC (BEFORE actual entry of 06:15 UTC)

### What the BUGGY soak fetched (PRE-entry window 04:20-04:30 UTC):

```
04:20  h=290.00 l=289.50  SL HIT (h ≥ sl 288.5355)
04:25  h=290.40 l=289.70  SL HIT
04:30  h=290.30 l=289.60  SL HIT
```

### What ACTUALLY happened forward (real entry 06:15 UTC onwards):

```
06:20  h=286.60 l=285.90
06:25  h=286.40 l=286.00
06:30  h=286.70 l=286.10
06:35  h=287.00 l=286.40
...
07:00  h=286.10 l=284.40
07:05  h=286.80 l=284.60
07:10  h=287.40 l=286.70
07:15  h=288.90 l=287.30   ← SL HIT forward (high 288.90 ≥ sl 288.5355)
```

**Recorded: LOSS −1.0 R**
**Actual: ALSO LOSS −1.0 R** (just at 07:15 UTC, not 04:24)

For BCH #4 the recorded R-value is COINCIDENTALLY correct because the
forward outcome is also LOSS in a strong bear market. But the timing and
the basis of the decision is still wrong. Two of the four (BCH #2, #3)
likely have the same pattern — the recorded LOSS happens to match the
forward outcome by coincidence of regime.

**LINK is the giveaway** because the recorded outcome (PARTIAL_TP1) differs
from the actual forward outcome (LOSS).

---

## 5. Exit-model decision tree — verified per `resolve_open_signals`

For completeness, the exit logic itself (the "should runner trail to BE
or hold for TP2/TP3?" question the operator asked) is:

`breakout_paper_soak_B.py:288-303`:

```python
for bar in raw:
    ...
    if direction == "BUY":
        if not sl_hit and not tp1_hit and l_p <= sl: sl_hit = True; break
        if not tp1_hit and h_p >= tp1: tp1_hit = True
        if tp1_hit and not tp2_hit and h_p >= tp2: tp2_hit = True
        if tp2_hit and not tp3_hit and h_p >= tp3: tp3_hit = True
    else:
        if not sl_hit and not tp1_hit and h_p >= sl: sl_hit = True; break
        if not tp1_hit and l_p <= tp1: tp1_hit = True
        if tp1_hit and not tp2_hit and l_p <= tp2: tp2_hit = True
        if tp2_hit and not tp3_hit and l_p <= tp3: tp3_hit = True
```

Then classification at line 303-308:

```python
if sl_hit:        outcome, tp_reached = "LOSS", 0
elif tp3_hit:     outcome, tp_reached = "WIN", 3
elif tp2_hit:     outcome, tp_reached = "PARTIAL_TP2", 2
elif tp1_hit:     outcome, tp_reached = "PARTIAL_TP1", 1
elif now_utc >= expiry_dt: outcome, tp_reached = "EXPIRED", 0
else: continue  # still open
```

The intent: walk ALL forward bars, set highest-TP-reached flag. Then return
the highest tier. The SL-first guard (`if not tp1_hit`) implements the
implicit "move stop to BE after TP1" — once TP1 hits, subsequent SL hits
on the same bar-walk don't count as LOSS; we keep climbing TPs.

**This logic is IDENTICAL to the backtest's `check_outcome`.** When fed
correct forward bars, it correctly tracks WIN / PARTIAL_TP2 / PARTIAL_TP1 /
LOSS / EXPIRED. The exit model is fine; the BUG is which bars get fed in.

**Additional subtle concern**: even with correct timestamps, this loop will
classify a signal as PARTIAL_TP1 the moment TP1 hits (within the window),
even if TP2 has time to hit later. This is correct for the BACKTEST where
ALL 576 future bars are available upfront. But for the SOAK running in
real-time, a signal that has hit TP1 at hour 6 (of a 48-h window) would be
classified PARTIAL_TP1 and the position closed — even though TP2 might hit
in the remaining 42 hours. **This is a SECOND issue** (premature-close on
TP1) but the primary BUG (timezone shift) is masking it for now.

---

## 6. Cross-check vs the BACKTEST

The backtest uses `check_outcome` in `breakout_backtest.py` and `run_tf_grid.py`.
Both walk arrays by INDEX:

```python
future = [
    {"h": c5m["highs"][j], "l": c5m["lows"][j]}
    for j in range(entry_bar + 1, min(entry_bar + 1 + FORWARD_BARS, n5))
]
```

**No `datetime.timestamp()` arithmetic in the outcome path.** The backtest
walks the next N candle-array slots after `entry_bar`, regardless of clock
time. **The backtest is NOT affected by this bug.**

The validated backtest evidence (+0.72 avg_R, +0.549 friction-on, etc.)
stands. Only the LIVE SOAK is corrupted.

---

## 7. Soak liveness + stuck-open check

| Soak | PID | Cycle | Open | Closed | Healthy? |
|---|---:|---:|---:|---:|---|
| Fade | 393274 | 8400+ | — | — | ✓ unaffected (different code path) |
| A | 458923 | 172 | 0 | **0** | ✓ alive cycling, bug not yet fired (no signals to resolve) |
| B | 465237 | 102 | 0 | **4** | ✓ alive cycling, bug fired on all 4 closed signals |
| Viewer | 468868 | — | — | — | ✓ alive (no bug in viewer) |

**No stuck-open positions.** Ironically, the bug causes IMMEDIATE close —
the buggy fetch returns pre-entry bars that almost always have SOME high
or low matching a TP or SL level. Signals never stay OPEN long enough to
get stuck.

A soak has 0 closed because its 4H reference produces few signal candidates
in the current regime — same regime drag finding from `FADE_CRT_DIAGNOSIS.md`.
The moment A emits a signal, it WILL exhibit the same bug.

---

## 8. Severity ranking + scope

### Severity: **CRITICAL** — both soaks must be fixed before forward data is meaningful

| Component | State |
|---|---|
| **Signal EMISSION** (price levels, SL, TPs) | **CORRECT** — no datetime arithmetic on this path |
| **Soak outcome RESOLUTION** | **BROKEN** in both A and B (same buggy code) |
| **Backtest outcome** | **CORRECT** — array-index walks, no timestamp() calls |
| **Viewer display** | **CORRECT** — reads the stored outcomes; if the stored outcomes are bogus, the viewer faithfully displays bogus |
| **Locked gates** | **STRUCTURALLY VALID** but currently being evaluated on bogus data |

### What this invalidates

- All 4 B-soak closed signals are bogus outcomes. The recorded
  PARTIAL_TP1 +0.4375 (LINK) is wrong; actual is LOSS −1.0.
  The 3 BCH LOSS rows happen to match forward by regime coincidence
  but the basis of decision is still wrong.
- All `tracking.sum_R` and `tracking.R_per_day` values in the viewer for
  B (currently −2.5625 R) are wrong; the real number (forward) is closer
  to −3.5 to −4.0 R.
- Future signals from EITHER A or B will hit the same bug.
- The locked ≥ 30-signal gate is unreachable with valid data while the
  bug exists.

### What this does NOT invalidate

- Backtest evidence (+0.72 clean / +0.549 friction-on / TF comparison)
- Pre-registered gate criteria (the threshold values are fine; only the
  observed values are bogus)
- Engine code (`detect_h4_breakout`, `compute_breakout_sl_tp`,
  `compute_crt_trade_economics`) — all correct
- Signal-emit code (price levels stored correctly)
- Viewer code (correctly displays what's in the DB)

---

## 9. Proposed fix (sketch only — NOT applied)

The fix would be a one-line-per-call replacement of naive `.timestamp()`
with tz-aware calls. Two patterns possible:

**Option A — Add tz at parse time** (minimal change):

```python
entry_dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
expiry_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
```

Then `entry_dt.timestamp()` returns the correct UTC unix value.

**Option B — Keep utcfromtimestamp on the receiving end** (changes round-trip):
not recommended; option A is cleaner.

Both A (`breakout_paper_soak.py:301-302`) and B (`breakout_paper_soak_B.py:263-264`)
would need the same change. Plus the `now_utc` definition at A:286 / B:259
can remain naive (it's only used in `min()` against naive datetimes
afterward — that comparison is safe).

After the fix, **both soaks would need a restart** to pick up the new code,
AND the 4 bogus B-soak outcomes would need to be either:
1. Deleted from breakout.db so they don't pollute the gate math, OR
2. Tagged as `BOGUS_PRE_FIX` so the viewer can exclude them

**The fix is NOT applied here. Awaiting operator decision.**

---

## 10. Isolation re-check

| Item | State |
|---|---|
| All queries this diagnosis | `file:...?mode=ro` URI; no writes |
| Soak A | PID 458923 cycle 172, alive |
| Soak B | PID 465237 cycle 102, alive |
| Fade soak | PID 393274, alive |
| `signals.db` (fade) | 5,492,736 bytes — unchanged |
| Run-3704 pin | mtime 2026-05-30 14:31:11 — unchanged |
| `breakout.db` writers | only the two soak PIDs |
| `origin/main` | `af331b9` — not touched |
| `origin/breakout-thesis` | `70852df` — not advanced |
| Code change this diagnosis | **NONE** — pure read-only |
