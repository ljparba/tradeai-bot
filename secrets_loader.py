"""
TradeAI — Secrets Loader
=========================
Loads secrets from .env / .env.vault into os.environ at process start.

Roadmap reference:
  • Phase A item #4 of docs/ENTERPRISE_ROADMAP.md ("dotenv-vault — ADOPT")
  • Cross-check per docs/ROADMAP_AUDIT_CROSSCHECK.md:
    config.py owns non-secret tunables; this module owns SECRETS.

Why two files (.env + .env.vault):
  • .env       — plain-text local development (gitignored). Used by default.
  • .env.vault — AES-256-GCM encrypted bundle (committable). Decrypted at
                 runtime using DOTENV_KEY env var. Only loaded when the
                 optional `dotenv-vault` package is installed AND
                 DOTENV_KEY is set in the environment.

Lookup order (highest priority wins):
  1. Existing os.environ values (set before bot start) — never overridden
  2. .env.vault decrypted secrets (if vault is enabled)
  3. .env plain values (local dev)
  4. env.bat / env.example.bat (legacy Windows path — still honored)

No-deps fallback:
  The stdlib parser supports the standard .env subset used by python-dotenv:
    KEY=value
    KEY="quoted value with spaces"
    KEY='single-quoted'
    # comments
    export KEY=value     (the `export ` prefix is stripped)
  Anything more exotic (variable expansion, multi-line) is NOT supported —
  use plain shell-style values to avoid surprises.

Importing this module DOES NOT auto-load. Callers must invoke load_env()
explicitly at the top of their process entry point, BEFORE any module
that reads os.environ.get(...) is imported.

Security:
  • .env IS gitignored (.gitignore line "/.env").
  • .env.vault is safe to commit — it's encrypted at rest with DOTENV_KEY,
    which lives only in your local/CI environment.
  • Never log the raw values of TELEGRAM_TOKEN or any secret — only their
    presence/absence is logged here.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

_logger = logging.getLogger("secrets_loader")

# Module-level guard so load_env() is idempotent within one process.
_LOADED: bool = False
_REPO_ROOT: Path = Path(__file__).resolve().parent


# ── stdlib .env parser ────────────────────────────────────────────────────────
def _parse_env_text(text: str) -> Dict[str, str]:
    """Parse .env-formatted text into a dict.

    Supported lines (matches python-dotenv's common subset):
      KEY=value
      KEY="value with spaces"   (quotes are stripped)
      KEY='value'               (single quotes are stripped)
      export KEY=value          (the `export ` prefix is stripped)
      # this whole line is a comment
      <blank line>

    Unsupported (silently ignored — logged at DEBUG):
      multi-line values, variable expansion, JSON values, shell substitution.
    """
    out: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # strip "export " prefix
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        # CMD-style "set KEY=VAL" — friendliness with legacy env.bat content
        if line.lower().startswith("set "):
            line = line[len("set "):].lstrip()
        if "=" not in line:
            _logger.debug(f"secrets_loader: skipping malformed .env line: {raw_line!r}")
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key[0].isalpha() and key[0] != "_":
            _logger.debug(f"secrets_loader: skipping invalid env key {key!r}")
            continue
        value = value.strip()
        # Strip matching surrounding quotes (single or double).
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        out[key] = value
    return out


def _read_dotenv_file(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Windows env.bat may be cp1252; tolerate that.
        text = path.read_text(encoding="cp1252", errors="replace")
    return _parse_env_text(text)


# ── optional dotenv-vault decryption ──────────────────────────────────────────
def _try_load_vault(vault_path: Path) -> Tuple[bool, Dict[str, str]]:
    """Attempt to load .env.vault via the optional `dotenv-vault` package.

    Returns (loaded?, decrypted_dict). Never raises — falls back to (False, {})
    on any failure so the plain .env path remains usable in production.
    """
    if not vault_path.is_file():
        return False, {}
    if not os.environ.get("DOTENV_KEY"):
        _logger.info(
            "secrets_loader: .env.vault present but DOTENV_KEY not set — "
            "falling back to plain .env"
        )
        return False, {}
    try:
        # Import here so the package stays OPTIONAL — bot must run without it.
        from dotenv_vault import load_dotenv as _vault_load  # type: ignore
    except ImportError:
        _logger.info(
            "secrets_loader: .env.vault present but `python-dotenv-vault` not "
            "installed — falling back to plain .env. To enable: "
            "`pip install python-dotenv-vault` and set DOTENV_KEY."
        )
        return False, {}
    try:
        # dotenv-vault populates os.environ directly. Snapshot before & after
        # so we can attribute which keys came from the vault.
        before = dict(os.environ)
        _vault_load(dotenv_path=str(vault_path), override=False)
        injected = {k: v for k, v in os.environ.items() if k not in before}
        return True, injected
    except Exception as exc:
        _logger.warning(f"secrets_loader: .env.vault decrypt failed ({exc!r}) — using .env")
        return False, {}


# ── public API ────────────────────────────────────────────────────────────────
def load_env(
    *,
    repo_root: Optional[Path] = None,
    extra_paths: Optional[Iterable[Path]] = None,
    override: bool = False,
) -> Dict[str, str]:
    """Load secrets into os.environ from .env / .env.vault.

    Idempotent within one process — subsequent calls are no-ops unless
    `extra_paths` is provided (which forces a re-scan of just those paths).

    Parameters
    ----------
    repo_root : Path, optional
        Repository root containing .env / .env.vault. Defaults to the directory
        of secrets_loader.py (= project root in normal install).
    extra_paths : iterable of Path, optional
        Additional .env files to read AFTER the default ones. Useful for
        tests that need a temp .env. Last write wins (within the load).
    override : bool, default False
        If True, .env values overwrite values already in os.environ. The
        default False matches python-dotenv's default — pre-set env vars
        (e.g. exported in CI) take precedence.

    Returns
    -------
    dict
        The full key→value map injected into os.environ this call. Empty
        if everything was already loaded.
    """
    global _LOADED
    if _LOADED and not extra_paths:
        return {}

    root = (repo_root or _REPO_ROOT).resolve()
    injected: Dict[str, str] = {}

    # 1. .env.vault (encrypted) — only if all the conditions align.
    vault_loaded, vault_keys = _try_load_vault(root / ".env.vault")
    if vault_loaded:
        injected.update(vault_keys)

    # 2. .env (plain text local) — always loaded if present.
    env_keys = _read_dotenv_file(root / ".env")
    for k, v in env_keys.items():
        if override or k not in os.environ:
            os.environ[k] = v
            injected[k] = v

    # 3. env.bat (legacy Windows CMD format) — keep supporting it so existing
    #    deployments keep working. Same precedence as .env.
    env_bat_keys = _read_dotenv_file(root / "env.bat")
    for k, v in env_bat_keys.items():
        if override or k not in os.environ:
            os.environ[k] = v
            injected[k] = v

    # 4. caller-supplied extras (e.g. tests).
    if extra_paths:
        for p in extra_paths:
            for k, v in _read_dotenv_file(Path(p)).items():
                if override or k not in os.environ:
                    os.environ[k] = v
                    injected[k] = v

    # Log presence (NOT values) of the key secrets so ops can confirm wiring.
    if not _LOADED:
        present = []
        for sk in ("TELEGRAM_TOKEN", "CHAT_ID", "EXECUTION_MODE"):
            if os.environ.get(sk):
                present.append(sk)
        _logger.info(
            f"secrets_loader: loaded ({len(injected)} keys injected); "
            f"present: {present or 'NONE'}"
        )

    _LOADED = True
    return injected


def reset_for_tests() -> None:
    """Reset the idempotency guard. Tests only — never call from production."""
    global _LOADED
    _LOADED = False


__all__ = ["load_env", "reset_for_tests"]
