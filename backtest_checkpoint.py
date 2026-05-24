"""Backtest checkpointing — Phase A-3 of ENTERPRISE_ROADMAP.

A single backtest run iterates ~9 tokens × 3 timeframes × 365 days of Binance
candles. A typical full run takes 5–15 minutes; an interrupted run (VPN drop,
Ctrl-C, OS sleep, network blip) loses every minute already spent.

This module persists progress after each token completes:

    data/backtest_checkpoint.json
        {
            "config_hash": "<sha256 of all params that affect signal generation>",
            "started_at":  "<ISO timestamp of the run that created this checkpoint>",
            "completed_tokens": ["BTC", "ETH", ...],
            "all_signals":      [ ... cumulative list of signals ... ]
        }

On startup, ``load_checkpoint(current_hash)`` returns the checkpoint if and only
if the hash matches — any change to ACTIVE_CONFIG or BACKTEST_DAYS or ICT params
invalidates the checkpoint, so a stale resume cannot silently mix results
across two different parameter regimes.

After the full run completes successfully, ``clear_checkpoint()`` removes the
file so the next run starts fresh.

Atomic write semantics match ``state_store.py`` — tmp + fsync + rename.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("tradeai.backtest_checkpoint")

_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _ROOT / "data"
_DATA_DIR.mkdir(exist_ok=True)

CHECKPOINT_FILE = _DATA_DIR / "backtest_checkpoint.json"


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _config_to_dict(cfg: Any) -> Dict[str, Any]:
    """Convert a StrategyConfig dataclass (or similar) into a JSON-stable dict."""
    if cfg is None:
        return {}
    if dataclasses.is_dataclass(cfg):
        d = dataclasses.asdict(cfg)
    elif hasattr(cfg, "__dict__"):
        d = dict(cfg.__dict__)
    else:
        d = {"repr": repr(cfg)}
    # Normalise set → sorted list so the hash is stable across Python runs
    return {k: (sorted(v) if isinstance(v, (set, frozenset)) else v) for k, v in d.items()}


def compute_config_hash(params: Dict[str, Any]) -> str:
    """Stable SHA-256 over the parameter dict.

    The caller passes everything that meaningfully changes signal output — see
    ``backtest.py`` for the canonical set.
    """
    normalised: Dict[str, Any] = {}
    for k, v in sorted(params.items()):
        if dataclasses.is_dataclass(v) or hasattr(v, "__dict__") and not isinstance(v, (str, int, float, bool)):
            normalised[k] = _config_to_dict(v)
        elif isinstance(v, (set, frozenset)):
            normalised[k] = sorted(v)
        elif isinstance(v, dict):
            normalised[k] = {kk: vv for kk, vv in sorted(v.items())}
        else:
            normalised[k] = v
    blob = json.dumps(normalised, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def save_checkpoint(
    config_hash: str,
    completed_tokens: Iterable[str],
    all_signals: List[Dict[str, Any]],
    started_at: Optional[str] = None,
    path: Path = CHECKPOINT_FILE,
) -> bool:
    """Persist progress so far. Best-effort — never raises into the caller."""
    payload = {
        "schema_version": 1,
        "config_hash": config_hash,
        "started_at": started_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "saved_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_tokens": list(completed_tokens),
        "signal_count": len(all_signals),
        "all_signals": all_signals,
    }
    try:
        _atomic_write_json(path, payload)
        return True
    except Exception as e:
        logger.error(f"[CKPT] save failed: {e}")
        return False


def load_checkpoint(
    expected_hash: str,
    path: Path = CHECKPOINT_FILE,
) -> Optional[Dict[str, Any]]:
    """Load checkpoint iff its config_hash matches ``expected_hash``.

    Returns ``None`` if the file is missing, malformed, or stale (hash mismatch).
    Hash mismatch leaves the file in place — the caller decides whether to
    overwrite (a new run) or clear (operator intervention).
    """
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[CKPT] unreadable ({e}) — ignoring")
        return None
    if not isinstance(data, dict):
        logger.warning("[CKPT] not a dict — ignoring")
        return None
    if data.get("config_hash") != expected_hash:
        logger.warning(
            f"[CKPT] config_hash mismatch — checkpoint is from a previous parameter set. "
            f"Run with --no-resume to start fresh, or --clear-checkpoint to delete it."
        )
        return None
    if not isinstance(data.get("completed_tokens"), list):
        return None
    if not isinstance(data.get("all_signals"), list):
        return None
    return data


def clear_checkpoint(path: Path = CHECKPOINT_FILE) -> bool:
    """Remove the checkpoint file. Returns True if removed (or absent)."""
    try:
        if path.exists():
            path.unlink()
            logger.info("[CKPT] cleared")
        return True
    except OSError as e:
        logger.error(f"[CKPT] clear failed: {e}")
        return False


def describe_checkpoint(path: Path = CHECKPOINT_FILE) -> Tuple[bool, str]:
    """Return ``(exists, human_summary)`` — handy for startup banners."""
    if not path.exists():
        return False, "no checkpoint"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ct = data.get("completed_tokens", [])
        sc = data.get("signal_count", "?")
        sa = data.get("saved_at", "?")
        return True, f"checkpoint from {sa}: {len(ct)} tokens done ({', '.join(ct)}), {sc} signals so far"
    except Exception as e:
        return True, f"checkpoint present but unreadable: {e}"
