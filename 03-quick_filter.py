#!/usr/bin/env python3
"""
Quick filter stage.
Reads keywords from 03-exclusions.txt (one per line, # = comment).
For each .url file in 02-deduplicated/:
  - Keyword found in filename → delete
  - No match               → move to 03-quickfiltered/
Matching is case-insensitive.
"""

import shutil
import sys
from pathlib import Path

INPUT_DIR      = Path(__file__).parent / "02-deduplicated"
OUTPUT_DIR     = Path(__file__).parent / "03-quickfiltered"
EXCLUSIONS_FILE = Path(__file__).parent / "03-exclusions.txt"


def load_keywords() -> list[str]:
    if not EXCLUSIONS_FILE.exists():
        print(f"WARNING: 03-exclusions.txt not found — no keywords loaded, all files will pass.")
        return []
    return [
        line.strip().lower()
        for line in EXCLUSIONS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def main():
    force = "--force" in sys.argv

    OUTPUT_DIR.mkdir(exist_ok=True)

    keywords = load_keywords()
    if force:
        print(f"Force mode — keyword filter bypassed ({len(keywords)} keyword(s) ignored).")
    else:
        print(f"Loaded {len(keywords)} exclusion keyword(s).")

    files = sorted(INPUT_DIR.glob("*.url"))
    if not files:
        print("02-deduplicated/ is empty — nothing to do.")
        return

    moved = deleted = 0

    for url_file in files:
        if force:
            shutil.move(str(url_file), OUTPUT_DIR / url_file.name)
            print(f"  FORCE  {url_file.name}")
            moved += 1
        else:
            name_lower = url_file.name.lower()
            matched = next((kw for kw in keywords if kw in name_lower), None)
            if matched:
                url_file.unlink()
                print(f"  DEL  [{matched}]  {url_file.name}")
                deleted += 1
            else:
                shutil.move(str(url_file), OUTPUT_DIR / url_file.name)
                print(f"  OK   {url_file.name}")
                moved += 1

    print(f"\nDone — {moved} kept, {deleted} deleted")


if __name__ == "__main__":
    main()
