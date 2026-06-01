---
name: parallel-work
description: Fan out N independent tasks through the implementer → 2 verifiers → fixer pattern. Use whenever the operator asks to do multiple changes in parallel, apply a list of fixes, implement several findings at once, or asks for "fan out", "parallel work", "implement and verify", "do these N", "work in parallel". Each task is implemented, adversarially verified by two domain-routed read-only auditor agents in parallel, and given exactly ONE fixer round if either verifier fails — otherwise it ships. Returns a per-task SHIPPED / NEEDS_OPERATOR table.
---

# parallel-work — Disciplined Multi-Agent Fan-Out

You are the orchestrator. The operator has asked you to do N independent things at once. Instead of hand-spawning agents, route the batch through the `parallel-fix-verify` workflow so every task gets the same discipline: implementer → 2 parallel verifiers → fixer (1 round) → return.

## Step 1 — Decompose the request into tasks

Read the operator's request and break it into `tasks: [{ id, description, domain, files? }]`.

- `id` — short slug (e.g. `t1`, `fix-ogd`, `tier-a`).
- `description` — full instruction for the implementer; include WHY plus any acceptance criteria.
- `domain` — one of: `strategy`, `backtest`, `config`, `risk`, `learning`, `infra`, `quality`. This picks which 2 verifiers run.
- `files` (optional) — known files in scope; helps the implementer.

**Cap: ≤8 tasks per invocation.** If the operator gave more, group them or do batches sequentially.

If domain is ambiguous, infer from the files involved:
- `ict_engine.py` / `crt_engine.py` / `strategy_*` → `strategy`
- `backtest.py` / `validation.py` → `backtest`
- `config.py` / `.env` / params → `config`
- `risk` / SL / sizing → `risk`
- `adaptive_engine.py` / `monitoring.py` / OGD → `learning`
- `crypto_alert.py` main loop / `heartbeat.py` / `state_store.py` / API clients → `infra`
- anything else (refactors, dead code, dashboard) → `quality`

## Step 2 — Pre-flight safety checks

Before invoking the workflow:

1. **Explorer guard (CLAUDE.md §13a).** Run:
   ```bash
   pgrep -fa "autonomous_explorer.py"
   ```
   If anything returns, ABORT with this message to the operator:
   > Autonomous explorer is running. Per CLAUDE.md §13a, I won't fan out code edits while it has a session active. Stop the explorer first (`sudo systemctl stop tradeai-explorer`) or pick non-code tasks (docs, dashboard HTML, scripts/ outside backtest+autonomous_explorer).

2. **Live-mode guard.** If any task description mentions flipping `EXECUTION_MODE=LIVE`, refuse — operator must do that manually.

3. **Anti-pattern preflight.** If any task description matches a confirmed anti-pattern from CLAUDE.md §7 (SWING_N≥3, MIN_RR≥2.0, FVG=LOW/MEDIUM, BACKTEST_DAYS=730, rejected tokens, WYCKOFF=strict, CRT_APPLY_QUALITY_GATES=1), refuse that task with a one-line citation.

## Step 3 — Invoke the workflow

Call the Workflow tool:

```
Workflow({
  name: 'parallel-fix-verify',
  args: { tasks: [ ... ] }
})
```

Optional: pass `args.verifierDomain` to force all tasks through the same verifier pair (override the per-task `domain` field). Use this only when the operator explicitly asks for it.

The workflow runs in the background — you will be notified when it completes via `<task-notification>`. While it runs, the operator can watch live progress with `/workflows`.

## Step 4 — Render the result

The workflow returns `{ summary, results }`. Render to the operator as:

| Task | Status | Verifier 1 | Verifier 2 | Fix round? |
|---|---|---|---|---|
| t1 | SHIPPED | PASS | PASS | no |
| t2 | SHIPPED | FAIL→PASS | PASS | yes |
| t3 | NEEDS_OPERATOR | FAIL→FAIL | PASS→FAIL | yes (exhausted) |

For any `NEEDS_OPERATOR` row, inline the remaining findings so the operator can decide whether to retry, escalate, or back out.

If `summary.failed > 0` (implement-failed or budget-skipped), call those out separately.

## Step 5 — Memory + history

If a task touched code that the operator will want to recall (a new pattern, a workaround), save a `feedback` or `project` memory per the auto-memory rules. Skip for routine fixes.

## Notes

- Fixer is capped at **1 round** by design. If both re-verifications still FAIL, the workflow returns `NEEDS_OPERATOR` instead of looping. Do not retry by re-invoking the same task — escalate to the operator.
- Use `isolation: 'worktree'` ONLY if the operator explicitly asks for isolated parallel edits to overlapping files. The default is shared working tree (faster).
- The workflow honors `budget.total` if set — it stops fanning out new tasks once `budget.remaining() < 100k` tokens.
