"""产品保真接线:
1) 保真指令从"只加主图"改为"所有角色都加"(image_render_jobs)。
2) 审查闭环加产品几何保真校验(brand_guard)。
3) 2026-08-03 熊猫花洒(PSPE-002)一轮根治:
   - 品牌抹除不许再碰功能件(电源键/指示灯/接口图标),它跟保真块自相矛盾;
   - 几何门去掉"看着像同一个东西就放行"的放水句,改逐项检查表 + 多角度参考图;
   - 新增物理可信度门(潜水泵搁干地上却在喷水);
   - 几何/物理违规改为自动重渲(同批 4 好 4 崩证明是抽卡,不是生成式上限)。
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

    # 2026-08-26 提示词拼接抽成 build_render_prompt(worker 与外部精修通道共用);
    # enqueue 必须走它,块本身在它里面断言。
    assert "build_render_prompt(" in inspect.getsource(irj.enqueue_image_render_jobs)
    src = inspect.getsource(irj.build_render_prompt)
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

    # 函数把参考图和渲染图都发出去
    fn_src = inspect.getsource(brand_guard.ai_geometry_violation)
    assert fn_src.count("image_url") >= 2
    assert "reference_bytes" in fn_src and "rendered_bytes" in fn_src


def test_geometry_auditor_has_no_looks_like_same_object_escape_hatch() -> None:
    """旧版结尾那句放水语放行了熊猫主图(凸台多长一块/耳朵不对称/边缘串色)。

    「还认得出是同一个东西就别标记」= 几何门形同虚设,永远不许再出现。
    """
    from backend.app.modules.k_series.product_knowledge import brand_guard

    instr = brand_guard._GEOMETRY_AUDIT_INSTRUCTION.lower()
    assert "looks like the same physical object" not in instr
    assert "only flag clear, obvious" not in instr
    # 改成逐项检查表:每项判过再下结论
    assert "checklist" in instr
    for item in (
        "control housing",
        "parts integrity",
        "connections & tubing",
        "silhouette",
        "colour bleeding",
    ):
        assert item in instr, f"geometry checklist missing: {item}"
    # 控件被抹平/填死/变成没特征的椭圆 = 明确的 FAIL(熊猫电源键实况)
    assert "featureless oval" in instr


def test_geometry_checklist_covers_hose_and_cable_topology() -> None:
    """2026-08-03 第二轮熊猫:三处软管错误全被几何门漏掉。

    主图提手后多出一截断管、配件图软管从肚子接出、场景图软管末端悬空没接到
    花洒头 —— 检查表当时只查「长得像不像」,没有「接得对不对」这一维。
    """
    from backend.app.modules.k_series.product_knowledge import brand_guard

    instr = brand_guard._GEOMETRY_AUDIT_INSTRUCTION.lower()
    # 接出位置(不许从肚子/脸上冒出来)
    assert "port/outlet position" in instr
    # 走线连续(不许中途消失/变粗/分叉)
    assert "continuously" in instr
    # 必须真的接到目标件,不许悬空/停在盆沿
    assert "terminate" in instr
    assert "mid-air" in instr
    # 凭空多出的断管
    assert "stub" in instr or "orphaned" in instr


def test_geometry_gate_does_not_flag_composition_differences() -> None:
    """治误报:参考图里有、这张没拍 ≠ 缺件。

    实测误报两条——主图被判「缺少花洒头」(主图本就只拍主体)、信息图被判
    「多了个橙色挂钩」(那是真配件)。误报会触发无谓重渲白烧额度。
    """
    from backend.app.modules.k_series.product_knowledge import brand_guard

    instr = brand_guard._GEOMETRY_AUDIT_INSTRUCTION.lower()
    assert "actually shown" in instr
    assert "never flag something as missing" in instr
    assert "not an 'extra part'" in instr
    # 构图/裁切/带了哪些配件,都在忽略清单里
    assert "crop" in instr and "which accessories were included" in instr


def test_render_batch_enqueues_audit_without_waiting_for_manual_save() -> None:
    """渲染一收尾就审,别让人当第一道质检。"""
    from backend.app.modules.k_series.product_knowledge import brand_guard
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    # 暂存待保存的图也要进审查范围,否则收尾时审了个寂寞
    assert '"available", "staged"' in inspect.getsource(brand_guard._render_assets)
    # 批次收尾入队 brand_audit,并且不重复入队
    finalize_src = inspect.getsource(irj._maybe_finalize_batch)
    assert "'brand_audit'" in finalize_src
    assert "NOT EXISTS" in finalize_src


def test_geometry_audit_sends_multiple_reference_angles() -> None:
    """单张正面营销图判不出部件数量和对称性,要多角度一起送。"""
    from backend.app.modules.k_series.product_knowledge import brand_guard

    assert brand_guard.MAX_AUDIT_REFERENCES >= 2
    fn_src = inspect.getsource(brand_guard.ai_geometry_violation)
    assert "extra_references" in fn_src
    # 参考图在前、渲染图最后(顺序错了审查器会比反)
    assert "rendered" in fn_src.split("extra_references")[-1]

    previews_src = inspect.getsource(brand_guard._reference_previews)
    assert "extras" in previews_src
    assert "MAX_AUDIT_REFERENCES" in previews_src

    audit_src = inspect.getsource(brand_guard.run_brand_audit)
    assert "reference_extras" in audit_src
    assert "extra_references=" in audit_src


def test_brand_removal_never_strips_functional_controls() -> None:
    """死规矩:电源符号既是 symbol 又是 control。

    抹除块原本写着 "symbols",跟保真块的「buttons/controls 布局数量不变」直接
    打架,模型每张图随机挑一边 —— 熊猫同一批 9 张图出现了 4 种电源键长相。
    """
    from backend.app.modules.k_series.product_knowledge import brand_guard

    block = brand_guard.BRAND_REMOVAL_PROMPT_BLOCK
    lowered = block.lower()
    # 不许再无差别删 symbols
    assert "logos, symbols," not in lowered
    # 必须显式豁免功能件,且豁免优先级高于抹除
    assert "functional-part exemption" in lowered
    assert "overrides" in lowered
    for part in ("power button", "indicator light", "display", "port"):
        assert part in lowered, f"functional exemption missing: {part}"
    assert "if a mark is a control, keep it" in lowered


def test_image_audit_does_not_call_product_controls_unfinished_design() -> None:
    """半成品检查里的「icons with no caption」会误伤产品自带的电源图标。"""
    from backend.app.modules.k_series.product_knowledge import brand_guard

    instr = brand_guard._IMAGE_AUDIT_INSTRUCTION.lower()
    assert "not a defect" in instr
    assert "power button" in instr and "indicator light" in instr


def test_physics_gate_exists_and_is_wired_fail_open() -> None:
    """物理可信度门:潜水泵搁在干地上却在喷水这类,几何门查不出来。"""
    from backend.app.modules.k_series.product_knowledge import brand_guard

    assert hasattr(brand_guard, "ai_physics_violation")
    assert hasattr(brand_guard, "ai_operating_model")
    assert hasattr(brand_guard, "product_operating_model")

    instr = brand_guard._PHYSICS_AUDIT_INSTRUCTION.lower()
    # 只判画面里看得见的;别把静态摆拍/开箱平铺当违规
    assert "visible" in instr
    assert "packshot" in instr or "not in use" in instr

    fn_src = inspect.getsource(brand_guard.ai_physics_violation)
    # 没有约束就直接跳过(普通产品不该凭空长出物理限制)
    assert "if not constraints and not forbidden" in fn_src
    assert "hard_constraints" in fn_src and "forbidden_depictions" in fn_src

    audit_src = inspect.getsource(brand_guard.run_brand_audit)
    assert "ai_physics_violation" in audit_src
    assert '"category": "physics"' in audit_src
    assert "K_PHYSICS_AUDIT_ENABLED" in audit_src
    # fail-open,和几何门同规格:审查器自己出错不许挡门
    assert "physics_findings = []" in audit_src


def test_operating_model_derivation_never_blocks_brief_and_respects_human_edit() -> None:
    from backend.app.modules.k_series.product_knowledge import workflow_engine

    src = inspect.getsource(workflow_engine.KWorkflowOrchestratorV2._resolve_operating_model)
    # 人工改过的永远权威,不重新推导覆盖
    assert 'existing.get("edited_by_user")' in src
    # 推导失败 fail-open:退回已有值,绝不炸掉整个作图指令生成
    assert "return existing" in src
    # 出网前先放掉读事务(idle-in-transaction 8s 会掐断连接)
    assert "self.db.commit()" in src


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
    # 几何违规进 image_violations → 未被忽略则计入 unresolved → clean=False → 挡门。
    # (clean 计算已升级为按"排除忽略后仍未解决"算,见 test_k_brand_audit_ignore。)
    from backend.app.modules.k_series.product_knowledge import brand_guard

    src = inspect.getsource(brand_guard.run_brand_audit)
    assert '"clean": not unresolved and not errors' in src
    assert "_audit_violation_fingerprints(deduped, image_violations)" in src


def test_geometry_and_physics_violations_do_trigger_auto_rerender() -> None:
    """推翻旧结论「几何变形重渲也修不好」。

    熊猫花洒同一份 prompt、同一个批次:p04/p06/p07/p09 保真很好,
    p02/p03/p05/p08 画崩了 —— 抽卡波动,不是生成式上限。所以三类图像违规
    (品牌/几何/物理)都走自动重渲,沿用 attempt<2 上限,2 轮不过才交人工。
    """
    from backend.app.modules.k_series.product_knowledge import generation_jobs

    src = inspect.getsource(generation_jobs._run_brand_audit_job)
    # 三类分别可见(通知文案要按类报)
    assert "brand_image_violations" in src
    assert "geometry_violations" in src
    assert "physics_violations" in src
    # 重渲条件覆盖三类,而不是只有品牌
    assert "rerenderable_violations" in src
    assert "and rerenderable_violations" in src
    assert "for violation in rerenderable_violations" in src
    # 轮数上限没被放开(别把额度烧穿)
    assert "attempt < 2" in src
    # 文本违规仍然一票否决:文案没改对之前重渲多少次都没用
    assert "not text_violations" in src


def test_rerender_hint_is_defect_neutral_not_brand_only() -> None:
    """重渲提示会喂给三类违规,措辞不能再写死成「品牌审查失败」。"""
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    src = inspect.getsource(irj.build_render_prompt)
    assert "FAILED brand review" not in src
    assert "REJECTED by review" in src


def test_operating_constraint_block_reaches_every_non_main_render() -> None:
    """物理约束必须真的拼进 prompt —— 存了不用等于没修。"""
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    # 有约束 -> 出块,并带上"必须成立/绝不出现"两段
    block = irj._operating_constraint_block(
        {
            "operating_model": {
                "how_it_works": "A submersible pump.",
                "hard_constraints": ["the pump body must be fully submerged"],
                "forbidden_depictions": ["pump on dry ground while spraying"],
            }
        }
    )
    assert "OPERATING CONSTRAINT" in block
    assert "fully submerged" in block
    assert "NEVER DEPICT" in block
    assert "dry ground" in block

    # 没有约束的普通产品 -> 空串(不给渲染 prompt 塞废话)
    assert irj._operating_constraint_block({}) == ""
    assert (
        irj._operating_constraint_block(
            {"operating_model": {"hard_constraints": [], "forbidden_depictions": []}}
        )
        == ""
    )

    src = inspect.getsource(irj.build_render_prompt)
    assert "operating_constraint_block" in src
    # 白底主图不展示工作状态,不需要;其余角色都要
    assert "if asset_role != ASSET_ROLE_MAIN:" in src
    # 保真块必须仍是最后一句(最高优先),物理块排在它前面
    fidelity_at = src.index("prompt += PRODUCT_FIDELITY_BLOCK")
    physics_at = src.index("prompt += context.operating_constraint_block")
    assert physics_at < fidelity_at


def test_scene_motif_dedup_blocks_repeated_situations() -> None:
    """9 张图 5 张「营地洗登山靴」不许再发生。"""
    from backend.app.modules.k_series.product_knowledge import workflow_engine as we

    # 同母题重复 -> 报问题
    issues = we._scene_motif_issues(
        [
            {"role": "proof_scene", "position": 4, "scene_motif": "campsite_gear_rinse"},
            {"role": "proof_scene", "position": 5, "scene_motif": "campsite_gear_rinse"},
            {"role": "proof_scene", "position": 7, "scene_motif": "backyard_dog_wash"},
        ]
    )
    assert any(issue.get("motif") == "campsite_gear_rinse" for issue in issues)
    assert any("4" in str(issue.get("positions")) for issue in issues)

    # 漏填 scene_motif -> 报问题
    missing = we._scene_motif_issues([{"role": "proof_scene", "position": 3}])
    assert any(issue.get("positions") == [3] for issue in missing)

    # 母题下限跟着 proof 张数走(封顶 3):两张不同母题的图组是合法的,
    # 但 5 张 proof 只有 2 个母题就不行。
    assert (
        we._scene_motif_issues(
            [
                {"role": "proof_scene", "position": 4, "scene_motif": "a_scene"},
                {"role": "proof_scene", "position": 5, "scene_motif": "b_scene"},
            ]
        )
        == []
    )
    thin = we._scene_motif_issues(
        [
            {"role": "proof_scene", "position": 4, "scene_motif": "a_scene"},
            {"role": "proof_scene", "position": 5, "scene_motif": "b_scene"},
            {"role": "proof_scene", "position": 6, "scene_motif": "a_scene"},
            {"role": "proof_scene", "position": 7, "scene_motif": "b_scene"},
            {"role": "proof_scene", "position": 8, "scene_motif": "a_scene"},
        ]
    )
    assert any(issue.get("expected_minimum") == 3 for issue in thin)

    # 三个互不相同 -> 干净放行
    assert (
        we._scene_motif_issues(
            [
                {"role": "proof_scene", "position": 4, "scene_motif": "campsite_gear_rinse"},
                {"role": "proof_scene", "position": 5, "scene_motif": "backyard_dog_wash"},
                {"role": "proof_scene", "position": 7, "scene_motif": "toddler_bath_patio"},
            ]
        )
        == []
    )

    # 非 proof 角色不参与去重(主图/信息图/尺寸图不该被要求 scene_motif)
    assert (
        we._scene_motif_issues(
            [
                {"role": "main", "position": 1},
                {"role": "feature_callout", "position": 2},
                {"role": "dimension", "position": 3},
            ]
        )
        == []
    )


def test_scene_motif_failure_is_wired_into_composition_gate_and_retry() -> None:
    from backend.app.modules.k_series.product_knowledge import workflow_engine as we

    gate_src = inspect.getsource(we._validate_image_brief_gallery_composition)
    assert "_scene_motif_issues" in gate_src

    brief_src = inspect.getsource(
        we.KWorkflowOrchestratorV2.generate_image_brief
    )
    # 重复母题要走已有的 retry 通道,并把「换场景换人」讲清楚
    assert 'issue.get("field") == "scene_motif"' in brief_src
    assert "distinct scene_motif" in brief_src


def test_image_brief_gets_operating_model_and_audience_fields() -> None:
    """作图 AI 看不到图,这些文字就是它唯一的「视觉/人群」输入。"""
    from backend.app.modules.k_series.product_knowledge import workflow_engine as we

    snapshot_src = inspect.getsource(we._copy_evidence_product_snapshot)
    assert "target_customer_en" in snapshot_src
    assert "primary_use_case_en" in snapshot_src

    brief_src = inspect.getsource(
        we.KWorkflowOrchestratorV2.generate_image_brief
    )
    assert "_resolve_operating_model" in brief_src
    assert '"operating_model": operating_model' in brief_src
    # 推导结果要跟着简报一起落库,否则渲染和审查读不到
    assert 'result["operating_model"] = operating_model' in brief_src


def test_art_direction_instruction_drops_hardcoded_camping_bias() -> None:
    """「camping -> 真营地」这条硬编码把所有图都推进了同一个场景。"""
    from backend.app.modules.k_series.product_knowledge import prompt_skills

    instr = prompt_skills.image_art_direction_instruction()
    assert "cooking/camping" not in instr
    # 换成通用规则:物理约束 + 场景多样性
    assert "OPERATING MODEL" in instr
    assert "SCENE DIVERSITY" in instr
    assert "scene_motif" in instr
    assert "buyer_personas" in instr


def test_product_own_name_words_are_never_third_party_brands() -> None:
    """产品叫 Panda Outdoor Shower,"Panda" 就不能被当成第三方品牌。

    2026-08-03 实测:审查一口气报了 52 条 "Panda" 违规(产品名/关键词/文案/每张
    图四字段全中),clean 打成 false,连带把自动重渲闭环整个卡死——因为有文本
    违规就不重渲图。真品牌走源头黑名单 detected_brand_terms,那条路不受影响。
    """
    from types import SimpleNamespace

    from backend.app.modules.k_series.product_knowledge import brand_guard

    product = SimpleNamespace(
        product_name_en="Panda Outdoor Shower",
        primary_keyword="portable panda camping shower",
    )
    words = brand_guard._product_own_words(product)
    assert "panda" in words
    assert "shower" in words

    src = inspect.getsource(brand_guard.run_brand_audit)
    # 过滤接线:自有词过滤掉,但仍在源头黑名单里的照挡
    assert "_product_own_words" in src
    assert "own_words" in src and "blacklist" in src

    # 必须按**词**判断,不是整串比对。2026-08-11 漏网:报上来的是短语
    # ("panda pump"、"Panda portable shower head"),整串永远不等于产品名里
    # 的单词,于是十条误报全溜过去把上架门堵死。
    assert "_is_own_description" in src
    assert "words & own_words" in src

    import re as _re
    word_re = brand_guard._WORD_RE
    own = {"panda", "outdoor", "shower"}
    def shares(term: str) -> bool:
        return bool({m.group(0).lower() for m in word_re.finditer(term)} & own)
    for phrase in ("panda pump", "Panda portable shower head",
                   "panda outdoor shower set", "Panda-shaped portable outdoor shower"):
        assert shares(phrase), f"自有描述被误判成品牌: {phrase}"
    for brand in ("Lululemon", "Gruper", "ididi"):
        assert not shares(brand), f"真品牌被放行: {brand}"

    # 自有词也要喂给审查器本身,从源头少报
    assert "own_words" in inspect.getsource(brand_guard.ai_text_violations)


def test_rerender_loop_has_a_backstop_independent_of_attempt_counter() -> None:
    """attempt 曾经一直停在 0 = 轮数上限形同虚设,必须有第二道闸。"""
    from backend.app.modules.k_series.product_knowledge import generation_jobs

    src = inspect.getsource(generation_jobs._run_brand_audit_job)
    # 1) attempt 必须真的落库(flag_modified + flush,覆盖 run_brand_audit 写的旧值)
    assert "flag_modified" in src and "db.flush()" in src
    # 2) 不依赖 attempt 的硬保险:按数据库里真实发生过的渲染批次数封顶
    assert "recent_batches" in src
    assert "_MAX_RECENT_RENDER_BATCHES" in src
    assert generation_jobs._MAX_RECENT_RENDER_BATCHES <= 5


def test_every_brand_audit_enqueue_is_dedup_guarded() -> None:
    """入队审查必须去重,否则撞唯一索引把调用方的事务整个回滚。

    2026-08-03 回归:渲染批次收尾新增了自动入队,而 save_render_assets 里原有
    那条裸 INSERT 没有去重 —— 只要收尾入队的那条还在 pending/running,用户点
    「保存」就撞 uq_k_gen_jobs_active_product_type,IntegrityError 让保存静默
    失败(用户表现为"图 1 和图 9 点保存保存不了")。
    """
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj

    src = inspect.getsource(irj)
    inserts = src.split("INSERT INTO k_generation_jobs")[1:]
    assert inserts, "本模块应当存在入队审查的语句"
    for statement in inserts:
        body = statement.split('"""')[0]
        if "'brand_audit'" not in body:
            continue
        assert "NOT EXISTS" in body, "发现未去重的 brand_audit 入队"
    # 两处入队(渲染批次收尾 / 人工保存)都要受保护
    assert sum("'brand_audit'" in s.split('"""')[0] for s in inserts) == 2
