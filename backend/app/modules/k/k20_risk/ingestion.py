"""K20-E risk ingestion layer.

K20-E imports upstream risk signals into K20 RiskTerm storage only. It does not
execute AI logic, calculate risk, apply SEO/ranking logic, expand backend
services, or access production/staging/external systems.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from .models import RiskCategory, RiskLevel, RiskTerm
from .service import RiskService

K20_E_MODE = "ingestion_only"
K20_RUNTIME = "no_execution"
K20_EXTERNAL_ACCESS = False

K20_E_DATA_FLOW = (
    "K13 output",
    "K17 output",
    "K18 output",
    "K20-E ingestion",
    "K20 RiskTerm storage",
)

RiskIngestionInputSource = Literal["K13", "K17", "K18"]

_DEFAULT_PRODUCT_ID = "unassigned"
_DEFAULT_RISK_LEVEL: RiskLevel = "low"
_DEFAULT_CATEGORY: RiskCategory = "platform"

_RISK_LEVEL_ORDER: dict[RiskLevel, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
_VALID_RISK_LEVELS = set(_RISK_LEVEL_ORDER)
_VALID_CATEGORIES: set[str] = {
    "legal",
    "compliance",
    "marketing",
    "safety",
    "platform",
}

_RISK_COLLECTION_KEYS = ("risk_terms", "risk_flags", "risks")
_K13_KEYWORD_COLLECTION_KEYS = (
    "exaggeration_keywords",
    "unsafe_claims",
    "missing_fields",
)
_TERM_KEYS = ("keyword", "term", "risk_term", "flag", "risk", "value", "name")
_LEVEL_KEYS = ("risk_level", "level", "risk_flag", "severity")
_CATEGORY_KEYS = ("category", "risk_category", "type")
_PRODUCT_ID_KEYS = ("product_id", "productId")


class RiskIngestionService:
    """Convert K13/K17/K18 risk output into canonical K20 RiskTerm records."""

    def __init__(self, risk_service: RiskService | None = None) -> None:
        self.risk_service = RiskService() if risk_service is None else risk_service

    def ingest_from_k13(self, k13_output: object) -> list[RiskTerm]:
        return self._convert_to_risk_terms(k13_output, source="K13")

    def ingest_from_k17(self, k17_output: object) -> list[RiskTerm]:
        return self._convert_to_risk_terms(k17_output, source="K17")

    def ingest_from_k18(self, k18_output: object) -> list[RiskTerm]:
        return self._convert_to_risk_terms(k18_output, source="K18")

    def _convert_to_risk_terms(
        self,
        risk_output: object,
        source: RiskIngestionInputSource,
    ) -> list[RiskTerm]:
        product_id = self._product_id_for(risk_output)
        risk_records = self._risk_records_for(risk_output, source=source)
        upserted_terms: list[RiskTerm] = []
        upserted_ids: set[str] = set()

        for risk_record in risk_records:
            term = self._term_for(risk_record)
            if not term:
                continue

            now = datetime.now(UTC)
            incoming_term = RiskTerm(
                id=str(uuid4()),
                product_id=product_id,
                term=term,
                risk_level=self._risk_level_for(risk_record, risk_output),
                category=self._category_for(risk_record, risk_output),
                source=source,
                status="active",
                created_at=now,
                updated_at=now,
            )
            stored_term = self._merge_or_create(incoming_term)
            if stored_term.id in upserted_ids:
                upserted_terms = [
                    stored_term if term.id == stored_term.id else term
                    for term in upserted_terms
                ]
                continue
            upserted_terms.append(stored_term)
            upserted_ids.add(stored_term.id)

        return upserted_terms

    def _merge_or_create(self, incoming_term: RiskTerm) -> RiskTerm:
        existing_term = self._find_existing(
            product_id=incoming_term.product_id,
            term=incoming_term.term,
        )
        if existing_term is None:
            return self.risk_service.create(incoming_term)

        if not self._incoming_level_is_higher(existing_term, incoming_term):
            return existing_term

        updated_term = self.risk_service.update(
            existing_term.id,
            {
                "risk_level": incoming_term.risk_level,
                "category": incoming_term.category,
                "source": incoming_term.source,
                "status": "active",
            },
        )
        if updated_term is None:
            raise ValueError(
                f"risk term disappeared during merge: {existing_term.id}"
            )
        return updated_term

    def _find_existing(self, product_id: str, term: str) -> RiskTerm | None:
        normalized_product_id = self._clean_text(product_id)
        normalized_term = self._clean_text(term).lower()
        for existing_term in self.risk_service.store.values():
            if (
                existing_term.product_id == normalized_product_id
                and existing_term.term == normalized_term
            ):
                return existing_term
        return None

    def _risk_records_for(
        self,
        risk_output: object,
        source: RiskIngestionInputSource,
    ) -> list[object]:
        risk_records: list[object] = []

        for collection_key in _RISK_COLLECTION_KEYS:
            risk_records.extend(
                self._records_from_value(self._get_value(risk_output, collection_key))
            )

        context = self._get_value(risk_output, "context")
        for collection_key in _RISK_COLLECTION_KEYS:
            risk_records.extend(
                self._records_from_value(self._get_value(context, collection_key))
            )

        if source == "K13":
            k13_records: list[object] = []
            for collection_key in _K13_KEYWORD_COLLECTION_KEYS:
                k13_records.extend(
                    self._records_from_value(
                        self._get_value(risk_output, collection_key)
                    )
                )
            if k13_records:
                risk_records.extend(k13_records)
            else:
                risk_records.extend(
                    self._records_from_value(self._get_value(risk_output, "warnings"))
                )

        if risk_records:
            return risk_records

        if self._has_any_value(risk_output, _TERM_KEYS):
            return [risk_output]
        return []

    def _product_id_for(self, risk_output: object) -> str:
        product_id = self._first_value(risk_output, _PRODUCT_ID_KEYS)
        if product_id is None:
            product_id = self._first_value(
                self._get_value(risk_output, "context"),
                _PRODUCT_ID_KEYS,
            )
        cleaned_product_id = self._clean_text(product_id or _DEFAULT_PRODUCT_ID)
        return cleaned_product_id or _DEFAULT_PRODUCT_ID

    def _term_for(self, risk_record: object) -> str:
        if isinstance(risk_record, str):
            return self._clean_text(risk_record)

        term = self._first_value(risk_record, _TERM_KEYS)
        if term is None:
            return ""
        return self._clean_text(term)

    def _risk_level_for(
        self,
        risk_record: object,
        risk_output: object,
    ) -> RiskLevel:
        risk_level = self._normalize_risk_level(
            self._first_value(risk_record, _LEVEL_KEYS)
        )
        if risk_level is not None:
            return risk_level

        risk_level = self._normalize_risk_level(
            self._first_value(risk_output, _LEVEL_KEYS)
        )
        if risk_level is not None:
            return risk_level

        return _DEFAULT_RISK_LEVEL

    def _category_for(
        self,
        risk_record: object,
        risk_output: object,
    ) -> RiskCategory:
        category = self._normalize_category(
            self._first_value(risk_record, _CATEGORY_KEYS)
        )
        if category is not None:
            return category

        category = self._normalize_category(
            self._first_value(risk_output, _CATEGORY_KEYS)
        )
        if category is not None:
            return category

        return _DEFAULT_CATEGORY

    @staticmethod
    def _incoming_level_is_higher(
        existing_term: RiskTerm,
        incoming_term: RiskTerm,
    ) -> bool:
        return (
            _RISK_LEVEL_ORDER[incoming_term.risk_level]
            > _RISK_LEVEL_ORDER[existing_term.risk_level]
        )

    @staticmethod
    def _records_from_value(value: object) -> list[object]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, Mapping):
            return [value]
        if isinstance(value, list | tuple | set):
            return list(value)
        return []

    def _first_value(self, value: object, keys: tuple[str, ...]) -> object | None:
        for key in keys:
            item = self._get_value(value, key)
            if not self._is_null_like(item):
                return item
        return None

    def _has_any_value(self, value: object, keys: tuple[str, ...]) -> bool:
        return self._first_value(value, keys) is not None

    @staticmethod
    def _get_value(value: object, key: str) -> object | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            return value.get(key)
        if hasattr(value, "model_dump"):
            dumped_value = value.model_dump()
            if isinstance(dumped_value, Mapping):
                return dumped_value.get(key)
        return getattr(value, key, None)

    @staticmethod
    def _normalize_risk_level(value: object) -> RiskLevel | None:
        normalized_value = RiskIngestionService._normalize_key(value)
        if normalized_value in _VALID_RISK_LEVELS:
            return cast(RiskLevel, normalized_value)
        return None

    @staticmethod
    def _normalize_category(value: object) -> RiskCategory | None:
        normalized_value = RiskIngestionService._normalize_key(value)
        if normalized_value in _VALID_CATEGORIES:
            return cast(RiskCategory, normalized_value)
        return None

    @staticmethod
    def _normalize_key(value: object) -> str:
        return "_".join(str(value or "").strip().lower().split())

    @staticmethod
    def _clean_text(value: object) -> str:
        return " ".join(str(value).strip().split())

    @staticmethod
    def _is_null_like(value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return False


__all__ = [
    "K20_E_DATA_FLOW",
    "K20_E_MODE",
    "K20_EXTERNAL_ACCESS",
    "K20_RUNTIME",
    "RiskIngestionInputSource",
    "RiskIngestionService",
]
