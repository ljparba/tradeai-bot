---
name: tradeai-config-validate
description: Validate that all TradeAI configuration parameters are perfectly consistent across crypto_alert.py, backtest.py, and ict_engine.py to prevent parameter drift bugs. Use this after any code change, before any backtest run, or whenever the user wants to confirm configs are in sync. Always trigger on phrases like "config check", "validate config", "check for drift", "are configs in sync", "config validation", "check parameters", "sync check", or "parameter check". Also trigger automatically after any edit to backtest.py or crypto_alert.py to catch drift before it causes 0-signal bugs like M24.
---

# TradeAI Configuration Consistency Validator

You are the senior systems engineer for the TradeAI ICT crypto signal bot. Your job is to prevent parameter drift — specifically the class of bug where a parameter is correctly set in one config but silently wrong in another, causing the live system to behave differently from what was backtested.

**The M24 bug (2026-05-21):** `liquid_hours` was correctly set to `list(range(24))` in BACKTEST_CONFIG but reverted to `None` (10H killzones only) in LIVE_CONFIG. This caused **0 signals** across all 9 tokens for an entire session before the bug was found. This validator exists to catch that class of bug instantly.

**Project:** `C:\Users\User\Desktop\TradeAI\`
**Files to cross-check:** `crypto_alert.py`, `backtest.py`, `ict_engine.py`

---

## Review Previous Run

Before checking anything, look for previous config validation reports:
```
C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-config-validate\
```
Read the most recent file. Note:
- Which parameters were PASS vs FAIL last time
- Any CRITICAL mismatches that were found — check if they've been fixed
- If all were PASS last time and you find a new FAIL today, that means something changed recently

New failures vs last run are especially important — they pinpoint what changed.

---

## Block 1 — Live vs Backtest Config Parity

For each parameter, find the value in `crypto_alert.py` LIVE_CONFIG AND `backtest.py` BACKTEST_CONFIG. Report file:line for each.

| Parameter | LIVE_CONFIG | File:Line | BACKTEST_CONFIG | File:Line | Match? |
|-----------|-------------|-----------|-----------------|-----------|--------|
| liquid_hours | ? | ? | ? | ? | YES/NO |
| bias_4h_gate | ? | ? | ? | ? | YES/NO |
| blocked_regimes | ? | ? | ? | ? | YES/NO |
| blocked_weekdays | ? | ? | ? | ? | YES/NO |
| fvg_quality | ? | ? | ? | ? | YES/NO |
| max_sl_pct | ? | ? | ? | ? | YES/NO |
| min_sl_pct | ? | ? | ? | ? | YES/NO |
| min_rr | ? | ? | ? | ? | YES/NO |
| entry_window | ? | ? | ? | ? | YES/NO |

Any mismatch = **CRITICAL**. A mismatched parameter means the live system runs on different logic than what was backtested, directly invalidating WR% predictions.

## Block 2 — Cooldown Consistency

The backtest uses bars (COOLDOWN_BARS × 5 minutes per bar). The live system uses minutes (SIGNAL_COOLDOWN).
They must be equivalent: `SIGNAL_COOLDOWN == COOLDOWN_BARS × 5`

- `COOLDOWN_BARS` in backtest.py = ? (expected: 8)
- `SIGNAL_COOLDOWN` in crypto_alert.py = ? (expected: 40)
- Equivalence: COOLDOWN_BARS × 5 = ? (expected: 40)
- **PASS** if equal | **FAIL** if not

## Block 3 — Token List Consistency

The live token list and the backtest token list must be identical.
SOL was permanently removed (T-1 decision: 42.9% WR, chronic underperformer).
Expected: BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL (9 tokens)

- LIVE token list (from crypto_alert.py BINANCE_TOKENS): ?
- BACKTEST token list (from backtest.py): ?
- **PASS** if identical | **FAIL** if different

## Block 4 — ICT Engine Parameter Consistency

These ICT parameters in `ict_engine.py` are used by both live and backtest. Verify they match the expected Run-60 values:

| Parameter | Expected | Actual in ict_engine.py | File:Line | Status |
|-----------|----------|------------------------|-----------|--------|
| ICT_SWING_N | 2 | ? | ? | OK/MISMATCH |
| ICT_SWEEP_LOOKBACK | any | ? | ? | (note value) |
| ICT_MSS_HORIZON | any | ? | ? | (note value) |
| ICT_FVG_MIN_GAP | any | ? | ? | (note value) |
| ICT_IFVG_LOOKBACK | any | ? | ? | (note value) |
| DEALING_RANGE_LOOKBACK | any | ? | ? | (note value) |
| ROUND_TRIP_COST_PCT | 0.003 | ? | ? | OK/MISMATCH |
| MIN_TP1_MULT | 1.5 | ? | ? | OK/MISMATCH |
| ICT_MIN_RR_GATE | 1.5 | ? | ? | OK/MISMATCH |

`ICT_SWING_N` was rolled back to 2 from P-1b experiment. If you see ICT_SWING_N=1, that is a regression — flag as CRITICAL.

## Block 5 — Hard-coded Value Scan

Search all `.py` files (excluding `backups/` and `tests/`) for values that should be in config but may be hardcoded:

```
grep for: 0.030, 0.005, 0.003, 1.5, "SOL", "SOLUSDT"
```

- `0.030` appearing outside config = potential hardcoded MAX_SL_PCT
- `0.005` appearing outside config = potential hardcoded MIN_SL_PCT
- `0.003` appearing outside config = potential hardcoded ROUND_TRIP_COST_PCT
- `"SOLUSDT"` anywhere = SOL was supposed to be permanently removed (T-1)

## Final Report

**Total checks:** count all YES/NO and PASS/FAIL results.

**PASS count:** X
**FAIL count:** X (any fail = action required)
**CRITICAL count:** X (any critical = LIVE-blocker)

If any CRITICAL found:
→ State exact fix needed with file:line
→ State: "Do not switch to LIVE mode until this is resolved."
→ Follow `docs/comprehensive/PROTOCOL.md` for the formal fix procedure — one issue at a time, test after each fix.

If all PASS:
→ State: "Configuration fully consistent. Ready for backtest or LIVE operation."

---

## Trend Comparison

| Parameter | Previous | Current | Changed? |
|-----------|----------|---------|----------|
| liquid_hours | ? | ? | Yes/No |
| bias_4h_gate | ? | ? | Yes/No |
| blocked_regimes | ? | ? | Yes/No |
| blocked_weekdays | ? | ? | Yes/No |
| ICT_SWING_N | ? | ? | Yes/No |
| Token count | ? | ? | Yes/No |
| Overall result | PASS/FAIL | PASS/FAIL | ↑/↓/─ |

Newly introduced FAILs (were PASS last time) = highest priority — something changed recently.
Fixed FAILs (were FAIL last time, now PASS) = confirm the fix worked.

---

## Save This Run

**1. Save dated report** to:
`C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-config-validate\[YYYY-MM-DD].md`

Include: full parameter concordance table, all PASS/FAIL results with file:line, trend comparison, final verdict.

**2. Append to history log:**
`C:\Users\User\Desktop\TradeAI\.claude\reports\HISTORY.md`

Format (one line):
```
[YYYY-MM-DD] | tradeai-config-validate | [CONSISTENT/DRIFT] | FAIL=[n] | [params that failed or "all clear"]
```
