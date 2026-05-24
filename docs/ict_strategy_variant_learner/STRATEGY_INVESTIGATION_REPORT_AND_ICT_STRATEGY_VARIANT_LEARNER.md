# TradeAI Strategy Investigation Report
**Date:** 2026-05-20  
**Type:** Read-only investigation — no files modified

---

## A. Executive Summary

**Current strategy in plain English:**
The bot is an ICT-style liquidity sweep and FVG retracement signal generator operating on 5-minute candles. It detects a confirmed swing high/low sweep, then requires a displacement candle to appear within 9 bars (45 min), a fair-value gap at that displacement candle, a market structure shift after the sweep, and price returning into the FVG zone with a reaction candle. The 4H bias and 1H trend filter direction (loose mode). It is **not purely sequence-based** — it checks ICT components exist and partially validates their order (sweep → displacement → FVG → price in zone → reaction), but does **not** enforce strict timing between displacement and MSS, and does not confirm HTF Point of Interest.

**Whether strict ICT sequence or general confluence-based:**
Hybrid. It partially validates sequence (displacement must follow sweep, FVG is anchored to displacement bar, MSS must occur after sweep) but MSS is not verified to occur after displacement, and there is no HTF POI requirement.

**Biggest missing pieces vs. proper ICT model:**
1. No HTF POI (specific institutional level) — only directional bias
2. MSS not enforced to occur after displacement (could fire out of order)
3. No retracement depth check (price just needs to touch FVG, not retrace a specific distance)
4. SMT is logged but not gated (`smt_gate=False`)
5. Dealing range gate is disabled (`dealing_range_gate=False`)
6. No session-specific blocking (all 24H used in LIVE_CONFIG learning phase)

---

## B. Signal Flow Map

**Call path:** `main loop → check_tokens() → generate_signal(token, price, change_24h, volume_24h)` in `crypto_alert.py:1670`

**Step-by-step signal decision process:**

```
1.  crypto_alert.py:generate_signal()
    ├── Get closed 5M candles (exclude forming bar)          [line 1737-1747]
    ├── Compute RSI/MACD/ATR/trend/vol_ratio (logging only)  [line 1690-1695]
    ├── detect_regime() via indicators.py                     [line 1701]
    │     uses 1H candles, ADX+ATR+efficiency
    ├── OGD weight loading from adaptive_engine.py            [line 1705-1717]
    │     falls back to DEFAULT_WEIGHTS if n < 30 closed trades
    ├── EARLY EXIT: blocked regime OR illiquid session        [line 1720-1723]
    ├── check_kill_switches() - daily/weekly loss, streaks   [line 1726]
    │
    ├── compute 4H bias via get_ict_4h_bias()                 [line 1765]
    │     ict_engine.py: EMA50/200 + swing structure break on 4H closed bars
    ├── compute 1H trend via get_trend()                      [line 1771]
    │     indicators.py: EMA50 vs EMA200
    │
    ├── GATE: evaluate_setup() → strategy_engine.py          [line 1774]
    │     Gate 1: direction enabled (enable_buy/enable_sell)
    │     Gate 2: session liquid hours
    │     Gate 3: regime not in blocked_regimes
    │     Gate 4: 4H bias (loose: blocks hard countertrend only)
    │     Gate 5: 1H trend (loose: blocks hard countertrend only)
    │     → REJECT if any fails, log to rejections table
    │
    ├── find_ict_swings() on 5M                              [line 1750]
    │     ict_engine.py: confirmed swing highs/lows (2-bar lag)
    ├── detect_ict_sweep() on 5M (lookback=30 bars=2.5H)     [line 1753]
    │     ict_engine.py: BSL or SSL sweep on recent swing
    │     → RETURN None if no sweep found
    ├── Assign direction: SSL→BUY, BSL→SELL                  [line 1757]
    │
    ├── GATE: detect_ict_displacement()                       [line 1792]
    │     ict_engine.py: body>=1.5x avg, body_ratio>=0.55, within 9 bars of sweep
    │     → RETURN None if not found
    │
    ├── GATE: score_ict_fvg() at displacement bar            [line 1798]
    │     ict_engine.py: 3-bar gap pattern [disp-1, disp, disp+1]
    │     direction must match signal; quality >= fvg_min_quality (LOW)
    │     → RETURN None if no FVG or wrong direction or quality too low
    │
    ├── GATE: score_ict_mss() on 5M (horizon=30 bars=2.5H)  [line 1812]
    │     ict_engine.py: close through most recent prior swing after sweep_bar
    │     quality >= mss_min_quality (LOW)
    │     → RETURN None if not confirmed or quality too low
    │
    ├── detect_ict_ifvg() on 5M — metadata only              [line 1827]
    ├── detect_5m_ifvg_entry() — precision entry zone        [line 1828]
    │     if found, narrows FVG entry zone
    │
    ├── [GATE: dealing_range_gate — currently DISABLED]      [line 1839]
    │
    ├── GATE: price inside FVG entry zone                    [line 1868]
    │     entry_bottom <= price <= entry_top
    │     → RETURN None if price not in zone
    │
    ├── GATE: detect_fvg_entry_reaction() on last 6 5M bars  [line 1875]
    │     requires MIDPOINT_RECLAIM or REACTION_CONFIRMED
    │     ZONE_TOUCH = no reaction → RETURN None
    │
    ├── get_btc_filter() — BTC correlation hard BLOCK        [line 1891]
    │     BTC 1H/15M trend must not oppose signal direction
    │     → RETURN None if BTC hard opposing
    │
    ├── Cooldown check (SIGNAL_COOLDOWN=0, effectively disabled) [line 1903]
    ├── [open signal guard — commented out for learning phase] [line 1908]
    │
    ├── detect_smt_divergence() on BTC 5M — metadata only    [line 1922]
    │     [GATE: smt_gate=False, not enforced]
    │
    ├── compute_liquidity_targets() — 1H swing TP pool       [line 1948]
    ├── compute_ict_trade_plan() — structural SL, pool TPs   [line 1958]
    │     SL = 0.3% beyond swept wick; TP from liquidity pool
    │     → RETURN None if plan invalid (SL too large/small, BEW > 60%)
    │
    ├── GATE: R:R >= ICT_MIN_RR_GATE (1.5x)                  [line 1963]
    │     → RETURN None if R:R < 1.5
    │
    ├── portfolio_layer.check() — exposure/drawdown cap      [line 1974]
    │     adaptive_engine.py: MAX_OPEN_POSITIONS=20 (unlimited in learning)
    │     → RETURN None if portfolio cap hit
    │
    ├── compute_ev_score() — historical EV lookup            [line 2005]
    │     adaptive_engine.py: hierarchical bucket (L1-L5)
    │     GATE: blocks only if NEGATIVE EV AND sample_n >= 100
    │     → RETURN None if confirmed negative EV
    │
    ├── OGD confidence score (5-10)                          [line 2029-2056]
    │     weighted by OGD features: fvg_quality, mss_quality,
    │     session, trend_strength, dr_location
    ├── GATE: confidence >= _conf_floor (dynamic, starts at 5) [line 2057]
    ├── GATE: ranging/unknown floor adjustment               [line 2062]
    ├── GATE: per-token WR gate (tightens if token WR < 35%) [line 2071]
    │
    └── RETURN signal dict + regime dict
```

---

## C. Current Required BUY Conditions

| Condition | Required? | Config | Current Value | Blocks Signal? | File/Function |
|---|---|---|---|---|---|
| BUY enabled | Required | `enable_buy` | `True` | YES | `strategy_engine.py:167` |
| Liquid session | Required | `liquid_hours` | All 24H (learning phase) | YES | `strategy_engine.py:176` |
| Regime not blocked | Required | `blocked_regimes` | CHOPPY, HIGH_VOL, TRENDING_BEAR, LOW_VOL_CHOP, LIQUIDATION | YES | `strategy_engine.py:183` |
| 4H bias not BEARISH | Required (loose) | `bias_4h_gate="loose"` | BEARISH blocks BUY; NEUTRAL allowed | YES | `strategy_engine.py:207` |
| 1H trend not BEAR/STRONG_BEAR | Required (loose) | `trend_1h_gate="loose"` | BEAR/STRONG_BEAR blocks BUY | YES | `strategy_engine.py:230` |
| SSL sweep detected | Required | `ICT_SWEEP_LOOKBACK=30` | Last 30 5M bars (2.5H) | YES | `ict_engine.py:43` |
| Kill switches pass | Required | `MAX_DAILY_LOSSES=3` etc | 3 losses/day, 3% capital, 3 consecutive | YES | `crypto_alert.py:1726` |
| Displacement candle | Required | `ICT_DISP_MAX_LOOK=9` | Within 9 bars (45 min) of sweep | YES | `ict_engine.py:66` |
| FVG BUY direction at disp bar | Required | `fvg_min_quality="LOW"` | LOW or better | YES | `ict_engine.py:180` |
| MSS confirmed (CHoCH above) | Required | `mss_min_quality="LOW"` | LOW or better; within 30 bars | YES | `ict_engine.py:98` |
| Price inside FVG entry zone | Required | hardcoded | price between FVG bottom and top | YES | `crypto_alert.py:1868` |
| FVG reaction confirmed | Required | hardcoded (P1-A) | MIDPOINT_RECLAIM or REACTION_CONFIRMED | YES | `ict_engine.py:244` |
| BTC not BEAR/STRONG_BEAR | Required | hardcoded | BTC 1H trend must not be bearish | YES | `crypto_alert.py:1891` |
| Trade plan valid (SL/TP) | Required | `MAX_SL_PCT=3%`, `MIN_SL_PCT=0.5%`, `MAX_BREAKEVEN_WR=0.60` | BEW <= 60%, SL between 0.5%-3% | YES | `ict_engine.py:594` |
| R:R >= 1.5 | Required | `ICT_MIN_RR_GATE=1.5` | 1.5x minimum | YES | `crypto_alert.py:1963` |
| Portfolio cap | Required | `MAX_OPEN_POSITIONS=20` | 20 (effectively unlimited) | YES | `adaptive_engine.py:94` |
| EV not confirmed negative | Required (after 100 samples) | `SAMPLE_N_USABLE=100` | Only blocks at n>=100 | YES (conditionally) | `adaptive_engine.py:992` |
| Confidence >= dynamic floor | Required | `_conf_floor` (starts at 5) | Min 5, raises if low WR levels detected | YES | `crypto_alert.py:2057` |
| Dealing range (DISCOUNT) | Optional | `dealing_range_gate=False` | **DISABLED** | No | `ict_engine.py:326` |
| SMT divergence | Optional | `smt_gate=False` | **DISABLED** | No | `ict_engine.py:420` |
| IFVG precision entry | Optional | none | Narrows entry zone if found, not required | No | `ict_engine.py:471` |

---

## D. Current Required SELL Conditions

| Condition | Required? | Config | Current Value | Blocks Signal? | File/Function |
|---|---|---|---|---|---|
| SELL enabled | Required | `enable_sell` | `True` | YES | `strategy_engine.py:171` |
| Liquid session | Required | `liquid_hours` | All 24H (learning phase) | YES | `strategy_engine.py:176` |
| Regime allowed for SELL | Required | `blocked_regimes`, `sell_allowed_regimes` | TRENDING_BEAR unblocked for SELL | YES | `strategy_engine.py:183` |
| 4H bias not BULLISH | Required (loose) | `bias_4h_gate="loose"` | BULLISH blocks SELL; NEUTRAL allowed | YES | `strategy_engine.py:210` |
| 1H trend not BULL/STRONG_BULL | Required (loose) | `trend_1h_gate="loose"` | BULL/STRONG_BULL blocks SELL | YES | `strategy_engine.py:233` |
| BSL sweep detected | Required | `ICT_SWEEP_LOOKBACK=30` | Last 30 5M bars | YES | `ict_engine.py:43` |
| Kill switches pass | Required | same as BUY | same | YES | `crypto_alert.py:1726` |
| Displacement candle (bearish) | Required | `ICT_DISP_MAX_LOOK=9` | Within 9 bars of sweep | YES | `ict_engine.py:66` |
| FVG SELL direction at disp bar | Required | `fvg_min_quality="LOW"` | LOW or better | YES | `ict_engine.py:180` |
| MSS confirmed (CHoCH below) | Required | `mss_min_quality="LOW"` | LOW or better; within 30 bars | YES | `ict_engine.py:98` |
| Price inside FVG entry zone | Required | hardcoded | price between FVG bottom and top | YES | `crypto_alert.py:1868` |
| FVG reaction confirmed (bearish) | Required | hardcoded (P1-A) | MIDPOINT_RECLAIM or REACTION_CONFIRMED | YES | `ict_engine.py:244` |
| BTC not BULL/STRONG_BULL | Required | hardcoded | BTC 1H must not be bullish for SELL | YES | `crypto_alert.py:1893` |
| Trade plan valid | Required | same as BUY | same | YES | `ict_engine.py:594` |
| R:R >= 1.5 | Required | `ICT_MIN_RR_GATE=1.5` | same | YES | `crypto_alert.py:1963` |
| Dealing range (PREMIUM) | Optional | `dealing_range_gate=False` | **DISABLED** | No | `ict_engine.py:326` |
| SMT divergence | Optional | `smt_gate=False` | **DISABLED** | No | `ict_engine.py:420` |

**Key SELL difference:** `TRENDING_BEAR` regime is unblocked for SELL (`sell_allowed_regimes={"TRENDING_BEAR"}`). 4H BULLISH blocks SELL instead of BEARISH. BTC must not be bullish.

---

## E. Confluence Order Validation

| ICT Step | Currently Detected? | Required? | Sequence Validated? | Notes |
|---|---|---|---|---|
| 1. Liquidity sweep | YES | YES (hard gate) | N/A — first step | `detect_ict_sweep()` scans last 30 5M bars |
| 2. Displacement | YES | YES (hard gate) | PARTIAL — scans bars sweep_bar+1 to +9 only | displacement must occur after sweep, within 9 bars |
| 3. MSS/CHoCH | YES (scored) | YES (hard gate) | PARTIAL — scans from sweep_bar+1 forward | MSS looks for close beyond prior swing level, scans same window as displacement — could technically fire before displacement |
| 4. FVG creation | YES (scored) | YES (hard gate) | YES — anchored to displacement bar | `score_ict_fvg()` called with `disp_bar`; checks [disp-1, disp, disp+1]; FVG is the displacement candle's gap |
| 5. Retracement into FVG | PARTIAL | YES (hard gate) | NO explicit retracement depth | Only checks "price is inside FVG zone now" — no verification that price first moved away then came back |
| 6. Reaction confirmation | YES | YES (hard gate) | YES — checks last 6 5M bars | `detect_fvg_entry_reaction()` requires bullish/bearish body at zone edge |
| 7. Final signal | YES | YES | N/A | Signal emitted only if all gates above pass |

**Critical sequence gaps:**
- MSS is scanned from `sweep_bar+1` (same start as displacement), so MSS could technically confirm before the displacement candle fires. In practice, displacement needs only 1 bar while MSS needs a CHoCH close — so MSS almost always comes after displacement, but this is not enforced by code.
- No "retracement" check: the bot does not verify that price was inside the FVG, then moved away, then returned. It only checks that current price is inside the FVG zone.
- No HTF POI: 4H bias is directional (BULLISH/BEARISH/NEUTRAL), not a specific price level.

---

## F. Strategy Variant Backtest Feasibility

| Strategy Model | Can Test Now? | Requires Config Only? | Requires Code Change? | Missing Pieces |
|---|---|---|---|---|
| **Model A:** Sweep + FVG + Reaction | NO | NO | YES | Need code to skip displacement and MSS checks |
| **Model B:** Sweep + Displacement + FVG + Reaction | NO | NO | YES | Need code to skip MSS check |
| **Model C:** Sweep + MSS + FVG + Reaction | NO | NO | YES | Need code to skip displacement check |
| **Model D:** Sweep + Displacement + MSS + FVG + Reaction | YES (current) | YES | NO | Already running; tunable via config quality gates |
| **Model E:** HTF bias/POI + Sweep + Disp + MSS + FVG + Reaction | PARTIAL | YES (for bias) | YES (for POI) | 4H bias gate exists; strict mode via `bias_4h_gate="strict"`. HTF POI as specific price level does not exist |
| **Model D strict quality** | YES | YES | NO | Set `mss_min_quality="HIGH"`, `fvg_min_quality="HIGH"` in BACKTEST_CONFIG |
| **Model D with strict gates** | YES | YES | NO | Set `bias_4h_gate="strict"`, `trend_1h_gate="strict"` |
| **Model D with SMT gate** | YES | YES | NO | Set `smt_gate=True` in StrategyConfig |
| **Model D with DR gate** | YES | YES | NO | Set `dealing_range_gate=True` |
| **Model D buy-only** | YES | YES | NO | Set `enable_sell=False` |

**Existing diagnostic configs already in `backtest.py`:**
- `BACKTEST_CONFIG` — current research config (loose 4H/1H, all quality LOW)
- `GATE_OFF_CONFIG` — minimal filtering (only blocks HIGH_VOL/LIQUIDATION)
- `COUNTER_TREND_CONFIG` — no direction filtering at all
- `NEUTRAL_4H_CONFIG` — 4H loose, 1H gate none (allows pullbacks)
- `LIVE_CONFIG` — mirror of live configuration

To run all 5 models independently, **Models A, B, and C require code changes** to add `enable_displacement` and `enable_mss` flags to `StrategyConfig` plus conditional checks in the backtest signal loop.

---

## G. Logging Gaps

### What IS already logged per signal

| Field | Logged? | Location |
|---|---|---|
| symbol | YES | `signals.token` |
| direction | YES | `signals.signal` |
| timestamp | YES | `signals.timestamp` |
| market regime | YES | `signals.market_regime` |
| HTF bias (4H) | PARTIAL | `feature_scores_json` blob only — not a top-level column |
| 1H trend | YES | `signals.trend_1h` |
| liquidity sweep present | IMPLICIT | signal existence implies sweep found |
| sweep type (BSL/SSL) | YES | `signals.sweep_type` |
| MSS quality | YES | `signals.mss_quality` |
| FVG quality | YES | `signals.fvg_quality` |
| retracement into FVG | IMPLICIT | signal existence implies price was in FVG zone |
| reaction confirmed | YES | `signals.entry_type` (MIDPOINT_RECLAIM / REACTION_CONFIRMED) |
| DR location | YES | `signals.dr_location` |
| SMT confirmed | YES | `signals.smt_type` |
| killzone/session | YES | `signals.session` |
| final score (confidence) | YES | `signals.confidence` |
| rejected reason | YES | `rejections.failed_filter` + `rejection_reason` |
| win/loss | YES | `results.result` |
| EV score | YES | `signals.ev_score` |
| day of week | YES | `signals.day_of_week` |
| UTC hour | YES | `signals.hour_utc` |

### What IS MISSING and should be added

| Suggested Field | Currently Missing? | Why Needed |
|---|---|---|
| `timeframe` | YES | Strategy variant tracking when multi-TF setups are compared |
| `sweep_level` (price of swept swing) | YES — only in JSON blob | Needs own column for SQL analysis |
| `displacement_bars_after_sweep` | YES — not stored at all | Analyze displacement timing quality |
| `displacement_strength` (body/avg_body ratio) | YES — not stored | Higher displacement = stronger setup |
| `mss_bars_to_mss` | YES — only in JSON blob | Rapid MSS = stronger signal |
| `mss_score_pts` | YES — only in JSON blob | Discrimination between MSS qualities |
| `fvg_size_pct` | YES — only in JSON blob | Backtest shows HIGH FVG quality = 53% WR vs 31-33% |
| `retracement_depth_pct` (how deep price entered FVG) | NO — not computed anywhere | Key ICT quality indicator |
| `bias_4h` | YES — only in JSON blob | Needs own column; currently mapped indirectly via `trend_4h` DB label |
| `executed` status (paper/live) | NO | All signals are paper; no differentiation stored |
| `result_R` (normalized to R) | NO — `profit_pct` exists but not R-normalized | Standard performance metric |
| `max_favorable_excursion` (MFE) | NO | Needed to optimize TP placement |
| `max_adverse_excursion` (MAE) | NO | Needed to optimize SL placement |
| `strategy_model` (A/B/C/D/E) | NO | Required for clean variant comparison in DB |

---

## H. Final Recommendations

### What You Can Test Immediately (Config Only, No Code Changes)

1. **High-quality FVG filter** — Set `fvg_min_quality="HIGH"` in BACKTEST_CONFIG.
   Backtest (Run 39) shows: HIGH FVG quality = **53.3% WR** vs 31.0-33.3% for MEDIUM/LOW.
   This is the single most impactful change available via config.

2. **Dealing range gate** — Set `dealing_range_gate=True`.
   Run 39 failure classification: **43.3% of all losses** came from `entered_in_equilibrium`.
   This gate would block those entries.

3. **Strict bias gates** — Set `bias_4h_gate="strict"`, `trend_1h_gate="strict"`.
   Eliminates neutral and counter-trend trades. Reduces trade count significantly but targets only fully aligned setups.

4. **SELL-only or BUY-only** — Run 39 shows: BUY WR = 31.1%, SELL WR = 38.9%.
   SELL direction has meaningfully better backtest performance.

5. **SMT gate test** — Set `smt_gate=True`. Run 39 shows SMT NOT confirmed had higher WR (40.7% vs 34.2%) — this gate may hurt rather than help. Test it to confirm.

6. **Session restriction** — Narrow `liquid_hours` to kill zones: `[2,3,4,13,14,15,20,21,22,23]`.
   NY_AM_KZ (37.3%) and LONDON_KZ (37.7%) outperform ASIA_KZ (32.4%).

7. **Day-of-week filter** — Run 39 shows Tuesday = 11.6% WR. Worth investigating blocking Tuesdays.

### What Requires Only New Config Presets

```python
# High-quality ICT Model D — most promising starting point
STRICT_QUALITY_CONFIG = StrategyConfig(
    enable_buy=True, enable_sell=True,
    bias_4h_gate="loose", trend_1h_gate="loose",
    mss_min_quality="LOW", fvg_min_quality="HIGH",
    dealing_range_gate=True, smt_gate=False,
    blocked_regimes=("CHOPPY","HIGH_VOLATILITY","TRENDING_BEAR",
                     "LOW_VOLATILITY_CHOP","LIQUIDATION"),
    sell_allowed_regimes={"TRENDING_BEAR"},
)

# SELL-biased with DR gate
SELL_STRICT_CONFIG = StrategyConfig(
    enable_buy=False, enable_sell=True,
    bias_4h_gate="loose", trend_1h_gate="loose",
    mss_min_quality="LOW", fvg_min_quality="MEDIUM",
    dealing_range_gate=True,
    sell_allowed_regimes={"TRENDING_BEAR"},
)
```

### What Requires Code Changes

1. **Models A, B, C** — need `enable_displacement: bool` and `enable_mss: bool` flags added to `StrategyConfig` and conditional skip logic in both `generate_signal()` and `run_backtest_token()`.

2. **Strict sequence validation (MSS after displacement)** — add `mss_bar > disp_bar` check after both are detected in `generate_signal()` and `run_backtest_token()`. Approximately 3 lines.

3. **Retracement depth check** — verify price touched FVG midpoint before reaction fires. Modify `detect_fvg_entry_reaction()` to accept a `require_midpoint: bool` parameter.

4. **HTF POI** — a separate function to detect institutional order blocks or FVGs on 4H/1H as named price levels. Currently only directional bias exists, not a specific price zone.

5. **MFE/MAE tracking** — modify `check_outcome()` in `backtest.py` to track max favorable/adverse price movement relative to entry during the forward scan window.

6. **Logging improvements** — promote `sweep_level`, `displacement_bars_after_sweep`, `mss_bars_to_mss`, `fvg_size_pct`, and `bias_4h` from the JSON blob to named columns in the signals table via `ALTER TABLE` migration.

### Recommended Order of Backtest Experiments

```
Run 40: fvg_min_quality="HIGH" only           → isolate FVG quality impact
Run 41: dealing_range_gate=True only           → test if blocking equilibrium helps
Run 42: enable_sell=False (BUY-only)           → isolate BUY direction performance
Run 43: fvg_min_quality="HIGH" + DR gate       → combine two best config changes
Run 44: bias_4h_gate="strict"                  → fully aligned direction only
Run 45: smt_gate=True                          → verify SMT gate helps or hurts
Run 46: After code change — Model B (no MSS)   → measure MSS contribution
Run 47: After code change — Model C (no disp)  → measure displacement contribution
Run 48: Best config from Runs 40-45 + sequence validation code change
```

### Hard-Gate vs Scoring Strategy for Adaptive Learning

**Recommendation: Keep the current hybrid approach (hard gates as safety floor + OGD scoring above that floor).**

The current architecture is well-designed. Hard gates (sweep, displacement, FVG, MSS, entry reaction, R:R) provide non-negotiable ICT structure, while OGD scoring on top captures quality gradations.

**Key risks to address before OGD becomes useful:**

- **Sample size problem:** At 35-56 signals/token/year (Run 39), OGD won't activate (`SAMPLE_N_OBSERVE=30`) for months in live trading. The EV gate (`SAMPLE_N_USABLE=100`) won't realistically trigger for 2-3 years at current signal frequency.
  - **Fix:** Run `weight_engine.bootstrap_from_backtest()` immediately after each backtest to warm-start OGD from historical results. This function already exists in `adaptive_engine.py:366`.

- **OGD learns weights, not combinations:** The system learns relative feature weights for 6 features (fvg_quality, mss_quality, session, trend_strength, dr_location, confidence) but cannot learn that a specific **combination** is profitable (e.g., HIGH FVG + DISCOUNT + NY_AM_KZ = 60%+ WR).
  - **Fix:** Hard-gate the combination directly using config (e.g., `fvg_min_quality="HIGH"`) rather than waiting for OGD to discover it.

- **Critical finding from Run 39:** FVG HIGH quality is the single strongest predictor with 53.3% WR. Hard-gating on this (`fvg_min_quality="HIGH"`) would be more immediately effective than any OGD update.

---

*End of Section A–H. Section I below adds the ICT Strategy Variant Learner investigation (2026-05-20).*

---

## I. ICT Strategy Variant Learner — Capability Investigation

**Date:** 2026-05-20
**Status:** Read-only investigation. No code was modified.

---

### I.1 Executive Summary

The codebase has a strong ICT confluence detection and per-signal logging foundation, but it does **not** currently support an ICT Strategy Variant Learner. The core gaps are: no strategy template data model, no multi-template evaluation per signal, no per-template outcome tracking (MFE/MAE/realized R), and no backtest framework capable of comparing tiers side-by-side. However, the 12+ confluence columns already in the `signals` table and the existing OGD engine provide a solid starting point. Safe implementation is feasible in an estimated 17–25 days of targeted development.

---

### I.2 Where Are ICT Confluences Currently Detected?

All detection lives in [ict_engine.py](../ict_engine.py).

| Confluence | Function | Notes |
|---|---|---|
| Liquidity sweep (BSL/SSL) | `detect_ict_sweep()` ~L44 | Returns sweep_type + level |
| Displacement candle | `detect_ict_displacement()` ~L67 | Body/range ratio ≥ 0.55, within 9 bars of sweep |
| MSS quality | `score_ict_mss()` ~L99 | HIGH / MEDIUM / LOW / NONE |
| FVG quality | `score_ict_fvg()` ~L180 | HIGH / MEDIUM / LOW + size_pct |
| 4H HTF bias | `get_ict_4h_bias()` ~L281 | EMA50/200 + swing structure break |
| Dealing range location | `compute_dealing_range()` ~L326 | PREMIUM / DISCOUNT / EQUILIBRIUM |
| iFVG (inversion FVG) | `detect_ict_ifvg()` ~L471 | Presence, direction, zone bounds, age in bars |
| iFVG precision entry | `detect_5m_ifvg_entry()` ~L531 | Narrows entry zone on 5 m |
| Session / killzone | `_utc_to_session()` in adaptive_engine.py ~L55 | ASIA_KZ / LONDON_KZ / NY_AM_KZ / OVERNIGHT |

**Verdict:** Confluence detection is comprehensive and well-structured.

---

### I.3 Does Each Signal Log Individual Confluences?

**Yes.** The `signals` table (created in [crypto_alert.py](../crypto_alert.py) ~L206) stores each confluence as a discrete column:

| Column | Type | Purpose |
|---|---|---|
| `sweep_type` | TEXT | "BSL" / "SSL" |
| `mss_quality` | TEXT | Quality tier of MSS |
| `fvg_quality` | TEXT | Quality tier of FVG |
| `session` | TEXT | ICT killzone label |
| `dr_location` | TEXT | PREMIUM / DISCOUNT / EQUILIBRIUM |
| `ict_bias_4h` | TEXT | BULLISH / BEARISH / NEUTRAL |
| `ifvg_present` | INTEGER | Boolean |
| `ifvg_direction` | TEXT | BUY / SELL / NONE |
| `ifvg_top / ifvg_bottom` | REAL | Entry zone bounds |
| `ifvg_age_bars` | INTEGER | Age in bars |
| `smt_type` | TEXT | BULLISH / BEARISH / NONE |
| `entry_type` | TEXT | ZONE_TOUCH / REACTION_CONFIRMED / MIDPOINT_RECLAIM |
| `market_regime` | TEXT | From drift + regime detector |
| `feature_scores_json` | TEXT | Normalized ICT feature contribution scores |

**Verdict:** Individual confluences are logged. The raw material for variant learning already exists.

---

### I.4 Can Signals Be Tagged with Matched Strategy Templates?

**No.** There is no template matching, template tagging, or strategy variant identification in the codebase. Signals are generated as a single undifferentiated "ICT Liquidity Sweep + MSS + FVG" setup type. No tier, variant, or template label is ever attached to a signal.

**Gap:** A `template_id` foreign key column and a `templates` lookup table need to be created.

---

### I.5 Can Multiple Strategy Templates Be Evaluated Per Signal?

**No.** The signal generation flow in [crypto_alert.py](../crypto_alert.py) ~L2029 evaluates one set of gates sequentially. There is no:

- Template registry or list to iterate over
- Per-template scoring loop
- Variant comparison step before emission
- Mechanism to record which templates a signal almost matched

**Gap:** A `evaluate_confluences_vs_templates()` function must be built and called at signal generation time.

---

### I.6 Are Trade Outcomes Linked Back to Confluences Present at Entry?

**Partially.** The `results` table links to the original `signal_id` (which carries all confluence columns), but the link is indirect and the outcome data is incomplete:

- [crypto_alert.py](../crypto_alert.py) ~L852 `compute_failure_reason()` classifies losses into categorical labels (e.g. `"low_quality_MSS"`, `"FVG_invalidated"`, `"entered_in_premium_zone"`).
- `results` columns: `result` (WIN/PARTIAL/LOSS/EXPIRED), `profit_pct`, `closed_at`, `failure_reason`.
- **Not tracked:** realized R, MFE (max favourable excursion), MAE (max adverse excursion).
- Failure reason is a single text label, not a structured confluence-pair attribution.

**Gap:** MFE, MAE, and realized R need to be added to the `results` table. Failure reason should support multi-confluence attribution.

---

### I.7 Can the Adaptive Learning System Rank Strategy Variants Over Time?

**No.** The adaptive engine ([adaptive_engine.py](../adaptive_engine.py) ~L190) is an Online Gradient Descent (OGD) system that learns **feature-level weights** globally across all signals for 6 ICT features:

```
fvg_quality, mss_quality, session, confidence, trend_strength, dr_location
```

- Learning rate: 0.03, Momentum: 0.85
- Weights are normalized to sum to 1.0 and tracked per-token (per-symbol)
- There is no concept of a "strategy template" in the learning loop

This is **confluence weighting**, not **template variant ranking**. The system cannot currently answer "Tier A has a 62% win rate vs Tier B's 54%."

**Gap:** The OGD engine must be extended to maintain per-template outcome distributions and weight adjustments separately from global feature weights.

---

### I.8 Current Database Schema — ICT Variant Learner Audit

#### Present in schema

| Field | Table | Status |
|---|---|---|
| Confluences present (12+ columns) | `signals` | **Present** |
| Market regime | `signals` | **Present** |
| Session / killzone | `signals` | **Present** |
| HTF bias (4H) | `signals` | **Present** (as `feature_scores_json` blob, not a top-level column) |
| MSS quality | `signals` | **Present** |
| FVG quality | `signals` | **Present** |
| Entry type (reaction quality proxy) | `signals` | **Present** |
| RR ratios (rr1, rr2, rr3) | `signals` | **Present** |
| Win / loss outcome | `results` | **Present** |

#### Missing from schema

| Field | Table | Gap Severity |
|---|---|---|
| `strategy_template` / `template_id` | `signals` | **Critical** |
| `displacement_quality` (scored, not just boolean) | `signals` | **High** |
| `mfe_pct` (max favourable excursion) | `results` | **High** |
| `mae_pct` (max adverse excursion) | `results` | **High** |
| `realized_r` (actual R multiple at close) | `results` | **High** |
| `confluences_present_json` (structured list) | `signals` | **Medium** |
| `template_scores_json` (per-template eval at signal time) | `signals` | **Medium** |

**Overall verdict:** Schema is ~70% ready. It needs 7 new fields across 2 tables plus 2 new tables (`templates`, `signal_variant_matches`).

---

### I.9 Can the Config System Adjust Confluence Parameters?

**Partially.** Two layers exist:

#### Layer 1 — Adaptive OGD weights (learned, not manually configured)
Default weights in [adaptive_engine.py](../adaptive_engine.py) ~L75 are then learned online per-token. These are not per-template or per-tier.

#### Layer 2 — Gate flags in strategy config
In [strategy_engine.py](../strategy_engine.py) ~L114 (`LIVE_CONFIG`):

| Parameter | Current Value | Purpose |
|---|---|---|
| `fvg_min_quality` | `"LOW"` | Minimum FVG gate |
| `mss_min_quality` | `"LOW"` | Minimum MSS gate |
| `bias_4h_gate` | `"loose"` | 4H bias filter strictness |
| `trend_1h_gate` | `"loose"` | 1H trend filter strictness |
| `dealing_range_gate` | `False` | Enable DR location filter |
| `blocked_regimes` | frozenset | Block regimes from trading |
| `sell_allowed_regimes` | frozenset | Override for sell signals |

#### What is NOT configurable

- Required confluence combinations (e.g., "require FVG + MSS together")
- Minimum confluence count thresholds per tier
- Per-confluence quality value ranges (e.g., fvg_pct > 0.3%)
- Strategy-specific scoring functions
- Tier-level filtering rules

**Gap:** The config needs a `confluence_rules` structure capable of expressing combination requirements, not just individual gates.

---

### I.10 Can Backtesting Compare Different ICT Templates?

**No.** The backtest ([backtest.py](../backtest.py) ~L76) supports multiple named configs but only runs **one config per execution**. There is no:

- Multi-template parallel backtest runner
- Tier-by-tier result aggregation (Tier A strict vs B balanced vs C exploratory)
- Automated comparison report across config variants
- Statistical significance testing between variants

**Gap:** The backtest framework needs a multi-config harness that runs each template against the same historical data and produces a single comparative report.

---

### I.11 Gaps and Overfitting Risks

#### Structural gaps

1. No strategy template data model (table, registry, matcher)
2. No multi-template evaluation per signal at generation time
3. No per-template outcome tracking
4. No MFE / MAE / realized R in results table
5. No displacement quality score (only boolean detection)
6. Backtest cannot compare tiers side by side in one run
7. Adaptive learning is global, not per-template

#### Overfitting risks

1. **Small sample sizes per tier** — if Tier A gets only 30 trades in backtest, any learned weights are noise, not signal
2. **Regime concentration** — if all Tier A signals occur in trending regimes and Tier B in ranging, the comparison is confounded
3. **Recency bias in OGD** — online learning over-adapts to recent regime shifts without a lookback window
4. **Template proliferation** — adding too many tiers fragments data; every tier looks different by chance
5. **Survivorship in backtest** — configs tuned on historical data will outperform live results
6. **Feedback contamination** — loose Tier C signals could pollute global feature weights and degrade Tier A performance

---

### I.12 Proposed Implementation Plan

#### Phase 1 — Database Schema Expansion (2 days)

Create `templates` table:
```sql
CREATE TABLE templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    created_at TEXT,
    active INTEGER DEFAULT 1
);
```

Create `signal_variant_matches` table:
```sql
CREATE TABLE signal_variant_matches (
    id INTEGER PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    template_id INTEGER REFERENCES templates(id),
    match_score REAL,
    confluences_matched_json TEXT
);
```

Add to `signals` table: `matched_template_id INTEGER`, `template_scores_json TEXT`

Add to `results` table: `mfe_pct REAL`, `mae_pct REAL`, `realized_r REAL`

---

#### Phase 2 — Template Registry and Signal Tagger (3–5 days)

Build a `strategy_templates.py` module with three initial templates:

**Tier A — Strict**
- Requires: HIGH mss_quality + (HIGH or MEDIUM) fvg_quality + SMT confirmed + session in {LONDON_KZ, NY_AM_KZ} + DR location = DISCOUNT (buy) or PREMIUM (sell)
- Minimum confluences: 4 of 5
- Entry: REACTION_CONFIRMED only
- Live trading: enabled after n ≥ 50

**Tier B — Balanced**
- Requires: MEDIUM+ mss_quality + any fvg_quality + session in {LONDON_KZ, NY_AM_KZ, ASIA_KZ}
- Minimum confluences: 3 of 5
- Entry: ZONE_TOUCH or REACTION_CONFIRMED
- Live trading: enabled after n ≥ 50

**Tier C — Exploratory**
- Requires: any mss_quality + any fvg_quality
- Minimum confluences: 2 of 5
- Entry: any
- Live trading: **disabled by default** — backtest and paper only until manually promoted

Build `evaluate_confluences_vs_templates(signal_features) -> List[TemplateMatch]` that:
1. Iterates all active templates
2. Scores each against the signal's confluence data
3. Returns a ranked match list
4. Tags the signal with the best-matched template

---

#### Phase 3 — Backtest Multi-Template Harness (3–5 days)

Extend [backtest.py](../backtest.py) to:
1. Accept a list of template configs
2. Run each template against the same historical signal set
3. Aggregate per tier: win rate, avg R, sample n, Sharpe ratio, max drawdown
4. Output a side-by-side comparison table
5. Require minimum n=50 per tier before reporting statistics (guard against small-sample noise)

---

#### Phase 4 — Per-Template Adaptive Learning (5–7 days)

Extend `AdaptiveWeightEngine` in [adaptive_engine.py](../adaptive_engine.py) to:
1. Maintain a separate OGD weight vector per template
2. Update template weights only on signals matched to that template
3. Expose `get_template_confidence_adjustment(template_id, signal_features)` for use in signal generation
4. Include template weight snapshots in the existing weight persistence file

**Overfitting safeguards:**
- Minimum 30 outcomes before per-template weights diverge from global defaults
- Weight bounds: no individual template weight can exceed 2× the global weight for that feature
- Automatic reset if template win rate drops below 40% over 20 consecutive signals

---

#### Phase 5 — Risk Management Layer (2–3 days)

1. Per-template daily exposure cap (e.g., Tier C max 0.5% daily risk)
2. Tier consistency validator: assert Tier A requirements are a strict superset of Tier B
3. Circuit breaker: pause template if rolling 10-signal win rate < threshold
4. Minimum sample gate: do not recommend config changes from < 30 outcomes

---

#### Phase 6 — Monitoring and Reporting (2–3 days)

1. Extend Telegram alerts to include tier tag on new signals (e.g., "Tier A Setup")
2. Weekly digest: per-tier win rate, sample n, avg R
3. Alert if any tier's win rate drops > 10 percentage points vs rolling baseline
4. Human-review gate: adaptive config recommendations are never applied automatically

---

### I.13 Safeguards Against Overfitting

| Safeguard | Mechanism |
|---|---|
| Minimum sample gate | No template stats reported or acted on until n ≥ 50 |
| Weight bounding | Per-template OGD weights capped at 2× global feature weight |
| Tier hierarchy validation | Assert A ⊇ B ⊇ C on every config load |
| Regime tagging | All results tagged with market regime to prevent regime-confounded comparisons |
| Paper-only for Tier C | Tier C signals never sent live until manually promoted |
| Circuit breaker | Template paused if 10-signal rolling WR < 35% |
| No live auto-tuning | Adaptive config recommendations are human-reviewed before activation |
| Holdout set in backtest | Reserve final 20% of historical data as holdout; tune on training set only |

---

### I.14 Summary Table — Current Readiness

| Capability | Status | Gap |
|---|---|---|
| ICT confluence detection | **Ready** | — |
| Per-signal confluence logging (12+ columns) | **Ready** | — |
| Signal tagging with strategy template | **Not present** | Phase 2 |
| Multi-template evaluation per signal | **Not present** | Phase 2 |
| Outcome → confluence linkage | **Partial** | MFE/MAE/realized R missing |
| Adaptive per-template ranking | **Not present** | Phase 4 |
| DB: confluences stored | **Ready** | — |
| DB: strategy_template column | **Not present** | Phase 1 |
| DB: MFE / MAE / realized R | **Not present** | Phase 1 |
| Config: confluence weights | **Partial** (OGD global only) | Phase 4 |
| Config: combination requirements | **Not present** | Phase 2 |
| Backtest: multi-template comparison | **Not present** | Phase 3 |
| Overfitting safeguards | **Not present** | Phase 5 |

**Estimated total implementation time: 17–25 days**

The safest delivery order is: Phase 1 → Phase 2 → Phase 3 → Phase 5 → Phase 4 → Phase 6.
Phase 3 (backtest validation) must precede Phase 4 (live adaptive learning) to confirm templates produce genuine edge before adapting them online.

---

*End of ICT Strategy Variant Learner investigation. No files were modified, created, deleted, or edited.*
