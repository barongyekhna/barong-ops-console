"""K16-C mock SERP adapter service.

This module creates deterministic SERPResult records for the K16 flow. It does
not call Serper or any external provider, perform AI filtering, apply SEO
ranking, persist data, or target production/staging environments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from re import split
from urllib.parse import quote_plus, urlparse
from uuid import uuid4

from .models import SERPItem, SERPResult

K16_C_MODE = "mock_service_only"
K16_RUNTIME = "no_external_calls"
K16_SERP_PROVIDER = "disabled"

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "best",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}

_SYNONYMS_BY_TERM = {
    "bag": ("tote", "carry bag"),
    "bottle": ("drinkware", "water bottle"),
    "chair": ("seat", "office chair"),
    "kids": ("children", "toddler"),
    "laptop": ("notebook", "computer"),
    "phone": ("mobile", "smartphone"),
    "stainless": ("steel", "metal"),
    "water": ("hydration", "drink"),
}

_COMMERCIAL_MODIFIERS = ("buy", "best", "reviews", "price", "supplier")
_COMPETITOR_DOMAINS = (
    "amazon.com",
    "walmart.com",
    "target.com",
    "etsy.com",
    "aliexpress.com",
    "shopify.com",
)


class SERPAdapterService:
    """Mock SERP data service for K16-C."""

    def search(self, product_id: str, market: str, query: str) -> SERPResult:
        normalized_product_id = product_id.strip()
        normalized_market = market.strip().lower()
        normalized_query = query.strip()

        if not normalized_product_id:
            raise ValueError("product_id is required for SERP search.")
        if not normalized_market:
            raise ValueError("market is required for SERP search.")
        if not normalized_query:
            raise ValueError("query is required for SERP search.")

        now = datetime.now(UTC)
        organic_results = self._mock_results(normalized_query, normalized_market)
        return SERPResult(
            id=str(uuid4()),
            product_id=normalized_product_id,
            market=normalized_market,
            query=normalized_query,
            organic_results=organic_results,
            competitor_links=self._extract_competitors(organic_results),
            keywords=self._generate_keywords(normalized_query),
            source="serper_mock",
            created_at=now,
            updated_at=now,
        )

    def _mock_results(self, query: str, market: str) -> list[SERPItem]:
        query_slug = quote_plus(query.lower())
        market_slug = quote_plus(market.lower())
        result_specs = (
            (
                f"{query.title()} Buying Options",
                f"https://{self._domain_for(0)}/search?q={query_slug}",
                f"Marketplace listings for {query} in the {market} channel.",
            ),
            (
                f"{query.title()} Product Comparison",
                f"https://{self._domain_for(1)}/browse/{query_slug}",
                f"Comparable ecommerce products and offers for {query}.",
            ),
            (
                f"{query.title()} Supplier Catalog",
                f"https://{self._domain_for(2)}/market/{market_slug}/{query_slug}",
                f"Mock supplier catalog result for {query} and {market}.",
            ),
            (
                f"{query.title()} Customer Picks",
                f"https://{self._domain_for(3)}/collections/{query_slug}",
                f"Simulated customer-facing result for {query}.",
            ),
        )
        return [
            SERPItem(title=title, url=url, snippet=snippet, rank=index)
            for index, (title, url, snippet) in enumerate(result_specs, start=1)
        ]

    def _extract_competitors(self, organic_results: list[SERPItem]) -> list[str]:
        domains = []
        for item in organic_results:
            domain = urlparse(item.url).netloc.lower()
            if not domain:
                continue
            domains.append(domain)
        return self._dedupe(domains)

    def _generate_keywords(self, query: str) -> list[str]:
        terms = self._terms(query)
        keywords: list[str] = []

        if terms:
            keywords.append(" ".join(terms[:4]))
            keywords.extend(terms[:4])

        for term in terms[:3]:
            keywords.extend(_SYNONYMS_BY_TERM.get(term, ()))
            keywords.extend(f"{modifier} {term}" for modifier in _COMMERCIAL_MODIFIERS)

        return self._dedupe(keywords)[:12]

    @staticmethod
    def _domain_for(index: int) -> str:
        return _COMPETITOR_DOMAINS[index % len(_COMPETITOR_DOMAINS)]

    @staticmethod
    def _terms(value: str) -> list[str]:
        terms = []
        for term in split(r"[^a-zA-Z0-9]+", value.lower()):
            if len(term) < 2:
                continue
            if term.isdigit() or term in _STOP_WORDS:
                continue
            terms.append(term)
        return terms

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


__all__ = [
    "SERPAdapterService",
    "K16_C_MODE",
    "K16_RUNTIME",
    "K16_SERP_PROVIDER",
]
