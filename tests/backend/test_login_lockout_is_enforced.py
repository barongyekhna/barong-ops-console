"""登录锁定与限流必须**被读取**，不能只写不读。

2026-08-31 体检发现：配置里写着「5 次失败锁 15 分钟」、`login_side_effects` 也确实
在往库里写 `failed_login_count` / `locked_until`，但 `login()` 从头到尾没有一处读它们，
`rate_limiter` 的三层桶全仓零调用方。实测在锁定期内用正确密码登录仍然 200。
限流桶的最后写入停在 2026-06-20——这条链路是那之后被摘掉的。

这个文件锁的是「接线还在」这件事本身。三条断言分别对应三段曾经断掉的线：
桶限流被调用、账号锁定被读取、被拒时抛的是路由层认识的那个异常。
"""

from __future__ import annotations

import inspect

import pytest

from backend.app.services import auth_service

pytestmark = pytest.mark.unit


def _login_source() -> str:
    return inspect.getsource(auth_service.login)


class TestLoginActuallyConsultsItsDefenses:
    def test_login_calls_the_rate_limiter(self) -> None:
        """三层桶(IP/用户名/端点)必须在 login 里被调用。

        它们曾经存在、被配置、被测试，但没有任何调用方——等于摆设。
        """
        assert "register_login_rate_limit_attempt(" in _login_source(), (
            "login() 没有调用 register_login_rate_limit_attempt —— "
            "登录限流又变回了死代码，撞库将不受任何速率限制。"
        )

    def test_login_reads_the_account_lockout(self) -> None:
        """`locked_until` / `failed_login_count` 必须被读，不能只写。"""
        assert "_user_retry_after_seconds(" in _login_source(), (
            "login() 没有读账号锁定状态 —— locked_until 会被写进库但没人执行，"
            "锁定期内用正确密码仍然能登录。"
        )

    def test_rate_limit_check_precedes_password_hashing(self) -> None:
        """限流必须在密码哈希**之前**。

        撞库的唯一成本就是那次 argon2 计算(约 0.5s，且可并发)。
        先把它花掉再判断要不要拦，等于没有拦。
        """
        src = _login_source()
        limiter_at = src.index("register_login_rate_limit_attempt(")
        hash_at = src.index("hash_password(password)")
        assert limiter_at < hash_at, (
            "限流检查排在了密码哈希之后 —— 攻击者仍然可以让服务器为每次尝试"
            "付出完整的哈希代价。"
        )

    def test_denial_raises_the_error_the_route_layer_understands(self) -> None:
        """被拒时抛 LoginRateLimitError —— 路由层据此返回 429 + Retry-After。"""
        src = _login_source()
        assert "LoginRateLimitError(" in src
        assert hasattr(auth_service.LoginRateLimitError("x", retry_after_seconds=1),
                       "retry_after_seconds")

    def test_rate_limit_counter_is_committed_before_the_password_check(self) -> None:
        """限流计数必须**当场提交**，否则失败次数永远回到零。

        这是比「有没有调用限流」更隐蔽的一层：`register_login_rate_limit_attempt`
        自己不 commit，计数只留在事务里；而登录失败会抛异常、事务被丢弃 ——
        于是限流器数不到任何失败，只有成功登录才留得下记录。

        2026-08-31 实测：接回限流之后，连发 25 次错密码仍然全部 401，
        桶表里只有成功登录留下的 2 条。少这一行 commit，前面所有接线都白接。
        """
        src = _login_source()
        limiter_at = src.index("register_login_rate_limit_attempt(")
        commit_at = src.index("db.commit()", limiter_at)
        hash_at = src.index("hash_password(password)")
        assert limiter_at < commit_at < hash_at, (
            "限流计数没有在密码校验之前提交 —— 失败次数会随事务回滚一起丢失，"
            "撞库将不受限制。"
        )
