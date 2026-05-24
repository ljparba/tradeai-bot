# TradeAI Issue Resolution Protocol

Enterprise-grade workflow for handling audit findings. Follow this every time issues are found.
Never fix multiple issues without validation in between.

---

## Core Rule

> **One issue → brainstorm → fix → test → sign off. Then and only then move to the next.**

---

## Phase 1 — Audit

1. Decide which audit agent(s) to run (see Agent Routing below)
2. Run the agent — do NOT fix anything yet
3. Copy all findings into `AUDIT_REPORT.md`
4. Fill `ISSUE_CHECKLIST.md` — sort by severity (CRITICAL → HIGH → MEDIUM → LOW)
5. Update `INDEX.md` Active Audit section

---

## Phase 2 — Per-Issue Loop

```
PICK next unchecked issue (highest severity first)
        ↓
CLASSIFY domain → pick specialist agent (see Agent Routing)
        ↓
BRAINSTORM with agent
  Agent output must answer:
  - What is the root cause?
  - What is the minimal surgical fix?
  - What other functionality could this affect?
        ↓
REVIEW brainstorm → confirm fix approach
        ↓
APPLY fix (touch only what is necessary — no cleanup, no extras)
        ↓
SMOKE TEST (see Smoke Test Matrix)
        ↓
FULL TEST SUITE (all 162 tests must pass)
        ↓
BACKTEST (only if signal logic / filters / parameters changed)
        ↓
LOG the fix in FIX_LOG.md
        ↓
MARK issue as done [x] in ISSUE_CHECKLIST.md
        ↓
PICK next issue
```

---

## Agent Routing — Brainstorm Phase

| Issue Domain | Specialist Agent |
|---|---|
| ICT logic (MSS, FVG, sweeps, killzone, swing detection) | `ict-logic-validator` |
| Backtest bias / lookahead / overfitting / curve-fitting | `backtest-bias-detector` |
| Live vs backtest logic inconsistency | `live-backtest-consistency-checker` |
| OGD / adaptive learning / weight behavior | `adaptive-learning-code-reviewer` |
| OGD weight inspection / convergence | `ogd-weight-inspector` |
| Risk / position sizing / drawdown / exposure | `risk-management-auditor` |
| Binance API / data pipeline / candles / WebSocket | `data-pipeline-validator` |
| Signal statistics / win rate / performance trends | `signal-performance-analyzer` |
| Template tier quality / Tier A/B/C calibration | `template-tier-calibrator` |
| Pre-live deployment safety | `live-deployment-readiness-checker` |
| Cross-cutting / general system review | `trading-system-auditor` |

---

## Smoke Test Matrix

Run the targeted test first, then the full suite.

| What Changed | Targeted Smoke Test | Full Suite Required |
|---|---|---|
| ICT engine logic (`ict_engine.py`) | `pytest tests/test_phase2_data.py` | Yes |
| DB / SQL / schema | `pytest tests/test_tracker_db_alignment.py` | Yes |
| OGD / adaptive weights | `pytest tests/test_adaptive_snapshot.py` | Yes |
| Signal generation / backtest logic | `pytest tests/test_tunebot.py` + mini backtest | Yes |
| Any other change | Full suite only | Yes |

**Full suite command:**
```
pytest tests/ -v
```
Expected: 162/162 PASS

**Mini backtest command** (when signal logic changed):
```
python backtest.py
```
Check: WR, z-score, n-signals — must not regress significantly from baseline.

---

## Severity Handling Rules

| Severity | Fix This Session? | Can Skip? |
|---|---|---|
| CRITICAL | Yes — fix before anything else | No |
| HIGH | Yes — after all CRITICALs | No |
| MEDIUM | Next session preferred | Only if session is already long |
| LOW | Backlog | Yes — skip unless fix is 1-line zero-risk |

---

## Hard Rules — Never Break These

1. Never fix more than 1 issue before running smoke test
2. Never carry an unvalidated fix into the next session
3. If smoke test fails → revert immediately → re-brainstorm
4. Never run full backtest as substitute for targeted smoke test
5. MEDIUM and LOW issues never block starting paper trading
6. Log every fix in FIX_LOG.md — no exceptions
7. Update INDEX.md at end of every session

---

## End of Session Checklist

Before closing:
- [ ] All applied fixes logged in `FIX_LOG.md`
- [ ] `ISSUE_CHECKLIST.md` updated (all done items marked [x])
- [ ] `INDEX.md` Active Audit section updated (Resolved count, Resume From)
- [ ] No unvalidated fix left in the codebase
