# TREND_EXPLORATION — descriptive trend-property measurement (read-only)

**Bottom line: NO tradeable trend property at 4H / 12H / daily.** The variance ratio does **not**
rise above 1 at higher timeframes — it is ≈1 at 4H (a tiny trend tilt at the shortest horizons
that fades) and actually **slightly below 1 at 12H and daily** (a mild *mean-reversion* tilt, the
opposite of trend). Daily efficiency ratio is **~0.22 — firmly in the chop band** (a clean trend
needs >0.5); daily return autocorrelation is **~0 at all lags 1–10** (no persistence); and a daily
moving-average direction null test hits **~49–50% (coin-flip)** with a near-zero, inconsistent
forward signal. So the tokens are **random walk (with a mild MR tilt) at every scale tested
(5m → daily)** — trend-following has **no statistical foundation** here, same as mean-reversion.
**Descriptive measurement only — NO strategy built, proposed, or tuned.**

720d, 12 tokens, in-memory (NO DB writes; reads the 4H cache, resampled to 12H/daily by UTC
grouping). Soaks A=515231, B=515230 + fade=512666 alive and untouched. Builds on
`MEAN_REVERSION_EXPLORATION.md` (random walk at 1H) by extending the variance-ratio method up to
the daily scale. VR(q) = Var(q-bar log return)/(q·Var(1-bar)): **>1 trend, ≈1 random walk, <1 mean-revert.**

---

## 1. Variance ratio across timeframes — the core test

| timeframe | mean VR2 | mean VR4 | mean VR8 | mean VR16 | reading |
|-----------|----------|----------|----------|-----------|---------|
| **4H** (4320 bars) | 1.036 | 1.057 | 0.983 | 0.997 | ≈ random walk; faint trend tilt at q2/q4 that fades by q8 |
| **12H** (1440 bars) | 0.989 | 0.950 | 0.928 | 0.934 | **< 1 — mild mean-reversion**, not trend |
| **DAILY** (~720 bars) | 0.943 | 0.951 | 0.978 | — | **< 1 — mild mean-reversion**, not trend |

**Key question answered: VR does NOT cross above 1 at higher timeframes.** If trend emerged at
scale, VR would rise meaningfully above 1 at 4H/daily. Instead it sits at ≈1 (4H) and dips to
0.93–0.95 (12H/daily). The faint 4H q2/q4 tilt (1.04–1.06) is the *only* >1 reading and it
disappears by q8 — not a sustained trend. Per-token at daily, every token is in 0.86–1.13 (close
to 1, several clearly <1 — BCH 0.90/0.90/0.81, LINK 0.89/0.88/0.82, ADA 0.86/0.91). Sample sizes:
4H n≈4320, 12H n≈1440, daily n≈660–720 (POL/TON shorter); **daily VR at long q is noisier — read
q2/q4 as primary, q8 as indicative.**

---

## 2. Daily trend-strength: efficiency ratio + return autocorrelation

- **Kaufman efficiency ratio (N=20), mean = 0.222** (range 0.190–0.262 across tokens). ER ~0.0–0.3
  = **chop**; >0.5 = clean trend. **No token exceeds 0.27** — daily paths are inefficient/choppy,
  little net directional movement per unit of path length. The opposite of a trending series.
- **Daily return autocorrelation, lags 1–10 (mean):** all near zero (+0.001, −0.020, −0.037,
  +0.012, +0.018, −0.008, +0.018, −0.035, +0.007, +0.037). **No persistent positive
  autocorrelation** — trend would show consistently positive multi-lag persistence; this is
  random-walk noise.

---

## 3. Trend-direction NULL test (daily, PRE-friction — NOT a strategy)

State = long if close > daily MA else short; forward = next-day log return.
`signal = mean(state · forward_return)`: >0 = trend-direction carries info, ≈0 = coin-flip, <0 = mean-revert.

| MA | mean hit-rate | mean signal (state·fwd) | reading |
|----|---------------|--------------------------|---------|
| **20-day** | **49.2%** | **+0.000196** (~0.02%/day) | coin-flip, ~zero signal |
| **50-day** | **49.8%** | **+0.001147** (~0.11%/day) | coin-flip; tiny, inconsistent positive |

→ Hit-rate is **~49–50% — coin-flip** (even slightly below 50% at 20-day). The 20-day signal is
**essentially zero**; the 50-day signal is **barely positive (~0.11%/day pre-friction)** and
**inconsistent across tokens** (positive for ETH +0.0027, HBAR +0.0034, POL +0.0029, but *negative*
for AVAX, ADA, BCH). A real trend property would show hit-rate clearly >50% and a consistent
positive signal across tokens. This is **no reliable directional information** — only a faint hint
that *longer* lookbacks capture marginally more (the slow-trend intuition), but far too small and
inconsistent to be a foundation, and pre-friction (at ER=0.22 chop, whipsaws + friction would
erase it).

---

## 4. Per-token + time-window variation

- **Per-token:** no token trends. Large caps are **not** more trending than alts — BTC daily VR2
  0.933, ETH 0.921 (both mildly <1), ER ~0.226/0.231, same chop band as the alts. The 50-day
  signal positives (ETH/HBAR/POL/TON) vs negatives (AVAX/ADA/BCH) show **no clean large-cap-vs-alt
  split** — trend strength is uniformly low everywhere.
- **Time variation (daily ER, first vs second half of 720d):** every token stays in the
  **0.18–0.28 chop band in both halves** (BTC 0.244→0.216, BNB 0.180→0.246, BCH 0.205→0.177). No
  half is meaningfully more trending; **no sustained-trend regime emerges** that would be frequent
  or large enough for trend-following to live on. The window is uniformly choppy at daily.

---

## 5. Interpretation (descriptive only)

**Is there a real, measurable TREND property at 4H/daily? — No.** The tokens are **random walk
(with a mild mean-reversion tilt) at every scale tested**:
- **VR never rises above 1 at higher TFs** — ≈1 at 4H, slightly <1 (mean-reverting) at 12H/daily.
- **Efficiency ratio ~0.22** at daily = chop, not clean trends; **daily autocorrelation ~0** = no persistence.
- **Daily MA-direction is a coin-flip** (49–50% hit), with a near-zero/inconsistent forward signal.
- **No token, and no time-window, trends** more than the rest.

**Consequence for strategy direction:** trend-following has **no statistical foundation** in these
12 tokens at 4H/12H/daily — the same null result mean-reversion gave at 5m/1h. Combined with:
- `MEAN_REVERSION_EXPLORATION.md` — random walk at 1H, no MR edge;
- the Config 14 breakout being broad-marginal (+0.34, below the +0.40 gate);

the honest read is that **price-pattern edges appear absent in these tokens across the full tested
range (5m → daily)** — they are broadly random walk (mild microstructure MR at 5m in a couple of
illiquid names; mild MR tilt at 12H/daily; no trend anywhere). This points **away from price-based
strategies entirely** (trend, mean-reversion, and breakout all rest on a price-pattern property
that the data does not show).

**Caveats:**
- A trend property — which here mostly **isn't present** — would still not be a profitable strategy
  by itself; friction, whipsaws, and the trend-following "death by a thousand cuts" in ER≈0.22 chop
  routinely erase even real trend signals. So even the faint 50-day tilt is not actionable.
- VR/ER/autocorr are sample- and frequency-sensitive; daily VR at long q (n≈700) is noisy — the q2/q4
  readings and ER are the more reliable, and they agree: no trend.
- Confirming a property is the *precondition* for a separate pre-registered experiment; here the
  precondition **fails**, so there is no foundation to justify a trend-following experiment.

**No trend-following strategy is built or proposed.** The trend property is not there at 4H/12H/daily;
the tokens are random walk at all tested scales. Reporting what the data shows; building nothing.

---

**Isolation honored:** read-only descriptive measurement; in-memory (0 DB rows written); both soaks
(A 515231, B 515230) + fade (512666) alive and untouched; signals.db + Run-3704 pin unchanged; main
untouched; branch not pushed. No strategy, no rules, no change. STOP.
