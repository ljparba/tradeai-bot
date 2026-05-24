"""
Tests for phase2_data.py — Phase 2 Step 1: Live Data Collection & Readiness Validation

Covers:
  V1  — validate_record: valid minimal record passes
  V2  — validate_record: test token rejected
  V3  — validate_record: missing field (direction) rejected
  V4  — validate_record: invalid fvg_quality rejected
  V5  — validate_record: invalid mss_quality rejected
  V6  — validate_record: invalid session rejected
  V7  — validate_record: invalid dr_location rejected
  V8  — validate_record: sl_pct=0 rejected
  V9  — validate_record: not closed (no close_time) rejected
  V10 — validate_record: missing feature_scores_json rejected
  V11 — validate_record: legacy text feature_scores_json sanitised and passes
  V12 — validate_record: feature_scores_json with out-of-range float rejected
  V13 — validate_record: direction from 'signal' key is accepted

  G1  — check_readiness: empty list -> all gates fail, ok=False
  G2  — check_readiness: < GATE_MIN_TOTAL records -> min_total fails
  G3  — check_readiness: single token -> min_tokens fails
  G4  — check_readiness: no losses -> min_loss_fraction fails
  G5  — check_readiness: all BUY -> buy_sell_balance fails
  G6  — check_readiness: single session -> session_diversity fails
  G7  — check_readiness: single FVG quality -> fvg_diversity fails
  G8  — check_readiness: balanced dataset -> all gates pass, ok=True

  R1  — training_report: empty list returns without error
  R2  — training_report: non-empty synthetic list returns without error and contains expected sections
  R3  — training_report: ready tokens listed when min_per_token met

  DB1 — get_training_records: real DB returns ([], []) with zero live closed signals
"""

import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import phase2_data as p2
from phase2_data import (
    validate_record,
    check_readiness,
    training_report,
    get_training_records,
    GATE_MIN_TOTAL,
    GATE_MIN_PER_TOKEN,
    GATE_MIN_TOKENS,
    VALID_OUTCOMES,
    REQUIRED_OGD_FEATURES,
)

# ── Synthetic record factory ──────────────────────────────────────────────────

_CLEAN_SCORES = json.dumps({
    "fvg_quality":    1.0,
    "mss_quality":    0.75,
    "session":        1.0,
    "confidence":     0.7,
    "trend_strength": 0.6,
    "dr_location":    0.9,
})

_LEGACY_SCORES = json.dumps({
    "fvg_quality":    "HIGH",      # legacy text
    "mss_quality":    "MEDIUM",    # legacy text
    "session":        "NY_AM_KZ",  # legacy text
    "confidence":     0.7,
    "trend_strength": 0.6,
    "dr_location":    0.9,
})


def _make_row(overrides: dict = None) -> dict:
    """Return a minimal valid synthetic DB row, with optional field overrides."""
    base = {
        "id":                  1,
        "token":               "BTC",
        "direction":           "BUY",
        "confidence":          7,
        "trend_1h":            "BULLISH",
        "session":             "NY_AM_KZ",
        "dr_location":         "DISCOUNT",
        "mss_quality":         "HIGH",
        "fvg_quality":         "HIGH",
        "sl_pct":              1.0,
        "tp1_pct":             2.0,
        "feature_scores_json": _CLEAN_SCORES,
        "strategy_version":    "v1",
        "entry_time":          "2026-05-20 10:00:00",
        "hour_utc":            10,
        "outcome":             "WIN",
        "profit_pct":          2.0,
        "close_time":          "2026-05-20 12:00:00",
    }
    if overrides:
        base.update(overrides)
    return base


def _make_records(
    n: int,
    token: str = "BTC",
    outcome: str = "WIN",
    direction: str = "BUY",
    session: str = "NY_AM_KZ",
    fvg_quality: str = "HIGH",
) -> list:
    """Return a list of n clean synthetic records for check_readiness testing."""
    rows = []
    for i in range(n):
        row = _make_row({
            "id":          i + 1,
            "token":       token,
            "outcome":     outcome,
            "direction":   direction,
            "session":     session,
            "fvg_quality": fvg_quality,
        })
        ok, reason = validate_record(row)
        assert ok, f"_make_records: built an invalid row: {reason}"
        # Build clean record directly
        rows.append(p2._make_clean_record(row))
    return rows


def _make_balanced_dataset() -> list:
    """Return a dataset that passes all 6 gates."""
    records = []
    # 2 tokens × 16 records = 32 total (> GATE_MIN_TOTAL=30, each token > GATE_MIN_PER_TOKEN=10)
    for tok in ["BTC", "ETH"]:
        # 8 WIN BUY + 4 SELL WIN + 4 LOSS SELL = varied outcomes + directions
        for _ in range(8):
            records += _make_records(1, token=tok, outcome="WIN", direction="BUY",
                                     session="NY_AM_KZ",   fvg_quality="HIGH")
        for _ in range(4):
            records += _make_records(1, token=tok, outcome="WIN", direction="SELL",
                                     session="LONDON_KZ",  fvg_quality="MEDIUM")
        for _ in range(4):
            records += _make_records(1, token=tok, outcome="LOSS", direction="SELL",
                                     session="ASIA_KZ",    fvg_quality="LOW")
    return records


# ═══════════════════════════════════════════════════════════
# V1–V13: validate_record
# ═══════════════════════════════════════════════════════════

def test_validate_valid_record():
    ok, reason = validate_record(_make_row())
    assert ok, f"V1 FAIL: valid row rejected: {reason}"
    print("PASS V1: valid record accepted")


def test_validate_test_token_rejected():
    ok, reason = validate_record(_make_row({"token": "_TEST_"}))
    assert not ok, "V2 FAIL: test token was not rejected"
    assert "test_token" in reason, f"V2 FAIL: unexpected reason: {reason}"
    print(f"PASS V2: test token rejected ({reason})")


def test_validate_missing_direction():
    ok, reason = validate_record(_make_row({"direction": "", "signal": ""}))
    assert not ok, "V3 FAIL: missing direction was not rejected"
    assert "direction" in reason, f"V3 FAIL: unexpected reason: {reason}"
    print(f"PASS V3: missing direction rejected ({reason})")


def test_validate_invalid_fvg_quality():
    ok, reason = validate_record(_make_row({"fvg_quality": "NONE"}))
    assert not ok, "V4 FAIL: NONE fvg_quality was not rejected"
    assert "fvg_quality" in reason, f"V4 FAIL: unexpected reason: {reason}"
    print(f"PASS V4: invalid fvg_quality rejected ({reason})")


def test_validate_invalid_mss_quality():
    ok, reason = validate_record(_make_row({"mss_quality": "PERFECT"}))
    assert not ok, "V5 FAIL: invalid mss_quality not rejected"
    assert "mss_quality" in reason, f"V5 FAIL: unexpected reason: {reason}"
    print(f"PASS V5: invalid mss_quality rejected ({reason})")


def test_validate_invalid_session():
    ok, reason = validate_record(_make_row({"session": "MIDNIGHT"}))
    assert not ok, "V6 FAIL: invalid session not rejected"
    assert "session" in reason, f"V6 FAIL: unexpected reason: {reason}"
    print(f"PASS V6: invalid session rejected ({reason})")


def test_validate_invalid_dr_location():
    ok, reason = validate_record(_make_row({"dr_location": "ABOVE_HIGH"}))
    assert not ok, "V7 FAIL: invalid dr_location not rejected"
    assert "dr_location" in reason, f"V7 FAIL: unexpected reason: {reason}"
    print(f"PASS V7: invalid dr_location rejected ({reason})")


def test_validate_sl_pct_zero():
    ok, reason = validate_record(_make_row({"sl_pct": 0}))
    assert not ok, "V8 FAIL: sl_pct=0 was not rejected"
    assert "sl_pct" in reason, f"V8 FAIL: unexpected reason: {reason}"
    print(f"PASS V8: sl_pct=0 rejected ({reason})")


def test_validate_not_closed():
    ok, reason = validate_record(_make_row({"close_time": None, "closed_at": None}))
    assert not ok, "V9 FAIL: open trade was not rejected"
    assert "not_closed" in reason, f"V9 FAIL: unexpected reason: {reason}"
    print(f"PASS V9: open trade rejected ({reason})")


def test_validate_missing_feature_scores():
    ok, reason = validate_record(_make_row({"feature_scores_json": None}))
    assert not ok, "V10 FAIL: missing feature_scores_json not rejected"
    assert "feature_scores" in reason or "missing" in reason, f"V10 FAIL: unexpected reason: {reason}"
    print(f"PASS V10: missing feature_scores_json rejected ({reason})")


def test_validate_legacy_text_feature_scores():
    ok, reason = validate_record(_make_row({"feature_scores_json": _LEGACY_SCORES}))
    assert ok, f"V11 FAIL: legacy text feature scores rejected: {reason}"
    print("PASS V11: legacy text feature_scores_json sanitised and accepted")


def test_validate_out_of_range_feature_score():
    bad_scores = json.dumps({
        "fvg_quality":    1.5,  # > 1.0
        "mss_quality":    0.75,
        "session":        1.0,
        "confidence":     0.7,
        "trend_strength": 0.6,
        "dr_location":    0.9,
    })
    ok, reason = validate_record(_make_row({"feature_scores_json": bad_scores}))
    assert not ok, "V12 FAIL: out-of-range feature score not rejected"
    assert "out_of_range" in reason or "range" in reason, f"V12 FAIL: unexpected reason: {reason}"
    print(f"PASS V12: out-of-range feature score rejected ({reason})")


def test_validate_signal_key_as_direction():
    """Records from DB may expose direction via 'signal' column rather than 'direction'."""
    row = _make_row()
    row.pop("direction", None)
    row["signal"] = "SELL"
    ok, reason = validate_record(row)
    assert ok, f"V13 FAIL: 'signal' key not accepted as direction: {reason}"
    print("PASS V13: 'signal' key accepted as direction")


# ═══════════════════════════════════════════════════════════
# G1–G8: check_readiness
# ═══════════════════════════════════════════════════════════

def test_readiness_empty_records():
    r = check_readiness(records=[])
    assert not r["ok"], "G1 FAIL: empty list should not pass"
    assert r["n_valid"] == 0, f"G1 FAIL: n_valid={r['n_valid']}"
    assert len(r["blockers"]) == len(r["gates"]), (
        f"G1 FAIL: not all gates blocked with empty list"
    )
    print(f"PASS G1: empty list -> {len(r['blockers'])} gates failed, ok=False")


def test_readiness_insufficient_total():
    # 10 records < GATE_MIN_TOTAL=30, two tokens
    records = (
        _make_records(5, token="BTC", outcome="WIN",  direction="BUY") +
        _make_records(3, token="ETH", outcome="LOSS", direction="SELL") +
        _make_records(2, token="BTC", outcome="LOSS", direction="SELL")
    )
    r = check_readiness(records=records)
    assert "min_total" in r["blockers"], (
        f"G2 FAIL: min_total should fail with {len(records)} records"
    )
    assert not r["ok"], "G2 FAIL: should not be ok"
    print(f"PASS G2: {len(records)} records -> min_total fails")


def test_readiness_single_token():
    # 35 records of single token — meets total but min_tokens fails
    records = (
        _make_records(21, token="BTC", outcome="WIN",  direction="BUY",  session="NY_AM_KZ") +
        _make_records(7,  token="BTC", outcome="LOSS", direction="SELL", session="LONDON_KZ") +
        _make_records(7,  token="BTC", outcome="WIN",  direction="SELL", session="ASIA_KZ")
    )
    r = check_readiness(records=records)
    assert "min_tokens" in r["blockers"], (
        f"G3 FAIL: min_tokens should fail with 1 token (ready_tokens={r['ready_tokens']})"
    )
    assert not r["ok"], "G3 FAIL: should not be ok"
    print(f"PASS G3: single token -> min_tokens fails (ready_tokens={r['ready_tokens']})")


def test_readiness_no_losses():
    # All wins — min_loss_fraction fails
    records = (
        _make_records(16, token="BTC", outcome="WIN", direction="BUY",  session="NY_AM_KZ") +
        _make_records(16, token="ETH", outcome="WIN", direction="SELL", session="LONDON_KZ")
    )
    r = check_readiness(records=records)
    assert "min_loss_fraction" in r["blockers"], (
        f"G4 FAIL: min_loss_fraction should fail with 0 losses"
    )
    assert not r["ok"], "G4 FAIL: should not be ok"
    print(f"PASS G4: no losses -> min_loss_fraction fails")


def test_readiness_all_buys():
    # All BUY — buy_sell_balance fails
    records = (
        _make_records(14, token="BTC", outcome="WIN",  direction="BUY", session="NY_AM_KZ") +
        _make_records(6,  token="BTC", outcome="LOSS", direction="BUY", session="LONDON_KZ") +
        _make_records(14, token="ETH", outcome="WIN",  direction="BUY", session="ASIA_KZ") +
        _make_records(6,  token="ETH", outcome="LOSS", direction="BUY", session="NY_AM_KZ")
    )
    r = check_readiness(records=records)
    assert "buy_sell_balance" in r["blockers"], (
        f"G5 FAIL: buy_sell_balance should fail with all-BUY"
    )
    assert not r["ok"], "G5 FAIL: should not be ok"
    print(f"PASS G5: all BUY -> buy_sell_balance fails")


def test_readiness_single_session():
    # All NY_AM_KZ — session_diversity fails
    records = (
        _make_records(13, token="BTC", outcome="WIN",  direction="BUY",  session="NY_AM_KZ") +
        _make_records(6,  token="BTC", outcome="LOSS", direction="SELL", session="NY_AM_KZ") +
        _make_records(13, token="ETH", outcome="WIN",  direction="BUY",  session="NY_AM_KZ") +
        _make_records(6,  token="ETH", outcome="LOSS", direction="SELL", session="NY_AM_KZ")
    )
    r = check_readiness(records=records)
    assert "session_diversity" in r["blockers"], (
        f"G6 FAIL: session_diversity should fail with 100% NY_AM_KZ"
    )
    assert not r["ok"], "G6 FAIL: should not be ok"
    print(f"PASS G6: single session -> session_diversity fails")


def test_readiness_single_fvg():
    # All HIGH FVG — fvg_diversity fails
    records = (
        _make_records(13, token="BTC", outcome="WIN",  direction="BUY",  session="NY_AM_KZ",  fvg_quality="HIGH") +
        _make_records(3,  token="BTC", outcome="LOSS", direction="SELL", session="LONDON_KZ", fvg_quality="HIGH") +
        _make_records(13, token="ETH", outcome="WIN",  direction="BUY",  session="ASIA_KZ",   fvg_quality="HIGH") +
        _make_records(3,  token="ETH", outcome="LOSS", direction="SELL", session="OVERNIGHT", fvg_quality="HIGH")
    )
    r = check_readiness(records=records)
    assert "fvg_diversity" in r["blockers"], (
        f"G7 FAIL: fvg_diversity should fail with 100% HIGH FVG (blockers={r['blockers']})"
    )
    assert not r["ok"], "G7 FAIL: should not be ok"
    print(f"PASS G7: single FVG quality -> fvg_diversity fails")


def test_readiness_all_gates_pass():
    records = _make_balanced_dataset()
    r = check_readiness(records=records)
    if not r["ok"]:
        for name, g in r["gates"].items():
            if not g["passed"]:
                print(f"  FAIL gate {name}: {g['detail']}")
    assert r["ok"], f"G8 FAIL: balanced dataset did not pass — blockers={r['blockers']}"
    assert len(r["blockers"]) == 0, f"G8 FAIL: blockers={r['blockers']}"
    assert len(r["ready_tokens"]) >= GATE_MIN_TOKENS, (
        f"G8 FAIL: ready_tokens={r['ready_tokens']}"
    )
    print(f"PASS G8: balanced dataset passes all gates "
          f"(n={r['n_valid']}, tokens={r['ready_tokens']})")


# ═══════════════════════════════════════════════════════════
# R1–R3: training_report
# ═══════════════════════════════════════════════════════════

def test_report_empty():
    report = training_report(records=[])
    assert isinstance(report, str) and len(report) > 0, "R1 FAIL: empty report"
    assert "No valid" in report or "NOT READY" in report, (
        f"R1 FAIL: empty report missing expected text\n{report}"
    )
    print("PASS R1: training_report with empty records runs without error")


def test_report_non_empty():
    records = _make_balanced_dataset()
    report = training_report(records=records)
    assert isinstance(report, str), "R2 FAIL: report not a string"
    # Check for expected section headers
    for section in ["Trades per Token", "Direction Balance", "Outcome Distribution",
                     "FVG Quality", "Retraining Readiness Gates"]:
        assert section in report, f"R2 FAIL: section '{section}' not found in report"
    assert "READY" in report, "R2 FAIL: readiness status not shown"
    print("PASS R2: training_report with synthetic data contains all expected sections")


def test_report_ready_tokens_listed():
    records = _make_balanced_dataset()
    report = training_report(records=records)
    r = check_readiness(records=records)
    for tok in r["ready_tokens"]:
        assert tok in report, f"R3 FAIL: ready token {tok} not mentioned in report"
    print(f"PASS R3: ready tokens {r['ready_tokens']} listed in report")


# ═══════════════════════════════════════════════════════════
# DB1: get_training_records against real DB
# ═══════════════════════════════════════════════════════════

def test_get_training_records_real_db():
    """With zero live closed signals in DB, should return ([], [])."""
    valid, rejected = get_training_records()
    # There may or may not be live signals; the function must not crash
    assert isinstance(valid,    list), "DB1 FAIL: valid not a list"
    assert isinstance(rejected, list), "DB1 FAIL: rejected not a list"
    # All valid records must have the required keys
    required_keys = {
        "signal_id", "token", "direction", "outcome", "confidence",
        "session", "dr_location", "mss_quality", "fvg_quality",
        "fvg_score", "mss_score", "session_score", "conf_score",
        "trend_strength", "dr_score", "ogd_scores",
        "sl_pct", "profit_pct", "r_multiple",
        "entry_time", "close_time", "strategy_version",
    }
    for rec in valid:
        missing = required_keys - set(rec.keys())
        assert not missing, f"DB1 FAIL: valid record missing keys {missing}"
    print(f"PASS DB1: get_training_records returns ({len(valid)}, {len(rejected)}) "
          f"without error, all required keys present")


# ── runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("V1  — valid record accepted",                        test_validate_valid_record),
        ("V2  — test token rejected",                          test_validate_test_token_rejected),
        ("V3  — missing direction rejected",                   test_validate_missing_direction),
        ("V4  — invalid fvg_quality rejected",                 test_validate_invalid_fvg_quality),
        ("V5  — invalid mss_quality rejected",                 test_validate_invalid_mss_quality),
        ("V6  — invalid session rejected",                     test_validate_invalid_session),
        ("V7  — invalid dr_location rejected",                 test_validate_invalid_dr_location),
        ("V8  — sl_pct=0 rejected",                            test_validate_sl_pct_zero),
        ("V9  — open trade rejected",                          test_validate_not_closed),
        ("V10 — missing feature_scores rejected",              test_validate_missing_feature_scores),
        ("V11 — legacy text feature_scores accepted",          test_validate_legacy_text_feature_scores),
        ("V12 — out-of-range feature score rejected",          test_validate_out_of_range_feature_score),
        ("V13 — 'signal' key accepted as direction",           test_validate_signal_key_as_direction),
        ("G1  — empty list, all gates fail",                   test_readiness_empty_records),
        ("G2  — insufficient total",                           test_readiness_insufficient_total),
        ("G3  — single token",                                 test_readiness_single_token),
        ("G4  — no losses",                                    test_readiness_no_losses),
        ("G5  — all BUY",                                      test_readiness_all_buys),
        ("G6  — single session",                               test_readiness_single_session),
        ("G7  — single FVG quality",                           test_readiness_single_fvg),
        ("G8  — balanced dataset passes all gates",            test_readiness_all_gates_pass),
        ("R1  — report: empty records",                        test_report_empty),
        ("R2  — report: sections present",                     test_report_non_empty),
        ("R3  — report: ready tokens listed",                  test_report_ready_tokens_listed),
        ("DB1 — get_training_records real DB",                 test_get_training_records_real_db),
    ]

    passed = 0
    failed = 0
    errors = []

    print("=" * 62)
    print("  Phase 2 Step 1 Test Suite")
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
        import sys as _sys
        _sys.exit(1)
