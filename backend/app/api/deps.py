from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.permissions import SCOPE_GLOBAL
from ..core.rbac import check_internal_permission, check_permission
from ..core.roles import is_owner_role
from ..db.session import get_db
from ..models.user import User
from ..schemas.common import contains_runtime_address_data
from ..services.auth_service import (
    AuditContext,
    AuthenticatedSession,
    InvalidSessionError,
    validate_session,
)
from ..services.permission_service import user_has_permission

SENSITIVE_HEADER_MARKERS = (
    "bearer",
    "token",
    "secret",
    "password",
    "authorization",
    "api-key",
)


def _safe_header(value: str | None, max_length: int) -> str | None:
    if value is None or len(value) > max_length:
        return None
    lowered = value.lower()
    if any(marker in lowered for marker in SENSITIVE_HEADER_MARKERS):
        return None
    if contains_runtime_address_data(value):
        return None
    return value


def get_audit_context(request: Request) -> AuditContext:
    request_id = _safe_header(request.headers.get("x-request-id"), 128)
    if request_id is None:
        request_id = str(uuid4())

    ip_address = request.client.host if request.client is not None else None
    if ip_address is not None:
        ip_address = ip_address[:45]

    return AuditContext(
        request_id=request_id,
        ip_address=ip_address,
        user_agent=_safe_header(request.headers.get("user-agent"), 1000),
    )


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
    )


def get_current_session(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedSession:
    session_id = request.cookies.get(settings.auth_session_cookie_name)
    if session_id is None:
        raise unauthorized()

    try:
        return validate_session(
            db,
            session_id=session_id,
            audit=get_audit_context(request),
        )
    except InvalidSessionError:
        raise unauthorized() from None


def get_current_user(
    current_session: AuthenticatedSession = Depends(get_current_session),
) -> User:
    return current_session.user


def require_owner(
    user: User = Depends(get_current_user),
) -> User:
    if not check_permission(user, "ADMIN", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="RBAC permission denied.",
        )
    if not is_owner_role(user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required.",
        )
    return user


def require_permission(
    permission_key: str,
    scope_type: str = SCOPE_GLOBAL,
    scope_key: str = "*",
):
    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if is_owner_role(user.role):
            return user

        try:
            has_permission = user_has_permission(
                db,
                user,
                permission_key,
                scope_type=scope_type,
                scope_key=scope_key,
            )
        except ValueError:
            has_permission = False

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission_key}",
            )
        return user

    return dependency


def require_rbac(module: str, action: str):
    def dependency(
        user: User = Depends(get_current_user),
    ) -> User:
        if not check_permission(user, module, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="RBAC permission denied.",
            )
        return user

    return dependency


def require_internal_rbac(module: str, action: str = "internal") -> None:
    if not check_internal_permission(module, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="RBAC internal permission denied.",
        )
