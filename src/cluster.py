"""
src/cluster.py
──────────────
LangChain LCEL clustering agent.

Groups CleanReview objects into ≤ 5 named themes using Gemini.

Public API:
    cluster_themes(reviews) -> Dict[str, List[CleanReview]]
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List

from dotenv import load_dotenv
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from src.models import CleanReview, ClusterResult, Theme
from src.prompts import CLUSTER_SYSTEM_PROMPT, THEMES, THEME_DISPLAY

load_dotenv()
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_BATCH_SIZE  = 50    # reviews per LLM call (safe for Gemini context window)
_MAX_THEMES  = 5
_MODEL       = "gemini-2.0-flash"
_TEMPERATURE = 0.3


# ── LangChain chain setup ─────────────────────────────────────────────────────

def _build_chain():
    """Build the LCEL cluster chain (lazy — call once per run)."""
    parser = PydanticOutputParser(pydantic_object=ClusterResult)

    prompt = ChatPromptTemplate.from_messages([
        ("system", CLUSTER_SYSTEM_PROMPT),
        ("human",  "{reviews_json}"),
    ])

    llm = ChatGoogleGenerativeAI(
        model=_MODEL,
        temperature=_TEMPERATURE,
        google_api_key=os.getenv("GEMINI_API_KEY"),
    ).with_retry(stop_after_attempt=3)

    return prompt | llm | parser, parser


# ── Public function ───────────────────────────────────────────────────────────

def cluster_themes(reviews: List[CleanReview]) -> Dict[str, List[CleanReview]]:
    """
    Group CleanReview objects into ≤ 5 named themes using Gemini.

    Steps:
      1. Split reviews into batches of _BATCH_SIZE.
      2. Run each batch through the LCEL chain → ClusterResult.
      3. Merge all batch ClusterResults into a single assignment map.
      4. Enforce _MAX_THEMES cap (merge smallest theme into nearest neighbour).
      5. Tag each CleanReview.theme and group into Dict[theme, reviews].
      6. Falls back to keyword heuristic if LLM chain fails.

    Returns:
        Dict[theme_label, List[CleanReview]] — keys are valid THEMES labels.
    """
    if not reviews:
        raise ValueError("No reviews to cluster.")

    log.info("Clustering %d reviews into ≤ %d themes…", len(reviews), _MAX_THEMES)

    try:
        assignments = _llm_cluster(reviews)
    except Exception as exc:       # noqa: BLE001
        log.warning("LLM clustering failed (%s). Falling back to keyword heuristic.", exc)
        assignments = _keyword_fallback(reviews)

    # Tag each review with its theme
    for review in reviews:
        review.theme = assignments.get(review.id, THEMES[0])

    # Group by theme
    grouped: Dict[str, List[CleanReview]] = {t: [] for t in THEMES}
    for review in reviews:
        grouped.setdefault(review.theme, []).append(review)

    # Remove empty themes
    grouped = {k: v for k, v in grouped.items() if v}

    # Enforce 5-theme cap
    grouped = _enforce_theme_cap(grouped)

    _log_cluster_stats(grouped, len(reviews))
    return grouped


# ── LLM clustering ────────────────────────────────────────────────────────────

def _llm_cluster(reviews: List[CleanReview]) -> Dict[str, str]:
    """Call Gemini in batches; return merged {review_id: theme_label} dict."""
    chain, parser = _build_chain()
    theme_list    = ", ".join(THEMES)
    format_instr  = parser.get_format_instructions()

    all_assignments: Dict[str, str] = {}

    batches = [reviews[i:i+_BATCH_SIZE] for i in range(0, len(reviews), _BATCH_SIZE)]
    log.info("Processing %d batch(es) of ≤ %d reviews…", len(batches), _BATCH_SIZE)

    for idx, batch in enumerate(batches, 1):
        reviews_json = json.dumps(
            [{"id": r.id, "rating": r.rating, "text": r.text} for r in batch],
            ensure_ascii=False,
        )
        log.info("  Batch %d/%d (%d reviews)…", idx, len(batches), len(batch))

        result: ClusterResult = chain.invoke({
            "theme_list":          theme_list,
            "format_instructions": format_instr,
            "reviews_json":        reviews_json,
        })

        # Validate: only allowed labels
        for review_id, label in result.assignments.items():
            if label not in THEMES:
                log.warning("Unknown theme '%s' returned — remapping to '%s'", label, THEMES[0])
                result.assignments[review_id] = THEMES[0]

        all_assignments.update(result.assignments)
        log.info("  Batch %d done. Running total: %d assignments.", idx, len(all_assignments))

    # Any reviews not in the LLM response get the fallback theme
    for r in reviews:
        if r.id not in all_assignments:
            log.warning("Review %s not assigned by LLM — using fallback theme.", r.id)
            all_assignments[r.id] = _keyword_theme(r.text)

    return all_assignments


# ── Keyword-heuristic fallback ────────────────────────────────────────────────

_KEYWORD_MAP: Dict[str, List[str]] = {
    "onboarding_kyc":          ["kyc", "onboard", "verification", "document", "account open", "aadhar", "pan"],
    "payments_transactions":   ["payment", "upi", "transaction", "failed", "debit", "bank", "neft", "imps"],
    "app_performance":         ["crash", "slow", "lag", "bug", "freeze", "glitch", "load", "error", "update"],
    "portfolio_statements":    ["portfolio", "statement", "returns", "holding", "pl", "gain", "loss", "nav", "chart"],
    "withdrawals_redemptions": ["withdraw", "redemption", "redeem", "money", "stuck", "pending", "fund", "sip"],
}


def _keyword_theme(text: str) -> str:
    """Return best-matching theme label via keyword scoring."""
    text_lower = text.lower()
    scores = {theme: sum(1 for kw in kws if kw in text_lower)
              for theme, kws in _KEYWORD_MAP.items()}
    best = max(scores, key=lambda t: scores[t])
    return best if scores[best] > 0 else THEMES[2]   # default: app_performance


def _keyword_fallback(reviews: List[CleanReview]) -> Dict[str, str]:
    """Full keyword-heuristic fallback when LLM is unavailable."""
    log.info("Using keyword fallback for %d reviews.", len(reviews))
    return {r.id: _keyword_theme(r.text) for r in reviews}


# ── Theme-cap enforcement ─────────────────────────────────────────────────────

def _enforce_theme_cap(grouped: Dict[str, List[CleanReview]]) -> Dict[str, List[CleanReview]]:
    """Merge the smallest theme into its nearest allowed neighbour until ≤ 5 themes remain."""
    while len(grouped) > _MAX_THEMES:
        smallest = min(grouped, key=lambda t: len(grouped[t]))
        # Pick the next-smallest as merge target
        others   = [t for t in grouped if t != smallest]
        target   = min(others, key=lambda t: len(grouped[t]))
        log.info("Merging theme '%s' (%d reviews) into '%s'.", smallest, len(grouped[smallest]), target)
        for review in grouped[smallest]:
            review.theme = target
        grouped[target].extend(grouped.pop(smallest))
    return grouped


# ── Logging helper ────────────────────────────────────────────────────────────

def _log_cluster_stats(grouped: Dict[str, List[CleanReview]], total: int) -> None:
    log.info("✅ Clustering complete — %d themes:", len(grouped))
    for label, reviews in sorted(grouped.items(), key=lambda x: -len(x[1])):
        display = THEME_DISPLAY.get(label, label)
        pct = 100 * len(reviews) / total if total else 0
        log.info("   %-30s  %3d reviews  (%.1f%%)", display, len(reviews), pct)


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    import json as _json
    data = _json.loads(Path("output/clean_reviews_2026-09-06.json").read_text())

    from src.models import CleanReview as _CR
    from datetime import date as _date
    reviews = [_CR(**{**r, "date": _date.fromisoformat(r["date"])}) for r in data]

    print(f"\n🔀 Clustering {len(reviews)} reviews…\n")
    grouped = cluster_themes(reviews)

    print("\n📊 Results:")
    total = len(reviews)
    for theme, revs in sorted(grouped.items(), key=lambda x: -len(x[1])):
        display = THEME_DISPLAY.get(theme, theme)
        pct = 100 * len(revs) / total
        avg = sum(r.rating for r in revs) / len(revs)
        print(f"  {display:<35} {len(revs):>3} reviews  ({pct:.1f}%)  avg ★{avg:.1f}")

    # Verify all exit criteria
    all_ids   = {r.id for r in reviews}
    assigned  = {r.id for revs in grouped.values() for r in revs}
    missing   = all_ids - assigned
    bad_labels = [k for k in grouped if k not in THEMES]
    print(f"\n✅ All reviews assigned   : {len(missing) == 0} (missing: {len(missing)})")
    print(f"✅ All labels valid       : {len(bad_labels) == 0} (bad: {bad_labels})")
    print(f"✅ Theme count ≤ 5        : {len(grouped) <= 5} (got: {len(grouped)})")
