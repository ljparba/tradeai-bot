# TF-comparison pre-registration (LOCKED before any backtest run)

## Configurations

| ID | Entry TF | Reference TF | Notes |
|---|---|---|---|
| **A** | 5M | 4H | Current validated config (matches Config 14) |
| **B** | 5M | 1H | Same entry, shorter reference |
| **C** | 1M | 1H | Finer entry, same reference as B |

## Constant knobs (held identical across A/B/C — Config 14 fingerprint)

```
H4_BREAKOUT_CLOSE_BUFFER_PCT     = 0.001
BREAKOUT_TP1_RR                  = 2.0
BREAKOUT_TP2_RR                  = 3.0
BREAKOUT_TP3_RR                  = 4.0
H4_BREAKOUT_OB_SCAN_LOOKBACK     = 20 (reference-TF bars)
H4_BREAKOUT_FVG_PROBE_WIDTH      = 3  (entry-TF bars)
BREAKOUT_SL_INSIDE_BUFFER_PCT    = 0.001
ICT_MIN_RR_GATE                  = 1.3 (from config.py)
MAX_BREAKEVEN_WR                 = 0.60 (from config.py)
MIN_SL_PCT / MAX_SL_PCT          = 0.005 / 0.030
```

## TF-scaling rule (LOCKED — affects fairness)

The engine has two knobs that depend on bar count:
`H4_BREAKOUT_C2_LOOKBACK` (reference bars back for C1 candidate) and
`H4_BREAKOUT_MSS_HORIZON` (entry bars for continuation MSS).

I keep BOTH at the same bar-count value across configs (4 / 30 respectively).
This means the wall-clock window DIFFERS per config:

| | Ref bar size | C2 lookback wall-clock | Entry bar size | MSS horizon wall-clock |
|---|---|---|---|---|
| **A** | 4 hours | 4 bars × 4h = **16 hours** | 5 min | 30 bars × 5m = **150 min** |
| **B** | 1 hour | 4 bars × 1h = **4 hours** | 5 min | 30 bars × 5m = **150 min** |
| **C** | 1 hour | 4 bars × 1h = **4 hours** | 1 min | 30 bars × 1m = **30 min** |

### Why "same bar count" rather than "same wall-clock"?

Either choice is defensible. I lock SAME BAR COUNT because:
1. The engine's structural intent is "look at the last N reference candles for a C1 candidate" — that's a count, not a clock.
2. Scaling MSS horizon to wall-clock at 1M means searching 150 bars after a sweep — that's 50× more candidates than at 5M and would inflate signal count artificially.
3. Same bar count keeps the engine's selectivity comparable across TFs; the wall-clock difference is the natural property of the TF choice.

This MUST be documented in the report so the operator knows configs C and B test a SHORTER wall-clock window than A.

## Universe (LOCKED)

12 tokens, same as soak: `BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON, ATOM, BCH`.

## Data span (LOCKED)

**90 days ending 2026-05-31** (the cache freeze date).
- Window: 2026-03-02 → 2026-05-31 UTC
- Reason: 1M data over 365d would be ~6 million bars (~500 MB). 90 days is tractable and gives ~3000-5000 1M signals per config which is statistically meaningful.
- All three configs use the SAME 90-day window for fair comparison.
- Note: this is a SHORTER span than the 365-day grid that originally validated A — flagged in report.

## Metrics (pre-registered)

Run ALL three configs ONCE, frictionless. Then ALL three again with `execution.simulate_execution`. Report ALL 6 results regardless of outcome.

For each (config, friction-mode):

- n signals attempted / filled (friction-mode)
- WR strict ((WIN + PARTIAL_TP2) / n)
- avg_R per traded signal
- sum_R
- profit factor
- max drawdown (R) over the period
- CPCV (n_groups=10, n_test=2, embargo=1%) — wr_mean / wr_std / wr_q05 / verdict
- PSR vs SR=0 (per-trade Sharpe)
- DSR deflated by `n_trials = 3` (the 3 clean configs are 3 distinct trials)
- temporal 70/30 train→test split (avg_R delta)
- walk-forward by calendar **month** (90 days = 3 months max)
- per-token (n, WR, avg_R, sum_R, blowup flag)

## Friction-sensitivity diagnostic

For each config (A, B, C) report:
- avg_R clean → avg_R friction-on → % degradation
- 1M is EXPECTED to lose more to friction; report by how much

## DB persistence

All 6 runs land in `/home/tradeai/breakout-work/data/breakout.db`:
- `backtest_runs` row per config-mode combo, summary JSON has TF + friction tags
- `backtest_signals` rows per signal, source = `H4_BREAKOUT_TF_{A,B,C}_{CLEAN,FRICTION}`

## Reporting discipline

- Pre-registered metrics — no late additions
- Lead with EXPECTANCY (avg_R, PF, sum_R) — not WR
- WR shown but secondary
- One side-by-side table for the headline
- Plain finding: state which config has the strongest HONEST edge, OR that A remains best, OR that the data is ambiguous
- DO NOT recommend changing the live soak. Any switch would require its own fresh forward soak.

## Hash

`pre_register_hash` = sha256 of the above text minus this line, computed for auditability.
