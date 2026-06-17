from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models.module_binding import ModuleBindingRecord
from ..schemas.module_binding import GLOBAL_MODULE_BOUND_ORG, ModuleBinding


def _now() -> datetime:
    return datetime.now(UTC)


def _binding_from_records(records: Iterable[ModuleBindingRecord]) -> ModuleBinding:
    items = list(records)
    if not items:
        raise ValueError("Module binding requires at least one record.")

    enabled_items = [item for item in items if item.status == "enabled"]
    source_items = enabled_items or items
    module_id = source_items[0].module_id
    bound_orgs = [item.org_id for item in source_items]
    if GLOBAL_MODULE_BOUND_ORG in bound_orgs:
        bound_orgs = [GLOBAL_MODULE_BOUND_ORG]
        mode = "global"
    elif len(bound_orgs) == 1:
        mode = "single"
    else:
        mode = "multi"

    created_at = min(item.created_at for item in source_items)
    updated_at = max(item.updated_at for item in source_items)
    return ModuleBinding(
        module_id=module_id,
        bound_orgs=bound_orgs,
        mode=mode,
        enabled=bool(enabled_items),
        created_at=created_at,
        updated_at=updated_at,
    )


def list_module_binding_records(db: Session) -> list[ModuleBindingRecord]:
    return list(
        db.scalars(
            select(ModuleBindingRecord).order_by(
                ModuleBindingRecord.id,
            )
        )
    )


def list_module_bindings(db: Session) -> list[ModuleBinding]:
    grouped: dict[str, list[ModuleBindingRecord]] = {}
    for record in list_module_binding_records(db):
        grouped.setdefault(record.module_id, []).append(record)
    return [_binding_from_records(records) for records in grouped.values()]


def get_module_binding(db: Session, module_id: str) -> ModuleBinding | None:
    records = list(
        db.scalars(
            select(ModuleBindingRecord)
            .where(ModuleBindingRecord.module_id == module_id)
            .order_by(ModuleBindingRecord.org_id)
        )
    )
    if not records:
        return None
    return _binding_from_records(records)


def replace_module_binding(
    db: Session,
    *,
    module_id: str,
    bound_orgs: list[str],
) -> ModuleBinding:
    now = _now()
    existing = list(
        db.scalars(
            select(ModuleBindingRecord).where(
                ModuleBindingRecord.module_id == module_id
            )
        )
    )
    created_by_org = {record.org_id: record.created_at for record in existing}

    db.execute(
        delete(ModuleBindingRecord).where(ModuleBindingRecord.module_id == module_id)
    )
    for org_id in bound_orgs:
        db.add(
            ModuleBindingRecord(
                org_id=org_id,
                module_id=module_id,
                status="enabled",
                created_at=created_by_org.get(org_id, now),
                updated_at=now,
            )
        )
    db.flush()
    binding = get_module_binding(db, module_id)
    if binding is None:
        raise ValueError("Module binding persistence failed.")
    return binding


def clear_module_bindings(db: Session) -> None:
    db.execute(delete(ModuleBindingRecord))
    db.flush()
