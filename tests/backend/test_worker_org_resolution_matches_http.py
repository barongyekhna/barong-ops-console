"""worker 与 HTTP 两条路径必须对同一个用户算出同一个组织。

2026-08-31 体检：`resolve_execution_org_id`（worker/执行门用）把
`user.organization_id` 排在查 `org_memberships` **之前**，而 HTTP 路径
（`middleware/org_context.py` 的 `_resolve_org`）先看「唯一 active membership」。

`users.organization_id` 是一列裸字符串——没有外键约束，也没有任何机制保证它
与 `org_memberships` 同步。两条路径优先级不同 ⇒ 同一个用户，前台请求算出 org_Y、
后台任务算出 org_X。

为什么这条特别要紧：GEO/SEO/P 的发布全部由 worker 执行，而 worker 场景
（`request=None`、无隔离上下文）恰好会落到那一位。算错组织的后果不是报错，
是**内容发到错的站、错的账**——静默的、事后才发现的那种。
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def _resolver_source() -> str:
    from backend.app.services.module_execution_gate import resolve_execution_org_id

    return inspect.getsource(resolve_execution_org_id)


class TestMembershipWinsOverTheLegacyColumn:
    def test_membership_lookup_precedes_user_organization_id(self) -> None:
        """org_memberships 必须排在 user.organization_id 之前。

        membership 是有约束、有生命周期管理的那一份；organization_id 只是兼容位。
        """
        src = _resolver_source()
        membership_at = src.index("_single_active_membership_org(")
        legacy_at = src.index('getattr(user, "organization_id"')
        assert membership_at < legacy_at, (
            "user.organization_id 又排到了 org_memberships 前面 —— "
            "worker 与 HTTP 会对同一个用户算出不同组织，"
            "GEO/SEO/P 的发布会发到错的站。"
        )

    def test_legacy_column_requires_an_active_organization(self) -> None:
        """用 organization_id 兜底时必须确认那个组织还是 active 的。

        HTTP 路径的 `_resolve_org` 同样会校验 `organization.status == "active"`；
        两边不一致就又是一处分歧。
        """
        assert "_organization_is_active(" in _resolver_source(), (
            "用 user.organization_id 兜底时没有校验组织是否 active。"
        )


class TestBothPathsShareTheSamePrecedence:
    def test_http_path_also_prefers_membership(self) -> None:
        """确认 HTTP 那一侧的顺序没有反过来变——这条测试是双向的。"""
        from backend.app.middleware.org_context import _resolve_org

        src = inspect.getsource(_resolve_org)
        membership_at = src.index("len(memberships) == 1")
        legacy_at = src.index("user.organization_id")
        assert membership_at < legacy_at, (
            "HTTP 路径改成了先读 user.organization_id —— "
            "那就轮到 worker 那侧与它不一致了。两边要一起改。"
        )


class TestMultiOrgHomeFallback:
    def test_multi_membership_without_session_choice_lands_on_home_org(self) -> None:
        """多组织成员、会话没选过组织 → 落在主组织,而不是整站 403。"""
        from backend.app.middleware.org_context import _resolve_org

        src = inspect.getsource(_resolve_org)
        assert "fallback_home_org_membership" in src
        single_at = src.index("len(memberships) == 1")
        home_at = src.index("fallback_home_org_membership")
        admin_at = src.index("is_org_admin_like_role(user_role)")
        assert single_at < home_at < admin_at, "主组织兜底要排在唯一成员关系之后、org-admin 回退之前"
