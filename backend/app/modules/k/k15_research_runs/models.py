"""Standard data model for K15-A research runs.

K15-A defines the normalized research task structure and lifecycle only. It is
not a keyword analysis, SEO, AI processing, or ranking layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

K15_A_MODE = "schema_standardization"
K15_RUNTIME = "disabled_execution"
K15_EXTERNAL_ACCESS = False

RESEARCH_RUN_QUERY_TYPE = "keyword_research"

ResearchRunStatus = Literal["pending", "running", "completed", "failed"]
ResearchRunSource = Literal["k15_trigger", "manual", "system_mock"]

RESEARCH_RUN_LIFECYCLE: tuple[
    tuple[ResearchRunStatus, ResearchRunStatus],
    ...,
] = (
    ("pending", "running"),
    ("running", "completed"),
    ("pending", "failed"),
)


class ResearchRun(BaseModel):
    """Canonical K15 research run structure."""

    id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    status: ResearchRunStatus
    query_type: Literal["keyword_research"] = RESEARCH_RUN_QUERY_TYPE
    created_at: datetime
    updated_at: datetime
    keywords: list[str] = Field(default_factory=list)
    competitor_brands: list[str] = Field(default_factory=list)
    search_intent: str = ""
    source: ResearchRunSource
    confidence_score: float = Field(ge=0.0, le=1.0)
