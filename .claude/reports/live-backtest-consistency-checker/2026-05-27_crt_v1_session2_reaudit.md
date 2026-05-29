# CRT v1 Session 2 — Re-audit after Options B + E (parity readiness)
**Date:** 2026-05-27
**Branch:** experiment/crt-h4-signal-source
**Commits audited:** 76fcafb (Option B), 2c82d7d (Option E)
**Scope:** Re-verify the 3 prior HIGH live-side parity gates remain implementable as designed AND surface any NEW parity divergence risks introduced by the Option B/E fixes.
**Verdict:** **DRIFT-RISK** — Options B+E are net-positive for backtest validity, but they introduce ONE new HIGH parity gap (4H bias windowing) that Session 3 must resolve explicitly, and TWO MEDIUM helper-location concerns that argue strongly for a small refactor BEFORE Session 3.

---

## 1. Executive Summary

Options B and E materially improved backtest realism (no more lookahead from H4-open-time anchor, no more hardcoded NEUTRAL bias, no more raw-wick SL, no more 24h truncation of H4 setups, no more confidence=10 monoculture). All three prior LBC findings remain valid and are now DOCUMENTED-FOR-S3 in spec § 16. None has been silently closed nor regressed.

However, the Option B fixes introduced a NEW parity gap not present in the original Session 2 audit:

- **NEW-H-1 — 4H bias windowing asymmetry**: Backtest CRT computes `bias_4h` from the same 12-bar H4 sub-window the detector saw (`backtest.py:1495`, intent: "honor the same data cutoff as the detector for live/BT parity"). Live's 5M-sweep path computes bias from the LAST 210 H4 closes (`crypto_alert.py:2188-2189`). If Session 3 follows the live convention (use full c4h cache), the bias verdict will differ from backtest CRT's 12-bar verdict on the same H4 candidate. If Session 3 follows the backtest CRT convention (slice to 12 bars), it deviates from how the 5M path computes bias — meaning live CRT and live 5M-sweep would disagree on bias for the same H4 candle in the same cycle, which is operationally confusing.

Plus, the new helpers (`_compute_crt_trade_economics`, `_crt_quality_to_confidence`) live in `backtest.py` with prefixed `_` private naming. Session 3 live cannot cleanly import private backtest functions without either (a) cross-module backwards-import dependency (bad), (b) re-implementation (drift risk), or (c) moving them to `crt_engine.py` now. The spec doc § 16 implementation order already says "Extract `compute_crt_trade_plan()` into crt_engine.py FIRST" — extending that refactor to also move the two Option E helpers is a small additional step that turns three potential divergences into structural parity.

No CRITICAL parity-killers. No regressions on prior findings. The Option B+E fixes are sound; they just shift the parity-by-construction work earlier in the Session 3 sequence than originally planned.

---

## 2. Prior LBC Findings — Status

### LBC-H-1 — `source` column on live signals table → DOCUMENTED-FOR-S3 (actionable)
- Verified live `signals` schema at `crypto_alert.py:201` (CREATE) and `crypto_alert.py:350` (ALTER loop) still has NO `source` column.
- Spec doc § 16 lines 580-588 prescribe exactly the right action: add `ALTER TABLE signals ADD COLUMN source TEXT DEFAULT '5M_SWEEP'` to the migration list and extend the INSERT.
- The live ALTER migration pattern at `crypto_alert.py:350` (`conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {typ}")`) is iterated over a tuple list — appending one entry is a 1-line change. Straightforward.
- INSERT extension touches one SQL statement and the dict construction at the call site. Straightforward.
- **Status: CLEAN — spec instruction is precise, mechanical, and matches the existing migration pattern.**

### LBC-H-2 — `consumed_sweeps` persistence to state_store → DOCUMENTED-FOR-S3 (actionable, with one note)
- Verified live StateStore defaults at `crypto_alert.py:3247-3253` still do NOT include `consumed_sweeps` or any CRT consumed set. Confirmed unchanged since prior audit.
- Spec § 16 prescription ("persist as list of (c1_time, c1_high, c1_low) tuples, reload at bot start, prune entries older than ~8h × H4_CRT_C2_LOOKBACK") is correct and implementable.
- **One scoping note**: The spec calls only for CRT consumed-set persistence. The EXISTING 5M-sweep `consumed_sweeps` set (`crypto_alert.py:154`) is also in-memory only and has the same restart-duplication risk for 5M signals. This is a pre-existing gap, NOT a CRT-v1 regression — but Session 3 may want to address both with one StateStore field (`consumed_crt_keys` + `consumed_sweeps`) for symmetry. Not strictly required for CRT parity.
- Pruning TTL: spec says `~8h × H4_CRT_C2_LOOKBACK`. With `H4_CRT_C2_LOOKBACK=10` that's 80h. Reasonable upper bound; a C2 candle that closed >80h ago cannot produce a valid MSS within `H4_CRT_MSS_HORIZON=30` 5M bars (2.5h). I would suggest spec say `4h × H4_CRT_C2_LOOKBACK + safety_pad` = 44h, since the H4 bar duration is 4h not 8h — but 80h is conservative and harmless (set stays small).
- **Status: CLEAN — implementable as specced. Suggest minor TTL refinement (4h × LOOKBACK, not 8h).**

### LBC-H-3 — Shared TP/SL helper → PARTIALLY-CLOSED, NEW-CONCERN on location
- Option E DID extract `_compute_crt_trade_economics()` at `backtest.py:237` — covers gross/net P&L %, RR, realized R, breakeven WR.
- However, this helper:
  1. Lives in `backtest.py` (not `crt_engine.py`)
  2. Is named with leading `_` (private convention)
  3. Takes an `outcome` parameter, which is BACKTEST-ONLY (live has no synthesized outcome at signal time — `realized_r` only fills when the tracker observes the lifecycle)
- The TP2/TP3 RR-cascade math (`tp2_price = entry_price ± CRT_TP2_RR * risk_dist`) is STILL inlined at `backtest.py:1523-1528`, not in any helper. Session 3 live MUST replicate this exact formula.
- Spec § 16 implementation order step 1 ("Extract `compute_crt_trade_plan()` into crt_engine.py FIRST") is the correct call. Session 3 should:
  - Extract the inlined TP2/TP3/SL-buffer/risk-distance math into `crt_engine.compute_crt_trade_plan(direction, entry, raw_wick_sl, tp1_target)` returning a dict (sl, tp1, tp2, tp3, risk_dist).
  - Split `_compute_crt_trade_economics` into TWO functions: a live-safe `compute_crt_signal_economics(direction, entry, sl, tp1, tp2, tp3, rt_cost)` returning the static % / RR fields, and a backtest-only `compute_crt_realized_r(outcome, net_tp1, net_tp2, net_tp3, net_sl)` that takes the outcome. Both live in `crt_engine.py`.
  - Backtest calls both; live calls only the first. No drift possible.
- **Status: PARTIALLY-CLOSED — Option E extracted the math but in the wrong location and with the wrong shape for live reuse. Session 3 must finish the job by moving + splitting.**

---

## 3. NEW Parity Divergence Risks Introduced by Option B/E Fixes

### NEW-H-1 — 4H bias windowing asymmetry (HIGH)
**Files:** `backtest.py:1495` (CRT: 12-bar sub-window) vs `crypto_alert.py:2188-2189` (5M sweep: full 210-bar slice)
**Issue:** Backtest CRT scanner passes `c4h_win["closes"]` (12 bars) to `get_ict_4h_bias`. Live 5M-sweep passes the full `closes_4h[:-1]` (up to last 210 bars enforced by the `min_bars` guard in `_lookup_4h_bias` for backtest's 5M path). `get_ict_4h_bias` likely uses a structural-bias window of N≥50 swing pivots — with only 12 bars, it may return NEUTRAL by default (insufficient data), while the live full-cache version returns BULLISH/BEARISH. So:
- Backtest CRT with `bias_4h_gate='loose'`: 12-bar bias is mostly NEUTRAL → always passes loose gate.
- Live CRT (if it mirrors live 5M-sweep style): 210-bar bias is more often directional → loose gate passes only when aligned.
- Different signal counts on the same H4 candle, same OHLCV input.

**Inspect `get_ict_4h_bias`**: at `ict_engine.py:409`. If the function has a `min_bars` guard internally, the 12-bar call may fall through to NEUTRAL always — making the new B-fix bias gate functionally inert in backtest while being binding in live. That would be a SILENT parity-killer.

**Fix for Session 3:** Standardize the bias-window contract. Recommended: live CRT computes bias from the same `closes_4h[:-1]` slice the 5M path uses (full cache, up to ~210 bars), and the backtest CRT scanner is updated to pass a wider H4 slice to `get_ict_4h_bias` (e.g. `c4h["closes"][:h4_end]` not `c4h_win["closes"]`). Then live and BT compute bias from semantically equivalent windows. **The comment at `backtest.py:1493` ("honor the same data cutoff as the detector for live/BT parity") is well-intentioned but achieves window-size mismatch, not parity.**

### NEW-M-1 — `_compute_crt_trade_economics` location + naming (MEDIUM)
**Files:** `backtest.py:237`
**Issue:** Private (`_` prefix) helper in `backtest.py`. Session 3 live integration cannot import without (a) creating a `from backtest import _compute_crt_trade_economics` line in `crypto_alert.py` — breaks the architectural rule that `backtest.py` depends on engine modules, not vice versa — or (b) duplicating the function — drift risk. The comment at `backtest.py:233-236` explicitly anticipates this: "Session 3 will extract a more general helper covering all three callers (live + 5M-bt + CRT-bt) when the live caller exists." Acknowledged tech debt.
**Fix for Session 3:** Move to `crt_engine.py`, drop `_` prefix, split outcome-dependent portion (see LBC-H-3 above).

### NEW-M-2 — `_crt_quality_to_confidence` same concern (MEDIUM)
**File:** `backtest.py:299-315`
**Issue:** Same architectural issue as NEW-M-1. Live CRT signal MUST use the identical quality→confidence mapping or confidence-stratified analytics will compare apples to oranges across live and backtest. Currently private + in `backtest.py`.
**Fix for Session 3:** Move to `crt_engine.py` alongside the other helpers. No logic changes required.

### Verified parity-by-construction (OK)

- **Session filter (`config.liquid_hours`)**: `backtest.py:1487` uses `config.liquid_hours`; live uses `LIVE_CONFIG.liquid_hours` at `crypto_alert.py:1789` and the 5M-sweep `evaluate_setup()` gate. Both read the same config field from the same source (config.py). Verified.
- **SL buffer (`ICT_SL_BUFFER_PCT`)**: `backtest.py:1514-1516` applies `wick * (1 ± ICT_SL_BUFFER_PCT)`. `ict_engine.py:757,784` (5M-sweep path used in live + BT) applies the identical formula. Parity by construction — both paths import the same constant from `ict_engine`.
- **`CRT_FORWARD_BARS=576`**: Used only in `backtest.py` for outcome scanning and data-sufficiency gates (`backtest.py:1416, 1474, 1478, 1536, 1547`). Live signal generation does NOT depend on it — outcomes resolve via the tracker watching real-time prices. Verified no live coupling.
- **5M-sweep `consumed_sweeps` parity**: Live at `crypto_alert.py:154,2163-2169` (timestamp-keyed). Backtest at `backtest.py:804` (`consumed_sweeps_abs` keyed on `(abs_bar_idx, level)`). Different key shapes but functionally equivalent within their respective domains — this is pre-existing and not a CRT-v1 change.
- **`source='H4_CRT'` string literal**: Backtest sets it at signal-dict construction. Live must use the IDENTICAL string. Recommendation L from prior audit (lift into `crt_engine.SOURCE_TAG = 'H4_CRT'`) remains the safest pattern. Not regressed; still pending Session 3.

---

## 4. Session 3 Design Recommendation — Helper Location

**Ranked best to worst:**

### (a) MOVE helpers to crt_engine.py NOW, before Session 3 — **STRONGLY RECOMMENDED**
**Pros:**
- Parity-by-construction: live and BT cannot diverge on TP cascade, economics math, confidence mapping, source tag, or any inlined CRT logic.
- Aligns with spec § 16 implementation order step 1 ("Extract `compute_crt_trade_plan()` into crt_engine.py FIRST"), just slightly expanded scope to cover all three Option E helpers + the still-inlined TP2/TP3 math + SL buffer.
- One small focused refactor PR (~150 lines moved, no behavior change). Easy to review, easy to verify via `python3 backtest.py` snapshot diff.
- Cleans up the comment at `backtest.py:233-236` which currently apologizes for the architectural shortcut.
- Reduces Session 3's surface area: instead of designing 3 helpers + 1 integration, Session 3 becomes "just call the helpers from `scan_token()` and add the migration".

**Cons:**
- Risk of breaking backtest behavior during the move (mitigatable by snapshot-diff test: run BT before/after, verify identical signal_hash output).
- Burns ~30 min of operator time on a "non-functional" refactor.

### (b) Have Session 3 IMPORT helpers from backtest.py — **NOT RECOMMENDED**
**Pros:**
- Zero refactor work before Session 3.

**Cons:**
- Creates `crypto_alert.py → backtest.py` import edge. Architecturally inverted (backtest is supposed to consume the live engine, not vice versa). Will break the CI hash-discipline check at `tools/check_backtest_redefinitions.py` if such a check exists for the inverse direction.
- Imports private `_`-prefixed functions across module boundaries — code-smell and a future-refactor hazard (any cleanup in `backtest.py` could silently break live).
- Cannot split the outcome-dependent portion cleanly; live would have to either pass a dummy outcome (lie) or call only part of the helper (re-implementation creep).

### (c) Have Session 3 DUPLICATE helpers in crypto_alert.py — **NOT RECOMMENDED**
**Pros:**
- Decouples live from backtest mechanics.

**Cons:**
- Pure drift risk. The whole point of the prior LBC audit was that any duplicated logic between live and BT WILL diverge over time. We have explicit historical evidence: the M24 `liquid_hours` parity failure was exactly this pattern.
- Any subsequent change to TP cascade, fee model, or confidence mapping requires touching two files — easy to forget one.
- Defeats the entire shared-module design pattern of `crt_engine.py`.

**Verdict:** Option (a). Recommend a small "Option F" PR (refactor-only, no behavior change) before Session 3 starts, with the following moves:
1. `compute_crt_trade_plan(direction, entry, raw_wick_sl, tp1_target)` → new in `crt_engine.py`. Encapsulates SL buffer + TP2/TP3 RR cascade. Backtest CRT scanner refactored to call it.
2. `compute_crt_signal_economics(direction, entry, sl, tp1, tp2, tp3, rt_cost)` → moved from `backtest.py:237`, drop `_`, drop `outcome` parameter, returns only static % / RR fields.
3. `compute_crt_realized_r(outcome, net_tp1, net_tp2, net_tp3, net_sl)` → new in `crt_engine.py` (or stays in `backtest.py` since it's BT-only — but putting in `crt_engine.py` keeps all CRT math co-located).
4. `quality_to_confidence(mss_quality, fvg_quality)` → moved from `backtest.py:299`, drop `_crt_` prefix (it's already in `crt_engine` namespace), drop `_`.
5. `SOURCE_TAG = "H4_CRT"` and `ENTRY_TYPE_TEMPLATE = "H4_CRT_{}"` → new module-level constants in `crt_engine.py`.
6. Verify behavior unchanged via BT snapshot diff (signal counts + WR identical before/after).

After this 1-hour refactor, Session 3 reduces to: ALTER TABLE migration + StateStore consumed-set + `scan_token()` integration + Telegram source tag. Each is a 5-20 line change. Total Session 3 risk drops materially.

### Additionally — resolve NEW-H-1 (4H bias windowing) in the same refactor
Add `compute_crt_4h_bias(closes_4h_full)` to `crt_engine.py` that wraps `get_ict_4h_bias` with the same min-bar guards the live 5M path uses (>=200 bars → real bias; else NEUTRAL). Backtest CRT scanner stops passing the 12-bar window and instead passes the full prefix `c4h["closes"][:h4_end]`. Live CRT calls the same helper with `closes_4h[:-1]` (same as live 5M-sweep). Bias computation becomes parity-by-construction across all three callers.

---

## Closing Assessment

Options B and E successfully closed the in-backtest realism issues (lookahead, hardcoded bias, raw wick SL, 24h truncation, confidence monoculture). The 3 prior LBC findings are correctly DOCUMENTED-FOR-S3 in spec § 16 and remain actionable as written. The NEW concerns are not regressions — they are consequences of pulling more logic out of "hardcoded" and into "computed", which exposed two architectural seams that need to be addressed before live integration:

1. The 4H bias windowing convention must be unified (NEW-H-1).
2. The Option E helpers need to move from `backtest.py` to `crt_engine.py` to be live-importable (NEW-M-1, NEW-M-2, LBC-H-3 unfinished portion).

A single ~1-hour "Option F" refactor PR before Session 3 — covering bias helper unification + relocating the three Option E helpers + extracting TP cascade — turns Session 3 from a 5-step integration with 5 chances to silently diverge into a 4-step integration where all parity is structural. Strong recommendation: do Option F first.

Files audited (absolute paths):
- `/home/tradeai/TradeAI/backtest.py` (lines 230-320, 1380-1620, 2188, 3325)
- `/home/tradeai/TradeAI/crypto_alert.py` (lines 154, 201-350, 2155-2210, 3245-3265)
- `/home/tradeai/TradeAI/crt_engine.py` (lines 34-50, 99, 162)
- `/home/tradeai/TradeAI/config.py` (lines 288-368)
- `/home/tradeai/TradeAI/ict_engine.py` (line 409 — `get_ict_4h_bias` signature)
- `/home/tradeai/TradeAI/docs/exploration_runs/CRT_RESEARCH_2026_05_27.md` (§ 16, lines 574-624)
- `/home/tradeai/TradeAI/.claude/reports/live-backtest-consistency-checker/2026-05-27_crt_v1_session2.md` (prior report)
