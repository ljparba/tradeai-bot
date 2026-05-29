# Risk Management Audit — Post-CRT Pro Cycle
**Date:** 2026-05-27
**Cycle:** 8 (post-CRT-Pro shipping cycle)
**Prior score:** 9.5/10 (cycle-7)
**Mode:** PAPER, CRT-only (ENABLE_5M_SWEEP=0, ENABLE_H4_CRT=1, CRT_TP1_MODE=min_1r)

---

## Prior Art Check

All regression-prone items from CROSS_REF.md verified still in place:
- C6 (kill switches): VERIFIED — check_kill_switches() active in PAPER (crypto_alert.py:1197)
- C7 (drawdown formula): VERIFIED — profit_pct × MAX_POSITION_PCT math correct (adaptive_engine.py:1700)
- C8 (capital guard): VERIFIED — YOUR_CAPITAL hard-stop in LIVE block (crypto_alert.py:3436)
- H11 (equity curve drawdown): VERIFIED — full chronological equity curve (adaptive_engine.py:1681)
- H13 (actual P&L kill switch): VERIFIED — SUM(profit_pct) used (crypto_alert.py:1224)
- H14 (position sizing 20% cap): VERIFIED — MAX_POSITION_PCT=0.20 cap in compute_position_size (crypto_alert.py:2318)
- M17 (circuit breaker 0.55): VERIFIED — config.py:232
- M18 (portfolio risk gate 0.03): VERIFIED — adaptive_engine.py:176
- RM-CORR (XRP/ADA in CORRELATED set): VERIFIED — adaptive_engine.py:1626

---

## CRITICAL RISK FLAWS

### CRIT-CRT-1: CRT Live Scanner Bypasses Kill Switches and Portfolio Risk Gate

**File:** `/home/tradeai/TradeAI/crypto_alert.py`, lines 3774–3815

**Flaw:** The CRT live scan block (lines 3774–3815) calls `scan_h4_crt_for_token()` and proceeds directly to `save_signal()` with NO call to `check_kill_switches(token)` and NO call to `portfolio_layer.check(token, signal, RISK_PER_TRADE_PCT)`.

By contrast, the 5M_SWEEP path in `generate_signal()` calls both:
- `check_kill_switches(token)` at line 2424
- `portfolio_layer.check(...)` at line 2731

**What this means in practice (current PAPER mode):**
- The kill switch limits (MAX_DAILY_LOSSES=3, MAX_DAILY_LOSS_PCT=3%, MAX_CONSECUTIVE_LOSSES=3, SYMBOL_LOSS_COOLDOWN_H=2h) are **ignored for every CRT signal**. After 3 consecutive CRT losses the bot will continue firing CRT signals regardless.
- The portfolio risk caps (MAX_OPEN_POSITIONS=20, MAX_PORTFOLIO_RISK_PCT=1.0) are loose in PAPER mode anyway, so the real impact is in LIVE mode.

**Worst-case scenario in LIVE mode (if CRT ever goes live):**
- The portfolio cap is MAX_OPEN_POSITIONS=4 and MAX_PORTFOLIO_RISK_PCT=3% in LIVE mode. Without this check, CRT could add a 5th, 6th, or more positions, making total open risk exceed the design cap. With CRT's 416 signals/year rate (17/month), multiple simultaneous CRT opens are plausible.
- During a correlated BTC-led crash, a CRT SELL or BUY signal could bypass the correlation block (`adaptive_engine.py:1720`) that prevents >2 correlated alts in the same direction.
- A daily kill switch activated by 5M_SWEEP losses would NOT prevent CRT from adding more signals that day.

**Classification:** NEW FINDING — HIGH severity in PAPER mode (data contamination), CRITICAL in any LIVE transition.

**Note:** The `last_signal_times` per-direction cooldown check is also in `generate_signal()` at line 2660, which CRT bypasses. However, CRT has its own mitigation via `consumed_h4_crt` (one-shot per C1 zone), but this is zone-level not time-level. Two different CRT setups on the same token (different C1 zones) can fire within 40 minutes.

---

### CRIT-CRT-2: CRT Live Signal Expiry Set to 12h While Backtest Outcome Window is 48h

**File:** `/home/tradeai/TradeAI/crypto_alert.py`, line 700–701 (save_signal); `/home/tradeai/TradeAI/crt_engine.py`, line 85 (CRT_FORWARD_BARS=576)

**Flaw:** CRT signals saved in the live DB receive `expires_at = now + EXPIRY_BY_REGIME["UNKNOWN"] = now + 12h`. The CRT backtest evaluates outcomes over `CRT_FORWARD_BARS=576` (48 hours). This is a 4× mismatch:

- **Backtest:** outcome window = 48h. If TP1/TP2/TP3 is reached within 48h after entry → WIN/PARTIAL.
- **Live paper tracking:** signal expires after 12h. If price hasn't reached TP1 by hour 12 → EXPIRED (not WIN). Any CRT setup that would win in backtest between hour 12 and hour 48 will log as EXPIRED live.

**Impact on metrics:**
- Paper WR will be systematically understated vs backtest WR. The honest backtest says 54.8% WR; paper soak WR will likely show lower, misleadingly suggesting strategy edge has decayed.
- OGD learning is corrupted: EXPIRED signals contribute reward = -0.25 (adaptive_engine.py:1021). Trades that win at hour 14, 20, 36 will all be scored as -0.25 losses to the adaptive engine — training the per-token weights away from genuinely profitable setups.
- Kill switch daily loss count (MAX_DAILY_LOSSES=3) counts EXPIRED as a loss outcome (crypto_alert.py:1224). Under CRT's 12h expiry, this could trigger kill switches on days when the strategy is actually profitable but slow.

**Worst-case:** With 17 CRT signals/month and 48h development time, a meaningful fraction (~30-50%) of winning CRT trades could expire at 12h. OGD weights are actively learning in the wrong direction right now.

**Correct behavior:** CRT signals should expire at 48h to match `CRT_FORWARD_BARS`. Either:
(a) Add a CRT-specific expiry: `expires_at = now + timedelta(hours=48)` for `source='H4_CRT'` signals in save_signal(), or
(b) Set `EXPIRY_BY_REGIME["UNKNOWN"] = 48` (risks changing 5M_SWEEP expiry too — use (a)), or
(c) Pass the expiry hours through the result dict and let save_signal() use it.

**Classification:** NEW FINDING — CRITICAL (corrupts paper attribution data and OGD weights).

---

## SERIOUS RISK GAPS

### GAP-CRT-1: CRT Path Has No ICT_MIN_RR_GATE (1.5R Minimum Not Applied)

**Files:** `/home/tradeai/TradeAI/crypto_alert.py` (scan_h4_crt_for_token), `/home/tradeai/TradeAI/backtest.py` (run_backtest_token_h4_crt)

**Gap:** The 5M_SWEEP path applies `ICT_MIN_RR_GATE=1.5` at `crypto_alert.py:2720` and `backtest.py:1090`. Neither the live CRT path (scan_h4_crt_for_token, lines 766–1017) nor the backtest CRT path (run_backtest_token_h4_crt, lines 1295–1650) applies this gate.

**Mitigating factor (partial):** The `compute_crt_trade_economics()` function rejects trades where `breakeven_wr > MAX_BREAKEVEN_WR=0.60`. As verified by calculation:
- With rt_cost=0.30%, a 1R TP1 setup (SL=1%, TP1=1%) has bew=0.65 → rejected.
- The bew gate implicitly enforces a minimum RR of ~1.167R for 1% SL setups.
- For SL >= 1.5%, 1R TP1 has bew=0.60 which is exactly at the boundary (the gate uses `>` not `>=` so bew=0.60 passes).

**Remaining gap:** For SL >= 1.5%, a 1R setup passes the bew gate with no additional RR check. The bew gate is not equivalent to a strict 1.5R minimum — a 1.167R setup (just clearing bew for a 1% SL) would pass through with a sub-1.5R actual RR, which the 5M_SWEEP path would reject.

**In CRT_TP1_MODE=min_1r:** The TP1 is at least 1R, so the minimum practical RR1 on the plan will be 1:1 for setups where c1_opposite < 1R distance. The bew gate provides backstop but is not equivalent to the 1.5R hard gate.

**Classification:** NEW FINDING — SERIOUS. In current PAPER mode, this inflates CRT signal count above what the 5M_SWEEP consistency gate would permit. In any future dual-scanner mode this creates a WR/RR asymmetry between the two signal sources.

### GAP-CRT-2: CRT Per-Direction Cooldown Uses Zone-Level (Not Time-Level) Throttle

**File:** `/home/tradeai/TradeAI/crypto_alert.py`, lines 3786–3816

**Gap:** The 5M_SWEEP path enforces a wall-clock 40-minute per-direction cooldown per token via `STATE[token]["last_signal_times"]` (crypto_alert.py:2660–2661). The CRT path only uses `consumed_h4_crt` (one-shot mitigation per C1 zone). Two separate CRT setups (different C1 zones) on the same token can fire within minutes of each other.

**Impact with 416 signals/yr:** At ~1.14 CRT signals per day across 9 tokens, multi-signal days are common. Back-to-back BUY on the same token within 5 minutes (two different H4 zones detected simultaneously in the H4 candle scan) is theoretically possible. This would confuse the operator and inflate the per-token open count.

**Backtest note:** The backtest has no equivalent of this per-time cooldown for CRT (it has no `COOLDOWN_BARS` check in `run_backtest_token_h4_crt`). The H4 scan walks forward one H4 bar at a time — a new CRT setup can fire every 4 hours regardless of the prior CRT signal on the same token. This matches the live behavior gap noted here, so at least live/BT are symmetric in their lack of time-cooldown. The issue is whether the operator wants a CRT time-cooldown at all.

**Classification:** NEW FINDING — SERIOUS (signal count consistency with stated 40-min cooldown design).

---

## PARAMETER SANITY ISSUES

### PARAM-1: CRT Expiry at 12h Creates BEW Miscalibration

**Parameter:** `EXPIRY_BY_REGIME["UNKNOWN"]` = 12h (config.py:198)
**CRT_FORWARD_BARS** = 576 (48h)
**Recommended:** Add CRT-specific expiry of 48h (see CRIT-CRT-2 above).

### PARAM-2: MAX_BREAKEVEN_WR=0.60 Is Compatible With CRT Economics (Not Aggressive)

**Parameter:** `MAX_BREAKEVEN_WR` = 0.60 (ict_engine.py:69)
**Current CRT WR:** 54.8% (from Run #139 empirical data)

With CRT's 54.8% WR, the bew gate at 0.60 is correctly calibrated: setups requiring >60% WR to break even should be rejected because the strategy doesn't achieve that WR. Setups with bew <= 0.60 are within the strategy's demonstrated edge range. No change needed here.

### PARAM-3: RISK_PER_TRADE_PCT=1% Is Appropriate for CRT's Volume

**Parameter:** `RISK_PER_TRADE_PCT` = 0.01 (1%) (config.py:203)
**CRT signal rate:** ~416/yr (~34/month)

With up to 34 signals/month and 1% risk/trade, worst-case scenario (all losses in one month) = 34% drawdown. However:
- `MAX_PORTFOLIO_RISK_PCT=3%` in LIVE mode caps concurrent exposure at 3 simultaneous 1% trades.
- `MAX_DAILY_LOSSES=3` and `MAX_CONSECUTIVE_LOSSES=3` kill switches bound the daily/streak exposure.
- Monthly worst-case under kill switches: ~10 losses before halts activate = 10% × 20% notional = ~2% capital (well-bounded).

**BUT** — note that the kill switch bypass (CRIT-CRT-1) breaks this bound if CRT is ever taken live without the fix.

### PARAM-4: CRT Forward Window 48h vs Signal Cooldown 40min — No Conflict

**CRT_FORWARD_BARS=576** (48h outcome window in backtest)
**SIGNAL_COOLDOWN=40min** (per-direction cooldown in live)

These operate at different levels and don't conflict. The 48h forward window is the backtest outcome evaluation period, not a live cooldown mechanism. A new CRT signal on the same token/direction can fire 40 minutes after the first one closes if the consumed set is clear. No issue here.

---

## EDGE CASE FAILURES

### EDGE-1: CRT min_1r TP1 for SL < 1.5% — BEW Gate Interaction

**Trigger:** CRT setup with tight SL (< 1.5%) when CRT_TP1_MODE=min_1r.

**Behavior:** For SL = 0.5%, 0.8%, 1.0%, 1.4%, the min_1r mode sets TP1 = 1R. The bew gate computes bew = (SL + 0.30) / (TP1 + SL) = (0.5 + 0.30) / 1.0 = 0.80 for SL=0.5%, rejecting the trade. This is the INTENDED behavior — tight-SL 1R setups are genuinely negative-EV at 54.8% WR.

**The actual risk:** When c1_opposite > 1R (so min_1r doesn't boost TP1 and the trade would have passed economics in dynamic mode), min_1r is a no-op and the economics gate behaves identically to dynamic mode. No spurious rejections introduced by min_1r.

**Verified correct behavior** — no action needed.

### EDGE-2: What if entry_price == sl_price for CRT?

**File:** `/home/tradeai/TradeAI/crypto_alert.py`, lines 887–889

The live scanner checks `if risk_dist <= 0: return None, None, "zero_risk_dist"`. The backtest at `backtest.py:1496` checks `if risk_dist <= 0: rej["crt_zero_risk_dist"] += 1; continue`. Both paths handle this edge case. No issue.

### EDGE-3: CRT Signal When Account Balance is $0 or Negative

**File:** `/home/tradeai/TradeAI/crypto_alert.py`, line 2315

`compute_position_size()` returns zero-size dict when `capital <= 0`. CRT does not call `compute_position_size()` in its own path (the sizing is done in `generate_signal()` for 5M_SWEEP). The CRT path emits a signal with position sizing computed via the Telegram message renderer at line 3226. The renderer reads `sz_risk_pct` but does not crash on zero capital. No runtime crash risk, but a $0 YOUR_CAPITAL would produce a $0 position size recommendation — operator confusion rather than system failure.

---

## VERIFIED FIXES (CRT-Specific, Cycle-7)

The following cycle-7 fixes were verified still in place:

1. **TP cascade math (crt_engine.py):** SL = sweep_wick × (1 ± ICT_SL_BUFFER_PCT=0.003), TP1 = adjust_crt_tp1(min_1r), TP2 = entry ± 1.5R, TP3 = entry ± 2.0R. Math verified correct at lines 869–895 of crypto_alert.py and lines 1480–1504 of backtest.py.

2. **Economics gate (compute_crt_trade_economics):** net_tp1 ≤ 0 gate and bew > MAX_BREAKEVEN_WR=0.60 gate both active (crt_engine.py:593, 604). rt_cost_pct=0.30% (0.003 × 100) correctly applied. Returns None on rejection; caller uses crt_trade_rejection_reason() for diagnostic counters. VERIFIED.

3. **LIVE portfolio caps in LIVE mode:** MAX_OPEN_POSITIONS=4, MAX_PORTFOLIO_RISK_PCT=3%, MAX_DRAWDOWN_PCT=10% for LIVE mode (adaptive_engine.py:174–177). VERIFIED. (Issue: these are bypassed by CRT path — see CRIT-CRT-1.)

4. **CRT signal frequency and cooldown:** CRT uses consumed_h4_crt (one-shot zone mitigation) rather than time-based cooldown. The 40min SIGNAL_COOLDOWN from config.py applies only to 5M_SWEEP path. This is a known structural gap (see GAP-CRT-2) but not a regression from cycle-7 — it was never wired for CRT.

5. **CRT_TP1_MODE=min_1r ensures TP1 >= 1R:** Verified via direct calculation — max(c1_opposite, entry±1R) for BUY / min(c1_opposite, entry-1R) for SELL. Logic correct (crt_engine.py:167–211).

---

## RISK SYSTEM SCORECARD

| Component | Status | Notes |
|-----------|--------|-------|
| Position Sizing | Sound | 1% risk/trade, 20% notional cap, zero-division protected |
| Stop Placement | Sound | SL = sweep_wick ± 0.3% buffer; MIN_SL_PCT=0.5%, MAX_SL_PCT=3.0% |
| Portfolio Heat Limit | Flawed | Enforced for 5M_SWEEP; bypassed by CRT live path (CRIT-CRT-1) |
| Daily Loss Circuit Breaker | Flawed | Enforced for 5M_SWEEP; bypassed by CRT live path (CRIT-CRT-1) |
| Total Drawdown Limit | Flawed | Enforced for 5M_SWEEP; bypassed by CRT live path (CRIT-CRT-1) |
| R:R Minimum Filter (1.5R) | Flawed | Applied to 5M_SWEEP; absent from both CRT paths (GAP-CRT-1) |
| CRT Expiry / Outcome Window | Flawed | 12h expiry vs 48h backtest window (CRIT-CRT-2) |
| BEW Economics Gate | Sound | Correctly filters sub-BEW setups for CRT |
| OGD Adaptive Learning | Sound (with caveat) | Feature scores now populated; DSR-FAIL scale-down active. Corrupted by CRIT-CRT-2 until expiry fixed |
| Edge Case Handling | Robust | zero_risk_dist, API error fail-closed, zero-capital safe |
| Correlation Guard | Partially Sound | Enforced for 5M_SWEEP; bypassed for CRT via CRIT-CRT-1 |
| Symbol Loss Cooldown | Flawed | Bypassed by CRT path (CRIT-CRT-1) |

---

## SCORE: 8.5 / 10

**Deductions from 9.5 (cycle-7 baseline):**
- **-0.5** CRIT-CRT-1: Kill switch + portfolio gate bypass on CRT live path (HIGH severity in PAPER, CRITICAL if CRT goes LIVE)
- **-0.5** CRIT-CRT-2: 12h expiry vs 48h backtest outcome window — corrupts paper WR attribution and OGD learning right now

**Mitigating factors preventing larger deduction:**
- Both flaws are in PAPER mode only currently (no real money risk today)
- CRT signals are blocked from LIVE Telegram in v1 by `template_live_allowed=0` (crypto_alert.py:3806)
- The portfolio/kill switch bypass still logs to DB, so retrospective analysis is possible
- OGD is in DSR-FAIL soft-scale mode (0.25× LR) so corrupted gradients have reduced impact

---

## PROACTIVE IMPROVEMENT SUGGESTIONS

**Suggestion:** Fix CRT expiry to 48h matching CRT_FORWARD_BARS
**Why:** Every CRT signal currently expires at 12h while backtest measures at 48h. OGD is actively being trained with wrong outcome labels. This affects paper WR benchmarks and the LIVE clearance gate (need ≥30 closed paper signals).
**Impact:** HIGH
**Effort:** Simple — in save_signal(), check result.get("source") == "H4_CRT" and use timedelta(hours=48) for expires_at.

**Suggestion:** Wire check_kill_switches() and portfolio_layer.check() into the CRT scan block at crypto_alert.py:3790
**Why:** The current gap means CRT will violate daily loss limits and portfolio heat caps the moment it gets LIVE-capable. The fix is 4 lines.
**Impact:** HIGH
**Effort:** Simple

**Suggestion:** Apply ICT_MIN_RR_GATE=1.5 to CRT path (or document why bew gate is sufficient)
**Why:** The bew gate provides a minimum implied RR but it's SL-dependent (for SL >= 1.5%, 1R passes). The 5M_SWEEP hard floor of 1.5R is more conservative and consistent. Either add the gate to both CRT paths or add a config comment explaining the intentional asymmetry.
**Impact:** MEDIUM
**Effort:** Simple

**Suggestion:** Add per-direction time-based cooldown to CRT live path
**Why:** Currently two different CRT zones on the same token/direction can fire within minutes. At 17 signals/month, multi-zone detection within a scan cycle is possible on liquid tokens. Consider `STATE[token]["last_crt_signal_times"]` mirroring the 5M_SWEEP pattern, or accept and document the zone-based mitigation as sufficient.
**Impact:** MEDIUM
**Effort:** Simple

---

## CROSS-DOMAIN OBSERVATIONS

**Observation:** The 12h CRT expiry vs 48h backtest window (CRIT-CRT-2) will produce a systematic divergence in live vs backtest WR metrics that the live-backtest-consistency-checker should be aware of. The blended WR shown in the tracker dashboard will understate the true CRT edge until the expiry is fixed.
**Relevant Agent:** live-backtest-consistency-checker
**Reason:** This is a data-layer parity issue, not purely a risk issue.

**Observation:** OGD weights are currently being trained with wrong outcome labels (EXPIRED instead of WIN for slow CRT winners). The adaptive-learning-code-reviewer should consider whether the current paper soak is producing valid weight vectors for CRT tokens, given that the effective reward signal is biased toward -0.25 (EXPIRED penalty) for a large fraction of winning trades.
**Relevant Agent:** adaptive-learning-code-reviewer
**Reason:** The 48h development time of CRT setups means a significant fraction of winners will be misclassified before CRIT-CRT-2 is fixed.

