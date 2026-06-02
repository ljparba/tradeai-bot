# Exit-Model Verification — Backtest vs Soak

> **VERDICT: SOAK DIVERGES FROM BACKTEST. CRITICAL impact.**
>
> The soak's `resolve_open_signals` closes signals as PARTIAL_TP1 the moment
> TP1 hits in any cycle — regardless of remaining window time. The backtest's
> `check_outcome` walks the FULL 48 h window and returns the HIGHEST tier
> reached anywhere in it. Quantified on the validated Config 14 / 365-day
> backtest: this difference would convert avg_R from **+0.72 → +0.02**
> (97.2 % of the strategy's edge lost). Of TP1-hits in the backtest, **95.1 %
> continued past TP1** to TP2 or TP3 — they would all be mis-classified as
> PARTIAL_TP1 by the soak.
>
> **No fix applied. Awaiting operator decision.**

---

## 1. Backtest's `check_outcome` — the authoritative reference

Source: `/home/tradeai/breakout-work/run_tf_grid.py:123-147` (used by the TF
comparison runs) and `/home/tradeai/breakout-work/breakout_backtest.py:109+`
(used by the Step 1 grid). Identical logic in both:

```python
def check_outcome(direction, sl, tp1, tp2, tp3, future_bars):
    """Same intrabar SL-first logic as breakout_backtest.check_outcome."""
    tp1_hit = tp2_hit = tp3_hit = sl_hit = False
    for bar in future_bars:                           # ← walks ALL bars
        h, l = bar["h"], bar["l"]
        if direction == "BUY":
            if not sl_hit and not tp1_hit and l <= sl:
                sl_hit = True
                break                                  # ← break ONLY on SL-before-TP1
            if not tp1_hit and h >= tp1: tp1_hit = True
            if tp1_hit and not tp2_hit and h >= tp2: tp2_hit = True
            if tp2_hit and not tp3_hit and h >= tp3: tp3_hit = True
        else:
            if not sl_hit and not tp1_hit and h >= sl:
                sl_hit = True
                break
            if not tp1_hit and l <= tp1: tp1_hit = True
            if tp1_hit and not tp2_hit and l <= tp2: tp2_hit = True
            if tp2_hit and not tp3_hit and l <= tp3: tp3_hit = True
    if sl_hit:   return "LOSS",        0              # ← classify AFTER walking ALL
    if tp3_hit:  return "WIN",         3              #    returns HIGHEST tier
    if tp2_hit:  return "PARTIAL_TP2", 2
    if tp1_hit:  return "PARTIAL_TP1", 1
    return "EXPIRED",                  0
```

Called once per signal at `run_tf_grid.py:233` with the FULL 48-h forward
window as a list (`future` built at lines 227-230, `forward_entry_bars = 576`
for 5M entry):

```python
future = [
    {"h": c_entry["highs"][j], "l": c_entry["lows"][j]}
    for j in range(entry_bar + 1, min(entry_bar + 1 + forward_entry_bars, n_entry))
]
outcome, tp_reached = check_outcome(direction, sl_price, tp1, tp2, tp3, future)
```

### Answers to the 4 spec questions for the BACKTEST

a. **Does it close on TP1?** **NO.** The function keeps walking through all
   `future_bars` after TP1 hits, accumulating `tp2_hit` and `tp3_hit` flags.
b. **Does it walk the full window?** **YES.** `future_bars` is the full 576-bar
   (48 h) slice. The loop only `break`s on `sl_hit AND not tp1_hit` —
   i.e. SL hit BEFORE TP1.
c. **What happens to SL after TP1?** Once `tp1_hit` is True, the SL-check
   guard `if not sl_hit and not tp1_hit` is False, so subsequent bars where
   `low ≤ sl` don't trigger `sl_hit`. This implements the implicit
   "stop-to-breakeven after TP1" — once TP1 hits, SL is effectively ignored,
   the runner can continue toward TP2/TP3.
d. **Final-tier logic?** Returns the **HIGHEST** tier reached. Example: if
   the walk sets `tp1_hit=True, tp2_hit=True, tp3_hit=False`, the elif chain
   skips `tp3_hit`, fires on `tp2_hit` → returns `PARTIAL_TP2`.

---

## 2. Soak's `resolve_open_signals` — what we have now

Source: `/home/tradeai/breakout-work/breakout_paper_soak_B.py:241+` (B; A is
identical structure at `breakout_paper_soak.py:269+`).

Critical bits (post tz-fix):

```python
now_utc = datetime.now(timezone.utc)
for row in open_rows:
    ...
    entry_dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    expiry_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    start_ms = int(entry_dt.timestamp() * 1000) + 5 * 60 * 1000
    end_ms = int(min(now_utc, expiry_dt).timestamp() * 1000)        # ← WINDOW SO FAR
    ...
    # Fetch + walk bars in [start_ms, end_ms]
    tp1_hit = tp2_hit = tp3_hit = sl_hit = False
    for bar in raw:                                                 # ← walks bars-so-far
        h_p = float(bar[2]); l_p = float(bar[3])
        if direction == "BUY":
            if not sl_hit and not tp1_hit and l_p <= sl: sl_hit = True; break
            if not tp1_hit and h_p >= tp1: tp1_hit = True
            if tp1_hit and not tp2_hit and h_p >= tp2: tp2_hit = True
            if tp2_hit and not tp3_hit and h_p >= tp3: tp3_hit = True
        else:
            ...
    if sl_hit:        outcome, tp_reached = "LOSS", 0               # ← CLOSES
    elif tp3_hit:     outcome, tp_reached = "WIN", 3                # ← CLOSES
    elif tp2_hit:     outcome, tp_reached = "PARTIAL_TP2", 2        # ← CLOSES *immediately*
    elif tp1_hit:     outcome, tp_reached = "PARTIAL_TP1", 1        # ← CLOSES *immediately*
    elif now_utc >= expiry_dt:
                      outcome, tp_reached = "EXPIRED", 0            # ← CLOSES
    else:
        continue                                                     # ← stays open ONLY if no flag fired
```

### Answers to the 4 spec questions for the SOAK

a. **Does it close on TP1?** **YES.** The classification chain reaches
   `elif tp1_hit:` (line 309 in B, line 388 in A) and closes the signal
   the moment TP1 is detected — regardless of remaining window time. The
   `continue` (stay-open) branch only fires if NO flag is set.
b. **Does it walk the full window?** **NO.** Each cycle (every 120 s)
   re-fetches bars from `start_ms = entry+5min` to `end_ms = min(now, expiry)`.
   When `now < expiry`, only the bars-so-far are walked. Future bars
   beyond `now` aren't visible.
c. **What happens to SL after TP1?** Same intrabar SL-first guard
   (`if not sl_hit and not tp1_hit`). But this only matters within ONE
   bar — the signal closes at TP1-hit-classification BEFORE another cycle
   can encounter a post-TP1 SL spike.
d. **Final-tier logic?** Returns the highest tier reached AS OF THE LAST
   FETCHED BAR. If TP1 hit in cycle N, classification = PARTIAL_TP1, close.
   The signal does not survive to cycle N+1 where TP2 might be reached.

---

## 3. Realized-R computation — IDENTICAL between soak and backtest

Both compute realized_R via the 50/50 split-exit model.

**Backtest** (`run_tf_grid.py:150-161`):

```python
def _calc_realized_r(outcome, net_tp1, net_sl, net_tp2, net_tp3):
    risk = abs(net_sl) or 0.0001
    if outcome == "LOSS":           return round(net_sl / risk, 4)             # ≈ -1.0
    if outcome == "PARTIAL_TP1":    return round((0.5 * net_tp1) / risk, 4)
    if outcome == "PARTIAL_TP2":    return round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
    if outcome == "WIN":            return round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
    return 0.0  # EXPIRED
```

**Soak A** (`breakout_paper_soak.py:385-394`) — same formula:

```python
if outcome == "LOSS":           realized_r = round(net_sl / risk, 4)
elif outcome == "PARTIAL_TP1":  realized_r = round((0.5 * net_tp1) / risk, 4)
elif outcome == "PARTIAL_TP2":  realized_r = round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
elif outcome == "WIN":          realized_r = round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
else:                           realized_r = 0.0
```

**Soak B** (`breakout_paper_soak_B.py:331-339`) — same formula.

**The R formula per tier is identical.** The divergence is purely in WHICH
tier label gets assigned to a signal. Once the label is decided, both
compute R the same way.

---

## 4. The DIVERGENCE TABLE

| Aspect | BACKTEST | SOAK | Divergence? |
|---|---|---|---|
| When is `check_outcome` called? | Once per signal, at end of strategy walk | Every 120 s (per soak cycle) on all OPEN signals | YES — recurring vs one-shot |
| What bars does the walk see? | ALL 576 bars (full 48 h window) upfront | Bars from `entry+5min` to `min(now, expiry)` — window-so-far | YES — partial vs full |
| Closes on TP1 (within window)? | **NO** — keeps walking, sees if TP2/TP3 also hit | **YES** — `elif tp1_hit:` fires, signal closed immediately | **YES — CRITICAL** |
| Closes on TP2 (within window)? | NO — keeps walking, sees if TP3 also hit | YES — `elif tp2_hit:` fires, signal closed immediately | YES |
| SL after TP1 ignored? | YES (the `not tp1_hit` guard) | YES (same guard) — but signal usually closes before this matters | identical guard, but rare-fire on soak |
| Final tier returned | HIGHEST tier reached anywhere in 48 h window | Highest tier reached in window-so-far at the cycle that first sees ANY tier | YES — biases LOWER tier |
| R formula per tier | identical (50/50 split-exit) | identical | NO |

---

## 5. Quantified impact

### Outcome distribution in the validated backtests

| Backtest | n | WIN | PARTIAL_TP2 | PARTIAL_TP1 | LOSS | EXPIRED |
|---|---:|---:|---:|---:|---:|---:|
| Config 14 / 365d (run_id=14) | 2249 | 1406 (62.5%) | 101 (4.5%) | 77 (3.4%) | 660 (29.3%) | 5 (0.2%) |
| TF A 5M/4H 90d (run_id=19) | 410 | 260 (63.4%) | 24 (5.9%) | 11 (2.7%) | 115 (28.0%) | 0 |
| TF B 5M/1H 90d (run_id=21) | 1132 | 615 (54.3%) | 84 (7.4%) | 89 (7.9%) | 343 (30.3%) | 1 (0.1%) |

### Fraction of TP1-hits that continued past TP1

This is THE key population the soak's premature-close would mis-classify.

| Backtest | TP1 hits | Continued past TP1 | Stopped at TP1 |
|---|---:|---:|---:|
| Config 14 / 365d | 1584 (70.4 % of all) | **1507 (95.1 %)** | 77 (4.9 %) |
| TF A 5M/4H 90d | 295 (72.0 % of all) | **284 (96.3 %)** | 11 (3.7 %) |
| TF B 5M/1H 90d | 788 (69.6 % of all) | **699 (88.7 %)** | 89 (11.3 %) |

**The vast majority of signals that touch TP1 go on to touch TP2 and/or TP3
later in the 48 h window.** Closing at first TP1 hit means under-classifying
88-96 % of TP-hitting signals.

### Estimated avg_R impact if the soak's premature-close logic were applied to the backtest data

For each backtest signal, I re-classified WIN and PARTIAL_TP2 outcomes as
PARTIAL_TP1 (the assumption: the soak would have closed on the first TP1 hit
in every case), then recomputed realized_R using the same formula.

| Backtest | actual avg_R | soak-style avg_R | drop |
|---|---:|---:|---:|
| Config 14 / 365d | **+0.7223** | **+0.0204** | **−97.2 %** |
| TF A 5M/4H 90d | **+0.7586** | **+0.0370** | **−95.1 %** |
| TF B 5M/1H 90d | **+0.6624** | **+0.0148** | **−97.8 %** |

**The soak's premature-close logic would erase 95-98 % of the strategy's
edge as measured by avg_R per signal.** The strategy would appear to
generate near-zero expected value when it actually generates +0.66 to +0.76
per signal in the validated backtest.

---

## 6. Recent forward evidence — corroborates the divergence

Since the tz-fix restart (2026-06-02 ~07:40 UTC), B has emitted and closed
one signal:

| id | tok | dir | entry | sl | tp1 | tp2 | tp3 | opened | closed | result | R |
|---:|---|---|---:|---:|---:|---:|---:|---|---|---|---:|
| 5 | TON | SELL | 2.0380 | 2.0500 | 2.0139 | 2.0019 | 1.9898 | 07:30:00 | 07:39:59 | LOSS | −1.0000 |

This signal hit SL only ~10 min after entry — terminal outcome, premature-
close issue doesn't apply (it never hit TP1). So this single data point
neither confirms nor refutes the premature-close divergence; we'd need a
signal that hits TP1, continues to TP2/TP3, and is currently in flight to
demonstrate the bug LIVE.

But the backtest population data (§5) is unambiguous: 95-98 % of the
strategy's edge depends on signals reaching TP2/TP3 after touching TP1.

---

## 7. What a fix would need to do (description ONLY — NOT applied)

The minimal fix would change the classification elif chain so that only
TERMINAL outcomes close the signal:

```python
# Pseudocode — illustrative, NOT applied:
if sl_hit:                                              # terminal — SL ends the trade
    outcome = "LOSS"; close=True
elif tp3_hit:                                           # terminal — full TP cascade complete
    outcome = "WIN"; close=True
elif now_utc >= expiry_dt:                              # terminal — window ran out
    if tp2_hit:   outcome = "PARTIAL_TP2"; close=True
    elif tp1_hit: outcome = "PARTIAL_TP1"; close=True
    else:         outcome = "EXPIRED";     close=True
else:
    # tp1_hit or tp2_hit but window still open → KEEP open, re-check next cycle
    continue
```

Effectively: once TP1 or TP2 is hit, the signal stays OPEN until either
the SL hits (now blocked by `not tp1_hit` guard so this can't happen
post-TP1), TP3 hits (terminal WIN), or the 48-h window expires (terminal
PARTIAL_TP2 or PARTIAL_TP1 depending on highest tier reached).

### Side-effect: each cycle re-walks bars from `entry+5min` to `now`

Each `resolve_open_signals` call already re-walks all bars from `start_ms`
to `now_utc` every cycle (the state isn't persisted between cycles — the
flags reset to False at line 290). So the same TP1-bar gets seen again in
each cycle, the flags get re-set. With the fix, the signal stays OPEN
through cycles where TP1 is the highest tier-so-far, until eventually
either TP3 hits (close) or 48 h pass (close at the highest tier seen).

### Expected impact magnitude (from §5)

- Avg_R per signal goes from current near-zero back to backtest-consistent
  +0.66 to +0.76 range — restoring the validated strategy's edge.
- Closed-signal count goes DOWN per unit time (each signal stays open
  longer, waiting for TP3/expiry). Median signal lifetime would go from
  current ~10-60 min (close at first TP1) to closer to the median TP3-time
  (which the backtest data suggests is several hours for most signals).
- WIN rate (as a fraction of closed signals) goes from current near-zero
  to backtest's ~54-63 % range.

### Already-closed clean-data signals that would need re-resolution

So far, only **1 signal** has closed since the tz-fix restart: the TON SELL
LOSS at id=5. This was a clean LOSS (SL hit at 07:39, no TP touched) — a
fix wouldn't change its outcome. **Zero re-resolution needed for currently-
closed data.**

But every future signal that hits TP1 would be affected. The bug is silent
until the next TP1-touching signal closes, at which point it would close
as PARTIAL_TP1 even if TP2/TP3 would have been reached.

### What this does NOT propose

- ❌ NOT applying the fix (per operator instruction)
- ❌ NOT restarting either soak
- ❌ NOT modifying the backtest (it's already correct)
- ❌ NOT changing the realized_R formula (already consistent between
  backtest and soak per tier label)
- ❌ NOT changing the locked gate thresholds

---

## 8. Verdict

**The soak's exit logic DIVERGES from the backtest's exit logic in a way
that systematically under-records the strategy's edge by ~95-98 %.**

The divergence is purely in WHEN the outcome label is decided:
- **Backtest:** label = highest tier reached over the FULL 48 h window
- **Soak:** label = first tier reached AT THE CYCLE THAT NOTICES IT, then close

Since 88-96 % of TP1-hit signals in the backtest continue to TP2 or TP3,
the soak's "close on first TP1" logic would mis-classify the vast majority
of TP-touching signals as PARTIAL_TP1 — collapsing the +0.72 backtest
avg_R to ~+0.02.

The gate criteria (avg_R ≥ +0.40, PF ≥ 2.0, WR ≥ 55 %) WOULD FAIL the
soak even though the underlying strategy is performing as backtested,
because the recorded outcomes would systematically under-classify.

**Recommendation status: NOT applied. Awaiting operator decision on:**
1. **Apply the fix** to both A and B (3-line classification reordering per
   file, similar minimal-surgery shape to the tz-fix). Restart both soaks
   after. Estimated impact: avg_R recovery from ~+0.02 to ~+0.66-+0.76
   on subsequent forward signals.
2. **Keep current logic and re-derive the gate** for the actual "all-out
   at TP1" exit model the soak implements. Requires re-running the
   backtest with the same logic to get a fair gate baseline (which would
   show avg_R ≈ +0.02, PF much lower, WR concentration in PARTIAL_TP1
   — completely different gate thresholds).
3. **Hybrid:** apply fix but also offer the operator a "close-at-TP1"
   discipline option for risk-averse execution. Requires more code.

Option 1 (apply fix) restores parity with the validated backtest and is
the minimal change. Option 2 (re-derive gate) is more honest about the
soak's actual behavior but requires redoing the entire Step 1-2 validation
chain.

---

## 9. Isolation re-check (read-only throughout)

| Item | State |
|---|---|
| All queries | `file:...?mode=ro` URI; no writes |
| Soak A | PID 470514 cycle 14, alive (post tz-fix) |
| Soak B | PID 470518 cycle 14, alive (post tz-fix), 1 clean closed signal (TON LOSS) |
| Fade soak | PID 393274, alive |
| `signals.db` (fade) | 5,492,736 bytes — unchanged |
| Run-3704 pin | mtime 2026-05-30 14:31:11 — unchanged |
| `breakout.db` writers | only the two soak PIDs |
| `origin/main` | `af331b9` — not touched |
| `origin/breakout-thesis` | `70852df` — not advanced (tz-fix commit `0df3bf3` still local-only) |
| Code change this diagnosis | **NONE** — pure read-only |
