# CRT v1 Session 2 Option S — Targeted Re-Audit
**Agent:** backtest-bias-detector
**Date:** 2026-05-27
**Branch:** experiment/crt-h4-signal-source
**Head commit:** 2c0247f (Option S)
**Prior commit audited:** 469ceeb (Option H)
**Scope:** READ-ONLY spot-check of 3 specific Option S changes

---

## 1. Executive Summary

Option S closes all 5 LOW polish items from the cumulative re-audit cleanly.
No new bias introduced. All 39 CRT/integration tests pass (5 new rejection-reason
tests added). B-CRT-S2-H2 (per-source CPCV) remains NOT-CLOSED by design —
no change in Option S. Branch is **SESSION 3 READY**.

---

## 2. Option S Closure Verification

### Item 1 — FINDING-1: config_hash assertion covers all 7 CRT knobs

**Status: CLOSED — CONFIRMED**

`tests/test_crt_backtest_integration.py:187-193` now iterates over all 7 knobs:
`ENABLE_H4_CRT`, `H4_CRT_DISABLED_TOKENS`, `H4_CRT_C2_LOOKBACK`,
`H4_CRT_MSS_HORIZON`, `H4_CRT_VALIDATION_SCHOOL`, `CRT_FORWARD_BARS`,
`H4_CRT_OB_SCAN_LOOKBACK`. Assertion uses `inspect.getsource()` against the
production `_compute_run_config_hash` function — catches any future removal.
Test confirmed passing.

### Item 2 — `_clean_crt_env()` hardening

**Status: CLOSED — CONFIRMED**

`tests/test_crt_backtest_integration.py:27-31`: cleanup tuple now includes
`CRT_FORWARD_BARS`, `CRT_TP2_RR`, `CRT_TP3_RR` alongside the prior 6 keys.
Full set: 9 env vars popped. Latent test-ordering risk eliminated.

### Item 3 — Per-gate rejection counter split

**Status: CLOSED — CONFIRMED. No double-counting. Gate order is CORRECT.**

`crt_engine.py:507-552` — `crt_trade_rejection_reason()` gate evaluation order:

| Step | Condition | Returns |
|------|-----------|---------|
| 1 | `net_tp1 <= 0` | `"fees_kill"` |
| 2 | `(gross_tp1 + risk_pct) <= 0` | `"invalid_inputs"` |
| 3 | `bew > MAX_BREAKEVEN_WR` | `"bew_too_high"` |
| — | defensive fallthrough | `"unknown"` |

This mirrors `compute_crt_trade_economics` (lines 459-472) exactly: same
formula, same guard ordering, same sentinel values. First-failing gate is
correctly identified.

**Backtest call site** (`backtest.py:1488-1504`): `rt_cost` is computed once
at line 1488 as `TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100` and
passed to both `compute_crt_trade_economics` (line 1492) and
`crt_trade_rejection_reason` (line 1500). Identical value — no divergence
possible.

The `if econ is None:` branch calls the helper exactly once, increments one
`rej[_key]` counter, then `continue`. No double-counting path exists.

**CRT_TP2_RR / CRT_TP3_RR / CRT_FORWARD_BARS constant move** (`crt_engine.py:83-85`):
constants now defined via `_env_float` / `_env_int` with correct defaults
(1.5, 2.0, 576). `backtest.py:128` imports them from `crt_engine`. No local
definition remains in `backtest.py` (confirmed: grep for `^CRT_TP2_RR` etc.
returns nothing). Values byte-identical to prior definitions.

---

## 3. NEW Issues Introduced by Option S

**None found.**

The only structural observation worth documenting is a reachability nuance
in `crt_trade_rejection_reason` that the test file already acknowledges:

The `"invalid_inputs"` path (`gross_tp1 + risk_pct <= 0`) at line 545 is
unreachable in practice for any non-degenerate trade where net_tp1 > 0
(gate 1 passes). For `gross_tp1 + risk_pct <= 0` to hold while `net_tp1 > 0`,
you would need `gross_tp1 > rt_cost_pct` while simultaneously
`gross_tp1 <= -risk_pct` — impossible for any real trade where risk_pct > 0.
The test at line 509-520 explicitly documents this and verifies `"fees_kill"`
is the actual catch-all for degenerate inputs. This is NOT a bug: the gate
exists as a zero-division guard identical to the one in the main function,
and the helper correctly mirrors it. No bias implication.

---

## 4. B-CRT-S2-H2 Status

**NOT-CLOSED — as expected. No change in Option S.**

Blended CPCV (all signals pooled regardless of source) remains in place.
`validation.py` and the CPCV call in `backtest.py` have no per-source
stratification logic. The issue as stated in the cumulative re-audit stands:
when H4_CRT is enabled, the combined CPCV reflects a mix of 5M-sweep and
H4_CRT outcomes. If H4_CRT produces structurally different base rates than
5M-sweep, the blended CPCV WR will not represent either source accurately.

**Severity remains LOW-MEDIUM** (quantitative impact unknown until H4_CRT
produces live backtest signals). **Deferred to Session 3+ by design.**
No change to prior assessment.

---

## 5. Final Session 3 Readiness

| Check | Result |
|-------|--------|
| All 7 CRT knobs in config_hash assertion | PASS |
| `_clean_crt_env()` covers all 9 env vars | PASS |
| Gate order in rejection helper matches main fn | PASS |
| `rt_cost` value identical at both call sites | PASS |
| No double-counting in rejection counter | PASS |
| CRT constants in shared module (crt_engine.py) | PASS |
| 39 CRT/integration tests passing | PASS (39/39) |
| 0 CRITICAL / 0 HIGH / 0 MEDIUM actionable remaining | CONFIRMED |
| B-CRT-S2-H2 per-source CPCV | NOT-CLOSED (Session 3+, accepted) |

**VERDICT: OPTION S CLOSES ALL CLAIMED ITEMS CLEANLY. BRANCH IS SESSION 3 READY.**
