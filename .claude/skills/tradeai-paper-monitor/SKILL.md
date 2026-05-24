---
name: tradeai-paper-monitor
description: Monitor the TradeAI paper trading session progress toward the N≥30 closed signals needed for LIVE deployment clearance. Use whenever the user asks about paper trading status, how many signals have been collected, whether the bot is active, current open positions, ETA to live trading, or adaptive learning state. Always trigger on phrases like "paper trading", "paper progress", "how many signals", "ETA to live", "is the bot running", "monitor paper", "signal count", "open positions", "bot active", or "how long until live".
---

# TradeAI Paper Trading Monitor

You are the senior operations analyst for the TradeAI ICT crypto signal bot. Monitor the paper trading session health and give a clear picture of progress toward LIVE readiness.

**Project:** `C:\Users\User\Desktop\TradeAI\`
**Database:** `TradeAI.db`
**LIVE target:** N ≥ 30 closed paper signals with stable WR tracking the backtest baseline
**Backtest baseline (Run-60):** WR ≈ 85.3% | ~2.8 signals/month | z ≈ +4.53

---

## Review Previous Run

Before querying the DB, check for previous paper monitor reports:
```
C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-paper-monitor\
```
Read the most recent file. Extract for comparison:
- Previous closed signal count
- Previous signal rate (signals/month)
- Previous bot status (ACTIVE / STALE)
- Previous OGD state (active or not)
- Any stale signals or inactive tokens flagged last time

Calculate: how many new signals were collected since the last run? Is the rate improving or dropping?

---

## Step 1 — Signal Count and Progress

```sql
SELECT
  COUNT(*) as total_all,
  SUM(CASE WHEN status='CLOSED' OR result IS NOT NULL THEN 1 ELSE 0 END) as closed,
  SUM(CASE WHEN status='OPEN' OR status='ACTIVE' THEN 1 ELSE 0 END) as open,
  MIN(CASE WHEN status='CLOSED' OR result IS NOT NULL THEN created_at END) as first_closed,
  MAX(CASE WHEN status='CLOSED' OR result IS NOT NULL THEN created_at END) as last_closed
FROM signals;
```

Display progress bar:
```
Paper Trade Progress: [████░░░░░░] X/30 (Y%) closed signals
```

## Step 2 — Signal Rate and ETA

From the first and last closed signal timestamps:
- Days elapsed since first closed signal
- Closed signals per month = closed_count / (days_elapsed / 30)
- ETA to N=30 = (30 - closed_count) / rate_per_month → "approximately X months"

If rate < 1/month → flag **LOW SIGNAL RATE**: bot may be filtering too aggressively, or VPN not active during sessions.
If last closed signal > 7 days ago → flag **POSSIBLE BOT INACTIVITY**.

## Step 3 — Current Open Signals

```sql
SELECT token, direction, entry_price, sl_price, tp1_price, created_at
FROM signals WHERE status='OPEN' OR status='ACTIVE'
ORDER BY created_at DESC;
```

For each open signal, calculate:
- Age = current time - created_at
- Flag any signal open for > 7 days as **POTENTIALLY STALE** — may indicate a stuck position

If 0 open signals: note this is normal between signal events.

## Step 4 — Token Activity Check

```sql
SELECT token, COUNT(*) as total_signals,
  SUM(CASE WHEN status='CLOSED' OR result IS NOT NULL THEN 1 ELSE 0 END) as closed,
  MAX(created_at) as last_signal
FROM signals GROUP BY token ORDER BY last_signal DESC;
```

Expected tokens: BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL
- Any expected token with 0 signals → may be incorrectly filtered (check blocked_regimes or FVG filter)
- Any unexpected token appearing → config issue (SOL should not appear)

## Step 5 — Performance Snapshot

```sql
SELECT
  ROUND(AVG(CASE WHEN result='WIN' THEN 1.0 WHEN result='PARTIAL' THEN 0.5 ELSE 0.0 END) * 100, 1) as wr_pct,
  SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
  SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
  SUM(CASE WHEN result='PARTIAL' THEN 1 ELSE 0 END) as partials
FROM signals WHERE status='CLOSED' OR result IS NOT NULL;
```

Compare live WR to Run-60 baseline (85.3%). If N < 10, note the sample is too small for reliable WR comparison.

## Step 6 — Adaptive Learning State

```sql
SELECT token, weight, updated_at FROM token_weights ORDER BY weight DESC;
```

- **OGD not active yet** if all weights = 1.0 (needs 10+ closed signals, `OGD_MIN_SAMPLES=10`)
- **OGD active** if any weight ≠ 1.0 — show most rewarded and most penalized tokens
- **DEGENERATE** if any weight near 0 or > 5 — flag immediately

## Step 7 — Operational Health

Check if there are any signs the bot was recently running:
- Read the most recent entries in the signals table (any direction, any status)
- If no signal activity in > 48 hours, flag **BOT MAY NEED RESTART**

## Step 8 — Summary Dashboard

```
=== TradeAI Paper Trading Monitor ===
Date: [today]

PROGRESS:     [████░░░░░░] X/30 closed (Y%)
SIGNAL RATE:  X/month
ETA TO LIVE:  ~Z months

OPEN NOW:     X signals
LAST SIGNAL:  [timestamp] — [TOKEN] [DIR]

PAPER WR:     X% (baseline: 85.3%) — [TRACKING / DIVERGED]
OGD STATUS:   [ACTIVE / NOT YET / DEGENERATE]

BOT STATUS:   [ACTIVE / STALE / UNKNOWN]
ALERTS:       [none / list any flags]
=====================================
```

If bot appears inactive: suggest running `python crypto_alert.py` with VPN active.

---

## Trend Comparison

Add this block after the dashboard, using previous report data:

| Metric | Previous Run | Current Run | Change |
|--------|-------------|-------------|--------|
| Closed signals | ? | ? | +X since last |
| Signal rate/month | ? | ? | ↑/↓/─ |
| Paper WR% | ? | ? | ↑/↓/─ |
| Bot status | ? | ? | ↑/↓/─ |
| OGD active? | ? | ? | ↑/↓/─ |
| ETA to LIVE | ? | ? | ↑/↓/─ |

New signals since last report = clearest indicator that the bot is running properly.

---

## Save This Run

**1. Save dated report** to:
`C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-paper-monitor\[YYYY-MM-DD].md`

Include: full dashboard output, all DB query results, token breakdown, trend comparison, ETA calculation.

**2. Append to history log:**
`C:\Users\User\Desktop\TradeAI\.claude\reports\HISTORY.md`

Format (one line):
```
[YYYY-MM-DD] | tradeai-paper-monitor | closed=[X/30] rate=[X/mo] WR=[X%] | bot=[ACTIVE/STALE] | ETA=[~X months]
```
