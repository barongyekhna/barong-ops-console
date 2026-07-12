from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.permissions import SCOPE_GLOBAL, SCOPE_ORGANIZATION
from ..core.roles import is_owner_role, is_super_admin_role
from ..core.session_cookies import get_session_id_from_request
from ..db.session import get_db
from ..models.user import User
from ..schemas.common import contains_runtime_address_data
from ..services.event_collector import emit_event, set_current_event_context
from ..services.auth_service import (
    AuditContext,
    AuthenticatedSession,
    InvalidSessionError,
    authenticated_session_from_identity,
    validate_session,
    validate_session_identity_fast,
)
from ..services.session_seen_buffer import queue_session_seen
from ..services.permission_decision_engine import PermissionDecisionEngine
from ..services.request_session_cache import (
    cache_authenticated_session,
    get_cached_authenticated_session,
)
from ..services.unified_permission_engine import (
    UnifiedPermissionRequest,
    check_internal_permission,
)

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
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        audit = get_audit_context(request)
        emit_event(
            event_type="auth.session.validate",
            module="system",
            action="auth.session.validate",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            payload={"outcome": "missing_session"},
        )
        raise unauthorized()

    cached_session = get_cached_authenticated_session(
        request,
        session_id=session_id,
    )
    if cached_session is not None:
        request.state.user_id = str(cached_session.user.id)
        set_current_event_context(user_id=str(cached_session.user.id))
        emit_event(
            event_type="auth.session.validate",
            module="system",
            action="auth.session.validate",
            source="backend",
            status="success",
            context_id=get_audit_context(request).request_id,
            user_id=str(cached_session.user.id),
            payload={
                "outcome": "request_cache_hit",
                "role": cached_session.user.role,
            },
        )
        return cached_session

    audit = get_audit_context(request)
    try:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            identity = validate_session_identity_fast(db, session_id=session_id)
            current_session = authenticated_session_from_identity(
                identity,
                audit=audit,
            )
        else:
            current_session = validate_session(
                db,
                session_id=session_id,
                audit=audit,
            )
    except InvalidSessionError:
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
    queue_session_seen(current_session.auth_session.session_id_hash)
    cache_authenticated_session(
        request,
        session_id=session_id,
        current_session=current_session,
    )
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
    db: Session = Depends(get_db),
) -> User:
    decision = PermissionDecisionEngine(db, request=request).decide_platform_metadata(
        UnifiedPermissionRequest(
            user_id=user.id,
            org_id=getattr(request.state, "org_id", None),
            module_id="ADMIN",
            action="admin",
            role=user.role,
            scope_type=SCOPE_GLOBAL,
            scope_key="*",
            source="api_require_owner",
        )
    )
    emit_event(
        event_type="rbac.check",
        module="system",
        action="rbac.ADMIN.admin",
        source="backend",
        status="success" if decision.allowed else "failed",
        context_id=get_audit_context(request).request_id,
        user_id=str(user.id),
        payload={
            "module": "ADMIN",
            "action": "admin",
            "role": user.role,
            "decision_source": "PermissionDecisionEngine",
            "denial_code": decision.denial_code,
        },
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied.",
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


def require_permission_manager(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Owner or super admin may reach permission-assignment endpoints.

    Owner assigns globally; super admin is restricted to their own organization's
    members by the permission service (org-scope enforced there, not here).
    """
    decision = PermissionDecisionEngine(db, request=request).decide_platform_metadata(
        UnifiedPermissionRequest(
            user_id=user.id,
            org_id=getattr(request.state, "org_id", None),
            module_id="ADMIN",
            action="admin",
            role=user.role,
            scope_type=SCOPE_GLOBAL,
            scope_key="*",
            source="api_require_permission_manager",
        )
    )
    allowed = decision.allowed and (
        is_owner_role(user.role) or is_super_admin_role(user.role)
    )
    emit_event(
        event_type="rbac.permission_manager_check",
        module="system",
        action="rbac.permission_manager",
        source="backend",
        status="success" if allowed else "failed",
        context_id=get_audit_context(request).request_id,
        user_id=str(user.id),
        payload={
            "role": user.role,
            "decision_source": "PermissionDecisionEngine",
            "denial_code": decision.denial_code,
        },
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or super admin role required.",
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
        module_id, _, action = permission_key.partition(".")
        decision = PermissionDecisionEngine(db, request=request).decide_permission_key(
            UnifiedPermissionRequest(
                user_id=user.id,
                org_id=scope_key if scope_type == SCOPE_ORGANIZATION else None,
                module_id=module_id or "permissions",
                action=action or "read",
                role=user.role,
                scope_type=scope_type,
                scope_key=scope_key,
                permission_key=permission_key,
                source="api_require_permission",
            )
        )
        has_permission = decision.allowed

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
                "decision_source": "PermissionDecisionEngine",
                "denial_code": decision.denial_code,
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
        db: Session = Depends(get_db),
    ) -> User:
        decision = PermissionDecisionEngine(db, request=request).decide_platform_metadata(
            UnifiedPermissionRequest(
                user_id=user.id,
                org_id=getattr(request.state, "org_id", None),
                module_id=module,
                action=action,
                role=user.role,
                scope_type=SCOPE_GLOBAL,
                scope_key="*",
                source="api_require_rbac",
            )
        )
        emit_event(
            event_type="rbac.check",
            module="system",
            action=f"rbac.{module}.{action}",
            source="backend",
            status="success" if decision.allowed else "failed",
            context_id=get_audit_context(request).request_id,
            user_id=str(user.id),
            payload={
                "module": module,
                "action": action,
                "role": user.role,
                "decision_source": "PermissionDecisionEngine",
                "denial_code": decision.denial_code,
            },
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied.",
            )
        return user

    return dependency


def require_cached_control_plane_admin(
    request: Request,
    user: User = Depends(get_current_user),
) -> User:
    decision = getattr(request.state, "control_plane_rbac_decision", None)
    if (
        decision is not None
        and getattr(decision, "allowed", False)
        and getattr(decision, "module_id", None) == "C16"
        and getattr(decision, "action", None) == "admin"
    ):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied.",
    )


def require_lightweight_control_plane_admin(request: Request) -> User:
    current_session = getattr(request.state, "authenticated_session", None)
    user = getattr(current_session, "user", None)
    decision = getattr(request.state, "control_plane_rbac_decision", None)
    if (
        isinstance(current_session, AuthenticatedSession)
        and isinstance(user, User)
        and decision is not None
        and getattr(decision, "allowed", False)
        and getattr(decision, "module_id", None) == "C16"
        and getattr(decision, "action", None) == "admin"
    ):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied.",
    )


def require_internal_rbac(module: str, action: str = "internal") -> None:
    decision = check_internal_permission(module, action)
    emit_event(
        event_type="rbac.internal_check",
        module="system",
        action=f"rbac.{module}.{action}",
        source="backend",
        status="success" if decision.allowed else "failed",
        payload={
            "module": module,
            "action": action,
            "principal": "system",
            "decision_source": "UnifiedPermissionEngine",
            "denial_code": decision.denial_code,
        },
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal permission denied.",
        )
