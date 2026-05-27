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

## 7. TradeAI's Opinionated CRT Specification (Phased: v1 → v2)

Honest-research correction (2026-05-27, operator review):
The original spec had three decisions framed as "convenient for TradeAI"
rather than "what the best research actually advocates." Operator
directive: follow research-best, accept the additional implementation
cost. Spec below is the revised, honestly-research-grounded version.

The spec is split into v1 (initial implementation, 55-62% WR ceiling)
and v2 (enhancements that reach the article's reported 60-65% ceiling).
v2 only starts after v1 backtest validates the foundation.

### Common (v1 + v2)

| Spec dimension | Decision | Source / Rationale |
|---|---|---|
| **Reference timeframe** | H4 | Per crypto guidance across 4+ sources. Aligns with article's "4H CRT Model" specifically. Avoids M1/M5 noise. |
| **Entry timeframe** | 5M | Existing TradeAI infrastructure. Precision entry refinement after H4 CRT confirmed. |
| **Stop placement** | Below C2 wick (sweep low/high) | 100% consensus across all sources. |
| **Take profit (TP1)** | Opposite extreme of C1 range | Universal rule across sources. |
| **Take profit (TP2/TP3)** | Reuse `ict_engine.compute_ict_trade_plan()` | Maintains TradeAI's existing TP cascade logic. |
| **Mitigation** | One-shot per C1 zone | "A CRT zone only works once" — universal rule. Reuse `consumed_sweeps_abs` pattern. |
| **HTF filter** | Existing 4H bias gate (`LIVE_BIAS_4H_GATE`) as "Daily Bias proxy" | 4H bias already approximates the macro direction filter article calls "Daily Bias." |
| **Tokens** | All 10 (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON) | Operator override of article's "BTC+ETH only" default — justified by Run-81 empirical evidence on full portfolio. See §8. |
| **Killzones** | Reuse existing NY AM / London / Asia gates | Proven TradeAI calibration. |
| **Daily cap** | Same as existing template tiers | Tier classification still applies. |
| **Risk per trade** | Same 1% (no change) | Risk management unchanged. |

### v1 — Foundation (target: 55-62% WR ceiling per article's stats)

| Spec dimension | v1 Decision | Honest research rationale |
|---|---|---|
| **Validation school** | FLEXIBLE (Wyckoff) | Trading Wyckoff article author **explicitly recommends** this school: "from a Wyckoff Method perspective, the question of where the sweep candle closes is not the determining factor" + "Practical Recommendation: If you trade from a Wyckoff perspective, the key is the confirmation candle." Authoritative source recommendation, not convenience. |
| **Entry mode** | **HYBRID — LTF MSS per Wyckoff/flexible authorization** | NOT article-conservative (which means waiting for full H4 C3 close = 4+ hours after sweep). NOT article-aggressive (which enters on raw C2 wick break with no confirmation). The 5M MSS approach is explicitly authorized by the flexible school's "Look for MSS (Market Structure Shift) on lower timeframe" alternative. Faster than article-conservative (~30 min vs 4 hours) but more structural than article-aggressive (requires MSS, not just wick). Honest framing: TradeAI hybrid adaptation within Wyckoff school. |
| **Confluence required** | **(FVG OR Order Block) overlap with C1 range OR MSS bar** | Article highlights **Order Block as the PRIMARY confluence** ("CRT + Order Block... probability of reversal increases significantly") with FVG as secondary. Requires new `detect_ict_order_block()` function (~3-4h). Single-confluence requirement (FVG OR OB) rather than both, to avoid over-filtering. |
| **Wyckoff phase context** | NOT IN v1 (documented gap) | Article shows phase context (Accumulation Phase C, Distribution Phase D) is required to reach the 60-65% WR ceiling. Without it, v1's expected WR ceiling is ~55-62%. Deferred to v2. |

### v2 — Research-best ceiling (target: 60-65% WR per article's stats)

| Spec dimension | v2 Addition | Honest research rationale |
|---|---|---|
| **Wyckoff phase detection** | Add `detect_wyckoff_phase()` on H4/D1 — identify accumulation/distribution phases (A/B/C/D/E) | Required for the article's top-tier WR (60-65%). Filter CRT signals: bullish CRT only valid in Wyckoff accumulation Phase C or D; bearish CRT only in distribution Phase C or D. Significant new work (~6-10h) — defers until v1 baseline validates the foundation. |
| **Strict-vs-Wyckoff A/B test** | Implement BOTH validation schools, A/B test via parallel backtest, keep whichever yields higher DSR | Article explicitly says both schools are valid. Author favors flexible but acknowledges strict is more conservative. Best research-correctness: don't pick upfront — let the data decide for OUR specific crypto context. ~4-6h additional code path + backtest comparison. |

### v1 → v2 sequencing rule

v2 work does NOT start until v1 has:
- Produced ≥ 100 backtest CRT signals across 10 tokens
- CPCV verdict = PASS or MARGINAL (not FAIL)
- DSR ≥ 80% (loose floor for experimental track)
- Per-token attribution shows ≥ 5 tokens with WR ≥ 50%

If v1 fails these gates → root-cause analysis BEFORE adding v2 complexity.
Adding more confluences on a broken foundation doesn't fix the foundation.

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
        consumed: set of mitigated C1 ranges. C-CRT-1 fix (2026-05-27): keyed
                  on (c1_time, round(c1.high,6), round(c1.low,6)) — the H4
                  TIMESTAMP, not the array index. List indices shift the
                  moment the H4 cache rotates (rolling window slides forward),
                  which would silently re-fire signals on the same C1 zone
                  every cycle. Timestamp survives cache rotations.
    
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
        c1_time = c4h['times'][c1_idx]
        # C-CRT-1 fix: key on timestamp, not list index (survives cache rotation)
        key = (c1_time, round(c1_high, 6), round(c1_low, 6))
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

## 12. Implementation Effort Estimate (Revised for Phased v1 → v2)

### v1 — Foundation (target: 22-25 hours, 55-62% WR ceiling)

| Task | Hours |
|---|---|
| `crt_engine.py` — H4 CRT detection + Wyckoff/flexible validation | 4-6 |
| `crt_engine.py` — LTF MSS hybrid entry logic (reuses `detect_ict_mss`) | 1-2 |
| `ict_engine.py` — add `detect_ict_order_block()` function | 3-4 |
| `crt_engine.py` — (FVG OR OB) confluence filter | 1 |
| Schema migration (`source` column + backfill default) | 1 |
| `backtest.py` integration (parallel scan path + tag) | 2 |
| `crypto_alert.py` integration | 2 |
| Per-token blacklist env handling (`H4_CRT_DISABLED_TOKENS`) | 1 |
| Test suite — 8-12 unit tests (CRT detection + OB detection + integration) | 3-4 |
| Initial backtest run + per-token attribution analysis | 1-2 |
| Documentation update (CLAUDE.md, README.md, ADAPTIVE_LEARNING.md) | 1 |
| **v1 Total** | **22-25 hours** |

### v2 — Research-best ceiling (additional 10-15 hours, 60-65% WR target)

Only starts after v1 passes its validation gates (see §7 sequencing rule).

| Task | Hours |
|---|---|
| `crt_engine.py` — `detect_wyckoff_phase()` on H4/D1 (5 phases: A/B/C/D/E) | 6-10 |
| Phase-context filter integration into CRT signal pipeline | 1-2 |
| Dual validation school code paths (strict + flexible) | 2-3 |
| A/B backtest harness — run both schools, compare DSR | 1-2 |
| Test suite expansion — phase detection + dual-school cases | 2-3 |
| Re-baseline backtest + per-school per-phase attribution | 1-2 |
| Documentation update with v2 findings + chosen school | 1 |
| **v2 Total** | **10-15 hours** |

### Combined v1 + v2 grand total

**32-40 hours of focused engineering work** to reach research-best CRT
implementation. Spread across multiple sessions with backtest validation
gates between phases.

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

- **2026-05-27 (initial)** — Created. Research consolidated from Trading
  Wyckoff long-form article + 4 web searches across ICT/CRT topic space.
  Operator spec confirmed: H4 reference, 5M entry, all 10 tokens (override
  of BTC+ETH-only conservative default with empirical justification from
  Run-81 baseline performance).

- **2026-05-27 (revision — honest research correction)** — Operator
  flagged that three spec decisions (entry mode, confluence requirement,
  validation school) were framed as "convenient for TradeAI" rather than
  "what authoritative research advocates." Revised:
  - Entry mode honestly labeled as "HYBRID LTF MSS per Wyckoff/flexible
    authorization" (not "conservative" which has a specific article
    meaning we don't match)
  - Confluence broadened to "FVG OR Order Block" — article highlights OB
    as the PRIMARY confluence, not FVG. Adds `detect_ict_order_block()`
    implementation (~3-4h)
  - Validation school rationale rewritten from "code reuse" to "article
    author's explicit recommendation"
  - Added v2 phase with Wyckoff phase detection + strict-vs-flexible
    A/B test to reach the article's reported 60-65% WR ceiling
  - Phased rollout v1 (foundation, 22-25h, 55-62% WR ceiling) → v2
    (research-best, +10-15h, 60-65% WR ceiling) with explicit gates
    between phases
