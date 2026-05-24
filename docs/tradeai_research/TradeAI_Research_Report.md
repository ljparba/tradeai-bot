# TradeAI Research Report
## Enterprise ICT Crypto Trading Bot — Upgrade Roadmap

---

## Priority Tier Legend

| Tier | Meaning |
|---|---|
| **MUST-HAVE** | High lift, low overfit risk, reasonable effort |
| **SHOULD-HAVE** | Meaningful lift, moderate effort |
| **NICE-TO-HAVE** | Situational, marginal, or high effort |
| **DO NOT IMPLEMENT** | Hype, overfit risk extreme, or wrong sample size regime |

---

## Section 1: Open-Source Tools / Libraries

---

### 1.1 Backtesting Frameworks

**vectorbt** — https://github.com/polakowo/vectorbt
- **License:** Fair Code (BSL 1.1) — ⚠️ NOT purely permissive. Free for personal/research use, commercial use requires license.
- **Integration:** Parallel parameter sweep for ICT template optimization; replace or complement your custom engine for batch runs
- **Lift:** No direct WR lift — reduces development time for validation runs by ~10x via NumPy vectorization
- **Effort:** 3–5 days to adapt your signal format to vectorbt's portfolio API
- **Overfit risk:** Low (it's a framework, not a model), but its ease of parameter sweeping increases researcher-induced overfit risk
- **Priority: SHOULD-HAVE** — fast iteration, but watch the license

---

**nautilus_trader** — https://github.com/nautechsystems/nautilus-trader
- **License:** LGPL 3.0 — ⚠️ Copyleft. Usable without open-sourcing your code if linked dynamically, but verify your legal position.
- **Integration:** Full replacement of your execution + backtesting pipeline; has built-in Binance adapter, async event loop, and actor model
- **Lift:** Significant latency reduction in live execution; backtesting fidelity with tick-level simulation
- **Effort:** High — 2–4 weeks migration. Architectural overhaul, not a drop-in.
- **Overfit risk:** Low (infrastructure concern, not modeling)
- **Priority: NICE-TO-HAVE** — unless latency or execution quality becomes a bottleneck

---

**backtrader** — https://github.com/mementum/backtrader
- **License:** GPL 3.0 — 🚫 Avoid for commercial use. Skip it.

---

**Lean (QuantConnect)** — https://github.com/QuantConnect/Lean
- **License:** Apache 2.0 ✅
- **Integration:** Full-stack alternative; C#-based core, Python layer. Too heavy for your use case.
- **Priority: NICE-TO-HAVE** — only if you ever need institutional-grade audit trails

---

> **Honest verdict:** Your custom engine is probably fine. The main gains from frameworks come from parallelized parameter sweeps (vectorbt) and execution-layer fidelity (nautilus). Don't migrate unless your current bottleneck is clearly one of those.

---

### 1.2 Market Microstructure

**Order-book-imbalance / LOB analysis:** No dominant Python lib. Build lightweight from Binance's `depth` WebSocket stream.

---

**pandas-ta** — https://github.com/twopirllc/pandas-ta
- **License:** MIT ✅
- **Integration:** Drop into `feature_engineering.py`; covers CVD-adjacent indicators (OBV, CMF), ATR variants, volume profile
- **Effort:** 1–2 hours
- **Priority: MUST-HAVE** — already production-ready, replaces manual TA code

---

**ta-lib** — https://github.com/mrjbq7/ta-lib
- **License:** BSD ✅ (Python wrapper; underlying C lib is LGPL — check)
- **Integration:** Same as pandas-ta; faster than pandas-ta for large arrays via C bindings
- **Honest assessment:** pandas-ta is more actively maintained. Use ta-lib only if you need raw speed on OHLCV features.
- **Priority: SHOULD-HAVE**

---

**tsfresh** — https://github.com/blue-yonder/tsfresh
- **License:** MIT ✅
- **Integration:** Auto-generate 700+ time series features from OHLCV windows; feed into meta-labeling model
- **Honest assessment:** Most features will be noise. Use ONLY with aggressive feature selection (Benjamini-Hochberg FDR correction). With ~50 signals/year, this is a curse-of-dimensionality trap unless you have multi-year multi-symbol data pooled.
- **Overfit risk:** HIGH without strict FDR filtering
- **Priority: NICE-TO-HAVE** — only with pooled cross-asset data

---

### 1.3 Walk-Forward + Purged CV

**mlfinlab** — https://github.com/hudson-and-thames/mlfinlab
- **License:** BSD 3-Clause ✅
- **Integration:** `PurgedKFold`, `CombinatorialPurgedKFold` in your backtesting/validation module; triple-barrier labeling; meta-labeling pipeline
- **Lift:** Properly purged CV will likely *reduce* reported WR — which is the point. It prevents you from shipping overfit strategies.
- **Effort:** 2–3 days
- **Overfit risk:** This library reduces overfit; the risk is implementation error (leakage via incorrect embargo gaps)
- **Priority: MUST-HAVE** — this is the single most important library in this entire list for your sample size

---

**skfolio** — https://github.com/skfolio/skfolio
- **License:** BSD 3-Clause ✅
- **Integration:** Portfolio optimization (ERC, CVaR) for position sizing across multiple open positions
- **Effort:** 2–3 days
- **Priority: SHOULD-HAVE** — particularly ERC for multi-position exposure management

---

### 1.4 Bayesian Hyperparameter Optimization

**Optuna** — https://github.com/optuna/optuna
- **License:** MIT ✅
- **Integration:** Wrap your template parameter sweep (OB lookback, FVG threshold, killzone hours) in an Optuna study; use `MedianPruner` to stop bad trials early
- **Critical caveat:** Always optimize on out-of-sample fold; never on full history. With 50 signals/year, your optimization space must be tiny (≤5 parameters). More parameters = guaranteed overfit regardless of framework.
- **Effort:** 1–2 days
- **Priority: MUST-HAVE** — but with strict discipline on parameter count

---

**Hyperopt** — https://github.com/hyperopt/hyperopt
- **License:** BSD ✅
- **Honest assessment:** Optuna has surpassed Hyperopt in usability and features. Use Optuna.

---

### 1.5 Regime Detection

**hmmlearn** — https://github.com/hmmlearn/hmmlearn
- **License:** BSD 3-Clause ✅
- **Integration:** 2–3 state HMM on daily returns or volatility → regime label → gate which templates fire (e.g., suppress mean-reversion setups in trending regime)
- **Lift:** Estimated +3–6% WR by avoiding countertrend trades in strong trends. Honest: results vary widely; requires re-training as regimes shift.
- **Effort:** 2–3 days
- **Overfit risk:** Moderate — HMM state count and emission distributions need to be fixed a priori, not tuned on test data
- **Priority: SHOULD-HAVE**

---

**ruptures** — https://github.com/deepcharles/ruptures
- **License:** BSD 2-Clause ✅
- **Integration:** Offline changepoint detection on historical data for regime boundary labeling during backtest construction
- **Honest assessment:** Useful for labeling, not for live deployment (looks ahead). Use in walk-forward label construction only.
- **Priority: SHOULD-HAVE** for backtest construction

---

**Markovian / regime-switching:** No dominant Python lib. `statsmodels`' `MarkovRegression` (BSD) covers basic Markov-switching models adequately.

---

### 1.6 Drift Detection

**river** — https://github.com/online-ml/river
- **License:** BSD 3-Clause ✅
- **Integration:** `ADWIN` or `DDM` detector on rolling prediction accuracy → trigger adaptive weight reset or re-calibration in `adaptive_engine.py`
- **Lift:** Prevents zombie weights from persisting through regime changes. Hard to quantify but important for long-run robustness.
- **Effort:** 1 day
- **Priority: MUST-HAVE** — your OGD has no mechanism to know when it's drifting; this adds one

---

**alibi-detect** — https://github.com/SeldonIO/alibi-detect
- **License:** Apache 2.0 ✅
- **Integration:** MMD or KS drift tests on feature distributions (FVG sizes, OB distances) to detect when market microstructure is changing
- **Honest assessment:** More powerful than river's detectors but significantly heavier. Use river for online signal-level drift; alibi-detect for periodic batch feature-distribution monitoring.
- **Priority: NICE-TO-HAVE**

---

## Section 2: Algorithms to Improve Win Rate

---

### 2.1 Meta-Labeling (López de Prado — Advances in Financial ML, Ch. 3)

Train a secondary binary classifier (XGBoost, LogReg) that takes your primary ICT signal + features and predicts whether the signal will be profitable. Only trade when secondary model says yes.

**Implementation:**
- **Primary model:** Your ICT engine (existing)
- **Secondary model features:** Regime label, ATR percentile, session (killzone), funding rate, OI delta, distance to nearest liquidity level, FVG size relative to ATR
- **Label:** Triple-barrier outcome (see 2.2)
- **Model:** Logistic Regression or XGBoost with `max_depth=2` — with 50 signals/year over 3 years = 150 samples, DO NOT use deep models
- **Integration point:** `signal_filter.py` (new module), called after ICT signal generation

**Lift:** Potentially +5–12% WR by filtering false signals. Honest caveat: with 150 samples, confidence intervals on WR are ±8–15%. You may not have statistical power to validate improvement.

**Effort:** 3–5 days

**Overfit risk:** HIGH if you use >10 features or a complex model. Stick to LogReg + ≤6 hand-selected features.

**Priority: MUST-HAVE** — but with extreme discipline on feature count and model complexity

---

### 2.2 Triple-Barrier Labeling

Instead of labeling trades as win/loss by a single take-profit, label by whichever of three barriers is hit first: upper TP, lower SL, or time-based expiry.

- **Integration:** Replace your current trade outcome labeling in backtest engine. Use mlfinlab's `triple_barrier` function.
- **Why it matters:** Proper labeling is upstream of meta-labeling. Wrong labels = wrong filter.
- **Effort:** 1–2 days
- **Priority: MUST-HAVE** — quick win with high downstream impact

---

### 2.3 Volatility-Adjusted Position Sizing

**Kelly Fraction (half-Kelly):**
```
f = (p * b - q) / b
```
Where `b = avg_win/avg_loss`, `p = WR`, `q = 1-WR`. Use **half-Kelly** always. Full Kelly is theoretically optimal but practically produces drawdowns most traders can't stomach.

**ERC (Equal Risk Contribution):** If you run multiple templates simultaneously, size each so its ATR-based risk contribution is equal. skfolio handles this.

**Integration:** Replace flat percentage sizing in `risk_manager.py` with half-Kelly × volatility scalar (`ATR / recent_ATR_mean`).

**Effort:** 1 day

**Priority: MUST-HAVE**

---

### 2.4 Ensemble Signal Voting

Running Tier A + Tier B + Tier C templates and requiring 2-of-3 or weighted vote agreement before entry. Key additions:

- Weight votes by **recent template performance** (rolling 20-trade WR per template) — your OGD already approximates this
- Add a **regime gate** (from HMM): suppress certain template classes in certain regimes
- **Honest assessment:** With 50 signals/year, requiring 2-of-3 agreement will drop signal count sharply. You need to validate that the WR improvement offsets the reduced frequency. Don't assume it does without testing.

**Priority: SHOULD-HAVE**

---

### 2.5 Market Regime Conditioning

- **Regimes:** Trending (directional, low volatility), Volatile (high ATR, large swings), Ranging (low ATR, choppy)
- **Rules:** Tier C setups (lower confluence) → fire only in Trending; Tier A → fire in all regimes
- Use HMM on 1D or 4H returns for regime labeling

**Priority: SHOULD-HAVE**

---

### 2.6 Order Flow / Liquidation Heatmap

**Coinglass API** — https://coinglass.com/pricing
- **Free tier:** Funding rates, OI, liquidation data (limited endpoints)
- **Integration:** Add `funding_rate`, `oi_delta_24h`, `liquidation_level_distance` as features in meta-labeling model AND as confluence gate in `ict_engine.py` (e.g., require positive OI delta for long entries near liquidity sweeps)
- **Lift:** Liquidation cluster proximity is one of the more empirically supported confluence factors in crypto. Estimated +2–5% WR as a binary gate.
- **Effort:** 1–2 days to integrate API

**Hyblock** — https://hyblock.io — paid, ~$50/month for basic tier. Useful if Coinglass free tier is insufficient.

**Priority: MUST-HAVE** (Coinglass free tier at minimum)

---

### 2.7 News/Sentiment Filtering

Major macro events (FOMC, CPI, ETF approvals, exchange hacks) generate price action that looks like ICT setups but isn't. These are the false signals that hurt WR most.

**Implementation:**
- Maintain a blocklist calendar (FOMC, CPI, NFP dates)
- In the 30 minutes before / 60 minutes after scheduled events: suppress all new entries
- Use `economic-calendar` Python package or fetch from Forex Factory API (free)
- For crypto-specific events: no reliable free API. Manual monitoring or Santiment's event feed.

**Lift:** Estimated +2–4% WR by eliminating news-spike false signals

**Effort:** 0.5–1 day for macro blocklist

**Priority: MUST-HAVE** — trivial effort, real lift

---

## Section 3: Adaptive Learning Improvements

---

### 3.1 Contextual Bandits

**LinUCB / Thompson Sampling** — river library covers both

Instead of gradient-descending on all template weights simultaneously, treat template selection as a multi-armed bandit: each template is an arm, each trade is a pull, reward is outcome. LinUCB adds context (regime, session, volatility state).

**Honest assessment for 50 signals/year:**
- Thompson Sampling converges faster than OGD under uncertainty and naturally handles the exploration/exploitation tradeoff
- LinUCB requires a feature vector per signal — you likely already have this
- With 50 signals/year, both bandit methods and OGD are operating in high-uncertainty territory. Don't expect dramatic differences in first 1–2 years.
- **Implementation:** `river.bandit.LinUCBBandit` or `river.bandit.ThompsonSamplingBandit` — replace OGD weight update in `adaptive_engine.py`

**Effort:** 2–3 days

**Overfit risk:** Low — bandits are designed for low-data regimes

**Priority: SHOULD-HAVE** — Thompson Sampling particularly; better uncertainty handling than OGD

---

### 3.2 Concept Drift Handling

Use ADWIN from `river` (covered in 1.6). Additionally:

- **Sliding window OGD:** Already implicit if your OGD has a lookback window. Explicitly make window size a tunable parameter via Optuna.
- **Weight entropy monitoring:** `H = -sum(w_i * log(w_i))` over template weights. If entropy collapses (one template dominates), it's a signal that your adaptive system may be overfitting to recent luck rather than true skill. Alert and investigate.

**Priority: MUST-HAVE** (entropy monitoring is a 2-hour add)

---

### 3.3 Reinforcement Learning — Honest Assessment

> **The honest answer: RL is not worth it for 50 signals/year.**

- PPO, SAC, DQN all need thousands of environment steps to learn meaningful policies
- Financial RL environments are notoriously reward-hacked: bots learn to exploit backtest artifacts
- The academic literature on RL for trading has a severe publication bias toward overfit results that don't hold out-of-sample
- Conservative Q-learning and offline RL reduce but don't eliminate these problems

**When RL might be appropriate for your system:** Only if you model the *execution* problem (order splitting, slippage minimization) rather than the *signal* problem. At that granularity, RL has more reasonable sample counts.

**Verdict:** Don't implement RL for signal generation. Your OGD + bandit approach is more appropriate for your sample size.

**Priority: DO NOT IMPLEMENT**

---

### 3.4 Bayesian Online Updates vs OGD

Bayesian online learning (e.g., Kalman filter on weights, or Bayesian logistic regression with online updates) wins over OGD when:
- Sample size is small ✓ (your case)
- You have meaningful priors (e.g., "Tier A templates should have higher prior weight")
- You need calibrated uncertainty estimates (useful for position sizing)

**Implementation:** `PyMC` for batch re-fitting; `river.linear_model.BayesianLinearRegression` for online. Alternatively, a simple Kalman filter on each template's rolling WR is lightweight and interpretable.

**Effort:** 3–4 days for Kalman-based adaptive weights

**Priority: SHOULD-HAVE** — particularly for incorporating prior beliefs about template quality

---

### 3.5 Detecting Adaptive Weight Degeneration

Full prescription:

1. **Entropy of weight distribution** — alert if `H < threshold` (concentration)
2. **KL divergence from prior** — if weights drift far from your initialized priors, investigate
3. **Rolling Brier score** — are your probability estimates (if using bandit/Bayesian) actually calibrated?
4. **Per-template drawdown monitoring** — if any template has 5+ consecutive losses, pause it regardless of adaptive weight

Implement as a nightly job in `monitoring.py`.

**Effort:** 1–2 days

**Priority: MUST-HAVE**

---

## Section 4: Data Sources

---

### 4.1 Free/Cheap APIs

| Source | Free Tier | Key Signals | Effort |
|---|---|---|---|
| **Coinglass** | Yes (rate-limited) | Funding rate, OI, liquidations | 1 day |
| **Glassnode** | Limited (on-chain lagging) | Exchange netflow, SOPR | 2 days |
| **Santiment** | 1000 credits/month free | Social volume, dev activity | 2 days |
| **CryptoQuant** | Some free endpoints | Exchange reserve, miner flows | 2 days |
| **Velo Data** | Paid (~$99/mo) | High-freq funding, perp data | — |

**Honest signal quality ranking for short-term price prediction (1H–4H):**

1. Funding rate (Coinglass) — strongest, mean-reverting signal
2. OI delta — directional confirmation
3. Liquidation cluster distance — confluence for sweep targets
4. Exchange netflow (Glassnode) — 12–48H lag, less useful for your timeframe
5. Social sentiment (Santiment) — too noisy for systematic use; only useful as a negative filter (spike in negative sentiment → avoid longs)

---

### 4.2 On-Chain Signals That Actually Work at Your Timeframe

**Funding rate:** When funding is highly positive → market is over-leveraged long → ICT short setups have higher completion rate. Add as a ±1 confluence multiplier.

**OI delta (rolling 4H):** Rising OI + price rise = real buying. Rising OI + price fall = shorts adding. Integrate as directional confirmation.

**Liquidation clusters:** Coinglass heatmap shows price levels with clustered liquidations. These are ICT liquidity levels — your engine already targets these conceptually. Map API data to confirm your detected liquidity levels.

**Exchange netflow:** Negative netflow (more BTC leaving exchanges) = accumulation. Useful for 4H–1D setups. Not fast enough for 15M–1H.

---

### 4.3 Cross-Asset SMT

- **DXY inverse correlation:** When DXY makes a new high while BTC fails to make a new low → bullish divergence. Use `yfinance` (free) for DXY OHLCV.
- **SPX correlation:** During risk-off periods (VIX > 25), BTC/SPX correlation spikes. Use regime as a filter — suppress certain setups when VIX is elevated.
- **BTC dominance:** Rising BTC dominance + altcoin liquidity sweep = strong altcoin short setup (alt underperformance confirmation)

**Effort:** 1–2 days for DXY + SPX via yfinance

**Priority: SHOULD-HAVE**

---

### 4.4 Session-Anchored References

Additions to your existing killzone implementation:

- **Asian range high/low as explicit levels:** Many ICT setups use Asian range as the initial liquidity pool. Explicitly store and reference Asian H/L in `ict_engine.py` if not already done.
- **Previous day high/low (PDH/PDL):** High-priority ICT levels; track explicitly.
- **Weekly open:** ICT places high importance on weekly open as a magnet.

---

## Section 5: Enterprise Infrastructure

---

### 5.1 Database

**DuckDB** — https://github.com/duckdb/duckdb
- **License:** MIT ✅
- **Best for:** Analytics queries on OHLCV history, backtesting data scanning, ad-hoc research
- **Integration:** Replace SQLite for read-heavy analytics queries; keep SQLite for live state/trade log
- **Effort:** 1–2 days
- **Priority: SHOULD-HAVE**

---

**TimescaleDB** — https://github.com/timescale/timescaledb
- **License:** Timescale License ⚠️ (source-available, not OSI open source for certain features). Community version Apache 2.0 for basic time-series features.
- **Best for:** If you're ingesting tick-level data at scale (millions of rows/day)
- **Effort:** 3–5 days to migrate + self-host PostgreSQL
- **Priority: NICE-TO-HAVE** — unless you scale to tick data ingestion

> **Honest verdict:** DuckDB is your quick win. TimescaleDB is only justified at tick data scale.

---

### 5.2 Observability — Prometheus + Grafana

Use `prometheus_client` Python library (Apache 2.0). Grafana dashboards as code via Grafonnet or JSON exports.

**Key metrics to track:**

```
tradeai_signals_total           # counter, by template, by tier
tradeai_open_positions          # gauge
tradeai_equity_usd              # gauge
tradeai_template_wr_rolling20   # gauge, per template
tradeai_adaptive_weight_entropy # gauge
tradeai_drift_detected          # gauge, 0/1
tradeai_websocket_lag_seconds   # histogram
```

**Effort:** 2–3 days for meaningful dashboard

**Priority: MUST-HAVE** for production

---

### 5.3 Alerting

- **Telegram** (already have) → sufficient for most cases
- **PagerDuty** (https://pagerduty.com) — free tier for solo devs: good for P0 alerts (position stuck, websocket dead, margin call risk)
- **Dead man's switch:** Send a heartbeat every 5 minutes. If it stops, alert. More important than any specific alert rule.

**Effort:** 1 day

**Priority: SHOULD-HAVE**

---

### 5.4 Crash Recovery

**supervisord** — simplest, battle-tested for Python daemons:

```ini
[program:tradeai]
command=python /path/to/main.py
autostart=true
autorestart=true
startretries=5
stderr_logfile=/var/log/tradeai.err.log
```

**Docker with healthcheck** — add `HEALTHCHECK` in Dockerfile; combine with `--restart=unless-stopped`

**State persistence:** On crash, your bot must be able to reconstruct: open positions, adaptive weights, current signals. Store these to SQLite on every state change, not just at shutdown.

**Effort:** 1 day

**Priority: MUST-HAVE**

---

### 5.5 Secrets Management

- **Solo deployment:** python-dotenv + encrypted `.env` (dotenv-vault, free tier) is sufficient. Never commit API keys.
- **Team/cloud:** AWS Secrets Manager (~$0.40/secret/month) or HashiCorp Vault (self-hosted, free)

**Priority: MUST-HAVE** (dotenv-vault: 2 hours)

---

### 5.6 CI/CD — Backtest Regression Gate

```yaml
# GitHub Actions — pre-merge backtest regression gate
- name: Run backtest regression
  run: python backtest_regression.py --min-sharpe 1.2 --min-wr 0.58
```

Gate merges on: Sharpe ≥ threshold, WR ≥ threshold, max drawdown ≤ threshold on held-out OOS period.

**Effort:** 1–2 days

**Priority: MUST-HAVE** — prevents deploying regressions to live

---

### 5.7 Latency Optimization

**uvloop** — https://github.com/MagicStack/uvloop
- **License:** MIT / Apache 2.0 ✅
- Drop-in replacement for asyncio event loop; 2–4x faster
- **Integration:** `asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())` at startup
- **Effort:** 30 minutes
- **Priority: MUST-HAVE** — trivial effort

---

**msgspec** — https://github.com/jcrist/msgspec
- **License:** BSD 3-Clause ✅
- Replace Pydantic for WebSocket message parsing; 10–20x faster serialization
- **Effort:** 1–2 days to replace Pydantic models
- **Priority: SHOULD-HAVE** — if you're parsing high-frequency WebSocket messages

---

## Section 6: Validation & Anti-Overfitting

---

### 6.1 Deflated Sharpe Ratio + Probabilistic Sharpe

**References:** López de Prado, "The Sharpe Ratio Efficient Frontier" (2012)

mlfinlab has `deflated_sharpe_ratio`. The deflation factor penalizes Sharpe based on number of trials tested.

**Key insight:** If you've tried 20 parameter combinations and report the best Sharpe, your "true" Sharpe is much lower than the backtest shows. DSR quantifies this.

**Effort:** 1 day to integrate into your reporting

**Priority: MUST-HAVE**

---

### 6.2 Combinatorial Purged Cross-Validation (CPCV)

Use mlfinlab `CombinatorialPurgedKFold`.

Standard k-fold leaks future information through overlapping labels. CPCV + embargo gap eliminates this. For your timeframe (1H–4H signals), use **1–2 bar embargo minimum**.

**Effort:** 2–3 days

**Priority: MUST-HAVE** — this changes your reported WR significantly (usually downward, but honestly)

---

### 6.3 Monte Carlo Backtest Randomization

**Method 1 — Trade order shuffle:** Shuffle the sequence of your historical trades 10,000 times, compute Sharpe distribution. If your actual Sharpe is in the top 5% of the shuffle distribution, it suggests the edge is in trade selection, not lucky sequencing.

**Method 2 — Bootstrap resampling:** Sample with replacement from your trade outcomes 10,000 times. Gives confidence intervals on WR and Sharpe.

**Implementation:** 50 lines of NumPy — don't need a library.

**Effort:** 0.5 days

**Priority: MUST-HAVE** — quick and provides honest confidence intervals

---

### 6.4 Out-of-Sample Reservation

Reserve the most recent **20% of your data** as a true holdout — **never touch it during development.** Use it once, at deployment decision time. If you've already peeked at it while tuning, it's no longer OOS.

> This is a discipline issue, not a technical one. No library solves it.

---

### 6.5 Multiple Testing Corrections

When you tune N parameters or test N variants, use:
- **Bonferroni** (conservative, simple): divide p-value threshold by N
- **Benjamini-Hochberg FDR** (less conservative, better for independent tests)

**Rule of thumb:** If you've tried >5 parameter combinations, your reported p-value needs correction. mlfinlab's DSR handles this implicitly.

---

## Section 7: ICT-Specific Tooling

---

### 7.1 Open-Source ICT Libraries

**smart-money-concepts** — https://github.com/joshyattridge/smart-money-concepts
- **License:** MIT ✅
- **Covers:** BOS, CHoCH, order blocks, FVG, swing highs/lows
- **Honest assessment:** Community-grade code. Useful for cross-referencing your detection logic, not production-ready as-is. The OB/FVG detection logic is often simplified vs ICT's actual definitions.
- **Integration:** Use as a **test oracle** — run against your engine on the same data and compare detections. Discrepancies reveal bugs in your implementation.
- **Effort:** 1 day for comparison harness
- **Priority: SHOULD-HAVE** for validation purposes

---

### 7.2 Pine Script to Python Porting

Reliable community indicators on TradingView:
- "ICT Concepts" by LuxAlgo (freemium) — well-maintained, documented
- "Smart Money Concepts" by LuxAlgo — same

Porting Pine to Python is straightforward for structural logic (BOS, FVG) but requires careful handling of `barstate` (real-time vs confirmed bars).

> ⚠️ **Critical Pine-to-Python porting note:** Many Pine ICT scripts use `security()` calls with `lookahead=barmerge.lookahead_on` — this introduces **look-ahead bias**. Any port must audit and eliminate this.

---

### 7.3 Communities

- **r/Forex + r/Daytrading** — anecdotal, low statistical rigor
- **ICT Discord servers** — primarily educational, no systematic statistics
- **Quantitative ICT research:** Essentially absent in peer-reviewed literature.

> **Honest assessment:** The ICT community's statistical claims (60–70% WR, etc.) are almost entirely anecdotal or based on cherry-picked backtests. Your systematic approach with CPCV validation is already more rigorous than the community norm.

---

## Final Prioritized Ranking

Ranked by **(estimated_lift × feasibility) / (effort × overfit_risk)**:

| Rank | Item | Priority | Est. Effort | Overfit Risk | Estimated Lift |
|---|---|---|---|---|---|
| 1 | News/macro blocklist | MUST-HAVE | 4 hours | Very Low | +2–4% WR |
| 2 | uvloop | MUST-HAVE | 30 min | None | Latency |
| 3 | Triple-barrier labeling | MUST-HAVE | 1–2 days | Low | Upstream quality |
| 4 | ADWIN drift detection (river) | MUST-HAVE | 1 day | Low | Prevents WR decay |
| 5 | Adaptive weight entropy monitoring | MUST-HAVE | 2 hours | None | Diagnostic |
| 6 | Coinglass funding + OI integration | MUST-HAVE | 1–2 days | Low | +2–5% WR |
| 7 | Half-Kelly + ATR position sizing | MUST-HAVE | 1 day | Low | Sharpe +0.2–0.5 |
| 8 | Optuna parameter optimization | MUST-HAVE | 1–2 days | Moderate | +Consistency |
| 9 | mlfinlab CPCV + DSR | MUST-HAVE | 2–3 days | Low | Honest metrics |
| 10 | Supervisord crash recovery + state persistence | MUST-HAVE | 1 day | None | Reliability |
| 11 | Meta-labeling (LogReg, ≤6 features) | MUST-HAVE | 3–5 days | HIGH | +5–12% WR (uncertain) |
| 12 | Prometheus + Grafana | MUST-HAVE | 2–3 days | None | Observability |
| 13 | pandas-ta | MUST-HAVE | 1–2 hours | Low | Code quality |
| 14 | CI/CD backtest regression gate | MUST-HAVE | 1–2 days | None | Safety net |
| 15 | Thompson Sampling (river) | SHOULD-HAVE | 2–3 days | Low | Better uncertainty |
| 16 | HMM regime conditioning | SHOULD-HAVE | 2–3 days | Moderate | +3–6% WR |
| 17 | DuckDB | SHOULD-HAVE | 1–2 days | None | Analytics speed |
| 18 | Monte Carlo backtest validation | MUST-HAVE | 0.5 days | None | Honest CI |
| 19 | DXY/SPX cross-asset SMT (yfinance) | SHOULD-HAVE | 1–2 days | Low | +1–3% WR |
| 20 | Kalman filter adaptive weights | SHOULD-HAVE | 3–4 days | Low | Better calibration |
| 21 | skfolio ERC sizing | SHOULD-HAVE | 2–3 days | Low | Risk-adjusted returns |
| 22 | msgspec | SHOULD-HAVE | 1–2 days | None | Latency |
| 23 | smart-money-concepts (validation oracle) | SHOULD-HAVE | 1 day | None | Bug detection |
| 24 | ruptures (backtest label construction) | SHOULD-HAVE | 1 day | Low | Label quality |
| 25 | TimescaleDB | NICE-TO-HAVE | 3–5 days | None | Scale |
| 26 | tsfresh | NICE-TO-HAVE | 3–4 days | VERY HIGH | Uncertain |
| 27 | nautilus_trader | NICE-TO-HAVE | 2–4 weeks | None | Execution fidelity |
| 28 | RL (PPO/DQN for signals) | **DO NOT IMPLEMENT** | — | EXTREME | Negative expected |

---

## Implementation Sequence

### Week 1–2 — Foundation
- uvloop, supervisord + state persistence, macro blocklist, pandas-ta, Coinglass API

### Week 3–4 — Validation Overhaul
- Triple-barrier labeling, mlfinlab CPCV, Monte Carlo CI, DSR reporting

### Week 5–6 — Adaptive Improvements
- ADWIN drift detection, weight entropy monitoring, half-Kelly sizing, Optuna (narrow search space)

### Week 7–8 — Signal Quality
- Meta-labeling (LogReg, disciplined), HMM regime conditioning

### Month 3+ — Infrastructure
- Prometheus + Grafana, CI/CD gates, DuckDB migration

### Ongoing
- Thompson Sampling evaluation vs current OGD (A/B on paper trading)

---

> **The most important thing not on any library list:** Your signal sample size is the binding constraint. Every improvement to labeling quality, drift detection, and validation rigor compounds — whereas adding more features or model complexity compounds your overfit risk. The libraries that reduce noise and improve measurement are worth more than the ones that promise higher WR.
