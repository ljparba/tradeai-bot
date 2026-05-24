# TradeAI Team Workflow Guide

**Your role: Project Owner — you approve only. The team handles everything else.**

---

## The Team Structure

```
YOU (approve only)
    │
    ▼
MAIN SESSION — Project Lead (Claude Code)
    │ routes work, applies fixes, runs tests
    │
    ├── SKILLS (run inside main session — type /skill-name)
    │   ├── /tradeai-health           → quick status: GREEN / YELLOW / RED
    │   ├── /tradeai-audit            → full team audit (spawns all agents in parallel)
    │   ├── /tradeai-pre-live         → pre-live checklist (CPCV/DSR + monitoring gates)
    │   ├── /tradeai-config-validate  → config consistency check
    │   ├── /tradeai-backtest         → run single backtest + parse HONEST METRICS
    │   ├── /tradeai-paper-monitor    → paper trading progress toward N≥30
    │   └── /tradeai-signal-report    → signal performance + OGD weight state
    │
    └── AGENTS (run in isolation — spawned by main session or /tradeai-audit)
        │
        REVIEW AGENTS (read-only, report findings)
        ├── ict-logic-validator           ICT sweep/MSS/FVG/killzone logic
        ├── backtest-bias-detector        Lookahead bias, overfitting, broad statistical risk
        ├── live-backtest-consistency-checker   Live vs backtest parity (incl. macro/cache divergences)
        ├── risk-management-auditor       SL/TP, position sizing, drawdown
        ├── data-pipeline-validator       Binance API, OHLCV cache, candles, WebSocket
        ├── crash-recovery-auditor        24/7 resilience, heartbeat, state_store
        ├── adaptive-learning-reviewer    OGD learning system + monitoring.py
        ├── ogd-weight-inspector          Weight convergence, monitoring.py CRIT alerts
        ├── config-consistency-validator  config.py SSoT, LIVE vs BACKTEST parity
        ├── signal-performance-analyzer   Historical WR, R:R, time-of-day edge
        ├── template-tier-calibrator      Tier A/B/C discrimination power
        ├── phase-implementation-planner  Roadmap status, next phase
        ├── trading-system-auditor        Cross-cutting system review
        ├── live-deployment-readiness-checker   Pre-live safety checklist (16 categories)
        ├── honest-metrics-reviewer       CPCV/PSR/DSR formula correctness (NEW Sprint 3)
        └── professional-code-quality-reviewer  Code quality, dead code, bugs

        OPTIMIZATION PIPELINE AGENTS (read + write, autonomous)
        ├── backtest-explorer        TEST patterns — log + REVERT (Step 1, NEW 2026-05-23)
        ├── backtest-pattern-analyzer  ANALYZE cross-cycle (Step 2, TODO post-Cycle-1)
        └── backtest-optimizer       APPLY robust patterns (Step 3)
```

**Key connecting files:**
- `docs/comprehensive/CROSS_REF.md` — every agent reads this before reporting; prevents re-flagging fixed issues
- `docs/OPTIMIZATION_AGENT_PIPELINE.md` — the 3-agent optimization flow (Explorer → Analyzer → Optimizer)
- `docs/ENTERPRISE_ROADMAP.md` — phased work queue (Section 0 lists all related architecture docs)
- `memory/project_run113_baseline_and_cycleZ.md` — current immutable baseline + dead-zone rules

---

## Session Types — When to Use What

### Session Type 1 — Quick Health Check (5 min)
**When:** Start of each week, or before doing anything with the bot.

**You type:**
```
/tradeai-health
```

**What happens:**
- Main session checks system status across all dimensions
- Reports GREEN / YELLOW / RED with reasons
- If GREEN: nothing to do — bot is healthy
- If YELLOW/RED: paste the Continuous Improvement Loop prompt (Type 4) — it will health check → audit → fix → repeat until clean

---

### Session Type 2 — Full Team Audit (30–60 min)
**When:** Monthly, or after any significant code change, or if health check returns RED.

**You type:**
```
/tradeai-audit
```

**What happens:**
1. Main session spawns up to 8 specialist agents **in parallel**
2. All agents read CROSS_REF.md first — only new issues reported
3. Each agent returns: findings + proactive suggestions + cross-domain observations
4. Main session aggregates all cross-domain observations and routes them
5. Main session produces a **Priority Action List** (Critical → High → Medium → Low)
6. Main session presents the list and waits

**Your role:** Review the Priority Action List. If you want fixes applied, start a Fix Session.

---

### Session Type 3 — Fix Session (fully autonomous)
**When:** After audit finds issues, or health check returns RED.

**You paste at the start of a new session:**
```
Resume the TradeAI fix loop. Run fully autonomous — fix all open issues without asking for approval. Make all expert decisions yourself. Use specialist agents when you need a second opinion, then pick the best recommendation.

STEP 1 — READ THE ACTIVE AUDIT
Open .claude/reports/tradeai-audit/ and find the MOST RECENT dated report (e.g. 2026-05-21.md). This is the PRIMARY source of open issues — read its full Priority Action List.
Also read:
- docs/comprehensive/CROSS_REF.md — classify each finding (REGRESSION / KNOWN STRUCTURAL / NEW / VERIFIED FIXED)
- docs/comprehensive/FIX_LOG.md — what was already fixed this session

Report:
- Total open issues by severity (CRITICAL / HIGH / MEDIUM / LOW)
- Full list: ID, severity, description, file
- What was already fixed this session (from FIX_LOG.md)

STEP 2 — PICK THE FIRST ISSUE
Priority order: REGRESSION first → CRITICAL → HIGH → MEDIUM → LOW.
State which issue you are tackling and why it was picked.

STEP 3 — BRAINSTORM (spawn specialist agent based on domain)
  ICT logic (MSS, FVG, sweeps, killzone)  → ict-logic-validator
  Backtest bias / lookahead / overfitting  → backtest-bias-detector
  Live vs backtest inconsistency           → live-backtest-consistency-checker
  OGD / adaptive learning / weights        → adaptive-learning-code-reviewer
  Risk / position sizing / drawdown        → risk-management-auditor
  Binance API / data pipeline / candles    → data-pipeline-validator
  Cross-cutting / general system           → trading-system-auditor

The agent must confirm:
1. Exact root cause
2. Minimal surgical fix (file, line, change)
3. What else could this accidentally break

STEP 4 — APPLY THE FIX
Do not ask for approval. Apply the fix, run smoke tests, run the full test suite.
If the fix touches signal logic → also run backtest.
Log the fix in docs/comprehensive/FIX_LOG.md and update CROSS_REF.md.

STEP 5 — LOOP
Move immediately to the next issue (STEP 2). Keep going until all open issues are resolved.
Only stop for: switching EXECUTION_MODE to LIVE, running DB migrations on production data, or changing config that affects real capital.
```

**What happens per issue (no approval needed):**
1. Main session picks highest-severity unresolved issue
2. Spawns the correct specialist agent to confirm root cause + fix
3. Main session picks the best recommendation as expert lead — no user input needed
4. Applies the fix immediately, runs smoke tests + full test suite
5. Runs backtest if signal logic changed
6. Logs fix in FIX_LOG.md, updates CROSS_REF.md
7. Moves to the next issue automatically

**You only need to intervene for:** switching to LIVE mode / DB migrations on production data / capital config changes

---

### Session Type 4 — Continuous Improvement Loop (fully autonomous)
**When:** Any time you want the system to self-heal — fix everything until clean with zero input from you.

**You paste at the start of a new session:**
```
Run the TradeAI continuous improvement loop. Fully autonomous — no approval needed for any code fix.

LOOP ALGORITHM:

STEP A — QUICK HEALTH CHECK
Run the equivalent of /tradeai-health:
  - Syntax check all key files (crypto_alert.py, ict_engine.py, adaptive_engine.py, backtest.py, strategy_engine.py)
  - Run full test suite (python -m pytest tests/ --ignore=tests/test_tracker_db_alignment.py -q)
  - Check CROSS_REF.md regression-prone items: C6, C8, C10, H4, H14
  - Check the latest audit report in .claude/reports/tradeai-audit/ for any remaining open issues
If tests all pass AND audit report shows 0 open issues → loop is COMPLETE. Report done and stop.
If YELLOW (open issues but tests pass) or RED (test failures) → continue to STEP B.

STEP B — FULL AUDIT
Invoke /tradeai-audit to run all 8 specialist agents in parallel.
Read the resulting report in .claude/reports/tradeai-audit/.
If the report finds 0 new issues AND average score ≥ 9/10 → loop is COMPLETE. Report done and stop.
Otherwise → continue to STEP C.

STEP C — FIX SESSION (fully autonomous)
Fix all open issues from the audit report using the Fix Session protocol:
  - Priority order: REGRESSION → CRITICAL → HIGH → MEDIUM → LOW
  - For each issue: spawn the correct specialist agent to confirm root cause + minimal fix
  - Pick the best recommendation as expert lead — no user input
  - Apply the fix, run tests, log in FIX_LOG.md, update CROSS_REF.md
  - Continue until all issues in the report are resolved

STEP D — REGRESSION CHECK
After all fixes: run full test suite + syntax checks.
If any regression found → fix inline immediately before proceeding.

STEP E — RETURN TO STEP B
Start the next audit cycle.

TERMINATION:
Loop ends when: audit finds 0 new findings AND all test suites pass AND score ≥ 9/10.
Only pause (ask user) for: switching EXECUTION_MODE to LIVE, running DB migrations on production data, changing config that affects real capital.
```

**What happens:**
1. Light health check first — catches obvious regressions without spending 8-agent audit time
2. Full audit runs and produces prioritised findings
3. Fix session runs autonomously — all fixes applied, no approval needed
4. Health check verifies fixes didn't introduce regressions
5. Full audit re-runs to confirm score improved
6. Repeats until audit finds nothing new and score ≥ 9/10

**Your role:** Paste the prompt. Come back when it says "COMPLETE."
Only interrupt if: LIVE switch / DB migration / capital config.

---

### Session Type 5 — Backtest Optimization (3-agent pipeline)

The optimization pipeline now has **three distinct agents** with separation of concerns. See `docs/OPTIMIZATION_AGENT_PIPELINE.md` for the canonical reference.

#### Type 5a — Pattern Exploration (NEW 2026-05-23)
**When:** You want to test many patterns WITHOUT committing changes. Use this for the first 1-3 cycles to build cross-cycle data for the analyzer.

**You type:**
```
Use the Task tool with subagent_type "backtest-explorer" to run all Tier 1 frequency experiments F-1 through F-11. Follow the agent's protocol exactly — don't restate the rules.
```

**What happens:**
- Explorer snapshots the baseline DB (`scripts/snapshot_baseline.py`)
- Runs each experiment: change → backtest → log → **REVERT**
- Writes result table to `docs/exploration_runs/explorer_run_*.md`
- Never modifies live config, never makes ACCEPT/REJECT decisions
- Cycle takes ~20-30 min (cache makes it fast)

**Your role:** Review the result table. Decide which patterns interest you. Either:
1. Wait 3-4 weeks, run another explorer cycle (let paper data shift the OGD state)
2. Once you have 3+ cycles → build the analyzer agent to find robust cross-cycle patterns
3. Once analyzer recommends PROMOTE candidates → invoke optimizer to apply them

#### Type 5b — Pattern Analysis (TODO — build after Cycle-1 explorer)
**When:** You have 1+ explorer cycle outputs and want cross-cycle synthesis.

**Status:** Agent not yet built. Will be created against real Cycle-1 explorer output (designed against actual data, not hypothetical).

#### Type 5c — Optimizer Apply Cycle
**When:** Analyzer has flagged STRONG PROMOTE candidates, OR you want a legacy free-form optimization cycle.

**You type (apply analyzer recommendations):**
```
Run the backtest-optimizer agent. Apply ONLY the patterns flagged STRONG PROMOTE in the latest analyzer report at docs/exploration_runs/analyzer_report_*.md. Do not freelance new hypotheses.
```

**You type (legacy free-form):**
```
Run the backtest-optimizer agent starting from the current Run-113 baseline. Read project_state.md and CROSS_REF.md first. Do not re-test already-decided experiments.
```

**What happens:**
- Optimizer snapshots baseline DB (Phase 0a-pre, mandatory FIX 3)
- Runs experiments one at a time, ACCEPT/REJECT per CPCV+DSR+monitoring gates
- Logs every result to `docs/optimization_experiments.md`
- Stops on PRIMARY SUCCESS, ACCEPTABLE SUCCESS, PLATEAU, OVER-FILTERED, STALE PROGRESS, or ADAPTIVE UNSTABLE
- Reports final configuration when done

**Exception — VPN required:** Binance is blocked in PH; optimizer halts if VPN is off.

**Honest expectation post Run-113:** per Session 4 final recommendation, further WR optimization at this n is noise. The optimizer will likely hit ACCEPTABLE_SUCCESS or PLATEAU quickly. The path to LIVE-strict is paper trading, not more optimization.

---

### Session Type 6 — Pre-Live Validation (milestone session)
**When:** When you're ready to switch from PAPER to LIVE mode.

**Prerequisites (must all be true first):**
- N ≥ 30 closed paper signals collected (~12 months at 2.6/month)
- WR in expected range (within 10pp of backtest)
- All audit findings resolved (CROSS_REF.md: 0 CRITICAL open)

**You type:**
```
/tradeai-pre-live
```

**What happens:**
1. Main session runs the full pre-live checklist
2. Spawns relevant agents to verify: risk management, config consistency, deployment readiness, live/backtest parity
3. Produces GO / NO-GO verdict with evidence
4. If NO-GO: lists exactly what must be fixed first
5. If GO: gives you the exact commands to switch to LIVE

**LIVE switch requires your explicit action (never automatic):**
1. Change `EXECUTION_MODE = 'PAPER'` to `'LIVE'` in crypto_alert.py
2. Set env var `LIVE_MODE_CONFIRMED=YES`
3. Main session will NOT do this without your direct instruction

---

### Session Type 7 — Monthly Performance Review
**When:** Monthly, once paper signals are accumulating.

**You type:**
```
Run a monthly performance review.
Use: signal-performance-analyzer, ogd-weight-inspector, template-tier-calibrator.
Run them in parallel and summarize the combined findings.
```

**What happens:**
- `signal-performance-analyzer` → WR by setup/token/time, OGD improvement trend
- `ogd-weight-inspector` → weight convergence, degenerate token detection
- `template-tier-calibrator` → Tier A/B/C separation, confluence power
- Main session aggregates all findings into one report
- Flags if performance is drifting from backtest expectations

---

### Session Type 8 — Daily OGD Weight Monitor (NEW Sprint 3 / 2026-05-22)
**When:** Daily — either run manually or via Windows Task Scheduler using `scripts/run_monitoring.bat`.

**You type (manual):**
```
python monitoring.py
```
or for JSON snapshot:
```
python monitoring.py --json data\monitoring\report_2026-05-23.json --exit-on-crit
```

**What happens:**
- Reads `token_weights` + `weight_history` tables (read-only via `file:?mode=ro` URI)
- Computes per-token: entropy, max weight, floor-pin count, drift over last 10 snapshots
- Computes cross-token: avg pairwise L1 (homogeneity check)
- Outputs alert level: OK / WARN / CRIT
- Exit code 2 on CRIT (degeneration, floor saturation, catastrophic entropy drop)

**Detection coverage:**
- CRIT: Degenerate (>0.40 single feature), Floor saturation (≥4/6 features at MIN — Run-46 fingerprint), Catastrophic entropy drop (>0.60 in 10 snapshots)
- WARN: Low entropy, pinning, drift, staleness (>14 days)

**Your role:** If CRIT → investigate flagged token's `weight_history` rows before any optimizer/explorer cycle. If WARN → document but proceed.

---

### Session Type 9 — Honest Metrics Statistical Review (NEW Sprint 3)
**When:** After any change to `validation.py`, `labeling.py`, or before declaring an experiment a real improvement. Or any time DSR<0.95 is reported.

**You type:**
```
Use the honest-metrics-reviewer agent to audit the CPCV/PSR/DSR implementation and interpretation in the latest backtest report.
```

**What happens:**
- Reviews `validation.py` for formula correctness vs Bailey/LdP 2014, López de Prado 2018
- Validates `n_trials_for_dsr` counting (FIX 1, 2026-05-23): must use COUNT(DISTINCT config_hash)
- Checks the anti-conservative proxy warning when `sr_trial_std` is auto-estimated
- Verifies VERDICT logic enforces DSR gate at both PASS and MARGINAL branches
- Statistical-philosophy review: are we drawing conclusions our n supports?

**Your role:** Read the report. If formulas are wrong → fix. If interpretation is misleading → fix the report wording. Sample-size warnings (n=46 < 100 power floor) should be heeded, not ignored.

---

## Standard Routine

```
DAILY          → python monitoring.py --exit-on-crit  (Session 8 — OGD weight health, <5 sec)
                 Or schedule scripts/run_monitoring.bat via Windows Task Scheduler

WEEKLY         → /tradeai-health         (5 min — just check GREEN/YELLOW/RED)

MONTHLY        → Continuous Improvement Loop (Session Type 4)
                 Paste the loop prompt → walk away → come back when COMPLETE
                 (runs: health check → audit → fix → health check → audit → ... until clean)

AFTER CODE CHANGE → /tradeai-health immediately
                    If YELLOW/RED → Continuous Improvement Loop

SIGNAL RATE LOW → Session 5a: backtest-explorer (autonomous, log-only, no commits)
                  THEN Session 5b: build analyzer after 3 cycles
                  THEN Session 5c: backtest-optimizer (applies analyzer's PROMOTE candidates)

MONTHLY (once paper signals accumulate) → Session 7: Monthly Performance Review

WHEN N≥30 PAPER SIGNALS → /tradeai-pre-live → GO/NO-GO
                          (now checks CPCV mean ≥58%, DSR ≥0.95, monitoring CRIT, macro filter)

AFTER ANY OPTIMIZER/EXPLORER CYCLE → python scripts/snapshot_baseline.py (FIX 3 safety net)
```

---

## Which Agent for Which Problem

| Symptom | Start with |
|---|---|
| Weird ICT signals, wrong sweep/FVG detection | `ict-logic-validator` |
| Backtest WR doesn't hold up in live | `live-backtest-consistency-checker` |
| Bot stopped generating signals | `/tradeai-health` first, then `config-consistency-validator` |
| OGD weights look wrong, learning not working | `python monitoring.py` first, then `ogd-weight-inspector` → `adaptive-learning-reviewer` |
| Signal rate too low | `backtest-explorer` (Session 5a — explore first, don't commit) |
| Want to test patterns without committing | `backtest-explorer` (NEW — Session 5a) |
| Want to apply specific known-good patterns | `backtest-optimizer` (Session 5c) |
| DSR collapsed, CPCV looks broken | `honest-metrics-reviewer` (NEW Sprint 3) — check formula + n_trials counting |
| Risk seems off (SL/TP/position sizing) | `risk-management-auditor` |
| Binance data gaps or API failures | `data-pipeline-validator` → `crash-recovery-auditor` |
| OHLCV cache may be corrupted | `data-pipeline-validator` |
| Bot crashed / stopped running silently | `crash-recovery-auditor` (now also covers heartbeat.py + state_store.py) |
| Code quality review / dead code | `professional-code-quality-reviewer` |
| "What phase are we on / what's next?" | `phase-implementation-planner` (or check `docs/OPTIMIZATION_AGENT_PIPELINE.md` status table) |
| Ready to go LIVE? | `/tradeai-pre-live` (now includes CPCV/DSR/monitoring/macro gates) |
| Full system check (monthly) | `/tradeai-audit` (now coordinates 11 agents in parallel) |
| Want to check cumulative paper signals | `/tradeai-paper-monitor` |
| Want WR breakdown by token/session/setup | `/tradeai-signal-report` |
| Just want to run ONE backtest with HONEST METRICS | `/tradeai-backtest` |

---

## How Agents Talk to Each Other

Agents don't call each other directly — they leave **Cross-Domain Observations** in their reports.

Example:
> `risk-management-auditor` notices: "ICT_MIN_RR_GATE affects position sizing downstream"
> → flags for `ict-logic-validator` to investigate

The `tradeai-audit` skill aggregates all cross-domain observations after agents finish, then routes each one to the correct follow-up agent.

This means: even if you only run one agent, its findings can trigger work in other domains — and that gets surfaced cleanly in the next audit cycle.

---

## Your Approval Gates

Three things — and only three — require your explicit "yes":

| Action | Why you approve |
|---|---|
| Switching EXECUTION_MODE to LIVE | Capital at risk — never automatic |
| Running DB migration on production data | Irreversible |
| Changing config that affects real capital | High stakes |

Everything else — code fixes, agent spawning, file reads, report writing, running tests, backtest runs — happens automatically. You paste a prompt and come back to the result.

### Hard Blockers Against LIVE Switch (auto-checked by `/tradeai-pre-live`)

Even with your explicit "yes", these MUST be cleared first:

| Blocker | Current Status (2026-05-23) |
|---|---|
| DSR ≥ 0.95 (Phase A exit criterion) | ❌ Run-113 DSR ~0.90 — short by 0.05; needs paper signals |
| `monitoring.py --exit-on-crit` returns 0 | ✅ OK (1 WARN: BNB dr_location pinning) |
| CPCV mean WR ≥ 58% | ✅ Run-113: 75.83% |
| n ≥ 30 closed paper signals | ❌ paper trading not yet started |
| No hardcoded secrets in source | ✅ Sprint 2 migration complete (.env + secrets_loader) |
| No degenerate OGD weights | ✅ all tokens healthy per monitoring.py |
| Live/backtest parity documented | ✅ DR-1 + macro asymmetric gates noted in `live-backtest-consistency-checker.md` |

**The DSR + paper-signals gates are the binding constraints.** Path to clearance: start paper trading, accumulate n≥30 closed signals (~6 months), re-evaluate DSR with real OOS data.

---

## Copy-Paste Prompts for Common Sessions

### Quick health check:
```
/tradeai-health
```

### Full audit only:
```
/tradeai-audit
```

### Continuous Improvement Loop (autonomous — paste and walk away):
```
Run the TradeAI continuous improvement loop. Fully autonomous — no approval needed for any code fix.

LOOP ALGORITHM:

STEP A — QUICK HEALTH CHECK
Run the equivalent of /tradeai-health:
  - Syntax check all key files (crypto_alert.py, ict_engine.py, adaptive_engine.py, backtest.py, strategy_engine.py)
  - Run full test suite (python -m pytest tests/ --ignore=tests/test_tracker_db_alignment.py -q)
  - Check CROSS_REF.md regression-prone items: C6, C8, C10, H4, H14
  - Check the latest audit report in .claude/reports/tradeai-audit/ for any remaining open issues
If tests all pass AND audit report shows 0 open issues → loop is COMPLETE. Report done and stop.
If YELLOW (open issues but tests pass) or RED (test failures) → continue to STEP B.

STEP B — FULL AUDIT
Invoke /tradeai-audit to run all 8 specialist agents in parallel.
Read the resulting report in .claude/reports/tradeai-audit/.
If the report finds 0 new issues AND average score ≥ 9/10 → loop is COMPLETE. Report done and stop.
Otherwise → continue to STEP C.

STEP C — FIX SESSION (fully autonomous)
Fix all open issues from the audit report using the Fix Session protocol:
  - Priority order: REGRESSION → CRITICAL → HIGH → MEDIUM → LOW
  - For each issue: spawn the correct specialist agent to confirm root cause + minimal fix
  - Pick the best recommendation as expert lead — no user input
  - Apply the fix, run tests, log in FIX_LOG.md, update CROSS_REF.md
  - Continue until all issues in the report are resolved

STEP D — REGRESSION CHECK
After all fixes: run full test suite + syntax checks.
If any regression found → fix inline immediately before proceeding.

STEP E — RETURN TO STEP B
Start the next audit cycle.

TERMINATION:
Loop ends when: audit finds 0 new findings AND all test suites pass AND score ≥ 9/10.
Only pause (ask user) for: switching EXECUTION_MODE to LIVE, running DB migrations on production data, changing config that affects real capital.
```

### Start backtest EXPLORER (test patterns, no commits — NEW):
```
Use the Task tool with subagent_type "backtest-explorer" to run all Tier 1 frequency experiments F-1 through F-11. Follow the agent's protocol exactly — don't restate the rules.
```

### Start backtest OPTIMIZER (legacy free-form OR apply analyzer-recommended patterns):
```
Run the backtest-optimizer. Read project_state.md and docs/OPTIMIZATION_AGENT_PIPELINE.md first. Start from current Run-113 baseline. Do not re-test already-decided experiments.
```

### Daily OGD weight monitor (NEW Sprint 3):
```
python monitoring.py --exit-on-crit
```
Or schedule via Windows Task Scheduler using `scripts/run_monitoring.bat`.

### Snapshot baseline DB before any risky cycle (NEW FIX 3):
```
python scripts/snapshot_baseline.py
```

### Honest-metrics statistical review (NEW Sprint 3):
```
Use the honest-metrics-reviewer agent to audit validation.py and the HONEST METRICS interpretation in the latest backtest report.
```

### Monthly performance review:
```
Run a monthly review using signal-performance-analyzer, ogd-weight-inspector, and template-tier-calibrator in parallel. Summarize combined findings.
```

### Pre-live check (now with Sprint 3 honest-metrics gates):
```
/tradeai-pre-live
```

### Single backtest with HONEST METRICS:
```
/tradeai-backtest
```

### Paper trading progress:
```
/tradeai-paper-monitor
```

### Signal performance report:
```
/tradeai-signal-report
```
