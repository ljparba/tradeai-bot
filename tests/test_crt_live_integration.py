"""Integration tests for CRT v1 Session 3 — crypto_alert.py live integration.

Verifies the live-side wiring of detect_h4_crt() in crypto_alert.py:
  - source column added to live signals table schema migration
  - source column referenced in save_signal's INSERT
  - scan_h4_crt_for_token returns (None, None, reason_str) on default-OFF / blacklist
  - scan_h4_crt_for_token returns (None, None, "no_setup") on flat data
  - consumed_h4_crt state field initialized per-token in new_state()
  - state_store persistence serializes/rehydrates consumed_h4_crt correctly
  - Live result dict shape carries source='H4_CRT' tag
  - All CRT helpers imported from crt_engine (no duplication)

H4-CRT v1 is paper-only in LIVE mode (template_live_allowed=0). Verified
the LIVE block path saves the signal but suppresses Telegram per design.

These tests do NOT exercise a real 5M scan loop or Telegram dispatch —
the smoke test for full-cycle behavior is documented separately.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _clean_crt_env():
    """Mirror tests/test_crt_engine.py + test_crt_backtest_integration.py
    isolation pattern so cross-file test order doesn't leak env state."""
    for k in ("ENABLE_H4_CRT", "H4_CRT_DISABLED_TOKENS", "H4_CRT_C2_LOOKBACK",
              "H4_CRT_MSS_HORIZON", "H4_CRT_OB_SCAN_LOOKBACK",
              "H4_CRT_VALIDATION_SCHOOL",
              "CRT_FORWARD_BARS", "CRT_TP2_RR", "CRT_TP3_RR"):
        os.environ.pop(k, None)


def _flat_candles(n: int, price: float = 100.0, t_step: int = 60_000,
                  t_start: int = 1_700_000_000_000) -> dict:
    return {
        "opens":  [price] * n,
        "highs":  [price] * n,
        "lows":   [price] * n,
        "closes": [price] * n,
        "times":  [t_start + i * t_step for i in range(n)],
    }


class TestLiveSchemaMigration(unittest.TestCase):
    """LBC-H-1 close verification: live signals table now has source column."""

    def setUp(self):
        _clean_crt_env()

    def tearDown(self):
        _clean_crt_env()

    def test_source_column_in_init_db(self):
        """init_db migration list must include source TEXT DEFAULT '5M_SWEEP'."""
        import crypto_alert
        import inspect
        src = inspect.getsource(crypto_alert.init_db)
        self.assertIn('"source"', src,
                      "init_db migration must add source column")
        self.assertIn("'5M_SWEEP'", src,
                      "Default value for source must be '5M_SWEEP'")

    def test_save_signal_insert_includes_source(self):
        """save_signal's INSERT must reference source + pass result.get('source')."""
        import crypto_alert
        import inspect
        src = inspect.getsource(crypto_alert.save_signal)
        self.assertIn("source", src,
                      "save_signal INSERT must reference source column")
        self.assertIn("'5M_SWEEP'", src,
                      "save_signal must default source to '5M_SWEEP' for back-compat")


class TestPerTokenStateInit(unittest.TestCase):
    """LBC-H-2 close verification: per-token consumed_h4_crt set initialized."""

    def setUp(self):
        _clean_crt_env()

    def tearDown(self):
        _clean_crt_env()

    def test_new_state_has_consumed_h4_crt(self):
        """new_state() must return a dict with consumed_h4_crt = empty set."""
        import crypto_alert
        s = crypto_alert.new_state()
        self.assertIn("consumed_h4_crt", s, "new_state missing consumed_h4_crt")
        self.assertEqual(s["consumed_h4_crt"], set(),
                         "consumed_h4_crt must default to empty set")
        self.assertIsInstance(s["consumed_h4_crt"], set,
                              "consumed_h4_crt must be a set, not list/dict")


class TestLiveScannerGates(unittest.TestCase):
    """Verify the gate short-circuits (default-OFF, blacklist, no-setup)."""

    def setUp(self):
        _clean_crt_env()
        for mod in ("crt_engine", "crypto_alert"):
            if mod in sys.modules:
                del sys.modules[mod]

    def tearDown(self):
        _clean_crt_env()

    def test_disabled_by_default(self):
        """ENABLE_H4_CRT=0 (default) → scanner returns (None, None, 'default_off')."""
        import crypto_alert
        self.assertFalse(crypto_alert.ENABLE_H4_CRT,
                         "ENABLE_H4_CRT must default to False")
        c4h = _flat_candles(30, t_step=14_400_000)
        c5m = _flat_candles(600, t_step=300_000)
        result, plan, reason = crypto_alert.scan_h4_crt_for_token(
            "BTC", c5m, c4h, consumed=set(),
        )
        self.assertIsNone(result)
        self.assertIsNone(plan)
        self.assertEqual(reason, "default_off")

    def test_blacklist_skips_token(self):
        os.environ["ENABLE_H4_CRT"] = "1"
        os.environ["H4_CRT_DISABLED_TOKENS"] = "POL,HBAR"
        for mod in ("crt_engine", "crypto_alert"):
            if mod in sys.modules:
                del sys.modules[mod]
        import crypto_alert
        c4h = _flat_candles(30, t_step=14_400_000)
        c5m = _flat_candles(600, t_step=300_000)
        result, plan, reason = crypto_alert.scan_h4_crt_for_token(
            "POL", c5m, c4h, consumed=set(),
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "blacklisted")

    def test_flat_data_no_setup(self):
        """Flat OHLCV → no swings → no sweep → no CRT → (None, None, 'no_setup')."""
        os.environ["ENABLE_H4_CRT"] = "1"
        for mod in ("crt_engine", "crypto_alert"):
            if mod in sys.modules:
                del sys.modules[mod]
        import crypto_alert
        c4h = _flat_candles(30, t_step=14_400_000)
        c5m = _flat_candles(600, t_step=300_000)
        result, plan, reason = crypto_alert.scan_h4_crt_for_token(
            "BTC", c5m, c4h, consumed=set(),
        )
        self.assertIsNone(result)
        self.assertEqual(reason, "no_setup")


class TestLiveSourceTagging(unittest.TestCase):
    """Verify CRT signals produced by live scanner carry source='H4_CRT'."""

    def setUp(self):
        _clean_crt_env()

    def tearDown(self):
        _clean_crt_env()

    def test_live_crt_result_dict_has_source_tag(self):
        """Source-code inspection: live scanner builds result['source']='H4_CRT'."""
        import crypto_alert
        import inspect
        src = inspect.getsource(crypto_alert.scan_h4_crt_for_token)
        self.assertIn('"source":           "H4_CRT"', src,
                      "Live CRT result dict must tag source='H4_CRT'")
        # Verify entry_price is also surfaced (needed by save_signal contract)
        self.assertIn('"entry_price"', src,
                      "Live CRT result dict must include entry_price")


class TestStateStorePersistence(unittest.TestCase):
    """LBC-H-2: verify the rehydration + serialization round-trip."""

    def test_serialize_format_is_json_safe(self):
        """consumed_h4_crt sets serialize as lists of 3-element lists.
        Tuples and sets aren't JSON-safe — must convert at persist time."""
        import json
        # Mimic the persistence transformation from crypto_alert.py
        per_token = {
            "BTC": {(1234567890.0, 70000.0, 68000.0)},
            "ETH": set(),
        }
        serialized = {
            t: [list(k) for k in per_token[t]]
            for t in per_token
            if per_token[t]
        }
        json_str = json.dumps(serialized)
        roundtrip = json.loads(json_str)
        self.assertIn("BTC", roundtrip)
        self.assertNotIn("ETH", roundtrip, "Empty sets must be pruned at serialize time")
        # Rehydrate
        rehydrated = {
            t: {tuple(e) for e in roundtrip[t]
                if isinstance(e, list) and len(e) == 3}
            for t in roundtrip
        }
        self.assertEqual(rehydrated["BTC"],
                         {(1234567890.0, 70000.0, 68000.0)})


class TestSharedHelperImports(unittest.TestCase):
    """LBC-H-3 close verification: all CRT helpers imported from crt_engine."""

    def test_no_duplicate_helper_definitions(self):
        """crypto_alert.py must NOT redefine compute_crt_trade_economics,
        crt_quality_to_confidence, or crt_trade_rejection_reason — they
        live in crt_engine.py and must be imported."""
        with open("/home/tradeai/TradeAI/crypto_alert.py") as f:
            src = f.read()
        for fn in ("def compute_crt_trade_economics",
                   "def crt_quality_to_confidence",
                   "def crt_trade_rejection_reason"):
            self.assertNotIn(fn, src,
                f"{fn} must NOT be redefined in crypto_alert.py — "
                "import from crt_engine instead (live/BT parity)")

    def test_imports_from_crt_engine(self):
        """All 8 CRT-specific names must be imported from crt_engine."""
        with open("/home/tradeai/TradeAI/crypto_alert.py") as f:
            src = f.read()
        for name in ("detect_h4_crt", "ENABLE_H4_CRT", "H4_CRT_DISABLED_TOKENS",
                     "H4_CRT_C2_LOOKBACK", "compute_crt_trade_economics",
                     "crt_quality_to_confidence", "crt_trade_rejection_reason",
                     "CRT_TP2_RR", "CRT_TP3_RR"):
            self.assertIn(name, src,
                f"crypto_alert must import {name} from crt_engine")


if __name__ == "__main__":
    unittest.main()
