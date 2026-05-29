# Live ↔ Backtest Consistency — Post-CRT-Pro v1.1 Audit
**Date:** 2026-05-27 (post all-day CRT cycle: Pro v1.1 + Wyckoff + Telegram fix + LIVE_LIQUID_HOURS fix)
**Branch:** experiment/crt-h4-signal-source @ a3f2d71 (head)
**Reviewer:** live-backtest-consistency-checker
**Mode:** READ-ONLY
**Prior audit baseline:** 2026-05-27_crt_v1_session2_reaudit.md (10.0/10 perfect)

---

## EXECUTIVE SUMMARY

**Verdict: DRIFT-RISK — one CRITICAL latent bomb + one MEDIUM gate-asymmetry undetected by today's prior audits and the existing test suite.**

While today's CRT-Pro v1.1 cycle correctly defused TWO known bombs (LIVE_LIQUID_HOURS ImportError + Telegram KeyError on net_tp1_pct), a THIRD silent bomb survived all audits unmolested:

- **CRITICAL-CRT-T1 (NEW, undetected before today)**: The live CRT scanner is fundamentally inert in production. `STATE[token]["candles"][tf]` is populated by `fetch_binance_candles()` which uses the key `"timestamps"`, but `crt_engine.detect_h4_crt()` requires the key `"times"` and silently returns `None` on the `required_keys.issubset()` check (crt_engine.py:357-359). The bot in production will never emit an H4_CRT signal. The TODO comment "Inject 'times' if missing" at `crypto_alert.py:3780` was never implemented.

Score: **8.5 / 10** (down from cycle-7's 10.0/10 due to one CRITICAL undetected silent bomb).

---

## FINDINGS

### CRITICAL-CRT-T1 — Live CRT scanner is silently inert (NEW BOMB, fires immediately on first cycle)

**Severity:** CRITICAL DIVERGENCE (live emits 0 signals; backtest emits hundreds)
**Files:**
- `/home/tradeai/TradeAI/crypto_alert.py:1761-1767` — `fetch_binance_candles()` returns dict with key `"timestamps"` (not `"times"`)
- `/home/tradeai/TradeAI/crypto_alert.py:1825` — `update_token_state` writes that dict straight to `state["candles"][tf]` without normalization
- `/home/tradeai/TradeAI/crypto_alert.py:3775-3789` — live caller passes `STATE[token]["candles"]["4h"]` etc. directly to `scan_h4_crt_for_token` without injecting `"times"` key
- `/home/tradeai/TradeAI/crypto_alert.py:3780` — TODO comment "Inject 'times' if missing (some fetch paths use 'time')" never converted to code
- `/home/tradeai/TradeAI/crt_engine.py:357-359` — `detect_h4_crt` enforces `required_keys = {"opens","highs","lows","closes","times"}` and silently returns `None` if any key missing
- `/home/tradeai/TradeAI/backtest.py:367,550,1369,1391` — backtest populates `"times"` correctly throughout

**Empirical proof** (run from this audit shell):
```
$ python3 -c "from crypto_alert import scan_h4_crt_for_token; ..."
Production-shape (timestamps key) → reason: no_setup
   result: None
```

The live scanner returns `(None, None, "no_setup")` on every cycle of every token because the `required_keys` check fails before any detection logic runs. The operator believes CRT is in active paper soak (per `CRT_STRATEGY_CONTEXT.md` §1: "PAPER mode, CRT-only, ENABLE_5M_SWEEP=0, ENABLE_H4_CRT=1") but the live bot is producing zero signals from either scanner. Backtest reports show CRT signals because `backtest.py` builds the candle dict from scratch with `"times"` (`backtest.py:367`).

**Why this matters for live↔BT parity:** The two paths CANNOT diverge more than this. Backtest shows 416 CRT signals over 365 days (per CRT_STRATEGY_CONTEXT.md §5); live in the same time window will show 0. All CRT-paper-soak metrics (DSR, CPCV, WR per scanner attribution) will diverge by 100%.

**Why no audit caught this:**
- The cumulative re-audit (2026-05-27_crt_v1_cumulative_reaudit.md §3) declared the helper-import path verified at backtest.py:117-127 with "Zero drift risk" — that's true for the helper imports but did NOT inspect the candle-dict shape passed into `detect_h4_crt`.
- The unit test fixture `_flat_candles()` at `tests/test_crt_live_integration.py:50` fabricates dicts with `"times"` key, bypassing the production cache shape.
- No existing test invokes `scan_h4_crt_for_token` with a `fetch_binance_candles()` output.

**Fix:** Inject `"times"` from `"timestamps"` either at the fetch site (`crypto_alert.py:1761`) by adding `"times": ts_list` to the return dict, OR at the call site (`crypto_alert.py:3785`) by passing `{**_c4h, "times": _c4h["timestamps"]}` etc. The fetch-site fix is preferred (single point of normalization).

---

### MEDIUM-CRT-T2 — `trend_1h` for CRT live always NEUTRAL (CRT_REQUIRE_1H_TREND silently inert in LIVE)

**Severity:** MEDIUM (only fires when operator sets `CRT_REQUIRE_1H_TREND=1`; default 0 is safe)
**Files:**
- `/home/tradeai/TradeAI/crypto_alert.py:3788` — caller passes `trend_1h=STATE[token].get("trend_1h", "NEUTRAL")`
- `/home/tradeai/TradeAI/crypto_alert.py:165-190` — `new_state()` does NOT define a `"trend_1h"` key
- No code path ever sets `STATE[token]["trend_1h"]` (only `BTC_STATE["trend_1h"]` at line 1868 — different dict)
- Result: `STATE[token].get("trend_1h", "NEUTRAL")` always returns `"NEUTRAL"`

**Backtest equivalent** at `backtest.py:1449-1454`: when `CRT_REQUIRE_1H_TREND=1`, computes real `_trend_1h = _lookup_trend(_ind1h, c5m["times"][entry_bar])` from precomputed 1H trends. Gate fires correctly.

**Live equivalent** at `crypto_alert.py:852-857`: when `CRT_REQUIRE_1H_TREND=1`, `trend_1h` arg is always "NEUTRAL" → both `_bull_ok` and `_bear_ok` evaluate True → gate is a no-op.

**Impact:** Silent parity-killer if operator flips `CRT_REQUIRE_1H_TREND=1` — backtest will gate signals by 1H trend, live will not. Currently the default `0` keeps both inert in lockstep, so this is latent rather than active.

**Fix:** Either write `STATE[token]["trend_1h"] = local_trend_1h` after `generate_signal()` computes it (line ~2507), OR compute `trend_1h` directly inside `scan_h4_crt_for_token` from `STATE[token]["candles"]["1h"]` using the same `get_trend()` call as the 5M_SWEEP path.

---

### Verified parity items (still OK)

Today's CRT cycle was audited against the 9 specific verification points the parent asked about. Results:

| # | Check | Status |
|---|---|---|
| 1 | Live `scan_h4_crt_for_token` vs backtest `run_backtest_token_h4_crt` byte-identical detection | **FAIL** — CRITICAL-CRT-T1 silently kills live detection at required_keys gate |
| 2 | LIVE_LIQUID_HOURS ImportError fix at line 814 → `LIVE_CONFIG.liquid_hours` | **OK** — `_liquid_hours = LIVE_CONFIG.liquid_hours` confirmed at crypto_alert.py:814 |
| 3 | MEDIUM-1: 4H bias `_closes_full[-_N:]` matching backtest's `_lookup_4h_bias` (210-bar cap) | **OK with caveat** — slice arithmetic matches; but live does NOT strip the forming H4 bar (5M_SWEEP path strips via `[:-1]` at line 2498, CRT path does not). Sub-percent EMA200 effect on first/last bar. Documented as KNOWN STRUCTURAL drift (pre-existing for 5M_SWEEP too per prior audit). |
| 4 | `adjust_crt_tp1` produces identical output in both paths | **OK** — shared module helper, same args, same mode=None semantics → defaults to `CRT_TP1_MODE` env constant in both paths |
| 5 | `compute_crt_feature_scores` produces same OGD score dict in both paths | **OK with caveat** — function exists, signature stable, BUT backtest does not call it. This is INTENTIONAL (H6 isolation: backtest uses adaptive bootstrap path at `adaptive_engine.py:1011`, not feature_scores_json). Live writes `feature_scores_json` to DB row; backtest writes nothing for that field on CRT signals. Documented intentional asymmetry. |
| 6 | ENABLE_5M_SWEEP guards enclose 5M scanner in BOTH live + backtest | **OK** — `if ENABLE_5M_SWEEP:` at `crypto_alert.py:3751` and `backtest.py:3686`. Symmetric. |
| 7 | CRT plan dict (crypto_alert.py:938-959) has `net_tp1_pct`, `net_rr1`, `breakeven_wr` (CRITICAL-B0 fix) | **OK** — confirmed at lines 956-958. Telegram renderer at line 3233-3235 reads same keys. |
| 8 | `CRT_TP1_MODE` env knob flows identically through both paths via `adjust_crt_tp1` | **OK** — single source of truth in `crt_engine.py:134`. Both `crypto_alert.py:114` and `backtest.py:138` import it. `adjust_crt_tp1` uses module-level constant when `mode=None`. |
| 9 | New `ict_trend_1h` + `ict_bias_4h` on CRT result dict (HIGH B-1 fix) | **OK** — confirmed at `crypto_alert.py:978-979`. Renderer keys at line 3110-3111 match. |

### KNOWN STRUCTURAL items (unchanged, still acknowledged)

- **DR-1**: `LIVE_CONFIG.dealing_range_gate=False` / `BACKTEST_CONFIG.dealing_range_gate=False` — both OFF since Phase B revert 2026-05-26. Symmetric. Not relevant to CRT path (CRT doesn't compute dealing range).
- **C4 (regime drift)**: 5M_SWEEP-only; CRT operates above regime classifier.
- **EMA-history-depth divergence**: Pre-existing 210-bar cap in backtest vs ~400-bar live cache — affects BOTH paths equally. Below CRITICAL-T1 it's moot anyway (live path emits no CRT signals).
- **M24 (liquid_hours)**: VERIFIED — `LIVE_CONFIG_KWARGS["liquid_hours"]` and `BACKTEST_CONFIG_KWARGS["liquid_hours"]` BOTH resolve to `_liquid_hours_from_env()` at `config.py:364,384`. Single source of truth, byte-identical. No M24 regression.

---

## DELTA vs cycle-7's 10.0/10 audit

| Dimension | Cycle-7 score | Post-CRT-Pro score | Delta |
|---|---|---|---|
| Helper / function parity | 10 | 10 | 0 |
| Constant / env knob parity | 10 | 10 | 0 |
| Cache / dict-shape parity | 10 | **3** | **-7** (NEW CRITICAL-CRT-T1) |
| Gate logic parity | 10 | 9 | -1 (MEDIUM-CRT-T2 latent) |
| Schema / source-tag parity | 10 | 10 | 0 |
| Configuration SSoT (M24) | 10 | 10 | 0 |
| Telegram-renderer / result-dict | 10 | 10 | 0 (today's B-0/B-1 fixes verified) |
| Test coverage of integration shape | 10 | 7 | -3 (fixtures don't catch prod cache shape mismatch) |
| **Composite** | **10.0** | **8.5** | **−1.5** |

---

## GO / NO-GO DECISIONS

- **Continue CRT-only PAPER mode AS-IS:** **NO-GO**. The live bot is currently producing zero CRT signals. The entire current paper-soak data set is non-existent.
- **Flip to LIVE mode:** **NO-GO** (independent of this audit — Session 3 still pending paper-soak validation per CLAUDE.md §5).
- **Fix CRITICAL-CRT-T1 and resume PAPER:** GO once the 1-line fix is shipped. Recommend the fetch-site fix:
  ```python
  # crypto_alert.py:1761 — fetch_binance_candles return dict
  return {"opens": ..., "highs": ..., "lows": ..., "closes": ..., "volumes": ...,
          "timestamps": [int(c[0]) for c in validated],
          "times":      [int(c[0]) for c in validated],   # NEW — for crt_engine parity
          "max_gap_bars": max_gap_bars}
  ```

---

## Cross-domain observations

**Observation:** The CRITICAL-CRT-T1 bomb survived FIVE prior audits (Session 2 audit, Option B/E re-audit, Option H re-audit, Option S re-audit, today's pre-Pro-v1.1 audit) because every reviewer examined the helper-import contract and the function signatures in isolation, not the actual data-shape contract at the call site. The unit-test fixtures fabricate the "correct" dict shape so the test suite cannot detect the production-shape mismatch.

**Relevant Agent:** `backtest-bias-detector` and `professional-code-quality-reviewer`
**Reason:** This is a classic M24-isomorphic silent parity failure — two code paths agree on every named function but disagree on the data structure passed BETWEEN those functions. The systemic prevention is a contract test: `tests/test_crt_live_integration.py` should include one test that calls `scan_h4_crt_for_token` with the EXACT output of `fetch_binance_candles()` (mocked or replayed from a canned response) rather than `_flat_candles()`. This contract test would have caught the bomb at the moment Session 3 wired the integration.

**Observation:** The `trend_1h` MEDIUM finding is also M24-class — different lookup conventions agreed-on at the named-arg level (`trend_1h="NEUTRAL"` is a valid default in both paths) but disagreeing at the SOURCE-OF-VALUE level (backtest looks up real value, live looks up a state slot that's never populated).

**Relevant Agent:** `config-consistency-validator`
**Reason:** SSoT-discipline scope. The fact that `STATE[token]` defines `last_signal_times` (line 174) but not `trend_1h` is an asymmetry exposed only by today's CRT integration. The fix is small but the systemic risk is large — `new_state()` should be the canonical schema, and ANY code path that does `STATE[token].get("X", default)` should be auditable against that canonical schema. Today an audit script that diffs `STATE[token]` accessor patterns against `new_state()` defaults would catch this class of bug.

---

## Proactive improvement suggestions

**Suggestion:** Add a `tests/test_crt_prod_shape.py` that mocks `requests.get` to return a real Binance kline response, runs `fetch_binance_candles`, then passes the result through `scan_h4_crt_for_token`. Assert that the result is one of `("ok", "no_setup", "outside_killzone", "bias_gate_blocked", "blacklisted", "default_off")` — NOT a silent None from a key-missing path.
**Why:** Catches CRITICAL-CRT-T1 class bugs that the existing fixture-based tests cannot. Pinning the production data shape into a test forces future refactors to maintain the contract.
**Impact:** HIGH
**Effort:** Medium (~1 hour — write the mock + canned response + 4 assert variants)

**Suggestion:** Add a CI lint: grep `STATE\[[^]]+\]\.get\(` in `crypto_alert.py` and assert every default key is present in `new_state()`'s returned dict.
**Why:** Catches MEDIUM-CRT-T2 class bugs (state-slot accessors with no setter). Today this would have flagged `STATE[token].get("trend_1h", "NEUTRAL")` since `trend_1h` is not in `new_state()`. The pattern is general — applies to any future state field added.
**Impact:** MEDIUM
**Effort:** Simple (~15 min — one grep + dict-key diff in a pre-commit hook)

**Suggestion:** Move the "Inject 'times' if missing" TODO at `crypto_alert.py:3780` into the `fetch_binance_candles` return dict itself, alongside the existing `"timestamps"` key. Add a code comment explicitly stating: "`times` is an alias for `timestamps` — both keys MUST be present so crt_engine's required_keys check passes. DO NOT remove without auditing every detection-engine consumer." This eliminates the asymmetry permanently rather than papering over it at every call site.
**Why:** Prevents the same bomb from recurring in any future scanner (e.g. v3 IPDA, daily-bias detector) that follows the same dict-shape convention.
**Impact:** HIGH
**Effort:** Simple (~5 min — one line + one comment)

---

## Files audited (absolute paths)

- /home/tradeai/TradeAI/crypto_alert.py (lines 90-115, 160-200, 759-1020, 1711-1845, 2480-2520, 2880-3000, 3110-3235, 3525-3825)
- /home/tradeai/TradeAI/backtest.py (lines 95-145, 365-580, 1290-1640, 3490-3730)
- /home/tradeai/TradeAI/crt_engine.py (lines 130-215, 290-400, 545-800, 825-940)
- /home/tradeai/TradeAI/config.py (lines 300-390)
- /home/tradeai/TradeAI/tests/test_crt_live_integration.py (full file)
- /home/tradeai/TradeAI/.claude/CRT_STRATEGY_CONTEXT.md (full file)
- /home/tradeai/TradeAI/.claude/reports/live-backtest-consistency-checker/2026-05-27_*.md (4 prior audits)
- /home/tradeai/TradeAI/docs/comprehensive/CROSS_REF.md (M24, C3, C4 status check)
