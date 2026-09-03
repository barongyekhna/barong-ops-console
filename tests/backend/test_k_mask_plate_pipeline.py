"""换路后的作图管线接线：实拍底图 + 产品保护蒙版 + AI 只画背景。

2026-08-03 全天在修「让 AI 重绘产品」这条路上的问题(电源键被抹平、软管接错
位置、画面里两个熊猫、泵在干地上喷水),修四轮仍有新问题——因为前提就是错的。
家规 SKILL.md 第 38 行本来就写着「产品本体永远用真实照片,AI 只负责背景」。

这批断言锁住换路后的关键接线,免得哪天又被改回「整张画布交给模型」。
免 AI / 免 DB,全部用 inspect.getsource 查接线。
"""
from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_mask_semantics_are_documented_where_it_is_sent() -> None:
    """mask 的语义反了就等于把产品交出去,必须在代码里写死这条注释。"""
    from backend.app.modules.i_series.image_system import service

    src = inspect.getsource(service.IImageModelEngine._request_provider_candidates)
    assert "mask_image" in src
    # 表单字段名必须是 mask,且不能跟参考图共用字段
    assert '"mask"' in src
    # 400/422 换字段名重试时,不能把 mask 一起换成 image
    assert "alternate_files.append(mask_file)" in src


def test_mask_reaches_the_provider_from_the_k_renderer() -> None:
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    src = inspect.getsource(irj._process_render_job)
    assert "_resolve_render_plate" in src
    assert "mask_image=mask_image" in src
    # 底板选择要按简报角色(proof_scene/accessory/…),不是 asset_role
    assert 'job.get("role_label")' in src


def test_plate_resolution_prefers_masked_and_correct_pose() -> None:
    """场景图必须优先拿「正在使用」姿态的实拍当底板。

    产品的姿态在照片里定死了、事后改不了(行业边界)。拿摆拍当场景图底板,
    出来就是「产品静静躺着而水在喷」。
    """
    from backend.app.modules.k_series.product_knowledge import brand_guard
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    prefs = brand_guard.PLATE_POSE_PREFERENCE
    assert prefs["proof_scene"][0] == brand_guard.POSE_IN_USE
    assert prefs["accessory"][0] == brand_guard.POSE_ACCESSORIES
    assert prefs["detail"][0] == brand_guard.POSE_DETAIL
    # 主图要干净产品展示,不能优先拿"正在使用"(那张里有人有手)
    assert prefs["main"][0] == brand_guard.POSE_PRODUCT_ONLY

    src = inspect.getsource(irj._resolve_render_plate)
    # 刷过蒙版的底图优先——没蒙版就等于把产品重新交给模型画
    assert "0 if mask_loaded is not None else 1" in src
    # 但姿态必须排在蒙版前面:姿态错=废图(配件平铺图当主图底板),
    # 没蒙版只是产品可能被重绘,几何门还兜得住
    keys = src[src.index("candidates.append("):src.index("if not candidates")]
    assert keys.index("pose_rank") < keys.index("mask_loaded is not None")
    # 没建素材台账的老产品必须退回旧路径,不能直接失败
    assert "return None" in src


def test_old_products_without_ledger_keep_working() -> None:
    """没圈过产品的老品仍要能出图,只是走旧的多参考图路径。"""
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    src = inspect.getsource(irj._process_render_job)
    order = [
        src.index("_resolve_render_plate"),
        src.index("_resolve_reference_images"),
        src.index("_resolve_reference_image(db, product)"),
    ]
    assert order == sorted(order), "退让顺序必须是 底板 → 多参考图 → 单图兜底"


def test_mask_asset_is_isolated_from_gallery_and_audit() -> None:
    """蒙版不是给人看的素材,别让它混进画廊/审查/上架。"""
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    src = inspect.getsource(irj.store_product_mask_asset)
    assert 'asset_role=ASSET_ROLE_PRODUCT_MASK' in src
    assert '"k_image_review_allowed": False' in src
    assert '"k_image_ai_generation_allowed": False' in src
    # 必须是 PNG:蒙版靠 alpha 表达保护区,JPEG 没有 alpha
    assert "MASK_NOT_PNG" in src
    # 覆盖式:一张底图只留一份蒙版
    assert 'stale.status = "removed"' in src


def test_mask_endpoints_registered() -> None:
    from backend.app.modules.k_series.product_knowledge import router as k_router

    src = inspect.getsource(k_router)
    assert '@router.get("/products/{product_id}/image-plates")' in src
    assert (
        '@router.put("/products/{product_id}/image-plates/{asset_id}/mask")' in src
    )
    # 底板列表要把证书/纯文字页排除掉——它们当不了底板
    plates_src = inspect.getsource(k_router.product_knowledge_list_image_plates)
    assert "reference_kind_usable" in plates_src
    assert "POSE_NONE" in plates_src


def test_pose_ledger_comes_from_the_existing_vision_call() -> None:
    """姿态标注要搭今天那次 vision 调用的便车,不许为它单开一次 AI。"""
    from backend.app.modules.k_series.product_knowledge import brand_guard

    instr = brand_guard._OPERATING_MODEL_INSTRUCTION
    assert "reference_poses" in instr
    assert "in_use" in instr and "accessories" in instr
    # 逐张独立判断 —— 曾经六张全被判成同一个标签
    assert "one at a time" in instr
    assert "do not give them all the same tag" in instr
    # in_use 的判定线要具体(有人碰 / 软管展开连着 / 有东西喷出 / 在工作位),
    # 不能只说"正在使用"那种模糊话
    assert "EXTENDED and connected" in instr
    assert "working position" in instr

    src = inspect.getsource(brand_guard.ai_operating_model)
    assert '"reference_poses": poses' in src
    # 认不出来的一律按最保守的用途处理
    assert "POSE_PRODUCT_ONLY" in src


def test_mask_is_resized_to_the_plate_not_rejected() -> None:
    """蒙版尺寸与底图对齐由后端负责，别难为前端。

    画笔按显示尺寸(~520px)作画，底图又可能是 preview(1280px)，而 image edit
    接口要求蒙版与原图逐像素同尺寸——三者天然对不上。统一在保存时缩放对齐。
    """
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    src = inspect.getsource(irj.store_product_mask_asset)
    assert "mask_img.size != plate_size" in src
    # 二值蒙版必须用 NEAREST：插值会在边界糊出半透明像素，
    # 保护区边缘就半生不熟了
    assert "NEAREST" in src
    # Pillow 缺席时不许把保存整个挡掉（本地测试是轻依赖环境）
    assert "except Exception" in src


def test_audit_reaudits_when_content_changed_during_the_run() -> None:
    """审查耗时几分钟，期间内容可能被改，指纹一落库就过期。

    2026-08-11 实测：06:50 开审 → 06:52 运营者保存图 → 06:54 落库，
    存下的指纹当场作废。他明明刚忽略放行过，上架门禁却报「内容在品牌审查后
    有改动」。审完必须自查一次指纹，变了就再排一轮。
    """
    from backend.app.modules.k_series.product_knowledge import generation_jobs

    src = inspect.getsource(generation_jobs._run_brand_audit_job)
    assert "brand_fingerprint" in src
    # 触发了重渲的分支不用重复排队（渲染收尾本来就会入队审查）
    assert "if not rerender_started:" in src
    # 自愈失败不许淹掉本轮审查结果
    assert "stale-fingerprint re-audit enqueue failed" in src
