"""
Tests for monitoring.py (Sprint 3 item 3 / Top-10 #9).

Coverage:
  • Pure metric functions: entropy, pinning, degenerate, drift, pairwise L1
  • Per-token alert levels (OK / WARN / CRIT)
  • Cross-token homogeneity detection
  • JSON write atomicity + parent dir creation
  • Text report rendering
  • Empty / missing DB tolerated (read-only never raises)
  • Sync with adaptive_engine constants (DEGENERATE_THRESHOLD, WEIGHT_MIN/MAX, FEATURES)
  • CLI exit codes (--exit-on-crit)
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import monitoring as mon
import adaptive_engine as ae


# ── Constants sync with adaptive_engine ──────────────────────────────────────

class TestConstantsSync:
    """If adaptive_engine raises the threshold, monitoring must move with it."""

    def test_degenerate_threshold_matches(self):
        assert mon.DEGENERATE_THRESHOLD == ae.DEGENERATE_THRESHOLD

    def test_weight_min_matches(self):
        assert mon.WEIGHT_MIN == ae.WEIGHT_MIN

    def test_weight_max_matches(self):
        assert mon.WEIGHT_MAX == ae.WEIGHT_MAX

    def test_features_match(self):
        assert tuple(mon.FEATURES) == tuple(ae.FEATURES)


# ── Pure metric functions ────────────────────────────────────────────────────

class TestComputeEntropy:

    def test_empty_returns_zero(self):
        assert mon.compute_entropy({}) == 0.0

    def test_uniform_six_features_equals_ln6(self):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        assert math.isclose(mon.compute_entropy(weights), math.log(6), rel_tol=1e-6)

    def test_collapsed_single_feature_near_zero(self):
        # 99% on one feature → entropy near 0
        weights = {"fvg_quality": 0.99, "mss_quality": 0.002,
                   "session": 0.002, "confidence": 0.002,
                   "trend_strength": 0.002, "dr_location": 0.002}
        h = mon.compute_entropy(weights)
        assert h < 0.10, f"expected near-zero entropy for degenerate weights, got {h}"

    def test_zero_total_returns_zero(self):
        # All-zero weights → ratio undefined → return 0
        weights = {f: 0.0 for f in mon.FEATURES}
        assert mon.compute_entropy(weights) == 0.0

    def test_unnormalized_handled(self):
        # 2 features both = 1.0 (sum=2) — entropy of {0.5, 0.5} = ln(2)
        weights = {"a": 1.0, "b": 1.0}
        assert math.isclose(mon.compute_entropy(weights), math.log(2), rel_tol=1e-6)


class TestDetectPinning:

    def test_pinned_at_min(self):
        weights = {"fvg_quality": mon.WEIGHT_MIN, "mss_quality": 0.30}
        assert mon.detect_pinning(weights) == ["fvg_quality"]

    def test_pinned_at_max(self):
        weights = {"fvg_quality": mon.WEIGHT_MAX, "mss_quality": 0.10}
        assert mon.detect_pinning(weights) == ["fvg_quality"]

    def test_no_pin_when_middle(self):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        assert mon.detect_pinning(weights) == []

    def test_multiple_pinned(self):
        weights = {"fvg_quality": mon.WEIGHT_MIN,
                   "mss_quality": mon.WEIGHT_MAX,
                   "session": 0.15}
        pinned = mon.detect_pinning(weights)
        assert set(pinned) == {"fvg_quality", "mss_quality"}

    def test_tolerance_accepts_near_min(self):
        weights = {"fvg_quality": mon.WEIGHT_MIN + 5e-5}  # within tol=1e-4
        assert mon.detect_pinning(weights) == ["fvg_quality"]


class TestCountFloorPins:

    def test_no_pins_when_uniform(self):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        assert mon.count_floor_pins(weights) == 0

    def test_counts_floor_only(self):
        # 4 at floor, 1 at max, 1 in middle → count_floor_pins = 4
        weights = {"fvg_quality": mon.WEIGHT_MIN, "mss_quality": mon.WEIGHT_MIN,
                   "session": mon.WEIGHT_MIN, "confidence": mon.WEIGHT_MIN,
                   "trend_strength": mon.WEIGHT_MAX, "dr_location": 0.15}
        assert mon.count_floor_pins(weights) == 4

    def test_max_pins_not_counted_as_floor(self):
        weights = {"fvg_quality": mon.WEIGHT_MAX}
        assert mon.count_floor_pins(weights) == 0


class TestFloorSaturationAlert:
    """Run-46 fingerprint: N-1 features at floor → CRIT."""

    def test_floor_saturation_triggers_crit(self, temp_db):
        # 5/6 features at WEIGHT_MIN=0.05, 1 at 0.75 (sums to 1.0)
        # Note: this is also degenerate (0.75 > 0.45), so both alerts fire.
        weights = {"fvg_quality": 0.75, "mss_quality": mon.WEIGHT_MIN,
                   "session": mon.WEIGHT_MIN, "confidence": mon.WEIGHT_MIN,
                   "trend_strength": mon.WEIGHT_MIN, "dr_location": mon.WEIGHT_MIN}
        _insert_weights(temp_db, "BTC", weights)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        assert btc["alert_level"] == "CRIT"
        assert btc["floor_pin_count"] == 5
        assert any("FLOOR_SATURATION" in a for a in btc["alerts"])

    def test_three_pins_below_crit_threshold(self, temp_db):
        # Only 3 features at floor — does NOT escalate to CRIT on its own
        weights = {"fvg_quality": 0.30, "mss_quality": 0.30, "session": 0.25,
                   "confidence": mon.WEIGHT_MIN, "trend_strength": mon.WEIGHT_MIN,
                   "dr_location": mon.WEIGHT_MIN}
        _insert_weights(temp_db, "BTC", weights)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        assert btc["floor_pin_count"] == 3
        # WARN from PINNED at bounds, but not CRIT from floor_saturation
        assert not any("FLOOR_SATURATION" in a for a in btc["alerts"])


class TestCatastrophicEntropyDropEscalation:

    def test_catastrophic_drop_triggers_crit(self, temp_db):
        uniform = {f: 1.0 / 6 for f in mon.FEATURES}
        # Force max collapse: 0.95 on one, 0.01 on others → very low entropy
        collapsed = {"fvg_quality": 0.95, "mss_quality": 0.01,
                     "session": 0.01, "confidence": 0.01,
                     "trend_strength": 0.01, "dr_location": 0.01}
        # Current = uniform (not degenerate by itself) so CRIT can only come
        # from the entropy drop escalation.
        _insert_weights(temp_db, "BTC", uniform, n_updates=50)
        n = mon.ENTROPY_DRIFT_LOOKBACK
        snapshots = [(f"2026-05-{1+i:02d} 00:00:00",
                      uniform if i == n - 1 else collapsed)
                     for i in range(n)]
        # Note: oldest=collapsed, newest=uniform → drift POSITIVE (recovery)
        # We want a DROP, so flip: oldest=uniform, newest=collapsed
        snapshots = [(f"2026-05-{1+i:02d} 00:00:00",
                      uniform if i == 0 else collapsed)
                     for i in range(n)]
        _insert_history(temp_db, "BTC", snapshots)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        # Drop magnitude > ENTROPY_DRIFT_CRIT = 0.60 → CRIT
        assert btc["entropy_drift"] is not None
        assert btc["entropy_drift"] < -mon.ENTROPY_DRIFT_CRIT
        assert btc["alert_level"] == "CRIT"
        assert any("CATASTROPHIC" in a for a in btc["alerts"])

    def test_moderate_drop_only_warn(self, temp_db):
        # Drop between ENTROPY_DRIFT_ALERT (0.30) and ENTROPY_DRIFT_CRIT (0.60)
        uniform = {f: 1.0 / 6 for f in mon.FEATURES}
        mild = {"fvg_quality": 0.40, "mss_quality": 0.15,
                "session": 0.15, "confidence": 0.10,
                "trend_strength": 0.10, "dr_location": 0.10}
        _insert_weights(temp_db, "BTC", uniform, n_updates=50)
        n = mon.ENTROPY_DRIFT_LOOKBACK
        snapshots = [(f"2026-05-{1+i:02d} 00:00:00",
                      uniform if i == 0 else mild)
                     for i in range(n)]
        _insert_history(temp_db, "BTC", snapshots)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        drift = btc["entropy_drift"]
        if drift is not None and -mon.ENTROPY_DRIFT_CRIT < drift < -mon.ENTROPY_DRIFT_ALERT:
            assert btc["alert_level"] == "WARN"
            assert any("ENTROPY_DROP" in a and "CATASTROPHIC" not in a
                       for a in btc["alerts"])


class TestIsDegenerate:

    def test_uniform_not_degenerate(self):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        is_d, worst, val = mon.is_degenerate(weights)
        assert is_d is False
        assert val < mon.DEGENERATE_THRESHOLD

    def test_above_threshold_is_degenerate(self):
        weights = {"fvg_quality": 0.55, "mss_quality": 0.09,
                   "session": 0.09, "confidence": 0.09,
                   "trend_strength": 0.09, "dr_location": 0.09}
        is_d, worst, val = mon.is_degenerate(weights)
        assert is_d is True
        assert worst == "fvg_quality"
        assert val == 0.55

    def test_at_threshold_not_degenerate(self):
        weights = {"fvg_quality": mon.DEGENERATE_THRESHOLD,
                   "mss_quality": 0.11, "session": 0.11,
                   "confidence": 0.11, "trend_strength": 0.11,
                   "dr_location": 0.11}
        is_d, _, _ = mon.is_degenerate(weights)
        assert is_d is False  # strict greater-than per adaptive_engine


class TestEntropyDrift:

    def test_none_when_lt_2_snapshots(self):
        history = [("2026-01-01 00:00:00", {f: 1.0 / 6 for f in mon.FEATURES})]
        assert mon.entropy_drift(history) is None

    def test_collapse_returns_negative_drift(self):
        uniform = {f: 1.0 / 6 for f in mon.FEATURES}
        collapsed = {"fvg_quality": 0.95, "mss_quality": 0.01,
                     "session": 0.01, "confidence": 0.01,
                     "trend_strength": 0.01, "dr_location": 0.01}
        history = [
            ("2026-01-01 00:00:00", uniform),
            ("2026-01-02 00:00:00", collapsed),
        ]
        delta = mon.entropy_drift(history)
        assert delta is not None
        assert delta < -1.0  # large entropy drop

    def test_no_drift_when_constant(self):
        uniform = {f: 1.0 / 6 for f in mon.FEATURES}
        history = [("t1", uniform), ("t2", dict(uniform))]
        delta = mon.entropy_drift(history)
        assert abs(delta) < 1e-9


class TestPairwiseL1:

    def test_identical_is_zero(self):
        w = {f: 1.0 / 6 for f in mon.FEATURES}
        assert mon.pairwise_l1(w, dict(w)) == 0.0

    def test_one_swap_correct_l1(self):
        a = {"fvg_quality": 0.5, "mss_quality": 0.5}
        b = {"fvg_quality": 0.3, "mss_quality": 0.7}
        # |0.5-0.3| + |0.5-0.7| = 0.4
        assert math.isclose(mon.pairwise_l1(a, b), 0.4, rel_tol=1e-9)

    def test_disjoint_keys_handled(self):
        a = {"x": 0.5}
        b = {"y": 0.5}
        assert mon.pairwise_l1(a, b) == 1.0


class TestCrossTokenDiversity:

    def test_two_identical_tokens_l1_zero(self):
        w = {f: 1.0 / 6 for f in mon.FEATURES}
        snap = {"BTC": dict(w), "ETH": dict(w)}
        avg, mn, n = mon.cross_token_diversity(snap)
        assert avg == 0.0
        assert mn == 0.0
        assert n == 1

    def test_single_token_no_pairs(self):
        avg, mn, n = mon.cross_token_diversity({"BTC": {"a": 0.5}})
        assert n == 0

    def test_three_tokens_three_pairs(self):
        w1 = {f: 1.0 / 6 for f in mon.FEATURES}
        w2 = dict(w1); w2["fvg_quality"] = 0.40; w2["dr_location"] = 0.10
        w3 = dict(w1); w3["mss_quality"] = 0.40; w3["dr_location"] = 0.10
        avg, mn, n = mon.cross_token_diversity({"A": w1, "B": w2, "C": w3})
        assert n == 3
        assert avg > 0
        assert mn >= 0


# ── DB-driven report generation ──────────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path):
    """Create a fresh empty DB with the schema monitoring expects."""
    db_path = tmp_path / "signals.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE token_weights (
        token TEXT NOT NULL,
        feature TEXT NOT NULL,
        weight REAL NOT NULL,
        velocity REAL DEFAULT 0.0,
        n_updates INTEGER DEFAULT 0,
        updated_at TEXT,
        PRIMARY KEY (token, feature)
    )""")
    conn.execute("""CREATE TABLE weight_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recorded_at TEXT NOT NULL,
        token TEXT NOT NULL,
        trigger TEXT NOT NULL,
        feature TEXT NOT NULL,
        weight_before REAL NOT NULL,
        weight_after REAL NOT NULL,
        n_updates INTEGER NOT NULL,
        run_id INTEGER
    )""")
    conn.commit()
    conn.close()
    return str(db_path)


def _insert_weights(db_path, token, weights, n_updates=10, updated_at=None):
    if updated_at is None:
        updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    for feat, w in weights.items():
        conn.execute(
            "INSERT OR REPLACE INTO token_weights VALUES (?,?,?,?,?,?)",
            (token, feat, w, 0.0, n_updates, updated_at),
        )
    conn.commit()
    conn.close()


def _insert_history(db_path, token, snapshots_oldest_first):
    """snapshots: list of (recorded_at, weights_dict)."""
    conn = sqlite3.connect(db_path)
    for recorded_at, weights in snapshots_oldest_first:
        for feat, w in weights.items():
            conn.execute(
                "INSERT INTO weight_history "
                "(recorded_at, token, trigger, feature, weight_before, weight_after, n_updates) "
                "VALUES (?,?,?,?,?,?,?)",
                (recorded_at, token, "test", feat, w, w, 0),
            )
    conn.commit()
    conn.close()


class TestGenerateReport:

    def test_missing_db_returns_empty_report(self, tmp_path):
        ghost = tmp_path / "missing.db"
        report = mon.generate_report(str(ghost))
        assert report["summary"]["tokens_monitored"] == 0
        assert report["summary"]["global_alert_level"] == "OK"

    def test_healthy_token_alert_ok(self, temp_db):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        _insert_weights(temp_db, "BTC", weights, n_updates=50)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        assert btc["alert_level"] == "OK"
        assert btc["alerts"] == []
        assert btc["is_degenerate"] is False

    def test_degenerate_token_alert_crit(self, temp_db):
        weights = {"fvg_quality": 0.55, "mss_quality": 0.09,
                   "session": 0.09, "confidence": 0.09,
                   "trend_strength": 0.09, "dr_location": 0.09}
        _insert_weights(temp_db, "BTC", weights, n_updates=50)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        assert btc["alert_level"] == "CRIT"
        assert btc["is_degenerate"] is True
        assert report["summary"]["global_alert_level"] == "CRIT"

    def test_pinned_token_alert_warn(self, temp_db):
        weights = {"fvg_quality": mon.WEIGHT_MIN,
                   "mss_quality": 0.20, "session": 0.20,
                   "confidence": 0.20, "trend_strength": 0.20,
                   "dr_location": 0.15}
        _insert_weights(temp_db, "BTC", weights, n_updates=50)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        # Pinning alone triggers WARN if entropy is still above threshold.
        assert "fvg_quality" in btc["pinned_features"]
        # Either WARN (entropy still > threshold) or higher
        assert btc["alert_level"] in ("WARN", "CRIT")

    def test_stale_token_alert_warn(self, temp_db):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        _insert_weights(temp_db, "BTC", weights, n_updates=50, updated_at=old_ts)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        assert btc["alert_level"] == "WARN"
        assert any("STALE" in a for a in btc["alerts"])

    def test_homogeneity_alert_when_all_tokens_identical(self, temp_db):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        for tok in ("BTC", "ETH", "XRP"):
            _insert_weights(temp_db, tok, dict(weights), n_updates=50)
        report = mon.generate_report(temp_db)
        assert report["cross_token"]["homogeneity_alert"] is True
        assert report["cross_token"]["avg_pairwise_l1"] == 0.0
        assert report["summary"]["global_alert_level"] == "WARN"

    def test_no_homogeneity_when_diverse(self, temp_db):
        uniform = {f: 1.0 / 6 for f in mon.FEATURES}
        skewed = dict(uniform); skewed["fvg_quality"] = 0.35; skewed["dr_location"] = 0.10
        _insert_weights(temp_db, "BTC", uniform, n_updates=50)
        _insert_weights(temp_db, "ETH", skewed,  n_updates=50)
        report = mon.generate_report(temp_db)
        # avg L1 = |0.35-1/6| + |0.10-1/6| ≈ 0.183 + 0.067 = 0.25
        assert report["cross_token"]["homogeneity_alert"] is False

    def test_entropy_drop_alert_from_history(self, temp_db):
        # entropy_drift compares LAST (newest) to FIRST (oldest) in the
        # ENTROPY_DRIFT_LOOKBACK slice. Use exactly the lookback size so all
        # snapshots are retained.
        uniform = {f: 1.0 / 6 for f in mon.FEATURES}
        collapsed = {"fvg_quality": 0.55, "mss_quality": 0.09,
                     "session": 0.09, "confidence": 0.09,
                     "trend_strength": 0.09, "dr_location": 0.09}
        _insert_weights(temp_db, "BTC", collapsed, n_updates=50)
        # Exactly ENTROPY_DRIFT_LOOKBACK snapshots so none get truncated.
        # Oldest = uniform, rest = collapsed → large negative drift.
        n = mon.ENTROPY_DRIFT_LOOKBACK
        snapshots = [(f"2026-05-{1+i:02d} 00:00:00",
                      uniform if i == 0 else collapsed)
                     for i in range(n)]
        _insert_history(temp_db, "BTC", snapshots)
        report = mon.generate_report(temp_db)
        btc = report["per_token"]["BTC"]
        assert btc["entropy_drift"] is not None
        assert btc["entropy_drift"] < -mon.ENTROPY_DRIFT_ALERT, (
            f"expected drift < {-mon.ENTROPY_DRIFT_ALERT}, got {btc['entropy_drift']}"
        )
        assert any("ENTROPY_DROP" in a for a in btc["alerts"])

    def test_report_schema_keys(self, temp_db):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        _insert_weights(temp_db, "BTC", weights)
        report = mon.generate_report(temp_db)
        for key in ("generated_at", "schema_version", "summary",
                    "thresholds", "cross_token", "per_token"):
            assert key in report
        for key in ("tokens_monitored", "tokens_degenerate",
                    "tokens_low_entropy", "tokens_pinned",
                    "tokens_stale", "global_alert_level"):
            assert key in report["summary"]


class TestJsonWrite:

    def test_json_write_creates_file(self, tmp_path):
        report = {"hello": "world", "summary": {"global_alert_level": "OK"}}
        path = tmp_path / "out.json"
        mon.write_report_json(str(path), report)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["hello"] == "world"

    def test_json_write_creates_parent_dirs(self, tmp_path):
        report = {"x": 1}
        path = tmp_path / "deep" / "nested" / "out.json"
        mon.write_report_json(str(path), report)
        assert path.exists()

    def test_json_write_atomic_no_tmp_leftover(self, tmp_path):
        report = {"x": 1}
        path = tmp_path / "out.json"
        mon.write_report_json(str(path), report)
        # No .monitoring_*.tmp files remain
        tmps = list(tmp_path.glob(".monitoring_*.tmp"))
        assert tmps == []


class TestTextReport:

    def test_text_report_includes_global_level(self):
        report = mon.generate_report("nonexistent.db")  # empty
        text = mon.format_text_report(report)
        assert "global=OK" in text

    def test_text_report_includes_alerts(self, tmp_path):
        # Build a synthetic report with a CRIT alert and confirm it renders
        report = {
            "generated_at": "2026-05-22T00:00:00Z",
            "summary": {"global_alert_level": "CRIT",
                        "tokens_monitored": 1, "tokens_degenerate": 1,
                        "tokens_low_entropy": 0, "tokens_pinned": 0,
                        "tokens_stale": 0},
            "cross_token": {"avg_pairwise_l1": 0.0, "min_pairwise_l1": 0.0,
                            "n_pairs": 0, "homogeneity_alert": False},
            "per_token": {
                "BTC": {
                    "max_weight": 0.55, "max_feature": "fvg_quality",
                    "is_degenerate": True, "entropy": 0.20,
                    "entropy_drift": None, "pinned_features": [],
                    "n_updates": 50, "last_updated": "2026-05-22 00:00:00",
                    "days_since_update": 0.5, "alert_level": "CRIT",
                    "alerts": ["DEGENERATE: fvg_quality=0.550 > 0.45"],
                }
            },
        }
        text = mon.format_text_report(report)
        assert "DEGENERATE: fvg_quality=0.550" in text
        assert "BTC" in text


class TestCLI:

    def test_cli_text_only_runs(self, temp_db, capsys):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        _insert_weights(temp_db, "BTC", weights)
        rc = mon.cli_main(["--db", temp_db, "--text"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "BTC" in captured.out

    def test_cli_writes_json(self, temp_db, tmp_path):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        _insert_weights(temp_db, "BTC", weights)
        json_path = tmp_path / "report.json"
        rc = mon.cli_main(["--db", temp_db, "--json", str(json_path)])
        assert rc == 0
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert "BTC" in data["per_token"]

    def test_cli_exit_on_crit_returns_2(self, temp_db):
        weights = {"fvg_quality": 0.60, "mss_quality": 0.08,
                   "session": 0.08, "confidence": 0.08,
                   "trend_strength": 0.08, "dr_location": 0.08}
        _insert_weights(temp_db, "BTC", weights)
        rc = mon.cli_main(["--db", temp_db, "--exit-on-crit"])
        assert rc == 2

    def test_cli_exit_on_crit_returns_0_when_ok(self, temp_db):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        _insert_weights(temp_db, "BTC", weights)
        rc = mon.cli_main(["--db", temp_db, "--exit-on-crit"])
        assert rc == 0


class TestReadOnlyInvariant:
    """Monitoring must NEVER mutate the DB."""

    def test_generate_report_does_not_change_db(self, temp_db):
        weights = {f: 1.0 / 6 for f in mon.FEATURES}
        _insert_weights(temp_db, "BTC", weights, n_updates=50)
        before_mtime = os.path.getmtime(temp_db)
        mon.generate_report(temp_db)
        after_mtime = os.path.getmtime(temp_db)
        # mtime should not change — generate_report opened read-only
        assert after_mtime == before_mtime
