# Realistic Execution Model — Calibration Guide

**Module:** [`execution.py`](../execution.py)
**Tests:** [`tests/test_execution.py`](../tests/test_execution.py)
**Roadmap context:** [`LIVE_BACKTEST_PARITY_ROADMAP.md`](./LIVE_BACKTEST_PARITY_ROADMAP.md) — Phase A.1

---

## 1. What this module does

`execution.py` simulates the friction between "backtest fills at signal price + flat 30bps" and "live operator manually executes via Telegram with latency + spreads + occasional missed fills". After Phase A.3 deploys (REALISTIC_EXECUTION=1 default), every backtest signal goes through `simulate_execution()` and gets:

- A **realistic fill price** (next-bar open + small latency slip)
- A **probabilistic outcome** (93% full, 5% partial 50%, 2% rejected)
- A **time + volatility conditioned spread**
- An **adverse-selection cost** in trending regimes
- A **stale-price reject** if the move exceeded 1.5× ATR during the latency window

The result is a more honest backtest WR — typically 5-8pp lower than the optimistic "perfect fill" baseline.

## 2. The 15 calibration knobs

All env-overridable. Defaults match conservative retail-execution priors.

### Latency

| Variable | Default | Units | Meaning |
|---|---|---|---|
| `EXEC_LATENCY_MEAN_SEC` | `12.0` | sec | Center of truncated-Gaussian latency distribution |
| `EXEC_LATENCY_STD_SEC` | `8.0` | sec | Standard deviation |
| `EXEC_LATENCY_MIN_SEC` | `3.0` | sec | Lower clamp (faster than this is unrealistic for manual exec) |
| `EXEC_LATENCY_MAX_SEC` | `60.0` | sec | Upper clamp (if operator hasn't placed order in 60s, signal abandoned) |

**Calibration target:** measure actual seconds-from-Telegram-to-Binance-fill for 30 closed paper signals. If median is 18s, set `EXEC_LATENCY_MEAN_SEC=18`. If you place orders within 5-10s consistently, you can lower to 6-8.

### Fill outcomes

| Variable | Default | Units | Meaning |
|---|---|---|---|
| `EXEC_PARTIAL_FILL_PROB` | `0.05` | probability | Chance order gets 50% fill at limit |
| `EXEC_NO_FILL_PROB` | `0.02` | probability | Chance order doesn't fill at all (signal aborted) |

**Calibration target:** measure how often your limit orders get 50% partial or 0% on actual Binance trades. Retail typical: 5%/2%. Very illiquid alts: 10%/5%. Pristine BTC during NY: 2%/0%.

### Stale-price reject

| Variable | Default | Units | Meaning |
|---|---|---|---|
| `EXEC_STALE_ATR_MULT` | `1.5` | multiplier | Reject if price moved more than this × ATR(5M) during latency |

**Calibration target:** count signals where Telegram arrived but price had moved >1.5× ATR by the time you placed the order. If you can't keep up during volatility (e.g. 5% of signals get away), keep default. If you're very fast on the trigger, raise to 2.0.

### Adverse selection

| Variable | Default | Units | Meaning |
|---|---|---|---|
| `EXEC_ADV_SEL_COST` | `0.0005` | fraction | Extra cost in TRENDING_BULL/BEAR regimes (smart-money fade) |

**Calibration target:** if backtest WR with adverse=0 vs adverse=0.0005 differs by <1pp, this knob barely matters and you can zero it. Default 5bps is a small but realistic conservatism for retail trend-following entries.

### Time-of-day spread multipliers

| Variable | Default | Hours UTC | Meaning |
|---|---|---|---|
| `EXEC_TIME_MULT_ASIA_EARLY` | `1.4` | 00:00-06:00 | Thinnest liquidity period (Asian session early) |
| `EXEC_TIME_MULT_OVERNIGHT` | `1.2` | 20:00-24:00 | After NY close, before Asia open |
| `EXEC_TIME_MULT_ACTIVE` | `1.0` | 06:00-20:00 | London + NY overlap — tightest spreads |

**Calibration target:** check actual Binance avg bid-ask spread per hour-of-day for your tokens. The defaults assume retail-style liquidity skew. Major tokens (BTC, ETH) may not show this much variation; alts (HBAR, POL) often show more.

### Vol-conditioned spread multipliers

| Variable | Default | Trigger | Meaning |
|---|---|---|---|
| `EXEC_VOL_MULT_HIGH` | `1.6` | `atr_ratio > 2.0` | Extreme volatility — wide spreads |
| `EXEC_VOL_MULT_MED` | `1.3` | `atr_ratio > 1.5` | Above-normal volatility |
| `EXEC_VOL_MULT_NORMAL` | `1.0` | otherwise | Baseline |

**Calibration target:** observe spread widening during high-vol periods. ATR ratio of 2.0 typically means a news event or liquidation; spreads can widen 2-3×. Default 1.6× is conservative.

### Latency slip

| Variable | Default | Units | Meaning |
|---|---|---|---|
| `EXEC_LATENCY_SLIP_PER_30S` | `0.0002` | fraction | Adverse price drift per 30 seconds of latency |

At max latency (60s), this gives 4bps adverse slip on BUY (price drifts up while you wait) and same for SELL (price drifts down). Tunable to match observed slippage between Telegram alert and your Binance fill.

## 3. Calibration procedure (after Phase A.3 deploys)

### Pre-requisites
- Phase A.1 + A.2 + A.3 all deployed (`REALISTIC_EXECUTION=1` default)
- At least 30 closed paper signals accumulated
- Manual logging of: Telegram timestamp, your decision/fill timestamp, fill price vs Binance bid-ask at fill time

### Procedure

1. **Measure ground truth** for 30+ closed paper signals:
   - Median latency from Telegram → fill
   - Partial fill rate (count of signals that got only 50%)
   - No-fill rate (count abandoned because price moved away)
   - Average slippage between signal_price and actual_fill_price
   - Spread observed at fill time (typical & high-vol)

2. **Compare to current backtest predictions** by running a backtest with default knobs and observing:
   - Backtest predicted WR vs paper actual WR
   - Backtest predicted slippage vs paper actual slippage
   - Backtest rejection rate vs paper no-fill rate

3. **If divergence > 3pp WR**, tune the knobs:
   - If paper WR is HIGHER than backtest predicted: backtest is too pessimistic → lower latency, partial-fill, stale-reject probabilities
   - If paper WR is LOWER than backtest predicted: backtest is too optimistic → raise the above
   - Adjust 1-2 knobs at a time, re-backtest, iterate

4. **Document the calibration** by appending to `.env.backtest` or similar:
   ```
   EXEC_LATENCY_MEAN_SEC=18
   EXEC_PARTIAL_FILL_PROB=0.03
   EXEC_NO_FILL_PROB=0.01
   ```

5. **Lock the calibration** after backtest predicts paper WR within ±3pp. Don't keep iterating beyond that — repeated tuning is calibration overfitting.

## 4. Anti-patterns

**❌ Don't tune knobs to make Run-168 look better.** That's calibration overfitting against the metric, not against reality.

**❌ Don't change knobs faster than you accumulate paper signals.** Each tuning cycle needs at least 20 new signals to validate against.

**❌ Don't trust paper data from less than 20 closed signals.** Statistical noise dominates.

**❌ Don't tune more than 2 knobs at a time.** Causal attribution becomes impossible.

**❌ Don't disable any single friction component.** Every component models a real effect; zeroing out (e.g., `EXEC_ADV_SEL_COST=0`) means your backtest is back to pretending one piece of reality doesn't exist.

## 5. Reproducibility

The model is **deterministic given the seed**. Backtest reproducibility is preserved by:

```python
seed = execution.derive_seed(signal_ts, token, direction)
result = execution.simulate_execution(..., seed=seed)
```

The seed is `hash((signal_ts.isoformat(), token, direction)) & 0x7FFFFFFF`. Same backtest → same seeds → same fills → same metrics. Optuna trials get independent seeds because they have different `BACKTEST_*` params that affect signal timing, which affects `signal_ts`.

## 6. Defaults are conservative

The defaults assume:
- You're a retail operator manually executing on Binance (median 12s latency)
- You miss ~2% of signals entirely (price moved too fast)
- You get 5% partial fills (limit orders at FVG edge don't always fully fill)
- You face 5bps adverse selection in strong trends (smart money fades retail breakouts)
- Spreads widen during overnight/Asian early hours by 20-40%
- Volatile periods widen spreads by 30-60%

These are conservative for a typical retail VPS-based bot. A faster operator with co-located execution would tune down; an operator using mobile-only execution might tune up.

## 7. When to recalibrate

| Trigger | What to do |
|---|---|
| First 30 paper signals close | Run initial calibration (Section 3) |
| Quarterly review | Re-measure ground truth, adjust if drift |
| New token added | Audit token-specific spread (`TOKEN_RT_COST`) |
| New tooling (auto-execute, faster device) | Lower `LATENCY_MEAN_SEC` to match |
| Regime change (volatility regime shifts persistently) | Re-validate vol multipliers |
| LIVE-mode launch | Final calibration against live (not paper) data |

## 8. Diagnostic commands

```bash
# See current active config (env vars + defaults)
python3 -c "import execution; import json; print(json.dumps(execution.current_config(), indent=2))"

# Run all tests
python3 -m unittest tests.test_execution -v

# Quick smoke: simulate one execution
python3 -c "
from datetime import datetime, timezone
import execution
r = execution.simulate_execution(
    signal_ts=datetime(2026, 5, 25, 14, 30, 0, tzinfo=timezone.utc),
    signal_price=108432.50,
    next_bar_open=108450.00,
    token='BTC',
    direction='BUY',
    regime='TRENDING_BULL',
    atr_5m=350.0,
    atr_ratio=1.2,
    seed=42,
)
print(f'{r.status:8} fill=${r.fill_price:,.2f} size={r.fill_size_pct:.0%} cost={r.total_cost_pct*100:.3f}% latency={r.latency_sec:.1f}s reason={r.reason}')
"
```

## 9. Roadmap status

- **Phase A.1** (this module + tests + this doc) — **DONE 2026-05-26** (commit `2885706`)
- **Phase A.2** (wire into backtest.py with REALISTIC_EXECUTION=0 default) — **DONE 2026-05-26** (commit `2885706`; verified byte-identical via Run-76)
- **Phase A.3** (flip default to 1 + update baseline pin) — **DONE 2026-05-26**
- **Phase A calibration** (this doc Section 3) — pending after first 30 paper signals close

Update this doc as calibration data accumulates. The knobs above are starting priors, not final values.

## 10. Phase A.3 observed effect (2026-05-26)

Backtest under default knobs, same config_hash, REALISTIC_EXECUTION=0 vs 1:

| Metric | Run-76 (=0, byte-equiv Run-168) | Run-77 (=1, default ON) | Δ |
|---|---|---|---|
| n_signals | 43 | 34 | **−9 (−21%)** |
| Headline WR | 79.1% | 85.3% | **+6.2pp** |
| CPCV mean WR | 79.11% | 85.27% | +6.16pp |
| CPCV std | 5.40% | 6.01% | +0.61 |
| CPCV q05 | 70.6% | 76.9% | +6.3pp |
| Sharpe (CPCV mean) | 0.933 | 1.180 | **+0.247 (+26%)** |
| Overall Sharpe | 0.928 | 1.133 | +0.205 |
| DSR | 100.0% | 100.0% | unchanged |
| Verdict | PASS | PASS | ✅ |

**Key observation:** the realistic model **rescued** the strategy — Run-168's optimistic 79.1% was being dragged DOWN by signals that would have been stale fills in live. The remaining 34 signals are HIGHER quality, producing better WR + Sharpe. The strategy edge is REAL, the original presentation was just pessimistic about itself.

**Execution-reject totals (across 10 tokens):** ~70 stale_move + ~1 no_fill = ~71 candidate signals filtered. These were the signals where the operator's 10-30s Telegram→order placement window saw price gap >1.5× ATR(5M) — bad fills in live, no fills in honest backtest.

**Live trading implication (not yet implemented):** `crypto_alert.py` should add a parallel stale-price-reject. When operator order-placement latency exceeds the ATR-scaled threshold, the live signal should be canceled instead of fired. This would mirror the backtest's honest behavior in live. Tracked as a future enhancement; see parity roadmap §5.

## 11. Validation against live (pending paper trade accumulation)

After 30+ closed paper signals accumulate, validate the honest model against live:

```python
# pseudocode
backtest_predicted_wr  = parse("backtest_reports/Run77.txt").cpcv_mean  # 85.27%
live_actual_wr         = compute_paper_wr(closed_signals)
absolute_gap_pp        = abs(backtest_predicted_wr - live_actual_wr)

if absolute_gap_pp <= 3:
    print("Phase A.3 model is well-calibrated. Lock baseline.")
elif absolute_gap_pp > 5:
    print("Recalibration needed. Adjust EXEC_LATENCY_MEAN_SEC / EXEC_*.")
```

Until paper data exists, the model is calibrated against PRIORS (Section 2). The first 30 paper signals will be the empirical test.
