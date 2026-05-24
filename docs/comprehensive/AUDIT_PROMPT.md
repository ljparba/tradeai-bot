# TradeAI Comprehensive Audit Prompt

Copy the full block below and paste it to Claude Code at the start of any audit session.
Update [TODAY'S DATE] before pasting. Nothing else needs to be updated — ever.

---

## When to Run This Audit

| Trigger | Audit Type |
|---|---|
| After any multi-file code change | Full audit — all 7 agents |
| After fixing CRITICAL or HIGH issues | Full audit |
| Monthly health check | Full audit |
| Before switching PAPER → LIVE | Full audit (mandatory) |
| Single module change only | Run only the relevant agent (see PROTOCOL.md) |

---

## The Prompt (copy everything between the lines)

---

Act as a world-class AI systems architect, quantitative trading expert, ICT strategy specialist, and senior software engineer with 50+ years of combined experience in algorithmic trading, adaptive AI systems, machine learning, risk management, and large-scale production systems. You have led projects for top hedge funds, fintech companies, and enterprise AI systems.

Treat this project as if it is your own company product that will eventually serve thousands to millions of users and manage high-stakes trading decisions. Your responsibility is not to be polite — your responsibility is to find weaknesses, risks, inconsistencies, hidden bugs, architectural flaws, unrealistic assumptions, scalability problems, strategy issues, and long-term failure points.

Do NOT assume things are correct. Challenge everything. Investigate deeply. Trace logic from start to finish. Think like a hedge-fund CTO and principal AI architect performing a pre-production audit.

════════════════════════════════════════════════════════════
PROJECT IDENTITY — TradeAI
════════════════════════════════════════════════════════════

Project : TradeAI — ICT-based crypto signal bot (signal-only, no auto-execution)
Goal    : Achieve 10/10 across all audit dimensions for enterprise production readiness

Key files (read all of these before starting):
  crypto_alert.py     → live/paper signal generation (main loop)
  ict_engine.py       → all ICT detection logic (sweeps, MSS, FVG, DR, SMT)
  backtest.py         → backtesting engine
  adaptive_engine.py  → OGD online gradient descent adaptive learning
  tracker.py          → web dashboard (localhost:8888)
  TradeAI.db          → SQLite database (all signals, trades, weights)

════════════════════════════════════════════════════════════
STEP 0 — READ CURRENT STATE FROM SOURCE (do this before anything else)
════════════════════════════════════════════════════════════

Do NOT use any hardcoded assumptions about config, tokens, or performance.
Read the actual current state from these files:

  Current config and portfolio
    → backtest.py       : read BACKTEST_CONFIG and ACTIVE_CONFIG blocks
    → crypto_alert.py   : read LIVE_CONFIG and BINANCE_TOKENS list

  Backtest history and latest validated baseline
    → docs/optimization_experiments.md : read the most recent accepted run

  Previous fix history (what has already been fixed)
    → docs/comprehensive/audit_*/FIX_LOG.md : read the most recent one

  Previous audit scores (baseline for comparison)
    → docs/comprehensive/INDEX.md
    → docs/comprehensive/audit_*/AUDIT_REPORT.md : read the most recent one

  Current test suite count
    → run: pytest tests/ --collect-only -q

After reading, confirm what you found:
  - Current EXECUTION_MODE (PAPER or LIVE)
  - Current token list (BINANCE_TOKENS)
  - Current ACTIVE_CONFIG parameter values
  - Most recent validated backtest baseline (WR, z, n, WF gap)
  - Previous audit scores per dimension
  - Number of tests currently in suite

════════════════════════════════════════════════════════════
KNOWN RECURRING PATTERNS — ALWAYS CHECK THESE FIRST
════════════════════════════════════════════════════════════

These patterns have caused real bugs in this codebase before.
Verify each one still holds regardless of recent changes:

1. LOOKAHEAD BIAS IN BACKTEST SLICES
   Wrong:   data[idx0 : i+1]  ← includes the forming (current) bar
   Correct: data[idx0 : i]    ← excludes forming bar
   Check every slice operation in backtest.py without exception.

2. SESSION ATTRIBUTION TIMESTAMP
   Session/killzone must be classified using the detection bar timestamp (ts.hour),
   NOT the entry bar timestamp (ts_entry_ms).
   Check all killzone classifiers and session attribution logic.

3. FAIL-CLOSED SAFETY GATE DEFAULTS
   All .get("key", DEFAULT) safety gates must default to BLOCKED / 0 / False.
   A default of 1 / True / allowed means a missing config silently bypasses safety.
   Check every regime gate, config lookup, and signal filter.

4. SQLITE UTC DATE COMPARISONS
   All date() comparisons against UTC timestamps must use date('now', 'utc').
   date('now') returns local time and causes off-by-one date errors.
   Check all SQL queries in adaptive_engine.py, tracker.py, and backtest.py.

5. OGD BOOTSTRAP BIAS
   If bootstrap seed data is SELL-biased (>55% SELL), dr_location weight
   inflates to degenerate levels and corrupts live weight state.
   After any re-bootstrap: verify health_check() runs and is_degenerate=False
   for all tokens.

════════════════════════════════════════════════════════════
REVIEW OBJECTIVES
════════════════════════════════════════════════════════════

Perform a complete audit of:
  - Entire project architecture
  - All source code
  - Folder structure and modularity
  - Database design and integrity
  - Trading strategy logic and ICT confluences
  - Adaptive learning system and OGD behavior
  - Signal generation pipeline (end to end)
  - Live vs backtest behavior and consistency
  - Risk management and position controls
  - Performance optimization and scalability
  - Website tracker and dashboard accuracy
  - Config system design
  - Data collection pipeline and API reliability
  - All documentation and MD reports
  - Existing implementation phases
  - Future scalability and production readiness

Required mindset:
  - Check if implementation truly matches documentation
  - Check if documentation matches actual code behavior
  - Verify whether features are truly implemented or only claimed
  - Detect fake completeness and false assumptions
  - Find hidden technical debt
  - Find areas where future failures can happen

════════════════════════════════════════════════════════════
SPECIFIC DEEP CHECKS
════════════════════════════════════════════════════════════

── 1. ARCHITECTURE REVIEW ──────────────────────────────────

Analyze:
  - System design and component interactions
  - Modularity and coupling between files
  - Scalability under increasing signal volume
  - Maintainability and future expansion risk
  - Hidden bottlenecks and single points of failure
  - Error propagation paths

Questions to answer:
  - Will this architecture survive 10× signal volume?
  - Are there hidden design flaws that will hurt at scale?
  - Which components will become problematic first?
  - Is generate_signal() too monolithic? Should it be broken into sub-functions?
  - Is crash alerting sufficient for production use?

── 2. TRADING STRATEGY AUDIT ───────────────────────────────

Act as a profitable ICT trader with 50+ years experience.

Read the current active config from backtest.py and crypto_alert.py first.
Then inspect the exact signal flow — trace from market data arrival to signal firing:

  - Liquidity sweep detection (is the sweep confirmed before entry is considered?)
  - MSS sequence guard (is mss_bar > disp_bar+1 enforced in all paths?)
  - Displacement bar quality (is displacement magnitude validated?)
  - FVG detection and mitigation check (is every gap checked for closure before use?)
  - FVG quality filter (verify the current quality level in config — what gets through?)
  - Retracement into FVG (is the entry zone still valid at time of detection?)
  - iFVG bonus spatial gate (is the spatial proximity threshold enforced correctly?)
  - SMT divergence (confirmed swings only, not raw min/max?)
  - DR classification and EQUILIBRIUM gate (is the gate condition correct?)
  - 4H bias gate (read current setting from config — is it intentional and safe?)
  - Confluence scoring (what is the minimum score threshold to fire a signal?)
  - Killzone timing (read current liquid_hours from config — all classified correctly?)
  - Regime detection (read current blocked_regimes from config — all reliably identified?)
  - DOW filter (read current blocked_weekdays from config — centralized in StrategyConfig?)

Determine:
  - What EXACTLY causes a signal to trigger? (trace the full logic path)
  - How many confluences are required at minimum?
  - Must confluences happen in strict sequence? Is sequence enforced?
  - Where is the weakest link in the signal chain?
  - Any overfitting risk from the current filter combination?
  - Any unrealistic assumptions about entry timing or fill price?

── 3. ADAPTIVE LEARNING AUDIT ──────────────────────────────

Act as an expert in reinforcement learning, online learning, and adaptive systems.

Read adaptive_engine.py fully before answering. Then inspect the OGD engine:

  - Is _trigger_weight_update() actually called after every closed trade?
  - Does it correctly JOIN the results table to fetch profit_pct?
    (This was a CRITICAL bug — verify the fix is still intact)
  - Is the learning rate decay schedule implemented correctly?
    (Read the actual schedule from adaptive_engine.py — do not assume values)
  - Is OGD_MIN_SAMPLES enforced? (Read current value from code)
    Engine must not activate before this threshold of closed signals.
  - Is the backtest weights table fully isolated from the live weights table?
    No cross-contamination between backtest bootstrap and live OGD.
  - Is health_check() called? Is is_degenerate=False verified for all tokens?
  - Is the P&L reward proportional to profit_pct or just binary win/loss?
  - Can the OGD engine experience catastrophic forgetting from bad trade streaks?
  - Is there any feedback loop that could cause weight oscillation?
  - Is bias accumulation from SELL-heavy bootstrap data prevented?
  - Does the adaptive engine genuinely improve signal selection over time?
  - Or is it only adjusting numbers without real measurable improvement?

── 4. BACKTEST vs LIVE REALITY AUDIT ───────────────────────

Read backtest.py fully. Then inspect every assumption:

  - Lookahead bias: every data slice must exclude the forming bar (see Pattern 1 above)
  - Walk-forward split: is OOS data truly unseen during parameter selection?
  - Regime detection: does it use any future data to classify the current bar?
  - Candle close assumption: does the backtest fill at close or at open of next bar?
  - Entry timing: is the ENTRY_WINDOW (read from config) applied correctly?
  - Fee simulation: read ROUND_TRIP_COST_PCT from config — does this match realistic live fees?
  - Slippage: is any slippage modeled? Is zero-slippage realistic for the current token list?
  - Signal frequency: is the expected n/year realistic given the full filter stack?
  - Win rate: does the current WR suggest overfitting? Compare in-sample vs OOS carefully.
  - Walk-forward gap: is the current WF gap within acceptable range?
    (Read from docs/optimization_experiments.md — acceptable threshold is <10%)

── 5. DATABASE + WEBSITE TRACKER AUDIT ─────────────────────

Trace every displayed metric from screen → API → database → actual value.
Read tracker.py fully. Check every tab in the dashboard:

  - Do displayed win rates match the actual closed trades in TradeAI.db?
  - Are partial trades (PARTIAL result) counted correctly (as 0.5 win)?
  - Are open signals properly excluded from WR calculation?
  - Are any fields stale (inserted once and never updated)?
  - PRAGMA foreign_keys=ON — set in ALL _connect() calls across all files?
  - DB indexes — are all performance-critical columns indexed?
  - Are there any SQL queries using date('now') without 'utc' modifier? (see Pattern 4)
  - Read current BINANCE_TOKENS from crypto_alert.py — does the tracker reflect exactly
    those tokens and no others (including no removed tokens)?
  - Are correlation queries referencing only the current active token list?

── 6. RISK MANAGEMENT AUDIT ────────────────────────────────

Read both BACKTEST_CONFIG and LIVE_CONFIG from the actual files.
Then inspect all risk controls end to end:

  - Drawdown formula: verify it uses a single cumulative equity curve,
    not separate peak and trough tracking (this was a CRITICAL bug — verify fix holds)
  - Is the drawdown gate actually reachable now? What exact threshold triggers it?
  - Position sizing: does the formula use YOUR_CAPITAL env var correctly?
  - Portfolio limits: read MAX_OPEN_POSITIONS and MAX_SAME_DIRECTION from config.
    Are they enforced correctly for PAPER mode vs LIVE mode?
  - Stop-loss bounds: read MAX_SL_PCT and MIN_SL_PCT from config.
    Are both bounds enforced before a signal fires?
  - R:R gate: read MIN_TP1_MULT and ICT_MIN_RR_GATE from config.
    Are both checked before a signal fires?
  - LIVE mode kill switch: LIVE_MODE_CONFIRMED=YES env var — is it impossible to bypass?
  - Duplicate signal guard: active and effective?
  - Can this system survive a 10-consecutive-loss streak without catastrophic drawdown?
  - What is the maximum possible loss in a single session under worst-case conditions?

── 7. DOCUMENTATION AUDIT ──────────────────────────────────

Read ALL markdown files in docs/ and its subdirectories.
Do not skip any file.

For each document, verify:
  - Do documentation claims match what the code actually does right now?
  - Are any features claimed as complete but not yet implemented in code?
  - Are any reports outdated relative to the fixes recorded in the latest FIX_LOG.md?
  - Are there false assumptions or misleading performance claims?
  - Is optimization_experiments.md accurate and consistent with backtest.py config?
  - Does docs/comprehensive/INDEX.md reflect the actual current audit state?

════════════════════════════════════════════════════════════
STEP 1 — RUN ALL 7 AGENTS IN PARALLEL
════════════════════════════════════════════════════════════

Spawn all agents simultaneously. Do not wait for one before starting others.
Each agent must complete Step 0 (read current state) before beginning its review.

  Agent 1 : ict-logic-validator
  Agent 2 : backtest-bias-detector
  Agent 3 : live-backtest-consistency-checker
  Agent 4 : adaptive-learning-code-reviewer
  Agent 5 : risk-management-auditor
  Agent 6 : data-pipeline-validator
  Agent 7 : live-deployment-readiness-checker

Each agent covers the Known Recurring Patterns and its relevant deep check section.

════════════════════════════════════════════════════════════
STEP 2 — OUTPUT FORMAT (per issue found)
════════════════════════════════════════════════════════════

SEVERITY          : CRITICAL / HIGH / MEDIUM / LOW
ID                : C1 / H1 / M1 / L1  (sequential per severity level)
Agent             : which agent found it
Problem           : what is wrong — be specific, cite file and line number
File              : filename.py:line_number
Root Cause        : why it happens
Why Dangerous     : what breaks, fails silently, or is at risk if not fixed
Suggested Fix Direction : high-level direction only — no code

════════════════════════════════════════════════════════════
STEP 3 — REQUIRED OUTPUT SECTIONS
════════════════════════════════════════════════════════════

After all agents complete, provide ALL of the following sections in order:

── EXECUTIVE SUMMARY ───────────────────────────────────────

State the current scores you found from Step 0 (previous audit baseline).
Then provide your updated scores based on what you actually found in the code today.

  Dimension                    | Previous | Current | Target
  -----------------------------|----------|---------|-------
  Overall                      |          |         | 10/10
  Trading Strategy Logic       |          |         | 10/10
  ICT Implementation           |          |         | 10/10
  Adaptive Learning            |          |         | 10/10
  Backtest Validity            |          |         | 10/10
  Live vs Backtest Consistency |          |         | 10/10
  Risk Management              |          |         | 10/10
  Architecture & Code Quality  |          |         | 10/10
  Database & Dashboard         |          |         | 10/10
  Documentation                |          |         | 10/10
  Production Readiness         |          |         | 10/10

For each dimension scoring below 8/10: state exactly what is missing to reach 10/10.

── CRITICAL PROBLEMS ───────────────────────────────────────

For each CRITICAL issue:
  Severity        : CRITICAL
  ID              : C_
  Problem         : [specific description — cite file and line]
  Why Dangerous   : [exact consequences if left unfixed]
  Recommended Fix : [direction — not code]

── HIGH PROBLEMS ───────────────────────────────────────────

Same format as CRITICAL for each HIGH issue.

── UNIFIED ISSUE LIST ──────────────────────────────────────

All issues from all agents, sorted by severity.
Format: ID | Severity | Agent | Short description | File:line

Issue count: CRITICAL: _ | HIGH: _ | MEDIUM: _ | LOW: _ | TOTAL: _

── HIDDEN RISKS ────────────────────────────────────────────

Issues that do not cause immediate failure but will cause problems in production.
Focus on: time bombs, edge cases under live conditions, race conditions,
accumulation effects, bad market scenarios, compounding failures.

── MISSING COMPONENTS ──────────────────────────────────────

Features claimed in documentation but not fully implemented in code.
Features needed for production that are not present at all.

── ARCHITECTURE WEAKNESSES ─────────────────────────────────

Design-level problems that will limit scalability, maintainability,
or reliability as the system grows toward production.

── TRADING STRATEGY WEAKNESSES ─────────────────────────────

ICT logic gaps, unrealistic assumptions, overfitting risks,
edge cases in signal generation that could produce bad signals in live conditions.

── ADAPTIVE LEARNING WEAKNESSES ────────────────────────────

OGD issues, weight behavior problems, learning that may not represent
genuine improvement, contamination risks, convergence problems.

── DATABASE + TRACKER PROBLEMS ─────────────────────────────

Data mismatches, stale fields, wrong calculations, display errors,
queries that could silently return wrong values.

── DOCUMENTATION INCONSISTENCIES ───────────────────────────

Documents that claim things the code does not do.
Reports that are outdated relative to the current codebase state.
Misleading or unverifiable performance claims.

── IMMEDIATE FIX PRIORITY LIST ─────────────────────────────

Rank ALL issues in exact order of urgency.
Format: Rank | ID | Severity | One-line description | Estimated impact if fixed

── LONG-TERM RECOMMENDATIONS ───────────────────────────────

What architectural, strategic, or learning improvements are needed
for this system to genuinely reach 10/10 across all dimensions.
Be specific — reference actual code, actual files, actual behavior.
Do not give generic advice. Do not give praise.

════════════════════════════════════════════════════════════
STEP 4 — SAVE TO DOCS
════════════════════════════════════════════════════════════

After completing the full output:

1. Create folder  : docs/comprehensive/audit_[TODAY'S DATE]/
2. Save full output → docs/comprehensive/audit_[TODAY'S DATE]/AUDIT_REPORT.md
3. Fill checklist  → docs/comprehensive/audit_[TODAY'S DATE]/ISSUE_CHECKLIST.md
                     (copy from docs/comprehensive/_template/ISSUE_CHECKLIST.md)
4. Create fix log  → docs/comprehensive/audit_[TODAY'S DATE]/FIX_LOG.md
                     (copy from docs/comprehensive/_template/FIX_LOG.md — leave empty)
5. Update index    → docs/comprehensive/INDEX.md
                     Set Active Audit to this folder
                     Fill issue count (C / H / M / L)
                     Set Resume From to the first CRITICAL issue ID

════════════════════════════════════════════════════════════
AUDIT ONLY — DO NOT FIX ANYTHING
════════════════════════════════════════════════════════════

This session is for audit and documentation only.
Do not modify any source file.
Do not apply any fix.
Report back when all steps are complete and all files are saved.

TODAY'S DATE: [YYYY-MM-DD]

---

## After the Audit Completes

Open [POST_AUDIT_PROMPT.md](POST_AUDIT_PROMPT.md) and use **PROMPT A** to begin the fix loop.
