from __future__ import annotations

import json
import re
from uuid import uuid4

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import inspect

from ..core.api_classification import is_lightweight_control_plane_path
from ..core.auth_paths import is_auth_me_path
from ..core.config import get_settings
from ..core.security_headers import apply_security_headers
from ..core.session_cookies import get_session_id_from_request
from ..db.compatibility import table_exists
from ..db.session import managed_read_session
from ..middleware.org_context import get_org_context
from ..schemas.organization import ORG_ID_PATTERN
from ..services.auth_service import AuditContext, InvalidSessionError, validate_session
from ..services.data_isolation import (
    OrgDataIsolationError,
    OrgDataIsolationUserContext,
    org_data_isolation_context,
    without_org_data_isolation,
)
from ..services.event_collector import emit_event, set_current_event_context
from ..services.request_session_cache import (
    cache_authenticated_session,
    get_cached_authenticated_session,
)
from ..services.session_seen_buffer import queue_session_seen

settings = get_settings()

API_PATH_PREFIXES = ("/api/app", "/api/control-plane")
TENANT_API_PATH_PREFIXES = ("/api/app",)
ORG_CONTEXT_EXEMPT_PATHS = frozenset(
    (
        "/api/app/org/create",
        "/api/app/module/bind",
        "/api/app/module/shared/create",
        "/api/app/module/shared/update-orgs",
        "/api/app/module/shared/list",
    )
)
ORG_PATH_PATTERN = re.compile(r"/org/(?P<org_id>org_[0-9a-f]{32})(?:/|$)")
MUTATING_METHODS = frozenset(("POST", "PUT", "PATCH", "DELETE"))
C18D_TARGET_ORG_PAYLOAD_PATHS = frozenset(("/api/app/module/bind",))
DATA_ISOLATION_EXEMPT_PATHS = frozenset(
    (
        "/api/app/permissions/me",
    )
)


def _security_response(status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    apply_security_headers(response, settings=settings)
    return response


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


def _valid_org_id(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if ORG_ID_PATTERN.fullmatch(candidate) or candidate.startswith("org_"):
        return candidate
    return None


def _org_id_from_c18f_state(request: Request) -> str | None:
    decision = getattr(request.state, "c18f_permission_decision", None)
    if not isinstance(decision, dict) or decision.get("allowed") is not True:
        return None
    return _valid_org_id(str(decision.get("org_id") or ""))


def _org_id_from_path(request: Request) -> str | None:
    match = ORG_PATH_PATTERN.search(request.url.path)
    if match is None:
        return None
    return match.group("org_id")


def _org_id_from_org_context(request: Request) -> str | None:
    context = get_org_context(request)
    if context is None:
        return None
    return _valid_org_id(context.org_id)


def _role_from_org_context(request: Request) -> str | None:
    context = get_org_context(request)
    if context is None:
        return None
    return context.role


def _target_org_payload_allowed(request: Request) -> bool:
    return request.url.path in C18D_TARGET_ORG_PAYLOAD_PATHS


def _resolve_org_id(request: Request) -> tuple[str | None, str]:
    c18f_org_id = _org_id_from_c18f_state(request)
    if c18f_org_id is not None:
        return c18f_org_id, "c18f_permission_decision"

    context_org_id = _org_id_from_org_context(request)
    if context_org_id is not None:
        return context_org_id, "c18h_org_context"

    path_org_id = _org_id_from_path(request)
    if path_org_id is not None:
        return path_org_id, "c18c_path_context"

    return None, "missing"


def _payload_contains_org_id(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key == "org_id" or _payload_contains_org_id(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_payload_contains_org_id(item) for item in value)
    return False


async def _request_body_contains_org_id(request: Request) -> bool:
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return False
    body = await request.body()
    if not body:
        return False
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    return _payload_contains_org_id(payload)


def _is_api_path(request: Request) -> bool:
    return request.url.path.startswith(API_PATH_PREFIXES)


def _requires_org_context(request: Request) -> bool:
    path = request.url.path
    return (
        path.startswith(TENANT_API_PATH_PREFIXES)
        and path not in ORG_CONTEXT_EXEMPT_PATHS
    )


def _c05b_schema_without_c18_data_isolation() -> bool:
    with managed_read_session() as db:
        if not table_exists(db, "org_memberships"):
            return True
        if table_exists(db, "operation_logs"):
            operation_log_columns = {
                column["name"]
                for column in inspect(db.get_bind()).get_columns("operation_logs")
            }
            if "org_id" not in operation_log_columns:
                return True
    return False


async def enforce_org_data_isolation(request: Request, call_next):
    if is_auth_me_path(request.url.path):
        return await call_next(request)

    if (
        request.url.path in DATA_ISOLATION_EXEMPT_PATHS
        or is_lightweight_control_plane_path(request.url.path)
    ):
        return await call_next(request)

    if not _is_api_path(request):
        return await call_next(request)

    if _c05b_schema_without_c18_data_isolation():
        org_context = get_org_context(request)
        if org_context is None:
            return await call_next(request)
        context = OrgDataIsolationUserContext(
            org_id=org_context.org_id,
            user_id=org_context.user_id,
            role=org_context.role,
            source="c05b_schema_compat_org_context",
            strict=False,
        )
        with org_data_isolation_context(context):
            return await call_next(request)

    org_id, source = _resolve_org_id(request)
    if org_id is None:
        if _requires_org_context(request):
            return _security_response(
                status.HTTP_403_FORBIDDEN,
                "C18H org context is required.",
            )
        return await call_next(request)

    if (
        request.method.upper() in MUTATING_METHODS
        and not _target_org_payload_allowed(request)
        and await _request_body_contains_org_id(request)
    ):
        emit_event(
            event_type="org_data_isolation.api_rejected",
            module="system",
            action="c18g.api_context",
            source="backend",
            status="failed",
            context_id=_request_id(request),
            payload={
                "org_id": org_id,
                "reason": "frontend_payload_org_id_not_allowed",
            },
        )
        return _security_response(
            status.HTTP_400_BAD_REQUEST,
            "org_id must come from the authenticated server context.",
        )

    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        return _security_response(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")

    audit = _audit_context(request)
    current_session = get_cached_authenticated_session(
        request,
        session_id=session_id,
    )
    if current_session is None:
        with without_org_data_isolation():
            with managed_read_session() as db:
                try:
                    current_session = validate_session(
                        db,
                        session_id=session_id,
                        audit=audit,
                    )
                except InvalidSessionError:
                    return _security_response(
                        status.HTTP_401_UNAUTHORIZED,
                        "Not authenticated.",
                    )
        cache_authenticated_session(
            request,
            session_id=session_id,
            current_session=current_session,
        )

    queue_session_seen(current_session.auth_session.session_id_hash)
    request.state.user_id = str(current_session.user.id)
    set_current_event_context(user_id=str(current_session.user.id))
    context = OrgDataIsolationUserContext(
        org_id=org_id,
        user_id=str(current_session.user.id),
        role=_role_from_org_context(request) or current_session.user.role,
        source=source,
        strict=True,
    )

    try:
        with org_data_isolation_context(context):
            response = await call_next(request)
    except OrgDataIsolationError as exc:
        emit_event(
            event_type="org_data_isolation.api_rejected",
            module="system",
            action="c18g.api_context",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            user_id=str(current_session.user.id),
            payload={
                "org_id": org_id,
                "reason": exc.__class__.__name__,
            },
        )
        return _security_response(status.HTTP_403_FORBIDDEN, str(exc))

    emit_event(
        event_type="org_data_isolation.api_context",
        module="system",
        action="c18g.api_context",
        source="backend",
        status="success" if response.status_code < 400 else "failed",
        context_id=audit.request_id,
        user_id=str(current_session.user.id),
        payload={
            "org_id": org_id,
            "context_source": source,
            "role": context.role,
            "status_code": response.status_code,
        },
    )
    return response
