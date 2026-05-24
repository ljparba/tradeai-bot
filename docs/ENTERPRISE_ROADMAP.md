# TradeAI Enterprise Upgrade Roadmap

**Source:** Triage of `docs/tradeai_research/TradeAI_Research_Report.md`
**Date locked:** 2026-05-22
**Status:** Authoritative — all agents and skills must check `STATUS` column before recommending duplicate work.

---

## How agents/skills should use this document

1. Before recommending any new library, algorithm, or infrastructure change, **grep this file** for the item name. If it appears as `REJECT`, `DEFER`, or `DONE`, do not re-propose it without new evidence.
2. The **Phased Roadmap** (Section 4) is the canonical execution order. Do not skip phases.
3. The **Top 10 Priority Items** (Section 3) is the active work queue. Pick the topmost item with `STATUS = TODO`.
4. When a task is completed, update its `STATUS` to `DONE` with the date and a one-line outcome.
5. **Red Flags** (Section 5) are hard invariants. Any PR that violates one must be rejected.

---

## 0. Related Architecture Docs

- [`docs/AUTONOMOUS_EXPLORER_DESIGN.md`](./AUTONOMOUS_EXPLORER_DESIGN.md) — **Autonomous explorer (Optuna-based)** — nightly self-driving search over existing backtest engine. Phased 5-day project. Design APPROVED 2026-05-24; implementation pending operator approval gate.
- [`docs/OPTIMIZATION_AGENT_PIPELINE.md`](./OPTIMIZATION_AGENT_PIPELINE.md) — **3-agent flow** (Explorer → Analyzer → Optimizer) for OPERATOR-DRIVEN pattern discovery. Explorer + Optimizer SHIPPED 2026-05-23. Will coexist with autonomous explorer (manual = ad-hoc; autonomous = standing search).
- [`docs/ROADMAP_AUDIT_CROSSCHECK.md`](./ROADMAP_AUDIT_CROSSCHECK.md) — cross-check vs TradingAgents investigation audit.
- [`docs/comprehensive/CROSS_REF.md`](./comprehensive/CROSS_REF.md) — every prior issue's resolution status.
- [`docs/comprehensive/FIX_LOG.md`](./comprehensive/FIX_LOG.md) — permanent fix history.

---

## 1. Executive Summary

- **Sample-size discipline is the binding constraint.** ~150 trades over 3 years means every recommendation must be evaluated against curse-of-dimensionality risk first, lift second.
- **The research report's ranking is mostly correct, but soft on overfit.** Meta-labeling, Optuna, and HMM regime conditioning are PILOT (not ADOPT) until CPCV-validated.
- **Pre-LIVE hardening is more urgent than any WR lift.** Dead-man's switch, supervisord state persistence, CI regression gate, and CPCV/DSR honest-metrics overhaul ship before any new alpha source.
- **Reject all paid feeds, all RL for signals, all GPL/BSL libraries, all auto-feature-generation (tsfresh).** Coinglass free tier + yfinance is the entire external-data budget.
- **Single biggest blind spot in the report:** operator ergonomics — no kill-switch, no audit trail, no position reconciliation, no exchange failover. These are enterprise-grade gaps that must close before LIVE.

---

## 2. Triage Table

| Item | Bucket | One-line reason |
|---|---|---|
| vectorbt | REJECT | BSL 1.1 license is not OSI open-source; commercial use requires license and the custom engine works. |
| nautilus_trader | DEFER | 2–4 wk rewrite + LGPL; trigger only if measured execution latency or fill quality becomes the bottleneck. |
| backtrader | REJECT | GPL 3.0 contaminates the codebase. |
| Lean (QuantConnect) | REJECT | C#-core full-stack replacement is wildly disproportionate to a ~50/year bot. |
| Order-book lib | DEFER | DIY from Binance depth stream when microstructure features are actually wired into a template. |
| pandas-ta | ADOPT | MIT, drop-in TA refactor; replaces hand-rolled indicators with maintained code. |
| ta-lib | DEFER | Underlying C lib is LGPL; pandas-ta is more actively maintained — only revisit for raw-array speed. |
| tsfresh | REJECT | 700+ auto-features × 150 samples = guaranteed false discovery even with BH-FDR. |
| mlfinlab (CPCV + DSR + triple-barrier) | ADOPT | BSD; the single most important library for this sample size — three independent wins. |
| skfolio (ERC) | ADOPT | BSD; clean ERC for multi-position sizing when >1 template fires concurrently. |
| Optuna | PILOT | Useful only with ≤5 params + CPCV splitter; otherwise silent curve-fitter. |
| Hyperopt | REJECT | Superseded by Optuna in every dimension. |
| hmmlearn | PILOT | Lift plausible but state-count tuning leaks; validate on CPCV before promoting. |
| ruptures | ADOPT | Offline-only label construction; never wire to live (lookahead). |
| statsmodels MarkovRegression | DEFER | Redundant with hmmlearn if HMM PILOT succeeds. |
| river (ADWIN) | ADOPT | Closes the "OGD has no idea it's drifting" gap. |
| river (bandits / Thompson) | PILOT | A/B vs OGD on paper before any live promotion. |
| alibi-detect | DEFER | Heavier than river; revisit when monthly feature-distribution monitoring is needed. |
| Meta-labeling (LogReg) | PILOT | Highest WR upside AND highest overfit risk — must use ≤6 features + CPCV + DSR. |
| Triple-barrier labeling | ADOPT | Upstream of every honest metric; cheap, no overfit risk. |
| Half-Kelly + ATR sizing | ADOPT | Direct Sharpe lift; replaces flat % sizing with no overfit exposure. |
| Ensemble 2-of-3 voting | PILOT | Will sharply drop signal count; needs frequency-vs-WR tradeoff measured. |
| Regime conditioning | PILOT | Depends on HMM PILOT; gate it behind that result. |
| Coinglass (funding + OI + liq clusters) | ADOPT | Free tier covers it; strongest non-price signal for 1H–4H crypto. |
| Hyblock | REJECT | $50/mo for marginal lift over Coinglass free. |
| Velo Data | REJECT | $99/mo exceeds budget posture. |
| News/macro blocklist | ADOPT | Hours of effort, eliminates a known class of false signals. |
| Weight entropy + degeneration suite | ADOPT | 2-hour add; diagnoses the failure mode that killed Run-46. |
| RL for signals | REJECT | Sample size impossible; reward-hacking is endemic in literature. |
| Bayesian / Kalman online weights | PILOT | Promising for low-data regime but defer until OGD failure modes are characterized. |
| Glassnode / Santiment / CryptoQuant | DEFER | Lagging or noisy at 1H–4H timeframe. |
| DXY / SPX cross-asset SMT (yfinance) | ADOPT | Free, 1–2 days, modest but real lift. |
| BTC dominance, PDH/PDL, weekly open | ADOPT | Pure ICT structural levels. |
| Asian range explicit levels | ADOPT | Verify whether already in ict_engine; if not, ship. |
| DuckDB | PILOT | Defer until analytics queries become slow. |
| TimescaleDB | REJECT | Only justified at tick-data ingestion scale, which this bot does not need. |
| Prometheus + Grafana | ADOPT | Required for enterprise operability. |
| PagerDuty | DEFER | Telegram + dead-man's switch + secondary alert channel is sufficient for solo. |
| Dead-man's switch | ADOPT | Single highest-value operational add. |
| supervisord + state persistence | ADOPT | Required before LIVE — non-negotiable. |
| dotenv-vault | ADOPT | Encrypted secrets, 2 hours. |
| CI/CD backtest regression gate | ADOPT | Prevents Run-46-class regressions from merging. |
| uvloop | ADOPT | 30-minute trivial win even though latency isn't the bottleneck. |
| msgspec | DEFER | Pydantic parsing is not the bottleneck at this signal rate. |
| Deflated Sharpe Ratio | ADOPT | Inside mlfinlab; mandatory if Optuna runs ≥5 trials. |
| Combinatorial Purged CV | ADOPT | Inside mlfinlab; replaces walk-forward as the validation gate. |
| Monte Carlo bootstrap | ADOPT | 50 lines of NumPy; honest CI on WR/Sharpe. |
| OOS holdout discipline | ADOPT | Process rule: lock most-recent 20% until LIVE decision. |
| Multiple-testing corrections | ADOPT | BH-FDR on every parameter-sweep report. |
| smart-money-concepts | ADOPT | Use only as test oracle vs ict_engine — never as the engine itself. |
| Pine→Python ports | DEFER | No specific script named; audit `security(lookahead=on)` if pursued. |
| quantstats | ADOPT | Apache 2.0; drop-in replacement for hand-rolled Sharpe/Sortino/Calmar/DD in tracker_html.py; one-call tearsheet HTML. No overfit risk. |
| freqtrade | REJECT | GPL-3.0 (license invariant); FreqAI live re-training is the same overfit trap meta-labeling has at 50 signals/year; adoption = full rewrite. Read its issue tracker only as ops-lessons reference. |
| hummingbot | REJECT | Wrong problem class — market-making / cross-exchange arb engine. TradeAI is a directional ICT signal generator. Architecture docs worth reading for connector design only. |
| FinRL | REJECT | RL for signals — explicit Red Flag domain. PPO/DQN/DDPG cannot train on 50 signals/year; literature has severe publication bias toward overfit results. |

---

## 3. Top 10 Priority Items (Active Work Queue)

Scoring: `(IMPACT × 2) − EFFORT − (OVERFIT_RISK × 2)`. Ties broken by foundation-laying value.

| # | Item | I | E | O | Score | Target | Pattern | STATUS |
|---|---|---|---|---|---|---|---|---|
| 1 | Triple-barrier labeling (mlfinlab) | 4 | 1 | 1 | 5 | `backtest.py` trade-outcome labeling + new `labeling.py` | Drop-in label generator; rerun full backtest suite. | DONE 2026-05-22 — labeling.py (stdlib-only, no mlfinlab dep): triple_barrier_label, ewma_daily_sigma, vol_scaled_barriers, bootstrap_wr_ci, bootstrap_sharpe_ci. Wired into backtest.py (tb_bin/tb_touch/tb_ret/tb_t1 per signal + DB columns). Honest-label section in print_report. 39 new unit tests (156/156 total passing). |
| 2 | Dead-man's switch + secondary alert channel | 4 | 1 | 1 | 5 | `crypto_alert.py` main loop + new `heartbeat.py` | Sidecar heartbeat task; Telegram + SMTP fallback. | DONE 2026-05-22 — heartbeat.py + scripts/watchdog.py + MultiChannelAlerter + SELFTEST cadence + 18 tests |
| 3 | supervisord + atomic state persistence | 4 | 1 | 1 | 5 | `crypto_alert.py` state mutations + new `state_store.py` | Wrap every state mutation in `persist_atomic()`; supervisord ini outside repo. | DONE 2026-05-22 — state_store.py (atomic JSON + .bak + PidFile) + supervisord.conf + run_supervised.bat + 19 tests |
| 4 | CI/CD backtest regression gate | 4 | 2 | 1 | 4 | New `.github/workflows/backtest_gate.yml` + `scripts/backtest_regression.py` | Sidecar — runs full backtest, fails merge below Run-48 baseline minus tolerance. | DONE 2026-05-22 — scripts/backtest_regression.py (three modes: --mode=ci checks strategy param drift offline; --mode=lastrun validates committed data/backtest_results.json against floors n≥25/WR≥72%/z≥2.5; --mode=full runs fresh backtest). .github/workflows/backtest_gate.yml triggers on PR+push to main/master. WR formula matches backtest.py:987 is_win() (PARTIAL_TP1/2 = full wins). Validated against Run 93 (n=42, WR=76.19%, z=+3.826 — all floors cleared). |
| 5 | mlfinlab CPCV + DSR | 4 | 3 | 1 | 3 | `backtest.py` walk-forward block | Drop-in replacement of WF splitter; breaks Run-48 parity — re-baseline expected. | DONE 2026-05-22 — validation.py: stdlib-only CPCV (Lopez de Prado 2018) + PSR + DSR (Bailey/LdP 2014) with proper purging + embargo + median-horizon label fallback. CPCV reports OOS WR/Sharpe across C(K,k) disjoint test sets. DSR deflates against historical run count. Wired into backtest.py main(). Initial smoke (Run-93): CPCV=76.48%, DSR=81.3% — VERDICT: FAIL. **Updated baseline 2026-05-23 — Run 110 (post +TON, post FIX-29 DSR-NameError fix): n=46, CPCV mean=76.23%, DSR=89.8% — VERDICT: ACCEPTABLE SUCCESS** (≥85% threshold). Still short of LIVE-strict (≥95%) by 5.2pp due to n=46<80 sample-power requirement. Path to PRIMARY SUCCESS = paper-trading accumulation, NOT more optimizer tuning. 46 unit tests. backtest-bias-detector review: 4 fixes applied (verdict DSR gate, OOS PSR, anti-conservative proxy warning, t1 median-horizon fallback). |
| 6 | river ADWIN drift detection | 3 | 1 | 1 | 3 | `adaptive_engine.py` OGD update hook | Additive observability + optional weight-reset trigger behind config flag. | TODO |
| 7 | Half-Kelly + ATR position sizing | 4 | 1 | 2 | 3 | New `risk_manager.py` wired into `crypto_alert.py` | Drop-in replacement of flat-% sizing; config flag `SIZING_MODE=flat\|half_kelly`. | TODO |
| 8 | News/macro blocklist | 3 | 1 | 1 | 3 | `ict_engine.py` signal gate + new `event_calendar.py` | Additive confluence filter; gate behind config flag `MACRO_FILTER_ENABLED`. | DONE 2026-05-22 — event_calendar.py (FOMC 2025-2027 + CPI 2025-2027 + NFP algorithmic); MACRO_FILTER_ENABLED=false default; MACRO_ADVISORY_ONLY=true (log, don't block); gate wired in generate_signal() after kill-switch; 17 unit tests passing. |
| 9 | Weight-degeneration monitoring suite | 3 | 1 | 1 | 3 | `adaptive_engine.py` + nightly job in new `monitoring.py` | Observability layer; emits Prometheus gauges. | DONE 2026-05-22 — monitoring.py read-only sidecar (file:?mode=ro URI) over token_weights + weight_history. Detects: degeneration, low entropy (H<1.55), pinning at WEIGHT_MIN/MAX, floor saturation (>=4/6 features at floor = Run-46 fingerprint), entropy drift (WARN at -0.30, CRIT at -0.60 catastrophic), cross-token homogeneity, stale tokens (>14d). CLI: --json/--text/--prometheus/--exit-on-crit. 52 unit tests. Smoke test on live DB reveals BNB dr_location pinning (real signal). ogd-weight-inspector review: 2 fixes applied, 3 future gaps documented. |
| 10 | smart-money-concepts validation oracle | 3 | 1 | 1 | 3 | New `tests/test_ict_oracle.py` | One-shot bug-detection harness; not a runtime dep. | DONE 2026-05-22 — tests/test_ict_oracle.py: independent reference implementations for 7 ict_engine functions (swings, BSL/SSL sweep, FVG+mitigation, MSS+quality, displacement, EQH/EQL clusters, dealing range); 38 tests passing; ict-logic-validator review passed (3 false-confidence issues fixed; 6 coverage gaps documented as deferred). |

Tied-at-3 items not in the top 10 (Monte Carlo bootstrap, dotenv-vault, OOS holdout discipline, **quantstats tearsheet**) ship inside Phase A regardless. Quantstats specifically: target = `tracker_html.py` reporting block, effort ≤ half day, replaces hand-rolled stats with `qs.reports.html(returns)`. **DONE 2026-05-24** — `quantstats_report.py` (get_returns_series + get_summary + get_tearsheet_html with periods_per_year auto-scaled to actual trade frequency). Two new routes `/api/quantstats` + `/api/quantstats/tearsheet`. New "QuantStats" tab in tracker_html.py with 16 metric cards (Sharpe, Sortino, Calmar, Omega, Tail Ratio, VaR/CVaR, Kelly, Skew/Kurtosis, etc.) and an "Open Full HTML Tearsheet" button. Source toggle (Paper / Backtest). Backtest smoke against Run-168 (43 ICT signals, 26 trade-days): Sharpe=4.15, Sortino=16.00, Calmar=29.33, MaxDD=−4.49%, Profit Factor=6.70, Kelly=62%. Paper source returns "insufficient_data" cleanly until first close.

**TAB HIDDEN 2026-05-24** (operator decision): the QuantStats tab button in `tracker_html.py` is hidden via `style="display:none"` because paper trading hasn't started — most cards would be empty / zero. Backend routes (`/api/quantstats`, `/api/quantstats/tearsheet`) remain live. Re-enable trigger: **once LIVE trading is on AND closed signals are producing real P&L** (≥10 closed paper or live signals as a soft floor), remove the `display:none` from `#tabBtnQuantStats`. The panel and all 16 metric cards will then auto-populate from the same backend.

---

### Previously Evaluated External Repos (do NOT re-propose)

| Repo | Date evaluated | Verdict | Why locked |
|---|---|---|---|
| freqtrade/freqtrade | 2026-05-24 | REJECT | GPL-3.0 license invariant + FreqAI overfit trap at our sample size. |
| hummingbot/hummingbot | 2026-05-24 | REJECT | Market-maker / arb engine — wrong strategy class. |
| AI4Finance-Foundation/FinRL | 2026-05-24 | REJECT | RL for signals — Red Flag invariant. |
| nautechsystems/nautilus_trader | 2026-05-22 / 2026-05-24 | DEFER | LGPL + 2–4 wk rewrite. Borrow the *unified-engine* pattern only. |
| ranaroussi/quantstats | 2026-05-24 | ADOPT | Apache 2.0 tearsheet/reporting; net-new addition to Phase A. |
| polakowo/vectorbt | 2026-05-24 | **REJECT** | Apache 2.0 but uses NumPy-vectorized primitives that cannot import ict_engine.py. Would force re-implementation of ICT logic → two engines to keep in sync → live/BT parity dim drops 9.5→~6. Speed gain (50-100x) unnecessary: cached existing engine already does 10-15s/run → 1,500-2,000 runs per overnight session. See docs/AUTONOMOUS_EXPLORER_DESIGN.md §2. |
| optuna/optuna | 2026-05-24 | **ADOPT** | MIT license; Bayesian hyperparameter search wraps our existing backtest engine (parity preserved). Foundation for Autonomous Explorer (5-day project). See docs/AUTONOMOUS_EXPLORER_DESIGN.md. |

---

## 4. Phased Roadmap

### PHASE A — Pre-LIVE Hardening
Ship BEFORE flipping ACTIVE_CONFIG to LIVE_CONFIG. **STATUS: IN PROGRESS**

1. State persistence + supervisord + dead-man's switch + secondary alert channel — **DONE 2026-05-22** (heartbeat.py, scripts/watchdog.py, state_store.py, scripts/supervisord.conf, scripts/run_supervised.bat, scripts/run_watchdog.bat). Plus backtest checkpointing (backtest_checkpoint.py + backtest.py --no-resume/--clear-checkpoint flags). 55 new unit tests added; 117/117 total passing.
2. Triple-barrier labeling + Monte Carlo bootstrap + CPCV + DSR — **DONE 2026-05-22** (labeling.py: stdlib-only triple_barrier_label, ewma_daily_sigma, vol_scaled_barriers, bootstrap_wr_ci, bootstrap_sharpe_ci; wired into backtest.py with tb_bin/tb_touch/tb_ret/tb_t1 per-signal columns + DB persistence + Honest-Label section in print_report; 39 new unit tests. Sprint 3 closed CPCV+DSR via validation.py (Top-10 #5) — see line 97. 222→375/375 total tests passing.)
3. CI/CD backtest regression gate + OOS 20% holdout lock — **DONE 2026-05-22** (scripts/backtest_regression.py three-mode runner + .github/workflows/backtest_gate.yml. Top-10 item #4 shipped end-to-end. Phase A regression gate now live on every PR.)
4. News/macro blocklist + dotenv-vault — **DONE 2026-05-22** (config.py centralizes tunables; secrets_loader.py + .env replace env.bat; optional .env.vault. Sprint 3: event_calendar.py (FOMC/CPI/NFP 2025-2027); MACRO_FILTER_ENABLED=false default; MACRO_ADVISORY_ONLY=true; gate in generate_signal() after kill-switch; 17 unit tests; 239/239 total passing.)
5. smart-money-concepts oracle sweep — **DONE 2026-05-22** (tests/test_ict_oracle.py: 38 tests cross-validating 7 ict_engine functions against independent reference implementations. ict-logic-validator review passed. See Top-10 #10.)
6. OHLCV disk cache for backtest speed — **DONE 2026-05-23** (`backtest.py`: `fetch_cached()` wraps `fetch_historical()` with `data/ohlcv_cache/{symbol}_{interval}_{days}d.json` cache. Key auto-invalidates on `BACKTEST_DAYS` change. 24h TTL + atomic write + schema validation + forming-candle drop (hardened 2026-05-23 per data-pipeline-validator audit). `--fresh` and `--clear-cache` CLI flags. Reduces repeat experiment runs from ~25min fetch to <60s. No lookahead bias.)

**Exit criteria:** Bot survives `kill -9` + restart with open positions + OGD weights intact. CPCV-validated WR ≥ 58% on OOS 20%. CI gate blocks any PR that drops Sharpe below Run-48 by >0.15. Dead-man's switch fires within 60s of process death. Macro blocklist suppresses 100% of FOMC/CPI windows in replay.

**Rollback:** If post-CPCV honest WR falls below 55%, do NOT go LIVE. Revert config to Run-48 paper-only and continue research.

---

### PHASE B — Win-rate Lift (First 30 Days LIVE)
Additive confluence + sizing only. No new ML models. **STATUS: BLOCKED ON PHASE A**

1. Coinglass funding + OI + liquidation-cluster distance as additive confluence filter
2. Half-Kelly × ATR scalar position sizing (start at 0.25-Kelly)
3. pandas-ta refactor + PDH/PDL/weekly-open/BTC-dominance/Asian-range explicit levels
4. Prometheus + Grafana dashboard
5. uvloop drop-in

**Exit criteria:** 30 days LIVE, ≥10 closed signals, no per-feature flag has caused WR regression vs Run-48 paper baseline by >5 pp, dashboards green for full 30 days.

**Rollback:** Every Phase B feature is config-flagged. Flip individually to isolate a regression.

---

### PHASE C — Adaptive Learning Upgrade (After 100+ LIVE Signals)
Champion/challenger only — never replace OGD until challenger wins on paper. **STATUS: BLOCKED ON PHASE B**

1. river ADWIN drift detection wired to OGD weight resets (actionable)
2. Thompson Sampling A/B vs OGD on paper-mode shadow account
3. HMM regime conditioning (PILOT)
4. Meta-labeling LogReg with ≤6 hand-selected features + triple-barrier labels + CPCV/DSR
5. skfolio ERC sizing for concurrent templates

**Exit criteria:** ≥100 LIVE closed signals. Challenger wins on OOS by Sharpe Δ ≥ 0.2, validated under CPCV + DSR + Monte Carlo CI not overlapping zero.

**Rollback:** OGD remains champion until challenger statistically wins. No A/B framework auto-promotes.

---

### PHASE D — Scale-Out (After Proven 6-Month LIVE Track Record)
Trigger only after a real track record exists. **STATUS: BLOCKED ON PHASE C**

1. DuckDB for analytics queries; SQLite remains live state store
2. Multi-exchange read-only price-feed redundancy
3. Kalman-filter Bayesian online weights as next-gen OGD replacement
4. Optuna with ≤5 params + CPCV splitter for periodic re-tuning
5. Capital scaling decision based on observed live Sharpe + max DD

**Exit criteria:** 6-month live Sharpe ≥ 1.5; max DD within risk budget; ops runbook battle-tested.

**Rollback:** SQLite trade journal is sacred — never deleted, never re-formatted. Every Phase D component is additive.

---

## 5. Red Flags (HARD INVARIANTS — agents must reject PRs that violate)

1. **Meta-labeling without ≤6-feature hard cap is curve-fit-by-default** at 150 samples. Feature count is an enforced architectural invariant.
2. **Optuna without mlfinlab `CombinatorialPurgedKFold` splitter silently curve-fits.** Wrap Optuna in a project-internal `OptunaPurged` helper that refuses to run without a purged splitter.
3. **tsfresh at this sample size is statistically indefensible** regardless of BH-FDR. Permanently rejected.
4. **vectorbt's BSL 1.1 license** poisons productization. Avoid.
5. **Pine→Python ports with `security(lookahead=barmerge.lookahead_on)`** = lookahead bias = M24 class. Every port must pass `live-backtest-consistency-checker`.
6. **smart-money-concepts as a runtime dependency** would replace validated engine with simplified community logic. Use only as `tests/` oracle.
7. **nautilus_trader migration** at this scale risks reintroducing config-drift bugs. Defer until execution latency is measured as bottleneck.
8. **river bandits replacing OGD without A/B** repeats Run-46→48 mistake. Always champion/challenger.
9. **Coinglass free tier is rate-limited.** Hard-cache responses; respect rate limits — 429 storm during high volatility = signal blackout.
10. **HMM state count tuned on test data** is the standard regime-detection bug. State count must be fixed a priori via BIC on training fold only.
11. **Hyblock/Velo paid feeds** breach budget posture and create vendor lock-in on a solo-operated bot.
12. **Dead-man's switch silently failing** is worse than no dead-man's switch. Heartbeat must self-test (every Nth heartbeat asserts the alert path actually delivers).
13. **Any new gate or filter ships in default-off state during paper collection.** (Per `docs/ROADMAP_AUDIT_CROSSCHECK.md` §3 reconciliation.) Promotion to default-on requires ≥20 closed signals showing the gate's correlation with outcome, AND a fresh backtest demonstrating the gate does not violate the 30-signals/year frequency floor. Currently applies to: `MACRO_FILTER_ENABLED=false`, `MACRO_ADVISORY_ONLY=true` (Sprint 3, event_calendar.py). Future filters added in Phase B–D must follow the same discipline.

---

## 6. Missing Concerns (gaps the research report did not cover)

1. **Immutable append-only trade journal.** Add a journal table with WAL mode and a daily SHA-256 hash chain.
2. **Disaster recovery drill.** Daily SQLite backup to encrypted off-host storage; quarterly restore drill; documented exchange-outage "safe-stop" protocol.
3. **API-key rotation schedule.** Quarterly minimum with 24h overlap window. Procedure runnable in <5 minutes at 3am.
4. **Multi-exchange price-feed redundancy.** Read-only secondary (Coinbase/Kraken) feeds even if execution stays on Binance.
5. **Regulatory / tax reporting hooks.** Every closed position emits a FIFO cost-basis record to a separate ledger.
6. **Kill-switch ergonomics.** One Telegram command (`/killall`) that cancels open orders → market-closes positions → disables auto-restart → persists "halted" state → notifies on second channel.
7. **Position reconciliation loop.** Hourly fetch of exchange-side positions; flag any divergence; auto-halt on mismatch >$X.
8. **Clock-skew enforcement.** NTP sync check at startup; refuse to start if local clock drifts >100ms from Binance server time.
9. **Trade records tagged with git SHA + config hash.** Post-mortem reproducibility.
10. **Telegram failover.** SMTP-via-Mailgun as secondary alert path.
11. **Survivorship bias in backtest universe.** Document delisted-pair gap (LUNA, FTT absent); preserve historical OHLCV for delisted symbols.
12. **OPEX tracking.** Compute + data costs vs realized PnL line item for capital-allocation decisions in Phase D.

---

## 7. Recommended Single Next Action

**Implement triple-barrier labeling via mlfinlab in `backtest.py`.**

Highest-scored item (5), zero overfit risk, hard prerequisite for every other Phase A item (CPCV, DSR, meta-labeling, Monte Carlo CI all consume triple-barrier-labeled outcomes). One focused day. After it ships, re-run the full backtest suite under the new labels and lock the result as the new honest baseline.

---

## Change Log

| Date | Change | Editor |
|---|---|---|
| 2026-05-22 | Initial roadmap locked from research report triage | Lead architect (Claude) |
| 2026-05-22 | Phase A items #2 (dead-man's switch) and #3 (supervisord + state persistence) shipped; added backtest checkpointing (backtest_checkpoint.py). 55 new tests, 117/117 passing, zero regression. | Lead architect (Claude) |
| 2026-05-22 | Phase A Sprint 2: Triple-barrier labeling (Top-10 item #1) shipped. labeling.py = stdlib-only de Prado AFML §3.4 implementation (triple_barrier_label + ewma_daily_sigma + vol_scaled_barriers + bootstrap_wr_ci + bootstrap_sharpe_ci). Wired into backtest.py: tb_bin/tb_touch/tb_ret/tb_t1 per-signal columns, DB schema extended, Honest-Label section added to print_report. 39 new unit tests; 156/156 passing. No mlfinlab dep — keeps the bot's stdlib + requests posture intact. | Lead architect (Claude) |
| 2026-05-22 | Phase A Sprint 2 (full closeout): config.py (centralized tunables with env-var override + fail-loud type validation; Tune Bot anchor moved from strategy_engine.py to config.py); secrets_loader.py + .env migration (TELEGRAM_TOKEN, CHAT_ID); CI/CD backtest regression gate shipped end-to-end (scripts/backtest_regression.py 3 modes + .github/workflows/backtest_gate.yml). Top-10 item #4 closed. 222/222 tests passing. Run 93 validated: n=42, WR=76.19%, z=+3.826 — all Phase A floors cleared, bootstrap CI [61.9-88.1%] contains both Run-48 and Session-2 baselines. **Open item:** 5 extra AVAX signals in Run 93 vs Run 48 spread across 270 days (not market drift) — diff-trace queued. | Lead architect (Claude) |
| 2026-05-22 | Post-Sprint-2 verification: ROADMAP_AUDIT_CROSSCHECK.md authored to reconcile this roadmap with docs/TRADINGAGENTS_INVESTIGATION_AUDIT.md. One real conflict identified (news/macro filter — gate vs advisory) — resolved by phased ship: ADVISORY default during paper collection, promotion to gate gated on data. | Lead architect (Claude) |
