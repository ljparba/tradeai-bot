# CRT v1 Session 2 Option S — Live/BT Parity Re-Audit

**Date:** 2026-05-27
**Branch:** `experiment/crt-h4-signal-source`
**Head commit:** `2c0247f` (Option S)
**Prior commit:** `469ceeb` (Option H)
**Scope:** Verify LBC-H-3 closure and surface any new parity gaps introduced by Option S.

---

## 1. Executive Summary

**Final parity verdict for Option S: CLEAR — proceed to Session 3.**

Option S delivers exactly what the prior cumulative re-audit (LBC-H-3) requested: the three TP-cascade / forward-window constants are moved from `backtest.py` into `crt_engine.py` with byte-identical defaults and are now consumable via a single shared import. Backtest re-imports them and continues to behave identically. No new parity divergences were introduced. The shared module (`crt_engine.py`) is now the canonical source of truth for ALL CRT detection, economics, quality-mapping, AND outcome-window/TP constants — meaning Session 3 can wire the live path without any backwards dependency on `backtest.py`.

| LBC-finding | Pre-Option-S | Post-Option-S |
|---|---|---|
| LBC-H-3 (TP cascade constants in BT only) | OPEN | **CLOSED** |
| LBC-H-1 (signals.source column) | Session-3 work | Unchanged (Session 3) |
| LBC-H-2 (consumed_sweeps persistence) | Session-3 work | Unchanged (Session 3) |

No CRITICAL, HIGH, or MEDIUM parity findings remain blocking Session 3.

---

## 2. LBC-H-1 / H-2 / H-3 Final Status

### LBC-H-3 — CLOSED (verified)

`crt_engine.py:83-85` defines the canonical constants:
```python
CRT_TP2_RR       = _env_float("CRT_TP2_RR", 1.5)
CRT_TP3_RR       = _env_float("CRT_TP3_RR", 2.0)
CRT_FORWARD_BARS = _env_int("CRT_FORWARD_BARS", 576)
```

`backtest.py:117-133` re-imports them from the shared module; the in-file definitions at the old lines `223-232` are deleted (replaced by a one-line comment pointer at line 232). `grep "CRT_TP2_RR\|CRT_TP3_RR\|CRT_FORWARD_BARS" backtest.py` returns ONLY import-site + usage-site hits — zero stray local definitions.

**Default-value drift check:** Diff `469ceeb..2c0247f` shows the BT side was `CRT_TP2_RR = 1.5`, `CRT_TP3_RR = 2.0`, and `CRT_FORWARD_BARS = int(os.environ.get("CRT_FORWARD_BARS", "576"))`. The new shared definitions use `_env_float("CRT_TP2_RR", 1.5)`, `_env_float("CRT_TP3_RR", 2.0)`, `_env_int("CRT_FORWARD_BARS", 576)`. Byte-identical defaults; env-override semantics preserved (still string-coerce to float/int). Backtest config_hash entry at `backtest.py:3450` still records `CRT_FORWARD_BARS` from the same `os.environ` source, so explorer-cache invalidation continues to fire correctly when the env knob changes.

**Bonus closure (Option S extra):** the previously-opaque `crt_economics_gate` rejection counter is now split into 3 specific counters (`crt_economics_fees_kill`, `crt_economics_bew_too_high`, `crt_economics_invalid_inputs`) via the new `crt_trade_rejection_reason()` helper at `crt_engine.py:507`. This is a D2 diagnostic improvement only — does NOT change any signal pass/fail logic, so it is parity-neutral.

### LBC-H-1 — Unchanged (Session 3 work)

`signals` table in `crypto_alert.py` still lacks a `source` column. Backtest side already has it: `backtest.py:2249` adds `("source", "TEXT DEFAULT '5M_SWEEP'")` to `backtest_signals` with a default-tag for backfill. Session 3 must mirror this ALTER on the live `signals` table.

### LBC-H-2 — Unchanged (Session 3 work)

`consumed_sweeps` lives only as an in-memory `set()` per-token in `crypto_alert.py` state (`crypto_alert.py:154`). Session 3 must persist this (likely via `state_store.py`) so process restart does not re-fire the same swept-low signal. Backtest replicates this correctly within a single run via `consumed_sweeps_abs` dict (`backtest.py:728-786`).

---

## 3. NEW Parity Gaps from Option S

**None.** Option S is purely structural (file-move + diagnostic counter split). Verified:

- `_env_float` helper in `crt_engine.py:56-60` is byte-identical pattern to `_env_int` immediately above and matches the canonical `config.py:71-75` definition (same try/except KeyError/ValueError, same return-default semantics). Convention-compliant.
- `crt_trade_rejection_reason()` only mirrors the existing gate ordering in `compute_crt_trade_economics()` (fees → bew → invalid). Mirror is correct and additive; the success path is untouched.
- No new constants introduced. No new gate logic. Sweep/MSS/FVG/OB detection untouched.

---

## 4. Session 3 Import List — Exact Lines for `crypto_alert.py`

Session 3 `scan_token()` (or the dedicated `scan_token_h4_crt()` it adds) needs this single import block. Mirrors `backtest.py:117-133` for guaranteed parity:

```python
# CRT v1 Session 3: H4-CRT live integration — single shared module
# (crt_engine.py) is the source of truth for live + backtest. Imports
# below mirror backtest.py:117-133 so live signal generation, gating,
# and trade-economics use byte-identical logic + constants.
from crt_engine import (
    # ── Detection + config ─────────────────────────────────────────────
    detect_h4_crt,
    ENABLE_H4_CRT,
    H4_CRT_DISABLED_TOKENS,
    H4_CRT_C2_LOOKBACK,
    H4_CRT_MSS_HORIZON,
    # ── Economics + quality helpers ────────────────────────────────────
    compute_crt_trade_economics,
    crt_trade_rejection_reason,
    crt_quality_to_confidence,
    # ── TP cascade + forward-window constants ──────────────────────────
    CRT_TP2_RR,
    CRT_TP3_RR,
    CRT_FORWARD_BARS,
)
```

**Notes for Session 3 wiring:**

1. **No backwards dependency on `backtest.py`** — every symbol above resolves inside `crt_engine.py`. Verified by grepping `from crt_engine` across the repo: only `backtest.py` currently consumes it, and `crypto_alert.py` will be the second clean consumer.
2. **`CRT_FORWARD_BARS` is informational only on the live path** — the live bot does not run forward-bar TP/SL scans (operator manually executes). Use it only if Session 3 adds a "max expected resolution time" annotation to Telegram alerts.
3. **`ICT_SL_BUFFER_PCT`** for SL placement comes from `ict_engine.py`, NOT `crypto_alert.py` — mirror `backtest.py:136` (`from ict_engine import ICT_SL_BUFFER_PCT`).
4. **Rejection-reason counter (`crt_trade_rejection_reason`)** is optional on the live path. If Session 3 logs structured rejections, wire it to the same 3 keys (`fees_kill` / `bew_too_high` / `invalid_inputs`) for cross-path attribution comparability.
5. **`H4_CRT_DISABLED_TOKENS`** must be honored in the live scan loop (skip token if `token.upper() in H4_CRT_DISABLED_TOKENS`) — same gate as backtest path.
6. **`ENABLE_H4_CRT` default is 0** — Session 3 should ship the live integration BEHIND this env flag, then operator flips `ENABLE_H4_CRT=1` after manual paper-soak validation. This matches the CLAUDE.md "never auto-flip" discipline.

---

## Cross-Domain Observations

**Observation:** `crt_engine.py` now defines its own `_env_int` / `_env_float` / `_env_str` helpers that duplicate the canonical helpers in `config.py:54-75`. While the implementations are byte-identical, this is a minor SSoT smell — a future refactor could have `crt_engine.py` import them from `config.py` (after verifying no circular import). Non-blocking for Session 3.

**Relevant Agent:** `config-consistency-validator`
**Reason:** SSoT-policing scope — confirm whether the env-helper duplication is acceptable as a deliberate decoupling (crt_engine is meant to be importable standalone) or should consolidate to `config.py` in a cleanup pass.

---

## Consistency Score & Verdict

- **Consistency score for Option S diff:** 100% — no behavior change, only structural improvement
- **Critical divergences:** 0
- **Parity-blocking findings for Session 3:** 0
- **GO / NO-GO for Session 3 wiring:** **GO**
- **GO / NO-GO for LIVE mode:** unchanged — still NO-GO (Session 3 H-1/H-2 work + paper-soak + honest LIVE clearance gate still required)
