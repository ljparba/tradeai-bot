@echo off
setlocal
title TradeAI — Tracker Dashboard

rem ── Run ──────────────────────────────────────────────────────
cd /d "%~dp0.."
echo  Starting TradeAI Tracker...
echo  Open: http://localhost:8888
echo  Press Ctrl+C to stop.
echo.
python tracker.py
pause
endlocal
