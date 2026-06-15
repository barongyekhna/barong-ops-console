"""K18-E K17-to-K18 pipeline adapter.

This module transforms K17-F output into the K18-A Claude input contract. It
does not call AI providers, execute C14, apply SEO logic, run ranking systems,
mutate K18-A/B/C/D, or access production/staging services.
"""

from __future__ import annotations

from typing import Any, Mapping

from .schema import ClaudeFilterInput

K18_E_MODE = "pipeline_only"
K18_RUNTIME = "no_execution"
K18_EXTERNAL_ACCESS = False

K18_E_DATA_FLOW = (
    "K17-F output",
    "K18-E Pipeline Adapter",
    "K18-A Contract",
    "K18-B Rule Engine",
    "K18-C C14 Request",
    "K18-D Response Parser",
)


class K18PipelineAdapter:
    """Adapt K17-F output into ClaudeFilterInput without executing C14."""

    def transform(self, k17_output: object) -> ClaudeFilterInput:
        flattened_output = self._flatten_k17_output(k17_output)

        return ClaudeFilterInput(
            keywords=self._normalize_text_list(flattened_output.get("keywords")),
            competitors=self._normalize_text_list(
                flattened_output.get("competitors"),
            ),
            market_signals=self._normalize_text_list(
                flattened_output.get("market_signals"),
            ),
            context={
                "reasoning": self._clean_text(flattened_output.get("reasoning", "")),
                "confidence_score": self._normalize_confidence(
                    flattened_output.get("confidence_score"),
                ),
                "risk_flags": self._normalize_text_list(
                    flattened_output.get("risk_flags"),
                ),
            },
            intent="k18_second_pass_validation",
        )

    def _flatten_k17_output(self, k17_output: object) -> dict[str, object]:
        context = self._get_mapping(k17_output, "context")
        return self._remove_null_fields(
            {
                "keywords": self._first_present(
                    k17_output,
                    "keywords",
                    "selected_keywords",
                ),
                "competitors": self._first_present(
                    k17_output,
                    "competitors",
                    "filtered_competitors",
                ),
                "market_signals": self._get_value(
                    k17_output,
                    "market_signals",
                    [],
                ),
                "reasoning": self._first_present(
                    k17_output,
                    "reasoning",
                    context=context,
                ),
                "confidence_score": self._first_present(
                    k17_output,
                    "confidence_score",
                    "confidence",
                    context=context,
                ),
                "risk_flags": self._first_present(
                    k17_output,
                    "risk_flags",
                    context=context,
                ),
            }
        )

    def _first_present(
        self,
        value: object,
        *field_names: str,
        context: Mapping[str, Any] | None = None,
    ) -> object:
        for field_name in field_names:
            direct_value = self._get_value(value, field_name, None)
            if not self._is_null_like(direct_value):
                return direct_value
            if context:
                context_value = context.get(field_name)
                if not self._is_null_like(context_value):
                    return context_value
        return None

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

    def _normalize_text_list(self, value: object) -> list[str]:
        if self._is_null_like(value):
            return []
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list | tuple | set):
            values = list(value)
        else:
            return []

        normalized_values: list[str] = []
        for item in values:
            if self._is_null_like(item):
                continue
            normalized_item = self._clean_text(item)
            if normalized_item:
                normalized_values.append(normalized_item)
        return self._dedupe(normalized_values)

    @staticmethod
    def _clean_text(value: object) -> str:
        return " ".join(str(value).strip().split())

    @staticmethod
    def _normalize_confidence(value: object) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.0
        return min(1.0, max(0.0, confidence))

    def _remove_null_fields(self, value: dict[str, object]) -> dict[str, object]:
        return {
            key: item
            for key, item in value.items()
            if not self._is_null_like(item)
        }

    @staticmethod
    def _is_null_like(value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if isinstance(value, list | tuple | set | dict) and not value:
            return True
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
    "K18PipelineAdapter",
    "K18_E_DATA_FLOW",
    "K18_E_MODE",
    "K18_EXTERNAL_ACCESS",
    "K18_RUNTIME",
]
