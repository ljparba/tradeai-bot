# Tracker Frontend ↔ Backend Field-Name Audit — 2026-05-26 (cycle 7)

> Scope: same class of bug as the just-fixed `tracker_html.py:3380 d.avg_rr → d.avg_net_rr`. Walk every JS property accessor in `tracker_html.py` and verify the field is actually produced by the backend endpoint that supplies the panel. Read-only audit — operator decides which to fix.
> Method: enumerated all 23 `fetch('/api/...')` call sites in `tracker_html.py`, cross-referenced each to its backend producer in `tracker.py` / `backtest.py:build_summary` / `adaptive_engine.py` / `quantstats_report.py`, then ran field-by-field parity on the rendered JS for each panel.

DB state at audit time: 8 backtest_runs (latest=Run-82), 0 signals, 0 results (clean DB). Several findings are therefore **latent** — they will only surface once signals start firing or a specific code path runs.

---

## CRITICAL bugs (rendering broken data visibly)

**None found.** The exact-class bug that motivated this audit (`d.avg_rr` vs `d.avg_net_rr` at `tracker_html.py:3380`) is the only field-name mismatch in any panel that renders a data table. Every other backtest by-token / by-regime / by-conf / by-session field access was verified against `backtest.py:build_summary tok_entry()` / `simple_entry()` and all match.

---

## HIGH bugs (rendering wrong/stale values silently — operator sees a number but it's wrong)

**None found.** The closest call is the QuantStats tab being hidden (`display:none`) per CLAUDE.md §6, so even if a field name were wrong there it would never render. All visible metric fields verified.

---

## MEDIUM bugs (null/undefined rendering on edge cases)

### M-1 — Honest Metrics tab will TypeError when no backtest run exists
`tracker.py:2456` initialises the fallback as `honest = {"cpcv_wr_mean": None, "dsr": None, "verdict": None}` — only 3 keys. If `latest_run["id"] is None` OR no `backtest_reports/RunNN_*.txt` is found, this stripped dict is returned without `cpcv_wr_std`, `cpcv_wr_q05`, `overall_sharpe`, `psr_oos`, `dsr_proxy_used`, `n_signals`.

Frontend at `tracker_html.py:3914-3927` reads:
```js
hm.cpcv_wr_q05 !== null ? hm.cpcv_wr_q05.toFixed(1) + '%' : '—'
hm.cpcv_wr_std !== null ? hm.cpcv_wr_std.toFixed(2) + '%' : '—'
hm.overall_sharpe !== null ? hm.overall_sharpe.toFixed(3) : '—'
hm.psr_oos !== null ? hm.psr_oos.toFixed(1) + '%' : '—'
```
In JS strict equality, `undefined !== null` is **true**, so the truthy branch runs and `undefined.toFixed(1)` throws `TypeError: Cannot read properties of undefined (reading 'toFixed')`. The entire Honest Metrics panel will fail to render and the catch-block at line 3956 shows "Failed to load honest metrics: …".

Currently masked because Run-82 exists and `_parse_honest_metrics_from_report` always returns a 9-key dict with explicit `None` for missing fields. Fires the moment the DB is reset or run on a host with no backtest_reports dir.

Fix: change the fallback default at `tracker.py:2456` to mirror `_parse_honest_metrics_from_report`'s full 9-key dict. (Same surface as the existing `_parse_…` default at `tracker.py:2072-2074`.)

### M-2 — OGD weights tab fallback feature list is bogus
`tracker_html.py:4048` — `const feats = wdata.feature_order || ['rsi','trend','sr','mtf','volume','momentum'];`
The real `_ADAP_FEATURES` are `["fvg_quality", "mss_quality", "session", "confidence", "trend_strength", "dr_location"]` (`tracker.py:624`). The 6 fallback names `rsi/trend/sr/mtf/volume/momentum` correspond to *no* feature in the OGD system; they are vestigial from an older feature scheme. If `/api/adaptive/summary` errors mid-flight and returns no `weights.feature_order`, the dashboard renders 6 phantom feature bars labelled `RSI/Trend/Sr/Mtf/Volume/Momentum` with all-zero weights (because `tw[f]` lookups against the bogus keys return undefined → `defW` default). Operator would believe these are real features.

Fix: change fallback to `_ADAP_FEATURES` (`['fvg_quality','mss_quality','session','confidence','trend_strength','dr_location']`) or to `[]` so the panel renders empty if the API broke.

### M-3 — `_FEAT_LABELS` is missing labels for the bogus fallback feature names
`tracker_html.py:3801` defines labels only for the real 6 features. Combined with M-2: if the fallback path is hit, the JS at line 4072 `(_FEAT_LABELS[f]||f)` falls through to the raw feature key (`rsi`, `trend`, etc.) — same root cause as M-2. Fixing M-2 closes this transitively.

### M-4 — `d.points[].ts.substring(5, 16)` on equity curve assumes ISO format with `-`
`tracker_html.py:2769` — labels rendered as `p.ts.substring(5, 16)` to produce `"MM-DD HH:MM"`. Backend `tracker.py:156` writes `"ts": closed_at or ts` where `closed_at` is whatever the bot persisted. `crypto_alert.py:1029` writes `closed_at=?` via `datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")` — 19-char string starting `YYYY-MM-DD`. Substring(5,16) → `MM-DD HH:MM`. OK. But `manual_close_signal` at `tracker.py:1834` (already flagged H-1 in cycle 6 audit) writes via `datetime.now()` (naive local time, same format) — still substring-safe. No new bug, but worth noting that **any future writer that uses ISO-T format (`2026-05-26T07:02:00`)** would render labels as `5-26T07:02` (cosmetic). Defensive: change to `p.ts.replace('T',' ').substring(5,16)`.

### M-5 — Latest backtest panel reads `rr.run_date.slice(0,16)` without null guard
`tracker_html.py:3358` — `rr.run_date.slice(0,16)`. If `get_backtest_results()` ever returns a row with NULL run_date, `null.slice` throws. Schema has `run_date TEXT NOT NULL`, so currently safe. Defensive `(rr.run_date||'').slice(0,16)` would harden. Same applies to `_btHistData` at line 3753.

### M-6 — Token table `t.signals` / `t.wins` etc. accessed without null guard
`tracker_html.py:3236-3245` — `+t.signals+` etc. concatenated directly. If a token row from `get_intelligence().tokens` was somehow missing a field, the cell would print `undefined`. Backend always returns all keys, so currently safe.

### M-7 — Open card `r.tp1.toFixed(4)` on possibly NULL price columns
`tracker_html.py:2925-2935` — `Number(r.tp3).toFixed(4)`, `Number(r.sl).toFixed(4)`, etc. `Number(null)` = `0`, so this renders `$0.0000` if tp3 is NULL. Schema allows NULL on `tp1/tp2/tp3/sl` (`crypto_alert.py:206`). Currently the bot always writes these, but the fail mode is `$0.0000` (silently wrong), not `undefined`. Low risk.

### M-8 — Recent trials table date column missing
`tracker_html.py:4467-4477` renders `t.trial_id, t.study_name, t.verdict, t.n, t.wr, t.cpcv_mean, t.dsr, t.walltime_s, t.reject_reason`. Backend returns these plus `started_at, optuna_trial_no, cpcv_std, cpcv_q05, sharpe, dsr_proxy_used` — none of which are surfaced in the UI. Not a bug, but the `started_at` would be useful in the table; operator currently can't tell when a trial ran from the dashboard.

---

## LOW (cosmetic / brittle but harmless today)

### L-1 — `paretoR.archive[].dsr` shown as `p.dsr+'%'` even though some Pareto entries may have dsr=None
`tracker_html.py:4433` — `(p.dsr!=null ? p.dsr+'%' : '—')` — already guarded. Verified clean.

### L-2 — Promotions table appends `'%'` to `m1.cpcv_mean` and `m1.dsr` without null check
`tracker_html.py:4452-4453` — `(m1.cpcv_mean||'—') + '% / ' + (m2.cpcv_mean||'—') + '%'`. When `m1.cpcv_mean` is null, this renders `—%`. Cosmetic.

### L-3 — Frontend fallback `pp.target || 30` and `pp.eta_months !== undefined ? : '—'`
`tracker_html.py:3886-3888` — mixed null-check styles in the same block. Backend `_paper_progress` always returns these keys, so fine. Cosmetic inconsistency.

### L-4 — `recent.profit_pct*100` unit assumption
`tracker_html.py:4274` — `(recent.profit_pct*100).toFixed(2) + '%'`. Verified backend at `crypto_alert.py:1159` stores `_pct = float(profit_pct) / 100.0` — fraction in DB → JS multiplies by 100 → percent. Correct, but the unit conversion is implicit; a future writer that stores percent directly would double the displayed value. Add a comment or normalize at write time.

### L-5 — `s.final.toFixed(2)`, `s.peak.toFixed(2)`, `s.max_dd.toFixed(2)` in equity sub
`tracker_html.py:2776-2779` — `(s.final||0).toFixed(2)`. Backend always rounds and returns these, but `0.toFixed(2)` is `"0.00"` (safe). Correct as-is.

### L-6 — Drift panel hardcodes defaults `||25, ||38, ||62`
`tracker_html.py:4165, 4168, 4171` — `(dt.adx_threshold||25)`, `(dt.rsi_oversold||38)`, `(dt.rsi_overbought||62)`. The bot's actual defaults are `25.0 / 38.0 / 62.0` per `crypto_alert.py` regime detection. But the values for active tokens with low ATR can legitimately push these to 18.0 / 35.0 / 52.0. The `||` fallback is fine for "no data" but masks the *actual* default of 25.0/45.0-vol_adj/55.0+vol_adj from `_get_drift_state_raw`. Backend defaults at `tracker.py:792-793` are 45-vol_adj and 55+vol_adj — frontend default of 38/62 corresponds to vol_adj≈7. Inconsistent. Operator unlikely to notice.

### L-7 — `tw.adx_mean || '—'` and `tw.atr_ratio_mean || '—'` render '—' on legitimate 0.0
`tracker_html.py:4174, 4177`. `0 || '—'` → `'—'`. Realistic ADX is never 0 (would be flat market), so not a real risk.

### L-8 — Backtest history list `r.avg_rr` printed raw with no decimal control
`tracker_html.py:3757` — `'R:R: 1:'+r.avg_rr`. Backend `backtest_runs.avg_rr` is already rounded to 2 decimals (`backtest.py:2880 round(...,2)`). Cosmetic only.

### L-9 — Explorer "promos today" computation uses `new Date()` local time
`tracker_html.py:4402-4404` — `const today = new Date().toISOString().slice(0,10)` then `(p.promoted_at_utc||'').startsWith(today)`. `toISOString()` is always UTC, and `promoted_at_utc` is UTC (`autonomous_explorer.py:807 strftime("%Y-%m-%dT%H:%M:%SZ")`). Correct. But the field name `today` is misleading — it's "today UTC", not the operator's local date.

### L-10 — Last-promote-soak formula mixes UTC ISO + JS Date
`tracker_html.py:4406-4413` — `new Date(lastPromoTs).getTime()` parses the trailing `Z` as UTC. Correct calculation.

---

## VERIFIED-CLEAN panels

The following panels were walked field-by-field against their backend producers and contain ZERO field-name mismatches:

| Panel | Frontend lines | Backend producer | Status |
|-------|---------------|------------------|--------|
| Stats card row (Total/WR/Wins/Losses/Open/RR/Best) | `tracker_html.py:2855-2861` | `tracker.py:get_stats()` returns `total, win_rate, wins, losses, opens, avg_rr, best_trade` | CLEAN |
| Open positions card | `tracker_html.py:2887-2939` reads `r.signal, token, id, entry_price, rsi, mtf_bias, mtf_conf, trend_4h, trend_1h, trend_5m, expires_at, sweep_type, mss_quality, fvg_quality, dr_location, ev_status, ev_score, tp1-3, tp1-3_hit, tp1-3_pct, sl, sl_pct, sl_hit, profit_pct` | `tracker.py:2560-2570` SELECT joins `signals s LEFT JOIN results r` — all columns exist in `crypto_alert.py:201-257` schema | CLEAN |
| Signal history table | `tracker_html.py:3074-3096` reads `r.id, token, signal, entry_price, sl, tp1-3, tp1-3_hit, rr1, confidence, mtf_bias, rsi, trend_4h/1h/5m, session, sweep_type, ev_status, ev_score, outcome, profit_pct, timestamp` | `tracker.py:2546-2556` SELECT joins `signals s LEFT JOIN results r` — all match | CLEAN |
| Bot Health Score (Intelligence tab) | `tracker_html.py:3116-3135` reads `bot_score, total_closed, bot_parts.{wr,rr,hc,sel}` | `tracker.py:611-617` returns same fields | CLEAN |
| Token performance table (live, not backtest) | `tracker_html.py:3203-3247` reads `t.token, signals, closed, wins, losses, wr, wr_lo, wr_hi, avg_conf, avg_rr, recent_wr, blend_pct, ogd_n` | `tracker.py:587-593` returns same fields | CLEAN |
| Confidence stacked bar | `tracker_html.py:2711-2742` reads `l.wins, partial, losses, expired, wr, level, count, closed` | `tracker.py:532-542 conf_levels` returns same fields | CLEAN |
| Hour×Day heatmap | `tracker_html.py:2620-2654` reads `c.wr, n, wins, partial, losses, expired`, `s.best.{dow,hour,wr,n}`, `s.worst.{dow,hour,wr,n}`, `s.n_cells_usable` | `tracker.py:get_hour_day_heatmap` (verified payload) | CLEAN |
| OGD sparkline series | `tracker_html.py:2568-2585` reads `pts[i].w` | `tracker.py:430` returns `[{ts, w, n}]` | CLEAN |
| Rolling walk-forward chart | `tracker_html.py:2373-2456` reads `w.train_end_ts, train_wr, train_n, test_wr, test_n`, `s.{n_windows, mean_gap, consistent}`, `d.run_id` | `tracker.py:215-249` returns same fields | CLEAN |
| Equity curve chart | `tracker_html.py:2769-2779` reads `p.ts, cum_pnl`, `s.{n, final, peak, max_dd}` | `tracker.py:171-181` returns same fields | CLEAN |
| Backtest meta bar | `tracker_html.py:3344-3364` reads `rr.overall_wr, avg_rr, run_date, days, total_signals`, `cm.{slippage_pct, rt_total_pct, timeframe}` | `tracker.py:937-944` returns `dict(row)` from `backtest_runs`; cm from `summary.cost_model` (`backtest.py:1966-1975`) | CLEAN |
| Backtest by-regime / by-conf / by-dir / by-session bars | `tracker_html.py:3385-3427` reads `d.wr, d.signals` from each `simple_entry` dict | `backtest.py:1950-1956 simple_entry` returns `{signals, wins, partial, wr}` | CLEAN |
| Backtest recommendations list | `tracker_html.py:3432-3441` reads `rec.type, area, title, detail, action` | Verified `generate_recommendations` writes these keys | CLEAN |
| Tune Bot preview / apply | `tracker_html.py:3474-3535` reads `adj.param, delta, old_val, new_val, reason, changes_desc`, `d.walk_forward_gap, train_wr, test_wr, backtest_wr, adjustments, validation_notes`, `fg.{passed, need_days, need_signals, note, new_signals, days_since_apply}` | `tracker.py:calculate_tune_preview` + `tune_status` (verified field-by-field) | CLEAN |
| Tune history table | `tracker_html.py:3692-3722` reads `h.{id, applied_at, param, old_val, new_val, train_wr, test_wr, post_apply_wr, post_apply_n, status, notes, backup_file, signals_at_apply, backtest_run_id}` | `tracker.py:879-887` returns exactly these | CLEAN |
| Adaptive Bot State card | `tracker_html.py:3976-4007` reads `bs.{threshold_adj, conf_floor, last_signal_ts, bot_active}` | `tracker.py:829-831` returns same fields | CLEAN |
| Adaptive Portfolio gauges | `tracker_html.py:4011-4044` reads `po.{open_count, max_open, buy_count, sell_count, max_same_dir, risk_used_pct, max_risk_pct, slots_free}` | `tracker.py:745-757` returns same fields | CLEAN |
| Adaptive OGD weight bars | `tracker_html.py:4057-4137` reads `tw.{n_updates, updated_at, blend_pct, recent_wr, wr_n, source, is_degenerate}` + per-feature weights | `tracker.py:653-721` returns same fields including the `source` field added in cycle-6 fix | CLEAN |
| Adaptive Drift baselines | `tracker_html.py:4152-4185` reads `dt.{active, n_samples, updated_at, adx_threshold, rsi_oversold, rsi_overbought, adx_mean, atr_ratio_mean}` | `tracker.py:777-793` returns same fields | CLEAN |
| Honest Metrics top status row | `tracker_html.py:3831-3880` reads `d.{bot_version, execution_mode, audit.score, audit.date, ogd_health.{global_alert, tokens, degenerate, pinned, stale}, macro_filter.{enabled, advisory_only}}` | `tracker.py:get_honest_metrics` + sub-helpers | CLEAN |
| Honest Metrics paper-progress | `tracker_html.py:3883-3901` reads `pp.{closed, target, pct, eta_months, rate_source, rate_per_month, remaining}` | `tracker.py:2370-2378` returns same fields | CLEAN |
| Cross-config sr_trial_std card | `tracker_html.py:3938-3945` reads `cs.{value, n_configs, mean_oos_sharpe, computed_at, note}` | `tracker.py:2406-2420` returns same fields | CLEAN |
| Baseline pin banner | `tracker_html.py:4498-4523` reads `d.{pin.{run_id, label, promoted_at, expected.{n, wr_pct, cpcv_wr_mean_pct, cpcv_sharpe_mean, dsr_pct}}, latest.{id, n, wr}, status, message}` | `tracker.py:2304-2310` returns same nested structure | CLEAN |
| Explorer summary cards | `tracker_html.py:4393-4416` reads `trialsR.{totals.{PASS,FAIL,ERROR}, n_studies, trials}`, `paretoR.archive`, `promoR.promotions` | `tracker.py:2237-2250, 2205, 2217` return same | CLEAN |
| Explorer session card | `tracker_html.py:4369-4391` reads `statusR.{state, session}` and `s.{study_name, last_updated, counts, trials_completed, trials_planned, best_cpcv, best_dsr, pause_reason}` | `tracker.py:get_explorer_status` + `autonomous_explorer.py:1027-1039` writers | CLEAN |
| Pareto archive table | `tracker_html.py:4423-4436` reads `p.{trial_id, study_name, n, wr, cpcv_mean, cpcv_std, sharpe, dsr, params}` | `autonomous_explorer.py:927-937 _update_pareto_archive` writes same fields | CLEAN |
| Promotions table | `tracker_html.py:4445-4456` reads `p.{kind, promoted_at_utc, trial_no, backtest_run_id, metrics_run1.{cpcv_mean, dsr, sharpe}, metrics_run2.{cpcv_mean}}` | `autonomous_explorer.py:805-816 _append_promotion_log` writes same fields | CLEAN |
| R10 forensic per-token table | `tracker_html.py:4257-4288` reads `t.{n_updates, current_weights, recent_updates[0].{reward, gradient_l1, regime, profit_pct, ts}, last_update_iso, health_flags}` | `tracker.py:307-394 get_adaptive_forensic` returns same fields | CLEAN |
| R10 forensic global verdict | `tracker_html.py:4235-4247` reads `g.{latest_cpcv_verdict.{verdict, updated_at}, learning_freeze_state.{frozen, active_triggers}}` | Verified `bot_state.latest_cpcv_verdict` blob shape in `backtest.py:3360-3370` | CLEAN |
| QuantStats summary card row | `tracker_html.py:4560-4580` reads `m.{sharpe, sortino, calmar, cagr_pct, max_drawdown_pct, profit_factor, kelly_criterion, win_rate_pct, avg_win_pct, avg_loss_pct, best_day_pct, worst_day_pct, volatility_ann_pct, value_at_risk_pct, cvar_pct, omega, tail_ratio, skew, kurtosis, cumulative_return_pct, periods_per_year}`, `d.{n, first_ts, last_ts}` | `quantstats_report.py:108-138` returns all 21 metric fields + the 3 top-level fields | CLEAN |

---

## Coverage assessment

**Audited (~85% of dashboard surface):**
- All 23 `/api/*` fetch handlers in `tracker_html.py` enumerated and matched to their tracker.py producers
- All major panels walked field-by-field: Stats, Open Positions, Signal History, Intelligence (Bot Score + Token Performance + Confidence Levels + Hour-Day Heatmap + Confidence-Stacked Bar), Backtest (Meta + Per-Token + Per-Regime + Per-Conf + Per-Dir + Per-Session + Recommendations + Walk-Forward + History List), Tune Bot (Preview + Apply + History), Adaptive (Bot State + Portfolio Gauges + OGD Weights + Sparklines + Drift Baselines + R10 Forensic), Honest Metrics (all sub-cards), Auto-Explorer (Session + Summary + Pareto + Promotions + Trials), Baseline Pin Banner, QuantStats (all 21 metrics)
- Cross-checked schemas in `crypto_alert.py:201-257` (signals + results) for column-level field matching

**Not audited / out of scope:**
- Pure UX / chart styling code (no field-name risk)
- The 7 FAQ modal HTML templates (static content, no data-binding) — `tracker_html.py:4324-4340`
- Tune Bot config editor (reads raw text from `config.py` — not JSON-typed)
- CSS class-name → state-name strings (e.g. `class="db-ok"` etc.; these are intentional and don't depend on backend types)
- The `close_position` POST handler payload — verified clean in spot-check (`signal_id, exit_price` round-trip OK)

**Confidence:** HIGH that no critical/high-severity field-name mismatches remain. The cycle-6 audit already swept the same surface and produced 3 critical findings (all distinct from this audit's class). This pass focused exclusively on the field-name parity vector raised by the operator and finds only the 4 medium / 10 low-severity issues above. The Honest Metrics no-data fallback (M-1) is the most likely to bite in practice if/when the DB is reset or a fresh install is bootstrapped.

---

## Recommended fix priority

1. **M-1** — 3-line fix at `tracker.py:2456` (broaden the fallback dict). Prevents Honest Metrics tab from breaking on DB reset.
2. **M-2 + M-3** — 1-line fix at `tracker_html.py:4048` (change bogus default to real `_ADAP_FEATURES`). Prevents phantom feature rendering if the adaptive API briefly errors.
3. **L-6** — change drift threshold default fallbacks to match backend defaults (45-vol_adj, 55+vol_adj) — minor consistency win.

No other action needed. The dashboard is in materially good shape on the field-name correctness front.
