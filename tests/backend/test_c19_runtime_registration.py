from __future__ import annotations

from fastapi import Request

from backend.app.main import app
from backend.app.middleware.data_isolation import (
    _is_data_isolation_exempt_path,
    _requires_org_context as data_isolation_requires_org_context,
)
from backend.app.middleware.org_context import (
    _requires_org_context as request_requires_org_context,
)


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def _registered_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }


def test_c19_registers_only_durable_control_runtime_routes() -> None:
    routes = _registered_routes()
    expected = {
        ("GET", "/api/app/c19/directory"),
        ("GET", "/api/app/c19/profiles/{user_id}"),
        ("GET", "/api/app/c19/friend-requests"),
        ("POST", "/api/app/c19/friend-requests"),
        ("POST", "/api/app/c19/friend-requests/{request_id}/accept"),
        ("POST", "/api/app/c19/friend-requests/{request_id}/reject"),
        ("POST", "/api/app/c19/friend-requests/{request_id}/cancel"),
        ("GET", "/api/app/c19/friends"),
        ("DELETE", "/api/app/c19/friends/{user_id}"),
        ("GET", "/api/app/c19/blocks"),
        ("POST", "/api/app/c19/blocks/{user_id}"),
        ("DELETE", "/api/app/c19/blocks/{user_id}"),
        ("GET", "/api/app/c19/conversations"),
        ("POST", "/api/app/c19/conversations/direct"),
        ("GET", "/api/app/c19/conversations/{conversation_id}"),
        ("GET", "/api/app/c19/conversations/{conversation_id}/settings"),
        ("PATCH", "/api/app/c19/conversations/{conversation_id}/settings"),
        ("POST", "/api/app/c19/groups"),
        ("PATCH", "/api/app/c19/groups/{conversation_id}"),
        ("POST", "/api/app/c19/groups/{conversation_id}/members"),
        ("DELETE", "/api/app/c19/groups/{conversation_id}/members/{user_id}"),
        ("POST", "/api/app/c19/groups/{conversation_id}/leave"),
        ("POST", "/api/app/c19/groups/{conversation_id}/transfer-owner"),
        ("DELETE", "/api/app/c19/groups/{conversation_id}"),
        ("POST", "/api/app/c19/conversations/{conversation_id}/messages"),
        ("GET", "/api/app/c19/conversations/{conversation_id}/messages"),
        ("POST", "/api/app/c19/conversations/{conversation_id}/delivered"),
        ("POST", "/api/app/c19/conversations/{conversation_id}/read"),
        ("GET", "/api/app/c19/conversations/{conversation_id}/unread"),
        ("GET", "/api/app/c19/conversations/{conversation_id}/resume"),
        ("GET", "/api/app/c19/events"),
        ("GET", "/api/app/c19/events/tail"),
    }
    assert expected <= routes

    forbidden_c19_segments = (
        "/attachments",
        "/moments",
        "/storage",
        "/providers",
        "/vps",
        "/calls",
    )
    assert not any(
        path.startswith("/api/app/c19")
        and any(segment in path for segment in forbidden_c19_segments)
        for _, path in routes
    )


def test_legacy_process_local_c19_routes_are_not_mounted() -> None:
    routes = _registered_routes()
    legacy_prefixes = (
        "/api/app/contacts",
        "/api/app/conversations",
        "/api/app/comm/cross-org",
        "/api/app/friends",
        "/api/app/messages",
        "/api/app/attachments",
    )
    assert not any(
        path == prefix or path.startswith(f"{prefix}/")
        for _, path in routes
        for prefix in legacy_prefixes
    )


def test_c19_global_prefix_does_not_require_a_single_org_context() -> None:
    for path in (
        "/api/app/c19",
        "/api/app/c19/directory",
        "/api/app/c19/conversations/conv_0123456789abcdef",
    ):
        request = _request(path)
        assert request_requires_org_context(request) is False
        assert data_isolation_requires_org_context(request) is False
        assert _is_data_isolation_exempt_path(path) is True

    nearby_non_c19_path = "/api/app/c190/directory"
    request = _request(nearby_non_c19_path)
    assert request_requires_org_context(request) is True
    assert data_isolation_requires_org_context(request) is True
    assert _is_data_isolation_exempt_path(nearby_non_c19_path) is False
