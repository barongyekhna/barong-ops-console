"""K 外部精修通道 —— 真协议冒烟:用 MCP Streamable HTTP 的 JSON-RPC 打 build_app()。

守的是「Codex 连上来会不会炸」这一层:initialize → tools/list(5 个工具)→
tools/call(k_get_image_brief)→ 错 token 401 → 签名文件链接能取到参考图字节。
业务断言在 test_k_mcp_channel_integration.py,这里只看协议与鉴权接线。

跑法(铁律):scripts/run_backend_tests.sh integration
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select, text

from backend.app.db.session import SessionLocal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.k_mcp]

_HEADERS_BASE = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _rpc(client, token: str, method: str, params: dict | None, rpc_id: int | None):
    from backend.app.mcp.k_images_server import MCP_PATH

    body: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if rpc_id is not None:
        body["id"] = rpc_id
    return client.post(
        MCP_PATH,
        content=json.dumps(body),
        headers={**_HEADERS_BASE, "Authorization": f"Bearer {token}"},
    )


def test_mcp_protocol_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.testclient import TestClient

    from tests.backend.test_k_mcp_channel_integration import _seed

    media_root = tmp_path / "k-media"
    monkeypatch.setenv("K_PRODUCT_MEDIA_STORAGE_DIR", str(media_root))
    bot_username, sku = _seed(media_root)

    # 个人钥匙:owner 登录控制台 → 在「设置」里给自己生成一把 → 拿它当 Bearer
    from fastapi.testclient import TestClient as ApiClient

    from backend.app.main import app as console_app
    from tests.backend.test_k_mcp_channel_integration import OWNER_PASSWORD

    owner_username = "mcp_owner_" + bot_username.removeprefix("codex_painter_")
    with ApiClient(console_app) as api:
        login = api.post(
            "/api/public/auth/login",
            json={"username": owner_username, "password": OWNER_PASSWORD},
        )
        assert login.status_code == 200, login.text
        session = login.json()["session_token"]
        headers = {"Authorization": f"Bearer {session}"}
        before = api.get("/api/app/profile/me/mcp", headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()["summary"]["has_token"] is False
        issued = api.post("/api/app/profile/me/mcp/reset", headers=headers)
        assert issued.status_code == 200, issued.text
        token = issued.json()["token"]
        assert token.startswith("bk_") and "setup.sh | bash -s -- " + token in issued.json()["setup_command_mac"]
        after = api.get("/api/app/profile/me/mcp", headers=headers).json()
        assert after["summary"]["has_token"] is True and after["summary"]["token_prefix"] == token[:12]
        # 列表/详情只露前缀,不露明文
        listed = api.get("/api/app/users?limit=100", headers=headers)
        assert listed.status_code == 200, listed.text
        me = next(u for u in listed.json()["items"] if u["username"] == owner_username)
        assert me["mcp_token"]["token_prefix"] == token[:12]
        assert token not in listed.text
        # 「接入钥匙」操作记录:刚才的 reset 要能看到,且 id 已解析成用户名
        log = api.get("/api/app/users/mcp-token-log?limit=20", headers=headers)
        assert log.status_code == 200, log.text
        mine = [row for row in log.json()["items"] if row["target_username"] == owner_username]
        assert mine and mine[0]["action"] in ("mcp_token.issue", "mcp_token.reset")
        assert mine[0]["actor_username"] == owner_username
        assert "avatar_url" in me

    monkeypatch.setenv("K_MCP_FILE_SIGNING_KEY", "protocol-smoke-signing-key-" + "x" * 32)
    monkeypatch.setenv("K_MCP_PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("K_MCP_ALLOWED_HOSTS", "testserver,127.0.0.1:*")

    from backend.app.mcp import k_images_server as srv

    srv.CONFIG = srv._Config()
    app = srv.build_app()

    with TestClient(app) as client:
        assert client.get(f"{srv.MCP_PATH}/health").json() == {"ok": True, "service": "k-mcp"}
        # 错 token → 401,协议层根本进不去
        assert client.post(srv.MCP_PATH, content="{}", headers=_HEADERS_BASE).status_code == 401

        init = _rpc(
            client,
            token,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
            1,
        )
        assert init.status_code == 200, init.text
        payload = init.json()
        assert payload["result"]["serverInfo"]["name"] == "barong-k-images"
        assert "instructions" in payload["result"]
        # 无状态模式:initialized 通知照收(202),之后每个请求独立
        notified = _rpc(client, token, "notifications/initialized", None, None)
        assert notified.status_code in (200, 202), notified.text

        tools = _rpc(client, token, "tools/list", {}, 2)
        assert tools.status_code == 200, tools.text
        names = sorted(t["name"] for t in tools.json()["result"]["tools"])
        assert names == [
            "k_get_image_brief",
            "k_get_reference_images",
            "k_get_submission_status",
            "k_list_products_awaiting_images",
            "k_submit_image",
        ]

        listing = _rpc(
            client, token, "tools/call",
            {"name": "k_list_products_awaiting_images", "arguments": {"limit": 50}}, 3,
        )
        assert listing.status_code == 200, listing.text
        result = listing.json()["result"]
        assert result.get("isError") is not True
        listed = json.loads(result["content"][0]["text"])
        assert any(item["sku"] == sku for item in listed)

        brief = _rpc(
            client, token, "tools/call",
            {"name": "k_get_image_brief", "arguments": {"sku": sku}}, 4,
        )
        assert brief.status_code == 200, brief.text
        brief_text = brief.json()["result"]["content"][0]["text"]
        assert f"# Image brief — {sku}" in brief_text
        assert "Reference image download URLs" in brief_text
        # 签名链接能直接取到参考图字节(给 Codex 的 shell curl 用),无需 Bearer
        url_line = next(line for line in brief_text.splitlines() if "/mcp/k-images/files/" in line)
        file_url = url_line.split(": ", 1)[-1].strip()
        parsed = urlparse(file_url)
        fetched = client.get(f"{parsed.path}?{parsed.query}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.headers["content-type"].startswith("image/")
        assert len(fetched.content) > 100
        # 篡改签名 → 403
        tampered = client.get(f"{parsed.path}?{parsed.query[:-1]}0")
        assert tampered.status_code == 403

        refs = _rpc(
            client, token, "tools/call",
            {"name": "k_get_reference_images", "arguments": {"sku": sku}}, 5,
        )
        assert refs.status_code == 200, refs.text
        blocks = refs.json()["result"]["content"]
        assert [b["type"] for b in blocks] == ["text", "image"]
        assert blocks[1]["mimeType"].startswith("image/")

        unknown = _rpc(
            client, token, "tools/call",
            {"name": "k_get_image_brief", "arguments": {"sku": "NOPE-000"}}, 6,
        )
        assert unknown.status_code == 200
        assert "PRODUCT_NOT_FOUND" in unknown.json()["result"]["content"][0]["text"]

        # 交稿归属 = 登录的这个人(不再是机器人)
        import base64

        from tests.backend.test_k_mcp_channel_integration import _png

        submit = _rpc(
            client, token, "tools/call",
            {"name": "k_submit_image", "arguments": {
                "sku": sku, "position": 2,
                "image_base64": base64.b64encode(_png((800, 600), "green")).decode(),
            }}, 7,
        )
        assert submit.status_code == 200, submit.text
        submitted = json.loads(submit.json()["result"]["content"][0]["text"])
        assert submitted.get("error") is None, submitted
        assert submitted["submitted_by"] == owner_username
        with SessionLocal() as db:
            who = db.execute(
                text("SELECT metadata_json->>'submitted_by_username' FROM k_product_knowledge_media_assets WHERE id = :id"),
                {"id": submitted["asset_id"]},
            ).scalar()
            assert who == owner_username

        # 管理者(自己是 owner)停用自己的钥匙 → 立刻 401
        with SessionLocal() as db:
            from backend.app.models.user import User
            from backend.app.services import mcp_token_service
            from backend.app.services.auth_service import AuditContext

            owner = db.scalars(select(User).where(User.username == owner_username)).first()
            mcp_token_service.disable_token_for_user(
                db, user_id=owner.id, actor=owner,
                audit=AuditContext(request_id="t", ip_address=None, user_agent=None),
            )
        assert _rpc(client, token, "tools/list", {}, 8).status_code == 401
