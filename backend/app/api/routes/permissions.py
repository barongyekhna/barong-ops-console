import logging
from threading import Lock
from time import monotonic
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ...core.roles import is_owner_role, is_super_admin_role
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
    permission_response_category,
)
from ...services.api_stability import (
    api_error_info,
    api_snapshot_key,
    degraded_snapshot,
    get_api_snapshot,
    raise_structured_api_error,
    save_api_snapshot,
    stable_read_failure,
)
from ...services.api_request_guard import guarded_heavy_api_request
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
    upsert_permission_registry,
)
from ..deps import get_audit_context, require_owner, require_rbac

router = APIRouter(prefix="/permissions", tags=["permissions"])
logger = logging.getLogger(__name__)
PERMISSION_READ_CACHE_TTL_SECONDS = 5.0
_permission_cache_lock = Lock()
_permission_me_cache: dict[tuple[int, str], tuple[float, CurrentUserPermissionResponse]] = {}
_permission_registry_cache: dict[
    tuple[bool, int, int],
    tuple[float, ListResponse[PermissionRegistryRead]],
] = {}


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


def _current_user_permission_response(
    *,
    user: User,
    permissions: CurrentUserPermissionsRead,
) -> CurrentUserPermissionResponse:
    return CurrentUserPermissionResponse(
        id=user.id,
        user_id=user.id,
        role=user.role,
        is_owner=is_owner_role(user.role),
        permission_keys=permissions.permission_keys,
        permissions=permissions,
    )


def _owner_permissions_me_response(user: User) -> CurrentUserPermissionResponse:
    permissions = CurrentUserPermissionsRead(
        is_owner_full_access=True,
        permission_keys=["*"],
        assignments=[],
        scope_summary=[],
    )
    return _current_user_permission_response(
        user=user,
        permissions=permissions,
    )


def _permission_registry_response_item(permission) -> PermissionRegistryRead:
    return PermissionRegistryRead(
        id=permission.id,
        permission_key=permission.permission_key,
        module_key=permission.module_key,
        category=permission_response_category(
            module_key=permission.module_key,
            permission_key=permission.permission_key,
        ),
        action=permission.action,
        label=permission.label,
        description=permission.description,
        risk_level=permission.risk_level,
        menu_policy=permission.menu_policy,
        is_system=permission.is_system,
        is_enabled=permission.is_enabled,
        created_at=permission.created_at,
        updated_at=permission.updated_at,
    )


@router.get("/me", response_model=CurrentUserPermissionResponse)
def permissions_me(
    guard: None = Depends(
        guarded_heavy_api_request(
            "permissions.me",
            allow_idempotent_duplicates=True,
        )
    ),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUTH", "read")),
) -> CurrentUserPermissionResponse:
    del guard
    cache_key = (int(user.id), str(user.role))
    now = monotonic()
    with _permission_cache_lock:
        cached = _permission_me_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1].model_copy(deep=True)

    if is_owner_role(user.role):
        response = _owner_permissions_me_response(user)
        with _permission_cache_lock:
            _permission_me_cache[cache_key] = (
                monotonic() + PERMISSION_READ_CACHE_TTL_SECONDS,
                response.model_copy(deep=True),
            )
        return response

    permissions = CurrentUserPermissionsRead.model_validate(
        resolve_current_user_permission_info(db, user)
    )
    response = _current_user_permission_response(
        user=user,
        permissions=permissions,
    )
    with _permission_cache_lock:
        _permission_me_cache[cache_key] = (
            monotonic() + PERMISSION_READ_CACHE_TTL_SECONDS,
            response.model_copy(deep=True),
        )
    return response


@router.get("/registry", response_model=ListResponse[PermissionRegistryRead])
def permissions_registry(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    guard: None = Depends(
        guarded_heavy_api_request(
            "permissions.registry",
            allow_idempotent_duplicates=True,
        )
    ),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("C16", "admin")),
) -> ListResponse[PermissionRegistryRead]:
    del guard
    can_read_full_registry = is_owner_role(user.role) or is_super_admin_role(user.role)
    registry_cache_key = (can_read_full_registry, limit, offset)
    now = monotonic()
    with _permission_cache_lock:
        cached = _permission_registry_cache.get(registry_cache_key)
        if cached is not None and cached[0] > now:
            return cached[1].model_copy(deep=True)

    cache_key = api_snapshot_key("permissions.registry", limit, offset)
    try:
        permissions = list_enabled_permissions(db)
        if not permissions:
            upsert_permission_registry(db)
            permissions = list_enabled_permissions(db)
        visible_permissions = (
            permissions
            if can_read_full_registry
            else [
                permission
                for permission in permissions
                if permission_response_category(
                    module_key=permission.module_key,
                    permission_key=permission.permission_key,
                )
                == "feature"
            ]
        )
        items = [
            _permission_registry_response_item(permission)
            for permission in visible_permissions[offset : offset + limit]
        ]
        response = ListResponse(
            items=items,
            count=len(visible_permissions),
            limit=limit,
            offset=offset,
            degraded=not bool(permissions),
            error=(
                api_error_info(
                    code="permission_registry_empty",
                    message="Permission registry is empty after seed repair.",
                    request=request,
                    retryable=True,
                )
                if not permissions
                else None
            ),
        )
        if permissions:
            save_api_snapshot(cache_key, response)
            with _permission_cache_lock:
                _permission_registry_cache[registry_cache_key] = (
                    monotonic() + PERMISSION_READ_CACHE_TTL_SECONDS,
                    response.model_copy(deep=True),
                )
        return response
    except Exception as exc:
        db.rollback()
        stable_read_failure(
            logger=logger,
            route="/permissions/registry",
            exc=exc,
            request=request,
            code="permission_registry_failed",
        )
        snapshot = get_api_snapshot(cache_key)
        if snapshot is not None:
            return degraded_snapshot(
                snapshot,
                code="permission_registry_failed",
                message="Permission registry is using the last successful snapshot because the live read failed.",
                request=request,
            )
        raise_structured_api_error(
            code="permission_registry_failed",
            message="Permission registry is temporarily unavailable.",
            request=request,
            retryable=True,
        )


@router.get(
    "/users/{user_id}/assignments",
    response_model=PermissionAssignmentListResponse,
)
def user_permission_assignments(
    user_id: int,
    guard: None = Depends(guarded_heavy_api_request("permissions.assignments")),
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> PermissionAssignmentListResponse:
    del guard, owner
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
