@echo off
setlocal
title TradeAI — Signal Bot

rem ── Load env vars from env.bat if it exists ─────────────────
if exist "%~dp0..\env.bat" (
    call "%~dp0..\env.bat"
)

rem ── Validate required env vars ───────────────────────────────
if "%TELEGRAM_TOKEN%"=="" (
    echo.
    echo  ERROR: TELEGRAM_TOKEN is not set.
    echo.
    echo  Create env.bat in the project root:
    echo    set TELEGRAM_TOKEN=your_token_here
    echo    set CHAT_ID=your_chat_id_here
    echo.
    echo  Or set it directly in this terminal before running.
    echo.
    pause
    exit /b 1
)

rem ── Auto-restart loop ────────────────────────────────────────
cd /d "%~dp0.."
echo  Starting TradeAI Signal Bot (auto-restart enabled)...
echo  Press Ctrl+C to stop permanently.
echo.

:restart_loop
echo [%TIME%] Starting crypto_alert.py...
python crypto_alert.py
set EXIT_CODE=%ERRORLEVEL%
echo.
echo [%TIME%] Bot exited with code %EXIT_CODE%.

rem Exit code 0 = intentional stop (Ctrl+C or clean shutdown) — do not restart
if %EXIT_CODE%==0 (
    echo  Clean exit detected — not restarting.
    goto :done
)

echo  Unexpected exit — restarting in 5 seconds (press Ctrl+C to cancel)...
timeout /t 5 /nobreak >nul
goto :restart_loop

:done
pause
endlocal
