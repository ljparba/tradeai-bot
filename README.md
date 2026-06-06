# TradeAI — Project Overview (breakout-thesis branch)

> Read-only project overview, generated from what is actually in the repo (the `*.md`
> reports, configs, and commit history). Every number is cited from a report file —
> nothing invented. This branch (`breakout-thesis`) layers the Phase-C breakout
> exploration on top of the production ICT signal bot. The full production-bot
> reference (the prior README) is retained verbatim in **Appendix A** below.

---

## 1. Purpose

TradeAI is a **signal-only** ICT (Inner Circle Trader) crypto bot: it detects setups on
12 large-cap tokens (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON, ATOM, BCH),
backtests them with honest statistics (Combinatorial Purged k-Fold CV + Deflated Sharpe
Ratio), forward-validates in 24/7 PAPER soaks, and only sends Telegram alerts — the
operator executes every trade manually, and **LIVE never auto-flips**. The Phase-C goal on
this branch is to determine, with pre-registered, out-of-sample-honest discipline, whether
an **H4 breakout / continuation** strategy ("Config 14") has a real, live-portable edge —
and to understand the tokens' behaviour well enough to read the forward soaks correctly.

---

## 2. Strategy history (each line cites its report file)

| Experiment | What was tested | Result (numbers) | Verdict |
|---|---|---|---|
| **Breakout Config 14 — Step 1 (clean grid)** `PHASE_C_BREAKOUT_REPORT.md` | Pre-registered TP/lookback grid, H4 break + 5M MSS + FVG/OB | Best cfg n=2511, avg_R **+0.682**, sum_R +1711, PF 3.19, DSR 1.00 | **PASS** (clean) |
| **Step 2A — friction screen** `PHASE_C_STEP2A_FRICTION.md` | Does +0.72 survive spread/slippage/partial fills, 365d, run once | Friction-on avg_R clearly positive, PF > 1.5 | **PASS → paper soak authorized** |
| **Timeframe comparison (A/B/C)** `PHASE_C_TIMEFRAME_COMPARISON.md` | 5M/4H vs 5M/1H vs 1M/1H, CPCV+DSR | A avg_R **+0.759**, PF 3.71, n=410, DSR 1.00; B +0.66 but 2.8× signals (+607 R); C middle | All **PASS**; **no live-switch recommended** |
| **720d multi-regime stress** `PHASE_C_720D_BACKTEST.md` | Edge vs more data + per-regime | TF_B improved monotonically **+0.549 → +0.634 → +0.640**; most regimes above the +0.40 gate | **Validated (robust to regime)** |
| **Exit-model divergence** `EXIT_MODEL_VERIFICATION.md` | Soak's premature-close vs backtest exit | Premature close would convert avg_R **+0.72 → +0.02** | **Bug — fixed** (commit `870c7f4`) |
| **Runner-exit gap (post-TP1)** `RUNNER_EXIT_GAP.md` | Post-TP1 runner had no stop (unrealistic) | Moved SL→entry after TP1 (BE); drag −0.004 / −0.009 R | **Fixed** (BE-after-TP1, `ae46c1d`) |
| **Post-TP2 trail-to-TP1** `EXIT_MODEL_VERIFICATION.md` / commit `a526ca5` | Add trailed stop to TP1 after TP2 (last runner gap) | Honest avg_R drops ~0.12 → TF_B **+0.484 → +0.3644**, TF_A → +0.3376 (now **below the +0.40 gate floor**) | **Shipped (live-portable); edge now marginal** |
| **TP-geometry experiment (5 variants)** `TP_GEOMETRY_EXPERIMENT.md` | Pre-registered 5 TP-RR variants, OOS + deflated DSR | On primary TF_B **no variant cleared OOS test ≥ +0.40** (best 0.396) | **REJECTED — no qualifying geometry** |
| **Regime / trend filter** `PHASE_C_REGIME_FILTER.md` | Filter counter-trend signals (1 pre-registered trial) | avg_R improves only **+0.013–0.018**; sum_R drops **27–29%** | **REJECTED — hypothesis fails** |
| **Mean-reversion property** `MEAN_REVERSION_EXPLORATION.md` | Variance-ratio / autocorr, 12 tokens, 5m+1h | **1H = random walk (VR≈1.00)**; 5m VR<1 is microstructure (AVAX/TON) that vanishes at 1H | **No tradeable property; would duplicate the fade** |
| **Volume bucketing** `VOLUME_BREAKDOWN.md` | avg_R by breakout-bar volume (causal) | **Inverted, OOS-robust**: LOW +0.469 > NORMAL +0.421 > HIGH +0.297 (TF_B) | **Information, but not a filter case** |
| **Trend alignment** `TREND_ALIGNMENT_BREAKDOWN.md` | WITH vs AGAINST 1H/4H trend (causal) | WITH +0.415 > AGAINST +0.307 (TF_B, holds OOS) but **counter-trend still +0.30 R profitable** | **Not a filter case** |
| **Session / VWAP** `SESSION_BREAKDOWN.md`, `SESSION_VWAP_BREAKDOWN.md` | avg_R by UTC session + entry-vs-VWAP | NY only +0.04 above mean, **decays OOS** (partly the volume effect); VWAP **AGAINST > ALIGNED** (inverted, OOS-robust) | **Session not robust; VWAP info but not a filter** |
| **MSS quality** `MSS_QUALITY_BREAKDOWN.md` | avg_R by HIGH/MEDIUM/LOW MSS tag | Small, non-monotonic, **flips OOS** | **Noise — no information** |
| **Fade (production CRT)** `FADE_CRT_DIAGNOSIS.md` | Why the live CRT/fade emits ~zero signals | All detected setups rejected downstream by gates (regime drag primary); gate reasons not logged | **Regime-drag + gate-tightening; diagnostic blind spot** |

Recurring lesson across the filter/geometry experiments: the "worse" bucket is almost
always still **net-profitable and the majority of signals**, so filtering raises avg_R but
cuts total sum_R — the avg_R-vs-sum_R trap (first quantified by the regime filter, −28%).

---

## 3. Current state

- **Active forward soaks (PAPER):** Soak A (5M/4H, PID 515231) and Soak B (5M/1H, PID
  515230, **PRIMARY**), both running **Config 14 on the post-TP2 trail-to-TP1 exit model**.
  They were **reset to n=0** after the post-TP2 change (old forward signals archived as
  `_PRE_POSTTP2`); the gate is **PENDING until n ≥ 30** under the new model. Read-only
  viewer on port 8890.
- **Production fade bot:** `crypto_alert.py` (PID 512666) runs the CRT/fade in PAPER in the
  separate `/home/tradeai/TradeAI/` deployment, writing `signals.db` — **untouched by this
  branch's work**.
- **Locked Soak B gate (binding):** avg_R ≥ **+0.40**, WR ≥ 0.58 (BE-after-TP1
  recalibration), PF ≥ 2.0, max DD ≤ 20 R, n ≥ 30, no per-token blowup
  (`TF_B_SOAK_PRE_REGISTER.md`).
- **Open question:** under the honest post-TP2 exit, the breakout backtest avg_R is
  **+0.34–0.36 — below the +0.40 gate floor**. The forward soaks are accumulating to test
  whether the edge holds at realistic execution. Meanwhile **no descriptive signal**
  (volume, trend, session, VWAP, MSS quality) qualified as an actionable filter, and the
  TP-geometry experiment found no better geometry. The strategic question is whether
  Config 14 clears the gate forward, or whether the realistic exit has eroded the edge.

---

## 4. Key constraints

### Validation discipline (from the report headers themselves)
- **Pre-registered, single-trial, run-once.** New variants declare their decision rule and
  trial count *before* running ("run ONCE, no parameter sweep" — `PHASE_C_REGIME_FILTER.md`,
  `TP_GEOMETRY_EXPERIMENT.md`). **"No edge" is an accepted outcome.**
- **Out-of-sample honesty.** Descriptive checks use a chronological **70/30 OOS** split; the
  formal **Held-Out Lockbox** reserves the most-recent 90 days, never touched during tuning,
  for a one-shot verdict (`docs/held_out_protocol.md`, `walk_forward.py`).
- **Honest metrics.** CPCV (Combinatorial Purged k-Fold) + **DSR deflated for the trial
  count** (Bailey & López de Prado); avg_R is reported alongside sum_R / PF / maxDD so the
  avg_R-vs-sum_R trap stays visible. A statistical property is never treated as a strategy
  until a separate pre-registered experiment confirms it survives friction.

### Isolation rules (followed throughout Phase-C)
- All exploratory analyses run **in-memory, writing NO DB rows**; backtests use the separate
  `data/breakout.db`, never the production `signals.db`.
- The running soaks (A, B) and the production fade are **never interrupted** by analysis; the
  **Run-3704 pin and `signals.db` live in the production `/home/tradeai/TradeAI/` deployment
  and are left untouched**.
- Work stays on the **`breakout-thesis`** branch — **`main` is untouched, not merged, not
  pushed**; LIVE is never armed. Code changes are paired with unit tests and branch-isolated
  when a soak is mid-run.

*See `PROJECT_INVENTORY.md` for the file / data / convention inventory, and `CLAUDE.md` for
the canonical project context.*

---
---

# Appendix A — Production ICT Bot Reference (retained verbatim from the prior README)

> The section below is the previous `README.md` (the production CRT/5M bot reference),
> preserved unchanged so no documentation is lost. It describes the production deployment
> in `/home/tradeai/TradeAI/`, not the Phase-C breakout work above.

# TradeAI — ICT Crypto Signal Bot

> **Signal-only.** Sends BUY / SELL alerts to Telegram. No order execution — the operator places every trade manually.

A directional crypto signal bot built on Inner Circle Trader (ICT) methodology. Ships **two parallel detection engines**: a 5-minute liquidity-sweep scanner and an H4 Candle Range Theory (CRT) scanner, each independently switchable. Detects liquidity sweeps, market structure shifts, fair value gaps, order blocks, Wyckoff context, optimal-trade-entry retracement zones, and killzone session timing across 10 large-cap tokens. Every signal is validated through a 365-day backtest engine using Combinatorial Purged k-Fold cross-validation and the Deflated Sharpe Ratio (Bailey & López de Prado 2014). Online Gradient Descent per-token weights adapt the scoring on every closed paper trade. Funding-rate divergence and rolling BTC-correlation overlays modulate signal confidence.

---

## Current State

| Item | Value |
|---|---|
| Execution mode | `PAPER` — 24/7 on Contabo VPS Singapore |
| Active scanner | CRT-only paper soak (5M_SWEEP scanner available but disabled) |
| Statistical clearance for LIVE | CPCV mean WR ≥ 60% **AND** Deflated Sharpe ≥ 95% **AND** 30 closed paper signals |
| Test coverage | 570+ passing tests across 24 modules |
| Hosting | Contabo Cloud VPS 10 Singapore (4 vCPU, 8 GB RAM, Ubuntu 24.04) |

**The LIVE switch never auto-flips.** It requires explicit `EXECUTION_MODE=LIVE` + `LIVE_MODE_CONFIRMED=YES` environment variables set by the operator, plus a non-default `YOUR_CAPITAL` value. The bot is signal-only — there is no order-execution code path anywhere in the codebase.

---

## What It Does

Monitors 10 crypto pairs on Binance in real time, identifies high-probability ICT setups with multi-timeframe confirmation, scores them through an adaptive per-token weight model, and sends structured trade plans (entry, TP1/TP2/TP3, stop-loss) to Telegram.

A web dashboard on port 8888 (SSH-tunnel only — never public) tracks open positions, historical performance, per-token OGD adaptive weight matrix, autonomous explorer state, and an operator-driven Tune Bot for gate parameter changes.

---

## Tokens Monitored

BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON.

Rejected after documented underperformance (do not re-propose): SOL, DOT, NEAR, SUI, LTC. See `config.py:130-138` for rationale.

---

## Architecture

### Core signal path

| File | Role |
|---|---|
| `crypto_alert.py` | Main signal bot — scan loop, Telegram dispatch, paper-trade lifecycle, BTC macro filter, live activity feed |
| `crt_engine.py` | H4 Candle Range Theory detector — range sweep + 5M structure confirmation + fair-value-gap or order-block confluence + Wyckoff phase tagging |
| `ict_engine.py` | ICT primitives — sweeps, market structure shifts, fair value gaps, dealing range, inverse FVG, SMT divergence, OTE overlay, equal-highs/lows clustering, trade plan |
| `strategy_engine.py` | Shared gate engine consuming live and backtest configs |
| `strategy_templates.py` | Signal quality templates (Tier A / B / C classification with per-direction calibration) |
| `adaptive_engine.py` | Per-token weight engine, expected-value scoring, drift detection, portfolio risk layer, statistical-validity-aware learning rate |
| `funding_rate_client.py` | 8-hour funding-rate overlay — live and historical Binance perpetual data, confidence bonus on extreme readings |
| `btc_correlation.py` | Rolling Pearson correlation between BTC and token 5-minute log-returns, confidence bonus on alignment |
| `backtest.py` | 365-day backtest engine with multi-template harness, checkpoint resume, both scanner paths |
| `validation.py` | CPCV + PSR + Deflated Sharpe Ratio (López de Prado 2018, Bailey & LdP 2014) — honest metrics workhorse |
| `walk_forward.py` | Walk-forward validation + held-out lockbox + dual-track parity quantification |
| `labeling.py` | Triple-barrier labels + bootstrap confidence intervals (López de Prado AFML 2018) |
| `indicators.py` | RSI, ATR, ADX, Bollinger, candle structure helpers |
| `config.py` | Single source of truth for all tunables + environment-variable overrides |
| `tracker.py` / `tracker_html.py` | Web dashboard server + single-file HTML/JS frontend with Reports tab, AI Intelligence panel, adaptive weights view, and live activity feed |

### Operational resilience

| File | Role |
|---|---|
| `heartbeat.py` | Dead-man's switch + multi-channel alerter (Telegram + SMTP fallback) |
| `state_store.py` | Atomic JSON state persistence (`tempfile → fsync → os.replace`) + PidFile |
| `backtest_checkpoint.py` | Per-token checkpoint so killed backtests resume from last completed token |
| `scripts/watchdog.py` | External heartbeat-watchdog sidecar |
| `monitoring.py` | OGD weight degeneration sidecar (read-only) — daily health check |
| `event_calendar.py` | FOMC / CPI / NFP macro filter (advisory default) |
| `secrets_loader.py` | `.env` / `.env.vault` loader (`TELEGRAM_TOKEN`, `CHAT_ID`, etc.) |

### Autonomous R&D layer

| File | Role |
|---|---|
| `scripts/autonomous_explorer.py` | Optuna Bayesian parameter search with 4 phases (core loop, anti-overfit guard, auto-promotion, dashboard) |
| `scripts/promote_baseline.py` | Operator + auto-promotion path with 8-criteria gate + reproducibility re-run |
| `scripts/compute_cross_config_sr_std.py` | Honest cross-config `sr_trial_std` refresher (post-promote) |
| `scripts/snapshot_baseline.py` | `signals.db` snapshot + restore tooling |
| `data/explorer_learning.db` | Per-trial verdict and metric log |
| `data/pareto_archive.json` | Top-10 non-dominated configs across all sessions |
| `data/promotion_log.json` | 30-entry rolling audit of promote attempts |

---

## Signal Pipeline

Two parallel scanners run independently per cycle, each gated by its own kill switch. Any single gate failure short-circuits the rest within that scanner.

### 5M_SWEEP scanner (canonical, currently DISABLED)

```
 1. Fetch OHLCV       — 5M / 1H / 4H candles (Binance REST)
 2. Data quality      — gap detection (5M ≥3 bars, 1H ≥2, 4H ≥1 → block)
 3. ICT sweep         — BSL or SSL swept within last ICT_SWEEP_LOOKBACK bars
 4. Displacement      — momentum candle confirms sweep within 9 bars
 5. MSS               — market structure shift confirmed within ICT_MSS_HORIZON
 6. FVG               — fair value gap present and unmitigated (quality HIGH/MED/LOW)
 7. Dealing range     — price in premium (SELL) or discount (BUY) zone
 8. 4H bias gate      — higher-timeframe directional alignment
 9. 1H trend gate     — intermediate trend confirmation
10. Regime gate       — RANGING / CHOPPY regimes suppressed or blocked
11. Killzone          — NY AM / London / Asia sessions only
12. EV gate           — expected value positive over 100+ signal history
13. Template          — Tier A / B / C ICT variant classification
14. OGD score         — per-token adaptive confidence (1–10)
15. Confidence floor  — signal blocked if below dynamic floor
```

See `crypto_alert.py:generate_signal()` for the canonical 5M_SWEEP implementation.

### H4_CRT scanner (active in current paper soak)

```
 1. Fetch OHLCV          — 5M / 4H candles (with stale + gap guards)
 2. C1 candidate         — H4 reference candle within the lookback window
 3. C2 sweep              — C2 wicks beyond C1's high or low
 4. Mitigation check     — consumed-zone pruning (re-eligibility TTL)
 5. 5M structure shift   — confirmation within the MSS horizon
 6. FVG or order block   — confluence at C1's swept-extreme half
 7. Killzone session     — liquid-hours filter
 8. 4H bias gate         — higher-timeframe directional alignment
 9. 1H trend gate         — intermediate trend confirmation (optional)
10. Wyckoff context      — phase tag (informational by default)
11. Trade economics      — SL / TP1 / TP2 / TP3 cascade + min RR
12. Funding overlay      — confidence bonus on extreme funding rates
13. BTC correlation      — confidence bonus on aligned BTC log-returns
14. EQH/EQL cluster tag  — equal-highs/lows liquidity-pool annotation
15. OTE retracement tag  — optimal-trade-entry Fibonacci zone (62-79%)
16. Template tier        — Tier A (premium) / Tier B / Tier C classification
17. Per-token cooldown   — 40 min per direction
18. Macro filter         — FOMC / CPI / NFP window check
19. Kill switches        — daily loss, weekly loss, consecutive losses
20. Portfolio gate       — max open positions, risk cap, correlation guard
21. Regime classification — live market regime stored with the signal
22. Telegram dispatch    — multi-channel alerter with SMTP fallback
```

The shared CRT detection engine is identical between live and backtest paths, so backtest results are predictive of live behavior.

---

## ICT Detection Modules

All defined in `ict_engine.py`. Constants are env-overridable (`config.py`).

| Module | Responsibility |
|---|---|
| Sweep detection | Scans `ICT_SWEEP_LOOKBACK` bars (current: 20) for BSL/SSL wick beyond prior swing high/low. ICT_SWING_N=2 (LOCKED anti-pattern at ≥3). |
| Market structure shift | Confirms MSS within `ICT_MSS_HORIZON` bars (30). Scores: displacement body size, close vs structure, retest quality. Quality gate enforced. |
| Fair value gap | Three-candle FVG pattern. Quality scoring on gap-to-ATR ratio and DR location. iFVG (inverse FVG) confirmation for precision entries. |
| Dealing range | Dynamic premium / discount classification from last N swing points (`DEALING_RANGE_LOOKBACK`). BUY requires DISCOUNT, SELL requires PREMIUM. |
| SMT divergence | Detects correlated-pair non-confirmation (e.g. BTC fails to sweep with ETH). Confidence bonus/penalty rather than hard gate. |
| Trade plan | TP1 = 1:1 RR (sweep wick → MSS), TP2 = 1.5:1, TP3 = next liquidity pool. SL beyond sweep wick with buffer. Min RR gate = 1.5 (LOCKED anti-pattern at ≥2.0). |

---

## Adaptive Learning System

Three connected layers that improve signal quality over time. Canonical reference: `docs/ADAPTIVE_LEARNING.md`.

### Layer 1 — OGD per-token weights (`adaptive_engine.py`)

Online Gradient Descent updates six feature weights per token on every closed paper trade:
`fvg_quality`, `mss_quality`, `session`, `confidence`, `trend_strength`, `dr_location`.

Weights are persisted to `data/signals.db` (`token_weights` table) and survive restarts. Backtest history warm-starts weights via a separate isolated table (`backtest_token_weights`) — backtest writes never contaminate the live weight pool (H6 isolation).

### Layer 2 — Safety + observability

| Component | Description |
|---|---|
| Statistical-validity learning gate | Downscales the learning rate when the latest cross-validation verdict is FAIL or unverified-MARGINAL |
| Soft warmup ramp | Continuous learning-rate ramp from first sample to full-rate (no cliff transitions) |
| Bootstrap isolation | Backtest weight writes are gated by an explicit opt-in so non-canonical runs never contaminate the live weight pool |
| Forensic weight history | Every update logs reward, gradient magnitude, profit percentage, regime, and source run for retrospective analysis |
| Daily weight monitor | Sidecar checks for degeneracy, floor-pinning, entropy collapse — escalates via Telegram alert |
| Event-driven decay | Weight decay fires per-token on scan activity rather than a fixed cron — survives bot restarts cleanly |
| Regime tagging | Market regime is stored with each signal for retrospective slicing without affecting acceptance |
| Reward magnitude alert | Large reward magnitudes (potential unit-violation guards) fire Telegram alerts |
| Learning-freeze predicate | Three trigger conditions (consecutive losses, validity-fail streak, gradient spike) freeze learning in shadow mode by default |
| Per-token dashboard panel | Full weight matrix with badges for warm-start, live, degenerate, or floor-pinned states |

### Layer 3 — Tune Bot (operator-driven gate tuning)

Analyzes backtest with 60/40 train/test walk-forward split. Proposes changes to `strategy_engine.py LIVE_CONFIG` only when a finding holds in **both** halves. Guards: frequency gate (50 new signals OR 14 days), Wilson CI overlap check, max 2 APPLIED entries, walk-forward gap warning (>15pp = overfitting risk). Post-apply WR verdict (`VERIFIED_BETTER` / `VERIFIED_WORSE`) fires Telegram alert.

### Layer 3 — Live/backtest parity simulation

A sandboxed copy of the adaptive engine runs alongside the canonical backtest to simulate what the live learning trajectory would look like if the engine had been active across the full historical window. This is engineering-only — it does not persist state or affect production decisions, but it lets new adaptive features be validated without waiting for months of real paper closes.

---

## Honest Metrics

Every backtest and explorer trial uses the same statistical pipeline. Critical for separating genuine edge from selection bias.

| Metric | Source | Purpose |
|---|---|---|
| CPCV mean WR / std / q05 | `validation.py:cpcv_summary()` | Combinatorial Purged k-Fold (López de Prado 2018) — out-of-sample robustness |
| Sharpe (per-trade + CPCV mean) | `validation.py` | Risk-adjusted return |
| Deflated Sharpe Ratio (DSR) | `validation.py` (Bailey & LdP 2014) | Selection-bias-corrected Sharpe across `n_trials` distinct configs |
| Probabilistic Sharpe Ratio (PSR) | `validation.py` | Probability the true Sharpe exceeds a benchmark |
| Cross-config `sr_trial_std` | `bot_state.cross_config_sr_trial_std` | Honest standard deviation across distinct config_hashes (not within-fold proxy) |
| Triple-barrier labels | `labeling.py` | Continuous outcome labeling (TP / SL / timeout) with bootstrap CI |

The `cumulative_min_trials` seed in `bot_state` ensures the DSR selection-bias correction stays honestly conservative even after a DB wipe.

---

## Autonomous Explorer

A standing background Bayesian search built in four phases (`scripts/autonomous_explorer.py`).

| Phase | Capability |
|---|---|
| Phase 1 — Core loop | Optuna TPE search over 8 ICT parameters, per-trial CPCV verdict |
| Phase 2 — Anti-overfit guard | PidFile, pre-cache warm, 4 trip conditions (consecutive FAILs, ERRORs, DSR drop, sr_trial_std drift, code drift), Telegram alerts, `--status` CLI |
| Phase 3 — Auto-promotion | 8-criteria eligibility gate + reproducibility re-run + 2/day cap + 24h soak between promotes |
| Phase 4 — Dashboard | "Auto-Explorer" tab in `tracker_html.py` + 4 API routes + `--digest` CLI |

### Critical safety invariants

- Never auto-flips `EXECUTION_MODE=LIVE`.
- Auto-promote writes `baseline_pin.json` + `tune_history` only — does not toggle anything else.
- Reproducibility required: two backtests with matching `config_hash` and ±0.5pp `cpcv_mean` tolerance.
- 2 auto-promotes per UTC day cap. 24-hour soak between promotions.
- Explorer trials skip the bootstrap weight write — never contaminate the live learning pool.
- Explorer trials skip the cross-validation verdict write — never pollute the live learning-rate gate.
- Anti-pattern locks asserted at session start prevent re-testing parameter regions empirically shown to be net-harmful.

### Objective function

Optuna maximizes `cpcv_mean + alpha * log(max(1, n))` where alpha is set via `EXPLORER_N_BONUS_ALPHA` (default 2.0). Bigger alpha biases the search toward higher-frequency configs at the cost of marginal WR — the LIVE-clearance gate requires 30 closed paper signals, so frequency is operationally as important as WR.

Error / timeout trials return `-100.0` sentinel — strictly below the worst valid FAIL score, so TPE avoids error-prone regions.

---

## Signal Quality Templates

Defined in `strategy_templates.py`. Each signal is classified into one of three tiers based on confluence quality and direction calibration. Empirical paper data drives the tier definitions — they evolve as the live cohort accumulates.

| Tier | Live execution | Daily cap | Description |
|---|---|---|---|
| A | After 50 closed live signals | 3 per day | Premium-confluence setups (currently SELL-direction only per empirical calibration) |
| B | After 50 closed live signals | 2 per day | High-quality fair-value-gap or order-block confluence with strong structure-shift |
| C | Paper only | 0 | Catchall for signals that don't meet the higher tiers — observed only, never live |

A circuit breaker pauses any template if its rolling win rate drops below 55% over 20 signals. Range-bound regimes block the order-block-confluence templates because order-block reactions are empirically weakest in choppy markets.

---

## Risk Management

| Control | Value | Notes |
|---|---|---|
| Risk per trade | 1% of capital | Position size scales with stop-loss distance, capped at 20% notional |
| Max open positions | 4 (live) / unlimited (paper) | Portfolio-level cap |
| Daily loss limit | 3% of capital and 3-trade count | Dual-gate kill switch (percentage AND count) |
| Weekly loss limit | 6% of capital | Kill switch active in both PAPER and LIVE |
| Max consecutive losses | 3 | Kill switch on breach |
| Total drawdown | 10% LIVE / 20% PAPER | Computed via full equity-curve replay |
| Per-symbol cooldown | 2 hours after a stop-loss hit | Per-token post-loss pause |
| Correlation guard | Block third same-direction correlated position | Prevents stacked exposure during BTC-led moves |
| Template safety gates | Insufficient-sample, circuit-breaker, daily-cap, ranging-regime block | Enforced before any live alert |
| Adaptive learning throttle | Conservative scaling when statistical validity is stale | Protects OGD from drifting away from a confirmed baseline |
| Execution-mode triple-lock | Three independent environment variables required for LIVE | Bot refuses to start LIVE otherwise |

---

## Deployment

### Production (VPS)

**Host:** Contabo Cloud VPS 10 Singapore (4 vCPU, 8 GB RAM, 75 GB NVMe).
**OS:** Ubuntu 24.04 LTS.
**Path:** `/home/tradeai/TradeAI/`.

#### Always-on systemd services

| Service | Role |
|---|---|
| `tradeai.service` | Signal bot (24/7 scan loop) |
| `tradeai-tracker.service` | Dashboard server on port 8888 (SSH-tunnel only) |
| `tradeai-watchdog.service` | Heartbeat monitor with Telegram alerting on freeze |

#### Manual-trigger services (not auto-started on boot)

| Service | Role |
|---|---|
| `tradeai-explorer.service` | Autonomous Optuna explorer — `sudo systemctl start tradeai-explorer` to begin; `stop` for clean SIGTERM |

#### Dashboard access

Open an SSH tunnel from a local machine:

```bash
# In ~/.ssh/config
Host tradeai-vps
    LocalForward 8888 127.0.0.1:8888
```

Then browse to `http://localhost:8888`.

#### Daily operator workflow

```bash
# Edit a file in VSCode Remote SSH, save, restart the bot:
sudo systemctl restart tradeai

# Watch live logs:
journalctl -u tradeai -f

# Run an explorer session:
nano /home/tradeai/TradeAI/.env.explorer   # edit trial count + study name
sudo systemctl start tradeai-explorer
journalctl -u tradeai-explorer -f          # detach with Ctrl+C, service keeps running

# Check explorer progress without disrupting:
python3 scripts/autonomous_explorer.py --status

# Run a one-off canonical backtest (~11 min):
cd /home/tradeai/TradeAI && python3 backtest.py
```

### Local development (Linux / macOS)

```bash
# 1. Clone
git clone https://github.com/leomerjhonparba/tradeai-bot.git
cd tradeai-bot

# 2. Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp deploy/env.example .env
nano .env   # set TELEGRAM_TOKEN, CHAT_ID, EXECUTION_MODE=PAPER, YOUR_CAPITAL

# 4. Run the bot (foreground)
python3 crypto_alert.py

# 5. Run the dashboard (separate terminal)
python3 tracker.py
# Browse to http://localhost:8888

# 6. Run a backtest (VPN required for Binance from PH)
python3 backtest.py
```

`requirements.txt` covers `requests`, `pandas`, `numpy`, `optuna`, `scipy` for the honest-metrics layer, and standard library deps elsewhere.

---

## Execution Modes

| Mode | Behavior |
|---|---|
| `PAPER` | Signals sent to Telegram with paper labels. Kill switches active. OGD learns from real paper closes. |
| `LIVE` | Only ACTIVE-template signals sent. All safety gates enforced. Requires `LIVE_MODE_CONFIRMED=YES`. |

Switching to LIVE requires two explicit steps: set `EXECUTION_MODE=LIVE` in `.env` **and** set `LIVE_MODE_CONFIRMED=YES`. The bot validates both at startup. Bot is signal-only — has no order-execution code path. The operator places every trade manually.

---

## Dashboard Tabs

| Tab | Content |
|---|---|
| Overview | Open paper positions, TP progress, live aggregate stats (WR, total signals, P&L) |
| Signal History | All signals with filters, sorting, pagination, per-signal forensic detail |
| AI Intelligence | Bot health score, per-token adaptive weight matrix, drift baselines, learning state |
| Backtest | Run history, template performance report, Tune Bot panel, Tune History with rollback, honest-metrics summary |
| Auto-Explorer | Live explorer session state, Pareto archive top-10, promotion log, trial digest |

QuantStats tab exists in code but is hidden via `display:none` until LIVE trading produces real P&L (`tracker_html.py:635`).

---

## Project Layout

```
TradeAI/
├── crypto_alert.py            Main signal bot (24/7 scan loop)
├── ict_engine.py              ICT detection (sweep, MSS, FVG, DR, iFVG, SMT, trade plan)
├── strategy_engine.py         Shared gate engine
├── strategy_templates.py      Tier A / B / C template registry
├── adaptive_engine.py         OGD weights, EV, drift, portfolio risk
├── backtest.py                Backtest engine + checkpoint resume
├── validation.py              CPCV + PSR + DSR
├── walk_forward.py            Walk-forward validation + held-out lockbox + parity simulation
├── labeling.py                Triple-barrier labels + bootstrap CI
├── monitoring.py              OGD weight monitor (read-only)
├── tracker.py                 Dashboard API server
├── tracker_html.py            Dashboard HTML/CSS/JS template
├── quantstats_report.py       QuantStats integration (LIVE-only)
├── heartbeat.py               Heartbeat writer
├── state_store.py             Atomic JSON state + PidFile
├── secrets_loader.py          .env loader
├── event_calendar.py          Macro event filter
├── config.py                  Single source of truth
├── indicators.py              Technical indicator helpers
│
├── scripts/
│   ├── autonomous_explorer.py        Phases 1-4 autonomous R&D
│   ├── promote_baseline.py           Operator + auto-promotion
│   ├── compute_cross_config_sr_std.py  Honest DSR pool refresher
│   ├── snapshot_baseline.py          signals.db snapshot tooling
│   └── watchdog.py                   External heartbeat watchdog
│
├── deploy/
│   ├── tradeai.service               systemd unit (bot)
│   ├── tradeai-tracker.service       systemd unit (dashboard)
│   ├── tradeai-watchdog.service      systemd unit (watchdog)
│   ├── tradeai-explorer.service      systemd unit (explorer, manual-trigger)
│   ├── bootstrap_vps.sh              One-time VPS setup
│   └── env.example                   .env template
│
├── data/                             GITIGNORED — VPS-only operational data
│   ├── signals.db                    Main DB: signals, results, weights, runs, bot_state
│   ├── explorer_learning.db          Explorer trial log
│   ├── optuna_study.db               Optuna study state
│   ├── baseline_pin.json             Canonical baseline reference
│   ├── pareto_archive.json           Top-10 non-dominated configs
│   ├── promotion_log.json            30-entry rolling promote audit
│   ├── snapshots/                    signals.db snapshots
│   └── ohlcv_cache/                  Binance candle cache
│
├── docs/
│   ├── ADAPTIVE_LEARNING.md          Canonical adaptive layer reference
│   ├── AUTONOMOUS_EXPLORER_DESIGN.md
│   ├── LIVE_BACKTEST_PARITY_ROADMAP.md
│   ├── OPTIMIZATION_AGENT_PIPELINE.md
│   ├── ENTERPRISE_ROADMAP.md
│   ├── exploration_runs/             Per-cycle exploration reports
│   ├── ict_strategy_variant_learner/
│   └── comprehensive/
│       └── CROSS_REF.md              Every prior issue's resolution status
│
├── tests/                            444 passing across 19 test modules
├── .claude/
│   ├── agents/                       Subagent definitions
│   ├── skills/                       Operator-invocable skills
│   └── reports/                      Audit reports (cycle-by-cycle)
└── README.md                         This file
```

---

## Development Workflow

The project uses a multi-agent review system via Claude Code. Operator-invocable skills:

| Skill | Purpose |
|---|---|
| `/tradeai-health` | GREEN / YELLOW / RED status check (~5 min) |
| `/tradeai-audit` | Full parallel audit — 11 specialist agents (~30-60 min) |
| `/tradeai-pre-live` | Pre-live GO / NO-GO checklist |
| `/tradeai-backtest` | Run + parse a canonical backtest |
| `/tradeai-paper-monitor` | Paper-trade progress + LIVE-clearance ETA |
| `/tradeai-signal-report` | Per-token + per-setup signal performance breakdown |
| `/tradeai-config-validate` | Parameter consistency check across all configs |

Specialist agents cover: ICT logic, backtest bias, live/backtest consistency, risk management, data pipeline, adaptive learning, OGD weights, template tier calibration, signal performance, honest metrics, operational resilience, config consistency.

Periodic audits produce a unified scorecard across eleven engineering dimensions: ICT logic, live/backtest consistency, risk management, backtest validity, adaptive learning, weight quality, template calibration, data pipeline, honest metrics, operational resilience, and configuration consistency.

---

## Roadmap

| Component | Status | Description |
|---|---|---|
| ICT signal pipeline | Complete | Sweep, market structure shift, fair value gap, dealing range, inverse FVG, SMT, trade plan, template registry, backtest harness |
| H4 Candle Range Theory scanner | Complete | Independent second scanner with shared backtest path; per-direction template calibration |
| Operational resilience | Complete | Heartbeat, watchdog, atomic state store, backtest checkpoint, multi-channel alerter with SMTP fallback |
| Configuration foundation | Complete | Single-source-of-truth config, secrets loader, environment-variable overrides, schema-parity tests |
| Honest metrics | Complete | CPCV + PSR + Deflated Sharpe Ratio, weight-quality monitor, macro-event filter |
| Realistic execution model | Complete | Fees, slippage, limit-order fillability tracking |
| Held-out lockbox | Complete | One-shot final-validation gate for promotion candidates |
| Live/backtest parity simulation | Complete | Sandboxed adaptive engine quantifies how live learning would have evolved across the historical window |
| Autonomous explorer | Complete | Optuna Bayesian search, anti-overfit guard, auto-promotion gate, dashboard panel |
| Adaptive learning safety + observability | Complete | Statistical-validity-aware learning rate, soft warmup ramp, forensic logging, daily monitor |
| Funding-rate divergence overlay | Complete | Live and historical Binance perpetual funding-rate data feeds confidence bonus |
| BTC correlation overlay | Complete | Rolling Pearson correlation modulates confidence on aligned vs divergent moves |
| Per-template adaptive weights | Pending closed-signal threshold | Requires sufficient closed live signals per template before activation |
| Paper signal accumulation | In progress | Statistical-clearance gate ahead of any LIVE consideration |

The remaining gate to LIVE is statistical: the system needs enough closed paper signals to clear the Deflated Sharpe Ratio threshold. Explorer sessions search for higher-frequency parameter configurations that preserve win rate, shortening the soak window.

---

## Confirmed Anti-Patterns

Parameter regions empirically shown to be net-harmful — locked at the explorer level so future tuning cannot drift back into them.

- Looser swing-detection threshold — degrades win rate and Sharpe
- Aggressive minimum risk/reward gate — catastrophically thins the signal pool with no quality compensation
- Lower fair-value-gap quality bars — collapses win rate to coin-flip territory
- Wider backtest window that includes regime-degraded periods — averages the live edge away
- Adding tokens shown to chronically underperform on this strategy
- Strict Wyckoff phase filter on crypto — calibrated for gold/forex, empirically harms crypto win rate
- Universal high-mass-quality gating across both directions — destroys the BUY-side signal pool under current TP geometry
- Backtest-internal library shortcuts that would break live/backtest parity

---

## Notes

- **Signal-only** — no auto-trading code path, no exchange API keys for execution, no order placement logic anywhere.
- All Telegram tokens loaded via `.env` only — the bot refuses to start if `TELEGRAM_TOKEN` is missing.
- After any code change that affects `strategy_engine.py` gate logic, **restart the bot** for the new config to load.
- Backtest validity requires a full re-run after any change to signal-generation parameters — old runs are stale.
- The persisted cross-validation verdict is gated by an explicit opt-in environment variable (default-on for manual backtests, default-off for explorer trials) so only canonical backtests overwrite the live learning-rate-gate input.

---

## License

Private. All rights reserved.

## Contact

Maintainer: Operator (Cebu, Philippines).
Project canonical context: `CLAUDE.md` (read first for any new contributor / Claude session).
