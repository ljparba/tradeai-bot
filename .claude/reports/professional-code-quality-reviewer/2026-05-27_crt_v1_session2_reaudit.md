# CRT v1 Session 2 — RE-AUDIT after Options B + E

**Branch:** `experiment/crt-h4-signal-source` @ `2c82d7d`
**Reviewer:** professional-code-quality-reviewer
**Date:** 2026-05-27
**Prior report (claimed):** `2026-05-27_crt_v1_session2.md` — file NOT FOUND
on disk; only `..._session1.md` present. Re-audit performed against the
user-supplied summary (0/4/7/5) + direct diff inspection vs `3d47c77`.
**Scope:** `backtest.py` deltas in `76fcafb` + `2c82d7d`; `tests/test_crt_backtest_integration.py` deltas
**Mode:** READ-ONLY

---

## 1. Executive summary

Options B + E close every claimed prior finding cleanly. The two new helpers
(`_compute_crt_trade_economics`, `_crt_quality_to_confidence`) are pure,
focused, well-documented. The programmatic INSERT via `_BACKTEST_SIGNALS_COLS`
+ `_backtest_signal_to_row` is a real maintainability win.

**However, the refactor introduces 3 NEW issues** — 1 CRITICAL (config-hash
gap), 1 HIGH (economics-formula parity divergence the extraction made
visible), 1 MEDIUM (test only validates length not schema alignment), plus
3 LOW polish items.

**Updated maintainability score: 8.0/10** (up from 7.5).
+1.5 for helpers, programmatic INSERT, scanner-contract symmetry, constant
promotion. −1.0 for new config-hash gap + economics divergence.

**Top 3 must-do before Session 3:**
- NEW-H-1: add `CRT_FORWARD_BARS` + `H4_CRT_OB_SCAN_LOOKBACK` to
  `_compute_run_config_hash`. Identical failure mode to B-CRT-S2-C2 just fixed.
- NEW-H-2: `_compute_crt_trade_economics` uses 2-decimal rounding + no
  MAX_BREAKEVEN_WR/net_tp1≤0 gates, whereas `compute_ict_trade_plan` uses
  3-decimal + applies both gates. Aggregate BEW will mix incompatible cohorts.
- NEW-M-1: `test_insert_includes_source_column` asserts tuple length only,
  not column-name alignment against the SQLite schema.

---

## 2. Closure verification — each prior finding

### Option B (commit 76fcafb)

| Prior | Status | Evidence |
|-------|--------|----------|
| H-1 (drop `c1h`) | **CLOSED** | `backtest.py:1369` sig now `(token, c5m, c4h, config=None)`; sole caller at `:3677` matches. |
| H-3 (magic→constants) | **CLOSED** | `backtest.py:211-228` — 7 named constants with docstrings. |
| H-4 (return tuple) | **CLOSED** | `:1398-1642` builds + returns `rej`; caller `:3677-3686` aggregates into `_GLOBAL_REJECTIONS` mirroring 5M path at `:3663-3666`. |
| H-CRT2-1 (SL buffer) | **CLOSED** | `:123` import + `:1513-1516` same form as `ict_engine.py:757,784`. |
| H-CRT2-3 (session filter) | **CLOSED** | `:1487` `if ts.hour not in config.liquid_hours: continue` + rejection counter. |
| H-CRT2-4 (4H bias computed) | **CLOSED** | `:1495` `get_ict_4h_bias(c4h_win[...])` on SAME H4 window the detector saw (data-cutoff parity); gate `:1499-1508`. |

### Option E (commit 2c82d7d)

| Prior | Status | Evidence |
|-------|--------|----------|
| H-2 partial | **CLOSED** | `:237-296` helper; `:1555-1572` consumes; ~120 LoC removed. Full 3-caller extraction explicitly deferred to S3. |
| M-1 (local bisect) | **CLOSED** | `:16` top-level `import bisect`; `:1449` uses `bisect.bisect_right`; no `_bisect_local` refs. |
| M-2 (risk_dist counter) | **CLOSED** | `:1520-1522` `if risk_dist <= 0: rej["crt_zero_risk_dist"] = ...; continue`. |
| M-4 (quality→conf) | **CLOSED** | `:299-315`. Verified all 16 grade pairs map to `[6, 10]`; NONE+NONE=6, HIGH+HIGH=10. |
| M-5 (TB `t1_bars`) | **CLOSED** | `:1547` `t1_bars=CRT_FORWARD_BARS`. |
| M-6 (programmatic INSERT) | **CLOSED** | `:3291-3306` tuple, `:3309-3341` builder, `:3422-3426` derived SQL. Length invariant tested. |

**12 of 12 verified.** No regressions.

---

## 3. NEW issues introduced

### NEW-H-1 — Config-hash gap on `CRT_FORWARD_BARS` + `H4_CRT_OB_SCAN_LOOKBACK` (CRITICAL)

**File:** `backtest.py:3437-3501` (`_compute_run_config_hash`)

**Problem:** Option E added `CRT_FORWARD_BARS` as env-overridable
(`backtest.py:228`) — directly governs forward scan, every WIN/LOSS/EXPIRED
outcome depends on it. NOT in the hash. Same gap for
`H4_CRT_OB_SCAN_LOOKBACK` (`crt_engine.py:68`), which affects OB-confluence
gating in CRT detection.

**Failure mode** (identical to B-CRT-S2-C2 just fixed): two backtests on
the same ICT params differing only in `CRT_FORWARD_BARS` collide on
config_hash → DSR n_trials undercount, Pareto-archive collision, checkpoint
cross-contamination.

**Evidence:**
- `:228` `CRT_FORWARD_BARS = int(os.environ.get(...))`
- `:3487-3500` hash payload includes 5 CRT knobs but NOT these two
- `tests/test_crt_backtest_integration.py:83-87` assertion list ALSO omits both

**Fix:** Add both knobs to hash payload + to the test's assertion list.
~6 LoC.

---

### NEW-H-2 — `_compute_crt_trade_economics` ≠ `compute_ict_trade_plan` formulas (HIGH)

**File:** `backtest.py:237-296` vs `ict_engine.py:746-842`

**Problem:** The two paths compute the same metrics with different rounding
and different economic gating:

| Metric | 5M-sweep (ict_engine `:811-839`) | CRT (`backtest:256-281`) |
|---|---|---|
| `net_tp%/net_sl%` rounding | `round(..., 3)` | `round(..., 2)` |
| `MAX_BREAKEVEN_WR` filter | `:820-821` rejects setup | **absent** |
| `net_tp1_pct <= 0` filter | `:817-818` rejects setup | **absent** |
| `net_rr1` formula | `net_tp1 / (risk + rt_cost)` | `net_tp1 / abs(net_sl)` |
| `breakeven_wr` formula | `(risk + rt_cost) / (tp1_gross + risk)` | `abs(net_sl) / (abs(net_sl) + net_tp1)` |

The last two formulas are **algebraically equivalent** (`risk + rt_cost ==
abs(net_sl)`, `tp1_gross + risk == net_tp1 + abs(net_sl)`) so produce
identical floats modulo the 2-vs-3 decimal rounding gap. But the missing
economic gates are real:

- A CRT setup with cost > gross TP1 still emits a signal (net negative-EV)
- A CRT setup with `breakeven_wr > MAX_BREAKEVEN_WR` still emits

The `print_report` aggregate BEW (`:2077, :2221`) averages both cohorts —
once CRT signals flow into the pool, aggregate BEW becomes apples-to-oranges.

**Risk:** MEDIUM (not yet HIGH because `ENABLE_H4_CRT=0` is the default;
becomes HIGH the moment an explorer trial flips it on for DSR scoring).

**Fix:** Either (a) apply the same `MAX_BREAKEVEN_WR` + `net_tp1≤0` early-
return guards in `_compute_crt_trade_economics` (matches 5M floor), or
(b) document explicitly that CRT bypasses these by design + update
print_report to segment BEW by `source`. Standardize rounding to 3 decimals.

---

### NEW-M-1 — INSERT schema test validates length but not column-name alignment (MEDIUM)

**File:** `tests/test_crt_backtest_integration.py:55-74`

**Problem:** `test_insert_includes_source_column` asserts
`len(row) == len(_BACKTEST_SIGNALS_COLS)` only. It does NOT verify that
each column name in `_BACKTEST_SIGNALS_COLS` actually exists in the SQLite
schema produced by `init_backtest_db`. A future rename
(`dr_location` → `dr4h_location` in the tuple, missing the schema migration)
would pass the test but fail at runtime with `OperationalError: no such
column`.

**Fix:** Open in-memory SQLite, run `init_backtest_db`, query
`PRAGMA table_info(backtest_signals)`, assert
`set(_BACKTEST_SIGNALS_COLS) - {"run_id"} ⊆ set(actual_cols)`. ~15 LoC.

---

### NEW-L-1 — `_compute_crt_trade_economics` no `entry_price <= 0` guard

`backtest.py:246-255`. All `gross_*` divide by `entry_price`. The caller at
`:1520-1522` rejects `risk_dist <= 0` first, so in practice safe — but the
helper is fragile if Session 3 reuses it elsewhere. Add a precondition
assertion or docstring note.

### NEW-L-2 — `_crt_quality_to_confidence` mapping has a flat-spot

`backtest.py:299-315`. `(pts * 2) // 3` integer math produces:
- pts=3 (HIGH+NONE, LOW+MEDIUM) → conf=8
- pts=4 (HIGH+LOW, MEDIUM+MEDIUM) → conf=8 (same)

Same confidence for "HIGH MSS + LOW FVG" and "HIGH MSS + NONE FVG" —
contradicts the docstring's "gradations of quality" claim. Document
explicitly or refine mapping.

### NEW-L-3 — `_BACKTEST_SIGNALS_COLS` missing dict-key/DB-col rename note

`backtest.py:3291-3306` uses `dr_location` but the signal dict key is
`dr4h_location` (handled correctly at `:3329` via `s.get("dr4h_location",
...)`). The rename is invisible to readers of the column tuple — add an
inline comment OR converge the names.

---

## 4. Missed opportunities

**A. Other 5M-sweep duplications worth extracting?** No. After H-2 partial,
both scanners share `triple_barrier_label`, `check_outcome`,
`compute_excursions`, `_utc_to_session`. The only remaining duplication is
the economics + signal-dict construction, which the commit message
correctly defers to Session 3's 3-caller threshold.

**B. `_BACKTEST_SIGNALS_COLS` completeness.** Cross-referenced against
`init_backtest_db` schema at `backtest.py:2262-2306` — all 48 schema columns
present; ordering matches the row-builder output (verified by enumerated
dump).

**C. Pre-Session-2 back-compat.** `_backtest_signal_to_row` uses
`s.get("source", "5M_SWEEP")` at `:3340` — replay of legacy snapshot
signals without the `source` field still works. No breakage.

**D. Module-constant tunability asymmetry.** `CRT_FORWARD_BARS` is env-
overridable (`:228`); the other 6 new constants (`:215-220`) are not. If
Session 3 wants the explorer to tune them, they'll need `_env_int` lifts.
Worth a one-line comment marking which are tuning-locked.

**E. Scanner readability post-extraction.** The CRT scanner is meaningfully
clearer. The 10-line unpack at `:1563-1572` could be replaced with
`signals.append({..., **econ})` if dict-merge style is preferred, but the
explicit unpack reads as documentation — keep.

---

## 5. Test quality re-check

| Helper | Unit-test? | Coverage type |
|--------|------------|---------------|
| `_compute_crt_trade_economics` | **None** | None — pure function shipped untested |
| `_crt_quality_to_confidence` | **None** | None — pure function shipped untested |
| `_backtest_signal_to_row` | **Partial** | Length only (see NEW-M-1) |

**Recommend (~30 LoC):**
- 4 parametrized cases on `_compute_crt_trade_economics`: BUY-WIN, BUY-LOSS,
  SELL-PARTIAL_TP2, EXPIRED. Assert `realized_r`, `breakeven_wr`, `net_rr1`
  against hand-computed expected values.
- 1 grid-test on `_crt_quality_to_confidence` over all 16 grade pairs,
  asserting range `[6, 10]` + corner values.
- 1 schema-alignment test (per NEW-M-1) — runs `init_backtest_db` against
  in-memory SQLite, verifies tuple-to-PRAGMA column-name set inclusion.

---

## 6. Pre-Session-3 checklist (updated)

### MUST close before Session 3 starts
- [ ] **NEW-H-1** — add `CRT_FORWARD_BARS` + `H4_CRT_OB_SCAN_LOOKBACK` to
      `_compute_run_config_hash` payload AND to the test assertion list.
      Without this, any explorer trial varying these knobs corrupts the
      config_hash partition.

### SHOULD close before ENABLE_H4_CRT=1 ever runs in production / explorer
- [ ] **NEW-H-2** — decide explicitly whether CRT signals are subject to
      `MAX_BREAKEVEN_WR` and `net_tp1_pct ≤ 0` gates (the 5M path applies
      both). Either add the guards to `_compute_crt_trade_economics`, or
      segment aggregate BEW by `source` in print_report so cohorts don't
      get averaged. Standardize rounding to 3 decimals.
- [ ] **NEW-M-1** — add schema-vs-tuple alignment test.
- [ ] Add unit tests for `_compute_crt_trade_economics` and
      `_crt_quality_to_confidence` (currently untested).

### NICE to have
- [ ] NEW-L-1: precondition on `entry_price <= 0`.
- [ ] NEW-L-2: document confidence-mapping plateau.
- [ ] NEW-L-3: rename comment on `dr_location ↔ dr4h_location`.
- [ ] Comment tuning-locked vs env-overridable constants at `:211-228`.

### Session-3 design items already documented
- LBC-H-1/2/3 (live integration parity gates) per spec § 16
- H-2 FULL extraction: fold `_compute_crt_trade_economics` and
  `compute_ict_trade_plan` into a single shared helper when `crypto_alert.py`
  becomes the 3rd caller. **THIS is the natural moment to resolve NEW-H-2**
  — the unified helper either applies the economic gates or doesn't; the
  asymmetry disappears.

---

## 7. Verdict

Options B + E are **clean, surgical, and close every claimed prior
finding.** The two new helpers are professional-grade. The programmatic
INSERT is a real architectural improvement.

The 3 NEW issues are not regressions:
- NEW-H-1 is a missed knob in the very fix Option B made
- NEW-H-2 is a pre-existing structural divergence that the extraction made
  visible (the extraction itself didn't introduce the divergence — it
  exposed it by giving it a name and a discrete location)
- NEW-M-1 is a thin spot in the test added with the M-6 fix

All 3 are straightforward to address. The branch is **ready for Session 3
once NEW-H-1 is closed** (~15 min of work). NEW-H-2 and NEW-M-1 are
appropriate to fold into Session 3's unified-helper + live-integration
work — flagging them now means the Session 3 author can't miss them.

**Updated maintainability score: 8.0/10.**

---

**End of re-audit.** No code modified. All findings cite `file:line`.
Prior 12 of 12 closures verified; 3 new issues introduced (1 CRITICAL,
1 HIGH, 1 MEDIUM); 3 minor LOW observations.
