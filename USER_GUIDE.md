# LinkedIn Sourcing — User Guide

User-facing operational manual. For pipeline internals (stages, Ollama flags, Excel schema, file naming), see `README.txt`.

---

## First-time setup

1. **Python packages**
   ```
   pip install playwright html2text requests openpyxl flask
   ```

2. **Chrome for Playwright** (one-time)
   ```
   playwright install chrome
   ```

3. **LinkedIn login** — first run of stage 01 (or `___RUN_ALL.bat`) will open Chrome. Log in once; the session is saved in `.chrome_profile/` and reused forever.

4. **Ollama host** — the Legion machine (192.168.68.52) must be on with `gemma4:26b` loaded for stages 05 and 06. Connection details: see `README.txt` → `OLLAMA CONNECTION`.

---

## Daily workflow

**The happy path:**

1. (Optional) Drop `.eml` files into `00-emails/` — see "How to get .eml files" below.
2. (Optional) Edit `00-links.txt` to add/remove LinkedIn search URLs.
3. Double-click `___RUN_ALL.bat`. It runs stages 00 → 06 unattended, opens the Command Center (stage 07) in your browser, then starts a 300-second countdown.
4. Come back when ready. Press any key in the RUN_ALL window within 300 seconds to cancel hibernation and close that window — the 07 server window stays running.
5. Review listings in the browser. Drag cards between columns, reject with a preset reason, edit scores, add notes.

**Running a single stage:** double-click any `NN-*.bat` file. Each stage reads from its input folder and writes to its output folder independently.

---

## How to get .eml files from Gmail

1. Open the email in Gmail (browser, not mobile app).
2. Three-dot menu (top right of the message) → **Download message**.
3. Save the `.eml` file into `00-emails/`.

Stage 00 parses every `.eml` in that folder, extracts LinkedIn job IDs, and deletes the `.eml` when done.

---

## Adding non-LinkedIn URLs

You can drop `.url` shortcut files directly into `01-extracted/`. The pipeline picks them up at stage 02 onwards. Stage 04's Chrome scraper has generic fallbacks that usually work on Personio, Greenhouse, Lever, etc. Stage 05's LLM identifies the source and labels the filename accordingly.

If extraction fails for a given site, stage 04 saves `_debug_last_page.html` — inspect it to see what the page looked like.

---

## Tuning the scoring

All scoring rules live in `06-score_crit.txt`. It's plain natural-language text — edit any value and it takes effect on the **next run** of stage 06. No code changes needed.

The LLM identifies which criteria apply; Python calculates the final score from that itemised breakdown. Full architecture: `README.txt` → `SCORING ARCHITECTURE`.

**To re-score existing listings after changing criteria:** see "Rollback / reprocess" below.

---

## Git workflow (safety net for changes)

The project is a local git repo. Use it before any non-trivial change so you can revert cleanly.

**See what changed since the last commit:**
```
git status
git diff
```

**Commit a known-good state before experimenting:**
```
git add .
git commit -m "checkpoint before <what I'm about to try>"
```

**See commit history:**
```
git log --oneline
```

**Revert a single file to a previous commit:**
```
git checkout <commit-hash> -- path/to/file.py
```

**Revert everything to a previous commit** (destructive — loses uncommitted work):
```
git reset --hard <commit-hash>
```

**Diff between two commits:**
```
git diff <older-hash> <newer-hash>
```

Commit hashes come from `git log --oneline`. The first ~7 characters are enough.

---

## Hibernation / RUN_ALL behavior

`___RUN_ALL.bat` ends with a single 300-second countdown:
- **Any key pressed** → cancels hibernation AND closes the RUN_ALL window. The stage 07 server window keeps running.
- **Countdown reaches zero** → PC hibernates. Stage 07 server is killed.

---

## Rollback / reprocessing

**To re-run stage 04 on a single listing** (e.g. the description didn't extract properly):
1. Delete the `.md` in `04-enriched/` (or `03-quickfiltered/` if still there).
2. Move the matching `.url` back to `03-quickfiltered/`.
3. Re-run `04-enrich.bat`.

**To re-score listings after editing `06-score_crit.txt`:**
1. Move the triplet (`.md`, `.url`, `_SCORING.md`) from `06-LLM_scored/` back to `05-LLMfiltered/`.
2. Delete the corresponding row(s) from `06-listings_db.xlsx`.
3. Re-run `06-score.bat`. The ref_nr counter resumes from the last remaining Excel row.

**To recover a deleted listing:** check `07-rejects/`, `02-dedup_seen.txt` (you may need to remove the URL here to un-skip it), or git history of the Excel file.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Stage 01 opens Chrome but doesn't scroll | LinkedIn session expired → log in when prompted, press Enter in the console |
| Stage 04 saves `_debug_last_page.html` | Page layout changed or non-LinkedIn site not recognized → open the HTML, check the structure, tell Claude |
| Stage 05/06 hangs with no output | Legion not reachable, or `gemma4:26b` not loaded → check Ollama on Legion, re-pull model if needed |
| Stage 05/06 streams empty content | `think: false` flag missing or `format: json` present — see `README.txt` → `CRITICAL STREAMING FLAGS` |
| Excel file locked / open | Close it in Excel before running stage 06 or stage 07 actions |
| Card shows wrong score | Edit Score in the side panel → edit raw JSON → Save. Filename and Excel update automatically |
| Ref_nr jumped / gaps | Expected after rollback; ref_nr is assigned sequentially on first insert and doesn't reuse slots |

---

## Where to find things

- Final scored listings: `06-LLM_scored/`
- Kanban board cards: `06-LLM_scored/` (New), `08-consider/`, `09-priorities/`, `10-in_process/`, `11-applied/`
- Rejected cards: `07-rejects/`
- Cumulative database: `06-listings_db.xlsx`
- Master deduplication list: `02-dedup_seen.txt`
- Debug dump when stage 04 fails: `_debug_last_page.html`
