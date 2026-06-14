"""K17-D C14 response parser.

This module normalizes raw C14 response payloads into K17/K18-consumable
structures. It does not call AI providers, execute C14, perform SEO ranking,
mutate upstream contracts, or access production/staging services.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .schema import ChatGPTFilterOutput

K17_D_MODE = "response_parser_only"
K17_RUNTIME = "no_execution"
K17_EXTERNAL_ACCESS = False

_REQUIRED_FIELDS = (
    "selected_keywords",
    "filtered_competitors",
    "market_signals",
    "reasoning",
    "confidence_score",
    "risk_flags",
)
_INVALID_LINK_MARKERS = (
    "404",
    "login",
    "not-found",
    "redirect",
    "redir",
    "signup",
    "track",
    "utm_",
    "utm=",
)


class K17ResponseParser:
    """Normalize C14 output into the K17-A output contract."""

    def parse(self, raw_c14_response: dict[str, Any]) -> dict[str, object]:
        parsed = {
            "selected_keywords": self._normalize_keywords(raw_c14_response),
            "filtered_competitors": self._normalize_competitors(raw_c14_response),
            "market_signals": self._extract_signals(raw_c14_response),
            "reasoning": str(raw_c14_response.get("reasoning", "")),
            "confidence_score": self._normalize_confidence(raw_c14_response),
            "risk_flags": self._extract_risks(raw_c14_response),
        }
        return parsed

    def parse_to_contract(
        self,
        raw_c14_response: dict[str, Any],
    ) -> ChatGPTFilterOutput:
        return ChatGPTFilterOutput(**self.parse(raw_c14_response))

    def _normalize_keywords(
        self,
        raw_c14_response: dict[str, Any],
    ) -> list[str]:
        keywords = raw_c14_response.get("selected_keywords", [])
        if not isinstance(keywords, list):
            return []

        normalized_keywords = []
        for keyword in keywords:
            normalized_keyword = " ".join(str(keyword).strip().lower().split())
            if normalized_keyword:
                normalized_keywords.append(normalized_keyword)
        return self._dedupe(normalized_keywords)

    def _normalize_competitors(
        self,
        raw_c14_response: dict[str, Any],
    ) -> list[str]:
        competitors = raw_c14_response.get("filtered_competitors", [])
        if not isinstance(competitors, list):
            return []

        normalized_competitors = []
        for competitor in competitors:
            domain = self._domain_from_link(str(competitor))
            if not domain:
                continue
            if self._is_invalid_link(str(competitor)):
                continue
            normalized_competitors.append(domain)
        return self._dedupe(normalized_competitors)

    def _extract_signals(
        self,
        raw_c14_response: dict[str, Any],
    ) -> list[str]:
        market_signals = raw_c14_response.get("market_signals", [])
        if not isinstance(market_signals, list):
            return []

        normalized_signals = []
        for signal in market_signals:
            normalized_signal = " ".join(str(signal).strip().split())
            if normalized_signal:
                normalized_signals.append(normalized_signal)
        return self._dedupe(normalized_signals)

    def _normalize_confidence(self, raw_c14_response: dict[str, Any]) -> float:
        raw_confidence = raw_c14_response.get("confidence_score", 0.5)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        return min(1.0, max(0.0, confidence))

    def _extract_risks(self, raw_c14_response: dict[str, Any]) -> list[str]:
        risk_flags = raw_c14_response.get("risk_flags", [])
        normalized_risks = []

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
        if not value:
            return ""

        parsed = urlparse(value if "://" in value else f"https://{value}")
        if not parsed.netloc:
            return ""

        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        if "." not in domain:
            return ""
        return domain

    @staticmethod
    def _is_invalid_link(link: str) -> bool:
        normalized_link = link.strip().lower()
        return any(marker in normalized_link for marker in _INVALID_LINK_MARKERS)

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
    "K17ResponseParser",
    "K17_D_MODE",
    "K17_RUNTIME",
    "K17_EXTERNAL_ACCESS",
]
