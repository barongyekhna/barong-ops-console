"""K20-F final risk governance engine.

K20-F resolves ingested K20 risk terms into the final governance truth layer.
It applies deterministic rule resolution only. It does not execute AI
inference, apply SEO/ranking logic, expand backend services, access external
APIs, or target production/staging systems.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from .models import RiskLevel

K20_F_MODE = "governance_only"
K20_RUNTIME = "no_execution"
K20_FINAL_AUTHORITY = "human_priority"
K20_EXTERNAL_ACCESS = False

K20_F_DATA_FLOW = (
    "K20-E ingestion",
    "RiskGovernanceEngine",
    "final system truth layer",
)

GovernanceSource = Literal["manual", "K18", "K17", "K16", "K15", "K13"]

_DEFAULT_PRODUCT_ID = "unassigned"
_DEFAULT_RISK_LEVEL: RiskLevel = "low"
_DEFAULT_SOURCE = "system"
_DEFAULT_STATUS = "active"

_SOURCE_PRIORITY: dict[str, int] = {
    "manual": 5,
    "K18": 4,
    "K17": 3,
    "K16": 2,
    "K15": 1,
    "K13": 0,
}
_SEVERITY_PRIORITY: dict[RiskLevel, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
_VALID_RISK_LEVELS = set(_SEVERITY_PRIORITY)


class RiskGovernanceEngine:
    """Resolve K20 risk term conflicts into one final term per product/term."""

    def resolve(self, risk_terms: list[object]) -> dict[str, dict[str, object]]:
        grouped = self._group_by_product(risk_terms)

        return {
            product_id: self._resolve_conflicts(group)
            for product_id, group in grouped.items()
        }

    def _group_by_product(
        self,
        risk_terms: list[object],
    ) -> dict[str, list[object]]:
        grouped_terms: dict[str, list[object]] = {}
        for risk_term in risk_terms:
            product_id = self._product_id_for(risk_term)
            grouped_terms.setdefault(product_id, []).append(risk_term)
        return grouped_terms

    def _resolve_conflicts(self, risk_terms: list[object]) -> dict[str, object]:
        grouped_terms = self._group_by_term(risk_terms)
        final_risk_terms: list[dict[str, object]] = []
        resolved_conflicts: list[dict[str, object]] = []
        override_log: list[dict[str, object]] = []

        for term_key in sorted(grouped_terms):
            candidates = grouped_terms[term_key]
            selected_term = self._select_final_term(candidates)
            final_risk_terms.append(self._to_governed_term(selected_term))

            conflict = self._conflict_record(candidates, selected_term)
            if conflict is not None:
                resolved_conflicts.append(conflict)

            override = self._override_record(candidates, selected_term)
            if override is not None:
                override_log.append(override)

        return {
            "final_risk_terms": final_risk_terms,
            "resolved_conflicts": resolved_conflicts,
            "override_log": override_log,
            "severity_summary": self._severity_summary(final_risk_terms),
        }

    def _group_by_term(
        self,
        risk_terms: list[object],
    ) -> dict[str, list[object]]:
        grouped_terms: dict[str, list[object]] = {}
        for risk_term in risk_terms:
            term = self._term_for(risk_term)
            if not term:
                continue
            product_id = self._product_id_for(risk_term)
            grouped_terms.setdefault(f"{product_id}:{term}", []).append(risk_term)
        return grouped_terms

    def _select_final_term(self, candidates: list[object]) -> object:
        manual_terms = [
            candidate
            for candidate in candidates
            if self._source_for(candidate) == "manual"
        ]
        if manual_terms:
            return max(manual_terms, key=self._manual_resolution_key)
        return max(candidates, key=self._system_resolution_key)

    def _manual_resolution_key(self, risk_term: object) -> tuple[int, float, str]:
        return (
            self._severity_value(risk_term),
            self._updated_timestamp(risk_term),
            self._id_for(risk_term),
        )

    def _system_resolution_key(
        self,
        risk_term: object,
    ) -> tuple[int, int, float, str]:
        return (
            self._severity_value(risk_term),
            self._source_priority(risk_term),
            self._updated_timestamp(risk_term),
            self._id_for(risk_term),
        )

    def _conflict_record(
        self,
        candidates: list[object],
        selected_term: object,
    ) -> dict[str, object] | None:
        if len(candidates) <= 1:
            return None

        candidate_levels = sorted(
            {self._risk_level_for(candidate) for candidate in candidates},
            key=lambda risk_level: _SEVERITY_PRIORITY[risk_level],
        )
        conflict_type = (
            "risk_level_conflict"
            if len(candidate_levels) > 1
            else "duplicate_term"
        )
        return {
            "product_id": self._product_id_for(selected_term),
            "term": self._term_for(selected_term),
            "conflict_type": conflict_type,
            "candidate_count": len(candidates),
            "candidate_sources": sorted(
                {self._source_for(candidate) for candidate in candidates}
            ),
            "candidate_risk_levels": candidate_levels,
            "selected_source": self._source_for(selected_term),
            "selected_risk_level": self._risk_level_for(selected_term),
        }

    def _override_record(
        self,
        candidates: list[object],
        selected_term: object,
    ) -> dict[str, object] | None:
        if len(candidates) <= 1:
            return None

        selected_source = self._source_for(selected_term)
        candidate_sources = {self._source_for(candidate) for candidate in candidates}
        candidate_severities = {
            self._risk_level_for(candidate) for candidate in candidates
        }

        if selected_source == "manual" and len(candidate_sources) > 1:
            reason = "manual_final_authority"
        elif len(candidate_severities) > 1:
            reason = "highest_severity_selected"
        else:
            reason = "source_priority_tiebreak"

        return {
            "product_id": self._product_id_for(selected_term),
            "term": self._term_for(selected_term),
            "selected_source": selected_source,
            "selected_risk_level": self._risk_level_for(selected_term),
            "reason": reason,
            "manual_protected": selected_source == "manual",
        }

    def _to_governed_term(self, risk_term: object) -> dict[str, object]:
        return {
            "id": self._id_for(risk_term),
            "product_id": self._product_id_for(risk_term),
            "term": self._term_for(risk_term),
            "risk_level": self._risk_level_for(risk_term),
            "category": self._clean_text(self._get_value(risk_term, "category")),
            "source": self._source_for(risk_term),
            "status": self._status_for(risk_term),
            "final_authority": (
                "manual" if self._source_for(risk_term) == "manual" else "system"
            ),
        }

    @staticmethod
    def _severity_summary(
        final_risk_terms: list[dict[str, object]],
    ) -> dict[RiskLevel, int]:
        summary: dict[RiskLevel, int] = {
            "low": 0,
            "medium": 0,
            "high": 0,
            "critical": 0,
        }
        for risk_term in final_risk_terms:
            risk_level = risk_term.get("risk_level")
            if risk_level in _VALID_RISK_LEVELS:
                summary[cast(RiskLevel, risk_level)] += 1
        return summary

    def _product_id_for(self, risk_term: object) -> str:
        product_id = self._clean_text(self._get_value(risk_term, "product_id"))
        return product_id or _DEFAULT_PRODUCT_ID

    def _term_for(self, risk_term: object) -> str:
        return self._clean_text(self._get_value(risk_term, "term")).lower()

    def _risk_level_for(self, risk_term: object) -> RiskLevel:
        risk_level = self._clean_text(
            self._get_value(risk_term, "risk_level")
        ).lower()
        if risk_level in _VALID_RISK_LEVELS:
            return cast(RiskLevel, risk_level)
        return _DEFAULT_RISK_LEVEL

    def _source_for(self, risk_term: object) -> str:
        source = self._clean_text(self._get_value(risk_term, "source"))
        if not source:
            return _DEFAULT_SOURCE
        if source.lower() == "manual":
            return "manual"
        normalized_source = source.upper()
        if normalized_source in _SOURCE_PRIORITY:
            return normalized_source
        return source

    def _status_for(self, risk_term: object) -> str:
        status = self._clean_text(self._get_value(risk_term, "status"))
        return status or _DEFAULT_STATUS

    def _id_for(self, risk_term: object) -> str:
        return self._clean_text(self._get_value(risk_term, "id"))

    def _severity_value(self, risk_term: object) -> int:
        return _SEVERITY_PRIORITY[self._risk_level_for(risk_term)]

    def _source_priority(self, risk_term: object) -> int:
        return _SOURCE_PRIORITY.get(self._source_for(risk_term), -1)

    def _updated_timestamp(self, risk_term: object) -> float:
        updated_at = self._get_value(risk_term, "updated_at")
        if isinstance(updated_at, datetime):
            return updated_at.timestamp()
        return 0.0

    @staticmethod
    def _get_value(value: object, key: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(key)
        if hasattr(value, "model_dump"):
            dumped_value = value.model_dump()
            if isinstance(dumped_value, Mapping):
                return dumped_value.get(key)
        return getattr(value, key, None)

    @staticmethod
    def _clean_text(value: object) -> str:
        return " ".join(str(value or "").strip().split())


__all__ = [
    "GovernanceSource",
    "K20_EXTERNAL_ACCESS",
    "K20_F_DATA_FLOW",
    "K20_F_MODE",
    "K20_FINAL_AUTHORITY",
    "K20_RUNTIME",
    "RiskGovernanceEngine",
]
