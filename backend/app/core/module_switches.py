from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .modules import MODULE_MANIFESTS_V1


MODULE_SWITCH_REGISTRY_UPDATED_AT = datetime(2026, 6, 14, tzinfo=UTC)


def _switch(
    *,
    module_key: str,
    state: str = "ON",
    disabled_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "module_key": module_key,
        "state": state,
        "enabled": state == "ON",
        "disabled_reason": disabled_reason,
        "updated_at": MODULE_SWITCH_REGISTRY_UPDATED_AT,
    }


MODULE_SWITCH_REGISTRY_V1: tuple[dict[str, Any], ...] = tuple(
    _switch(module_key=str(manifest["module_key"]))
    for manifest in MODULE_MANIFESTS_V1
)

