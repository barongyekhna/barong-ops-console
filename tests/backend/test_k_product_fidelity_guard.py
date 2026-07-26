"""产品保真两处修复:
1) 保真指令从"只加主图"改为"所有角色都加"(image_render_jobs)。
2) 审查闭环加产品几何保真校验(brand_guard),且几何变形只挡发布不自动重渲
   (generation_jobs),因为重渲修不好生成式变形。
全部用 inspect.getsource 断言接线,免 AI / 免 DB(与 test_image_slim_iron_rule 同风格)。
"""
from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_fidelity_block_exists_and_allows_scene_but_locks_geometry() -> None:
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    block = irj.PRODUCT_FIDELITY_BLOCK.lower()
    # 锁死几何/控件/颜色/标记
    assert "identical" in block
    assert "shape" in block and "proportions" in block
    assert "buttons" in block and "display" in block
    assert "colour" in block and "markings" in block
    # 允许换取景/角度/场景(否则会和 proof 场景图冲突)
    assert "angle" in block or "scene" in block
    assert "never" in block  # 明确禁止 redesign/reshape


def test_every_role_gets_fidelity_block() -> None:
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    src = inspect.getsource(irj.enqueue_image_render_jobs)
    assert "prompt += PRODUCT_FIDELITY_BLOCK" in src
    # 该行必须无角色守卫(不能只在 asset_role == main 分支里)
    for line in src.splitlines():
        if "prompt += PRODUCT_FIDELITY_BLOCK" in line:
            indent = len(line) - len(line.lstrip())
            # 与其它每图必加块(BRAND_REMOVAL_PROMPT_BLOCK)同层缩进 = 无条件
            assert indent <= 8, f"fidelity block looks role-gated: indent={indent}"


def test_house_style_block_no_longer_carries_lone_fidelity_line() -> None:
    # 保真句已抽到独立块;主图不应再靠 HOUSE_STYLE_BLOCK 里的那句(避免只主图有)
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    assert "do not alter product shape" not in irj.HOUSE_STYLE_BLOCK.lower()


def test_geometry_auditor_compares_reference_and_ignores_non_form() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard

    assert hasattr(brand_guard, "ai_geometry_violation")
    instr = brand_guard._GEOMETRY_AUDIT_INSTRUCTION.lower()
    # 比几何
    assert "shape" in instr and "proportions" in instr
    # 明确忽略颜色/背景/角度(否则误挡三色图和场景图)
    assert "ignore" in instr
    assert "colour" in instr and "background" in instr and "angle" in instr
    # 保守:拿不准别挡
    assert "do not flag" in instr or "not flag" in instr

    # 函数把参考图和渲染图两张都发出去
    fn_src = inspect.getsource(brand_guard.ai_geometry_violation)
    assert fn_src.count("image_url") >= 2
    assert "reference_bytes" in fn_src and "rendered_bytes" in fn_src


def test_run_brand_audit_wires_geometry_check_fail_open() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard

    src = inspect.getsource(brand_guard.run_brand_audit)
    # 跑几何检查并打 category 标签
    assert "ai_geometry_violation" in src
    assert '"category": "geometry"' in src
    assert '"category": "brand"' in src
    # 有环境开关
    assert "K_GEOMETRY_AUDIT_ENABLED" in src
    # fail-open:几何审查异常不进 errors(否则 fail-closed 误挡)
    assert "geo_findings = []" in src


def test_geometry_violation_gates_publish_via_clean_flag() -> None:
    # clean 由 image_violations 决定;几何违规进 image_violations → clean=False → 挡门
    from backend.app.modules.k_series.product_knowledge import brand_guard

    src = inspect.getsource(brand_guard.run_brand_audit)
    assert '"clean": not deduped and not image_violations and not errors' in src


def test_geometry_violations_do_not_trigger_auto_rerender() -> None:
    from backend.app.modules.k_series.product_knowledge import generation_jobs

    src = inspect.getsource(generation_jobs._run_brand_audit_job)
    # 拆分品牌/几何
    assert "brand_image_violations" in src and "geometry_violations" in src
    # 重渲条件用的是品牌违规,不是全部 image_violations
    assert "and brand_image_violations" in src
    # 重渲的 hints 只遍历品牌违规
    assert "for violation in brand_image_violations" in src
    # 几何违规有独立的人工通知分支
    assert "geometry_violations and not text_violations" in src
