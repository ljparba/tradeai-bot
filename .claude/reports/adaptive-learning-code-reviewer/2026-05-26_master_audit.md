# TradeAI Adaptive Learning — Master Audit
**Reviewer:** adaptive-learning-code-reviewer (Opus 4.7 1M context)
**Date:** 2026-05-26
**Scope:** Full adaptive layer (OGD engine, monitoring, dual-track WFV, reward, bootstrap, persistence)
**Cross-ref reviewed:** `docs/comprehensive/CROSS_REF.md` (203 entries)
**Score:** **8.6 / 10** — fundamentally sound, production-safe; specific weaknesses identified.

---

## 1. Executive Summary

The adaptive layer is **legitimately adaptive** — not cosmetic. After tracing the
full loop (signal generated → OGD scores → trade closes → `_trigger_weight_update`
→ DB-persisted weight delta → next signal scored with new weight → Phase D.1 dual
track audits the gap), I confirm:

- Learning genuinely happens, is bounded, persisted atomically, and visible on dashboards.
- H6 isolation between backtest scoring and live learning is correctly preserved for CPCV validity.
- Phase D.1 dual-track is a genuinely strong addition — it closes the H6 quantification gap without breaking CPCV honesty.
- Guardrails (warmup, velocity clip, weight envelope, degenerate-reject, thin-sample reject, decay-suppression-after-update, cross-token diversity monitor, M-I/M-J fixes) form a tight defense-in-depth.

What is **not yet present** and represents the realistic improvement frontier:
- No regime-conditioned weights (single weight pool per token across all market states).
- No DSR-aware learning gate (OGD updates fire even when CPCV says current edge is unreliable).
- No automatic learning kill switch on volatility/parity-drift anomalies.
- Reward function has subtle conservation issue at the n=10 cliff (PARTIAL_TP1 burns warmup slots at full count but contributes 0.5 to n_effective; cliff is sharp).
- Confidence-as-feature loop (M13) remains accepted; valid trade-off but should be re-examined post-LIVE.

**Bottom line:** the system is honest, sample-efficient, interpretable, and statistically defensible at current sample counts. Do not redesign. Apply 4 quick wins and 3 medium-term improvements. Wait on regime conditioning, per-template OGD, and concept-drift CUSUM until n_per_token ≥ 30 paper signals.

---

## 2. Critical Findings

### 2a. What is EXCELLENT (preserve, do not touch)

| # | Finding | Why it is excellent |
|---|---|---|
| E1 | **H6 isolation** (`backtest.py:1102` uses AE_DEFAULT_WEIGHTS only) | Correctly preserves CPCV's independence assumption. Documented, tested, intentional. |
| E2 | **Phase D.1 dual-track** (`walk_forward.walk_forward_with_ogd`) | Statistically valid (sequential WFV does not break independence even with adaptive weights — per López de Prado AFML §8). Sandboxed engine (persist=False, fresh state) is the right pattern. |
| E3 | **Decaying LR with momentum + velocity clip** (lines 409–417) | Mathematically sound under low samples. LR floor 0.01 + decay halflife 100 + MAX_WEIGHT_STEP 0.04 prevents any single outcome from moving any feature weight by more than 4pp post-clip. |
| E4 | **Weight envelope + renormalization + degenerate-reject at 0.40** | Run-46 collapse mode cannot recur silently. Mirrored in 3 places (adaptive_engine, monitoring, tracker) with CI drift test (`tests/test_monitoring.py:41`). |
| E5 | **M-I + M-J + thin-sample guard** (lines 639–705) | The bootstrap pool is the most dangerous input (cross-runs, asymmetric direction mix). The combination of (a) thin-sample → force defaults, (b) degenerate-reject → force defaults, (c) seed _last_update_time to bootstrap epoch → 7-day decay-suppression activates correctly, eliminates an entire class of silent contamination. |
| E6 | **State atomicity** | `_persist_token` is single INSERT OR REPLACE in one transaction; PA-3/PA-4 (`state_store.py`) covers process state. No half-written states possible. |
| E7 | **Monitoring `--source bootstrap` flag** (OGD-MON-SCOPE fix) | 99% of OGD learning lives in `backtest_token_weights`; monitor finally sees it. |
| E8 | **Cross-token diversity monitor** (`monitoring.cross_token_diversity`) | The only protection against "everything converges to one global vector" — necessary because the architecture explicitly forbids cross-token transfer. |
| E9 | **Reward function blend** (50/50 discrete + P&L-scaled, line 384) | The right trade-off: bucket structure preserves robustness against P&L tail extremes while P&L blend prevents the WIN/LOSS binarization from ignoring magnitude. |
| E10 | **CPCV verdict cap at MARGINAL when DSR is None** (validation.py C-B fix) | Prevents the most dangerous bug class: silent verdict inflation. Combined with `n_oos_per_fold` fix (C-NEW-1), DSR is now honest. |

### 2b. What needs ATTENTION (MEDIUM severity, fix in coming weeks)

| # | Finding | File:Line | Why it matters |
|---|---|---|---|
| A1 | **No DSR-aware learning gate** | `crypto_alert.py:1155` (`weight_engine.update` always fires) | When CPCV verdict = FAIL or MARGINAL, the rule engine's edge is statistically unreliable. Learning on top of unreliable signal amplifies noise. Documented as L-H in cross-ref, not yet wired. |
| A2 | **n=10 warmup cliff is sharp** | `adaptive_engine.py:395` | First 9 signals: zero learning. 10th: full LR. With effective sample tracking (`_n_effective`) showing PARTIAL share at 28.6%, real "effective n=10" lands at raw n≈14. Cliff should ramp, not jump. |
| A3 | **Decay-toward-default runs every 30 min unconditionally during the 7-day window** | `adaptive_engine.py:745`, `crypto_alert.py:3269` | The 7-day suppression is good, but post-7-days the 0.0004 decay rate still fires every 30 min regardless of whether new market data has arrived. On weekend / dead hours, weights silently relax toward defaults — operator cannot tell whether weight drift came from real signals or decay drift. |
| A4 | **Reward conservation at n=10 cliff** | `adaptive_engine.py:388` | When `reward == 0.0` (unknown outcome) the n counter increments but no learning happens. Combined with the n=10 hard cliff this is correct, but PARTIAL_TP1 outcomes with reward 0.4 burn full-weight warmup slots in raw n while only contributing 0.4 to gradient — `n_effective` is the right metric for ACTIVATION, not just diagnostic. |
| A5 | **No automatic learning freeze on drift/volatility anomalies** | n/a | DriftDetector detects regime change for thresholds (ADX/RSI) but does NOT signal "stop learning" to AdaptiveWeightEngine. Black swan day → 5 LOSS outcomes → 5 large negative gradients. The bounded weight step (0.04) helps but does not prevent a synchronized down-shift. |
| A6 | **Bootstrap re-runs on EVERY backtest** (`backtest.py:3388`) | `backtest.py:3388` | Operator runs many backtests/day during optimization. Each rewrites `backtest_token_weights`. The M-J thin-sample guard catches small samples, but a backtest with `BACKTEST_DAYS=30` accidentally clears prior-learned bootstrap weights for tokens with >5 samples in the small window. Should require an explicit `--bootstrap` flag or guard on n>=BOOTSTRAP_MIN_N. |
| A7 | **Confidence-as-feature loop** | `adaptive_engine.py:1304` (M13) | KNOWN STRUCTURAL per CROSS_REF, accepted under current hyperparameters. Re-examine post-LIVE — at n=100 paper signals per token the recursive-reinforcement risk grows. Fix A (remove `confidence` from FEATURES) is one option; alternative: keep but normalize differently. |
| A8 | **Scheduled monitoring not verified running daily** | `data/monitoring/` shows last entry `report_2026-05-24.json` | Two-day lag suggests no cron / systemd timer. The OGD-MON-SCOPE fix is necessary but useless if the monitor is never invoked. Recommend `tradeai-monitor.timer` systemd unit, daily at 06:00 UTC, with `--exit-on-crit` driving Telegram alerting. |

### 2c. What is DANGEROUS if left unchanged (HIGH/CRITICAL)

| # | Finding | Severity | Why dangerous |
|---|---|---|---|
| D1 | **Bootstrap can silently overwrite learned bootstrap weights from prior run** (carry of A6) | HIGH | If an operator runs a 30-day backtest "just to check", every token's bootstrap weights are replaced by 30-day-derived weights. Live continues using its own `token_weights`, but next deployment / reset would warm-start from the corrupted bootstrap pool. Gate: require explicit env var `BOOTSTRAP_AFTER_RUN=1` to enable bootstrap, default OFF. |
| D2 | **Reward magnitude not capped at the BLEND step, only the P&L step** | MEDIUM-HIGH | `_pnl_scaled = max(-2.0, min(2.0, profit_pct/0.01))` then `reward = 0.5*base + 0.5*_pnl_scaled`. WIN base = +1.0; pnl_scaled cap = +2.0; reward max = +1.5. Then gradient = reward × score where score ∈ [0,1]. Per-feature step ≤ MAX_WEIGHT_STEP (0.04) — clipped. But: with momentum at 0.85, a sequence of three +1.5 rewards on the same dominant feature pushes velocity to ~0.04×3/(1-0.85)≈0.10 — clipping bites three times. The clip works, but the LR×reward×score product should be checked for the realistic worst case (~3 large WINs on a single bias). Recommend adding explicit per-update reward log + alert when `|reward|>1.2`. |
| D3 | **Live `token_weights` has no per-update audit row in `weight_history`** with the gradient itself | MEDIUM-HIGH | `weight_history` only stores weight_before/weight_after; the reward, profit_pct, feature_scores driving the update are NOT recorded. Post-hoc forensics ("why did fvg_quality jump 0.08 on signal #245?") requires joining `signals.feature_scores_json` and `results.profit_pct` — works but fragile. Add `reward` and `gradient_l1` columns to `weight_history`. |
| D4 | **DriftDetector and AdaptiveWeightEngine are operationally disconnected** | MEDIUM | DriftDetector flips ADX/RSI thresholds when concept drift detected. AdaptiveWeightEngine continues learning as if nothing happened. When drift hits, the very features (session, trend_strength) that learned under regime A may be actively wrong under regime B. No coupling. This is the deepest current weakness. |

### 2d. What should NOT be changed yet (low-sample protection)

| # | Item | Why defer |
|---|---|---|
| W1 | **Per-template OGD (Phase 5B)** | Requires n≥30 per (token, template). Currently n≈3-4 per token total. Wait. |
| W2 | **Per-direction (BUY/SELL) weight pools** | Doubles the parameter count; would require n≥30 per (token, direction). Same blocker. |
| W3 | **Regime-conditioned weights** with 8 regimes | At 8 regimes × 10 tokens × 6 features = 480 weights. Need n≥30 per cell ≈ 14,400 samples. Wait, but START labeling regime NOW (per-signal column). |
| W4 | **Feature interaction terms (fvg × session, mss × trend)** | At low n these are noise. Test in shadow mode only when n≥100 per token. |
| W5 | **Multi-armed bandit for template selection** | Same as W1 — needs sample volume. |
| W6 | **Negative feature weights** | Requires normalization redesign + much stronger monitoring. n needs to be high enough to confidently say "this feature is anti-predictive" — Wilson CI at n=20 spans ±20pp. Defer indefinitely. |
| W7 | **Concept-drift CUSUM (Phase D.2)** | Per ADAPTIVE_LEARNING §13 — requires 100+ closed paper signals. Wait. |

---

## 3. Prioritized Recommendations

### R1 — Wire DSR-aware learning gate
- **Priority:** HIGH
- **Impact:** Prevents amplifying noise when CPCV says edge is unreliable
- **Effort:** Simple (2-4h)
- **Implementation risk:** LOW — single check before `weight_engine.update()` in `crypto_alert._trigger_weight_update`
- **Safe now or defer:** SAFE NOW (hookup exists per L-H in cross-ref)
- **Pros:** Statistical honesty; learning aligns with validation verdict; defends against learning during MARGINAL/FAIL regimes
- **Cons:** Will pause learning during early paper period if CPCV is borderline — that is the correct behavior
- **Data leakage risk:** NONE (CPCV verdict is computed on historical signals; reading it before applying live learning is read-only)
- **Overfitting risk:** REDUCES overfitting (pauses learning when DSR says edge is too small to trust)
- **Implementation:**
  1. After backtest, persist latest CPCV verdict + DSR + sr_trial_std to `bot_state.latest_cpcv_verdict` (already partly there)
  2. In `_trigger_weight_update`, read it; if verdict in {FAIL, MARGINAL} AND `n_seen[token] < OGD_MIN_SAMPLES × 3` (still warming up), increment n only, skip OGD math
  3. Log `[ADAPTIVE] {token} learning gated: cpcv_verdict={X} dsr={Y}`
- **Acceptance:** Test with synthetic FAIL-verdict signal → assert update() skips OGD math but n increments; assert PASS-verdict resumes normal updates

### R2 — Soft warmup ramp (replace n=10 cliff)
- **Priority:** HIGH
- **Impact:** Smoother adaptation, better behavior at the boundary
- **Effort:** Simple (1-2h)
- **Implementation risk:** LOW
- **Safe now or defer:** SAFE NOW
- **Pros:** Removes a discontinuity; lets early signals contribute partial gradient instead of being discarded
- **Cons:** Slightly more learning before n=10 (need to validate not destabilizing)
- **Data leakage risk:** NONE
- **Overfitting risk:** Tightly bounded by an additional `warmup_scale = min(1.0, n_effective / OGD_MIN_SAMPLES)` multiplier
- **Implementation:** Multiply the effective LR by `warmup_scale ∈ [0,1]`. At n=0: zero learning. At n=10: full LR. Smooth ramp.
- **Acceptance:** Unit test: 5 WIN signals with the ramp produces strictly smaller weight delta than 5 WIN signals post-warmup full LR

### R3 — Gate bootstrap on explicit env var
- **Priority:** HIGH
- **Impact:** Prevents accidental bootstrap pool corruption during ad-hoc backtests
- **Effort:** Simple (15 min)
- **Implementation risk:** VERY LOW
- **Safe now or defer:** SAFE NOW
- **Pros:** Eliminates D1 entirely
- **Cons:** Operator must remember the flag; documented behavior change
- **Implementation:** `backtest.py:3388`: wrap the `weight_engine.bootstrap_from_backtest` call in `if os.environ.get("BOOTSTRAP_AFTER_RUN", "0") == "1":`. Default OFF. Operator promotion script explicitly sets it.
- **Acceptance:** Run `python3 backtest.py` without flag → no bootstrap write; run with `BOOTSTRAP_AFTER_RUN=1` → bootstrap write

### R4 — Add `reward, gradient_l1, profit_pct` columns to weight_history
- **Priority:** MEDIUM
- **Impact:** Forensic clarity; future feature importance analysis without DB joins
- **Effort:** Simple (1h: schema migration + write path)
- **Risk:** LOW (additive columns, NULL-default)
- **Safe now:** YES
- **Acceptance:** New rows have reward + gradient_l1 populated; old rows stay NULL

### R5 — Daily monitoring systemd timer + Telegram on CRIT
- **Priority:** MEDIUM
- **Impact:** Closes operational visibility gap (last report 2026-05-24)
- **Effort:** Simple (30 min: write unit + timer file)
- **Risk:** VERY LOW
- **Safe now:** YES
- **Implementation:** `deploy/tradeai-monitor.timer` + `tradeai-monitor.service` running `python3 monitoring.py --source bootstrap --exit-on-crit --json /home/tradeai/TradeAI/data/monitoring/report_$(date +%Y-%m-%d).json` daily at 06:00 UTC; on exit code 2 send Telegram via `secrets_loader` + `heartbeat.MultiChannelAlerter`
- **Acceptance:** New JSON report appears daily; CRIT scenario delivered via Telegram

### R6 — Decouple decay timer from real-time clock; tie to signal events
- **Priority:** MEDIUM
- **Impact:** Removes A3 ambiguity (was that drift from learning or decay?)
- **Effort:** Medium (4-6h: change decay trigger from cron-style to event-driven)
- **Risk:** MEDIUM (changes a load-bearing behavior)
- **Safe now:** YES (additive — gate existing decay loop behind an env var; new event-driven path in parallel)
- **Implementation:** Decay rate becomes per-signal (e.g. `decay_per_signal = 0.005`) applied just before each `update()`. Remove or gate the 30-min cron loop.
- **Acceptance:** With OGD updates suspended, weights do NOT drift toward defaults; with updates active, decay applies as a small pre-step

### R7 — Regime labeling (NOT regime conditioning) — start now
- **Priority:** MEDIUM
- **Impact:** Foundation for future R10 without breaking current low-sample posture
- **Effort:** Simple (2-3h: add `regime_label` column to `signals` table; populate from existing `market_regime` field already in use)
- **Risk:** VERY LOW (additive, no behavior change)
- **Safe now:** YES — only labels; does NOT condition weights yet
- **Implementation:** `regime = classify_regime(adx, atr_ratio, session, btc_trend)`. Persist as new column. Monitor per-regime WR via dashboard.
- **Acceptance:** Every new signal has regime_label. Dashboard shows per-regime WR with sample counts. NO change to OGD math.

### R8 — Reward magnitude alert on `|reward|>1.2`
- **Priority:** MEDIUM
- **Impact:** Closes D2 (large extreme-event signal injection)
- **Effort:** Trivial (10 min)
- **Risk:** ZERO
- **Implementation:** in `update()` after `reward` computed, log + optional Telegram on `abs(reward) > 1.2`
- **Acceptance:** Synthetic +1.8 reward triggers alert

### R9 — Automatic learning freeze on volatility / FOMC / outage
- **Priority:** MEDIUM (will be HIGH once LIVE)
- **Impact:** Black-swan defense
- **Effort:** Medium (1-2 days: integrate `event_calendar` + Binance status + DriftDetector signals into a single `learning_enabled()` predicate)
- **Risk:** MEDIUM
- **Safe now:** PARTIAL — implement the predicate + log; do NOT auto-freeze until LIVE
- **Implementation:** `learning_enabled(token, now)` returns False when: (a) `event_calendar.in_window(now)`, (b) `drift_detector.drift_detected[token]`, (c) Binance feed flagged failed within last 60 min, (d) consecutive_losses ≥ 5 in last 24h. If False → log + skip OGD math (still increment n_effective for diagnostic visibility).
- **Acceptance:** Synthetic FOMC window → 3 closed trades during it → no weight changes; log shows "frozen — fomc_window"

### R10 — Regime-conditioned weights (DEFERRED until n_per_token ≥ 30 paper)
- **Priority:** LOW (becomes HIGH at 6-month paper mark)
- **Impact:** Captures the strongest known structural variance
- **Effort:** Complex (1-2 weeks)
- **Defer:** YES until N_per_token ≥ 30 in EACH regime cell
- **Implementation guidance:** Start with 3 regimes (TRENDING, RANGING, HIGH_VOL) — not 8. Each token has 3 weight vectors. Regime classifier from signal time. Update applies to the active regime's vector. Decay-toward-default still per-regime.
- **Acceptance:** Per-regime weights all bounded; per-regime entropy monitored; cross-regime homogeneity alarmed at L1<0.20

### R11 — Feature importance via per-feature ablation (shadow mode)
- **Priority:** LOW
- **Impact:** Quantifies which of the 6 features carries real signal — Phase 5B prerequisite
- **Effort:** Medium (3-5 days)
- **Defer:** UNTIL n_per_token ≥ 50
- **Implementation:** For each feature, run a shadow OGD with that feature held at default. Compare top-decile-WR-lift in walk_forward_with_ogd. The lift delta is that feature's contribution.

### R12 — Replace OGD with FTRL-Proximal (REJECTED)
- **Priority:** NO
- **Rationale:** FTRL is better at L1 sparsity. We do NOT want sparsity here (`WEIGHT_MIN=0.05` prevents it). The current bounded clip-and-renormalize is a more interpretable bounded analog. Do not over-engineer.

### R13 — Replace OGD with Bayesian linear (DEFERRED)
- **Priority:** LOW
- **Rationale:** Closest mathematical alternative. Adds posterior uncertainty per feature. Major API change. Defer to post-LIVE re-evaluation; current OGD is sufficient.

---

## 4. Quick Wins (≤ 1-2 days)
1. **R3** — Gate bootstrap on env var (15 min)
2. **R8** — Reward magnitude alert (10 min)
3. **R5** — Daily monitor systemd timer (30 min)
4. **R4** — weight_history forensic columns (1h)
5. **R2** — Soft warmup ramp (1-2h)
6. **R1** — DSR-aware learning gate (2-4h)
7. **R7** — Regime labeling (2-3h)

Total ≈ 1 working day. All seven safe-now. None changes OGD math fundamentally.

---

## 5. Medium-Term Roadmap (1-3 weeks)
- **R6** — Event-driven decay (4-6h)
- **R9** — Learning freeze predicate (1-2 days)
- Forensic dashboard panel showing per-token: raw n, n_effective, reward distribution histogram, last 20 weight deltas
- Telegram weekly digest of adaptive health (degenerate count, entropy trend, cross-token diversity)

---

## 6. Long-Term Roadmap (3-12 months, n_per_token ≥ 30 paper)
- **R10** — Regime-conditioned weights (3 regimes first)
- **R11** — Feature importance via shadow ablation
- Phase 5B per-template OGD weights (per ADAPTIVE_LEARNING §13)
- Concept-drift CUSUM (Phase D.2)
- Multi-armed bandit for template selection
- Re-evaluate confidence-as-feature loop with empirical data

---

## 7. Revised Code Structure Suggestions

| File | Suggested addition |
|---|---|
| `adaptive_engine.py` | `learning_enabled(token, now)` predicate (R9). `warmup_scale(n_effective)` helper (R2). Add `reward`+`gradient_l1` to `weight_history` write (R4). |
| `monitoring.py` | `parity_drift_check()` reading `walk_forward_with_ogd` parity verdict history. Already has good bones. |
| `walk_forward.py` | Persist Phase D.1 verdict per-run to `bot_state.latest_parity_verdict` so R9 can read it. |
| `backtest.py` | Gate `bootstrap_from_backtest` on `BOOTSTRAP_AFTER_RUN` env (R3). |
| `crypto_alert.py:_trigger_weight_update` | Read `bot_state.latest_cpcv_verdict` + DSR; gate update math (R1). |
| `deploy/tradeai-monitor.{service,timer}` | New systemd files (R5). |
| `data/signals.db` schema | Add `signals.regime_label` column (R7). Add `weight_history.reward`, `gradient_l1` (R4). |

---

## 8. Recommended Hyperparameters (current values are good; minor refinements)

| Param | Current | Recommended | Rationale |
|---|---|---|---|
| `LEARNING_RATE_INIT` | 0.06 | **Keep 0.06** | Empirically tested. Decay halves it at n=100. |
| `LEARNING_RATE_FLOOR` | 0.01 | **Keep 0.01** | Sufficient for late-stage refinement. |
| `LEARNING_RATE_DECAY` | 100 | **Keep 100** | ~3 years at 34 signals/yr per token — appropriate horizon. |
| `MOMENTUM` | 0.85 | **0.80** | Slightly lower momentum gives faster response to regime change; combined with velocity clip, no instability risk. MINOR. |
| `MAX_WEIGHT_STEP` | 0.04 | **Keep 0.04** | 4pp/update is the right magnitude given 6 features summing to 1.0. |
| `WEIGHT_MIN` | 0.05 | **Keep 0.05** | Forbids "feature goes silent" — anti-Run-46 protection. |
| `WEIGHT_MAX` | 0.50 | **Keep 0.50** | Permits 2× default concentration but no more. |
| `DEGENERATE_THRESHOLD` | 0.40 | **Keep 0.40** | Tested, mirrored, CI-gated. |
| `OGD_MIN_SAMPLES` | 10 | **Keep 10** (but add R2 ramp) | Hard activation threshold; ramp smooths the transition. |
| `BOOTSTRAP_MIN_N_PER_TOKEN` | 5 | **Keep 5** | M-J fix; appropriate. |
| `DECAY_RATE` | 0.0004 | **Keep 0.0004** (but switch to event-driven per R6) | Magnitude is right; trigger is wrong. |
| Decay-suppression-after-update window | 7 days | **Keep 7d** | Reasonable at current signal frequency. |
| `_SCORE_FLOOR` | 0.05 | **Keep 0.05** | Critical for SELL@DISCOUNT (and BUY@PREMIUM) zero-gradient avoidance. |

New parameters proposed:
- `DSR_LEARNING_GATE_THRESHOLD = 0.95` (only learn when DSR ≥ 95%) — R1
- `REWARD_ALERT_THRESHOLD = 1.2` — R8
- `LEARNING_FREEZE_LOSS_STREAK = 5` (consecutive losses → freeze) — R9
- `BOOTSTRAP_AFTER_RUN` env var, default "0" — R3

---

## 9. Anti-Overengineering Filter (DO NOT IMPLEMENT YET)

| Idea | Reject reason |
|---|---|
| Neural net or deep RL | Per ADAPTIVE_LEARNING §3.5 — sample-starved, opaque, no edge. |
| Replace OGD with Adam | Adam needs larger gradients to shine; OGD with momentum already adapts step size implicitly via velocity. Switching = new bugs, no win. |
| Per-feature uncertainty (Bayesian) | Beautiful but adds parameters that themselves need calibration; defer to R13. |
| Replay buffer | RL pattern; with ~34 signals/yr the buffer would either be ancient or trivially small. |
| Negative feature weights | At n<50 per token, false-negative-weight conclusions destroy the signal. Defer indefinitely. |
| Meta-learning the learning rate | The current decay schedule IS meta-learning, hand-tuned with empirical justification. Adding a meta-optimizer is unnecessary complexity. |
| Cross-token transfer (multi-task) | Architecture forbids it by design (see ADAPTIVE_LEARNING §16 FAQ). |
| Per-regime × per-direction × per-template weights | Parameter explosion (480+ weights). NOT before n ≥ 5,000 closed signals. |
| Adversarial signal injection / red-team learning | Premature for a paper bot. |
| Adaptive threshold learning (displacement, FVG size) | NOT before R7+R10 land and we have data — shadow mode only when sample arrives. |

---

## 10. Final Recommended Implementation Order

This sequence minimizes risk, maximizes early value, and preserves CPCV/H6 honesty throughout.

1. **R3** Gate bootstrap on env var — eliminates accidental pool corruption (15 min)
2. **R8** Reward magnitude alert — observability win, zero risk (10 min)
3. **R5** Daily monitoring systemd timer — close visibility gap (30 min)
4. **R4** Add reward + gradient_l1 columns to weight_history — forensic foundation (1h)
5. **R7** Regime labeling — data collection NOW so future R10 has samples (2-3h)
6. **R2** Soft warmup ramp — smoother boundary at n=10 (1-2h)
7. **R1** DSR-aware learning gate — biggest single statistical-honesty win (2-4h)
8. **R6** Event-driven decay — cleanup before adding more layers (4-6h)
9. **R9** Learning freeze predicate — wire it in shadow-mode (log only) first (1 day)
10. Build per-token forensic dashboard panel — operational maturity
11. WAIT for n_per_token ≥ 30 paper closed signals (estimated Q3 2026)
12. **R11** Feature importance ablation in shadow
13. **R10** Regime-conditioned weights with 3 regimes
14. Phase 5B per-template OGD
15. Concept-drift CUSUM (Phase D.2)
16. Re-examine M13 confidence-as-feature loop with empirical evidence

Steps 1-9 are achievable within 2 weeks. Steps 10+ are 6-12 months out, gated on paper sample accrual.

---

## 11. Final Verdict

**Truly adaptive — production-grade for current sample regime.**

The system learns, persists, audits, and validates honestly. The H6 + Phase D.1 dual-track design is genuinely a strong piece of quant engineering — most "adaptive" bots either contaminate their backtest or skip the parity check entirely. The guardrails (warmup, clip, envelope, degenerate-reject, thin-sample reject, decay-suppression, cross-token diversity) reflect mature defensive engineering.

The improvements identified are refinements, not rebuilds. The 4 quick wins close real operational gaps (R3/R5/R8/R4) and 3 medium improvements (R1/R2/R7) advance statistical honesty. Defer everything regime/template/feature-interaction until paper samples justify the parameter expansion.

**Do not:** re-baseline by changing OGD math while operator is paper-trading; redesign reward function without 30+ paper signals; add per-template/per-regime/per-direction weights before sample accrual gates clear; reintroduce vectorbt; replace OGD with Adam/Bayesian.

**Do:** ship the 7 quick + medium items in order; instrument; observe; revisit at the n=30/token milestone.
