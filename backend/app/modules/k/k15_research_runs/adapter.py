"""K15-E read-only integration adapter.

This adapter exposes K15 research run data for downstream K12/K14 consumers
without mutating K15 state, invoking the execution engine, calling external
providers, or adding AI/SEO/ranking behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict

from .models import ResearchRun, ResearchRunStatus
from .service import RESEARCH_RUN_STORE

K15_E_MODE = "read_only"
K15_WRITE_ACCESS = False
K15_MUTATION = "disabled"


class ResearchRunSummary(TypedDict):
    product_id: str
    run_id: str | None
    status: ResearchRunStatus | None
    updated_at: datetime | None
    keywords: list[str]
    competitor_brands: list[str]
    search_intent: str
    confidence_score: float
    run_count: int


class CompetitorContext(TypedDict):
    product_id: str
    run_id: str | None
    competitor_brands: list[str]
    search_intent: str


class K15ReadOnlyAdapter:
    """Read-only facade for K15 research data."""

    def __init__(
        self,
        store: Mapping[str, ResearchRun] | None = None,
    ) -> None:
        self._store = RESEARCH_RUN_STORE if store is None else store

    def get_research_summary(self, product_id: str) -> ResearchRunSummary:
        runs = self._runs_for_product(product_id)
        latest_run = runs[0] if runs else None

        if latest_run is None:
            return {
                "product_id": product_id,
                "run_id": None,
                "status": None,
                "updated_at": None,
                "keywords": [],
                "competitor_brands": [],
                "search_intent": "",
                "confidence_score": 0.0,
                "run_count": 0,
            }

        return {
            "product_id": latest_run.product_id,
            "run_id": latest_run.id,
            "status": latest_run.status,
            "updated_at": latest_run.updated_at,
            "keywords": list(latest_run.keywords),
            "competitor_brands": list(latest_run.competitor_brands),
            "search_intent": latest_run.search_intent,
            "confidence_score": latest_run.confidence_score,
            "run_count": len(runs),
        }

    def get_keywords(self, product_id: str) -> list[str]:
        latest_run = self._latest_run(product_id)
        if latest_run is None:
            return []
        return list(latest_run.keywords)

    def get_competitor_context(self, product_id: str) -> CompetitorContext:
        latest_run = self._latest_run(product_id)
        if latest_run is None:
            return {
                "product_id": product_id,
                "run_id": None,
                "competitor_brands": [],
                "search_intent": "",
            }

        return {
            "product_id": latest_run.product_id,
            "run_id": latest_run.id,
            "competitor_brands": list(latest_run.competitor_brands),
            "search_intent": latest_run.search_intent,
        }

    def _latest_run(self, product_id: str) -> ResearchRun | None:
        runs = self._runs_for_product(product_id)
        return runs[0] if runs else None

    def _runs_for_product(self, product_id: str) -> list[ResearchRun]:
        return sorted(
            (
                research_run.model_copy(deep=True)
                for research_run in self._store.values()
                if research_run.product_id == product_id
            ),
            key=lambda research_run: research_run.updated_at,
            reverse=True,
        )


__all__ = [
    "K15ReadOnlyAdapter",
    "ResearchRunSummary",
    "CompetitorContext",
    "K15_E_MODE",
    "K15_WRITE_ACCESS",
    "K15_MUTATION",
]
