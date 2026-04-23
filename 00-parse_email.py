#!/usr/bin/env python3
"""
Stage 00 — Email job URL extraction.
Reads .eml files from 00-emails/, finds all LinkedIn job URLs,
writes one .url shortcut file per unique job ID to 01-extracted/,
then deletes the processed .eml files.

Filenames are placeholder-only: YYYYMMDD_Job_XXXXXXXXXX - Email - LinkedIn.url
Stage 04 renames them properly using the live page title and company.

No extra dependencies — stdlib only.
"""

import email
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(write_through=True)

EMAIL_DIR  = Path(__file__).parent / '00-emails'
OUTPUT_DIR = Path(__file__).parent / '01-extracted'
TODAY      = date.today().strftime('%Y%m%d')

JOB_ID_RE = re.compile(r'linkedin\.com(?:/comm)?/jobs/view/(\d+)')


def get_html_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                raw     = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                return raw.decode(charset, errors='replace')
    elif msg.get_content_type() == 'text/html':
        raw     = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or 'utf-8'
        return raw.decode(charset, errors='replace')
    return ''


def process_eml(eml_path: Path) -> int:
    html = get_html_body(email.message_from_bytes(eml_path.read_bytes()))
    if not html:
        print('  WARNING: no HTML body found — skipping.')
        return 0

    # Collect unique job IDs in order of first appearance
    seen: set[str] = set()
    job_ids: list[str] = []
    for m in JOB_ID_RE.finditer(html):
        jid = m.group(1)
        if jid not in seen:
            seen.add(jid)
            job_ids.append(jid)

    count = 0
    for jid in job_ids:
        url      = f'https://www.linkedin.com/jobs/view/{jid}/'
        stem     = f'{TODAY}_Job_{jid} - Email - LinkedIn'
        out_path = OUTPUT_DIR / f'{stem}.url'
        out_path.write_text(f'[InternetShortcut]\nURL={url}\n', encoding='utf-8')
        print(f'  → {out_path.name}')
        count += 1

    return count


def main():
    EMAIL_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    eml_files = sorted(EMAIL_DIR.glob('*.eml'))
    if not eml_files:
        print('00-emails\\ has no .eml files — nothing to do.')
        return

    print(f'Found {len(eml_files)} .eml file(s) in 00-emails\\')
    total = 0

    for eml_path in eml_files:
        print(f'\n[{eml_path.name}]')
        count = process_eml(eml_path)
        print(f'  Extracted {count} URL(s).')
        eml_path.unlink()
        print(f'  Deleted.')
        total += count

    print(f'\nDone. {total} URL file(s) written to 01-extracted\\')


if __name__ == '__main__':
    main()
