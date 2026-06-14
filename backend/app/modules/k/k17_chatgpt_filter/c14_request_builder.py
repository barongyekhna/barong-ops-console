"""K17-C C14 request builder.

This module builds a structured handoff request for the future C14 execution
layer. It does not read API keys, call ChatGPT/OpenAI/Claude, implement HTTP
transport, execute AI logic, apply SEO ranking, or target production/staging
environments.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .schema import ChatGPTFilterInput, ChatGPTFilterOutput

K17_C_MODE = "request_only"
K17_C_EXTERNAL_EXECUTION = False
C14_HANDOFF_ONLY = True

_REQUIRED_OUTPUT_FIELDS = [
    "selected_keywords",
    "filtered_competitors",
    "market_signals",
    "reasoning",
    "confidence_score",
    "risk_flags",
]


class K17C14RequestBuilder:
    """Build a standard C14 handoff payload from K17 filter contracts."""

    def build_chatgpt_request(
        self,
        filter_input: ChatGPTFilterInput,
        filter_output: ChatGPTFilterOutput,
    ) -> dict[str, Any]:
        return {
            "provider": "chatgpt",
            "model": "gpt-filter-v1",
            "task": "keyword_and_competitor_filtering",
            "input": {
                "serp_data": self._serialize(filter_input.serp_bundle),
                "product_context": filter_input.product_context,
                "market": filter_input.market,
                "query": filter_input.query,
            },
            "rules_applied": {
                "keyword_filter": list(filter_output.selected_keywords),
                "competitor_filter": list(filter_output.filtered_competitors),
                "market_signals": list(filter_output.market_signals),
            },
            "output_format": {
                "type": "structured_json",
                "required_fields": list(_REQUIRED_OUTPUT_FIELDS),
            },
            "execution_mode": "filter_only",
            "meta": {
                "source": "K17-C",
                "pipeline": "K16 -> K17-B -> C14 -> K17-D",
            },
        }

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value


class C14Gateway:
    """Interface contract for the external C14 execution layer."""

    @staticmethod
    def send(request: dict[str, Any]) -> dict[str, Any]:
        del request
        raise NotImplementedError("C14 handles execution externally")


__all__ = [
    "K17C14RequestBuilder",
    "C14Gateway",
    "K17_C_MODE",
    "K17_C_EXTERNAL_EXECUTION",
    "C14_HANDOFF_ONLY",
]
