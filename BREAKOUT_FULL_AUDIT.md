# BREAKOUT_FULL_AUDIT — Phase C-Breakout worktree mechanical + isolation audit

**Date:** 2026-06-05 · **Branch:** `breakout-thesis` (worktree `/home/tradeai/breakout-work`)
**Type:** READ-ONLY mechanical-correctness + isolation + consistency audit. No code changed,
no DB written, no soak/viewer/process touched, nothing pushed/merged.
**Soaks audited:** A `breakout_paper_soak.py` (PID 555796), B `breakout_paper_soak_B.py` (PID 555797).

## 0. Verdict

**Mechanically clean and fully isolated. Soak↔backtest parity is exact. ONE substantive
consistency discrepancy (MEDIUM): the live gate is evaluated on the soak's CLEAN avg_R
(~+0.48, above +0.40) while the validated-negative conclusion is on the FRICTION basis
(+0.3765, below +0.40) — so the viewer verdict is projected to flip PENDING→PASS at n≥30,
contradicting the honest negative conclusion.** This is a gate-basis/labeling issue, NOT a
code bug, and it does NOT change the validated-negative conclusion (which is friction-basis
and correct). Two LOW notes. No HIGH/CRITICAL findings.

| # | Area | Result |
|---|---|---|
| 1 | Entry / signal logic (Config 14) | ✅ CLEAN |
| 2 | Exit model (V_ENTRY) | ✅ CLEAN (7 cases + ATOM#38 pass; no trail logic) |
| 3 | Soak↔backtest parity | ✅ EXACT (40k random paths, 0 mismatch) + 1 LOW |
| 4 | exec_quality observation layer | ✅ CLEAN (additive, fetch-safe, 18/18) |
| 5 | Viewer read-only | ✅ CLEAN |
| 6 | Isolation | ✅ CLEAN |
| 7 | State / restart recovery | ✅ CLEAN |
| 8 | Consistency with findings | ⚠️ **MEDIUM — gate-basis tension** |

---

## 1. Entry / signal logic (Config 14) — ✅ CLEAN

- **Config 14 knobs are applied via env overrides set before `import breakout_engine`.** The
  engine's *defaults* differ (C2_LOOKBACK=8, CLOSE_BUFFER=0.0, TP 1.5/2.5/3.5), but both
  soaks set `CONFIG_14 = {CLOSE_BUFFER:0.001, TP1/2/3_RR:2.0/3.0/4.0, C2_LOOKBACK:4,
  MSS_HORIZON:30}` into `os.environ` first, and `run_tf_grid.py` sets the same via
  `LOCKED_KNOBS` + `importlib.reload`. Live heartbeats confirm `config_14` / `config_14_B_5m_1h`.
- **Entry conditions match the documented contract:** C2 close beyond C1 ± buffer
  (`buy_threshold = c1_high*(1+CLOSE_BUFFER)`, `sell_threshold = c1_low*(1-CLOSE_BUFFER)`,
  `breakout_engine.py:300,355`), 5M continuation MSS (`horizon=H4_BREAKOUT_MSS_HORIZON`),
  FVG-or-OB confluence (OB scan `lookback=OB_SCAN_LOOKBACK` + FVG probe width), then the
  economics gate.
- **No hidden filters.** Grep of the breakout entry path finds NO regime / Wyckoff / trend /
  volume / quality / session gating wired in — the only mentions are docstrings stating these
  are OFF. The economics gate (`compute_crt_trade_economics`) is the sole filter; it enforces
  `ICT_MIN_RR_GATE`, `MIN_SL_PCT`, `MAX_SL_PCT`, and fee/BEW viability (multiple `return None`
  rejections in `crt_engine.py`).
- **One-shot consumed-zone logic is correct.** `detect_h4_breakout` skips any setup whose key
  `(c1_time, round(c1_high,6), round(c1_low,6))` is already in `consumed` (`breakout_engine.py:292`).
  The soak adds the key only AFTER `persist_signal` commits (F4 crash-safe), so a setup is never
  double-traded and a crash between detect and persist leaves the zone retry-eligible (correct).

## 2. Exit model (V_ENTRY) — ✅ CLEAN

- **Post-TP2 hold-at-entry confirmed:** SL→entry after TP1 (BE stop), stays at ENTRY after TP2
  (NOT trailed to TP1), monotonic-up. Between TP2 and entry there is no stop, so a dip to TP1
  after TP2 does not terminate — it can resume to TP3 (WIN) or expire (PARTIAL_TP2). Tiers:
  `LOSS / PARTIAL_TP1 / PARTIAL_TP2_BE / PARTIAL_TP2 / WIN / EXPIRED`.
- **V_ENTRY unit verification — all pass.** No standing dedicated test file existed (see LOW-2),
  so the 7 canonical cases + the ATOM#38 path were re-derived and run against
  `run_tf_grid.check_outcome` (V_ENTRY default) AND an exact transcription of the soak's
  `resolve_open_signals` walk:

  | case | outcome | grid | soak |
  |---|---|---|---|
  | 1 SL before TP1 | LOSS | ✅ | ✅ |
  | 2 TP1→back to entry | PARTIAL_TP1 | ✅ | ✅ |
  | 3 TP1→TP2→TP3 | WIN | ✅ | ✅ |
  | 4 TP1→TP2→back to entry | PARTIAL_TP2_BE | ✅ | ✅ |
  | 5 TP1→TP2→**dip to TP1 (not entry)→TP3** | **WIN** | ✅ | ✅ |
  | 6 TP1→TP2→expire above entry | PARTIAL_TP2 | ✅ | ✅ |
  | 7 never TP1→expire | EXPIRED | ✅ | ✅ |
  | ATOM#38 TP1→TP2→no TP3→drift→expire | PARTIAL_TP2 (live: OPEN until expiry) | ✅ | ✅ |

  The dip-to-TP1→TP3=WIN behavior (the defining difference vs the retired trail model) is
  reproduced correctly. `verify_fulltp2_unit.py` (which exercises the same `check_outcome`)
  re-run: ALL CLASSIFICATIONS OK.
- **No trail/T1 logic remains in the soaks.** Grep for `PARTIAL_TP2_T1 / trail_tp1 / t1_trail`
  in both soaks returns only comments ("not trailed to TP1") — zero trail code. The retired
  `trail_tp1` mode survives ONLY as a backtest-only reference parameter in `run_tf_grid.py`
  (default `hold_entry`), never reachable from the soaks.

## 3. Soak ↔ backtest parity — ✅ EXACT (+1 LOW)

This is the historically bug-prone area; it was stress-tested hard.

- **Outcome classification: EXACT.** A randomized battery of **40,000 synthetic OHLC paths**
  (BUY+SELL, random SL distance, random bar spans, 1–40 bars) through both
  `run_tf_grid.check_outcome` (V_ENTRY) and an exact transcription of the soak walk →
  **0 mismatches.** Plus the 8 named cases above. The soak's only extra state ("still OPEN,
  not yet expired") converges to the identical terminal tier as the backtest end-of-window.
- **R formula: EXACT.** All six tiers produce identical R from identical nets:
  LOSS −1.0000, PARTIAL_TP1 +0.7391, PARTIAL_TP2_BE +0.7391, PARTIAL_TP2 +2.0435, WIN +2.4783,
  EXPIRED 0.0000. Both use `rt_cost = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT)*100`,
  identical net = gross − rt_cost, identical risk = |net_sl|.
- **tz handling: matches.** Both soaks parse DB timestamps as UTC-aware
  (`.replace(tzinfo=timezone.utc)`) and build the forward window in UTC ms (TZ-FIX 2026-06-02);
  bar close times via `datetime.fromtimestamp(ms/1000, tz=timezone.utc)` (F3-FIX). `run_tf_grid`
  is UTC-aware throughout. No naive-local-time drift.
- **Friction basis:** the soak computes `realized_r` on the **CLEAN basis** (baseline rt_cost
  only — no `simulate_execution` Monte-Carlo). This is identical to the backtest **CLEAN** path
  (same next-5M-open entry, same rt_cost). The backtest **FRICTION** path (slippage / partial
  fill / rejection) is a separate, harsher estimate. The soak↔backtest-CLEAN bases match exactly;
  the friction divergence is the subject of finding §8 (it is documented + intentional, but its
  calibration is now stale).

**LOW-3 (cosmetic):** the degenerate risk fallback differs — soak `risk = abs(net_sl) or 0.001`,
grid `... or 0.0001`. Only triggers if `net_sl` rounds to exactly 0.0, which the `MIN_SL_PCT`
(0.5%) econ gate makes impossible. Never reached; no effect. Harmonize for tidiness only.

## 4. exec_quality observation layer — ✅ CLEAN

- **Purely additive / never consulted.** Grep for `would_skip` across `breakout_engine.py`,
  both soaks, and `crt_engine.py` → NONE. The flag is computed and logged but read by NO
  entry/exit/execution path. `observe_exec_quality` is called AFTER `persist_signal` + the
  `consumed.add` mark, and its return value is ignored.
- **Fetch-failure safe.** `verify_exec_quality.py` re-run: **18/18 checks pass** — a simulated
  order-book exception logs a `fetch_failed` row (NULL metrics) and returns without raising; the
  `signals`/`results` tables are SHA-256-identical on both success and failure paths; the trade
  stays OPEN; a `would_skip=1` snapshot still persists the trade unchanged. The fetch uses a 3s
  timeout / single attempt (cannot stall the 120s cycle).
- **Separate table, schema unaltered.** `exec_quality.py` only `CREATE TABLE IF NOT EXISTS
  exec_quality_log`; ZERO `ALTER/CREATE` of `signals` or `results` anywhere in the soaks or the
  module. (Live confirmation: 1 real row already logged — ADA SELL, soak B, would_skip=0,
  fetch ok — and the trade executed normally.)

## 5. Viewer (read-only) — ✅ CLEAN

- One sqlite connection, `mode=ro` (write attempts raise). **0** write-SQL statements
  (`INSERT/UPDATE/DELETE/DROP/CREATE TABLE`). All four write HTTP verbs (POST/PUT/DELETE/PATCH)
  → 405. The Exec Quality panel is display-only: SELECT-only aggregates, no form/input/checkbox,
  the word "gating" only in the static "No gating" label + warning. `would_skip` is shown,
  never used as a branch condition.

## 6. Isolation — ✅ CLEAN

- **Soaks hold ONLY `breakout.db`.** `/proc/555796/fd` and `/proc/555797/fd` each list only
  `/home/tradeai/breakout-work/data/breakout.db` (+wal/shm) — neither holds `signals.db` open.
  In code, `signals.db` is referenced solely as a read-only `.exists()` isolation check, never
  opened for I/O.
- **Fade soak (512666) alive and untouched** (still `crypto_alert.py`). `signals.db` is owned
  and written by the fade bot, never by the breakout soaks. **Run-3704 pin unchanged** (run_id
  3704). **`main` unchanged** (`2f71b69b…`).
- **Branch `breakout-thesis` committed but NOT pushed** (ahead of origin by 9; all breakout
  work local). `main` clean.

## 7. State / restart recovery — ✅ CLEAN

- `load_consumed_set` rebuilds the one-shot consumed-zone set from the soak's own
  `signals.feature_scores_json` (`c1_zone_key`), source-filtered so A/B never cross-pollute.
  Open signals are re-resolved every cycle from `breakout.db`. F3 (tz-aware `fromtimestamp`) and
  F4 (post-persist consumed mark — closes the crash gap) are both present. A restart loses no
  state and double-trades nothing — confirmed at the most recent restart (B reloaded 24 zones).

## 8. Consistency with findings — ⚠️ MEDIUM (gate-basis tension)

**Documented running config matches:** live = Config 14 + V_ENTRY hold-at-entry, gate currently
PENDING (n<30 closed), backtest friction ref TF_B = +0.3765 / TF_A = +0.3623 — all consistent
with the docs. The strategy is validated-negative (friction avg_R below the +0.40 gate) due to
random-walk token behavior, not code. **That conclusion is correct and unchanged by this audit.**

**The discrepancy — the live gate and the negative conclusion are on different cost bases:**

Authoritative 720d backtest (just re-run, `run_posttp2_backtests.py`, in-memory):

| TF | CLEAN avg_R (soak basis) | FRICTION avg_R (honest basis) | +0.40 gate |
|---|---|---|---|
| **B (primary)** | **+0.4818** (n=12330) | **+0.3765** (n=12090) | clean PASS / friction FAIL |
| A | +0.4830 (n=4843) | +0.3623 (n=4744) | clean PASS / friction FAIL |

- The **soak writes CLEAN `realized_r`**, and the **viewer gate evaluates `avg_r >= 0.40` on that
  clean value** (`breakout_viewer.py:688,729`). The clean expectancy (~+0.48) is **well above
  0.40**, and the other gates also pass on the friction run (WR 69.98% ≥ 0.58, PF 2.38 ≥ 2.0,
  maxDD 18.7 ≤ 20). So once the soak reaches **n≥30 closed**, the viewer verdict is projected to
  flip **PENDING → PASS**.
- But the **honest (friction) conclusion is REJECT** — TF_B +0.3765 < 0.40. So the live dashboard
  will display a PASS that contradicts the validated-negative finding.
- This was partly anticipated (`PHASE_C_AUDIT.md` LOW-1: "soak measures CLEAN R; thresholds had a
  friction cushion"), but that cushion was calibrated when clean ≈ +0.595 and friction sat near/
  above 0.40. The **current** model's friction (+0.3765) is **below** 0.40 while clean (+0.4818)
  is **above** it — the two now straddle the gate, so the cushion assumption ("pass clean ⇒
  friction still acceptable") no longer holds. The friction/clean ratio is ~0.78, i.e. a clean
  threshold of ~**+0.51** would map to the +0.40 friction bar.
- The viewer DOES correctly label the friction reference as `ref_avg_R_friction` /
  "Observational only — NOT part of verdict" — so the inconsistency is specifically that the
  binding gate runs on clean data while the negative verdict is friction-based.

**Severity: MEDIUM.** Not a mechanical bug (all computation is correct and internally consistent);
it is a gate-basis/calibration inconsistency that will make the live verdict disagree with the
honest conclusion. **Recommendation (no change made — read-only audit):** make the gate basis
explicit — either (a) raise the live avg_R gate to the clean-equivalent (~+0.51) of the +0.40
friction bar, (b) apply a friction haircut to the soak avg_R before gating, or (c) annotate the
verdict as clean-basis and cross-reference the friction conclusion so a future "PASS" isn't read
as a refutation of the validated-negative finding. Operator decision.

---

## Evidence / reproduction (all read-only)

```bash
cd /home/tradeai/breakout-work
python3 verify_fulltp2_unit.py          # V_ENTRY check_outcome contrast — ALL OK
python3 verify_exec_quality.py          # exec_quality safety — 18/18 PASS
python3 /tmp/audit_ventry_parity.py     # 7 cases + ATOM#38 + 40k-path parity — 0 mismatch
python3 run_posttp2_backtests.py        # clean vs friction avg_R (720d) — in-memory
```

- Soak↔backtest parity: 40,000 random paths, **0 mismatches**; R formula identical all tiers.
- Isolation: `/proc/{555796,555797}/fd` → only `breakout.db`; fade 512666 alive; Run-3704 + main unchanged.
- No code modified; no DB written; branch not pushed.

**Bottom line:** the breakout-thesis system is mechanically correct, internally consistent, and
fully isolated. The single MEDIUM item is a gate-basis labeling/calibration tension that should be
resolved before any live "PASS" is trusted — it does not alter the validated-negative conclusion.
