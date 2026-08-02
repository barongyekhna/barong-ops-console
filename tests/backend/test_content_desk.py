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
