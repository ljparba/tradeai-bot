"""
TradeAI — Baseline DB Snapshot Discipline (FIX 3, 2026-05-23)
==============================================================

Creates an immutable snapshot of `data/signals.db` before any optimizer or
explorer cycle starts. The snapshot is named after the latest run_id so the
operator can always revert to a known-good state.

Usage:
    python scripts/snapshot_baseline.py                 # auto-name from MAX(run_id)
    python scripts/snapshot_baseline.py --tag mytest    # custom suffix
    python scripts/snapshot_baseline.py --list          # list existing snapshots
    python scripts/snapshot_baseline.py --restore <path> # restore from a snapshot

Why this exists:
    The backtest-optimizer cycle Z (2026-05-23) demonstrated that:
    1. An ill-advised Phase 0e instruction (BACKTEST_DAYS=730) collapsed metrics
    2. The OGD bootstrap pool changed, making Run-110 no longer byte-reproducible
    3. There was no clean way to revert because nothing snapshotted the DB state

    This script enforces the snapshot discipline: ALWAYS take a snapshot before
    a destructive cycle, and ALWAYS preserve the snapshot file as the rollback
    target.

The snapshots live in `data/snapshots/` and are named:
    signals_baseline_run{NNN}_{YYYYMMDD_HHMM}.db

They are read-only (chmod 444 on POSIX). On Windows, we set the attribute
where possible — but the discipline is on the operator: do not delete these
unless you're sure you no longer need that fallback.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import stat
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "data" / "signals.db"
_SNAPSHOT_DIR = _ROOT / "data" / "snapshots"


def _latest_run_id(db_path: Path) -> int:
    """Returns MAX(id) from backtest_runs, or 0 if table doesn't exist."""
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        row = conn.execute("SELECT MAX(id) FROM backtest_runs").fetchone()
        conn.close()
        return int(row[0]) if row and row[0] else 0
    except sqlite3.Error:
        return 0


def _list_snapshots() -> list[Path]:
    if not _SNAPSHOT_DIR.exists():
        return []
    return sorted(_SNAPSHOT_DIR.glob("signals_baseline_*.db"))


def cmd_snapshot(tag: str | None = None) -> Path:
    """Create a new snapshot. Returns the snapshot file path."""
    if not _DB_PATH.exists():
        print(f"[snapshot] no DB to snapshot at {_DB_PATH} — aborting")
        sys.exit(1)

    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = _latest_run_id(_DB_PATH)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    if tag:
        # sanitize tag — only alnum + underscore + hyphen
        safe = "".join(c for c in tag if c.isalnum() or c in "-_")[:32]
        name = f"signals_baseline_run{run_id}_{ts}_{safe}.db"
    else:
        name = f"signals_baseline_run{run_id}_{ts}.db"

    target = _SNAPSHOT_DIR / name
    if target.exists():
        print(f"[snapshot] target already exists, skipping: {target.name}")
        return target

    # Use sqlite3 backup API instead of shutil.copy so an in-progress write
    # by the bot doesn't corrupt the snapshot.
    src = sqlite3.connect(str(_DB_PATH))
    dst = sqlite3.connect(str(target))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()

    # Make read-only so an accidental write fails loudly rather than silently
    # corrupting the snapshot.
    try:
        target.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass  # best-effort on Windows

    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"[snapshot] saved {target.name} ({size_mb:.1f} MB, run_id={run_id})")
    return target


def cmd_list() -> None:
    snaps = _list_snapshots()
    if not snaps:
        print("[snapshot] no snapshots in data/snapshots/")
        return
    print(f"[snapshot] {len(snaps)} snapshots in {_SNAPSHOT_DIR}/:")
    for p in snaps:
        mb = p.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  {p.name}  ({mb:.1f} MB, {mtime})")


def cmd_restore(snapshot_path: str) -> None:
    src = Path(snapshot_path)
    if not src.is_absolute():
        # try relative to snapshot dir first, then repo root
        candidate1 = _SNAPSHOT_DIR / src.name
        candidate2 = _ROOT / src
        src = candidate1 if candidate1.exists() else candidate2
    if not src.exists():
        print(f"[snapshot] not found: {snapshot_path}")
        sys.exit(1)

    if _DB_PATH.exists():
        # Auto-snapshot current state before clobbering it
        print("[snapshot] backing up current DB before restore...")
        cmd_snapshot(tag="pre_restore")

    # Need to clear read-only attr on target if it inherited it
    if _DB_PATH.exists():
        try:
            _DB_PATH.chmod(stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass

    shutil.copy2(src, _DB_PATH)
    # restore writable on the working copy
    try:
        _DB_PATH.chmod(stat.S_IREAD | stat.S_IWRITE)
    except OSError:
        pass
    print(f"[snapshot] restored {_DB_PATH} from {src.name}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="TradeAI baseline DB snapshot tool",
        allow_abbrev=False,
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--tag", type=str, default=None,
                   help="Optional suffix for the snapshot filename")
    g.add_argument("--list", action="store_true",
                   help="List existing snapshots and exit")
    g.add_argument("--restore", type=str, default=None,
                   help="Restore signals.db from a snapshot (auto-backs up current DB first)")
    args = p.parse_args()

    if args.list:
        cmd_list()
        return 0
    if args.restore:
        cmd_restore(args.restore)
        return 0
    cmd_snapshot(tag=args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
