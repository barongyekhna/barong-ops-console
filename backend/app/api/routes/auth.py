from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.rbac import check_permission
from ...core.session_cookies import clear_session_cookie, set_session_cookie
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
    InvalidSessionError,
    LoginRateLimitError,
    login as login_user,
    logout as logout_user,
    validate_session,
)
from ...services.permission_service import resolve_current_user_permission_info
from ..deps import get_audit_context, require_rbac

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
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
        ) from None
    except LoginRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from None

    request.state.user_id = str(result.user.id)
    set_session_cookie(
        response,
        session_id=result.session_id,
        settings=settings,
    )
    return LoginResponse(
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
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LogoutResponse:
    session_id = request.cookies.get(settings.auth_session_cookie_name)
    current_session = None
    audit = get_audit_context(request)

    if session_id is not None:
        try:
            current_session = validate_session(
                db,
                session_id=session_id,
                audit=audit,
            )
        except InvalidSessionError:
            current_session = None

    if current_session is not None:
        user = current_session.user
        if not check_permission(user, "AUTH", "read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="RBAC permission denied.",
            )
        logout_user(
            db,
            user=user,
            auth_session=current_session.auth_session,
            audit=audit,
        )

    clear_session_cookie(response, settings=settings)
    return LogoutResponse(message="Logged out.")
