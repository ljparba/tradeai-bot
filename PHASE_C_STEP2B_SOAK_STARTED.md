# Phase C-Breakout — Step 2B: Paper Soak STARTED

**Status:** Parallel paper soak running. The fade soak is untouched.
**Soak label:** `H4_BREAKOUT_PAPER_SOAK`
**Config:** locked at Config 14, will NOT be tuned during the soak.
**Decision gate:** pre-registered below — applied AFTER ≥30 closed signals.

> The contract is: do not tune mid-soak, do not restart to change params,
> do not flip live. The soak is a forward OOS experiment that either
> validates or rejects the backtest's expectation. Both outcomes are
> acceptable.

---

## 1. Pre-registered pass criteria (locked BEFORE the first signal closes)

The soak passes its OOS validation gate when ALL of the following hold on
the first 30 CLOSED signals (or more — we report at the 30-close mark and
again at any subsequent milestone the operator requests):

| Criterion | Threshold | Notes |
|---|---|---|
| **avg_R per closed signal** | ≥ **+0.40** | Backtest (friction-on) predicted +0.59-0.68. We allow a generous 25-30% live-degradation cushion. Below +0.40 means live cost is larger than the friction model predicted — investigate before continuing. |
| **profit factor** | ≥ **2.0** | Backtest (friction-on) was 3.14. Allow degradation but require a clearly profitable ratio. PF below 2.0 means wins are not dwarfing losses by enough margin. |
| **WR** | ≥ **55%** | Backtest was 67%. A 12-pp gap accommodates live execution overhead; below 55% suggests the 67% backtest was overfit OR the harness missed real costs. |
| **per-token blowup** | no token with WR ≤ 35% AND avg_R < 0 over ≥5 signals | Soft per-token blowup check. POL and TON are the marginal performers in backtest — if either turns clearly negative live, surface it. |
| **max DD (R)** | ≤ **20 R** | Backtest peak DD was 14.8R. Allow ~35% buffer. If the live equity curve gets through 20R drawdown, the strategy's risk profile is materially worse than the backtest predicted. |

**On-failure action:** STOP the soak (`kill -TERM $(cat data/breakout_soak.pid)`),
write a failure report, do NOT tune params to rescue.

**On-pass action:** report to operator. Operator decides whether to:
- continue soaking to accumulate more out-of-sample evidence
- escalate to a candidate-pin promotion path (which is a separate process,
  not auto-triggered)
- archive the experiment

**What this gate does NOT do:**
- It does not arm LIVE mode. The production LIVE-clearance gate requires
  ≥ 30 paper signals on a config the operator has explicitly chosen to
  validate, plus CPCV mean WR ≥ 60% on production data, plus DSR ≥ 0.95.
  This soak is a research validation, not a live-clearance run.

---

## 2. Soak isolation — verified at startup

| Check | Verification |
|---|---|
| Separate process | PID 458923 (`python3 /home/tradeai/breakout-work/breakout_paper_soak.py`) |
| Separate working dir | `/home/tradeai/breakout-work/` (worktree on branch `breakout-thesis`) |
| Separate DB | All signals + results go to `data/breakout.db` ONLY. Fade soak's `data/signals.db` never opened. |
| Separate PID file | `data/breakout_soak.pid` (fade soak uses `/home/tradeai/TradeAI/data/tradeai.pid`) |
| Separate heartbeat | `data/breakout_soak_heartbeat.json` (fade soak uses `data/heartbeat.json`) |
| Separate log | `logs/breakout_soak.log` (fade soak journal via systemd) |
| No code-import overlap | `breakout_paper_soak.py` imports `breakout_engine`, `crt_engine`, `ict_engine`, `execution` — NO `crypto_alert`, `backtest`, `adaptive_engine`. |
| OGD off | No `token_weights` table reads or writes. |
| Wyckoff / funding / BTC-corr off | All overlays explicitly excluded; clean Config 14 thesis only. |

---

## 3. Soak runtime contract

| Aspect | Value |
|---|---|
| Cycle interval | 120 seconds |
| Tokens scanned per cycle | 12 (BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON, ATOM, BCH) |
| Binance API calls per cycle | 24 (12 tokens × 2 timeframes: 5m + 4h) |
| Total Binance rate impact | ~12 req/min (well under 1200/min Binance ceiling) |
| Outcome resolution | Each cycle also polls Binance for OPEN signal price history and resolves any TP1/2/3/SL hits |
| Forward window | 48h per signal (matches backtest) |
| Stale-signal guard | Refuses to emit signals whose MSS bar is > 60 min old |
| Restart safety | On restart, rebuilds the `consumed_h4_crt` set from existing OPEN+CLOSED signal rows so no duplicate firings |
| Graceful shutdown | SIGTERM/SIGINT handler waits for current cycle to finish, removes PID file |

### To monitor

```bash
# Heartbeat
cat /home/tradeai/breakout-work/data/breakout_soak_heartbeat.json

# Live log
tail -f /home/tradeai/breakout-work/logs/breakout_soak.log

# Signal count
sqlite3 /home/tradeai/breakout-work/data/breakout.db \
  "SELECT status, COUNT(*) FROM signals WHERE source='H4_BREAKOUT_PAPER_SOAK' GROUP BY status;"

# Closed signal performance
sqlite3 /home/tradeai/breakout-work/data/breakout.db -header -column \
  "SELECT s.token, s.signal AS dir, s.timestamp, r.result, r.realized_r
   FROM signals s JOIN results r ON s.id=r.signal_id
   WHERE s.source='H4_BREAKOUT_PAPER_SOAK' ORDER BY r.closed_at DESC LIMIT 30;"
```

### To stop gracefully

```bash
kill -TERM "$(cat /home/tradeai/breakout-work/data/breakout_soak.pid)"
```

### To restart after stop

```bash
cd /home/tradeai/breakout-work
nohup python3 breakout_paper_soak.py > logs/breakout_soak.log 2>&1 &
echo $! > data/breakout_soak.pid
```

---

## 4. Expected signal frequency

The 365-day backtest produced 2222 attempted signals for Config 14, so the
expected rate is ~6 signals/day across 12 tokens. The 30-signal milestone
should therefore arrive after ~5 days, with the first 30 CLOSED signals
arriving after ~5 + 2 (the 48h forward window) = ~7 days.

If the actual rate is materially lower (e.g. < 1 signal/day for a week),
the live universe is producing fewer breakouts than the historical window
implies — itself a useful signal about regime shift.

---

## 5. Carry-over caveats from Step 2A

1. The friction-on backtest under-states stale-price reject (the bar-data
   harness reported 0 stale rejections; the live soak will surface real
   latency-driven rejections — that's the main "unknown unknown" for paper).
2. Adverse-selection cost was disabled in 2A (regime=UNKNOWN). The live
   soak runs in real market regimes, so the realised friction overlay will
   be slightly heavier than the +0.59 avg_R per attempted estimate from 2A.
3. The fade soak is running in parallel and may emit Telegram alerts on
   ITS signals — the operator should ignore those for breakout validation
   purposes (they belong to a different research thread).

---

## 6. NEXT STOPS

I have stopped here per the prompt's instructions:
1. Soak is running and isolated.
2. Step 2A report committed.
3. Step 2B start report committed.
4. **No merge to main. No push of `breakout-thesis` to GitHub.**
5. **No live arming.**

I will not check on the soak again unless instructed. The operator can
report back when:
- The 30-close milestone is reached (~7 days).
- The soak shows clear failure earlier (per-token blowup, large drawdown).
- A configuration question arises that requires my context.
