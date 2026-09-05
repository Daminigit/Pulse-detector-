# Evaluation Framework — Pulse Detector

> Structured evaluation criteria, scoring rubrics, and test protocols for every component and output of the Pulse Detector pipeline. Use this document during Phase 9 testing and for ongoing quality assessment of each weekly run.

---

## Table of Contents

1. [Evaluation Philosophy](#1-evaluation-philosophy)
2. [Eval Dimensions Overview](#2-eval-dimensions-overview)
3. [E1 — Ingestion Quality](#e1--ingestion-quality)
4. [E2 — Filter & Clean Quality](#e2--filter--clean-quality)
5. [E3 — Clustering Quality](#e3--clustering-quality)
6. [E4 — Pulse Note Quality (LLM Output)](#e4--pulse-note-quality-llm-output)
7. [E5 — Google Docs Output Quality](#e5--google-docs-output-quality)
8. [E6 — Gmail Draft Quality](#e6--gmail-draft-quality)
9. [E7 — End-to-End Pipeline Eval](#e7--end-to-end-pipeline-eval)
10. [E8 — Privacy & Compliance Eval](#e8--privacy--compliance-eval)
11. [E9 — Resilience & Error Handling Eval](#e9--resilience--error-handling-eval)
12. [Scoring Rubric & Grading](#12-scoring-rubric--grading)
13. [Eval Run Checklist](#13-eval-run-checklist)
14. [Regression Eval — Week-over-Week](#14-regression-eval--week-over-week)

---

## 1. Evaluation Philosophy

The Pulse Detector pipeline has two distinct evaluation targets:

| Target | What We Evaluate | Method |
|---|---|---|
| **Functional correctness** | Does the code do what it's supposed to? | Automated checks, assertions |
| **Output quality** | Is the pulse note useful, accurate, and trustworthy? | Human review, LLM-as-judge |

Because much of the output is LLM-generated, purely automated evaluation is insufficient. This framework combines:

- **Automated checks** — assertions on structure, length, schema, PII absence
- **Human review** — stakeholder readability, quote accuracy, action relevance
- **LLM-as-judge** — use a second Gemini call to score theme coherence and action specificity

---

## 2. Eval Dimensions Overview

| ID | Dimension | Type | Automatable |
|---|---|---|---|
| E1 | Ingestion Quality | Functional | ✅ Yes |
| E2 | Filter & Clean Quality | Functional | ✅ Yes |
| E3 | Clustering Quality | Functional + Quality | 🔶 Partial |
| E4 | Pulse Note Quality | Quality | 🔶 Partial |
| E5 | Google Docs Output | Functional + Quality | 🔶 Partial |
| E6 | Gmail Draft | Functional | ✅ Yes |
| E7 | End-to-End Pipeline | Functional | ✅ Yes |
| E8 | Privacy & Compliance | Functional | ✅ Yes |
| E9 | Resilience | Functional | ✅ Yes |

---

## E1 — Ingestion Quality

**Goal:** Verify the pipeline fetches the right reviews in the right quantity and time window.

### Automated Checks

| Check ID | Check | Pass Condition | Severity |
|---|---|---|---|
| E1-A01 | Review count | `len(raw_reviews) > 0` | 🔴 Critical |
| E1-A02 | Newest review date | `max(r.date for r in raw) <= date.today()` | 🟠 High |
| E1-A03 | Oldest review date | `min(r.date for r in raw) >= date.today() - timedelta(weeks=WEEKS_BACK)` | 🟠 High |
| E1-A04 | App ID match | All reviews belong to `com.nextbillion.groww` | 🔴 Critical |
| E1-A05 | Rating range | `all(1 <= r.rating <= 5 for r in raw)` | 🟠 High |
| E1-A06 | No empty texts | `all(r.text.strip() for r in raw)` — after filter | 🟡 Medium |
| E1-A07 | Retry on failure | `fetch_reviews` retries 3× on `ConnectionError` | 🟠 High |
| E1-A08 | Abort on 0 reviews | `SystemExit` raised with message if `len(raw) == 0` | 🔴 Critical |

### Metrics to Log

```
✅ Reviews fetched     : {N}
✅ Date range          : {oldest} → {newest}
✅ Avg raw rating      : {X.X} ★
✅ Scraper attempts    : {1–3}
```

---

## E2 — Filter & Clean Quality

**Goal:** Verify that the cleaning step produces high-signal, PII-free, well-formed reviews.

### Automated Checks

| Check ID | Check | Pass Condition | Severity |
|---|---|---|---|
| E2-A01 | PII fields stripped | `not hasattr(r, 'reviewer_name')` for all `CleanReview` | 🔴 Critical |
| E2-A02 | `reviewer_id` absent | `not hasattr(r, 'reviewer_id')` for all `CleanReview` | 🔴 Critical |
| E2-A03 | `device` absent | `not hasattr(r, 'device')` for all `CleanReview` | 🟠 High |
| E2-A04 | Email masked in text | No `r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b'` in any `text` | 🔴 Critical |
| E2-A05 | Phone masked in text | No `r'\+?\d[\d\s\-]{8,}\d'` in any `text` | 🟠 High |
| E2-A06 | UUID format for `id` | `all(UUID(r.id) for r in clean)` — valid UUID v4 | 🟠 High |
| E2-A07 | Deduplication | `len(clean) <= len(raw)` and no duplicate `text` hashes | 🟡 Medium |
| E2-A08 | Date filter applied | `all(r.date >= cutoff for r in clean)` | 🟠 High |
| E2-A09 | Non-empty text | `all(len(r.text.strip()) >= 10 for r in clean)` | 🟡 Medium |
| E2-A10 | Drop rate is reasonable | `len(clean) >= 0.3 * len(raw)` (< 70% drop rate) | 🟡 Medium |

### Metrics to Log

```
✅ Reviews after filter : {N} / {raw_N}  ({drop_pct}% dropped)
✅ PII emails masked    : {N}
✅ PII phones masked    : {N}
✅ Duplicates removed   : {N}
⚠️  Low signal warning  : {triggered | not triggered}
```

---

## E3 — Clustering Quality

**Goal:** Verify that themes are distinct, representative, well-labelled, and within the 5-theme limit.

### Automated Checks

| Check ID | Check | Pass Condition | Severity |
|---|---|---|---|
| E3-A01 | Theme count | `1 <= len(themes) <= 5` | 🔴 Critical |
| E3-A02 | All reviews assigned | `sum(len(v) for v in themes.values()) == len(clean)` | 🔴 Critical |
| E3-A03 | Valid theme labels | All keys in `themes` are from `THEMES` list | 🟠 High |
| E3-A04 | No theme is empty | `all(len(v) > 0 for v in themes.values())` | 🟠 High |
| E3-A05 | Fallback triggered | Heuristic fallback logged when LLM retries exhausted | 🟠 High |
| E3-A06 | Retry count logged | `cluster_attempts` is between 1 and 3 | 🟡 Medium |

### Human / LLM-as-Judge Checks

| Check ID | Check | Evaluator | Scoring |
|---|---|---|---|
| E3-H01 | **Theme distinctness** — themes cover meaningfully different topics | Human or LLM-judge | 0–3 scale |
| E3-H02 | **Theme label accuracy** — label matches the reviews assigned to it | Human review of 3 random reviews per theme | Pass / Fail |
| E3-H03 | **Theme coverage** — no major topic in the reviews is uncaptured | Human review | Pass / Fail |
| E3-H04 | **Theme balance** — no single theme dominates > 80% unless justified | Computed + human review | Pass / Warn |

### LLM-as-Judge Prompt (E3-H01, E3-H03)

```
System: You are evaluating the quality of theme clustering for a review analysis pipeline.
        Rate the following themes on two dimensions:
        1. Distinctness (0–3): Are all themes meaningfully different from each other?
        2. Coverage (0–3): Do the themes cover the main topics in the reviews?
        Return JSON: {"distinctness": N, "coverage": N, "feedback": "..."}

User: Themes identified: {theme_list}
      Sample reviews (3 per theme): {sample_reviews_json}
```

### Scoring Rubric — E3-H01 (Distinctness)

| Score | Meaning |
|---|---|
| 3 | All themes are clearly distinct; no overlap |
| 2 | Mostly distinct; 1–2 themes could be merged |
| 1 | Significant overlap between themes |
| 0 | Themes are essentially identical (all collapsed) |

### Metrics to Log

```
✅ Themes generated    : {N}
✅ Review coverage     : {N}/{total} assigned
✅ Largest theme       : "{label}" ({N} reviews, {pct}%)
✅ Smallest theme      : "{label}" ({N} reviews, {pct}%)
✅ LLM attempts        : {N}
✅ Fallback used       : {Yes | No}
```

---

## E4 — Pulse Note Quality (LLM Output)

**Goal:** Verify that the generated `PulseNote` is accurate, well-structured, within word limits, and genuinely useful.

### Automated Checks

| Check ID | Check | Pass Condition | Severity |
|---|---|---|---|
| E4-A01 | Exactly 3 top themes | `len(pulse.top_themes) == 3` | 🔴 Critical |
| E4-A02 | Exactly 3 quotes | `len(pulse.quotes) == 3` | 🔴 Critical |
| E4-A03 | Exactly 3 action ideas | `len(pulse.action_ideas) == 3` | 🔴 Critical |
| E4-A04 | Word count ≤ 250 | `word_count(quotes + action_ideas) <= 250` | 🔴 Critical |
| E4-A05 | No PII in quotes | No email/phone regex match in any quote | 🔴 Critical |
| E4-A06 | No PII in action ideas | No email/phone regex match in any action idea | 🔴 Critical |
| E4-A07 | Quotes are non-empty | `all(len(q.strip()) > 10 for q in pulse.quotes)` | 🟠 High |
| E4-A08 | Action ideas are non-empty | `all(len(a.strip()) > 20 for a in pulse.action_ideas)` | 🟠 High |
| E4-A09 | `avg_rating` is plausible | `1.0 <= pulse.avg_rating <= 5.0` | 🟡 Medium |
| E4-A10 | `week_range` is formatted | Matches pattern `MMM D – MMM D, YYYY` | 🟡 Medium |
| E4-A11 | `reviews_analysed` is correct | `pulse.reviews_analysed == len(clean_reviews)` | 🟡 Medium |
| E4-A12 | Top themes are from cluster | `all(t.label in themes for t in pulse.top_themes)` | 🟠 High |
| E4-A13 | Quotes exist in corpus | Each quote is a substring of at least one `CleanReview.text` | 🔴 Critical |

### Human / LLM-as-Judge Checks

| Check ID | Check | Evaluator | Scoring |
|---|---|---|---|
| E4-H01 | **Quote authenticity** — quotes read like genuine user language, not paraphrased | Human | Pass / Fail |
| E4-H02 | **Action idea specificity** — ideas are concrete and tied to a named theme | Human or LLM-judge | 0–3 scale |
| E4-H03 | **Action idea feasibility** — ideas could realistically be acted upon by a product team | Human | 0–3 scale |
| E4-H04 | **Pulse readability** — a non-technical stakeholder could read the pulse in < 2 min | Human | Pass / Fail |
| E4-H05 | **Theme ranking accuracy** — top 3 themes reflect the highest-volume concerns | Human vs. computed rank | Pass / Fail |

### LLM-as-Judge Prompt (E4-H02, E4-H03)

```
System: You are evaluating action ideas generated from a mobile app review analysis.
        Rate each action idea on:
        1. Specificity (0–3): Is it specific to an identified theme, not generic?
        2. Feasibility (0–3): Could a product team realistically act on this?
        Return JSON: [{"action": "...", "specificity": N, "feasibility": N}]

User: Themes analysed: {top_3_themes}
      Action ideas to evaluate:
      1. {action_1}
      2. {action_2}
      3. {action_3}
```

### Scoring Rubric — E4-H02 (Specificity)

| Score | Meaning |
|---|---|
| 3 | Directly references a theme and a concrete fix (e.g., "Add progress indicator to KYC step 3") |
| 2 | References a theme but fix is vague (e.g., "Improve KYC flow") |
| 1 | Generic suggestion not tied to any theme (e.g., "Improve the app") |
| 0 | Irrelevant or nonsensical |

### Scoring Rubric — E4-H03 (Feasibility)

| Score | Meaning |
|---|---|
| 3 | Team could pick this up in a sprint with clear scope |
| 2 | Feasible but needs further scoping |
| 1 | Vague or requires significant investigation |
| 0 | Not actionable (e.g., "Fix everything") |

### Metrics to Log

```
✅ Word count             : {N} / 250
✅ Quotes verified        : {N}/3 found in corpus
✅ Action specificity avg : {X.X} / 3
✅ Action feasibility avg : {X.X} / 3
✅ LLM re-prompt count    : {N} (0 = first attempt succeeded)
```

---

## E5 — Google Docs Output Quality

**Goal:** Verify the Google Doc is created correctly and presents the pulse in a readable, professional format.

### Automated Checks

| Check ID | Check | Pass Condition | Severity |
|---|---|---|---|
| E5-A01 | Doc URL returned | `doc_url` is non-null and starts with `https://docs.google.com` | 🔴 Critical |
| E5-A02 | Doc ID is valid | `doc_id` is non-empty string | 🔴 Critical |
| E5-A03 | MCP call succeeded | No exception raised from `create_document` / `update_document` | 🔴 Critical |
| E5-A04 | Doc URL accessible | HTTP GET on `doc_url` returns 200 (requires auth) | 🟡 Medium |

### Human Checks

| Check ID | Check | Evaluator |
|---|---|---|
| E5-H01 | Doc title matches `"Groww App — Weekly Pulse {week_range}"` | Human visual check |
| E5-H02 | All three sections present: Top Themes, What Users Are Saying, Action Ideas | Human visual check |
| E5-H03 | Headings render correctly (not raw Markdown `##`) | Human visual check |
| E5-H04 | No `[object Object]` or raw JSON visible in Doc | Human visual check |
| E5-H05 | Doc is readable on mobile (responsive formatting) | Human visual check |

### Metrics to Log

```
✅ Doc created/updated   : {created | updated}
✅ Doc ID                : {doc_id}
✅ Doc URL               : {doc_url}
✅ Render check          : {pass | manual review needed}
```

---

## E6 — Gmail Draft Quality

**Goal:** Verify the draft email is well-formed, addressed correctly, and contains the right content.

### Automated Checks

| Check ID | Check | Pass Condition | Severity |
|---|---|---|---|
| E6-A01 | Draft ID returned | `draft_id` is non-null | 🟠 High |
| E6-A02 | MCP call succeeded | No exception from `create_draft` (or soft-warned) | 🟠 High |
| E6-A03 | `TARGET_EMAIL` set | `TARGET_EMAIL` is a valid email format at startup | 🔴 Critical |
| E6-A04 | Subject contains week range | `week_range` string present in email subject | 🟡 Medium |
| E6-A05 | Doc URL in body | `doc_url` present in email body | 🟠 High |
| E6-A06 | Body non-empty | `len(email_body.strip()) > 50` | 🟡 Medium |
| E6-A07 | No raw `None` in body | `"None"` not present as string in email body | 🟠 High |

### Human Checks

| Check ID | Check | Evaluator |
|---|---|---|
| E6-H01 | Draft appears in Gmail Drafts folder | Human visual check |
| E6-H02 | Recipient address is correct | Human visual check |
| E6-H03 | Doc link is clickable and opens the correct document | Human click-test |
| E6-H04 | Email is readable without opening the Doc (summary sufficient) | Human readability check |

### Metrics to Log

```
✅ Draft created         : {Yes | Soft-failed}
✅ Draft ID              : {draft_id | N/A}
✅ Recipient             : {TARGET_EMAIL}
✅ Doc link in body      : {Yes | No}
```

---

## E7 — End-to-End Pipeline Eval

**Goal:** Verify the full pipeline runs correctly from trigger to output.

### Automated Checks

| Check ID | Check | Pass Condition | Severity |
|---|---|---|---|
| E7-A01 | Pipeline exit code | `python src/main.py` exits with code `0` | 🔴 Critical |
| E7-A02 | Total runtime | Pipeline completes in < 5 minutes | 🟠 High |
| E7-A03 | Output JSON saved | `output/pulse_YYYY-MM-DD*.json` exists post-run | 🟡 Medium |
| E7-A04 | Output JSON valid | `json.loads(output_file)` succeeds | 🟡 Medium |
| E7-A05 | All 6 stages logged | Console output shows all 6 stage messages | 🟡 Medium |
| E7-A06 | Doc URL printed | Final success message contains `https://docs.google.com` URL | 🟠 High |
| E7-A07 | No unhandled exceptions | No traceback in stdout/stderr | 🔴 Critical |
| E7-A08 | Idempotent re-run | Running pipeline twice produces 2 distinct output files | 🟡 Medium |

### Performance Benchmarks

| Stage | Expected Duration | Alert Threshold |
|---|---|---|
| Ingest | < 30 sec | > 60 sec |
| Filter | < 2 sec | > 10 sec |
| Cluster | < 60 sec | > 120 sec |
| Summarise | < 30 sec | > 60 sec |
| Docs MCP | < 15 sec | > 30 sec |
| Gmail MCP | < 10 sec | > 20 sec |
| **Total** | **< 3 min** | **> 5 min** |

### Metrics to Log

```
✅ Pipeline status       : {success | failed at stage N}
✅ Total duration        : {Xs}
✅ Stage durations       : ingest={X}s, filter={X}s, cluster={X}s, summarise={X}s, docs={X}s, gmail={X}s
✅ Output file           : {path}
✅ Doc URL               : {url}
```

---

## E8 — Privacy & Compliance Eval

**Goal:** Ensure no PII leaks into any output artifact — the LLM, the Google Doc, the email, or local files.

### Automated PII Scan

Run after pipeline completion across **all output surfaces**:

```python
import re, json

PII_PATTERNS = {
    "email":   r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone":   r"\+?\d[\d\s\-]{8,}\d",
    "pan":     r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b",   # Indian PAN card
    "aadhaar": r"\b\d{4}\s\d{4}\s\d{4}\b",          # Aadhaar number
}

def scan_for_pii(text: str) -> dict[str, list[str]]:
    return {k: re.findall(v, text) for k, v in PII_PATTERNS.items() if re.findall(v, text)}
```

| Surface | What to Scan | Expected Result |
|---|---|---|
| `CleanReview.text` | Email, phone patterns | All masked with `[email]` / `[phone]` |
| `PulseNote.quotes` | All PII patterns | Zero matches |
| `PulseNote.action_ideas` | All PII patterns | Zero matches |
| `output/pulse_*.json` | All PII patterns | Zero matches |
| Google Doc content | All PII patterns (manual) | Zero matches |
| Gmail draft body | All PII patterns (manual) | Zero matches |

### Compliance Checks

| Check ID | Check | Pass Condition | Severity |
|---|---|---|---|
| E8-A01 | No `reviewer_name` in any output | Grep outputs for any name field | 🔴 Critical |
| E8-A02 | No `reviewer_id` in any output | Grep outputs for any ID field | 🔴 Critical |
| E8-A03 | No email patterns in quotes | Regex scan on `pulse.quotes` | 🔴 Critical |
| E8-A04 | No phone patterns in quotes | Regex scan on `pulse.quotes` | 🟠 High |
| E8-A05 | `.env` not tracked by git | `git ls-files .env` returns empty | 🔴 Critical |
| E8-A06 | `output/` not tracked by git | `git ls-files output/` returns empty | 🟠 High |
| E8-A07 | API key not in any output file | Grep all output files for `GEMINI_API_KEY` value | 🔴 Critical |

---

## E9 — Resilience & Error Handling Eval

**Goal:** Verify the pipeline degrades gracefully under failure conditions, not catastrophically.

### Failure Injection Tests

| Test ID | Injected Failure | Expected Behaviour | Automated |
|---|---|---|---|
| E9-T01 | Mock scraper returns `[]` | `SystemExit` with clear message; no MCP calls | ✅ |
| E9-T02 | Mock scraper raises `ConnectionError` | Retry x3, then `SystemExit` | ✅ |
| E9-T03 | Mock LLM returns invalid JSON | `OutputParserException` caught; retry triggered | ✅ |
| E9-T04 | Mock LLM always returns 503 | Retries x3; heuristic fallback used; pulse generated | ✅ |
| E9-T05 | Mock LLM returns > 5 themes | Themes merged to ≤ 5; log entry present | ✅ |
| E9-T06 | Mock LLM returns 380 words | Re-prompt triggered; final count ≤ 250 | ✅ |
| E9-T07 | Mock Docs MCP raises error | Hard abort; Doc URL not printed | ✅ |
| E9-T08 | Mock Gmail MCP raises error | Soft warning; Doc URL still printed | ✅ |
| E9-T09 | `GOOGLE_DOC_ID` set to invalid ID | 404 caught; `create_document` fallback | ✅ |
| E9-T10 | Run with `WEEKS_BACK=0` | Startup validation error; pipeline not started | ✅ |
| E9-T11 | Run with `GEMINI_API_KEY=bad` | `AuthenticationError` caught; helpful message | ✅ |
| E9-T12 | Send `SIGINT` during LLM call | `KeyboardInterrupt` caught; stage N printed; exit | ✅ |

### Resilience Scoring

| Score | Meaning |
|---|---|
| All 12 tests pass | ✅ **Production-ready** |
| 10–11 tests pass | 🟡 **Good — minor gaps** |
| 7–9 tests pass | 🟠 **Needs work before use** |
| < 7 tests pass | 🔴 **Not ready** |

---

## 12. Scoring Rubric & Grading

### Per-Eval Section Score

Each eval section (E1–E9) is scored independently:

| Score | Label | Meaning |
|---|---|---|
| 5 | ✅ Excellent | All automated checks pass; human checks score ≥ 2.5/3 |
| 4 | 🟢 Good | All critical checks pass; 1–2 non-critical failures |
| 3 | 🟡 Acceptable | All critical checks pass; some quality concerns |
| 2 | 🟠 Needs Improvement | 1 critical check failing; major quality issues |
| 1 | 🔴 Failing | Multiple critical checks failing |
| 0 | ❌ Broken | Section does not run |

### Overall Pipeline Score

| Weight | Section | Max |
|---|---|---|
| 20% | E4 — Pulse Note Quality | 1.0 |
| 15% | E8 — Privacy & Compliance | 0.75 |
| 15% | E3 — Clustering Quality | 0.75 |
| 12% | E7 — End-to-End Pipeline | 0.60 |
| 12% | E9 — Resilience | 0.60 |
| 10% | E1 — Ingestion | 0.50 |
| 8% | E5 — Google Docs Output | 0.40 |
| 5% | E6 — Gmail Draft | 0.25 |
| 3% | E2 — Filter & Clean | 0.15 |
| **100%** | **Total** | **5.00** |

### Grade Thresholds

| Grade | Score | Meaning |
|---|---|---|
| **A** | 4.5 – 5.0 | Ship it — production quality |
| **B** | 3.5 – 4.4 | Good — minor gaps to address |
| **C** | 2.5 – 3.4 | Acceptable — known issues documented |
| **D** | 1.5 – 2.4 | Needs significant rework |
| **F** | < 1.5 | Do not use |

> **Minimum bar to ship:** Grade ≥ C AND all 🔴 Critical automated checks passing AND E8 score ≥ 4.

---

## 13. Eval Run Checklist

Run this checklist after every pipeline execution (Phase 9 and beyond):

### Pre-Run
- [ ] `.env` is populated with real keys
- [ ] MCP servers (Docs + Gmail) are running
- [ ] Previous `output/` JSON files noted for comparison
- [ ] Internet connectivity confirmed

### Automated Checks (run `python eval/run_checks.py`)
- [ ] E1 ingestion checks all pass
- [ ] E2 filter checks all pass
- [ ] E3 clustering automated checks all pass
- [ ] E4 automated checks all pass (word count, quote count, action count, PII scan)
- [ ] E5 Doc URL returned and non-null
- [ ] E6 draft ID returned (or soft warning logged)
- [ ] E7 exit code 0, runtime < 5 min, output file saved
- [ ] E8 PII scan clean across all surfaces

### Human Review (spend ~10 min)
- [ ] Open Google Doc — visually inspect formatting
- [ ] Read all 3 quotes — do they read as genuine? Any PII?
- [ ] Read all 3 action ideas — are they specific? Tied to themes?
- [ ] Open Gmail draft — correct subject? Doc link works?
- [ ] Does the pulse pass the "5-second scan" test for a busy exec?

### After Review
- [ ] Record scores in the **Eval Log** table below
- [ ] Flag any 🔴 Critical failures for immediate fix
- [ ] Commit updated eval log to git

---

## 14. Regression Eval — Week-over-Week

For ongoing runs, compare the current pulse to last week's to detect quality regressions.

### Regression Metrics

| Metric | How to Compute | Alert Condition |
|---|---|---|
| **Theme drift** | Jaccard similarity between this week's and last week's top-3 theme labels | < 0.3 (completely new themes — expected or bug?) |
| **Avg rating delta** | `abs(this_week.avg_rating - last_week.avg_rating)` | > 0.5 (sharp shift — worth flagging) |
| **Review volume delta** | `abs(this_N - last_N) / last_N` | > 50% change (unusual spike or drop) |
| **Word count stability** | `abs(this_wc - last_wc)` | > 100 words delta (quality inconsistency) |
| **Quote novelty** | % of quotes not seen in last week's pulse | < 100% means a quote was recycled |

### Eval Log (fill in each week)

| Run Date | Reviews | Avg ★ | Themes | Word Count | Quotes Verified | E4 Score | E8 Score | Overall Grade | Notes |
|---|---|---|---|---|---|---|---|---|---|
| _YYYY-MM-DD_ | — | — | — | — | —/3 | —/5 | —/5 | — | First run |
| | | | | | | | | | |
| | | | | | | | | | |

---

*Last updated: 2026-09-05 · Pulse Detector v0.1*
