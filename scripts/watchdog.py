"""External dead-man's-switch watchdog.

Runs as a sidecar process (separate from crypto_alert.py). Polls
``data/heartbeat.json`` every ``--interval`` seconds; if the file is older
than ``--staleness`` seconds, fires alerts on both Telegram and SMTP.

Why a separate process: a watchdog living in the same Python interpreter as
the bot can never detect ``kill -9``, segfault, or main-loop deadlock. The
watchdog must be supervised independently — see ``scripts/supervisord.conf``
(Linux) or run via Windows Task Scheduler / NSSM service.

Usage (manual):
    python scripts/watchdog.py
    python scripts/watchdog.py --interval 60 --staleness 600

Required env vars (inherits from the bot):
    TELEGRAM_TOKEN, CHAT_ID    — primary alert path
    SMTP_HOST / PORT / USER / PASS / TO  — optional secondary path
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import requests  # noqa: E402

# Load .env / .env.vault so TELEGRAM_TOKEN / CHAT_ID resolve when the watchdog
# is started by supervisord with a minimal inherited environment.
from secrets_loader import load_env as _load_env  # noqa: E402
_load_env(repo_root=_ROOT)

from heartbeat import HEARTBEAT_FILE, SmtpAlerter, is_stale  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("watchdog")


def _send_telegram(message: str) -> bool:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("CHAT_ID", "")
    if not token or not chat:
        logger.warning("TELEGRAM_TOKEN/CHAT_ID not set — primary alert path disabled")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat, "text": message}, timeout=10)
        if r.status_code == 200:
            return True
        logger.error(f"Telegram returned {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Telegram send raised: {e}")
        return False


def _alert(subject: str, body: str) -> None:
    """Fire on BOTH channels — this is exactly when redundancy must work."""
    full = f"{subject}\n{body}"
    tg_ok = _send_telegram(full)
    smtp = SmtpAlerter()
    smtp_ok = smtp.send(subject, body) if smtp.configured else False
    logger.info(f"alert dispatched — telegram={'OK' if tg_ok else 'FAIL'} smtp={'OK' if smtp_ok else 'FAIL/UNCONFIGURED'}")
    if not tg_ok and not smtp_ok:
        logger.critical("BOTH channels failed — operator will not be notified")


def main() -> int:
    p = argparse.ArgumentParser(description="TradeAI dead-man's-switch watchdog")
    p.add_argument("--interval", type=int, default=60,
                   help="seconds between heartbeat checks (default 60)")
    p.add_argument("--staleness", type=int,
                   default=int(os.environ.get("HEARTBEAT_STALENESS_SEC", "600")),
                   help="seconds without heartbeat before alerting (default 600 = 10 min)")
    p.add_argument("--realert-cooldown", type=int, default=900,
                   help="seconds between re-alerts while still down (default 900 = 15 min)")
    p.add_argument("--heartbeat-file", default=str(HEARTBEAT_FILE))
    args = p.parse_args()

    hb_path = Path(args.heartbeat_file)
    logger.info(f"starting — file={hb_path} interval={args.interval}s staleness={args.staleness}s")
    _alert(
        "Watchdog started",
        f"Watchdog now monitoring {hb_path}\n"
        f"Stale threshold: {args.staleness}s\n"
        f"Started: {datetime.now().isoformat(timespec='seconds')}",
    )

    last_alert_ts = 0.0
    last_state = "OK"   # OK | STALE
    while True:
        stale, age, payload = is_stale(hb_path, staleness_sec=args.staleness)
        now = time.time()

        if stale:
            need_alert = (last_state == "OK") or (now - last_alert_ts >= args.realert_cooldown)
            if need_alert:
                if payload is None:
                    body = (
                        f"HEARTBEAT FILE MISSING\n"
                        f"Expected at: {hb_path}\n"
                        f"The bot has either never started or crashed before writing its first beat.\n"
                        f"Time: {datetime.now().isoformat(timespec='seconds')}"
                    )
                    subject = "Bot heartbeat MISSING"
                else:
                    body = (
                        f"BOT HEARTBEAT STALE — possible crash or hang\n"
                        f"Last beat: {payload.get('ts_utc', 'unknown')} UTC ({age:.0f}s ago)\n"
                        f"PID:       {payload.get('pid', '?')}\n"
                        f"Cycle:     {payload.get('cycle', '?')}\n"
                        f"Mode:      {payload.get('execution_mode', '?')}\n"
                        f"Threshold: {args.staleness}s\n"
                        f"Investigate immediately: check bot console, system, network."
                    )
                    subject = "Bot heartbeat STALE"
                _alert(subject, body)
                last_alert_ts = now
            last_state = "STALE"
        else:
            if last_state == "STALE":
                # Recovery — tell operator the bot is back
                ts_utc = (payload or {}).get("ts_utc", "?")
                _alert(
                    "Bot RECOVERED",
                    f"Heartbeat resumed.\nLast beat: {ts_utc} UTC ({age:.0f}s ago)\nThe bot is alive again.",
                )
                last_alert_ts = now
            last_state = "OK"

        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("watchdog stopped by user")
        sys.exit(0)
