# CRT v1 (Session 1) — ICT/CRT Principle Conformance Audit

**Branch:** `experiment/crt-h4-signal-source` @ `8a6caea`
**Date:** 2026-05-27
**Scope:** Detection layer only — pre-integration with backtest.py / crypto_alert.py
**Files reviewed:**
- `/home/tradeai/TradeAI/crt_engine.py` (340 lines)
- `/home/tradeai/TradeAI/ict_engine.py:843-961` (OB + overlap functions)
- `/home/tradeai/TradeAI/tests/test_crt_engine.py` (12 tests)
- `/home/tradeai/TradeAI/docs/exploration_runs/CRT_RESEARCH_2026_05_27.md` (spec)

---

## 1. Executive Summary

The Session-1 CRT v1 implementation is **structurally faithful to the Wyckoff/flexible spec** and correctly composes the three required ingredients (H4 C1/C2 detection → 5M MSS confirmation → FVG-or-OB confluence). The universal CRT rules — SL below sweep wick, TP1 at opposite C1 extreme, one-shot mitigation per C1 — are all honored. Order-Block detection is a fresh, defensible implementation of "last opposite candle before strong displacement." However, two design-level issues meaningfully **degrade fidelity to the article's Wyckoff school**: (a) the mitigation key uses an unstable list index instead of a candle timestamp, which is a correctness bug the moment the cache is re-sliced (a near-certainty in live operation), and (b) the FVG/OB confluence overlap is checked against the **entire C1 range** rather than the **swept extreme zone**, which weakens the institutional-zone semantics the article calls for. The MSS helper used inside CRT is a hand-rolled re-derivation of the MSS bar that **silently uses `detect_ict_mss` (boolean) and then re-walks** — duplicated logic that can drift from `score_ict_mss` if the canonical MSS definition changes. Overall conformance is solid for an experimental v1 detection layer that is still gated default-OFF, but the mitigation-key bug and the FVG-window edge case should be fixed before any backtest run that relies on the mitigation set surviving across cycles.

**Overall CRT conformance score: 72 / 100.** Recommendation: **fix CRITICAL #1 (mitigation key) and HIGH #1 (FVG window/overlap semantics) before Session 2 integration; the rest can ride.**

---

## 2. CRITICAL Findings

### C-CRT-1 — Mitigation key uses unstable list index, not candle timestamp
**File:** `/home/tradeai/TradeAI/crt_engine.py:248`, `:293`, `:337`
**Issue:** `key = (c1_idx, round(c1_high, 6), round(c1_low, 6))`. `c1_idx` is the *position in the c4h array passed by the caller*, not a stable identifier. As soon as the caller refetches H4 candles and drops the oldest bar (which happens routinely in live operation as the rolling window slides forward), every previously-recorded `c1_idx` shifts by −1 and **the same C1 candle gets a new key**. Result: the "one-shot per zone" CRT invariant — explicitly called out as "100% consistent across sources" in the spec (§7 row "Mitigation") — is silently violated the next cycle.
**Fix (spec match):** key off the timestamp, not the index. Use `(c1_time, round(c1_high, 6), round(c1_low, 6))` where `c1_time = h4_times[c1_idx]`. This survives slice rotations and is what the operator's existing `consumed_sweeps_abs` pattern (§9 of spec) does. The spec pseudocode at line 305 actually says `tuple of (c1_idx, round(c1.high,6), round(c1.low,6))` which has the same bug — flag this back to the spec author.
**Spec divergence:** matches spec literally, but spec is wrong on this point. Operator-research intent ("zone is dead after first touch", spec §6 mitigation row) is violated.

### C-CRT-2 — `detect_ict_mss` called, then `_approx_mss_bar` walks the same window again with potentially different logic
**File:** `/home/tradeai/TradeAI/crt_engine.py:82-116, 257-270, 301-314`
**Issue:** Code first calls `detect_ict_mss(...)` (a wrapper that calls `score_ict_mss` with empty `opens/highs/lows` and returns `confirmed: bool`), then calls `_approx_mss_bar(...)` to *re-derive* the bar at which MSS confirmed. The two implementations must stay consistent, but they don't share code:
- `score_ict_mss` uses `recent_sh = max(... key=lambda p: p[0])` over swings in the ICT_SWEEP_LOOKBACK window before `sweep_bar` (ict_engine.py:233-236).
- `_approx_mss_bar` uses `for sh_idx, sh_lev in reversed(sh_5m): if sh_idx < sweep_5m_idx: target = sh_lev; break` — this picks the most-recent swing **with no lookback bound**.
If the most recent swing-high before the sweep is older than ICT_SWEEP_LOOKBACK bars, `score_ict_mss` says "no recent swing → NONE" while `_approx_mss_bar` happily targets it. The two will then disagree: `detect_ict_mss` returns False (no confirmation), but if it had returned True via a different path the `_approx_mss_bar` would point at a wrong target. The current code short-circuits before that becomes a correctness bug (the boolean gate fires first), but it is a structural footgun: change `ICT_SWEEP_LOOKBACK` or alter `score_ict_mss`, and the two paths silently diverge.
**Fix:** change `score_ict_mss` to also return `mss_bar` when confirmed (it already computes it at line 240-241 / 252-253), and have CRT consume that field directly. Eliminates `_approx_mss_bar` entirely.
**Impact:** correctness is preserved today because the boolean is checked first; this is a maintainability landmine, not a live bug — but I am flagging CRITICAL because **two implementations of the same ICT primitive is exactly the divergence pattern the operator's CLAUDE.md warns about ("live/BT parity by construction")**.

---

## 3. HIGH Findings

### H-CRT-1 — FVG confluence window misses the article-required institutional-zone constraint
**File:** `/home/tradeai/TradeAI/crt_engine.py:135-144`
**Issue:** The spec (§7 row "Confluence required") calls for "(FVG OR Order Block) overlap with C1 range OR MSS bar". The code checks: FVG direction matches AND `not (fvg.bottom > c1_high or fvg.top < c1_low)` — i.e. the FVG overlaps the **entire C1 H4 range**. For a typical H4 candle, that range can be 1-3% wide; a 5M FVG anywhere inside it qualifies. Per the Trading Wyckoff article, the OB/FVG confluence is meant to mark the **institutional zone where price was defended after the sweep** — that zone is *near the swept extreme* (the c2 wick end), not anywhere inside C1. A bullish CRT sweep at C1.low should require the FVG to overlap near C1.low / the c2 wick (the demand zone), not near C1.high.
**Fix (spec-faithful):** constrain the FVG overlap to a tighter zone around the swept extreme. E.g. for bullish CRT, require `fvg.bottom <= c1_low + 0.5 * (c1_high - c1_low)` (the lower half of C1, i.e. the discount half — which the operator already computes via `compute_dealing_range`). Mirror for bearish.
**Spec divergence:** spec text is ambiguous ("overlap with C1 range OR MSS bar"); article intent is clearly the swept-extreme zone.

### H-CRT-2 — Order-Block displacement threshold (0.5%) is too low for H4 crypto
**File:** `/home/tradeai/TradeAI/ict_engine.py:863`
**Issue:** `ICT_OB_MIN_DISPLACEMENT_PCT = 0.005` (0.5% of price). On H4 crypto, the median 4-hour ATR is ~1-2% — a 0.5% body is well within noise. The textbook ICT definition is "expansion candle" with body ≥ ~1.5× recent ATR, which on H4 BTC would be ~2.5-3%. At 0.5%, the function will frequently fire on candles that are not displacements at all.
**Fix:** raise to 0.015 (1.5%) for H4, or — better — replace with ATR-relative: `body >= 1.5 * atr14`. The existing `detect_ict_displacement` (ict_engine.py:172, with the H1-fixed ATR floor at 0.4× ATR) is a model for this.
**Impact:** today, with `ICT_FVG_MIN_QUALITY=HIGH` and 5M MSS already gating, downstream filters will catch most of the noise. But the OB function as written is not portable to other contexts (e.g. confluence on its own).

### H-CRT-3 — Order-Block "stop on same-direction candle" can miss the real OB
**File:** `/home/tradeai/TradeAI/ict_engine.py:944-948`
**Issue:** The walk-back loop returns the OB on first opposite-direction candle, and breaks on a same-direction candle. But ICT teaches: "go back to the start of the move" — meaning the OB is the **last** opposite candle, but if the sequence is bullish-disp ← bullish ← bullish ← bearish ← bearish ← …, the loop will:
- j = disp-1 (bullish) → break (line 947-948).
- Never reach the bearish OB.
This is the documented edge case in the prompt ("two bearish in a row before bullish move"). Reading lines 944-948: the `break` at 947 fires only when `(is_bullish_disp and j_bullish) or (is_bearish_disp and j_bearish)` — i.e. SAME direction. So `bullish disp ← bullish ← bearish` produces: j=disp-1 (bullish) → break, **never finds the bearish OB**. This is the opposite of ICT methodology.
**Fix:** remove the `break`. Walk all the way through `opposite_lookback` bars and return the first opposite candle found. Same-direction candles inside the displacement leg are normal (they are part of the impulse), not a reason to abort. The cap at `opposite_lookback` already bounds the search.
**Impact:** today this silently rejects valid OBs when the displacement is more than 1 candle. Given crypto H4 moves often span 2-3 expansion candles before the OB candle, this likely throws away most legitimate OBs. **Confluence will then fall back to FVG-only**, neutering the spec's "OB is PRIMARY confluence" intent.
**Test coverage:** T4 (line 76-86 of test_crt_engine.py) only validates the no-opposite-found case, not the multi-disp-bar case — gap in tests.

### H-CRT-4 — `_approx_mss_bar` ignores `ICT_SWEEP_LOOKBACK` bound on swing freshness
**File:** `/home/tradeai/TradeAI/crt_engine.py:94-100, 106-112`
Already noted under C-CRT-2 — repeating here under HIGH because if C-CRT-2 is fixed at the canonical-MSS level, this falls out automatically.

---

## 4. MEDIUM Findings

### M-CRT-1 — Bullish-first short-circuit on dual-extreme sweep
**File:** `/home/tradeai/TradeAI/crt_engine.py:253, 297`
**Issue:** If C2 wicks both below C1.low AND above C1.high (extreme-volatility candle), the code tests `if c2_low < c1_low` first and returns BUY without checking the bearish path. Per article, a candle that sweeps BOTH extremes is "invalid" (no clean directional bias). The prompt explicitly flagged this.
**Fix:** before either branch, check `c2_low < c1_low AND c2_high > c1_high` → continue (skip the C2, ambiguous).
**Severity rationale:** rare on H4 crypto, but mis-labels signals when it does happen.

### M-CRT-2 — Missing C2 close-position option / Wyckoff-strict path
**File:** `/home/tradeai/TradeAI/crt_engine.py:253-294`
**Issue:** Spec §7 v1 explicitly says "FLEXIBLE (Wyckoff)" — so this is *correct for v1*. But the spec also says v2 will A/B test strict-vs-flexible. The current code makes no allowance for a `H4_CRT_VALIDATION_SCHOOL=strict` env knob to swap behavior. Adding it now (one extra condition: `c2_close > c1_low` for bullish, `c2_close < c1_high` for bearish) costs ~5 lines and unblocks v2 work later.
**Spec divergence:** none for v1; documented gap for v2.

### M-CRT-3 — OB detected on H4 stream only, not 5M
**File:** `/home/tradeai/TradeAI/crt_engine.py:146-157`
**Issue:** Confluence falls back to OB on the H4 stream. Per ICT teaching, OB confluence is usually checked on the **entry timeframe** (here, 5M) because that's where the institutional defense is visible. H4 OBs are macro zones — useful as bias, less so as entry triggers. The spec is silent on the timeframe.
**Suggestion:** check 5M OB first (near the MSS bar), fall back to H4 OB only if no 5M OB. Or check both and accept either.
**Spec divergence:** ambiguous; ICT-textbook intent suggests 5M.

### M-CRT-4 — TP/SL not run through `compute_ict_trade_plan` (fees/slippage)
**File:** `/home/tradeai/TradeAI/crt_engine.py:291-292, 335-336`
**Issue:** `tp1 = c1_high` and `sl = c2_low` are raw price levels, no cost adjustment. Spec §7 says "Reuse `ict_engine.compute_ict_trade_plan()`" — this is acknowledged as Session 2 work, not Session 1, but worth keeping visible. As a *detection-layer* function this is acceptable; the integration layer must apply ROUND_TRIP_COST_PCT and TP1_GROSS_MIN_PCT before emitting the signal.
**Spec divergence:** explicitly deferred. Flag for Session 2 reviewer.

### M-CRT-5 — No TP2 / TP3 returned
**File:** `/home/tradeai/TradeAI/crt_engine.py:291, 335`
**Issue:** Single TP1 only. The 5M-sweep pipeline returns a cascade (TP1/TP2/TP3) used by the position-sizing and partial-take logic. CRT signals merged in via Session 2 will need TP2/TP3 — either derived in `compute_ict_trade_plan` from the CRT zone, or here in `detect_h4_crt`.
**Spec divergence:** §7 says reuse `compute_ict_trade_plan()` — acceptable.

### M-CRT-6 — Multi-timeframe time-unit assumption is unchecked
**File:** `/home/tradeai/TradeAI/crt_engine.py:70-79, 245, 254`
**Issue:** `_find_5m_bar_after(c5m_times, c2_time)` does `if t > target_time` — both sides must be in the same unit (UTC seconds, milliseconds, or minutes-since-epoch). The test fixture uses minutes (line 175 of test). The caller in backtest.py / crypto_alert.py uses UTC seconds. There is no type guard or assertion.
**Fix:** at function entry, assert `c5m_times[0]` and `h4_times[0]` are the same order of magnitude (e.g. both > 1e9 for unix-seconds), or accept a unit hint.
**Severity rationale:** silent wrong behavior if Session-2 wiring uses different units. Test fixture currently uses minutes-since-zero which would silently "work" but produce wrong bar offsets in production.

---

## 5. LOW Findings

### L-CRT-1 — "Walks most-recent first; first valid CRT setup wins" comment is correct but the first valid setup may not be the BEST setup
**File:** `/home/tradeai/TradeAI/crt_engine.py:232`
The most-recent CRT setup may have weaker confluence than an older un-mitigated setup. v1 acceptable; consider scoring all candidates and returning the best in v2.

### L-CRT-2 — `round(c1_high, 6)` precision sensitivity
**File:** `/home/tradeai/TradeAI/crt_engine.py:248`
Six-decimal rounding is fine for BTC/ETH (cents) but for low-priced tokens (POL at ~$0.40, TON at ~$5) this is overkill; floating-point representation could in theory produce different keys on identical reads after a JSON round-trip. Cosmetic.

### L-CRT-3 — Test T11 ("bearish CRT skeleton") is essentially a smoke test
**File:** `/home/tradeai/TradeAI/tests/test_crt_engine.py:258-276`
The test only verifies "no crash"; it accepts `None` as a valid result. Mirror-symmetric fixture should be built (the operator's note "production behavior validated via same code path" is fair, but a passing fixture would catch direction-confusion bugs).

### L-CRT-4 — Test T10 self-skips when confluence missing
**File:** `/home/tradeai/TradeAI/tests/test_crt_engine.py:244-249`
A unit test that "soft-skips" when the synthetic fixture doesn't produce the expected outcome is a flag that the fixture isn't tight enough. The 11/12 passing rate noted in the prompt is actually this skip. Recommend tightening the fixture so this becomes a hard pass.

### L-CRT-5 — Documentation mismatch with c1h
**File:** `/home/tradeai/TradeAI/crt_engine.py:163, 173`
Function signature accepts `c4h, c5m` only; spec §9 pseudocode mentions a `c1h` parameter. Spec says "currently unused" so dropping it is fine — just update the spec doc to match the implementation when convenient.

---

## 6. Per-Section ICT Conformance Matrix

| # | Section | Verdict | Notes |
|---|---------|---------|-------|
| 1 | Order Block detection | **PARTIAL** | Bullish/bearish branches correct; displacement threshold too low for H4 crypto (H-CRT-2); same-direction break bug in opposite-walk loop (H-CRT-3) |
| 2 | CRT H4 detection (C1/C2 logic) | **PASS** | Walk direction, C1=c2_idx-1 anchoring, bullish/bearish conditions all correct. Dual-extreme edge case unhandled (M-CRT-1) |
| 3 | Wyckoff/flexible LTF MSS | **PARTIAL** | Uses `detect_ict_mss` correctly, but `_approx_mss_bar` duplicates logic with subtle lookback divergence (C-CRT-2). Article *does* authorize LTF MSS, so principle is right; implementation is fragile |
| 4 | (FVG OR OB) Confluence | **PARTIAL** | Direction matching correct; overlap window too wide vs article intent (H-CRT-1); OB confluence weakened by H-CRT-3; H4-only OB check questionable (M-CRT-3) |
| 5 | One-shot mitigation | **FAIL** | Logic intent correct, but mitigation key based on unstable list index (C-CRT-1). The spec doc shares this bug |
| 6 | SL / TP per CRT theory | **PASS (detection-layer)** | SL = sweep wick, TP1 = opposite extreme — universal CRT. TP2/TP3 + cost adjustment correctly deferred to Session 2 integration (M-CRT-4, M-CRT-5) |
| 7 | Multi-timeframe alignment | **PASS-with-caveat** | Logic correct; unit-of-time assumption unguarded (M-CRT-6). Test fixture uses minutes; real callers will use seconds — needs caller-side verification |

---

## 7. Comparison Against Trading Wyckoff Article Specifics

| Article requirement | Spec v1 decision | Code conformance |
|---|---|---|
| Wyckoff/flexible validation school | Adopted (§7) | YES — `detect_ict_mss` used as LTF MSS confirmation per article (crt_engine.py:257-264) |
| C1 = parent, C2 = manipulation, C3 = confirmation | Adopted (§3) | YES — c1_idx = c2_idx - 1; C3 substituted by LTF MSS per flexible school |
| SL below sweep wick | Universal rule (§5) | YES — `sl = c2_low` (bullish) / `c2_high` (bearish) |
| TP1 = opposite extreme of C1 | Universal rule (§5) | YES — `tp1 = c1_high` (bullish) / `c1_low` (bearish) |
| One-shot mitigation per C1 zone | Universal rule (§5, §7) | NO — keyed on unstable list index, violates "zone is dead after first touch" across cache rotations (C-CRT-1) |
| OB is PRIMARY confluence (FVG secondary) | Adopted (§7 v1) | PARTIAL — code checks FVG first, OB second (crt_engine.py:135 vs 146). Article would prefer OB-first ordering. Also H-CRT-3 weakens the OB path |
| OB/FVG overlap with the **swept extreme zone** | Implicit in article | PARTIAL — code overlaps with **entire C1 range** (H-CRT-1), which is more permissive than article intent |
| "Strong" displacement | "Strong" qualitatively | WEAK — 0.5% is below H4 ATR-noise floor (H-CRT-2) |
| Daily Bias filter | 4H bias gate as proxy (§7) | DEFERRED — detection-layer doesn't enforce; correctly Session-2 integration concern |
| Killzone bias | Reuse existing gates (§7) | DEFERRED — detection-layer doesn't enforce; correct |
| Article-aggressive entry (raw C2 wick break) | REJECTED | YES — code requires MSS, not raw wick |
| Article-conservative entry (full H4 C3 close, ~4 hrs) | REJECTED | YES — code waits only `H4_CRT_MSS_HORIZON` (30 × 5M = 2.5 hrs max) |
| Wyckoff phase context (Phase C/D filter) | Deferred to v2 (§7) | DEFERRED — correct |
| `H4_CRT_DISABLED_TOKENS` env blacklist | Required (§8) | YES — implemented (crt_engine.py:59-63, 204-205) |
| `ENABLE_H4_CRT=0` default OFF | Required (§7) | YES — implemented (crt_engine.py:58, 202-203) |

---

## Prior-Art Classification Summary

| Finding | Cross-Ref Status | Note |
|---|---|---|
| C-CRT-1 mitigation key | NEW FINDING | Not in CROSS_REF (CRT is new module) |
| C-CRT-2 dual MSS implementations | NEW FINDING | Tangentially related to H2 (FALSE ALARM in CROSS_REF) — that one was about off-by-one in score_ict_mss itself; this is about reimplementation drift |
| H-CRT-1 FVG overlap window | NEW FINDING | M4 (KNOWN STRUCTURAL: FVG mitigation full-fill rule) is independent; this is about overlap region, not mitigation rule |
| H-CRT-2 OB displacement threshold | NEW FINDING | Related conceptually to H1 (DONE — ATR floor on displacement); should apply same ATR-relative pattern here |
| H-CRT-3 OB same-direction break | NEW FINDING | Specific to the new `detect_ict_order_block` function |
| H-CRT-4 → folded into C-CRT-2 | — | |
| M-CRT-* | NEW FINDING | All specific to the CRT module |

**Verification of items in scope from prior CROSS_REF that touch this module:**
- H1 (ATR minimum for displacement) — VERIFIED FIXED in `detect_ict_displacement` (ict_engine.py:189). NOT applied to new `detect_ict_order_block` — flagged as H-CRT-2.
- H2 (MSS sequence guard) — VERIFIED FIXED in `score_ict_mss` (ict_engine.py:231-253). New CRT code reuses it correctly via `detect_ict_mss` wrapper.
- M1 (MSS lookback constant) — VERIFIED FIXED (ict_engine.py:234, 246 use `ICT_SWEEP_LOOKBACK`). CRT's `_approx_mss_bar` does NOT respect this — see C-CRT-2.

---

## Cross-Domain Observations

**Observation 1:** The Session-2 integration will need to thread `consumed_sweeps_abs` (existing pattern, ref H4-DONE in CROSS_REF) into the CRT loop. If C-CRT-1 (unstable mitigation key) is not fixed first, the Session-2 reviewer should hard-block integration.
**Relevant Agent:** `live-backtest-consistency-checker`
**Reason:** live (long-running cache rotation) will diverge from backtest (static array) on the same setup. Live will re-fire mitigated CRT signals; backtest won't.

**Observation 2:** `detect_ict_order_block` (new in ict_engine.py:867) is exposed at module level and could be picked up by the 5M-sweep pipeline as a confluence input. If it is, H-CRT-2 (0.5% threshold) and H-CRT-3 (same-direction break) become 5M-pipeline bugs too, not just CRT bugs.
**Relevant Agent:** `ict-logic-validator` (re-run on the 5M pipeline next cycle).
**Reason:** A new public function in the ICT primitive layer should not silently be available to other consumers without an audit pass.

**Observation 3:** The spec § 7 says CRT signals enter the DSR pool as an additional trial (§10). The signal-source tag work in Session 2 must coordinate with the explorer's `dsr_proxy_used` flag and the honest-cross-config std refresh (CROSS_REF DSR pipeline). CRT trials should NOT enter the DSR pool until they have honest CPCV runs of their own.
**Relevant Agent:** `validation-methodology-auditor`
**Reason:** Premature DSR pool inclusion of an experimental signal source can deflate the cross-config std and inflate the headline DSR.

---

## Proactive Improvement Suggestions

**Suggestion 1:** Add `H4_CRT_VALIDATION_SCHOOL` env knob now (strict | flexible) even though v1 is flexible-only — unblocks v2 A/B test with no code refactor later.
**Why:** Spec §7 v2 explicitly calls for this. Plumbing the toggle now costs ~5 lines and 1 test; doing it under v2 pressure means rewriting v1's main loop.
**Impact:** MEDIUM **Effort:** Simple

**Suggestion 2:** Score CRT setups rather than first-match. Walk all candidates in the C2_LOOKBACK window, score each by (MSS quality + FVG quality + OB present + bias alignment), return the best.
**Why:** "First valid wins" is arbitrary; in volatile H4 markets multiple un-mitigated C1 ranges can coexist. Article author teaches "take the cleanest setup, not the first."
**Impact:** MEDIUM **Effort:** Medium

**Suggestion 3:** Add an EQH/EQL liquidity-pool boost on H4 — if C2 sweeps a level that has multiple H4 swing-highs at near-equal price (a BSL pool), the setup quality increases. The codebase already has `find_eqh_eql_clusters` (ict_engine.py:98) for 5M — reuse on H4.
**Why:** Article and ICT teaching both agree that sweeps of EQH/EQL pools are higher-quality than sweeps of isolated swings.
**Impact:** MEDIUM **Effort:** Simple

**Suggestion 4:** Compute and surface `R:R` in the returned signal dict. Currently caller has to derive it from `tp1, sl, entry`. Adding it here keeps the detection-layer contract complete.
**Why:** ICT teaching: every setup carries an explicit R:R; sub-2R setups should be flagged/filtered. Aligns with `ICT_MIN_RR_GATE=1.5` (locked anti-pattern at ≥2.0).
**Impact:** LOW **Effort:** Simple

**Suggestion 5:** Persist `consumed` set to bot_state (operator open-question #3 in spec §15 — "Default: YES"). Spec already plans this; do it as part of Session 2.
**Why:** Without persistence, every restart resets mitigation memory — every C1 zone gets a second life. Violates the universal CRT rule.
**Impact:** HIGH (when wired to live) **Effort:** Simple — reuse `state_store.py` atomic JSON

**Suggestion 6:** Add explicit OTE (Optimal Trade Entry) check — for bullish CRT, entry should land in the 0.618-0.79 Fibonacci retracement of the c2_low → mss_bar_5m move. ICT teaches OTE as the institutional re-accumulation zone after MSS.
**Why:** Adds a measurable quality filter that the 5M-sweep pipeline doesn't currently apply. Cheap to compute, high-information.
**Impact:** MEDIUM **Effort:** Simple

**Suggestion 7:** Tag CRT signals with the CHoCH-vs-BOS distinction on the 5M MSS. CHoCH (Change of Character) = first MSS against the prior 5M trend (high-quality reversal). BOS (Break of Structure) = continuation MSS in the trend direction. Currently the code treats both identically.
**Why:** Pure ICT methodology weights CHoCH higher than BOS for reversal setups. CRT is, by definition, a reversal setup — so CHoCH should be required, BOS should be filtered.
**Impact:** HIGH **Effort:** Medium

---

## Honesty Notes

- I did NOT run the test suite; I read the code only.
- I did NOT verify the `c5m_times` / `h4_times` unit convention in the actual callers (backtest.py / crypto_alert.py) since the prompt scoped this to detection-layer only.
- I did NOT verify the `find_ict_swings` / `score_ict_fvg` end-to-end interaction on the synthetic fixture in T10 — accepted the operator's "11/12 passing, T10 self-skips" framing as given.
- C-CRT-2 (dual MSS implementations) is a structural-debt finding, not a live correctness bug under the current code path. I rated it CRITICAL because of the operator's strong stated preference for live/BT parity by construction; another reviewer could reasonably rate it HIGH.
- The OB detection same-direction-break bug (H-CRT-3) was identified by trace-reading lines 922-948; I did not write a unit test to confirm. The text I quoted from the file is exact.

---

## Final Verdict

- **Overall ICT/CRT conformance: 72/100** (solid v1 detection scaffolding; two correctness issues and one weak default keep it out of the 80s).
- **Recommendation for Session 2 integration:** **CONDITIONAL GO** — fix C-CRT-1 (mitigation key → timestamp) and H-CRT-3 (OB same-direction break) before merging into backtest.py / crypto_alert.py. Both are < 1 hour of work. The rest can ship and be tuned via the validation pipeline (§10 of spec).
- The spec doc itself (§9 pseudocode line 305) contains the same mitigation-key bug — recommend updating the spec at the same time the code is fixed, so the documented architecture matches the corrected implementation.
