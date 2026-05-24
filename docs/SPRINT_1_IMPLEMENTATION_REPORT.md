# Sprint 1 — Phase A Pre-LIVE Hardening — Implementation Report

**Sprint dates:** 2026-05-22
**Lead:** Claude (full autonomous lead per [feedback_enterprise_leadership.md](../../.claude/projects/c--Users-User-Desktop-TradeAI/memory/feedback_enterprise_leadership.md))
**Roadmap reference:** [docs/ENTERPRISE_ROADMAP.md](./ENTERPRISE_ROADMAP.md) Phase A items #2 (dead-man's switch) and #3 (supervisord + atomic state persistence), plus the implicit "backtest checkpointing" companion.

---

## Why this sprint

The Enterprise Roadmap names five Phase A workstreams that must ship **before** flipping `ACTIVE_CONFIG` to `LIVE_CONFIG`. Two of them are pure operational hardening — they don't lift WR, they remove blind spots that turn a single network blip into "I lost five hours of paper trades and didn't know."

Sprint 1 closes the two highest-score operational items:

| Roadmap # | Item | Score | Effort | Risk |
|---|---|---|---|---|
| Phase A #2 | Dead-man's switch + secondary alert channel | 5 | 1 day | 0 |
| Phase A #3 | supervisord + atomic state persistence | 5 | 1 day | 0 |

A third item — backtest checkpointing — was bundled because (a) the atomic-write primitive is identical, (b) every interrupted backtest re-fetches 9 tokens × 3 timeframes × 365 days from Binance, which is wasted operator time, and (c) the same VPN-required environment that breaks the bot also breaks backtests.

---

## What shipped

### 1. Dead-man's switch + secondary alert channel

**Files added**

| File | LOC | Purpose |
|---|---|---|
| `heartbeat.py` | ~280 | Heartbeat-file writer, `MultiChannelAlerter`, SELFTEST scheduler |
| `scripts/watchdog.py` | ~140 | External sidecar that polls the heartbeat file and alerts on staleness |
| `tests/test_heartbeat.py` | ~215 | 18 unit tests |

**Files modified**

| File | Change |
|---|---|
| `crypto_alert.py` | Import `Heartbeat`, `MultiChannelAlerter`; initialise alerter + heartbeat in `main()`; call `_heartbeat.beat(...)` each cycle; route hourly Telegram heartbeat through `MultiChannelAlerter` so SMTP fallback fires on Telegram outage |

**Public surface**

```python
from heartbeat import Heartbeat, MultiChannelAlerter, SmtpAlerter, read_heartbeat, is_stale
```

**Behavior**

1. **Liveness file.** Bot atomically rewrites `data/heartbeat.json` every cycle:
   ```json
   {"ts_unix": 1748541234.5, "ts_utc": "2026-05-22 03:53:54", "pid": 12345,
    "execution_mode": "PAPER", "cycle": 142, "open_signals": 2,
    "threshold_adj": 0, "consecutive_errors": 0}
   ```
2. **External watchdog.** `scripts/watchdog.py` polls the file every 60s. If mtime exceeds `HEARTBEAT_STALENESS_SEC` (default 600s) it alerts on **both** Telegram and SMTP. Re-alerts every `--realert-cooldown` seconds while still down; sends a recovery alert when heartbeat resumes.
3. **Multi-channel alerter.** `MultiChannelAlerter.send(subject, body)` tries Telegram primary; on failure falls back to SMTP. Logs CRITICAL when both fail.
4. **Self-test.** Every Nth beat (default 24 ≈ once/day at 1h cadence) forces delivery on **both** channels with a SELFTEST payload. Counter persisted to `bot_state` so restarts don't skip the cadence. Honors Red Flag #12: *"Dead-man's switch silently failing is worse than no dead-man's switch."*

**SMTP configuration (optional)**

```bat
set SMTP_HOST=smtp.gmail.com
set SMTP_PORT=587
set SMTP_USER=ops@example.com
set SMTP_PASS=app-password
set SMTP_FROM=ops@example.com
set SMTP_TO=ops-alerts@example.com
```
Port 587 → STARTTLS, port 465 → SSL. If any required var is missing, secondary path is disabled (operator gets warning at startup) and Telegram remains primary.

**Failure semantics.** Every save/send path swallows exceptions and logs. Disk-full, SMTP-broken, Telegram-revoked — none of them crash the main loop.

---

### 2. supervisord + atomic state persistence

**Files added**

| File | LOC | Purpose |
|---|---|---|
| `state_store.py` | ~220 | `StateStore` (atomic JSON dict) + `PidFile` (double-start guard) |
| `scripts/supervisord.conf` | ~70 | Linux supervisord program block (bot + watchdog) |
| `scripts/run_supervised.bat` | ~50 | Windows analogue — exponential backoff retry loop, NSSM-ready |
| `scripts/run_watchdog.bat` | ~25 | Windows watchdog wrapper |
| `tests/test_state_store.py` | ~205 | 19 unit tests |

**Files modified**

| File | Change |
|---|---|
| `crypto_alert.py` | Import `StateStore`, `PidFile`; acquire `PidFile` at startup (refuses double-start); load persisted counters at `main()` entry; save snapshot at end of each cycle |

**Public surface**

```python
from state_store import StateStore, PidFile
```

**Behavior**

1. **Atomic writes.** `StateStore.save(state)` writes to a `.tmp` file, `fsync`s, then `os.replace`s into place. A crash mid-write never leaves a half-written state file. Previous good copy is preserved as `.bak`.
2. **Corruption recovery.** `StateStore.load()` tries primary, falls back to `.bak`, finally returns supplied defaults. Tested against malformed JSON, non-dict payloads, simulated disk errors.
3. **Transactional API.** `with store.transaction(defaults={...}) as state:` saves on exit, even on exception.
4. **Non-JSON safety.** Non-serialisable values (sets, objects) are dropped with a warning rather than crashing the save.
5. **PidFile guard.** On startup, refuses if another bot PID is alive (uses `os.kill(pid, 0)` probe). Supervisord auto-restart races make this real — without it, two bots could update the same DB concurrently and corrupt OGD state. Stale pid files (process gone) are silently reclaimed. `release()` is race-safe: only deletes the file if the recorded PID still matches our own.

**What gets persisted to `data/process_state.json`**

```json
{
    "cycle": 142,
    "consecutive_errors": 0,
    "last_heartbeat_ts": 1748541200.0,
    "last_cycle_ts_unix": 1748541234.5,
    "restart_count": 3,
    "_saved_at": 1748541234.6
}
```

Restart resumes the cycle counter, error counter, and heartbeat timestamp — operators are not double-paged on restart, error-count alerting works across crashes, and the heartbeat cadence stays coherent.

**Supervisord (Linux)**

```ini
[program:tradeai_bot]
command=/usr/bin/env python3 -u crypto_alert.py
autorestart=true
startretries=999
user=tradeai
; ... log rotation, env, etc.

[program:tradeai_watchdog]
command=/usr/bin/env python3 -u scripts/watchdog.py --interval 60 --staleness 600
autorestart=true
; ...
```

Install:
```bash
sudo cp scripts/supervisord.conf /etc/supervisor/conf.d/tradeai.conf
sudo supervisorctl reread && sudo supervisorctl update
sudo supervisorctl start tradeai:*
```

**Windows analogue**

```cmd
nssm install TradeAI "C:\Users\User\Desktop\TradeAI\scripts\run_supervised.bat"
nssm set TradeAI AppDirectory "C:\Users\User\Desktop\TradeAI"
nssm start TradeAI

nssm install TradeAIWatchdog "C:\Users\User\Desktop\TradeAI\scripts\run_watchdog.bat"
nssm set TradeAIWatchdog AppDirectory "C:\Users\User\Desktop\TradeAI"
nssm start TradeAIWatchdog
```

`run_supervised.bat` retries with exponential backoff (5s → 10s → 20s → … capped at 300s). Clean exit (`code 0`, e.g. operator Ctrl+C) stops the loop.

---

### 3. Backtest checkpointing

**Files added**

| File | LOC | Purpose |
|---|---|---|
| `backtest_checkpoint.py` | ~155 | Checkpoint reader/writer with SHA-256 config-hash invalidation |
| `tests/test_backtest_checkpoint.py` | ~180 | 18 unit tests |

**Files modified**

| File | Change |
|---|---|
| `backtest.py` | Import checkpoint helpers + `argparse`; new `_compute_run_config_hash()` over every signal-affecting parameter; new `_parse_args()` for `--no-resume` / `--clear-checkpoint`; main loop skips tokens already in checkpoint; save after each token completes; clear after full pipeline succeeds |

**Behavior**

1. After every token completes, `save_checkpoint()` writes:
   ```json
   {
       "schema_version": 1,
       "config_hash": "7ac4d3809e288e23...",
       "started_at": "2026-05-22T03:00:00Z",
       "saved_at":   "2026-05-22T03:04:12Z",
       "completed_tokens": ["BTC", "ETH"],
       "signal_count": 8,
       "all_signals": [ ... ]
   }
   ```
2. On startup, `load_checkpoint(expected_hash)` returns the checkpoint **only** if `config_hash` matches. Any change to `ACTIVE_CONFIG`, `BACKTEST_DAYS`, `ENTRY_WINDOW`, `COOLDOWN_BARS`, `ICT_*` params, fees, or `BINANCE_TOKENS` invalidates the checkpoint. This is the single biggest safety property: two different parameter sweeps cannot silently share signals.
3. Resume refetches BTC reference candles (one extra fetch, ~30s) so downstream tokens still have BTC data for SMT divergence detection. Skipping this would require either resimulating BTC (wasteful) or persisting raw OHLCV (large + fragile).
4. After the full pipeline finishes (report + walk-forward + template comparison + DB save + OGD bootstrap), the checkpoint file is cleared. If any of those steps raise, the checkpoint stays in place for the next run.
5. CLI:
   ```bash
   python backtest.py                       # auto-resume if checkpoint matches
   python backtest.py --no-resume           # ignore existing checkpoint, start fresh
   python backtest.py --clear-checkpoint    # delete checkpoint file and exit
   ```

**What parameters are in the hash**

```python
ACTIVE_CONFIG, BINANCE_TOKENS, BACKTEST_DAYS, WARMUP_BARS, FORWARD_BARS,
REGIME_WINDOW, COOLDOWN_BARS, ENTRY_WINDOW, ICT_SWING_N, ICT_SWEEP_LOOKBACK,
ICT_DISP_MAX_LOOK, ICT_MSS_HORIZON, ICT_FVG_MIN_GAP, ICT_MAX_SETUP_AGE_BARS,
ICT_MSS_DISP_MAX_GAP, ENTRY_REACTION_LOOKBACK, ROUND_TRIP_COST_PCT,
FEE_PCT, SLIPPAGE_PCT, STRATEGY_VERSION
```

If a new signal-affecting parameter is added, append it to `_compute_run_config_hash()` so old checkpoints invalidate.

---

## Test results

| Suite | New | Pre-existing | Total | Result |
|---|---|---|---|---|
| `test_heartbeat.py` | 18 | — | 18 | 18/18 pass |
| `test_state_store.py` | 19 | — | 19 | 19/19 pass |
| `test_backtest_checkpoint.py` | 18 | — | 18 | 18/18 pass |
| `test_tunebot.py` | — | 31 | 31 | 31/31 pass |
| `test_adaptive_snapshot.py` | — | 6 | 6 | 6/6 pass |
| `test_phase2_data.py` | — | 25 | 25 | 25/25 pass |
| **Total (ex. tracker)** | **55** | **62** | **117** | **117/117 pass** |

`test_tracker_db_alignment.py` (100 tests) is excluded from the regression gate per existing convention.

**Regression check:** `python -c "import crypto_alert"` and `python -c "import backtest"` both succeed cleanly. `python backtest.py --help` works. The config hash computes deterministically against the real `ACTIVE_CONFIG`.

---

## Operator runbook (post-sprint)

### First-time deployment (Linux)

```bash
sudo apt install supervisor
sudo useradd -r tradeai
sudo mkdir -p /opt/tradeai /var/log/tradeai
sudo cp -r . /opt/tradeai/
sudo chown -R tradeai:tradeai /opt/tradeai /var/log/tradeai

# Set env vars in /etc/default/tradeai (TELEGRAM_TOKEN, CHAT_ID, etc.)
sudo cp scripts/supervisord.conf /etc/supervisor/conf.d/tradeai.conf
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start tradeai:*
```

### First-time deployment (Windows)

```cmd
REM Install NSSM from https://nssm.cc
nssm install TradeAI "C:\Users\User\Desktop\TradeAI\scripts\run_supervised.bat"
nssm set TradeAI AppDirectory "C:\Users\User\Desktop\TradeAI"
nssm install TradeAIWatchdog "C:\Users\User\Desktop\TradeAI\scripts\run_watchdog.bat"
nssm set TradeAIWatchdog AppDirectory "C:\Users\User\Desktop\TradeAI"
nssm start TradeAI
nssm start TradeAIWatchdog
```

### Manual run (development)

```cmd
REM Terminal 1
python crypto_alert.py

REM Terminal 2
python scripts\watchdog.py --interval 60 --staleness 600
```

### Verifying the dead-man's switch works

```cmd
REM In one terminal:
python crypto_alert.py

REM In another, after the bot has written its first heartbeat:
type data\heartbeat.json

REM Kill the bot:
taskkill /F /IM python.exe

REM Wait HEARTBEAT_STALENESS_SEC + a bit. The watchdog should fire a
REM Telegram + SMTP alert. After restarting the bot, you should also
REM get a "Bot RECOVERED" alert.
```

### Verifying the SELFTEST works

Set `HEARTBEAT_SELFTEST_EVERY=2` in env, restart the bot. After the second cycle (~2× CHECK_INTERVAL), you should receive a `[SELFTEST]` message on both Telegram and (if configured) SMTP. After verifying delivery, unset the var and restart.

### Resuming an interrupted backtest

```bash
# Backtest crashed mid-token? Just re-run:
python backtest.py
# It will detect data/backtest_checkpoint.json and skip completed tokens.

# Discard the checkpoint:
python backtest.py --no-resume

# Or delete it explicitly:
python backtest.py --clear-checkpoint
```

---

## What this sprint does NOT close

Items still on the Phase A queue (in roadmap order):

- **Triple-barrier labeling (mlfinlab)** — Roadmap Item #1, score 5. Recommended Single Next Action. Zero overfit risk. Hard prerequisite for CPCV, DSR, meta-labeling, Monte Carlo CI.
- **CI/CD backtest regression gate** — Roadmap Item #4. Prevents Run-46-class regressions from merging. No new external deps.
- **mlfinlab CPCV + DSR** — Roadmap Item #5. Blocks on triple-barrier labels.
- **News/macro blocklist + dotenv-vault** — Phase A items #4/#5. Pure additive, config-flagged.
- **smart-money-concepts oracle sweep** — Roadmap Item #10. Adds as `tests/` dependency only.
- **Monte Carlo bootstrap CIs** — Section 2 Triage Table. 50 lines NumPy.
- **Weight-degeneration monitoring suite** — Roadmap Item #9. Detects the Run-46 failure mode before it kills future runs.

The roadmap's recommended next item is **Triple-barrier labeling** — see `docs/ENTERPRISE_ROADMAP.md` Section 7.

---

## Change log

| Date | Change | Editor |
|---|---|---|
| 2026-05-22 | Sprint 1 shipped — heartbeat.py, state_store.py, backtest_checkpoint.py + 55 new tests. Roadmap Phase A items #2 and #3 closed. | Claude (lead) |
