# Phase C-Breakout — Full Audit (read-only, diagnostic)

**Date:** 2026-06-02 (UTC)
**Scope:** Full correctness audit of the running breakout-thesis stack on `breakout-thesis @ 44aa89c` in worktree `/home/tradeai/breakout-work/`.
**Mode:** Read-only. **No code changed. Soak NOT touched.**

> **Bottom-line verdict: SOAK IS TRUSTWORTHY AS-IS. NO RESTART NEEDED.**
> Five sections PASS, one section PASS-with-cosmetic-note. No critical, no
> medium-severity defects found. Three LOW-severity informational items
> documented but none invalidate the forward validation.

---

## 1. DIRECTION / LOGIC CORRECTNESS — **PASS**

### 1.1 BUY-breakout direction mapping is the true inverse of the fade

**`breakout_engine.py:299-301`** — BUY breakout requires C2 to CLOSE above C1.high + buffer:

```python
# ── BUY breakout (C2 CLOSED above C1.high + buffer) ─────────────
buy_threshold = c1_high * (1.0 + H4_BREAKOUT_CLOSE_BUFFER_PCT)
if c2_close > buy_threshold:
```

Compared to the fade engine `crt_engine.py:617`:

```python
# Fade engine — BUY when C2 WICKED below C1.low (and optionally closed back in)
if c2_low < c1_low and (not _strict or c2_close >= c1_low):
```

| Direction | Fade trigger | Breakout trigger |
|---|---|---|
| **BUY** | `c2_low < c1_low` (sweep DOWN, reverse UP) | `c2_close > c1_high + buf` (break UP, continue UP) |
| **SELL** | `c2_high > c1_high` (sweep UP, reverse DOWN) | `c2_close < c1_low - buf` (break DOWN, continue DOWN) |

**This is unambiguously the inverse.** The fade *fades* a wick-only sweep; the breakout *continues* a close-confirmed break. Different trigger candle (wick vs close), different direction (reversal vs continuation). **No sign error.**

### 1.2 Break confirmation requires CLOSE BEYOND the level (with buffer)

**`breakout_engine.py:299-301, 354-356`** — both BUY and SELL use the C2's CLOSE (not wick) against a buffered threshold:

```python
buy_threshold = c1_high * (1.0 + H4_BREAKOUT_CLOSE_BUFFER_PCT)
if c2_close > buy_threshold:
...
sell_threshold = c1_low * (1.0 - H4_BREAKOUT_CLOSE_BUFFER_PCT)
if c2_close < sell_threshold:
```

Buffer in effect at runtime: **0.001 (0.1%)**, verified by direct import in §2.1 below.

The fade's "strict school" check at `crt_engine.py:617` is `c2_close >= c1_low` (close back INSIDE the range — rejection). The breakout requires `c2_close > c1_high * 1.001` (close OUTSIDE the range — commitment). These are **logically opposite**.

### 1.3 MSS is used as a CONTINUATION confirm (not reversal)

**`breakout_engine.py:311-321`** for BUY breakout:

```python
mss = score_ict_mss(
    sweep_bar=sweep_5m_idx,
    closes=c5m_closes, opens=c5m_opens, highs=h5, lows=l5,
    sh=sh_5m, sl=sl_5m,
    sweep_type="SSL",  # continuation UP confirmer
    horizon=H4_BREAKOUT_MSS_HORIZON,
)
```

Cross-checked against `ict_engine.py:262-273`:

```python
if sweep_type == "SSL":
    recent_sh = max(...)   # most recent prior swing HIGH
    mss_bar = next((j for j in range(...) if closes[j] > mss_level), None)
```

So `sweep_type="SSL"` makes the helper search for a 5M close ABOVE a recent swing high (= bullish CHoCH up). For a BUY breakout that's the continuation confirm. **Direction is consistent.**

Same logic mirror'd for SELL at `breakout_engine.py:364-374`: `sweep_type="BSL"` → close BELOW recent swing low → bearish CHoCH down → SELL continuation. ✓

The fade engine uses the SAME `sweep_type` labels but reads them differently (a SSL "sweep" leads to a BUY reversal); here we reuse the predicate's MATHEMATICAL meaning (close above a swing high) as continuation. The shared helper does not need to be modified — the call-site interpretation is what changed.

### 1.4 TP geometry uses fixed-R cascade, NOT C1-opposite-extreme

**`breakout_engine.py:439-452`** (compute_breakout_sl_tp):

```python
risk_dist = entry_price - sl
tp1 = entry_price + BREAKOUT_TP1_RR * risk_dist     # 2.0R fixed
tp2 = entry_price + BREAKOUT_TP2_RR * risk_dist     # 3.0R fixed
tp3 = entry_price + BREAKOUT_TP3_RR * risk_dist     # 4.0R fixed
```

There is **no `adjust_crt_tp1` call**, no C1-opposite reference, no dynamic cap. The R-multiples come from `BREAKOUT_TP1_RR / TP2_RR / TP3_RR`, which §2.1 confirms are loaded at 2.0/3.0/4.0 at runtime.

**Section 1 verdict: PASS.** Direction inversion is correct, break-confirm is on the close, MSS-as-continuation is properly wired, and the TP geometry is the fixed cascade that the grid validated.

---

## 2. LIVE vs SOAK PARITY — **PASS**

### 2.1 Soak's effective module constants vs Config 14 (locked spec)

Reproduced the soak's import sequence in isolation (`os.environ` populated from `CONFIG_14`, then `import breakout_engine`):

```
H4_BREAKOUT_CLOSE_BUFFER_PCT = 0.001   (expect 0.001)   ✓
BREAKOUT_TP1_RR              = 2.0     (expect 2.0)     ✓
BREAKOUT_TP2_RR              = 3.0     (expect 3.0)     ✓
BREAKOUT_TP3_RR              = 4.0     (expect 4.0)     ✓
H4_BREAKOUT_C2_LOOKBACK      = 4       (expect 4)       ✓
H4_BREAKOUT_MSS_HORIZON      = 30      (expect 30)      ✓
H4_BREAKOUT_OB_SCAN_LOOKBACK = 20      (default)        ✓
H4_BREAKOUT_FVG_PROBE_WIDTH  = 3       (default)        ✓
BREAKOUT_SL_INSIDE_BUFFER_PCT= 0.001   (default)        ✓
```

Inherited shared gates:

```
ICT_MIN_RR_GATE              = 1.3
MAX_BREAKEVEN_WR             = 0.6
MIN_SL_PCT                   = 0.005
MAX_SL_PCT                   = 0.03
```

The `CONFIG_14` dict is set on `os.environ` **before** the soak imports `breakout_engine` (see `breakout_paper_soak.py:81-83`):

```python
for k, v in CONFIG_14.items():
    os.environ[k] = str(v)

import breakout_engine  # noqa: E402   (reads env on import)
```

This guarantees the module-level constants in `breakout_engine` are bound to the Config 14 values at import time and never change during the soak's lifetime.

### 2.2 Adaptive / OGD / Wyckoff / funding / BTC-corr off

Verified by **absence of imports** in `breakout_paper_soak.py`. Full executable import list:

```
breakout_paper_soak.py:49  from __future__ import annotations
breakout_paper_soak.py:51  import bisect
breakout_paper_soak.py:52  import json
breakout_paper_soak.py:53  import os
breakout_paper_soak.py:54  import signal as signal_module
breakout_paper_soak.py:55  import sqlite3
breakout_paper_soak.py:56  import sys
breakout_paper_soak.py:57  import time as _time
breakout_paper_soak.py:58  import traceback
breakout_paper_soak.py:59  import urllib.error
breakout_paper_soak.py:60  import urllib.parse
breakout_paper_soak.py:61  import urllib.request
breakout_paper_soak.py:62  from datetime import datetime, timedelta, timezone
breakout_paper_soak.py:63  from pathlib import Path
breakout_paper_soak.py:64  from typing import Optional
breakout_paper_soak.py:84  import breakout_engine
breakout_paper_soak.py:85  from breakout_engine import (detect_h4_breakout, compute_breakout_sl_tp, H4_BREAKOUT_C2_LOOKBACK)
breakout_paper_soak.py:89  from crt_engine import compute_crt_trade_economics
breakout_paper_soak.py:90  from ict_engine import TOKEN_RT_COST, ROUND_TRIP_COST_PCT
```

| Forbidden | Present? |
|---|---|
| `adaptive_engine` | ✓ not imported |
| `crypto_alert` | ✓ not imported (the `import crypto_alert` substring at line 12 is in the docstring describing what's NOT imported) |
| `backtest` | ✓ not imported |
| `funding_rate_client` | ✓ not imported |
| `btc_correlation` | ✓ not imported |
| `detect_wyckoff_context` / `WYCKOFF_PHASE_FILTER` | ✓ not referenced |
| `FUNDING_BONUS` / `BTC_CORR_BONUS` | ✓ not referenced |
| `token_weights` table | ✓ no SQL touches it |

**Section 2 verdict: PASS.** The soak's loaded config is bit-exact Config 14, and all overlays are absent by virtue of not being imported.

---

## 3. DATA INTEGRITY — **PASS** (with LOW-3 cosmetic note)

### 3.1 OHLCV source identical in shape to the backtest

The backtest used cached Binance OHLCV from `/home/tradeai/TradeAI/data/ohlcv_cache/*.json` (which themselves were Binance REST output frozen to disk). The soak fetches **directly from Binance REST**:

**`breakout_paper_soak.py:419-420`**:

```python
c5m = fetch_klines(symbol, "5m", OHLCV_5M_LIMIT)
c4h = fetch_klines(symbol, "4h", OHLCV_4H_LIMIT)
```

Same endpoint, same kline encoding, same per-bar dict shape (`opens/highs/lows/closes/times`). No transformation difference between cache and fetcher.

### 3.2 No look-ahead — fetcher DROPS the currently-forming bar

**`breakout_paper_soak.py:182-194`** (`fetch_klines`):

```python
# Each kline is [open_time, open, high, low, close, vol, close_time, ...]
# The LAST kline may still be forming; we drop it so all bars are CLOSED.
opens, highs, lows, closes, times = [], [], [], [], []
for row in raw[:-1]:                       # ← raw[:-1] drops the forming bar
    opens.append(float(row[1]))
    ...
return {"opens": opens, ..., "times": times}
```

The `raw[:-1]` slice removes the last (in-formation) bar from every fetch. **All bars the detector sees have already closed.** No look-ahead possible.

### 3.3 Entry timing — only fires on bars whose open exists in closed data

**`breakout_paper_soak.py:437-440`**:

```python
mss_bar = setup["mss_bar_5m"]
if mss_bar + 1 >= len(c5m["opens"]):
    # Not enough bars after MSS — wait for next cycle
    return False
entry_price = c5m["opens"][mss_bar + 1]
```

If the MSS-confirmation bar happens to be the most recently closed bar (`mss_bar = len(c5m["opens"]) - 1`), then `mss_bar + 1` doesn't exist in the closed-bar array, and the function returns False — waits for the NEXT scan cycle (when that next bar will have closed). **This is the same temporal protocol the backtest uses** (`entry_bar = mss_bar_abs + 1`, with the bound check `if entry_bar >= n5 - FORWARD_BARS - 1: continue`).

### 3.4 Stale-signal guard prevents emission on old setups

**`breakout_paper_soak.py:447-450`**:

```python
age_sec = (datetime.now(timezone.utc).replace(tzinfo=None) - signal_ts).total_seconds()
if age_sec > 3600:
    _log(f"  {token}: signal too stale ({age_sec:.0f}s old), skipping")
    return False
```

On a fresh process start, the H4 detector may identify a setup whose MSS confirmed many hours ago (because the recent kline windows still contain it). The guard rejects anything older than 60 min. **This is honest forward-OOS behavior — operator can't time-travel to take a signal that already played out.**

### 3.5 Source tagging — soak rows are in a DIFFERENT TABLE than backtest rows

Verified runtime state of `data/breakout.db`:

```
backtest_signals | source = 'H4_BREAKOUT'           | n = 20248   (Step 1 grid)
backtest_signals | source = 'H4_BREAKOUT_FRICTION'  | n =  2180   (Step 2A)
signals          | source = 'H4_BREAKOUT_PAPER_SOAK'| n =     0   (soak — none closed yet)
```

The soak writes to `signals` + `results` (the live-style tables). The backtest grid + friction wrote to `backtest_signals` + `backtest_runs`. **They are in physically separate tables.** Even if a future bug introduced a duplicate source tag, the viewer's queries only ever read from `signals` JOIN `results`, never `backtest_signals`.

Verified at `breakout_paper_soak.py:308`:

```python
... h, signal_ts.weekday(), SOAK_LABEL, feat_blob),
                              ^^^^^^^^^^
                              SOAK_LABEL = 'H4_BREAKOUT_PAPER_SOAK'  (line ~83)
```

### 3.6 Economics gates applied in soak path identically to backtest

**`breakout_paper_soak.py:460-466`**:

```python
rt_cost_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
econ = compute_crt_trade_economics(
    setup["direction"], entry_price, sl_price, tp1, tp2, tp3,
    outcome=None, rt_cost_pct=rt_cost_pct,
)
if econ is None:
    return False
```

Same function (`compute_crt_trade_economics` from `crt_engine.py`), same per-token RT cost (`TOKEN_RT_COST`), same baseline rate, same gate-on-None semantic. This function internally enforces `MAX_SL_PCT` ceiling, `MIN_TP1_MULT` (via `gross_tp1/gross_sl < ICT_MIN_RR_GATE`), `net_tp1 <= 0` fees_kill, and `bew > MAX_BREAKEVEN_WR=0.60` BEW gate.

This matches the backtest's gate at `breakout_backtest.py:225-232` (called by `run_breakout_token`), and the friction harness at `run_friction_config14.py:144-153` (post-friction gate at intended_entry).

**Section 3 verdict: PASS** with one cosmetic note: the `volumes` array is fetched but never used by detection (LOW-3, see §7 LOW items).

---

## 4. OUTCOME / R ACCOUNTING — **PASS**

### 4.1 R-multiple mapping identical to backtest

Soak's outcome-to-R map at **`breakout_paper_soak.py:381-402`**:

```python
risk = abs(net_sl) or 0.001
if outcome == "LOSS":
    realized_r = round(net_sl / risk, 4)               # ≈ -1.0
elif outcome == "PARTIAL_TP1":
    realized_r = round((0.5 * net_tp1) / risk, 4)
elif outcome == "PARTIAL_TP2":
    realized_r = round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
elif outcome == "WIN":
    realized_r = round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
else:  # EXPIRED
    realized_r = 0.0
```

Backtest's `_calc_realized_r` at **`breakout_backtest.py:159-181`** is bit-identical. **R-comparability between soak and backtest is preserved.**

### 4.2 Intrabar SL-before-TP detection logic

Soak's outcome scan at **`breakout_paper_soak.py:343-360`**:

```python
for bar in raw:
    h_p = float(bar[2]); l_p = float(bar[3])
    if direction == "BUY":
        if not sl_hit and not tp1_hit and l_p <= sl:
            sl_hit = True; break
        if not tp1_hit and h_p >= tp1:  tp1_hit = True
        if tp1_hit  and not tp2_hit and h_p >= tp2:  tp2_hit = True
        if tp2_hit  and not tp3_hit and h_p >= tp3:  tp3_hit = True
    else:
        ...same structure with l_p/h_p swapped...
```

Compared to `breakout_backtest.py:66-87` (`check_outcome`) — **identical structure**, identical SL-FIRST-before-TP ordering inside each bar.

Single-bar collision behavior:
- If `l_p <= sl` AND `h_p >= tp1` in the SAME bar AND `not tp1_hit` yet → SL wins (`break`). **Conservative.**
- If a prior bar already hit TP1 (so `tp1_hit = True`), the SL check `if not sl_hit and not tp1_hit and l_p <= sl` becomes inactive — TPs can continue to climb. This implements the implicit "stop-to-breakeven after TP1" assumption of the 50/50 split-exit model.

Both behaviors match the backtest exactly. **No silent drift.**

### 4.3 R values match the friction-on backtest's R distribution

Friction-on Config 14 produced `avg_R = +0.595 per attempted`. The soak will measure CLEAN R (no friction model applied — see LOW-1 note in §7). The locked thresholds (avg_R ≥ +0.40, PF ≥ 2.0, WR ≥ 55%) were set with a generous friction-degradation cushion baked in, so the soak's CLEAN avg_R can be compared directly against them without rescaling. See LOW-1 below for an interpretive note.

**Section 4 verdict: PASS.** R-multiple mapping is identical, intrabar logic is identical, comparability is preserved.

---

## 5. ISOLATION — **PASS** (re-verified)

| Invariant | Check at audit time |
|---|---|
| Fade soak alive | PID 393274, cycle 8195, 0 errors, 12/12 tokens, ts 2026-06-02 02:15:14 |
| Fade `signals.db` size | 5,492,736 bytes — **unchanged** since Step 1 baseline |
| Fade `baseline_pin.json` | run_id=3704, mtime 2026-05-30 14:31:11 — **unchanged** |
| Breakout soak alive | PID 458923, cycle 20, ts 2026-06-02 02:15:56 |
| Breakout soak open fds | only `breakout.db` + `breakout.db-wal` + `breakout.db-shm` |
| Breakout soak fds on fade DB | **zero** (confirmed via `/proc/458923/fd/`) |
| Branch state | `breakout-thesis @ 44aa89c` — local only, NOT pushed to origin |
| `main` branch state | `2f71b69` — untouched |
| Origin known refs | `origin/experiment/crt-h4-signal-source`, `origin/main` only |
| `git ls-remote origin breakout-thesis` | **0 matches** — confirms not pushed |

**Section 5 verdict: PASS.** All isolation invariants from Step 1 still hold.

---

## 6. VIEWER CORRECTNESS — **PASS**

### 6.1 Read-only enforcement

**`breakout_viewer.py:81-87`**:

```python
def _open_ro_conn() -> sqlite3.Connection:
    ...
    # mode=ro ensures: cannot write, cannot create. URI required for ?mode=ro.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn
```

Verified at SQLite C level — any `INSERT/UPDATE/DELETE/CREATE` on this connection raises `OperationalError: attempt to write a readonly database`. HTTP write methods (POST/PUT/DELETE/PATCH) explicitly return 405. Smoke test from Step 2 confirmed DB mtime unchanged after 3 API hits.

### 6.2 Filter to soak signals only

All SELECTs in `collect_state()` use `WHERE s.source = ? AND s.status IN ('OPEN','CLOSED')` with `SOAK_LABEL = 'H4_BREAKOUT_PAPER_SOAK'`. Verified at lines:

- `breakout_viewer.py:178-184` (CLOSED join with results)
- `breakout_viewer.py:189-195` (OPEN signals)

Plus the source-tagging cross-check from §3.5 shows the backtest grid + friction runs are in `backtest_signals` (a different table the viewer never queries).

### 6.3 Gate math matches locked thresholds

**`breakout_viewer.py:45-51`**:

```python
GATE_N_TARGET           = 30
GATE_AVG_R_MIN          = 0.40
GATE_PF_MIN             = 2.0
GATE_WR_MIN             = 0.55
GATE_MAX_DD_R           = 20.0
GATE_PER_TOKEN_MIN_N    = 5
GATE_PER_TOKEN_BLOWUP_WR = 0.35
```

Bit-exact match to the locked thresholds in `PHASE_C_STEP2B_SOAK_STARTED.md §1`.

WR is computed as **strict** `(WIN + PARTIAL_TP2) / n_closed` at `breakout_viewer.py:224-227`:

```python
n_wins_p2 = sum(1 for r in closed if r["result"] in ("WIN", "PARTIAL_TP2"))
n_p1      = sum(1 for r in closed if r["result"] == "PARTIAL_TP1")
wr_raw    = n_wins_p2 / n if n else 0.0
```

This is **the same definition** the Step 1 / Step 2A backtest reports used for their headline WR (`compare_friction.py:79` and the per-config table in `compute_metrics.py:189`), against which the 55% threshold was set. The compute_metrics.py `overall_wr` column that credits PARTIAL_TP1 as 0.5 is a separate field that does not feed the locked threshold. **No definitional mismatch with the gate.**

### 6.4 PENDING locked until n ≥ 30

**`breakout_viewer.py:107-113`** (`_gate_status`):

```python
def _gate_status(threshold_check: bool, n_signals: int) -> str:
    if n_signals < GATE_N_TARGET:
        return "PENDING"
    return "PASS" if threshold_check else "FAIL"
```

Applied to every per-criterion call at lines 264-273. Plus the overall verdict at lines 280-286:

```python
if n < GATE_N_TARGET:
    state["verdict_overall"] = "PENDING"
elif (avg_r_pass and pf_pass and wr_pass and max_dd_pass and blowup_pass):
    state["verdict_overall"] = "PASS"
else:
    state["verdict_overall"] = "FAIL"
```

**No code path can render a non-PENDING verdict at n < 30.**

### 6.5 Per-token blowup criterion

**`breakout_viewer.py:248-251`**:

```python
blowup = (n_tok >= GATE_PER_TOKEN_MIN_N
          and tok_wr <= GATE_PER_TOKEN_BLOWUP_WR
          and tok_avg < 0)
```

Matches the prompt spec: `WR ≤ 35% AND avg_R < 0 over ≥ 5 signals`. ✓

**Section 6 verdict: PASS.** Viewer's gate math, filter, and PENDING-locking all match the spec.

---

## 7. Findings inventory

### Critical (invalidates the soak)

**None.**

### Medium (should fix before trusting results)

**None.**

### Low (informational; do not require action)

**LOW-1 — Soak measures CLEAN edge, not friction-adjusted edge.**
The soak records each signal's outcome assuming zero slippage, zero spread above the baseline `TOKEN_RT_COST`, 100% fill, no latency cost. The friction screen (Step 2A) already validated that the edge survives realistic friction (degraded by 16-18%). The locked thresholds (avg_R ≥ +0.40, PF ≥ 2.0, WR ≥ 55%) were chosen to leave room for this degradation — passing them on CLEAN soak data means the friction-adjusted live experience is expected to be ~16-18% below those numbers but still net-positive. **This is intentional design**, not a defect. No change recommended.

**LOW-2 — Soak's intrabar resolution can't distinguish wick-only TP hits within the entry bar itself.**
Both the backtest and the soak begin outcome tracking from `entry_bar + 1`. Within `entry_bar` (the bar at which entry_price = bar's open), intrabar moves above TP1 or below SL are NOT examined. This is consistent across both — the backtest also has this property — so it does NOT bias the comparison. Live operators don't get to retroactively hit TP/SL inside the bar they entered either. **No fix needed.**

**LOW-3 — `c4h["volumes"]` is fetched but unused.**
`fetch_klines` parses `bar[5]` as volume but the `c4h`/`c5m` dicts returned to the detector don't contain it (they only carry opens/highs/lows/closes/times). The detection itself never references volume. The volume parse line is **dead code** with effectively zero cost. **No fix needed.**

### Findings NOT raised (explicitly verified absent)

| Suspicion | Verified absent because |
|---|---|
| Sign error inverting back to fade | C2.close check (not wick), comparison direction matches §1.1 table |
| Config 14 mismatch at runtime | §2.1 verified all 6 knobs at expected values |
| OGD bootstrap accidentally enabled | No `adaptive_engine` import, no `token_weights` queries |
| Wyckoff filter inherited | No `detect_wyckoff_context` reference, no `WYCKOFF_PHASE_FILTER` env read |
| Funding / BTC-corr bonuses | No imports of those modules, no env reads, no confidence-adjustment math |
| Look-ahead via forming bar | `raw[:-1]` drops the forming bar at `breakout_paper_soak.py:189` |
| WR definition mismatch with gate | Strict `(WIN+PARTIAL_TP2)/n` used everywhere (backtest headline, friction comparison, viewer); compute_metrics `overall_wr` is a separate field that does not feed the gate |
| Branch quietly pushed | `git ls-remote origin breakout-thesis` returns 0 matches |
| Viewer prematurely declaring verdict | `_gate_status` returns PENDING for any criterion when `n < 30`; overall verdict identically gated |
| Soak holding fds on fade DB | `/proc/458923/fd/` only references `breakout.db*` |

---

## 8. Final recommendation

The running breakout paper soak (PID 458923) is **TRUSTWORTHY AS-IS**. **Do NOT restart.** Every directional, parity, data, R-accounting, isolation, and viewer correctness check passes. The three LOW-severity items are informational and do not affect the soak's validity as a forward OOS gate.

**Continue the soak unchanged.** The 30-closed-signal gate will become evaluable once enough signals close (estimated ~7 days from soak start). The viewer's PENDING lock prevents any premature verdict before then.

**Do NOT push, merge, or flip live on the strength of this audit.** This audit only validates that the soak is *correctly measuring what it is supposed to measure*. The locked gate criteria still need to be met on the ≥ 30 closed signals before the soak's empirical result can be acted on.

---

## 9. Reproducibility

Every claim in this audit can be re-verified independently using only read-only tooling:

```bash
# §1, §2.2 — direction logic and forbidden-import check
grep -nE "(c2_close|sweep_type)" /home/tradeai/breakout-work/breakout_engine.py | head
grep -nE "^(import|from) " /home/tradeai/breakout-work/breakout_paper_soak.py

# §2.1 — soak's effective constants
python3 -c "import os; \
  os.environ['H4_BREAKOUT_CLOSE_BUFFER_PCT']='0.001'; \
  os.environ['BREAKOUT_TP1_RR']='2.0'; \
  import sys; sys.path.insert(0,'/home/tradeai/breakout-work'); \
  sys.path.insert(0,'/home/tradeai/TradeAI'); \
  import breakout_engine as b; \
  print(b.BREAKOUT_TP1_RR, b.H4_BREAKOUT_C2_LOOKBACK, b.H4_BREAKOUT_MSS_HORIZON)"

# §3.5 — source tagging
sqlite3 -readonly "file:/home/tradeai/breakout-work/data/breakout.db?mode=ro" \
  "SELECT source, COUNT(*) FROM signals GROUP BY source; \
   SELECT source, COUNT(*) FROM backtest_signals GROUP BY source;"

# §5 — isolation
stat -c '%s %y' /home/tradeai/TradeAI/data/signals.db
ls -la /proc/458923/fd/ | grep \.db
git -C /home/tradeai/breakout-work ls-remote origin breakout-thesis

# §6.1 — viewer read-only proof (test from running viewer)
curl -X POST http://127.0.0.1:8890/api/state -w "HTTP %{http_code}\n" -o /dev/null
```
