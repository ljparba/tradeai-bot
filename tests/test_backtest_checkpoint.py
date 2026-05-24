"""Unit tests for backtest_checkpoint.py — Phase A-3 resumable backtest."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backtest_checkpoint import (  # noqa: E402
    _atomic_write_json,
    _config_to_dict,
    clear_checkpoint,
    compute_config_hash,
    describe_checkpoint,
    load_checkpoint,
    save_checkpoint,
)


@dataclasses.dataclass
class _FakeCfg:
    enable_buy: bool = True
    enable_sell: bool = True
    blocked_regimes: tuple = ("CHOPPY",)
    sell_allowed_regimes: frozenset = frozenset()


def test_config_hash_deterministic() -> None:
    params = {"a": 1, "b": "foo", "c": [1, 2, 3]}
    h1 = compute_config_hash(params)
    h2 = compute_config_hash(dict(params))
    assert h1 == h2


def test_config_hash_changes_when_param_changes() -> None:
    h1 = compute_config_hash({"a": 1})
    h2 = compute_config_hash({"a": 2})
    assert h1 != h2


def test_config_hash_handles_dataclass() -> None:
    h1 = compute_config_hash({"cfg": _FakeCfg(enable_buy=True)})
    h2 = compute_config_hash({"cfg": _FakeCfg(enable_buy=False)})
    assert h1 != h2


def test_config_hash_set_order_irrelevant() -> None:
    """sets/frozensets must hash stably regardless of insertion order."""
    h1 = compute_config_hash({"x": {3, 1, 2}})
    h2 = compute_config_hash({"x": {2, 3, 1}})
    assert h1 == h2


def test_config_to_dict_dataclass_normalises_sets() -> None:
    cfg = _FakeCfg(sell_allowed_regimes=frozenset({"TRENDING_BEAR", "RANGING"}))
    d = _config_to_dict(cfg)
    assert d["sell_allowed_regimes"] == ["RANGING", "TRENDING_BEAR"]


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    h = "abc123"
    signals = [{"token": "BTC", "outcome": "WIN"}, {"token": "ETH", "outcome": "LOSS"}]
    assert save_checkpoint(h, ["BTC", "ETH"], signals, started_at="2026-05-22T00:00:00Z", path=p) is True
    data = load_checkpoint(h, path=p)
    assert data is not None
    assert data["completed_tokens"] == ["BTC", "ETH"]
    assert data["all_signals"] == signals
    assert data["signal_count"] == 2
    assert data["started_at"] == "2026-05-22T00:00:00Z"


def test_load_rejects_hash_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    save_checkpoint("hash-A", ["BTC"], [], path=p)
    assert load_checkpoint("hash-B", path=p) is None
    # File is NOT deleted on hash mismatch — operator must clear explicitly
    assert p.exists()


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_checkpoint("any", path=tmp_path / "nope.json") is None


def test_load_handles_malformed_file(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    p.write_text("not json", encoding="utf-8")
    assert load_checkpoint("any", path=p) is None


def test_load_handles_non_dict_payload(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_checkpoint("any", path=p) is None


def test_load_rejects_wrong_schema(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    # Missing all_signals (wrong type)
    json.dump({"config_hash": "h", "completed_tokens": [], "all_signals": "not a list"},
              open(p, "w", encoding="utf-8"))
    assert load_checkpoint("h", path=p) is None


def test_clear_removes_existing(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    save_checkpoint("h", ["BTC"], [], path=p)
    assert p.exists()
    assert clear_checkpoint(path=p) is True
    assert not p.exists()


def test_clear_handles_missing(tmp_path: Path) -> None:
    assert clear_checkpoint(path=tmp_path / "nope.json") is True


def test_describe_checkpoint(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    exists, summary = describe_checkpoint(path=p)
    assert exists is False
    assert "no checkpoint" in summary.lower()

    save_checkpoint("h", ["BTC", "ETH"], [{"x": 1}], path=p)
    exists, summary = describe_checkpoint(path=p)
    assert exists is True
    assert "BTC" in summary and "ETH" in summary
    assert "1 signal" in summary  # signal_count rendered


def test_save_is_atomic_no_tmp_leftover(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.json"
    save_checkpoint("h", ["BTC"], [], path=p)
    save_checkpoint("h", ["BTC", "ETH"], [], path=p)
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_json(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    _atomic_write_json(p, {"k": 1})
    _atomic_write_json(p, {"k": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"k": 2}


def test_resume_flow_simulated(tmp_path: Path) -> None:
    """End-to-end: save partial, load, append, save complete, clear."""
    p = tmp_path / "ckpt.json"
    h = compute_config_hash({"days": 365, "tokens": ["BTC", "ETH", "SOL"]})

    # First run: BTC completes, then "crash"
    save_checkpoint(h, ["BTC"], [{"t": "BTC", "i": 0}], path=p)

    # Second run resumes
    resumed = load_checkpoint(h, path=p)
    assert resumed is not None
    completed = set(resumed["completed_tokens"])
    sigs = list(resumed["all_signals"])
    assert completed == {"BTC"}

    # ETH simulated
    sigs.append({"t": "ETH", "i": 1})
    completed.add("ETH")
    save_checkpoint(h, completed, sigs, path=p)

    # SOL simulated, then done — clear
    sigs.append({"t": "SOL", "i": 2})
    completed.add("SOL")
    save_checkpoint(h, completed, sigs, path=p)

    final = load_checkpoint(h, path=p)
    assert final is not None
    assert set(final["completed_tokens"]) == {"BTC", "ETH", "SOL"}
    assert len(final["all_signals"]) == 3

    clear_checkpoint(path=p)
    assert not p.exists()


def test_config_change_invalidates_checkpoint(tmp_path: Path) -> None:
    """Realistic scenario: parameter changes between runs → no resume."""
    p = tmp_path / "ckpt.json"
    h_old = compute_config_hash({"days": 365, "cooldown": 8})
    h_new = compute_config_hash({"days": 365, "cooldown": 12})  # one param changed
    save_checkpoint(h_old, ["BTC"], [{"t": "BTC"}], path=p)
    # Old-hash load succeeds
    assert load_checkpoint(h_old, path=p) is not None
    # New-hash load rejects
    assert load_checkpoint(h_new, path=p) is None
