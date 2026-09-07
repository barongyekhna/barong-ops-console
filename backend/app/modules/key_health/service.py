"""Execution and read models for the hourly key health monitor."""

from __future__ import annotations

import logging
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterator

from sqlalchemy import select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ...core.key_registry import infer_key_type_from_record
from ...core.roles import is_owner_role
from ...db.session import engine, managed_read_session, managed_session
from ...models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from ...models.key_health import KeyHealthCheck, KeyHealthRun, KeyHealthState
from ...models.user import User
from ...services.api_key_orchestration import _decrypt_key_value
from ...services.data_isolation import without_org_data_isolation
from ..notifications.service import create_notification
from .probes import HEALTHY, WARNING_STATUSES, ProbeResult, ProbeTarget, safe_probe_target
from ...services.data_isolation import SKIP_ORG_DATA_ISOLATION


logger = logging.getLogger(__name__)

RUN_LOCK_ID = 1_264_938_312
NOTIFICATION_REPEAT_AFTER = timedelta(hours=24)
# 业务 worker 回报的「运行时事故」（余额 0 / 套餐额度用完）在 state.details 里的键。
# 定时探针都是零消耗的，看不见这两种情况；事故未过期前探针的 healthy 不能把它冲绿。
RUNTIME_INCIDENT_KEY = "runtime_incident"
RUNTIME_INCIDENT_TTL = timedelta(hours=24)
RUNTIME_INCIDENT_STATUS = "provider_error"
RUNTIME_RECOVERED_REASON = "runtime_call_ok"
ABANDONED_RUN_AFTER = timedelta(minutes=20)
DEFAULT_PROBE_CONCURRENCY = 4
MAX_PROBE_CONCURRENCY = 8

_process_run_lock = threading.Lock()


class KeyHealthRunInProgress(RuntimeError):
    pass


@dataclass(frozen=True)
class RunOutcome:
    run_id: int
    created: bool
    status: str
    total_count: int
    healthy_count: int
    warning_count: int
    failed_count: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def scheduled_hour(value: datetime | None = None) -> datetime:
    current = value or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _probe_concurrency() -> int:
    try:
        configured = int(os.getenv("KEY_HEALTH_PROBE_CONCURRENCY", ""))
    except ValueError:
        configured = DEFAULT_PROBE_CONCURRENCY
    return max(1, min(configured or DEFAULT_PROBE_CONCURRENCY, MAX_PROBE_CONCURRENCY))


def _try_postgres_lock(connection: Connection) -> bool:
    acquired = bool(
        connection.scalar(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": RUN_LOCK_ID},
        )
    )
    connection.commit()
    return acquired


@contextmanager
def exclusive_run_lock() -> Iterator[None]:
    if engine.dialect.name != "postgresql":
        acquired = _process_run_lock.acquire(blocking=False)
        if not acquired:
            raise KeyHealthRunInProgress("key_health_run_in_progress")
        try:
            yield
        finally:
            _process_run_lock.release()
        return

    connection = engine.connect()
    acquired = False
    try:
        acquired = _try_postgres_lock(connection)
        if not acquired:
            raise KeyHealthRunInProgress("key_health_run_in_progress")
        yield
    finally:
        if acquired:
            try:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": RUN_LOCK_ID},
                    execution_options=SKIP_ORG_DATA_ISOLATION,
                )
                connection.commit()
            except Exception:
                logger.exception("Failed to release key health advisory lock")
        connection.close()


def _owner_user_ids() -> tuple[str, ...]:
    with without_org_data_isolation(), managed_read_session() as db:
        users = list(db.scalars(select(User).where(User.is_active.is_(True))))
        return tuple(str(user.id) for user in users if is_owner_role(user.role))


def _load_probe_targets() -> list[ProbeTarget]:
    with without_org_data_isolation(), managed_read_session() as db:
        keys = list(
            db.scalars(
                select(ApiKeyRecord)
                .where(ApiKeyRecord.status == "active")
                .order_by(ApiKeyRecord.id.asc())
            )
        )
        key_ids = [row.key_id for row in keys]
        bindings = (
            list(
                db.scalars(
                    select(ApiKeyModuleBindingRecord).where(
                        ApiKeyModuleBindingRecord.key_id.in_(key_ids),
                        ApiKeyModuleBindingRecord.status == "active",
                    )
                )
            )
            if key_ids
            else []
        )
        aliases_by_key: dict[str, set[str]] = {}
        for binding in bindings:
            aliases_by_key.setdefault(binding.key_id, set()).add(binding.key_alias)

        targets: list[ProbeTarget] = []
        for row in keys:
            metadata = dict(row.metadata_json or {})
            key_type = infer_key_type_from_record(
                name=row.name,
                url=row.url,
                metadata=metadata,
            )
            secret_value: str | None = None
            load_error: str | None = None
            try:
                secret_value = _decrypt_key_value(row.encrypted_key_value)
            except Exception:
                load_error = "secret_decryption_failed"
            aliases = set(aliases_by_key.get(row.key_id, set()))
            for field in ("key_alias", "default_alias"):
                value = str(metadata.get(field) or "").strip()
                if value:
                    aliases.add(value)
            targets.append(
                ProbeTarget(
                    key_id=row.key_id,
                    org_id=row.org_id,
                    name=row.name,
                    url=row.url,
                    key_hash_prefix=row.key_hash_prefix,
                    key_type=key_type,
                    aliases=tuple(sorted(aliases)),
                    secret_value=secret_value,
                    metadata=metadata,
                    load_error=load_error,
                )
            )
    return targets


def _mark_abandoned_runs(db: Session, *, now: datetime) -> None:
    db.execute(
        update(KeyHealthRun)
        .where(
            KeyHealthRun.status == "running",
            KeyHealthRun.started_at < now - ABANDONED_RUN_AFTER,
        )
        .values(
            status="failed",
            completed_at=now,
            error_code="worker_abandoned",
        )
    )


def _create_run(
    *,
    trigger: str,
    scheduled_for: datetime,
) -> tuple[KeyHealthRun, bool]:
    now = utc_now()
    with without_org_data_isolation(), managed_session() as db:
        _mark_abandoned_runs(db, now=now)
        existing = db.scalar(
            select(KeyHealthRun).where(KeyHealthRun.scheduled_for == scheduled_for)
        )
        if existing is not None:
            return existing, False
        row = KeyHealthRun(
            scheduled_for=scheduled_for,
            trigger=trigger[:24],
            status="running",
            worker_id=f"{socket.gethostname()}:{os.getpid()}",
            started_at=now,
            total_count=0,
            healthy_count=0,
            warning_count=0,
            failed_count=0,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        return row, True


def _should_notify(
    *,
    previous_status: str | None,
    previous_notified_at: datetime | None,
    new_status: str,
    now: datetime,
) -> bool:
    if new_status == HEALTHY:
        return previous_status is not None and previous_status != HEALTHY
    if previous_status != new_status or previous_notified_at is None:
        return True
    if previous_notified_at.tzinfo is None:
        previous_notified_at = previous_notified_at.replace(tzinfo=UTC)
    return now - previous_notified_at.astimezone(UTC) >= NOTIFICATION_REPEAT_AFTER


def _notification_text(
    target: ProbeTarget,
    result: ProbeResult,
    *,
    recovered: bool,
) -> tuple[str, str, str, str]:
    identity = f"{target.name} (hash {target.key_hash_prefix})"
    if recovered:
        return (
            "success",
            "key_health.recovered",
            "密钥检测已恢复",
            f"{identity} 已恢复正常，检测适配器：{result.adapter}。",
        )
    if result.status in WARNING_STATUSES:
        return (
            "warning",
            "key_health.warning",
            "密钥检测警告",
            f"{identity} 当前状态：{result.reason_code}。",
        )
    return (
        "error",
        "key_health.failed",
        "密钥检测失败",
        f"{identity} 无法通过最小检测：{result.reason_code}。",
    )


def _persist_result(
    *,
    run_id: int,
    target: ProbeTarget,
    result: ProbeResult,
    owner_user_ids: tuple[str, ...],
) -> None:
    now = result.checked_at
    state_details = dict(result.details)
    state_details["latency_ms"] = result.latency_ms
    if result.http_status is not None:
        state_details["http_status"] = result.http_status
    with without_org_data_isolation(), managed_session() as db:
        db.add(
            KeyHealthCheck(
                run_id=run_id,
                key_id=target.key_id,
                org_id=target.org_id,
                key_name=target.name,
                key_hash_prefix=target.key_hash_prefix,
                key_type=target.key_type,
                adapter=result.adapter,
                status=result.status,
                reason_code=result.reason_code,
                http_status=result.http_status,
                latency_ms=result.latency_ms,
                checked_at=result.checked_at,
                details_json=dict(result.details),
            )
        )
        state = db.scalar(
            select(KeyHealthState).where(KeyHealthState.key_id == target.key_id)
        )
        previous_status = state.current_status if state is not None else None
        previous_notified_at = state.last_notified_at if state is not None else None
        if state is None:
            state = KeyHealthState(
                key_id=target.key_id,
                org_id=target.org_id,
                key_name=target.name,
                key_hash_prefix=target.key_hash_prefix,
                key_type=target.key_type,
                adapter=result.adapter,
                current_status=result.status,
                reason_code=result.reason_code,
                last_checked_at=now,
                consecutive_failures=0,
                details_json={},
            )
            db.add(state)

        incident = _active_runtime_incident(state.details_json, now=now)
        effective_status = result.status
        effective_reason = result.reason_code
        if incident is not None:
            # 探针零消耗看不见余额/套餐，业务侧回报的事故未过期前不许冲绿。
            state_details[RUNTIME_INCIDENT_KEY] = incident
            if result.status == HEALTHY:
                effective_status = RUNTIME_INCIDENT_STATUS
                effective_reason = str(incident.get("reason_code") or result.reason_code)
        notify = _should_notify(
            previous_status=previous_status,
            previous_notified_at=previous_notified_at,
            new_status=effective_status,
            now=now,
        )

        state.org_id = target.org_id
        state.key_name = target.name
        state.key_hash_prefix = target.key_hash_prefix
        state.key_type = target.key_type
        state.adapter = result.adapter
        state.current_status = effective_status
        state.reason_code = effective_reason
        state.last_checked_at = now
        state.details_json = state_details
        if effective_status == HEALTHY:
            state.last_success_at = now
            state.consecutive_failures = 0
        else:
            state.last_failure_at = now
            state.consecutive_failures = int(state.consecutive_failures or 0) + 1

        if notify:
            recovered = effective_status == HEALTHY and previous_status != HEALTHY
            level, event_type, title, body = _notification_text(
                target,
                result,
                recovered=recovered,
            )
            for owner_user_id in owner_user_ids:
                create_notification(
                    db,
                    event_type=event_type,
                    title=title,
                    body=body,
                    level=level,
                    source="key.health",
                    org_id=target.org_id,
                    recipient_user_id=owner_user_id,
                    external_refs={"url": "/key-health"},
                    payload={
                        "key_hash_prefix": target.key_hash_prefix,
                        "status": result.status,
                        "reason_code": result.reason_code,
                        "adapter": result.adapter,
                    },
                )
            if owner_user_ids:
                state.last_notified_at = now


# ------------------------------------------------- runtime incident reports
def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _active_runtime_incident(
    details: dict[str, object] | None,
    *,
    now: datetime,
) -> dict[str, object] | None:
    incident = (details or {}).get(RUNTIME_INCIDENT_KEY)
    if not isinstance(incident, dict):
        return None
    expires_at = _parse_iso(incident.get("expires_at"))
    if expires_at is None or expires_at <= now:
        return None
    return dict(incident)


def _active_keys_of_type(db: Session, key_type: str) -> list[ApiKeyRecord]:
    keys = list(
        db.scalars(
            select(ApiKeyRecord)
            .where(ApiKeyRecord.status == "active")
            .order_by(ApiKeyRecord.id.asc())
        )
    )
    matched: list[ApiKeyRecord] = []
    for row in keys:
        try:
            inferred = infer_key_type_from_record(
                name=row.name,
                url=row.url,
                metadata=dict(row.metadata_json or {}),
            )
        except Exception:
            continue
        if inferred == key_type:
            matched.append(row)
    return matched


def report_runtime_incident(
    *,
    key_type: str,
    reason_code: str,
    message: str,
    source: str = "worker",
    ttl: timedelta = RUNTIME_INCIDENT_TTL,
) -> int:
    """业务调用撞上「余额不足 / 套餐额度用完」时由 worker 回报。

    定时探针零消耗，看不见这两种事故（DeepSeek models 列表照样 200、1688 只探
    网关可达），2026-09-05 就这样绿了三天。回报后 state 立刻变 provider_error，
    事故带 24h 过期时间，期间探针的 healthy 不冲绿；同 provider 一次业务成功
    调 report_runtime_recovered 清掉。不建 KeyHealthCheck 行（(run_id,key_id)
    唯一约束是给定时探针的）。返回命中的 key 数。
    """
    now = utc_now()
    owner_user_ids = _owner_user_ids()
    incident = {
        "reason_code": reason_code,
        "message": str(message)[:500],
        "source": source,
        "reported_at": now.isoformat(),
        "expires_at": (now + ttl).isoformat(),
    }
    with without_org_data_isolation(), managed_session() as db:
        keys = _active_keys_of_type(db, key_type)
        for key in keys:
            state = db.scalar(
                select(KeyHealthState).where(KeyHealthState.key_id == key.key_id)
            )
            previous_status = state.current_status if state is not None else None
            previous_notified_at = state.last_notified_at if state is not None else None
            if state is None:
                state = KeyHealthState(
                    key_id=key.key_id,
                    org_id=key.org_id,
                    key_name=key.name,
                    key_hash_prefix=key.key_hash_prefix,
                    key_type=key_type,
                    adapter=key_type,
                    current_status=RUNTIME_INCIDENT_STATUS,
                    reason_code=reason_code,
                    last_checked_at=now,
                    consecutive_failures=0,
                    details_json={},
                )
                db.add(state)
            details = dict(state.details_json or {})
            details[RUNTIME_INCIDENT_KEY] = incident
            state.details_json = details
            state.current_status = RUNTIME_INCIDENT_STATUS
            state.reason_code = reason_code
            state.last_failure_at = now
            state.consecutive_failures = int(state.consecutive_failures or 0) + 1
            if _should_notify(
                previous_status=previous_status,
                previous_notified_at=previous_notified_at,
                new_status=RUNTIME_INCIDENT_STATUS,
                now=now,
            ):
                identity = f"{key.name} (hash {key.key_hash_prefix})"
                for owner_user_id in owner_user_ids:
                    create_notification(
                        db,
                        event_type="key_health.failed",
                        title="密钥运行时告警",
                        body=f"{identity} 业务调用报 {reason_code}：{incident['message'][:200]}",
                        level="error",
                        source="key.health",
                        org_id=key.org_id,
                        recipient_user_id=owner_user_id,
                        external_refs={"url": "/key-health"},
                        payload={
                            "key_hash_prefix": key.key_hash_prefix,
                            "status": RUNTIME_INCIDENT_STATUS,
                            "reason_code": reason_code,
                            "adapter": state.adapter,
                            "runtime_source": source,
                        },
                    )
                if owner_user_ids:
                    state.last_notified_at = now
        return len(keys)


def report_runtime_recovered(*, key_type: str, source: str = "worker") -> int:
    """同 provider 一次业务调用成功：清掉运行时事故，状态回 healthy。"""
    now = utc_now()
    owner_user_ids = _owner_user_ids()
    with without_org_data_isolation(), managed_session() as db:
        keys = _active_keys_of_type(db, key_type)
        cleared = 0
        for key in keys:
            state = db.scalar(
                select(KeyHealthState).where(KeyHealthState.key_id == key.key_id)
            )
            if state is None:
                continue
            details = dict(state.details_json or {})
            if RUNTIME_INCIDENT_KEY not in details:
                continue
            details.pop(RUNTIME_INCIDENT_KEY, None)
            details["runtime_recovered_at"] = now.isoformat()
            details["runtime_recovered_source"] = source
            previous_status = state.current_status
            previous_notified_at = state.last_notified_at
            state.details_json = details
            state.current_status = HEALTHY
            state.reason_code = RUNTIME_RECOVERED_REASON
            state.last_success_at = now
            state.consecutive_failures = 0
            cleared += 1
            if _should_notify(
                previous_status=previous_status,
                previous_notified_at=previous_notified_at,
                new_status=HEALTHY,
                now=now,
            ):
                identity = f"{key.name} (hash {key.key_hash_prefix})"
                for owner_user_id in owner_user_ids:
                    create_notification(
                        db,
                        event_type="key_health.recovered",
                        title="密钥检测已恢复",
                        body=f"{identity} 业务调用已恢复正常（{source}）。",
                        level="success",
                        source="key.health",
                        org_id=key.org_id,
                        recipient_user_id=owner_user_id,
                        external_refs={"url": "/key-health"},
                        payload={
                            "key_hash_prefix": key.key_hash_prefix,
                            "status": HEALTHY,
                            "reason_code": RUNTIME_RECOVERED_REASON,
                            "adapter": state.adapter,
                            "runtime_source": source,
                        },
                    )
                if owner_user_ids:
                    state.last_notified_at = now
        return cleared


def _finish_run(
    run_id: int,
    *,
    status: str,
    total: int,
    healthy: int,
    warning: int,
    failed: int,
    error_code: str | None = None,
) -> RunOutcome:
    completed_at = utc_now()
    with without_org_data_isolation(), managed_session() as db:
        row = db.get(KeyHealthRun, run_id)
        if row is None:
            raise RuntimeError("key_health_run_missing")
        row.status = status
        row.completed_at = completed_at
        row.total_count = total
        row.healthy_count = healthy
        row.warning_count = warning
        row.failed_count = failed
        row.error_code = error_code
    return RunOutcome(
        run_id=run_id,
        created=True,
        status=status,
        total_count=total,
        healthy_count=healthy,
        warning_count=warning,
        failed_count=failed,
    )


def _outcome_for_existing(row: KeyHealthRun) -> RunOutcome:
    return RunOutcome(
        run_id=row.id,
        created=False,
        status=row.status,
        total_count=row.total_count,
        healthy_count=row.healthy_count,
        warning_count=row.warning_count,
        failed_count=row.failed_count,
    )


def run_key_health_check(
    *,
    trigger: str = "manual",
    scheduled_for: datetime | None = None,
) -> RunOutcome:
    slot = scheduled_for or utc_now()
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=UTC)
    slot = slot.astimezone(UTC)

    with exclusive_run_lock():
        run, created = _create_run(trigger=trigger, scheduled_for=slot)
        if not created:
            return _outcome_for_existing(run)
        try:
            targets = _load_probe_targets()
            owner_user_ids = _owner_user_ids()
            with ThreadPoolExecutor(
                max_workers=_probe_concurrency(),
                thread_name_prefix="key-health",
            ) as executor:
                results = list(executor.map(safe_probe_target, targets))
            for target, result in zip(targets, results, strict=True):
                _persist_result(
                    run_id=run.id,
                    target=target,
                    result=result,
                    owner_user_ids=owner_user_ids,
                )
            healthy = sum(result.status == HEALTHY for result in results)
            warning = sum(result.status in WARNING_STATUSES for result in results)
            failed = len(results) - healthy - warning
            return _finish_run(
                run.id,
                status="completed",
                total=len(results),
                healthy=healthy,
                warning=warning,
                failed=failed,
            )
        except Exception:
            logger.exception("Key health run failed")
            _finish_run(
                run.id,
                status="failed",
                total=0,
                healthy=0,
                warning=0,
                failed=0,
                error_code="run_internal_error",
            )
            raise


def _run_payload(row: KeyHealthRun | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "scheduled_for": row.scheduled_for,
        "trigger": row.trigger,
        "status": row.status,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "total_count": row.total_count,
        "healthy_count": row.healthy_count,
        "warning_count": row.warning_count,
        "failed_count": row.failed_count,
        "error_code": row.error_code,
    }


def key_health_summary(db: Session) -> dict[str, object]:
    with without_org_data_isolation():
        latest_run = db.scalar(
            select(KeyHealthRun).order_by(KeyHealthRun.started_at.desc()).limit(1)
        )
        keys = list(
            db.scalars(
                select(ApiKeyRecord)
                .where(ApiKeyRecord.status == "active")
                .order_by(ApiKeyRecord.name.asc(), ApiKeyRecord.id.asc())
            )
        )
        key_ids = [row.key_id for row in keys]
        states = (
            list(
                db.scalars(
                    select(KeyHealthState).where(KeyHealthState.key_id.in_(key_ids))
                )
            )
            if key_ids
            else []
        )
        bindings = (
            list(
                db.scalars(
                    select(ApiKeyModuleBindingRecord).where(
                        ApiKeyModuleBindingRecord.key_id.in_(key_ids),
                        ApiKeyModuleBindingRecord.status == "active",
                    )
                )
            )
            if key_ids
            else []
        )

    state_by_key = {state.key_id: state for state in states}
    bindings_by_key: dict[str, list[dict[str, str]]] = {}
    for binding in bindings:
        bindings_by_key.setdefault(binding.key_id, []).append(
            {"module_id": binding.module_id, "key_alias": binding.key_alias}
        )

    items: list[dict[str, object]] = []
    for key in keys:
        state = state_by_key.get(key.key_id)
        key_type = infer_key_type_from_record(
            name=key.name,
            url=key.url,
            metadata=key.metadata_json,
        )
        items.append(
            {
                "key_id": key.key_id,
                "key_name": key.name,
                "key_hash_prefix": key.key_hash_prefix,
                "key_type": state.key_type if state is not None else key_type,
                "adapter": state.adapter if state is not None else None,
                "status": state.current_status if state is not None else "never_checked",
                "reason_code": state.reason_code if state is not None else "not_yet_checked",
                "last_checked_at": state.last_checked_at if state is not None else None,
                "last_success_at": state.last_success_at if state is not None else None,
                "last_failure_at": state.last_failure_at if state is not None else None,
                "consecutive_failures": (
                    state.consecutive_failures if state is not None else 0
                ),
                "details": dict(state.details_json or {}) if state is not None else {},
                "bindings": sorted(
                    bindings_by_key.get(key.key_id, []),
                    key=lambda item: (item["module_id"], item["key_alias"]),
                ),
            }
        )

    counts = {
        "total": len(items),
        "healthy": sum(item["status"] == HEALTHY for item in items),
        "warning": sum(item["status"] in WARNING_STATUSES for item in items),
        "failed": sum(
            item["status"] not in WARNING_STATUSES | {HEALTHY, "never_checked"}
            for item in items
        ),
        "never_checked": sum(item["status"] == "never_checked" for item in items),
    }
    return {
        "generated_at": utc_now(),
        "interval_minutes": 60,
        "latest_run": _run_payload(latest_run),
        "counts": counts,
        "items": items,
    }


def list_key_health_runs(db: Session, *, limit: int = 20) -> list[dict[str, object]]:
    with without_org_data_isolation():
        rows = list(
            db.scalars(
                select(KeyHealthRun)
                .order_by(KeyHealthRun.started_at.desc())
                .limit(limit)
            )
        )
    return [payload for row in rows if (payload := _run_payload(row)) is not None]
