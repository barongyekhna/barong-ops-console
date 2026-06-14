"""K17-E K16-to-K17 pipeline adapter.

This module transforms K16 SERPResult data into the K17-A input contract. It
does not call AI providers, run C14, filter keywords, rank results, parse
responses, design K18 behavior, or access external systems.
"""

from __future__ import annotations

from urllib.parse import urlparse

from backend.app.modules.k.k16_serp.models import SERPItem, SERPResult

from .schema import ChatGPTFilterInput

K17_E_MODE = "pipeline_only"
K17_RUNTIME = "no_execution"
K17_EXTERNAL_ACCESS = False


class K17PipelineAdapter:
    """Adapt K16 SERPResult data into ChatGPTFilterInput."""

    def transform(self, serp_result: SERPResult) -> ChatGPTFilterInput:
        cleaned_market = self._clean_text(serp_result.market).lower()
        cleaned_query = self._clean_text(serp_result.query)
        cleaned_keywords = self._normalize_keywords(serp_result.keywords)
        cleaned_organic_results = self._normalize_results(
            serp_result.organic_results,
        )
        cleaned_competitors = self._normalize_competitors(
            serp_result.competitor_links,
            cleaned_organic_results,
        )

        return ChatGPTFilterInput(
            serp_bundle=serp_result,
            product_context=self._extract_context(
                serp_result=serp_result,
                organic_results=cleaned_organic_results,
                competitor_links=cleaned_competitors,
            ),
            market=cleaned_market,
            query=cleaned_query,
            filter_mode="strict",
            keywords=cleaned_keywords,
            organic_results=cleaned_organic_results,
            competitor_links=cleaned_competitors,
            intent="structured_for_chatgpt",
        )

    def _extract_context(
        self,
        serp_result: SERPResult,
        organic_results: list[SERPItem],
        competitor_links: list[str],
    ) -> dict[str, object]:
        return {
            "product_id": self._clean_text(serp_result.product_id),
            "source": self._clean_text(serp_result.source),
            "result_id": self._clean_text(serp_result.id),
            "market": self._clean_text(serp_result.market).lower(),
            "query": self._clean_text(serp_result.query),
            "keyword_count": len(serp_result.keywords),
            "organic_result_count": len(organic_results),
            "competitor_count": len(competitor_links),
        }

    def _normalize_results(self, organic_results: list[SERPItem]) -> list[SERPItem]:
        normalized_results = []
        for index, item in enumerate(organic_results, start=1):
            title = self._clean_text(item.title)
            url = self._clean_text(item.url)
            if not title or not url:
                continue

            normalized_results.append(
                item.model_copy(
                    update={
                        "title": title,
                        "url": url,
                        "snippet": self._clean_text(item.snippet),
                        "rank": item.rank if item.rank >= 1 else index,
                    }
                )
            )
        return normalized_results

    def _normalize_keywords(self, keywords: list[str]) -> list[str]:
        normalized_keywords = []
        for keyword in keywords:
            normalized_keyword = self._clean_text(keyword).lower()
            if normalized_keyword:
                normalized_keywords.append(normalized_keyword)
        return self._dedupe(normalized_keywords)

    def _normalize_competitors(
        self,
        competitor_links: list[str],
        organic_results: list[SERPItem],
    ) -> list[str]:
        competitors = [self._domain_from_link(link) for link in competitor_links]
        competitors.extend(
            self._domain_from_link(item.url) for item in organic_results
        )
        return self._dedupe([competitor for competitor in competitors if competitor])

    @staticmethod
    def _clean_text(value: str) -> str:
        return " ".join(str(value).strip().split())

    @staticmethod
    def _domain_from_link(link: str) -> str:
        value = " ".join(str(link).strip().lower().split())
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
    "K17PipelineAdapter",
    "K17_E_MODE",
    "K17_RUNTIME",
    "K17_EXTERNAL_ACCESS",
]
