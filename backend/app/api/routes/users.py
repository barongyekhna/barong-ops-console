import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ...core.roles import list_standard_role_metadata, normalize_role
from ...core.roles import is_owner_role
from ...db.session import get_db
from ...models.user import User
from ...schemas.common import ListResponse
from ...schemas.user import (
    PasswordResetRequest,
    UserCreate,
    UserResponse,
    UserRolesResponse,
    UserUpdate,
    is_user_manager_role,
    user_management_role_metadata,
)
from ...services.user_management_service import (
    DuplicateUsernameError,
    ManagedUserNotFoundError,
    OwnerRoleNotAllowedError,
    SelfDisableNotAllowedError,
    SelfPasswordResetNotAllowedError,
    UserManagementPermissionDeniedError,
    UserOrganizationNotFoundError,
    create_managed_user,
    disable_managed_user,
    enable_managed_user,
    get_managed_user,
    list_users,
    reset_managed_user_password,
    update_managed_user,
)
from ...services.api_stability import (
    api_snapshot_key,
    degraded_snapshot,
    get_api_snapshot,
    raise_structured_api_error,
    save_api_snapshot,
    stable_read_failure,
)
from ..deps import get_audit_context, get_current_user

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)


def _actor_org_id(actor: User) -> str | None:
    organization_id = actor.organization_id
    if organization_id is None:
        return None
    organization_id = organization_id.strip()
    return organization_id or None


def _scoped_organization_id(
    actor: User,
    requested_org_id: str | None,
) -> str | None:
    if is_owner_role(actor.role):
        return requested_org_id
    actor_org_id = _actor_org_id(actor)
    if actor_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context is required.",
        )
    if requested_org_id is not None and requested_org_id != actor_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users outside the current organization are not visible.",
        )
    return actor_org_id


def _ensure_user_visible(actor: User, target: User) -> None:
    if is_owner_role(actor.role):
        return
    actor_org_id = _actor_org_id(actor)
    if actor_org_id is None or target.organization_id != actor_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users outside the current organization are not visible.",
        )


def _raise_user_management_error(exc: Exception) -> None:
    if isinstance(exc, ManagedUserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    if isinstance(exc, DuplicateUsernameError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if isinstance(exc, OwnerRoleNotAllowedError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    if isinstance(exc, UserOrganizationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    if isinstance(exc, UserManagementPermissionDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from None
    if isinstance(
        exc,
        (SelfDisableNotAllowedError, SelfPasswordResetNotAllowedError),
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    raise exc


def require_user_manager(user: User = Depends(get_current_user)) -> User:
    if not is_user_manager_role(user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or super admin role required.",
        )
    return user


@router.get("", response_model=ListResponse[UserResponse])
def users(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Query(default=None, max_length=40),
    role: str | None = Query(default=None, max_length=40),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ListResponse[UserResponse]:
    requested_org = organization_id.strip() if organization_id else None
    requested_org = requested_org or None
    requested_role = normalize_role(role) if role and role.strip() else None
    effective_org = _scoped_organization_id(actor, requested_org or None)

    cache_key = api_snapshot_key(
        "users.list",
        actor.id,
        actor.role,
        effective_org,
        requested_role,
        limit,
        offset,
    )

    try:
        result = list_users(
            db,
            limit=limit,
            offset=offset,
            organization_id=effective_org,
            role=requested_role,
        )
        response = ListResponse(
            items=[UserResponse.model_validate(item) for item in result.items],
            count=result.count,
            limit=limit,
            offset=offset,
        )
        save_api_snapshot(cache_key, response)
        return response
    except Exception as exc:
        db.rollback()
        stable_read_failure(
            logger=logger,
            route="/users",
            exc=exc,
            request=request,
            code="users_list_failed",
        )
        snapshot = get_api_snapshot(cache_key)
        if snapshot is not None:
            return degraded_snapshot(
                snapshot,
                code="users_list_failed",
                message="User list is using the last successful snapshot because the live read failed.",
                request=request,
            )
        raise_structured_api_error(
            code="users_list_failed",
            message="User list is temporarily unavailable.",
            request=request,
            retryable=True,
        )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def user_create(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = create_managed_user(
            db,
            payload=payload,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return UserResponse.model_validate(user)


@router.get("/roles", response_model=UserRolesResponse)
def user_roles(
    actor: User = Depends(get_current_user),
) -> UserRolesResponse:
    if not is_user_manager_role(actor.role):
        return UserRolesResponse(
            assignable_roles=[],
            standard_roles=list_standard_role_metadata(),
        )
    role_metadata = user_management_role_metadata()
    return UserRolesResponse(
        assignable_roles=role_metadata,
        standard_roles=list_standard_role_metadata(),
    )


@router.get("/{user_id}", response_model=UserResponse)
def user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> UserResponse:
    try:
        user = get_managed_user(db, user_id)
    except Exception as exc:
        _raise_user_management_error(exc)
    _ensure_user_visible(actor, user)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
def user_update(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = update_managed_user(
            db,
            user_id=user_id,
            payload=payload,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return UserResponse.model_validate(user)


@router.post("/{user_id}/reset-password", response_model=UserResponse)
def user_reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = reset_managed_user_password(
            db,
            user_id=user_id,
            new_password=payload.new_password.get_secret_value(),
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return UserResponse.model_validate(user)


@router.post("/{user_id}/disable", response_model=UserResponse)
def user_disable(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = disable_managed_user(
            db,
            user_id=user_id,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return UserResponse.model_validate(user)


@router.post("/{user_id}/enable", response_model=UserResponse)
def user_enable(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    try:
        user = enable_managed_user(
            db,
            user_id=user_id,
            actor=owner,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_user_management_error(exc)
    return UserResponse.model_validate(user)
