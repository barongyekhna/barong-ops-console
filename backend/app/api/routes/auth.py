from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.security import SecurityConfigurationError
from ...db.session import get_db
from ...models.user import User
from ...schemas.auth import (
    AuthenticatedUser,
    AuthenticatedUserWithPermissions,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)
from ...schemas.permission import CurrentUserPermissionsRead
from ...services.auth_service import (
    InvalidCredentialsError,
    login as login_user,
    logout as logout_user,
)
from ...services.permission_service import resolve_current_user_permission_info
from ..deps import get_audit_context, require_rbac

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    audit = get_audit_context(request)
    try:
        result = login_user(
            db,
            username=payload.username,
            password=payload.password.get_secret_value(),
            settings=settings,
            audit=audit,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except SecurityConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable.",
        ) from None

    return LoginResponse(
        access_token=result.access_token,
        token_type="bearer",
        user=AuthenticatedUser.model_validate(result.user),
    )


@router.get("/me", response_model=AuthenticatedUserWithPermissions)
def me(
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUTH", "read")),
) -> AuthenticatedUserWithPermissions:
    permissions = CurrentUserPermissionsRead.model_validate(
        resolve_current_user_permission_info(db, user)
    )
    return AuthenticatedUserWithPermissions(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        permissions=permissions,
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUTH", "read")),
) -> LogoutResponse:
    logout_user(db, user=user, audit=get_audit_context(request))
    return LogoutResponse(message="Logged out.")
