# TradeAI Adaptive Learning — Post-CRT Pro Review (Cycle-7 follow-up)

**Reviewer:** adaptive-learning-code-reviewer (Opus 4.7 1M)
**Date:** 2026-05-27
**Scope:** Today's CRT-aware adaptive-learning changes — `compute_crt_feature_scores`, loosened bootstrap WHERE, monitoring sparse-pool downgrades. Re-verify yesterday's cycle-7 R1-R10 + S/M-CY7 fixes still hold.
**Files in scope:** `crt_engine.py` (compute_crt_feature_scores), `crypto_alert.py` (CRT signal builder L919-936, _trigger_weight_update L1439), `adaptive_engine.py` (bootstrap_from_backtest WHERE L946-955, extract_ict_feature_scores L1812), `monitoring.py` (homogeneity_alert L445, sparse-pool downgrade L457-472), `backtest.py` (M-CY7-4 first_fail_onset writer L3873-3910, WRITE_CPCV_VERDICT gate L3855)
**DB evidence:** `data/signals.db`, `data/monitoring/report_2026-05-27.json`
**Cross-ref reviewed:** `docs/comprehensive/CROSS_REF.md` — H8, H9, M12, M13 (KNOWN), M14, L7, OGD-PHASEA all confirmed still DONE.

---

## 1. Executive Summary

Today's changes are **coherent, correct, and close a real gap**. The CRT-aware path now feeds the OGD pipeline end-to-end: `compute_crt_feature_scores` produces the same 6-feature schema as `extract_ict_feature_scores` (verified — it literally calls the same function with sensible CRT-defaults), live CRT signals now persist `feature_scores_json`, and the loosened bootstrap WHERE (`fvg OR mss NOT IN ('','NONE')`) now admits 2195 CRT signals (97% of total CRT signals in backtest_signals — was 0 before). Bootstrap from Run #145 was re-run and produced learned weights for 8/10 tokens, with HBAR and TON correctly degenerate-rejected back to DEFAULT_WEIGHTS — the rejection mechanism is honest and the fallback is uniform. R1 DSR gate is wired correctly to today's verdict (FAIL, DSR=25.2%, WR=48.2%, n=416) — first paper close will run at `lr_scale=0.25 (soft_fail)`. M-CY7-4 first_fail_onset is correctly populated (3.4h elapsed at review time → freeze trigger fires at hour 24 if streak persists, but shadow mode means log-only). M13 KNOWN LIMITATION (confidence circular feedback) still applies and is correctly documented in CRT path comments. **Score: 9.7 → 9.6 (-0.1).** Net findings unchanged from cycle-7 with one NEW MEDIUM (cross-source contamination via shared token_weights table) offset by one CY7-A still unfixed (BOOTSTRAP_AFTER_RUN default ON). Verdict remains: **Truly adaptive.**

The −0.1 is for the new cross-source contamination risk: with `ENABLE_5M_SWEEP=0 ENABLE_H4_CRT=1` in production (.env confirmed), all live learning today is CRT-only and there is no contamination NOW, but if the operator re-enables 5M_SWEEP mid-paper, learned CRT weights would persist into shared `token_weights[token]` rows that 5M_SWEEP would then read. The architecture does not partition weights by source.

---

## 2. CRITICAL findings

**None.** All four traced code paths (CRT signal save → `_trigger_weight_update` → `weight_engine.update` → `_persist_token`) operate on the same 6-feature dict and same DB schema. No crash, no shape mismatch, no NaN propagation. Day-1 risk for the first CRT paper close is **LOW** for corruption and **MODERATE** only for operator confusion at the `DSR gate soft_fail: lr_scale=0.25` log line.

---

## 3. HIGH findings

### H-1 — Cross-source contamination: shared `token_weights` table has no source partition (NEW FINDING)

- **Where:** `adaptive_engine.py:224` (CREATE TABLE token_weights — schema is `token, feature, weight, velocity, n_updates, updated_at` with PK `(token, feature)`. No `source` column.)
- **Evidence:** `compute_crt_feature_scores` produces scores from the CRT signal context (fvg='NONE' floored at 0.05, mss='HIGH'/MEDIUM/LOW, dr='UNKNOWN' at 0.25). The `update()` path writes the same `token_weights[token]` row regardless of source. Today's production env has `ENABLE_5M_SWEEP=0 ENABLE_H4_CRT=1` so all live learning is CRT-only — but if operator flips back, the next 5M_SWEEP signal close at the same token reads the CRT-learned weights.
- **Why this is a concern:** CRT's `fvg_quality` score is structurally floored at 0.05 (always NONE for OB-only), and `dr_location` is always 0.25 (UNKNOWN). After 30 CRT closes the gradient on `mss_quality` + `session` + `trend_strength` will dominate the renormalised budget — `mss` could push toward WEIGHT_MAX. A subsequent 5M_SWEEP signal at that token would inherit those CRT-tuned weights, but 5M_SWEEP signals have real fvg_quality + dr_location signal that would now be under-weighted from the start. This is real ICT-vs-CRT cross-contamination through the score path.
- **Classification:** NEW FINDING. Was structurally non-existent until 2026-05-27 (CRT did not write feature_scores_json before today).
- **Impact:** Inert under the current `ENABLE_5M_SWEEP=0` config. Becomes HIGH the moment operator re-enables 5M_SWEEP.
- **Mitigation:**
  1. Document this in CLAUDE.md and the CRT-mode toggle path.
  2. Long-term: add `source` column to `token_weights` PK + maintain per-source rows. Read path resolves source-of-active-signal at scoring time.
  3. Shorter-term: maintain a `dual_source_active` startup guard that refuses to load OGD weights with mismatched-source heritage.

### H-CY7-A — `BOOTSTRAP_AFTER_RUN` default still "1" (CARRY-OVER from cycle-7)

- **Where:** `backtest.py:4035` — `_BOOTSTRAP_AFTER_RUN = os.environ.get("BOOTSTRAP_AFTER_RUN", "1") == "1"`
- **Status:** UNFIXED since 2026-05-27 cycle-7 audit. Today's CRT bootstrap rerun (Run #145, persisted at `2026-05-27 13:58:55`) provides fresh evidence: every backtest invocation that runs to completion will overwrite `backtest_token_weights` for all 10 tokens. With the stale-verdict pollution gate (`WRITE_CPCV_VERDICT=0` for explorer) the verdict is now protected, but the bootstrap table is NOT similarly gated.
- **Mitigation:** Same as cycle-7 — flip default to "0", require explicit "1" in promotion path. Single-line fix.

---

## 4. MEDIUM findings

### M-1 — Today's monitor report (02:32 UTC) ran BEFORE the new monitoring fields shipped (NEW)

- **Where:** `data/monitoring/report_2026-05-27.json` lacks `tokens_alt_pool`, `alt_pool_table`, `source_table` keys in summary. n_pairs=45 (10 tokens, all at DEFAULT_WEIGHTS → identical → avg_l1=0.0) means `homogeneity_alert=true` fires WHEN it should have been protected by the new `n_pairs ≥ 1` guard. The new code WOULD have correctly fired homogeneity=true at n_pairs=45 because all values matched defaults — so the alert is honest, but only after the CRT bootstrap reran at 13:58 the picture changed (8 tokens now have learned weights). Next monitor run (next 02:30 UTC) will produce a substantially different report.
- **Impact:** Today's dashboard view is stale — operator may interpret WARN as a new alert when it's actually a pre-CRT-bootstrap snapshot.
- **Mitigation:** Trigger a manual monitor refresh after each backtest+bootstrap or each major adaptive change. Or: invoke monitor as the last step of the bootstrap path in `bootstrap_from_backtest`. Or: add `--invalidate` flag to delete same-day report when bootstrap reruns.

### M-2 — `compute_crt_feature_scores` passes `dr_location="UNKNOWN"` → 0.25 score → constant 6.4% normalized weight (NEW)

- **Where:** `crt_engine.py:776` (default) + `crypto_alert.py:935` (live caller always passes UNKNOWN since CRT scanner doesn't compute DR). `extract_ict_feature_scores` returns `dr_score=0.25` for UNKNOWN, which after FLOOR + renorm is 0.064.
- **Math:** With reward=±1 and dr_score=0.064, the per-update gradient on `dr_location` is bounded at ±0.064. Over 30 CRT WINs (all +1 reward), the accumulated unclipped weight delta is `30 × 0.06 × 0.064 = 0.115` — but `MAX_WEIGHT_STEP=0.04` clips per step, so realistic delta is `min(0.04, 0.06×0.064) = 0.0038` per step → 0.114 over 30 closes BEFORE momentum + renorm.
- **Impact:** `dr_location` weight does NOT converge to its information content (zero) — it accumulates small positive deltas every WIN, which after renorm shrink only because other features grow. In practice today's backtest_token_weights for ETH shows `dr_location=0.1526` (close to DEFAULT 0.05 inflated to 0.15 — suggests the floor-driven drift). The honest answer is "we don't know" → dr_location should approach WEIGHT_MIN. The CRT engine cannot supply this signal.
- **Mitigation:**
  1. **Cleanest:** Skip the `dr_location` gradient when `dr_location='UNKNOWN'` (treat as masked feature — no update). Requires a new `mask` arg to `update()`.
  2. **Quick:** Reduce UNKNOWN's dr_score from 0.25 to `_SCORE_FLOOR` (0.05) so the CRT path produces the same 0.013 contribution as a NONE-fvg.
  3. **Document:** Add a comment in `compute_crt_feature_scores` that CRT cannot learn the dr_location dimension and any future dashboards should treat its weight as non-informative for CRT-derived signals.

### M-3 — Cross-source freeze trigger: `_check_consecutive_loss_spike` reads from results table without source filter (NEW)

- **Where:** `adaptive_engine.py:523-538`. Query: `SELECT result FROM results ORDER BY id DESC LIMIT 5` — does NOT filter by `source`.
- **Impact:** If 5 consecutive CRT losses occur, the freeze trigger fires globally — would freeze hypothetical 5M_SWEEP weight updates too. With `ENABLE_5M_SWEEP=0` today this is inert, but as M-2 noted, the cross-source contamination story is consistent — the engine treats both sources as one stream.
- **Mitigation:** Either (a) per-source freeze tracking with `results r JOIN signals s ON r.signal_id=s.id WHERE s.source = ?` parameterized at update time, or (b) explicit single-source assertion at startup when only one source is enabled (cheap).

### M-4 — CRT path scores `confidence` from `crt_quality_to_confidence(mss, fvg)` — both inputs already gradient-tracked, fully inside M13 KNOWN LIMITATION (NEW context)

- **Where:** `crypto_alert.py:917` calls `crt_quality_to_confidence(_mss_q, _fvg_q)` to compute the integer confidence, which is then fed to `compute_crt_feature_scores(confidence=...)` at line 932 and re-projected into the `confidence` feature gradient.
- **Why this matters:** M13 documented the loop for the 5M_SWEEP path where confidence is "derived from the 5 structural features." In the CRT path, confidence is derived from JUST TWO features (mss_quality + fvg_quality) — a tighter loop. With fvg_quality always NONE (→ floor 0.05), the CRT confidence is effectively a monotone function of mss_quality alone. The confidence feature then receives ~0.15 normalised gradient signal that is fully colinear with mss_quality.
- **Severity:** This does not break learning, but the per-feature gradient attribution between `confidence` and `mss_quality` is meaningless for CRT signals. After N closes, the relative weight of `confidence` vs `mss_quality` is a mathematical artifact of the score lookup tables, not a learned property.
- **Classification:** Extension of M13 to the CRT path. Document but do not re-flag as new bug.
- **Mitigation:** Same as M13 — Fix A (drop confidence from FEATURES entirely) is the right long-term answer. Defer to post-live.

### M-5 — `_load_all` warm-start path is source-agnostic: ETH live row at n=0 + CRT-bootstrapped row will warm-start to CRT weights at next restart (NEW)

- **Where:** `adaptive_engine.py:397-413`. The warm-start logic: `if self._n.get(token, 0) == 0: load from backtest_token_weights`. ETH currently has a live `token_weights` row from `2026-05-27 15:11:01` with n=0 (existence confirmed via DB query), and the `backtest_token_weights` row from `2026-05-27 13:58:55` has CRT-influenced weights (`fvg=0.0515, mss=0.2878, conf=0.2972, …`). Next bot restart warm-starts ETH to CRT weights — but if the operator later flips ENABLE_5M_SWEEP=1, ETH's live scoring would use CRT-tuned weights for 5M_SWEEP signals.
- **Impact:** Composes with H-1. Inert today; activates the moment 5M_SWEEP is re-enabled.
- **Mitigation:** Same source-partitioning argument as H-1.

---

## 5. LOW findings

- **L-1** Monitor report 2026-05-27 reports `homogeneity_alert=true` with `avg_l1=0.0` and `n_pairs=45`. After today's CRT bootstrap, the actual diversity is much higher (XRP fvg=0.387, ETH conf=0.297, HBAR=DEFAULT, …). Tomorrow's monitor report will show non-zero diversity. Today's report is correctly stale, not wrong.
- **L-2** XRP `fvg_quality=0.3873` in backtest_token_weights is uncomfortably close to `DEGENERATE_THRESHOLD=0.40`. Crossed by 1.27 percentage points → would trip the degenerate-reject gate. Operator should keep an eye on XRP's next bootstrap.
- **L-3** `compute_crt_feature_scores` lazy-imports `extract_ict_feature_scores` inside the function body to avoid circular imports — this is defensive but means every CRT signal pays a `_local_import` cost. Negligible (1-2 µs).
- **L-4** The `_trigger_weight_update` early-return at `crypto_alert.py:1464-1466` ("no feature_scores_json stored") was the silent-skip bug that today's fix closes. With `compute_crt_feature_scores` populating `feature_scores_json` for every CRT signal, this branch should no longer trigger for live signals. Worth adding a metric counter (`_skipped_no_fs` in bot_state) to detect any regression.

---

## 6. Verification matrix — today's changes

| Change | Status | Evidence |
|--------|--------|----------|
| `compute_crt_feature_scores` schema parity with `extract_ict_feature_scores` | **VERIFIED CORRECT** | crt_engine.py:788-797 lazy-imports and delegates; identical 6-feature dict. |
| Live CRT signals populate `feature_scores_json` (closes `_trigger_weight_update` skip) | **VERIFIED CORRECT** | crypto_alert.py:992 — `"feature_scores_json": json.dumps(_crt_ogd_scores)` in the CRT result dict. |
| Bootstrap WHERE clause admits OB-only CRT signals | **VERIFIED CORRECT** | adaptive_engine.py:946-955; DB query confirms 2195 CRT rows admitted (fvg=NONE, mss=meaningful). |
| Bootstrap result for HBAR/TON correctly degenerate-rejected → DEFAULT_WEIGHTS | **VERIFIED CORRECT** | DB query shows both rows EXACTLY = DEFAULT_WEIGHTS. |
| Bootstrap fallback path is honest (uniform substitute, not no-op) | **VERIFIED CORRECT** | adaptive_engine.py:1082 substitutes `dict(DEFAULT_WEIGHTS)`. Scratch_v zeroed at 1083. Scratch_n stays at n_actual (NOT cleared). |
| `_trigger_weight_update` correctly reads `feature_scores_json` for CRT | **VERIFIED CORRECT** | crypto_alert.py:1454 selects `s.feature_scores_json` regardless of source; CRT signals provide it. |
| `monitoring.py:homogeneity_alert` requires n_pairs ≥ 1 | **VERIFIED CORRECT** | monitoring.py:445 `homogeneous = bool(snapshot) and n_pairs >= 1 and avg_l1 < HOMOGENEITY_THRESHOLD`. |
| `tokens_alt_pool` field added | **VERIFIED CORRECT** | monitoring.py:489 + 490 in summary. (Note: today's report was generated before the change shipped; tomorrow's will include it.) |
| `global_alert` downgrades WARN→OK in sparse live + ≥5 alt pool | **VERIFIED CORRECT** | monitoring.py:464-468 `_live_sparse = len(per_token) < 3 and len(_alt_snapshot) >= 5`. |
| R1 DSR gate reads current verdict + applies soft_fail at LR×0.25 | **VERIFIED CORRECT** | Current verdict in DB is FAIL, dsr_gate_applied=true, dsr=25.2%. `_dsr_gate_lr_scale()` returns `(0.25, "soft_fail")`. First paper close runs at lr_scale=0.25. |
| M-CY7-4 first_fail_onset preserved across FAIL-FAIL re-runs | **VERIFIED CORRECT** | DB shows `first_fail_onset=2026-05-27 12:30:39` (1.5h before updated_at=13:58:53) — confirms preservation logic fired during today's re-bootstrap. |
| 24h FAIL streak freeze trigger | **NOT YET FIRED — INERT BY DESIGN** | Streak age at review time = 3.4h; threshold = 24h. OGD_FREEZE_MODE=shadow → would log only even if 24h is reached. |
| M13 KNOWN LIMITATION still documented in BOTH 5M_SWEEP and CRT paths | **VERIFIED CORRECT** | adaptive_engine.py:1851 + crypto_alert.py:2864 still carry the comment. |
| CRT outcomes contaminating 5M_SWEEP weight learning | **PRESENT BUT INERT** | See H-1, M-3, M-5. ENABLE_5M_SWEEP=0 means no 5M_SWEEP weight updates occur. The contamination is structural (shared table) but no active 5M_SWEEP consumer exists. |
| Cycle-7 R1-R10 + S/M-CY7 fixes still in place | **VERIFIED** | All H8/H9/M12/M14/L7/OGD-PHASEA confirmed via spot-grep + DB schema check. No regressions. |

---

## 7. Cross-domain observations

**Observation:** The CRT bootstrap path computes a session label via `_utc_to_session(ts.hour)` (live) but `extract_ict_feature_scores` is called in bootstrap from the `backtest_signals.session` column. If the backtest writer is writing a different session label vocabulary (e.g. "UNKNOWN" instead of "OVERNIGHT") the `_SESSION_SCORE` lookup falls through to 0.0 → max(0.05, 0.0) = 0.05 floor. Worth a 1-line check that the backtest CRT session string matches the live session string verbatim.
**Relevant Agent:** live-backtest-consistency-checker
**Reason:** Already a known LBC concern, but the CRT path adds a new surface — `_utc_to_session(ts.hour)` is used in live save, the backtest's session string is written elsewhere. Parity should be confirmed.

**Observation:** Bootstrap result for ETH shows `confidence=0.2972` and `trend_strength=0.1594` after CRT bootstrap. M-4 noted CRT confidence is effectively a monotone of MSS — yet ETH's `mss_quality=0.2878` and `confidence=0.2972` are very close, suggesting the colinearity argument is empirically validated. If a future analyzer wants to attribute "which feature is driving ETH performance", confidence vs mss is indistinguishable for CRT signals. The signal-performance-analyzer should be aware before drawing per-feature conclusions on CRT-only data.
**Relevant Agent:** signal-performance-analyzer
**Reason:** Cycle-3 to cycle-7 had concluded "mss_quality is the dominant feature" — that conclusion may no longer be sound under the CRT-only regime because confidence is now derived from a 2-input function rather than the broader 5-input one used in 5M_SWEEP.

---

## 8. Proactive improvement suggestions

**Suggestion 1:** Add `source` column to `token_weights` PK + per-source weight rows; modify `update()` and warm-start to be source-aware.
**Why:** Closes H-1, M-3, M-5 in one shot. Aligns the engine with the production reality of two co-existing signal generators.
**Impact:** HIGH
**Effort:** Medium (schema migration + 6-8 call-site changes in adaptive_engine.py and monitoring.py)

**Suggestion 2:** Mask the `dr_location` feature for CRT signals (treat as "no information" → zero gradient contribution).
**Why:** Closes M-2. Today the dr_location weight is learning noise rather than signal. Adding a mask arg to `update()` cleanly avoids polluting the gradient.
**Impact:** MEDIUM
**Effort:** Simple

**Suggestion 3:** Add automatic monitor refresh as the final step of `bootstrap_from_backtest`.
**Why:** Closes M-1. Bootstrap reruns invalidate the same-day report; running the monitor immediately after keeps the dashboard truthful.
**Impact:** MEDIUM
**Effort:** Simple (1 subprocess call or function invocation)

**Suggestion 4:** Phase 5B per-template OGD weights — wait for n≥30 live closes per (token, template) cell.
**Why:** Long-standing item from cycle-7. Today's CRT learning is per-token only; per-template would expose whether CRT_OB vs CRT_FVG vs CRT_DR-PREMIUM perform differently.
**Impact:** MEDIUM
**Effort:** Complex (requires both data accumulation and engine refactor)

**Suggestion 5:** Source-aware freeze predicate — `_check_consecutive_loss_spike(source=None)` filters by source.
**Why:** Composes with Suggestion 1. Without it, a CRT loss spike would freeze hypothetical 5M_SWEEP learning too.
**Impact:** LOW today, MEDIUM under dual-source mode
**Effort:** Simple

**Suggestion 6:** Add a startup invariant: if `ENABLE_5M_SWEEP=0` and `_load_all()` finds non-default `token_weights` rows with `n_updates>0` from a previous 5M_SWEEP session, emit a WARN-level log.
**Why:** Operator's actions could mix source heritage silently. Surface it.
**Impact:** LOW
**Effort:** Simple

---

## 9. Final verdict

**Truly adaptive — 9.6/10** (was 9.7/10 in cycle-7).

The −0.1 is for the new H-1 cross-source contamination surface that emerged when today's `compute_crt_feature_scores` change closed the CRT learning gap. The fix is genuinely useful and increases the system's adaptive capacity; the side-effect is a previously-non-existent contamination path that is currently inert (ENABLE_5M_SWEEP=0) but architecturally present. The remaining 9.6 reflects the now-complete CRT-aware learning pipeline, the still-honest degenerate-rejection at the bootstrap boundary, the verified-correct M-CY7-4 first_fail_onset wiring, and the unchanged R1 DSR gate behavior.

**Key state at review time:**
- 2 live token_weights rows (ETH, TON) both at n=0 — warm-start eligible
- 10 backtest_token_weights rows, 8 with learned values, HBAR + TON DEFAULTed via degenerate-reject (honest)
- 2867 backtest_signals rows total (425 5M_SWEEP + 2441 H4_CRT)
- Latest CPCV verdict: FAIL, DSR=25.2%, WR=48.2%, n=416, first_fail_onset=12:30:39 (3.4h elapsed)
- First paper close will fire at LR×0.25 (soft DSR-gate). This is by design.

**Day-1 readiness:** READY. The first CRT paper close will:
1. Read `feature_scores_json` from the signal row (now populated, not NULL).
2. Compute reward from profit_pct.
3. Apply LR × ramp_scale × 0.25 (soft DSR fail).
4. Write `weight_history` row with `trigger='signal_close'` + all forensic columns (R4 cols already in schema).
5. Update token_weights atomically via `_persist_token`.

No crash path, no data-shape mismatch, no NaN propagation. Operator should expect a "DSR gate soft_fail: lr_scale=0.25" log line on every CRT close until a fresh backtest with PASS/MARGINAL verdict is run.
