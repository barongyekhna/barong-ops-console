from __future__ import annotations

from time import perf_counter

from fastapi import Request

from ..core.api_classification import is_lightweight_control_plane_path
from ..core.auth_paths import is_auth_login_path, is_auth_me_path
from ..services.event_collector import (
    classify_module_from_path,
    emit_event,
    normalize_context_id,
    reset_current_event_context,
    set_current_event_context,
)

CONTEXT_HEADER_CANDIDATES = ("x-request-id", "x-trace-id")
REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"


def ensure_request_context_id(request: Request) -> str:
    existing = getattr(request.state, "context_id", None)
    if existing:
        return normalize_context_id(str(existing))

    header_value = None
    for header in CONTEXT_HEADER_CANDIDATES:
        header_value = request.headers.get(header)
        if header_value:
            break

    context_id = normalize_context_id(header_value)
    request.state.context_id = context_id
    return context_id


def set_request_context_id(request: Request, context_id: str) -> str:
    normalized = normalize_context_id(context_id)
    request.state.context_id = normalized
    set_current_event_context(context_id=normalized)
    return normalized


def request_trace_root_id(request: Request, fallback_context_id: str) -> str:
    root_request_id = getattr(request.state, "request_id", None)
    if root_request_id:
        return normalize_context_id(str(root_request_id))
    trace_id = getattr(request.state, "trace_id", None)
    if trace_id:
        return normalize_context_id(str(trace_id))
    return fallback_context_id


async def capture_audit_events(request: Request, call_next):
    if (
        is_auth_me_path(request.url.path)
        or is_auth_login_path(request.url.path)
        or is_lightweight_control_plane_path(request.url.path)
    ):
        return await call_next(request)

    context_id = ensure_request_context_id(request)
    tokens = set_current_event_context(context_id=context_id)
    module = classify_module_from_path(request.url.path)
    started_at = perf_counter()

    emit_event(
        event_type="api.request.received",
        module=module,
        action=f"{request.method} {request.url.path}",
        source="backend",
        status="pending",
        context_id=context_id,
        org_id=getattr(request.state, "org_id", None),
        payload={
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
        },
        metadata={"client": request.client.host if request.client else None},
    )

    try:
        response = await call_next(request)
    except Exception:
        final_context_id = ensure_request_context_id(request)
        trace_root_id = request_trace_root_id(request, final_context_id)
        emit_event(
            event_type="api.response.completed",
            module=module,
            action=f"{request.method} {request.url.path}",
            source="backend",
            status="failed",
            context_id=trace_root_id,
            user_id=getattr(request.state, "user_id", None),
            workflow_id=getattr(request.state, "workflow_id", None),
            org_id=getattr(request.state, "org_id", None),
            latency_ms=(perf_counter() - started_at) * 1000,
            payload={
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
            },
            metadata={"exception": "unhandled"},
        )
        reset_current_event_context(tokens)
        raise

    final_context_id = ensure_request_context_id(request)
    trace_root_id = request_trace_root_id(request, final_context_id)
    response.headers[REQUEST_ID_HEADER] = trace_root_id
    response.headers[TRACE_ID_HEADER] = trace_root_id
    emit_event(
        event_type="api.response.completed",
        module=module,
        action=f"{request.method} {request.url.path}",
        source="backend",
        status="success" if response.status_code < 400 else "failed",
        context_id=trace_root_id,
        user_id=getattr(request.state, "user_id", None),
        product_key=getattr(request.state, "product_key", None),
        workflow_id=getattr(request.state, "workflow_id", None),
        org_id=getattr(request.state, "org_id", None),
        latency_ms=(perf_counter() - started_at) * 1000,
        payload={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
        },
    )
    reset_current_event_context(tokens)
    return response
