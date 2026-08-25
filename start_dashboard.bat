@echo off
setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [ERROR] Not set up yet.  Run setup.bat first, then try again.
    pause & exit /b 1
)

echo ============================================================
echo   RFP Dashboard
echo   Open in browser:  http://localhost:5000
echo   Press Ctrl+C to stop.
echo ============================================================
echo.
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\run_dashboard.py"
pause
