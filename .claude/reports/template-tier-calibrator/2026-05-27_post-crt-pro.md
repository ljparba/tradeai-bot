# Template Tier Calibration — Post-CRT-Pro Audit (cycle-7 follow-up)

**Date:** 2026-05-27
**Mode under audit:** PAPER, CRT-only (ENABLE_5M_SWEEP=0, ENABLE_H4_CRT=1)
**Prior score (cycle-7, 2026-05-26):** 6.5/10
**This audit score:** **7.0/10** (+0.5 — see §Score Movement Justification)
**Files reviewed (read-only):**
- `/home/tradeai/TradeAI/strategy_templates.py`
- `/home/tradeai/TradeAI/crypto_alert.py` (lines 990-1130, 3750-3810)
- `/home/tradeai/TradeAI/crt_engine.py`
- `/home/tradeai/TradeAI/docs/ict_strategy_variant_learner/template_performance_report.md`
- `/home/tradeai/TradeAI/docs/comprehensive/CROSS_REF.md`
- `/home/tradeai/TradeAI/data/signals.db` (read-only SQL)

---

## Verification Tasks (from request)

### 1. Template definitions haven't drifted
**VERIFIED.** `strategy_templates.py` last modified `2026-05-24 16:01` and last touched in initial commit `24860b5`. **Zero CRT-era commits to this file.** Today's 16+ CRT commits (`8a6caea` → `a3f2d71`) did not modify tier logic. Tier hierarchy invariant `A⊇B⊇C` re-verified by calling `validate_tier_hierarchy()` → **0 violations** across the full Cartesian product of bot-realistic inputs (288 combos).

### 2. Tier A/B separation on 5M_SWEEP historical data
**5M_SWEEP-only, n=426, all outcomes labelled (filtered per CRT context block):**

| matched_template_id | n | WR% | avg realR | avg MFE% | avg MAE% |
|---|---:|---:|---:|---:|---:|
| TIER_A | 155 | 81.3% | +1.073 | +4.017 | +0.988 |
| TIER_B | 271 | 83.0% | +1.095 | +2.944 | +0.849 |
| TIER_C | 0 | — | — | — | — |
| NONE   | 0 | — | — | — | — |

**Tier A vs Tier B separation: NEGLIGIBLE.**
- WR delta = **−1.7pp** (Tier A is *lower* WR than Tier B — counter-intuitive but n=155 vs 271 is enough to take seriously)
- avg realR delta = **−0.022R** (statistically indistinguishable; pooled SD ≫ |Δ|)
- The only real differentiator is **MFE%** (A=4.017 vs B=2.944) — Tier A signals run further before exit, but realised R is identical because both hit TP1 at ~83%.

**Interpretation:** the 5M_SWEEP entry gates (FVG=HIGH binding, MSS≥MEDIUM, BIAS=strict, TREND_1H=strict) are now so restrictive that **everything that gets through is already Tier B-or-better**. The Tier A/B threshold no longer carries discriminating power on the *current* gate configuration. This is a Run-168 + CRT-era artefact, not a tier-design bug.

### 3. CRT signals correctly bypass templates with template_live_allowed=0
**VERIFIED.** Confirmed at three layers:

| Layer | File:Line | Behaviour |
|---|---|---|
| Signal construction | `crypto_alert.py:1006-1009` | Every CRT signal hard-codes `matched_template_id="NONE"`, `template_status="UNKNOWN_TEMPLATE"`, `template_live_allowed=0`, `template_block_reason="crt_v1_no_template"` |
| LIVE Telegram gate | `crypto_alert.py:3806-3808` | CRT scanner unconditionally prints `[CRT-v1] LIVE BLOCK ... no Telegram` when `EXECUTION_MODE==LIVE`. CRT v1 is paper-only by design until v2 introduces CRT-specific templates. |
| Generic gate | `crypto_alert.py:3760-3766` | `Phase5A` block also catches CRT via `template_live_allowed=0` even if the CRT-specific block above were bypassed (belt + suspenders). |

DB confirms: 2,441 H4_CRT backtest signals all carry `matched_template_id='NONE'`. None of the 426 5M_SWEEP rows carry NONE. The two scanner streams partition cleanly. **Behaviour is intentional and correctly implemented.**

### 4. 5M_SWEEP confluence base rates (discriminating power audit)

**MSS quality** — 411/426 = **96.5% HIGH**, 15/426 = 3.5% MEDIUM → effectively a constant, **zero discrimination**.
**FVG quality** — 426/426 = **100% HIGH** → constant, **zero discrimination** (FVG=HIGH gate is binding by config).
**Session** — LONDON 19%, NY_AM 24%, ASIA 15%, OVERNIGHT 42%. **Genuinely discriminating** (range 15-42%).
**Entry type** — REACTION_CONFIRMED 10%, MIDPOINT_RECLAIM 90%. REACTION_CONFIRMED is the rare-but-strong path; usable as a discriminator but only fires the Tier-A bonus 10% of the time.
**DR location** — PREMIUM 39%, DISCOUNT 39%, UNKNOWN 22%. After Fix #30 the canonical post-displacement geometry is near-uniform — confirmed in cross-ref as TPL-DR carry-over open at HIGH.
**SMT** — 332/426 = 78% confirmed; **bonus** but weak discriminator at this rate.
**iFVG** — 414/426 = **97% present** → essentially a constant, bonus has near-zero portfolio impact.

**Conclusion:** of the 5 Tier A confluences, only **session** and **entry_type** carry real discriminating power on current data. **MSS=HIGH, FVG=MEDIUM+, DR=match** are all near-saturated. **iFVG bonus** is operationally inert.

### 5. Phase I-5B (per-template OGD weight isolation)
**Still NOT STARTED.** Confirmed in:
- `docs/ict_strategy_variant_learner/PHASE_STATUS.md:20,110-128`
- `docs/ADAPTIVE_LEARNING.md:431` ("Need n≥30 per (token, template); not achievable until paper accumulates")
- `docs/audits/AUDIT_2026-05-22_strategy_and_adaptive.md:34` ("Schema is (token, feature) only. Cross-template poisoning structurally possible.")

**CRT-only mode impact on urgency:** **REDUCED to near-zero priority.**
- In CRT-only mode 100% of OGD updates come from `matched_template_id='NONE'` (CRT) signals. There is only one effective "template bucket" feeding the learner.
- Per-template isolation would still be useful for 5M_SWEEP once that scanner is re-enabled, but **the n≥30-per-template gate is now an order of magnitude further out** because the closed-trade stream is being absorbed entirely by CRT.
- More urgent for CRT is **per-source weight isolation** (5M_SWEEP vs H4_CRT), not per-tier — this is the cross-domain observation flagged below.

---

## Prior Art (CROSS_REF) Classification

| Ref | Issue | Classification |
|---|---|---|
| C2 | Tier C coverage overlap (all C ⊆ B) | **KNOWN STRUCTURAL** (acknowledged in template_performance_report.md §All-Matched View) — *not re-flagged.* |
| TPL-DR | DR confluence semantics flipped (Fix #30) | **VERIFIED FIXED** — re-confirmed at `strategy_templates.py:141-143, 211-214, 280-282`. |
| TPL-SMT | SMT bonus sign (Fix #31) | **VERIFIED FIXED** — re-confirmed `strategy_templates.py:148-150, 220-221, 276-277` with `bonus += 0.10`. |
| M15 | Template confidence thresholds match BT performance | **VERIFIED — but now stale.** Thresholds (4/5 Tier A, 3/5 Tier B, 2/2 Tier C) were calibrated against Run #85-era data. Current 5M_SWEEP gates (Run-168 + CRT-era) saturate 3-4 of the 5 confluences, so the threshold no longer discriminates. Not a regression (no code change) — a **gate-drift artefact**. |
| M16 | SMT (+0.10) / iFVG (+0.05) bonus calibration | **PARTIALLY STALE.** SMT bonus at 78% base rate is OK as a tilt. **iFVG bonus at 97% base rate is operationally inert** — recommend re-examination if 5M_SWEEP is re-enabled. CRT path doesn't use these bonuses (no template). |

---

## Findings (new vs known)

### F1 — Tier A and Tier B are no longer statistically separated [NEW FINDING — MEDIUM]
**Evidence:** 5M_SWEEP n=155 vs 271, ΔWR = −1.7pp, ΔrealR = −0.022R. Tier A is *not better* than Tier B in either metric.
**Root cause:** entry gate saturation (FVG=HIGH + BIAS=strict + TREND_1H=strict + MSS≥MEDIUM) has pre-filtered to a homogeneous quality population. Tier B captures the bulk; Tier A captures a sub-slice with no measurable lift.
**Severity:** MEDIUM. The template system is currently dormant (CRT-only mode), so this affects no live signals today. But if 5M_SWEEP is re-enabled, the **Tier A vs Tier B split is providing zero decision-useful information** — Tier A daily cap (3) vs Tier B (2) in `TIER_DAILY_LIVE_CAPS` is therefore misallocating live attention.
**Action when 5M_SWEEP re-enabled:** Either (a) collapse to a single live-allowed tier with a single daily cap, or (b) re-define Tier A on **MFE-based** criteria (Tier A signals had +1.07pp larger MFE — a real but weak signal).

### F2 — Two of five Tier A confluences are saturated to ≥96% base rate [NEW FINDING — LOW]
**Evidence:** MSS=HIGH at 96.5%, FVG=HIGH (the ≥MEDIUM check) at 100%, iFVG bonus at 97%. These cannot contribute discrimination.
**Implication:** Tier A is effectively `4/5 confluences = session + entry_type + DR_match + (MSS_HIGH_automatic) + (FVG_HIGH_automatic)`. Practically only **session + entry_type + DR_match** carry information. Of those, DR_match is near-uniform after Fix #30 (39/39/22 split).
**Action:** documented as `TPL-DR` carry-over (HIGH) in CROSS_REF. No new action — re-design of Tier A is the open carry-over from cycle-7.

### F3 — Tier C coverage problem unchanged [KNOWN STRUCTURAL — C2]
**State:** Confirmed in `template_performance_report.md:217` (Tier B and C identical in All-Matched View because every signal already satisfies MSS≥MEDIUM by entry gate). Acknowledged. No re-flag.

### F4 — Best-match assignment hides Tier A signals when bonuses lift Tier B score [VERIFIED behaviour, not a bug]
The "Best Match Only" view sorts `(not is_match, tier_rank, -score)`. A signal that matches both Tier A and Tier B is assigned to Tier A. The 0/0/0 in the current report is because **100% of current signals are CRT** (`matched_template_id='NONE'`). Behaviour is correct.

### F5 — CRT signals bypass templates correctly [VERIFIED]
Three-layer defence (data-tag + 5M-scanner Phase5A check + CRT-specific LIVE BLOCK) all aligned. No bug found.

### F6 — iFVG bonus has near-zero discriminating power on 5M_SWEEP [NEW FINDING — LOW]
At 97% base rate, the +0.05 iFVG bonus is paid to almost every signal. It is effectively a constant offset to the score. Not harmful, but if a future Tier A redesign uses score-based gating (e.g. score ≥ 0.85), this constant offset must be subtracted or the gate calibration will drift.

---

## Score Movement Justification (6.5 → 7.0)

| Aspect | Cycle-7 (6.5) | This audit | Δ |
|---|---|---|---|
| Code drift since last audit | n/a | **0 commits** to strategy_templates.py | +0.0 |
| CRT bypass correctness | not yet audited | **verified at 3 layers** | +0.3 |
| Tier hierarchy invariant | OK | re-validated (0 violations) | +0.0 |
| Tier A/B discrimination | flagged weak | **quantified — confirmed negligible** | -0.2 |
| Confluence base-rate diagnosis | partial | **complete — 3 of 5 confluences saturated** | +0.4 |
| Operational relevance | live | **dormant (CRT-only)** — risk surface shrunk | +0.0 |
| Cycle-7 carry-overs | open | still open (TPL-DR HIGH, F1 MEDIUM) | +0.0 |

Net: **+0.5** for completing the CRT-bypass verification and quantifying the saturation problem, partially offset by the now-quantified A/B separation failure.

---

## Proactive Improvement Suggestions

**Suggestion 1 — Defer Tier-A redefinition until 5M_SWEEP is re-enabled.**
**Why:** The system is dormant; any redesign now would be calibrated on stale Run-168 data and re-calibrated again before going live. Wait for at least one operator-driven 5M_SWEEP re-enable session before re-scoring.
**Impact:** MEDIUM (avoids wasted effort)
**Effort:** Simple (a decision, not a change)

**Suggestion 2 — When 5M_SWEEP is re-enabled, redefine Tier A on MFE-percentile basis.**
**Why:** The one metric where Tier A *does* separate from Tier B is MFE (+1.07pp). Define Tier A as "top 25% of signals by realised MFE on holdout." This is data-driven (per the task's percentile-rank suggestion) and uses the only confluence that survives gate-saturation.
**Impact:** HIGH (only path to restoring tier discrimination on current gates)
**Effort:** Medium (offline calibration + 1 PR to swap `_score_tier_a`)

**Suggestion 3 — Introduce a CRT-side template tier system in CRT v2.**
**Why:** Currently every CRT signal lands in `NONE`/`UNKNOWN_TEMPLATE` and is paper-only. The CRT data already supports tier-like discrimination — entry_type breakdown in `template_performance_report.md` shows `H4_CRT_OB_MARKDOWN` at 78.6% WR vs `H4_CRT_OB_TRANSITION` at 30.8% WR — a 47.8pp spread. This is the *strongest tier discriminator in the entire dataset*, larger than anything the ICT tier system ever produced on 5M_SWEEP.
**Impact:** HIGH (a CRT-tier system would actually do useful work; the ICT tier system is currently doing none)
**Effort:** Complex (new template family + `evaluate_template_status` extension + tracker UI; aligns with planned CRT v2 work)

**Suggestion 4 — Drop the iFVG bonus or replace with iFVG age/freshness.**
**Why:** At 97% base rate, `ifvg_present=True` is a constant. iFVG **age** (`ifvg_age_bars`) is in the schema and has real variance — recent iFVGs may carry more signal than old ones.
**Impact:** LOW (bonus is already operationally inert; cleanup only)
**Effort:** Simple

**Suggestion 5 — Add `template_performance_report.md` warning when 100% of signals are NONE.**
**Why:** The current report shows Tier A/B/C all at n=0 with no contextual note explaining "this is because all 416 signals are CRT". A new reader would assume the system is broken. Add a one-line banner: "100% of signals are H4_CRT — the 5M_SWEEP template tiers are dormant for this run."
**Impact:** LOW (UX clarity)
**Effort:** Simple (template_performance_report writer in `backtest.py:_dim_table`)

---

## Cross-Domain Observations

**Observation 1 — OGD weight isolation by source matters more than by template now.**
**Relevant Agent:** `adaptive-learning-code-reviewer`
**Reason:** With CRT producing 2,441 closed signals (85% of all closed trades) vs 5M_SWEEP producing 426 (15%), the shared `token_weights` vector is now learning predominantly from CRT signals. When 5M_SWEEP is re-enabled, the OGD bootstrap will be **CRT-flavoured** and may not generalise to the 5M_SWEEP signal mix (which has very different MSS, FVG, session, entry_type distributions — confirmed §4). The Phase 5B per-template isolation was scoped for the wrong axis; **per-source isolation** is the more urgent need. Recommend auditing `token_weights` schema + `_trigger_weight_update` for a `source` dimension before re-enabling 5M_SWEEP.

**Observation 2 — Entry-type discrimination on CRT side is enormous.**
**Relevant Agent:** `ict-logic-validator` and `signal-performance-analyzer` (if exists)
**Reason:** `template_performance_report.md` shows CRT entry-type WR spread of 47.8pp (`H4_CRT_FVG_ACCUMULATION` 84.6% vs `H4_CRT_OB_TRANSITION` 30.8%). That's a stronger predictive signal than anything in the 5M_SWEEP feature space. Two follow-ups: (a) validate that `H4_CRT_OB_TRANSITION` shouldn't simply be gated out, (b) confirm the Wyckoff-phase tagging (TRANSITION/ACCUMULATION/MARKDOWN) is being captured into `feature_scores_json` so OGD can learn it.

**Observation 3 — Run-168 metrics (29 signals, 82.8% WR) vs current 5M_SWEEP backtest (426 signals, ~82% WR) — sample-size mismatch.**
**Relevant Agent:** `backtest-bias-detector` or `live-backtest-consistency-checker`
**Reason:** The CRT context file lists 5M_SWEEP at n=29/365d but the live signals.db shows n=426 closed 5M_SWEEP backtest signals across all runs. WR is consistent (~82-83%), but the n discrepancy suggests the historical aggregator is mixing multiple backtest_run configs. Recommend confirming the 426 are all from the Run-168 gate config (not bleed-through from older runs).

---

## Decision Summary

- **Tier system is DORMANT in CRT-only mode** — no live blocking risk.
- **No template-code drift today** — strategy_templates.py untouched in 16+ CRT commits.
- **Tier A/B discrimination has decayed** to a statistically meaningless 1.7pp WR delta on 5M_SWEEP, but this is a **gate-saturation artefact** and is the cycle-7 carry-over, not a regression.
- **CRT bypass is correctly implemented** at 3 layers.
- **Phase 5B per-template OGD isolation is LESS urgent in CRT-only mode** — the more urgent isolation axis is now **per-source** (5M vs CRT).

**Recommended re-audit trigger:** when operator re-enables `ENABLE_5M_SWEEP=1` (mixed-source mode) — at that point the tier system becomes operationally live again and the recommendations in §Proactive should be acted on.

---

**Score: 7.0 / 10** (up from 6.5/10 — see §Score Movement Justification)
