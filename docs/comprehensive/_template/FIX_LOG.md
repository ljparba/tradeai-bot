# Fix Log — [DATE]

> Log every fix here immediately after applying it — before moving to the next issue.
> This is your audit trail. If something breaks later, this tells you exactly what changed and when.

---

## Fix Entries

---

### Fix #C1 — [Issue Title]

| Field | Value |
|---|---|
| **Issue Ref** | #C1 |
| **Severity** | CRITICAL |
| **Date Fixed** | YYYY-MM-DD |
| **Brainstorm Agent** | _(agent used)_ |

**Root Cause:**
> What was actually wrong and why it happened.

**Fix Applied:**
> Exact description of what was changed. Be specific.

**Files Changed:**
- `filename.py` — line ___ : _what changed_

**Smoke Test:**
- Command run: `pytest tests/test_xxx.py`
- Result: `PASS / FAIL`

**Full Test Suite:**
- Command: `pytest tests/ -v`
- Result: `___ / 162 PASS`

**Backtest Run:**
- Required: `Yes / No`
- Result: _(if yes — WR: _%, z: _, n: _)_
- Regression: `None / [describe if any]`

**Sign-off:** ✅ COMPLETE

---

### Fix #H1 — [Issue Title]

| Field | Value |
|---|---|
| **Issue Ref** | #H1 |
| **Severity** | HIGH |
| **Date Fixed** | YYYY-MM-DD |
| **Brainstorm Agent** | _(agent used)_ |

**Root Cause:**

**Fix Applied:**

**Files Changed:**
- `filename.py` — line ___ :

**Smoke Test:**
- Command run:
- Result: `PASS / FAIL`

**Full Test Suite:**
- Result: `___ / 162 PASS`

**Backtest Run:**
- Required: `Yes / No`
- Result:

**Sign-off:** ✅ COMPLETE

---

## Session Summary

| Field | Value |
|---|---|
| **Session Date** | YYYY-MM-DD |
| **Issues Fixed This Session** | _ |
| **Tests After Last Fix** | _ / 162 PASS |
| **Backtest Ran** | Yes / No |
| **Baseline Maintained** | Yes / No |
| **Next Session Resume** | #___ |
