@echo off
setlocal EnableDelayedExpansion

:: ── Project root is the folder containing this file ──────────────────────────
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

echo.
echo ============================================================
echo   RFP Agent  --  One-Time Setup
echo ============================================================
echo   Project folder: %ROOT%
echo.

:: ── Step 0: Python check ──────────────────────────────────────────────────────
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         During install, check "Add Python to PATH".
    echo.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo [OK] Python %PYVER%

:: ── Step 1: Virtual environment ───────────────────────────────────────────────
echo.
echo [1/4] Setting up virtual environment (.venv) ...
if exist "%ROOT%\.venv\Scripts\python.exe" (
    echo       Already exists -- skipping.
) else (
    python -m venv "%ROOT%\.venv"
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Could not create virtual environment.
        pause & exit /b 1
    )
    echo       Created.
)
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "PYTHONW=%ROOT%\.venv\Scripts\pythonw.exe"
set "PIP=%ROOT%\.venv\Scripts\pip.exe"

:: ── Step 2: Install dependencies ──────────────────────────────────────────────
echo.
echo [2/4] Installing Python packages ...
"%PIP%" install --upgrade pip --quiet
"%PIP%" install -r "%ROOT%\requirements.txt" --quiet
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Package installation failed.
    echo         Check your internet connection and try again.
    pause & exit /b 1
)
echo       All packages installed.

:: ── Step 3: Create runtime directories ───────────────────────────────────────
echo.
echo [3/4] Creating runtime directories ...
if not exist "%ROOT%\data"      mkdir "%ROOT%\data"
if not exist "%ROOT%\logs"      mkdir "%ROOT%\logs"
if not exist "%ROOT%\downloads" mkdir "%ROOT%\downloads"
echo       data\   logs\   downloads\   ready.

:: ── Step 4: Register Windows Task Scheduler ───────────────────────────────────
echo.
echo [4/4] Scheduling daily RFP fetch at 7:00 AM ...

:: Write a temp PowerShell file to avoid quoting issues in the batch command line
set "TMPPS=%TEMP%\rfp_register_task.ps1"

(
    echo $proj  = '%ROOT%'
    echo $py    = '%PYTHONW%'
    echo $sc    = '%ROOT%\run_agent.py'
    echo $act   = New-ScheduledTaskAction -Execute $py -Argument "`"$sc`"" -WorkingDirectory $proj
    echo $trig  = New-ScheduledTaskTrigger -Daily -At '07:00'
    echo $set   = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ^(New-TimeSpan -Minutes 30^)
    echo Register-ScheduledTask -TaskName 'RFP Agent Daily' -Action $act -Trigger $trig -Settings $set -Force ^| Out-Null
    echo Write-Host 'Task registered.'
) > "%TMPPS%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%TMPPS%"
del "%TMPPS%" 2>nul

if %ERRORLEVEL% neq 0 (
    echo [WARN] Task Scheduler registration failed.
    echo        You can still fetch manually: double-click run_now.bat
) else (
    echo       Scheduled OK.
    echo       Runs daily at 7 AM; catches up automatically if PC was off.
)

:: ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo ============================================================
echo   Setup complete!
echo.
echo   Fetch RFPs now  -->  double-click  run_now.bat
echo   View dashboard  -->  double-click  start_dashboard.bat
echo                        then open     http://localhost:5000
echo.
echo   Daily auto-fetch: 7:00 AM (no action needed)
echo ============================================================
echo.
pause
