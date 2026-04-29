#!/usr/bin/env python3
"""
Stage 05 — LLM filter.
Reads .md files from 04-enriched/, calls Ollama (model from _model_config.txt) to:
  - Detect language of the job description
  - Extract published date, city, title, company for renaming

Non-EN/PT/ES jobs → 05-LLMfiltered/lang_rejects/
Accepted jobs     → renamed and moved to 05-LLMfiltered/

Rename format: YYYYMMDD_CITY_Title_-_Company_-_Source.url/.md
(Source is identified by the LLM — "LinkedIn", "Personio", "Greenhouse", etc.)
"""

import json
import re
import shutil
import sys
import unicodedata
from datetime import date
from pathlib import Path

import requests

sys.stdout.reconfigure(write_through=True)

# ── Paths ──────────────────────────────────────────────────────────────────────
INPUT_DIR   = Path(__file__).parent / "04-enriched"
OUTPUT_DIR  = Path(__file__).parent / "05-LLMfiltered"
LANG_REJECT = OUTPUT_DIR / "lang_rejects"

# ── Ollama config ──────────────────────────────────────────────────────────────
OLLAMA_URL  = "http://192.168.68.52:11434/api/chat"
NUM_CTX     = 49152
MAX_TOKENS  = 8192

def _load_model(stage: int) -> str:
    cfg = Path(__file__).parent / "_model_config.txt"
    default = None
    for raw in cfg.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        model, _, rhs = line.partition("-")
        model, rhs = model.strip(), rhs.strip()
        if model == "default":
            default = rhs  # rhs is the fallback model name
            continue
        if rhs and any(s.strip() == str(stage) for s in rhs.split(",")):
            return model
    if default:
        return default
    raise RuntimeError(f"No model assigned to stage {stage} and no default in _model_config.txt")

MODEL = _load_model(5)

def _unload_all_models():
    base = OLLAMA_URL.replace("/api/chat", "")
    try:
        ps = requests.get(f"{base}/api/ps", timeout=10).json()
    except Exception:
        return  # Ollama unreachable — will surface properly at call time
    for m in ps.get("models", []):
        requests.post(f"{base}/api/generate",
                      json={"model": m["name"], "keep_alive": 0}, timeout=30)
        print(f"  Unloaded {m['name']} from Ollama.", flush=True)

ACCEPTED_LANGS = {"en", "pt", "es"}
TODAY = date.today()


# ── Ollama call ────────────────────────────────────────────────────────────────

def call_ollama(md_content: str) -> dict:
    prompt = f"""Today's date is {TODAY.strftime('%Y-%m-%d')}.

Analyze the job posting below and return ONLY a JSON object with exactly these fields:
- "language": language of the job description section. Use "en" (English), "pt" (Portuguese), "es" (Spanish), or "other".
- "published_date": estimated publication date as YYYYMMDD. Calculate from phrases like "X days ago", "X hours ago", "1 week ago", "2 weeks ago", "1 month ago", etc. relative to today. If not found, use today's date.
- "city": job location city name. Use "REMOTE" if fully remote with no city. If multiple cities, use the primary one.
- "title": the job title.
- "company": the company name.
- "source": the job board hosting this posting, inferred from the URL and page content. Examples: "LinkedIn", "Personio", "Greenhouse", "Lever", "Workday", "Indeed", "company-website". Default to "LinkedIn" if unclear.

Respond with ONLY the JSON object — no explanation, no markdown, no extra text.

---
{md_content}
"""

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "think": False,
        "options": {
            "num_ctx": NUM_CTX,
            "num_predict": MAX_TOKENS,
        },
    }

    for attempt in range(1, 3):
        print("  ", end="", flush=True)
        full_content = ""

        resp = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=300)
        resp.raise_for_status()

        for line in resp.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            delta = chunk.get("message", {}).get("content", "")
            if delta:
                print(delta, end="", flush=True)
                full_content += delta
            if chunk.get("done"):
                break

        print()

        if not full_content:
            print(f"  Empty response (attempt {attempt}) — retrying...")
            continue

        m = re.search(r'\{.*\}', full_content, re.DOTALL)
        if not m:
            print(f"  No JSON found (attempt {attempt}) — retrying...")
            continue

        raw_json = m.group(0)
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            # Fallback: escape any literal control chars inside string values
            cleaned = re.sub(r'[\x00-\x1f]', lambda c: {
                '\n': '\\n', '\t': '\\t', '\r': '\\r'
            }.get(c.group(), ''), raw_json)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                print(f"  JSON parse error (attempt {attempt}): {full_content[:200]!r}")
                raise

    raise ValueError("Ollama returned empty content after 2 attempts")


# ── Filename helpers ───────────────────────────────────────────────────────────

def city_code(city: str) -> str:
    """Return 4-char uppercase city code, or RMTE for remote."""
    c = city.strip()
    if c.upper() in ("REMOTE", "RMTE", "FULLY REMOTE", "REMOTE WORK", "WORLDWIDE"):
        return "RMTE"
    # Strip accents, remove spaces, take first 4 chars uppercased
    nfd = unicodedata.normalize("NFD", c)
    ascii_str = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    compact = ascii_str.replace(" ", "")
    return compact[:4].upper() if compact else "UNKN"


_INVALID = re.compile(r'[<>:"/\\|?*]')

def sanitize(text: str) -> str:
    """Remove filename-invalid chars and replace spaces with underscores."""
    text = _INVALID.sub("", text)
    text = text.replace(" ", "_")
    return text.strip("_")


def build_stem(date_str: str, code: str, title: str, company: str, source: str) -> str:
    return f"{date_str}_{code}_{sanitize(title)}_-_{sanitize(company)}_-_{sanitize(source)}"


def unique_path(parent: Path, stem: str, ext: str) -> Path:
    """Return a non-colliding path, appending _01 _02 … if needed."""
    candidate = parent / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter:02d}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


# ── Per-file processing ────────────────────────────────────────────────────────

def process_file(md_file: Path, force: bool = False) -> None:
    url_file = md_file.with_suffix(".url")
    if not url_file.exists():
        print(f"  WARNING: no matching .url found — skipping.")
        return

    content = md_file.read_text(encoding="utf-8")

    if "no longer accepting applications" in content.lower() and not force:
        print(f"  → CLOSED (no longer accepting applications) — moving to closed/")
        closed_dir = OUTPUT_DIR / "closed"
        closed_dir.mkdir(exist_ok=True)
        shutil.move(str(md_file), closed_dir / md_file.name)
        shutil.move(str(url_file), closed_dir / url_file.name)
        return

    print("  Calling Ollama...", flush=True)
    try:
        info = call_ollama(content)
    except requests.exceptions.ConnectionError:
        print("  ERROR: cannot reach Ollama at", OLLAMA_URL)
        return
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    lang     = str(info.get("language", "other")).lower().strip()
    pub_date = str(info.get("published_date", TODAY.strftime("%Y%m%d"))).strip()
    city     = str(info.get("city", "")).strip()
    title    = str(info.get("title", md_file.stem)).strip()
    company  = str(info.get("company", "")).strip()
    source   = str(info.get("source", "LinkedIn")).strip() or "LinkedIn"

    # Validate date format — fall back to today if malformed
    if not re.fullmatch(r"\d{8}", pub_date):
        pub_date = TODAY.strftime("%Y%m%d")

    print(f"  Language : {lang}")
    print(f"  Date     : {pub_date}")
    print(f"  City     : {city}")
    print(f"  Title    : {title}")
    print(f"  Company  : {company}")
    print(f"  Source   : {source}")

    if lang not in ACCEPTED_LANGS:
        if force:
            print(f"  FORCE — language {lang!r} accepted (bypassing language filter)")
        else:
            print(f"  → REJECTED (language: {lang!r}) — moving to lang_rejects/")
            LANG_REJECT.mkdir(parents=True, exist_ok=True)
            shutil.move(str(md_file),  LANG_REJECT / md_file.name)
            shutil.move(str(url_file), LANG_REJECT / url_file.name)
            return

    code = city_code(city)
    stem = build_stem(pub_date, code, title, company, source)

    # Resolve conflicts independently so both extensions share the same counter
    new_md  = unique_path(OUTPUT_DIR, stem, ".md")
    new_url = new_md.with_suffix(".url")
    while new_url.exists():
        # Both must be free; bump the counter used for .md and retry
        base = new_md.stem
        m = re.search(r"_(\d{2})$", base)
        if m:
            n = int(m.group(1)) + 1
            base = base[: -len(m.group(0))]
        else:
            n = 1
        new_md  = OUTPUT_DIR / f"{base}_{n:02d}.md"
        new_url = OUTPUT_DIR / f"{base}_{n:02d}.url"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(md_file),  new_md)
    shutil.move(str(url_file), new_url)
    print(f"  → ACCEPTED")
    print(f"    {new_md.name}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    force = "--force" in sys.argv

    _unload_all_models()

    md_files = sorted(INPUT_DIR.glob("*.md"))
    if not md_files:
        print("04-enriched/ has no .md files — nothing to do.")
        return

    print(f"Stage 05 — LLM Filter")
    print(f"  Model : {MODEL}")
    print(f"  Input : 04-enriched/  ({len(md_files)} listings)")
    print(f"  Output: 05-LLMfiltered/")
    if force:
        print("Force mode — language filter and closed-listing check bypassed.")
    OUTPUT_DIR.mkdir(exist_ok=True)

    for i, md_file in enumerate(md_files, 1):
        print(f"\n[{i}/{len(md_files)}] {md_file.name}")
        process_file(md_file, force=force)


    print("\nDone.")


if __name__ == "__main__":
    main()
