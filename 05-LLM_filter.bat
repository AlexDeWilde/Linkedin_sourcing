@echo off
chcp 65001 > nul
cd /d "%~dp0"
python -u 05-LLM_filter.py
pause
