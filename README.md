# TradeAI — ICT Crypto Signal Bot v13 ICT MODE

> **Signal-only.** Sends BUY/SELL alerts to Telegram. No auto-execution — you make the final call.

Built on Inner Circle Trader (ICT) methodology: liquidity sweeps, market structure shifts, fair value gaps, dealing ranges, and killzone timing — validated through a statistical backtesting engine with CPCV + Deflated Sharpe Ratio honest metrics and adaptive learning.

---

## Current State (2026-05-23)

- **Baseline:** Run 110 — n=46, WR=76.1%, CPCV mean WR=76.23%, **DSR=0.898 (ACCEPTABLE SUCCESS)**
- **LIVE readiness:** **NOT YET** — DSR=0.898 < 0.95 LIVE-strict threshold. Path is paper-trading accumulation (n=46 → n≥80), not more optimization.
- **Test coverage:** 375/375 passing
- **Mode:** PAPER (`EXECUTION_MODE=PAPER`) — signal-only with status labels

---

## What It Does

TradeAI monitors 10 crypto pairs (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON) in real time on Binance, identifies high-probability ICT setups on the 5-minute chart with multi-timeframe confirmation, and sends structured trade plans to Telegram with entry, TP1/TP2/TP3, and stop-loss levels.

A web dashboard (port 8888) tracks open positions, historical performance, OGD adaptive weights, and a Tune Bot that proposes and applies gate parameter changes based on backtest analysis.

---

## Architecture

**Core signal path:**
```
crypto_alert.py      — main signal bot (runs 24/7)
ict_engine.py        — ICT detection logic (sweeps, MSS, FVG, DR, iFVG, SMT, EQH/EQL clusters)
strategy_engine.py   — shared gate engine (LIVE_CONFIG / BACKTEST_CONFIG)
adaptive_engine.py   — OGD weight engine, EV scoring, drift detection, risk layer
strategy_templates.py — ICT variant templates (Tier A/B/C classification)
backtest.py          — 365-day backtesting engine with multi-template harness + CPCV + DSR
tracker.py           — web dashboard API (port 8888)
tracker_html.py      — dashboard frontend (single-file HTML/JS)
indicators.py        — RSI, ATR, ADX, Bollinger, structure helpers
phase2_data.py       — CoinGecko dominance + market stats
```

**Sprint 1 — Operational resilience (2026-05-22):**
```
heartbeat.py            — Dead-man's switch + multi-channel alerter (Telegram + SMTP fallback)
state_store.py          — Atomic JSON state persistence (temp+fsync+os.replace) + PidFile
backtest_checkpoint.py  — Per-token checkpoint so killed backtests resume
scripts/watchdog.py     — External heartbeat watchdog sidecar
scripts/supervisord.conf, run_supervised.bat, run_watchdog.bat
```

**Sprint 2 — Config + statistical foundation (2026-05-22):**
```
config.py               — Single source of truth for all tunables + env-var overrides
secrets_loader.py       — .env / .env.vault secrets loader (TELEGRAM_TOKEN, CHAT_ID, etc.)
labeling.py             — Triple-barrier labels + bootstrap CI (Lopez de Prado AFML 2018)
scripts/backtest_regression.py + .github/workflows/backtest_gate.yml — CI regression gate
```

**Sprint 3 — Honest metrics + observability (2026-05-22/23):**
```
validation.py           — CPCV + PSR + DSR (Bailey/Lopez de Prado 2014) — honest-metrics workhorse
monitoring.py           — OGD weight-degeneration sidecar (read-only) — daily health check
event_calendar.py       — FOMC/CPI/NFP macro filter (advisory default per Red Flag #13)
tests/test_ict_oracle.py — Independent SMC oracle for 7 ict_engine functions
backtest.py OHLCV cache — TTL + atomic write + schema validation + forming-candle drop
```

---

## Signal Pipeline

Each 5-minute cycle runs through a fixed sequence:

```
1. Fetch OHLCV  →  5M / 1H / 4H candles (Binance REST)
2. Data quality  →  gap detection (5M ≥3 bars, 1H ≥2 bars, 4H ≥1 bar blocks signal)
3. ICT sweep     →  BSL or SSL swept within last 30 bars
4. Displacement  →  momentum candle confirms sweep within 9 bars
5. MSS           →  market structure shift confirmed within 30 bars of sweep
6. FVG           →  fair value gap present and unmitigated (quality: HIGH/MEDIUM/LOW)
7. Dealing range →  price in premium (SELL) or discount (BUY) zone
8. 4H bias       →  higher-timeframe directional alignment
9. 1H trend      →  intermediate trend confirmation
10. Regime gate  →  RANGING/CHOPPY regimes suppressed or blocked
11. Killzone     →  NY AM / London / Asia sessions only
12. EV gate      →  expected value positive over 100+ signal history
13. Template     →  Tier A/B/C ICT variant classification
14. OGD score    →  per-token adaptive confidence (1–10)
15. Conf floor   →  signal blocked if below dynamic confidence floor
```

---

## Tokens Monitored

| Token | Pair | Notes |
|---|---|---|
| BTC | BTCUSDT | Benchmark — used as correlation reference |
| ETH | ETHUSDT | |
| XRP | XRPUSDT | |
| HBAR | HBARUSDT | |
| AVAX | AVAXUSDT | |
| LINK | LINKUSDT | |
| BNB | BNBUSDT | |
| ADA | ADAUSDT | |
| POL | POLUSDT | MATIC renamed Sep 2024 |
| LTC | LTCUSDT | BTC-derivative structure |

> SOL removed (Run 69 post-fix WR=27.3%, chronically below break-even).

---

## ICT Detection Modules

### Sweep Detection (`ict_engine.py`)
- Scans last 30 bars for BSL (buy-side) or SSL (sell-side) liquidity sweep
- Validates sweep wick extends beyond prior swing high/low (ICT_SWING_N=2)
- Scores sweep quality: wick depth, bar count, volume context

### Market Structure Shift (`ict_engine.py:144`)
- Confirms MSS within 30 bars after sweep
- Scores: displacement body size, close above/below structure, retest quality
- Quality gate: HIGH/MEDIUM/LOW enforced by LIVE_CONFIG.mss_min_quality

### Fair Value Gap (`ict_engine.py:227`)
- Three-candle FVG pattern detection
- Quality scoring: gap size relative to ATR, position within dealing range
- iFVG (inverse FVG) detection for entry confirmation
- Quality gate: HIGH/MEDIUM/LOW enforced by LIVE_CONFIG.fvg_min_quality

### Dealing Range (`ict_engine.py:383`)
- Dynamic premium/discount zone from last N swing points
- Classifies price location: PREMIUM / DISCOUNT / EQUILIBRIUM
- Required: BUY in DISCOUNT, SELL in PREMIUM

### SMT Divergence (`ict_engine.py:476`)
- Detects correlated-pair non-confirmation (e.g. BTC fails to sweep with ETH)
- Adds confidence penalty when missing, bonus when confirmed

### Trade Plan (`ict_engine.py:666`)
- TP1: 1:1 RR (sweep wick to MSS)
- TP2: 1.5:1 RR
- TP3: next liquidity pool (opposing swing level)
- SL: beyond sweep wick with buffer

---

## Adaptive Learning System

Three connected layers that improve signal quality over time:

### Layer 1 — OGD Per-Token Weights (`adaptive_engine.py`)
Online Gradient Descent updates 6 feature weights per token on every closed trade:
`fvg_quality`, `mss_quality`, `session`, `confidence`, `trend_strength`, `dr_location`

Weights are persisted to `data/signals.db` and survive restarts. Backtest history warm-starts weights before live trades accumulate (bootstrap isolation — separate table from live weights).

7-day decay suppression: `decay_toward_default()` skips tokens updated within 7 days, protecting freshly learned weights from being eroded between rare signals.

### Layer 2 — Scalar Performance State (`crypto_alert.py:511`)
Every 30 minutes, `load_performance_state()` reads live trade history and adjusts:
- `_conf_floor` — raised above the highest-losing confidence level (WR < 40%)
- `_signal_threshold_adj` — tightens gate for RANGING/UNKNOWN regime signals
- Per-token WR gate — adds +1/+2 confidence floor for tokens below 35% recent WR
- EV gate — blocks signals with statistically negative expected value (n ≥ 100)

### Layer 3 — Tune Bot (Gate Parameter Tuning)
Analyzes backtest with 60/40 train/test walk-forward split. Proposes changes to `strategy_engine.py` LIVE_CONFIG only when a finding holds in **both** halves:
- `FVG_MIN_QUALITY`, `MSS_MIN_QUALITY` — quality gate thresholds
- `SESSION_LIQUID_HOURS` — remove chronically low-WR trading hours
- `CONF_FLOOR_RAISE` — raise minimum confidence floor

Guards: frequency gate (50 new signals OR 14 days), max 2 APPLIED entries, Wilson CI overlap check, walk-forward gap warning (>15pp = overfitting risk). Post-apply WR verdict (VERIFIED_BETTER / VERIFIED_WORSE) fires Telegram alert if performance degrades.

---

## ICT Strategy Variant Templates

Signals are classified into Tier A / B / C variants by `strategy_templates.py`:

| Tier | Live Execution | Daily Cap | Description |
|---|---|---|---|
| Tier A | Yes (≥50 closed trades) | 3/day | Highest-confluence ICT setups |
| Tier B | Yes (≥50 closed trades) | 2/day | Standard ICT setups |
| Tier C | Paper only | 0 | Experimental — never live |

Template safety controls: circuit breaker pauses a template if rolling WR drops below 55% over 20 signals. RANGING regime blocks Tier B/NONE templates.

---

## Risk Management

| Control | Value | Notes |
|---|---|---|
| Risk per trade | 1% of capital | Position size scales with SL distance |
| Max open positions | 4 (live) / unlimited (paper) | Portfolio-level cap |
| Daily loss limit | 3% of capital | Auto-kill switch |
| Weekly loss limit | 8% of capital | Auto-kill switch |
| Max consecutive losses | Configurable | Kill switch fires on breach |
| Drawdown gate | Configurable | Blocks new signals during drawdown |

Kill switches are active in both PAPER and LIVE mode.

---

## Quick Start

### 1. Prerequisites
- Python 3.10+
- Windows (scripts use `.bat`)
- VPN required for Binance access in the Philippines

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
Copy `env.example.bat` → `env.bat` and fill in your values:
```bat
set TELEGRAM_TOKEN=your_token_here
set CHAT_ID=your_chat_id_here
set EXECUTION_MODE=PAPER
set YOUR_CAPITAL=1000
```

> Never hardcode tokens. Always set via `env.bat` — the bot refuses to start if `TELEGRAM_TOKEN` is missing.

### 4. Run the bot
```bat
scripts\start_bot.bat
```

### 5. Run the dashboard (separate terminal)
```bat
scripts\start_tracker.bat
```
Open: **http://localhost:8888**

### 6. Run a backtest (VPN required)
```bash
python backtest.py
```
Results stored in `data/signals.db` and `data/backtest_results.json`. After backtest, open the dashboard → Backtest tab to view performance and run Tune Bot analysis.

---

## Dashboard Tabs

| Tab | What It Shows |
|---|---|
| **Overview** | Open positions, TP progress, live stats (WR, total signals, P&F) |
| **Signal History** | All signals with filters, sorting, pagination |
| **AI Intelligence** | Bot health score, per-token OGD weights, adaptive learning state |
| **Backtest** | Run history, template performance report, Tune Bot panel, Tune History with rollback |

---

## Execution Modes

| Mode | Behavior |
|---|---|
| `PAPER` | All signals sent to Telegram with paper labels. Kill switches active. OGD learns. |
| `LIVE` | Only ACTIVE-template signals sent. All safety gates enforced. Requires `LIVE_MODE_CONFIRMED=YES`. |

> Switching to LIVE requires two explicit steps: change `EXECUTION_MODE=LIVE` in `env.bat` AND set `LIVE_MODE_CONFIRMED=YES`. The bot validates both at startup.

---

## Project Layout

```
TradeAI/
├── crypto_alert.py        — main signal bot (24/7 loop)
├── ict_engine.py          — ICT detection: sweep, MSS, FVG, DR, iFVG, SMT, trade plan
├── strategy_engine.py     — shared gate engine (LIVE_CONFIG / BACKTEST_CONFIG)
├── adaptive_engine.py     — OGD, EV scoring, DriftDetector, PortfolioRiskLayer
├── strategy_templates.py  — ICT variant template registry (Tier A/B/C)
├── backtest.py            — backtesting engine + multi-template harness
├── tracker.py             — web dashboard API server (port 8888)
├── tracker_html.py        — dashboard HTML/JS (single file)
├── indicators.py          — RSI, ATR, ADX, Bollinger, candle structure
├── phase2_data.py         — CoinGecko market dominance + market stats
│
├── data/
│   ├── signals.db         — SQLite: signals, results, weights, tune_history, backtest runs
│   └── backtest_results.json
│
├── backups/               — auto-created .bak files before every Tune Bot apply
│
├── docs/
│   ├── comprehensive/     — CROSS_REF.md, FIX_LOG.md, TEAM_WORKFLOW.md
│   ├── ict_strategy_variant_learner/   — ICT phase status + implementation reports
│   └── adaptive_tunebot/ — TuneBot phase status + implementation reports
│
├── tests/
│   ├── test_tunebot.py              — Tune Bot apply/rollback/isolation tests (31 tests)
│   └── test_tracker_db_alignment.py — DB schema + API alignment tests (98 tests)
│
├── scripts/
│   ├── start_bot.bat      — launch signal bot
│   └── start_tracker.bat  — launch web tracker
│
├── env.example.bat        — environment variable template
├── requirements.txt
└── README.md
```

---

## Development Workflow

The project uses a multi-agent review system via Claude Code. Key workflow types:

| Command | What It Does |
|---|---|
| `/tradeai-health` | Quick GREEN/YELLOW/RED status check (5 min) |
| `/tradeai-audit` | Full parallel audit — 8 specialist agents (30–60 min) |
| `/tradeai-pre-live` | Pre-live GO/NO-GO checklist |

Specialist agents cover: ICT logic, backtest bias, live/backtest consistency, risk management, data pipeline, adaptive learning, OGD weights, template tier calibration, and signal performance analysis.

See `docs/comprehensive/TEAM_WORKFLOW.md` for the full autonomous improvement loop.

---

## Roadmap

| Phase | Status | Description |
|---|---|---|
| ICT I-1 → I-5A | Complete | Signal pipeline, template registry, backtest harness, safety controls |
| ICT I-5B / I-6 | Data-gated | Per-template OGD weights — needs N ≥ 30 live signals per template |
| TuneBot Phase 0–3 | Complete | DB schema, OGD foundation, walk-forward tuning, dashboard |
| TuneBot Phase 2 Step 2 | Data-gated | OGD retrain from live — needs 30+ closed live trades |
| Live paper collection | Not started | Blocked on Telegram token rotation (BotFather) |

---

## Notes

- **Signal-only** — no auto-trading, no API keys for execution, no order placement.
- Backtest WR from Run 60 (85.3%) is **pre-fix and invalid** — run a fresh backtest after any significant code change.
- All Telegram tokens via environment variables only — never hardcoded.
- After applying Tune Bot changes, **restart the bot** for `strategy_engine.py` to reload.
