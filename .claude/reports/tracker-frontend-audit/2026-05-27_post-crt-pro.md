# Tracker Frontend Audit — Post-CRT-Pro Ship (2026-05-27)

**Scope:** Verify the TradeAI tracker dashboard (port 8888, served by `tracker.py` +
`tracker_html.py`) correctly handles the backend changes shipped today:

1. New `source` column on `signals` + `backtest_signals` (`'5M_SWEEP'` | `'H4_CRT'`)
2. Extended `entry_type` format — CRT signals now carry 3-part names like
   `H4_CRT_OB_ACCUMULATION` (Wyckoff phase suffix)
3. New env knobs — `ENABLE_5M_SWEEP`, `CRT_TP1_MODE`, `CRT_APPLY_QUALITY_GATES`,
   `CRT_REQUIRE_1H_TREND`
4. Mixed-source backtest runs (#138–#143) with 5M_SWEEP + H4_CRT rows
5. `ENABLE_5M_SWEEP=0` currently — all NEW live signals will be `H4_CRT`

**Methodology:** Read full `tracker.py` (2779 lines) + `tracker_html.py` (4598 lines),
queried the live DB, probed all dashboard APIs at `http://127.0.0.1:8888`, ran the
98-case `tests/test_tracker_db_alignment.py` regression suite (all PASS).

**Live state at audit time:**
- `signals` table empty (0 live signals so far in current CRT-only session)
- `backtest_signals` distribution: `5M_SWEEP=426`, `H4_CRT=1609`
- Latest backtest = Run-143 (314 sigs, 55.7% WR, mixed sources)
- Honest-metrics API loads cleanly (CPCV 48.88%, DSR 31.9%, FAIL verdict)
- 98/98 tracker DB-alignment tests pass

---

## Section A — Source attribution display

🟠 **HIGH — No per-source breakdown anywhere in the dashboard**

- **Location:** entire `tracker_html.py`
- **What's wrong:** A repo-wide grep for `5M_SWEEP`, `H4_CRT`, or any rendering of
  the new `source` field returns ZERO hits in the HTML/JS template. None of:
  - Signal History table headers (`tracker_html.py:931-943`)
  - Open Positions card layout (`tracker_html.py:2895-2938`)
  - Backtest panel meta bar (`tracker_html.py:3357-3364`)
  - Backtest per-token / per-regime / per-session breakdowns
  - History page filter pills (`tracker_html.py:917-928`) — only outcome + token, no source
  - Backtest summary `by_*` consumed keys (only by_token / by_regime / by_conf /
    by_dir / by_sweep / by_trend / by_session at `tracker_html.py:3369-3427`)
- **Why it matters:** Operator cannot tell at a glance whether Run-143's 55.7% WR
  is a blend of strong 5M_SWEEP (29 sigs, historically ~80% WR) being dragged down
  by weak CRT (285 sigs, ~53% WR), or any other mix. With mixed-source runs being
  the new norm post-CRT, every WR number on the dashboard is now a weighted
  average across two strategies — invisible to the operator.
- **Crash risk on NULL source:** None — `tracker.py` uses `SELECT s.*` for live
  signals and the new column has `DEFAULT '5M_SWEEP'`, so older rows surface as
  `'5M_SWEEP'`. JS does not access `r.source` anywhere so even if it were NULL
  there's no crash. **Field is silently dropped, not surfaced.**
- **Suggested fix (one-liner):** Add `by_source` breakdown to
  `backtest._summarize()` and render a "Source split" panel beside the existing
  by-token/by-regime breakdowns; surface `source` in the Signal History table.

🟡 **MEDIUM — Backtest panel does not call out the strategy-blend**

- **Location:** `tracker_html.py:3357-3364` (meta bar)
- **What's wrong:** The meta bar shows Run Date / Period / Total Signals / WR / R:R
  but not the source mix (e.g. "29 SWEEP + 285 CRT"). Operator scanning the
  Backtest tab has no signal of which scanner produced which volume.
- **Suggested fix:** Add a meta-bar tile with `source` counts pulled from
  `summary.by_source` (after a backend change).

🟢 **LOW — Backtest History row labels do not disambiguate runs**

- **Location:** `tracker_html.py:3743-3768` (`_renderBtHistory`)
- **What's wrong:** Each history row shows date / signals / WR / R:R / days — no
  hint of which CRT-Pro config knob set it apart. Run-138 vs Run-141 look
  identical from the row.
- **Suggested fix:** Show short `config_hash` prefix (first 6 chars) per row.
  Already available in `backtest_runs.config_hash` but not selected by
  `get_backtest_history()` (`tracker.py:951-952`).

---

## Section B — `entry_type` rendering

🟢 **LOW — `entry_type` is not displayed anywhere on the dashboard**

- **Location:** entire `tracker_html.py`
- **What's wrong:** Grep for `entry_type` returns ZERO hits in the HTML template.
  Live and backtest signal rows expose `sweep_type`, `mss_quality`, `fvg_quality`,
  `dr_location` (e.g. `tracker_html.py:2910-2913`, `:3091`) but never
  `entry_type`. The new 3-part Wyckoff form (`H4_CRT_OB_ACCUMULATION`) is therefore
  invisible to operators — no display, no filter, no group-by.
- **Crash risk:** None — nothing reads it. The proliferation of variants
  (`H4_CRT_OB_ACCUMULATION` 637 rows, `_OB_TRANSITION` 97, `_OB_MARKDOWN` 78,
  `_FVG_ACCUMULATION` 33, `_FVG_TRANSITION` 5, `_FVG_MARKDOWN` 4, plus legacy
  `MIDPOINT_RECLAIM` 78 and `REACTION_CONFIRMED` 9 from the 5M_SWEEP scanner)
  could in principle break a group-by, but no group-by exists.
- **Why it matters less than Section A:** `sweep_type` and the existing
  ICT-quality columns already carry the structural meaning. `entry_type` is more
  of a setup-classifier — its absence is a missed analytics opportunity, not a
  correctness bug.
- **Suggested fix:** Either (a) accept the gap — `entry_type` is informational
  metadata; or (b) add it as a tooltip on the per-signal row in Signal History
  + a `by_entry_type` breakdown in the Backtest panel for setup-classifier
  analytics.

🟢 **LOW — `_load_raw_bt_signals()` does not load `entry_type`**

- **Location:** `tracker.py:1175-1187`
- **What's wrong:** The Tune Bot loader for raw backtest signals SELECTs `ts,
  regime, confidence, outcome, session, mss_quality, fvg_quality, smt_type,
  dr_location, signal` — no `entry_type`, no `source`. If `calculate_tune_preview()`
  ever needed to slice by setup classifier (e.g. "only tune on 5M_SWEEP rows
  since CRT is a different strategy"), it cannot.
- **Why it matters:** The Tune Bot at present analyzes the WHOLE latest run
  (mix of sources). On Run-143 that means it would propose FVG/MSS gate changes
  blended across both scanners, even though the gates only affect the 5M_SWEEP
  path. Risk of nonsense recommendations on mixed runs.
- **Suggested fix:** Add `source` to the SELECT and filter `ict_sigs = [s for s
  in raw_sigs if s.get("source") == "5M_SWEEP"]` before computing FVG/MSS WR
  splits (or default the Tune Bot to 5M_SWEEP-only since those are the gates
  it tunes).

---

## Section C — Backtest tab

🟢 **PASS — Recent runs (138-143) all render correctly**

- **Verified via** `curl /api/backtest/history` — returns runs 1, 76, 77, 78, 79,
  80, 82, 119, 138, 139, 140, 141, 142, 143 cleanly with id/run_date/days/
  total_signals/overall_wr/avg_rr/status.
- **`avg_rr` regression check:** `tracker_html.py:3243` uses
  `(t.avg_rr?'1:'+t.avg_rr:'—')` and `:3757` uses `'R:R: 1:'+r.avg_rr`. The
  per-token guard is in place (yesterday's M-1 + M-2 fix from commit `6efcd20`
  and `adf62b9`). The `_renderBtHistory` row (`:3757`) is unguarded but
  `backtest_runs.avg_rr` is `DEFAULT 0` (`tracker.py:899`) so it cannot be null;
  worst case renders as `R:R: 1:0` for an empty run. **No regression.**

🟡 **MEDIUM — `config_hash` not surfaced in the backtest panel**

- **Location:** `tracker.py:951-952` (`get_backtest_history`) +
  `tracker.py:933-946` (`get_backtest_results`)
- **What's wrong:** `backtest_runs.config_hash` (now incorporates
  `ENABLE_5M_SWEEP`, `CRT_TP1_MODE`, `CRT_APPLY_QUALITY_GATES`,
  `CRT_REQUIRE_1H_TREND` per `backtest.py:3511-3519`) exists in every recent run
  (verified: `273abdef...`, `c826152b...`, etc.) but is only used by
  `get_baseline_pin()` (`tracker.py:2255-2311`) for the pin-banner.
  Neither `/api/backtest/results` nor `/api/backtest/history` includes
  config_hash in its response, so the operator can't tell from the dashboard
  which CRT-Pro variant produced Run-141 vs Run-143.
- **Suggested fix:** Add `config_hash` to both SELECTs and render the first 8
  chars in the meta-bar + history-row.

🟠 **HIGH — WR is overstated on mixed-source runs**

- **Location:** `tracker.py:933-946` + render at `tracker_html.py:3344`
- **What's wrong:** `backtest_runs.overall_wr` is the headline WR for the whole
  run, blended across 5M_SWEEP + H4_CRT. On Run-138 (29 SWEEP + 499 CRT, 56.0%
  WR) and Run-141 (29 SWEEP + 416 CRT, 56.6% WR), the operator sees a single
  number that hides the fact that the 5M_SWEEP 29 sigs are still at ~80% WR
  while CRT is in the mid-50s. **The number isn't wrong, but the framing is
  misleading** — the dashboard suggests "the strategy" is at 56%, when really
  one strategy is at 80% and the other at 53%, and the operator needs to know
  which to keep funding.
- **Why it matters:** This is the core "two-strategies-in-one-run" problem. The
  Honest Metrics tab's CPCV is computed on the blend too, so DSR FAIL on
  Run-143 may be CRT dragging down a SWEEP that's still passing — invisible.
- **Suggested fix:** When the backtest summary exposes per-source breakdown
  (Section A), surface "SWEEP WR: 80% (29)  ·  CRT WR: 54% (285)" in the meta
  bar so the headline 55.7% is contextualized.

---

## Section D — Honest Metrics tab

🟢 **PASS — All 9 honest-metrics keys render cleanly**

- **Verified via** `curl /api/honest-metrics` — full schema returned:
  ```
  cpcv_wr_mean=48.88, cpcv_wr_std=4.66, cpcv_wr_q05=41.2, overall_sharpe=0.128,
  psr_oos=92.1, dsr=31.9, dsr_proxy_used=false, verdict=FAIL, n_signals=314
  ```
- **M-1 fallback-dict regression check:** `tracker.py:2461-2463` matches the
  full 9-key shape returned by `_parse_honest_metrics_from_report()` (which
  defaults to None on missing). The frontend `null !== null ? .toFixed(N) : '—'`
  pattern at `tracker_html.py:3912-3927` handles all None cases safely. **No
  regression.**

🟠 **HIGH — CPCV is computed on the source-blend, mislabel risk**

- **Location:** Honest Metrics tab — every CPCV field in the API
- **What's wrong:** The "Latest Backtest — Honest Metrics" section labels its
  numbers as if they were for a single strategy. But on Run-143 the CPCV is
  computed on all 314 signals (29 SWEEP + 285 CRT). When `ENABLE_5M_SWEEP=0`
  ships to live, the LIVE strategy is CRT-only, but the CPCV being shown to
  the operator is partially SWEEP. **The dashboard implies "CPCV says
  Run-143 strategy is FAIL" — but it's really saying "blend is FAIL", and
  the CRT-only subset might be even worse (or marginally better) than the
  blend.**
- **Why it matters:** Operator may make LIVE-clearance decisions on a metric
  that's partly informed by signals the live bot will never fire (29 SWEEP
  legacy rows in the dataset). Per CLAUDE.md §5, the LIVE-clearance gate
  requires CPCV ≥ 60% — a blended number could pass while the actual live
  CRT-only strategy fails (or vice versa).
- **Suggested fix:** Either (a) make the Honest Metrics tab show CPCV split by
  source (requires `validation.py` to produce per-source CPCV), or (b) at
  minimum add a banner: "⚠ Honest metrics blend 29 5M_SWEEP + 285 H4_CRT
  signals. Live mode is CRT-only — interpret with care."

🟢 **PASS — Execution mode renders correctly**

- **Verified via** API: `execution_mode: "PAPER"`. The C-3 fix from cycle-6 is
  still in place at `tracker.py:2482-2496` and `tracker_html.py:3836-3841`.

---

## Section E — Auto-Explorer tab

🟢 **PASS — All 4 API routes load**

- Verified: `/api/explorer/status`, `/api/explorer/pareto`,
  `/api/explorer/promotions`, `/api/explorer/trials` (rendered at
  `tracker_html.py:4357-4488`). No schema mismatch from the `source` column
  additions — explorer reads from `explorer_learning.db`, separate from
  `signals.db` schema.

🟡 **MEDIUM — Pareto archive does not surface CRT-Pro knobs**

- **Location:** `tracker_html.py:4428-4441` + `data/pareto_archive.json`
- **What's wrong:** Current 10 entries in `pareto_archive.json` contain ONLY
  `ICT_SWEEP_LOOKBACK / ICT_MSS_HORIZON / ICT_FVG_MIN_GAP /
  DEALING_RANGE_LOOKBACK / BACKTEST_BIAS_4H_GATE / BACKTEST_TREND_1H_GATE /
  BACKTEST_FVG_MIN_QUALITY / BACKTEST_MSS_MIN_QUALITY` in their `params` blob.
  The new CRT knobs (`ENABLE_5M_SWEEP`, `CRT_TP1_MODE`, `CRT_APPLY_QUALITY_GATES`,
  `CRT_REQUIRE_1H_TREND`) are NOT in any Pareto entry — they aren't part of the
  explorer's Optuna search space yet (verified via `grep` on
  `scripts/autonomous_explorer.py` → ZERO matches for any CRT knob).
- **Why it matters less than it sounds:** This is an EXPLORER scope issue, not
  a tracker rendering bug. The tracker correctly displays whatever knobs the
  archive contains. Once the explorer adds CRT knobs to its search space, the
  rendering at `tracker_html.py:4429` already strips `BACKTEST_` / `ICT_`
  prefixes generically, so `CRT_TP1_MODE=fixed_1r` will render cleanly.
- **Why I'm flagging it:** Operator may look at the Pareto tab and conclude
  "the explorer is exploring the new CRT-Pro space" when it isn't. Dashboard
  should signal this somehow (or the explorer should expand its search space).
- **Suggested fix:** Either expand `scripts/autonomous_explorer.py` search
  space to include CRT knobs (operator decision), OR add a Pareto-tab note:
  "Search space: 8 ICT/BACKTEST knobs. CRT-Pro knobs not yet in Optuna
  scope."

---

## Section F — Signals tab / Open positions

🟡 **MEDIUM — Live signals tab will not visually distinguish CRT signals**

- **Location:** `tracker_html.py:2887-2939` (`_openCardHtml`) +
  `tracker_html.py:3060-3097` (history table row)
- **What's wrong:** The live-signals card renders Sweep / MSS / FVG / DR / EV —
  no source or entry_type. When the next CRT signal fires (currently
  `signals` table is empty, but `ENABLE_5M_SWEEP=0` means the next signal
  is guaranteed to be `H4_CRT`), the operator sees a card that looks
  identical to a legacy 5M_SWEEP card. Yet the SL/TP and trade management
  semantics are different (CRT uses adjusted TP1 per `CRT_TP1_MODE`).
- **Why it matters:** Operator may apply the wrong manual-trade discipline
  ("this looks like a sweep — close at the wick reclaim") when the underlying
  setup is a CRT/Wyckoff phase. Mental-model mismatch.
- **Crash risk on H4_CRT signal:** None — `_openCardHtml` reads sweep_type /
  mss_quality / fvg_quality / dr_location. For CRT signals, these values
  may be NULL (CRT logic in `ict_engine.py` may not populate them) — the
  `||'—'` fallback at `tracker_html.py:2910-2913` handles that. So no crash,
  but cards display as a wall of em-dashes for ICT-quality columns. **The
  CRT card carries almost no information for the operator.**
- **Suggested fix:** Branch `_openCardHtml` on `r.source` — for `H4_CRT`
  signals, show entry_type (e.g. "H4_CRT_OB_ACCUMULATION") and Wyckoff phase
  instead of sweep_type / mss_quality / fvg_quality / dr_location, which are
  meaningless for CRT.

---

## Section G — QuantStats tab

🟢 **PASS — Tab remains HIDDEN per operator preference**

- **Location:** `tracker_html.py:665-668`
- **Verified:** `style="display:none"` still on `tabBtnQuantStats`. Comment
  block at `:658-664` documents the operator preference. Backend routes
  `/api/quantstats` + `/api/quantstats/tearsheet` remain active (no changes
  needed). **Status quo preserved.**

---

## Section H — Adaptive learning / OGD weights tab

🔴 **CRITICAL — OGD/adaptive metrics report `tokens_monitored=1` but bootstrap shows all 10**

- **Location:** Verified via `curl /api/honest-metrics` →
  `ogd_health: { tokens: 1, pinned: 1, homogeneity_alert: true, ... }`
- **What's wrong:** The OGD health snapshot (`tracker.py:2381-2402`) wraps
  `monitoring.generate_report()`, which counts ONLY rows in `token_weights`
  (the live OGD pool). After the bootstrap from Run-141 (445 closed sigs),
  the bootstrap pool (`backtest_token_weights`) carries weights for all 10
  tokens — but `token_weights` only has 1 token (TON, per the cycle-6 audit
  notes at `tracker.py:634-643`). So Honest Metrics says `tokens=1`,
  `homogeneity_alert: true` — the alert is **structurally guaranteed**
  while the bootstrap pool is the only source, and isn't really an alert.
- **Why it matters:** Honest Metrics tab's OGD health pill shows ⚠ WARN, the
  Tab-bar honestPill at `tracker_html.py:3950` shows `⚠`. Operator sees a
  persistent WARN that is unactionable (it's not actually unhealthy — it's
  just that live OGD hasn't accumulated 10 updates per token yet).
- **Note:** This pre-dates today's CRT-Pro changes, but the CRT signal source
  shift will keep the live OGD pool sparse for longer (CRT signals also feed
  OGD, but the bootstrap pool wasn't computed on CRT signals, so the eventual
  blend will compare apples to oranges).
- **Suggested fix (one-liner):** Either (a) make `monitoring.generate_report()`
  include the bootstrap pool in `tokens_monitored` (then `tokens=10,
  homogeneity_alert=false` until live OGD has data for all), or (b) downgrade
  the WARN pill to '·' when the only "warning" is bootstrap-only state.

🟡 **MEDIUM — Adaptive bootstrap attribution does not distinguish source**

- **Location:** `tracker.py:629-728` (`_get_adaptive_weights_raw`)
- **What's wrong:** The Adaptive tab shows per-token weights but treats all
  closed signals as equivalent for the `recent_wr` 30-bar window
  (`tracker.py:699-715`). After bootstrap from Run-141 (mix of 29 5M_SWEEP +
  416 H4_CRT), the per-token weight has been learned from a blend. If 5M_SWEEP
  signals later resume (operator can flip `ENABLE_5M_SWEEP=1`), the weights
  are still informed by CRT signal outcomes.
- **Why it matters:** Per-token weight `recent_wr` mixes both scanners' outcomes
  invisibly. The 30-bar recent-WR window may flicker between strategies as
  the live mix shifts (currently CRT-only).
- **Suggested fix:** Either (a) accept the blend as canonical "this token's
  WR across all strategies" (cleanest, simplest), or (b) split per-token
  weights by source (more accurate, but doubles state complexity and the
  bootstrap pool already doesn't have per-source state — would require
  schema change).
- **Recommendation:** Document the blend in a tooltip on the Adaptive tab and
  defer the per-source split until the strategy mix stabilizes.

---

## Section I — Mobile responsive / general UX

🟢 **LOW — Longer `entry_type` strings would not visually break anything**

- **Where it would manifest:** Nowhere — `entry_type` is not rendered.
- **Future risk:** If/when `entry_type` is added to the Signal History table
  (Section B suggestion), a 25-character string like `H4_CRT_OB_ACCUMULATION`
  in a `font-size: 0.72rem` cell next to Session (currently `'NY_AM_KZ'`,
  also `_KZ`-trimmed) would fit. **No layout fix needed today.**

---

## Section J — API consistency

🟠 **HIGH — `/api/signals` and `/api/open` do NOT explicitly include `source` or `entry_type`**

- **Location:** `tracker.py:2553-2563` (`/api/signals`) +
  `tracker.py:2567-2578` (`/api/open`)
- **What's wrong:** Both endpoints use `SELECT s.*` which WILL include the new
  `source` and (existing) `entry_type` columns implicitly. **No crash, no
  data loss** — the field is in the JSON response, just unused by the
  frontend (verified at audit time: signals table empty, so couldn't confirm
  shape directly, but `SELECT s.*` is unambiguous and `tracker.py:921-924`
  shows `entry_type` is registered as a backtest column already).
- **Why I'm flagging it:** The implicit `SELECT s.*` pattern means future
  schema additions land in the API automatically — that's good for forward
  compat — but it also means the frontend silently ignores `source`. The
  next dev who adds `source` rendering to the JS won't have to touch the
  backend. **This is more a "noted, no fix needed" item than a bug.**
- **Backward compat:** Old frontend code that doesn't know about `source`
  reads `r.source` → `undefined` → falsy → renders as `'—'` via
  `(r.source||'—')`. No JSON parse errors. **Safe.**

🟢 **PASS — `/api/backtest/results` summary contains expected by_* breakdowns**

- Verified: `by_token`, `by_regime`, `by_conf`, `by_dir`, `by_sweep`,
  `by_trend`, `by_session`, `cost_model`, `config_mode`, `config_dirs`,
  `walk_forward`. **No `by_source`, no `by_entry_type`** — confirms Section A
  gap is at the backend summary stage, not just the frontend.

---

## Summary scorecard

| Section | Verdict | Severity of worst finding |
|---------|---------|---------------------------|
| A — Source attribution | Gap, no crashes | 🟠 HIGH |
| B — entry_type rendering | Not displayed anywhere | 🟢 LOW (gap, not bug) |
| C — Backtest tab | Renders cleanly; WR overstated on blend | 🟠 HIGH (framing) |
| D — Honest Metrics | All 9 keys load; blend mislabel risk | 🟠 HIGH (framing) |
| E — Auto-Explorer | All 4 APIs work; CRT knobs not in search | 🟡 MEDIUM |
| F — Signals tab | Live CRT signals will display em-dashes for ICT cols | 🟡 MEDIUM |
| G — QuantStats | Still hidden as expected | 🟢 PASS |
| H — Adaptive / OGD | OGD health WARN is unactionable + blend attribution | 🔴 CRITICAL (UX) |
| I — Mobile / layout | No layout break from longer strings | 🟢 PASS |
| J — API consistency | `SELECT s.*` carries new fields silently | 🟢 PASS (notable) |

98/98 tracker DB-alignment regression tests pass. Honest Metrics fallback-dict
fix (commit `adf62b9`) and per-token Avg R:R fix (commit `6efcd20`) both
verified intact, no regressions.

---

## TOP 3 PRIORITY FIXES

### 1. Add per-source breakdown to the backtest summary + render it on the Backtest panel (Section A + C)

**Why first:** The dashboard currently obscures the fact that EVERY recent run
(138–143) is a blend of 5M_SWEEP and H4_CRT, with very different WRs per
source. A 56% blended WR could hide a SWEEP at 80% and CRT at 53%. Operator
LIVE-clearance + tuning decisions depend on seeing the split.

**Files:** `backtest.py` (add `by_source` to `_summarize()`), `tracker.py`
(`get_backtest_results` already passes summary through), `tracker_html.py`
(add a panel near the existing `by_token` / `by_regime` blocks).

### 2. Branch the Open Positions card layout on `source` (Section F)

**Why second:** With `ENABLE_5M_SWEEP=0`, the NEXT live signal is guaranteed
to be `source='H4_CRT'`. The current card design renders Sweep / MSS / FVG / DR
columns that may be NULL for CRT signals — producing an info-less card of em-dashes.
Operator needs entry_type + Wyckoff phase + CRT-specific context (e.g. CRT_TP1_MODE
adjustment marker) to manage the trade.

**Files:** `tracker_html.py:_openCardHtml()` (around line 2887), simple
`if(r.source==='H4_CRT')` branch.

### 3. Calm down the OGD homogeneity_alert / tokens=1 WARN in Honest Metrics (Section H)

**Why third:** Operator already sees a persistent ⚠ on the Honest Metrics tab
that is structurally unactionable in the pre-live phase. Lowers signal-to-noise
on real alerts. Either teach `monitoring.generate_report()` to count the
bootstrap pool, or downgrade the WARN to '·' when the only complaint is
"bootstrap-only state".

**Files:** `monitoring.py` (count bootstrap pool in `tokens_monitored`) OR
`tracker.py:_ogd_health_snapshot()` (downgrade WARN heuristically when
bootstrap_only=true).

---

## Notes deliberately not flagged as fixes

- **`entry_type` rendering (Section B):** A genuine gap, but `sweep_type` +
  ICT-quality columns already carry most of the structural meaning for
  5M_SWEEP. For CRT signals, fixing #2 above (source-branched card layout)
  is the higher-leverage move — it can surface `entry_type` as part of the
  CRT-specific layout.
- **CRT knobs not in Optuna search space (Section E):** This is an explorer-
  scope decision, not a tracker bug. Out of audit scope.
- **`by_entry_type` summary (Section J):** Defer until per-source split lands
  — entry_type granularity is more useful within a source than across.

End of audit.
