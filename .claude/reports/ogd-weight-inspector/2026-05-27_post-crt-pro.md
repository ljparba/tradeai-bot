# OGD Weight Inspector — Post-CRT-Shipping Audit (2026-05-27)

**Inspector:** ogd-weight-inspector (Opus 4.7 1M)
**Date:** 2026-05-27 (post-shipping cycle, CRT-only PAPER mode)
**Files in scope:** `adaptive_engine.py`, `monitoring.py`, `crypto_alert.py`, `backtest.py`, `crt_engine.py`, `data/signals.db`
**Cross-ref baseline:** Cycle-7 OGD Weight Quality = **9.6/10**
**Reference context:** `.claude/CRT_STRATEGY_CONTEXT.md` (2026-05-27)

---

## 1. Executive Summary — Score: **9.7/10** (+0.1 vs cycle-7)

The CRT shipping cycle closed the adaptive-learning gap exactly as designed. Bootstrap from Run #145 admitted **416 signals across 10 tokens** (vs ~70 pre-WHERE-clause-fix) and the degenerate-reject guard correctly substituted DEFAULT_WEIGHTS for the **2 tokens** (HBAR, TON) whose CRT-OB-dominated empirical distribution produced a >0.40 concentration. The remaining 8 tokens carry legitimately learned, sub-degenerate weights. Cross-token homogeneity is healthy (avg L1 = 0.368 on bootstrap pool — well above 0.05 floor). Monitoring is pre-paper-state aware: `global_alert=OK` despite individual token WARN flags, `homogeneity_alert=false`, exit-on-crit returns 0. CPCV verdict in `bot_state` is FAIL with a valid `first_fail_onset` timestamp, so when the first paper close fires the R1 DSR gate will scale LR to 0.25× as designed. The only stale element is TON's live `token_weights` row from 2026-05-25 — purely cosmetic since the warm-start path reads from `backtest_token_weights` on cold start.

The +0.1 lift over cycle-7 reflects: (a) successful CRT-to-OGD bridge via `compute_crt_feature_scores`, (b) bootstrap admit count grew 6× (70 → 416), (c) degenerate-reject substitution worked first try on HBAR+TON, (d) `homogeneity_alert` and `tokens_alt_pool` correctly suppress pre-paper false-positives.

---

## 2. Verification Checklist (operator's 5 specific items)

| # | Assertion | Verified | Evidence |
|---|---|---|---|
| 1 | HBAR + TON bootstrap rows match DEFAULT_WEIGHTS after degenerate-reject | **PASS** | All 12 rows exact: fvg=0.25, mss=0.20, conf=0.20, session=0.15, trend=0.15, dr=0.05 |
| 2 | All other 8 tokens have feature weights ≤ DEGENERATE_THRESHOLD (0.40) | **PASS** | Max weight across pool = XRP fvg_quality=0.3873 (below threshold by 1.3pp) |
| 3 | `latest_cpcv_verdict` = FAIL with `first_fail_onset` populated | **PASS** | verdict=FAIL, wr_mean=48.20%, dsr=0.252, n_signals=416, first_fail_onset=2026-05-27 12:30:39, dsr_gate_applied=true |
| 4 | `token_weights` live table has 0 OGD-driven updates (n_updates) | **PASS** | All 12 live rows (ETH+TON) carry n_updates=0; ETH row reflects bootstrap-shadow write at 15:11:01; TON row stale from 2026-05-25 (pre-CRT era) |
| 5 | `monitoring.py --text` shows `homogeneity_alert=false` and `global_alert=OK` | **PASS** | Live-source: global=OK, tokens=2, degen=0, low_H=0, pinned=2, stale=0, homog_alert=False; exit code = 0 |

All 5 specific verifications passed. No surprises.

---

## 3. Bootstrap Pool State (`backtest_token_weights`, Run #145)

| Token | n_bootstrap | Max feature (weight) | Entropy | Floor-pinned features | Status |
|-------|------------:|----------------------|--------:|------------------------|---------|
| AVAX  | 69 | mss_quality=0.256 | 1.746 | — | OK |
| ETH   | 51 | confidence=0.297  | 1.604 | fvg_quality, session | WARN (CRT-OB legitimate) |
| TON   | 49 | fvg_quality=0.250 | 1.709 | dr_location | DEFAULT (degen-rejected) |
| XRP   | 47 | fvg_quality=0.387 | 1.581 | mss_quality, dr_location | WARN (concentrated but legal) |
| LINK  | 42 | confidence=0.241  | 1.710 | session | WARN |
| HBAR  | 40 | fvg_quality=0.250 | 1.709 | dr_location | DEFAULT (degen-rejected) |
| ADA   | 39 | confidence=0.282  | 1.701 | — | OK |
| BNB   | 30 | mss_quality=0.251 | 1.738 | — | OK |
| POL   | 30 | mss_quality=0.254 | 1.725 | — | OK |
| BTC   | 19 | mss_quality=0.259 | 1.728 | — | OK |

**Total admitted:** 416 signals (matches context). **DEGENERATE_THRESHOLD breaches: 0**. **Mean entropy: 1.696** (uniform = ln(6) = 1.792, so pool is at 94.6% of max entropy — very healthy distribution).

**Floor-pin analysis:**
- ETH `fvg_quality=0.0516`, `session=0.0516` — these are the CRT-OB-mode legitimate slow-learners described in CRT_STRATEGY_CONTEXT.md §6. OB-only signals contribute fvg_score=floor=0.05 → gradient is small but nonzero. The pinning here is *correct behavior under CRT-OB-heavy data*, not a Run-46-style collapse.
- LINK `session=0.0538`, XRP `mss_quality=0.06` + `dr_location=0.0616`, HBAR/TON `dr_location=0.05` — same pattern. `dr_location` floor is structural (CRT does not compute dealing-range → score floor every signal).
- FLOOR_PIN_CRIT_COUNT=4: no token reaches 4 floor pins, so no CRIT trips. Sane.

---

## 4. Live Pool State (`token_weights`)

Only 2 tokens have rows:
- **ETH** (updated 2026-05-27 15:11:01) — mirrors bootstrap row exactly (shadow-write from `_persist_token` during prior live activity; n_updates=0)
- **TON** (updated 2026-05-25 10:48:39) — pure DEFAULT_WEIGHTS, stale 2.2 days but operationally harmless (the warm-start in `_load_all` reads bootstrap pool for tokens lacking live OGD updates)

The 8 missing tokens (ADA, AVAX, BNB, BTC, HBAR, LINK, POL, XRP) have no live row at all. This is **correct** for pre-paper state — on first close, `_persist_token` will INSERT a new row carrying the bootstrap-derived weight plus the OGD delta.

---

## 5. Constants Sync (CI-asserted)

| Constant | `adaptive_engine.py` | `monitoring.py` | Sync |
|---|---|---|---|
| DEGENERATE_THRESHOLD | 0.40 (L56) | 0.40 (L59) | ✓ |
| WEIGHT_MIN | 0.05 (L42) | 0.05 (L60) | ✓ |
| WEIGHT_MAX | 0.50 (L43) | 0.50 (L61) | ✓ |
| FEATURES | 6 features (L152) | 6 features (L62-63) | ✓ |

All four constants properly mirrored. `tests/test_monitoring.py:41` enforces this in CI.

---

## 6. Threshold Calibration (`monitoring.py` alerts)

| Alert | Threshold | Today's reading | Calibration verdict |
|---|---|---|---|
| LOW_ENTROPY | < 1.55 | min=1.581 (XRP) | OK — XRP just above; tight but appropriate |
| HOMOGENEITY | avg_L1 < 0.05 | avg_L1=0.368 (bootstrap), 0.594 (live) | OK — pool is heterogeneous |
| STALE_DAYS | > 14 d | max=2.21 (TON live) | OK |
| ENTROPY_DRIFT_ALERT | -0.30 | d_old=0.03-0.08 (post-bootstrap) | OK — no drift |
| ENTROPY_DRIFT_CRIT | -0.60 | (same) | OK |
| FLOOR_PIN_CRIT_COUNT | ≥ 4 | max=2 (ETH, XRP) | OK |

The tightening from 0.45 → 0.40 (Fix #36) catches XRP-class concentration without false-flagging it. Today's bootstrap state has zero false positives and zero false negatives.

---

## 7. Cross-Ref Prior-Art Classification

| Item | Classification | Status |
|------|---------------|--------|
| **H3** (degenerate weight check on bootstrap output) | VERIFIED FIXED | `_check_degenerate()` fired on HBAR + TON today; substitution worked |
| **H6** (cross-run contamination) | VERIFIED FIXED | Backtest scoring still uses AE_DEFAULT_WEIGHTS |
| **H8** (OGD bootstrap gate ≥10 closed signals) | VERIFIED FIXED | Two-path gate at adaptive_engine.py:751-784 intact (WARMUP_FLOOR=3 → OGD_MIN_SAMPLES=10 ramp) |
| **H9** (decay rate) | VERIFIED FIXED | Decay still calibrated; M-I seeds `_last_update_time` after bootstrap (no silent decay) |
| **M12** (PARTIAL_TP1/TP2 reward handling) | VERIFIED FIXED | Reward table populated; OGD-PHASEA closed via `_n_effective` |
| **M13** (confidence circular feedback) | KNOWN STRUCTURAL | Docstring intact; not re-flagged |
| **M14** (SELL-bias guard) | VERIFIED FIXED | Soft-threshold alert at 3× default; degenerate-reject catches HBAR/TON today |
| **L7** (health_check post-bootstrap) | VERIFIED FIXED | `_check_degenerate()` runs inline (intentionally not health_check, which reads live table) |
| **OGD-DEGEN** (0.45→0.40) | VERIFIED FIXED | All 3 mirror sites at 0.40 |
| **OGD-MON-SCOPE** (monitor blind to bootstrap pool) | VERIFIED FIXED | `--source bootstrap` flag working; revealed full 10-token view today |
| **M-D/E/F/I/J** (cycle-4) | VERIFIED FIXED | All intact (M-I: bootstrap _last_update_time seeding fired correctly today for all 8 non-thinned tokens) |

No regressions. No new HIGH/CRITICAL items in this domain.

---

## 8. NEW FINDINGS (post-CRT)

### F-CRT-1 — Bootstrap shadow-write to live token_weights (informational)
- **Where:** ETH live `token_weights` row at 2026-05-27 15:11:01 mirrors the bootstrap pool exactly
- **Cause:** `_persist_token` writes both bootstrap-time and live-update-time rows; ETH had a pre-existing live row that got refreshed via the bootstrap-after snapshot path
- **Severity:** LOW (informational only — no semantic effect, since `_load_all` uses bootstrap pool as warm-start; the ETH live row just happens to be a stale mirror)
- **Action:** None required. After first ETH paper close, the live row will diverge from bootstrap as expected.

### F-CRT-2 — TON live row stale 2.2 days (cosmetic)
- **Where:** TON `token_weights` updated_at=2026-05-25 (pre-CRT era)
- **Cause:** TON's previous degenerate-reject left a stale DEFAULT_WEIGHTS row; current cycle correctly re-substituted DEFAULT_WEIGHTS in the bootstrap pool but did not overwrite the live row (no signals closed in between)
- **Severity:** LOW (cosmetic — values match DEFAULT_WEIGHTS, so behaviorally identical)
- **Action:** None required. STALE_DAYS_THRESHOLD=14 so no alert; will refresh on first TON close.

### F-CRT-3 — ETH/LINK/XRP entropy floor proximity under CRT-OB data
- **Where:** ETH H=1.604, XRP H=1.581 (LOW_ENTROPY threshold=1.55, ln(6)=1.792)
- **Cause:** Under CRT-OB-dominated data (≈90% of CRT signals are OB-only per context), `fvg_quality` and `dr_location` features receive only the floor gradient (0.05 score) on most updates → those weights asymptote to WEIGHT_MIN, compressing the distribution
- **Severity:** LOW-MEDIUM — this is *legitimate empirical behavior*, not a bug. But if more CRT-OB signals accumulate in bootstrap, more tokens will drift toward H<1.55 and start triggering LOW_ENTROPY alerts that are *expected* under this regime
- **Action:** Consider raising LOW_ENTROPY_THRESHOLD from 1.55 → 1.45 *if* CRT-OB-heavy posture persists into paper accumulation. Re-assess after first 30 paper closes. **Do NOT change preemptively** — current calibration is correct for blended scanner regime.

---

## 9. Proactive Improvement Suggestions

### Suggestion A — Persist `_n_effective` to DB (carry-over from cycle-7 H-CY7-B)
- **Why:** PARTIAL_TP1/TP2 closes contribute 0.5 reward magnitude. With raw n=4 PARTIALs you have n_eff=2.0 worth of gradient signal. After restart, `_n_effective` snaps to 0.0 while raw n recovers from DB → operational diagnostic becomes a liar
- **Impact:** MEDIUM
- **Effort:** Simple (add `n_effective REAL DEFAULT 0.0` column + populate in `_persist_token`)
- **Status:** Already documented by adaptive-learning-code-reviewer cycle-7; carry-over

### Suggestion B — Per-source bootstrap pool isolation
- **Why:** Currently `backtest_token_weights` blends 5M_SWEEP and CRT signals into one weight vector. Today's CRT-only Run #145 gives a clean per-scanner snapshot. Once operator re-enables 5M_SWEEP (post-paper), the next bootstrap will blend → tokens may receive a Frankenstein weight that fits neither scanner well. Future per-source weight tables would let live runtime pick the right vector based on signal.source
- **Impact:** HIGH (necessary before dual-scanner LIVE)
- **Effort:** Medium (add `source` column to `backtest_token_weights`; update warm-start lookup; conditional `_persist_token`)
- **Note:** Phase B-level architectural change. Defer until 5M_SWEEP re-enabled.

### Suggestion C — Adaptive LOW_ENTROPY threshold under detected CRT-OB regime
- **Why:** Under CRT-OB-heavy data, mean entropy will be structurally lower (FVG floor-pinning is inevitable). A fixed 1.55 threshold will start crying wolf as paper closes accumulate. Make the threshold a function of the per-token OB-fraction (computable from `entry_type` regex on closed signals)
- **Impact:** MEDIUM
- **Effort:** Medium (requires running average of OB-fraction per token in bot_state; threshold becomes `1.55 - 0.10 * ob_fraction`)
- **Note:** Phase 5B-level; defer until ≥30 closed paper signals available

### Suggestion D — Gradient clipping at the per-feature level
- **Why:** `MAX_WEIGHT_STEP=0.04` caps total velocity magnitude but individual features can still receive disproportionate gradient under volatile market periods. A per-feature `max(grad) <= 0.02` would prevent any single update from pushing a single feature ≥4% in one step
- **Impact:** LOW (current MOMENTUM=0.85 + LR ramp already dampens this; defense-in-depth)
- **Effort:** Simple (one-line clamp before velocity update at L784 / L1030)

### Suggestion E — Feature importance audit dashboard panel
- **Why:** After ~30 paper closes, run a `mutual_info_regression(feature_scores, profit_pct)` per token. If FVG quality has near-zero MI under CRT-OB mode, we have empirical justification to *drop* fvg_quality from CRT's feature set entirely (rather than pin it at floor forever)
- **Impact:** HIGH (informs Phase 5B feature pruning)
- **Effort:** Medium (sklearn dependency + ~50 LOC panel)

---

## 10. Cross-Domain Observations

**Observation 1:** Run #145 OGD bootstrap used `cpcv_summary` writing path with `WRITE_CPCV_VERDICT=1` (default). If today's bootstrap was invoked from within an `autonomous_explorer` trial, the trial would have overwritten `latest_cpcv_verdict` for the live bot — though this didn't happen (verdict is correctly stamped at 13:58:53 matching bootstrap, with `first_fail_onset=12:30:39` indicating onset preserved across multiple FAIL backtests today).
- **Relevant Agent:** `backtest-explorer-audit`
- **Reason:** Confirm explorer trial subprocesses still default `WRITE_CPCV_VERDICT=0` per the recent stale-verdict pollution fix (commit 2f3b772). If explorer trials are accidentally writing verdicts during their CRT-tuned search-space runs, the live bot's `OGD_DSR_GATE` decisions could be made on the explorer's noisy per-trial verdict instead of the canonical backtest verdict.

**Observation 2:** ETH bootstrap weights show `fvg_quality=0.0516, session=0.0516` while ETH live `token_weights` shows IDENTICAL values (with n_updates=0). This implies `_load_all` or `_persist_token` shadow-wrote bootstrap state into live table. The expected behavior is bootstrap pool stays in `backtest_token_weights` only and only `_trigger_weight_update` (on paper close) populates `token_weights`. Need to confirm this is the M-I `_last_update_time` seeder OR genuinely a shadow-write path.
- **Relevant Agent:** `adaptive-learning-code-reviewer`
- **Reason:** Verify whether the ETH live row at 2026-05-27 15:11:01 came from a legitimate path (pre-existing live row from earlier paper era refreshed by warm-start) or an unintended bootstrap-to-live shadow write. If unintended, it could mask the boundary between "bootstrap pool" and "live OGD pool".

**Observation 3:** Bootstrap admit count went from ~70 → 416 (6×) after the WHERE-clause loosening at adaptive_engine.py:946-955. The OB-only CRT rows now contribute, but they bring `fvg_quality=NONE → score floor 0.05` baked into 90% of the empirical sample. This means the bootstrap pool is now mathematically biased toward floor-pinning the FVG feature for all CRT-active tokens. Long-term, this will reshape OGD's signal mix in ways that may not match the *intent* of CRT (where FVG is not a feature, but a confluence type). Worth flagging that "OGD's 6-feature schema does not perfectly fit CRT's signal model."
- **Relevant Agent:** `adaptive-learning-code-reviewer` + `signal-performance-analyzer`
- **Reason:** A future Phase 5B-level refactor should consider scanner-specific feature schemas (CRT uses {mss, session, confidence, trend, wyckoff_phase, ob_quality}; 5M_SWEEP uses the current 6). Currently we're shoehorning CRT into the 5M schema with floor-pinning as the workaround. This is a Phase 5B architectural decision, not a today-fix.

---

## 11. Final Verdict

**OGD adaptive learning is functioning correctly post-CRT shipping.** The 6× admit-count expansion + degenerate-reject substitution + monitor-aware pre-paper state all worked as designed. No CRITICAL or HIGH issues. Three LOW/MEDIUM new findings, all expected behaviors under CRT-OB-heavy data; not regressions. **Score 9.7/10** (+0.1 vs cycle-7), reflecting the clean execution of today's CRT bridge work and the fact that the system correctly distinguishes "pre-paper waiting" from "degenerate state."

The system is **ready for first CRT paper close**. When it fires, the R1 DSR gate will scale LR by 0.25× (verdict=FAIL today), the R9 freeze predicate will continue in shadow mode (POL `weight_volatility_spike` trigger from previous era still logged but not enforcing), and the next bootstrap (if WRITE_CPCV_VERDICT=1 and run_id≠explorer) will refresh `latest_cpcv_verdict` with the up-to-date FAIL onset.

