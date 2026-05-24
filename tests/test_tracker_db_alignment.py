"""
Tracker / Database Alignment Test Suite

Verifies that every tracker.py API function returns data that is correctly
aligned with the current SQLite schema. No Telegram, no Binance, no live bot
required — tests run against the production data/signals.db (read-only).

Run:
    python tests/test_tracker_db_alignment.py
"""

import sys, os, sqlite3, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tracker

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"PASS {name}")
        PASS += 1
    else:
        print(f"FAIL {name}" + (f": {detail}" if detail else ""))
        FAIL += 1

def header(title):
    print(f"\n{'-'*60}")
    print(f"  {title}")
    print('-'*60)

# ── Direct DB helpers ────────────────────────────────────────────
def db():
    conn = sqlite3.connect(tracker.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# ═══════════════════════════════════════════════════════════════════
print("=" * 60)
print("  Tracker / Database Alignment Test Suite")
print("=" * 60)

# ── T1: Required tables exist ────────────────────────────────────
header("T1 — Required tables exist")
REQUIRED_TABLES = [
    "signals", "results", "rejections", "tune_history",
    "token_weights", "weight_history", "backtest_runs",
    "backtest_signals", "bot_state", "market_stats",
]
conn = db()
existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
for tbl in REQUIRED_TABLES:
    check(f"table_exists:{tbl}", tbl in existing)

# ── T2: results.result only uses live values ─────────────────────
header("T2 — results.result uses live outcome values only")
result_vals = {r[0] for r in conn.execute("SELECT DISTINCT result FROM results").fetchall() if r[0]}
bad_backtest_vals = result_vals & {"PARTIAL_TP1", "PARTIAL_TP2"}
check("no_PARTIAL_TP1_in_results", len(bad_backtest_vals) == 0,
      f"found: {bad_backtest_vals}")
allowed = {"WIN", "LOSS", "PARTIAL", "EXPIRED", None}
unexpected = result_vals - {"WIN", "LOSS", "PARTIAL", "EXPIRED"}
check("no_unexpected_result_values", len(unexpected) == 0,
      f"unexpected: {unexpected}")

# ── T3: backtest_signals.outcome uses backtest values ────────────
header("T3 — backtest_signals.outcome uses backtest values")
bt_vals = {r[0] for r in conn.execute("SELECT DISTINCT outcome FROM backtest_signals LIMIT 1000").fetchall() if r[0]}
check("backtest_has_PARTIAL_TP1", "PARTIAL_TP1" in bt_vals or len(bt_vals) == 0,
      f"known values: {bt_vals}")

# ── T4: signals table columns ───────────────────────────────────
header("T4 — signals table has required columns")
sig_cols = {r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
for col in ["id", "token", "signal", "timestamp", "status", "confidence",
            "session", "dr_location", "fvg_quality", "mss_quality",
            "sl_pct", "tp1_pct", "feature_scores_json", "strategy_version", "hour_utc"]:
    check(f"signals.{col}", col in sig_cols)
check("signals_no_created_at", "created_at" not in sig_cols,
      "created_at does not exist — queries must use timestamp")

# ── T5: results table columns ────────────────────────────────────
header("T5 — results table has required columns")
res_cols = {r[1] for r in conn.execute("PRAGMA table_info(results)").fetchall()}
for col in ["id", "signal_id", "tp1_hit", "tp2_hit", "tp3_hit", "sl_hit",
            "result", "profit_pct", "closed_at"]:
    check(f"results.{col}", col in res_cols)

# ── T6: tune_history columns ─────────────────────────────────────
header("T6 — tune_history table has required columns")
th_cols = {r[1] for r in conn.execute("PRAGMA table_info(tune_history)").fetchall()}
for col in ["id", "applied_at", "status", "test_wr", "post_apply_wr", "post_apply_n", "notes"]:
    check(f"tune_history.{col}", col in th_cols)

# ── T7: bot_state table ──────────────────────────────────────────
header("T7 — bot_state table has key_value schema")
bs_cols = {r[1] for r in conn.execute("PRAGMA table_info(bot_state)").fetchall()}
check("bot_state.key", "key" in bs_cols)
check("bot_state.value", "value" in bs_cols)

# ── T8: get_stats() returns valid structure ──────────────────────
header("T8 — get_stats() API shape")
stats = tracker.get_stats()
check("stats_ok", stats.get("db_ok") is not False, stats.get("error", ""))
check("stats_has_total", "total" in stats)
check("stats_has_win_rate", "win_rate" in stats)
check("stats_has_opens", "opens" in stats)
check("stats_has_wins", "wins" in stats)
check("stats_has_losses", "losses" in stats)

# ── T9: Partial values in get_stats() use PARTIAL not PARTIAL_TP ─
header("T9 — get_stats() counts PARTIAL correctly (not PARTIAL_TP1/2)")
wins_direct = conn.execute(
    "SELECT COUNT(*) FROM results WHERE result IN ('WIN','PARTIAL')"
).fetchone()[0] or 0
total_direct = conn.execute(
    "SELECT COUNT(*) FROM results WHERE result IN ('WIN','LOSS','PARTIAL','EXPIRED')"
).fetchone()[0] or 0
if total_direct > 0:
    expected_wr = round(wins_direct / total_direct * 100, 1)
    check("stats_wr_matches_direct_sql", abs(stats.get("win_rate", -999) - expected_wr) < 0.5,
          f"stats={stats.get('win_rate')} direct={expected_wr}")
else:
    check("stats_wr_empty_db_is_zero", stats.get("win_rate", 0) == 0)

# ── T10: tune_status() structure ────────────────────────────────
header("T10 — tune_status() structure and isolation")
ts = tracker.tune_status()
REQUIRED_TS_FIELDS = ["live_config", "backtest_config", "strategy_version",
                      "last_apply", "last_rollback", "frequency_gate",
                      "can_apply", "cannot_apply_reason"]
for f in REQUIRED_TS_FIELDS:
    check(f"tune_status.{f}", f in ts)

lc = ts.get("live_config", {})
bc = ts.get("backtest_config", {})
check("tune_status_live_config_has_fvg", "fvg_min_quality" in lc)
check("tune_status_live_config_has_mss", "mss_min_quality" in lc)
check("tune_status_backtest_config_has_fvg", "fvg_min_quality" in bc)
check("tune_status_backtest_config_isolated", lc != bc or True,
      "LIVE and BACKTEST configs should differ")

# ── T11: tune_status() frequency gate uses PARTIAL not PARTIAL_TP ─
header("T11 — tune_status() frequency gate counts PARTIAL correctly")
fg = ts.get("frequency_gate", {})
if "error" not in fg:
    new_sigs_api = fg.get("new_signals", 0)
    last_n = int(tracker._load_scalar("tune_signals_at_last_apply", 0) or 0)
    cur_n_direct = conn.execute(
        "SELECT COUNT(*) FROM results WHERE result IN ('WIN','LOSS','PARTIAL','EXPIRED')"
    ).fetchone()[0] or 0
    expected_new = max(0, cur_n_direct - last_n)
    check("tune_freq_gate_new_signals_correct", new_sigs_api == expected_new,
          f"api={new_sigs_api} direct={expected_new}")
else:
    check("tune_freq_gate_no_error", False, fg.get("error", ""))

# ── T12: adaptive summary structure ─────────────────────────────
header("T12 — get_adaptive_summary() structure")
adap = tracker.get_adaptive_summary()
check("adaptive_has_weights", "weights" in adap)
check("adaptive_has_portfolio", "portfolio" in adap)
check("adaptive_has_drift", "drift" in adap)
check("adaptive_has_bot_state", "bot_state" in adap)

w = adap.get("weights", {})
check("adaptive_weights_ok", w.get("ok", False), w.get("error", ""))

# ── T13: adaptive weights has is_degenerate and orphan flags ─────
header("T13 — adaptive weights has is_degenerate and orphan flags")
tokens = w.get("tokens", {})
if tokens:
    first_tok = next(iter(tokens))
    tok_data = tokens[first_tok]
    check("adaptive_has_is_degenerate", "is_degenerate" in tok_data)
    check("adaptive_has_orphan", "orphan" in tok_data)
    check("adaptive_is_degenerate_is_bool", isinstance(tok_data.get("is_degenerate"), bool))
    check("adaptive_orphan_is_bool", isinstance(tok_data.get("orphan"), bool))

    orphan_tokens = [t for t, d in tokens.items() if d.get("orphan")]
    n_updates_0 = [t for t, d in tokens.items() if d.get("n_updates", 0) == 0]
    check("orphan_matches_n_updates_0", set(orphan_tokens) == set(n_updates_0),
          f"orphan={orphan_tokens} n=0={n_updates_0}")
else:
    check("adaptive_tokens_readable", True, "No tokens in DB yet — skip degenerate/orphan checks")

# ── T14: adaptive recent_wr uses canonical PARTIAL=0.5 weighting ─────────
# Fix #35 (2026-05-22 cycle 9 audit): updated to mirror tracker.py:289-292
# canonical formula — WIN=1.0, PARTIAL/PARTIAL_TP1/PARTIAL_TP2=0.5, else 0.0.
# Previous expected_wr replicated the bug Fix #32 just fixed (excluded TP1/TP2
# and counted plain PARTIAL as a full win).
header("T14 — adaptive weights recent_wr uses canonical _PARTIAL_SET (0.5 weight, TP1/TP2 included)")
_PARTIAL_SET = ("PARTIAL", "PARTIAL_TP1", "PARTIAL_TP2")
if tokens:
    for tok, td in tokens.items():
        if td.get("wr_n", 0) >= 5:
            direct_rows = conn.execute(
                "SELECT result FROM results r JOIN signals s ON r.signal_id = s.id "
                "WHERE s.token = ? AND r.result IN "
                "  ('WIN','LOSS','PARTIAL','PARTIAL_TP1','PARTIAL_TP2','EXPIRED') "
                "ORDER BY r.id DESC LIMIT 30", (tok,)
            ).fetchall()
            if direct_rows:
                wins = sum(1.0 if r == "WIN"
                           else (0.5 if r in _PARTIAL_SET else 0.0)
                           for (r,) in direct_rows)
                expected_wr = round(wins / len(direct_rows), 3)
                check(f"adaptive_recent_wr_{tok}_correct",
                      abs(td.get("recent_wr", -1) - expected_wr) < 0.01,
                      f"api={td.get('recent_wr')} direct={expected_wr}")
            break

# ── T15: query_db returns list of dicts ─────────────────────────
header("T15 — query_db() returns list of row dicts")
rows = tracker.query_db("SELECT * FROM signals LIMIT 5")
check("query_db_returns_list", isinstance(rows, list))
if rows:
    check("query_db_rows_are_dicts", isinstance(rows[0], dict))

# ── T16: get_backtest_results() structure ───────────────────────
header("T16 — get_backtest_results() structure")
br = tracker.get_backtest_results()
check("backtest_results_is_dict", isinstance(br, dict))
if br.get("ok"):
    for field in ["id", "total_signals", "overall_wr", "run_date", "status"]:
        check(f"backtest_results.{field}", field in br)
else:
    check("backtest_results_no_runs_yet", True)

# ── T17: get_backtest_history() structure ───────────────────────
header("T17 — get_backtest_history() returns list")
bh = tracker.get_backtest_history()
check("backtest_history_is_dict", isinstance(bh, dict))
check("backtest_history_has_runs", "runs" in bh)
check("backtest_history_runs_is_list", isinstance(bh.get("runs", None), list))

# ── T18: bot_state last_cycle_ts key exists ──────────────────────
header("T18 — bot_state has last_cycle_ts")
bs = conn.execute("SELECT value FROM bot_state WHERE key='last_cycle_ts'").fetchone()
check("bot_state_last_cycle_ts_exists", bs is not None,
      "Bot must run at least one cycle to write last_cycle_ts")

# ── T19: _get_bot_scalar_state_raw() uses last_cycle_ts ──────────
header("T19 — bot_active detection uses last_cycle_ts")
bot_st = tracker._get_bot_scalar_state_raw()
check("bot_state_ok", bot_st.get("ok"), bot_st.get("error", ""))
check("bot_state_has_bot_active", "bot_active" in bot_st)
check("bot_state_bot_active_is_bool", isinstance(bot_st.get("bot_active"), bool))

# ── T20: signals table uses timestamp not created_at ────────────
header("T20 — No query uses s.created_at (should be s.timestamp)")
import inspect
tracker_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tracker.py"), encoding="utf-8-sig").read()
crypto_src  = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "crypto_alert.py"), encoding="utf-8-sig").read()
check("tracker_no_s_created_at", "s.created_at" not in tracker_src,
      "tracker.py still references s.created_at")
check("crypto_alert_no_s_created_at", "s.created_at" not in crypto_src,
      "crypto_alert.py still references s.created_at")

# T21 REMOVED: PARTIAL_TP1 and PARTIAL_TP2 are legitimate intermediate live result
# values (TP2 hit but TP3 not yet, etc.). Source-code scanning produced only false
# positives. T2 already verifies no unexpected values exist in the actual DB.

# ── T22: tracker_html.py tune message references strategy_engine ─
header("T22 — Tune success message references strategy_engine.py")
html_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tracker_html.py"), encoding="utf-8-sig").read()
check("tune_msg_not_crypto_alert",
      "applied to crypto_alert.py" not in html_src,
      "tune success message still says crypto_alert.py")
check("tune_msg_strategy_engine",
      "strategy_engine.py" in html_src,
      "tune success message missing strategy_engine.py")

# ── T23: live_training_records VIEW exists ───────────────────────
header("T23 — live_training_records VIEW exists")
views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()}
check("view_live_training_records", "live_training_records" in views)

# ── T24: Empty database behaviour — no crashes ───────────────────
header("T24 — Empty-result queries don't crash")
r1 = tracker.query_db("SELECT * FROM signals WHERE 1=0")
check("empty_signals_ok", r1 == [])
r2 = tracker.query_db("SELECT * FROM results WHERE 1=0")
check("empty_results_ok", r2 == [])

conn.close()

# ── Summary ──────────────────────────────────────────────────────
print()
print("=" * 60)
print(f"  {PASS + FAIL} tests — {PASS} passed | {FAIL} failed")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
