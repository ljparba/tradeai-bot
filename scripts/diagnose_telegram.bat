@echo off
call "%~dp0..\env.bat"
echo.
echo === TELEGRAM DIAGNOSTIC ===
python "%~dp0diagnose_telegram.py"
pause
