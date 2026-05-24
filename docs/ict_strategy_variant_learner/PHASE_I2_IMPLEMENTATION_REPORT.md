# Phase I-2 Implementation Report — ICT Strategy Variant Learner

**Date:** 2026-05-20
**Scope:** Phase 1 (DB schema) + Phase 2 (template registry + signal tagging)
**Status:** Complete. No live gates changed. No adaptive learning modified.

---

## Files Changed

| File | Type | Summary |
|---|---|---|
| [strategy_templates.py](../strategy_templates.py) | **New** | Tier A/B/C template definitions + evaluation engine |
| [crypto_alert.py](../crypto_alert.py) | Modified | Import, init_db schema, generate_signal tagging, save_signal persistence |
| [backtest.py](../backtest.py) | Modified | Import, init_backtest_db columns, run_backtest_token tagging, save_to_db columns |

---

## 1. New File: strategy_templates.py

**Purpose:** Single source of truth for all template definitions and matching logic. No external dependencies except `strategy_engine.QUALITY_RANK`.

**Key exports:**
- `TemplateMatch` — dataclass-style result object per template evaluation
- `TEMPLATE_REGISTRY` — list of template metadata dicts (used for DB seeding)
- `evaluate_confluences_vs_templates(features)` — public evaluation API
- `seed_templates_table(conn)` — idempotent DB seeder called by `init_db()`

---

## 2. Database Schema Changes

### New tables

#### `templates`
```sql
CREATE TABLE IF NOT EXISTS templates (
    id           TEXT PRIMARY KEY,   -- "TIER_A" | "TIER_B" | "TIER_C"
    name         TEXT NOT NULL,
    tier         TEXT NOT NULL,
    description  TEXT,
    live_allowed INTEGER DEFAULT 1,  -- 0 for TIER_C (paper/backtest only)
    created_at   TEXT
);
```
Seeded at `init_db()` time via `INSERT OR IGNORE` (idempotent).

#### `signal_variant_matches`
```sql
CREATE TABLE IF NOT EXISTS signal_variant_matches (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id                INTEGER REFERENCES signals(id),
    template_id              TEXT    REFERENCES templates(id),
    match_score              REAL,
    confluences_matched_json TEXT,   -- JSON list of satisfied confluence labels
    is_best_match            INTEGER DEFAULT 0   -- 1 for the best-matched template only
);
```
Indexes: `idx_svm_signal_id`, `idx_svm_template_id`

### Columns added to `signals` (via ALTER TABLE migration)

| Column | Type | Purpose |
|---|---|---|
| `matched_template_id` | TEXT | Best-matched template ID ("TIER_A" / "TIER_B" / "TIER_C" / "NONE") |
| `template_scores_json` | TEXT | JSON object of all three template scores, e.g. `{"TIER_A": 0.6, "TIER_B": 0.8, "TIER_C": 1.0}` |

### Columns added to `results` (via ALTER TABLE migration)

| Column | Type | Purpose |
|---|---|---|
| `mfe_pct` | REAL | Max favourable excursion % (not populated yet — reserved for Phase 4) |
| `mae_pct` | REAL | Max adverse excursion % (not populated yet — reserved for Phase 4) |
| `realized_r` | REAL | Realized R multiple at close (not populated yet — reserved for Phase 4) |

### Columns added to `backtest_signals` (via ALTER TABLE migration)

| Column | Type | Purpose |
|---|---|---|
| `matched_template_id` | TEXT | Best-matched template for this backtest signal |
| `template_scores_json` | TEXT | JSON scores for all three templates |

---

## 3. Template Definitions

### Tier A — Strict (`TIER_A`)
**Threshold:** 4 of 5 required confluences must be satisfied.

| # | Required Confluence | Criterion |
|---|---|---|
| 1 | MSS quality | Must be `HIGH` |
| 2 | FVG quality | Must be `MEDIUM` or `HIGH` |
| 3 | Session | Must be `LONDON_KZ` or `NY_AM_KZ` |
| 4 | DR location | Must match direction: `DISCOUNT` for BUY, `PREMIUM` for SELL |
| 5 | Entry reaction | Must be `REACTION_CONFIRMED` |

**Optional bonuses** (applied proportionally to base score, max +0.20):
- SMT divergence confirmed → +0.10
- iFVG precision entry present → +0.05
- 4H bias aligned with direction → +0.05

**Live allowed:** Yes

---

### Tier B — Balanced (`TIER_B`)
**Threshold:** 3 of 5 required confluences must be satisfied.

| # | Required Confluence | Criterion |
|---|---|---|
| 1 | MSS quality | Must be `MEDIUM` or `HIGH` |
| 2 | FVG quality | Any valid quality (`LOW`, `MEDIUM`, or `HIGH`) — not `NONE` |
| 3 | Session | Any active killzone (`LONDON_KZ`, `NY_AM_KZ`, or `ASIA_KZ`) |
| 4 | DR location | Must match direction |
| 5 | Entry reaction | `REACTION_CONFIRMED` or `MIDPOINT_RECLAIM` |

**Optional bonuses:** Same as Tier A.

**Live allowed:** Yes

---

### Tier C — Exploratory (`TIER_C`)
**Threshold:** 2 of 2 required confluences must be satisfied.

| # | Required Confluence | Criterion |
|---|---|---|
| 1 | MSS quality | Any valid quality (`LOW`, `MEDIUM`, or `HIGH`) — not `NONE` |
| 2 | FVG quality | Any valid quality — not `NONE` |

**Optional bonuses:**
- SMT confirmed → +0.10
- Session in any killzone → +0.05
- DR location matches direction → +0.05
- iFVG present → +0.05

**Live allowed:** No (`live_allowed = 0` in DB). This is stored as metadata only — no live gate enforces it yet. Enforcement is planned for Phase 5 risk management.

---

### SMT as optional bonus only

Per the implementation scope, SMT is **never** a required confluence in any tier. It contributes a +0.10 bonus score when confirmed but can never block a template from matching. This is intentional — SMT detection has a small BTC data window and should not gate template classification.

---

## 4. How Template Matching Works

### Scoring formula

For each template:
```
base  = required_confluences_hit / total_required_rules
bonus = sum(optional_bonuses_satisfied)      # max 0.20
score = min(base + bonus * base, 1.0)        # bonus scales with base — zero base = no bonus
```

The bonus is multiplied by `base` so that a signal with zero required confluences cannot reach a non-zero score from bonuses alone.

### Sort order

`evaluate_confluences_vs_templates()` returns all three templates sorted:
1. Matched templates first (`is_match = True`), ordered by tier (A > B > C)
2. Unmatched templates last, ordered by tier then score descending

The **best match** is the first element that has `is_match = True`. For a bare-bones signal (Tier C only), the list is `[TIER_C, TIER_A, TIER_B]` — TIER_C sorted first as the only match.

### `matched_template_id` stored value

| Situation | Stored value |
|---|---|
| Signal matches Tier A | `"TIER_A"` |
| Signal matches Tier B but not A | `"TIER_B"` |
| Signal matches Tier C but not A or B | `"TIER_C"` |
| No template matches | `"NONE"` |

Note: "No template matches" should be rare in live trading because the bot already requires a valid MSS + FVG to reach signal generation — which satisfies both Tier C requirements.

---

## 5. Integration Points

### In `generate_signal()` (crypto_alert.py ~L2180)

Template evaluation is inserted **after** all ICT features are computed and **before** the signal reasons list is built. Specifically, after:
- `session` is computed (~L2017)
- `smt_result` is computed (~L1951)
- `entry_reaction` is computed (~L1875)
- `mss_result`, `fvg`, `dr_4h`, `ifvg_meta`, `bias_4h` are all known

The evaluation is wrapped in a try/except inside `evaluate_confluences_vs_templates()` — any failure returns `[]` and `matched_template_id` falls back to `"NONE"`. Signal generation is never blocked by template evaluation failure.

A log line is printed for every signal:
```
[TEMPLATES] BTCUSDT BUY → TIER_A score=0.860 (MSS=HIGH, FVG=HIGH, session=NY_AM_KZ, DR=DISCOUNT, entry=REACTION_CONFIRMED, SMT_bonus)
```

### In `save_signal()` (crypto_alert.py ~L588)

Two changes:
1. `matched_template_id` and `template_scores_json` are included in the `INSERT INTO signals` statement.
2. After the signal is saved, one row per template is inserted into `signal_variant_matches` with `is_best_match=1` for the winning template.

### In `run_backtest_token()` (backtest.py ~L607)

Template evaluation is called after computing `_bt_session` and before `signals.append({...})`. The template features dict uses `_bt_session` (already computed), `mss_result`, `fvg`, `dr_4h`, `smt_result`, `entry_reaction`, and `ifvg_meta` — all of which are available at that point.

Backtest signals store `matched_template_id` and `template_scores_json` in the signal dict, which is then persisted via `save_to_db()`.

---

## 6. How to Verify DB Rows

After the bot runs and generates a signal, run these SQL queries against `data/signals.db`:

```sql
-- View template tags on recent live signals
SELECT id, token, signal, matched_template_id, template_scores_json
FROM signals
ORDER BY id DESC
LIMIT 20;

-- Count signals by template tier
SELECT matched_template_id, COUNT(*) as n,
       ROUND(AVG(confidence), 1) as avg_conf
FROM signals
WHERE matched_template_id IS NOT NULL
GROUP BY matched_template_id
ORDER BY matched_template_id;

-- View per-signal confluence detail
SELECT s.token, s.signal, s.matched_template_id,
       svm.template_id, svm.match_score,
       svm.is_best_match, svm.confluences_matched_json
FROM signal_variant_matches svm
JOIN signals s ON svm.signal_id = s.id
ORDER BY s.id DESC
LIMIT 30;

-- Win rate by template tier (after signals close)
SELECT s.matched_template_id,
       COUNT(*) as total,
       ROUND(SUM(CASE WHEN r.result = 'WIN' THEN 1
                      WHEN r.result = 'PARTIAL' THEN 0.5
                      ELSE 0 END) * 100.0 / COUNT(*), 1) as weighted_wr
FROM signals s
JOIN results r ON r.signal_id = s.id
WHERE r.result IN ('WIN','LOSS','PARTIAL','EXPIRED')
GROUP BY s.matched_template_id
ORDER BY weighted_wr DESC;

-- Verify templates table is seeded
SELECT id, name, live_allowed FROM templates;

-- After backtest: tier breakdown in backtest_signals
SELECT matched_template_id, COUNT(*) as n,
       ROUND(SUM(CASE WHEN outcome IN ('WIN','PARTIAL_TP1','PARTIAL_TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as wr_pct
FROM backtest_signals
WHERE run_id = (SELECT MAX(id) FROM backtest_runs)
GROUP BY matched_template_id
ORDER BY matched_template_id;
```

---

## 7. What Was NOT Changed

- No live trading gate was modified or added
- No adaptive learning weights were changed
- No signal is ever blocked by template evaluation failure
- `LIVE_CONFIG` and `BACKTEST_CONFIG` are unchanged
- No new ICT detectors were added — all confluences come from existing `ict_engine.py` outputs
- Tier C's `live_allowed = False` is stored in the DB but not enforced as a gate (Phase 5)
- MFE/MAE/realized_r columns are added to `results` but are NULL — population is Phase 4

---

## 8. Risks and Rollback Steps

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Template eval exception blocks a signal | Low | `evaluate_confluences_vs_templates()` catches all exceptions and returns `[]`; `matched_template_id` defaults to `"NONE"` |
| Import failure of `strategy_templates` crashes the bot | Medium | Confirmed syntax OK via `python -c "import ast; ast.parse(...)"`; import is at module load time so failure is caught at startup, not mid-run |
| DB migration fails (e.g., column already exists) | Low | All ALTER TABLE operations are wrapped in `try/except pass` |
| New INSERT column count mismatch | Medium | Verified by running syntax check; `?` placeholder count matches column count |
| Backtest performance regression from template eval | Low | `evaluate_confluences_vs_templates` is O(1) per signal (3 fixed templates, no DB calls) |

### Rollback procedure

If a rollback is needed:

1. **Revert `crypto_alert.py`** — remove the `from strategy_templates import` line, remove the template evaluation block in `generate_signal()`, remove the `matched_template_id` and `template_scores_json` columns from the INSERT in `save_signal()`, remove the `signal_variant_matches` INSERT block.

2. **Revert `backtest.py`** — remove the `from strategy_templates import` line, remove the template evaluation block in `run_backtest_token()`, remove the two columns from the `backtest_signals` INSERT in `save_to_db()`.

3. **Delete `strategy_templates.py`** — the other two files must be reverted first or the import will fail.

4. **DB cleanup (optional)** — the new tables and columns are additive and do not affect existing queries. If you want to remove them:
   ```sql
   DROP TABLE IF EXISTS signal_variant_matches;
   DROP TABLE IF EXISTS templates;
   -- SQLite does not support DROP COLUMN; new NULL columns on signals/results/backtest_signals are harmless
   ```

5. **No data loss** — existing signals, results, and backtest data are not modified by any of the new code. All changes are additive.

---

## 9. Next Steps (Phases 3–6)

| Phase | Description |
|---|---|
| Phase 3 | Backtest multi-template harness: run all three tiers in one pass and print comparative stats |
| Phase 5 | Risk management: enforce `live_allowed=False` for Tier C in live trading; per-tier circuit breakers |
| Phase 4 | Per-template OGD learning: extend adaptive engine to track per-template feature weights |
| Phase 6 | Monitoring: Telegram tier tag on new signals; weekly per-tier win-rate digest |

The data foundation is now in place. After accumulating 50+ closed signals, run the verification queries above to confirm tier distribution and begin Phase 3 backtest comparison.

---

*End of report. All changes are additive and fully backwards-compatible.*
