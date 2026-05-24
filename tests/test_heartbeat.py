"""Unit tests for heartbeat.py — Phase A-1 dead-man's switch."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from heartbeat import (  # noqa: E402
    Heartbeat,
    MultiChannelAlerter,
    SmtpAlerter,
    _atomic_write_json,
    is_stale,
    read_heartbeat,
)


def _tmp_hb_path(tmp_path: Path) -> Path:
    return tmp_path / "heartbeat.json"


def test_atomic_write_replaces_existing(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    _atomic_write_json(p, {"a": 1})
    _atomic_write_json(p, {"a": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 2}
    # No stray tmp files left behind
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_no_partial_on_crash(tmp_path: Path) -> None:
    p = tmp_path / "y.json"
    _atomic_write_json(p, {"ok": True})
    # Simulate a failed write by patching os.replace to raise
    with mock.patch("heartbeat.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            _atomic_write_json(p, {"ok": False})
    # Original file is untouched
    assert json.loads(p.read_text(encoding="utf-8")) == {"ok": True}


def test_read_heartbeat_missing_returns_none(tmp_path: Path) -> None:
    assert read_heartbeat(tmp_path / "nope.json") is None


def test_is_stale_missing_file(tmp_path: Path) -> None:
    stale, age, payload = is_stale(tmp_path / "nope.json", staleness_sec=10)
    assert stale is True
    assert age == float("inf")
    assert payload is None


def test_is_stale_fresh_file(tmp_path: Path) -> None:
    p = _tmp_hb_path(tmp_path)
    _atomic_write_json(p, {"ts_unix": time.time()})
    stale, age, payload = is_stale(p, staleness_sec=60)
    assert stale is False
    assert age < 5
    assert payload is not None


def test_is_stale_old_file(tmp_path: Path) -> None:
    p = _tmp_hb_path(tmp_path)
    _atomic_write_json(p, {"ts_unix": time.time() - 999})
    stale, age, payload = is_stale(p, staleness_sec=60)
    assert stale is True
    assert age > 60


def test_smtp_alerter_unconfigured_returns_false() -> None:
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_TO"):
            os.environ.pop(k, None)
        a = SmtpAlerter()
        assert a.configured is False
        assert a.send("subj", "body") is False


def test_smtp_alerter_configured_calls_smtp() -> None:
    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "u@example.com",
        "SMTP_PASS": "pw",
        "SMTP_TO": "ops@example.com",
    }
    with mock.patch.dict(os.environ, env):
        a = SmtpAlerter()
        assert a.configured is True
        with mock.patch("heartbeat.smtplib.SMTP") as smtp_cls:
            ctx = mock.MagicMock()
            smtp_cls.return_value.__enter__.return_value = ctx
            assert a.send("subj", "body") is True
            ctx.starttls.assert_called_once()
            ctx.login.assert_called_once_with("u@example.com", "pw")
            ctx.send_message.assert_called_once()


def test_smtp_alerter_465_uses_ssl() -> None:
    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "465",
        "SMTP_USER": "u@example.com",
        "SMTP_PASS": "pw",
        "SMTP_TO": "ops@example.com",
    }
    with mock.patch.dict(os.environ, env):
        a = SmtpAlerter()
        with mock.patch("heartbeat.smtplib.SMTP_SSL") as ssl_cls:
            ctx = mock.MagicMock()
            ssl_cls.return_value.__enter__.return_value = ctx
            assert a.send("subj", "body") is True
            ctx.login.assert_called_once()
            ctx.send_message.assert_called_once()


def test_multichannel_primary_success_skips_secondary() -> None:
    primary = mock.MagicMock(return_value=True)
    secondary = mock.MagicMock(spec=SmtpAlerter)
    secondary.configured = True
    secondary.send = mock.MagicMock(return_value=True)
    alerter = MultiChannelAlerter(primary_send=primary, secondary=secondary)
    result = alerter.send("s", "b")
    assert result == {"primary_ok": True, "secondary_ok": False}
    secondary.send.assert_not_called()


def test_multichannel_primary_failure_falls_back() -> None:
    primary = mock.MagicMock(return_value=False)
    secondary = mock.MagicMock(spec=SmtpAlerter)
    secondary.configured = True
    secondary.send = mock.MagicMock(return_value=True)
    alerter = MultiChannelAlerter(primary_send=primary, secondary=secondary)
    result = alerter.send("s", "b")
    assert result["primary_ok"] is False
    assert result["secondary_ok"] is True
    secondary.send.assert_called_once()


def test_multichannel_primary_exception_treated_as_failure() -> None:
    primary = mock.MagicMock(side_effect=RuntimeError("boom"))
    secondary = mock.MagicMock(spec=SmtpAlerter)
    secondary.configured = True
    secondary.send = mock.MagicMock(return_value=True)
    alerter = MultiChannelAlerter(primary_send=primary, secondary=secondary)
    result = alerter.send("s", "b")
    assert result["primary_ok"] is False
    assert result["secondary_ok"] is True


def test_multichannel_force_secondary_sends_both() -> None:
    primary = mock.MagicMock(return_value=True)
    secondary = mock.MagicMock(spec=SmtpAlerter)
    secondary.configured = True
    secondary.send = mock.MagicMock(return_value=True)
    alerter = MultiChannelAlerter(primary_send=primary, secondary=secondary)
    result = alerter.send("s", "b", force_secondary=True)
    assert result == {"primary_ok": True, "secondary_ok": True}
    primary.assert_called_once()
    secondary.send.assert_called_once()


def test_heartbeat_beat_writes_atomically(tmp_path: Path) -> None:
    p = _tmp_hb_path(tmp_path)
    alerter = mock.MagicMock(spec=MultiChannelAlerter)
    alerter.secondary_configured = False
    hb = Heartbeat(alerter=alerter, heartbeat_path=p)
    hb.beat(cycle=42, open_signals=2)
    payload = read_heartbeat(p)
    assert payload is not None
    assert payload["cycle"] == 42
    assert payload["open_signals"] == 2
    assert payload["pid"] == os.getpid()
    assert "ts_unix" in payload and "ts_utc" in payload


def test_heartbeat_persists_counter(tmp_path: Path) -> None:
    p = _tmp_hb_path(tmp_path)
    saved = {"v": 0}

    def loader() -> int:
        return saved["v"]

    def saver(v: int) -> None:
        saved["v"] = v

    alerter = mock.MagicMock(spec=MultiChannelAlerter)
    alerter.send = mock.MagicMock(return_value={"primary_ok": True, "secondary_ok": True})
    hb = Heartbeat(alerter=alerter, heartbeat_path=p,
                   load_counter=loader, save_counter=saver, selftest_every=100)
    for _ in range(7):
        hb.beat()
    assert saved["v"] == 7
    # New instance resumes from saved counter
    hb2 = Heartbeat(alerter=alerter, heartbeat_path=p,
                    load_counter=loader, save_counter=saver, selftest_every=100)
    hb2.beat()
    assert saved["v"] == 8


def test_heartbeat_selftest_fires_on_cadence(tmp_path: Path) -> None:
    p = _tmp_hb_path(tmp_path)
    alerter = mock.MagicMock(spec=MultiChannelAlerter)
    alerter.secondary_configured = True
    alerter.send = mock.MagicMock(return_value={"primary_ok": True, "secondary_ok": True})
    hb = Heartbeat(alerter=alerter, heartbeat_path=p, selftest_every=3)
    for _ in range(3):
        hb.beat()
    # Exactly one selftest call (the 3rd beat is the cadence boundary)
    selftests = [c for c in alerter.send.call_args_list if c.kwargs.get("force_secondary")]
    assert len(selftests) == 1
    # Subject is SELFTEST tag
    assert "[SELFTEST]" in selftests[0].args[0]


def test_heartbeat_beat_swallows_write_errors(tmp_path: Path) -> None:
    """If the disk goes read-only, beat() must not crash the main loop."""
    p = _tmp_hb_path(tmp_path)
    alerter = mock.MagicMock(spec=MultiChannelAlerter)
    alerter.secondary_configured = False
    hb = Heartbeat(alerter=alerter, heartbeat_path=p)
    with mock.patch("heartbeat._atomic_write_json", side_effect=OSError("ro fs")):
        # Should not raise
        hb.beat(cycle=1)


def test_heartbeat_selftest_logs_critical_when_both_fail(tmp_path: Path) -> None:
    p = _tmp_hb_path(tmp_path)
    alerter = mock.MagicMock(spec=MultiChannelAlerter)
    alerter.secondary_configured = True
    alerter.send = mock.MagicMock(return_value={"primary_ok": False, "secondary_ok": False})
    hb = Heartbeat(alerter=alerter, heartbeat_path=p, selftest_every=1)
    # Use the logger of the heartbeat module to catch CRITICAL
    with mock.patch("heartbeat.logger") as lg:
        hb.beat()
        critical_calls = [c for c in lg.critical.call_args_list]
        assert any("BLIND" in str(c) for c in critical_calls)
