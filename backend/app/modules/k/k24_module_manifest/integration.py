"""K24-E K-system registry integration."""

from __future__ import annotations

from .models import ModuleManifest
from .registry import ModuleRegistry
from .validation import ModuleManifestValidator

K24_E_MODE = "k_system_only"
K24_RUNTIME = "no_execution"
K24_EXTERNAL_ACCESS = False
K24_INTEGRATION_TIMESTAMP = "2026-06-16T00:00:00Z"


class KModuleIntegration:
    """Registers known K-series modules into the module registry."""

    def __init__(self) -> None:
        self.validator = ModuleManifestValidator()

    def register_k_modules(self, registry: ModuleRegistry) -> None:
        modules = [
            ModuleManifest(
                module_key="K19",
                module_name="Keyword Control System",
                module_type="K",
                version="1.0.0",
                status="active",
                description="Human-controlled keyword system",
                dependencies=[],
                created_at=K24_INTEGRATION_TIMESTAMP,
                updated_at=K24_INTEGRATION_TIMESTAMP,
            ),
            ModuleManifest(
                module_key="K20",
                module_name="Risk Governance System",
                module_type="K",
                version="1.0.0",
                status="active",
                description="Risk governance and validation system",
                dependencies=[],
                created_at=K24_INTEGRATION_TIMESTAMP,
                updated_at=K24_INTEGRATION_TIMESTAMP,
            ),
            ModuleManifest(
                module_key="K23",
                module_name="Feature Flag Control Plane",
                module_type="K",
                version="1.0.0",
                status="active",
                description="System-wide feature flag control system",
                dependencies=[],
                created_at=K24_INTEGRATION_TIMESTAMP,
                updated_at=K24_INTEGRATION_TIMESTAMP,
            ),
        ]

        for module in modules:
            self.validator.validate(module)
            registry.register(module)

    def list_k_modules(self, registry: ModuleRegistry) -> list[ModuleManifest]:
        return list_k_modules(registry)


def list_k_modules(registry: ModuleRegistry) -> list[ModuleManifest]:
    return [
        module
        for module in registry.list_modules()
        if module.module_key.startswith("K")
    ]


__all__ = [
    "K24_E_MODE",
    "K24_EXTERNAL_ACCESS",
    "K24_INTEGRATION_TIMESTAMP",
    "K24_RUNTIME",
    "KModuleIntegration",
    "list_k_modules",
]
