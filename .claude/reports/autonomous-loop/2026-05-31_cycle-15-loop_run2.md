# TradeAI Autonomous Loop — Cycle #2 Report

**Date:** 2026-05-31
**Mode:** ONE cycle then STOP per operator spec.
**Pin:** Run-3704 (kept per operator decision after cycle #1)
**Bot live state:** PAPER mode, PID 393274, cycle 6168+, 0 errors, 12 tokens scanning, FUNDING_GATE_ENABLED=1 (first live activation, 25h+ stable).

---

## Pre-cycle ledger corrections (per operator note)

Before opening cycle #2, I applied three ledger corrections so prior cycle findings aren't re-raised:

- **C15L-2 (the n_trials-undercount CRITICAL):** marked RESOLVED. The corrected analysis from yesterday's discussion shows that under any consistent (N, σ) pairing, DSR lands in the 96-98% range — comfortably clearing the 95% gate. The "DSR is optimistic" framing was based on a methodology mix-up between pool σ and population σ.
- **C15L-4 (the "thin head-room" HIGH):** WITHDRAWN. Same root cause — the projected 96.2% used pool σ=0.138 on a hypothetical larger N, which is methodologically wrong. The proper Bailey/LdP correction uses population σ=0.082 at large N, giving DSR ≈ 97.8%, not 96.2%.
- **New C15L-9 logged:** the bot's published DSR is actually CONSERVATIVE (under-reports the true selection-adjusted edge), not optimistic. Not a fix needed; documented for transparency.

---

## What I checked this cycle

I fanned out 5 read-only specialists, scoped to areas cycle #1 did NOT deeply cover:

| Specialist | Focus |
|---|---|
| adaptive-learning-code-reviewer | OGD math + DSR-aware learning-rate gate under the new pin (Run-3704's config_hash changed) |
| template-tier-calibrator | Tier A/B/C discrimination under Run-3704's much-wider FVG probe + faster mitigation TTL |
| data-pipeline-validator | First live activation of FUNDING_GATE=1 — funding fetch reliability, rate-limit budget |
| ogd-weight-inspector | DB-level OGD state (12 tokens, ATOM/BCH defaults, DSR-gate sync) |
| live-deployment-readiness-checker | GO/NO-GO for LIVE given DSR now clears 95% |

All 5 returned. Synthesizing.

---

## What I found, by severity

### HIGH — 1 finding (independently confirmed by 2 reviewers)

**The OGD learning-rate gate is failing OPEN.** Two reviewers caught the same root cause from different angles:

The bot has a safety system that throttles the adaptive learning rate when the statistical-validity verdict (DSR) is stale or doesn't match the current pin's config hash. When you promoted Run-3704 yesterday, the persisted DSR verdict still had the OLD config hash (`287881168f...` from a Run-2749 era backtest, not the new `3ee13531...` from Run-3704). The hash-mismatch detection correctly fired, but the next step — "if the mismatch has been stale for more than 48 hours, throttle to 0.5× learning rate" — silently broke.

Why it broke: the code reads the verdict's timestamp from `blob.get("written_at")` or `blob.get("ts")`, but the actual backtest writer only persists `updated_at`. Three different field names, none matched. So the timestamp parse returned 0, the grace-window guard never fired, and the learning rate stayed at 1.0× indefinitely instead of throttling.

**Why it qualifies as HIGH** per your spec: "a gate that fails OPEN is at least HIGH." The OGD adaptive system was supposed to be running at a throttled rate because the verdict on the current pin is unknown — instead, it's running at full rate.

**Actual current impact:** Almost none yet. The bot has been on Run-3704 only ~26 hours, well within the 48-hour grace window. So at this exact moment the behavior is identical with-or-without the fix. The damage would have started ~22 hours from now — OGD would have stayed at 1.0× LR indefinitely instead of throttling to 0.5×.

### MEDIUM — 3 findings

1. **Tier B BUY win rate dropped from 70.8% (Run-3702) to 65.0% (Run-3704).** Two parameters changed simultaneously between those backtests — wider FVG probe (W=2→5) and faster mitigation TTL (168h→24h). The signals affected are all OB-confluence (not FVG), so the FVG probe is probably not the culprit. The faster mitigation TTL is the more likely cause: zones now re-open 7× faster, admitting lower-probability re-entries into already-tested levels. Not a code defect — a strategy parameter choice with empirical cost. Recommendation: run an isolation backtest holding TTL=168 and flipping only the probe width to confirm root cause.

2. **A module-default gap could silently distort explorer trials.** The funding bonus (0.10 in `.env`) and BTC-correlation bonus (0.08 in `.env`) are read at module-import time. If any subprocess spawned by the autonomous explorer fails to inherit the full env, those constants fall back to module defaults (0.05 and 0.0 respectively), silently producing a different strategy than the parent expected. Need to verify whether `autonomous_explorer.py` properly passes the env. If yes, this is moot. If no, every explorer trial that searched these bonus parameters could have been mis-evaluated.

3. **ATOM and BCH OGD bootstrap priors are stale relative to Run-3704.** Both tokens' weights came from Run-2749 (yesterday's bootstrap), which used the OLD pin's params. Because their bootstrap weights are at exact DEFAULT_WEIGHTS (n_bootstrap=10 and 6 — too few signals to actually move weights), there's no real contamination. But when Run-3704 accumulates ≥15 closed signals per token, a fresh re-bootstrap would replace these flat defaults with learned weights.

### LOW — 4 findings (carry to backlog)

- A pre-existing timezone bug in the same OGD-gate timestamp path: VPS is on `Europe/Berlin (CEST, +0200)`, the timestamp roundtrip drops the UTC marker, the parse interprets the naive string as local time → grace window calculation off by 2 hours. Conservative direction (throttles 2h sooner than intended).
- ATOM ≡ BCH identical-weight collision creates a cosmetic `min_L1=0.000` reading. The homogeneity alert is correctly suppressed; it auto-resolves on first closed signal for either token.
- OHLCV cache TTL boundary upcoming (~4 hours from now). Any backtest run after that triggers a slower full re-fetch. Not a bug, just operational awareness.
- 9 pre-existing test failures still pre-existing (proven yesterday via git stash).

### PRE-LIVE — NO-GO (data maturity, not code)

The deployment-readiness specialist ran all 7 code-level checks: PASS on all of them (no hardcoded secrets, Telegram has retry+backoff, consecutive_errors=8 threshold intact, triple-lock execution mode wired, zero order-execution code, risk gates correct in LIVE branch, no auto-flip paths).

The single LIVE blocker is the project's own 30-closed-paper-signal floor. Current count: 5, none on Run-3704 yet. Expected wait: ~6-8 weeks at current signal frequency.

---

## What I fixed and why it mattered

**One minimal fix per spec.** I picked the HIGH (the OGD gate failing OPEN).

### The fix

File: `/home/tradeai/TradeAI/adaptive_engine.py:637-648` — added `or blob.get("updated_at")` to the timestamp fallback chain.

```python
# BEFORE:
_written_at_iso = blob.get("written_at") or blob.get("ts") or ""

# AFTER:
_written_at_iso = (blob.get("written_at") or blob.get("ts")
                   or blob.get("updated_at") or "")
```

The fallback order is preserved (`written_at` still preferred first), so if a future backtest writes that field, behavior is unchanged. The new `updated_at` fallback simply catches the actual current write-side schema.

### Why it mattered

Without this fix, after 22 more hours, the OGD adaptive learning system would have been running at full learning rate against the wrong config's FAIL verdict. The intended behavior — throttle to 0.5× when the verdict is stale-and-mismatched — would silently not happen. Per your spec, that's exactly the "gate fails OPEN" pattern.

### Independent verification

I spawned the `trading-system-auditor` agent (Opus, read-only). It ran 7 checks and returned **PASS** with one noted pre-existing caveat:

- **PASS:** bug is real (confirmed against actual DB blob), fix resolves it, backward-compatible (preserves `written_at` priority), no guardrail weakened, non-drift path unaffected, Python 3.12 / Ubuntu 24.04 `fromisoformat` handles space-separated format correctly.
- **Pre-existing caveat:** VPS timezone is Europe/Berlin, not UTC. The timestamp parse loses the UTC marker, off by 2h. I logged this as separate finding C15L2-2 (LOW, conservative direction).
- **Test coverage gap:** no unit tests exist for `_dsr_gate_lr_scale()`. Not introduced by this fix — existing gap.

---

## What the tests show

**569 pass, 9 fail. Same 9 as cycle #1 — all pre-existing, all proven yesterday via git stash.** No new failures. No failure touches the OGD gate code path, the timestamp parsing, or the verdict blob.

---

## Could I fully verify everything? — Honest answer

**Yes for the fix itself.** Verifier ran 7 checks; I ran sanity-check Python that replayed the exact pre-fix and post-fix behavior on the actual persisted blob.

**Partial on the secondary issues:**
- I did NOT verify whether `autonomous_explorer.py` strips env when spawning subprocess trials (C15L2-5). If you run another explorer session, that's a worthwhile thing to check first. Could affect past explorer fitness scoring.
- I did NOT run the isolation backtest to attribute Tier B BUY WR drop to FVG_PROBE vs MITIGATION_TTL (C15L2-4). Operator-side experimental decision.
- The timezone bug (C15L2-2) is acknowledged but unfixed — orthogonal to today's main fix, direction is conservative.

---

## Config recommendations (not auto-applied)

1. **Refresh `bot_state.latest_cpcv_verdict` to Run-3704's hash.** Run any backtest under Run-3704 config with `WRITE_CPCV_VERDICT=1` (NOT the explorer-mode `=0` flag I used in reproductions yesterday). This refreshes the verdict to the current pin, clearing the stale-fallback escalation path entirely. Single command, ~30 seconds cache-hot.

2. **Verify `autonomous_explorer.py` subprocess env passthrough.** Single grep + 5-line read in the explorer file. If it correctly inherits env, C15L2-5 is closed. If not, past explorer trials may have used wrong overlay bonuses.

3. **Add unit tests for `_dsr_gate_lr_scale()`** covering the three paths: hash-match, hash-mismatch within grace, hash-mismatch past grace. This was an existing gap, surfaced by verifier.

4. **Fix the timezone roundtrip** in the verdict timestamp (write with explicit `Z` or parse with explicit UTC). Cycle worth: LOW; conservative direction.

5. **Once Run-3704 hits ≥15 closed paper signals per token**, run a fresh bootstrap to replace ATOM/BCH default-flat weights with Run-3704-era learned weights.

---

## Safe to keep running in PAPER mode: YES — and why.

Bot is operationally healthy. Today's fix is purely additive (adds a fallback to a broken read-path that was silently failing). Current behavior is unchanged for the next ~22 hours — the fix takes effect only at hour 48 after the verdict's `updated_at` timestamp, and it produces a CONSERVATIVE throttle (slower learning, never faster). No guardrail weakened, no anti-pattern reopened, no order-execution code added, no LIVE auto-flip introduced. 5 LIVE-clearance code checks PASS; single LIVE blocker is statistical (30-paper-signal floor) — not a defect, just maturity.

**LIVE remains NO-GO** until 30 paper signals close under Run-3704 (~6-8 weeks).

---

**Cycle-15-loop run #2 complete. Stopping per spec. Awaiting operator decision before continuing to cycle #3.**
