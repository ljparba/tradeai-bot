# Phase C-Breakout — Audit of B Soak Addition + Viewer Rewrite (read-only)

**Date:** 2026-06-02 ~04:13 UTC
**Scope:** the additions/changes since the prior audit (`PHASE_C_AUDIT.md`):
new `breakout_paper_soak_B.py`, rewritten `breakout_viewer.py`, new
`TF_B_SOAK_PRE_REGISTER.md`. Verifies (a) B is correctly Config B, (b) B's
addition did not regress A, and (c) the viewer rewrite did not regress any
read-only / per-soak-filter invariant from the prior audit.
**Mode:** read-only. No code changes. Neither soak touched.

> **Verdict: BOTH SOAKS TRUSTWORTHY AS-IS. NO RESTART NEEDED.**
> Six sections PASS. **Zero critical, zero medium-severity defects.** Two LOW-
> severity cosmetic items recorded for completeness.

---

## 1. B-soak Config correctness — **PASS**

### 1.1 Config 14 fingerprint identical to A

`breakout_paper_soak_B.py:56-64`:

```python
CONFIG_14 = {
    "H4_BREAKOUT_CLOSE_BUFFER_PCT": 0.001,
    "BREAKOUT_TP1_RR":              2.0,
    "BREAKOUT_TP2_RR":              3.0,
    "BREAKOUT_TP3_RR":              4.0,
    "H4_BREAKOUT_C2_LOOKBACK":      4,
    "H4_BREAKOUT_MSS_HORIZON":      30,
}
```

Bit-identical to A's `CONFIG_14` at `breakout_paper_soak.py:73-80`. Verified
via `diff` (no value differences, only docstring + adjacent commentary lines).

`breakout_paper_soak_B.py:64-65` writes these to `os.environ` BEFORE importing
`breakout_engine`, so the engine's module-level `_env_float` / `_env_int`
constants resolve to Config 14 values at import time — same mechanism as A.

### 1.2 Reference timeframe = 1H (the ONLY structural delta vs A)

`breakout_paper_soak_B.py:95-100`:

```python
SOAK_LABEL = "H4_BREAKOUT_PAPER_SOAK_B"
REF_BAR_DURATION_MS = 1 * 60 * 60 * 1000   # 1h in ms
REF_TF_INTERVAL = "1h"
```

vs A (`breakout_paper_soak.py:81`): hardcoded "4h" string in the
`fetch_klines(..., "4h", ...)` call at line 419.

The detector handoff at `breakout_paper_soak_B.py:360-371`:

```python
c5m = fetch_klines(symbol, "5m", OHLCV_5M_LIMIT)          # entry TF
c1h = fetch_klines(symbol, REF_TF_INTERVAL, OHLCV_1H_LIMIT)  # reference TF
...
setup = detect_h4_breakout(c1h, c5m, token=token, consumed=consumed)
```

The engine's parameter names are `c4h, c5m` (legacy from H4 development) but
the function treats both arguments as opaque dicts of OHLCV arrays — the
"4h" in the parameter name has no semantic effect. Passing `c1h` as the
first argument means the engine treats 1H bars as the reference, exactly
what we want for Config B.

### 1.3 NOT fading — same breakout detector as A

`breakout_paper_soak_B.py:67-68`:
```python
from breakout_engine import (
    detect_h4_breakout, compute_breakout_sl_tp,
    H4_BREAKOUT_C2_LOOKBACK,
)
```

Same engine, same direction-inversion logic verified in `PHASE_C_AUDIT.md §1`
(C2 closes BEYOND C1.high → BUY continuation; C2 closes BELOW C1.low →
SELL continuation). B inherits that inversion bit-exactly because it imports
the same function.

### 1.4 60-min staleness guard present

`breakout_paper_soak_B.py:382-385`:

```python
age_sec = (datetime.now(timezone.utc).replace(tzinfo=None) - signal_ts).total_seconds()
if age_sec > 3600:
    _log(f"  {token}: signal too stale ({age_sec:.0f}s old), skipping")
    return False
```

Bit-identical to A at `breakout_paper_soak.py:447-450`. Confirmed in B's log:
`[2026-06-02 03:58:50]   BTC: signal too stale (8630s old), skipping`
The guard fired on startup, as it should.

### 1.5 NO overlays imported

Verified via greps in B's source — all of the following are **absent**:

| Forbidden | Found? |
|---|---|
| `adaptive_engine` | ✓ absent |
| `crypto_alert` | ✓ absent |
| `backtest` (import) | ✓ absent |
| `funding_rate_client` | ✓ absent |
| `btc_correlation` | ✓ absent |
| `detect_wyckoff_context` | ✓ absent |
| `WYCKOFF_PHASE_FILTER` env access | ✓ absent |
| `FUNDING_BONUS_PCT` env access | ✓ absent |
| `BTC_CORR_BONUS_PCT` env access | ✓ absent |
| `token_weights` SQL touch | ✓ absent |

Full executable import list of B (`grep -nE "^(import|from)"`): only stdlib,
plus `breakout_engine`, `crt_engine.compute_crt_trade_economics`,
`ict_engine.TOKEN_RT_COST/ROUND_TRIP_COST_PCT`. No adaptive / overlay modules.

**Section 1 verdict: PASS.** Config 14 bit-exact, TF correctly switched to 1H,
detector is the breakout (not fade) engine, staleness guard present, no
overlay imports.

---

## 2. A vs B shared-state / contamination check — **PASS**

### 2.1 A's source file is BYTE-IDENTICAL to its committed state

```bash
git diff HEAD -- breakout_paper_soak.py
# Returns nothing — A has no uncommitted modifications.
```

A's source file was last committed in `739f2ff` (the Step 2 commit, before B
existed). The file has not been touched since. The currently-running A
process (PID 458923, started 03:37:51, elapsed 02:35:57 at audit time) is
running the exact code from that commit.

### 2.2 Separate runtime state paths (verified)

| | A | B |
|---|---|---|
| Source | `breakout_paper_soak.py` | `breakout_paper_soak_B.py` |
| PID file | `data/breakout_soak.pid` | `data/breakout_soak_B.pid` |
| Heartbeat | `data/breakout_soak_heartbeat.json` | `data/breakout_soak_B_heartbeat.json` |
| Log | `logs/breakout_soak.log` | `logs/breakout_soak_B.log` |
| Source tag (DB) | `'H4_BREAKOUT_PAPER_SOAK'` | `'H4_BREAKOUT_PAPER_SOAK_B'` |
| Entry-type prefix | `H4_BREAKOUT_<conf>` | `H4_BREAKOUT_<conf>_B` |
| Reference TF | 4h | 1h |

Direct read of PID files:
```
A PID file: 458923   (matches A's running PID)
B PID file: 465237   (matches B's running PID, started 05:58:48)
```

The two PID files mtimes (03:37 for A, 05:58 for B) confirm A's PID file was
never touched when B was added.

### 2.3 Independent OS processes

Different PIDs imply OS-level memory isolation. The only resource the two
processes share is the DB file `breakout.db`. Verified writers via `lsof`:

```
COMMAND    PID    USER   FD   TYPE DEVICE SIZE/OFF    NODE NAME
python3 458923 tradeai    3ur  REG    8,1  6590464 1326260 ...breakout.db
python3 465237 tradeai    3ur  REG    8,1  6590464 1326260 ...breakout.db
```

Both processes have the file open in `3ur` mode (file descriptor 3, update +
read). SQLite WAL mode handles concurrent writers + readers safely — each
INSERT/UPDATE appends to the `-wal` sidecar, and per-statement `conn.commit()`
keeps the contended-transaction window minimal.

`breakout_paper_soak_B.py:159`:
```python
conn.execute("PRAGMA journal_mode=WAL")
```
matches A at `breakout_paper_soak.py:177`. Both soaks call `conn.commit()`
immediately after each `INSERT`/`UPDATE` (B at lines 237, 349; A at lines
265, 407).

### 2.4 Consumed-zone sets ISOLATED per soak

`breakout_paper_soak_B.py:163-173`:
```python
def load_consumed_set(conn) -> set:
    """Rebuild consumed-zone set from B's own signal rows only (NOT A's).

    Filters by SOAK_LABEL so A's writes never pollute B's mitigation set.
    """
    consumed = set()
    rows = conn.execute(
        "SELECT feature_scores_json FROM signals WHERE source = ?",
        (SOAK_LABEL,),
    ).fetchall()
```

The filter `WHERE source = ?` with `SOAK_LABEL = 'H4_BREAKOUT_PAPER_SOAK_B'`
guarantees B's consumed set is built ONLY from B's own historical rows.
A's writes (source = `'H4_BREAKOUT_PAPER_SOAK'`) cannot enter B's `consumed`
set, and vice versa.

**Consequence:** A and B can emit signals on the same `(c1_time, c1_high,
c1_low)` zone independently — each soak treats the zone as fresh from its
own perspective. This is structurally correct: A and B are testing different
reference timeframes, so the meaning of a "consumed zone" is per-strategy.

### 2.5 A's behavior is unchanged by B's existence

The audit's prior `PHASE_C_AUDIT.md` verified A's correctness at commit
`739f2ff`. A's source is byte-identical to that commit (§2.1). A's process
was started May 30 03:37 — it has Python's module cache fixed at that
moment. Even if A's `.py` file had been modified after start (which it
wasn't, per §2.1), the running A process would not pick up the change until
restart.

**Direct confirmation:** A's heartbeat shows cycle 78 (started at cycle 0 on
process start; ~78 × 2 min = ~156 min into operation, consistent with the
elapsed time of 02:35 = 155 min). No restart, no crash, no behavior change.

### 2.6 No shared in-memory state, no shared cache

Each soak runs in its own Python process. The `consumed` set, the open DB
cursor, the `_RUNNING` flag, the per-token last-fetched cache — all of these
live in process-local memory. The OS guarantees no cross-process access.

The only shared mutable resource is `data/breakout.db` (SQLite, WAL mode),
and the only shared *path* is `logs/` (with distinct filenames).

**Section 2 verdict: PASS.** A's code, runtime state, and behavior are
unchanged by B's introduction. B uses correctly-isolated state files and
distinct source tags. No code path of A was touched.

---

## 3. Viewer correctness (rewritten) — **PASS**

### 3.1 Read-only DB connection enforced at SQLite C level

`breakout_viewer.py:98-103`:
```python
def _open_ro_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"breakout.db missing at {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn
```

`mode=ro` URI — any `INSERT/UPDATE/DELETE/CREATE` raises
`sqlite3.OperationalError: attempt to write a readonly database`. Verified
in the prior audit's smoke test (DB mtime unchanged after multiple API hits).

Re-confirmed in this audit: DB mtime before/after 5 API hits was
`2026-06-02 03:32:19.115876` both times — read traffic does not touch the
file.

### 3.2 HTTP write methods blocked

`breakout_viewer.py:635-638`:
```python
def do_POST(self):   self.send_error(405)
def do_PUT(self):    self.send_error(405)
def do_DELETE(self): self.send_error(405)
def do_PATCH(self):  self.send_error(405)
```

Confirmed via curl in the prior smoke test: `POST / → HTTP 405`.

### 3.3 Localhost-only bind

`breakout_viewer.py:63`:
```python
HOST = "127.0.0.1"
```
Used at line 653 in `TCPServer((HOST, PORT), ...)`. Public-internet
unreachable.

### 3.4 Per-column source-tag filter — A's column reads ONLY A's rows, B's column ONLY B's rows

The viewer has TWO soak specs at `breakout_viewer.py:75-93`:

```python
SOAKS = [
    {"key": "A", "label": "Soak A — 5M / 4H",
     "soak_label": "H4_BREAKOUT_PAPER_SOAK", ... },
    {"key": "B", "label": "Soak B — 5M / 1H",
     "soak_label": "H4_BREAKOUT_PAPER_SOAK_B", ... },
]
```

`collect_state()` at line 354-370 iterates each spec independently:
```python
for spec in SOAKS:
    try:
        state["soaks"][spec["key"]] = collect_one_soak(spec)
```

`collect_one_soak(spec)` at line 148+ uses `label = spec["soak_label"]`
(line 207) for all subsequent queries. The three SQL filters at lines
218-219, 230-231, 277-278 all use `(label,)` as the bound parameter:

```sql
WHERE s.source = ? AND s.status = 'CLOSED'   -- line 223
WHERE source = ? AND status = 'OPEN'         -- line 232
WHERE source = ? ORDER BY id ASC LIMIT 1     -- line 277
```

**A's column → A's source tag → A's rows. B's column → B's source tag →
B's rows. No SQL path crosses soaks.** The closure of `collect_one_soak`
on its local `label` variable also prevents accidental late-binding from
SOAKS iteration.

### 3.5 ONLY `signals` + `results` tables — backtest tables NEVER queried

```bash
grep -nE "FROM (signals|backtest_signals|backtest_runs|results)" breakout_viewer.py
```
Results:
```
222: FROM signals s JOIN results r ON r.signal_id = s.id
232: FROM signals WHERE source = ? AND status = 'OPEN'
277: SELECT timestamp FROM signals WHERE source = ?
```

**Zero reads from `backtest_signals` or `backtest_runs`.** The TF grid runs
(rows in `backtest_signals` tagged `H4_BREAKOUT_TF_*_CLEAN` / `_FRICTION`)
cannot bleed into the soak columns even if their source strings overlapped
(they don't), because the viewer never queries that table.

### 3.6 verdict_overall locked PENDING until n ≥ 30 — per soak

`breakout_viewer.py:339-345`:
```python
if n < GATE_N_TARGET:
    out["verdict_overall"] = "PENDING"
elif avg_r_pass and pf_pass and wr_pass and max_dd_pass and blowup_pass:
    out["verdict_overall"] = "PASS"
else:
    out["verdict_overall"] = "FAIL"
```

The check `n < GATE_N_TARGET` evaluates on `n = len(closed)` for THIS soak's
closed signals (line 248). It is impossible for B's verdict to flip while
A is at n=35: each `collect_one_soak(spec)` runs with its own `n` and its
own `out` dict.

`_gate_status(threshold_check, n_signals)` at line 134-137:
```python
if n_signals < GATE_N_TARGET:
    return "PENDING"
return "PASS" if threshold_check else "FAIL"
```

This is called per-criterion at lines 328, 331, 333, 335, 337 with the same
`n` — so every criterion ALSO shows PENDING individually until n ≥ 30.

### 3.7 Tracking-only block is NOT wired into verdict

`breakout_viewer.py:175` (init):
```python
"tracking":    {},     # observational, not part of verdict
```

`breakout_viewer.py:274-291` (populated):
```python
# Tracking-only metrics (NOT in verdict)
first_signal_ts = None
first_rows = list(conn.execute(...))
...
out["tracking"] = {
    "sum_R":              round(sum_r, 3),
    "R_per_day":          round(sum_r / days_elapsed, 4) if days_elapsed else 0,
    "days_elapsed":       round(days_elapsed, 2),
    "first_signal_ts":    first_signal_ts,
    "ref_avg_R_friction": spec["ref_avg_R"],
    "ref_source":         spec["ref_source"],
    "note": "Observational only — NOT part of verdict. See ...",
}
```

The verdict_overall logic (lines 339-345 from §3.6) reads only `n`,
`avg_r_pass`, `pf_pass`, `wr_pass`, `max_dd_pass`, `blowup_pass`.
**Tracking values are NEVER referenced in the verdict path.**

HTML (line 545):
```html
<div class="tracking">
  <div class="label">Tracking-only (NOT in verdict)</div>
  ...
</div>
```

Visually distinct (different background color via CSS class `.tracking`)
with the explicit "NOT in verdict" caption.

**Section 3 verdict: PASS.** Viewer is read-only, per-column source-filtered
(no cross-bleed), PENDING-locked until n ≥ 30 per soak independently, and
tracking metrics never influence the verdict.

---

## 4. Gate / pre-registration integrity — **PASS**

### 4.1 TF_B_SOAK_PRE_REGISTER.md §3 thresholds match viewer constants

| Criterion | Pre-reg threshold | Viewer constant | Match? |
|---|---|---|---|
| avg_R per closed ≥ +0.40 | `+0.40` | `GATE_AVG_R_MIN = 0.40` (line 68) | ✓ |
| Profit factor ≥ 2.0 | `2.0` | `GATE_PF_MIN = 2.0` (line 69) | ✓ |
| WR strict ≥ 55% | `55%` | `GATE_WR_MIN = 0.55` (line 70) | ✓ |
| Max drawdown ≤ 20 R | `20` | `GATE_MAX_DD_R = 20.0` (line 71) | ✓ |
| Per-token blowup: WR ≤ 35% AND avg_R < 0 over ≥ 5 sigs | `n ≥ 5, WR ≤ 35%, avg_R < 0` | `GATE_PER_TOKEN_MIN_N = 5` (line 72) + `GATE_PER_TOKEN_BLOWUP_WR = 0.35` (line 73) | ✓ |
| n closed ≥ 30 | `30` | `GATE_N_TARGET = 30` (line 67) | ✓ |

**All six match bit-exactly.** Pre-registration is honored by the code.

### 4.2 Same thresholds applied to A and B

Per the pre-reg §3 ("Same five criteria as A's soak"), A and B share the
same 5 gate constants. The viewer's GATE_* constants are global (not
per-spec), so by construction both columns apply identical thresholds.

### 4.3 WR caveat + friction-on reference recorded

Pre-reg §4 documents:
- A's friction-on backtest WR = 69.1% (comfortable cushion vs 55% floor)
- B's friction-on backtest WR = 61.8% (closer to floor)
- WR floor "may be unfavorable to B's structural profile"

Pre-reg §8 documents:
- A friction-on reference avg_R = +0.616
- B friction-on reference avg_R = +0.549

Both are surfaced in the viewer:
- `breakout_viewer.py:83` — `"ref_avg_R": 0.616` for A
- `breakout_viewer.py:92` — `"ref_avg_R": 0.549` for B
- HTML line 529 — `ref friction avg_R = +${(s.ref_avg_R||0).toFixed(3)}`
- HTML line 550 — friction-on ref card

### 4.4 Tracking metrics surfaced per pre-reg §5

Pre-reg §5 calls for `sum_R`, `R per day`, friction-on reference as
"observational only, NOT part of verdict". Viewer surfaces:
- `breakout_viewer.py:283` — `"sum_R": round(sum_r, 3)`
- `breakout_viewer.py:284` — `"R_per_day": round(sum_r / days_elapsed, 4)`
- `breakout_viewer.py:287` — `"ref_avg_R_friction": spec["ref_avg_R"]`
- `breakout_viewer.py:288` — `"note": "Observational only — NOT part of verdict..."`

**Section 4 verdict: PASS.** Documented gate and implemented gate are
identical. Caveat + friction reference are recorded and surfaced.

---

## 5. R / outcome accounting — **PASS**

### 5.1 R-multiple mapping identical to A and to backtest

B's `resolve_open_signals` at `breakout_paper_soak_B.py:323-339`:

```python
if outcome == "LOSS":
    realized_r = round(net_sl / risk, 4); profit_pct = net_sl
elif outcome == "PARTIAL_TP1":
    realized_r = round((0.5 * net_tp1) / risk, 4)
    profit_pct = round(0.5 * net_tp1, 3)
elif outcome == "PARTIAL_TP2":
    realized_r = round((0.5 * net_tp1 + 0.5 * net_tp2) / risk, 4)
    profit_pct = round(0.5 * net_tp1 + 0.5 * net_tp2, 3)
elif outcome == "WIN":
    realized_r = round((0.5 * net_tp1 + 0.5 * net_tp3) / risk, 4)
    profit_pct = round(0.5 * net_tp1 + 0.5 * net_tp3, 3)
else:
    realized_r = 0.0; profit_pct = 0.0
```

Bit-identical to A's at `breakout_paper_soak.py:381-401` (only whitespace
differs — A uses newlines, B uses semicolons in places). Same split-exit
50/50 model.

This is also bit-identical to the TF backtest's `_calc_realized_r` in
`run_tf_grid.py` (the function used by the TF comparison study), so B's
forward avg_R is directly comparable to the +0.549 friction-on backtest
expectation.

### 5.2 Gross %s computed correctly per direction

`breakout_paper_soak_B.py:309-317`:

```python
if direction == "BUY":
    gross_tp1 = (tp1 - entry)/entry * 100
    gross_tp2 = (tp2 - entry)/entry * 100
    gross_tp3 = (tp3 - entry)/entry * 100
    gross_sl  = (sl - entry)/entry * 100
else:
    gross_tp1 = (entry - tp1)/entry * 100
    gross_tp2 = (entry - tp2)/entry * 100
    gross_tp3 = (entry - tp3)/entry * 100
    gross_sl  = (entry - sl)/entry * 100
```

For BUY: TP prices are above entry → positive gross %; SL below entry →
negative gross %. For SELL: mirror. Standard.

`net_<x> = round(gross_<x> - rt_cost_pct, ndp)` at lines 319-322 — uses
per-token RT cost via `TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100`
at line 308. Same per-token cost basis as A and the backtest.

### 5.3 Intrabar SL-first check_outcome — same conservative logic

`breakout_paper_soak_B.py:290-305`:

```python
if direction == "BUY":
    if not sl_hit and not tp1_hit and l_p <= sl: sl_hit = True; break
    if not tp1_hit and h_p >= tp1: tp1_hit = True
    if tp1_hit and not tp2_hit and h_p >= tp2: tp2_hit = True
    if tp2_hit and not tp3_hit and h_p >= tp3: tp3_hit = True
else:
    if not sl_hit and not tp1_hit and h_p >= sl: sl_hit = True; break
    if not tp1_hit and l_p <= tp1: tp1_hit = True
    if tp1_hit and not tp2_hit and l_p <= tp2: tp2_hit = True
    if tp2_hit and not tp3_hit and l_p <= tp3: tp3_hit = True
```

Same SL-first check, same `not tp1_hit` guard that implements the
"move-stop-to-BE-after-TP1" assumption. Same as A and the backtest's
`check_outcome`.

### 5.4 Signal close-out lifecycle complete

`breakout_paper_soak_B.py:340-349`:
```python
cur.execute(
    "INSERT INTO results (signal_id, tp1_hit, tp2_hit, tp3_hit, "
    " sl_hit, result, profit_pct, closed_at, realized_r) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (sig_id, int(tp1_hit), int(tp2_hit), int(tp3_hit), int(sl_hit),
     outcome, profit_pct, closed_at, realized_r),
)
cur.execute(
    "UPDATE signals SET status = 'CLOSED' WHERE id = ?", (sig_id,),
)
conn.commit()
```

Both INSERT to `results` AND UPDATE `signals.status = 'CLOSED'` are present
and committed together. The viewer's `JOIN signals ON r.signal_id = s.id
WHERE s.status = 'CLOSED'` pattern (line 215-216) will correctly include
B's resolved signals.

**Section 5 verdict: PASS.** B's R-accounting is bit-equivalent to A's and
to the backtest harness's. Forward avg_R is directly comparable to the
+0.549 friction-on backtest expectation per §4.3.

---

## 6. Isolation re-verify — **PASS**

| Item | State |
|---|---|
| Fade soak alive | PID 393274, cycle 8274, 0 errors, 12/12 tokens, ts 04:12 UTC |
| `signals.db` (fade) | 5,492,736 bytes — **unchanged** |
| Run-3704 pin | `run_id = 3704`, mtime 2026-05-30 14:31:11 — **unchanged** |
| Soak A alive | PID 458923, cycle 78, ts 2026-06-02 04:12:01 UTC, started 03:37:51, elapsed 02:35:57 |
| Soak A open/closed | 0 / 0 (no signals have qualified yet — consistent with §FADE_CRT_DIAGNOSIS regime drag) |
| Soak A source file | **byte-identical** to commit `739f2ff` (no uncommitted changes) |
| Soak B alive | PID 465237, cycle 8, ts 2026-06-02 04:12:53 UTC, started 05:58:48, elapsed 15:00 |
| Soak B open/closed | 0 / 0 (no signals yet — newly started ~15 min ago) |
| `breakout.db` writers (via lsof) | 458923 + 465237 ONLY |
| Branch state | `breakout-thesis @ 70852df` on origin — **not advanced** by B addition |
| `main` branch | `af331b9` on origin — **NOT touched** |
| Operator-launched viewer | PID 465737 — running the new A+B viewer code (launched after I freed port 8890 in the prior step) |

The operator launched the viewer at PID 465737 after I left port 8890 free.
Verified via `/proc/465737/cwd → /home/tradeai/breakout-work` and 4 open fds
(consistent with the viewer's per-request connection pattern).

---

## 7. Findings inventory

### Critical (would invalidate either soak) — **0**

None.

### Medium (would warrant fixing before trusting forward data) — **0**

None.

### Low (cosmetic / informational; no soak invalidation) — **2**

**LOW-1 — `.gitignore` does not cover B's runtime files.**
The existing `.gitignore` includes `data/breakout_soak.pid` and
`data/breakout_soak_heartbeat.json` (B's analogs are missing). If the
operator ever runs `git add data/`, the B PID file and heartbeat file would
be staged. They contain only a PID number and a JSON snapshot — no secrets,
no DB data — so accidental commit is harmless. Proposed fix:
`.gitignore` → add `data/breakout_soak_B.pid` and
`data/breakout_soak_B_heartbeat.json`. **Do not apply without operator OK.**

**LOW-2 — B's `entry_type` adds a `_B` suffix.**
`breakout_paper_soak_B.py:226` writes `entry_type = f"H4_BREAKOUT_{confluence_type}_B"`.
A's entry_type (e.g. `H4_BREAKOUT_FVG` from `breakout_paper_soak.py:286`)
does NOT include any suffix. **This is intentional and a feature: it makes
the entry_type column self-identify which soak produced the row even
without joining on `source`.** It does mean any future analytics that
groups by entry_type assuming A's format would not naturally match B's
rows. Per-soak analysis using `source =` correctly distinguishes them.
**No fix needed.**

### Items explicitly verified ABSENT (suspicions ruled out)

| Suspicion | Ruled out because |
|---|---|
| B silently still fading | B imports the same `detect_h4_breakout` from `breakout_engine` whose direction-inversion was verified in `PHASE_C_AUDIT.md §1` |
| B using A's 4H reference by mistake | §1.2 confirms `REF_TF_INTERVAL = "1h"` and the fetch call uses it at line 361 |
| A's behavior changed by B addition | A's source file is byte-identical to its committed state (§2.1). A's process started May 30 03:37 and has Python module cache fixed from that time (§2.5) |
| Cross-soak consumed-zone pollution | B's `load_consumed_set` filters by `SOAK_LABEL = 'H4_BREAKOUT_PAPER_SOAK_B'` only — A's rows cannot enter B's set (§2.4) |
| WAL writer collision | Both soaks use `PRAGMA journal_mode=WAL` (§2.3) and commit per-statement; the OS-level lsof confirms both as concurrent writers without blocking |
| Viewer cross-bleed between A and B columns | Closure of `collect_one_soak(spec)` on its local `label` variable; SQL parameter `(label,)` at each query (§3.4) |
| Viewer reading backtest_signals/TF grid rows | Grep proves only `signals` + `results` tables queried (§3.5) |
| B-column verdict flipping while A < 30 | Per-soak `n` is computed independently in each `collect_one_soak(spec)` call (§3.6) |
| Tracking metrics influencing verdict | `verdict_overall` is set only in 5 places (lines 176, 341, 343, 345, 368), none of which reference the `tracking` dict (§3.7) |
| Pre-reg / code drift | Bit-exact match across all 6 gate values (§4.1) |
| R-accounting drift | Bit-equivalent split-exit model across B, A, and the backtest harness (§5.1) |

---

## 8. Final recommendation

**Both soaks are TRUSTWORTHY AS-IS. Do NOT restart either.**

- **Soak A (PID 458923):** byte-identical to its audited state. Behavior
  unchanged. Continue forward.
- **Soak B (PID 465237):** correctly configured for Config B (5M/1H),
  R-accounting bit-equivalent to A and to the backtest expectation, gate
  math matches the pre-registration, no overlay contamination.
- **Viewer (PID 465737, operator-launched):** read-only, per-column source-
  filtered, PENDING-locked until each soak independently hits n ≥ 30. No
  cross-bleed.

The two LOW-severity items are cosmetic and do not affect either soak's
forward validity. Neither requires a code change to honor the pre-
registered gates.

**Do NOT push, merge, or arm live on the strength of this audit.** This
audit only confirms the parallel-B configuration is structurally correct.
The locked gate criteria for B (and A) still need to be met on ≥ 30 closed
forward signals before either soak's results can be acted on.

---

## 9. Reproducibility

```bash
# §1.1 — Config 14 bit-exact match
diff <(grep -A8 "CONFIG_14 = {" /home/tradeai/breakout-work/breakout_paper_soak.py | head -10) \
     <(grep -A8 "CONFIG_14 = {" /home/tradeai/breakout-work/breakout_paper_soak_B.py | head -10)

# §2.1 — A's source unchanged
git -C /home/tradeai/breakout-work diff HEAD -- breakout_paper_soak.py
# (empty output = unchanged)

# §2.3 — DB writer enumeration
lsof /home/tradeai/breakout-work/data/breakout.db

# §3.5 — viewer only reads signals/results
grep -nE "FROM (signals|backtest_signals|backtest_runs|results)" \
  /home/tradeai/breakout-work/breakout_viewer.py

# §4.1 — gate constants
grep -E "^GATE_" /home/tradeai/breakout-work/breakout_viewer.py
```
