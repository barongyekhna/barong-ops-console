"""K24-F read-only drift detection for K-series module manifests."""

from __future__ import annotations

from typing import Any

from .models import ModuleManifest
from .registry import ModuleRegistry

DriftResult = dict[str, list[ModuleManifest]]
DriftReport = dict[str, Any]


class ModuleDriftDetector:
    """Compares registry entries with a supplied K-module manifest list."""

    def detect(
        self,
        registry: ModuleRegistry,
        codebase_modules: list[ModuleManifest],
    ) -> DriftResult:
        return {
            "missing_in_registry": self._find_missing_in_registry(
                registry,
                codebase_modules,
            ),
            "orphan_registry_modules": self._find_orphan_registry(
                registry,
                codebase_modules,
            ),
            "version_mismatch": self._check_version_drift(
                registry,
                codebase_modules,
            ),
        }

    def _find_missing_in_registry(
        self,
        registry: ModuleRegistry,
        codebase: list[ModuleManifest],
    ) -> list[ModuleManifest]:
        return [
            module
            for module in codebase
            if registry.get(module.module_key) is None
        ]

    def _find_orphan_registry(
        self,
        registry: ModuleRegistry,
        codebase: list[ModuleManifest],
    ) -> list[ModuleManifest]:
        codebase_module_keys = [module.module_key for module in codebase]
        return [
            module
            for module in registry.list_modules()
            if module.module_key not in codebase_module_keys
        ]

    def _check_version_drift(
        self,
        registry: ModuleRegistry,
        codebase: list[ModuleManifest],
    ) -> list[ModuleManifest]:
        version_drift = []
        for module in codebase:
            registry_module = registry.get(module.module_key)
            if registry_module and registry_module.version != module.version:
                version_drift.append(module)
        return version_drift

    def generate_report(self, drift_result: DriftResult) -> DriftReport:
        has_drift = any(drift_result.values())
        return {
            "status": "drift_detected" if has_drift else "clean",
            "summary": drift_result,
            "risk_level": self._calculate_risk_level(drift_result),
            "recommendation": (
                "sync registry or codebase"
                if has_drift
                else "no sync required"
            ),
        }

    def _calculate_risk_level(self, drift_result: DriftResult) -> str:
        if (
            drift_result["missing_in_registry"]
            or drift_result["orphan_registry_modules"]
        ):
            return "high"

        if drift_result["version_mismatch"]:
            return "medium"

        return "low"


__all__ = [
    "DriftReport",
    "DriftResult",
    "ModuleDriftDetector",
]
