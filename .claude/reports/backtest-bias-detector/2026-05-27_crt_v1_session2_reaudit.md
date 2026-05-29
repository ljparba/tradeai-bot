# CRT v1 Session 2 — Re-Audit After Options B + E

**Branch:** `experiment/crt-h4-signal-source`
**Commits reviewed:** `76fcafb` (Option B) + `2c82d7d` (Option E)
**Prior audit:** `2026-05-27_crt_v1_session2.md` @ `3d47c77`
**Date:** 2026-05-27
**Scope:** Closure verification of all 10+ items claimed fixed; spot-checks 1-4; new bias scan.

---

## 1. Executive Summary

**Overall verdict: MOSTLY-CLEAN**

Options B and E land all claimed fixes correctly. The two CRITICAL lookahead bias findings
(B-CRT-S2-C1 + collapse H1/H3) and the config_hash integrity finding (B-CRT-S2-C2) are
confirmed closed. All 7 HIGH and 5 MEDIUM items claimed in the operator's summary are
verified in place. Spot-checks 1-4 all pass with one caveat (see below).

One new LOW finding is introduced by Option E: `CRT_FORWARD_BARS` (the new env-overridable
forward-window knob) is absent from `_compute_run_config_hash()`. This is the same collision
pattern that C2 fixed for the other CRT knobs. Impact is limited because the explorer does
not currently tune `CRT_FORWARD_BARS`, but it is a latent DSR integrity gap.

The previously-flagged open issue `B-CRT-S2-H2` (blended CPCV pool, no per-source
attribution) was not claimed as fixed and is confirmed still open. At MEDIUM severity in the
current state (CRT is default-OFF), it becomes HIGH the moment any CRT-enabled run is
considered for promotion.

The branch is ready for a first CRT-enabled backtest run. The operator should treat the
result as exploratory evidence, not a promotion candidate, until H2 per-source CPCV
is addressed.

---

## 2. Closure Verification Matrix

| ID | Description | Status | Evidence |
|----|-------------|--------|---------|
| B-CRT-S2-C1 | H4 open-time lookahead via +60 bar headroom | CLOSED | `backtest.py:1447-1451` — anchor changed to `h4_open_time_ms + CRT_H4_BAR_DURATION_MS`; headroom tightened to `+H4_CRT_MSS_HORIZON + CRT_5M_HEADROOM_BUFFER` (+35 bars) |
| B-CRT-S2-C2 | ENABLE_H4_CRT absent from config_hash | CLOSED | `backtest.py:3492-3500` — 5 CRT env knobs added: ENABLE_H4_CRT, H4_CRT_DISABLED_TOKENS (sorted+normalized), H4_CRT_C2_LOOKBACK, H4_CRT_MSS_HORIZON, H4_CRT_VALIDATION_SCHOOL |
| B-CRT-S2-H1 | Swing computation on future-contaminated sub-window | CLOSED | Root cause was C1 (open-time anchor); closing C1 also closes H1. Confirmed no residual leakage in sub-window construction |
| B-CRT-S2-H2 | Blended CPCV pool — no per-source attribution | NOT-CLOSED | Not claimed in Option B/E scope. No per-source CPCV block found anywhere in `backtest.py`. Severity remains MEDIUM while CRT is default-OFF; escalates to HIGH on first CRT-enabled promotion attempt |
| B-CRT-S2-H3 | h4_end_time_ms was H4 OPEN not CLOSE | CLOSED | Same root cause as C1; C1 fix directly resolves this |
| H-CRT2-1 | No SL buffer on CRT sweep wick | CLOSED | `backtest.py:1513-1516` — `raw_wick * (1.0 - ICT_SL_BUFFER_PCT)` for BUY, `raw_wick * (1.0 + ICT_SL_BUFFER_PCT)` for SELL |
| H-CRT2-3 | No session/killzone filter on CRT entries | CLOSED | `backtest.py:1487` — `if ts.hour not in config.liquid_hours: continue` |
| H-CRT2-4 | No 4H bias gate on CRT entries | CLOSED | `backtest.py:1495-1508` — `get_ict_4h_bias()` called on `c4h_win` (data-cutoff-correct); gates via `config.bias_4h_gate` with strict/loose/none modes |
| H-1 (H-CRT2-sig) | c1h parameter in scanner signature | CLOSED | `backtest.py:1369` — signature is `run_backtest_token_h4_crt(token, c5m, c4h, config=None)`; caller at line 3677 confirmed |
| H-3 (constants) | Magic numbers in CRT scanner | CLOSED | `backtest.py:215-220` — six named module constants: CRT_H4_WINDOW_BUFFER, CRT_5M_WINDOW_SIZE, CRT_5M_HEADROOM_BUFFER, CRT_H4_BAR_DURATION_MS, CRT_TP2_RR, CRT_TP3_RR |
| H-4 (rejections) | Scanner did not return rejection counts | CLOSED | `backtest.py:1639-1643` — returns `(signals, rej)` tuple; caller at `3685-3686` aggregates into `_GLOBAL_REJECTIONS` with `crt_` prefix |
| M-1 | import bisect inside loop | CLOSED | `backtest.py:16` — top-level import; loop at `1449` uses `bisect.bisect_right` directly |
| M-2 | breakeven_wr hardcoded 0.0 | CLOSED | `_compute_crt_trade_economics()` at `backtest.py:278-281` — `abs(net_sl) / (abs(net_sl) + net_tp1)`. Formula verified correct (EV=0 identity passes) |
| M-3 | BSL_CRT/SSL_CRT labels in generate_recommendations | CLOSED | `backtest.py:3212-3215` — explicit elif branches for BSL_CRT and SSL_CRT with correct directional labels |
| M-4 | confidence=10 hardcoded for all CRT signals | CLOSED | `_crt_quality_to_confidence(mss_q, fvg_q)` at `backtest.py:299-315` — maps quality sum to [6,10] range |
| M-5 | DSR n_trials undercount (secondary of C2) | CLOSED | C2 fix adds ENABLE_H4_CRT to hash; CRT-enabled and CRT-disabled runs now produce distinct hashes; COUNT(DISTINCT) increments correctly |
| M-6 | Programmatic INSERT via hardcoded string | CLOSED | `_BACKTEST_SIGNALS_COLS` (48 cols) + `_backtest_signal_to_row()` at `backtest.py:3291-3341`; column count verified programmatically: 48 == 48 |
| M-CRT2-2 | FORWARD_BARS=288 used for CRT outcome window | CLOSED | `CRT_FORWARD_BARS = int(os.environ.get("CRT_FORWARD_BARS", "576"))` at `backtest.py:228`; data-sufficiency guard, per-signal guards, and future window all updated |

---

## 3. Spot-Check Results

### Spot-check 1: Time anchoring math — PASS

`CRT_H4_BAR_DURATION_MS = 4 * 3600 * 1000 = 14_400_000 ms` is exactly 4 hours. Verified.

The headroom is `H4_CRT_MSS_HORIZON (default 30) + CRT_5M_HEADROOM_BUFFER (5) = 35 bars
= 175 minutes = ~2h55m`. This is sufficient for `score_ict_mss` which scans
`range(sweep_bar + 1, min(sweep_bar + horizon + 1, n))` — a maximum of `horizon=30` bars.
The `+5` buffer accommodates the offset between the sub-window-relative `sweep_5m_idx` and
the start of the actual MSS scan range. No under-provisioning.

`bisect_right(c5m["times"], h4_close_time_ms)` correctly places the boundary: it returns
the index of the first 5M bar whose open_time strictly exceeds the H4 close. The 5M bar
that opens exactly at H4 close time is included (bisect_right semantics), which is correct —
that bar is the first bar of the post-H4 period and is valid for MSS detection.

### Spot-check 2: CRT_FORWARD_BARS = 576 lookahead risk — PASS

The data-sufficiency guard at `backtest.py:1416` (`n5 < WARMUP_BARS + CRT_FORWARD_BARS`)
correctly enforces that the dataset contains enough bars for at least one valid signal.
The per-signal guards at `1474` and `1478` (`mss_bar_abs >= n5 - CRT_FORWARD_BARS - 1`,
`entry_bar >= n5 - CRT_FORWARD_BARS - 1`) ensure the forward window never exceeds `n5`.
Verified with n5=1000, fwd=576: last valid entry at bar 422, future range [423, 999),
576 bars, max index 998 < 1000. No out-of-bounds access.

The 48h forward window does NOT introduce lookahead. The forward bars are legitimately
post-entry data. The only effect is that the last 576 5M bars (48h) before the dataset
end cannot generate CRT signals — correct behavior, as outcome labeling requires 48h
of post-entry data.

### Spot-check 3: _compute_crt_trade_economics correctness — PASS

Sign conventions are correct:
- BUY: `gross_tp1 = (tp1 - entry) / entry * 100 > 0` (profit when tp1 > entry). Verified.
- BUY: `gross_sl = (sl - entry) / entry * 100 < 0` (loss when sl < entry). Verified.
- SELL: `gross_tp1 = (entry - tp1) / entry * 100 > 0` (profit when tp1 < entry). Verified.
- SELL: `gross_sl = (entry - sl) / entry * 100 < 0` (loss when sl > entry). Verified.

`net_sl = gross_sl - rt_cost_pct`: since `gross_sl < 0` and `rt_cost_pct > 0`, net_sl is
more negative than gross_sl. This correctly represents that costs increase the loss. The
same cost subtraction from `net_tp1` (positive) reduces the winner — both directions are
directionally correct.

`realized_r` LOSS branch: hardcoded `-1.0`. Correct. For any loss, `net_sl / |net_sl| = -1.0`
by identity. The hardcoded value matches what the 5M path's `_calc_realized_r` would compute
for a full stop-out.

`breakeven_wr`: `abs(net_sl) / (abs(net_sl) + net_tp1)`. Verified via EV identity:
`EV = wr * net_tp1 - (1-wr) * |net_sl| = 0` → `wr = |net_sl| / (|net_sl| + net_tp1)`.
The formula uses NET values (post-cost), which is correct — breakeven should account for
trading costs, not just gross geometry.

One minor note: when `confluence["type"] == "OB"`, `_fvg_q` is hardcoded to "NONE"
(`backtest.py:1581-1582`). The `detect_ict_order_block()` return dict does not include
a quality field, so no quality information is available. OB-confluence setups cap at
`conf=8` (MSS=HIGH + OB = 3+0 pts → 8). This is a design limitation but not a bias.

### Spot-check 4: Programmatic INSERT row builder — PASS

`_BACKTEST_SIGNALS_COLS` has 48 columns. `_backtest_signal_to_row()` returns 48 values.
Verified with manual count (confirmed programmatically). Field ordering matches exactly:
`run_id` first, `source` last. Back-compat default `s.get("source", "5M_SWEEP")` correctly
handles pre-Session-2 signal dicts. The `dr4h_location` → `dr_location` rename is handled
at the row level (`s.get("dr4h_location", "UNKNOWN")`) without requiring schema migration.

---

## 4. NEW Findings Introduced by Options B + E

### NEW-1 — `CRT_FORWARD_BARS` absent from `_compute_run_config_hash()` (LOW)

**File:** `backtest.py:228` (constant definition), `3437-3501` (hash function body)

**Mechanism:** Option E introduced `CRT_FORWARD_BARS` as an env-overridable knob
(`int(os.environ.get("CRT_FORWARD_BARS", "576"))`). The five other CRT knobs added by
Option B are correctly included in the config_hash payload (`backtest.py:3492-3500`). But
`CRT_FORWARD_BARS` was not added. Two CRT-enabled runs differing only on `CRT_FORWARD_BARS`
(e.g., 576 vs 288) will produce identical config_hash values. This is the same DSR
n_trials undercount / Pareto archive collision pattern that B-CRT-S2-C2 fixed.

**Current impact:** LOW — the autonomous explorer does not currently tune `CRT_FORWARD_BARS`
(`scripts/autonomous_explorer.py` has no reference to it). Manual operator experimentation
with this knob would undercount DSR trials.

**Fix:** Add one line to `_compute_run_config_hash()`:
```python
"CRT_FORWARD_BARS": os.environ.get("CRT_FORWARD_BARS", "576"),
```
This is the same pattern as the five other CRT knobs at lines 3492-3500.

**Prior-art classification:** NEW FINDING — not in CROSS_REF.md or prior Session 2 report.
`CRT_FORWARD_BARS` did not exist before commit `2c82d7d`.

---

## 5. Previously Open Items — Status

**B-CRT-S2-H2** (Blended CPCV pool — no per-source attribution) remains NOT-CLOSED.
Not in scope for Options B or E per the operator's fix list. No per-source CPCV block
exists in `backtest.py`. This issue does not affect the correctness of the backtest
simulation but means the CPCV WR reported for a CRT-enabled run blends two signal
populations with potentially different base rates. Severity while CRT is default-OFF:
MEDIUM (informational). Severity for a CRT-enabled promotion candidate: HIGH.

---

## 6. Cross-Domain Observations

**Observation:** B-CRT-S2-H2 (blended CPCV) means the `promote_baseline.py --auto`
8-criteria gate (calibrated on 5M-only runs) would receive a mixed-source CPCV WR for
a CRT-enabled baseline. The gate cannot distinguish whether a CPCV mean of 75%+ came
from the CRT signals, the 5M signals, or a blend.
**Relevant agent:** validation-methodology-auditor
**Reason:** The promotion gate's CPCV threshold needs a per-source clause before any
CRT-enabled config can be promoted with honest statistical coverage.

---

## 7. Recommendation

**Proceed to Session 3** with one prerequisite: add `CRT_FORWARD_BARS` to
`_compute_run_config_hash()` (2-line change, trivial effort). This can land in the same
commit as any Session 3 work.

The branch is ready for a first CRT-enabled exploratory backtest. Do not trigger
auto-promotion from any CRT-enabled result until B-CRT-S2-H2 (per-source CPCV) is
addressed. Manual review of per-source WR breakdown via the `source` column in
`backtest_signals` is a viable substitute for the interim period.

