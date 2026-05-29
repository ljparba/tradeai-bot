# CRT Strategy Context — Shared Reference for All Agents & Skills

**Last updated:** 2026-05-28 (Run-338 baseline promoted + cycle-11 patches)
**Operator state:** PAPER mode, CRT-only (ENABLE_5M_SWEEP=0); Run-338 baseline pin (Trial #336)
**Reference for:** all `.claude/agents/*.md` and `.claude/skills/*/SKILL.md`

This file is the **shared CRT context** any agent should consult when working on TradeAI after 2026-05-27. It complements the project-wide `CLAUDE.md` (which is auto-loaded into every session) by concentrating CRT-specific architectural facts in one place.

---

## 1. Two parallel scanners

TradeAI ships with TWO independent signal sources, each gated by a kill switch:

| Scanner | Env knob | Default | Module |
|---------|----------|---------|--------|
| **5M_SWEEP** | `ENABLE_5M_SWEEP` | `1` (ON) — back-compat | `crypto_alert.py:scan_token` → `generate_signal`; `backtest.py:run_backtest_token` |
| **H4_CRT** | `ENABLE_H4_CRT` | `0` (OFF) | `crypto_alert.py:scan_h4_crt_for_token`; `backtest.py:run_backtest_token_h4_crt`; detection in `crt_engine.py:detect_h4_crt` |

Both scan the same 5M/4H candle cache. Each emits its own signal stream, tagged with `source='5M_SWEEP'` or `source='H4_CRT'` in both `signals` and `backtest_signals` tables.

**Current operator config** (in `.env`, Run-338 baseline aligned 2026-05-28):
```
ENABLE_5M_SWEEP=0       # legacy scanner DISABLED
ENABLE_H4_CRT=1         # CRT scanner ACTIVE
CRT_TP1_MODE=dynamic    # Trial #336 promoted config (was min_1r pre Run-338)
CRT_TP2_RR=1.8
CRT_TP3_RR=2.2
CRT_FORWARD_BARS=864    # 72h outcome window
CRT_REQUIRE_1H_TREND=1
H4_CRT_C2_LOOKBACK=6
LIVE_BIAS_4H_GATE=loose      # was strict pre Run-338
BACKTEST_BIAS_4H_GATE=loose
WYCKOFF_PHASE_FILTER=off
```

---

## 2. CRT detection flow (high-level)

```
H4 candle stream → detect_h4_crt():
  ├── Find C1 reference candle (within H4_CRT_C2_LOOKBACK H4 bars back; code default=10, operator's .env=6)
  ├── Detect C2 sweep (C2.low < C1.low → BUY candidate, or C2.high > C1.high → SELL)
  ├── Skip if dual-extreme sweep (chaos)
  ├── On 5M timeframe within C2 window: find MSS confirming reversal
  │     score_ict_mss(...) → mss_quality ∈ {HIGH, MEDIUM, LOW}
  │     [CRT_APPLY_QUALITY_GATES=1 would reject mss < MEDIUM — currently OFF]
  ├── Find FVG OR OB confluence overlapping the swept half of C1
  │     FVG path: score_ict_fvg() → fvg_quality
  │     OB path:  detect_ict_order_block() → binary
  │     [CRT_APPLY_QUALITY_GATES=1 would reject fvg < HIGH — currently OFF]
  └── Build setup dict: {direction, c1_high, c1_low, mss_quality, confluence{type,details},
                         tp1, sl, key=(c1_time, c1_high, c1_low)}

Caller (live/backtest):
  ├── Check key NOT in `consumed_h4_crt` (mitigation — one-shot per zone)
  ├── Lookup 4h bias (slice last 210 bars, get_ict_4h_bias)
  ├── Apply LIVE_BIAS_4H_GATE / BACKTEST_BIAS_4H_GATE (strict/loose/none)
  ├── Compute Wyckoff phase (detect_wyckoff_context) — tagged in entry_type ALWAYS
  ├── If WYCKOFF_PHASE_FILTER != "off": apply is_crt_phase_aligned
  ├── If CRT_REQUIRE_1H_TREND=1: check 1H trend alignment
  ├── SL = sweep wick ± ICT_SL_BUFFER_PCT (0.3%)
  ├── TP1 = adjust_crt_tp1(direction, entry, sl, c1_high, c1_low, mode=CRT_TP1_MODE)
  ├── TP2 = entry ± CRT_TP2_RR (1.5) × risk_dist
  ├── TP3 = entry ± CRT_TP3_RR (2.0) × risk_dist
  ├── Compute economics (compute_crt_trade_economics) — reject if fees_kill or bew>53%
  ├── Compute OGD feature scores (compute_crt_feature_scores → feature_scores_json)
  └── Emit signal with source='H4_CRT', entry_type='H4_CRT_<FVG|OB>_<phase>'
```

---

## 3. Critical files (file:function references)

| Concern | File | Function |
|---------|------|----------|
| CRT detection | `crt_engine.py` | `detect_h4_crt`, `_check_confluence`, `detect_wyckoff_context`, `is_crt_phase_aligned` |
| TP1 mode helper | `crt_engine.py` | `adjust_crt_tp1` |
| OGD feature bridge | `crt_engine.py` | `compute_crt_feature_scores` |
| Trade economics | `crt_engine.py` | `compute_crt_trade_economics`, `crt_trade_rejection_reason`, `crt_quality_to_confidence` |
| Live scanner | `crypto_alert.py:766+` | `scan_h4_crt_for_token` |
| Live scan loop gate | `crypto_alert.py:3624+` | `if ENABLE_5M_SWEEP: ... if ENABLE_H4_CRT: scan_h4_crt_for_token(...)` |
| Backtest CRT scanner | `backtest.py:1295+` | `run_backtest_token_h4_crt` |
| Backtest main loop gate | `backtest.py:3666+` | Same dual-guard pattern |
| Config knob | `config.py:128` | `ENABLE_5M_SWEEP` |
| Per-source aggregation | `backtest.py:_summarize` | `by_source` block |
| OGD update on close | `crypto_alert.py:1383+` | `_trigger_weight_update` — reads `feature_scores_json` |
| OGD bootstrap admit | `adaptive_engine.py:936-955` | Loosened WHERE clause (fvg OR mss) |

---

## 4. Locked anti-patterns (DO NOT re-test or set)

**CRT-side empirically rejected on 2026-05-27:**
- `WYCKOFF_PHASE_FILTER=strict` → −5.22pp WR vs `off` (Run #140 Test B). Strict mode reduces signal count by half AND drops WR. Article's gold/forex calibration does not translate to crypto.
- `CRT_APPLY_QUALITY_GATES=1` → −21% total R/year vs `0` (Run #142). Quality gates designed for 5M_SWEEP's FVG-required pipeline don't fit CRT's OB-confluence-heavy signal mix.

Both are enforced by the explorer's `CRT_ANTI_PATTERN_LOCKS` at session startup (`scripts/autonomous_explorer.py:162-176`). Do not loosen.

**5M_SWEEP-side (still apply when scanner is enabled):**
- `ICT_SWING_N ≥ 3` — locked at 2
- `ICT_MIN_RR_GATE ≥ 2.0` — locked at 1.5
- `BACKTEST_FVG_MIN_QUALITY = LOW/MEDIUM` — coin-flip WR
- `BACKTEST_DAYS = 730` — 2024 dead-zone averaging

---

## 5. Honest empirical CRT findings (Run #139 ship config = "Test A")

| Source | n / 365d | WR | avg_R | sum_R/year |
|--------|----------|----|----|--------|
| 5M_SWEEP (Run-168 baseline, currently disabled) | 29 | 82.8% | 1.04 | 30.1 |
| H4_CRT (current ship, `CRT_TP1_MODE=min_1r`) | 416 | 54.8% | 0.33 | 135.1 |

**Key insight:** 5M_SWEEP is elite-quality / low-frequency; CRT is medium-quality / high-frequency. They are COMPLEMENTARY (zero overlap in 365 days — different setups at different times). Combined (when both ON): ~445 signals, 55-60% WR, 165R/year.

---

## 6. Adaptive learning — CRT-aware (post-2026-05-27)

Before today, CRT signals had `feature_scores_json=NULL`, causing `_trigger_weight_update` to silently skip every CRT trade close → adaptive learning was effectively OFF for CRT.

**Today's fix:** `compute_crt_feature_scores()` builds the same 6-feature dict (`fvg_quality`, `mss_quality`, `session`, `confidence`, `trend_strength`, `dr_location`) that the 5M_SWEEP path produces. Stored in `signals.feature_scores_json` at signal creation; read back by `_trigger_weight_update` at close.

**Caveats:**
- For OB-only CRT signals, `fvg_quality='NONE'` → score floor 0.05 → normalised ~1.5-6% of gradient. FVG feature learns slowly under CRT-OB-heavy mode.
- `dr_location` is always `UNKNOWN` for CRT (no dealing range computed) → floor contribution.
- Bootstrap WHERE clause loosened to admit OB-only CRT rows (was excluding 90% of CRT signals).
- DSR gate currently FAIL → learning rate scaled to 25% (`OGD_DSR_FAIL_LR_SCALE=0.25`). Tomorrow ~12:30 UTC the 24h FAIL streak may trip `OGD_FREEZE_DSR_FAIL_HOURS` → all OGD updates discarded. This is by-design self-protection given CRT WR is below the 55% MARGINAL threshold.

---

## 7. Per-scanner attribution rules for audits

When auditing TradeAI:
- **Tracker dashboard:** the Backtest tab now shows per-source WR/avg_R via `by_source` panel. Headline WR is a blend on mixed runs — the blend warning banner fires on Honest Metrics tab when `latest_run.blended=true`.
- **Pareto archive entries** (`data/pareto_archive.json`): each entry has a `runtime_env` block capturing the scanner toggles + CRT knobs active at trial time. Use this to determine whether a Pareto entry came from 5M-only, CRT-only, or both-on.
- **`baseline_pin.json`:** `key_settings` includes the full scanner + CRT fingerprint (today's E-3 fix). Rollbacks now include CRT knob diffs.
- **CPCV / DSR:** computed on ALL signals in the run (blended across sources). The Honest Metrics tab surfaces this blend via warning banner. Per-source CPCV is a future enhancement.
- **OGD weights:** `token_weights` (live) + `backtest_token_weights` (bootstrap) are NOT split by source. The same weight vector applies to both scanners' signals. If one scanner dominates the closed-trade distribution, the learned weights reflect THAT scanner's empirical signal — not a blend.

---

## 8. Operator's deliberate constraints (2026-05-27)

- **CRT-only paper soak in progress.** Do not flip `ENABLE_5M_SWEEP=1` without explicit operator instruction — it would interrupt the attribution-clean soak.
- **Wyckoff context still TAGGED in entry_type** even with filter off, so OGD can learn per-phase confidence in the future once enough paper trades close per context bucket.
- **No CRT promotion yet.** The Pareto archive + baseline_pin still reference Run-168 (the 5M_SWEEP pin from 2026-05-24). CRT is in paper-validation phase, not yet a canonical baseline.
- **Explorer search space is now CRT-tuned (default 2026-05-27).** `EXPLORER_SEARCH_SPACE=crt` (default) tunes 8 CRT params: `CRT_TP1_MODE`, `CRT_TP2_RR`, `CRT_TP3_RR`, `H4_CRT_C2_LOOKBACK`, `WYCKOFF_PHASE_FILTER` (off/loose only), `CRT_REQUIRE_1H_TREND`, `BACKTEST_BIAS_4H_GATE`, `CRT_FORWARD_BARS`. Trial subprocesses auto-pin `ENABLE_5M_SWEEP=0, ENABLE_H4_CRT=1` to match. Legacy 5M-tuned space available via `EXPLORER_SEARCH_SPACE=5m`. `CRT_ANTI_PATTERN_LOCKS` keeps `WYCKOFF_PHASE_FILTER=strict` and `CRT_APPLY_QUALITY_GATES=1` out of any session.

---

## 9. Common pitfalls (where agents go wrong)

1. **Assuming "the strategy" is one thing.** Always ask: is this question about the 5M_SWEEP path, the CRT path, or both? Their gates, TPs, and outcome windows differ.
2. **Quoting CPCV/DSR without acknowledging the blend.** On mixed-source runs, every metric is a weighted average. If the operator is in CRT-only mode (now), CPCV reflects CRT only — fine. But on historic mixed runs (#138-#143), CPCV blends.
3. **Treating Run-168 as "the baseline" in the CRT era.** Run-168 IS the 5M_SWEEP canonical baseline — still valid for that scanner. CRT doesn't have a promoted baseline; it has shipping config (Test A from Run #139).
4. **Suggesting Wyckoff strict mode.** Empirically rejected. Same for CRT_APPLY_QUALITY_GATES=1. Locked.
5. **Touching `.env` knobs without reading this file.** Operator's `.env` is hand-curated. Don't propose changes without first checking against today's empirical findings.

---

## 10. When you should re-read this file

- Any task involving signal generation, trade economics, OGD updates, or feature scoring
- Any backtest / explorer / promotion / Pareto / DSR-pool question
- Any tracker dashboard display question
- Any time the operator says "CRT" or "the new strategy" or "current paper soak"

For everything else, `CLAUDE.md` is sufficient.
