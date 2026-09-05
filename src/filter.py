"""
src/filter.py
─────────────
Cleans raw Play Store reviews: filters by date, deduplicates, strips PII,
and produces privacy-safe CleanReview objects ready for LLM processing.

Public API:
    filter_and_clean(raw_reviews, weeks_back) -> List[CleanReview]
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import List

from src.models import CleanReview, RawReview

log = logging.getLogger(__name__)

# ── PII patterns ──────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
_PHONE_RE = re.compile(
    r"(\+?\d[\d\s\-]{8,}\d)"
)

# ── Language heuristic ────────────────────────────────────────────────────────
# Keeps reviews that are mostly ASCII (English) — simple but fast.
# No external library required.
_ASCII_THRESHOLD = 0.75   # at least 75 % of chars must be ASCII


def _is_english(text: str) -> bool:
    if not text:
        return False
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return (ascii_chars / len(text)) >= _ASCII_THRESHOLD


# ── PII masking ───────────────────────────────────────────────────────────────

def _mask_pii(text: str) -> str:
    """Replace email addresses and phone numbers with safe placeholders."""
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub("[phone]", text)
    return text


# ── Public function ───────────────────────────────────────────────────────────

def filter_and_clean(
    raw_reviews: List[RawReview],
    weeks_back: int = 10,
    output_dir: str = "./output",
) -> List[CleanReview]:
    """
    Filter, deduplicate, sanitise, and PII-strip raw reviews.

    Steps (in order):
      1. Date-range filter  — drop reviews older than weeks_back
      2. Empty text filter  — drop reviews with no meaningful text
      3. Language filter    — keep English-dominant reviews
      4. Deduplication      — drop exact-text duplicates (by SHA-256 hash)
      5. PII strip          — mask emails and phone numbers in text
      6. CleanReview build  — assign fresh UUID; drop reviewer_name/id/device

    Saves the clean list to output/clean_reviews_YYYY-MM-DD.json.

    Returns:
        List[CleanReview]
    """
    cutoff = date.today() - timedelta(weeks=weeks_back)
    total_raw = len(raw_reviews)
    log.info("Filtering %d raw reviews (cutoff: %s)…", total_raw, cutoff)

    seen_hashes: set[str] = set()
    clean: List[CleanReview] = []

    dropped = {"date": 0, "empty": 0, "language": 0, "duplicate": 0}

    for raw in raw_reviews:

        # 1. Date filter
        if raw.date < cutoff:
            dropped["date"] += 1
            continue

        # 2. Empty text filter
        stripped_text = raw.text.strip() if raw.text else ""
        if len(stripped_text) < 10:
            dropped["empty"] += 1
            continue

        # 3. Language filter
        if not _is_english(stripped_text):
            dropped["language"] += 1
            continue

        # 4. Deduplication
        text_hash = hashlib.sha256(stripped_text.encode()).hexdigest()
        if text_hash in seen_hashes:
            dropped["duplicate"] += 1
            continue
        seen_hashes.add(text_hash)

        # 5. PII masking on text
        clean_text = _mask_pii(stripped_text)

        # 6. Build CleanReview  (reviewer_name / reviewer_id / device NOT copied)
        clean.append(CleanReview(
            id=str(uuid.uuid4()),
            rating=raw.rating,
            title=_mask_pii(raw.title) if raw.title else None,
            text=clean_text,
            date=raw.date,
            app_version=raw.app_version,
            # theme=None  (assigned later by cluster.py)
        ))

    # ── Stats ─────────────────────────────────────────────────────────────────
    n_clean = len(clean)
    avg_rating = sum(r.rating for r in clean) / n_clean if n_clean else 0.0

    log.info(
        "Filter complete: %d → %d reviews kept "
        "(dropped: date=%d, empty=%d, lang=%d, dup=%d)",
        total_raw, n_clean,
        dropped["date"], dropped["empty"], dropped["language"], dropped["duplicate"],
    )
    log.info("Avg rating (clean): %.2f ★", avg_rating)

    if n_clean < 10:
        log.warning(
            "⚠️  Only %d reviews remain after filtering. "
            "Pulse may not be representative.",
            n_clean,
        )

    # ── Persist to disk ───────────────────────────────────────────────────────
    _save_to_disk(clean, output_dir)

    return clean


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_to_disk(clean: List[CleanReview], output_dir: str) -> None:
    """Save the clean reviews as JSON for inspection / debugging."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"clean_reviews_{date.today()}.json"
    path = Path(output_dir) / filename

    data = [r.model_dump(mode="json") for r in clean]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)

    log.info("💾 Clean reviews saved → %s (%d records)", path, len(clean))


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    from src.ingest import fetch_reviews

    app_id     = os.getenv("APP_ID", "com.nextbillion.groww")
    weeks_back = int(os.getenv("WEEKS_BACK", "10"))
    output_dir = os.getenv("OUTPUT_DIR", "./output")

    print(f"\n🔍 Fetching reviews for '{app_id}'…")
    raw = fetch_reviews(app_id, weeks_back)

    print(f"\n🧹 Filtering {len(raw)} raw reviews…")
    clean = filter_and_clean(raw, weeks_back=weeks_back, output_dir=output_dir)

    print(f"\n✅ Clean reviews      : {len(clean)}")
    print(f"⭐ Avg rating         : {sum(r.rating for r in clean) / len(clean):.2f} ★")
    print(f"📅 Date range         : {min(r.date for r in clean)} → {max(r.date for r in clean)}")

    # Privacy checks
    import re as _re
    pii_hits = sum(
        1 for r in clean
        if _re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", r.text)
    )
    print(f"🔒 PII emails in text : {pii_hits}  (should be 0)")
    has_names = any(hasattr(r, "reviewer_name") for r in clean)
    print(f"🔒 reviewer_name field: {'present ❌' if has_names else 'absent ✅'}")

    print(f"\nSample clean review:")
    print(f"  id         : {clean[0].id}")
    print(f"  rating     : {clean[0].rating}")
    print(f"  text[:100] : {clean[0].text[:100]}…")

