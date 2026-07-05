@echo off
REM Daily premium capture job (Build Order Step 3 — time-sensitive, cannot be backfilled).
REM Scheduled via Windows Task Scheduler as "HomeFund-PremiumCapture".
REM %~dp0 is this file's dir (jobs\); ".." is the repo root.
cd /d "%~dp0.."
call ".venv\Scripts\activate.bat"
echo ---- %DATE% %TIME% ---- >> "data\premium_capture.log"
python -m adapters.premium >> "data\premium_capture.log" 2>&1
