# Phase C-Breakout — Config B (5M/1H) Paper Soak Pre-Registration

**LOCKED BEFORE the first B signal is emitted.**
**Date:** 2026-06-02 (UTC)
**Branch:** `breakout-thesis @ 70852df` (uncommitted code for B added on top)
**A soak running independently:** PID 458923, source tag `H4_BREAKOUT_PAPER_SOAK`

> This document is the **binding contract** for what counts as B passing or
> failing its forward soak. Operator can change the criteria at any time but
> only by writing a new pre-registration document AND time-stamping the change.
> A mid-soak gate tweak without a corresponding new pre-reg is not honored.

---

## 1. Locked configuration — exactly Config B from the TF comparison

| Knob | Value | Source |
|---|---|---|
| Entry timeframe | **5M** | locked |
| Reference timeframe | **1H** | this is the only delta vs A |
| `H4_BREAKOUT_CLOSE_BUFFER_PCT` | 0.001 | Config 14 fingerprint (matches A) |
| `BREAKOUT_TP1_RR` | 2.0 | matches A |
| `BREAKOUT_TP2_RR` | 3.0 | matches A |
| `BREAKOUT_TP3_RR` | 4.0 | matches A |
| `H4_BREAKOUT_C2_LOOKBACK` | 4 (1H bars = 4 hours wall-clock) | TF-scaling rule (same bar count) |
| `H4_BREAKOUT_MSS_HORIZON` | 30 (5M bars = 150 minutes) | matches A |
| `H4_BREAKOUT_OB_SCAN_LOOKBACK` | 20 | matches A |
| `H4_BREAKOUT_FVG_PROBE_WIDTH` | 3 | matches A |
| `BREAKOUT_SL_INSIDE_BUFFER_PCT` | 0.001 | matches A |
| `MIN_SL_PCT / MAX_SL_PCT` | 0.005 / 0.030 | matches A |
| `MAX_BREAKEVEN_WR` | 0.60 | matches A |
| `ICT_MIN_RR_GATE` | 1.3 | matches A |
| Forward outcome window | 48 h wall-clock | matches A |
| Universe | 12 tokens (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON, ATOM, BCH) | matches A |
| Adaptive / OGD | **OFF** | clean baseline |
| Wyckoff filter | **OFF** | clean baseline |
| Funding overlay | **OFF** | clean baseline |
| BTC-correlation overlay | **OFF** | clean baseline |
| Staleness guard | 60 min on signal emit | matches A |

**The ONLY structural difference between A and B is the reference timeframe.**
Everything else is held identical so the comparison is a clean A/B test of TF.

## 2. Process / state isolation (B never touches A)

| | A soak | B soak |
|---|---|---|
| Script file | `breakout_paper_soak.py` | `breakout_paper_soak_B.py` |
| PID file | `data/breakout_soak.pid` | `data/breakout_soak_B.pid` |
| Heartbeat file | `data/breakout_soak_heartbeat.json` | `data/breakout_soak_B_heartbeat.json` |
| Log file | `logs/breakout_soak.log` | `logs/breakout_soak_B.log` |
| Source tag (DB) | `H4_BREAKOUT_PAPER_SOAK` | `H4_BREAKOUT_PAPER_SOAK_B` |
| Reference TF data | Binance REST `4h` klines | Binance REST `1h` klines |
| Entry TF data | Binance REST `5m` klines | Binance REST `5m` klines |
| Consumed-zone set | per-process, rebuilt from own source-tag rows | per-process, rebuilt from own source-tag rows |
| DB writer | `data/breakout.db` | `data/breakout.db` (same DB, different `source` filter) |

**Cross-process guarantee:** SQLite WAL mode permits concurrent writers + readers.
Each soak's `consumed` set is rebuilt at startup from `signals WHERE source = <its own tag>` —
A's writes can't pollute B's mitigation set and vice versa. Per-statement commits
keep transactions short.

## 3. LOCKED GATE (binding verdict)

**Same five criteria as A's soak**, applied to B's first **30 closed signals**:

| Criterion | Threshold | Verdict mechanism |
|---|---|---|
| avg_R per closed signal | ≥ **+0.40** | PENDING until n ≥ 30; PASS if observed ≥ threshold, FAIL otherwise |
| profit factor | ≥ **2.0** | same as above |
| WR strict ((WIN + PARTIAL_TP2) / n) | ≥ **55%** | same |
| max drawdown (R) | ≤ **20** | same |
| per-token blowup | no token with WR ≤ 35% AND avg_R < 0 over ≥ 5 signals | same |
| **n closed ≥ 30** | yes | PENDING gate (no verdict before this) |

**Overall verdict logic:**
- `n_closed < 30` → **PENDING** (no criterion can flip to PASS/FAIL)
- `n_closed ≥ 30` AND all 5 PASS → **PASS**
- `n_closed ≥ 30` AND any FAIL → **FAIL**

## 4. **CRITICAL CAVEAT** (recorded UP FRONT, NOT after results land)

The five criteria are **identical to A's** by operator choice. This may be
**unfavorable to B's structural profile**:

- A's TF backtest (90-day, friction-on) reported **WR = 69.1%**, comfortably
  above the 55% floor.
- **B's TF backtest (90-day, friction-on) reported WR = 61.8%** — closer to
  the 55% floor, with less cushion. A 7-pp friction-to-soak degradation
  would put B below the WR gate while still being a profitable strategy
  in absolute R terms.
- B's edge IS NOT in WR; it's in **VOLUME × per-trade R**. Per the TF
  backtest, B produced 2.4× more total R than A (+750 vs +311 clean,
  +607 vs +245 friction-on) despite lower WR.
- A WR-floor failure on B should NOT be interpreted as "B has no edge."
  It would mean "B fails the COMMON gate" — which is a different statement.

**This is on the record BEFORE results land so it cannot be added retroactively.**
If B fails the WR gate but passes expectancy, the operator will see the data
honestly framed — no spin in either direction.

## 5. Tracking-only metrics (NOT part of the gate)

For B specifically, also record (read-only display in the viewer):

- **sum_R** — total R earned across all closed B signals
- **R per attempt** — sum_R / n_attempted (where attempts include rejected /
  unfilled, so this is the strategy's economic efficiency per signal opportunity)
- **R per day** — sum_R / days_elapsed (volume × per-trade efficiency)
- **friction-adjusted expected avg_R** = +0.549 from the 90-day backtest (this
  is the reasonable forward expectation, NOT the +0.40 floor)

These are **observational only**. If they look strong while the WR gate fails,
the operator has the data to argue that the WR gate was the wrong yardstick
for B's profile. If they ALSO look weak, B genuinely failed.

The 5 binding criteria in §3 are the verdict mechanism. Nothing else flips
PASS or FAIL.

## 6. Expected timeline

- B's TF backtest (90-day) produced **1132 clean signals = ~12.6 signals/day
  across 12 tokens**.
- Forward live rate will be lower (signals from very recent setups don't make
  it past the 60-min staleness guard for the first ~hour), so first cycles
  may emit nothing.
- After stabilization, **B's first 30 closed signals should arrive in ~2.5-3
  days** of pure detection plus the 48 h forward outcome window = **~5 days**
  from soak start to first gate evaluation.
- A (currently at cycle 69, 0 closed) is on a slower schedule because A's
  backtest signal rate is ~4.6/day (vs B's 12.6/day).

## 7. What this pre-registration does NOT do

- ❌ Recommend merging B to main if it passes
- ❌ Recommend swapping the live config from A to B
- ❌ Predict whether A or B will land better on forward data
- ❌ Change A's gate or A's soak in any way

## 8. Reference-line to judge avg_R against

B's friction-on 90-day backtest: **+0.549 avg_R per filled signal**.
- The +0.40 floor has +0.149 R cushion baked in.
- A forward avg_R of +0.40-0.45 means "real friction is worse than the model
  predicted by ~20-30%" but still passing.
- A forward avg_R of +0.50+ means "the friction model was a reasonable predictor."
- A forward avg_R of +0.55+ means "the live experience matched or beat the
  backtest expectation" — exceptional.

Same logic applies for A:
- A's friction-on 90-day backtest: **+0.616 avg_R per filled signal**.
- A's +0.40 floor has +0.216 R cushion.

This pre-registration is the binding contract. Document hash + checksum can
be regenerated from the file contents.
