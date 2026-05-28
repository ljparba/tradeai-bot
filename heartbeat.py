"""TradeAI dead-man's switch + multi-channel alerter.

Phase A-1 (ENTERPRISE_ROADMAP). Three responsibilities:

1. Liveness file — every cycle the bot calls `Heartbeat.beat()`, which atomically
   rewrites ``data/heartbeat.json``. An external watchdog (``scripts/watchdog.py``)
   polls the file mtime; if it exceeds the staleness threshold the watchdog raises.

2. Secondary alert channel — Telegram is primary, SMTP (env-configured) is fallback.
   When Telegram fails (network outage, token revoked, 429 storm), critical alerts
   still reach the operator via email.

3. Self-test — every Nth heartbeat (default 24, i.e. every ~24h at 1h cadence)
   pings the secondary channel with a SELFTEST message. Per Red Flag #12 a
   silently-dead alert path is worse than no alert path. The self-test counter
   itself is persisted to ``bot_state`` so restarts do not skip it.

The module is intentionally framework-free (stdlib only) and never raises into
the caller — alerter errors are logged but never crash the main loop.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import tempfile
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("tradeai.heartbeat")

_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _ROOT / "data"
_DATA_DIR.mkdir(exist_ok=True)
HEARTBEAT_FILE = _DATA_DIR / "heartbeat.json"

# Watchdog considers the bot dead if heartbeat file is older than this many
# seconds. Set comfortably above CHECK_INTERVAL × 3 so a single slow Binance
# cycle does not trip a false alarm. Caller can override via env var.
DEFAULT_STALENESS_SEC = int(os.environ.get("HEARTBEAT_STALENESS_SEC", "600"))

# Self-test cadence — number of beats between secondary-channel verifications.
# Default 24 ≈ once a day at hourly heartbeat cadence.
SELFTEST_EVERY_N_BEATS = int(os.environ.get("HEARTBEAT_SELFTEST_EVERY", "24"))


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON to path via temp+rename so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class SmtpAlerter:
    """SMTP secondary alert channel. Disabled if env vars are not set.

    Required env vars:
        SMTP_HOST   — e.g. smtp.gmail.com
        SMTP_PORT   — usually 587 (STARTTLS) or 465 (SSL)
        SMTP_USER   — login username
        SMTP_PASS   — login password / app password
        SMTP_FROM   — sender address (defaults to SMTP_USER)
        SMTP_TO     — recipient address (alerts get sent here)
    """

    def __init__(self) -> None:
        self.host = os.environ.get("SMTP_HOST", "").strip()
        self.port = int(os.environ.get("SMTP_PORT", "0") or 0)
        self.user = os.environ.get("SMTP_USER", "").strip()
        self.password = os.environ.get("SMTP_PASS", "")
        self.sender = os.environ.get("SMTP_FROM", self.user).strip()
        self.recipient = os.environ.get("SMTP_TO", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.host and self.port and self.user and self.password and self.recipient)

    def send(self, subject: str, body: str) -> bool:
        if not self.configured:
            logger.debug("[ALERT] SMTP not configured — skipping secondary channel")
            return False
        try:
            msg = EmailMessage()
            msg["From"] = self.sender
            msg["To"] = self.recipient
            msg["Subject"] = f"[TradeAI] {subject}"
            msg.set_content(body)
            ctx = ssl.create_default_context()
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=ctx) as s:
                    s.login(self.user, self.password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=15) as s:
                    s.starttls(context=ctx)
                    s.login(self.user, self.password)
                    s.send_message(msg)
            logger.info(f"[ALERT] SMTP secondary sent: {subject!r}")
            return True
        except Exception as e:
            logger.error(f"[ALERT] SMTP send failed ({subject!r}): {e}")
            return False


class MultiChannelAlerter:
    """Primary + secondary delivery with structured logging.

    The primary channel is injected (typically ``crypto_alert.send_telegram``).
    The secondary defaults to SMTP and is never called if Telegram succeeds —
    unless the caller passes ``force_secondary=True`` (used by self-tests).
    """

    def __init__(
        self,
        primary_send: Callable[[str], bool],
        secondary: Optional[SmtpAlerter] = None,
    ) -> None:
        self.primary_send = primary_send
        self.secondary = secondary if secondary is not None else SmtpAlerter()
        self._last_primary_ok_ts: Optional[float] = None
        self._last_secondary_ok_ts: Optional[float] = None

    @property
    def secondary_configured(self) -> bool:
        return self.secondary.configured

    def send(self, subject: str, body: str, *, force_secondary: bool = False) -> dict:
        """Deliver to primary; fall back to secondary on failure (or always if forced).

        ``body`` may contain HTML tags (<b>, <pre>, <code>, <i>) for the
        Telegram primary channel. The SMTP secondary path receives an
        HTML-stripped version so emails render cleanly without tag noise.

        Returns ``{"primary_ok": bool, "secondary_ok": bool}``.
        """
        result = {"primary_ok": False, "secondary_ok": False}
        try:
            full_msg = body if subject in body else f"{subject}\n{body}"
            result["primary_ok"] = bool(self.primary_send(full_msg))
        except Exception as e:
            logger.error(f"[ALERT] primary send raised: {e}")
            result["primary_ok"] = False

        if result["primary_ok"]:
            self._last_primary_ok_ts = time.time()

        if force_secondary or not result["primary_ok"]:
            # SMTP receives a plain-text version — strip HTML tags so the
            # email body doesn't show literal <b>, <pre>, etc.
            import re as _re
            plain_body = _re.sub(r"<[^>]+>", "", body)
            result["secondary_ok"] = self.secondary.send(subject, plain_body)
            if result["secondary_ok"]:
                self._last_secondary_ok_ts = time.time()

        if not result["primary_ok"] and not result["secondary_ok"]:
            logger.critical(
                f"[ALERT] BOTH channels failed for {subject!r} — operator will not be notified"
            )
        return result


class Heartbeat:
    """Liveness writer + scheduler for periodic self-tests.

    Typical wiring (inside main loop):

        from heartbeat import Heartbeat, MultiChannelAlerter
        alerter = MultiChannelAlerter(primary_send=send_telegram)
        hb = Heartbeat(alerter=alerter,
                       load_counter=lambda: load_scalar_state("hb_selftest_counter", 0),
                       save_counter=lambda v: save_scalar_state("hb_selftest_counter", v))
        ...
        while True:
            ...
            hb.beat(cycle=cycle, open_signals=open_cnt, threshold=eff_thr, wr=wr_live)

    ``beat()`` is cheap: a JSON write and a counter increment. It is safe to
    call every cycle even if no Telegram heartbeat is sent.
    """

    def __init__(
        self,
        alerter: MultiChannelAlerter,
        load_counter: Optional[Callable[[], int]] = None,
        save_counter: Optional[Callable[[int], None]] = None,
        selftest_every: int = SELFTEST_EVERY_N_BEATS,
        heartbeat_path: Path = HEARTBEAT_FILE,
    ) -> None:
        self.alerter = alerter
        self.path = heartbeat_path
        self.selftest_every = max(1, int(selftest_every))
        self._load_counter = load_counter or (lambda: 0)
        self._save_counter = save_counter or (lambda _v: None)
        try:
            self._counter = int(self._load_counter() or 0)
        except Exception:
            self._counter = 0

    def beat(self, **status: object) -> None:
        """Write liveness payload atomically; run self-test on the cadence boundary."""
        payload = {
            "ts_unix": time.time(),
            "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "pid": os.getpid(),
            "execution_mode": os.environ.get("EXECUTION_MODE", "PAPER").upper(),
        }
        payload.update({k: v for k, v in status.items() if v is not None})
        try:
            _atomic_write_json(self.path, payload)
        except Exception as e:
            logger.error(f"[HEARTBEAT] file write failed: {e}")

        self._counter += 1
        try:
            self._save_counter(self._counter)
        except Exception as e:
            logger.warning(f"[HEARTBEAT] counter persist failed: {e}")

        if self._counter % self.selftest_every == 0:
            self.run_selftest()

    def run_selftest(self) -> dict:
        """Send a SELFTEST message via both channels and log outcome.

        Per Red Flag #12: a silently-dead alert path is worse than none. The
        self-test forces a delivery to BOTH primary AND secondary so silent
        rot of the SMTP path is detected within a day at 1h cadence.
        """
        import html as _html
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        _hr = "━" * 22  # mirrors crypto_alert._TG_HR — same visual width
        body = (
            "\U0001FA7A <b>ALERT PATH CHECK</b>\n"
            f"\n{_hr}\n"
            f"\n⏰ <b>Time:</b> {_html.escape(ts)} UTC"
            f"\n\U0001F522 <b>PID:</b> {_html.escape(str(os.getpid()))}"
            f"\n\U0001F493 <b>Beat:</b> #{_html.escape(str(self._counter))}"
            f"\n\n{_hr}\n"
            "\n<i>Confirms both Telegram AND SMTP are reachable. "
            "If you don't see this on every configured channel, "
            "the alert path is degraded — investigate before LIVE.</i>"
        )
        outcome = self.alerter.send("Selftest", body, force_secondary=True)
        logger.info(
            f"[HEARTBEAT] selftest #{self._counter // self.selftest_every}: "
            f"primary={'OK' if outcome['primary_ok'] else 'FAIL'} | "
            f"secondary={'OK' if outcome['secondary_ok'] else 'FAIL/UNCONFIGURED'}"
        )
        if not outcome["primary_ok"] and not outcome["secondary_ok"]:
            logger.critical(
                "[HEARTBEAT] SELFTEST FAILED on BOTH channels — operator is BLIND. "
                "Investigate Telegram token and SMTP credentials immediately."
            )
        elif not outcome["secondary_ok"] and self.alerter.secondary_configured:
            logger.error(
                "[HEARTBEAT] SELFTEST: SMTP secondary path broken. Operator only "
                "has Telegram — fix before LIVE."
            )
        return outcome


def read_heartbeat(path: Path = HEARTBEAT_FILE) -> Optional[dict]:
    """Read the last-written heartbeat payload. Returns None if missing."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def is_stale(path: Path = HEARTBEAT_FILE, staleness_sec: int = DEFAULT_STALENESS_SEC) -> tuple:
    """Return ``(stale: bool, age_sec: float, payload: dict|None)``.

    External watchdog uses this. If the file is missing, returns ``(True, inf, None)``.
    """
    payload = read_heartbeat(path)
    if payload is None:
        return True, float("inf"), None
    try:
        age = time.time() - float(payload.get("ts_unix", 0.0))
    except (TypeError, ValueError):
        return True, float("inf"), payload
    return age > staleness_sec, age, payload
