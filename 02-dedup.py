#!/usr/bin/env python3
"""
Deduplication routine.
Reads .url files from 01-extracted/, checks each URL against 02-dedup_seen.txt.
  - Already in 02-dedup_seen.txt  → delete the .url file
  - Not in 02-dedup_seen.txt      → append URL to 02-dedup_seen.txt, move file to 02-deduplicated/
"""

import shutil
import sys
from pathlib import Path

INPUT_DIR  = Path(__file__).parent / "01-extracted"
OUTPUT_DIR = Path(__file__).parent / "02-deduplicated"
DEDUP_FILE = Path(__file__).parent / "02-dedup_seen.txt"


def parse_url(url_file: Path) -> str | None:
    for line in url_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("URL="):
            return line[4:].strip()
    return None


def safe_dest(folder: Path, filename: str) -> Path:
    dest = folder / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 0
    while True:
        dest = folder / f"{stem} ({counter:02d}){suffix}"
        if not dest.exists():
            return dest
        counter += 1


def main():
    force = "--force" in sys.argv

    OUTPUT_DIR.mkdir(exist_ok=True)
    DEDUP_FILE.touch(exist_ok=True)

    known_urls = set(
        line.strip()
        for line in DEDUP_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )

    files = sorted(INPUT_DIR.glob("*.url"))
    if not files:
        print("01-extracted/ is empty — nothing to do.")
        return

    moved = deleted = skipped = 0

    with DEDUP_FILE.open("a", encoding="utf-8", newline="\n") as dedup_out:
        for url_file in files:
            url = parse_url(url_file)
            if url is None:
                print(f"  SKIP (no URL found): {url_file.name}")
                skipped += 1
                continue

            if url in known_urls:
                if force:
                    dest = safe_dest(OUTPUT_DIR, url_file.name)
                    shutil.move(str(url_file), dest)
                    print(f"  FORCE (duplicate, passing through): {dest.name}")
                    moved += 1
                else:
                    url_file.unlink()
                    print(f"  DEL  (duplicate): {url_file.name}")
                    deleted += 1
            else:
                known_urls.add(url)
                dedup_out.write(url + "\n")
                dest = safe_dest(OUTPUT_DIR, url_file.name)
                shutil.move(str(url_file), dest)
                print(f"  OK   {dest.name}")
                moved += 1

    print(f"\nDone — {moved} moved, {deleted} deleted, {skipped} skipped")


if __name__ == "__main__":
    main()
