# CRT v1 Session 2 — ICT Re-Audit After Options B + E

**Branch:** `experiment/crt-h4-signal-source` @ `2c82d7d` (Option E), stacked on `76fcafb` (Option B)
**Prior report:** `.claude/reports/ict-logic-validator/2026-05-27_crt_v1_session2.md` (74/100)
**Scope:** re-verify the 3 HIGH + 2 MEDIUM closures; spot-check Session-1 detection layer for regressions.
**Mode:** READ-ONLY.

---

## 1. Executive Summary

Options B + E land the three structural HIGH fixes (SL buffer, session filter, 4H bias gate) with correct formulas matching the 5M-sweep reference implementation, and add a defensible quality→confidence mapping plus a CRT-specific 48h forward window. **One previously-undetected bug was found in the H-CRT2-4 implementation**: `get_ict_4h_bias()` is called with a 12-bar H4 sub-window, but the function silently returns `"NEUTRAL"` when `len(closes_4h) < 200` (ict_engine.py:413-414). The bias gate therefore never actually filters anything — it tags every CRT signal as bias=NEUTRAL, identical to the pre-Option-B hardcode. The other two HIGH fixes (SL buffer, session filter) verified correct.

Zero Session-1 detection-layer regressions: `crt_engine.py` is byte-identical between Session-1 fix commit (`d454b9b`) and HEAD (`2c82d7d`); all detection-layer fixes (C-CRT-1 mitigation key, C-CRT-2 canonical MSS path, H-3 OB walk-back, etc.) remain intact.

**Updated conformance: 79 / 100** (+5 from 74). Three of three HIGH structurally closed (one with a subtle but real semantic bug that needs follow-up); two of two targeted MEDIUMs closed cleanly. The score didn't jump more because the H-CRT2-4 implementation is correct in *form* but inert in *function*.

**Verdict: GO for Session 3 experimentation, NO-GO for any honest CRT-vs-5M-sweep WR comparison until H-CRT2-4-FOLLOWUP is fixed.**

---

## 2. HIGH / MEDIUM Closure Status

### H-CRT2-1 — SL buffer — **CLOSED (verified correct)**
**File:** `/home/tradeai/TradeAI/backtest.py:1510-1516`
- BUY: `sl_price = raw_wick * (1.0 - ICT_SL_BUFFER_PCT)` — pulls SL *below* the swept low → SL further from entry (correct direction).
- SELL: `sl_price = raw_wick * (1.0 + ICT_SL_BUFFER_PCT)` — pushes SL *above* the swept high → SL further from entry (correct direction).
- Formula matches `ict_engine.py:757,784` byte-for-byte.
- Buffer is applied AFTER `raw_wick = setup["sl"]` reads the unbuffered detector output — correct: the detection layer continues to return structural wick, and the scanner does the buffering.
- Constant `ICT_SL_BUFFER_PCT` correctly imported at `backtest.py:123`.

**Note:** the 5M-sweep `compute_ict_trade_plan` also applies `MIN_SL_PCT` / `MAX_SL_PCT` floors and a BEW gate. The CRT scanner skips these. Not a regression of Option B (the prior report didn't request them), but for parity: if a CRT swept wick is <`MIN_SL_PCT` away from entry, CRT will accept it while the 5M path would normalize. Flag for Session 3.

### H-CRT2-3 — Session/killzone filter — **CLOSED (structurally correct, currently a no-op)**
**File:** `/home/tradeai/TradeAI/backtest.py:1486-1489`
- `if ts.hour not in config.liquid_hours: continue` — identical pattern to the 5M-sweep path at `backtest.py:812`.
- Rejection counter `rej["crt_outside_killzone"]` instrumented correctly.

**Caveat — operator should know this:** the default `LIQUID_HOURS` (config.py:291) is `list(range(24))` — every hour is allowed. So the session filter is a *no-op in production* and only takes effect if operator sets `LIQUID_HOURS=13,14,15,...` env var. The 5M-sweep path has the same property (this is parity-correct). Spec § 7 phrasing "covers NY AM 13-17 UTC, London 7-10 UTC, Asia 23-3 UTC" is misleading — those killzones are not enforced by default. Recommend updating spec doc to say "infrastructure to filter by killzone exists; default config does not filter".

### H-CRT2-4 — 4H bias gate — **NOT-CLOSED (semantic bug — bias is always NEUTRAL)**
**File:** `/home/tradeai/TradeAI/backtest.py:1495`
- Code: `bias_4h = get_ict_4h_bias(c4h_win["closes"], c4h_win["highs"], c4h_win["lows"])`
- `c4h_win` length = `H4_CRT_C2_LOOKBACK (10) + CRT_H4_WINDOW_BUFFER (2) = 12` bars (`backtest.py:1429,1434-1439`).
- `get_ict_4h_bias` at `ict_engine.py:413-414`: `if len(closes_4h) < 200: return "NEUTRAL"`.
- **Consequence:** `bias_4h` is *always* `"NEUTRAL"` for CRT signals. The gate logic at lines 1500-1505 always falls into the "loose accepts NEUTRAL" branch and never blocks.

This is a step forward vs. the literal `"NEUTRAL"` hardcode (now the value is at least *computed*), but the result is functionally identical: zero CRT signals are filtered by 4H bias.

**Fix (one-liner for Session 3):** mirror the 5M-sweep path. Use `_lookup_4h_bias(c4h_indicator_dict, ts_ms)` (helper at `backtest.py:635-647`) which binary-searches the full pre-computed H4 series for ≥200 bars before the timestamp. That helper exists, is the canonical 5M-sweep entry point at the bias gate, and is already a static method on the same module — no new infrastructure needed. The CRT scanner should pass it `c4h` (the full series), not `c4h_win` (the sliding sub-window).

**Live/BT parity implication:** when the bug is fixed, the gate WILL start blocking signals in `BIAS_4H_GATE=strict` configs. This will change the CRT trial WR distribution — re-baseline any in-flight CRT explorer trials after the fix lands.

**Severity:** HIGH (same as before). Tagging as **NOT-CLOSED**.

### M-CRT2-2 — `FORWARD_BARS=288` too short for H4 — **CLOSED**
**File:** `/home/tradeai/TradeAI/backtest.py:228, 1416, 1474, 1478, 1536, 1547`
- `CRT_FORWARD_BARS = int(os.environ.get("CRT_FORWARD_BARS", "576"))` — default 48h, env-overridable.
- Applied consistently: `WARMUP_BARS + CRT_FORWARD_BARS` guard at scan start; `mss_bar_abs >= n5 - CRT_FORWARD_BARS - 1` and `entry_bar >= n5 - CRT_FORWARD_BARS - 1` look-ahead guards; `range(entry_bar+1, min(entry_bar+1+CRT_FORWARD_BARS, n5))` future bar window; `triple_barrier_label(..., t1_bars=CRT_FORWARD_BARS)`.
- Separation from the 5M-sweep's `FORWARD_BARS=288` is clean — the 5M-sweep path is unaffected.
- **Survivorship-bias risk: LOW.** A longer window does NOT mechanically inflate WR — `check_outcome` walks bar-by-bar and the FIRST barrier touched (SL or TP) terminates the trade. A longer window only converts what would be EXPIRED outcomes into one of {WIN, LOSS, PARTIAL_TP1}. It cannot turn a hit-SL trade into a win.
- 48h vs ICT theory: H4 dealing-range setups completing within 12 H4 bars (48h) is canonical. Some institutional swings extend to 72h (12-bar H4 leg), so 576 may still under-call a small tail — but it's the right order of magnitude.

### M-CRT2-4 — Confidence hardcoded to 10 — **CLOSED**
**File:** `/home/tradeai/TradeAI/backtest.py:299-315, 1580-1583`
- `_crt_quality_to_confidence(mss_quality, fvg_quality)` maps {NONE, LOW, MEDIUM, HIGH} × 2 → integer in [6, 10] via `max(6, min(10, 6 + (pts * 2) // 3))`.
- Verified mapping (computed):

  | MSS | FVG | pts | confidence |
  |-----|-----|-----|------------|
  | HIGH | HIGH | 6 | 10 |
  | HIGH | MEDIUM | 5 | 9 |
  | HIGH | LOW | 4 | 8 |
  | MEDIUM | MEDIUM | 4 | 8 |
  | HIGH | NONE | 3 | 8 |
  | MEDIUM | LOW | 3 | 8 |
  | LOW | LOW | 2 | 7 |
  | LOW | NONE | 1 | 6 |
  | NONE | NONE | 0 | 6 |

- ICT principle check: the floor at 6 (>= 5M-sweep typical floor of 5) means CRT signals always sit *above* the lowest 5M-sweep confidence. That's reasonable given CRT requires the strong dual-confluence (sweep + MSS + (FVG OR OB)). The ceiling at 10 only when BOTH layers are HIGH-graded is also reasonable.
- One minor quibble: a pure-OB confluence emits `fvg_quality="NONE"`, so a HIGH-MSS + HIGH-OB setup gets only confidence=8, but a HIGH-MSS + HIGH-FVG setup gets 10. The OB path is penalized for not being FVG. The fix at line 1581-1582 explicitly maps OB confluence → fvg_quality=NONE, so this is intentional but worth documenting — OB confluences cap at 8 instead of 10. ICT-defensible (FVG is the more institutional pattern in classical ICT), but operator should know.

---

## 3. New ICT Concerns Introduced by Options B + E

1. **H-CRT2-4-FOLLOWUP (HIGH):** the 4H bias gate is inert because `get_ict_4h_bias` is called with too few bars. See § 2 above. This is the only new structural issue.

2. **MEDIUM — OB confluences can't reach confidence=10.** Documented above. Spec gap, not a bug. Recommend either widening the mapping (e.g. infer an OB-quality grade) or documenting "OB confluences cap at 8 by design".

3. **LOW — `MIN_SL_PCT` / `MAX_SL_PCT` / BEW gate not applied to CRT.** The 5M-sweep path normalizes SL distance and rejects setups with bad breakeven WR via `compute_ict_trade_plan`. CRT skips these. Edge cases (very tight or very wide swept wicks) will produce signals the 5M path would have rejected. Not a regression of Option B, but flag for parity in Session 3.

4. **LOW — `liquid_hours` default = 24-hour pass-through.** The session filter is structurally wired but currently a no-op. Spec doc text suggests it actively filters killzones; reality is it does not (mirrors 5M-sweep behavior, parity-correct).

---

## 4. Session-1 Detection-Layer Regression Spot-Check

`git diff 3d47c77..2c82d7d -- crt_engine.py` returned **empty**. The detection layer is byte-identical between the Session-1 final fix commit (`d454b9b`) and the current HEAD (`2c82d7d`). All Session-1 fixes verified intact via grep:

| Session-1 fix | Location | Status |
|---|---|---|
| C-CRT-1 mitigation key uses `(c1_time, c1_high, c1_low)` tuple | `crt_engine.py:282-289` | INTACT |
| C-CRT-2 / H-1 canonical `score_ict_mss` (no `_approx_mss_bar`) | `crt_engine.py:306-310, 353` | INTACT |
| H-3 OB walk-back probe at `mss_bar_5m - 1, mss_bar_5m` (dropped +1) | `crt_engine.py:141-142` | INTACT |
| `score_ict_mss` returns `mss_bar` consumed by scanner | `crt_engine.py:340,383` | INTACT |
| Setup returns `key` tuple for caller to add to `consumed` | `crt_engine.py:213, 345, 388` | INTACT |

Wiring at `backtest.py:1294, 1474` continues to consume these correctly: `consumed = set()` initialized once per token; `consumed.add(setup["key"])` after each emitted signal.

**Zero regressions.**

---

## 5. Final Verdict

**Are CRT signals now produced according to ICT principles?**

**Mostly yes, with one notable caveat.** After Options B + E:

- **SL placement:** structurally correct (buffered wick, matches 5M-sweep formula). ✓
- **Entry timing:** next-bar open is acceptable v1 ICT (MEDIUM gap vs. FVG-retest still open, deferred to Session 3). ✓ (acceptable)
- **TP cascade:** TP1=C1 opposite extreme is liquidity-correct (CRT universal); TP2/TP3 as fixed RR multiples is a documented v1 simplification per spec § 7. ✓ (acceptable v1)
- **Session filter:** infrastructure correct, currently a no-op with default `LIQUID_HOURS=range(24)` — same as 5M-sweep. ✓ (parity-correct)
- **4H bias gate:** wired structurally but **inert** — `get_ict_4h_bias` always returns NEUTRAL when fed 12 H4 bars. The gate code path exists but cannot filter. ✗ (NEEDS FIX before any CRT-vs-5M-sweep WR comparison is published)
- **Confidence:** quality-derived in [6, 10] range, reasonable mapping. ✓
- **Forward window:** 48h CRT-specific, decoupled from 5M-sweep's 24h. No survivorship-bias risk. ✓
- **Detection layer:** zero regressions from Session 1. ✓

**Updated conformance: 79 / 100** (+5 from 74). The +5 reflects two of three HIGH structurally closed plus both targeted MEDIUMs cleanly closed. The H-CRT2-4 inert-gate bug prevents a full +10 boost.

**Recommendation:**
1. **GO** for continued CRT experimentation under `ENABLE_H4_CRT=1` in feature-branch backtests. Production unaffected (default `ENABLE_H4_CRT=0`).
2. **NO-GO** for publishing any CRT-vs-5M-sweep WR comparison until H-CRT2-4 is properly closed — until then, the CRT path runs with effectively `bias_4h_gate=none` regardless of config, while the 5M-sweep path honors `LIVE_BIAS_4H_GATE`. WR comparisons are apples-to-oranges.
3. **One-liner fix** for Session 3: swap `get_ict_4h_bias(c4h_win[...])` for `_lookup_4h_bias(c4h, c5m["times"][entry_bar])` at `backtest.py:1495`. Re-baseline any in-flight CRT trials after the fix.
