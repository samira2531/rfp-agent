@echo off
cd /d "%~dp0.."
echo Running RFP Agent...
python run_agent.py
echo.
echo Done. Check logs\rfp_agent.log for details.
pause
