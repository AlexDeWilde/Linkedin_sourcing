@echo off
chcp 65001 > nul
cd /d "%~dp0"
python 03-quick_filter.py
pause
