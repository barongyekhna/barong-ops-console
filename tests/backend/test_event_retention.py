"""观测表留存清理。

2026-09-01 体检：`event_streams` 2.0 GB / 107 万行、`storage_events` 1.0 GB /
107 万行，两张占整库 64%，每小时各涨约 2,400 行；而 `storage_events`
**全仓没有任何一处 SELECT**，`event_streams` 也只有 `snapshot()` 取最新
5000 条。超过留存窗的行写进去就再没人看。

这份测试盯的是清理最容易出的两种错：
1. 删多了 —— 把窗口内该留的行一起删掉（审计留痕删了不可逆）。
2. 删不动 —— 分批逻辑写错，跑一轮删 0 行，表照样涨。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.models.observability import (
    EventStreamRecord,
    StorageEventRecord,
)
from backend.app.services.event_collector import (
    EVENT_RETENTION_BATCH_ROWS,
    EventQueueBackend,
)
from backend.app.services.data_isolation import (
    SKIP_ORG_DATA_ISOLATION,
    without_org_data_isolation,
)

pytestmark = pytest.mark.integration

_MARK = "retention-test-"


def _seed(
    db, table: str, *, age_days: int, count: int, markers: list[str] | None = None
) -> list[str]:
    """按 ORM 造行。

    手写 INSERT 会漏列 —— 这两张表各有十几个 NOT NULL 字段，而且随迁移在变。
    走 ORM 的话，列一变编译期就报，不会等到测试运行时才发现。
    """
    stamp = datetime.now(timezone.utc) - timedelta(days=age_days)
    created = markers or [f"{_MARK}{uuid4().hex}" for _ in range(count)]
    for marker in created:
        common = {
            "backend_targets": ["db"],
            "context_id": marker,
            "created_at": stamp,
            "entity_type": "retention_test",
            "event_id": marker,
            "module_id": "core.retention_test",
            "org_id": "org_retention_test",
            "payload": {},
            "status": "recorded",
            "storage_tier": "hot",
            "trace_id": marker,
            "updated_at": stamp,
        }
        if table == "event_streams":
            db.add(
                EventStreamRecord(
                    **common,
                    action="retention.seed",
                    event_type="retention.seed",
                    metadata_json={},
                    record_id=marker,
                    source="test",
                    timestamp=stamp,
                )
            )
        else:
            db.add(
                StorageEventRecord(
                    **common,
                    occurred_at=stamp,
                    operation="write",
                    record_id=marker,
                    storage_event_id=marker,
                )
            )
    db.flush()
    return created


def _count(db, table: str) -> int:
    return db.scalar(
        text(
            f"SELECT count(*) FROM {table} WHERE record_id LIKE :mark"
        ),
        {"mark": f"{_MARK}%"},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )


def _cleanup(db) -> None:
    # 先子后父 —— 外键是 NO ACTION，反过来删不动。
    for table in ("storage_events", "event_streams"):
        db.execute(
            text(f"DELETE FROM {table} WHERE record_id LIKE :mark"),
            {"mark": f"{_MARK}%"},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )


@pytest.fixture
def seeded_events():
    with without_org_data_isolation():
        with SessionLocal() as db:
            _cleanup(db)
            # 窗口外（100 天前）5 条，窗口内（1 天前）3 条
            # 先造父表再造子表：storage_events.record_id 外键指向 event_streams。
            # 子表复用父表的 record_id，这样也顺带覆盖了「父子同窗口一起过期」。
            for age, count in ((100, 5), (1, 3)):
                markers = _seed(db, "event_streams", age_days=age, count=count)
                _seed(db, "storage_events", age_days=age, count=count,
                      markers=markers)
            db.commit()
    yield
    with without_org_data_isolation():
        with SessionLocal() as db:
            _cleanup(db)
            db.commit()


def test_prune_removes_only_rows_older_than_the_window(seeded_events) -> None:
    """删的必须**只是**窗口外的行。窗口内被误删 = 审计留痕不可逆地少了一截。"""
    deleted = EventQueueBackend().prune_expired()

    assert deleted["event_streams"] >= 5
    assert deleted["storage_events"] >= 5

    with without_org_data_isolation():
        with SessionLocal() as db:
            # 1 天前的三条必须还在
            assert _count(db, "event_streams") == 3
            assert _count(db, "storage_events") == 3


def test_prune_is_disabled_when_retention_days_is_zero(
    seeded_events, monkeypatch
) -> None:
    """留 0 天 = 关闭清理，不是「全删」。取证时要能一键停掉。"""
    monkeypatch.setenv("EVENT_RETENTION_DAYS", "0")
    deleted = EventQueueBackend().prune_expired()

    assert deleted == {"event_streams": 0, "storage_events": 0}
    with without_org_data_isolation():
        with SessionLocal() as db:
            assert _count(db, "event_streams") == 8
            assert _count(db, "storage_events") == 8


def test_prune_batches_are_bounded(seeded_events) -> None:
    """一轮最多删 batch × max_batches 行。

    分批不是为了快，是为了**别开长事务** —— 这两张表是全库写得最频繁的，
    一条扫 90 万行的 DELETE 会持锁并把表撑肿。
    """
    collector = EventQueueBackend()
    deleted = collector.prune_expired(max_batches=1)
    assert deleted["event_streams"] <= EVENT_RETENTION_BATCH_ROWS
    assert deleted["storage_events"] <= EVENT_RETENTION_BATCH_ROWS


def test_prune_does_not_hit_the_request_path_statement_timeout(seeded_events) -> None:
    """清理必须**真能删得动**，不能只是逻辑对。

    2026-09-02 实测踩到：全局 statement_timeout 是 8 秒（给请求路径定的），
    而删 event_streams 的每一行都要检查外键 —— 子表 storage_events.record_id
    上当时**没有索引**，于是每删一行就全表扫一遍 110 万行，直接超时。
    而超时异常在 `_prune_if_due` 里被吞成日志，线上表现是
    「清理每小时静默失败一次、表继续涨」。

    这条测试盯的就是「跑得完」：清理自己设的超时预算要生效，
    执行不能抛 OperationalError。
    """
    from sqlalchemy.exc import OperationalError

    collector = EventQueueBackend()
    try:
        deleted = collector.prune_expired()
    except OperationalError as exc:  # pragma: no cover - 出现即为回归
        raise AssertionError(
            f"留存清理撞上语句超时，说明它在生产上会静默失效：{exc}"
        ) from exc
    assert deleted["event_streams"] >= 5


def test_prune_failures_are_visible_in_stats() -> None:
    """连续失败必须能被看见。

    只写日志的话，「静默不生效」和「一切正常」在 stats() 上长得一模一样，
    而这两张表一旦停止清理就会无限涨。
    """
    collector = EventQueueBackend()
    assert "prune_failures" in collector.stats()


def test_maintenance_thread_does_not_depend_on_the_drain_loop() -> None:
    """清理必须有自己的线程。

    2026-09-02 生产实测：`DEFAULT_EVENT_EMITTER` 的 `_auto_drain=False`、
    `_started=False`、`_worker=None` —— 队列消费循环**从来没运行过**
    （107 万条事件卡在 queued 就是这么来的）。清理一开始被挂在那个循环里，
    等于写了个永不执行的功能。

    这条测试钉死：清理线程独立于队列消费，start_maintenance() 之后必须真的
    有一个活着的线程，而且不需要 start()。
    """
    collector = EventQueueBackend()
    assert collector._started is False, "前提：队列消费默认不启动"

    collector.start_maintenance()
    try:
        worker = collector._maintenance_worker
        assert worker is not None, "start_maintenance 没建线程"
        assert worker.is_alive(), "清理线程没活着"
        assert worker.daemon, "必须是守护线程，否则进程退不出去"
    finally:
        collector.stop_maintenance()


def test_app_lifespan_starts_retention_maintenance() -> None:
    """启动钩子里必须真的调用 start_maintenance()。

    这一条守的是「接回死代码≠生效」：函数写好了、没人调用，
    和没写是一样的 —— 本轮已经在登录限流、组织切换上各栽过一次。
    """
    source = Path("backend/app/main.py").read_text(encoding="utf-8")
    assert "DEFAULT_EVENT_EMITTER.start_maintenance()" in source
    assert "DEFAULT_EVENT_EMITTER.stop_maintenance()" in source


def test_first_prune_runs_soon_after_startup_not_after_a_full_interval() -> None:
    """第一轮必须尽快跑，不能等满一个间隔。

    间隔是一小时。如果循环写成「先等满一小时再跑」，那么容器重启比一小时
    频繁时，清理**永远轮不到执行** —— 又是一个「看起来做了、其实不跑」。
    """
    from backend.app.services import event_collector as module

    assert module.EVENT_RETENTION_FIRST_RUN_DELAY_SECONDS < (
        module.EVENT_RETENTION_INTERVAL_SECONDS
    )
    source = Path(module.__file__).read_text(encoding="utf-8")
    loop = source[source.index("def _maintenance_loop") :]
    loop = loop[: loop.index("\n    def ")]
    first_wait = loop.index("EVENT_RETENTION_FIRST_RUN_DELAY_SECONDS")
    first_prune = loop.index("self._prune_once()")
    interval_wait = loop.index("EVENT_RETENTION_INTERVAL_SECONDS")
    assert first_wait < first_prune < interval_wait, (
        "第一轮清理必须排在按间隔循环之前"
    )


def test_every_prune_cycle_is_recorded_in_the_heartbeat_table(seeded_events) -> None:
    """跑了但没删，也必须留痕 —— 而且要留在**看得见**的地方。

    2026-09-02 实测：生产进程里应用 logger 没有任何 handler、有效级别 WARNING，
    `logger.info()` 写不到任何地方。所以「每轮记一条日志」这种观测等于没有观测
    —— 我先写了一版，正是这个毛病。改走 worker_heartbeats 表：
    Phase 5 专门为「后台任务到底有没有在干活」建的，有独立检查脚本。
    """
    collector = EventQueueBackend()
    collector._prune_once()

    assert collector.stats()["prune_runs"] == 1
    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT last_success_at, consecutive_failures FROM worker_heartbeats "
                "WHERE worker_name = :name"
            ),
            {"name": "c17-retention"},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).first()
    assert row is not None, "清理跑完了却没写心跳 —— 线上将无法判断它有没有在跑"
    assert row.last_success_at is not None
    assert row.consecutive_failures == 0


def test_prune_keeps_going_until_a_batch_deletes_nothing(seeded_events) -> None:
    """删完的判据是「这一批删了 0 行」，不是「删得少于一批」。

    2026-09-02 实测踩到：清存量时脚本报「完成」，实际还剩 192,474 行过期
    没删——因为退出条件写的是 `removed < BATCH_ROWS`。
    `ctid IN (子查询)` 在并发写入下会有部分 ctid 失效，
    **一批删得少于 LIMIT 是常态**，不代表没有更多了。跑第二遍才删干净。

    这条测试用「批量大到一次删完」的方式逼出那个分支：
    如果退出条件还是 `< BATCH_ROWS`，第一批删 5 行 < 5000 就退出，
    看起来也「对」——所以真正要断言的是**跑完之后窗口外一行不剩**。
    """
    collector = EventQueueBackend()
    collector.prune_expired(max_batches=8)

    cutoff_days = collector._retention_days()
    stamp = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
    with without_org_data_isolation():
        with SessionLocal() as db:
            for table in ("storage_events", "event_streams"):
                left = db.scalar(
                    text(
                        f"SELECT count(*) FROM {table} "
                        "WHERE created_at < :cutoff AND record_id LIKE :mark"
                    ),
                    {"cutoff": stamp, "mark": f"{_MARK}%"},
                    execution_options=SKIP_ORG_DATA_ISOLATION,
                )
                assert left == 0, (
                    f"{table} 跑完清理后还剩 {left} 行过期 —— "
                    "退出条件又变回「删得少于一批就收工」了"
                )


def test_break_condition_is_zero_not_partial_batch() -> None:
    """把退出条件本身钉在源码里。

    这是少数几个值得断言实现细节的地方：这个条件写错时**不报错、不崩溃**，
    只是静默地少删——和「一切正常」在任何监控上都长得一样。
    """
    from pathlib import Path

    from backend.app.services import event_collector as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    prune = source[source.index("def prune_expired") :]
    prune = prune[: prune.index("\n    def ")]
    assert "if removed == 0:" in prune
    assert "removed < EVENT_RETENTION_BATCH_ROWS" not in prune
