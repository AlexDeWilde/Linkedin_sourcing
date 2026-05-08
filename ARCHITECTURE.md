# Architecture

Visual reference for the LinkedIn Sourcing pipeline. All diagrams use [Mermaid](https://mermaid.js.org/) syntax.

---

## Module Structure

```mermaid
graph LR
    subgraph Ingestion
        S00[00-parse_email.py]
        S01[01-extract.py]
    end

    subgraph Filtering
        S02[02-dedup.py]
        S03[03-quick_filter.py]
    end

    subgraph Enrichment & Scoring
        S04[04-enrich.py]
        S05[05-LLM_filter.py]
        S06[06-score.py]
    end

    subgraph Review
        S07p[07-review.py<br/>Flask server]
        S07h[07-review.html<br/>Kanban SPA]
    end

    subgraph External Services
        OL[(Ollama<br/>192.168.68.52:11434)]
        PW[[Playwright / Chrome]]
    end

    subgraph Shared State
        DEDUP[02-dedup_seen.txt]
        EXCEL[(06-listings_db.xlsx)]
        CHROME[.chrome_profile/]
        MCFG[_model_config.txt]
        CRIT[06-score_crit.txt]
    end

    S01 --> PW
    S04 --> PW
    S05 --> OL
    S06 --> OL
    S07p --> PW

    S01 & S04 --> CHROME
    S05 & S06 --> MCFG
    S06 --> CRIT
    S02 --> DEDUP
    S06 --> EXCEL
    S07p --> EXCEL
    S07p --> S07h
```

---

## Pipeline Data Flow

```mermaid
flowchart TD
    EML["00-emails/<br/>.eml files"] --> S00["<b>00 — Parse Email</b><br/>Extract LinkedIn URLs"]
    LINKS["00-links.txt<br/>Search URLs"] --> S01["<b>01 — Extract</b><br/>Scrape LinkedIn search<br/><i>Playwright</i>"]

    S00 --> EX01["01-extracted/<br/>.url files"]
    S01 --> EX01

    EX01 --> S02["<b>02 — Dedup</b><br/>Check against seen list"]
    S02 -->|new| EX02["02-deduplicated/<br/>.url"]
    S02 -.->|duplicate| DEL1((deleted))
    S02 -->|append| SEEN["02-dedup_seen.txt"]

    EX02 --> S03["<b>03 — Quick Filter</b><br/>Keyword exclusion"]
    EXCL["03-exclusions.txt"] -.-> S03
    S03 -->|pass| EX03["03-quickfiltered/<br/>.url"]
    S03 -.->|match| DEL2((deleted))

    EX03 --> S04["<b>04 — Enrich</b><br/>Fetch full JD via Chrome<br/><i>Playwright</i>"]
    S04 --> EX04["04-enriched/<br/>.url + .md pairs"]

    EX04 --> S05["<b>05 — LLM Filter</b><br/>Language · date · city · source<br/><i>Ollama</i>"]
    S05 -->|EN/PT/ES| EX05["05-LLMfiltered/<br/>renamed .url + .md"]
    S05 -.->|wrong language| LR["lang_rejects/"]
    S05 -.->|FR/NL B2+, other B1+| LRR["lang_req_rejects/"]
    S05 -.->|closed listing| CL["closed/"]

    EX05 --> S06["<b>06 — Score</b><br/>Score vs criteria<br/><i>Ollama</i>"]
    CRIT["06-score_crit.txt"] -.-> S06
    S06 -->|score ≥ 30| EX06["06-LLM_scored/<br/>.url + .md + _SCORING.md"]
    S06 -->|location disq.| DQ["06-disqualified/"]
    S06 -->|role disq. or &lt;30| REJ["07-rejects/"]
    S06 -->|append row| XL[("06-listings_db.xlsx")]

    EX06 --> S07["<b>07 — Review</b><br/>Kanban console<br/><i>Flask</i>"]
    REJ --> S07
    S07 <-->|read/write| XL
    S07 <-->|move files| COLS["08-consider/<br/>09-priorities/<br/>10-in_process/<br/>11-applied/"]
```

---

## File Lifecycle

Shows how a single listing's files evolve across stages.

```mermaid
flowchart LR
    A[".url<br/><i>YYYYMMDD_Title - Company - LinkedIn.url</i>"]
    -->|"02 dedup<br/>03 filter"| B[".url<br/><i>same name</i>"]
    -->|"04 enrich"| C[".url + .md<br/><i>same stem, paired</i>"]
    -->|"05 LLM filter"| D[".url + .md<br/><i>YYYYMMDD_CITY_Title_-_Company_-_Source</i>"]
    -->|"06 score"| E[".url + .md + _SCORING.md<br/><i>REFNR_SCORE_DATE_CITY_Title_-_Co_-_Src</i>"]
    -->|"07 review"| F["same triplet<br/>moved between<br/>column folders"]
```

---

## LLM Scoring Sequence

```mermaid
sequenceDiagram
    participant S as 06-score.py
    participant O as Ollama
    participant X as Excel DB

    S->>S: Load criteria from 06-score_crit.txt
    S->>S: Read .md job description

    S->>O: POST /api/chat (stream: true, think: false)
    Note right of O: Model evaluates JD<br/>against all criteria
    O-->>S: Streaming JSON chunks

    S->>S: Parse JSON (additions, deductions, disqualifiers)

    alt Location disqualifier
        S->>S: Move to 06-disqualified/
        Note over S: No ref_nr, no Excel row
    else Role disqualifier or score < 30
        S->>X: Append row (status=rejected, reason=Role)
        S->>S: Move to 07-rejects/
    else Normal
        S->>S: Calculate score (100 + adds − deds, floor 0)
        S->>S: Assign ref_nr (next sequential)
        S->>X: Append row (status=new)
        S->>S: Rename triplet, move to 06-LLM_scored/
    end
```

---

## Review Console Interactions

```mermaid
sequenceDiagram
    participant U as Browser
    participant F as Flask (07-review.py)
    participant FS as Filesystem
    participant X as Excel DB

    U->>F: GET /
    F-->>U: 07-review.html (SPA)

    U->>F: GET /api/listings
    F->>FS: Scan 6 column folders
    F-->>U: JSON (all cards)

    U->>F: POST /api/move {stem, from, to}
    F->>FS: Move .md + .url + sidecars
    F->>X: Update status + date column
    F-->>U: {ok: true}

    U->>F: POST /api/save_scoring {ref_nr, raw JSON}
    F->>F: Recalculate score
    F->>FS: Rewrite _SCORING.md, rename triplet
    F->>X: Update score + metadata
    F-->>U: {ok, new_stem, new_score}

    U->>F: POST /api/expire_old
    F->>FS: Find cards > 30 days old
    F->>FS: Move to 07-rejects/
    F->>X: Set status=rejected, reason=Expired
    F-->>U: {ok, expired: N}
```

---

## Batch Orchestration

```mermaid
flowchart TD
    subgraph "__01_RUN_ALL.bat"
        A1[00] --> A2[01] --> A3[02] --> A4[03] --> A5[04] --> A6[05] --> A7[06]
        A7 --> A8["07 (new window)"]
        A8 --> A9["5-min countdown → hibernate"]
    end

    subgraph "__02_RUN_ALL_NOHIB.bat"
        B1[00] --> B2[01] --> B3[02] --> B4[03] --> B5[04] --> B6[05] --> B7[06]
        B7 --> B8["07 (new window)"]
    end

    subgraph "__03_EMAIL_ONLY.bat"
        C1[00] --> C3[02] --> C4[03] --> C5[04] --> C6[05] --> C7[06]
    end

    subgraph "__04_EXTRACTED.bat  (--force)"
        D3["02 --force"] --> D4["03 --force"] --> D5[04] --> D6[05] --> D7[06]
    end
```

---

## Ollama Integration

```mermaid
flowchart LR
    subgraph Pipeline Host
        S05[05-LLM_filter.py]
        S06[06-score.py]
        CFG[_model_config.txt]
    end

    subgraph "Legion (192.168.68.52)"
        OL[Ollama API :11434]
        M1[gemma4:e4b]
        M2[gemma4:26b]
        OL --- M1 & M2
    end

    CFG -.->|model assignment| S05 & S06
    S05 -->|"stage 05 · num_ctx 49152 · num_predict 8192"| OL
    S06 -->|"stage 06 · num_ctx 49152 · num_predict 2048"| OL
```

---

## Excel Database Schema

```mermaid
erDiagram
    LISTING {
        text ref_nr PK "0001 (4-digit)"
        text fit_score "082 (3-digit)"
        date date_published "DD/MM/YYYY"
        text city "MUNICH (7-char)"
        text tag "client company or blank"
        text job_title "CFO"
        text company_name "Acme Corp"
        text source "LinkedIn"
        date date_found "DD/MM/YYYY"
        text status "new | in_consideration | priorities | in_process | applied | rejected"
        text report_produced "Yes / No"
        text processed "notes"
        text url "full URL"
        date date_considered "set by stage 07"
        date date_priorities "set by stage 07"
        date date_in_process "set by stage 07"
        date date_applied "set by stage 07"
        date date_rejected "set by stage 07"
        text comment "free-text notes"
        text reject_reason "Location | Seniority | Stack | Company | Pay | Role | Expired | Language(s)"
    }
```
