from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.roles import is_owner_role, is_super_admin_role
from ..models.module_control import ModuleControlStateRecord
from ..models.org_membership import OrgMembershipRecord
from ..models.organization import OrganizationRecord
from ..models.permission import PermissionRegistry
from ..models.user import User
from ..repositories.permissions import list_enabled_user_assignments
from ..schemas.module import ModuleManifestV1
from ..schemas.module_control import (
    ModuleControlCenterResponse,
    ModuleControlOrgGroup,
    ModuleControlStateRead,
    ModuleControlUpdateRequest,
)
from .module_registry import (
    get_module_manifest_for_db,
    list_module_manifests_snapshot,
    list_module_manifests_with_dynamic,
)


class ModuleControlError(ValueError):
    pass


from .module_registry import (
    FACTORY_ONLY_MODULE_KEYS,
    INTL_TRADE_ONLY_MODULE_KEYS,
)

TARGET_PRODUCT_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"
I_IMAGE_SYSTEM_MODULE_ID = "i.image_system"
I_IMAGE_SYSTEM_ORGANIZATION_NAME = TARGET_PRODUCT_ORGANIZATION_NAME
R_WAREHOUSE_MODULE_ID = "r.warehouse"
R_ANALYSIS_MODULE_ID = "r.analysis"
R_SERIES_MODULE_IDS = frozenset({R_WAREHOUSE_MODULE_ID, R_ANALYSIS_MODULE_ID})
R_SERIES_ORGANIZATION_NAME = TARGET_PRODUCT_ORGANIZATION_NAME
CS_CUSTOMER_SERVICE_MODULE_ID = "cs.customer_service"
# 独立站/贸易业务模块只属于国际贸易公司,制造公司下不该出现
# (2026-07-27 用户拍板一次性清理;此前只有 I/R/CS 做了限定,其余漏了)。
B2B_WHOLESALE_MODULE_ID = "b2b.wholesale"
# M 系列只属于 factory 类型组织(按 org_type 判,不按组织名;2026-08-21 拍板)。
MFG_INVENTORY_MODULE_ID = "mfg.inventory"
FACTORY_ORG_TYPE = "factory"
# 唯一真相源在 module_registry。这里曾经是一份手抄件，漏了 geo.content /
# seo.content —— owner 的侧边栏里制造组织下会冒出 GEO/SEO 内容引擎。
# 手抄一份清单就一定会漂移，所以直接引用。
TRADE_ONLY_MODULE_IDS = INTL_TRADE_ONLY_MODULE_KEYS


def _is_r_series_module(module_id: str) -> bool:
    return module_id in R_SERIES_MODULE_IDS


def _module_allowed_for_organization(
    organization: OrganizationRecord,
    manifest: ModuleManifestV1,
) -> bool:
    # **按 org_type 判，不按组织名。**
    # 组织名是可以改的（工商变更、简称调整），而这套判定原本散在三处、
    # 每处都拿中文名做字符串比较 —— 改一次名字三处一起失效，而且失效方式是
    # 「模块静默出现在不该出现的组织下」，不会报错。
    org_type = (organization.org_type or "").strip()
    if manifest.module_key in FACTORY_ONLY_MODULE_KEYS:
        return org_type == FACTORY_ORG_TYPE
    if manifest.module_key in TRADE_ONLY_MODULE_IDS:
        return org_type != FACTORY_ORG_TYPE
    return True


def _active_organizations(db: Session) -> list[OrganizationRecord]:
    return list(
        db.scalars(
            select(OrganizationRecord)
            .where(OrganizationRecord.status != "deleted")
            .order_by(OrganizationRecord.org_name, OrganizationRecord.org_id)
        )
    )


def list_module_control_org_summary(db: Session) -> list[OrganizationRecord]:
    return _active_organizations(db)


def list_module_control_module_list(
    db: Session | None = None,
) -> list[ModuleManifestV1]:
    if db is None:
        return list_module_manifests_snapshot()
    return list_module_manifests_with_dynamic(db)


def _state_lookup(
    db: Session,
    org_ids: list[str],
) -> dict[tuple[str, str], ModuleControlStateRecord]:
    if not org_ids:
        return {}
    records = list(
        db.scalars(
            select(ModuleControlStateRecord).where(
                ModuleControlStateRecord.org_id.in_(org_ids)
            )
        )
    )
    return {(record.org_id, record.module_id): record for record in records}


def list_module_control_status(
    db: Session,
    org_ids: list[str],
) -> dict[tuple[str, str], ModuleControlStateRecord]:
    return _state_lookup(db, org_ids)


def build_module_control_execution_snapshot(
    lookup: dict[tuple[str, str], ModuleControlStateRecord],
) -> dict[str, int]:
    counts = Counter(record.runtime_status for record in lookup.values())
    return {
        "active": counts.get("active", 0),
        "disabled": counts.get("disabled", 0),
        "error": counts.get("error", 0),
        "total": sum(counts.values()),
    }


def _runtime_status_for_enabled(enabled: bool) -> str:
    return "active" if enabled else "disabled"


def _default_enabled_for_manifest(manifest: ModuleManifestV1) -> bool:
    if manifest.module_key == R_ANALYSIS_MODULE_ID:
        return False
    return manifest.status != "disabled"


def _read_from_record(
    record: ModuleControlStateRecord,
    *,
    manifest: ModuleManifestV1 | None = None,
) -> ModuleControlStateRead:
    return ModuleControlStateRead(
        org_id=record.org_id,
        module_id=record.module_id,
        display_name=manifest.display_name if manifest is not None else record.module_id,
        category=manifest.category if manifest is not None else "unknown",
        enabled=record.enabled,
        runtime_status=record.runtime_status,  # type: ignore[arg-type]
        runtime_error_code=record.runtime_error_code,
        runtime_error_message=record.runtime_error_message,
        last_error_at=record.last_error_at,
        updated_at=record.updated_at,
    )


def _read_default_state(
    organization: OrganizationRecord,
    manifest: ModuleManifestV1,
) -> ModuleControlStateRead:
    timestamp = organization.updated_at or datetime.now(UTC)
    enabled = _default_enabled_for_manifest(manifest)
    return ModuleControlStateRead(
        org_id=organization.org_id,
        module_id=manifest.module_key,
        display_name=manifest.display_name,
        category=manifest.category,
        enabled=enabled,
        runtime_status=_runtime_status_for_enabled(enabled),
        runtime_error_code=None,
        runtime_error_message=None,
        last_error_at=None,
        updated_at=timestamp,
    )


def ensure_module_control_states(
    db: Session,
    *,
    organizations: list[OrganizationRecord] | None = None,
    manifests: list[ModuleManifestV1] | None = None,
) -> tuple[int, list[OrganizationRecord]]:
    organizations = (
        organizations if organizations is not None else _active_organizations(db)
    )
    manifests = (
        manifests if manifests is not None else list_module_control_module_list(db)
    )
    lookup = _state_lookup(db, [organization.org_id for organization in organizations])
    created = 0
    for organization in organizations:
        for manifest in manifests:
            if not _module_allowed_for_organization(organization, manifest):
                continue
            key = (organization.org_id, manifest.module_key)
            if key in lookup:
                continue
            enabled = _default_enabled_for_manifest(manifest)
            record = ModuleControlStateRecord(
                org_id=organization.org_id,
                module_id=manifest.module_key,
                enabled=enabled,
                runtime_status=_runtime_status_for_enabled(enabled),
                metadata_json={
                    "locked_until_rw_ready": manifest.module_key
                    == R_ANALYSIS_MODULE_ID,
                    "source": "auto_registered_from_manifest",
                },
            )
            db.add(record)
            lookup[key] = record
            created += 1
    if created:
        db.flush()
    return created, organizations


def build_module_control_center_from_parts(
    *,
    auto_registered_count: int,
    organizations: list[OrganizationRecord],
    manifests: list[ModuleManifestV1],
    state_lookup: dict[tuple[str, str], ModuleControlStateRecord],
) -> ModuleControlCenterResponse:
    module_ids = [manifest.module_key for manifest in manifests]
    manifest_by_key = {manifest.module_key: manifest for manifest in manifests}
    groups: list[ModuleControlOrgGroup] = []
    for organization in organizations:
        modules: list[ModuleControlStateRead] = []
        for module_id in module_ids:
            manifest = manifest_by_key.get(module_id)
            if manifest is not None and not _module_allowed_for_organization(
                organization,
                manifest,
            ):
                continue
            record = state_lookup.get((organization.org_id, module_id))
            if record is None:
                if manifest is None:
                    continue
                modules.append(
                    _read_default_state(
                        organization,
                        manifest,
                    )
                )
            else:
                modules.append(
                    _read_from_record(
                        record,
                        manifest=manifest_by_key.get(module_id),
                    )
                )
        groups.append(
            ModuleControlOrgGroup(
                org_id=organization.org_id,
                org_name=organization.org_name,
                modules=modules,
            )
        )
    return ModuleControlCenterResponse(
        organizations=groups,
        organization_count=len(groups),
        module_count=sum(len(group.modules) for group in groups),
        auto_registered_count=auto_registered_count,
    )


def build_module_control_center(db: Session) -> ModuleControlCenterResponse:
    organizations = list_module_control_org_summary(db)
    manifests = list_module_control_module_list(db)
    auto_registered_count, organizations = ensure_module_control_states(
        db,
        organizations=organizations,
        manifests=manifests,
    )
    lookup = list_module_control_status(
        db,
        [organization.org_id for organization in organizations],
    )
    return build_module_control_center_from_parts(
        auto_registered_count=auto_registered_count,
        organizations=organizations,
        manifests=manifests,
        state_lookup=lookup,
    )


def _module_sort_key(module: ModuleControlStateRead) -> tuple[str, str, str]:
    return (
        module.category.casefold(),
        module.display_name.casefold(),
        module.module_id.casefold(),
    )


def _org_sort_key(group: ModuleControlOrgGroup) -> tuple[str, str]:
    return (group.org_name.casefold(), group.org_id.casefold())


def _sorted_modules(
    modules: list[ModuleControlStateRead],
) -> list[ModuleControlStateRead]:
    return sorted(modules, key=_module_sort_key)


def _sorted_groups(
    groups: list[ModuleControlOrgGroup],
) -> list[ModuleControlOrgGroup]:
    return sorted(
        [
            group.model_copy(update={"modules": _sorted_modules(group.modules)})
            for group in groups
        ],
        key=_org_sort_key,
    )


def _recount_response(
    response: ModuleControlCenterResponse,
    groups: list[ModuleControlOrgGroup],
) -> ModuleControlCenterResponse:
    sorted_groups = _sorted_groups(groups)
    return response.model_copy(
        deep=True,
        update={
            "organizations": sorted_groups,
            "organization_count": len(sorted_groups),
            "module_count": sum(len(group.modules) for group in sorted_groups),
        },
    )


def _active_user_org_ids(db: Session, user: User) -> set[str]:
    org_ids: set[str] = set()
    if user.organization_id:
        organization = db.get(OrganizationRecord, user.organization_id)
        if organization is not None and organization.status != "deleted":
            org_ids.add(organization.org_id)

    memberships = db.scalars(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == str(user.id),
            OrgMembershipRecord.status == "active",
        )
    )
    membership_org_ids = [membership.org_id for membership in memberships]
    if membership_org_ids:
        active_org_ids = db.scalars(
            select(OrganizationRecord.org_id).where(
                OrganizationRecord.org_id.in_(membership_org_ids),
                OrganizationRecord.status != "deleted",
            )
        )
        org_ids.update(active_org_ids)
    return org_ids


def _assigned_module_ids_for_user(db: Session, user: User) -> set[str]:
    assignments = list_enabled_user_assignments(
        db,
        user.id,
        now=datetime.now(UTC),
    )
    if not assignments:
        return set()

    permission_keys = sorted({assignment.permission_key for assignment in assignments})
    permission_modules = db.scalars(
        select(PermissionRegistry.module_key).where(
            PermissionRegistry.permission_key.in_(permission_keys),
            PermissionRegistry.is_enabled.is_(True),
        )
    )
    assigned_module_ids = {module_key for module_key in permission_modules if module_key}
    assigned_module_ids.update(
        assignment.scope_key
        for assignment in assignments
        if assignment.scope_type == "module" and assignment.scope_key != "*"
    )
    return assigned_module_ids


def filter_module_control_center_for_user(
    db: Session,
    *,
    user: User,
    response: ModuleControlCenterResponse,
) -> ModuleControlCenterResponse:
    if is_owner_role(user.role):
        return _recount_response(response, list(response.organizations))

    org_ids = _active_user_org_ids(db, user)
    if not org_ids:
        return _recount_response(response, [])

    scoped_groups = [
        group
        for group in response.organizations
        if group.org_id in org_ids
    ]
    if is_super_admin_role(user.role):
        return _recount_response(response, scoped_groups)

    assigned_module_ids = _assigned_module_ids_for_user(db, user)
    filtered_groups = [
        group.model_copy(
            update={
                "modules": [
                    module
                    for module in group.modules
                    if module.module_id in assigned_module_ids
                    or (
                        _is_r_series_module(module.module_id)
                        and group.org_name.strip() == R_SERIES_ORGANIZATION_NAME
                    )
                ]
            }
        )
        for group in scoped_groups
    ]
    return _recount_response(response, filtered_groups)


def get_module_control_state(
    db: Session,
    *,
    org_id: str,
    module_id: str,
) -> ModuleControlStateRecord | None:
    return db.scalar(
        select(ModuleControlStateRecord).where(
            ModuleControlStateRecord.org_id == org_id,
            ModuleControlStateRecord.module_id == module_id,
        )
    )


def update_module_control_state(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    payload: ModuleControlUpdateRequest,
    actor_user_id: str,
) -> ModuleControlStateRead:
    manifest = get_module_manifest_for_db(db, module_id)
    if manifest is None:
        raise ModuleControlError("module_not_registered")
    organization = db.get(OrganizationRecord, org_id)
    if organization is None or organization.status == "deleted":
        raise ModuleControlError("organization_not_found")
    if not _module_allowed_for_organization(organization, manifest):
        raise ModuleControlError("module_not_available_for_organization")

    record = get_module_control_state(db, org_id=org_id, module_id=module_id)
    if record is None:
        record = ModuleControlStateRecord(
            org_id=org_id,
            module_id=module_id,
            enabled=True,
            runtime_status="active",
            metadata_json={"source": "auto_registered_before_update"},
        )
        db.add(record)
        db.flush()

    record.enabled = payload.enabled
    record.runtime_status = _runtime_status_for_enabled(payload.enabled)
    record.updated_by_user_id = actor_user_id
    if payload.enabled:
        record.runtime_error_code = None
        record.runtime_error_message = None
        record.last_error_at = None
    else:
        record.runtime_error_code = payload.runtime_error_code
        record.runtime_error_message = payload.runtime_error_message
        if payload.runtime_error_code or payload.runtime_error_message:
            record.runtime_status = "error"
            record.last_error_at = datetime.now(UTC)
    db.add(record)
    db.flush()
    return _read_from_record(record, manifest=manifest)


def record_module_runtime_error(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    error_code: str,
    error_message: str,
) -> ModuleControlStateRead:
    manifest = get_module_manifest_for_db(db, module_id)
    if manifest is None:
        raise ModuleControlError("module_not_registered")
    organization = db.get(OrganizationRecord, org_id)
    if organization is None or organization.status == "deleted":
        raise ModuleControlError("organization_not_found")
    if not _module_allowed_for_organization(organization, manifest):
        raise ModuleControlError("module_not_available_for_organization")
    record = get_module_control_state(db, org_id=org_id, module_id=module_id)
    if record is None:
        record = ModuleControlStateRecord(
            org_id=org_id,
            module_id=module_id,
            enabled=True,
            runtime_status="active",
            metadata_json={"source": "auto_registered_before_runtime_error"},
        )
    record.runtime_status = "error"
    record.runtime_error_code = error_code[:128]
    record.runtime_error_message = error_message[:1000]
    record.last_error_at = datetime.now(UTC)
    db.add(record)
    db.flush()
    return _read_from_record(record, manifest=manifest)
