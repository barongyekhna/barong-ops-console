"""MCP 个人钥匙 · 控制台接入面守卫(免 DB)。

2026-08-28 拍板:每个真人账号一把钥匙、认人、可停、跨模块通用;全局钥匙退役。
这里钉死:端点挂在哪、谁能调、明文只回一次、装机脚本不含秘密、前后端指令文案同源。
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_global_token_endpoint_is_gone_and_per_user_endpoints_exist() -> None:
    import importlib

    from backend.app import main
    from backend.app.api.routes import profile, users

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("backend.app.modules.k_series.product_knowledge.mcp_setup_router")
    assert "k_mcp_setup_router" not in inspect.getsource(main)

    profile_src = inspect.getsource(profile)
    assert '@router.get("/me/mcp"' in profile_src
    assert '@router.post("/me/mcp/reset"' in profile_src
    # 本人端点只要登录(get_current_user),不要 owner
    assert "require_owner" not in profile_src

    users_src = inspect.getsource(users)
    for route in ("mcp-token-reset", "mcp-token-disable", "mcp-token-enable"):
        assert f'"/{{user_id}}/{route}"' in users_src
    # 管理别人的钥匙 = 用户管理同一道门
    for fn in (users.user_mcp_token_reset, users.user_mcp_token_disable, users.user_mcp_token_enable):
        assert "Depends(require_user_manager)" in inspect.getsource(fn)


def test_service_enforces_manage_gate_and_self_reset_cannot_revive_disabled() -> None:
    from backend.app.services import mcp_token_service as svc

    for fn in (svc.reset_token_for_user, svc.disable_token_for_user, svc.enable_token_for_user):
        assert "_ensure_actor_can_manage_user(actor, user)" in inspect.getsource(fn)
    own = inspect.getsource(svc.reset_own_token)
    assert "TOKEN_STATUS_DISABLED" in own and "raise" in own
    # 认人:必须同时看钥匙状态、账号状态、机器人标记
    resolve = inspect.getsource(svc.resolve_user_by_token)
    assert "row.status != TOKEN_STATUS_ACTIVE" in resolve
    assert "not user.is_active or user.is_bot" in resolve
    assert "LAST_USED_WRITE_THROTTLE" in resolve


def test_user_create_mints_token_and_returns_secret_once() -> None:
    from backend.app.api.routes import users
    from backend.app.schemas.user import McpTokenIssueResponse, UserCreateResponse

    src = inspect.getsource(users.user_create)
    assert "mcp_token_service.mint_token(" in src
    assert "if not user.is_bot:" in src
    assert "mcp_token_secret" in UserCreateResponse.model_fields
    assert {"token", "setup_command_mac", "setup_command_windows"} <= set(
        McpTokenIssueResponse.model_fields
    )


def test_setup_scripts_are_secret_free_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.mcp import k_images_server as srv

    sh = srv._render_setup_script(srv.SETUP_SH)
    ps = srv._render_setup_script(srv.SETUP_PS1)
    for text in (sh, ps):
        assert "__URL__" not in text and "__VAR__" not in text and "__NAME__" not in text
        assert "barong_k_images" in text and "BARONG_K_MCP_TOKEN" in text
        assert "bk_" not in text  # 脚本里没有任何真钥匙
    assert "grep -q" in sh and "已有" in sh
    assert "Select-String" in ps
    app_src = inspect.getsource(srv.build_app)
    assert "setup.sh" in app_src and "setup.ps1" in app_src
    assert "TokenGuard(" in app_src


def test_codex_prompt_text_matches_between_backend_and_frontend() -> None:
    """前端 codexPromptForSku 与后端简报说明同源:改一处必须改另一处。"""
    from pathlib import Path

    api_ts = Path("frontend/src/modules/k/product-knowledge/api.ts").read_text(encoding="utf-8")
    for fragment in (
        "k_get_image_brief",
        "k_get_reference_images",
        "k_submit_image",
        "k_get_submission_status",
        "缺哪位出哪位",
    ):
        assert fragment in api_ts
    # 旧的 owner 专属端点客户端已删,前端改走本人 profile 端点
    assert "getMcpSetup" not in api_ts
    route_ts = Path("frontend/src/app/api/backend/[...path]/route.ts").read_text(encoding="utf-8")
    assert '"mcp-token-reset"' in route_ts and '"mcp-token-disable"' in route_ts
    assert 'path[2] === "mcp"' in route_ts
    assert 'path[1] === "mcp" && path[2] === "setup"' not in route_ts


def test_mcp_keys_overview_endpoint_and_frontend_registration() -> None:
    """「接入钥匙」模块:日志端点守门 + 静态路径先于 /{user_id} + 前端六处登记缺一不可。"""
    from pathlib import Path

    from backend.app.api.routes import users
    from backend.app.schemas.user import McpTokenLogResponse, UserResponse

    src = inspect.getsource(users.users_mcp_token_log)
    assert "Depends(require_user_manager)" in src
    assert 'like("mcp_token.%")' in src
    paths = [route.path for route in users.router.routes]
    assert paths.index("/users/mcp-token-log") < paths.index("/users/{user_id}")
    assert "avatar_url" in UserResponse.model_fields
    assert "items" in McpTokenLogResponse.model_fields

    fe = Path("frontend/src")
    assert (fe / "app/(console)/mcp-keys/page.tsx").exists()
    assert '"admin.mcp_keys"' in (fe / "lib/navigation.ts").read_text(encoding="utf-8")
    assert '"admin.mcp_keys"' in (fe / "components/capability-sidebar-engine.tsx").read_text(encoding="utf-8")
    state = (fe / "lib/frontend-capability-state.ts").read_text(encoding="utf-8")
    assert state.count('"admin.mcp_keys"') >= 4  # groups/labels/order + 隐藏判定
    assert '"admin.mcp_keys"' in (fe / "lib/i18n.ts").read_text(encoding="utf-8")
    assert "isMcpKeysRoute" in (fe / "components/permission-route-guard.tsx").read_text(encoding="utf-8")
    assert 'path[1] === "mcp-token-log"' in (fe / "app/api/backend/[...path]/route.ts").read_text(encoding="utf-8")
