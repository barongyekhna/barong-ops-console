"""K23-D feature flag fallback safety layer.

K23-D defines deterministic fallback decisions for missing feature flags only.
It does not mutate K23-A/B/C, expose services or APIs, render UI, call external
systems, apply AI/SEO/ranking logic, or target production/staging environments.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

K23_D_MODE = "fallback_only"
K23_RUNTIME = "no_execution"
K23_SAFE_MODE = True
K23_EXTERNAL_ACCESS = False

K23_D_DATA_FLOW = (
    "FeatureFlagEvaluator",
    "missing flag",
    "FeatureFlagFallback",
    "safe boolean decision",
)

SYSTEM_CRITICAL_FLAG_KEYS = frozenset(
    {
        "system_critical",
        "safe_mode",
        "emergency_shutdown",
        "k23_safe_mode",
    }
)

EMERGENCY_CONTEXT_KEYS = frozenset(
    {
        "system_failure",
        "emergency_mode",
        "safe_shutdown",
    }
)


class FeatureFlagFallback:
    """Deterministic fallback resolver for missing feature flags."""

    def resolve_missing_flag(
        self,
        key: str,
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        normalized_key = self._normalize_key(key)
        if self._is_emergency_context(context):
            return True
        if normalized_key in SYSTEM_CRITICAL_FLAG_KEYS:
            return True
        return False

    @staticmethod
    def _is_emergency_context(context: Mapping[str, Any] | None) -> bool:
        if not context:
            return False
        return any(bool(context.get(key)) for key in EMERGENCY_CONTEXT_KEYS)

    @staticmethod
    def _normalize_key(key: str) -> str:
        return "_".join(str(key).strip().lower().split())


__all__ = [
    "EMERGENCY_CONTEXT_KEYS",
    "FeatureFlagFallback",
    "K23_D_DATA_FLOW",
    "K23_D_MODE",
    "K23_EXTERNAL_ACCESS",
    "K23_RUNTIME",
    "K23_SAFE_MODE",
    "SYSTEM_CRITICAL_FLAG_KEYS",
]
