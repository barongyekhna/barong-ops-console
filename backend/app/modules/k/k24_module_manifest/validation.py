"""K24-D validation for K-series module manifests."""

from __future__ import annotations

import re

from .models import ModuleManifest

SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
ALLOWED_MODULE_STATUSES = [
    "active",
    "deprecated",
    "experimental",
]


class ModuleManifestValidator:
    """Fail-fast validator for module manifest entries."""

    def validate(self, module: ModuleManifest) -> None:
        self._validate_module_key(module.module_key)
        self._validate_version(module.version)
        self._validate_required_fields(module)
        self._validate_status(module.status)

    def _validate_module_key(self, key: str) -> None:
        if not key or len(key.strip()) == 0:
            raise Exception("module_key is required")

        if " " in key:
            raise Exception("module_key must not contain spaces")

    def _validate_version(self, version: str) -> None:
        if not re.match(SEMVER_PATTERN, version):
            raise Exception("version must follow x.y.z format")

    def _validate_required_fields(self, module: ModuleManifest) -> None:
        required_fields = [
            module.module_key,
            module.module_name,
            module.module_type,
            module.version,
            module.status,
        ]

        if any(field is None or field == "" for field in required_fields):
            raise Exception("missing required field in ModuleManifest")

    def _validate_status(self, status: str) -> None:
        if status not in ALLOWED_MODULE_STATUSES:
            raise Exception("invalid module status")


__all__ = [
    "ALLOWED_MODULE_STATUSES",
    "ModuleManifestValidator",
    "SEMVER_PATTERN",
]
