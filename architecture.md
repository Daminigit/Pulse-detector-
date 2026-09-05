# Architecture — Pulse Detector

> **Groww App · Weekly Review Pulse Pipeline**
> Converts raw Play Store reviews into a themed, actionable weekly note — published to Google Docs and delivered via a Gmail draft — using an LLM agent and MCP-first integrations.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture Diagram](#2-high-level-architecture-diagram)
3. [Component Breakdown](#3-component-breakdown)
4. [Data Model](#4-data-model)
5. [Pipeline Stages (Detailed)](#5-pipeline-stages-detailed)
6. [MCP Integration Architecture](#6-mcp-integration-architecture)
7. [LLM / Agent Layer](#7-llm--agent-layer)
8. [Configuration & Secrets](#8-configuration--secrets)
9. [Error Handling & Resilience](#9-error-handling--resilience)
10. [Security & Privacy](#10-security--privacy)
11. [Scalability & Extension Points](#11-scalability--extension-points)
12. [Tech Stack Summary](#12-tech-stack-summary)

---

## 1. System Overview

Pulse Detector is a **single-pipeline agent** that runs on demand (or on a weekly schedule). It has no persistent server — it is a stateless script that reads from a public source, processes with an LLM, and writes to Google Workspace via MCP.

```
Trigger (manual / cron)
        │
        ▼
  Pulse Detector Agent
  ┌───────────────────────────────────────────────────────┐
  │  Ingest  →  Filter  →  Cluster  →  Summarise         │
  │                                         │             │
  │                             ┌───────────┴──────────┐  │
  │                             ▼                      ▼  │
  │                       Google Docs            Gmail    │
  │                       (MCP Server)          (MCP Server)│
  └───────────────────────────────────────────────────────┘
```

**Key design principles:**
- **MCP-first** — all Google Workspace I/O goes through MCP tool calls, zero bespoke OAuth/REST
- **Stateless** — no database; each run is self-contained
- **Privacy-by-default** — PII stripped before any LLM call or output artifact
- **Scannable output** — pulse note hard-capped at ≤ 250 words

---

## 2. High-Level Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL SOURCES                            │
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  Google Play Store  (public RSS / google-play-scraper)      │   │
│   │  App ID: com.nextbillion.groww                               │   │
│   └────────────────────────────┬────────────────────────────────┘   │
└───────────────────────────────┬┘                                     │
                                │  Raw reviews (JSON)                  
                                ▼                                      
┌──────────────────────────────────────────────────────────────────────┐
│                        PULSE DETECTOR AGENT                          │
│                                                                      │
│  ┌────────────┐   ┌────────────┐   ┌───────────────┐   ┌─────────┐  │
│  │  INGEST    │──▶│  FILTER &  │──▶│   CLUSTER     │──▶│SUMMARISE│  │
│  │  Module    │   │  CLEAN     │   │   (LLM)       │   │ (LLM)   │  │
│  │            │   │  Module    │   │  ≤ 5 Themes   │   │         │  │
│  └────────────┘   └────────────┘   └───────────────┘   └────┬────┘  │
│                                                              │       │
│                                          Pulse Note (dict)  │       │
│  ┌───────────────────────────────────────────────────────────▼────┐  │
│  │                     ORCHESTRATOR  (main.py)                    │  │
│  │                                                                │  │
│  │         ┌──────────────────┐      ┌──────────────────┐        │  │
│  │         │  Docs MCP Client │      │  Gmail MCP Client│        │  │
│  │         └────────┬─────────┘      └────────┬─────────┘        │  │
│  └──────────────────┼──────────────────────────┼─────────────────┘  │
└─────────────────────┼──────────────────────────┼────────────────────┘
                      │                          │                     
                      ▼                          ▼                     
           ┌──────────────────┐      ┌──────────────────┐             
           │  Google Docs     │      │  Gmail           │             
           │  MCP Server      │      │  MCP Server      │             
           └────────┬─────────┘      └────────┬─────────┘             
                    │                          │                       
                    ▼                          ▼                       
           ┌──────────────────┐      ┌──────────────────┐             
           │  Google Docs API │      │  Gmail API       │             
           │  (handled by MCP)│      │  (handled by MCP)│             
           └──────────────────┘      └──────────────────┘             
```

---

## 3. Component Breakdown

### 3.1 `ingest.py` — Review Ingestion

| Property | Detail |
|---|---|
| **Responsibility** | Fetch public Play Store reviews for Groww |
| **Source** | `google-play-scraper` (Python) or equivalent ToS-compliant library |
| **App ID** | `com.nextbillion.groww` |
| **Time window** | Configurable — default last 8–12 weeks (`WEEKS_BACK` env var) |
| **Output** | `List[RawReview]` — list of raw review objects |
| **Privacy step** | Strip `reviewer_name`, `reviewer_id`, device identifiers before returning |

```python
# Conceptual interface
def fetch_reviews(app_id: str, weeks_back: int) -> List[RawReview]:
    ...
```

---

### 3.2 `filter.py` — Filter & Clean

| Property | Detail |
|---|---|
| **Responsibility** | Normalise, deduplicate, and sanitise reviews |
| **Operations** | Date-range filter · duplicate removal · language filter (English) · PII strip |
| **Input** | `List[RawReview]` |
| **Output** | `List[CleanReview]` |

**PII stripping rules:**
- Remove `reviewer_name`, `reviewer_id`, `device`
- Mask email patterns in review text (`re.sub`)
- Retain only: `rating`, `title`, `text`, `date`, `app_version`

---

### 3.3 `cluster.py` — Theme Clustering

| Property | Detail |
|---|---|
| **Responsibility** | Group reviews into ≤ 5 meaningful themes |
| **Method** | LLM prompt — send batched review texts, ask for theme assignment |
| **Model** | Gemini (via `google-generativeai` SDK) |
| **Max themes** | **5** (hard constraint) |
| **Output** | `Dict[str, List[CleanReview]]` — theme → reviews mapping |

**Clustering strategy:**
1. Send all cleaned review texts to Gemini in a single structured prompt
2. LLM returns a JSON mapping of `review_id → theme_label`
3. Themes are normalised (merged if semantically equivalent, capped at 5)
4. Each review is tagged with its primary theme

**Candidate themes for Groww:**

| Theme | Typical signals |
|---|---|
| `onboarding_kyc` | account creation, document upload, verification delays |
| `payments_transactions` | SIP setup, transfer failures, UPI issues |
| `app_performance` | crashes, slow load, UI glitches, black screen |
| `portfolio_statements` | P&L display, report downloads, data accuracy |
| `withdrawals_redemptions` | withdrawal delays, failed redemptions, payout issues |

---

### 3.4 `summarise.py` — Pulse Generation

| Property | Detail |
|---|---|
| **Responsibility** | Generate the one-page weekly pulse note |
| **Input** | Themed review clusters |
| **Output** | `PulseNote` dataclass |
| **LLM call** | Single structured prompt → JSON output |
| **Word limit** | ≤ 250 words enforced post-generation |

**`PulseNote` structure:**
```python
@dataclass
class PulseNote:
    week_range: str           # "Aug 18 – Sep 05, 2026"
    reviews_analysed: int     # total count
    avg_rating: float         # e.g. 3.4
    top_themes: List[Theme]   # top 3 themes with counts
    quotes: List[str]         # 3 anonymised verbatim quotes
    action_ideas: List[str]   # 3 concrete recommendations
    generated_at: datetime
```

---

### 3.5 `docs_mcp.py` — Google Docs Integration

| Property | Detail |
|---|---|
| **Responsibility** | Publish pulse note to Google Docs via MCP |
| **Integration** | MCP tool calls — no direct Google Docs REST API |
| **Operations** | `create_document` (first run) or `update_document` (subsequent runs) |
| **Output** | Google Doc URL returned for use in Gmail draft |

**Decision: create vs. update**
- If `GOOGLE_DOC_ID` is set in `.env` → update existing document (append or overwrite)
- If not set → create a new document, print/log the new Doc ID for future use

---

### 3.6 `gmail_mcp.py` — Gmail Integration

| Property | Detail |
|---|---|
| **Responsibility** | Create a draft email via MCP |
| **Integration** | MCP tool calls — no direct Gmail REST API |
| **Operations** | `create_draft` |
| **Recipient** | `TARGET_EMAIL` from `.env` (self or alias) |
| **Draft content** | Subject line + pulse summary body + Google Doc link |

**Draft email format:**
```
Subject: 📊 Groww App Weekly Pulse – [Week Range]

Hi,

Here's the weekly review pulse for the Groww app.

📄 Full pulse document: [Google Doc Link]

━━━ Quick Summary ━━━
Top themes: [Theme 1], [Theme 2], [Theme 3]
Reviews analysed: N  |  Avg rating: X.X ★

[Inline pulse body — truncated if > 500 chars]

This pulse was auto-generated by Pulse Detector.
```

---

### 3.7 `main.py` — Orchestrator

The entry point that chains all components in sequence:

```python
def run_pipeline():
    # 1. Ingest
    raw = fetch_reviews(APP_ID, WEEKS_BACK)

    # 2. Filter & Clean
    clean = filter_and_clean(raw)

    # 3. Cluster
    themed = cluster_themes(clean, max_themes=MAX_THEMES)

    # 4. Summarise
    pulse = generate_pulse(themed)

    # 5. Publish to Google Docs
    doc_url = publish_to_docs(pulse)

    # 6. Draft Gmail
    draft_gmail(pulse, doc_url)

    print(f"✅ Pipeline complete. Doc: {doc_url}")
```

---

## 4. Data Model

```
RawReview
├── reviewer_name   str   ← STRIPPED before CleanReview
├── reviewer_id     str   ← STRIPPED before CleanReview
├── rating          int   (1–5)
├── title           str
├── text            str
├── date            date
├── app_version     str
└── device          str   ← STRIPPED before CleanReview

CleanReview
├── id              str   (generated UUID — no original reviewer ID)
├── rating          int   (1–5)
├── title           str
├── text            str   (PII-masked)
├── date            date
├── app_version     str
└── theme           str   (assigned after clustering)

Theme
├── label           str   (e.g. "app_performance")
├── display_name    str   (e.g. "App Performance")
├── count           int   (number of reviews in theme)
└── pct             float (% of total corpus)

PulseNote
├── week_range      str
├── reviews_analysed int
├── avg_rating      float
├── top_themes      List[Theme]   (top 3)
├── quotes          List[str]     (3 verbatim, anonymised)
├── action_ideas    List[str]     (3 concrete)
└── generated_at    datetime
```

---

## 5. Pipeline Stages (Detailed)

```
Stage 1 — INGEST
─────────────────
Input : App ID, weeks_back
Action: Call google-play-scraper, paginate until date cutoff
Output: List[RawReview]  (~50–500 reviews typical)
Error : Retry x3 on network failure; abort if 0 reviews

Stage 2 — FILTER & CLEAN
─────────────────────────
Input : List[RawReview]
Action: Date filter → deduplicate → language detect → PII strip → normalise text
Output: List[CleanReview]
Error : Warn if < 10 reviews (low signal); continue

Stage 3 — CLUSTER
─────────────────
Input : List[CleanReview]  (texts only, no IDs)
Action: Batch LLM prompt → JSON theme assignment → normalise → cap at 5
Output: Dict[theme_label, List[CleanReview]]
Error : Retry on LLM timeout; fallback to keyword heuristics if LLM fails

Stage 4 — SUMMARISE
────────────────────
Input : Themed clusters
Action: LLM prompt → structured PulseNote JSON → validate word count
Output: PulseNote
Error : Re-prompt if word count > 250 (ask LLM to trim)

Stage 5 — DOCS MCP
───────────────────
Input : PulseNote (rendered as Markdown/HTML)
Action: MCP create_document or update_document
Output: Google Doc URL
Error : Abort with clear message if MCP call fails

Stage 6 — GMAIL MCP
────────────────────
Input : PulseNote + Google Doc URL
Action: MCP create_draft
Output: Draft email created in sender's Gmail
Error : Log warning; pipeline still succeeds if Docs step passed
```

---

## 6. MCP Integration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Pulse Detector Agent                       │
│                                                             │
│   docs_mcp.py                     gmail_mcp.py             │
│   ┌──────────────────┐            ┌──────────────────┐     │
│   │ MCPClient        │            │ MCPClient        │     │
│   │ .call_tool(      │            │ .call_tool(      │     │
│   │  "create_doc",   │            │  "create_draft", │     │
│   │  {content: ...}  │            │  {to, subject,   │     │
│   │ )                │            │   body}          │     │
│   └────────┬─────────┘            └────────┬─────────┘     │
└────────────┼──────────────────────────────┼────────────────┘
             │  MCP protocol (stdio / SSE)  │
             ▼                              ▼
   ┌──────────────────┐          ┌──────────────────┐
   │  @google/mcp-    │          │  @google/mcp-    │
   │  server-gdocs    │          │  server-gmail    │
   │  (MCP Server)    │          │  (MCP Server)    │
   └────────┬─────────┘          └────────┬─────────┘
            │ Google Docs API              │ Gmail API
            │ (OAuth handled by MCP)       │ (OAuth handled by MCP)
            ▼                              ▼
   ┌──────────────────┐          ┌──────────────────┐
   │  Google Docs     │          │  Gmail           │
   └──────────────────┘          └──────────────────┘
```

**MCP tool contracts:**

| MCP Server | Tool | Key Parameters | Returns |
|---|---|---|---|
| Google Docs | `create_document` | `title`, `content` (Markdown/HTML) | `doc_id`, `doc_url` |
| Google Docs | `update_document` | `doc_id`, `content` | `doc_url` |
| Gmail | `create_draft` | `to`, `subject`, `body` | `draft_id` |

---

## 7. LLM / Agent Layer

### Framework — LangChain

**LangChain** is used as the agent and orchestration framework. It fits this pipeline because:

| LangChain Capability | How It's Used Here |
|---|---|
| `langchain-google-genai` | First-class Gemini integration — no raw SDK boilerplate |
| `ChatPromptTemplate` | Manages system + user prompt pairs for clustering & summarisation |
| `PydanticOutputParser` | Parses LLM JSON output directly into `ClusterResult` / `PulseNote` Pydantic models |
| `LCEL` (LangChain Expression Language) | Composes `prompt | llm | parser` chains with one line |
| Built-in retry / backoff | `with_retry()` wraps any Runnable — handles `429 / 503` automatically |
| `LangGraph` (optional) | Models the full ingest → cluster → summarise → publish pipeline as a typed state graph |

---

### LangChain Pipeline Design

```
┌─────────────────────────────────────────────────────────────────┐
│                    LANGCHAIN AGENT PIPELINE                     │
│                                                                 │
│  reviews: List[CleanReview]                                     │
│        │                                                        │
│        ▼                                                        │
│  cluster_chain                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ChatPromptTemplate (system + user)                      │  │
│  │           │                                              │  │
│  │           ▼                                              │  │
│  │  ChatGoogleGenerativeAI(model="gemini-2.0-flash",        │  │
│  │                         temperature=0.3)                 │  │
│  │           │                                              │  │
│  │           ▼                                              │  │
│  │  PydanticOutputParser[ClusterResult]                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│        │                                                        │
│        ▼  themed clusters                                       │
│  summarise_chain                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ChatPromptTemplate (system + user)                      │  │
│  │           │                                              │  │
│  │           ▼                                              │  │
│  │  ChatGoogleGenerativeAI(model="gemini-2.0-flash",        │  │
│  │                         temperature=0.7)                 │  │
│  │           │                                              │  │
│  │           ▼                                              │  │
│  │  PydanticOutputParser[PulseNote]                         │  │
│  └──────────────────────────────────────────────────────────┘  │
│        │                                                        │
│        ▼  PulseNote                                             │
│  MCP tool calls (Docs + Gmail)                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Model
- **Provider:** Google Gemini via `langchain-google-genai`
- **Model:** `gemini-2.0-flash` (default) — fast, cost-effective for batch text
- **Fallback:** `gemini-1.5-pro` for complex clustering if flash underperforms

### LCEL Chain Pattern (Conceptual)

```python
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableRetry

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.3)
parser = PydanticOutputParser(pydantic_object=ClusterResult)

cluster_chain = (
    ChatPromptTemplate.from_messages([
        ("system", CLUSTER_SYSTEM_PROMPT),
        ("human", "{reviews_json}")
    ])
    | llm.with_retry(stop_after_attempt=3)   # automatic backoff
    | parser
)

result: ClusterResult = cluster_chain.invoke({"reviews_json": reviews_json})
```

### Prompt Templates (`prompts.py`)

#### Clustering Prompt
```
System: You are an expert product analyst. Cluster the following app reviews
        into AT MOST 5 themes. Return JSON matching the schema below.
        Themes must be from this list: {theme_list}. Be consistent.
        {format_instructions}

User: {reviews_json}
```

#### Summarisation Prompt
```
System: You are a concise product analyst writing a weekly pulse note.
        Given clustered review themes, generate a pulse note matching the
        schema below. Quotes must be verbatim and anonymised (no PII).
        Total words across quotes + action_ideas must be ≤ 250.
        {format_instructions}

User: {themed_clusters_json}
```

> `{format_instructions}` is injected automatically by `PydanticOutputParser.get_format_instructions()` — it tells the LLM the exact JSON schema expected.

### LangChain Call Settings

| Setting | Clustering | Summarisation |
|---|---|---|
| Temperature | `0.3` (deterministic) | `0.7` (creative) |
| Retries | 3 (exponential backoff) | 3 (exponential backoff) |
| Output parser | `PydanticOutputParser[ClusterResult]` | `PydanticOutputParser[PulseNote]` |
| Structured output | Via `format_instructions` in prompt | Via `format_instructions` in prompt |

### LangGraph (Optional Enhancement)

For a more robust, inspectable pipeline, the orchestration in `main.py` can be replaced with a **LangGraph state machine**:

```
[ingest] → [filter] → [cluster] → [summarise] → [publish_docs] → [draft_gmail]
```

- Each node is a pure function operating on a shared `PipelineState` TypedDict
- Edges can be conditional (e.g., skip Gmail if Docs fails)
- Built-in checkpointing allows resuming a failed run from any stage

---

## 8. Configuration & Secrets

### `.env` File
```env
# LLM
GEMINI_API_KEY=your_gemini_api_key_here

# Review ingestion
APP_ID=com.nextbillion.groww
WEEKS_BACK=10
MAX_THEMES=5

# Google Workspace (via MCP)
TARGET_EMAIL=your-email@example.com
GOOGLE_DOC_ID=                        # Leave blank to auto-create on first run

# Output
OUTPUT_DIR=./output
```

### `.env.example`
A committed `.env.example` (no real values) documents all required variables. The `.env` file itself is in `.gitignore`.

---

## 9. Error Handling & Resilience

| Stage | Failure Mode | Handling |
|---|---|---|
| **Ingest** | Network error / rate limit | Retry x3, exponential backoff |
| **Ingest** | 0 reviews returned | Hard abort — no pulse to generate |
| **Filter** | < 10 reviews after filter | Warning logged, pipeline continues |
| **Cluster** | LLM timeout / error | Retry x3; fallback to keyword heuristics |
| **Cluster** | > 5 themes returned | Merge smallest themes until ≤ 5 |
| **Summarise** | Word count > 250 | Re-prompt LLM with explicit trim instruction |
| **Docs MCP** | MCP call fails | Hard abort with actionable error message |
| **Gmail MCP** | MCP call fails | Soft warning; Docs step result still valid |

---

## 10. Security & Privacy

| Area | Measure |
|---|---|
| **PII Stripping** | `reviewer_name`, `reviewer_id`, `device` removed in `filter.py` before any LLM call |
| **Email masking** | Regex masks `user@domain.com` patterns in review text |
| **API Keys** | Stored in `.env` only; never logged or embedded in output artifacts |
| **MCP Auth** | OAuth tokens managed entirely by MCP servers — agent code never touches credentials |
| **Output artifacts** | Pulse notes and Doc content reviewed for PII before publishing |
| **Git hygiene** | `.env` in `.gitignore`; no secrets in commit history |

---

## 11. Scalability & Extension Points

| Extension | How to add |
|---|---|
| **Multi-app support** | Parameterise `APP_ID`; run pipeline per app |
| **Multi-language reviews** | Filter by language in `filter.py`; run separate LLM passes per language |
| **Slack delivery** | Add `slack_mcp.py` using Slack MCP server; post pulse as a message |
| **Scheduled runs** | Add a `cron` job or Cloud Scheduler trigger calling `main.py` |
| **Historical trending** | Save `PulseNote` JSON to `output/` and add a trend-diff report |
| **Multiple languages** | Filter by language in `filter.py`; run separate LLM passes per language |
| **Sentiment scoring** | Add sentiment analysis step between filter and cluster stages |

---

## 12. Tech Stack Summary

| Layer | Technology | Purpose |
|---|---|---|
| **Language** | Python 3.11+ | Primary implementation |
| **Review Source** | `google-play-scraper` | Fetch public Play Store reviews |
| **LLM** | Google Gemini (`gemini-2.0-flash`) | Clustering + summarisation |
| **Agent Framework** | **LangChain** (`langchain-core`, `langchain-google-genai`) | Prompt templates, LCEL chains, output parsers, retry wrappers |
| **Pipeline Graph** | **LangGraph** *(optional)* | Model pipeline as a typed state graph with checkpointing |
| **Docs Integration** | Google Docs MCP Server | Publish pulse to Google Docs |
| **Gmail Integration** | Gmail MCP Server | Create draft email |
| **MCP Client** | MCP Python SDK | Interface with MCP servers |
| **Config** | `python-dotenv` | Load `.env` variables |
| **Data validation** | `pydantic` | Validate LLM output schemas (also used by LangChain parsers) |
| **Scheduling** | `cron` / Cloud Scheduler | Weekly automated runs |

### Python Dependency Summary (`requirements.txt`)
```
# LangChain — agent framework
langchain-core>=0.2
langchain-google-genai>=1.0     # Gemini integration for LangChain
langgraph>=0.1                  # Optional: pipeline as state graph

# Google Play Store
google-play-scraper>=1.2

# MCP
mcp>=1.0

# Config & validation
python-dotenv>=1.0
pydantic>=2.0
```

---

## Repository Layout

```
Pulse-detector-/
├── ProblemStatement.md     # Project context & requirements
├── ProblemStatement.txt    # Original brief
├── architecture.md         # This file
├── README.md               # Quick-start guide
├── .env                    # Local secrets (gitignored)
├── .env.example            # Config template (committed)
├── .gitignore
├── requirements.txt
└── src/
    ├── main.py             # Orchestrator / pipeline entry point
    ├── ingest.py           # Pull & clean Play Store reviews
    ├── filter.py           # Filter, deduplicate, PII-strip
    ├── cluster.py          # LLM-based theme clustering
    ├── summarise.py        # Generate PulseNote from clusters
    ├── docs_mcp.py         # Google Docs MCP integration
    ├── gmail_mcp.py        # Gmail MCP integration
    ├── models.py           # Pydantic data models (RawReview, CleanReview, PulseNote)
    └── prompts.py          # LLM prompt templates
└── output/
    └── pulse_YYYY-MM-DD.json  # Local copy of each weekly pulse
```

---

*Last updated: 2026-09-05 · Pulse Detector v0.1*
