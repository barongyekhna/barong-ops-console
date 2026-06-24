import logging
from threading import Lock
from time import monotonic

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
    clear_module_registry_cache,
    list_module_manifests_with_dynamic,
    list_modules_for_user,
)
from ...services.module_control_cache_service import (
    refresh_module_control_center_cache_async,
)
from ..deps import (
    get_audit_context,
    require_cached_control_plane_admin,
    require_rbac,
)

router = APIRouter(prefix="/modules", tags=["modules"])
logger = logging.getLogger(__name__)
MODULE_READ_CACHE_TTL_SECONDS = 5.0
FRONTEND_FORCE_REFRESH_HEADER = "x-frontend-force-refresh"
_module_cache_lock = Lock()
_modules_list_cache: dict[tuple[int, int], tuple[float, ListResponse[ModuleResponse]]] = {}
_module_registry_cache: tuple[float, ModuleRegistryResponse] | None = None
_modules_me_cache: dict[tuple[int, str], tuple[float, ModuleAccessListResponse]] = {}
_module_detail_cache: dict[str, tuple[float, ModuleResponse]] = {}


def _clear_module_read_caches() -> None:
    global _module_registry_cache
    with _module_cache_lock:
        _modules_list_cache.clear()
        _module_registry_cache = None
        _modules_me_cache.clear()
        _module_detail_cache.clear()


def _is_force_refresh_request(request: Request) -> bool:
    return (
        request.headers.get(FRONTEND_FORCE_REFRESH_HEADER) == "1"
        or request.query_params.get("force_refresh") == "1"
        or request.query_params.get("_force_refresh") == "1"
    )


def clear_module_read_caches() -> None:
    _clear_module_read_caches()
    clear_module_registry_cache()
    refresh_module_control_center_cache_async(force=True)


@router.get("", response_model=ListResponse[ModuleResponse])
def modules(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    guard: None = Depends(
        guarded_heavy_api_request(
            "modules.list",
            allow_idempotent_duplicates=True,
        )
    ),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ListResponse[ModuleResponse]:
    del guard, user
    if _is_force_refresh_request(request):
        clear_module_read_caches()
    list_cache_key = (limit, offset)
    now = monotonic()
    with _module_cache_lock:
        cached = _modules_list_cache.get(list_cache_key)
        if cached is not None and cached[0] > now:
            return cached[1].model_copy(deep=True)

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
        with _module_cache_lock:
            _modules_list_cache[list_cache_key] = (
                monotonic() + MODULE_READ_CACHE_TTL_SECONDS,
                response.model_copy(deep=True),
            )
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
    guard: None = Depends(
        guarded_heavy_api_request(
            "modules.registry",
            allow_idempotent_duplicates=True,
        )
    ),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ModuleRegistryResponse:
    global _module_registry_cache
    del guard, user
    if _is_force_refresh_request(request):
        clear_module_read_caches()
    now = monotonic()
    with _module_cache_lock:
        cached = _module_registry_cache
        if cached is not None and cached[0] > now:
            return cached[1].model_copy(deep=True)

    cache_key = api_snapshot_key("modules.registry")
    try:
        manifests = list_module_manifests_with_dynamic(db)
        items = [
            ModuleManifestRead.model_validate(manifest.model_dump())
            for manifest in manifests
        ]
        response = ModuleRegistryResponse(items=items, count=len(items))
        save_api_snapshot(cache_key, response)
        with _module_cache_lock:
            _module_registry_cache = (
                monotonic() + MODULE_READ_CACHE_TTL_SECONDS,
                response.model_copy(deep=True),
            )
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
    guard: None = Depends(
        guarded_heavy_api_request(
            "modules.me",
            allow_idempotent_duplicates=True,
        )
    ),
    db: Session = Depends(get_db),
    user: User = Depends(require_cached_control_plane_admin),
) -> ModuleAccessListResponse:
    del guard
    if _is_force_refresh_request(request):
        clear_module_read_caches()
    me_cache_key = (int(user.id), str(user.role))
    now = monotonic()
    with _module_cache_lock:
        cached = _modules_me_cache.get(me_cache_key)
        if cached is not None and cached[0] > now:
            return cached[1].model_copy(deep=True)

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
        with _module_cache_lock:
            _modules_me_cache[me_cache_key] = (
                monotonic() + MODULE_READ_CACHE_TTL_SECONDS,
                response.model_copy(deep=True),
            )
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
    guard: None = Depends(
        guarded_heavy_api_request(
            "modules.detail",
            allow_idempotent_duplicates=True,
        )
    ),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ModuleResponse:
    del guard, user
    now = monotonic()
    with _module_cache_lock:
        cached = _module_detail_cache.get(module_key)
        if cached is not None and cached[0] > now:
            return cached[1].model_copy(deep=True)

    module = get_module(db, module_key)
    if module is None:
        raise not_found("Module", module_key)
    response = ModuleResponse.model_validate(module)
    with _module_cache_lock:
        _module_detail_cache[module_key] = (
            monotonic() + MODULE_READ_CACHE_TTL_SECONDS,
            response.model_copy(deep=True),
        )
    return response


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
    _clear_module_read_caches()
    refresh_module_control_center_cache_async(force=True)
    return ModuleResponse.model_validate(module)
