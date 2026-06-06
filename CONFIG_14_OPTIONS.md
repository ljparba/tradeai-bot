# CONFIG_14_OPTIONS — current confluence + entry inventory (descriptive only)

**Read-only "what exists right now" inventory** of Config 14 (the breakout engine used by
both paper soaks A=5M/4H and B=5M/1H). NO change, NO tuning, NO recommendation — just the
current configuration as it stands in code. Line cites are `breakout_engine.py` (engine),
`breakout_paper_soak_B.py` (soak/Config 14 lock), `crt_engine.py` (economics gate),
`ict_engine.py` / `config.py` (shared ICT constants).

Soaks A=515231, B=515230 + fade=512666 alive and untouched; signals.db + Run-3704 unchanged.

---

## 1. CONFLUENCE TYPES

`_check_breakout_confluence` ([breakout_engine.py:120-189](breakout_engine.py#L120)) supports
exactly **two** confluence types: **FVG** and **OB**. Logic is **OR with a fixed priority**:

- **FVG is checked first.** If a qualifying FVG is found it returns immediately
  (`{"type":"FVG"}`) — [breakout_engine.py:158-178](breakout_engine.py#L158).
- **OB is the fallback** — only evaluated if no FVG matched
  (`{"type":"OB"}`) — [breakout_engine.py:180-187](breakout_engine.py#L180).
- It is **OR (any one)**. There is **no flag to require both**, and **no flag to use only
  one type** — the FVG-first-then-OB-fallback order is **hardcoded**. A setup needs exactly
  one confluence (whichever fires first); if neither, the setup is rejected (`return None`).

### FVG trigger (what makes it fire)
- Probes 5M bars around the MSS bar: `d` in `[mss_bar - (FVG_PROBE_WIDTH-1) .. mss_bar]`
  → with `H4_BREAKOUT_FVG_PROBE_WIDTH = 3`, that's the 3 bars `mss_bar-2 .. mss_bar`.
- Calls `score_ict_fvg(d, …, max_post_d_bars=H4_BREAKOUT_MSS_HORIZON=30)`
  ([ict_engine.py:330](ict_engine.py#L330)); minimum gap `ICT_FVG_MIN_GAP = 0.001` (0.1% of price).
- Must (a) have `direction == breakout direction`, (b) **not predate the C2 break**
  (`d ≥ sweep_5m_idx` guard, [breakout_engine.py:166](breakout_engine.py#L166)), and
  (c) overlap the continuation zone ([breakout_engine.py:177](breakout_engine.py#L177)).

### OB trigger (what makes it fire)
- One H4 order block is precomputed per call: `detect_ict_order_block(…, lookback=H4_BREAKOUT_OB_SCAN_LOOKBACK=20)`
  ([breakout_engine.py:269](breakout_engine.py#L269)).
- OB detection params (defaults, not overridden by the breakout caller):
  `ICT_OB_MIN_DISPLACEMENT_PCT = 0.015` (displacement body ≥1.5% of price),
  `ICT_OB_OPPOSITE_LOOKBACK = 5` ([ict_engine.py:909-910](ict_engine.py#L909)).
- Accepted only if `ob["direction"] == breakout direction` AND its zone overlaps the
  continuation zone (`order_block_overlaps_range`) — [breakout_engine.py:185-187](breakout_engine.py#L185).

### Continuation ("entry") zone the confluence must overlap
- BUY: `[c1_high, c1_high × 1.02]` (2% headroom above the broken level) — [breakout_engine.py:328-329](breakout_engine.py#L328).
- SELL: `[c1_low × 0.98, c1_low]` (2% band below the broken level) — [breakout_engine.py:380-381](breakout_engine.py#L380).

---

## 2. ENTRY TRIGGER (full signal condition)

`detect_h4_breakout` ([breakout_engine.py:193](breakout_engine.py#L193)) +
`scan_token` ([breakout_paper_soak_B.py:416-455](breakout_paper_soak_B.py#L416)).
A signal requires **all** of the following, in order:

1. **C1/C2 scan** — walk H4 candles most-recent-first, `c2_idx` in
   `[n_h4 - H4_BREAKOUT_C2_LOOKBACK .. n_h4-1]`; `c1 = c2-1`. First valid breakout wins.
   (`H4_BREAKOUT_C2_LOOKBACK = 4`.)
2. **One-shot consumed guard** — `key = (c1_time, round(c1_high,6), round(c1_low,6))`; if
   already consumed, skip ([breakout_engine.py:291-293](breakout_engine.py#L291)).
3. **Not a dual-extreme wick** — reject if C2 engulfs C1 on both sides ([breakout_engine.py:296](breakout_engine.py#L296)).
4. **C2 CLOSED beyond C1 (+buffer)** — committed break, not a wick:
   - BUY: `c2_close > c1_high × (1 + H4_BREAKOUT_CLOSE_BUFFER_PCT)`, buffer `= 0.001`.
   - SELL: `c2_close < c1_low × (1 − 0.001)`.
5. **5M continuation MSS** — `score_ict_mss(sweep_bar=first 5M bar after C2 close, sweep_type="SSL"(BUY-up)/"BSL"(SELL-down), horizon=H4_BREAKOUT_MSS_HORIZON=30)` must be
   `confirmed` ([breakout_engine.py:311-323](breakout_engine.py#L311)). 5M swings from
   `find_ict_swings(n=ICT_SWING_N=2)`. **MSS quality is TAGGED (HIGH/MEDIUM/LOW) but NOT
   gated** — any confirmed MSS is accepted.
6. **Confluence** — FVG OR OB as in §1 ([breakout_engine.py:326-334](breakout_engine.py#L326)).
7. **Entry price** = open of bar `mss_bar + 1` ([breakout_paper_soak_B.py:427](breakout_paper_soak_B.py#L427)).
8. **Staleness (live only)** — skip if the entry bar is > **3600 s** old ([breakout_paper_soak_B.py:431](breakout_paper_soak_B.py#L431)).
9. **SL/TP geometry** (`compute_breakout_sl_tp`, [breakout_engine.py:410](breakout_engine.py#L410)):
   SL = broken level pushed inside by `BREAKOUT_SL_INSIDE_BUFFER_PCT = 0.001`, then floored
   to `MIN_SL_PCT = 0.005` (0.5%); **reject if SL distance > `MAX_SL_PCT = 0.030` (3%)**.
   TPs = entry ± `RR × risk_dist` (fixed cascade, RR = 2.0/3.0/4.0).
10. **Economics / EV gate** (`compute_crt_trade_economics`, [crt_engine.py](crt_engine.py)) —
    rejects (returns None, signal dropped) if **any** of:
    - `sl_pct > MAX_SL_PCT` (3%)
    - `gross_tp1 / |gross_sl| < ICT_MIN_RR_GATE` (**1.3**)
    - `net_tp1 ≤ 0` (friction kills the trade)
    - `breakeven_wr > MAX_BREAKEVEN_WR` (**0.60**)

### Entry options/filters that EXIST in the wider codebase but are OFF / not wired into the breakout path
The breakout engine + soak apply **only** the gates listed above. The following exist in the
shared ICT/CRT/5M-sweep code but are **NOT referenced anywhere in the breakout path**
(0 occurrences in `breakout_paper_soak_B.py`; the single hit in `breakout_engine.py` is a
docstring mention, not active code):

| Filter / toggle | Exists in | Breakout state |
|---|---|---|
| 4H bias gate (`LIVE/BACKTEST_BIAS_4H_GATE`) | CRT / 5M_SWEEP | **not wired in** |
| 1H trend gate (`CRT_REQUIRE_1H_TREND`, `LIVE_TREND_1H_GATE`) | CRT / 5M_SWEEP | **not wired in** |
| Market-regime gate (ADX/efficiency, `market_regime`) | indicators / CRT | **not wired in** |
| MSS min-quality gate (`LIVE_MSS_MIN_QUALITY`) | 5M_SWEEP | **not wired in** (quality tagged only) |
| FVG min-quality gate (`LIVE_FVG_MIN_QUALITY`) | 5M_SWEEP | **not wired in** |
| Wyckoff phase filter (`WYCKOFF_PHASE_FILTER`) | CRT | **not wired in** |
| CRT quality gates (`CRT_APPLY_QUALITY_GATES`) | CRT | **not wired in** |
| SMT divergence gate (`LIVE_SMT_GATE`) | 5M_SWEEP | **not wired in** |
| Session / killzone filter | CRT / 5M_SWEEP | **not wired in** |
| Volume / `vol_ratio` filter | indicators | **not wired in** |
| Dealing-range gate (`LIVE_DEALING_RANGE_GATE`) | 5M_SWEEP | **not wired in** |

(Listed descriptively — this is what exists vs. what the breakout path uses, not a suggestion to enable any of them.)

---

## 3. CONFIG 14 — FULL PARAMETER DUMP (current values)

**Locked in `CONFIG_14` dict** ([breakout_paper_soak_B.py:55-62](breakout_paper_soak_B.py#L55), env-set before engine import; A is identical):

| Param | Config 14 value | engine default |
|---|---|---|
| `H4_BREAKOUT_CLOSE_BUFFER_PCT` | **0.001** | 0.0 |
| `BREAKOUT_TP1_RR` | **2.0** | 1.5 |
| `BREAKOUT_TP2_RR` | **3.0** | 2.5 |
| `BREAKOUT_TP3_RR` | **4.0** | 3.5 |
| `H4_BREAKOUT_C2_LOOKBACK` | **4** | 8 |
| `H4_BREAKOUT_MSS_HORIZON` | **30** | 30 |

**Engine defaults in effect (not overridden by Config 14):**

| Param | Value |
|---|---|
| `H4_BREAKOUT_OB_SCAN_LOOKBACK` | 20 |
| `H4_BREAKOUT_FVG_PROBE_WIDTH` | 3 |
| `BREAKOUT_SL_INSIDE_BUFFER_PCT` | 0.001 |

**Shared ICT / risk constants used by the breakout path:**

| Param | Value | Source |
|---|---|---|
| `MIN_SL_PCT` (SL floor) | 0.005 (0.5%) | config.py:262 |
| `MAX_SL_PCT` (SL ceiling) | 0.030 (3%) | config.py:261 |
| `ICT_MIN_RR_GATE` (EV gate) | 1.3 | ict_engine.py:106 |
| `MAX_BREAKEVEN_WR` (EV gate) | 0.60 | ict_engine.py:85 |
| `ICT_FVG_MIN_GAP` | 0.001 (0.1%) | ict_engine.py:40 |
| `ICT_OB_MIN_DISPLACEMENT_PCT` | 0.015 (1.5%) | ict_engine.py:909 |
| `ICT_OB_OPPOSITE_LOOKBACK` | 5 | ict_engine.py:910 |
| `ICT_SWING_N` (swing pivot lag) | 2 | ict_engine.py:24 |

**Exit model (the frozen post-TP2 model, [breakout_paper_soak_B.py:293-360](breakout_paper_soak_B.py#L293)):**
- 50/50 split exit. Pre-TP1 SL active. TP1 hit → stop to entry (BE). TP2 hit → stop trails to
  TP1 (PARTIAL_TP2_T1 on return to TP1). TP3 → WIN. Outcome window = **48h** forward
  (`expires_at = opened + 2 days`). Tiers: LOSS / PARTIAL_TP1 / PARTIAL_TP2_T1 / PARTIAL_TP2 / WIN / EXPIRED.

**Friction (`TOKEN_RT_COST`, round-trip %; default `ROUND_TRIP_COST_PCT = 0.003`):**
- 0.003 (0.3%): BTC, ETH, BNB, XRP, AVAX, LINK, BCH
- 0.004 (0.4%): ADA, TON, ATOM
- 0.005 (0.5%): POL, HBAR

**Token universe (12, [breakout_paper_soak_B.py:75-76](breakout_paper_soak_B.py#L75)):**
BTC, ETH, XRP, HBAR, AVAX, LINK, BNB, ADA, POL, TON, ATOM, BCH.

**Operational:** entry TF 5m; reference TF 1h (soak B) / 4h (soak A); scan cadence
`CHECK_INTERVAL_SEC = 120`; live staleness cutoff 3600 s.

**Adaptive / OGD:** **not used by the breakout path.** The breakout soak is a pure
detect → economics-gate → paper-track → resolve loop; there is no OGD weight learning or
adaptive confidence scoring wired into Config 14 (OGD belongs to the separate production
CRT/5M system).

---

## 4. WHAT'S AVAILABLE BUT UNUSED (built, not part of Config 14)

Descriptive list of capabilities present in the codebase but **not** wired into the breakout
Config 14 (i.e. already-built vs. net-new):

- **Confluence types beyond FVG/OB:** none additional are wired — the breakout confluence is
  exactly FVG-or-OB. (The wider ICT engine also has SMT divergence, EQH/EQL clusters, iFVG,
  OTE — none used by `_check_breakout_confluence`.)
- **Require-both / single-type confluence flags:** do not exist for breakout (hardcoded OR,
  FVG-first).
- **Quality gates:** MSS min-quality, FVG min-quality, CRT quality gates — all exist
  (5M_SWEEP / CRT) but unused here; breakout tags MSS quality without gating on it.
- **Directional / context gates:** 4H bias, 1H trend, market-regime, Wyckoff phase, session/
  killzone, volume, dealing-range, SMT — all exist in the shared stack, none wired into breakout.
- **TP cap at C1 opposite extreme** (the CRT `CRT_TP1_MODE` dynamic/min_1r logic) exists in
  `crt_engine`, but the breakout path deliberately uses a **fixed RR cascade** (no
  liquidity-pool cap) — `compute_breakout_sl_tp` ignores it.
- **Adaptive OGD weighting / per-template tiers / honest-metrics promotion pipeline** — exist
  in the production system, not part of the breakout soak.

---

**Isolation honored:** read-only inventory; both soaks (A 515231, B 515230) + fade (512666)
alive and untouched; signals.db + Run-3704 pin unchanged; main untouched; branch not pushed.
No change, no tuning, no recommendation. STOP.
