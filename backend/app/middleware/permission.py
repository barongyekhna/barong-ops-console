from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..core.auth_paths import is_auth_me_path
from ..core.config import get_settings
from ..core.security_headers import apply_security_headers
from ..core.session_cookies import get_session_id_from_request
from ..db.compatibility import table_exists
from ..db.session import managed_read_session
from ..middleware.org_context import get_org_context
from ..schemas.permission import PermissionAction
from ..services.auth_service import AuditContext, InvalidSessionError, validate_session
from ..services.event_collector import emit_event, set_current_event_context
from ..services.permission_isolation import check_permission
from ..services.request_session_cache import cache_authenticated_session
from ..services.session_seen_buffer import queue_session_seen

settings = get_settings()

API_PATH_PREFIXES = ("/api/app", "/api/control-plane")
ORG_PATH_PATTERN = re.compile(r"/org/(?P<org_id>[^/?#]+)(?:/|$)")
MODULE_PATH_PATTERNS = (
    re.compile(r"/module/(?P<module_id>[^/?#]+)(?:/|$)"),
    re.compile(r"/modules/(?P<module_id>[^/?#]+)(?:/|$)"),
)

METHOD_ACTIONS = {
    "GET": PermissionAction.READ,
    "HEAD": PermissionAction.READ,
    "OPTIONS": PermissionAction.READ,
    "POST": PermissionAction.WRITE,
    "PUT": PermissionAction.WRITE,
    "PATCH": PermissionAction.WRITE,
    "DELETE": PermissionAction.DELETE,
}

C15_PATH_MARKERS = (
    "/workflow-registry/decision",
    "/webhook-gateway",
    "/callback-handler",
    "/payload-standardization/normalize",
    "/module-workflow-bindings/decision",
)
C14_PATH_MARKERS = (
    "/execution-prompts/payload",
    "/ai-execution-bindings",
)


@dataclass(frozen=True)
class PermissionRequestContext:
    org_id: str
    module_id: str
    action: PermissionAction
    source: str


def _request_id(request: Request) -> str:
    existing = getattr(request.state, "context_id", None)
    if existing is not None:
        return str(existing)
    header = request.headers.get("x-request-id")
    if header is not None and 0 < len(header) <= 128:
        request.state.context_id = header
        return header
    generated = str(uuid4())
    request.state.context_id = generated
    return generated


def _audit_context(request: Request) -> AuditContext:
    context_id = _request_id(request)
    set_current_event_context(context_id=context_id)
    return AuditContext(
        request_id=context_id,
        ip_address=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("user-agent"),
    )


def _security_response(status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    apply_security_headers(response, settings=settings)
    return response


def _first_context_value(request: Request, *keys: str) -> str | None:
    for key in keys:
        value = request.query_params.get(key)
        if value is not None and value.strip():
            return value.strip()
    for key in keys:
        value = request.headers.get(f"x-{key.replace('_', '-')}")
        if value is not None and value.strip():
            return value.strip()
    return None


def _org_id_from_path(path: str) -> str | None:
    match = ORG_PATH_PATTERN.search(path)
    if match is None:
        return None
    return match.group("org_id")


def _module_id_from_path(path: str) -> str | None:
    for pattern in MODULE_PATH_PATTERNS:
        match = pattern.search(path)
        if match is not None:
            return match.group("module_id")
    return None


def _path_has_marker(path: str, markers: tuple[str, ...]) -> bool:
    return any(marker in path for marker in markers)


def _action_for_request(request: Request) -> PermissionAction:
    path = request.url.path
    if "/operation-logs" in path:
        return PermissionAction.READ
    if _path_has_marker(path, C15_PATH_MARKERS):
        return PermissionAction.EXECUTE
    if _path_has_marker(path, C14_PATH_MARKERS):
        return PermissionAction.EXECUTE
    if path.endswith("/module/bind"):
        return PermissionAction.ADMIN
    return METHOD_ACTIONS.get(request.method.upper(), PermissionAction.READ)


def _module_id_for_request(request: Request) -> tuple[str | None, str]:
    path = request.url.path
    module_id = _first_context_value(
        request,
        "module_id",
        "module",
        "module_key",
    )
    if module_id is not None:
        return module_id, "query_or_header"

    if path.endswith("/module/bind"):
        return None, "missing"

    module_id = _module_id_from_path(path)
    if module_id is not None:
        return module_id, "path"

    if "/operation-logs" in path:
        return "C17", "c17_logs_access"
    if _path_has_marker(path, C15_PATH_MARKERS):
        return "C15", "c15_workflow_execution"
    if _path_has_marker(path, C14_PATH_MARKERS):
        return "C14", "c14_ai_execution"
    return None, "missing"


def resolve_permission_request_context(
    request: Request,
) -> PermissionRequestContext | None:
    path = request.url.path
    if not path.startswith(API_PATH_PREFIXES):
        return None

    org_context = get_org_context(request)
    org_id = org_context.org_id if org_context is not None else None
    if org_id is None:
        org_id = _org_id_from_path(path)
    if org_id is None:
        return None

    module_id, source = _module_id_for_request(request)
    if module_id is None:
        return None

    return PermissionRequestContext(
        org_id=org_id,
        module_id=module_id,
        action=_action_for_request(request),
        source=source,
    )


def _c18_permission_tables_available(db: Session) -> bool:
    return table_exists(db, "org_memberships") and table_exists(
        db,
        "module_bindings",
    )


async def enforce_permission_isolation(request: Request, call_next):
    if is_auth_me_path(request.url.path):
        return await call_next(request)

    context = resolve_permission_request_context(request)
    if context is None:
        return await call_next(request)

    request.state.org_id = context.org_id
    request.state.module_id = context.module_id
    request.state.permission_action = context.action
    audit = _audit_context(request)
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        emit_event(
            event_type="permission_isolation.check",
            module="system",
            action="c18f.permission_check",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            payload={
                "org_id": context.org_id,
                "module_id": context.module_id,
                "permission_action": context.action,
                "reason": "missing_session",
            },
        )
        return _security_response(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated.",
        )

    skipped_c05b_compat = False
    with managed_read_session() as db:
        try:
            current_session = validate_session(
                db,
                session_id=session_id,
                audit=audit,
            )
        except InvalidSessionError:
            emit_event(
                event_type="permission_isolation.check",
                module="system",
                action="c18f.permission_check",
                source="backend",
                status="failed",
                context_id=audit.request_id,
                payload={
                    "org_id": context.org_id,
                    "module_id": context.module_id,
                    "permission_action": context.action,
                    "reason": "invalid_session",
                },
            )
            return _security_response(
                status.HTTP_401_UNAUTHORIZED,
                "Not authenticated.",
            )

        queue_session_seen(current_session.auth_session.session_id_hash)
        cache_authenticated_session(
            request,
            session_id=session_id,
            current_session=current_session,
        )
        request.state.user_id = str(current_session.user.id)
        set_current_event_context(user_id=str(current_session.user.id))
        if not _c18_permission_tables_available(db):
            skipped_c05b_compat = True
            decision = None
            request.state.c18f_permission_decision = {
                "allowed": True,
                "denied": False,
                "denial_code": None,
                "reason": "C18 permission tables unavailable on c05b baseline.",
            }
        else:
            decision = check_permission(
                db,
                current_session.user.id,
                context.org_id,
                context.module_id,
                context.action,
                request=request,
            )
            request.state.c18f_permission_decision = decision.model_dump(mode="json")

    if skipped_c05b_compat:
        emit_event(
            event_type="permission_isolation.check",
            module="system",
            action="c18f.permission_check",
            source="backend",
            status="success",
            context_id=audit.request_id,
            user_id=getattr(request.state, "user_id", None),
            payload={
                "org_id": context.org_id,
                "module_id": context.module_id,
                "permission_action": context.action,
                "context_source": "c05b_compat_no_c18_tables",
                "allowed": True,
                "denial_code": None,
                "owner_override": False,
                "permission_equals_visibility": False,
                "permission_equals_data_access": False,
            },
        )
        return await call_next(request)

    emit_event(
        event_type="permission_isolation.check",
        module="system",
        action="c18f.permission_check",
        source="backend",
        status="success" if decision.allowed else "failed",
        context_id=audit.request_id,
        user_id=getattr(request.state, "user_id", None),
        payload={
            "org_id": context.org_id,
            "module_id": context.module_id,
            "permission_action": context.action,
            "context_source": context.source,
            "allowed": decision.allowed,
            "denial_code": decision.denial_code,
            "owner_override": decision.owner_override_applied,
            "permission_equals_visibility": False,
            "permission_equals_data_access": False,
        },
    )
    if decision.denied:
        return _security_response(
            status.HTTP_403_FORBIDDEN,
            "C18F permission denied.",
        )

    return await call_next(request)
