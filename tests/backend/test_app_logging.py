"""应用日志配置。

2026-09-02 之前，生产进程里的应用 logger **没有任何 handler**、有效级别是
WARNING —— `logger.info()` 写不到任何地方，整个生产日志里一条应用级 INFO
都没有。后果是所有「靠日志证明后台任务在跑」的观测手段全是摆设，
本轮在留存清理上实地栽过一次（加了每轮一条日志，却怎么都看不到）。

这份测试盯三件容易回退的事：
1. 自家 logger 真的能写出去；
2. 第三方（httpx / SQLAlchemy）保持 WARNING —— 开了它们，应用自己的信息
   会被出网日志和每一条 SQL 淹掉，等于换一种方式看不见；
3. 配置幂等 —— gunicorn 多 worker 各 import 一次，叠 handler 会让日志重复。
"""

from __future__ import annotations

import logging

import pytest

from backend.app.main import _APP_LOGGER_NAMES, _configure_app_logging

pytestmark = pytest.mark.unit


def test_app_loggers_can_actually_write(caplog) -> None:
    _configure_app_logging()
    logger = logging.getLogger("barong.audit_events")

    assert logger.level <= logging.INFO, "自家 logger 级别高于 INFO，info 又写不出去了"
    assert logger.handlers, "没有 handler —— 这正是 2026-09-02 之前的状态"

    with caplog.at_level(logging.INFO, logger="barong.audit_events"):
        logger.info("probe")
    assert any("probe" in record.getMessage() for record in caplog.records)


def test_third_party_loggers_stay_quiet() -> None:
    """出网和 SQL 日志不许开到 INFO —— 那会把应用自己的信息淹掉。"""
    _configure_app_logging()
    for noisy in ("httpx", "httpcore", "sqlalchemy.engine", "urllib3"):
        assert logging.getLogger(noisy).level >= logging.WARNING, (
            f"{noisy} 被开到了 INFO 以下"
        )


def test_configuration_is_idempotent() -> None:
    """多 worker 各 import 一次，叠 handler 会让每条日志出现多次。"""
    _configure_app_logging()
    before = len(logging.getLogger("barong.audit_events").handlers)
    _configure_app_logging()
    _configure_app_logging()
    after = len(logging.getLogger("barong.audit_events").handlers)
    assert after == before


def test_worker_logger_namespaces_are_covered() -> None:
    """worker 用的具名 logger 必须在清单里，否则后台任务的日志照样写不出去。

    这些名字散在各个 worker 里（`getLogger("nijing.worker")` 这种），
    漏一个的表现是「那个 worker 的日志静默消失」，没有任何报错。
    """
    for required in (
        "backend.app",
        "barong.audit_events",
        "nijing.worker",
        "baisuwan-worker",
        "k-image-render-worker",
        "geo-content-worker",
        "seo-content-worker",
    ):
        assert required in _APP_LOGGER_NAMES, f"{required} 不在日志配置清单里"


def test_startup_banner_reports_the_config_actually_in_effect() -> None:
    """启动时必须把「这个容器带着什么配置起来的」打出来。

    2026-09-02 连续两次踩到同一个坑：改了 `.env.production` 却改错了副本
    （发版脚本在发版目录下跑，compose 的 env_file 是相对路径，读的是那份），
    结果发版成功、健康检查通过、烟测通过，配置却完全没生效 —— 全程静默。

    一行启动横幅就能当场暴露这类问题，所以它是运维设施而不是装饰。
    """
    from pathlib import Path

    from backend.app import main as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    lifespan = source[source.index("async def _app_lifespan") :]
    lifespan = lifespan[: lifespan.index("\n\napp = FastAPI")]

    assert "控制台后端已启动" in lifespan
    for field in ("settings.app_version", "EVENT_RETENTION_DAYS", "LOG_LEVEL"):
        assert field in lifespan, f"启动横幅没报告 {field}"
