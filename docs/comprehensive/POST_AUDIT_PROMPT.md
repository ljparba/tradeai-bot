# Post-Audit Prompt

Use this prompt immediately after the comprehensive audit finishes and all files are saved.
This starts the one-issue-at-a-time fix loop.

---

## PROMPT A — Start Fix Loop (paste this right after audit completes)

```
The comprehensive audit is done and the files are saved.
Now begin the fix loop. Follow these exact steps:

STEP 1 — READ THE ACTIVE AUDIT
Open docs/comprehensive/INDEX.md and identify the active audit folder.
Open that folder's ISSUE_CHECKLIST.md.
Tell me:
- Total issue count by severity (CRITICAL / HIGH / MEDIUM / LOW)
- The full list of all issues (ID, severity, description, file)

STEP 2 — PICK THE FIRST ISSUE
Pick the first unchecked CRITICAL issue.
If no CRITICALs remain, pick the first unchecked HIGH.
Tell me which issue we are working on and why it was picked.

STEP 3 — BRAINSTORM ONLY (do not fix yet)
Spawn the correct specialist agent based on the issue domain:

  ICT logic (MSS, FVG, sweeps, killzone)  → ict-logic-validator
  Backtest bias / lookahead / overfitting  → backtest-bias-detector
  Live vs backtest inconsistency           → live-backtest-consistency-checker
  OGD / adaptive learning / weights        → adaptive-learning-code-reviewer
  Risk / position sizing / drawdown        → risk-management-auditor
  Binance API / data pipeline / candles    → data-pipeline-validator
  Cross-cutting / general system           → trading-system-auditor

The agent must answer these three questions:
1. What is the exact root cause?
2. What is the minimal surgical fix (which file, which line, what change)?
3. What other functionality could this fix accidentally affect?

STEP 4 — PRESENT AND WAIT
After the brainstorm agent finishes, present the findings to me clearly:
- Root cause (confirmed)
- Exact proposed fix
- Risk to other functionality
- Which smoke test will be run after

Then STOP. Do not apply the fix yet.
Wait for me to say "proceed" or "go" before touching any code.
```

---

## PROMPT B — Resume Next Session (paste at the start of a new session)

```
Resume the TradeAI comprehensive audit fix loop.

STEP 1 — CHECK WHERE WE LEFT OFF
Open docs/comprehensive/INDEX.md.
Find the Active Audit section — note the folder and "Resume From" field.
Open that folder's ISSUE_CHECKLIST.md.
Tell me:
- How many issues are resolved vs remaining
- Which issue we should resume from (first unchecked item by severity)
- A quick summary of what was fixed last session (from FIX_LOG.md)

STEP 2 — PICK THE NEXT ISSUE
Pick the next unchecked issue (highest severity first).
Tell me which issue it is and why.

STEP 3 — BRAINSTORM ONLY (do not fix yet)
Spawn the correct specialist agent based on the issue domain:

  ICT logic (MSS, FVG, sweeps, killzone)  → ict-logic-validator
  Backtest bias / lookahead / overfitting  → backtest-bias-detector
  Live vs backtest inconsistency           → live-backtest-consistency-checker
  OGD / adaptive learning / weights        → adaptive-learning-code-reviewer
  Risk / position sizing / drawdown        → risk-management-auditor
  Binance API / data pipeline / candles    → data-pipeline-validator
  Cross-cutting / general system           → trading-system-auditor

The agent must answer:
1. What is the exact root cause?
2. What is the minimal surgical fix (file, line, change)?
3. What other functionality could this fix accidentally affect?

STEP 4 — PRESENT AND WAIT
Present the brainstorm findings clearly.
Then STOP — wait for me to say "proceed" or "go" before touching any code.
```

---

## After Each Fix — What Claude Will Do Automatically

After you say "proceed" or "go", Claude will:

1. Apply the minimal surgical fix
2. Run the targeted smoke test for that issue type
3. Run the full 162-test suite
4. Run backtest only if signal logic changed
5. Log the fix in FIX_LOG.md (root cause, files changed, test results)
6. Mark the issue [x] in ISSUE_CHECKLIST.md
7. Update INDEX.md (Resolved count, Resume From)
8. Present the next issue and brainstorm — then STOP and wait again

You stay in control at every step. Nothing gets applied without your "proceed".
