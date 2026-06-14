"""K15-C mock research run service.

This service manages ResearchRun lifecycle records in memory only. It does not
perform keyword analysis, SEO ranking, content generation, persistence, or
external provider access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .models import RESEARCH_RUN_QUERY_TYPE, ResearchRun

RESEARCH_RUN_STORE: dict[str, ResearchRun] = {}


class K15ResearchService:
    """In-memory service facade for K15 research runs."""

    def __init__(self, store: dict[str, ResearchRun] | None = None) -> None:
        self.store = RESEARCH_RUN_STORE if store is None else store

    def start(self, product_id: str) -> ResearchRun:
        now = datetime.now(UTC)
        run_id = str(uuid4())
        research_run = ResearchRun(
            id=run_id,
            product_id=product_id,
            status="pending",
            query_type=RESEARCH_RUN_QUERY_TYPE,
            created_at=now,
            updated_at=now,
            keywords=[],
            competitor_brands=[],
            search_intent="",
            source="k15_trigger",
            confidence_score=0.0,
        )
        self.store[run_id] = research_run
        return research_run

    def get(self, run_id: str) -> ResearchRun | None:
        return self.store.get(run_id)

    def list_by_product(self, product_id: str) -> list[ResearchRun]:
        return [
            research_run
            for research_run in self.store.values()
            if research_run.product_id == product_id
        ]
