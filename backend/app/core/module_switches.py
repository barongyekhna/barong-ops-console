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


def _dependency(
    *,
    parent_module_key: str,
    child_module_key: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "parent_module_key": parent_module_key,
        "child_module_key": child_module_key,
        "parent_off_behavior": "disable_child",
        "recursive": True,
        "reason": reason,
    }


MODULE_SWITCH_DEPENDENCY_GRAPH_V1: tuple[dict[str, Any], ...] = (
    _dependency(
        parent_module_key="admin.users",
        child_module_key="admin.permissions",
        reason="Permission management depends on user management.",
    ),
    _dependency(
        parent_module_key="admin.modules",
        child_module_key="admin.agents",
        reason="Agent registry depends on module registry.",
    ),
    _dependency(
        parent_module_key="system.operation_logs",
        child_module_key="system.errors",
        reason="Error review depends on operation log access.",
    ),
    _dependency(
        parent_module_key="system.operation_logs",
        child_module_key="system.memory_events",
        reason="Memory event review depends on operation log access.",
    ),
)


def _group_policy(
    *,
    group_key: str,
    module_keys: tuple[str, ...],
    default_state: str = "ON",
    disabled_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "group_key": group_key,
        "module_keys": module_keys,
        "default_state": default_state,
        "disabled_reason": disabled_reason,
        "batch_control_supported": True,
    }


def _normalized_group_segment(value: object) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _module_keys_by_category(category: str) -> tuple[str, ...]:
    return tuple(
        str(manifest["module_key"])
        for manifest in MODULE_MANIFESTS_V1
        if manifest["category"] == category
    )


def _module_keys_by_navigation_group(group: str) -> tuple[str, ...]:
    return tuple(
        str(manifest["module_key"])
        for manifest in MODULE_MANIFESTS_V1
        if manifest["navigation"]["group"] == group
    )


MODULE_SWITCH_GROUP_POLICIES_V1: tuple[dict[str, Any], ...] = (
    _group_policy(
        group_key="category.core",
        module_keys=_module_keys_by_category("core"),
    ),
    _group_policy(
        group_key="category.admin",
        module_keys=_module_keys_by_category("admin"),
    ),
    _group_policy(
        group_key="category.system",
        module_keys=_module_keys_by_category("system"),
    ),
    _group_policy(
        group_key="category.business",
        module_keys=_module_keys_by_category("business"),
    ),
    _group_policy(
        group_key="category.integration",
        module_keys=_module_keys_by_category("integration"),
    ),
    _group_policy(
        group_key="category.experimental",
        module_keys=_module_keys_by_category("experimental"),
    ),
    _group_policy(
        group_key="navigation.overview",
        module_keys=_module_keys_by_navigation_group("Overview"),
    ),
    _group_policy(
        group_key="navigation.system",
        module_keys=_module_keys_by_navigation_group("System"),
    ),
    _group_policy(
        group_key="navigation.registry",
        module_keys=_module_keys_by_navigation_group("Registry"),
    ),
    _group_policy(
        group_key="navigation.operations",
        module_keys=_module_keys_by_navigation_group("Operations"),
    ),
    _group_policy(
        group_key="navigation.governance",
        module_keys=_module_keys_by_navigation_group("Governance"),
    ),
)


def _inheritance_policy(raw_manifest: dict[str, Any]) -> dict[str, Any]:
    module_key = str(raw_manifest["module_key"])
    category_group = f"category.{raw_manifest['category']}"
    navigation_group = (
        "navigation."
        f"{_normalized_group_segment(raw_manifest['navigation']['group'])}"
    )
    policy_mode = (
        "override"
        if module_key in {"core.dashboard", "system.operation_logs"}
        else "inherit"
    )
    return {
        "module_key": module_key,
        "group_keys": (category_group, navigation_group),
        "policy_mode": policy_mode,
        "parent_off_overrides_module": True,
    }


MODULE_SWITCH_INHERITANCE_POLICIES_V1: tuple[dict[str, Any], ...] = tuple(
    _inheritance_policy(raw_manifest)
    for raw_manifest in MODULE_MANIFESTS_V1
)
