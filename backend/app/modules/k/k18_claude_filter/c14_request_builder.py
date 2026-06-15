"""K18-C C14 request builder for Claude validation.

This module builds a structured handoff request for the external C14 execution
layer. It does not call Claude, ChatGPT, C14, external APIs, apply SEO logic,
or target production/staging environments.
"""

from __future__ import annotations

from typing import Any, Mapping

K18_C_MODE = "request_only"
K18_RUNTIME = "no_execution"
K18_EXTERNAL_ACCESS = False
C14_HANDOFF_ONLY = True

K18_C_DATA_FLOW = (
    "K17-F output",
    "K18-A contract",
    "K18-B rule engine",
    "K18-C request builder",
    "C14 (external execution system)",
    "K18-D (future response parser)",
)

_KEYWORD_RULES = (
    "relevance_check",
    "commercial_validation",
    "dedupe",
)

_COMPETITOR_RULES = (
    "domain_validation",
    "ecommerce_priority",
    "tracking_filter",
)

_OUTPUT_FORMAT = {
    "final_keywords": "list[str]",
    "validated_competitors": "list[str]",
    "market_validation": "dict",
    "reasoning": "str",
    "confidence_score": "float",
    "risk_flags": "list[str]",
}


class K18C14RequestBuilder:
    """Build a Claude C14 handoff payload from K17 and K18-B outputs."""

    def build_request(
        self,
        k17_output: object,
        k18_filtered: object,
    ) -> dict[str, Any]:
        return {
            "provider": "claude",
            "model": "claude-filter-v1",
            "task": "second_pass_filter",
            "input": {
                "product_id": self._get_text(k17_output, "product_id"),
                "keywords": self._get_list(k17_output, "selected_keywords"),
                "competitors": self._get_list(k17_output, "filtered_competitors"),
                "market_signals": self._get_list(k17_output, "market_signals"),
                "context": self._context_from_k17_output(k17_output),
            },
            "k18_rules_applied": {
                "keyword_rules": self._get_list(
                    k18_filtered,
                    "keyword_rules",
                    default=list(_KEYWORD_RULES),
                ),
                "competitor_rules": self._get_list(
                    k18_filtered,
                    "competitor_rules",
                    default=list(_COMPETITOR_RULES),
                ),
                "final_keywords": self._get_list(k18_filtered, "final_keywords"),
                "validated_competitors": self._get_list(
                    k18_filtered,
                    "validated_competitors",
                ),
                "market_validation": self._get_mapping(
                    k18_filtered,
                    "market_validation",
                ),
            },
            "output_format": dict(_OUTPUT_FORMAT),
            "execution_mode": "validation_only",
            "meta": {
                "pipeline": "K17 -> K18 -> C14 -> K18-D",
                "source": "K18-C",
            },
        }

    def _get_text(self, value: object, field_name: str) -> str:
        return " ".join(str(self._get_value(value, field_name, "")).strip().split())

    def _context_from_k17_output(self, k17_output: object) -> dict[str, object]:
        return {
            "reasoning": str(self._get_value(k17_output, "reasoning", "")),
            "confidence_score": self._bounded_confidence(
                self._get_value(k17_output, "confidence_score", 0.0),
            ),
            "risk_flags": self._get_list(k17_output, "risk_flags"),
        }

    @staticmethod
    def _get_value(value: object, field_name: str, default: Any) -> Any:
        if isinstance(value, Mapping):
            return value.get(field_name, default)
        return getattr(value, field_name, default)

    def _get_list(
        self,
        value: object,
        field_name: str,
        default: list[str] | None = None,
    ) -> list[str]:
        raw_value = self._get_value(value, field_name, default or [])
        if raw_value is None:
            return []
        if isinstance(raw_value, str):
            return [raw_value] if raw_value else []
        if isinstance(raw_value, list | tuple | set):
            return [str(item) for item in raw_value if str(item)]
        return list(default or [])

    def _get_mapping(self, value: object, field_name: str) -> dict[str, Any]:
        raw_value = self._get_value(value, field_name, {})
        if isinstance(raw_value, Mapping):
            return dict(raw_value)
        if hasattr(raw_value, "model_dump"):
            dumped_value = raw_value.model_dump(mode="json")
            if isinstance(dumped_value, Mapping):
                return dict(dumped_value)
        return {}

    @staticmethod
    def _bounded_confidence(value: object) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return min(1.0, max(0.0, confidence))


class C14Gateway:
    """Interface contract for the external C14 execution layer."""

    @staticmethod
    def send(request: dict[str, Any]) -> dict[str, Any]:
        del request
        raise NotImplementedError("C14 handles execution externally")


__all__ = [
    "C14Gateway",
    "C14_HANDOFF_ONLY",
    "K18C14RequestBuilder",
    "K18_C_DATA_FLOW",
    "K18_C_MODE",
    "K18_EXTERNAL_ACCESS",
    "K18_RUNTIME",
]
