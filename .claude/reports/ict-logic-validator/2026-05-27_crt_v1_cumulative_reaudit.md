# CRT v1 — Cumulative ICT Re-Audit (Sessions 1 + 2, all Option rounds)

**Branch:** `experiment/crt-h4-signal-source` @ `469ceeb`
**Scope:** 7 commits across Session 1 (3 commits) + Session 2 (4 commits, incl. Options B + C + E + H)
**Mode:** READ-ONLY.
**Prior reports cross-referenced:** Session-1 audit (74/100 → after Option B+C), Session-2 audit (74/100), Session-2 re-audit after B+E (79/100).

---

## 1. Executive Summary

All 16 Session-1 fixes and all 16 Session-2 fixes (across Options B + E + H) verified **CLOSED**, including the previously-open **H-CRT2-4** (4H-bias-gate inert) which the Option H NEW-2 fix correctly closes by swapping the 12-bar sub-window call to `_lookup_4h_bias(c4h, c5m["times"][entry_bar])`. The bias gate now actually fires.

The branch is in materially better ICT shape than at the close of any prior audit:

- Detection layer (`crt_engine.py`) is byte-identical to the Option-C commit other than the two new helpers appended at file end (NEW-4 helper move). Zero detection-layer regressions.
- Order Block detection (`ict_engine.py:845-970`) preserves H-CRT-3 walk-back fix.
- Scanner layer (`backtest.py:1292-1576`) gains a real economics gate (NEW-3) that matches `compute_ict_trade_plan` (3-dp rounding, BEW≤0.60, net_tp1>0), bringing CRT into structural parity with the 5M-sweep path.
- `config_hash` correctly fingerprints all 7 CRT env knobs (NEW-1 closure).
- Helper move (NEW-4) is byte-equivalent in math — verified by reading the diff: no semantic change, only file relocation + signature normalization to accept `rt_cost_pct` as an arg.

**Two NEW observations** introduced by Option H worth flagging (severity LOW — design choices, not regressions). See § 3.

**Updated conformance: 88 / 100** (+9 from the prior 79).

**Verdict: GO for Session 3. CRT v1 is ICT-correct and economically gated. Production unaffected (ENABLE_H4_CRT=0 default).**

---

## 2. Cumulative Closure Verification

### Session 1 (16 items)
| ID | What | Location | Status |
|---|---|---|---|
| C-CRT-1 | mitigation key keyed on `c1_time` (not `c1_idx`) | `crt_engine.py:289` | CLOSED — verified intact |
| C-CRT-2 | canonical `score_ict_mss` (no `_approx_mss_bar`) | `crt_engine.py:311-321, 354-364` | CLOSED — verified intact |
| H-CRT-1 | FVG/OB confluence on swept-extreme half only | `crt_engine.py:133-138, 150, 156` | CLOSED — verified intact |
| H-CRT-2 | OB displacement threshold env-overridable + 1.5% | `ict_engine.py:867` | CLOSED |
| H-CRT-3 | OB walk-back walks past same-direction candles | `ict_engine.py:921-957` | CLOSED — verified by reading loop body |
| M-CRT-1 | dual-extreme C2 skipped | `crt_engine.py:299-300` | CLOSED |
| M-CRT-2 | `H4_CRT_VALIDATION_SCHOOL` env knob plumbed | `crt_engine.py:77-79` | CLOSED |
| M-CRT-6 | time-unit cross-check on sweep anchor | `crt_engine.py:250-254` | CLOSED |
| M-CRT-7 | test tearDown env isolation | (tests) | CLOSED — operator confirmed prior |
| M-CRT-8 | thread-safety docstring | `crt_engine.py:181-187` | CLOSED |
| M-CRT-9 | T8 negative-control assertion | (tests) | CLOSED |
| M-CRT-10 | stale OB comment fix | (comment) | CLOSED |
| T10 | un-skipped via mock | (tests) | CLOSED |
| L-3 | `Optional[dict]` type hints | `crt_engine.py:36, 164, 403` | CLOSED |
| L-4 | `bisect.bisect_right` time lookup | `crt_engine.py:96` | CLOSED |
| (impl) | `key` returned for caller mitigation tracking | `crt_engine.py:346, 389` | CLOSED |

### Session 2 — Option B (2 CRITICAL + 7 HIGH)
| ID | What | Location | Status |
|---|---|---|---|
| B-CRT-S2-C1 | H4 close-time anchoring (open + CRT_H4_BAR_DURATION_MS) | `backtest.py:1370-1372` | CLOSED — verified |
| B-CRT-S2-C2 | CRT env knobs in `config_hash` | `backtest.py:3426-3434` | CLOSED |
| H-CRT2-1 | SL buffer applied (correct direction) | `backtest.py:1440-1443` | CLOSED — verified BUY pulls SL down, SELL pushes SL up |
| H-CRT2-3 | session/killzone filter applied | `backtest.py:1409-1412` | CLOSED — `liquid_hours` default range(24) is a no-op (parity-correct with 5M path) |
| H-CRT2-4 | 4H bias gate firing | `backtest.py:1422-1435` | **CLOSED** (was NOT-CLOSED in prior re-audit; Option H NEW-2 fixes) |
| H-1 | `c1h` param dropped | (signature) | CLOSED |
| H-3 | magic constants promoted | `backtest.py:219-224, 1352, 1374-1375, 1451-1455` | CLOSED |
| H-4 | scanner returns `(signals, rejections)` tuple | `backtest.py:1576` | CLOSED |
| H-3-OB | OB walk-back preserved | `ict_engine.py:921-957` | CLOSED |

### Session 2 — Option E (5 MEDIUMs)
| ID | What | Location | Status |
|---|---|---|---|
| M-2/3/4 | BEW computed / by_sweep labels / confidence | `backtest.py:1496-1525` | CLOSED |
| M-CRT2-2 | CRT_FORWARD_BARS = 576 (48h) | `backtest.py:232, 1339, 1463, 1474` | CLOSED |
| H-2 partial | helpers planned to be moved | `crt_engine.py:400-502` | CLOSED via NEW-4 |
| M-6 | programmatic INSERT | (DB writer) | CLOSED — operator confirmed prior |

### Session 2 — Option H (5 NEW findings from re-audit)
| ID | What | Location | Status |
|---|---|---|---|
| NEW-1 | `CRT_FORWARD_BARS` + `H4_CRT_OB_SCAN_LOOKBACK` in config_hash | `backtest.py:3441-3442` | CLOSED |
| NEW-2 | 4H bias gate uses `_lookup_4h_bias(c4h, ts_ms)` not 12-bar sub-window | `backtest.py:1422` | CLOSED — verified now actually filters (helper at `backtest.py:558-570` requires ≥200 bars from the FULL c4h series) |
| NEW-3 | `compute_crt_trade_economics` aligned with `compute_ict_trade_plan` (3-dp + BEW≤0.60 + net_tp1>0 gates) | `crt_engine.py:400-481` | CLOSED — verified formula byte-equivalent to ict_engine.py:819 |
| NEW-4 | helpers moved to `crt_engine.py` (importable by live + backtest) | `crt_engine.py:400-502`; `backtest.py:122-123` | CLOSED |
| NEW-5 | schema test via `:memory:` SQLite | (tests) | CLOSED — operator confirmed prior |

### Detection-layer regression spot-check (re-verified)
- `git diff main..HEAD -- crt_engine.py` shows only:
  1. New helpers at end of file (NEW-4)
  2. Wyckoff/flexible detection from Session 1
  3. `MAX_BREAKEVEN_WR` import added for the moved helper
- `git diff main..HEAD -- ict_engine.py` shows ONLY the new OB functions appended at lines 845-970. Pre-existing detection (`score_ict_mss`, `score_ict_fvg`, `find_ict_swings`, `detect_ict_sweep`, `get_ict_4h_bias`, `compute_ict_trade_plan`) is untouched.
- **Zero detection-layer regressions across all 7 commits.**

---

## 3. NEW Issues Found in This Cumulative Re-Audit

### NEW-A — Economics gate may reject many CRT setups (LOW severity, design tension)
**File:** `backtest.py:1488-1495` + `crt_engine.py:436-449`

The new `compute_crt_trade_economics` returns `None` when `net_tp1 ≤ 0` or `bew > 0.60`. For CRT, TP1 is fixed at `C1 opposite extreme` while SL is below the swept wick + buffer. If the MSS confirms DEEP inside C1's range (entry close to mid-C1), then:

- `gross_tp1 = (c1_high - entry) / entry` shrinks as entry moves up toward c1_high
- `gross_sl = (sl - entry) / entry` grows because SL sits below the swept wick (below c1_low)
- Therefore `risk_pct ≫ gross_tp1` → `bew → 1.0`, hitting the 0.60 gate

This is **correct ICT behavior** (negative-EV setups should be rejected) but **changes the CRT trial distribution** vs. Session-2 prior — the gate did not exist then. Operators running A/B comparisons between current HEAD and pre-NEW-3 CRT trials should expect a meaningful drop in CRT signal count (likely 20-40% reduction). The remaining signals will have higher mean RR.

**Recommendation:** add an instrumentation counter `rej["crt_economics_gate"]` (already done — line 1494) and surface this in D2 diagnostics so operators can see how many setups the gate trims.

### NEW-B — `_lookup_4h_bias` returns NEUTRAL for first ~200 H4 bars of the series (LOW)
**File:** `backtest.py:558-570`

The helper requires `idx >= min_bars` (default 200) and returns NEUTRAL otherwise. For CRT scans, this means the first ~33 days of any backtest window cannot have non-NEUTRAL bias. With 365-day backtests this is ~9% of the window — acceptable (signals exist, gate falls into `loose`-accepts-NEUTRAL branch). On shorter feature-branch backtests (e.g. 90-day cycles) this would be ~37% of the window — non-trivial. Not a bug, but worth noting:

**Recommendation:** when CRT-tuning at shorter horizons, document that the early-window bias gate runs effectively `none` mode. The 5M-sweep path has the identical behavior (parity-correct).

### NEW-C — OB confluences cap at confidence 8 (LOW, intentional, documented previously)
**File:** `crt_engine.py:500-502` + `backtest.py:1514-1517`

A pure-OB confluence has `fvg_quality="NONE"`, so a HIGH-MSS + HIGH-OB setup gets confidence=8 instead of 10. Flagged in prior re-audit; still present here. ICT-defensible (FVG is the more institutional pattern in classical ICT), and operator should know that OB-only setups under-report confidence vs. FVG setups of equal structural quality.

**Recommendation (defer to v2):** add `ob_quality` grading (e.g. by displacement_pct: >2% → HIGH, 1-2% → MEDIUM, <1% → LOW) and re-balance the confidence mapping so OB setups can reach 10.

---

## 4. Key ICT-correctness invariants — spot-check verification

| Invariant | Verified at | Result |
|---|---|---|
| 4H bias gate ACTUALLY fires (not NEUTRAL fallback) | `backtest.py:1422-1435` + `backtest.py:558-570` | ✓ `_lookup_4h_bias` binary-searches FULL c4h series, requires ≥200 bars, calls `get_ict_4h_bias` on last 210 bars |
| SL buffer pushed in correct direction | `backtest.py:1440-1443` | ✓ BUY: `sl = raw_wick * (1 - 0.003)` (below wick) ; SELL: `sl = raw_wick * (1 + 0.003)` (above wick) — matches ict_engine.py:757,784 |
| Session/killzone filter applied to CRT | `backtest.py:1409-1412` | ✓ `ts.hour not in config.liquid_hours: continue` — same gate as 5M path at `backtest.py:735` |
| (FVG OR OB) confluence mandatory + on swept-extreme half | `crt_engine.py:100-159` | ✓ swept-extreme zone computed from `c1_mid`; FVG overlap test at line 150; OB overlap test at line 156 |
| OB walks past same-direction candles (no early break) | `ict_engine.py:929-957` | ✓ inner loop continues on same-direction candles instead of breaking |
| Mitigation key uses timestamp (not list index) | `crt_engine.py:289` | ✓ `key = (c1_time, round(c1_high, 6), round(c1_low, 6))` |
| `compute_crt_trade_economics` 3-dp rounding matches ict_engine | `crt_engine.py:431-434` | ✓ `round(..., 3)` on net_tp1/2/3; `round(..., 2)` on net_sl (matches ict_engine.py:816,828,829,837) |
| BEW formula matches ict_engine | `crt_engine.py:445` vs `ict_engine.py:819` | ✓ identical: `(risk + rt_cost) / (tp1_gross + risk)` |
| Realized R formula correct per outcome class | `crt_engine.py:454-466` | ✓ WIN → net_tp3/|net_sl|; PARTIAL_TP2 → net_tp2/|net_sl|; PARTIAL_TP1 → net_tp1/|net_sl|; LOSS → -1.0; EXPIRED → 0.0 |
| `crt_quality_to_confidence` maps [0,6] pts → [6,10] | `crt_engine.py:500-502` | ✓ formula `max(6, min(10, 6 + (pts*2)//3))` — verified mapping table in prior re-audit |
| Detection layer unchanged from Option C | `git diff d454b9b..HEAD -- crt_engine.py` | ✓ only NEW-4 additions (no edits to lines 1-393) |

---

## 5. Final Verdict

**Is CRT v1 ICT-correct and ready for Session 3?**

**YES.** Every Session-1 and Session-2 finding is now CLOSED. The detection layer has been frozen since Option C (4 commits ago) — only scanner-layer and helper-layer additions across the last 3 commits. The Option H batch (commit `469ceeb`) is the cleanest of the round: NEW-2 properly closes the H-CRT2-4 inert-gate bug found in the prior re-audit, NEW-3 brings CRT economics gate symmetric with the 5M-sweep path's BEW + net_tp1 gates, and NEW-4 makes the helpers callable from `crypto_alert.py` for Session 3 live integration without creating a backtest.py dependency.

The three NEW observations in § 3 are all **LOW severity** and do not block Session 3:
- NEW-A is the economics gate working AS DESIGNED — operators just need to know it reduces signal count
- NEW-B is identical to the 5M-sweep path's early-window behavior (parity-correct)
- NEW-C is documented in prior reports as an intentional FVG-bias preference

**Conformance score: 88 / 100** (+9 from 79).
The remaining 12 points are split across:
- v1 simplifications documented in spec § 7 (TP2/TP3 as fixed RR multiples instead of HTF liquidity targets) — 4 pts
- v2-deferred A/B against "strict" validation school — 3 pts
- OB-quality grading not yet implemented (NEW-C) — 2 pts
- Lack of OTE 61.8-79% Fibonacci validation on entry zone — 2 pts (proactive improvement, not a bug)
- Minor: `MIN_SL_PCT` / `MAX_SL_PCT` floors from `compute_ict_trade_plan` not applied to CRT (CRT entries with very tight or very wide SLs pass through) — 1 pt

**Recommendations for Session 3:**
1. Re-baseline any in-flight CRT explorer trials — the H-CRT2-4 NEW-2 + NEW-3 fixes will materially change the distribution.
2. Wire live integration in `crypto_alert.py` to import `compute_crt_trade_economics` and `crt_quality_to_confidence` from `crt_engine.py` (NEW-4 enables this). Live and backtest will then produce byte-identical confidence + economics for the same setup.
3. (Optional v2) Add `ob_quality` grading per NEW-C; apply `MIN_SL_PCT` / `MAX_SL_PCT` floors per the final point above.

**Production safety:** `ENABLE_H4_CRT=0` is the default in `crt_engine.py:61`, and `run_backtest_token_h4_crt` short-circuits at `backtest.py:1322-1324`. Production behavior unchanged. CRT is opt-in via env var, exactly as the operator requested.

---

## 6. Files reviewed (absolute paths)

- `/home/tradeai/TradeAI/crt_engine.py` (502 lines)
- `/home/tradeai/TradeAI/ict_engine.py` (lines 845-970 — new OB functions; rest unchanged)
- `/home/tradeai/TradeAI/backtest.py` (lines 112-235 imports + constants; 558-570 `_lookup_4h_bias`; 1292-1576 CRT scanner; 3420-3443 config_hash)
- Prior reports:
  - `/home/tradeai/TradeAI/.claude/reports/ict-logic-validator/2026-05-27_crt_v1_session1.md`
  - `/home/tradeai/TradeAI/.claude/reports/ict-logic-validator/2026-05-27_crt_v1_session2.md`
  - `/home/tradeai/TradeAI/.claude/reports/ict-logic-validator/2026-05-27_crt_v1_session2_reaudit.md`
