"""verify_exec_quality.py — safety + correctness tests for Type-A observation logging.

Uses a THROWAWAY temp DB in /tmp — never touches the real breakout.db, the soaks,
signals.db, or main. Proves:
  1. compute_snapshot correctness (spread / depth / slippage / would_skip) on
     synthetic books — deep/clean (no skip), thin (depth+slippage skip), wide-spread.
  2. FETCH-FAILURE SAFETY (the key test): a simulated order-book fetch exception →
     the row is still recorded as fetch_failed, observe() does NOT raise, the trade
     row is untouched, the "soak" continues.
  3. NON-INTRUSIVE: the signals + results tables are byte-identical before/after
     observe() — for BOTH the success and the failure path — and a would_skip=1
     snapshot leaves the trade row exactly as persisted (trade NOT skipped/altered).
  4. would_skip is RECORDED but the trade persists regardless (never consulted).
  5. backfill_outcomes joins results → exec_quality_log without touching results.
  6. LIVE Bybit fetch (BTCUSDT) produces an 'ok' snapshot (non-fatal if offline).
"""
import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/home/tradeai/TradeAI")

import exec_quality as EQ

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def table_fingerprint(conn, table):
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()


def make_temp_db():
    fd = tempfile.NamedTemporaryFile(prefix="exq_test_", suffix=".db", delete=False)
    fd.close()
    conn = sqlite3.connect(fd.name)
    conn.execute("PRAGMA journal_mode=WAL")
    # Faithful subset of the real signals/results schema (enough for the tests).
    conn.execute("""CREATE TABLE signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, signal TEXT,
        entry_price REAL, timestamp TEXT, status TEXT DEFAULT 'OPEN', source TEXT)""")
    conn.execute("""CREATE TABLE results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id INTEGER,
        result TEXT, realized_r REAL, closed_at TEXT)""")
    conn.commit()
    EQ.ensure_exec_quality_table(conn)
    return conn, fd.name


# ── synthetic books ──────────────────────────────────────────────────────────
def deep_book(mid=100.0):
    # ~0.0002% spread, ~$1M/level → fills $5k with ~0 slippage, no skip.
    tick = mid * 1e-6
    big = 1000.0 / mid * mid  # ~$1000-per-base*… simpler: huge base size
    big = 1_000_000.0 / mid   # ~$1M notional per level
    bids = [(mid - tick - i * tick, big) for i in range(50)]
    asks = [(mid + tick + i * tick, big) for i in range(50)]
    return bids, asks


def thin_book(mid=100.0):
    # 2 tiny levels (~$200 notional each) → cannot fill $5k → depth + slippage trip.
    sz = 200.0 / mid
    bids = [(mid * (1 - 1e-5), sz), (mid * (1 - 5e-3), sz)]
    asks = [(mid * (1 + 1e-5), sz), (mid * (1 + 5e-3), sz)]
    return bids, asks


def wide_spread_book(mid=100.0):
    # 0.3% spread (> 0.10%) but deep → spread trips.
    big = 1_000_000.0 / mid
    bids = [(mid * (1 - 0.0015) - i * mid * 1e-6, big) for i in range(50)]
    asks = [(mid * (1 + 0.0015) + i * mid * 1e-6, big) for i in range(50)]
    return bids, asks


print("=" * 90)
print("EXEC-QUALITY OBSERVATION LOGGING — SAFETY + CORRECTNESS TESTS")
print("=" * 90)
print(f"  Pre-registered thresholds: spread>{EQ.SPREAD_MAX_PCT}%  slippage>{EQ.SLIPPAGE_MAX_PCT}%  "
      f"near-touch depth<{EQ.DEPTH_MULT_MIN}× size")
print(f"  Nominal position size: ${EQ.NOMINAL_POSITION_USD:,.0f}   bands: ±{EQ.BAND_TIGHT*100:.2f}% / ±{EQ.BAND_WIDE*100:.2f}%")
print()

# ── 1. compute_snapshot correctness ──────────────────────────────────────────
print("[1] compute_snapshot on synthetic books")
s = EQ.compute_snapshot(*deep_book(), "BUY")
check("deep/clean book → would_skip=0", s["would_skip"] == 0, f"tripped='{s['tripped_rules']}' spread={s['spread_pct']}% slip={s['est_slippage_pct']}% filled={s['filled_fraction']}")
check("deep book fills full size", s["filled_fraction"] == 1.0)
check("deep book slippage tiny", s["est_slippage_pct"] < EQ.SLIPPAGE_MAX_PCT)

s = EQ.compute_snapshot(*thin_book(), "BUY")
check("thin book → would_skip=1", s["would_skip"] == 1, f"tripped='{s['tripped_rules']}' filled={s['filled_fraction']}")
check("thin book trips depth", "depth" in s["tripped_rules"])
check("thin book cannot fill size", s["filled_fraction"] < 1.0)

s = EQ.compute_snapshot(*wide_spread_book(), "BUY")
check("wide-spread book trips spread", "spread" in s["tripped_rules"], f"spread={s['spread_pct']}% tripped='{s['tripped_rules']}'")
check("wide-spread would_skip=1", s["would_skip"] == 1)

# SELL walks bids — symmetry
s_buy = EQ.compute_snapshot(*deep_book(), "BUY")
s_sell = EQ.compute_snapshot(*deep_book(), "SELL")
check("BUY vs SELL slippage symmetric on symmetric book",
      abs(s_buy["est_slippage_pct"] - s_sell["est_slippage_pct"]) < 1e-6,
      f"buy={s_buy['est_slippage_pct']} sell={s_sell['est_slippage_pct']}")
print()

# ── 2 & 3 & 4. fetch-failure safety + non-intrusiveness ──────────────────────
print("[2/3/4] fetch-failure safety + non-intrusiveness (the key safety tests)")
conn, path = make_temp_db()
# Persist a 'trade' exactly as the soak would (this is the row that must stay safe)
cur = conn.cursor()
cur.execute("INSERT INTO signals (token, signal, entry_price, timestamp, status, source) "
            "VALUES (?,?,?,?,?,?)", ("BTC", "BUY", 63000.0, "2026-06-05 01:00:00", "OPEN", "H4_BREAKOUT_PAPER_SOAK"))
conn.commit()
sig_id = cur.lastrowid
sig_fp_before = table_fingerprint(conn, "signals")
res_fp_before = table_fingerprint(conn, "results")

# (a) FORCE a fetch failure by monkeypatching the fetcher to raise
_orig_fetch = EQ.fetch_bybit_orderbook
def _boom(*a, **k):
    raise TimeoutError("simulated order-book API timeout")
EQ.fetch_bybit_orderbook = _boom
logs = []
status = EQ.observe_exec_quality(conn, signal_id=sig_id, soak_label="H4_BREAKOUT_PAPER_SOAK",
                                 token="BTC", symbol="BTCUSDT", direction="BUY",
                                 log_fn=lambda m: logs.append(m))
EQ.fetch_bybit_orderbook = _orig_fetch
check("fetch failure → observe() returns 'fetch_failed' (no raise)", status == "fetch_failed")
row = conn.execute("SELECT fetch_status, would_skip, mid, signal_id FROM exec_quality_log WHERE signal_id=?", (sig_id,)).fetchone()
check("fetch_failed row recorded", row is not None and row[0] == "fetch_failed", f"row={row}")
check("fetch_failed row has NULL metrics (mid)", row is not None and row[2] is None)
check("fetch_failed row links to the trade (signal_id)", row is not None and row[3] == sig_id)
check("signals table UNTOUCHED after fetch failure", table_fingerprint(conn, "signals") == sig_fp_before)
check("results table UNTOUCHED after fetch failure", table_fingerprint(conn, "results") == res_fp_before)
check("trade still OPEN (failure did NOT skip/alter trade)",
      conn.execute("SELECT status FROM signals WHERE id=?", (sig_id,)).fetchone()[0] == "OPEN")

# (b) SUCCESS path with a forced would_skip=1 (thin) book — trade must STILL be untouched
def _thin(*a, **k):
    return thin_book(63000.0)
EQ.fetch_bybit_orderbook = _thin
cur.execute("INSERT INTO signals (token, signal, entry_price, timestamp, status, source) "
            "VALUES (?,?,?,?,?,?)", ("ETH", "BUY", 3000.0, "2026-06-05 01:02:00", "OPEN", "H4_BREAKOUT_PAPER_SOAK"))
conn.commit()
sig_id2 = cur.lastrowid
sig_fp_before2 = table_fingerprint(conn, "signals")
status2 = EQ.observe_exec_quality(conn, signal_id=sig_id2, soak_label="H4_BREAKOUT_PAPER_SOAK",
                                  token="ETH", symbol="ETHUSDT", direction="BUY")
EQ.fetch_bybit_orderbook = _orig_fetch
row2 = conn.execute("SELECT fetch_status, would_skip, tripped_rules FROM exec_quality_log WHERE signal_id=?", (sig_id2,)).fetchone()
check("would_skip=1 snapshot recorded on success path", row2 is not None and row2[0] == "ok" and row2[1] == 1, f"row={row2}")
check("trade with would_skip=1 STILL persisted unchanged (flag never consulted)",
      table_fingerprint(conn, "signals") == sig_fp_before2 and
      conn.execute("SELECT status FROM signals WHERE id=?", (sig_id2,)).fetchone()[0] == "OPEN")
print()

# ── 5. backfill_outcomes ─────────────────────────────────────────────────────
print("[5] backfill_outcomes (join results → exec_quality_log; results untouched)")
conn.execute("INSERT INTO results (signal_id, result, realized_r, closed_at) VALUES (?,?,?,?)",
             (sig_id, "WIN", 1.42, "2026-06-06 01:00:00"))
conn.commit()
res_fp_pre_backfill = table_fingerprint(conn, "results")
n = EQ.backfill_outcomes(conn, "H4_BREAKOUT_PAPER_SOAK")
filled = conn.execute("SELECT outcome, realized_r FROM exec_quality_log WHERE signal_id=?", (sig_id,)).fetchone()
check("backfill filled outcome/realized_r from results", filled == ("WIN", 1.42), f"filled={filled} n_updated={n}")
check("results table UNTOUCHED by backfill", table_fingerprint(conn, "results") == res_fp_pre_backfill)
check("unclosed signal stays NULL outcome", conn.execute(
      "SELECT outcome FROM exec_quality_log WHERE signal_id=?", (sig_id2,)).fetchone()[0] is None)
conn.close()
Path(path).unlink(missing_ok=True)
for ext in ("-wal", "-shm"):
    Path(path + ext).unlink(missing_ok=True)
print()

# ── 6. LIVE Bybit fetch (non-fatal if offline) ───────────────────────────────
print("[6] LIVE Bybit fetch (BTCUSDT) — real order book")
try:
    bids, asks = EQ.fetch_bybit_orderbook("BTCUSDT")
    snap = EQ.compute_snapshot(bids, asks, "BUY")
    check("live fetch returns a usable snapshot", snap["mid"] > 0 and snap["spread_pct"] >= 0,
          f"mid={snap['mid']:.1f} spread={snap['spread_pct']}% slip(${EQ.NOMINAL_POSITION_USD:.0f})={snap['est_slippage_pct']}% "
          f"ask_depth±0.1%=${snap['ask_depth_01pct_usd']:,.0f} would_skip={snap['would_skip']} tripped='{snap['tripped_rules']}'")
except Exception as e:
    print(f"  SKIP (live fetch unavailable — degrades safely to fetch_failed in prod): {e!r}")
print()

print("=" * 90)
if FAILS:
    print(f"*** {len(FAILS)} CHECK(S) FAILED: {FAILS}")
    sys.exit(1)
print("ALL CHECKS PASSED — observation logging is safe + non-intrusive.")
sys.exit(0)
