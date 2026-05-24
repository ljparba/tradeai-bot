---
name: tradeai-signal-report
description: Generate a full signal performance report from TradeAI.db covering win rates, token breakdown, OGD adaptive weight state, and paper trading progress toward LIVE readiness. Use whenever the user asks about signal performance, how the bot is doing, paper trade results, win rate, token stats, OGD weights, or adaptive learning progress. Always trigger on phrases like "signal report", "performance report", "how is the bot doing", "check signals", "win rate", "paper trading stats", "how many wins", "OGD weights", "token performance", or "are we on track for live".
---

# TradeAI Signal Performance Report

You are the senior performance analyst for the TradeAI ICT crypto signal bot. Pull all available data from the database, compute statistics, and give a clear assessment of whether live paper performance is tracking the backtested expectations.

**Project:** `C:\Users\User\Desktop\TradeAI\`
**Database:** `TradeAI.db` (SQLite)
**Run-60 Backtest Baseline:** WR ≈ 85.3% | n ≈ 34/year (2.8/month) | z ≈ +4.53 | Net E ≈ +1.648%/trade | Max DD ≈ 2.62%
**Tokens:** BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL (9 tokens — SOL permanently removed)

---

## Review Previous Run

Before querying the DB, check for previous reports:
```
C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-signal-report\
```
Read the most recent file. Extract for comparison:
- Previous closed signal count and WR%
- Previous signal rate (signals/month)
- Previous OGD weight state (active or not, which tokens rewarded/penalized)
- Any underperforming tokens flagged last time

If no previous report — note "First run" and continue.

---

## Step 1 — Overall Signal Statistics

Query closed signals (result IS NOT NULL, or status = 'CLOSED'):

```sql
SELECT
  COUNT(*) as total_closed,
  SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
  SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
  SUM(CASE WHEN result='PARTIAL' THEN 1 ELSE 0 END) as partials,
  ROUND(AVG(CASE WHEN result='WIN' THEN 1.0 WHEN result='PARTIAL' THEN 0.5 ELSE 0.0 END) * 100, 1) as wr_pct,
  MIN(created_at) as first_signal,
  MAX(created_at) as last_signal
FROM signals WHERE status='CLOSED' OR result IS NOT NULL;
```

Also query total open signals separately:
```sql
SELECT COUNT(*) as open_signals FROM signals WHERE status='OPEN' OR status='ACTIVE';
```

Note: PARTIAL counts as 0.5 wins — this matches the canonical WR formula used in the backtest.

## Step 2 — Performance by Token

```sql
SELECT token,
  COUNT(*) as n,
  ROUND(AVG(CASE WHEN result='WIN' THEN 1.0 WHEN result='PARTIAL' THEN 0.5 ELSE 0.0 END) * 100, 1) as wr_pct,
  SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
  SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses
FROM signals WHERE status='CLOSED' OR result IS NOT NULL
GROUP BY token ORDER BY wr_pct DESC;
```

Flag: any token with WR < 50% → potential underperformer (SOL was removed for 42.9% WR).
Flag: any expected token with 0 signals → may be incorrectly filtered.

## Step 3 — Performance by Direction

```sql
SELECT direction, COUNT(*) as n,
  ROUND(AVG(CASE WHEN result='WIN' THEN 1.0 WHEN result='PARTIAL' THEN 0.5 ELSE 0.0 END) * 100, 1) as wr_pct
FROM signals WHERE status='CLOSED' OR result IS NOT NULL
GROUP BY direction;
```

Backtest baseline: BUY 72.7% WR | SELL 80.0% WR (Run-48). Divergence > 20pp from baseline is notable.

## Step 4 — Performance by Session

```sql
SELECT session, COUNT(*) as n,
  ROUND(AVG(CASE WHEN result='WIN' THEN 1.0 WHEN result='PARTIAL' THEN 0.5 ELSE 0.0 END) * 100, 1) as wr_pct
FROM signals WHERE (status='CLOSED' OR result IS NOT NULL) AND session IS NOT NULL
GROUP BY session ORDER BY wr_pct DESC;
```

If the `session` column does not exist, skip this step and note it.

## Step 5 — OGD Adaptive Weight State

```sql
SELECT token, weight, updated_at FROM token_weights ORDER BY weight DESC;
```

Also check backtest isolation:
```sql
SELECT token, weight, updated_at FROM backtest_token_weights ORDER BY weight DESC;
```

Interpret:
- **Weight > 1.0** → OGD is rewarding this token (performing above expectations)
- **Weight < 1.0** → OGD is penalizing this token (underperforming)
- **Weight = 1.0 for all** → OGD has not yet activated (needs 10 closed signals, `OGD_MIN_SAMPLES=10`)
- **Weight near 0 or > 5** → DEGENERATE — prior bug that was fixed; flag if seen again

## Step 6 — Paper Trade Progress

Calculate from signal timestamps:
- Days elapsed since first closed signal
- Signal rate: closed signals per month (annualized)
- Progress: **X / 30** closed signals needed for LIVE readiness
- ETA: at current rate, how many months until N=30?

If signal rate is 0 or last signal was > 7 days ago: flag as **BOT MAY BE INACTIVE**.

## Step 7 — Live vs Backtest Comparison

| Metric | Run-60 Baseline | Live Paper | Delta | Status |
|--------|----------------|------------|-------|--------|
| WR% | 85.3% | ?% | ? | OK / DIVERGED |
| Signals/month | 2.8 | ? | ? | OK / LOW |
| BUY WR | ~72.7% | ?% | ? | OK / DIVERGED |
| SELL WR | ~80.0% | ?% | ? | OK / DIVERGED |

**CRITICAL DIVERGENCE** = live WR differs from baseline by more than 15 percentage points.
If divergence detected, investigate: is it statistical noise (low N) or a systematic issue?

## Step 8 — Summary

If total closed signals < 5: state "Insufficient data for statistical conclusions — X more needed before patterns are meaningful."

If N ≥ 5: give a confidence-adjusted performance assessment and list the top 3 recommended actions.

Always end with the paper trade progress bar:
```
Paper Trade Progress: [████░░░░░░] X/30 (Y%) — ETA: ~Z months to LIVE readiness
```

---

## Trend Comparison

Add this block after the progress bar, comparing to previous report:

| Metric | Previous Run | Current Run | Trend |
|--------|-------------|-------------|-------|
| Closed signals | ? | ? | ↑/↓/─ |
| Overall WR% | ? | ? | ↑/↓/─ |
| Signal rate/month | ? | ? | ↑/↓/─ |
| OGD active? | ? | ? | ↑/↓/─ |
| Best token | ? | ? | ─ |
| Worst token | ? | ? | ─ |

If previous run had an underperforming token flagged — check if it's still underperforming.

---

## Save This Run

**1. Save dated report** to:
`C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-signal-report\[YYYY-MM-DD].md`

Include: all DB query results, token breakdown table, OGD state, trend comparison, progress bar.

**2. Append to history log:**
`C:\Users\User\Desktop\TradeAI\.claude\reports\HISTORY.md`

Format (one line):
```
[YYYY-MM-DD] | tradeai-signal-report | closed=[X/30] WR=[X%] rate=[X/mo] OGD=[active/inactive] | [main finding]
```
