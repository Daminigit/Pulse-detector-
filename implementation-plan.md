# Implementation Plan — Pulse Detector

> **Groww App · Weekly Review Pulse Pipeline**
> Phase-wise build plan derived from [`architecture.md`](./architecture.md) and [`ProblemStatement.md`](./ProblemStatement.md).

---

## Overview

| # | Phase | Scope | Est. Effort |
|---|---|---|---|
| ✅ P0 | Project Setup & Scaffolding | Repo structure, env, dependencies | 0.5 day |
| ✅ P1 | Data Models | Pydantic models for all data objects | 0.5 day |
| ✅ P2 | Review Ingestion | Fetch & clean Play Store reviews | 1 day |
| ✅ P3 | LangChain Agent — Clustering | Theme clustering with Gemini | 1 day |
| P4 | LangChain Agent — Summarisation | Generate `PulseNote` from clusters | 1 day |
| P5 | Google Docs via MCP | Publish pulse to Google Docs | 1 day |
| P6 | Gmail via MCP | Create draft email | 0.5 day |
| P7 | Orchestrator & End-to-End Pipeline | Wire all stages in `main.py` | 0.5 day |
| P8 | Error Handling & Resilience | Retries, fallbacks, edge cases | 0.5 day |
| P9 | Testing & Validation | Manual + dry-run verification | 1 day |
| P10 | Documentation & Cleanup | README, `.env.example`, final push | 0.5 day |

**Total estimated effort: ~7.5 days**

**Status legend:**
`⬜ Todo` · `🔄 In Progress` · `✅ Done` · `❌ Blocked` · `⏭️ Skipped`

---

## Phase 0 — Project Setup & Scaffolding

**Goal:** Working repo skeleton — everything compiles, env loads, git is clean.

### Tasks

| Task | File(s) | Status |
|---|---|---|
| Create `src/` directory structure | `src/` | ✅ |
| Create `output/` directory with `.gitkeep` | `output/.gitkeep` | ✅ |
| Write `.gitignore` (`.env`, `__pycache__`, `output/*.json`) | `.gitignore` | ✅ |
| Write `.env.example` with all required keys | `.env.example` | ✅ |
| Create local `.env` with real API key | `.env` | ✅ |
| Write `requirements.txt` | `requirements.txt` | ✅ |
| Install dependencies in a virtual environment | `venv/` | ✅ |
| Verify imports work (`python -c "import langchain_google_genai"`) | — | ✅ |

### `.env.example` content
```env
GEMINI_API_KEY=your_gemini_api_key_here
APP_ID=com.nextbillion.groww
WEEKS_BACK=10
MAX_THEMES=5
TARGET_EMAIL=your-email@example.com
GOOGLE_DOC_ID=
OUTPUT_DIR=./output
```

### `requirements.txt`
```
# LangChain — agent framework
langchain-core>=0.2
langchain-google-genai>=1.0
langgraph>=0.1

# Play Store scraper
google-play-scraper>=1.2

# MCP client
mcp>=1.0

# Config & validation
python-dotenv>=1.0
pydantic>=2.0
```

### Exit Criteria
- [x] `pip install -r requirements.txt` completes without errors
- [x] `.env` loads correctly via `python-dotenv`
- [x] All `src/*.py` files exist (even if empty stubs)
- [x] `.env` is absent from `git status`

---

## Phase 1 — Data Models

**Goal:** Define all Pydantic models that flow through the pipeline. Every other phase depends on these.

### Tasks

| Task | File | Status |
|---|---|---|
| Define `RawReview` model | `src/models.py` | ✅ |
| Define `CleanReview` model | `src/models.py` | ✅ |
| Define `Theme` model | `src/models.py` | ✅ |
| Define `ClusterResult` model (LangChain output parser target) | `src/models.py` | ✅ |
| Define `PulseNote` model | `src/models.py` | ✅ |
| Write unit smoke-test: instantiate each model with dummy data | `src/models.py` | ✅ |

### Model Definitions

```python
# src/models.py

from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import List, Optional

class RawReview(BaseModel):
    reviewer_name: Optional[str] = None   # stripped in filter
    reviewer_id: Optional[str] = None     # stripped in filter
    rating: int = Field(ge=1, le=5)
    title: Optional[str] = None
    text: str
    date: date
    app_version: Optional[str] = None
    device: Optional[str] = None          # stripped in filter

class CleanReview(BaseModel):
    id: str                               # generated UUID
    rating: int = Field(ge=1, le=5)
    title: Optional[str] = None
    text: str                             # PII-masked
    date: date
    app_version: Optional[str] = None
    theme: Optional[str] = None           # assigned post-clustering

class Theme(BaseModel):
    label: str
    display_name: str
    count: int
    pct: float

class ClusterResult(BaseModel):
    assignments: dict[str, str]           # review_id → theme_label

class PulseNote(BaseModel):
    week_range: str
    reviews_analysed: int
    avg_rating: float
    top_themes: List[Theme]               # top 3
    quotes: List[str]                     # 3 anonymised verbatim quotes
    action_ideas: List[str]               # 3 concrete recommendations
    generated_at: datetime = Field(default_factory=datetime.utcnow)
```

### Exit Criteria
- [x] All 5 models instantiate without errors
- [x] `ClusterResult` and `PulseNote` are importable by `cluster.py` and `summarise.py`

---

## Phase 2 — Review Ingestion (`ingest.py` + `filter.py`)

**Goal:** Reliably fetch Play Store reviews for `com.nextbillion.groww` and return clean, PII-free `CleanReview` objects.

### Tasks

| Task | File | Status |
|---|---|---|
| Implement `fetch_reviews(app_id, weeks_back)` using `google-play-scraper` | `src/ingest.py` | ✅ |
| Handle pagination until date cutoff is reached | `src/ingest.py` | ✅ |
| Map raw scraper output to `RawReview` model | `src/ingest.py` | ✅ |
| Implement `filter_and_clean(reviews)` | `src/filter.py` | ✅ |
| Date-range filter (drop reviews older than `weeks_back`) | `src/filter.py` | ✅ |
| Deduplicate by review text hash | `src/filter.py` | ✅ |
| Language filter — keep English only | `src/filter.py` | ✅ |
| PII strip — remove `reviewer_name`, `reviewer_id`, `device` | `src/filter.py` | ✅ |
| Mask email patterns in text with regex | `src/filter.py` | ✅ |
| Assign UUID to each `CleanReview` | `src/filter.py` | ✅ |
| Log count + avg rating after filtering | `src/filter.py` | ✅ |
| Warn if `< 10` reviews remain | `src/filter.py` | ✅ |

### Key Implementation Notes

```python
# src/ingest.py  — core fetch loop (conceptual)
from google_play_scraper import reviews, Sort

def fetch_reviews(app_id: str, weeks_back: int) -> list[RawReview]:
    cutoff = date.today() - timedelta(weeks=weeks_back)
    result, _ = reviews(app_id, lang="en", country="in",
                        sort=Sort.NEWEST, count=500)
    return [RawReview(**r) for r in result if r["at"].date() >= cutoff]
```

```python
# src/filter.py  — PII strip (conceptual)
import re, uuid

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

def strip_pii(text: str) -> str:
    return EMAIL_RE.sub("[email]", text)
```

### Exit Criteria
- [x] `fetch_reviews("com.nextbillion.groww", 10)` returns ≥ 1 `RawReview`
- [x] `filter_and_clean(raw)` returns `List[CleanReview]` with no `reviewer_name` / `reviewer_id`
- [x] Email patterns in text are replaced with `[email]`
- [x] Reviews older than `WEEKS_BACK` are excluded

---

## Phase 3 — LangChain Clustering Agent (`cluster.py`)

**Goal:** Use a LangChain LCEL chain with Gemini to group `CleanReview` objects into ≤ 5 named themes.

### Tasks

| Task | File | Status |
|---|---|---|
| Write `CLUSTER_SYSTEM_PROMPT` with `{format_instructions}` and `{theme_list}` | `src/prompts.py` | ✅ |
| Instantiate `ChatGoogleGenerativeAI` with `temperature=0.3` | `src/cluster.py` | ✅ |
| Build `cluster_chain` using LCEL (`prompt \| llm \| parser`) | `src/cluster.py` | ✅ |
| Wrap chain with `.with_retry(stop_after_attempt=3)` | `src/cluster.py` | ✅ |
| Serialize `CleanReview` texts to JSON for prompt input | `src/cluster.py` | ✅ |
| Parse `ClusterResult` and map theme labels back to reviews | `src/cluster.py` | ✅ |
| Enforce 5-theme cap (merge smallest if > 5 returned) | `src/cluster.py` | ✅ |
| Implement keyword-heuristic fallback if LLM chain fails | `src/cluster.py` | ✅ |
| Return `Dict[str, List[CleanReview]]` (theme → reviews) | `src/cluster.py` | ✅ |

### LCEL Chain Pattern

```python
# src/cluster.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from src.models import ClusterResult
from src.prompts import CLUSTER_SYSTEM_PROMPT

parser = PydanticOutputParser(pydantic_object=ClusterResult)

cluster_chain = (
    ChatPromptTemplate.from_messages([
        ("system", CLUSTER_SYSTEM_PROMPT),
        ("human", "{reviews_json}")
    ])
    | ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.3)
      .with_retry(stop_after_attempt=3)
    | parser
)
```

### Candidate Themes
```python
THEMES = [
    "onboarding_kyc",
    "payments_transactions",
    "app_performance",
    "portfolio_statements",
    "withdrawals_redemptions",
]
```

### Exit Criteria
- [x] `cluster_themes(clean_reviews)` returns a dict with 1–5 keys
- [x] Every `CleanReview` is assigned to exactly one theme
- [x] No theme label is outside the `THEMES` list
- [x] Chain retries on `429` without crashing

---

## Phase 4 — LangChain Summarisation Agent (`summarise.py`)

**Goal:** Use a second LangChain chain to generate a structured `PulseNote` from themed clusters.

### Tasks

| Task | File | Status |
|---|---|---|
| Write `SUMMARISE_SYSTEM_PROMPT` with `{format_instructions}` | `src/prompts.py` | ⬜ |
| Build `summarise_chain` using LCEL (`prompt \| llm \| parser`) | `src/summarise.py` | ⬜ |
| Set `temperature=0.7` for creative action ideas | `src/summarise.py` | ⬜ |
| Select top 3 themes by review count before passing to LLM | `src/summarise.py` | ⬜ |
| Pass themed clusters as JSON to the prompt | `src/summarise.py` | ⬜ |
| Validate word count post-generation (≤ 250 words) | `src/summarise.py` | ⬜ |
| Re-prompt with trim instruction if word count exceeded | `src/summarise.py` | ⬜ |
| Save `PulseNote` as JSON to `output/pulse_YYYY-MM-DD.json` | `src/summarise.py` | ⬜ |

### Word Count Validation

```python
# Post-generation guard
def word_count(pulse: PulseNote) -> int:
    text = " ".join(pulse.quotes + pulse.action_ideas)
    return len(text.split())

if word_count(pulse) > 250:
    # re-invoke summarise_chain with explicit trim instruction
    ...
```

### Exit Criteria
- [ ] `generate_pulse(themed_clusters)` returns a valid `PulseNote`
- [ ] `PulseNote` has exactly 3 themes, 3 quotes, 3 action ideas
- [ ] Word count of quotes + action ideas is ≤ 250
- [ ] Output saved to `output/pulse_YYYY-MM-DD.json`
- [ ] No PII in quotes (reviewer names absent)

---

## Phase 5 — Google Docs via MCP (`docs_mcp.py`)

**Goal:** Publish the `PulseNote` as a formatted document in Google Docs using MCP tool calls.

### Tasks

| Task | File | Status |
|---|---|---|
| Set up and verify Google Docs MCP server is running | MCP config | ⬜ |
| Implement `render_pulse_to_markdown(pulse: PulseNote) -> str` | `src/docs_mcp.py` | ⬜ |
| Implement `publish_to_docs(pulse)` using MCP `create_document` | `src/docs_mcp.py` | ⬜ |
| If `GOOGLE_DOC_ID` set → use MCP `update_document` instead | `src/docs_mcp.py` | ⬜ |
| Log and return the Google Doc URL | `src/docs_mcp.py` | ⬜ |
| Store returned `doc_id` in `.env` hint for subsequent runs | `src/docs_mcp.py` | ⬜ |

### Rendered Pulse Format (Markdown → Docs)

```markdown
# Groww App — Weekly Pulse
**Week:** {week_range}  |  **Reviews:** {reviews_analysed}  |  **Avg Rating:** {avg_rating} ★

---
## Top Themes
1. **{theme_1.display_name}** — {theme_1.count} reviews ({theme_1.pct:.0f}%)
2. **{theme_2.display_name}** — {theme_2.count} reviews ({theme_2.pct:.0f}%)
3. **{theme_3.display_name}** — {theme_3.count} reviews ({theme_3.pct:.0f}%)

## What Users Are Saying
- "{quote_1}"
- "{quote_2}"
- "{quote_3}"

## Action Ideas
1. {action_1}
2. {action_2}
3. {action_3}

---
*Auto-generated by Pulse Detector on {generated_at}*
```

### Exit Criteria
- [ ] MCP server responds to a test `create_document` call
- [ ] A Google Doc is created/updated with the pulse content
- [ ] A valid `doc_url` is returned and printed to console
- [ ] Doc is readable via the returned URL in a browser

---

## Phase 6 — Gmail via MCP (`gmail_mcp.py`)

**Goal:** Create a draft email in Gmail addressed to `TARGET_EMAIL` with the pulse summary and Doc link.

### Tasks

| Task | File | Status |
|---|---|---|
| Set up and verify Gmail MCP server is running | MCP config | ⬜ |
| Implement `build_email_body(pulse, doc_url)` | `src/gmail_mcp.py` | ⬜ |
| Implement `draft_gmail(pulse, doc_url)` using MCP `create_draft` | `src/gmail_mcp.py` | ⬜ |
| Compose subject: `📊 Groww App Weekly Pulse – {week_range}` | `src/gmail_mcp.py` | ⬜ |
| Include top 3 themes, avg rating, and Doc link in body | `src/gmail_mcp.py` | ⬜ |
| Handle MCP failure as soft warning (not hard abort) | `src/gmail_mcp.py` | ⬜ |

### Draft Email Template

```
Subject: 📊 Groww App Weekly Pulse – {week_range}

Hi,

Here's the weekly review pulse for the Groww app.

📄 Full pulse document: {doc_url}

━━━ Quick Summary ━━━
Top themes: {theme_1}, {theme_2}, {theme_3}
Reviews analysed: {reviews_analysed}  |  Avg rating: {avg_rating} ★

{inline_pulse_body}  ← truncated at 500 chars

—
Auto-generated by Pulse Detector
```

### Exit Criteria
- [ ] Gmail MCP server responds to a test `create_draft` call
- [ ] Draft appears in Gmail Drafts folder addressed to `TARGET_EMAIL`
- [ ] Subject line matches format
- [ ] Body contains Google Doc link

---

## Phase 7 — Orchestrator (`main.py`)

**Goal:** Wire all 6 stages into a single runnable pipeline.

### Tasks

| Task | File | Status |
|---|---|---|
| Load `.env` variables at startup | `src/main.py` | ⬜ |
| Call each stage in sequence with typed handoffs | `src/main.py` | ⬜ |
| Print progress to console at each stage | `src/main.py` | ⬜ |
| Print final success message with Doc URL | `src/main.py` | ⬜ |
| Handle `SystemExit` on hard abort stages | `src/main.py` | ⬜ |
| Add `if __name__ == "__main__": run_pipeline()` entrypoint | `src/main.py` | ⬜ |

### Pipeline Sequence

```python
# src/main.py
def run_pipeline():
    print("🔍 [1/6] Fetching reviews...")
    raw = fetch_reviews(APP_ID, WEEKS_BACK)

    print("🧹 [2/6] Filtering and cleaning...")
    clean = filter_and_clean(raw)

    print("🗂️  [3/6] Clustering into themes...")
    themed = cluster_themes(clean, max_themes=MAX_THEMES)

    print("✍️  [4/6] Generating pulse note...")
    pulse = generate_pulse(themed)

    print("📄 [5/6] Publishing to Google Docs...")
    doc_url = publish_to_docs(pulse)

    print("📧 [6/6] Creating Gmail draft...")
    draft_gmail(pulse, doc_url)

    print(f"\n✅ Done! Pulse published: {doc_url}")
```

### Exit Criteria
- [ ] `python src/main.py` runs end-to-end without manual intervention
- [ ] All 6 stages complete and log their progress
- [ ] Doc URL printed on success

---

## Phase 8 — Error Handling & Resilience

**Goal:** Make the pipeline robust against common failures at each stage.

### Tasks

| Stage | Task | Status |
|---|---|---|
| **Ingest** | Retry x3 with exponential backoff on network error | ⬜ |
| **Ingest** | Hard abort if 0 reviews returned | ⬜ |
| **Filter** | Log warning if < 10 reviews remain; continue | ⬜ |
| **Cluster** | Retry x3 via LangChain `.with_retry()` (already built in P3) | ⬜ |
| **Cluster** | Keyword heuristic fallback if all LLM retries fail | ⬜ |
| **Cluster** | Merge themes if > 5 returned | ⬜ |
| **Summarise** | Re-prompt if word count > 250 (max 2 attempts) | ⬜ |
| **Docs MCP** | Hard abort with descriptive error if MCP call fails | ⬜ |
| **Gmail MCP** | Soft warning — log failure, pipeline still reports success | ⬜ |

### Exit Criteria
- [ ] Simulated network failure in ingest retries 3 times before aborting
- [ ] A run with 0 reviews exits with a clear message
- [ ] Pipeline completes even if Gmail MCP fails

---

## Phase 9 — Testing & Validation

**Goal:** Verify end-to-end correctness against real data and constraints.

### Manual Test Checklist

| Test | Expected Result | Status |
|---|---|---|
| Full pipeline run (`python src/main.py`) | Completes in < 3 min, Doc + draft created | ⬜ |
| Pulse note word count | ≤ 250 words (quotes + action ideas) | ⬜ |
| Theme count | Exactly 3 top themes in pulse; ≤ 5 total clusters | ⬜ |
| Quote count | Exactly 3 quotes in pulse | ⬜ |
| Action idea count | Exactly 3 action ideas | ⬜ |
| PII check | No reviewer names in pulse note or Google Doc | ⬜ |
| Google Doc | Readable at returned URL, formatting correct | ⬜ |
| Gmail draft | Present in Drafts, correct subject + Doc link | ⬜ |
| `.env` hygiene | `git status` does not show `.env` | ⬜ |
| Reviews within window | No review older than `WEEKS_BACK` weeks in output | ⬜ |

### Dry-Run Mode (Optional)
Add a `--dry-run` flag to `main.py` that skips MCP calls and prints the rendered pulse to stdout instead — useful for rapid iteration on prompt quality.

---

## Phase 10 — Documentation & Cleanup

**Goal:** Repo is clean, documented, and ready to share or hand off.

### Tasks

| Task | File | Status |
|---|---|---|
| Write `README.md` (quick-start, prerequisites, run instructions) | `README.md` | ⬜ |
| Document MCP server setup steps in README | `README.md` | ⬜ |
| Ensure `.env.example` is complete and committed | `.env.example` | ⬜ |
| Add inline docstrings to all public functions | `src/*.py` | ⬜ |
| Remove debug `print` statements; use `logging` module | `src/*.py` | ⬜ |
| Update `ProblemStatement.md` implementation plan statuses | `ProblemStatement.md` | ⬜ |
| Final `git add . && git commit && git push` | — | ⬜ |

### README Sections
1. Project Overview
2. Prerequisites (Python 3.11+, API keys, MCP servers)
3. Setup (`clone → venv → pip install → .env`)
4. MCP Server Setup (Google Docs + Gmail)
5. Running the pipeline (`python src/main.py`)
6. Output (what gets created)
7. Configuration reference (all `.env` variables)

---

## Dependency Graph

```
P0 (Setup)
   │
   ▼
P1 (Models) ──────────────────────┐
   │                              │
   ▼                              │
P2 (Ingest) ──▶ P3 (Cluster) ──▶ P4 (Summarise)
                                   │
                    ┌──────────────┤
                    │              │
                    ▼              ▼
                 P5 (Docs)    P6 (Gmail)
                    │              │
                    └──────┬───────┘
                           ▼
                       P7 (Orchestrator)
                           │
                           ▼
                       P8 (Error Handling)
                           │
                           ▼
                       P9 (Testing)
                           │
                           ▼
                       P10 (Docs & Cleanup)
```

---

## Key Constraints Checklist

> Verify these at the end of P9 before marking the project complete.

- [ ] **Reviews:** Only public Play Store data — no login-gated scraping
- [ ] **Themes:** ≤ 5 clusters; pulse shows top 3
- [ ] **Length:** Pulse note ≤ 250 words (quotes + action ideas)
- [ ] **Privacy:** Zero PII in any output artifact (Doc, email, local JSON)
- [ ] **MCP-first:** No bespoke OAuth/REST — all Workspace calls go through MCP

---

*Last updated: 2026-09-05 · Pulse Detector v0.1*
