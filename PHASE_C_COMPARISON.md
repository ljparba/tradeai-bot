# Phase C-Breakout — Fade CRT vs Breakout Comparison

**Mode:** Read-only diagnostic. Both DBs opened with `file:...?mode=ro` URI.
**Audit time:** 2026-06-02 ~02:54 UTC
**Branch:** `breakout-thesis @ 98fafcf` (pushed to origin/breakout-thesis)
**Both soaks still running unchanged throughout this read.**

> **Headline: NO VALID FORWARD COMPARISON IS POSSIBLE TODAY.**
>
> Fade live has **n = 5** closed signals (all from 2026-05-28, statistically
> meaningless). Breakout soak has **n = 0** closed signals (started ~75 min ago,
> waiting for first qualifying H4 close + 5M MSS to materialize). The locked
> 30-signal gate cannot be evaluated yet on either side. A merge decision
> today would rest **on backtest data only**.

---

## 0. What was read, from where

| Source | File | Read mode |
|---|---|---|
| Fade CRT (live, PAPER) | `/home/tradeai/TradeAI/data/signals.db` | `file:...?mode=ro` |
| Breakout (backtest + friction + soak) | `/home/tradeai/breakout-work/data/breakout.db` | `file:...?mode=ro` |

No writes issued from this audit. SQLite URI `mode=ro` enforced at the C
level (any `INSERT/UPDATE/DELETE` raises `OperationalError: attempt to write
a readonly database`).

---

## 1. Raw numbers — pulled live from the two DBs

### 1.1 Fade CRT — LIVE FORWARD (production soak `/home/tradeai/TradeAI/`)

**Query:** `signals.source = 'H4_CRT' AND signals.status = 'CLOSED'`
joined to `results` on `signal_id`.

```
n_closed       : 5
date span      : signals opened 2026-05-27 17:02 → 2026-05-28 00:00
                 signals closed 2026-05-28 01:30 → 2026-05-28 05:05
direction      : all 5 are SELL (no BUY in the closed forward sample)
outcomes       : WIN=3, PARTIAL_TP1=2, LOSS=0, PARTIAL_TP2=0, EXPIRED=0
```

Per-signal split-exit R reconstruction (50% at TP1 + 50% at TP3 model,
matched to the breakout backtest's accounting so the rows are comparable):

| token | outcome | tp1_pct | tp3_pct | sl_pct | split-exit R |
|---|---|---:|---:|---:|---:|
| LINK | WIN | 2.16 | 4.33 | -2.16 | **+1.502** |
| TON | PARTIAL_TP1 | 6.18 | 12.35 | -6.18 | **+0.500** |
| TON | WIN | 3.06 | 6.13 | -3.06 | **+1.502** |
| TON | PARTIAL_TP1 | 4.13 | 8.27 | -4.13 | **+0.500** |
| AVAX | WIN | 1.31 | 1.96 | -0.98 | **+1.668** |

**Aggregate (n = 5):**
- avg_R (split-exit) = **+1.134**
- sum_R = +5.67
- profit factor = **∞** (no losses in the sample)
- max drawdown (R) = 0.00
- WR strict ((WIN+PARTIAL_TP2)/n) = **60.0%**

**Critical caveats:**
1. **n = 5 is statistically meaningless.** Confidence intervals on the avg_R
   span from near-zero to comfortably above the backtest expectation. No
   honest conclusion can be drawn at this sample size.
2. **No closed signals exist after 2026-05-28** despite the fade soak
   running 24/7 since 2026-05-30. The current Run-3704 config has produced
   **zero new signals in ~3.5 days**. Either market conditions are
   unfavourable to the current fade gates or the bot's signal pool is
   currently dry.
3. **All five signals are SELL.** No BUY-direction live data exists on the
   fade side to compare. Backtest data shows fade is symmetric on direction;
   live forward data has not yet sampled the BUY side.
4. **Live bot's `realized_r` column is NULL** for these 5 rows — the schema
   field exists but is not populated by the production close path. The R
   values above are reconstructed from `profit_pct` + the signal row's
   `sl_pct/tp1_pct/tp3_pct` using the same split-exit formula the breakout
   backtest uses. This is the apples-to-apples accounting; the bot's
   `profit_pct` column instead records the gross % move (assumes 100% at
   highest TP), which would be larger.

### 1.2 Breakout — BACKTEST Config 14 frictionless (`backtest_runs.id = 14`)

**Source:** historical 365-day OHLCV (cached from Binance, frozen ~2026-05-31).

```
config         : H4_BREAKOUT_CLOSE_BUFFER_PCT=0.001, BREAKOUT_TP1_RR=2.0,
                 BREAKOUT_TP2_RR=3.0, BREAKOUT_TP3_RR=4.0,
                 H4_BREAKOUT_C2_LOOKBACK=4, H4_BREAKOUT_MSS_HORIZON=30
n              : 2249  (out of attempted 2249; no friction = no rejections)
data span      : 365 days of 5m/4h OHLCV per token (2025-Q2 through 2026-Q2)
outcomes       : WIN=1406, PARTIAL_TP2=101, PARTIAL_TP1=77, LOSS=660, EXPIRED=5
```

**Aggregate:**
- avg_R = **+0.722**
- sum_R = +1624.51
- profit factor = **3.461**
- max drawdown (R) = 14.12 (over 365 days)
- WR strict ((WIN+PARTIAL_TP2)/n) = **67.0%**

### 1.3 Breakout — FRICTION-ON screen (`backtest_runs.id = 18`)

**Source:** same 365-day OHLCV, signals filtered through
`execution.simulate_execution` (spread + latency + partial fills +
no_fill + adverse selection). Default execution defaults, `regime="UNKNOWN"`
(disables +5 bps adverse-selection — under-states friction slightly).

```
config         : Config 14 (same as 1.2)
n_attempted    : 2222   ← bot would have emitted these
n_filled       : 2180   ← after execution.simulate_execution
n_partial      :   88   (FULL fill = 2092, 50% fill = 88)
n_rejected_no_fill :  42
n_rejected_stale   :   0 (bar-data harness limit)
outcomes       : WIN=1377, PARTIAL_TP2=97, PARTIAL_TP1=69, LOSS=632, EXPIRED=5
```

**Aggregate:**
- avg_R per filled signal = **+0.607**
- avg_R per attempted signal = +0.595
- sum_R = +1322.73
- profit factor = **3.140**
- max drawdown (R) = 14.81
- WR strict = **67.6%**

### 1.4 Breakout — PAPER SOAK forward (`signals.source = 'H4_BREAKOUT_PAPER_SOAK'`)

**Source:** the running soak at PID 458923, accumulating forward data.

```
n_closed       : 0
n_open         : 0
n_total        : 0
soak running   : cycle 39 (~75 min elapsed since 2026-06-02 01:37 UTC)
gate target    : 30 closed signals  →  progress 0 / 30  (0.0%)
```

**No metrics are computable yet.** The breakout soak refuses to emit signals
whose MSS bar is more than 60 min old (no time-travel on signals that already
played out), so the first signal will fire only after a fresh H4 close +
5M MSS confirmation that the operator could realistically have traded.

---

## 2. Side-by-side table

| Metric | **Fade CRT — LIVE FORWARD** | **Breakout — BACKTEST (clean)** | **Breakout — BACKTEST (friction-on)** | **Breakout — SOAK FORWARD** |
|---|---:|---:|---:|---:|
| **Source label** | FORWARD/LIVE (paper soak) | BACKTEST/SIMULATED (historical) | BACKTEST/SIMULATED (historical + friction model) | FORWARD/LIVE (paper soak) |
| **n closed** | **5** | 2249 | 2180 | **0** |
| **WR strict** | 60.0 % | 67.0 % | 67.6 % | n/a (n = 0) |
| **avg R (split-exit)** | **+1.134** | +0.722 | +0.607 | n/a (n = 0) |
| **PF** | **∞** (no losses in sample) | 3.461 | 3.140 | n/a (n = 0) |
| **sum R** | +5.67 | +1624.51 | +1322.73 | n/a (n = 0) |
| **max DD (R)** | 0.00 | 14.12 | 14.81 | n/a (n = 0) |
| **Data span** | 2026-05-27 to 2026-05-28 (1.5 days, all closed by May 28) | ~365 days of 5m/4h OHLCV (2025-Q2 to 2026-Q2) | same 365 days | ~75 min elapsed (started 2026-06-02 01:37 UTC) |
| **Statistical weight** | **NONE — n too small** | High — robust per CPCV PASS verdict (Step 1) | High — same n base, friction model adds variance | **NONE — n = 0** |

### Apples-to-apples columns

Direct forward-vs-forward comparison: **Column 1 vs Column 4**.

| | Fade live forward | Breakout soak forward |
|---|---:|---:|
| n | 5 | 0 |

**This comparison cannot produce a verdict.** The fade column has n = 5
(too small to support any conclusion); the breakout column has n = 0
(nothing to compare against). The locked breakout gate (§3) cannot be
applied until n ≥ 30. The fade live record has not refreshed since May 28,
so even more fade forward data will not materialize at the current signal
rate.

### Apples-to-oranges columns (do NOT use for merge decisions)

- Fade live forward (n=5, May 27-28) vs Breakout backtest C14 (n=2249, 365d) — **invalid**: forward sample is dated and tiny; backtest is large and out-of-time-window.
- Fade live forward vs Breakout friction-on backtest — same problem.
- Breakout backtest vs Breakout friction-on — **valid** but already covered in `PHASE_C_STEP2A_FRICTION.md`. Not new information.

---

## 3. Locked breakout gate — current status

From `PHASE_C_STEP2B_SOAK_STARTED.md §1`, applied to the soak's **0** closed
signals so far.

| Criterion | Threshold | Observed (soak) | Status |
|---|---|---:|---|
| avg_R per closed signal | ≥ **+0.40** | n/a | **PENDING** |
| profit factor | ≥ **2.0** | n/a | **PENDING** |
| WR strict | ≥ **55%** | n/a | **PENDING** |
| max drawdown (R) | ≤ **20** | n/a | **PENDING** |
| per-token blowup | no token at WR ≤ 35% AND avg_R < 0 over ≥ 5 signals | n/a | **PENDING** |
| **n closed ≥ 30** | yes | 0 | **PENDING (0/30)** |

The viewer's overall verdict is locked at **PENDING** until `n ≥ 30`. No
criterion can flip to PASS or FAIL before then.

**Distance to gate evaluation:** at the breakout backtest's expected rate of
~6 signals/day across 12 tokens, the gate becomes evaluable in roughly
**~5 days of pure detection + 2 days of 48h-window resolution = ~7 days** from
soak start. Soak started 2026-06-02 01:37 UTC → gate evaluation realistically
not before 2026-06-09. If live signal density runs lower than backtest
(as is currently the case for fade — 0 new signals in 3.5 days), the gate
date slips proportionally.

---

## 4. Honest decision framing

**A merge decision today would rest on backtest data only.** Specifically:

- Backtest C14 (clean): +0.72 avg_R, PF 3.46, WR 67%, max DD 14R — strong.
- Friction-on backtest: +0.61 avg_R, PF 3.14, WR 67% — still strong; 16% degradation.
- The Step 1 grid showed all 8 TP-B configs PASS CPCV, regime-stable across 5 calendar quarters, per-token positive on all 12 tokens.

**What is unknown today:**

1. **Whether the breakout backtest's edge holds in forward live data.** Zero
   forward observations exist on the breakout side.
2. **Whether the fade soak's apparent live silence (5 signals total, zero
   since May 28) is regime drag, a configuration tightening, or a structural
   issue.** This is a question about the FADE side that this comparison
   surfaced but does not answer.
3. **Whether the operator's manual execution will match the friction model.**
   The soak measures "signal edge" not "operator-realized edge"; some
   additional discount will apply in real account terms.

**What the comparison does NOT tell us:**

- It does NOT tell you breakout is "better" than fade in live — both forward
  samples are too small for any such claim.
- It does NOT show breakout under-performs — there's just no forward data yet.
- It does NOT validate or invalidate the locked gate — the gate cannot be
  evaluated at n = 0.

**No merge / no-merge recommendation is made here.** The numbers are presented
above; the forward-vs-backtest distinction is explicit; the locked gate's
PENDING status is binding. The merge decision sits with the operator.

---

## 5. Isolation check (re-verified at end of read)

| Check | State |
|---|---|
| Fade soak alive | PID 393274, cycle 8221, ts 2026-06-02 02:54:13, 0 errors |
| Breakout soak alive | PID 458923, cycle 39, ts 2026-06-02 02:53:57, 0 open / 0 closed |
| Fade `signals.db` size | unchanged at 5,492,736 bytes (verified before + during reads) |
| Run-3704 pin | run_id 3704, mtime 2026-05-30 14:31:11 — unchanged |
| Breakout `breakout.db` writer | PID 458923 only (own fds + `fuser` confirms) |
| `main` branch on origin | `af331b9` — NOT touched by this audit (no pushes, no merges) |
| `breakout-thesis` on origin | `98fafcf` — exactly what we pushed in the prior step |
| This audit's connections | both read-only URI mode; no `INSERT/UPDATE/DELETE` issued |

---

## 6. Cross-reference

- For the locked breakout gate spec: `PHASE_C_STEP2B_SOAK_STARTED.md §1`
- For the backtest grid evidence: `PHASE_C_BREAKOUT_REPORT.md`
- For the friction screen detail: `PHASE_C_STEP2A_FRICTION.md`
- For the soak isolation + viewer correctness: `PHASE_C_AUDIT.md`
- For the soak runtime monitoring: `VIEWER_README.md` (port 8890)

---

## 7. Reproducing this report

```bash
# Fade live, split-exit R reconstruction
sqlite3 -readonly "file:/home/tradeai/TradeAI/data/signals.db?mode=ro" \
  "SELECT s.id, s.token, s.signal, s.sl_pct, s.tp1_pct, s.tp3_pct, r.result, r.profit_pct \
   FROM signals s JOIN results r ON r.signal_id = s.id \
   WHERE s.source = 'H4_CRT' AND s.status = 'CLOSED' ORDER BY s.id;"

# Breakout backtest C14 + friction
sqlite3 -readonly "file:/home/tradeai/breakout-work/data/breakout.db?mode=ro" \
  "SELECT outcome, COUNT(*), ROUND(AVG(realized_r),4), ROUND(SUM(realized_r),2) \
   FROM backtest_signals WHERE run_id IN (14, 18) GROUP BY run_id, outcome;"

# Breakout soak forward
sqlite3 -readonly "file:/home/tradeai/breakout-work/data/breakout.db?mode=ro" \
  "SELECT status, COUNT(*) FROM signals WHERE source='H4_BREAKOUT_PAPER_SOAK' GROUP BY status;"
```
