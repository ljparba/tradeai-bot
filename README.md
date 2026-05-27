# TradeAI — ICT Crypto Signal Bot

> **Signal-only.** Sends BUY / SELL alerts to Telegram. No order execution — the operator places every trade manually.

A directional crypto signal bot built on Inner Circle Trader (ICT) methodology. Detects liquidity sweeps, market structure shifts, fair value gaps, dealing ranges, and killzone timing on the 5-minute chart across 10 large-cap tokens. Every signal is validated through a statistical backtest engine using Combinatorial Purged k-Fold cross-validation (CPCV) and the Deflated Sharpe Ratio (Bailey & López de Prado 2014). Online Gradient Descent (OGD) per-token weights adapt the scoring on every closed paper trade.

---

## Current State (2026-05-27)

| Item | Value |
|---|---|
| Execution mode | `PAPER` — 24/7 on Contabo VPS Singapore |
| Canonical baseline | **Run-81** (Phase B reverted; DR gate OFF both sides) |
| Baseline metrics | n=35, CPCV mean WR 70.0%, std 7.93%, q05 53.3%, Sharpe 1.007, **DSR 98.7%** (honest cross-config) |
| LIVE-clearance gate | CPCV WR ≥ 60% **AND** DSR ≥ 95% **AND** 30 closed paper signals |
| Current paper signals closed | 0 / 30 — the only remaining blocker |
| Cycle-7 audit score | 9.30 / 10 (all-time peak) |
| Test coverage | 444 passing across 19 test modules |

**LIVE switch never auto-flips.** Requires explicit `EXECUTION_MODE=LIVE` + `LIVE_MODE_CONFIRMED=YES` env vars set by the operator.

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
| `crypto_alert.py` | Main signal bot — 5-minute scan loop, Telegram dispatch, paper-trade lifecycle |
| `ict_engine.py` | ICT detection — sweeps, MSS, FVG, dealing range, iFVG, SMT divergence, trade plan |
| `strategy_engine.py` | Shared gate engine consuming `LIVE_CONFIG` / `BACKTEST_CONFIG` |
| `strategy_templates.py` | ICT variant templates (Tier A / B / C classification) |
| `adaptive_engine.py` | OGD weight engine, EV scoring, drift detection, portfolio risk layer |
| `backtest.py` | 365-day backtesting engine with multi-template harness + checkpoint resume |
| `validation.py` | CPCV + PSR + DSR (Bailey & López de Prado 2014) — honest metrics workhorse |
| `walk_forward.py` | Walk-forward validation + held-out lockbox + Phase D.1 dual-track WFV-with-OGD |
| `labeling.py` | Triple-barrier labels + bootstrap CI (López de Prado AFML 2018) |
| `indicators.py` | RSI, ATR, ADX, Bollinger, candle structure helpers |
| `config.py` | Single source of truth for all tunables + env-var overrides |
| `tracker.py` / `tracker_html.py` | Web dashboard server + frontend (single-file HTML/JS template) |

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

Each 5-minute cycle runs through a fixed sequence. Any single failure short-circuits the rest.

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

See `crypto_alert.py:scan_token()` for the canonical implementation.

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

### Layer 2 — R1–R10 master adaptive sweep (2026-05-26)

| Ref | Component |
|---|---|
| R1 | DSR-aware learning gate — `_dsr_gate_lr_scale()` downscales LR when latest CPCV verdict is FAIL or MARGINAL-without-DSR-correction |
| R2 | Soft warmup ramp — continuous LR from n=3 to n=10 (no n=10 cliff) |
| R3 | Bootstrap env gate — `BOOTSTRAP_AFTER_RUN=0` opt-out for non-canonical backtests |
| R4 | `weight_history` forensic columns: `reward`, `gradient_l1`, `profit_pct`, `regime`, `run_id` |
| R5 | Daily monitor systemd timer + Telegram CRIT alert |
| R6 | Event-driven decay — `apply_decay_if_due()` (replaces fixed-cadence cron) |
| R7 | Regime labeling — observation-only, not conditioning |
| R8 | Reward magnitude alert — \|reward\| > 1.2 → Telegram |
| R9 | Learning-freeze predicate — shadow mode default, gates active under 3 trigger conditions |
| R10 | Per-token forensic dashboard panel — full weight matrix with badges |

### Layer 3 — Tune Bot (operator-driven gate tuning)

Analyzes backtest with 60/40 train/test walk-forward split. Proposes changes to `strategy_engine.py LIVE_CONFIG` only when a finding holds in **both** halves. Guards: frequency gate (50 new signals OR 14 days), Wilson CI overlap check, max 2 APPLIED entries, walk-forward gap warning (>15pp = overfitting risk). Post-apply WR verdict (`VERIFIED_BETTER` / `VERIFIED_WORSE`) fires Telegram alert.

### Phase D.1 dual-track WFV-with-OGD (parity quantification)

`walk_forward.py:walk_forward_with_ogd()` runs a sandboxed `AdaptiveWeightEngine` per backtest. Simulates what the live OGD trajectory would look like if learning had been active — used for engineering validation of new adaptive features without waiting for real paper closes. Does not persist state or affect verdicts.

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
- Explorer trials skip the bootstrap weight write (`BOOTSTRAP_AFTER_RUN=0`) — never contaminate the live OGD pool.
- Explorer trials skip the CPCV verdict write (`WRITE_CPCV_VERDICT=0`) — never pollute the R1 DSR gate.
- Anti-pattern locks asserted at session start: `ICT_SWING_N=2`, `ICT_MIN_RR_GATE=1.5`.

### Objective function (cycle-7)

Optuna maximizes `cpcv_mean + alpha * log(max(1, n))` where alpha is set via `EXPLORER_N_BONUS_ALPHA` (default 2.0). Bigger alpha biases the search toward higher-frequency configs at the cost of marginal WR — the LIVE-clearance gate requires 30 closed paper signals, so frequency is operationally as important as WR.

Error / timeout trials return `-100.0` sentinel — strictly below the worst valid FAIL score, so TPE avoids error-prone regions.

---

## ICT Strategy Variant Templates

Defined in `strategy_templates.py`.

| Tier | Live execution | Daily cap | Description |
|---|---|---|---|
| A | After 50 closed live signals | 3 per day | Highest-confluence ICT setups |
| B | After 50 closed live signals | 2 per day | Standard ICT setups |
| C | Paper only | 0 | Experimental — never live |

Circuit breaker pauses a template if rolling WR drops below 55% over 20 signals. RANGING regime blocks Tier B / NONE templates.

---

## Risk Management

| Control | Value | Notes |
|---|---|---|
| Risk per trade | 1% of capital | Position size scales with SL distance |
| Max open positions | 4 (live) / unlimited (paper) | Portfolio-level cap |
| Daily loss limit | 3% of capital | Kill switch active in both PAPER and LIVE |
| Weekly loss limit | 8% of capital | Kill switch active in both PAPER and LIVE |
| Max consecutive losses | Configurable | Kill switch on breach |
| Drawdown gate | Configurable | Blocks new signals during drawdown |

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
| AI Intelligence | Bot health score, per-token OGD weight matrix (R10 panel), drift baselines, adaptive learning state |
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
├── walk_forward.py            Walk-forward + held-out + Phase D.1 dual-track
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

Periodic audits produce a unified 10/10 scorecard. Current state: **9.30 / 10** (cycle-7, 2026-05-27 — all-time peak). See `.claude/reports/tradeai-audit/` for the full history.

---

## Roadmap

| Phase | Status | Description |
|---|---|---|
| ICT signal pipeline (I-1 → I-5A) | Complete | Sweep, MSS, FVG, DR, iFVG, SMT, trade plan, template registry, backtest harness |
| Sprint 1 — Operational resilience | Complete | Heartbeat, watchdog, atomic state store, backtest checkpoint |
| Sprint 2 — Config + statistical foundation | Complete | `config.py` SSoT, secrets loader, triple-barrier labels, CI regression gate |
| Sprint 3 — Honest metrics + observability | Complete | CPCV + PSR + DSR, OGD weight monitor, macro event filter |
| Phase A — Realistic execution model | Complete | Fees, slippage, partial fill model (REALISTIC_EXECUTION=1) |
| Phase B — DR gate parity | Reverted (KNOWN STRUCTURAL) | D2 diagnostic revealed gate killed 98.5% of signals — reverted to OFF both sides |
| Phase C — Held-out lockbox | Complete | One-shot final validation gate (`HELD_OUT_DAYS` configurable) |
| Phase D.1 — Dual-track WFV-with-OGD | Complete | Live↔backtest parity quantification via sandboxed AdaptiveWeightEngine |
| Autonomous explorer (Phases 1-4) | Complete | Optuna search, anti-overfit guard, auto-promote, dashboard |
| R1–R10 master adaptive sweep | Complete | DSR gate, warmup ramp, forensic cols, regime labels, freeze predicate, dashboard |
| ICT I-5B / I-6 per-template OGD | Data-gated | Needs N ≥ 30 closed live signals per template |
| Paper signal accumulation | In progress | 0 / 30 closed — only remaining LIVE-clearance blocker |

The remaining blocker is operator patience plus explorer-discovered higher-frequency configs. Current baseline produces ~2.88 signals / month; reaching 30 closed signals at that rate takes ~10 months. Explorer sessions are tuned to find higher-frequency configs that pass the honest-metrics gates.

---

## Confirmed Anti-Patterns (Do Not Re-Test)

Documented in `docs/comprehensive/CROSS_REF.md`. Burned testing each.

- `ICT_SWING_N ≥ 3` — −3.9pp WR / −0.07 Sharpe
- `ICT_MIN_RR_GATE ≥ 2.0` — catastrophic (n=10, WR=50%)
- `BACKTEST_FVG_MIN_QUALITY = LOW` or `MEDIUM` — coin-flip WR (~44%)
- `BACKTEST_DAYS = 730` — averages the 2024 dead-zone (Cycle Z)
- Adding SOL / DOT / NEAR / SUI / LTC — chronic underperformers
- `vectorbt` library — rejected (would break live↔backtest parity)

---

## Notes

- **Signal-only** — no auto-trading code path, no exchange API keys for execution, no order placement logic anywhere.
- All Telegram tokens loaded via `.env` only — the bot refuses to start if `TELEGRAM_TOKEN` is missing.
- After any code change that affects `strategy_engine.py` gate logic, **restart the bot** for the new config to load.
- Backtest validity requires a full re-run after any change to signal-generation parameters — old runs are stale.
- The `bot_state.latest_cpcv_verdict` is gated by `WRITE_CPCV_VERDICT=1` (default for manual backtests, =0 for explorer trials) — only canonical backtests overwrite the R1 DSR gate input.

---

## License

Private. All rights reserved.

## Contact

Maintainer: Operator (Cebu, Philippines).
Project canonical context: `CLAUDE.md` (read first for any new contributor / Claude session).
