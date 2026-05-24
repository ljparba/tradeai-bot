# TradeAI End-to-End Audit — Strategy Correctness + Adaptive Learning

**Date:** 2026-05-22
**Scope:** Two-dimension audit covering (1) ICT strategy implementation correctness and live-vs-backtest parity, (2) OGD adaptive learning correctness.
**Method:** 9 specialized subagents executed in parallel (ict-logic-validator, live-backtest-consistency-checker, backtest-bias-detector, risk-management-auditor, config-consistency-validator, ogd-weight-inspector, adaptive-learning-code-reviewer, signal-performance-analyzer, template-tier-calibrator). No code modified.

---

## Strategy Implementation Scorecard

| # | Component | Correct per ICT? | Live=Backtest? | Improvement Available? |
|---|-----------|------------------|----------------|------------------------|
| 1 | Liquidity sweep detection | PARTIAL — wick+reclaim mechanic is correct (`ict_engine.py:66-98`) but no EQH/EQL clustering, no IRL/ERL distinction | YES — same `ICT_SWEEP_LOOKBACK=30`, same `consumed_sweeps` dedup (`backtest.py:481`) | YES — add EQH/EQL clustering for sweep-target quality |
| 2 | MSS quality scoring | PARTIAL — displacement body scored, but break does NOT require displacement candle; CHoCH vs BOS unlabeled (`ict_engine.py:144-219`) | YES — same `ICT_MSS_HORIZON=30` both sides | YES — require breaking candle to be displacement candle; tag CHoCH vs BOS |
| 3 | FVG detection / mitigation | PARTIAL — 3-candle pattern correct; mitigation uses outer edge (not 50%, intentional Run-41 revert per CROSS_REF M4); freshness removed | YES — `score_ict_fvg` same on both sides (`ict_engine.py:227-298`) | YES — restore freshness tier (≤4 bars = +1) |
| 4 | iFVG | YES — inversion + spatial gate (`ict_engine.py:543-663`) C3/M7 verified | YES — `ICT_IFVG_PROXIMITY_PCT=0.03` both sides | YES — add HTF (1H/4H) iFVG scan alongside 5M |
| 5 | Dealing range classification | YES — swing-derived, 50% midpoint correct, ±5% equilibrium band (`ict_engine.py:383-426`) | YES with caveat — `dealing_range_gate=True` LIVE / `False` BACKTEST (DR-1 KNOWN STRUCTURAL, live stricter) | LOW — already canonical |
| 6 | Killzone timing | PARTIAL — uses Huddleston "Judas Swing" 02-04 UTC labeled LONDON_KZ, not canonical 07-10 UTC (`adaptive_engine.py:63-79`). No DST. Canonical London Open (07-10 UTC) scores 0. | YES — same `_utc_to_session` function imported both sides | YES — re-add canonical London Open (07-10 UTC) tier OR rename to JUDAS_SWING_KZ honestly |
| 7 | SMT divergence | YES — confirmed-swing reference, two-horizon design (`ict_engine.py:476-540`); SMT gate currently OFF (advisory) | YES — same lookbacks both sides | LOW — gate is off; data showed SMT anti-predictive (Run 48), penalty -0.10 retained correctly |
| 8 | Order block detection | **NO — not implemented anywhere.** `grep order_block` zero hits | N/A | YES — HIGH impact, this is the largest canonical-ICT gap |
| 9 | Entry trigger sequencing | PARTIAL — order check is only `mss_bar > sweep_bar` (`crypto_alert.py:2207`). FVG built on `disp_bar` (line 2187) BEFORE MSS check (line 2201). FVG can sit pre-MSS without rejection | YES — same loose enforcement both sides | YES — enforce `mss_bar >= disp_bar` and FVG on MSS bar |
| 10 | Stop-loss placement | YES — structural, 0.3% beyond swept wick, `MIN_SL_PCT=0.005`, `MAX_SL_PCT=0.030` (`ict_engine.py:666-752`) | YES — same logic | LOW |
| 11 | Take-profit / R:R targeting | PARTIAL — TP1/TP2 liquidity-driven (good); TP3 fixed 3R (not ICT). PDH/PDL and DR_MID removed. Session-H/L uses hours (17,13,8,0) that **don't match** killzone hours (20,13,2) — internal inconsistency (`ict_engine.py:452-459`) | YES — same fn both sides | YES — align session-H/L source hours with killzone hours |
| 12 | Position sizing + portfolio caps | YES — risk-pct based, 20% notional cap (H14 VERIFIED FIXED), portfolio layer with `MAX_OPEN_POSITIONS=4`, `MAX_SAME_DIRECTION=2`, `MAX_PORTFOLIO_RISK_PCT=0.03` (`adaptive_engine.py:111-121`) | NO — backtest doesn't simulate portfolio caps (M11 KNOWN STRUCTURAL); will reduce live signal yield once LIVE caps lower from PAPER 20/10 to 4/2 | YES — simulate caps in backtest to quantify yield drop |
| 13 | Fee + slippage assumptions | PARTIAL — 0.30%/0.50% per-token round-trip cost (M15 fixed); **NO explicit slippage model** in either backtest or live; `grep slippage` zero hits in `crypto_alert.py` | YES — both use `TOKEN_RT_COST[token]` map | YES — add adverse-slippage model for sweep-bar fills (especially HBAR/POL alts) |

---

## Adaptive Learning Scorecard

| # | Question | Answer | Evidence (file:line or DB query) |
|---|----------|--------|----------------------------------|
| 1 | Does the bot ACTUALLY learn from past trades? | **NO — COSMETIC.** Zero live trades exist. All weight movement is bootstrap from backtest replay or test snapshots. | `SELECT COUNT(*) FROM signals` → 0; `SELECT COUNT(*) FROM results` → 0; `DISTINCT trigger FROM weight_history` shows only `bootstrap_*`, `test_*`, `reset` — no `live_update` row ever |
| 2 | Per-template weight isolation (Phase 5B)? | **NO — NOT IMPLEMENTED.** Schema is `(token, feature)` only. Cross-template poisoning is structurally possible. | `adaptive_engine.py:153-161` PRIMARY KEY (token, feature) — no `template_id` column; `Grep template_token_weights` → no matches; PHASE_STATUS.md:110-128 confirms 5B NOT STARTED |
| 3 | Learning rate calibrated correctly? | **NO — EFFECTIVELY SPENT.** Test snapshots contaminated `n_updates` (XRP=2755, AVAX=1500, BTC=1459). LR formula `0.01 + 0.05/(1+n/100)` → effective LR ~0.012 for 6/9 tokens before first real signal | `adaptive_engine.py:37-50`; `SELECT token, n_updates FROM token_weights`; `tests/test_adaptive_snapshot.py:90` writes to production DB |
| 4 | Converging / diverging / stuck? | **STUCK** for 9/9 live-tracked tokens. XRP `fvg_quality` frozen at 0.217081 for 17+ hours; 130+ identical bootstrap_after snapshots | `SELECT recorded_at, weight_after FROM weight_history WHERE token='XRP' AND feature='fvg_quality' ORDER BY recorded_at` |
| 5 | Degenerate states? | **6 of 7 backtest-warmstart tokens near-degenerate.** `dr_location` ~0.45-0.53 with 3-4 features at WEIGHT_MIN floor (ETH, HBAR, LINK, POL, SOL, AVAX). All pass the lenient 0.60 hard threshold so degenerate-fallback NEVER triggers — **PARTIAL REGRESSION of M14** | `SELECT token, feature, weight FROM backtest_token_weights WHERE weight > 0.40 OR weight < 0.06`; `adaptive_engine.py:48` `DEGENERATE_THRESHOLD=0.60`; `crypto_alert.py:2074-2078` |
| 6 | Look-ahead-free features only? | **YES — CLEAN.** All 6 features use closed bars (`[:-1]` slicing). `feature_scores_json` persisted at signal-emit time, reused unchanged at close time | `crypto_alert.py:2108-2112`, `crypto_alert.py:1177-1192` |
| 7 | Demonstrable WR improvement over time? | **UNMEASURABLE.** N_live_closed = 0. Apparent 37% → 82% WR jump runs 33→76 is **manual filter tightening (90.6% signal rejection)**, not learning | `backtest_runs` runs 33 (20% WR n=42) → 76 (79.5% WR n=39); `weight_history` 0 actual weight changes from `test_actual` trigger |
| 8 | Backtest seeds initial weights correctly? | **PARTIAL.** `bootstrap_from_backtest()` writes to isolated `backtest_token_weights` (H6 verified). But `_load_all()` gate `n_updates == 0` blocks warm-start for 9/9 live tokens (stale counters from test pollution) — they remain on frozen old snapshots, not on current bootstrap | `backtest.py:2566-2568`; `adaptive_engine.py:298-312` |
| 9 | Drift guardrail capping weight movement from backtest baseline? | **NO — ABSENT.** Only bounds are per-feature `WEIGHT_MIN=0.05`/`WEIGHT_MAX=0.50` and per-step velocity clip `MAX_WEIGHT_STEP=0.04`. `decay_toward_default()` pulls to **uniform DEFAULT_WEIGHTS**, not to the backtest-fitted prior | `adaptive_engine.py:649-668` — `dw = DEFAULT_WEIGHTS`, not `backtest_token_weights[token]` |

**Additional findings from learning-side agents:**
- `tracker.py:1559` manual-close path drops `profit_pct` arg to `weight_engine.update()` — manual closes lose proportional P&L scaling
- M13 confidence circular feedback acknowledged structural — `eff_weights["confidence"]` is being updated by a derivative of itself

---

## Top 5 Concrete Improvements (ranked by expected edge gain)

### 1. Fix 1H EMA200 unconverged data window in live (C-N3)
- **What:** Raise `TIMEFRAMES["1h"]["limit"]` from 210 to ~700 bars so EMA200 converges identically to backtest (which has 8,760 bars)
- **Where:** `crypto_alert.py:97`
- **Expected impact:** Eliminates a silent live/backtest divergence in `trend_1h` classification that today can flip BULL↔STRONG_BULL↔NEUTRAL between the two paths. Restores backtest as a valid predictor of live trend gating.
- **Overfitting risk:** ZERO — pure numerical convergence fix

### 2. Reset polluted `token_weights.n_updates` and isolate test DB
- **What:** (a) One-time `UPDATE token_weights SET n_updates=0` (preserves weights); (b) re-route `tests/test_adaptive_snapshot.py:90,288,321` through a temp DB by monkey-patching `adaptive_engine.DB_PATH`; (c) optionally count only `trigger='live_update'` rows for sample_count
- **Where:** `adaptive_engine.py:27`, `tests/test_adaptive_snapshot.py:90`
- **Expected impact:** Restores ~5× LR responsiveness to first 50 live signals. Without this, OGD is effectively frozen at floor-LR before paper trading even begins.
- **Overfitting risk:** ZERO — this is removing a measurement artifact, not training on more data

### 3. Tighten DEGENERATE_THRESHOLD and promote M14 soft alert to hard fallback
- **What:** Lower `DEGENERATE_THRESHOLD` from 0.60 to 0.40 OR promote the existing 3×-default soft alert (`adaptive_engine.py:611-621`) to a hard runtime fallback in `crypto_alert.py:2074-2078`
- **Where:** `adaptive_engine.py:48`
- **Expected impact:** 6 of 7 backtest-warmstart tokens currently have `dr_location` ~0.45-0.53 (10× the default of 0.05) but pass the 0.60 threshold. Live signals on those tokens are currently using anti-aligned-DR-inflated weights silently.
- **Overfitting risk:** LOW — this is a safety bound, not a learning signal

### 4. Replace 2 non-discriminating Tier-A confluences with FVG=HIGH + REACTION_CONFIRMED×killzone
- **What:** In Tier A definition, drop `MSS=HIGH` (99.5% Tier-A satisfaction — decorative) and DR-alignment (97.1% — decorative). Replace with `FVG quality = HIGH` only (70.6% WR vs 31.9% at FVG=MEDIUM — 38pp gap) and a compound `session∈killzone × entry=REACTION_CONFIRMED`. Move Tier A to 5/5 requirement.
- **Where:** `strategy_templates.py:125-158`
- **Expected impact:** Widens Tier A vs Tier B WR delta from current 11.9pp (71.7% vs 59.8%) to plausibly 18-22pp. Cost: halves Tier A volume.
- **Overfitting risk:** MEDIUM — selected from in-sample dim tables; should be re-validated against the locked OOS set

### 5. Reconcile BTC filter logic (C-N1) and add 1H limit fix as a bundle pre-LIVE
- **What:** Live's BTC filter is dom-direction conditional and **never blocks SELL on BTC bull** (`crypto_alert.py:1596-1644`); backtest blocks any opposed-trend BTC (`backtest.py:705-711`). Pick one canonical filter (recommend: live's dom-aware BUY block + symmetric SELL block on BTC bull dom_FALLING) and use it on both sides.
- **Where:** above + same area
- **Expected impact:** Removes the largest bidirectional bias making backtest WR an unreliable live predictor. Currently backtest understates live BUY WR in bear and overstates live SELL WR in bull.
- **Overfitting risk:** LOW — this is reconciling two existing rules, not adding a new gate

---

## Verdict

**Strategy: NEEDS WORK.** The detection primitives that exist are mechanically correct and well-fixed (76+ items in CROSS_REF verified). But three structural gaps materially reduce the system's claim to be "real ICT":
1. No Order Block detection at all — the primary canonical ICT PD-array is missing
2. Entry trigger sequence is not strictly enforced — FVG can sit pre-MSS without rejection
3. Killzone labels disagree with canonical ICT hours (Judas Swing 02-04 UTC is labeled LONDON_KZ; the canonical 07-10 UTC London Open scores 0)

Overall ICT correctness ≈ 6.5/10.

**Adaptive learning: COSMETIC.** The OGD plumbing is mathematically correct, persistence is wired, bootstrap from backtest fires (H6), and look-ahead is clean. But:
- `N_live_closed = 0`
- Test snapshots have polluted live `n_updates` counters into the thousands
- LR is effectively at-floor before the first real trade
- Weights are stuck for 17+ hours
- Manual-close path drops `profit_pct`
- Phase 5B per-template isolation is unimplemented

The system *can* learn once it sees live data and the test pollution is purged; today, it is plumbing without a signal.

**Backtest validity: OPTIMISTIC + FRAGILE (4/10 bias rating).** Core ICT detection has no lookahead, but the meta-process compromises results:
- Weekday gate selected in-sample (Tue/Wed/Sat blocked from observed 0%/4 WR)
- Token universe pruned by in-sample WR (SOL/DOT/NEAR/LTC removed)
- 76+ sequential optimization runs on the same 365-day data
- Post-TP1 implicit breakeven assumption
- PARTIAL_TP1 counted as full win in WR (backtest) vs 0.5 weight in tracker.py (live divergence)

Realistic OOS WR estimate: **55-65%** (vs reported 79.5%).

**Risk management: 5/10 — NOT safe for LIVE today.** Position sizing and structural SL are sound. But:
- Daily-loss kill switch and drawdown formula both have dimensionally-inconsistent units (`profit_pct * RISK_PER_TRADE_PCT` — PARTIAL REGRESSION of C7 propagated to `adaptive_engine.py:1040`)
- Correlation guard is warning-only (3 correlated longs allowed during a BTC cascade)
- `YOUR_CAPITAL` never updates to reflect account changes
- No flash-crash / spread filter for HBAR/POL alts

**Config consistency: 10/10.** Single source of truth pattern (`strategy_engine.py` co-located configs, `ict_engine.py` shared constants, `BINANCE_TOKENS` imported not duplicated). All divergences pre-classified KNOWN STRUCTURAL (DR-1, C4, CF-1, M11). Zero unclassified drift detected. The M24 class of bug is structurally prevented.

---

| Question | Answer |
|----------|--------|
| **Strategy** | NEEDS WORK |
| **Adaptive learning** | COSMETIC |
| **Safe to keep paper trading?** | **YES** — paper trading is exactly what's needed; the system has 0 live signals and cannot self-validate without them. Run paper for 60-90 days to accumulate ≥50 closed signals before any LIVE consideration. |
| **Safe to go LIVE today?** | **NO** |

### LIVE blockers (must fix before flipping LIVE_CONFIG)

1. **CRIT-1 / CRIT-2 risk formula:** Fix dimensional inconsistency in daily-loss (`crypto_alert.py:966`) and drawdown (`adaptive_engine.py:1040`) — kill switches currently fire at wrong thresholds
2. **C-N3 1H EMA200 unconverged in live:** Raise limit from 210→700 bars
3. **C-N1 BTC filter divergence:** Reconcile live (dom-aware, never blocks SELL) vs backtest (blocks both directions)
4. **OGD pollution reset:** Zero `token_weights.n_updates` once + isolate `test_adaptive_snapshot.py` to temp DB
5. **DEGENERATE_THRESHOLD tightening:** Promote M14 soft alert to hard fallback so the 6/7 near-degenerate `dr_location`-inflated tokens don't ship to live
6. **N_live_closed must reach ≥50** with measured WR consistent with backtest claims, before increasing position sizes from PAPER caps to LIVE caps (4 positions / 2 same-direction)
7. **Slippage / spread filter:** Add `if spread_pct > TOKEN_RT_COST[token]: return None` for HBAR/POL alts
8. **Correlation guard:** Make blocking at ≥3 correlated same-direction positions (not warning-only)

---

## Overall Assessment

The bot's foundation is genuinely strong:
- Config discipline (10/10)
- Persistent risk-fix archaeology (CROSS_REF tracking)
- Mathematically sound OGD framework
- Clean look-ahead protection
- Sound position sizing and structural SL

The current state is **"well-engineered scaffolding without operational signal."** Paper trading is the right next phase; LIVE is not.
