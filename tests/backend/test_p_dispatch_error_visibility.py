from __future__ import annotations

import asyncio
import json

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

from backend.app import main


pytestmark = pytest.mark.unit


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "root_path": "",
            "scheme": "https",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 443),
        }
    )


def _production_response(
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: str,
    detail: object,
):
    monkeypatch.setattr(main, "_production_like", lambda: True)
    return asyncio.run(
        main.sanitized_http_exception_handler(
            _request(path),
            HTTPException(status_code=409, detail=detail),
        )
    )


def test_production_preserves_exact_p_publish_gate_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = {"ready": False, "blockers": ["价格缺失", "未绑定类目"]}

    response = _production_response(
        monkeypatch,
        path="/api/app/p/products/00000000-0000-4000-8000-000000000000/dispatch",
        detail=detail,
    )

    assert response.status_code == 409
    assert json.loads(response.body) == {"detail": detail}


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        (
            "/api/app/k/products/00000000-0000-4000-8000-000000000000",
            {"ready": False, "blockers": ["价格缺失"]},
        ),
        (
            "/api/app/p/products/00000000-0000-4000-8000-000000000000/dispatch",
            {"ready": "false", "blockers": ["价格缺失"]},
        ),
        (
            "/api/app/p/products/00000000-0000-4000-8000-000000000000/dispatch",
            {"ready": False, "blockers": ["价格缺失"], "debug": "hidden"},
        ),
    ],
)
def test_production_still_sanitizes_non_whitelisted_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    detail: object,
) -> None:
    response = _production_response(monkeypatch, path=path, detail=detail)

    assert response.status_code == 409
    assert json.loads(response.body) == {"detail": "Request conflict."}
