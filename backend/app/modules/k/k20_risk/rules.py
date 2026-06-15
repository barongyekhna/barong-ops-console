"""K20-B deterministic risk detection rule definitions.

This module defines local string-matching risk rules only. It does not call AI
providers, use ML inference, perform SEO or ranking logic, persist data, expose
APIs, or access external systems.
"""

from __future__ import annotations

from typing import NamedTuple

from .models import RiskCategory, RiskLevel

K20_B_MODE = "rule_definition_only"
K20_RUNTIME = "no_execution"
K20_EXTERNAL_ACCESS = False

K20_B_DATA_FLOW = (
    "K19 keywords",
    "K20-B rule engine",
    "RiskTerm generation",
    "K20-C service layer",
)

RISK_LEVEL_ACTIONS: dict[RiskLevel, str] = {
    "low": "warning",
    "medium": "review",
    "high": "block suggestion",
    "critical": "future enforcement block",
}


class RiskRule(NamedTuple):
    """Single deterministic risk trigger definition."""

    trigger: str
    risk_level: RiskLevel
    category: RiskCategory


MARKETING_RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule("best", "low", "marketing"),
    RiskRule("#1", "medium", "marketing"),
    RiskRule("guaranteed", "high", "marketing"),
    RiskRule("100% safe", "high", "marketing"),
    RiskRule("miracle", "high", "marketing"),
    RiskRule("instant cure", "critical", "marketing"),
)

LEGAL_RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule("cure disease", "critical", "legal"),
    RiskRule("legal claim guarantees", "high", "legal"),
    RiskRule("medical effectiveness claims", "high", "legal"),
)

COMPLIANCE_RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule("restricted product claims", "high", "compliance"),
    RiskRule("platform forbidden terms", "high", "compliance"),
    RiskRule("deceptive pricing claims", "medium", "compliance"),
)

SAFETY_RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule("dangerous use", "high", "safety"),
    RiskRule("hazardous claims", "high", "safety"),
    RiskRule("prohibited materials", "critical", "safety"),
)

PLATFORM_RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule("marketplace banned", "high", "platform"),
    RiskRule("listing policy violation", "high", "platform"),
    RiskRule("platform restricted", "medium", "platform"),
)

RISK_RULES_BY_CATEGORY: dict[RiskCategory, tuple[RiskRule, ...]] = {
    "marketing": MARKETING_RISK_RULES,
    "legal": LEGAL_RISK_RULES,
    "compliance": COMPLIANCE_RISK_RULES,
    "safety": SAFETY_RISK_RULES,
    "platform": PLATFORM_RISK_RULES,
}

RISK_RULES: tuple[RiskRule, ...] = (
    *LEGAL_RISK_RULES,
    *SAFETY_RISK_RULES,
    *COMPLIANCE_RISK_RULES,
    *MARKETING_RISK_RULES,
    *PLATFORM_RISK_RULES,
)

_RISK_LEVEL_WEIGHT: dict[RiskLevel, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


class RiskDetectionRules:
    """Rule-only risk detector for K20-B governance checks."""

    def detect_keyword_risk(self, keyword: str) -> dict[str, object]:
        matched_rules = self._matched_rules(keyword)
        selected_rule = self._select_rule(matched_rules)
        return {
            "is_risk": bool(matched_rules),
            "risk_level": self._evaluate_risk_level(selected_rule),
            "category": self._classify_category(selected_rule),
            "matched_terms": [rule.trigger for rule in matched_rules],
        }

    def _is_risk_keyword(self, keyword: str) -> bool:
        return bool(self._matched_rules(keyword))

    def _evaluate_risk_level(self, rule: RiskRule | None) -> RiskLevel:
        if rule is None:
            return "low"
        return rule.risk_level

    def _classify_category(self, rule: RiskRule | None) -> RiskCategory:
        if rule is None:
            return "platform"
        return rule.category

    def _matched_rules(self, keyword: str) -> list[RiskRule]:
        normalized_keyword = self._normalize_keyword(keyword)
        if not normalized_keyword:
            return []

        return [
            rule
            for rule in RISK_RULES
            if self._trigger_matches(normalized_keyword, rule.trigger)
        ]

    def _select_rule(self, matched_rules: list[RiskRule]) -> RiskRule | None:
        if not matched_rules:
            return None
        return max(
            matched_rules,
            key=lambda rule: _RISK_LEVEL_WEIGHT[rule.risk_level],
        )

    @staticmethod
    def _normalize_keyword(keyword: str) -> str:
        return " ".join(str(keyword).strip().lower().split())

    @staticmethod
    def _trigger_matches(keyword: str, trigger: str) -> bool:
        normalized_trigger = " ".join(trigger.strip().lower().split())
        if not normalized_trigger:
            return False
        if " " in normalized_trigger or normalized_trigger.startswith("#"):
            return normalized_trigger in keyword
        return normalized_trigger in keyword.split()


__all__ = [
    "COMPLIANCE_RISK_RULES",
    "K20_B_DATA_FLOW",
    "K20_B_MODE",
    "K20_EXTERNAL_ACCESS",
    "K20_RUNTIME",
    "LEGAL_RISK_RULES",
    "MARKETING_RISK_RULES",
    "PLATFORM_RISK_RULES",
    "RISK_LEVEL_ACTIONS",
    "RISK_RULES",
    "RISK_RULES_BY_CATEGORY",
    "RiskDetectionRules",
    "RiskRule",
    "SAFETY_RISK_RULES",
]
