from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ...core.roles import list_standard_role_metadata
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
    UserOrganizationNotFoundError,
    create_managed_user,
    disable_managed_user,
    enable_managed_user,
    get_managed_user,
    list_users,
    reset_managed_user_password,
    update_managed_user,
)
from ..deps import get_audit_context, get_current_user

router = APIRouter(prefix="/users", tags=["users"])


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
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> ListResponse[UserResponse]:
    del owner
    result = list_users(db, limit=limit, offset=offset)
    return ListResponse(
        items=result.items,
        count=result.count,
        limit=limit,
        offset=offset,
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
    owner: User = Depends(require_user_manager),
) -> UserRolesResponse:
    del owner
    role_metadata = user_management_role_metadata()
    return UserRolesResponse(
        assignable_roles=role_metadata,
        standard_roles=list_standard_role_metadata(),
    )


@router.get("/{user_id}", response_model=UserResponse)
def user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(require_user_manager),
) -> UserResponse:
    del owner
    try:
        user = get_managed_user(db, user_id)
    except Exception as exc:
        _raise_user_management_error(exc)
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
