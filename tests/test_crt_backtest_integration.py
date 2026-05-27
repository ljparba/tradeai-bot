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
    for k in ("ENABLE_H4_CRT", "H4_CRT_DISABLED_TOKENS", "H4_CRT_C2_LOOKBACK",
              "H4_CRT_MSS_HORIZON", "H4_CRT_OB_SCAN_LOOKBACK",
              "H4_CRT_VALIDATION_SCHOOL"):
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
        import backtest
        import inspect
        src = inspect.getsource(backtest.save_to_db)
        self.assertIn("source", src,
                      "save_to_db INSERT must reference the `source` column")
        # 48-column VALUES list (was 47 pre-Session-2)
        self.assertIn("?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?", src,
                      "VALUES placeholder count must be 48 (47 fields + source)")


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
        import backtest
        self.assertFalse(backtest.ENABLE_H4_CRT,
                         "ENABLE_H4_CRT must default to False")
        c4h = _flat_candles(30, t_step=14_400_000)  # H4 = 4h in ms
        c1h = _flat_candles(120, t_step=3_600_000)  # H1 = 1h in ms
        c5m = _flat_candles(600, t_step=300_000)    # 5M = 5min in ms
        result = backtest.run_backtest_token_h4_crt("BTC", c5m, c1h, c4h)
        self.assertEqual(result, [],
                         "default-OFF must return empty list immediately")

    def test_blacklist_skips_token(self):
        os.environ["ENABLE_H4_CRT"] = "1"
        os.environ["H4_CRT_DISABLED_TOKENS"] = "POL,HBAR"
        for mod in ("crt_engine", "backtest"):
            if mod in sys.modules:
                del sys.modules[mod]
        import backtest
        c4h = _flat_candles(30, t_step=14_400_000)
        c1h = _flat_candles(120, t_step=3_600_000)
        c5m = _flat_candles(600, t_step=300_000)
        self.assertEqual(backtest.run_backtest_token_h4_crt("POL", c5m, c1h, c4h), [])
        self.assertEqual(backtest.run_backtest_token_h4_crt("hbar", c5m, c1h, c4h), [])

    def test_missing_data_returns_empty(self):
        os.environ["ENABLE_H4_CRT"] = "1"
        for mod in ("crt_engine", "backtest"):
            if mod in sys.modules:
                del sys.modules[mod]
        import backtest
        # All-empty inputs
        self.assertEqual(backtest.run_backtest_token_h4_crt("BTC", None, None, None), [])
        # Too few H4 bars
        self.assertEqual(
            backtest.run_backtest_token_h4_crt(
                "BTC",
                _flat_candles(600, t_step=300_000),
                _flat_candles(120, t_step=3_600_000),
                _flat_candles(5, t_step=14_400_000),  # only 5 H4 bars
            ),
            [],
        )

    def test_flat_data_produces_no_signals(self):
        """Flat OHLCV with no swings → no sweep → no CRT → empty list."""
        os.environ["ENABLE_H4_CRT"] = "1"
        for mod in ("crt_engine", "backtest"):
            if mod in sys.modules:
                del sys.modules[mod]
        import backtest
        c4h = _flat_candles(30, t_step=14_400_000)
        c1h = _flat_candles(120, t_step=3_600_000)
        c5m = _flat_candles(600, t_step=300_000)
        result = backtest.run_backtest_token_h4_crt("BTC", c5m, c1h, c4h)
        self.assertEqual(result, [],
                         "Flat data produces no swings, no sweep, no CRT")


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
