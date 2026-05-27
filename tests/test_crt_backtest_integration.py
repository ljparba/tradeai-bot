"""Integration tests for CRT v1 Session 2 backtest.py wiring.

Verifies:
  - `source` column is in the backtest_signals schema migration list
  - run_backtest_token_h4_crt returns [] when ENABLE_H4_CRT=0 (default-OFF)
  - run_backtest_token_h4_crt returns [] when token is in disabled list
  - run_backtest_token_h4_crt returns [] on insufficient input data
  - 5M-sweep signal dicts emitted by run_backtest_token carry source='5M_SWEEP'
  - INSERT statement schema includes the source column
  - When CRT signals are emitted, they carry source='H4_CRT' (via stub)

These tests do NOT run a full backtest (requires Binance data + ~11 min);
the smoke test for full-run behavior is documented separately.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _clean_crt_env():
    # Option S fix (audit cycle-7 2026-05-27): added CRT_FORWARD_BARS,
    # CRT_TP2_RR, CRT_TP3_RR — the LBC re-audit flagged these as missing
    # from test isolation, latent risk if any future test sets them in env.
    # Option KK (v2): added WYCKOFF_PHASE_FILTER + tuning knobs so the
    # Wyckoff-context tests don't leak state across runs.
    for k in ("ENABLE_H4_CRT", "H4_CRT_DISABLED_TOKENS", "H4_CRT_C2_LOOKBACK",
              "H4_CRT_MSS_HORIZON", "H4_CRT_OB_SCAN_LOOKBACK",
              "H4_CRT_VALIDATION_SCHOOL",
              "CRT_FORWARD_BARS", "CRT_TP2_RR", "CRT_TP3_RR",
              "WYCKOFF_PHASE_FILTER",
              "WYCKOFF_H4_LOOKBACK", "WYCKOFF_H4_MIN_BARS",
              "WYCKOFF_RECENT_WINDOW", "WYCKOFF_CONSOLIDATION_RATIO",
              "WYCKOFF_RANGE_POSITION_HI", "WYCKOFF_RANGE_POSITION_LO",
              "WYCKOFF_TREND_THRESHOLD_PCT"):
        os.environ.pop(k, None)


def _flat_candles(n: int, price: float = 100.0, t_step: int = 60_000,
                  t_start: int = 1_700_000_000_000) -> dict:
    """Build a `n`-bar OHLCV dict with all-equal flat candles. Time in ms."""
    return {
        "opens":  [price] * n,
        "highs":  [price] * n,
        "lows":   [price] * n,
        "closes": [price] * n,
        "times":  [t_start + i * t_step for i in range(n)],
    }


class TestSourceColumnSchema(unittest.TestCase):
    """Verify the schema migration includes `source` with the right default."""

    def test_source_column_in_migration_list(self):
        import backtest
        # Inspect the source of init_backtest_db for the migration tuple
        import inspect
        src = inspect.getsource(backtest.init_backtest_db)
        self.assertIn('"source"', src,
                      "init_backtest_db migration must include the `source` column")
        self.assertIn("5M_SWEEP", src,
                      "Default value for `source` must be '5M_SWEEP'")

    def test_insert_includes_source_column(self):
        # Option E M-6 quality fix (audit cycle-7 2026-05-27): INSERT is now
        # built programmatically via _BACKTEST_SIGNALS_COLS + placeholder
        # interpolation. The "source" column must appear in the canonical
        # column tuple and in the row-builder function.
        import backtest
        self.assertIn("source", backtest._BACKTEST_SIGNALS_COLS,
                      "source column must be in canonical column tuple")
        # _backtest_signal_to_row must produce a tuple of exact length
        # matching _BACKTEST_SIGNALS_COLS for SQL parameter binding to work
        synthetic = {
            "token": "BTC", "signal": "BUY", "price": 1.0, "ts": "t",
            "regime": "TR", "confidence": 8, "wscore": 0.5, "margin": 1.0,
            "conflict": "LOW", "tp1_pct": 1.0, "sl_pct": -1.0, "rr1": 1.0,
            "net_tp1_pct": 0.7, "net_sl_pct": -1.3, "net_rr1": 0.54,
            "breakeven_wr": 0.5, "tp_reached": 0, "outcome": "EXPIRED",
        }
        row = backtest._backtest_signal_to_row(synthetic, run_id=42)
        self.assertEqual(len(row), len(backtest._BACKTEST_SIGNALS_COLS),
                         "row tuple length must equal column tuple length")

    def test_insert_schema_alignment_via_in_memory_sqlite(self):
        """NEW-5 fix (Option H audit 2026-05-27): tuple-length equality
        alone doesn't catch column-name drift. This test executes the
        actual INSERT against an in-memory SQLite with the production
        schema and verifies it succeeds — proving every column referenced
        in `_BACKTEST_SIGNALS_COLS` exists in `backtest_signals` and that
        `_backtest_signal_to_row()` produces a valid parameter binding.
        """
        import sqlite3
        import backtest

        # Build the schema using the same migration the production code uses
        conn = sqlite3.connect(":memory:")
        try:
            # Mirror the schema migration block at init_backtest_db
            conn.execute("""CREATE TABLE backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT, days INTEGER,
                total_signals INTEGER, overall_wr REAL, avg_rr REAL,
                status TEXT, summary TEXT, recommendations TEXT,
                config_hash TEXT
            )""")
            conn.execute("""CREATE TABLE backtest_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES backtest_runs(id),
                token TEXT, signal TEXT, price REAL, ts TEXT,
                regime TEXT, confidence INTEGER, wscore REAL,
                margin REAL, conflict TEXT,
                tp1_pct REAL, sl_pct REAL, rr1 REAL,
                tp_reached INTEGER DEFAULT 0, outcome TEXT
            )""")
            for col_def in [
                ("net_tp1_pct", "REAL"), ("net_sl_pct", "REAL"),
                ("net_rr1", "REAL"), ("breakeven_wr", "REAL"),
                ("sweep_type", "TEXT"), ("fvg_pct", "REAL"),
                ("trend_1h", "TEXT"), ("bias_4h", "TEXT"),
                ("ifvg_present", "INTEGER"), ("ifvg_direction", "TEXT"),
                ("ifvg_age_bars", "INTEGER"), ("ifvg_5m_used", "INTEGER"),
                ("session", "TEXT"), ("hour_utc", "INTEGER"),
                ("day_of_week", "INTEGER"), ("dr_location", "TEXT"),
                ("mss_quality", "TEXT"), ("fvg_quality", "TEXT"),
                ("smt_type", "TEXT"), ("smt_confirmed", "INTEGER"),
                ("entry_type", "TEXT"),
                ("matched_template_id", "TEXT"),
                ("template_scores_json", "TEXT"),
                ("mfe_pct", "REAL"), ("mae_pct", "REAL"), ("realized_r", "REAL"),
                ("net_tp2_pct", "REAL"), ("net_tp3_pct", "REAL"),
                ("tb_bin", "INTEGER"), ("tb_touch", "TEXT"),
                ("tb_ret", "REAL"), ("tb_t1", "INTEGER"),
                ("source", "TEXT DEFAULT '5M_SWEEP'"),
            ]:
                conn.execute(f"ALTER TABLE backtest_signals ADD COLUMN {col_def[0]} {col_def[1]}")

            # Verify the schema has every column the row-builder references
            cols_in_schema = {
                row[1] for row in conn.execute("PRAGMA table_info(backtest_signals)")
            }
            missing = [c for c in backtest._BACKTEST_SIGNALS_COLS
                       if c not in cols_in_schema]
            self.assertEqual(missing, [],
                f"Columns in _BACKTEST_SIGNALS_COLS missing from schema: {missing}")

            # Insert a fake row + verify
            cur = conn.execute(
                "INSERT INTO backtest_runs(run_date, days, total_signals, "
                "overall_wr, avg_rr, status) VALUES (?, ?, ?, ?, ?, ?)",
                ("2026-05-27 00:00:00", 365, 1, 100.0, 1.5, "TEST"),
            )
            run_id = cur.lastrowid

            synthetic = {
                "token": "BTC", "signal": "BUY", "price": 1.0, "ts": "t",
                "regime": "TR", "confidence": 8, "wscore": 0.5, "margin": 1.0,
                "conflict": "LOW", "tp1_pct": 1.0, "sl_pct": -1.0, "rr1": 1.0,
                "net_tp1_pct": 0.7, "net_sl_pct": -1.3, "net_rr1": 0.54,
                "breakeven_wr": 0.5, "tp_reached": 0, "outcome": "EXPIRED",
            }
            row = backtest._backtest_signal_to_row(synthetic, run_id=run_id)
            placeholders = ",".join(["?"] * len(backtest._BACKTEST_SIGNALS_COLS))
            sql = (f"INSERT INTO backtest_signals "
                   f"({','.join(backtest._BACKTEST_SIGNALS_COLS)}) "
                   f"VALUES ({placeholders})")
            # If this succeeds, the column-name/tuple-position alignment is correct
            conn.execute(sql, row)
            # Verify it landed as source='5M_SWEEP' (default for missing source key)
            stored_source = conn.execute(
                "SELECT source FROM backtest_signals WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            self.assertEqual(stored_source, "5M_SWEEP",
                "Pre-Session-2 signal dict (no source key) must default to '5M_SWEEP'")
        finally:
            conn.close()

    def test_config_hash_includes_crt_knobs(self):
        """B-CRT-S2-C2 + NEW-1 + Option S fix: _compute_run_config_hash
        must include EVERY env-overridable CRT knob so two runs differing
        only on any one of them produce different config_hashes (prevents
        DSR n_trials collision + Pareto archive overwrite + checkpoint
        cross-contamination).

        Option S fix (audit cycle-7 2026-05-27): cumulative re-audit
        FINDING-1 — earlier assertion missed CRT_FORWARD_BARS (Option E)
        and H4_CRT_OB_SCAN_LOOKBACK (Session 1). Now asserts all 7 knobs.
        """
        import backtest
        import inspect
        src = inspect.getsource(backtest._compute_run_config_hash)
        for knob in ("ENABLE_H4_CRT", "H4_CRT_DISABLED_TOKENS",
                     "H4_CRT_C2_LOOKBACK", "H4_CRT_MSS_HORIZON",
                     "H4_CRT_VALIDATION_SCHOOL",
                     # Added in Option S cleanup
                     "CRT_FORWARD_BARS", "H4_CRT_OB_SCAN_LOOKBACK",
                     # Added in v2 (Option KK)
                     "WYCKOFF_PHASE_FILTER"):
            self.assertIn(knob, src,
                          f"config_hash payload must include CRT knob {knob}")


class TestCrtScannerGates(unittest.TestCase):
    """Verify the default-OFF and blacklist gates short-circuit cleanly."""

    def setUp(self):
        _clean_crt_env()
        # Force re-import so module-level env reads pick up cleared state
        for mod in ("crt_engine", "backtest"):
            if mod in sys.modules:
                del sys.modules[mod]

    def tearDown(self):
        _clean_crt_env()

    def test_disabled_by_default(self):
        # H-4 fix: scanner now returns (signals, rejections) tuple.
        # H-1 fix: signature dropped unused c1h parameter.
        import backtest
        self.assertFalse(backtest.ENABLE_H4_CRT,
                         "ENABLE_H4_CRT must default to False")
        c4h = _flat_candles(30, t_step=14_400_000)
        c5m = _flat_candles(600, t_step=300_000)
        sigs, rej = backtest.run_backtest_token_h4_crt("BTC", c5m, c4h)
        self.assertEqual(sigs, [], "default-OFF must return empty signals list")
        self.assertIn("crt_default_off", rej, "rejection counter must record default-off")

    def test_blacklist_skips_token(self):
        os.environ["ENABLE_H4_CRT"] = "1"
        os.environ["H4_CRT_DISABLED_TOKENS"] = "POL,HBAR"
        for mod in ("crt_engine", "backtest"):
            if mod in sys.modules:
                del sys.modules[mod]
        import backtest
        c4h = _flat_candles(30, t_step=14_400_000)
        c5m = _flat_candles(600, t_step=300_000)
        sigs, rej = backtest.run_backtest_token_h4_crt("POL", c5m, c4h)
        self.assertEqual(sigs, [])
        self.assertIn("crt_blacklisted", rej)
        sigs2, rej2 = backtest.run_backtest_token_h4_crt("hbar", c5m, c4h)
        self.assertEqual(sigs2, [])
        self.assertIn("crt_blacklisted", rej2)

    def test_missing_data_returns_empty(self):
        os.environ["ENABLE_H4_CRT"] = "1"
        for mod in ("crt_engine", "backtest"):
            if mod in sys.modules:
                del sys.modules[mod]
        import backtest
        # All-empty inputs — should return ([], {'crt_no_data': 1})
        sigs, rej = backtest.run_backtest_token_h4_crt("BTC", None, None)
        self.assertEqual(sigs, [])
        self.assertIn("crt_no_data", rej)
        # Too few H4 bars
        sigs2, rej2 = backtest.run_backtest_token_h4_crt(
            "BTC",
            _flat_candles(600, t_step=300_000),
            _flat_candles(5, t_step=14_400_000),  # only 5 H4 bars
        )
        self.assertEqual(sigs2, [])
        self.assertIn("crt_insufficient_data", rej2)

    def test_flat_data_produces_no_signals(self):
        """Flat OHLCV with no swings → no sweep → no CRT → empty signals.

        Fixture sized at 5M >= WARMUP_BARS + CRT_FORWARD_BARS (210 + 576 = 786)
        so the data-sufficiency gate doesn't short-circuit before the H4
        sliding-window scan can fire. Without this, the function returns
        on crt_insufficient_data without exercising the inner scan logic.
        """
        os.environ["ENABLE_H4_CRT"] = "1"
        for mod in ("crt_engine", "backtest"):
            if mod in sys.modules:
                del sys.modules[mod]
        import backtest
        c4h = _flat_candles(30, t_step=14_400_000)
        c5m = _flat_candles(800, t_step=300_000)  # ≥ 786 to pass data gate
        sigs, rej = backtest.run_backtest_token_h4_crt("BTC", c5m, c4h)
        self.assertEqual(sigs, [],
                         "Flat data produces no swings, no sweep, no CRT")
        # At least one inner-loop rejection counter must fire — proves the
        # scanner entered the per-H4-window loop instead of bailing on data.
        self.assertTrue(
            any(k in rej for k in
                ("crt_no_setup", "crt_sub_window_too_small", "crt_late_mss_no_forward")),
            f"Expected at least one inner-loop rejection counter; got {rej}",
        )


class TestSignalSourceTags(unittest.TestCase):
    """Verify the source tag flows through signal-dict construction."""

    def test_5m_sweep_dict_carries_source(self):
        """The 5M-sweep signal dict must include source='5M_SWEEP'."""
        # We verify this via source code inspection rather than running the
        # full simulator (which requires real OHLCV + ~11 min). The source
        # tag is in the signals.append() block at backtest.py:~1173.
        import backtest
        import inspect
        src = inspect.getsource(backtest.run_backtest_token)
        self.assertIn('"source":     "5M_SWEEP"', src,
                      "5M-sweep signal dict must carry source='5M_SWEEP'")

    def test_h4_crt_dict_carries_source(self):
        """The H4-CRT signal dict construction must include source='H4_CRT'."""
        import backtest
        import inspect
        src = inspect.getsource(backtest.run_backtest_token_h4_crt)
        self.assertIn('"source":          "H4_CRT"', src,
                      "H4-CRT signal dict must carry source='H4_CRT'")
        # Verify check_outcome + triple_barrier_label are reused (parity)
        self.assertIn("check_outcome", src,
                      "CRT scanner must reuse shared check_outcome helper")
        self.assertIn("triple_barrier_label", src,
                      "CRT scanner must reuse shared TB label helper")


class TestCrtSignalShape(unittest.TestCase):
    """Verify CRT signal dict matches the schema the INSERT statement expects."""

    def setUp(self):
        _clean_crt_env()

    def tearDown(self):
        _clean_crt_env()

    def test_crt_signal_has_all_required_fields(self):
        """CRT signal dict must contain every field the INSERT references."""
        os.environ["ENABLE_H4_CRT"] = "1"
        for mod in ("crt_engine", "backtest"):
            if mod in sys.modules:
                del sys.modules[mod]
        import backtest

        # Required keys per the INSERT statement at save_to_db
        required_fields = {
            "token", "signal", "price", "ts", "regime", "confidence",
            "wscore", "margin", "conflict", "tp1_pct", "sl_pct", "rr1",
            "net_tp1_pct", "net_tp2_pct", "net_tp3_pct", "net_sl_pct",
            "net_rr1", "breakeven_wr", "sweep_type", "fvg_pct", "trend_1h",
            "bias_4h", "ifvg_present", "ifvg_direction", "ifvg_age_bars",
            "ifvg_5m_used", "session", "hour_utc", "day_of_week",
            "dr4h_location", "mss_quality", "fvg_quality", "smt_type",
            "smt_confirmed", "entry_type", "tp_reached", "outcome",
            "matched_template_id", "template_scores_json", "mfe_pct",
            "mae_pct", "realized_r", "tb_bin", "tb_touch", "tb_ret", "tb_t1",
            "source",
        }
        # We can't easily fire a real CRT detection here (synthetic OHLCV
        # rarely passes confluence). Instead inspect source for keys.
        import inspect
        src = inspect.getsource(backtest.run_backtest_token_h4_crt)
        missing = []
        for f in required_fields:
            if f'"{f}":' not in src:
                missing.append(f)
        self.assertEqual(missing, [],
                         f"CRT signal dict missing required INSERT fields: {missing}")


if __name__ == "__main__":
    unittest.main()
