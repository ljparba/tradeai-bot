"""
ict_engine.py -- ICT strategy functions and constants.
Extracted from crypto_alert.py. Imports get_trend from indicators.py.

Env-overridable constants (default = current baseline value):
  ICT_SWEEP_LOOKBACK, ICT_MSS_HORIZON, ICT_FVG_MIN_GAP, DEALING_RANGE_LOOKBACK
These are read at module import. Used by the autonomous explorer to inject
trial parameters per backtest without per-trial file edits. Setting any of
these via env affects BOTH live and backtest (parity preserved).
"""
import os as _os

from indicators import get_trend

def _env_int(name: str, default: int) -> int:
    try:    return int(_os.environ[name])
    except (KeyError, ValueError): return default

def _env_float(name: str, default: float) -> float:
    try:    return float(_os.environ[name])
    except (KeyError, ValueError): return default

# ICT Strategy parameters
ICT_SWING_N          = 2       # rollback: P-1b reverted; quality config (Run 60: WR=85.3%, n=34, z=4.53)
ICT_SWEEP_LOOKBACK      = _env_int("ICT_SWEEP_LOOKBACK", 20)   # P-2b baseline (Run 143/168)
ICT_DISP_MAX_LOOK       = 9    # max bars after sweep to find displacement candle (45min)
ICT_MSS_HORIZON         = _env_int("ICT_MSS_HORIZON", 30)      # max bars after sweep for MSS to confirm
ICT_MAX_SETUP_AGE_BARS  = 24   # max bars from sweep detection to signal evaluation (2H on 5M).
                                # ICT: setup is only valid within its originating killzone/session.
                                # A-1 REJECTED: 24→30 causes MSS-before-FVG sequence failures (0 signals).
                                # The age gate prevents evaluating stale setups where MSS already fired before FVG.
ICT_MSS_DISP_MAX_GAP    = 6    # max bars from displacement to MSS confirmation (Fix #10, 2026-05-22).
                                # ICT entry methodology requires FVG to be on/near the MSS displacement bar.
                                # If MSS confirms >6 bars (30min on 5M) after displacement, the FVG is
                                # structurally stale (the displacement didn't promptly break structure).
                                # Allows: M < D (MSS-first), M = D (instant), M = D+1..D+6 (typical CHoCH-via-disp).
                                # Rejects: M > D+6 (slow-grind through structure — weakest ICT pattern).
ENTRY_REACTION_LOOKBACK = 4    # bars of 5M history scanned for FVG entry reaction confirmation.
                                # ICT: reaction must be the 1-3 bars immediately before entry.
ICT_FVG_MIN_GAP      = _env_float("ICT_FVG_MIN_GAP", 0.001)   # min FVG gap as fraction of price (0.1%)
ICT_IFVG_LOOKBACK    = 50      # bars to scan backward for IFVG detection
ICT_5M_IFVG_LOOKBACK = 60      # 5M bars to scan for precision entry iFVG
ICT_IFVG_PROXIMITY_PCT = 0.03  # iFVG midpoint must be within 3% of FVG midpoint to earn confidence bonus
DEALING_RANGE_LOOKBACK = _env_int("DEALING_RANGE_LOOKBACK", 50)  # 4H/1H bars to define active dealing range

# Trade plan constants
MIN_TP1_MULT         = 1.5    # Run #36: reverted 2.0→1.5 — 2.0R killed WR (18% vs 38%), 1.5R+24H untested
# Fix #37 (2026-05-22 cycle 11): MAX_SL_PCT / MIN_SL_PCT migrated to config.py
# with env-var support. Imported here as module-level constants so all existing
# `from ict_engine import MAX_SL_PCT` callers (crypto_alert.py:71, backtest.py:66)
# continue to work unchanged. Single source of truth: config.py.
from config import MAX_SL_PCT, MIN_SL_PCT
ROUND_TRIP_COST_PCT  = 0.003   # 0.10%/side fee + minimal spread — default for liquid pairs (BTC/ETH)
# M15: Per-token RT cost map — accounts for wider bid-ask spread on illiquid alts.
# Exchange fee (0.10%/side) is uniform; the difference is spread paid at fill.
# HBAR/POL carry ~0.10-0.20%/side spread on top of the fee → 0.50% RT realistic.
# Tokens absent from this map fall back to ROUND_TRIP_COST_PCT.
TOKEN_RT_COST: dict = {
    "BTC":  0.003,
    "ETH":  0.003,
    "BNB":  0.003,
    "XRP":  0.003,
    "AVAX": 0.003,
    "LINK": 0.003,
    "ADA":  0.004,
    "POL":  0.005,
    "HBAR": 0.005,
}
MAX_BREAKEVEN_WR     = 0.60    # relaxed - ICT structural SLs are larger
ICT_SL_BUFFER_PCT          = 0.003  # SL placed 0.3% beyond swept wick (structural buffer)
ICT_FVG_SIZE_BONUS_THRESHOLD = 0.003  # FVG must be ≥0.3% of price to earn confidence bonus
ICT_SMT_LOOKBACK           = 8   # bars to scan backward for SMT sweep confirmation
ICT_SMT_REF_HORIZON        = 40  # reference window (bars) to check BTC did not sweep
# 2026-05-28 — env-overridable + lowered default 1.5 → 1.3 per operator decision
# after cycle-9 H-NEW-3 fix cut CRT signal output from ~416 to ~95 (−77%).
# Rationale: 1.5 was calibrated for 5M_SWEEP era (sparse signals, high per-signal
# Sharpe). CRT is a higher-frequency scanner (~10-20× more candidate setups);
# the 1.5 floor was rejecting marginal-but-defensible setups. Lowering to 1.3
# admits setups where TP1 is 1.3× SL distance (still net-positive after fees
# at MAX_BREAKEVEN_WR=0.60). Tuneable via env in case operator wants to push
# back up. Anti-pattern: ≥ 2.0 catastrophic per CLAUDE.md §7.
ICT_MIN_RR_GATE            = _env_float("ICT_MIN_RR_GATE", 1.3)

def find_ict_swings(highs, lows, n=ICT_SWING_N):
    """Confirmed swing highs/lows with n-bar confirmation lag (non-repainting).
    Swing high at i: highs[i] > highs[i-1] AND highs[i] > highs[i+1..i+n].
    Returns (sh, sl) — each a list of (bar_index, level) tuples."""
    sh, sl = [], []
    end = len(highs) - n
    for i in range(1, end):
        if highs[i] > highs[i-1] and all(highs[i] > highs[i+k] for k in range(1, n+1)):
            sh.append((i, highs[i]))
        if lows[i] < lows[i-1] and all(lows[i] < lows[i+k] for k in range(1, n+1)):
            sl.append((i, lows[i]))
    return sh, sl


# ── EQH/EQL clustering (canonical ICT — added 2026-05-22 Fix #9) ─────────
# Two or more swing highs at near-equal price form an EQH cluster — a strong
# BSL pool where retail stops cluster. Same for swing lows / EQL / SSL pool.
# An isolated swing high (no near-equal neighbors) is a WEAKER sweep target
# than a clustered swing high. The cluster_size metadata is consumed by
# detect_ict_sweep → strategy_templates.py for a quality bonus on Tier A/B.
ICT_EQH_TOLERANCE = 0.0015  # 0.15% fractional distance threshold for "equal"

def find_eqh_eql_clusters(sh, sl, tolerance=ICT_EQH_TOLERANCE):
    """Cluster near-equal swing highs and swing lows by price proximity.

    Returns
    -------
    sh_clusters : dict {round(level, 8): cluster_size}
        Map from swing-high level → number of swing highs within ±tolerance.
        cluster_size == 1 means isolated swing high (weak BSL pool).
        cluster_size >= 2 means EQH cluster (strong BSL pool).
    sl_clusters : dict {round(level, 8): cluster_size}
        Same for swing lows / EQL pool.

    Tolerance is fractional vs the cluster midpoint, scaling correctly across
    tokens (0.15% on BTC at $60K ≈ $90; on HBAR at $0.10 ≈ $0.00015).
    """
    def _cluster(swings):
        if not swings:
            return {}
        levels = sorted(lev for _, lev in swings)
        clusters = {}
        for lev in levels:
            if lev <= 0:
                clusters[round(lev, 8)] = 1
                continue
            cnt = sum(1 for l in levels if abs(l - lev) / lev <= tolerance)
            clusters[round(lev, 8)] = cnt
        return clusters
    return _cluster(sh), _cluster(sl)


def detect_ict_sweep(highs, lows, closes, sh, sl, lookback=ICT_SWEEP_LOOKBACK,
                     consumed=None, sh_clusters=None, sl_clusters=None):
    """Scan last `lookback` closed bars (most-recent first) for a BSL or SSL sweep.
    BSL sweep: high > swing_high AND close < swing_high → bearish (SELL signal).
    SSL sweep: low  < swing_low  AND close > swing_low  → bullish (BUY signal).
    Returns first (most-recent) NON-consumed sweep dict or None.

    consumed: optional set of (bar, round(level,6)) tuples already used for signals.
              Pass the same set each call; the caller marks entries consumed after
              a signal is generated. Prevents duplicate signals from the same sweep.

    sh_clusters / sl_clusters: optional dicts from find_eqh_eql_clusters() — when
              provided, the returned sweep dict includes cluster_size (1=isolated,
              2+=EQH/EQL clustered, stronger sweep target per canonical ICT). When
              not provided, cluster_size defaults to 1.
    """
    if consumed is None:
        consumed = set()
    n = len(closes)
    lo = max(0, n - lookback)
    for i in range(n - 1, lo - 1, -1):
        for sh_idx, sh_lev in reversed(sh):
            if sh_idx > i - ICT_SWING_N - 1:
                continue
            if highs[i] > sh_lev and closes[i] < sh_lev:
                key = (i, round(sh_lev, 6))
                if key not in consumed:
                    cs = (sh_clusters or {}).get(round(sh_lev, 8), 1)
                    return {"type":"BSL","level":sh_lev,"bar":i,
                            "sweep_high":highs[i],"sweep_low":lows[i],
                            "cluster_size": cs}
        for sl_idx, sl_lev in reversed(sl):
            if sl_idx > i - ICT_SWING_N - 1:
                continue
            if lows[i] < sl_lev and closes[i] > sl_lev:
                key = (i, round(sl_lev, 6))
                if key not in consumed:
                    cs = (sl_clusters or {}).get(round(sl_lev, 8), 1)
                    return {"type":"SSL","level":sl_lev,"bar":i,
                            "sweep_high":highs[i],"sweep_low":lows[i],
                            "cluster_size": cs}
    return None


def detect_ict_displacement(sweep_bar, opens, highs, lows, closes, sweep_type,
                             max_look=ICT_DISP_MAX_LOOK):
    """Find first displacement candle within max_look bars of sweep_bar (inclusive).
    Bullish disp (after SSL): bullish body ≥ 1.5× avg, body_ratio ≥ 0.55.
    Bearish disp (after BSL): bearish body ≥ 1.5× avg, body_ratio ≥ 0.55.
    Returns displacement bar index or None.
    M6: close-to-close fallback removed — body must be open-to-close; return None if opens unavailable.
    """
    n = len(closes)
    if len(opens) < n:  # M6: opens are required; close-to-close is a fundamentally different measure
        return None
    body_start = max(0, sweep_bar - 20)
    bodies = [abs(closes[j] - opens[j]) for j in range(body_start, sweep_bar) if j > 0]
    avg_body = sum(bodies) / len(bodies) if bodies else 0.0
    if avg_body == 0:
        return None

    # ATR floor: displacement body must be >= 0.4 × ATR(14) of the look-back window.
    # Prevents micro-noise in low-vol consolidation from passing the relative body check
    # (when avg_body itself is tiny, avg_body × 1.5 is also tiny and lets noise through).
    # Internal proxy keeps caller signatures identical — live and backtest pass the same slice.
    _trs = [max(highs[j] - lows[j],
                abs(closes[j] - closes[j - 1]) if j > 0 else 0.0)
            for j in range(body_start, sweep_bar) if j > 0]
    _atr_proxy = sum(_trs[-14:]) / min(14, len(_trs)) if _trs else 0.0
    _ATR_FLOOR = 0.4

    want_bull = (sweep_type == "SSL")
    for j in range(sweep_bar + 1, min(sweep_bar + max_look + 1, n)):
        body = abs(closes[j] - opens[j])
        rng  = highs[j] - lows[j]
        if rng == 0 or body < avg_body * 1.5 or body < _atr_proxy * _ATR_FLOOR:
            continue
        if body / rng < 0.55:
            continue
        is_bull = closes[j] > opens[j]
        if want_bull and is_bull:
            return j
        if not want_bull and not is_bull:
            return j
    return None


def score_ict_mss(sweep_bar, closes, opens, highs, lows, sh, sl, sweep_type,
                  horizon=ICT_MSS_HORIZON):
    """Score MSS quality after a sweep. Returns a quality dict.

    Quality criteria (max 5 pts):
      Timing  — ≤3 bars: 2 pts | ≤6 bars: 1 pt
      Close   — decisive close through level: 2 pts | ok: 1 pt
      Body    — body/range ≥ 0.55 at MSS bar: 1 pt

    quality: "HIGH" (≥4 pts) | "MEDIUM" (2-3 pts) | "LOW" (0-1 pt) | "NONE" (not confirmed)
    """
    _NONE = {"confirmed": False, "quality": "NONE", "mss_bar": None,
             "mss_level": None, "bars_to_mss": None, "score_pts": 0, "reasons": []}
    n = len(closes)

    if sweep_type == "SSL":
        # H2: ICT CHoCH requires breaking the MOST RECENT prior swing high, not the highest one.
        # ICT_SWEEP_LOOKBACK window — keeps MSS scan consistent with sweep detection horizon.
        recent_sh = max(
            (p for p in sh if sweep_bar - ICT_SWEEP_LOOKBACK <= p[0] < sweep_bar),
            key=lambda p: p[0], default=None
        )
        if recent_sh is None:
            return _NONE
        mss_level = recent_sh[1]
        mss_bar = next((j for j in range(sweep_bar + 1, min(sweep_bar + horizon + 1, n))
                        if closes[j] > mss_level), None)
    else:
        # H2: ICT CHoCH requires breaking the MOST RECENT prior swing low, not the lowest one.
        # ICT_SWEEP_LOOKBACK window — keeps MSS scan consistent with sweep detection horizon.
        recent_sl = max(
            (p for p in sl if sweep_bar - ICT_SWEEP_LOOKBACK <= p[0] < sweep_bar),
            key=lambda p: p[0], default=None
        )
        if recent_sl is None:
            return _NONE
        mss_level = recent_sl[1]
        mss_bar = next((j for j in range(sweep_bar + 1, min(sweep_bar + horizon + 1, n))
                        if closes[j] < mss_level), None)

    if mss_bar is None:
        return _NONE

    bars_to_mss = mss_bar - sweep_bar
    pts = 0
    reasons = []

    if bars_to_mss <= 3:
        pts += 2; reasons.append("rapid")
    elif bars_to_mss <= 6:
        pts += 1; reasons.append("medium_speed")

    rng = highs[mss_bar] - lows[mss_bar] if mss_bar < len(highs) else 0
    if rng > 0:
        close_loc = ((closes[mss_bar] - lows[mss_bar]) / rng if sweep_type == "SSL"
                     else (highs[mss_bar] - closes[mss_bar]) / rng)
        if close_loc >= 0.65:
            pts += 2; reasons.append("strong_close")
        elif close_loc >= 0.45:
            pts += 1; reasons.append("ok_close")

    has_opens = len(opens) >= n and mss_bar < len(opens)
    body = abs(closes[mss_bar] - opens[mss_bar]) if has_opens else 0
    if rng > 0 and body > 0 and body / rng >= 0.55:
        pts += 1; reasons.append("displacement_body")

    quality = "HIGH" if pts >= 4 else "MEDIUM" if pts >= 2 else "LOW"
    return {
        "confirmed":   True,
        "quality":     quality,
        "mss_bar":     mss_bar,
        "mss_level":   round(mss_level, 6),
        "bars_to_mss": bars_to_mss,
        "score_pts":   pts,
        "reasons":     reasons,
    }


def detect_ict_mss(sweep_bar, closes, sh, sl, sweep_type, horizon=ICT_MSS_HORIZON):
    """Thin wrapper for backward compatibility — returns bool only."""
    return score_ict_mss(sweep_bar, closes, [], [], [], sh, sl, sweep_type, horizon)["confirmed"]


def score_ict_fvg(d, highs, lows, opens=(), closes=(), max_post_d_bars=None):
    """Score Fair Value Gap quality on 3-bar pattern [d-1, d, d+1].

    Quality criteria (max 3 pts):
      Size       — ≥0.5%: 2 pts | ≥0.2%: 1 pt
      Body       — displacement bar body/range ≥ 0.65: 1 pt
      H4: Freshness removed — age was always 2-4 bars in normal signal flow,
          so it awarded +1 to every FVG and never discriminated quality.

    L-NEW-1 fix (cycle-9 audit 2026-05-28): `max_post_d_bars` caps the
    mitigation lookahead so the backtest CRT path (which can pass slices
    extending up to ~35 bars past the FVG formation point) doesn't reject
    FVGs that the LIVE path — only seeing closed bars up to "now" at signal
    time — would have accepted. Default None preserves the pre-existing
    no-cap behavior used by the live and 5M_SWEEP paths.

    quality: "HIGH" (3 pts = large gap + strong body)
             "MEDIUM" (2 pts = large gap only, or medium gap + strong body)
             "LOW" (0-1 pt)
    Returns None if no valid FVG found.
    """
    if d < 1 or d + 1 >= len(highs):
        return None

    direction = bottom = top = None
    if lows[d+1] > highs[d-1]:
        gap = (lows[d+1] - highs[d-1]) / max(highs[d-1], 1e-10)
        if gap >= ICT_FVG_MIN_GAP:
            direction = "BUY"; bottom = highs[d-1]; top = lows[d+1]
    if direction is None and highs[d+1] < lows[d-1]:
        gap = (lows[d-1] - highs[d+1]) / max(lows[d-1], 1e-10)
        if gap >= ICT_FVG_MIN_GAP:
            direction = "SELL"; bottom = highs[d+1]; top = lows[d-1]
    if direction is None:
        return None

    mid      = (bottom + top) / 2
    # Mitigation check — FVG is consumed once price COMPLETELY fills the gap (ICT standard).
    # Full fill = close on the FAR SIDE of the gap (below bottom for BUY, above top for SELL).
    # The 50%-midpoint threshold was too aggressive: in crypto, price routinely retraces
    # to the midpoint of any gap within 30min (6 5M bars), eliminating nearly all FVGs.
    # "Mitigated" = gap no longer structurally exists; partial fills leave the gap intact.
    if len(closes) > d + 2:
        # L-NEW-1: bound the scan window with max_post_d_bars if caller specified one
        _mit_end = (min(len(closes), d + 2 + max_post_d_bars)
                    if max_post_d_bars is not None else len(closes))
        if direction == "BUY" and any(closes[k] <= bottom for k in range(d + 2, _mit_end)):
            return None
        if direction == "SELL" and any(closes[k] >= top for k in range(d + 2, _mit_end)):
            return None
    size_pct = (top - bottom) / max(bottom, 1e-10) * 100

    pts = 0
    reasons = []

    if size_pct >= 0.5:
        pts += 2; reasons.append("large_gap")
    elif size_pct >= 0.2:
        pts += 1; reasons.append("medium_gap")

    has_opens = len(opens) > d and len(closes) > d
    body_d = abs(closes[d] - opens[d]) if has_opens else 0
    rng_d  = highs[d] - lows[d]
    if rng_d > 0 and body_d > 0 and body_d / rng_d >= 0.65:
        pts += 1; reasons.append("strong_displacement")

    quality = "HIGH" if pts >= 3 else "MEDIUM" if pts >= 2 else "LOW"
    return {
        "direction": direction,
        "bottom":    round(bottom, 6),
        "top":       round(top, 6),
        "mid":       round(mid, 6),
        "size_pct":  round(size_pct, 3),
        "quality":   quality,
        "score_pts": pts,
        "reasons":   reasons,
    }


def detect_ict_fvg(d, highs, lows):
    """Thin wrapper for backward compatibility."""
    return score_ict_fvg(d, highs, lows)


def detect_fvg_entry_reaction(h5, l5, o5, c5, fvg_top, fvg_bottom, direction):
    """Classify 5M entry type when price touches an FVG zone.

    Checks last few 5M candles for a rejection (bullish/bearish reversal body at zone edge).

    Returns dict: entry_type ("ZONE_TOUCH"|"REACTION_CONFIRMED"|"MIDPOINT_RECLAIM").
    """
    n = len(c5)
    if n < 2:
        return {"entry_type": "ZONE_TOUCH"}
    fvg_mid  = (fvg_top + fvg_bottom) / 2
    has_o5   = len(o5) >= n

    for i in range(n - 1, max(n - 5, -1), -1):
        rng  = h5[i] - l5[i]
        if rng <= 0:
            continue
        body = abs(c5[i] - (o5[i] if has_o5 else (c5[i-1] if i > 0 else c5[i])))
        if body / rng < 0.40:
            continue

        if direction == "BUY":
            if l5[i] > fvg_top or h5[i] < fvg_bottom:
                continue
            if c5[i] > (o5[i] if has_o5 else c5[i-1] if i > 0 else c5[i]):  # bullish candle
                return {"entry_type": ("MIDPOINT_RECLAIM" if c5[i] >= fvg_mid
                                       else "REACTION_CONFIRMED")}
        else:
            if h5[i] < fvg_bottom or l5[i] > fvg_top:
                continue
            if c5[i] < (o5[i] if has_o5 else c5[i-1] if i > 0 else c5[i]):  # bearish candle
                return {"entry_type": ("MIDPOINT_RECLAIM" if c5[i] <= fvg_mid
                                       else "REACTION_CONFIRMED")}

    return {"entry_type": "ZONE_TOUCH"}


def get_ict_4h_bias(closes_4h, highs_4h, lows_4h):
    """Non-repainting 4H directional bias: EMA50/200 + swing structure break.
    All inputs must be slices of CLOSED 4H bars only (caller must exclude forming bar).
    Returns 'BULLISH', 'BEARISH', or 'NEUTRAL'."""
    if len(closes_4h) < 200:
        return "NEUTRAL"

    # EMA-based bias using existing get_trend() (EMA50 vs EMA200)
    ema_trend = get_trend(closes_4h)
    if ema_trend in ("STRONG_BULL", "BULL"):
        ema_bias = "BULLISH"
    elif ema_trend in ("STRONG_BEAR", "BEAR"):
        ema_bias = "BEARISH"
    else:
        ema_bias = "NEUTRAL"

    # Swing structure break confirmation (last 30 closed 4H bars, ICT_SWING_N lag)
    swing_bias = "NEUTRAL"
    if len(closes_4h) >= 6:
        _n  = min(len(closes_4h), 30)
        h4  = highs_4h[-_n:]
        l4  = lows_4h[-_n:]
        c4  = closes_4h[-_n:]
        sh, sl = find_ict_swings(h4, l4, n=ICT_SWING_N)
        last_close = c4[-1]
        if sh:
            recent_sh = sh[-1][1]
            if last_close > recent_sh:
                swing_bias = "BULLISH"
        if sl and swing_bias == "NEUTRAL":
            recent_sl = sl[-1][1]
            if last_close < recent_sl:
                swing_bias = "BEARISH"

    # Merge: agreement → use it; EMA alone → use it; swing alone → use it; conflict → NEUTRAL
    if ema_bias == swing_bias:
        return ema_bias
    if ema_bias != "NEUTRAL" and swing_bias == "NEUTRAL":
        return ema_bias
    if ema_bias == "NEUTRAL" and swing_bias != "NEUTRAL":
        return swing_bias
    # Both non-neutral and conflicting → NEUTRAL (structural disagreement)
    return "NEUTRAL"


def compute_dealing_range(highs, lows, price, lookback=DEALING_RANGE_LOOKBACK):
    """Classify price location within the active HTF dealing range.

    Dealing range = most recent confirmed structural swing high (BSL pool) and
    swing low (SSL pool) within `lookback` closed bars, detected via
    find_ict_swings() with ICT_SWING_N confirmation lag.
    Midpoint divides premium (upper half) from discount (lower half).
    A ±5% equilibrium band around the midpoint is marked as EQUILIBRIUM.
    Returns UNKNOWN when no confirmed structural swing exists in either direction.

    Returns dict: range_high, range_low, midpoint, location.
    """
    if len(highs) < 10 or len(lows) < 10:
        return {"range_high": None, "range_low": None,
                "midpoint": None, "location": "UNKNOWN"}
    n = min(len(highs), lookback)
    sh, sl = find_ict_swings(highs[-n:], lows[-n:])
    if not sh or not sl:
        return {"range_high": None, "range_low": None,
                "midpoint": None, "location": "UNKNOWN"}
    # Most recent confirmed structural swing high/low (last by bar index)
    rng_high = sh[-1][1]
    rng_low  = sl[-1][1]
    if rng_high <= rng_low:
        return {"range_high": round(rng_high, 6), "range_low": round(rng_low, 6),
                "midpoint": None, "location": "UNKNOWN"}
    span     = rng_high - rng_low
    if span <= 0:
        return {"range_high": round(rng_high, 6), "range_low": round(rng_low, 6),
                "midpoint": round(rng_high, 6), "location": "EQUILIBRIUM"}
    midpoint = (rng_high + rng_low) / 2
    eq_band  = span * 0.05   # ±5% of range = EQUILIBRIUM zone around midpoint
    if price > midpoint + eq_band:
        location = "PREMIUM"
    elif price < midpoint - eq_band:
        location = "DISCOUNT"
    else:
        location = "EQUILIBRIUM"
    return {
        "range_high": round(rng_high, 6),
        "range_low":  round(rng_low, 6),
        "midpoint":   round(midpoint, 6),
        "location":   location,
    }


def compute_liquidity_targets(
    price, direction, sh_1h_lvl, sl_1h_lvl,
    highs_4h=(), lows_4h=(),
    highs_1h=(), lows_1h=(),
    dr_4h=None, utc_hour=None,
):
    """Build a labeled pool of opposing liquidity levels for TP selection.

    Sources: 1H swing highs/lows, session H/L (from 1H).
    PDH/PDL and DR_MID removed — all showed 0% WR in Run 41 (capped trades before valid targets).

    Returns list of (level, label) sorted by proximity to price:
      BUY  — levels above price, ascending  (nearest first)
      SELL — levels below price, descending (nearest first)
    """
    pool = []

    for lev in sh_1h_lvl:
        pool.append((lev, "1H_SWING_H"))
    for lev in sl_1h_lvl:
        pool.append((lev, "1H_SWING_L"))

    # Session high/low — 1H candles sliced from session open to now.
    # Hours align with adaptive_engine._utc_to_session killzone definitions:
    #   ASIA_KZ  start = 20 UTC
    #   NY_AM_KZ start = 13 UTC
    #   LONDON_KZ start = 02 UTC
    # Previously used (17, 13, 8, 0) — arbitrary anchors that did not match any
    # killzone definition, producing SESSION_H/L from non-session windows. Aligned
    # 2026-05-22 (audit Fix #8) so the SESSION_H/L levels truly reflect liquidity
    # from the most-recent killzone's price range. During OVERNIGHT hours the loop
    # falls through to the last-killzone-start before utc_hour.
    if utc_hour is not None and len(highs_1h) >= 1:
        for sess_start in (20, 13, 2):
            if utc_hour >= sess_start:
                n_bars = min(utc_hour - sess_start + 1, len(highs_1h))
                if n_bars >= 1:
                    pool.append((max(highs_1h[-n_bars:]), "SESSION_H"))
                    pool.append((min(lows_1h[-n_bars:]),  "SESSION_L"))
                break

    # Filter by direction, deduplicate within 0.1%, sort by proximity
    if direction == "BUY":
        candidates = sorted([(l, lb) for l, lb in pool if l > price], key=lambda x: x[0])
    else:
        candidates = sorted([(l, lb) for l, lb in pool if l < price],
                            key=lambda x: x[0], reverse=True)

    deduped = []
    for lev, lbl in candidates:
        if not deduped or abs(lev - deduped[-1][0]) / max(price, 1e-10) > 0.001:
            deduped.append((lev, lbl))

    return deduped


def detect_smt_divergence(sweep_type, ref_h, ref_l, lookback=8, reference_horizon=40,
                          ref_sh_levels=None, ref_sl_levels=None):
    """SMT divergence: token swept a swing; BTC did NOT make the same move.

    C4 fix: uses two separate price-data horizons to define reference structure and test
    confirmation independently. Eliminates the prior_low-within-test-window bug where
    the old code compared BTC to its own recent structure (not a true cross-asset divergence).

    Uses confirmed swing highs/lows (via find_ict_swings) as the reference structure
    instead of raw min/max, preventing noise spikes from establishing false structural levels.
    Falls back to raw min/max when no confirmed swings exist in the reference window.

    reference_horizon (40 bars before test): defines BTC's established structural high/low.
    lookback (8 bars, the confirmation window): tests if BTC held that structure recently.

    BUY  (SSL): BTC low over last `lookback` >= BTC confirmed low from `reference_horizon` bars prior.
    SELL (BSL): BTC high over last `lookback` <= BTC confirmed high from `reference_horizon` bars prior.

    Parameters
    ----------
    sweep_type        : "SSL" or "BSL"
    ref_h, ref_l      : BTC 15M highs/lows (most recent last); needs lookback+reference_horizon bars
    lookback          : confirmation window size in bars (default 8)
    reference_horizon : reference window size in bars before confirmation (default 40)
    ref_sh_levels     : precomputed BTC swing highs [(bar, level)] — optional optimisation
    ref_sl_levels     : precomputed BTC swing lows  [(bar, level)] — optional optimisation

    Returns dict with smt_confirmed (bool), smt_type ("BULLISH"|"BEARISH"|"NONE"), reason.
    """
    _no_data = {"smt_confirmed": False, "smt_type": "NONE", "reason": "insufficient ref data"}
    if len(ref_l) < lookback + 2 or len(ref_h) < lookback + 2:
        return _no_data

    n = len(ref_l)
    conf_start = n - lookback                         # start of confirmation window
    ref_start  = max(0, conf_start - reference_horizon)  # start of reference window

    # Use confirmed swings for reference structure; fall back to raw extremes if none found.
    if ref_sh_levels is None or ref_sl_levels is None:
        _ref_sh, _ref_sl = find_ict_swings(ref_h, ref_l)
    else:
        _ref_sh, _ref_sl = ref_sh_levels, ref_sl_levels

    if sweep_type == "SSL":  # BUY setup
        # Find lowest confirmed swing low in the reference window
        _sl_in_ref = [lv for bar, lv in _ref_sl if ref_start <= bar < conf_start]
        prior_low  = min(_sl_in_ref) if _sl_in_ref else (
            min(ref_l[ref_start:conf_start]) if conf_start > ref_start else ref_l[ref_start])
        recent_min = min(ref_l[-lookback:])
        if recent_min < prior_low:
            return {"smt_confirmed": False, "smt_type": "NONE",
                    "reason": f"BTC also swept SSL ({recent_min:.5f}<prior={prior_low:.5f})"}
        return {"smt_confirmed": True, "smt_type": "BULLISH",
                "reason": f"BTC held low {recent_min:.5f}>=prior={prior_low:.5f}"}
    else:  # SELL setup — BSL sweep
        # Find highest confirmed swing high in the reference window
        _sh_in_ref = [lv for bar, lv in _ref_sh if ref_start <= bar < conf_start]
        prior_high = max(_sh_in_ref) if _sh_in_ref else (
            max(ref_h[ref_start:conf_start]) if conf_start > ref_start else ref_h[ref_start])
        recent_max = max(ref_h[-lookback:])
        if recent_max > prior_high:
            return {"smt_confirmed": False, "smt_type": "NONE",
                    "reason": f"BTC also swept BSL ({recent_max:.5f}>prior={prior_high:.5f})"}
        return {"smt_confirmed": True, "smt_type": "BEARISH",
                "reason": f"BTC held high {recent_max:.5f}<=prior={prior_high:.5f}"}


def detect_ict_ifvg(highs, lows, closes, signal, lookback=None):
    """Scan last `lookback` closed bars for an Inversion Fair Value Gap (IFVG).

    Bullish IFVG (adds BUY confidence):
      A former bearish FVG (highs[d+1] < lows[d-1]) where price later closed above
      the FVG top — the bearish gap was reclaimed, flipping it to support.

    Bearish IFVG (adds SELL confidence):
      A former bullish FVG (lows[d+1] > highs[d-1]) where price later closed below
      the FVG bottom — the bullish gap was violated, flipping it to resistance.

    Strictly non-lookahead: only closed bars [0..n-1] are used.
    Scans backward so the most recent qualifying IFVG is returned first.
    Returns dict with ifvg_present, ifvg_direction, ifvg_top, ifvg_bottom."""
    if lookback is None:
        lookback = ICT_IFVG_LOOKBACK
    n = len(closes)
    _no = {"ifvg_present": False, "ifvg_direction": None,
           "ifvg_top": 0.0, "ifvg_bottom": 0.0, "ifvg_age_bars": 0}
    if n < 4:
        return _no

    start = max(1, n - lookback)

    for d in range(n - 3, start - 1, -1):
        # Need indices d-1, d, d+1, and d+2..n-1 for reclaim check
        if d < 1:
            continue

        if signal == "BUY":
            # Former bearish FVG: highs[d+1] < lows[d-1]
            if highs[d + 1] < lows[d - 1]:
                fvg_bottom = highs[d + 1]
                fvg_top    = lows[d - 1]
                gap = (fvg_top - fvg_bottom) / max(fvg_top, 1e-10)
                if gap < ICT_FVG_MIN_GAP:
                    continue
                # Reclaimed: any subsequent close > fvg_top
                if any(closes[k] > fvg_top for k in range(d + 2, n)):
                    return {"ifvg_present": True, "ifvg_direction": "BUY",
                            "ifvg_bottom":    round(fvg_bottom, 8),
                            "ifvg_top":       round(fvg_top,    8),
                            "ifvg_age_bars":  (n - 1) - d}
        else:
            # Former bullish FVG: lows[d+1] > highs[d-1]
            if lows[d + 1] > highs[d - 1]:
                fvg_bottom = highs[d - 1]
                fvg_top    = lows[d + 1]
                gap = (fvg_top - fvg_bottom) / max(fvg_top, 1e-10)
                if gap < ICT_FVG_MIN_GAP:
                    continue
                # Violated: any subsequent close < fvg_bottom
                if any(closes[k] < fvg_bottom for k in range(d + 2, n)):
                    return {"ifvg_present": True, "ifvg_direction": "SELL",
                            "ifvg_bottom":    round(fvg_bottom, 8),
                            "ifvg_top":       round(fvg_top,    8),
                            "ifvg_age_bars":  (n - 1) - d}
    return _no


def detect_5m_ifvg_entry(highs_5m, lows_5m, closes_5m, fvg_top, fvg_bottom, direction):
    """Find the most recent 5M Inversion FVG within the 15M FVG zone for precision entry.

    For BUY: scans backward for bearish 5M FVGs (gap down: highs[d+1] < lows[d-1])
    that were later reclaimed (price closed above the gap top) AND overlap with the
    15M bullish FVG zone. The reclaimed zone flips to support — that is the iFVG entry.

    For SELL: scans backward for bullish 5M FVGs (gap up: lows[d+1] > highs[d-1])
    that were later violated (price closed below the gap bottom) AND overlap with the
    15M bearish FVG zone. The violated zone flips to resistance — that is the iFVG entry.

    Strictly non-lookahead: all input arrays must be slices of CLOSED 5M bars only.
    Returns entry zone clamped to the 15M FVG zone, or ifvg_5m_found=False if none found."""
    n = len(closes_5m)
    _no = {"ifvg_5m_found": False, "ifvg_5m_top": 0.0, "ifvg_5m_bottom": 0.0}
    if n < 4:
        return _no

    for d in range(n - 3, 0, -1):
        if d < 1 or d + 1 >= n:
            continue

        if direction == "BUY":
            # Bearish 5M FVG: gap DOWN — highs[d+1] < lows[d-1]
            if highs_5m[d + 1] >= lows_5m[d - 1]:
                continue
            gap_bottom = highs_5m[d + 1]
            gap_top    = lows_5m[d - 1]
        else:
            # Bullish 5M FVG: gap UP — lows[d+1] > highs[d-1]
            if lows_5m[d + 1] <= highs_5m[d - 1]:
                continue
            gap_bottom = highs_5m[d - 1]
            gap_top    = lows_5m[d + 1]

        if (gap_top - gap_bottom) / max(gap_top, 1e-10) < ICT_FVG_MIN_GAP:
            continue

        # Must overlap with the 15M FVG zone
        if min(gap_top, fvg_top) <= max(gap_bottom, fvg_bottom):
            continue

        # Reclaim check (non-lookahead: only bars after d+1)
        if direction == "BUY":
            reclaimed = any(closes_5m[k] > gap_top for k in range(d + 2, n))
        else:
            reclaimed = any(closes_5m[k] < gap_bottom for k in range(d + 2, n))
        if not reclaimed:
            continue

        # Clamp entry zone to the 15M FVG boundaries
        entry_top = min(gap_top, fvg_top)
        entry_bot = max(gap_bottom, fvg_bottom)
        if entry_top <= entry_bot:
            continue

        return {"ifvg_5m_found": True,
                "ifvg_5m_top":    round(entry_top, 8),
                "ifvg_5m_bottom": round(entry_bot, 8)}

    return _no


def compute_ict_trade_plan(price, signal, sweep_wick, sh_1h, sl_1h, extra_liq=None, token=""):
    """ICT structural trade plan.
    SL: 0.3% beyond the swept wick (structural — invalidates if retested).
    TP1/TP2: chosen from the nearest valid opposing liquidity levels
             when extra_liq pool is provided (Task 9); else 1H swing fallback.
    TP3: fixed 3R.
    Applies MIN_SL_PCT, MAX_SL_PCT, and BEW gate. Returns plan dict or None.
    token: used to look up TOKEN_RT_COST; defaults to ROUND_TRIP_COST_PCT if absent."""
    if price <= 0 or sweep_wick <= 0:
        return None
    if signal == "BUY":
        sl        = sweep_wick * (1.0 - ICT_SL_BUFFER_PCT)
        sl        = min(sl, price * (1.0 - MIN_SL_PCT))
        if sl <= 0 or (price - sl) / price > MAX_SL_PCT:
            return None
        risk_dist = price - sl
        rr_floor  = price + risk_dist * MIN_TP1_MULT
        if extra_liq:
            tp1 = rr_floor; tp1_label = "RR_FALLBACK"
            for lev, lbl in extra_liq:
                if lev >= rr_floor and lev <= price + risk_dist * 4:
                    tp1 = lev; tp1_label = lbl; break
            tp2 = tp1 + (tp1 - price); tp2_label = "RR_EXTENSION"
            for lev, lbl in extra_liq:
                if lev > tp1:
                    tp2 = lev; tp2_label = lbl; break
        else:
            above = sorted([l for l in sh_1h if l > price])
            if above and above[0] <= price + risk_dist * 4:
                tp1 = max(above[0], rr_floor)
                tp1_label = "1H_SWING_H" if above[0] >= rr_floor else "RR_FALLBACK"
            else:
                tp1 = rr_floor; tp1_label = "RR_FALLBACK"
            above_tp1 = sorted([l for l in sh_1h if l > tp1])
            tp2 = above_tp1[0] if above_tp1 else tp1 + (tp1 - price)
            tp2_label = "1H_SWING_H" if above_tp1 else "RR_EXTENSION"
        tp3 = price + risk_dist * 3.0
    else:
        sl        = sweep_wick * (1.0 + ICT_SL_BUFFER_PCT)
        sl        = max(sl, price * (1.0 + MIN_SL_PCT))
        if (sl - price) / price > MAX_SL_PCT:
            return None
        risk_dist = sl - price
        rr_floor  = price - risk_dist * MIN_TP1_MULT
        if extra_liq:
            tp1 = rr_floor; tp1_label = "RR_FALLBACK"
            for lev, lbl in extra_liq:
                if lev <= rr_floor and lev >= price - risk_dist * 4:
                    tp1 = lev; tp1_label = lbl; break
            tp2 = tp1 - (price - tp1); tp2_label = "RR_EXTENSION"
            for lev, lbl in extra_liq:
                if lev < tp1:
                    tp2 = lev; tp2_label = lbl; break
        else:
            below = sorted([l for l in sl_1h if l < price], reverse=True)
            if below and below[0] >= price - risk_dist * 4:
                tp1 = min(below[0], rr_floor)
                tp1_label = "1H_SWING_L" if below[0] <= rr_floor else "RR_FALLBACK"
            else:
                tp1 = rr_floor; tp1_label = "RR_FALLBACK"
            below_tp1 = sorted([l for l in sl_1h if l < tp1], reverse=True)
            tp2 = below_tp1[0] if below_tp1 else tp1 - (price - tp1)
            tp2_label = "1H_SWING_L" if below_tp1 else "RR_EXTENSION"
        tp3 = price - risk_dist * 3.0

    risk        = abs(price - sl) / price * 100
    rt_cost     = TOKEN_RT_COST.get(token, ROUND_TRIP_COST_PCT) * 100
    def pct(t): return round(((t-price)/price*100 if signal=="BUY" else (price-t)/price*100), 2)
    def rr(t):  return round(abs(pct(t))/risk, 1) if risk > 0 else 0.0
    tp1_gross   = pct(tp1)
    net_tp1_pct = round(tp1_gross - rt_cost, 3)
    if net_tp1_pct <= 0:
        return None
    bew = (risk + rt_cost) / (tp1_gross + risk)
    if bew > MAX_BREAKEVEN_WR:
        return None
    net_rr1 = round(net_tp1_pct / (risk + rt_cost), 2)
    # Cycle 6 Fix #16 (2026-05-22): expose net TP2 and TP3 returns to enable the
    # split-exit P&L model in downstream P&L aggregation. The previous backtest
    # credited every win at TP1's value for the full position, which understated
    # full TP3 wins and overstated PARTIAL_TP1 outcomes (second leg actually
    # exits at breakeven, not at TP1's price).
    net_tp2_pct = round(pct(tp2) - rt_cost, 3)
    net_tp3_pct = round(pct(tp3) - rt_cost, 3)
    return {
        "sl":round(sl,8),"tp1":round(tp1,8),"tp2":round(tp2,8),"tp3":round(tp3,8),
        "sl_pct":round(-risk,2),"tp1_pct":tp1_gross,"tp2_pct":pct(tp2),"tp3_pct":pct(tp3),  # sl_pct is NEGATIVE (e.g. -0.85); use abs(sl_pct) as denominator in R-multiple calculations
        "rr1":rr(tp1),"rr2":rr(tp2),"rr3":rr(tp3),
        "net_tp1_pct":net_tp1_pct,
        "net_tp2_pct":net_tp2_pct,
        "net_tp3_pct":net_tp3_pct,
        "net_sl_pct":round(-(risk+rt_cost),2),
        "net_rr1":net_rr1,"breakeven_wr":round(bew,4),
        "tp1_target_type": tp1_label,
        "tp2_target_type": tp2_label,
        "entry_note":f"ICT FVG retracement | SL below swept {sweep_wick:.5f}",
    }


# ── Order Block detection (CRT v1 confluence — added 2026-05-27) ──────────
# An ICT Order Block (OB) is the LAST opposite-direction candle immediately
# preceding a strong displacement. It marks where institutions absorbed the
# opposite-side flow before initiating the real move — and therefore where
# they are likely to defend on a retest.
#
# Bullish OB:  last BEARISH candle (close < open) before a strong BULLISH
#              displacement. Acts as a demand zone — price expected to bounce
#              UP from this zone on retest.
# Bearish OB:  last BULLISH candle (close > open) before a strong BEARISH
#              displacement. Acts as a supply zone — price expected to reverse
#              DOWN from this zone on retest.
#
# Used by crt_engine.py as a confluence filter alongside FVG: a CRT setup
# qualifies for entry only if the C2 sweep wick (or the MSS bar) overlaps
# with either a fresh FVG or a fresh OB. Per the Trading Wyckoff article,
# the OB is the PRIMARY confluence (more significant than FVG alone) so
# including it materially improves the CRT signal quality stack.
# H-CRT-2 fix (cycle-7 audit 2026-05-27): raised from 0.5% → 1.5% because
# 0.5% is well within H4 crypto ATR noise (~1-2%). Made env-overridable for
# the explorer / Optuna tuning per the project's other env-knob convention
# (cf. ict_engine.py:25, 27, 40, 44 — all env-overridable).
ICT_OB_MIN_DISPLACEMENT_PCT = _env_float("ICT_OB_MIN_DISPLACEMENT_PCT", 0.015)
ICT_OB_OPPOSITE_LOOKBACK    = _env_int("ICT_OB_OPPOSITE_LOOKBACK", 5)


def detect_ict_order_block(opens, highs, lows, closes, lookback=20,
                           min_disp_body_pct=ICT_OB_MIN_DISPLACEMENT_PCT,
                           opposite_lookback=ICT_OB_OPPOSITE_LOOKBACK):
    """Detect the most recent Order Block on the given candle stream.

    Scans the last `lookback` bars (most recent first) for a strong
    displacement candle, then walks back up to `opposite_lookback` bars to
    find the last opposite-direction candle — that candle's range is the OB.

    Args:
        opens, highs, lows, closes: equal-length arrays of candle data
        lookback:           bars from the end to scan for displacement (default 20)
        min_disp_body_pct:  displacement body must be ≥ this fraction of price (default 0.5%)
        opposite_lookback:  max bars before displacement to find opposite candle (default 5)

    Returns:
        dict with the OB metadata or None if no OB found within window.

        {
          "bar_idx":          int,    # index of the OB candle
          "displacement_bar": int,    # index of the displacement candle
          "displacement_pct": float,  # body magnitude as fraction of price
          "top":              float,  # OB candle high (zone ceiling)
          "bottom":           float,  # OB candle low (zone floor)
          "mid":              float,  # midpoint of OB zone
          "direction":        "BUY" | "SELL",  # which CRT direction the OB supports
        }

    A bullish OB (direction="BUY") supports BUY signals — its zone is a
    demand block, so a BUY-side CRT whose sweep wick reaches this zone
    has institutional defense backing the reversal.
    """
    n = len(closes)
    if n < 2 or len(opens) != n or len(highs) != n or len(lows) != n:
        return None
    start = max(1, n - lookback)

    # Walk backward from most recent candle looking for displacement
    for i in range(n - 1, start - 1, -1):
        price = closes[i]
        if price <= 0:
            continue
        body = abs(closes[i] - opens[i])
        if body / price < min_disp_body_pct:
            continue

        is_bullish_disp = closes[i] > opens[i]
        is_bearish_disp = closes[i] < opens[i]

        # Walk back to find last opposite-direction candle.
        # H-CRT-3 fix (cycle-7 audit 2026-05-27): previously broke out of the
        # loop on any same-direction candle, which discarded the real OB
        # whenever a displacement leg spanned more than one bar (e.g.
        # bullish_disp ← bullish ← bullish ← bearish OB ← ...). Per ICT
        # methodology, the OB is the LAST opposite candle BEFORE the move
        # leg began — walking through impulse bars in the same direction is
        # normal. The cap at `opposite_lookback` already bounds the search.
        opp_start = max(0, i - opposite_lookback)
        for j in range(i - 1, opp_start - 1, -1):
            j_bullish = closes[j] > opens[j]
            j_bearish = closes[j] < opens[j]

            if is_bullish_disp and j_bearish:
                # Bullish OB — last bearish candle before bullish move
                return {
                    "bar_idx":          j,
                    "displacement_bar": i,
                    "displacement_pct": round(body / price, 4),
                    "top":              round(highs[j], 6),
                    "bottom":           round(lows[j], 6),
                    "mid":              round((highs[j] + lows[j]) / 2, 6),
                    "direction":        "BUY",
                }
            if is_bearish_disp and j_bullish:
                # Bearish OB — last bullish candle before bearish move
                return {
                    "bar_idx":          j,
                    "displacement_bar": i,
                    "displacement_pct": round(body / price, 4),
                    "top":              round(highs[j], 6),
                    "bottom":           round(lows[j], 6),
                    "mid":              round((highs[j] + lows[j]) / 2, 6),
                    "direction":        "SELL",
                }
            # Continue walking through same-direction candles — they are
            # part of the displacement leg, not a reason to abort. Doji
            # candles (close == open) also continue the search.

    return None


def order_block_overlaps_range(ob, range_high, range_low):
    """True if the OB zone [bottom, top] overlaps the given price range.

    Used by crt_engine.py to confirm OB confluence with a CRT C1 range or
    the MSS bar's high/low envelope.
    """
    if ob is None:
        return False
    return not (ob["bottom"] > range_high or ob["top"] < range_low)
