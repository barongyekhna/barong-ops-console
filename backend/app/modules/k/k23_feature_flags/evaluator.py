"""K23-C feature flag runtime evaluator.

K23-C evaluates K23-A FeatureFlag records from the K23-B registry only. It does
not mutate schemas or registries, expose services or APIs, render UI, call
external systems, apply AI/SEO/ranking logic, or target production/staging
environments.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .registry import FeatureFlagRegistry

K23_C_MODE = "runtime_only"
K23_RUNTIME = "evaluation_only"
K23_MUTATION = False
K23_EXTERNAL_ACCESS = False

K23_C_DATA_FLOW = (
    "FeatureFlagRegistry (K23-B)",
    "FeatureFlagEvaluator (K23-C)",
    "boolean runtime decision",
)

K23_C_SCOPE_AWARENESS = (
    "global",
    "module",
    "product",
    "user",
)


class FeatureFlagEvaluator:
    """Read-only deterministic evaluator for registered feature flags."""

    def __init__(self, registry: FeatureFlagRegistry) -> None:
        self.registry = registry

    def is_enabled(
        self,
        key: str,
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        del context
        flag = self.registry.get(key)

        if not flag:
            return False

        if flag.enabled is None:
            return flag.fallback_value

        return flag.enabled


__all__ = [
    "FeatureFlagEvaluator",
    "K23_C_DATA_FLOW",
    "K23_C_MODE",
    "K23_C_SCOPE_AWARENESS",
    "K23_EXTERNAL_ACCESS",
    "K23_MUTATION",
    "K23_RUNTIME",
]
