@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================================
echo  STAGE 00 - EMAIL URL EXTRACTION ONLY
echo  %DATE%  %TIME%
echo ============================================================
echo.
echo Drop .eml files into 00-emails\ before running.
echo Extracted .url files will appear in 01-extracted\
echo Processed .eml files will be deleted automatically.
echo.
echo [STAGE 00] Parsing emails...
echo --------------------------------------------
python -u 00-parse_email.py
if errorlevel 1 echo WARNING: Stage 00 exited with errors.

echo.
echo Done. Run 02-dedup.bat and onwards to process, or use 00-parse_and_process.bat.
echo.
pause
