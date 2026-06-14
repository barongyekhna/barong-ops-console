"""Standard data model for K14-A product selling points.

Layer boundary:
K13 produces raw AI output, while K14-A defines the normalized product selling
points structure consumed by future normalizers and review surfaces.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BulletCategory = Literal["feature", "benefit", "usage", "spec"]
SellingPointSource = Literal[
    "k13_ai_engine",
    "k13_bridge",
    "manual_input",
    "future_live_ai",
]


class BulletPoint(BaseModel):
    """Normalized selling point bullet."""

    text: str = Field(min_length=1)
    category: BulletCategory
    importance_score: float = Field(ge=0, le=100)


class ProductSellingPoints(BaseModel):
    """Canonical K14-A product selling points structure."""

    product_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    raw_input: str = Field(min_length=1)
    language: str = Field(default="en", min_length=1)
    bullets: list[BulletPoint] = Field(default_factory=list)
    seo_bullets: list[str] = Field(default_factory=list)
    seo_keywords: list[str] = Field(default_factory=list)
    market_tags: list[str] = Field(default_factory=list)
    source: SellingPointSource
    confidence_score: float = Field(ge=0.0, le=1.0)
