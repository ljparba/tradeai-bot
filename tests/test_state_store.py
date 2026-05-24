"""Unit tests for state_store.py — Phase A-2 atomic process state."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from state_store import (  # noqa: E402
    PidFile,
    StateStore,
    _atomic_write_json,
    _pid_alive,
    _safe_read_json,
)


# ─────────────────────────────────────────────────────────
# StateStore
# ─────────────────────────────────────────────────────────
def test_load_returns_defaults_when_missing(tmp_path: Path) -> None:
    s = StateStore(path=tmp_path / "state.json")
    assert s.load(defaults={"cycle": 0, "errors": 0}) == {"cycle": 0, "errors": 0}


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    s = StateStore(path=tmp_path / "state.json")
    assert s.save({"cycle": 5, "errors": 2}) is True
    out = s.load(defaults={"cycle": 0, "errors": 0})
    assert out["cycle"] == 5
    assert out["errors"] == 2
    assert "_saved_at" in out  # save() stamps a timestamp


def test_save_is_atomic_no_tmp_leftover(tmp_path: Path) -> None:
    s = StateStore(path=tmp_path / "state.json")
    s.save({"a": 1})
    s.save({"a": 2})
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_drops_non_json_values(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    s = StateStore(path=tmp_path / "state.json")
    # `object()` is not JSON-serialisable; `set()` is not either
    s.save({"cycle": 7, "bad": object(), "alsobad": {1, 2}})
    loaded = s.load()
    assert loaded["cycle"] == 7
    assert "bad" not in loaded
    assert "alsobad" not in loaded


def test_load_recovers_from_corrupt_primary(tmp_path: Path) -> None:
    primary = tmp_path / "state.json"
    bak = tmp_path / "state.json.bak"
    bak.write_text(json.dumps({"cycle": 3, "errors": 0}), encoding="utf-8")
    primary.write_text("{this is not valid json", encoding="utf-8")
    s = StateStore(path=primary)
    out = s.load(defaults={"cycle": 0, "errors": 0})
    assert out["cycle"] == 3


def test_load_falls_back_to_defaults_if_both_corrupt(tmp_path: Path) -> None:
    primary = tmp_path / "state.json"
    bak = tmp_path / "state.json.bak"
    primary.write_text("garbage", encoding="utf-8")
    bak.write_text("also garbage", encoding="utf-8")
    s = StateStore(path=primary)
    out = s.load(defaults={"cycle": 0})
    assert out == {"cycle": 0}


def test_save_creates_backup_on_second_write(tmp_path: Path) -> None:
    s = StateStore(path=tmp_path / "state.json")
    s.save({"cycle": 1})
    s.save({"cycle": 2})
    bak = tmp_path / "state.json.bak"
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8"))["cycle"] == 1


def test_save_never_raises_on_disk_error(tmp_path: Path) -> None:
    s = StateStore(path=tmp_path / "state.json")
    with mock.patch("state_store._atomic_write_json", side_effect=OSError("no disk")):
        # Must not raise
        assert s.save({"cycle": 9}) is False


def test_transaction_saves_on_exit(tmp_path: Path) -> None:
    s = StateStore(path=tmp_path / "state.json")
    with s.transaction(defaults={"cycle": 0}) as state:
        state["cycle"] = 99
    out = s.load(defaults={"cycle": 0})
    assert out["cycle"] == 99


def test_transaction_saves_even_on_exception(tmp_path: Path) -> None:
    s = StateStore(path=tmp_path / "state.json")
    with pytest.raises(RuntimeError):
        with s.transaction(defaults={"cycle": 0}) as state:
            state["cycle"] = 77
            raise RuntimeError("boom")
    out = s.load(defaults={"cycle": 0})
    assert out["cycle"] == 77


def test_atomic_write_json_replaces_existing(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    _atomic_write_json(p, {"a": 1})
    _atomic_write_json(p, {"a": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 2}


def test_safe_read_json_returns_none_on_garbage(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text("not json", encoding="utf-8")
    assert _safe_read_json(p) is None


def test_safe_read_json_rejects_non_dict(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text("[1,2,3]", encoding="utf-8")
    assert _safe_read_json(p) is None


# ─────────────────────────────────────────────────────────
# PidFile
# ─────────────────────────────────────────────────────────
def test_pid_alive_self_is_alive() -> None:
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_bogus_is_dead() -> None:
    # PID 0 is sentinel; very high PIDs are unlikely to exist
    assert _pid_alive(0) is False
    assert _pid_alive(99999999) is False


def test_pidfile_writes_and_releases(tmp_path: Path) -> None:
    p = tmp_path / "tradeai.pid"
    with PidFile(path=p) as guard:
        assert p.exists()
        assert int(p.read_text(encoding="utf-8")) == os.getpid()
        assert guard._acquired is True
    assert not p.exists()


def test_pidfile_reclaims_stale(tmp_path: Path) -> None:
    p = tmp_path / "tradeai.pid"
    # A pid that doesn't exist
    p.write_text("99999999", encoding="utf-8")
    with PidFile(path=p):
        assert int(p.read_text(encoding="utf-8")) == os.getpid()


def test_pidfile_refuses_when_other_alive(tmp_path: Path) -> None:
    p = tmp_path / "tradeai.pid"
    # Pretend the current process is "the other" by writing our own PID,
    # then patch _pid_alive to claim *another* PID is alive.
    p.write_text("424242", encoding="utf-8")
    with mock.patch("state_store._pid_alive", return_value=True):
        guard = PidFile(path=p)
        with pytest.raises(RuntimeError, match="Another TradeAI"):
            guard.acquire()


def test_pidfile_release_only_deletes_own_pid(tmp_path: Path) -> None:
    """Race: another bot replaced our pid file. release() must not delete it."""
    p = tmp_path / "tradeai.pid"
    guard = PidFile(path=p)
    guard.acquire()
    assert p.exists()
    # Another process overwrites with a different PID
    p.write_text("424242", encoding="utf-8")
    guard.release()
    # The other PID's file is still there
    assert p.exists()
    assert p.read_text(encoding="utf-8").strip() == "424242"
