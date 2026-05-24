---
name: tradeai-pre-live
description: Run the full TradeAI pre-LIVE deployment checklist and produce a definitive GO / NO-GO verdict for switching from PAPER to LIVE mode. Use whenever the user asks about LIVE readiness, switching to live trading, pre-live status, deployment checklist, or whether the system is ready for real money. Always trigger on phrases like "pre-live check", "ready for live", "can we go live", "LIVE checklist", "deployment check", "switch to live", "go live", "am I ready", or "what's left before live".
---

# TradeAI Pre-LIVE Deployment Checklist

You are the senior deployment gatekeeper for the TradeAI ICT crypto signal bot. Your job is to protect real capital by verifying every requirement before clearing the system for LIVE mode. Be thorough and conservative — a false GO costs real money.

**Project:** `C:\Users\User\Desktop\TradeAI\`
**Database:** `TradeAI.db`
**LIVE switch requires:** changing `EXECUTION_MODE = "PAPER"` to `"LIVE"` AND setting env var `LIVE_MODE_CONFIRMED=YES`

---

## Review Previous Run

Before checking anything, look for previous pre-live reports:
```
C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-pre-live\
```
Read the most recent file. Note:
- Previous overall verdict (GO / NO-GO)
- Which items were FAIL or PENDING last time — check if they've been resolved
- Previous closed signal count (the key blocker)

If FAIL items from last run now PASS — that's progress. Flag it explicitly.

---

## CATEGORY A — Backtest Validation (HONEST METRICS — Sprint 3 edition)

Validated from `data/backtest_results.json` + latest `backtest_reports/RunNN_*.txt`:

- [x] **Walk-forward gap < 10%** — Run-110: verify in latest backtest_reports/RunNN_*.txt
- [x] **n ≥ 30 with z ≥ 1.28** — Run-110: n=46, z=+4.02 ✅
- [x] **Headline WR > 50% with positive Net E** — Run-110: WR=76.1%, Net E positive ✅
- [x] **CPCV mean WR ≥ 58%** — Run-110: CPCV mean=76.23% ✅
- [x] **CPCV WR q05 ≥ 50%** — Run-110: q05=63.2% ✅
- [ ] **DSR ≥ 0.95** — Run-110: DSR=0.898 ❌ **FAIL LIVE-strict — short by 5.2pp**
- [x] **DSR ≥ 0.85 (ACCEPTABLE SUCCESS)** — Run-110: DSR=0.898 ✅ extended PAPER OK
- [x] **OOS Sharpe (CPCV mean) > 0.5** — Run-110: OK ✅

**Critical:** DSR=0.898 meets ACCEPTABLE SUCCESS (≥0.85) but does NOT meet LIVE-strict (≥0.95). The canonical blocker against switching to LIVE is the n=46 < n=80 sample-power requirement. With 110+ backtest runs in history, the best-of-N selection bias means we have 89.8% confidence the strategy survives multiple-testing inflation — short of the 95% required. **Path to LIVE = paper trade to n≥80, NOT more optimization** (per optimization_experiments.md Session 4 final recommendation).

## CATEGORY B — Code & Configuration (Verify by reading files)

Read `crypto_alert.py` and verify each item:

### B1. Signal Cooldown Match
`SIGNAL_COOLDOWN` must equal `COOLDOWN_BARS × 5` minutes.
- COOLDOWN_BARS = 8 (backtest) → SIGNAL_COOLDOWN must = 40 minutes
- **PASS** if SIGNAL_COOLDOWN == 40 | **FAIL** if different

### B2. LIVE Mode Kill Switch
The code must require `LIVE_MODE_CONFIRMED=YES` env var to enter LIVE mode.
Search for `LIVE_MODE_CONFIRMED` in crypto_alert.py — must exist and actively block execution if absent.
- **PASS** if kill switch is present and enforced | **FAIL** if missing

### B3. Duplicate Signal Guard
Verify a guard exists that prevents the same signal from firing twice in LIVE mode.
- **PASS** if guard is active | **FAIL** if missing

### B4. Telegram Token Security
Verify `TELEGRAM_TOKEN` is loaded from environment variable only — never hardcoded.
- **PASS** if env-var only | **FAIL** if hardcoded anywhere

### B5. LIVE_CONFIG Position Limits
In LIVE_CONFIG, verify:
- `MAX_OPEN_POSITIONS = 4` (limits concurrent exposure)
- `MAX_SAME_DIRECTION = 2` (prevents directional overexposure)
- **PASS** if both present in LIVE_CONFIG | **FAIL** if missing or set higher

### B6. Config Sync (Live vs Backtest)
Verify these match between LIVE_CONFIG and BACKTEST_CONFIG:
- `liquid_hours` (must both be `list(range(24))`)
- `bias_4h_gate` (must both be `"none"`)
- `blocked_regimes` (must match)
- `blocked_weekdays` (must match [1, 2, 5])
- **PASS** if all match | **FAIL** if any mismatch (invalidates backtest WR predictions)

## CATEGORY C — Database Requirements (Query TradeAI.db)

### C1. Paper Signals Collected
```sql
SELECT COUNT(*) FROM signals WHERE status='CLOSED' OR result IS NOT NULL;
```
- **PASS** if count ≥ 30 | **PENDING** if < 30 (state how many more needed)
- This is the most likely blocker — collecting 30 signals at ~2.6/month takes ~12 months from first signal

### C2. OGD Weights Non-Degenerate
```sql
SELECT token, weight FROM token_weights;
```
- **PASS** if all weights are between 0.1 and 5.0
- **FAIL** if any weight is 0, null, or > 10 (degenerate — OGD disabled effectively)

## CATEGORY D — Operational Requirements (Cannot auto-verify — user confirms)

These require user confirmation:

- [ ] **D1. YOUR_CAPITAL** env var is set to actual trading capital (in USDT)
- [ ] **D2. Binance API key** is configured (env var, never hardcoded) with trading permissions enabled
- [ ] **D3. VPN is available** — Binance is blocked in the Philippines; VPN must be active before every session
- [ ] **D4. Telegram bot is working** — test a message to confirm alerts are received
- [ ] **D5. Bot runs stably** — paper trading has run for at least 48 hours without crashes

## CATEGORY E — Sprint 3 Honest-Metrics Gates (NEW)

### E1. OGD Weight Health Check
```bash
python monitoring.py --exit-on-crit
```
- **PASS** if exit code 0 (no degenerate weights, no floor saturation, entropy healthy)
- **FAIL** if exit code 2 (CRIT — Run-46 fingerprint detected somewhere in token state)
- **WARN** if any WARN-level alerts (e.g., BNB dr_location pinning observed 2026-05-22)

### E2. CPCV + DSR Verdict (validation.py)
Read the HONEST METRICS section in the latest `backtest_reports/RunNN_*.txt`:
- **PASS** if verdict is "PASS" (CPCV mean WR ≥ 58% AND DSR ≥ 0.95)
- **MARGINAL** if verdict is "MARGINAL" (CPCV ≥ 55% with DSR not failing)
- **FAIL** if verdict is "FAIL" — **DO NOT GO LIVE**

### E3. Macro Event Filter Status
Verify in `config.py`:
- `MACRO_FILTER_ENABLED` — for LIVE, recommend `True`
- `MACRO_ADVISORY_ONLY` — for LIVE, recommend `False` (active blocking) OR keep `True` (advisory) per user preference
- Note current setting in the verdict — both modes are acceptable but the choice must be intentional

### E4. Cache Hygiene
Verify in `data/ohlcv_cache/`:
- Cache files exist (proves backtests have been running)
- Cache `--clear-cache` was run after any data-pipeline-affecting code change
- TTL is active (no files older than 24h that haven't been refetched)

---

## Final Verdict

After checking all items, output:

| Category | Items | Passed | Failed | Pending |
|----------|-------|--------|--------|---------|
| A — Backtest (Honest Metrics) | 7 | ? | ? | ? |
| B — Code/Config | 6 | ? | ? | ? |
| C — Database | 2 | ? | ? | ? |
| D — Operational | 5 | ? | ? | ? |
| E — Sprint 3 Gates | 4 | ? | ? | ? |
| **Total** | **24** | **?** | **?** | **?** |

**Hard blockers (any one of these → NO-GO regardless of other PASSes):**
- A6: DSR < 0.95
- E1: monitoring.py CRIT
- E2: CPCV verdict = FAIL
- B4: Telegram token hardcoded
- C2: any degenerate OGD weight

### Verdict: GO / NO-GO

**If any CRITICAL item FAILS or any PENDING item is not met → NO-GO**

State exactly what must happen before the next pre-live check, in priority order.

**If all items PASS → GO**
State: "System cleared for LIVE. Set EXECUTION_MODE='LIVE' and confirm LIVE_MODE_CONFIRMED=YES env var is set before starting."

⚠️ Even with GO verdict: switching to LIVE requires explicit user confirmation. Never switch automatically.

---

## Trend Comparison

| Item | Previous | Current | Change |
|------|----------|---------|--------|
| Items passing | ?/16 | ?/16 | ↑/↓/─ |
| Closed signals | ? | ? | ↑/↓/─ |
| Overall verdict | GO/NO-GO | GO/NO-GO | ─ |
| New items fixed | — | list | — |
| Still failing | — | list | — |

---

## Save This Run

**1. Save dated report** to:
`C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-pre-live\[YYYY-MM-DD].md`

Include: full checklist with PASS/FAIL/PENDING per item, comparison to previous run, final GO/NO-GO verdict.

**2. Append to history log:**
`C:\Users\User\Desktop\TradeAI\.claude\reports\HISTORY.md`

Format (one line):
```
[YYYY-MM-DD] | tradeai-pre-live | [GO/NO-GO] | passing=[X/16] | signals=[X/30] | [main blocker]
```
