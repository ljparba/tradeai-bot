# Backtest Explorer Audit — Post-CRT-Pro

**Date:** 2026-05-27
**Auditor:** Claude (Opus 4.7, 1M ctx)
**Scope:** `scripts/autonomous_explorer.py` + `scripts/promote_baseline.py` + `scripts/compute_cross_config_sr_std.py` and their interaction with today's CRT (Candle Range Theory) Session-2 / Session-3 ship.
**Mode:** Read-only. No files modified.
**Explorer state:** `inactive` (systemd), last session `freq_hunt_2026_05_27_v3` PAUSED at trial 18/70 by SIGTERM at `2026-05-27T06:13:48Z`. Pin = Run-81 (DSR 98.7%).
**Operator env state:** `.env` has `ENABLE_H4_CRT=1`, `CRT_TP1_MODE=min_1r`, `BACKTEST_BIAS_4H_GATE=strict`, `WYCKOFF_PHASE_FILTER=off`, `ENABLE_5M_SWEEP=0` (CRT-only mode).

---

## TL;DR

The autonomous explorer is **NOT CRT-aware**. The Optuna search space, anti-overfit guards, Pareto archive schema, and auto-promotion path were all built before CRT existed and have **zero references** to any CRT knob (`grep -rn "CRT_\|WYCKOFF\|ENABLE_H4_CRT\|ENABLE_5M_SWEEP" scripts/` returns nothing). The good news: the `config_hash` payload (today's B-CRT-S2-C2 + NEW-1 + Option-KK + Pro-v1.1 fixes) already includes every CRT env knob — so the DSR `n_trials` pool and Pareto archive are *protected from collision* even if a CRT run is recorded.

The bad news: if the operator starts the explorer NOW with the current `.env` (`ENABLE_5M_SWEEP=0`, `ENABLE_H4_CRT=1`), the explorer subprocess will **inherit those values**, will spend ~11 minutes per trial running a backtest where **all 8 search-space params are no-ops on the disabled 5M_SWEEP scanner**, while every trial's signals come from the CRT scanner — whose params are not being tuned. Result: **wasted compute, misleading Pareto archive entries** that look like 5M_SWEEP wins but are actually CRT-only runs.

There are **2 CRITICAL** findings (subprocess env inheritance + Pareto archive schema-blind to CRT), **3 HIGH** findings (DSR pool now mixes CRT and pre-CRT runs without filter, anti-pattern lock doesn't cover CRT regressions, objective math undefined for n=0 CRT-only trials in the operator's current config), and **3 MEDIUM** findings.

---

## Section A — Explorer search space coverage

### Finding A-1 — Search space pre-dates CRT entirely 🟡 MEDIUM

**File:** `scripts/autonomous_explorer.py:411-421` (`_suggest_params`)

The Optuna search space is exactly 8 params, all 5M_SWEEP / shared-ICT:

```
ICT_SWEEP_LOOKBACK       (int 15-60 step 5)
ICT_MSS_HORIZON          (int 10-60 step 5)
ICT_FVG_MIN_GAP          (float 0.0005-0.0030 step 0.0001)
DEALING_RANGE_LOOKBACK   (int 30-100 step 10)
BACKTEST_BIAS_4H_GATE    (cat: none|loose|strict)
BACKTEST_TREND_1H_GATE   (cat: none|loose|strict)
BACKTEST_FVG_MIN_QUALITY (cat: LOW|MEDIUM|HIGH)
BACKTEST_MSS_MIN_QUALITY (cat: LOW|MEDIUM|HIGH)
```

**No CRT params present.** Specifically not searched: `CRT_TP1_MODE`, `H4_CRT_C2_LOOKBACK`, `H4_CRT_MSS_HORIZON`, `H4_CRT_OB_SCAN_LOOKBACK`, `H4_CRT_VALIDATION_SCHOOL`, `WYCKOFF_PHASE_FILTER`, `CRT_TP2_RR`, `CRT_TP3_RR`, `CRT_FORWARD_BARS`, `CRT_APPLY_QUALITY_GATES`, `CRT_FVG_MIN_QUALITY`, `CRT_MSS_MIN_QUALITY`, `CRT_REQUIRE_1H_TREND`.

**Verdict:** EXPECTED and DESIRABLE for today. The CRT calibration is still being shaped manually by the operator (today's findings rejected `CRT_APPLY_QUALITY_GATES=1`, `WYCKOFF_PHASE_FILTER=strict` empirically). The explorer should not stumble onto those regions until manual calibration plateaus. Note though that the search space remains 100% 5M_SWEEP-tuned — see Section I for the consequence under current `.env`.

### Finding A-2 — Boolean toggles correctly excluded 🟢 LOW

`ENABLE_5M_SWEEP` and `ENABLE_H4_CRT` are not in `_suggest_params`. Correct: they're operator-deliberate kill switches, not tunable params.

---

## Section B — Env variable propagation

### Finding B-1 — Subprocess inherits operator's `ENABLE_5M_SWEEP=0` 🔴 CRITICAL

**Files / lines (the smoking gun):**

- `scripts/autonomous_explorer.py:424-438` (`_params_to_env`):
  ```python
  def _params_to_env(params: dict) -> dict:
      env = os.environ.copy()              # inherits parent (= systemd .env)
      for k, v in params.items():
          env[k] = str(v)
      env["BOOTSTRAP_AFTER_RUN"] = "0"
      env["WRITE_CPCV_VERDICT"] = "0"
      return env                            # NO removal of ENABLE_5M_SWEEP / ENABLE_H4_CRT
  ```
- `deploy/tradeai-explorer.service:23-27`:
  ```ini
  EnvironmentFile=/home/tradeai/TradeAI/.env                        ← inherits ENABLE_5M_SWEEP=0
  EnvironmentFile=-/home/tradeai/TradeAI/.env.explorer
  ExecStart=/usr/bin/python3 -u /home/tradeai/TradeAI/scripts/autonomous_explorer.py
  ```
- `backtest.py:3686`: `if ENABLE_5M_SWEEP: ...` — gates the 5M_SWEEP scanner the explorer is tuning.

**Consequence with operator's current `.env`:**

1. Operator runs `sudo systemctl start tradeai-explorer`.
2. systemd loads `.env` → exports `ENABLE_5M_SWEEP=0, ENABLE_H4_CRT=1`.
3. Python explorer starts, `os.environ` already has both.
4. Optuna proposes e.g. `ICT_SWEEP_LOOKBACK=25, BACKTEST_FVG_MIN_QUALITY=MEDIUM, …`.
5. `_params_to_env(params)` does `env = os.environ.copy()` (preserves `ENABLE_5M_SWEEP=0`), overlays the 8 search params.
6. Subprocess starts `python3 backtest.py` with merged env.
7. `backtest.py:3686 if ENABLE_5M_SWEEP:` short-circuits — **5M_SWEEP scanner is OFF**.
8. The CRT scanner runs (`ENABLE_H4_CRT=1`) and emits signals — but Optuna tuned only `ICT_SWEEP_LOOKBACK`, `BACKTEST_FVG_MIN_QUALITY`, etc., NONE of which the CRT scanner reads.
9. Trial finishes in ~11 min. `cpcv_mean / DSR` are computed over CRT-only signals.
10. Optuna treats those metrics as *caused by* the proposed 5M_SWEEP params → polluted gradient.

**Severity:** CRITICAL because (a) every minute of explorer compute is wasted under this operator state, (b) Pareto archive entries land in the file recording 5M_SWEEP params attributed to CRT-derived metrics, (c) auto-promotion logic at `autonomous_explorer.py:861-887` may eventually pass the eligibility check on a "lucky" CRT-only run — promoting a `BACKTEST_BIAS_4H_GATE=loose` change that didn't actually drive the win.

### Finding B-2 — Same vector for `ENABLE_H4_CRT` 🟠 HIGH

By symmetry: `_params_to_env` does not pin `ENABLE_H4_CRT` either. If a future operator session sets `ENABLE_H4_CRT=0` in `.env` (and `ENABLE_5M_SWEEP=1`), the subprocess is correctly 5M_SWEEP-only — that's safe but obscured: trials look like they have CRT off, not because the explorer set it off but because of parent env. Symbolically the same bug class. Recommended fix in §"Top 3 Priority Fixes" makes it explicit.

### Finding B-3 — Pre-cache warm has the same inheritance 🟠 HIGH

**File:** `scripts/autonomous_explorer.py:361-408` (`_precache_warm`)

```python
def _precache_warm(...):
    env = os.environ.copy()              # ← same inheritance
    env["BOOTSTRAP_AFTER_RUN"] = "0"
    env["WRITE_CPCV_VERDICT"] = "0"
    subprocess.run([..., "backtest.py", "--clear-checkpoint"], env=env, ...)
    subprocess.run([..., "backtest.py"], env=env, ...)
```

The pre-cache warm runs a full backtest. With `ENABLE_5M_SWEEP=0` inherited, the warm step generates CRT-only signals into a transient `backtest_runs` row, which is then `_cleanup_run_row`'d. The cache (5M/4H Binance candles) is still warmed correctly because both scanners fetch the same OHLCV. **Not critical**, but the warm-run cost burns 5-15 minutes of unnecessary work and creates a CRT row that is reaped.

### Finding B-4 — Bootstrap + verdict guards correctly extended 🟢 LOW (already fixed)

`_params_to_env:431-437` sets `BOOTSTRAP_AFTER_RUN=0` and `WRITE_CPCV_VERDICT=0`. `backtest.py:4035` and `backtest.py:3855` honor both. The R3 protection (no `token_weights` writes, no `latest_cpcv_verdict` overwrite) is intact for CRT and 5M_SWEEP runs alike, since the env-guards predate today's CRT changes.

---

## Section C — Objective function CRT-awareness

### Finding C-1 — Objective treats all signals as one pool 🟡 MEDIUM

**File:** `scripts/autonomous_explorer.py:1043-1066`

```python
_n_obs = m.get("n") if m and m.get("n") is not None else 0
_n_bonus = N_BONUS_ALPHA * math.log(max(1, _n_obs))
if verdict == "PASS":
    _score = float(m["cpcv_mean"]) + _n_bonus
…
```

`m["n"]` is read by regex from `Total: \d+ signals` in backtest stdout (`autonomous_explorer.py:480`). Under today's parallel-scanner design, the printed total is **5M_SWEEP + CRT signals combined** (`backtest.py:3696 all_signals.extend(sigs); 3718 all_signals.extend(crt_sigs)`). The explorer therefore optimizes `cpcv_mean + α·log(n_blend)` without distinguishing sources.

**Why it's only MEDIUM:** the merged metric is *honest* at the aggregate level (CPCV runs on the union, DSR pool is keyed by full `config_hash`). It just isn't *attributable*. As long as the operator manually decides what gets tuned, this is fine.

**Why it could escalate to HIGH:** combined with B-1, the CRT signals' WR drives the cpcv_mean while the 5M_SWEEP params get the credit/blame. That is misattribution at the optimization level.

### Finding C-2 — Objective produces a sane n=0 sentinel 🟢 LOW

`_n_bonus = α · log(max(1, n))` so n=0 → bonus=0. Error path (`m.get("cpcv_mean") is None`) returns `-100.0` sentinel (line 1066, post-H-1 fix). If the operator's `.env` results in a CRT-only run that produces zero CRT signals (e.g., `WYCKOFF_PHASE_FILTER=strict` kills all candidates), the regex `Total:\s+(\d+)\s+signals` returns `0` and the explorer correctly handles it as a FAIL with `_score = cpcv_mean - 30 + 0`. Defensible.

---

## Section D — config_hash + DSR n_trials integrity

### Finding D-1 — config_hash correctly includes ALL today's CRT knobs 🟢 LOW (already protected)

**File:** `backtest.py:3491-3529` — `_compute_run_config_hash` now includes:

- `ENABLE_H4_CRT`, `H4_CRT_DISABLED_TOKENS`, `H4_CRT_C2_LOOKBACK`, `H4_CRT_MSS_HORIZON`, `H4_CRT_VALIDATION_SCHOOL`
- `CRT_FORWARD_BARS`, `H4_CRT_OB_SCAN_LOOKBACK`
- `WYCKOFF_PHASE_FILTER`
- `CRT_TP1_MODE`, `CRT_APPLY_QUALITY_GATES`, `CRT_FVG_MIN_QUALITY`, `CRT_MSS_MIN_QUALITY`, `CRT_REQUIRE_1H_TREND`
- `ENABLE_5M_SWEEP`

All 14+ env knobs are read via `os.environ.get(..., DEFAULT)`. Two CRT runs with different `CRT_TP1_MODE` produce different hashes; a 5M-only and a CRT-only run on identical ICT params produce different hashes. **DSR `n_trials` and Pareto-archive uniqueness are honest.**

### Finding D-2 — `compute_cross_config_sr_std.py` is naively inclusive 🟠 HIGH

**File:** `scripts/compute_cross_config_sr_std.py:130-149` (`_list_distinct_configs`)

```sql
SELECT br.config_hash, MAX(br.id) AS latest_run_id
FROM backtest_runs br
WHERE br.config_hash IS NOT NULL
GROUP BY br.config_hash
```

Every distinct `config_hash` with `>= min_signals` signals contributes to the cross-config Sharpe std. With CRT now in the hash, **CRT-flavored runs and 5M-only runs land in the same pool** — but they are fundamentally different strategies (different scanners, different setups, different killzones). The std across them measures *strategy heterogeneity*, not *parameter heterogeneity*.

**Concrete impact today:** the pool still has its baseline `sr_trial_std = 0.0836` (24 distinct pre-CRT configs). Once a CRT run lands at distinct hash and crosses `min_signals=30`, it will be folded in. If CRT's OOS-Sharpe is very different from the 5M_SWEEP cluster, the std balloons → DSR drops across the board → the next explorer trial sees lower DSR vs pin → `best_dsr_drop_vs_pin_pp` guard at `autonomous_explorer.py:583-586` will trip on `5.0pp` drop.

**Severity:** HIGH because (a) the guard can falsely halt a session, and (b) the resulting DSR isn't apples-to-apples with Run-81's promotion-time DSR.

### Finding D-3 — Pre-CRT historic runs preserved 🟢 LOW

`compute_cross_config_sr_std.py` reuses the latest run per hash. Pre-CRT historic configs (Run #1-#125) had no CRT knobs in env when their hash was computed (they hashed `os.environ.get("ENABLE_H4_CRT", "0")` to "0" since the env var wasn't set — confirmed by `backtest.py:3496`'s `"0"` default). Their hashes remain stable. **No orphaning.**

---

## Section E — Pareto archive + promotion safety

### Finding E-1 — Pareto archive schema doesn't record source attribution 🔴 CRITICAL

**File:** `scripts/autonomous_explorer.py:954-965`

```python
_update_pareto_archive({
    "trial_id":    trial.number,
    "study_name":  study_name,
    "params":      params,           # only the 8 search-space dims
    "n":           m.get("n"),
    "wr":          m.get("wr"),
    "cpcv_mean":   m.get("cpcv_mean"),
    "cpcv_std":    m.get("cpcv_std"),
    "sharpe":      m.get("sharpe"),
    "dsr":         m.get("dsr"),
    "captured_at": ...
})
```

The entry records the **8 tuned params only**. It does NOT record `ENABLE_5M_SWEEP`, `ENABLE_H4_CRT`, or any CRT knob. Existing 10 entries (`data/pareto_archive.json`) confirm — every entry has exactly the 8 keys.

If the explorer runs under operator's current env, a new Pareto entry will be saved with:
- `params = {ICT_SWEEP_LOOKBACK: 25, BACKTEST_FVG_MIN_QUALITY: MEDIUM, …}` (the 8 Optuna params)
- `n, wr, cpcv_mean, sharpe, dsr` derived from CRT-only signals
- **NO record** that `ENABLE_5M_SWEEP=0` and `ENABLE_H4_CRT=1` were the actual drivers.

**Result:** the Pareto archive is **silently corrupted**. A future operator inspecting the archive cannot reproduce these entries from `params` alone. Auto-promotion uses `params` to call `promote_baseline.py` — but the actual config that produced the metrics also depended on the CRT env knobs that aren't there.

**Severity:** CRITICAL because the archive is presented in the dashboard ("Auto-Explorer" tab) and treated as ground truth.

### Finding E-2 — `_auto_promote` headline-param picker is CRT-blind 🟠 HIGH

**File:** `scripts/autonomous_explorer.py:779-822`

```python
nice_key = {
    "BACKTEST_BIAS_4H_GATE":  "bias_4h_gate",
    "BACKTEST_TREND_1H_GATE": "trend_1h_gate",
    "BACKTEST_FVG_MIN_QUALITY": "fvg_min_quality",
    "BACKTEST_MSS_MIN_QUALITY": "mss_min_quality",
    "ICT_SWEEP_LOOKBACK":  "ict_sweep_lookback",
    …
}
```

The map covers all 8 search-space params but no CRT knobs. If the search space is later expanded to include `WYCKOFF_PHASE_FILTER`, the headline-param fallback (line 796 `.get(k, k.lower())`) silently uses the raw env-name lower-cased — which won't match any key in `pin["key_settings"]` (because `_current_settings()` in `promote_baseline.py:33-50` doesn't include CRT settings either).

**Severity:** HIGH because the headline-param logging would be silently wrong on the first CRT-inclusive promotion.

### Finding E-3 — `promote_baseline._current_settings()` is CRT-blind 🟠 HIGH

**File:** `scripts/promote_baseline.py:33-50`

```python
return {
    "bias_4h_gate":              cfg.LIVE_BIAS_4H_GATE,
    "trend_1h_gate":             cfg.LIVE_TREND_1H_GATE,
    "dealing_range_gate_live":   cfg.LIVE_DEALING_RANGE_GATE,
    "dealing_range_gate_backtest": cfg.BACKTEST_DEALING_RANGE_GATE,
    "mss_min_quality":           cfg.LIVE_MSS_MIN_QUALITY,
    "fvg_min_quality":           cfg.LIVE_FVG_MIN_QUALITY,
    "ict_sweep_lookback":        ict.ICT_SWEEP_LOOKBACK,
    "ict_swing_n":               ict.ICT_SWING_N,
    "ict_mss_horizon":           ict.ICT_MSS_HORIZON,
    "ict_fvg_min_gap":           ict.ICT_FVG_MIN_GAP,
    "ict_eqh_tolerance":         ict.ICT_EQH_TOLERANCE,
}
```

If a CRT-influenced backtest gets auto-promoted, `baseline_pin.json` will be written with `key_settings` that **omit** every CRT knob and `ENABLE_5M_SWEEP`. A future rollback that diffs against current state will see those CRT knobs change *silently* — the audit trail is broken.

**Severity:** HIGH because `baseline_pin.json` is the canonical reference for "what is the baseline" and currently does not include CRT signature.

### Finding E-4 — Auto-promotion eligibility math depends on pin_n proximity 🟡 MEDIUM

**File:** `scripts/autonomous_explorer.py:732-735`

```python
if pin_n > 0:
    n_change_pct = abs((m.get("n") or 0) - pin_n) / pin_n * 100
    if n_change_pct > PROMOTE["n_change_pct_max"]:  # 20%
        return False, f"n change {n_change_pct:.1f}% > 20%"
```

Pin's `n=35` (Run-81 from baseline_pin.json). Under the operator's current `.env` (CRT-only, ENABLE_5M_SWEEP=0), a typical CRT signal count is `181-416` (per today's notes). A CRT-driven trial with n=416 produces `n_change_pct = |416 - 35| / 35 * 100 = 1089%`. This **correctly** blocks auto-promotion. So the system fails-safe here — no false promotions of CRT-shaped runs against a 5M_SWEEP pin. ✓

But it also means **no auto-promotion is achievable** while the operator is in CRT-only mode. The explorer would run for hours and never promote.

---

## Section F — Live OGD bootstrap interaction (R3 protection)

### Finding F-1 — R3 protection holds, but admits new flow 🟡 MEDIUM

**Files:**
- `scripts/autonomous_explorer.py:431-437` — explorer sets `BOOTSTRAP_AFTER_RUN=0` for every subprocess.
- `backtest.py:4035` — `_BOOTSTRAP_AFTER_RUN = os.environ.get("BOOTSTRAP_AFTER_RUN", "1") == "1"` — explorer trials correctly skip the bootstrap write.
- `adaptive_engine.py:936-955` — today's loosened bootstrap WHERE clause admits OB-only CRT rows.

**Walk-through:** during an explorer trial, `backtest_signals` rows ARE written (the explorer relies on them to compute CPCV/DSR; `_cleanup_run_row` later deletes them and their associated `backtest_runs` row at `autonomous_explorer.py:1017`). The bootstrap-from-backtest call is gated by `BOOTSTRAP_AFTER_RUN=1`. The explorer always sets this to `0`. So **no `backtest_token_weights` writes during explorer trials.**

**Residual risk:** if the operator manually runs `python3 backtest.py` (NOT via the explorer) with `ENABLE_H4_CRT=1` AND `BOOTSTRAP_AFTER_RUN=1` (the default), the loosened WHERE clause will pull CRT-OB rows into the OGD warm-start pool. That's by-design today (operator chose it). The explorer doesn't create this risk; the explorer correctly opts out.

### Finding F-2 — Cleanup race: explorer's CRT signals deleted along with row 🟢 LOW

`_cleanup_run_row` at `autonomous_explorer.py:520-531`:
```python
con.execute("DELETE FROM backtest_signals WHERE run_id=?", (run_id,))
con.execute("DELETE FROM backtest_runs WHERE id=?", (run_id,))
```

Deletes both 5M_SWEEP and CRT signals (since the run_id is shared). Clean. No CRT contamination leak from explorer trial rows.

---

## Section G — Anti-overfit guard CRT-awareness

### Finding G-1 — Anti-pattern lock doesn't cover today's empirically-disproven CRT settings 🟠 HIGH

**File:** `scripts/autonomous_explorer.py:157-160`

```python
ANTI_PATTERN_LOCKS = {
    "ICT_SWING_N":      2,
    "ICT_MIN_RR_GATE":  1.5,
}
```

Today's findings established CRT anti-patterns:
- `CRT_APPLY_QUALITY_GATES=1` empirically harmful (-21% total R)
- `WYCKOFF_PHASE_FILTER=strict` empirically harmful (-5.22pp WR)
- (And historic: `CRT_TP1_MODE=fixed_1r` was earlier rejected.)

`_assert_anti_pattern_locks()` at `autonomous_explorer.py:163-188` only checks the 2 hardcoded `ict_engine` constants. If the operator later expands the search space to CRT knobs (or accidentally sets a CRT env var that pollutes the trial), there's no startup gate.

**Severity:** HIGH because the protection model (a startup assertion that previously-disproven regions are NOT searchable) does not extend to CRT.

### Finding G-2 — Code-drift guard catches CRT file changes 🟢 LOW (already covered)

`CODE_FILES = ["config.py", "backtest.py", "ict_engine.py"]` at `autonomous_explorer.py:81`.

`crt_engine.py` is NOT in this list. **However**, `backtest.py` imports CRT defaults from `crt_engine.py` at module load (line 119-138 of backtest.py). When the explorer subprocess starts a backtest, those constants are captured at import time. If the operator edits `crt_engine.py` mid-session, the subprocess sees the new value — but `_hash_code_files()` does not see the change in its sha256 over `config.py / backtest.py / ict_engine.py`. The code-drift guard would NOT trip.

**Impact:** the operator can technically silently retune CRT mid-session without tripping the guard. Today this isn't a hot risk (CRT params are env-overridable, not source-edited usually), but it's a future hole. Logging this for awareness.

### Finding G-3 — `sr_trial_std_jump` guard sensitive to CRT pool dilution 🟠 HIGH

**File:** `scripts/autonomous_explorer.py:593-599`

```python
if self.best_dsr > 0 and self.start_sr_std > 0:
    current_std = _read_cross_config_std()
    if current_std > 0:
        jump_pct = (current_std - self.start_sr_std) / self.start_sr_std * 100
        if jump_pct > GUARD["sr_trial_std_jump_pct"]:  # 25%
            return "sr_trial_std_jump (...)"
```

As D-2 noted: once enough CRT-distinct hashes accumulate in `backtest_runs` and the operator manually runs `compute_cross_config_sr_std.py` (it's also called by `_refresh_cross_config_std` after every auto-promote), the std can jump >25% legitimately. This guard would then **trip on the next trial** and end the session.

**Severity:** HIGH because this is now a known triggerable false-positive in CRT-mixed environments.

---

## Section H — Honest CRT findings interaction

### Finding H-1 — Disproven CRT params not in search space (today's only protection) 🟡 MEDIUM

The empirically-rejected settings (`CRT_APPLY_QUALITY_GATES=1`, `WYCKOFF_PHASE_FILTER=strict`) cannot be retested by the explorer because they're not in `_suggest_params`. **Protection holds by absence, not by assertion.**

If a future PR adds CRT knobs to the search space without also adding entries to `ANTI_PATTERN_LOCKS`, those settings could be re-explored. There is no negative-list mechanism (e.g., "explorer must never propose `WYCKOFF_PHASE_FILTER=strict`"). Document this in the explorer's README or `_suggest_params` docstring.

---

## Section I — Operator workflow conflicts

### Finding I-1 — Starting explorer NOW under operator's current `.env` is WASTED COMPUTE 🔴 CRITICAL

**Scenario:** operator runs `sudo systemctl start tradeai-explorer` right now.

**Actual behavior** (with file:line evidence):

1. `deploy/tradeai-explorer.service:23` loads `.env` → exports `ENABLE_5M_SWEEP=0, ENABLE_H4_CRT=1, CRT_TP1_MODE=min_1r, WYCKOFF_PHASE_FILTER=off, BACKTEST_BIAS_4H_GATE=strict`.
2. `autonomous_explorer.py:1070` enters `run_study()` → calls `_assert_anti_pattern_locks()` (passes, the locks don't cover CRT) → calls `_precache_warm()` → runs a CRT-only backtest (the 5M_SWEEP branch is short-circuited at `backtest.py:3686`).
3. For each Optuna trial:
   - `_suggest_params` returns 8 params, all 5M_SWEEP-tunable.
   - `_params_to_env` overlays them on `os.environ.copy()`, which still has `ENABLE_5M_SWEEP=0`.
   - Subprocess runs `backtest.py` with `ENABLE_5M_SWEEP=0` → no 5M signals.
   - CRT scanner emits its (181-416)ish signals using fixed CRT params from `.env`.
   - Trial metrics reflect CRT signal performance.
   - Optuna attributes metrics to the 8 5M_SWEEP params — **misattribution**.
4. After ~30 trials (~6 hours), Pareto archive is polluted with entries that:
   - Record only 5M_SWEEP params.
   - Have metrics from CRT signals.
   - Are not reproducible without knowing the CRT env (which the archive does not record).
5. Auto-promotion blocked by `n_change_pct > 20%` gate (per E-4), so live state is safe — but `baseline_pin.json` is not at risk.

**Three operating modes ranked from safest to most dangerous:**

| Mode | `.env` | Behavior | Verdict |
|---|---|---|---|
| **A. Don't run explorer** | current (CRT-only) | n/a | ✅ Recommended for current paper-soak phase |
| **B. Restore 5M_SWEEP for explorer session** | set `ENABLE_5M_SWEEP=1, ENABLE_H4_CRT=0` before `systemctl start` | explorer tunes its native search space; live bot stops emitting CRT until reverted | ⚠️ Splits paper/explorer attention; CRT paper soak interrupted |
| **C. Run explorer as-is under current `.env`** | `ENABLE_5M_SWEEP=0, ENABLE_H4_CRT=1` | misattribution + polluted Pareto archive | ❌ Do not do this |

---

## Section J — Self-test / regression

### Finding J-1 — No existing explorer tests 🟢 LOW

```bash
$ ls tests/ | grep -i 'explorer\|promote'
# (no output)
```

There are no automated tests for the explorer subprocess env propagation, Pareto archive schema integrity, or guard trip-condition behavior. This is pre-existing, not a CRT-induced regression.

### Finding J-2 — `--status` is functional and read-only 🟢 LOW

```
[status] session     : freq_hunt_2026_05_27_v3  (PAUSED)
[status] pause reason: stopped_by_sigterm
[status] trials      : 18/70  PASS=9 FAIL=8 ERROR=1
[status] pin         : Run-81  DSR=98.7
[status] auto-promotions today: 0/2
[status] Pareto archive top 10 (non-dominated configs)
```

All entries reflect the PRE-CRT session that ran overnight. Confirmed no CRT contamination yet because the operator's last explorer session ended at 06:13:48Z (~3.5 hours before CRT Session-3 shipped, based on commit log).

### Finding J-3 — Pareto archive top-10 are all pre-CRT 🟢 LOW

```bash
$ python3 -c "...; ks=set(); [ks.update(e['params'].keys()) for e in archive]"
   BACKTEST_BIAS_4H_GATE
   BACKTEST_FVG_MIN_QUALITY
   BACKTEST_MSS_MIN_QUALITY
   BACKTEST_TREND_1H_GATE
   DEALING_RANGE_LOOKBACK
   ICT_FVG_MIN_GAP
   ICT_MSS_HORIZON
   ICT_SWEEP_LOOKBACK
```

All 10 archive entries use the 8-param schema only. No CRT knobs. Captured timestamps range 2026-05-24 → 2026-05-26 — all pre-CRT. **No CRT pollution in the archive yet** (because the explorer hasn't been run since CRT shipped).

---

## TOP 3 PRIORITY FIXES

### #1 (CRITICAL) — Pin scanner-toggle env vars in `_params_to_env`

**File:** `scripts/autonomous_explorer.py:424-438`

Suggested change (do not apply, audit-only): after the `for k, v in params.items()` loop, explicitly override the two scanner toggles so the subprocess always runs **both scanners** when tuning the 5M_SWEEP search space (or define an explicit operator-controllable mode).

```python
def _params_to_env(params: dict) -> dict:
    env = os.environ.copy()
    for k, v in params.items():
        env[k] = str(v)
    env["BOOTSTRAP_AFTER_RUN"] = "0"
    env["WRITE_CPCV_VERDICT"] = "0"
    # Explorer search space is 100% 5M_SWEEP — force 5M_SWEEP on regardless
    # of parent .env so trial metrics measure the tuned params, not whatever
    # scanner mix the operator is currently running for paper soak.
    env["ENABLE_5M_SWEEP"] = os.environ.get("EXPLORER_ENABLE_5M_SWEEP", "1")
    # CRT runs in shadow if operator wants attribution-blend, off otherwise.
    env["ENABLE_H4_CRT"]   = os.environ.get("EXPLORER_ENABLE_H4_CRT",   "0")
    return env
```

This decouples explorer trial env from operator paper-soak env. Also document the two new `EXPLORER_ENABLE_*` knobs in `deploy/env.explorer.example`.

### #2 (CRITICAL) — Record scanner-toggle + CRT signature in Pareto archive entries

**File:** `scripts/autonomous_explorer.py:954-965` (`_update_pareto_archive` call)

Add a `runtime_env` block snapshotting the env vars that affect signal output but live OUTSIDE `params`. This is what `_compute_run_config_hash` already enumerates at `backtest.py:3477-3530`. Without this, a Pareto entry is not reproducible.

```python
_update_pareto_archive({
    "trial_id":    trial.number,
    ...
    "runtime_env": {
        "ENABLE_5M_SWEEP":   os.environ.get("ENABLE_5M_SWEEP", "1"),
        "ENABLE_H4_CRT":     os.environ.get("ENABLE_H4_CRT",   "0"),
        "CRT_TP1_MODE":      os.environ.get("CRT_TP1_MODE",    "dynamic"),
        "WYCKOFF_PHASE_FILTER": os.environ.get("WYCKOFF_PHASE_FILTER", "off"),
        # ... other CRT knobs the explorer doesn't tune but the run depends on
        "config_hash":       m.get("config_hash"),  # canonical reproducibility key
    },
})
```

Same change must extend to `_auto_promote` log entry (`autonomous_explorer.py:833-844`) so the promotion log preserves CRT context.

### #3 (HIGH) — Extend `_current_settings()` and anti-pattern locks to cover CRT

**Files:**
- `scripts/promote_baseline.py:33-50` (`_current_settings`)
- `scripts/autonomous_explorer.py:157-160` (`ANTI_PATTERN_LOCKS`)

Add to `_current_settings()`:
```python
"enable_5m_sweep": os.environ.get("ENABLE_5M_SWEEP", "1"),
"enable_h4_crt":   os.environ.get("ENABLE_H4_CRT",   "0"),
"crt_tp1_mode":    os.environ.get("CRT_TP1_MODE",    "dynamic"),
"wyckoff_phase_filter": os.environ.get("WYCKOFF_PHASE_FILTER", "off"),
"crt_apply_quality_gates": os.environ.get("CRT_APPLY_QUALITY_GATES", "0"),
# ... full set per backtest.py:3491-3529
```

So `baseline_pin.json` records the full strategy fingerprint, not just ICT params.

Add to `ANTI_PATTERN_LOCKS` (or a new `CRT_ANTI_PATTERN_LOCKS`):
```python
CRT_ANTI_PATTERNS = {
    # If explorer ever tunes these, lock them to known-good values:
    "WYCKOFF_PHASE_FILTER":     ("off",   "loose"),   # strict empirically harmful 2026-05-27
    "CRT_APPLY_QUALITY_GATES":  ("0",),               # =1 empirically harmful 2026-05-27
}
```

with a corresponding assertion in `_assert_anti_pattern_locks()`.

---

## SECONDARY RECOMMENDATIONS (not in Top 3)

- **D-2 mitigation:** consider filtering `compute_cross_config_sr_std.py` to either (a) compute std *within* a scanner-mode bucket (5M-only / CRT-only / both-on) and pick the bucket matching the trial's `config_hash`, or (b) require `n >= 50` (vs current 30) to dampen noisy CRT-only entries from skewing the std until CRT has more soak. Lower-effort: just bump `--min-signals` to 50 before next explorer session.
- **G-2 mitigation:** add `crt_engine.py` to `CODE_FILES` so mid-session edits trip the code-drift guard.
- **J-1 mitigation:** add a unit test asserting `_params_to_env` pins both scanner toggles + the full CRT env signature, so future regressions are caught at CI time.

---

## VERDICT

**🔴 EXPLORER IS NOT SAFE TO RUN UNDER OPERATOR'S CURRENT `.env`.**

Three concrete reasons:
1. (B-1) Subprocess inherits `ENABLE_5M_SWEEP=0` → 8-param Optuna search becomes a no-op while CRT-only signals masquerade as 5M_SWEEP wins.
2. (E-1) Pareto archive will record those entries with no CRT context → silent corruption.
3. (G-3) `sr_trial_std_jump` guard becomes prone to false-positives once CRT runs land in the cross-config pool.

**Operator instructions for current cycle:**
- **Do not start the explorer until the Top-3 priority fixes are applied** (or, as a temporary workaround, before any `systemctl start tradeai-explorer`, manually export `ENABLE_5M_SWEEP=1, ENABLE_H4_CRT=0` for the explorer's session and accept that the live PAPER soak will lose CRT signals for that window).
- **Continue current operating mode** (`ENABLE_5M_SWEEP=0, ENABLE_H4_CRT=1`) for paper soak — that mode itself is safe (the bot's live path correctly gates both scanners at `crypto_alert.py:3654`).
- **Last clean Pareto/explorer state:** as of `--status` capture above, all 10 Pareto entries are pre-CRT and intact; no contamination has occurred yet.

**Estimated effort to apply Top-3 fixes:** ~45 min of code + 15 min of operator review. After fixes, run a 5-trial smoke session to verify (a) subprocess env contains pinned scanner toggles, (b) Pareto entry carries `runtime_env` block, (c) `_assert_anti_pattern_locks()` rejects `WYCKOFF_PHASE_FILTER=strict` if exported.

---

**End of audit. No files were modified.**
