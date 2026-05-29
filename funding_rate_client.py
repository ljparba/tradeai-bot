"""
funding_rate_client.py — Binance perpetuals funding-rate fetcher (T1.2 / ENHANCEMENT_ROADMAP.md)
================================================================================

WHY THIS EXISTS
---------------
The 8h-funding-rate on perpetual futures is a free contrarian signal. When
funding is extreme positive (>+0.03%), longs are paying shorts heavily, which
historically predicts mean-reversion (good SHORT setup). When extreme negative
(<-0.03%), shorts are paying longs — predicts mean-reversion up (good LONG).

The current CRT scanner doesn't consume this signal. Adding it as a tagged
metadata field opens a new search dimension for the explorer:
  - FUNDING_EXTREME_LONG_THRESH   (e.g., -0.0003)
  - FUNDING_EXTREME_SHORT_THRESH  (e.g., +0.0003)
  - FUNDING_BONUS_PCT             (e.g., 0.05)
  - FUNDING_GATE_ENABLED          (0/1)

ARCHITECTURE
------------
Per ENHANCEMENT_ROADMAP.md T1.2 design: **metadata + tunable overlay**, NOT a
direct OGD feature. Reason: adding to the OGD 6-feature vector would dilute
existing trained weights on AVAX/LINK/TON. Safer path = tag every signal
with funding_rate_pct + funding_extreme flag; let the explorer search over
how to use these via tunable thresholds.

API
---
Binance perpetuals futures endpoint:
  GET https://fapi.binance.com/fapi/v1/premiumIndex
  Returns: [{"symbol": "BTCUSDT", "lastFundingRate": "0.00010000",
             "nextFundingTime": <ms>, ...}, ...]

The funding rate is a fractional 8h rate (0.00010000 = 0.01% per 8h).
Positive = longs pay shorts. Negative = shorts pay longs.

CACHE STRATEGY
--------------
Funding rates update every 8h (Binance settles 00:00, 08:00, 16:00 UTC). No
need to fetch every scan cycle. We cache for 5 minutes — enough to stay fresh
within a settle window without spamming the API.

Falls back gracefully: on fetch failure returns 0.0 (neutral, no bonus) with
an inline log. Bot continues to scan; just doesn't get the funding overlay.

TIME-UNIT CONTRACT
------------------
All funding rates are stored as FLOAT FRACTIONS (0.0001 = 0.01% per 8h).
Display layer multiplies by 100 to show as percent.

USAGE
-----
    from funding_rate_client import get_funding_rate, classify_funding_extreme

    rate = get_funding_rate("BTC")   # → 0.0001 (= +0.01%)
    extreme = classify_funding_extreme(rate, signal_dir="SELL")
    # extreme is one of: "EXTREME_LONG_PAY", "EXTREME_SHORT_PAY",
    #                    "NEUTRAL_LONG_PAY", "NEUTRAL_SHORT_PAY", "FLAT"
"""

from __future__ import annotations

import os
import time
from typing import Dict, Optional

import requests

from config import BINANCE_TOKENS, HEADERS, API_RETRIES, API_DELAY


# ── Binance perpetuals fapi base (different from spot api/v3) ────────────────
BINANCE_FAPI_BASE = "https://fapi.binance.com/fapi/v1"

# ── Cache TTL — funding settles every 8h so 5 min is safe ────────────────────
_CACHE_TTL_SECONDS = 300

# ── Tunable thresholds (env-overridable for explorer search) ─────────────────
# Default thresholds taken from canonical "extreme funding" literature:
# >+0.03% per 8h = longs are paying significantly → SHORT bias
# <-0.03% per 8h = shorts are paying significantly → LONG bias
FUNDING_EXTREME_LONG_THRESH: float = float(
    os.environ.get("FUNDING_EXTREME_LONG_THRESH", "-0.0003")
)
FUNDING_EXTREME_SHORT_THRESH: float = float(
    os.environ.get("FUNDING_EXTREME_SHORT_THRESH", "0.0003")
)
# Confidence bonus when signal direction is counter to extreme funding.
# 0.0 = no effect (gate disabled). 0.05 = +0.5 confidence point bonus.
FUNDING_BONUS_PCT: float = float(os.environ.get("FUNDING_BONUS_PCT", "0.05"))
# Master enable flag — explorer can turn off entirely
FUNDING_GATE_ENABLED: int = int(os.environ.get("FUNDING_GATE_ENABLED", "1"))


# ── Module-level cache ────────────────────────────────────────────────────────
# {token_upper: {"rate": float, "fetched_at": float, "next_funding_ms": int,
#                "available": bool, "fetch_failed": bool}}
# fetch_failed=True means the most recent attempt errored — used to distinguish
# real-NEUTRAL (rate truly within band) from fetch-failure-fallback (rate=0.0
# because /premiumIndex returned no data). Allows downstream code to mark
# signals as `funding_classification = FETCH_FAILED` instead of NEUTRAL.
_FUNDING_CACHE: Dict[str, dict] = {}

# ── Historical funding cache (Stage B, 2026-05-29) ───────────────────────────
# {token_upper: {"rates": list[(ts_ms, rate)], "fetched_at": float}}
# Binance /fundingRate returns settled rates per 8h boundary. We fetch once
# per backtest run (cached for the duration) and binary-search by timestamp
# at signal-evaluation time. limit=1000 returns ~333 days of 8h settles.
_FUNDING_HISTORY_CACHE: Dict[str, dict] = {}
# Max age of historical cache before re-fetch. 1 hour is conservative — a
# backtest run takes ~11 min so cache is fresh within a single run, and the
# next run fetches latest if needed.
_HISTORY_CACHE_TTL_SECONDS = 3600


def _fetch_all_premium_index() -> Optional[list]:
    """Single API call retrieves funding rates for ALL Binance perpetuals.

    Returns the raw response list or None on failure. Caller is responsible
    for caching and error handling.

    The /premiumIndex endpoint is preferred over /fundingRate (history) because
    it returns the CURRENT mark price + next funding time in one call.
    """
    for attempt in range(1, API_RETRIES + 1):
        try:
            r = requests.get(
                f"{BINANCE_FAPI_BASE}/premiumIndex",
                headers=HEADERS, timeout=10,
            )
            # M-CY12-4 fix (audit 2026-05-29 cycle-12): inspect 418/429 BEFORE
            # raise_for_status mirrors spot pattern at crypto_alert.py:2271-2300.
            # fapi shares the same Binance IP rate-limit pool as spot; ignoring
            # 429 here can cascade into a 418 IP ban that takes down BOTH paths.
            _sc = r.status_code
            if _sc == 418:
                print(f"[FUNDING] /premiumIndex: IP BANNED (418) — aborting fetch")
                return None
            if _sc == 429:
                _wait = min(
                    int(getattr(r, 'headers', {}).get("Retry-After", 30)), 60)
                print(f"[FUNDING] /premiumIndex attempt {attempt}: rate limited "
                      f"(429) — sleeping {_wait}s")
                if attempt < API_RETRIES:
                    time.sleep(_wait)
                    continue
                return None
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                # Error body: {"code": ..., "msg": ...}
                code = data.get("code", "?")
                msg = data.get("msg", str(data))[:200]
                print(f"[FUNDING-ERR] /premiumIndex returned HTTP 200 with "
                      f"error body code={code} msg={msg!r}")
                return None
            if not isinstance(data, list):
                print(f"[FUNDING-ERR] unexpected response shape: {type(data)}")
                return None
            return data
        except requests.exceptions.RequestException as e:
            if attempt < API_RETRIES:
                time.sleep(API_DELAY)
                continue
            print(f"[FUNDING-ERR] fetch failed after {API_RETRIES} retries: {e}")
            return None
        except Exception as e:
            print(f"[FUNDING-ERR] unexpected error: {e}")
            return None
    return None


def _refresh_cache_from_api() -> bool:
    """Refresh _FUNDING_CACHE for all configured tokens. Returns True on success."""
    data = _fetch_all_premium_index()
    if not data:
        return False
    now = time.time()
    # Index API response by symbol for O(1) lookup
    by_symbol = {item.get("symbol"): item for item in data
                 if isinstance(item, dict) and item.get("symbol")}
    for token, symbol in BINANCE_TOKENS.items():
        item = by_symbol.get(symbol)
        if item is None:
            # Token not on Binance perpetuals (e.g., maybe a spot-only listing)
            # Cache as 0.0 so caller doesn't repeatedly retry
            _FUNDING_CACHE[token.upper()] = {
                "rate": 0.0, "fetched_at": now, "next_funding_ms": 0,
                "available": False,
            }
            continue
        try:
            rate = float(item.get("lastFundingRate", "0") or "0")
        except (TypeError, ValueError):
            rate = 0.0
        try:
            next_funding = int(item.get("nextFundingTime", "0") or "0")
        except (TypeError, ValueError):
            next_funding = 0
        _FUNDING_CACHE[token.upper()] = {
            "rate": rate, "fetched_at": now, "next_funding_ms": next_funding,
            "available": True, "fetch_failed": False,
        }
    return True


def _mark_all_fetch_failed():
    """Mark every cached token as fetch_failed=True (used when refresh fails)."""
    now = time.time()
    for tok in list(_FUNDING_CACHE.keys()):
        existing = _FUNDING_CACHE[tok]
        existing["fetch_failed"] = True
        existing["fetched_at"] = now
    # Also mark every configured token even if not previously cached.
    for token in BINANCE_TOKENS.keys():
        tok_u = token.upper()
        if tok_u not in _FUNDING_CACHE:
            _FUNDING_CACHE[tok_u] = {
                "rate": 0.0, "fetched_at": now, "next_funding_ms": 0,
                "available": False, "fetch_failed": True,
            }


def is_funding_fetch_failed(token: str) -> bool:
    """Return True if the most recent fetch attempt for this token errored.

    Lets callers distinguish "rate=0.0 because Binance API failed" from
    "rate=0.0 because the actual funding rate IS near zero."
    """
    cached = _FUNDING_CACHE.get(token.upper())
    return bool(cached and cached.get("fetch_failed", False))


def get_funding_rate(token: str) -> float:
    """Return the current 8h funding rate for `token` as a float fraction.

    Returns 0.0 if the token is not on Binance perpetuals OR the API failed.
    Auto-refreshes cache when stale.

    Examples:
        0.0001  → +0.01% per 8h (longs pay shorts)
        -0.0005 → -0.05% per 8h (shorts pay longs)
        0.0    → no funding bias (or fetch failure — caller can't distinguish)
    """
    if not FUNDING_GATE_ENABLED:
        return 0.0
    tok = token.upper()
    now = time.time()
    cached = _FUNDING_CACHE.get(tok)
    # Cache miss or stale → refresh
    if cached is None or (now - cached.get("fetched_at", 0)) > _CACHE_TTL_SECONDS:
        ok = _refresh_cache_from_api()
        if not ok:
            # Refresh failed — mark fetch_failed so callers can distinguish
            # this from real NEUTRAL. Return stale value if we have one, else 0.0
            _mark_all_fetch_failed()
            if cached is not None:
                return cached.get("rate", 0.0)
            return 0.0
        cached = _FUNDING_CACHE.get(tok)
    if cached is None:
        return 0.0
    return cached.get("rate", 0.0)


def classify_funding_extreme(rate: float, signal_dir: str,
                              fetch_failed: bool = False) -> str:
    """Classify the funding rate relative to the signal direction.

    Returns one of:
      EXTREME_COUNTER_LONG   — extreme negative funding + BUY signal (favorable contrarian)
      EXTREME_COUNTER_SHORT  — extreme positive funding + SELL signal (favorable contrarian)
      EXTREME_AGAINST        — extreme funding agrees with signal direction (less favorable)
      NEUTRAL                — funding within neutral band; no bias
      FETCH_FAILED           — fetch errored, distinguishable from real NEUTRAL (2026-05-29)
      DISABLED               — FUNDING_GATE_ENABLED=0

    Parameters
    ----------
    rate         : float fraction (e.g., 0.0001 = +0.01% per 8h)
    signal_dir   : "BUY" | "SELL"
    fetch_failed : True if the underlying fetch returned an error
                   (rate parameter still passed for backwards compat — typically 0.0)
    """
    if fetch_failed:
        # Surface fetch failure as distinct from NEUTRAL so dashboards can
        # show a yellow indicator instead of green. Bonus is still 0 — same
        # signal behavior, different observability.
        return "FETCH_FAILED"
    if not FUNDING_GATE_ENABLED:
        return "DISABLED"
    sig = (signal_dir or "").upper()
    if rate <= FUNDING_EXTREME_LONG_THRESH:
        # Shorts paying longs — bullish contrarian
        return "EXTREME_COUNTER_LONG" if sig == "BUY" else "EXTREME_AGAINST"
    if rate >= FUNDING_EXTREME_SHORT_THRESH:
        # Longs paying shorts — bearish contrarian
        return "EXTREME_COUNTER_SHORT" if sig == "SELL" else "EXTREME_AGAINST"
    return "NEUTRAL"


def funding_confidence_bonus(rate: float, signal_dir: str) -> float:
    """Return the confidence bonus to add when funding favors the signal.

    Per the ENHANCEMENT_ROADMAP.md T1.2 design:
    - EXTREME_COUNTER_* (favorable) → +FUNDING_BONUS_PCT bonus (positive)
    - EXTREME_AGAINST → -FUNDING_BONUS_PCT penalty (negative)
    - NEUTRAL or DISABLED → 0.0

    The bonus is in confidence-point units (added directly to confidence
    integer in [0..10] scale). Callers should clamp final confidence to [0, 10].
    """
    cls = classify_funding_extreme(rate, signal_dir)
    if cls in ("EXTREME_COUNTER_LONG", "EXTREME_COUNTER_SHORT"):
        return +FUNDING_BONUS_PCT
    if cls == "EXTREME_AGAINST":
        return -FUNDING_BONUS_PCT
    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Stage B (2026-05-29) — Historical funding-rate fetcher for backtest parity
# ══════════════════════════════════════════════════════════════════════════════
def _fetch_one_funding_page(symbol: str, start_time_ms: Optional[int] = None,
                              end_time_ms: Optional[int] = None,
                              limit: int = 1000) -> Optional[list]:
    """Single-page fetch from Binance fapi /fundingRate.

    Returns list of (ts_ms, rate_float) sorted ASC, or None on failure.

    When `start_time_ms` is provided, retrieves rates AT OR AFTER that time.
    Empirically, anchoring with `startTime` is far more reliable than
    `endTime` for paginating from a known anchor — Binance returns up to
    1000 consecutive entries from that point forward without surprise jumps.

    `end_time_ms` is supported for backwards-pagination fallback but the
    preferred path is forward-pagination using `start_time_ms`.
    """
    params = {"symbol": symbol, "limit": min(limit, 1000)}
    if start_time_ms is not None:
        params["startTime"] = start_time_ms
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    for attempt in range(1, API_RETRIES + 1):
        try:
            r = requests.get(
                f"{BINANCE_FAPI_BASE}/fundingRate",
                params=params, headers=HEADERS, timeout=15,
            )
            # M-CY12-4 fix (cycle-12 2026-05-29): same 418/429 pattern as
            # _fetch_all_premium_index above. Historical fetch hits at
            # backtest start (10 tokens × 1-2 pages) — most likely path to
            # hit rate limit if the operator runs back-to-back backtests.
            _sc = r.status_code
            if _sc == 418:
                print(f"[FUNDING-HIST] {symbol}: IP BANNED (418) — aborting")
                return None
            if _sc == 429:
                _wait = min(
                    int(getattr(r, 'headers', {}).get("Retry-After", 30)), 60)
                print(f"[FUNDING-HIST] {symbol} attempt {attempt}: "
                      f"rate limited (429) — sleeping {_wait}s")
                if attempt < API_RETRIES:
                    time.sleep(_wait)
                    continue
                return None
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                code = data.get("code", "?")
                msg = data.get("msg", str(data))[:200]
                print(f"[FUNDING-HIST-ERR] {symbol}: HTTP 200 with error "
                      f"body code={code} msg={msg!r}")
                return None
            if not isinstance(data, list):
                print(f"[FUNDING-HIST-ERR] {symbol}: unexpected shape {type(data)}")
                return None
            out = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                try:
                    ts_ms = int(item.get("fundingTime", "0") or "0")
                    rate = float(item.get("fundingRate", "0") or "0")
                except (TypeError, ValueError):
                    continue
                if ts_ms > 0:
                    out.append((ts_ms, rate))
            out.sort(key=lambda x: x[0])
            return out
        except requests.exceptions.RequestException as e:
            if attempt < API_RETRIES:
                time.sleep(API_DELAY)
                continue
            print(f"[FUNDING-HIST-ERR] {symbol} fetch failed after "
                  f"{API_RETRIES} retries: {e}")
            return None
        except Exception as e:
            print(f"[FUNDING-HIST-ERR] {symbol} unexpected error: {e}")
            return None
    return None


def _fetch_historical_funding(symbol: str, days: int = 365) -> Optional[list]:
    """Forward-paginate `days` of funding-rate history using startTime anchor.

    Binance's `/fapi/v1/fundingRate`:
      - default call (no start/end): returns ~200 most-recent entries
      - with `startTime=X, limit=1000`: returns up to 1000 entries AT OR
        AFTER X, no surprise gaps. This is the reliable pagination path.

    Each page returns up to 1000 settles ≈ 333 days at 8h settle cadence.
    For a 365-day backtest we typically need 1-2 pages. Safety cap at 5 pages.

    Returns list of (ts_ms, rate_float) sorted ASC, or None on first-page
    failure. Partial coverage (e.g., token listed mid-window) is returned
    as-is — caller's `get_historical_funding_at` returns 0.0 for any ts
    before the earliest cached rate.
    """
    start_ts_ms = int((time.time() - days * 86400) * 1000)
    aggregate: list = []
    # Page forward from start_ts_ms until we run out of data or stop getting
    # new rates (page is empty or doesn't advance time).
    cursor_ts = start_ts_ms
    for page_num in range(5):
        page = _fetch_one_funding_page(symbol, start_time_ms=cursor_ts)
        if page is None:
            # First-page failure → return None so caller can mark as unavailable.
            # Later-page failure → keep what we have.
            if page_num == 0:
                return None
            break
        if not page:
            break
        aggregate.extend(page)
        latest_in_page = max(ts for ts, _ in page)
        # If the page doesn't advance past our cursor, we're at the end.
        if latest_in_page <= cursor_ts:
            break
        cursor_ts = latest_in_page + 1
    # Dedupe by timestamp + sort ASC
    seen: dict = {}
    for ts, rate in aggregate:
        seen[ts] = rate
    return [(ts, seen[ts]) for ts in sorted(seen.keys())]


def preload_historical_funding(tokens=None) -> int:
    """Pre-fetch historical funding rates for the listed tokens.

    Called at backtest start to populate the history cache once, so the
    per-signal lookup at signal-evaluation time is a fast in-memory bisect
    instead of an API call. Returns the count of tokens successfully cached.

    Caller passes the list of tokens this backtest will evaluate (typically
    `BINANCE_TOKENS.keys()` minus the BTC-self-correlation cases). Skipping
    BTC is fine — funding overlay applies to all tokens including BTC, and
    BTC's own funding is meaningful (it's the perp-vs-spot premium).
    """
    if tokens is None:
        tokens = list(BINANCE_TOKENS.keys())
    now = time.time()
    success = 0
    # M-CY12-3 fix (cycle-12 audit 2026-05-29): defense-in-depth — pace the
    # per-token fetches at 0.25s/token to mirror backtest.py:354 (spot kline
    # paginator). 10 tokens × ~2 pages = ~20 fapi requests in ~2 seconds is
    # well under the 2400-weight/min cap, but adds zero cost beyond ~2.5s
    # one-time at backtest start. Pacing makes the burst invisible to
    # Binance's rolling limit counter.
    _INTER_TOKEN_SLEEP_S = 0.25
    _first = True
    for token in tokens:
        tok_u = token.upper()
        symbol = BINANCE_TOKENS.get(token) or BINANCE_TOKENS.get(tok_u)
        if not symbol:
            continue
        cached = _FUNDING_HISTORY_CACHE.get(tok_u)
        if cached and (now - cached.get("fetched_at", 0)) < _HISTORY_CACHE_TTL_SECONDS:
            success += 1
            continue
        if not _first:
            time.sleep(_INTER_TOKEN_SLEEP_S)
        _first = False
        data = _fetch_historical_funding(symbol)
        if data is None:
            _FUNDING_HISTORY_CACHE[tok_u] = {
                "rates": [], "fetched_at": now, "available": False,
            }
            continue
        _FUNDING_HISTORY_CACHE[tok_u] = {
            "rates": data, "fetched_at": now, "available": True,
        }
        success += 1
    return success


def get_historical_funding_at(token: str, ts_ms: int) -> float:
    """Look up the funding rate that was in effect at `ts_ms` for `token`.

    Returns the most recent settled funding rate AT OR BEFORE ts_ms. This
    matches how the live bot would have seen the rate at that wall-clock time.

    Returns 0.0 (treated as NEUTRAL) when:
      - History cache is empty (preload_historical_funding wasn't called)
      - ts_ms is before the earliest cached rate
      - Fetch had previously failed for this token
      - FUNDING_GATE_ENABLED=0

    The cache is populated by preload_historical_funding() — callers should
    call that once at backtest start.
    """
    if not FUNDING_GATE_ENABLED:
        return 0.0
    tok = token.upper()
    cached = _FUNDING_HISTORY_CACHE.get(tok)
    if not cached or not cached.get("available") or not cached.get("rates"):
        return 0.0
    rates = cached["rates"]
    # bisect_right on the timestamp column to find insertion point;
    # the funding rate IN EFFECT at ts_ms is the most recent ts <= ts_ms.
    import bisect
    # Build a lightweight key list once (or just iterate; rates is ~1000 entries max)
    ts_keys = [r[0] for r in rates]
    idx = bisect.bisect_right(ts_keys, ts_ms) - 1
    if idx < 0:
        return 0.0
    return rates[idx][1]


def historical_fetch_failed(token: str) -> bool:
    """Return True if the historical preload attempt for this token errored."""
    cached = _FUNDING_HISTORY_CACHE.get(token.upper())
    return bool(cached and not cached.get("available", True))


def reset_cache():
    """Test-only: clear the module cache. Used by unit tests."""
    _FUNDING_CACHE.clear()
    _FUNDING_HISTORY_CACHE.clear()


# ── Public API ────────────────────────────────────────────────────────────────
__all__ = [
    "get_funding_rate",
    "classify_funding_extreme",
    "funding_confidence_bonus",
    "is_funding_fetch_failed",
    # Stage B (2026-05-29)
    "preload_historical_funding",
    "get_historical_funding_at",
    "historical_fetch_failed",
    "FUNDING_EXTREME_LONG_THRESH",
    "FUNDING_EXTREME_SHORT_THRESH",
    "FUNDING_BONUS_PCT",
    "FUNDING_GATE_ENABLED",
    "reset_cache",
]
