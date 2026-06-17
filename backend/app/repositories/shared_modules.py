from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models.shared_module import SharedModuleRecord
from ..schemas.shared_module import SHARED_MODULE_GLOBAL_ORG, SharedModule


def _now() -> datetime:
    return datetime.now(UTC)


def _shared_module_from_records(records: Iterable[SharedModuleRecord]) -> SharedModule:
    items = list(records)
    if not items:
        raise ValueError("Shared module requires at least one record.")

    enabled_items = [item for item in items if item.status == "enabled"]
    source_items = enabled_items or items
    first = source_items[0]
    allowed_orgs = [item.target_org_id for item in source_items]
    if SHARED_MODULE_GLOBAL_ORG in allowed_orgs:
        allowed_orgs = [SHARED_MODULE_GLOBAL_ORG]
    created_at = min(item.created_at for item in source_items)
    updated_at = max(item.updated_at for item in source_items)
    return SharedModule(
        module_id=first.module_id,
        mode=first.mode,
        allowed_orgs=allowed_orgs,
        enabled=bool(enabled_items),
        created_at=created_at,
        updated_at=updated_at,
    )


def list_shared_module_records(db: Session) -> list[SharedModuleRecord]:
    return list(
        db.scalars(
            select(SharedModuleRecord).order_by(
                SharedModuleRecord.id,
            )
        )
    )


def list_shared_modules(db: Session) -> list[SharedModule]:
    grouped: dict[str, list[SharedModuleRecord]] = {}
    for record in list_shared_module_records(db):
        grouped.setdefault(record.module_id, []).append(record)
    return [_shared_module_from_records(records) for records in grouped.values()]


def get_shared_module(db: Session, module_id: str) -> SharedModule | None:
    records = list(
        db.scalars(
            select(SharedModuleRecord)
            .where(SharedModuleRecord.module_id == module_id)
            .order_by(SharedModuleRecord.target_org_id)
        )
    )
    if not records:
        return None
    return _shared_module_from_records(records)


def replace_shared_module(
    db: Session,
    *,
    module_id: str,
    mode: str,
    allowed_orgs: list[str],
    enabled: bool,
) -> SharedModule:
    now = _now()
    existing = list(
        db.scalars(
            select(SharedModuleRecord).where(SharedModuleRecord.module_id == module_id)
        )
    )
    created_by_target = {record.target_org_id: record.created_at for record in existing}
    source_org_id = (
        SHARED_MODULE_GLOBAL_ORG
        if mode == "global"
        else next(
            org_id for org_id in allowed_orgs if org_id != SHARED_MODULE_GLOBAL_ORG
        )
    )

    db.execute(
        delete(SharedModuleRecord).where(SharedModuleRecord.module_id == module_id)
    )
    for target_org_id in allowed_orgs:
        db.add(
            SharedModuleRecord(
                source_org_id=source_org_id,
                target_org_id=target_org_id,
                module_id=module_id,
                mode=mode,
                status="enabled" if enabled else "disabled",
                created_at=created_by_target.get(target_org_id, now),
                updated_at=now,
            )
        )
    db.flush()
    module = get_shared_module(db, module_id)
    if module is None:
        raise ValueError("Shared module persistence failed.")
    return module


def clear_shared_modules(db: Session) -> None:
    db.execute(delete(SharedModuleRecord))
    db.flush()
