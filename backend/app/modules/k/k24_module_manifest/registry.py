"""K24-B in-memory registry for K-series module manifests."""

from __future__ import annotations

from .models import ModuleManifest


class ModuleRegistry:
    """In-memory store for K-series module manifests."""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleManifest] = {}

    def register(self, module: ModuleManifest) -> None:
        if module.module_key in self._modules:
            raise Exception("Module already registered")

        self._modules[module.module_key] = module

    def get(self, module_key: str) -> ModuleManifest | None:
        return self._modules.get(module_key)

    def list_modules(self) -> list[ModuleManifest]:
        return list(self._modules.values())

    def update_module(self, module_key: str, module: ModuleManifest) -> None:
        if module_key not in self._modules:
            raise Exception("Module not found")

        self._modules[module_key] = module

    def delete_module(self, module_key: str) -> None:
        if module_key in self._modules:
            self._modules[module_key].status = "deprecated"


__all__ = [
    "ModuleRegistry",
]
