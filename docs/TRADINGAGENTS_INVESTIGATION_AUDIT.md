# TradingAgents Investigation Report — Audit

**Audit date:** 2026-05-22
**Auditor:** Senior trading-systems architect (Claude Sonnet 4.6)
**Audit target:** `docs/TRADINGAGENTS_INVESTIGATION_REPORT.md` (dated 2026-05-18)
**Method:** Six-pass review — claim verification → fit-for-purpose re-scoring → gap analysis → conflict analysis → adoption plan → second-order findings

---

## 1. TL;DR

1. **The report's premise that "we currently call Claude directly" is false.** [requirements.txt](requirements.txt) lists only `requests>=2.31.0`. There is no `anthropic`, `openai`, `langchain`, or `pydantic` import anywhere in our codebase. Every LLM-based pattern in the report is **greenfield infrastructure work**, not a port.

2. **Our bottleneck is frequency (37 sigs/yr ceiling) and time-to-live (need N≥30 paper closes ≈ 12 months at 2.6/month). Every LLM REJECTION filter the report proposes makes both worse.** A bull/bear debate that rejects 30% of signals turns 37/yr into 26/yr → paper collection extends from 12 to 18 months → LIVE further delayed.

3. **Adopt now (low risk, no rejection logic): backtest checkpointing (3.9) + signal explanation generator (3.10) only if it runs after Telegram, not as a gate.** Defer everything else until after N≥30 paper closes are collected.

4. **Drop entirely: LLM bull/bear debate (3.1), LLM risk debate (3.4), final-signal-approver (Pattern 5).** These break our deterministic live-vs-backtest invariant (a core safety property — the WR=81% / z=+4.15 baseline is only valid because backtest and live use identical logic). Once an LLM votes inside the signal path, backtest WR no longer predicts live WR.

5. **Biggest hidden risk the report missed: data egress / compliance.** Every signal sent through an external LLM API exposes pre-public trade plans, account balance, P&L history, and token positions to a third party. The report does not flag this. For a single-user paper bot this is "fine"; if you ever monetize or share this tool, it becomes a real concern.

---

## 2. Claim Verification Table (Pass 1)

| # | Report claim | Verified? | Evidence | Notes |
|---|---|---|---|---|
| 1 | "Our current result dict is an untyped Python dict" (§3.2) | **YES** | [crypto_alert.py:2620-2670](crypto_alert.py#L2620) — `generate_signal()` returns a ~50-key dict with no schema | Recommendation is technically correct. |
| 2 | "Our `adaptive_engine.py` has no narrative memory" (§3.3) | **YES** | `adaptive_engine.py` has `weight_history` table for numeric OGD snapshots but no LLM reflection, no markdown log, no `signal_memory.md`. `grep narrative\|reflection\|signal_memory` returns 0 hits in the engine. | True — but the Tune Bot history table is qualitatively similar. |
| 3 | "Our risk manager is a set of threshold gates" (§3.4) | **YES** | [adaptive_engine.py:960-1090](adaptive_engine.py#L960) — `PortfolioRiskLayer.check()` is exactly 5 numbered threshold gates (MAX_OPEN_POSITIONS, MAX_SAME_DIRECTION, MAX_PORTFOLIO_RISK, MAX_DRAWDOWN, correlation warning) | True. |
| 4 | **"We currently call Claude directly"** (§3.6) | **NO — FABRICATED** | [requirements.txt](requirements.txt) = `requests>=2.31.0` only. Zero LLM client imports in any .py file. Zero anthropic/openai references in code. The 16 review agents in `.claude/agents/` are Claude Code subagents (developer tooling), not runtime calls from `crypto_alert.py`. | Critical inaccuracy. Every LLM pattern requires building infrastructure first. |
| 5 | "Our backtest can take 30+ minutes" (§3.9) | **PARTIAL** | [backtest.py:145](backtest.py#L145) `BACKTEST_DAYS=365` × 9 tokens × 3 TFs is plausibly 30+ min on cold cache, but no instrumentation exists to confirm the actual runtime. No `time.time()` start/end around `main()`. | Plausible but unverified. Worth instrumenting before claiming the value of checkpointing. |
| 6 | "Our Telegram messages list raw reasons as bullet points" (§3.10) | **YES** | [crypto_alert.py:2831](crypto_alert.py#L2831) — `msg+=f"\nWhy:\n{reasons}\n\nAnalysis only. Final call is yours."` where `reasons` is a `\n`-joined list of raw strings | True. |
| 7 | "Our signal generation loop runs every 90 seconds" (§6.4) | **YES** | [crypto_alert.py:103](crypto_alert.py#L103) `CHECK_INTERVAL = 90` | True. |
| 8 | "We have no news/sentiment filter" (§3.5) | **YES** | Only external context source is CoinGecko `/global` (BTC dominance only) at [crypto_alert.py:173](crypto_alert.py#L173). No news, no sentiment, no Fear/Greed. The label `news_or_liquidation_spike` at [crypto_alert.py:1128](crypto_alert.py#L1128) is a regime classifier, not a fetched news feed. | True. |
| 9 | Pydantic schemas would "make future DB storage trivial" (§3.2) | **MISLEADING** | DB storage is already trivial — `save_signal()` works fine with the dict, and 162/162 alignment tests pass. The Pydantic refactor solves a problem we do not currently have. | Not wrong, but not load-bearing. |
| 10 | "TradingAgents is fundamentally a fundamental + macro analysis system for stocks" (§1) | **YES** | The report's own description of the source repo. Correctly flags this as a non-port. | True and important. |
| 11 | "Estimated total LLM cost: ~$0.004/signal" (§7.1) | **OPTIMISTIC** | $0.004 assumes 12k tokens at Claude Haiku rates. Real input tokens once you include the full signal context, past 5 memory entries (~500 each = 2500), news fetcher output (~1500), and bull/bear/judge chained outputs, are probably 20-30k. Realistic cost is $0.01-0.02/signal. | Not catastrophic, but 3-5× understated. |
| 12 | "Crash recovery via LangGraph SQLite is overhead not justified" for live bot (§6.5) | **YES** | True for live (90s cycles re-fetch state cheaply). For backtest the claim flips — checkpointing IS justified. Report acknowledges this in §3.9. | Internally consistent. |
| 13 | "Claude Haiku is the right model for all AI review calls" (§8.7) | **OUTDATED MODEL CHOICE** | The report names "claude-haiku-4-5" but as of 2026-05-22 the latest is Haiku 4.5 (claude-haiku-4-5-20251001). Naming is roughly correct but should be verified before any client is built. Also: latency for Haiku is ~1-2s typical but tail latency can exceed 10s — at 9 tokens × 5 LLM calls per cycle that is 50-100s of LLM work fitted into a 90s cycle. Real-time deployment is tight. | Latency/cycle-budget math is unsafe. |
| 14 | "Graceful degradation discipline we should enforce everywhere" (§1) | **PARTIALLY ALREADY DONE** | Our codebase already uses try/except + fallbacks heavily, including the kill-switch DB error path ([crypto_alert.py:1013](crypto_alert.py#L1013)), template evaluator ([crypto_alert.py:825](crypto_alert.py#L825)) "On any exception returns (UNKNOWN_TEMPLATE, False, str(exc)) — never raises", BTC feed failure handler, and Telegram retry. The pattern exists; it just is not labeled "graceful degradation". | Adopt-now framing overstates the delta. |

---

## 3. Re-Scored Priority Table (Pass 2)

Our bottleneck is **frequency** (~37 sigs/yr structural ceiling) and **time-to-live** (need 30 paper closes ≈ 12 months). Quality is NOT a problem (WR=81%, z=+4.15). Patterns are re-scored on:
- **Freq Δ** — does this give us more setups?
- **Edge Δ** — does this preserve the WR=81% baseline as we widen filters?
- **TTL Δ** — does this delay paper collection?
- **Determinism risk** — does this break the live-vs-backtest invariant?
- **Latency budget** — does this fit in <15s/token within a 90s cycle?

| Ref | Pattern | Report priority | Audited priority | Freq Δ | Edge Δ | TTL Δ | Determinism risk | Why changed |
|---|---|---|---|---|---|---|---|---|
| 3.1 | Bull/Bear LLM debate | **HIGH** | **DROP** | 0 to −20% (rejects setups) | could rescue marginal edges, but we have no marginal edges left | +6-12 months (fewer signals, slower N≥30) | **BREAKS** invariant — LLM votes are non-deterministic | We are already above-edge. A debate that rejects signals just lowers n. Backtest cannot model an LLM judge → live WR no longer predicted by backtest WR. |
| 3.2 | Pydantic schemas | **HIGH** | **LOW** | 0 | 0 | 0 (small refactor cost) | 0 | Pure refactor of working code. Not wrong, just not load-bearing. Tests pass with the dict. Defer. |
| 3.3 | Memory + reflection | **HIGH** | **DEFER (post-30-closes)** | 0 | could help over time | +1-2 months build, requires live history | Reads only — does not vote | Requires N>0 closed live signals to be useful. We have zero. Build AFTER 30+ closes exist, not before. |
| 3.4 | Risk debate LLM | **HIGH** | **DROP** | 0 to −10% (rejects) | already protected by deterministic kill switches | +3-6 months | **BREAKS** invariant | We have 5 hard threshold gates that work. Replacing them with an LLM that may say "BLOCK" non-deterministically is a regression in safety, not an upgrade. |
| 3.5 | News/sentiment fetcher | **MEDIUM** | **MEDIUM (sources changed)** | 0 to −10% if used as gate | could prevent trading into FOMC days | +1-2 weeks build | Low if used as read-only context, high if used as gate | Port the **pattern** (graceful fetcher) but use crypto sources: Fear/Greed Index (alternative.me) + CoinGecko event calendar. Stock sources are pointless. Use as advisory tag, not gate, until live data shows it correlates with losses. |
| 3.6 | LLM client factory | **MEDIUM** | **LOW** | 0 | 0 | small upfront cost | 0 | Useful only AFTER we decide an LLM call is justified. Until then, building an abstraction for zero calls is over-engineering. |
| 3.7 | Decision log with outcomes | **MEDIUM** | **LOW (already partial)** | 0 | 0 | 0 | 0 | We already store every signal+outcome in [signals.db](data/signals.db). The markdown story is qualitatively useful but our existing schema gives the structured equivalent. Only worth doing if (a) we build the reflection LLM call AND (b) we have closed live signals to reflect on. |
| 3.8 | Capability-aware structured output | **MEDIUM** | **DROP** | n/a | n/a | n/a | n/a | Only relevant if we go multi-provider. We are single-provider (Anthropic) at most. Dead complexity. |
| 3.9 | Backtest checkpointing | **LOW** | **MEDIUM** | 0 | 0 | **saves dev time per iteration** | 0 | Promoted up. Backtest crashes during optimizer runs (Session 2, A-1 through A-9) wasted hours. Simple per-token JSON checkpoint is ~50 lines, zero risk, no LLM. Worth doing alongside paper collection. |
| 3.10 | Signal explanation generator | **MEDIUM** | **OPTIONAL (post-Telegram only)** | 0 (post-filter, not gate) | 0 | small build cost | 0 only if it runs AFTER `send_telegram()` and does not affect signal decision | A 2-sentence prose summary in Telegram is nice-to-have. The MUST-NOT is "AI summary feeds back into confidence or approval". Build only if confined to formatting. |

**Re-scored summary:**
- **ADOPT NOW (low-risk):** 3.9 (backtest checkpointing).
- **CONDITIONAL POST-TELEGRAM:** 3.10 (explanation generator, never as gate).
- **DEFER until N≥30 closes:** 3.3 (memory/reflection), 3.5 (news fetcher with crypto sources).
- **DROP:** 3.1, 3.4, 3.6, 3.8, Pattern 5 (final-signal-approver).
- **LOW PRIORITY:** 3.2 (Pydantic), 3.7 (markdown log — DB already does this).

---

## 4. Gaps and Missed Risks (Pass 3)

### 4.1 Risks the reviewer downplayed or omitted

1. **Live-vs-backtest invariant break.** Our backtest WR=81% is only meaningful because [strategy_engine.py](strategy_engine.py) is used identically by both `backtest.py` and `crypto_alert.py` (the entire purpose of that module). The moment an LLM votes inside the signal path, backtest stops being a predictor of live performance. CROSS_REF.md treats live-backtest divergence as a CRITICAL property (C4 KNOWN STRUCTURAL is even flagged just for ADX threshold drift). The report does not mention this invariant once.

2. **N-reduction compounds time-to-live.** At 37/yr, we need ~12 months for N≥30. A 30% LLM rejection rate stretches that to ~17 months. We need to LIVE-trade more than we need to QUALITY-filter. The report optimizes the wrong axis.

3. **LLM as 24/7 dependency = new failure mode.** API outage, rate limit, billing failure, or transient 5xx during a setup window means signal is silently dropped (or, worse, force-rejected). Our current hard dependencies are Binance REST (mature) and Telegram API (mature). Adding Anthropic API adds a 3rd 24/7 dependency without a graceful-degradation story in the report — §3.5 talks about graceful degradation for fetchers but not for the judge LLM. What happens when the bull/bear debate cannot complete?

4. **Memory leakage / lookahead.** §3.3 proposes "Inject the last 5 same-token reflections into the AI reviewer prompt." If reflections include outcome P&L of *open* positions, that leaks future information into a decision about a different position. If we only include closed-trade reflections, the system implicitly biases away from recent losers — that is **a recency bias that the OGD layer already explicitly guards against** ([adaptive_engine.py:655](adaptive_engine.py#L655), 7-day decay suppression). The report does not address either failure mode.

5. **Data egress.** Every LLM call ships our signal context, account balance, P&L history, and trade plan to Anthropic. For a single-user paper bot in 2026-05-22 this is "fine". If you ever share this tool, monetize it, or onboard a second user, this is a real compliance gap (signal pre-broadcast leakage, account info disclosure).

6. **Cost is understated by 3-5×.** Report estimates $0.004/signal at ~12k tokens. Real-world chained inputs (news context + memory + bull case + bear case + risk debate + setup dict) routinely exceed 25-30k tokens. Cost is closer to $0.015-0.02/signal. At 37 signals/year the absolute number is still tiny ($0.55-0.75/yr), but the scaling story for a larger token universe or shorter timeframes changes.

7. **Tail-latency budget.** Haiku averages 1-2s but 99th percentile can exceed 8-12s. 5 chained LLM calls per token × 9 tokens × P99 latency = potential 360s+ in the worst case, against a 90s cycle. Report frames this only as a per-call cost issue.

### 4.2 Patterns the report did not cover that ARE worth considering

1. **`graph/signal_processing.py`** — a deterministic markdown parser that extracts a rating from freetext. Report mentions it (§4) but does not surface it as a pattern. **This** is the right abstraction if we ever want LLM output — parse defensively, never trust JSON-only paths.

2. **`graph/conditional_logic.py`** — debate termination routing. We do not need this for our use case (we are not running multi-round debates), but the pattern of "expensive node has an early-exit predicate" is useful for **the backtest optimizer** ("if a token's WR is already > backtest's WR, skip the next experiment"). This is a non-LLM pattern worth applying inside `backtest.py`.

3. **`default_config.py`** — env-var override system with type coercion. Our config is genuinely scattered ([strategy_engine.py](strategy_engine.py) `LIVE_CONFIG` + `BACKTEST_CONFIG`, [crypto_alert.py:80-200](crypto_alert.py#L80) constants, [adaptive_engine.py:113-160](adaptive_engine.py#L113) thresholds). The report buries this in §4. **It would actually help us.**

### 4.3 Ideas the report did not test — could an LLM HELP frequency?

The reviewer focused on the LLM as a **rejection** filter. The asymmetric question is: could an LLM identify VALID setups that our deterministic gates currently reject? Our 9% conversion rate (413 qualified → 37 fired) is mostly "no FVG reaction" — price passes through the FVG zone without retracing. An LLM looking at the same chart cannot ADD signals; the FVG retracement is a deterministic measurable thing, and the LLM has no information our code does not.

**Verdict: LLMs cannot raise our frequency ceiling. The constraint is structural to ICT methodology, not analytical.**

The only way to raise frequency without collapsing edge is multi-instrument expansion (more tokens) or multi-timeframe expansion (3M or 1M base TF). Both are deterministic, both are testable against the existing baseline. Neither needs an LLM.

---

## 5. Conflicts with Current Decisions (Pass 4)

| Decision (source) | Report recommendation that conflicts | Severity |
|---|---|---|
| **Quality over frequency** chosen at Session 2 (project_state.md: "n≥50 NOT achievable without collapsing edge") | §3.1 bull/bear debate, §3.4 risk debate — both REJECT signals, lowering n further from 37 | **HIGH conflict** |
| **ICT_SWING_N=2 rollback** (project_state.md: "ICT-soundness — SWING_N=1 violates ICT swing structure requirements") | §3.1 proposes a "BearValidator attacks: is the sweep clean?" — fine in principle, but if the LLM can override ICT-sound determinism, it can re-introduce the same kind of unsound shortcut we just rolled back | MEDIUM conflict |
| **Live-vs-backtest invariant** (entire purpose of [strategy_engine.py](strategy_engine.py); CROSS_REF.md flags ADX drift as KNOWN STRUCTURAL) | All in-loop LLM patterns (3.1, 3.4, Pattern 5) — non-deterministic outputs break the invariant entirely | **CRITICAL conflict** |
| **Crash-recovery transparency** (CROSS_REF.md regression-prone item: "errors must not be silently swallowed") | §7 / Pattern 7 "graceful degradation returns a string on error" — if used as the LLM-judge fallback, signals would silently fire without an LLM judgment that the operator believes is in the loop | MEDIUM conflict |
| **Pre-LIVE checklist** (project_state.md: "Collect N≥30 total closed paper signals — start NOW") | Anything that delays paper collection (every LLM rejection filter) | HIGH conflict |
| **TELEGRAM_TOKEN via env var only** (project_state.md) | An Anthropic API key would be a new secret with the same handling requirements — the report does not flag the operational parity needed | LOW (just a TODO if we ever build it) |
| **OGD bootstrap isolation** (project_state.md: "Bootstrap OGD isolated from live OGD (backtest_token_weights table separate)") | §3.3 memory injection "the last 5 same-ticker reflections" — if mixed across paper/live without an `execution_mode` tag, contaminates live decisions with paper outcomes | MEDIUM conflict (solvable with a column, but report doesn't mention it) |

---

## 6. Adoption Plan, Ordered (Pass 5)

Each plan item lists files touched, effort in **hours** (not days — report's day-level estimates are imprecise), dependencies, acceptance test (must NOT break Run-48 baseline), and rollback.

### Adopt 1 — Backtest per-token checkpointing (from §3.9)

- **Module:** `backtest.py` (no new file).
- **Effort:** 3-4 hours.
- **Dependencies:** none.
- **What changes:** After each token's `run_backtest_token()` completes, write `backups/backtest_checkpoint.json` with the per-token signal list and run_id. On `main()` start, if a checkpoint exists for the same `BACKTEST_DAYS` window and config hash, load completed tokens and skip them.
- **Acceptance test:**
  1. Run full backtest cold → confirm WR=81.1%, n≈37, z≈+4.15 (Run-48 baseline).
  2. Delete checkpoint mid-way, restart → backtest skips already-done tokens and produces identical numbers.
  3. Run with `--force-fresh` → ignores checkpoint, full re-run produces identical numbers.
- **Rollback:** Delete the checkpoint read/write block; the existing flow is untouched.
- **Why first:** Zero LLM, zero invariant risk, zero operator cost, immediate dev-time savings during optimizer iterations.

### Adopt 2 — Crypto-native news/sentiment fetcher *as advisory tag only* (from §3.5, sources changed)

- **Module:** `phase2_data.py` (new function), do not modify signal gates.
- **Effort:** 5-7 hours including testing.
- **Dependencies:** none (use existing `requests`).
- **Sources:**
  - Fear & Greed Index: `https://api.alternative.me/fng/` (free, no key, JSON)
  - CoinGecko status updates: already polling the global endpoint; add `/coins/{id}/status_updates`
  - Skip Yahoo/StockTwits/Reddit entirely (stock-focused, low signal for crypto)
- **What it does:** On the live signal cycle, compute a `news_context` string (current Fear/Greed value + last-24h status updates). Attach to the result dict as `news_context` AND log to DB but **do not use it as a gate**.
- **Acceptance test:**
  1. Run for 7 days with the fetcher attached → no signal count change vs prior 7 days (proves it is advisory only).
  2. Fetcher failure (network down) → signal fires anyway with `news_context = "[unavailable]"`.
  3. New `news_context` column in `signals` table is populated for ≥80% of new signals.
- **Rollback:** Stop calling the fetcher; signals continue to fire unmodified.
- **Why second:** Read-only enrichment. No invariant break. Lets us COLLECT correlation data between news regime and outcome — which is what we would need before any LLM news-gate becomes data-driven.

### Adopt 3 — Centralized config with env-var overrides (not in report's headline patterns, hidden in §4)

- **Module:** `config.py` (new), refactor [strategy_engine.py:121-150](strategy_engine.py#L121), [crypto_alert.py:80-200](crypto_alert.py#L80).
- **Effort:** 8-10 hours including test updates.
- **Dependencies:** none.
- **What it does:** Single source of truth for all tunable constants. Defaults match current values. Env-var override for ops flexibility (e.g. `MAX_SL_PCT=0.025 scripts\start_bot.bat`).
- **Acceptance test:**
  1. 162/162 tests still pass with no behavior change.
  2. Fresh backtest produces identical WR, n, z to Run-48.
  3. `MAX_SL_PCT=0.025` env override flows through correctly.
- **Rollback:** Restore constants to original files. (Worth doing on a branch.)
- **Why third:** Pure infrastructure, no LLM, but improves operational ergonomics during paper collection.

### STOP HERE until N≥30 paper closes are collected.

Everything below depends on paper data we do not have yet. Building it now is premature optimization.

### Deferred 1 — Pydantic schema layer (post-paper) (from §3.2)

- 4-6 hours. Wrap the `generate_signal()` result dict in a typed schema. Acceptance test: 162/162 tests pass; serialization to DB identical. No invariant risk because no LLM involved.

### Deferred 2 — Signal explanation generator, POST-Telegram only (from §3.10)

- 6-8 hours including LLM client setup.
- HARD GUARDRAIL: must run AFTER `send_telegram()` has fired. The Telegram message is authoritative; the LLM prose is a tracker-dashboard footnote, never a gate.
- Defer because: introduces our first LLM dependency. Want N≥30 closes to validate the explanation against actual outcomes before letting it live in front of users.

### Deferred 3 — Narrative memory + reflection (from §3.3)

- 10-15 hours.
- Defer until N≥30 closes. Useless before that — reflections on zero closed trades are noise.
- Add an `execution_mode` column to the memory log so paper reflections cannot leak into LIVE decisions.

### Permanently dropped from this audit

- §3.1 bull/bear debate as gate
- §3.4 LLM risk debate as gate
- §3.6 multi-provider LLM factory
- §3.7 markdown decision log (DB already does this)
- §3.8 capability-aware output binding
- Pattern 5 final-signal-approver as gate
- All multi-round debate patterns
- LangGraph

---

## 7. Second-Order Findings (Pass 6)

### 7.1 Our 16 Claude Code agents already do most of what the report proposes

The report proposes runtime LLM agents (`bull_bear_debate_layer`, `risk_manager`, `post_trade_review_agent`, `final_signal_approver`, etc.). We already have **developer-time** equivalents in [.claude/agents/](.claude/agents/):
- `ict-logic-validator` ≈ technical setup validator
- `risk-management-auditor` ≈ risk_manager review
- `signal-performance-analyzer` ≈ post-trade reflection (but offline, not per-signal)
- `backtest-bias-detector` ≈ live-backtest consistency (which the report does NOT mention)
- `live-deployment-readiness-checker` ≈ pre-live gate

These run on-demand against the codebase and signal history, not in the 90s cycle. **For a paper-collecting bot, that is the right place for LLM intelligence.** The report's main framing — "build LLM agents into the runtime" — would partly duplicate what we already have in a worse place (the latency-critical signal path).

### 7.2 LLM-assisted backtest reviewer is higher value than LLM live reviewer

For the same engineering cost, an offline backtest reviewer:
- has no 90s latency budget
- has no live-vs-backtest invariant risk
- has no daily ops cost (runs only when a backtest is queued)
- can read the full backtest report once and produce a human summary

The report does not propose this, even though it is the strictly safer first LLM integration. **Recommended sequencing if any LLM is added: post-backtest reviewer first, signal explanation generator second, anything in the live loop never.**

### 7.3 Documentation drift

- README.md (which we just updated) lists 10 tokens. project_state.md confirms 9. The actual code at [crypto_alert.py:80-94](crypto_alert.py#L80) is 10. The discrepancy is SOL in the comment vs SOL not in the dict — needs a clarifying comment in the code. Not the report's problem, but a cheap fix.
- CROSS_REF.md does not reference the TradingAgents report at all. If we adopt anything from it, that decision must be cross-referenced so future agents do not propose the same idea or re-flag the deferred items.

### 7.4 Tests we could add cheaply alongside the adoption plan

- Test that `news_context` enrichment never alters signal selection (compare with-fetcher vs without-fetcher run, assert identical signal IDs). This is the only way to keep §3.5 honest as "advisory only".
- Test that the backtest checkpoint produces byte-identical signal DB rows whether resumed or run cold.
- Test that env-var overrides actually propagate (we have nothing testing config wiring right now).

### 7.5 The report's most useful single sentence

> "Keep AI review as a post-filter that runs after deterministic ICT logic confirms a setup, not as a primary analysis layer." (§6.4)

This is correct. But the report then immediately violates its own rule by putting bull/bear/risk debate INSIDE the decision loop in the Suggested Architecture (§7). If §6.4 is honored, only §3.10 (signal explanation generator, post-Telegram) survives — which is exactly what this audit recommends.

---

## 8. Final Verdict

**Wait until after N≥30 paper closes are collected before adopting any LLM-bearing pattern from this report. Adopt only the three non-LLM patterns (backtest checkpointing, crypto-native news fetcher as advisory tag, centralized config) during the paper-collection window.**

Justification:
1. Our edge is real and structural (WR=81%, z=+4.15) and protected by the live-vs-backtest invariant. Inserting an LLM into the signal path destroys that invariant before it has produced a single live closed trade.
2. Our bottleneck is frequency, not quality. Every LLM rejection filter delays reaching N≥30 by months and provides no upside on an already-positive expectancy.
3. The report's central premise that we "currently call Claude directly" is false — every LLM pattern is greenfield, not a port. The effort estimates in the report are systematically understated because they assume LLM infrastructure exists.
4. The report ignores the data-egress and invariant-break risks; these are first-order concerns for a system that protects user capital.
5. Once N≥30 paper closes are collected, the deferred items (narrative memory, post-Telegram explanation generator, possibly a post-backtest LLM reviewer) become evaluable against real outcome data instead of intuition.

**Do not stop paper collection to build LLM features. Do not adopt LLM features as gates. Use the next 12 months to ship 30 closed paper signals and the three non-LLM adoptions above.**

*End of audit.*
