# TradeAI Skill Run History

All skill runs are logged here. Format per line:
`[DATE] | [SKILL] | [KEY METRICS] | [VERDICT/STATUS] | [MAIN FINDING]`

Newest entries at the top.

---

<!-- Skill runs will be appended here automatically after each run -->
[2026-05-23] | backtest-bias-detector | OHLCV cache review | VERDICT=VALID | No lookahead/snooping. 2 MODERATE (both directionally conservative): stale cache shrinks OOS window; tracker.py tune-triggered runs reuse cache (PA-12b queued). M20 _valid_candle guard confirmed still in place.
[2026-05-23] | backtest-cache | OHLCV disk cache shipped | data/ohlcv_cache/ | fetch_cached() wraps fetch_historical(); key={symbol}_{interval}_{days}d.json; auto-invalidates on BACKTEST_DAYS change; --fresh/--clear-cache flags; reduces re-runs 25min→2-3min; bias-detector verified: no lookahead risk
[2026-05-23] | backtest-optimizer | Session 4 B-series | n=46 WR=76.1% z=+3.54 | B-4 ACCEPTED (TON +4 signals WR=75%); B-1/2/3/5/6/7/8/9 REJECTED; FVG=HIGH structural ceiling confirmed; 10 tokens now; BACKTEST_DAYS=365
[2026-05-22] | tradeai-health | GREEN | signals=0/30 | clean — config now centralized via PA-7 (config.py); no new findings vs 2026-05-21b; paper trading still not started
[2026-05-21] | tradeai-backtest | n=38 WR=78.9% z=+4.08 NetE=+1.355% MaxDD=3.67% | REGRESSION | WR −6.4pp vs Run-60 (78.9% vs 85.3%); 5M iFVG precision entry (58.3% WR, 12 sigs) is primary drag; FVG fallback alone = 88.5% WR; Max DD worsened; signal freq improved to 38/yr
[2026-05-21] | tradeai-audit | overall=6.6/10 | CRITICAL=1 HIGH=7 MEDIUM=8 LOW=13 | NO-GO (Telegram token not rotated; N=0 paper signals; TOKEN_RT_COST mismatch) | First post-fix scored audit; improved from 3.3→6.6/10; 72/76 prior issues verified fixed; 28 new findings; MSS gate divergence is highest-priority code fix
[2026-05-21b] | tradeai-health | GREEN | signals=0/30 | All prior YELLOW items resolved: E-1 rejected/reverted, DR-1 added to CROSS_REF, legacy OGD tokens cleaned
[2026-05-21] | tradeai-health | YELLOW | signals=0/30 | E-1 experiment (ENTRY_WINDOW=96) unresolved; dealing_range_gate drift not in CROSS_REF; system structurally sound, paper trading not yet started
[2026-05-22] | tradeai-config-validate | CONSISTENT | FAIL=0 | all clear (post Fix #1: 1h limit 210→600)
[2026-05-22] | tradeai-backtest | n=37 WR=81.1% z=+4.15 | STABLE | Fix #1: 1H limit 210→600 (C-N3 EMA200 convergence)
[2026-05-22] | tradeai-audit | overall=7.06/10 | CRITICAL=5 HIGH=5 | NO-GO live, GO paper | +0.46 from 5-fix remediation; OGD +2, Adaptive +1, Live/BT +0.5
[2026-05-22] | tradeai-backtest | n=42 WR=76.2% z=+3.83 | STABLE | Fix #6: backtest BTC filter removed (C-N1 harmonized) — +5 BUY signals admitted, WR drops 4.9pp (honest re-calibration)
[2026-05-22] | tradeai-audit | overall=7.13/10 | CRITICAL=4 HIGH=5 | NO-GO live, GO paper | Cycle 2: C-N1 fixed (Live/BT +0.5), C-N2 KNOWN STRUCTURAL
[2026-05-22] | tradeai-audit | overall=7.22/10 | ICT cycle 3: +0.75 to ICT dim (8→8.75) | GO paper, NO-GO live | Fixes 8,9,10 canonical-correct, OB deferred
[2026-05-22] | tradeai-audit | overall=7.41/10 | Risk dim 7→8.5 (+1.5) | LIVE conditional GO post-paper-N30 | Fixes 11/12/13: CRIT-1/2 closed + correlation block
[2026-05-22] | tradeai-audit | overall=7.53/10 | Backtest dim 5→6 (+1.0) | GO paper-trading per auditor | Cycle 5: Wilson CIs + Bonferroni verified
[2026-05-22] | tradeai-audit | overall=7.66/10 | Backtest dim 6→7 (+1.0) | Cycle 6 Fix #16: canonical split-exit P&L model
[2026-05-22] | tradeai-audit | overall=7.98/10 | CRITICAL=4 HIGH=5 MEDIUM=7 LOW=6 | NO-GO live, GO paper | Cycle 7 full 8-agent re-audit: ICT 9.5, Live/BT 10.0, Data 9.3, OGD 9.0 — but Template regressed 6→4 (DR + SMT) and Backtest 7→5.5 (DSR NameError)
[2026-05-22] | tradeai-fix-session | 4 CRITICAL closed | 375/375 tests | autonomous loop | Fixes #29-32: DSR DB_PATH, DR confluence flip, SMT bonus flip, tracker.py PARTIAL counting
[2026-05-22] | tradeai-audit | overall=8.75/10 | CRITICAL=0 HIGH=6 MEDIUM=7 LOW=6 | NO-GO live, GO paper | Cycle 8 post-fix verification: Template 4→9 (+5), Adaptive 8.5→9.2, Backtest 5.5→6.0; loop continues toward ≥9.0 termination
[2026-05-22] | tradeai-fix-session | 4 cycle-9 + 1 cycle-10b fixes | 375/375 tests | autonomous loop | Fixes #33-36: env-var mirrors, correlation set XRP/ADA, stale test, DEGEN→0.40; cycle-10 caught Fix #34 SQL desync → patched inline as #34b
[2026-05-22] | tradeai-audit | overall=8.96/10 | CRITICAL=0 HIGH=3 MEDIUM=7 LOW=5 | NO-GO live, GO paper | Cycle 10 verification: Risk 8.0→9.0, OGD 9.0→9.5, Adaptive 9.2→9.4; 0.04 short of 9.0 termination; cycle 11 fix #37 queued (MAX_SL_PCT migration)
[2026-05-22] | tradeai-fix-session | Fix #37 MAX_SL_PCT/MIN_SL_PCT → config.py | 375/375 tests | autonomous loop | Cycle 11 single-fix to cross 9.0 threshold
[2026-05-22] | tradeai-audit | overall=9.025/10 | CRITICAL=0 HIGH=3 MEDIUM=7 LOW=4 | TERMINATION | Cycle 12 FINAL: Risk 9.0→9.5; loop terminates per spec (score≥9.0 + 0 critical + 375/375 tests); 10 fixes applied across cycles 7-11; 3.3→9.025 in 2 days (+5.73)
[2026-05-23] | tradeai-audit | overall=8.94/10 (11 dims) | CRITICAL=1 (TON unseeded — fixed inline) HIGH=2 (heartbeat init, Tier B>A) | GO (paper) / NO-GO (LIVE — needs N>=30 paper signals) | Cleared for paper trading; F-8 promoted, FIX 1 Part 2 verified, Sprint 3 dimensions all >=9.0
[2026-05-24] | tradeai-health | GREEN | signals=0/30 | Run-168 baseline holds; Run-172 PASS DSR=100%; F-8+TP-2-b promoted in parity; TON added (10 tokens); 2 WARN pins on dr_location (BNB/TON) bootstrap artifact
[2026-05-24] | tradeai-audit | overall=8.89/10 (11 dims) | CRITICAL=3 HIGH=4 MEDIUM=6 LOW=9 | GO (paper) / NO-GO (LIVE) | post-DB-reset: cross_config_sr_trial_std null → verdict-bypass gap; tradeai-watchdog.service missing on disk; Tier A vs B z=0.65 indistinguishable; SMT sign contradiction confidence-vs-template; no CROSS_REF regressions
[2026-05-25] | tradeai-audit | overall=8.86/10 (11 dims) | CRITICAL=3 HIGH=4 MEDIUM=9 LOW=9 | GO (paper) / NO-GO (LIVE) | cycle-2 post-VPS-hardening: C-A+C-C closed (cross_config_std seed + watchdog deployed); Resilience 8.5→9.2 (+0.7), Config 9.4→9.6 (+0.2); deeper inspection found 2 NEW CRITICAL (C-D n_trials_for_dsr undercount post-wipe, C-E SMT sign regression in backtest.py:990) + 1 NEW HIGH (BTC feed no Telegram); Backtest 7.0→6.5 (−0.5) Honest Metrics 8.2→7.8 (−0.4) OGD 9.5→9.3 (−0.2); net flat
[2026-05-26] | tradeai-audit | overall=9.00/10 (11 dims) | CRITICAL=1 HIGH=6 MEDIUM=10 LOW=9 | GO (paper) / NO-GO (LIVE) | cycle-3 post-Phase-A: GAP-1/7/8 closed (execution.py realistic-fill model + 29 tests); Run-77 promoted as honest baseline (CPCV 85.27%, Sharpe 1.180, n=34, same config_hash as Run-168); cycle-2 C-D + C-E + C-B all VERIFIED FIXED (commit 01416ec); Backtest 6.5→8.0 (+1.5), Honest Metrics 7.8→8.6 (+0.8), OGD 9.3→9.6 (+0.3); side-effects Template 7.5→6.5 (−1.0 Phase-A sample-size collapse, FVG=HIGH 100% base rate) + Live/BT 10.0→9.7 (−0.3 derive_seed PYTHONHASHSEED non-determinism); 9.0+ termination threshold crossed first time
