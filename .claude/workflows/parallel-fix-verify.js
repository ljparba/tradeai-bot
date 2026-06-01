export const meta = {
  name: 'parallel-fix-verify',
  description: 'Fan out N tasks; each runs implementer → 2 parallel verifiers → fixer (1 round) → return.',
  whenToUse: 'When the operator asks to do several independent changes in parallel with adversarial verification.',
  phases: [
    { title: 'Implement', detail: 'one implementer agent per task' },
    { title: 'Verify',    detail: 'two read-only verifiers in parallel per task' },
    { title: 'Fix',       detail: 'single fix round if either verifier returned FAIL' },
  ],
}

// ── Verifier routing table ─────────────────────────────────────────────────
const VERIFIER_MAP = {
  strategy: ['ict-logic-validator',              'live-backtest-consistency-checker'],
  backtest: ['backtest-bias-detector',           'honest-metrics-reviewer'],
  config:   ['config-consistency-validator',     'live-backtest-consistency-checker'],
  risk:     ['risk-management-auditor',          'trading-system-auditor'],
  learning: ['adaptive-learning-reviewer',       'ogd-weight-inspector'],
  infra:    ['crash-recovery-auditor',           'data-pipeline-validator'],
  quality:  ['professional-code-quality-reviewer', 'trading-system-auditor'],
}

const DEFAULT_DOMAIN = 'quality'
const MAX_TASKS = 8
const FIXER_ROUNDS = 1

// ── Schemas ────────────────────────────────────────────────────────────────
const IMPL_SCHEMA = {
  type: 'object',
  required: ['summary', 'filesChanged'],
  properties: {
    summary:      { type: 'string' },
    filesChanged: { type: 'array', items: { type: 'string' } },
    notes:        { type: 'string' },
  },
}

const VERIFY_SCHEMA = {
  type: 'object',
  required: ['verdict', 'findings'],
  properties: {
    verdict:  { enum: ['PASS', 'FAIL'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'description'],
        properties: {
          severity:    { enum: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] },
          description: { type: 'string' },
          location:    { type: 'string' },
        },
      },
    },
    reason: { type: 'string' },
  },
}

const FIX_SCHEMA = {
  type: 'object',
  required: ['summary', 'filesChanged', 'addressed'],
  properties: {
    summary:      { type: 'string' },
    filesChanged: { type: 'array', items: { type: 'string' } },
    addressed:    { type: 'array', items: { type: 'string' } },
    notes:        { type: 'string' },
  },
}

// ── Safety context injected into every implementer/fixer prompt ───────────
const SAFETY_PREAMBLE = `
You are working inside the TradeAI repo at /home/tradeai/TradeAI/.
CLAUDE.md operational constraints (NON-NEGOTIABLE):
- NEVER flip EXECUTION_MODE to LIVE. NEVER push to public repos.
- NEVER re-test confirmed anti-patterns: ICT_SWING_N>=3, ICT_MIN_RR_GATE>=2.0,
  FVG_MIN_QUALITY=LOW/MEDIUM, BACKTEST_DAYS=730, tokens SOL/DOT/NEAR/SUI/LTC,
  WYCKOFF_PHASE_FILTER=strict, CRT_APPLY_QUALITY_GATES=1.
- NEVER add vectorbt / freqtrade / FinRL / hummingbot.
- NEVER modify signals.db directly; never delete data/snapshots/.
- Operator runs CRT-only paper soak; do NOT flip ENABLE_5M_SWEEP=1.
- If autonomous_explorer.py is running, do NOT run backtest / restart tradeai /
  edit ict_engine.py | config.py | backtest.py | crt_engine.py.
Return ONLY the schema-required object. Do not include extra prose.
`.trim()

// ── Helpers ────────────────────────────────────────────────────────────────
function pickVerifiers(task, override) {
  const domain = (override || task.domain || DEFAULT_DOMAIN).toLowerCase()
  return VERIFIER_MAP[domain] || VERIFIER_MAP[DEFAULT_DOMAIN]
}

function summarizeFindings(verifications) {
  const all = []
  for (const v of verifications) {
    if (!v) continue
    for (const f of (v.findings || [])) {
      all.push(`- [${f.severity}] ${f.description}${f.location ? ' @ ' + f.location : ''}`)
    }
  }
  return all.length ? all.join('\n') : '(no specific findings provided)'
}

// ── Validate args ──────────────────────────────────────────────────────────
const tasks = Array.isArray(args?.tasks) ? args.tasks : null
if (!tasks || tasks.length === 0) {
  throw new Error('parallel-fix-verify: args.tasks must be a non-empty array')
}
if (tasks.length > MAX_TASKS) {
  throw new Error(`parallel-fix-verify: max ${MAX_TASKS} tasks per invocation (got ${tasks.length}); chunk and re-invoke`)
}

const verifierOverride = args?.verifierDomain
log(`parallel-fix-verify: ${tasks.length} task(s), fixer-rounds=${FIXER_ROUNDS}, max-fanout=${MAX_TASKS}`)

// ── Pipeline: implement → verify → fix (single round) ──────────────────────
const results = await pipeline(
  tasks,

  // Stage 1: implementer
  async (task, _orig, idx) => {
    if (budget.total && budget.remaining() < 100_000) {
      log(`task[${idx}] skipped: token budget exhausted`)
      return { task, status: 'SKIPPED_BUDGET' }
    }
    const tid = task.id || `t${idx}`
    const prompt = [
      SAFETY_PREAMBLE,
      '',
      `Task ${tid} (domain=${task.domain || DEFAULT_DOMAIN}): ${task.description}`,
      task.files?.length ? `Files in scope: ${task.files.join(', ')}` : '',
      '',
      'Implement the change. Use Read/Edit/Write/Bash as needed.',
      'Return the implementation summary + list of files actually changed.',
    ].filter(Boolean).join('\n')

    const impl = await agent(prompt, {
      label: `implement:${tid}`,
      phase: 'Implement',
      schema: IMPL_SCHEMA,
    })
    return { task, tid, impl }
  },

  // Stage 2: 2 verifiers in parallel
  async ({ task, tid, impl, status }) => {
    if (status === 'SKIPPED_BUDGET') return { task, tid, status }
    if (!impl) return { task, tid, status: 'IMPLEMENT_FAILED' }

    const [v1Type, v2Type] = pickVerifiers(task, verifierOverride)
    const verifyPrompt = [
      `An implementer just made the following change for task ${tid}:`,
      `  Summary: ${impl.summary}`,
      `  Files changed: ${(impl.filesChanged || []).join(', ') || '(none reported)'}`,
      impl.notes ? `  Notes: ${impl.notes}` : '',
      '',
      `Original task description: ${task.description}`,
      '',
      'Run your standard audit against the current state of those files.',
      'Return verdict=PASS only if you find no CRITICAL or HIGH severity issues',
      'introduced by this change. Otherwise verdict=FAIL with specific findings.',
    ].filter(Boolean).join('\n')

    const [v1, v2] = await parallel([
      () => agent(verifyPrompt, {
        label:     `verify:${tid}:${v1Type}`,
        phase:     'Verify',
        agentType: v1Type,
        schema:    VERIFY_SCHEMA,
      }),
      () => agent(verifyPrompt, {
        label:     `verify:${tid}:${v2Type}`,
        phase:     'Verify',
        agentType: v2Type,
        schema:    VERIFY_SCHEMA,
      }),
    ])
    return { task, tid, impl, v1, v2, verifiers: [v1Type, v2Type] }
  },

  // Stage 3: fixer (only if either verifier FAILed)
  async ({ task, tid, impl, v1, v2, verifiers, status }) => {
    if (status) return { taskId: tid, status, task }

    const fails = [v1, v2].filter(v => v && v.verdict === 'FAIL')
    if (fails.length === 0) {
      log(`task[${tid}] PASS — both verifiers cleared`)
      return {
        taskId:    tid,
        status:    'SHIPPED',
        task:      task.description,
        impl,
        verifiers: { types: verifiers, v1, v2 },
      }
    }

    log(`task[${tid}] FAIL — spawning fixer (1 round)`)
    const fixPrompt = [
      SAFETY_PREAMBLE,
      '',
      `Task ${tid}: ${task.description}`,
      `Implementer summary: ${impl.summary}`,
      `Files changed: ${(impl.filesChanged || []).join(', ')}`,
      '',
      'Two verifiers reviewed the change. At least one returned FAIL.',
      'Findings to address:',
      summarizeFindings([v1, v2]),
      '',
      'Apply targeted fixes for each finding. Do NOT introduce new behavior',
      'beyond what the original task required. Return a list of which findings',
      'you addressed (by description).',
    ].join('\n')

    const fix = await agent(fixPrompt, {
      label: `fix:${tid}`,
      phase: 'Fix',
      schema: FIX_SCHEMA,
    })

    // Re-verify once with the same two verifiers
    const reverifyPrompt = [
      `A fixer just applied changes for task ${tid}.`,
      `Fixer summary: ${fix?.summary || '(none)'}`,
      `Files changed: ${(fix?.filesChanged || []).join(', ') || '(none)'}`,
      `Addressed: ${(fix?.addressed || []).join('; ') || '(none reported)'}`,
      '',
      'Re-audit. Return PASS only if no CRITICAL/HIGH remain.',
    ].join('\n')

    const [v1b, v2b] = await parallel([
      () => agent(reverifyPrompt, {
        label:     `reverify:${tid}:${verifiers[0]}`,
        phase:     'Verify',
        agentType: verifiers[0],
        schema:    VERIFY_SCHEMA,
      }),
      () => agent(reverifyPrompt, {
        label:     `reverify:${tid}:${verifiers[1]}`,
        phase:     'Verify',
        agentType: verifiers[1],
        schema:    VERIFY_SCHEMA,
      }),
    ])

    const stillFailing = [v1b, v2b].filter(v => v && v.verdict === 'FAIL')
    const shipped = stillFailing.length === 0

    return {
      taskId:    tid,
      status:    shipped ? 'SHIPPED' : 'NEEDS_OPERATOR',
      task:      task.description,
      impl,
      verifiers: { types: verifiers, initial: { v1, v2 }, postFix: { v1: v1b, v2: v2b } },
      fix,
    }
  },
)

const summary = {
  total:          tasks.length,
  shipped:        results.filter(r => r && r.status === 'SHIPPED').length,
  needsOperator:  results.filter(r => r && r.status === 'NEEDS_OPERATOR').length,
  failed:         results.filter(r => r && (r.status === 'IMPLEMENT_FAILED' || r.status === 'SKIPPED_BUDGET')).length,
}
log(`parallel-fix-verify done: shipped=${summary.shipped} needsOperator=${summary.needsOperator} failed=${summary.failed}`)

return { summary, results }
