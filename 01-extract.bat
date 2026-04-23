@echo off
chcp 65001 > nul
REM Close all Chrome windows before running this.
cd /d "%~dp0"
python 01-extract.py
pause
