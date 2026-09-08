"""
src/summarise.py
────────────────
LangChain LCEL summarisation agent.

Takes the clustered Dict[theme, List[CleanReview]] from cluster.py and
generates a structured PulseNote using Groq (openai/gpt-oss-120b).

Public API:
    generate_pulse(grouped, total_reviews) -> PulseNote
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from src.models import CleanReview, PulseNote, Theme
from src.prompts import SUMMARISE_SYSTEM_PROMPT, THEME_DISPLAY

load_dotenv()
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_MODEL            = "gemini-2.0-flash"   # Gemini for summarisation (P4)
_TEMPERATURE      = 0.7    # higher for creative, grounded action ideas
_TOP_N_THEMES     = 3      # only top 3 themes passed to the LLM
_SAMPLE_PER_THEME = 8      # representative reviews per theme sent in prompt
_MAX_WORDS        = 250
_MAX_TRIM_RETRIES = 2


# ── Public function ────────────────────────────────────────────────────────────

def generate_pulse(
    grouped: Dict[str, List[CleanReview]],
    total_reviews: int,
    output_dir: str = "./output",
) -> PulseNote:
    """
    Generate a PulseNote from themed review clusters.

    Steps:
      1. Rank themes by review count; keep top 3.
      2. Serialise sample texts per theme for the prompt.
      3. Invoke summarise_chain → PulseNote.
      4. Validate ≤ 250 words; re-prompt if exceeded.
      5. Save to output/pulse_YYYY-MM-DD.json.

    Returns:
        PulseNote — the final weekly pulse deliverable.
    """
    if not grouped:
        raise ValueError("No clustered reviews to summarise.")

    # ── 1. Select top 3 themes ─────────────────────────────────────────────
    ranked = sorted(grouped.items(), key=lambda x: -len(x[1]))
    top3   = ranked[:_TOP_N_THEMES]

    # ── 2. Build Theme objects & serialise clusters for prompt ─────────────
    theme_objects: List[Theme] = []
    clusters_payload: List[dict] = []

    for label, reviews in top3:
        count = len(reviews)
        pct   = round(100 * count / total_reviews, 1) if total_reviews else 0.0
        theme_objects.append(Theme(
            label=label,
            display_name=THEME_DISPLAY.get(label, label),
            count=count,
            pct=pct,
        ))
        # Pick a diverse sample: spread across rating values
        sample = _pick_sample(reviews, n=_SAMPLE_PER_THEME)
        clusters_payload.append({
            "theme_label":  label,
            "display_name": THEME_DISPLAY.get(label, label),
            "count":        count,
            "pct":          pct,
            "sample_texts": [r.text for r in sample],
        })

    # ── 3. Compute metadata ────────────────────────────────────────────────
    all_reviews  = [r for revs in grouped.values() for r in revs]
    avg_rating   = round(sum(r.rating for r in all_reviews) / len(all_reviews), 1)
    week_range   = _week_range_str()
    clusters_json = json.dumps(clusters_payload, ensure_ascii=False, indent=2)

    # ── 4. Invoke LLM chain ────────────────────────────────────────────────
    pulse = _invoke_chain(
        week_range=week_range,
        reviews_analysed=total_reviews,
        avg_rating=avg_rating,
        top_themes=theme_objects,
        clusters_json=clusters_json,
    )

    # ── 5. Word-count guard ────────────────────────────────────────────────
    for attempt in range(1, _MAX_TRIM_RETRIES + 1):
        wc = pulse.word_count()
        if wc <= _MAX_WORDS:
            break
        log.warning(
            "PulseNote word count %d > %d — re-prompting (attempt %d/%d)…",
            wc, _MAX_WORDS, attempt, _MAX_TRIM_RETRIES,
        )
        pulse = _invoke_chain(
            week_range=week_range,
            reviews_analysed=total_reviews,
            avg_rating=avg_rating,
            top_themes=theme_objects,
            clusters_json=clusters_json,
            trim_instruction=(
                f"IMPORTANT: The previous response was {wc} words. "
                f"You MUST stay strictly under {_MAX_WORDS} words total "
                f"across quotes + action_ideas. Be concise."
            ),
        )

    # ── 6. Persist ─────────────────────────────────────────────────────────
    _save_pulse(pulse, output_dir)

    return pulse


# ── LangChain chain ───────────────────────────────────────────────────────────

def _invoke_chain(
    *,
    week_range: str,
    reviews_analysed: int,
    avg_rating: float,
    top_themes: List[Theme],
    clusters_json: str,
    trim_instruction: str = "",
) -> PulseNote:
    """Build and invoke the LCEL summarise chain; return parsed PulseNote."""
    parser = PydanticOutputParser(pydantic_object=PulseNote)

    system_msg = SUMMARISE_SYSTEM_PROMPT
    if trim_instruction:
        system_msg = trim_instruction + "\n\n" + system_msg

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("human",  "{clusters_json}"),
    ])

    llm = ChatGoogleGenerativeAI(
        model=_MODEL,
        temperature=_TEMPERATURE,
        google_api_key=os.getenv("GEMINI_API_KEY"),
    ).with_retry(stop_after_attempt=3)

    chain = prompt | llm | parser

    return chain.invoke({
        "week_range":          week_range,
        "reviews_analysed":    reviews_analysed,
        "avg_rating":          f"{avg_rating:.1f}",
        "format_instructions": parser.get_format_instructions(),
        "clusters_json":       clusters_json,
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pick_sample(reviews: List[CleanReview], n: int) -> List[CleanReview]:
    """Pick n representative reviews spread across rating bands 1–5."""
    by_rating: Dict[int, List[CleanReview]] = {}
    for r in reviews:
        by_rating.setdefault(r.rating, []).append(r)

    sample: List[CleanReview] = []
    # Round-robin across rating bands, low ratings first (more signal)
    bands = sorted(by_rating.keys())
    idx   = {b: 0 for b in bands}
    while len(sample) < n:
        added = False
        for band in bands:
            lst = by_rating[band]
            if idx[band] < len(lst) and len(sample) < n:
                sample.append(lst[idx[band]])
                idx[band] += 1
                added = True
        if not added:
            break
    return sample


def _week_range_str() -> str:
    """Return a human-readable date range for the current week window."""
    today = date.today()
    # Approximate: 10 weeks back to today
    from datetime import timedelta
    start = today - timedelta(weeks=10)
    return f"{start.strftime('%b %d')} – {today.strftime('%b %d, %Y')}"


def _save_pulse(pulse: PulseNote, output_dir: str) -> None:
    """Persist the PulseNote to output/pulse_YYYY-MM-DD.json."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"pulse_{date.today()}.json"
    path     = Path(output_dir) / filename

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(pulse.model_dump(mode="json"), fh, indent=2, default=str)

    log.info("💾 PulseNote saved → %s", path)


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    # ── Load clean reviews from disk ──────────────────────────────────────
    import json as _json
    from datetime import date as _date

    review_file = sorted(Path("output").glob("clean_reviews_*.json"))[-1]
    log.info("Loading reviews from %s", review_file)
    data = _json.loads(review_file.read_text())
    from src.models import CleanReview as _CR
    reviews = [_CR(**{**r, "date": _date.fromisoformat(r["date"])}) for r in data]

    # ── Cluster ───────────────────────────────────────────────────────────
    from src.cluster import cluster_themes
    print(f"\n🔀 Clustering {len(reviews)} reviews (keyword fallback for speed)…")
    from src.cluster import _keyword_fallback
    assignments = _keyword_fallback(reviews)
    for r in reviews:
        r.theme = assignments[r.id]
    grouped: Dict[str, List[_CR]] = {}
    for r in reviews:
        grouped.setdefault(r.theme, []).append(r)

    # ── Summarise ─────────────────────────────────────────────────────────
    print(f"\n📝 Generating PulseNote via Groq ({_MODEL})…\n")
    pulse = generate_pulse(grouped, total_reviews=len(reviews), output_dir="./output")

    # ── Print results ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📋 PULSE NOTE — {pulse.week_range}")
    print(f"{'='*60}")
    print(f"Reviews analysed : {pulse.reviews_analysed}")
    print(f"Avg rating       : ★{pulse.avg_rating}")
    print(f"\n🏷️  Top Themes:")
    for t in pulse.top_themes:
        print(f"  {t.display_name:<35} {t.count:>3} reviews  ({t.pct:.1f}%)")
    print(f"\n💬 Quotes:")
    for i, q in enumerate(pulse.quotes, 1):
        print(f"  {i}. {q}")
    print(f"\n💡 Action Ideas:")
    for i, a in enumerate(pulse.action_ideas, 1):
        print(f"  {i}. {a}")
    wc = pulse.word_count()
    print(f"\n📏 Word count: {wc}/250 {'✅' if wc <= 250 else '❌'}")
    print(f"🕐 Generated at: {pulse.generated_at}")
    print(f"{'='*60}")
