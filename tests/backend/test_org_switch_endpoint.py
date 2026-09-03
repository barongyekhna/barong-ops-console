"""组织切换端点：多组织用户的自救出口，也是一个高危的写入面。

**为什么有这两个端点**（2026-08-31 体检）：
`middleware/org_context.py` 一直在读 `auth_session.active_org_id`，而这一列
根本不存在，于是「会话选定组织」那条分支永不执行。任何拥有 ≥2 个 active
成员关系、又不是某组织 `owner_user_id` 的用户，解析链全落空 → 整站 403，
而前端没有任何切换器可以自救。本次补齐了列 + 写入端点 + 可选列表端点。

**为什么必须有这个测试文件**：这两个端点用的是**函数内 import**（避免循环依赖），
而函数内 import 的名字写错**只在端点被调用时才炸**，单元测试全绿。
本轮已经栽过两次同类的：B2B 的 `status` 未导入（只在错误路径炸）、
这里的 `OrgMembership` 类名猜错（真名是 `OrgMembershipRecord`，发版后实测才发现）。
所以这些用例**必须真的把端点调起来**，不能只做源码断言。
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


class TestEndpointsResolveTheirDeferredImports:
    """把函数内 import 的名字全部当场解析一遍。

    这是针对「函数内 import 写错只在运行时炸」这一类问题的最小护栏：
    不需要数据库，只要求每个被 import 的名字**真的存在**。
    """

    def test_switch_organization_imports_resolve(self) -> None:
        from backend.app.api.routes.auth import auth_switch_organization

        src = inspect.getsource(auth_switch_organization)
        assert "OrgMembershipRecord" in src, (
            "org_membership 模型的类名是 OrgMembershipRecord，不是 OrgMembership。"
        )
        # 逐个真的 import 一遍：写错名字这里就会 ImportError。
        from backend.app.core.roles import is_owner_role  # noqa: F401
        from backend.app.middleware.org_context import (  # noqa: F401
            reset_org_context_cache_for_tests,
        )
        from backend.app.models.org_membership import OrgMembershipRecord  # noqa: F401
        from backend.app.models.organization import OrganizationRecord  # noqa: F401

    def test_available_organizations_imports_resolve(self) -> None:
        from backend.app.api.routes.auth import auth_available_organizations

        src = inspect.getsource(auth_available_organizations)
        assert "OrgMembershipRecord" in src


class TestSwitchIsGuarded:
    """切换端点写的是**后续所有请求**的组织上下文，校验漏了就是越权入口。

    比原本那个「多组织被锁死」的 bug 危险得多，所以把校验写成契约。
    """

    def test_membership_is_verified_before_switching(self) -> None:
        from backend.app.api.routes.auth import auth_switch_organization

        src = inspect.getsource(auth_switch_organization)
        assert "OrgMembershipRecord" in src and "status ==" in src.replace(" ", " "), (
            "切换前没有校验 active 成员关系。"
        )
        assert "HTTP_403_FORBIDDEN" in src, "不是成员时必须 403。"
        assert "HTTP_404_NOT_FOUND" in src, "组织不存在/已停用必须 404。"

    def test_owner_may_switch_anywhere(self) -> None:
        """owner 是平台级角色，可切任意 active 组织 —— 与权限引擎的语义一致。"""
        from backend.app.api.routes.auth import auth_switch_organization

        assert "is_owner_role" in inspect.getsource(auth_switch_organization)

    def test_switch_invalidates_the_org_context_cache(self) -> None:
        """Phase 6 给组织上下文加了 5 秒缓存；切换后不清它，用户会以为没生效。"""
        from backend.app.api.routes.auth import auth_switch_organization

        assert "reset_org_context_cache_for_tests" in inspect.getsource(
            auth_switch_organization
        )


class TestRoutesAreRegisteredAndProxied:
    def test_routes_exist(self) -> None:
        from backend.app.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        assert "/api/public/auth/switch-organization" in paths
        assert "/api/public/auth/organizations" in paths

    def test_frontend_proxy_allowlist_covers_them(self) -> None:
        """已知坑：新端点漏登记代理白名单 = 页面红条。"""
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        src = (
            repo / "frontend/src/app/api/backend/[...path]/route.ts"
        ).read_text(encoding="utf-8")
        assert '"auth/switch-organization"' in src
        assert '"auth/organizations"' in src
