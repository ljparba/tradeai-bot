# MEAN_REVERSION_EXPLORATION — descriptive property measurement (read-only)

**Bottom line: NO — these tokens do NOT exhibit a robust, economically-meaningful mean-reversion
property at the tradeable timescale.** At **1H the price series are essentially random walks**
(variance ratio ≈ 1.00 for all 12 tokens). At **5M the aggregate VR is <1, but that is
concentrated in a couple of illiquid tokens (AVAX, TON) with extreme negative lag-1
autocorrelation — the classic bid-ask-bounce *microstructure* signature — and it VANISHES at 1H**
(AVAX 5m VR2 0.578 → 1h VR2 1.005). Post-breakout, price **reverts and continues at roughly equal
rates** (~36% each within 60 bars on TF_B) — random-walk-like, not fade-like. So the three clues
(low-vol breakouts win, SELL>BUY, counter-trend profitable) do **not** translate into a tradeable
mean-reversion property. **This is descriptive measurement only — NO strategy built, proposed, or
tuned.**

720d, 12 tokens, in-memory (NO DB writes). Soaks A=515231, B=515230 + fade=512666 alive and
untouched. **Variance Ratio** VR(q) = Var(q-bar log return) / (q·Var(1-bar log return)):
VR<1 mean-revert, ≈1 random walk, >1 trend.

---

## 1. Core statistic — Variance Ratio + return autocorrelation

### 5M log returns (per-token + mean)
| token | VR2 | VR4 | VR8 | VR16 | ac1 | ac5 |
|-------|-----|-----|-----|------|-----|-----|
| BTC | 0.984 | 0.969 | 0.957 | 0.941 | −0.007 | +0.005 |
| ETH | 0.991 | 0.987 | 0.993 | 0.981 | −0.003 | +0.005 |
| XRP | 0.980 | 1.016 | 0.991 | 0.961 | +0.005 | −0.013 |
| HBAR | 1.009 | 1.066 | 1.084 | 1.064 | +0.020 | −0.026 |
| **AVAX** | **0.578** | **0.534** | 0.532 | 0.537 | **−0.306** | −0.046 |
| LINK | 0.974 | 1.034 | 1.007 | 1.005 | −0.003 | −0.040 |
| BNB | 0.848 | 0.841 | 0.841 | 0.851 | −0.080 | −0.011 |
| ADA | 0.880 | 0.952 | 0.977 | 0.956 | −0.015 | −0.054 |
| POL | 0.997 | 1.054 | 1.085 | 0.829 | +0.025 | −0.022 |
| **TON** | **0.421** | **0.493** | 0.486 | 0.334 | **−0.178** | −0.076 |
| ATOM | 0.946 | 1.010 | 1.026 | 1.028 | +0.010 | −0.014 |
| BCH | 0.982 | 0.980 | 0.977 | 0.940 | −0.007 | +0.000 |
| **MEAN** | **0.882** | **0.911** | **0.913** | **0.869** | **−0.045** | −0.024 |

→ Aggregate VR<1, but it is **driven by a few tokens**: AVAX (VR2 0.578, ac1 −0.306) and TON
(0.421, ac1 −0.178) dominate, with BNB/ADA milder. **8 of 12 tokens (BTC, ETH, XRP, LINK, BCH,
ATOM, POL, HBAR) sit at VR ≈ 0.94–1.09 — random walk** (HBAR even slightly >1). The extreme
AVAX/TON values + large *negative lag-1* autocorrelation are the textbook **bid-ask-bounce /
microstructure** signature of noisy or less-liquid 5m data — not economic mean-reversion.

### 1H log returns (per-token + mean)
| | VR2 | VR4 | VR8 | VR16 | ac1 |
|---|---|---|---|---|---|
| MEAN | **1.002** | **0.991** | **0.973** | **1.006** | −0.004 |

→ **All 12 tokens cluster at VR ≈ 0.92–1.05 — random walk at 1H.** Crucially, the strong 5m
"reversion" in AVAX/TON **disappears** at 1H (AVAX 5m VR2 0.578 → 1h 1.005; TON 0.421 → 1.053).
That confirms the 5m effect is **microstructure noise, not a tradeable property** — it does not
survive aggregation to the 1H scale where a strategy would actually operate.

---

## 2. Post-breakout reversion (existing breakout signals)

Of each breakout, within N 5m bars: % that **reverted** to the broken level (≈ SL) vs % that
**continued** to TP3; plus the near-miss-revert rate (reached ≥50% to TP1 then reverted to SL).

### TF_B (5M/1H) — n=12330
| within | % revert-to-broken-level | % reached TP3 | % near-miss-revert |
|--------|--------------------------|---------------|--------------------|
| 12 bars (1h) | 12.2% | 15.7% | 4.1% |
| 30 bars (2.5h) | 20.7% | 28.5% | 10.9% |
| 60 bars (5h) | **36.1%** | **36.7%** | 24.1% |

### TF_A (5M/4H) — n=4843
| within | % revert | % TP3 | % near-miss-revert |
|--------|----------|-------|--------------------|
| 12 bars | 21.9% | 12.1% | 3.5% |
| 30 bars | 27.6% | 28.5% | 7.5% |
| 60 bars | 34.2% | 41.4% | 13.5% |

→ **Reversion and continuation are roughly balanced** (TF_B 60-bar: 36.1% revert vs 36.7%
continue; TF_A even tilts to *continuation* 34.2% vs 41.4%). This is **random-walk-like — not the
"breakouts behave like fades" picture**. The near-miss-revert (price pokes toward TP1 then comes
back) is real (10–24% by 60 bars) and is the same signature the day-1 analysis saw, but it is a
**minority** outcome, not a dominant reversion tendency.

---

## 3. Regime-conditional (within 30 bars, revert-to-broken-level rate)

| regime | TF_B | TF_A |
|--------|------|------|
| BEAR | 23.6% (n3986) | 31.6% (n1506) |
| BULL | 22.5% (n4252) | 27.8% (n1719) |
| RANGE | **16.0%** (n4092) | 23.6% (n1618) |

→ Reversion (breakout failure back to the level) is **highest in BEAR, lowest in RANGE** — the
*opposite* of the "reversion dominates in chop" intuition from the day-1 read. The differences are
modest. There is no regime where reversion strongly dominates; even in the most-reverting bucket
(BEAR ~24–32%), continuation is the more common path. Consistent with the random-walk VR at 1H.

---

## 4. Overlap with the production FADE strategy

The production fade is itself mean-reversion (sweep → reverse). The relevant finding here is what
it implies for the fade:
- **If a broad MR property existed, any "new" MR edge would largely DUPLICATE the fade** — the
  answer would be "re-validate the fade," not "build something new."
- **But the property is NOT broadly present** (random walk at 1H; 5m effect is microstructure).
  That implies the fade's edge — to the extent it has one — comes from the **specific sweep→reverse
  setup and its timing/structure**, NOT from a general statistical MR tendency of the tokens. A
  generic MR strategy on these tokens has no underlying statistical property to exploit at the 1H
  scale, so it would neither beat nor meaningfully differ from the fade; it would just be a
  weaker, less-specific version of the same idea.

---

## 5. Interpretation (descriptive only)

**Do these tokens exhibit a real, measurable mean-reversion property at 5m/1h? — Essentially no.**
- **1H: random walk** (VR ≈ 1.00 across all 12 tokens). No mean-reversion at the tradeable scale.
- **5M: aggregate VR<1 is microstructure**, concentrated in 2 illiquid tokens (AVAX, TON) via
  large negative lag-1 autocorrelation (bid-ask bounce) that **vanishes at 1H**. Not an economic edge.
- **Post-breakout: revert ≈ continue** (~balanced; TF_A even favors continuation). Not fade-like.
- The three motivating clues are better explained without invoking MR: low-vol breakouts win
  because high-vol entries are climactic/late (entry-timing, not series-MR); SELL>BUY is a
  sample-period directional drift; counter-trend profitability comes from the breakout *exit model*
  extracting R from near-random paths regardless of the trend label.

**Heavy caveats:**
- **A statistical property ≠ a profitable strategy.** Even the 5m AVAX/TON negative autocorrelation
  is almost certainly **un-capturable after fees** — bid-ask-bounce reversion lives inside the
  spread; friction + slippage erase it (the fade's own mixed history shows MR ideas don't bank
  easily here).
- VR/autocorrelation are sample- and sampling-frequency-sensitive; the 5m vs 1h split is exactly
  why the 5m reading must not be over-read.
- Confirming a property (which here we mostly *fail* to find) would only justify a **separate
  pre-registered strategy experiment from zero** — and given the random-walk 1H result, there is
  little statistical basis for one.

**No mean-reversion strategy is built or proposed.** The property is not robustly there at the
tradeable scale; the apparent 5m signal is microstructure that disappears at 1H; post-breakout
behavior is balanced/random-walk-like; and any MR edge would duplicate the existing fade rather
than be new. Reporting what the data shows; building nothing.

---

**Isolation honored:** read-only descriptive measurement; in-memory (0 DB rows written); both
soaks (A 515231, B 515230) + fade (512666) alive and untouched; signals.db + Run-3704 pin
unchanged; main untouched; branch not pushed. No strategy, no rules, no change. STOP.
