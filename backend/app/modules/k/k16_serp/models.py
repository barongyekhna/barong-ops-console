"""Standard data model for K16-A SERP market data.

K16-A defines the shape for market query results only. It does not call SERP
providers, analyze keywords, filter with AI, rank results, or apply SEO logic.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

K16_A_MODE = "schema_only"
K16_RUNTIME = "disabled"
K16_EXTERNAL_ACCESS = False


class SERPItem(BaseModel):
    """Single organic SERP item."""

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    snippet: str = ""
    rank: int = Field(ge=1)


class SERPResult(BaseModel):
    """Canonical K16 SERP result structure."""

    id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    market: str = Field(min_length=1)
    query: str = Field(min_length=1)
    organic_results: list[SERPItem] = Field(default_factory=list)
    competitor_links: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    source: str = "serper_mock"
    created_at: datetime
    updated_at: datetime
