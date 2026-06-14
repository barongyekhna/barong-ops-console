"""K15-C API layer for keyword research runs.

The router exposes mock ResearchRun task management only. It does not implement
keyword analysis, SEO/ranking, content generation, persistence, production
activation, or external API access.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from .models import ResearchRun, ResearchRunSource, ResearchRunStatus
from .service import K15ResearchService, RESEARCH_RUN_STORE

K15_C_MODE = "api_layer"
K15_RUNTIME = "mock_only"
K15_EXTERNAL_ACCESS = False

keyword_research_router = APIRouter(
    prefix="/k/keyword-research",
    tags=["k-keyword-research"],
)


class StartResearchRunRequest(BaseModel):
    """Request payload for starting a mock keyword research run."""

    product_id: str = Field(min_length=1)


class StartResearchRunResponse(BaseModel):
    """Start response with required run_id plus ResearchRun-compatible fields."""

    run_id: str
    status: ResearchRunStatus
    id: str
    product_id: str
    query_type: Literal["keyword_research"]
    created_at: datetime
    updated_at: datetime
    keywords: list[str]
    competitor_brands: list[str]
    search_intent: str
    source: ResearchRunSource
    confidence_score: float = Field(ge=0.0, le=1.0)

    @classmethod
    def from_research_run(
        cls,
        research_run: ResearchRun,
    ) -> "StartResearchRunResponse":
        return cls(
            run_id=research_run.id,
            status=research_run.status,
            id=research_run.id,
            product_id=research_run.product_id,
            query_type=research_run.query_type,
            created_at=research_run.created_at,
            updated_at=research_run.updated_at,
            keywords=research_run.keywords,
            competitor_brands=research_run.competitor_brands,
            search_intent=research_run.search_intent,
            source=research_run.source,
            confidence_score=research_run.confidence_score,
        )


research_service = K15ResearchService()


@keyword_research_router.post(
    "/start",
    response_model=StartResearchRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_research_run(
    payload: StartResearchRunRequest,
) -> StartResearchRunResponse:
    research_run = research_service.start(payload.product_id)
    return StartResearchRunResponse.from_research_run(research_run)


@keyword_research_router.get(
    "/by-product/{product_id}",
    response_model=list[ResearchRun],
)
def get_research_runs_by_product(product_id: str) -> list[ResearchRun]:
    return research_service.list_by_product(product_id)


@keyword_research_router.get(
    "/{run_id}",
    response_model=ResearchRun,
)
def get_research_run(run_id: str) -> ResearchRun:
    research_run = research_service.get(run_id)
    if research_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run '{run_id}' was not found.",
        )
    return research_run


__all__ = [
    "K15_C_MODE",
    "K15_RUNTIME",
    "K15_EXTERNAL_ACCESS",
    "RESEARCH_RUN_STORE",
    "K15ResearchService",
    "keyword_research_router",
]
