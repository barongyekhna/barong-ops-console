import logging

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.registry import create_module, get_module, list_modules
from ...schemas.common import ListResponse
from ...schemas.module import (
    ModuleAccessListResponse,
    ModuleManifestRead,
    ModuleRegistryResponse,
)
from ...schemas.registry import ModuleCreate, ModuleResponse
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    not_found,
)
from ...services.api_stability import (
    api_snapshot_key,
    degraded_snapshot,
    get_api_snapshot,
    raise_structured_api_error,
    save_api_snapshot,
    stable_read_failure,
)
from ...services.api_request_guard import guarded_heavy_api_request
from ...services.module_registry import (
    list_module_manifests,
    list_modules_for_user,
)
from ..deps import (
    get_audit_context,
    require_cached_control_plane_admin,
    require_rbac,
)

router = APIRouter(prefix="/modules", tags=["modules"])
logger = logging.getLogger(__name__)


@router.get("", response_model=ListResponse[ModuleResponse])
def modules(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    guard: None = Depends(guarded_heavy_api_request("modules.list")),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ListResponse[ModuleResponse]:
    del guard, user
    cache_key = api_snapshot_key("modules.list", limit, offset)
    try:
        items = list_modules(db, limit=limit, offset=offset)
        response = ListResponse(
            items=[ModuleResponse.model_validate(item) for item in items],
            count=len(items),
            limit=limit,
            offset=offset,
        )
        save_api_snapshot(cache_key, response)
        return response
    except Exception as exc:
        db.rollback()
        stable_read_failure(
            logger=logger,
            route="/modules",
            exc=exc,
            request=request,
            code="modules_list_failed",
        )
        snapshot = get_api_snapshot(cache_key)
        if snapshot is not None:
            return degraded_snapshot(
                snapshot,
                code="modules_list_failed",
                message="Module list is using the last successful snapshot because the live read failed.",
                request=request,
            )
        raise_structured_api_error(
            code="modules_list_failed",
            message="Module list is temporarily unavailable.",
            request=request,
            retryable=True,
        )


@router.get("/registry", response_model=ModuleRegistryResponse)
def module_registry(
    request: Request,
    guard: None = Depends(guarded_heavy_api_request("modules.registry")),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ModuleRegistryResponse:
    del guard, user
    cache_key = api_snapshot_key("modules.registry")
    try:
        manifests = list_module_manifests()
        items = [
            ModuleManifestRead.model_validate(manifest.model_dump())
            for manifest in manifests
        ]
        response = ModuleRegistryResponse(items=items, count=len(items))
        save_api_snapshot(cache_key, response)
        return response
    except Exception as exc:
        stable_read_failure(
            logger=logger,
            route="/modules/registry",
            exc=exc,
            request=request,
            code="modules_registry_failed",
        )
        snapshot = get_api_snapshot(cache_key)
        if snapshot is not None:
            return degraded_snapshot(
                snapshot,
                code="modules_registry_failed",
                message="Module registry is using the last successful snapshot because the live read failed.",
                request=request,
            )
        raise_structured_api_error(
            code="modules_registry_failed",
            message="Module registry is temporarily unavailable.",
            request=request,
            retryable=True,
        )


@router.get("/me", response_model=ModuleAccessListResponse)
def modules_me(
    request: Request,
    guard: None = Depends(guarded_heavy_api_request("modules.me")),
    db: Session = Depends(get_db),
    user: User = Depends(require_cached_control_plane_admin),
) -> ModuleAccessListResponse:
    del guard
    cache_key = api_snapshot_key("modules.me", user.id, user.role)
    try:
        permission_info, items = list_modules_for_user(db, user, request=request)
        response = ModuleAccessListResponse(
            user_id=user.id,
            role=user.role,
            is_owner_full_access=permission_info.is_owner_full_access,
            items=items,
            count=len(items),
        )
        save_api_snapshot(cache_key, response)
        return response
    except Exception as exc:
        db.rollback()
        stable_read_failure(
            logger=logger,
            route="/modules/me",
            exc=exc,
            request=request,
            code="modules_me_failed",
        )
        snapshot = get_api_snapshot(cache_key)
        if snapshot is not None:
            return degraded_snapshot(
                snapshot,
                code="modules_me_failed",
                message="Module access is using the last successful snapshot because the live read failed.",
                request=request,
            )
        raise_structured_api_error(
            code="modules_me_failed",
            message="Module access is temporarily unavailable.",
            request=request,
            retryable=True,
        )


@router.get("/{module_key}", response_model=ModuleResponse)
def module_detail(
    module_key: str,
    guard: None = Depends(guarded_heavy_api_request("modules.detail")),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ModuleResponse:
    del guard, user
    module = get_module(db, module_key)
    if module is None:
        raise not_found("Module", module_key)
    return ModuleResponse.model_validate(module)


@router.post(
    "",
    response_model=ModuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def module_create(
    payload: ModuleCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ModuleResponse:
    if get_module(db, payload.module_key) is not None:
        raise conflict("Module", payload.module_key)
    module = create_module(db, payload)
    audit = get_audit_context(request)
    commit_foundation_write(
        db,
        user=user,
        audit=audit,
        action="module.create_demo",
        target_type="module",
        target_id=payload.module_key,
        details={"status": payload.status},
    )
    db.refresh(module)
    return ModuleResponse.model_validate(module)
