@echo off
cd /d "%~dp0.."
echo Starting RFP Dashboard...
echo Open: http://localhost:5000
echo Press Ctrl+C to stop.
echo.
python run_dashboard.py
pause
