from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.security_headers import apply_security_headers
from ..db.session import SessionLocal
from ..models.auth_session import AuthSession
from ..models.org_membership import OrgMembershipRecord
from ..models.organization import OrganizationRecord
from ..models.user import User
from ..schemas.module_binding import GLOBAL_MODULE_BOUND_ORG
from ..services.auth_service import AuditContext, InvalidSessionError, validate_session
from ..services.event_collector import emit_event, set_current_event_context
from ..services.module_binding_service import list_module_bindings

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
FRONTEND_ORG_QUERY_KEYS = ("org_id", "active_org_id")
FRONTEND_ORG_HEADER_KEYS = ("x-org-id", "x-active-org-id")
ORG_CONTEXT_ROLE = Literal["owner", "admin", "member"]


@dataclass(frozen=True)
class OrgContext:
    user_id: str
    org_id: str
    role: ORG_CONTEXT_ROLE
    module_scope: list[str]
    request_id: str


@dataclass(frozen=True)
class OrgResolution:
    org_id: str
    role: ORG_CONTEXT_ROLE
    source: str


def generate_request_id() -> str:
    return str(uuid4())


def get_org_context(request: Request) -> OrgContext | None:
    context = getattr(request.state, "org_context", None)
    if isinstance(context, OrgContext):
        return context
    return None


def get_request_org_id(request: Request) -> str | None:
    context = get_org_context(request)
    if context is None:
        return None
    return context.org_id


def get_request_id(request: Request) -> str | None:
    context = get_org_context(request)
    if context is not None:
        return context.request_id
    value = getattr(request.state, "context_id", None)
    if value is not None:
        return str(value)
    return None


def _is_api_path(request: Request) -> bool:
    return request.url.path.startswith(API_PATH_PREFIXES)


def _requires_org_context(request: Request) -> bool:
    path = request.url.path
    return path.startswith(TENANT_API_PATH_PREFIXES) and path not in ORG_CONTEXT_EXEMPT_PATHS


def _security_response(status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    apply_security_headers(response, settings=settings)
    return response


def _audit_context(request: Request, request_id: str) -> AuditContext:
    set_current_event_context(context_id=request_id)
    return AuditContext(
        request_id=request_id,
        ip_address=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("user-agent"),
    )


def _frontend_org_context_present(request: Request) -> str | None:
    for key in FRONTEND_ORG_QUERY_KEYS:
        if request.query_params.get(key) is not None:
            return f"query:{key}"
    for key in FRONTEND_ORG_HEADER_KEYS:
        if request.headers.get(key) is not None:
            return f"header:{key}"
    return None


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate or None


def _server_state_active_org_id(
    request: Request,
    auth_session: AuthSession,
) -> str | None:
    for state_key in ("active_org_id", "session_org_id", "jwt_org_id"):
        candidate = _string_value(getattr(request.state, state_key, None))
        if candidate is not None:
            return candidate

    candidate = _string_value(getattr(auth_session, "active_org_id", None))
    if candidate is not None:
        return candidate

    claims = getattr(request.state, "jwt_claims", None)
    if isinstance(claims, dict):
        for claim_key in ("active_org_id", "org_id"):
            candidate = _string_value(claims.get(claim_key))
            if candidate is not None:
                return candidate

    session_claims = getattr(request.state, "session_claims", None)
    if isinstance(session_claims, dict):
        for claim_key in ("active_org_id", "org_id"):
            candidate = _string_value(session_claims.get(claim_key))
            if candidate is not None:
                return candidate

    return None


def _active_memberships_for_user(
    db: Session,
    *,
    user_id: str,
) -> list[OrgMembershipRecord]:
    return list(
        db.scalars(
            select(OrgMembershipRecord)
            .where(
                OrgMembershipRecord.user_id == user_id,
                OrgMembershipRecord.status == "active",
            )
            .order_by(OrgMembershipRecord.joined_at, OrgMembershipRecord.org_id)
        )
    )


def _owner_org_for_user(
    db: Session,
    *,
    user_id: str,
) -> OrganizationRecord | None:
    return db.scalar(
        select(OrganizationRecord)
        .where(
            OrganizationRecord.owner_user_id == user_id,
            OrganizationRecord.status == "active",
        )
        .order_by(OrganizationRecord.created_at, OrganizationRecord.org_id)
    )


def _role_for_membership(
    membership: OrgMembershipRecord | None,
) -> ORG_CONTEXT_ROLE:
    if membership is None:
        return "owner"
    if membership.role == "admin":
        return "admin"
    if membership.role == "owner":
        return "owner"
    return "member"


def _resolve_org(
    db: Session,
    *,
    request: Request,
    user: User,
    auth_session: AuthSession,
) -> OrgResolution | None:
    user_id = str(user.id)
    memberships = _active_memberships_for_user(db, user_id=user_id)
    memberships_by_org = {membership.org_id: membership for membership in memberships}

    session_org_id = _server_state_active_org_id(request, auth_session)
    if session_org_id is not None:
        membership = memberships_by_org.get(session_org_id)
        if membership is not None:
            return OrgResolution(
                org_id=session_org_id,
                role=_role_for_membership(membership),
                source="session_or_jwt",
            )
        owner_org = _owner_org_for_user(db, user_id=user_id)
        if (
            owner_org is not None
            and owner_org.org_id == session_org_id
        ):
            return OrgResolution(
                org_id=owner_org.org_id,
                role="owner",
                source="session_or_jwt_owner_org",
            )

    if len(memberships) == 1:
        membership = memberships[0]
        return OrgResolution(
            org_id=membership.org_id,
            role=_role_for_membership(membership),
            source="c18c_active_membership",
        )

    owner_org = _owner_org_for_user(db, user_id=user_id)
    if owner_org is not None:
        return OrgResolution(
            org_id=owner_org.org_id,
            role="owner",
            source="fallback_owner_org",
        )

    return None


def _module_scope_for_org(db: Session, org_id: str) -> list[str]:
    module_ids: list[str] = []
    for binding in list_module_bindings(db):
        if not binding.enabled:
            continue
        if (
            binding.mode == "global"
            or GLOBAL_MODULE_BOUND_ORG in binding.bound_orgs
            or org_id in binding.bound_orgs
        ):
            module_ids.append(binding.module_id)
    return module_ids


def build_org_context(
    db: Session,
    *,
    request: Request,
    user: User,
    auth_session: AuthSession,
    request_id: str,
) -> tuple[OrgContext | None, str]:
    resolution = _resolve_org(
        db,
        request=request,
        user=user,
        auth_session=auth_session,
    )
    if resolution is None:
        return None, "missing_org_context"

    return (
        OrgContext(
            user_id=str(user.id),
            org_id=resolution.org_id,
            role=resolution.role,
            module_scope=_module_scope_for_org(db, resolution.org_id),
            request_id=request_id,
        ),
        resolution.source,
    )


def inject_org_context(request: Request, context: OrgContext) -> None:
    request.state.org_context = context
    request.state.user_id = context.user_id
    request.state.org_id = context.org_id
    request.state.active_org_id = context.org_id
    request.state.request_id = context.request_id
    request.state.trace_id = context.request_id
    request.state.context_id = context.request_id
    set_current_event_context(context_id=context.request_id, user_id=context.user_id)


async def org_context_middleware(request: Request, call_next):
    if not _is_api_path(request):
        return await call_next(request)

    request_id = generate_request_id()
    request.state.request_id = request_id
    request.state.context_id = request_id
    request.state.trace_id = request_id
    set_current_event_context(context_id=request_id)

    frontend_org_source = _frontend_org_context_present(request)
    if frontend_org_source is not None:
        emit_event(
            event_type="org_context.rejected",
            module="system",
            action="c18h.org_context",
            source="backend",
            status="failed",
            context_id=request_id,
            payload={
                "reason": "frontend_org_context_not_allowed",
                "frontend_source": frontend_org_source,
            },
        )
        return _security_response(
            status.HTTP_400_BAD_REQUEST,
            "org_id must come from the authenticated server context.",
        )

    session_id = request.cookies.get(settings.auth_session_cookie_name)
    if session_id is None:
        if _requires_org_context(request):
            return _security_response(
                status.HTTP_401_UNAUTHORIZED,
                "Not authenticated.",
            )
        return await call_next(request)

    audit = _audit_context(request, request_id)
    with SessionLocal() as db:
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

        request.state.user_id = str(current_session.user.id)
        context, resolution_source = build_org_context(
            db,
            request=request,
            user=current_session.user,
            auth_session=current_session.auth_session,
            request_id=request_id,
        )

    if context is not None:
        inject_org_context(request, context)
        emit_event(
            event_type="org_context.injected",
            module="system",
            action="c18h.org_context",
            source="backend",
            status="success",
            context_id=context.request_id,
            user_id=context.user_id,
            payload={
                "org_id": context.org_id,
                "role": context.role,
                "module_scope": context.module_scope,
                "resolution_source": resolution_source,
            },
        )
    else:
        set_current_event_context(context_id=request_id, user_id=request.state.user_id)
        emit_event(
            event_type="org_context.missing",
            module="system",
            action="c18h.org_context",
            source="backend",
            status="pending",
            context_id=request_id,
            user_id=request.state.user_id,
            payload={"reason": resolution_source},
        )
        if _requires_org_context(request):
            return _security_response(
                status.HTTP_403_FORBIDDEN,
                "C18H org context is required.",
            )

    return await call_next(request)
