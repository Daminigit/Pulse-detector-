"""
src/models.py
─────────────
Pydantic v2 data models for every stage of the Pulse Detector pipeline.

Flow:
    google-play-scraper  →  RawReview
    filter.py            →  CleanReview   (PII stripped, UUID assigned)
    cluster.py (LLM)     →  ClusterResult (review_id → theme_label)
    summarise.py (LLM)   →  PulseNote     (final deliverable)
    Theme                →  used inside PulseNote and ClusterResult
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ── 1. RawReview ─────────────────────────────────────────────────────────────
# Directly mapped from google-play-scraper output.
# PII fields (reviewer_name, reviewer_id, device) are present here but
# MUST be stripped before constructing a CleanReview.

class RawReview(BaseModel):
    """Raw review as returned by google-play-scraper. Contains PII fields."""

    reviewer_name: Optional[str] = None   # ← PII — stripped in filter.py
    reviewer_id:   Optional[str] = None   # ← PII — stripped in filter.py
    rating:        int            = Field(..., ge=1, le=5, description="Star rating 1–5")
    title:         Optional[str] = None
    text:          str            = Field(..., min_length=1)
    date:          date
    app_version:   Optional[str] = None
    device:        Optional[str] = None   # ← PII — stripped in filter.py

    @field_validator("rating", mode="before")
    @classmethod
    def coerce_rating(cls, v: object) -> int:
        """Coerce None / out-of-range ratings rather than hard-failing."""
        if v is None:
            return 1
        v = int(v)
        return max(1, min(5, v))


# ── 2. CleanReview ────────────────────────────────────────────────────────────
# Sanitised form produced by filter.py.
# • PII fields are absent.
# • id is a freshly generated UUID (never the original reviewer_id).
# • text has been PII-masked (emails, phones replaced).
# • theme is populated by cluster.py after clustering.

class CleanReview(BaseModel):
    """PII-free, deduplicated review ready for LLM processing."""

    id:          str            = Field(default_factory=lambda: str(uuid.uuid4()))
    rating:      int            = Field(..., ge=1, le=5)
    title:       Optional[str] = None
    text:        str            = Field(..., min_length=1)
    date:        date
    app_version: Optional[str] = None
    theme:       Optional[str] = None   # assigned by cluster.py

    @field_validator("id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Ensure id is always a valid UUID v4 string."""
        uuid.UUID(v, version=4)          # raises ValueError if invalid
        return v


# ── 3. Theme ──────────────────────────────────────────────────────────────────
# Represents a single cluster theme with its review-count statistics.

class Theme(BaseModel):
    """A named theme cluster with volume statistics."""

    label:        str   = Field(..., description="Snake_case theme key, e.g. 'app_performance'")
    display_name: str   = Field(..., description="Human-readable name, e.g. 'App Performance'")
    count:        int   = Field(..., ge=0, description="Number of reviews in this theme")
    pct:          float = Field(..., ge=0.0, le=100.0, description="Percentage of total corpus")


# ── 4. ClusterResult ──────────────────────────────────────────────────────────
# Direct target of PydanticOutputParser in cluster.py.
# LLM must return JSON matching this schema exactly.

class ClusterResult(BaseModel):
    """LLM clustering output: maps every CleanReview.id to a theme label."""

    assignments: Dict[str, str] = Field(
        ...,
        description="Mapping of CleanReview.id → theme_label (snake_case)"
    )

    @field_validator("assignments")
    @classmethod
    def no_empty_values(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Every review must be assigned to a non-empty theme label."""
        for review_id, label in v.items():
            if not label or not label.strip():
                raise ValueError(
                    f"Review '{review_id}' has an empty theme assignment."
                )
        return v


# ── 5. PulseNote ─────────────────────────────────────────────────────────────
# The final one-page weekly pulse — target of PydanticOutputParser in
# summarise.py. This object is published to Google Docs and emailed via Gmail.

class PulseNote(BaseModel):
    """The weekly one-page pulse note — the primary deliverable."""

    week_range:       str         = Field(..., description="e.g. 'Aug 25 – Sep 05, 2026'")
    reviews_analysed: int         = Field(..., ge=0)
    avg_rating:       float       = Field(..., ge=1.0, le=5.0)
    top_themes:       List[Theme] = Field(..., min_length=1, max_length=3)
    quotes:           List[str]   = Field(..., min_length=3, max_length=3,
                                          description="3 verbatim, anonymised user quotes")
    action_ideas:     List[str]   = Field(..., min_length=3, max_length=3,
                                          description="3 concrete, theme-grounded recommendations")
    generated_at:     datetime    = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of generation"
    )

    @field_validator("quotes", "action_ideas", mode="before")
    @classmethod
    def no_empty_strings(cls, v: List[str]) -> List[str]:
        for item in v:
            if not item or not item.strip():
                raise ValueError("Quotes and action ideas must not be empty strings.")
        return v

    def word_count(self) -> int:
        """Total word count across quotes + action ideas (must be ≤ 250)."""
        combined = " ".join(self.quotes + self.action_ideas)
        return len(combined.split())


# ── Smoke-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from datetime import date as _date

    print("Running P1 smoke-test…\n")

    # 1. RawReview
    raw = RawReview(
        reviewer_name="Test User",
        reviewer_id="uid_123",
        rating=2,
        title="App keeps crashing",
        text="Every time I try to withdraw funds the app crashes. Very frustrating.",
        date=_date(2026, 8, 28),
        app_version="5.1.0",
        device="Pixel 7",
    )
    print(f"✅ RawReview        : rating={raw.rating}, text[:40]={raw.text[:40]!r}")

    # 2. CleanReview
    clean = CleanReview(
        rating=raw.rating,
        title=raw.title,
        text=raw.text,
        date=raw.date,
        app_version=raw.app_version,
        # reviewer_name / reviewer_id / device intentionally absent
    )
    print(f"✅ CleanReview       : id={clean.id}, theme={clean.theme!r}")
    assert clean.id != raw.reviewer_id, "CleanReview.id must NOT be the original reviewer_id"

    # 3. Theme
    theme = Theme(label="withdrawals_redemptions", display_name="Withdrawals & Redemptions",
                  count=42, pct=28.5)
    print(f"✅ Theme             : {theme.label} ({theme.count} reviews, {theme.pct}%)")

    # 4. ClusterResult
    cluster = ClusterResult(assignments={clean.id: "withdrawals_redemptions"})
    print(f"✅ ClusterResult     : {len(cluster.assignments)} assignment(s)")

    # 5. PulseNote
    pulse = PulseNote(
        week_range="Aug 25 – Sep 05, 2026",
        reviews_analysed=150,
        avg_rating=3.2,
        top_themes=[
            Theme(label="app_performance", display_name="App Performance", count=60, pct=40.0),
            Theme(label="withdrawals_redemptions", display_name="Withdrawals & Redemptions", count=42, pct=28.0),
            Theme(label="payments_transactions", display_name="Payments & Transactions", count=30, pct=20.0),
        ],
        quotes=[
            "Every time I try to withdraw funds the app crashes.",
            "KYC verification has been stuck for 3 days with no response.",
            "UPI payments fail silently — no error message shown.",
        ],
        action_ideas=[
            "Investigate and fix the crash on the withdrawal flow (reproduced on Android 13).",
            "Add a KYC status tracker so users know exactly where their verification stands.",
            "Surface a clear error message when UPI payments fail, with a retry option.",
        ],
    )
    wc = pulse.word_count()
    print(f"✅ PulseNote         : {pulse.reviews_analysed} reviews, avg ★{pulse.avg_rating}")
    print(f"   Word count        : {wc} / 250 {'✅' if wc <= 250 else '❌ EXCEEDS LIMIT'}")
    print(f"   generated_at      : {pulse.generated_at}")

    print("\n🎉 All P1 models instantiated successfully.")

