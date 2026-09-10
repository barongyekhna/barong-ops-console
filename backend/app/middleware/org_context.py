from __future__ import annotations

from threading import Lock

import time

import hashlib

from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

import anyio
from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.api_classification import is_lightweight_control_plane_path
from ..core.auth_paths import is_auth_me_path
from ..core.config import get_settings
from ..core.security_headers import apply_security_headers
from ..core.session_cookies import get_session_id_from_request
from ..core.roles import is_org_admin_like_role, normalize_role
from ..db.compatibility import is_missing_table_error, table_exists
from ..db.session import managed_read_session
from ..models.auth_session import AuthSession
from ..models.org_membership import OrgMembershipRecord
from ..models.organization import OrganizationRecord
from ..models.user import User
from ..schemas.module_binding import GLOBAL_MODULE_BOUND_ORG
from ..repositories.tenant import ROLLOUT_BACKFILL_ORG_ID
from ..services.auth_service import (
    AuditContext,
    InvalidSessionError,
    authenticated_session_from_identity,
    validate_session_identity_fast,
)
from ..services.event_collector import emit_event, set_current_event_context
from ..services.module_binding_service import list_module_bindings
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
        "/api/app/permissions/me",
        "/api/app/h/ingest",
    )
)
# C19 is native to every active authenticated user and has no organization
# admission gate. Its own services enforce participant/content policy and
# validate an affiliation only when a user explicitly selects organization data.
ORG_CONTEXT_EXEMPT_PREFIXES = ("/api/app/c19",)
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
    is_exempt = path in ORG_CONTEXT_EXEMPT_PATHS or any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in ORG_CONTEXT_EXEMPT_PREFIXES
    )
    return path.startswith(TENANT_API_PATH_PREFIXES) and not is_exempt


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


def _c18_org_tables_available(db: Session) -> bool:
    return table_exists(db, "org_memberships") and table_exists(
        db,
        "organizations",
    )


def _compat_org_resolution(*, role: str) -> OrgResolution:
    normalized_role = normalize_role(role)
    return OrgResolution(
        org_id=ROLLOUT_BACKFILL_ORG_ID,
        role="owner" if normalized_role == "owner" else "member",
        source="c05b_compat_no_c18_tables",
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
    user_role = normalize_role(user.role)
    if not _c18_org_tables_available(db):
        return _compat_org_resolution(role=user_role)

    try:
        memberships = _active_memberships_for_user(db, user_id=user_id)
    except SQLAlchemyError as exc:
        if is_missing_table_error(exc, "org_memberships"):
            db.rollback()
            return _compat_org_resolution(role=user_role)
        raise
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
        try:
            owner_org = _owner_org_for_user(db, user_id=user_id)
        except SQLAlchemyError as exc:
            if is_missing_table_error(exc, "organizations"):
                db.rollback()
                return _compat_org_resolution(role=user_role)
            raise
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

    # 多组织成员、会话还没选过组织(比如刚被加进第二家公司、或换了设备登录):
    # 落在主组织(users.organization_id)上,前提是他在主组织确实有 active 成员关系。
    # 没有这条,这种人第一次登录整站 403,连切换器都来不及点(2026-08-31 体检坑)。
    if len(memberships) > 1:
        home_org_id = _string_value(user.organization_id)
        home_membership = memberships_by_org.get(home_org_id) if home_org_id else None
        if home_membership is not None:
            return OrgResolution(
                org_id=home_org_id,
                role=_role_for_membership(home_membership),
                source="fallback_home_org_membership",
            )

    if is_org_admin_like_role(user_role):
        user_org_id = _string_value(user.organization_id)
        if user_org_id is not None:
            organization = db.get(OrganizationRecord, user_org_id)
            if organization is not None and organization.status == "active":
                return OrgResolution(
                    org_id=organization.org_id,
                    role="admin",
                    source="fallback_org_admin_user_org",
                )

    try:
        owner_org = _owner_org_for_user(db, user_id=user_id)
    except SQLAlchemyError as exc:
        if is_missing_table_error(exc, "organizations"):
            db.rollback()
            return _compat_org_resolution(role=user_role)
        raise
    if owner_org is not None:
        return OrgResolution(
            org_id=owner_org.org_id,
            role="owner",
            source="fallback_owner_org",
        )

    return None


def _module_scope_for_org(db: Session, org_id: str) -> list[str]:
    if not table_exists(db, "module_bindings"):
        return []
    module_ids: list[str] = []
    try:
        bindings = list_module_bindings(db)
    except SQLAlchemyError as exc:
        if is_missing_table_error(exc, "module_bindings"):
            db.rollback()
            return []
        raise
    for binding in bindings:
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


# --- 组织上下文的会话级缓存 ---------------------------------------------------
#
# 为什么需要：2026-09-01 剖析发现完整中间件链每请求约 90ms，其中数据库往返只占
# 约 18ms，真正的大头是 `anyio.to_thread.run_sync` 的线程切换（每请求 36 次，
# `_thread.lock.acquire` 累计占 83%）。而「这个用户属于哪个组织」在一个会话内
# 是稳定答案，没必要每个请求重算一遍、还为此走一趟线程池。
#
# TTL 与 auth_service.SESSION_IDENTITY_CACHE_TTL_SECONDS 保持一致：
# 组织归属变更（加/去成员关系）最多 5 秒后生效，与会话身份缓存的既有取舍同源。
ORG_CONTEXT_CACHE_TTL_SECONDS = 5
ORG_CONTEXT_CACHE_MAX_ENTRIES = 4096
_org_context_cache: dict[str, tuple[float, OrgContext, str]] = {}
_org_context_cache_lock = Lock()


def _org_context_cache_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _org_context_from_cache(session_id: str) -> tuple[OrgContext, str] | None:
    key = _org_context_cache_key(session_id)
    now = time.monotonic()
    with _org_context_cache_lock:
        entry = _org_context_cache.get(key)
        if entry is None:
            return None
        expires_at, context, source = entry
        if expires_at <= now:
            _org_context_cache.pop(key, None)
            return None
        return context, source


def _store_org_context_in_cache(
    session_id: str, context: OrgContext, source: str
) -> None:
    key = _org_context_cache_key(session_id)
    expires_at = time.monotonic() + ORG_CONTEXT_CACHE_TTL_SECONDS
    with _org_context_cache_lock:
        if len(_org_context_cache) >= ORG_CONTEXT_CACHE_MAX_ENTRIES:
            _org_context_cache.clear()
        _org_context_cache[key] = (expires_at, context, source)


def reset_org_context_cache_for_tests() -> None:
    """清空缓存。测试里改了成员关系/组织之后必须调用。"""
    with _org_context_cache_lock:
        _org_context_cache.clear()

async def org_context_middleware(request: Request, call_next):
    if is_auth_me_path(request.url.path):
        return await call_next(request)

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

    if is_lightweight_control_plane_path(request.url.path):
        return await call_next(request)

    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        if _requires_org_context(request):
            return _security_response(
                status.HTTP_401_UNAUTHORIZED,
                "Not authenticated.",
            )
        return await call_next(request)

    # 先看缓存：命中就直接在事件循环上注入，**完全不进线程池、不开数据库会话**。
    # 这一条省掉的不只是几次查询，更是那趟线程池往返 —— 剖析显示后者才是大头。
    cached_context = _org_context_from_cache(session_id)
    if cached_context is not None:
        context, resolution_source = cached_context
        inject_org_context(request, context)
        return await call_next(request)

    audit = _audit_context(request, request_id)
    current_session = get_cached_authenticated_session(
        request,
        session_id=session_id,
    )

    # Session validation and org-context resolution are synchronous
    # SQLAlchemy work; run them on the thread pool so they cannot block the
    # event loop under concurrency.
    def _resolve_org_context_off_loop():
        resolved_session = current_session
        with managed_read_session() as db:
            if resolved_session is None:
                identity = validate_session_identity_fast(
                    db,
                    session_id=session_id,
                )
                resolved_session = authenticated_session_from_identity(
                    identity,
                    audit=audit,
                )
                cache_authenticated_session(
                    request,
                    session_id=session_id,
                    current_session=resolved_session,
                )

            queue_session_seen(resolved_session.auth_session.session_id_hash)
            request.state.user_id = str(resolved_session.user.id)
            resolved_context, source = build_org_context(
                db,
                request=request,
                user=resolved_session.user,
                auth_session=resolved_session.auth_session,
                request_id=request_id,
            )
        return resolved_context, source

    try:
        context, resolution_source = await anyio.to_thread.run_sync(
            _resolve_org_context_off_loop
        )
    except InvalidSessionError:
        return _security_response(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated.",
        )

    if context is not None:
        _store_org_context_in_cache(session_id, context, resolution_source)
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
