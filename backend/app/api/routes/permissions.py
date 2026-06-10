from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.common import ListResponse
from ...schemas.permission import (
    CurrentUserPermissionResponse,
    CurrentUserPermissionsRead,
    PermissionRegistryRead,
)
from ...services.permission_service import (
    list_enabled_permissions,
    resolve_current_user_permission_info,
)
from ..deps import get_current_user, require_permission

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("/me", response_model=CurrentUserPermissionResponse)
def permissions_me(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CurrentUserPermissionResponse:
    return CurrentUserPermissionResponse(
        user_id=user.id,
        role=user.role,
        permissions=CurrentUserPermissionsRead.model_validate(
            resolve_current_user_permission_info(db, user)
        ),
    )


@router.get("/registry", response_model=ListResponse[PermissionRegistryRead])
def permissions_registry(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("permissions.read")),
) -> ListResponse[PermissionRegistryRead]:
    del user
    permissions = list_enabled_permissions(db)
    items = permissions[offset : offset + limit]
    return ListResponse(
        items=items,
        count=len(permissions),
        limit=limit,
        offset=offset,
    )
