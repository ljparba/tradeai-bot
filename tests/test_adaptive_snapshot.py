"""
Tests for BUG-SNAPSHOT-1 fix in adaptive_engine._snapshot_weights().

Verifies:
  T1 — _snapshot_weights: weight_before reflects actual in-memory weight, not DEFAULT
  T2 — _snapshot_weights: weight_after reflects actual in-memory weight
  T3 — bootstrap_before: both columns == pre-bootstrap weights (not DEFAULT)
  T4 — bootstrap_after: weight_before == pre-bootstrap, weight_after == post-bootstrap
  T5 — reset_token: weight_before == actual old weight, weight_after == DEFAULT
  T6 — reset_token: weight_before != DEFAULT when old weight != DEFAULT
  T7 — health_check still returns all 5 required fields
  T8 — existing weights survive round-trip through _snapshot_weights (no mutation)
"""

import sys
import os
import sqlite3
import math
import tempfile
import atexit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import adaptive_engine as ae_mod

# T-ISO (2026-05-22): Redirect adaptive_engine.DB_PATH to a temp DB BEFORE any
# import that reads it. Previous behavior wrote weight_history rows tagged
# trigger='test_*' into the production data/signals.db, producing ~6k rows of
# synthetic history that could be mistaken for real OGD activity in
# forensic queries. Mirrors the validate_phase36.py pattern.
_TMP_DB = tempfile.NamedTemporaryFile(suffix="_test_adaptive_snapshot.db", delete=False).name
ae_mod.DB_PATH = _TMP_DB

def _cleanup_tmp_db():
    try: os.unlink(_TMP_DB)
    except OSError: pass
atexit.register(_cleanup_tmp_db)

from adaptive_engine import (
    AdaptiveWeightEngine,
    DEFAULT_WEIGHTS,
    FEATURES,
    DB_PATH,
    _connect,
    _init_adaptive_tables,
)

# ── helpers ──────────────────────────────────────────────────────────────────

TEST_TOKEN = "_TEST_SNAP_"   # underscore prefix guarantees no collision with live tokens


def _clean(conn):
    """Remove test token rows from all tables."""
    conn.execute("DELETE FROM token_weights  WHERE token=?", (TEST_TOKEN,))
    conn.execute("DELETE FROM weight_history WHERE token=?", (TEST_TOKEN,))
    conn.commit()


def _seed_weights(conn, weights: dict):
    """Insert specific weights for TEST_TOKEN directly into DB."""
    now = "2026-01-01 00:00:00"
    for feat, w in weights.items():
        conn.execute(
            "INSERT OR REPLACE INTO token_weights "
            "(token, feature, weight, velocity, n_updates, updated_at) VALUES (?,?,?,?,?,?)",
            (TEST_TOKEN, feat, w, 0.0, 99, now),
        )
    conn.commit()


def _get_history(conn, trigger: str) -> list:
    """Fetch weight_history rows for TEST_TOKEN and given trigger."""
    return conn.execute(
        "SELECT feature, weight_before, weight_after FROM weight_history "
        "WHERE token=? AND trigger=? ORDER BY feature",
        (TEST_TOKEN, trigger),
    ).fetchall()


def _fresh_engine() -> AdaptiveWeightEngine:
    """Return a fresh AdaptiveWeightEngine that has read TEST_TOKEN from DB."""
    return AdaptiveWeightEngine()


# ── T1 / T2 — _snapshot_weights records actual weights, not DEFAULT ───────────

def test_snapshot_records_actual_weights():
    _init_adaptive_tables()
    conn = _connect()
    _clean(conn)

    # Seed non-default weights (deliberately far from DEFAULT_WEIGHTS)
    seeded = {
        "fvg_quality":    0.40,
        "mss_quality":    0.20,
        "session":        0.10,
        "confidence":     0.10,
        "trend_strength": 0.10,
        "dr_location":    0.10,
    }
    _seed_weights(conn, seeded)

    engine = _fresh_engine()
    # Snapshot without weights_before → weight_before should be current in-memory weight
    engine._snapshot_weights(trigger="test_actual", run_id=None)

    rows = _get_history(conn, "test_actual")
    _clean(conn)
    conn.close()

    assert rows, "T1/T2: no weight_history rows written"
    assert len(rows) == len(FEATURES), f"T1/T2: expected {len(FEATURES)} rows, got {len(rows)}"

    feature_map = {feat: (before, after) for feat, before, after in rows}
    for feat in FEATURES:
        assert feat in feature_map, f"T1/T2: missing feature {feat}"
        before, after = feature_map[feat]
        expected = seeded[feat]

        # T1: weight_before must equal actual seeded weight, not DEFAULT
        assert abs(before - expected) < 1e-5, (
            f"T1 FAIL {feat}: weight_before={before:.6f} expected={expected:.6f} "
            f"(DEFAULT={DEFAULT_WEIGHTS[feat]:.6f}) — still using DEFAULT?"
        )

        # T2: weight_after must equal actual weight
        assert abs(after - expected) < 1e-5, (
            f"T2 FAIL {feat}: weight_after={after:.6f} expected={expected:.6f}"
        )

    print("PASS T1/T2: _snapshot_weights records actual weights for weight_before and weight_after")


# ── T3 / T4 — bootstrap before/after have correct before values ───────────────

def test_bootstrap_snapshot_before_after():
    _init_adaptive_tables()
    conn = _connect()
    _clean(conn)

    # Seed known weights
    pre_weights = {
        "fvg_quality":    0.40,
        "mss_quality":    0.15,
        "session":        0.10,
        "confidence":     0.15,
        "trend_strength": 0.10,
        "dr_location":    0.10,
    }
    _seed_weights(conn, pre_weights)
    conn.close()

    engine = _fresh_engine()

    # Directly simulate what bootstrap_from_backtest does
    pre_bootstrap = {tok: dict(w) for tok, w in engine._weights.items()}
    engine._snapshot_weights(trigger="bootstrap_before", run_id=999)

    # Simulate one OGD update to change weights away from pre_weights
    if TEST_TOKEN in engine._weights:
        for feat in FEATURES:
            engine._weights[TEST_TOKEN][feat] = DEFAULT_WEIGHTS[feat]  # force to defaults
        engine._n[TEST_TOKEN] = 150  # past OGD_MIN_SAMPLES

    # Now snapshot after
    engine._snapshot_weights(trigger="bootstrap_after", run_id=999,
                             weights_before=pre_bootstrap)

    conn = _connect()
    before_rows = {feat: (wb, wa) for feat, wb, wa in _get_history(conn, "bootstrap_before")}
    after_rows  = {feat: (wb, wa) for feat, wb, wa in _get_history(conn, "bootstrap_after")}
    _clean(conn)
    conn.execute("DELETE FROM weight_history WHERE token=? AND run_id=?", (TEST_TOKEN, 999))
    conn.commit()
    conn.close()

    # T3: bootstrap_before — both columns should equal pre_weights (actual, not DEFAULT)
    assert before_rows, "T3: no bootstrap_before rows"
    for feat in FEATURES:
        assert feat in before_rows, f"T3: missing feat {feat} in bootstrap_before"
        wb, wa = before_rows[feat]
        exp = pre_weights[feat]
        assert abs(wb - exp) < 1e-5, (
            f"T3 FAIL {feat}: bootstrap_before weight_before={wb:.6f} expected={exp:.6f}"
        )
        assert abs(wa - exp) < 1e-5, (
            f"T3 FAIL {feat}: bootstrap_before weight_after={wa:.6f} expected={exp:.6f}"
        )

    # T4: bootstrap_after — weight_before = pre_weights, weight_after = DEFAULT (simulated post-boot)
    assert after_rows, "T4: no bootstrap_after rows"
    for feat in FEATURES:
        assert feat in after_rows, f"T4: missing feat {feat} in bootstrap_after"
        wb, wa = after_rows[feat]
        exp_before = pre_weights[feat]
        exp_after  = DEFAULT_WEIGHTS[feat]  # we forced defaults above
        assert abs(wb - exp_before) < 1e-5, (
            f"T4 FAIL {feat}: bootstrap_after weight_before={wb:.6f} expected={exp_before:.6f}"
        )
        assert abs(wa - exp_after) < 1e-5, (
            f"T4 FAIL {feat}: bootstrap_after weight_after={wa:.6f} expected={exp_after:.6f}"
        )

    print("PASS T3: bootstrap_before records actual pre-bootstrap weights")
    print("PASS T4: bootstrap_after weight_before=pre, weight_after=post")


# ── T5 / T6 — reset_token records correct old weights ────────────────────────

def test_reset_token_weight_history():
    _init_adaptive_tables()
    conn = _connect()
    _clean(conn)

    # Seed non-default weights
    old_weights = {
        "fvg_quality":    0.38,
        "mss_quality":    0.22,
        "session":        0.12,
        "confidence":     0.12,
        "trend_strength": 0.08,
        "dr_location":    0.08,
    }
    _seed_weights(conn, old_weights)
    conn.close()

    engine = _fresh_engine()
    engine.reset_token(TEST_TOKEN)

    conn = _connect()
    rows = _get_history(conn, "reset")
    _clean(conn)
    conn.close()

    assert rows, "T5/T6: no reset weight_history rows"
    assert len(rows) == len(FEATURES), f"T5/T6: expected {len(FEATURES)} rows, got {len(rows)}"

    feature_map = {feat: (before, after) for feat, before, after in rows}
    for feat in FEATURES:
        assert feat in feature_map, f"T5: missing feature {feat}"
        before, after = feature_map[feat]

        # T5: weight_after must equal DEFAULT_WEIGHTS
        assert abs(after - DEFAULT_WEIGHTS[feat]) < 1e-5, (
            f"T5 FAIL {feat}: weight_after={after:.6f} expected DEFAULT={DEFAULT_WEIGHTS[feat]:.6f}"
        )

        # T6: weight_before must equal the actual old weight, NOT the default
        assert abs(before - old_weights[feat]) < 1e-5, (
            f"T6 FAIL {feat}: weight_before={before:.6f} expected old={old_weights[feat]:.6f} "
            f"(DEFAULT={DEFAULT_WEIGHTS[feat]:.6f})"
        )
        # Also confirm old_weights[feat] != DEFAULT for at least some features
    # Verify the test data actually differs from DEFAULT (otherwise T6 would be trivially true)
    differing = [f for f in FEATURES if abs(old_weights[f] - DEFAULT_WEIGHTS[f]) > 0.001]
    assert differing, "T6: test weights identical to DEFAULT — test data error"

    print("PASS T5: reset_token weight_after == DEFAULT_WEIGHTS")
    print(f"PASS T6: reset_token weight_before == actual old weight (not DEFAULT) for {len(differing)} features")


# ── T7 — health_check still returns all 5 required fields ─────────────────────

def test_health_check_fields():
    _init_adaptive_tables()
    engine = _fresh_engine()
    result = engine.health_check()

    required_fields = {"max_weight", "is_degenerate", "n_updates", "weight_entropy", "last_updated"}

    for token, info in result.items():
        missing = required_fields - set(info.keys())
        assert not missing, f"T7 FAIL: token {token} missing fields {missing}"
        assert isinstance(info["max_weight"],    float), f"T7: max_weight not float for {token}"
        assert isinstance(info["is_degenerate"], bool),  f"T7: is_degenerate not bool for {token}"
        assert isinstance(info["n_updates"],     int),   f"T7: n_updates not int for {token}"
        assert isinstance(info["weight_entropy"], float), f"T7: weight_entropy not float for {token}"

    print(f"PASS T7: health_check returned all 5 fields for {len(result)} tokens")


# ── T8 — _snapshot_weights does not mutate in-memory weights ──────────────────

def test_snapshot_does_not_mutate():
    _init_adaptive_tables()
    conn = _connect()
    _clean(conn)

    seeded = {
        "fvg_quality":    0.30,
        "mss_quality":    0.20,
        "session":        0.15,
        "confidence":     0.15,
        "trend_strength": 0.10,
        "dr_location":    0.10,
    }
    _seed_weights(conn, seeded)
    conn.close()

    engine = _fresh_engine()
    weights_before_snap = dict(engine._weights.get(TEST_TOKEN, {}))

    engine._snapshot_weights(trigger="test_mutation_check")

    weights_after_snap = dict(engine._weights.get(TEST_TOKEN, {}))

    conn = _connect()
    _clean(conn)
    conn.close()

    assert weights_before_snap == weights_after_snap, (
        "T8 FAIL: _snapshot_weights mutated in-memory weights"
    )
    print("PASS T8: _snapshot_weights does not mutate in-memory weights")


# ── T9 — snapshot without weights_before: weight_before == weight_after (no phantom DEFAULT) ──

def test_snapshot_no_weights_before_is_self_consistent():
    _init_adaptive_tables()
    conn = _connect()
    _clean(conn)

    seeded = {
        "fvg_quality":    0.45,
        "mss_quality":    0.20,
        "session":        0.10,
        "confidence":     0.10,
        "trend_strength": 0.10,
        "dr_location":    0.05,
    }
    _seed_weights(conn, seeded)
    conn.close()

    engine = _fresh_engine()
    engine._snapshot_weights(trigger="test_self_consistent")

    conn = _connect()
    rows = _get_history(conn, "test_self_consistent")
    _clean(conn)
    conn.close()

    for feat, before, after in rows:
        assert abs(before - after) < 1e-7, (
            f"T9 FAIL {feat}: without weights_before, weight_before={before} != weight_after={after}"
        )
        assert abs(after - seeded[feat]) < 1e-5, (
            f"T9 FAIL {feat}: weight_after={after} != seeded={seeded[feat]}"
        )
        # Must NOT be DEFAULT value (this is the core of BUG-SNAPSHOT-1)
        if abs(seeded[feat] - DEFAULT_WEIGHTS[feat]) > 0.001:
            assert abs(before - DEFAULT_WEIGHTS[feat]) > 0.001, (
                f"T9 FAIL {feat}: weight_before={before} is the DEFAULT value — bug not fixed"
            )

    print("PASS T9: without weights_before, weight_before==weight_after==actual weight (not DEFAULT)")


# ── runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("T1/T2 — snapshot records actual weights",         test_snapshot_records_actual_weights),
        ("T3/T4 — bootstrap before/after correct",         test_bootstrap_snapshot_before_after),
        ("T5/T6 — reset_token correct weight history",     test_reset_token_weight_history),
        ("T7    — health_check fields intact",             test_health_check_fields),
        ("T8    — snapshot does not mutate weights",       test_snapshot_does_not_mutate),
        ("T9    — no weights_before is self-consistent",   test_snapshot_no_weights_before_is_self_consistent),
    ]

    passed = 0
    failed = 0
    errors = []

    print("=" * 62)
    print("  BUG-SNAPSHOT-1 Test Suite")
    print("=" * 62)

    for name, fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {name}")
            print(f"      {e}")
            errors.append((name, str(e)))
            failed += 1
        except Exception as e:
            print(f"ERROR {name}")
            print(f"      {type(e).__name__}: {e}")
            errors.append((name, f"{type(e).__name__}: {e}"))
            failed += 1

    print("=" * 62)
    print(f"  {passed} passed  |  {failed} failed")
    print("=" * 62)

    if failed:
        sys.exit(1)
