"""K16-E SERP input adapter for future K17/K18 consumers.

This module flattens K16 SERPResult records into read-only input structures for
future K17 and K18 layers. It does not call AI systems, perform SEO analysis,
rank results, mutate K16 data, persist state, or access external providers.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .models import SERPItem, SERPResult

K16_E_MODE = "input_adapter_only"
K16_RUNTIME = "no_execution"
K16_EXTERNAL_ACCESS = False

_MAX_SNIPPET_LENGTH = 180


class SERPToAIAdapter:
    """Normalize SERPResult data into K17/K18 input shapes."""

    def to_k17_input(self, serp_result: SERPResult) -> dict[str, object]:
        normalized_items = self._normalize_items(serp_result.organic_results)
        return {
            "keywords": self._normalize_keywords(serp_result.keywords),
            "context": normalized_items,
            "competitors": self._normalize_competitors(
                serp_result.competitor_links,
                normalized_items,
            ),
            "intent": "structured_for_chatgpt",
        }

    def to_k18_input(self, serp_result: SERPResult) -> dict[str, object]:
        normalized_items = self._normalize_items(serp_result.organic_results)
        return {
            "keywords": self._normalize_keywords(serp_result.keywords),
            "competitors": self._normalize_competitors(
                serp_result.competitor_links,
                normalized_items,
            ),
            "market_signals": normalized_items,
            "intent": "structured_for_claude",
        }

    def _normalize_items(
        self,
        organic_results: list[SERPItem],
    ) -> list[dict[str, object]]:
        return [
            {
                "title": item.title.strip(),
                "url": item.url.strip(),
                "domain": self._domain_from_link(item.url),
                "snippet": self._truncate_snippet(item.snippet),
                "rank": item.rank,
            }
            for item in organic_results
        ]

    def _normalize_keywords(self, keywords: list[str]) -> list[str]:
        normalized_keywords = []
        for keyword in keywords:
            normalized_keyword = " ".join(keyword.strip().lower().split())
            if normalized_keyword:
                normalized_keywords.append(normalized_keyword)
        return self._dedupe(normalized_keywords)

    def _normalize_competitors(
        self,
        competitor_links: list[str],
        normalized_items: list[dict[str, object]],
    ) -> list[str]:
        domains = [self._domain_from_link(link) for link in competitor_links]
        domains.extend(
            str(item["domain"])
            for item in normalized_items
            if item.get("domain")
        )
        return self._dedupe([domain for domain in domains if domain])

    @staticmethod
    def _truncate_snippet(snippet: str) -> str:
        normalized_snippet = " ".join(snippet.strip().split())
        if len(normalized_snippet) <= _MAX_SNIPPET_LENGTH:
            return normalized_snippet
        return normalized_snippet[: _MAX_SNIPPET_LENGTH - 3].rstrip() + "..."

    @staticmethod
    def _domain_from_link(link: str) -> str:
        value = link.strip().lower()
        if not value:
            return ""

        parsed = urlparse(value if "://" in value else f"https://{value}")
        domain = parsed.netloc or parsed.path
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.split("/")[0]

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
    "SERPToAIAdapter",
    "K16_E_MODE",
    "K16_RUNTIME",
    "K16_EXTERNAL_ACCESS",
]
