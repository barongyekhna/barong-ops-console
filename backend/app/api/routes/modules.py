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


@router.get("", response_model=ListResponse[ModuleResponse])
def modules(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ListResponse[ModuleResponse]:
    del user
    items = list_modules(db, limit=limit, offset=offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/registry", response_model=ModuleRegistryResponse)
def module_registry(
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ModuleRegistryResponse:
    del user
    manifests = list_module_manifests()
    items = [
        ModuleManifestRead.model_validate(manifest.model_dump())
        for manifest in manifests
    ]
    return ModuleRegistryResponse(items=items, count=len(items))


@router.get("/me", response_model=ModuleAccessListResponse)
def modules_me(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_cached_control_plane_admin),
) -> ModuleAccessListResponse:
    permission_info, items = list_modules_for_user(db, user, request=request)
    return ModuleAccessListResponse(
        user_id=user.id,
        role=user.role,
        is_owner_full_access=permission_info.is_owner_full_access,
        items=items,
        count=len(items),
    )


@router.get("/{module_key}", response_model=ModuleResponse)
def module_detail(
    module_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ModuleResponse:
    del user
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
