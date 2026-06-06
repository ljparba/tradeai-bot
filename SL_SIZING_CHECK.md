# Phase C-Breakout — SL Sizing + All-BUY Cluster Check

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~06:25 UTC.
**Audited processes:** A PID 486821, B PID 486822 (alive, on new BE-after-TP1 exit model, untouched).

---

## §0 — The 7 open positions (snapshot)

```
id  tok    dir  entry      SL          SL%      TP1%      TP3%   entry_type      mss   fvg    opened (UTC)
32  XRP    BUY  1.2317     1.217681   -1.138%   +2.276%   +4.553%  H4_BREAKOUT_OB_B  MEDIUM  NONE   2026-06-03 05:15:00
33  HBAR   BUY  0.08839    0.086573   -2.056%   +4.110%   +8.222%  H4_BREAKOUT_FVG_B MEDIUM  LOW    2026-06-03 05:15:00
34  AVAX   BUY  8.295      8.178813   -1.401%   +2.801%   +5.603%  H4_BREAKOUT_FVG_B MEDIUM  MEDIUM 2026-06-03 05:15:00
35  LINK   BUY  8.482      8.364627   -1.384%   +2.768%   +5.535%  H4_BREAKOUT_FVG_B MEDIUM  MEDIUM 2026-06-03 05:15:00
36  BNB    BUY  642.57     639.35715  -0.500%   +1.000%   +2.000%  H4_BREAKOUT_FVG_B HIGH    MEDIUM 2026-06-03 05:15:00
38  ATOM   BUY  1.865      1.851147   -0.743%   +1.486%   +2.971%  H4_BREAKOUT_OB_B  MEDIUM  NONE   2026-06-03 05:15:00
39  BCH    BUY  253.6      248.3514   -2.070%   +4.139%   +8.279%  H4_BREAKOUT_FVG_B HIGH    MEDIUM 2026-06-03 05:15:00
```

All 7 opened on the same 5M bar at 05:15:00 UTC. SL% spans 0.50% – 2.07%.

---

## §1 — SL sizing logic + bounds

### The formula (`compute_breakout_sl_tp` at [`breakout_engine.py:410`](breakout_engine.py#L410))

```python
if direction == "BUY":
    sl_struct = sl_anchor * (1.0 - BREAKOUT_SL_INSIDE_BUFFER_PCT)  # = c1_high × 0.999
    sl = min(sl_struct, entry_price * (1.0 - MIN_SL_PCT))           # whichever is FURTHER from entry
    if sl_pct > MAX_SL_PCT:
        return None                                                  # signal REJECTED — too wide
    risk_dist = entry_price - sl
    tp1 = entry_price + BREAKOUT_TP1_RR * risk_dist                  # RR multiples × actual SL distance
    tp2 = entry_price + BREAKOUT_TP2_RR * risk_dist
    tp3 = entry_price + BREAKOUT_TP3_RR * risk_dist
```

The SL is placed at the **structural level** (just inside the broken zone, 0.1% buffer below the C1 high for BUY), then bounded by:
- **`MIN_SL_PCT = 0.005` (0.5%)** — minimum SL distance from entry. If structural would be even tighter, widen to 0.5%.
- **`MAX_SL_PCT = 0.030` (3.0%)** — maximum SL distance. If structural would be wider, **the signal is REJECTED** (`return None` → emit skipped).

TP cascade is FIXED R-multiples of the actual SL distance: `TP1_RR=2.0, TP2_RR=3.0, TP3_RR=4.0` (from Config 14).

### Effective constants in the running soaks

```
MIN_SL_PCT          = 0.005   (0.5%)
MAX_SL_PCT          = 0.030   (3.0%)
BREAKOUT_SL_INSIDE_BUFFER_PCT = 0.001   (0.1% inside the broken level)
BREAKOUT_TP1_RR     = 2.0
BREAKOUT_TP2_RR     = 3.0
BREAKOUT_TP3_RR     = 4.0
```

### Per-position SL geometry decomposition

| Token | entry | SL | SL% | Rule | Reconstructed c1_high | Entry gap above c1_high |
|---|---|---|---|---|---|---|
| **BNB** | 642.57 | 639.36 | 0.500% | **MIN FLOOR** (structural was tighter) | (tighter than floor) | (gap minimal — entry near c1_high) |
| ATOM | 1.865 | 1.851 | 0.743% | structural | 1.853 | +0.648% |
| XRP | 1.2317 | 1.2177 | 1.138% | structural | 1.2189 | +1.050% |
| LINK | 8.482 | 8.365 | 1.384% | structural | 8.373 | +1.302% |
| AVAX | 8.295 | 8.179 | 1.401% | structural | 8.187 | +1.319% |
| **HBAR** | 0.08839 | 0.08657 | **2.056%** | structural | 0.08666 | **+1.997%** |
| **BCH** | 253.6 | 248.35 | **2.070%** | structural | 248.60 | **+2.011%** |

**None exceed the 3.0% MAX cap.** All within `[0.500%, 2.070%]`.

### Why are HBAR and BCH so wide?

The SL is structural: just below the broken C1 high. The wide SL distance reflects that **entry opened ~2% ABOVE the C1 high** for these two tokens — a strong gap-up breakout. The 5M entry bar (the bar AFTER MSS confirmation) opened well above the C1 zone, leaving the structural SL (just inside the C1 zone) ~2% away.

This is **correct structural behavior, not a computation error**. Wide SL = price moved far past the broken zone before the strategy could enter. The structural SL stays at the technical invalidation point (back inside C1).

### TP scaling check — RR multiples honor actual SL distance

| Token | SL dist (price) | TP1 RR | TP2 RR | TP3 RR | Match 2/3/4? |
|---|---|---|---|---|---|
| XRP | 0.01402 | 2.000 | 3.000 | 4.000 | ✓ |
| HBAR | 0.00182 | 1.999 | 2.999 | 3.999 | ✓ (rounding) |
| AVAX | 0.11619 | 2.000 | 3.000 | 4.000 | ✓ |
| LINK | 0.11737 | 2.000 | 3.000 | 4.000 | ✓ |
| BNB | 3.21285 | 2.000 | 3.000 | 4.000 | ✓ |
| ATOM | 0.01385 | 2.000 | 3.000 | 4.000 | ✓ |
| BCH | 5.24860 | 2.000 | 3.000 | 4.000 | ✓ |

**All 7 honor RR=2/3/4 exactly off the actual SL distance.** So HBAR/BCH (wide SL) have proportionally wide TPs: TP1 at +4.1%, TP3 at +8.2%. Internally consistent geometry.

**§1 verdict: SL sizing is CORRECT structural behavior within MAX_SL_PCT. HBAR/BCH wide SLs reflect ~2% gap-up entries, not bugs.**

---

## §2 — Risk implication under the new BE-after-TP1 R model

### R normalization (key claim to verify)

The R formula divides every gain/loss by `risk = abs(net_sl)`. For a LOSS:

```
realized_R = net_sl / risk = -|net_sl| / |net_sl| = -1.0
```

This is **invariant to SL width**. A LOSS on BNB (SL 0.5%) and a LOSS on BCH (SL 2.07%) both contribute exactly **−1.0 R** to the gate math.

Worked example (BCH #39, 2.07% SL, RT cost 0.3% for BCH):

```
gross_sl   = -2.070%
net_sl     = round(-2.070 - 0.30, 2) = -2.37
risk       = 2.37
R if LOSS  = -2.37 / 2.37 = -1.0    ✓
```

Same for HBAR (RT cost 0.5%):

```
gross_sl   = -2.056%
net_sl     = round(-2.056 - 0.50, 2) = -2.56
risk       = 2.56
R if LOSS  = -2.56 / 2.56 = -1.0    ✓
```

**Confirmed: wide-SL tokens are NOT over-risked in R terms.** Each closed signal contributes the same R magnitude regardless of structural SL width. The backtest and soak are purely R-normalized; the gate math `(avg_R ≥ +0.40 over n≥30)` is independent of position-sizing choices.

### Live position-sizing implication (operator-facing note)

When the operator deploys to Bybit, position size in dollars depends on the SL distance:

| Sizing scheme | Wide SL impact |
|---|---|
| **Fixed-R sizing** (`position_USDT = capital × risk% / sl_dist%`) | Same R risk per position. Wide-SL position has SMALLER notional in dollars. Correct portfolio risk; matches what the backtest assumed. |
| **Fixed-notional sizing** (same dollar amount per signal) | Wide-SL position has BIGGER R risk per position. Would over-weight HBAR/BCH-style 2% setups vs BNB's 0.5%. Mismatches the backtest. |

**Recommendation (informational):** the operator should use fixed-R sizing on Bybit to match the backtest's R-normalized model. With 7 simultaneous opens at SL widths 0.5%-2.07%, a fixed-notional scheme would have BCH/HBAR dollar-risk ~4× BNB's.

---

## §3 — The all-BUY cluster (regime check)

### Market state around 05:15 UTC (cluster open time)

Fetched fresh BTC 15M klines from Binance:

| time UTC | open | close | %chg |
|---|---|---|---|
| 03:00 | 66620 | 66516 | −0.16% |
| 03:15 | 66516 | 66148 | −0.55% |
| 03:30 | 66148 | **65755** | **−0.59% (intraday low)** |
| 03:45 | 65755 | 65850 | +0.14% |
| 04:00 | 65850 | 66340 | +0.74% |
| 04:15 | 66340 | 66579 | +0.36% |
| 04:30 | 66579 | 66441 | −0.21% |
| 04:45 | 66441 | 66466 | +0.04% |
| **05:00** | **66466** | **67136** | **+1.01% (rally bar)** |
| **05:15** | **67136** | **67103** | **−0.05%** ← signal cluster bar |
| 05:30 | 67103 | 67026 | −0.11% |
| 05:45 | 67026 | 67330 | +0.45% |
| **06:15 (now)** | 67160 | 67353 | +0.29% |

**BTC rallied from the 65755 intraday low (03:30) to 67269 (05:00 high), +2.30% in 90 minutes.** The all-BUY cluster fired at 05:15 — exactly when the major alts likely had their 4h candles break the C1 zone after the BTC rally. BTC is now at 67353, **+1.0% above where it was when the cluster fired**.

### Were all 7 tokens correlated?

Cross-checked `c1_zone_key` from `feature_scores_json`:

| Token | c1_time | c1_high | c1_low |
|---|---|---|---|
| XRP | 2026-06-03 00:00 UTC | 1.2189 | 1.1977 |
| HBAR | 2026-06-03 00:00 UTC | 0.08666 | 0.08547 |
| AVAX | 2026-06-03 00:00 UTC | 8.187 | 8.051 |
| LINK | 2026-06-03 00:00 UTC | 8.373 | 8.228 |
| BNB | 2026-06-03 00:00 UTC | 640.11 | 632.81 |
| ATOM | 2026-06-03 00:00 UTC | 1.853 | 1.82 |
| BCH | 2026-06-03 00:00 UTC | 248.6 | 243.8 |

**All 7 c1_time values are identical (2026-06-03 00:00 UTC) — the same parent 4h bar (00:00-04:00 UTC) across every token.** Each token has its OWN unique `(c1_high, c1_low)` pair, so the `consumed-zone key (c1_time, c1_high, c1_low)` tuple is unique per token → no duplication / no zone re-fire.

All 7 are `sweep_type=BSL_BREAKOUT` (committed close above the C1 high). MSS quality ranges HIGH/MEDIUM (no LOW); confluence types are mixed FVG/OB.

### Is simultaneous multi-token firing normal?

**Yes — and expected.** Crypto markets are highly correlated, especially during BTC-led moves. When BTC rallies +2.3% in 90 minutes, the major alts typically participate (varying betas), and each one's H4 candle simultaneously closes above its previous high. The strategy fires the BSL_BREAKOUT trigger on each independently — they're not duplicates, they're correlated independent setups.

Per `DIRECTIONAL_ANALYSIS.md`, the prior 26 closed signals were SELL-dominant (18 SELL / 8 BUY) during a confirmed downtrend (BTC −6.4%/28h). **The current cluster is the REGIME-FLIP signal**: BTC bounced from 65755 to 67353 (+2.4% from yesterday's afternoon low), and the strategy's direction-blind triggers naturally rotated to BUY-side. This is exactly the "captures whichever direction breaks" behavior `DIRECTIONAL_ANALYSIS.md` predicted: SELL wins in downtrends, BUY wins in uptrends.

### Cross-correlation risk (informational)

If all 7 close as LOSS, the gate sees 7 × (−1.0) = **−7 R sum**. That's a substantial drawdown chunk concentrated in ~48h. The gate's `max DD ≤ 20R` ceiling has plenty of room but the correlation is real.

This is a known characteristic of correlated-asset strategies, not a bug. Crypto's high correlation means simultaneous wins (like this cluster could deliver) AND simultaneous losses both compress into short windows. The R-normalized gate math handles this; the OPERATOR's portfolio-level risk does depend on:
- Whether the Bybit harness caps simultaneous open positions
- Whether per-token notional is capped to a fraction of total capital

These are LIVE-side guardrails, not strategy-model issues.

---

## §4 — Verdict

**(a) Wide SL is CORRECT structural behavior within MAX_SL_PCT.**

- All 7 within `[0.500%, 2.070%]`; cap is 3.0%; none rejected.
- BNB at 0.500% hit the MIN floor (its structural SL would have been even tighter).
- HBAR/BCH at ~2% reflect entries ~2% above C1_high (gap-up breakouts). The structural SL stays at the technical invalidation point, which is naturally ~2% away. **Not a bug.**
- TP cascade honors RR=2/3/4 off the actual SL distance for all 7 (verified to 3 decimals).

**(b) Risk is properly R-normalized; wide-SL tokens are not over-risked in R terms.**

- LOSS = −1.0 R for every position regardless of SL width (verified for BCH and HBAR explicitly).
- The backtest and soak are R-normalized. The +0.40 R gate is invariant to SL-width distribution.
- **Live operator note (NOT a bug):** for the Bybit auto-trade to match the backtest's R-normalization, use **fixed-R position sizing** (`position_USDT = capital × risk% / sl_dist%`). Fixed-notional sizing would over-risk wide-SL positions.

**(c) The all-BUY cluster is a REGIME-ALIGNED correlated move, not a concern.**

- BTC rallied +2.3% in 90 min just before the cluster (65755 → 67269); all major alts followed and broke their respective C1 highs at the same 5M bar.
- 7 distinct `c1_zone_keys` (each token's own high/low) — no duplication, no zone re-fire.
- The cluster signals the regime turn from the downtrend (BTC −6.4% over Jun 1-2) to the rally (BTC +2.4% from low). Per `DIRECTIONAL_ANALYSIS.md`, this is exactly the predicted behavior: BUY wins in uptrends as SELL wins in downtrends.
- Crypto high correlation makes simultaneous firing normal. Not a duplication bug.

**No code change proposed.** All three findings are normal/expected behavior. Two informational notes for the operator's go-live notebook:

1. Use **fixed-R position sizing** on Bybit to match the backtest's R-normalization. Wide-SL setups (HBAR, BCH) should automatically get smaller notional.
2. Crypto correlation means **simultaneous open positions are expected**. Consider whether the Bybit harness should cap max-concurrent positions (e.g. ≤5 simultaneous open), or whether the operator is comfortable letting all 7 ride. Strategy edge survives at unlimited concurrency in backtest; live capital allocation is the operator's call.

---

## §5 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched |
| `data/signals.db` (production) | unchanged |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `ae46c1d` (BE-after-TP1 commit), not pushed |
| Soak A 486821 / B 486822 | ALIVE, cycling, untouched throughout this audit |
| All DB backups | intact |

Awaiting operator call. No fixes applied.
