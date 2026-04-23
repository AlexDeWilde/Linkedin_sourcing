@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================================
echo  LINKEDIN SOURCING PIPELINE - FULL RUN
echo  %DATE%  %TIME%
echo ============================================================

echo.
echo [STAGE 00] Extract URLs from emails in 00-emails\...
echo --------------------------------------------
python -u 00-parse_email.py
if errorlevel 1 echo WARNING: Stage 00 exited with errors.

echo.
echo [STAGE 01] Extract from LinkedIn searches...
echo --------------------------------------------
python 01-extract.py
if errorlevel 1 echo WARNING: Stage 01 exited with errors.

echo.
echo [STAGE 02] Deduplicate...
echo --------------------------------------------
python 02-dedup.py
if errorlevel 1 echo WARNING: Stage 02 exited with errors.

echo.
echo [STAGE 03] Quick filter...
echo --------------------------------------------
python 03-quick_filter.py
if errorlevel 1 echo WARNING: Stage 03 exited with errors.

echo.
echo [STAGE 04] Enrich (fetch full job descriptions)...
echo --------------------------------------------
python 04-enrich.py
if errorlevel 1 echo WARNING: Stage 04 exited with errors.

echo.
echo [STAGE 05] LLM filter (language + rename)...
echo --------------------------------------------
python -u 05-LLM_filter.py
if errorlevel 1 echo WARNING: Stage 05 exited with errors.

echo.
echo [STAGE 06] LLM scoring...
echo --------------------------------------------
python -u 06-score.py
if errorlevel 1 echo WARNING: Stage 06 exited with errors.

echo.
echo [STAGE 07] Launching Job Finding Command Center...
echo --------------------------------------------
start "Job Finding Command Center" python -u 07-review.py

echo.
echo ============================================================
echo  ALL STAGES COMPLETE - %DATE%  %TIME%
echo  Command Center is opening at http://localhost:5000
echo.
echo  Press ANY KEY to cancel hibernation and close this window.
echo  The 07 server (separate window) will keep running.
echo ============================================================

echo.
powershell -NoProfile -Command "for ($i=300; $i -gt 0; $i--) { Write-Host -NoNewline ([char]13 + ('Hibernating in {0,4}s (any key cancels and closes)...' -f $i)); if ([Console]::KeyAvailable) { [Console]::ReadKey($true) | Out-Null; exit 1 }; Start-Sleep 1 }; exit 0"
if errorlevel 1 exit /b

echo.
echo.
echo Hibernating now.
shutdown /h
exit /b
