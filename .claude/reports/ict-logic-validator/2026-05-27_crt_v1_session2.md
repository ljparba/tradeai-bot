# CRT v1 (Session 2) — ICT Conformance Audit of Backtest Wiring

**Branch:** `experiment/crt-h4-signal-source` @ `3d47c77`
**Date:** 2026-05-27
**Scope:** `run_backtest_token_h4_crt()` and its integration into the main backtest loop. Detection-layer internals already audited in Session 1.
**Files reviewed:**
- `/home/tradeai/TradeAI/backtest.py:1254-1473, 3446-3457`
- `/home/tradeai/TradeAI/crt_engine.py:335-389` (sl/tp1 set points)
- `/home/tradeai/TradeAI/ict_engine.py:70, 746-810` (5M-sweep SL buffer + liquidity-TP comparator)

---

## 1. Executive Summary

Session 2 wires CRT signals into the backtest engine in a structurally clean way: the same outcome simulator (`check_outcome`), triple-barrier labeling, excursion metrics, and round-trip cost model are reused, and signals are tagged `source='H4_CRT'` for per-source attribution. The Session-1 detection layer is consumed verbatim, and the C-CRT-1 mitigation-key fix (timestamp-keyed `consumed` set) is preserved at `backtest.py:1294, 1332`.

However, the wiring **deliberately bypasses three institutional filters** that the spec doc §7 said would be reused from the 5M-sweep path: the session/killzone gate, the 4H bias gate (as Daily Bias proxy), and structural SL buffering. None of these are CRT-theory violations on their own (CRT is a self-contained Wyckoff setup), but the spec promised they would be applied, and they are not. Additionally, the SL is placed **exactly at the swept wick** instead of `wick × (1 ± ICT_SL_BUFFER_PCT)` — a non-trivial fidelity gap because real fills will almost certainly stop out on the very wick that defined the setup. The TP cascade switches from liquidity-based (5M-sweep) to R-multiples (CRT), which is a defensible v1 choice but is the single biggest ICT-fidelity downgrade in this file.

**No Session-1 fix is regressed.** Detection-layer internals are not touched; only consumption is added.

**Overall Session-2 ICT conformance: 74 / 100.** Recommendation: **ship as v1 experimental (default-OFF protects production), but document the four spec-vs-implementation gaps explicitly in the spec doc so Session 3 has a checklist.**

---

## 2. CRITICAL Findings

**None.** No ICT principle that the detection layer correctly enforced has been undone by the wiring. The wiring is an honest "v1 minimal viable consumption" and the default-OFF gate (`ENABLE_H4_CRT=0` at `backtest.py:1276`) means production is unaffected.

---

## 3. HIGH Findings

### H-CRT2-1 — SL placed on the raw wick, no `ICT_SL_BUFFER_PCT` applied
**File:** `/home/tradeai/TradeAI/backtest.py:1347` reading `setup["sl"]`; source at `/home/tradeai/TradeAI/crt_engine.py:344, 387` returns raw `c2_low` / `c2_high`.
**Issue:** The 5M-sweep path applies a 0.3% structural buffer beyond the swept wick via `compute_ict_trade_plan` (`ict_engine.py:757, 784`: `sl = sweep_wick * (1.0 ± ICT_SL_BUFFER_PCT)`). The CRT path uses the raw wick. In practice, CRT setups stop out **on the very wick that defines the setup** — which means any minor retest of the swept low/high (a normal post-MSS pullback) triggers SL. Real-fill simulation will systematically over-count CRT losses relative to the actual institutional setup.
**Fix:** apply the same buffer in `run_backtest_token_h4_crt`. Either (a) call `compute_ict_trade_plan(entry_price, direction, sweep_wick=setup["sweep_wick"], …)` and consume `plan["sl"]`, or (b) inline the buffer: `sl_price = setup["sl"] * (1.0 - ICT_SL_BUFFER_PCT)` for BUY, `* (1.0 + ...)` for SELL.
**Impact:** likely a 5-15pp WR penalty in backtest vs. what the same setups would achieve with the buffer — this is the most likely cause of the CRT path looking worse than the spec predicts.

### H-CRT2-2 — TP cascade uses fixed R-multiples instead of liquidity targets
**File:** `/home/tradeai/TradeAI/backtest.py:1349-1360`
**Issue:** TP1 is correctly set to the C1 opposite extreme (universal CRT rule, good). But TP2 = entry + 1.5R and TP3 = entry + 2.0R are fixed-R extensions, **bypassing** `compute_liquidity_targets` + `compute_ict_trade_plan` (which the 5M-sweep uses to align TPs to 1H swing levels, 4H swing levels, and DR-extreme liquidity pools). Per ICT/Wyckoff, after TP1 (the C1 opposite extreme — already a liquidity target), price typically gravitates to the **next** liquidity pool, not to a fixed R-multiple in empty space.
**Fix (Session 3):** call `compute_liquidity_targets` to build the `extra_liq` pool, then route through `compute_ict_trade_plan` with `sweep_wick=setup["sweep_wick"]`. Override TP1 = `setup["tp1"]` (C1 opposite extreme, CRT universal) but use the liquidity-routed TP2 and TP3. The TODO comment at line 1350-1351 already acknowledges this.
**Impact:** TP2/TP3 will hit less often than they would if anchored to real liquidity, but TP1 is the dominant outcome bucket in backtest — TP2/TP3 ICT-fidelity is a v2 win, not a v1 blocker.

### H-CRT2-3 — No session / killzone filter on CRT signals
**File:** `/home/tradeai/TradeAI/backtest.py:1254-1473` — no `config.liquid_hours` check.
**Issue:** The 5M-sweep path at `backtest.py:700` skips bars where `ts.hour not in config.liquid_hours`. The CRT scanner has no equivalent. The spec doc §7 explicitly said "Reuse existing NY AM / London / Asia gates" — implementation does not. Crypto is 24/7 but ICT teaches that institutional positioning happens in killzones; CRT setups that confirm during low-liquidity Asian deadzone hours are statistically lower-quality.
**Fix:** at line 1416 after `ts = ...`, add `if ts.hour not in ACTIVE_CONFIG.liquid_hours: continue`. One line.
**Impact:** likely 10-30% of raw CRT signals are in low-liquidity hours and skew WR downward. Cheap and high-value to add.

### H-CRT2-4 — No 4H bias gate applied (Daily Bias proxy)
**File:** `/home/tradeai/TradeAI/backtest.py:1424` (`"bias_4h": "NEUTRAL"`)
**Issue:** Spec doc §7 v1 said "Reuse existing 4H bias gate as Daily Bias proxy". Implementation tags every CRT signal with `bias_4h="NEUTRAL"` and does not call `detect_4h_bias` or apply the bias filter. CRT theory (Trading Wyckoff article) explicitly emphasizes Daily Bias as the **first** filter — taking SSL-CRT (bullish) against a bearish 4H bias is precisely the "counter-trend without confluence" trap CRT is supposed to avoid.
**Note:** the current production 5M-sweep config has `LIVE_BIAS_4H_GATE = "none"` (F-8 promoted; see CLAUDE.md §7), so the 5M-sweep path also doesn't enforce it. This makes Session 2's lack of bias filtering **consistent with production** in spirit, but the spec promised the gate would be **wired** (even if currently "none"), and tagging `bias_4h="NEUTRAL"` instead of the actual computed bias breaks downstream per-source bias analytics.
**Fix:** compute the actual `bias_4h` at signal time and tag it; let the gate decision remain config-driven.
**Impact:** medium — current config wouldn't filter anyway, but blocks Session 3 from gridding `LIVE_BIAS_4H_GATE` against CRT.

---

## 4. MEDIUM Findings

### M-CRT2-1 — Entry timing: next-bar open after MSS is OK but suboptimal vs. FVG retracement
**File:** `/home/tradeai/TradeAI/backtest.py:1340-1343`
**Issue:** `entry_bar = mss_bar_abs + 1; entry_price = c5m["opens"][entry_bar]` — this enters at the open of the next 5M bar after MSS confirmation. Per ICT, the canonical entry after MSS is **at the FVG retracement** (price returns to the FVG zone formed during the MSS impulse), not market-on-next-open. The 5M-sweep path itself uses this canonical FVG retracement entry via `iFVG_5M_used` and explicit retest logic. CRT skips this and enters market-open.
**Why this is MEDIUM not HIGH:** next-bar-open is a valid ICT entry (taught as the "aggressive" entry), it's just not the optimal one. For a v1 backtest it's a defensible simplification — but it will produce a worse cost basis on average and slightly inflate SL distance vs. FVG-retest entries.
**Fix (Session 3):** when `setup["confluence"]["type"] == "FVG"`, attempt FVG retracement entry within ENTRY_WINDOW bars; fall back to next-bar open only if no retracement happens.
**Impact:** likely 2-4pp WR penalty + ~10% worse R:R on TP1.

### M-CRT2-2 — `FORWARD_BARS = 288` (24h) reused from 5M-sweep; H4 CRT setups typically need longer
**File:** `/home/tradeai/TradeAI/backtest.py:1287, 1337, 1365`
**Issue:** H4 CRT setups originate on H4 timeframe and target the opposite C1 extreme — that can be 50-150 bps away on BTC, taking 1-3 days, not 24 hours. The 5M-sweep `FORWARD_BARS=288` was tuned for 5M-origin setups with closer TPs. Using 288 for CRT may over-count EXPIRED outcomes that would have been WINs given more time.
**Fix:** introduce a CRT-specific `H4_CRT_FORWARD_BARS = 576` (48h) or 864 (72h). Sensitivity: re-run the same trial pool with 288 vs 576 vs 864 — if EXPIRED rate is <10% at 288 then 288 is fine; if it's >25% then extend.
**Impact:** likely 3-8pp WR shift if EXPIRED is being miscategorized as non-win.

### M-CRT2-3 — No token-level circuit breaker
**File:** `/home/tradeai/TradeAI/backtest.py:1254-1473`
**Issue:** Spec doc / pattern in 5M-sweep path uses `CIRCUIT_BREAKER_LOOKBACK + CIRCUIT_BREAKER_MIN_WR` to pause a template if rolling WR < 55%. CRT path doesn't. Acceptable for v1 (no historical data), but should be documented in the spec as a known gap to revisit in Session 3 once n>=30 CRT signals exist per token.
**Fix:** add to spec doc §7 row "Circuit breaker" as "v1 OMITTED — wire in v2 once per-token sample size reaches CIRCUIT_BREAKER_LOOKBACK".

### M-CRT2-4 — `confidence=10` hardcoded
**File:** `/home/tradeai/TradeAI/backtest.py:1425`
**Issue:** Every CRT signal gets `confidence=10` with comment "CRT is high-confluence by construction". This is OK as a v1 simplification but loses information — an FVG+HIGH confluence is genuinely more confident than an OB-only confluence; a HIGH-quality MSS is more confident than a LOW. Downstream analytics can't differentiate signal quality.
**Fix:** compose confidence from `mss_quality` + `confluence.type` + `confluence.details.quality`. E.g. base=7, +1 for HIGH MSS, +1 for FVG confluence, +1 for HIGH FVG quality. Or simply pass through the confluence quality field.

### M-CRT2-5 — Adaptive OGD weights not consumed (intentional, mirrors 5M-sweep — but worth flagging)
**File:** docstring at `backtest.py:1273-1275`
**Issue:** docstring says "backtest uses DEFAULT_WEIGHTS for OGD scoring" — fine for parity with the 5M-sweep backtest path, but means CRT will not benefit from per-token adaptive weighting in either live or backtest until the spec defines a CRT-specific weight scheme. Document this as a known limit.

---

## 5. Per-Question Verdict (A-G)

| # | Question | Verdict | Severity | Notes |
|---|----------|---------|----------|-------|
| A | Entry = next-bar open vs FVG retest | **NOT IDEAL** | MEDIUM | M-CRT2-1. Valid ICT entry, just not optimal; FVG retest path defers to Session 3. |
| B | TP cascade fixed R vs liquidity | **DEGRADED FIDELITY** | HIGH | H-CRT2-2. TP1 (C1 extreme) is liquidity-correct; TP2/TP3 are not. |
| C | SL buffer (`ICT_SL_BUFFER_PCT`) | **MISSING** | HIGH | H-CRT2-1. Detection returns raw wick; scanner does NOT add buffer. Should add. |
| D | `FORWARD_BARS=288` for H4 setups | **POTENTIALLY TOO SHORT** | MEDIUM | M-CRT2-2. Needs sensitivity test; H4 CRT may need 48-72h. |
| E | Regime/bias tagging hardcoded | **SPEC GAP** | HIGH | H-CRT2-4. Spec promised bias gate; implementation tags NEUTRAL. Compute bias even if gate=none. |
| F | Session/killzone filter | **SPEC GAP** | HIGH | H-CRT2-3. Spec promised killzone reuse; implementation has none. One-line fix. |
| G | Token circuit breaker | **DELIBERATE v1 OMISSION** | LOW-MEDIUM | M-CRT2-3. Acceptable, document in spec. |

---

## 6. Session-1 Regression Check

Re-verified each Session-1 finding against the Session-2 wiring:

| Session-1 finding | Status in Session 2 |
|---|---|
| C-CRT-1 (mitigation key on timestamp, not idx) | **PRESERVED.** `backtest.py:1294` initializes `consumed: set`; `:1332` adds `setup["key"]` which is timestamp-keyed per the Session-1 fix. The scanner does not introduce a list-index-keyed shadow. |
| C-CRT-2 (MSS dual-path divergence) | **NOT REGRESSED.** Wiring consumes `setup["mss_bar_5m"]` produced by the detection layer; no duplicate MSS re-derivation in `backtest.py`. The fix that landed in Session 1 (using canonical `score_ict_mss` returning `mss_bar`) flows through cleanly. |
| H-CRT-1 (FVG confluence near swept extreme) | **NOT REGRESSED.** Detection-layer concern; wiring does not weaken it. |
| H-CRT-2 (OB displacement threshold) | **NOT REGRESSED.** Detection-layer concern; untouched. |
| H-CRT-3 (OB walk-back break on same-dir candle) | **NOT REGRESSED.** Detection-layer concern; untouched. |
| H-CRT-4 (`_approx_mss_bar` lookback) | **NOT REGRESSED.** Helper removed in Session 1 fix; wiring uses canonical path. |
| M-CRT-1 (dual-extreme C2 ambiguity) | **NOT REGRESSED.** Detection-layer concern; untouched. |
| M-CRT-2 (close-position option) | **NOT REGRESSED.** Detection-layer concern; untouched. |

**Conclusion: zero Session-1 regressions.** Session 2 is purely additive; it consumes Session 1's outputs without modifying or shadowing them.

---

## 7. Proactive Improvement Suggestions

**Suggestion 1:** Route CRT through `compute_ict_trade_plan` with `extra_liq` built from `compute_liquidity_targets`, then override `tp1` with the C1 opposite extreme (CRT universal) and apply `ICT_SL_BUFFER_PCT` automatically.
**Why:** unifies the 5M-sweep and CRT paths under one SL/TP discipline; gets ICT_SL_BUFFER_PCT, liquidity-routed TP2/TP3, MIN_SL_PCT, MAX_SL_PCT, and BEW gate for free; preserves CRT's TP1 = C1-opposite invariant.
**Impact:** HIGH **Effort:** Simple (one function call swap + override).

**Suggestion 2:** Add per-source attribution columns explicitly in `signals.db` (currently `source='H4_CRT'` is in the dict at line 1470; verify the DB write layer persists it — and that tracker.py groups by source).
**Why:** without per-source attribution the explorer's Optuna objective will pool 5M-sweep and CRT signals together; the high WR of the former will mask the (likely lower) WR of the latter early on.
**Impact:** HIGH **Effort:** Simple if column already exists, Medium if schema migration needed.

**Suggestion 3:** Add EQH/EQL detection (equal-highs / equal-lows) as a confluence option alongside FVG and OB. The Trading Wyckoff article explicitly calls these out as the **prime** SSL/BSL targets — they are the textbook "liquidity pool" CRT is sweeping. Currently `crt_engine._check_confluence` only accepts FVG or OB.
**Why:** the C2 sweep itself implicitly assumes a level was swept, but no check verifies that level was an EQH/EQL cluster vs. a one-off wick. EQH/EQL confirmation would tighten signal quality.
**Impact:** MEDIUM **Effort:** Medium.

**Suggestion 4:** Add OTE (Optimal Trade Entry, 61.8-79% Fib retracement of the MSS impulse) as a refinement on top of "next-bar open after MSS". This is the canonical ICT entry zone and would address M-CRT2-1 more rigorously than FVG-retest alone.
**Why:** pure ICT methodology. Pairs naturally with the existing PD-array (premium/discount) classifier.
**Impact:** MEDIUM **Effort:** Medium.

---

## 8. Cross-Domain Observations

**Observation:** Session 2 emits CRT signals with `wscore=0.0` and `matched_template_id="NONE"`. Adaptive learning's OGD weight update path keys off template_id and wscore. CRT signals will therefore be **invisible to the adaptive learner** — neither rewarding nor penalizing the OGD weights as they win/lose.
**Relevant Agent:** adaptive-learning-code-reviewer
**Reason:** confirm whether this is intentional isolation (likely yes — spec says CRT bypasses templates) or an oversight. If intentional, document in the OGD docstring so future maintainers don't try to "fix" it.

**Observation:** The CRT scanner returns signals tagged `source='H4_CRT'`, but I did not verify whether `tracker.py` / `tracker_html.py` / `print_report()` / `cpcv_summary` recognize this source for per-source filtering. If they don't, headline metrics will silently include CRT in the 5M-sweep pool.
**Relevant Agent:** live-backtest-consistency-checker (or tracker-frontend-audit)
**Reason:** verify per-source attribution flows end-to-end. The spec promised this; the wiring sets the field but downstream consumption is out of scope here.

**Observation:** `confidence=10` hardcoded on CRT signals will inflate any confidence-weighted aggregation downstream (e.g. portfolio-level sizing, template scoring).
**Relevant Agent:** risk-management-auditor
**Reason:** confirm no downstream code interprets confidence=10 as a position-sizing multiplier without bounds-checking.

---

**End of report.** Overall verdict: **74/100 — GO for Session 3 enhancement**, no Session-1 regressions, but address H-CRT2-1 (SL buffer) and H-CRT2-3 (session filter) before any honest WR comparison between CRT and 5M-sweep is published.
