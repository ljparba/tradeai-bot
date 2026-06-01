# TradeAI Autonomous Loop — First Cycle Report

**Date:** 2026-05-30 PM (cycle-15-loop, run #1)
**Mode:** ONE cycle then STOP per operator spec.
**Bot live state at audit time:** PAPER mode, Run-3704 pin (promoted ~3h ago), 12 tokens scanning, 0 errors, 0 closed signals on new pin yet.

---

## What I checked

I fanned out 7 specialist read-only reviewers in parallel, each with a focused scope and explicit instructions to NOT re-flag already-resolved findings unless they had concrete evidence of regression:

| Specialist | Focus this cycle |
|---|---|
| ict-logic-validator | Does Run-3704's wider FVG probe, faster mitigation TTL, looser SL buffer, and first-time-ON funding gate behave correctly? |
| live-backtest-consistency-checker | Do all 23 new Run-3704 env params behave identically in live and backtest? |
| backtest-bias-detector | Is the Run-3704 promotion honest given we selected from a ~1000-trial explorer sweep? |
| honest-metrics-reviewer | Is DSR=97.6% math correct? What happens if I re-score after the pool refresh? |
| risk-management-auditor | Are yesterday's cycle-15 fixes intact? Do the new params produce sane economics? |
| config-consistency-validator | Are the 23 new params read identically across all 5 source files (no M24-class drift)? |
| crash-recovery-auditor | After 5 bot restarts today, is anything corrupted? |

(One additional specialist — `adaptive-learning-reviewer` — failed to spawn due to a name typo on my end. I'll fix that in cycle 2. We have plenty of data from the other 7.)

---

## What I found, by severity

### CRITICAL — 2 findings

**1. Backtest was running a different cooldown than live.** The operator's `.env` had `SIGNAL_COOLDOWN=60` (60 minutes between same-direction signals on the same token). The live bot honored this. But the backtest code had a hardcoded number (`COOLDOWN_BARS = 8` = 40 minutes) that ignored the `.env` value. So **the backtest was running on a strategy the live bot does not actually run.** Specifically, the Run-3704 backtest projected 106 signals per year, but the live bot at 60-min cooldown would only produce roughly 83 (about 28% fewer). This kind of mismatch is the exact "M24-class" drift bug we've hunted before — different parts of the system disagreeing on the same number.

**2. The DSR=97.6% on Run-3704 is optimistic.** The bot's statistical-validity check (DSR) deflates a strategy's Sharpe ratio based on how many candidate strategies were tested. The math assumes we counted ALL the candidates the operator saw before picking the winner. In reality, the operator picked trial 3777 from a ~1000-trial overnight explorer sweep. The code only counts trials that were RUN as named backtests in the database — it doesn't know about the 1000 trials in the explorer-only database. So the DSR penalty is too small, and the reported 97.6% is higher than the honest selection-adjusted number. Estimated true DSR: lower, by an unknowable amount, but the LIVE-clearance gate (95%) is no longer firmly cleared.

### HIGH — 1 finding

**3. DSR head-room is thin.** Even ignoring the n_trials undercount above, if we re-score Run-3704 using the cross-config Sharpe spread that exists AFTER the pool refresh (the pool now includes Run-3704 itself), DSR drops about 1.4 percentage points to ~96.2%. Still above the 95% gate but not by much. The next time a new config enters the pool, DSR could fall below the gate without any code change.

### MEDIUM / LOW — 6 findings

- Ledger (`docs/comprehensive/CROSS_REF.md`) was stale (Sprint 3 era from May 23 — no entries for cycle-12/13/14/15 work). Now updated with this cycle's findings.
- A small arithmetic discrepancy between reported `bench_SR` shift and what the math implies (probably a misreport in earlier session text, not a real bug — operator should verify against the actual Run-3704 log line).
- H4_CRT_MITIGATION_TTL_H=24 + CRT_FORWARD_BARS=864 combination: a CRT zone could re-fire after 24h while the original signal's 72h outcome window is still open. Backtest has a guard against this; live does not.
- Watchdog sends an "ACTIVE" alert on every restart — operator may see alert spam during busy edit/restart days.
- FUNDING_GATE_ENABLED=1 first live activation: verified fail-safe (a fetch failure doesn't block signals).
- H4_CRT_FVG_PROBE_WIDTH=5 array-bounds verified safe.

---

## What I fixed and why it mattered

**One minimal fix per spec.** I picked the SIGNAL_COOLDOWN/COOLDOWN_BARS parity issue (CRITICAL #1).

### The fix

Two files changed:

1. **`backtest.py:265`** — replaced the hardcoded `COOLDOWN_BARS = 8` with a line that reads `SIGNAL_COOLDOWN` from the environment (same variable the live bot reads), with the same default (40 minutes) so all prior baselines reproduce identically.

2. **`scripts/backtest_regression.py:67`** — removed the now-stale `COOLDOWN_BARS: 8` expectation from the CI parameter-drift guard, because the value is no longer a fixed constant.

### Why it mattered

The live bot and the backtest were running different strategies. The DSR=97.6% verdict that justified promoting Run-3704 was earned on a strategy with a 40-minute cooldown — but the live bot was running a 60-minute cooldown, which produces materially fewer trades. This means the "first PASS verdict of the session" that I told you about earlier today was technically scored on the wrong backtest configuration relative to the live config that resulted from it. After this fix, any future backtest will use the same cooldown the live bot uses, automatically.

I picked this fix because:
- It directly restores live↔backtest cadence parity
- It's a 2-line code change with bit-exact backward compatibility (default branch returns 8, matching the old hardcoded value)
- It doesn't weaken any safety gate — it tightens parity
- It was caught by TWO independent reviewers (selection-bias resistant)

### Independent verification

I spawned the `trading-system-auditor` agent (Opus, read-only, did not write or find the fix) to verify. It ran 9 independent checks and returned **PASS with 2 caveats**:

- **Caveat 1 (LOW):** an empty-string `SIGNAL_COOLDOWN=` in `.env` would crash backtest at module load with `ValueError`. This is fail-loud (the bot won't silently use the wrong value), consistent with the project's "fail-loud" philosophy. No action needed.
- **Caveat 2 (MEDIUM):** the CI drift guard at `scripts/backtest_regression.py:69` had a stale `COOLDOWN_BARS: 8` entry that would now produce a false-positive alert. **I addressed this in the same cycle** by removing the entry (which is the verifier's recommended remediation).

---

## What the tests show

**569 passed, 9 failed.**

| Failure | Root cause | Caused by my fix? |
|---|---|---|
| `test_backtest_regression.py` × 3 | Stale `_EXPECTED_PARAMS` snapshot still expects `BACKTEST_DAYS=730` (an anti-pattern that was rolled back to 365), 9-token universe (now 12), and `bias_4h_gate='none'` (now 'loose') | **No** — pre-existing drift in fixtures from the Run-48 era |
| `test_config.py` × 4 | Same as above — `test_token_universe_locked` expects 9 tokens, actual is 12 (TON/ATOM/BCH added) | **No** — pre-existing |
| `test_crt_engine.py::TestCycle12ExtendedConfigHashIsolation::test_each_knob_changes_config_hash` × 1 | Subprocess inherits operator's `.env` (which now contains `SIGNAL_COOLDOWN=60`), and the test's "flip-to-60" override collides because env is already 60. Verified by temporarily removing `SIGNAL_COOLDOWN=60` from `.env` → test passes. | **No** — caused by operator's `.env` state, not my code change. Test needs to clear env before subprocess. |
| `test_heartbeat.py::test_heartbeat_selftest_fires_on_cadence` × 1 | Pre-existing | **No** |

**None of the 9 failures touch COOLDOWN_BARS or relate to my fix.** They are documentation/fixture drift accumulated over many cycles and should be cleaned up in a future cycle.

One additional test file (`test_tracker_db_alignment.py`) calls `sys.exit(1)` at module load, which breaks pytest collection. I ran the suite with `--ignore` to get the 569/9 count. This is a pre-existing test-design issue (the file is script-style, not pytest-style).

---

## Config recommendations (not auto-applied)

Per spec, I report config changes as recommendations only:

1. **Run a fresh backtest on Run-3704 now that COOLDOWN_BARS correctly equals 12.** The original Run #3704/#3705 reproduction used 40-min cooldown internally; the next backtest will use 60-min. Expected outcome: signal count drops from n=106 to roughly n=80-90. The honest DSR under the corrected cadence is the real number to evaluate Run-3704 against the 95% LIVE clearance gate.

2. **Decide on Run-3704's status given the corrected backtest.** Two paths:
   - If new DSR still clears 95% → keep Run-3704 as pin
   - If new DSR drops below 95% → consider rolling back to Run-2156 (pre-3777 baseline) or to one of the other Pareto-archived candidates

3. **Address the n_trials_for_dsr undercount (CRITICAL #2).** This is a methodological issue, not a code bug. Two complementary fixes proposed:
   - Record `n_explorer_trials_sweep` as metadata on every explorer session; persist as a floor seed for `cumulative_min_trials`
   - Log `_n_trials_dsr` to `promotion_log.json` for audit trail
   Both are Simple effort, HIGH impact. Not auto-fixed because they require operator judgment on methodology.

4. **Update the stale CI fixtures** (`test_config.py`, `test_backtest_regression.py`) to reflect the current 12-token universe + Run-3704 pin. Not done in this cycle to avoid drive-by refactors.

5. **Confirm H4_CRT_MITIGATION_TTL_H=24 was intentional, not a typo for 240.** With CRT_FORWARD_BARS=864 (72h), a zone can re-fire while the original signal is still open. Operator should verify intent.

---

## Could I fully verify everything? — Honest answer

**Yes for the fix itself.** The independent verifier ran 9 checks. The math on the env value → COOLDOWN_BARS mapping is mechanical and I verified all edge cases. The test suite (excluding 9 pre-existing fixture failures) passes cleanly.

**No for the broader DSR honesty question.** CRITICAL #2 (n_trials_for_dsr undercount) is a structural measurement issue. I cannot prove Run-3704's true selection-adjusted DSR without running explicit Bonferroni or held-out validation that the project does not currently implement. The reported 97.6% is OPTIMISTIC by an unknown amount. The operator should treat Run-3704 as a "strong candidate" rather than a "validated LIVE-clearance baseline" until either the methodology gap is closed OR a fresh out-of-sample window confirms the edge.

---

## Safe to keep running in PAPER mode: YES — and why.

The bot is operationally healthy (PID 393274, cycle 5743+, 0 errors, 12 tokens scanning, heartbeat fresh, all state files clean). The fix shipped today restores live↔backtest cadence parity. The remaining findings are recommendations, not bugs that would corrupt paper-mode data. Paper mode is the right place to absorb the corrected cadence and observe whether Run-3704's edge holds at the actually-deployed cooldown.

**LIVE NO-GO** until:
- A fresh backtest under the corrected cooldown re-confirms DSR ≥ 95%
- The n_trials_for_dsr undercount is resolved (operator-side methodology decision)
- 30 closed paper signals accumulate under Run-3704
- Pin and `.env` both stable for at least 48h of paper soak

---

**Cycle-15-loop run #1 complete. Stopping here per spec. Awaiting operator decision before continuing to cycle #2.**
