# Phase C-Breakout — Full Behavioral Audit V2 (Post BE-after-TP1 Exit Model)

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~06:55 UTC.
**Audited processes:** A PID 486821 (cycle 32, 0 open, 0 closed), B PID 486822 (cycle 32, 7 open, 1 closed).
**Reference commit:** `ae46c1d` — `fix(exit): BE-after-TP1 runner model — match live Bybit execution`.
**Premise:** the prior full audit (`PHASE_C_FULL_AUDIT.md`) verified the "ignore-SL-after-TP1" model. That model has since been rewritten to true BE-after-TP1 with friction. This audit re-verifies the WHOLE system under the new model with the same data-path/behavioral focus that caught the tz + exit-model bugs.

---

## §1 — BE-after-TP1 model is LIVE and correct

### 1.1 Process vs committed source

| Process | Start (UTC) | File mtime (UTC) | HEAD commit (UTC) | `git diff HEAD` | Verdict |
|---|---|---|---|---|---|
| A 486821 | 2026-06-03 05:51:57 | breakout_paper_soak.py @ 05:42:15 | `ae46c1d` @ 05:54:49 | 0 lines | **PASS — running the committed code** |
| B 486822 | 2026-06-03 05:51:57 | breakout_paper_soak_B.py @ 05:42:56 | same | 0 lines | **PASS — same** |

### 1.2 New exit model markers live in source

| Marker | A line | B line | run_tf_grid line |
|---|---|---|---|
| `RUNNER-EXIT FIX (2026-06-03)` comment | 332, 417 | 290, 352 | 126, 176 |
| `be_stopped` variable declared | 339 | 293 | 136 |
| BE-stop check `l_p <= entry` (BUY) | 354 | 304 | 147 |
| BE-stop check `h_p >= entry` (SELL) | 364 | 313 | 158 |
| `elif be_stopped:` classification branch | 383 | 322 | 166 |
| New PARTIAL_TP1 R formula | 419 | 353 | 183 |

**Formula byte-identical across all three files:**
```python
realized_r = round((0.5 * net_tp1 + 0.5 * (-rt_cost_pct)) / risk, 4)
```

### 1.3 Unit tests against current code

**13/13 EXIT-MODEL PASS:** SL pre-TP1 LOSS, TP1→BE PARTIAL_TP1, TP1→TP2→expiry PARTIAL_TP2, TP1→TP2→TP3 WIN, TP1 no-rebreach expiry PARTIAL_TP1, TP1 dip-near-BE then TP3 WIN, Nothing→EXPIRED, intrabar TP1+BE deferral, BE+TP2 same-bar conservative BE-first, SELL mirrors (j-m).

**4/4 TZ-FIX PASS:** signal_ts is UTC not local, expiry = entry+48h, start_ms = entry+5min UTC, start_ms ≠ entry-2h shifted.

**§1 result — PASS.**

---

## §2 — End-to-end data path trace under new model

### 2.1 TON #37 (the one closed signal)

```
EMIT:
  Token=TON, dir=BUY, entry=2.029, sl=2.018855, tp1=2.04929, tp2=2.059435, tp3=2.06958
  timestamp=2026-06-03 05:15:00 UTC, expires_at=2026-06-05 05:15:00 UTC (entry + 48h)
  source=H4_BREAKOUT_PAPER_SOAK_B, entry_type=H4_BREAKOUT_OB_B

DB stored verbatim ✓

RESOLVE (under new model):
  Forward bars fetched from start_ms = entry_ts + 5min UTC (tz-fix applied)
  Walk: SL hit at 05:34:59 UTC (bar 4, ~20min after entry, pre-TP1)
  → outcome=LOSS, sl_hit=1, tp1_hit=0, tp2_hit=0, tp3_hit=0

R COMPUTATION (LOSS branch, unchanged from old model):
  rt = 0.4% (TON friction)
  gross_sl = (2.029 − 2.018855)/2.029 = -0.50%
  net_sl = round(-0.50 − 0.40, 2) = -0.90
  risk = 0.90
  R = net_sl / risk = -0.90/0.90 = -1.0000  ✓ (matches stored -1.0)

WRITE: INSERT into results + UPDATE signals SET status='CLOSED' (atomic, single commit)
  Stored: result='LOSS', realized_r=-1.0, closed_at='2026-06-03 05:34:59'

VIEWER: reads status='CLOSED' + result='LOSS' → renders in red outcome cell
  R-cell formatter shows -1.000 (negative-tinted)
  Tier pills: TP1/TP2/TP3 all NOT hit, no green tint applied to TP cells ✓
```

**Every transition value preserved end-to-end.**

### 2.2 The 7 open positions (live walk under new model)

Fetched fresh klines, applied the new exit logic from `run_tf_grid.check_outcome`:

| # | Token | Curr drift | State under new model |
|---|---|---|---|
| 32 | XRP | +0.92% | no tier yet (open, no SL touch) |
| 33 | HBAR | +0.53% | no tier yet |
| 34 | AVAX | +0.02% | no tier yet |
| 35 | LINK | +0.54% | no tier yet |
| 36 | BNB | −0.06% | no tier yet |
| 38 | ATOM | +0.32% | no tier yet |
| 39 | BCH | −0.20% | no tier yet |

All 7 correctly evaluated as "still open" (consistent with B's heartbeat `open=7`).

**§2 result — PASS.** Closed-signal trace + open-position walk both match the new model's logic exactly.

---

## §3 — Soak vs backtest parity under new model

### 3.1 BUY walk side-by-side

| Aspect | Soak A | Soak B | run_tf_grid |
|---|---|---|---|
| Pre-TP1 SL trigger `not tp1_hit and not sl_hit and l ≤ sl` | L346 | L297 | L141 |
| TP1 hit `not tp1_hit and h ≥ tp1` then `continue` | L349 | L300 | L144 |
| BE-stop `tp1_hit and not tp2_hit and not be_stopped and l ≤ entry` | L354 | L304 | L147 |
| TP2 progression `tp1_hit and not tp2_hit and h ≥ tp2` | (later) | L306 | L150 |
| TP3 trigger `tp2_hit and not tp3_hit and h ≥ tp3` then `break` | (later) | L307 | L152 |

Code identical across all 3 (modulo formatting / comments). SELL mirrors identically.

### 3.2 Parity table (BE-after-TP1 model)

| Dimension | Soak A | Soak B | run_tf_grid | Verdict |
|---|---|---|---|---|
| BE-stop trigger price (=entry) | `l_p <= entry` | `l_p <= entry` | `l <= entry` | MATCH |
| Intrabar BE-first vs TP2 | BE check before TP2 check | same | same | MATCH (conservative) |
| TP1-fills-first deferral | `tp1_hit=True; continue` | same | same | MATCH |
| Friction application | `net_tp1 = round(g_tp1 - rt, 3)` | same | same | MATCH |
| PARTIAL_TP1 R formula | `(0.5*net_tp1 + 0.5*(-rt))/risk` | same | same | MATCH |
| Forward window | 576 bars (48h) | 576 bars | 576 bars (`FORWARD_MINUTES=2880`) | MATCH |
| Bar walk start | `entry + 5min UTC` | same | `entry_bar + 1` (equivalent) | MATCH |
| Outcome label classification | LOSS / WIN / PARTIAL_TP1 (BE OR expiry above BE) / PARTIAL_TP2 / EXPIRED | same | same | MATCH |

**§3 result — PASS.** No 3rd-class divergence found.

---

## §4 — Accumulated-state / runtime risks

### 4.1 Stuck-OPEN

Query: signals with status='OPEN' AND now > expires_at → **0 rows**.
All 7 current open positions have expires_at = 2026-06-05 05:15:00 UTC (entry + 48h via tz-fix path). Not stuck.

### 4.2 Double-resolve / orphan rows

| Check | Result |
|---|---|
| Duplicate results rows (signal_id has multiple results) | **0** |
| Orphan CLOSED (signals.status='CLOSED' but no results row) | **0** |
| INSERT into results + UPDATE signals atomic? | ✓ single `conn.commit()` covers both |

### 4.3 Consumed-zone re-emission

Query: `signals` rows grouped by c1_zone_key, HAVING COUNT > 1 → **0 rows**. Each (c1_time, c1_high, c1_low) tuple fired exactly once. **F4-fix (post-persist consumed mark) verifiably preventing duplicates.**

For the 7 open BUYs: all have the same c1_time (2026-06-03 00:00 UTC = the same parent 4h bar across tokens), but each token's `(c1_high, c1_low)` pair is unique → 7 distinct zone keys. No duplication.

### 4.4 New BE-stop terminal — can a position get stuck?

The new model adds one new terminal path (`be_stopped`). Failure-mode review:

| Failure mode | Can stick? | Why |
|---|---|---|
| BE never triggers, TP3 never hits, expiry never fires | No — expires_at is hard timestamp + cycle check `now_utc >= expiry_dt` → forced terminal at expiry | ✓ |
| BE-stop fires falsely on a wick that didn't reach entry | No — `l <= entry` requires the bar's actual low to touch entry | ✓ |
| TP2 reached after BE rebreach but before TP3 — paper said WIN, new says PARTIAL_TP1 | Correct — once `be_stopped=True`, loop `break`s and TP2/TP3 never re-evaluated | ✓ (this IS the design fix) |
| Process crash mid-walk | next cycle re-walks from `start_ms`; flags rebuild from scratch — restart-safe | ✓ |

**§4 result — PASS.**

---

## §5 — Outcome re-distribution sanity (CRITICAL spot-check)

The new model reclassifies 1353 of 7291 OLD WIN outcomes in TF_B 720d FRICTION as NEW PARTIAL_TP1 (18.5% reclassification). The operator asked: is the BE-stop firing correctly, or too aggressively?

**5 random samples walked end-to-end:**

| Token | Dir | Signal ts | TP1 hit @ bar | BE hit @ bar | TP3 hit @ bar | BE before TP3? |
|---|---|---|---|---|---|---|
| BTC | SELL | 2024-06-13 15:20 | 1055 | 1069 (+14 bars = ~70 min) | 1345 | ✓ BE 24h before TP3 |
| BTC | BUY | 2024-07-14 04:15 | 9853 | 9946 (+93 bars = ~7.75h) | 10048 | ✓ BE 8.5h before TP3 |
| BTC | BUY | 2024-07-15 22:15 | 10417 | 10432 (+15 bars = ~75min) | 10670 | ✓ BE 19.8h before TP3 |
| BTC | BUY | 2024-07-16 15:15 | 10559 | 10573 (+14 bars = ~70min) | 10669 | ✓ BE 8h before TP3 |
| BTC | SELL | 2024-07-27 23:15 | 13825 | 13845 (+20 bars = ~100min) | 14310 | ✓ BE 38.7h before TP3 |

**All 5 spot-checks confirm:** TP1 was hit, BE was subsequently and genuinely touched, then TP3 was eventually reached — but the BE-stop correctly terminated the runner BEFORE the TP3 could fire.

The old model labeled these WIN (because TP3 was eventually touched, ignoring the SL-after-TP1 retest). The new model correctly labels them PARTIAL_TP1 (BE-stopped before TP3). The reclassification is CORRECT — these were never genuine WINs in live execution.

**§5 result — PASS.** The 1353 reclassifications are sound.

---

## §6 — Concurrency / DB integrity

| Check | Result |
|---|---|
| WAL mode active | ✓ `PRAGMA journal_mode → wal` |
| `synchronous` level | 2 (FULL) |
| WAL file present | breakout.db-wal (197 KB, active writes) |
| Backup files intact | 7 backups (`prefix`, `exitfix`, `lowfix`, `before_365d`, `before_720d`, `before_regime`, `runnerfix` @ 24 MB) |
| Backtest sources cleanly tagged | OLD (`_720D`, `_365D`, no suffix) + NEW (`_NEW720`, `_NEW365`, `_NEW90`) coexist; verified 32 distinct source tags, no collision |

WAL allows concurrent A+B writers + viewer reader with snapshot isolation. No torn-read concern.

**§6 result — PASS.**

---

## §7 — Gate + viewer correctness

### 7.1 Gate constants intact

```python
GATE_N_TARGET           = 30      ✓ (line 67)
GATE_AVG_R_MIN          = 0.40    ✓ (line 68)
GATE_PF_MIN             = 2.0     ✓ (line 69)
GATE_WR_MIN             = 0.55    ✓ (line 70)
GATE_MAX_DD_R           = 20.0    ✓
verdict_overall = "PENDING" / "PASS" / "FAIL" branches ✓
```

PENDING-until-n≥30 lock intact at `breakout_viewer.py:467`.

### 7.2 ⚠ MEDIUM FINDING: Viewer reference values STALE under new model

The viewer hard-codes the friction-on backtest reference avg_R values that the operator uses to gauge live progress against the backtest. Under the OLD model these were +0.616 (TF_A) and +0.549 (TF_B). Under the NEW BE-after-TP1 model they should be **+0.4536 (TF_A) and +0.4840 (TF_B)**.

| File:Line | Stale (OLD) value | Should be (NEW) | Severity |
|---|---|---|---|
| `breakout_viewer.py:22` | comment `A: +0.616 avg_R` | +0.4536 | MEDIUM (display only — misleading) |
| `breakout_viewer.py:23` | comment `B: +0.549 avg_R` | +0.4840 | MEDIUM |
| `breakout_viewer.py:93` | `"ref_avg_R": 0.616` | 0.4536 | **MEDIUM (used in JSON payload + rendered in dashboard)** |
| `breakout_viewer.py:102` | `"ref_avg_R": 0.549` | 0.4840 | **MEDIUM (same)** |

These values are rendered to the operator at:
- L835: `Friction-on ref = +0.616` (legend in soak header)
- L856: `Friction-on ref = +0.616` (header card)

**Operator-facing impact:** if the soak's avg_R lands at e.g. +0.50, the dashboard would show "below the +0.616 ref" — but +0.50 is actually ABOVE the new model's reference (+0.4536). The operator would incorrectly interpret in-line forward results as underperforming. **Does NOT affect the gate verdict** (the +0.40 floor is unchanged at L68). Display-only misleading.

### 7.3 ⚠ MEDIUM FINDING: GATE_WR_MIN = 0.55 may not be compatible with new model

Under the new model the backtest WR is:
- TF_A 720d FRICTION NEW: 56.9% → above 55% gate ✓
- **TF_B 720d FRICTION NEW: 53.2% → BELOW 55% gate** ✗

If the soak's forward WR approximately matches the backtest, **TF_B may PASS avg_R≥0.40 (live ref +0.4840 ✓) and PASS PF≥2.0 (live ref 2.77 ✓) and PASS maxDD≤20R (11.3R ✓) but FAIL WR≥0.55**.

This isn't a bug — it's a gate calibration question. The WR drop is the direct consequence of the new model correctly relabeling ~18% of OLD WINs as PARTIAL_TP1_BE (still profitable +0.25 R, just not "wins"). The operator may want to lower GATE_WR_MIN to e.g. 0.50 to match the new model's realistic WR distribution, or accept that TF_B's verdict will be PENDING longer / FAIL on WR.

**Suggested follow-up (NOT a fix here):** decide whether to:
- (a) Lower GATE_WR_MIN to 0.50 to match new model
- (b) Keep at 0.55 — accept that TF_B may fail WR (and is therefore lower-confidence)
- (c) Re-define WR to include PARTIAL_TP1_BE as "positive close" (currently `WIN ∪ PARTIAL_TP2` only)

### 7.4 Other viewer integrity

| Check | State |
|---|---|
| Source-isolation filters intact (closed/open/tracking SELECTs filter by `source = ?`) | ✓ L345, L356, L403 |
| Read-only connection only | ✓ L111 `mode=ro`, no INSERT/UPDATE/commit anywhere |
| TP-tier cell coloring intact | ✓ L581-583 (tp1-hit, tp2-hit, tp3-hit CSS) |
| All-closed scroll pagination intact | ✓ L588-592 (closed-scroll container) |
| Open-position UTC mapping columns intact | ✓ L703 (opened (UTC), expires (UTC)), L714 (tv-symbol BINANCE:TOKENUSDT) |
| Backtest rows excluded from gate calc | ✓ filter `source = ?` always uses soak label |
| `tp2_hit=1 AND result=LOSS` sanity flag intact | ✓ L243-247 in `_enrich_geometry` |

**§7 result — PASS with 2 MEDIUM findings** (stale references + WR-gate calibration).

---

## §8 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE 3d 18h 21m, untouched throughout this audit |
| `data/signals.db` (production) | unchanged (mtime reflects fade-soak's own writes; audit was read-only) |
| `data/baseline_pin.json` Run-3704 | unchanged (config_hash `3ee13531421d7ba5...`) |
| Main branch HEAD | `228e04f feat(cycle-15-loop)...` (unchanged) |
| Breakout branch HEAD | `ae46c1d fix(exit): BE-after-TP1 runner model` (uncommitted viewer + .gitignore + 13 doc files in working tree, **not pushed**) |
| Both soaks (A 486821, B 486822) | ALIVE 1h 02m, cycle 32, untouched (B has 7 open + 1 closed, A has 0+0) |
| 7 backups | intact (prefix, exitfix, lowfix, before_365d, before_720d, before_regime, runnerfix @ 24 MB) |
| 32 backtest source tags | coexist with no collision |

**§8 result — PASS.**

---

## Findings summary (sorted by severity)

| # | Severity | Section | Finding | Where |
|---|---|---|---|---|
| F1 | **MEDIUM** | §7.2 | Viewer hard-codes OLD model's friction-references (+0.616/+0.549) — should display NEW model's references (+0.4536/+0.4840). Misleading; does NOT affect gate verdict. | `breakout_viewer.py:22,23,93,102` |
| F2 | **MEDIUM** | §7.3 | `GATE_WR_MIN=0.55` may not be calibrated for the new model — TF_B 720d NEW backtest WR=53.2% sits below the gate, so soak's forward WR may fail this criterion even though avg_R/PF/maxDD all clear. Operator decision needed: lower the WR gate, accept the harder bar, or redefine WR to count PARTIAL_TP1_BE. | `breakout_viewer.py:70` |

**No CRITICAL findings. No 3rd-class behavioral divergence found.** The exit-model rewrite (commit `ae46c1d`) is bit-for-bit consistent across soak A, soak B, and `run_tf_grid.py`, and the 5 random reclassifications from OLD WIN → NEW PARTIAL_TP1 all verified as correct (BE genuinely touched before TP3 in the bar data).

---

## Verdict

**The system is trustworthy to accumulate forward toward n≥30 under the new BE-after-TP1 model. The forward numbers WILL be portable to live Bybit IF AND ONLY IF the operator implements "move SL to entry once TP1 fills" on the live execution side** (which is what `RUNNER_EXIT_GAP.md` recommended and what the new paper model now matches).

**No 3rd-class divergence. The exit-model rewrite is correct end-to-end.**

The two MEDIUM findings (F1/F2) are operator-facing but do not invalidate the soak's forward edge. They affect dashboard display and gate calibration, not the underlying simulation. They can be addressed before n=30 lands (the soak has plenty of accumulation time — current pace ~1 closed per ~5h on B alone, projecting n=30 in roughly 6 days).

**Recommendation:** address F1 (update viewer references to +0.4536/+0.4840) before the operator starts watching the dashboard for daily progress, because the stale references could mislead live-progress interpretation. F2 is a strategic decision (whether to lower the WR gate) that the operator should make consciously, ideally before n=30 lands.

Awaiting operator call. No fixes applied.
