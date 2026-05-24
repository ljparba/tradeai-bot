"""
TuneBot Hardening Test Suite

Tests:
  Apply flow:
    A1  valid FVG_MIN_QUALITY change succeeds and modifies LIVE_CONFIG
    A2  valid MSS_MIN_QUALITY change succeeds and modifies LIVE_CONFIG
    A3  invalid param rejected — file unchanged, strategy_version unchanged
    A4  invalid value rejected — file unchanged, strategy_version unchanged
    A5  no-op (same value as current) rejected — file unchanged
    A6  empty adjustments list rejected — file unchanged
    A7  BACKTEST_CONFIG section unchanged after apply
    A8  StrategyConfig.__init__ defaults unchanged after apply
    A9  tune_history row created on successful apply
    A10 strategy_version increments after successful apply
    A11 strategy_version does NOT increment on failed apply
    A12 backup file created on successful apply
    A13 backup contains pre-change content
    A14 BACKTEST_CONFIG anchor missing -> rejected, file unchanged

  Rollback flow:
    R1  valid rollback succeeds, LIVE_CONFIG reverted
    R2  double rollback rejected
    R3  nonexistent tune_id rejected
    R4  tune_history row status updated to ROLLED_BACK
    R5  strategy_version increments after rollback
    R6  backup created before rollback write
    R7  BACKTEST_CONFIG unchanged during rollback

  Status command:
    S1  tune_status() returns all required top-level fields
    S2  tune_status() live_config reflects current LIVE_CONFIG values
    S3  tune_status() backtest_config reads BACKTEST_CONFIG values
    S4  tune_status() strategy_version is an integer
    S5  read_backtest_config_values() reads BACKTEST_CONFIG correctly

  Config isolation (paranoia checks):
    C1  LIVE_CONFIG change does not touch fvg_min_quality in BACKTEST_CONFIG
    C2  LIVE_CONFIG change does not touch mss_min_quality in BACKTEST_CONFIG
    C3  StrategyConfig.__init__ parameter defaults are never modified

  Windows / encoding safety:
    W1  apply and rollback produce no UnicodeEncodeError in print output
    W2  strategy_engine.py written with utf-8 encoding (no BOM introduced)
"""

import os
import sys
import re
import shutil
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tracker import (
    apply_tune_adjustments,
    rollback_tune_adjustment,
    tune_status,
    read_bot_values,
    read_backtest_config_values,
    _load_scalar,
)

_ROOT       = os.path.join(os.path.dirname(__file__), "..")
SE_PATH     = os.path.join(_ROOT, "strategy_engine.py")
CONFIG_PATH = os.path.join(_ROOT, "config.py")

# Phase A item #4 — Tune Bot now edits config.py (the centralized source of
# truth), not strategy_engine.py. _save_se/_restore_se still cover both files
# so the suite catches accidental drift in either.

# ── Test fixture helpers ──────────────────────────────────────────────────────

def _save_se():
    """Snapshot the Tune Bot target file (config.py)."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _restore_se(content):
    """Restore the Tune Bot target file (config.py)."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def _save_strategy_engine():
    """Snapshot strategy_engine.py (must remain unmodified by Tune Bot)."""
    with open(SE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _cur_fvg():
    r = read_bot_values()
    return r.get("fvg_min_quality") if r.get("ok") else None


def _cur_mss():
    r = read_bot_values()
    return r.get("mss_min_quality") if r.get("ok") else None


def _cur_ver():
    try:
        return int(_load_scalar("strategy_version", 1))
    except Exception:
        return None


def _cleanup_tune_ids(ids):
    """Delete test tune_history rows by ID."""
    if not ids:
        return
    try:
        from tracker import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        for tid in ids:
            conn.execute("DELETE FROM tune_history WHERE id=?", (tid,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _opposite_quality(val):
    """Return a valid quality that is different from val."""
    return "HIGH" if val != "HIGH" else "MEDIUM"


def _get_init_defaults(_unused=None):
    """Extract fvg_min_quality + mss_min_quality from StrategyConfig.__init__.

    The Tune Bot edits config.py, but the __init__ signature defaults live in
    strategy_engine.py. C3/A8 assert those never change — so we always read
    them from strategy_engine.py regardless of the _unused arg (kept for the
    existing call sites that pass a content snapshot)."""
    with open(SE_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    init_m = re.search(
        r'def __init__\s*\(.*?(?=class\s|\Z)', content, re.DOTALL
    )
    block = init_m.group(0) if init_m else content
    fvg_m = re.search(r'fvg_min_quality\s*=\s*"(\w+)"', block)
    mss_m = re.search(r'mss_min_quality\s*=\s*"(\w+)"', block)
    return (fvg_m.group(1) if fvg_m else None,
            mss_m.group(1) if mss_m else None)


# ═══════════════════════════════════════════════════════════
# A1–A14: Apply flow
# ═══════════════════════════════════════════════════════════

def test_apply_valid_fvg():
    """A1: valid FVG_MIN_QUALITY change modifies LIVE_CONFIG."""
    orig = _save_se()
    before_fvg = _cur_fvg()
    before_ver = _cur_ver()
    target_val = _opposite_quality(before_fvg)
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"A1 FAIL: apply returned ok=False: {r.get('error')}"
        assert r.get("applied_count") == 1, f"A1 FAIL: applied_count={r.get('applied_count')}"
        after_fvg = _cur_fvg()
        assert after_fvg == target_val, f"A1 FAIL: fvg_min_quality={after_fvg}, expected {target_val}"
        after_ver = _cur_ver()
        assert after_ver == before_ver + 1, f"A1 FAIL: version {before_ver} -> {after_ver}"
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS A1: FVG_MIN_QUALITY {before_fvg} -> {target_val}, version {before_ver} -> {after_ver}")
    finally:
        _restore_se(orig)


def test_apply_valid_mss():
    """A2: valid MSS_MIN_QUALITY change modifies LIVE_CONFIG."""
    orig = _save_se()
    before_mss = _cur_mss()
    before_ver = _cur_ver()
    target_val = _opposite_quality(before_mss)
    try:
        r = apply_tune_adjustments([{"param": "MSS_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"A2 FAIL: {r.get('error')}"
        after_mss = _cur_mss()
        assert after_mss == target_val, f"A2 FAIL: mss={after_mss}, expected {target_val}"
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS A2: MSS_MIN_QUALITY {before_mss} -> {target_val}")
    finally:
        _restore_se(orig)


def test_apply_invalid_param():
    """A3: invalid param rejected, file unchanged, strategy_version unchanged."""
    orig = _save_se()
    before_ver = _cur_ver()
    r = apply_tune_adjustments([{"param": "UNKNOWN_PARAM", "new_val": "HIGH"}])
    assert not r.get("ok"), "A3 FAIL: invalid param was accepted"
    assert "Unknown param" in r.get("error", "") or "Validation failed" in r.get("error", ""), \
        f"A3 FAIL: unexpected error: {r.get('error')}"
    assert _save_se() == orig, "A3 FAIL: file was modified"
    assert _cur_ver() == before_ver, f"A3 FAIL: strategy_version changed"
    print(f"PASS A3: invalid param rejected ({r['error'][:60]})")


def test_apply_invalid_value():
    """A4: invalid value rejected, file unchanged, strategy_version unchanged."""
    orig = _save_se()
    before_ver = _cur_ver()
    r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": "EXTREME"}])
    assert not r.get("ok"), "A4 FAIL: invalid value was accepted"
    assert _save_se() == orig, "A4 FAIL: file was modified"
    assert _cur_ver() == before_ver, "A4 FAIL: strategy_version changed"
    print(f"PASS A4: invalid value rejected ({r['error'][:60]})")


def test_apply_noop_rejected():
    """A5: no-op change (same value as current) rejected, file unchanged."""
    orig = _save_se()
    before_ver = _cur_ver()
    current_fvg = _cur_fvg()
    r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": current_fvg}])
    assert not r.get("ok"), f"A5 FAIL: no-op was accepted (fvg={current_fvg})"
    assert "No-op" in r.get("error", "") or "already" in r.get("error", "").lower(), \
        f"A5 FAIL: unexpected error: {r.get('error')}"
    assert _save_se() == orig, "A5 FAIL: file was modified"
    assert _cur_ver() == before_ver, "A5 FAIL: strategy_version changed"
    print(f"PASS A5: no-op {current_fvg} correctly rejected")


def test_apply_empty_list():
    """A6: empty adjustments list rejected."""
    r = apply_tune_adjustments([])
    assert not r.get("ok"), "A6 FAIL: empty list was accepted"
    print(f"PASS A6: empty adjustments rejected ({r['error'][:60]})")


def test_apply_backtest_config_unchanged():
    """A7: BACKTEST_CONFIG section is identical before and after apply."""
    orig = _save_se()
    before_bt = read_backtest_config_values()
    target_val = _opposite_quality(_cur_fvg())
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"A7 FAIL: apply failed: {r.get('error')}"
        after_bt = read_backtest_config_values()
        assert before_bt.get("fvg_min_quality") == after_bt.get("fvg_min_quality"), \
            f"A7 FAIL: BACKTEST_CONFIG fvg_min_quality changed: {before_bt} -> {after_bt}"
        assert before_bt.get("mss_min_quality") == after_bt.get("mss_min_quality"), \
            f"A7 FAIL: BACKTEST_CONFIG mss_min_quality changed"
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS A7: BACKTEST_CONFIG unchanged during apply")
    finally:
        _restore_se(orig)


def test_apply_init_defaults_unchanged():
    """A8: StrategyConfig.__init__ default values never modified."""
    orig = _save_se()
    fvg_init_before, mss_init_before = _get_init_defaults(orig)
    target_val = _opposite_quality(_cur_fvg())
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"A8 FAIL: apply failed"
        new_content = _save_se()
        fvg_init_after, mss_init_after = _get_init_defaults(new_content)
        assert fvg_init_before == fvg_init_after, \
            f"A8 FAIL: __init__ fvg_min_quality changed: {fvg_init_before} -> {fvg_init_after}"
        assert mss_init_before == mss_init_after, \
            f"A8 FAIL: __init__ mss_min_quality changed"
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS A8: StrategyConfig.__init__ defaults unchanged (fvg={fvg_init_before})")
    finally:
        _restore_se(orig)


def test_apply_tune_history_row():
    """A9: tune_history row is created on successful apply."""
    orig = _save_se()
    target_val = _opposite_quality(_cur_fvg())
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"A9 FAIL: {r.get('error')}"
        ids = r.get("tune_ids", [])
        assert len(ids) == 1, f"A9 FAIL: expected 1 tune_id, got {ids}"
        from tracker import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT param, new_val, status FROM tune_history WHERE id=?", (ids[0],)
        ).fetchone()
        conn.close()
        assert row is not None, f"A9 FAIL: tune_history row id={ids[0]} not found"
        assert row[0] == "FVG_MIN_QUALITY", f"A9 FAIL: param={row[0]}"
        assert row[1] == target_val, f"A9 FAIL: new_val={row[1]}"
        assert row[2] == "APPLIED", f"A9 FAIL: status={row[2]}"
        _cleanup_tune_ids(ids)
        print(f"PASS A9: tune_history row created (id={ids[0]}, status=APPLIED)")
    finally:
        _restore_se(orig)


def test_apply_version_increments():
    """A10: strategy_version increments after successful apply."""
    orig = _save_se()
    before_ver = _cur_ver()
    target_val = _opposite_quality(_cur_fvg())
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"A10 FAIL: {r.get('error')}"
        after_ver = _cur_ver()
        assert after_ver == before_ver + 1, \
            f"A10 FAIL: version {before_ver} -> {after_ver} (expected +1)"
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS A10: strategy_version incremented {before_ver} -> {after_ver}")
    finally:
        _restore_se(orig)


def test_failed_apply_no_version_increment():
    """A11: failed apply does NOT increment strategy_version."""
    before_ver = _cur_ver()
    # Invalid param — must fail before any file changes
    apply_tune_adjustments([{"param": "BAD_PARAM", "new_val": "HIGH"}])
    assert _cur_ver() == before_ver, \
        f"A11 FAIL: version changed on failed apply ({before_ver} -> {_cur_ver()})"
    print(f"PASS A11: strategy_version unchanged after failed apply (ver={before_ver})")


def test_apply_backup_created():
    """A12: backup file is created in backups/ on successful apply."""
    orig = _save_se()
    target_val = _opposite_quality(_cur_fvg())
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"A12 FAIL: {r.get('error')}"
        backup_rel = r.get("backup")
        assert backup_rel, "A12 FAIL: no backup path in response"
        backup_abs = os.path.join(_ROOT, backup_rel)
        assert os.path.exists(backup_abs), f"A12 FAIL: backup file not found at {backup_abs}"
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS A12: backup created at {backup_rel}")
    finally:
        _restore_se(orig)


def test_apply_backup_contains_original():
    """A13: backup file contains pre-change config.py content."""
    orig = _save_se()
    before_fvg = _cur_fvg()
    target_val = _opposite_quality(before_fvg)
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"A13 FAIL: {r.get('error')}"
        backup_abs = os.path.join(_ROOT, r["backup"])
        with open(backup_abs, "r", encoding="utf-8") as f:
            bak_content = f.read()
        # Backup is a snapshot of config.py BEFORE the edit; production has new value.
        bak_pattern = re.compile(
            rf'LIVE_FVG_MIN_QUALITY\s*:\s*str\s*=\s*_env_choice\("LIVE_FVG_MIN_QUALITY",\s*"{before_fvg}"'
        )
        assert bak_pattern.search(bak_content), \
            f"A13 FAIL: backup does not contain original LIVE_FVG_MIN_QUALITY={before_fvg}"
        after_content = _save_se()
        prod_pattern = re.compile(
            rf'LIVE_FVG_MIN_QUALITY\s*:\s*str\s*=\s*_env_choice\("LIVE_FVG_MIN_QUALITY",\s*"{target_val}"'
        )
        assert prod_pattern.search(after_content), \
            f"A13 FAIL: production config.py does not contain new value {target_val}"
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS A13: backup has {before_fvg}, production has {target_val}")
    finally:
        _restore_se(orig)


def test_apply_missing_backtest_anchor():
    """A14: BACKTEST_CONFIG anchor missing in config.py -> rejected, file unchanged."""
    orig = _save_se()
    # Mangle the BACKTEST anchor header so Tune Bot's anchor detector fails.
    mangled = orig.replace(
        "# ── BACKTEST_CONFIG — per-field constants",
        "# ── REMOVED — per-field constants",
    )
    before_ver = _cur_ver()
    try:
        _restore_se(mangled)
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": "HIGH"}])
        assert not r.get("ok"), "A14 FAIL: should have rejected missing BACKTEST_CONFIG anchor"
        assert "BACKTEST_CONFIG" in r.get("error", ""), \
            f"A14 FAIL: unexpected error: {r.get('error')}"
        assert _cur_ver() == before_ver, "A14 FAIL: version changed"
        print(f"PASS A14: missing BACKTEST_CONFIG anchor correctly rejected")
    finally:
        _restore_se(orig)


# ═══════════════════════════════════════════════════════════
# R1–R7: Rollback flow
# ═══════════════════════════════════════════════════════════

def test_rollback_valid():
    """R1: valid rollback restores LIVE_CONFIG to original value."""
    orig = _save_se()
    before_fvg = _cur_fvg()
    target_val = _opposite_quality(before_fvg)
    try:
        apply_r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert apply_r.get("ok"), f"R1 setup FAIL: apply failed: {apply_r.get('error')}"
        tune_id = apply_r["tune_ids"][0]
        assert _cur_fvg() == target_val, "R1 setup FAIL: fvg not changed"

        roll_r = rollback_tune_adjustment(tune_id)
        assert roll_r.get("ok"), f"R1 FAIL: rollback failed: {roll_r.get('error')}"
        assert _cur_fvg() == before_fvg, \
            f"R1 FAIL: after rollback fvg={_cur_fvg()}, expected {before_fvg}"
        _cleanup_tune_ids([tune_id])
        print(f"PASS R1: rollback restored FVG {target_val} -> {before_fvg}")
    finally:
        _restore_se(orig)


def test_rollback_double_rejected():
    """R2: rolling back an already-rolled-back record is rejected."""
    orig = _save_se()
    target_val = _opposite_quality(_cur_fvg())
    try:
        apply_r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert apply_r.get("ok"), f"R2 setup FAIL"
        tune_id = apply_r["tune_ids"][0]

        r1 = rollback_tune_adjustment(tune_id)
        assert r1.get("ok"), f"R2 FAIL: first rollback failed: {r1.get('error')}"

        r2 = rollback_tune_adjustment(tune_id)
        assert not r2.get("ok"), "R2 FAIL: double rollback was accepted"
        assert "already rolled back" in r2.get("error", "").lower(), \
            f"R2 FAIL: unexpected error: {r2.get('error')}"
        _cleanup_tune_ids([tune_id])
        print(f"PASS R2: double rollback correctly rejected")
    finally:
        _restore_se(orig)


def test_rollback_nonexistent_id():
    """R3: rollback for nonexistent tune_id returns ok=False."""
    r = rollback_tune_adjustment(9999999)
    assert not r.get("ok"), "R3 FAIL: nonexistent id was accepted"
    assert "not found" in r.get("error", "").lower(), \
        f"R3 FAIL: unexpected error: {r.get('error')}"
    print(f"PASS R3: nonexistent tune_id rejected")


def test_rollback_tune_history_status():
    """R4: tune_history row status updated to ROLLED_BACK."""
    orig = _save_se()
    target_val = _opposite_quality(_cur_fvg())
    try:
        apply_r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert apply_r.get("ok"), "R4 setup FAIL"
        tune_id = apply_r["tune_ids"][0]

        rollback_tune_adjustment(tune_id)

        from tracker import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT status FROM tune_history WHERE id=?", (tune_id,)
        ).fetchone()
        conn.close()
        assert row and row[0] == "ROLLED_BACK", \
            f"R4 FAIL: status={row[0] if row else 'NOT FOUND'}"
        _cleanup_tune_ids([tune_id])
        print(f"PASS R4: tune_history#{tune_id} status=ROLLED_BACK")
    finally:
        _restore_se(orig)


def test_rollback_version_increments():
    """R5: strategy_version increments after rollback."""
    orig = _save_se()
    target_val = _opposite_quality(_cur_fvg())
    try:
        apply_r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert apply_r.get("ok"), "R5 setup FAIL"
        tune_id = apply_r["tune_ids"][0]
        ver_after_apply = _cur_ver()

        rollback_tune_adjustment(tune_id)
        ver_after_rollback = _cur_ver()
        assert ver_after_rollback == ver_after_apply + 1, \
            f"R5 FAIL: version {ver_after_apply} -> {ver_after_rollback} (expected +1)"
        _cleanup_tune_ids([tune_id])
        print(f"PASS R5: strategy_version incremented by rollback "
              f"({ver_after_apply} -> {ver_after_rollback})")
    finally:
        _restore_se(orig)


def test_rollback_backup_created():
    """R6: backup file created before rollback write."""
    orig = _save_se()
    target_val = _opposite_quality(_cur_fvg())
    try:
        apply_r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert apply_r.get("ok"), "R6 setup FAIL"
        tune_id = apply_r["tune_ids"][0]

        roll_r = rollback_tune_adjustment(tune_id)
        assert roll_r.get("ok"), f"R6 FAIL: rollback failed: {roll_r.get('error')}"
        backup_abs = os.path.join(_ROOT, roll_r["backup"])
        assert os.path.exists(backup_abs), f"R6 FAIL: rollback backup not found at {backup_abs}"
        _cleanup_tune_ids([tune_id])
        print(f"PASS R6: rollback backup created at {roll_r['backup']}")
    finally:
        _restore_se(orig)


def test_rollback_backtest_unchanged():
    """R7: BACKTEST_CONFIG unchanged during rollback."""
    orig = _save_se()
    before_bt = read_backtest_config_values()
    target_val = _opposite_quality(_cur_fvg())
    try:
        apply_r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert apply_r.get("ok"), "R7 setup FAIL"
        tune_id = apply_r["tune_ids"][0]

        rollback_tune_adjustment(tune_id)

        after_bt = read_backtest_config_values()
        assert before_bt.get("fvg_min_quality") == after_bt.get("fvg_min_quality"), \
            f"R7 FAIL: BACKTEST_CONFIG fvg changed during rollback"
        assert before_bt.get("mss_min_quality") == after_bt.get("mss_min_quality"), \
            f"R7 FAIL: BACKTEST_CONFIG mss changed during rollback"
        _cleanup_tune_ids([tune_id])
        print(f"PASS R7: BACKTEST_CONFIG unchanged during rollback")
    finally:
        _restore_se(orig)


# ═══════════════════════════════════════════════════════════
# S1–S5: Status command
# ═══════════════════════════════════════════════════════════

def test_status_required_fields():
    """S1: tune_status() returns all required top-level fields."""
    s = tune_status()
    required = {
        "ok", "live_config", "backtest_config", "strategy_version",
        "last_apply", "last_rollback", "frequency_gate",
        "can_apply", "cannot_apply_reason",
    }
    missing = required - set(s.keys())
    assert not missing, f"S1 FAIL: missing fields: {missing}"
    assert s["ok"] is True, f"S1 FAIL: ok={s['ok']}"
    print(f"PASS S1: tune_status() has all {len(required)} required fields")


def test_status_live_config():
    """S2: tune_status() live_config matches read_bot_values()."""
    s  = tune_status()
    rv = read_bot_values()
    assert rv.get("ok"), f"S2 FAIL: read_bot_values() failed"
    assert s["live_config"].get("fvg_min_quality") == rv.get("fvg_min_quality"), \
        f"S2 FAIL: live_config fvg mismatch"
    assert s["live_config"].get("mss_min_quality") == rv.get("mss_min_quality"), \
        f"S2 FAIL: live_config mss mismatch"
    print(f"PASS S2: tune_status() live_config correct "
          f"(fvg={rv['fvg_min_quality']}, mss={rv['mss_min_quality']})")


def test_status_backtest_config():
    """S3: tune_status() backtest_config reads BACKTEST_CONFIG values."""
    s  = tune_status()
    bc = read_backtest_config_values()
    assert bc.get("ok"), f"S3 FAIL: read_backtest_config_values() failed"
    assert s["backtest_config"].get("fvg_min_quality") == bc.get("fvg_min_quality"), \
        f"S3 FAIL: backtest fvg mismatch"
    print(f"PASS S3: tune_status() backtest_config correct "
          f"(fvg={bc['fvg_min_quality']})")


def test_status_strategy_version():
    """S4: tune_status() strategy_version is a non-negative integer."""
    s = tune_status()
    ver = s.get("strategy_version")
    assert isinstance(ver, int), f"S4 FAIL: strategy_version type={type(ver)}"
    assert ver >= 0, f"S4 FAIL: strategy_version={ver}"
    print(f"PASS S4: strategy_version={ver}")


def test_read_backtest_config():
    """S5: read_backtest_config_values() returns known BACKTEST_CONFIG values."""
    bc = read_backtest_config_values()
    assert bc.get("ok"), f"S5 FAIL: {bc.get('error')}"
    assert bc["fvg_min_quality"] in {"LOW", "MEDIUM", "HIGH"}, \
        f"S5 FAIL: invalid fvg_min_quality={bc['fvg_min_quality']!r}"
    assert bc["mss_min_quality"] in {"LOW", "MEDIUM", "HIGH"}, \
        f"S5 FAIL: invalid mss_min_quality={bc['mss_min_quality']!r}"
    print(f"PASS S5: BACKTEST_CONFIG fvg={bc['fvg_min_quality']} mss={bc['mss_min_quality']}")


# ═══════════════════════════════════════════════════════════
# C1–C3: Config isolation (paranoia)
# ═══════════════════════════════════════════════════════════

def test_isolation_backtest_fvg():
    """C1: LIVE_FVG_MIN_QUALITY change must not touch BACKTEST_FVG_MIN_QUALITY."""
    orig = _save_se()
    bt_before = read_backtest_config_values()
    target_val = _opposite_quality(_cur_fvg())
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"C1 setup FAIL: {r.get('error')}"
        bt_after = read_backtest_config_values()
        assert bt_before["fvg_min_quality"] == bt_after["fvg_min_quality"], (
            f"C1 FAIL: BACKTEST_FVG_MIN_QUALITY changed "
            f"{bt_before['fvg_min_quality']} -> {bt_after['fvg_min_quality']}"
        )
        # Also verify at raw text level — BACKTEST_FVG_MIN_QUALITY literal in config.py.
        new_content = _save_se()
        bt_idx = new_content.find("# ── BACKTEST_CONFIG — per-field constants")
        bt_section = new_content[bt_idx:]
        bt_fvg_match = re.search(
            r'BACKTEST_FVG_MIN_QUALITY\s*:\s*str\s*=\s*_env_choice\("BACKTEST_FVG_MIN_QUALITY",\s*"(\w+)"',
            bt_section,
        )
        assert bt_fvg_match and bt_fvg_match.group(1) == bt_before["fvg_min_quality"], (
            f"C1 FAIL: raw BACKTEST_FVG_MIN_QUALITY changed to "
            f"{bt_fvg_match.group(1) if bt_fvg_match else 'NOT FOUND'}"
        )
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS C1: BACKTEST_FVG_MIN_QUALITY={bt_after['fvg_min_quality']} (unchanged)")
    finally:
        _restore_se(orig)


def test_isolation_backtest_mss():
    """C2: LIVE_CONFIG MSS change does not touch BACKTEST_CONFIG mss_min_quality."""
    orig = _save_se()
    bt_before = read_backtest_config_values()
    target_val = _opposite_quality(_cur_mss())
    try:
        r = apply_tune_adjustments([{"param": "MSS_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"C2 setup FAIL: {r.get('error')}"
        bt_after = read_backtest_config_values()
        assert bt_before["mss_min_quality"] == bt_after["mss_min_quality"], (
            f"C2 FAIL: BACKTEST_CONFIG mss changed"
        )
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS C2: BACKTEST_CONFIG mss={bt_after['mss_min_quality']} (unchanged)")
    finally:
        _restore_se(orig)


def test_isolation_init_defaults():
    """C3: StrategyConfig.__init__ default values never modified by any apply."""
    orig = _save_se()
    fvg_init_before, mss_init_before = _get_init_defaults(orig)
    assert fvg_init_before is not None, "C3 FAIL: could not read __init__ defaults"

    # Apply a change to FVG
    target_val = _opposite_quality(_cur_fvg())
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"C3 FAIL: apply failed"
        new_content = _save_se()
        fvg_init_after, mss_init_after = _get_init_defaults(new_content)
        assert fvg_init_before == fvg_init_after, (
            f"C3 FAIL: __init__ fvg_min_quality changed "
            f"{fvg_init_before!r} -> {fvg_init_after!r}"
        )
        assert mss_init_before == mss_init_after, (
            f"C3 FAIL: __init__ mss_min_quality changed"
        )
        _cleanup_tune_ids(r.get("tune_ids", []))
        print(f"PASS C3: __init__ defaults unchanged (fvg={fvg_init_before!r})")
    finally:
        _restore_se(orig)


# ═══════════════════════════════════════════════════════════
# W1–W2: Windows / encoding safety
# ═══════════════════════════════════════════════════════════

def test_no_unicode_error(capsys=None):
    """W1: apply and rollback print statements produce no UnicodeEncodeError."""
    orig = _save_se()
    target_val = _opposite_quality(_cur_fvg())

    import io, contextlib
    buf = io.StringIO()
    try:
        # Redirect stdout to StringIO (always accepts any unicode)
        with contextlib.redirect_stdout(buf):
            r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"W1 FAIL: apply failed: {r.get('error')}"
        tune_id = r["tune_ids"][0]

        with contextlib.redirect_stdout(buf):
            rb = rollback_tune_adjustment(tune_id)
        assert rb.get("ok"), f"W1 FAIL: rollback failed"

        # Now check that all printed content is ASCII-safe (no arrows etc.)
        output = buf.getvalue()
        try:
            output.encode("cp1252")
        except UnicodeEncodeError as e:
            assert False, f"W1 FAIL: output contains cp1252-incompatible char: {e}"
        _cleanup_tune_ids([tune_id])
        print("PASS W1: no UnicodeEncodeError in print output (cp1252-safe)")
    finally:
        _restore_se(orig)


def test_utf8_no_bom():
    """W2: config.py written with utf-8 (no BOM introduced) — Tune Bot target."""
    orig = _save_se()
    target_val = _opposite_quality(_cur_fvg())
    try:
        r = apply_tune_adjustments([{"param": "FVG_MIN_QUALITY", "new_val": target_val}])
        assert r.get("ok"), f"W2 FAIL: apply failed"
        with open(CONFIG_PATH, "rb") as f:
            header = f.read(3)
        assert header != b"\xef\xbb\xbf", \
            "W2 FAIL: apply introduced UTF-8 BOM into config.py"
        _cleanup_tune_ids(r.get("tune_ids", []))
        print("PASS W2: config.py written without BOM")
    finally:
        _restore_se(orig)


# ── runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("A1  apply: valid FVG change",                  test_apply_valid_fvg),
        ("A2  apply: valid MSS change",                  test_apply_valid_mss),
        ("A3  apply: invalid param rejected",            test_apply_invalid_param),
        ("A4  apply: invalid value rejected",            test_apply_invalid_value),
        ("A5  apply: no-op rejected",                    test_apply_noop_rejected),
        ("A6  apply: empty list rejected",               test_apply_empty_list),
        ("A7  apply: BACKTEST_CONFIG unchanged",         test_apply_backtest_config_unchanged),
        ("A8  apply: __init__ defaults unchanged",       test_apply_init_defaults_unchanged),
        ("A9  apply: tune_history row created",          test_apply_tune_history_row),
        ("A10 apply: version increments",                test_apply_version_increments),
        ("A11 apply: failed -> no version change",       test_failed_apply_no_version_increment),
        ("A12 apply: backup created",                    test_apply_backup_created),
        ("A13 apply: backup has original content",       test_apply_backup_contains_original),
        ("A14 apply: missing BACKTEST anchor rejected",  test_apply_missing_backtest_anchor),
        ("R1  rollback: valid rollback",                 test_rollback_valid),
        ("R2  rollback: double rollback rejected",       test_rollback_double_rejected),
        ("R3  rollback: nonexistent id rejected",        test_rollback_nonexistent_id),
        ("R4  rollback: tune_history status updated",    test_rollback_tune_history_status),
        ("R5  rollback: version increments",             test_rollback_version_increments),
        ("R6  rollback: backup created",                 test_rollback_backup_created),
        ("R7  rollback: BACKTEST_CONFIG unchanged",      test_rollback_backtest_unchanged),
        ("S1  status: required fields present",          test_status_required_fields),
        ("S2  status: live_config correct",              test_status_live_config),
        ("S3  status: backtest_config correct",          test_status_backtest_config),
        ("S4  status: strategy_version is int",          test_status_strategy_version),
        ("S5  read_backtest_config_values()",            test_read_backtest_config),
        ("C1  isolation: BACKTEST fvg unchanged",        test_isolation_backtest_fvg),
        ("C2  isolation: BACKTEST mss unchanged",        test_isolation_backtest_mss),
        ("C3  isolation: __init__ defaults unchanged",   test_isolation_init_defaults),
        ("W1  Windows: no UnicodeEncodeError",           test_no_unicode_error),
        ("W2  Windows: no BOM on write",                 test_utf8_no_bom),
    ]

    passed = 0
    failed = 0

    print("=" * 62)
    print("  TuneBot Hardening Test Suite")
    print("=" * 62)

    for name, fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {name}")
            print(f"      {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {name}")
            print(f"      {type(e).__name__}: {e}")
            failed += 1

    print("=" * 62)
    print(f"  {passed} passed  |  {failed} failed")
    print("=" * 62)

    if failed:
        sys.exit(1)
