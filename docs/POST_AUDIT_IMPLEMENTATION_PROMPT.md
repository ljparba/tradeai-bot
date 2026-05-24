# TradeAI — Post-Audit Implementation Prompt

**Source audit:** `docs/TRADINGAGENTS_INVESTIGATION_AUDIT.md` (2026-05-22)
**Purpose:** Drive the three non-LLM adoption items approved in audit Section 6.
**Use:** Copy-paste into a fresh coding agent session, or hand to a subagent.

---

## Role
You are a senior trading-systems engineer implementing the three non-LLM
adoption items approved by the audit in
`docs/TRADINGAGENTS_INVESTIGATION_AUDIT.md` (Section 6, "Adoption Plan,
Ordered"). You are NOT auditing, planning, or researching. You are
implementing — but only inside hard guardrails.

## Required reading (read in full before any edit)
1. `docs/TRADINGAGENTS_INVESTIGATION_AUDIT.md` Section 6 + Section 8
   (final verdict)
2. `C:\Users\User\.claude\projects\c--Users-User-Desktop-TradeAI\memory\project_state.md`
   — current baseline (Run-48: n=31, WR=77.4%, z=+3.36; Post-Session-2:
   n≈37/yr, WR≈81.1%, z≈+4.15)
3. `crypto_alert.py`, `backtest.py`, `ict_engine.py`, `adaptive_engine.py`,
   `strategy_templates.py` — read enough to make safe edits
4. `docs/comprehensive/CROSS_REF.md` — known issues; do not re-introduce
   resolved bugs

## Absolute guardrails (violating any = stop and report)
1. **No LLM code.** Do not import `anthropic`, `openai`, `langchain`,
   `pydantic`, or any LLM client. The audit dropped every LLM-bearing
   pattern. If you are tempted to add one, you are out of scope — stop.
2. **No change to signal generation logic.** `evaluate_setup()`,
   `generate_signal()`, ICT detection in `ict_engine.py`, OGD math in
   `adaptive_engine.py`, strategy templates — all read-only.
3. **No change to ACTIVE_CONFIG or BACKTEST_CONFIG values.** Constants
   stay byte-identical. (Adopt 3 moves them to a new file but defaults
   must match the current values exactly.)
4. **No change to DB schema columns that tracker.py reads.** Adding new
   columns is fine; renaming/removing existing columns is forbidden.
5. **Run-48 baseline must not regress.** After every adopt, a fresh
   backtest must reproduce n≈37, WR≈81%, z≈+4.15 (within ±1 signal,
   ±2pp WR). If it changes, rollback the adopt.
6. **No code that requires VPN/network beyond what already exists.**
   Binance + CoinGecko + Telegram + (new) alternative.me Fear/Greed
   public endpoint only. No paid APIs.
7. **All 162 tests must still pass after every adopt.**

## Execution sequence — STRICT ORDER, do not skip ahead

### Adopt 1 — Backtest per-token checkpointing
**Source:** Audit §6 "Adopt 1". Audit §3.9 promoted from LOW to MEDIUM.
**Effort budget:** 3-4 hours. If you exceed 6 hours, stop and report.

**Tasks:**
1. Add `BACKTEST_CHECKPOINT_DIR = "backups/"` constant in `backtest.py`.
2. After each token's run completes inside `main()`, write
   `backups/backtest_checkpoint.json` containing:
   - `config_hash`: SHA-256 of the active config dict (sorted keys)
   - `backtest_days`: current BACKTEST_DAYS value
   - `completed_tokens`: {token: {signals: [...], stats: {...}}}
   - `timestamp`: ISO UTC
3. On `main()` start, if a checkpoint exists AND `config_hash` matches
   AND `backtest_days` matches, skip already-completed tokens and merge
   their signals into the final report.
4. Add a `--force-fresh` CLI flag to ignore the checkpoint.
5. On final report generation, delete the checkpoint (clean exit).

**Acceptance tests (all must pass before moving to Adopt 2):**
- AT-1a: Cold run from scratch → n≈37, WR≈81%, z≈+4.15 (within tolerance).
- AT-1b: Kill backtest after 4 tokens complete → restart → resumes from
  token 5 → final numbers identical to AT-1a.
- AT-1c: `--force-fresh` ignores checkpoint, full re-run produces
  numbers identical to AT-1a.
- AT-1d: Changing any config constant invalidates checkpoint
  (config_hash differs → full re-run).
- AT-1e: 162/162 tests pass.

**Rollback:** Remove the checkpoint read/write blocks. The remaining
flow is unchanged.

**Report back:** Diff summary + AT results + actual hours. Stop and
wait for approval before starting Adopt 2.

---

### Adopt 2 — Crypto-native news/sentiment fetcher (advisory tag ONLY)
**Source:** Audit §6 "Adopt 2". Audit §3.5 with sources changed.
**Effort budget:** 5-7 hours. If you exceed 10 hours, stop and report.

**Tasks:**
1. New function `fetch_crypto_news_context(token: str) -> str` in
   `phase2_data.py` (or new `news_sentiment.py` if cleaner).
2. Sources (all free, no API key):
   - Fear & Greed Index: `https://api.alternative.me/fng/?limit=1`
   - CoinGecko status updates: `/coins/{id}/status_updates?per_page=3`
     (already have CoinGecko client at `crypto_alert.py:173`)
   - SKIP Yahoo, StockTwits, Reddit (stock-focused, audit §3 dropped).
3. Function returns a single string. On ANY failure (network, timeout,
   parse error, rate limit) returns `"[news unavailable: <reason>]"` —
   never raises. Pattern from audit §7 Pattern 7.
4. Add `news_context TEXT` column to the `signals` table via a migration
   that is idempotent (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
5. In `crypto_alert.py` signal generation, call the fetcher AFTER
   `evaluate_setup()` returns PASS but BEFORE `save_signal()`. Attach
   the string to the result dict as `news_context` and persist to DB.
6. **CRITICAL:** Do not branch on `news_context` anywhere. It is
   advisory. No `if news_context == "...": reject`. The audit calls
   this out as the must-not.

**Acceptance tests:**
- AT-2a: 7-day live (paper) run with fetcher attached → identical
  signal count and identical signal IDs vs a 7-day run with the
  fetcher disabled. (Proves it is advisory only.)
- AT-2b: Simulate network failure (block alternative.me in hosts file)
  → signal still fires, `news_context = "[news unavailable: ...]"` in
  DB.
- AT-2c: `news_context` column populated for ≥80% of new signals over
  a 24-hour live test.
- AT-2d: Fresh backtest unaffected (fetcher is live-only) → n≈37,
  WR≈81%, z≈+4.15.
- AT-2e: 162/162 tests pass + 1 new test asserting fetcher failure
  does not raise.

**Rollback:** Stop calling the fetcher. Existing `news_context` column
stays (harmless NULL).

**Report back:** Diff summary + AT results + actual hours. Stop and
wait for approval before starting Adopt 3.

---

### Adopt 3 — Centralized config with env-var overrides
**Source:** Audit §4.2 (hidden in §4), promoted to Adopt 3 in §6.
**Effort budget:** 8-10 hours. If you exceed 14 hours, stop and report.

**Tasks:**
1. New file `config.py` at repo root. Single source of truth for all
   tunable constants currently scattered across:
   - `strategy_engine.py:121-150` (LIVE_CONFIG, BACKTEST_CONFIG)
   - `crypto_alert.py:80-200` (intervals, thresholds, token list)
   - `adaptive_engine.py:113-160` (OGD thresholds, risk gates)
2. Each constant gets an env-var override with type coercion:
   ```python
   MAX_SL_PCT = float(os.environ.get("MAX_SL_PCT", "0.030"))
   ```
3. Defaults must EXACTLY match current values. No re-tuning.
4. Update import sites to read from `config.py`. Keep old constant
   names so no other file changes.
5. Add `tests/test_config_wiring.py` that:
   - Asserts defaults match Run-48 documented values
   - Asserts env-var overrides propagate (set `MAX_SL_PCT=0.025`,
     reload config, assert it equals 0.025)

**Acceptance tests:**
- AT-3a: All 162 existing tests pass with no edits to test code.
- AT-3b: Fresh cold backtest → n≈37, WR≈81%, z≈+4.15 (within
  tolerance). Identical to AT-1a.
- AT-3c: New `test_config_wiring.py` passes (≥3 new tests).
- AT-3d: `MAX_SL_PCT=0.025 python backtest.py` produces a different
  signal count than the default run (proves env-var actually wires
  through).
- AT-3e: `ICT_SWING_N=1 python backtest.py` reproduces the
  ICT-unsound regression we previously rolled back (proves env-var
  reaches the engine).

**Rollback:** Delete `config.py`, restore constants to original files.
Work on a branch named `adopt-3-config`.

**Report back:** Diff summary + AT results + actual hours + verdict
on whether the new structure is worth merging or if the scattered
constants should be reverted.

---

## After all 3 adopts succeed — HARD STOP

Do NOT start Pydantic schemas, signal explanation generator, narrative
memory, LLM client, or anything else from the audit's "Deferred" list.
Those require N≥30 closed paper signals (currently 0) and are out of
scope.

Final report to user must include:
1. All AT results (15 acceptance tests across 3 adopts)
2. Updated baseline run numbers (still n≈37, WR≈81%, z≈+4.15)
3. Confirmation that 162/162 tests pass
4. Confirmation that paper trading can begin (or is already running)
5. Updated `CROSS_REF.md` entry referencing this implementation
6. Updated `MEMORY.md` project_state entry with new adopt status

## Style rules
- One adopt at a time. Wait for user approval between adopts.
- Cite file:line for every code reference.
- Use TodoWrite to track the 3 adopts + their AT sub-items.
- No emoji. No fluff. No "exciting" / "powerful" language.
- If anything is ambiguous, ASK before editing. Do not assume.
- Today is 2026-05-22. Use absolute dates in any memory updates.
