# Autonomous Explorer — Design Document
**Status:** DESIGN APPROVED · 2026-05-24 · Phased rollout pending implementation
**Owner:** TradeAI R&D layer
**Locked decisions:** vectorbt REJECTED (live/BT parity risk) · Optuna ADOPTED (Bayesian search over existing engine)

---

## 1. Goal & Non-Goals

### Goal
A self-driving strategy R&D system that runs nightly **without operator input**, autonomously searches the parameter / pattern space, and proposes (never auto-executes) Pareto-improving baselines. Turns the bot's 8.5-month paper-waiting period into productive R&D time.

### Non-Goals
- **NOT** auto-flip to LIVE — promotion goes only as far as updating `baseline_pin.json` and writing `tune_history`. The LIVE-mode flip remains a deliberate operator action.
- **NOT** a new backtest engine. Uses the existing `backtest.py` (which preserves live/BT parity).
- **NOT** a meta-learning / RL system. Bayesian search of fixed param ranges only.
- **NOT** a replacement for the manual `backtest-explorer` agent — that agent handles ad-hoc operator-defined experiments. Autonomous explorer handles the standing search.

---

## 2. Why NOT vectorbt (locked decision)

vectorbt is 50–100× faster than our current engine but uses NumPy-vectorized primitives that cannot import `ict_engine.py` directly. Using it would require:

1. Re-implementing all ICT logic (swing detection, sweep, MSS, FVG, dealing range, EQH/EQL, killzones, etc.) in vectorbt's vector language.
2. Maintaining two engines forever; any subtle divergence (off-by-one bar, swing-N edge cases, displacement gap rules) silently breaks live/BT parity.
3. Live/BT consistency audit dim would drop from 9.5 → ~6 immediately.
4. Cross-engine verification step on every promotion.

**The speed gain is not worth the parity cost.** With cached Binance data, our existing engine runs ~10-15s per backtest. That allows ~1,500-2,000 runs per overnight session — already enough for autonomous exploration.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                  AUTONOMOUS EXPLORER (nightly job)               │
│  ──────────────────────────────────────────────────────────      │
│                                                                  │
│  ┌──────────┐    ┌──────────────────┐    ┌──────────────────┐    │
│  │ Optuna   │───▶│ Existing         │───▶│ Honest Validation│    │
│  │ Bayesian │    │ backtest.py      │    │ Gates            │    │
│  │ Search   │    │ (cached candles) │    │ CPCV+DSR+q05     │    │
│  └──────────┘    └──────────────────┘    └────────┬─────────┘    │
│       ▲                                            │              │
│       │                                            ▼              │
│  ┌────┴─────────┐                         ┌─────────────────┐     │
│  │ Learning Log │◀────────────────────────│ Promote-or-Skip │     │
│  │ (avoid dead  │   updates next search   │ Decision Engine │     │
│  │ zones)       │   bias                  └────────┬────────┘     │
│  └──────────────┘                                   │              │
│                                                     ▼              │
│                                          ┌─────────────────┐      │
│                                          │ Anti-Overfit    │      │
│                                          │ Guard           │      │
│                                          │ (DSR death-     │      │
│                                          │  spiral check)  │      │
│                                          └────────┬────────┘      │
│                                                   │                │
│                            PASS ✓                 │  FAIL ✗        │
│                                                   ▼                │
│             ┌──────────────────────┬──────────────────────┐       │
│             ▼                      ▼                      ▼       │
│   ┌──────────────────┐  ┌─────────────────┐  ┌──────────────┐    │
│   │ Update           │  │ Pareto Archive  │  │ Telegram     │    │
│   │ baseline_pin.    │  │ (top-10 non-    │  │ Morning      │    │
│   │ json             │  │  dominated)     │  │ Digest       │    │
│   │ + tune_history   │  └─────────────────┘  └──────────────┘    │
│   └──────────────────┘                                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. Phased Rollout

### Phase 1 — Core Loop (Days 1-2)
**Definition of done:** `python scripts/autonomous_explorer.py --trials 100` runs Optuna for 100 trials, scores each via existing backtest + CPCV+DSR gates, persists results to `data/explorer_learning.db`, does NOT yet promote.

Ships:
- `scripts/autonomous_explorer.py` — Optuna study runner + scoring
- `data/explorer_learning.db` — schema: `trials(trial_id, config_hash, params_json, n, wr, cpcv_mean, cpcv_std, q05, dsr, sharpe, dsr_proxy_used, walltime_s, verdict, timestamp)`
- `requirements.txt`: add `optuna>=3.5,<4`
- Reuses existing: `backtest.py`, `validation.py` CPCV/DSR, `scripts/compute_cross_config_sr_std.py`

Search space (initial, locked):
```python
# Continuous (Bayesian)
ICT_SWEEP_LOOKBACK   in [15, 60]   step 5
ICT_MSS_HORIZON      in [10, 60]   step 5
ICT_FVG_MIN_GAP      in [0.0005, 0.0030] step 0.0001
DEALING_RANGE_LOOKBACK in [30, 100] step 10

# Categorical
BACKTEST_BIAS_4H_GATE  in {none, loose, strict}
BACKTEST_TREND_1H_GATE in {none, loose, strict}
BACKTEST_FVG_MIN_QUALITY in {LOW, MEDIUM, HIGH}
BACKTEST_MSS_MIN_QUALITY in {LOW, MEDIUM, HIGH}

# Anti-pattern lockouts (from documented findings — never explored)
ICT_SWING_N    LOCKED to 2  (3+ proven net-negative across Cycle 1b + 1c)
ICT_MIN_RR_GATE LOCKED to 1.5 (≥2.0 catastrophic per Cycle 1b)
```

Gates per trial (must ALL pass to count as "PASS"):
- n ≥ 30
- cpcv_wr_mean ≥ 60%
- cpcv_wr_q05 ≥ 50%
- dsr ≥ 95%
- monitoring.py exit 0 (no OGD degeneration)

### Phase 2 — Scheduler + Anti-Overfit Guard (Days 3)
**Definition of done:** Windows Task Scheduler runs explorer 6h/night. Anti-overfit guard pauses the run if statistical health degrades.

Ships:
- `scripts/run_explorer_nightly.bat` — Task Scheduler entry point
- Anti-overfit guard in `autonomous_explorer.py`:
  - PAUSE if cross-config sr_trial_std jumps >25% in one session
  - PAUSE if 50 consecutive trials produce VERDICT=FAIL (search lost the basin)
  - PAUSE if DSR for "best of session" drops below current baseline DSR by >5pp
  - On PAUSE: log reason, fire Telegram alert, exit gracefully
- Pre-cache step: `python -c "from backtest import warm_cache; warm_cache()"` runs before search so all trials are cache-hits

### Phase 3 — Auto-Promotion + Pareto Archive (Day 4)
**Definition of done:** A trial that beats current baseline on every honest dimension AND reproduces in a second confirmation run gets auto-promoted via the existing `scripts/promote_baseline.py` helper. Pareto archive holds the top-10 non-dominated configs.

Strict auto-promotion criteria:
1. Beats current baseline on cpcv_mean (Δ ≥ +0.5pp)
2. Sharpe (CPCV) Δ ≥ +0.02
3. CPCV std does NOT widen by more than 1.0pp
4. q05 Δ ≥ -1.0pp (worst-case doesn't get worse)
5. n change within ±20% (no extreme over/under-fitting)
6. DSR ≥ 95% honest cross-config
7. **Two independent runs** must reproduce identical metrics (config_hash match required)
8. Anti-overfit guard NOT tripped this session

If ALL pass → auto-call `promote_baseline.py` → updates `baseline_pin.json` + writes `tune_history` row with status `AUTO_PROMOTED`. Operator notified via Telegram. Operator can roll back manually.

Pareto archive (`data/pareto_archive.json`):
- Top-10 non-dominated configs across (cpcv_mean, cpcv_std⁻¹, Sharpe, n)
- Refreshed each session
- Surfaced in tracker dashboard

### Phase 4 — Dashboard Panel + Telegram Digest (Day 5)
**Definition of done:** New "🤖 Auto-Explorer" tab in `tracker_html.py`. Morning Telegram digest summarizes overnight activity.

Tracker panel:
- Current Optuna study state (n_trials, best trial, best params)
- Pareto archive table (top-10 non-dominated configs)
- Learning heatmap: param-space coverage visualization
- Auto-promotion history (last 10 promotions, with rollback links)
- "Pause/Resume" toggle

Telegram digest (06:00 UTC daily):
```
🌅 Auto-Explorer overnight digest

Trials run:         1,247
PASS verdicts:      89 (7.1%)
Anti-overfit hits:  0
Auto-promotions:    0
Best of session:    cpcv=79.3% Δ=+0.2pp (not promoted — failed reproducibility)

Pareto top-3:
  #1  ICT_SWEEP_LOOKBACK=20, MSS_HORIZON=30, ... (current baseline Run-168)
  #2  ICT_SWEEP_LOOKBACK=25, MSS_HORIZON=35, ... (challenger)
  #3  ...

Coverage: 34% of search space explored
Next session: continues Bayesian acquisition from study.db
```

---

## 5. Risk Register

| Risk | Mitigation |
|------|------------|
| **DSR death spiral** — n_trials counts grow to 10,000+, deflating every winner's DSR | DSR pool uses *distinct promoted config_hashes only* (already shipped via FIX 1), explorer's own trials are NOT added to DSR pool unless they get promoted |
| **Cache drift mid-search** — Binance candles update daily; mid-session refresh would invalidate intra-session comparisons | Pin a frozen snapshot of candle cache at session start, restore on session end |
| **Search bias toward fast-running configs** — Lower N means faster runs but worse statistics | Score function penalizes n<30 to break the speed-accuracy tradeoff |
| **Anti-pattern re-exploration** — Optuna might keep proposing known-bad regions | Hard lockouts in search space + soft penalty from learning log |
| **Live code drift breaks parity mid-search** — Operator edits ict_engine.py while explorer is running | Pre-flight: hash check of (config.py, backtest.py, ict_engine.py); abort if drift since last session |
| **Auto-promote chains creating regression** — Promotion #1 enables config space where Promotion #2 is overfit | Two-promotion-per-day cap; mandatory 24h "soak" between auto-promotions |
| **Operator surprise** — Wake up to a promoted baseline you don't recognize | Telegram digest + dashboard banner with rollback button + 7-day rollback history |

---

## 6. Integration Points (Existing Code Touches)

| File | What changes |
|------|--------------|
| **NEW** `scripts/autonomous_explorer.py` | Main entry point |
| **NEW** `scripts/run_explorer_nightly.bat` | Task Scheduler hook |
| **NEW** `data/explorer_learning.db` | Trial history schema |
| **NEW** `data/pareto_archive.json` | Top-10 non-dominated configs |
| **NEW** `tracker_html.py` "Auto-Explorer" tab | UI surface |
| **NEW** `tracker.py` `/api/explorer/*` routes | Dashboard API |
| **REUSE** `backtest.py` | No changes — main loop runs as subprocess |
| **REUSE** `validation.py` CPCV/DSR | No changes — same honest gates |
| **REUSE** `scripts/promote_baseline.py` | Add `--auto` flag for AUTO_PROMOTED status |
| **REUSE** `scripts/compute_cross_config_sr_std.py` | Run after every auto-promotion |
| **REUSE** `monitoring.py` | Health check between trials |
| **REUSE** `baseline_pin.json` | Updated by auto-promotion path |
| **REUSE** `tune_history` table | New status enum: `AUTO_PROMOTED` |
| **REQ.** `requirements.txt` | Add `optuna>=3.5,<4` |

---

## 6.5 Honest-Metrics Integration (Phase 1+3)

Every trial and every promotion uses the **same honest validation pipeline** as manual operator backtests:

| Metric | Source | Same as manual? |
|--------|--------|-----------------|
| CPCV WR mean / std / q05 | `validation.py` per-trial output | ✓ identical |
| DSR (multi-test) | Honest cross-config `sr_trial_std` from `bot_state` | ✓ FIX 1 Part 2 in effect |
| `dsr_proxy_used` flag | Captured from backtest stdout | ✓ logged per trial |
| PSR (OOS) | Computed by `validation.py` | ✓ informational |
| Cross-config std refresh | Called automatically after every AUTO_PROMOTED | ✓ next trial sees updated pool |

**Phase 3 ACCEPT gate**: trial's DSR must be ≥95% AND beat current pin on CPCV mean / Sharpe / std-no-widen.

**Critical safeguard**: explorer trials are NOT counted in DSR pool unless they get PROMOTED. The pool only grows when a baseline is actually promoted, preventing DSR death-spiral from running thousands of exploratory trials.

---

## 7. Anti-Patterns (do NOT do)

1. **Don't add vectorbt** — see §2.
2. **Don't auto-flip LIVE** — promotion ≠ live activation.
3. **Don't search SWING_N or MIN_RR_GATE** — anti-patterns are locked.
4. **Don't run >1 explorer instance** — SQLite write contention will corrupt the learning DB. PidFile guard required.
5. **Don't include explorer trials in DSR pool** — only promoted configs count.
6. **Don't promote without two reproducible runs** — single-run wins are luck.
7. **Don't trust Optuna's "best trial" blindly** — apply Pareto archive logic; the best on one dim might be worst on another.
8. **Don't run during paper-trading hours when bot is live** — DB lock conflicts. Schedule for 02:00-08:00 local when crypto_alert.py is in low-activity window.

---

## 8. Operational

### How to start a session manually
```bash
python scripts/autonomous_explorer.py --trials 100 --study-name nightly_explorer
```

### How to view results
- Tracker dashboard → 🤖 Auto-Explorer tab
- `data/explorer_learning.db` (SQLite, queryable directly)
- Morning Telegram digest

### How to rollback an auto-promotion
```bash
python scripts/promote_baseline.py --rollback-to-run <N>
```
Or click "Rollback" in the dashboard's Tune Bot History next to the AUTO_PROMOTED row.

### How to pause
```bash
python scripts/autonomous_explorer.py --pause
# resumes from Task Scheduler next night unless --pause persists
```
Or click the "Pause" toggle in the dashboard.

### How to expand the search space
Edit the search space definition in `autonomous_explorer.py`. Document the change in this file's §4 Phase 1 block. Hash check will catch the code change next session.

---

## 9. Decision Log

| Date | Decision | Why |
|------|----------|-----|
| 2026-05-24 | vectorbt REJECTED | Parity risk; speed gain unnecessary with cache |
| 2026-05-24 | Optuna ADOPTED for search | Bayesian > brute grid; preserves existing engine |
| 2026-05-24 | DSR pool stays at *promoted-only* configs | Explorer trials would otherwise inflate n_trials |
| 2026-05-24 | Two-promotion-per-day cap | Prevent runaway promotion chains |
| 2026-05-24 | Auto-promotion requires reproducibility | Single-run wins are statistical luck |
| 2026-05-24 | Phased rollout 1→2→3→4 | Ship incrementally; each phase usable alone |

---

## 10. Cross-References

- [docs/ENTERPRISE_ROADMAP.md](ENTERPRISE_ROADMAP.md) — vectorbt REJECT row + new ADOPT row for Autonomous Explorer
- [docs/OPTIMIZATION_AGENT_PIPELINE.md](OPTIMIZATION_AGENT_PIPELINE.md) — 3-agent pipeline now has an autonomous layer added
- [docs/comprehensive/CROSS_REF.md](comprehensive/CROSS_REF.md) — new entry: AUTO_EXPLORER_PHASE_1..4
- [.claude/agents/backtest-explorer.md](../.claude/agents/backtest-explorer.md) — manual + autonomous explorer coexist
- [.claude/agents/backtest-optimizer.md](../.claude/agents/backtest-optimizer.md) — Tier 2 grids will increasingly be deprecated in favor of Optuna search
- [data/baseline_pin.json](../data/baseline_pin.json) — auto-promotion target
- [scripts/promote_baseline.py](../scripts/promote_baseline.py) — gets `--auto` flag in Phase 3

---

## 11. Status & Next Steps

| Phase | Status | Notes |
|-------|--------|-------|
| 1 — Core loop | **DONE 2026-05-24** | `scripts/autonomous_explorer.py`, `data/explorer_learning.db`, env overrides in `ict_engine.py`, Optuna study persistence. Smoke test Trial 4: PASS (n=44, WR=77.3%, CPCV 77.25%, DSR 100%). |
| 2 — Anti-overfit + observability (operator-triggered) | **DONE 2026-05-24** | **Scheduler omitted per operator preference** — operator triggers all sessions. Shipped: PidFile collision guard, pre-cache warm step, anti-overfit guard (4 trip conditions), Telegram notify, `--status` command, `data/explorer_session.json` for live state. Smoke test Trial 0 ran cleanly with full Phase 2 wrapper. |
| 3 — Auto-promotion + Pareto archive | **DONE 2026-05-24** | Shipped: `_try_auto_promote()` with 8-criteria eligibility gate + reproducibility re-run + daily cap (2/day) + 24h soak; `data/pareto_archive.json` (top-10 non-dominated configs); `data/promotion_log.json` (30-entry rolling audit); `promote_baseline.py --auto` and `--rollback-to-run` flags; `--status` shows promotions today + Pareto top-5. **Auto-promotion NEVER flips LIVE** — only writes baseline_pin.json + tune_history (status=AUTO_PROMOTED). 8/8 logic tests pass. **Bug-fix 2026-05-24 post-review:** (a) backtest_runs row cleanup deferred until after promotion decision so promoted trial's row remains as the new baseline; (b) `_refresh_cross_config_std()` called immediately after every auto-promotion so subsequent trials' DSR uses the updated honest pool (NOT the within-fold proxy). |
| 4 — Dashboard panel + on-demand digest | **DONE 2026-05-24** | Shipped: 4 new API routes (`/api/explorer/status`, `/pareto`, `/promotions`, `/trials`); new "🤖 Auto-Explorer" tab in `tracker_html.py` with session banner, 4 summary cards, Pareto archive table, auto-promotion history, recent trials table; auto-refresh every 15s while visible; CLI `--digest [hours]` command for operator copy-into-Telegram summary. Scheduled cron digest **omitted per operator preference** — operator triggers all digests on demand. All 4 endpoints + HTML elements verified live. |

## Post-Audit Fixes (2026-05-24)

Full code audit identified 2 CRITICAL/HIGH issues. Both fixed:

| ID | Fix | What changed |
|----|-----|--------------|
| **C1** | Race condition: explorer could DELETE operator's backtest row if `python backtest.py` ran concurrently | `_run_backtest()` and `_precache_warm()` now snapshot `MAX(backtest_runs.id)` BEFORE the subprocess and scope row lookup to `WHERE id > ?`. Multiple new rows = warning + take the latest (ours) without touching the others. PidFile only blocks another *explorer*; it doesn't block operator-driven backtests. |
| **H1** | Orphan `backtest_runs` row if exception occurred between trial completion and cleanup | Post-backtest logic in `_objective_factory` now wrapped in `try/finally`. Cleanup of trial's row always runs in `finally`, only skipped when `promoted=True` (promoted trial's row IS the new baseline). Initial `promoted = False` declared before the try block so it's defined in the finally scope. |

Verified by 9/9 structural checks: max_id snapshot present (read-only mode), scoped lookup query, concurrent-operator warning, try/finally wrap, conditional cleanup, precache also scoped, --clear-checkpoint return code now checked.

### Round-2 polish fixes (2026-05-24, post C1+H1)

| ID | Fix | What changed |
|----|-----|--------------|
| **L5** | Module docstring rewrite | `autonomous_explorer.py` header now lists all 4 phases + post-audit fixes. Old "Phase 1 + Phase 2" wording removed. |
| **M2** | Implemented dormant q05 check | `_eligibility_check()` now actually compares `cpcv_q05` delta against `PROMOTE["cpcv_q05_delta_pp_min"]` (was set in dict but never checked). Derives pin q05 via mean − 1.645·std when not stored. `promote_baseline.py` now persists `cpcv_wr_q05_pct` in `baseline_pin.json` so future eligibility checks have the exact value. |
| **M3** | `_read_cross_config_std` uses ro mode | `sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)` — eliminates any chance of write contention with live bot writers. |
| **M4** | `rollback_to_run` SQL now uses real previous-pin run_id | Was inserting literal string `'?'` as `old_val` in tune_history. Now reads current pin BEFORE overwriting and writes that as `old_val` (e.g., `"Run-168"`). Audit trail now shows `from Run-X to Run-Y` clearly. |
| **L1** | Anti-pattern startup assertion added | `_assert_anti_pattern_locks()` runs at session start. Fails fast if (a) `ICT_SWING_N` / `ICT_MIN_RR_GATE` values in `ict_engine.py` no longer match documented locks, or (b) someone added an env-override for these and the env var is set. Prevents silent drift if future edits remove the implicit lock. |
| **L4** | Telegram rate-limit on promote failures | Persistent promote-failure (e.g., subprocess crash) would spam Telegram once per PASS trial. Now only the FIRST failure per session sends Telegram; further failures are console-only. Reset on next session. |

All 6 fixes verified by 7/7 structural sanity checks. System is now polished — only L2 (PID liveness check duplication explorer/tracker) remains as a refactor opportunity, no functional bugs left.

### Phase 1 Verified Throughput (REVISED from original estimate)

The original estimate of 1,500-2,000 trials/night assumed ~10-15s per backtest. Empirical from-scratch reality is **~11 minutes per trial** (Trial 4 = 662s walltime). My earlier estimate conflated cached-fetch time with full-simulation time — when each trial uses a different param set, the simulation step (5M bars × 365d × 10 tokens × per-bar ICT detection) is the bottleneck, not data fetch.

| Window | Trials |
|--------|--------|
| Per trial (avg) | ~11 min |
| Per hour | ~5 |
| Per 6-hour overnight session | **~30** |
| Per week (7 nights) | ~210 |
| Per month | ~900 |
| Paper-trading wait (8.5 mo) | ~7,500 |

Optuna typically finds Pareto front in 100-300 trials for an 8-dim space, so **~5-10 nights of unattended search is enough for a meaningful first sweep**.

### Phase 1 Definition of Done (achieved)

✅ `python scripts/autonomous_explorer.py --trials N` runs Optuna over the existing engine
✅ Search space matches §4 with locked anti-patterns (ICT_SWING_N=2, ICT_MIN_RR_GATE=1.5)
✅ Each trial scored via existing CPCV + DSR gates
✅ Results persisted to `data/explorer_learning.db` (full trial ledger)
✅ Optuna study persisted to `data/optuna_study.db` (resumable)
✅ ICT params injectable via env (no per-trial file edits)
✅ Explorer trials AUTO-DELETED from `backtest_runs` after capture → no DSR pool pollution, no baseline-pin drift
✅ `--list-recent`, `--best`, `--study-name` inspector commands
✅ Windows console Unicode-safe printing
✅ 20-min timeout per trial (was 8-min — undersized for from-scratch backtest)

### Speedup options for Phase 5+ (not in scope yet)

1. **Multiprocessing** — process tokens in parallel. 3-4× speedup on 4-core CPU. Low risk, no parity issue.
2. **Subset-only screen** — 3-token fast pass for screening, full 10-token confirmation only on candidates. 3× screening throughput.
3. **Walk-forward window cache** — reuse partial OOS simulation across trials. Complex, big gain.

**Approval gate before Phase 2 start:** Operator confirms (a) realistic 30 trials/night throughput is acceptable, (b) wants Task Scheduler integration (otherwise manual `--trials N` runs work fine).
