# Phase I-5A Implementation Report — Template Safety Controls & Regime Safety Layer

**Date:** 2026-05-20  
**Author:** Claude (Sonnet 4.6)  
**Scope:** Safety controls layer only. No live gate changes to ICT detection, no adaptive learning
modifications, no per-template OGD, no auto-config changes.

---

## Overview

Phase I-5A adds a Template Safety Layer that classifies every generated signal with a `template_status`
before it reaches Telegram or live execution. In `PAPER` mode (default) all signals are sent to Telegram
regardless of status — the status is informational. In `LIVE` mode, only `ACTIVE` signals generate
Telegram alerts; blocked signals are saved to the DB with their block reason.

---

## New Constants in `crypto_alert.py`

Added after the `PERF_CHECK_INTERVAL` block:

```python
EXECUTION_MODE           = "PAPER"    # "PAPER" | "LIVE"
TEMPLATE_MIN_SAMPLE      = 50         # min closed trades per template before live execution
CIRCUIT_BREAKER_LOOKBACK = 10         # rolling window (trades) for circuit breaker
CIRCUIT_BREAKER_MIN_WR   = 0.35       # rolling WR below this pauses the template
TIER_DAILY_LIVE_CAPS     = {"TIER_A": 3, "TIER_B": 2, "TIER_C": 0, "NONE": 1}
BLOCK_RANGING_LIVE       = True       # block live execution in RANGING regime
BLOCK_RANGING_TEMPLATES  = {"TIER_B", "NONE"}  # templates blocked in RANGING
```

**Key design decisions:**
- `EXECUTION_MODE = "PAPER"` is the safe default — all existing behavior preserved until explicitly set to `"LIVE"`
- `TIER_DAILY_LIVE_CAPS["TIER_C"] = 0` means Tier C is always blocked even if `live_allowed` logic changed
- `BLOCK_RANGING_TEMPLATES` includes `NONE` (unmatched signals) to prevent RANGING-bias pollution in live P&L

---

## DB Migrations in `init_db()` — `crypto_alert.py`

Three new columns added to the `signals` table via idempotent `ALTER TABLE` migrations:

```python
("template_status",       "TEXT"),    # Phase 5A safety status string
("template_live_allowed", "INTEGER"), # 1 = live allowed, 0 = blocked
("template_block_reason", "TEXT"),    # human-readable reason if blocked
```

These are safe, additive migrations — `try/except` swallows the error if the column already exists.

---

## New Phase 5A Functions in `crypto_alert.py`

### `_tmpl_closed_count(conn, template_id) → int`

Returns the number of closed trades for a template (`WIN`, `PARTIAL_TP1`, `PARTIAL_TP2`, `LOSS`,
`EXPIRED`). Used for the minimum sample gate.

```sql
SELECT COUNT(*) FROM results r
JOIN signals s ON r.signal_id = s.id
WHERE s.matched_template_id = ?
AND r.result IN ('WIN','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED')
```

### `_tmpl_rolling_wr(conn, template_id, lookback) → float`

Returns the weighted win rate over the last `lookback` closed trades for a template.
- Weighted: `WIN = 1.0`, `PARTIAL_TP1 / PARTIAL_TP2 = 0.5`, `LOSS / EXPIRED = 0.0`
- Returns `1.0` (pass) when no data exists — avoids false circuit breaker trigger on new templates

```sql
SELECT r.result FROM results r
JOIN signals s ON r.signal_id = s.id
WHERE s.matched_template_id = ?
AND r.result IN ('WIN','PARTIAL_TP1','PARTIAL_TP2','LOSS','EXPIRED')
ORDER BY r.closed_at DESC LIMIT {lookback}
```

### `_tmpl_daily_live_count(conn, template_id) → int`

Returns the number of signals for a template that reached `template_status = 'ACTIVE'`
today (UTC). Used for the daily cap check.

```sql
SELECT COUNT(*) FROM signals
WHERE matched_template_id = ?
AND template_status = 'ACTIVE'
AND date(timestamp) = date('now')
```

### `evaluate_template_status(conn, template_id, regime) → (str, bool, str | None)`

Main safety evaluation. Returns `(status, live_allowed, block_reason)`.

**Check order — first failure wins:**

| Priority | Status | Trigger |
|----------|--------|---------|
| 1 | `UNKNOWN_TEMPLATE` | `template_id` not in `{TIER_A, TIER_B, TIER_C, NONE}` |
| 2 | `PAPER_ONLY` | `template_id == TIER_C` OR `TIER_DAILY_LIVE_CAPS[template_id] == 0` |
| 3 | `BLOCKED_BY_REGIME_SAFETY` | `BLOCK_RANGING_LIVE=True` AND `regime == RANGING` AND `template_id in BLOCK_RANGING_TEMPLATES` |
| 4 | `INSUFFICIENT_SAMPLE` | closed trade count < `TEMPLATE_MIN_SAMPLE` |
| 5 | `PAUSED_BY_CIRCUIT_BREAKER` | rolling WR < `CIRCUIT_BREAKER_MIN_WR` over last `CIRCUIT_BREAKER_LOOKBACK` trades |
| 6 | `DAILY_CAP_REACHED` | today's ACTIVE count >= `TIER_DAILY_LIVE_CAPS[template_id]` |
| 7 | `ACTIVE` | all checks passed |

**Failure safety:** `try/except` wraps the entire function. Any exception returns
`("UNKNOWN_TEMPLATE", False, str(exc))` — the function never raises.

---

## Changes to `generate_signal()` — `crypto_alert.py`

Phase 5A evaluation block inserted after the Phase I-2 template tagging block:

```python
try:
    _conn_5a = _connect()
    _tmpl_status, _tmpl_live_ok, _tmpl_block_reason = evaluate_template_status(
        _conn_5a, _best_template_id, regime.get("regime", "UNKNOWN"))
    _conn_5a.close()
except Exception as _e5a:
    _tmpl_status = "UNKNOWN_TEMPLATE"
    _tmpl_live_ok = False
    _tmpl_block_reason = f"Safety eval exception: {_e5a}"
_live_tag = "LIVE-OK" if _tmpl_live_ok else "PAPER"
print(f"[PHASE5A] {token} {signal} → {_best_template_id} "
      f"status={_tmpl_status} exec={_live_tag}"
      + (f" | {_tmpl_block_reason}" if _tmpl_block_reason else ""))
```

Three fields added to the `generate_signal()` return dict:

```python
"template_status":       _tmpl_status,
"template_live_allowed": int(_tmpl_live_ok),
"template_block_reason": _tmpl_block_reason or "",
```

---

## Changes to `save_signal()` — `crypto_alert.py`

Column list extended (now 60 columns):

```sql
...strategy_version, matched_template_id, template_scores_json,
template_status, template_live_allowed, template_block_reason)
VALUES (?, ..., ?, ?, ?)
```

VALUES tuple extended with:

```python
result.get("template_status", "UNKNOWN_TEMPLATE"),
result.get("template_live_allowed", 0),
result.get("template_block_reason", None)
```

`.get()` with defaults ensures old signal dicts (before Phase 5A) save cleanly with `NULL`.

---

## Changes to `send_signal_msg()` — `crypto_alert.py`

New `*STRATEGY TEMPLATE*` section added between ICT SETUP and TRADE PLAN in the Telegram message:

```
*STRATEGY TEMPLATE*
  Template: TIER_B ✅ ACTIVE
  Execution: LIVE-OK

*STRATEGY TEMPLATE*
  Template: TIER_B 🚫 BLOCKED_BY_REGIME_SAFETY
  Execution: PAPER
  Blocked: RANGING regime blocked for TIER_B (BLOCK_RANGING_LIVE=True...)
```

**Status emoji map:**

| Status | Emoji |
|--------|-------|
| `ACTIVE` | ✅ |
| `PAPER_ONLY` | 📋 |
| `PAUSED_BY_CIRCUIT_BREAKER` | ⏸ |
| `INSUFFICIENT_SAMPLE` | 🔬 |
| `BLOCKED_BY_REGIME_SAFETY` | 🚫 |
| `DAILY_CAP_REACHED` | 🔒 |
| `UNKNOWN_TEMPLATE` | ❓ |

---

## Main Loop — Telegram Suppression in LIVE Mode — `crypto_alert.py`

```python
if EXECUTION_MODE == "LIVE" and not result.get("template_live_allowed", 1):
    print(f"[PHASE5A] LIVE BLOCK: {token} {result['signal']} "
          f"template={result.get('matched_template_id','NONE')} "
          f"status={result.get('template_status','?')} "
          f"reason={result.get('template_block_reason','')} — signal saved, no Telegram")
else:
    send_signal_msg(token, price, ch24, result, plan, sig_id, regime)
```

- In `PAPER` mode (default): `EXECUTION_MODE != "LIVE"` → always calls `send_signal_msg()` → all signals reach Telegram
- In `LIVE` mode with `template_live_allowed=1`: calls `send_signal_msg()` → signal reaches Telegram
- In `LIVE` mode with `template_live_allowed=0`: prints block log → signal saved to DB only, no Telegram

---

## `validate_tier_hierarchy()` — `strategy_templates.py`

New public function added to `strategy_templates.py` and exported in `__all__`.

Tests that A ⊇ B ⊇ C holds for all bot-realistic signals (576 combinations):
- MSS ∈ {MEDIUM, HIGH} × FVG ∈ {LOW, MEDIUM, HIGH} × Session × DR location × Entry type × Direction
- Bonuses excluded — they only affect the float `score`, not `is_match`

Returns a list of violation strings. Empty list = hierarchy valid.

Called at the end of `init_db()` in `crypto_alert.py`:

```python
_hier_violations = validate_tier_hierarchy()
if _hier_violations:
    print(f"[PHASE5A] WARNING — {len(_hier_violations)} tier hierarchy violation(s):")
    for _v in _hier_violations: print(f"  {_v}")
else:
    print("[PHASE5A] Tier hierarchy OK — A ⊇ B ⊇ C holds for all bot-realistic signals")
```

**Smoke test result:** 0 violations ✓

---

## Phase 5A Simulation Section — `backtest.py`

New section appended to `write_template_performance_md()` (Phase I-3/4 report):

- Imports `EXECUTION_MODE, TEMPLATE_MIN_SAMPLE, CIRCUIT_BREAKER_LOOKBACK, CIRCUIT_BREAKER_MIN_WR, TIER_DAILY_LIVE_CAPS, BLOCK_RANGING_LIVE, BLOCK_RANGING_TEMPLATES` from `crypto_alert`
- Adds `"_all_signals": all_signals` to the `template_comparison_report()` return dict
- Simulation table shows signals blocked by each rule that can be computed from backtest data
- Notes rules requiring live DB state (circuit breaker, sample gate, daily cap) as "requires live DB"
- Regime safety breakdown by template: RANGING count, RANGING WR%, and block decision

---

## Files Changed

| File | Change Type | Change Summary |
|------|-------------|----------------|
| `crypto_alert.py` | New constants | `EXECUTION_MODE`, `TEMPLATE_MIN_SAMPLE`, `CIRCUIT_BREAKER_*`, `TIER_DAILY_LIVE_CAPS`, `BLOCK_RANGING_*` |
| `crypto_alert.py` | DB migration | 3 new columns: `template_status`, `template_live_allowed`, `template_block_reason` |
| `crypto_alert.py` | New functions | `_tmpl_closed_count`, `_tmpl_rolling_wr`, `_tmpl_daily_live_count`, `evaluate_template_status` |
| `crypto_alert.py` | Import update | Added `validate_tier_hierarchy` to `from strategy_templates import (...)` |
| `crypto_alert.py` | `generate_signal()` | Phase 5A eval block + 3 new return fields |
| `crypto_alert.py` | `save_signal()` | Column list + VALUES tuple extended with 3 Phase 5A fields |
| `crypto_alert.py` | `send_signal_msg()` | `*STRATEGY TEMPLATE*` section added to Telegram message |
| `crypto_alert.py` | `init_db()` | `validate_tier_hierarchy()` startup call + violation logging |
| `crypto_alert.py` | main loop | `LIVE` mode Telegram suppression when `template_live_allowed=0` |
| `strategy_templates.py` | New function | `validate_tier_hierarchy()` |
| `strategy_templates.py` | `__all__` | Added `validate_tier_hierarchy` |
| `backtest.py` | Import update | Added Phase 5A constants to `from crypto_alert import (...)` |
| `backtest.py` | `template_comparison_report()` | Added `"_all_signals"` to return dict |
| `backtest.py` | `write_template_performance_md()` | Phase 5A simulation section appended |

---

## DB / Schema Changes

| Table | Column | Type | Notes |
|-------|--------|------|-------|
| `signals` | `template_status` | TEXT | `ACTIVE`, `PAPER_ONLY`, `INSUFFICIENT_SAMPLE`, etc. |
| `signals` | `template_live_allowed` | INTEGER | 1 = live OK, 0 = blocked |
| `signals` | `template_block_reason` | TEXT | Human-readable explanation |

Total column count in `signals`: now **60 columns** (was 57).

---

## What is NOT Changed

- ICT detection logic (`ict_engine.py` — untouched)
- Adaptive learning / OGD weights (`adaptive_engine.py` — untouched)
- Strategy config (`strategy_engine.py` — untouched)
- Any live entry gate (no signals are ever blocked from being generated or saved)
- Existing backtest metrics (WR%, WF gap, MFE/MAE — unchanged)

---

## Behavior Matrix

| `EXECUTION_MODE` | `template_live_allowed` | Saved to DB? | Telegram sent? |
|------------------|------------------------|--------------|----------------|
| `PAPER` | 0 (blocked) | YES | YES (paper label in message) |
| `PAPER` | 1 (active) | YES | YES |
| `LIVE` | 0 (blocked) | YES | NO (print log only) |
| `LIVE` | 1 (active) | YES | YES |

Signals are **always saved to the DB** regardless of mode or status. The only difference is whether
Telegram is notified.

---

## Rollback

To disable Phase 5A without removing code:

1. Keep `EXECUTION_MODE = "PAPER"` — this is the safe default and restores all-signals-to-Telegram behavior
2. The `evaluate_template_status()` call in `generate_signal()` is wrapped in `try/except` — it cannot crash the signal flow
3. The three new DB columns are `NULL`-safe — old code that doesn't write them is unaffected
4. The `validate_tier_hierarchy()` call in `init_db()` is informational — violations print as warnings, never exceptions

---

## Tests / Checks Performed

| Check | Method | Result |
|-------|--------|--------|
| `crypto_alert.py` syntax | `python -c "import ast; ast.parse(open(..., encoding='utf-8').read())"` | PASS |
| `backtest.py` syntax | same | PASS |
| `strategy_templates.py` syntax | same | PASS |
| `validate_tier_hierarchy()` | Isolated run — 576 bot-realistic combos | PASS — 0 violations |
| All 4 new functions exist | AST walk for function names | PASS |
| All 7 new constants exist | AST walk for assignment targets | PASS |

---

## Next Phase

| Phase | Scope |
|-------|-------|
| I-5B | Per-template OGD adaptive learning — confidence weight adjustment per tier |
| I-5C | Tier C live gating enforcement as hard gate (vs. current convention) |
| I-6 | Phase 5B-equivalent: full per-template learning pipeline |

---

## Remaining Risks

| Risk | Severity | Notes |
|------|----------|-------|
| `TEMPLATE_MIN_SAMPLE = 50` — bot has ~277 backtest signals but results table has real closed data | Medium | TIER_A and TIER_B may not yet have 50 closed live trades; INSUFFICIENT_SAMPLE will fire for most templates initially |
| RANGING blocks reduce signal count for TIER_B | Medium | RANGING is 49% of TIER_B signals in backtest — expected and desired |
| Strategy breakeven (Tier B WR 35.9% vs BEW 36.1%) | High | Phase 5A RANGING block should improve WR; monitor after first 50 blocked-regime signals |
| `DAILY_CAP_REACHED` with small sample | Low | With low live traffic, daily cap will rarely trigger |
