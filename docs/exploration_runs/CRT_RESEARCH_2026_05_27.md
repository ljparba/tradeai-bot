# Candle Range Theory (CRT) — Research Notes + Implementation Spec

**Date:** 2026-05-27
**Status:** Research / planning document — NO code change yet
**Owner decision:** H4 reference candle + 5M entry timeframe, tested on ALL 10 tokens (not just BTC+ETH)
**Implementation gate:** Wait until current autonomous explorer session finishes before starting CRT engine work

---

## 1. Purpose of This Document

Consolidates the research from web search + the Trading Wyckoff long-form
article (Rubén Villahermosa, 50-min read) into an opinionated specification
for an EXPERIMENTAL parallel signal source: H4-CRT detection feeding the
existing 5M entry pipeline.

The TradeAI bot's current 5M sweep model (Run-81 baseline, DSR=98.7%) is
NOT being replaced. CRT will be added as an additional signal source,
tagged separately in the DB for independent performance attribution,
behind an env-flag default OFF.

This document is the canonical reference for what CRT actually is,
which sources agree, where the schools diverge, and what design
decisions TradeAI made and why.

---

## 2. What CRT Is (One-Paragraph Summary)

Candle Range Theory (CRT) treats every higher-timeframe candle as a price
range, then trades the liquidity raid of that range when price closes back
inside. Each higher-timeframe candle contains a mini Accumulation-
Manipulation-Distribution (AMD) cycle: the candle's body is accumulation,
a wick beyond one extreme is manipulation (sweep), and the subsequent
reversal toward the opposite extreme is distribution. CRT is the
community-systematized intersection of Richard Wyckoff's Spring/Upthrust
(1930s), Linda Raschke's Turtle Soup (1990s, "Street Smarts"), and
Michael Huddleston's ICT Liquidity Sweep / Power of 3 (2010s).

---

## 3. The Universal 3-Candle Rule (All Sources Agree)

```
Candle 1 (parent / reference): establishes the range (high + low = liquidity targets)
Candle 2 (manipulation):       wicks beyond one extreme, sweeps stops
Candle 3 (confirmation):       closes back inside C1's range — entry trigger
```

**Bullish CRT:** C2 wicks below C1.low → C3 closes inside C1 range → BUY signal
**Bearish CRT:** C2 wicks above C1.high → C3 closes inside C1 range → SELL signal

The minimum candle count is 3. Some flexible interpretations allow extra
"inside bars" during accumulation (multiple candles inside C1's range
before manipulation fires), but the C1-sweep-confirmation structure is
inviolate.

---

## 4. Authoritative Sources

### Tier 1 — Comprehensive + honest

1. **Trading Wyckoff (Rubén Villahermosa)** — https://tradingwyckoff.com/en/crt/
   50-minute read. Wyckoff-grounded interpretation. Honest WR stats, common
   mistakes section, 20-year gold backtest. Most rigorous public source.

2. **Inner Circle Trader official** — https://innercircletrader.net/tutorials/candle-range-theory-crt/
   ICT's canonical site. Authoritative on underlying ICT concepts (Power of 3,
   Liquidity Sweep, AMD).

### Tier 2 — Structured educational guides

3. **TradingFinder** — https://tradingfinder.com/education/forex/ict-candle-range-theory/
4. **CRT Trading (crttrading.com)** — https://www.crttrading.com/ (free PDF guide)
5. **TraderFactor** — https://traderfactor.com/what-is-the-candle-range-theory-strategy/
6. **Crypoptionhub (crypto-specific)** — https://crypoptionhub.com/candle-range-theory/

### Tier 3 — Reference implementations (Pine Script, study-able)

7. **CRT Marker (Joel-James)** — https://www.tradingview.com/script/gUxrLRJG-CRT-Marker-Candle-Range-Theory-Detection/
   Cleanest open-source reference. Pine v6. Best candidate for porting to Python.
8. **CRT MTF Model (RAJATAMIL)** — https://www.tradingview.com/script/dAPHgT5k-CRT-MTF-Candle-Range-Theory-Model/
   Multi-timeframe variant.
9. **CRT + CISD (Algo1493)** — https://www.tradingview.com/script/4hsHUzMV/
   Adds Change-in-State-of-Delivery confirmation layer.
10. **Candle Range Trading with Alerts (marcostan93)** — https://www.tradingview.com/script/7ypbzgUM-Candle-Range-Trading-CRT-with-Alerts/
11. **CRT | Turtle Soup (Algoryze)** — https://www.tradingview.com/script/eI0VWQLu/
    Explicit ICT/Turtle Soup linkage.

### Tier 4 — ICT foundation (background reading)

12. **ICT Power of 3 explained** — https://innercircletrader.net/tutorials/ict-power-of-3/
13. **ICT Power of 3 (FluxCharts)** — https://www.fluxcharts.com/articles/trading-strategies/ict-strategies/ict-power-of-three
14. **4H CRT (1AM and 5AM) indicator** — https://www.tradingview.com/script/kXR0vkG2-4H-CRT-1AM-and-5AM/
    Demonstrates the 4H CRT model specifically.

---

## 5. Areas of Agreement Across Sources

### Stop loss placement — 100% consistent
Always below the sweep wick (C2 low for bullish, C2 high for bearish).
Never tighter (gets stopped on micro-noise), never wider (R:R collapses).

### Take profit placement — 100% consistent
Opposite extreme of C1's range (the unswept side). Extensions allowed
only when HTF context supports continuation.

### Mitigation rule — 100% consistent
Each CRT zone is valid only ONCE. After price reaches the opposite
extreme, the range is "mitigated" and dead. Don't look for second chances
in the same zone.

### Crypto-specific guidance — 4+ sources agree
- Higher timeframes (H4, D1) work better than lower (M5, M1)
- Wider stops required (crypto sweeps go deeper)
- Daily Bias filter mandatory
- Article author qualifies: "Only for experienced traders"
- Some sources say "BTC + ETH only" — TradeAI overrides this (see §8)

### Win rate calibration (Trading Wyckoff honest stats)

| Setup quality | Realistic WR | Avg R:R |
|---|---|---|
| Raw CRT (no filters) | 45-50% | 1.5-2R |
| + HTF trend filter | 50-58% | 2-2.5R |
| + Wyckoff phase context | 55-62% | 2-3R |
| + Wyckoff + killzone + key level | 60-65% | 2.5-3R |

### Killzone bias — sources agree
London Open (08:00-09:00 CET), NY Open (14:30-15:30 CET), London Close
(17:00-18:00 CET) are highest-probability windows. Asian session is
range-formation, lower probability for CRT entries.

---

## 6. Areas of Divergence (Schools of Interpretation)

### Validation school — TWO legitimate camps

| School | Rule for C2 close | Confirmation source |
|---|---|---|
| Strict | C2 BODY must close inside C1's range; otherwise = legitimate breakout, no setup | C2 close itself + C3 re-entry |
| Flexible (Wyckoff/ICT) | C2 close position doesn't matter; what matters is C3 (or later) confirming control change | C3 close beyond swept level OR LTF MSS |

**The flexible school explicitly accepts LTF MSS confirmation** — directly
maps to TradeAI's existing `detect_ict_mss()` function. This is a major
implementation simplification.

### Entry mode

| Mode | Trigger | Trade-off |
|---|---|---|
| Aggressive | Buy/Sell Stop above/below C2 high/low | Better entry price, more false fills |
| Conservative | Buy/Sell Stop above/below C3 high/low | Worse entry price, fewer false fills, higher WR |

### Number of inside bars allowed in C1 phase

| Interpretation | Rule |
|---|---|
| Strict | Exactly 3 candles (C1, C2, C3); no inside bars between them |
| Flexible | Additional inside bars allowed during accumulation; manipulation candle is "C2" by role, not position |

### Confluence requirements

| Source | Required confluences |
|---|---|
| Joel-James indicator | None (raw CRT detection only) |
| Trading Wyckoff | Daily Bias filter + Order Block OR FVG overlap |
| CRT + CISD (Algo1493) | Adds CISD (Change in State of Delivery) on entry TF |
| TradeAI design (below) | 4H bias (existing) + FVG overlap (existing) + 5M MSS (existing) |

### Killzone applicability for crypto

| Source | Crypto killzone position |
|---|---|
| Trading Wyckoff | Apply same forex killzones (London/NY) since US institutional flows dominate crypto |
| Crypto-specific guides | Crypto is 24/7; some pivot times: Asia post-09:00 UTC, US open ~13:00 UTC |
| TradeAI design | Reuse existing NY AM / London / Asia gates — proven calibration |

---

## 7. TradeAI's Opinionated CRT Specification

Combines the best of all sources, leverages existing TradeAI infrastructure
to minimize new surface area, and reflects operator decisions (H4 reference,
5M entry, all 10 tokens).

| Spec dimension | Decision | Rationale |
|---|---|---|
| **Reference timeframe** | H4 | Per crypto guidance from multiple sources. Aligns with article's "4H CRT Model" specifically. Avoids M1/M5 noise. |
| **Entry timeframe** | 5M | Existing infrastructure. Precision entry refinement after H4 CRT confirmed. |
| **Validation school** | FLEXIBLE (Wyckoff) | Allows reuse of `ict_engine.detect_ict_mss()` as confirmation. Major simplification. |
| **Entry mode** | CONSERVATIVE | Wait for 5M MSS, not just C2 wick. Matches TradeAI's existing risk discipline. |
| **Stop placement** | Below C2 wick (sweep low/high) | 100% consensus across sources. |
| **Take profit (TP1)** | Opposite extreme of C1 range | Universal rule. |
| **Take profit (TP2/TP3)** | Use existing trade plan logic (`ict_engine.compute_ict_trade_plan`) | Reuse rather than reinvent. |
| **Mitigation** | One-shot per zone | Reuse existing `consumed_sweeps_abs` pattern. |
| **HTF filter** | Existing 4H bias gate (`LIVE_BIAS_4H_GATE`) as "Daily Bias proxy" | The 4H bias already approximates "is the market currently bullish/bearish at the macro?" |
| **Confluence required** | FVG overlap with C1 range OR with MSS bar | Reuse existing FVG quality scoring. |
| **Tokens** | All 10 (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON) | Operator decision: TradeAI's Run-81 already validated 10-token portfolio empirically. Article's "BTC+ETH only" is conservative default for forex traders adopting CRT; we have empirical evidence smaller caps work for ICT-style logic in our setup. See §8 below. |
| **Killzones** | Reuse existing NY AM / London / Asia gates | Proven calibration. |
| **Daily cap** | Same as existing template tiers | Tier classification still applies. |
| **Risk per trade** | Same 1% (no change) | Risk management unchanged. |

---

## 8. Token Coverage Decision (Operator Override)

### What the source recommends
> "Trade only BTC and ETH (highest liquidity)" — Trading Wyckoff,
> Crypoptionhub, and other crypto-CRT guides.

### Why TradeAI overrides this

1. **Empirical evidence from Run-81 baseline** — DSR=98.7%, CPCV mean WR
   70.0%, validated across 10-token portfolio. The bot's existing
   5M sweep + MSS + FVG model successfully extracts edge from POL,
   HBAR, TON, ADA despite their smaller market cap.

2. **ICT logic transfers across crypto pairs** — TradeAI has empirical
   counter-evidence that ICT-style detection works on lower-cap pairs.
   The article's caveat reflects forex-trader conservatism, not a
   universal physical limit.

3. **Selection-by-attribution is safer than upfront exclusion** —
   tagging each CRT signal by token lets us measure per-token WR after
   backtest. If POL/HBAR/TON CRT signals turn out to be noise (WR < 50%),
   we can selectively disable per token via env flag without disabling
   the whole CRT path.

4. **Pareto archive growth** — running on 10 tokens gives 5× the per-run
   signal count vs. BTC+ETH only. Faster statistical convergence on
   per-token WR estimates.

5. **Cost of exclusion is symmetric** — if 8 of 10 tokens produce no
   useful CRT signals, the backtest will show n≈0 for those tokens
   and operator can disable them. The cost of testing them once is
   one extra backtest cycle. The cost of NOT testing them is missed
   edge that we'd never know about.

### Risk mitigation for the broader token set

- Tag every CRT signal with `source='H4_CRT'` AND record `token` in
  the existing signals table. Per-token WR is queryable from day 1.
- Add an env-driven token blacklist: `H4_CRT_DISABLED_TOKENS=POL,HBAR`
  — operator can selectively disable underperformers without code
  change.
- Apply existing template Tier circuit breaker logic to CRT signals
  (rolling WR < 55% over 20 signals → pause that template for that
  token).
- Start in PAPER mode only. LIVE clearance for H4-CRT is a separate
  decision after independent paper-trade accumulation.

---

## 9. Pseudocode Map to Existing TradeAI Modules

```python
# New file: crt_engine.py (alongside ict_engine.py — does NOT modify ict_engine)

from ict_engine import detect_ict_mss, find_ict_fvg  # reuse confirmation

def detect_h4_crt(c4h, c5m, c1h, consumed=None):
    """
    Detect H4 Candle Range Theory setups with 5M MSS confirmation.
    
    Args:
        c4h: dict with 'opens', 'highs', 'lows', 'closes', 'times' (last ~30 H4 bars)
        c5m: dict same shape (~300 5M bars within the recent H4 window)
        c1h: dict same shape (~50 1H bars — for future use, currently unused)
        consumed: set of mitigated C1 ranges (tuple of (c1_idx, round(c1.high,6), round(c1.low,6)))
    
    Returns:
        dict with 'type' (BSL_CRT / SSL_CRT), 'c1_high', 'c1_low', 'sweep_wick',
        'sweep_bar_5m', 'mss_bar_5m', 'cluster_size', etc.
        OR None if no valid CRT setup detected.
    """
    if consumed is None:
        consumed = set()
    
    # Walk backward through H4 candles looking for sweep (C2) of prior C1's extreme
    n_h4 = len(c4h['closes'])
    for c2_idx in range(n_h4 - 1, max(0, n_h4 - 10), -1):  # last 10 H4 bars
        # The candle BEFORE c2 is C1 (parent / reference)
        c1_idx = c2_idx - 1
        if c1_idx < 0:
            continue
        c1_high = c4h['highs'][c1_idx]
        c1_low  = c4h['lows'][c1_idx]
        c2_high = c4h['highs'][c2_idx]
        c2_low  = c4h['lows'][c2_idx]
        c2_close = c4h['closes'][c2_idx]
        c2_time  = c4h['times'][c2_idx]
        
        # Mitigation check — has this C1 range been used?
        key = (c1_idx, round(c1_high, 6), round(c1_low, 6))
        if key in consumed:
            continue
        
        # BULLISH CRT — C2 wicked BELOW C1.low + (flexible: close inside OR LTF MSS confirms)
        if c2_low < c1_low and c2_close > c1_low:  # C2 wicked below + closed back inside
            # Flexible school: confirm via 5M MSS within window after c2_time
            # Find 5M bar index corresponding to c2_time + 1 bar (start of "after sweep" window)
            sweep_5m_idx = _find_5m_bar_after(c5m, c2_time)
            if sweep_5m_idx is None:
                continue
            mss_result = detect_ict_mss(
                sweep_bar=sweep_5m_idx,
                closes=c5m['closes'],
                sh=_compute_5m_swings_after(c5m, sweep_5m_idx),
                sl=_compute_5m_swings_after(c5m, sweep_5m_idx),
                sweep_type='SSL',
                horizon=ICT_MSS_HORIZON,  # 30 bars
            )
            if mss_result is None:
                continue
            # FVG overlap requirement
            fvg = find_ict_fvg(c5m, mss_result['mss_bar'], 'BUY')
            if fvg is None or fvg['quality'] != 'HIGH':
                continue
            return {
                'type': 'SSL_CRT',
                'direction': 'BUY',
                'c1_idx': c1_idx,
                'c1_high': c1_high,
                'c1_low': c1_low,
                'c2_wick': c2_low,
                'c2_time': c2_time,
                'mss_bar_5m': mss_result['mss_bar'],
                'fvg': fvg,
                'tp1': c1_high,  # opposite extreme
                'sl': c2_low,     # below sweep wick
            }
        
        # BEARISH CRT — symmetric
        if c2_high > c1_high and c2_close < c1_high:
            # ... symmetric to bullish, BSL_CRT, SELL direction
            pass
    
    return None
```

### Integration points

```python
# crypto_alert.py (scan_token function — add parallel CRT path)
if ENABLE_H4_CRT:
    crt_signal = detect_h4_crt(c4h, c5m, c1h, consumed=_crt_consumed[token])
    if crt_signal:
        # Apply existing 4H bias gate (Daily Bias proxy)
        if _bias_aligned(crt_signal['direction'], bias_4h):
            # Apply existing killzone check
            if in_killzone(now):
                # Apply existing template tier classification + OGD scoring
                # Tag source='H4_CRT' in DB write
                emit_signal(crt_signal, source='H4_CRT')

# backtest.py — same pattern, parallel scan path
# Tag rows with source='H4_CRT' so per-source aggregation works in tracker
```

### Schema migration

```sql
-- Add to signals and backtest_signals tables
ALTER TABLE signals ADD COLUMN source TEXT DEFAULT '5M_SWEEP';
ALTER TABLE backtest_signals ADD COLUMN source TEXT DEFAULT '5M_SWEEP';

-- Per-source aggregation query
SELECT source, token, COUNT(*) AS n, AVG(canonical_wr) AS wr_pct
FROM (-- joined signals+results query --)
GROUP BY source, token;
```

### Env toggles

```bash
# Default OFF — opt-in only after backtest validates
ENABLE_H4_CRT=0

# Per-token exclusion (comma-separated) — operator can disable underperformers
H4_CRT_DISABLED_TOKENS=

# Optional: relax mitigation (allow multi-touch per H4 range)
H4_CRT_MITIGATION_STRICT=1
```

---

## 10. Validation Pipeline (Pre-Production Gates)

CRT must pass the same honest-metrics pipeline as the main bot before any
production decision:

1. **Initial backtest** — H4_CRT signals on 365 days, ALL 10 tokens. Goal:
   establish baseline n per token + aggregate WR + DSR.
2. **CPCV verdict** — must produce PASS verdict. If MARGINAL, document and
   continue; if FAIL, do not ship.
3. **DSR check** — honest cross-config sr_trial_std. CRT signals are a
   separate config (different config_hash) so they enter the DSR n_trials
   pool as one additional trial.
4. **Per-token attribution** — measure WR per token. Disable tokens with
   WR < 50% over n ≥ 20 via env blacklist.
5. **Walk-forward validation** — 60/40 train/test split. WR gap must be
   < 15pp (overfitting threshold from existing TuneBot logic).
6. **Paper trading** — minimum 10 closed paper signals per token before
   LIVE consideration for CRT path. Separate from main bot's 30-signal gate.
7. **LIVE clearance for CRT** — independent decision after paper data
   accumulates. Operator-only.

---

## 11. Expected Frequency Estimate

H4 candle = 6 candles per day per token. Across 10 tokens, 60 H4 candles
per day are "candidates" for the C2 sweep position. Empirical CRT
literature suggests roughly 10-20% of H4 candles produce valid CRT
setups (sweep + reversal confirmed).

| Scenario | H4 candles/day | CRT hit rate | Daily setups | Per year |
|---|---|---|---|---|
| Conservative (10%) | 60 | 10% | 6 | ~2,200 |
| Realistic (15%) | 60 | 15% | 9 | ~3,300 |
| With confluences (5%) | 60 | 5% | 3 | ~1,100 |

After 4H bias + killzone + FVG quality filters, expect ~20-40% of raw
setups to survive. Final estimate: **200-800 H4-CRT signals per year**
across the full 10-token portfolio.

This is 5-20× the current 5M sweep model's ~35 signals/year, dramatically
accelerating the 30-paper-close LIVE-clearance gate IF WR holds.

Risk: high signal count at low WR (45-50% raw) could net out negative
after fees. Validation pipeline above is designed to catch this before
production.

---

## 12. Implementation Effort Estimate

| Task | Hours |
|---|---|
| `crt_engine.py` — H4 detection + flexible C3/MSS validation | 4-6 |
| Schema migration (`source` column + backfill default) | 1 |
| `backtest.py` integration (parallel scan path + tag) | 2 |
| `crypto_alert.py` integration | 2 |
| Per-token blacklist env handling | 1 |
| Test suite — 6-10 unit tests for CRT detection | 3 |
| Initial backtest run + per-token analysis | 1-2 |
| Documentation update (CLAUDE.md, README.md, ADAPTIVE_LEARNING.md) | 1 |
| **Total** | **15-18 hours** |

---

## 13. Pre-Requisites Before Implementation

1. Current autonomous explorer session must finish (~14 hours from start)
2. Explorer findings reviewed — if it finds higher-frequency configs via
   parameter tuning alone, CRT may become lower priority
3. Operator approval to proceed
4. Feature branch (`experiment/crt-h4-signal-source`) created
5. No other concurrent code changes to signal-generation files

---

## 14. What This Document Does NOT Authorize

- ANY code change to `ict_engine.py` or other existing detection modules
- ANY modification to the Run-81 baseline
- LIVE clearance for CRT signals (separate operator decision after
  independent paper-trade accumulation)
- Disabling the main 5M sweep model (CRT is additive, not replacement)
- Promoting CRT-only configs via the autonomous explorer auto-promote
  path (initial CRT validation is operator-driven via manual backtest)

---

## 15. Open Questions for Implementation Time

1. **H4 candle alignment** — Binance uses 00:00 UTC as the H4 boundary
   (00/04/08/12/16/20). The article's "4H CRT Model" uses NY-aligned
   1am/5am EST. Decision: should TradeAI use UTC-aligned H4 (matches
   existing data fetch) or remap to NY-aligned? Default: UTC-aligned
   (simpler), revisit if backtest shows session-time sensitivity.

2. **FVG confluence strictness** — Should FVG be REQUIRED for every CRT
   signal, or just a confidence booster? Default: REQUIRED (matches
   TradeAI's existing high-quality filter discipline), but worth A/B
   testing later.

3. **Mitigation persistence** — Should mitigated C1 ranges survive bot
   restart? Default: YES (persist consumed set to bot_state), to prevent
   re-trading same range across cycles.

4. **OGD weight isolation for CRT** — Should CRT signals use separate
   per-token weights from 5M-sweep signals? Default: SHARED (single
   OGD weight per token across all signal sources) initially; revisit if
   CRT shows clearly different feature importance.

5. **Trade plan adaptation** — `compute_ict_trade_plan()` was tuned for
   5M sweep entries. For H4 CRT entries (wider stops, larger targets),
   the RR calculations may need separate parameters. Default: reuse
   existing logic, document any anomalies, tune in v2.

---

## 16. Document History

- **2026-05-27** — Created. Research consolidated from Trading Wyckoff
  long-form article + 4 web searches across ICT/CRT topic space. Operator
  spec confirmed: H4 reference, 5M entry, all 10 tokens (override of
  BTC+ETH-only conservative default with empirical justification from
  Run-81 baseline performance).
