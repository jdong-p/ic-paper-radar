@echo off
rem Engineer Paper Radar: double-click to open the Setup & Control Center (STARTUP.html) with working buttons.
rem It runs "python briefing.py --gui": a small server on http://127.0.0.1 (this computer only) that opens
rem your browser. Keep this window open while you use the page; close it (or Ctrl+C) to stop.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 briefing.py --gui
) else (
    python briefing.py --gui
)
if errorlevel 1 (
    echo.
    echo The Control Center stopped with an error. Python 3.11+ must be installed: https://www.python.org/downloads/
    pause
)
