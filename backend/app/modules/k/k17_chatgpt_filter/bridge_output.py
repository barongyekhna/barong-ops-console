"""K17-F final output bridge for K18 input.

This module formats K17 output into a deterministic K18 input structure. It
does not call AI providers, C14, external APIs, SEO systems, ranking systems, or
production/staging services.
"""

from __future__ import annotations

from .schema import ChatGPTFilterOutput

K17_F_MODE = "final_output_only"
K17_RUNTIME = "no_execution"
K17_EXTERNAL_ACCESS = False


class K17BridgeOutput:
    """Build K18-ready input from normalized K17 results."""

    def build_k18_input(
        self,
        k17_result: ChatGPTFilterOutput,
        product_id: str | None = None,
    ) -> dict[str, object]:
        output = {
            "product_id": self._product_id_for(k17_result, product_id),
            "keywords": self._normalize_keywords(k17_result.selected_keywords),
            "competitors": self._dedupe_text(k17_result.filtered_competitors),
            "market_signals": self._normalize_market_signals(
                k17_result.market_signals,
            ),
            "context": self._context_for(k17_result),
            "intent": "k18_second_pass_filter",
            "source": "K17_FINAL_OUTPUT",
        }
        return self._remove_null_fields(output)

    def _product_id_for(
        self,
        k17_result: ChatGPTFilterOutput,
        fallback_product_id: str | None,
    ) -> str:
        product_id = getattr(k17_result, "product_id", "")
        if not product_id and isinstance(k17_result, dict):
            product_id = k17_result.get("product_id", "")
        return self._clean_text(product_id or fallback_product_id or "")

    def _context_for(self, k17_result: ChatGPTFilterOutput) -> dict[str, object]:
        context = {
            "reasoning": self._clean_text(k17_result.reasoning),
            "confidence": min(1.0, max(0.0, k17_result.confidence_score)),
            "risk_flags": self._dedupe_text(k17_result.risk_flags),
        }
        return self._remove_null_fields(context)

    def _normalize_keywords(self, keywords: list[str]) -> list[str]:
        normalized_keywords = []
        for keyword in keywords:
            normalized_keyword = self._clean_text(keyword).lower()
            if normalized_keyword:
                normalized_keywords.append(normalized_keyword)
        return self._dedupe_text(normalized_keywords)

    def _normalize_market_signals(self, market_signals: list[str]) -> list[str]:
        normalized_signals = []
        for signal in market_signals:
            normalized_signal = self._clean_text(signal)
            if normalized_signal:
                normalized_signals.append(normalized_signal)
        return self._dedupe_text(normalized_signals)

    @staticmethod
    def _clean_text(value: str) -> str:
        return " ".join(str(value).strip().split())

    @staticmethod
    def _dedupe_text(values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = " ".join(str(value).strip().split())
            key = text.lower()
            if not text or key in seen:
                continue
            deduped.append(text)
            seen.add(key)
        return deduped

    def _remove_null_fields(self, value: dict[str, object]) -> dict[str, object]:
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            if item is None:
                continue
            if isinstance(item, str) and not item:
                continue
            if isinstance(item, list) and not item:
                continue
            if isinstance(item, dict):
                nested = self._remove_null_fields(item)
                if not nested:
                    continue
                cleaned[key] = nested
                continue
            cleaned[key] = item
        return cleaned


__all__ = [
    "K17BridgeOutput",
    "K17_F_MODE",
    "K17_RUNTIME",
    "K17_EXTERNAL_ACCESS",
]
