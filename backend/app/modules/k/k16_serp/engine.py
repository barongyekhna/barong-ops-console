"""K16-D mock SERP execution engine.

This module coordinates the mock SERP lifecycle and enriches K16-C service
output while preserving the K16-A schema. It does not call external providers,
run AI analysis, perform SEO scoring, persist state, or target production and
staging environments.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from .models import SERPItem, SERPResult
from .service import SERPAdapterService

K16_D_MODE = "execution_mock"
K16_RUNTIME = "no_side_effect"
K16_SERP_PROVIDER = "disabled"

SERPExecutionStatus = Literal["pending", "running", "completed", "failed"]
SERP_EXECUTION_LIFECYCLE: tuple[SERPExecutionStatus, ...] = (
    "pending",
    "running",
    "completed",
)

_ALLOWED_TRANSITIONS: dict[SERPExecutionStatus, tuple[SERPExecutionStatus, ...]] = {
    "pending": ("running", "failed"),
    "running": ("completed", "failed"),
    "completed": (),
    "failed": (),
}

_TIMESTAMP_BASE = datetime(2026, 1, 1, tzinfo=UTC)
_KEYWORD_BOOST_SUFFIXES = ("market", "offers", "catalog", "store")


class SERPExecutionEngine:
    """Synchronous mock lifecycle processor for K16 SERP requests."""

    def __init__(self, service: SERPAdapterService | None = None) -> None:
        self.service = service or SERPAdapterService()
        self.status: SERPExecutionStatus = "pending"

    def run(self, product_id: str, market: str, query: str) -> SERPResult:
        self._transition("running")

        try:
            result = self.service.search(product_id, market, query)
            enriched_result = self._enrich(result)
            self._transition("completed")
            return enriched_result
        except Exception:
            self._transition("failed")
            raise

    def _enrich(self, result: SERPResult) -> SERPResult:
        seed = self._seed_for(result)
        organic_results = self._apply_rank_noise(result.organic_results, seed)
        created_at = self._created_at(seed)

        return result.model_copy(
            update={
                "id": self._result_id(seed),
                "organic_results": organic_results,
                "competitor_links": self._competitor_links_for(organic_results),
                "keywords": self._boost_keywords(result.keywords, result.market),
                "created_at": created_at,
                "updated_at": created_at + self._updated_at_delta(seed),
            }
        )

    def _transition(self, next_status: SERPExecutionStatus) -> None:
        if self.status == next_status:
            return

        allowed_next_statuses = _ALLOWED_TRANSITIONS[self.status]
        if next_status not in allowed_next_statuses:
            raise ValueError(
                f"Invalid K16-D lifecycle transition: {self.status} -> {next_status}."
            )
        self.status = next_status

    def _apply_rank_noise(
        self,
        organic_results: list[SERPItem],
        seed: str,
    ) -> list[SERPItem]:
        if len(organic_results) <= 1:
            return [
                item.model_copy(update={"rank": index})
                for index, item in enumerate(organic_results, start=1)
            ]

        offset = self._checksum(seed) % len(organic_results)
        rotated_results = organic_results[offset:] + organic_results[:offset]
        return [
            item.model_copy(update={"rank": index})
            for index, item in enumerate(rotated_results, start=1)
        ]

    def _boost_keywords(self, keywords: list[str], market: str) -> list[str]:
        boosted_keywords = list(keywords)
        for keyword in keywords[:3]:
            for suffix in _KEYWORD_BOOST_SUFFIXES:
                boosted_keywords.append(f"{keyword} {suffix}")

        if market:
            boosted_keywords.extend(f"{market} {keyword}" for keyword in keywords[:3])

        return self._dedupe(boosted_keywords)[:18]

    @staticmethod
    def _seed_for(result: SERPResult) -> str:
        parts = (
            result.product_id.strip().lower(),
            result.market.strip().lower(),
            result.query.strip().lower(),
        )
        return "|".join(parts)

    @staticmethod
    def _result_id(seed: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"k16-serp:{seed}"))

    @classmethod
    def _created_at(cls, seed: str) -> datetime:
        seconds = cls._checksum(seed) % (60 * 60 * 24 * 90)
        return _TIMESTAMP_BASE + timedelta(seconds=seconds)

    @classmethod
    def _updated_at_delta(cls, seed: str) -> timedelta:
        return timedelta(seconds=5 + (cls._checksum(f"updated:{seed}") % 180))

    @staticmethod
    def _competitor_links_for(organic_results: list[SERPItem]) -> list[str]:
        domains: list[str] = []
        for item in organic_results:
            domain = urlparse(item.url).netloc.lower()
            if domain:
                domains.append(domain)
        return SERPExecutionEngine._dedupe(domains)

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
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

    @staticmethod
    def _checksum(value: str) -> int:
        return sum((index + 1) * ord(char) for index, char in enumerate(value))


__all__ = [
    "SERPExecutionEngine",
    "SERPExecutionStatus",
    "SERP_EXECUTION_LIFECYCLE",
    "K16_D_MODE",
    "K16_RUNTIME",
    "K16_SERP_PROVIDER",
]
