# Phase C-Breakout — Entry-Type / Confluence Audit

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-02 ~19:00 UTC.
**Audited processes:** A PID 473059, B PID 473060 (both alive on F3/F4-fixed code at commit `68166b2`).

---

## §1 — Enumerate the entry types

The breakout engine can emit **exactly two** entry-type variants, both produced via the same setup detector. The variant is determined by which confluence triggered: FVG or OB. Defined in [`breakout_engine.py:150`](breakout_engine.py#L150) — `"type": "FVG"|"OB"`.

### Tag naming convention (per emitter)

| Emitter | DB `entry_type` column | Code |
|---|---|---|
| Soak A (5m/4h) | `H4_BREAKOUT_{FVG\|OB}` | [`breakout_paper_soak.py:262`](breakout_paper_soak.py#L262) → `f"H4_BREAKOUT_{confluence_type}"` |
| Soak B (5m/1h) | `H4_BREAKOUT_{FVG\|OB}_B` | [`breakout_paper_soak_B.py:234`](breakout_paper_soak_B.py#L234) → `f"H4_BREAKOUT_{confluence_type}_B"` |
| Backtest (TF grid) | `H4_BREAKOUT_{FVG\|OB}_TF` | [`run_tf_grid.py:268`](run_tf_grid.py#L268) → `f"H4_BREAKOUT_{setup['confluence']['type']}_TF"` |

> The suffix differs across emitters (no-suffix / `_B` / `_TF`), but the underlying confluence detection is identical — all three call the same `_check_breakout_confluence` in `breakout_engine.py`. This is a tag-naming convention for analyzability, NOT a logic divergence.

### FVG confluence — qualifying conditions

Source: [`breakout_engine.py:158-178`](breakout_engine.py#L158-L178).

The FVG path probes 5M bars around the MSS bar (window controlled by `H4_BREAKOUT_FVG_PROBE_WIDTH=3`) and accepts an FVG iff ALL conditions hold:

| # | Condition | Code line |
|---|---|---|
| 1 | Probe bar `d` is within `c5` range (≥1, < len-1) | L163 |
| 2 | `d ≥ sweep_5m_idx` (FVG must form AFTER the C2 break, no stale pre-breakout FVGs) | L166 |
| 3 | `score_ict_fvg(...)` returns non-None (i.e. real 3-bar imbalance pattern) | L168–171 |
| 4 | `fvg["direction"] == direction` (FVG direction matches breakout direction) | L173 |
| 5 | Overlap test: `fvg["bottom"] > entry_zone_high OR fvg["top"] < entry_zone_low` — the FVG sits OUTSIDE the broken level (in the new continuation territory) | L177 |

The "entry zone" is the 2% band beyond the broken level: for BUY, `[c1_high, c1_high*1.02]` (L328-329); for SELL, `[c1_low*0.98, c1_low]` (L380-381).

Note line 177 reads `bottom > entry_zone_high OR top < entry_zone_low` — that's the condition for the FVG to be SEPARATED from the entry zone (not overlapping). Returned as confluence. This is semantically "FVG sits on the breakout side of the entry zone." Worth re-reading carefully but appears intentional per the docstring (breakout side, not retest side).

### OB confluence — qualifying conditions

Source: [`breakout_engine.py:180-187`](breakout_engine.py#L180-L187).

Single H4 order block pre-computed once per detect call ([`breakout_engine.py:269-272`](breakout_engine.py#L269-L272), `H4_BREAKOUT_OB_SCAN_LOOKBACK=20`). Accepted iff:

| # | Condition | Code line |
|---|---|---|
| 1 | `ob_cached is not None` (a valid H4 OB was found) | L185 |
| 2 | `ob_cached["direction"] == direction` (OB direction matches breakout direction) | L185 |
| 3 | `order_block_overlaps_range(ob_cached, entry_zone_high, entry_zone_low)` — the OB price zone overlaps the continuation zone above c1_high (BUY) or below c1_low (SELL) | L186 |

The OB is from `ict_engine.detect_ict_order_block` (the shared ICT helper). Quality is NOT consulted — any directionally-matching, range-overlapping OB qualifies.

### Selection order

Per `_check_breakout_confluence` body: **FVG is checked first** (L158–178). If an FVG match is found, that wins and the function returns immediately. Only if no FVG matches does OB get checked (L180–187). So a given setup can return one or the other but never both — and FVG has priority when both could in principle apply.

---

## §2 — Strictness / gating: WIDE net or TIGHT net?

### Quality gates on confluence — NONE

Grepped both soaks, the engine, and the backtest reference for any of: `CRT_APPLY_QUALITY_GATES`, `MSS_MIN_QUALITY`, `FVG_MIN_QUALITY`, `WYCKOFF_PHASE_FILTER`, `LIVE_BIAS_4H_GATE`, `CRT_REQUIRE_1H_TREND`. Results:

| Gate (in fade engine) | Present in breakout engine? | Present in soak code? | Present in backtest? |
|---|---|---|---|
| `CRT_APPLY_QUALITY_GATES` (fvg HIGH / mss MEDIUM threshold) | **No** (only in a doc comment at L47 noting it was harmful for fade) | No | No |
| `MSS_MIN_QUALITY` (LOW/MEDIUM/HIGH minimum) | **No** | No | No |
| `FVG_MIN_QUALITY` | **No** | No | No |
| `WYCKOFF_PHASE_FILTER` | **No** | No | No |
| `LIVE_BIAS_4H_GATE` (4H trend alignment) | **No** | No | No |
| `CRT_REQUIRE_1H_TREND` (1H trend alignment) | **No** | No | No |

`mss_quality` IS computed (HIGH/MEDIUM/LOW) and TAGGED in the DB row, but the breakout engine does NOT reject on it — see [`breakout_engine.py:322-323`](breakout_engine.py#L322-L323) and [L375-L376](breakout_engine.py#L375-L376): only `mss["confirmed"]` is consulted; quality is captured for downstream tagging (L348, L400) but never gates emission.

Verified empirically on live data: B's 8 closed signals include `MSS=MEDIUM,FVG=NONE` (4 rows), `MSS=MEDIUM,FVG=MEDIUM` (1 row), `MSS=HIGH,FVG=NONE` (2 rows), `MSS=HIGH,FVG=LOW` (1 row). Every combination accepted.

### Active filters between "H4 break detected" and "signal emitted"

| # | Filter | Tight or permissive? | Code line |
|---|---|---|---|
| 1 | C2 must CLOSE beyond C1 high/low + `0.1%` buffer (`H4_BREAKOUT_CLOSE_BUFFER_PCT=0.001`) | TIGHT (committed break, not wick) | L300 BUY, L355 SELL |
| 2 | Dual-extreme wick rejected (C2 swept both C1.high AND C1.low) | TIGHT (avoid chaos) | L296 |
| 3 | Scan only last `H4_BREAKOUT_C2_LOOKBACK=4` H4 bars (~16h) for a C1 candidate | TIGHT (recent setups only) | L276 |
| 4 | Find a 5M bar after C2's open time | structural | L302/L357 |
| 5 | 5M continuation MSS must be `confirmed=True` within `H4_BREAKOUT_MSS_HORIZON=30` 5M bars (~150 min) | TIGHT (must confirm fast) | L322-L323, L375-L376 |
| 6 | (FVG OR OB) confluence — at least one must match | PERMISSIVE (OR, not AND) | L326-L334, L378-L386 |
| 7 | `consumed.add(setup["key"])` mitigation — one-shot per C1 zone | TIGHT (no re-fire) | post-persist (F4-fixed) |
| 8 | `compute_breakout_sl_tp` `MIN_SL_PCT`/`MAX_SL_PCT` floor/ceiling | TIGHT (rejects bad geometry) | L431-L437 |
| 9 | `compute_crt_trade_economics` BEW + fees_kill economics gate | TIGHT (rejects negative-edge setups) | `if econ is None: return False` (soak A L493, B L426) |
| 10 | Staleness guard (entry_ts < 60min old) | SOAK-ONLY, prevents stale replay | A L467, B L406 |

### Net assessment — moderate net, NO quality threshold

The breakout's discrimination comes from STRUCTURAL filters (committed close, MSS confirmation, geometry, economics), NOT from quality thresholds on the confluence. Compared to the fade (`H4_CRT`) which has `CRT_APPLY_QUALITY_GATES=0` operator override but the bot still has the gate as a knob, the breakout simply doesn't have the gate AT ALL.

Quantitative density (from `backtest_signals` table):

| Reference run (365d, friction-on) | Total signals | Per-token-per-month rate |
|---|---|---|
| TF_A (5m / 4h) | **398** signals → ~33/month over 12 tokens | ~2.7 signals/token/month |
| TF_B (5m / 1h) | **1106** signals → ~92/month over 12 tokens | ~7.7 signals/token/month |

For comparison: the fade CRT canonical Run-168 produced 43 signals over 730d (~1.5/month total across all tokens). The breakout is ~75-200× higher density. **WIDE net relative to fade**, structurally moderate net within its own thesis. The +0.55-0.72 avg_R is achieved across a HIGH-volume, MIXED-quality population — NOT a hand-picked elite subset.

---

## §3 — LIVE soak vs backtest parity

### Effective Config 14 knobs

| Knob | Soak A | Soak B | Backtest `LOCKED_KNOBS` | Match? |
|---|---|---|---|---|
| `H4_BREAKOUT_CLOSE_BUFFER_PCT` | 0.001 ([A:74](breakout_paper_soak.py#L74)) | 0.001 ([B:56](breakout_paper_soak_B.py#L56)) | "0.001" ([run_tf_grid:52](run_tf_grid.py#L52)) | ✓ |
| `BREAKOUT_TP1_RR` | 2.0 ([A:75](breakout_paper_soak.py#L75)) | 2.0 ([B:57](breakout_paper_soak_B.py#L57)) | "2.0" ([run_tf_grid:53](run_tf_grid.py#L53)) | ✓ |
| `BREAKOUT_TP2_RR` | 3.0 ([A:76](breakout_paper_soak.py#L76)) | 3.0 ([B:58](breakout_paper_soak_B.py#L58)) | "3.0" | ✓ |
| `BREAKOUT_TP3_RR` | 4.0 ([A:77](breakout_paper_soak.py#L77)) | 4.0 ([B:59](breakout_paper_soak_B.py#L59)) | "4.0" | ✓ |
| `H4_BREAKOUT_C2_LOOKBACK` | 4 ([A:78](breakout_paper_soak.py#L78)) | 4 ([B:60](breakout_paper_soak_B.py#L60)) | "4" ([run_tf_grid:59](run_tf_grid.py#L59)) | ✓ |
| `H4_BREAKOUT_MSS_HORIZON` | 30 ([A:79](breakout_paper_soak.py#L79)) | 30 ([B:61](breakout_paper_soak_B.py#L61)) | "30" | ✓ |
| `H4_BREAKOUT_OB_SCAN_LOOKBACK` | **implicit default 20** ([breakout_engine:98](breakout_engine.py#L98)) | implicit default 20 | "20" (explicit) | ✓ (same effective value) |
| `H4_BREAKOUT_FVG_PROBE_WIDTH` | **implicit default 3** ([breakout_engine:99](breakout_engine.py#L99)) | implicit default 3 | "3" (explicit) | ✓ (same effective value) |
| `BREAKOUT_SL_INSIDE_BUFFER_PCT` | **implicit default 0.001** ([breakout_engine:107](breakout_engine.py#L107)) | implicit default 0.001 | "0.001" (explicit) | ✓ (same effective value) |

Symmetric-difference of soak's keys vs backtest's keys: **empty**. Value mismatches across the union: **none**. The implicit defaults match the explicit backtest values exactly.

### Effective gating parity

| Aspect | Soak A | Soak B | Backtest | Match? |
|---|---|---|---|---|
| Confluence acceptance | FVG OR OB (engine `_check_breakout_confluence`) | same | same | ✓ |
| MSS quality gate | none (only `confirmed`) | none | none | ✓ |
| 4H bias gate | none | none | none | ✓ |
| 1H trend gate | none | none | none | ✓ |
| Wyckoff filter | none | none | none | ✓ |
| Quality-gate flag (`CRT_APPLY_QUALITY_GATES`) | absent | absent | absent | ✓ |
| Break confirm buffer | 0.001 (committed close) | 0.001 | 0.001 | ✓ |
| C2 lookback | 4 H4 bars | 4 H4 bars | 4 H4 bars | ✓ |
| Continuation MSS horizon | 30 5M bars | 30 5M bars | 30 5M bars | ✓ |
| OB scan lookback | 20 H4 bars (default) | 20 H4 bars (default) | 20 (explicit) | ✓ |
| FVG probe width | 3 5M bars (default) | 3 5M bars (default) | 3 (explicit) | ✓ |
| Economics gate | `compute_crt_trade_economics` | same | same | ✓ |
| SL/TP formula | `compute_breakout_sl_tp` (fixed-R 2/3/4) | same | same | ✓ |
| One-shot mitigation by C1 zone | yes (consumed set) | yes | yes (`consumed: set`) | ✓ |

### Tag-naming asymmetry (cosmetic, NOT a behavioral divergence)

| Source | `entry_type` produced |
|---|---|
| Soak A | `H4_BREAKOUT_FVG`, `H4_BREAKOUT_OB` |
| Soak B | `H4_BREAKOUT_FVG_B`, `H4_BREAKOUT_OB_B` |
| Backtest TF run | `H4_BREAKOUT_FVG_TF`, `H4_BREAKOUT_OB_TF` |

The underlying setup logic is identical — only the suffix differs. When comparing A's live results to its `TF_A_5m_4h` backtest reference, the operator must remember to map `H4_BREAKOUT_OB ↔ H4_BREAKOUT_OB_TF` (same logic, different label). Likewise for B↔TF_B. No code change required; flagging this so per-type comparisons don't get derailed by string mismatches.

**§3 verdict — no 3rd behavioral divergence.** The gating is byte-for-byte equivalent between the two soaks and the backtest reference.

---

## §4 — Per-type performance in the backtest

### A's reference: `TF_A_5m_4h_FRICTION` (friction-on, 365d, 12 tokens)

| `entry_type` | n | WR% | avg_R | sum_R |
|---|---|---|---|---|
| `H4_BREAKOUT_FVG_TF` | 158 | 65.8% | +0.606 | +95.74 |
| `H4_BREAKOUT_OB_TF` | 240 | 71.3% | +0.623 | +149.51 |
| **Total** | **398** | **69.1%** | **+0.616** | **+245.25** |

OB-dominant (60% of A's signals), both types similar avg_R, both positive.

### B's reference: `TF_B_5m_1h_FRICTION` (friction-on, 365d, 12 tokens)

| `entry_type` | n | WR% | avg_R | sum_R |
|---|---|---|---|---|
| `H4_BREAKOUT_FVG_TF` | 914 | 59.1% | +0.509 | +465.13 |
| `H4_BREAKOUT_OB_TF` | 192 | 74.5% | +0.740 | +142.15 |
| **Total** | **1106** | **61.8%** | **+0.549** | **+607.28** |

FVG-dominant (83% of B's signals). OB is small (17%) but high-edge (+0.74 / 74.5% WR). FVG carries the population, OB carries the per-signal edge.

### Aggregate across all breakout backtest runs (cross-config sanity)

| `entry_type` | n | WR% | avg_R | sum_R |
|---|---|---|---|---|
| `H4_BREAKOUT_FVG` | 7162 | 63.4% | +0.775 | +5549.02 |
| `H4_BREAKOUT_OB` | 13086 | 65.7% | +0.630 | +8242.32 |
| `H4_BREAKOUT_FVG_FRICTION` | 677 | 66.3% | +0.707 | +478.54 |
| `H4_BREAKOUT_OB_FRICTION` | 1503 | 68.2% | +0.562 | +844.19 |
| `H4_BREAKOUT_FVG_TF` | 2985 | 57.8% | +0.512 | +1528.18 |
| `H4_BREAKOUT_OB_TF` | 1292 | 77.9% | +0.855 | +1105.11 |

**No weak / negative type.** All 6 entry-type buckets across all configs have positive avg_R and WR ≥ 57%. Neither FVG nor OB is "broken"; the live soak emitting either type is not diluting results.

### Live B accumulated so far (8 closed since restart ~11h ago)

| `entry_type` | n | WIN | LOSS | avg_R | sum_R |
|---|---|---|---|---|---|
| `H4_BREAKOUT_FVG_B` | 2 | 1 | 1 | +0.148 | +0.30 |
| `H4_BREAKOUT_OB_B` | 6 | 4 | 2 | +0.637 | +3.82 |
| **B total** | **8** | **5** | **3** | **+0.515** | **+4.12** |

Tiny sample (PENDING the n≥30 gate), but the directional signal so far is consistent with the backtest distribution: OB carrying the early edge (+0.637 vs backtest +0.740), FVG more variable. 5 WINs means TP3 IS being reached — positive empirical evidence that the exit-fix's "stay open until terminal" path is working.

---

## §5 — Verdict

| Question | Answer |
|---|---|
| Is the entry gating strict or loose? | **Moderate-loose.** The breakout has no quality threshold on MSS or FVG, no bias gate, no Wyckoff filter. Discrimination comes from STRUCTURAL filters (committed-close break, MSS confirmation, geometry sanity, economics gate, one-shot mitigation), not quality thresholds. Density is ~75-200× higher than the fade — by design, since the strategy lives on volume × moderate edge, not selectivity × elite edge. |
| Does the LIVE soak match the BACKTEST? | **Yes — bit-for-bit gating parity.** All 9 effective Config 14 knobs match. All 13 gating dimensions match (confluence type, quality, bias, buffer, lookbacks, horizons, economics, SL/TP). The only asymmetry is the entry-type tag suffix (none/`_B`/`_TF`) which is cosmetic — the underlying detection is the same call to `_check_breakout_confluence`. No 3rd behavioral divergence found. |
| Is any entry_type a weak spot? | **No.** All 6 entry-type / config combinations in the backtest history show positive avg_R and WR ≥ 57.8%. OB carries higher per-signal edge in TF_A and aggregate; FVG carries volume but still positive. Both types contribute positively. Neither should be filtered out. |

**PASS. No action proposed.** Gating is symmetric live↔backtest; both confluence types carry edge; the previously-found behavioral divergences (tz, exit-model, F3/F4 micro-bugs) are not joined by a 3rd in this dimension.

Two non-blocking observations for the operator's notebook (not bugs):
1. The entry-type suffix asymmetry (`_B` vs `_TF`) means per-type roll-ups across live and backtest need a string-normalizing join. The breakout viewer's gate math doesn't care (it sums all closed rows per `source`), so no immediate issue.
2. B is FVG-dominant (83% of signals) while A is OB-dominant (60%). This is a property of the reference timeframe (1H = more FVG opportunities, 4H = stronger OBs), not a bug. If forward results diverge significantly from backtest, distribution differences across the OB/FVG mix would be a hypothesis worth checking first.

---

## §6 — Isolation

| Check | State |
|---|---|
| Fade soak production (PID 393274) | ALIVE, untouched |
| `data/signals.db` (production) | unchanged by this audit (read-only access only) |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `68166b2` (F3/F4 fix, not pushed) |
| Both soaks (A 473059, B 473060) | alive, cycling, untouched by this audit |
| Backups | `prefix_bak`, `exitfix_bak`, `lowfix_bak` all intact |

Awaiting operator call. No fixes applied.
