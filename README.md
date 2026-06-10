LINKEDIN SOURCING PIPELINE
==========================

DOCUMENTATION GUIDELINES
------------------------
This README is the agent technical reference for the pipeline. User-facing
operational content (setup steps, git workflow, troubleshooting, rollback
procedures, daily workflow) lives in USER_GUIDE.md — do NOT duplicate it here;
add a "see USER_GUIDE.md" pointer instead.

Claude must update this file at the end of every chat session that changes any
of the following:
  - A stage script (what it does, inputs, outputs, key flags)
  - A folder added, renamed, or removed
  - The Excel database schema (columns added or changed)
  - A config file's purpose or format
  - __01_RUN_ALL.bat behaviour (stages covered, post-run actions)
  - Ollama model, host, or streaming configuration

What to update and where:
  STAGES section         One subsection per stage. Keep "what it does", inputs,
                         outputs, key flags, and any non-obvious gotchas current.
                         Mark completed stages as "(complete)".
  EXCEL DATABASE         Reflect every column A through the last one. Include
                         which stage adds each column and what values it holds.
  FOLDER / FILE STRUCTURE  Every script, config file, and folder that exists.
                         One line per entry. Mark new items when added.
  OLLAMA CONNECTION      Update model name, host/IP, or flags if they change.

What NOT to put in README:
  - In-progress debugging or one-off fixes (those belong in git commits)
  - Ephemeral task notes ("next session: do X") — use Claude memory for those
  - Duplicate information that is already in the script itself

Claude memory file (project_linkedin_sourcing.md) holds a compact summary for
quick orientation — update it at the same time as README when stage status,
folder structure, or Excel schema changes.


COMMIT APPROVAL WORKFLOW
------------------------
The project is a local git repo. Claude authors commits on the user's behalf
but MUST ask for confirmation before each commit. Pause after meaningful
changes and propose a commit message; wait for explicit yes before running
`git commit`. Recommend commits at natural checkpoints: feature tested, before
a risky change, after documentation updates, when the user says "it works".
Other git rules (no destructive ops, message style) live in CLAUDE.md.


OVERVIEW
--------
Sequential pipeline that harvests LinkedIn job postings, deduplicates, filters,
enriches, and LLM-processes them into a scored database for review.
Each stage reads from its input folder and writes to its output folder.
Run __01_RUN_ALL.bat to execute all stages unattended end-to-end.
Run individual .bat files to execute a single stage.

DEPENDENCIES
------------
Python packages : playwright, html2text, requests, openpyxl, flask
Playwright      : chrome channel
Install steps and first-time setup: see USER_GUIDE.md.

OLLAMA CONNECTION  (stages 05 and 06)
--------------------------------------
  Host        : localhost (each machine runs its own Ollama)
  Port        : 11434
  API URL     : http://127.0.0.1:11434/api/chat
  Model       : configured per-stage in _model_config_{HOSTNAME}.txt (see below)
  num_ctx     : configured per-model in the same file (default 32768)
  num_predict : 8192    (stage 05) / 2048 (stage 06 — JSON output is short)

  MODEL CONFIG  (_model_config_{HOSTNAME}.txt)
  ----------------------------------------------
  Scripts detect the machine hostname at startup and load the matching config:
    _model_config_LEGION.txt  → used on LEGION
    _model_config_VIVO.txt    → used on VIVO
    _model_config.txt         → fallback if no hostname-specific file exists
  Format:  model_name  -  stage_numbers (comma-separated)  -  num_ctx (optional)
           default     -  fallback_model_name               -  num_ctx (optional)
  Empty stage field means that model is not used by any stage.
  If num_ctx is omitted, scripts use 32768.
  Edit the file directly to change models or context windows; no code changes needed.
  If a stage has no explicit assignment and no default line, it aborts.

  CRITICAL STREAMING FLAGS (apply to both stages 05 and 06)
  ----------------------------------------------------------
  Thinking-mode models (e.g. gemma4:26b) put ALL generated tokens into a
  "thinking" field by default — the "content" field stays empty until done,
  making the response appear to hang and returning an empty string.

  Three flags are required together for live streaming to work with such models:

    1. "think": false          Top-level payload key. Disables thinking mode.
                               Without this, content is always empty.

    2. "format": "json"        MUST BE OMITTED. When present, Ollama buffers
                               the entire response to validate JSON before
                               sending any tokens — streaming is silently
                               disabled even with stream:true.

    3. "stream": true          Standard streaming flag.

  Because format:json is omitted, JSON is extracted from free text using:
      re.search(r'\{.*\}', response, re.DOTALL)
  The model may wrap its output in markdown fences (```json ... ```) — the
  regex handles this correctly.

  Python-side unbuffering (both scripts):
    - python -u flag in .bat launchers
    - sys.stdout.reconfigure(write_through=True) at script start
    - chcp 65001 > nul in all .bat files (UTF-8 console encoding)

  Chunk structure with think:false:
    {"model":"...","message":{"role":"assistant","content":"..."},"done":false}
  Chunk structure WITHOUT think:false (broken for thinking-mode models):
    {"model":"...","message":{"role":"assistant","content":"","thinking":"..."},"done":false}


SCORING ARCHITECTURE (stage 06)
---------------------------------
  06-score_crit.txt is the single source of truth for all scoring rules.
  It is written in natural language for the user to read and edit.
  Edit any value and it takes effect on the next run — no code changes needed.

  The LLM's role is to IDENTIFY what applies (additions, deductions, flags).
  Python CALCULATES the final score from the itemised breakdown.
  The LLM is explicitly instructed NOT to calculate or return a total score —
  asking it to do so caused it to reverse-engineer component points to make
  its arithmetic look right, distorting criterion identification.

  Scoring rules summary:
    - Start at 100
    - Apply additions (industry bonus: +10, applied ONCE regardless of matches)
    - Apply deductions (all forced negative by Python regardless of LLM sign)
    - Floor at 0, no ceiling (scores above 100 are valid)
    - Auto-rejection thresholds (Python applies after scoring, before saving to CC):
        Role disqualifier  : LLM flags "Role disqualifier:" → 07-rejects/ with Excel row
                             (ref_nr assigned, status=rejected, reject_reason=Role)
        Score < 30         : → 07-rejects/ with Excel row (same columns written)
        Location disqualifier: LLM flags "Location disqualifier:" → 06-disqualified/
                             (no ref_nr, no Excel row — never visible anywhere)

  LLM output fields (JSON) — no fit_score, Python owns that:
    city_code, date_published, job_title, company_name,
    client_company, source, additions[], deductions[], disqualifiers[], notes

  company_name = recruiter/agency name if posted via one; direct company otherwise
  client_company = actual hiring company if posted via recruiter and known; else ""
  client_company populates the [tag] field in the filename and Excel tag column


FILE NAMING CONVENTIONS
-----------------------
Stage 00 output (placeholder, renamed by stage 04):
    YYYYMMDD_Job_XXXXXXXXXX - Email - LinkedIn.url

Stage 01 output:
    YYYYMMDD_[Title] - [Company] - LinkedIn.url
    Date = extraction date. Duplicates get a (00), (01)... suffix.

Stage 04 renames email-sourced files (those containing '- Email -') using the
    live page title and company, producing the same format as stage 01 output.

Stage 05 output:
    YYYYMMDD_CITY_Title_-_Company_-_LinkedIn.url / .md
    Date     = estimated publication date (from "X days ago" etc.)
    CITY     = first 4 letters of city name, no spaces, no accents, uppercase.
               Fully remote: RMTE.

Stage 06 output (3 files per listing):
    [ref_nr]_[score]_[YYYYMMDD]_[city]_[title]_[company]_[source].md
    [ref_nr]_[score]_[YYYYMMDD]_[city]_[title]_[company]_[source].url
    [ref_nr]_[score]_[YYYYMMDD]_[city]_[title]_[company]_[source]_SCORING.md

    ref_nr   = 4-digit zero-padded sequential number (e.g. 0277)
    score    = 3-digit zero-padded fit score (e.g. 082)
    city     = up to 7 letters of city name, no spaces, no accents, uppercase.
               Remote roles: REMOTE. Examples: MUNICH, AMSTERD, BARCELO, SAOPAU.
    tag      = optional client company name (recruiter listings only), appended
               after double-underscore: ..._LinkedIn__Desconecta.md
               Omitted entirely (including __) when not applicable.


EXCEL DATABASE  (06-listings_db.xlsx)
--------------------------------------
  One row per listing. Columns A through S:

  Original columns (A–M):
    A: ref_nr          4-digit zero-padded text (e.g. "0277")
    B: fit_score       3-digit zero-padded text (e.g. "082")
    C: date_published  DD/MM/YYYY
    D: city            city code as in filename (up to 7 chars)
    E: tag             client company name for recruiter listings; blank otherwise
    F: job_title
    G: company_name    recruiter name if via agency; direct company otherwise
    H: source          e.g. LinkedIn
    I: date_found      DD/MM/YYYY (date script ran)
    J: status          new / in_consideration / priorities / in_process / applied / rejected
    K: report_produced Yes / No
    L: processed       notes or blank
    M: url

  Stage 07 tracking columns (N–T) — added by setup_excel_columns() at first launch:
    N: date_considered  DD/MM/YYYY — stamped when card moved to In Consideration
    O: date_priorities  DD/MM/YYYY — stamped when card moved to Priorities
    P: date_in_process  DD/MM/YYYY — stamped when card moved to In Process
    Q: date_applied     DD/MM/YYYY — stamped when card moved to Applied
    R: date_rejected    DD/MM/YYYY — stamped when card rejected
    S: comment          free-text comment saved from the review console
    T: reject_reason    reason chosen when rejecting. Preset buttons write one of:
                        Location / Seniority / Stack / Company / Pay / Role /
                        Expired / Language(s).

  ref_nr and fit_score are stored as text with @ format to preserve zero-padding.
  setup_excel_columns() runs at 07-review.py startup and adds missing N–T columns
  automatically — safe to run against an existing file with no header row.
  Past rows (before stage 06 was built) may have different status values — leave as-is.


FOLDER / FILE STRUCTURE
-----------------------
  __01_RUN_ALL.bat         Full pipeline (stages 00–07) + 300s hibernate countdown.
                           Keypress cancels hibernation and closes this window;
                           the 07 server (separate window) keeps running.
  __02_RUN_ALL_NOHIB.bat  Full pipeline (stages 00–07), no hibernation.
  __03_EMAIL_ONLY.bat     Email + pipeline (stages 00, 02–06), no hibernate.
                           Skips stage 01 LinkedIn search scraping.
  __04_EXTRACTED.bat      Force-mode pipeline (stages 02–06) for manually placed URLs.
                           Bypasses dedup exclusion, keyword filter, language filter.
  00-emails/               Drop .eml files here before running stage 00 or RUN_ALL
  00-parse_email.py/.bat   Stage 00: email-only extraction to 01-extracted/
  00-links.txt             LinkedIn search URLs fed to stage 01 (# = comment)
  01-extract.py/.bat       Stage 01
  01-extracted/            Stage 01 output staging area
  02-dedup.py/.bat         Stage 02
  02-dedup_seen.txt        Cumulative master list of all seen job URLs (never delete)
  02-deduplicated/         Stage 02 output staging area
  03-quick_filter.py/.bat  Stage 03
  03-exclusions.txt        Filename keywords for quick-filter exclusion (# = comment)
  03-quickfiltered/        Stage 03 output staging area
  04-enrich.py/.bat        Stage 04
  04-enriched/             Stage 04 output — paired .url + .md files
  05-LLM_filter.py/.bat    Stage 05
  05-LLMfiltered/          Stage 05 output — renamed paired .url + .md files
  05-LLMfiltered/
    lang_rejects/          Stage 05 JD-language rejects (original filenames, untouched)
    lang_req_rejects/      Stage 05 language-requirement rejects (original filenames)
    closed/                Listings with "no longer accepting applications" in the JD;
                           moved here by stage 05 (or stage 06 as a backstop), untouched
  06-score.py/.bat         Stage 06
  06-score_crit.txt        Scoring criteria — edit to tune scores, no code change needed
  06-listings_db.xlsx      Scored job database (all listings, cumulative)
  06-LLM_scored/           Stage 06 output — scored triplets (.md + .url + _SCORING.md)
  06-disqualified/         Stage 06 location-excluded listings (no ref_nr, no Excel row)
  07-review.py             Stage 07 — Flask backend for the review console
  07-review.html           Stage 07 — single-page kanban app (served by Flask)
  07-review.bat            Stage 07 — launcher (starts Flask, opens browser)
  07-rejects/              Cards rejected from the review console
  08-consider/             Cards moved to "In Consideration"
  09-priorities/           Cards moved to "Priorities"
  10-in_process/           Cards moved to "In Process"
  11-applied/              Cards moved to "Applied"
  .chrome_profile/         Persistent Chrome session (log in once, reused every run)
  _model_config.txt        Fallback model config (used if no hostname-specific file)
  _model_config_LEGION.txt Model config for LEGION (larger models, more VRAM)
  _model_config_VIVO.txt   Model config for VIVO (smaller models, less VRAM)
  _debug_last_page.html    Stage 04 debug dump when description extraction fails


STAGES
------

00 — EMAIL URL EXTRACTION  (optional, runs before stage 01)
  Script : 00-parse_email.py / 00-parse_email.bat
  Input  : 00-emails/  (.eml files downloaded from Gmail)
  Output : 01-extracted/  (.url shortcut files)
  What   : Parses each .eml file (stdlib only, no extra packages).
           Extracts the HTML body, finds all LinkedIn job IDs via regex
           (handles both linkedin.com/jobs/view/ and linkedin.com/comm/jobs/view/).
           Normalises tracking URLs to canonical linkedin.com/jobs/view/XXXXXXXXX/.
           Writes one .url file per unique job ID. Does NOT visit any URLs.
           Deletes processed .eml files on completion.
  Filename format: YYYYMMDD_Job_XXXXXXXXXX - Email - LinkedIn.url  (placeholder)
           Stage 04 renames these using the live page title and company.
  How to get .eml: see USER_GUIDE.md.
  Duplicates: stage 02 dedup catches any URL already seen from search results.
  Bat options:
    00-parse_email.bat       extraction only (manual pipeline run after)
    __03_EMAIL_ONLY.bat      extraction + stages 02-06 (skips LinkedIn search)
    __01_RUN_ALL.bat         runs stage 00 then all stages including 07

00 — SEARCH LINKS  (config file, not a script)
  File   : 00-links.txt
  What   : One LinkedIn job search URL per line. Lines starting with # are ignored.
           Edit this file to control which searches stage 01 harvests.

01 — EXTRACT
  Script : 01-extract.py / 01-extract.bat
  Input  : 00-links.txt
  Output : 01-extracted/  (.url shortcut files)
  What   : Opens Chrome with the saved profile, scrolls each search result page,
           harvests job card URLs incrementally (LinkedIn virtualises the DOM).
           Dismisses harvested cards after each search so they don't reappear.
           Stops at the "Are these results helpful" sentinel.
           Chrome window stays open after completion.
  Notes  : Close all Chrome windows before running.
           First run only: if LinkedIn session has expired, a login prompt
           appears — log in and press ENTER to continue. Session is then saved
           in .chrome_profile/ and reused automatically on all subsequent runs.

02 — DEDUP
  Script : 02-dedup.py / 02-dedup.bat
  Input  : 01-extracted/
  Output : 02-deduplicated/ (new URLs only), 01-extracted/ emptied,
           02-dedup_seen.txt updated with newly seen URLs
  What   : Reads the URL from each .url file, checks against 02-dedup_seen.txt.
           Duplicate -> file deleted.
           New       -> URL appended to 02-dedup_seen.txt, file moved to 02-deduplicated/.

03 — QUICK FILTER
  Script : 03-quick_filter.py / 03-quick_filter.bat
  Input  : 02-deduplicated/
  Output : 03-quickfiltered/ (passing files), matched files deleted
  What   : Reads keywords from 03-exclusions.txt (case-insensitive, # = comment).
           If any keyword appears in the filename -> delete.
           Otherwise -> move to 03-quickfiltered/.

04 — ENRICH
  Script : 04-enrich.py / 04-enrich.bat
  Input  : 03-quickfiltered/
  Output : 04-enriched/  (paired .url + .md files)
  What   : Opens each job URL in Chrome (saved profile, logged in).
           Email-sourced files (containing '- Email -' in name) are renamed
           here using the live page title and company, matching stage 01 format.
           Clicks the "more" expander to reveal the full job description.
           Extracts title, company, and full description as a clean .md file.
           Strips: nav preamble, "Use AI to assess how you fit",
                   "People you can reach out to",
                   everything after "Set alert for similar jobs".
           Moves both .url and .md to 04-enriched/.
           Chrome window stays open after completion.
  Notes  : To reprocess a file: delete its .md and move the .url back to
           03-quickfiltered/.
           Description not found -> saves _debug_last_page.html for diagnosis.

05 — LLM FILTER
  Script : 05-LLM_filter.py / 05-LLM_filter.bat
  Input  : 04-enriched/  (.url + .md pairs)
  Output : 05-LLMfiltered/  (renamed .url + .md pairs)
           05-LLMfiltered/lang_rejects/      (non-EN/PT/ES JD language, original names)
           05-LLMfiltered/lang_req_rejects/  (disqualifying language requirements)
  Model  : per _model_config.txt  (see OLLAMA CONNECTION above)
  What   : One Ollama call per file. Streams response live to console.
           Detects the language of the job description.
           Rejects non-English / non-Portuguese / non-Spanish -> lang_rejects/.
           Closed listings (description contains "no longer accepting applications")
           are moved to 05-LLMfiltered/closed/ with original filenames, no Ollama call.
           For accepted files: estimates publication date, extracts city/title/company,
           renames both files using the stage 05 naming convention, moves to
           05-LLMfiltered/. Retries up to 2x on empty/unparseable response.
           Language requirement filter (runs after language detection):
             LLM extracts required language proficiencies from the JD text.
             Disqualifying requirements -> lang_req_rejects/ (never reach stage 06):
               French or Dutch required at B2 or above (advanced/fluent/native)
               Any other language (not EN/PT/ES/DE) required at B1 or above
             Optional/preferred language requirements are ignored.
             German at any level is never excluded here (stage 06 applies deductions).
             The prompt asks for language names in English; the filter also
             recognizes common localized forms (e.g. "espanhol", "alemão") so a
             PT/ES-language JD cannot smuggle an exempt language past the check.
  --force: bypasses language detection filter, closed-listing check, and language
           requirement filter.
  Notes  : Fully unattended. Requires Ollama on Legion with the configured model loaded.
           See CRITICAL STREAMING FLAGS above.

06 — LLM SCORING
  Script : 06-score.py / 06-score.bat
  Input  : 05-LLMfiltered/  (.url + .md pairs)
  Output : 06-LLM_scored/   (.url + .md + _SCORING.md per listing)
           06-listings_db.xlsx  (one row appended per listing)
           06-disqualified/     (location-excluded listings — no Excel row, never shown)
           07-rejects/          (auto-rejected listings with score < 30)
  Criteria: 06-score_crit.txt  (edit freely — live reload on every run)
  Model  : per _model_config.txt  (see OLLAMA CONNECTION and SCORING ARCHITECTURE)
  What   : Fully unattended. One Ollama call per listing.
           Streams scoring JSON live to console.
           Python recalculates final score from itemised breakdown (LLM math ignored).
           Appends row to Excel, renames files, moves triplet to 06-LLM_scored/.
           Retries up to 3x on empty/unparseable response, skips on persistent error.
           Closed listings (description contains "no longer accepting applications")
           are moved to 05-LLMfiltered/closed/ and skipped — backstop for items
           stage 05 didn't catch.
           Location disqualifier: if the LLM flags a "Location disqualifier:" entry,
           the listing is moved to 06-disqualified/ with no ref_nr and no Excel row.
           Covers: any city not in the acceptable locations list, Rio de Janeiro state
           outside 20km, and other Brazilian locations outside accepted areas.
           Role disqualifier: if the LLM flags a "Role disqualifier:" entry (job title
           matches no accepted tier in Criterion 1), the listing is assigned a ref_nr,
           appended to Excel (status=rejected, reject_reason=Role), and moved to
           07-rejects/. It never appears in the Command Center.
           Score auto-rejection: if fit_score < 30, same behaviour as role disqualifier
           — ref_nr assigned, Excel row written, moved to 07-rejects/.
  Output files per listing (normal path):
           [ref_nr]_[score]_[date]_[city]_[title]_[company]_[source].md
           [ref_nr]_[score]_[date]_[city]_[title]_[company]_[source].url
           [ref_nr]_[score]_[date]_[city]_[title]_[company]_[source]_SCORING.md
           _SCORING.md contains: summary table, additions, deductions, disqualifier
           flags, notes, and full raw JSON — used as input for stage 07.
  Rollback procedure (to reprocess listings): see USER_GUIDE.md.
  Notes  : Requires Ollama on Legion with the configured model loaded.
           See CRITICAL STREAMING FLAGS above.

07 — JOB FINDING COMMAND CENTER  (complete)
  Scripts: 07-review.py (Flask backend), 07-review.html (single-page app)
  Launcher: 07-review.bat  → starts server at localhost:5000, opens browser
  Input  : 06-LLM_scored/  (and 08-consider/, 09-priorities/, 10-in_process/)
  Output : cards physically moved between folders on disk; Excel updated in real-time

  Kanban board — 4 visible columns (left to right):
    New              ← 06-LLM_scored/   status: new
    In Consideration ← 08-consider/     status: in_consideration
    Priorities       ← 09-priorities/   status: priorities
    In Process       ← 10-in_process/   status: in_process
  Hidden folders (not visible in UI):
    07-rejects/      Rejected cards (status: rejected)
    11-applied/      Applied cards (status: applied)

  Card actions:
    Drag-and-drop    Move card between any visible column
    Reject buttons   One preset button per reason — Location / Seniority / Stack /
                     Company / Pay / Role / Expired / Language(s).
                     Expired = job was de-listed from LinkedIn.
                     Moves triplet to 07-rejects/, stamps column R (date_rejected)
                     and column T (reject_reason), auto-advances to next card.
                     Bar hidden when the selected card is already in Applied.
    Edit Score       Opens raw JSON from _SCORING.md in a modal editor;
                     on save: recalculates score, renames all 3+ files if score
                     changed, rewrites _SCORING.md, updates Excel fit_score column
    Prev / Next      Navigate cards within the current column
    Sort (all cols)  Dropdown lives in the New column header but re-sorts ALL four
                     visible columns by the same criterion: score high-low,
                     score low-high, date new-old, date old-new, company A-Z.
                     In-place re-render, no server call.

  Card layout:
    Meta line        CITY · DATE · REF_NR (ref_nr is the 4-digit prefix — lets you
                     locate the file on disk by name).

  Side panel (opens on card click, 711px wide):
    Header           Score badge, job title, company, city · date · ref_nr,
                     LINKEDIN ↗ link (opens job page in new tab)
    Scoring tab      Rendered _SCORING.md (markdown)
    Job Description  Rendered .md (full JD)
    Notes tab        Personal notes textarea + Save Notes button;
                     saved as [stem]_comment.md and synced to Excel column S

  Topbar buttons:
    Check LinkedIn   Launches a headless Chrome session (using .chrome_profile/) and
                     visits each active card's LinkedIn URL to detect "no longer
                     accepting applications". Shows live progress (X/Y). When done,
                     prompts to move all expired cards to 07-rejects/ with reason
                     "Expired". Requires Chrome windows to be closed first.
    30-day Expiry    Immediately rejects all active cards whose date_published is more
                     than 30 days before today. Writes reason "Expired" to Excel.
                     No confirmation — cards move to 07-rejects/, not deleted.
    Sync DB          One-shot batch: scans all 6 folders, updates Excel status +
                     stage dates + comments for every listing found. Shows count.
                     Also runs automatically at server startup as a safety net —
                     manual button remains available for on-demand use.
    Refresh          Reloads all listings from disk without losing panel state.

  Excel integration:
    Every move       Writes status + stage date (date_X column) to Excel
    Every comment    Writes comment text to Excel column S
    Sync DB          Updates all rows from disk state (idempotent, safe to re-run)
    setup_excel_columns() runs at startup — adds missing N–S columns automatically

  To stop: Ctrl+C in the console, or close the console window.
  To restart: run 07-review.bat again.
