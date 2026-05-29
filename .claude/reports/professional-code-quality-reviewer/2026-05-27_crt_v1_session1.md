# CRT v1 (Session 1) — Professional Code Quality Review

**Branch:** `experiment/crt-h4-signal-source` @ `8a6caea`
**Reviewer:** professional-code-quality-reviewer
**Date:** 2026-05-27
**Scope:** `crt_engine.py` (new), `ict_engine.py` lines 843-961 (new), `tests/test_crt_engine.py` (new)
**Mode:** READ-ONLY

---

## 1. Executive summary

CRT v1 is **good but needs cleanup before merge**. The module is well-scoped,
self-contained, defensively gated (`ENABLE_H4_CRT=0` default), and follows the
project's env-overridable constants pattern. Docstrings are unusually thorough
and accurately describe the Wyckoff/flexible design choice.

However, there are several concrete issues that should be fixed before this
module is integrated by Sessions 2-4: an unnecessary O(N·horizon) duplicate
walk that the existing `score_ict_mss()` already provides for free; a fixture
in `test_crt_engine.py` that contains a half-written discarded code block
(lines 188-190) which is dead/confusing code shipped to main; a confluence
predicate whose 5M FVG search uses an unchecked `mss_bar_5m` boundary; and a
test for the "default off" gate that does not actually clear the env-var
inherited from prior tests in the same process.

**Maintainability score: 7.5/10** — clean, readable, well-documented; loses
points for the dead fixture code, duplicate MSS walk, and shallow E2E test
coverage (T10 skips, T11 is essentially a smoke test).

**Top 3 findings:**
- H-1: `_approx_mss_bar` re-walks data that `score_ict_mss()` already returned (`mss_bar` field). Replace `detect_ict_mss` + `_approx_mss_bar` with a single `score_ict_mss` call.
- H-2: `tests/test_crt_engine.py:188-190` contains stale/abandoned list-comp code overwritten immediately on 191-194 — dead code shipped to a test fixture.
- M-1: T7 (`test_t7_disabled_by_default`) does not clear `H4_CRT_DISABLED_TOKENS` or other env vars; test isolation depends on test execution order.

---

## 2. CRITICAL issues
None. No issues that would cause production bugs in the current default-OFF
state. (Per CLAUDE.md, this module is pre-integration and gated behind
`ENABLE_H4_CRT=0`.)

---

## 3. HIGH issues

### H-1 — Duplicate MSS walk via `_approx_mss_bar`
**File:** `crt_engine.py:82-116`, called at `:267-270` and `:311-314`
**Problem:** `_approx_mss_bar` re-implements the inner loop of `score_ict_mss`
(`ict_engine.py:240-241, 252-253`) — which already returns the `mss_bar`
index in its result dict. The current code calls the boolean wrapper
`detect_ict_mss` (`ict_engine.py:293-295`) and then walks the same window a
second time to recover `mss_bar`. This is:
- ~2× the loop cost on the hottest path (every CRT candidate per scan cycle)
- Semantically fragile — `_approx_mss_bar` reads "most-recent swing prior to
  sweep" while `score_ict_mss` reads "most-recent swing within
  `ICT_SWEEP_LOOKBACK` window before sweep" (`ict_engine.py:233-236, 245-248`).
  These can pick **different** target levels, meaning `mss_bar_5m` may not
  correspond to the bar that actually confirmed MSS.

**Fix:** Replace both `detect_ict_mss` + `_approx_mss_bar` call pairs with a
single `score_ict_mss(...)` call and read `result["confirmed"]` +
`result["mss_bar"]`. This also lets you propagate MSS `quality` into the CRT
signal dict (useful for downstream filtering).

### H-2 — Dead/abandoned code in test fixture
**File:** `tests/test_crt_engine.py:188-190`
**Problem:** Three list-comp lines (`c5m_opens = [100.0]*40 + ...`,
`c5m_highs = [100.3]*30 + ... + [...] * 20`, comment `# Above lines got
tangled — rebuild cleanly below.`) are assigned and immediately overwritten
on lines 191-194. This is dead code accidentally shipped — the comment on
line 190 confirms the author meant to delete them. It also leaves a partially
constructed `c5m_highs` of mixed length that is misleading to anyone reading
the fixture.

**Fix:** Delete lines 188-190 outright.

### H-3 — `_check_confluence` 5M FVG range can index out of bounds via `mss_bar_5m+1`
**File:** `crt_engine.py:135-144`
**Problem:** The loop `for d in (mss_bar_5m - 1, mss_bar_5m, mss_bar_5m + 1)`
is guarded by `if d < 1 or d + 1 >= len(c5)`, which protects `score_ict_fvg`
itself but the *outer* guard `0 <= mss_bar_5m < len(c5) - 1` allows
`mss_bar_5m = len(c5) - 2`, then `d = mss_bar_5m + 1 = len(c5) - 1`, then the
inner check passes only because `d + 1 == len(c5)` triggers the `continue`.
This is correct behavior but reads as accidental — the `mss_bar_5m + 1`
probe is effectively dead for the last two bars. More importantly, this
silently fails to detect FVGs at the freshest data. Since CRT inherently
fires near the current bar, this matters.

**Fix:** Either widen the outer guard to require `mss_bar_5m + 2 < len(c5)`
or accept that "FVG one bar after MSS" is unreachable in real-time and drop
the `+1` probe entirely. Document the choice.

### H-4 — `score_ict_fvg` 'mitigation walk' is O(M·N) over the entire candle stream every call
**File:** `crt_engine.py:139` (calls `score_ict_fvg`)
**Problem:** `score_ict_fvg` itself (`ict_engine.py:333-337`) does an inner
`any(closes[k] ... for k in range(d+2, len(closes)))` mitigation walk. CRT
calls this up to 3 times per candidate, and there can be ~10 candidates per
scan (`H4_CRT_C2_LOOKBACK=10`), so worst-case 30 full mitigation-walks per
10-token × 5-min cycle. With 5M cache of ~300 bars, this is ~9k extra ops
per cycle — small in absolute terms but worth noting. Not blocking.

**Fix:** Cache the FVG list once per scan or accept the cost. Lower priority
than H-1.

---

## 4. MEDIUM issues

### M-1 — T7 env isolation is incomplete
**File:** `tests/test_crt_engine.py:111-121`
**Problem:** T7 pops `ENABLE_H4_CRT` but does NOT pop `H4_CRT_DISABLED_TOKENS`,
`H4_CRT_C2_LOOKBACK`, etc. If another test set those previously and didn't
clean up, T7's "default" claim is false. T8 does clean up `ENABLE_H4_CRT` and
`H4_CRT_DISABLED_TOKENS` (`:136-137`), but T9 doesn't restore
`H4_CRT_DISABLED_TOKENS`. T11 doesn't pop after itself either.

**Fix:** Add a `tearDown(self)` that pops all `ENABLE_H4_CRT`,
`H4_CRT_DISABLED_TOKENS`, `H4_CRT_C2_LOOKBACK`, `H4_CRT_MSS_HORIZON`,
`H4_CRT_OB_SCAN_LOOKBACK` from `os.environ` to guarantee per-test isolation.

### M-2 — `_check_confluence` parameter name collision with module
**File:** `crt_engine.py:119`
**Problem:** Function signature `_check_confluence(direction, c1_high, c1_low,
mss_bar_5m, c4h, c5m)` takes both `c4h` and `c5m` dicts and reaches into them
via dict access. This is the only place the OB detection runs — and it runs
on every CRT candidate (`H4_CRT_C2_LOOKBACK=10`) even though the OB
calculation is identical for every candidate (it scans H4 data which doesn't
change per candidate). The OB is computed up to 10× per scan when it could
be computed once.

**Fix:** Hoist `detect_ict_order_block(...)` out of the per-candidate loop in
`detect_h4_crt`. Compute it once, pass into `_check_confluence`.

### M-3 — Mitigation `consumed` set requires a separate `.add(key)` call by the caller, but `detect_h4_crt` returns `key` only
**File:** `crt_engine.py:163-340`
**Problem:** The contract says "Caller mutates the set after generating a
signal to mark the range mitigated" (`:178-179`), and the returned dict
includes `"key"` (`:293`). But the function NEVER mutates `consumed` itself,
so two near-simultaneous calls with the same `consumed` set (e.g. in a
multi-token scan loop that shares state, or in a backtest replay) can both
fire on the same C1 before the caller acts. If Session 2/3 wires this into a
multi-pass loop, this becomes a correctness issue.

**Fix:** Either (a) document explicitly that `consumed` mutation is the
caller's responsibility and the function is not thread-safe, or (b) take a
`mark_consumed=True` flag and have `detect_h4_crt` add to the set itself.
Recommend (a) for clarity.

### M-4 — T8 case-insensitive check passes a lowercase token but doesn't verify the blacklist comparison
**File:** `tests/test_crt_engine.py:134`
**Problem:** The blacklist comparison at `crt_engine.py:204` does
`token.upper() in H4_CRT_DISABLED_TOKENS`. T8 passes `"hbar"` and asserts
None. But the test does NOT also verify that a **non-blacklisted** token
WOULD have proceeded past the gate — so a bug that returns None for all
tokens regardless of blacklist would pass T8. Need a negative-control assert.

**Fix:** Add an assertion that `detect_h4_crt(c4h, c5m, token="BTC")` returns
None for a *different* reason (it does, because of insufficient data + no
sweep) — but use a structured way (e.g. set BTC, verify token != blacklist
path is taken via a mock or by checking a different gate fires).

### M-5 — `detect_ict_order_block` displacement scan can return an OB that is **older** than the displacement
**File:** `ict_engine.py:905-948`
**Problem:** The scan walks `i` backward from the end looking for
displacement; for each displacement candidate it walks `j` backward looking
for the last opposite candle. Per the docstring this should be the *most
recent* OB. But the outer loop returns on the first displacement found with
an opposite candle — which is the *newest* displacement, good. However, the
inner `break` at line 947-948 (`if (is_bullish_disp and j_bullish) or
(is_bearish_disp and j_bearish): break`) is unreachable: the earlier
branches at 922 and 933 already `return` when they find the opposite. The
only way to reach line 947 is when both `j_bullish` and `j_bearish` are
False (a doji where `close == open`), in which case `break` exits the inner
loop and the outer loop tries the **next-older displacement**. This is
acceptable but the comment on lines 944-946 is misleading — it says "if we
hit a same-direction candle we stop" but the actual code path that triggers
the `break` is "if we hit a doji".

**Fix:** Either correct the comment to "if we hit a doji, abandon this
displacement" or change the logic to match the comment (break on
same-direction j, continue on doji).

---

## 5. LOW issues

### L-1 — `crt_engine.py:34` uses `import os as _os` consistent with `ict_engine.py:11`
Not an issue — flagging as **consistent** with project conventions. Good.

### L-2 — Module constants and helpers mixed at module top
**File:** `crt_engine.py:46-66`
**Cosmetic:** The `_env_int`/`_env_str` helpers are duplicated from
`ict_engine.py:15-21`. Consider extracting to a `env_helpers.py` (or
`config.py` already SSoT per CLAUDE.md). The current duplication means
fixing `_env_int` behavior must happen in two places. Low priority — they're
~3 lines each.

### L-3 — `detect_h4_crt` docstring "Returns" claim of `dict` vs actual None default
**File:** `crt_engine.py:181-200`
**Cosmetic:** Docstring says "Returns: Signal dict on valid setup, None
otherwise." but the function signature says `-> dict`. Add `Optional[dict]`
or `-> dict | None` to the return-type annotation (Python 3.10+).

### L-4 — `_find_5m_bar_after` is O(N) linear scan; could be bisect
**File:** `crt_engine.py:70-79`
**Cosmetic:** With `times` sorted ascending, `bisect.bisect_right(times,
target_time)` is O(log N) vs current O(N). At N=300 this saves ~290 ops per
candidate — negligible but cleaner.

### L-5 — `_check_confluence` returns `{"type": "FVG", "details": fvg}` — `fvg` contains nested floats already rounded
**File:** `crt_engine.py:144, 157`
**Cosmetic:** The returned `confluence["details"]` carries `score_ict_fvg`'s
full dict (incl. `score_pts`, `reasons`, `quality`). This is fine but if
this dict will be JSON-stored downstream (Sessions 2/3), the `reasons` list
of strings is fine; `score_pts` is int; all serializable. **No bug.** Flagging
to confirm no hidden non-serializable types.

### L-6 — Test fixture H4 times use `range(0, 10*240, 240)` — non-UTC integers
**File:** `tests/test_crt_engine.py:175, 228, 270, 272`
**Cosmetic:** Times are bare ints, not pandas Timestamps or datetime objects.
This is fine for `_find_5m_bar_after` which uses `>` comparison and works
for any orderable type. Just be aware: production data will pass
`pd.Timestamp` objects, and `>` between Timestamp and int will raise. The
function is well-isolated by the dict contract, but unit-test it with at
least one Timestamp fixture to flush out future bugs.

### L-7 — `_approx_mss_bar` sweep_type uses string literal "SSL"/"BSL"
**File:** `crt_engine.py:92, 104`
**Cosmetic:** Magic strings — these match the existing convention in
`ict_engine.py` (`detect_ict_mss` uses `sweep_type="SSL"|"BSL"`), so this is
consistent. Not a blocker. Consider an enum if the project ever moves away
from stringly-typed sweeps.

---

## 6. Specific refactoring suggestions

### R-1 — Collapse `detect_ict_mss + _approx_mss_bar` → single `score_ict_mss` call
Eliminates H-1 entirely. Reduces `crt_engine.py` by ~35 LoC (`_approx_mss_bar`
becomes dead). Side benefit: propagate `mss_quality` into the signal dict for
Session 2 filtering.

### R-2 — Hoist `detect_ict_order_block` out of per-candidate loop
M-2 fix. OB depends only on `c4h`, not on the candidate. Compute once at the
top of `detect_h4_crt`, pass the result into `_check_confluence`.

### R-3 — Factor `_validate_bullish_crt` and `_validate_bearish_crt`
The two branches at `:252-294` (bullish) and `:296-338` (bearish) are
near-perfect mirrors. Extract:

```
def _validate_crt_direction(direction, sweep_type, c1_idx, c1_high, c1_low,
                            c2_idx, c2_high, c2_low, c2_time,
                            c4h, c5m, c5m_times, c5m_closes, sh_5m, sl_5m,
                            ob_cached):
    ...
```

Caller does one call for SSL+BUY, one for BSL+SELL. Removes ~50 LoC of
duplication. Trade-off: signature gets long.

### R-4 — Use bisect in `_find_5m_bar_after`
L-4 fix. One-line change.

### R-5 — Move `_env_int`/`_env_str` to a shared `env_helpers.py` or `config.py`
L-2 cleanup. Out of scope for this branch — flag for the next config-hygiene
sprint.

---

## 7. Test quality assessment

**Coverage:**

| Test | Path exercised | Effective? |
|------|----------------|------------|
| T1, T2 | OB detection happy paths (bull + bear) | ✓ solid |
| T3 | OB displacement floor | ✓ solid |
| T4 | OB no-opposite-candle | ✓ solid |
| T5, T6 | Overlap predicate | ✓ solid |
| T7 | Env flag default OFF | ⚠ env isolation incomplete (M-1) |
| T8 | Blacklist | ⚠ missing negative-control assert (M-4) |
| T9 | Short H4 data | ✓ solid |
| T10 | Bullish CRT E2E | ✗ SKIPPED — defeats purpose |
| T11 | Bearish CRT smoke | ✗ asserts `None or SELL` — too permissive |
| T12 | Mitigation set | ✓ solid (but bullish-only) |

**What's missing:**
- E2E bullish CRT detection with confluence (T10 must not skip)
- E2E bearish CRT detection with confluence (T11 must assert direction=SELL,
  not "either None or SELL")
- `_find_5m_bar_after` returning -1 → caller handles cleanly (verify no
  IndexError)
- `c4h` / `c5m` with missing keys → `detect_h4_crt` returns None
  (`crt_engine.py:210-212` IS guarded; ADD a test)
- `consumed=None` default → fresh empty set (covered implicitly by T10/T11
  but no explicit assertion)
- Race / interleaved calls with the same `consumed` set across two C1
  candidates (M-3 documentation)
- `mss_bar_5m` at the boundary (`len(c5)-1`, `len(c5)-2`) — H-3 territory

**T10 should not skip.** The skip rationale ("synthetic fixtures can't
guarantee FVG/OB confluence") is solvable: mock `_check_confluence` to
return a stub `{"type": "FVG", "details": {...}}` and then assert the
detection path produces the correct signal shape. This is a one-line
`unittest.mock.patch` and would lift the E2E test from "soft-skipped" to
actually validating the signal dict structure.

**Test isolation:** Per M-1, add a tearDown. Several tests pop some env vars
but not all; running these tests under randomized order (`pytest -p
randomly`) would expose the gaps.

---

## 8. Comparison against project conventions

| Convention | Where established | CRT v1 follows? |
|------------|-------------------|-----------------|
| Env-overridable constants at module top | `ict_engine.py:15-44`, `config.py` | ✓ Yes — `crt_engine.py:58-66` |
| `_env_int`/`_env_float` helpers | `ict_engine.py:15-21` | ✓ Yes (duplicated, see L-2) |
| `import os as _os` underscore alias | `ict_engine.py:11` | ✓ Yes — `crt_engine.py:34` |
| UPPER_SNAKE module constants | `ict_engine.py:24-74` | ✓ Yes |
| Docstring style (multi-section, "Args:"/"Returns:") | `ict_engine.py:217-225, 299-310` | ✓ Yes — actually more thorough than baseline |
| `round(..., 6)` on emitted price fields | `ict_engine.py:286, 357-360` | ✓ Yes — `crt_engine.py:283-291, 327-336` |
| **Reuse existing `score_ict_mss` instead of duplicating logic** | `ict_engine.py:293-295` shows even the bool wrapper *uses* `score_ict_mss` | ✗ **NO — H-1.** CRT calls the bool wrapper then re-walks. |
| Tests reload modules per-test to honor env changes | None of the existing project tests do this; `test_crt_engine.py` introduces it | ⚠ Novel pattern. Acceptable but heavy. |
| Signal dict shape: `direction`, `tp1`, `sl`, … | `compute_ict_trade_plan` at `ict_engine.py:746` | ⚠ Partially. CRT signal lacks `tp2`, `tp3`, `regime`, `confidence` — Session 2 territory. |

**Specific divergences from `ict_engine.py`:**
- CRT defines OB constants `ICT_OB_MIN_DISPLACEMENT_PCT` and
  `ICT_OB_OPPOSITE_LOOKBACK` as **bare module constants** in `ict_engine.py`
  (`:863-864`), NOT as env-overridable via `_env_float`/`_env_int`. Every
  other newer constant in the file is env-overridable (see lines 25, 27, 40,
  44). Recommend making these env-overridable for explorer compatibility.
- `detect_ict_order_block` does NOT round the `displacement_pct` to 6 places
  (`:927, 938`) — uses `round(..., 4)`. Acceptable (it's a percentage, not a
  price), but inconsistent with the rest of the file.

---

## 9. Pre-merge checklist

Before this branch merges to `main`:

- [ ] **H-1 (must):** Replace `detect_ict_mss + _approx_mss_bar` pair with a
      single `score_ict_mss` call. Delete `_approx_mss_bar`. Propagate
      `mss_quality` into the CRT signal dict.
- [ ] **H-2 (must):** Delete dead lines `tests/test_crt_engine.py:188-190`.
- [ ] **H-3 (should):** Fix or document the `mss_bar_5m + 1` boundary case
      in `_check_confluence`.
- [ ] **M-1 (should):** Add `tearDown` to all three test classes that pops
      every `ENABLE_H4_CRT*` env var to guarantee isolation.
- [ ] **M-2 (should):** Hoist `detect_ict_order_block` out of the
      per-candidate loop — compute once per `detect_h4_crt` call.
- [ ] **M-4 (should):** Strengthen T8 with a negative-control assert.
- [ ] **M-5 (nice):** Fix the misleading comment in `detect_ict_order_block`
      lines 944-946 to match actual `break` behavior (or fix the logic).
- [ ] **OB constants (nice):** Make `ICT_OB_MIN_DISPLACEMENT_PCT` and
      `ICT_OB_OPPOSITE_LOOKBACK` env-overridable for explorer compatibility.
- [ ] **T10 un-skip (nice):** Mock `_check_confluence` to validate the E2E
      bullish path actually produces the expected signal dict.
- [ ] **Type hints (nice):** Change `detect_h4_crt(...) -> dict` to
      `-> dict | None` (or `Optional[dict]`).
- [ ] **Run tests in randomized order** to confirm isolation:
      `pytest tests/test_crt_engine.py -p randomly --randomly-seed=42`.

Anything below this line (the **nice** items) can defer to Session 2 as long
as the **must** + **should** items are addressed.

---

**End of review.** No code was modified. All findings cite `file:line`. The
module is structurally sound, well-documented, and safely gated — fix H-1,
H-2, M-1, M-2 and this is ready to ship behind the `ENABLE_H4_CRT=1` flag
for shadow validation in Session 2.
