# Type-A Execution-Quality OBSERVATION Logging — Phase C-Breakout

**Date:** 2026-06-05 · **Branch:** `breakout-thesis` (worktree `/home/tradeai/breakout-work`)
**Status:** SHIPPED to both soaks (code committed, NOT pushed/merged). Observation-only.
**Scope:** records a live Bybit order-book execution-quality snapshot at each Config-14
signal. **Zero effect on entries/exits.** NOT a gate. NOT alpha. Hygiene observation to
build a forward, causal dataset for a LATER "would a Type-A gate have helped?" analysis.

---

## 0. What this does (and explicitly does NOT do)

- **Does:** at each new breakout signal, fetch the Bybit public spot order book, compute
  spread / depth / expected-slippage / a pre-registered `would_skip` flag, and log a row
  to a SEPARATE `exec_quality_log` table linked to the trade by `signal_id`.
- **Does NOT:** change entry, exit, geometry, SL/TP, or which signals execute. Config 14 +
  V_ENTRY are byte-for-byte unchanged. Every signal that executed before still executes.
  The `would_skip` flag is **recorded but never consulted** by execution.

Runs in BOTH soaks — A (5M/4H, PID 522562) and B (5M/1H, PID 522561) — observation-only in
both. The production fade soak (512666), `signals.db`, Run-3704, and `main` are untouched.

---

## 1. Logging schema — `exec_quality_log` (new, additive)

Created via `exec_quality.ensure_exec_quality_table()` on soak start. The existing
`signals` / `results` schema is NOT altered.

| Column | Meaning |
|---|---|
| `id` | PK |
| `signal_id` | FK → `signals.id` (links the snapshot to the trade) |
| `soak_label` | `H4_BREAKOUT_PAPER_SOAK` (A) / `..._B` (B) |
| `ts_utc` | order-book capture time (UTC) |
| `token`, `symbol`, `direction` | BTC / BTCUSDT / BUY\|SELL |
| `fetch_status` | `ok` \| `fetch_failed` |
| `fetch_error` | `repr(exc)` when the fetch failed (else NULL) |
| `mid`, `best_bid`, `best_ask` | top of book |
| `spread_pct` | `(ask − bid) / mid × 100` |
| `position_usd` | pre-registered nominal size the metrics are measured at ($5,000) |
| `bid_depth_01pct_usd`, `ask_depth_01pct_usd` | depth within ±0.10% of mid, each side (USD) |
| `bid_depth_025pct_usd`, `ask_depth_025pct_usd` | depth within ±0.25% of mid, each side (USD) |
| `exec_side_depth_01pct_usd` | near-touch depth on the side we'd trade (ask for BUY, bid for SELL) |
| `est_slippage_pct` | VWAP fill vs mid, % — walk the book for `position_usd` |
| `vwap_fill_price` | volume-weighted fill price for the size |
| `filled_fraction` | 1.0 if the visible book fills the size; <1 if it can't |
| `would_skip` | 0/1 — **OBSERVATION ONLY, never acted on** |
| `tripped_rules` | comma-joined: which pre-registered rule(s) tripped |
| `outcome`, `realized_r` | backfilled from `results` (join on `signal_id`) post-resolution |
| `created_at` | row insert time (UTC) |

**Order-book source:** Bybit v5 public spot `/v5/market/orderbook` (50 levels/side, no auth).
Verified reachable from the VPS at ~20–60 ms for all 12 tokens.

---

## 2. Pre-registered Type-A rules (recorded, NEVER acted on)

Coarse, round, from cost-model first principles, **identical across all 12 tokens, NOT
tuned to results** (`exec_quality.py` constants):

| Rule | Threshold | Trips `would_skip` when |
|---|---|---|
| spread | `SPREAD_MAX_PCT = 0.10%` | `spread_pct > 0.10` |
| slippage | `SLIPPAGE_MAX_PCT = 0.15%` | est. slippage for the size `> 0.15` (or book can't fill the size) |
| near-touch depth | `DEPTH_MULT_MIN = 3.0×` | exec-side ±0.10% depth `< 3 × position_usd` (i.e. `< $15,000`) |

**Position-size assumption (stated):** the soak is paper / signal-only with no configured
capital, so a fixed **$5,000 nominal notional** per signal is used as the measurement size
(`NOMINAL_POSITION_USD`, round, same across tokens). It is recorded per-row so a later
analysis can re-derive every metric at any other size without re-fetching.

`would_skip = 1` iff any rule trips; `tripped_rules` records which. This is the flag whose
correlation with outcomes will be tested AFTER N≥30–60 signals accumulate — together with
the **disguise check** (does `would_skip` just track low volume / illiquid tokens rather
than carry independent execution-cost signal?).

---

## 3. Non-intrusiveness — how it's guaranteed

The observe call is placed in `scan_token` **after** the trade row is persisted and the
C1 zone is consumed-marked, immediately before `return True`:

```
sig_id = persist_signal(...)        # trade is durable in `signals` here
consumed.add(setup["key"])          # crash-safe mark
_log("NEW SIGNAL ...")
try:                                 # ← the ONLY added trade-path line
    exec_quality.observe_exec_quality(conn, signal_id=sig_id, ...)
except Exception:                    # belt-and-suspenders (observe never raises anyway)
    _log("exec_quality observe error (non-fatal)")
return True                          # unchanged
```

- **Additive diff:** `git diff` of both soaks = **43 insertions, 0 deletions**. `persist_signal`,
  `resolve_open_signals`, the forward-walk, geometry, gates, and economics are byte-identical.
- **Decoupled backfill:** `outcome`/`realized_r` are filled by a separate `backfill_outcomes()`
  call after `resolve_open_signals()` returns — it JOINs `results` and writes ONLY
  `exec_quality_log`. The resolution code path itself is untouched, so outcomes cannot change.
- **`would_skip` never read by execution:** the trade is already committed before observe runs;
  observe's return value is ignored for any trade decision.

---

## 4. Fetch-failure safety test (the key safety requirement) — PASS

`verify_exec_quality.py` (throwaway temp DB in /tmp; never touches `breakout.db`):

```
[2/3/4] fetch-failure safety + non-intrusiveness
  PASS  fetch failure → observe() returns 'fetch_failed' (no raise)
  PASS  fetch_failed row recorded
  PASS  fetch_failed row has NULL metrics (mid)
  PASS  fetch_failed row links to the trade (signal_id)
  PASS  signals table UNTOUCHED after fetch failure
  PASS  results table UNTOUCHED after fetch failure
  PASS  trade still OPEN (failure did NOT skip/alter trade)
  PASS  would_skip=1 snapshot recorded on success path
  PASS  trade with would_skip=1 STILL persisted unchanged (flag never consulted)
```

A simulated order-book API timeout (`fetch_bybit_orderbook` monkeypatched to raise) →
`observe()` swallows it, logs a `fetch_failed` row with NULL metrics, returns normally; the
`signals`/`results` tables are byte-identical (SHA-256 fingerprints match) and the trade
stays `OPEN`. The fetch uses a **3-second timeout, single attempt** (no retries) so it can
never stall the 120-second cycle. **18/18 checks pass.**

Correctness checks also pass (deep/clean book → no skip; thin book → depth+slippage trip;
0.3% spread book → spread trips; BUY/SELL slippage symmetric).

---

## 5. Live end-to-end (real Bybit, temp DB) — already discriminates by liquidity

```
  BTC  BUY : status=ok  spread=0.00016% slip=0.0001% nearDepth=$399,218 would_skip=0
  ATOM SELL: status=ok  spread=0.05529% slip=0.1676%  nearDepth=$871     would_skip=1 (slippage,depth)
  TON  BUY : status=ok  spread=0.05976% slip=0.0705%  nearDepth=$6,882   would_skip=1 (depth)
```

BTC at $5k size is effectively frictionless (no skip); thin alts (ATOM, TON) trip the
depth/slippage rules. This is the raw signal the later analysis will test for real
predictive value vs the volume-disguise null.

---

## 6. Files & isolation

| File | Change |
|---|---|
| `exec_quality.py` | NEW — fetch + pure `compute_snapshot` + defensive `observe_exec_quality` + `backfill_outcomes` + table DDL |
| `breakout_paper_soak.py` | +22 lines (import, table init, observe call, backfill call) |
| `breakout_paper_soak_B.py` | +21 lines (same four points) |
| `verify_exec_quality.py` | NEW — 18-check safety + correctness suite |

**Isolation honored:** breakout-thesis worktree only · fade soak (512666) untouched ·
`signals.db` / Run-3704 unchanged · `main` untouched · committed to breakout-thesis,
**NOT pushed/merged** · observation-only (zero effect on entries/exits) · separate
`exec_quality_log` table · no DB mutated by this work (tests use /tmp).

---

## 7. Activation note (operator action required)

The two soaks (522562, 522561) are **still running the pre-logging code** — editing the
files does not change a running process. Logging begins only after a graceful restart picks
up the new code, e.g.:

```bash
cd /home/tradeai/breakout-work
kill -TERM "$(cat data/breakout_soak.pid)"    && nohup python3 breakout_paper_soak.py   > logs/breakout_soak.log   2>&1 & echo $! > data/breakout_soak.pid
kill -TERM "$(cat data/breakout_soak_B.pid)"  && nohup python3 breakout_paper_soak_B.py > logs/breakout_soak_B.log 2>&1 & echo $! > data/breakout_soak_B.pid
```

The soaks are restart-safe (consumed-zone set + open signals rebuilt from `breakout.db`),
so a restart loses no state. **I have NOT restarted them** — that is an operator decision,
deferred per the "don't disrupt running soaks" discipline. Until restarted, the feature is
inert (no rows logged); the trade behavior is unchanged either way.

---

## 8. Next step (separate, NOT done here)

After N≥30–60 signals with snapshots accumulate: analyze whether `would_skip=1` correlates
with worse realized R, and run the **disguise check** (partial-correlation vs token volume /
liquidity) to confirm any signal is execution-cost-specific and not just "illiquid token"
re-labeled. Only then consider whether a Type-A gate is justified. **No gating now.**
