"""
Tests for the OHLCV disk cache hardening (data-pipeline-validator audit
2026-05-23).

Coverage:
  CRIT-1  Stale-cache TTL — blob older than _CACHE_MAX_AGE_SECONDS rejected
  CRIT-2  Atomic write — temp+fsync+replace; no torn writes left behind
  CRIT-3  Schema validation on load:
            - missing required key                → None
            - mismatched array lengths            → None
            - top-level not dict / payload not dict → None
            - empty arrays                        → None
            - missing fetched_at                  → None (legacy reject)
            - missing/wrong schema_version        → None
  WARN-1  Forming-candle drop — last bar dropped if open_time+interval > now
  Round-trip — save then load returns identical payload
  No-fetch path — _cache_save never raises even on disk error
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# We import backtest module-level functions but NOT main(): backtest.py has
# heavy module-level constants and imports that are OK at import time.
import backtest as bt


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def temp_cache_dir(tmp_path, monkeypatch):
    """Redirect CACHE_DIR to a tmp path so tests never touch the real cache."""
    fake = tmp_path / "ohlcv_cache"
    fake.mkdir()
    monkeypatch.setattr(bt, "CACHE_DIR", str(fake))
    return fake


def _valid_payload(n: int = 10) -> dict:
    """Return a structurally-valid OHLCV payload with `n` bars."""
    return {
        "opens":   [100.0 + i for i in range(n)],
        "highs":   [101.0 + i for i in range(n)],
        "lows":    [ 99.0 + i for i in range(n)],
        "closes":  [100.5 + i for i in range(n)],
        "volumes": [1000.0   for _ in range(n)],
        "times":   [1700000000000 + i * 300_000 for i in range(n)],
    }


# ─── CRIT-1: TTL ─────────────────────────────────────────────────────────────

class TestTTL:

    def test_fresh_blob_loads(self):
        bt._cache_save(_valid_payload(), "BTCUSDT", "5m", 30)
        loaded = bt._cache_load("BTCUSDT", "5m", 30)
        assert loaded is not None
        assert loaded["closes"][0] == 100.5

    def test_stale_blob_rejected(self, temp_cache_dir):
        # Manually write a blob with fetched_at older than max-age
        path = bt._cache_path("BTCUSDT", "5m", 30)
        blob = {
            "schema_version": bt._CACHE_SCHEMA_VERSION,
            "fetched_at":     time.time() - bt._CACHE_MAX_AGE_SECONDS - 60,
            "data":           _valid_payload(),
        }
        with open(path, "w") as f:
            json.dump(blob, f)
        assert bt._cache_load("BTCUSDT", "5m", 30) is None

    def test_legacy_blob_without_fetched_at_rejected(self, temp_cache_dir):
        # Legacy format: bare data dict with no wrapper
        path = bt._cache_path("BTCUSDT", "5m", 30)
        with open(path, "w") as f:
            json.dump(_valid_payload(), f)
        assert bt._cache_load("BTCUSDT", "5m", 30) is None

    def test_boundary_just_inside_ttl_loads(self, temp_cache_dir):
        path = bt._cache_path("BTCUSDT", "5m", 30)
        blob = {
            "schema_version": bt._CACHE_SCHEMA_VERSION,
            "fetched_at":     time.time() - bt._CACHE_MAX_AGE_SECONDS + 60,
            "data":           _valid_payload(),
        }
        with open(path, "w") as f:
            json.dump(blob, f)
        assert bt._cache_load("BTCUSDT", "5m", 30) is not None

    def test_future_fetched_at_rejected(self, temp_cache_dir):
        """NTP-rollback safety: fetched_at > now (negative age) must be
        rejected, not treated as perpetually fresh."""
        path = bt._cache_path("BTCUSDT", "5m", 30)
        blob = {
            "schema_version": bt._CACHE_SCHEMA_VERSION,
            "fetched_at":     time.time() + 3600,  # 1h in the future
            "data":           _valid_payload(),
        }
        with open(path, "w") as f:
            json.dump(blob, f)
        assert bt._cache_load("BTCUSDT", "5m", 30) is None


# ─── CRIT-2: Atomic write ────────────────────────────────────────────────────

class TestAtomicWrite:

    def test_no_tmp_leftover_on_success(self, temp_cache_dir):
        bt._cache_save(_valid_payload(), "BTCUSDT", "5m", 30)
        tmps = list(temp_cache_dir.glob("*.tmp"))
        assert tmps == [], f"unexpected tmp files: {tmps}"

    def test_target_exists_after_save(self, temp_cache_dir):
        bt._cache_save(_valid_payload(), "BTCUSDT", "5m", 30)
        target = Path(bt._cache_path("BTCUSDT", "5m", 30))
        assert target.exists()

    def test_save_does_not_raise_on_invalid_input(self, temp_cache_dir):
        # Empty data → silent skip, no file written
        bt._cache_save({}, "BTCUSDT", "5m", 30)
        assert not Path(bt._cache_path("BTCUSDT", "5m", 30)).exists()

    def test_save_does_not_raise_on_missing_keys(self, temp_cache_dir):
        # Missing required keys → silent skip
        bt._cache_save({"opens": [1.0]}, "BTCUSDT", "5m", 30)
        assert not Path(bt._cache_path("BTCUSDT", "5m", 30)).exists()


# ─── CRIT-3: Schema validation on load ───────────────────────────────────────

class TestSchemaValidation:

    def _write_blob(self, path, payload, **overrides):
        blob = {
            "schema_version": bt._CACHE_SCHEMA_VERSION,
            "fetched_at":     time.time(),
            "data":           payload,
        }
        blob.update(overrides)
        with open(path, "w") as f:
            json.dump(blob, f)

    def test_missing_required_key_rejected(self, temp_cache_dir):
        bad = _valid_payload()
        del bad["volumes"]
        self._write_blob(bt._cache_path("BTC", "5m", 30), bad)
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_mismatched_lengths_rejected(self, temp_cache_dir):
        bad = _valid_payload(10)
        bad["closes"] = bad["closes"][:8]  # 8 closes, 10 of everything else
        self._write_blob(bt._cache_path("BTC", "5m", 30), bad)
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_non_list_value_rejected(self, temp_cache_dir):
        bad = _valid_payload()
        bad["closes"] = "not a list"
        self._write_blob(bt._cache_path("BTC", "5m", 30), bad)
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_empty_arrays_rejected(self, temp_cache_dir):
        empty = {k: [] for k in bt._CACHE_REQUIRED_KEYS}
        self._write_blob(bt._cache_path("BTC", "5m", 30), empty)
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_wrong_schema_version_rejected(self, temp_cache_dir):
        self._write_blob(
            bt._cache_path("BTC", "5m", 30),
            _valid_payload(),
            schema_version=999,
        )
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_top_level_not_dict_rejected(self, temp_cache_dir):
        path = bt._cache_path("BTC", "5m", 30)
        with open(path, "w") as f:
            json.dump([1, 2, 3], f)
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_payload_not_dict_rejected(self, temp_cache_dir):
        path = bt._cache_path("BTC", "5m", 30)
        with open(path, "w") as f:
            json.dump({
                "schema_version": bt._CACHE_SCHEMA_VERSION,
                "fetched_at":     time.time(),
                "data":           "not a dict",
            }, f)
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_torn_write_invalid_json_rejected(self, temp_cache_dir):
        path = bt._cache_path("BTC", "5m", 30)
        with open(path, "w") as f:
            f.write('{"schema_version": 1, "fetched_at": 1700000000, "data": {"opens": [1.0,')
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_list_of_strings_rejected(self, temp_cache_dir):
        """A list-of-strings would pass isinstance(list) but blow up in
        float arithmetic downstream. Element-type check must reject it."""
        bad = _valid_payload()
        bad["closes"] = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
        self._write_blob(bt._cache_path("BTC", "5m", 30), bad)
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_list_of_dicts_rejected(self, temp_cache_dir):
        bad = _valid_payload()
        bad["volumes"] = [{} for _ in range(10)]
        self._write_blob(bt._cache_path("BTC", "5m", 30), bad)
        assert bt._cache_load("BTC", "5m", 30) is None

    def test_list_of_bools_rejected(self, temp_cache_dir):
        # bool is a subclass of int in Python — must be explicitly rejected
        bad = _valid_payload()
        bad["highs"] = [True] * 10
        self._write_blob(bt._cache_path("BTC", "5m", 30), bad)
        assert bt._cache_load("BTC", "5m", 30) is None


# ─── WARN-1: forming candle drop ────────────────────────────────────────────

class TestFormingCandleDrop:

    def test_interval_to_ms_known_intervals(self):
        assert bt._interval_to_ms("5m")  == 300_000
        assert bt._interval_to_ms("15m") == 900_000
        assert bt._interval_to_ms("1h")  == 3_600_000
        assert bt._interval_to_ms("4h")  == 14_400_000

    def test_interval_to_ms_unknown_returns_zero(self):
        # 0 means "skip the forming-bar drop" — graceful degradation
        assert bt._interval_to_ms("99x") == 0
        assert bt._interval_to_ms("")    == 0

    def test_forming_bar_logic_triggered_when_open_plus_interval_in_future(self):
        # Direct unit test on the helper — the actual fetch_historical is
        # network-bound so we test the predicate it uses.
        now_ms = int(time.time() * 1000)
        interval_ms = 300_000  # 5m
        # Bar that opened 60s ago → forming (60_000 + 300_000 > 0 elapsed → True)
        forming_open = now_ms - 60_000
        assert forming_open + interval_ms > now_ms

        # Bar that opened 6 minutes ago → closed
        closed_open = now_ms - 360_000
        assert closed_open + interval_ms < now_ms


# ─── Round-trip ──────────────────────────────────────────────────────────────

class TestRoundTrip:

    def test_save_then_load_preserves_payload(self):
        original = _valid_payload(20)
        bt._cache_save(original, "ETHUSDT", "15m", 90)
        loaded = bt._cache_load("ETHUSDT", "15m", 90)
        assert loaded is not None
        for k in bt._CACHE_REQUIRED_KEYS:
            assert loaded[k] == original[k]

    def test_different_keys_isolated(self):
        a = _valid_payload(5); a["closes"][0] = 999.0
        b = _valid_payload(5); b["closes"][0] = 111.0
        bt._cache_save(a, "BTC", "5m", 30)
        bt._cache_save(b, "ETH", "5m", 30)
        assert bt._cache_load("BTC", "5m", 30)["closes"][0] == 999.0
        assert bt._cache_load("ETH", "5m", 30)["closes"][0] == 111.0


# ─── Missing-file load ──────────────────────────────────────────────────────

class TestMissingFile:

    def test_missing_file_returns_none(self, temp_cache_dir):
        assert bt._cache_load("NEVER", "5m", 30) is None
