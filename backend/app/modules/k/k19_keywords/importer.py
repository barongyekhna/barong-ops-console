"""K19-E keyword import layer.

This module imports keyword lists from K15-K18 outputs into K19 KeywordEntry
storage through the K19-B service layer. It does not call AI providers, perform
SEO analysis, run ranking systems, modify K19-A/B/C/D, access external APIs, or
target production/staging environments.
"""

from __future__ import annotations

from typing import Any, Mapping

from .models import KeywordEntry, KeywordEntrySource, KeywordEntryStatus
from .service import KeywordService

K19_E_MODE = "import_only"
K19_RUNTIME = "no_execution"
K19_EXTERNAL_ACCESS = False

K19_E_DATA_FLOW = (
    "K15 -> K19 importer",
    "K16 -> K19 importer",
    "K17 -> K19 importer",
    "K18 -> K19 importer",
    "KeywordEntry storage",
)

K19_IMPORT_SOURCE_MAPPING = {
    "K15": "research",
    "K16": "serp",
    "K17": "chatgpt",
    "K18": "claude",
    "manual": "human",
}

K19_IMPORT_STATUS_MAPPING: dict[str, KeywordEntryStatus] = {
    "K15": "suggested",
    "K16": "suggested",
    "K17": "suggested",
    "K18": "active",
    "manual": "active",
}

_KEYWORD_FIELDS_BY_SOURCE = {
    "K15": ("keywords",),
    "K16": ("keywords",),
    "K17": ("selected_keywords", "keywords"),
    "K18": ("keywords", "final_keywords"),
}

_PRODUCT_ID_FIELDS = ("product_id", "productId")


class KeywordImportService:
    """Import normalized upstream keywords into K19 persistence."""

    def __init__(self, keyword_service: KeywordService | None = None) -> None:
        self.keyword_service = (
            KeywordService() if keyword_service is None else keyword_service
        )

    def import_from_k15(
        self,
        research_run: object,
        product_id: str | None = None,
    ) -> list[KeywordEntry]:
        return self._convert_to_keyword_entries(
            research_run,
            source="K15",
            fallback_product_id=product_id,
        )

    def import_from_k16(
        self,
        serp_result: object,
        product_id: str | None = None,
    ) -> list[KeywordEntry]:
        return self._convert_to_keyword_entries(
            serp_result,
            source="K16",
            fallback_product_id=product_id,
        )

    def import_from_k17(
        self,
        k17_output: object,
        product_id: str | None = None,
    ) -> list[KeywordEntry]:
        return self._convert_to_keyword_entries(
            k17_output,
            source="K17",
            fallback_product_id=product_id,
        )

    def import_from_k18(
        self,
        k18_output: object,
        product_id: str | None = None,
    ) -> list[KeywordEntry]:
        return self._convert_to_keyword_entries(
            k18_output,
            source="K18",
            fallback_product_id=product_id,
        )

    def _convert_to_keyword_entries(
        self,
        source_payload: object,
        source: KeywordEntrySource,
        fallback_product_id: str | None = None,
    ) -> list[KeywordEntry]:
        product_id = self._extract_product_id(source_payload, fallback_product_id)
        if not product_id:
            raise ValueError(f"product_id is required to import {source} keywords")

        keywords = self._extract_keywords(source_payload, source)
        if not keywords:
            return []

        return self.keyword_service.bulk_create_from_source(
            product_id=product_id,
            keywords=keywords,
            source=source,
            status=K19_IMPORT_STATUS_MAPPING[str(source)],
        )

    def _extract_keywords(
        self,
        source_payload: object,
        source: KeywordEntrySource,
    ) -> list[str]:
        for field_name in _KEYWORD_FIELDS_BY_SOURCE[str(source)]:
            keywords = self._normalize_keywords(
                self._get_value(source_payload, field_name, []),
            )
            if keywords:
                return keywords
        return []

    def _extract_product_id(
        self,
        source_payload: object,
        fallback_product_id: str | None = None,
    ) -> str:
        for field_name in _PRODUCT_ID_FIELDS:
            product_id = self._clean_text(
                self._get_value(source_payload, field_name, ""),
            )
            if product_id:
                return product_id

        for context_field in ("context", "product_context"):
            context = self._get_mapping(source_payload, context_field)
            for field_name in _PRODUCT_ID_FIELDS:
                product_id = self._clean_text(context.get(field_name, ""))
                if product_id:
                    return product_id

        serp_bundle = self._get_value(source_payload, "serp_bundle", None)
        if serp_bundle is not None:
            return self._extract_product_id(serp_bundle)

        return self._clean_text(fallback_product_id or "")

    def _normalize_keywords(self, value: object) -> list[str]:
        if self._is_blank(value):
            return []
        if isinstance(value, str):
            raw_keywords = [value]
        elif isinstance(value, list | tuple | set):
            raw_keywords = list(value)
        else:
            return []

        normalized_keywords: list[str] = []
        for keyword in raw_keywords:
            if self._is_blank(keyword):
                continue
            normalized_keyword = self._clean_text(keyword).lower()
            if normalized_keyword:
                normalized_keywords.append(normalized_keyword)
        return self._dedupe(normalized_keywords)

    @staticmethod
    def _get_value(value: object, field_name: str, default: Any) -> Any:
        if isinstance(value, Mapping):
            return value.get(field_name, default)
        return getattr(value, field_name, default)

    def _get_mapping(self, value: object, field_name: str) -> Mapping[str, Any]:
        raw_value = self._get_value(value, field_name, {})
        if isinstance(raw_value, Mapping):
            return raw_value
        if hasattr(raw_value, "model_dump"):
            dumped_value = raw_value.model_dump(mode="json")
            if isinstance(dumped_value, Mapping):
                return dumped_value
        return {}

    @staticmethod
    def _clean_text(value: object) -> str:
        return " ".join(str(value).strip().split())

    @staticmethod
    def _is_blank(value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, list | tuple | set | dict):
            return not value
        return False

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
    "K19_E_DATA_FLOW",
    "K19_E_MODE",
    "K19_EXTERNAL_ACCESS",
    "K19_IMPORT_SOURCE_MAPPING",
    "K19_IMPORT_STATUS_MAPPING",
    "K19_RUNTIME",
    "KeywordImportService",
]
