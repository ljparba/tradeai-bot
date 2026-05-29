# TradeAI — Enhancement Roadmap (2026-05-28)

**Purpose:** Track all strategy + AI improvements identified post-cycle-11 audit.
**Status as of creation:** Bot scored 9.30/10 (new ATH). Baseline = Run-1056 (C2).
Live paper data = 5 closed signals; LIVE-clearance gate still 25+ signals away.

This document is the **single canonical list** of remaining bot improvements.
Each item is tiered by when it makes sense to ship vs the binding constraint
(usually paper-data accumulation).

---

## Tier 1 — DO BEFORE LIVE flip (~2-3 weeks total)

These add real edge or close real risk gaps. Should be in place before
EXECUTION_MODE=LIVE flips.

### T1.1 — Portfolio-level risk model 🔴 CRITICAL for LIVE
**Status:** Not started
**Blocker:** None
**Effort:** 2-3 days
**Files to modify:** `crypto_alert.py:scan_h4_crt_for_token`, new `portfolio_risk.py`

**Problem:** Currently per-trade risk is capped at 1% but there's no
aggregate-portfolio-risk limit. With 4 open positions = 4% portfolio risk.
With correlated tokens (BTC + ETH + LINK all SELL during BTC dump) = effective
6-8% portfolio exposure.

**Proposed:**
- New `PortfolioRiskLayer` class tracking sum of open-position risk
- Hard cap at 3% aggregate portfolio risk
- Correlation-adjusted exposure (BTC/ETH count as 1.5× weight)
- Reject new signals when adding them would exceed the cap

**Expected impact:** Prevents single-day -10% portfolio loss scenarios.
No alpha gain but massive downside protection in LIVE.

---

### T1.2 — Funding rate divergence feature
**Status:** ✅ SHIPPED 2026-05-29 (Stage A: live-only; Stage B historical-fetch deferred)
**Blocker:** None
**Effort:** 1 day (took ~3 hours)
**Files:** new `funding_rate_client.py` (~200 LoC), `crypto_alert.py` (CRT scan + save_signal + schema), `backtest.py` (stub NEUTRAL until Stage B), `scripts/autonomous_explorer.py` (4 new knobs in CRT search space)

**Stage A delivered:**
- Binance fapi `/premiumIndex` fetcher with 5min cache + 10-token batch fetch
- DB schema: `signals.funding_rate_pct` + `signals.funding_classification` + matching `backtest_signals` cols
- Live CRT scan tags every signal with funding rate + classification
- Confidence overlay (`confidence + 10 * funding_bonus`, clamped [0,10])
- Explorer search space: `FUNDING_GATE_ENABLED`, `FUNDING_EXTREME_LONG_THRESH`, `FUNDING_EXTREME_SHORT_THRESH`, `FUNDING_BONUS_PCT`
- `_compute_run_config_hash` extended with all 4 knobs (prevents collision)

**Stage B (deferred):** historical funding-rate lookup for backtest parity. Currently backtest writes `funding_rate_pct=0.0, funding_classification=NEUTRAL`. Live ↔ BT divergence documented at `backtest.py:run_backtest_token_h4_crt` signal-dict comment.

**Problem:** Extreme funding rates predict mean reversion. Free signal from
Binance/Bybit perpetuals API but currently ignored.

**Proposed:**
- Fetch 8h-funding-rate snapshots every 30 min
- Tag signals with `funding_rate_pct` + `funding_extreme` flag
- Add as 7th OGD feature (`funding_divergence_score`)
- Counter-trend signals get bonus when funding is extreme (>0.03% positive
  for SHORTs, <-0.03% for LONGs)

**Expected impact:** +1-3pp WR on counter-trend setups.

---

### T1.3 — BTC correlation feature (metadata overlay, NOT 7th OGD axis)
**Status:** ✅ SHIPPED 2026-05-29 (with full live/backtest parity)
**Blocker:** None (free OHLCV)
**Effort:** 1-2 days (took ~2 hours)
**Files:** new `btc_correlation.py` (~180 LoC), `crypto_alert.py` (CRT scan + save_signal + schema), `backtest.py` (mirror computation), `scripts/autonomous_explorer.py` (3 new knobs)

**Design pivot:** Originally planned as 7th OGD feature. **Pivoted to metadata + tunable overlay** to preserve existing trained OGD weights on AVAX/LINK/TON. Adding to OGD vector would have diluted ~3 months of learning.

**Delivered:**
- `compute_btc_correlation()` — Pearson r of log-returns over rolling window
- DB schema: `signals.btc_corr_strength` + `signals.btc_corr_classification` + matching `backtest_signals` cols
- Live CRT scan computes corr against BTC's 5M closed-only closes (no forming-bar bias)
- Backtest mirror computation with mss_bar_abs slice (no lookahead)
- Confidence overlay: `+BONUS` on ALIGNED_HIGH, `+BONUS/2` on ALIGNED_LOW, `-BONUS` on DIVERGENT
- Explorer search space: `BTC_CORR_WINDOW_MIN` (30..120), `BTC_CORR_BONUS_PCT` (0..0.10), `BTC_CORR_HIGH_THRESH` (0.5..0.9)
- `_compute_run_config_hash` extended with all 5 BTC corr knobs

**Default behavior:** `BTC_CORR_BONUS_PCT=0.0` ships disabled. Tagging only. Explorer tunes the bonus magnitude empirically via paper-soak feedback.

**Problem:** When BTC pumps 3% in an hour, ALT signals tend to follow.
Bot doesn't explicitly model this. Currently `BTC_BIAS` is used only as a
gate, not as a feature for OGD weight learning.

**Proposed:**
- Compute `btc_correlation_strength` = rolling 1h corr between BTC and target
  token returns
- Add as 7th OGD feature with initial weight 0.10
- Phase 5A safety: high-corr signals should NOT all fire same direction same
  minute (already handled via cooldown but worth reverifying)

**Expected impact:** +1-2pp WR on ALT signals (BTC + 9 alts).

---

## Tier 2 — DO AFTER first 30 closed paper signals

These need empirical validation that current strategy works in LIVE before
adding complexity.

### T2.1 — Multi-armed bandit for template selection
**Status:** Considered (see `docs/ADAPTIVE_LEARNING.md:139`)
**Blocker:** Need 30+ closed signals to seed prior
**Effort:** 5-7 days
**Files:** new `template_bandit.py`, `strategy_engine.py`

**Problem:** Current 4-tier template system is FIXED. Tier A=highest priority,
Tier C=paper-only. But what if Tier B starts outperforming Tier A in a new
market regime? Static tiers can't adapt.

**Proposed:**
- Replace static tiers with Thompson sampling
- Each template has Beta(α, β) posterior
- Sample from posteriors at signal time, pick highest-sample template
- Auto-explores templates that haven't been tested recently

**Why preferred over Phase 5B:** Bandit works at low n (n=10+); Phase 5B
needs n≥30 per template per token (=480+ total signals).

**Expected impact:** +2-4pp WR if market regime changes; allows graceful
template retirement when one stops working.

---

### T2.2 — Volume Profile Visible Range (VPVR)
**Status:** Not started
**Blocker:** Need validated CRT baseline first
**Effort:** 2-3 days
**Files:** `ict_engine.py`, `crt_engine.py`

**Problem:** ICT canonically uses HVN (High Volume Node) and LVN (Low Volume
Node) for reaction-zone identification. Current bot only uses price-action
swings, not volume.

**Proposed:**
- Compute VPVR over rolling 30-day window (price bins × volume)
- Identify HVN (top 20% volume) and LVN (bottom 20%)
- Tag signals with `entry_near_hvn` / `entry_near_lvn` flags
- HVN = strong support/resistance (good for TP placement)
- LVN = fast move-through zone (good for entry/SL placement)

**Expected impact:** +2-4pp WR; better TP/SL placement.

---

### T2.3 — Daily / Weekly bias as multi-timeframe confluence
**Status:** Not started
**Blocker:** None but lower priority
**Effort:** 1-2 days
**Files:** `ict_engine.py`, `adaptive_engine.py`

**Problem:** Current MTF stack = 4H bias / 1H trend / 5M execution.
Daily/Weekly bias never explicitly factored.

**Proposed:**
- Compute D1 EMA50/200 bias (BULL / BEAR / NEUTRAL)
- Compute W1 EMA20/50 bias
- Add `d1_aligned` / `w1_aligned` flags to signals
- Triple-aligned signals (D1 + 4H + 1H all same direction) get tier bonus

**Expected impact:** +1-2pp WR; better selectivity in chop.

---

## Tier 3 — DO AFTER 100+ closed paper signals

These require enough data to be statistically meaningful.

### T3.1 — Phase D.2 concept-drift CUSUM auto-pause
**Status:** Planned (see `docs/LIVE_BACKTEST_PARITY_ROADMAP.md:226, 513, 533`
+ `docs/ADAPTIVE_LEARNING.md:435`)
**Blocker:** 100+ closed signals required for CUSUM threshold calibration
**Effort:** 3-4 days
**Files:** `adaptive_engine.py`, `monitoring.py`

**Problem:** When market regime shifts (e.g., trending → ranging), strategy
edge degrades. Currently bot keeps firing signals until manual pause.

**Proposed:** CUSUM test on rolling WR over last N=20 closed signals vs
expected (from baseline CPCV). If cumulative deviation > threshold, auto-pause
learning + send Telegram alert.

**Expected impact:** Prevents 10-20% drawdown during regime shifts.

---

### T3.2 — Per-direction OGD pools (BUY vs SELL)
**Status:** Considered (see `docs/ADAPTIVE_LEARNING.md:433`)
**Blocker:** Need n≥30 per direction per token
**Effort:** 2-3 days
**Files:** `adaptive_engine.py` (schema change)

**Problem:** Current OGD weights are direction-agnostic. SELL signals on a
BEAR market and BUY signals on a BULL market might have different optimal
feature weightings.

**Proposed:** Separate weight vectors for `<token>_BUY` and `<token>_SELL`.
Doubles the weight table size but cleaner attribution.

**Expected impact:** +1-3pp WR; cleaner regime adaptation.

---

### T3.3 — Online feature importance / permutation testing
**Status:** Considered (see `docs/ADAPTIVE_LEARNING.md:436`)
**Blocker:** Phase 5B prerequisite, needs Phase D.2 first
**Effort:** 3-4 days
**Files:** `adaptive_engine.py`, new `feature_importance.py`

**Problem:** All 6 OGD features have equal initial weight. We don't know
which features actually matter. Phase 5B needs to know feature importance
to decide which features to specialize per template.

**Proposed:** Periodic (weekly) permutation importance test on recent N=50
signals. Features that contribute ≤2% to prediction get pinned at floor
weight; high-contribution features get expanded weight ceiling.

**Expected impact:** Cleaner OGD convergence; foundation for Phase 5B.

---

## Tier 4 — DO AFTER 480+ closed paper signals (~4 years at current rate)

These need substantial data to justify the complexity.

### T4.1 — Phase 5B per-template OGD weights ⭐ HIGHEST EVENTUAL IMPACT
**Status:** Planned (see `docs/ADAPTIVE_LEARNING.md:431`)
**Blocker:** n≥30 per (token, template) cell = 4 tokens × 4 templates × 30 = 480
signals
**Effort:** 1 week
**Files:** `adaptive_engine.py` (schema), `crypto_alert.py`, `monitoring.py`

**Problem:** Tier A signals (FVG aligned) probably have different feature
weights than Tier B (OB + MSS HIGH). Currently ONE weight vector per token.

**Proposed:** Separate weight table per (token, template). 40 weight vectors
total. Aggregated under the same OGD update rule but specialized priors.

**Expected impact:** +3-5pp WR via fine-grained learning.

---

### T4.2 — ML regime classifier (replace ADX-based regime detection)
**Status:** Not started
**Blocker:** Need 300+ signals across multiple regime types
**Effort:** 1-2 weeks
**Files:** new `regime_classifier.py`, `crypto_alert.py`

**Problem:** Current regime detection = 3-feature ADX-based (TRENDING_BULL,
RANGING, etc.). Could be ML classifier with 20+ features.

**Proposed:** Light gradient boosting model (sklearn) classifying market into
6 regimes using ATR / EMA slopes / RSI / volume / correlation. Cross-validated
quarterly.

**Why deferred:** Current ADX-based regime works fine empirically. ML adds
complexity without proven incremental edge.

---

### T4.3 — Contextual weights by (token × session)
**Status:** Not started
**Blocker:** Need n≥30 per (token, session) cell = 4 sessions × 10 tokens × 30 = 1200 signals
**Effort:** 3-4 days
**Files:** `adaptive_engine.py` (schema)

**Problem:** Asia killzone vs NY killzone have different liquidity. Same token
in Asia kazillzone might want different weights than in NY kazillzone.

**Proposed:** OGD weights keyed by (token, session) instead of just (token).
40 vectors total.

**Expected impact:** +1-2pp WR; smoother performance across sessions.

---

## Items I would NOT add (already considered, rejected)

| Feature | Reason rejected |
|---|---|
| Reinforcement learning (Q-learning, PPO) | Needs 100,000+ trades. Won't work at 96/year |
| LLM-based sentiment | Per `CLAUDE.md` operator preference — avoid LLM stuff |
| vectorbt / FinRL / hummingbot | Per `CLAUDE.md` — breaks parity, rejected libraries |
| Order book footprint chart | Requires sub-second tick data; infrastructure cost too high for $200 capital |
| Co-location near exchange | Overkill for swing strategy |
| News/social sentiment feed | LLM-adjacent, deferred indefinitely |

---

## Cross-reference summary

| Doc | Coverage |
|---|---|
| `docs/ENTERPRISE_ROADMAP.md` | Phase A/B/C completion status, Sprint structure |
| `docs/ADAPTIVE_LEARNING.md` § 13 (Future roadmap) | Phase 5B, Phase D.2, Bandit, per-direction, feature importance (5 items) |
| `docs/LIVE_BACKTEST_PARITY_ROADMAP.md` Phase D | CUSUM concept-drift implementation details |
| `docs/AUTONOMOUS_EXPLORER_DESIGN.md` | Optuna explorer (Tier 1-4 of THIS doc reference it for tuning) |
| **`docs/ENHANCEMENT_ROADMAP.md` (this file)** | **All strategy + AI improvements consolidated by tier** |

---

## Tracking discipline

When implementing any item from this roadmap:
1. Update status field in this file (Not started → In progress → Shipped)
2. Cross-reference the commit SHA in the status line
3. Add empirical results once 30+ post-ship signals close
4. If experiment fails (no measurable improvement), mark as ✗ Rejected with rationale

When new ideas surface:
1. Add to appropriate Tier (1=before LIVE, 2=after 30, 3=after 100, 4=after 480)
2. Cross-reference any related existing doc
3. Estimate effort + expected impact honestly

---

## Honest assessment as of creation (2026-05-28)

- **Bot is enterprise-grade quality TODAY** (9.30/10 audit, NEW ATH)
- **Primary blocker = paper data accumulation**, not algorithm sophistication
- **Tier 1 items add real edge without overfitting risk** — can be shipped now
- **Tier 2-4 require data the bot must EARN through paper trading**
- **No amount of additional ML/AI sophistication will substitute** for the
  empirical reality of n=30+ closed paper signals

The bot doesn't need more brains. It needs more chances to use the brains it has.
