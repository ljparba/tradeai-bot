# Freqtrade / FreqAI — Adoptable Ideas for the Breakout Bot

**Purpose:** A curated list of patterns, tools, and ideas from Freqtrade (the
mature open-source crypto bot, 48k stars) and FreqAI (its ML extension) that
could improve OUR breakout/continuation bot — WITHOUT porting to Freqtrade.

**Decision already made:** We are NOT migrating to Freqtrade. Our validation work
(tz-fix, exit-model fix, BE-after-TP1, WR recalibration, 720d multi-regime
backtest, isolation discipline) is too deep to throw away, and porting would
reset all of it. This doc is for *borrowing ideas*, not switching frameworks.

**How to read this:** Each item is tagged:
- `[NOW]` — safe to consider applying during/around the current paper soak
  (read-only diagnostics, or things that don't touch the running soak/exit model)
- `[POST-SOAK]` — wait until the forward soak completes (n≥30, then 60); applying
  now would reset forward count or add unvalidated complexity
- `[LIVE-HARNESS]` — relevant when building the Bybit auto-trade harness (the
  BE-after-TP1, fixed-R sizing, concurrency caps we already identified as
  go-live prerequisites)

**IMPORTANT discipline note:** Nothing here overrides our existing principles.
Anything adopted must go through the same gates: read the actual Freqtrade source
before copying any logic, unit-verify, keep soak/backtest parity, never tune to
target, and don't reset the forward soak for a non-critical change.

---

## 1. Lookahead-bias detection — `[NOW]` (as methodology, not their tool)

**What Freqtrade does:** It has a `lookahead-analysis` command that runs a baseline
backtest, then re-runs backtests for each entry/exit signal *in isolation*, and
compares whether indicator values or entry/exit timings CHANGED between the full
run and the sliced run. If they changed, the strategy is "seeing" future data.

**Why this matters to us:** The two worst bugs we found (the timezone
outcome-resolution bug and the exit-model premature-close bug) were both forms of
look-ahead / wrong-data-window bugs. Our structural audits MISSED them; only the
end-to-end data-path trace caught them. Freqtrade formalized exactly this class of
check into a repeatable command.

**Their concrete examples of look-ahead bias (worth checking our engine against):**
- `shift(-10)` — looking N candles into the future
- `.iloc[]` accessing a specific row in a way that can reach future rows
- For-loops that don't tightly control the index range
- Aggregations (`.mean()`, `.min()`, `.max()`) WITHOUT a rolling window — these
  compute over the WHOLE series, so the signal candle "sees" future values. The
  unbiased form is `.rolling(N).mean()`.

**What to adopt (methodology, not the tool):**
- Build (or formalize) our own "sliced re-resolution" check: for a sample of
  closed signals, re-resolve each one in isolation using ONLY bars available at
  signal time, and confirm the outcome/R matches the full-run resolution. We
  already do a version of this in the end-to-end data-path trace — this just makes
  it a standing, repeatable audit rather than an ad-hoc one.
- Grep our `breakout_engine.py` for the bias patterns above (non-rolling
  aggregations, negative shifts, raw `.iloc[]` into forward indices).

**Caveat from their docs:** the analysis only verifies signals that actually
triggered in the test window — untriggered signal types produce false negatives.
So our version must ensure the sample covers all entry types (FVG + OB) and both
directions.

**Action:** `[NOW]` — Claude Code can run a read-only grep audit of
`breakout_engine.py` for the listed bias patterns, and (separately) formalize the
sliced-re-resolution check as a reusable diagnostic. No code change to the engine
unless a real bias is found.

---

## 2. `custom_stoploss` / BE-after-TP1 patterns — `[LIVE-HARNESS]`

**What Freqtrade does:** It has a mature, battle-tested `custom_stoploss()` callback
system. The stoploss "can only ever move upwards" (toward locking profit) — exactly
the BE-after-TP1 behavior we just built into our paper model. They have a documented
helper `stoploss_from_open()` that converts "I want my stop at X% above entry" into
the relative-to-current-price value the exchange needs.

**Directly relevant patterns they document:**
- **Stepped stoploss** — fixed stop levels by profit tier (e.g. at +20% profit,
  move stop to +7% above entry; at +25%, move to +15%). This is conceptually our
  BE-after-TP1, generalized to multiple tiers. If we ever want BE-after-TP1 PLUS a
  trailing stop after TP2, this is the reference pattern.
- **`stoploss_from_open(0.0, current_profit, ...)`** — this is literally "move stop
  to breakeven." It's the exact primitive our Bybit harness needs for the
  "move SL to entry once TP1 fills" rule.
- **`order_filled()` callback** — fires right after ANY order fills (entry, exit,
  stop, partial). This is the event hook we need: when the TP1 partial-exit order
  fills, THAT is when we cancel the old SL and place the BE stop. Freqtrade's
  `order_filled()` is the canonical place to do this.
- **`stoploss_on_exchange`** — they place the stop ON the exchange (not just in the
  bot), updated at a configurable interval. For Bybit, this matters: a stop held
  only in our bot dies if our process/VPS dies; a stop on the exchange survives.

**Why this matters to us:** Our RUNNER_EXIT_GAP.md found that the live BE-after-TP1
rule requires: listen for TP1 fill → cancel original SL → submit new SL at entry,
within seconds. Freqtrade's `order_filled()` + `custom_stoploss()` +
`stoploss_on_exchange` is a working, multi-year-tested implementation of exactly
this sequence. We should READ their source (not copy blindly) when building our
Bybit harness, to learn the edge cases they hit (partial fills, websocket
disconnects, stop-update races).

**Action:** `[LIVE-HARNESS]` — when we build the Bybit harness, fetch and study
Freqtrade's `order_filled()` and `custom_stoploss()` source + their
`stoploss_on_exchange` logic as a reference implementation. Do NOT adopt now —
this is post-soak, live-harness work.

---

## 3. Stop-loss ON the exchange (survivability) — `[LIVE-HARNESS]`

**What Freqtrade does:** `stoploss_on_exchange` places the actual stop order on the
exchange, so it triggers even if the bot is offline. They update it on an interval
(`stoploss_on_exchange_interval`).

**Why this matters to us:** Our current design (and TopStep MNQ background) assumes
local execution. For Bybit auto-trade, a stop that lives only in our bot is a
single point of failure — if the VPS hiccups, an unprotected runner could blow
past its stop. Putting the SL (and the BE stop after TP1) ON Bybit is a
survivability upgrade.

**Caveat:** This interacts with our BE-after-TP1 logic — when TP1 fills, we must
cancel the exchange SL and replace it with the BE SL on the exchange. That's a
cancel+replace race that Freqtrade handles; we'd need to handle it too.

**Action:** `[LIVE-HARNESS]` — design the Bybit harness to keep stops on-exchange,
with the BE replacement done via the fill-event hook. Reference Freqtrade's
interval-based stop-update approach.

---

## 4. Fixed-R / stake sizing callback — `[LIVE-HARNESS]`

**What Freqtrade does:** `custom_stake_amount()` callback lets you size each position
before entry. They support compounding, per-condition sizing, etc.

**Why this matters to us:** SL_SIZING_CHECK.md already concluded we MUST use
fixed-R sizing on Bybit (position_USDT = capital × risk% ÷ sl_dist%), because our
structural SL varies 0.5%–3% per signal. Fixed-notional would over-risk wide-SL
tokens (HBAR/BCH ~4× BNB's risk). Freqtrade's `custom_stake_amount()` is the
canonical place to implement fixed-R sizing, and confirms this is the standard
approach (size by stop distance, not fixed dollars).

**Action:** `[LIVE-HARNESS]` — implement fixed-R sizing in the Bybit harness's
equivalent of `custom_stake_amount()`. Reference their callback signature/pattern.

---

## 5. Concurrency / max-open-trades cap — `[LIVE-HARNESS]`

**What Freqtrade does:** `max_open_trades` config caps simultaneous positions. They
also have `protections` plugins (cooldown, max-drawdown stop, low-profit-pairs
lockout) that pause trading under adverse conditions.

**Why this matters to us:** SL_SIZING_CHECK.md flagged the correlated-cluster risk:
7 simultaneous BUYs fired in one bar (crypto high correlation). If all lose, that's
−7R compressed into ~48h. We identified the need for a max-concurrent cap and/or
per-token notional cap. Freqtrade's `max_open_trades` + protections are the
reference for this — including the idea of a max-drawdown protection that halts
new entries after a drawdown threshold.

**Their protections worth considering (POST-SOAK / LIVE):**
- Cooldown period after a loss
- MaxDrawdown lockout (stop entering after X drawdown)
- StoplossGuard (stop after N stops in a window)

**Action:** `[LIVE-HARNESS]` — add a max-concurrent-position cap to the Bybit
harness. Consider a drawdown-based "pause new entries" protection. Decide the cap
value consciously (backtest survives unlimited concurrency, but live capital
allocation is a separate risk decision).

---

## 6. Realistic backtest of adaptive/retraining models — `[POST-SOAK]`

**What FreqAI does:** Its headline feature is **self-adaptive retraining** —
retraining a predictive model periodically during live deployment to adapt to the
market. Critically, its backtesting module **emulates this retraining on historic
data** (walk-forward retraining), which is the honest way to backtest an adaptive
model WITHOUT look-ahead bias.

**Why this matters to us:** We DEFERRED adaptive learning (the OGD layer) precisely
because (a) it would contaminate the base-strategy validation, and (b) backtesting
an adaptive model honestly is hard (easy to leak future data into the retrain). If
we ever revisit adaptive learning post-soak, FreqAI is the best open-source
reference for how to backtest periodic retraining without look-ahead — they solved
the exact hard problem we'd face.

**Their relevant features:**
- Walk-forward retraining emulation in backtest
- Outlier detection / removal on training data
- PCA dimensionality reduction
- Crash resilience (models stored to disk, reload on restart)
- "Realistic backtesting" that automates retraining over the historic window

**Their own warning (important):** their example strategy is explicitly "not for
production" — it's a feature showcase. And ML forecasting of chaotic markets is
notoriously hard; FreqAI is a sandbox, not a free edge.

**Action:** `[POST-SOAK]` — only after the base frozen Config 14 proves a real
forward edge. If we revisit adaptive learning, study FreqAI's walk-forward
retraining backtest methodology FIRST (it's the honest way to avoid the look-ahead
trap). Do NOT enable any adaptive layer during the current soak.

---

## 7. Recursive-formula bias check — `[NOW]`

**What Freqtrade does:** A `recursive-analysis` command checks for indicators whose
value at a candle depends on how much history was loaded (e.g. indicators that
haven't "warmed up" produce different values depending on the start point). This is
a subtle correctness bug: the same candle gets different indicator values depending
on the backtest window.

**Why this matters to us:** Our backtest runs at 90d / 365d / 720d windows. If any
of our indicators (MSS detection, FVG/OB confluence, the structural SL anchor) are
sensitive to how much warm-up history was loaded, the same signal could resolve
differently across windows. We saw avg_R shift slightly across windows
(+0.616 → +0.582 → +0.564 for TF_A) — most of that is sample composition, but a
recursive/warm-up sensitivity could contribute. Worth a one-time check.

**Action:** `[NOW]` — Claude Code can run a read-only check: take a fixed recent
date, compute our engine's indicators/signals using progressively more warm-up
history (e.g. 100 bars vs 500 vs 2000 of lookback), and confirm the signal at that
date is IDENTICAL regardless of warm-up depth. If it drifts, we have a warm-up
sensitivity to document/fix.

---

## 8. Trade-data persistence / custom data on trades — `[POST-SOAK]`

**What Freqtrade does:** `trade.set_custom_data(key, value)` lets a strategy attach
arbitrary data to a trade (e.g. the entry-candle high), persisted across restarts.

**Why this matters to us:** Minor, but: if we want to store per-signal metadata
(the c1_zone_key, the regime at entry, the MSS quality) attached to each trade for
later analysis, this is a clean pattern. We already store some of this in
feature_scores_json. Low priority — we have our own persistence.

**Action:** `[POST-SOAK]` low priority. Our DB already does this; only worth
revisiting if we want richer per-trade metadata for post-hoc analysis.

---

## What NOT to take from Freqtrade

- **Don't adopt their `populate_*` vectorized strategy format.** Our engine is
  bar-walk based and already validated; rewriting into their dataframe-vectorized
  format would reset all validation and risks introducing the very look-ahead bugs
  their own `lookahead-analysis` exists to catch.
- **Don't use their example strategies.** Their docs explicitly say the examples
  are showcases, "not for production."
- **Don't enable FreqAI adaptive retraining as a shortcut.** Same reason we
  deferred our own OGD layer: it contaminates base-strategy validation and is hard
  to backtest honestly. Base edge first.
- **Don't treat ML forecasting as a free edge.** FreqAI is a sandbox for testing
  hypotheses, not a money printer. Chaotic-market forecasting is genuinely hard.

---

## Summary — priority order

| Priority | Item | Tag | Why |
|---|---|---|---|
| 1 | Lookahead-bias methodology (#1) | NOW | Directly addresses the bug-class that bit us twice; read-only |
| 2 | Recursive/warm-up sensitivity check (#7) | NOW | One-time read-only correctness check across our backtest windows |
| 3 | BE-after-TP1 via order_filled + custom_stoploss (#2) | LIVE-HARNESS | Reference impl for the runner-protection we MUST build before Bybit |
| 4 | Stop-on-exchange survivability (#3) | LIVE-HARNESS | Protects runners if VPS dies |
| 5 | Fixed-R stake sizing (#4) | LIVE-HARNESS | We already concluded this is required |
| 6 | Max-concurrent cap + drawdown protection (#5) | LIVE-HARNESS | Correlated-cluster risk we flagged |
| 7 | FreqAI walk-forward retraining backtest (#6) | POST-SOAK | Honest way to backtest adaptive layer IF we revisit it |
| 8 | Trade custom-data persistence (#8) | POST-SOAK | Minor; we mostly have this |

**The two `[NOW]` items (#1 and #7) are the only things worth doing during the
soak — and both are read-only diagnostics that don't touch the running soak or the
exit model.** Everything else is post-soak or live-harness work, to be done only
after the forward edge is proven.
