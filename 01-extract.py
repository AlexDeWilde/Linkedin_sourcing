#!/usr/bin/env python3
"""
LinkedIn Job URL Extractor
Launches a dedicated Chrome profile (inside this project folder) via Playwright.
Your main Chrome stays open — no conflict, no restart needed.

First run only: log into LinkedIn in the Chrome window that opens, then
re-run. The session is saved in .chrome_profile/ and reused every time.
"""

import re
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

LINKS_FILE      = Path(__file__).parent / "00-links.txt"
OUTPUT_DIR      = Path(__file__).parent / "01-extracted"
CHROME_PROFILE  = Path(__file__).parent / ".chrome_profile"
SENTINEL        = "Are these results helpful"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def make_output_path(title: str, company: str, date_str: str) -> Path:
    base = f"{date_str}_{safe_filename(title)} - {safe_filename(company)} - LinkedIn"
    path = OUTPUT_DIR / f"{base}.url"
    if not path.exists():
        return path
    counter = 0
    while True:
        path = OUTPUT_DIR / f"{base} ({counter:02d}).url"
        if not path.exists():
            return path
        counter += 1


def write_url_file(path: Path, url: str) -> None:
    path.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Page interactions
# ---------------------------------------------------------------------------

def has_no_results(page) -> bool:
    return page.evaluate("""
        () => {
            const t = document.body.innerText || '';
            return t.includes('No matching jobs') || t.includes('no matching jobs');
        }
    """)


def dismiss_all_cards(page, limit: int) -> int:
    # Only target genuine dismiss buttons — not the "undo" state that appears after clicking
    SELECTOR = 'button.job-card-container__action[aria-label^="Dismiss "]'
    dismissed = 0
    for _ in range(limit):
        btns = page.locator(SELECTOR)
        if btns.count() == 0:
            print("  No more dismiss buttons found")
            break
        try:
            btn = btns.first
            btn.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(1000)
            aria = btn.get_attribute("aria-label") or "(no label)"
            print(f"  Clicking: {aria}")
            btn.click(timeout=3000)
            dismissed += 1
            # Wait for this card to leave the active-dismiss state before next
            page.wait_for_timeout(1500)
        except Exception as e:
            print(f"  Click failed: {e}")
            break

    print(f"  Done — dismissed {dismissed} cards")
    return dismissed


def get_expected_count(page) -> int | None:
    return page.evaluate("""
        () => {
            for (const el of document.querySelectorAll('*')) {
                if (el.children.length > 0) continue;
                const t = (el.innerText || '').trim();
                if (t.length > 60) continue;
                const m = t.match(/\\b(\\d+)\\s+results?\\b/i);
                if (m) return parseInt(m[1]);
            }
            return null;
        }
    """)


def scroll_and_collect(page) -> list:
    seen_urls = set()
    jobs      = []

    def harvest():
        batch = page.evaluate(f"""
            () => {{
                const results = [];
                for (const card of document.querySelectorAll('a[href*="/jobs/view/"]')) {{
                    const href  = card.getAttribute('href') || '';
                    const match = href.match(/\\/jobs\\/view\\/(\\d+)/);
                    if (!match) continue;
                    const cleanUrl = `https://www.linkedin.com/jobs/view/${{match[1]}}/`;
                    const title = (card.innerText || '').trim().split('\\n')[0].trim();
                    if (!title) continue;
                    const li = card.closest('li');
                    let company = '';
                    if (li) {{
                        const el =
                            li.querySelector('[class*="company-name"]')        ||
                            li.querySelector('[class*="primary-description"]') ||
                            li.querySelector('[class*="subtitle"]');
                        if (el) company = (el.innerText || '').trim().split('\\n')[0].trim();
                    }}
                    results.push({{ url: cleanUrl, title, company: company || 'LinkedIn' }});
                }}
                return results;
            }}
        """)
        new = 0
        for r in (batch or []):
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                jobs.append((r["title"], r["company"], r["url"]))
                new += 1
        return new

    def sentinel_in_dom():
        return page.evaluate(f"""
            () => {{
                for (const el of document.querySelectorAll('*'))
                    if (el.children.length === 0 &&
                        el.textContent.includes('{SENTINEL}')) return true;
                return false;
            }}
        """)

    # Find first job card position for mouse wheel target
    card_box = None
    try:
        card_box = page.locator('li:has(a[href*="/jobs/view/"])').first.bounding_box(timeout=5000)
    except Exception:
        pass
    wx = card_box["x"] + card_box["width"]  / 2 if card_box else 300
    wy = card_box["y"] + card_box["height"] / 2 if card_box else 400
    page.wait_for_timeout(500)

    for i in range(80):
        new = harvest()
        if sentinel_in_dom() and new == 0:
            break
        page.mouse.move(wx, wy)
        page.wait_for_timeout(300)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(1500)
    else:
        print("  WARNING: reached scroll limit before sentinel")

    return jobs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    links = [
        u.strip()
        for u in LINKS_FILE.read_text(encoding="utf-8").splitlines()
        if u.strip() and not u.strip().startswith("#")
    ]

    if not links:
        print("00-links.txt is empty — nothing to do.")
        return

    date_str = datetime.now().strftime("%Y%m%d")

    CHROME_PROFILE.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(CHROME_PROFILE),
            channel="chrome",
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page  = context.new_page()

        # First-run check: redirect to LinkedIn login if not authenticated
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30_000)
        if "/login" in page.url or "/authwall" in page.url:
            print("\nNot logged in. Please log into LinkedIn in the Chrome window,")
            print("then press ENTER here to continue...")
            input()
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30_000)

        total = 0

        for i, search_url in enumerate(links, 1):
            print(f"\n[{i}/{len(links)}] {search_url[:90]}")
            page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2_500)

            if has_no_results(page):
                print("   No matching jobs — skipping")
                continue

            expected = get_expected_count(page)
            print(f"   Expected: {expected if expected is not None else 'unknown'}")

            jobs = scroll_and_collect(page)
            print(f"   Extracted: {len(jobs)}")

            if expected is not None and len(jobs) != expected:
                print(f"   WARNING: expected {expected}, got {len(jobs)}")

            for title, company, job_url in jobs:
                out = make_output_path(title, company, date_str)
                write_url_file(out, job_url)
                print(f"   + {out.name}")
                total += 1

            print("   Dismissing cards...")
            dismiss_all_cards(page, limit=len(jobs))

        print(f"\nDone — {total} .url files saved to {OUTPUT_DIR}")
        context.close()


if __name__ == "__main__":
    main()
