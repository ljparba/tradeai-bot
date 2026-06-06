# Soak B Reference Timeframe — Code vs Empirical Evidence

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~08:00 UTC.
**Audited processes:** A PID 486821, B PID 486822 (both alive on BE-after-TP1 model, untouched).

**Trigger:** entry_type label `H4_BREAKOUT_FVG_B` raised the question — is soak B actually using a 4H reference (matching the label), or correctly using 1H (matching its declared role as the 5m/1h validation soak)?

---

## §1 — Soak B's reference timeframe (code evidence)

### B's reference TF is explicitly 1h

[`breakout_paper_soak_B.py:102`](breakout_paper_soak_B.py#L102):

```python
REF_TF_INTERVAL = "1h"
```

[`breakout_paper_soak_B.py:386-387`](breakout_paper_soak_B.py#L386-L387) — the fetch:

```python
c5m = fetch_klines(symbol, "5m", OHLCV_5M_LIMIT)
c1h = fetch_klines(symbol, REF_TF_INTERVAL, OHLCV_1H_LIMIT)   # ← "1h" interval
```

[`breakout_paper_soak_B.py:394-397`](breakout_paper_soak_B.py#L394-L397) — the detect call, with an explicit inline comment:

```python
# The detector takes (ref_TF_data, entry_TF_data). Naming convention says
# `c4h` for the reference and `c5m` for the entry, but the function does
# NOT actually care about the timeframe — it just walks the arrays.
setup = detect_h4_breakout(c1h, c5m, token=token, consumed=consumed)
```

The variable is called `c1h`, the interval string fetched from Binance is `"1h"`, and the same engine function `detect_h4_breakout` is called — but with 1h candles instead of 4h.

### Soak A's reference TF is explicitly 4h (for direct comparison)

[`breakout_paper_soak.py:457`](breakout_paper_soak.py#L457):

```python
c4h = fetch_klines(symbol, "4h", OHLCV_4H_LIMIT)   # ← "4h" interval
```

[`breakout_paper_soak.py:464`](breakout_paper_soak.py#L464):

```python
setup = detect_h4_breakout(c4h, c5m, token=token, consumed=consumed)
```

### Single shared detector function

Both soaks `from breakout_engine import (detect_h4_breakout, ...)`. The detector itself is timeframe-agnostic — it walks whatever bar array is passed as the first argument. A passes 4h bars; B passes 1h bars. **Their detectors look at different timeframes.**

---

## §2 — Where the "H4_BREAKOUT" label comes from (and why it's misleading)

[`breakout_paper_soak_B.py:234`](breakout_paper_soak_B.py#L234) — the entry_type string assignment:

```python
f"H4_BREAKOUT_{confluence_type}_B"
```

For comparison, [`breakout_paper_soak.py:262`](breakout_paper_soak.py#L262):

```python
f"H4_BREAKOUT_{confluence_type}"
```

**The "H4" prefix is hard-coded in the f-string.** It's not derived from the actual reference TF — it comes from the engine's function name (`detect_h4_breakout`), which was originally written for 4h breakouts and kept its name when extended to be TF-agnostic.

This is a **naming artifact**, not a logic bug. The function and the label both say "H4" but the actual computation uses whatever TF the caller passes in.

The trailing `_B` suffix exists precisely so the operator (and the analyzer) can distinguish soak B's outputs from soak A's in the DB — but the `H4_` prefix is identical in both, which is the source of the confusion.

---

## §3 — DECISIVE empirical test: c1_time alignment

If soak B is actually using a 4h reference, every C1 zone timestamp MUST land on the 4h grid (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC). Any single C1 time off that grid PROVES the reference is 1h.

### B-soak signals (9 total — 8 OPEN, 1 CLOSED)

| id | tok | status | c1_time UTC | hour | 1h-aligned? | 4h-aligned? |
|---|---|---|---|---|---|---|
| 32 | XRP | OPEN | 2026-06-03 04:00:00 | 4 | YES | YES |
| 33 | HBAR | OPEN | 2026-06-03 04:00:00 | 4 | YES | YES |
| 34 | AVAX | OPEN | 2026-06-03 04:00:00 | 4 | YES | YES |
| 35 | LINK | OPEN | 2026-06-03 04:00:00 | 4 | YES | YES |
| 36 | BNB | OPEN | 2026-06-03 04:00:00 | 4 | YES | YES |
| 37 | TON | CLOSED | 2026-06-03 04:00:00 | 4 | YES | YES |
| 38 | ATOM | OPEN | 2026-06-03 04:00:00 | 4 | YES | YES |
| 39 | BCH | OPEN | 2026-06-03 04:00:00 | 4 | YES | YES |
| **40** | **XRP** | **OPEN** | **2026-06-03 05:00:00** | **5** | **YES** | **NO** ← decisive |

**XRP #40 fired with c1_time = 05:00:00 UTC (hour=5).** 5 is NOT on the 4h grid (which is hours 0, 4, 8, 12, 16, 20). This means C1 was a 1h candle, not a 4h candle. **Soak B is using a 1h reference.**

If B were actually 4h, XRP #40 could not exist with that c1_time — it would have to have been one of the 4h-grid hours.

The earlier 8 signals all happen to align to a 4h-grid hour (04:00) because that's when the correlated all-BUY cluster fired — but that's coincidence. The 9th signal (XRP #40 at 05:00) breaks the coincidence and reveals the true grid.

### Aligned counts

- Aligned to 1h boundary: **9/9** (100%)
- Aligned to 4h boundary: **8/9** (89%)

Under a 4h reference these would both be 9/9. The 89% disqualifies 4h.

---

## §4 — Cross-check against backtest TF_B

### Code: backtest TF_B is explicitly 1h

[`run_tf_grid.py:73-79`](run_tf_grid.py#L73-L79):

```python
{
    "id": "B_5m_1h",
    "entry_tf": "5m",
    "ref_tf":   "1h",
    "ref_bar_duration_ms": 1 * 60 * 60 * 1000,
    "entry_bar_duration_ms": 5 * 60 * 1000,
    "label": "5M / 1H (same entry, shorter ref)",
},
```

### Empirical: TF_B 720d backtest entry-hour distribution

Pulled all 12,090 TF_B 720d FRICTION (new model) signals and bucketed their entry timestamps by hour:

| hour | signals | hour | signals |
|---|---|---|---|
| 0 | 519 | 12 | 475 |
| 1 | 521 | 13 | 638 |
| 2 | 526 | 14 | 677 |
| 3 | 464 | 15 | 718 |
| 4 | 418 | 16 | 622 |
| 5 | 457 | 17 | 566 |
| 6 | 483 | 18 | 481 |
| 7 | 441 | 19 | 506 |
| 8 | 518 | 20 | 457 |
| 9 | 421 | 21 | 484 |
| 10 | 432 | 22 | 452 |
| 11 | 441 | 23 | 373 |

**All 24 hours have signals.** Under a 4h reference this would not be possible — only the 4h-grid hours could populate. Backtest TF_B is genuinely 1h.

### For comparison: TF_A 720d FRICTION (4h reference)

| hour | signals | hour | signals |
|---|---|---|---|
| 0 | 693 | 12 | 658 |
| 1 | 144 | 13 | 176 |
| 2 | 31 | 14 | 58 |
| 3 | **0** | 15 | **0** |
| 4 | 593 | 16 | 565 |
| 5 | 109 | 17 | 132 |
| 6 | 40 | 18 | 51 |
| 7 | **0** | 19 | **0** |
| 8 | 643 | 20 | 484 |
| 9 | 136 | 21 | 131 |
| 10 | 49 | 22 | 51 |
| 11 | **0** | 23 | **0** |

The 4h-reference signature: heavy on 4h-grid hours (0, 4, 8, 12, 16, 20 each have 484-693 signals), light on +1/+2 hours (the MSS_HORIZON allows entries up to 150 minutes after C2 close to spill into the next 1-2 hours), and ZERO on hours 3, 7, 11, 15, 19, 23 (impossible — would require the C2 close to be more than the MSS_HORIZON ago).

### Soak B vs backtest TF_B match

| Aspect | Backtest TF_B | Soak B | Match? |
|---|---|---|---|
| Reference TF code config | `"1h"` ([run_tf_grid:76](run_tf_grid.py#L76)) | `REF_TF_INTERVAL = "1h"` ([B:102](breakout_paper_soak_B.py#L102)) | ✓ |
| Detector invoked with | `c_ref` from `load_cached(tok, "1h")` | `c1h = fetch_klines(symbol, "1h", ...)` | ✓ |
| Entry TF | 5m | 5m | ✓ |
| C1 timestamps land on | Any hour 0-23 | XRP #40 at hour 5 (off 4h grid) | ✓ both 1h |

**Soak B is using exactly the same reference TF as backtest TF_B (1h). The forward validation is on the correct timeframe.**

---

## §5 — Verdict

**Case (a): correctly using a 1h reference with a cosmetically-wrong "H4" label artifact.** Benign — logic is sound.

### Evidence summary

| Question | Answer | Evidence |
|---|---|---|
| What reference TF does soak B fetch? | **1h** | `REF_TF_INTERVAL = "1h"` at L102; `fetch_klines(symbol, "1h", ...)` at L387 |
| What is passed to the detector? | **1h bars** (`c1h` variable) | L397 `detect_h4_breakout(c1h, c5m, ...)` |
| Where does "H4_BREAKOUT" label come from? | **Hard-coded prefix** in entry_type f-string | L234 `f"H4_BREAKOUT_{confluence_type}_B"` |
| Does the engine care about the label? | **No** — `detect_h4_breakout` is TF-agnostic | Confirmed by L394-396 inline comment |
| Empirical C1 hours from B's actual signals | **1h-aligned, NOT 4h-only** | XRP #40 at c1_time 2026-06-03 05:00 UTC (hour=5, OFF 4h grid) |
| Does soak B match backtest TF_B's reference TF? | **YES** — both 1h | Backtest TF_B has signals in all 24 hours; soak B has C1 at hour=5 |

### Recommended follow-up (LOW priority — cosmetic)

The `H4_BREAKOUT` prefix in the entry_type label is misleading and should ideally be fixed for clarity:

| Location | Suggested label change |
|---|---|
| `breakout_paper_soak.py:262` | `f"H4_BREAKOUT_{confluence_type}"` → `f"H4_BREAKOUT_{confluence_type}"` (keep — A is genuinely 4h) |
| `breakout_paper_soak_B.py:234` | `f"H4_BREAKOUT_{confluence_type}_B"` → **`f"H1_BREAKOUT_{confluence_type}_B"`** or `f"REF_BREAKOUT_{confluence_type}_B"` |
| `run_tf_grid.py:268` | `f"H4_BREAKOUT_{setup['confluence']['type']}_TF"` → similar adjustment for TF_B variant |

This is a LOW priority because:
- The source tag (`H4_BREAKOUT_PAPER_SOAK_B` vs `_TF_B_5m_1h_*`) is the actual differentiator for per-soak filtering — that one is unambiguous and correct.
- The viewer's existing per-token / per-source analysis doesn't depend on the entry_type prefix.
- Changing the entry_type label retroactively would require a DB migration on prior backtest_signals rows; doing it forward-only would split the per-type rollups.
- The operator can ignore the "H4" prefix when reading B's signals — it's a known cosmetic legacy from the engine's function name.

**Severity: LOW (cosmetic only). No fix proposed at this time.**

---

## §6 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched |
| `data/signals.db` (production) | unchanged (read-only access only) |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `1f2f40b` (viewer WR recalibration commit; not pushed) |
| Both soaks (A 486821, B 486822) | alive, cycling, untouched throughout this audit |

Awaiting operator call. No fixes applied.
