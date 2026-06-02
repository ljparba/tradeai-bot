# Breakout Soak Viewer

A small read-only dashboard so you can watch `data/breakout.db` accumulate
closed paper-soak signals toward the locked ≥ 30 gate, without touching either
running soak.

> **Read-only.** This viewer NEVER writes to any database. NEVER signals the
> soak. NEVER blends with the fade tracker. NEVER auto-opens — you launch it
> manually when you want to look, and kill it when you're done.

---

## What it shows

| Section | What's there |
|---|---|
| **Gate progress** | Count of CLOSED soak signals vs the 30 target + progress % |
| **Locked thresholds** | avg_R ≥ +0.40, PF ≥ 2.0, WR ≥ 55%, max DD ≤ 20 R, no per-token blowup — each with PASS / FAIL / **PENDING** marker (PENDING until n ≥ 30; no early verdict) |
| **Verdict overall** | PENDING / PASS / FAIL across the gate as a whole |
| **Soak health** | Heartbeat timestamp + age (OK / STALE / NO_HEARTBEAT), PID, current cycle, last signal ts |
| **n-vs-expectancy drift** | Cumulative avg_R as n grows — so you can see if edge holds, strengthens, or converges to break-even |
| **Per-token** | n, WR, avg_R, sum_R, PF per token; ⚠ BLOWUP flag fires when WR ≤ 35% AND avg_R < 0 over ≥ 5 signals |
| **Open positions** | Currently-live soak positions — id, token, dir, entry, SL, TPs, age in minutes |
| **Closed (most recent 25)** | Per-signal outcome, R, profit %, open/close timestamps |

Auto-refresh every 30 seconds on the client side. Ctrl+Shift+R for manual.

---

## Run it

### Foreground (recommended for ad-hoc monitoring)

```bash
cd /home/tradeai/breakout-work
python3 breakout_viewer.py
# → "Breakout viewer starting on http://127.0.0.1:8890"
# Ctrl+C to stop.
```

### Detached (survives SSH disconnect)

```bash
cd /home/tradeai/breakout-work
nohup python3 breakout_viewer.py > logs/breakout_viewer.log 2>&1 &
echo $! > /tmp/breakout_viewer.pid  # optional helper

# Stop:
kill "$(cat /tmp/breakout_viewer.pid)"
# or:
pkill -f "python3 breakout_viewer.py"
```

---

## Access via SSH tunnel (typical operator setup)

Add this to `~/.ssh/config` on your local PC (the same way you already do for
the fade tracker on 8888):

```sshconfig
Host tradeai-vps
    LocalForward 8890 127.0.0.1:8890
```

Then on your local PC, point a browser at `http://localhost:8890`.

The viewer binds **only to 127.0.0.1** on the VPS — it's not reachable from
the public internet.

---

## Port & process inventory (so it's clear what runs where)

| Service | Port | PID location | Notes |
|---|---|---|---|
| Fade tracker | 8888 | (systemd-managed) | `/home/tradeai/TradeAI/tracker.py`, dashboard for the FADE soak |
| **Breakout viewer** | **8890** | None — you control launch | this README's tool |
| Fade soak | n/a | `/home/tradeai/TradeAI/data/tradeai.pid` | fade strategy bot |
| Breakout soak | n/a | `/home/tradeai/breakout-work/data/breakout_soak.pid` | breakout strategy bot |

---

## Read-only verification (how the viewer is *forced* read-only)

In code at `breakout_viewer.py:_open_ro_conn()`:

```python
conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=2.0)
```

The `mode=ro` URI parameter is enforced at the SQLite C level. Any attempt to
issue `INSERT/UPDATE/DELETE/CREATE` via this connection raises
`sqlite3.OperationalError: attempt to write a readonly database` — there is no
code path that even tries. Fresh connection per HTTP request, closed in the
`finally` block. The soak's WAL writer is never blocked.

HTTP-level write methods are also blocked:

| Method | Response |
|---|---|
| GET | 200 (page or JSON) |
| POST | **405** |
| PUT | **405** |
| DELETE | **405** |
| PATCH | **405** |

---

## API contract (for direct curl / scripting)

| Endpoint | Returns |
|---|---|
| `GET /` | HTML dashboard |
| `GET /api/state` | JSON snapshot — see below |
| anything else | 404 |

### `GET /api/state` JSON shape (key fields)

```jsonc
{
  "ts_utc":          "2026-06-02 02:00:00",
  "soak_label":      "H4_BREAKOUT_PAPER_SOAK",
  "gate":            { "n_target": 30, "avg_R_min": 0.40, ... },
  "metrics":         { "n_closed": 0, "n_open": 0, "avg_R": 0.0, "profit_factor": 0.0,
                       "win_rate": 0.0, "max_drawdown_R": 0.0, "progress_pct": 0.0 },
  "gate_eval":       { "avg_R":    { "value": 0.0, "threshold": 0.40, "status": "PENDING" },
                       "profit_factor": { ... },
                       "win_rate": { ... },
                       "max_drawdown": { ... },
                       "blowup":   { ... } },
  "verdict_overall": "PENDING",       // PENDING / PASS / FAIL
  "soak_health":     { "heartbeat_age_s": 69.4, "pid": 458923, "cycle": 8,
                       "status": "OK" },
  "per_token":       [ { "token": "BCH", "n": 0, "wr": 0.0, ... }, ... ],
  "drift":           [ { "n": 1, "cum_R": -0.50, "cum_avg_R": -0.5 }, ... ],
  "open":            [ ... ],
  "closed":          [ ... ]
}
```

---

## Isolation invariants (no exceptions)

1. **No writes anywhere.** Verified via `mode=ro` URI + HTTP write methods blocked.
2. **Doesn't touch the running soak process** — no signals sent to PID 458923.
3. **Doesn't open** `data/signals.db` (the fade soak's DB).
4. **No autostart.** Not in systemd, not in cron, not in the soak's process.
5. **No external network.** No telemetry, no Telegram, no fetches.
6. **Doesn't share port** with the fade tracker (8888 vs 8890).
7. **Filters by source** = 'H4_BREAKOUT_PAPER_SOAK' so backtest grid + friction
   rows (which live in `backtest_signals` anyway, but defense-in-depth) never
   show up.

---

## What the viewer does NOT do

- ❌ Edit any config or signal.
- ❌ Start, stop, or restart the soak.
- ❌ Push to GitHub.
- ❌ Flip `EXECUTION_MODE`.
- ❌ Write any kind of state file (no cookies, no session, no cache files).
- ❌ Show fade-soak signals.
- ❌ Blend the two soaks.
