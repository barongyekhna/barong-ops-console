"""K15-D mock execution engine for research runs.

This module simulates a synchronous ResearchRun lifecycle. It does not perform
AI analysis, SEO ranking, content generation, persistence, external API access,
or production/staging execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from re import split

from .models import ResearchRun
from .service import K15ResearchService, RESEARCH_RUN_STORE

K15_D_MODE = "mock_execution"
K15_RUNTIME = "no_side_effect"
K15_AI = "disabled"

_SEARCH_INTENTS = ("informational", "transactional", "commercial")
_GENERIC_KEYWORD_PARTS = ("product", "market", "buyers")
_COMPETITOR_BRANDS = (
    "Northline",
    "EverPeak",
    "BrightNest",
    "UrbanForge",
    "ClearMint",
)


class K15ExecutionEngine:
    """Synchronous mock lifecycle processor for K15 research runs."""

    def __init__(
        self,
        service: K15ResearchService | None = None,
    ) -> None:
        self.service = service or K15ResearchService(RESEARCH_RUN_STORE)

    def run(self, run_id: str) -> ResearchRun:
        research_run = self.service.get(run_id)
        if research_run is None:
            raise KeyError(f"Research run '{run_id}' was not found.")

        if research_run.status != "pending":
            return research_run

        running_run = self._replace_run(
            research_run,
            status="running",
            updated_at=datetime.now(UTC),
        )
        title_seed = self._title_seed(running_run)
        completed_run = self._replace_run(
            running_run,
            status="completed",
            updated_at=datetime.now(UTC),
            keywords=self.generate_keywords(title_seed),
            competitor_brands=self.generate_competitors(title_seed),
            search_intent=self.simulate_search_intent(title_seed),
            source="system_mock",
            confidence_score=0.64,
        )
        return completed_run

    def generate_keywords(self, product_title: str) -> list[str]:
        terms = self._terms(product_title)
        if not terms:
            terms = list(_GENERIC_KEYWORD_PARTS)

        primary = " ".join(terms[:3])
        secondary = terms[0]
        return self._dedupe(
            (
                primary,
                f"{secondary} buying guide",
                f"{secondary} comparison",
                f"{secondary} supplier",
                f"{secondary} wholesale",
            )
        )

    def generate_competitors(self, product_title: str) -> list[str]:
        offset = self._checksum(product_title) % len(_COMPETITOR_BRANDS)
        ordered = _COMPETITOR_BRANDS[offset:] + _COMPETITOR_BRANDS[:offset]
        return list(ordered[:3])

    def simulate_search_intent(self, product_title: str) -> str:
        return _SEARCH_INTENTS[self._checksum(product_title) % len(_SEARCH_INTENTS)]

    def _replace_run(self, research_run: ResearchRun, **updates: object) -> ResearchRun:
        next_run = research_run.model_copy(update=updates)
        self.service.store[next_run.id] = next_run
        return next_run

    @staticmethod
    def _title_seed(research_run: ResearchRun) -> str:
        return research_run.product_id.strip()

    @staticmethod
    def _terms(value: str) -> list[str]:
        terms = []
        for term in split(r"[^a-zA-Z0-9]+", value.lower()):
            if len(term) < 3:
                continue
            if term.isdigit():
                continue
            terms.append(term)
        return terms[:5]

    @staticmethod
    def _checksum(value: str) -> int:
        return sum(ord(char) for char in value)

    @staticmethod
    def _dedupe(values: tuple[str, ...]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = value.strip()
            key = text.lower()
            if not text or key in seen:
                continue
            deduped.append(text)
            seen.add(key)
        return deduped


__all__ = [
    "K15ExecutionEngine",
    "K15_D_MODE",
    "K15_RUNTIME",
    "K15_AI",
]
