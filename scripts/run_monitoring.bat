@echo off
REM Daily OGD weight monitor — saves JSON snapshot + appends to log.
REM Schedule via Windows Task Scheduler at e.g. 03:00 UTC daily.
REM Exits with code 2 on global=CRIT so the scheduler can alert.
cd /d "%~dp0\.."
set TS=%date:~-4%-%date:~3,2%-%date:~0,2%
if not exist "data\monitoring" mkdir "data\monitoring"
python monitoring.py --json "data\monitoring\report_%TS%.json" --text --exit-on-crit >> "data\monitoring\monitoring.log" 2>&1
exit /b %errorlevel%
