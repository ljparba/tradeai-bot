# CRT v1 Session 2 — Live/Backtest Parity Readiness Audit
**Date:** 2026-05-27
**Branch:** experiment/crt-h4-signal-source
**Commit:** 3d47c77
**Scope:** Verify that the Session 2 backtest CRT implementation is structured such that Session 3 can integrate `crt_engine.detect_h4_crt()` into `crypto_alert.py` and produce IDENTICAL signals on identical OHLCV inputs.
**Verdict:** AMBER — parity-by-construction is broadly intact (shared module is clean), but FIVE structural items must be designed-into Session 3 or backtest signals will diverge from live in ways that invalidate the attribution layer.

---

## 1. Executive Summary

The architectural foundation is sound: `crt_engine.py` is a self-contained module with NO call sites in either `backtest.py` or `crypto_alert.py` that re-implement any detection logic — Session 3 can simply `from crt_engine import detect_h4_crt` and call it with the same dict-shape inputs the backtest passes. `_utc_to_session` is already shared via `adaptive_engine.py`. The blacklist check, env-flag handling, time-unit cross-check, mitigation key, and confluence gating all live INSIDE the shared module — Session 3 gets all of these for free.

However, five Session-3-must-fix items emerged:

1. The live `signals` table at `crypto_alert.py:201-246` has NO `source` column — Session 3 must add an ALTER TABLE migration mirroring `backtest.py:2137` BEFORE wiring CRT into `save_signal()`, or H4_CRT signals will be silently lumped with 5M_SWEEP in any per-source attribution.
2. The backtest's outcome attribution uses `check_outcome()` / `compute_excursions()` / `triple_barrier_label()` synchronously in the same call — the LIVE path has no analog (outcomes are tracked asynchronously by the tracker watching open signals). This is structural, not a parity bug, but it means the backtest `outcome` column is a forward-simulated label while live's eventual `result` comes from real lifecycle tracking. The CRT scanner does not change this asymmetry, but the per-source WR comparison must be aware of it.
3. `consumed_sweeps`-style mitigation memory is in-memory-only in the live bot (`crypto_alert.py:154`) — it does NOT survive a restart, while the backtest's CRT `consumed` set is fresh-per-call. Spec doc §15 says live SHOULD persist; this is a known deferred item, but Session 3 must either persist `consumed` to StateStore or document the divergence.
4. TP/SL ladder for CRT signals: backtest uses entry +/- 1.5R / 2.0R for TP2/TP3 (`backtest.py:1356-1360`). Session 3 must mirror this EXACTLY in the live path — using `compute_ict_trade_plan()` instead (the 5M-sweep ladder) would silently diverge. Best path: extract a `compute_crt_trade_plan()` helper into `crt_engine.py`.
5. Iteration semantics are NOT equivalent in the strict sense — backtest walks a sliding H4 window forward and can fire on the FIRST window that encloses a valid C1+C2+MSS triplet; live fires on whatever the CURRENT cache contains at scan time, which may have rotated past the optimal MSS bar (especially for older C2 candles within `H4_CRT_C2_LOOKBACK=10`). In practice this should produce equivalent signals for recent-C2 setups but may cause backtest to capture some setups live would miss (selection bias in favor of backtest WR).

No CRITICAL parity-killers were found. The Session 2 backtest is well-structured for Session 3 integration provided the five items above are addressed.

---

## 2. CRITICAL findings — none

No findings rise to CRITICAL (live and backtest will produce non-overlapping signals from the same input). The shared-module pattern prevents the worst class of drift by construction.

---

## 3. HIGH findings

### H-1 — `signals` table missing `source` column in live DB
**Files:** `crypto_alert.py:201-246` (CREATE TABLE), `crypto_alert.py:307-346` (migration ALTER list), `backtest.py:2137`
**Issue:** The backtest `backtest_signals` table has `source TEXT DEFAULT '5M_SWEEP'` migration. The live `signals` table has NO `source` column in either the CREATE or the ALTER migration list. When Session 3 wires CRT into `save_signal()` and tries to write `source='H4_CRT'`, either: (a) the INSERT will fail silently if the column is missing, or (b) if Session 3 forgets to add it, all live CRT signals will be indistinguishable from 5M sweep signals in the tracker / DSR / CPCV pool.
**Fix for Session 3:** Add `("source", "TEXT DEFAULT '5M_SWEEP'")` to the migration list at `crypto_alert.py:308-346` AND extend the INSERT at `crypto_alert.py:630-644` to include the `source` column.

### H-2 — Mitigation memory does NOT persist across bot restart in live
**Files:** `crypto_alert.py:154` (`consumed_sweeps` in STATE dict), `crypto_alert.py:3246-3255` (StateStore — does NOT include consumed_sweeps in defaults), `crt_engine.py:175-186` (docstring notes caller is responsible for `consumed` mgmt)
**Issue:** Backtest's CRT `consumed` set is fresh-per-call (`backtest.py:1294`). Live's `consumed_sweeps` is in `STATE[token]` (in-memory only). Neither persists across restart in current code. Spec doc §15 explicitly says live's `consumed` SHOULD persist to bot_state for restart-safety. Without this:
  - Bot restart → re-emits the same H4 CRT signal on the same C1 zone (operator alert duplication)
  - Backtest will NEVER do this because it walks once
  - Live and backtest will disagree on signal counts whenever a restart happens during an active C1 zone
**Fix for Session 3:** Add `consumed_crt_keys` to StateStore defaults at `crypto_alert.py:3247-3253`, persist it on every signal emission, prune entries older than `H4_CRT_C2_LOOKBACK * 4h` to bound the set size. JSON-serialize tuple keys as lists.

### H-3 — TP2/TP3 ladder is inlined in backtest; Session 3 must NOT diverge
**Files:** `backtest.py:1352-1360` (CRT-specific 1.5R/2.0R ladder)
**Issue:** The backtest CRT scanner computes TP2 = entry +/- 1.5R, TP3 = entry +/- 2.0R as inline math. There is no shared `compute_crt_trade_plan()` helper. If Session 3 calls the existing `compute_ict_trade_plan()` (which the 5M sweep path uses at `crypto_alert.py:2402`), the TP ladder will use liquidity targets instead of fixed R-multiples — silent divergence. The CRT spec is explicit that the universal CRT TP is the opposite extreme of C1 (already in `setup["tp1"]`); only TP2/TP3 need a convention.
**Fix for Session 3:** Either (a) extract a `compute_crt_trade_plan(setup, entry_price)` helper into `crt_engine.py` returning the full dict with tp1/tp2/tp3/sl/rr1/etc., and call it from BOTH backtest and live; or (b) duplicate the inline math at the live call site with an explicit comment cross-referencing `backtest.py:1352-1360`. Option (a) is the safer parity-by-construction pattern and consistent with how `detect_h4_crt` itself is shared.

---

## 4. MEDIUM findings

### M-1 — Sliding-window vs single-snapshot iteration is not strictly equivalent
**Files:** `backtest.py:1300-1327` (H4 window sliding loop), `crt_engine.py:267-270` (`H4_CRT_C2_LOOKBACK` controls how many H4 candles back the detector scans on each call)
**Issue:** Backtest iterates `for h4_end in range(H4_WINDOW, n4)` — at each step a 12-bar window ending at `h4_end` is passed to the detector. A given C1/C2 pair may be visible in MULTIPLE consecutive windows; the mitigation `consumed` set prevents re-firing. So the FIRST window that produces a valid (C1, C2, MSS, confluence) tuple wins.

Live calls `detect_h4_crt` once per 5-min scan cycle with the most-recent ~30 H4 bars cached. If the live cache covers the SAME C2_LOOKBACK=10 window, the detector sees the same C2 candidates. However: live scans every 5 minutes, so a setup whose MSS confirms 25 minutes after C2 close will see TWO live cycles miss it (insufficient 5M bars after C2) and the THIRD cycle catch it. Backtest's window catches it the moment the H4 close + 60-bar headroom is in range. In most cases these are equivalent — but for setups where MSS confirms RIGHT at the edge of the 30-bar `H4_CRT_MSS_HORIZON`, ordering effects could cause live to miss what backtest caught.
**Severity:** MEDIUM because the actual signal-level WR shouldn't shift much, but the SIGNAL COUNT will differ — backtest may produce slightly more H4_CRT signals than live on the same data window. Affects per-source attribution if the operator compares signal counts directly.
**Fix for Session 3:** Document this as a known structural difference in spec doc §7. Consider adding a parity test that runs `detect_h4_crt` on N consecutive sliding 5M snapshots and checks that the signal set is a SUPERSET of the snapshot-only detection (live should be ⊆ backtest, not equal).

### M-2 — Outcome attribution path is fundamentally different (acknowledged structural)
**Files:** `backtest.py:541-606` (`check_outcome` + `compute_excursions`), `crypto_alert.py` — no equivalent (lifecycle tracked by tracker)
**Issue:** Backtest synchronously simulates forward bars and produces `outcome`, `tp_reached`, `mfe_pct`, `mae_pct`, `realized_r`, `tb_*` in the same dict as the signal. Live writes `outcome='OPEN'` and tracker.py later updates it via real-time price polling. CRT signals will follow the same pattern via the shared `save_signal()` path. The CRT-specific outcome fields don't add new drift, but Session 3 should NOT replicate `check_outcome` logic in the live path — keep relying on the tracker.
**Severity:** MEDIUM only as documentation — no code fix needed if Session 3 simply lets `outcome` default to OPEN at insert time.

### M-3 — `entry_type` field shape differs between backtest CRT and live 5M sweep
**Files:** `backtest.py:1453` uses `f"H4_CRT_{setup['confluence']['type']}"` → produces `"H4_CRT_FVG"` or `"H4_CRT_OB"`. Live 5M sweep uses values from `detect_5m_ifvg_entry()` (e.g. `ZONE_TOUCH`, `IFVG_5M`, etc.)
**Issue:** This is a legitimate distinguishing tag — the dashboard's entry_type filter will now have new values. Not a parity bug but Session 3 must use the IDENTICAL string format at the live call site. Recommend extracting the format into a constant in `crt_engine.py`: `CRT_ENTRY_TYPE_TEMPLATE = "H4_CRT_{}"`.

### M-4 — Default-value fields (regime, bias_4h, trend_1h) hardcoded to "UNKNOWN"/"NEUTRAL"
**Files:** `backtest.py:1424` (`regime='UNKNOWN'`), `1443` (`trend_1h='NEUTRAL'`), `1444` (`bias_4h='NEUTRAL'`)
**Issue:** Backtest CRT signals do NOT compute regime / bias_4h / trend_1h — they're tagged as defaults because CRT operates above the regime classifier. Live CRT will ALSO need to use these same defaults rather than the regime/bias values it just computed for the 5M sweep path in the same cycle, or per-source filtering on these columns will lump CRT signals incorrectly. Easy to forget at the live site since these variables ARE in scope.
**Fix for Session 3:** When building the live CRT signal dict, explicitly override regime='UNKNOWN', trend_1h='NEUTRAL', bias_4h='NEUTRAL' rather than reusing the cycle's computed values. Add a code comment cross-referencing this.

---

## 5. LOW findings

### L-1 — `import bisect as _bisect_local` inside the loop
**File:** `backtest.py:1313`
**Issue:** Cosmetic — the import happens inside `run_backtest_token_h4_crt`, executed once per token. Should be at module top. No functional impact.

### L-2 — `confidence=10` hardcoded for all CRT signals
**File:** `backtest.py:1425`
**Issue:** "CRT is high-confluence by construction" comment is true, but confidence=10 is the maximum value — it will bias any confidence-weighted aggregator. Session 3 should use the same hardcoded value or this becomes a divergence. Recommend lifting into a `crt_engine.py` constant.

### L-3 — Time-unit contract relies on `type()` equality, not `isinstance()`
**File:** `crt_engine.py:250`
**Issue:** `if type(h4_times[0]) is not type(c5m_times[0])` will treat `numpy.int64` and `int` as different types even though both encode ms. Both backtest and live receive list[int] from Binance — so this is currently fine, but Session 3 must NOT introduce a path where pandas DataFrames are used in live (the cache could return numpy ints from a DataFrame). Document the int-list contract explicitly in `crt_engine.py`.

### L-4 — Token blacklist normalization is asymmetric on input side
**Files:** `crt_engine.py:218` (`token.upper() in H4_CRT_DISABLED_TOKENS`), `backtest.py:1278` (`token.upper() in H4_CRT_DISABLED_TOKENS`)
**Issue:** Both paths uppercase the input token. The set `H4_CRT_DISABLED_TOKENS` is built with `.strip().upper()` at `crt_engine.py:62-65`. Symmetric and case-insensitive — confirmed OK. Noted for completeness.

---

## 6. Per-Section Parity Matrix

| # | Check | Verdict | Notes |
|---|---|---|---|
| 1 | Helper function parity | PARTIAL | `_utc_to_session` shared (OK). `check_outcome` / `compute_excursions` are backtest-only and MUST NOT be replicated live (M-2). `triple_barrier_label` shared via labeling.py (OK). |
| 2 | Signal dict shape | NEEDS WORK | `signals` table missing `source` column (H-1). Default-field hardcoding is necessary (M-4). |
| 3 | Sliding window vs scan cycle | DOCUMENT | Backtest superset, live subset — known structural (M-1). |
| 4 | Mitigation set persistence | NEEDS WORK | Live `consumed_sweeps` is in-memory only; spec says persist (H-2). |
| 5 | ENABLE_H4_CRT env flag | OK | Module-level constant read at import; same env flag, same semantic in both paths. |
| 6 | Per-token blacklist | OK | Case-insensitive `.upper()` on both sides (L-4 confirmed clean). |
| 7 | Time unit handling | OK | Binance returns int ms on both paths; `type()` cross-check at `crt_engine.py:250` will pass. L-3 is a future-proofing note. |
| 8 | TP/SL computation | NEEDS WORK | TP2/TP3 ladder inlined in backtest only — Session 3 must replicate exact 1.5R/2.0R formula, NOT call `compute_ict_trade_plan` (H-3). |
| 9 | Signal emission cadence | DOCUMENT | Subset-of-backtest live emissions per M-1; OK in practice. |
| 10 | `source='H4_CRT'` tag | OK in backtest, PENDING in live | Backtest sets it explicitly (`backtest.py:1470`); live must set the IDENTICAL string. |

---

## 7. Session 3 Design Recommendations

### Mandatory before Session 3 ships
1. **Add `source` column to live `signals` table** (H-1). New migration line in `crypto_alert.py:307-346` ALTER list. Extend INSERT at `crypto_alert.py:630-644`. Verify back-compat: existing live signals receive default `'5M_SWEEP'`.
2. **Extract a `compute_crt_trade_plan(setup, entry_price, token)` helper into `crt_engine.py`** returning the full plan dict (sl, tp1, tp2, tp3, sl_pct, tp1_pct, tp2_pct, tp3_pct, rr1, rr2, rr3). Refactor `backtest.py:1352-1360` to use it. Live calls the SAME helper. This is the single most important parity-by-construction action because the TP ladder is otherwise easy to silently desynchronize (H-3).
3. **Persist live `consumed_crt_keys` to StateStore** (H-2). JSON-serialize tuples as 3-element lists; restore as tuples on load. Add a TTL prune step on every cycle (`H4_CRT_C2_LOOKBACK * 4h * 2` is a safe upper bound).
4. **Hardcode regime/bias/trend defaults when building the live CRT signal dict** (M-4). Cross-reference the backtest line numbers in a comment so a future reader sees the parity intent.

### Strongly recommended
5. **Add a parity unit test**: feed the same fixed (c4h, c5m) inputs to both `run_backtest_token_h4_crt`'s detection call AND a simulated live single-snapshot call. Assert the live snapshot's signal set is a subset of the backtest's signal set. Catches future drift in either path.
6. **Lift the `confidence=10` and `entry_type` format string into module-level constants in `crt_engine.py`** (L-2, M-3). Both backtest and live import the constants; no string literal duplication.
7. **Promote the `H4_WINDOW = 12` constant in `backtest.py:1299` to `crt_engine.H4_CRT_DETECT_WINDOW`** with the documented invariant `H4_CRT_DETECT_WINDOW >= H4_CRT_C2_LOOKBACK + 2`. Live should slice the cache to the same window size before passing in.

### Optional polish
8. Move `import bisect` to module top in `backtest.py` (L-1).
9. Document the int-ms time-unit contract explicitly in `crt_engine.py` (L-3).

---

## Closing assessment

The Session 2 implementation is a textbook example of shared-module parity-by-design: detection logic lives in `crt_engine.py`, both paths import the same function, the time-unit cross-check guards against silent mixed-type bugs, and the mitigation key was correctly migrated from list-index to timestamp during the Session 1 audit (C-CRT-1 fix). What's left for Session 3 is purely the integration boilerplate at the live call site — but FIVE of those integration choices (source column, TP ladder, consumed persistence, default field overrides, dict shape) can silently break parity if Session 3 author is not careful. The recommendations above shift those choices into shared code so the parity becomes structural rather than discipline-dependent.

