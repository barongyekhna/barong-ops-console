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
from ..services.event_collector import emit_event, set_current_event_context
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
    request_id = getattr(request.state, "context_id", None)
    if request_id is not None:
        request_id = _safe_header(str(request_id), 128)
    if request_id is None:
        request_id = _safe_header(request.headers.get("x-request-id"), 128)
    if request_id is None:
        request_id = str(uuid4())
    request.state.context_id = request_id
    set_current_event_context(context_id=request_id)

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
        audit = get_audit_context(request)
        emit_event(
            event_type="auth.session.validate",
            module="system",
            action="auth.session.validate",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            payload={"outcome": "missing_session_cookie"},
        )
        raise unauthorized()

    try:
        current_session = validate_session(
            db,
            session_id=session_id,
            audit=get_audit_context(request),
        )
    except InvalidSessionError:
        audit = get_audit_context(request)
        emit_event(
            event_type="auth.session.validate",
            module="system",
            action="auth.session.validate",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            payload={"outcome": "invalid_session"},
        )
        raise unauthorized() from None
    request.state.user_id = str(current_session.user.id)
    set_current_event_context(user_id=str(current_session.user.id))
    emit_event(
        event_type="auth.session.validate",
        module="system",
        action="auth.session.validate",
        source="backend",
        status="success",
        context_id=get_audit_context(request).request_id,
        user_id=str(current_session.user.id),
        payload={"outcome": "session_valid", "role": current_session.user.role},
    )
    return current_session


def get_current_user(
    current_session: AuthenticatedSession = Depends(get_current_session),
) -> User:
    return current_session.user


def require_owner(
    request: Request,
    user: User = Depends(get_current_user),
) -> User:
    allowed = check_permission(user, "ADMIN", "admin")
    emit_event(
        event_type="rbac.check",
        module="system",
        action="rbac.ADMIN.admin",
        source="backend",
        status="success" if allowed else "failed",
        context_id=get_audit_context(request).request_id,
        user_id=str(user.id),
        payload={"module": "ADMIN", "action": "admin", "role": user.role},
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="RBAC permission denied.",
        )
    if not is_owner_role(user.role):
        emit_event(
            event_type="rbac.owner_check",
            module="system",
            action="rbac.owner",
            source="backend",
            status="failed",
            context_id=get_audit_context(request).request_id,
            user_id=str(user.id),
            payload={"role": user.role},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required.",
        )
    emit_event(
        event_type="rbac.owner_check",
        module="system",
        action="rbac.owner",
        source="backend",
        status="success",
        context_id=get_audit_context(request).request_id,
        user_id=str(user.id),
        payload={"role": user.role},
    )
    return user


def require_permission(
    permission_key: str,
    scope_type: str = SCOPE_GLOBAL,
    scope_key: str = "*",
):
    def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
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

        emit_event(
            event_type="rbac.permission_check",
            module="system",
            action=f"permission.{permission_key}",
            source="backend",
            status="success" if has_permission else "failed",
            context_id=get_audit_context(request).request_id,
            user_id=str(user.id),
            payload={
                "permission_key": permission_key,
                "scope_type": scope_type,
                "scope_key": scope_key,
                "role": user.role,
            },
        )
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission_key}",
            )
        return user

    return dependency


def require_rbac(module: str, action: str):
    def dependency(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        allowed = check_permission(user, module, action)
        emit_event(
            event_type="rbac.check",
            module="system",
            action=f"rbac.{module}.{action}",
            source="backend",
            status="success" if allowed else "failed",
            context_id=get_audit_context(request).request_id,
            user_id=str(user.id),
            payload={"module": module, "action": action, "role": user.role},
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="RBAC permission denied.",
            )
        return user

    return dependency


def require_internal_rbac(module: str, action: str = "internal") -> None:
    allowed = check_internal_permission(module, action)
    emit_event(
        event_type="rbac.internal_check",
        module="system",
        action=f"rbac.{module}.{action}",
        source="backend",
        status="success" if allowed else "failed",
        payload={"module": module, "action": action, "principal": "system"},
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="RBAC internal permission denied.",
        )
