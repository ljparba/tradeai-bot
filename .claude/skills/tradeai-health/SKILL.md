---
name: tradeai-health
description: Run a full TradeAI system health check covering execution mode, all key ICT parameters, config drift between live and backtest configs, database signal state, OGD weight sanity, and paper trading progress. Use this whenever the user asks about system status, bot health, current config, whether parameters are correct, or if the bot is running properly. Always trigger on phrases like "health check", "check the bot", "check the system", "is everything ok", "what's the current config", "check parameters", or "system status". Also trigger proactively after any code change to verify nothing regressed.
---

# TradeAI Health Check

You are the senior technical lead for the TradeAI ICT crypto signal bot. Run a complete health check and give a definitive status verdict. Be specific — cite file:line for any issue found.

**Project:** `C:\Users\User\Desktop\TradeAI\`
**Database:** `TradeAI.db` (SQLite, same directory)
**Current version:** v13 ICT MODE — Phase 5A complete — Run-60 quality config

---

## Review Previous Run

Before doing anything else, check for previous reports:
```
C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-health\
```
List all files. Read the most recent one (highest date). Extract for comparison:
- Previous overall status (GREEN / YELLOW / RED)
- Previous closed signal count (X/30)
- Previous OGD weight status
- Any issues that were flagged last time and whether they were fixed

If no previous report exists — note "First run, no baseline" and continue.

---

## Step 1 — Execution Mode

Read `crypto_alert.py`. Report:
- `EXECUTION_MODE` (must be `"PAPER"` — never switch to `"LIVE"` without full pre-live clearance)
- `SIGNAL_COOLDOWN` (must be `40` — matches COOLDOWN_BARS=8 × 5min)
- Which config block is active (LIVE_CONFIG or BACKTEST_CONFIG equivalent)

## Step 2 — Key Parameter Snapshot

Read `backtest.py` and `ict_engine.py`. Report each value and whether it matches the expected Run-60 standard:

| Parameter | Expected | Actual | File:Line | Status |
|-----------|----------|--------|-----------|--------|
| COOLDOWN_BARS | 8 | ? | ? | OK/MISMATCH |
| ENTRY_WINDOW | 72 | ? | ? | OK/MISMATCH |
| ICT_SWING_N | 2 | ? | ? | OK/MISMATCH |
| FVG quality | HIGH | ? | ? | OK/MISMATCH |
| liquid_hours | range(24) all 24H | ? | ? | OK/MISMATCH |
| bias_4h_gate | "none" | ? | ? | OK/MISMATCH |
| blocked_weekdays | [1, 2, 5] Tue/Wed/Sat | ? | ? | OK/MISMATCH |
| BINANCE_TOKENS count | 9 (SOL removed) | ? | ? | OK/MISMATCH |

The `liquid_hours` check is critical — when this was incorrectly set to `None` (M24 bug), it caused **0 signals** across all tokens.

## Step 2b — Prior Art Check

Before flagging any parameter mismatch or issue, check `docs/comprehensive/CROSS_REF.md`.
Classify each finding:
- **REGRESSION** (was fixed, now broken) — flag at CRITICAL regardless
- **NEW FINDING** (not in cross-ref) — report with full context
- **KNOWN STRUCTURAL / SKIPPED** — note as acknowledged, do not flag as new issue
- **VERIFIED FIXED** — confirm it's still in place, note as confirmed

This prevents re-reporting resolved issues as new problems.

---

## Step 3 — Config Drift Detection

Compare these values between `crypto_alert.py` LIVE_CONFIG and `backtest.py` BACKTEST_CONFIG side by side.
Any mismatch means live signals use different logic than the backtested logic — this directly invalidates the WR predictions.

Parameters to compare:
- `liquid_hours`
- `bias_4h_gate`
- `blocked_regimes` (full list)
- `blocked_weekdays`
- `fvg_quality`

Flag every mismatch as **CRITICAL**.

## Step 4 — Database State

Connect to `TradeAI.db` and run:

```sql
SELECT COUNT(*) as total FROM signals;
SELECT status, COUNT(*) as n FROM signals GROUP BY status;
SELECT MAX(created_at) as last_signal FROM signals;
SELECT result, COUNT(*) as n FROM signals WHERE status='CLOSED' GROUP BY result;
```

Report: total signals, open count, closed count, last signal timestamp, win/loss/partial breakdown of closed signals.

## Step 5 — OGD Weight Sanity (via monitoring.py — Sprint 3)

Run the dedicated weight monitor:
```bash
python monitoring.py --exit-on-crit
```
Parse the output and report:
- Global alert level: **OK / WARN / CRIT**
- Per-token degenerate count, low-entropy count, pinned count, stale count
- Cross-token homogeneity check (`avg_pairwise_l1`)

**Exit code 2 (CRIT) → flag as RED.** Specifically check for:
- DEGENERATE (max weight > 0.45)
- FLOOR_SATURATION (≥4/6 features at WEIGHT_MIN = Run-46 fingerprint)
- CATASTROPHIC_ENTROPY_DROP

WARN-level alerts (pinning, low entropy on a single token) are acceptable but must be documented. The known BNB `dr_location` pinning observed 2026-05-22 is a WARN, not CRIT.

For the raw weight numbers (background reference), also query:
```sql
SELECT token, feature, weight, n_updates, updated_at FROM token_weights ORDER BY token, feature;
```
OGD activates after 10 closed signals (`OGD_MIN_SAMPLES=10`).

## Step 5b — Honest Metrics State

Read the most recent `backtest_reports/RunNN_*.txt` (latest run). Extract the HONEST METRICS section:
- CPCV mean WR, CPCV WR std/q05
- Overall Sharpe, OOS Sharpe (CPCV mean)
- PSR (in-sample) vs PSR (OOS CPCV)
- DSR (multi-test) and the verdict (PASS / MARGINAL / FAIL)

A `FAIL` verdict on the latest run is a **YELLOW** finding (not RED — only RED if it represents a regression from previous PASS).

## Step 6 — Final Status Table

Output this table as the closing verdict:

| Check | Status | Detail |
|-------|--------|--------|
| EXECUTION_MODE | OK / WARNING | value |
| SIGNAL_COOLDOWN | OK / MISMATCH | value |
| liquid_hours | OK / CRITICAL | value |
| ICT_SWING_N | OK / MISMATCH | value |
| ENTRY_WINDOW | OK / MISMATCH | value |
| Config Sync (live vs backtest) | OK / DRIFT DETECTED | pass/fail per param |
| Paper Signals Closed | X / 30 | count toward LIVE |
| OGD Weights (monitoring.py) | OK / WARN / CRIT | global alert level + token count |
| Honest Metrics (latest run) | PASS / MARGINAL / FAIL | CPCV WR + DSR |
| OHLCV cache health | OK / STALE / MISSING | youngest cache file age vs 24h TTL |
| **Overall** | **GREEN / YELLOW / RED** | one-line summary |

**GREEN** = all checks pass, system healthy.
**YELLOW** = minor issues present, safe to continue paper trading but fix soon.
**RED** = critical issue found — do not switch to LIVE until resolved. Follow `docs/comprehensive/PROTOCOL.md` for formal issue resolution (one issue at a time, smoke test after each fix, full suite before advancing).

---

## Trend Comparison

After the final status table, add a trend block comparing this run to the previous report:

| Metric | Previous | Current | Trend |
|--------|----------|---------|-------|
| Overall Status | ? | ? | ↑ / ↓ / ─ |
| Closed Signals | ? | ? | ↑ / ↓ / ─ |
| Config Sync | ? | ? | ↑ / ↓ / ─ |
| OGD Weights | ? | ? | ↑ / ↓ / ─ |

If this is the first run, skip the trend table.

---

## Save This Run

After all checks are complete:

**1. Save dated report** to:
`C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-health\[YYYY-MM-DD].md`

Include: date, all metric values, issues flagged (with file:line), comparison vs previous run, final verdict.

**2. Append to history log:**
`C:\Users\User\Desktop\TradeAI\.claude\reports\HISTORY.md`

Format (one line):
```
[YYYY-MM-DD] | tradeai-health | [GREEN/YELLOW/RED] | signals=[X/30] | [main finding or "clean"]
```
