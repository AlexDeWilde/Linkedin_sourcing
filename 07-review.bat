@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo Checking Flask...
pip show flask > nul 2>&1 || pip install flask
echo.
echo Starting Job Review Console at http://localhost:5000
echo Press Ctrl+C to stop.
echo.
python -u 07-review.py
pause
