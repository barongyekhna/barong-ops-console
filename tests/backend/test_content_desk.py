"""内容台（content.desk）。

内容台不是第三台内容引擎。它自己不生成内容、不发明状态、不建自己的表，只做
三件事：把 GEO/SEO 归一化成一个 DTO、把状态推导成「下一步该干嘛」、把整篇
审阅塞进一个浮窗让人连着过完。

由来（2026-08-02）：用户原话「我甚至不知道怎么用」「我经常不知道自己下一步
该干嘛」。GEO+SEO 两页加起来 39 个按钮、5 个页签、8 个板块——界面照代码结构
排的，不是照他的一天排的。后果不是难看，是**真的漏事**：排查时才发现 6 篇
GEO 指南待审、他完全不知道。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


def test_module_is_registered_everywhere_and_org_gated() -> None:
    """新模块的登记点漏一处 = 侧边栏隐身或测试红。

    这条踩过四次（F/W/H/B2B），所以逐点钉死，而不是相信自己记得。
    """
    from backend.app.core.modules import MODULE_MANIFESTS_V1
    from backend.app.core.permissions import BASE_PERMISSION_REGISTRY_SEED
    from backend.app.services.module_control_center import TRADE_ONLY_MODULE_IDS
    from backend.app.services.module_registry import INTL_TRADE_ONLY_MODULE_KEYS

    manifest = next(
        m for m in MODULE_MANIFESTS_V1 if m["module_key"] == "content.desk"
    )
    assert manifest["route_namespace"] == "/content-desk"
    # /content 被 content_links 的 machine router 占了
    assert manifest["api_namespace"] == "/content-desk"
    assert manifest["category"] == "business"

    seeded = {
        p["permission_key"]
        for p in BASE_PERMISSION_REGISTRY_SEED
        if p["module_key"] == "content.desk"
    }
    assert seeded == {
        "content.desk.read",
        "content.desk.execute",
        "content.desk.manage",
    }

    # 只属于国际贸易组织——两个独立的门都要过（用户死命令）
    assert "content.desk" in INTL_TRADE_ONLY_MODULE_KEYS
    assert "content.desk" in TRADE_ONLY_MODULE_IDS


def test_permission_migration_exists_and_chains_from_the_previous_head() -> None:
    """权限注册表只在**整张表为空**时才从 seed 自动灌。

    改了 BASE_PERMISSION_REGISTRY_SEED 对已有库零效果——模块会在侧边栏
    显示成锁着的。所以每个新模块必须自带迁移。B2B/CS/F/W 四次都栽在这。
    """
    src = (
        REPO
        / "backend/alembic/versions/20260802_01_content_desk_permissions.py"
    ).read_text()
    assert 'down_revision: str | Sequence[str] | None = "20260731_01_content_link_settings"' in src
    for key in ("content.desk.read", "content.desk.execute", "content.desk.manage"):
        assert key in src
    # 撤销时必须先清依赖表，否则外键挡着删不掉
    assert "role_default_permissions" in src
    assert "user_permission_assignments" in src

    manifest = json.loads((REPO / "migration_manifest.json").read_text())
    assert manifest["alembic_head"] == "20260802_01_content_desk_permissions"
    assert manifest["head_locked"] is True


def test_publish_blockers_reach_production_unsanitised() -> None:
    """409 的 blockers 是「为什么发不出去」唯一有用的那句话。

    生产的错误消毒器默认把 detail 换成「Request failed.」——内容台必须进
    白名单，否则用户看到的是一句废话。
    """
    from backend.app import main

    src = inspect.getsource(main._p_publish_gate_conflict_detail_for_production)
    assert "/content-desk/" in src


def test_desk_is_mounted_once_and_never_bare() -> None:
    """内容台全是人用的端点，**不裸挂**。

    机器路由才双挂载（带前缀那份被会话中间件守着，裸挂那份给 n8n 打）。
    内容台没有 n8n 会打它——裸挂等于开一个不过会话中间件的口子。
    """
    from backend.app.main import app

    paths = [
        r.path for r in app.routes if "content-desk" in getattr(r, "path", "")
    ]
    assert paths, "内容台没挂上"
    assert all(p.startswith("/api/app/content-desk") for p in paths), paths


def test_sidebar_prefix_is_in_both_hardcoded_tables() -> None:
    """侧边栏组织树有**两张**硬编码前缀表，只加一张 = 模块隐身。

    W-A 栽过一次，B2B 又栽了一次。
    """
    src = (
        REPO / "frontend/src/components/capability-sidebar-engine.tsx"
    ).read_text()
    prefixes = src.split("ORGANIZATION_MODULE_PREFIXES")[1].split("] as const")[0]
    assert '"content."' in prefixes
    restricted = src.split("function isRestrictedProductModule")[1].split("}")[0]
    assert 'startsWith("content.")' in restricted


def _function_body_source(func: object) -> str:
    """函数体源码，**去掉 docstring**。

    直接 inspect.getsource 会把 docstring 也算进去，于是「文件里不许出现
    "geo" 字面量」这条规矩自己写在注释里就会把自己的测试搞红。
    """
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = tree.body[0]
    body = node.body[1:] if ast.get_docstring(node) else node.body  # type: ignore[attr-defined]
    return "\n".join(ast.unparse(stmt) for stmt in body)


def test_queries_never_hardcode_an_engine_name() -> None:
    """两台引擎的不对称写在**一张声明式的表**里，不散在 if source == "geo" 里。

    判据（照 content_core/consistency.py 的 ProductionCheck 先例）：加第三个
    内容源应该只在 SOURCES 里加一行，不改任何逻辑。这条测试就是那个"不改逻辑"
    的守卫——一旦有人在查询层写死引擎名，规矩当场破功而没人会发现。
    """
    from backend.app.modules.content_desk import dto, queries

    for func in (
        queries.list_articles,
        queries.review_queue,
        queries.article_ref,
        queries.article_detail,
        queries.step_counts,
        queries._product_labels,
        dto.to_article,
    ):
        body = _function_body_source(func)
        assert '"geo"' not in body, func.__name__
        assert '"seo"' not in body, func.__name__


def test_source_table_captures_every_known_asymmetry() -> None:
    """GEO/SEO 的不对称是历史事实，不是设计失误。全部进表，一处不漏。"""
    from backend.app.modules.content_desk.sources import SOURCE_BY_KEY

    geo = SOURCE_BY_KEY["geo"]
    seo = SOURCE_BY_KEY["seo"]

    assert (geo.kind_column, seo.kind_column) == ("item_type", "item_kind")
    assert (geo.parent_fk, seo.parent_fk) == ("cluster_id", "topic_id")
    # GEO 的正文有 answer_blocks，SEO 没有
    assert "answer_blocks" in geo.body_keys and "answer_blocks" not in seo.body_keys
    # review 权限两边不一样：GEO 是 execute，SEO 是 manage。**这是故意的**
    assert geo.review_permission == "geo.content.execute"
    assert seo.review_permission == "seo.content.manage"
    # 放行一律要 manage —— 放行是推翻门禁，比批准一篇更重。
    # GEO 因此「能批准但不能放行」，这不是笔误。
    assert geo.manage_permission == "geo.content.manage"
    assert geo.review_permission != geo.manage_permission
    # SEO 在 review 时就拦品牌门（409），GEO 到发布才拦
    assert seo.review_requires_clean is True
    assert geo.review_requires_clean is False
    assert (geo.revise_mode, seo.revise_mode) == ("sync", "queued")
    assert (geo.publish_unit, seo.publish_unit) == ("parent", "items")


def test_unknown_source_is_rejected() -> None:
    """source 会被拼进查询和权限判断，只认表里有的。"""
    from backend.app.modules.content_desk.sources import UnknownSource, source_for

    with pytest.raises(UnknownSource):
        source_for("wordpress")
    with pytest.raises(UnknownSource):
        source_for("")


def test_dto_exposes_all_seven_deepseek_keys() -> None:
    """DeepSeek 解读七项，后端一个不砍、前端一个不藏。

    SEO 面板现在**只渲染 risks**，把翻译 / GEO 作用 / 为什么这么写 / 优点 /
    模型 全藏了——类型定义里明明都有。显示层自己挑字段就会这样，所以归一化层
    原样透传。用户点名要「DeepSeek 检查审阅必须在浮窗里显示完整」。
    """
    from backend.app.modules.content_desk.dto import ANALYSIS_KEYS, normalize_analysis

    assert set(ANALYSIS_KEYS) == {
        "translation",
        "geo_role",
        "why_written_this_way",
        "strengths",
        "risks",
        "model",
        "skill_version",
    }
    # 只给一个键，其余六个补 None —— **不是省略**（省略和"值为空"在前端是
    # 两条不同的代码路径）
    out = normalize_analysis({"risks": ["x"]})
    assert out is not None
    assert set(out) == set(ANALYSIS_KEYS)
    assert out["translation"] is None
    # 整个为空才返回 None，前端据此显示「还没解读」而不是七个空框
    assert normalize_analysis({}) is None
    assert normalize_analysis(None) is None


def test_dto_body_always_has_both_keys() -> None:
    """SEO 没有 answer_blocks，给 [] 而不是不给——前端只写一套渲染。"""
    from backend.app.modules.content_desk.dto import normalize_body

    seo_like = normalize_body({"sections": [{"heading": "h", "body": "b"}]})
    assert seo_like["answer_blocks"] == []
    assert len(seo_like["sections"]) == 1
    assert normalize_body(None) == {"sections": [], "answer_blocks": []}


def test_missing_brand_audit_is_not_clean() -> None:
    """没有审查记录 ≠ 审查通过。

    SEO 路由现在两处写的是 .get("clean", True)（缺记录=放行），GEO 是
    .get("clean")（缺记录=拦住）——同一个概念两个相反的默认值。内容台一律
    fail-closed，步 4 会把那两处也统一过来。
    """
    from backend.app.modules.content_desk.dto import normalize_audit

    assert normalize_audit({})["clean"] is False
    assert normalize_audit(None)["clean"] is False
    assert normalize_audit({"clean": True})["clean"] is True
    # 四族 finding 恒存在
    for key in (
        "brand_violations",
        "cjk_surfaces",
        "ungrounded_numbers",
        "bad_derivations",
        "ignored_findings",
    ):
        assert normalize_audit({})[key] == []


def test_modal_reuses_the_shared_overlay_and_does_not_reinvent_it() -> None:
    """浮窗行为只写一处。

    仓库里原本一个通用浮窗都没有，四处各造一半：NotificationOverlay 行为最全
    但视觉是通知专用的；R 的 DetailModal 视觉能用但**没有** portal / focus trap /
    滚动锁 / Esc。内容台把两边合起来放进 components/overlay-modal，
    desk 目录里不许再出现第五份。
    """
    from pathlib import Path

    desk = Path("frontend/src/modules/content/desk")
    modal = (desk / "ArticleModal.tsx").read_text()
    assert 'from "@/components/overlay-modal"' in modal

    for path in desk.glob("*.tsx"):
        src = path.read_text()
        assert "createPortal" not in src, path
        assert "FOCUSABLE_SELECTOR" not in src, path
        # 滚动锁也不许自己写
        assert "body.style.overflow" not in src, path


def test_arrow_keys_yield_to_text_inputs() -> None:
    """←/→ 翻篇是本仓第一处方向键导航（非游戏的 keydown 只有 5 处 Esc）。

    现有代码都没覆盖的坑：焦点在输入框里时方向键属于光标，不属于浮窗。
    抢走它，用户就没法在输入框里移动光标了。
    """
    from pathlib import Path

    overlay = Path("frontend/src/components/overlay-modal.tsx").read_text()
    assert "isTypingTarget" in overlay
    assert "isContentEditable" in overlay
    for tag in ("INPUT", "TEXTAREA"):
        assert tag in overlay

    modal = Path("frontend/src/modules/content/desk/ArticleModal.tsx").read_text()
    # 翻页前先让路
    assert modal.index("isTypingTarget") < modal.index("ArrowLeft")


def test_analysis_panel_renders_all_seven_keys() -> None:
    """DeepSeek 七项，前端一项不藏。

    SEO 面板现在只渲染 risks，把 translation / geo_role / why_written_this_way /
    strengths / model 全藏了——类型定义里明明都有。用户点名要「必须显示完整」。
    """
    from pathlib import Path

    from backend.app.modules.content_desk.dto import ANALYSIS_KEYS

    panel = Path(
        "frontend/src/modules/content/desk/AnalysisPanel.tsx"
    ).read_text()
    for key in ANALYSIS_KEYS:
        assert key in panel, key
    # 没解读时不静默隐藏——安静地少一块信息，人根本不会发现
    assert "跑一次解读" in panel

    types = Path("frontend/src/modules/content/desk/types.ts").read_text()
    for key in ANALYSIS_KEYS:
        assert key in types, key


def test_bad_derivations_have_no_release_button() -> None:
    """算错的数**永远**不能人工放行。

    它不是误报族——校验器真的把算式算过一遍，对不上才报的。放行它 = 主动把一个
    算错的数字发到面向美国买家的页面上。
    """
    from pathlib import Path

    panel = Path("frontend/src/modules/content/desk/AuditPanel.tsx").read_text()
    # 锚到 JSX 那一处区块标题。裸文本 "算错的数字" 在模块 docstring 里也有，
    # bad_derivations.length 也出现两次——两个都会切错地方。
    tail = panel[panel.index("blockLabel}>算错的数字"):]
    assert "误报，放行" not in tail
    assert "算错的数不能放行" in panel
    # 已放行的不隐藏——放行清单不自动清理，藏起来人就忘了自己放过什么
    assert "已放行" in panel


def test_fetch_boilerplate_is_defined_once() -> None:
    """buildHeaders/readJson 原来在三个面板里各复制一份。内容台是第四个用到
    它们的地方——再抄一遍就是四份，四份必然分叉。"""
    from pathlib import Path

    root = Path("frontend/src/modules/content")
    definitions = [
        path
        for path in root.rglob("*.ts*")
        if "function buildHeaders" in path.read_text()
    ]
    assert [p.name for p in definitions] == ["api-base.ts"], definitions
