"""K18-F final output normalization layer.

This module normalizes K18 Claude output into the system output contract. It
does not call AI providers, execute C14, apply SEO logic, run ranking systems,
mutate K18-A/B/C/D/E, or access production/staging services.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

K18_F_MODE = "final_normalization"
K18_RUNTIME = "no_execution"
K18_EXTERNAL_ACCESS = False

K18_F_DATA_FLOW = (
    "K18-E Pipeline",
    "K18-F Normalization",
    "System Output Layer (K19 / K14 consumption)",
)

_DOMAIN_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

_SCORE_SIGNAL_KEYS = {
    "commercial_intensity_score",
    "competitor_density_score",
    "keyword_quality_score",
}

_COUNT_SIGNAL_KEYS = {
    "competitor_count",
    "ecommerce_competitor_count",
    "keyword_count",
    "source_market_signal_count",
}


class K18FinalOutput:
    """Normalize K18 results for downstream K19/K14 consumption."""

    def normalize(self, k18_input: object, k18_output: object) -> dict[str, object]:
        keywords = self._normalize_keywords(k18_output)
        competitors = self._normalize_competitors(k18_output)
        market_signals = self._normalize_signals(k18_output)

        return {
            "keywords": keywords,
            "competitors": competitors,
            "market_signals": market_signals,
            "context": {
                "reasoning": self._clean_text(
                    self._get_value(k18_output, "reasoning", "")
                ),
                "confidence_score": self._clamp_confidence(k18_output),
                "risk_flags": self._normalize_risks(k18_output),
            },
            "final_quality_score": self._compute_quality_score(
                k18_input,
                k18_output,
                keywords,
                competitors,
                market_signals,
            ),
            "source": "K18_FINAL",
            "pipeline_status": "sealed",
        }

    def _normalize_keywords(self, k18_output: object) -> list[str]:
        keywords = self._first_present(k18_output, "final_keywords", "keywords")
        if not isinstance(keywords, list | tuple | set):
            return []

        normalized_keywords: list[str] = []
        for keyword in keywords:
            if self._is_null_like(keyword):
                continue
            normalized_keyword = self._clean_text(keyword).lower()
            if normalized_keyword:
                normalized_keywords.append(normalized_keyword)
        return self._dedupe(normalized_keywords)

    def _normalize_competitors(self, k18_output: object) -> list[str]:
        competitors = self._first_present(
            k18_output,
            "validated_competitors",
            "competitors",
        )
        if not isinstance(competitors, list | tuple | set):
            return []

        normalized_competitors: list[str] = []
        for competitor in competitors:
            if self._is_null_like(competitor):
                continue
            domain = self._domain_from_link(str(competitor))
            if domain:
                normalized_competitors.append(domain)
        return self._dedupe(normalized_competitors)

    def _normalize_signals(self, k18_output: object) -> list[str]:
        market_validation = self._get_mapping(k18_output, "market_validation")
        normalized_signals: list[str] = []

        for key in sorted(market_validation):
            normalized_key = self._normalize_key(key)
            if not normalized_key:
                continue
            value = market_validation[key]
            normalized_value = self._normalize_signal_value(normalized_key, value)
            if normalized_value is None:
                continue
            normalized_signals.append(f"{normalized_key}={normalized_value}")

        extra_signals = self._get_value(k18_output, "market_signals", [])
        if isinstance(extra_signals, list | tuple | set):
            for signal in extra_signals:
                normalized_signal = self._clean_text(signal)
                if normalized_signal:
                    normalized_signals.append(normalized_signal)

        return self._dedupe(normalized_signals)

    def _normalize_risks(self, k18_output: object) -> list[str]:
        risk_flags = self._get_value(k18_output, "risk_flags", [])
        if not isinstance(risk_flags, list | tuple | set):
            return []

        normalized_risks: list[str] = []
        for risk in risk_flags:
            if self._is_null_like(risk):
                continue
            normalized_risk = self._clean_text(risk).lower()
            if normalized_risk:
                normalized_risks.append(normalized_risk)
        return self._dedupe(normalized_risks)

    def _clamp_confidence(self, k18_output: object) -> float:
        raw_confidence = self._get_value(k18_output, "confidence_score", 0.5)
        return self._clamp_score(raw_confidence, default=0.5)

    def _compute_quality_score(
        self,
        k18_input: object,
        k18_output: object,
        keywords: list[str],
        competitors: list[str],
        market_signals: list[str],
    ) -> float:
        del k18_output
        keyword_completeness = self._keyword_completeness_score(k18_input, keywords)
        competitor_density = self._competitor_density_score(k18_input, competitors)
        signal_consistency = self._signal_consistency_score(market_signals)
        return round(
            min(
                1.0,
                (keyword_completeness * 0.4)
                + (competitor_density * 0.3)
                + (signal_consistency * 0.3),
            ),
            2,
        )

    def _keyword_completeness_score(
        self,
        k18_input: object,
        normalized_keywords: list[str],
    ) -> float:
        input_keywords = self._normalize_text_list(
            self._get_value(k18_input, "keywords", [])
        )
        if not input_keywords:
            return 1.0 if normalized_keywords else 0.0
        return round(min(1.0, len(normalized_keywords) / len(input_keywords)), 2)

    def _competitor_density_score(
        self,
        k18_input: object,
        normalized_competitors: list[str],
    ) -> float:
        input_competitors = self._normalize_text_list(
            self._get_value(k18_input, "competitors", [])
        )
        if not input_competitors:
            return 1.0 if normalized_competitors else 0.0
        return round(
            min(1.0, len(normalized_competitors) / len(input_competitors)),
            2,
        )

    @staticmethod
    def _signal_consistency_score(market_signals: list[str]) -> float:
        if not market_signals:
            return 0.0

        expected_signals = (
            "commercial_intensity_score=",
            "competitor_density_score=",
            "keyword_quality_score=",
        )
        matched_signals = sum(
            1
            for expected_signal in expected_signals
            if any(signal.startswith(expected_signal) for signal in market_signals)
        )
        return round(matched_signals / len(expected_signals), 2)

    def _first_present(self, value: object, *field_names: str) -> object:
        for field_name in field_names:
            field_value = self._get_value(value, field_name, None)
            if not self._is_null_like(field_value):
                return field_value
        return None

    @staticmethod
    def _get_value(value: object, field_name: str, default: Any) -> Any:
        if isinstance(value, Mapping):
            return value.get(field_name, default)
        return getattr(value, field_name, default)

    def _get_mapping(self, value: object, field_name: str) -> dict[str, Any]:
        raw_value = self._get_value(value, field_name, {})
        if isinstance(raw_value, Mapping):
            return dict(raw_value)
        if hasattr(raw_value, "model_dump"):
            dumped_value = raw_value.model_dump(mode="json")
            if isinstance(dumped_value, Mapping):
                return dict(dumped_value)
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
            normalized_item = self._clean_text(item).lower()
            if normalized_item:
                normalized_values.append(normalized_item)
        return self._dedupe(normalized_values)

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

    def _normalize_signal_value(self, key: str, value: object) -> str | None:
        if key in _SCORE_SIGNAL_KEYS:
            return f"{self._clamp_score(value):.2f}"
        if key in _COUNT_SIGNAL_KEYS:
            return str(self._non_negative_int(value))
        if self._is_json_scalar(value):
            normalized_value = self._clean_text(value)
            return normalized_value if normalized_value else None
        return None

    @staticmethod
    def _normalize_key(key: object) -> str:
        return "_".join(str(key).strip().lower().split())

    @staticmethod
    def _clean_text(value: object) -> str:
        return " ".join(str(value).strip().split())

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
    def _is_json_scalar(value: object) -> bool:
        return value is None or isinstance(value, str | int | float | bool)

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
    "K18FinalOutput",
    "K18_EXTERNAL_ACCESS",
    "K18_F_DATA_FLOW",
    "K18_F_MODE",
    "K18_RUNTIME",
]
