"""C17 审计事件采集。

事件写入是**同步**的：`emit_event` 把事件落进 `event_streams`（并派生一条
`storage_events`），请求路径上就完成，不依赖任何后台进程。审计留痕不会因为
后台没跑而丢失 —— 这一点是这个模块的底线。

## ⚠️ 队列消费默认关闭，这是有意的决定，不是 bug

`DEFAULT_EVENT_EMITTER` 用的是 `auto_drain=False`，全仓也没有任何地方调用
`start()`。也就是说 `_drain()` 那条消费循环**从来没有运行过**，事件写进去之后
一直停在 `processing_status='queued'`，不会被二次加工（加工是指写进
`audit_logs` 等派生表）。

2026-09-02 复核时的事实：
- 自 2026-06-17 建表起累计约 107 万条，其中 98% 停在 queued；
- 这两个半月里**没有任何功能因此报错**，说明加工后的产物当前没有消费方；
- 原始审计事件本身照常落库，需要查证时直接查 `event_streams` 即可。

**据此拍板：维持不打开。** 积压随留存窗自然过期（见下方留存策略）。

要打开的话，把 `DEFAULT_EVENT_EMITTER` 换成 `EventQueueBackend(auto_drain=True)`
或在启动时调 `start()` —— 但**先想清楚谁在消费加工产物**，否则只是把 107 万条
积压变成几个小时的持续写入负载，换来一堆同样没人看的派生行。

## 留存清理走的是另一条线

`start_maintenance()` 起的独立线程，**不依赖上面那条消费循环**（正因为它从不运行）。
清理结果写进 `worker_heartbeats` 表而不是日志 —— 这个进程里应用 logger
没有 handler，`logger.info` 写不到任何地方。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Mapping
from contextvars import Token, ContextVar
from dataclasses import dataclass
from typing import Any, get_args
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from ..schemas.event_collector import (
    AuditEvent,
    EmittedAuditEvent,
    EventModule,
    EventSource,
    EventStatus,
)

EVENT_LOGGER_NAME = "barong.audit_events"
DEFAULT_EVENT_BUFFER_SIZE = 5000
DEFAULT_EVENT_QUEUE_SIZE = 10000
DEFAULT_EVENT_QUEUE_BATCH_SIZE = 25
DEFAULT_EVENT_QUEUE_POLL_INTERVAL_SECONDS = 0.25
DEFAULT_EVENT_QUEUE_MAX_ATTEMPTS = 3
COLLECTOR_RECORD_PREFIX = "event-"

# --- 留存策略 -----------------------------------------------------------------
#
# 2026-09-01 实测：`event_streams` 2.0 GB / 107 万行，`storage_events` 1.0 GB /
# 107 万行，两张加起来占整库 64%，每小时各涨约 2,400 行。
#
# 而**读取侧只看最新的一小段**：`snapshot()` 按时间倒序取 `_snapshot_limit`
# （默认 5000）条；`storage_events` 全仓没有任何一处 SELECT，只写不读。
# 也就是说超过留存窗的行，写进去之后再也不会被任何代码看一眼。
#
# 90 天是刻意留宽的：这是审计留痕，不是缓存，宁可多留。真要缩短请改
# `EVENT_RETENTION_DAYS` 环境变量，别改这里的默认值。
DEFAULT_EVENT_RETENTION_DAYS = 90
# 每次删多少行。分批的理由不是性能，是**别开长事务**：一条 DELETE 扫 90 万行
# 会长时间持锁并把表撑肿，而这两张表正是全库写得最频繁的。
EVENT_RETENTION_BATCH_ROWS = 5000
# 两次清理之间至少隔多久。清理不是热路径，一小时一次足够，
# 频繁跑只会和写入抢锁。
EVENT_RETENTION_INTERVAL_SECONDS = 3600.0
# 清理语句自己的超时。全局 statement_timeout 是 8 秒 —— 那是给请求路径定的，
# 后台维护套用它会让清理在数据量一上来就永远超时，而异常又被吞成日志，
# 表现为「静默不生效、表继续涨」。2026-09-02 实测撞到过。
EVENT_RETENTION_STATEMENT_TIMEOUT_MS = 60000
# 咨询锁编号。生产上 5 个 gunicorn worker 各有一个清理线程，
# 让它们同时删同一批行只会互相抢锁，不会更快。
EVENT_RETENTION_ADVISORY_LOCK = 917_231_004
# 启动后多久跑第一轮。不是「等满一个间隔」——那样重启频繁就永远跑不到。
EVENT_RETENTION_FIRST_RUN_DELAY_SECONDS = 60.0
PLATFORM_ORG_ID = "platform"
VALID_EVENT_MODULES = frozenset(get_args(EventModule))
VALID_EVENT_SOURCES = frozenset(get_args(EventSource))
VALID_EVENT_STATUSES = frozenset(get_args(EventStatus))
MAX_STRING_LENGTH = 2000
SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "password_hash",
    "token",
    "secret",
    "session_id",
    "cookie",
    "set-cookie",
    "signature",
    "nonce",
    "idempotency",
    "authorization",
    "api_key",
    "private_key",
    "credential",
    "webhook_url",
    "provider_url",
    "endpoint",
)
HIGH_FREQUENCY_SUCCESS_EVENT_TYPES = frozenset(
    {
        "auth.session.validate",
        "rbac.check",
        "rbac.owner_check",
        "rbac.permission_check",
        # 2026-07-11 approved downsampling: per-request success events are
        # write amplification (one synchronous INSERT each on the hot path).
        # Failures of the same event types are still persisted, and the
        # control_plane.* audit trail stays untouched.
        "api.response.completed",
        "org_data_isolation.api_context",
        "permission_isolation.check",
    }
)
# Pending-status markers that only pair with a success outcome later; the
# failure completion event carries all investigative detail, so persisting
# the start marker per request is pure noise.
HIGH_FREQUENCY_PENDING_EVENT_TYPES = frozenset(
    {
        "api.request.received",
    }
)

_context_id: ContextVar[str | None] = ContextVar(
    "event_context_id",
    default=None,
)
_user_id: ContextVar[str | None] = ContextVar("event_user_id", default=None)
_product_key: ContextVar[str | None] = ContextVar(
    "event_product_key",
    default=None,
)
_workflow_id: ContextVar[str | None] = ContextVar(
    "event_workflow_id",
    default=None,
)
_org_id: ContextVar[str | None] = ContextVar("event_org_id", default=None)


@dataclass(frozen=True)
class EventQueueWriteResult:
    persisted: bool
    queued: bool
    record_id: str | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.persisted and self.queued and self.error is None


class EventQueueBackend:
    def __init__(
        self,
        *,
        queue_size: int = DEFAULT_EVENT_QUEUE_SIZE,
        snapshot_limit: int = DEFAULT_EVENT_BUFFER_SIZE,
        batch_size: int = DEFAULT_EVENT_QUEUE_BATCH_SIZE,
        poll_interval_seconds: float = DEFAULT_EVENT_QUEUE_POLL_INTERVAL_SECONDS,
        max_attempts: int = DEFAULT_EVENT_QUEUE_MAX_ATTEMPTS,
        auto_drain: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._queue_size = queue_size
        self._snapshot_limit = snapshot_limit
        self._batch_size = batch_size
        self._poll_interval_seconds = poll_interval_seconds
        self._max_attempts = max_attempts
        self._auto_drain = auto_drain
        self._failed = 0
        self._emitted = 0
        self._started = False
        self._worker: threading.Thread | None = None
        # 连续清理失败次数。只写日志的话，「静默不生效」和「一切正常」
        # 在 stats() 上长得一模一样 —— 这个计数让它们分得开。
        self._prune_failures = 0
        self._prune_runs = 0
        self._maintenance_worker: threading.Thread | None = None
        self._maintenance_stop = threading.Event()
        self._prune_lock_session = None
        self._logger = logging.getLogger(EVENT_LOGGER_NAME)
        self._tables_ready = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._worker = threading.Thread(
                target=self._drain,
                name="barong-audit-event-queue",
                daemon=True,
            )
            self._worker.start()
            self._started = True

    def emit(
        self,
        event: AuditEvent,
        *,
        org_id: str | None = None,
    ) -> EventQueueWriteResult:
        write = self._write_event(event, org_id=org_id)
        if not write.persisted or write.record_id is None:
            with self._lock:
                self._failed += 1
            return write

        if self._auto_drain:
            self.start()
            self._wake.set()
        with self._lock:
            self._emitted += 1
        return EventQueueWriteResult(
            persisted=True,
            queued=True,
            record_id=write.record_id,
        )

    def snapshot(self) -> list[AuditEvent]:
        self._ensure_tables()
        from sqlalchemy import select

        from ..db.session import managed_session
        from ..models.observability import EventStreamRecord, StorageEventRecord

        with managed_session() as db:
            rows = list(
                db.scalars(
                    select(EventStreamRecord)
                    .where(EventStreamRecord.record_id.like(f"{COLLECTOR_RECORD_PREFIX}%"))
                    .order_by(
                        EventStreamRecord.timestamp.desc(),
                        EventStreamRecord.id.desc(),
                    )
                    .limit(self._snapshot_limit)
                )
            )
        rows.reverse()
        return [self._audit_event_from_record(row) for row in rows]

    def clear(self) -> None:
        self._ensure_tables()
        from sqlalchemy import delete

        from ..db.session import managed_session
        from ..models.observability import EventStreamRecord, StorageEventRecord
        from .data_isolation import without_org_data_isolation

        with without_org_data_isolation():
            with managed_session() as db:
                db.execute(
                    delete(StorageEventRecord).where(
                        StorageEventRecord.record_id.like(
                            f"{COLLECTOR_RECORD_PREFIX}%"
                        )
                    )
                )
                db.execute(
                    delete(EventStreamRecord).where(
                        EventStreamRecord.record_id.like(
                            f"{COLLECTOR_RECORD_PREFIX}%"
                        )
                    )
                )
                db.commit()
        with self._lock:
            self._failed = 0
            self._emitted = 0
        self._wake.set()

    def stats(self) -> dict[str, int]:
        self._ensure_tables()
        from sqlalchemy import func, select

        from ..db.session import managed_session
        from ..models.observability import EventStreamRecord

        with managed_session() as db:
            stored = db.scalar(
                select(func.count())
                .select_from(EventStreamRecord)
                .where(EventStreamRecord.record_id.like(f"{COLLECTOR_RECORD_PREFIX}%"))
            )
            queued = db.scalar(
                select(func.count())
                .select_from(EventStreamRecord)
                .where(
                    EventStreamRecord.record_id.like(f"{COLLECTOR_RECORD_PREFIX}%"),
                    EventStreamRecord.processing_status.in_(
                        ("queued", "retry_pending", "backpressure")
                    ),
                )
            )
        with self._lock:
            return {
                "buffered": int(stored or 0),
                "queued": int(queued or 0),
                "emitted": self._emitted,
                "dropped": 0,
                "failed": self._failed,
                # >0 表示留存清理连续失败中 —— 那意味着表在无限增长。
                "prune_failures": self._prune_failures,
                # 0 表示清理从没跑过 —— 和「跑了但没删」是两回事。
                "prune_runs": self._prune_runs,
            }

    def _retention_days(self) -> int:
        """留存天数。0 或负数表示关闭清理（给需要长期取证时留的后门）。"""
        raw = os.getenv("EVENT_RETENTION_DAYS")
        if raw is None or not raw.strip():
            return DEFAULT_EVENT_RETENTION_DAYS
        try:
            return int(raw)
        except ValueError:
            self._logger.warning(
                "EVENT_RETENTION_DAYS 不是整数（%r），按默认 %s 天处理。",
                raw,
                DEFAULT_EVENT_RETENTION_DAYS,
            )
            return DEFAULT_EVENT_RETENTION_DAYS

    def prune_expired(self, *, max_batches: int = 4) -> dict[str, int]:
        """删掉超过留存窗的观测行。

        分批删而不是一条 DELETE 干完：这两张表是全库写得最频繁的，
        一条扫 90 万行的 DELETE 会长时间持锁、把表撑肿，还会把正在写入的
        请求拖住。每批 5000 行、每次最多 4 批，跑不完下一轮接着跑。

        返回删掉的行数，调用方可以据此判断还要不要接着跑。
        """
        days = self._retention_days()
        if days <= 0:
            return {"event_streams": 0, "storage_events": 0}

        self._ensure_tables()
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import text

        from ..db.session import managed_session
        from .data_isolation import (
            SKIP_ORG_DATA_ISOLATION,
            without_org_data_isolation,
        )

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = {"event_streams": 0, "storage_events": 0}

        # 观测表是跨组织的运维数据，清理按时间不按组织，所以显式跳过 C18G 守卫。
        # 用 per-statement 逃生口而不是整块 without_org_data_isolation()，
        # 让豁免范围只覆盖这两条语句。
        # **顺序不能反**：storage_events.record_id 有外键指向 event_streams.record_id，
        # 删除规则是 NO ACTION。先删父表会直接违反外键、清理一行都跑不动。
        # 子表先删干净，父表那一批才删得下去。
        with without_org_data_isolation():
            for table in ("storage_events", "event_streams"):
                for _ in range(max_batches):
                    with managed_session() as db:
                        # 后台维护不该用请求路径那 8 秒的预算。分批已经把单条
                        # 语句的规模压到 5000 行，给 60 秒是留裕量，不是放任。
                        db.execute(
                            text(
                                "SET LOCAL statement_timeout = "
                                f"{EVENT_RETENTION_STATEMENT_TIMEOUT_MS}"
                            )
                        )
                        result = db.execute(
                            text(
                                f"""
                                DELETE FROM {table}
                                WHERE ctid IN (
                                    SELECT ctid FROM {table}
                                    WHERE created_at < :cutoff
                                    LIMIT :batch
                                )
                                """
                            ),
                            {"batch": EVENT_RETENTION_BATCH_ROWS, "cutoff": cutoff},
                            execution_options=SKIP_ORG_DATA_ISOLATION,
                        )
                        db.commit()
                    removed = result.rowcount or 0
                    deleted[table] += removed
                    # **只有删到 0 行才算删完**。曾经写成「删得少于一批就退出」，
                    # 结果 2026-09-02 清存量时提前收工：报告「完成」，实际
                    # 还剩 192,474 行过期没删（跑第二遍才删掉）。
                    # 原因是 `ctid IN (子查询)` 在并发写入下会有部分 ctid 失效，
                    # 一批删得少于 LIMIT 是常态，**不代表没有更多了**。
                    if removed == 0:
                        break

        if deleted["event_streams"] or deleted["storage_events"]:
            self._logger.debug(
                "C17 观测留存清理：event_streams -%s 行，storage_events -%s 行"
                "（保留 %s 天）。",
                deleted["event_streams"],
                deleted["storage_events"],
                days,
            )
        return deleted

    def start_maintenance(self) -> None:
        """启动留存清理线程。

        **刻意不挂在 `_drain` 上**：那个消费循环需要 `auto_drain=True` 或有人
        显式调 `start()` 才会跑，而 `DEFAULT_EVENT_EMITTER` 用的是默认值
        `auto_drain=False`，全仓也没有任何地方调用 `start()` ——
        2026-09-02 在生产实测：`_started=False`、`_worker=None`，
        那个循环**从来没运行过**（这也是 107 万条事件卡在 queued 的原因）。
        把清理挂上去等于写了个永不执行的功能。

        所以清理走自己的线程，不依赖队列消费是否开启。
        """
        with self._lock:
            if self._maintenance_worker is not None:
                return
            self._maintenance_worker = threading.Thread(
                target=self._maintenance_loop,
                name="c17-retention",
                daemon=True,
            )
            self._maintenance_worker.start()

    def _maintenance_loop(self) -> None:
        # **先等一小段再跑第一轮，而不是等满一小时**：容器重启比一小时频繁时，
        # 「等满再跑」意味着清理永远轮不到执行 —— 又是一个「看起来做了、其实不跑」。
        # 60 秒是给应用启动让路，别和冷启的那波请求抢连接。
        if self._maintenance_stop.wait(EVENT_RETENTION_FIRST_RUN_DELAY_SECONDS):
            return
        self._prune_once()
        while not self._maintenance_stop.wait(EVENT_RETENTION_INTERVAL_SECONDS):
            self._prune_once()

    def stop_maintenance(self) -> None:
        self._maintenance_stop.set()

    def _prune_once(self) -> None:
        """清理一轮。失败只记日志并计数，绝不影响事件落库。"""
        try:
            if not self._acquire_prune_lock():
                return
            try:
                deleted = self.prune_expired()
            finally:
                self._release_prune_lock()
            self._prune_failures = 0
            self._prune_runs += 1
            self._record_heartbeat(deleted=deleted)
        except Exception as exc:
            self._prune_failures += 1
            # exception 是 ERROR 级，这条能到 stdout；info 不行（见 _record_heartbeat）。
            self._logger.exception(
                "C17 观测留存清理失败（连续第 %s 次，不影响事件落库）。",
                self._prune_failures,
            )
            self._record_heartbeat_failure(str(exc))

    def _record_heartbeat(self, *, deleted: dict[str, int]) -> None:
        """把「这一轮真的跑完了」记进 worker_heartbeats。

        **为什么不用日志**：2026-09-02 实测，这个进程里的应用 logger
        没有任何 handler、有效级别是 WARNING —— `logger.info()` 写不到任何地方，
        整个生产日志里一条应用级 INFO 都没有。拿它当观测手段等于没有观测。

        心跳表是 Phase 5 专门为「后台任务到底有没有在干活」建的，
        不依赖控制台、有独立检查脚本，是这里唯一靠得住的通道。

        一轮删 0 行**也算干成活**：留存窗内没有过期行是一个**已核实**的结论，
        不是空转。真正要能看见的失败（线程没起来、语句超时）走 record_failure，
        两者在 last_success_at / last_attempt_at 的距离上分得开。
        """
        from ..db.session import managed_session
        from .worker_heartbeat import record_success

        total = deleted["event_streams"] + deleted["storage_events"]
        try:
            with managed_session() as db:
                record_success(
                    db,
                    worker_name="c17-retention",
                    module_key=f"deleted={total}",
                    expected_interval_seconds=int(EVENT_RETENTION_INTERVAL_SECONDS * 2),
                )
                db.commit()
        except Exception:
            self._logger.exception("C17 留存清理心跳写入失败。")

    def _record_heartbeat_failure(self, error: str) -> None:
        from ..db.session import managed_session
        from .worker_heartbeat import record_failure

        try:
            with managed_session() as db:
                record_failure(
                    db,
                    worker_name="c17-retention",
                    error=error[:500],
                    expected_interval_seconds=int(EVENT_RETENTION_INTERVAL_SECONDS * 2),
                )
                db.commit()
        except Exception:
            self._logger.exception("C17 留存清理失败心跳写入失败。")

    def _acquire_prune_lock(self) -> bool:
        """Postgres 咨询锁：5 个 gunicorn worker 里只让一个真去删。

        拿不到锁就直接跳过 —— 说明别的进程正在清，不必排队。
        """
        from sqlalchemy import text

        from ..db.session import managed_session

        with managed_session() as db:
            if db.get_bind().dialect.name != "postgresql":
                return True
            acquired = db.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": EVENT_RETENTION_ADVISORY_LOCK},
            )
            self._prune_lock_session = db if acquired else None
            return bool(acquired)

    def _release_prune_lock(self) -> None:
        from sqlalchemy import text

        from ..db.session import managed_session

        with managed_session() as db:
            if db.get_bind().dialect.name != "postgresql":
                return
            db.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": EVENT_RETENTION_ADVISORY_LOCK},
            )

    def _drain(self) -> None:
        while True:
            try:
                record_ids = self._claim_queued_records()
            except StaleDataError:
                self._logger.debug(
                    "C17 event queue claim skipped records that disappeared."
                )
                continue
            if not record_ids:
                self._wake.wait(self._poll_interval_seconds)
                self._wake.clear()
                continue
            for record_id in record_ids:
                try:
                    self._process_record(record_id)
                except StaleDataError:
                    self._logger.debug(
                        "C17 event queue record disappeared before processing completed: %s",
                        record_id,
                    )
                except Exception as exc:
                    self._logger.exception(
                        "C17 event queue processing failed for %s",
                        record_id,
                    )
                    try:
                        self._mark_processing_failure(record_id, error=str(exc))
                    except Exception:
                        self._logger.exception(
                            "C17 event queue failed to mark processing failure for %s",
                            record_id,
                        )
            self._wake.wait(min(self._poll_interval_seconds, 0.05))
            self._wake.clear()

    def _write_event(
        self,
        event: AuditEvent,
        *,
        org_id: str | None,
    ) -> EventQueueWriteResult:
        try:
            self._ensure_tables()
            from ..db.session import managed_session
            from ..models.observability import EventStreamRecord, StorageEventRecord
            from .data_isolation import without_org_data_isolation
            from .storage_layer import storage_record_from_event_raw

            record = storage_record_from_event_raw(event)
            record.record_id = f"{COLLECTOR_RECORD_PREFIX}{event.event_id}"
            metadata = {
                **dict(event.metadata),
                "c17_collector": "EventQueueBackend",
            }
            resolved_org_id = self._resolve_org_id(
                event,
                explicit_org_id=org_id,
            )
            row = EventStreamRecord(
                org_id=resolved_org_id,
                record_id=record.record_id,
                entity_type=record.entity_type,
                event_id=record.event_id,
                context_id=record.context_id,
                trace_id=record.trace_id,
                product_key=record.product_key,
                user_id=record.user_id,
                workflow_id=event.workflow_id,
                job_id=self._string_payload_value(event, "job_id"),
                actor_id=self._string_payload_value(event, "actor_id"),
                module_id=record.module,
                event_type=record.event_type,
                action=event.action,
                source=event.source,
                status=record.status,
                latency_ms=event.latency_ms,
                timestamp=record.timestamp,
                storage_tier=record.tier,
                backend_targets=list(record.backend_targets),
                payload=record.payload,
                metadata_json=metadata,
                compressed=record.compressed,
                archive_object_key=record.archive_object_key,
                processing_status="queued",
                processing_attempts=0,
            )
            with without_org_data_isolation():
                with managed_session() as db:
                    db.add(row)
                    db.add(
                        StorageEventRecord(
                            org_id=resolved_org_id,
                            storage_event_id=f"storage-event-{uuid4()}",
                            record_id=record.record_id,
                            operation="collector_write",
                            entity_type=record.entity_type,
                            context_id=record.context_id,
                            trace_id=record.trace_id,
                            event_id=record.event_id,
                            module_id=record.module,
                            storage_tier=record.tier,
                            backend_targets=list(record.backend_targets),
                            status="queued",
                            payload={
                                "collector": "EventQueueBackend",
                                "processing_status": "queued",
                            },
                            occurred_at=event.timestamp,
                        )
                    )
                    db.commit()
            return EventQueueWriteResult(
                persisted=True,
                queued=False,
                record_id=record.record_id,
            )
        except SQLAlchemyError as exc:
            return EventQueueWriteResult(
                persisted=False,
                queued=False,
                error=str(exc),
            )
        except Exception as exc:
            return EventQueueWriteResult(
                persisted=False,
                queued=False,
                error=str(exc),
            )

    def _ensure_tables(self) -> None:
        if self._tables_ready:
            return
        with self._lock:
            if self._tables_ready:
                return
            from ..db.base import Base
            from ..db.session import engine
            from ..models.observability import (
                AnomalyEventRecord,
                AuditLogRecord,
                EventStreamRecord,
                ReplayJobRecord,
                StorageEventRecord,
            )
            from ..models.execution_state import DLQStateRecord

            Base.metadata.create_all(
                bind=engine,
                tables=[
                    DLQStateRecord.__table__,
                    EventStreamRecord.__table__,
                    AuditLogRecord.__table__,
                    ReplayJobRecord.__table__,
                    AnomalyEventRecord.__table__,
                    StorageEventRecord.__table__,
                ],
                checkfirst=True,
            )
            self._tables_ready = True

    def _resolve_org_id(
        self,
        event: AuditEvent,
        *,
        explicit_org_id: str | None,
    ) -> str:
        for value in (explicit_org_id, _org_id.get()):
            if isinstance(value, str) and value.strip():
                return value.strip()[:40]

        try:
            from .data_isolation import current_org_data_isolation_context

            context = current_org_data_isolation_context()
        except Exception:
            context = None
        if context is not None and context.org_id:
            return context.org_id[:40]

        for source in (event.metadata, event.payload):
            for key in ("org_id", "active_org_id", "tenant_org_id"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:40]
        return PLATFORM_ORG_ID

    def _mark_processing_status(
        self,
        record_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        self._ensure_tables()
        from datetime import UTC, datetime

        from sqlalchemy import update

        from ..db.session import managed_session
        from ..models.observability import EventStreamRecord
        from .data_isolation import without_org_data_isolation

        with without_org_data_isolation():
            with managed_session() as db:
                db.execute(
                    update(EventStreamRecord)
                    .where(EventStreamRecord.record_id == record_id)
                    .values(
                        processing_status=status,
                        processing_error=error,
                        processed_at=datetime.now(UTC),
                    )
                )
                db.commit()

    def _queued_count(self) -> int:
        self._ensure_tables()
        from sqlalchemy import func, select

        from ..db.session import managed_session
        from ..models.observability import EventStreamRecord
        from .data_isolation import without_org_data_isolation

        with without_org_data_isolation():
            with managed_session() as db:
                value = db.scalar(
                    select(func.count())
                    .select_from(EventStreamRecord)
                    .where(
                        EventStreamRecord.record_id.like(
                            f"{COLLECTOR_RECORD_PREFIX}%"
                        ),
                        EventStreamRecord.processing_status.in_(
                            ("queued", "retry_pending", "backpressure")
                        ),
                    )
                )
        return int(value or 0)

    def _claim_queued_records(self) -> list[str]:
        self._ensure_tables()
        from datetime import UTC, datetime

        from sqlalchemy import or_, select

        from ..db.session import managed_session
        from ..models.observability import EventStreamRecord
        from .data_isolation import without_org_data_isolation

        now = datetime.now(UTC)
        with without_org_data_isolation():
            with managed_session() as db:
                statement = (
                    select(EventStreamRecord)
                    .where(
                        EventStreamRecord.record_id.like(
                            f"{COLLECTOR_RECORD_PREFIX}%"
                        ),
                        EventStreamRecord.processing_status.in_(
                            ("queued", "retry_pending", "backpressure")
                        ),
                        or_(
                            EventStreamRecord.next_retry_at.is_(None),
                            EventStreamRecord.next_retry_at <= now,
                        ),
                    )
                    .order_by(EventStreamRecord.id)
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True)
                )
                rows = list(db.scalars(statement))
                for row in rows:
                    row.processing_status = "processing"
                    row.processing_attempts = int(row.processing_attempts or 0) + 1
                    row.processing_error = None
                db.commit()
                return [row.record_id for row in rows]

    def _mark_processing_failure(
        self,
        record_id: str,
        *,
        error: str,
    ) -> None:
        self._ensure_tables()
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import select

        from ..db.session import managed_session
        from ..models.execution_state import DLQStateRecord
        from ..models.observability import EventStreamRecord
        from .data_isolation import without_org_data_isolation

        with without_org_data_isolation():
            with managed_session() as db:
                row = db.scalar(
                    select(EventStreamRecord).where(
                        EventStreamRecord.record_id == record_id
                    )
                )
                if row is None:
                    return

                attempts = int(row.processing_attempts or 0)
                if attempts < self._max_attempts:
                    row.processing_status = "retry_pending"
                    row.processing_error = error
                    row.next_retry_at = datetime.now(UTC) + timedelta(
                        seconds=min(2 ** attempts, 60)
                    )
                    db.commit()
                    return

                row.processing_status = "dlq"
                row.processing_error = error
                row.processed_at = datetime.now(UTC)
                dlq_id = f"event-dlq-{row.record_id}"
                existing = db.scalar(
                    select(DLQStateRecord).where(DLQStateRecord.dlq_id == dlq_id)
                )
                if existing is None:
                    db.add(
                        DLQStateRecord(
                            org_id=row.org_id,
                            dlq_id=dlq_id,
                            context_id=row.context_id,
                            execution_id=row.context_id,
                            trace_id=row.trace_id,
                            job_id=row.job_id,
                            actor_id=row.actor_id or row.user_id,
                            module_key=row.module_id,
                            workflow_id=row.workflow_id,
                            failure_type="manual_failure",
                            status="queued",
                            reason="C17 event queue processing exhausted retries.",
                            payload={
                                "record_id": row.record_id,
                                "event_id": row.event_id,
                                "processing_error": error,
                            },
                            failure_context={
                                "event_stream_record_id": row.record_id,
                                "event_type": row.event_type,
                                "attempts": attempts,
                            },
                            retry_decision={},
                            attempt=attempts,
                            retry_count=attempts,
                            replayable=True,
                            last_error=error,
                        )
                    )
                db.commit()

    def _process_record(self, record_id: str) -> None:
        self._ensure_tables()
        from datetime import UTC, datetime

        from sqlalchemy import select

        from ..db.session import managed_session
        from ..models.observability import EventStreamRecord
        from .audit_query_engine import AuditLogWriter
        from .data_isolation import without_org_data_isolation

        with without_org_data_isolation():
            with managed_session() as db:
                row = db.scalar(
                    select(EventStreamRecord).where(
                        EventStreamRecord.record_id == record_id
                    )
                )
                if row is None:
                    return
                event = self._audit_event_from_record(row)
                self._logger.info(
                    json.dumps(event.model_dump(mode="json"), sort_keys=True)
                )
                AuditLogWriter(db, org_id=row.org_id).write_event_stream(row)
                row.processing_status = "processed"
                row.processing_error = None
                row.next_retry_at = None
                row.processed_at = datetime.now(UTC)
                db.commit()

    def _audit_event_from_record(self, row: Any) -> AuditEvent:
        payload = row.payload if isinstance(row.payload, Mapping) else {}
        raw_payload = payload.get("payload") if isinstance(payload, Mapping) else {}
        raw_metadata = payload.get("metadata") if isinstance(payload, Mapping) else {}
        module = row.module_id if row.module_id in VALID_EVENT_MODULES else "system"
        source = row.source if row.source in VALID_EVENT_SOURCES else "system"
        status = row.status if row.status in VALID_EVENT_STATUSES else "pending"
        return AuditEvent(
            event_id=row.event_id,
            timestamp=row.timestamp,
            event_type=row.event_type,
            module=module,
            action=row.action,
            context_id=row.context_id,
            user_id=row.user_id,
            product_key=row.product_key,
            workflow_id=row.workflow_id,
            source=source,
            status=status,
            latency_ms=max(float(row.latency_ms or 0), 0),
            payload=dict(raw_payload or {}),
            metadata=dict(raw_metadata or {}),
        )

    def _string_payload_value(self, event: AuditEvent, key: str) -> str | None:
        for source in (event.payload, event.metadata):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:128]
            if value is not None and not isinstance(value, (dict, list, tuple)):
                return str(value).strip()[:128]
        return None


EventEmitter = EventQueueBackend
DEFAULT_EVENT_EMITTER = EventQueueBackend()


def _truncate(value: str) -> str:
    if len(value) <= MAX_STRING_LENGTH:
        return value
    return f"{value[:MAX_STRING_LENGTH]}...[truncated]"


def sanitize_event_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(marker in normalized_key for marker in SENSITIVE_KEY_MARKERS):
                sanitized[str(key)] = "[redacted]"
                continue
            sanitized[str(key)] = sanitize_event_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_event_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_event_payload(item) for item in value]
    if isinstance(value, str):
        return _truncate(value)
    return value


def generate_context_id() -> str:
    return str(uuid4())


def normalize_context_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate or len(candidate) > 128:
        return generate_context_id()
    lowered = candidate.lower()
    if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
        return generate_context_id()
    return candidate


def current_context_id() -> str | None:
    return _context_id.get()


def set_current_event_context(
    *,
    context_id: str | None = None,
    user_id: str | None = None,
    product_key: str | None = None,
    workflow_id: str | None = None,
    org_id: str | None = None,
) -> dict[str, Token[str | None]]:
    tokens: dict[str, Token[str | None]] = {}
    if context_id is not None:
        tokens["context_id"] = _context_id.set(normalize_context_id(context_id))
    if user_id is not None:
        tokens["user_id"] = _user_id.set(user_id)
    if product_key is not None:
        tokens["product_key"] = _product_key.set(product_key)
    if workflow_id is not None:
        tokens["workflow_id"] = _workflow_id.set(workflow_id)
    if org_id is not None:
        tokens["org_id"] = _org_id.set(org_id)
    return tokens


def reset_current_event_context(tokens: Mapping[str, Token[str | None]]) -> None:
    resetters = {
        "context_id": _context_id,
        "user_id": _user_id,
        "product_key": _product_key,
        "workflow_id": _workflow_id,
        "org_id": _org_id,
    }
    for key, token in tokens.items():
        resetters[key].reset(token)


def emit_event(
    *,
    event_type: str,
    module: EventModule = "system",
    action: str,
    source: EventSource = "backend",
    status: EventStatus = "success",
    context_id: str | None = None,
    user_id: str | None = None,
    product_key: str | None = None,
    workflow_id: str | None = None,
    org_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> EmittedAuditEvent:
    effective_context_id = normalize_context_id(context_id or _context_id.get())
    event = AuditEvent(
        event_type=event_type,
        module=module,
        action=action,
        context_id=effective_context_id,
        user_id=user_id if user_id is not None else _user_id.get(),
        product_key=(
            product_key if product_key is not None else _product_key.get()
        ),
        workflow_id=(
            workflow_id if workflow_id is not None else _workflow_id.get()
        ),
        source=source,
        status=status,
        latency_ms=max(latency_ms, 0),
        payload=sanitize_event_payload(dict(payload or {})),
        metadata=sanitize_event_payload(dict(metadata or {})),
    )
    if (status == "success" and event_type in HIGH_FREQUENCY_SUCCESS_EVENT_TYPES) or (
        status == "pending" and event_type in HIGH_FREQUENCY_PENDING_EVENT_TYPES
    ):
        return EmittedAuditEvent(
            **event.model_dump(mode="python"),
            persisted=False,
            queued=False,
            success=True,
            error=None,
        )
    result = DEFAULT_EVENT_EMITTER.emit(event, org_id=org_id)
    return EmittedAuditEvent(
        **event.model_dump(mode="python"),
        persisted=result.persisted,
        queued=result.queued,
        success=result.success,
        error=result.error,
    )


def classify_module_from_path(path: str) -> EventModule:
    normalized = path.lower()
    if "/module-switch" in normalized or "/emergency-kill-switch" in normalized:
        return "C13"
    if any(
        marker in normalized
        for marker in (
            "/external-dependencies",
            "/dependency",
            "/ai-execution-bindings",
            "/model-locks",
            "/capability-bindings",
            "/module-allocations",
            "/execution-prompts",
        )
    ):
        return "C14"
    if any(
        marker in normalized
        for marker in (
            "/workflow",
            "/webhook-gateway",
            "/payload-standardization",
            "/callback-handler",
            "/result-normalization",
            "/failure-handling",
            "/n8n-test",
        )
    ):
        return "C15"
    if "/security" in normalized or "/control-plane" in normalized:
        return "C16"
    if "/products" in normalized or "/product" in normalized:
        return "Pxx"
    return "system"


def record_workflow_event(
    *,
    event_type: str,
    action: str,
    context_id: str,
    workflow_id: str | None,
    module_key: str | None = None,
    status: EventStatus = "success",
    source: EventSource = "n8n",
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=event_type,
        module="C15",
        action=action,
        source=source,
        status=status,
        context_id=context_id,
        workflow_id=workflow_id,
        latency_ms=latency_ms,
        payload={"module": module_key, **dict(payload or {})},
        metadata=metadata,
    )


def record_llm_request(
    *,
    provider: str,
    model: str,
    context_id: str | None = None,
    prompt_input: Any = None,
    workflow_id: str | None = None,
    module: EventModule = "C14",
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type="ai.llm.request",
        module=module,
        action="llm.request",
        source="ai",
        status="pending",
        context_id=context_id,
        workflow_id=workflow_id,
        payload={
            "provider": provider,
            "model": model,
            "prompt_input": prompt_input,
        },
        metadata=metadata,
    )


def record_llm_response(
    *,
    provider: str,
    model: str,
    status: EventStatus,
    context_id: str | None = None,
    prompt_output: Any = None,
    token_usage: Mapping[str, Any] | None = None,
    workflow_id: str | None = None,
    latency_ms: float = 0,
    module: EventModule = "C14",
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type="ai.llm.response",
        module=module,
        action="llm.response",
        source="ai",
        status=status,
        context_id=context_id,
        workflow_id=workflow_id,
        latency_ms=latency_ms,
        payload={
            "provider": provider,
            "model": model,
            "prompt_output": prompt_output,
            "token_usage": dict(token_usage or {}),
        },
        metadata=metadata,
    )


def record_file_operation(
    *,
    action: str,
    storage_provider: str,
    storage_ref: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=f"file.{action}",
        module="system",
        action=f"file.{action}",
        source="system",
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload={
            "storage_provider": storage_provider,
            "storage_ref": storage_ref,
            **dict(payload or {}),
        },
        metadata=metadata,
    )


def record_filebrowser_operation(
    *,
    action: str,
    path: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return record_file_operation(
        action=action,
        storage_provider="FileBrowser",
        storage_ref=path,
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload=payload,
        metadata=metadata,
    )


def record_minio_operation(
    *,
    action: str,
    object_key: str | None = None,
    bucket: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return record_file_operation(
        action=action,
        storage_provider="MinIO",
        storage_ref=object_key,
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload={"bucket": bucket, **dict(payload or {})},
        metadata=metadata,
    )


def record_product_knowledge_event(
    *,
    action: str,
    status: EventStatus = "success",
    context_id: str | None = None,
    product_key: str | None = None,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=f"product_knowledge.{action}",
        module="Pxx",
        action=f"product_knowledge.{action}",
        source="system",
        status=status,
        context_id=context_id,
        product_key=product_key,
        payload=payload,
        metadata=metadata,
    )


def get_event_buffer_snapshot() -> list[AuditEvent]:
    return DEFAULT_EVENT_EMITTER.snapshot()


def clear_event_buffer() -> None:
    DEFAULT_EVENT_EMITTER.clear()


def get_event_emitter_stats() -> dict[str, int]:
    return DEFAULT_EVENT_EMITTER.stats()
