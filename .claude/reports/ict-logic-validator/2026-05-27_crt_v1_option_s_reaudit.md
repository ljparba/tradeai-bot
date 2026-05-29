# CRT v1 Session 2 Option S — Targeted Re-Audit

**Date:** 2026-05-27
**Auditor:** ict-logic-validator
**Branch:** experiment/crt-h4-signal-source
**Commit:** 2c0247f (Option S) — diff baseline 469ceeb (Option H)
**Scope:** Hygiene-only verification (no detection logic should change)
**Prior cumulative re-audit:** 88/100 — GO for Session 3

---

## 1. Executive Summary

Option S is **confirmed hygiene-only**. Zero ICT detection logic changes.
All four verification points pass:

| Verification | Result |
|---|---|
| CRT_TP2_RR default = 1.5R | PASS — unchanged |
| CRT_TP3_RR default = 2.0R | PASS — unchanged |
| CRT_FORWARD_BARS default = 576 (48h) | PASS — unchanged |
| crt_trade_rejection_reason introduces NO new gates | PASS — pure mirror |
| crt_quality_to_confidence q_score map + formula | PASS — byte-identical |

**Final ICT conformance score: 88/100** (unchanged from cumulative re-audit; Option S touches only diagnostics + module layout, not ICT semantics).

---

## 2. Hygiene-Only Verification

### 2.1 Constant defaults unchanged (move-only refactor)

Pre-Option S (commit 469ceeb, backtest.py:223-232):
```
CRT_TP2_RR                 = 1.5
CRT_TP3_RR                 = 2.0
CRT_FORWARD_BARS           = int(os.environ.get("CRT_FORWARD_BARS", "576"))
```

Post-Option S (crt_engine.py:81-83):
```
CRT_TP2_RR       = _env_float("CRT_TP2_RR", 1.5)
CRT_TP3_RR       = _env_float("CRT_TP3_RR", 2.0)
CRT_FORWARD_BARS = _env_int("CRT_FORWARD_BARS", 576)
```

All three default values are byte-identical. The change is a relocation
from `backtest.py` (live/BT-asymmetric module) to `crt_engine.py` (shared
module), which is the correct architectural fix flagged by the LBC auditor —
Session 3's `crypto_alert.py` will now import the same source-of-truth as
the backtest. Net effect on ICT logic: zero. Net effect on live/BT parity
risk: improved.

Bonus: CRT_TP2_RR + CRT_TP3_RR gain env-overridability (previously hard-coded
floats in backtest.py). This is a discipline improvement and matches the
project's "every tunable is env-overridable" convention. Default-only behavior
unchanged — operators not setting the env knob see identical 1.5R / 2.0R.

### 2.2 `crt_trade_rejection_reason` is a pure mirror (no new decision logic)

Reading the helper (crt_engine.py:507-549) against `compute_crt_trade_economics`
(crt_engine.py:440-472), the gate sequence is identical:

| Gate | compute_crt_trade_economics | crt_trade_rejection_reason |
|---|---|---|
| 1. fees_kill | `if net_tp1 <= 0: return None` (L460) | `if net_tp1 <= 0: return "fees_kill"` |
| 2. invalid_inputs | `if (gross_tp1 + risk_pct) <= 0: return None` (L466) | `if (gross_tp1 + risk_pct) <= 0: return "invalid_inputs"` |
| 3. bew_too_high | `if bew > MAX_BREAKEVEN_WR: return None` (L471) | `if bew > MAX_BREAKEVEN_WR: return "bew_too_high"` |

Same gross-% computation, same `round(gross_tp1 - rt_cost_pct, 3)` net_tp1,
same `risk_pct = abs(gross_sl)`, same `bew = (risk_pct + rt_cost_pct) / (gross_tp1 + risk_pct)`
formula, same `MAX_BREAKEVEN_WR = 0.60` threshold. The helper introduces
**zero new gates** — it only re-evaluates the same conditions in the same
order to return a descriptive string instead of None. This is precisely
the "describe which gate fired" pattern requested.

Helper-only artifacts (non-ICT):
- Returns `"unknown"` defensive fallback (never reached if caller invokes
  only on None branch — test `test_returns_unknown_when_no_gate_fires`
  documents this).
- Caller integration at backtest.py:1495-1502 splits the previously-opaque
  `crt_economics_gate` rejection counter into 3 per-gate counters
  (`crt_economics_fees_kill` / `crt_economics_bew_too_high` /
  `crt_economics_invalid_inputs`). Diagnostic surfacing only — does NOT
  change which trades pass/fail. A trade that returned None before still
  returns None now; only the rejection-counter bucket label differs.

### 2.3 `crt_quality_to_confidence` mapping unchanged

Pre-Option S (Option H commit 469ceeb, crt_engine.py:500-502):
```
q_score = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}
pts = q_score.get(mss_quality, 0) + q_score.get(fvg_quality, 0)
return max(6, min(10, 6 + (pts * 2) // 3))
```

Post-Option S (crt_engine.py:586-588): byte-identical — same dict, same sum,
same `max(6, min(10, 6 + (pts * 2) // 3))` clamp+formula.

Only the docstring changed (Option S explicitly notes it: "docstring
rewritten to remove drift between the prior text [which described
score_ict_mss's internal 4-5/2-3/0-1 point scale] and the actual q_score
map below [which uses 0/1/2/3]"). The new docstring includes the full
pts→confidence table (0→6, 1→6, 2→7, 3→8, 4→8, 5→9, 6→10) which I
recomputed independently and matches the formula output. Confidence
output for every (mss_quality, fvg_quality) input combination is
byte-identical to Option H.

### 2.4 Test additions (5 new tests + 1 config-hash assertion expansion)

- `TestCrtTradeRejectionReason` × 5 tests verify the mirror helper
  (fees_kill, bew_too_high, bearish path, invalid_inputs documented
  as unreachable-in-practice, unknown defensive fallback).
- `test_config_hash_includes_crt_knobs` expanded to assert
  `CRT_FORWARD_BARS` + `H4_CRT_OB_SCAN_LOOKBACK` are in the config-hash
  payload (closes a latent gap flagged by NEW-1 in the cumulative re-audit).
- `_clean_crt_env` extended to clear CRT_FORWARD_BARS, CRT_TP2_RR,
  CRT_TP3_RR between tests — test-isolation hygiene only.

No new tests assert detection behavior; all are diagnostic/integration.

---

## 3. Final Verdict

**Option S is HYGIENE-ONLY. No ICT principle change. No detection logic change. No regression risk.**

- ICT conformance score: **88/100** (unchanged from cumulative re-audit)
- All four verification points: **PASS**
- Live/BT parity: **IMPROVED** (3 more constants now shared via crt_engine.py)
- Diagnostic granularity: **IMPROVED** (per-gate rejection counters)
- Test coverage: **IMPROVED** (5 new tests; config-hash assertion expanded)

**Recommendation: GO for Session 3 live integration on commit 2c0247f.**

Session 3 should:
1. Import `CRT_TP2_RR`, `CRT_TP3_RR`, `CRT_FORWARD_BARS` from `crt_engine`
   (NOT from `backtest` — the backtest re-export is for that module's
   internal use only).
2. Import `crt_quality_to_confidence` from `crt_engine` for byte-identical
   confidence stratification between live and BT.
3. Optionally use `crt_trade_rejection_reason` to surface live-side
   rejection diagnostics symmetric to the backtest counters.

No remaining ICT-domain concerns. Sign-off below for this audit cycle.
