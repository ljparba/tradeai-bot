# TradeAI Audit Cross-Reference Index

**Purpose:** Prevent agents and skills from re-reporting issues that are already resolved, skipped, or acknowledged as structural limits. Read this file FIRST before finalizing any finding.

**How to classify a finding:**

| Classification | Meaning | Action |
|----------------|---------|--------|
| **REGRESSION** | Was DONE, now broken again | Highest priority — flag immediately |
| **KNOWN STRUCTURAL** | Architectural limit; acknowledged, not fixable without major rework | Document the limit; do not flag as new |
| **STILL OPEN (SKIPPED)** | Was deferred; low priority; no fix planned | Flag only if severity increased |
| **VERIFIED FIXED** | Code was changed; should remain fixed | Confirm still in place; flag if reversed |
| **NEW FINDING** | Not in this index at all | Full severity assessment; add to priority list |

---

## CRITICAL Issues — All Handled

| ID | Description | Final Status | Notes for Agents |
|----|-------------|-------------|-----------------|
| C1 | Real Telegram tokens hardcoded in env.bat | DONE — tokens removed from files | Manual token rotation via BotFather still required by operator |
| C2 | Walk-forward split not a true hold-out | **RESOLVED — 2026-05-26 (Phase C)** | Shipped `walk_forward.py` (expanding-window WFV + held-out lockbox) + `validation.py:cpcv_summary_split()` + `scripts/validate_baseline_held_out.py` (one-shot tool) + `docs/held_out_protocol.md`. `backtest.py:HELD_OUT_DAYS` env (default 0, opt-in) splits the most-recent N days as a never-tuned lockbox. `promote_baseline.py --auto` blocks promotion on OVERFIT verdict. 12 unit tests pass. Forward-looking honesty restored from 2026-05-26 onward; prior contamination of the tuning portion is acknowledged in `held_out_protocol.md` §5a (the operator's LIVE paper trading is the ground truth). |
| C3 | iFVG spatial gate absent in backtest | DONE via M7 | Both backtest.py and crypto_alert.py now use `_ifvg_spatially_valid` |
| C4 | Regime ADX thresholds static (backtest) vs DriftDetector-adjusted (live) | KNOWN STRUCTURAL | Architectural divergence deferred post-live; flag if DriftDetector thresholds shift regime classification by >10% |
| C5 | OHLCV validation missing close/open bounds | DONE | `close < low` and `close > high` guards added to fetch_binance_candles() |
| C6 | Kill switches bypassed in PAPER mode | DONE | 2-line early return removed; all kill switches active in PAPER |
| C7 | Drawdown gate uses trade-price-% not capital-impact-% | DONE | Multiplied profit_pct by RISK_PER_TRADE_PCT; threshold no longer off by 100× |
| C8 | YOUR_CAPITAL default $1000 — no LIVE enforcement | DONE | Hard-stop guard in LIVE block; refuses startup if env var unset or default |
| C9 | Regime detection uses forming 1H bar in backtest | DONE (FALSE ALARM) | Symmetric — live also uses forming bar; explanatory comment added |
| C10 | EXECUTION_MODE hardcoded string | DONE | Now reads from env var; ValueError guard at module level |
| C11 | profit_pct double-conversion undocumented | DONE | Documentation-only; both sides documented with warning comments |
| C12 | DR metadata stored from wrong reference price | DONE | Unified to FVG edge reference; ~12 downstream reads corrected |

---

## HIGH Issues — All Handled

| ID | Description | Final Status | Notes for Agents |
|----|-------------|-------------|-----------------|
| H1 | Displacement: no ATR minimum (flat-market noise) | DONE | 14-bar ATR proxy added; body must be >= 0.4× ATR |
| H2 | MSS sequence guard off-by-one | DONE (FALSE ALARM) | Guard is arithmetically correct; no code change |
| H3 | OGD bootstrap: no degenerate weight check on output | DONE | `_check_degenerate()` helper added; post-bootstrap warning loop |
| H4 | Consumed sweeps not tracked in backtest loop | DONE | `consumed_sweeps_abs` dict added before bar loop |
| H5 | No recency constraint on MSS — ancient setups fire | DONE | `ICT_MAX_SETUP_AGE_BARS=24` added to ict_engine.py |
| H6 | OGD weights from prior backtest runs contaminate later runs | DONE | Backtest scoring uses AE_DEFAULT_WEIGHTS only; bootstrap still trains |
| H7 | Entry reaction look-back: 4 bars backtest vs 6 bars live | DONE | `ENTRY_REACTION_LOOKBACK=4` constant; both paths use 4 |
| H8 | OGD updates at n=10, signal path ignores until n=30 | DONE | Two-path gate: bootstrap OR n>=OGD_MIN_SAMPLES(10) |
| H9 | Decay rate erases 64% of learned weights between signals | DONE | decay_rate 0.002 → 0.0004; 82% retention per inter-signal gap |
| H10 | Kill switch only at startup — bypassable via import | DONE | Inline env-var check in generate_signal(); raises RuntimeError |
| H11 | Drawdown uses 20-trade rolling window, not equity curve | DONE | Full chronological equity curve with running peak |
| H12 | EXECUTION_MODE read from two independent sources | DONE | Resolved by C10; both sources now read from env var |
| H13 | Kill switch daily loss uses count×1% not actual P&L | DONE | SUM(profit_pct) used; EXPIRED trades contribute 0 |
| H14 | YOUR_CAPITAL: notional can reach 100% on tight stops | DONE | MAX_POSITION_PCT 1.0 → 0.20; gap-through worst case = 20% |
| H15 | API retry storm: worst-case 752s (vs 90s target) | DONE | API_RETRIES 3→2, API_DELAY 10→3; worst case ~252s |
| H16 | Stale candle guard not applied to TP/SL monitor | DONE | Staleness check added inside monitor_open_signals() |
| H17 | BTC 10-minute filter staleness (BTC_FETCH_INTERVAL=600s) | DONE | 600s gate removed; BTC recomputes every cycle from STATE |
| H18 | BTC feed failure silently enables all alt signals | DONE | feed_ok flag added; BLOCK when feed_ok=False |
| H19 | Gap in 5M data: detection logs warning, no action | DONE | max_gap_bars propagated; skip guard at >= 3 bars |
| H20 | env.example.bat not in .gitignore | DONE | Fixed as part of C1 |
| H21 | tracker.py counts PARTIAL as full win (WR inflated) | DONE | PARTIAL weighted 0.5 at both get_intelligence() and adaptive weights |
| H22 | adaptive_engine.py uses datetime.now() (local time) | DONE | replace_all: datetime.now() → datetime.utcnow() |
| H23 | No auto-start on machine reboot | DOCUMENTED | Task Scheduler command in FIX_LOG.md; operator task |
| H24 | LIVE alert fires before init_db() | DONE | Alert moved to after init_db() + restore_cooldowns() |
| H25 | DR classification corrupts confidence scores (C12 HIGH aspect) | RESOLVED BY C12 | No separate code change; historical data corrects via OGD |

---

## MEDIUM Issues — All Handled

| ID | Description | Final Status | Notes for Agents |
|----|-------------|-------------|-----------------|
| M1 | MSS lookback uses magic number 30, not constant | DONE | Uses ICT_SWEEP_LOOKBACK constant |
| M2 | ASIA_KZ includes UTC 00-01 (dead zone) | DONE | Hours 0-1 → OVERNIGHT; ASIA_KZ = 20:00-23:59 UTC |
| M3 | DR uses rolling stats range not structural swing extremes | DONE | find_ict_swings() replaces rolling max/min |
| M4 | FVG mitigation uses outer edge not 50% midpoint | KNOWN STRUCTURAL | ICT 50% midpoint rule was implemented, then reverted: Run 41 empirical data showed full-fill FVG entry (outer edge) produces higher WR. Entry uses full FVG zone. See ict_engine.py:255-264 for documented rationale. Do NOT flag as regression — the revert was intentional and data-driven. |
| M5 | DR gate blocks EQUILIBRIUM only; PREMIUM/DISCOUNT wrong | DONE | BUY+PREMIUM and SELL+DISCOUNT also blocked |
| M6 | Cooldown anchored to entry bar not detection bar | DONE | Cooldown now anchors to detection bar i |
| M7 | iFVG confirmation checks historical reclaim only | DONE | `_ifvg_spatially_valid` used in template scoring and DB |
| M8 | Slippage double-counted in backtest eff_price | DONE | eff_price = entry_price; ROUND_TRIP_COST_PCT covers all costs |
| M9 | Walk-forward: ~14 OOS signals, CI spans ±26pp | DONE | Wald 95% CI warning printed when OOS n < 30 |
| M10 | Survivorship bias: SOL excluded on backtest performance | DONE | Documentation-only; inline comment + optimization_experiments.md |
| M11 | Signal count overstated: portfolio limits not modeled | DONE | Documentation-only; NOTE(M11) in print_report() header |
| M12 | Live trigger sends generic PARTIAL (not TP1/TP2) | DONE | PARTIAL_TP1 and PARTIAL_TP2 wired through; OGD reward table updated |
| M13 | Confidence circular feedback loop in OGD gradient | DONE | Documentation-only; direct loop already broken; KNOWN LIMITATION comment |
| M14 | No SELL-bias guard in bootstrap input data | DONE | Alignment-balance warning at 60%; soft-threshold alert at 3× default |
| M15 | ROUND_TRIP_COST_PCT understates fees for HBAR/POL/ADA | DONE | TOKEN_RT_COST dict: ADAUSDT=0.004, POLUSDT/HBARUSDT=0.005 |
| M16 | MAX_CONSECUTIVE_LOSSES not persistent across restarts | DONE | Root cause: PARTIAL IN-clause missing PARTIAL_TP1/TP2 values — fixed |
| M17 | CIRCUIT_BREAKER_MIN_WR=0.35 too low | DONE | Raised to 0.55; LOOKBACK 10→20 |
| M18 | MAX_PORTFOLIO_RISK_PCT=0.15 dead gate | DONE | Lowered to 0.03 (fires on 4th concurrent position) |
| M19 | No warning when Binance returns fewer candles | DONE | [WARN-THIN] check added after validation |
| M20 | No OHLCV validation in backtest fetcher | DONE | `_valid_candle()` helper added to backtest.py |
| M21 | Exit intelligence uses forming 5M candle | DONE | `[:-1]` added to closes_5m; forming bar excluded |
| M22 | _GAP_TOLERANCE=2 accepts 2 missing candles silently | DONE | [WARN-GAP] log for sub-tolerance gaps |
| M23 | tracker.py hardcodes _MAX_OPEN=3 | DONE | Imports MAX_OPEN_POSITIONS from adaptive_engine |
| M24 | liquid_hours=range(24) removes session filtering | DISPUTED | Checklist fix: set to None (ICT killzones). Current code: range(24) per F-1 acceptance. Both LIVE and BACKTEST match — no config drift. Do NOT flag as bug unless they diverge from each other. |
| M25 | Kill switch daily loss uses count×1% | DONE | Resolved by H13 fix |
| M26 | No startup Binance connectivity check | DONE | Pre-flight GET /ping added before main loop |
| M27 | Readiness report has stale parameters | DONE | Report updated with current parameters |

---

## LOW Issues — 8 Done, 4 Skipped

| ID | Description | Final Status | Notes for Agents |
|----|-------------|-------------|-----------------|
| L1 | 4H bias uses max() of last 3 swings | DONE | Uses most recent swing level sh[-1][1] |
| L2 | Displacement body calc fails near warmup start | SKIPPED | Warmup window only; no live impact |
| L3 | FVG mitigation guard condition redundant | SKIPPED | Purely cosmetic |
| L4 | NY_AM_KZ starts at UTC 12 (should be 13) | SKIPPED | Dead code — UTC 12 not in liquid_hours |
| L5 | TP2 can land below TP1 under specific edge cases | SKIPPED | Cannot reproduce; likely fixed incidentally |
| L6 | datetime.now() inconsistency in adaptive_engine.py | DONE | Pre-resolved by H22 fix |
| L7 | health_check() not called after bootstrap | DONE | `_check_degenerate()` inline helper runs immediately after bootstrap OGD completes. `health_check()` is NOT the correct check here — it reads from `token_weights` (live weights table) while bootstrap writes to `backtest_token_weights`. Calling `health_check()` post-bootstrap would always read live state, not bootstrap results. Do NOT flag as regression. |
| L8 | CoinGecko: no retry backoff, stale dom_dir persists | DONE | After 3× DOM_FETCH_INTERVAL, dom_dir forced NEUTRAL |
| L9 | Daily summary RSI uses forming candle | DONE | Pre-resolved by M21 fix |
| L10 | No 429 handling in backtest fetcher | DONE | Retry-After header read; sleep on 429 |
| L11 | tracker.py uses local time for bot_active calculation | DONE | datetime.utcnow() used |
| L12 | Readiness report token table shows SOL | DONE | Resolved by M27 |

---

## Summary

| Severity | Total | Verified Fixed | Known Structural | Skipped | Disputed |
|----------|-------|----------------|-----------------|---------|---------|
| CRITICAL | 12 | 11 | 1 (C4) | 0 | 0 |
| HIGH | 25 | 23 | 1 (H23 operator task) | 0 | 0 |
| MEDIUM | 27 | 26 | 0 | 0 | 1 (M24 liquid_hours) |
| LOW | 12 | 8 | 0 | 4 | 0 |
| **Post-Audit** | **5** | **2** | **3 (CF-1, C-N2, C-N3)** | **0** | **0** |
| **Sprint 1 Infra** | **6** | **6** | **0** | **0** | **0** |
| **Sprint 2 Infra** | **5** | **5** | **0** | **0** | **0** |
| **Sprint 3 Infra** | **2** | **2** | **0** | **0** | **0** |
| **Total** | **94** | **81** | **7** | **4** | **1** |

**Items agents should NOT flag as new bugs:**
- C2 (walk-forward OOS) — RESOLVED 2026-05-26 Phase C; held-out lockbox shipped. C4 (ADX drift — deferred), H23 (auto-start — operator task)
- L2, L3, L4, L5 (intentionally skipped)
- M24 (liquid_hours — DISPUTED; only flag if LIVE vs BACKTEST configs diverge from each other)
- DR-1 (dealing_range_gate — RESOLVED 2026-05-26 Phase B.1; gate now symmetric LIVE=true / BACKTEST=true. See Post-Audit row for n=7 caveat.)
- CF-1 (adaptive confidence floors — KNOWN STRUCTURAL; see Post-Audit section below)
- C-N1 (BTC trend filter — VERIFIED FIXED 2026-05-22; backtest BLOCK removed)
- C-N2 (EV gate in backtest — KNOWN STRUCTURAL; activates post-paper-N≥30)

**Items agents should verify are STILL FIXED (regression-prone):**
- C6 (kill switch bypass), C8 (capital guard), C10 (EXECUTION_MODE env var), H4 (consumed sweeps), H14 (position sizing)

---

## Post-Audit Known Items (added after initial 76-issue pass)

| ID | Description | Final Status | Notes for Agents |
|----|-------------|-------------|-----------------|
| DR-1 | `dealing_range_gate`: LIVE_CONFIG=True vs BACKTEST_CONFIG=False | **RESOLVED — 2026-05-26 (Phase B.1)** | `config.py:329` flipped `BACKTEST_DEALING_RANGE_GATE: false → true`. Gate is now symmetric across live + backtest. Run-78 verification baseline: n=7 (was 34 pre-flip), CPCV mean WR 87.5%, DSR 99.9%, VERDICT PASS. The DR gate filter rate is ~79% in backtest — significantly more aggressive than the roadmap's predicted ~50-60%; this is a real sample-size cliff. Backtest is no longer a precise predictor of live WR at n=7, but the structural divergence (which was the audit-correctness concern) is closed. Files: `config.py:329`, `strategy_engine.py` lines 126/139 (no longer divergent). For ongoing R&D, treat backtest CPCV mean as VERDICT-only at this sample size; CPCV q05 + DSR are the only reliable discriminators. See `docs/LIVE_BACKTEST_PARITY_ROADMAP.md` Phase B for derivation + n=7 caveat documentation. |
| CF-1 | Adaptive confidence floors (`_conf_floor`, `_signal_threshold_adj`, `_wr_extra`) applied in live but not backtest | KNOWN STRUCTURAL | Backtest uses static floor=5 (the initial starting value). Live adaptive increments only activate after live signals accumulate — backtest correctly models the bot's fresh-start behavior. The static floor=5 is already enforced via `max(5, ...)` in both paths. Explicit static check added to backtest.py to make code symmetric. Full adaptive modeling would require loading live history into backtest (H6-style contamination risk). Do NOT flag as config drift. File: crypto_alert.py:2432-2453 (live), backtest.py confidence floor check. |
| TT-1 | T21 source-code scan for PARTIAL_TP1/2 | REMOVED — FALSE PREMISE | T21 was scanning source code for uses of PARTIAL_TP1/2 outside backtest context. Removed because PARTIAL_TP1/2 ARE legitimate intermediate live result values (TP2 hit, TP3 pending). T2 already verifies the actual DB has no unexpected values. Do NOT recreate T21. |
| TT-2 | A13 fvg_min_quality pattern mismatch | VERIFIED FIXED | strategy_engine.py uses 6-space alignment `fvg_min_quality      = "HIGH"`. test_tunebot.py now checks all 4 spacing variants (0, 1, 4, 6 spaces). Do NOT flag A13 as flaky — it was a test bug, not a code bug. |
| TT-3 | Max 2 APPLIED guard | VERIFIED FIXED | tracker.py:apply_tune_adjustments() Phase 3.5 gate: blocks apply if ≥2 rows with `status='APPLIED' AND signals_at_apply > 0`. Test-cycle rows (signals_at_apply=0) are excluded. Do NOT remove this guard. |
| TT-4 | VERIFIED_WORSE Telegram alert | VERIFIED FIXED | crypto_alert.py:load_performance_state() now sends Telegram alert when tune_history verdict → VERIFIED_WORSE. Wrapped in try/except so Telegram error never breaks the perf loop. |
| TT-5 | Wilson CI missing from FVG/MSS quality notes | VERIFIED FIXED | tracker.py:calculate_tune_preview() FVG and MSS quality breakdown notes now include `[lo-hi%]` Wilson CI. Session and confidence notes already had CI. |
| TT-6 | OGD health warning in confirm overlay | VERIFIED FIXED | tracker_html.py confirmTune() now populates `#tuneConfirmOgdNote` explaining OGD weights will be re-bootstrapped on apply. HTML element added to overlay. |
| TT-7 | _tune_wr() PARTIAL miscounting | VERIFIED FIXED | tracker.py:_tune_wr() now counts PARTIAL_TP1/TP2 as 0.5 wins and uses only closed outcomes in denominator. Consistent with _canonical_wr() and _weighted_wr(). Do NOT revert to counting PARTIAL as 1.0. |
| C-N1 | BTC trend filter divergence (2026-05-22 audit Top-5) | VERIFIED FIXED | Backtest's unconditional `if btc_bear/btc_bull: continue` (was `backtest.py:705-711`) rejected signals live admits with `-1 conf` penalty. Resolution: backtest BTC trend BLOCK stripped. Backtest now matches live's `dom_dir != "RISING"` common case (~75% of bearish-BTC time). Remaining structural gap: backtest cannot replicate live's `btc_bear AND dom_dir == "RISING"` BLOCK because no historical CoinGecko dominance series exists; net effect is backtest slightly looser than live during heavy-alt-bleed days only. Do NOT re-add the unconditional filter. File: backtest.py:705-723 (now docs only). |
| C-N2 | EV gate present in live, absent in backtest | KNOWN STRUCTURAL | Live `compute_ev_score` (crypto_alert.py:2400-2422) queries the live `signals + results` DB to gate on negative expected value. Currently INERT in live because N_closed_live = 0; activates only when bucket sample_n ≥ SAMPLE_N_USABLE. Backtest cannot replicate without one of: (a) cross-run history query against `backtest_signals` (philosophically debatable — introduces optimizer feedback bias), (b) in-run accumulation (always inert at typical 37-signal/run scale), or (c) replay against live signal history (only meaningful once N≥30 lives accumulate). **Activation condition: once live `signals` table contains ≥30 closed rows per (regime, sweep_type) bucket, this divergence begins to matter — backtest WR will overstate live WR by the amount the EV gate filters.** Plan: re-validate backtest against live history after first 50 paper signals. Do NOT implement EV-in-backtest until paper trading produces a meaningful baseline. File: crypto_alert.py:2400-2422 (live only); backtest.py has TODO marker. |
| C-N3 | Backtest cooldown gates on DETECTION bar; live cooldown gates on WALL CLOCK at ENTRY — same-entry-bar collisions possible in backtest only | KNOWN STRUCTURAL — surfaced 2026-05-22 Run 93 | Backtest [`backtest.py:778`](backtest.py#L778) checks `(i - last_signal_bar) < COOLDOWN_BARS` where `i` is the DETECTION bar. Live [`crypto_alert.py:2247-2249`](crypto_alert.py#L2247) checks `(now - last_signal_times[direction]).total_seconds()/60 < SIGNAL_COOLDOWN` where `last_signal_times` is the SEND time (≈ entry bar). Effect: two sweeps detected 9+ bars apart can BOTH find their entry on the same ENTRY_WINDOW=72 bar in backtest and both fire; in live, the first signal's send-time would block the second from passing cooldown. Run 93 exposed this — 2 duplicate entry-timestamp clusters (XRP BUY 2025-07-07 18:20, ADA BUY 2025-07-11 07:20). Run 48 did not happen to surface it (no collisions in that market window). This is **NOT a Sprint 2 regression** — it's a pre-existing structural divergence latent until the right market geometry. **Severity:** LOW for current paper baseline (n=2 of 42 = 4.8% noise, both within bootstrap CI); MEDIUM once live trading starts (live will produce fewer signals than backtest predicts in collision-prone windows). **Fix path (deferred):** Either (a) repoint backtest cooldown to anchor on entry-bar timestamp (mirrors live), or (b) add a post-hoc `(ts, token, signal)` dedup in `save_to_db()` before persisting. Do NOT implement either until Sprint 3 starts — touching backtest cooldown logic before the news-fetcher work would conflate two unrelated diffs. Re-baseline Run-48 after the fix lands. |
| C-N4 | DSR silently disabled by `DB_PATH` NameError | VERIFIED FIXED — 2026-05-22 cycle 7 Fix #29 | `backtest.py:2839` referenced undefined `DB_PATH`; module defines `BT_DB_PATH = ...` at line 151. Outer `except` swallowed NameError → CPCV/DSR block always skipped → deflated Sharpe never computed → reported Sharpe never corrected for 93+ optimizer trials. Fix: one-char `DB_PATH` → `BT_DB_PATH`. Do NOT re-flag. After next backtest run, expect reported Sharpe to materially decrease (DSR deflation by ~sqrt(log(n_trials))). |
| TPL-DR | DR confluence in strategy_templates.py expected `BUY+DISCOUNT/SELL+PREMIUM` (pre-sweep geometry) but bot emits `BUY+PREMIUM/SELL+DISCOUNT` (post-displacement geometry) | VERIFIED FIXED — 2026-05-22 cycle 7 Fix #30 | Run #85 data: 22 BUYs all in PREMIUM/UNKNOWN, 20 SELLs all in DISCOUNT/UNKNOWN → 0/42 satisfied old check. Tier-A silently capped at 4-of-5, fired only 1/42. Resolution: flipped to canonical post-displacement semantics in all 3 tiers (Tier A line 135-137, Tier B line 205-207, Tier C line 273-275). Replacement check is near-uniform in current data — genuine Tier-A discrimination requires pre-sweep DR snapshot (Tier-A redefinition still open as HIGH carry-over). Do NOT re-flag DR semantics. |
| TPL-SMT | SMT bonus signed as penalty (-0.10) per stale Run 48 finding; Run #85 shows SMT is +12pp predictive | VERIFIED FIXED — confidence-integer path resolved 2026-05-25 (cycle-2 audit C-E). | Template side flipped 2026-05-22 cycle 7 Fix #31: `bonus += 0.10` in all 3 tiers (Tier A line 149-150, Tier B line 220-221, Tier C line 276-277). Label `SMT_penalty` → `SMT_bonus`. Confidence-integer path was missed initially; flipped 2026-05-25 in commit `01416ec`: `backtest.py:990` + `crypto_alert.py:2431` now use `smt_bonus = +1 if smt_confirmed else 0` and the formula on `backtest.py:1027` / `crypto_alert.py:2456` adds it (was subtracting). After fix re-validate vs ~50 closed paper signals — if SMT becomes anti-predictive again, restore the negative weighting. |
| GAP-1 / GAP-7 / GAP-8 (Phase A) | Backtest assumed perfect fills at signal price + flat 30bps RT cost; live has real latency + spread-by-time-of-day + partial fills + stale-price-reject + adverse selection | VERIFIED FIXED — 2026-05-26 Phase A.3 | `execution.py` simulates 5 friction components (deterministic, seeded). `backtest.py` integrates via env var `REALISTIC_EXECUTION` (default ON since A.3). 29 unit tests pass. Run-77 baseline: CPCV 85.27%, Sharpe 1.180, DSR 100% (n=34); was Run-168 CPCV 79.11%, Sharpe 0.933 (n=43). The honest model REJECTS stale-fill candidates, revealing genuine strategy strength. Disable via `REALISTIC_EXECUTION=0` to revert. See `docs/LIVE_BACKTEST_PARITY_ROADMAP.md` Phase A + `docs/exec_model_calibration.md`. Do NOT re-flag the old "perfect fill" assumption. |
| C-D (cycle-2 audit 2026-05-25) | `n_trials_for_dsr` undercounted post-DB-wipe (was 2; honest historical is 27) | VERIFIED FIXED — 2026-05-25 commit `01416ec` | Seeded `bot_state.cumulative_min_trials = 27` (one-time DB write). `backtest.py:3065` now reads it + uses `max(cumulative, db_count + 1)` so DB wipes can't reset selection-bias denominator. Verified in Run-76 + Run-77 reports: DSR header shows `[n_trials=27, ...]` instead of `[n_trials=2, ...]`. Do NOT delete the seed row. |
| C-E (cycle-2 audit 2026-05-25) | SMT sign contradiction between confidence integer path (-1 penalty) and template fractional path (+0.10 bonus) | VERIFIED FIXED — 2026-05-25 commit `01416ec` | Both now aligned: `backtest.py:990` + `crypto_alert.py:2431` set `smt_bonus = +1 if smt_confirmed else 0`. Adders updated at `backtest.py:1027` + `crypto_alert.py:2456`. See also TPL-SMT above. |
| C-B (cycle-2 audit 2026-05-25) | Verdict gate granted PASS when `out["dsr"]` is None (no multiple-testing correction applied) | VERIFIED FIXED — 2026-05-25 commit `01416ec` | `validation.py:640-660` now caps verdict at MARGINAL when DSR is None. PASS requires `dsr >= 0.95` AND `dsr_present == True`. New `out["dsr_gate_applied"]` flag for operator visibility. Seven smoke-test cases verified the logic. Do NOT revert. |
| TR-PARTIAL | tracker.py per-token WR and recent_wr split-counted PARTIAL variants | VERIFIED FIXED — 2026-05-22 cycle 7 Fix #32 (TT-7 class) | Two parallel paths in tracker dashboard never received TT-7's PARTIAL=0.5 upgrade. `tracker.py:180-204` per-token `w` was full-count of WIN+PARTIAL+TP1+TP2 (overstated WR); `tracker.py:197,272` `recent_wr` predicate `r in ("WIN","PARTIAL")` silently dropped TP1/TP2 to 0. Fixed by splitting into discrete WIN/PARTIAL/LOSS/EXPIRED counters routed through `_canonical_wr()`, and replacing predicate with explicit `_PARTIAL_SET = ("PARTIAL","PARTIAL_TP1","PARTIAL_TP2")`. Do NOT revert to single-COUNT. |
| RM-MIRROR | adaptive_engine.py `_MAX_POSITION_PCT` / `_RISK_PER_TRADE_PCT` mirrors silently ignored env-var overrides | VERIFIED FIXED — 2026-05-22 cycle 9 Fix #33 | `adaptive_engine.py:131-138` now reads via `_env_float()` helper. Operator overrides via `.env` / `config.py` now reach the drawdown gate (line 1051) and portfolio risk calc (line 1016). Do NOT revert to hardcoded literals. |
| RM-CORR | Correlation guard missing XRP and ADA (carry-over from cycle 1) | VERIFIED FIXED — 2026-05-22 cycle 9 Fix #34 + cycle 10 Fix #34b | `adaptive_engine.py:994` `CORRELATED` set now includes `XRP` and `ADA`. **Fix #34b (cycle 10):** SQL at `adaptive_engine.py:1088-1102` rebuilt to derive the IN-clause from `self.CORRELATED` dynamically — previous hardcoded `('BTC','ETH','BNB','AVAX')` literal silently bypassed the BLOCK count for the newly-added XRP/ADA. Now driven by single source of truth. Do NOT revert to a static IN-clause; mirror any future set change automatically. |
| OGD-DEGEN | DEGENERATE_THRESHOLD too lenient at 0.45 (AVAX 0.448 skimmed under) | VERIFIED FIXED — 2026-05-22 cycle 9 Fix #36 | Tightened to 0.40 in all 3 mirror sites: `adaptive_engine.py:56`, `monitoring.py:59`, `tracker.py:27`. CI test `tests/test_monitoring.py:41` catches drift between any two of these mirrors. Do NOT change any single mirror without updating all three. |
| TR-TEST-T14 | tests/test_tracker_db_alignment.py:T14 expected reference replicated the old PARTIAL miscounting bug | VERIFIED FIXED — 2026-05-22 cycle 9 Fix #35 | Test now uses canonical `1.0 if r=='WIN' else 0.5 if r in _PARTIAL_SET else 0.0` weighting and includes PARTIAL_TP1/TP2 in the IN-clause. File is in pytest --ignore= list (operator-run only). |
| RM-SL | MAX_SL_PCT / MIN_SL_PCT hardcoded in ict_engine.py; config.py docstring used MAX_SL_PCT as env-var example but the env var never propagated | VERIFIED FIXED — 2026-05-22 cycle 11 Fix #37 | Migrated to `config.py:188-189` with `_env_float()` defaults. `ict_engine.py:37` re-exports via `from config import MAX_SL_PCT, MIN_SL_PCT` so existing callers (crypto_alert.py:71, backtest.py:66) work unchanged. Single source of truth. Operator can now `set MAX_SL_PCT=0.025` for one run. Do NOT revert to module-level literals. |
| F-2 | Wednesday unblock experiment | VERIFIED REVERTED — 2026-05-23 B-series Session 4 | `config.py:281` reverted to `(1, 2, 5)` (Tue+Wed+Sat blocked). B-1 confirmed: under `BACKTEST_DAYS=365` regime, Wed produced 4 signals all TRENDING_BEAR SELL with WR=0%. Blocking Wed restores exact Run 93 baseline (n=42, WR=76.2%). Do NOT unblock Wednesday again without a data window that includes a new market regime change. The 0% WR is not a sample-size artifact — all 4 were qualitatively similar setups that failed at SL. |
| **C-NEW-1** (cycle-4 audit 2026-05-26) | `validation.py:592-598` (psr_oos) + `validation.py:617-623` (DSR) passed `n_returns=len(pnl_pool)` while `sr_observed=sharpe_mean` (mean of OOS fold Sharpes from ~`n/K*k` obs each). Per Bailey & López de Prado 2014 eq (1)-(2), T must = per-Sharpe observation count. Using full pool inflated `sqrt(T-1)` by ~1.67× → DSR overstated ~12pp. | **VERIFIED FIXED — 2026-05-26 cycle-4** | Fix applied in `validation.py:592-636`: psr_oos + DSR now use `n_oos_per_fold = max(1, int(n * n_test_groups / n_groups))` as T (Option A from audit; conservative interpretation of mean-of-K-estimators). `n_oos_per_fold` added to summary dict and surfaced in text report. **Run-79 honest baseline** verified the fix: DSR dropped 99.9% → 89.1% (−10.8pp), PSR(OOS) 99.9% → 89.8% (−10.1pp), verdict flipped PASS → FAIL (DSR below 95% gate). Same config_hash as Run-77/78 — strategy unchanged; this is the honest math finally being applied. Do NOT revert. |
| **FLAW-1** (cycle-4 audit 2026-05-26) | `backtest.py:3205` called `walk_forward(all_signals)` on FULL pool — contaminating held-out window when `HELD_OUT_DAYS > 0`. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `backtest.py:3199-3253` rewritten: `split_held_out()` now runs FIRST; `walk_forward()` operates on `_tune_sigs` only. When `HELD_OUT_DAYS=0` (default), behavior is byte-identical to pre-fix (no lockbox in effect, no contamination concern). Lockbox invariant restored. |
| **S-1** (cycle-4 audit 2026-05-26) | `walk_forward.py:375` `held_out_text_report` hardcoded "HELD-OUT LOCKBOX (final 90d window..." regardless of `HELD_OUT_DAYS`. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `held_out_text_report(ho, *, tuning_wr=None, held_out_days=90)` now accepts `held_out_days` and interpolates into the header string. Callers in `backtest.py:3246-3248` and `scripts/validate_baseline_held_out.py:155-158` pass the actual value. |
| **S-2a** (cycle-4 audit 2026-05-26) | `scripts/promote_baseline.py:_check_held_out_gate` called `cpcv_summary_split` without `n_trials_for_dsr` or `sr_trial_std_for_dsr` → tuning CPCV silently got `dsr=None`. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `_check_held_out_gate` now reads `n_trials_for_dsr` (anchored to `cumulative_min_trials=27`) + `sr_trial_std_for_dsr` from `bot_state` (same path as `backtest.py:3140-3164`) and passes both to the call. Honest DSR now applied at promotion time. Returns dict also includes `tuning_dsr` for operator visibility. |
| **S-2b** (cycle-4 audit 2026-05-26) | `scripts/promote_baseline.py:189` SELECT loaded only `ts, outcome, realized_r` — missing PnL columns → default pnl_func returned 0 → silent zero-Sharpe. | **VERIFIED FIXED — 2026-05-26 cycle-4** | SELECT extended to `ts, outcome, realized_r, net_tp1_pct, net_sl_pct, net_tp2_pct`. Signal dict construction now includes all PnL keys matching `validation._default_outcome_to_pnl` shape. |
| **OGD-MON-SCOPE** (cycle-4 audit 2026-05-26) | `monitoring.py` only reads live `token_weights` table; 99% of OGD learning actually lives in `backtest_token_weights`. Monitor + Run-46 fingerprint detector are operationally blind to the table that carries the real weight mass. | **STILL OPEN — HIGH** | Fix: add `--source {live,bootstrap}` flag; make `_fetch_current_weights` + `_fetch_recent_history` accept a `table` param. Until fixed, M-D / M-E / M-F fixes are necessary but insufficient. |
| **OGD-PHASEA** (cycle-4 audit 2026-05-26) | Phase A's stale-reject raised PARTIAL_TP1 share monotonically (18.6% → 20.6% → 28.6% across Run-1/76/77/78). PARTIAL_TP1 has 0.5 reward weight → effective gradient signal per signal is ~25% weaker post-Phase-A. Combined with smaller n, bootstrap learning capacity dropped ~40%. | **STILL OPEN — MEDIUM** | Not a bug — emergent consequence of Phase A. Fix: implement `n_effective` accounting in `_compute_reward()` so `OGD_MIN_SAMPLES=10` becomes effective-sample-count, not raw count. |
| **M-J** (cycle-4 audit 2026-05-26) | `adaptive_engine.py:475` `bootstrap_from_backtest()` selects from `MAX(backtest_runs.id)`. Run-78 produced n=7 — insufficient to populate 10 tokens. Tokens with <5 samples retain DEFAULT_WEIGHTS but masquerade as "bootstrapped" via the `_has_bootstrap` flag if any feature-weight drift survived rounding. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `adaptive_engine.bootstrap_from_backtest()` now applies a per-token thin-sample guard before degenerate-reject: if `n_bootstrap < BOOTSTRAP_MIN_N_PER_TOKEN` (default 5, env-overridable), substitute `DEFAULT_WEIGHTS` AND force `n_bootstrap = 0` so `_has_bootstrap` predicate in `crypto_alert.py:2031` correctly reads False. `[ADAPTIVE] bootstrap THIN ...` log line per affected token + summary at end. |
| **MOD-3** (cycle-4 audit 2026-05-26) | `walk_forward.py:57-58` `_default_is_win` treats `PARTIAL_TP1/TP2` as full win (returns True). Inconsistent with project-wide TT-7 convention where PARTIAL = 0.5 weight. WFV test_wr overstates in PARTIAL-heavy periods; decay slope based on inflated metric. | **STILL OPEN — MEDIUM** | Fix: change `_default_is_win` to a float-returning scorer matching TT-7, OR use a separate scoring function explicitly weighted. Same issue exists in `validation.py:414-415` (`_default_is_win`). |
| **M-H ESCALATED** (cycle-3 audit, cycle-4 compounded) | `REALISTIC_EXECUTION` was not in `_compute_run_config_hash()` payload (cycle-3 finding). Cycle-4: Phase C added `HELD_OUT_DAYS` as a SECOND env-driven knob that materially affects backtest output but is also outside the hash → silent collision vector. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `backtest.py:_compute_run_config_hash()` payload extended with `os.environ.get("REALISTIC_EXECUTION", "1")` AND `HELD_OUT_DAYS`. Verified: same code with different REALISTIC_EXECUTION env produces different hashes. DSR `COUNT(DISTINCT config_hash)` and Pareto-archive uniqueness now honor execution-model variation. |
| **H-A** (cycle-3 + cycle-4 carry-over) | `scripts/compute_cross_config_sr_std.py:81` `SELECT ts, outcome, ts as closed_at, ...` set `closed_at = ts` for every signal. Zero-length label windows disabled CPCV purging across cross-config Sharpe estimation → honest `sr_trial_std` in `bot_state` was slightly inflated. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `_load_signals_for_run()` now derives `closed_at` from `ts + tb_t1 * 5 minutes` (triple-barrier exit bar). When `tb_t1` is NULL (legacy / unfilled), falls back to ts+24h (matches validation.py:511 default). Real label windows now feed purging. Re-run `compute_cross_config_sr_std.py` to refresh the seeded value once ≥2 distinct configs have ≥30 signals. |
| **H-B** (cycle-3 + cycle-4 carry-over) | `validation.py:171` `_apply_embargo` anchored `forbidden_windows` at `t0[b_end]` (test event ENTRY) not `t1[b_end]` (label-window EXIT). Per López de Prado AFML §7.4 — embargo must extend from label END since that is where post-test autocorrelation begins. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `_apply_embargo` now takes optional `t1` kwarg and anchors at `t1[b_end]` when provided. Both CPCV call sites (`validation.py:230, 248`) updated to pass `t1=t1`. Backward-compatible: if `t1` is None, falls back to old `t0` anchor. |
| **H-F** (cycle-1+ carry-over) | `crypto_alert.py:1525-1531` BTC feed failure silently suppressed all alt signals via `feed_ok=False` but emitted no Telegram alert. Operator went silent without knowing why; open for 3+ cycles. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `crypto_alert.py:1525-1554` now sends a Telegram alert when feed transitions healthy → failed, with a 1-per-hour rate limit while the outage persists. Alert dedup tracked via `BTC_STATE["feed_alert_ts"]`. When the feed recovers and later fails again, a new alert fires (timer reset on recovery). |
| **OGD-MON-SCOPE** (cycle-4 audit 2026-05-26) | `monitoring.py` only read live `token_weights`; 99% of OGD learning lives in `backtest_token_weights` and was invisible to alerting. | **VERIFIED FIXED — 2026-05-26 cycle-4** | `monitoring.py` `_fetch_current_weights / _fetch_n_updates / _fetch_last_updated` and `generate_report()` now accept a `table` parameter. CLI added `--source {live,bootstrap}` flag (default `live` for backward compat). Report dict now surfaces `source_table` so operator knows which pool was audited. Verified: `--source bootstrap` shows all 10 tokens; `--source live` shows only the live-update tokens. |

---

## Phase A Pre-LIVE Hardening (Sprint 1 — 2026-05-22)

New enterprise infrastructure shipped end-to-end. Agents must NOT propose re-implementing any of these — check this section first.

| ID | Component | Final Status | Notes for Agents |
|----|-----------|-------------|-----------------|
| PA-1 | Dead-man's switch (heartbeat file + external watchdog) | DONE — Roadmap Phase A #2 | `heartbeat.py` writes `data/heartbeat.json` atomically every cycle. `scripts/watchdog.py` is a separate process that alerts on staleness via Telegram + SMTP. Do NOT propose replacing with an in-process timer — a same-process watchdog cannot detect `kill -9` or main-loop deadlock. Wired in crypto_alert.py main(). 18 tests in tests/test_heartbeat.py. |
| PA-2 | Secondary alert channel (SMTP) | DONE — Roadmap Phase A #2 | `MultiChannelAlerter` in heartbeat.py tries Telegram primary, falls back to SMTP on failure. SELFTEST every ~24h forces both channels to deliver (Red Flag #12). Optional — disabled if SMTP_* env vars unset. Do NOT propose Mailgun/SendGrid replacements — stdlib `smtplib` is sufficient at this signal rate. |
| PA-3 | Atomic process-state persistence | DONE — Roadmap Phase A #3 | `state_store.py::StateStore` writes JSON atomically (tmp + fsync + os.replace) with `.bak` rotation. Wired in crypto_alert.py to persist cycle counter, consecutive_errors, last_heartbeat_ts every cycle. 19 tests in tests/test_state_store.py. Do NOT propose moving these counters into the DB `bot_state` table — file-based store survives DB corruption and bypasses any DB lock contention. |
| PA-4 | PID-file double-start guard | DONE — Roadmap Phase A #3 | `state_store.py::PidFile` refuses bot startup if another bot process is alive. Supervisord auto-restart races make this real. Stale pid files (process gone) are silently reclaimed. Release() only deletes the file if the recorded PID still matches our own (race-safe). Do NOT remove. |
| PA-5 | supervisord configuration | DONE — Roadmap Phase A #3 | `scripts/supervisord.conf` provides the canonical Linux deployment config (autorestart=true, startretries=999, log rotation). Windows operators use `scripts/run_supervised.bat` (exponential backoff retry loop, NSSM/Task Scheduler ready) + `scripts/run_watchdog.bat`. Do NOT propose Docker/systemd alternatives — supervisord is the documented enterprise path. |
| PA-6 | Backtest checkpointing | DONE — Sprint 1 (operational hardening) | `backtest_checkpoint.py` writes `data/backtest_checkpoint.json` after each token completes. SHA-256 config-hash invalidation prevents resuming under a different parameter regime. CLI flags `--no-resume` and `--clear-checkpoint`. Resume refetches BTC reference candles (~30s) for downstream SMT divergence. Checkpoint cleared after full pipeline completes. 18 tests in tests/test_backtest_checkpoint.py. Do NOT propose pickle-based state — JSON is human-inspectable and version-portable. |

---

## Phase A Pre-LIVE Hardening (Sprint 2 — 2026-05-22)

| ID | Component | Final Status | Notes for Agents |
|----|-----------|-------------|-----------------|
| PA-7 | Centralized tunables (`config.py`) | DONE — Audit Adopt 3 + Roadmap §2 | `config.py` is the single source of truth for every tunable. Every scalar (`MAX_SL_PCT`, `LIVE_FVG_MIN_QUALITY`, `LIQUID_HOURS`, etc.) reads `os.environ` first with fail-loud type validation. `strategy_engine.py` builds `LIVE_CONFIG = StrategyConfig(**LIVE_CONFIG_KWARGS)` from config.py. Tune Bot in `tracker.py` was repointed from `strategy_engine.py` anchors to per-field constants in `config.py`. Do NOT re-scatter constants back into `crypto_alert.py` top-level — every new tunable belongs in `config.py`. |
| PA-8 | Secrets migration (`.env` + `secrets_loader.py`) | DONE — Roadmap §2 dotenv-vault triage item | `secrets_loader.py` is a stdlib-only `.env` parser supporting `KEY=val`, `export`, CMD `set`, quotes, comments. Optional `.env.vault` decryption when `python-dotenv-vault` installed and `DOTENV_KEY` env var set. Precedence: existing env > `.env.vault` > `.env` > `env.bat`. TELEGRAM_TOKEN and CHAT_ID migrated from `env.bat` (which is now an empty shim for legacy supervisord configs). Logs secret PRESENCE only, never values. Do NOT propose taking `python-dotenv-vault` as a hard dependency — it is BSL-encumbered and the stdlib parser is sufficient. |
| PA-9 | CI/CD backtest regression gate | DONE — Roadmap Top-10 #4 | `scripts/backtest_regression.py` has three modes: `--mode=ci` (default for CI, offline strategy param drift check — catches M24 class), `--mode=lastrun` (validates committed `data/backtest_results.json` against floors n≥25/WR≥72%/z≥2.5), `--mode=full` (operator fresh-backtest path with VPN). `.github/workflows/backtest_gate.yml` triggers on PR + push to main/master. WR formula matches `backtest.py:987 is_win()` (PARTIAL_TP1/2 = full wins). Do NOT propose loosening the floors without re-validating against a fresh Run-48-class baseline. Do NOT replace with custom CI infrastructure — the GitHub Actions workflow is the canonical entry. |
| PA-10 | Triple-barrier labeling (`labeling.py`) | DONE — Roadmap Top-10 #1 | `labeling.py` is a stdlib-only de Prado AFML §3.4 implementation. NO mlfinlab dependency — preserves the bot's stdlib+requests posture. Exposes: `triple_barrier_label()`, `ewma_daily_sigma()`, `vol_scaled_barriers()`, `bootstrap_wr_ci()`, `bootstrap_sharpe_ci()`. Wired into `backtest.py` — every signal gets `tb_bin`/`tb_touch`/`tb_ret`/`tb_t1` columns persisted to DB. Honest-Label section in `print_report()`. Do NOT propose adding mlfinlab as a dependency for any of these primitives — they are tested at 39 unit tests and adequate. CPCV + DSR (Top-10 #5) will consume `tb_bin` from this layer. |
| PA-11 | Bootstrap CI on WR + Sharpe | DONE — Roadmap §2 Monte Carlo bootstrap item | Same module as PA-10 (`labeling.py`). 5000-iteration bootstrap 95% CI. Backtest `print_report()` shows the CI alongside the point estimate. Run 93 CI: WR [61.9-88.1%] (contains both Run-48 77.4% and Session-2 81.1% — statistically consistent). Do NOT replace with parametric (Wald/Wilson) intervals — bootstrap is robust to the non-normal WR distribution at n≈42. |

**Sprint 2 net result:** 222/222 tests passing. Run 93 validated all Phase A floors. One open item: 5 extra AVAX signals in Run 93 vs Run 48 (270-day spread, NOT market drift) — diff-trace queued before Sprint 3 starts.

---

## Phase A Pre-LIVE Hardening (Sprint 3 — 2026-05-23)

| ID | Component | Final Status | Notes for Agents |
|----|-----------|-------------|-----------------|
| PA-12 | OHLCV disk cache for backtest speed | DONE — 2026-05-23 | `backtest.py`: `fetch_cached()` wraps `fetch_historical()` with `data/ohlcv_cache/{symbol}_{interval}_{days}d.json`. Cache key auto-invalidates on `BACKTEST_DAYS` change (different filename). No TTL — user-controlled via `--fresh` (bypass) and `--clear-cache` (wipe + exit). Per-token label in output: `(cached)` vs `(live fetch)`. Reduces repeated experiment runs from ~25min fetch to ~2-3min. **Bias review (backtest-bias-detector, 2026-05-23):** VERDICT VALID — no lookahead, no snooping. Two known MODERATE limitations: (1) stale cache produces temporally shrinking OOS window (directionally conservative, not optimistic); (2) `tracker.py` tune-triggered backtests at line 1875 reuse cache with no `--fresh`, so auto-validation WR estimates use compressed OOS window when cache is old — fix queued as PA-12b. Do NOT propose TTL-based expiry — cache is operator-controlled by design (same data across all optimizer iterations in a session is the goal). |
| PA-12b | `--fresh` for tune-triggered backtests | DONE — 2026-05-23 | `tracker.py:1875` now passes `"--fresh"` in the `subprocess.Popen` args. Tune-apply validation backtests always re-fetch current Binance data, ensuring OOS WR comparisons are against a consistent data window. Do NOT remove `--fresh` — stale cache would silently compress the OOS sample for tune decisions. |

## Autonomous R&D Layer (Design Phase — 2026-05-24)

| ID | Component | Final Status | Notes for Agents |
|----|-----------|-------------|-----------------|
| AUTO-EXPLORER | Autonomous Optuna-based explorer | **DESIGN APPROVED — implementation pending** | Full design: `docs/AUTONOMOUS_EXPLORER_DESIGN.md`. Phased 5-day project: Phase 1 (Optuna wrapper + scoring), Phase 2 (Task Scheduler + anti-overfit guard), Phase 3 (auto-promotion + Pareto archive), Phase 4 (dashboard + Telegram digest). Coexists with existing operator-driven 3-agent pipeline (`docs/OPTIMIZATION_AGENT_PIPELINE.md`). Auto-promotes only as far as `baseline_pin.json` + `tune_history` — never auto-flips LIVE. Trials are NOT added to DSR pool unless promoted. Two-promotion-per-day cap. Hard search-space lockouts: ICT_SWING_N=2, ICT_MIN_RR_GATE=1.5 (anti-patterns from Cycle 1b/1c). |
| VECTORBT-REJECT | vectorbt library evaluation | **REJECTED 2026-05-24** | Apache 2.0 but requires re-implementation of ict_engine.py in NumPy-vectorized primitives. Would create two engines to keep in sync → live/BT parity dim drops 9.5→~6. Speed gain (50-100x) unnecessary: cached existing engine does 10-15s/run = 1,500-2,000 runs per overnight session via autonomous explorer. Do NOT re-propose. See `docs/AUTONOMOUS_EXPLORER_DESIGN.md` §2. |
| OPTUNA-ADOPT | Optuna Bayesian search library | ADOPTED 2026-05-24 | MIT license. Wraps existing backtest engine (parity preserved). Foundation for AUTO-EXPLORER. Add to requirements.txt as `optuna>=3.5,<4` when Phase 1 starts. Do NOT propose other ML/RL hyperparameter libraries. |
