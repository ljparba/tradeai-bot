# Phase C-Breakout — Live Resolution-Loop Robustness Audit

**Mode:** read-only / diagnostic only. No code changed, no DB written, no soak restarted.
**Audited:** 2026-06-03 ~12:10 UTC.
**Audited processes:** A PID 486821, B PID 486822 (alive, BE-after-TP1 model, untouched).

**Premise:** prior audits covered engine logic + backtest causality. This one focuses on the OPERATIONAL live loop — data fetching, error handling, real-time resolution. The class of bug the backtest cannot test.

---

## §3 — PRIORITY: 500-bar fetch vs 576-bar 48h window

**Finding: NOT a bug.** The resolution loop uses a SEPARATE Binance fetch with explicit start/end times.

[`breakout_paper_soak_B.py:271-278`](breakout_paper_soak_B.py#L271-L278):

```python
start_ms = int(entry_dt.timestamp() * 1000) + 5 * 60 * 1000
end_ms = int(min(now_utc, expiry_dt).timestamp() * 1000)
if end_ms <= start_ms:
    continue
url = (f"{BINANCE_BASE}?symbol={symbol}&interval=5m&limit=1000&"
       f"startTime={start_ms}&endTime={end_ms}")
```

| Constraint | Value | Check |
|---|---|---|
| 48h window | 576 5m bars | ✓ |
| Resolution fetch limit | **1000 bars** (~83h) | ✓ exceeds 576 |
| Start time | entry + 5min UTC (tz-fixed) | ✓ explicit |
| End time | `min(now, expiry)` UTC | ✓ never fetches future bars |

The signal-generation fetch (`OHLCV_5M_LIMIT=500`, rolling) and the resolution fetch (`limit=1000`, explicit window) are **two independent calls**. A position 41h old never falls outside its resolution window — the resolution call requests bars by absolute timestamps with a 1000-bar limit.

**§3 result: PASS.**

---

## §1 — Data-fetch failure handling

[`breakout_paper_soak_B.py:121-156`](breakout_paper_soak_B.py#L121-L156) — `fetch_klines`:

```python
def fetch_klines(symbol: str, interval: str, limit: int) -> Optional[dict]:
    ...
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    _log(f"  [{symbol} {interval}] HTTP {resp.status}, retrying")
                    _time.sleep(2 * (attempt + 1))
                    continue
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            _log(f"  [{symbol} {interval}] fetch error: {e!r}, retrying")
            _time.sleep(2 * (attempt + 1))
            continue
        if not raw or not isinstance(raw, list):
            return None
        ...
        return {"opens": opens, ...}
    return None
```

| Failure mode | Behavior |
|---|---|
| HTTP non-200 | Logged + retry up to 3× with backoff (2s, 4s, 6s) |
| URLError / TimeoutError / JSONDecodeError | Logged + retry up to 3× |
| Empty/non-list response | Return `None` immediately (no retry) |
| All 3 attempts fail | Return `None` |
| Forming bar | Always dropped via `raw[:-1]` |

Downstream handling [`breakout_paper_soak_B.py:388-392`](breakout_paper_soak_B.py#L388-L392):

```python
c5m = fetch_klines(symbol, "5m", OHLCV_5M_LIMIT)
c1h = fetch_klines(symbol, REF_TF_INTERVAL, OHLCV_1H_LIMIT)
if c5m is None or c1h is None:
    _log(f"  {token}: fetch failed, skipping cycle")
    return False
if len(c1h["closes"]) < H4_BREAKOUT_C2_LOOKBACK + 5:
    return False
```

| Question | Answer |
|---|---|
| Does fetch failure crash the cycle? | **No** — `scan_token` returns `False` after a clean log message |
| Does one token's failure affect others? | **No** — each token is independently handled in the main scan loop |
| Does empty/short array cause a bogus signal? | **No** — `len(c1h["closes"]) < 9` check + the engine's own length guards (`mss_bar + 1 >= len(c5m["opens"])` at L406) prevent emit |
| Does fetch error in resolution propagate? | **No** — resolution loop at L280-289 has the same `try / except / continue` pattern |

**§1 result: PASS.** Clean skip, retry with backoff, per-token isolation.

One LOW finding: there's no explicit minimum bar count check for 5m (relying on `H4_BREAKOUT_C2_LOOKBACK + 5` on the 1h side). The engine's internal guards catch this — but documenting it would be cleaner.

---

## §2 — Bar-gap / missing-candle handling

[`breakout_paper_soak_B.py:294-300`](breakout_paper_soak_B.py#L294-L300):

```python
for bar in raw:
    h_p = float(bar[2])
    l_p = float(bar[3])
    last_bar_ts = datetime.fromtimestamp(int(bar[6]) / 1000, tz=timezone.utc).replace(tzinfo=None)
    if direction == "BUY":
        if not tp1_hit and not sl_hit and l_p <= sl:
            sl_hit = True; break
        ...
```

The walk iterates bars in the order Binance returned them (Binance always returns klines in ascending time order, so order is guaranteed). The walk is **INDEX-BASED, not timestamp-based** — it processes each bar's high/low without checking that the bar timestamp is contiguous with the previous one.

| Aspect | Behavior |
|---|---|
| Walk iteration | `for bar in raw` — pure index iteration |
| Contiguity check | **NONE** — gaps would be silently skipped |
| Outcome flags | Only depend on h/l touching SL/TP/BE — not on bar count or timing |
| `last_bar_ts` accuracy | Tracks the LAST processed bar's time — if gap exists, may be earlier than expected |
| Expiry check | `now_utc >= expiry_dt` — wall-clock based, not bar-count based ✓ |

**Practical impact of a Binance gap (rare):**
- If a 5m bar is missing from the fetch, the walk doesn't see it. The strategy's flags (`tp1_hit`, `sl_hit`, etc.) only trip if a bar's high/low crosses a level — a missing bar simply means we don't get to evaluate that 5-min window. The flags carry over from prior bars correctly.
- The `closed_at` timestamp (set from `last_bar_ts`) would reflect the LAST actually-processed bar, which may be slightly earlier than reality if gaps exist near the close.
- The outcome classification (LOSS / WIN / PARTIAL_TP1 / etc.) is determined by whichever flag triggers first — gap doesn't change this since flags are stateful across bars.

**§2 result: PASS with LOW caveat.** Bar gaps don't corrupt outcome classification, but `closed_at` precision could be off by a few minutes in the rare gap scenario. Cosmetic only.

---

## §4 — Restart / crash recovery

[`breakout_paper_soak_B.py:164-185`](breakout_paper_soak_B.py#L164-L185) — `load_consumed_set`:

```python
def load_consumed_set(conn) -> set:
    """Rebuild consumed-zone set from B's own signal rows only (NOT A's)."""
    consumed = set()
    rows = conn.execute(
        "SELECT feature_scores_json FROM signals WHERE source = ?",
        (SOAK_LABEL,),
    ).fetchall()
    for row in rows:
        ...
        d = json.loads(blob)
        key = d.get("c1_zone_key")
        if key and isinstance(key, list) and len(key) == 3:
            consumed.add((key[0], key[1], key[2]))
    return consumed
```

[`breakout_paper_soak_B.py:524-526`](breakout_paper_soak_B.py#L524-L526) — main entry:

```python
conn = open_db()
consumed = load_consumed_set(conn)
_log(f"  Restart-safe: loaded {len(consumed)} previously-consumed B C1 zones.")
```

Open positions are loaded fresh **each cycle** (not just at startup) from the DB:

```python
open_rows = list(conn.execute(
    "SELECT id, token, signal, entry_price, sl, tp1, tp2, tp3, "
    " timestamp, expires_at FROM signals "
    "WHERE source = ? AND status = 'OPEN'", (SOAK_LABEL,),
))
```

| Recovery scenario | Behavior |
|---|---|
| Soak restart | Open positions re-loaded from DB; consumed zones reconstructed from prior signals' `c1_zone_key` |
| Crash mid-cycle (before persist) | F4-FIX (commit `68166b2`) — `consumed.add` is AFTER `persist_signal()`, so a crash between detect and persist leaves both consumed and DB clean |
| Crash mid-resolution | Outcome resolution uses single transaction with `conn.commit()` at L370 — atomic write of `results` INSERT + `signals UPDATE` |
| Double-resolve risk | Each cycle's resolve loop only processes `status='OPEN'` rows — a closed signal can't be re-resolved |

**§4 result: PASS.** F4-FIX already addressed the crash-window class. Resolution is atomic.

---

## §5 — Stale-data / clock issues

[`breakout_paper_soak_B.py:269-271`](breakout_paper_soak_B.py#L269-L271) — entry/expiry parse:

```python
entry_dt = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
expiry_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
```

[`breakout_paper_soak_B.py:255, 274`](breakout_paper_soak_B.py#L255):

```python
now_utc = datetime.now(timezone.utc)
...
end_ms = int(min(now_utc, expiry_dt).timestamp() * 1000)
```

[`breakout_paper_soak_B.py:410-414`](breakout_paper_soak_B.py#L410-L414) — staleness gate:

```python
signal_ts = datetime.fromtimestamp(entry_ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None)  # F3-FIX
age_sec = (datetime.now(timezone.utc).replace(tzinfo=None) - signal_ts).total_seconds()
if age_sec > 3600:
    _log(f"  {token}: signal too stale ({age_sec:.0f}s old), skipping")
    return False
```

| Aspect | Behavior |
|---|---|
| Entry/expiry timestamps | tz-aware UTC (F3-FIX applied) |
| `now_utc` for end_ms clamp | tz-aware UTC |
| Signal age calculation | naive-UTC subtraction (both sides naive-UTC) — consistent |
| Heartbeat timestamps | `datetime.now(timezone.utc).strftime(...)` — UTC |
| Persistence (`ts_str`) | `signal_ts.strftime` from UTC-derived naive — UTC |
| Hour/weekday for session tag | `signal_ts.hour` (naive-UTC hour) — correct UTC hour ✓ |

**Clock skew analysis:**
- The VPS clock is NTP-synced (`/etc/systemd/timesyncd.conf` typical Ubuntu default). Skew typically < 100ms.
- Binance kline timestamps come FROM Binance servers (server-authoritative).
- Local clock is only used for "is signal stale?" check and the "now" comparison vs expiry.
- If local clock drifts FAST: stale signals might be falsely rejected (`age_sec` exaggerated). LOW risk — staleness threshold is 1h; clock would have to drift > 1h for this to matter.
- If local clock drifts SLOW: signals barely stale by Binance-time could be wrongly accepted. Same LOW risk.

**§5 result: PASS.** tz-fix consistently applied to all UTC-relevant paths. Clock skew is a theoretical concern only if NTP fails by ≥1h.

---

## §6 — Resolution idempotency

The resolve loop at [`breakout_paper_soak_B.py:241-378`](breakout_paper_soak_B.py#L241-L378):

```python
def resolve_open_signals(conn) -> int:
    open_rows = list(conn.execute(...))   # ← re-queried each cycle
    ...
    for row in open_rows:
        ...
        tp1_hit = tp2_hit = tp3_hit = sl_hit = be_stopped = False   # ← reset each cycle
        last_bar_ts = entry_dt
        for bar in raw:
            ...  # walk
        # classify outcome
        if sl_hit: ...
        elif tp3_hit: ...
        elif be_stopped: ...
        elif now_utc >= expiry_dt: ...
        else:
            continue   # ← non-terminal, stays OPEN
```

| Property | Behavior |
|---|---|
| Per-cycle state reset | Flags initialized fresh at top of each position's walk |
| Bar fetch | Re-done each cycle with explicit `[start_ms, end_ms]` window |
| Same bars input | Same h/l per bar → same flag-trip pattern → same outcome |
| Non-terminal `continue` | Doesn't write to DB; signal stays OPEN unchanged |
| Terminal outcome | Single transaction: INSERT into `results` + UPDATE `signals.status='CLOSED'` |
| Re-evaluation after close | Closed signals don't appear in next cycle's `status='OPEN'` query → not re-walked |

**Idempotency analysis:**
- If cycle N walks position P and concludes "still open", cycle N+1 will re-walk P with possibly MORE bars (time passed). The walk's flag-trip logic is deterministic given the input bar sequence.
- If cycle N concludes "terminal" and writes the close, cycle N+1's query no longer sees P. No double-resolve.
- Edge case: cycle N decides terminal but the commit fails (race / disk error). Status stays OPEN. Cycle N+1 re-walks and re-decides. Decision should be identical (same bars). No drift, no double-write.

**§6 result: PASS.** Fully idempotent.

---

## Findings summary (sorted by severity)

| # | Severity | Section | Finding | Where |
|---|---|---|---|---|
| L1 | LOW | §1 | No explicit minimum 5m bar count check — engine's internal guards cover it | `breakout_paper_soak_B.py:388-392` |
| L2 | LOW | §2 | Bar-gap handling is implicit (index-based walk) — outcome flags survive gaps but `closed_at` precision could be off by a few minutes if gaps exist near close | `breakout_paper_soak_B.py:294-300` |

**No CRITICAL findings. No MEDIUM findings. The single PRIORITY check (§3 — 500-bar vs 576-bar window) is NOT a bug** — resolution uses an independent 1000-bar fetch.

---

## Verdict

**The live resolution loop is operationally sound for the soak's purpose.**

| Area | Verdict |
|---|---|
| §1 Data-fetch failure handling | **PASS** (3 retries + clean skip + per-token isolation) |
| §2 Bar-gap / missing-candle | **PASS** with LOW cosmetic caveat |
| §3 500-bar fetch vs 576-bar window | **PASS** (resolution uses separate 1000-bar windowed fetch) |
| §4 Restart / crash recovery | **PASS** (F4-FIX already addressed; consumed set re-built from DB) |
| §5 Stale-data / clock issues | **PASS** (tz-fix consistently applied; clock skew tolerance ≥ 1h) |
| §6 Resolution idempotency | **PASS** (deterministic + atomic transactions) |

The operational layer is robust:
- 3-retry fetch with backoff prevents transient network errors from corrupting the soak.
- Each token's failures are isolated.
- Resolution uses an explicit-window 1000-bar fetch that comfortably covers the 48h expiry (576 5m bars).
- tz-aware UTC datetime objects propagate consistently (F3 + tz-fix already applied).
- Restart-safety + atomic-resolution writes prevent double-resolve and orphan rows.

**The forward soak's accumulating signal data is operationally trustworthy.** The two LOW findings (no explicit 5m bar count check, implicit bar-gap handling) are quality-of-implementation notes — they don't affect correctness of stored outcomes.

**No code change proposed.** Awaiting operator call.

---

## §7 — Isolation

| Surface | State |
|---|---|
| Fade soak PID 393274 | ALIVE, untouched throughout |
| `data/signals.db` (production) | unchanged (read-only access only) |
| `data/baseline_pin.json` Run-3704 | unchanged |
| Main branch HEAD | `228e04f` (unchanged) |
| Breakout branch HEAD | `1f2f40b` (viewer WR recalibration; not pushed) |
| Soak A 486821 / B 486822 | alive, cycling, untouched throughout this audit |
| All DB backups | intact |

Read-only throughout. No fixes applied. Awaiting operator call.
