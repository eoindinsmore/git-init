@echo off
REM Weekly registry-control workbook refresh (registry_control.xlsx).
REM Scheduled via Windows Task Scheduler as "HomeFund-WeeklyWorkbook".
REM Build only: reads registry + store and rewrites the workbook (Tabs 1 & 3),
REM preserving any pending "New Series" input. It never writes back to the YAML;
REM run `python registry_workbook.py sync` by hand for that.
REM %~dp0 is this file's dir (jobs\); ".." is the repo root.
cd /d "%~dp0.."
call ".venv\Scripts\activate.bat"
echo ---- %DATE% %TIME% ---- >> "data\workbook_build.log"
python registry_workbook.py build >> "data\workbook_build.log" 2>&1
