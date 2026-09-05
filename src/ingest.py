"""
src/ingest.py
─────────────
Fetches public Play Store reviews for the Groww app using google-play-scraper.

Public API:
    fetch_reviews(app_id, weeks_back) -> List[RawReview]
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import List

from google_play_scraper import Sort, reviews as gps_reviews
from google_play_scraper.exceptions import NotFoundError

from src.models import RawReview

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_BATCH_SIZE   = 200    # reviews per scraper page
_MAX_BATCHES  = 10     # safety cap  → max 2 000 reviews
_MAX_RETRIES  = 3
_BACKOFF_BASE = 2      # seconds; doubles each retry


# ── Public function ───────────────────────────────────────────────────────────

def fetch_reviews(app_id: str, weeks_back: int) -> List[RawReview]:
    """
    Fetch recent Play Store reviews for *app_id* going back *weeks_back* weeks.

    Paginates until:
      - The date cutoff is reached (reviews older than cutoff are skipped), or
      - _MAX_BATCHES pages have been fetched (safety cap).

    Retries up to _MAX_RETRIES times on network / rate-limit errors.

    Returns:
        List[RawReview] — raw, unfiltered reviews within the time window.

    Raises:
        SystemExit: if the app is not found or 0 reviews are returned.
    """
    if weeks_back < 1:
        raise ValueError(f"weeks_back must be >= 1, got {weeks_back}")

    cutoff = date.today() - timedelta(weeks=weeks_back)
    log.info("Fetching reviews for '%s' (cutoff: %s)", app_id, cutoff)

    collected: List[RawReview] = []
    continuation_token = None

    for batch_num in range(1, _MAX_BATCHES + 1):
        raw_batch, continuation_token = _fetch_batch(
            app_id, continuation_token, batch_num
        )

        if not raw_batch:
            log.info("Empty batch at page %d — stopping.", batch_num)
            break

        reached_cutoff = False
        for item in raw_batch:
            review_date: date = _parse_date(item.get("at"))
            if review_date is None or review_date < cutoff:
                reached_cutoff = True
                continue                 # skip but keep checking rest of batch
            try:
                collected.append(_to_raw_review(item))
            except Exception as exc:    # noqa: BLE001
                log.warning("Skipping malformed review: %s", exc)

        log.info(
            "Batch %d: +%d reviews (total so far: %d)",
            batch_num, len(raw_batch), len(collected),
        )

        if reached_cutoff or continuation_token is None:
            log.info("Date cutoff reached — stopping pagination.")
            break

    if not collected:
        log.error(
            "No reviews fetched for '%s' in the past %d weeks. "
            "Cannot generate pulse.",
            app_id, weeks_back,
        )
        raise SystemExit(1)

    log.info("✅ Fetched %d reviews for '%s'.", len(collected), app_id)
    return collected


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_batch(
    app_id: str,
    continuation_token: object,
    batch_num: int,
) -> tuple[list, object]:
    """Fetch one page of reviews with retry / backoff."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result, token = gps_reviews(
                app_id,
                lang="en",
                country="in",
                sort=Sort.NEWEST,
                count=_BATCH_SIZE,
                continuation_token=continuation_token,
            )
            return result, token

        except NotFoundError:
            log.error(
                "App '%s' not found on Play Store. Check APP_ID in .env.", app_id
            )
            raise SystemExit(1)

        except Exception as exc:    # noqa: BLE001
            if attempt == _MAX_RETRIES:
                log.error(
                    "Failed to fetch batch %d after %d attempts: %s",
                    batch_num, _MAX_RETRIES, exc,
                )
                raise SystemExit(1)
            wait = _BACKOFF_BASE ** attempt
            log.warning(
                "Batch %d attempt %d failed (%s). Retrying in %ds…",
                batch_num, attempt, exc, wait,
            )
            time.sleep(wait)

    return [], None     # unreachable — keeps type checker happy


def _parse_date(value: object) -> date | None:
    """Safely convert scraper 'at' field (datetime or date) to date."""
    if value is None:
        return None
    try:
        return value.date() if hasattr(value, "date") else date.fromisoformat(str(value))
    except Exception:   # noqa: BLE001
        return None


def _to_raw_review(item: dict) -> RawReview:
    """Map a google-play-scraper dict to a RawReview model."""
    return RawReview(
        reviewer_name=item.get("userName"),
        reviewer_id=item.get("reviewId"),
        rating=item.get("score"),
        title=item.get("title") or None,
        text=item.get("content", ""),
        date=_parse_date(item.get("at")) or date.today(),
        app_version=item.get("appVersion") or None,
        device=item.get("deviceMetadata", {}).get("productName") if isinstance(
            item.get("deviceMetadata"), dict
        ) else None,
    )


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os, json
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    app_id    = os.getenv("APP_ID", "com.nextbillion.groww")
    weeks_back = int(os.getenv("WEEKS_BACK", "10"))

    raw = fetch_reviews(app_id, weeks_back)
    print(f"\n📦 Total raw reviews : {len(raw)}")
    print(f"⭐ Avg raw rating    : {sum(r.rating for r in raw) / len(raw):.2f}")
    print(f"📅 Oldest review     : {min(r.date for r in raw)}")
    print(f"📅 Newest review     : {max(r.date for r in raw)}")
    print(f"\nSample (first review):\n  rating : {raw[0].rating}")
    print(f"  title  : {raw[0].title}")
    print(f"  text   : {raw[0].text[:120]}…")

