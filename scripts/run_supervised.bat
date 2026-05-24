@echo off
REM ---------------------------------------------------------------------------
REM TradeAI Windows supervised runner  (Phase A-2 — Windows analogue of supervisord)
REM
REM Real supervisord is Unix-only. On Windows operators have three options:
REM   1. (Recommended) Install NSSM (https://nssm.cc) and register this batch as
REM      a Windows service:
REM         nssm install TradeAI "C:\Users\User\Desktop\TradeAI\scripts\run_supervised.bat"
REM         nssm set TradeAI AppDirectory "C:\Users\User\Desktop\TradeAI"
REM         nssm start TradeAI
REM      NSSM provides crash detection, restart throttling, and log capture.
REM
REM   2. Run this script under Windows Task Scheduler with "Restart on failure".
REM
REM   3. Run it manually in two cmd windows (this one + run_watchdog.bat).
REM
REM Required env vars (set in env.bat before running):
REM     TELEGRAM_TOKEN, CHAT_ID
REM     EXECUTION_MODE              (PAPER unless explicitly switching to LIVE)
REM     LIVE_MODE_CONFIRMED=YES     (required ONLY when EXECUTION_MODE=LIVE)
REM     YOUR_CAPITAL                (required when LIVE)
REM     SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TO  (optional)
REM
REM Restart semantics:
REM     If the Python process exits non-zero, this script sleeps for an
REM     exponentially-increasing backoff (capped at 5 min) and restarts it.
REM     Combined with state_store.py the bot resumes its cycle counter and
REM     consecutive-error tracking across restarts.
REM ---------------------------------------------------------------------------

setlocal EnableDelayedExpansion

set BOT_DIR=%~dp0..
cd /d "%BOT_DIR%"

set BACKOFF=5
set MAX_BACKOFF=300

:loop
echo [%date% %time%] [SUPERVISOR] starting crypto_alert.py
python crypto_alert.py
set EXITCODE=%ERRORLEVEL%

if !EXITCODE! EQU 0 (
    echo [%date% %time%] [SUPERVISOR] crypto_alert.py exited cleanly ^(code 0^) — not restarting
    goto end
)

echo [%date% %time%] [SUPERVISOR] crypto_alert.py exited with code !EXITCODE! — restarting in !BACKOFF!s
timeout /t !BACKOFF! /nobreak >nul

set /a BACKOFF=BACKOFF*2
if !BACKOFF! GTR !MAX_BACKOFF! set BACKOFF=!MAX_BACKOFF!

goto loop

:end
endlocal
