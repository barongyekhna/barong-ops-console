import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.modules import MODULE_MANIFESTS_V1
from ..core.permissions import ALLOWED_SCOPE_TYPES, validate_permission_key
from ..core.roles import is_owner_role
from ..models.org_membership import OrgMembershipRecord
from ..models.organization import OrganizationRecord
from ..models.registry import ModuleRegistry
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
    resolve_current_user_module_permission_info,
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
RUNTIME_ACTIVE_MODULE_STATUSES = frozenset({"active", "production_ready"})
DYNAMIC_STATUS_TO_MODULE_STATUS = {
    "foundation": "installed",
    "demo": "enabled",
    "draft_demo": "planned",
    "inactive_demo": "disabled",
}
R_SERIES_TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"
R_SERIES_MODULE_KEYS = frozenset({"r.warehouse", "r.analysis"})
CS_CUSTOMER_SERVICE_MODULE_KEYS = frozenset({"cs.customer_service"})
# 死命令（2026-07-12）：独立站系列模块（F/W/H，后续视觉同规）只属于国际贸易
# 一个组织——非该组织成员（owner 除外）在模块清单里直接看不到。
INTL_TRADE_ONLY_MODULE_KEYS = R_SERIES_MODULE_KEYS | frozenset(
    {"f.enrichment", "w.site_ops", "h.site_health", "geo.content"}
)
INTL_TRADE_ONLY_MODULE_KEYS |= CS_CUSTOMER_SERVICE_MODULE_KEYS


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


@lru_cache(maxsize=1)
def _cached_module_manifests() -> tuple[ModuleManifestV1, ...]:
    return tuple(validate_module_manifests())


def clear_module_registry_cache() -> None:
    _cached_module_manifests.cache_clear()


def list_module_manifests() -> list[ModuleManifestV1]:
    manifests = list(_cached_module_manifests())
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


def list_module_manifests_snapshot() -> list[ModuleManifestV1]:
    return list(_cached_module_manifests())


def _dynamic_module_category(record: ModuleRegistry) -> ModuleCategory:
    prefix = record.module_id.split(".", 1)[0]
    if prefix == "business":
        return "business"
    if prefix == "integration":
        return "integration"
    if prefix == "admin":
        return "admin"
    if prefix == "core":
        return "core"
    if prefix == "system":
        return "system"
    return "experimental"


def dynamic_module_manifest_from_record(record: ModuleRegistry) -> ModuleManifestV1:
    category = _dynamic_module_category(record)
    denied_behavior = (
        "show_locked" if category == "business" else "hide_when_denied"
    )
    status = DYNAMIC_STATUS_TO_MODULE_STATUS.get(record.status, "planned")
    route_namespace = f"/modules/{record.module_id}"
    return ModuleManifestV1(
        module_key=record.module_id,
        display_name=record.name,
        description=(
            "Dynamic module registered through the control-plane module registry."
        ),
        category=category,
        status=status,  # type: ignore[arg-type]
        lifecycle=(
            "production_released"
            if status in {"installed", "enabled"}
            else "designed"
        ),
        route_namespace=route_namespace,
        api_namespace=route_namespace,
        no_api=False,
        navigation={
            "group": "Dynamic Modules",
            "label": record.name,
            "icon": "Boxes",
            "order": 900,
            "default_visible": True,
            "owner_only": False,
        },
        required_permissions=[],
        permission_manifest=[],
        denied_behavior=denied_behavior,
        unavailable_behavior="show_unavailable",
        external_dependencies=[],
        execution_provider_required=False,
        module_adapter_required=False,
        sandbox_required=False,
        feature_flag_key=None,
        audit_log_actions=[],
        operation_log_policy={
            "read": "optional",
            "write": "required",
            "approve": "required",
            "release": "required",
        },
        allowed_scope_types=["global", "organization", "module"],
        data_boundary={
            "reads": ["dynamic_module_registry"],
            "writes": [],
            "blocked_objects": [
                "server_local_config",
                "external_provider_config",
                "cross_module_writes",
            ],
        },
        release_requirements={
            "local_verify": True,
            "staging_acceptance": False,
            "production_archive": False,
            "required_checks": ["dynamic registry record exists"],
        },
        staging_acceptance_required=False,
        production_release_required=False,
        docs_path="docs/MODULE_CONTRACT.md",
    )


def list_dynamic_module_manifests(db: Session) -> list[ModuleManifestV1]:
    static_keys = {manifest.module_key for manifest in _cached_module_manifests()}
    rows = list(
        db.scalars(
            select(ModuleRegistry)
            .where(ModuleRegistry.module_id.notin_(static_keys))
            .order_by(ModuleRegistry.module_id)
        )
    )
    return [dynamic_module_manifest_from_record(row) for row in rows]


def list_module_manifests_with_dynamic(db: Session) -> list[ModuleManifestV1]:
    return [*list_module_manifests_snapshot(), *list_dynamic_module_manifests(db)]


def list_active_module_manifests(db: Session) -> list[ModuleManifestV1]:
    return [
        manifest
        for manifest in list_module_manifests_with_dynamic(db)
        if manifest.status in RUNTIME_ACTIVE_MODULE_STATUSES
    ]


def get_module_manifest(module_key: str) -> ModuleManifestV1 | None:
    for manifest in list_module_manifests_snapshot():
        if manifest.module_key == module_key:
            return manifest
    return None


def get_module_manifest_for_db(
    db: Session,
    module_key: str,
) -> ModuleManifestV1 | None:
    manifest = get_module_manifest(module_key)
    if manifest is not None:
        return manifest
    record = db.scalar(
        select(ModuleRegistry).where(ModuleRegistry.module_id == module_key)
    )
    if record is None:
        return None
    return dynamic_module_manifest_from_record(record)


def _user_has_r_series_org_access(db: Session, user: User) -> bool:
    if is_owner_role(user.role):
        return True

    org_ids: set[str] = set()
    if user.organization_id:
        org_ids.add(user.organization_id)

    membership_org_ids = db.scalars(
        select(OrgMembershipRecord.org_id).where(
            OrgMembershipRecord.user_id == str(user.id),
            OrgMembershipRecord.status == "active",
        )
    )
    org_ids.update(membership_org_ids)

    if not org_ids:
        return False

    return (
        db.scalar(
            select(OrganizationRecord.org_id)
            .where(
                OrganizationRecord.org_id.in_(org_ids),
                OrganizationRecord.org_name == R_SERIES_TARGET_ORGANIZATION_NAME,
                OrganizationRecord.status != "deleted",
            )
            .limit(1)
        )
        is not None
    )


def _filter_r_series_manifests_for_user(
    db: Session,
    user: User,
    manifests: list[ModuleManifestV1],
) -> list[ModuleManifestV1]:
    if _user_has_r_series_org_access(db, user):
        return manifests
    return [
        manifest
        for manifest in manifests
        if manifest.module_key not in INTL_TRADE_ONLY_MODULE_KEYS
    ]


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
    is_owner = current_user_permissions.is_platform_owner
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
    *,
    request: object | None = None,
) -> tuple[CurrentUserPermissionInfo, list[ModuleAccessRead]]:
    current_user_permissions = resolve_current_user_module_permission_info(
        db,
        user,
        request=request,
    )
    manifests = _filter_r_series_manifests_for_user(
        db,
        user,
        list_module_manifests_with_dynamic(db),
    )
    items = [
        build_module_access_state(manifest, current_user_permissions)
        for manifest in manifests
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
