import asyncio
import json
from inspect import iscoroutinefunction
from time import perf_counter

import pytest

from backend.app.api.routes.health import health
from backend.app.main import app

EXPECTED_HEALTH_PAYLOAD = {
    "status": "ok",
    "service": "barong-ops-console",
    "mode": "lightweight",
    "db": "not_checked",
}
HEALTH_ENDPOINTS = (
    "/health",
    "/api/backend/health",
    "/api/public/health",
)


def _get(path: str) -> tuple[int, dict[str, str], dict[str, str]]:
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))

    start_message = messages[0]
    body_message = messages[1]
    body = body_message.get("body", b"")
    assert isinstance(body, bytes)
    headers = {
        key.decode().lower(): value.decode()
        for key, value in start_message.get("headers", [])
    }
    return int(start_message["status"]), json.loads(body), headers


def test_health() -> None:
    status_code, payload, _headers = _get("/api/public/health")

    assert status_code == 200
    assert payload == EXPECTED_HEALTH_PAYLOAD

    sensitive_markers = ("secret", "token", "password", "key")
    assert not any(
        marker in field.lower()
        for field in payload
        for marker in sensitive_markers
    )


@pytest.mark.parametrize("path", HEALTH_ENDPOINTS)
def test_health_endpoints_are_lightweight(path: str) -> None:
    status_code, payload, headers = _get(path)

    assert status_code == 200
    assert payload == EXPECTED_HEALTH_PAYLOAD
    assert "x-request-id" not in headers
    assert "x-trace-id" not in headers
    assert "x-content-type-options" not in headers


@pytest.mark.parametrize("path", HEALTH_ENDPOINTS)
def test_health_bypasses_middleware_and_db(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("health endpoint reached a forbidden dependency")

    monkeypatch.setattr("backend.app.main.apply_security_headers", fail_if_called)
    monkeypatch.setattr("backend.app.main.capture_audit_events", fail_if_called)
    monkeypatch.setattr("backend.app.main.enforce_org_data_isolation", fail_if_called)
    monkeypatch.setattr("backend.app.main.enforce_permission_isolation", fail_if_called)
    monkeypatch.setattr("backend.app.main.org_context_middleware", fail_if_called)
    monkeypatch.setattr("backend.app.main._auth_me_payload", fail_if_called)
    monkeypatch.setattr("backend.app.main.managed_read_session", fail_if_called)
    monkeypatch.setattr("backend.app.main.emit_event", fail_if_called)
    monkeypatch.setattr(
        "backend.app.middleware.data_isolation.managed_read_session",
        fail_if_called,
    )
    monkeypatch.setattr(
        "backend.app.middleware.org_context.managed_read_session",
        fail_if_called,
    )
    monkeypatch.setattr(
        "backend.app.middleware.permission.managed_read_session",
        fail_if_called,
    )

    status_code, payload, _headers = _get(path)

    assert status_code == 200
    assert payload == EXPECTED_HEALTH_PAYLOAD


@pytest.mark.parametrize("path", ("/health", "/api/backend/health"))
def test_health_endpoint_latency_target(path: str) -> None:
    _get(path)

    started_at = perf_counter()
    status_code, payload, _headers = _get(path)
    elapsed_ms = (perf_counter() - started_at) * 1000

    assert status_code == 200
    assert payload == EXPECTED_HEALTH_PAYLOAD
    assert elapsed_ms < 50


def test_health_handler_is_synchronous() -> None:
    assert not iscoroutinefunction(health)
    assert health().__class__.__name__ == "HealthResponse"
