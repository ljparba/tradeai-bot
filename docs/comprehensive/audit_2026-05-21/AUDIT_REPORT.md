# TradeAI Comprehensive Audit Report — 2026-05-21

> Full 7-agent parallel audit. Raw agent outputs collated and synthesized.
> DO NOT FIX ANYTHING based on this document — triage first via ISSUE_CHECKLIST.md.

---

## Audit Session Info

| Field | Value |
|---|---|
| **Date** | 2026-05-21 |
| **Agents Run** | ict-logic-validator, backtest-bias-detector, live-backtest-consistency-checker, adaptive-learning-code-reviewer, risk-management-auditor, data-pipeline-validator, live-deployment-readiness-checker |
| **Scope** | Full system — all source files, config, database, tracker, documentation |
| **Triggered By** | First formal comprehensive audit after Session 21 fix pass (optimizer complete, quality config active) |

---

## Step 0 — Confirmed Current State

| Field | Value |
|---|---|
| EXECUTION_MODE | PAPER (hardcoded string at `crypto_alert.py:139`) |
| BINANCE_TOKENS | 9 tokens: BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL (SOL removed T-1) |
| Active Config | "Run 60 quality config" — ICT_SWING_N=2, COOLDOWN_BARS=8, ENTRY_WINDOW=72, bias_4h_gate="none", liquid_hours=range(24), FVG=HIGH, RANGING blocked, Tue/Wed/Sat blocked, DR EQUILIBRIUM-only gate |
| Expected backtest | n≈34/year, WR≈85.3%, z≈+4.53, NetE≈+1.648%, MaxDD≈2.62% |
| Live closed signals | 0 (paper trading NOT started) |
| Test suite | 162 tests, all passing |
| Previous audit scores | Estimated after Session 21 fixes (~5.5/10 overall) — this is first formal scored audit |

---

## Known Recurring Pattern Checks

| Pattern | Verdict | Notes |
|---|---|---|
| 1 — Lookahead bias in backtest slices | **PASS** | `backtest.py:471-474` correctly uses `[idx0:i]` exclusive. Entry scan starts at `i+1`. |
| 2 — Session attribution timestamp | **PASS** | Both paths use detection bar timestamp (`ts.hour` / `_utc_now.hour`). |
| 3 — Fail-closed safety gate defaults | **PASS** | No `.get(key, True)` or `.get(key, 1)` patterns in gate logic. DB error returns fail-closed. |
| 4 — SQLite UTC date comparisons | **PASS** | `date('now', 'utc')` used at `crypto_alert.py:783`. No bare `date('now')` found. |
| 5 — OGD bootstrap SELL-bias | **UNVERIFIED** | No guard against >55% SELL in bootstrap input. Prior degenerate collapse mechanism still latent. |

---

## Executive Summary — Scores

| Dimension | Previous (est.) | Current | Target |
|---|---|---|---|
| **Overall** | ~5.5/10 | **5.5/10** | 10/10 |
| Trading Strategy Logic | ~5/10 | **6/10** | 10/10 |
| ICT Implementation | ~7/10 | **6/10** | 10/10 |
| Adaptive Learning | ~5/10 | **5/10** | 10/10 |
| Backtest Validity | ~5/10 | **4/10** | 10/10 |
| Live vs Backtest Consistency | ~7/10 | **5/10** | 10/10 |
| Risk Management | ~6/10 | **5/10** | 10/10 |
| Architecture & Code Quality | ~7/10 | **6.5/10** | 10/10 |
| Database & Dashboard | ~7/10 | **6.5/10** | 10/10 |
| Documentation | ~8/10 | **7/10** | 10/10 |
| Production Readiness | n/a | **4/10** | 10/10 |

### What each sub-10 dimension needs

**Backtest Validity (4/10):** Walk-forward OOS must be a fixed wall-clock date locked before optimization. Consumed sweeps must be tracked in the backtest loop. Regime detection must not use the forming 1H bar. Statistical confidence intervals must be reported. Target: 8/10 after fixing C2, C9, H-BT2.

**Live vs Backtest Consistency (5/10):** iFVG spatial gate must be added to backtest. DR computation must use FVG edge reference in both paths. Entry reaction window must be unified. Regime ADX threshold divergence must be documented. Target: 8/10 after fixing C3, C4, H-LB1, H-LB2.

**Risk Management (5/10):** Drawdown gate must use capital-impact %, not trade-price %. EXECUTION_MODE mismatch between two modules must be resolved. Drawdown must track peak-to-trough equity curve. Target: 8/10 after fixing C7, H-R2, H-R3.

**Production Readiness (4/10):** Telegram tokens must be revoked and rotated. EXECUTION_MODE must be read from env var. YOUR_CAPITAL must have enforcement gate in LIVE mode. Auto-restart on reboot must be configured. Target: 9/10 after fixing C1, C8, C10, H-D4.

**Adaptive Learning (5/10):** Threshold mismatch (n=10 updates, n=30 gate) must be resolved. Decay rate must respect recency of last update. SELL-bias bootstrap guard must be added. Phase 5B per-template OGD not yet implemented. Target: 7/10 after fixes. 8/10 requires Phase 5B + N≥50 live signals.

**ICT Implementation (6/10):** MSS guard off-by-one must be fixed. Displacement must have ATR minimum. DR metadata must use FVG edge reference. FVG mitigation should use 50% midpoint. DR gate should block PREMIUM-BUY and DISCOUNT-SELL. Target: 8/10 after fixing H-ICT2, H-ICT3, M-ICT3/4/5.

---

## CRITICAL PROBLEMS

---

### C1 — Real Telegram Tokens Hardcoded in Tracked Files

```
Severity        : CRITICAL
ID              : C1
Agent           : live-deployment-readiness-checker
Problem         : Two real Telegram bot tokens are in plaintext files. env.bat (gitignored)
                  contains the live production token. env.example.bat (NOT gitignored) contains
                  a second real token with the same CHAT_ID (5818729474).
                  Files: env.bat:5-6, env.example.bat:5-6
Why Dangerous   : env.example.bat is not in .gitignore. If the project is ever pushed to
                  a git remote, synced to cloud storage, or shared, both tokens are exposed.
                  An attacker with the bot token can send fake trading signals to the user's
                  Telegram. For a signal-only bot where the user acts on signals with real
                  money, a fake signal is a direct financial attack vector.
Recommended Fix : Revoke both tokens immediately via BotFather. Generate new tokens. Replace
                  token values in both files with placeholders. Add env.example.bat to .gitignore.
```

---

### C2 — Walk-Forward Split Is Not a True Hold-Out

```
Severity        : CRITICAL
ID              : C2
Agent           : backtest-bias-detector
Problem         : The 60/40 chronological split at backtest.py:1362-1367 is computed after all
                  signals are generated, on the same data used for all 15+ optimization experiments.
                  The OOS period was never locked before optimization began. The WFgap was used as
                  an acceptance criterion for every experiment (docs/optimization_experiments.md),
                  meaning the "out-of-sample" set was visible during parameter selection.
                  The split boundary itself shifts with every run because it is n_signals * 0.60.
Why Dangerous   : The reported WFgap of -0.7% (Run 60 quality config) is not a genuinely
                  out-of-sample result. The optimizer selected configs that passed OOS — but OOS
                  data was used in the selection process. This is data snooping on the held-out
                  set. WR=85.3% cannot be distinguished from lucky parameter selection at n=34.
                  95% CI on WR=85.3% at n=34: [69.2%, 94.4%] — lower bound is 69.2%.
Recommended Fix : Define a hard wall-clock OOS start date (last 90 days of 365-day period) before
                  any parameter optimization. Never expose that period during experiments. Report
                  its WR only once as final validation. Re-run with this locked OOS to get a
                  genuine forward-test result.
```

---

### C3 — iFVG Spatial Gate Absent in Backtest

```
Severity        : CRITICAL
ID              : C3
Agent           : live-backtest-consistency-checker
Problem         : In live path (crypto_alert.py:2299-2305), ifvg_bonus=+1 requires spatial
                  proximity check (iFVG midpoint within 3% of FVG midpoint, _IFVG_PROXIMITY_PCT=0.03).
                  In backtest (backtest.py:667): ifvg_bonus = +1 if ifvg_meta.get("ifvg_present")
                  — no spatial gate at all. The backtest awards +1 confidence bonus for any
                  historical iFVG regardless of proximity.
Why Dangerous   : Backtest inflates confidence scores for signals where iFVG is spatially distant
                  from the FVG zone — signals that the live bot would score as zero. This shifts
                  some backtest signals above the confidence floor that live would block, corrupting
                  the WR prediction. The direction: backtest WR is optimistic relative to live.
Recommended Fix : Add the identical _IFVG_PROXIMITY_PCT=0.03 spatial gate to the backtest loop's
                  ifvg_bonus calculation (backtest.py:667) before assigning +1.
```

---

### C4 — Regime ADX Thresholds Static in Backtest vs DriftDetector-Adjusted in Live

```
Severity        : CRITICAL
ID              : C4
Agent           : live-backtest-consistency-checker
Problem         : Backtest (backtest.py:459-463) calls detect_regime() with default ADX thresholds
                  (25.0/20.0/15.0). Live path (crypto_alert.py:1577-1583) calls detect_regime()
                  via get_regime_for_token() with DriftDetector-adjusted thresholds (adx_trend,
                  adx_range=0.80x, adx_choppy=0.60x). DriftDetector accumulates a rolling Z-score
                  of ADX values and shifts all three thresholds dynamically.
Why Dangerous   : Regime classification drives the largest filter in the system (blocks CHOPPY,
                  RANGING, HIGH_VOLATILITY, etc.). When live DriftDetector drifts ADX threshold
                  from 25.0 to 20.0 or 30.0, entire categories of setups pass the gate in backtest
                  but are blocked in live (or vice versa). This divergence widens over time as
                  the DriftDetector accumulates more data. Backtest WR predicts a static-threshold
                  world that live will never reproduce.
Recommended Fix : Document the backtest as using static non-drift-adjusted ADX thresholds.
                  Monitor DriftDetector drift in production and alert if live ADX threshold
                  deviates more than ±5 from the backtest-default 25.0. Consider a backtest
                  "replay with drift" mode for longitudinal validation.
```

---

### C5 — OHLCV Validation Missing Close/Open Bounds Checks

```
Severity        : CRITICAL
ID              : C5
Agent           : data-pipeline-validator
Problem         : fetch_binance_candles() at crypto_alert.py:1413 validates h >= l and h >= o
                  and l <= o, but NEVER checks: (a) close < low, (b) close > high,
                  (c) open < low, (d) open > high. A corrupted candle with close=0.01 or
                  open outside [low, high] passes all validation and flows into EMA200,
                  RSI, ATR, FVG detection, MSS scoring, and swing detection.
Why Dangerous   : A single Binance API glitch candle (e.g., close at 1/100th of actual price)
                  would spike ATR by 4 orders of magnitude, permanently contaminate the EMA200
                  seed value for every subsequent bar, and could trigger false FVGs with
                  enormous apparent size. Backtest fetcher has zero OHLCV validation.
Recommended Fix : Replace partial price-ordering checks with the full invariant:
                  reject if h < max(o, cl) or l > min(o, cl) or h <= 0 or l <= 0.
                  Apply same validation to fetch_historical() in backtest.py.
```

---

### C6 — Kill Switches Fully Bypassed in PAPER Mode

```
Severity        : CRITICAL
ID              : C6
Agent           : risk-management-auditor
Problem         : check_kill_switches() at crypto_alert.py:921 returns (True, None) immediately
                  when EXECUTION_MODE == "PAPER", bypassing ALL kill switches: daily loss limit,
                  weekly loss limit, consecutive-loss pause, symbol cooldown, AND the portfolio
                  drawdown gate is the ONLY active protection. Since the drawdown gate is also
                  miscalibrated (see C7), the system currently has no meaningful circuit breakers.
Why Dangerous   : 10 consecutive losses in a session generate zero halt in the current running
                  state. Paper trading is designed to inform future live decisions — if paper
                  data is collected during a period when no circuit breaker would have fired,
                  the paper WR will be inflated relative to what live would produce with kill
                  switches active.
Recommended Fix : Separate kill-switch logic: bypass daily/weekly dollar-cap kills in paper,
                  but keep consecutive-loss pause and circuit breaker active in paper mode so
                  paper data is representative of live conditions.
```

---

### C7 — Drawdown Gate Uses Trade-Price-% Not Capital-Impact-%

```
Severity        : CRITICAL
ID              : C7
Agent           : risk-management-auditor
Problem         : PortfolioRiskLayer.check() at adaptive_engine.py:935-954 sums the last 20
                  profit_pct values (trade-level price-movement percentages, e.g. -0.85 for a
                  0.85% SL hit) and compares against MAX_DRAWDOWN_PCT * 100 = 20.0. The
                  profit_pct values are price-movement % (e.g. -0.85), not capital-impact %
                  (which would be RISK_PER_TRADE_PCT * price-movement / SL_distance = ~1%).
                  The 2026-05-21 fix corrected the factor-of-100 bug but the unit-mismatch
                  between price-% and capital-% remains.
Why Dangerous   : With 20 trades all hitting MIN_SL_PCT=0.5%: sum = -10.0, gate never fires
                  (threshold -20.0). With 20 trades all hitting MAX_SL_PCT=3%: sum = -60.0,
                  gate fires. The actual capital loss in the first case is ~10% (10 trades × 1%
                  risk), well beyond the intended 20% drawdown trigger. Gate calibration is
                  broken in a direction that allows larger losses than intended.
Recommended Fix : Multiply each profit_pct by RISK_PER_TRADE_PCT to convert to capital-impact
                  units before summing. Compare sum against MAX_DRAWDOWN_PCT (not *100).
```

---

### C8 — YOUR_CAPITAL Default $1000 — No Enforcement Gate in LIVE Mode

```
Severity        : CRITICAL
ID              : C8
Agent           : live-deployment-readiness-checker + risk-management-auditor
Problem         : YOUR_CAPITAL = float(os.environ.get("YOUR_CAPITAL", "1000.0")) at
                  crypto_alert.py:76. No startup check verifies this env var is set before
                  entering LIVE mode. A user who changes EXECUTION_MODE to LIVE without setting
                  YOUR_CAPITAL will have all position sizes calculated on $1000 regardless of
                  actual account balance. With $5,000 actual capital, recommended position sizes
                  are 5x too small; with $500, positions may be below Binance's minimum notional.
Why Dangerous   : Direct financial risk at the moment of going live — incorrect position sizing
                  communicated to the operator on the first real trade.
Recommended Fix : In main(), check os.environ.get("YOUR_CAPITAL") directly (not the parsed float).
                  If absent and EXECUTION_MODE == "LIVE", abort with a clear error message
                  requiring explicit capital configuration.
```

---

### C9 — Regime Detection Uses Forming 1H Bar in Backtest

```
Severity        : CRITICAL
ID              : C9
Agent           : backtest-bias-detector
Problem         : Backtest at backtest.py:455-463 uses bisect_right(ind1h["times"], ts_ms - 1) - 1
                  to find the last 1H bar. This finds the bar whose open timestamp straddles ts_ms.
                  In pre-loaded historical data, closes[idx_1h_reg] is the bar's FINAL close value
                  (the bar is complete in the dataset). In live trading at signal time, this bar
                  has not yet closed — it reflects only the partial candle progress so far.
Why Dangerous   : The backtest uses the final close of a still-forming 1H bar for regime
                  classification. Live trading must use only CLOSED 1H bars. Regime gates
                  (blocking CHOPPY, RANGING, etc.) may fire differently, creating a systematic
                  bias where the backtest over-classifies TRENDING (using the final close) versus
                  what live would see mid-candle. WR is inflated by an unmeasurable amount.
Recommended Fix : Use bisect_right(ind1h["times"], ts_ms - 3600000) - 1 (subtract one 1H period
                  in ms) to guarantee only fully closed 1H bars are used for regime classification.
```

---

### C10 — EXECUTION_MODE Hardcoded String — Ambiguous/Risky Mode Switch

```
Severity        : CRITICAL
ID              : C10
Agent           : live-deployment-readiness-checker + risk-management-auditor
Problem         : EXECUTION_MODE = "PAPER" at crypto_alert.py:139 is a hardcoded string literal,
                  not read from an environment variable. adaptive_engine.py:111 reads
                  EXECUTION_MODE from os.environ.get("EXECUTION_MODE", "PAPER"). These two reads
                  are independent — if someone changes the source file to "LIVE" without setting
                  the env var, adaptive_engine gets PAPER limits (MAX_OPEN_POSITIONS=20) while
                  crypto_alert runs in LIVE mode. Switching to LIVE requires a source code edit
                  with no documented operator procedure.
Why Dangerous   : (a) Source edit at the live-switch moment carries bug-introduction risk.
                  (b) EXECUTION_MODE mismatch between the two modules can enable LIVE mode
                  signal behavior with PAPER mode risk limits (20 simultaneous positions × 1% = 20%
                  portfolio risk instead of 4%). (c) The kill switch at main() guards a constant
                  that can never be "LIVE" without a code change, making it misleading in docs.
Recommended Fix : Read EXECUTION_MODE from os.environ.get("EXECUTION_MODE", "PAPER") in
                  crypto_alert.py. Add a startup assertion that both modules read the same value.
```

---

### C11 — profit_pct Double-Conversion Undocumented Fragility

```
Severity        : CRITICAL
ID              : C11
Agent           : risk-management-auditor
Problem         : profit_pct is stored in the DB as percentage points (e.g., -0.85 for a 0.85%
                  loss). In _trigger_weight_update() at crypto_alert.py:1167, it is divided by 100
                  before being passed to adaptive_engine.update(). Inside update() at
                  adaptive_engine.py:342, the value is divided by 0.01 (i.e., multiplied by 100).
                  Net effect: -0.85 → -0.0085 → -0.85. The double-conversion cancels out and is
                  currently correct, but only due to the clamping to [-2.0, +2.0] masking errors.
Why Dangerous   : Any future code that reads profit_pct from the DB and assumes it is a decimal
                  fraction (0.0085) instead of percentage points (-0.85) will produce OGD rewards
                  that are 100x wrong. The cancellation is invisible, not documented, and will be
                  broken the first time someone touches either conversion without knowing about
                  the other.
Recommended Fix : Remove the /100 conversion at crypto_alert.py:1167. Pass profit_pct directly
                  to update(). Add a comment at the DB schema level documenting the unit:
                  "profit_pct stored as percentage points (e.g., -0.85 = 0.85% loss)".
```

---

### C12 — DR Metadata Stored from Wrong Reference Price

```
Severity        : CRITICAL
ID              : C12
Agent           : ict-logic-validator + live-backtest-consistency-checker
Problem         : In live generate_signal(), dr_4h at crypto_alert.py:2062 is computed using
                  price (current spot price). A second DR at lines 2122-2123 uses _entry_ref
                  (FVG bottom/top) for the actual gate check. The stored dr_4h in the signal
                  record uses the first computation (spot price). In backtest (backtest.py:518-522),
                  only one DR is computed using _entry_ref throughout.
Why Dangerous   : When price and the FVG edge straddle the equilibrium band boundary (±5% of
                  range midpoint), the two DR computations yield different location values. The
                  stored dr_location (used for EV scoring, OGD feature weights, template tagging,
                  and all DR-bucketed win-rate analysis) is based on the wrong reference price
                  in live mode. All EV population lookups and OGD dr_location weight updates
                  from this point forward are corrupted. This is data pollution that worsens
                  over time.
Recommended Fix : Replace the first dr_4h computation in generate_signal() with _entry_ref
                  (consistent with backtest). Remove the duplicate _dr_gate computation. Use a
                  single DR result for both the gate and the stored metadata.
```

---

## HIGH PROBLEMS

---

### ICT Logic HIGH Issues (Agent 1)

```
H1 — Displacement Bar Has No Absolute ATR Minimum
Agent           : ict-logic-validator
Problem         : detect_ict_displacement() at ict_engine.py:90-108 uses only relative body
                  size (body >= avg_body * 1.5 AND body/range >= 0.55). In low-volatility
                  consolidation, avg_body can be tiny, making a 0.03% displacement body
                  qualify as "displacement" if avg_body was 0.02%. This is not institutional
                  displacement — it is noise.
File            : ict_engine.py:90-108
Why Dangerous   : False displacement signals in flat markets pass through to FVG+MSS stages,
                  producing spurious setups. Even with blocked regimes, HIGH_VOLATILITY periods
                  are allowed through, where absolute displacement distance matters most.
Fix Direction   : Add minimum absolute displacement: body must be at least 0.3% of price,
                  or at least 0.5× ATR(N) of prior N bars.

H2 — MSS Sequence Guard Off-By-One: Rejects Valid Setups
Agent           : ict-logic-validator
Problem         : backtest.py:538 and crypto_alert.py:2093 reject signals when
                  mss_result["mss_bar"] <= disp_bar + 1. The FVG is a 3-candle pattern using
                  bars [d-1, d, d+1]. MSS should be allowed from bar d+2 onward. The current
                  check blocks MSS at bar d+1 (the third FVG candle itself — a valid MSS bar).
                  Valid setups where MSS fires simultaneously with FVG close are rejected.
File            : backtest.py:538, crypto_alert.py:2093
Why Dangerous   : Valid ICT setups are systematically rejected. This partially explains the low
                  n≈34/year and may inflate WR by removing borderline-valid setups.
Fix Direction   : Change condition to mss_result["mss_bar"] < disp_bar + 2 (require MSS at
                  disp_bar+2 or later) in both files.

H3 — OGD Bootstrap: No Degenerate Weight Check on Output
Agent           : ict-logic-validator + adaptive-learning-code-reviewer
Problem         : bootstrap_from_backtest() at adaptive_engine.py:443-540 completes and persists
                  weights to backtest_token_weights without any post-bootstrap health check.
                  DEGENERATE_THRESHOLD=0.60 check only runs lazily at runtime in generate_signal().
                  No direction-balance validation on input data.
File            : adaptive_engine.py:443-540
Why Dangerous   : If bootstrap produces degenerate weights (dr_location > 0.60), no alert is
                  raised. Bootstrap weights flow into live confidence scoring immediately.
Fix Direction   : Call health_check() immediately after bootstrap_from_backtest() and log a
                  visible warning if any token shows is_degenerate=True. Add direction balance
                  check: warn if SELL fraction > 60% in bootstrap input.
```

---

### Backtest Validity HIGH Issues (Agent 2)

```
H4 — Consumed Sweeps Not Tracked in Backtest Loop
Agent           : backtest-bias-detector
Problem         : detect_ict_sweep() at ict_engine.py:44-75 has a consumed parameter for tracking
                  used sweeps. At backtest.py:477, the call passes no consumed argument — it
                  defaults to set() (empty, local) on every single bar iteration. The same sweep
                  can generate multiple signals on consecutive bars until cooldown expires.
File            : backtest.py:477, ict_engine.py:44-56
Why Dangerous   : Signal count n is inflated (same structural sweep fires multiple times).
                  Win rates may be inflated or deflated. Live bot (which may have a consumed set)
                  will generate fewer signals than backtest predicts. This is a fundamental
                  cause of n-inflation.
Fix Direction   : Instantiate per_token_consumed = {} before the bar loop. Pass the set to
                  detect_ict_sweep(). Add the returned sweep's (bar, level) key to the set
                  after a signal is recorded.

H5 — No Recency Constraint on MSS: Ancient Setups Trigger Entry Scans
Agent           : backtest-bias-detector
Problem         : score_ict_mss() scans for MSS across the entire lookback window without
                  requiring the confirmed setup to be recent relative to the current bar i.
                  A sweep from 280 bars ago (>23 hours) with its MSS 250 bars ago can still
                  trigger an entry scan at bar i. No maximum age constraint.
File            : backtest.py:533-534, ict_engine.py:135-148
Why Dangerous   : In live trading, a 23-hour-old ICT setup is no longer actionable. By allowing
                  ancient setups to trigger entries, the backtest generates opportunities a
                  disciplined live trader would not take. Signal count and potentially WR are
                  affected.
Fix Direction   : Add a maximum age constraint requiring MSS confirmation within the last
                  ENTRY_WINDOW (72) bars of the current detection bar.

H6 — OGD Weights From Prior Backtest Runs Contaminate Later Runs
Agent           : backtest-bias-detector
Problem         : At backtest.py:2335, load_backtest_ogd_weights() loads whatever OGD weights
                  are in the DB from prior runs. Later experiments use those weights for
                  confidence scoring. Each bootstrap at line 2399-2401 trains on the current
                  run's output and persists, polluting the next run. Sequential optimizer
                  experiments (15+) accumulate compounding OGD contamination.
File            : backtest.py:2335, 2399-2401
Why Dangerous   : Confidence scores in later experiments are influenced by OGD weights trained
                  on earlier experiments' data. Template tier assignments and EV scores are
                  subtly biased by the optimization path history, not just the current config.
Fix Direction   : Reset OGD weights to AE_DEFAULT_WEIGHTS when running optimization experiments.
                  Only bootstrap from a confirmed final configuration.
```

---

### Live vs Backtest Consistency HIGH Issues (Agent 3)

```
H7 — Entry Reaction Look-Back Window: 4 Bars Backtest vs 6 Bars Live
Agent           : live-backtest-consistency-checker
Problem         : Backtest uses 4-bar window (backtest.py:591: _r_start = max(0, j - 4)).
                  Live uses 6-bar window (crypto_alert.py:2140-2141: _N5_react = min(len(c5_all), 6)).
                  Entry type classification (REACTION_CONFIRMED vs ZONE_TOUCH) drives the entry
                  gate that rejects ~17.9% WR ZONE_TOUCH setups. 5th and 6th bar can change
                  the classification from ZONE_TOUCH to REACTION_CONFIRMED.
File            : backtest.py:591 vs crypto_alert.py:2140-2141
Why Dangerous   : Backtest may accept setups as ZONE_TOUCH that live classifies as
                  REACTION_CONFIRMED (or vice versa), changing which setups are accepted.
                  Corrupts WR prediction for the ZONE_TOUCH-filtered subset.
Fix Direction   : Extract the reaction look-back window into a single constant in ict_engine.py
                  and import it in both callers.

H8 — DR Classification Different Reference in Live vs Backtest
Agent           : live-backtest-consistency-checker (same as C12 above — this is the HIGH
                  aspect: the live confidence scoring impact)
[See C12 for full description]
```

---

### Adaptive Learning HIGH Issues (Agent 4)

```
H9 — OGD Threshold Mismatch: Updates at n=10, Signal Path Ignores Until n=30
Agent           : adaptive-learning-code-reviewer
Problem         : update() begins modifying weights after n=10 (OGD_MIN_SAMPLES at
                  adaptive_engine.py:50). generate_signal() only applies OGD weights when
                  n >= 30 (SAMPLE_N_OBSERVE at crypto_alert.py:1963-1975). Between n=10 and n=29,
                  the engine updates weights in DB but the signal path uses defaults. Bootstrap
                  weights loaded at startup are also discarded by the n >= SAMPLE_N_OBSERVE gate.
File            : crypto_alert.py:1963-1975, adaptive_engine.py:50
Why Dangerous   : Bootstrap warm-start is completely bypassed. Effective learning does not begin
                  until n=30 (~10.5 months at 34/year), not n=10 as the comment implies. 20
                  wasted OGD updates before any effect on signals.
Fix Direction   : Lower SAMPLE_N_OBSERVE to match OGD_MIN_SAMPLES (10), or add a separate
                  bootstrap threshold that allows bootstrap-loaded weights to be used when
                  n_live == 0 without waiting for n >= 30.

H10 — Decay Rate Erases 64% of Learned Weights Between Signals
Agent           : adaptive-learning-code-reviewer
Problem         : decay_toward_default() called every 30 minutes (crypto_alert.py:2859-2861).
                  At decay_rate=0.002, over 514 calls between signals (34/year = one signal
                  every ~10.7 days × 48 calls/day), 1 - 0.998^514 = 64% of any learned
                  deviation is erased before the next signal fires.
File            : crypto_alert.py:2859-2861, adaptive_engine.py:562-576
Why Dangerous   : The learning system fights its own regularization. Each trade's weight
                  signal is reduced to 36% of amplitude before the next trade can reinforce it.
                  Learning from persistent patterns (e.g., OVERNIGHT session consistently
                  loses) requires many consecutive confirming signals to survive decay.
Fix Direction   : Suppress decay_toward_default() for tokens that had a live OGD update within
                  the last 7 days (compare updated_at from token_weights against current time).
```

---

### Risk Management HIGH Issues (Agent 5)

```
H11 — Kill Switch Only at startup main() — Not Injection-Proof
Agent           : risk-management-auditor
Problem         : LIVE_MODE_CONFIRMED check at crypto_alert.py:2793-2804 is in main() only.
                  A caller who imports generate_signal() directly (test harness, future
                  integration, Jupyter notebook) bypasses the kill switch entirely.
File            : crypto_alert.py:2793-2804
Why Dangerous   : As the system evolves toward execution integration, this assumption breaks.
                  Currently limited to signal-only risk.
Fix Direction   : Add module-level _live_mode_confirmed flag set at startup. Assert inside
                  generate_signal() that EXECUTION_MODE != "LIVE" or _live_mode_confirmed.

H12 — Drawdown Uses LIMIT 20 Rolling Window, Not Peak-to-Trough Equity Curve
Agent           : risk-management-auditor
Problem         : adaptive_engine.py:935-954 sums LAST 20 profit_pct values. Not a
                  peak-equity-to-current-equity drawdown. A run of 100 trades with losses
                  scattered and the last 20 being 15 wins + 5 losses will never trigger.
File            : adaptive_engine.py:935-954
Why Dangerous   : During a regime change producing extended losing streak, interspersed wins
                  keep the rolling window above the threshold. No true drawdown gate exists.
Fix Direction   : Track running equity in bot_state table. Update peak_equity on each trade.
                  Compute drawdown as (peak - current) / peak. Compare against MAX_DRAWDOWN_PCT.

H13 — EXECUTION_MODE Read from Two Independent Sources
Agent           : risk-management-auditor
Problem         : crypto_alert.py:139 — hardcoded string "PAPER". adaptive_engine.py:111 —
                  os.environ.get("EXECUTION_MODE", "PAPER"). If source is changed to "LIVE"
                  without setting the env var, adaptive_engine gets PAPER limits
                  (MAX_OPEN_POSITIONS=20) while crypto_alert runs LIVE logic.
File            : crypto_alert.py:139, adaptive_engine.py:111
Why Dangerous   : In LIVE mode with PAPER portfolio limits, up to 20 simultaneous open
                  positions allowed: 20 × 1% = 20% portfolio at risk simultaneously.
Fix Direction   : [Same as C10] Read EXECUTION_MODE from env var in crypto_alert.py.

H14 — Kill Switch Uses Loss Count Approximation, Not Actual P&L
Agent           : risk-management-auditor
Problem         : check_kill_switches() at crypto_alert.py:936-948 calculates
                  daily_loss_pct = n_daily * RISK_PER_TRADE_PCT. Does not use actual
                  profit_pct from the results table.
File            : crypto_alert.py:936-948
Why Dangerous   : A tight SL hit (-0.3%) counts the same as a maximum SL hit (-1.5%). In
                  a gap-through event where actual loss exceeds the stop distance, the kill
                  switch underestimates capital loss. A sequence of 3 tight-SL losses
                  (actual -0.9%) triggers the count-based halt even though drawdown is small.
Fix Direction   : Sum ABS(profit_pct) * RISK_PER_TRADE_PCT for today's losses from the
                  results table rather than counting events.

H15 — YOUR_CAPITAL Max Position 100% Notional Concentration Risk
Agent           : risk-management-auditor
Problem         : MAX_POSITION_PCT = 1.0 at adaptive_engine.py (LIVE mode). With
                  capital=$1000, risk_pct=1%, sl_pct=0.5% (minimum SL): notional =
                  (1000×0.01)/0.005 = $2000, capped to $1000 (100% of capital).
File            : adaptive_engine.py (MAX_POSITION_PCT definition), crypto_alert.py:1902
Why Dangerous   : Tight-stop setups recommend 100% of capital as the notional position.
                  If price gaps through the stop, 100% of capital is at risk on a single trade.
Fix Direction   : Lower MAX_POSITION_PCT to 0.20-0.25 (20-25% of capital per trade).
```

---

### Data Pipeline HIGH Issues (Agent 6)

```
H16 — API Retry Storm: Maximum Cycle Time 752 Seconds (vs 90s Target)
Agent           : data-pipeline-validator
Problem         : API_RETRIES=3, API_DELAY=10s between attempts, 0.3s inter-call delay.
                  With 9 tokens × 4 timeframes = 36 fetch calls: worst-case cycle time
                  = 36 × (10 + 0.3 + 10 + 0.3 + 0.3) ≈ 752 seconds. This is 8.4× the
                  90-second target cycle interval.
File            : crypto_alert.py:1437, crypto_alert.py:2913-2917
Why Dangerous   : During VPN reconnect or Binance outage, open signals are not monitored
                  for up to 12+ minutes. SL hits during this window are missed. In live
                  mode, this is a capital protection failure.
Fix Direction   : Add a per-token total fetch timeout (not per-attempt). Reduce API_DELAY
                  for retries within a cycle to 2-3s. Reserve longer backoff for between
                  full cycle attempts. Use requests.Session() to reduce connection overhead.

H17 — Stale Candle Guard Not Applied to TP/SL Monitor
Agent           : data-pipeline-validator
Problem         : _age > STALE_CANDLE_THRESHOLD guard at crypto_alert.py:2893 only applies
                  to signal generation. monitor_open_signals() at line 2873 runs unconditionally
                  before the stale check, using potentially stale candle data (crypto_alert.py:
                  2711-2715) for TP/SL hit detection.
File            : crypto_alert.py:2685-2725, crypto_alert.py:2873
Why Dangerous   : In live mode, a TP1 or SL can be missed during a stale data window.
                  Signal stays OPEN while market has already moved past SL level.
Fix Direction   : Add per-token age check inside monitor_open_signals() before using
                  candle extremes for TP/SL detection.

H18 — BTC 10-Minute Filter Staleness (BTC_FETCH_INTERVAL=600s)
Agent           : data-pipeline-validator
Problem         : BTC_FETCH_INTERVAL=600s at crypto_alert.py:162. Between refreshes, the
                  BTC trend used to allow/block alt signals is up to 10 minutes stale,
                  even though BTC candles in STATE are refreshed every 90s cycle.
File            : crypto_alert.py:1479-1498
Why Dangerous   : If BTC drops 2% in 5 minutes (flash drop), bot continues allowing BUY
                  signals on alts for up to 10 minutes using stale BULL classification.
Fix Direction   : When BTC is in BINANCE_TOKENS, always refresh BTC_STATE trends from the
                  already-fetched current candles (ignore BTC_FETCH_INTERVAL). The interval
                  only matters for the BTC fallback fetch path.

H19 — BTC Feed Failure Silently Enables All Alt Signals (NEUTRAL = ALLOW)
Agent           : data-pipeline-validator
Problem         : When c1h is empty after fetch failure, get_trend([]) returns "NEUTRAL"
                  (indicators.py:60: len < 200 → "NEUTRAL"). get_btc_filter() at
                  crypto_alert.py:1518-1560 treats NEUTRAL as ALLOW for both BUY and SELL.
File            : crypto_alert.py:1492, crypto_alert.py:1518-1560
Why Dangerous   : BTC API outage removes the primary macro filter. Bot generates alt signals
                  without any BTC alignment check. Warning is printed but no signal suppression.
Fix Direction   : Track BTC_STATE["data_valid"] boolean. In get_btc_filter(), treat
                  data_valid=False as CAUTION (confidence penalty) or BLOCK rather than ALLOW.

H20 — Gap in 5M Data: Detection Logs Warning But Takes No Action
Agent           : data-pipeline-validator
Problem         : Gap detection at crypto_alert.py:1420-1428 detects and logs missing 5M
                  candles but ICT analysis proceeds unchanged. A 6-bar gap inside a 3-candle
                  FVG pattern produces a false FVG. ICT displacement/MSS lookback of 9 bars
                  can span 90 real minutes instead of 45 due to undetected gaps.
File            : crypto_alert.py:1420-1428
Why Dangerous   : False FVG zones formed by missing data can trigger full ICT signal chains.
Fix Direction   : Reduce _GAP_TOLERANCE to 0 for 5M. On detected gap, skip signal generation
                  for that token that cycle and use stale data for open signal monitoring only.
```

---

### Live Deployment HIGH Issues (Agent 7)

```
H21 — env.example.bat Not in .gitignore
Agent           : live-deployment-readiness-checker
Problem         : .gitignore:2 lists env.bat but not env.example.bat, which contains a real
                  Telegram token. If a git remote is added, env.example.bat is committed.
File            : .gitignore:2
Why Dangerous   : Token committed to git history is permanently exposed in all forks/mirrors.
Fix Direction   : Add env.example.bat to .gitignore (do this WITH token rotation from C1).

H22 — tracker.py Counts PARTIAL as Full Win (WR Inflated in Dashboard)
Agent           : live-deployment-readiness-checker
Problem         : tracker.py:191 (get_intelligence) and :268 (_get_adaptive_weights_raw):
                  sum(1 for (r,) in rows if r in ("WIN","PARTIAL")) counts PARTIAL=1.0.
                  Canonical formula _canonical_wr() at tracker.py:71 uses PARTIAL=0.5.
                  These are two of the three WR display paths — both inflate.
File            : tracker.py:191, tracker.py:268
Why Dangerous   : Operator sees inflated per-token WR in dashboard Intelligence and Adaptive
                  Weight tabs. Marginal tokens look healthier than they are, delaying corrective
                  action.
Fix Direction   : Replace inline win-count expressions with calls to existing _canonical_wr().

H23 — adaptive_engine.py Uses datetime.now() (Local Time) in DB Persistence
Agent           : live-deployment-readiness-checker + adaptive-learning-code-reviewer
Problem         : adaptive_engine.py:413, :428 use datetime.now() (UTC+8 local) for
                  token_weights.updated_at and market_stats.updated_at. Lines 532, 638, 676
                  correctly use datetime.utcnow(). Inconsistency is internal to the same file.
File            : adaptive_engine.py:413, :428
Why Dangerous   : Dashboard queries comparing updated_at to signal timestamps (UTC) are 8 hours
                  off. Bot shows "last updated 8h ago" for a just-updated weight. Staleness
                  detection is wrong in Philippines timezone (UTC+8).
Fix Direction   : Standardize all datetime.now() calls in persistence methods to
                  datetime.now(timezone.utc) or datetime.utcnow().

H24 — No System-Level Auto-Start on Machine Reboot
Agent           : live-deployment-readiness-checker
Problem         : Restart mechanism is a batch file loop (scripts/start_bot.bat:31-46) — in-
                  session crash recovery only. No Windows service, Task Scheduler entry, or
                  NSSM registration. Machine restart at 3am = no signals until manual restart.
File            : scripts/start_bot.bat
Why Dangerous   : Open signals not marked expired on bot down. Duplicate signal guard can
                  get stuck. N=30 paper milestone delayed by missed signals.
Fix Direction   : Create a Windows Task Scheduler task to run start_bot.bat at system startup.
                  Document the configuration in scripts/ so it survives a Windows reinstall.

H25 — LIVE MODE ACTIVATED Telegram Alert Fires Before init_db()
Agent           : live-deployment-readiness-checker
Problem         : Startup sequence in main(): kill switch check → send Telegram LIVE alert →
                  init_db() → restore_cooldowns(). If init_db() fails (disk full, DB corrupted),
                  operator received "LIVE MODE ACTIVATED" but bot is not running.
File            : crypto_alert.py:2806-2812
Why Dangerous   : Operator believes bot is live-trading. May take manual positions.
Fix Direction   : Reorder: init_db() first, then kill switch check, then LIVE alert.
```

---

## UNIFIED ISSUE LIST

All issues from all agents, sorted by severity.

```
ID    | Sev      | Agent                    | Short description                                              | File:line
------|----------|--------------------------|----------------------------------------------------------------|----------------------------------
C1    | CRITICAL | deploy-readiness         | Real Telegram tokens in env files (security exposure)          | env.bat:5, env.example.bat:5
C2    | CRITICAL | backtest-bias            | Walk-forward OOS not a true hold-out (data snooping)           | backtest.py:1362-1367
C3    | CRITICAL | live-backtest-consistency| iFVG spatial gate absent in backtest                            | backtest.py:667 vs crypto_alert.py:2299
C4    | CRITICAL | live-backtest-consistency| Regime ADX static backtest vs DriftDetector live               | backtest.py:459 vs crypto_alert.py:1577
C5    | CRITICAL | data-pipeline            | OHLCV validation missing close/open bounds checks              | crypto_alert.py:1413
C6    | CRITICAL | risk-management          | Kill switches fully bypassed in PAPER mode                     | crypto_alert.py:921
C7    | CRITICAL | risk-management          | Drawdown gate uses trade-price-% not capital-impact-%          | adaptive_engine.py:935-954
C8    | CRITICAL | deploy-readiness         | YOUR_CAPITAL default $1000, no enforcement gate in LIVE        | crypto_alert.py:76
C9    | CRITICAL | backtest-bias            | Regime detection uses forming 1H bar                           | backtest.py:455-463
C10   | CRITICAL | deploy-readiness         | EXECUTION_MODE hardcoded — ambiguous/risky mode switch         | crypto_alert.py:139
C11   | CRITICAL | risk-management          | profit_pct double-conversion undocumented fragility            | crypto_alert.py:1167, adaptive_engine.py:342
C12   | CRITICAL | ict-logic                | DR metadata from spot price vs FVG edge — corrupts EV/OGD     | crypto_alert.py:2062, 2122-2123
H1    | HIGH     | ict-logic                | Displacement has no ATR minimum (purely relative)              | ict_engine.py:90-108
H2    | HIGH     | ict-logic                | MSS guard off-by-one: rejects valid same-bar MSS               | backtest.py:538, crypto_alert.py:2093
H3    | HIGH     | ict-logic                | Bootstrap: no degenerate weight check on output                | adaptive_engine.py:443-540
H4    | HIGH     | backtest-bias            | Consumed sweeps not tracked in backtest loop                   | backtest.py:477
H5    | HIGH     | backtest-bias            | No recency constraint on MSS — ancient setups trigger entries  | backtest.py:533-534
H6    | HIGH     | backtest-bias            | OGD weights from prior runs contaminate later backtest runs    | backtest.py:2335, 2399-2401
H7    | HIGH     | live-backtest-consistency| Entry reaction window 4 bars backtest vs 6 bars live           | backtest.py:591 vs crypto_alert.py:2140
H8    | HIGH     | adaptive-learning        | OGD threshold mismatch: updates n=10, signal path n=30         | crypto_alert.py:1963-1975
H9    | HIGH     | adaptive-learning        | Decay erases 64% of learned weights before next signal         | crypto_alert.py:2861, adaptive_engine.py:562
H10   | HIGH     | risk-management          | Kill switch only in main() — not injection-proof               | crypto_alert.py:2793-2804
H11   | HIGH     | risk-management          | Drawdown uses LIMIT 20 rolling window, not equity curve        | adaptive_engine.py:935-954
H12   | HIGH     | risk-management          | EXECUTION_MODE read from two independent sources               | crypto_alert.py:139, adaptive_engine.py:111
H13   | HIGH     | risk-management          | Kill switch uses loss count approximation, not actual P&L      | crypto_alert.py:936-948
H14   | HIGH     | risk-management          | MAX_POSITION_PCT=1.0 allows 100% notional concentration        | adaptive_engine.py (MAX_POSITION_PCT)
H15   | HIGH     | data-pipeline            | API retry storm: max cycle 752s vs 90s target                  | crypto_alert.py:1437, 2913
H16   | HIGH     | data-pipeline            | Stale candle guard not applied to TP/SL monitor                | crypto_alert.py:2685-2725, 2873
H17   | HIGH     | data-pipeline            | BTC 10-minute filter staleness (BTC_FETCH_INTERVAL=600s)       | crypto_alert.py:1479-1498
H18   | HIGH     | data-pipeline            | BTC feed failure silently enables all alt signals              | crypto_alert.py:1492, 1518-1560
H19   | HIGH     | data-pipeline            | Gap detection logs but takes no action — false FVGs possible   | crypto_alert.py:1420-1428
H20   | HIGH     | deploy-readiness         | env.example.bat not in .gitignore (will be committed)          | .gitignore:2
H21   | HIGH     | deploy-readiness         | tracker.py counts PARTIAL as full win (WR inflated)            | tracker.py:191, 268
H22   | HIGH     | deploy-readiness         | adaptive_engine.py uses datetime.now() (local) in DB writes    | adaptive_engine.py:413, 428
H23   | HIGH     | deploy-readiness         | No system-level auto-start on machine reboot                   | scripts/start_bot.bat
H24   | HIGH     | deploy-readiness         | LIVE MODE alert fires before init_db()                         | crypto_alert.py:2806-2812
M1    | MEDIUM   | ict-logic                | Hardcoded 30 in MSS lookback (not ICT_SWEEP_LOOKBACK constant) | ict_engine.py:129, 141
M2    | MEDIUM   | ict-logic                | ASIA_KZ includes UTC 00:00-01:59 (dead zone, not Asia KZ)      | adaptive_engine.py:76
M3    | MEDIUM   | ict-logic                | DR uses rolling statistical range not structural swing extremes | ict_engine.py:361-381
M4    | MEDIUM   | ict-logic                | FVG mitigation uses outer edge — should use 50% midpoint       | ict_engine.py:227-230
M5    | MEDIUM   | ict-logic                | DR gate only blocks EQUILIBRIUM — BUY PREMIUM/SELL DISCOUNT pass| crypto_alert.py:2121, backtest.py:525
M6    | MEDIUM   | ict-logic                | Cooldown anchored to entry bar not detection bar               | backtest.py:620-624
M7    | MEDIUM   | ict-logic                | iFVG bonus in backtest without spatial gate (live has it)      | backtest.py:667, ict_engine.py:536
M8    | MEDIUM   | backtest-bias            | Slippage double-counted in backtest eff_price                  | backtest.py:639-640
M9    | MEDIUM   | backtest-bias            | Walk-forward only 14 OOS signals — CIs span ±26pp              | backtest.py:1362-1367
M10   | MEDIUM   | backtest-bias            | Survivorship bias: SOL excluded based on backtest performance  | optimization_experiments.md
M11   | MEDIUM   | backtest-bias            | Signal count overstated — no portfolio position limits modeled | backtest.py:444-624
M12   | MEDIUM   | adaptive-learning        | Live trigger sends generic PARTIAL (not TP1/TP2 differentiated)| crypto_alert.py:1036-1041
M13   | MEDIUM   | adaptive-learning        | Confidence circular feedback loop in OGD gradient              | crypto_alert.py:2308, adaptive_engine.py:1075
M14   | MEDIUM   | adaptive-learning        | No SELL-bias guard in bootstrap input data                     | adaptive_engine.py:458-476
M15   | MEDIUM   | risk-management          | ROUND_TRIP_COST_PCT understates fees for HBAR/POL/ADA          | ict_engine.py:22
M16   | MEDIUM   | risk-management          | MAX_CONSECUTIVE_LOSSES=3 not persistent across restarts        | crypto_alert.py:128-129, 963-975
M17   | MEDIUM   | risk-management          | CIRCUIT_BREAKER_MIN_WR=0.35 — too low (allows 65% loss rate)  | crypto_alert.py:141-142
M18   | MEDIUM   | risk-management          | MAX_PORTFOLIO_RISK_PCT=0.15 is a dead gate (never reached)     | adaptive_engine.py:115
M19   | MEDIUM   | data-pipeline            | No warning when Binance returns fewer candles than requested   | crypto_alert.py:1399-1438
M20   | MEDIUM   | data-pipeline            | No OHLCV validation in backtest fetcher (fetch_historical)     | backtest.py:185-215
M21   | MEDIUM   | data-pipeline            | Exit intelligence uses forming 5M candle for RSI/MACD          | crypto_alert.py:2721
M22   | MEDIUM   | data-pipeline            | _GAP_TOLERANCE=2 silently accepts 2 missing 5M candles         | crypto_alert.py:1397
M23   | MEDIUM   | deploy-readiness         | tracker.py hardcodes _MAX_OPEN=3 (should be 4 in LIVE)         | tracker.py:231-232
M24   | MEDIUM   | deploy-readiness         | liquid_hours=range(24) removes all session filtering in LIVE   | strategy_engine.py:132-133
M25   | MEDIUM   | deploy-readiness         | Kill switch daily loss uses count×1% not actual P&L            | crypto_alert.py:936-948
M26   | MEDIUM   | deploy-readiness         | No startup Binance connectivity check before main loop         | crypto_alert.py:2812, 2853
M27   | MEDIUM   | deploy-readiness         | LIVE_PAPER_COLLECTION_READINESS_REPORT.md has stale params     | docs/LIVE_PAPER_COLLECTION_READINESS_REPORT.md:48-51
L1    | LOW      | ict-logic                | 4H bias uses max() of last 3 swings vs most recent swing level | ict_engine.py:330, 334
L2    | LOW      | ict-logic                | Displacement body calc fails near warmup start (if j > 0 edge) | ict_engine.py:91
L3    | LOW      | ict-logic                | FVG mitigation guard condition is redundant (cosmetic)         | ict_engine.py:226
L4    | LOW      | ict-logic                | NY_AM_KZ starts at UTC 12 (should be UTC 13)                   | adaptive_engine.py:78
L5    | LOW      | ict-logic                | TP2 can land below TP1 under specific 4R-cap interactions      | ict_engine.py:638-644
L6    | LOW      | adaptive-learning        | datetime.now() vs utcnow() inconsistency in adaptive_engine.py | adaptive_engine.py:413, 428 vs 532, 638
L7    | LOW      | adaptive-learning        | health_check() not called after bootstrap_from_backtest()      | adaptive_engine.py (bootstrap end)
L8    | LOW      | data-pipeline            | CoinGecko: no retry backoff on failure, stale dom_dir persists | crypto_alert.py:1500-1516
L9    | LOW      | data-pipeline            | Daily summary RSI uses forming candle (no [:-1] exclusion)     | crypto_alert.py:2764
L10   | LOW      | data-pipeline            | No 429 handling in backtest fetcher — silent partial data      | backtest.py:185-215
L11   | LOW      | deploy-readiness         | tracker.py datetime.now() vs UTC for bot_active calculation    | tracker.py:374, 380
L12   | LOW      | deploy-readiness         | LIVE_PAPER readiness report token table shows SOL (removed)    | docs/LIVE_PAPER_COLLECTION_READINESS_REPORT.md:126
```

**Issue Count: CRITICAL: 12 | HIGH: 25 | MEDIUM: 27 | LOW: 12 | TOTAL: 76**

---

## Hidden Risks

1. **Walk-forward confidence illusion** — With n=34 signals and 15+ optimizer experiments, the reported WR=85.3% has 95% CI [69.2%, 94.4%]. The optimization ran far beyond the statistical capacity of the sample. The WFgap of -0.7% represents only ~14 OOS signals. A single win/loss flip changes the gap by ±7pp. The system's apparent statistical edge is indistinguishable from noise at this sample size.

2. **Compounding OGD decay** — With 34 signals/year and decay_toward_default() every 30 minutes, learned weights return to defaults in ~10 days between signals. When OGD does eventually activate (n=30), every update is fighting a constant erosion force. The system will never converge to stable learned weights without either more signal frequency or a suppressed decay rate.

3. **DriftDetector temporal divergence** — The longer live trading runs, the further DriftDetector's ADX thresholds drift from the backtest defaults. Regime classifications that were accurate in paper backtest become increasingly inaccurate as the live ADX threshold shifts. This is a slow-burn divergence that is invisible until the live WR drops.

4. **SELL-bias bootstrap time bomb** — If the backtest data is SELL-heavy (plausible in a bear market period), bootstrap produces degenerate dr_location weights. These weights are used for confidence scoring until n=30 live signals accumulate. Up to 10.5 months of paper signals would be scored with potentially corrupted weights, corrupting the very data used to validate the pre-live readiness.

5. **Partial candle in exit intelligence** — Exit RSI/MACD in monitor_open_signals() uses the forming 5M candle. During volatile 5M candles, the partial close can show false overbought/oversold readings. The system could suggest "CONSIDER PARTIAL CLOSE" based on intra-candle noise during a strong trend continuation bar.

6. **Memory accumulation across 960 cycles/day** — With CHECK_INTERVAL=90s, the main loop runs 960 iterations/day. STATE dict grows with each token update. consumed_sweeps entries are pruned by age but the pruning logic needs verification for memory leaks over weeks of uptime.

7. **Simultaneous BUY+SELL on same token** — The duplicate signal guard only blocks same-direction duplicates (in LIVE mode). A BUY and SELL signal for ETH can both be OPEN simultaneously. The PARTIAL result from TP1 on the BUY while the SELL is also open creates a confusing position state for a manual trader.

---

## Missing Components

1. **Phase 5B per-template OGD** — Not implemented. Single shared weight vector per token across all template tiers. Required for 10/10 adaptive learning score.

2. **Genuine walk-forward validation** — No locked-OOS validation against a period that was never seen during optimization. Required for 10/10 backtest validity.

3. **Consumed sweeps in backtest loop** — The consumed set infrastructure exists in ict_engine.py but is never wired into the backtest bar loop. Required for accurate signal count.

4. **ATR-based absolute displacement minimum** — Displacement filter is purely relative (body/avg-body). No floor against flat-market noise.

5. **Equity curve peak-to-trough drawdown** — No running equity tracking. Drawdown gate uses rolling sum approximation. Required for production-grade risk management.

6. **System-level process supervision** — No Windows service, Task Scheduler entry, or watchdog. Crash recovery is batch-file-only and not reboot-persistent.

7. **Backtest OHLCV validation** — fetch_historical() has zero data quality checks. Live bot has partial checks (with gaps per C5). Backtest should match live.

8. **Post-bootstrap health validation** — health_check() exists but is never called after bootstrap completes. Degenerate weights only detected lazily at signal generation time.

---

## Architecture Weaknesses

1. **Monolithic generate_signal()** — The function spans hundreds of lines and handles sweep detection, displacement, FVG, MSS, iFVG, SMT, regime, DR, session, DOW, template scoring, EV scoring, confidence, risk, and signal dispatch. It is impossible to unit-test individual stages. Any future modification risks unintended interactions between stages.

2. **EXECUTION_MODE as hardcoded string** — The most dangerous single-point-of-failure in the architecture. Mode switches require source edits. The two-module mismatch (hardcoded vs env-var) means risk controls can be wrong at the exact moment of going live.

3. **SQLite under multi-writer concurrency** — tracker.py and crypto_alert.py both write to the same SQLite file. WAL mode is not explicitly enabled. Under load (tracker serving a dashboard request while crypto_alert writes a new signal), lock contention is possible. SQLite's writer lock is exclusive.

4. **No integration test for live/backtest consistency** — There is no automated test that verifies generate_signal() and run_backtest_token() produce the same intermediate state for a given bar. The 22-point consistency audit found 4 material divergences manually. These would have been caught by an integration test suite.

5. **Adaptive engine module-level state** — weight_engine, drift_detector, portfolio_layer are module-level singletons. In a multi-token parallel future, this creates shared state contention. Currently sequential, so no immediate issue, but blocks horizontal scaling.

6. **No structured operational runbook** — The pre-live checklist is in memory files, not in the project. There is no documented operator procedure for: starting the bot, switching from PAPER to LIVE, rotating tokens, rotating Telegram tokens, or responding to specific alert types.

---

## Trading Strategy Weaknesses

1. **DR gate is only half-implemented** — The gate blocks EQUILIBRIUM entries (correct) but allows BUY in PREMIUM and SELL in DISCOUNT (incorrect ICT practice). High-probability losing setups are passing through on every bar where price is in the wrong zone.

2. **Dealing range from rolling max/min** — ICT dealing ranges should be bounded by confirmed structural swing extremes, not statistical rolling max/min over 50×4H bars (~8.3 days). The wide statistical range compresses most setups to DISCOUNT/PREMIUM, making the DR location label overconfident about directional context.

3. **FVG mitigation uses full traversal** — ICT defines FVG mitigation as 50% fill (midpoint breached). Current code requires the close to pass through the outer FVG edge. Setups using half-filled (degraded) FVGs are accepted and may produce lower-quality entries.

4. **MSS off-by-one suppresses valid setups** — Valid ICT setups where MSS fires on the bar immediately after FVG close (disp_bar+1) are rejected. This artificially reduces signal count and may be a contributing factor to n≈34/year being sparse.

5. **Session boundary imprecision** — ASIA_KZ includes UTC 00:00-01:59 (actually post-NY dead zone). NY_AM_KZ starts at UTC 12 (actually 07:00 NY, pre-open). Session quality scores are wrong for these boundary hours, affecting OGD confidence calibration.

6. **No recency constraint on ICT setups** — A sweep+displacement+FVG+MSS sequence from 23 hours ago can still trigger an entry scan. In live ICT trading, any setup more than 2-4 hours old is considered stale. Allowing 23-hour-old setups to generate entries may explain some of the backtest WR optimism.

---

## Adaptive Learning Weaknesses

1. **Bootstrap warm-start completely bypassed** — The primary pre-live differentiation (bootstrapped weights) is ignored for the first 10.5 months of live trading due to the SAMPLE_N_OBSERVE=30 gate. The system runs on default equal weights during the entire paper-trading period.

2. **Learning fights its own decay** — With 34 signals/year and 30-minute decay, the signal-to-decay ratio is approximately 0.36 (each trade's weight signal decays to 36% before the next trade). Persistent market patterns that last weeks cannot accumulate enough weight signal to survive the constant decay erosion.

3. **Statistical confidence at activation** — At OGD_MIN_SAMPLES=10, the engine starts updating weights based on ~10 trades. Wilson interval at WR=85% on n=10: CI=[55%, 97%]. The engine is fitting noise with statistical confidence spanning the full range of possible outcomes.

4. **Confidence circular feedback** — The confidence feature is both an input to the OGD gradient and an output of OGD weights. This creates a feedback loop where high-confidence weight → confidence score rises → confidence feature credited more on WIN → weight rises further. The loop can amplify or suppress confidence independently of real market signal.

5. **Phase 5B (per-template OGD) not implemented** — A single weight vector per token means a TIER_A BTC signal and a TIER_C BTC signal share the same feature weights. Template-specific learning cannot occur. Phase 5B was identified as required for 10/10 adaptive learning score.

---

## Database & Tracker Problems

1. **tracker.py:191, :268** — PARTIAL counted as WIN=1.0 in two out of three WR display paths. Only the main stats panel uses the canonical 0.5 weight. Dashboard shows inflated per-token WR in Intelligence and Adaptive Weights tabs.

2. **adaptive_engine.py:413, :428** — token_weights.updated_at and market_stats.updated_at stored in local Philippines time (UTC+8) while signals table uses UTC. Join queries for temporal analysis produce 8-hour offset. Dashboard "last updated" display is wrong for 7 months of daylight saving time in the US (which changes UTC offset comparisons).

3. **tracker.py:231-232** — _MAX_OPEN=3 and _MAX_SAME_DIR=2 hardcoded, independent of adaptive_engine MAX_OPEN_POSITIONS=4 (LIVE). Dashboard will show incorrect "slots_free" when in LIVE mode.

4. **tracker.py:374, :380** — bot_active comparison uses datetime.now() (local) vs bot_state.last_cycle_ts (UTC). In Philippines (UTC+8), bot shows "inactive" from 00:00-07:59 UTC (08:00-15:59 local) when it is actually running.

5. **No foreign key enforcement test** — PRAGMA foreign_keys=ON is confirmed set in all _connect() calls (Pattern 3 PASS), but there is no automated test that verifies orphaned results records cannot be created.

---

## Documentation Inconsistencies

1. **docs/LIVE_PAPER_COLLECTION_READINESS_REPORT.md:48-51** — States fvg_min_quality=MEDIUM and mss_min_quality=MEDIUM. Current code: fvg_min_quality=HIGH and mss_min_quality=LOW. Report predates Run 43 acceptance of FVG=HIGH.

2. **docs/LIVE_PAPER_COLLECTION_READINESS_REPORT.md:126-136** — Token table includes SOL and shows only 8 tokens. Current code: 9 tokens without SOL, with BNB/ADA/POL added.

3. **docs/optimization_experiments.md** — Correctly documents Run 60 quality config and rollbacks. No inconsistencies with current code state. PASS.

4. **memory/project_state.md** — Correctly reflects all 2026-05-21 fixes. However, pre-LIVE checklist item "LIVE mode kill switch (LIVE_MODE_CONFIRMED=YES required)" is misleading — EXECUTION_MODE is hardcoded and cannot be switched by env var. The kill switch is a startup gate for a constant that can never change to "LIVE" without a source edit.

5. **backtest.py:12** — Comment says "Phase 4.5" but the system is at Phase 5A. Minor version label staleness.

6. **crypto_alert.py:1** — Docstring says "Crypto Signal Bot v11" but strategy is v2 (STRATEGY_VERSION = "v2" at line 99). Version inconsistency in file header vs internal version constant.

---

## Immediate Fix Priority List

All 76 issues ranked by urgency:

| Rank | ID | Sev | One-line description | Estimated impact if fixed |
|---|---|---|---|---|
| 1 | C1 | CRITICAL | Revoke exposed Telegram tokens in env files | Prevents fake-signal attack; immediate security |
| 2 | C10 | CRITICAL | Read EXECUTION_MODE from env var (not hardcoded) | Eliminates mode-switch ambiguity; fixes H12 |
| 3 | H20 | HIGH | Add env.example.bat to .gitignore | Prevents token commit on git remote add |
| 4 | C3 | CRITICAL | Add iFVG spatial gate to backtest (same as live) | Fixes confidence divergence; improves WR prediction |
| 5 | C12 | CRITICAL | Use FVG edge reference for DR metadata (not spot price) | Stops DR data pollution in EV/OGD from this point forward |
| 6 | H2 | HIGH | Fix MSS guard off-by-one in both paths | Increases signal count; aligns backtest with live |
| 7 | H7 | HIGH | Unify entry reaction window constant (4 bars → shared) | Fixes entry type divergence between paths |
| 8 | C5 | CRITICAL | Add close/open bounds to OHLCV validation | Prevents corrupt candle from poisoning all indicators |
| 9 | C11 | CRITICAL | Remove profit_pct /100 conversion — document DB unit | Eliminates fragile double-conversion |
| 10 | C7 | CRITICAL | Fix drawdown gate to use capital-impact % | Calibrates the primary circuit breaker correctly |
| 11 | H11 | HIGH | Fix drawdown to use peak-to-trough equity curve | True drawdown gate replaces rolling window approximation |
| 12 | C9 | CRITICAL | Fix regime detection to use only closed 1H bars | Eliminates live/backtest regime divergence |
| 13 | H4 | HIGH | Wire consumed sweeps tracking into backtest loop | Deflates n; makes signal count realistic |
| 14 | H8 | HIGH | Lower SAMPLE_N_OBSERVE to match OGD_MIN_SAMPLES=10 | Bootstrap weights activate; learning begins at n=10 |
| 15 | H9 | HIGH | Suppress decay_toward_default() for recently-updated tokens | Learning survives inter-signal gaps |
| 16 | C6 | CRITICAL | Keep circuit breaker active in PAPER mode | Paper data representative of live conditions |
| 17 | C8 | CRITICAL | Enforce YOUR_CAPITAL env var in LIVE mode startup | Prevents position sizing error at live switch |
| 18 | H22 | HIGH | Fix tracker.py PARTIAL=0.5 in all WR calculations | Accurate WR displayed to operator |
| 19 | H23 | HIGH | Fix datetime.now() → datetime.utcnow() in adaptive_engine.py | All DB timestamps in UTC |
| 20 | H16 | HIGH | Apply stale candle guard to TP/SL monitor | Prevents missed SL hits during data gaps |
| 21 | H18 | HIGH | BTC feed failure → CAUTION not ALLOW | Fail-safe macro filter on data outage |
| 22 | H17 | HIGH | Fix BTC 10-min staleness (ignore interval if BTC in tokens) | BTC filter uses current cycle data |
| 23 | H15 | HIGH | Add timeout cap to API retry per cycle | Prevent 752s cycles during outages |
| 24 | H24 | HIGH | Set up Windows Task Scheduler for bot auto-start | Survive machine reboots |
| 25 | C2 | CRITICAL | Lock OOS date before next optimization | Genuine forward-test validation |
| 26 | H5 | HIGH | Add MSS recency constraint (ENTRY_WINDOW bars) | Reject stale 23-hour-old setups |
| 27 | C4 | CRITICAL | Document ADX threshold divergence; monitor drift | Understand live-backtest regime gap |
| 28 | H19 | HIGH | Add 5M gap → skip generation for gapped token | Prevent false FVGs from missing bars |
| 29 | M20 | MEDIUM | Add OHLCV validation to fetch_historical() | Clean backtest data matches live validation |
| 30 | M21 | MEDIUM | Apply [:-1] to closes in exit RSI/MACD | Prevent intra-candle RSI noise in exit suggestions |
| 31 | M5 | MEDIUM | Extend DR gate to block BUY-PREMIUM and SELL-DISCOUNT | Implement full ICT DR direction logic |
| 32 | M4 | MEDIUM | Change FVG mitigation to use 50% midpoint | Align with ICT standard |
| 33 | M12 | MEDIUM | Pass PARTIAL_TP1/PARTIAL_TP2 to OGD trigger | Differentiated reward signals in live |
| 34 | M13 | MEDIUM | Remove confidence from OGD gradient features | Break circular feedback loop |
| 35 | M14 | MEDIUM | Add SELL-bias guard in bootstrap input | Prevent degenerate dr_location weight |
| 36 | L7 | LOW | Call health_check() after bootstrap_from_backtest() | Immediate degenerate weight detection |
| 37 | M8 | MEDIUM | Remove double-counted slippage in backtest eff_price | Consistent fee model between paths |
| 38 | H6 | HIGH | Reset OGD weights for optimization experiments | Clean experiment independence |
| 39 | M23 | MEDIUM | Import MAX_OPEN_POSITIONS in tracker.py (not hardcoded) | Accurate slot count in dashboard |
| 40 | M27 | MEDIUM | Update LIVE_PAPER_COLLECTION_READINESS_REPORT.md | Remove stale parameter values |
| 41-76 | M9-M26, L1-L12 | MED/LOW | Various medium/low priority issues | See unified list above |

---

## Long-Term Recommendations

1. **Run a locked-OOS validation before the next production decision.** Fix the OOS boundary (last 90 days) before running any more experiments. Run the current quality config against that locked period. The reported WR=85.3% must be validated against data the optimizer never saw. This is the single most important action for trusting the strategy.

2. **Break generate_signal() into testable sub-functions.** The function currently handles 15+ distinct stages. Extract: detect_ict_sweep_and_displacement(), score_fvg_and_mss(), compute_dr_and_session_context(), evaluate_gates(), compute_signal_plan(). This enables unit testing of each stage independently and prevents regression bugs when any stage is modified.

3. **Implement true equity-curve drawdown tracking.** The current rolling-sum drawdown is not a production-grade circuit breaker. Add bot_state.peak_equity and bot_state.current_equity fields. Update on each closed trade. Compare (peak-current)/peak against MAX_DRAWDOWN_PCT. This is the standard risk management primitive for all professional trading systems.

4. **Design a formal live/backtest consistency test suite.** The 22-point manual consistency check found 4 material divergences. Write an automated test that instantiates both generate_signal() and run_backtest_token() with the same synthetic bar sequence and asserts identical intermediate state at each ICT detection step. Run this test in CI before every merge to strategy-relevant files.

5. **Implement Phase 5B per-template OGD after N≥50 live signals.** The current single-weight-vector-per-token architecture cannot differentiate between TIER_A and TIER_C setups for the same token. Phase 5B is required for the adaptive system to produce genuine per-template improvement. Plan timeline: ~18 months from paper start (50 signals at 34/year).

6. **Replace the batch-file process supervisor with a proper Windows service.** NSSM (Non-Sucking Service Manager) is free and takes 5 minutes to configure. It provides: automatic restart on crash, start on boot, proper stdout/stderr logging to Windows Event Log, service start/stop controls. This eliminates the most significant operational fragility in the deployment stack.

7. **Add a structured ICT recency requirement.** Require that the MSS confirmation occurred within ENTRY_WINDOW bars of the current detection bar. In ICT methodology, a setup older than 2-4 hours is stale. This both aligns with ICT principles and reduces the risk of entering on expired structural context.

8. **Implement token-tier slippage model.** Flat 0.05%/side slippage ignores the liquidity reality of HBAR and POL versus BTC and ETH. Use: BTC/ETH/BNB: 0.02%/side; XRP/AVAX/LINK/ADA: 0.05%/side; HBAR/POL: 0.10-0.15%/side. This makes cost assumptions more realistic and slightly reduces modeled edge for the illiquid alts.

9. **Implement the full ICT dealing range gate.** The current gate only blocks EQUILIBRIUM. The complete ICT logic is: BUY only from DISCOUNT (≤50% of range), SELL only from PREMIUM (≥50%). The gate was simplified for backtest pragmatism, but in production trading with real capital, taking a BUY at PREMIUM is the single most common reason ICT setups fail. Extend the gate and retest to see the WR and frequency impact.

10. **Consider replacing online OGD with a periodic offline retraining approach.** Given 34 signals/year and the known limitations of online learning at low sample frequency, an offline batch retraining step every 90-180 days (when n_new >= 20 signals) with proper cross-validation may outperform continuous OGD updates that fight their own decay rate between signal events. The infrastructure change is modest: keep the current weight persistence but replace the per-signal gradient update with a scheduled batch logistic regression or similar on the accumulated closed signal dataset.

---

## Raw Agent Outputs

Agents reported findings independently. Conflicts between agents (if any) are resolved in the synthesis above in favor of the more conservative (more safety-focused) interpretation.

- **Agent 1 (ict-logic-validator):** 0 CRITICAL, 4 HIGH, 7 MEDIUM, 5 LOW — ICT logic score 61/100. NO-GO for live until H2 (MSS off-by-one), H3 (DR metadata), M7 (iFVG backtest gate) fixed.
- **Agent 2 (backtest-bias-detector):** 2 CRITICAL, 4 HIGH, 6 MEDIUM — verdict "OPTIMISTIC + FRAGILE". WR=85.3% 95% CI [69.2%, 94.4%]. Walk-forward gap not a valid OOS result.
- **Agent 3 (live-backtest-consistency-checker):** 2 CRITICAL, 2 HIGH, 2 MEDIUM — consistency score 62/100. NO-GO for live mode.
- **Agent 4 (adaptive-learning-code-reviewer):** 0 CRITICAL, 2 HIGH, 3 MEDIUM, 2 LOW — verdict "Partially adaptive — infrastructure real, but sample size too small for meaningful improvement at current signal frequency". 2026-05-21 SQL fix confirmed present.
- **Agent 5 (risk-management-auditor):** 3 CRITICAL, 6 HIGH, 5 MEDIUM — verdict "AT RISK for live trading". Drawdown gate miscalibrated, mode mismatch possible, kill switches bypassed in paper.
- **Agent 6 (data-pipeline-validator):** 4 CRITICAL, 6 HIGH, 8 MEDIUM, 3 LOW — verdict "AT RISK". OHLCV validation incomplete, BTC feed fail-open, stale candle not guarding TP/SL monitor.
- **Agent 7 (live-deployment-readiness-checker):** 3 CRITICAL, 6 HIGH, 8 MEDIUM, 4 LOW — verdict "NO-GO". Tokens exposed, EXECUTION_MODE hardcoded, YOUR_CAPITAL unenforced.
