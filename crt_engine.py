"""
crt_engine.py — Candle Range Theory (CRT) detection module.

H4 reference candle + 5M entry timeframe per the operator-confirmed spec
in docs/exploration_runs/CRT_RESEARCH_2026_05_27.md (v1).

Architecture:
  - Wyckoff/flexible validation school: LTF (5M) MSS confirmation is
    accepted in lieu of waiting for the H4 C3 close (article author's
    explicit recommendation; allows reuse of ict_engine.detect_ict_mss).
  - Hybrid entry: 5M MSS within sweep window (~30 min after H4 C2 close)
    rather than article-aggressive (immediate at C2 wick) or article-
    conservative (full H4 C3 close ~4 hours later).
  - Confluence: requires (FVG OR Order Block) overlap with the C1 range
    or with the MSS bar's local envelope. Order Block highlighted by the
    Trading Wyckoff article as the PRIMARY confluence (more significant
    than FVG alone).
  - One-shot mitigation per C1 range — first valid touch only.

This module DOES NOT modify ict_engine.py's existing detection logic. It
reuses find_ict_swings, detect_ict_mss, score_ict_fvg, and the new
detect_ict_order_block / order_block_overlaps_range functions.

Env-overridable constants:
  ENABLE_H4_CRT           — master toggle (default 0 = OFF, no signals emitted)
  H4_CRT_DISABLED_TOKENS  — comma-separated blacklist (default empty)
  H4_CRT_C2_LOOKBACK      — H4 bars to scan for sweep candle (default 10)
  H4_CRT_MSS_HORIZON      — 5M bars after H4 sweep for MSS confirmation (default 30)
  H4_CRT_OB_SCAN_LOOKBACK — bars to scan for OB on the H4 candle stream (default 20)

H6 isolation: shared by crypto_alert.py (live) AND backtest.py (backtest)
via the same module — guarantees live/backtest parity by construction.
"""
import bisect as _bisect
import os as _os
from typing import Optional

from ict_engine import (
    ICT_MSS_HORIZON,
    ICT_MIN_RR_GATE,
    MAX_BREAKEVEN_WR,
    find_ict_swings,
    score_ict_mss,
    score_ict_fvg,
    detect_ict_order_block,
    order_block_overlaps_range,
)
# H-NEW-3 fix (audit 2026-05-28): import SL clamps so the CRT path enforces
# the same structural floor/ceiling the 5M_SWEEP path applies in
# compute_ict_trade_plan (ict_engine.py:759, 786). Pre-fix, CRT could emit
# signals with sl_pct > MAX_SL_PCT (e.g. TON #2 SELL: sl_pct=-6.18% vs ceiling 3%).
from config import MIN_SL_PCT, MAX_SL_PCT


def _env_int(name: str, default: int) -> int:
    try:
        return int(_os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_str(name: str, default: str) -> str:
    return _os.environ.get(name, default)


# ── Module constants (env-overridable) ──────────────────────────────────────
ENABLE_H4_CRT = _env_int("ENABLE_H4_CRT", 0) == 1
H4_CRT_DISABLED_TOKENS = {
    t.strip().upper()
    for t in _env_str("H4_CRT_DISABLED_TOKENS", "").split(",")
    if t.strip()
}
H4_CRT_C2_LOOKBACK = _env_int("H4_CRT_C2_LOOKBACK", 10)
H4_CRT_MSS_HORIZON = _env_int("H4_CRT_MSS_HORIZON", ICT_MSS_HORIZON)
H4_CRT_OB_SCAN_LOOKBACK = _env_int("H4_CRT_OB_SCAN_LOOKBACK", 20)

# Option S (audit cycle-7 2026-05-27): TP cascade + forward-window constants
# moved from backtest.py to the shared module so the Session 3 live
# integration can import the SAME values via `from crt_engine import ...`.
# Eliminates the live/BT drift risk the LBC auditor flagged at backtest.py:
# 223-232 (constants in wrong module for shared import).
CRT_TP2_RR       = _env_float("CRT_TP2_RR", 1.5)    # TP2 R-multiple extension from entry
CRT_TP3_RR       = _env_float("CRT_TP3_RR", 2.0)    # TP3 R-multiple extension from entry
CRT_FORWARD_BARS = _env_int("CRT_FORWARD_BARS", 576)  # 48h CRT outcome window (vs 5M-sweep's 288 = 24h)

# M-CRT-2 plumbing (audit cycle-7 2026-05-27): validation school knob for v2.
# v1 ships "flexible" (Wyckoff) as the only behavior — the strict-school
# branch (requiring C2.close inside C1.range) is added in v2 with an A/B
# backtest comparison. Plumbing the env var NOW so v2 doesn't require a
# main-loop refactor; the constant is currently read but only "flexible"
# is honored. Spec doc §7 v2 row.
H4_CRT_VALIDATION_SCHOOL = _env_str("H4_CRT_VALIDATION_SCHOOL", "flexible").lower()
if H4_CRT_VALIDATION_SCHOOL not in ("flexible", "strict"):
    H4_CRT_VALIDATION_SCHOOL = "flexible"  # safe default on typo

# CRT v2 — Wyckoff phase context filter (audit cycle-7 2026-05-27, Option KK).
# Per the Trading Wyckoff article (CRT_RESEARCH § 7 v2): adding Wyckoff phase
# context to the CRT signal stack pushes WR from the raw 45-50% band to the
# 55-62% band — the single biggest WR booster identified by the article.
#
# Filter modes:
#   off    — preserve v1 behavior (default — no Wyckoff filter applied)
#   loose  — reject only TRANSITION context; allow direction-aligned AND
#            counter-trend (high-risk reversal) setups
#   strict — require direction-aligned Wyckoff context:
#              bullish CRT → ACCUMULATION (Spring) or MARKUP (continuation)
#              bearish CRT → DISTRIBUTION (Upthrust) or MARKDOWN (continuation)
#            Rejects TRANSITION and counter-trend setups.
WYCKOFF_PHASE_FILTER = _env_str("WYCKOFF_PHASE_FILTER", "off").lower()
if WYCKOFF_PHASE_FILTER not in ("off", "loose", "strict"):
    WYCKOFF_PHASE_FILTER = "off"  # safe default on typo

# H4 lookback windows for Wyckoff context detection (~20 days at 4h/bar).
WYCKOFF_H4_LOOKBACK     = _env_int("WYCKOFF_H4_LOOKBACK", 120)
WYCKOFF_H4_MIN_BARS     = _env_int("WYCKOFF_H4_MIN_BARS", 80)
WYCKOFF_RECENT_WINDOW   = _env_int("WYCKOFF_RECENT_WINDOW", 40)
WYCKOFF_CONSOLIDATION_RATIO = _env_float("WYCKOFF_CONSOLIDATION_RATIO", 0.5)
WYCKOFF_RANGE_POSITION_HI   = _env_float("WYCKOFF_RANGE_POSITION_HI", 0.65)
WYCKOFF_RANGE_POSITION_LO   = _env_float("WYCKOFF_RANGE_POSITION_LO", 0.35)
WYCKOFF_TREND_THRESHOLD_PCT = _env_float("WYCKOFF_TREND_THRESHOLD_PCT", 0.02)

# ── CRT Pro v1.1 — "merge best of 5M_SWEEP into CRT" experiment ─────────────
# Discovery from Run #139 analysis (2026-05-27): 52.5% of CRT setups have
# TP1 (= C1 opposite extreme) < 1R from entry, capping per-trade profit
# below 5M_SWEEP's elite tier. These knobs let us empirically test whether
# merging 5M_SWEEP's strict quality + fixed R:R into CRT framework improves
# overall avg_R without crushing signal frequency.
#
# CRT_TP1_MODE — how to compute TP1:
#   dynamic  — TP1 = C1 opposite extreme (article's prescription, current default)
#   fixed_1r — TP1 = entry ± 1R (ignore C1 opposite; uncap upside)
#   min_1r   — TP1 = max(C1 opposite, entry ± 1R) — hybrid (use C1 only when ≥ 1R)
CRT_TP1_MODE = _env_str("CRT_TP1_MODE", "dynamic").lower()
if CRT_TP1_MODE not in ("dynamic", "fixed_1r", "min_1r"):
    CRT_TP1_MODE = "dynamic"  # safe default on typo

# CRT_APPLY_QUALITY_GATES — when 1, require:
#   MSS quality >= CRT_MSS_MIN_QUALITY (default MEDIUM)
#   FVG quality >= CRT_FVG_MIN_QUALITY (default HIGH) when confluence is FVG
#   (OB confluence is binary — exists or doesn't, no quality tier)
# Mirrors 5M_SWEEP's BACKTEST_FVG_MIN_QUALITY=HIGH + BACKTEST_MSS_MIN_QUALITY
# binding gates. Default OFF (preserves v1 CRT permissive behavior).
CRT_APPLY_QUALITY_GATES = _env_int("CRT_APPLY_QUALITY_GATES", 0) == 1
CRT_FVG_MIN_QUALITY     = _env_str("CRT_FVG_MIN_QUALITY", "HIGH").upper()
CRT_MSS_MIN_QUALITY     = _env_str("CRT_MSS_MIN_QUALITY", "MEDIUM").upper()
if CRT_FVG_MIN_QUALITY not in ("LOW", "MEDIUM", "HIGH"):
    CRT_FVG_MIN_QUALITY = "HIGH"
if CRT_MSS_MIN_QUALITY not in ("LOW", "MEDIUM", "HIGH"):
    CRT_MSS_MIN_QUALITY = "MEDIUM"

# CRT_REQUIRE_1H_TREND — when 1, the CRT scanner (in backtest.py /
# crypto_alert.py) applies the same TREND_1H_GATE check used by 5M_SWEEP.
# Read here for documentation + config_hash purposes; the actual gate is
# applied in the caller because crt_engine.py doesn't ingest 1H data.
CRT_REQUIRE_1H_TREND = _env_int("CRT_REQUIRE_1H_TREND", 0) == 1


_QUALITY_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def _quality_meets(actual: str, minimum: str) -> bool:
    """True if `actual` quality tier ≥ `minimum` tier (HIGH > MEDIUM > LOW > NONE)."""
    return _QUALITY_RANK.get(actual, 0) >= _QUALITY_RANK.get(minimum, 0)


def adjust_crt_tp1(direction: str, entry_price: float, sl_price: float,
                    c1_high: float, c1_low: float,
                    mode: Optional[str] = None) -> float:
    """Compute final TP1 price per CRT_TP1_MODE policy.

    Per the Wyckoff article, the CRT theory's natural target is the C1
    opposite extreme (where the swept liquidity comes from). But Run #139
    empirical data shows this caps 52.5% of setups at < 1R reward, dragging
    avg_R down vs 5M_SWEEP's fixed 1R/1.5R/2R cascade. This function lets
    the caller pick between article-faithful (dynamic), profit-uncapped
    (fixed_1r), and hybrid (min_1r) policies via env knob.

    Args:
        direction:    "BUY" or "SELL"
        entry_price:  filled entry (from mss_bar_5m close)
        sl_price:     SL with buffer applied
        c1_high:      C1 candle high (CRH)
        c1_low:       C1 candle low (CRL)
        mode:         override env default (used by tests). None = use env.

    Returns:
        Final TP1 price (always > entry for BUY, < entry for SELL).
    """
    if mode is None:
        mode = CRT_TP1_MODE

    if direction == "BUY":
        c1_opposite = c1_high
        r_distance = entry_price - sl_price  # positive
        fixed_target = entry_price + r_distance
    elif direction == "SELL":
        c1_opposite = c1_low
        r_distance = sl_price - entry_price  # positive
        fixed_target = entry_price - r_distance
    else:
        return c1_high if direction == "BUY" else c1_low  # safe fallback

    if mode == "fixed_1r":
        return fixed_target
    if mode == "min_1r":
        if direction == "BUY":
            return max(c1_opposite, fixed_target)
        return min(c1_opposite, fixed_target)
    # mode == "dynamic" (default)
    return c1_opposite


# ── Helpers ──────────────────────────────────────────────────────────────────
def _find_5m_bar_after(c5m_times, target_time) -> int:
    """Return the index of the first 5M bar whose timestamp > target_time.

    Used to anchor the 5M MSS-confirmation window to the H4 C2 (sweep)
    candle's close. Returns -1 if no later 5M bar exists in the cache.

    L-4 fix (audit cycle-7): O(log N) via bisect.bisect_right on the sorted
    times array (prior O(N) linear scan). Times are expected sorted ascending
    — true for every caller (Binance OHLCV stream + tests).
    """
    n = len(c5m_times)
    if n == 0:
        return -1
    idx = _bisect.bisect_right(c5m_times, target_time)
    return idx if idx < n else -1


def _check_confluence(direction: str, c1_high: float, c1_low: float,
                      mss_bar_5m: int, c5m: dict, ob_cached):
    """Return a confluence dict if EITHER an FVG OR an Order Block overlaps
    the SWEPT-EXTREME ZONE of C1. Otherwise None.

    H-CRT-1 fix (cycle-7 audit 2026-05-27): per the Trading Wyckoff article,
    the OB/FVG confluence is meant to mark the institutional defense zone
    NEAR the swept extreme — not anywhere in C1's full range. For bullish
    CRT (sweep of C1.low), the demand zone is the lower half [c1_low, c1_mid].
    For bearish CRT (sweep of C1.high), the supply zone is [c1_mid, c1_high].

    H-3 fix (cycle-7 audit 2026-05-27): dropped the mss_bar_5m+1 probe — in
    real-time live scanning, the bar AFTER the MSS doesn't exist yet, so
    that probe was reachable only in backtest. Live/backtest parity now
    enforced by symmetry: probe only [mss_bar - 1, mss_bar].

    M-2 fix (cycle-7 audit 2026-05-27): OB is now precomputed by the caller
    (detect_h4_crt) once per scan instead of per CRT candidate. ~10× fewer
    OB scans per cycle when H4_CRT_C2_LOOKBACK = 10.

    direction:    "BUY" or "SELL"
    ob_cached:    pre-computed OB result from detect_ict_order_block on the
                  H4 stream (computed once per detect_h4_crt call), or None
                  if no OB was found within the scan window.
    Returns:
        {"type": "FVG"|"OB", "details": <dict>}  on overlap
        None on no qualifying confluence
    """
    h5 = c5m["highs"]
    l5 = c5m["lows"]
    o5 = c5m["opens"]
    c5 = c5m["closes"]

    # Compute the swept-extreme zone (half of C1 where the manipulation hit)
    c1_mid = (c1_high + c1_low) / 2.0
    if direction == "BUY":
        zone_high, zone_low = c1_mid, c1_low
    else:
        zone_high, zone_low = c1_high, c1_mid

    # 1. Check for FVG near the MSS bar (5M displacement creates FVG).
    #    Probe [mss-1, mss] only — live/backtest parity (H-3 fix).
    if 0 <= mss_bar_5m < len(c5):
        for d in (mss_bar_5m - 1, mss_bar_5m):
            if d < 1 or d + 1 >= len(c5):
                continue
            # L-NEW-1 fix (cycle-9 audit 2026-05-28): cap the FVG mitigation
            # lookahead to H4_CRT_MSS_HORIZON bars past the FVG formation.
            # Bars beyond the MSS confirmation window are post-signal and
            # should not retroactively invalidate the setup. Pre-fix the
            # backtest CRT path passed unbounded c5 → mitigation scanned up
            # to 35 future bars and rejected FVGs the live path (which can
            # only see ~MSS_HORIZON closed bars at signal time) accepted.
            fvg = score_ict_fvg(d, h5, l5, o5, c5,
                                max_post_d_bars=H4_CRT_MSS_HORIZON)
            if fvg is None or fvg["direction"] != direction:
                continue
            # FVG must overlap the swept-extreme zone (H-CRT-1 fix)
            if not (fvg["bottom"] > zone_high or fvg["top"] < zone_low):
                return {"type": "FVG", "details": fvg}

    # 2. Order Block confluence — use the H4-stream OB cached by the caller.
    #    Same swept-extreme overlap constraint (H-CRT-1 fix).
    if ob_cached is not None and ob_cached["direction"] == direction:
        if order_block_overlaps_range(ob_cached, zone_high, zone_low):
            return {"type": "OB", "details": ob_cached}

    return None


# ── Main detection ──────────────────────────────────────────────────────────
def detect_h4_crt(c4h: dict, c5m: dict, token: str = "",
                  consumed: Optional[set] = None) -> Optional[dict]:
    """Detect an H4 Candle Range Theory setup with 5M LTF MSS confirmation.

    Per the Wyckoff/flexible school — the sweep candle's BODY close
    position is NOT the decisive factor. What confirms the setup is the
    subsequent control change, detected here via 5M MSS within
    H4_CRT_MSS_HORIZON bars after C2's close.

    Args:
        c4h: dict with keys 'opens','highs','lows','closes','times' (~30 H4 bars)
        c5m: dict with same keys (~300 5M bars covering the H4 window)
        token: token symbol for blacklist check (case-insensitive)
        consumed: set of (c1_time, round(c1_high,6), round(c1_low,6)) tuples
                  representing C1 ranges already used by a prior signal.
                  Caller mutates the set after generating a signal to mark
                  the range mitigated. None → fresh empty set per call.

                  Thread-safety (M-CRT-8 note): the function reads `consumed`
                  but never mutates it. The caller is responsible for adding
                  the returned `key` to `consumed` after generating a signal
                  AND for guarding concurrent access if multiple scan loops
                  share the same set. The detection function itself is
                  read-only on the consumed set — safe for single-writer
                  serial scan cycles (the standard TradeAI scan pattern).

        Time-unit contract (M-CRT-6 note): `c4h["times"]` and `c5m["times"]`
        must be in the SAME unit (e.g. both UTC unix seconds, or both
        unix milliseconds, or both pd.Timestamp). The function compares
        timestamps directly via `>` between the two arrays — mixed units
        produce silently wrong sweep-anchor offsets. Validated at function
        entry below.

    Returns:
        Signal dict on valid setup, None otherwise.

        {
          "source":          "H4_CRT",
          "type":            "SSL_CRT" | "BSL_CRT",
          "direction":       "BUY" | "SELL",
          "c1_idx":          int,        # H4 bar index of parent candle
          "c1_high":         float,
          "c1_low":          float,
          "c2_idx":          int,        # H4 bar index of sweep candle
          "c2_time":         <time>,     # close time of C2 (for downstream timing)
          "sweep_wick":      float,      # the actual wicked extreme (SL anchor)
          "sweep_5m_idx":    int,        # first 5M bar after C2 close
          "mss_bar_5m":      int,        # 5M bar where MSS confirmed (entry anchor)
          "confluence":      {"type": "FVG"|"OB", "details": dict},
          "tp1":             float,      # opposite extreme of C1 (universal CRT TP)
          "sl":              float,      # below/above C2 wick (universal CRT SL)
          "key":             tuple,      # mitigation key for caller to add to consumed
        }
    """
    if not ENABLE_H4_CRT:
        return None
    if token and token.upper() in H4_CRT_DISABLED_TOKENS:
        return None
    if consumed is None:
        consumed = set()

    # Defensive: required dict shape
    required_keys = {"opens", "highs", "lows", "closes", "times"}
    if not required_keys.issubset(c4h.keys()) or not required_keys.issubset(c5m.keys()):
        return None

    h4_opens = c4h["opens"]
    h4_highs = c4h["highs"]
    h4_lows = c4h["lows"]
    h4_closes = c4h["closes"]
    h4_times = c4h["times"]
    n_h4 = len(h4_closes)
    if n_h4 < 3:
        return None

    c5m_times = c5m["times"]
    c5m_closes = c5m["closes"]
    c5m_opens = c5m["opens"]
    h5 = c5m["highs"]
    l5 = c5m["lows"]
    if len(c5m_closes) < 30:
        return None

    # M-CRT-6 fix (audit cycle-7 2026-05-27): time-unit cross-check. Both
    # arrays must use the SAME orderable type so `>` comparisons work
    # consistently. Compare types of the first elements; bail silently on
    # mismatch (don't crash the live scanner, just skip the cycle).
    try:
        if type(h4_times[0]) is not type(c5m_times[0]):
            return None
    except IndexError:
        return None

    # Build 5M swings once per call (cheap to compute, reused per candidate)
    sh_5m, sl_5m = find_ict_swings(h5, l5)

    # M-2 fix (cycle-7 audit 2026-05-27): pre-compute H4 Order Block ONCE per
    # call instead of per CRT candidate. OB depends only on c4h data — same
    # result for every candidate in this scan cycle.
    ob_cached = detect_ict_order_block(
        h4_opens, h4_highs, h4_lows, h4_closes,
        lookback=H4_CRT_OB_SCAN_LOOKBACK,
    )

    # Walk most-recent H4 candles first — first valid CRT setup wins
    end = n_h4 - 1
    start = max(1, n_h4 - H4_CRT_C2_LOOKBACK)

    for c2_idx in range(end, start - 1, -1):
        c1_idx = c2_idx - 1
        if c1_idx < 0:
            continue

        c1_high = h4_highs[c1_idx]
        c1_low = h4_lows[c1_idx]
        c2_high = h4_highs[c2_idx]
        c2_low = h4_lows[c2_idx]
        c2_time = h4_times[c2_idx]
        c1_time = h4_times[c1_idx]

        # C-CRT-1 fix (cycle-7 audit 2026-05-27): mitigation key uses the C1
        # candle's TIMESTAMP, not its array index. List indices shift the
        # moment the H4 cache rotates (rolling window slides forward), which
        # would silently re-fire signals on the same C1 zone every cycle.
        # Timestamp is stable across cache rotations and matches the universal
        # CRT "one-shot per zone" rule.
        key = (c1_time, round(c1_high, 6), round(c1_low, 6))
        if key in consumed:
            continue

        # M-CRT-1 fix (audit cycle-7 2026-05-27): dual-extreme sweep is
        # ambiguous — a C2 that wicks BOTH below C1.low AND above C1.high
        # (e.g. an extreme-volatility candle) doesn't have a clean
        # directional bias per CRT theory. Skip the candidate; downstream
        # bullish-first short-circuit would otherwise mis-label such bars
        # as BUY signals unconditionally.
        if c2_low < c1_low and c2_high > c1_high:
            continue

        # ── Bullish CRT (SSL sweep of C1.low) ────────────────────────────
        if c2_low < c1_low:
            sweep_5m_idx = _find_5m_bar_after(c5m_times, c2_time)
            if sweep_5m_idx < 0:
                continue
            # C-CRT-2 / H-1 fix (cycle-7 audit 2026-05-27): use score_ict_mss
            # directly (returns confirmed + mss_bar + quality in one call)
            # instead of the previous detect_ict_mss + hand-rolled
            # _approx_mss_bar that could pick a different MSS target level.
            mss = score_ict_mss(
                sweep_bar=sweep_5m_idx,
                closes=c5m_closes,
                opens=c5m_opens,
                highs=h5,
                lows=l5,
                sh=sh_5m,
                sl=sl_5m,
                sweep_type="SSL",
                horizon=H4_CRT_MSS_HORIZON,
            )
            if not mss["confirmed"]:
                continue
            # CRT Pro quality gate (2026-05-27): mirror 5M_SWEEP's MSS quality bar.
            if CRT_APPLY_QUALITY_GATES and not _quality_meets(mss["quality"], CRT_MSS_MIN_QUALITY):
                continue
            mss_bar = mss["mss_bar"]
            confluence = _check_confluence(
                "BUY", c1_high, c1_low, mss_bar, c5m, ob_cached,
            )
            if confluence is None:
                continue
            # CRT Pro quality gate: FVG-confluence path must pass quality bar.
            # OB confluence is binary (no quality tier), so it always passes.
            if CRT_APPLY_QUALITY_GATES and confluence["type"] == "FVG":
                fvg_q = confluence["details"].get("quality", "NONE")
                if not _quality_meets(fvg_q, CRT_FVG_MIN_QUALITY):
                    continue
            return {
                "source":        "H4_CRT",
                "type":          "SSL_CRT",
                "direction":     "BUY",
                "c1_idx":        c1_idx,
                "c1_high":       round(c1_high, 6),
                "c1_low":        round(c1_low, 6),
                "c2_idx":        c2_idx,
                "c2_time":       c2_time,
                "sweep_wick":    round(c2_low, 6),
                "sweep_5m_idx":  sweep_5m_idx,
                "mss_bar_5m":    mss_bar,
                "mss_quality":   mss["quality"],
                "confluence":    confluence,
                "tp1":           round(c1_high, 6),
                "sl":            round(c2_low, 6),
                "key":           key,
            }

        # ── Bearish CRT (BSL sweep of C1.high) ───────────────────────────
        if c2_high > c1_high:
            sweep_5m_idx = _find_5m_bar_after(c5m_times, c2_time)
            if sweep_5m_idx < 0:
                continue
            mss = score_ict_mss(
                sweep_bar=sweep_5m_idx,
                closes=c5m_closes,
                opens=c5m_opens,
                highs=h5,
                lows=l5,
                sh=sh_5m,
                sl=sl_5m,
                sweep_type="BSL",
                horizon=H4_CRT_MSS_HORIZON,
            )
            if not mss["confirmed"]:
                continue
            # CRT Pro quality gate (2026-05-27): mirror 5M_SWEEP's MSS quality bar.
            if CRT_APPLY_QUALITY_GATES and not _quality_meets(mss["quality"], CRT_MSS_MIN_QUALITY):
                continue
            mss_bar = mss["mss_bar"]
            confluence = _check_confluence(
                "SELL", c1_high, c1_low, mss_bar, c5m, ob_cached,
            )
            if confluence is None:
                continue
            # CRT Pro quality gate: FVG-confluence path must pass quality bar.
            if CRT_APPLY_QUALITY_GATES and confluence["type"] == "FVG":
                fvg_q = confluence["details"].get("quality", "NONE")
                if not _quality_meets(fvg_q, CRT_FVG_MIN_QUALITY):
                    continue
            return {
                "source":        "H4_CRT",
                "type":          "BSL_CRT",
                "direction":     "SELL",
                "c1_idx":        c1_idx,
                "c1_high":       round(c1_high, 6),
                "c1_low":        round(c1_low, 6),
                "c2_idx":        c2_idx,
                "c2_time":       c2_time,
                "sweep_wick":    round(c2_high, 6),
                "sweep_5m_idx":  sweep_5m_idx,
                "mss_bar_5m":    mss_bar,
                "mss_quality":   mss["quality"],
                "confluence":    confluence,
                "tp1":           round(c1_low, 6),
                "sl":            round(c2_high, 6),
                "key":           key,
            }

    return None


# ────────────────────────────────────────────────────────────────────────────
# CRT economics + confidence helpers (Session 2 Option H NEW-4 — moved from
# backtest.py so the Session 3 live integration (crypto_alert.py → crt_engine)
# can import them without backwards dependency on backtest.py)
# ────────────────────────────────────────────────────────────────────────────
def compute_crt_trade_economics(direction: str, entry_price: float,
                                 sl_price: float, tp1_price: float,
                                 tp2_price: float, tp3_price: float,
                                 outcome: Optional[str], rt_cost_pct: float) -> Optional[dict]:
    """Compute gross/net P&L %, RR multiples, realized R, and breakeven WR.

    NEW-3 fix (audit cycle-7 Option H 2026-05-27): aligned with
    `compute_ict_trade_plan` conventions used by the 5M-sweep path:
      - 3-decimal rounding on net % values (matches ict_engine.py:816,828,829)
      - Returns None if `net_tp1_pct <= 0` (fees kill the trade)
      - Returns None if breakeven_wr > MAX_BREAKEVEN_WR (= 0.60)

    Option S fix (audit cycle-7 2026-05-27): the None return now also surfaces
    a single-line print via `_REJECT_REASON_*` sentinels in the diagnostic
    layer — see `crt_trade_rejection_reason()` below. The caller's standard
    pattern remains `if econ is None: continue` for success/skip flow, but
    the rejection counter can now record WHICH gate fired by calling
    `crt_trade_rejection_reason(direction, entry, sl, tp1, rt_cost_pct)`
    on the None branch. This splits the previously-opaque
    `crt_economics_gate` counter into `crt_economics_fees_kill` /
    `crt_economics_bew_too_high` / `crt_economics_invalid_inputs` for D2
    diagnostic surfacing.

    `outcome` may be None when called outside the backtest path (e.g. live
    signal preview). In that case `realized_r` is left as None.
    """
    if direction == "BUY":
        gross_tp1 = (tp1_price - entry_price) / entry_price * 100
        gross_tp2 = (tp2_price - entry_price) / entry_price * 100
        gross_tp3 = (tp3_price - entry_price) / entry_price * 100
        gross_sl  = (sl_price  - entry_price) / entry_price * 100
    else:
        gross_tp1 = (entry_price - tp1_price) / entry_price * 100
        gross_tp2 = (entry_price - tp2_price) / entry_price * 100
        gross_tp3 = (entry_price - tp3_price) / entry_price * 100
        gross_sl  = (entry_price - sl_price)  / entry_price * 100

    # H-NEW-3 fix (audit 2026-05-28): structural SL ceiling matching the
    # 5M_SWEEP path (ict_engine.py:759 BUY, :786 SELL). Pre-fix the CRT path
    # could emit |sl_pct| > MAX_SL_PCT — live evidence: TON #2 SELL had
    # sl_pct=-6.18% (>2× the 3% structural ceiling).
    #
    # F-4 fix (ict-logic-validator 2026-05-28): MIN_SL_PCT enforcement moved
    # UPSTREAM to the CRT scan paths (`crypto_alert.py:scan_h4_crt_for_token`
    # and `backtest.py:run_backtest_token_h4_crt`) where the SL is computed
    # — they now WIDEN a too-tight SL to the floor, exactly like
    # compute_ict_trade_plan does for the 5M_SWEEP path. By the time SL
    # reaches this function it's already at-or-above MIN_SL_PCT, so the
    # rejection branch here is removed (it was the source of the
    # asymmetric strictness flagged in F-4).
    sl_pct_abs = abs(gross_sl) / 100.0
    if sl_pct_abs > MAX_SL_PCT:
        return None  # SL too wide — structural risk-management ceiling

    # H-NEW-3 fix: minimum R:R gate mirrors ICT_MIN_RR_GATE = 1.5 used by the
    # 5M_SWEEP path. A TP1 ≥ 1.5× SL distance is the floor for a setup to be
    # economically worth taking once fees are baked in.
    if gross_sl != 0 and (abs(gross_tp1) / abs(gross_sl)) < ICT_MIN_RR_GATE:
        return None

    # 3-decimal rounding on net % — matches compute_ict_trade_plan (ict_engine.py:816)
    net_tp1 = round(gross_tp1 - rt_cost_pct, 3)
    net_tp2 = round(gross_tp2 - rt_cost_pct, 3)
    net_tp3 = round(gross_tp3 - rt_cost_pct, 3)
    net_sl  = round(gross_sl  - rt_cost_pct, 2)  # net_sl is intentionally 2-dp per 5M path

    # NEW-3 gate 1: fees kill the trade
    if net_tp1 <= 0:
        return None

    # Breakeven WR formula = (|sl| + rt_cost) / (tp1_gross + |sl|).
    # Note: matches compute_ict_trade_plan's formula at ict_engine.py:819.
    risk_pct = abs(gross_sl)
    if (gross_tp1 + risk_pct) <= 0:
        return None
    bew = (risk_pct + rt_cost_pct) / (gross_tp1 + risk_pct)

    # NEW-3 gate 2: breakeven WR too high (structurally negative-EV setup)
    if bew > MAX_BREAKEVEN_WR:
        return None

    rr1 = round(abs(gross_tp1 / gross_sl), 2) if gross_sl != 0 else 0
    net_rr1 = round(net_tp1 / abs(net_sl), 2) if net_sl != 0 else 0

    # Realized R-multiple from outcome (None if outcome not provided)
    if outcome == "WIN":
        realized_r = round(net_tp3 / abs(net_sl), 2) if net_sl != 0 else None
    elif outcome == "PARTIAL_TP2":
        realized_r = round(net_tp2 / abs(net_sl), 2) if net_sl != 0 else None
    elif outcome == "PARTIAL_TP1":
        realized_r = round(net_tp1 / abs(net_sl), 2) if net_sl != 0 else None
    elif outcome == "LOSS":
        realized_r = -1.0
    elif outcome == "EXPIRED":
        realized_r = 0.0
    else:
        realized_r = None

    return {
        "gross_tp1":    gross_tp1,
        "gross_tp2":    gross_tp2,
        "gross_tp3":    gross_tp3,
        "gross_sl":     gross_sl,
        "net_tp1":      net_tp1,
        "net_tp2":      net_tp2,
        "net_tp3":      net_tp3,
        "net_sl":       net_sl,
        "rr1":          rr1,
        "net_rr1":      net_rr1,
        "realized_r":   realized_r,
        "breakeven_wr": round(bew, 4),
    }


def crt_trade_rejection_reason(direction: str, entry_price: float,
                                sl_price: float, tp1_price: float,
                                rt_cost_pct: float) -> str:
    """Identify WHICH economics gate caused `compute_crt_trade_economics`
    to return None for a given trade. Used by the backtest scanner to
    split the previously-opaque `crt_economics_gate` rejection counter
    into per-gate counters for D2 diagnostic surfacing.

    Returns one of:
      "fees_kill"          — net_tp1 (gross_tp1 - rt_cost_pct) <= 0
      "bew_too_high"       — breakeven_wr > MAX_BREAKEVEN_WR (= 0.60)
      "invalid_inputs"     — gross_tp1 + risk_pct <= 0 (degenerate input)
      "unknown"            — defensive default; should not occur

    Mirrors the same gate evaluation order as `compute_crt_trade_economics`
    so the first-failing gate is the one reported.

    Option S fix (audit cycle-7 2026-05-27): replaces the opaque None
    return with a structured rejection reason. Caller pattern:

        econ = compute_crt_trade_economics(...)
        if econ is None:
            reason = crt_trade_rejection_reason(direction, entry, sl, tp1, rt_cost)
            rej[f"crt_economics_{reason}"] = rej.get(...) + 1
            continue
    """
    if direction == "BUY":
        gross_tp1 = (tp1_price - entry_price) / entry_price * 100
        gross_sl  = (sl_price  - entry_price) / entry_price * 100
    else:
        gross_tp1 = (entry_price - tp1_price) / entry_price * 100
        gross_sl  = (entry_price - sl_price)  / entry_price * 100

    # H-NEW-3 gates (matches the clamps in compute_crt_trade_economics).
    # F-4 fix (2026-05-28): sl_too_tight no longer emitted from the main
    # function (MIN_SL_PCT widening moved upstream to the CRT scan paths).
    # Branch kept here for back-compat with any historical caller that
    # passes a raw sub-floor SL directly into this rejection helper.
    sl_pct_abs = abs(gross_sl) / 100.0
    if sl_pct_abs > MAX_SL_PCT:
        return "sl_too_wide"
    if sl_pct_abs < MIN_SL_PCT:
        return "sl_too_tight"  # back-compat; unreachable from compute_crt_trade_economics post-F-4
    if gross_sl != 0 and (abs(gross_tp1) / abs(gross_sl)) < ICT_MIN_RR_GATE:
        return "rr_below_floor"

    net_tp1 = round(gross_tp1 - rt_cost_pct, 3)
    if net_tp1 <= 0:
        return "fees_kill"

    risk_pct = abs(gross_sl)
    if (gross_tp1 + risk_pct) <= 0:
        return "invalid_inputs"

    bew = (risk_pct + rt_cost_pct) / (gross_tp1 + risk_pct)
    if bew > MAX_BREAKEVEN_WR:
        return "bew_too_high"

    return "unknown"  # defensive — should not reach here if helper returned None


def crt_quality_to_confidence(mss_quality: str, fvg_quality: str) -> int:
    """Map MSS + FVG quality GRADES (HIGH/MEDIUM/LOW/NONE) to a 1-10
    confidence integer for downstream confidence-stratified analysis.

    NEW-4 fix (audit cycle-7 Option H 2026-05-27): moved from backtest.py
    so the Session 3 live integration can call the same function and produce
    byte-identical confidence values for the same setup.

    Option S fix (audit cycle-7 2026-05-27): docstring rewritten to remove
    drift between the prior text (which described score_ict_mss's internal
    4-5 / 2-3 / 0-1 point scale) and the actual q_score map below (which
    uses a simpler 0/1/2/3 grade-to-points conversion).

    Grade → q_score points (per quality dimension):
      HIGH   = 3
      MEDIUM = 2
      LOW    = 1
      NONE   = 0 (also returned for any unknown grade string)

    Total points (sum of MSS + FVG) → confidence integer:
      pts=0  → 6  (both NONE — typically pure-OB confluence)
      pts=1  → 6
      pts=2  → 7
      pts=3  → 8
      pts=4  → 8
      pts=5  → 9
      pts=6  → 10 (HIGH+HIGH — top-tier setup with both confluences strong)

    Output is clamped to [6, 10] so CRT signals stay above the typical
    5M-sweep confidence floor but carry actual quality info.
    """
    q_score = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}
    pts = q_score.get(mss_quality, 0) + q_score.get(fvg_quality, 0)
    return max(6, min(10, 6 + (pts * 2) // 3))


# ────────────────────────────────────────────────────────────────────────────
# CRT OGD feature scoring (2026-05-27 — closes the adaptive-learning gap)
# ────────────────────────────────────────────────────────────────────────────
#
# BEFORE this helper existed, CRT signals were saved with `feature_scores_json
# = NULL`, which caused `_trigger_weight_update` (in crypto_alert.py) to bail
# out at: `if not fs_json: skip OGD update`. Result: every CRT trade close
# silently failed to update per-token OGD weights — adaptive learning was
# effectively OFF in CRT-only mode (ENABLE_5M_SWEEP=0).
#
# This helper closes that gap by computing the same 6-feature score vector
# the OGD engine expects, derived from data CRT signals already carry. The
# returned dict is JSON-serialisable and gets persisted to
# `signals.feature_scores_json` (live) / `backtest_signals` template_scores
# isn't used here — backtest_signals doesn't have a feature_scores_json
# column at the time of writing, but the live path is the one that drives
# OGD learning; backtests don't update live token_weights.
#
# Design choices:
#   - Reuses adaptive_engine.extract_ict_feature_scores() so the score
#     contract stays in one place (no risk of silent drift between sources).
#   - For CRT, dr_location = "UNKNOWN" (CRT doesn't compute dealing range).
#     This makes the `dr_location` feature contribute its FLOOR weight only —
#     non-zero so renormalisation doesn't inflate other features, but the
#     OGD engine won't learn meaningful dr signal from CRT trades.
#   - FVG quality is "NONE" when the CRT confluence is OB (no FVG present).
#     Same floor-contribution behavior — adaptive engine handles this.
#
# Import is local to the function to avoid a top-of-file circular import
# (adaptive_engine imports from crt_engine indirectly via crypto_alert).
def compute_crt_feature_scores(direction: str,
                                mss_quality: str,
                                fvg_quality: str,
                                confidence: int,
                                session: str,
                                trend_1h: str = "NEUTRAL",
                                dr_location: str = "UNKNOWN") -> dict:
    """Build the 6-feature OGD score vector for a CRT signal.

    Returns the SAME schema as adaptive_engine.extract_ict_feature_scores()
    so the OGD update path doesn't need to branch on signal source.

    Args:
        direction:   "BUY" or "SELL"  (drives sign of trend_strength/dr_location)
        mss_quality: "HIGH"/"MEDIUM"/"LOW"/"NONE"  (from setup["mss_quality"])
        fvg_quality: "HIGH"/"MEDIUM"/"LOW"/"NONE"  (from FVG confluence) or "NONE" for OB
        confidence:  6-10  (from crt_quality_to_confidence())
        session:     "NY_AM_KZ"/"LONDON_KZ"/"ASIA_KZ"/"OVERNIGHT"
        trend_1h:    "STRONG_BULL"/"BULL"/"NEUTRAL"/"BEAR"/"STRONG_BEAR"
                     Default NEUTRAL — only meaningful when caller has 1H data
                     (live path passes the per-token trend; backtest computes
                     via _lookup_trend when CRT_REQUIRE_1H_TREND=1; otherwise
                     NEUTRAL is the honest "we don't know" answer).
        dr_location: "PREMIUM"/"DISCOUNT"/"EQUILIBRIUM"/"UNKNOWN"
                     Default UNKNOWN — CRT scanner doesn't compute dealing range.

    Returns:
        {"fvg_quality": 0.xxx, "mss_quality": 0.xxx, "session": 0.xxx,
         "confidence": 0.xxx, "trend_strength": 0.xxx, "dr_location": 0.xxx}
        Sum equals 1.0 (normalised contributions).
    """
    # Local import — adaptive_engine -> crypto_alert -> crt_engine import chain
    # would create a cycle at module top. The function-scoped import lazily
    # resolves the dependency at first call.
    from adaptive_engine import extract_ict_feature_scores
    return extract_ict_feature_scores(
        signal=direction,
        fvg_quality=fvg_quality,
        mss_quality=mss_quality,
        session=session,
        confidence=confidence,
        trend_1h=trend_1h,
        dr_location=dr_location,
    )


# ────────────────────────────────────────────────────────────────────────────
# CRT v2 — Wyckoff phase context detector (Option KK, audit cycle-7 2026-05-27)
# ────────────────────────────────────────────────────────────────────────────
#
# Per the Trading Wyckoff article (research doc § 7 v2), adding Wyckoff phase
# context to the CRT signal stack is the single biggest WR booster — pushes
# from the raw 45-50% band to 55-62% (per article's calibration table).
#
# Implementation note: Wyckoff phase detection is heuristic, not deterministic
# (the article gives qualitative guidance, not a precise algorithm). This
# implementation uses H4 candle structure to classify a SIMPLIFIED 5-state
# context — sufficient for direction-aligned filtering of CRT setups:
#
#   ACCUMULATION — H4 range at relative LOWS after preceding downtrend or
#                  flat period. Bullish CRT here = textbook Spring setup.
#   DISTRIBUTION — H4 range at relative HIGHS after preceding uptrend or
#                  flat. Bearish CRT here = textbook Upthrust setup.
#   MARKUP       — Clear bullish trend (post-accumulation Phase D/E). Bullish
#                  CRT here = continuation setup.
#   MARKDOWN     — Clear bearish trend (post-distribution Phase D/E). Bearish
#                  CRT here = continuation setup.
#   TRANSITION   — Ambiguous or chaotic (Phase A or early B). Filter all CRT
#                  setups here — Wyckoff teaches "don't trade between phases."
#
# The detector takes raw H4 OHLCV (no precomputed indicators) so it can be
# called from BOTH live (crypto_alert.py:scan_h4_crt_for_token) and backtest
# (backtest.py:run_backtest_token_h4_crt) — same module, same logic, byte-
# identical output for identical inputs.

def detect_wyckoff_context(c4h: dict,
                            lookback: int = None,
                            min_bars: int = None) -> str:
    """Classify the macro Wyckoff context from H4 candle structure.

    Args:
        c4h: dict with 'highs', 'lows', 'closes' arrays. ≥ min_bars required.
        lookback: H4 bars to analyze (default WYCKOFF_H4_LOOKBACK = 120 = ~20 days)
        min_bars: minimum bars required to compute (default 80 = ~13 days)

    Returns:
        One of: "ACCUMULATION", "DISTRIBUTION", "MARKUP", "MARKDOWN", "TRANSITION".
        Returns "TRANSITION" defensively on bad input or insufficient data —
        caller's strict-mode filter rejects this; loose-mode rejects only this.
    """
    if lookback is None:
        lookback = WYCKOFF_H4_LOOKBACK
    if min_bars is None:
        min_bars = WYCKOFF_H4_MIN_BARS

    try:
        closes = c4h["closes"]
        highs = c4h["highs"]
        lows = c4h["lows"]
    except (KeyError, TypeError):
        return "TRANSITION"

    n = len(closes)
    if n < min_bars or len(highs) != n or len(lows) != n:
        return "TRANSITION"

    # Slice the analysis window (most-recent `lookback` bars)
    window_n = min(n, lookback)
    c = closes[-window_n:]
    h = highs[-window_n:]
    l = lows[-window_n:]

    # Macro range over the full window
    range_high = max(h)
    range_low = min(l)
    if range_high <= range_low:
        return "TRANSITION"
    range_width = range_high - range_low
    range_mid = (range_high + range_low) / 2.0
    current = c[-1]
    if current <= 0:
        return "TRANSITION"

    # Position within range (0 = at low, 1 = at high)
    position_ratio = (current - range_low) / range_width
    if position_ratio > WYCKOFF_RANGE_POSITION_HI:
        position = "TOP"
    elif position_ratio < WYCKOFF_RANGE_POSITION_LO:
        position = "BOTTOM"
    else:
        position = "MID"

    # Consolidation vs trending: compare recent sub-window range to full range
    recent_n = min(WYCKOFF_RECENT_WINDOW, window_n)
    recent_h = max(h[-recent_n:])
    recent_l = min(l[-recent_n:])
    recent_range = recent_h - recent_l
    consolidation_ratio = recent_range / range_width if range_width > 0 else 1.0
    is_consolidating = consolidation_ratio < WYCKOFF_CONSOLIDATION_RATIO

    # Trend INTO the range: compare close ~2× recent_n bars ago vs ~recent_n ago.
    # If we don't have enough history, treat as flat (defensive).
    pre_range_idx = -(2 * recent_n)
    range_start_idx = -recent_n
    if abs(pre_range_idx) <= window_n and abs(range_start_idx) <= window_n:
        pre_close = c[pre_range_idx]
        start_close = c[range_start_idx]
        if pre_close > 0:
            change = (start_close - pre_close) / pre_close
            if change > WYCKOFF_TREND_THRESHOLD_PCT:
                pre_range_trend = "UP"
            elif change < -WYCKOFF_TREND_THRESHOLD_PCT:
                pre_range_trend = "DOWN"
            else:
                pre_range_trend = "FLAT"
        else:
            pre_range_trend = "FLAT"
    else:
        pre_range_trend = "FLAT"

    # Classification — consolidating cases
    if is_consolidating:
        if position == "BOTTOM" and pre_range_trend in ("DOWN", "FLAT"):
            # Range at lows after downtrend or flat → Phase B accumulation
            return "ACCUMULATION"
        if position == "TOP" and pre_range_trend in ("UP", "FLAT"):
            # Range at highs after uptrend or flat → Phase B distribution
            return "DISTRIBUTION"
        # Consolidating but ambiguous (e.g., range at MID position)
        return "TRANSITION"

    # Trending cases (range expanded vs recent window)
    if pre_range_trend == "UP" and current > range_mid:
        # Uptrend leading INTO current up-position → markup phase
        return "MARKUP"
    if pre_range_trend == "DOWN" and current < range_mid:
        # Downtrend leading INTO current down-position → markdown phase
        return "MARKDOWN"

    # Default — no clear Wyckoff structure
    return "TRANSITION"


def is_crt_phase_aligned(context: str, direction: str, mode: str = None) -> bool:
    """Determine whether a CRT setup's direction aligns with the current
    Wyckoff context, per the configured WYCKOFF_PHASE_FILTER mode.

    Mode semantics:
      "off"    — always returns True (no filtering applied)
      "loose"  — rejects only TRANSITION context (ambiguous structure)
      "strict" — requires direction-aligned context:
                   BUY  → ACCUMULATION (Spring) or MARKUP (continuation)
                   SELL → DISTRIBUTION (Upthrust) or MARKDOWN (continuation)
                 Rejects TRANSITION and counter-trend setups.
    """
    if mode is None:
        mode = WYCKOFF_PHASE_FILTER
    mode = mode.lower()

    if mode == "off":
        return True
    if mode == "loose":
        return context != "TRANSITION"
    if mode == "strict":
        if direction == "BUY":
            return context in ("ACCUMULATION", "MARKUP")
        if direction == "SELL":
            return context in ("DISTRIBUTION", "MARKDOWN")
        return False
    # Unknown mode — fail-open (preserves prior behavior)
    return True
