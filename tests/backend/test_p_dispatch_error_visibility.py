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
    # 消毒后的文案 2026-08-31 改成了中文（整站中文界面里冒英文套话，而且
    # 三种不同的失败说同一句话）。这条测试的本意是「非白名单路径的 detail
    # 必须被换掉、内部细节不外泄」——所以断言的重点是：原始 detail 里的
    # 内容一个字都没漏出来，而不是那句话本身长什么样。
    body = json.loads(response.body)
    assert set(body) == {"detail"}
    assert body["detail"] == "和现有数据冲突了（可能已经存在，或刚被别人改过）。请刷新后重试。"
    assert "hidden" not in response.body.decode()
    assert "blockers" not in response.body.decode()
