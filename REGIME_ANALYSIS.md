# Phase C-Breakout — Regime Handling + Regime Coverage Analysis

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~04:30 UTC.
**Audited processes:** A PID 473059, B PID 473060 (both alive on F3/F4-fixed code, untouched).

---

## Part 1 — Is there a regime gate?

### What I searched

Greps run against the entire breakout side of the codebase, looking for any signal-gating regime mechanism: keywords `regime / REGIME / adx / TRENDING / RANGING / ENABLE_REGIME / REGIME_FILTER` and conventional gating idioms.

| File | Hits |
|---|---|
| `breakout_engine.py` | **0 hits** for "regime" (only `range` as in `for d in range(...)` and `order_block_overlaps_range`) |
| `breakout_paper_soak.py` | **0 hits** for any regime keyword |
| `breakout_paper_soak_B.py` | **0 hits** for any regime keyword |
| `run_tf_grid.py` | **1 hit**: [`run_tf_grid.py:368`](run_tf_grid.py#L368) → `regime="UNKNOWN"` hardcoded |

### Detailed inspection of the one hit

[`run_tf_grid.py:362-372`](run_tf_grid.py#L362-L372):

```python
res = simulate_exec_fn(
    signal_ts=ts_dt, signal_price=signal_price,
    next_bar_open=next_bar_open, token=tok,
    direction=s["signal"], regime="UNKNOWN",
    atr_5m=atr, atr_ratio=atr_ratio, seed=seed,
)
```

`simulate_execution` lives in `/home/tradeai/TradeAI/execution.py`. The `regime` parameter there is documented and used **as a cost input only**, not as a signal-gating filter:

[`execution.py:152`](../TradeAI/execution.py#L152) — `regime: str, # "TRENDING_BULL" | "TRENDING_BEAR" | "RANGING" | ...`
[`execution.py:56`](../TradeAI/execution.py#L56) — `5. **Adverse selection** — in TRENDING_BULL/BEAR regimes, retail entries face`
[`execution.py:217`](../TradeAI/execution.py#L217) — `adverse = ADVERSE_SELECT_COST if regime in ("TRENDING_BULL", "TRENDING_BEAR") else 0.0`

So `regime` in `execution.py` controls **adverse-selection cost**: when the regime is trending, an extra cost is added to simulated entries (modelling adverse fill in trending markets). When regime is anything else (including `"UNKNOWN"`), this cost is zero.

The backtest passes `regime="UNKNOWN"` for every signal. **The backtest's friction-on numbers therefore do NOT include any regime-dependent adverse-selection penalty** — they're regime-blind on the cost side.

### Verdict for Part 1

| Question | Answer |
|---|---|
| Is there a signal-gating regime filter (rejects/accepts signals by regime)? | **No.** Not in `breakout_engine.py`, not in either soak, not in the backtest. |
| Is there an env knob to toggle one? | **No.** No `REGIME_FILTER`, `ENABLE_REGIME`, or equivalent. |
| Does `execution.py`'s regime parameter affect signal generation? | **No.** It only modulates per-trade adverse-selection cost. |
| Is regime-dependent cost applied in the backtest? | **No.** `regime="UNKNOWN"` is hardcoded, so `adverse=0` always. |
| Live ↔ backtest parity on regime handling? | ✓ Both are regime-blind (no live regime gate either). |

**The breakout system has zero regime gating. It is a pure structural-trigger strategy (committed C2 close + 5M MSS + FVG/OB confluence) that runs regardless of macro market state.**

This is distinct from the fade (CRT) engine, which has `LIVE_BIAS_4H_GATE` and `CRT_REQUIRE_1H_TREND` knobs — those gate on a directional bias, not a regime classification, but they're at least *toggleable*. Breakout has neither.

---

## Part 2 — What regimes did the backtest cover?

### Actual backtest window

The cache files are named `*_365d.json` (and contain 369.7 days of 4H bars from 2025-05-26 to 2026-05-30), BUT [`run_tf_grid.py:34-35`](run_tf_grid.py#L34-L35) slices to a 90-day window:

```python
END_MS   = int(datetime(2026, 5, 31, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
START_MS = END_MS - 90 * 24 * 60 * 60 * 1000
```

= **2026-03-02 → 2026-05-31, 90 days**. Verified by the actual `backtest_signals.ts` range:

| Source | First signal | Last signal | Days covered |
|---|---|---|---|
| `H4_BREAKOUT_TF_A_5m_4h_FRICTION` | 2026-03-03 | 2026-05-28 | 79 distinct days |
| `H4_BREAKOUT_TF_B_5m_1h_FRICTION` | 2026-03-02 | 2026-05-28 | 88 distinct days |

> The "365d" cache filename is a misnomer for the breakout backtest — only the most recent 90 days drive the +0.616/+0.549 reference avg_R values. The other 275 days of cached data are unused.

### Per-token regime characterization over the 90-day window

Method: for each of the 12 breakout tokens, computed over the 90-day 4H closes:
- `%chg` = net price change start→end
- `max_DD%` / `max_RU%` = max running drawdown vs run-up
- `vol_ann%` = annualized realized vol from log-returns
- `%>SMA20` = fraction of 4H bars closing above their 20-bar SMA (trending proxy)

Regime label rules (simple, transparent):
- `STRONG_TREND` if |%chg| ≥ 25%
- `TRENDING` if |%chg| ≥ 10% and `%>SMA20` ≤ 35% or ≥ 65%
- `RANGING` if 45 ≤ `%>SMA20` ≤ 55 and |%chg| < 15%
- `VOLATILE_CHOP` if max_DD > 25% AND max_RU > 25% AND |%chg| < 15%
- else `MIXED`

| tok | first | last | %chg | max_DD% | max_RU% | vol_ann% | %>SMA20 | regime |
|---|---|---|---|---|---|---|---|---|
| BTC | 66820 | 73880 | +10.6 | 11.8 | 25.1 | 38.9 | 54.4 | RANGING |
| ETH | 1972 | 2022 | +2.5 | 18.9 | 26.1 | 51.6 | 48.1 | RANGING |
| XRP | 1.374 | 1.341 | −2.4 | 17.2 | 17.0 | 45.1 | 45.6 | RANGING |
| HBAR | 0.0990 | 0.0951 | −3.9 | 20.0 | 21.8 | 52.9 | 42.1 | MIXED |
| AVAX | 9.12 | 8.95 | −1.9 | 18.1 | 21.2 | 56.9 | 50.0 | RANGING |
| LINK | 8.83 | 9.19 | +4.1 | 18.1 | 28.6 | 55.2 | 50.2 | RANGING |
| BNB | 624 | 719 | +15.1 | 15.6 | 25.6 | 36.9 | 55.4 | MIXED |
| ADA | 0.277 | 0.236 | −14.8 | 21.1 | 21.6 | 55.2 | 45.0 | RANGING |
| POL | 0.108 | 0.090 | −16.8 | 24.3 | 27.8 | 51.5 | 50.4 | MIXED |
| **TON** | 1.205 | 1.818 | **+50.9** | 36.5 | 127.8 | 89.6 | 48.7 | **STRONG_TREND** |
| ATOM | 1.818 | 2.034 | +11.9 | 18.4 | 38.5 | 56.4 | 51.8 | RANGING |
| **BCH** | 450 | 306 | **−32.0** | 38.8 | 12.3 | 49.5 | 40.1 | **STRONG_TREND** |

**Distribution:**
- RANGING: **7/12 tokens (58%)**
- MIXED: **3/12 tokens (25%)**
- STRONG_TREND: **2/12 tokens (17%)** — TON (up) and BCH (down)

### Sub-period (within-window) regime check using BTC as macro proxy

Splitting the 90 days into 3 ~30-day buckets:

| Sub-period | BTC %chg | BTC max-DD | Sub-regime |
|---|---|---|---|
| 2026-03-02 → 2026-03-31 | +2.2% | 11.9% | RANGING |
| 2026-04-01 → 2026-04-30 | +12.0% | 16.5% | RANGING (choppy uptrend with deep mid-month dip) |
| 2026-05-01 → 2026-05-30 | −4.2% | 11.6% | RANGING |

Every sub-period is RANGING by the macro proxy. **The 90-day window does not include a sustained directional macro regime.**

### Per-regime backtest avg_R (the key answer)

Bucketing each token's signals by its per-token regime label and summing:

**TF_A (5m / 4h) friction-on:**

| Bucket | n | sum_R | avg_R |
|---|---|---|---|
| RANGING (BTC, ETH, XRP, AVAX, LINK, ADA, ATOM) | 288 | +171.77 | **+0.596** |
| MIXED (HBAR, BNB, POL) | 40 | +25.86 | **+0.646** |
| STRONG_TREND (TON, BCH) | 70 | +47.62 | **+0.680** |

All three buckets positive. Strong-trend slightly higher per-signal than ranging.

**TF_B (5m / 1h) friction-on:**

| Bucket | n | sum_R | avg_R |
|---|---|---|---|
| RANGING | 744 | +468.64 | **+0.630** |
| MIXED | 147 | +31.30 | **+0.213** |
| STRONG_TREND | 215 | +107.36 | **+0.499** |

TF_B's MIXED bucket is weak (+0.21), pulled down by POL (n=29, avg_R=−0.147) and a thin HBAR (n=18, avg_R=+0.063). Strong-trend still solidly positive; RANGING is the dominant contributor.

### Per-month avg_R (within-window stability)

**TF_A:** 2026-03 +0.433 / 2026-04 +0.655 / 2026-05 +0.781 — all months above the +0.40 gate.
**TF_B:** 2026-03 +0.530 / 2026-04 +0.525 / 2026-05 +0.591 — all months above the gate, and remarkably stable.

The edge is **temporally stable across the 90-day window**, with no single month carrying disproportionate weight.

---

## Part 3 — Verdict

### (a) Is there a toggleable regime gate?

**No.** The breakout system has zero regime gating, no env knob, no quality gate, no bias gate, no trend gate. The only `regime` parameter in the call graph (`execution.py`) is a cost-side input and is hardcoded to `"UNKNOWN"` in the backtest — so even adverse-selection cost is regime-blind. Live ↔ backtest parity on regime handling is intact (both regime-blind). The strategy fires on pure structural triggers (committed C2 close + 5M MSS + FVG/OB confluence + economics).

### (b) What regimes did the backtest cover?

**Validation window is 90 days (2026-03-02 → 2026-05-31), NOT 365 as the cache filenames suggest.**

Per-token regime over the window:
- 58% RANGING (7/12 tokens)
- 25% MIXED (3/12 tokens)
- 17% STRONG_TREND (2/12 tokens — TON +50.9%, BCH −32%)

Within-window, BTC sub-periods are all RANGING (no sustained macro trend at the index level).

### Is the edge regime-dependent?

Per-regime bucket avg_R:

| Regime bucket | TF_A avg_R | TF_B avg_R | Both above gate (+0.40)? |
|---|---|---|---|
| RANGING | +0.596 | +0.630 | ✓ |
| MIXED | +0.646 | +0.213 | TF_A yes, TF_B no |
| STRONG_TREND | +0.680 | +0.499 | ✓ |

**The headline +0.616/+0.549 averages survive when sliced by regime, with one exception**: TF_B in the MIXED bucket falls to +0.213, dragged by POL (one underperforming token). This is the only sub-population below the gate threshold.

Importantly: a breakout strategy **self-selects trending micro-moments** by definition — every signal requires a committed H4 close beyond C1, which is itself a directional break. So even within a "ranging" macro regime, the strategy only acts during the trending sub-moments. The macro-regime classification of the token reflects what the OPERATOR sees, not what the strategy trades.

### Known risks for the live decision

1. **90-day, regime-narrow validation.** The window spans a single quarter with predominantly ranging macro behavior (BTC ±5% per month, max-DD ~12-17%). The strategy has NOT been validated against:
   - A sustained multi-month bear trend (e.g., 2022-style 70% drawdown).
   - An extended low-volatility sideways year (e.g., 2018-style 75% vol crush).
   - A high-volatility expansion / parabolic phase (e.g., 2021 Q1 or 2024 Q4).
   - A macro vol shock (COVID-March-2020 style).
   The 365 days of cached data exist but are NOT used by `run_tf_grid.py`. Extending validation to the full 365 days would test at least one more market sub-phase.

2. **Per-token regime coverage is asymmetric.** STRONG_TREND tokens (TON, BCH) are only 2/12 of the sample. Both showed positive avg_R, but n is small (70 in TF_A, 215 in TF_B). Confidence interval on the trending-regime edge is wider than the ranging-regime edge.

3. **No regime-dependent cost in the backtest.** `regime="UNKNOWN"` skips `execution.py`'s adverse-selection cost (`ADVERSE_SELECT_COST` from `execution.py:217`). If we believe trending regimes carry adverse-selection cost in live trading, the backtest is mildly optimistic for trending regimes. Magnitude is bounded by `ADVERSE_SELECT_COST` (single value in execution.py).

### What this is NOT

- It's NOT a bug. There's no requirement that a breakout strategy have a regime gate; many real-world breakout systems run flat regardless. The architectural choice "fire on every structural setup" is consistent live↔backtest.
- It's NOT a divergence from the validated backtest. The live soak and the backtest are both regime-blind — they will fire (or not fire) in the same way under the same market conditions.
- It's NOT a reason to delay live deployment, but it IS a known risk to log in the operator's go-live notes.

### Recommendation (operator decision)

No code change proposed. Two notebook items for the operator's go-live risk register:

1. **Validation window note.** Document that the +0.616 / +0.549 backtest references were measured on a 90-day window dominated by ranging crypto markets, not a full-cycle bear/sideways/bull mix. The first 6-12 months live should be considered "regime-out-of-sample" testing, not a confirmation of the backtest.
2. **Regime-extended re-backtest (optional, for confidence)**. The cache already contains 369 days. A trivial change to `run_tf_grid.py:35` (`START_MS = END_MS - 365 * 24 * 60 * 60 * 1000`) would extend validation by ~3 quarters at zero code cost — exposing the strategy to multiple macro regimes within the cached data. **NOT proposed as part of this audit**; flagged as a low-effort, high-confidence-gain follow-up the operator may want before n≥30 lock.

---

## §4 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched |
| `data/signals.db` (production) | unchanged by this audit (read-only access only) |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (not pushed) |
| Both soaks (A 473059, B 473060) | alive, untouched, cycling |
| All 3 DB backups | intact |

Awaiting operator call. No fixes applied.
