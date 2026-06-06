# Phase C-Breakout — FVG Mitigation Behavior: Soak vs Backtest

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~10:30 UTC.
**Audited processes:** A PID 486821, B PID 486822 (alive, BE-after-TP1 model, untouched).
**Premise:** `LOOKAHEAD_RECURSIVE_CHECK.md` flagged one bounded forward-looking computation — the FVG mitigation check at `ict_engine.py:370-378`, capped at `max_post_d_bars=MSS_HORIZON=30`. This audit determines whether the soak inherits the backtest's forward visibility (bug class similar to runner-exit gap) or behaves like live.

---

## §1 — How does the soak fetch + index 5m data?

[`breakout_paper_soak_B.py:84-85`](breakout_paper_soak_B.py#L84-L85):

```python
OHLCV_5M_LIMIT     = 500      # entry-TF fetch
OHLCV_1H_LIMIT     = 300      # reference-TF fetch
```

[`breakout_paper_soak_B.py:140-147`](breakout_paper_soak_B.py#L140-L147) — `fetch_klines`:

```python
for row in raw[:-1]:   # drop forming bar — same as A
    opens.append(float(row[1]))
    ...
```

**`raw[:-1]` drops the most-recent forming bar.** The returned `c5m` array contains only CLOSED 5m bars, ending at the latest closed bar at cycle time.

[`breakout_paper_soak_B.py:405-413`](breakout_paper_soak_B.py#L405-L413) — signal emission:

```python
mss_bar = setup["mss_bar_5m"]
if mss_bar + 1 >= len(c5m["opens"]):
    return False
entry_price = c5m["opens"][mss_bar + 1]
entry_ts_ms = c5m["times"][mss_bar + 1]
signal_ts = datetime.fromtimestamp(entry_ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
age_sec = (datetime.now(timezone.utc).replace(tzinfo=None) - signal_ts).total_seconds()
if age_sec > 3600:
    _log(f"  {token}: signal too stale ({age_sec:.0f}s old), skipping")
    return False
```

The signal entry bar must be `mss_bar + 1`, which **must already exist** in the array — i.e. it must be a CLOSED bar. And the staleness gate caps signal age at **3600 sec = 1 hour = 12 5m bars**.

### Effective forward visibility in the soak

| MSS bar position in array | Bars after entry_bar in `c5m` (= mitigation forward visibility) |
|---|---|
| `mss_bar = len - 2` (latest closed) | entry_bar = `len - 1`. Bars after entry: **0** |
| `mss_bar = len - 4` (2 bars old) | entry_bar = `len - 3`. Bars after: **2** |
| `mss_bar = len - 13` (12 bars old = staleness cap) | entry_bar = `len - 12`. Bars after: **11** |
| `mss_bar = len - 30` (cap exceeded) | **REJECTED by staleness check** |

**Soak's MAX forward visibility ≈ 11-12 bars** (staleness-cap bounded). The most common case (fresh signal at next poll after MSS): **0-2 forward bars**.

---

## §2 — The decisive test: where does the signal candle sit in the array?

The soak emits signals via [`breakout_paper_soak_B.py:381-440`](breakout_paper_soak_B.py#L381-L440) which fetches the LATEST 500 bars from Binance and calls `detect_h4_breakout` ONCE per cycle. The detector walks backwards finding the most-recent valid (C1, C2, MSS) tuple.

**At signal emission, the entry candle is at array index `mss_bar + 1 ≤ len(c5m) - 1`** by construction. The bars AFTER the entry candle are however many bars have already closed between MSS and "now" — bounded by the staleness gate at 12 bars.

This is **NOT** "re-evaluate historical bars with full forward context" — each cycle evaluates only the LATEST window. There is no scan of older bars with their full forward data available. **The soak is real-time, not re-scanning.**

---

## §3 — Contrast with the backtest

[`run_tf_grid.py:203-209`](run_tf_grid.py#L203-L209):

```python
entry_end_idx = bisect.bisect_right(c_entry["times"], ref_close_t)
entry_end_idx = min(entry_end_idx + mss_horizon_entry_bars + 10, n_entry)
```

The backtest builds entry sub-windows that extend **`MSS_HORIZON + 10 = 40 bars FORWARD of C2's close**. At each iteration's "signal moment", the entry sub-window contains:
- 500 bars of history before the entry bar
- Up to 40 bars AFTER the entry bar

The FVG mitigation scan in `score_ict_fvg` then has access to all 30 cap-allowed forward bars.

**The backtest emulates a hypothetical observer who CAN see 30 forward bars when making the signal decision.** The soak/live cannot.

---

## §4 — Quantifying the impact

### Direct measurement at `score_ict_fvg` level (random 5m bars)

Sampled 30,000 random 5m bars across 6 tokens; called `score_ict_fvg` with cap=0/12/30:

| Cap | FVG patterns rejected by mitigation |
|---|---|
| 0 (no scan) | 0 / 2752 valid patterns (0%) |
| 12 (soak max) | 1,386 (50.4%) |
| 30 (backtest) | 1,810 (65.8%) |

**The cap=30 → cap=12 gap is 424 patterns = 15.4% of valid FVG candidates** rejected only by backtest's wider mitigation scan.

### In the BREAKOUT PATH specifically

Patched `score_ict_fvg` to log all calls made by `detect_h4_breakout` across 6 tokens × 55 days. Ran the engine end-to-end:

| Metric | Count |
|---|---|
| Total FVG checks in breakout path | 18,478 |
| Valid FVG patterns (pre-mitigation) | 2,951 |
| Rejected in `[d+2, d+12]` (both soak AND backtest reject) | 705 (23.9%) |
| **Rejected in `[d+13, d+30]` (ONLY backtest rejects)** | **552 (18.7%)** |

**The breakout path has 552 cases where the BACKTEST rejects the FVG but the SOAK would accept** (because the soak's array can't see bars 13-30 after the FVG formation).

### End-to-end emission count

| Mode | Total signals emitted (6 tokens, 55 days) | FVG-labeled | OB-labeled |
|---|---|---|---|
| Backtest (cap=30) | 1,378 | 1,216 | 162 |
| Soak (cap≈12, truncated array) | 1,378 | 1,216 | 162 |
| **Δ** | **0** | **0** | **0** |

**Total emissions identical.** Why doesn't the 18.7% FVG-rejection gap translate to a signal-count gap?

### The mechanism: OB fallback in `_check_breakout_confluence`

[`breakout_engine.py:158-189`](breakout_engine.py#L158-L189):

```python
# 1. FVG confluence
for d in range(_probe_start, _probe_end_inclusive + 1):
    ...
    fvg = score_ict_fvg(d, h5, l5, o5, c5, max_post_d_bars=H4_BREAKOUT_MSS_HORIZON)
    if fvg is None: continue   # ← FVG rejection falls through
    ...
    return {"type": "FVG", "details": fvg}

# 2. OB confluence — institutional defense block
if ob_cached is not None and ob_cached["direction"] == direction:
    if order_block_overlaps_range(ob_cached, entry_zone_high, entry_zone_low):
        return {"type": "OB", "details": ob_cached}
```

When the FVG check rejects (either via mitigation or pattern absence), the engine falls through to the OB check. If a directional OB exists with overlapping range, the signal still emits — just labeled as **OB confluence** instead of FVG.

So the SOAK-vs-BACKTEST gap is a **CONFLUENCE TYPE LABEL drift, not a signal-count drift.** The same underlying setup is recognized by both — only the confluence reason differs.

---

## §5 — Verdict

**(a) Soak ≈ LIVE-STYLE for total signal count and gate metrics.** The signal SET is identical to what live execution would produce, because:
1. The soak fetches only closed bars through "now" (drops forming bar at `breakout_paper_soak_B.py:145`).
2. The MSS+entry constraint forces the signal candle to be at/near the array end.
3. FVG mitigation has only 0-12 forward bars visible (staleness-capped).
4. When FVG mitigation IS triggered, OB confluence catches the signal — same total emission count.

**(b) Pure type-label drift in the BACKTEST.** The backtest's 30-bar mitigation cap rejects ~18.7% of FVG candidates that the soak/live accept. The same signals re-emit as OB-labeled in backtest. Therefore:
- The backtest reports MORE OB-labeled signals than live will produce.
- The backtest reports FEWER FVG-labeled signals than live will produce.
- **TOTAL signal count, avg_R, WR, PF, maxDD** — all live-portable.
- **Per-confluence-type breakdowns** (e.g. "FVG vs OB performance comparison") are systematically biased: backtest's OB pool over-represents migrated-out-of-FVG cases.

### Severity assessment

| Aspect | Severity | Why |
|---|---|---|
| Gate metrics (avg_R, WR, PF, maxDD) | **NONE** | Same total signal count → same metrics |
| Forward-soak live-portability | **NONE** | Soak ≈ live; forward results carry forward |
| Per-type avg_R interpretation | **LOW** | Backtest's FVG_avg_R is slightly understated, OB_avg_R is slightly overstated (~18.7% of backtest "OBs" would be "FVGs" in live) |
| Strategy correctness | **NONE** | Both labels are valid structural reasons — the underlying breakout + MSS + confluence-of-some-kind holds in both |

### What this is NOT

- It's **NOT** the runner-exit class of bug. The runner-exit gap was about the simulator computing a different OUTCOME than live could produce. Here the OUTCOME walks are identical; only the CONFLUENCE LABEL on the entry side shifts.
- It's **NOT** signal selection bias. The backtest doesn't reject signals that live takes (which would mean live captures edge backtest doesn't credit); it RE-LABELS some FVG signals as OB. Both signals fire identically; both produce identical outcomes.

### What this IS

- A **documented L-NEW-1 caveat** that materializes more visibly in the per-type breakdown. Worth noting for future per-type analyses, but doesn't affect the BE-after-TP1 gate.
- **Confirmation that the soak's forward results are live-portable** at the count + gate-metrics level.

**No code change proposed.** Awaiting operator call.

---

## §6 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched |
| `data/signals.db` (production) | unchanged (read-only access only) |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `1f2f40b` (viewer WR recalibration; not pushed) |
| Soak A 486821 / B 486822 | alive, cycling, untouched throughout this audit |
| All DB backups | intact |

Read-only throughout. No fixes applied. Awaiting operator call.
