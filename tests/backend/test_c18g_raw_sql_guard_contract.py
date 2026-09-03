"""C18G 裸 SQL 守卫的契约测试。

**为什么要有这个文件**：2026-08-22 的迁移 `20260822_01_backfill_orgscoped_org_id`
给 `operation_logs` 补了 `org_id` 列，这让 `middleware/data_isolation.py` 的兼容探针
从「库还是老形状」翻转成「新形状」，于是**严格模式全局意外启用**，65 处裸 SQL 当场
被拒——建品、上架、GEO/SEO 生成、发布、内容台全挂，九天没人发现。

整条链路上没有任何一个测试盯着这个开关：探针有测试钩子
`_reset_c05b_schema_probe_cache_for_tests`，但全仓零调用方。加一列就能静默改变
全站行为，这是最不该没有护栏的地方。

这里把三件事固化成契约：
1. 探针的翻转条件（什么情况下 strict 会被打开）；
2. 守卫拦得住 execute / scalar / scalars 三条路径（不只是 execute）；
3. 单语句逃生口 `SKIP_ORG_DATA_ISOLATION` 只放行它自己那一条。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.services.data_isolation import (
    SKIP_ORG_DATA_ISOLATION,
    OrgDataIsolationManualSqlError,
    OrgDataIsolationUserContext,
    current_org_data_isolation_context,
    org_data_isolation_context,
    without_org_data_isolation,
)

def _ctx(org_id: str = "org_" + "a" * 32) -> OrgDataIsolationUserContext:
    return OrgDataIsolationUserContext(user_id="1", org_id=org_id, role="owner")


@pytest.mark.unit
class TestGuardCoversAllExecutionPaths:
    """守卫必须覆盖 execute / scalar / scalars。

    `schemas/data_isolation.py` 断言 `intercepts_raw_sql is True`。在补上
    scalar/scalars 之前那是一句空承诺——SQLAlchemy 2.0 的 scalar/scalars 走
    `_execute_internal`，不经过被 override 的 `execute()`，裸 SQL 可以直接绕过去。
    """

    def test_execute_rejects_raw_sql_without_org_filter(self) -> None:
        with SessionLocal() as db, org_data_isolation_context(_ctx()):
            with pytest.raises(OrgDataIsolationManualSqlError):
                db.execute(text("SELECT 1 FROM users"))

    def test_scalar_rejects_raw_sql_without_org_filter(self) -> None:
        with SessionLocal() as db, org_data_isolation_context(_ctx()):
            with pytest.raises(OrgDataIsolationManualSqlError):
                db.scalar(text("SELECT count(*) FROM users"))

    def test_scalars_rejects_raw_sql_without_org_filter(self) -> None:
        with SessionLocal() as db, org_data_isolation_context(_ctx()):
            with pytest.raises(OrgDataIsolationManualSqlError):
                db.scalars(text("SELECT id FROM users"))


@pytest.mark.integration
class TestSingleStatementEscapeHatch:
    """单语句逃生口只放行它自己那一条，不影响同一个 session 里的其它语句。

    这正是它比 `without_org_data_isolation()` 安全的地方——后者把整个隔离上下文
    置 None，ORM 自动过滤、写保护、跨组织 get 拦截会一起失效。
    """

    def test_skip_option_allows_that_one_statement(self) -> None:
        with SessionLocal() as db, org_data_isolation_context(_ctx()):
            # 不带豁免会被拒
            with pytest.raises(OrgDataIsolationManualSqlError):
                db.execute(text("SELECT 1 FROM users"))
            # 带上豁免就放行
            db.execute(
                text("SELECT 1 FROM users"),
                execution_options=SKIP_ORG_DATA_ISOLATION,
            )

    def test_skip_option_does_not_leak_to_the_next_statement(self) -> None:
        with SessionLocal() as db, org_data_isolation_context(_ctx()):
            db.execute(
                text("SELECT 1 FROM users"),
                execution_options=SKIP_ORG_DATA_ISOLATION,
            )
            # 上一条豁免了，这一条必须照样被拦——豁免不能有残留
            with pytest.raises(OrgDataIsolationManualSqlError):
                db.execute(text("SELECT 1 FROM users"))

    def test_skip_option_keeps_ambient_context_intact(self) -> None:
        """豁免期间上下文仍在——对比 without_org_data_isolation 会把它整个置 None。"""
        with SessionLocal() as db, org_data_isolation_context(_ctx()):
            db.execute(
                text("SELECT 1 FROM users"),
                execution_options=SKIP_ORG_DATA_ISOLATION,
            )
            assert current_org_data_isolation_context() is not None

            with without_org_data_isolation():
                assert current_org_data_isolation_context() is None
            assert current_org_data_isolation_context() is not None


@pytest.mark.integration
class TestOrgIdLiteralIsWhatUnlocksTheGuard:
    """守卫的判据是纯子串匹配 `org_id`，不解析 SQL。

    把这条写成测试是因为它是**反直觉**的：SQL 里任意位置出现 org_id 三个字就放行，
    哪怕它在注释里、或者是 `requested_by_org_id` 这种别的列名。谁要改判据逻辑，
    这条会提醒他影响面有多大。
    """

    def test_sql_containing_org_id_passes(self) -> None:
        with SessionLocal() as db, org_data_isolation_context(_ctx()):
            db.execute(
                text("SELECT :org_id AS org_id"),
                {"org_id": "org_" + "a" * 32},
            )

    def test_non_dml_statements_are_not_guarded(self) -> None:
        """只拦 select/insert/update/delete 开头的语句；SET/WITH/DDL 不管。"""
        with SessionLocal() as db, org_data_isolation_context(_ctx()):
            db.execute(text("SET LOCAL statement_timeout = '8000'"))


@pytest.mark.integration
class TestStrictModeProbeContract:
    """严格模式那个开关的契约。**这是本文件存在的首要理由。**

    `_probe_c05b_schema_without_c18_data_isolation()` 返回 True = 库还是 C05B 老形状
    → strict 关；返回 False → strict 开、裸 SQL 守卫全站生效。

    它的判据只有两条：`org_memberships` 表存在，且 `operation_logs` 有 `org_id` 列。
    2026-08-22 那次迁移只是想给 `/errors` 和 `/memory-events` 补列，顺手也给
    `operation_logs` 补了——于是第二条判据成立，全站 strict 被打开，主链断了九天。

    把它写成测试的意义不在于「防止有人改坏探针」，而在于**让下一个动这两张表的人
    当场看见这里有个全局开关**。测试红了会逼他读这段注释。
    """

    def test_probe_returns_false_when_schema_is_current(self) -> None:
        """当前生产形状（两条判据都成立）→ 探针 False → strict 开。"""
        from backend.app.middleware.data_isolation import (
            _probe_c05b_schema_without_c18_data_isolation,
            _reset_c05b_schema_probe_cache_for_tests,
        )

        _reset_c05b_schema_probe_cache_for_tests()
        assert _probe_c05b_schema_without_c18_data_isolation() is False, (
            "探针返回了 True，说明 org_memberships 缺失或 operation_logs 没有 org_id 列。"
            "在当前 schema 下这不该发生；如果你刚删了这两者之一，"
            "请注意这会让全站 C18G 严格模式静默关闭。"
        )

    def test_probe_result_is_cached_per_process(self) -> None:
        """探针按进程缓存一次定终身——改 schema 不重启，行为不会跟着变。

        这一条固化的是「为什么当时没人发现」：迁移跑完之后，已经在跑的进程要等到
        下一次重启才会翻转。所以事故是延迟生效的。
        """
        from backend.app.middleware import data_isolation as mw

        mw._reset_c05b_schema_probe_cache_for_tests()
        assert mw._c05b_schema_probe_cache is None
        first = mw._c05b_schema_without_c18_data_isolation()
        assert mw._c05b_schema_probe_cache is not None
        assert mw._c05b_schema_without_c18_data_isolation() is first
