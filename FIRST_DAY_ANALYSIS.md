# FIRST_DAY_ANALYSIS — Soak B (H4_BREAKOUT_PAPER_SOAK_B, PID 486822)

**Scope:** ONE day of forward paper data — 2026-06-03, ~18h (first close 05:34 → last 23:19 UTC).
**Result under analysis:** 33 closed signals, avg_R −0.394, sum_R −13.0R.
**Purpose:** understand the *structure* of the first-day loss so we read the coming days
correctly. This is NOT a verdict on the strategy. One day is statistically light and not
conclusive either way. **No code, config, soak, DB, or pin was touched. No change proposed.**

Data sources (all read-only): `breakout-work/data/breakout.db`
(`source='H4_BREAKOUT_PAPER_SOAK_B'`) + Binance public 5m/15m klines fetched live for
2026-06-03 (the 720d OHLCV cache ends 2025-06-01 and does not cover the soak day; the
live `results` rows have empty `mfe_pct`/`mae_pct`, so MFE was reconstructed from real bars).

---

## 1. Correlated clusters — are these 33 *independent* bets? (NO)

Grouping by entry time, the day is NOT 33 independent bets. It is a handful of
near-simultaneous, same-direction breakout bursts (crypto cross-correlation = one bet, not N).

**Same-direction bursts within ~20 min (n ≥ 3 = one correlated event):**

| Window (UTC) | Dir | n | sum_R | tokens | outcome |
|---|---|---|---|---|---|
| 05:15 | BUY | 7 | **−7.00** | XRP HBAR AVAX LINK BNB TON BCH | LOST (morning range chop) |
| 19:20–19:30 | SELL | 3 | +2.00 | XRP ETH LINK | won (down-leg) |
| 20:40–20:55 | SELL | 6 | **−4.75** | XRP BTC POL ETH LINK ATOM | LOST (evening consolidation whipsaw) |
| 21:15–21:50 | BUY | 7 | +0.50 | LINK XRP ETH BNB BCH AVAX ATOM | mixed |

- The **two losing bursts** (morning 7-BUY −7.0R, evening 6-SELL −4.75R) = **−11.75R of the −13.0R**.
- The remaining 13 singleton signals net only **−1.25R**.
- Net across all n≥3 clusters = −9.25R (the two winning bursts partly offset).

**Collapsing to independent events** (each entry-minute counted once, R averaged):
- Raw framing: 33 signals, avg_R −0.394.
- Collapsed: **23 timestamp-events**, mean event-avg_R **−0.230**.
- By same-direction-burst framing there are really only **~6 independent directional bets**
  on the day (morning BUY, midday SELL, early-eve SELL, late-eve SELL, late-eve BUY, plus
  scattered singles), and **2 of those bets carry nearly the entire loss.**

**Takeaway:** the "33 trades, −13R" framing **overstates the statistical weight** of the loss.
On an independent-bet basis this is closer to *two bad correlated directional calls* in one
session, not 33 separate failures.

---

## 2. Near-miss analysis on the 23 FULL_SL losses (chop vs wrong-direction)

MFE reconstructed from real 5m bars over each trade's [entry → exit] window;
fraction = how far price travelled toward TP1 before reversing to SL.

| Bucket | Definition | n | sum_R | ids |
|---|---|---|---|---|
| **NEAR_MISS** | reached ≥50% of the way to TP1, then reversed to SL | **16** | −16.0 | 32 35 36 37 40 41 43 44 48 50 54 56 57 59 64 66 |
| MID | 25–50% toward TP1 | 5 | −5.0 | 34 46 53 58 65 |
| WRONG_DIR | <25% toward TP1 (wrong from the start) | **2** | −2.0 | 33 (HBAR), 39 (BCH) |

- **70% (16/23) of FULL_SL were near-misses; 91% (21/23) travelled ≥25% toward TP1.**
- Only **2** signals were genuinely wrong-direction.
- Several were extreme near-misses: XRP #40 reached **99.5%** of TP1, XRP #56 **91.0%**,
  LINK #57 **80.8%**, BNB #43 **75.3%** — price all but tagged TP1, then whipped to SL.

**Takeaway:** these were **choppy-session stop-outs**, not wrong-direction signals. The setups
were directionally reasonable; a whippy day reversed them just short of TP1. This directly
argues *against* "the strategy picked wrong."

---

## 3. BUY vs SELL in the same windows (directional vs whipsaw)

| Window (UTC) | BUY | SELL |
|---|---|---|
| MORNING 05–12 | n=10, **−8.75R** | n=0, +0.00R |
| MIDDAY 12–18 | n=2, −2.00R | n=4, **+1.00R** |
| EVENING 18–24 | n=8, −0.50R | n=9, −2.75R |

- **Morning:** only BUYs fired (the 7-token cluster + singles), and all lost. There were **no
  morning SELLs** to confirm/deny — so morning is one-directional, not a clean BUY-vs-SELL test.
  BTC was rangy-up in the morning (see §5), so the alt BUY breakouts had no trend and chopped.
- **Midday:** mixed direction with a real edge to SELL — **SELLs won (+1.0R) while BUYs lost
  (−2.0R)** as BTC rolled over. This is **directional**: the day had a down-trend the strategy
  half-caught (SELL side paid, wrong-side BUYs paid for it).
- **Evening:** both directions net-negative — early-evening SELLs won (+2.0R, 19:20–19:30) on
  the continuation, but the 20:40–20:55 SELL burst lost (−4.75R) into a consolidation, and late
  BUYs were mixed. The evening late-window reads as **whipsaw/consolidation**, not clean trend.

**Takeaway:** not pure chop everywhere — there was a genuine midday down-trend the SELLs
caught. The losses concentrate where direction was *absent* (morning range, evening
consolidation), the wins where a *leg* existed (midday/early-evening down-moves).

---

## 4. Per-token forward (day 1) vs 720d backtest direction

Backtest reference: run 57 (TF_B 5m_1h, CLEAN, NEW720) — matches config_14_B_5m_1h.
All 12 tokens have **positive** backtest avg_R. (Friction run 58 is also all-positive; signs identical.)

| Token | Fwd sum_R (d1) | BT avg_R (720d) | Sign agreement |
|---|---|---|---|
| ETH | +4.75 | +0.713 | **AGREE (+/+)** |
| AVAX | +0.75 | +0.708 | **AGREE (+/+)** |
| XRP | −1.25 | +0.627 | disagree |
| HBAR | −1.00 | +0.297 | disagree |
| BTC | −1.00 | +0.595 | disagree |
| ATOM | −2.00 | +0.447 | disagree |
| POL | −2.00 | +0.265 | disagree |
| TON | −2.00 | +0.374 | disagree |
| LINK | −2.50 | +0.632 | disagree |
| BNB | −3.00 | +0.660 | disagree |
| BCH | −3.75 | +0.680 | disagree |

- **2 agree / 9 disagree** (of 11 traded tokens; ADA did not trade day 1).
- Overwhelming day-1 sign disagreement → **this single day differs from the 720d average**,
  i.e. a regime sample that ran against the backtest mean.

**Caveat:** one day per token is tiny n (mostly 1–5 signals/token). This is a **directional
hint only**, not significant. It says "day 1 was an off-sample day," nothing about the
strategy's expectation.

---

## 5. BTC path overlay (regime window)

BTC 15m closes, 2026-06-03 (UTC), open ≈66,761 → last ≈64,317 (**choppy down-day, ≈−3.7% close-to-close, day range 67,342 → 64,143**):

```
04:00 66340   10:00 67306   16:00 66173   22:00 65328
05:00 67136   11:00 67342   17:00 65715   23:00 64605
06:00 67160   12:00 66973   18:00 65973
07:00 67072   13:00 67122   19:00 65970
08:00 67070   14:00 66904   20:00 65580
09:00 66962   15:00 66526   21:00 65413
```

Three sub-regimes:
1. **05:00–11:00 — choppy range / mild up** (66,960 ↔ 67,342). The 05:15 **7-BUY alt cluster
   fired into this range** with no trend behind it → breakouts poked toward TP1 and
   mean-reverted (the near-misses of §2). **Losses here = range chop.**
2. **11:00–17:00 — clean down-leg** (67,342 → 65,715, ≈−2.4%). The **midday SELLs won**
   (ETH +1.5, AVAX +1.5); a wrong-side BUY (POL) lost. **Wins here = trend.**
3. **17:00–23:00 — lower but choppy / consolidation then drop** (65,970 → 65,328, then
   a late slide to ~64,600). Early-evening SELLs caught the continuation (+2.0R), but the
   **20:40–20:55 SELL burst fired into the ~65,400–65,580 consolidation and got whipsawed
   (−4.75R)** before the final 23:00 leg down.

**Mapping losses/wins onto the path:**

| Window | wins | losses | sum_R | regime |
|---|---|---|---|---|
| MORNING 05–12 | 1 | 9 | −8.75 | choppy range (no trend) |
| MIDDAY 12–18 | 2 | 4 | −1.00 | clean down-leg (SELLs paid) |
| EVENING 18–24 | 7 | 10 | −3.25 | down-then-consolidation (whipsaw) |

**Takeaway:** the loss is **concentrated in the two no-trend windows** (morning range, evening
consolidation), and the wins land in the cleaner down-legs. This is **"bad regime windows,"
not losses scattered uniformly across all conditions.**

---

## VERDICT (one day — refining understanding, not judging the strategy)

The first-day −13R is **best explained by (a) a few correlated clusters caught in
choppy / no-trend windows, with (b) a regime mismatch vs backtest as the natural secondary
frame.** It is **NOT (c) broad wrong-direction signal failure.**

Evidence:
- **Concentration (§1):** two correlated directional bursts (morning 7-BUY −7.0R, evening
  6-SELL −4.75R) carry −11.75R of −13.0R. On an independent-bet basis the day is ~6 bets,
  ~2 of them bad — mean event-avg_R −0.23, not 33 separate failures.
- **Mechanism (§2):** 70% of stop-outs were near-misses (reached ≥50% of TP1), only 2 were
  truly wrong-direction. The setups were directionally fine; a whippy tape reversed them just
  short of target. That is the signature of chop, not of the model picking the wrong side.
- **Direction existed when trend existed (§3, §5):** the strategy's SELLs *won* the midday
  BTC down-leg; it lost specifically where there was no trend (morning range, evening
  consolidation). It half-caught the day's direction.
- **Off-sample day (§4):** 9/11 tokens' day-1 sign disagrees with their all-positive 720d
  backtest avg_R — one day ran against the mean. Expected variance for n=1 day.

**Relatively benign, statistically light, and consistent with a single choppy/failed-range
session — not evidence of broad strategy failure.** It is also *not* evidence the strategy
works. The point of day 1 is to calibrate how we read day 2+.

**What to watch in the coming days (no action now):**
- Do the breakout bursts **run** on clean-trend days (vs chop just short of TP1 on range days)?
  If the near-miss rate stays this high on trending days too, that points to TP1/stop geometry
  rather than regime. If near-misses collapse into wins on trend days, day 1 was regime.
- Does per-token forward begin to **track** the all-positive backtest sign once more days
  accumulate (regression toward the 720d mean), or keep diverging?
- Are losses still **concentrated in correlated bursts**, or do independent single-token bets
  start carrying them?

**No change proposed. Both soaks (A 486821, B 486822) + fade soak alive and untouched;
signals.db + Run-3704 pin unchanged; main untouched; branch not pushed. Read-only — STOP.**
