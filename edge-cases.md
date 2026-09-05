# Edge Cases — Pulse Detector

> Comprehensive catalogue of corner scenarios, failure modes, and boundary conditions across every stage of the pipeline. Use this as a test checklist and a defensive coding reference.

---

## Table of Contents

1. [Review Ingestion (`ingest.py`)](#1-review-ingestion-ingestpy)
2. [Filter & Clean (`filter.py`)](#2-filter--clean-filterpy)
3. [Theme Clustering (`cluster.py`)](#3-theme-clustering-clusterpy)
4. [Pulse Summarisation (`summarise.py`)](#4-pulse-summarisation-summarisepy)
5. [Google Docs MCP (`docs_mcp.py`)](#5-google-docs-mcp-docs_mcppy)
6. [Gmail MCP (`gmail_mcp.py`)](#6-gmail-mcp-gmail_mcppy)
7. [Orchestrator (`main.py`)](#7-orchestrator-mainpy)
8. [Data Model Edge Cases](#8-data-model-edge-cases)
9. [Privacy & PII Edge Cases](#9-privacy--pii-edge-cases)
10. [LangChain / LLM Edge Cases](#10-langchain--llm-edge-cases)
11. [Configuration & Environment Edge Cases](#11-configuration--environment-edge-cases)
12. [Cross-Cutting / End-to-End Edge Cases](#12-cross-cutting--end-to-end-edge-cases)

**Status legend:** `⬜ Untested` · `✅ Handled` · `❌ Known gap` · `⏭️ Out of scope`

---

## 1. Review Ingestion (`ingest.py`)

### EC-I-01 · Zero reviews returned
| Attribute | Detail |
|---|---|
| **Scenario** | `google-play-scraper` returns an empty list (e.g., API temporarily blocked, app ID invalid) |
| **Risk** | Pipeline continues with no data, producing a meaningless or broken pulse |
| **Expected behaviour** | Hard abort with `SystemExit` and message: *"No reviews fetched. Cannot generate pulse."* |
| **Test** | Mock scraper to return `[]`; assert pipeline exits with non-zero code |
| **Status** | ⬜ |

---

### EC-I-02 · Scraper rate-limited or throttled (`429`)
| Attribute | Detail |
|---|---|
| **Scenario** | Play Store rate-limits the scraper mid-pagination |
| **Risk** | Only partial reviews fetched; themes skewed toward the first page |
| **Expected behaviour** | Retry x3 with exponential backoff; abort after 3 failures with count of reviews already fetched |
| **Test** | Mock scraper to raise `HTTPError(429)` on 2nd call; verify retry and eventual success |
| **Status** | ⬜ |

---

### EC-I-03 · Scraper returns reviews beyond the date window
| Attribute | Detail |
|---|---|
| **Scenario** | `google-play-scraper` returns reviews older than `WEEKS_BACK` (no server-side date filter) |
| **Risk** | Stale reviews distort theme distribution |
| **Expected behaviour** | Date-range filter in `filter.py` drops all reviews older than cutoff |
| **Test** | Include a review dated 6 months ago; assert it is absent from `CleanReview` list |
| **Status** | ⬜ |

---

### EC-I-04 · Duplicate reviews across paginated requests
| Attribute | Detail |
|---|---|
| **Scenario** | Same review appears in multiple pages (scraper pagination overlap) |
| **Risk** | Inflated review count; review quoted multiple times in pulse |
| **Expected behaviour** | Deduplicated by review text hash in `filter.py` |
| **Test** | Inject a duplicate review; assert `CleanReview` list length is deduplicated |
| **Status** | ⬜ |

---

### EC-I-05 · Network timeout / DNS failure
| Attribute | Detail |
|---|---|
| **Scenario** | Machine has no internet access when pipeline runs |
| **Risk** | Unhandled exception crashes pipeline with a cryptic traceback |
| **Expected behaviour** | Catch `ConnectionError` / `TimeoutError`; retry x3; abort with user-friendly message |
| **Test** | Run with network disabled; verify clean error message |
| **Status** | ⬜ |

---

### EC-I-06 · App ID is wrong or app delisted
| Attribute | Detail |
|---|---|
| **Scenario** | `APP_ID` env var contains a typo or the app has been removed from Play Store |
| **Risk** | Scraper returns `[]` or raises `NotFoundError` |
| **Expected behaviour** | Catch the error; print *"App not found: {APP_ID}"*; hard abort |
| **Test** | Set `APP_ID=com.invalid.app`; assert abort message contains app ID |
| **Status** | ⬜ |

---

### EC-I-07 · Very large review corpus (500+ reviews)
| Attribute | Detail |
|---|---|
| **Scenario** | App has hundreds of new reviews in the window (viral event, major release) |
| **Risk** | LLM prompt token limit exceeded when all texts are batched |
| **Expected behaviour** | Chunk reviews into batches of ≤ 100 before LLM call in `cluster.py` |
| **Test** | Generate 600 mock reviews; verify pipeline completes without token overflow error |
| **Status** | ⬜ |

---

### EC-I-08 · All reviews are in a non-English language
| Attribute | Detail |
|---|---|
| **Scenario** | Groww app has a spike of reviews in Hindi/Gujarati/Marathi only |
| **Risk** | Language filter drops all reviews → 0 clean reviews → pipeline aborts |
| **Expected behaviour** | Warn: *"All reviews filtered (language). Consider setting LANG_FILTER=None."*; abort gracefully |
| **Test** | Inject 20 Hindi-only reviews; assert warning is logged |
| **Status** | ⬜ |

---

## 2. Filter & Clean (`filter.py`)

### EC-F-01 · Fewer than 10 reviews after filtering
| Attribute | Detail |
|---|---|
| **Scenario** | Date + language filters leave < 10 reviews — very low statistical signal |
| **Risk** | Themes and quotes are unrepresentative; misleading pulse |
| **Expected behaviour** | Log `WARNING: Only {N} reviews after filtering. Pulse may not be representative.` Continue pipeline |
| **Test** | Input 5 reviews; verify warning is logged and pipeline continues |
| **Status** | ⬜ |

---

### EC-F-02 · Review with empty text body
| Attribute | Detail |
|---|---|
| **Scenario** | Reviewer submitted a star rating with no text (empty string or whitespace only) |
| **Risk** | Empty string passed to LLM; clustering prompt contains blank entries |
| **Expected behaviour** | Drop reviews with `text.strip() == ""`; log count of dropped reviews |
| **Test** | Include 3 blank-text reviews; assert they are absent from `CleanReview` list |
| **Status** | ⬜ |

---

### EC-F-03 · Review text is extremely long (> 2000 chars)
| Attribute | Detail |
|---|---|
| **Scenario** | A reviewer writes a very detailed multi-paragraph complaint |
| **Risk** | Single long review consumes disproportionate token budget |
| **Expected behaviour** | Truncate `text` to 500 chars in `CleanReview` with `text[:500] + "..."` |
| **Test** | Input review with 3000-char text; assert `CleanReview.text` length ≤ 503 |
| **Status** | ⬜ |

---

### EC-F-04 · Review text contains only emoji or special characters
| Attribute | Detail |
|---|---|
| **Scenario** | `"🔥🔥🔥"` or `"!!!!!!"` submitted as review text |
| **Risk** | LLM cannot extract meaningful theme signal; may produce garbage cluster |
| **Expected behaviour** | Filter out reviews where `len(text.strip()) < 10` after stripping non-alphanumeric |
| **Test** | Input emoji-only reviews; assert they are dropped |
| **Status** | ⬜ |

---

### EC-F-05 · PII in review text — email, phone number
| Attribute | Detail |
|---|---|
| **Scenario** | Reviewer writes: *"Contact me at john@gmail.com or +91-9876543210"* |
| **Risk** | PII reaches LLM and potentially appears verbatim in the pulse quote |
| **Expected behaviour** | Regex replaces `john@gmail.com` → `[email]` and `+91-9876543210` → `[phone]` |
| **Test** | Input review with email + phone; assert both are masked in `CleanReview.text` |
| **Status** | ⬜ |

---

### EC-F-06 · `reviewer_name` leaked into review text
| Attribute | Detail |
|---|---|
| **Scenario** | Reviewer self-identifies in text: *"— Priya Sharma, Bangalore"* |
| **Risk** | Name survives PII strip since it is in the text body, not a metadata field |
| **Expected behaviour** | This is a known limitation; document it. Text-body name extraction is out of scope for MVP. |
| **Test** | Verify `reviewer_name` field is stripped; name in text body is not auto-detected |
| **Status** | ⏭️ Out of scope for MVP |

---

### EC-F-07 · All reviews are 5-star (uniformly positive week)
| Attribute | Detail |
|---|---|
| **Scenario** | Groww had a great week — all 50 reviews are 5 ★ and very short |
| **Risk** | No negative themes; action ideas may be generic or trivial |
| **Expected behaviour** | Pipeline completes; LLM generates themes from positive signals; action ideas focus on "maintain / expand" |
| **Test** | Input 30 five-star reviews; assert `PulseNote` is generated without errors |
| **Status** | ⬜ |

---

### EC-F-08 · All reviews are 1-star (crisis week)
| Attribute | Detail |
|---|---|
| **Scenario** | A major outage generates 200 one-star reviews in a single week |
| **Risk** | All 5 themes become variants of the same problem (e.g., "app crash" x5) |
| **Expected behaviour** | Clustering merges near-duplicate themes; final clusters are meaningfully distinct |
| **Test** | Input 100 identical-topic 1-star reviews; assert ≤ 5 distinct, non-duplicate themes |
| **Status** | ⬜ |

---

## 3. Theme Clustering (`cluster.py`)

### EC-C-01 · LLM returns more than 5 themes
| Attribute | Detail |
|---|---|
| **Scenario** | Despite the prompt constraint, Gemini returns 6 or 7 theme labels |
| **Risk** | Violates the hard constraint of ≤ 5 themes |
| **Expected behaviour** | Merge smallest themes (by review count) until ≤ 5 remain; log merge actions |
| **Test** | Mock LLM to return 7 themes; assert output dict has ≤ 5 keys |
| **Status** | ⬜ |

---

### EC-C-02 · LLM returns only 1 theme
| Attribute | Detail |
|---|---|
| **Scenario** | LLM lumps all reviews into a single bucket (e.g., `"general_feedback"`) |
| **Risk** | Pulse has only 1 theme — fails to meet "top 3 themes" deliverable |
| **Expected behaviour** | Detect single-theme output; re-prompt with instruction to create more granular themes |
| **Test** | Mock LLM to return 1 theme; assert re-prompt is triggered |
| **Status** | ⬜ |

---

### EC-C-03 · LLM returns a theme label not in the allowed `THEMES` list
| Attribute | Detail |
|---|---|
| **Scenario** | LLM invents `"customer_service"` which is not in the predefined list |
| **Risk** | Downstream code keyed on `THEMES` list breaks |
| **Expected behaviour** | Map unknown label to the closest allowed theme using string similarity; log the remapping |
| **Test** | Mock LLM output with `"support"` label; assert it maps to nearest canonical theme |
| **Status** | ⬜ |

---

### EC-C-04 · LLM returns malformed JSON (not parseable)
| Attribute | Detail |
|---|---|
| **Scenario** | Gemini returns partial JSON or prose instead of the schema |
| **Risk** | `PydanticOutputParser` raises `OutputParserException`; pipeline crashes |
| **Expected behaviour** | LangChain's built-in `OutputFixingParser` or retry re-sends with the parse error as context |
| **Test** | Mock LLM to return `"Sorry, I cannot..."` text; assert retry is triggered |
| **Status** | ⬜ |

---

### EC-C-05 · LLM assigns a review to a theme that does not appear in `ClusterResult`
| Attribute | Detail |
|---|---|
| **Scenario** | `review_id → theme` map references a theme label not present in the allowed set |
| **Risk** | `KeyError` when building the `Dict[theme, List[CleanReview]]` |
| **Expected behaviour** | Validate every `review_id` maps to a valid theme after parsing; raise `ValueError` and re-cluster |
| **Test** | Inject invalid theme in mock response; assert re-cluster is triggered |
| **Status** | ⬜ |

---

### EC-C-06 · LLM omits some review IDs from the clustering response
| Attribute | Detail |
|---|---|
| **Scenario** | Response contains 80 out of 100 review assignments (truncated output) |
| **Risk** | 20 reviews are unassigned; distorted theme counts |
| **Expected behaviour** | Detect unassigned IDs; assign them to the largest theme as a fallback; log count |
| **Test** | Mock response missing 20 IDs; assert all reviews are assigned |
| **Status** | ⬜ |

---

### EC-C-07 · All retries exhausted; LLM clustering fails completely
| Attribute | Detail |
|---|---|
| **Scenario** | Network outage or sustained `503` from Gemini API; all 3 retries fail |
| **Risk** | Pipeline crashes with an unhandled exception |
| **Expected behaviour** | Fall back to keyword heuristic clustering (regex match against theme keywords); log degraded mode |
| **Test** | Mock LLM to always raise `503`; assert heuristic fallback is used and pipeline completes |
| **Status** | ⬜ |

---

### EC-C-08 · Token limit exceeded during batch LLM call
| Attribute | Detail |
|---|---|
| **Scenario** | All 500 reviews sent in one prompt exceed the model's context window |
| **Risk** | `InvalidArgument: Request payload size exceeds the limit` error |
| **Expected behaviour** | Split reviews into batches of 100; cluster per batch; merge results |
| **Test** | Input 600 reviews; assert prompt is batched and all reviews are assigned |
| **Status** | ⬜ |

---

## 4. Pulse Summarisation (`summarise.py`)

### EC-S-01 · Word count exceeds 250 after first generation
| Attribute | Detail |
|---|---|
| **Scenario** | LLM generates verbose quotes and action ideas totalling 320 words |
| **Risk** | Violates the ≤ 250 word constraint from the problem statement |
| **Expected behaviour** | Detect overcount; re-prompt with: *"Trim your response to ≤ 250 words total. Current count: 320."* Max 2 re-prompts |
| **Test** | Mock LLM to return long output on first call, short on second; assert word count ≤ 250 |
| **Status** | ⬜ |

---

### EC-S-02 · Word count still exceeds 250 after max re-prompts
| Attribute | Detail |
|---|---|
| **Scenario** | After 2 trim re-prompts, LLM still returns > 250 words |
| **Risk** | Either abort or publish an over-length pulse |
| **Expected behaviour** | Hard-truncate at word level as last resort; add marker `[truncated]` at end; log warning |
| **Test** | Mock LLM to always return 300 words; assert final output is truncated and marked |
| **Status** | ⬜ |

---

### EC-S-03 · Fewer than 3 themes to summarise
| Attribute | Detail |
|---|---|
| **Scenario** | Only 1 or 2 distinct themes emerged from clustering (very homogeneous review set) |
| **Risk** | Pulse template requires "top 3 themes" but only 1–2 exist |
| **Expected behaviour** | Include all available themes; fill missing slots with `N/A` placeholder and note in pulse |
| **Test** | Pass 2-theme cluster to `generate_pulse`; assert pulse has 2 themes with note |
| **Status** | ⬜ |

---

### EC-S-04 · LLM invents a quote (hallucination)
| Attribute | Detail |
|---|---|
| **Scenario** | LLM fabricates a review quote that doesn't exist in the input corpus |
| **Risk** | Violates the explicit constraint: *"Real user quotes — no invented wording"* |
| **Expected behaviour** | Post-generation, validate each quote against the original `CleanReview.text` corpus using substring match; flag or replace fabricated quotes |
| **Test** | Mock LLM to return a quote not present in any review; assert validation catches it |
| **Status** | ⬜ |

---

### EC-S-05 · LLM returns fewer than 3 quotes or action ideas
| Attribute | Detail |
|---|---|
| **Scenario** | LLM returns only 2 quotes in the JSON |
| **Risk** | `PulseNote.quotes` has length 2; violates deliverable spec |
| **Expected behaviour** | Validate list lengths post-parse; re-prompt with: *"You must provide exactly 3 quotes and 3 action ideas."* |
| **Test** | Mock LLM to return 2 quotes; assert re-prompt is triggered |
| **Status** | ⬜ |

---

### EC-S-06 · Action ideas are too generic
| Attribute | Detail |
|---|---|
| **Scenario** | LLM returns: *"Improve the app. Fix bugs. Better UX."* — not actionable |
| **Risk** | Low-value pulse that doesn't help stakeholders prioritise |
| **Expected behaviour** | Prompt engineering concern — system prompt must demand *specific, concrete* actions tied to theme names. Enforce in `SUMMARISE_SYSTEM_PROMPT`. |
| **Test** | Manual review of action ideas in test run; no automated detection |
| **Status** | ⬜ |

---

### EC-S-07 · `generated_at` timezone inconsistency
| Attribute | Detail |
|---|---|
| **Scenario** | `datetime.utcnow()` used on a machine in IST; displayed time is confusing |
| **Risk** | Stakeholders see UTC timestamp and are confused |
| **Expected behaviour** | Standardise to `datetime.now(timezone.utc)` with UTC label; document in pulse footer |
| **Test** | Assert `PulseNote.generated_at` is timezone-aware |
| **Status** | ⬜ |

---

## 5. Google Docs MCP (`docs_mcp.py`)

### EC-D-01 · MCP server not running / not reachable
| Attribute | Detail |
|---|---|
| **Scenario** | Google Docs MCP server process is not started before running the pipeline |
| **Risk** | `ConnectionRefusedError` or `MCPError`; pipeline crashes at stage 5 |
| **Expected behaviour** | Catch MCP connection error; abort with: *"Google Docs MCP server unreachable. Start it with: [command]"* |
| **Test** | Run pipeline without starting MCP server; assert helpful abort message |
| **Status** | ⬜ |

---

### EC-D-02 · `create_document` fails due to Google API quota
| Attribute | Detail |
|---|---|
| **Scenario** | Google Docs API quota exceeded for the day |
| **Risk** | MCP call returns error; Doc not created; pipeline continues to Gmail with no doc URL |
| **Expected behaviour** | Hard abort at Docs stage; do not proceed to Gmail with an empty doc URL |
| **Test** | Mock MCP to return quota error; assert pipeline aborts cleanly |
| **Status** | ⬜ |

---

### EC-D-03 · `GOOGLE_DOC_ID` set but doc no longer exists
| Attribute | Detail |
|---|---|
| **Scenario** | User deleted the Docs file after a previous run; `update_document` is called with a stale ID |
| **Risk** | MCP returns 404; update fails |
| **Expected behaviour** | Catch 404 on update; fall back to `create_document`; log new Doc ID for user to update `.env` |
| **Test** | Mock MCP `update_document` to return 404; assert fallback to `create_document` |
| **Status** | ⬜ |

---

### EC-D-04 · Pulse content contains Markdown not rendered by Docs
| Attribute | Detail |
|---|---|
| **Scenario** | MCP creates Doc but renders raw Markdown symbols (`**bold**`, `---`) as plain text |
| **Risk** | Doc looks unformatted and hard to scan |
| **Expected behaviour** | Either pass structured content via Docs API's native formatting (if MCP supports it) or document this limitation |
| **Test** | Inspect created Doc; verify headers and bold text render correctly |
| **Status** | ⬜ |

---

### EC-D-05 · Google Doc URL not returned by MCP
| Attribute | Detail |
|---|---|
| **Scenario** | MCP call succeeds but response does not include `doc_url` field |
| **Risk** | `None` passed to Gmail draft body; broken link |
| **Expected behaviour** | Reconstruct URL as `https://docs.google.com/document/d/{doc_id}/edit`; log warning |
| **Test** | Mock MCP to return `doc_id` but no `doc_url`; assert URL is reconstructed |
| **Status** | ⬜ |

---

### EC-D-06 · Pulse rendered as empty string
| Attribute | Detail |
|---|---|
| **Scenario** | Bug in `render_pulse_to_markdown()` returns an empty string |
| **Risk** | Empty Google Doc is created and linked in email |
| **Expected behaviour** | Validate rendered string is non-empty before MCP call; raise `ValueError` if empty |
| **Test** | Mock renderer to return `""`; assert `ValueError` is raised |
| **Status** | ⬜ |

---

## 6. Gmail MCP (`gmail_mcp.py`)

### EC-G-01 · Gmail MCP server not running
| Attribute | Detail |
|---|---|
| **Scenario** | Gmail MCP process not started |
| **Risk** | `ConnectionRefusedError`; pipeline crashes at stage 6 |
| **Expected behaviour** | Soft warning only (Gmail is non-critical vs. Docs): *"Gmail MCP unreachable. Draft not created. Doc URL: {url}"* |
| **Test** | Run without Gmail MCP; assert warning logged and Docs URL still printed |
| **Status** | ⬜ |

---

### EC-G-02 · `TARGET_EMAIL` not set in `.env`
| Attribute | Detail |
|---|---|
| **Scenario** | `TARGET_EMAIL` is blank or missing from `.env` |
| **Risk** | `create_draft` called with `to=""` — MCP rejects or sends to no one |
| **Expected behaviour** | Validate `TARGET_EMAIL` at startup; abort with: *"TARGET_EMAIL must be set in .env"* |
| **Test** | Run with empty `TARGET_EMAIL`; assert validation error at startup |
| **Status** | ⬜ |

---

### EC-G-03 · `TARGET_EMAIL` is malformed
| Attribute | Detail |
|---|---|
| **Scenario** | `TARGET_EMAIL=not-an-email` |
| **Risk** | Gmail API / MCP rejects the `to` field at runtime |
| **Expected behaviour** | Validate format with regex at startup; abort with helpful message |
| **Test** | Set `TARGET_EMAIL=invalid`; assert startup validation fails |
| **Status** | ⬜ |

---

### EC-G-04 · `doc_url` is `None` when Gmail draft is being composed
| Attribute | Detail |
|---|---|
| **Scenario** | Docs stage returned `None` for `doc_url` due to a silent failure |
| **Risk** | Draft email contains `"Full pulse document: None"` |
| **Expected behaviour** | Check `doc_url is not None` before drafting; if None, omit link section and add warning line |
| **Test** | Pass `doc_url=None` to `draft_gmail`; assert body does not contain `"None"` |
| **Status** | ⬜ |

---

### EC-G-05 · Pulse email body exceeds Gmail's size limit
| Attribute | Detail |
|---|---|
| **Scenario** | Inline pulse body is very long (unlikely given 250-word cap, but possible with headers) |
| **Risk** | MCP `create_draft` fails with payload-too-large error |
| **Expected behaviour** | Truncate inline body to 500 chars; always include Doc link as the primary content reference |
| **Test** | Construct 10,000-char body; assert it is truncated in draft |
| **Status** | ⬜ |

---

### EC-G-06 · Draft created but not visible in Gmail
| Attribute | Detail |
|---|---|
| **Scenario** | MCP returns `draft_id` but draft doesn't appear in Gmail UI |
| **Risk** | Silent failure — user doesn't know the draft failed |
| **Expected behaviour** | After `create_draft`, verify by calling `get_draft(draft_id)`; log confirmation or error |
| **Test** | Manual verification after test run |
| **Status** | ⬜ |

---

## 7. Orchestrator (`main.py`)

### EC-O-01 · Partial pipeline state on second run (no `GOOGLE_DOC_ID` set yet)
| Attribute | Detail |
|---|---|
| **Scenario** | First run creates a new Doc; user forgets to set `GOOGLE_DOC_ID` in `.env`; second run creates a duplicate Doc |
| **Risk** | Multiple orphaned Docs created every week |
| **Expected behaviour** | Print new `doc_id` prominently after first run; prompt user to add it to `.env`; warn on subsequent runs if `GOOGLE_DOC_ID` is blank |
| **Test** | Run twice without setting `GOOGLE_DOC_ID`; assert two different Doc IDs are printed |
| **Status** | ⬜ |

---

### EC-O-02 · Keyboard interrupt (`Ctrl+C`) mid-pipeline
| Attribute | Detail |
|---|---|
| **Scenario** | User cancels pipeline while LLM is mid-call or MCP is writing |
| **Risk** | Partial Doc created; incomplete state in output directory |
| **Expected behaviour** | `KeyboardInterrupt` caught at top level; print *"Pipeline cancelled at stage {N}. Partial output may exist at {path}."* |
| **Test** | Send `SIGINT` during pipeline; assert graceful exit message |
| **Status** | ⬜ |

---

### EC-O-03 · `.env` file missing entirely
| Attribute | Detail |
|---|---|
| **Scenario** | Repo cloned fresh; user runs `python src/main.py` without creating `.env` |
| **Risk** | `GEMINI_API_KEY` is `None`; LLM call fails with `AuthenticationError` |
| **Expected behaviour** | At startup, validate all required env vars; abort with list of missing vars and reference to `.env.example` |
| **Test** | Run with no `.env`; assert startup validation prints all missing keys |
| **Status** | ⬜ |

---

### EC-O-04 · `GEMINI_API_KEY` is invalid or expired
| Attribute | Detail |
|---|---|
| **Scenario** | API key is revoked or has incorrect value |
| **Risk** | `PermissionDenied` raised by LangChain on first LLM call |
| **Expected behaviour** | Catch `PermissionDenied` / `AuthenticationError`; abort with: *"Invalid GEMINI_API_KEY. Please check your .env."* |
| **Test** | Set `GEMINI_API_KEY=invalid`; assert auth error is caught cleanly |
| **Status** | ⬜ |

---

### EC-O-05 · Output directory does not exist
| Attribute | Detail |
|---|---|
| **Scenario** | `OUTPUT_DIR=./output` but `output/` was deleted or never created |
| **Risk** | `FileNotFoundError` when saving `pulse_YYYY-MM-DD.json` |
| **Expected behaviour** | Auto-create `OUTPUT_DIR` at startup with `os.makedirs(exist_ok=True)` |
| **Test** | Delete `output/`; run pipeline; assert directory is recreated and JSON saved |
| **Status** | ⬜ |

---

### EC-O-06 · Two pipeline runs on the same day overwrite the output file
| Attribute | Detail |
|---|---|
| **Scenario** | `output/pulse_2026-09-05.json` already exists; pipeline runs again |
| **Risk** | Previous run's output silently overwritten |
| **Expected behaviour** | Append timestamp to filename: `pulse_2026-09-05_143022.json`; or prompt user before overwriting |
| **Test** | Run pipeline twice on same day; assert two distinct output files exist |
| **Status** | ⬜ |

---

## 8. Data Model Edge Cases

### EC-M-01 · `rating` field is `None` or outside 1–5
| Attribute | Detail |
|---|---|
| **Scenario** | Scraper returns `None` or `0` for rating (data quality issue) |
| **Risk** | Pydantic validation fails; `RawReview` not created |
| **Expected behaviour** | Coerce `None` → skip review; coerce `0` → treat as `1`; log each coercion |
| **Test** | Input review with `rating=None`; assert it is skipped with log entry |
| **Status** | ⬜ |

---

### EC-M-02 · `date` field is `None` or unparseable
| Attribute | Detail |
|---|---|
| **Scenario** | Scraper returns date as string `"invalid-date"` |
| **Risk** | Pydantic `date` type raises `ValidationError` |
| **Expected behaviour** | Catch parse error; skip review with log: *"Skipping review with invalid date: {raw_date}"* |
| **Test** | Input review with `date="bad-date"`; assert it is skipped |
| **Status** | ⬜ |

---

### EC-M-03 · `PulseNote` serialisation to JSON fails
| Attribute | Detail |
|---|---|
| **Scenario** | `PulseNote` contains a non-serialisable field (e.g., raw `datetime` object without JSON encoder) |
| **Risk** | `TypeError` when calling `json.dumps(pulse.dict())` |
| **Expected behaviour** | Use `pulse.model_dump_json()` (Pydantic v2) which handles all native types correctly |
| **Test** | Serialise `PulseNote` with `model_dump_json()`; assert valid JSON string returned |
| **Status** | ⬜ |

---

## 9. Privacy & PII Edge Cases

### EC-P-01 · PII appears in LLM-generated action ideas
| Attribute | Detail |
|---|---|
| **Scenario** | LLM generates: *"Contact user priya@groww.in to resolve KYC issue"* |
| **Risk** | PII in output artifact (Google Doc, email); compliance violation |
| **Expected behaviour** | Run post-generation PII scan (email regex) on all `action_ideas`; mask or reject affected items |
| **Test** | Mock LLM to return email in action idea; assert it is masked in final `PulseNote` |
| **Status** | ⬜ |

---

### EC-P-02 · PII appears in LLM-generated quotes
| Attribute | Detail |
|---|---|
| **Scenario** | LLM selects a quote that contains a name not caught by the pre-LLM PII strip (text-body name) |
| **Risk** | Name appears in Google Doc and Gmail draft |
| **Expected behaviour** | Post-generation PII scan on each quote string; mask detected PII |
| **Test** | Include review with self-identified name in text; assert name masked in final quote |
| **Status** | ⬜ |

---

### EC-P-03 · `reviewer_id` used as `CleanReview.id`
| Attribute | Detail |
|---|---|
| **Scenario** | Developer mistakenly uses original `reviewer_id` as the UUID for `CleanReview` |
| **Risk** | PII (`reviewer_id`) propagated through entire pipeline |
| **Expected behaviour** | `CleanReview.id` must always be a freshly generated `uuid.uuid4()`; `reviewer_id` must be dropped before `CleanReview` construction |
| **Test** | Assert `CleanReview.id` is a valid UUID v4 format, not equal to any raw `reviewer_id` |
| **Status** | ⬜ |

---

### EC-P-04 · Output JSON file accidentally committed to git
| Attribute | Detail |
|---|---|
| **Scenario** | `output/pulse_*.json` files contain verbatim review quotes and are accidentally committed |
| **Risk** | Review data (even anonymised) stored in public git history |
| **Expected behaviour** | `output/` must be in `.gitignore`; enforce with pre-commit hook |
| **Test** | `git status` after a pipeline run; assert `output/*.json` is not tracked |
| **Status** | ⬜ |

---

## 10. LangChain / LLM Edge Cases

### EC-L-01 · Gemini model deprecated or renamed
| Attribute | Detail |
|---|---|
| **Scenario** | `gemini-2.0-flash` is deprecated; API returns `ModelNotFoundError` |
| **Risk** | Pipeline fails with cryptic model error |
| **Expected behaviour** | Catch `ModelNotFoundError`; abort with: *"Model '{MODEL}' not found. Update GEMINI_MODEL in .env."* |
| **Test** | Set `GEMINI_MODEL=gemini-fake`; assert helpful error message |
| **Status** | ⬜ |

---

### EC-L-02 · `PydanticOutputParser` format instructions too long for prompt
| Attribute | Detail |
|---|---|
| **Scenario** | Pydantic schema for `PulseNote` is complex; `format_instructions` blows up prompt token budget |
| **Risk** | Token limit exceeded before user content is even passed |
| **Expected behaviour** | Pre-check combined prompt length; trim `format_instructions` to key fields if necessary |
| **Test** | Log total prompt token count; assert it is < 80% of model's context limit |
| **Status** | ⬜ |

---

### EC-L-03 · LangChain version mismatch / breaking API change
| Attribute | Detail |
|---|---|
| **Scenario** | `langchain-core` is updated and `PydanticOutputParser` interface changes |
| **Risk** | `ImportError` or `AttributeError` at runtime |
| **Expected behaviour** | Pin exact versions in `requirements.txt`; document tested versions in README |
| **Test** | Run `pip check` to verify no dependency conflicts |
| **Status** | ⬜ |

---

### EC-L-04 · Gemini returns a safety-filtered response
| Attribute | Detail |
|---|---|
| **Scenario** | Review content triggers Gemini's safety filters (e.g., extreme language); response is blocked |
| **Risk** | `StopCandidateException` with `SAFETY` finish reason; LangChain chain raises exception |
| **Expected behaviour** | Catch safety exception; remove the offending review(s) from batch; re-cluster without them; log removed count |
| **Test** | Inject a review with hate speech; assert it is removed and pipeline completes |
| **Status** | ⬜ |

---

### EC-L-05 · LLM response is `null` / empty for structured output
| Attribute | Detail |
|---|---|
| **Scenario** | LLM returns `{"assignments": null}` instead of a populated dict |
| **Risk** | `None` propagated into theme clustering; `NoneType` errors downstream |
| **Expected behaviour** | Pydantic validator rejects `null` for a required field; triggers retry |
| **Test** | Mock LLM to return `{"assignments": null}`; assert Pydantic validation fails and retry fires |
| **Status** | ⬜ |

---

## 11. Configuration & Environment Edge Cases

### EC-E-01 · `WEEKS_BACK=0` or negative
| Attribute | Detail |
|---|---|
| **Scenario** | User sets `WEEKS_BACK=0` or `WEEKS_BACK=-3` |
| **Risk** | Date cutoff is today or in the future; all reviews filtered out |
| **Expected behaviour** | Validate `WEEKS_BACK >= 1` at startup; abort with helpful message |
| **Test** | Set `WEEKS_BACK=0`; assert startup validation error |
| **Status** | ⬜ |

---

### EC-E-02 · `MAX_THEMES` set to > 5 or < 1
| Attribute | Detail |
|---|---|
| **Scenario** | User sets `MAX_THEMES=10` bypassing the constraint |
| **Risk** | Violates problem statement constraint of ≤ 5 themes |
| **Expected behaviour** | Cap `MAX_THEMES` to `min(MAX_THEMES, 5)` silently, or abort if > 5 with warning |
| **Test** | Set `MAX_THEMES=10`; assert it is capped to 5 |
| **Status** | ⬜ |

---

### EC-E-03 · `GOOGLE_DOC_ID` contains whitespace or newline
| Attribute | Detail |
|---|---|
| **Scenario** | User copy-pastes Doc ID with trailing space: `GOOGLE_DOC_ID=abc123 ` |
| **Risk** | MCP call fails with 404 due to whitespace in ID |
| **Expected behaviour** | Strip whitespace from all env var values at load time |
| **Test** | Set `GOOGLE_DOC_ID=abc123 ` (trailing space); assert value is stripped before use |
| **Status** | ⬜ |

---

### EC-E-04 · Running pipeline on a machine with a different timezone
| Attribute | Detail |
|---|---|
| **Scenario** | CI/CD server is UTC; developer is in IST; date in output filename mismatches |
| **Risk** | `pulse_2026-09-04.json` created at 11pm IST but dated previous day in UTC |
| **Expected behaviour** | Use local date for filename; document timezone assumption |
| **Test** | Verify filename date matches local calendar date |
| **Status** | ⬜ |

---

## 12. Cross-Cutting / End-to-End Edge Cases

### EC-X-01 · First-ever run vs. subsequent runs
| Attribute | Detail |
|---|---|
| **Scenario** | No `GOOGLE_DOC_ID` on first run (create) vs. existing ID on subsequent (update) |
| **Risk** | Docs stage branches differently; update path untested on first run |
| **Expected behaviour** | Both paths tested independently; first run prints new Doc ID prominently |
| **Test** | Test `create` path with blank `GOOGLE_DOC_ID`; test `update` path with valid ID |
| **Status** | ⬜ |

---

### EC-X-02 · Pipeline run during a week with no new reviews at all
| Attribute | Detail |
|---|---|
| **Scenario** | Extremely quiet week — 0 reviews submitted to Play Store |
| **Risk** | Hard abort at ingest; no pulse generated; no doc or email |
| **Expected behaviour** | Abort with: *"No reviews found for the past {N} weeks. No pulse generated."*; do NOT create empty Docs or drafts |
| **Test** | Mock scraper to return `[]`; assert no MCP calls are made |
| **Status** | ⬜ |

---

### EC-X-03 · Docs succeeds but Gmail fails — partial success state
| Attribute | Detail |
|---|---|
| **Scenario** | Google Doc is created successfully; Gmail MCP fails |
| **Risk** | User doesn't know the Doc was created; may run again creating a duplicate |
| **Expected behaviour** | Print: *"⚠️ Gmail draft failed, but your Doc is ready: {doc_url}"*; save state to `output/` |
| **Test** | Mock Gmail MCP to fail; assert Doc URL is still printed and `output/` JSON is saved |
| **Status** | ⬜ |

---

### EC-X-04 · Pipeline output is identical to previous week's (no new signal)
| Attribute | Detail |
|---|---|
| **Scenario** | Reviews are identical week-over-week; themes and pulse are unchanged |
| **Risk** | Stakeholders get the same pulse twice with no differentiation |
| **Expected behaviour** | *(Enhancement)* Diff this week's pulse against last week's JSON; note unchanged themes in the Doc |
| **Status** | ⏭️ Post-MVP enhancement |

---

### EC-X-05 · Concurrent pipeline runs (double-trigger)
| Attribute | Detail |
|---|---|
| **Scenario** | Cron fires while a previous run is still in progress |
| **Risk** | Two runs both call `create_document`, creating duplicate Docs |
| **Expected behaviour** | Use a lock file (`output/.pipeline.lock`) to prevent concurrent runs |
| **Test** | Simulate two concurrent invocations; assert second exits with *"Pipeline already running"* |
| **Status** | ⬜ |

---

### EC-X-06 · System clock is wrong (far in the future or past)
| Attribute | Detail |
|---|---|
| **Scenario** | Machine clock is misconfigured; date filter uses `date.today()` incorrectly |
| **Risk** | All reviews are filtered out (clock in future) or no filtering happens (clock in past) |
| **Expected behaviour** | Document dependency on system clock; add sanity check: if `date.today()` is > 1 year from scraper's newest review date, warn |
| **Test** | Mock `date.today()` to a future date; assert warning is logged |
| **Status** | ⬜ |

---

## Summary Table

| ID | Stage | Severity | Status |
|---|---|---|---|
| EC-I-01 | Ingest | 🔴 Critical | ⬜ |
| EC-I-02 | Ingest | 🟠 High | ⬜ |
| EC-I-03 | Ingest | 🟠 High | ⬜ |
| EC-I-04 | Ingest | 🟡 Medium | ⬜ |
| EC-I-05 | Ingest | 🟠 High | ⬜ |
| EC-I-06 | Ingest | 🟠 High | ⬜ |
| EC-I-07 | Ingest | 🟠 High | ⬜ |
| EC-I-08 | Ingest | 🟡 Medium | ⬜ |
| EC-F-01 | Filter | 🟡 Medium | ⬜ |
| EC-F-02 | Filter | 🟡 Medium | ⬜ |
| EC-F-03 | Filter | 🟡 Medium | ⬜ |
| EC-F-04 | Filter | 🟢 Low | ⬜ |
| EC-F-05 | Filter | 🔴 Critical | ⬜ |
| EC-F-06 | Filter | 🟡 Medium | ⏭️ |
| EC-F-07 | Filter | 🟢 Low | ⬜ |
| EC-F-08 | Filter | 🟡 Medium | ⬜ |
| EC-C-01 | Cluster | 🔴 Critical | ⬜ |
| EC-C-02 | Cluster | 🟠 High | ⬜ |
| EC-C-03 | Cluster | 🟠 High | ⬜ |
| EC-C-04 | Cluster | 🟠 High | ⬜ |
| EC-C-05 | Cluster | 🟠 High | ⬜ |
| EC-C-06 | Cluster | 🟡 Medium | ⬜ |
| EC-C-07 | Cluster | 🔴 Critical | ⬜ |
| EC-C-08 | Cluster | 🟠 High | ⬜ |
| EC-S-01 | Summarise | 🔴 Critical | ⬜ |
| EC-S-02 | Summarise | 🔴 Critical | ⬜ |
| EC-S-03 | Summarise | 🟠 High | ⬜ |
| EC-S-04 | Summarise | 🔴 Critical | ⬜ |
| EC-S-05 | Summarise | 🟠 High | ⬜ |
| EC-S-06 | Summarise | 🟡 Medium | ⬜ |
| EC-S-07 | Summarise | 🟢 Low | ⬜ |
| EC-D-01 | Docs MCP | 🔴 Critical | ⬜ |
| EC-D-02 | Docs MCP | 🔴 Critical | ⬜ |
| EC-D-03 | Docs MCP | 🟠 High | ⬜ |
| EC-D-04 | Docs MCP | 🟡 Medium | ⬜ |
| EC-D-05 | Docs MCP | 🟡 Medium | ⬜ |
| EC-D-06 | Docs MCP | 🟠 High | ⬜ |
| EC-G-01 | Gmail MCP | 🟡 Medium | ⬜ |
| EC-G-02 | Gmail MCP | 🟠 High | ⬜ |
| EC-G-03 | Gmail MCP | 🟡 Medium | ⬜ |
| EC-G-04 | Gmail MCP | 🟠 High | ⬜ |
| EC-G-05 | Gmail MCP | 🟢 Low | ⬜ |
| EC-G-06 | Gmail MCP | 🟡 Medium | ⬜ |
| EC-O-01 | Orchestrator | 🟡 Medium | ⬜ |
| EC-O-02 | Orchestrator | 🟢 Low | ⬜ |
| EC-O-03 | Orchestrator | 🔴 Critical | ⬜ |
| EC-O-04 | Orchestrator | 🔴 Critical | ⬜ |
| EC-O-05 | Orchestrator | 🟡 Medium | ⬜ |
| EC-O-06 | Orchestrator | 🟢 Low | ⬜ |
| EC-M-01 | Models | 🟡 Medium | ⬜ |
| EC-M-02 | Models | 🟡 Medium | ⬜ |
| EC-M-03 | Models | 🟡 Medium | ⬜ |
| EC-P-01 | Privacy | 🔴 Critical | ⬜ |
| EC-P-02 | Privacy | 🔴 Critical | ⬜ |
| EC-P-03 | Privacy | 🔴 Critical | ⬜ |
| EC-P-04 | Privacy | 🟠 High | ⬜ |
| EC-L-01 | LangChain | 🟠 High | ⬜ |
| EC-L-02 | LangChain | 🟡 Medium | ⬜ |
| EC-L-03 | LangChain | 🟠 High | ⬜ |
| EC-L-04 | LangChain | 🟠 High | ⬜ |
| EC-L-05 | LangChain | 🟠 High | ⬜ |
| EC-E-01 | Config | 🟠 High | ⬜ |
| EC-E-02 | Config | 🟠 High | ⬜ |
| EC-E-03 | Config | 🟡 Medium | ⬜ |
| EC-E-04 | Config | 🟢 Low | ⬜ |
| EC-X-01 | End-to-End | 🟠 High | ⬜ |
| EC-X-02 | End-to-End | 🟠 High | ⬜ |
| EC-X-03 | End-to-End | 🟠 High | ⬜ |
| EC-X-04 | End-to-End | 🟢 Low | ⏭️ |
| EC-X-05 | End-to-End | 🟡 Medium | ⬜ |
| EC-X-06 | End-to-End | 🟢 Low | ⬜ |

**Total: 66 edge cases** · **🔴 Critical: 16** · **🟠 High: 26** · **🟡 Medium: 18** · **🟢 Low: 8** · **⏭️ Out of scope: 2**

---

*Last updated: 2026-09-05 · Pulse Detector v0.1*
