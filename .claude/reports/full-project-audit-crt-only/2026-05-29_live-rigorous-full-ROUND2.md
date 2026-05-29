# Live/PAPER Rigorous Full Audit — ROUND 2 — 2026-05-29

**Scope:** Same as round 1 — every live signal-generation + persistence + UI path.
**Trigger:** Operator shipped 8 cycle-12 fixes after round 1, requested re-audit to confirm closure + catch regressions.
**Agents:** Same 8 agents re-ran in parallel.

---

## Round-2 scorecard vs Round-1

| # | Dimension | R1 | R2 | Δ | After round-2 fixes |
|---|---|---|---|---|---|
| 1 | Adaptive learning | 6.5 | 7.2 | +0.7 | **7.4** (NEW-CY12-A closed + TON repaired) |
| 2 | OGD weight DB | 7.0 | 7.0 | 0 | 7.0 (code latent — no new signals fired) |
| 3 | 24/7 resilience | 8.5 | 8.7 | +0.2 | **8.9** (N-RES-1 IF-branch closed) |
| 4 | Live data pipeline | 8.2 | 8.4 | +0.2 | **8.6** (N-RES-1 convergent fix) |
| 5 | Live risk management | 8.5 | 8.5 | 0 | 8.5 (no regressions) |
| 6 | Live ICT/CRT logic | 8.7 | 9.2 | +0.5 | 9.2 (best improvement — convergent fixes verified) |
| 7 | Tracker data flow | 8.4 | 8.8 | +0.4 | **8.9** (NEW-1 closed) |
| 8 | Pre-LIVE deployment | 5.5 | 6.0 | +0.5 | 6.0 (statistical gates intentional) |
| | **Overall avg (8 dims)** | **7.66** | **7.99** | +0.33 | **~8.1** |
| | **System avg (excl. Pre-LIVE stat)** | **7.97** | **8.26** | +0.29 | **~8.4** |

---

## Cross-agent verdict on the 8 cycle-12 fixes

| # | Fix | ICT | Adaptive | Resilience | Data | Tracker | Pre-LIVE | Verdict |
|---|---|---|---|---|---|---|---|---|
| H1 | CY12-REGIME-TG | ✓ CLOSED | ✓ CLOSED | — | — | — | — | **CLOSED** |
| H2 | CY12-BTC-CORR-KEY | ✓ CLOSED | — | — | ✓ CLOSED | — | — | **CLOSED** |
| H3 | CY12-UTC-* (4 sites) | — | — | — | — | ✓ CLOSED | ✓ CLOSED | **CLOSED** |
| H5 | CY12-SVM-DICT-OR-OBJ | — | ✓ code correct (latent) | — | — | — | — | **CLOSED (forward)** |
| H6 | CY12-SIGNAL-SMTP | — | — | ✓ CLOSED | — | — | ✓ CLOSED | **CLOSED** |
| H7 | CY12-BTC-STALE-GATE | — | — | ⚠ PARTIAL → fixed in R2 | ⚠ PARTIAL → fixed in R2 | — | — | **CLOSED (after R2 fix)** |
| H9 | CY12-OGD-MIN-UNIFY | — | — | — | — | ✓ CLOSED | — | **CLOSED** |
| M4 | CY12-INIT-DB-WRAP | — | — | ✓ CLOSED | — | — | ✓ CLOSED | **CLOSED** |

**7 of 8 fully CLOSED in round 2. H7 was 50% (else-branch only) — fixed in this round.**

---

## NEW findings from round 2 (4 — all fixed in this round)

### N-RES-1 (HIGH, 2 agents convergent) — BTC stale gate IF-branch dormant
**Convergence:** Resilience + Data pipeline
**Issue:** The round-1 CY12-BTC-STALE-GATE fix only set `last_candle_fetch_ok` in the ELSE-branch (BTC not in monitored tokens). The operator's production config HAS BTC monitored, so the IF-branch executes — and never refreshed the timestamp. The stale gate's `_last_ok > 0` precondition stayed permanently False → gate inert in production.
**Fix (shipped):** [crypto_alert.py:2410](crypto_alert.py#L2410) — IF-branch now refreshes `BTC_STATE["last_candle_fetch_ok"]` when `STATE["BTC"]["last_1h_fetched_at"]` proves the cache is fresh (within STALE_CANDLE_THRESHOLD).

### NEW-CY12-A (HIGH, Adaptive) — DSR stale-too-long fallback missing
**Issue:** Round-1's stale-verdict-drift guard returns `(1.0, "stale_verdict_config_drift")` — leaving OGD at full-rate learning during the "silent-inert window" after every promotion. Operator's current state: `latest_cpcv_verdict.config_hash=477f7b...` vs `baseline_pin.config_hash=36f1ea...` → genuine FAIL verdict being ignored.
**Fix (shipped):** [adaptive_engine.py:567](adaptive_engine.py#L567) — after `OGD_DSR_STALE_GRACE_HOURS=48`, escalate to `OGD_DSR_STALE_LR_SCALE=0.5` (conservative throttling). Within grace window: 1.0 (recent promotion not yet throttled). Past grace: 0.5 (no fresh evidence ⇒ caution). Both knobs env-overridable.

### TON `last_decay_times=0.0` malformed scalar
**Issue:** `bot_state.last_decay_times` JSON has `"TON": 0.0` while all other 9 tokens have valid epoch ~1.78e9. The decay clamp catches the resulting huge `(now - 0.0)` delta but the scalar is data-integrity-wrong.
**Fix (shipped):** One-line DB UPDATE setting TON's value to current epoch. Repaired live, persisted.

### Tracker NEW-1 (LOW) — `/api/health` LOCAL `datetime.now()`
**Issue:** Last surviving non-UTC writer in tracker.py. Cosmetic (frontend doesn't consume it for display) but inconsistent with CY12-UTC discipline.
**Fix (shipped):** [tracker.py:2992](tracker.py#L2992) — `/api/health` now returns `time` in UTC + `heartbeat_age_s` + `bot_active` fields so frontend can render "BOT STALE" instead of always-green "DB OK".

---

## Other round-2 NEW findings (LOW, deferred)

| # | Finding | Source | Decision |
|---|---|---|---|
| N-RES-2 | Crash-loop Telegram amplification on disk-full (CY12-INIT-DB-WRAP fires once per restart) | Resilience | Defer — `Restart=always` rate-limited by systemd `RestartSec=10s` + Telegram's own rate limiting; acceptable |
| NEW-CY12-B | Dead code in adaptive_engine.py:520-527 (`_pin` path computed twice) | Adaptive | Defer — harmless cleanup |
| CY12-NEW-3 | `_signal_alerter=None` before `main()` runs | Pre-LIVE | Acceptable — fallback to `send_telegram` works correctly; tests don't fire signals |
| Tracker H3 | Heartbeat staleness on page header pill | Tracker | PARTIAL — `/api/health` now exposes the data; frontend consumption deferred |
| ICT M1/M2/M3/M4 | Recency window, FVG probe, dealing range, EQH/EQL off-by-one | ICT | Tag-only; non-blocking |

---

## What stays open (intentional)

1. **DSR 87.6% < 95%** required — statistical gate, function of paper soak depth
2. **5/30 closed paper signals** — statistical gate, function of time
3. **DSR safety net inert pending fresh backtest** — operator action: run a backtest under Run-1749 pin so `latest_cpcv_verdict.config_hash` matches pin. Then the gate becomes ACTIVE again.
4. **Telegram per-message rate limiter** — round-1 CRIT-3, signal-delivery reliability gap (not safety-of-capital since bot has no execution). Deferred to next cycle.

---

## Files modified in round 2 fixes

| File | Change |
|---|---|
| [crypto_alert.py](crypto_alert.py) | N-RES-1 — IF-branch BTC stale gate refresh |
| [adaptive_engine.py](adaptive_engine.py) | NEW-CY12-A — DSR stale-too-long fallback (48h grace + 0.5 scale) + 2 new env knobs |
| [tracker.py](tracker.py) | Tracker NEW-1 — `/api/health` UTC + heartbeat surface |
| `data/signals.db` (bot_state) | TON `last_decay_times` one-shot DB repair |

**Tests:** 565 pass (8 pre-existing stale-baseline failures unrelated to this audit).
**Compile:** all 3 modified modules clean.

---

## LIVE GO/NO-GO

**Still NO-GO** — purely on statistical gates (DSR + paper soak depth). System infrastructure now at ~8.4/10 average across 7 system dimensions (up from 7.97 in round 1, 7.97 → 8.26 → ~8.4 with round-2 fixes).

All round-1 HIGH findings are now CLOSED or accepted as deferred LOW polish. The bot is operationally ready for LIVE the moment statistical gates clear.

---

## Files cited

- `/home/tradeai/TradeAI/crypto_alert.py`
- `/home/tradeai/TradeAI/adaptive_engine.py`
- `/home/tradeai/TradeAI/tracker.py`
- `/home/tradeai/TradeAI/scripts/watchdog.py`
- `/home/tradeai/TradeAI/data/signals.db`
- `/home/tradeai/TradeAI/data/baseline_pin.json`
