# CRT v1 Session 2 — Backtest Bias Audit

**Branch:** `experiment/crt-h4-signal-source` @ `3d47c77`
**Date:** 2026-05-27
**Scope:** Session 2 additions only — `run_backtest_token_h4_crt()` and integration blocks.
**Files reviewed:**
- `/home/tradeai/TradeAI/backtest.py` lines 109-117, 1228-1238, 1254-1473, 1858-1907, 3210-3221, 3446-3463
- `/home/tradeai/TradeAI/crt_engine.py` (full — shared detection module)
- `/home/tradeai/TradeAI/ict_engine.py:215-290` (score_ict_mss), `298-360` (score_ict_fvg)
- `/home/tradeai/TradeAI/labeling.py:40-126` (triple_barrier_label)
- `/home/tradeai/TradeAI/docs/comprehensive/CROSS_REF.md` (prior-art check)

---

## 1. Executive Summary

The Session 2 integration of `run_backtest_token_h4_crt()` is structurally sound.
The Session 1 CRITICAL findings (C-CRT-1 mitigation key, C-CRT-2 dual MSS
implementations) and HIGH findings (H-CRT-1 FVG overlap zone, M-CRT-1
dual-extreme short-circuit) are all confirmed FIXED in the current `crt_engine.py`.
The mitigation set lifecycle — fresh per token, persistent across H4 scan windows —
is correct. Entry execution (bar-open of next 5M after MSS) is strictly forward.
Outcome simulation only uses bars after `entry_bar`. Forward-bar guard arithmetic
is correct.

One CRITICAL lookahead bias was found: the 5M sub-window contains `+60`
headroom bars that extend past the H4 scanning window's close time. The FVG
mitigation scan inside `score_ict_fvg` sweeps ALL remaining closes in the
sub-window (including those +60 future bars) to decide if a FVG is "consumed."
A FVG that would be valid at signal generation time can be incorrectly rejected
because a bar in the future headroom filled it. This biases the backtest toward
FEWER but HIGHER-QUALITY signals — the direction is opposite to typical overfitting
(it will understate signal count), but it is still a form of data leakage that
makes backtest results non-reproducible in live trading.

One HIGH issue was found: `ENABLE_H4_CRT` is absent from `_compute_run_config_hash()`,
causing CRT-enabled and CRT-disabled runs on the same config to collide on the same
config_hash. This undercounts DSR n_trials and corrupts the Pareto-archive uniqueness
check in the autonomous explorer if the explorer ever tests CRT variants.

**Overall verdict: OPTIMISTIC** — FVG qualification overstates signal selectivity
vs real-time trading; DSR n_trials undercounting is a statistical integrity issue.
The strategy IS non-lookahead in entry price (correct bar-open execution), outcome
simulation (clean forward window), and C1/C2 detection (closed H4 bars only). The
bias is narrow and fixable.

---

## 2. CRITICAL Findings

### B-CRT-S2-C1 — FVG mitigation scan reads future bars via +60 headroom (LOOKAHEAD BIAS)

**File:** `backtest.py:1314-1315` (window construction) + `ict_engine.py:333-337` (mitigation logic)

**Mechanism:**
```
c5m_end_idx = bisect_right(c5m["times"], h4_end_time_ms)
c5m_end_idx = min(c5m_end_idx + 60, n5)   # +60 bars (5h) headroom
```
`h4_end_time_ms` is the OPEN time of the last H4 bar in the window (`c4h["times"][h4_end-1]`,
where `c[0]` = kline open_time per `backtest.py:325`). The H4 bar CLOSES 4 hours (48 5M
bars) later. The `+60` adds another 60 5M bars beyond the H4 bar's open time = approximately
12 bars (1 hour) past the H4 bar's CLOSE time.

Inside `detect_h4_crt`, `_check_confluence` calls `score_ict_fvg(d, h5, l5, o5, c5)` where
`c5 = c5m_win["closes"]`. In `score_ict_fvg` (`ict_engine.py:333-337`):
```python
if len(closes) > d + 2:
    if direction == "BUY" and any(closes[k] <= bottom for k in range(d + 2, len(closes))):
        return None
    if direction == "SELL" and any(closes[k] >= top for k in range(d + 2, len(closes))):
        return None
```
This sweeps `closes[d+2:]` all the way to the end of the sub-window — including the
future +60 bars added by the headroom. A FVG at `mss_bar_5m - 1` or `mss_bar_5m`
that is valid at signal-generation time (before the H4 bar closes) can be disqualified
by a fill that occurs in those future 60 bars. In live trading, the scanner would see
the FVG as unmitigated and accept the signal; the backtest sees it as mitigated and
rejects it.

**Direction of bias:** The backtest will generate FEWER CRT signals than the live
scanner would. The rejected signals are those followed by a close fill within ~1 hour
of the H4 bar close — which likely includes many mean-reverting setups. The surviving
signals skew toward those with persistent FVGs, which may have higher WR in backtest.
This is a form of survivorship bias within the signal-generation step.

**Why it would not reproduce in live trading:** In live, `detect_h4_crt` is called
during the scan cycle; the sub-window ends at the current candle. The `+60` headroom
only exists in the backtest's historical sub-window construction. Signal counts and
WRs will diverge.

**Severity:** CRITICAL — invalidates the CRT signal count and skews WR.

**Fix path:** In `run_backtest_token_h4_crt`, trim the sub-window to end exactly at
the H4 bar's close time (open_time + 4×3600×1000 ms), not open_time + 5h. Replace:
```
c5m_end_idx = bisect_right(c5m["times"], h4_end_time_ms) + 60
```
with:
```
h4_close_time_ms = h4_end_time_ms + 4 * 3600 * 1000
c5m_end_idx = bisect_right(c5m["times"], h4_close_time_ms)
```
Then add minimal post-close headroom for the MSS scan:
```
c5m_end_idx = min(c5m_end_idx + H4_CRT_MSS_HORIZON + 5, n5)
```
This correctly anchors the sub-window to the H4 CLOSE time and only adds the
MSS horizon beyond it — matching live scanner semantics.

---

### B-CRT-S2-C2 — `ENABLE_H4_CRT` absent from `_compute_run_config_hash()` (DSR CONTAMINATION)

**File:** `backtest.py:3243-3279` (full hash payload), confirmed absent by
`grep -n "ENABLE_H4_CRT" backtest.py` (only appears at import and conditional block,
never in the hash dict)

**Mechanism:** A backtest run with `ENABLE_H4_CRT=0` and one with `ENABLE_H4_CRT=1`
on identical ICT parameters produce materially different signal pools but hash to
the SAME `config_hash`. Downstream effects:

1. **DSR n_trials undercounting:** `COUNT(DISTINCT config_hash)` in `backtest.py:3516`
   treats CRT-enabled and CRT-disabled as the same trial. The selection-bias correction
   in DSR (Bailey/LdP 2014) is weakened.

2. **Pareto-archive corruption:** The autonomous explorer's Pareto-archive uses
   `config_hash` for uniqueness. A CRT-enabled trial would overwrite a CRT-disabled
   trial of the same parameter set, or vice versa — silently losing one result.

3. **Checkpoint collision:** A checkpoint from a CRT-disabled run could be resumed
   as a CRT-enabled run (or vice versa), mixing signal pools mid-run.

**Severity:** CRITICAL for statistical validity. The DSR gap is compounded by the
existing `cumulative_min_trials=27` seed — the hash collision means the seed anchors
the denominator conservatively, but a future explorer session testing CRT variants
would fail to increment it accurately.

**Fix path:** Add to `_compute_run_config_hash()` payload:
```python
"ENABLE_H4_CRT":          os.environ.get("ENABLE_H4_CRT", "0"),
"H4_CRT_DISABLED_TOKENS": os.environ.get("H4_CRT_DISABLED_TOKENS", ""),
"H4_CRT_C2_LOOKBACK":     os.environ.get("H4_CRT_C2_LOOKBACK", "10"),
"H4_CRT_MSS_HORIZON":     os.environ.get("H4_CRT_MSS_HORIZON", str(ICT_MSS_HORIZON)),
```

---

## 3. HIGH Findings

### B-CRT-S2-H1 — Swing computation on future-contaminated sub-window (ROLLING-WINDOW LEAKAGE)

**File:** `crt_engine.py:256` + `ict_engine.py:76-87`

`find_ict_swings(h5, l5)` is called on the full `c5m_win` arrays, which (as established
in B-CRT-S2-C1) can include bars up to 12 bars past the H4 bar's close time. The swing
identification at bar `i` requires `highs[i] > highs[i+1]` and `highs[i] > highs[i+2]`
(ICT_SWING_N=2). For bars near `sweep_5m_idx - 2` and `sweep_5m_idx - 1`, the confirmation
bars `i+1` and `i+2` may include future bars that lie past the H4 bar's close.

If a swing high that would have been confirmed at the close of the H4 C2 bar would NOT
be confirmed by the future bars (because those future bars are higher), it will be
absent from `sh_5m`, changing which `recent_sh` is selected in `score_ict_mss`. This
affects which MSS level is targeted and whether MSS confirms at all.

**Severity:** HIGH — the swing list contamination is more subtle than the FVG
mitigation issue but affects the MSS confirmation logic. Note that fixing B-CRT-S2-C1
(trimming the sub-window to H4 close time + MSS horizon) would also eliminate this
issue: the extra 12 future bars causing swing contamination would be removed.

---

### B-CRT-S2-H2 — Blended CPCV pool mixes signal sources without per-source attribution

**File:** `backtest.py:3565-3569`

```python
_cpcv = cpcv_summary(
    _tune_sigs,  # all_signals including H4_CRT when ENABLE_H4_CRT=1
    n_trials_for_dsr=_n_trials_dsr,
    sr_trial_std_for_dsr=_sr_trial_std_honest,
)
```

When CRT is enabled, `_tune_sigs` contains both `source='5M_SWEEP'` and
`source='H4_CRT'` signals. The CPCV folds assign both sources to the same fold
boundaries, which are determined by time (sorted by `ts`). Since CRT signals are
interleaved with 5M signals by timestamp, fold WR computation blends two
strategically different signal types.

**Statistical validity problem:** The CPCV headline WR and DSR refer to the COMBINED
strategy, not either component. Promoting based on a combined CPCV when only the 5M
baseline has a validated DSR history (n_trials=27 anchor in bot_state) is misleading:
the honest DSR denominator was calibrated for 5M-only runs, not for combined runs. A
combined run is a genuinely new "trial" but is treated as a continuation of the 5M
trial pool.

**Estimated direction:** If CRT signals have LOWER WR than 5M (plausible for a new
unvalidated strategy), blending deflates the combined WR and the operator correctly
passes on the config. If CRT has HIGHER WR (also possible given the tighter confluence
requirement), blending inflates the combined metrics and disguises that the 5M
component may have degraded. Either direction obscures the truth.

**Severity:** HIGH for statistical validity — not a lookahead bias but a metric
integrity issue that will produce misleading CPCV reports for the first CRT-enabled
runs.

---

### B-CRT-S2-H3 — `h4_end_time_ms` is H4 OPEN time, not CLOSE time — C2 condition ambiguity

**File:** `backtest.py:1311`

```python
h4_end_time_ms = c4h["times"][h4_end - 1]
```

`c4h["times"]` stores `c[0]` = Binance kline open_time (per `backtest.py:325`). The
last bar in the window is the H4 bar whose OPEN time is `h4_end_time_ms`, but this bar
may still be forming. The CRT strategy requires C2 (the sweep candle) to have swept
below/above C1's extreme. Using the OPEN time as the anchor means the C2 candle's
sweep is evaluated using H4 data (`c4h_win["lows"][-1]`) that represents the bar's
CURRENT state — which in backtest corresponds to the FINAL state since the historical
candle is fully closed.

For historical data this is fine — the candle is already closed and `c4h["lows"][-1]`
is the true low. The issue is conceptual alignment: the sub-window is anchored to the
H4 OPEN time, not the H4 CLOSE time. All the downstream time comparisons (FVG
mitigation, swing lookback, MSS horizon) should anchor to the H4 CLOSE time to be
consistent with the strategy intent. This is the root cause of B-CRT-S2-C1 and
B-CRT-S2-H1.

**Severity:** HIGH (root cause of two CRITICAL/HIGH issues above). Fix in the same
pass as B-CRT-S2-C1.

---

## 4. MEDIUM Findings

### B-CRT-S2-M1 — `import bisect as _bisect_local` inside the scan loop

**File:** `backtest.py:1313`

```python
for h4_end in range(H4_WINDOW, n4):
    ...
    import bisect as _bisect_local
```

The `import bisect` statement is inside the tight scan loop (up to ~900 iterations
for 730 days of H4 data per token × 10 tokens). Python caches modules so no I/O
occurs, but the import lookup adds overhead and is confusing — `import bisect` is
already at `backtest.py:16`. This is the same module; use the top-level import
directly.

**Impact:** No bias; performance and readability concern only.

---

### B-CRT-S2-M2 — `breakeven_wr: 0.0` hardcoded in CRT signal dilutes BEW aggregates

**File:** `backtest.py:1437`

The 5M sweep path computes `plan["breakeven_wr"]` from the actual R:R geometry.
CRT sets `breakeven_wr: 0.0`. The `print_report` at `backtest.py:1568` computes:
```python
p = sum(s["breakeven_wr"] for s in sigs) / n
```
When CRT signals are present, this average is pulled toward zero — the BEW metric
becomes meaningless for the mixed pool. The operator cannot read meaningful portfolio
quality information from BEW when sources are blended.

**Impact:** Cosmetic distortion of BEW; no signal selection bias.

---

### B-CRT-S2-M3 — `sweep_type` label logic ignores 'SSL_CRT'/'BSL_CRT' in recommendations

**File:** `backtest.py:3035`

```python
label = f"{'BSL (SELL)' if sweep_type == 'BSL' else 'SSL (BUY)'}"
```

CRT signals have `sweep_type='SSL_CRT'` or `'BSL_CRT'`. The label logic falls through
to `'SSL (BUY)'` for both CRT types. `generate_recommendations` would emit misleading
"SSL (BUY) sweep underperforming" messages for BSL_CRT signals. When both CRT and 5M
signals coexist, the by-sweep groups "SSL", "SSL_CRT", "BSL", "BSL_CRT" all appear
— the per-sweep recommendation block fires on each.

**Impact:** Incorrect recommendation labels; no simulation bias.

---

### B-CRT-S2-M4 — `confidence: 10` hardcoded for all CRT signals (no OGD weighting)

**File:** `backtest.py:1425`

```python
"confidence":      10,         # CRT is high-confluence by construction
"wscore":          0.0,
```

The 5M sweep path computes confidence via a scored gate pipeline incorporating OGD
weights, template matching, and regime filters. CRT bypasses this and hardcodes
`confidence=10` for every signal. The rationale comment ("high-confluence by
construction") is a design choice, not a measured property. When the mixed pool is
analyzed by confidence level, all CRT signals cluster at conf=10 regardless of
actual setup quality variation.

This also means the `confidence × wscore` product used in CPCV's `score_func` gives
CRT signals identical weights regardless of quality. A mediocre CRT setup with
borderline confluence gets the same weight as a strong one.

**Impact:** MEDIUM — statistical validity concern for the confidence-stratified
analysis layers.

---

### B-CRT-S2-M5 — CPCV DSR n_trials undercount (B-CRT-S2-C2 secondary effect)

**File:** `backtest.py:3511-3562`

Even without the missing hash fields (B-CRT-S2-C2), the DSR n_trials logic at line
3556-3562 adds `+ 1` for "this pending run." When CRT is enabled, the pending run
uses the same `config_hash` as any prior CRT-disabled run with the same base parameters.
`COUNT(DISTINCT config_hash)` does not increment. The `cumulative_min_trials=27` seed
provides a floor, but if the operator has been running CRT trials, the true trial count
is higher than the seeded value. The DSR passes more easily than it should.

**Impact:** Optimistic DSR during the first phase of CRT experimentation.

---

## 5. LOW Findings

### B-CRT-S2-L1 — Session 1 CRITICAL findings confirmed FIXED (regression check)

**Verified in current `crt_engine.py`:**
- C-CRT-1 (mitigation key): FIXED — `key = (c1_time, round(c1_high, 6), round(c1_low, 6))`
  at `crt_engine.py:288`. Comment at `:282-287` correctly explains the fix.
- C-CRT-2 (dual MSS implementations): FIXED — `score_ict_mss(...)` called directly
  at `crt_engine.py:310-320` and `:353-363`; `_approx_mss_bar` is absent from the file.
- M-CRT-1 (dual-extreme skip): FIXED — guard at `crt_engine.py:298-299`.
- H-CRT-1 (FVG overlap zone): FIXED — `zone_high/zone_low` split at `crt_engine.py:133-137`.
- H-3 (mss_bar+1 probe): FIXED — probe reduced to `(mss_bar_5m-1, mss_bar_5m)` at `:142`.
- M-2 (OB computed once per call): FIXED — hoisted to `crt_engine.py:261-264`.
- M-CRT-6 (time-unit check): FIXED — type-equality guard at `crt_engine.py:250-253`.
- M-CRT-2 (validation school knob): FIXED — `H4_CRT_VALIDATION_SCHOOL` env var at `:76-78`.

No regressions of Session 1 critical fixes were detected.

---

### B-CRT-S2-L2 — `ev_score`/`ev_sample_n` absent from CRT signal dict; contributes to OBSERVE tier

**File:** `backtest.py:1419-1471`

CRT signals lack `ev_score` and `ev_sample_n` fields. The report code at `:1851-1858`
uses `.get(..., 0)` defaults so no crash occurs. All CRT signals bucket into the "OBSERVE"
EV tier (n=0). This is technically correct (no historical EV data exists for CRT) but
inflates the OBSERVE tier count when mixed with 5M signals. Minor cosmetic issue.

---

### B-CRT-S2-L3 — H4_CRT_VALIDATION_SCHOOL env var read but never acted upon (Session 2 regression-risk)

**File:** `crt_engine.py:70-78` — constant defined and range-validated but the
code inside `detect_h4_crt` never branches on `H4_CRT_VALIDATION_SCHOOL`. The "strict"
path (requiring `c2.close` inside C1 range) is documented as "v2 work." The operator
document comments note this at `:70-76`. Not a bug today (v1 is flexible-only) but
the constant existing without behavioral effect is a footgun if Session 3 assumes
strict mode is wired.

---

### B-CRT-S2-L4 — Session 1 H-CRT-2 and H-CRT-3 (OB displacement threshold / same-direction break) NOT fixed

**File:** `ict_engine.py:863` (threshold), `:944-948` (break logic)

Session 1 audit rated these HIGH. Session 1's CONDITIONAL GO recommendation required
only C-CRT-1 and H-CRT-3 to be fixed before integration. H-CRT-3 (OB same-direction
break bug in `detect_ict_order_block`) is NOT fixed — the `break` at `:947-948` is
still present. The impact is that OB confluence is often unavailable (falls back to
FVG-only), which weakens the "OB is primary confluence" article intent but does NOT
produce lookahead bias. Given the M-2 fix (OB precomputed once per call) and H-CRT-1
fix (tighter overlap zone), the OB path is now more selective anyway. Still OPEN as
per Session 1.

H-CRT-2 (0.5% displacement threshold too low for H4) remains unfixed. Not a bias
issue; an overfit risk (too many weak OBs qualify).

**Classification:** STILL OPEN (SKIPPED). Not re-escalated — severity unchanged from
Session 1.

---

## 6. Per-Section Verdict Matrix

| # | Check | Verdict | Notes |
|---|-------|---------|-------|
| 1 | Lookahead bias in sliding window (c4h_win) | PARTIAL FAIL | c4h bars are correctly closed; but sub-window includes future 5M bars via +60 headroom (B-CRT-S2-C1) |
| 2 | FVG qualification in c5m_win | FAIL | mitigation scan reads future headroom bars — B-CRT-S2-C1 |
| 3 | Swing computation (find_ict_swings) | PARTIAL FAIL | Future +60 bars change swing confirmability near sweep_5m_idx — B-CRT-S2-H1 |
| 4 | MSS horizon scan (score_ict_mss) | PASS | scan bounded to sub-window length; future bars inside window are valid post-C2 5M bars by design (Wyckoff school) |
| 5 | Mitigation set isolation (consumed) | PASS | fresh set per token call, persistent across scan iterations, keyed on timestamp (C-CRT-1 fix confirmed) |
| 6 | Forward-scan window correctness | PASS | FORWARD_BARS guard arithmetic correct; future window is exactly FORWARD_BARS when guard passes |
| 7 | Triple-barrier label consistency | PASS | t1_bars=FORWARD_BARS matches len(future) by guard invariant |
| 8 | Realized R-multiple formulas | PASS | WIN→TP3/SL, PARTIAL_TP2→TP2/SL, PARTIAL_TP1→TP1/SL, LOSS→-1.0; consistent with check_outcome |
| 9 | DSR pool / n_trials contamination | FAIL | ENABLE_H4_CRT absent from config_hash — B-CRT-S2-C2 |
| 10 | Downstream report/DB compatibility | PASS (with cosmetic issues) | No crashes; BEW dilution (M2), sweep_type label (M3) are cosmetic |

---

## 7. Statistical Validity Summary

- **Total CRT backtest trades:** Cannot determine without runtime data; by design the
  CRT scanner should produce fewer signals than 5M sweep (tighter confluence). Estimate:
  5-15 signals per 365d backtest based on H4 frequency × filtered confluence rate.
- **Combined pool size (5M + CRT):** If CRT adds <15 signals to an existing n=43, the
  combined pool WR is dominated by 5M signals. The CPCV improvement, if any, is
  statistically meaningless at this sample size.
- **Sample size verdict for CRT-only analysis:** TOO SMALL. A separate CRT CPCV run
  would need n≥30 to be interpreted — not achievable with 365d data at H4 granularity.
- **Parameter count vs sample size:** CRT adds 4 env-configurable parameters
  (C2_LOOKBACK, MSS_HORIZON, OB_SCAN_LOOKBACK, VALIDATION_SCHOOL). At n<30 CRT signals
  this ratio is >4/30 — overfitted by construction. The CPCV WR std would be high.
- **Out-of-sample validation for CRT:** Absent. The 5M baseline has HELD_OUT_DAYS
  lockbox (C2 RESOLVED); CRT shares the same split but has no independent validation.

---

## Cross-Domain Observations

**Observation 1:** The root cause of B-CRT-S2-C1 is that `c4h["times"]` stores H4
OPEN times, not CLOSE times. The live scanner uses a rolling live-candle approach
where the current H4 bar's close time is wall-clock now. Backtest must explicitly
compute close time = open_time + 4h. The `docs/LIVE_BACKTEST_PARITY_ROADMAP.md`
should document this H4 time-anchor discrepancy as a Phase A/B item.
**Relevant agent:** `live-backtest-consistency-checker`
**Reason:** In live, `c2_time` = current H4 bar OPEN time is used the same way. The
`_find_5m_bar_after(c5m_times, c2_time)` correctly finds bars AFTER C2 open — which
is intentional for the Wyckoff entry. But the FVG mitigation in the live scanner
also sees post-C2-open closes, meaning the FVG bias might also affect live detection
(a different angle of the same issue).

**Observation 2:** The blended CPCV pool (B-CRT-S2-H2) will make it impossible to
distinguish CRT contribution from 5M contribution in the promotion gate. The
`promote_baseline.py --auto` 8-criteria gate uses the combined CPCV WR mean; this
gate was calibrated on 5M-only runs. An auto-promotion to a CRT-enabled baseline
using a 5M-calibrated gate is not statistically warranted.
**Relevant agent:** `validation-methodology-auditor`
**Reason:** The cross-config `sr_trial_std` in `bot_state` was computed from 5M-only
runs. Using it as the DSR denominator for a CRT-blended run inflates DSR (the std
of OOS Sharpes for 5M runs is a biased estimator for a mixed pool). Recommend blocking
auto-promotion when `ENABLE_H4_CRT=1` until a CRT-specific sr_trial_std is built.

---

## Proactive Improvement Suggestions

**Suggestion 1:** Anchor sub-window to H4 CLOSE time, not H4 OPEN time.
**Why:** Eliminates B-CRT-S2-C1 (FVG mitigation lookahead) and B-CRT-S2-H1 (swing
contamination) in one change. Formula: `h4_close_time_ms = c4h["times"][h4_end-1] + 4 * 3600 * 1000`.
**Impact:** HIGH **Effort:** Simple

**Suggestion 2:** Add `ENABLE_H4_CRT` and sibling env knobs to `_compute_run_config_hash()`.
**Why:** Closes B-CRT-S2-C2 — restores DSR n_trials integrity and Pareto-archive
uniqueness for CRT experiments.
**Impact:** HIGH **Effort:** Simple

**Suggestion 3:** Add a separate CPCV report for `source='H4_CRT'` signals when
`ENABLE_H4_CRT=1`.
**Why:** Closes B-CRT-S2-H2 — provides honest per-source attribution. The combined
CPCV is valid as a portfolio-level metric but cannot substitute for per-source
validation. Filter `_tune_sigs` by source, run `cpcv_summary` twice, print both.
**Impact:** HIGH **Effort:** Simple

**Suggestion 4:** Block auto-promotion when `ENABLE_H4_CRT=1` until CRT-specific
`sr_trial_std` is built.
**Why:** The honest DSR denominator (`sr_trial_std_honest`) was calibrated on 5M-only
runs. Using it for mixed CRT runs gives a false pass. Add a check in
`promote_baseline.py --auto`: if `ENABLE_H4_CRT=1`, require a CRT-specific std
(or refuse auto-promotion with an explicit REQUIRES_MANUAL note).
**Impact:** HIGH **Effort:** Simple

**Suggestion 5:** Compute `breakeven_wr` for CRT signals from actual SL/TP geometry.
**Why:** Closes B-CRT-S2-M2. CRT has an entry, SL, and TP1 — BEW is `SL_pct / (SL_pct + TP1_pct)`.
This is the same formula the 5M path uses inside `compute_ict_trade_plan`. One line.
**Impact:** LOW **Effort:** Simple

