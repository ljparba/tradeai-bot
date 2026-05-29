---
name: tradeai-audit
description: Run a complete multi-agent audit of the TradeAI system across all dimensions and produce a unified 10/10 scorecard. Use this whenever the user wants a full system audit, comprehensive review, score update, or asks how close the system is to 10/10. Always trigger on phrases like "run the audit", "full audit", "full review", "check everything", "10/10 scorecard", "system score", "how are we doing", "audit all agents", or "comprehensive check". Also trigger proactively before any major phase transition or before switching to LIVE mode.
---

# TradeAI Full Multi-Agent Audit

You are the senior technical lead. Coordinate all audit agents, synthesize their findings, and produce the authoritative 10/10 scorecard. This is the highest-level quality gate for the TradeAI system.

## CRT-era context (2026-05-27 onward) — READ FIRST

TradeAI now ships TWO scanners (`5M_SWEEP` + `H4_CRT`). Operator currently runs CRT-only (`ENABLE_5M_SWEEP=0`). Before invoking subagents, read `.claude/CRT_STRATEGY_CONTEXT.md` and ensure subagents read it too. Each subagent's `.md` has a CRT-era context block added 2026-05-27.

Today's audit cycle (2026-05-27) caught a CRITICAL `LIVE_LIQUID_HOURS` ImportError that would have crash-looped the bot on first CRT signal — fixed in commit `6c9137e`. Subsequent audits should verify it remains fixed.

**Project:** `/home/tradeai/TradeAI/` (VPS) — the original Windows path `C:\Users\User\Desktop\TradeAI\` in older docs refers to the same project pre-VPS migration.
**Target:** 10/10 across all dimensions
**Audit history:**
- 2026-05-21 8-agent audit: **3.3/10** overall (pre-fix baseline; all CRITICAL/HIGH/MEDIUM catalogued)
- 2026-05-21 bug-fix pass: **72 of 76 issues resolved** (4 skipped as structural/by-design)
- Post-fix estimated: **~8/10** (no re-audit since — this run produces the first post-fix score)

---

## Review Previous Run

Before dispatching agents, check for previous audit reports:
```
C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-audit\
```
Read the most recent file. Extract for comparison:
- Previous scores per dimension (X/10 each)
- Previous overall score
- CRITICAL/HIGH issues that were listed — are they still open or were they fixed?
- Previous GO/NO-GO verdict

If no previous report — note "First audit run" and continue.

---

## Step 1 — Parallel Agent Dispatch

Spawn ALL agents simultaneously in a single message as parallel tool calls. Each agent should run concurrently to save time. Do not wait for one to finish before starting the next.

Fire these agents using the Agent tool with their exact `subagent_type` names:

1. `ict-logic-validator` — ICT principle conformance in ict_engine.py
2. `live-backtest-consistency-checker` — live vs backtest parameter parity (incl. macro gate divergence)
3. `risk-management-auditor` — position sizing, SL logic, exposure limits
4. `backtest-bias-detector` — lookahead bias, data snooping, curve-fitting
5. `adaptive-learning-code-reviewer` — OGD adaptive learning validity
6. `ogd-weight-inspector` — OGD weight state in TradeAI.db + monitoring.py alerts
7. `template-tier-calibrator` — Tier A/B/C template quality separation
8. `data-pipeline-validator` — Binance API, OHLCV cache integrity, stale candle handling
9. `honest-metrics-reviewer` — validation.py CPCV/PSR/DSR formulas + interpretation (Sprint 3)
10. `crash-recovery-auditor` — heartbeat.py, state_store.py, supervisord wiring (Sprint 1)
11. `config-consistency-validator` — config.py as single source of truth (Sprint 2)

## Step 2 — Score Each Dimension

After all agents complete, map their findings to a 0–10 score per dimension.

Scoring guide:
- **10/10** = no issues of any severity
- **8–9/10** = LOW severity issues only (cosmetic, minor calibration)
- **6–7/10** = MEDIUM issues (suboptimal but not wrong)
- **4–5/10** = HIGH issues (logic flaws, parameter problems)
- **0–3/10** = CRITICAL issues (wrong signals, live-blocking bugs)

## Step 3 — Unified 10/10 Scorecard

| Dimension | Agent | Pre-Fix Audit (2026-05-21) | This Audit | Target | Trend vs Pre-Fix |
|-----------|-------|---------------------------|------------|--------|-----------------|
| ICT Logic Integrity | ict-logic-validator | 3/10 | ? | 10/10 | ? |
| Live/Backtest Consistency | live-backtest-consistency-checker | 3/10 | ? | 10/10 | ? |
| Risk Management | risk-management-auditor | 2/10 | ? | 10/10 | ? |
| Backtest Validity | backtest-bias-detector | 3/10 | ? | 10/10 | ? |
| Adaptive Learning | adaptive-learning-code-reviewer | 4/10 | ? | 10/10 | ? |
| OGD Weight Quality | ogd-weight-inspector | 4/10 | ? | 10/10 | ? |
| Template Calibration | template-tier-calibrator | 4/10 | ? | 10/10 | ? |
| Data Pipeline | data-pipeline-validator | 3/10 | ? | 10/10 | ? |
| **Honest Metrics (CPCV/DSR)** | honest-metrics-reviewer | n/a (new) | ? | 10/10 | new dim |
| **Operational Resilience** | crash-recovery-auditor | n/a (new) | ? | 10/10 | new dim |
| **Config Consistency** | config-consistency-validator | n/a (new) | ? | 10/10 | new dim |
| **Overall Average** | all | **3.3/10** | **?/10** | **10/10** | **?** |

> **Note:** The pre-fix column reflects the 8-agent audit run BEFORE the 72-issue bug-fix pass (2026-05-21).
> A score significantly higher than 3.3/10 in this audit is expected and reflects the fix pass working.
> If any dimension scores *lower* than the pre-fix baseline — that is a REGRESSION requiring immediate investigation.

## Step 3b — Known Issues Verification

The 2026-05-21 bug-fix pass resolved 72/76 issues. Agents should explicitly verify these critical categories were fixed:

| Category | Known Issue (pre-fix) | Agent Responsible |
|----------|-----------------------|-------------------|
| ICT Logic | No CHoCH/BOS distinction; London session = OVERNIGHT; no EQH/EQL | ict-logic-validator |
| Live/BT Parity | 4 critical divergences; MSS gate looser live; ACTIVE_CONFIG=BACKTEST | live-backtest-consistency-checker |
| Risk Mgmt | Drawdown formula off by 6 orders of magnitude; daily loss % inert | risk-management-auditor |
| Backtest | ~12 params tuned on ~34 signals; OOS window only ~14 signals | backtest-bias-detector |
| Adaptive | OGD unreachable thresholds; confidence loop; 2.5yr/token activation | adaptive-learning-code-reviewer |
| OGD Weights | SOL degenerate weight (0.508); zero live updates; static learning rate | ogd-weight-inspector |
| Templates | Tier C inert; DR confluence backwards for BUY; SMT bonus wrong-signed | template-tier-calibrator |
| Data | API error body uninspected; partial fetch resets stale clock; no 429 handling | data-pipeline-validator |

If an agent finds any of these **still present** → flag as **REGRESSION** (was fixed, now broken — highest priority).
If an agent finds a **new issue** not on this list → flag as **NEW CRITICAL/HIGH/MEDIUM/LOW**.

---

## Step 4 — Prior Art Check + Priority Action List

**Before listing any finding as actionable, read `docs/comprehensive/CROSS_REF.md` and classify each:**

| Classification | Action |
|----------------|--------|
| **REGRESSION** — was fixed, now broken | List as CRITICAL regardless of original severity |
| **NEW FINDING** — not in cross-ref | Full severity assessment, add to priority list |
| **KNOWN STRUCTURAL** — C2, C4, H23 | Note as acknowledged limit; do not add to action list |
| **STILL OPEN (SKIPPED)** — L2-L5 | Flag only if severity increased since last audit |
| **VERIFIED FIXED** — still correct | Note as "confirmed fixed" — no action needed |

> **Escalation protocol:** For any CRITICAL finding, follow `docs/comprehensive/PROTOCOL.md` — one issue at a time, test after each fix, full suite before advancing. Never fix multiple issues without validation between them.

Deduplicate findings across all agents. Order by severity then impact.

### CRITICAL — Must fix before switching to LIVE
- [ ] [Finding] — [Agent] — [File:Line] — [NEW FINDING / REGRESSION]

### HIGH — Fix before next backtest run or phase advance
- [ ] [Finding] — [Agent] — [File:Line]

### MEDIUM — Schedule for next session
- [ ] [Finding] — [Agent] — [File:Line]

### LOW — Backlog
- [ ] [Finding] — [Agent] — [File:Line]

### Cross-Domain Observations (from all agent reports)
Collect and list any "Cross-Domain Observations" sections from agent outputs here. Route each to the appropriate priority level or agent for follow-up.

### Acknowledged (Not Actionable)
- [List all VERIFIED FIXED, KNOWN STRUCTURAL, and SKIPPED items agents flagged — confirmed as non-issues]

## Step 5 — Executive Summary

Write a single paragraph covering:
- Overall system readiness verdict
- Whether it is safe to continue paper trading (yes/no and why)
- LIVE GO / NO-GO verdict with the specific blocking reason if NO-GO
- The single highest-impact improvement that would move the overall score the most

## Step 6 — Trend Comparison

After scoring all dimensions, compare to the previous audit report:

| Dimension | Previous | Current | Trend | Fixed Since Last? |
|-----------|----------|---------|-------|-------------------|
| ICT Logic | ? | ? | ↑/↓/─ | Yes/No/N-A |
| Live/BT Consistency | ? | ? | ↑/↓/─ | Yes/No/N-A |
| Risk Management | ? | ? | ↑/↓/─ | Yes/No/N-A |
| Backtest Validity | ? | ? | ↑/↓/─ | Yes/No/N-A |
| Adaptive Learning | ? | ? | ↑/↓/─ | Yes/No/N-A |
| OGD Weight Quality | ? | ? | ↑/↓/─ | Yes/No/N-A |
| Template Calibration | ? | ? | ↑/↓/─ | Yes/No/N-A |
| Data Pipeline | ? | ? | ↑/↓/─ | Yes/No/N-A |
| **Overall** | ? | ? | ↑/↓/─ | — |

Also check: how many CRITICAL issues from last audit are now resolved? How many are still open?

## Step 7 — Update Memory

After completing the audit, update the project memory file at:
`C:\Users\User\.claude\projects\c--Users-User-Desktop-TradeAI\memory\project_goal_10_10.md`

Update the "Current Scores" table with the new scores from this audit and today's date. This ensures future sessions start with an accurate baseline.

---

## Save This Run

**1. Save dated report** to:
`C:\Users\User\Desktop\TradeAI\.claude\reports\tradeai-audit\[YYYY-MM-DD].md`

Include: all dimension scores, full priority action list, trend comparison table, GO/NO-GO verdict, executive summary.

**2. Append to history log:**
`C:\Users\User\Desktop\TradeAI\.claude\reports\HISTORY.md`

Format (one line):
```
[YYYY-MM-DD] | tradeai-audit | overall=[X/10] | CRITICAL=[n] HIGH=[n] | [GO/NO-GO] | [one-line summary]
```
