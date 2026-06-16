from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.roles import is_owner_role
from ..models.org_membership import OrgMembershipRecord
from ..models.user import User
from ..schemas.module_binding import ModuleBinding
from ..schemas.permission import PermissionAction
from ..schemas.shared_module import (
    OrgSharedModulesResponse,
    SharedModule,
    SharedModuleCreateRequest,
    SharedModuleExecutionDecision,
    SharedModuleListResponse,
    SharedModuleMode,
    SharedModuleUpdateOrgsRequest,
)
from . import module_binding_service as c18d_module_binding
from .event_collector import emit_event
from .permission_isolation import check_permission


class SharedModuleError(ValueError):
    pass


class SharedModuleAlreadyExistsError(SharedModuleError):
    pass


class SharedModuleNotFoundError(SharedModuleError):
    pass


class SharedModulePermissionDeniedError(PermissionError):
    pass


class SharedModuleOrgContextRequiredError(SharedModulePermissionDeniedError):
    pass


_SHARED_MODULES: dict[str, SharedModule] = {}
_SHARED_MODULES_LOCK = RLock()


def _now() -> datetime:
    return datetime.now(UTC)


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _is_owner(actor: User) -> bool:
    return is_owner_role(actor.role)


def _ensure_owner(actor: User) -> None:
    if not _is_owner(actor):
        raise SharedModulePermissionDeniedError(
            "Owner role is required to modify shared modules."
        )


def _active_membership(
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


def _ensure_can_view_org_modules(db: Session, *, org_id: str, actor: User) -> None:
    if _is_owner(actor):
        return
    if (
        _active_membership(
            db,
            user_id=_actor_user_id(actor),
            org_id=org_id,
        )
        is None
    ):
        raise SharedModulePermissionDeniedError(
            "Active C18C organization membership is required to view shared modules."
        )


def _c18d_mode_for(mode: SharedModuleMode) -> str:
    if mode == "shared":
        return "multi"
    return mode


def _c18d_bound_orgs_for(module: SharedModule) -> list[str]:
    if module.mode == "global":
        return [c18d_module_binding.GLOBAL_MODULE_BOUND_ORG]
    return list(module.allowed_orgs)


def _sync_c18d_binding(module: SharedModule) -> None:
    binding = ModuleBinding(
        module_id=module.module_id,
        bound_orgs=_c18d_bound_orgs_for(module),
        mode=_c18d_mode_for(module.mode),
        enabled=module.enabled,
        created_at=module.created_at,
        updated_at=module.updated_at,
    )
    with c18d_module_binding._MODULE_BINDINGS_LOCK:
        c18d_module_binding._MODULE_BINDINGS[module.module_id] = binding


def reset_shared_module_registry() -> None:
    with _SHARED_MODULES_LOCK:
        _SHARED_MODULES.clear()


def list_shared_module_records() -> list[SharedModule]:
    with _SHARED_MODULES_LOCK:
        return list(_SHARED_MODULES.values())


def get_module(module_id: str) -> SharedModule | None:
    lookup = SharedModuleCreateRequest(
        module_id=module_id,
        mode="single",
        allowed_orgs=["org_lookup"],
    ).module_id
    with _SHARED_MODULES_LOCK:
        return _SHARED_MODULES.get(lookup)


def get_shared_module(module_id: str) -> SharedModule:
    module = get_module(module_id)
    if module is None:
        raise SharedModuleNotFoundError("Shared module not found.")
    return module


def is_module_available(user_org_id: str, module: SharedModule) -> bool:
    if not module.enabled:
        return False

    if module.mode == "global":
        return True

    if module.mode in ["multi", "shared"]:
        return user_org_id in module.allowed_orgs

    if module.mode == "single":
        return user_org_id in module.allowed_orgs

    return False


def create_shared_module(
    payload: SharedModuleCreateRequest,
    *,
    actor: User,
) -> SharedModule:
    _ensure_owner(actor)

    now = _now()
    module = SharedModule(
        module_id=payload.module_id,
        mode=payload.mode,
        allowed_orgs=payload.allowed_orgs,
        enabled=payload.enabled,
        created_at=now,
        updated_at=now,
    )
    with _SHARED_MODULES_LOCK:
        if module.module_id in _SHARED_MODULES:
            raise SharedModuleAlreadyExistsError("Shared module already exists.")
        _SHARED_MODULES[module.module_id] = module

    _sync_c18d_binding(module)
    emit_event(
        event_type="shared_module.create",
        module="C18I",
        action="shared_module.create",
        source="backend",
        status="success",
        user_id=_actor_user_id(actor),
        payload={
            "module_id": module.module_id,
            "mode": module.mode,
            "allowed_org_count": len(module.allowed_orgs),
            "module_logic_shared": module.mode == "shared",
            "shared_module_equals_shared_data": False,
            "data_access_granted": False,
        },
    )
    return module


def update_shared_module_orgs(
    payload: SharedModuleUpdateOrgsRequest,
    *,
    actor: User,
) -> SharedModule:
    _ensure_owner(actor)

    with _SHARED_MODULES_LOCK:
        existing = _SHARED_MODULES.get(payload.module_id)
        if existing is None:
            raise SharedModuleNotFoundError("Shared module not found.")

        updated = SharedModule(
            module_id=existing.module_id,
            mode=existing.mode,
            allowed_orgs=payload.allowed_orgs,
            enabled=existing.enabled,
            created_at=existing.created_at,
            updated_at=_now(),
        )
        _SHARED_MODULES[updated.module_id] = updated

    _sync_c18d_binding(updated)
    emit_event(
        event_type="shared_module.update_orgs",
        module="C18I",
        action="shared_module.update_orgs",
        source="backend",
        status="success",
        user_id=_actor_user_id(actor),
        payload={
            "module_id": updated.module_id,
            "mode": updated.mode,
            "allowed_org_count": len(updated.allowed_orgs),
            "shared_module_equals_shared_data": False,
            "data_access_granted": False,
        },
    )
    return updated


def list_shared_modules(*, actor: User) -> SharedModuleListResponse:
    _ensure_owner(actor)
    items = list_shared_module_records()
    emit_event(
        event_type="shared_module.list",
        module="C18I",
        action="shared_module.list",
        source="backend",
        status="success",
        user_id=_actor_user_id(actor),
        payload={
            "count": len(items),
            "registry_metadata_only": True,
            "data_access_granted": False,
        },
    )
    return SharedModuleListResponse(items=items, count=len(items))


def list_org_shared_modules_for_actor(
    db: Session,
    *,
    org_id: str,
    actor: User,
) -> OrgSharedModulesResponse:
    scoped_org_id = SharedModuleCreateRequest(
        module_id="lookup",
        mode="single",
        allowed_orgs=[org_id],
    ).allowed_orgs[0]
    _ensure_can_view_org_modules(db, org_id=scoped_org_id, actor=actor)
    available_modules = [
        module
        for module in list_shared_module_records()
        if is_module_available(scoped_org_id, module)
    ]
    emit_event(
        event_type="shared_module.org_available",
        module="C18I",
        action="org.shared_modules",
        source="backend",
        status="success",
        user_id=_actor_user_id(actor),
        payload={
            "org_id": scoped_org_id,
            "count": len(available_modules),
            "module_logic_shared": True,
            "shared_module_equals_shared_data": False,
            "data_access_granted": False,
        },
    )
    return OrgSharedModulesResponse(
        org_id=scoped_org_id,
        available_modules=available_modules,
        count=len(available_modules),
    )


def _org_id_from_user(user: Any) -> str | None:
    for key in ("org_id", "active_org_id"):
        value = getattr(user, key, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    org_context = getattr(user, "org_context", None)
    if org_context is not None:
        value = getattr(org_context, "org_id", None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def execute_module(
    user: Any,
    module_id: str,
    *,
    db: Session | None = None,
) -> SharedModuleExecutionDecision:
    module = get_shared_module(module_id)
    org_id = _org_id_from_user(user)
    if org_id is None:
        raise SharedModuleOrgContextRequiredError(
            "C18H org context is required before executing a shared module."
        )

    if not is_module_available(org_id, module):
        return SharedModuleExecutionDecision(
            module_id=module.module_id,
            org_id=org_id,
            allowed=False,
            denied=True,
            reason="Module is not available to the active organization.",
        )

    if db is not None:
        user_id = getattr(user, "id", None)
        if user_id is None:
            raise SharedModulePermissionDeniedError(
                "C18F permission checks require an authenticated user id."
            )
        permission = check_permission(
            db,
            user_id,
            org_id,
            module.module_id,
            PermissionAction.EXECUTE,
        )
        if permission.denied:
            return SharedModuleExecutionDecision(
                module_id=module.module_id,
                org_id=org_id,
                allowed=False,
                denied=True,
                reason=permission.reason,
            )

    emit_event(
        event_type="shared_module.execute",
        module="C18I",
        action="shared_module.execute",
        source="backend",
        status="success",
        user_id=str(getattr(user, "id", "")) or None,
        payload={
            "module_id": module.module_id,
            "org_id": org_id,
            "mode": module.mode,
            "c18f_permission_required": True,
            "c18g_data_isolation_required": True,
            "c18h_org_context_required": True,
            "shared_module_equals_shared_data": False,
            "runtime_state_shared": False,
        },
    )
    return SharedModuleExecutionDecision(
        module_id=module.module_id,
        org_id=org_id,
        allowed=True,
        denied=False,
        reason="Module logic may execute inside the active org context.",
    )
