@echo off
cd /d "%~dp0.."
echo ============================================================
echo  RFP Agent Setup
echo ============================================================
echo.
echo [1/2] Installing dependencies...
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 ( echo ERROR: pip install failed. & pause & exit /b 1 )

echo.
echo [2/2] Registering Windows Task Scheduler...
schtasks /create /tn "RFP Agent Daily" /tr "python \"%CD%\run_agent.py\"" /sc DAILY /st 07:00 /f /rl HIGHEST
if %ERRORLEVEL% neq 0 (
    echo WARNING: Task Scheduler registration failed.
    echo Run manually:  python run_agent.py
) else (
    echo Task scheduled — runs daily at 7:00 AM.
)

echo.
echo ============================================================
echo  NEXT STEPS:
echo  1. Edit config\config.yaml to add sources / credentials
echo  2. Test now:  python run_agent.py
echo  3. Dashboard: python run_dashboard.py  -> http://localhost:5000
echo ============================================================
pause
