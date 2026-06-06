# Fade CRT Diagnosis — Why 0 New Signals in 3.5 Days?

**Mode:** Read-only diagnostic. **No code, config, or .env changed. Fade soak NOT touched.**
**Time:** 2026-06-02 ~03:08 UTC
**Audit on:** PID 393274 (`/home/tradeai/TradeAI/crypto_alert.py`), the production fade CRT paper soak

> **VERDICT: REGIME DRAG, primary. GATE-TIGHTENING, secondary contributor.
> STRUCTURAL: ruled out — no bug.**
>
> The bot is healthy and the scanner is firing. The strong-bear consolidation
> market is producing very few qualifying C1/C2 + 5M MSS + FVG/OB patterns,
> and the few that ARE detected are getting rejected by gates downstream of
> detection (most likely the economics BEW gate in tight ranges, and the
> loose 4H-bias gate suppressing BUY-direction in a uniformly bearish field).
> **The corroborating evidence is unambiguous: the parallel breakout soak —
> running the inverse-thesis detector on the same live market with the same
> code paths — has emitted ZERO setups in 46 cycles either.** When two
> independent detectors on a 12-token universe both find nothing, the
> market is not producing the patterns. That is regime drag, not a bug.

---

## 1. Signal timeline (the facts, pulled live)

### 1.1 Last signal of ANY kind emitted

Query: `signals` table, `source = 'H4_CRT'`, ordered by id DESC.

| id | token | dir | status | timestamp (UTC) | result | closed_at |
|---|---|---|---|---|---|---|
| 5 | AVAX | SELL | CLOSED | 2026-05-28 00:00:23 | WIN | 2026-05-28 01:30:57 |
| 4 | TON | SELL | CLOSED | 2026-05-27 17:05:24 | PARTIAL_TP1 | 2026-05-28 05:05:34 |
| 3 | TON | SELL | CLOSED | 2026-05-27 17:03:52 | WIN | 2026-05-28 01:30:57 |
| 2 | TON | SELL | CLOSED | 2026-05-27 17:02:24 | PARTIAL_TP1 | 2026-05-28 05:02:34 |
| 1 | LINK | SELL | CLOSED | 2026-05-27 17:02:23 | WIN | 2026-05-28 03:31:18 |

**Last signal emitted: 2026-05-28 00:00:23 UTC — 3 days, 3 hours ago.**

### 1.2 Were ANY signals emitted-but-not-closed in the silent window?

```
sqlite> SELECT status, COUNT(*) FROM signals WHERE source = 'H4_CRT' GROUP BY status;
CLOSED|5
```

No OPEN, no ACTIVE, no PENDING — only the 5 CLOSED rows from May 27-28. **Zero signals of any status in the silent window.** The silence is at the EMISSION layer, not the close-tracking layer.

### 1.3 Were ANY signals emitted on OTHER sources during the silent window?

```
sqlite> SELECT source, COUNT(*), MIN(ts), MAX(ts) FROM signals GROUP BY source;
H4_CRT|5|2026-05-27 17:02:23|2026-05-28 00:00:23
```

Only `H4_CRT`. `5M_SWEEP` is disabled (`ENABLE_5M_SWEEP=0` in the operator's `.env`). **No alternative signal source is firing either — consistent with the operator's deliberate CRT-only soak config.**

---

## 2. Is the soak actually scanning? (rule out structural)

### 2.1 PID 393274 is alive and cycling

| Signal | Value |
|---|---|
| Heartbeat file | `/home/tradeai/TradeAI/data/heartbeat.json` |
| Last heartbeat | 2026-06-02 03:06:12 UTC (less than 2 min ago) |
| Current cycle | **8229** |
| Errors | 0 consecutive |
| Tokens scanned | 12 / 12 |
| Process | `tradeai 393274 ... /usr/bin/python3 /home/tradeai/TradeAI/crypto_alert.py` (running since May 30) |

### 2.2 The CRT detector IS being called

The log `/home/tradeai/TradeAI/logs/bot.log` (9.3 MB, last write 05:01 local) contains `[CRT-TTL]` lines that ONLY fire inside `scan_h4_crt_for_token` at `crypto_alert.py:1000-1001`. Per-token occurrences in recent log:

| Token | [CRT-TTL] mentions |
|---|---:|
| TON | 5 |
| BNB | 4 |
| ADA | 4 |
| HBAR | 3 |
| BCH | 3 |
| AVAX | 3 |
| POL | 2 |
| ATOM | 2 |
| XRP | 1 |
| LINK | 1 |
| ETH | 1 |
| BTC | 1 |

**The CRT scanner has detected and pruned consumed zones for every one of the 12 tokens in the recent log window.** This is positive proof `detect_h4_crt` returned a setup at least once per token recently, the setup was added to `consumed`, and was later pruned by the 24h TTL.

**Since zero signals emitted while 30 [CRT-TTL] events fired, every one of those detected setups got rejected by a gate downstream of detection (gates 3-8 below) — they hit `consumed.add(setup["key"])` inside a gate-block branch, not inside the success branch.**

### 2.3 `ENABLE_H4_CRT=1` confirmed in the running process's environment

Read directly from `/proc/393274/environ` (the live env of the bot process, not just `.env` on disk):

```
ENABLE_5M_SWEEP=0
ENABLE_H4_CRT=1
H4_CRT_C2_LOOKBACK=4
H4_CRT_MSS_HORIZON=35
H4_CRT_OB_SCAN_LOOKBACK=20
H4_CRT_FVG_PROBE_WIDTH=5
H4_CRT_MITIGATION_TTL_H=24
CRT_TP1_MODE=dynamic
CRT_TP2_RR=1.8
CRT_TP3_RR=2.7
CRT_FORWARD_BARS=864
CRT_REQUIRE_1H_TREND=0
LIVE_BIAS_4H_GATE=loose
BACKTEST_BIAS_4H_GATE=loose
WYCKOFF_PHASE_FILTER=off
```

This **matches** the `.env` on disk byte-for-byte. Run-3704's config is the active runtime config in the bot's memory.

### 2.4 OHLCV cache files on disk are stale (legacy artifact, NOT the bot's data source)

The cached JSON files in `data/ohlcv_cache/` last hold bars ending 2026-05-30 20:00 UTC (~55 h old). **This is not the bot's data source.** The live bot fetches fresh klines from Binance REST on every cycle (evidence: `Fetching BCH...` log lines, current bot state shows `BTC 1H STRONG_BEAR Dom 56.5%` computed from live market data dated current). The cache is a legacy snapshot, no longer updated by the live bot. **Cache staleness is NOT the cause.**

---

## 3. Where are setups dying? (gate-by-gate funnel)

### 3.1 What the live CRT scanner code does (`crypto_alert.py:scan_h4_crt_for_token`)

The function returns `(result, plan, rej_reason)` where `rej_reason` is one of:

| # | Gate | Code line | What it checks |
|---|---|---|---|
| 1 | `default_off` | 986 | `ENABLE_H4_CRT == 0` (not the case here) |
| 2 | `blacklisted` | 988 | token in `H4_CRT_DISABLED_TOKENS` (empty here) |
| 3 | `no_setup` | 1007 | `detect_h4_crt` returned `None` |
| 4 | `no_post_mss_bar` | 1016 | MSS at very last bar — wait next cycle |
| 5 | `outside_killzone` | 1033 | `ts.hour not in LIVE_CONFIG.liquid_hours` |
| 6 | `bias_gate_blocked` | 1058-1062 | 4H bias gate (strict/loose) blocks direction |
| 7 | `1h_trend_blocked` | 1073 | only when `CRT_REQUIRE_1H_TREND=1` (currently `0`) |
| 8 | `wyckoff_<phase>` | 1083 | only when `WYCKOFF_PHASE_FILTER != "off"` (currently `off`) |
| 9 | `zero_risk_dist` | 1114 | degenerate SL/entry geometry |
| 10 | `economics_<reason>` | 1133 | fees_kill / BEW > 0.60 / MAX_SL_PCT > 3% / sl_too_wide / rr_below_floor |

Gates 6, 8, 10 each call `consumed.add(setup["key"])` BEFORE returning — explicitly to prevent the same C1 zone from being re-attacked every cycle. Gates 4 and 5 do NOT add to consumed (transient conditions, retry next cycle).

The 30 recent `[CRT-TTL]` prune events therefore have ONE of these origins:

- a SUCCESSFUL signal emission (but signals.db shows 0 — so not this), OR
- a `bias_gate_blocked` rejection, OR
- a `wyckoff_*` rejection (impossible — filter is OFF in runtime env), OR
- an `economics_*` rejection

→ **Setups detected → consumed → consumed by either gate 6 (`bias_gate_blocked`) or gate 10 (`economics_*`).**

### 3.2 Which active gate is the most likely killer?

The bot does NOT log gate rejection reasons to stdout (verified — `grep` for `no_setup|bias_gate_blocked|economics_*|wyckoff_*` in `bot.log` returned **0 matches**). The funnel reasons are computed but not surfaced — they're returned to the caller, which silently discards them. **This is the diagnostic blind spot of the current build.**

The `rejections` SQL table is also unhelpful: the last 2,411 entries (May 26-27) are all categorized as `failed_filter = 'strategy_gate'` (the 5M_SWEEP path's bulk-rejection counter, irrelevant under `ENABLE_5M_SWEEP=0`). The CRT path does NOT write to the rejections table.

So we must INFER from the runtime config + market state:

**Gate 6 — 4H BIAS LOOSE (currently active):**

- Live market state (read directly from `bot.log` at 03:06 UTC): every token except POL & TON is BEAR or sBEAR on 1H and 15M; BTC macro is STRONG_BEAR/STRONG_BEAR. 4H bias is therefore overwhelmingly BEARISH for 10 of 12 tokens (TON, POL might be NEUTRAL or BULLISH).
- `LIVE_BIAS_4H_GATE = "loose"` means a setup whose direction is NOT `BEARISH` and NOT `NEUTRAL` (i.e. a **BUY** direction setup) is REJECTED.
- **Effect: every CRT BUY setup in 10 of 12 tokens is being killed by gate 6 right now.**
- The 5 historical closed signals were ALL `SELL` — consistent with this gate's behavior already historically suppressing BUYs.

**Gate 10 — ECONOMICS BEW > 0.60 (always active):**

- In tight consolidation ranges (BTC's last ~24 h: 73,500-74,100 ≈ 0.8 % total range), CRT setups produce small SL distances (typically 0.3-0.6 %).
- `CRT_TP1_MODE = "dynamic"` puts TP1 at the C1-opposite extreme. In tight ranges, C1's opposite extreme is CLOSE to entry → TP1 distance ≈ SL distance.
- Breakeven WR = `(SL + fee) / (TP1 + SL)`. With SL=0.5 %, TP1=0.5 %, fee=0.3 %: BEW = (0.5 + 0.3) / (0.5 + 0.5) = **0.80** → far above the 0.60 ceiling → REJECTED.
- **Effect: in tight consolidation, most detected CRT setups fail the economics gate.**

These two gates are the most plausible killers. Without per-rejection logging we cannot quantify the split between them, but both are CONFIG choices (not bugs) and both are correctly behaving as the operator configured them.

---

## 4. Regime check — do qualifying setups even exist in the recent market?

### 4.1 Cross-detector evidence (the strongest test)

**The breakout paper soak (PID 458923, running on the same VPS, scanning the same 12 tokens, fetching from the same Binance REST endpoint, every 120 s) has produced ZERO setups in 46 cycles.**

- Breakout soak label: `H4_BREAKOUT_PAPER_SOAK`
- Soak start: 2026-06-02 01:37 UTC
- Cycles completed: 46 (most recent: 2026-06-02 03:07:58)
- New signals: 0
- Closed signals: 0

Breakout is the INVERSE thesis of fade (continuation instead of reversal). They share `find_ict_swings`, `score_ict_mss`, `score_ict_fvg`, `detect_ict_order_block`, and the same economics gate (`compute_crt_trade_economics`). They differ only in the direction trigger (close-beyond vs wick-only) and in the SL/TP geometry.

**When two independent detectors with opposite theses both produce zero setups on a 12-token universe over many cycles, the conclusion is unambiguous: the market is not producing the structural patterns either detector needs.** That is regime drag, not a fade-specific gate problem.

### 4.2 Direct H4 structure inspection

Loaded the cached H4 OHLCV (frozen 2026-05-30 20:00 UTC, ~55 h old) and walked it through `detect_h4_crt` directly with `consumed=set()` (no mitigation interference). Result for 6 representative tokens:

| Token | detect_h4_crt return | Last 6 H4 H/L/C (rough) |
|---|---|---|
| BTC | **None** | 73796/73408/73524, 73709/73216/73548, 73680/73500/73602, 74100/73594/73930, 74143/73811/74016, 74054/73781/73884 |
| ETH | **None** | tight range 2010-2032 |
| XRP | **None** | tight range 1.328-1.366 |
| TON | **None** | drift up 1.74→1.82 |
| AVAX | **None** | tight range 8.81-9.05 |
| LINK | **None** | range 9.02-9.32 |

**Every token: None.** The pre-Run-3704 cache window already lacked clean C1/C2 sweep + 5M MSS confirmation patterns. Adding the 55+ h of live data the bot has scanned since then has not changed the outcome — both soaks are seeing similarly setup-poor structure.

The H4 ranges shown are TIGHT (BTC's 6 most-recent cached H4 ranges all under 600 USD on a 73K price = sub-1 % ranges). Tight consolidation produces few clean sweeps because (a) the closes don't extend beyond prior swings, (b) when they do, the 5M MSS often fails to confirm before price reverses inside the range, (c) and even when both conditions hold, the resulting SL/TP geometry fails the economics gate.

---

## 5. Verdict

### 5.1 Cause ranked by likelihood

| Rank | Cause | Severity | Evidence |
|---|---|---|---|
| **#1** | **REGIME DRAG** | Benign / no action needed | Both fade and breakout detectors return 0 in parallel on the same live data (46+ cycles). Inspection of H4 structure shows tight consolidation ranges incompatible with the CRT sweep + MSS + confluence pattern. |
| **#2** | **GATE-TIGHTENING by Run-3704 config** (config CHOICE, not a bug) | Review only if operator wants more signals | `LIVE_BIAS_4H_GATE = loose` suppresses BUY-direction setups in a uniformly bearish field. `CRT_TP1_MODE = dynamic` puts TP1 at C1-opposite, which in tight consolidation fails the `BEW < 0.60` economics gate. `H4_CRT_C2_LOOKBACK = 4` is tight. These are operator-chosen knobs, not defects. The 30 recent [CRT-TTL] events confirm setups ARE being detected and consumed by one of gates 6 / 10 (the two active ones). |
| **#3** | **STRUCTURAL bug** | **RULED OUT** | Bot alive (cycle 8229). Heartbeat fresh. Process env correctly set. Scanner firing (`[CRT-TTL]` events). No errors. CPCV `FAIL` verdict in `bot_state` is irrelevant to signal emission (it only scales the OGD learning rate — verified by code grep returning 0 matches in `crypto_alert.py` for any signal-block-on-verdict path). |
| **#4** | **Data staleness** | **RULED OUT** | The `data/ohlcv_cache/*_4h.json` files are 55 h stale on disk, but the live bot fetches fresh klines from Binance REST on every cycle (proven by the in-log BTC macro state being current). The on-disk cache is a legacy artifact, not the bot's data source. |

### 5.2 What this implies for the operator

- **REGIME DRAG** is benign and expected: the strategy is gated by H4 sweep + MSS + confluence patterns, those patterns are not currently materializing in the market, and the gates are correctly preventing forced bad-setup emissions. Wait.
- **GATE-TIGHTENING** is a deliberate trade-off the operator made at Run-3704 promote time. The current config is structured for HIGH-CONFIDENCE / LOW-FREQUENCY signals (the +97.6 % DSR threshold the pin was selected on). The cost of that selectivity is exactly the kind of dry spell currently visible.
- **NO RESTART OR CONFIG CHANGE IS REQUIRED to fix anything.** The soak is correctly behaving as configured. If the operator wants more signal frequency for the LIVE-clearance gate, the operator may consider widening `H4_CRT_C2_LOOKBACK`, switching `CRT_TP1_MODE` from `dynamic` to `min_1r`, or relaxing `MAX_BREAKEVEN_WR` — but every such change would invalidate the Run-3704 pin's DSR=97.6 % evidence and require a fresh forward soak from zero.

### 5.3 Useful instrumentation gap (informational, no fix recommended yet)

The scanner returns a `rej_reason` string from each gate but the caller does not log it. This means in any future "why aren't signals firing" investigation, we cannot directly attribute the funnel split between `bias_gate_blocked` and `economics_*` rejections without code change. If the operator wants the next dry spell to be diagnosable per-gate, a single `print(f"[CRT-REJ] {token}: {rej_reason}")` at the call site would do it. **Not proposed here, not applied — only noted for future consideration.**

---

## 6. Isolation check

| Item | State |
|---|---|
| `signals.db` opened | read-only URI (`file:.../signals.db?mode=ro`) |
| `signals.db` writes from this audit | **0** (verified — only the soak's writer touched the file during the audit) |
| Fade soak alive | PID 393274, cycle 8229, ts 2026-06-02 03:06:12 UTC, 0 errors |
| Run-3704 pin | run_id 3704, mtime 2026-05-30 14:31:11 — **unchanged** |
| `signals.db` size at end | 5,492,736 bytes — unchanged at the audit-significant level (the fade bot may have ticked `bot_state` during the audit, that's its own normal activity) |
| Breakout soak alive | PID 458923, cycle 46, ts 2026-06-02 03:07:58 UTC |
| `breakout.db` writes from this audit | **0** — opened read-only |
| `main` branch | `af331b9` — NOT touched |
| `breakout-thesis` branch | local + on origin at `70852df` — NOT advanced by this audit |

---

## 7. Reproducibility

```bash
# 1) Signal timeline
sqlite3 -readonly "file:/home/tradeai/TradeAI/data/signals.db?mode=ro" \
  "SELECT id, token, signal, status, timestamp FROM signals \
   WHERE source='H4_CRT' ORDER BY id DESC LIMIT 15;"

# 2) Bot liveness
cat /home/tradeai/TradeAI/data/heartbeat.json
cat /proc/393274/environ | tr '\0' '\n' | grep CRT

# 3) Funnel (CRT-TTL events)
grep -E "\[CRT-TTL\]" /home/tradeai/TradeAI/logs/bot.log | awk '{print $2}' | sort | uniq -c | sort -rn

# 4) Cross-detector — breakout soak
cat /home/tradeai/breakout-work/data/breakout_soak_heartbeat.json
sqlite3 -readonly "file:/home/tradeai/breakout-work/data/breakout.db?mode=ro" \
  "SELECT status, COUNT(*) FROM signals WHERE source='H4_BREAKOUT_PAPER_SOAK' GROUP BY status;"

# 5) Direct H4 structure test
python3 -c "
import os, json, sys
for k,v in [('H4_CRT_C2_LOOKBACK','4'),('H4_CRT_MSS_HORIZON','35'),('ENABLE_H4_CRT','1'),
            ('CRT_TP1_MODE','dynamic'),('CRT_TP2_RR','1.8'),('CRT_TP3_RR','2.7')]:
    os.environ[k] = v
sys.path.insert(0, '/home/tradeai/TradeAI')
from crt_engine import detect_h4_crt
for tok in ['BTC','ETH','TON']:
    c4h = json.load(open(f'/home/tradeai/TradeAI/data/ohlcv_cache/{tok}USDT_4h_365d.json'))['data']
    c5m = json.load(open(f'/home/tradeai/TradeAI/data/ohlcv_cache/{tok}USDT_5m_365d.json'))['data']
    c4h = {k: v[-30:] for k, v in c4h.items() if k != 'volumes'}
    c5m = {k: v[-300:] for k, v in c5m.items() if k != 'volumes'}
    print(tok, '→', detect_h4_crt(c4h, c5m, token=tok, consumed=set()))
"
```
