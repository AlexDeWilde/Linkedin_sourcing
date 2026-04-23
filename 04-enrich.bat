@echo off
chcp 65001 > nul
cd /d "%~dp0"
python 04-enrich.py
pause
