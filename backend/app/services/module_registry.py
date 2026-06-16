import re
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from sqlalchemy.orm import Session

from ..core.modules import MODULE_MANIFESTS_V1
from ..core.permissions import ALLOWED_SCOPE_TYPES, validate_permission_key
from ..models.user import User
from ..schemas.module import (
    ModuleAccessRead,
    ModuleCategory,
    ModuleDeniedBehavior,
    ModuleManifestV1,
    ModuleStatus,
)
from .event_collector import emit_event
from .permission_service import (
    CurrentUserPermissionInfo,
    resolve_current_user_permission_info,
)

MODULE_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)
ALLOWED_MODULE_CATEGORIES = frozenset(get_args(ModuleCategory))
ALLOWED_MODULE_STATUSES = frozenset(get_args(ModuleStatus))
ALLOWED_DENIED_BEHAVIORS = frozenset(get_args(ModuleDeniedBehavior))
EXTERNAL_DEPENDENCY_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)*$"
)
SENSITIVE_DEPENDENCY_MARKERS = (
    "secret",
    "token",
    "password",
    "credential",
    "authorization",
    "api_key",
    "env",
    "url",
    "http",
    "://",
    "=",
)
NON_EXECUTABLE_STATUS_STATES = {
    "planned": "planned",
    "adapter_pending": "adapter_pending",
    "unavailable": "unavailable",
    "disabled": "unavailable",
}


def _manifest_from_raw(
    raw: ModuleManifestV1 | Mapping[str, Any],
) -> ModuleManifestV1:
    if isinstance(raw, ModuleManifestV1):
        return raw
    return ModuleManifestV1.model_validate(raw)


def _validate_module_key(module_key: str) -> None:
    if not MODULE_KEY_PATTERN.fullmatch(module_key):
        raise ValueError("Module key must use stable lowercase dot segments.")


def _validate_namespace(manifest: ModuleManifestV1) -> None:
    if not manifest.route_namespace.strip():
        raise ValueError(f"{manifest.module_key} route_namespace is empty.")
    if not manifest.route_namespace.startswith("/"):
        raise ValueError(f"{manifest.module_key} route_namespace must start with '/'.")

    if manifest.no_api:
        if manifest.api_namespace != "no_api":
            raise ValueError(
                f"{manifest.module_key} no_api manifests must use api_namespace='no_api'."
            )
        return

    if not manifest.api_namespace.strip():
        raise ValueError(f"{manifest.module_key} api_namespace is empty.")
    if not manifest.api_namespace.startswith("/"):
        raise ValueError(f"{manifest.module_key} api_namespace must start with '/'.")


def _validate_external_dependencies(manifest: ModuleManifestV1) -> None:
    normalized_dependencies: list[str] = []
    for dependency in manifest.external_dependencies:
        normalized = dependency.strip().lower()
        if normalized != dependency:
            raise ValueError(
                f"{manifest.module_key} external dependency names must be normalized."
            )
        if not EXTERNAL_DEPENDENCY_KEY_PATTERN.fullmatch(normalized):
            raise ValueError(
                f"{manifest.module_key} external dependency key is invalid: {dependency}"
            )
        if any(marker in normalized for marker in SENSITIVE_DEPENDENCY_MARKERS):
            raise ValueError(
                f"{manifest.module_key} external dependency includes sensitive data."
            )
        normalized_dependencies.append(normalized)
    manifest.external_dependencies = normalized_dependencies


def _validate_permissions(manifest: ModuleManifestV1) -> None:
    manifest_permission_keys = {
        entry.permission_key for entry in manifest.permission_manifest
    }
    for permission_key in manifest.required_permissions:
        validate_permission_key(permission_key)
        if permission_key not in manifest_permission_keys:
            raise ValueError(
                f"{manifest.module_key} required permission is not declared: "
                f"{permission_key}"
            )

    for entry in manifest.permission_manifest:
        validate_permission_key(entry.permission_key)
        if entry.module_key != manifest.module_key:
            raise ValueError(
                f"{manifest.module_key} permission entry has mismatched module_key."
            )
        if entry.category != manifest.category:
            raise ValueError(
                f"{manifest.module_key} permission entry has mismatched category."
            )
        if entry.menu_policy != manifest.denied_behavior:
            raise ValueError(
                f"{manifest.module_key} permission entry has mismatched menu policy."
            )
        if not set(entry.allowed_scope_types).issubset(ALLOWED_SCOPE_TYPES):
            raise ValueError(
                f"{manifest.module_key} permission entry has invalid scope types."
            )

    if not set(manifest.allowed_scope_types).issubset(ALLOWED_SCOPE_TYPES):
        raise ValueError(f"{manifest.module_key} has invalid allowed scope types.")


def _validate_category_defaults(manifest: ModuleManifestV1) -> None:
    if (
        manifest.category == "business"
        and manifest.denied_behavior != "show_locked"
    ):
        raise ValueError("Business modules must default to show_locked.")
    if manifest.category in {"admin", "system"} and (
        manifest.denied_behavior != "hide_when_denied"
    ):
        raise ValueError("Admin/system modules must default to hide_when_denied.")


def validate_module_manifests(
    raw_manifests: Sequence[ModuleManifestV1 | Mapping[str, Any]] | None = None,
) -> list[ModuleManifestV1]:
    manifests = [
        _manifest_from_raw(raw_manifest)
        for raw_manifest in (raw_manifests or MODULE_MANIFESTS_V1)
    ]
    seen_keys: set[str] = set()
    for manifest in manifests:
        _validate_module_key(manifest.module_key)
        if manifest.module_key in seen_keys:
            raise ValueError(f"Duplicate module_key: {manifest.module_key}")
        seen_keys.add(manifest.module_key)
        if manifest.category not in ALLOWED_MODULE_CATEGORIES:
            raise ValueError(f"Invalid module category: {manifest.category}")
        if manifest.status not in ALLOWED_MODULE_STATUSES:
            raise ValueError(f"Invalid module status: {manifest.status}")
        if manifest.denied_behavior not in ALLOWED_DENIED_BEHAVIORS:
            raise ValueError(
                f"Invalid denied behavior: {manifest.denied_behavior}"
            )
        _validate_category_defaults(manifest)
        _validate_namespace(manifest)
        _validate_external_dependencies(manifest)
        _validate_permissions(manifest)
    return manifests


def list_module_manifests() -> list[ModuleManifestV1]:
    manifests = validate_module_manifests()
    emit_event(
        event_type="category_tree.read",
        module="system",
        action="category_tree.read",
        source="system",
        status="success",
        payload={
            "operation": "list_module_manifests",
            "count": len(manifests),
        },
    )
    return manifests


def get_module_manifest(module_key: str) -> ModuleManifestV1 | None:
    for manifest in list_module_manifests():
        if manifest.module_key == module_key:
            return manifest
    return None


def _missing_permissions(
    manifest: ModuleManifestV1,
    current_user_permissions: CurrentUserPermissionInfo,
) -> list[str]:
    if current_user_permissions.is_owner_full_access:
        return []
    permission_keys = set(current_user_permissions.permission_keys)
    if "*" in permission_keys:
        return []
    return [
        permission_key
        for permission_key in manifest.required_permissions
        if permission_key not in permission_keys
    ]


def _has_module_permission(
    manifest: ModuleManifestV1,
    current_user_permissions: CurrentUserPermissionInfo,
) -> bool:
    return not _missing_permissions(manifest, current_user_permissions)


def _non_executable_state(status: str) -> str | None:
    return NON_EXECUTABLE_STATUS_STATES.get(status)


def build_module_access_state(
    manifest: ModuleManifestV1,
    current_user_permissions: CurrentUserPermissionInfo,
) -> ModuleAccessRead:
    is_owner = current_user_permissions.is_owner_full_access
    missing_permissions = _missing_permissions(manifest, current_user_permissions)
    has_permission = _has_module_permission(manifest, current_user_permissions)

    if manifest.navigation.owner_only and not is_owner:
        return ModuleAccessRead(
            module_key=manifest.module_key,
            visible=False,
            locked=False,
            hidden=True,
            unavailable=False,
            executable=False,
            access_state="hidden",
            denied_behavior=manifest.denied_behavior,
            reason="Module is owner-only.",
            required_permissions=manifest.required_permissions,
            missing_permissions=missing_permissions,
            status=manifest.status,
            category=manifest.category,
            route_namespace=manifest.route_namespace,
        )

    if not has_permission:
        if manifest.denied_behavior == "show_locked":
            return ModuleAccessRead(
                module_key=manifest.module_key,
                visible=True,
                locked=True,
                hidden=False,
                unavailable=manifest.status in NON_EXECUTABLE_STATUS_STATES,
                executable=False,
                access_state="locked",
                denied_behavior=manifest.denied_behavior,
                reason="Missing required permissions.",
                required_permissions=manifest.required_permissions,
                missing_permissions=missing_permissions,
                status=manifest.status,
                category=manifest.category,
                route_namespace=manifest.route_namespace,
            )
        return ModuleAccessRead(
            module_key=manifest.module_key,
            visible=False,
            locked=False,
            hidden=True,
            unavailable=False,
            executable=False,
            access_state="hidden",
            denied_behavior=manifest.denied_behavior,
            reason="Missing required permissions.",
            required_permissions=manifest.required_permissions,
            missing_permissions=missing_permissions,
            status=manifest.status,
            category=manifest.category,
            route_namespace=manifest.route_namespace,
        )

    non_executable_state = _non_executable_state(manifest.status)
    if non_executable_state is not None:
        return ModuleAccessRead(
            module_key=manifest.module_key,
            visible=True,
            locked=False,
            hidden=False,
            unavailable=True,
            executable=False,
            access_state=non_executable_state,
            denied_behavior=manifest.denied_behavior,
            reason=f"Module status is {manifest.status}.",
            required_permissions=manifest.required_permissions,
            missing_permissions=[],
            status=manifest.status,
            category=manifest.category,
            route_namespace=manifest.route_namespace,
        )

    if manifest.external_dependencies:
        return ModuleAccessRead(
            module_key=manifest.module_key,
            visible=True,
            locked=False,
            hidden=False,
            unavailable=True,
            executable=False,
            access_state="unavailable",
            denied_behavior=manifest.denied_behavior,
            reason="External dependency is declared but not connected in C07B.",
            required_permissions=manifest.required_permissions,
            missing_permissions=[],
            status=manifest.status,
            category=manifest.category,
            route_namespace=manifest.route_namespace,
        )

    return ModuleAccessRead(
        module_key=manifest.module_key,
        visible=True,
        locked=False,
        hidden=False,
        unavailable=False,
        executable=False,
        access_state="available",
        denied_behavior=manifest.denied_behavior,
        reason="Module metadata is available.",
        required_permissions=manifest.required_permissions,
        missing_permissions=[],
        status=manifest.status,
        category=manifest.category,
        route_namespace=manifest.route_namespace,
    )


def list_modules_for_user(
    db: Session,
    user: User,
) -> tuple[CurrentUserPermissionInfo, list[ModuleAccessRead]]:
    current_user_permissions = resolve_current_user_permission_info(db, user)
    items = [
        build_module_access_state(manifest, current_user_permissions)
        for manifest in list_module_manifests()
    ]
    emit_event(
        event_type="category_tree.read",
        module="system",
        action="category_tree.read",
        source="system",
        status="success",
        user_id=str(user.id),
        payload={
            "operation": "list_modules_for_user",
            "count": len(items),
            "role": user.role,
        },
    )
    return (
        current_user_permissions,
        items,
    )
