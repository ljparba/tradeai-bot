# Backtest Bias Detector — Post-CRT-Pro Audit (Cycle 8)
**Date:** 2026-05-27
**Auditor model:** claude-sonnet-4-6
**Prior score:** 9.0/10 (cycle-7)
**Files audited:** `backtest.py`, `crt_engine.py`, `adaptive_engine.py`, `validation.py`, `docs/comprehensive/CROSS_REF.md`, `.claude/CRT_STRATEGY_CONTEXT.md`

---

## CRITICAL BIASES

### CRITICAL-1: Wyckoff Lookahead — `detect_wyckoff_context(c4h)` receives full dataset

**File:** `backtest.py:1469`
**Code:**
```python
wyckoff_context = detect_wyckoff_context(c4h)
```
**Mechanism:** The outer walk loop iterates `h4_end` from `h4_window` to `n4` (all 365 days of H4 bars). The inner detection sub-window `c4h_win` is correctly sliced to `c4h[h4_start:h4_end]` to avoid lookahead. However, immediately after the `setup` is found, `detect_wyckoff_context` is called with the **full** `c4h` dict — all 365 days of H4 candles — not with `c4h_win`.

`detect_wyckoff_context` internally slices `closes[-window_n:]` where `window_n = min(n, WYCKOFF_H4_LOOKBACK=120)`. This always reads the **final 120 bars of the full dataset** regardless of where in the timeline `h4_end` currently sits. For a signal at `h4_end=200` (roughly January 2025 in a 365-day backtest), the function computes Wyckoff context from bars 2080–2200 (December 2025 future candles), not from bars 80–200.

**Why it invalidates results:**
- Every Wyckoff label (ACCUMULATION/DISTRIBUTION/MARKUP/MARKDOWN/TRANSITION) stored in `entry_type` for every CRT signal was computed using future H4 prices.
- When `WYCKOFF_PHASE_FILTER != "off"`, signals are accepted or rejected based on this future-contaminated label — a direct trade-filter lookahead bias. The article claims 55-62% WR under the filter; that WR cannot be trusted.
- When the filter is `"off"` (current operator config), the label is still stored in `entry_type`. Any analysis correlating `entry_type` with outcomes (retrospective per-context WR, OGD feature learning via context bucket) will carry this contamination.
- Bias direction: optimistic for Wyckoff-filtered backtests (future alignment inflates WR).
- Severity: CRITICAL when `WYCKOFF_PHASE_FILTER != "off"`. MODERATE when filter is `"off"` (tagging contaminated but filtering not applied).

**Prior-art check:** NEW FINDING — not in CROSS_REF.md. The Option KK fix (cycle-7) correctly added `detect_wyckoff_context` but did not restrict the input to the historical window.

**Estimated impact:** At `WYCKOFF_PHASE_FILTER=strict`, the article's claimed +7-12pp WR gain is unverifiable. At `off` (current config), contextual analysis buckets are corrupted.

---

## SERIOUS FLAWS

### SERIOUS-1: `detect_wyckoff_context` also called from live path with fresh data only — live/backtest asymmetry

**File:** `crypto_alert.py` (live scanner `scan_h4_crt_for_token`)
**Mechanism:** In live trading, `detect_wyckoff_context` is called with the real-time H4 candles that are available at that moment — correct behavior. In backtest, it gets the entire historical array. This means even with the filter `"off"`, any future run that uses `WYCKOFF_PHASE_FILTER=loose/strict` will overstate WR vs what the live bot would achieve.

**Prior-art check:** Downstream from CRITICAL-1. Not separately in CROSS_REF.md.

---

### SERIOUS-2: CRT signal `trend_1h` field hardcoded `"NEUTRAL"` in backtest dict, even when 1H trend IS computed

**File:** `backtest.py:1600`
**Code:**
```python
"trend_1h": "NEUTRAL",
```
**Mechanism:** When `CRT_REQUIRE_1H_TREND=1`, `_trend_1h` is correctly computed via `_lookup_trend(_ind1h, ...)` at line 1452. However, the signal dict at line 1600 hardcodes `"trend_1h": "NEUTRAL"` regardless of whether `_trend_1h` was computed. The gating is correct (the trend is checked at line 1457), but the stored value is wrong.

**Impact:**
- `bootstrap_from_backtest()` reads `trend_1h` from `backtest_signals` (line 948) to run OGD learning. With `trend_1h` always `"NEUTRAL"` for all CRT signals, the OGD engine cannot learn trend-strength signal from CRT bootstrap data.
- Retrospective analytics (per-trend WR breakdown in the report) will show all CRT signals as NEUTRAL trend — suppresses true per-trend attribution.
- Not a gate-level lookahead but understates CRT's trend dependency, biasing OGD bootstrap toward NEUTRAL-feature weighting.

**Prior-art check:** NEW FINDING.

---

## MODERATE ISSUES

### MODERATE-1: Bootstrap WHERE clause now admits malformed rows from schema migration

**File:** `adaptive_engine.py:946-955`
**Mechanism:** The loosened WHERE clause admits rows where `mss_quality IS NOT NULL AND mss_quality NOT IN ('', 'NONE')`. The concern is whether older `backtest_signals` rows (pre-CRT schema) have non-NULL `mss_quality` values populated from `5M_SWEEP` signals that used a different MSS quality scoring scale (e.g., the pre-score_ict_mss era or pre-PARTIAL_TP1/2 era). These rows would now pass the filter for bootstrap.

**Assessment:** LOW practical risk. The `run_id` scoping at line 958-960 limits bootstrap to the most-recent backtest run, and old-schema rows from very early runs (pre-Sprint-3) would not have a `run_id` matching the current run. When `run_id=None` is passed (pre-M-E fix era), the concern is real — but M-E has been fixed. The schema change is safe given `run_id` scoping. Flagged as moderate for documentation.

**Prior-art check:** Acknowledged in CRT_STRATEGY_CONTEXT.md §6, point 3.

---

### MODERATE-2: CPCV blending — mixed-source runs produce a single combined CPCV verdict

**File:** `backtest.py:3831-3835`, `validation.py`
**Mechanism:** When both `ENABLE_5M_SWEEP=1` and `ENABLE_H4_CRT=1`, the single `cpcv_summary(_tune_sigs)` call operates on the union of 5M_SWEEP + H4_CRT signals. The two sources have fundamentally different WR distributions (5M: 54.8% raw, CRT: 54.8%), different outcome window lengths (24h vs 48h), and different feature profiles. A blended CPCV fold may contain predominantly one source in some folds and the other in others, inflating variance and making the mean WR and Sharpe uninterpretable as representative of either source.

**Assessment:** The `blended=True` warning banner is correctly surfaced in the Honest Metrics tab and CRT_STRATEGY_CONTEXT.md §7 documents this. MODERATE rather than SERIOUS because: (a) the current operator config is CRT-only (`ENABLE_5M_SWEEP=0`), so Run #145+ CPCV is pure-CRT; (b) the blending limitation is documented. The issue applies to historical mixed runs #138-#143.

**Prior-art check:** KNOWN LIMITATION per CRT_STRATEGY_CONTEXT.md §7. Documented. Do not re-flag as new.

---

### MODERATE-3: `detect_wyckoff_context` min_bars check uses `n` (full dataset length), not `h4_end`

**File:** `crt_engine.py:857`
**Mechanism:** `if n < min_bars or len(highs) != n` — when the full `c4h` is passed (CRITICAL-1), this guard is vacuously satisfied because `n=2200` >> `min_bars=80`. If `c4h_win` were correctly passed instead, there would be early H4 windows where `len(c4h_win) < min_bars`, correctly returning "TRANSITION" (conservative default). This means the fix for CRITICAL-1 (passing `c4h_win`) will slightly change behavior at the beginning of the backtest window — a small number of early signals will get TRANSITION context instead of a classified context. This is the correct behavior but operators should be aware.

**Prior-art check:** Downstream of CRITICAL-1. Implicit in the fix.

---

### MODERATE-4: CRT `entry_type` label carries lookahead-contaminated Wyckoff context into `_trigger_weight_update` indirectly

**File:** `crypto_alert.py` live OGD path
**Mechanism:** `entry_type` (e.g. `H4_CRT_OB_ACCUMULATION`) is stored in `signals` at live signal creation. When `_trigger_weight_update` fires on signal close, it reads `feature_scores_json` (correctly built from live data). However, the `entry_type` string could be used in future OGD feature bucketing or retrospective analysis (it's stored for "retroactive per-context analysis via SQL" per the code comment at backtest.py:1612). In backtest, the ACCUMULATION/DISTRIBUTION labels are future-contaminated, so retrospective SQL analysis will draw wrong conclusions.

**Prior-art check:** Downstream of CRITICAL-1.

---

## VERIFIED STILL FIXED (regression checks per CROSS_REF.md mandate)

- **H4 (consumed_sweeps tracking):** `consumed: set = set()` initialized at line 1354, `consumed.add(setup["key"])` at line 1400. STILL FIXED.
- **H5 (MSS recency guard):** `ICT_MAX_SETUP_AGE_BARS=24` imported and used in 5M_SWEEP path. Not separately applicable to CRT (CRT uses its own horizon). STILL FIXED for 5M.
- **H6 (OGD weight contamination):** CRT path in `run_backtest_token_h4_crt` uses `DEFAULT_WEIGHTS` via `wscore=0.0` in the signal dict. Backtest scoring is H6-isolated. STILL FIXED.
- **M8 (slippage double-count):** `entry_price = c5m["opens"][entry_bar]` at line 1410 — execution model (REALISTIC_EXECUTION) applies via `execution.py`. STILL FIXED.
- **M20 (OHLCV validation in backtest):** `_valid_candle()` helper in backtest.py:294. STILL FIXED.
- **C2 (Walk-forward OOS):** `HELD_OUT_DAYS` env var + Phase C lockbox. STILL FIXED.
- **C-D (cumulative_min_trials):** DSR n_trials reads cumulative seed at backtest.py:3808-3826. STILL FIXED.
- **GAP-1/Phase A (realistic execution):** `REALISTIC_EXECUTION` in config_hash, `execution.py` integration. STILL FIXED.
- **C-N4 (DSR NameError):** `BT_DB_PATH` used at line 3781. STILL FIXED.

---

## STATISTICAL VALIDITY SUMMARY

- **CRT signals / 365d:** 416 per CRT_STRATEGY_CONTEXT.md §5 (Run #139 Test A)
- **Test period:** 365 days (BACKTEST_DAYS=365)
- **Sample size verdict:** VALID for overall WR (n=416). Per-context sub-buckets (e.g., ACCUMULATION-FVG, DISTRIBUTION-OB) have n~40-80 each — MARGINAL.
- **CRT WR:** 54.8% raw. DSR status: FAIL at current paper phase (below 55% MARGINAL threshold). CPCV running; honest. Current DSR FAIL is expected and documented.
- **Parameter count:** CRT adds 8 new env-overridable knobs (`CRT_TP1_MODE`, `CRT_TP2_RR`, `CRT_TP3_RR`, `H4_CRT_C2_LOOKBACK`, `WYCKOFF_PHASE_FILTER`, `CRT_REQUIRE_1H_TREND`, `BACKTEST_BIAS_4H_GATE`, `CRT_FORWARD_BARS`). All in config_hash. At n=416, parameter count is acceptable ratio (ratio ~52:1).
- **Out-of-sample validation:** HELD_OUT_DAYS=0 (default). The WFV runs on the full 365d tuning pool. CRT has no promoted baseline yet — in paper-validation phase.
- **n_trials_for_dsr:** `cumulative_min_trials=27` seeded from 5M_SWEEP history. CRT-only runs add distinct config_hashes via `ENABLE_H4_CRT` + `CRT_TP1_MODE` etc. in the hash. Each distinct CRT config correctly increments the DSR denominator.

---

## VERDICT

**OPTIMISTIC** — Wyckoff lookahead (CRITICAL-1) inflates Wyckoff-filtered backtest WR.

Under the current operator config (`WYCKOFF_PHASE_FILTER=off`), CRITICAL-1 does NOT affect the gating of individual signals, only their `entry_type` tagging. The core CRT WR metrics (54.8%, avg_R=0.33) are derived from signal generation and outcome simulation which are correctly time-bounded (Option B fix confirmed the H4 sub-window anchor). The lookahead only contaminates the Wyckoff classification label stored alongside each signal.

The verdict is OPTIMISTIC rather than INVALID because: any backtest run with `WYCKOFF_PHASE_FILTER=strict` or `loose` would have an invalid filter gate, but the current ship config has it `off`. If the explorer tries `WYCKOFF_PHASE_FILTER=loose/strict` as a search dimension, all resulting trial WRs are biased.

The previous cycle-7 VALID verdict (for 5M_SWEEP and CRT v1) is not reversed for the CRT-only ship config at `WYCKOFF_PHASE_FILTER=off`. The SERIOUS-2 (trend_1h hardcoded NEUTRAL) and MODERATE-1 through MODERATE-4 issues add mild optimism to OGD bootstrap quality for CRT.

---

## PROACTIVE IMPROVEMENT SUGGESTIONS

**Suggestion:** Fix CRITICAL-1 by passing `c4h_win` (not `c4h`) to `detect_wyckoff_context` at `backtest.py:1469`. Change `detect_wyckoff_context(c4h)` to `detect_wyckoff_context(c4h_win)`.
**Why:** Restores time-bounded Wyckoff context. The `c4h_win` already has `h4_window` bars ending at `h4_end` — exactly the right historical slice.
**Impact:** HIGH (removes bias from Wyckoff-filtered config comparisons; ensures retrospective SQL analysis is honest)
**Effort:** Simple (one-char change)

**Suggestion:** Fix SERIOUS-2 by storing the computed `_trend_1h` in the signal dict when `CRT_REQUIRE_1H_TREND=1`. Add a conditional at the signal dict builder: `"trend_1h": _trend_1h if CRT_REQUIRE_1H_TREND and c1h is not None else "NEUTRAL"`.
**Why:** OGD bootstrap learning for CRT becomes trend-aware; retrospective analytics can show CRT's trend sensitivity.
**Impact:** MEDIUM
**Effort:** Simple

**Suggestion:** When `WYCKOFF_PHASE_FILTER` is `loose` or `strict`, add a guard in `autonomous_explorer.py` that prevents those values from being sampled until CRITICAL-1 is fixed.
**Why:** Prevents the explorer from promoting a lookahead-biased Wyckoff-filtered config as an "improvement."
**Impact:** HIGH (prevents false promotion)
**Effort:** Simple (add to CRT_ANTI_PATTERN_LOCKS at explorer session startup)

**Suggestion:** After fixing CRITICAL-1, run a comparison backtest: same dates, same params, `WYCKOFF_PHASE_FILTER=loose/strict` before and after the fix. Compare WR deltas. This validates whether the article's 55-62% claim holds honestly.
**Why:** The current Run #140 Test B data (−5.22pp for strict) was computed with lookahead. The true effect of Wyckoff filtering is unknown.
**Impact:** HIGH (honest empirical basis for future Wyckoff work)
**Effort:** Medium (two backtest runs + diff analysis)

---

## CROSS-DOMAIN OBSERVATIONS

**Observation:** The `trend_1h` field hardcoded to `"NEUTRAL"` for CRT signals (SERIOUS-2) means the live Telegram alert messages for CRT signals will also show NEUTRAL trend even when `CRT_REQUIRE_1H_TREND=1` passes a BULL/BEAR check. The signal display in Telegram should reflect the actual gating trend.
**Relevant Agent:** live-backtest-consistency-checker
**Reason:** The gating is correct but the displayed/stored metadata doesn't match the gating computation.

**Observation:** `detect_wyckoff_context` is called unconditionally (regardless of `WYCKOFF_PHASE_FILTER` mode) to populate `entry_type`. In live `scan_h4_crt_for_token`, this call also happens. However, the live path has no lookahead by construction. The live path's `entry_type` label will be valid. The discrepancy in `entry_type` quality (valid live, contaminated backtest-with-full-c4h) means SQL comparisons between live signals and backtest signals on `entry_type` will conflate two different Wyckoff classification regimes.
**Relevant Agent:** live-backtest-consistency-checker
**Reason:** Retrospective SQL joining live + backtest signals on `entry_type` will produce semantically mixed results.

---

## SCORE: 8.7/10

**Down from cycle-7's 9.0/10.** Penalty for:
- CRITICAL-1: Wyckoff lookahead is a genuine new bias introduced in the CRT v2 Option KK shipping (−0.2)
- SERIOUS-2: trend_1h metadata bug degrades OGD bootstrap integrity for CRT (−0.1)

**Preserved strengths:** H4 sub-window anchor (Option B) correct, 4H bias lookup correct (`_lookup_4h_bias` properly time-bounded), 1H trend lookup correct (`_lookup_trend` with bisect), `adjust_crt_tp1` uses only C1 prior-bar values (no lookahead), `CRT_FORWARD_BARS` slice correctly bounded (`min(entry_bar + 1 + CRT_FORWARD_BARS, n5)`), bootstrap WHERE loosening safe under `run_id` scoping, config_hash includes all CRT knobs, DSR n_trials correctly seeded, WRITE_CPCV_VERDICT=0 correctly set by explorer.
