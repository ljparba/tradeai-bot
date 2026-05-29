# Live/PAPER Rigorous Full Audit — 2026-05-29

**Scope:** Every live signal-generation + persistence + UI path. EXPLICITLY EXCLUDES backtest.py + explorer.
**Agents:** 8 parallel — adaptive-learning-code-reviewer, ogd-weight-inspector, crash-recovery-auditor, data-pipeline-validator, risk-management-auditor, ict-logic-validator, live-deployment-readiness-checker, general-purpose (tracker E2E)

---

## Aggregate scorecard

| # | Dimension | Score | Top finding |
|---|---|---|---|
| 1 | Adaptive learning (live OGD flow) | **6.5/10** | All 5 historical CRT signals stored regime=UNKNOWN; DSR safety net silently inert due to stale config_hash |
| 2 | OGD weight DB state | **7.0/10** | `signal_variant_matches` empty (0 rows) — Phase 5B blocked; TON `last_decay_times` malformed (=0.0) |
| 3 | 24/7 resilience | **8.5/10** | Signal-send bypasses SMTP fallback; BTC feed silent-stale window; init_db has no boot-fail alert |
| 4 | Live data pipeline | **8.2/10** | BTC correlation overlay silently non-functional in live CRT (key mismatch) |
| 5 | Live risk management | **8.5/10** | All critical prior fixes verified intact; minor consumed-zone ordering inefficiency |
| 6 | Live ICT/CRT logic | **8.7/10** | Telegram regime payload still hardcoded UNKNOWN (CY12-REGIME fix half-landed) |
| 7 | Tracker data flow (live) | **8.4/10** | `manual_close_signal()` uses LOCAL VPS time (+8h SGT drift); dual `_OGD_MIN` inconsistency |
| 8 | Pre-LIVE deployment readiness | **5.5/10** | NO-GO (DSR 87.6%<95%; 5/30 paper closed; no runbook) |
| | **Overall (system avg excl. statistical gates)** | **8.1/10** | Solid live system; 4 cross-agent convergent HIGH items to patch |

---

## Cross-agent convergent findings (CRITICAL signal)

Where multiple agents independently identified the same root cause:

### CONV-1: CY12-REGIME fix shipped INCOMPLETELY
**Convergence:** ICT (HIGH-1) + Adaptive (CRITICAL-1) + Tracker (verified)
- DB saves real regime via `_crt_regime_payload` (today's earlier fix landed)
- **Telegram alert call at `crypto_alert.py:4786`** still passes `{"regime": "UNKNOWN"}` hardcoded
- Historical 5 LIVE CRT signals + 12 weight_history rows all have `regime=UNKNOWN` (forensic queries dead)
- **Fix:** 1-line edit at the Telegram call site to use `_crt_regime_payload`. ~10 min.

### CONV-2: BTC correlation overlay silently broken in live CRT
**Convergence:** Data pipeline (HIGH) + ICT (cross-domain observation)
- `crypto_alert.py:4589` passes `btc_c5m` keyed `"timestamps"`; guard at `crypto_alert.py:1143` requires `"times"` → always falsy → T1.3 feature inert in live
- Zero impact today at `BTC_CORR_BONUS_PCT=0.0` BUT explorer can tune it non-zero, creating live↔BT parity gap that would invalidate promoted baselines
- **Fix:** Add `"times"` key to btc_c5m dict before passing into scan_h4_crt_for_token. ~2 lines.

### CONV-3: UTC timezone drift in multiple Telegram/UI paths
**Convergence:** Tracker (HIGH-1) + Pre-LIVE (MED-1/2/3)
- `tracker.py:2273` `manual_close_signal()` uses local `datetime.now()` (SGT = +8h)
- `crypto_alert.py:4420` heartbeat Telegram message (local time)
- `crypto_alert.py:4860` SIGTERM shutdown message (local time)
- `scripts/watchdog.py:118` "Watchdog ACTIVE" timestamp (local time)
- **Fix:** Replace `datetime.now()` with `datetime.now(timezone.utc)` at 4 sites. ~15 min.

### CONV-4: signal_variant_matches table empty
**Convergence:** OGD (H1) + Adaptive (M2)
- 0 rows despite 5 closed CRT signals — Phase 5B per-template OGD has zero learning substrate
- Signal-emit pipeline silently skipping per-template scoring write
- **Fix:** Add emit-time INSERT in `crypto_alert.py` CRT signal save path. ~20 min.

---

## CRITICAL findings (LIVE flip blockers — intentional)

### CRIT-1: Statistical LIVE gates fail (by-design)
- **DSR 87.6% < 95%** required gate
- **5/30 closed paper signals**
- Intentional system behavior — NOT bugs. Continue PAPER soak.

---

## HIGH findings (10)

| # | Finding | Source | Effort | File:line |
|---|---|---|---|---|
| H1 | Telegram alert hardcoded `regime=UNKNOWN` despite DB fix | ICT | 1 line | `crypto_alert.py:4786` |
| H2 | BTC correlation overlay inert in live CRT (key mismatch) | Data | 2 lines | `crypto_alert.py:4589` + `:1143` |
| H3 | `manual_close_signal()` uses LOCAL time (+8h SGT) | Tracker | 1 line | `tracker.py:2273` |
| H4 | DSR safety net silently inert (stale config_hash) | Adaptive | re-run backtest | `bot_state.latest_cpcv_verdict` |
| H5 | `signal_variant_matches` empty — Phase 5B blocked | OGD | ~20 LoC | `crypto_alert.py` save path |
| H6 | Signal-send bypasses SMTP fallback | Resilience | ~5 LoC | `crypto_alert.py:4451` |
| H7 | BTC feed stale-but-cached silent-degradation | Resilience | ~10 LoC | `crypto_alert.py:2380` |
| H8 | `consecutive_fail_max=500` in explorer (already fixed) | — | DONE | — |
| H9 | Dual `_OGD_MIN` (30 vs 10) blend_pct drift | Tracker | 1 line | `tracker.py:786,884` |
| H10 | Secret rotation + LIVE→PAPER rollback undocumented | Pre-LIVE | docs | `docs/RUNBOOK.md` |

---

## MEDIUM findings (selected — 11)

| # | Finding | Source |
|---|---|---|
| M1 | TON `last_decay_times["TON"]=0.0` malformed scalar | OGD |
| M2 | Warm-start carries backtest velocity into live (HBAR/POL drift w/o live closes) | Adaptive |
| M3 | `learning_freeze_state.active_triggers` stale `weight_volatility_spike(ADA)` | Adaptive |
| M4 | `init_db()` failure has no Telegram alert → silent restart-loop | Resilience |
| M5 | `consumed_h4_crt` set unbounded growth over long uptime | Resilience |
| M6 | CRT consumed-zone written BEFORE kill-switch check | Risk |
| M7 | `score_ict_mss` recency window (ICT_SWEEP_LOOKBACK=20) too narrow for CRT's 4h C2 | ICT |
| M8 | EQH/EQL `_cluster_size_near` off-by-one inflates cluster tags | ICT |
| M9 | Reports tab per-token + monthly WR formula collapses PARTIAL into losses | Tracker |
| M10 | Heartbeat staleness NOT surfaced on tracker page header | Tracker |
| M11 | CRT_FORWARD_BARS=864 makes H4_CRT_MITIGATION_TTL_H ≤72h structurally inert | Multi |

---

## LOW findings (15 — non-blocking polish)

Telegram per-message rate limiter missing; `data/bot.log` not in logrotate scope; CoinGecko single-attempt no-retry; ICT_MIN_RR_GATE double-check on 5M_SWEEP; dr_location floor-pin universality (by design); Wyckoff TRANSITION fail-open pollutes OGD slice; watchdog self-heartbeat has no external monitor; `cross_config_sr_trial_std=0.1211 n=5` under-pooled; Retry-After cap asymmetry (spot 30s vs fapi 60s); `print()` vs `logger.*` inconsistency; sample-size noise floor at n<50 CPCV; `fetch_binance_price` no 418/429 special-case; c2_time docstring drift (fixed today); per-call `ts_keys` rebuild in funding cache; SIGKILL bypasses atexit pidfile cleanup (acceptable per state_store reclaim).

---

## Recommended priority action list

### Ship now (~1 hour total) — closes 4 cross-agent convergent findings
1. **H1** — Pass `_crt_regime_payload` to `send_signal_msg` at `crypto_alert.py:4786`
2. **H2** — Add `"times"` key to btc_c5m dict before passing to scan_h4_crt_for_token at `crypto_alert.py:4589`
3. **H3** — Replace `datetime.now()` → `datetime.now(timezone.utc)` at `tracker.py:2273` + 3 Telegram message sites
4. **H9** — Unify `_OGD_MIN` constant between Intelligence + Adaptive panels

### Ship this week (~3 hours total)
5. **H5** — Wire emit-time INSERT for `signal_variant_matches` in CRT save path
6. **H6** — Route `send_signal_msg` through MultiChannelAlerter
7. **H7** — Add `last_btc_candle_fetch_ok_ts` + 10-min staleness gate to `fetch_btc_state`
8. **M4** — Wrap `init_db()` in try/except with Telegram emergency send

### Strategic / before LIVE flip
9. **H4** — Run a backtest under Run-1749 pin so `latest_cpcv_verdict.config_hash` matches → reactivates DSR soft-LR + 24h freeze safety nets
10. **H10** — Document `docs/RUNBOOK.md`: secret rotation, LIVE→PAPER rollback
11. **Statistical gates** — Continue PAPER soak to ≥30 closed CRT signals AND find configs with DSR ≥95%

---

## LIVE GO/NO-GO verdict

**NO-GO.** Continue PAPER soak.

Statistical gates dominate the verdict:
- DSR 87.6% < 95% required
- 5/30 closed paper signals (need 25 more)

System infrastructure is sound (~8.1/10 across the 7 system dimensions):
- 4 cross-agent convergent HIGH items (CONV-1 through CONV-4) all 1-line to ~20 LoC fixes
- No CRITICAL bugs in live signal path
- All prior-cycle fixes (C6/C7/C8/H14/M17/M18) verified still in place
- 24/7 resilience strong (8.5/10) — Sprint 1 components (heartbeat/watchdog/state_store/PidFile) verified wired

---

## Files cited (absolute paths)

- `/home/tradeai/TradeAI/crypto_alert.py`
- `/home/tradeai/TradeAI/crt_engine.py`
- `/home/tradeai/TradeAI/ict_engine.py`
- `/home/tradeai/TradeAI/adaptive_engine.py`
- `/home/tradeai/TradeAI/strategy_engine.py`
- `/home/tradeai/TradeAI/tracker.py`
- `/home/tradeai/TradeAI/tracker_html.py`
- `/home/tradeai/TradeAI/monitoring.py`
- `/home/tradeai/TradeAI/heartbeat.py`
- `/home/tradeai/TradeAI/funding_rate_client.py`
- `/home/tradeai/TradeAI/btc_correlation.py`
- `/home/tradeai/TradeAI/state_store.py`
- `/home/tradeai/TradeAI/config.py`
- `/home/tradeai/TradeAI/scripts/watchdog.py`
- `/home/tradeai/TradeAI/data/signals.db`
- `/home/tradeai/TradeAI/data/baseline_pin.json`
