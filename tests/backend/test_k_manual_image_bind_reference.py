"""手动图取图绑定 + 手动/链接两种参考图:
1. P 取图纳入「已绑定」的手动图(metadata.upload_bound=true),未绑定不取;webp 铁律门同步。
2. 单图重做 / 新增图 支持 reference_asset_id(先上传本地文件当参考图)与 reference_image_url 两种。
"""
from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_upload_package_includes_bound_manual_images() -> None:
    from backend.app.modules.p_series.upload import assemble

    src = inspect.getsource(assemble)
    # 取图 SQL: k_auto_render 或 upload_bound=true
    assert "metadata_json->>'upload_bound' = 'true'" in src
    assert "metadata_json->>'render_pipeline' = 'k_auto_render'" in src


def test_webp_gate_also_covers_bound_manual_images() -> None:
    from backend.app.modules.p_series.upload.assemble import _non_webp_image_blockers

    gate = inspect.getsource(_non_webp_image_blockers)
    # 绑定的手动图也必须过 webp 铁律,不能漏检
    assert "upload_bound" in gate
    assert "image/webp" in gate


def test_upload_bound_endpoint_wired() -> None:
    from backend.app.modules.k_series.product_knowledge import router

    src = inspect.getsource(router)
    assert "/images/{asset_id}/upload-bound" in src
    assert "def set_image_upload_bound" in src
    assert '"upload_bound"' in src
    # 助手:资产必须属于该产品
    assert "def _image_asset_for_product" in src


def test_rework_accepts_uploaded_reference_asset() -> None:
    from backend.app.modules.k_series.product_knowledge import router

    rework = inspect.getsource(router.product_knowledge_render_rework)
    # asset_id 优先于 url
    assert "payload.reference_asset_id is not None" in rework
    assert "_image_asset_for_product" in rework
    assert "reference_image_url" in rework  # 链接仍支持
    # 请求模型带 reference_asset_id
    model = inspect.getsource(router.RenderReworkRequest)
    assert "reference_asset_id" in model


def test_add_image_accepts_uploaded_reference_asset() -> None:
    from backend.app.modules.k_series.product_knowledge import router

    add = inspect.getsource(router.product_knowledge_brief_image_add)
    assert "payload.reference_asset_id is not None" in add
    assert "_image_asset_for_product" in add
    model = inspect.getsource(router.BriefImageAddRequest)
    assert "reference_asset_id" in model


def test_manual_reference_upload_reuses_existing_upload_endpoint() -> None:
    # req3:手动上传当参考图 = 走现有 upload_product_media_asset(asset_role=reference),
    # 参考图解析器 _original_photo_assets 接受任何非渲染 available 图(含手动 reference)。
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    src = inspect.getsource(irj._original_photo_assets)
    # 不按 1688/platform 过滤参考图,只排除渲染流水线图
    assert "RENDER_PIPELINE_TAG" in src
    assert "platform" not in src.lower()
