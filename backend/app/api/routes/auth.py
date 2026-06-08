from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.security import SecurityConfigurationError
from ...db.session import get_db
from ...models.user import User
from ...schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)
from ...services.auth_service import (
    InvalidCredentialsError,
    login as login_user,
    logout as logout_user,
)
from ..deps import get_audit_context, get_current_user

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


@router.get("/me", response_model=AuthenticatedUser)
def me(user: User = Depends(get_current_user)) -> AuthenticatedUser:
    return AuthenticatedUser.model_validate(user)


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LogoutResponse:
    logout_user(db, user=user, audit=get_audit_context(request))
    return LogoutResponse(message="Logged out.")
