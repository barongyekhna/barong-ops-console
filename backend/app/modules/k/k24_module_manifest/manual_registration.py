"""K24-C manual registration for K-series module manifests."""

from __future__ import annotations

from .models import ModuleManifest, ModuleStatus
from .registry import ModuleRegistry

MANUAL_REGISTRATION_TIMESTAMP = "2026-06-16T00:00:00Z"


class ManualModuleRegistration:
    """Manual controller for K-series module registry entries."""

    def __init__(self, registry: ModuleRegistry) -> None:
        self.registry = registry

    def add_k_modules(self) -> None:
        modules = [
            ModuleManifest(
                module_key="K19",
                module_name="Keyword Control System",
                module_type="K",
                version="1.0.0",
                status="active",
                description="Manual module entry for keyword control.",
                dependencies=[],
                created_at=MANUAL_REGISTRATION_TIMESTAMP,
                updated_at=MANUAL_REGISTRATION_TIMESTAMP,
            ),
            ModuleManifest(
                module_key="K20",
                module_name="Risk Governance System",
                module_type="K",
                version="1.0.0",
                status="active",
                description="Manual module entry for risk governance.",
                dependencies=[],
                created_at=MANUAL_REGISTRATION_TIMESTAMP,
                updated_at=MANUAL_REGISTRATION_TIMESTAMP,
            ),
            ModuleManifest(
                module_key="K23",
                module_name="Feature Flag Control Plane",
                module_type="K",
                version="1.0.0",
                status="active",
                description="Manual module entry for feature flag control.",
                dependencies=[],
                created_at=MANUAL_REGISTRATION_TIMESTAMP,
                updated_at=MANUAL_REGISTRATION_TIMESTAMP,
            ),
        ]

        for module in modules:
            self.registry.register(module)

    def update_module_metadata(
        self,
        module_key: str,
        description: str,
        version: str,
    ) -> None:
        module = self._get_existing_module(module_key)
        self._ensure_incremental_version(module.version, version)
        self._replace_module(
            module_key,
            module,
            description=description,
            version=version,
        )

    def mark_module_status(self, module_key: str, status: ModuleStatus) -> None:
        module = self._get_existing_module(module_key)
        self._replace_module(module_key, module, status=status)

    def update_module_version(self, module_key: str, version: str) -> None:
        module = self._get_existing_module(module_key)
        self._ensure_incremental_version(module.version, version)
        self._replace_module(module_key, module, version=version)

    def _get_existing_module(self, module_key: str) -> ModuleManifest:
        module = self.registry.get(module_key)
        if module is None:
            raise Exception("Module not found")
        return module

    def _replace_module(
        self,
        module_key: str,
        module: ModuleManifest,
        **changes: object,
    ) -> None:
        module_data = module.model_dump()
        module_data.update(changes)
        module_data["updated_at"] = MANUAL_REGISTRATION_TIMESTAMP
        updated_module = ModuleManifest(**module_data)
        self.registry.update_module(module_key, updated_module)

    @staticmethod
    def _ensure_incremental_version(current_version: str, next_version: str) -> None:
        if _parse_semver(next_version) <= _parse_semver(current_version):
            raise Exception("Module version must be incremented")


def _parse_semver(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise Exception("Module version must use x.y.z format")
    return int(parts[0]), int(parts[1]), int(parts[2])


__all__ = [
    "MANUAL_REGISTRATION_TIMESTAMP",
    "ManualModuleRegistration",
]
