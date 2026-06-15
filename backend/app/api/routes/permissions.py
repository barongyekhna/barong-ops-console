from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.common import ListResponse
from ...schemas.permission import (
    CurrentUserPermissionResponse,
    CurrentUserPermissionsRead,
    PermissionAssignmentActionResponse,
    PermissionAssignmentCreate,
    PermissionAssignmentListResponse,
    PermissionAssignmentRead,
    PermissionAssignmentRevokeRequest,
    PermissionAssignmentUpdate,
    PermissionRegistryRead,
)
from ...services.permission_service import (
    PermissionAssignmentDuplicateError,
    PermissionAssignmentHighRiskConfirmationError,
    PermissionAssignmentHighRiskReasonError,
    PermissionAssignmentKeyUpdateNotAllowedError,
    PermissionAssignmentNotFoundError,
    PermissionAssignmentOwnerTargetError,
    PermissionAssignmentWildcardError,
    PermissionDisabledError,
    PermissionNotFoundError,
    PermissionServiceError,
    PermissionUserNotFoundError,
    grant_user_permission,
    list_user_permission_assignments,
    list_enabled_permissions,
    resolve_current_user_permission_info,
    revoke_user_assignment,
    update_user_assignment,
)
from ..deps import get_audit_context, require_owner, require_rbac

router = APIRouter(prefix="/permissions", tags=["permissions"])


def _raise_permission_assignment_error(exc: Exception) -> None:
    if isinstance(exc, PermissionUserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    if isinstance(exc, PermissionAssignmentNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    if isinstance(exc, PermissionAssignmentDuplicateError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if isinstance(
        exc,
        (
            PermissionAssignmentHighRiskConfirmationError,
            PermissionAssignmentHighRiskReasonError,
            PermissionAssignmentKeyUpdateNotAllowedError,
            PermissionAssignmentOwnerTargetError,
            PermissionAssignmentWildcardError,
            PermissionDisabledError,
            PermissionNotFoundError,
            PermissionServiceError,
            ValueError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    raise exc


def _assignment_action_response(
    result,
) -> PermissionAssignmentActionResponse:
    return PermissionAssignmentActionResponse(
        assignment=PermissionAssignmentRead.model_validate(result.assignment),
        operation_id=result.operation_id,
    )


@router.get("/me", response_model=CurrentUserPermissionResponse)
def permissions_me(
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUTH", "read")),
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
    user: User = Depends(require_rbac("C16", "admin")),
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


@router.get(
    "/users/{user_id}/assignments",
    response_model=PermissionAssignmentListResponse,
)
def user_permission_assignments(
    user_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> PermissionAssignmentListResponse:
    del owner
    try:
        result = list_user_permission_assignments(db, user_id=user_id)
    except Exception as exc:
        _raise_permission_assignment_error(exc)
    return PermissionAssignmentListResponse.model_validate(result)


@router.post(
    "/users/{user_id}/assignments",
    response_model=PermissionAssignmentActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def user_permission_assignment_create(
    user_id: int,
    payload: PermissionAssignmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> PermissionAssignmentActionResponse:
    if payload.user_id is not None and payload.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request user_id must match path user_id.",
        )
    try:
        result = grant_user_permission(
            db,
            user_id=user_id,
            permission_key=payload.permission_key,
            scope_type=payload.scope_type,
            scope_key=payload.scope_key or "*",
            actor=owner,
            audit=get_audit_context(request),
            reason=payload.reason,
            expires_at=payload.expires_at,
            confirm_high_risk=payload.confirm_high_risk,
            confirmation_text=payload.confirmation_text,
        )
    except Exception as exc:
        _raise_permission_assignment_error(exc)
    return _assignment_action_response(result)


@router.patch(
    "/users/{user_id}/assignments/{assignment_id}",
    response_model=PermissionAssignmentActionResponse,
)
def user_permission_assignment_update(
    user_id: int,
    assignment_id: UUID,
    payload: PermissionAssignmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> PermissionAssignmentActionResponse:
    try:
        result = update_user_assignment(
            db,
            user_id=user_id,
            assignment_id=assignment_id,
            payload=payload,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_permission_assignment_error(exc)
    return _assignment_action_response(result)


@router.delete(
    "/users/{user_id}/assignments/{assignment_id}",
    response_model=PermissionAssignmentActionResponse,
)
def user_permission_assignment_revoke(
    user_id: int,
    assignment_id: UUID,
    request: Request,
    payload: PermissionAssignmentRevokeRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> PermissionAssignmentActionResponse:
    try:
        result = revoke_user_assignment(
            db,
            user_id=user_id,
            assignment_id=assignment_id,
            actor=owner,
            audit=get_audit_context(request),
            reason=payload.reason if payload is not None else None,
        )
    except Exception as exc:
        _raise_permission_assignment_error(exc)
    return _assignment_action_response(result)
