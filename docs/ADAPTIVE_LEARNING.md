# TradeAI Adaptive Learning — Architecture & Operations

**Document type:** Canonical reference (single source of truth for the adaptive learning subsystem)
**Audience:** Operator, code reviewers, future Claude sessions
**Last updated:** 2026-05-26
**Maintainer:** Project owner; PRs welcome

---

## 1. TL;DR (read this first)

TradeAI's adaptive layer is **Online Gradient Descent (OGD)** with **per-token, per-feature** weight vectors. Six ICT structural features. Learning happens after every closed paper trade. Backtest uses default weights for CPCV statistical validity (H6 isolation); a parallel dual-track (Phase D.1) simulates live's OGD behavior chronologically to quantify the live↔backtest gap.

**What it IS:** classical online linear scoring (regression-flavored, not deep)
**What it is NOT:** neural network, reinforcement learning with replay, LLM, transformer, ensemble of trees

The "intelligence" is in the rule-based ICT detection engine (`ict_engine.py`). OGD only learns **which structural features matter most per token** at a given point in time.

---

## 2. Where adaptive learning lives in the system

```
┌─────────────────────────────────────────────────────────────────────┐
│                     SIGNAL GENERATION PIPELINE                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ict_engine.py   → sweep detection, MSS, FVG, displacement           │
│       ↓                                                              │
│  strategy_engine → gate evaluation (bias/trend/regime/DR/quality)    │
│       ↓                                                              │
│  ╔═══════════════════════════════════════╗                           │
│  ║   ADAPTIVE LAYER (adaptive_engine.py)  ║                           │
│  ║                                        ║                           │
│  ║  - extract_ict_feature_scores()        ║                           │
│  ║  - AdaptiveWeightEngine                ║                           │
│  ║    .get_weights(token)  ← scoring      ║                           │
│  ║    .update(outcome,...) ← learning     ║                           │
│  ║                                        ║                           │
│  ║  Backtest scoring: DEFAULT weights     ║                           │
│  ║  Live scoring:    learned token_weights║                           │
│  ╚═══════════════════════════════════════╝                           │
│       ↓                                                              │
│  Signal score → confidence integer → gate decision                   │
│       ↓                                                              │
│  Save signal + Telegram alert                                        │
│       ↓                                                              │
│  Operator manually executes trade (signal-only bot)                  │
│       ↓                                                              │
│  Trade closes → update() called → weights nudged                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. The model — OGD with per-token isolation

### 3.1 Per-token, per-feature weight vector

Each of the 10 supported tokens (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON) has its own 6-dimensional weight vector. The bot maintains them independently — what BTC's pattern teaches the model is not directly transferred to ETH (cross-token diversity is monitored to ensure they don't all converge to the same vector — see `monitoring.cross_token_diversity`).

### 3.2 The six features

Defined in `adaptive_engine.py:91`:

| Feature | Default weight | What it measures |
|---|---|---|
| `fvg_quality` | 0.25 | HIGH/MEDIUM/LOW grade of the Fair Value Gap (binding gate) |
| `mss_quality` | 0.20 | Market Structure Shift quality (5-point ICT rubric) |
| `confidence` | 0.20 | Integer confidence 5–10 from the rule engine |
| `trend_strength` | 0.15 | 1H trend alignment with signal direction |
| `session` | 0.15 | Killzone classification (LONDON / NY_AM / ASIA / OVERNIGHT) |
| `dr_location` | 0.05 | Dealing-range premium/discount location (currently a floor-pin candidate post Phase B revert) |

Weights are normalized so they sum to 1.0 after every update.

### 3.3 The OGD update rule

Per `adaptive_engine.AdaptiveWeightEngine.update()`:

```python
# Compute reward from outcome + actual P&L
reward = compute_reward(outcome, profit_pct)

# Skip if accumulating samples (warmup gate)
if n_seen[token] < OGD_MIN_SAMPLES:        # default 10
    n_seen[token] += 1
    return

# Decaying learning rate (high early, stable late)
lr = LR_FLOOR + (LR_INIT - LR_FLOOR) / (1.0 + n / DECAY_HALFLIFE)
   # LR_INIT = 0.06, LR_FLOOR = 0.01, DECAY_HALFLIFE = 100

# Momentum-smoothed gradient step per feature
for feature in FEATURES:
    score = feature_scores[feature]        # contribution this signal
    gradient = reward * score              # signed by reward
    velocity[feature] = MOMENTUM * velocity[feature] + lr * gradient
    velocity[feature] = clamp(velocity[feature], -MAX_STEP, +MAX_STEP)
                                            # MOMENTUM = 0.85
                                            # MAX_STEP = 0.04
    weight[feature] += velocity[feature]

# Clamp to [WEIGHT_MIN, WEIGHT_MAX] and renormalize to sum=1
weight[feature] = clamp(weight[feature], 0.05, 0.50)
weights = weights / sum(weights)
```

### 3.4 Reward signal

Per `_compute_reward()`:

| Outcome | Base reward | Notes |
|---|---|---|
| WIN | +1.0 | Full TP3 (or pre-TP3 close) |
| PARTIAL_TP2 | +0.6 | TP1 + half to TP2 |
| PARTIAL_TP1 | +0.4 | TP1 only, then BE stop |
| LOSS | −1.0 | SL hit |
| EXPIRED | −0.25 | 24h window expired with no fill |

When real P&L is available, reward becomes a 50/50 blend:
```
reward = 0.5 × base_reward + 0.5 × (profit_pct / 0.01)
       (the P&L term capped at ±2.0)
```

This way larger wins/losses earn proportionally larger gradient signals than the discrete bucket would imply.

### 3.5 Why OGD, not something fancier

| Alternative | Why not chosen |
|---|---|
| Deep neural network | Sample-starved (n<100 per token); networks need 10⁴+ samples to escape underfitting |
| Reinforcement learning (Q-learning, PPO, etc.) | Reward sparsity (~3-4 signals/month/token) makes credit assignment nearly impossible |
| Transformer / LLM | Latency, compute cost, opaque decisions, no edge case for the structured ICT feature set |
| Tree ensemble (XGBoost, LightGBM) | Requires batch retraining; doesn't naturally update online; less interpretable per-feature contribution |
| Bayesian linear regression | Closest mathematical cousin to OGD; OGD chosen for online-update simplicity + bounded weight envelope |
| Multi-armed bandits (Thompson sampling) | Considered for Phase 5B template selection; not appropriate for the feature-weight problem |

OGD's properties match the operational reality:
- **Online**: updates on every closed trade — no batch retraining cycle
- **Interpretable**: each weight is a per-feature importance number an operator can read
- **Bounded**: WEIGHT_MIN/WEIGHT_MAX + renormalization prevent runaway weights
- **Sample-efficient**: works meaningfully from n≥10 per token

---

## 4. Operational guardrails

The raw OGD update is augmented with safety mechanisms:

### 4.1 Warmup gate (`OGD_MIN_SAMPLES = 10`)
No weight updates fire until a token has accumulated 10 closed trades. Below that, scoring uses defaults. Prevents single-outcome overreaction during cold start.

### 4.2 Decaying learning rate
LR starts at 0.06 (fast adaptation) and decays to a floor of 0.01 (stability). Decay half-life ~100 signals. Early signals matter more; late signals refine.

### 4.3 Velocity clipping (`MAX_WEIGHT_STEP = 0.04`)
Per-update velocity magnitude is hard-capped at 0.04. Prevents a single high-reward extreme outcome from shifting weights by >20% in one step.

### 4.4 Weight envelope (`WEIGHT_MIN = 0.05`, `WEIGHT_MAX = 0.50`)
No feature can go silent (min 0.05) or dominate (max 0.50). After clipping, weights renormalize to sum=1.

### 4.5 Degenerate-weight guard (`DEGENERATE_THRESHOLD = 0.40`)
If any single feature weight exceeds 0.40 post-renorm, the token is flagged degenerate. Live scoring falls back to defaults for that token until rebalanced.

### 4.6 Decay-toward-default (every 30 min)
A gentle pull-back toward the uniform default. Counteracts noise drift and prevents long-term divergence. Tunable: `DECAY_RATE = 0.0004` per cycle (~82% retention per inter-signal gap).

### 4.7 7-day decay-suppression after update
Within 7 days of an OGD update, decay-toward-default is paused — preserves freshly learned signal. After 7 days of inactivity, decay resumes (assumes learning has gone stale).

### 4.8 Thin-sample bootstrap guard (`BOOTSTRAP_MIN_N_PER_TOKEN = 5`)
During bootstrap warm-start from backtest, tokens with <5 sample signals get DEFAULT_WEIGHTS forced + `_has_bootstrap=False`. Prevents masquerading "learned" weights when sample is too thin to mean anything.

### 4.9 Effective-sample tracking (`_n_effective`)
Each update accumulates `min(1.0, |reward|)` toward an effective sample count alongside the raw n. Phase A's stale-reject raised PARTIAL_TP1 share, and PARTIAL has reward 0.4 (vs WIN's 1.0). The diagnostic surfaces the gap; operator can see when raw n overstates real learning signal.

### 4.10 Cross-token diversity monitor
`monitoring.cross_token_diversity` computes average pairwise L1 distance between per-token weight vectors. Homogeneity alert if avg L1 < 0.20 → all tokens have collapsed to the same vector → likely degenerate.

---

## 5. Bootstrap warm-start

When live's `token_weights` table is empty (fresh deployment), the bot would need months of paper data before OGD activates. Solution: **bootstrap from backtest history**.

Workflow:
1. Each backtest run, after all signals are saved, `bootstrap_from_backtest()` is called
2. The function reads ALL historical `backtest_signals` rows (across all runs)
3. Runs the full OGD update sequence chronologically per token
4. Writes the resulting weights to `backtest_token_weights` table (separate from live `token_weights`)
5. On bot startup, if live `token_weights` is empty for a token, bootstrap value is loaded as warm start

Critical guards:
- Bootstrap writes to `backtest_token_weights`, never to live `token_weights` (H6 isolation)
- Degenerate-reject substitutes defaults for tokens whose bootstrap weights blow the 0.40 ceiling
- Thin-sample guard (M-J) preserves defaults for tokens with <5 bootstrap samples
- `_last_update_time` is seeded to bootstrap completion epoch (M-I) so the 7-day decay-suppression activates immediately

---

## 6. The H6 isolation (and why it exists)

### 6.1 The asymmetry

| Path | Scoring weights |
|---|---|
| Live signal scoring | learned `token_weights` |
| Backtest signal scoring | `DEFAULT_WEIGHTS` (uniform priors per feature defaults) |

### 6.2 Why this asymmetry exists

CPCV (Combinatorial Purged k-fold Cross-Validation, the primary verdict gate) requires **model parameters to be independent of test-fold data**. If backtest used OGD-learned weights, the weights' training history would include "future" data relative to the test folds (because CPCV reshuffles signals into non-chronological train/test splits). This breaks the independence assumption → DSR (Deflated Sharpe Ratio) becomes meaningless → selection-bias correction collapses.

The H6 fix (early 2026-05) isolated backtest scoring from learned weights to preserve CPCV validity.

### 6.3 Phase D.1 dual-track (2026-05-26): close the H6 quantification gap

The H6 isolation creates a known divergence between backtest WR (default weights) and live WR (learned weights). Original Phase D plan: validate the gap after 100+ paper signals accrue (~6 months).

Better solution shipped 2026-05-26: **two parallel validation tracks**:

| Track | Validation method | Weights used | Purpose |
|---|---|---|---|
| 1 | CPCV (combinatorial purged k-fold) | DEFAULT | Selection-bias correction, DSR |
| 2 | **WFV with OGD (Phase D.1)** | Sandboxed OGD simulation (`walk_forward.walk_forward_with_ogd`) | Live-parity expected performance |

Sequential walk-forward validation has NO data leakage even with adaptive weights (at signal time T, the model only knows what happened before T). Per López de Prado AFML §8: "The walk-forward backtest with adaptive parameters is the only honest predictor of live performance."

Every `python3 backtest.py` now produces both tracks. Operator sees:
- Track 1: "Is the strategy edge real?" → CPCV mean WR + DSR + verdict (PASS/MARGINAL/FAIL)
- Track 2: "What should live look like?" → WFV-OGD WR mean + parity verdict (STRONG_LIFT / WEAK_LIFT / NEUTRAL / INVERTED / INSUFFICIENT_SAMPLE)

The Phase D.1 verdict at small samples (no token >= OGD_MIN_SAMPLES) reads NEUTRAL — confirms H6 has zero practical impact below activation threshold. At larger samples, the verdict surfaces real divergence between learned and default scoring.

---

## 7. Data persistence

### 7.1 Database tables

| Table | Used by | Purpose |
|---|---|---|
| `token_weights` | Live runtime (`crypto_alert.py`) | Real-time scoring of new signals; updated on every closed trade |
| `backtest_token_weights` | Bootstrap warm-start (`adaptive_engine.bootstrap_from_backtest`) | Cold-start defaults derived from historical backtest signals; never used in CPCV scoring |
| `weight_history` | Forensic / monitoring | Every weight change (before/after) logged with `run_id` (post M-E fix) and `trigger` (per M-F grouping fix) for audit |

### 7.2 Schema sketch (token_weights)

```
token            TEXT      e.g. 'BTC'
feature          TEXT      one of {fvg_quality, mss_quality, session,
                                    confidence, trend_strength, dr_location}
weight           REAL      current normalized weight, clamped [0.05, 0.50]
velocity         REAL      EWMA of recent gradient steps (for momentum)
n_updates        INTEGER   count of OGD updates applied since bootstrap
updated_at       TEXT      ISO UTC timestamp
```

Composite primary key on `(token, feature)`.

### 7.3 Snapshot triggers in weight_history

| Trigger | When | Use |
|---|---|---|
| `signal_close` | After each closed trade's update() | Forensic — track per-update weight evolution |
| `bootstrap_before` | Start of `bootstrap_from_backtest()` | Diff against after to see bootstrap delta |
| `bootstrap_after` | End of `bootstrap_from_backtest()` | Bootstrap output state |
| `reset` | Operator-triggered weight reset (`crypto_alert.py:reset_token_weights`) | Audit trail for manual interventions |

---

## 8. Monitoring & observability

### 8.1 `monitoring.py`

Read-only audit tool. Detects:
- **Degenerate weights** — any feature > DEGENERATE_THRESHOLD (0.40)
- **Floor pins** — features stuck at WEIGHT_MIN (the Run-46 collapse fingerprint)
- **Low entropy** — Shannon entropy across the feature distribution
- **Stale weights** — no updates in > STALE_DAYS_THRESHOLD
- **Cross-token homogeneity** — pairwise L1 distance across tokens
- **Entropy drift** — change in per-token entropy across recent snapshots

CLI:
```bash
python3 monitoring.py --text                  # human-readable report (default: live table)
python3 monitoring.py --source bootstrap      # audit bootstrap pool (OGD-MON-SCOPE fix)
python3 monitoring.py --json output.json      # machine-readable
python3 monitoring.py --prometheus            # Prometheus metrics
python3 monitoring.py --exit-on-crit          # exit code 2 if global=CRIT (CI-friendly)
```

### 8.2 Dashboard

The TradeAI dashboard (`tracker.py`, port 8888 via SSH tunnel) surfaces:
- Per-token current weight bar chart
- Weight history sparkline (last N updates)
- Degeneracy / pin / stale flags
- Bootstrap vs live divergence (when both populated)

### 8.3 Per-update logs

Every OGD update logs:
```
[ADAPTIVE] BTC OGD #15 outcome=WIN reward=+1.00 delta=0.0234 n=15/10+ n_eff=12.4
  | fvg_quality:0.252->0.261  mss_quality:0.198->0.196  ...
```

Visible in `journalctl -u tradeai -f` real-time.

---

## 9. Configuration knobs

All env-overridable via `.env`:

```bash
# Engine constants (adaptive_engine.py)
LEARNING_RATE_INIT=0.06
LEARNING_RATE_FLOOR=0.01
LEARNING_RATE_DECAY=100
MOMENTUM=0.85
WEIGHT_MIN=0.05
WEIGHT_MAX=0.50
MAX_WEIGHT_STEP=0.04
DEGENERATE_THRESHOLD=0.40
OGD_MIN_SAMPLES=10
BOOTSTRAP_MIN_N_PER_TOKEN=5

# Risk integration
_RISK_PER_TRADE_PCT=0.01
_MAX_POSITION_PCT=0.20
_MAX_PORTFOLIO_RISK_PCT=0.03
_MAX_DRAWDOWN_PCT=0.10           # LIVE; PAPER uses 0.20

# Monitoring thresholds (monitoring.py)
ENTROPY_DRIFT_ALERT=0.10
ENTROPY_DRIFT_CRIT=0.20
ENTROPY_DRIFT_LOOKBACK=10
STALE_DAYS_THRESHOLD=21
HOMOGENEITY_THRESHOLD=0.20
FLOOR_PIN_CRIT_COUNT=3
```

---

## 10. Operational scenarios

### 10.1 New deployment, zero paper data

1. `crypto_alert.py` boots, loads `token_weights` → empty
2. Checks `backtest_token_weights` for warm-start values
3. If backtest_token_weights has bootstrap weights, loads them
4. If neither available, uses `DEFAULT_WEIGHTS` for all 10 tokens
5. Generates signals using whichever weights are active
6. First closed trade triggers `update()` → token's n_seen += 1 → still in warmup
7. After 10 closed trades per token, OGD activates

### 10.2 Token degenerates (single feature blows ceiling)

1. `_check_degenerate(token_weights)` returns True with worst_feat=fvg_quality, val=0.45
2. Logged: `[ADAPTIVE] BTC weights DEGENERATE — fvg_quality=0.45 > 0.40`
3. Live scoring path for BTC falls back to `DEFAULT_WEIGHTS`
4. `monitoring.py` reports BTC = CRIT, dashboard flags red
5. Operator triages: continue (likely just thin-sample noise) or reset via `reset_token_weights(token='BTC')`

### 10.3 New baseline promoted, bootstrap re-runs

1. Operator promotes a new config via `scripts/promote_baseline.py`
2. New backtest runs at the new baseline
3. `bootstrap_from_backtest(run_id=current_run)` executes (M-E fix: run_id properly threaded)
4. New bootstrap weights written to `backtest_token_weights`
5. Live continues using its current `token_weights` (no immediate change)
6. If operator wants to reset live to the new bootstrap, runs `crypto_alert.py:apply_bootstrap_warmstart()` manually

### 10.4 Bot restarts mid-cycle (e.g., `systemctl restart tradeai`)

1. SIGTERM handler (M-C fix, cycle-4) sets `_SHUTDOWN_REQUESTED=True`
2. Current cycle completes (heartbeat + state_store save flush before exit)
3. Telegram "STOPPED — SIGTERM received" sent
4. New process starts, loads `token_weights` from DB (atomic — no half-written state)
5. Resumes from last checkpoint

---

## 11. Validation & honesty checks

### 11.1 What protects against learning the wrong thing

| Risk | Guardrail |
|---|---|
| Single extreme outcome dominates | `MAX_WEIGHT_STEP = 0.04` velocity clip |
| Long-term drift without supervision | Decay-toward-default every 30 min |
| Bootstrap pool contaminated | Degenerate-reject substitutes defaults |
| Sample-starved token learns noise | OGD_MIN_SAMPLES + BOOTSTRAP_MIN_N_PER_TOKEN |
| Same pattern across all tokens (data leakage) | Cross-token L1 diversity monitor |
| Float-equality bug masquerading as "bootstrapped" | `n_bootstrap > 0` check (M-J chain) |
| Forensic queries impossible | weight_history.run_id properly threaded (M-E fix) |
| Decay turning off newly-learned weights | 7-day decay-suppression after update |
| Backtest scores diverge from live silently | Phase D.1 dual-track (this codebase, 2026-05-26) |

### 11.2 Honest interpretation of metrics

- `n_updates` is the raw closed-trade count for the token. **Not all of those produced gradient signal** — see `n_effective` below.
- `n_effective` is the sum of `|reward|` per update (capped at 1.0 each). Closer to "effective sample count" for gradient updates. PARTIAL outcomes weighted at 0.5, EXPIRED at 0.25.
- `is_degenerate` reports whether any feature blew the 0.40 ceiling. Triggers fallback to defaults.
- Reading per-token weights: large dispersion across tokens (avg L1 ≥ 0.20) means tokens have differentiated; tight homogeneity (avg L1 < 0.20) means tokens have converged onto a similar pattern → may indicate market-wide regime dependence rather than per-token edge.

---

## 12. What this learning system is NOT

To avoid mis-selling expectations:

- **Not a learning system that figures out the strategy.** The ICT rule engine (`ict_engine.py`) generates the signals. OGD only reweights the post-hoc quality assessment.
- **Not a price predictor.** No price targets are learned. SL/TP placement is rule-based from FVG / liquidity levels.
- **Not RL with replay.** No Q-values, no experience buffer, no exploration policy — just per-feature linear weights.
- **Not a substitute for honest validation.** OGD adapts; CPCV + DSR audit; held-out lockbox verifies. Three independent layers.
- **Not LLM-anything.** No prompt engineering, no transformer, no GPT API.
- **Not "trained on millions of trades."** Sample sizes here are n=10-50 per token. Everything is engineered around that constraint.

---

## 13. Future roadmap

| Item | Status | Blocker |
|---|---|---|
| Phase 5B — per-template OGD (separate weight vector for Tier A / B / C) | Planned | Need n≥30 per (token, template); not achievable until paper accumulates |
| DSR-aware learning gate — suppress OGD when latest CPCV-OOS says FAIL | Planned (L-H) | Hookup exists post Phase C `cpcv_summary_split`; simple integration |
| Per-direction (BUY/SELL) weight pools | Considered | Schema change; medium complexity |
| Gradient clipping at ±0.005 per update | Considered | Currently MAX_WEIGHT_STEP=0.04 handles this; tighter clip = slower convergence |
| Phase D.2 — concept-drift auto-pause (CUSUM) | Planned | Requires 100+ closed paper signals |
| Feature importance / permutation testing | Considered | Phase 5B prerequisite — quantify which of the 6 features carries real signal |
| Multi-armed bandit (Thompson sampling) for template selection | Considered | Phase 5B alternative; better at low n than per-template OGD |

---

## 14. File map

| File | Role |
|---|---|
| `adaptive_engine.py` | Core OGD engine: `AdaptiveWeightEngine`, `extract_ict_feature_scores`, `bootstrap_from_backtest`, `_compute_reward` |
| `crypto_alert.py` | Live integration: scoring at signal time, update() call after close, reset path |
| `backtest.py` | Backtest integration: H6-isolated scoring with DEFAULT_WEIGHTS, bootstrap call after run completes |
| `walk_forward.py` | Phase D.1 dual-track: `walk_forward_with_ogd` simulates chronological OGD for live-parity verdict |
| `monitoring.py` | Read-only audit: degeneracy detection, floor pins, entropy drift, cross-token diversity |
| `tracker.py` + `tracker_html.py` | Dashboard surface for weights + history |
| `tests/test_monitoring.py` | Unit tests for monitoring formulas + thresholds |

---

## 15. References

### Internal docs
- `docs/comprehensive/CROSS_REF.md` — every audit finding's status (H6, H8, H9, M14, etc.)
- `docs/LIVE_BACKTEST_PARITY_ROADMAP.md` — Phase A/B/C/D timeline and rationale
- `docs/adaptive_tunebot/PHASE_1_ADAPTIVE_FOUNDATION_IMPLEMENTATION_REPORT.md` — original Phase 1 build
- `docs/audits/AUDIT_2026-05-22_strategy_and_adaptive.md` — original adaptive audit
- `.claude/reports/tradeai-audit/` — every multi-agent audit (cycles 1-5 to date)
- `.claude/agents/adaptive-learning-code-reviewer.md` — reviewer subagent contract
- `.claude/agents/ogd-weight-inspector.md` — weight-state inspector subagent contract

### External references
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. (CPCV, embargo, H6 logic)
- Bailey & López de Prado (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management*. (DSR formula; T must = per-Sharpe observation count — cycle-4 C-NEW-1 fix)
- Bottou, L. (1998). "Online algorithms and stochastic approximations." *Online Learning and Neural Networks*, Cambridge University Press. (OGD foundations)
- Hazan, E. (2016). *Introduction to Online Convex Optimization*. (Modern OGD treatment)

---

## 16. FAQ

**Q: Why per-token weights instead of one global model?**
Token-specific market microstructure (BTC orderbook ≠ ALT orderbook). What predicts a BTC reversal isn't necessarily what predicts an ALT reversal. Per-token also gives operator forensic visibility — "BTC's fvg_quality weight rose to 0.30; ALT's stayed at default" reveals per-token patterns.

**Q: Why 6 features and not more / fewer?**
6 was the minimum that captured the structural ICT dimensions: setup quality (fvg + mss), context (session + trend_strength), confluence (confidence), and location (dr_location). Adding more dilutes gradient signal; fewer collapses information.

**Q: What's the difference between confidence (a feature) and the integer confidence score (5-10) downstream?**
The OGD `confidence` feature is the normalized [0,1] score derived from the integer. The integer is what the rule engine emits before OGD reweights it. M13 KNOWN STRUCTURAL: there's a mild second-order loop here (confidence-as-feature is partly derived from features) — accepted under current hyperparameters; Fix A (remove confidence from FEATURES) deferred.

**Q: Will live ever surprise the operator vs backtest?**
Phase D.1 says NEUTRAL right now (n<10 per token → defaults still active). As paper signals accumulate, the parity verdict will shift. STRONG_LIFT = live should outperform backtest; INVERTED = investigate. Operator should monitor the parity verdict every backtest.

**Q: Can I disable OGD entirely?**
Yes — set `OGD_MIN_SAMPLES=999999` in env. Or empty the `token_weights` table; bot falls back to defaults. Reversible via env var change + restart.

**Q: What happens if the bot crashes mid-update?**
Atomic state writes (`_persist_token` uses `INSERT OR REPLACE` within a single transaction). At worst, the in-flight update is dropped — the previous valid state is the next-load reference. No corruption.

**Q: Can two tokens share learnings?**
No — explicit design. Cross-token homogeneity is an ALERT signal, not a feature. If you ever wanted cross-token transfer, it would be a major architectural shift (multi-task learning, shared embedding, etc.). Not in scope.

---

**End of canonical adaptive learning reference. Last updated 2026-05-26 post Phase D.1 dual-track shipment.**
