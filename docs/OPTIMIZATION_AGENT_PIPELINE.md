# Optimization Agent Pipeline — 3-Agent Flow (Operator-Driven)

**Status:** EXPLORER + OPTIMIZER shipped (2026-05-23). ANALYZER pending.
**Sibling system:** [Autonomous Explorer](AUTONOMOUS_EXPLORER_DESIGN.md) — nightly self-driving search, design APPROVED 2026-05-24. The two systems COEXIST:
- This 3-agent flow handles **ad-hoc, operator-defined** experiments (e.g., "test these 5 hypotheses I came up with").
- Autonomous explorer handles **standing background search** (e.g., "explore the parameter space every night while I sleep").

This document defines the **3-agent separation-of-concerns pipeline** for **operator-driven** TradeAI strategy optimization. It's the architectural answer to: "how do we test patterns without auto-applying them, analyze them statistically across cycles, and promote only those that pass robustness checks?"

For *autonomous* (self-driving, no operator input) exploration, see [`docs/AUTONOMOUS_EXPLORER_DESIGN.md`](AUTONOMOUS_EXPLORER_DESIGN.md).

---

## The Full Pipeline (proposed)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  1. EXPLORER  (test, log, revert)                  STATUS: SHIPPED      │
│        │                                                                  │
│        ↓                                                                  │
│  docs/exploration_runs/explorer_run_*.md          (raw data, many cycles)│
│        │                                                                  │
│        ↓                                                                  │
│  2. ANALYZER  (read cross-cycle, find robust patterns, recommend)        │
│        │                                                  STATUS: TODO   │
│        ↓                                                                  │
│  docs/exploration_runs/analyzer_report_*.md       (promotion candidates) │
│        │                                                                  │
│        ↓                                                                  │
│  3. OPTIMIZER  (apply specific patterns from analyzer's recommendations) │
│        │                                                  STATUS: SHIPPED│
│        ↓                                                                  │
│  data/signals.db updated, LIVE_CONFIG_KWARGS updated, Learned Patterns updated│
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Why This Design

The previous architecture had **one agent doing all three jobs** (backtest-optimizer):
- It TESTED patterns
- It DECIDED which to accept/reject
- It APPLIED accepted patterns

This created friction:
- When the operator wanted to **just explore** without committing, the optimizer would auto-apply or auto-stop on diminishing returns (Cycle Z, 2026-05-23).
- When the operator wanted to **cross-check patterns across cycles**, there was no place for that synthesis to happen.

Separation of concerns solves it:

| Agent | Job | Modifies live code? | Decision-making? |
|---|---|---|---|
| **Explorer** | TEST patterns | ❌ NO — always reverts | ❌ NO — log only |
| **Analyzer** | ANALYZE across cycles | ❌ NO — read-only | Recommends only |
| **Optimizer** | APPLY robust patterns | ✅ YES | Final accept/reject |

---

## Agent Definitions

### 1. EXPLORER — `backtest-explorer`

**File:** `.claude/agents/backtest-explorer.md`
**Invocation:**
```
Use the Task tool with subagent_type "backtest-explorer" to run all Tier 1 frequency experiments F-1 through F-11.
```

**What it does:**
- Snapshots baseline DB before starting (`scripts/snapshot_baseline.py`)
- Runs each hypothesis from Phase 1 / 1.5 / 1.6 / Phase 2 queues
- For each: change → backtest → log → **REVERT**
- Writes result table to `docs/exploration_runs/explorer_run_*.md`
- No ACCEPT/REJECT decisions
- No STOP conditions (runs until queue exhausted)

**What it produces:** A result table with one row per experiment showing CPCV WR, DSR, n, PF, OGD health. Plus a Final Summary listing "candidates for optimizer review" — but never promotes them.

### 2. ANALYZER — `backtest-pattern-analyzer` (TODO)

**File:** `.claude/agents/backtest-pattern-analyzer.md` (to be created after Cycle 1)
**Status:** Not yet built — will be designed against real explorer output data (not hypothetical).

**Planned behavior:**
- Read ALL `docs/exploration_runs/explorer_run_*.md` files (cross-cycle synthesis)
- Identify patterns that consistently improved metrics across cycles:
  - **Strong promote**: 3+ cycles agree, mean Δ(CPCV WR) > 0 AND mean Δ(n) ≥ 0
  - **Watchlist**: 2 cycles agree, needs more data
  - **Refused**: 1 cycle only OR contradicts known anti-pattern
- Token-specific patterns: token consistently behaves differently across cycles
- Pareto frontier map: (n, WR, DSR) tradeoff configs
- Output: `docs/exploration_runs/analyzer_report_YYYY-MM-DD.md` with promotion candidates

**What it does NOT do:**
- Never modifies code
- Never updates `data/signals.db`
- Never writes to Learned Patterns (that's the optimizer's job)
- Never applies changes

### 3. OPTIMIZER — `backtest-optimizer` (existing)

**File:** `.claude/agents/backtest-optimizer.md`
**Invocation (post-analyzer):**
```
Run the backtest-optimizer agent. Apply only the patterns flagged STRONG PROMOTE in the latest analyzer report.
```

**What changed in this flow:**
- Pre-pipeline: optimizer made its own discovery + acceptance decisions
- Post-pipeline: optimizer applies analyzer's specific recommendations, after cross-cycle validation
- Still maintains: STOP conditions, ACCEPT/REJECT gates, Learned Patterns table, baseline snapshots

---

## Recommended Cycle Schedule

| # | When | What Changes | Value |
|---|---|---|---|
| Cycle 1 | NOW (today) | Run-113 baseline, 0 paper signals | See data shape; identify obvious wins |
| (build analyzer) | After Cycle 1 (~30min) | Design against real output format | Pipeline complete |
| (run analyzer on Cycle 1) | Same day | Validates parsing logic | Tests analyzer code (not conclusions) |
| Cycle 2 | ~3-4 weeks later | After ~5-10 closed paper signals → OGD weights shifted | First cross-cycle comparison possible |
| Cycle 3 | ~6-8 weeks later | After ~15-20 closed paper signals | "2/3 cycles agree" → moderate confidence |
| Cycle 4 | ~3 months later | After ~30 closed paper signals | "3/4 cycles agree" → robust pattern |
| Cycle 5+ | every ~4-6 weeks | Ongoing paper-trade accumulation | Steady-state operation |

**Why cycles must be MEANINGFULLY DIFFERENT:**

Backtests are deterministic — same code + same data + same DB state = same result. Running explorer back-to-back produces identical reports. Cycles only add value when something underneath has changed. Natural drivers:

| Variance Source | Calendar Time |
|---|---|
| OGD weights shift (new paper signals close) | ~1-2 weeks per 5-10 signals |
| Optimizer applied changes (different baseline) | Manual — operator decides |
| OHLCV cache refetched (newer data, 24h TTL) | Daily, but only +1 day's worth |
| BACKTEST_DAYS rotates past old data | Weeks to months |

**Calendar estimate for 3 robust cycles:** ~2-3 months across paper trading.

---

## Promotion Logic (analyzer's planned rules)

| Tier | Criteria | Action |
|---|---|---|
| **STRONG PROMOTE** | 3+ cycles agree, mean Δ(CPCV WR) > 0 AND mean Δ(n) ≥ 0, no anti-pattern match | Optimizer should apply |
| **MODERATE PROMOTE** | 2 cycles agree, no anti-pattern match | Operator decides; analyzer flags |
| **WATCHLIST** | 1 cycle only, needs more data | Run additional cycles before deciding |
| **CONFIRMED ANTI-PATTERN** | 3+ cycles failed in same direction | Add to Learned Patterns anti-patterns |
| **CONTRADICTS LEARNED PATTERN** | Result conflicts with existing anti-pattern | Refused — note discrepancy for human review |
| **PARETO IMPROVEMENT** | Better on ALL of (n, WR, DSR) than baseline | Highest priority for optimizer |
| **PARETO LATERAL** | Better on some, worse on others (within tolerance) | Operator chooses based on risk preference |
| **PARETO DOMINATED** | Worse on all dimensions | Discard |

---

## Cross-References

- **Agent files:**
  - `.claude/agents/backtest-explorer.md` — explorer (shipped)
  - `.claude/agents/backtest-optimizer.md` — optimizer (shipped, updated to reference this pipeline)
  - `.claude/agents/backtest-pattern-analyzer.md` — analyzer (TODO)

- **Operational scripts:**
  - `scripts/snapshot_baseline.py` — mandatory pre-cycle DB snapshot
  - `python backtest.py` — the underlying engine all 3 agents use
  - `python monitoring.py --exit-on-crit` — OGD health check after each experiment

- **Data files:**
  - `docs/exploration_runs/explorer_run_*.md` — explorer output (raw data)
  - `docs/exploration_runs/analyzer_report_*.md` — analyzer output (recommendations)
  - `docs/optimization_experiments.md` — optimizer output (decisions + Learned Patterns)
  - `data/signals.db` — working DB (mutated only by optimizer + the backtest engine)
  - `data/snapshots/signals_baseline_runNNN_*.db` — immutable rollback targets

- **Memory references:**
  - `memory/project_run113_baseline_and_cycleZ.md` — Run-113 immutable baseline, dead-zone, DSR counting fix
  - `memory/feedback_workflow_protocol.md` — agent dispatch rules

---

## Status Tracker

| Component | Status | Date | Notes |
|---|---|---|---|
| Explorer agent (`backtest-explorer.md`) | ✅ SHIPPED | 2026-05-23 | Full Phase 0/1/2/3/4 protocol implemented |
| Snapshot script (`snapshot_baseline.py`) | ✅ SHIPPED | 2026-05-23 | Used by both explorer + optimizer |
| Optimizer agent (post-pipeline updates) | ✅ SHIPPED | 2026-05-23 | Phase 0a-pre added (mandatory snapshot); bad Phase 0e removed |
| DSR n_trials counting (FIX 1) | ✅ SHIPPED | 2026-05-23 | `config_hash` column + DISTINCT counting |
| DSR cross-config sr_trial_std (FIX 1 Part 2) | ✅ SHIPPED | 2026-05-23 | `scripts/compute_cross_config_sr_std.py` + bot_state persistence |
| **Cycle 1 explorer run** | ✅ COMPLETE | 2026-05-23 | `docs/exploration_runs/explorer_run_20260523_1105.md` — F-1..F-11 logged |
| **F-8 promotion via optimizer** | ✅ COMPLETE | 2026-05-23 | Run 128 = new baseline (n=46, CPCV=76.23%, DSR=100%) |
| **Paper trading start** | ⏳ PENDING | operator action | Start `crypto_alert.py` with VPN active |
| **Cycle 2 explorer run** | ⏳ DEFERRED | ~4 weeks post paper-trade start | After ~5-10 closed paper signals shift OGD state |
| **Analyzer agent design** | ⏳ DEFERRED | post-Cycle-2 | Build against real 2-cycle data, NOT hypothetical |
| **Analyzer agent implementation** | ⏳ DEFERRED | post-Cycle-2 | ~30min after Cycle 2 completes |
| **First analyzer report** | ⏳ DEFERRED | post-Cycle-2 | Cross-cycle synthesis (Cycle 1 + Cycle 2) |
| **First STRONG PROMOTE recommendation** | ⏳ DEFERRED | post-Cycle-3 | Statistical floor — 3+ cycle agreement |

---

## How to Resume This Work

When you come back to this:

1. **Read this file first** — it's the canonical pipeline reference.
2. **Check the Status Tracker** above to see where you left off.
3. **If Cycle 1 is done** (`docs/exploration_runs/explorer_run_*.md` exists):
   - Ask Claude: "Build the analyzer agent against the existing Cycle 1 output."
   - Claude will design the analyzer using actual data shape, not hypothetical.
4. **If Cycle 1 is NOT done yet**:
   - Run the explorer first: `Use the Task tool with subagent_type "backtest-explorer" to run all Tier 1 frequency experiments F-1 through F-11.`
   - Wait for it to complete (~20-30 min)
   - Then proceed to step 3.
5. **For Cycles 2+**: wait until meaningful state has changed (paper signals accumulated, OGD weights shifted, or baseline updated by optimizer). Then re-run the explorer with the same prompt.

---

## Last Updated

2026-05-23 — initial version created when explorer agent shipped (FIX 2 of Cycle Z aftermath).
