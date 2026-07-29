import logging
from contextlib import asynccontextmanager
from threading import Lock
from time import monotonic

import anyio
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.deps import get_audit_context
from .api.routes.agents import router as agents_router
from .api.routes.api_key_orchestration import router as api_key_orchestration_router
from .api.routes.ai_execution_bindings import router as ai_execution_bindings_router
from .api.routes.approval import plural_router as approvals_router
from .api.routes.approval import router as approval_router
from .api.routes.arcade import router as arcade_router
from .api.routes.auth import router as auth_router
from .api.routes.callback_handler import router as callback_handler_router
from .api.routes.capability_bindings import router as capability_bindings_router
from .api.routes.capability_bootstrap import router as capability_bootstrap_router
from .api.routes.dashboard import router as dashboard_router
from .api.routes.errors import router as errors_router
from .api.routes.external_dependencies import router as external_dependencies_router
from .api.routes.execution_providers import router as execution_providers_router
from .api.routes.execution_prompts import router as execution_prompts_router
from .api.routes.failure_handling import router as failure_handling_router
from .api.routes.foundation_demo import router as foundation_demo_router
from .api.routes.health import (
    HealthResponse,
    health,
    is_lightweight_health_path,
    lightweight_health_response,
    router as health_router,
)
from .modules.c19.router import router as c19_router
from .modules.cs_series.router import public_router as cs_public_router
from .modules.cs_series.router import router as cs_customer_service_router
from .modules.f_series.router import router as f_enrichment_router
from .modules.h_series.router import router as h_site_health_router
from .modules.geo_series.router import router as geo_content_router
from .modules.geo_series.machine_router import router as geo_machine_router
from .modules.w_series.router import machine_router as w_siteops_machine_router
from .modules.w_series.router import public_router as w_siteops_public_router
from .modules.w_series.router import router as w_siteops_router
from .modules.i_series.image_system.router import (
    router as i_image_system_router,
)
from .modules.k_series.product_knowledge.router import (
    router as k_product_knowledge_router,
)
from .modules.k_series.product_knowledge.spec_template_router import (
    router as k_spec_template_router,
)
from .modules.key_health.router import router as key_health_router
from .modules.notifications.router import (
    router as notifications_router,
)
from .modules.p_series.router import (
    router as p_upload_router,
)
from .api.routes.live_gate import router as live_gate_router
from .api.routes.memory import router as memory_router
from .api.routes.model_locks import router as model_locks_router
from .api.routes.module_control import router as module_control_router
from .api.routes.module_allocations import router as module_allocations_router
from .api.routes.module_adapters import router as module_adapters_router
from .api.routes.modules import router as modules_router
from .api.routes.module_workflow_bindings import (
    router as module_workflow_bindings_router,
)
from .api.routes.n8n_test import router as n8n_test_router
from .api.routes.webhook_registry import router as webhook_registry_router
from .api.routes.operation_logs import router as operation_logs_router
from .api.routes.organizations import router as organizations_router
from .api.routes.payload_standardization import (
    router as payload_standardization_router,
)
from .api.routes.permissions import router as permissions_router
from .api.routes.ra import router as ra_router
from .api.routes.reviews import router as reviews_router
from .api.routes.rw import router as rw_router
from .api.routes.result_normalization import router as result_normalization_router
from .api.routes.security_firewall import router as security_firewall_router
from .api.routes.users import router as users_router
from .api.routes.webhook_gateway import router as webhook_gateway_router
from .api.routes.workflow_registry import router as workflow_registry_router
from .api.module_binding import router as module_binding_router
from .api.module_visibility import router as module_visibility_router
from .api.org import router as org_router
from .api.org_membership import router as org_membership_router
from .api.shared_module import router as shared_module_router
from .core.api_classification import is_lightweight_control_plane_path
from .core.auth_paths import is_auth_me_path
from .core.config import get_settings
from .core.environments import is_production_like
from .core.security_headers import apply_security_headers
from .core.session_cookies import get_session_id_from_request
from .core.roles import is_owner_role, normalize_role
from .db.session import managed_read_session
from .models.auth_session import AuthSession
from .models.organization import OrganizationRecord
from .models.user import User
from .repositories.organizations import (
    get_organization,
    list_organizations as list_org_records,
)
from .middleware.event_collector import capture_audit_events
from .middleware.data_isolation import enforce_org_data_isolation
from .middleware.org_context import org_context_middleware
from .middleware.permission import enforce_permission_isolation
from .services.event_collector import emit_event
from .services.data_isolation import without_org_data_isolation
from .services.auth_service import (
    AuthenticatedSession,
    AuthenticatedUserIdentity,
    InvalidSessionError,
    get_cached_session_identity,
    validate_session,
    validate_session_identity_fast,
)
from .schemas.common import ListResponse
from .schemas.module import ModuleManifestRead, ModuleRegistryResponse
from .schemas.organization import Organization, OrganizationMetadata
from .schemas.permission import (
    CurrentUserPermissionResponse,
    CurrentUserPermissionsRead,
)
from .services.login_side_effects import (
    start_login_side_effect_worker,
    stop_login_side_effect_worker,
)
from .services.api_key_usage_tracker import (
    start_api_key_usage_flush_worker,
    stop_api_key_usage_flush_worker,
)
from .services.module_control_cache_service import (
    get_module_control_center_cached,
    refresh_module_control_center_cache_async,
    refresh_module_control_center_cache_sync,
    start_module_control_cache_worker,
    stop_module_control_cache_worker,
)
from .services.module_control_center import filter_module_control_center_for_user
from .services.module_registry import list_module_manifests_with_dynamic
from .services.permission_service import resolve_current_user_permission_info
from .services.permission_decision_engine import PermissionDecisionEngine
from .services.request_session_cache import cache_authenticated_session
from .services.session_seen_buffer import (
    queue_session_seen,
    start_session_seen_flush_worker,
    stop_session_seen_flush_worker,
)
from .services.unified_permission_engine import UnifiedPermissionRequest

settings = get_settings()
logger = logging.getLogger(__name__)

PUBLIC_API_PREFIX = "/api/public"
APPLICATION_API_PREFIX = "/api/app"
CONTROL_PLANE_API_PREFIX = "/api/control-plane"
HOT_READ_CACHE_TTL_SECONDS = 5.0
HOT_READ_PATHS = frozenset(
    (
        "/api/app/organizations",
        "/api/app/permissions/me",
        "/api/control-plane/module-control/center",
        "/api/control-plane/modules/registry",
    )
)
_hot_read_cache_lock = Lock()
_hot_read_cache: dict[tuple[object, ...], tuple[float, object]] = {}


def _production_like() -> bool:
    return is_production_like(settings)


def _docs_enabled() -> bool:
    if settings.app_docs_enabled is not None:
        return settings.app_docs_enabled
    return not _production_like()


def _control_plane_stealth_mode() -> bool:
    if settings.control_plane_stealth_mode is not None:
        return settings.control_plane_stealth_mode
    return _production_like()


def _json_security_response(
    *,
    status_code: int,
    detail: object,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers=headers,
    )
    apply_security_headers(response, settings=settings)
    return response


def _json_ok_security_response(content: object) -> JSONResponse:
    response = JSONResponse(status_code=status.HTTP_200_OK, content=content)
    apply_security_headers(response, settings=settings)
    return response


def _auth_me_payload(request: Request) -> dict[str, object] | None:
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        return None

    with managed_read_session() as db:
        try:
            identity = validate_session_identity_fast(db, session_id=session_id)
        except InvalidSessionError:
            return None
        queue_session_seen(identity.session_id_hash)
        request.state.user_id = str(identity.id)
        return jsonable_encoder(
            {
                "id": identity.id,
                "username": identity.username,
                "role": normalize_role(identity.role),
                "organization_id": identity.organization_id,
                "must_change_password": identity.must_change_password,
                "is_active": identity.is_active,
                "last_login_at": identity.last_login_at,
            }
        )


def _session_from_identity(
    identity: AuthenticatedUserIdentity,
    *,
    audit: object,
) -> AuthenticatedSession:
    user = User(
        username=identity.username,
        password_hash="",
        role=normalize_role(identity.role),
        organization_id=identity.organization_id,
        must_change_password=identity.must_change_password,
        is_active=identity.is_active,
    )
    user.id = identity.id
    user.last_login_at = identity.last_login_at

    auth_session = AuthSession(
        session_id_hash=identity.session_id_hash,
        user_id=identity.id,
        issued_at=identity.session_expires_at,
        expires_at=identity.session_expires_at,
        last_seen_at=None,
        ip_address=getattr(audit, "ip_address", None),
        user_agent=getattr(audit, "user_agent", None),
    )
    auth_session.id = 0
    auth_session.invalidated_at = None
    auth_session.invalidation_reason = None
    auth_session.user = user
    return AuthenticatedSession(user=user, auth_session=auth_session)


def _production_error_detail(request: Request, status_code: int) -> str:
    if _is_control_plane_path(request.url.path):
        return "Not found."
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "Not authenticated."
    if status_code == status.HTTP_403_FORBIDDEN:
        return "Forbidden."
    if status_code in {
        status.HTTP_404_NOT_FOUND,
        status.HTTP_405_METHOD_NOT_ALLOWED,
    }:
        return "Not found."
    if status_code == status.HTTP_409_CONFLICT:
        return "Request conflict."
    if status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        return "Invalid request."
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return "Too many requests."
    if status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        return "Service unavailable."
    if status_code >= 500:
        return "Internal server error."
    return "Request failed."


def _p_publish_gate_conflict_detail_for_production(
    request: Request,
    status_code: int,
    detail: object,
) -> dict[str, object] | None:
    """Keep only the non-sensitive P publish-gate conflict contract."""

    gated_prefixes = (
        f"{APPLICATION_API_PREFIX}/p/",
        # GEO publishing reuses the same publish-gate conflict contract, and its
        # blockers must stay readable in production or the operator cannot tell
        # why a cluster refused to publish.
        f"{APPLICATION_API_PREFIX}/geo/",
    )
    if (
        status_code != status.HTTP_409_CONFLICT
        or not request.url.path.startswith(gated_prefixes)
        or not isinstance(detail, dict)
        or set(detail) != {"ready", "blockers"}
    ):
        return None
    ready = detail.get("ready")
    blockers = detail.get("blockers")
    if not isinstance(ready, bool) or not isinstance(blockers, list):
        return None
    if not all(isinstance(blocker, str) for blocker in blockers):
        return None
    return {"ready": ready, "blockers": list(blockers)}


def _structured_failure_detail_for_production(
    request: Request,
    detail: object,
) -> object | None:
    if not request.url.path.startswith(f"{APPLICATION_API_PREFIX}/k/"):
        return None
    if not isinstance(detail, dict):
        return None
    if detail.get("status") != "failed" or not isinstance(detail.get("reason"), str):
        return None
    return detail


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    if _production_like():
        from .db.migration_safety import enforce_migration_safety
        from .db.session import engine

        enforce_migration_safety(engine, app_env=settings.app_env)
    start_session_seen_flush_worker()
    start_api_key_usage_flush_worker()
    start_login_side_effect_worker()
    start_module_control_cache_worker()
    refresh_module_control_center_cache_async(force=True)
    try:
        yield
    finally:
        stop_login_side_effect_worker()
        stop_module_control_cache_worker()
        stop_api_key_usage_flush_worker()
        stop_session_seen_flush_worker()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=False if _production_like() else settings.app_debug,
    docs_url="/docs" if _docs_enabled() else None,
    redoc_url="/redoc" if _docs_enabled() else None,
    openapi_url="/openapi.json" if _docs_enabled() else None,
    lifespan=_app_lifespan,
)


def _is_control_plane_path(path: str) -> bool:
    return (
        path == CONTROL_PLANE_API_PREFIX
        or path.startswith(f"{CONTROL_PLANE_API_PREFIX}/")
    )


def _is_removed_module_path(path: str) -> bool:
    removed_prefixes = (
        f"{APPLICATION_API_PREFIX}/artifacts",
        f"{APPLICATION_API_PREFIX}/jobs",
        f"{CONTROL_PLANE_API_PREFIX}/workflows",
    )
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in removed_prefixes
    )


def _control_plane_denied_response(
    *,
    status_code: int,
    detail: str,
) -> JSONResponse:
    if _control_plane_stealth_mode():
        return _json_security_response(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )
    return _json_security_response(status_code=status_code, detail=detail)


def _organization_to_schema(record: OrganizationRecord) -> Organization:
    return Organization(
        org_id=record.org_id,
        org_name=record.org_name,
        org_type=record.org_type,
        owner_user_id=record.owner_user_id,
        status=record.status,
        metadata=OrganizationMetadata.model_validate(record.metadata_json or {}),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _identity_to_user(identity: AuthenticatedUserIdentity) -> User:
    user = User(
        username=identity.username,
        password_hash="",
        role=normalize_role(identity.role),
        organization_id=identity.organization_id,
        must_change_password=identity.must_change_password,
        is_active=identity.is_active,
    )
    user.id = identity.id
    user.last_login_at = identity.last_login_at
    return user


def _cache_key_for_hot_read(
    identity: AuthenticatedUserIdentity,
    path: str,
    query_params: tuple[tuple[str, str], ...],
) -> tuple[object, ...]:
    limit = next((value for key, value in query_params if key == "limit"), "")
    offset = next((value for key, value in query_params if key == "offset"), "")
    if path == "/api/app/organizations":
        return (
            path,
            identity.id,
            normalize_role(identity.role),
            identity.organization_id,
            limit or "100",
            offset or "0",
        )
    if path == "/api/app/permissions/me":
        return (path, identity.id, normalize_role(identity.role))
    return (path, normalize_role(identity.role))


def _cached_hot_read_payload(
    key: tuple[object, ...],
    loader,
) -> object:
    now = monotonic()
    with _hot_read_cache_lock:
        cached = _hot_read_cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        value = loader()
        if len(_hot_read_cache) >= 512:
            _hot_read_cache.clear()
        _hot_read_cache[key] = (monotonic() + HOT_READ_CACHE_TTL_SECONDS, value)
        return value


def _get_cached_hot_read_payload(
    key: tuple[object, ...],
) -> object | None:
    now = monotonic()
    with _hot_read_cache_lock:
        cached = _hot_read_cache.get(key)
        if cached is None:
            return None
        if cached[0] <= now:
            _hot_read_cache.pop(key, None)
            return None
        return cached[1]


def _load_hot_read_payload(
    identity: AuthenticatedUserIdentity,
    path: str,
    query_params: tuple[tuple[str, str], ...],
) -> object:
    role = normalize_role(identity.role)
    key = _cache_key_for_hot_read(identity, path, query_params)

    def load_organizations() -> object:
        limit = min(
            max(
                1,
                int(next((value for k, value in query_params if k == "limit"), 100)),
            ),
            100,
        )
        offset = max(
            0,
            int(next((value for k, value in query_params if k == "offset"), 0)),
        )
        with managed_read_session() as db:
            if not is_owner_role(role):
                org_id = (identity.organization_id or "").strip()
                records = []
                if org_id:
                    record = get_organization(db, org_id)
                    if record is not None and record.status != "deleted":
                        records = [record]
                page = records[offset : offset + limit]
                response = ListResponse(
                    items=[_organization_to_schema(record) for record in page],
                    count=len(records),
                    limit=limit,
                    offset=offset,
                )
                return response.model_dump_json()
            with without_org_data_isolation():
                records = list_org_records(db, limit=limit, offset=offset)
            response = ListResponse(
                items=[_organization_to_schema(record) for record in records],
                count=len(records),
                limit=limit,
                offset=offset,
            )
            return response.model_dump_json()

    def load_permissions_me() -> object:
        user = _identity_to_user(identity)
        if is_owner_role(role):
            permissions = CurrentUserPermissionsRead(
                is_owner_full_access=True,
                permission_keys=["*"],
                assignments=[],
                scope_summary=[],
            )
        else:
            with managed_read_session() as db:
                permissions = CurrentUserPermissionsRead.model_validate(
                    resolve_current_user_permission_info(db, user)
                )
        response = CurrentUserPermissionResponse(
            id=user.id,
            user_id=user.id,
            role=user.role,
            is_owner=is_owner_role(user.role),
            permission_keys=permissions.permission_keys,
            permissions=permissions,
        )
        return response.model_dump_json()

    def load_module_registry() -> object:
        if not (is_owner_role(role) or role == "super_admin"):
            return {
                "detail": "Forbidden.",
                "_status_code": status.HTTP_403_FORBIDDEN,
            }
        with managed_read_session() as db:
            manifests = list_module_manifests_with_dynamic(db)
        response = ModuleRegistryResponse(
            items=[
                ModuleManifestRead.model_validate(manifest.model_dump())
                for manifest in manifests
            ],
            count=len(manifests),
        )
        return response.model_dump_json()

    def load_module_control_center() -> object:
        user = _identity_to_user(identity)
        with managed_read_session() as db:
            with without_org_data_isolation():
                force_refresh = any(
                    key in {"force_refresh", "_force_refresh"} and value == "1"
                    for key, value in query_params
                )
                response = (
                    refresh_module_control_center_cache_sync()
                    if force_refresh
                    else get_module_control_center_cached(db=db)
                )
                scoped_response = filter_module_control_center_for_user(
                    db,
                    user=user,
                    response=response,
                )
            return scoped_response.model_dump_json()

    if path == "/api/app/organizations":
        return _cached_hot_read_payload(key, load_organizations)
    if path == "/api/app/permissions/me":
        return _cached_hot_read_payload(key, load_permissions_me)
    if path == "/api/control-plane/module-control/center":
        return load_module_control_center()
    return _cached_hot_read_payload(key, load_module_registry)


@app.exception_handler(StarletteHTTPException)
async def sanitized_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
):
    if _production_like():
        detail = _p_publish_gate_conflict_detail_for_production(
            request,
            exc.status_code,
            exc.detail,
        )
        if detail is None:
            detail = _structured_failure_detail_for_production(request, exc.detail)
        if detail is None:
            detail = _production_error_detail(request, exc.status_code)
    else:
        detail = exc.detail
    return _json_security_response(
        status_code=exc.status_code,
        detail=detail,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def sanitized_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    detail: object = (
        _production_error_detail(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
        if _production_like()
        else exc.errors()
    )
    return _json_security_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


@app.exception_handler(Exception)
async def sanitized_unhandled_exception_handler(
    request: Request,
    exc: Exception,
):
    logger.error(
        "Unhandled API exception path=%s request_id=%s",
        request.url.path,
        getattr(request.state, "context_id", None),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    detail = (
        _production_error_detail(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        if _production_like()
        else "Internal server error."
    )
    return _json_security_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    )


@app.middleware("http")
async def enforce_control_plane_isolation(request: Request, call_next):
    if not _is_control_plane_path(request.url.path):
        return await call_next(request)

    audit = get_audit_context(request)
    lightweight_control_plane = is_lightweight_control_plane_path(request.url.path)
    if not lightweight_control_plane:
        emit_event(
            event_type="control_plane.entry",
            module="C16",
            action=f"{request.method} {request.url.path}",
            source="backend",
            status="pending",
            context_id=audit.request_id,
            payload={"path": request.url.path, "method": request.method},
        )
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        if not lightweight_control_plane:
            emit_event(
                event_type="control_plane.exit",
                module="C16",
                action=f"{request.method} {request.url.path}",
                source="backend",
                status="failed",
                context_id=audit.request_id,
                payload={"reason": "missing_session"},
            )
        return _control_plane_denied_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    if lightweight_control_plane:
        def _load_identity_off_loop() -> AuthenticatedUserIdentity:
            with managed_read_session() as db:
                return validate_session_identity_fast(db, session_id=session_id)

        try:
            identity = await anyio.to_thread.run_sync(_load_identity_off_loop)
        except InvalidSessionError:
            return _control_plane_denied_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
            )

        current_session = _session_from_identity(identity, audit=audit)
        queue_session_seen(identity.session_id_hash)
        cache_authenticated_session(
            request,
            session_id=session_id,
            current_session=current_session,
        )
        decision = PermissionDecisionEngine(request=request).decide_platform_metadata(
            UnifiedPermissionRequest(
                user_id=current_session.user.id,
                org_id=None,
                module_id="C16",
                action="admin",
                role=current_session.user.role,
                scope_type="global",
                scope_key="*",
                source="control_plane_lightweight_isolation",
            )
        )
        request.state.control_plane_rbac_decision = decision
        if not decision.allowed:
            request.state.user_id = str(current_session.user.id)
            return _control_plane_denied_response(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden.",
            )
        request.state.user_id = str(current_session.user.id)
        request.state.control_plane_pipeline = "lightweight"
        return await call_next(request)

    # Full session validation + platform permission decision are synchronous
    # SQLAlchemy work; run them on the thread pool so they cannot block the
    # event loop under concurrency.
    def _validate_and_decide_off_loop():
        with managed_read_session() as db:
            session = validate_session(
                db,
                session_id=session_id,
                audit=get_audit_context(request),
            )
            queue_session_seen(session.auth_session.session_id_hash)
            cache_authenticated_session(
                request,
                session_id=session_id,
                current_session=session,
            )
            # Extract primitives while the ORM instances are still bound;
            # closing the read session expires their attributes.
            user_id_value = str(session.user.id)
            role_value = session.user.role
            rbac_decision = PermissionDecisionEngine(
                db,
                request=request,
            ).decide_platform_metadata(
                UnifiedPermissionRequest(
                    user_id=session.user.id,
                    org_id=None,
                    module_id="C16",
                    action="admin",
                    role=role_value,
                    scope_type="global",
                    scope_key="*",
                    source="control_plane_isolation",
                )
            )
            return user_id_value, role_value, rbac_decision

    try:
        session_user_id, session_user_role, decision = (
            await anyio.to_thread.run_sync(_validate_and_decide_off_loop)
        )
    except InvalidSessionError:
        emit_event(
            event_type="control_plane.exit",
            module="C16",
            action=f"{request.method} {request.url.path}",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            payload={"reason": "invalid_session"},
        )
        return _control_plane_denied_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    request.state.control_plane_rbac_decision = decision
    if not decision.allowed:
        request.state.user_id = session_user_id
        emit_event(
            event_type="control_plane.exit",
            module="C16",
            action=f"{request.method} {request.url.path}",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            user_id=session_user_id,
            payload={
                "reason": "permission_denied",
                "role": session_user_role,
                "decision_source": "PermissionDecisionEngine",
                "denial_code": decision.denial_code,
            },
        )
        return _control_plane_denied_response(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden.",
        )
    request.state.user_id = session_user_id

    response = await call_next(request)
    emit_event(
        event_type="control_plane.exit",
        module="C16",
        action=f"{request.method} {request.url.path}",
        source="backend",
        status="success" if response.status_code < 400 else "failed",
        context_id=audit.request_id,
        user_id=getattr(request.state, "user_id", None),
        payload={"status_code": response.status_code},
    )
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    apply_security_headers(response, settings=settings)
    return response


@app.middleware("http")
async def collect_audit_events(request: Request, call_next):
    return await capture_audit_events(request, call_next)


@app.middleware("http")
async def enforce_c18g_org_data_isolation(request: Request, call_next):
    return await enforce_org_data_isolation(request, call_next)


@app.middleware("http")
async def enforce_c18f_permission_isolation(request: Request, call_next):
    return await enforce_permission_isolation(request, call_next)


@app.middleware("http")
async def inject_c18h_org_context(request: Request, call_next):
    return await org_context_middleware(request, call_next)


@app.middleware("http")
async def short_circuit_auth_me(request: Request, call_next):
    if not is_auth_me_path(request.url.path):
        return await call_next(request)

    payload = await anyio.to_thread.run_sync(_auth_me_payload, request)
    if payload is None:
        return _json_security_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    return _json_ok_security_response(payload)


@app.middleware("http")
async def short_circuit_lightweight_health(request: Request, call_next):
    if is_lightweight_health_path(request.url.path):
        return lightweight_health_response()
    return await call_next(request)


@app.middleware("http")
async def short_circuit_removed_modules(request: Request, call_next):
    if _is_removed_module_path(request.url.path):
        return _json_security_response(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )
    return await call_next(request)


@app.middleware("http")
async def short_circuit_authenticated_hot_reads(request: Request, call_next):
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        or request.url.path not in HOT_READ_PATHS
    ):
        return await call_next(request)

    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        return _json_security_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    audit = get_audit_context(request)

    try:
        identity = get_cached_session_identity(session_id)
    except InvalidSessionError:
        return _json_security_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    if identity is None:
        def load_identity() -> AuthenticatedUserIdentity:
            with managed_read_session() as db:
                return validate_session_identity_fast(db, session_id=session_id)

        try:
            identity = await anyio.to_thread.run_sync(load_identity)
        except InvalidSessionError:
            return _json_security_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
            )

    request.state.user_id = str(identity.id)
    query_params = tuple(request.query_params.multi_items())
    cache_key = _cache_key_for_hot_read(identity, request.url.path, query_params)
    if request.url.path == "/api/control-plane/module-control/center":
        payload = await anyio.to_thread.run_sync(
            _load_hot_read_payload,
            identity,
            request.url.path,
            query_params,
        )
    else:
        payload = _get_cached_hot_read_payload(cache_key)
        if payload is None:
            payload = await anyio.to_thread.run_sync(
                _load_hot_read_payload,
                identity,
                request.url.path,
                query_params,
            )
    if isinstance(payload, dict) and "_status_code" in payload:
        status_code = int(payload.get("_status_code") or 500)
        return _json_security_response(
            status_code=status_code,
            detail=payload.get("detail", "Request failed."),
        )

    if isinstance(payload, bytes):
        response = Response(content=payload, media_type="application/json")
        apply_security_headers(response, settings=settings)
    elif isinstance(payload, str):
        response = Response(content=payload, media_type="application/json")
        apply_security_headers(response, settings=settings)
    else:
        response = _json_ok_security_response(jsonable_encoder(payload))
    response.headers["X-Request-ID"] = audit.request_id
    response.headers["X-Trace-ID"] = audit.request_id
    return response


@app.get("/health", response_model=HealthResponse, include_in_schema=False)
@app.get(
    "/api/backend/health",
    response_model=HealthResponse,
    include_in_schema=False,
)
def lightweight_health() -> HealthResponse:
    return health()


app.include_router(health_router, prefix=PUBLIC_API_PREFIX)
app.include_router(security_firewall_router, prefix=PUBLIC_API_PREFIX)
app.include_router(auth_router, prefix=PUBLIC_API_PREFIX)
app.include_router(cs_public_router, prefix=PUBLIC_API_PREFIX)
app.include_router(w_siteops_public_router, prefix=PUBLIC_API_PREFIX)

app.include_router(users_router, prefix=APPLICATION_API_PREFIX)
app.include_router(dashboard_router, prefix=APPLICATION_API_PREFIX)
app.include_router(arcade_router, prefix=APPLICATION_API_PREFIX)
app.include_router(approval_router, prefix=APPLICATION_API_PREFIX)
app.include_router(approvals_router, prefix=APPLICATION_API_PREFIX)
app.include_router(reviews_router, prefix=APPLICATION_API_PREFIX)
app.include_router(errors_router, prefix=APPLICATION_API_PREFIX)
app.include_router(memory_router, prefix=APPLICATION_API_PREFIX)
app.include_router(operation_logs_router, prefix=APPLICATION_API_PREFIX)
app.include_router(permissions_router, prefix=APPLICATION_API_PREFIX)
app.include_router(organizations_router, prefix=APPLICATION_API_PREFIX)
app.include_router(org_router, prefix=APPLICATION_API_PREFIX)
app.include_router(org_membership_router, prefix=APPLICATION_API_PREFIX)
app.include_router(c19_router, prefix=APPLICATION_API_PREFIX)
app.include_router(cs_customer_service_router, prefix=APPLICATION_API_PREFIX)
app.include_router(geo_content_router, prefix=APPLICATION_API_PREFIX)
app.include_router(geo_machine_router, prefix=APPLICATION_API_PREFIX)
app.include_router(geo_machine_router)
app.include_router(module_binding_router, prefix=APPLICATION_API_PREFIX)
app.include_router(module_visibility_router, prefix=APPLICATION_API_PREFIX)
app.include_router(shared_module_router, prefix=APPLICATION_API_PREFIX)
app.include_router(k_product_knowledge_router, prefix=APPLICATION_API_PREFIX)
app.include_router(k_product_knowledge_router)
app.include_router(k_spec_template_router, prefix=APPLICATION_API_PREFIX)
app.include_router(k_spec_template_router)
app.include_router(i_image_system_router, prefix=APPLICATION_API_PREFIX)
app.include_router(notifications_router, prefix=APPLICATION_API_PREFIX)
app.include_router(notifications_router)
app.include_router(p_upload_router, prefix=APPLICATION_API_PREFIX)
app.include_router(p_upload_router)
app.include_router(f_enrichment_router, prefix=APPLICATION_API_PREFIX)
app.include_router(h_site_health_router, prefix=APPLICATION_API_PREFIX)
app.include_router(w_siteops_router, prefix=APPLICATION_API_PREFIX)
app.include_router(w_siteops_machine_router, prefix=APPLICATION_API_PREFIX)
app.include_router(w_siteops_machine_router)
app.include_router(rw_router, prefix=APPLICATION_API_PREFIX)
app.include_router(ra_router, prefix=APPLICATION_API_PREFIX)

app.include_router(modules_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(agents_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(foundation_demo_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(n8n_test_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(webhook_registry_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(module_adapters_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(module_control_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(module_workflow_bindings_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(execution_providers_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(api_key_orchestration_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(key_health_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(execution_prompts_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(external_dependencies_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(ai_execution_bindings_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(model_locks_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(capability_bindings_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(capability_bootstrap_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(module_allocations_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(workflow_registry_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(webhook_gateway_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(payload_standardization_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(callback_handler_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(result_normalization_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(failure_handling_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(live_gate_router, prefix=CONTROL_PLANE_API_PREFIX)
