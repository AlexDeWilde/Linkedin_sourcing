@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================================
echo  PIPELINE - MANUALLY PLACED URLs (force mode, stages 02-06)
echo  Place .url files in 01-extracted\ before running.
echo  Bypasses dedup exclusion, keyword filter, language filter.
echo  Reuses existing ref_nr if URL already scored.
echo  %DATE%  %TIME%
echo ============================================================

echo.
echo [STAGE 02] Deduplicate (force -- duplicates pass through)...
echo --------------------------------------------
python 02-dedup.py --force
if errorlevel 1 echo WARNING: Stage 02 exited with errors.

echo.
echo [STAGE 03] Quick filter (force -- no keyword exclusions)...
echo --------------------------------------------
python 03-quick_filter.py --force
if errorlevel 1 echo WARNING: Stage 03 exited with errors.

echo.
echo [STAGE 04] Enrich (fetch full job descriptions)...
echo --------------------------------------------
python 04-enrich.py
if errorlevel 1 echo WARNING: Stage 04 exited with errors.

echo.
echo [STAGE 05] LLM filter (force -- no language rejection)...
echo --------------------------------------------
python -u 05-LLM_filter.py --force
if errorlevel 1 echo WARNING: Stage 05 exited with errors.

echo.
echo [STAGE 06] LLM scoring (force -- reuse existing ref_nr)...
echo --------------------------------------------
python -u 06-score.py --force
if errorlevel 1 echo WARNING: Stage 06 exited with errors.

echo.
echo ============================================================
echo  DONE - %DATE%  %TIME%
echo  Run 07-review.bat to open the Command Center.
echo ============================================================
