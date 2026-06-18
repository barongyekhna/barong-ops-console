from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.deps import get_audit_context
from .api.routes.agents import router as agents_router
from .api.routes.ai_execution_bindings import router as ai_execution_bindings_router
from .api.routes.approval import router as approval_router
from .api.routes.attachments import router as attachments_router
from .api.routes.artifacts import router as artifacts_router
from .api.routes.auth import router as auth_router
from .api.routes.callback_handler import router as callback_handler_router
from .api.routes.capability_bindings import router as capability_bindings_router
from .api.routes.contacts import router as contacts_router
from .api.routes.conversations import router as conversations_router
from .api.routes.cross_org_communication import (
    router as cross_org_communication_router,
)
from .api.routes.errors import router as errors_router
from .api.routes.external_dependencies import router as external_dependencies_router
from .api.routes.execution_providers import router as execution_providers_router
from .api.routes.execution_prompts import router as execution_prompts_router
from .api.routes.failure_handling import router as failure_handling_router
from .api.routes.foundation_demo import router as foundation_demo_router
from .api.routes.friends import router as friends_router
from .api.routes.health import (
    HealthResponse,
    health,
    is_lightweight_health_path,
    lightweight_health_response,
    router as health_router,
)
from .api.routes.jobs import router as jobs_router
from .api.routes.live_gate import router as live_gate_router
from .api.routes.memory import router as memory_router
from .api.routes.messages import router as messages_router
from .api.routes.model_locks import router as model_locks_router
from .api.routes.module_allocations import router as module_allocations_router
from .api.routes.module_adapters import router as module_adapters_router
from .api.routes.modules import router as modules_router
from .api.routes.module_workflow_bindings import (
    router as module_workflow_bindings_router,
)
from .api.routes.n8n_test import router as n8n_test_router
from .api.routes.operation_logs import router as operation_logs_router
from .api.routes.payload_standardization import (
    router as payload_standardization_router,
)
from .api.routes.permissions import router as permissions_router
from .api.routes.reviews import router as reviews_router
from .api.routes.result_normalization import router as result_normalization_router
from .api.routes.security_firewall import router as security_firewall_router
from .api.routes.users import router as users_router
from .api.routes.webhook_gateway import router as webhook_gateway_router
from .api.routes.workflow_registry import router as workflow_registry_router
from .api.routes.workflows import router as workflows_router
from .api.module_binding import router as module_binding_router
from .api.module_visibility import router as module_visibility_router
from .api.org import router as org_router
from .api.org_membership import router as org_membership_router
from .api.shared_module import router as shared_module_router
from .core.auth_paths import is_auth_me_path
from .core.config import get_settings
from .core.security_headers import apply_security_headers
from .db.session import managed_read_session
from .middleware.event_collector import capture_audit_events
from .middleware.data_isolation import enforce_org_data_isolation
from .middleware.org_context import org_context_middleware
from .middleware.permission import enforce_permission_isolation
from .services.event_collector import emit_event
from .services.auth_service import (
    InvalidSessionError,
    validate_session,
    validate_session_identity_fast,
)
from .services.permission_decision_engine import PermissionDecisionEngine
from .services.request_session_cache import cache_authenticated_session
from .services.session_seen_buffer import (
    queue_session_seen,
    start_session_seen_flush_worker,
    stop_session_seen_flush_worker,
)
from .services.unified_permission_engine import UnifiedPermissionRequest

settings = get_settings()

PUBLIC_API_PREFIX = "/api/public"
APPLICATION_API_PREFIX = "/api/app"
CONTROL_PLANE_API_PREFIX = "/api/control-plane"
PRODUCTION_LIKE_ENVS = frozenset(("production", "prod", "staging"))


def _production_like() -> bool:
    return settings.app_env.lower() in PRODUCTION_LIKE_ENVS


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
    session_id = request.cookies.get(settings.auth_session_cookie_name)
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
                "role": identity.role,
                "is_active": identity.is_active,
                "last_login_at": identity.last_login_at,
            }
        )


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


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=False if _production_like() else settings.app_debug,
    docs_url="/docs" if _docs_enabled() else None,
    redoc_url="/redoc" if _docs_enabled() else None,
    openapi_url="/openapi.json" if _docs_enabled() else None,
)


@app.on_event("startup")
def enforce_production_migration_safety() -> None:
    if _production_like():
        from .db.migration_safety import enforce_migration_safety
        from .db.session import engine

        enforce_migration_safety(engine, app_env=settings.app_env)
    start_session_seen_flush_worker()


@app.on_event("shutdown")
def flush_deferred_session_seen_updates() -> None:
    stop_session_seen_flush_worker()


def _is_control_plane_path(path: str) -> bool:
    return (
        path == CONTROL_PLANE_API_PREFIX
        or path.startswith(f"{CONTROL_PLANE_API_PREFIX}/")
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


@app.exception_handler(StarletteHTTPException)
async def sanitized_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
):
    detail = (
        _production_error_detail(request, exc.status_code)
        if _production_like()
        else exc.detail
    )
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
    del exc
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
    emit_event(
        event_type="control_plane.entry",
        module="C16",
        action=f"{request.method} {request.url.path}",
        source="backend",
        status="pending",
        context_id=audit.request_id,
        payload={"path": request.url.path, "method": request.method},
    )
    session_id = request.cookies.get(settings.auth_session_cookie_name)
    if session_id is None:
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

    with managed_read_session() as db:
        try:
            current_session = validate_session(
                db,
                session_id=session_id,
                audit=get_audit_context(request),
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

        queue_session_seen(current_session.auth_session.session_id_hash)
        cache_authenticated_session(
            request,
            session_id=session_id,
            current_session=current_session,
        )
        decision = PermissionDecisionEngine(
            db,
            request=request,
        ).decide_platform_metadata(
            UnifiedPermissionRequest(
                user_id=current_session.user.id,
                org_id=None,
                module_id="C16",
                action="admin",
                role=current_session.user.role,
                scope_type="global",
                scope_key="*",
                source="control_plane_isolation",
            )
        )
        request.state.control_plane_rbac_decision = decision
        if not decision.allowed:
            request.state.user_id = str(current_session.user.id)
            emit_event(
                event_type="control_plane.exit",
                module="C16",
                action=f"{request.method} {request.url.path}",
                source="backend",
                status="failed",
                context_id=audit.request_id,
                user_id=str(current_session.user.id),
                payload={
                    "reason": "permission_denied",
                    "role": current_session.user.role,
                    "decision_source": "PermissionDecisionEngine",
                    "denial_code": decision.denial_code,
                },
            )
            return _control_plane_denied_response(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden.",
            )
        request.state.user_id = str(current_session.user.id)

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

    payload = _auth_me_payload(request)
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

app.include_router(users_router, prefix=APPLICATION_API_PREFIX)
app.include_router(jobs_router, prefix=APPLICATION_API_PREFIX)
app.include_router(approval_router, prefix=APPLICATION_API_PREFIX)
app.include_router(artifacts_router, prefix=APPLICATION_API_PREFIX)
app.include_router(reviews_router, prefix=APPLICATION_API_PREFIX)
app.include_router(errors_router, prefix=APPLICATION_API_PREFIX)
app.include_router(memory_router, prefix=APPLICATION_API_PREFIX)
app.include_router(operation_logs_router, prefix=APPLICATION_API_PREFIX)
app.include_router(permissions_router, prefix=APPLICATION_API_PREFIX)
app.include_router(org_router, prefix=APPLICATION_API_PREFIX)
app.include_router(org_membership_router, prefix=APPLICATION_API_PREFIX)
app.include_router(contacts_router, prefix=APPLICATION_API_PREFIX)
app.include_router(conversations_router, prefix=APPLICATION_API_PREFIX)
app.include_router(cross_org_communication_router, prefix=APPLICATION_API_PREFIX)
app.include_router(friends_router, prefix=APPLICATION_API_PREFIX)
app.include_router(messages_router, prefix=APPLICATION_API_PREFIX)
app.include_router(attachments_router, prefix=APPLICATION_API_PREFIX)
app.include_router(module_binding_router, prefix=APPLICATION_API_PREFIX)
app.include_router(module_visibility_router, prefix=APPLICATION_API_PREFIX)
app.include_router(shared_module_router, prefix=APPLICATION_API_PREFIX)

app.include_router(modules_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(agents_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(workflows_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(foundation_demo_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(n8n_test_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(module_adapters_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(module_workflow_bindings_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(execution_providers_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(execution_prompts_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(external_dependencies_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(ai_execution_bindings_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(model_locks_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(capability_bindings_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(module_allocations_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(workflow_registry_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(webhook_gateway_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(payload_standardization_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(callback_handler_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(result_normalization_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(failure_handling_router, prefix=CONTROL_PLANE_API_PREFIX)
app.include_router(live_gate_router, prefix=CONTROL_PLANE_API_PREFIX)
