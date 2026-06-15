"""K20-C risk service layer.

This module provides in-memory CRUD helpers and deterministic risk-term
creation through the K20-B rules engine only. It does not call AI providers,
perform SEO or ranking logic, expose APIs, modify K20-A/B, or access external
systems.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping, cast
from uuid import uuid4

from .models import (
    RiskCategory,
    RiskLevel,
    RiskTerm,
    RiskTermSource,
)
from .rules import RiskDetectionRules

K20_C_MODE = "service_only"
K20_RUNTIME = "no_execution"
K20_EXTERNAL_ACCESS = False

K20_C_DATA_FLOW = (
    "input keywords",
    "K20-B rules engine",
    "K20-C service layer",
    "RiskTerm objects",
    "K20-D UI layer",
)

RISK_STORE: dict[str, RiskTerm] = {}

_DEFAULT_PRODUCT_ID = "unassigned"

_PATCHABLE_FIELDS = {
    "product_id",
    "term",
    "risk_level",
    "category",
    "source",
    "status",
}


class RiskService:
    """CRUD and deterministic detection facade for RiskTerm records."""

    def __init__(
        self,
        store: dict[str, RiskTerm] | None = None,
        rule_engine: RiskDetectionRules | None = None,
    ) -> None:
        self.store = RISK_STORE if store is None else store
        self.rule_engine = RiskDetectionRules() if rule_engine is None else rule_engine

    def detect(
        self,
        keyword: str,
        product_id: str = _DEFAULT_PRODUCT_ID,
        source: RiskTermSource = "manual",
        risk_id: str | None = None,
        persist: bool = True,
    ) -> RiskTerm:
        result = self.rule_engine.detect_keyword_risk(keyword)
        now = datetime.now(UTC)
        risk_term = RiskTerm(
            id=risk_id or str(uuid4()),
            product_id=product_id,
            term=keyword,
            risk_level=cast(RiskLevel, result["risk_level"]),
            category=cast(RiskCategory, result["category"]),
            source=source,
            status="active",
            created_at=now,
            updated_at=now,
        )
        if not persist:
            return risk_term
        return self.create(risk_term)

    def batch_detect(
        self,
        keywords: list[str],
        product_id: str = _DEFAULT_PRODUCT_ID,
        source: RiskTermSource = "manual",
        persist: bool = True,
    ) -> list[RiskTerm]:
        return [
            self.detect(
                keyword,
                product_id=product_id,
                source=source,
                persist=persist,
            )
            for keyword in keywords
            if not self._is_blank(keyword)
        ]

    def create(self, risk_term: RiskTerm | Mapping[str, Any]) -> RiskTerm:
        entry = self._validate_entry(risk_term)
        if entry.id in self.store:
            raise ValueError(f"risk term already exists: {entry.id}")
        self.store[entry.id] = entry
        return entry

    def get(self, risk_id: str) -> RiskTerm | None:
        return self.store.get(self._clean_text(risk_id))

    def get_by_product(self, product_id: str) -> list[RiskTerm]:
        cleaned_product_id = self._clean_text(product_id)
        return [
            entry
            for entry in self.store.values()
            if entry.product_id == cleaned_product_id
        ]

    def update(
        self,
        risk_id: str,
        data: Mapping[str, Any],
    ) -> RiskTerm | None:
        existing_entry = self.get(risk_id)
        if existing_entry is None:
            return None

        patch = {
            key: value
            for key, value in data.items()
            if key in _PATCHABLE_FIELDS and value is not None
        }
        if not patch:
            return existing_entry

        updated_entry = existing_entry.model_copy(
            update={
                **patch,
                "updated_at": datetime.now(UTC),
            }
        )
        validated_entry = RiskTerm(**updated_entry.model_dump())
        self.store[existing_entry.id] = validated_entry
        return validated_entry

    def delete(self, risk_id: str) -> RiskTerm | None:
        existing_entry = self.get(risk_id)
        if existing_entry is None:
            return None

        ignored_entry = existing_entry.model_copy(
            update={
                "status": "ignored",
                "updated_at": datetime.now(UTC),
            }
        )
        self.store[existing_entry.id] = ignored_entry
        return ignored_entry

    @staticmethod
    def _validate_entry(risk_term: RiskTerm | Mapping[str, Any]) -> RiskTerm:
        if isinstance(risk_term, RiskTerm):
            return risk_term
        return RiskTerm(**dict(risk_term))

    @staticmethod
    def _clean_text(value: object) -> str:
        return " ".join(str(value).strip().split())

    @staticmethod
    def _is_blank(value: object) -> bool:
        return not str(value).strip()


__all__ = [
    "K20_C_DATA_FLOW",
    "K20_C_MODE",
    "K20_EXTERNAL_ACCESS",
    "K20_RUNTIME",
    "RISK_STORE",
    "RiskService",
]
