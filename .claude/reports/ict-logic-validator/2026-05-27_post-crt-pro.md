# ICT Logic Validator — Post CRT-Pro Audit
**Cycle:** 2026-05-27 evening (post CRT v1 + v2 + Pro v1.1 + ENABLE_5M_SWEEP toggle)
**Branch:** `main` @ `a3f2d71` (HEAD)
**Auditor:** ict-logic-validator
**Read-only.** No code changes.

**Cycle-7 baseline (2026-05-26):** ICT Logic Integrity = **9.5/10** (ict_engine.py byte-identical)
**This cycle:** **9.0/10** (regression — see C-1 below)
**Delta:** **−0.5** (one CRITICAL silent-failure on the new live CRT path)

---

## 1. Executive Summary

The CRT detection engine (`crt_engine.py`) is itself ICT-correct and economically well-gated — confirming the prior cumulative re-audit's 88/100 score. The TP1 mode helpers, Wyckoff context heuristic, and 4H-bias slice parity fix are all sound design choices well-aligned (within deliberate empirical deviations) with the Trading Wyckoff article and ICT principles.

**HOWEVER**, a single CRITICAL live-only issue blocks CRT signal emission entirely: the live integration in `crypto_alert.py` passes the raw `fetch_binance_candles` dicts (which key timestamps as `"timestamps"`) into `detect_h4_crt`, which requires the key `"times"`. The defensive guard at `crt_engine.py:357-359` silently returns `None` for every cycle. Live CRT signal count = 0 since deployment. Combined with the absent `[:-1]` forming-bar slice that the canonical 5M_SWEEP path applies, this is a CRITICAL live/BT parity break that the byte-identical detection layer cannot compensate for.

This is a NEW FINDING; not previously flagged in any audit (the Session 3 live-integration audit verified the result dict shape but did not exercise an end-to-end fetched-candle path; the unit tests pass synthetic `times`-keyed dicts that mask the bug).

---

## 2. Prior Art Verification (per CROSS_REF.md)

| Item | Status | Verified |
|---|---|---|
| H1 (ATR floor for displacement) | DONE | ✅ `ict_engine.py:189-203` — `_atr_proxy` + `_ATR_FLOOR=0.4` intact |
| H2 (MSS sequence guard) | FALSE ALARM | ✅ `ict_engine.py:230-253` — recent_sh/sl within ICT_SWEEP_LOOKBACK is correct |
| H5 (MSS recency guard) | DONE | ✅ `ict_engine.py:28` ICT_MAX_SETUP_AGE_BARS=24 still applied at `crypto_alert.py:2490` (5M_SWEEP path; gap on CRT — see L-3) |
| M1 (MSS lookback constant) | DONE | ✅ `score_ict_mss` uses `ICT_SWEEP_LOOKBACK` (lines 234, 246) |
| M2 (ASIA_KZ hours) | DONE | ✅ `adaptive_engine._utc_to_session` (confirmed via CRT live path import at crypto_alert.py:926) |
| M3 (DR swing extremes) | DONE | ✅ `compute_dealing_range` uses `find_ict_swings` (line 470) |
| M4 (FVG 50% mitigation) | KNOWN STRUCTURAL | ✅ `ict_engine.py:328-336` full-fill (close on far side) — documented |
| M5 (DR gate extended) | DONE | ✅ Strategy templates check both halves |
| M6 (cooldown anchor) | DONE | ✅ — outside ICT engine scope |
| M7 (iFVG spatial validity) | DONE | ✅ `detect_5m_ifvg_entry` overlap check at line 722 |
| L1 (4H bias most-recent swing) | DONE | ✅ `get_ict_4h_bias` uses `sh[-1][1]` and `sl[-1][1]` (lines 434, 439) |
| L4 (NY_AM_KZ skip) | SKIPPED | Confirmed dead code |

All cycle-7 ICT-engine fixes remain in place — no regressions on `ict_engine.py` itself.

---

## 3. Findings (severity-tagged)

### CRITICAL

#### C-1 — Live CRT scanner silently emits ZERO signals due to candle-key mismatch
**Classification:** NEW FINDING (not in CROSS_REF; not flagged in any prior CRT session audit)
**Files:**
- `crypto_alert.py:1761-1767` — `fetch_binance_candles()` returns `"timestamps"` (plural)
- `crypto_alert.py:1825` — `state["candles"][tf] = data` (stores fetcher output verbatim)
- `crypto_alert.py:3776` — `_c4h = STATE[token]["candles"]["4h"]` (passes raw dict to CRT scanner)
- `crypto_alert.py:3780` — orphaned comment "Inject 'times' if missing (some fetch paths use 'time')" — **the injection is NOT implemented**
- `crt_engine.py:357-359` — `required_keys = {..., "times"}; if not required_keys.issubset(...): return None` — silently fails

**Evidence:**
1. Live fetcher (`fetch_binance_candles`) emits dict with key `"timestamps"`. Verified: `grep -n '"timestamps"' crypto_alert.py:1766`.
2. CRT engine requires key `"times"`. Verified: `grep -n '"times"' crt_engine.py` (lines 358, 365, 370, etc.).
3. No remapping happens before `scan_h4_crt_for_token` is called. Verified: `grep -n '"times"' crypto_alert.py` returns only line 804 (CRT scanner internals) and line 3780 (orphan comment).
4. 5M_SWEEP path correctly reads `c5m_raw.get("timestamps", ...)` at line 2454 — proving the canonical state shape is `"timestamps"`.
5. Live `signals` table: zero `H4_CRT` rows. `data/signals.db` reports `signals.count = 0` (operator is in CRT-only mode with ENABLE_5M_SWEEP=0; 5M_SWEEP also disabled → no rows expected for that source. But CRT path should be emitting and isn't).
6. Bot log shows 2919 cycles with zero "[CRT]" or "[H4_CRT]" log lines.
7. The unit tests `test_crt_live_integration.py:_flat_candles` construct synthetic dicts with `"times"` key (line 50) — the test fixture matches what CRT engine expects but does NOT match what the live fetcher emits. Test blindspot.

**Why it slipped through:**
- Session 3 audit verified the result-dict construction shape (`scan_h4_crt_for_token` returns the right schema) but the audit harness used `_flat_candles()` with the `"times"` key already injected — never exercised the real fetched-candle path.
- The defensive guard at `crt_engine.py:357-359` returns `None` (rather than raising) — silent failure, no operator-visible error.
- `_crt_reason` is captured at `crypto_alert.py:3785` but never printed — `"no_setup"` would mask the underlying issue even if logged.

**Impact:**
- Operator's "CRT-only paper soak" is producing zero CRT signals. Adaptive learning has no closes to learn from. CPCV/DSR pool unchanging. Wyckoff phase tagging is also stuck (never computed).
- This is a TOTAL functional outage of the new live CRT path — not a parameter calibration issue.

**Suggested fix (illustrative; not applied):**
At `crypto_alert.py:3776-3779` (or inside `scan_h4_crt_for_token`'s entry), normalize the key:
```python
_c4h_norm = dict(_c4h)
if "times" not in _c4h_norm and "timestamps" in _c4h_norm:
    _c4h_norm["times"] = _c4h_norm["timestamps"]
# repeat for _c5m
```
Add a regression test that calls `scan_h4_crt_for_token` with the exact dict shape returned by `fetch_binance_candles` (i.e. `timestamps`-keyed) and asserts not-None on a constructed CRT setup.

**Severity:** CRITICAL — production-impacting silent failure on the only active scanner.

---

#### C-2 — Live CRT consumes FORMING (non-closed) 4H + 5M bars (lookahead/repaint risk)
**Classification:** NEW FINDING
**Files:**
- `crypto_alert.py:3776-3777` — passes `STATE[token]["candles"]["4h"]` and `["5m"]` directly (no `[:-1]` slice)
- `crypto_alert.py:2450-2454` — 5M_SWEEP path correctly applies `[:-1]` to exclude the forming bar
- `crypto_alert.py:2498-2500` — same for 4H

**Evidence:**
- The canonical 5M_SWEEP path slices `c5m_raw.get("highs", [])[:-1]` etc. for every TF (5M, 4H, 1H) at lines 2450-2454, 2498-2500. This is the project-wide invariant for non-repainting signal generation.
- The CRT live integration at line 3776 reads STATE candles RAW. The last 4H bar in the cache is the currently-forming H4 bar (open ≤ now, close > now). The last 5M bar is similarly forming.
- `detect_h4_crt` then evaluates the most-recent H4 bar as potential C2, and the most-recent 5M bars for MSS confirmation. Both can repaint within the cycle.

**Repaint scenarios:**
1. Forming H4 bar wicks below C1.low → BUY-side sweep detected → MSS confirms → signal emitted. Two hours later the same forming H4 closes back ABOVE C1.low — the sweep was a transient wick that got pulled back. The signal was emitted on a bar that never closed in the swept state.
2. Forming 5M MSS bar is treated as confirmed (`mss_bar = mss["mss_bar"]`); the next bar (`entry_bar = mss_bar + 1`) is the bar AFTER the still-forming MSS bar — i.e., the entry is fictional until the MSS bar actually closes.

**Compare with backtest:** the backtest `run_backtest_token_h4_crt` walks closed historical bars only — no forming-bar concept exists in replay. So this introduces a live/BT divergence the byte-identical detection layer alone cannot fix.

**Mitigating factor:** the `consumed` mitigation set is keyed on `(c1_time, c1_high, c1_low)`, so a forming-bar-induced spurious sweep would be re-evaluated next cycle. But the FIRST signal of the cycle has already been emitted to Telegram (or saved to DB).

**Severity:** CRITICAL (live/BT consistency + ICT non-repaint invariant). Same root cause as C-1 in that the live path doesn't apply the same input-shaping the 5M path does. Resolving C-1 should be paired with C-2's fix in one patch.

---

### HIGH

#### H-1 — Wyckoff `pre_range_trend` uses two single-bar snapshots (noise-vulnerable)
**Classification:** NEW FINDING (Wyckoff v2 was shipped today)
**File:** `crt_engine.py:894-912`

The `pre_range_trend` classification compares `c[pre_range_idx]` vs `c[range_start_idx]` — two single closes (~40 bars apart at default settings). One outlier close at either anchor flips the trend label. Per Wyckoff theory, phase identification should be based on the AGGREGATE structure (e.g., higher highs / higher lows), not point-to-point deltas.

**Mitigating factor:** the env knob `WYCKOFF_PHASE_FILTER=off` is currently active by operator decision (strict mode rejected empirically). When the filter is off, this noise doesn't reject signals — it only mis-tags `entry_type` for downstream analysis. Severity bounded.

**Suggested improvement:** use `mean(c[pre_range_idx-3:pre_range_idx+1])` vs `mean(c[range_start_idx-3:range_start_idx+1])` — 4-bar averages instead of single closes. Or compare EMA(10) at those two indices.

**Severity:** HIGH if filter is enabled; LOW with current `off` config.

---

#### H-2 — TP1 `min_1r` and `fixed_1r` modes can place TP1 in non-liquidity space
**Classification:** NEW FINDING (CRT Pro v1.1 shipped today; operator is using `min_1r`)
**File:** `crt_engine.py:167-211`

The canonical CRT trade-management rule (Trading Wyckoff article, §7 + universal source agreement) is: **TP1 = opposite extreme of C1**. The opposite extreme is where retail stops sit on the unswept side — i.e., LIQUIDITY. Taking TP1 there extracts liquidity per ICT principles.

The new `fixed_1r` mode replaces TP1 with `entry ± 1R`. This is a pure R-multiple target — there is no guarantee that the resulting price corresponds to a liquidity pool, swing high/low, or any structural level. In ICT terms, this is "TP at noise."

The `min_1r` mode is more defensible (uses C1 opposite when it's ≥1R, else extends to 1R). But when extending, it still lands at an arbitrary R-multiple price.

**Operator's empirical justification:** Run #139 showed 52.5% of dynamic-mode setups had TP1 < 1R from entry, capping avg_R below 5M_SWEEP's elite tier. The deviation is data-driven.

**ICT-pure recommendation:** Instead of an arbitrary R-multiple, use `compute_liquidity_targets()` (already in `ict_engine.py:500`) to find the next ACTUAL liquidity level beyond C1's opposite extreme — same approach the 5M_SWEEP path takes for its TP1. This would let `fixed_1r` and `min_1r` modes target real liquidity at a higher R-multiple rather than synthetic levels.

**Severity:** HIGH — strategic departure from ICT principles, but empirically justified. Worth surfacing for future iteration.

---

#### H-3 — No CRT-equivalent of ICT_MAX_SETUP_AGE_BARS staleness guard
**Classification:** NEW FINDING / STILL OPEN
**Files:**
- `ict_engine.py:28` — `ICT_MAX_SETUP_AGE_BARS = 24` (the 5M_SWEEP staleness cap)
- `crypto_alert.py:2490` — 5M_SWEEP enforcement (rejects if `len(c5) - 1 - sweep["bar"] > 24`)
- `crt_engine.py` — no equivalent setup-age check; only the `H4_CRT_MSS_HORIZON=30` cap on MSS confirmation distance

**Rationale:** ICT's "killzone validity window" says a setup is only valid within its originating killzone/session. The 5M_SWEEP path enforces this via the 24-bar (2h) age cap. CRT inherits this implicitly via `H4_CRT_MSS_HORIZON` (30 5M bars = 2.5h max between sweep and MSS), but does NOT cap age from MSS to entry.

In live operation, if a CRT setup's MSS confirms but the bot is restarted or the cycle gates trip, the consumed-set persistence might prevent re-emission of the same setup. But within a single cycle, there's no upper bound on how old the MSS bar can be relative to the current bar.

**Mitigating factor:** `entry_bar = mss_bar_5m + 1` and the entry uses that bar's open price. In backtest this is fine (closed bars only). In live, this would emit at MSS+1 only if MSS+1 has just closed; if MSS was N cycles ago and not yet emitted (e.g., due to bias gate flickering), the entry price becomes stale.

**Severity:** HIGH (logic) / LOW (practical) — most CRT setups will fire in the cycle they're detected. Worth adding a `CRT_MAX_MSS_AGE_BARS=6` (30min) cap for defense-in-depth.

---

### MEDIUM

#### M-1 — Live `c4h` slice for bias gate may include the forming bar
**Classification:** NEW FINDING (related to today's MEDIUM-1 fix)
**File:** `crypto_alert.py:825-832`

Today's MEDIUM-1 fix correctly slices `_closes_full[-_N:]` where `_N = min(len(_closes_full), 210)`. This matches the backtest's `_lookup_4h_bias` slice size.

**However**, the backtest's `_lookup_4h_bias` (backtest.py:565-577) uses `idx = bisect.bisect_right(ind4h["times"], ts_ms - 1) - 1` — this gives the most-recent **CLOSED** bar at `ts_ms`. Live uses `c4h["closes"][-_N:]` which includes the **FORMING** bar (since live's STATE candles cache includes the in-progress bar).

This is the same root cause as C-2 but applied to the bias lookup specifically. The bias calculation thus uses 209 closed bars + 1 forming bar in live, vs 210 closed bars in backtest. EMA50/EMA200 on the 210th forming bar can be slightly different from the closed-bar truth.

**Suggested fix:** `_closes_full = c4h.get("closes", [])[:-1]` before slicing (and same for highs/lows).

**Severity:** MEDIUM — bias gate is binary (BULLISH/BEARISH/NEUTRAL), and the forming bar's contribution to EMA200 is < 1% weight. Empirically rare to flip a label. But it's a non-parity micro-divergence.

---

#### M-2 — `_check_confluence` swept-extreme zone uses geometric midpoint, not OB-aware structure
**Classification:** NEW FINDING (minor design observation)
**File:** `crt_engine.py:265-270`

The confluence overlap check restricts FVG/OB to the "swept half" of C1 — for bullish CRT, the demand zone is `[c1_low, c1_mid]`. The midpoint is computed geometrically: `c1_mid = (c1_high + c1_low) / 2`.

ICT theory more precisely uses the **OTE zone** (Optimal Trade Entry: 0.618-0.79 retracement of the swept leg). The geometric midpoint (50%) is a reasonable coarse proxy but isn't the canonical ICT zone. A FVG at the 0.55 level (slightly above midpoint) would be excluded as "wrong half" when ICT methodology would still consider it part of the discount/premium zone.

**Severity:** MEDIUM — design choice, not a bug. The 50%-of-range proxy is the H-CRT-1 closure pattern and empirically reasonable.

---

### LOW

#### L-1 — `detect_wyckoff_context` "consolidating" criterion is range-width-dependent
**File:** `crt_engine.py:891-892`

`is_consolidating = consolidation_ratio < 0.5` where `consolidation_ratio = recent_range / full_range`. If the full 120-bar lookback range is wide (e.g., 30% price swing) and the recent 40-bar range is 10%, consolidation_ratio = 0.33 → consolidating. But a 10% range in 40 bars (~7 days) is NOT consolidation in any practical sense — it's normal trending action.

The ratio should probably be calibrated to absolute volatility (ATR-relative), not relative range. With `WYCKOFF_PHASE_FILTER=off` this is inert.

#### L-2 — `pre_range_idx = -(2 * recent_n)` can equal `-window_n`, accessing the same bar as `range_low`'s anchor
**File:** `crt_engine.py:896-898`

When `window_n == 2 * recent_n` (e.g., lookback=80, recent_window=40), `pre_range_idx = -80 = -window_n`. Accessing `c[-80]` is the FIRST bar in the window. `start_close = c[-40]`. This is correct Python — just confirming no off-by-one — but the boundary check `abs(pre_range_idx) <= window_n` should arguably be `<`, not `<=`, to ensure both reads have headroom. Edge case; off by one bar.

#### L-3 — CRT confidence floor at 6 ignores actual setup strength below that
**File:** `crt_engine.py:719-721`

`crt_quality_to_confidence` returns `max(6, min(10, 6 + (pts * 2) // 3))`. The floor of 6 means ALL CRT signals (even pts=0 = both NONE quality) get confidence 6. The OGD weight engine + downstream stratification (tracker UI's "confidence band") can't distinguish a HIGH+HIGH (=10) from a NONE+NONE (=6) below the floor. This was acknowledged in Option H's docstring but suggests a future-iteration audit point: when both qualities are NONE (pure-OB confluence), confidence should logically be 5 or 4, not 6.

#### L-4 — Time-unit check is shallow (type-only, not unit-level)
**File:** `crt_engine.py:382-386`

`if type(h4_times[0]) is not type(c5m_times[0]): return None` checks that the types match (both int, or both pd.Timestamp). It does NOT check that both are in the SAME unit (e.g., both are unix milliseconds vs one is unix seconds). A pd.Timestamp passed for h4 and an int for c5m would correctly bail; but two ints with different epoch scales would silently produce wrong sweep-anchor offsets. Acknowledged in the docstring (M-CRT-6 note), but the check is weaker than the docstring implies.

---

## 4. Cross-Domain Observations

**Observation:** C-1 (live CRT silently emits zero signals) directly impacts the live-backtest-consistency-checker, adaptive-learning-code-reviewer, and tracker-frontend audits. Each may have reported "clean" findings under the assumption that CRT signals were flowing in production.
**Relevant Agents:** live-backtest-consistency-checker, adaptive-learning-code-reviewer, tracker-frontend-audit
**Reason:** The adaptive learning audit may have concluded that CRT OGD plumbing works "because feature_scores_json is populated and the bridge exists" — but in production the bridge has zero traffic. Tracker frontend's `by_source` panel will show no CRT rows; the auditor should re-verify whether they detected this empty state. The LBC auditor should confirm whether the parity tests they ran exercised the real candle-dict shape vs synthetic test fixtures.

**Observation:** The orphaned comment "Inject 'times' if missing (some fetch paths use 'time')" at crypto_alert.py:3780 suggests the engineer who wrote the Session 3 integration was AWARE of the key-naming issue but the injection never made it into the diff. This implies the test suite never exercised the bug-revealing path.
**Relevant Agent:** professional-code-quality-reviewer
**Reason:** Test fixture realism is the gap — `_flat_candles()` should mirror the actual fetcher output schema, not the engine input schema. Synthetic fixtures that match the IMPLEMENTATION rather than the REAL data source mask integration bugs.

**Observation:** `compute_crt_feature_scores` always passes `dr_location="UNKNOWN"` because CRT doesn't compute dealing range. The OGD `extract_ict_feature_scores` will give UNKNOWN a floor contribution. Over many CRT closes, the `dr_location` weight gradient will be undertrained.
**Relevant Agent:** adaptive-learning-code-reviewer
**Reason:** Worth surfacing whether the OGD engine should de-prioritize the `dr_location` feature for CRT signals (rather than including its floor as noise) — possibly via per-source feature mask.

---

## 5. Proactive Improvement Suggestions

### Suggestion 1: Add EQH/EQL clustering to CRT C1 candle confluence
**Why:** Per canonical ICT (Fix #9 from cycle 11), EQH/EQL clusters are stronger liquidity pools than isolated swing extremes. A CRT C1 whose high/low coincides with an EQH/EQL cluster is structurally a higher-tier setup. Currently `find_eqh_eql_clusters()` is computed for the 5M_SWEEP path but not consulted by CRT.
**Impact:** MEDIUM
**Effort:** Simple — pass `sh_clusters/sl_clusters` (already computed at the H4 level conceptually) to `detect_h4_crt` and surface `cluster_size` on the setup dict for OGD's `mss_quality` enhancement.

### Suggestion 2: Add OTE (Optimal Trade Entry) zone validation for CRT entries
**Why:** ICT methodology positions OTE at the 0.618–0.79 retracement of the manipulation leg. Currently CRT entries fire at `mss_bar + 1` open with no retracement check. The MSS bar might be at the 0.50 retracement, or at 0.10 — there's no zone constraint. Validating that the entry falls within OTE would lift WR per ICT theory (and is the canonical institutional confluence beyond MSS+FVG).
**Impact:** MEDIUM-HIGH
**Effort:** Medium — compute the sweep-to-MSS leg's 0.618-0.79 zone in `detect_h4_crt`; gate the entry on `entry_price` falling inside it.

### Suggestion 3: Explicit CHoCH vs BOS labeling on CRT signals
**Why:** ICT distinguishes CHoCH (first break of opposite structure → reversal signal, what CRT is) from BOS (continuation break in same direction). CRT setups should ALL be CHoCH by construction (the C2 sweep reverses prior trend; the 5M MSS confirms the reversal). Currently the signal's `entry_type` field is `H4_CRT_<FVG|OB>_<phase>` — no CHoCH/BOS tag. Adding this labeling would surface useful diagnostic info and align with ICT vocabulary.
**Impact:** LOW (cosmetic; aids analysis)
**Effort:** Simple — append `_CHoCH` to `entry_type`.

### Suggestion 4: Add absolute-time staleness guard for CRT setups
**Why:** Per H-3 above. ICT setups are only valid within their originating killzone. A CRT setup whose C2 sweep is 8 hours old should not fire.
**Impact:** MEDIUM
**Effort:** Simple — add `CRT_MAX_SETUP_AGE_BARS` env knob defaulting to 48 5M bars (4h, ~one H4 cycle). Reject when `entry_bar - sweep_5m_idx > CRT_MAX_SETUP_AGE_BARS`.

### Suggestion 5: Per-source DR-location feature mask in OGD
**Why:** CRT always passes `dr_location="UNKNOWN"`. Including its floor contribution in the OGD gradient adds noise. The right move is either (a) compute DR on the H4 timeframe and use the resulting location, or (b) mask the feature out of CRT-source gradients entirely.
**Impact:** LOW–MEDIUM
**Effort:** Simple (mask) to Medium (H4 DR).

---

## 6. Final Score and Recommendation

**ICT Logic Integrity Score: 9.0 / 10** (cycle-7 baseline = 9.5; delta = −0.5)

Breakdown:
- Detection layer (`ict_engine.py` + `crt_engine.py` detection functions): **9.5/10** — unchanged from cumulative re-audit, byte-identical to verified state
- TP1/economics/Wyckoff helpers in `crt_engine.py`: **9.0/10** — well-designed, but TP1 modes deviate from pure ICT (H-2)
- Live integration in `crypto_alert.py`: **6.0/10** — silent failure (C-1), forming-bar inclusion (C-2), bias-slice non-parity (M-1)
- Backtest integration in `backtest.py`: **9.5/10** — closed-bar replay, correct slicing, parity-aligned

**Weighted average: 9.0/10** (live integration is the binding constraint right now).

**GO/NO-GO for live trading:** This question is currently moot because (a) ENABLE_5M_SWEEP=0 and (b) C-1 means CRT live also emits zero signals — the bot is effectively dormant. Operator's "paper soak in progress" is producing no paper trades to soak with.

Recommendations in priority order:
1. **STOP** treating the current state as a meaningful paper soak. Zero CRT signals are flowing.
2. **FIX C-1** (the `times`/`timestamps` key mismatch) — single-line patch + regression test that exercises the real fetcher schema.
3. **FIX C-2** (forming-bar exclusion in live CRT path) — pair with C-1 in the same patch.
4. **VERIFY** by running one production cycle after the fix and confirming `signals.db` accumulates `source='H4_CRT'` rows.
5. **THEN** the paper soak becomes meaningful and the remaining HIGH/MEDIUM/LOW findings can be addressed in subsequent cycles.

**Delta vs cycle-7 (9.5 → 9.0):** A single CRITICAL silent-failure introduced by today's Session 3 + Pro v1.1 live integration cycle. The detection layer itself remains at cycle-7 quality. The regression is in the live wiring only.

---

## 7. Files reviewed (absolute paths)

- `/home/tradeai/TradeAI/crt_engine.py`
- `/home/tradeai/TradeAI/ict_engine.py`
- `/home/tradeai/TradeAI/crypto_alert.py` (focused: 766-1017, 1711-1845, 2440-2510, 3770-3805)
- `/home/tradeai/TradeAI/backtest.py` (focused: 560-580, 1295-1545)
- `/home/tradeai/TradeAI/adaptive_engine.py` (function: extract_ict_feature_scores)
- `/home/tradeai/TradeAI/tests/test_crt_live_integration.py`
- `/home/tradeai/TradeAI/docs/exploration_runs/CRT_RESEARCH_2026_05_27.md`
- `/home/tradeai/TradeAI/.claude/CRT_STRATEGY_CONTEXT.md`
- `/home/tradeai/TradeAI/.claude/reports/ict-logic-validator/2026-05-27_crt_v1_cumulative_reaudit.md`
- `/home/tradeai/TradeAI/.claude/reports/ict-logic-validator/2026-05-27_crt_v1_option_s_reaudit.md`
- `/home/tradeai/TradeAI/.claude/reports/tradeai-audit/2026-05-26_cycle7.md`
- `/home/tradeai/TradeAI/docs/comprehensive/CROSS_REF.md`
- `/home/tradeai/TradeAI/data/signals.db` (read-only inspection — confirmed 0 H4_CRT rows in live)
- `/home/tradeai/TradeAI/logs/bot.log` (last ~50 cycles — no CRT activity)
