"""exec_quality.py — Phase C-Breakout Type-A execution-quality OBSERVATION logging.

OBSERVATION ONLY. Records a live order-book execution-quality snapshot alongside
every Config-14 breakout signal. It NEVER gates, never alters entry/exit/geometry,
never decides whether a trade is taken. The soaks trade identically with or without
this module loaded.

Safety contract (enforced by `observe_exec_quality`):
  - The order-book fetch is wrapped in try/except with a SHORT timeout. On ANY
    failure (timeout, HTTP error, parse error, missing symbol) the trade has
    ALREADY been persisted by the caller; this module logs a `fetch_failed` row
    and returns. A fetch failure can NEVER skip a trade, crash, or stall the soak.
  - `observe_exec_quality` never raises — even the DB insert is guarded.
  - The `would_skip` flag (pre-registered Type-A rules) is RECORDED but the caller
    never consults it. This builds a forward, causal dataset to LATER analyze
    whether a Type-A gate WOULD have helped — it is hygiene observation, not alpha,
    not a gate.

Storage: a SEPARATE additive table `exec_quality_log` in breakout.db. The existing
signals/results schema is untouched. The eventual trade OUTCOME + realized R are
backfilled (post-resolution, decoupled from the resolution code path) by joining
the existing `results` table on signal_id.

Order-book source: Bybit v5 public spot order book (no auth).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# PRE-REGISTERED Type-A thresholds — coarse, round, from cost-model first
# principles, IDENTICAL across all 12 tokens, NOT tuned to results.
# Recorded as `would_skip` / `tripped_rules`; NEVER acted on by execution.
# ─────────────────────────────────────────────────────────────────────────────
SPREAD_MAX_PCT   = 0.10   # spread            > 0.10% → would-skip
SLIPPAGE_MAX_PCT = 0.15   # est. slippage @ size > 0.15% → would-skip
DEPTH_MULT_MIN   = 3.0    # near-touch depth  < 3× position size → would-skip

# PRE-REGISTERED nominal position size (USD notional). Round, same across tokens.
# The slippage walk and the depth-multiple rule are measured against THIS size.
# Stated assumption (the soak is paper / signal-only with no configured capital):
# a fixed $5,000 nominal notional per signal. Recorded per-row so a later analysis
# can re-derive metrics at any other size without re-fetching.
NOMINAL_POSITION_USD = 5000.0

# Depth-band half-widths as a fraction of mid.
BAND_TIGHT = 0.0010   # ±0.10%  → "near-touch" band (used by the depth rule)
BAND_WIDE  = 0.0025   # ±0.25%

# Bybit v5 public spot order book.
BYBIT_ORDERBOOK_URL = "https://api.bybit.com/v5/market/orderbook"
BYBIT_OB_LIMIT      = 50            # 50 levels/side — enough for the ±0.25% band
FETCH_TIMEOUT_SEC   = 3            # SHORT — must never stall the 120s cycle
USER_AGENT          = "TradeAI-BreakoutSoak-ExecQual/1.0"


# ── Schema (additive; never touches signals/results) ─────────────────────────
def ensure_exec_quality_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS exec_quality_log (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id                INTEGER,           -- FK → signals.id
            soak_label               TEXT,
            ts_utc                   TEXT,              -- order-book capture time (UTC)
            token                    TEXT,
            symbol                   TEXT,
            direction                TEXT,              -- BUY | SELL
            fetch_status             TEXT,              -- 'ok' | 'fetch_failed'
            fetch_error              TEXT,              -- repr(exc) when failed, else NULL
            mid                      REAL,
            best_bid                 REAL,
            best_ask                 REAL,
            spread_pct               REAL,
            position_usd             REAL,              -- the pre-registered nominal size
            bid_depth_01pct_usd      REAL,              -- ±0.10% band, bid side (USD)
            ask_depth_01pct_usd      REAL,              -- ±0.10% band, ask side (USD)
            bid_depth_025pct_usd     REAL,              -- ±0.25% band, bid side (USD)
            ask_depth_025pct_usd     REAL,              -- ±0.25% band, ask side (USD)
            exec_side_depth_01pct_usd REAL,             -- near-touch depth on the side we'd trade
            est_slippage_pct         REAL,              -- VWAP fill vs mid, % (positive = cost)
            vwap_fill_price          REAL,
            filled_fraction          REAL,              -- 1.0 if book filled the size, else <1
            would_skip               INTEGER,           -- 0/1 — OBSERVATION ONLY, never acted on
            tripped_rules            TEXT,              -- comma-joined rule names
            outcome                  TEXT,              -- backfilled from results (nullable)
            realized_r               REAL,              -- backfilled from results (nullable)
            created_at               TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_exec_quality_signal "
        "ON exec_quality_log (signal_id)"
    )
    conn.commit()


# ── Order-book fetch (raises on any failure — caller catches) ────────────────
def fetch_bybit_orderbook(symbol: str, limit: int = BYBIT_OB_LIMIT,
                          timeout: float = FETCH_TIMEOUT_SEC):
    """Return (bids, asks) as lists of (price, size) floats. bids descending,
    asks ascending (Bybit's native order). RAISES on any failure — the caller
    (`observe_exec_quality`) converts any exception into a fetch_failed row."""
    url = (f"{BYBIT_ORDERBOOK_URL}?category=spot&symbol={symbol}&limit={limit}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise urllib.error.HTTPError(url, resp.status, "non-200", resp.headers, None)
        raw = json.loads(resp.read().decode("utf-8"))
    if not isinstance(raw, dict) or raw.get("retCode") != 0:
        raise ValueError(f"bybit retCode={raw.get('retCode')} retMsg={raw.get('retMsg')}")
    res = raw.get("result") or {}
    bids = [(float(p), float(s)) for p, s in res.get("b", [])]
    asks = [(float(p), float(s)) for p, s in res.get("a", [])]
    if not bids or not asks:
        raise ValueError("empty order book")
    return bids, asks


# ── Pure snapshot computation (no network — unit-testable) ────────────────────
def compute_snapshot(bids, asks, direction: str,
                     position_usd: float = NOMINAL_POSITION_USD) -> dict:
    """Compute execution-quality metrics from an order book. Pure function.

    bids/asks: list[(price, size_in_base_units)], bids descending, asks ascending.
    direction: 'BUY' walks asks; 'SELL' walks bids.
    Returns a metrics dict including the pre-registered would_skip flag.
    """
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid = (best_bid + best_ask) / 2.0
    spread_pct = (best_ask - best_bid) / mid * 100.0 if mid > 0 else 0.0

    # Depth bands in USD notional (price * size summed within the band of mid).
    def bid_depth(frac):
        lo = mid * (1.0 - frac)
        return sum(p * s for p, s in bids if p >= lo)

    def ask_depth(frac):
        hi = mid * (1.0 + frac)
        return sum(p * s for p, s in asks if p <= hi)

    bid_depth_01 = bid_depth(BAND_TIGHT)
    ask_depth_01 = ask_depth(BAND_TIGHT)
    bid_depth_025 = bid_depth(BAND_WIDE)
    ask_depth_025 = ask_depth(BAND_WIDE)

    # Walk the execution side to fill `position_usd`; compute VWAP fill + slippage.
    levels = asks if direction == "BUY" else bids
    exec_side_depth_01 = ask_depth_01 if direction == "BUY" else bid_depth_01
    remaining = position_usd
    spent_usd = 0.0
    filled_base = 0.0
    for p, s in levels:
        if remaining <= 0:
            break
        level_usd = p * s
        take_usd = min(level_usd, remaining)
        filled_base += take_usd / p
        spent_usd += take_usd
        remaining -= take_usd
    filled_fraction = (position_usd - remaining) / position_usd if position_usd > 0 else 0.0
    if filled_base > 0:
        vwap = spent_usd / filled_base
        if direction == "BUY":
            slippage_pct = (vwap - mid) / mid * 100.0
        else:
            slippage_pct = (mid - vwap) / mid * 100.0
    else:
        vwap = mid
        slippage_pct = 0.0

    # PRE-REGISTERED would-skip evaluation (recorded, NEVER acted on).
    tripped = []
    if spread_pct > SPREAD_MAX_PCT:
        tripped.append("spread")
    # If the book could not fill the full size, slippage for the size is at least
    # as bad as the partial-fill VWAP AND depth is structurally short → both trip.
    if filled_fraction < 1.0:
        tripped.append("slippage")   # could not even fill the size at any price shown
        if "depth" not in tripped:
            tripped.append("depth")
    elif slippage_pct > SLIPPAGE_MAX_PCT:
        tripped.append("slippage")
    if exec_side_depth_01 < DEPTH_MULT_MIN * position_usd and "depth" not in tripped:
        tripped.append("depth")
    would_skip = 1 if tripped else 0

    return {
        "mid": mid, "best_bid": best_bid, "best_ask": best_ask,
        "spread_pct": round(spread_pct, 5),
        "position_usd": position_usd,
        "bid_depth_01pct_usd": round(bid_depth_01, 2),
        "ask_depth_01pct_usd": round(ask_depth_01, 2),
        "bid_depth_025pct_usd": round(bid_depth_025, 2),
        "ask_depth_025pct_usd": round(ask_depth_025, 2),
        "exec_side_depth_01pct_usd": round(exec_side_depth_01, 2),
        "est_slippage_pct": round(slippage_pct, 5),
        "vwap_fill_price": vwap,
        "filled_fraction": round(filled_fraction, 4),
        "would_skip": would_skip,
        "tripped_rules": ",".join(tripped),
    }


# ── Defensive insert (never raises out) ──────────────────────────────────────
def _insert_row(conn, *, signal_id, soak_label, ts_utc, token, symbol, direction,
                fetch_status, fetch_error, position_usd, snap: Optional[dict]) -> None:
    s = snap or {}
    conn.execute(
        "INSERT INTO exec_quality_log "
        "(signal_id, soak_label, ts_utc, token, symbol, direction, "
        " fetch_status, fetch_error, mid, best_bid, best_ask, spread_pct, "
        " position_usd, bid_depth_01pct_usd, ask_depth_01pct_usd, "
        " bid_depth_025pct_usd, ask_depth_025pct_usd, exec_side_depth_01pct_usd, "
        " est_slippage_pct, vwap_fill_price, filled_fraction, would_skip, "
        " tripped_rules, outcome, realized_r, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?,  ?, ?, ?, ?, ?, ?,  ?, ?, ?,  ?, ?, ?,  ?, ?, ?, ?,  ?, ?, ?, ?)",
        (signal_id, soak_label, ts_utc, token, symbol, direction,
         fetch_status, fetch_error,
         s.get("mid"), s.get("best_bid"), s.get("best_ask"), s.get("spread_pct"),
         position_usd, s.get("bid_depth_01pct_usd"), s.get("ask_depth_01pct_usd"),
         s.get("bid_depth_025pct_usd"), s.get("ask_depth_025pct_usd"),
         s.get("exec_side_depth_01pct_usd"),
         s.get("est_slippage_pct"), s.get("vwap_fill_price"), s.get("filled_fraction"),
         s.get("would_skip"), s.get("tripped_rules"),
         None, None,  # outcome / realized_r — backfilled post-resolution
         datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()


# ── The single entry point the soak calls. NEVER raises. ─────────────────────
def observe_exec_quality(conn, *, signal_id: int, soak_label: str, token: str,
                         symbol: str, direction: str,
                         position_usd: float = NOMINAL_POSITION_USD,
                         log_fn=None) -> str:
    """Capture + log the Type-A snapshot for one signal. OBSERVATION ONLY.

    The caller invokes this AFTER the trade row is already persisted, so nothing
    here can affect whether the trade is taken. Returns 'ok' or 'fetch_failed'
    (purely informational — the caller ignores the return value for execution).
    Guaranteed not to raise.
    """
    ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    snap = None
    status = "ok"
    err = None
    try:
        bids, asks = fetch_bybit_orderbook(symbol)
        snap = compute_snapshot(bids, asks, direction, position_usd)
    except Exception as e:  # ANY failure → fetch_failed, trade already safe
        status = "fetch_failed"
        err = repr(e)[:300]
        if log_fn:
            log_fn(f"  exec_quality[{token}]: order-book fetch failed "
                   f"({err}) — logging fetch_failed, trade unaffected")
    try:
        _insert_row(conn, signal_id=signal_id, soak_label=soak_label, ts_utc=ts_utc,
                    token=token, symbol=symbol, direction=direction,
                    fetch_status=status, fetch_error=err,
                    position_usd=position_usd, snap=snap)
    except Exception as e:  # even the insert is non-fatal
        if log_fn:
            log_fn(f"  exec_quality[{token}]: log insert failed (non-fatal): {e!r}")
    return status


# ── Outcome backfill (decoupled from resolution; additive join on results) ───
def backfill_outcomes(conn, soak_label: Optional[str] = None) -> int:
    """Fill outcome/realized_r on exec_quality_log rows whose signal has since
    closed, by JOINing the existing `results` table on signal_id. Reads results;
    writes ONLY exec_quality_log. Decoupled from resolve_open_signals — it cannot
    affect outcome computation. Returns rows updated."""
    q = (
        "SELECT e.id, r.result, r.realized_r "
        "FROM exec_quality_log e JOIN results r ON r.signal_id = e.signal_id "
        "WHERE e.outcome IS NULL"
    )
    params = ()
    if soak_label is not None:
        q += " AND e.soak_label = ?"
        params = (soak_label,)
    rows = conn.execute(q, params).fetchall()
    for row in rows:
        eid = row[0]; outcome = row[1]; rr = row[2]
        conn.execute(
            "UPDATE exec_quality_log SET outcome = ?, realized_r = ? WHERE id = ?",
            (outcome, rr, eid),
        )
    if rows:
        conn.commit()
    return len(rows)
