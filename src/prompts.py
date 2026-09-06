"""
src/prompts.py
──────────────
LLM prompt templates for both LangChain agents.

  CLUSTER_SYSTEM_PROMPT  → used by cluster.py   (P3)
  SUMMARISE_SYSTEM_PROMPT → used by summarise.py (P4)
  THEMES                 → canonical theme labels (shared)
"""

# ── Canonical theme list ──────────────────────────────────────────────────────
# Every review MUST be assigned to one of these labels.
# The labels are snake_case; display_name mapping is in cluster.py.

THEMES = [
    "onboarding_kyc",
    "payments_transactions",
    "app_performance",
    "portfolio_statements",
    "withdrawals_redemptions",
]

THEME_DISPLAY = {
    "onboarding_kyc":           "Onboarding & KYC",
    "payments_transactions":    "Payments & Transactions",
    "app_performance":          "App Performance",
    "portfolio_statements":     "Portfolio & Statements",
    "withdrawals_redemptions":  "Withdrawals & Redemptions",
}

# ── Clustering prompt ─────────────────────────────────────────────────────────
# Variables injected at runtime:
#   {theme_list}          — comma-separated valid theme labels
#   {format_instructions} — PydanticOutputParser format instructions
#   {reviews_json}        — JSON array of {id, rating, text} objects

CLUSTER_SYSTEM_PROMPT = """\
You are a product-analytics assistant. Your task is to classify user reviews \
of the Groww investment app into exactly one theme per review.

ALLOWED THEMES (use these labels exactly, no others):
{theme_list}

RULES:
1. Assign EVERY review to exactly one theme label from the allowed list.
2. Do NOT invent new theme labels.
3. If a review touches multiple themes, pick the most prominent one.
4. Return ONLY valid JSON — no prose, no markdown fences.

{format_instructions}
"""

# ── Summarisation prompt ──────────────────────────────────────────────────────
# Variables injected at runtime:
#   {week_range}          — e.g. "Aug 25 – Sep 05, 2026"
#   {reviews_analysed}    — total count of clean reviews
#   {avg_rating}          — average star rating (1 decimal)
#   {format_instructions} — PydanticOutputParser format instructions
#   {clusters_json}       — JSON: list of {theme_label, display_name, count, pct, sample_texts[]}

SUMMARISE_SYSTEM_PROMPT = """\
You are a concise product-analytics writer. Generate a weekly PulseNote for \
the Groww investment app based on the themed review clusters below.

CONTEXT:
  Week      : {week_range}
  Reviews   : {reviews_analysed} total · avg ★{avg_rating}

RULES:
1. top_themes: include the top 3 themes by review count (already provided).
2. quotes: pick exactly 3 verbatim sentences from the sample_texts — \
choose the most specific, actionable ones. Never paraphrase.
3. action_ideas: write exactly 3 concrete, theme-grounded recommendations \
a PM or engineer could act on within a sprint.
4. TOTAL word count across quotes + action_ideas MUST be ≤ 250 words.
5. Do NOT include any PII, reviewer names, or review IDs.
6. Return ONLY valid JSON — no prose, no markdown fences.

{format_instructions}
"""
