# CRT v1 — Session 2 Option S Targeted Re-Audit

**Branch:** `experiment/crt-h4-signal-source` @ `2c0247f` (Option S, 8 commits)
**Prior baseline:** `469ceeb` (Option H — maintainability 8.5/10)
**Reviewer:** professional-code-quality-reviewer
**Date:** 2026-05-27
**Mode:** READ-ONLY — no code modified.

---

## 1. Executive summary + updated maintainability score

Option S is a tight, surgical polish commit. It closes the two highest-value
LOW items (A docstring drift, D opaque gate counter) from the prior
cumulative re-audit with zero behavioral change to the signal pipeline,
plus an opportunistic structural improvement (moving `CRT_TP2_RR` /
`CRT_TP3_RR` / `CRT_FORWARD_BARS` from `backtest.py` to `crt_engine.py`
to remove one more live/BT drift surface ahead of Session 3).

The 209-LOC diff (4 files) is well-commented — every change references
the finding ID it closes. The new helper (`crt_trade_rejection_reason`)
follows the same module-local convention as `compute_crt_trade_economics`.
All 39 CRT tests pass (`test_crt_engine.py` 26 + `test_crt_backtest_integration.py` 13).

**Updated maintainability score: 8.7/10** (up from 8.5).

+0.2 for: LOW-A closed with verifiable input→output table; LOW-D closed
with per-gate telemetry surface; 3 more shared constants in `crt_engine.py`;
`_clean_crt_env` expanded to all 9 env knobs.

**Three most important findings:**
1. NO REGRESSIONS — every prior closure (Sessions 1 + 2 Options B/E/H)
   verifies still closed at HEAD `2c0247f`.
2. The new docstring table is mathematically correct — all 7 rows verified
   by hand against `6 + (pts * 2) // 3`.
3. ZERO new critical/HIGH/MEDIUM issues. Two cosmetic NITs only.

---

## 2. LOW-A and LOW-D closure verification

### LOW-A — `crt_quality_to_confidence` docstring drift — CLOSED

**Evidence:** `crt_engine.py:553-583` removes the fictitious "4-5/2-3/0-1
pts" claim and adds two explicit tables: grade→points (matching `q_score`
at `:586` byte-identically), and points→confidence.

**Manual verification of every row against `6 + (pts * 2) // 3`:**
- pts=0 → 6 ✓   pts=1 → 6 ✓   pts=2 → 7 ✓   pts=3 → 8 ✓
- pts=4 → 8 ✓   pts=5 → 9 ✓   pts=6 → 10 ✓

All 7 rows correct. Output-clamp note `max(6, min(10, …))` also present.
Docstring is now sufficient and accurate.

### LOW-D — Per-gate rejection reason — CLOSED

**Evidence:**
- New helper at `crt_engine.py:507-551`
- Backtest call-site at `backtest.py:1495-1503` — counter key now
  `f"crt_economics_{reason}"`. Old `crt_economics_gate` key is gone
  (verified by grep — zero remaining references).

**Helper design quality:**
- Pure function — no env reads, no I/O, deterministic.
- Gate-evaluation order at `:540, 545, 549` mirrors the parent helper's
  order at `:460, 466, 471` byte-identically. First-firing gate is reported,
  matching "single root cause" semantic.
- `"unknown"` default at `:551` is sensible defensive coding. If it ever
  surfaces in D2 telemetry, it flags a code-bug regression — useful signal.
- Docstring at `:514-528` is sufficient: input/output spec, all 4 returns
  listed, gate-order mirror documented, caller usage example included.

**Tests (`TestCrtTradeRejectionReason`, 5 tests):**
- `test_fees_kill_reason` — same fixture as
  `TestCrtEconomicsHelper.test_returns_none_when_fees_kill_trade`
  (entry=100, sl=99, tp1=100.2, rt=0.5) ✓
- `test_bew_too_high_reason` — same fixture as
  `test_returns_none_when_breakeven_wr_too_high` (entry=100, sl=97,
  tp1=100.5, rt=0.1) ✓
- `test_invalid_inputs_reason` — degenerate input; test correctly asserts
  `fees_kill` fires first (acknowledges unreachability — see NIT-1)
- `test_bearish_direction` — SELL fixture, asserts `bew_too_high` ✓
- `test_returns_unknown_when_no_gate_fires` — healthy trade, defensive ✓

**Coverage: complete.** All 4 return paths exercised; fixtures align with
original economics tests so the parity contract is visible.

`pytest tests/test_crt_engine.py::TestCrtTradeRejectionReason` — 5/5 pass.

---

## 3. NEW issues from Option S

### NIT-1 — `invalid_inputs` rejection branch mathematically unreachable

**File:** `crt_engine.py:545-547`
**Severity:** Cosmetic.
The branch requires `net_tp1 > 0` AND `(gross_tp1 + risk_pct) ≤ 0`. Since
`net_tp1 > 0` implies `gross_tp1 > rt_cost ≥ 0`, and `risk_pct ≥ 0`, the
sum is necessarily > 0. The test `test_invalid_inputs_reason` correctly
acknowledges this by asserting `fees_kill` fires first.
**Risk:** None. Both `invalid_inputs` and `unknown` are defensive returns
that should never appear in production. Leave as-is — removing them would
lose the safety net against future refactors that change gate ordering.

### NIT-2 — `_env_float` helper triplicated across modules

**Files:** `crt_engine.py:56`, `ict_engine.py:19`, `config.py:71`
**Severity:** Cosmetic / pre-existing pattern.
Option S added `_env_float` to `crt_engine.py` following the same
module-local convention already used by `_env_int`/`_env_str`. Not new
debt — Option S followed established layout. Defer to a future
`env_utils.py` extraction if needed.

### Constant move (CRT_TP2_RR / TP3_RR / FORWARD_BARS) — clean

No NEW issue. The 3 constants at `crt_engine.py:83-85` are imported by
`backtest.py:128`; the removed block at the old location is replaced by
a clear pointer comment. All 7 usage sites in `backtest.py` reference
the import correctly. No leftover dead references.

### Counter-key proliferation — no dead branches in scanner

Scanner produces 3 (rarely 4) new counter keys at runtime:
`crt_economics_fees_kill`, `crt_economics_bew_too_high`,
`crt_economics_invalid_inputs`, `crt_economics_unknown`. Old key gone.
**Verify before Session 3:** any tracker dashboard that queried
`crt_economics_gate` must update to aggregate the new keys.

---

## 4. Final pre-Session-3 checklist

### MUST-DO — all DONE

| Item | Status |
|------|--------|
| LOW-A docstring fixed | DONE — table verified accurate |
| LOW-D per-gate counters | DONE — new helper + 5 tests pass |
| Constants importable from crt_engine | DONE — 5 names available |
| All env knobs in config_hash | DONE — 7 keys at `:3434-3451` |
| `_clean_crt_env` covers all 9 env keys | DONE at `:24-29` |
| All 39 CRT tests pass | DONE — verified live |

### SHOULD-DO before Session 3 (deferred from Option S)

| Item | Recommendation |
|------|----------------|
| LOW-B (`test_crt_engine.py` 585 lines, was 512) | Split file BEFORE adding live-side tests in Session 3 — otherwise will hit ~750 LOC. Recommended split: `test_order_block.py` + `test_crt_detection.py` + `test_crt_helpers.py`. Mechanical, one commit. |
| LOW-C (redundant tuple-length test) | Optional. Suite runs in 0.44s; collapse only if convenient. |
| Tracker dashboard sanity-check | Verify `tracker.py` / `tracker_html.py` don't query the now-removed `crt_economics_gate` key. 15-min audit. |

### Recommended Session 3 sequence

1. Pre-flight: audit tracker for `crt_economics_gate` references.
2. Split test file (LOW-B) in a mechanical commit before any live wiring.
3. Add live integration in `crypto_alert.py` — import same names that
   `backtest.py:121-131` imports.
4. Mirror tests for live path (new file `test_crt_live.py`).
5. PAPER smoke-test with `ENABLE_H4_CRT=1` for 24h before further audit.

---

## 5. Verdict

**APPROVED for merge + Session 3 entry.**

Option S is a clean, low-risk polish commit. Maintainability is now
**8.7/10**; the branch is structurally ready for live-side integration.
The two deferred LOW items (B file size, C test redundancy) are cosmetic
and can be cleaned up at the top of Session 3 in a mechanical commit
before live wiring begins.

No CRITICAL, HIGH, or MEDIUM findings. Two cosmetic NITs documented for
record-keeping only — both pre-existing pattern or defensible-by-design.
