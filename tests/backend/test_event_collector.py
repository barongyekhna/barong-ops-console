import asyncio

from fastapi import Request
from starlette.responses import Response

from backend.app.middleware.event_collector import capture_audit_events
from backend.app.schemas.failure_handling import FailureHandlingRequest
from backend.app.services.event_collector import (
    clear_event_buffer,
    emit_event,
    get_event_buffer_snapshot,
)
from backend.app.services.failure_handling import handle_failure


def test_event_collector_schema_buffer_and_redaction() -> None:
    clear_event_buffer()

    event = emit_event(
        event_type="unit.test",
        module="system",
        action="unit.test",
        source="backend",
        status="success",
        context_id="ctx-unit-test",
        payload={"safe": "value", "api_key": "secret-value"},
    )

    assert event.context_id == "ctx-unit-test"
    assert event.payload["safe"] == "value"
    assert event.payload["api_key"] == "[redacted]"
    assert get_event_buffer_snapshot()[-1].event_id == event.event_id


def test_http_middleware_propagates_request_context(
) -> None:
    clear_event_buffer()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def call_next(request: Request) -> Response:
        return Response(status_code=204)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/public/health",
        "raw_path": b"/api/public/health",
        "query_string": b"",
        "headers": [(b"x-request-id", b"ctx-http-test")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    request = Request(scope, receive=receive)
    response = asyncio.run(capture_audit_events(request, call_next))

    assert response.status_code == 204
    assert response.headers["X-Request-ID"] == "ctx-http-test"

    events = get_event_buffer_snapshot()
    api_events = [
        event
        for event in events
        if event.context_id == "ctx-http-test"
        and event.event_type.startswith("api.")
    ]
    assert {event.event_type for event in api_events} == {
        "api.request.received",
        "api.response.completed",
    }


def test_failure_handler_emits_failure_and_retry_events() -> None:
    clear_event_buffer()

    request = FailureHandlingRequest(
        module="k.product_knowledge",
        workflow_id="workflow.products.sync",
        context_id="ctx.c15c.1234567890abcdef",
        failure_type="webhook_timeout",
        reason="Webhook did not respond inside the timeout window.",
        attempt=1,
        payload={"sku": "demo-sku"},
    )

    outcome = handle_failure(request)

    assert outcome.context_id == request.context_id
    events = [
        event
        for event in get_event_buffer_snapshot()
        if event.context_id == request.context_id
    ]
    assert "workflow.failure" in {event.event_type for event in events}
    assert "workflow.retry" in {event.event_type for event in events}
