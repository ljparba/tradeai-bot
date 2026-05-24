"""
Tests for secrets_loader.py (Phase A item #4 / dotenv-vault migration).

Coverage:
  • Plain .env parsing (KEY=value, quoted, comments, blanks)
  • CMD `set KEY=val` and `export KEY=val` prefix stripping
  • Precedence: existing os.environ wins over .env (unless override=True)
  • Idempotency: load_env() runs once per process
  • .env.vault graceful fallback when DOTENV_KEY missing / package not installed
  • Secrets do not leak into log output (presence-only logging)
"""
import io
import logging
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import secrets_loader


@pytest.fixture(autouse=True)
def _reset_loader_state(monkeypatch, tmp_path):
    """Reset the module guard before every test."""
    secrets_loader.reset_for_tests()
    # Snapshot environment so per-test mutations don't leak.
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
    secrets_loader.reset_for_tests()


# ══════════════════════════════════════════════════════════════════════════════
# PARSER TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestParser:
    def test_basic_key_value(self):
        result = secrets_loader._parse_env_text("FOO=bar\nBAZ=qux")
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_double_quoted_value(self):
        result = secrets_loader._parse_env_text('GREETING="hello world"')
        assert result == {"GREETING": "hello world"}

    def test_single_quoted_value(self):
        result = secrets_loader._parse_env_text("FOO='bar baz'")
        assert result == {"FOO": "bar baz"}

    def test_export_prefix_stripped(self):
        result = secrets_loader._parse_env_text("export FOO=bar")
        assert result == {"FOO": "bar"}

    def test_cmd_set_prefix_stripped(self):
        # Real env.bat content like "set TELEGRAM_TOKEN=abc123"
        result = secrets_loader._parse_env_text("set TELEGRAM_TOKEN=abc123")
        assert result == {"TELEGRAM_TOKEN": "abc123"}

    def test_set_case_insensitive(self):
        result = secrets_loader._parse_env_text("SET FOO=bar\nSet BAZ=qux")
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_comments_skipped(self):
        text = "# a comment\nFOO=bar\n# another\nBAZ=qux"
        result = secrets_loader._parse_env_text(text)
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_blank_lines_skipped(self):
        result = secrets_loader._parse_env_text("\n\nFOO=bar\n\n")
        assert result == {"FOO": "bar"}

    def test_malformed_lines_skipped(self):
        # No "=" sign — should be silently skipped (logged at DEBUG).
        result = secrets_loader._parse_env_text("no equals here\nGOOD=value\nlikewise")
        assert result == {"GOOD": "value"}

    def test_value_with_equals_preserved(self):
        # Value containing "=" — only the FIRST "=" is the delimiter.
        result = secrets_loader._parse_env_text("URL=https://example.com?a=1&b=2")
        assert result == {"URL": "https://example.com?a=1&b=2"}

    def test_value_with_whitespace_trimmed(self):
        result = secrets_loader._parse_env_text("FOO =   bar   ")
        assert result == {"FOO": "bar"}


# ══════════════════════════════════════════════════════════════════════════════
# load_env() INTEGRATION TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestLoadEnv:
    def test_loads_env_file_into_environ(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("PHASE_A_TEST_KEY=hello\n", encoding="utf-8")
        monkeypatch.delenv("PHASE_A_TEST_KEY", raising=False)
        secrets_loader.load_env(repo_root=tmp_path)
        assert os.environ["PHASE_A_TEST_KEY"] == "hello"

    def test_does_not_override_existing_env_by_default(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("PHASE_A_TEST_KEY=from-env\n", encoding="utf-8")
        monkeypatch.setenv("PHASE_A_TEST_KEY", "from-shell")
        secrets_loader.load_env(repo_root=tmp_path)
        # Pre-set env wins — protects CI / supervisord configs.
        assert os.environ["PHASE_A_TEST_KEY"] == "from-shell"

    def test_override_true_overrides_existing_env(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("PHASE_A_TEST_KEY=from-env\n", encoding="utf-8")
        monkeypatch.setenv("PHASE_A_TEST_KEY", "from-shell")
        secrets_loader.load_env(repo_root=tmp_path, override=True)
        assert os.environ["PHASE_A_TEST_KEY"] == "from-env"

    def test_idempotent(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("PHASE_A_TEST_KEY=first\n", encoding="utf-8")
        monkeypatch.delenv("PHASE_A_TEST_KEY", raising=False)
        secrets_loader.load_env(repo_root=tmp_path)
        # Mutate the file after first load.
        (tmp_path / ".env").write_text("PHASE_A_TEST_KEY=second\n", encoding="utf-8")
        # Second call is a no-op — _LOADED guard.
        injected = secrets_loader.load_env(repo_root=tmp_path)
        assert injected == {}
        assert os.environ["PHASE_A_TEST_KEY"] == "first"

    def test_env_bat_legacy_path_honored(self, tmp_path, monkeypatch):
        # env.bat uses CMD `set KEY=val` syntax — must still parse.
        (tmp_path / "env.bat").write_text(
            "@rem TradeAI test\nset PHASE_A_LEGACY=yes\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("PHASE_A_LEGACY", raising=False)
        secrets_loader.load_env(repo_root=tmp_path)
        assert os.environ["PHASE_A_LEGACY"] == "yes"

    def test_extra_paths_loaded_in_order(self, tmp_path, monkeypatch):
        # Two extra .env files — second one's key wins when override=True.
        extra1 = tmp_path / "first.env"
        extra2 = tmp_path / "second.env"
        extra1.write_text("EXTRA_KEY=first\n", encoding="utf-8")
        extra2.write_text("EXTRA_KEY=second\n", encoding="utf-8")
        monkeypatch.delenv("EXTRA_KEY", raising=False)
        secrets_loader.load_env(
            repo_root=tmp_path,
            extra_paths=[extra1, extra2],
            override=True,
        )
        assert os.environ["EXTRA_KEY"] == "second"

    def test_missing_env_file_does_not_error(self, tmp_path):
        # Empty dir — no .env, no env.bat — should NOT raise.
        out = secrets_loader.load_env(repo_root=tmp_path)
        assert isinstance(out, dict)


# ══════════════════════════════════════════════════════════════════════════════
# .env.vault GRACEFUL FALLBACK
# ══════════════════════════════════════════════════════════════════════════════
class TestVaultFallback:
    def test_vault_skipped_without_dotenv_key(self, tmp_path, monkeypatch, caplog):
        (tmp_path / ".env.vault").write_text("ENCRYPTED_BUNDLE_PLACEHOLDER\n", encoding="utf-8")
        (tmp_path / ".env").write_text("PHASE_A_FALLBACK=plain\n", encoding="utf-8")
        monkeypatch.delenv("DOTENV_KEY", raising=False)
        monkeypatch.delenv("PHASE_A_FALLBACK", raising=False)
        with caplog.at_level(logging.INFO, logger="secrets_loader"):
            secrets_loader.load_env(repo_root=tmp_path)
        # Plain .env still loaded.
        assert os.environ["PHASE_A_FALLBACK"] == "plain"
        # Logged the fallback reason.
        assert any("DOTENV_KEY not set" in r.message for r in caplog.records)

    def test_vault_skipped_when_package_missing(self, tmp_path, monkeypatch, caplog):
        # Simulate the optional package being absent.
        (tmp_path / ".env.vault").write_text("ENCRYPTED\n", encoding="utf-8")
        monkeypatch.setenv("DOTENV_KEY", "dotenv://:key_test@dotenv.local/vault/.env.vault")
        # Force import failure.
        monkeypatch.setitem(sys.modules, "dotenv_vault", None)
        with caplog.at_level(logging.INFO, logger="secrets_loader"):
            ok, keys = secrets_loader._try_load_vault(tmp_path / ".env.vault")
        assert ok is False
        assert keys == {}
        assert any("python-dotenv-vault" in r.message for r in caplog.records)


# ══════════════════════════════════════════════════════════════════════════════
# SECURITY: no secret leakage in logs
# ══════════════════════════════════════════════════════════════════════════════
class TestNoSecretLeakage:
    def test_token_value_never_logged(self, tmp_path, monkeypatch, caplog):
        secret = "1234567:VERY_SECRET_BOT_TOKEN_VALUE_xyz"
        (tmp_path / ".env").write_text(f"TELEGRAM_TOKEN={secret}\n", encoding="utf-8")
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        with caplog.at_level(logging.DEBUG, logger="secrets_loader"):
            secrets_loader.load_env(repo_root=tmp_path)
        full_log = "\n".join(r.getMessage() for r in caplog.records)
        assert secret not in full_log, "secret value leaked into log output"
        # But presence indicator (just the key name) is fine.
        assert "TELEGRAM_TOKEN" in full_log
