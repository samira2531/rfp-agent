@echo off
setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [ERROR] Not set up yet.  Run setup.bat first, then try again.
    pause & exit /b 1
)

echo ============================================================
echo   RFP Agent  --  Fetching new RFPs now
echo ============================================================
echo.
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\run_agent.py"
echo.
echo Done.  Open start_dashboard.bat to view results.
echo.
pause
