from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.observability import AuditLogRecord, EventStreamRecord
from ..schemas.audit_query_engine import (
    AuditQueryEngineCompletionStatus,
    AuditQueryEngineDesign,
    AuditQueryIndexUsageStrategy,
    C17EStorageIntegrationDesign,
    DrillDownChainExpansion,
    DrillDownExecutionModelDesign,
    DrillDownQuery,
    DrillDownStepBreakdown,
    FilterCondition,
    FilterExpression,
    FilterSystemLogicDesign,
    FilterSystemQuery,
    QueryMetadata,
    QueryOptimizationPlan,
    QueryOptimizerDesign,
    QueryResult,
    QueryResultSchemaDefinition,
    SearchLogsAPIDesign,
    SearchLogsQuery,
)
from ..schemas.execution_trace import (
    EXECUTION_TRACE_FIELDS,
    ExecutionTrace,
    ExecutionTraceStep,
)
from ..schemas.storage_layer import (
    EventRaw,
    StorageRecordEnvelope,
    StorageTimeRange,
)
from ..schemas.structured_logs import LOG_ENTRY_FIELDS, LogEntry, LogModule
from .event_collector import normalize_context_id
from .storage_layer import (
    StorageAdapter,
    ensure_observability_tables,
    storage_record_from_event_stream_row,
)


IDX_CONTEXT = "idx_c17d_context_id"
IDX_TRACE = "idx_c17d_trace_id"
IDX_MODULE_EVENT = "idx_c17d_module_event_type"
IDX_TIMESTAMP = "idx_c17d_timestamp"
IDX_PRODUCT_USER_STATUS = "idx_c17d_product_user_status"
IDX_ACTION_SHADOW = "idx_c17e_action_shadow"

CHAIN_STAGE_LABELS: tuple[tuple[str, str], ...] = (
    ("C14", "C14 capability"),
    ("C15", "C15 workflow"),
    ("n8n", "n8n nodes"),
    ("AI", "AI calls"),
    ("DB", "DB writes"),
)


@dataclass(frozen=True)
class _IndexSnapshot:
    version: tuple[str, ...]
    records: tuple[StorageRecordEnvelope, ...]
    by_context_id: Mapping[str, tuple[StorageRecordEnvelope, ...]]
    by_trace_id: Mapping[str, tuple[StorageRecordEnvelope, ...]]
    by_module: Mapping[str, tuple[StorageRecordEnvelope, ...]]
    by_event_type: Mapping[str, tuple[StorageRecordEnvelope, ...]]
    by_product_key: Mapping[str, tuple[StorageRecordEnvelope, ...]]
    by_user_id: Mapping[str, tuple[StorageRecordEnvelope, ...]]
    by_status: Mapping[str, tuple[StorageRecordEnvelope, ...]]
    by_action: Mapping[str, tuple[StorageRecordEnvelope, ...]]
    by_module_event_type: Mapping[tuple[str, str], tuple[StorageRecordEnvelope, ...]]


def _empty_snapshot() -> _IndexSnapshot:
    empty: dict[str, tuple[StorageRecordEnvelope, ...]] = {}
    return _IndexSnapshot(
        version=(),
        records=(),
        by_context_id=empty,
        by_trace_id=empty,
        by_module=empty,
        by_event_type=empty,
        by_product_key=empty,
        by_user_id=empty,
        by_status=empty,
        by_action=empty,
        by_module_event_type={},
    )


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _timestamp_value(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _payload(record: StorageRecordEnvelope) -> Mapping[str, Any]:
    if isinstance(record.payload, Mapping):
        return record.payload
    return {}


def _sorted_records(
    records: Sequence[StorageRecordEnvelope],
) -> tuple[StorageRecordEnvelope, ...]:
    return tuple(sorted(records, key=lambda record: record.timestamp, reverse=True))


def _freeze_index(
    index: Mapping[Any, list[StorageRecordEnvelope]],
) -> dict[Any, tuple[StorageRecordEnvelope, ...]]:
    return {key: _sorted_records(records) for key, records in index.items()}


def _record_version(record: StorageRecordEnvelope) -> str:
    return "|".join(
        (
            record.record_id,
            record.entity_type,
            record.tier,
            record.status,
            record.timestamp.isoformat(),
        )
    )


def _record_modules(record: StorageRecordEnvelope) -> tuple[str, ...]:
    modules = [record.module]
    raw_modules = _payload(record).get("modules")
    if isinstance(raw_modules, Sequence) and not isinstance(raw_modules, str):
        modules.extend(str(module) for module in raw_modules if _string_value(module))
    return tuple(dict.fromkeys(module for module in modules if module))


def _record_actions(record: StorageRecordEnvelope) -> tuple[str, ...]:
    values: list[str] = []
    payload = _payload(record)
    action = _string_value(payload.get("action"))
    if action is not None:
        values.append(action)
    raw_chain = payload.get("chain")
    if isinstance(raw_chain, Sequence) and not isinstance(raw_chain, str):
        for raw_step in raw_chain:
            if isinstance(raw_step, Mapping):
                step_action = _string_value(raw_step.get("action"))
                if step_action is not None:
                    values.append(step_action)
    return tuple(dict.fromkeys(values))


def _record_latency_ms(record: StorageRecordEnvelope) -> float:
    payload = _payload(record)
    if record.entity_type == "ExecutionTrace":
        return _nonnegative_float(payload.get("total_latency_ms"))
    return _nonnegative_float(payload.get("latency_ms"))


def _nonnegative_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _build_index_snapshot(
    records: Sequence[StorageRecordEnvelope],
) -> _IndexSnapshot:
    by_context_id: defaultdict[str, list[StorageRecordEnvelope]] = defaultdict(list)
    by_trace_id: defaultdict[str, list[StorageRecordEnvelope]] = defaultdict(list)
    by_module: defaultdict[str, list[StorageRecordEnvelope]] = defaultdict(list)
    by_event_type: defaultdict[str, list[StorageRecordEnvelope]] = defaultdict(list)
    by_product_key: defaultdict[str, list[StorageRecordEnvelope]] = defaultdict(list)
    by_user_id: defaultdict[str, list[StorageRecordEnvelope]] = defaultdict(list)
    by_status: defaultdict[str, list[StorageRecordEnvelope]] = defaultdict(list)
    by_action: defaultdict[str, list[StorageRecordEnvelope]] = defaultdict(list)
    by_module_event_type: defaultdict[
        tuple[str, str], list[StorageRecordEnvelope]
    ] = defaultdict(list)

    ordered_records = _sorted_records(records)
    for record in ordered_records:
        by_context_id[record.context_id].append(record)
        by_trace_id[record.trace_id].append(record)
        by_event_type[record.event_type].append(record)
        by_status[record.status].append(record)
        if record.product_key is not None:
            by_product_key[record.product_key].append(record)
        if record.user_id is not None:
            by_user_id[record.user_id].append(record)

        for module in _record_modules(record):
            by_module[module].append(record)
            by_module_event_type[(module, record.event_type)].append(record)
        for action in _record_actions(record):
            by_action[action.lower()].append(record)

    return _IndexSnapshot(
        version=tuple(_record_version(record) for record in ordered_records),
        records=ordered_records,
        by_context_id=_freeze_index(by_context_id),
        by_trace_id=_freeze_index(by_trace_id),
        by_module=_freeze_index(by_module),
        by_event_type=_freeze_index(by_event_type),
        by_product_key=_freeze_index(by_product_key),
        by_user_id=_freeze_index(by_user_id),
        by_status=_freeze_index(by_status),
        by_action=_freeze_index(by_action),
        by_module_event_type=_freeze_index(by_module_event_type),
    )


def _time_range_key(time_range: StorageTimeRange | None) -> str:
    if time_range is None:
        return "none"
    start = time_range.start_at.isoformat() if time_range.start_at else "*"
    end = time_range.end_at.isoformat() if time_range.end_at else "*"
    return f"{start}..{end}"


def _cache_key(prefix: str, **values: Any) -> str:
    parts = [prefix]
    for key in sorted(values):
        value = values[key]
        if isinstance(value, StorageTimeRange):
            rendered = _time_range_key(value)
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return "|".join(parts)


def _post_filter_fields(
    *,
    primary_index: str,
    fields: Sequence[str],
) -> tuple[str, ...]:
    covered: set[str] = set()
    if primary_index == IDX_CONTEXT:
        covered.add("context_id")
    elif primary_index == IDX_TRACE:
        covered.add("trace_id")
    elif primary_index == IDX_TIMESTAMP:
        covered.add("timestamp")
    elif primary_index == IDX_MODULE_EVENT:
        covered.update({"module", "event_type"})
    elif primary_index == IDX_PRODUCT_USER_STATUS:
        covered.update({"product_key", "user_id", "status"})
    elif primary_index == IDX_ACTION_SHADOW:
        covered.add("action")
    return tuple(field for field in fields if field not in covered)


class AuditLogWriter:
    """Persistent C17 audit writer backed by audit_logs."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        org_id: str | None = None,
    ) -> None:
        ensure_observability_tables()
        self._db = db
        self._org_id = org_id

    def write_storage_record(
        self,
        record: StorageRecordEnvelope,
        *,
        org_id: str | None = None,
    ) -> AuditLogRecord:
        payload = dict(_payload(record))
        row = AuditLogRecord(
            org_id=self._resolve_org_id(org_id),
            audit_id=f"audit-{uuid4()}",
            event_stream_record_id=record.record_id,
            event_id=record.event_id,
            context_id=record.context_id,
            trace_id=record.trace_id,
            module_id=record.module,
            action=_string_value(payload.get("action")) or record.event_type,
            status=record.status,
            timestamp=record.timestamp,
            payload=payload,
            metadata_json=self._metadata_payload(payload),
        )
        with self._session() as db:
            db.add(row)
            self._commit(db)
            return row

    def write_event_stream(self, row: EventStreamRecord) -> AuditLogRecord:
        record = storage_record_from_event_stream_row(row)
        audit = AuditLogRecord(
            org_id=row.org_id,
            audit_id=f"audit-{uuid4()}",
            event_stream_record_id=row.record_id,
            event_id=row.event_id,
            context_id=row.context_id,
            trace_id=row.trace_id,
            module_id=row.module_id,
            action=row.action,
            status=row.status,
            timestamp=row.timestamp,
            payload=dict(row.payload),
            metadata_json={
                **dict(row.metadata_json),
                "storage_record": record.model_dump(mode="json"),
            },
        )
        with self._session() as db:
            db.add(audit)
            self._commit(db)
            return audit

    def query(
        self,
        *,
        org_id: str | None = None,
        module_id: str | None = None,
        context_id: str | None = None,
        trace_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[AuditLogRecord, ...]:
        with self._session() as db:
            statement = select(AuditLogRecord)
            effective_org_id = org_id or self._org_id
            if effective_org_id is not None:
                statement = statement.where(AuditLogRecord.org_id == effective_org_id)
            if module_id is not None:
                statement = statement.where(AuditLogRecord.module_id == module_id)
            if context_id is not None:
                statement = statement.where(AuditLogRecord.context_id == context_id)
            if trace_id is not None:
                statement = statement.where(AuditLogRecord.trace_id == trace_id)
            statement = statement.order_by(
                AuditLogRecord.timestamp.desc(),
                AuditLogRecord.id.desc(),
            )
            if limit is not None:
                statement = statement.limit(max(limit, 0))
            return tuple(db.scalars(statement))

    @contextmanager
    def _session(self) -> Iterator[Session]:
        if self._db is not None:
            yield self._db
            return
        from ..db.session import SessionLocal

        with SessionLocal() as db:
            yield db

    def _commit(self, db: Session) -> None:
        if self._db is None:
            db.commit()
        else:
            db.flush()

    def _resolve_org_id(self, explicit_org_id: str | None = None) -> str:
        for value in (explicit_org_id, self._org_id):
            if isinstance(value, str) and value.strip():
                return value.strip()[:40]
        try:
            from .data_isolation import current_org_data_isolation_context

            context = current_org_data_isolation_context()
        except Exception:
            context = None
        if context is not None and context.org_id:
            return context.org_id[:40]
        return "platform"

    def _metadata_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            return dict(metadata)
        return {}


class QueryOptimizer:
    def optimize_search(self, query: SearchLogsQuery) -> QueryOptimizationPlan:
        fields = [
            field
            for field, value in (
                ("context_id", query.context_id),
                ("trace_id", query.trace_id),
                ("timestamp", query.time_range),
                ("module", query.module),
                ("event_type", query.event_type),
                ("product_key", query.product_key),
                ("user_id", query.user_id),
            )
            if value is not None
        ]
        primary_index = self._select_index(
            query_type="search",
            context_id=query.context_id,
            trace_id=query.trace_id,
            time_range=query.time_range,
            module=query.module,
            event_type=query.event_type,
            product_key=query.product_key,
            user_id=query.user_id,
            status=None,
            action=None,
        )
        return QueryOptimizationPlan(
            query_type="search",
            primary_index=primary_index,
            index_used=(primary_index,),
            post_filters=_post_filter_fields(
                primary_index=primary_index,
                fields=fields,
            ),
            time_first_filtering=primary_index == IDX_TIMESTAMP,
            module_partition_pruning=query.module is not None,
            cache_key=_cache_key(
                "search",
                context_id=query.context_id,
                event_type=query.event_type,
                module=query.module,
                product_key=query.product_key,
                time_range=query.time_range,
                trace_id=query.trace_id,
                user_id=query.user_id,
            ),
            rationale="Selected the most selective C17D index available for search.",
        )

    def optimize_filter(self, query: FilterSystemQuery) -> QueryOptimizationPlan:
        hints = self._expression_hints(query.expression)
        context_id = query.context_id or hints.get("context_id")
        trace_id = query.trace_id or hints.get("trace_id")
        module = query.module or hints.get("module")
        event_type = query.event_type or hints.get("event_type")
        product_key = query.product_key or hints.get("product_key")
        user_id = query.user_id or hints.get("user_id")
        status = query.status or hints.get("status")
        action = query.action or hints.get("action")

        fields = [
            field
            for field, value in (
                ("timestamp", query.time_range),
                ("status", status),
                ("latency_ms", query.min_latency_ms or query.max_latency_ms),
                ("action", action),
                ("module", module),
                ("event_type", event_type),
                ("context_id", context_id),
                ("trace_id", trace_id),
                ("product_key", product_key),
                ("user_id", user_id),
            )
            if value is not None
        ]
        primary_index = self._select_index(
            query_type="filter",
            context_id=context_id,
            trace_id=trace_id,
            time_range=query.time_range,
            module=module,
            event_type=event_type,
            product_key=product_key,
            user_id=user_id,
            status=status,
            action=action,
        )
        return QueryOptimizationPlan(
            query_type="filter",
            primary_index=primary_index,
            index_used=(primary_index,),
            post_filters=_post_filter_fields(
                primary_index=primary_index,
                fields=fields,
            ),
            time_first_filtering=primary_index == IDX_TIMESTAMP,
            module_partition_pruning=module is not None,
            cache_key=_cache_key(
                "filter",
                action=action,
                context_id=context_id,
                event_type=event_type,
                module=module,
                product_key=product_key,
                status=status,
                time_range=query.time_range,
                trace_id=trace_id,
                user_id=user_id,
            ),
            rationale="Selected C17D timestamp first for broad filters, then exact indexes.",
        )

    def optimize_drill_down(self, query: DrillDownQuery) -> QueryOptimizationPlan:
        primary_index = IDX_TRACE if query.trace_id is not None else IDX_CONTEXT
        return QueryOptimizationPlan(
            query_type="drill_down",
            primary_index=primary_index,
            index_used=(primary_index,),
            post_filters=("entity_type",),
            cache_key=_cache_key(
                "drill_down",
                context_id=query.context_id,
                trace_id=query.trace_id,
            ),
            rationale="Trace drill-down uses trace_id first, then context_id.",
        )

    def _select_index(
        self,
        *,
        query_type: str,
        context_id: str | None,
        trace_id: str | None,
        time_range: StorageTimeRange | None,
        module: str | None,
        event_type: str | None,
        product_key: str | None,
        user_id: str | None,
        status: str | None,
        action: str | None,
    ) -> str:
        if query_type == "filter" and time_range is not None:
            return IDX_TIMESTAMP
        if trace_id is not None:
            return IDX_TRACE
        if context_id is not None:
            return IDX_CONTEXT
        if time_range is not None:
            return IDX_TIMESTAMP
        if module is not None or event_type is not None:
            return IDX_MODULE_EVENT
        if product_key is not None or user_id is not None or status is not None:
            return IDX_PRODUCT_USER_STATUS
        if action is not None:
            return IDX_ACTION_SHADOW
        return IDX_TIMESTAMP

    def _expression_hints(
        self,
        expression: FilterExpression | None,
    ) -> dict[str, str]:
        if expression is None:
            return {}
        hints: dict[str, str] = {}
        for condition in expression.conditions:
            value = _string_value(condition.value)
            if condition.comparator == "eq" and value is not None:
                hints.setdefault(condition.field, value)
        for child in expression.children:
            hints.update(self._expression_hints(child))
        return hints


class AuditQueryEngine:
    def __init__(
        self,
        storage: StorageAdapter,
        *,
        optimizer: QueryOptimizer | None = None,
    ) -> None:
        self.storage = storage
        self.optimizer = optimizer or QueryOptimizer()
        self._snapshot = _empty_snapshot()
        self._candidate_cache: dict[
            tuple[str, tuple[str, ...]], tuple[StorageRecordEnvelope, ...]
        ] = {}

    def search_logs(
        self,
        *,
        user_id: str | None = None,
        module: LogModule | None = None,
        context_id: str | None = None,
        event_type: str | None = None,
        product_key: str | None = None,
        trace_id: str | None = None,
        time_range: StorageTimeRange | None = None,
        limit: int | None = None,
    ) -> QueryResult:
        started = perf_counter()
        query = SearchLogsQuery(
            user_id=user_id,
            module=module,
            context_id=context_id,
            event_type=event_type,
            product_key=product_key,
            trace_id=trace_id,
            time_range=time_range,
            limit=limit,
        )
        plan = self.optimizer.optimize_search(query)
        candidates, cache_hit, searched_tiers = self._candidate_records(
            plan,
            context_id=query.context_id,
            event_type=query.event_type,
            module=query.module,
            product_key=query.product_key,
            time_range=query.time_range,
            trace_id=query.trace_id,
            user_id=query.user_id,
        )
        filtered = [
            record
            for record in candidates
            if record.entity_type == "LogEntry" and self._matches_search(record, query)
        ]
        data = tuple(self.decode_storage_record(record) for record in filtered)
        data = data[: query.limit] if query.limit is not None else data
        return self._result(
            started=started,
            query_type="search",
            data=data,
            plan=plan,
            cache_hit=cache_hit,
            candidate_count=len(candidates),
            searched_tiers=searched_tiers,
        )

    def filter_system(
        self,
        *,
        time_range: StorageTimeRange | None = None,
        status: str | None = None,
        min_latency_ms: float | None = None,
        max_latency_ms: float | None = None,
        action: str | None = None,
        module: str | None = None,
        context_id: str | None = None,
        trace_id: str | None = None,
        product_key: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        operator: str = "AND",
        expression: FilterExpression | None = None,
        entity_types: tuple[str, ...] = ("LogEntry", "ExecutionTrace", "EventRaw"),
        limit: int | None = None,
    ) -> QueryResult:
        started = perf_counter()
        query = FilterSystemQuery(
            time_range=time_range,
            status=status,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
            action=action,
            module=module,
            context_id=context_id,
            trace_id=trace_id,
            product_key=product_key,
            user_id=user_id,
            event_type=event_type,
            operator=operator,  # type: ignore[arg-type]
            expression=expression,
            entity_types=entity_types,  # type: ignore[arg-type]
            limit=limit,
        )
        plan = self.optimizer.optimize_filter(query)
        candidates, cache_hit, searched_tiers = self._candidate_records(
            plan,
            action=query.action,
            context_id=query.context_id,
            event_type=query.event_type,
            module=query.module,
            product_key=query.product_key,
            status=query.status,
            time_range=query.time_range,
            trace_id=query.trace_id,
            user_id=query.user_id,
        )
        expression_tree = self._combined_expression(query)
        filtered = [
            record
            for record in candidates
            if record.entity_type in query.entity_types
            and self._matches_time_range(record, query.time_range)
            and (
                expression_tree is None
                or self._matches_expression(record, expression_tree)
            )
        ]
        data = tuple(self.decode_storage_record(record) for record in filtered)
        data = data[: query.limit] if query.limit is not None else data
        return self._result(
            started=started,
            query_type="filter",
            data=data,
            plan=plan,
            cache_hit=cache_hit,
            candidate_count=len(candidates),
            searched_tiers=searched_tiers,
        )

    def drill_down(
        self,
        *,
        context_id: str | None = None,
        trace_id: str | None = None,
        limit: int | None = None,
    ) -> QueryResult:
        started = perf_counter()
        query = DrillDownQuery(context_id=context_id, trace_id=trace_id, limit=limit)
        plan = self.optimizer.optimize_drill_down(query)
        candidates, cache_hit, searched_tiers = self._candidate_records(
            plan,
            context_id=query.context_id,
            trace_id=query.trace_id,
        )
        trace_records = [
            record
            for record in candidates
            if record.entity_type == "ExecutionTrace"
            and (query.context_id is None or record.context_id == query.context_id)
            and (query.trace_id is None or record.trace_id == query.trace_id)
        ]
        if query.limit is not None:
            trace_records = trace_records[: query.limit]
        traces = tuple(
            data
            for data in (self.decode_storage_record(record) for record in trace_records)
            if isinstance(data, ExecutionTrace)
        )
        expansions = tuple(self._drill_down_expansion(trace) for trace in traces)
        return self._result(
            started=started,
            query_type="drill_down",
            data=traces,
            plan=plan,
            cache_hit=cache_hit,
            candidate_count=len(candidates),
            searched_tiers=searched_tiers,
            drill_down=expansions,
        )

    def decode_storage_record(
        self,
        record: StorageRecordEnvelope,
    ) -> LogEntry | ExecutionTrace | EventRaw:
        payload = dict(_payload(record))
        if record.entity_type == "LogEntry":
            return LogEntry.model_validate(
                {field: payload[field] for field in LOG_ENTRY_FIELDS if field in payload}
            )
        if record.entity_type == "ExecutionTrace":
            return ExecutionTrace.model_validate(
                {
                    field: payload[field]
                    for field in EXECUTION_TRACE_FIELDS
                    if field in payload
                }
            )
        return EventRaw.model_validate(
            {
                field: payload[field]
                for field in EventRaw.model_fields
                if field in payload
            }
        )

    def _candidate_records(
        self,
        plan: QueryOptimizationPlan,
        **hints: Any,
    ) -> tuple[tuple[StorageRecordEnvelope, ...], bool, tuple[str, ...]]:
        snapshot = self._current_snapshot()
        cache_identity = (plan.cache_key, snapshot.version)
        if cache_identity in self._candidate_cache:
            records = self._candidate_cache[cache_identity]
            return records, True, self._searched_tiers(records)

        if plan.primary_index == IDX_CONTEXT and hints.get("context_id") is not None:
            result = self.storage.query_by_context_id(
                normalize_context_id(_string_value(hints["context_id"])),
            )
            records = result.records
            searched_tiers = result.searched_tiers
        elif plan.primary_index == IDX_TRACE and hints.get("trace_id") is not None:
            result = self.storage.query_by_trace_id(
                normalize_context_id(_string_value(hints["trace_id"])),
            )
            records = result.records
            searched_tiers = result.searched_tiers
        elif plan.primary_index == IDX_TIMESTAMP and hints.get("time_range") is not None:
            result = self.storage.query_by_time_range(hints["time_range"])
            records = result.records
            searched_tiers = result.searched_tiers
        else:
            records = self._local_index_records(snapshot, plan.primary_index, hints)
            searched_tiers = self._searched_tiers(records)

        sorted_records = _sorted_records(records)
        self._candidate_cache[cache_identity] = sorted_records
        return sorted_records, False, searched_tiers

    def _local_index_records(
        self,
        snapshot: _IndexSnapshot,
        primary_index: str,
        hints: Mapping[str, Any],
    ) -> tuple[StorageRecordEnvelope, ...]:
        if primary_index == IDX_MODULE_EVENT:
            module = _string_value(hints.get("module"))
            event_type = _string_value(hints.get("event_type"))
            if module is not None and event_type is not None:
                return snapshot.by_module_event_type.get((module, event_type), ())
            if module is not None:
                return snapshot.by_module.get(module, ())
            if event_type is not None:
                return snapshot.by_event_type.get(event_type, ())
        if primary_index == IDX_PRODUCT_USER_STATUS:
            product_key = _string_value(hints.get("product_key"))
            user_id = _string_value(hints.get("user_id"))
            status = _string_value(hints.get("status"))
            if product_key is not None:
                return snapshot.by_product_key.get(product_key, ())
            if user_id is not None:
                return snapshot.by_user_id.get(user_id, ())
            if status is not None:
                return snapshot.by_status.get(status, ())
        if primary_index == IDX_ACTION_SHADOW:
            action = _string_value(hints.get("action"))
            if action is not None:
                return snapshot.by_action.get(action.lower(), ())
        return snapshot.records

    def _current_snapshot(self) -> _IndexSnapshot:
        records = self._adapter_records()
        version = tuple(_record_version(record) for record in _sorted_records(records))
        if version != self._snapshot.version:
            self._snapshot = _build_index_snapshot(records)
            self._candidate_cache.clear()
        return self._snapshot

    def _adapter_records(self) -> tuple[StorageRecordEnvelope, ...]:
        records = getattr(self.storage, "records", ())
        if callable(records):
            records = records()
        if isinstance(records, Sequence) and not isinstance(records, str):
            return tuple(
                record
                for record in records
                if isinstance(record, StorageRecordEnvelope)
            )
        return ()

    def _matches_search(self, record: StorageRecordEnvelope, query: SearchLogsQuery) -> bool:
        return all(
            (
                query.context_id is None or record.context_id == query.context_id,
                query.trace_id is None or record.trace_id == query.trace_id,
                query.user_id is None or record.user_id == query.user_id,
                query.product_key is None or record.product_key == query.product_key,
                query.module is None or record.module == query.module,
                query.event_type is None or record.event_type == query.event_type,
                self._matches_time_range(record, query.time_range),
            )
        )

    def _matches_time_range(
        self,
        record: StorageRecordEnvelope,
        time_range: StorageTimeRange | None,
    ) -> bool:
        if time_range is None:
            return True
        if time_range.start_at is not None and record.timestamp < time_range.start_at:
            return False
        if time_range.end_at is not None and record.timestamp > time_range.end_at:
            return False
        return True

    def _combined_expression(
        self,
        query: FilterSystemQuery,
    ) -> FilterExpression | None:
        conditions: list[FilterCondition] = []
        for field, value in (
            ("status", query.status),
            ("action", query.action),
            ("module", query.module),
            ("context_id", query.context_id),
            ("trace_id", query.trace_id),
            ("product_key", query.product_key),
            ("user_id", query.user_id),
            ("event_type", query.event_type),
        ):
            if value is not None:
                comparator = "contains" if field == "action" else "eq"
                conditions.append(
                    FilterCondition(
                        field=field,  # type: ignore[arg-type]
                        comparator=comparator,
                        value=value,
                    )
                )
        if query.min_latency_ms is not None:
            conditions.append(
                FilterCondition(
                    field="latency_ms",
                    comparator="gte",
                    value=query.min_latency_ms,
                )
            )
        if query.max_latency_ms is not None:
            conditions.append(
                FilterCondition(
                    field="latency_ms",
                    comparator="lte",
                    value=query.max_latency_ms,
                )
            )

        direct = (
            FilterExpression(
                operator=query.operator,
                conditions=tuple(conditions),
            )
            if conditions
            else None
        )
        if query.expression is not None and direct is not None:
            return FilterExpression(operator="AND", children=(direct, query.expression))
        return query.expression or direct

    def _matches_expression(
        self,
        record: StorageRecordEnvelope,
        expression: FilterExpression,
    ) -> bool:
        values = [
            self._matches_condition(record, condition)
            for condition in expression.conditions
        ]
        values.extend(
            self._matches_expression(record, child) for child in expression.children
        )
        if expression.operator == "AND":
            return all(values)
        if expression.operator == "OR":
            return any(values)
        return not all(values)

    def _matches_condition(
        self,
        record: StorageRecordEnvelope,
        condition: FilterCondition,
    ) -> bool:
        values = self._field_values(record, condition.field)
        if condition.comparator == "neq":
            return all(
                not self._compare_value(value, "eq", condition.value)
                for value in values
            )
        return any(
            self._compare_value(value, condition.comparator, condition.value)
            for value in values
        )

    def _field_values(
        self,
        record: StorageRecordEnvelope,
        field: str,
    ) -> tuple[Any, ...]:
        if field == "timestamp":
            return (record.timestamp,)
        if field == "status":
            return (record.status,)
        if field == "latency_ms":
            return (_record_latency_ms(record),)
        if field == "action":
            return _record_actions(record)
        if field == "module":
            return _record_modules(record)
        if field == "event_type":
            return (record.event_type,)
        if field == "user_id":
            return (record.user_id,)
        if field == "product_key":
            return (record.product_key,)
        if field == "context_id":
            return (record.context_id,)
        if field == "trace_id":
            return (record.trace_id,)
        return ()

    def _compare_value(self, value: Any, comparator: str, target: Any) -> bool:
        if value is None:
            return False
        if comparator == "contains":
            needle = _string_value(target)
            return needle is not None and needle.lower() in str(value).lower()
        if comparator == "in":
            if isinstance(target, Sequence) and not isinstance(target, str):
                return str(value) in {str(item) for item in target}
            return False

        if isinstance(value, datetime):
            target_ts = _timestamp_value(target)
            if target_ts is None:
                return False
            return self._compare_ordered(value, comparator, target_ts)

        left_number = self._number_value(value)
        right_number = self._number_value(target)
        if left_number is not None and right_number is not None:
            return self._compare_ordered(left_number, comparator, right_number)

        left = str(value)
        right = str(target)
        if comparator == "eq":
            return left == right
        if comparator == "neq":
            return left != right
        return False

    def _compare_ordered(self, left: Any, comparator: str, right: Any) -> bool:
        if comparator == "eq":
            return left == right
        if comparator == "neq":
            return left != right
        if comparator == "gt":
            return left > right
        if comparator == "gte":
            return left >= right
        if comparator == "lt":
            return left < right
        if comparator == "lte":
            return left <= right
        return False

    def _number_value(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _drill_down_expansion(self, trace: ExecutionTrace) -> DrillDownChainExpansion:
        breakdown = tuple(
            DrillDownStepBreakdown(
                step_index=step.step_index,
                step_id=step.step_id,
                module=step.module,
                action=step.action,
                status=step.status,
                latency_ms=step.latency_ms,
                timestamp=step.timestamp,
                dependency_step_id=step.dependency_step_id,
                input_keys=tuple(sorted(step.input)),
                output_keys=tuple(sorted(step.output)),
                error_present=step.error is not None,
            )
            for step in trace.chain
        )
        return DrillDownChainExpansion(
            context_id=trace.context_id,
            trace_id=trace.trace_id,
            root_event_id=trace.root_event_id,
            root_event=f"root_event:{trace.root_event_id}",
            step_count=len(trace.chain),
            total_latency_ms=trace.total_latency_ms,
            final_status=trace.final_status,
            breakdown=breakdown,
            text_tree=self._drill_down_text_tree(trace),
        )

    def _drill_down_text_tree(self, trace: ExecutionTrace) -> tuple[str, ...]:
        lines = [
            f"{trace.context_id} -> root_event:{trace.root_event_id}",
            "chain expansion:",
        ]
        steps_by_module: dict[str, list[ExecutionTraceStep]] = defaultdict(list)
        for step in trace.chain:
            steps_by_module[step.module].append(step)

        for index, (module, label) in enumerate(CHAIN_STAGE_LABELS):
            lines.append(label)
            for step in steps_by_module.get(module, ()):
                lines.append(
                    "  "
                    f"[{step.step_index}] {step.action} "
                    f"status={step.status} latency_ms={step.latency_ms:g}"
                )
            if index < len(CHAIN_STAGE_LABELS) - 1:
                lines.append("  v")

        for step in steps_by_module.get("system", ()):
            lines.append(
                "system boundary "
                f"[{step.step_index}] {step.action} status={step.status}"
            )
        return tuple(lines)

    def _result(
        self,
        *,
        started: float,
        query_type: str,
        data: tuple[LogEntry | ExecutionTrace | EventRaw, ...],
        plan: QueryOptimizationPlan,
        cache_hit: bool,
        candidate_count: int,
        searched_tiers: tuple[str, ...],
        drill_down: tuple[DrillDownChainExpansion, ...] = (),
    ) -> QueryResult:
        return QueryResult(
            result_count=len(data),
            execution_time_ms=(perf_counter() - started) * 1000,
            data=data,
            metadata=QueryMetadata(
                query_type=query_type,  # type: ignore[arg-type]
                index_used=plan.index_used,
                cache_hit=cache_hit,
                optimizer_plan_id=plan.plan_id,
                searched_tiers=searched_tiers,  # type: ignore[arg-type]
                candidate_count=candidate_count,
                post_filters=plan.post_filters,
                full_scan_avoided=plan.full_scan_avoided,
                time_first_filtering=plan.time_first_filtering,
                module_partition_pruning=plan.module_partition_pruning,
                drill_down=drill_down,
            ),
        )

    def _searched_tiers(
        self,
        records: Sequence[StorageRecordEnvelope],
    ) -> tuple[str, ...]:
        tiers = tuple(dict.fromkeys(record.tier for record in records))
        if tiers:
            return tiers
        return ("L1_hot", "L2_warm", "L3_cold")


def get_audit_query_engine_design() -> AuditQueryEngineDesign:
    return AuditQueryEngineDesign()


def get_search_logs_api_design() -> SearchLogsAPIDesign:
    return SearchLogsAPIDesign()


def get_filter_system_logic_design() -> FilterSystemLogicDesign:
    return FilterSystemLogicDesign()


def get_drill_down_execution_model_design() -> DrillDownExecutionModelDesign:
    return DrillDownExecutionModelDesign()


def get_audit_query_index_usage_strategy() -> AuditQueryIndexUsageStrategy:
    return AuditQueryIndexUsageStrategy()


def get_query_optimizer_design() -> QueryOptimizerDesign:
    return QueryOptimizerDesign()


def get_query_result_schema_definition() -> QueryResultSchemaDefinition:
    return QueryResultSchemaDefinition()


def get_c17e_storage_integration_design() -> C17EStorageIntegrationDesign:
    return C17EStorageIntegrationDesign()


def get_audit_query_engine_completion_status() -> AuditQueryEngineCompletionStatus:
    return AuditQueryEngineCompletionStatus()
