"""K23-B feature flag registry.

K23-B stores and retrieves K23-A FeatureFlag records only. It does not evaluate
flags, implement runtime toggle behavior, expose services or APIs, render UI,
call external systems, apply AI/SEO/ranking logic, or target production/staging
environments.
"""

from __future__ import annotations

from .models import FeatureFlag, FeatureFlagModule

K23_B_MODE = "registry_only"
K23_RUNTIME = "disabled"
K23_EVALUATION = False
K23_EXTERNAL_ACCESS = False

K23_B_DATA_FLOW = (
    "FeatureFlag (K23-A)",
    "FeatureFlagRegistry (K23-B)",
    "K23-C runtime evaluator (future)",
)


class FeatureFlagRegistry:
    """In-memory registry for canonical feature flag records."""

    def __init__(self) -> None:
        self._flags: dict[str, FeatureFlag] = {}

    def register(self, flag: FeatureFlag) -> FeatureFlag:
        self._flags[flag.key] = flag
        return flag

    def get(self, key: str) -> FeatureFlag | None:
        return self._flags.get(self._normalize_key(key))

    def list(self) -> list[FeatureFlag]:
        return list(self._flags.values())

    def update(self, key: str, flag: FeatureFlag) -> FeatureFlag:
        normalized_key = self._normalize_key(key)
        if normalized_key != flag.key:
            raise ValueError("registry key must match feature flag key")
        self._flags[normalized_key] = flag
        return flag

    def list_by_module(self, module: FeatureFlagModule | str) -> list[FeatureFlag]:
        normalized_module = self._normalize_module(module)
        return [
            flag
            for flag in self._flags.values()
            if flag.module == normalized_module
        ]

    def grouped_by_module(self) -> dict[str, list[FeatureFlag]]:
        grouped_flags: dict[str, list[FeatureFlag]] = {}
        for flag in self._flags.values():
            grouped_flags.setdefault(flag.module, []).append(flag)
        return grouped_flags

    @staticmethod
    def _normalize_key(key: str) -> str:
        return "_".join(str(key).strip().lower().split())

    @staticmethod
    def _normalize_module(module: FeatureFlagModule | str) -> str:
        return str(module).strip().upper()


__all__ = [
    "FeatureFlagRegistry",
    "K23_B_DATA_FLOW",
    "K23_B_MODE",
    "K23_EVALUATION",
    "K23_EXTERNAL_ACCESS",
    "K23_RUNTIME",
]
