# CRT v1 Cumulative Re-audit — Sessions 1 + 2 (all Options through H)
**Branch:** `experiment/crt-h4-signal-source` @ `469ceeb`
**Reviewer:** live-backtest-consistency-checker
**Mode:** READ-ONLY
**Date:** 2026-05-27

---

## 1. Executive summary

Option H closes the last two LBC findings raised in the prior re-audit:
- **NEW-H-1 (4H bias windowing asymmetry)** — fixed via `_lookup_4h_bias`.
- **NEW-H-2 (helpers in `backtest.py` with `_` prefix)** — fixed via move to `crt_engine.py` with PUBLIC names.

Static review of `crt_engine.py`, `backtest.py:1280–1577` (CRT scanner), `crypto_alert.py:2180–2200` (live 4H bias), and the shared 5M-sweep path confirms:
- Identical inputs to `get_ict_4h_bias` between CRT scanner and 5M-sweep scanner (both go through `_lookup_4h_bias` in backtest; both use `c4h_state[:-1]` in live).
- Identical SL buffer (`ICT_SL_BUFFER_PCT = 0.003` imported from `ict_engine`).
- Identical session classifier (`_utc_to_session` from `adaptive_engine`).
- Identical economics conventions (3-dp rounding, `MAX_BREAKEVEN_WR=0.60` gate, `net_tp1 ≤ 0` rejection, `net_sl` 2-dp).
- Identical confidence mapping (`crt_quality_to_confidence` in shared module).

**Parity verdict for the SCANNER itself: GREEN.** The CRT scanner in `backtest.py` shares every load-bearing function and constant with the existing 5M-sweep path. A Session 3 live integration that calls the same `detect_h4_crt` + `_lookup_4h_bias` + `compute_crt_trade_economics` + `crt_quality_to_confidence` from `crypto_alert.py` will produce byte-identical signals on identical OHLCV input — modulo the pre-existing EMA-history divergence noted in §3 (NOT introduced by CRT).

**Branch is parity-ready for Session 3 integration.** The three remaining gates are SESSION-3 work, not pre-existing parity bugs.

---

## 2. LBC-H-1 / LBC-H-2 / LBC-H-3 status

### LBC-H-1: live `signals` table needs `source` column ALTER + INSERT extension — STILL SESSION-3 WORK

`crypto_alert.py:201–246` defines the live `signals` table with NO `source` column. The backtest's `backtest.py:3239` row schema includes `"source"` but the live schema does not. Session 3 MUST:
1. Add `ALTER TABLE signals ADD COLUMN source TEXT DEFAULT '5M_SWEEP';` to the migration block.
2. Pass `source='5M_SWEEP'` for the existing path and `source='H4_CRT'` for the new CRT path in the INSERT statement around `crypto_alert.py:2543`.
3. Backfill historical rows with `source='5M_SWEEP'` for per-source aggregation in `tracker.py`.

Spec doc § 16 instruction remains accurate after Option H. No changes needed to the spec.

### LBC-H-2: `consumed_sweeps` mitigation set needs `state_store` persistence — STILL SESSION-3 WORK

Verified: `crypto_alert.py:154` initializes `"consumed_sweeps": set()` per-token in the in-process `STATE` dict only. `state_store.py:146` (`_atomic_write_json`) is used to persist named scalars and OGD weights but NOT `consumed_sweeps`. After a bot restart, the live CRT scanner would re-emit setups for already-mitigated H4 C1 ranges.

Session 3 MUST:
1. Serialize the per-token `consumed_sweeps` set to JSON in `state_store` on each cycle.
2. Restore on bot startup via `_state_store.load()` (the same pattern used for `last_decay_time` at `crypto_alert.py:3247`).
3. Apply the same TTL pruning logic used for the existing `consumed_sweeps` in `crypto_alert.py:2160–2169` (timestamp-based aging) so the on-disk set doesn't grow unbounded.

Spec doc § 16 instruction remains accurate.

### LBC-H-3: TP cascade helper must be shared — PARTIALLY CLOSED

**Closed portion:** Option H NEW-4 moved `compute_crt_trade_economics` and `crt_quality_to_confidence` to `crt_engine.py` with PUBLIC names. The economics + confidence helpers are now safely shareable between `backtest.py` and Session 3's `crypto_alert.py` via `from crt_engine import compute_crt_trade_economics, crt_quality_to_confidence`. Verified at `crt_engine.py:400` and `:484`, imported at `backtest.py:117–124`.

**Still open portion — CRT_TP2_RR / CRT_TP3_RR / CRT_FORWARD_BARS:** These named constants live in `backtest.py:223–232`, NOT `crt_engine.py`. The TP cascade arithmetic itself is inlined at `backtest.py:1450–1455`:
```
tp2_price = entry_price + CRT_TP2_RR * risk_dist
tp3_price = entry_price + CRT_TP3_RR * risk_dist
```

If Session 3 wires CRT in via `crypto_alert.py`, it MUST replicate this 4-line arithmetic block AND read the same constants. Two paths:

- **Recommended:** Move `CRT_TP2_RR`, `CRT_TP3_RR`, `CRT_FORWARD_BARS` to `crt_engine.py` (single source of truth, same pattern as NEW-4). Extract the cascade math into a small helper `compute_crt_tp_cascade(direction, entry, sl_price)` returning `(tp2, tp3)` for both callers.
- **Acceptable but architecturally fragile:** Have `crypto_alert.py` import from `backtest.py` — inverted dependency (live depends on backtest) creates a coupling that future refactors could break silently.

**Verdict: SESSION-3 PRE-WORK.** A 3-line move (constants → crt_engine.py) plus a 6-line helper extraction. ~5 minutes of work. If skipped, the cascade math drifts the moment one path changes RR values without the other.

---

## 3. NEW parity gaps introduced by Option H

### NEW-FINDING-1: NONE in the helper-move itself

Verified that the moved helpers have IDENTICAL signatures and return-shape to the prior `backtest.py` in-file versions:

| Aspect | Pre-move (backtest.py) | Post-move (crt_engine.py:400) | Drift? |
|---|---|---|---|
| Signature | `(direction, entry_price, sl_price, tp1_price, tp2_price, tp3_price, outcome, rt_cost_pct)` | Same | No |
| `MAX_BREAKEVEN_WR` source | `from ict_engine import MAX_BREAKEVEN_WR` in backtest.py | `from ict_engine import MAX_BREAKEVEN_WR` in crt_engine.py:40 | No — same canonical source |
| Return None gates | `net_tp1 ≤ 0` + `bew > MAX_BREAKEVEN_WR` + `gross_tp1 + risk_pct ≤ 0` | Same 3 gates at crt_engine.py:437,444,448 | No |
| Rounding | `round(net_tp1, 3)`, `round(net_sl, 2)`, `round(rr1, 2)`, `round(bew, 4)` | Same | No |
| `crt_quality_to_confidence` map | `q_score = {"HIGH":3,"MEDIUM":2,"LOW":1,"NONE":0}`, `max(6, min(10, 6 + (pts*2)//3))` | Same at crt_engine.py:500–502 | No |

Verified at backtest.py:1488–1505 — caller code passes the SAME positional args as the pre-move definition, unpacks the SAME dict keys.

### NEW-FINDING-2: NONE in the 4H bias parity claim

Verified live (`crypto_alert.py:2185–2189`) and backtest (`backtest.py:558–570`) both feed CLOSED 4H bars to `get_ict_4h_bias`:
- Live: `c4h_state["closes"][:-1]` etc. — strips forming bar.
- Backtest: `bisect.bisect_right(times, ts_ms - 1) - 1` — selects most-recent bar with timestamp < ts_ms, i.e. excludes a forming bar.
- Both invoke the SAME `get_ict_4h_bias(closes_4h, highs_4h, lows_4h)` from `ict_engine.py:409`.
- Both return `"NEUTRAL"` if the input has fewer than 200 closed bars (guard at ict_engine.py:413).

The CRT scanner at `backtest.py:1422` now uses `_lookup_4h_bias(c4h, c5m["times"][entry_bar])` — same helper as the 5M-sweep at `backtest.py:803`. Parity restored.

### KNOWN PRE-EXISTING DIVERGENCE (NOT introduced by Option H): EMA history depth

`get_ict_4h_bias` runs `get_trend()` on the full input slice. `get_trend()` calls `ema(closes, 200)` which seeds with SMA of `closes[:200]` then runs forward. The EMA's converged value depends on series length:

- Live: feeds `closes_4h[:-1]` — up to 399 closed bars (config.py:146 sets `limit=400`).
- Backtest (5M-sweep AND CRT, both): caps at 210 bars (`_N = min(idx + 1, 210)` at backtest.py:564).

For EMA200, the difference between 210-bar input and 399-bar input is real but bounded (sub-percent for typical daily volatility). The 5M-sweep path has had this divergence since `_lookup_4h_bias` was added; Option H merely brings CRT into alignment with the SAME convention. **Not a new finding — pre-existing structural divergence that affects BOTH paths equally.** If operator wants byte-identical EMA200 between live and backtest, they would need to either:
- Cap the live computation at 210 bars (`get_ict_4h_bias(c4h_state["closes"][-211:-1], ...)`), OR
- Remove the 210 cap in `_lookup_4h_bias` (let backtest see the full backwards history).

Recommend: file separately under "C4 known structural drift" successor work, not as a CRT-blocking issue.

### Helper-import path verification

Verified at backtest.py:117–127:
```
from crt_engine import (
    detect_h4_crt, ENABLE_H4_CRT, H4_CRT_DISABLED_TOKENS,
    H4_CRT_C2_LOOKBACK, H4_CRT_MSS_HORIZON,
    compute_crt_trade_economics, crt_quality_to_confidence,
)
from ict_engine import ICT_SL_BUFFER_PCT
```

These are the ONLY entry points the scanner uses for setup detection, economics, and SL buffer. Session 3 `crypto_alert.py` can use the EXACT SAME import block (replacing `backtest.py` line with `crypto_alert.py`). Zero drift risk.

---

## 4. Final verdict

**CRT v1 branch (`experiment/crt-h4-signal-source` @ `469ceeb`) is PARITY-READY for Session 3 integration, conditional on Session 3 completing the three pre-work items below.**

### Pre-conditions Session 3 MUST satisfy before live wiring

1. **LBC-H-1 (live schema):** ALTER TABLE signals ADD COLUMN source TEXT DEFAULT '5M_SWEEP' + INSERT extension. Required for per-source attribution; without it, CRT signals would be undistinguishable from 5M-sweep signals in `signals.db`, breaking the validation pipeline that compares the two sources.
2. **LBC-H-2 (state_store persistence):** Serialize per-token `consumed_sweeps` set to disk via `state_store`, restore on startup, apply TTL pruning. Required to prevent duplicate emissions across bot restarts (high-impact in PAPER mode where restarts happen on every code deploy).
3. **LBC-H-3 residual (constants + cascade math):** Move `CRT_TP2_RR`, `CRT_TP3_RR`, `CRT_FORWARD_BARS` to `crt_engine.py`. Extract `compute_crt_tp_cascade(direction, entry, sl_price)` helper. ~5 minutes of work. Without it, the cascade math is duplicated across `backtest.py` and `crypto_alert.py` — a future RR tweak in one file would silently diverge.

### Parity-correct by construction (verified)

- `detect_h4_crt` — single shared module function.
- `compute_crt_trade_economics` — single shared module function (NEW-4 fix).
- `crt_quality_to_confidence` — single shared module function (NEW-4 fix).
- `_lookup_4h_bias` — same helper for both 5M-sweep and CRT in backtest; live's bias call uses the same `get_ict_4h_bias` underlying function (NEW-2 fix).
- `_utc_to_session` — canonical, imported from `adaptive_engine`.
- `ICT_SL_BUFFER_PCT` — canonical, imported from `ict_engine`.
- `MAX_BREAKEVEN_WR` — canonical, imported from `ict_engine`.

### Outstanding pre-existing divergences (NOT CRT-introduced)

- C4 (regime drift) — known structural, unchanged.
- DR-1 (LIVE dealing_range_gate=True / BT=False) — known structural, unchanged.
- EMA-history-depth divergence (210 cap in backtest, full ~399 in live) — pre-existing; affects 5M-sweep just as it would affect CRT. Recommend separate ticket.

### Critical divergences introduced by Sessions 1 + 2 (including Option H)

**ZERO.** No CRITICAL divergences introduced. All HIGH/MEDIUM findings from prior LBC re-audits are CLOSED or downgraded to Session-3 pre-work.

### GO/NO-GO recommendation

**GO** for the spec doc § 16 Session 3 plan, conditional on completing the three pre-work items in order:
1. LBC-H-3 residual (move CRT_TP2_RR/CRT_TP3_RR/CRT_FORWARD_BARS to crt_engine.py + extract cascade helper) — 5 min.
2. LBC-H-1 (live signals schema migration + source column) — 30 min.
3. LBC-H-2 (state_store persistence for consumed_sweeps) — 1 hour.

Total Session 3 pre-work: ~1.5 hours before any live wiring. After that, CRT is structurally indistinguishable from the 5M-sweep path from a parity standpoint.

### Cross-domain observations

**Observation:** The CRT scanner enters at `c5m["opens"][entry_bar]` (the open of the bar AFTER MSS confirmation). The 5M-sweep path uses similar open-of-next-bar entry. In live, the bot reacts to a closed candle and would request entry at MARKET on the following bar — but Binance market orders fill at the bid/ask spread, not the open. This is a backtest-bias issue affecting BOTH paths equally — not CRT-specific.

**Relevant Agent:** `backtest-bias-detector`
**Reason:** Worth a fresh look at the open-of-next-bar fill assumption across both paths. May or may not be material at the 5M scale; the 5M-sweep path has been live-monitored for months without obvious slippage divergence, so it's likely already within noise.

---

## Proactive improvement suggestions

**Suggestion:** Add a `test_crt_parity.py` that imports the same helpers from `crt_engine.py` that both `backtest.py` and (eventually) `crypto_alert.py` import — feed a fixture H4+5M dataset and assert that `detect_h4_crt`, `compute_crt_trade_economics`, and `crt_quality_to_confidence` produce byte-identical outputs to a pinned golden output.
**Why:** Catches any future drift in CRT economics/confidence the moment a constant changes. Static analysis can't catch a future `compute_crt_trade_economics` regression; a unit test can.
**Impact:** HIGH
**Effort:** Simple (~30 min — fixture H4+5M JSON, one assert block)

**Suggestion:** CI check that fails if `backtest.py` or `crypto_alert.py` defines any constant matching the pattern `^CRT_[A-Z_]+\s*=` that isn't imported from `crt_engine`.
**Why:** Prevents the architectural anti-pattern of duplicating CRT-specific constants across both paths.
**Impact:** MEDIUM
**Effort:** Simple (~10 min — single grep in pre-commit hook)

**Suggestion:** When Session 3 lands, add a parity smoke test: run live in DRY_RUN mode against the same historical 30-day OHLCV window the backtest used, diff the resulting signal counts per source. Acceptable drift: 0 for CRT (same code path), ≤1% for 5M-sweep (mid-bar live tick vs bar-close backtest gives a small fill-timing delta).
**Why:** Detects integration drift at the system level, not just unit level. The unit tests in suggestion 1 catch helper-level regressions; this catches main-loop wiring regressions.
**Impact:** HIGH
**Effort:** Medium (~2 hours — DRY_RUN mode plumbing in crypto_alert + fixture window)
