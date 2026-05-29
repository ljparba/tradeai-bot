# Data Pipeline Validator — Cycle 8 (Post-CRT Pro)
**Date:** 2026-05-27
**Previous score:** 9.7/10 (cycle-7)
**Scope:** Binance API + OHLCV cache + CRT live integration + all cross-ref carry-over items

---

## PRIOR ART CLASSIFICATION

| Cross-ref ID | Status | Verification |
|---|---|---|
| H15 (API retry storm) | VERIFIED FIXED | API_RETRIES=2, API_DELAY=3 confirmed at config.py:223-224 |
| H16 (stale candle monitor) | VERIFIED FIXED | monitor_open_signals staleness gate at crypto_alert.py:3300-3303 intact |
| H17 (BTC 10-min staleness) | VERIFIED FIXED | 600s gate removed; BTC recomputes from STATE every cycle — crypto_alert.py:1852-1855 |
| H18 (BTC feed failure) | VERIFIED FIXED | feed_ok=False blocks all alt signals; Telegram alert w/ 1h dedup at crypto_alert.py:1872-1898 |
| H19 (gap detection action) | VERIFIED FIXED | max_gap_bars >= 3 skips signal at crypto_alert.py:2358-2366 |
| M19 (thin candle warning) | VERIFIED FIXED | [WARN-THIN] check at crypto_alert.py:1736-1740 |
| M21 (forming candle exit) | VERIFIED FIXED | [:-1] applied at crypto_alert.py:3318 and generate_signal 2372-2375 |
| M22 (sub-tolerance gap warning) | VERIFIED FIXED | [WARN-GAP] log at crypto_alert.py:1755-1760 |
| L8 (CoinGecko retry) | VERIFIED FIXED | dom_dir forced NEUTRAL after 3×DOM_FETCH_INTERVAL at crypto_alert.py:1919-1922 |
| L10 (429 handling in backtest) | VERIFIED FIXED | Retry-After header read, sleep on 429 at backtest.py:335-338 |
| H-CY7-2 (HTML-escape monitoring alert) | VERIFIED FIXED | sed escaping at scripts/run_monitoring_with_alert.sh:67-68 (was the specific check requested) |

---

## CRITICAL DATA FAILURES

### CRIT-1 (NEW FINDING) — Live CRT Scanner Silently Emits Zero Signals

**File:** crypto_alert.py:1766, crt_engine.py:357-358, crypto_alert.py:3780-3789
**Severity:** CRITICAL
**Impact:** With the current production config (ENABLE_H4_CRT=1, ENABLE_5M_SWEEP=0), the bot is emitting ZERO signals.

**Root cause:**
- `fetch_binance_candles()` at crypto_alert.py:1766 returns candle dicts with key `"timestamps"` (not `"times"`).
- `crt_engine.detect_h4_crt()` at line 357-358 checks `required_keys = {"opens", "highs", "lows", "closes", "times"}` — if `"times"` is not present in either dict, it returns `None` immediately.
- The live STATE candle dicts stored in `STATE[token]["candles"]["5m"]` and `STATE[token]["candles"]["4h"]` therefore always fail this check.
- `scan_h4_crt_for_token()` at crypto_alert.py:789 calls `detect_h4_crt(c4h, c5m, ...)` which returns `None`, causing every call to return `(None, None, "no_setup")`.
- The comment at crypto_alert.py:3780 says "Inject 'times' if missing (some fetch paths use 'time')" but NO injection code exists — this was planned but never implemented.
- Secondary issue: even if `detect_h4_crt` returned a result, line 804 `ts = datetime.utcfromtimestamp(c5m["times"][entry_bar] / 1000)` would `KeyError` since the live dict uses `"timestamps"`.

**What bad data is fed to signals:** None — the silent None return means CRT detections never happen, not that they happen on bad data. The damage is business-critical: the bot has been running in CRT-only mode (ENABLE_5M_SWEEP=0) since the .env was set on 2026-05-27, and every scan cycle produces zero signals.

**Contrast with backtest:** `backtest.py`'s `fetch_historical()` at line 367 uses `"times"` as the key. Backtest CRT works correctly. This is a live/backtest key-name divergence in the fetch layer.

**Fix required:** Before calling `detect_h4_crt`, alias the key in both c5m and c4h:
```python
if "times" not in _c5m and "timestamps" in _c5m:
    _c5m = {**_c5m, "times": _c5m["timestamps"]}
if "times" not in _c4h and "timestamps" in _c4h:
    _c4h = {**_c4h, "times": _c4h["timestamps"]}
```
Insert at crypto_alert.py:3780 (where the comment already marks the intent). Also fix line 804 in `scan_h4_crt_for_token`.

---

## RELIABILITY RISKS

### REL-1 (NEW FINDING) — CRT Scanner Uses Stale Per-Token trend_1h (Always NEUTRAL)

**File:** crypto_alert.py:3788, crypto_alert.py:165-190
**Severity:** MEDIUM
**Impact:** When `CRT_REQUIRE_1H_TREND=1` is set in future experiments, the trend gate will silently see NEUTRAL for every token because `STATE[token]` never has a `"trend_1h"` key populated.

**Root cause:** `scan_h4_crt_for_token` is called with `trend_1h=STATE[token].get("trend_1h", "NEUTRAL")`. The `new_state()` factory at crypto_alert.py:165-190 does not include `"trend_1h"` as a key. There is no code anywhere in the file that writes `STATE[token]["trend_1h"]`. The per-token 1H trend is computed inside `generate_signal()` as a local variable (`trend_1h = get_trend(closes_1h)`) but is never stored back to STATE.

**Current impact:** Low — with `CRT_REQUIRE_1H_TREND=0` (default), the gate is bypassed and "NEUTRAL" is a valid pass-through. But the feature score vector passed to OGD at crypto_alert.py:928-936 always uses `trend_1h="NEUTRAL"` for the CRT signal's OGD learning — the `trend_strength` feature is perpetually zero-input for all CRT trades. This is noted in crt_engine.py:773-776 as a design caveat, but the STATE write was apparently never wired.

**Risk escalation:** MEDIUM becomes HIGH if `CRT_REQUIRE_1H_TREND=1` is ever enabled without this fix. All CRT signals would then silently pass the trend gate regardless of actual 1H momentum.

---

## RATE LIMIT RISKS

### RL-1 (VERIFIED SAFE) — Request Weight Per Cycle Well Within Limits

**Analysis:**
- Per cycle (10 tokens × 4 timeframes + 10 ticker calls):
  - 4h (limit=400) = weight 2 per call × 10 tokens = 20
  - 1h (limit=600) = weight 5 per call × 10 tokens = 50 (crosses the 500-bar weight tier)
  - 15m (limit=210) = weight 2 per call × 10 tokens = 20
  - 5m (limit=500) = weight 2 per call × 10 tokens = 20
  - ticker/24hr = weight 1 × 10 tokens = 10
- **Total: 120 weight units per cycle**
- At 90s cycle interval: 0.67 cycles/minute × 120 = ~80 weight units/minute
- Binance limit: 1200 weight/minute
- **Headroom: 93% remaining — no rate limit risk**

### RL-2 (NEW FINDING) — 1H Limit=600 Crosses Binance Weight Tier Unexpectedly

**File:** config.py:163
**Severity:** LOW / INFORMATIONAL
**Note:** The 1H timeframe is configured with `limit=600`. Binance's klines endpoint assigns weight 5 (not 2) for `limit > 500`. The code comment says "C-N3: EMA200 needs ~4× period" — this is correct reasoning, but the limit jump from 500 to 600 triples the per-call weight (2 → 5). At current cycle rates this is still safe (80/1200 used), but if cycle interval is ever shortened or tokens expanded, this becomes the first pressure point. Not a current risk; flagged for awareness.

---

## DATA QUALITY GAPS

### DQ-1 (VERIFIED INTACT) — OHLCV Validation at fetch Layer

`fetch_binance_candles()` validates: `o > 0, h > 0, l > 0, cl > 0, h >= l, h >= o, l <= o, cl <= h, cl >= l` (C5 fix). Confirmed at crypto_alert.py:1725.

### DQ-2 (VERIFIED INTACT) — Gap Detection Functional

`_INTERVAL_MS` dict covers all used intervals (1m through 1d) at crypto_alert.py:1707-1708. Gap detection at crypto_alert.py:1746-1760 correctly uses `_INTERVAL_MS.get(interval, 0)` — returns 0 for unknown intervals which skips detection safely.

### DQ-3 (VERIFIED INTACT) — Forming Candle Exclusion

`[:-1]` slicing is applied at: generate_signal() for 15m closes/highs/lows/volumes (lines 2372-2375); 5M closes for ICT analysis (line 2450-2454); 4H and 1H closes for bias calculation (lines 2498-2507); exit intelligence (line 3318).

### DQ-4 (VERIFIED INTACT) — 4H Bar Count for CRT get_ict_4h_bias

- `TIMEFRAMES["4h"]["limit"] = 400` (config.py:162)
- `get_ict_4h_bias` requires `len(closes_4h) >= 200` (ict_engine.py:413)
- Live scan uses `closes_4h = c4h_state.get("closes", [])[:-1]` = 399 closed bars
- CRT's `scan_h4_crt_for_token` slices to last 210 bars when len >= 200 (crypto_alert.py:826-832)
- **Sufficient: 400 >> 200+10 (H4_CRT_C2_LOOKBACK)**
- Wyckoff context detector needs min 80 bars; 399 available — OK

### DQ-5 (VERIFIED INTACT) — CRT Reuses Existing OHLCV Cache, No Extra API Calls

The main loop at crypto_alert.py:3774-3788 reads `STATE[token]["candles"]["5m"]` and `STATE[token]["candles"]["4h"]` — already populated by `update_token_state()` earlier in the same cycle. Zero additional Binance calls per CRT scan cycle. Rate limit impact is neutral.

---

## WEBSOCKET RELIABILITY

**WebSocket: NOT USED.** TradeAI is a pure REST polling architecture (90s cycle interval). No WebSocket reconnection logic is needed or applicable.

---

## STALE DATA PROTECTION

### STALE-1 (VERIFIED INTACT) — Per-Token Staleness Gate

At crypto_alert.py:3736-3743: both `last_fetched_at` and `last_5m_fetched_at` are checked against `STALE_CANDLE_THRESHOLD` (default: 3 × CHECK_INTERVAL = 270s). Stale tokens are skipped for signal generation.

### STALE-2 (VERIFIED INTACT) — TP/SL Monitor Staleness Gate

H16 fix confirmed at crypto_alert.py:3300-3303. `_candles_stale` flag suppresses candle high/low from TP/SL monitor when data is stale; live price used instead.

### STALE-3 (VERIFIED INTACT) — CoinGecko Stale DOM Direction

L8 fix at crypto_alert.py:1919-1922: `dom_dir` forced to NEUTRAL if CoinGecko unreachable for > 3 × DOM_FETCH_INTERVAL. Fail-safe behavior confirmed.

---

## DRIFT-GATE WARNINGS — STATUS ASSESSMENT

**Item 4 from operator brief: "DRIFT-GATE warnings on adx_trend deltas — are they expected or new?"**

**Answer: EXPECTED / BY DESIGN.** The DRIFT-GATE at crypto_alert.py:3481-3506 is a visibility-only monitor (not a block). It warns when any token's live DriftDetector ADX threshold has moved > ±5.0 from the static backtest baseline of 25.0. This runs at bot startup only. Warnings are printed to log and appended to the startup Telegram message if any token has drifted. This is documented as KNOWN STRUCTURAL (C4 in CROSS_REF.md). The warnings are NOT new — they appear whenever the DriftDetector has accumulated enough live candle history to move thresholds. They do not affect signal generation correctness; they are advisory for the operator.

---

## DEPENDENCY RELIABILITY SUMMARY

| Component | Status | Notes |
|---|---|---|
| Binance REST API | ROBUST | OHLCV validation, gap detection, 418/429 handling, preflight check, all intact |
| Binance Rate Limits | ROBUST | 80/1200 weight units/minute at current config (93% headroom) |
| CoinGecko API | ROBUST | Retry + stale NEUTRAL fallback at 3× DOM_FETCH_INTERVAL confirmed |
| WebSocket | NOT USED | Pure REST polling; no WebSocket in use |
| Stale data protection | PRESENT | Per-token + TP/SL monitor gates confirmed |
| CRT live integration | FRAGILE — CRITICAL GAP | `timestamps` vs `times` key mismatch; ENABLE_H4_CRT=1 + ENABLE_5M_SWEEP=0 = zero signals |
| 5M_SWEEP pipeline | ROBUST (when enabled) | All H15-H19, M19-M22 fixes confirmed intact |
| Overall verdict | AT RISK | CRIT-1 renders the live bot operationally silent in current config |

---

## CYCLE-8 SCORE

**Score: 9.0 / 10** (down from cycle-7's 9.7/10)

**Reason for decrease:** CRIT-1 is a new finding that is actively breaking live operation. The `timestamps` vs `times` key mismatch completely disables CRT signal generation in live mode while backtest CRT works correctly. Given that the .env has `ENABLE_H4_CRT=1` and `ENABLE_5M_SWEEP=0`, the bot is currently running in a configuration that produces zero signals — a 100% operational failure for the CRT-only paper trading objective.

All cycle-7 previously verified items remain intact (+0 regressions). REL-1 (stale trend_1h in STATE) is a medium issue for future experiments but low impact today. Rate limit headroom is healthy. All prior cross-ref items confirmed.

**Restoring to 9.7+ requires:** Fixing CRIT-1 (the `timestamps`→`times` alias injection in the live scan path).

---

## PROACTIVE IMPROVEMENT SUGGESTIONS

**Suggestion 1:** Normalize the candle dict key from `"timestamps"` to `"times"` at the source — `fetch_binance_candles()` return dict. Change `"timestamps"` to `"times"` in the return value at crypto_alert.py:1766, then update all callers that read `"timestamps"` (crypto_alert.py:2454 `t5_all = c5m_raw.get("timestamps", [])[:-1]` and crypto_alert.py:2744 `_c15m_ts = STATE[token]["candles"]["15m"].get("timestamps", [])`).
**Why:** Eliminates the class of live/backtest key-name divergence at the architectural level rather than patching each new consumer. Backtest uses `"times"`, live used `"timestamps"` — a hidden inconsistency that will silently break any future addition that reads the cache.
**Impact:** HIGH
**Effort:** Simple (rename + grep callers)

**Suggestion 2:** Store computed per-token `trend_1h` back to `STATE[token]["trend_1h"]` at the end of `generate_signal()` or at the end of `update_token_state()`.
**Why:** Makes the per-token trend cache available to the CRT scanner for OGD feature scoring and future `CRT_REQUIRE_1H_TREND=1` experiments. Currently the CRT OGD gradient is always fed `trend_strength=NEUTRAL`, silently halving the informational value of every CRT trade close for the adaptive engine.
**Impact:** MEDIUM
**Effort:** Simple (one state write per cycle per token)

**Suggestion 3:** Add an `assert "times" in c5m and "times" in c4h` or a defensive key-check at the top of `scan_h4_crt_for_token` that logs a clear error message rather than silently returning "no_setup".
**Why:** The current silent failure (CRIT-1) could go undetected for hours or days in paper mode — the bot logs look normal (no errors) but `[CRT-v1] EMIT` never appears. A one-line assertion would make operational silence immediately visible.
**Impact:** HIGH
**Effort:** Simple

**Suggestion 4:** Add a cycle-level CRT signal counter to the heartbeat payload so the operator can see at a glance in the hourly Telegram message "CRT signals this cycle: 0/0" vs "CRT signals: 0/1 detected, 1/1 passed gates."
**Why:** Per-symbol rejection reasons are logged to stdout but not surfaced in Telegram. Zero-signal periods are invisible to the operator unless they tail the logs.
**Impact:** MEDIUM
**Effort:** Simple

---

## CROSS-DOMAIN OBSERVATIONS

**Observation 1:** CRIT-1 (timestamps vs times key mismatch) means that ALL CRT backtest results in the Optuna explorer and any manual backtest runs are valid, but ALL live paper signal data for `source='H4_CRT'` accumulated since the .env was set to `ENABLE_H4_CRT=1` is zero rows — no CRT signals have been saved to `signals.db`. Any performance analysis of CRT paper trading during this period (WR, OGD learning) has a sample of 0.
**Relevant Agent:** live-backtest-consistency-checker
**Reason:** The backtest CRT path (backtest.py + crt_engine.py using `"times"`) is correct. The live path is broken. This is a confirmed live/backtest parity failure in the data ingestion layer.

**Observation 2:** The adaptive OGD engine's `compute_crt_feature_scores()` always receives `trend_1h="NEUTRAL"` for all CRT signals because `STATE[token]["trend_1h"]` is never populated. Once CRIT-1 is fixed and CRT signals start flowing, the `trend_strength` feature dimension in the OGD gradient will be perpetually zero-input for CRT trades. This is a quiet adaptive-learning quality gap.
**Relevant Agent:** adaptive-learning-code-reviewer
**Reason:** OGD feature vector quality degrades silently when trend_1h is always NEUTRAL for CRT signals. The OGD system cannot learn whether 1H trend direction predicts CRT success.
