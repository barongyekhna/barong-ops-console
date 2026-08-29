"""K 外部精修通道(MCP)—— 免 DB / 免 AI 的守卫。

2026-08-26:Codex 桌面版(gpt-image-2 + 看图迭代)实测把 worker 管线一直画错的
几何/物理都做对了,于是给 K 加一条「有眼睛的精修通道」。这里钉死三件最容易
悄悄坏掉的事:
1. 外部拿到的提示词和 worker 用的是同一个函数(build_render_prompt),保真块永远最后;
2. MCP 交的稿不吃 24h 惰性回收、不被 worker 自动重渲盖掉;
3. 协议层鉴权 fail-closed(错 token 401),签名文件链接改一位就 403。
"""

from __future__ import annotations

import base64
import inspect
import io
import time

import pytest

pytestmark = pytest.mark.unit


def _png_bytes(size: tuple[int, int] = (64, 48), color: str = "red") -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


# --- 1. 提示词同源 ----------------------------------------------------------------


def test_enqueue_and_external_brief_share_build_render_prompt() -> None:
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj
    from backend.app.modules.k_series.product_knowledge import mcp_channel

    assert "build_render_prompt(" in inspect.getsource(irj.enqueue_image_render_jobs)
    assert "build_render_prompt(" in inspect.getsource(mcp_channel.build_external_brief)
    assert "build_render_prompt(" in inspect.getsource(mcp_channel.submit_rendered_image)
    # 位号/主图/白底副图校验也同源:外部看到的位号 == worker 会渲染的位号
    assert "resolve_render_specs(" in inspect.getsource(irj.enqueue_image_render_jobs)
    assert "resolve_render_specs(" in inspect.getsource(mcp_channel.build_external_brief)


def test_build_render_prompt_block_order_per_role() -> None:
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj
    from backend.app.modules.k_series.product_knowledge.brand_guard import (
        BRAND_REMOVAL_PROMPT_BLOCK,
    )

    context = irj.RenderPromptContext(
        brand_terms=("acmebrand",),
        festival_block=" FESTIVAL-BLOCK.",
        operating_constraint_block=" OPERATING-BLOCK.",
    )
    instruction = {"style_block": "STYLE BLOCK: bright"}

    main = irj.build_render_prompt(
        {"role": "main", "prompt": "white bg hero"},
        instruction,
        asset_role=irj.ASSET_ROLE_MAIN,
        context=context,
        position=1,
    )
    assert main.startswith("white bg hero")
    assert BRAND_REMOVAL_PROMPT_BLOCK in main
    assert "acmebrand" in main
    assert irj.HOUSE_STYLE_BLOCK in main
    assert irj.NON_MAIN_EVIDENCE_BLOCK not in main
    assert "FESTIVAL-BLOCK" not in main  # 主图永远纯净
    assert "OPERATING-BLOCK" not in main  # 白底主图不展示工作状态
    assert main.endswith(irj.PRODUCT_FIDELITY_BLOCK)

    scene = irj.build_render_prompt(
        {"role": "proof_scene", "prompt": "pump in a bucket"},
        instruction,
        asset_role=irj.ASSET_ROLE_GALLERY,
        context=context,
        position=2,
        rejection_hint="pump drawn on dry ground",
    )
    assert irj.HOUSE_STYLE_BLOCK not in scene
    assert irj.NON_MAIN_EVIDENCE_BLOCK in scene
    assert irj.PROOF_SCENE_BLOCK in scene
    assert "REJECTED by review" in scene and "dry ground" in scene
    assert "FESTIVAL-BLOCK" in scene
    assert scene.index("OPERATING-BLOCK") < scene.index(irj.PRODUCT_FIDELITY_BLOCK)
    assert scene.endswith(irj.PRODUCT_FIDELITY_BLOCK)

    colorway = irj.build_render_prompt(
        {"role": "detail", "prompt": "blue variant", "variant_color": "blue"},
        instruction,
        asset_role=irj.ASSET_ROLE_GALLERY,
        context=context,
        position=101,
    )
    assert "FESTIVAL-BLOCK" not in colorway  # 颜色变体主图也纯净

    with pytest.raises(irj.KImageRenderError) as excinfo:
        irj.build_render_prompt(
            {"role": "detail"},
            {},
            asset_role=irj.ASSET_ROLE_GALLERY,
            context=context,
            position=3,
        )
    assert excinfo.value.code == "IMAGE_PROMPT_MISSING"


def test_resolve_asset_role_matches_legacy_rules() -> None:
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    assert irj.resolve_asset_role(irj.PLACEMENT_DESCRIPTION, 1, 1) == irj.ASSET_ROLE_DESCRIPTION
    assert irj.resolve_asset_role(irj.PLACEMENT_GALLERY, 1, 1) == irj.ASSET_ROLE_MAIN
    assert irj.resolve_asset_role(irj.PLACEMENT_GALLERY, 2, 1) == irj.ASSET_ROLE_GALLERY


# --- 2. 外部稿的保护 --------------------------------------------------------------


def test_external_submissions_are_exempt_from_staged_gc_and_auto_rerender() -> None:
    from backend.app.modules.k_series.product_knowledge import (
        generation_jobs,
        image_render_jobs as irj,
        mcp_channel,
    )

    assert irj.EXTERNAL_SUBMISSION_TAG == "mcp"
    gc_src = inspect.getsource(irj.cleanup_stale_staged)
    assert "submitted_via" in gc_src and ":external" in gc_src
    # 必须仍按 render_pipeline 标记筛,否则三处(列表/保存/审查)都看不见外部稿
    assert "render_pipeline" in gc_src

    audit_src = inspect.getsource(generation_jobs._run_brand_audit_job)
    assert "EXTERNAL_SUBMISSION_TAG" in audit_src
    skip_at = audit_src.index("EXTERNAL_SUBMISSION_TAG")
    hint_at = audit_src.index("hints[position] =")
    assert skip_at < hint_at, "外部稿的跳过必须发生在写 hints 之前"

    submit_src = inspect.getsource(mcp_channel.submit_rendered_image)
    # 走 worker 同一条入库路径,标记经 plate_meta 合并进 metadata_json
    assert "_store_render_asset(" in submit_src
    assert '"submitted_via": EXTERNAL_SUBMISSION_TAG' in submit_src
    # 交稿后立刻排审查,而且只在有文案时(和 _maybe_finalize_batch 同条件)
    assert 'job_type="brand_audit"' in submit_src
    assert "if product.marketing_copy_json:" in submit_src
    # 绝不在这里把 staged 改成 available(人的命令高于程序)
    assert '"available"' not in submit_src


def test_submission_validation_rejects_garbage_and_accepts_png() -> None:
    from backend.app.modules.k_series.product_knowledge import mcp_channel

    with pytest.raises(mcp_channel.KMcpChannelError) as excinfo:
        mcp_channel._validate_image_bytes(b"")
    assert excinfo.value.code == "IMAGE_EMPTY"

    with pytest.raises(mcp_channel.KMcpChannelError) as excinfo:
        mcp_channel._validate_image_bytes(b"not an image at all")
    assert excinfo.value.code == "IMAGE_UNREADABLE"

    with pytest.raises(mcp_channel.KMcpChannelError) as excinfo:
        mcp_channel._validate_image_bytes(b"x" * (mcp_channel.MAX_SUBMISSION_BYTES + 1))
    assert excinfo.value.code == "IMAGE_TOO_LARGE"

    assert mcp_channel._validate_image_bytes(_png_bytes()) == ("png", 64, 48)


# --- 3. 协议层鉴权(个人钥匙) ----------------------------------------------------


def test_token_service_hash_only_and_bots_excluded() -> None:
    from backend.app.services import mcp_token_service as svc

    token = svc.generate_token()
    assert token.startswith("bk_") and len(token) > 40
    assert svc.hash_token(token) != token and len(svc.hash_token(token)) == 64
    assert svc.display_prefix(token) == token[:12]
    # resolve 对形状不对的输入直接 None,不查库
    assert svc.resolve_user_by_token(None, "not-a-token") is None  # type: ignore[arg-type]
    assert svc.resolve_user_by_token(None, "bk_short") is None  # type: ignore[arg-type]
    src = inspect.getsource(svc.mint_token)
    assert "is_bot" in src and "McpTokenNotForBotsError" in src
    # 明文绝不落库:模型没有明文列
    from backend.app.models.mcp_access_token import McpAccessToken

    assert not any("plain" in c.name or c.name == "token" for c in McpAccessToken.__table__.columns)


def _guarded_app(resolver):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, PlainTextResponse
    from starlette.routing import Route

    from backend.app.mcp import auth
    from backend.app.mcp.k_images_server import MCP_PATH

    async def whoami(request):
        return JSONResponse({"user_id": getattr(request.state, auth.STATE_USER_ID, None)})

    async def ok(_request):
        return PlainTextResponse("ok")

    inner = Starlette(
        routes=[
            Route(MCP_PATH, whoami, methods=["POST", "GET"]),
            Route(f"{MCP_PATH}/health", ok, methods=["GET"]),
            Route(f"{MCP_PATH}/files/{{asset_id}}", ok, methods=["GET"]),
        ]
    )
    return auth.TokenGuard(inner, open_prefixes=(f"{MCP_PATH}/files/", f"{MCP_PATH}/health"))


def test_token_guard_fails_closed_and_passes_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from starlette.testclient import TestClient

    from backend.app.mcp import auth
    from backend.app.mcp.k_images_server import MCP_PATH

    good = "bk_" + "g" * 43

    def fake_resolve(db, presented, *, ip_address=None):
        return SimpleNamespace(id=42, username="alice") if presented == good else None

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def commit(self):
            pass

    monkeypatch.setattr(auth, "resolve_user_by_token", fake_resolve)
    monkeypatch.setattr(auth, "SessionLocal", lambda: FakeSession())
    client = TestClient(_guarded_app(fake_resolve))
    assert client.post(MCP_PATH).status_code == 401
    assert client.post(MCP_PATH, headers={"Authorization": "Bearer bk_wrong"}).status_code == 401
    ok = client.post(MCP_PATH, headers={"Authorization": f"Bearer {good}"})
    assert ok.status_code == 200 and ok.json() == {"user_id": 42}
    assert client.post(MCP_PATH, headers={"Authorization": f"bearer {good}"}).status_code == 200
    # 存活探针与签名文件路径不要 Bearer(它们各有自己的保护)
    assert client.get(f"{MCP_PATH}/health").status_code == 200
    assert client.get(f"{MCP_PATH}/files/abc").status_code == 200


def test_signed_file_url_binds_user_and_tamper_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from backend.app.mcp import k_images_server as srv

    monkeypatch.setattr(srv.CONFIG, "file_signing_key", b"k" * 40)
    url = srv.signed_file_url("asset-1", user_id=7)
    parsed = urlparse(url)
    assert parsed.path.endswith("/mcp/k-images/files/asset-1")
    query = parse_qs(parsed.query)
    expires = int(query["exp"][0])
    sig = query["sig"][0]
    assert query["u"] == ["7"]
    assert expires > int(time.time())
    assert srv._sign("asset-1", 7, expires) == sig
    assert srv._sign("asset-1", 8, expires) != sig  # 换个人就不对
    assert srv._sign("asset-2", 7, expires) != sig
    assert srv._sign("asset-1", 7, expires + 1) != sig


def test_config_requires_signing_key_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.mcp import k_images_server as srv

    monkeypatch.delenv("K_MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("K_MCP_ACTOR_USERNAME", raising=False)
    monkeypatch.setenv("K_MCP_FILE_SIGNING_KEY", "short")
    with pytest.raises(SystemExit):
        srv._Config().validate()
    monkeypatch.setenv("K_MCP_FILE_SIGNING_KEY", "x" * 48)
    srv._Config().validate()  # 旧的全局钥匙/固定执行者不再需要
    src = inspect.getsource(srv)
    assert "K_MCP_BEARER_TOKEN" not in src.replace("BARONG_K_MCP_TOKEN", "")
    assert "K_MCP_ACTOR_USERNAME" not in src


def test_every_tool_takes_ctx_and_gates_k_permission() -> None:
    """工具体必须:从 ctx 取认出来的人 → require_k_access → 交稿要 write=True。"""
    from backend.app.mcp import k_images_server as srv

    src = inspect.getsource(srv.build_mcp)
    for name in (
        "k_list_products_awaiting_images",
        "k_get_image_brief",
        "k_get_reference_images",
        "k_submit_image",
        "k_get_submission_status",
    ):
        assert f'name="{name}"' in src
    assert src.count("actor_user_id(ctx)") == 5
    assert src.count("require_k_access(db, actor.user, write=False)") == 4
    assert src.count("require_k_access(db, actor.user, write=True)") == 1
    assert 'startswith("data:")' in src
    assert "validate=True" in src
