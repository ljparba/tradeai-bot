# TradeAI Fix Log

Track of all fixes applied outside the original 76-issue comprehensive audit pass.

---

## Session: 2026-05-21

### FIX-1 — `datetime.utcnow()` Deprecation Warning
**Severity:** LOW (Python 3.13 will remove it)
**Files changed:**
- `tracker.py` — import added `timezone`; 6 calls replaced: lines 381, 387, 638, 761 → `.replace(tzinfo=None)` (naive for strptime arithmetic); lines 1235, 1441 → `datetime.now(timezone.utc).strftime()`
- `adaptive_engine.py` — import added `timezone`; 6 calls replaced: all `.strftime()` → `datetime.now(timezone.utc).strftime()`
- `phase2_data.py` — import added `timezone`; 1 call replaced: `.strftime()` → `datetime.now(timezone.utc).strftime()`
**Root cause:** Python 3.12 deprecated `datetime.utcnow()`. Safe replacement: `datetime.now(timezone.utc)` which works Python 3.2+.
**Test:** Restarted tracker.py — no DeprecationWarning in output.

### FIX-2 — Stale Excluded Token Rows in SQLite DB
**Severity:** INFO (cosmetic — cluttered startup logs)
**DB:** `data/signals.db`
**Action:** Deleted rows for tokens no longer in BINANCE_TOKENS:
- `token_weights`: removed DOT (30 updates), NEAR (42), SOL (8700), BTCUSDT (0 — duplicate bootstrap key)
  - 78 rows → 54 rows (24 removed)
- `market_stats`: removed DOT, MATIC (pre-rename), NEAR, SOL
  - 39 rows → 27 rows (12 removed)
**Root cause:** Adaptive engine loads all rows from DB on startup; stale rows from previously-active tokens (DOT/NEAR removed Run 47, SOL removed T-1, MATIC renamed POL Sep 2024) still had entries.
**Result:** Startup now shows only the 9 active tokens (ADA, AVAX, BNB, BTC, ETH, HBAR, LINK, POL, XRP).

### FIX-3 — DR-1 Config Drift Not Documented in CROSS_REF.md
**Severity:** YELLOW (documentation gap — future agents would re-report as new drift)
**File changed:** `docs/comprehensive/CROSS_REF.md`
**Action:** Added DR-1 as KNOWN STRUCTURAL in new "Post-Audit Known Items" section. Updated summary table (76→77 total, 3→4 Known Structural).
**Root cause:** `dealing_range_gate` intentionally differs between LIVE_CONFIG (True — blocks EQUILIBRIUM) and BACKTEST_CONFIG (False — DR-1 catch-22: enabling gate blocks 100% of TRENDING_BEAR SELL signals). Conservative direction: live is stricter than backtest. Was not in the original 76-issue index.

---

### FIX-4 — SMT Bonus Sign REGRESSION in strategy_templates.py
**Severity:** HIGH (REGRESSION — contradicted empirical optimizer decision)
**Files changed:**
- `strategy_templates.py` — lines 143, 208, 261: `bonus += 0.10` → `bonus -= 0.10`; label `"SMT_bonus"` → `"SMT_penalty"` (all 3 templates: Tier A, B, C)
- Docstrings updated: `+0.10 SMT divergence confirmed` → `-0.10 SMT confirmed (anti-predictive per Run 48 empirical data)`
**Root cause:** Run 48 optimizer added `smt_penalty = -1` to the confidence engine (`backtest.py:770`, `crypto_alert.py:2394`) after empirical data showed SMT-confirmed signals are anti-predictive. But `strategy_templates.py` was never updated — it still awarded +0.10 bonus. Net effect: template scoring rewarded SMT while confidence engine penalized it. Now aligned.
**Test:** 60/60 tests pass. 1 pre-existing failure (test_apply_backup_contains_original) is unrelated to this fix.

### FIX-5 — MSS Sequence Gate Mismatch (Backtest vs Live)
**Severity:** HIGH (live/backtest divergence — backtest counted ~5-15% more signals than live generates)
**File changed:** `backtest.py` — line 631
**Change:** `if mss_result["mss_bar"] <= sweep["bar"]:` → `if mss_result["mss_bar"] <= disp_bar + 1:`
**Label changed:** `"MSS before sweep (error)"` → `"MSS sequence (fired before FVG complete)"`
**Comment updated:** Corrected wrong ICT explanation to match live code comment.
**Root cause:** Backtest only blocked MSS if it fired before the sweep bar (almost never happens). Live code (crypto_alert.py:2166) correctly requires MSS to fire AFTER the FVG completes at disp_bar+1. ICT sequence is sweep→displacement→FVG (3 candles through disp_bar+1)→MSS. The old backtest comment incorrectly claimed disp_bar+1 was "too strict."
**Test:** 61/61 tests pass. 1 pre-existing failure (test_apply_backup_contains_original) unrelated.
**Impact:** Backtest signal count will decrease slightly (the inflated ~5-15% signals were live-invalid). OGD bootstrap weights now trained on live-valid signal set.

### FIX-6 — 429/418 Rate-Limit Handling in live fetch_binance_candles()
**Severity:** HIGH (IP-ban path was silent; 429 used flat API_DELAY instead of Retry-After)
**File changed:** `crypto_alert.py` — except block at line 1470
**Change:** Added explicit status code inspection:
- HTTP 418 (IP ban): logs `IP BANNED (418)` and returns `{}` immediately — no point retrying a banned IP
- HTTP 429 (rate limit): reads `Retry-After` header, sleeps min(value, 30)s, then retries within loop
- Other errors: unchanged behavior (log + API_DELAY sleep)
**Root cause:** The bare `except Exception as e:` block treated all failures identically with a flat 3s sleep. Binance 418 (IP ban) was silent — no distinguishing log, kept retrying. Binance 429 (rate limit) ignored the Retry-After header. Backtest.py already had correct 429 handling (L10 fix); live path was missing it.
**Test:** 61/61 tests pass. 1 pre-existing failure unrelated.

### FIX-7 — TOKEN_RT_COST Key Format Mismatch (M15 Dead Code)
**Severity:** HIGH (M15 was marked DONE but was functionally dead — fee overrides silently never applied)
**File changed:** `ict_engine.py` — lines 33-41
**Change:** Dict keys changed from full symbols ("BTCUSDT", "ADAUSDT", "POLUSDT", "HBARUSDT") to short form ("BTC", "ADA", "POL", "HBAR") matching what callers pass.
**Root cause:** `TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT)` was called with short-form token names ("ADA", "HBAR", "POL") but the dict was keyed by full symbols. Every lookup fell through to the 0.003 default. ADA should be 0.004 (33% understatement), HBAR/POL should be 0.005 (67% understatement).
**Impact:** BEW gate now uses correct per-token costs. HBAR/ADA/POL signals with marginal R:R that previously passed will now correctly fail the BEW check. Both live and backtest affected equally — no live/backtest divergence introduced.
**Test:** 61/61 tests pass.

### FIX-8 — Bonferroni Correction for Phase 4.6 Multiple Comparisons
**Severity:** HIGH (FWER=82% with 17 subsets at z≥1.28 — at least one spurious CANDIDATE flag expected per run)
**File changed:** `backtest.py` — Phase 4.6 print loop + imports
**Changes:**
- Added `from statistics import NormalDist` to imports (stdlib, no new dependency)
- Compute `_z_bf = NormalDist().inv_cdf(1 - 0.10 / k)` dynamically from subset count
- CANDIDATE flag now requires z ≥ _z_bf (Bonferroni-corrected, ~2.52 for k=17)
- Subsets passing unadjusted z≥1.28 but not Bonferroni show `[z≥1.28 unadjusted]` — still visible to optimizer but not flagged as statistically validated candidates
- Header note added: "k tests; Bonferroni z ≥ {z_bf:.2f} (α=0.10 family-wise; FWER≈10%)"
**Root cause:** 17 subsets tested simultaneously at α=0.10 each → FWER = 1-(0.90)^17 ≈ 82%. At least 1 spurious CANDIDATE expected per run with no true edge. Bonferroni reduces FWER to 10%.
**Test:** 61/61 tests pass.

### FIX-9 — Template Holdout Split Locked to WF_OOS_START_DATE
**Severity:** HIGH (template OVERFIT/OK labels were unreliable — boundary shifted with every run)
**File changed:** `backtest.py` — `_holdout_split()` function
**Change:** `_holdout_split()` now uses `WF_OOS_START_DATE` ("2025-11-03") as the split boundary (same as the main WF validation `_wf_split()`). Falls back to count-based 80/20 only if the WF boundary falls outside the data range.
**Root cause:** `_holdout_split(all_signals, 0.80)` used a shifting count-based boundary (80% of signal count). Each new backtest added more signals, pushing the cut date earlier. Template OVERFIT/OK labels from run N were incommensurate with run N+1. The main walk-forward validation already used the fixed `WF_OOS_START_DATE` boundary — template comparison was the only place using the shifting split.
**Test:** 61/61 tests pass.

### FIX-10 — NY_AM_KZ Session Hours Off-By-One (L4 severity promoted to MEDIUM)
**Severity:** MEDIUM (was SKIPPED as LOW when liquid_hours excluded hour 12; now active with range(24))
**File changed:** `adaptive_engine.py` — line 78
**Change:** `if 12 <= hour <= 15:` → `if 13 <= hour <= 15:`
**Root cause:** Docstring already said `NY_AM_KZ — 13:00-15:59` but the guard used 12, including UTC noon (London afternoon). This was originally skipped because `liquid_hours` excluded hour 12 from signal generation. After liquid_hours was widened to range(24), hour-12 signals were being scored with maximum session bonus (1.0) when they should be classified as OVERNIGHT (0.0).
**Coverage:** crypto_alert.py and backtest.py both import `_utc_to_session` from adaptive_engine — single fix covers all paths.
**Test:** 61/61 tests pass.

### FIX-11 — 5m Fetch Success Tracked Separately from Any-TF Success
**Severity:** MEDIUM (5m data could be one cycle stale while stale guard passes)
**File changed:** `crypto_alert.py`
**Changes:**
- Added `"last_5m_fetched_at": 0.0` to `new_state()` dict
- Set `state["last_5m_fetched_at"] = time.time()` in `update_token_state()` inside the `if tf=="5m":` block
- Added second stale guard check in main loop: skips signal if `last_5m_fetched_at > 0` and `5m_age > STALE_CANDLE_THRESHOLD`; prints `[STALE-5M]`
**Root cause:** `any_ok=True` was set when any TF fetch succeeded, causing `last_fetched_at` to update even when the 5m fetch specifically failed. ICT signal detection runs on 5m data — a stale 5m feed silently passed the freshness check while generating signals on old candles.
**Test:** 61/61 tests pass.

### FIX-12 — Adaptive Confidence Floor Documented as KNOWN STRUCTURAL + Static Check Added to Backtest
**Severity:** MEDIUM (adaptive floor divergence between live and backtest — correctly classified as KNOWN STRUCTURAL)
**Files changed:** `backtest.py`, `docs/comprehensive/CROSS_REF.md`
**Changes:**
- Added explicit `if confidence < 5: continue` check in backtest.py after confidence computation (makes code symmetric with live path; never actually fires since `max(5, ...)` already enforces this)
- Added explanatory comment: backtest uses static floor=5 (initial starting value); live adaptive increments only activate after live signals accumulate
- Added CF-1 entry to CROSS_REF.md Post-Audit Known Items section as KNOWN STRUCTURAL
- Updated summary table: 77→78 total, 4→5 Known Structural
**Root cause:** Implementing the full adaptive floor system in backtest would require loading live performance history (H6-style contamination risk). The static floor=5 correctly models the bot's fresh-start behavior. Adaptive layers only change behavior after live signals accumulate — at that point backtest and live are expected to diverge.
**Test:** 61/61 tests pass.

### FIX-13 — BNB Added to CORRELATED Frozenset
**Severity:** MEDIUM (BNB signals silently bypassed correlation warning; asymmetric with SQL query)
**File changed:** `adaptive_engine.py` — line 958
**Change:** `frozenset({"BTC", "ETH", "AVAX"})` → `frozenset({"BTC", "ETH", "BNB", "AVAX"})`
**Root cause:** The SQL correlation query (line 1042) already counted BNB in the existing-open-positions check (`token IN ('BTC','ETH','BNB','AVAX')`), but BNB was absent from the frozenset gate that triggers the check. BNB signals would increase the count seen by BTC/ETH without themselves triggering a warning. Now symmetric — all 4 large-cap correlated tokens trigger the warning.
**Test:** 61/61 tests pass.

### FIX-14 — Bootstrap Now Uses Full Backtest History (run_id=None)
**Severity:** MEDIUM (bootstrap with single run ≤10 signals/token → near-default weights, defeating the purpose)
**File changed:** `backtest.py` — line 2554
**Change:** `bootstrap_from_backtest(run_id=run_id)` → `bootstrap_from_backtest(run_id=None)` — bootstrap from all historical backtest_signals
**Root cause:** The old call restricted bootstrap to the current run only (~38 signals, ≤10/token), producing weights statistically indistinguishable from defaults. With `run_id=None`, the full ~43,407-row history gives meaningful per-token priors. H6 fix already isolates bootstrap from scoring (bootstrap writes to backtest_token_weights; scoring reads from AE_DEFAULT_WEIGHTS) so there's no contamination risk.
**Test:** 61/61 tests pass.

### FIX-15 (retroactive) — LOW #1/2/3/6/7/9: Batch Minor Fixes (applied in previous session, not yet logged)

**LOW #1 — Removed dead `BTC_FETCH_INTERVAL = 600` variable**
- **File:** `crypto_alert.py` — constant removed; comment updated to reference H17 fix rationale
- BTC candles recompute every cycle from STATE; 600s gate had already been removed in H17; the const was orphaned

**LOW #2 — Telegram alert on kill switch DB error**
- **File:** `crypto_alert.py` — except block in kill switch check
- Added `send_telegram(f"⚠️ KILL SWITCH DB ERROR...")` so operator is notified when the DB error causes fail-closed
- Previously: DB errors were silent in Telegram (only console log); operator would not know signals were blocked

**LOW #3 — `fetch_binance_price()` wrapped in retry loop**
- **File:** `crypto_alert.py` — `fetch_binance_price()` function
- Converted single-attempt request to `for attempt in range(1, API_RETRIES + 1):` retry loop with `API_DELAY` sleep
- Previously: one transient network error caused 24h price/volume data to go stale for entire cycle

**LOW #6 — `generate_recommendations()` uses IS-only WR for overall verdict**
- **File:** `backtest.py` — `ow = _wr(all_signals)` → `ow = _wr(src)`
- `src` is the IS subset from `_holdout_split()`; OOS signals should not raise or lower the IS verdict
- Previously: high-WR IS performance could be masked by small OOS sample pulling overall WR down, or vice versa

**LOW #7 — `_wf_gap_sub()` returns `nan` when boundary outside subset range**
- **File:** `backtest.py` — `_wf_gap_sub()` function
- Returns `float("nan")` when subset has no signals on one side of `WF_OOS_START_DATE` boundary (incomparable)
- Previously: fell through to count-based fallback using a different boundary than main WF validation, making gap metrics incommensurate across subsets

**LOW #9 — `bootstrap_from_backtest(run_id=None)` uses full history**
- **File:** `backtest.py` — line 2566
- Changed from `run_id=run_id` (current run only, ~10 sigs/token) to `run_id=None` (full ~43k row history)
- Note: this is the same as FIX-14; FIX-14 was filed as MEDIUM because it was the primary semantic fix; LOW #9 is the LOW-severity description of the same change

**Test:** 61/61 tests pass.

### FIX-15 — 7-Day Decay Suppression for Recently-Updated Tokens (LOW #4)
**Severity:** LOW (without this, decay erodes freshly-learned OGD weights within hours of an update)
**File changed:** `adaptive_engine.py`
**Changes:**
- `__init__`: Added `self._last_update_time: Dict[str, float] = {}` tracking dict
- `_ensure_token()`: Initialises `self._last_update_time[token] = 0.0` for new tokens
- `_load_all()`: Extended SQL to `SELECT ... updated_at`; parses `updated_at` UTC string to epoch float and populates `_last_update_time` — so suppression survives restarts
- `_persist_token()`: Sets `self._last_update_time[token] = datetime.now(timezone.utc).timestamp()` after successful DB write
- `decay_toward_default()`: Added 7-day guard at top — if `time.time() - _last_update_time[token] < 7 * 86400`, skips decay entirely
**Root cause:** `decay_toward_default()` is called every 30 min (48×/day). After a live OGD update, the learned weights drift back toward default within hours: decay_rate=0.0004 × 48 calls/day × 7 days = 13% erosion per week. Suppressing decay for 7 days after each live update preserves the signal while still allowing slow convergence once the token has been dormant long enough.
**Test:** 61/61 tests pass. 1 pre-existing failure (test_apply_backup_contains_original) unrelated.

### FIX-16 — Gap Tracking Extended to 1H and 4H Timeframes (LOW #5)
**Severity:** LOW (1H/4H gaps left trend/regime data silently stale; 5M-only guard was insufficient)
**File changed:** `crypto_alert.py`
**Changes:**
- Added `"data_gap_bars_1h": 0` and `"data_gap_bars_4h": 0` to `new_state()`
- In `update_token_state()`: populated `data_gap_bars_1h` and `data_gap_bars_4h` from `max_gap_bars` when respective TF is fetched (already computed by `fetch_binance_candles()`)
- In `generate_signal()`: added skip guard after 5M check — skip if 1H gap ≥2 bars (≥2h blind spot in trend) or 4H gap ≥1 bar (≥4h blind spot in regime)
**Root cause:** `fetch_binance_candles()` already computed `max_gap_bars` for every TF, but `update_token_state()` only stored the 5M value. 1H gaps >2h and 4H gaps >4h left trend/regime classification running on stale data while the 5M-only guard passed.
**Thresholds rationale:** 1H: 2-bar gap = 2h of missing trend data; 4H: 1-bar gap = 4h of missing regime data. Both are meaningful blind spots that corrupt the DR classification and 4H bias filter.
**Test:** 61/61 tests pass.

### FIX-17 — A13 Test Bug: Missing 6-Space Pattern for fvg_min_quality
**Severity:** LOW (test false-negative — A13 always failed even when tune correctly applied)
**File changed:** `tests/test_tunebot.py`
**Changes:**
- Added `f'fvg_min_quality      = "{before_fvg}"' in bak_content` as 4th OR pattern (lines 338-341)
- Added `f'fvg_min_quality      = "{target_val}"' in after_content` as 4th OR pattern (lines 343-346)
**Root cause:** `strategy_engine.py` uses `fvg_min_quality      = "HIGH"` (6 spaces before `=`). The test checked only 4-space, 1-space, and no-space variants. None matched the actual file format.
**Test:** 31/31 tunebot tests pass including A13.

### FIX-18 — T21 False-Positive Source Scan Removed
**Severity:** LOW (test produced 35 false failures; no code bug)
**File changed:** `tests/test_tracker_db_alignment.py`
**Changes:**
- Removed T21 entirely (replaced with an explanatory comment)
**Root cause:** T21 scanned source code for `PARTIAL_TP1`/`PARTIAL_TP2` outside of `backtest_signals` context. But these are legitimate intermediate live result values (TP2 hit but TP3 not yet; written to `results` table). T2 already verifies the actual DB has no unexpected values — T21 was redundant and wrong.
**Test:** 98/98 alignment tests pass.

### FIX-19 — Max 2 APPLIED Guard in apply_tune_adjustments()
**Severity:** MEDIUM (prevented theoretically unbounded tune stacking without verification)
**File changed:** `tracker.py`
**Changes:**
- Added Phase 3.5 guard between signal-count check and apply loop
- Counts `tune_history` rows with `status='APPLIED' AND signals_at_apply > 0` (live runs only; excludes test-cycle rows)
- Returns error if count ≥ 2: "Max 2 APPLIED tune history entries reached."
**Root cause:** Nothing prevented applying a 3rd, 4th, etc. tune before verifying earlier ones. Filter `signals_at_apply > 0` avoids blocking on 76 test-cycle rows.
**Test:** Full suite passes.

### FIX-20 — VERIFIED_WORSE Telegram Alert in crypto_alert.py
**Severity:** MEDIUM (operator had no real-time notification when a tune degraded live WR)
**File changed:** `crypto_alert.py`
**Changes:**
- Added `if _verdict == "VERIFIED_WORSE": send_telegram(...)` block after line 664 in `load_performance_state()` post-apply check
- Alert text includes tune_id, post_apply WR, baseline WR, signal count, and rollback suggestion
- Wrapped in `try/except` to not disrupt the perf loop on Telegram errors
**Test:** Syntax OK; full suite passes.

### FIX-21 — Wilson CI Added to FVG/MSS Quality Breakdown Notes
**Severity:** LOW (quality bucket notes lacked uncertainty bounds; session/confidence notes already had CI)
**File changed:** `tracker.py`
**Changes:**
- `calculate_tune_preview()` FVG note loop: added `lo, hi = _wilson_ci(n, round(wr * n / 100))` and format `{q}: {wr:.0f}% [{lo:.0f}-{hi:.0f}%] (n={n})`
- Same change for MSS note loop
**Root cause:** Session and confidence bucket notes already used `_wilson_ci()` (added in Phase 2). FVG/MSS quality buckets were missed.
**Test:** Full suite passes.

### FIX-22 — OGD Health Warning Added to Confirm Overlay
**Severity:** LOW (UX gap — operator had no warning that applying a tune overwrites OGD bootstrap weights)
**Files changed:** `tracker_html.py`
**Changes:**
- Added `<div id="tuneConfirmOgdNote">` element after `tuneConfirmWfWarn` in the confirm overlay HTML
- Added OGD note population in `confirmTune()` JS function (shows indigo-tinted note: "OGD adaptive weights will be re-bootstrapped... Any in-progress live learning will be overwritten.")
**Test:** Full suite passes; no JS syntax errors.

### FIX-23 — _tune_wr() PARTIAL Miscounting (tracker.py:683)
**Severity:** MEDIUM (inflated Tune Bot WR readings → gate tightening triggered too readily)
**File changed:** `tracker.py`
**Changes:**
- `_tune_wr()` now counts `PARTIAL_TP1`/`PARTIAL_TP2` as 0.5 wins (was: 1.0 win)
- Denominator now uses only closed outcomes (WIN/LOSS/PARTIAL_TP1/PARTIAL_TP2/EXPIRED), excluding OPEN signals
- Consistent with `_canonical_wr()` (tracker.py:77) and `_weighted_wr()` (crypto_alert.py)
**Root cause:** PARTIAL_TP1/2 are intermediate states (TP1 hit, trade still open). Counting them as full wins inflated session/quality WR estimates used by the Tune Bot's 15pp gap threshold and 38%/40% floor gates.
**Found by:** adaptive-learning-code-reviewer agent
**Test:** 31/31 tunebot tests pass; syntax OK.

### FIX-24 — Telegram 400 on Startup Message (Markdown Parse Error)
**Severity:** HIGH (startup message + every system message containing underscores silently failed in production)
**File changed:** `crypto_alert.py`
**Changes:**
- `send_telegram()` now retries once as plain text on HTTPError when body contains `"can't parse entities"` or `"parse"`
- HTTPError handled in a separate except branch; non-HTTP errors keep the original retry-with-backoff path
- New log line `[TG] Markdown parse error — retrying as plain text` when fallback triggers
**Root cause:** Startup message included `_drift_note` which contains `adx_trend=18.0 (-7.0)`. The underscore `_` is Markdown v1 italic delimiter; unmatched underscores cause Telegram to return `400 Bad Request: can't parse entities`. All 3 retries failed because they all sent the same Markdown payload. User saw `Bot v13 Started` message never arriving.
**Diagnosis:** scripts/diagnose_telegram.bat confirmed bot token + CHAT_ID valid (200 on getMe + plain-text sendMessage); 400 only on Markdown-mode startup.
**Test:** Syntax OK. Restart the bot — startup message now sends as plain text on first Markdown failure.

## Open Items (not yet fixed)

| ID | Severity | Description | Waiting on |
|----|----------|-------------|------------|
| (none) | — | All previously-tracked open items resolved. | — |

### Resolved historical Open Items

- **E-1** (was YELLOW) — ENTRY_WINDOW=96 active, no ACCEPT/REJECT recorded → **REJECTED & REVERTED** per `docs/optimization_experiments.md` Session 2 context: "E-1: ENTRY_WINDOW=96 added 0 signals (reverted to 72)". Closed 2026-05-23 during cross-reference audit.

---

## Sprint 1 — Phase A Pre-LIVE Hardening (2026-05-22)

Three Enterprise Roadmap Phase A items shipped end-to-end with full test coverage. These are new infrastructure modules, not bug fixes — they remove operational blind spots that block the PAPER → LIVE transition.

### SPRINT1-1 — Dead-Man's Switch + Secondary Alert Channel
**Roadmap reference:** Phase A item #2 (score 5)
**Severity:** HIGH (operational gap — silent process death = missed signals = lost capital awareness)
**Files added:**
- `heartbeat.py` (new — ~280 lines)
- `scripts/watchdog.py` (new — external sidecar)
- `tests/test_heartbeat.py` (new — 18 tests)
**Files modified:**
- `crypto_alert.py` — imports + main-loop wiring; existing hourly Telegram heartbeat now routes through `MultiChannelAlerter` so SMTP fallback fires on Telegram outage.
**What it does:**
- Bot writes `data/heartbeat.json` atomically every cycle (tmp + fsync + rename).
- External watchdog process polls the file; alerts if mtime exceeds `HEARTBEAT_STALENESS_SEC` (default 600s) on **both** Telegram and SMTP.
- `MultiChannelAlerter` tries Telegram primary; on failure (network, 429, revoked token) falls back to SMTP — critical alerts still reach the operator.
- SELFTEST runs every Nth heartbeat (default 24 ≈ once/day at hourly cadence) forcing both channels to deliver — satisfies Red Flag #12 (silently-dead alert path detection).
- Counter persisted via `bot_state` so restarts do not reset the SELFTEST cadence.
**SMTP env vars (optional):** `SMTP_HOST`, `SMTP_PORT` (587 STARTTLS or 465 SSL), `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_TO`.
**Failure semantics:** Every save/send path swallows exceptions and logs; never raises into the main loop. Disk-full or SMTP-broken does not crash the bot.
**Test:** 18/18 heartbeat tests pass; full suite 80/80; crypto_alert imports clean.

### SPRINT1-2 — Atomic State Persistence + supervisord
**Roadmap reference:** Phase A item #3 (score 5)
**Severity:** HIGH (`kill -9` previously cold-zeroed in-memory counters)
**Files added:**
- `state_store.py` (new — ~220 lines)
- `scripts/supervisord.conf` (Linux supervisord program block)
- `scripts/run_supervised.bat` (Windows wrapper — NSSM/Task Scheduler ready)
- `scripts/run_watchdog.bat` (Windows watchdog wrapper)
- `tests/test_state_store.py` (new — 19 tests)
**Files modified:**
- `crypto_alert.py` — `StateStore` + `PidFile` wired into `main()`. On startup, `_persisted = StateStore().load(defaults={...})` restores cycle counter, consecutive-error count, and last-heartbeat timestamp. Every cycle the snapshot is rewritten atomically.
**What it does:**
- `StateStore.save()` writes JSON atomically (tmp + fsync + os.replace) with rotating `.bak` so corrupted primary recovers from backup.
- `PidFile` refuses startup if another bot is alive (supervisord auto-restart can race the previous PID's cleanup). Stale pid files (process gone) are silently reclaimed. `release()` only deletes the file if the recorded PID still matches our own.
- `transaction()` context manager saves on exit, even on exception.
- Non-JSON-serialisable values are dropped with a warning, never crash the save.
**Supervisord behavior:** `autorestart=true`, `startretries=999`, dedicated unprivileged `tradeai` user, log rotation 10MB×10. Combined with `state_store.py` a crash + restart resumes the cycle counter, cooldowns (DB-resident), OGD weights (DB-resident), and consecutive-error tracking exactly where the previous run left off.
**Windows analogue:** `run_supervised.bat` retries the bot with exponential backoff (5s → 300s cap) on non-zero exit. Designed for NSSM service or Task Scheduler "restart on failure".
**Test:** 19/19 state_store tests pass; full suite 99/99; crypto_alert imports clean.

### SPRINT1-3 — Backtest Checkpointing
**Roadmap reference:** Phase A operational hardening (not in Top-10 but a logical companion to SPRINT1-2)
**Severity:** MEDIUM (interrupted backtests previously lost all work; mid-run failures common when Binance fetch fails or VPN drops)
**Files added:**
- `backtest_checkpoint.py` (new — ~155 lines)
- `tests/test_backtest_checkpoint.py` (new — 18 tests)
**Files modified:**
- `backtest.py` — imports + `_compute_run_config_hash()` helper + `_parse_args()` CLI flags + per-token checkpoint save + clear-on-success.
**What it does:**
- After every token completes (~30s–2min of work each), `save_checkpoint()` writes `data/backtest_checkpoint.json` atomically with `{config_hash, completed_tokens, all_signals, started_at, saved_at}`.
- On startup `load_checkpoint()` returns the checkpoint **only** if its SHA-256 `config_hash` matches the current parameter set — any change to ACTIVE_CONFIG, BACKTEST_DAYS, ICT params, fees, or token list invalidates the checkpoint. This prevents silently mixing results across two parameter regimes.
- Resume refetches BTC reference candles (one extra fetch, ~30s) so downstream tokens still have BTC data for SMT divergence detection.
- After full pipeline completes (report + WF + template comparison + DB save + OGD bootstrap), the checkpoint file is cleared.
- CLI flags: `--no-resume` (ignore checkpoint, start fresh), `--clear-checkpoint` (delete file and exit, no run).
**Failure semantics:** All save paths swallow exceptions. Hash-mismatch checkpoints are left in place — operator decides whether to overwrite or `--clear-checkpoint`.
**Test:** 18/18 checkpoint tests pass; full suite 117/117; CLI `--help` works; hash computes deterministically against real ACTIVE_CONFIG.

---

### Sprint 1 summary

| Metric | Value |
|---|---|
| New modules | 3 (heartbeat.py, state_store.py, backtest_checkpoint.py) |
| New scripts | 3 (watchdog.py, run_supervised.bat, run_watchdog.bat) + 1 config (supervisord.conf) |
| New unit tests | 55 (heartbeat: 18, state_store: 19, backtest_checkpoint: 18) |
| Total test pass | 117/117 (was 62/62 before sprint) |
| Files modified | crypto_alert.py, backtest.py |
| Regression count | 0 |
| Roadmap items closed | Phase A #2, #3, plus backtest checkpointing (not in Top-10) |

---

## Sprint 2 — Phase A Pre-LIVE Hardening (2026-05-22)

Five Enterprise Roadmap Phase A deliverables shipped end-to-end. Together they close Top-10 items #1 and #4, the dotenv-vault triage item, and the centralized-config item from `docs/TRADINGAGENTS_INVESTIGATION_AUDIT.md` (Adopt 3). All validated against Run 93 (n=42, WR=76.19%, z=+3.826 — Phase A floors cleared).

### FIX-25 — Centralized Tunables via config.py (Audit Adopt 3)
**Severity:** MEDIUM (config drift — scattered constants across `crypto_alert.py`, `strategy_engine.py` LIVE_CONFIG/BACKTEST_CONFIG, no env-var overrides)
**Files added:**
- `config.py` (new) — single source of truth for all tunables. Every scalar (`MAX_SL_PCT`, `LIVE_FVG_MIN_QUALITY`, `LIQUID_HOURS`, etc.) has env-var override with fail-loud type validation.
**Files modified:**
- `strategy_engine.py` — `LIVE_CONFIG = StrategyConfig(**LIVE_CONFIG_KWARGS)` and same for BACKTEST_CONFIG; KWARGS imported from config.py
- `crypto_alert.py` — top-level constants now read from config.py
- `tracker.py` — Tune Bot anchor strings repointed from `"LIVE_CONFIG = StrategyConfig("` to per-field literal constants in config.py
- `tests/test_tunebot.py` — all 31 tests updated to read from config.py (CONFIG_PATH constant added); per-field test paths verified against new anchor
**Root cause:** Constants were scattered across 3 files with no override mechanism. Ops flexibility (e.g. tweaking `MAX_SL_PCT` for paper without code edit) required source modifications. Sprint 2 centralizes.
**Acceptance test:** 222/222 tests pass; `scripts/backtest_regression.py --mode=ci` proves every strategy parameter still matches Run-48 baseline byte-for-byte.
**Test:** 222/222.

### FIX-26 — Secrets Migration to .env + secrets_loader.py
**Severity:** HIGH (env.bat stored plaintext TELEGRAM_TOKEN/CHAT_ID; not encryptable; legacy supervisord configs depend on it)
**Files added:**
- `secrets_loader.py` (new) — stdlib-only `.env` parser. Supports `KEY=val`, `export`, CMD `set`, quotes, and `#` comments. Optional `.env.vault` decryption when `python-dotenv-vault` installed and `DOTENV_KEY` env var set. Logs secret PRESENCE only, never values.
- `.env` (gitignored) — new home for TELEGRAM_TOKEN, CHAT_ID
- `env.bat` retained as empty shim — legacy supervisord configs continue to invoke it without error
**Precedence:** existing env > `.env.vault` > `.env` > `env.bat` (override flag available for testing)
**Files modified:**
- `crypto_alert.py` — calls `secrets_loader.load()` at startup before reading `os.environ["TELEGRAM_TOKEN"]`
- `.gitignore` — added `.env` and `.env.vault`
**Root cause:** Plaintext secrets in `env.bat` violated dotenv-vault triage decision (ROADMAP §2 ADOPT). Sprint 2 ships the equivalent without taking the BSL-encumbered python-dotenv-vault as a hard dependency.
**Test:** Diagnostic `scripts/diagnose_telegram.bat` still validates after migration; bot starts cleanly; secrets never appear in logs.

### FIX-27 — CI/CD Backtest Regression Gate (Roadmap Top-10 #4)
**Severity:** HIGH (no CI gate — Run-46-class regressions could merge silently)
**Files added:**
- `scripts/backtest_regression.py` (new) — three operating modes:
  - `--mode=ci` (default for CI): offline strategy-parameter drift check, no network needed. Catches the M24 class of bug (parameter regression without explicit test).
  - `--mode=lastrun`: validates committed `data/backtest_results.json` against floors (n≥25, WR≥72%, z≥2.5).
  - `--mode=full`: runs fresh backtest locally before opening a PR (operator path, VPN required).
- `.github/workflows/backtest_gate.yml` (new) — triggers on `pull_request` + `push` to main/master. Calls `--mode=ci` and `--mode=lastrun`.
**WR formula:** matches `backtest.py:987 is_win()` exactly — PARTIAL_TP1 and PARTIAL_TP2 count as full wins (same as triple-barrier `tb_bin == 1` upper-touch).
**Acceptance test:** Both modes PASS on current `data/backtest_results.json` (n=42, WR=76.19%, z=+3.826 from Run 93). Strategy parameters still match Run-48 baseline.
**Test:** 222/222 tests pass; gate active on every PR.

### FIX-28 — Triple-Barrier Labeling + Bootstrap CI (Roadmap Top-10 #1)
**Severity:** HIGH (Run-48 WR was the OPEN/CLOSE label, not de Prado's path-dependent first-touch — biased upward by intrabar reversals)
**Files added:**
- `labeling.py` (new ~310 lines) — stdlib-only de Prado AFML §3.4 implementation. No mlfinlab dep — preserves stdlib+requests posture.
  - `triple_barrier_label()` — first-touch labeling: upper barrier=TP, lower=SL, vertical=timeout
  - `ewma_daily_sigma()` — exponentially-weighted volatility estimate
  - `vol_scaled_barriers()` — sigma-scaled TP/SL widths
  - `bootstrap_wr_ci()` — 5k-iteration bootstrap 95% CI on WR
  - `bootstrap_sharpe_ci()` — same for per-trade Sharpe
**Files modified:**
- `backtest.py` — `tb_bin`/`tb_touch`/`tb_ret`/`tb_t1` per-signal columns added to DB; Honest-Label section in `print_report()` shows first-touch breakdown + bootstrap CIs.
- DB schema — `backtest_signals` table extended with 4 triple-barrier columns (idempotent ALTER TABLE).
**Root cause:** Path-dependent reality: a trade that touches TP1 then reverses to SL was labeled WIN by OPEN/CLOSE outcome, but is actually a partial-win-then-loss scenario. Triple-barrier first-touch labels are honest.
**Acceptance test:** Run 93 honest labels: TP=32 (76.2%), SL=9 (21.4%), TIMEOUT=1 (2.4%). Bootstrap WR CI [61.9-88.1%] contains both Run-48 (77.4%) and Session-2 (81.1%) baselines — statistically consistent.
**Test:** 39 new unit tests in `tests/test_labeling.py`. 222/222 total passing.

### Sprint 2 summary

| Metric | Value |
|---|---|
| New modules | 3 (config.py, secrets_loader.py, labeling.py) |
| New scripts | 1 (backtest_regression.py) + 1 CI workflow (.github/workflows/backtest_gate.yml) |
| New unit tests | 66 (config: ~10, secrets_loader: ~10, regression_gate: ~7, labeling: 39) |
| Total test pass | 222/222 (was 156/156 before sprint) |
| Files modified | crypto_alert.py, strategy_engine.py, tracker.py, backtest.py, tests/test_tunebot.py, .gitignore |
| Regression count | 0 (Run 93 validates: n=42 WR=76.19% z=+3.826 — bootstrap CI contains both Run-48 and Session-2 baselines) |
| Roadmap items closed | Phase A Top-10 #1 (triple-barrier), Top-10 #4 (CI gate), dotenv-vault triage item, Audit Adopt 3 (config.py) |
| Open item | 5 extra AVAX signals in Run 93 vs Run 48 (270-day spread, not market drift) — diff-trace queued before Sprint 3 |

---

## Session: 2026-05-22 — Audit Cycle 7 / Fix Session 4 (autonomous loop)

Cycle 7 full 8-agent re-audit surfaced 4 CRITICAL findings (3 REGRESSIONs + 1 NEW critical). All 4 fixed in one batch — surgical edits, ≤10 lines each. Tests: 375/375 → 375/375.

### FIX-29 — DSR Silently Disabled by `DB_PATH` NameError (backtest.py:2839)
**Severity:** CRITICAL (NEW — silent failure of selection-bias correction)
**File changed:** `backtest.py:2839`
**Change:** `_sqlite3.connect(DB_PATH)` → `_sqlite3.connect(BT_DB_PATH)`
**Root cause:** Module defines `BT_DB_PATH = os.path.join(_ROOT, "data", "signals.db")` at line 151. The CPCV/DSR block referenced undefined `DB_PATH`. Outer `except Exception` swallowed the NameError → DSR never ran → deflated Sharpe never computed → reported Sharpe was never corrected for the 93+ historical optimizer trials. The ONLY anti-multiple-comparison safeguard in the backtest was silently dead.
**Test:** 375/375 pass. DSR will now actually execute on the next backtest run and deflate Sharpe by ~sqrt(log(93)) ≈ 2.13× — uncomfortable but honest.
**Impact:** Cycle 7 Backtest Validity: 5.5 → expected ~6.5 (DSR functional). Reported Sharpe in next backtest will materially decrease — operator should expect this.

### FIX-30 — DR Confluence Semantics Reversed in strategy_templates.py (REGRESSION-A)
**Severity:** CRITICAL (REGRESSION — 0/42 signals satisfied old check)
**Files changed:** `strategy_templates.py` Tier A (line 135-137), Tier B (line 205-207), Tier C (line 273-275)
**Change:** `(BUY and DISCOUNT) or (SELL and PREMIUM)` → `(BUY and PREMIUM) or (SELL and DISCOUNT)` in all 3 tiers (required confluence for A/B; bonus for C). Docstrings updated to explain post-displacement geometry.
**Root cause:** ICT post-MSS geometry — after a sweep + displacement, price has displaced INTO the opposite zone from the sweep, so BUYs land in PREMIUM and SELLs in DISCOUNT. The previous BUY+DISCOUNT semantics described PRE-sweep geometry. Run #85 empirical: 22 BUYs all in PREMIUM/UNKNOWN, 20 SELLs all in DISCOUNT/UNKNOWN → 0/42 satisfied old check. Tier-A's "5-of-5" became "4-of-4 + 1-impossible" — silently capped at 4/5 (Tier-A could only fire 1/42).
**Acknowledged limitation:** Replacement check is near-uniform in current data (since the strategy always emits this geometry post-MSS). Genuine discriminating power for Tier-A requires pre-sweep DR snapshot — deferred as Tier-A confluence redefinition (HIGH carry-over).
**Test:** 375/375 pass.

### FIX-31 — SMT Bonus Sign Flipped in strategy_templates.py (REGRESSION-B)
**Severity:** CRITICAL (REGRESSION — penalty applied against +12pp empirical edge)
**Files changed:** `strategy_templates.py` Tier A (line 143-144), Tier B (line 213-214), Tier C (line 269-270)
**Change:** `bonus -= 0.10; matched.append("SMT_penalty")` → `bonus += 0.10; matched.append("SMT_bonus")` in all 3 tiers. Docstrings updated.
**Root cause:** FIX-4 (2026-05-21) installed the -0.10 penalty citing Run 48 empirical data showing SMT-confirmed signals as anti-predictive. Run #85 cycle-7 audit re-validated: SMT=True 78.8% WR (n=33) vs SMT=False 66.7% WR (n=9) — SMT is now strongly predictive (+12.1pp). The penalty is corroded by ~5 cycles of accumulated learning.
**Test:** 375/375 pass.

### FIX-32 — tracker.py PARTIAL Counting Regression (REGRESSION-D / TT-7 class)
**Severity:** CRITICAL (REGRESSION — split-counting bug; same class as TT-7 which fixed `_tune_wr()`)
**Files changed:** `tracker.py:180-204` (`get_intelligence` per-token block) and `tracker.py:271-278` (`_get_adaptive_weights_raw` recent_wr)
**Change:**
- Per-token `w` was `COUNT(WIN+PARTIAL+PARTIAL_TP1+PARTIAL_TP2)` — double-counted partials as full wins → overstated WR. Split into separate WIN/PARTIAL/LOSS/EXPIRED counters and routed through `_canonical_wr()` (the existing PARTIAL=0.5 formula). Legacy `w` field retained for back-compat with downstream readers.
- Per-token `recent_wr` at lines 197 and 272: predicate `r in ("WIN","PARTIAL")` silently dropped `PARTIAL_TP1` and `PARTIAL_TP2` to 0 weight. Replaced with explicit `_PARTIAL_SET = ("PARTIAL","PARTIAL_TP1","PARTIAL_TP2")` and full-rows iteration.
**Root cause:** Two parallel counting paths in tracker dashboard never received the H21 / TT-7 partial-weighting upgrade. `_canonical_wr()` and `_tune_wr()` were correct; per-token intelligence and adaptive-engine dashboard were not.
**Test:** 375/375 pass.

### Cycle 7 Fix Session Summary

| Metric | Value |
|---|---|
| Fixes applied | 4 (FIX-29 through FIX-32) |
| Lines changed | ~30 across 3 files (backtest.py, strategy_templates.py, tracker.py) |
| Tests before / after | 375 / 375 |
| Regressions introduced | 0 |
| Expected score delta | Template 4 → ~7+; Backtest 5.5 → ~6.5; Adaptive 8.5 → 9; overall ~7.98 → ~8.6 (subject to cycle-8 re-audit confirmation) |
| Actual cycle-8 result | Template 4 → 9.0, Backtest 5.5 → 6.0, Adaptive 8.5 → 9.2; overall 7.98 → 8.75 |

---

## Session: 2026-05-22 — Audit Cycle 9 / Fix Session 5 (autonomous loop)

Cycle 8 audit (8.75/10) below 9.0 termination threshold → loop continued. Targeted the easiest HIGH carry-overs from cycle 8: 3 surgical adaptive/risk fixes + 1 hygiene test update. Tests: 375 → 375.

### FIX-33 — Env-var aware mirror constants in adaptive_engine.py (cycle 7 Risk SERIOUS)
**Severity:** HIGH (env-var override silently dropped)
**File changed:** `adaptive_engine.py:131-138`
**Change:** `_RISK_PER_TRADE_PCT = 0.01` / `_MAX_POSITION_PCT = 0.20` (hardcoded) → `_env_float(...)` helper reads from os.environ with same defaults.
**Root cause:** `adaptive_engine.py` cannot import `config.py` without a circular dep, so it mirrored two risk constants as hardcoded literals. If an operator overrode `MAX_POSITION_PCT=0.10` via env to halve exposure, `config.py` updated but `adaptive_engine.py`'s drawdown calc (line 1051) and portfolio risk accumulation (line 1016) silently kept using 0.20 — drawdown gate would understate by 2× and fail to fire early enough.
**Test:** 375/375.

### FIX-34 — Expand correlation guard to include XRP and ADA
**Severity:** HIGH (carry-over from cycle 1)
**File changed:** `adaptive_engine.py:986-990` (`PortfolioRiskLayer.CORRELATED`)
**Change:** `frozenset({"BTC","ETH","BNB","AVAX"})` → `frozenset({"BTC","ETH","BNB","AVAX","XRP","ADA"})`
**Root cause:** XRP and ADA both exhibit >0.65 Pearson correlation with BTC during 2024-2025 stress events. Pre-fix, the bot could hold 4 concurrent BUY positions across XRP + ADA + BNB + ETH and trigger zero correlation warning, since the warn-at-2/block-at-3 logic only counted CORRELATED members. HBAR/POL remain outside (genuinely lower-beta).
**Test:** 375/375.

### FIX-35 — Update stale test_tracker_db_alignment.py invariant (cycle 8 N1)
**Severity:** LOW (test hygiene — would produce false-fail noise when run against real PARTIAL_TP1/2 data)
**File changed:** `tests/test_tracker_db_alignment.py:190-211`
**Change:** Replaced expected `wins = sum(1 for r in ("WIN","PARTIAL"))` with canonical `1.0 if r=="WIN" else 0.5 if r in _PARTIAL_SET else 0.0` weighting. Updated query IN-clause to include `'PARTIAL_TP1','PARTIAL_TP2'`. Header text updated.
**Root cause:** Cycle-7 Fix #32 corrected `tracker.py` `recent_wr` to use canonical weighting; this test re-implemented the OLD broken formula as the "expected" reference, which would produce false failures whenever production DB contains PARTIAL_TP1 or PARTIAL_TP2 rows.
**Test:** File is in `--ignore=` list of standard pytest invocation; runs separately. Logic verified by inspection.

### FIX-36 — Tighten `DEGENERATE_THRESHOLD` 0.45 → 0.40
**Severity:** MEDIUM (cycle 7/8 carry-over)
**Files changed:** `adaptive_engine.py:56` + `monitoring.py:59` + `tracker.py:27` (3 mirrored locations)
**Change:** `0.45` → `0.40` in all three.
**Root cause:** AVAX bootstrap weight at 0.448 was skimming just under the 0.45 bar (3.2× default for fvg_quality), so the runtime degenerate fallback at `crypto_alert.py:2007` left a near-collapsed bootstrap active rather than substituting `AE_DEFAULT_WEIGHTS`. Lowered to 0.40 (2.4× default) which still permits genuine learned concentration but catches AVAX-class near-collapse.
**Critical side-effect found by CI:** `monitoring.py:59` and `tracker.py:27` carry hardcoded mirrors of the same threshold; `tests/test_monitoring.py:41` immediately failed when adaptive_engine was tightened but monitoring was not — exactly the M24-class parameter-drift bug the test was added to catch. Test mechanism worked. All three mirrors synced.
**Test:** 375/375 after monitoring + tracker sync.

### Cycle 9 Fix Session Summary

| Metric | Value |
|---|---|
| Fixes applied | 4 (FIX-33 through FIX-36) |
| Files changed | 5 (adaptive_engine.py, monitoring.py, tracker.py, tests/test_tracker_db_alignment.py) |
| Tests before / after | 375 / 375 |
| Regressions introduced | 0 (CI caught DEGENERATE_THRESHOLD mirror drift immediately — fixed inline) |
| Cycle 10 finding | Fix #34 was PARTIAL — SQL at adaptive_engine.py:1092 still hardcoded old 4-token list; flagged by 2 independent agents (risk-management-auditor + adaptive-learning-code-reviewer) |

### FIX-34b — Close Correlation SQL/Frozenset Desync (cycle 10 inline regression fix)
**Severity:** HIGH (correlation BLOCK silently bypassed for XRP/ADA — the exact tokens Fix #34 was meant to protect)
**File changed:** `adaptive_engine.py:1088-1102`
**Change:** Replaced hardcoded `"AND token IN ('BTC','ETH','BNB','AVAX')"` literal with dynamic IN-clause built from `self.CORRELATED` frozenset using parameterised placeholders.
**Root cause:** Fix #34 expanded `CORRELATED` to include XRP+ADA but the SQL at line 1092 kept the old 4-token literal. Net effect: XRP/ADA tokens entered the gate (via `if token in self.CORRELATED`) but their open peers were never counted by the query — so the 3+ BLOCK rule could never trigger for XRP/ADA-led clusters. Frozenset and SQL must always agree.
**Test:** 375/375.
**Followup proactive guard:** add a CI test asserting the SQL's IN-clause membership equals `PortfolioRiskLayer.CORRELATED` to prevent future single-side edits.

---

## Session: 2026-05-22 — Audit Cycle 11 / Fix Session 6 (autonomous loop, single fix to cross 9.0)

Cycle 10 overall 8.96/10 — 0.04 short of termination threshold. Single highest-leverage fix to push over: migrate `MAX_SL_PCT`/`MIN_SL_PCT` to config.py so operator can env-override.

### FIX-37 — Migrate MAX_SL_PCT / MIN_SL_PCT to config.py with env-var support
**Severity:** MEDIUM (carry-over from cycle 7+8+10 risk audits)
**Files changed:** `config.py:185-189` (new constants); `ict_engine.py:33-37` (import from config)
**Change:** Added `MAX_SL_PCT = _env_float("MAX_SL_PCT", 0.030)` and `MIN_SL_PCT = _env_float("MIN_SL_PCT", 0.005)` to config.py. Replaced ict_engine.py module-level literals with `from config import MAX_SL_PCT, MIN_SL_PCT`. All existing callers (`crypto_alert.py:71`, `backtest.py:66`) work unchanged via re-export.
**Root cause:** `config.py:38` docstring used `MAX_SL_PCT=0.025` as an example env override, but ict_engine.py hardcoded the literal — silent no-op for any operator attempting to tighten the stop ceiling via env var. Found in cycle 7 risk audit, persisted through cycles 8 and 10.
**Test:** 375/375.

