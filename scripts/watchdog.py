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
import html
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


def _send_telegram(html_text: str) -> bool:
    """Send a Telegram message in HTML parse-mode. Falls back to plain text
    if HTML parsing fails (e.g., malformed <pre> or unescaped <)."""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("CHAT_ID", "")
    if not token or not chat:
        logger.warning("TELEGRAM_TOKEN/CHAT_ID not set — primary alert path disabled")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            data={"chat_id": chat, "text": html_text, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.status_code == 200:
            return True
        # HTML parse-error fallback — retry as plain text without tags
        body = (r.text or "").lower()
        if "can't parse" in body or "parse" in body:
            import re as _re
            plain = _re.sub(r"<[^>]+>", "", html_text)
            r2 = requests.post(url, data={"chat_id": chat, "text": plain}, timeout=10)
            if r2.status_code == 200:
                logger.warning("Telegram HTML parse failed — sent as plain text")
                return True
        logger.error(f"Telegram returned {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Telegram send raised: {e}")
        return False


def _alert(subject: str, html_body: str, plain_body: str | None = None) -> None:
    """Fire on BOTH channels — this is exactly when redundancy must work.

    html_body  HTML-formatted Telegram payload (must escape <,>,& in dynamic values).
    plain_body Plain-text SMTP body. If None, falls back to HTML-stripped html_body.
    """
    if plain_body is None:
        import re as _re
        plain_body = _re.sub(r"<[^>]+>", "", html_body)
    tg_full = f"<b>{subject}</b>\n\n{html_body}"
    tg_ok = _send_telegram(tg_full)
    smtp = SmtpAlerter()
    smtp_ok = smtp.send(subject, plain_body) if smtp.configured else False
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

    _stale_minutes = max(1, args.staleness // 60)
    _started_str   = datetime.now().strftime("%Y-%m-%d %H:%M")
    _hr = "━" * 22  # mirrors crypto_alert._TG_HR — same visual width
    # 2026-05-28 redesign — match the clean signal/heartbeat/exit Telegram
    # style across operational alerts. Drops <pre> blocks (no copy button)
    # in favor of emoji-bulleted fields with a unicode divider.
    _alert(
        "\U0001F436 Watchdog ACTIVE",
        html_body=(
            f"{_hr}\n"
            f"\n\U0001F4C2 <b>Monitoring:</b> <code>{html.escape(str(hb_path))}</code>"
            f"\n⏱ <b>Threshold:</b> {_stale_minutes} min stale"
            f"\n⏰ <b>Started:</b> {html.escape(_started_str)}"
        ),
        plain_body=(
            f"Monitoring:  {hb_path}\n"
            f"Threshold:   {_stale_minutes} min stale\n"
            f"Started:     {_started_str}"
        ),
    )

    # L-NEW-4 fix (cycle-9 audit 2026-05-28): watchdog self-heartbeat.
    # Pre-fix this loop could itself hang on emit() or is_stale() and
    # systemd would still report the service "active" with no operator
    # notification — the classic who-watches-the-watcher gap. We now
    # touch a self-heartbeat file every loop iteration so an external
    # check (cron, dashboard ping, or supervisord) can detect a frozen
    # watchdog. Self-test, no alert path — purely a liveness marker.
    _self_hb_path = hb_path.parent / "watchdog_alive.txt"
    last_alert_ts = 0.0
    last_state = "OK"   # OK | STALE
    while True:
        # Self-heartbeat write — best-effort, never raises into the loop
        try:
            _self_hb_path.write_text(str(int(time.time())))
        except Exception:
            pass
        stale, age, payload = is_stale(hb_path, staleness_sec=args.staleness)
        now = time.time()

        if stale:
            need_alert = (last_state == "OK") or (now - last_alert_ts >= args.realert_cooldown)
            if need_alert:
                _age_min = max(1, int(age // 60))
                if payload is None:
                    subject = "\U0001F6A8 Watchdog BOT NOT RUNNING"
                    html_body = (
                        f"{_hr}\n"
                        f"\n\U0001F4C2 <b>Expected at:</b> <code>{html.escape(str(hb_path))}</code>"
                        "\n\n<i>Heartbeat file is missing. The bot has either never "
                        "started, or crashed before writing its first heartbeat.</i>"
                        f"\n\n{_hr}\n"
                        "\n\U0001F50D <b>Check:</b> <code>sudo systemctl status tradeai</code>"
                        "\n▶️ <b>Start:</b> <code>sudo systemctl start tradeai</code>"
                    )
                    plain_body = (
                        "Heartbeat file is missing.\n"
                        f"Expected at: {hb_path}\n\n"
                        "The bot has either never started, or crashed "
                        "before writing its first heartbeat.\n\n"
                        "Check:   sudo systemctl status tradeai\n"
                        "Start:   sudo systemctl start tradeai"
                    )
                else:
                    subject = f"⚠️ Watchdog BOT FROZEN — no heartbeat for {_age_min} min"
                    _last_beat = html.escape(str(payload.get("ts_utc", "unknown")))
                    _pid       = html.escape(str(payload.get("pid", "?")))
                    _cycle     = html.escape(str(payload.get("cycle", "?")))
                    _mode      = html.escape(str(payload.get("execution_mode", "?")))
                    html_body = (
                        f"{_hr}\n"
                        f"\n\U0001F501 <b>Last cycle:</b> #{_cycle} at {_last_beat} UTC"
                        f"\n\U0001F522 <b>PID:</b> {_pid} (alive per systemd)"
                        f"\n⚙️ <b>Mode:</b> {_mode}"
                        f"\n⏱ <b>Threshold:</b> {_stale_minutes} min"
                        f"\n\n{_hr}\n"
                        "\n<i>Likely cause: network hang, deadlock, or stuck API call.</i>"
                        f"\n\n\U0001F50D <b>Check:</b> <code>journalctl -u tradeai -n 50</code>"
                        "\n\U0001F501 <b>Restart:</b> <code>sudo systemctl restart tradeai</code>"
                    )
                    plain_body = (
                        f"Last cycle:  #{payload.get('cycle','?')}  at {payload.get('ts_utc','?')} UTC\n"
                        f"PID:         {payload.get('pid','?')} (alive per systemd)\n"
                        f"Mode:        {payload.get('execution_mode','?')}\n"
                        f"Threshold:   {_stale_minutes} min\n\n"
                        "Likely cause: network hang, deadlock, or stuck API call.\n\n"
                        "Check:   journalctl -u tradeai -n 50\n"
                        "Restart: sudo systemctl restart tradeai"
                    )
                _alert(subject, html_body, plain_body)
                last_alert_ts = now
            last_state = "STALE"
        else:
            if last_state == "STALE":
                # Recovery — tell operator the bot is back
                ts_utc = html.escape(str((payload or {}).get("ts_utc", "?")))
                _age_s = int(age)
                _alert(
                    "✅ Watchdog BOT RECOVERED",
                    html_body=(
                        f"{_hr}\n"
                        f"\n\U0001F493 <b>Last beat:</b> {ts_utc} UTC ({_age_s}s ago)"
                        "\n\n<i>Heartbeat resumed. The bot is alive again.</i>"
                    ),
                    plain_body=(
                        f"Last beat:  {(payload or {}).get('ts_utc', '?')} UTC  ({_age_s}s ago)\n\n"
                        "Heartbeat resumed. The bot is alive again."
                    ),
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
