from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.module_control import ModuleControlStateRecord
from ..models.organization import OrganizationRecord
from ..schemas.module_control import (
    ModuleControlCenterResponse,
    ModuleControlOrgGroup,
    ModuleControlStateRead,
    ModuleControlUpdateRequest,
)
from .module_registry import get_module_manifest, list_module_manifests


class ModuleControlError(ValueError):
    pass


def _active_organizations(db: Session) -> list[OrganizationRecord]:
    return list(
        db.scalars(
            select(OrganizationRecord)
            .where(OrganizationRecord.status != "deleted")
            .order_by(OrganizationRecord.org_name, OrganizationRecord.org_id)
        )
    )


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


def _runtime_status_for_enabled(enabled: bool) -> str:
    return "active" if enabled else "disabled"


def _read_from_record(record: ModuleControlStateRecord) -> ModuleControlStateRead:
    manifest = get_module_manifest(record.module_id)
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


def ensure_module_control_states(db: Session) -> tuple[int, list[OrganizationRecord]]:
    organizations = _active_organizations(db)
    manifests = list_module_manifests()
    lookup = _state_lookup(db, [organization.org_id for organization in organizations])
    created = 0
    for organization in organizations:
        for manifest in manifests:
            key = (organization.org_id, manifest.module_key)
            if key in lookup:
                continue
            record = ModuleControlStateRecord(
                org_id=organization.org_id,
                module_id=manifest.module_key,
                enabled=True,
                runtime_status="active",
                metadata_json={"source": "auto_registered_from_manifest"},
            )
            db.add(record)
            lookup[key] = record
            created += 1
    if created:
        db.flush()
    return created, organizations


def build_module_control_center(db: Session) -> ModuleControlCenterResponse:
    created, organizations = ensure_module_control_states(db)
    manifests = list_module_manifests()
    module_ids = [manifest.module_key for manifest in manifests]
    lookup = _state_lookup(db, [organization.org_id for organization in organizations])
    groups: list[ModuleControlOrgGroup] = []
    for organization in organizations:
        modules: list[ModuleControlStateRead] = []
        for module_id in module_ids:
            record = lookup.get((organization.org_id, module_id))
            if record is None:
                continue
            modules.append(_read_from_record(record))
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
        auto_registered_count=created,
    )


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
    manifest = get_module_manifest(module_id)
    if manifest is None:
        raise ModuleControlError("module_not_registered")
    organization = db.get(OrganizationRecord, org_id)
    if organization is None or organization.status == "deleted":
        raise ModuleControlError("organization_not_found")

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
    return _read_from_record(record)


def record_module_runtime_error(
    db: Session,
    *,
    org_id: str,
    module_id: str,
    error_code: str,
    error_message: str,
) -> ModuleControlStateRead:
    manifest = get_module_manifest(module_id)
    if manifest is None:
        raise ModuleControlError("module_not_registered")
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
    return _read_from_record(record)
