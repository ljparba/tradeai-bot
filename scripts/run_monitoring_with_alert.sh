#!/usr/bin/env bash
# Daily OGD-weight monitoring runner with Telegram alert on CRIT.
#
# R5 fix (master audit 2026-05-26): the OGD-MON-SCOPE fix wired monitoring.py
# to read the bootstrap pool but no scheduled cron/timer was running it, so
# the Run-46 collapse-mode safeguard was operationally dormant. This wrapper
# is the deploy target for a daily systemd timer.
#
# Flow:
#   1. Activate venv / project path
#   2. Run monitoring.py --json + --text against bootstrap pool (where 99% of
#      OGD learning lives until paper-trading produces live updates)
#   3. If global alert level is CRIT, send a Telegram alert with the report
#   4. Exit 0 always (timer should not crash on alert-level mismatch)
#
# Secrets: reads TELEGRAM_TOKEN + CHAT_ID from environment. systemd unit
# loads .env via EnvironmentFile.

set -u
PROJECT_ROOT="/home/tradeai/TradeAI"
cd "$PROJECT_ROOT" || exit 1

REPORT_DIR="$PROJECT_ROOT/data/monitoring"
mkdir -p "$REPORT_DIR"
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
DATE_TODAY=$(date -u +%Y-%m-%d)
JSON_OUT="$REPORT_DIR/report_${DATE_TODAY}.json"
LOG_OUT="$REPORT_DIR/report_${DATE_TODAY}.log"

# Run monitoring against BOTH pools — bootstrap is where the mass lives,
# live is where future learning will surface.
{
  echo "=== MONITORING REPORT ${TS} ==="
  echo
  echo "--- BOOTSTRAP POOL (backtest_token_weights) ---"
  python3 monitoring.py --text --source bootstrap 2>&1
  echo
  echo "--- LIVE POOL (token_weights) ---"
  python3 monitoring.py --text --source live 2>&1
  echo
} > "$LOG_OUT" 2>&1

# Capture global alert level from bootstrap pool (the dominant one)
python3 monitoring.py --json "$JSON_OUT" --source bootstrap 2>/dev/null
GLOBAL_LEVEL=$(python3 -c "
import json, sys
try:
    with open('$JSON_OUT') as f:
        d = json.load(f)
    print(d.get('summary',{}).get('global_alert_level','UNKNOWN'))
except Exception:
    print('READ_ERROR')
" 2>/dev/null)

echo "[monitor-cron] $TS global_alert_level=$GLOBAL_LEVEL"

# Telegram alert only on CRIT
if [ "$GLOBAL_LEVEL" = "CRIT" ]; then
    if [ -n "${TELEGRAM_TOKEN:-}" ] && [ -n "${CHAT_ID:-}" ]; then
        # Pull a 20-line summary from the log
        SUMMARY=$(head -40 "$LOG_OUT" | tail -30)
        MSG="<b>[OGD MONITOR CRIT]</b>
Time: $TS
Global alert level: <b>CRIT</b>

<pre>$SUMMARY</pre>

Full report: data/monitoring/report_${DATE_TODAY}.log"
        curl -sS -X POST \
            "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
            -d "chat_id=${CHAT_ID}" \
            -d "parse_mode=HTML" \
            --data-urlencode "text=${MSG}" \
            > /dev/null 2>&1
        echo "[monitor-cron] CRIT alert sent to Telegram"
    else
        echo "[monitor-cron] WARN: CRIT detected but TELEGRAM_TOKEN/CHAT_ID not set"
    fi
fi

# Always exit 0 so systemd timer doesn't mark unit as failed on CRIT
exit 0
