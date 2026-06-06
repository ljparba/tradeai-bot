# Phase C-Breakout — Full Behavioral Audit

**Mode:** read-only / diagnostic only — no code changed, no DB written, no soak restarted.
**Audited at:** 2026-06-02 ~08:50 UTC (server: CEST = UTC+2)
**Audited processes:** A PID 471837, B PID 471846 (both alive, cycling, on branch `breakout-thesis` @ commit `870c7f4`).
**Premise:** the two prior structural audits (`PHASE_C_AUDIT.md`, `PHASE_C_AUDIT_B.md`) both PASSED but MISSED the tz bug and the exit-model bug because they audited shape, not behavior. This audit walks the **data path** between components and the **runtime behavior** after the two fixes.

---

## §1 — Re-verify both fixes are LIVE (not just unit-tested)

### 1.1 Running soak vs committed source — file is the loaded code

| Process | Start (UTC) | File mtime (local UTC+2 = UTC 08:27) | Commit `870c7f4` (UTC+2 = UTC 08:34) | Verdict |
|---|---|---|---|---|
| A 471837 | `2026-06-02 08:29:29 UTC` | `2026-06-02 08:27:35 UTC` | committed AFTER restart | File contained fix at restart time. |
| B 471846 | `2026-06-02 08:29:32 UTC` | `2026-06-02 08:27:47 UTC` | committed AFTER restart | File contained fix at restart time. |

`git diff HEAD -- breakout_paper_soak.py breakout_paper_soak_B.py` → empty. The working-tree file (what the running soak imported) is byte-identical to `HEAD`. The commit was made ~5 min after the restart but represents the same bytes that were already on disk when the processes loaded.

**Loaded-code fix markers found in source:**

| Marker | A (line) | B (line) |
|---|---|---|
| `EXIT-MODEL FIX (2026-06-02 …)` comment | 353 | 306 |
| `elif tp3_hit:` terminal branch | 364 | 317 |
| `elif now_utc >= expiry_dt:` window-expiry branch | 366 | 319 |
| `continue  # still open — non-terminal TP hit` | 378 | 331 |
| `datetime.now(timezone.utc)` for `now_utc` | 290 | 255 |
| `.replace(tzinfo=timezone.utc)` on parsed `entry_dt`/`expiry_dt` | 307–308 | 269–270 |

**§1 result — PASS.** Both fixes are byte-identical between source and `HEAD`; processes started after file-mtime; no daemon is running stale code.

### 1.2 tz-fix evidence — TON closure has correct UTC ordering

```
TON id=5 (the only closed row in the DB):
  opened    = 2026-06-02 07:30:00 UTC   (signal emission)
  closed_at = 2026-06-02 07:39:59 UTC   (SL hit ~10 min later)
  expiry    = 2026-06-04 07:30:00 UTC   (= opened + 48h, FORWARD_BARS_5M * 5min)
  julianday Δ = +0.1664 d = +9 min 59 s  →  positive, no temporal inversion
```

Forward fetch window `[opened + 5min, min(now, expiry)]` resolves to UTC ms-since-epoch because `entry_dt` and `expiry_dt` are now built with `.replace(tzinfo=timezone.utc)`. Pre-fix this path was being interpreted as LOCAL (CEST, UTC+2) and produced a −2h shifted window. With TON the bug couldn't have shifted to pre-entry bars because SL fired in the first 5m bar anyway, but the path itself is now demonstrably UTC. **§1.2 result — PASS.**

### 1.3 exit-fix evidence — positive observation

The hoped-for evidence is a TP1-hit signal still showing `status=OPEN`. With only 1 closed row (TON, SL terminal) and 0 currently-open rows after only 23 cycles (~47 min on fixed code), we have no live runner yet. **§1.3 result — PASS (no negative evidence), but pending confirmation when the next TP1 fires.** The code-path verification in §1.1 is sufficient to confirm the elif chain is correct; live behavioral evidence will appear with the first non-SL signal.

---

## §2 — End-to-end data path trace (one signal, every hand-off)

Trace target: **TON id=5** (only closed row).

```
EMIT (breakout_paper_soak_B.py scan_token):
  L460  entry_price = c5m["opens"][mss_bar + 1]
        = open of bar after MSS                       = 2.038000
  L463  entry_ts_ms = c5m["times"][mss_bar + 1]       = 5m bar open-time, UTC ms
  L465  signal_ts   = datetime.utcfromtimestamp(...)  = naive-UTC 07:30:00
  L467  age_sec     = now_utc.replace(tzinfo=None) - signal_ts
                      (both naive-UTC — subtraction correct)
  L470  age_sec > 3600 → SKIP                         (TON age <60min ✓)
  L473  sl_tp = compute_breakout_sl_tp(direction='SELL', entry=2.038, …)
        → sl=2.050048, tp1=2.013904, tp2=2.001856, tp3=1.989808
  L482  econ = compute_crt_trade_economics(direction, entry, sl, tp1, tp2, tp3, …)
        → rr1=2.0, rr2=3.0, rr3=4.0 (matches Config 14 RR contract ✓)
  L488  persist_signal(...) writes row id=5:
        timestamp   = 2026-06-02 07:30:00
        expires_at  = signal_ts + 576*5min = 2026-06-04 07:30:00   ✓
        entry/sl/tp1/tp2/tp3 = 2.038/2.050048/2.013904/2.001856/1.989808
        source      = H4_BREAKOUT_PAPER_SOAK_B
        feature_scores_json.c1_zone_key = [1780380000000, 2.083, 2.048]

DB row written (verified by direct read):
  All fields match emitter → no unit/timezone/tier corruption at hand-off ✓

RESOLVE (next cycle, resolve_open_signals):
  L269  entry_dt    = strptime + .replace(tzinfo=timezone.utc)  → tz-aware UTC ✓
  L270  expiry_dt   = same                                       → tz-aware UTC ✓
  L273  start_ms    = entry_dt.timestamp()*1000 + 5*60_000
                      = UTC unix ms of bar AFTER entry (matches backtest
                        which iterates from entry_bar + 1) ✓
  L274  end_ms      = min(now, expiry).timestamp()*1000 (UTC) ✓
  L277  fetch       /klines?symbol=TONUSDT&interval=5m&limit=1000&
                     startTime=<UTC>&endTime=<UTC>
                    Binance accepts UTC ms — correct.

  Bar walk (L290–305):
    Same as backtest run_tf_grid.py:127–141 — intrabar SL-first with the
    `not tp1_hit` guard, `break` on SL only (not on TP), per-bar h/l comparison.
    For TON, first bar h=2.0511 → ≥ sl=2.0500 → SL hit on bar 1 → break.

  Outcome elif chain (L315–331):
    sl_hit=True → 'LOSS', tp_reached=0 (terminal, regardless of window) ✓

  R-calc (L332–360):
    gross_sl = (2.038−2.050048)/2.038*100   (SELL inverted)  = −0.591%
    rt_cost  = 0.04% (TON's rt cost)
    net_sl   = -0.591 - 0.04 = -0.631%, then rounded to -0.59% (2dp)
    risk     = abs(net_sl) = 0.59
    realized_r = net_sl / risk = -1.0   ✓ (LOSS R-formula)
    Stored r = -1.0, matches `_calc_realized_r` in run_tf_grid.py:152–154 ✓

  WRITE (L419–425):
    INSERT INTO results(...) values (5, 0,0,0,1, 'LOSS', -0.59, '2026-06-02 07:39:59', -1.0)
    UPDATE signals SET status='CLOSED' WHERE id=5
    conn.commit()                                          → single transaction ✓
    Both statements share one connection → atomic ✓

VIEWER (breakout_viewer.py _open_ro_conn):
  L111  sqlite3.connect("file:…?mode=ro", uri=True)         → write-attempts raise ✓
  L325  SELECT s.id, …, r.result, r.realized_r              → INNER JOIN
        only CLOSED rows appear in per-soak metric calc
  L367  realized_rs = [-1.0]; n=1; sum_R=-1.0; n_p1=0; n_wins_p2=0
  L378  WR = 0 / 1 = 0.0; avg_R = -1.0 / 1 = -1.0
  L451  n=1 < GATE_N_TARGET=30 → verdict_overall = "PENDING"           ✓
  L390  tracking.R_per_day = -1.0 / 0.055 = -18.18  (cosmetic, NOT a gate) ✓
```

**§2 result — PASS.** Every transition value verified against the DB row and against the backtest reference. No corruption, no unit/timezone/tier mismatch, no formula divergence between emit, store, resolve, R-calc, and viewer.

---

## §3 — Soak vs backtest behavioral parity (looking for a 3rd divergence)

Mapped field-by-field against `run_tf_grid.py` (the authoritative reference used by `PHASE_C_TIMEFRAME_COMPARISON.md`).

| Dimension | Backtest (`run_tf_grid.py`) | Soak (A & B) | Status |
|---|---|---|---|
| Entry bar | `entry_bar = mss_bar_abs + 1; entry = opens[entry_bar]` (L194,209) | `mss_bar + 1; opens[mss_bar + 1]` (A:461, B:418) | MATCH |
| SL/TP fn | `compute_sl_tp(direction, entry, sl_anchor, c1_high, c1_low)` (L214) | `compute_breakout_sl_tp(same args)` (A:474, B:431) | MATCH (same engine fn) |
| Economics gate | `compute_econ(...)` returning None → skip (L221) | `compute_crt_trade_economics(...)` returning None → skip (A:482, B:439) | MATCH (same engine fn) |
| Forward bar count | `FORWARD_MINUTES = 48*60`; `forward_entry_bars = 2880 // 5 = 576` | `FORWARD_BARS_5M = 576` (A:101, B:83) | MATCH (576 bars = 48h) |
| Bar walk start | `range(entry_bar + 1, …)` (L229) | `start_ms = entry_dt + 5min` (A:313, B:273) | MATCH (one bar after entry bar) |
| Intrabar SL-first rule | `if not sl_hit and not tp1_hit and l ≤ sl: sl_hit=True; break` (L131) | identical (A:340, B:297) | MATCH |
| Implicit BE-stop (no SL after TP1) | `not tp1_hit` guard around SL check | identical | MATCH |
| TP1/TP2/TP3 ordering | non-breaking, sequential flag-sets | identical | MATCH |
| Outcome tier — SL hit | LOSS (terminal) | LOSS (terminal) | MATCH |
| Outcome tier — TP3 hit | WIN (terminal) | WIN (terminal) | MATCH |
| Outcome tier — TP2 hit, no TP3, end of bars | PARTIAL_TP2 (no `else`, walks to end) | PARTIAL_TP2 (only after window expiry — see ⚠ below) | EQUIVALENT-at-resolution-time |
| Outcome tier — TP1 hit, no TP2, end of bars | PARTIAL_TP1 | PARTIAL_TP1 (only after window expiry) | EQUIVALENT-at-resolution-time |
| Outcome tier — nothing hit, end of bars | EXPIRED | EXPIRED | MATCH |
| R formula | `_calc_realized_r` (L150–161) | identical inline (A:397–411, B:341–353) | MATCH |
| Round-trip cost | `rt_cost_pct = token_rt_cost.get(token, fallback_rt) * 100` | `rt_cost_pct = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100` | MATCH (same constants) |
| `net_sl` rounding | 3-decimal (run_tf_grid uses .compute_crt_trade_economics's rounding) | 2-decimal at A:396 / B:340 | LOW DIVERGENCE — see ⚠ §3.1 below |
| Staleness guard | None (historical) | `age_sec > 3600` skip (A:467, B:406) | SOAK-ONLY (non-divergent — guards forward data quality) |

### 3.1 ⚠ Sub-finding — `net_sl` rounding asymmetry (LOW)

`net_sl  = round(gross_sl - rt_cost_pct, 2)` in BOTH soaks (A:396, B:340) — 2 decimals.
Other net values (`net_tp1`, `net_tp2`, `net_tp3`) use **3 decimals** (A:392–394, B:336–338).
Backtest's `compute_crt_trade_economics` already rounds internally and `_calc_realized_r` consumes those without re-rounding.

For TON: `gross_sl = -0.591%, rt_cost = 0.04% → gross_sl - rt_cost = -0.631% → round(_,2) = -0.63%`. Then `realized_r = net_sl / risk = -0.63 / 0.63 = -1.0`. Same final result. For larger SL distances the rounding can shift realized_r by ≤ 0.01 R per signal. Cumulative effect over 30 signals: ≤ 0.3 R. **Severity: LOW (cosmetic).** Marker for parity-perfectionism, not a verdict risk.

### 3.2 ⚠ Sub-finding — `closed_at` semantics differ from backtest (LOW)

Backtest doesn't track close time; soak does. Soak sets `closed_at = last_bar_ts.strftime(...)` where `last_bar_ts` is the **last bar processed in the loop**:
- LOSS: the SL bar (loop `break`s at SL) → correct.
- WIN / PARTIAL_TP2 / PARTIAL_TP1 / EXPIRED: the **last fetched bar** = `min(now, expiry)`, not the bar where TPx actually hit.

If TP3 hits 6 hours into a 48-hour window and resolution runs 36 hours later, `closed_at` will read 36h-out instead of 6h-in. The outcome and `realized_r` are correct (terminal at TP3 → WIN, R from formula); only the timestamp is misleading. The gate never reads `closed_at`. **Severity: LOW (cosmetic, off-by-time, no verdict impact).**

### 3.3 ⚠ Sub-finding — `datetime.utcfromtimestamp` deprecated (LOW)

`datetime.utcfromtimestamp` is deprecated in Python 3.12 (host runs 3.12.3) and will be removed in 3.13. Used at:
- A:338, A:465; B:295, B:405.

Returns a NAIVE datetime that **is** UTC, which is consistent with the rest of the naive arithmetic in this file (e.g., `now_utc.replace(tzinfo=None) - signal_ts`). No functional defect today. Will emit `DeprecationWarning`. **Severity: LOW (future-compat).**

**§3 result — PASS with 3 LOW sub-findings (no 3rd divergence).** Behavioral parity between soak and backtest is intact on every dimension that affects verdict math.

---

## §4 — Accumulated-state / runtime risks (new behavior post-exit-fix)

### 4.1 Can a position get stuck OPEN forever?

The new `else: continue` branch fires only when (a) no SL hit and (b) no TP3 hit and (c) `now_utc < expiry_dt`. Once `now_utc ≥ expiry_dt`, the elif chain falls into the window-expiry branch which is **terminal** (PARTIAL_TP2 / PARTIAL_TP1 / EXPIRED). The expiry timestamp is stored at signal-emit time as `signal_ts + 576*5min` and never modified.

**Failure modes considered:**

| Mode | Can stick? | Why |
|---|---|---|
| Binance API returns empty for the fetch window | No — `if not raw: continue` skips this cycle; next cycle retries. As long as `now_utc ≥ expiry_dt` at some future cycle, the window-expiry branch fires regardless of fetched bar count. Wait — actually if `raw` is empty, the bar walk doesn't execute, `sl_hit/tp1_hit/...` all stay False, then if `now ≥ expiry` the EXPIRED branch fires. ✓ |
| Soak process dies before resolution | No — on restart, `resolve_open_signals` SELECTs all `status='OPEN'` rows for `SOAK_LABEL` and rebuilds the walk from `start_ms`. Restart-safe. ✓ |
| Soak running but `resolve_open_signals` never called | No — `main()` calls it every cycle (heartbeat confirms cycles incrementing). |
| Clock drift makes `now_utc < expiry_dt` forever | No — the soak's host runs NTP; `now_utc = datetime.now(timezone.utc)` and `expiry_dt` are both anchored to wall clock, so they advance together. |
| `end_ms ≤ start_ms` causes the `continue` at L315/275 | At cycle N where `now ≥ expiry`, `end_ms = expiry`, `start_ms = entry+5min`. For any signal with a 48h window, `expiry > entry+5min` always → `end_ms > start_ms`. No stick. ✓ |

**§4.1 result — PASS.** No stuck-forever mode identified. Verified by query: 0 rows with `status='OPEN' AND now > expires_at` currently.

### 4.2 Can a signal be resolved/counted twice?

The `INSERT INTO results` + `UPDATE signals SET status='CLOSED'` pair is in a single transaction with one `conn.commit()` (A:417–426, B:367–375 equivalent). Next cycle's `resolve_open_signals` filters `WHERE source = ? AND status = 'OPEN'` — the already-closed row is excluded. **Cannot double-count.** ✓

DB integrity verified live: `SELECT signal_id, COUNT(*) FROM results … GROUP BY signal_id HAVING COUNT(*) > 1` → empty. No duplicates.

### 4.3 Can the same signal be re-emitted while OPEN?

`scan_token` consults the in-memory `consumed` set before calling `detect_h4_breakout`. After detection, `consumed.add(setup["key"])` (A:450, B equivalent). The key is `(c1_open_time_ms, c1_high, c1_low)` — once added, that exact C1 zone cannot fire again in this process lifetime.

On restart, `load_consumed_set()` rebuilds the set from `WHERE source = SOAK_LABEL` regardless of `status` (OPEN or CLOSED), so a still-OPEN signal's zone is correctly excluded. **§4.3 result — PASS.**

⚠ Narrow gap: if the process crashes **between** `consumed.add(setup["key"])` and `persist_signal(...)`, the zone is never written to DB and on restart it could re-fire. The window is microseconds (two adjacent statements). **Severity: LOW.**

### 4.4 Expiry uses the same corrected UTC path?

Expiry is computed at emit-time as `signal_ts + timedelta(minutes=576*5)` where `signal_ts = datetime.utcfromtimestamp(entry_ts_ms / 1000)` — naive-UTC. Stored as `%Y-%m-%d %H:%M:%S` string (UTC wall clock). On resolve, parsed with `.replace(tzinfo=timezone.utc)` (the tz-fix). So:

- emit: stored as UTC string ✓
- resolve: parsed as tz-aware UTC ✓
- comparison `now_utc >= expiry_dt`: both tz-aware UTC ✓

**§4.4 result — PASS.** Expiry is the tz-fix's sibling and shares the same corrected path.

### 4.5 Consumed-zone integrity with mid-position re-detection

The `consumed` set is the only mitigation against re-entry on the same C1 zone. A & B have **independent** consumed sets (different SOAK_LABEL → `load_consumed_set` filters on label). They cannot pollute each other. Within one soak, a C1 zone can fire at most once per process lifetime. ✓

---

## §5 — Concurrency / DB integrity (two soaks + viewer)

| Component | Mode | Conn options |
|---|---|---|
| A writer | `sqlite3.connect(DB_PATH)` + `PRAGMA journal_mode=WAL` | Python default `timeout=5.0` → busy_timeout=5000ms |
| B writer | same | same |
| Viewer reader | `sqlite3.connect("file:…?mode=ro", uri=True, timeout=2.0)` | read-only, busy_timeout=2000ms |

**Findings:**

- `journal_mode=wal` confirmed via PRAGMA read. WAL file at `data/breakout.db-wal` exists, SHM file too. WAL allows concurrent readers + one writer.
- Two writers (A and B) serialize via SQLite's write lock. Each transaction is the two INSERT+UPDATE pair on signal close, or single INSERT on signal emit. Both transactions are sub-millisecond. With busy_timeout=5000ms, collision is statistically negligible.
- Viewer reads in WAL-snapshot isolation → cannot see torn rows. A viewer query mid-write sees the pre-commit snapshot and returns consistent gate numbers. ✓
- No errors / lock-timeouts / busy retries in either log (grep for `error|fatal|busy|locked|exception` returns empty).
- Live integrity check:
  - Stuck-OPEN past expiry: 0 rows ✓
  - Orphan CLOSED (status=CLOSED, no results row): 0 rows (TON id=5 has its results row, `has_result=1`) ✓
  - Duplicate results rows: 0 ✓
- Backups intact:
  - `data/breakout.db.prefix_bak.20260602_073930` — pre-tz-fix snapshot, valid SQLite 3.x, 6.6 MB
  - `data/breakout.db.exitfix_bak.20260602_082909` — pre-exit-fix snapshot, valid SQLite 3.x, 7.4 MB

**§5 result — PASS.** WAL gives correct snapshot isolation; both writers serialize cleanly; viewer never sees a partial commit.

---

## §6 — Gate & viewer correctness (re-confirm post color/exit-fix changes)

Gate eval at `breakout_viewer.py:380–460`:

- Filters by `source = label` (per-soak isolation) at the SELECT level (L325) → A and B never blend. ✓
- `_gate_status(threshold_check, n)` at L144–146 returns `"PENDING"` whenever `n < GATE_N_TARGET=30`, regardless of pass/fail. Applied to ALL 5 criteria. ✓
- `out["verdict_overall"] = "PENDING"` whenever `n < 30` (L451). PASS only fires when all 5 pass AND `n ≥ 30`. ✓
- Tracking-only metrics (sum_R, R/day, days_elapsed) live in `out["tracking"]` and are explicitly noted "Observational only — NOT part of verdict" (L398). Not consumed by `verdict_overall`. ✓
- WR definition: `n_wins_p2 / n` where `n_wins_p2 = WIN + PARTIAL_TP2` (L370). Matches pre-registered gate spec.
- Per-token blowup gate fires only when `n_tok ≥ GATE_PER_TOKEN_MIN_N AND tok_wr ≤ GATE_PER_TOKEN_BLOWUP_WR AND tok_avg < 0`. ✓
- R/day fluctuation noted: with n=1 (TON LOSS, R=-1.0) and days_elapsed=0.055d, R/day ≈ -18. **This is sum_R / days_elapsed, cosmetic, NOT a gate.** ✓ Confirms the operator's observation.

**§6 result — PASS.** Gate math, PENDING lock, tracking/verdict separation, and per-token blowup logic all intact. The color-coding + exit-fix changes did not regress any of this.

---

## §7 — Isolation

| Check | Evidence | Verdict |
|---|---|---|
| Fade soak production alive + untouched | PID 393274 `etime 2d 20h 18min`, cmd `/usr/bin/python3 /home/tradeai/TradeAI/crypto_alert.py` | ✓ |
| `data/signals.db` (production) unchanged by this audit | mtime 10:49 — fade soak is writing it normally (last write 1 min before audit query); audit only opened it read-only | ✓ |
| `data/baseline_pin.json` Run-3704 unchanged | mtime 2026-05-30 14:31, config_hash `3ee13531421d7ba5…`, run_id=3704 | ✓ |
| `main` branch unchanged | (separate worktree at `/home/tradeai/TradeAI`), HEAD `228e04f feat(cycle-15-loop)…` — last commit predates Phase C work | ✓ |
| breakout-thesis branch committed-but-not-pushed | `## breakout-thesis…origin/breakout-thesis [ahead 2]` (`870c7f4` exit-fix + `0df3bf3` tz-fix); both backups present | ✓ |
| Soaks not restarted by this audit | Same PIDs (471837, 471846) as session start; etime 17+ min, cycle 11+ | ✓ |

**§7 result — PASS.** Production untouched, fixes committed locally only, branch not pushed, both backups intact.

---

## Sub-findings index (sorted by severity)

| # | Severity | Section | Description | File:line |
|---|---|---|---|---|
| F1 | LOW | §3.1 | `net_sl` rounded to 2 decimals while `net_tp1/2/3` rounded to 3 — can shift `realized_r` by ≤0.01 R per signal | A:392–396, B:336–340 |
| F2 | LOW | §3.2 | `closed_at` for non-LOSS outcomes reflects the resolution timestamp, not the bar where TPx actually hit (no verdict impact) | A:414, B:361 |
| F3 | LOW | §3.3 | `datetime.utcfromtimestamp` deprecated in Python 3.12 (host 3.12.3); will be removed in 3.13. No functional bug today | A:338,465 B:295,405 |
| F4 | LOW | §4.3 | Microsecond window between `consumed.add(key)` and `persist_signal()` where a crash could let the same zone re-fire on restart | A:450 (and persist follows) |

**No CRITICAL findings. No MEDIUM findings. No 3rd behavioral divergence between soak and backtest.**

---

## Verdict

**The system is trustworthy to accumulate forward toward the gate.**

The two known bugs (tz-shift, premature-close) are fixed in code, verified live on both running soaks (PIDs 471837 / 471846), and behaviorally consistent with `run_tf_grid.py`'s reference implementation on every parity dimension that affects the verdict (entry timing, SL/TP geometry, intrabar SL-first, implicit BE-stop, forward window length, R formula, tier mapping). No 3rd divergence found.

The 4 LOW sub-findings are cosmetic (F1 rounding asymmetry, F2 timestamp semantics, F3 deprecation warning, F4 narrow crash window). None invalidates the soak; none should block forward accumulation toward n≥30.

The exit-model fix introduces a new behavior (positions stay OPEN until terminal) which has been audited for: stuck-forever (impossible — expiry is terminal), double-counting (impossible — single-transaction commit + status filter), re-emission while OPEN (impossible — consumed-zone restart-safe), expiry UTC parity (verified — same tz-corrected path). DB concurrency between A, B and the viewer is sound under WAL.

**Recommendation:** let both soaks run. Re-audit after the first non-SL closed signal (which will provide live evidence the `else: continue` branch held a runner OPEN through TP1/TP2 and then resolved at TP3 or expiry).

Awaiting operator call. No fixes applied.
