# Phase C-Breakout — TON #26 Open Position Verification

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~04:58 UTC (281 minutes after position open).
**Audited processes:** A PID 473059, B PID 473060 (both alive, cycling, untouched).

---

## §1 — DB state of TON #26

```
id              = 26
token           = TON
direction       = BUY
entry_price     = 1.994000
sl              = 1.979019    (0.751% below entry)
tp1             = 2.023962    (RR 2.0 from entry)
tp2             = 2.038943    (RR 3.0)
tp3             = 2.053924    (RR 4.0)
status          = OPEN
opened_ts       = 2026-06-03 00:15:00 UTC
expires_at      = 2026-06-05 00:15:00 UTC (48h window, ~44h remaining)
entry_type      = H4_BREAKOUT_FVG_B
mss_quality     = MEDIUM
fvg_quality     = MEDIUM
source          = H4_BREAKOUT_PAPER_SOAK_B
has_results_row = 0   ← no results row yet (still open)
```

**Heartbeat snapshot at audit time:** B cycle 595, open=1, closed=26, ts age 85s. Soak ALIVE & cycling. TON #26 is in B's `WHERE status='OPEN' AND source='H4_BREAKOUT_PAPER_SOAK_B'` query result set.

---

## §2 — Forward bar-by-bar reconstruction (fresh Binance 5M klines)

Fetched 56 TON 5M bars from 00:20 UTC (entry + 5 min, per soak's resolve_open_signals walk-start) to 04:55 UTC. Applied the SAME intrabar walk the soak uses: SL-first with the `not tp1_hit` guard (the BE-stop guard).

### The key bar: TP1 hit at 01:05 UTC

| bar | time | open | high | low | close | event |
|---|---|---|---|---|---|---|
| 0 | 00:20 | 2.0040 | 2.0040 | 1.9870 | 1.9890 | (low 1.987 still ABOVE SL 1.979) |
| 1 | 00:25 | 1.9900 | 2.0000 | 1.9900 | 1.9950 | |
| 2 | 00:30 | 1.9960 | 2.0130 | 1.9910 | 2.0070 | |
| 3 | 00:35 | 2.0080 | 2.0110 | 2.0040 | 2.0080 | |
| 4 | 00:40 | 2.0070 | 2.0200 | 2.0020 | 2.0190 | |
| … | | | | | | |
| **9** | **01:05** | **2.0130** | **2.0260** | **2.0120** | **2.0210** | **TP1 HIT** (high 2.026 ≥ 2.024) |

After bar 9, the `not tp1_hit` guard switches OFF the SL check — exactly per the EXIT_MODEL_VERIFICATION.md fix. Any subsequent low ≤ original SL is now IGNORED (implicit BE-stop / runner mode).

### Post-TP1 dips that the BE-stop correctly ignored

Six bars between 03:35 and 04:00 UTC traded BELOW the original SL of 1.979019:

| bar | time | low | distance below SL | event |
|---|---|---|---|---|
| 39 | 03:35 | 1.9780 | −0.051% | POST-TP1 → ignored by BE-stop |
| 40 | 03:40 | 1.9620 | −0.860% | POST-TP1 → ignored |
| 41 | 03:45 | 1.9590 | −1.012% | POST-TP1 → ignored |
| **42** | **03:50** | **1.9580** | **−1.062%** | **POST-TP1 → ignored (deepest dip)** |
| 43 | 03:55 | 1.9630 | −0.809% | POST-TP1 → ignored |
| 44 | 04:00 | 1.9650 | −0.708% | POST-TP1 → ignored |

**These dips are what the operator saw on TradingView** ("looks like a LOSS by now"). The chart shows price BELOW the SL line. **But the strategy's exit logic correctly does not close on these dips** because TP1 had already been reached at 01:05 UTC, switching the runner into BE-stop mode.

### Current state

| Metric | Value |
|---|---|
| Most recent close (bar 55, 04:55 UTC) | **2.008** |
| Entry | 1.994 |
| Unrealized %  (entry → now) | **+0.702%** |
| Unrealized R  (vs SL distance) | **+0.935 R** |
| TP1 reached? | **Yes** (at 01:05 UTC, ~3.5h ago) |
| TP2 reached? | No (high never crossed 2.039) |
| TP3 reached? | No (high never crossed 2.054) |
| SL hit PRE-TP1? | **No** — first 9 bars all had low ≥ 1.987, never touched 1.979 |
| SL hit POST-TP1? | Yes, 6 times, but **ignored by BE-stop guard** per fixed exit model |

The min low observed across the full walk was **1.958** (at 03:50). The max high was **2.031** (max post-TP1 rally back). Position is currently in **runner mode** — TP1 reached, target is TP3 or expiry.

---

## §3 — Soak resolve health (is the strategy actively evaluating TON #26?)

Pulled the last 50 cycles from `logs/breakout_soak_B.log`:

```
[04:54:34]   cycle 594: new=0, closed_this_cycle=0, open=1, closed_total=26, elapsed=2.6s
[04:56:35]   cycle 595: new=0, closed_this_cycle=0, open=1, closed_total=26, elapsed=2.8s
```

- B has cycled 595 times since restart.
- The most recent 30+ cycles all show `open=1, closed_this_cycle=0` — meaning the soak IS evaluating the open position (TON #26) every 2 minutes, walking the bars, and concluding "still open, no terminal condition met."
- Each cycle takes 2.4-4.1 seconds (no hang).
- The earlier cycle 559 at 03:44 successfully closed BTC #18 and BNB #29 → exit logic IS firing terminals when conditions are met.
- The fixed exit model (commit `870c7f4`) is verifiably the live code (confirmed by the SL-after-TP1 dips being ignored — that's the F-exit-fix behavior).
- TZ fix (commit `0df3bf3`) is live too: the bar walk starts at `entry_dt + 5min` interpreted as UTC (not local-time-shifted by −2h) — verified by the fetched window starting at 00:20 UTC, matching `opened_ts + 5min`.

---

## §4 — Stuck-open risk check

| Risk | State |
|---|---|
| `expires_at` set? | Yes — 2026-06-05 00:15:00 UTC, ~44 hours from now |
| Will expiry close it if no SL/TP3? | Yes — `if now_utc >= expiry_dt → outcome = PARTIAL_TP1, tp_reached = 1` (since TP1 already hit) at the next cycle past expiry |
| Past expiry but still open? | No — expiry is 44h in the future |
| Resolution path UTC-correct? | Yes — bar walk uses `entry_dt.replace(tzinfo=timezone.utc)` per F3-fix |

**Not stuck.** The position has a valid expiry. If TP3 never hits, the expiry-branch will close it as PARTIAL_TP1 at the first cycle after 2026-06-05 00:15 UTC.

---

## §5 — Verdict

**Case (a): TON #26 is CORRECTLY still open.** The position is in runner mode after a legitimate TP1 reach at 01:05 UTC. The post-TP1 dips to 1.958 are intentionally ignored by the implicit BE-stop guard (`not tp1_hit` rule on the SL check) — this is the exact behavior locked in by the EXIT_MODEL_VERIFICATION.md fix (commit `870c7f4`).

### What the operator saw on TradingView, decoded

| Operator's chart observation | Strategy's interpretation |
|---|---|
| Price visited 1.958 (below the drawn SL line 1.979) | Yes — six 5M bars between 03:35-04:00 UTC. |
| Therefore "looks like a LOSS" | Under the OLD (pre-fix) exit model: yes. Under the FIXED model: no, because TP1 was hit 2.5h earlier at 01:05, switching the runner into "stays open until TP3 or expiry, SL ignored." |
| Current price 2.008 vs entry 1.994 | +0.935 R unrealized — actually **above** entry. The position has already crossed back into profit after the dip. |

This is the textbook benefit of the BE-stop guard: TON's dip below SL was a fast 25-min whipsaw that fully recovered. Under the pre-fix logic, this would have been a forced −1.0 R LOSS; under the fixed logic, the runner survived and is back at +0.94 R unrealized. The fix EARNED its keep on this specific position.

### Outlook for TON #26

Three possible outcomes from here:

1. **TP3 hit (high reaches 2.054):** outcome = WIN, R = +1.293 (TON's rt cost 0.5%, so realized R for TP3 is lower than the +1.5 typical of low-fee tokens — same friction math as HBAR #9 which closed at +1.296).
2. **Window expires at 2026-06-05 00:15 UTC** with TP1 reached but TP2/TP3 not: outcome = PARTIAL_TP1, R ≈ +0.422 (per the TON friction model from prior R-verification).
3. **TP2 reached without TP3**, then expiry: outcome = PARTIAL_TP2, R ≈ +1.014.

In ALL three terminal cases, the position closes POSITIVE. There is no longer a path to LOSS — once TP1 was hit, the worst case is EXPIRED at +0.422 R via PARTIAL_TP1.

### Non-issue, no bug

- DB: TON #26 status=OPEN ✓ correct
- Soak: actively resolving, cycle 595 ran 85s ago ✓ correct
- Exit logic: BE-stop guard honored ✓ correct  
- TZ: UTC-aware walk window ✓ correct
- Expiry: 44h future, will eventually close as terminal ✓ correct

**No fix proposed. Position is healthy, will close terminally on TP3 hit or window expiry. Awaiting the natural close.**

---

## §6 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched |
| `data/signals.db` (production) | unchanged |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (not pushed) |
| Soak A 473059 / B 473060 | alive, cycling, untouched throughout this audit |
| All DB backups | intact |

Read-only throughout. No fixes applied.
