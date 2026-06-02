#!/usr/bin/env python3
"""
Enrichment stage — one file at a time.
Takes the first .url from 03-quickfiltered/, opens it in Chrome (logged-in profile),
extracts the job description, saves a .md alongside it, then moves both to 04-enriched/.

To re-test: delete the .md and move the .url back to 03-quickfiltered/.
"""

import re
import shutil
import sys
import unicodedata
import html2text
from datetime import date
from pathlib import Path
from playwright.sync_api import sync_playwright

# encoding="utf-8" prevents UnicodeEncodeError on cp1252 consoles when scraped
# titles/companies/URLs contain non-Latin1 characters (e.g. São, Ønskeskyen).
sys.stdout.reconfigure(encoding="utf-8")

INPUT_DIR      = Path(__file__).parent / "03-quickfiltered"
OUTPUT_DIR     = Path(__file__).parent / "04-enriched"
CHROME_PROFILE = Path(__file__).parent / ".chrome_profile"
DEBUG_HTML     = Path(__file__).parent / "_debug_last_page.html"

TODAY = date.today().strftime('%Y%m%d')

_INVALID = re.compile(r'[<>:"/\\|?*]')


def _clean(text: str) -> str:
    """Strip accents and filename-invalid characters."""
    nfd = unicodedata.normalize('NFD', text)
    s   = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    return _INVALID.sub('', s).strip()


def email_stem(title: str, company: str) -> str:
    """Build a stage-01-style stem from live-page title and company."""
    t = _clean(title)[:60].strip()
    c = _clean(company)[:40].strip()
    if t and c:
        return f'{TODAY}_{t} - {c} - LinkedIn'
    if t:
        return f'{TODAY}_{t} - LinkedIn'
    return ''

DESC_SELECTORS = [
    "#job-details",
    ".jobs-description__content",
    ".jobs-description-content__text",
    ".description__text",
    "[class*='description__text']",
    ".jobs-box__html-content",
    "article",
]


def parse_url(url_file: Path) -> str | None:
    for line in url_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("URL="):
            return line[4:].strip()
    return None


def parse_stem(url_file: Path) -> tuple[str, str]:
    """
    Extract (title, company) from a non-email filename.
    Format: YYYYMMDD_Title - Company - Source
    Returns ('', '') if the pattern doesn't match.
    """
    stem = url_file.stem
    # Strip date prefix YYYYMMDD_
    stem = re.sub(r'^\d{8}_', '', stem)
    # Split on ' - '; last part is source, second-to-last is company, rest is title
    parts = stem.split(' - ')
    if len(parts) < 3:
        return '', ''
    company = parts[-2].strip()
    title   = ' - '.join(parts[:-2]).strip()
    return title, company


def first_text(page, selectors: list[str]) -> str:
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                text = (loc.first.inner_text(timeout=3000) or "").strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


def find_title_js(page) -> str:
    """
    Find job title without relying on class names.
    Uses the company link (stable href pattern) as an anchor, walks up the DOM,
    and returns the first <p> with substantial text in the same card container.
    """
    return page.evaluate("""
        () => {
            const anchor = document.querySelector('a[href*="/company/"][href*="/life/"]');
            if (!anchor) return '';
            let el = anchor;
            for (let i = 0; i < 6; i++) {
                el = el.parentElement;
                if (!el) break;
                const p = el.querySelector('p');
                if (p && (p.innerText || '').trim().length > 10)
                    return p.innerText.trim();
            }
            return '';
        }
    """) or ""


def expand_description(page) -> None:
    # Click the "...more" expander in the job description if present
    selectors = [
        "button.jobs-description__footer-button",
        "[class*='see-more-button']",
        "button[aria-label*='more']",
        "footer button",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                print("  Clicked 'more' expander.")
                return
        except Exception:
            continue

    # JS fallback: find a button/span whose visible text is exactly "more"
    clicked = page.evaluate("""
        () => {
            for (const el of document.querySelectorAll('button, span, a')) {
                if ((el.innerText || '').trim().toLowerCase() === 'more') {
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """)
    if clicked:
        page.wait_for_timeout(1000)
        print("  Clicked 'more' expander (JS fallback).")
    else:
        print("  No 'more' expander found — content may already be full.")


def find_desc_html(page) -> str:
    # Try known selectors first
    for sel in DESC_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                html = (loc.first.inner_html(timeout=5000) or "").strip()
                if len(html) > 200:
                    print(f"  Found description via selector: {sel}")
                    return html
        except Exception:
            continue

    # Fallback: JS scan for the element with the most text
    print("  Known selectors failed — trying JS content scan...")
    result = page.evaluate("""
        () => {
            let best = null, bestLen = 0;
            for (const el of document.querySelectorAll('div, section, article')) {
                const text = (el.innerText || '').trim();
                if (text.length > bestLen && text.length < 20000 && el.children.length < 30) {
                    bestLen = text.length;
                    best = el;
                }
            }
            if (best && bestLen > 200) {
                return { html: best.innerHTML, tag: best.tagName, cls: best.className, len: bestLen };
            }
            return null;
        }
    """)
    if result:
        print(f"  JS fallback found: <{result['tag']} class='{result['cls'][:60]}'> ({result['len']} chars)")
        return result["html"]

    return ""


STRIP_HEADINGS = {
    "use ai to assess how you fit",
    "people you can reach out to",
}


def html_to_md(raw_html: str) -> str:
    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    h.body_width = 0
    md = h.handle(raw_html).strip()

    # Cut everything from "Set alert for similar jobs" onwards
    cutoff = md.find("Set alert for similar jobs")
    if cutoff != -1:
        md = md[:cutoff].strip()

    # Strip nav preamble: everything up to and including the first horizontal rule
    for sep in ["\n* * *\n", "\n---\n", "\n- - -\n"]:
        idx = md.find(sep)
        if idx != -1:
            md = md[idx + len(sep):].strip()
            break

    # Strip blacklisted sections and their content
    lines = md.splitlines()
    result = []
    skip = False
    skip_level = 0
    for line in lines:
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            level = len(m.group(1))
            heading_text = m.group(2).strip().lower()
            if heading_text in STRIP_HEADINGS:
                skip = True
                skip_level = level
                continue
            elif skip and level <= skip_level:
                skip = False
        if not skip:
            result.append(line)

    return "\n".join(result).strip()


def process_file(page, url_file: Path) -> None:
    url = parse_url(url_file)
    if not url:
        print(f"  SKIP — could not parse URL from: {url_file.name}")
        return

    print(f"\nFile : {url_file.name}")
    print(f"URL  : {url}")

    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(5_000)

    is_email = '- Email -' in url_file.stem

    title = first_text(page, [
        "h1.job-details-jobs-unified-top-card__job-title",
        "h1[class*='job-title']",
        "h1",
    ]) or find_title_js(page)

    company = first_text(page, [
        "a[href*='/company/'][href*='/life/']",          # structural — stable
        ".job-details-jobs-unified-top-card__company-name",
        "[class*='company-name']",
        ".jobs-unified-top-card__company-name",
    ])

    if not title and not is_email:
        fn_title, fn_company = parse_stem(url_file)
        if fn_title:
            title   = fn_title
            company = company or fn_company
            print(f"  Title  : {title} (from filename)")
            print(f"  Company: {company or '(not found)'} (from filename)")
        else:
            print(f"  Title  : (not found)")
            print(f"  Company: {company or '(not found)'}")
    else:
        print(f"  Title  : {title or '(not found)'}")
        print(f"  Company: {company or '(not found)'}")

    if not title:
        # Selectors are stale — dump page HTML so selectors can be updated
        print("  WARNING: title not found — saving debug HTML for selector diagnosis.")
        DEBUG_HTML.write_text(page.content(), encoding="utf-8", newline="\n")
        print(f"  Debug HTML saved: {DEBUG_HTML.name}")

    expand_description(page)
    desc_html = find_desc_html(page)

    if not desc_html:
        print("  WARNING: description not found.")
        if title:  # only dump if we haven't already
            DEBUG_HTML.write_text(page.content(), encoding="utf-8", newline="\n")
            print(f"  Debug HTML saved: {DEBUG_HTML.name}")

    desc_md = html_to_md(desc_html) if desc_html else "(description not found)"

    lines = [f"# {title or url_file.stem}", ""]
    if company:
        lines += [f"**Company:** {company}", ""]
    lines += [f"**URL:** {url}", "", "---", "", desc_md, ""]

    md_file = INPUT_DIR / url_file.with_suffix(".md").name
    md_file.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    # Email-sourced files carry a placeholder name (contains '- Email -').
    # Rename them here using the title and company extracted from the live page.
    if '- Email -' in url_file.stem and title:
        new_stem = email_stem(title, company)
    else:
        new_stem = url_file.stem

    out_url = OUTPUT_DIR / f'{new_stem}.url'
    out_md  = OUTPUT_DIR / f'{new_stem}.md'

    # Avoid collision (shouldn't happen after dedup, but be safe)
    counter = 1
    while out_url.exists() or out_md.exists():
        out_url = OUTPUT_DIR / f'{new_stem}_{counter:02d}.url'
        out_md  = OUTPUT_DIR / f'{new_stem}_{counter:02d}.md'
        counter += 1

    shutil.move(str(url_file), out_url)
    shutil.move(str(md_file),  out_md)
    if new_stem != url_file.stem:
        print(f"  Renamed → {out_url.name}")
    print(f"  Saved and moved to {OUTPUT_DIR.name}/")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    files = sorted(INPUT_DIR.glob("*.url"))
    if not files:
        print("03-quickfiltered/ is empty — nothing to do.")
        return

    print(f"Found {len(files)} file(s) to process.")

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(CHROME_PROFILE),
            channel="chrome",
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = context.new_page()

        for i, url_file in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}]")
            process_file(page, url_file)

        print(f"\nDone — {len(files)} file(s) processed.")
        context.close()


if __name__ == "__main__":
    main()
