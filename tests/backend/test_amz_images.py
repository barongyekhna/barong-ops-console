"""A5 图片通道纯函数:图片校验、dHash、格式门、差异化门、同屏门 / 事实门(桩)、brief 文本、Codex 指令、MCP 服务登记。不碰库。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace as N

import pytest
from PIL import Image

from backend.app.modules.amz_series import images
from backend.app.modules.amz_series.service import AmzServiceError

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _png(width: int, height: int, color=(255, 255, 255), stripe: int | None = None) -> bytes:
    img = Image.new("RGB", (width, height), color)
    if stripe is not None:
        for x in range(stripe, min(width, stripe + width // 4)):
            for y in range(height):
                img.putpixel((x, y), (0, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_validate_image_and_dhash_distance() -> None:
    fmt, w, h = images.validate_image(_png(1200, 1200))
    assert (fmt, w, h) == ("png", 1200, 1200)
    with pytest.raises(AmzServiceError) as exc:
        images.validate_image(b"not an image")
    assert exc.value.code == "amz_image_unreadable"
    with pytest.raises(AmzServiceError):
        images.validate_image(b"")
    a = images.dhash(_png(600, 600, stripe=100))
    a_small = images.dhash(_png(300, 300, stripe=50))  # 同一张图缩小
    b = images.dhash(_png(600, 600, stripe=400))  # 构图不同
    assert images.hamming(a, a_small) < images.SIBLING_MIN_HAMMING
    assert images.hamming(a, b) >= images.SIBLING_MIN_HAMMING
    assert len(images.thumbnail_bytes(_png(2000, 2000))) < 20000


def test_format_and_sibling_gates() -> None:
    main_ok = N(width=1200, height=1200, dhash="0f0f0f0f0f0f0f0f")
    main_bad = N(width=800, height=1000, dhash="0f0f0f0f0f0f0f0f")
    assert images.gate_format(main_ok, position="main")["passed"] is True
    bad = images.gate_format(main_bad, position="main")
    assert bad["passed"] is False and len(bad["problems"]) == 2
    assert images.gate_format(main_bad, position="lifestyle")["passed"] is True
    refs = [N(id="r1", kind="sibling_main", dhash="0f0f0f0f0f0f0f0e", note="03us"), N(id="r2", kind="competitor_thumb", dhash="ffffffffffffffff", note=None)]
    same = images.gate_sibling(main_ok, refs)
    assert same["passed"] is False and "03us" in same["problems"][0]
    different = images.gate_sibling(N(width=1, height=1, dhash="f0f0f0f0f0f0f0f0"), refs)
    assert different["passed"] is True
    assert images.gate_sibling(main_ok, [])["skipped"]


def test_vision_gates_with_stub_and_when_model_is_down() -> None:
    brief = N(position="main", must_have_json=["产品本体"], forbidden_json=["文字"])
    calls = []

    def stub(messages, *, org_id):
        calls.append(org_id)
        text = messages[0]["content"][0]["text"]
        if "买家" in text:
            return {"passed": False, "click_rank": 4, "stands_out": "太暗", "fix": ["提亮背景", "换 45 度角"]}
        return {"passed": True, "must_have_missing": [], "forbidden_found": [], "text_or_logo": False, "notes": []}

    screen = images.gate_same_screen(candidate=_png(400, 400), refs=[("对手缩略图", _png(200, 200))], org_id="org_x", call=stub)
    assert screen["passed"] is False and screen["fix"] == ["提亮背景", "换 45 度角"] and screen["click_rank"] == 4
    facts = images.gate_facts(candidate=_png(400, 400), brief=brief, facts={"is": "泵"}, org_id="org_x", call=stub)
    assert facts["passed"] is True and calls == ["org_x", "org_x"]
    assert images.gate_same_screen(candidate=_png(10, 10), refs=[], org_id="o")["skipped"]

    def down(messages, *, org_id):
        raise RuntimeError("4sapi 403")

    unknown = images.gate_facts(candidate=_png(400, 400), brief=brief, facts={}, org_id="o", call=down)
    assert unknown["passed"] is None and "403" in unknown["unknown"]
    logo = images.gate_facts(candidate=_png(400, 400), brief=brief, facts={}, org_id="o", call=lambda m, *, org_id: {"passed": True, "text_or_logo": True})
    assert logo["passed"] is False and logo["text_or_logo"] is True


def test_brief_markdown_and_codex_prompt() -> None:
    store = N(display_name="龙杰 美国", store_code="01us")
    facts = {"is": "便携淋浴泵", "how_it_works": "整机入水", "is_not": "不加热", "specs": {"dimensions_cm": "10x10x20"}, "indicators": "红灯充电", "package": "泵、软管", "audience": "露营"}
    evidence = {"term": "camp shower pump", "window_days": 60, "mine": {"impressions": 1000, "clicks": 10, "ctr_pct": 1.0}, "best": {"store": "04us", "impressions": 900, "clicks": 33, "ctr_pct": 3.7}}
    must, forbidden = images._must_and_forbidden(facts, "main")
    md = images.build_brief_md(store=store, position="main", product_line="pump", sku="01-PCS-blue", asin="B0TESTA0001", facts=facts, evidence=evidence, siblings=["03us", "04us"], must_have=must, forbidden=forbidden)
    assert "camp shower pump" in md and "04us" in md and "不加热" in md and "兄弟店 03us, 04us" in md and "白底" in md
    assert any("文字" in f for f in forbidden) and any("暗示它不是的功能" in f for f in forbidden)
    prompt = images.codex_prompt(N(id="abc", position="main", max_rounds=4))
    assert "amz_get_image_brief(\"abc\")" in prompt and "amz_submit_image" in prompt and "最多 4 轮" in prompt


def test_mcp_server_and_deploy_registration() -> None:
    from backend.app.mcp import amz_images_server as srv

    assert srv.MCP_PATH == "/mcp/amz-images"
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert "amz-mcp:" in compose and "backend.app.mcp.amz_images_server" in compose and "console_amz_media_data:" in compose
    assert "127.0.0.1:8096:8096" in compose
    nginx = (ROOT / "deploy/nginx/ops.barongyekhna.com.conf.template").read_text(encoding="utf-8")
    assert "location ^~ /mcp/amz-images" in nginx and "proxy_pass http://127.0.0.1:8096" in nginx
    assert "amz-media" in (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "amz_images_server" in (ROOT / "backend/Dockerfile.amz-mcp").read_text(encoding="utf-8")
    from r_system_v2.ra import quota_ledger as ql

    assert ql.DEFAULT_DAILY_BUDGETS[ql.PROVIDER_AMZ_IMAGE_GATES] == 120
    # 工具名与 Codex 指令里的一致
    mcp = srv.build_mcp()
    import anyio

    tools = anyio.run(mcp.list_tools)
    names = {t.name for t in tools}
    assert names == {"amz_list_briefs", "amz_get_image_brief", "amz_get_reference_images", "amz_submit_image", "amz_get_submission_status"}
    for name in ("amz_get_image_brief", "amz_get_reference_images", "amz_submit_image", "amz_get_submission_status"):
        assert name in images.codex_prompt(N(id="x", position="main", max_rounds=4))
    json.dumps([t.model_dump() for t in tools], default=str)
