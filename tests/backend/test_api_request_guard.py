from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.services.api_request_guard import (
    enter_heavy_api_request,
    exit_heavy_api_request,
    reset_api_request_guard_state,
)


def request_for(path: str = "/api/app/operation-logs", query: str = "limit=50&offset=0"):
    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        cookies={"barong_ops_session": "session-token"},
        method="GET",
        url=SimpleNamespace(path=path, query=query),
    )


def settings():
    return SimpleNamespace(auth_session_cookie_name="barong_ops_session")


def test_api_request_guard_rejects_parallel_duplicate_request() -> None:
    reset_api_request_guard_state()
    first = enter_heavy_api_request(
        request_for(),
        settings=settings(),
        scope="operation_logs.list",
    )

    with pytest.raises(HTTPException) as exc_info:
        enter_heavy_api_request(
            request_for(),
            settings=settings(),
            scope="operation_logs.list",
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Duplicate request already in progress."

    exit_heavy_api_request(first)
    second = enter_heavy_api_request(
        request_for(),
        settings=settings(),
        scope="operation_logs.list",
    )
    exit_heavy_api_request(second)


def test_api_request_guard_throttles_session_burst() -> None:
    reset_api_request_guard_state()

    first = enter_heavy_api_request(
        request_for(query="limit=50&offset=0"),
        settings=settings(),
        scope="operation_logs.list",
        limit=2,
        window_seconds=10,
    )
    exit_heavy_api_request(first)
    second = enter_heavy_api_request(
        request_for(query="limit=50&offset=50"),
        settings=settings(),
        scope="operation_logs.list",
        limit=2,
        window_seconds=10,
    )
    exit_heavy_api_request(second)

    with pytest.raises(HTTPException) as exc_info:
        enter_heavy_api_request(
            request_for(query="limit=50&offset=100"),
            settings=settings(),
            scope="operation_logs.list",
            limit=2,
            window_seconds=10,
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Too many requests for this session."
