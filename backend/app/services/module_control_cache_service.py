from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Condition, Event, Thread
from time import monotonic
from typing import Any

from sqlalchemy import func, select

from ..db.session import SessionLocal, rollback_open_transaction
from ..models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from ..schemas.module_control import (
    ModuleControlCenterResponse,
    ModuleControlStateRead,
)
from .data_isolation import without_org_data_isolation
from .module_control_center import (
    build_module_control_center,
    build_module_control_execution_snapshot,
)

MODULE_CONTROL_CACHE_TTL_SECONDS = 5.0
MODULE_CONTROL_CACHE_REFRESH_INTERVAL_SECONDS = 5.0
MODULE_CONTROL_CACHE_WAIT_TIMEOUT_SECONDS = 0.5

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleControlCenterSnapshot:
    response: ModuleControlCenterResponse
    generated_at: datetime
    expires_at_monotonic: float
    fresh_json: str
    stale_json: str
    org_module_summary: dict[str, int]
    module_status: dict[str, dict[str, int]]
    execution_state_snapshot: dict[str, int]
    api_key_binding_summary: dict[str, Any]


_condition = Condition()
_wake = Event()
_stop = Event()
_worker: Thread | None = None
_snapshot: ModuleControlCenterSnapshot | None = None
_refresh_requested = False
_force_refresh_requested = False
_refreshing = False
_last_refresh_error: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _response_copy(
    snapshot: ModuleControlCenterSnapshot,
    *,
    cache_status: str,
) -> ModuleControlCenterResponse:
    return snapshot.response.model_copy(
        update={
            "cache_status": cache_status,
            "generated_at": snapshot.generated_at,
        },
    )


def _partial_response() -> ModuleControlCenterResponse:
    return ModuleControlCenterResponse(
        organizations=[],
        organization_count=0,
        module_count=0,
        auto_registered_count=0,
        cache_status="partial",
        generated_at=_now(),
    )


def _partial_response_json() -> str:
    return _partial_response().model_dump_json()


def _module_status_summary(
    response: ModuleControlCenterResponse,
) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for group in response.organizations:
        counts = Counter(module.runtime_status for module in group.modules)
        summary[group.org_id] = {
            "active": counts.get("active", 0),
            "disabled": counts.get("disabled", 0),
            "error": counts.get("error", 0),
            "total": sum(counts.values()),
        }
    return summary


def _execution_state_snapshot(
    response: ModuleControlCenterResponse,
) -> dict[str, int]:
    counts = Counter(
        module.runtime_status
        for group in response.organizations
        for module in group.modules
    )
    return {
        "active": counts.get("active", 0),
        "disabled": counts.get("disabled", 0),
        "error": counts.get("error", 0),
        "total": sum(counts.values()),
    }


def _api_key_binding_summary(db) -> dict[str, Any]:
    active_rows = list(
        db.execute(
            select(
                ApiKeyModuleBindingRecord.org_id,
                ApiKeyModuleBindingRecord.module_id,
                func.count(ApiKeyModuleBindingRecord.id),
            )
            .join(
                ApiKeyRecord,
                ApiKeyRecord.key_id == ApiKeyModuleBindingRecord.key_id,
            )
            .where(
                ApiKeyModuleBindingRecord.status == "active",
                ApiKeyRecord.status == "active",
            )
            .group_by(
                ApiKeyModuleBindingRecord.org_id,
                ApiKeyModuleBindingRecord.module_id,
            )
        )
    )
    return {
        "active_binding_count": sum(int(row[2]) for row in active_rows),
        "bound_org_count": len({str(row[0]) for row in active_rows}),
        "bound_module_count": len({str(row[1]) for row in active_rows}),
        "org_module_binding_count": {
            f"{row[0]}:{row[1]}": int(row[2]) for row in active_rows
        },
    }


def _snapshot_from_response(
    response: ModuleControlCenterResponse,
    *,
    api_key_binding_summary: dict[str, Any],
) -> ModuleControlCenterSnapshot:
    generated_at = _now()
    org_module_summary = {
        group.org_id: len(group.modules) for group in response.organizations
    }
    module_status = _module_status_summary(response)
    execution_state = _execution_state_snapshot(response)
    if not execution_state["total"]:
        execution_state = build_module_control_execution_snapshot({})
    clean_response = response.model_copy(
        deep=True,
        update={
            "cache_status": "fresh",
            "generated_at": generated_at,
        },
    )
    stale_response = clean_response.model_copy(update={"cache_status": "stale"})
    return ModuleControlCenterSnapshot(
        response=clean_response,
        generated_at=generated_at,
        expires_at_monotonic=monotonic() + MODULE_CONTROL_CACHE_TTL_SECONDS,
        fresh_json=clean_response.model_dump_json(),
        stale_json=stale_response.model_dump_json(),
        org_module_summary=org_module_summary,
        module_status=module_status,
        execution_state_snapshot=execution_state,
        api_key_binding_summary=api_key_binding_summary,
    )


def _refresh_snapshot() -> ModuleControlCenterSnapshot:
    db = SessionLocal()
    try:
        with without_org_data_isolation():
            response = build_module_control_center(db)
            api_key_summary = _api_key_binding_summary(db)
        db.commit()
        return _snapshot_from_response(
            response,
            api_key_binding_summary=api_key_summary,
        )
    except Exception:
        rollback_open_transaction(db)
        raise
    finally:
        db.close()


def _publish_snapshot(snapshot: ModuleControlCenterSnapshot) -> None:
    global _last_refresh_error, _snapshot
    with _condition:
        _snapshot = snapshot
        _last_refresh_error = None
        _condition.notify_all()


def _finish_refresh(error: Exception | None = None) -> None:
    global _last_refresh_error, _refreshing
    with _condition:
        _refreshing = False
        if error is not None:
            _last_refresh_error = str(error)
        _condition.notify_all()


def _run_refresh_cycle() -> None:
    global _force_refresh_requested, _refresh_requested, _refreshing
    with _condition:
        if _refreshing:
            return
        snapshot = _snapshot
        stale = (
            snapshot is None
            or snapshot.expires_at_monotonic <= monotonic()
        )
        if not _refresh_requested and not stale:
            return
        force = _force_refresh_requested
        if not force and snapshot is not None and not stale:
            _refresh_requested = False
            return
        _refreshing = True
        _refresh_requested = False
        _force_refresh_requested = False

    try:
        _publish_snapshot(_refresh_snapshot())
        _finish_refresh()
    except Exception as exc:
        logger.warning("module control cache refresh failed: %s", exc)
        _finish_refresh(exc)


def _worker_loop() -> None:
    while not _stop.is_set():
        _wake.wait(timeout=MODULE_CONTROL_CACHE_REFRESH_INTERVAL_SECONDS)
        _wake.clear()
        if _stop.is_set():
            break
        _run_refresh_cycle()


def start_module_control_cache_worker() -> None:
    global _worker
    with _condition:
        if _worker is not None and _worker.is_alive():
            return
        _stop.clear()
        _worker = Thread(
            target=_worker_loop,
            name="barong-module-control-cache",
            daemon=True,
        )
        _worker.start()


def stop_module_control_cache_worker(*, timeout_seconds: float = 1.0) -> None:
    global _worker
    worker = _worker
    if worker is None:
        return
    _stop.set()
    _wake.set()
    worker.join(timeout=timeout_seconds)
    with _condition:
        if _worker is worker:
            _worker = None


def refresh_module_control_center_cache_async(*, force: bool = False) -> None:
    global _force_refresh_requested, _refresh_requested
    start_module_control_cache_worker()
    with _condition:
        _refresh_requested = True
        _force_refresh_requested = _force_refresh_requested or force
    _wake.set()


def refresh_module_control_center_cache_sync() -> ModuleControlCenterResponse:
    global _force_refresh_requested, _refresh_requested, _refreshing
    with _condition:
        if _refreshing:
            while _refreshing:
                _condition.wait(timeout=MODULE_CONTROL_CACHE_WAIT_TIMEOUT_SECONDS)
            if _snapshot is not None:
                return _response_copy(_snapshot, cache_status="fresh")
        _refreshing = True
        _refresh_requested = False
        _force_refresh_requested = False
    try:
        snapshot = _refresh_snapshot()
        _publish_snapshot(snapshot)
        return _response_copy(snapshot, cache_status="fresh")
    finally:
        _finish_refresh()


def get_module_control_center_cached(
    *,
    max_wait_seconds: float = MODULE_CONTROL_CACHE_WAIT_TIMEOUT_SECONDS,
) -> ModuleControlCenterResponse:
    start_module_control_cache_worker()
    with _condition:
        snapshot = _snapshot
        if snapshot is not None:
            if snapshot.expires_at_monotonic > monotonic():
                return _response_copy(snapshot, cache_status="fresh")
            _refresh_requested_nowait_locked(force=False)
            return _response_copy(snapshot, cache_status="stale")

        _refresh_requested_nowait_locked(force=True)
        deadline = monotonic() + max(0.0, max_wait_seconds)
        while _snapshot is None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return _partial_response()
            _condition.wait(timeout=remaining)
        return _response_copy(_snapshot, cache_status="fresh")


def get_module_control_center_cached_json(
    *,
    max_wait_seconds: float = MODULE_CONTROL_CACHE_WAIT_TIMEOUT_SECONDS,
) -> str:
    start_module_control_cache_worker()
    with _condition:
        snapshot = _snapshot
        if snapshot is not None:
            if snapshot.expires_at_monotonic > monotonic():
                return snapshot.fresh_json
            _refresh_requested_nowait_locked(force=False)
            return snapshot.stale_json

        _refresh_requested_nowait_locked(force=True)
        deadline = monotonic() + max(0.0, max_wait_seconds)
        while _snapshot is None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return _partial_response_json()
            _condition.wait(timeout=remaining)
        return _snapshot.fresh_json


def _refresh_requested_nowait_locked(*, force: bool) -> None:
    global _force_refresh_requested, _refresh_requested
    _refresh_requested = True
    _force_refresh_requested = _force_refresh_requested or force
    _wake.set()


def apply_module_control_state_to_cache(item: ModuleControlStateRead) -> bool:
    global _snapshot
    with _condition:
        snapshot = _snapshot
        if snapshot is None:
            return False
        response = snapshot.response.model_copy(deep=True)
        for group in response.organizations:
            if group.org_id != item.org_id:
                continue
            for index, module in enumerate(group.modules):
                if module.module_id == item.module_id:
                    group.modules[index] = item.model_copy(deep=True)
                    _snapshot = _snapshot_from_response(
                        response,
                        api_key_binding_summary=snapshot.api_key_binding_summary,
                    )
                    _condition.notify_all()
                    return True
            group.modules.append(item.model_copy(deep=True))
            response.module_count += 1
            _snapshot = _snapshot_from_response(
                response,
                api_key_binding_summary=snapshot.api_key_binding_summary,
            )
            _condition.notify_all()
            return True
        return False


def get_module_control_cache_stats() -> dict[str, Any]:
    with _condition:
        snapshot = _snapshot
        return {
            "cache_present": snapshot is not None,
            "cache_status": (
                "missing"
                if snapshot is None
                else (
                    "fresh"
                    if snapshot.expires_at_monotonic > monotonic()
                    else "stale"
                )
            ),
            "refreshing": _refreshing,
            "last_refresh_error": _last_refresh_error,
            "ttl_seconds": MODULE_CONTROL_CACHE_TTL_SECONDS,
            "org_module_summary": (
                {} if snapshot is None else dict(snapshot.org_module_summary)
            ),
            "module_status": (
                {} if snapshot is None else dict(snapshot.module_status)
            ),
            "execution_state_snapshot": (
                {}
                if snapshot is None
                else dict(snapshot.execution_state_snapshot)
            ),
            "api_key_binding_summary": (
                {}
                if snapshot is None
                else dict(snapshot.api_key_binding_summary)
            ),
        }


def reset_module_control_center_cache_for_tests() -> None:
    global _force_refresh_requested, _last_refresh_error, _refresh_requested, _snapshot
    with _condition:
        _snapshot = None
        _refresh_requested = False
        _force_refresh_requested = False
        _last_refresh_error = None
        _condition.notify_all()
