"""K18-D Claude C14 response parser.

This module normalizes raw C14 Claude response payloads into the K18 output
contract. It does not call AI providers, execute C14, apply SEO logic, run
ranking systems, mutate K18-A/B/C, or access production/staging services.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .schema import ClaudeFilterOutput

K18_D_MODE = "parser_only"
K18_RUNTIME = "no_execution"
K18_EXTERNAL_ACCESS = False

K18_D_DATA_FLOW = (
    "K17-C request",
    "C14 Claude execution",
    "K18-D Response Parser",
    "K18 final output",
)

_REQUIRED_FIELDS = (
    "final_keywords",
    "validated_competitors",
    "market_validation",
    "reasoning",
    "confidence_score",
    "risk_flags",
)

_SCORE_FIELDS = {
    "commercial_intensity_score",
    "competitor_density_score",
    "keyword_quality_score",
}

_COUNT_FIELDS = {
    "competitor_count",
    "ecommerce_competitor_count",
    "keyword_count",
    "source_market_signal_count",
}

_DOMAIN_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


class K18ResponseParser:
    """Normalize raw Claude C14 output into the K18-A output contract."""

    def parse(self, raw_c14_response: dict[str, Any]) -> dict[str, object]:
        return {
            "final_keywords": self._extract_keywords(raw_c14_response),
            "validated_competitors": self._extract_competitors(raw_c14_response),
            "market_validation": self._extract_market_signals(raw_c14_response),
            "reasoning": str(raw_c14_response.get("reasoning", "")),
            "confidence_score": self._normalize_confidence(raw_c14_response),
            "risk_flags": self._extract_risk_flags(raw_c14_response),
        }

    def parse_to_contract(
        self,
        raw_c14_response: dict[str, Any],
    ) -> ClaudeFilterOutput:
        return ClaudeFilterOutput(**self.parse(raw_c14_response))

    def _extract_keywords(self, raw_c14_response: dict[str, Any]) -> list[str]:
        keywords = raw_c14_response.get("final_keywords", [])
        if not isinstance(keywords, list):
            return []

        normalized_keywords: list[str] = []
        for keyword in keywords:
            normalized_keyword = " ".join(str(keyword).strip().lower().split())
            if normalized_keyword:
                normalized_keywords.append(normalized_keyword)
        return self._dedupe(normalized_keywords)

    def _extract_competitors(self, raw_c14_response: dict[str, Any]) -> list[str]:
        competitors = raw_c14_response.get("validated_competitors", [])
        if not isinstance(competitors, list):
            return []

        normalized_competitors: list[str] = []
        for competitor in competitors:
            domain = self._domain_from_link(str(competitor))
            if domain:
                normalized_competitors.append(domain)
        return self._dedupe(normalized_competitors)

    def _extract_market_signals(
        self,
        raw_c14_response: dict[str, Any],
    ) -> dict[str, Any]:
        market_validation = raw_c14_response.get("market_validation", {})
        if not isinstance(market_validation, Mapping):
            return {}

        normalized_validation: dict[str, Any] = {}
        for key, value in market_validation.items():
            normalized_key = self._normalize_key(key)
            if not normalized_key:
                continue
            if normalized_key in _SCORE_FIELDS:
                normalized_validation[normalized_key] = self._clamp_score(value)
                continue
            if normalized_key in _COUNT_FIELDS:
                normalized_validation[normalized_key] = self._non_negative_int(value)
                continue
            if self._is_json_safe_value(value):
                normalized_validation[normalized_key] = value
        return normalized_validation

    def _normalize_confidence(self, raw_c14_response: dict[str, Any]) -> float:
        raw_confidence = raw_c14_response.get("confidence_score", 0.5)
        return self._clamp_score(raw_confidence, default=0.5)

    def _extract_risk_flags(self, raw_c14_response: dict[str, Any]) -> list[str]:
        risk_flags = raw_c14_response.get("risk_flags", [])
        normalized_risks: list[str] = []

        if isinstance(risk_flags, list):
            for risk in risk_flags:
                normalized_risk = " ".join(str(risk).strip().lower().split())
                if normalized_risk:
                    normalized_risks.append(normalized_risk)

        missing_fields = [
            field for field in _REQUIRED_FIELDS if field not in raw_c14_response
        ]
        normalized_risks.extend(
            f"missing_field:{field}" for field in missing_fields
        )

        if self._normalize_confidence(raw_c14_response) < 0.4:
            normalized_risks.append("low_confidence")

        return self._dedupe(normalized_risks)

    @staticmethod
    def _domain_from_link(link: str) -> str:
        value = link.strip().lower()
        if not value or any(character.isspace() for character in value):
            return ""

        parsed = urlparse(value if "://" in value else f"https://{value}")
        domain = parsed.netloc
        if not domain:
            return ""
        if "@" in domain:
            domain = domain.rsplit("@", 1)[-1]
        if ":" in domain:
            domain = domain.split(":", 1)[0]
        if domain.startswith("www."):
            domain = domain[4:]
        domain = domain.strip(".")
        if not _DOMAIN_PATTERN.match(domain):
            return ""
        return domain

    @staticmethod
    def _normalize_key(key: object) -> str:
        return "_".join(str(key).strip().lower().split())

    @staticmethod
    def _clamp_score(value: object, default: float = 0.0) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = default
        return min(1.0, max(0.0, score))

    @staticmethod
    def _non_negative_int(value: object) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, count)

    @staticmethod
    def _is_json_safe_value(value: object) -> bool:
        if value is None or isinstance(value, str | int | float | bool):
            return True
        if isinstance(value, list):
            return all(K18ResponseParser._is_json_safe_value(item) for item in value)
        if isinstance(value, Mapping):
            return all(
                isinstance(key, str)
                and K18ResponseParser._is_json_safe_value(item)
                for key, item in value.items()
            )
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
    "K18ResponseParser",
    "K18_D_DATA_FLOW",
    "K18_D_MODE",
    "K18_EXTERNAL_ACCESS",
    "K18_RUNTIME",
]
