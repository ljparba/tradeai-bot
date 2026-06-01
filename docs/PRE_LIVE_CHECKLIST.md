# TradeAI Pre-LIVE Checklist + Final Audit Scorecard

> **Purpose.** This is your canonical pre-LIVE deployment reference. Bring it back up whenever you're considering the PAPER → LIVE switch. Don't lose it.
>
> **Generated.** 2026-05-31, at the end of the autonomous audit/fix/hardening loop (cycles 1-4). Loop stopped per spec when cycle #4 produced 0 new CRITICAL/HIGH findings.
>
> **Active pin at generation time.** Run-3704 (config_hash `3ee13531421d7ba5...`). Bot on PID 393274, healthy, 12 tokens, PAPER mode.

---

## 1. LIVE Clearance Gates — Current Status

| Gate | Threshold | Current | Pass? |
|---|---|---|---|
| CPCV mean WR | ≥ 60% | 65.98% | ✅ |
| DSR (Deflated Sharpe Ratio) | ≥ 95% | 96.3% (bot) / 97.8% honest selection-adjusted | ✅ |
| Closed paper signals total | ≥ 30 | **5** | ❌ |
| Closed paper signals under Run-3704 | (n/a, but expected >0 before LIVE) | **0** | ❌ |
| All 7 code-level safety items | ALL PASS | ALL PASS | ✅ |

**Single blocker: 30-paper-signal floor.** At Run-3704's projected frequency (8.8 signals/month from backtest n=106/365d), ETA ≈ **3 months** from when the first Run-3704 paper signal closes. Could be longer if the current 50h+ signal drought continues.

### The 7 Code-Level Safety Items (all PASS as of 2026-05-31)

1. API keys / secrets — no hardcoded values, `.env` gitignored, `secrets_loader.py` logs presence not values
2. Telegram reliability — 3-retry exponential backoff + SMTP secondary fallback wired (SMTP currently UNCONFIGURED — acceptable for PAPER, configure before LIVE if desired)
3. Error recovery — `consecutive_errors=8` halt threshold + exponential backoff intact (`crypto_alert.py:5254`)
4. Triple-lock execution mode — 3 independent locks confirmed:
   - `EXECUTION_MODE=LIVE` env required
   - `LIVE_MODE_CONFIRMED=YES` env required
   - non-default `YOUR_CAPITAL` required
   - inline `generate_signal()` RuntimeError guard at line 3043 as belt-and-suspenders
5. No order-execution code anywhere — signal-only invariant verified across all .py files
6. Risk gates LIVE-mode active: `MAX_OPEN_POSITIONS=4`, `MAX_PORTFOLIO_RISK_PCT=0.03`, `MAX_DRAWDOWN_PCT=0.10`, `MAX_DAILY_LOSS_PCT=3%`, `MAX_DAILY_LOSSES=3`
7. No auto-flip-to-LIVE code paths — grep confirms zero

---

## 2. MUST FIX Before LIVE — These MEDIUM items become HIGH at LIVE flip

| ID | What it is | What goes wrong at LIVE if unfixed | Effort |
|---|---|---|---|
| **C15L4-2** | ATOM not in `CORRELATED` set in `adaptive_engine.py:1858`. Inline comment defers it until ATOM accumulates ≥10 paper closes (currently 0). No automated tracking. | Worst case: BTC + BCH + ATOM same-direction cluster opens 3 of 4 LIVE position slots without triggering the correlation-cluster BLOCK gate. The BLOCK only counts tokens IN the `CORRELATED` set. | Once ATOM hits 10 closes: 1-line code change (add `"ATOM"` to the frozenset). Or add a Telegram-reminder cron now so you don't miss it. |
| **C15L4-1 / C15L2-3** | `bot_state.latest_cpcv_verdict` has Run-2749's stale config_hash (`287881168f...`) instead of Run-3704's (`3ee13531...`). OGD learning-rate gate reads the wrong config's verdict. | Today: bot is throttled CONSERVATIVELY (correct direction, just suboptimal — 0.5× LR after 48h grace expires). At LIVE: same conservative throttle, which is safer than over-aggressive, so it's not catastrophic — but adaptive learning won't be running at the proper rate for the actual deployed strategy. | Run any backtest under Run-3704 config with `WRITE_CPCV_VERDICT=1` env var (default is `1`; explorer-mode `=0` was what suppressed the write yesterday). ~30 seconds cache-hot. Reversible. Touches 1 row in 1 DB table. Detailed safety analysis in `.claude/reports/autonomous-loop/2026-05-31_cycle-15-loop_run4.md` and earlier in this loop's transcripts. |
| **C15L3-4** | CRT scanner path has NO rejection logging. The `rejections` DB table stopped writing 2026-05-27 (when `ENABLE_5M_SWEEP=0` took effect). CRT was apparently never wired to log. | At LIVE: a silent signal drought (no signals fired for hours/days) would have no debug trail. Can't distinguish "strategy too tight" from "no candidates evaluated." For a LIVE bot, the inability to debug silence is a real operational risk. | Mirror the 5M_SWEEP scanner's `_GLOBAL_REJECTIONS` pattern in `crt_engine.py`. Moderate-effort code change but mechanical. |

### Strongly recommended (not blocking, but addresses observability/edge cases)

| ID | What it is | Why it matters |
|---|---|---|
| C15L-6 | Live CRT path has no concurrent-position guard on same C1 key. Backtest enforces `entry_bar` window guard; live doesn't. With `H4_CRT_MITIGATION_TTL_H=24` + `CRT_FORWARD_BARS=864` (72h), a zone can re-fire while original signal is still in its outcome window. | Could double-expose to the same C1 setup in live. Low-frequency event but real. |
| C15L2-2 | Verdict timestamp parse loses UTC marker (VPS is `Europe/Berlin, CEST +0200`). Grace window off by 2h. **Direction is CONSERVATIVE** (throttles 2h sooner than intended). | Pre-existing, low impact. Worth fixing with explicit UTC marker on write OR explicit UTC interpretation on read. |
| C15L3-7 | `SIGNAL_COOLDOWN` expressed in 4 different forms across the codebase (minutes, bars, search-space, etc.). | DRY opportunity. Won't break LIVE but makes future cooldown changes error-prone. |

---

## 3. Pre-LIVE Final Sweep (the checklist for the actual flip)

When you're approaching the 30-signal floor and considering the flip, run these checks in order:

```
[ ] 1. 30+ closed paper signals total, with >= 15 on the current promoted pin
[ ] 2. CPCV mean WR ≥ 60%, DSR ≥ 95% on a fresh backtest under the current pin
[ ] 3. ATOM is in CORRELATED set (or has been removed from BINANCE_TOKENS)
[ ] 4. latest_cpcv_verdict matches the current pin's config_hash
[ ] 5. CRT rejection logging wired (or accept the observability gap)
[ ] 6. Run `/tradeai-pre-live` skill — produces fresh GO/NO-GO verdict
[ ] 7. Snapshot signals.db before flipping: scripts/snapshot_baseline.py
[ ] 8. Configure SMTP secondary alert channel (.env: SMTP_HOST/PORT/USER/PASS/TO)
[ ] 9. Set EXECUTION_MODE=LIVE in .env
[ ] 10. Set LIVE_MODE_CONFIRMED=YES in .env
[ ] 11. Set YOUR_CAPITAL to your actual deployed capital (not default 1000)
[ ] 12. Restart tradeai service. Watch first 24h closely.
```

You do NOT need to fix every LOW item in the ledger before LIVE — most are UX/DRY/informational. The 3 in §2 are the real action items.

---

## 4. Audit Trail — Cycles 1-4 Fixes Shipped

| Cycle | Date | ID | Severity | What it was | Verifier |
|---|---|---|---|---|---|
| #1 | 2026-05-30 | C15L-1 | CRITICAL | Backtest used hardcoded 40-min cooldown; live used 60. `backtest.py:265` now derives `COOLDOWN_BARS` from `SIGNAL_COOLDOWN` env. Plus stale CI guard cleanup in `scripts/backtest_regression.py`. | trading-system-auditor (Opus) — PASS |
| #1 (later) | 2026-05-31 | C15L-2 ledger correction | reclassified | Original CRITICAL "DSR n_trials undercount" reanalyzed: properly paired (N, σ) shows DSR clears at any selection-surface size. RESOLVED via math, not code. | self (cycle #2) |
| #1 (later) | 2026-05-31 | C15L-4 ledger withdrawal | withdrawn | "Thin head-room ~1.4pp" was based on double-counted variance (pool σ × full-population N). Withdrawn. | self (cycle #2) |
| #2 | 2026-05-31 | C15L2-1 | HIGH | OGD learning-rate gate failed OPEN — verdict-blob `updated_at` field missing from read-side fallback chain. 48h grace throttle never fired. `adaptive_engine.py:637` now includes `updated_at`. | trading-system-auditor (Opus) — PASS w/ 1 LOW caveat (pre-existing TZ bug) |
| #2 | 2026-05-31 | C15L2-5 | closed (false alarm) | "Explorer subprocess env passthrough risk" — code-quality reviewer confirmed `os.environ.copy()` is used in `_params_to_env()`. Passthrough intact. | code-quality reviewer + cycle #3 confirmation |
| #3 | 2026-05-31 | C15L3-1 | CRITICAL | CRT backtest path missing `COOLDOWN_BARS` gate. 5M_SWEEP had it, live CRT had it, CRT backtest didn't. 3 additions to `run_backtest_token_h4_crt`. Bit-exact n=106 preserved; 7 cooldown rejections logged. | trading-system-auditor (Opus) — PASS w/ 1 LOW caveat (no unit test) |
| #4 | 2026-05-31 | C15L3-2 | HIGH (housekeeping) | `*.py.bak_*` not gitignored — risk of accidentally committing stale code. Added to `.gitignore`; deleted 6 root-level backup files. | inline (git check-ignore verified) |
| #4 | 2026-05-31 | — | (exit condition met) | Cycle #4 yielded 0 new CRITICAL/HIGH → autonomous loop stopped per spec. | self |

**4 substantive code fixes shipped (2 CRITICAL, 2 HIGH). Each independently verified. Zero regressions introduced. 569/578 tests pass throughout (9 pre-existing fixture failures unchanged).**

---

## 5. All Open Findings (Snapshot at Loop Stop)

### MEDIUM — actionable

- **C15L4-1 / C15L2-3** — stale verdict (operator-deferred)
- **C15L4-2** — ATOM not in CORRELATED (becomes HIGH at LIVE)
- **C15L3-4** — CRT rejection logging missing (becomes HIGH at LIVE)
- **C15L3-3** — 50h+ signal drought under Run-3704 (within stat expectation; monitor)
- **C15L3-6** — `learning_freeze_state` shadow mode with HBAR trigger active (by design)
- **C15L2-4** — Tier B BUY WR drop in Run-3704 (attribution unclear; strategy observation)
- **C15L2-6** — ATOM/BCH stale bootstrap priors (low impact at default weights)

### MEDIUM — methodological (acknowledged, conservative direction)

- **C15L-3 / C15L4-4** — DSR pool self-reference mild circularity (direction CONSERVATIVE)

### LOW — UX / DRY / informational

- **C15L-6** — H4_CRT_MITIGATION_TTL_H + CRT_FORWARD_BARS zone re-fire risk (live has no guard; backtest does)
- **C15L2-2** — verdict timestamp parse drops UTC marker (CEST → 2h off, CONSERVATIVE direction)
- **C15L4-3** — `learning_freeze_state.since_ts` overwrites on every dedup
- **C15L2-7** — ATOM≡BCH identical-weight `min_L1=0.000` cosmetic
- **C15L3-7** — SIGNAL_COOLDOWN 4 forms (DRY)
- **C15L-9** — Bot σ choice is conservative (informational)
- **C15L-5** — CROSS_REF.md backfill for cycles 12-15 partial

### RESOLVED in this loop

- **C15L-1** — Cooldown parity (cycle #1)
- **C15L-2** — DSR n_trials concern (cycle #2 analysis)
- **C15L-4** — Thin head-room (cycle #2 — withdrawn as double-counted)
- **C15L2-1** — OGD gate failing OPEN (cycle #2)
- **C15L2-5** — Explorer env passthrough (cycle #3 — false alarm)
- **C15L3-1** — CRT backtest cooldown gate (cycle #3)
- **C15L3-2** — `*.py.bak_*` gitignore (cycle #4 — inline)

---

## 6. Where to Find Detailed Info

| Item | Location |
|---|---|
| Cycle #1 full plain-language report | `.claude/reports/autonomous-loop/2026-05-30_cycle-15-loop_run1.md` |
| Cycle #2 full plain-language report | `.claude/reports/autonomous-loop/2026-05-31_cycle-15-loop_run2.md` |
| Cycle #3 full plain-language report | `.claude/reports/autonomous-loop/2026-05-31_cycle-15-loop_run3.md` |
| Cycle #4 full plain-language report | `.claude/reports/autonomous-loop/2026-05-31_cycle-15-loop_run4.md` |
| Master ledger (every finding, every status) | `docs/comprehensive/CROSS_REF.md` (cycle-15-loop blocks near the end, ~line 240+) |
| Verdict-refresh safety analysis | Cycle #2 report (Q1-Q4 plain language); cycle #4 report §"Verdict Refresh"; this file §2 row 2 |
| Cycle audit reports (cycle-12 through cycle-14, pre-loop) | `.claude/reports/tradeai-audit/2026-05-2*_cycle*.md` |
| Bot's own design docs | `docs/AUTONOMOUS_EXPLORER_DESIGN.md`, `docs/ENTERPRISE_ROADMAP.md`, `docs/OPTIMIZATION_AGENT_PIPELINE.md` |
| Skills you can invoke | `.claude/skills/tradeai-{audit,backtest,health,paper-monitor,pre-live,signal-report,config-validate}/SKILL.md` |
| Parallel-work orchestration (built this loop) | `.claude/skills/parallel-work/SKILL.md`, `.claude/workflows/parallel-fix-verify.js` |

---

## 7. Critical Operator Discipline (CLAUDE.md anti-patterns — never re-test)

These are documented as NEVER-DO. Cycle audits keep verifying they remain locked:

- `ICT_SWING_N ≥ 3` (−3.9pp WR / −0.07 Sharpe — Cycle 1b)
- `ICT_MIN_RR_GATE ≥ 2.0` (catastrophic n=10 WR=50% — Cycle 1b)
- `BACKTEST_FVG_MIN_QUALITY = LOW/MEDIUM` (coin-flip WR — TP-1 grid)
- `BACKTEST_DAYS = 730` (averages 2024 dead-zone — Cycle Z)
- Re-adding rejected tokens: SOL, DOT, NEAR, SUI, LTC (all chronic underperformers)
- `WYCKOFF_PHASE_FILTER=strict` (−5.22pp WR — Run #140)
- `CRT_APPLY_QUALITY_GATES=1` (−21% R/year — 3-run isolation test)
- Adding `vectorbt` (breaks live/BT parity — REJECTED 2026-05-24)
- Auto-flipping `EXECUTION_MODE=LIVE` (operator discretion ONLY)

---

**End of pre-LIVE checklist. Bring this back up before any LIVE flip decision.**
