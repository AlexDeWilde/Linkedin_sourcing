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

# encoding="utf-8" prevents UnicodeEncodeError on cp1252 consoles when the
# model emits non-Latin1 characters (e.g. é, ã in city names, → in output).
sys.stdout.reconfigure(write_through=True, encoding="utf-8")

# ── Paths ──────────────────────────────────────────────────────────────────────
INPUT_DIR       = Path(__file__).parent / "04-enriched"
OUTPUT_DIR      = Path(__file__).parent / "05-LLMfiltered"
LANG_REJECT     = OUTPUT_DIR / "lang_rejects"
LANG_REQ_REJECT = OUTPUT_DIR / "lang_req_rejects"

# ── Ollama config ──────────────────────────────────────────────────────────────
OLLAMA_URL  = "http://127.0.0.1:11434/api/chat"
MAX_TOKENS  = 8192
DEFAULT_NUM_CTX = 32768

def _load_model(stage: int) -> tuple[str, int]:
    """Return (model_name, num_ctx) for the given stage from _model_config.txt."""
    cfg = Path(__file__).parent / "_model_config.txt"
    default_model = None
    default_ctx = DEFAULT_NUM_CTX
    for raw in cfg.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r'\s+-\s*', line, maxsplit=2)]
        model = parts[0]
        stages = parts[1] if len(parts) > 1 else ""
        ctx = int(parts[2]) if len(parts) > 2 and parts[2] else DEFAULT_NUM_CTX
        if model == "default":
            default_model = stages  # second field is the fallback model name
            default_ctx = ctx
            continue
        if stages and any(int(s) == stage for s in stages.split(",") if s.strip().isdigit()):
            return model, ctx
    if default_model:
        return default_model, default_ctx
    raise RuntimeError(f"No model assigned to stage {stage} and no default in _model_config.txt")

MODEL, NUM_CTX = _load_model(5)

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

# ── Language requirement filter ────────────────────────────────────────────────

# Languages never excluded regardless of required level
# Includes English/ISO names plus localized forms the model may emit when the
# posting itself is in Portuguese, Spanish, French, etc.
_LANG_EXEMPT = {
    "english", "en", "inglês", "ingles", "inglés", "anglais", "englisch",
    "portuguese", "pt", "português", "portugues", "portugués", "portugiesisch",
    "spanish", "es", "espanhol", "español", "espanol", "espagnol", "spanisch",
    "german", "de", "deutsch", "alemão", "alemao", "alemán", "aleman", "allemand",
}

# Levels that map to B2 or above (triggers exclusion for French and Dutch)
_B2_PLUS = {
    "b2", "c1", "c2", "fluent", "native", "mother tongue",
    "full professional", "full professional proficiency",
    "professional proficiency", "advanced", "upper intermediate",
    "business fluent", "near native", "bilingual",
}

# Levels that map to B1 or above (triggers exclusion for all other non-exempt languages)
_B1_PLUS = _B2_PLUS | {
    "b1", "intermediate", "lower intermediate", "conversational",
    "working proficiency", "limited working proficiency",
    "professional", "business",
}

# French and Dutch canonical name sets (incl. localized forms)
_FRENCH  = {"french", "fr", "français", "francais", "french language",
            "francês", "frances", "francés", "französisch", "franzosisch"}
_DUTCH   = {"dutch", "nl", "flemish", "vlaams", "nederlands", "dutch language", "flemish dutch",
            "holandês", "holandes", "holandés", "neerlandais", "néerlandais", "niederländisch"}


def lang_req_disqualifier(lang_reqs: list) -> tuple[bool, str]:
    """Return (True, reason_string) if any hard language requirement triggers exclusion."""
    for req in lang_reqs:
        if not req.get("required", True):
            continue
        lang  = str(req.get("language", "")).lower().strip()
        level = str(req.get("level",    "")).lower().strip()

        if lang in _LANG_EXEMPT:
            continue

        if lang in _FRENCH or lang in _DUTCH:
            if level in _B2_PLUS:
                return True, f"{req.get('language', lang)} at {req.get('level', level)} required"
            continue

        # All other languages: B1 or above → exclude
        if level in _B1_PLUS:
            return True, f"{req.get('language', lang)} at {req.get('level', level)} required"

    return False, ""


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
- "language_requirements": list of language proficiencies that are HARD REQUIREMENTS in the job posting. Include ONLY languages explicitly required — not optional, preferred, "a plus", or "desirable". Each entry must have: {{"language": "<language name in English, e.g. English, Portuguese, Spanish, German, French, Dutch — NOT the localized name>", "level": "<CEFR level or descriptor such as B1, B2, C1, fluent, native, intermediate, advanced, basic>", "required": true}}. If no hard language requirements are stated, return an empty list [].

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

        resp = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=600)
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

    # ── Language requirement check ─────────────────────────────────────────────
    lang_reqs = info.get("language_requirements", [])
    if not isinstance(lang_reqs, list):
        lang_reqs = []
    disqualified, reason = lang_req_disqualifier(lang_reqs)
    if disqualified and not force:
        print(f"  → REJECTED (language requirement: {reason}) — moving to lang_req_rejects/")
        LANG_REQ_REJECT.mkdir(parents=True, exist_ok=True)
        shutil.move(str(md_file),  LANG_REQ_REJECT / md_file.name)
        shutil.move(str(url_file), LANG_REQ_REJECT / url_file.name)
        return
    if disqualified and force:
        print(f"  FORCE — language requirement ({reason}) bypassed")

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
