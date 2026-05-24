@echo off
REM ---------------------------------------------------------------------------
REM TradeAI watchdog Windows launcher  (Phase A-1 dead-man's switch)
REM
REM Run this in a separate cmd window from the bot, or register it as a second
REM NSSM service:
REM     nssm install TradeAIWatchdog "C:\Users\User\Desktop\TradeAI\scripts\run_watchdog.bat"
REM     nssm set TradeAIWatchdog AppDirectory "C:\Users\User\Desktop\TradeAI"
REM ---------------------------------------------------------------------------

setlocal

set BOT_DIR=%~dp0..
cd /d "%BOT_DIR%"

:loop
echo [%date% %time%] [WATCHDOG-SUPERVISOR] starting watchdog
python scripts\watchdog.py --interval 60 --staleness 600
echo [%date% %time%] [WATCHDOG-SUPERVISOR] watchdog exited — restarting in 10s
timeout /t 10 /nobreak >nul
goto loop

endlocal
