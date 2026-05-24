"""TradeAI atomic process-state store.

Phase A-2 (ENTERPRISE_ROADMAP). Companion to `heartbeat.py`. The DB already
handles atomicity for signals, cooldowns, OGD weights, and named scalars
(`bot_state` table). This module covers the in-process counters that today
live only in Python locals and therefore reset on every restart:

    * cycle number
    * consecutive error count
    * last cycle wall-clock timestamp
    * last hourly-heartbeat wall-clock timestamp
    * arbitrary additional key/value pairs the caller chooses to persist

Three guarantees:

1. **Atomic writes** — write to a sibling ``.tmp`` file, ``fsync``, then
   ``os.replace`` (atomic on POSIX, near-atomic on NTFS). A crash mid-write
   never leaves a half-written state file.

2. **Backup rotation** — the previous good copy is preserved as ``.bak`` so
   ``load()`` can recover even if the primary file is corrupt.

3. **PID-file double-start guard** — refuses to start a second bot process
   while the first is still alive. Two bots on the same DB cause split-brain
   OGD updates; supervisord auto-restart makes this a real risk.

The module is stdlib-only and never raises into the caller for save errors —
state persistence is best-effort by design (a missed snapshot is fine, a
crashed bot is not).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger("tradeai.state_store")

_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _ROOT / "data"
_DATA_DIR.mkdir(exist_ok=True)

STATE_FILE = _DATA_DIR / "process_state.json"
PID_FILE = _DATA_DIR / "tradeai.pid"


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON to `path` via temp+fsync+rename. Raises on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        # On Windows os.replace is atomic on the same volume; on POSIX it's
        # atomic always. This is the strongest portable guarantee we have.
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


class StateStore:
    """Persistent dict-of-scalars with backup rotation.

    Usage::

        store = StateStore()
        state = store.load(defaults={"cycle": 0, "consecutive_errors": 0})
        state["cycle"] += 1
        store.save(state)

    Or transactionally::

        with store.transaction(defaults={...}) as state:
            state["cycle"] += 1
        # auto-saved at context exit

    All payload values must be JSON-serialisable. Non-serialisable values are
    silently dropped from `save()` after a warning.
    """

    def __init__(self, path: Path = STATE_FILE) -> None:
        self.path = path
        self.bak_path = path.with_suffix(path.suffix + ".bak")

    def load(self, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return persisted state merged over `defaults`. Recovers from corruption."""
        defaults = dict(defaults or {})
        data = _safe_read_json(self.path)
        if data is None:
            # Try backup
            data = _safe_read_json(self.bak_path)
            if data is not None:
                logger.warning(f"[STATE] primary {self.path.name} corrupt; recovered from .bak")
            else:
                if self.path.exists() or self.bak_path.exists():
                    logger.warning(f"[STATE] both {self.path.name} and .bak unreadable; using defaults")
                data = {}
        merged = defaults
        merged.update(data)
        return merged

    def save(self, state: Dict[str, Any]) -> bool:
        """Atomically persist `state`. Returns True on success.

        Never raises — state persistence is best-effort by design.
        """
        try:
            # Drop non-serialisable values rather than blowing up the loop
            clean: Dict[str, Any] = {}
            for k, v in state.items():
                try:
                    json.dumps(v)
                    clean[str(k)] = v
                except (TypeError, ValueError):
                    logger.warning(f"[STATE] dropping non-JSON key {k!r}: {type(v).__name__}")
            clean["_saved_at"] = time.time()
            # Rotate primary → .bak before writing new primary
            if self.path.exists():
                try:
                    os.replace(self.path, self.bak_path)
                except OSError as e:
                    # Non-fatal — backup rotation failure shouldn't block the new write
                    logger.debug(f"[STATE] .bak rotation skipped: {e}")
            _atomic_write_json(self.path, clean)
            return True
        except Exception as e:
            logger.error(f"[STATE] save failed: {e}")
            return False

    @contextlib.contextmanager
    def transaction(self, defaults: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """Load → yield mutable dict → save on context exit (even on exception)."""
        state = self.load(defaults=defaults)
        try:
            yield state
        finally:
            self.save(state)


# ══════════════════════════════════════════════════════════
# PID FILE — double-start guard
# ══════════════════════════════════════════════════════════
def _pid_alive(pid: int) -> bool:
    """Best-effort check that `pid` is a running process on this OS."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows: use os.kill(pid, 0). If process is gone it raises OSError.
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    # POSIX: signal 0 probes existence without delivering
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists, but we lack permission to signal it. Treat as alive.
        return True
    except OSError:
        return False


class PidFile:
    """Cross-platform single-instance guard.

    Usage::

        with PidFile() as pid_file:
            run_bot()
        # on exit the file is removed

    If a stale pid file exists (process is gone) it is silently reclaimed.
    If the recorded PID is still alive, ``__enter__`` raises ``RuntimeError``.
    """

    def __init__(self, path: Path = PID_FILE) -> None:
        self.path = path
        self._acquired = False

    def acquire(self) -> None:
        if self.path.exists():
            try:
                prev_pid = int(self.path.read_text(encoding="utf-8").strip() or 0)
            except (ValueError, OSError):
                prev_pid = 0
            if prev_pid and prev_pid != os.getpid() and _pid_alive(prev_pid):
                raise RuntimeError(
                    f"Another TradeAI process is running (pid={prev_pid}). "
                    f"Refusing to start — two bots on one DB would corrupt OGD state. "
                    f"Kill the other process or delete {self.path} if you are sure it is dead."
                )
            else:
                logger.info(f"[PID] reclaiming stale pid file (prev pid {prev_pid} not running)")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(os.getpid()), encoding="utf-8")
            self._acquired = True
        except OSError as e:
            logger.error(f"[PID] could not write pid file: {e}")
            # Non-fatal: continue without guard rather than refusing to run

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            if self.path.exists():
                # Only delete if it's still our PID — guards against the race
                # where a respawned bot overwrote ours and we're now exiting.
                try:
                    recorded = int(self.path.read_text(encoding="utf-8").strip() or 0)
                except (ValueError, OSError):
                    recorded = 0
                if recorded == os.getpid():
                    self.path.unlink()
        except OSError as e:
            logger.debug(f"[PID] release: {e}")
        self._acquired = False

    def __enter__(self) -> "PidFile":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
