@echo off
REM Weekly COT capture job (CFTC COMEX + LME MiFID II positioning).
REM Scheduled via Windows Task Scheduler as "HomeFund-WeeklyCOT".
REM %~dp0 is this file's dir (jobs\); ".." is the repo root.
cd /d "%~dp0.."
call ".venv\Scripts\activate.bat"
echo ---- %DATE% %TIME% ---- >> "data\weekly_cot_capture.log"
python -m adapters.cot_capture >> "data\weekly_cot_capture.log" 2>&1
