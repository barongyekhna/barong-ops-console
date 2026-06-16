from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.roles import is_owner_role
from ..models.org_membership import OrgMembershipRecord
from ..models.user import User
from ..schemas.module_binding import (
    GLOBAL_MODULE_BOUND_ORG,
    ModuleBindRequest,
    ModuleBinding,
    OrgVisibleModulesResponse,
)
from .event_collector import emit_event


class ModuleBindingError(ValueError):
    pass


class ModuleBindingNotFoundError(ModuleBindingError):
    pass


class ModuleBindingPermissionDeniedError(PermissionError):
    pass


_MODULE_BINDINGS: dict[str, ModuleBinding] = {}
_MODULE_BINDINGS_LOCK = RLock()


def _now() -> datetime:
    return datetime.now(UTC)


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _is_owner(actor: User) -> bool:
    return is_owner_role(actor.role)


def _record_active_membership(
    db: Session,
    *,
    user_id: str,
    org_id: str,
) -> OrgMembershipRecord | None:
    return db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == user_id,
            OrgMembershipRecord.org_id == org_id,
            OrgMembershipRecord.status == "active",
        )
    )


def _active_org_ids_for_actor(db: Session, actor: User) -> set[str]:
    return set(
        db.scalars(
            select(OrgMembershipRecord.org_id).where(
                OrgMembershipRecord.user_id == _actor_user_id(actor),
                OrgMembershipRecord.status == "active",
            )
        )
    )


def _ensure_can_view_org_modules(db: Session, *, org_id: str, actor: User) -> None:
    if _is_owner(actor):
        return
    if (
        _record_active_membership(
            db,
            user_id=_actor_user_id(actor),
            org_id=org_id,
        )
        is None
    ):
        raise ModuleBindingPermissionDeniedError(
            "Active organization membership is required to view modules."
        )


def _redact_binding_to_actor_orgs(
    binding: ModuleBinding,
    active_org_ids: set[str],
) -> ModuleBinding:
    if binding.mode == "global":
        return binding
    visible_bound_orgs = [
        org_id for org_id in binding.bound_orgs if org_id in active_org_ids
    ]
    if not visible_bound_orgs:
        raise ModuleBindingPermissionDeniedError("Module is not visible to actor.")
    return binding.model_copy(update={"bound_orgs": visible_bound_orgs})


def reset_module_binding_registry() -> None:
    with _MODULE_BINDINGS_LOCK:
        _MODULE_BINDINGS.clear()


def list_module_bindings() -> list[ModuleBinding]:
    with _MODULE_BINDINGS_LOCK:
        return list(_MODULE_BINDINGS.values())


def get_module_binding(module_id: str) -> ModuleBinding:
    lookup = ModuleBindRequest(
        module_id=module_id,
        org_id="org_lookup",
        mode="single",
    ).module_id
    with _MODULE_BINDINGS_LOCK:
        binding = _MODULE_BINDINGS.get(lookup)
    if binding is None:
        raise ModuleBindingNotFoundError("Module binding not found.")
    return binding


def get_visible_modules(
    user_org_id: str,
    bindings: list[ModuleBinding] | None = None,
) -> list[ModuleBinding]:
    scoped_org_id = ModuleBindRequest(
        module_id="lookup",
        org_id=user_org_id,
        mode="single",
    ).org_id
    source = bindings if bindings is not None else list_module_bindings()
    return [
        binding
        for binding in source
        if binding.enabled
        and (
            binding.mode == "global"
            or scoped_org_id in binding.bound_orgs
        )
    ]


def get_visible_module_ids(user_org_id: str) -> list[str]:
    return [binding.module_id for binding in get_visible_modules(user_org_id)]


def bind_module_to_org(payload: ModuleBindRequest, *, actor: User) -> ModuleBinding:
    if not _is_owner(actor):
        raise ModuleBindingPermissionDeniedError(
            "Owner role is required to modify module bindings."
        )

    now = _now()
    with _MODULE_BINDINGS_LOCK:
        existing = _MODULE_BINDINGS.get(payload.module_id)
        created_at = existing.created_at if existing is not None else now

        if payload.mode == "global":
            bound_orgs = [GLOBAL_MODULE_BOUND_ORG]
        elif payload.mode == "single":
            bound_orgs = [payload.org_id]
        else:
            bound_orgs = [payload.org_id]
            if existing is not None and existing.mode != "global":
                bound_orgs = list(dict.fromkeys([*existing.bound_orgs, payload.org_id]))

        binding = ModuleBinding(
            module_id=payload.module_id,
            bound_orgs=bound_orgs,
            mode=payload.mode,
            enabled=True,
            created_at=created_at,
            updated_at=now,
        )
        _MODULE_BINDINGS[payload.module_id] = binding

    emit_event(
        event_type="module_binding.update",
        module="C18D",
        action="module.bind",
        source="backend",
        status="success",
        user_id=_actor_user_id(actor),
        payload={
            "module_id": binding.module_id,
            "mode": binding.mode,
            "bound_org_count": len(binding.bound_orgs),
            "visibility_only": True,
            "data_access_granted": False,
        },
    )
    return binding


def get_module_binding_for_actor(
    db: Session,
    *,
    module_id: str,
    actor: User,
) -> ModuleBinding:
    binding = get_module_binding(module_id)
    if _is_owner(actor):
        return binding
    active_org_ids = _active_org_ids_for_actor(db, actor)
    if not active_org_ids:
        raise ModuleBindingPermissionDeniedError(
            "Active organization membership is required to view module bindings."
        )
    return _redact_binding_to_actor_orgs(binding, active_org_ids)


def list_org_visible_modules_for_actor(
    db: Session,
    *,
    org_id: str,
    actor: User,
) -> OrgVisibleModulesResponse:
    _ensure_can_view_org_modules(db, org_id=org_id, actor=actor)
    visible_bindings = get_visible_modules(org_id)
    visible_modules = [binding.module_id for binding in visible_bindings]
    emit_event(
        event_type="module_binding.read",
        module="C18D",
        action="org.modules.visible",
        source="backend",
        status="success",
        user_id=_actor_user_id(actor),
        payload={
            "org_id": org_id,
            "count": len(visible_modules),
            "visibility_only": True,
            "data_access_granted": False,
        },
    )
    return OrgVisibleModulesResponse(
        org_id=org_id,
        visible_modules=visible_modules,
        bindings=visible_bindings,
        count=len(visible_modules),
    )
