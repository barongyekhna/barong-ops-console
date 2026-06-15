"""K23-E feature flag system integration layer.

K23-E connects the K23 registry, evaluator, and fallback components only. It
does not mutate K23-A/B/C/D, implement business logic, expose services or APIs,
render UI, call external systems, apply AI/SEO/ranking logic, or target
production/staging environments.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .evaluator import FeatureFlagEvaluator
from .fallback import FeatureFlagFallback
from .registry import FeatureFlagRegistry

K23_E_MODE = "integration_only"
K23_RUNTIME = "no_execution"
K23_SYSTEM_ACCESS = "controlled"
K23_EXTERNAL_ACCESS = False

K23_E_DATA_FLOW = (
    "FeatureFlagRegistry",
    "FeatureFlagEvaluator",
    "FeatureFlagFallback",
    "system integration decision",
)

K23_INTEGRATION_POINTS = {
    "K19": "keyword UI availability control",
    "K20": "risk governance availability control",
    "API": "endpoint availability control",
    "UI": "future frontend feature visibility control",
}


class FeatureFlagIntegration:
    """Connection layer for registry, evaluator, and fallback decisions."""

    def __init__(
        self,
        registry: FeatureFlagRegistry,
        evaluator: FeatureFlagEvaluator,
        fallback: FeatureFlagFallback,
    ) -> None:
        self.registry = registry
        self.evaluator = evaluator
        self.fallback = fallback

    def is_feature_enabled(
        self,
        key: str,
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        flag = self.registry.get(key)

        if not flag:
            return self.fallback.resolve_missing_flag(key, context)

        return self.evaluator.is_enabled(key, context)


__all__ = [
    "FeatureFlagIntegration",
    "K23_E_DATA_FLOW",
    "K23_E_MODE",
    "K23_EXTERNAL_ACCESS",
    "K23_INTEGRATION_POINTS",
    "K23_RUNTIME",
    "K23_SYSTEM_ACCESS",
]
