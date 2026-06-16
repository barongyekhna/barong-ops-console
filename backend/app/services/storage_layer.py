from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from ..schemas.event_collector import AuditEvent
from ..schemas.execution_trace import ExecutionTrace
from ..schemas.storage_layer import (
    HOT_RETENTION_DAYS,
    STORAGE_INDEX_FIELDS,
    WARM_RETENTION_DAYS,
    C17CToC17DStorageMigrationStrategy,
    EventRaw,
    HotWarmColdDataFlow,
    QueryPerformanceStrategy,
    StorageAdapterInterfaceDesign,
    StorageArchiveResult,
    StorageArchitectureDesign,
    StorageBackend,
    StorageBackendDesign,
    StorageDataModelDesign,
    StorageIndexingStrategy,
    StorageLayerCompletionStatus,
    StorageRecordEnvelope,
    StorageRetentionPolicy,
    StorageTier,
    StorageTimeRange,
    StorageWritePathDesign,
    StorageWriteResult,
    StorageQueryResult,
    utc_now,
)
from ..schemas.structured_logs import LogEntry
from .event_collector import normalize_context_id, sanitize_event_payload
from .execution_trace import execution_trace_to_db_record
from .structured_logs import log_entry_to_db_record


class StorageAdapter(Protocol):
    def write_log(self, log: LogEntry) -> StorageWriteResult:
        ...

    def write_trace(self, trace: ExecutionTrace) -> StorageWriteResult:
        ...

    def write_event_raw(self, raw_event: EventRaw | AuditEvent) -> StorageWriteResult:
        ...

    def query_by_context_id(
        self,
        context_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        ...

    def query_by_trace_id(
        self,
        trace_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        ...

    def query_by_time_range(
        self,
        time_range: StorageTimeRange,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        ...

    def archive_to_cold_storage(
        self,
        *,
        before: datetime | None = None,
        batch_size: int | None = None,
    ) -> StorageArchiveResult:
        ...


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return sanitize_event_payload(dict(value))
    return {}


def _timestamp_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return utc_now()
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return utc_now()


def _first_present(
    sources: tuple[Mapping[str, Any], ...],
    keys: tuple[str, ...],
) -> Any:
    for source in sources:
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
    return None


def _status_value(value: Any) -> str:
    text = (_string_value(value) or "pending").lower().replace("-", "_")
    if text in {"success", "failed", "pending", "partial"}:
        return text
    if text in {"complete", "completed", "ok", "succeeded"}:
        return "success"
    if text in {"error", "errored", "failure", "rejected", "denied"}:
        return "failed"
    return "pending"


def _trace_timestamp(trace: ExecutionTrace) -> datetime:
    if not trace.chain:
        return utc_now()
    return min(step.timestamp for step in trace.chain)


def _trace_modules(trace: ExecutionTrace) -> list[str]:
    return sorted({step.module for step in trace.chain}) or ["system"]


def _chain_value(trace: ExecutionTrace, key: str) -> str | None:
    for step in trace.chain:
        for source in (step.input, step.output):
            value = _string_value(source.get(key))
            if value is not None:
                return value
    return None


def _archive_object_key(record: StorageRecordEnvelope) -> str:
    stamp = record.timestamp.strftime("%Y/%m/%d")
    entity = record.entity_type.lower()
    return f"c17d/{entity}/{stamp}/{record.context_id}/{record.record_id}.jsonl.gz"


def resolve_storage_tier(
    timestamp: datetime,
    *,
    now: datetime | None = None,
) -> StorageTier:
    current = _timestamp_value(now) if now is not None else utc_now()
    observed_at = _timestamp_value(timestamp)
    age_days = max((current - observed_at).total_seconds() / 86400, 0)
    if age_days <= HOT_RETENTION_DAYS:
        return "L1_hot"
    if age_days <= WARM_RETENTION_DAYS:
        return "L2_warm"
    return "L3_cold"


def backend_targets_for_tier(tier: StorageTier) -> tuple[StorageBackend, ...]:
    if tier == "L1_hot":
        return ("postgresql", "redis")
    if tier == "L2_warm":
        return ("postgresql",)
    return ("s3_object_storage", "postgresql")


def normalize_event_raw(raw_event: EventRaw | AuditEvent | Mapping[str, Any]) -> EventRaw:
    if isinstance(raw_event, EventRaw):
        return raw_event
    if isinstance(raw_event, AuditEvent):
        raw = raw_event.model_dump(mode="python")
    elif isinstance(raw_event, Mapping):
        raw = dict(raw_event)
    else:
        raise TypeError("C17D raw event storage accepts EventRaw, AuditEvent, or mapping.")

    payload = _dict_value(raw.get("payload"))
    metadata = _dict_value(raw.get("metadata"))
    context_id = normalize_context_id(
        _string_value(
            _first_present(
                (raw, payload, metadata),
                (
                    "context_id",
                    "contextId",
                    "trace_id",
                    "traceId",
                    "correlation_id",
                    "correlationId",
                    "request_id",
                    "requestId",
                ),
            )
        )
    )
    trace_id = _string_value(
        _first_present((raw, payload, metadata), ("trace_id", "traceId"))
    )
    event_type = _string_value(raw.get("event_type")) or "unknown.event"
    return EventRaw(
        event_id=_string_value(raw.get("event_id")) or event_type,
        timestamp=_timestamp_value(raw.get("timestamp")),
        context_id=context_id,
        trace_id=normalize_context_id(trace_id) if trace_id is not None else context_id,
        product_key=_string_value(
            _first_present((raw, payload, metadata), ("product_key", "productKey"))
        ),
        user_id=_string_value(
            _first_present((raw, payload, metadata), ("user_id", "userId"))
        ),
        workflow_id=_string_value(
            _first_present((raw, payload, metadata), ("workflow_id", "workflowId"))
        ),
        module=_string_value(raw.get("module")) or "system",
        event_type=event_type,
        action=_string_value(raw.get("action")) or event_type,
        source=_string_value(raw.get("source")) or "system",
        status=_status_value(raw.get("status")),  # type: ignore[arg-type]
        payload=payload,
        metadata=metadata,
    )


def _write_result(record: StorageRecordEnvelope) -> StorageWriteResult:
    return StorageWriteResult(
        record_id=record.record_id,
        entity_type=record.entity_type,
        tier=record.tier,
        backend_targets=record.backend_targets,
        context_id=record.context_id,
        trace_id=record.trace_id,
        event_id=record.event_id,
        archive_object_key=record.archive_object_key,
    )


def storage_record_from_log_entry(
    log: LogEntry,
    *,
    now: datetime | None = None,
) -> StorageRecordEnvelope:
    if not isinstance(log, LogEntry):
        raise TypeError("C17D write_log accepts only C17B LogEntry.")

    record = log_entry_to_db_record(log)
    trace_id = (
        _string_value(log.request.get("trace_id"))
        or _string_value(log.request.get("traceId"))
        or _string_value(log.response.get("trace_id"))
        or _string_value(log.response.get("traceId"))
        or log.entity.request_id
        or log.context_id
    )
    tier = resolve_storage_tier(log.timestamp, now=now)
    return StorageRecordEnvelope(
        entity_type="LogEntry",
        tier=tier,
        backend_targets=backend_targets_for_tier(tier),
        context_id=log.context_id,
        trace_id=trace_id,
        event_id=log.event_id,
        product_key=log.entity.product_key,
        user_id=log.entity.user_id,
        module=log.module,
        event_type=log.event_type,
        timestamp=log.timestamp,
        status=log.status,
        payload=record,
        compressed=tier == "L3_cold",
        archive_object_key=None,
    )


def storage_record_from_execution_trace(
    trace: ExecutionTrace,
    *,
    now: datetime | None = None,
) -> StorageRecordEnvelope:
    if not isinstance(trace, ExecutionTrace):
        raise TypeError("C17D write_trace accepts only C17C ExecutionTrace.")

    record = execution_trace_to_db_record(trace)
    timestamp = _trace_timestamp(trace)
    tier = resolve_storage_tier(timestamp, now=now)
    modules = _trace_modules(trace)
    return StorageRecordEnvelope(
        entity_type="ExecutionTrace",
        tier=tier,
        backend_targets=backend_targets_for_tier(tier),
        context_id=trace.context_id,
        trace_id=trace.trace_id,
        event_id=trace.root_event_id,
        product_key=_chain_value(trace, "product_key"),
        user_id=_chain_value(trace, "user_id"),
        module=modules[0],
        event_type="execution.trace",
        timestamp=timestamp,
        status=trace.final_status,
        payload=record,
        compressed=tier == "L3_cold",
        archive_object_key=None,
    )


def storage_record_from_event_raw(
    raw_event: EventRaw | AuditEvent | Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> StorageRecordEnvelope:
    raw = normalize_event_raw(raw_event)
    record = raw.model_dump(mode="json")
    tier = resolve_storage_tier(raw.timestamp, now=now)
    return StorageRecordEnvelope(
        entity_type="EventRaw",
        tier=tier,
        backend_targets=backend_targets_for_tier(tier),
        context_id=raw.context_id,
        trace_id=raw.trace_id or raw.context_id,
        event_id=raw.event_id,
        product_key=raw.product_key,
        user_id=raw.user_id,
        module=raw.module,
        event_type=raw.event_type,
        timestamp=raw.timestamp,
        status=raw.status,
        payload=record,
        compressed=tier == "L3_cold",
        archive_object_key=None,
    )


class InMemoryStorageAdapter:
    """Side-effect-free adapter used for C17D design validation tests."""

    def __init__(self, *, now: datetime | None = None) -> None:
        self._records: list[StorageRecordEnvelope] = []
        self._now = _timestamp_value(now) if now is not None else None

    @property
    def records(self) -> tuple[StorageRecordEnvelope, ...]:
        return tuple(self._records)

    def write_log(self, log: LogEntry) -> StorageWriteResult:
        record = storage_record_from_log_entry(log, now=self._now)
        self._records.append(record)
        return _write_result(record)

    def write_trace(self, trace: ExecutionTrace) -> StorageWriteResult:
        record = storage_record_from_execution_trace(trace, now=self._now)
        self._records.append(record)
        return _write_result(record)

    def write_event_raw(
        self,
        raw_event: EventRaw | AuditEvent | Mapping[str, Any],
    ) -> StorageWriteResult:
        record = storage_record_from_event_raw(raw_event, now=self._now)
        self._records.append(record)
        return _write_result(record)

    def query_by_context_id(
        self,
        context_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        normalized = normalize_context_id(context_id)
        return self._query(
            lambda record: record.context_id == normalized,
            indexes_used=("idx_c17d_context_id",),
            limit=limit,
        )

    def query_by_trace_id(
        self,
        trace_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        normalized = normalize_context_id(trace_id)
        return self._query(
            lambda record: record.trace_id == normalized,
            indexes_used=("idx_c17d_trace_id",),
            limit=limit,
        )

    def query_by_time_range(
        self,
        time_range: StorageTimeRange,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        return self._query(
            lambda record: (
                (time_range.start_at is None or record.timestamp >= time_range.start_at)
                and (time_range.end_at is None or record.timestamp <= time_range.end_at)
            ),
            indexes_used=("idx_c17d_timestamp",),
            limit=limit,
        )

    def archive_to_cold_storage(
        self,
        *,
        before: datetime | None = None,
        batch_size: int | None = None,
    ) -> StorageArchiveResult:
        current = self._now or utc_now()
        cutoff = _timestamp_value(before) if before is not None else (
            current - timedelta(days=WARM_RETENTION_DAYS)
        )
        candidates = [
            record
            for record in self._records
            if record.tier != "L3_cold" and record.timestamp < cutoff
        ]
        selected = candidates[:batch_size] if batch_size is not None else candidates

        keys: list[str] = []
        for record in selected:
            object_key = record.archive_object_key or _archive_object_key(record)
            record.tier = "L3_cold"
            record.backend_targets = backend_targets_for_tier("L3_cold")
            record.compressed = True
            record.archive_object_key = object_key
            keys.append(object_key)

        return StorageArchiveResult(
            candidate_count=len(candidates),
            archived_count=len(selected),
            archive_object_keys=tuple(keys),
        )

    def _query(
        self,
        predicate: Any,
        *,
        indexes_used: tuple[str, ...],
        limit: int | None,
    ) -> StorageQueryResult:
        matched = [record for record in self._records if predicate(record)]
        matched.sort(key=lambda record: record.timestamp, reverse=True)
        total_count = len(matched)
        if limit is not None:
            matched = matched[: max(limit, 0)]
        searched_tiers = tuple(dict.fromkeys(record.tier for record in matched))
        if not searched_tiers:
            searched_tiers = ("L1_hot", "L2_warm", "L3_cold")
        return StorageQueryResult(
            records=tuple(matched),
            total_count=total_count,
            searched_tiers=searched_tiers,
            indexes_used=indexes_used,
        )


def get_storage_architecture_design() -> StorageArchitectureDesign:
    return StorageArchitectureDesign()


def get_storage_data_model_design() -> StorageDataModelDesign:
    return StorageDataModelDesign()


def get_storage_adapter_interface_design() -> StorageAdapterInterfaceDesign:
    return StorageAdapterInterfaceDesign()


def get_storage_backend_design() -> StorageBackendDesign:
    return StorageBackendDesign()


def get_storage_indexing_strategy() -> StorageIndexingStrategy:
    return StorageIndexingStrategy()


def get_storage_retention_policy() -> StorageRetentionPolicy:
    return StorageRetentionPolicy()


def get_storage_write_path_design() -> StorageWritePathDesign:
    return StorageWritePathDesign()


def get_hot_warm_cold_data_flow() -> HotWarmColdDataFlow:
    return HotWarmColdDataFlow()


def get_c17c_to_c17d_storage_migration_strategy() -> (
    C17CToC17DStorageMigrationStrategy
):
    return C17CToC17DStorageMigrationStrategy()


def get_query_performance_strategy() -> QueryPerformanceStrategy:
    return QueryPerformanceStrategy()


def get_storage_layer_completion_status() -> StorageLayerCompletionStatus:
    return StorageLayerCompletionStatus()
