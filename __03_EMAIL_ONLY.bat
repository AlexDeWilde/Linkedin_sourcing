@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================================
echo  EMAIL EXTRACTION + FULL PIPELINE  (stages 00, 02-06)
echo  Skips stage 01 LinkedIn search scraping.
echo  %DATE%  %TIME%
echo ============================================================

echo.
echo [STAGE 00] Extract URLs from emails in 00-emails\...
echo --------------------------------------------
python -u 00-parse_email.py
if errorlevel 1 echo WARNING: Stage 00 exited with errors.

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
echo ============================================================
echo  DONE - %DATE%  %TIME%
echo  Run 07-review.bat to open the Command Center.
echo ============================================================
