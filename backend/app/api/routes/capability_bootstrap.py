from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.live_gate import LiveGatePolicyRead
from ...schemas.module import (
    ModuleAccessListResponse,
    ModuleManifestRead,
    ModuleRegistryResponse,
)
from ...schemas.module_control import ModuleControlCenterResponse
from ...schemas.module_adapter import (
    ModuleAdapterAccessListResponse,
    ModuleAdapterRead,
    ModuleAdapterRegistryResponse,
)
from ...services.live_gating_controller import PLATFORM_ORG_ID, LiveGatingController
from ...services.module_adapter_registry import (
    list_adapter_contracts,
    list_adapters_for_user,
)
from ...services.module_control_cache_service import (
    get_module_control_center_cached,
    refresh_module_control_center_cache_sync,
)
from ...services.module_registry import (
    clear_module_registry_cache,
    list_module_manifests_with_dynamic,
    list_modules_for_user,
)
from ...services.permission_decision_engine import PermissionDecisionEngine
from ...services.unified_permission_engine import UnifiedPermissionRequest
from ..deps import require_cached_control_plane_admin

router = APIRouter(prefix="/capability", tags=["capability-bootstrap"])
logger = logging.getLogger(__name__)
FRONTEND_FORCE_REFRESH_HEADER = "x-frontend-force-refresh"

CapabilityEntry = dict[str, Any]


def _is_force_refresh_request(request: Request) -> bool:
    return (
        request.headers.get(FRONTEND_FORCE_REFRESH_HEADER) == "1"
        or request.query_params.get("force_refresh") == "1"
        or request.query_params.get("_force_refresh") == "1"
    )


def _entry(*, ok: bool, status: int, data: Any = None, detail: Any = None) -> CapabilityEntry:
    return {
        "data": jsonable_encoder(data) if ok else None,
        "detail": None if ok else detail,
        "ok": ok,
        "status": status,
    }


def _deferred_entry(detail: str) -> CapabilityEntry:
    return _entry(ok=False, status=503, detail=detail)


def _can_read_target(
    *,
    db: Session,
    request: Request,
    user: User,
    module_id: str,
    action: str,
) -> bool:
    decision = PermissionDecisionEngine(db, request=request).decide_platform_metadata(
        UnifiedPermissionRequest(
            user_id=user.id,
            org_id=getattr(request.state, "org_id", None),
            module_id=module_id,
            action=action,
            role=user.role,
            scope_type="global",
            scope_key="*",
            source="capability_bootstrap_batch",
        )
    )
    return decision.allowed


def _target_entry(
    *,
    db: Session,
    request: Request,
    user: User,
    module_id: str,
    action: str,
    loader: Callable[[], Any],
) -> CapabilityEntry:
    if not _can_read_target(
        db=db,
        request=request,
        user=user,
        module_id=module_id,
        action=action,
    ):
        return _entry(
            ok=False,
            status=403,
            detail="Permission denied.",
        )

    try:
        return _entry(ok=True, status=200, data=loader())
    except Exception:
        logger.exception(
            "Capability bootstrap subrequest failed module=%s action=%s request_id=%s",
            module_id,
            action,
            getattr(request.state, "context_id", None),
        )
        return _entry(
            ok=False,
            status=500,
            detail="Capability bootstrap subrequest failed.",
        )


@router.get("/bootstrap")
def capability_bootstrap(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_cached_control_plane_admin),
) -> dict[str, CapabilityEntry]:
    force_refresh = _is_force_refresh_request(request)
    if force_refresh:
        clear_module_registry_cache()

    def modules_registry() -> ModuleRegistryResponse:
        manifests = list_module_manifests_with_dynamic(db)
        items = [
            ModuleManifestRead.model_validate(manifest.model_dump())
            for manifest in manifests
        ]
        return ModuleRegistryResponse(items=items, count=len(items))

    def modules_me() -> ModuleAccessListResponse:
        permission_info, items = list_modules_for_user(db, user, request=request)
        return ModuleAccessListResponse(
            user_id=user.id,
            role=user.role,
            is_owner_full_access=permission_info.is_owner_full_access,
            items=items,
            count=len(items),
        )

    def module_adapters_registry() -> ModuleAdapterRegistryResponse:
        adapters = list_adapter_contracts()
        items = [
            ModuleAdapterRead.model_validate(adapter.model_dump())
            for adapter in adapters
        ]
        return ModuleAdapterRegistryResponse(items=items, count=len(items))

    def module_adapters_me() -> ModuleAdapterAccessListResponse:
        permission_info, items = list_adapters_for_user(db, user, request=request)
        return ModuleAdapterAccessListResponse(
            user_id=user.id,
            role=user.role,
            is_owner_full_access=permission_info.is_owner_full_access,
            items=items,
            count=len(items),
        )

    def live_gate_policies() -> list[LiveGatePolicyRead]:
        return LiveGatingController(db).list_policies(org_id=PLATFORM_ORG_ID)

    def module_control_center() -> ModuleControlCenterResponse:
        if force_refresh:
            return refresh_module_control_center_cache_sync()
        return get_module_control_center_cached(db=db)

    return {
        "modules_registry": _target_entry(
            db=db,
            request=request,
            user=user,
            module_id="REGISTRY",
            action="admin",
            loader=modules_registry,
        ),
        "modules_me": _target_entry(
            db=db,
            request=request,
            user=user,
            module_id="C16",
            action="admin",
            loader=modules_me,
        ),
        "module_control_center": _target_entry(
            db=db,
            request=request,
            user=user,
            module_id="REGISTRY",
            action="admin",
            loader=module_control_center,
        ),
        "module_adapters_registry": _target_entry(
            db=db,
            request=request,
            user=user,
            module_id="C14",
            action="admin",
            loader=module_adapters_registry,
        ),
        "module_adapters_me": _target_entry(
            db=db,
            request=request,
            user=user,
            module_id="C14",
            action="admin",
            loader=module_adapters_me,
        ),
        "execution_providers_registry": _deferred_entry(
            "Execution provider registry is deferred from capability bootstrap."
        ),
        "execution_providers_me": _deferred_entry(
            "Execution provider access is deferred from capability bootstrap."
        ),
        "live_gate_readiness": _deferred_entry(
            "Live gate readiness is deferred from capability bootstrap."
        ),
        "live_gate_production_readiness": _deferred_entry(
            "Production readiness is deferred from capability bootstrap."
        ),
        "live_gate_policies": _target_entry(
            db=db,
            request=request,
            user=user,
            module_id="GOVERNANCE",
            action="admin",
            loader=live_gate_policies,
        ),
    }
