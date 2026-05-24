# TradeAI — Claude Code Project Context

**Project:** TradeAI v13 — ICT (Inner Circle Trader) Crypto Signal Bot
**Owner:** Operator (Cebu, Philippines)
**Current state:** PAPER mode running 24/7 on Contabo VPS Singapore
**Last updated:** 2026-05-24

This file is the canonical project context for any Claude Code session opening this repo. Read it FIRST before making any changes.

---

## 1. What this bot does

A directional crypto signal bot using ICT methodology:
- Detects liquidity sweeps on 5M candles across 10 tokens (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON)
- Confirms via MSS (Market Structure Shift) + FVG (Fair Value Gap)
- Sends Telegram alerts to operator with entry, SL, TPs
- **Operator manually executes** — bot is signal-only, no auto-trading
- Has adaptive learning (OGD per-token weights), honest validation (CPCV + DSR), and autonomous R&D explorer (Optuna)

---

## 2. Current operational state (as of 2026-05-24)

### Execution mode
- `EXECUTION_MODE=PAPER` — signals only, no real trading
- LIVE switch requires: `EXECUTION_MODE=LIVE` + `LIVE_MODE_CONFIRMED=YES` env vars + `YOUR_CAPITAL` set
- **LIVE never auto-flips** — always operator-deliberate

### Canonical baseline
- **Run-168** = current Pareto-optimal baseline
- Stacked promotions: F-8 (`bias_4h_gate: strict→none`) + P-2b (`ICT_SWEEP_LOOKBACK: 30→20`) + TP-2-b (`TREND_1H_GATE: loose→strict`)
- Metrics: n=43, WR=79.1%, CPCV mean=79.11%, CPCV std=5.40%, Sharpe=0.933, DSR=100% [n_trials=27]
- Snapshot: `data/snapshots/signals_baseline_run168_20260524_0826_tp2b_promoted_honest.db`
- Honest cross-config `sr_trial_std=0.0836` from 24 distinct configs

### Deployment
- **VPS:** Contabo Cloud VPS 10 Singapore (4 vCPU, 8GB RAM, 75GB NVMe NVMe)
- **OS:** Ubuntu 24.04 LTS
- **User:** `tradeai` (sudo for systemctl tradeai* + journalctl only)
- **Path on VPS:** `/home/tradeai/TradeAI/`
- **Services running 24/7:**
  - `tradeai.service` — the bot
  - `tradeai-tracker.service` — dashboard on port 8888 (SSH-tunnel only, never public)
  - `tradeai-watchdog.service` — heartbeat monitor + Telegram alerts on freeze
- **Dashboard access:** SSH tunnel `LocalForward 8888 127.0.0.1:8888` then `http://localhost:8888` on local PC
- **Source of truth:** GitHub private repo `leomerjhonparba/tradeai-bot`

---

## 3. The 4-phase autonomous explorer (built 2026-05-24)

All shipped + audited + bug-fixed.

| Phase | What | Key files |
|-------|------|-----------|
| 1 — Core loop | Optuna Bayesian search over existing backtest engine | `scripts/autonomous_explorer.py`, `data/explorer_learning.db`, env-overrides in `ict_engine.py` |
| 2 — Anti-overfit guard | PidFile, pre-cache warm, 4 trip conditions, Telegram, `--status` | Same file + `data/explorer_session.json` |
| 3 — Auto-promotion | 8-criteria gate + reproducibility re-run + 2/day cap + 24h soak | `scripts/promote_baseline.py --auto`, `data/pareto_archive.json`, `data/promotion_log.json` |
| 4 — Dashboard | "🤖 Auto-Explorer" tab in tracker_html.py + 4 API routes + `--digest` CLI | `tracker.py`, `tracker_html.py` |

### Critical safety invariants (DO NOT VIOLATE)
- Explorer **NEVER** auto-flips LIVE
- Auto-promotion writes baseline_pin.json + tune_history only (status=AUTO_PROMOTED)
- Reproducibility required: 2 backtests with matching config_hash + ±0.5pp cpcv_mean
- 2/day cap + 24h soak between auto-promotions
- Explorer trials are NOT counted in DSR pool (prevents death spiral)
- Anti-pattern locks: `ICT_SWING_N=2`, `ICT_MIN_RR_GATE=1.5` (asserted at session start)
- Only ONE backtest engine active at a time (manual + explorer mutually exclusive — operator discipline)
- vectorbt **REJECTED** — would force re-implementation, breaks live/BT parity. Never re-propose.

### Post-audit fixes (2026-05-24)
- **C1**: Race condition — explorer uses `MAX(backtest_runs.id)` snapshot + scoped lookup to avoid deleting concurrent operator backtest rows
- **H1**: Try/finally cleanup wrapper prevents orphan rows on exception path
- **M2**: q05 eligibility gate actually checks q05 (was dormant)
- **M3**: cross_config_std read uses read-only SQLite mode
- **M4**: rollback writes real previous-pin run_id (was literal `?`)
- **L1**: Startup assertion verifies anti-pattern locks haven't drifted
- **L4**: Telegram rate-limit on repeated promote failures (1 per session)

---

## 4. The 3-agent operator-driven pipeline (parallel system)

Pre-existing, separate from autonomous explorer:

| Agent | Role | Status |
|-------|------|--------|
| `backtest-explorer` | Test specific hypotheses, log, REVERT (never modify) | SHIPPED 2026-05-23 |
| `backtest-pattern-analyzer` | Cross-cycle synthesis, find robust patterns | TODO |
| `backtest-optimizer` | Apply promoted patterns to live config | SHIPPED 2026-05-23 |

Coexists with autonomous explorer:
- Operator-driven (3-agent) = ad-hoc, hypothesis-driven
- Autonomous explorer = standing background search

When operator runs the 3-agent agent, they should **pause** autonomous explorer first for clean DSR pool accounting.

See `docs/OPTIMIZATION_AGENT_PIPELINE.md` and `docs/AUTONOMOUS_EXPLORER_DESIGN.md`.

---

## 5. Honest metrics integration

Every trial + every promotion uses the same honest pipeline:

| Metric | Source |
|--------|--------|
| CPCV WR mean / std / q05 | `validation.py` (Lopez de Prado 2018 CPCV) |
| DSR (Deflated Sharpe Ratio) | `validation.py` (Bailey/LdP 2014) |
| Cross-config sr_trial_std | `bot_state.cross_config_sr_trial_std` (FIX 1 Part 2, 2026-05-23) |
| dsr_proxy_used flag | Captured per trial in `explorer_learning.db` |

After every auto-promotion, `compute_cross_config_sr_std.py` runs to refresh the pool.

**LIVE clearance gate (all 3 required):**
- CPCV mean WR ≥ 60%
- DSR ≥ 95% (honest cross-config std, NOT within-fold proxy)
- ≥30 closed paper signals

---

## 6. Operator preferences (FROM CONVERSATIONS — RESPECT THESE)

### Always
- Operator wants **full autonomous lead** — make decisions, coordinate agents, fix issues proactively
- After every fix: run tests → deploy review agents → present summaries (workflow protocol)
- Cebuano/English mix is fine — operator is Filipino
- Never use emojis unless operator explicitly requests
- Honest scoring — actual scores, not optimistic ones
- **Don't proactively spawn Claude subagents** unless explicitly asked

### Specifically for this project
- Never auto-flip to LIVE
- Never widen `BACKTEST_DAYS=730` (Cycle Z dead-zone: 2024 data is dead-zone for FVG=HIGH variant)
- Never re-propose vectorbt (rejected; breaks parity)
- Never re-propose previously-rejected tokens: SOL, DOT, NEAR, SUI, LTC (all proven chronic underperformers; documented in `config.py:130-138`)
- Operator preferred **no auto-scheduler** for explorer — manually triggers all sessions
- QuantStats tab in dashboard HIDDEN until LIVE trading produces real P&L (`tracker_html.py:635` style="display:none")

### Workflow specifics
- Uses VSCode Remote SSH to edit VPS files
- Uses tmux for any long-running command (`tmux new -s X` then `Ctrl+B D` to detach)
- Uses Git workflow: edit → push → `git pull` on VPS → `sudo systemctl restart tradeai`

---

## 7. Strategy parameter state (canonical Run-168)

### Active gates
```python
# config.py
LIVE_BIAS_4H_GATE = "none"           # F-8
LIVE_TREND_1H_GATE = "strict"        # TP-2-b
LIVE_DEALING_RANGE_GATE = True       # DR-1 known structural (LIVE=True / BT=False)
LIVE_MSS_MIN_QUALITY = "LOW"
LIVE_FVG_MIN_QUALITY = "HIGH"        # binding gate
LIVE_SMT_GATE = False
```

### ICT constants
```python
# ict_engine.py (now env-overridable per Phase 1)
ICT_SWING_N = 2                                  # LOCKED — anti-pattern at ≥3
ICT_SWEEP_LOOKBACK = _env_int("ICT_SWEEP_LOOKBACK", 20)   # P-2b promoted
ICT_MSS_HORIZON = _env_int("ICT_MSS_HORIZON", 30)
ICT_FVG_MIN_GAP = _env_float("ICT_FVG_MIN_GAP", 0.001)
DEALING_RANGE_LOOKBACK = _env_int("DEALING_RANGE_LOOKBACK", 50)
ICT_MIN_RR_GATE = 1.5                            # LOCKED — anti-pattern at ≥2.0
```

### Confirmed anti-patterns (documented; do not re-test)
- `ICT_SWING_N ≥ 3` → −3.9pp WR / −0.07 Sharpe (Cycle 1b P-1, 1c TP-5c′)
- `ICT_MIN_RR_GATE ≥ 2.0` → catastrophic (n=10, WR=50%) (Cycle 1b)
- `BACKTEST_FVG_MIN_QUALITY = LOW/MEDIUM` → coin-flip WR (~44%) (TP-1 grid)
- `BACKTEST_BIAS_4H_GATE = strict` (at 365d) → high variance (n=37, std=15.6%) (D-2 reversal)
- `BACKTEST_DAYS = 730` → averages 2024 dead-zone (Cycle Z; never use)
- Adding SOL/DOT/NEAR/SUI/LTC tokens → chronic underperformers (documented)

### Confirmed inert at current config (don't waste cycles testing)
- `ICT_MSS_HORIZON` (30 vs 15) — FVG=HIGH gate dominates
- `ICT_FVG_MIN_GAP` (0.001 vs 0.0015) — FVG=HIGH gate dominates
- `ICT_EQH_TOLERANCE` (not in config_hash; bonus inert)
- `ICT_FVG_SIZE_BONUS_THRESHOLD` (not in config_hash; bonus inert)

---

## 8. File structure

```
TradeAI/
├── crypto_alert.py        # The bot (main loop, signal generation)
├── backtest.py            # Backtest engine
├── ict_engine.py          # ICT logic (sweep, MSS, FVG, swings)
├── adaptive_engine.py     # OGD weight learning, portfolio gates
├── strategy_engine.py     # Signal scoring, gate logic
├── strategy_templates.py  # Tier A/B/C template definitions
├── validation.py          # CPCV + PSR + DSR (Lopez de Prado)
├── labeling.py            # Triple-barrier labeling
├── monitoring.py          # OGD weight monitor (read-only)
├── tracker.py             # Dashboard HTTP server (port 8888)
├── tracker_html.py        # Dashboard HTML/CSS/JS (single-file template)
├── quantstats_report.py   # QuantStats integration (tab hidden until LIVE)
├── heartbeat.py           # Bot heartbeat writer
├── state_store.py         # PidFile + atomic JSON persistence
├── secrets_loader.py      # .env loader
├── event_calendar.py      # FOMC/CPI/NFP windows (macro filter, default OFF)
├── config.py              # All config: gates, tokens, risk, env-overrides
├── indicators.py          # Trend / RSI / ATR / regime detection
├── scripts/
│   ├── autonomous_explorer.py       # Phases 1-4 autonomous R&D
│   ├── promote_baseline.py          # Operator + auto-promotion path
│   ├── compute_cross_config_sr_std.py  # Honest DSR pool refresher
│   ├── snapshot_baseline.py         # signals.db snapshots
│   └── watchdog.py                  # Heartbeat monitor (runs as service)
├── deploy/
│   ├── tradeai.service              # systemd unit for bot
│   ├── tradeai-tracker.service      # systemd unit for dashboard
│   ├── tradeai-watchdog.service     # systemd unit for watchdog
│   ├── bootstrap_vps.sh             # one-time VPS setup
│   └── env.example                  # .env template
├── docs/
│   ├── AUTONOMOUS_EXPLORER_DESIGN.md
│   ├── ENTERPRISE_ROADMAP.md        # locked triage + phased plan
│   ├── OPTIMIZATION_AGENT_PIPELINE.md
│   ├── comprehensive/CROSS_REF.md   # every prior issue's resolution status
│   └── exploration_runs/            # explorer cycle reports
├── data/                            # GITIGNORED — VPS-only operational data
│   ├── signals.db                   # main DB (signals + backtest_runs + bot_state)
│   ├── explorer_learning.db         # autonomous explorer trials
│   ├── optuna_study.db              # Optuna Bayesian state
│   ├── baseline_pin.json            # canonical baseline reference
│   ├── pareto_archive.json          # top-10 non-dominated configs
│   ├── promotion_log.json           # 30-entry rolling audit
│   ├── snapshots/                   # signals.db snapshots
│   └── ohlcv_cache/                 # Binance candle cache
├── logs/                            # GITIGNORED — bot/tracker/watchdog stdout
├── tests/                           # 375+ unit tests (test_validation, test_labeling, etc.)
├── .claude/
│   ├── agents/                      # subagent definitions
│   ├── skills/                      # operator-invocable skills
│   ├── reports/                     # audit reports
│   └── settings.json                # local Claude Code settings
└── CLAUDE.md                        # ← this file
```

---

## 9. Daily operator workflow

### Standard ops
```bash
# Connect to VPS via VSCode Remote SSH
# (Status bar shows: SSH: tradeai-vps)

# Edit any file → Ctrl+S (saved directly on VPS)

# Restart bot to apply changes
sudo systemctl restart tradeai

# Watch live logs
journalctl -u tradeai -f
# or
tail -f ~/TradeAI/logs/bot.log

# Open dashboard (via SSH tunnel auto-forwarded)
# Browser → http://localhost:8888
```

### Backtests (one-off, ~11 min)
```bash
# Easiest: click "Run Backtest" button on Backtest tab
# Or terminal:
cd ~/TradeAI && python3 backtest.py
```

### Autonomous explorer (overnight, 5-18 hours)
```bash
# ALWAYS in tmux for survival on disconnect
tmux new -s explorer
cd ~/TradeAI
python3 scripts/autonomous_explorer.py --trials 30
# Detach: Ctrl+B then D
# Reattach: tmux attach -t explorer

# Check status without attaching:
python3 scripts/autonomous_explorer.py --status

# Stop early:
# Attached: Ctrl+C
# Detached: pkill -f autonomous_explorer.py
```

### Git workflow
```bash
cd ~/TradeAI
git add . && git commit -m "describe change" && git push
# (PAT cached, no password needed)

# To sync changes from local PC to VPS:
# Push from local → git pull on VPS
```

### Rollback
```bash
# Rollback a baseline promotion
python3 scripts/promote_baseline.py --rollback-to-run <prior_run_id>

# Restore signals.db from snapshot
python3 scripts/snapshot_baseline.py --restore <snapshot_filename>
```

---

## 10. Recent work timeline (most recent first)

| Date | Event |
|------|-------|
| 2026-05-24 | VPS deployment (Contabo Singapore), GitHub repo setup, systemd services, watchdog enabled |
| 2026-05-24 | FAQ modal system: 7 detailed FAQ pages, "Learn more" buttons on every tab |
| 2026-05-24 | Autonomous Explorer Phases 1-4 shipped + audited + 6 polish fixes + 2 critical bug fixes |
| 2026-05-24 | QuantStats tab hidden (will re-enable when LIVE P&L flows) |
| 2026-05-24 | Adaptive ETA (paper progress) + D-pilot rejected DOT/NEAR |
| 2026-05-24 | TP-2-b PROMOTED → Run-168 baseline (TREND_1H_GATE strict, CPCV 79.11%, DSR 100% honest) |
| 2026-05-23 | P-2b PROMOTED → Run-143 baseline (ICT_SWEEP_LOOKBACK 30→20) |
| 2026-05-23 | F-8 PROMOTED → Run-128 baseline (bias_4h_gate strict→none) |
| 2026-05-23 | QuantStats integration (16 metric cards + inline tearsheet) |
| 2026-05-23 | Sprint 3 honest metrics shipped: CPCV + DSR + PSR (Lopez de Prado) |
| 2026-05-22 | 3-agent pipeline (explorer + optimizer shipped, analyzer pending) |
| 2026-05-22 | Sprint 2: config.py SSoT + secrets_loader + CI gate |
| 2026-05-22 | Sprint 1: heartbeat + watchdog + state_store + 18 tests |
| 2026-05-22 | Full audit cycle 12 → 9.025/10 overall (autonomous loop terminated) |

---

## 11. How to resume work mid-stream

If you're a new Claude session opening this repo and the operator says "continue where we left off":

1. **Read** this file (you're doing it now)
2. **Check** the latest entry in section 10 (Recent work timeline) for what was last shipped
3. **Open** `data/baseline_pin.json` to confirm current baseline
4. **Run** these to see live state:
   ```bash
   python3 scripts/autonomous_explorer.py --status        # explorer state
   sudo systemctl status tradeai tradeai-tracker tradeai-watchdog  # services
   tail -20 ~/TradeAI/logs/bot.log                          # bot health
   ```
5. **Skim** `docs/AUTONOMOUS_EXPLORER_DESIGN.md` for architecture
6. **Check** `docs/comprehensive/CROSS_REF.md` for "what's already done" before re-proposing anything
7. Ask operator what they want to do next

---

## 12. Cross-references

- **Design docs:** `docs/AUTONOMOUS_EXPLORER_DESIGN.md`, `docs/OPTIMIZATION_AGENT_PIPELINE.md`, `docs/ENTERPRISE_ROADMAP.md`
- **Audit history:** `docs/comprehensive/CROSS_REF.md`, `.claude/reports/tradeai-audit/`
- **Exploration logs:** `docs/exploration_runs/` (Cycle 1, 1b, 1c, Tier-2 grids)
- **Operator skills:** `.claude/skills/` (tradeai-audit, tradeai-backtest, tradeai-health, etc.)
- **Subagents:** `.claude/agents/` (backtest-explorer, backtest-optimizer, etc.)

---

## 13. Things this Claude session should NEVER do without explicit operator approval

1. Flip EXECUTION_MODE to LIVE
2. Push commits to public repos
3. Run live trades (bot has no trade execution code, but never add it without consent)
4. Add vectorbt, freqtrade, FinRL, hummingbot, or any rejected library
5. Re-test confirmed anti-patterns (SWING_N≥3, MIN_RR≥2.0, FVG=LOW/MEDIUM, BACKTEST_DAYS=730, rejected tokens)
6. Auto-flip the autonomous explorer to a more aggressive auto-promote schedule
7. Modify `signals.db` directly (only via bot writes or `scripts/snapshot_baseline.py --restore`)
8. Bypass the honest metrics pipeline (CPCV / DSR cross-config)
9. Re-introduce within-fold sr_trial_std proxy (use honest cross-config std only)
10. Delete the `data/snapshots/` folder

---

**End of CLAUDE.md. Future sessions: this is your project brain. Trust it but verify current state via `--status` commands before making changes.**
