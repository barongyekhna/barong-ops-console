from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.app.schemas.event_collector import AuditEvent
from backend.app.schemas.execution_trace import ExecutionTrace, ExecutionTraceStep
from backend.app.schemas.storage_layer import EventRaw, StorageTimeRange
from backend.app.schemas.structured_logs import LogEntity, LogEntry, LogMetadata
from backend.app.services.storage_layer import (
    InMemoryStorageAdapter,
    get_c17c_to_c17d_storage_migration_strategy,
    get_hot_warm_cold_data_flow,
    get_query_performance_strategy,
    get_storage_adapter_interface_design,
    get_storage_architecture_design,
    get_storage_backend_design,
    get_storage_data_model_design,
    get_storage_indexing_strategy,
    get_storage_layer_completion_status,
    get_storage_retention_policy,
    get_storage_write_path_design,
    resolve_storage_tier,
    storage_record_from_event_raw,
    storage_record_from_execution_trace,
    storage_record_from_log_entry,
)


BASE_TIME = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


def _log_entry(
    *,
    timestamp: datetime = BASE_TIME,
    context_id: str = "ctx-c17d-001",
    trace_id: str = "trace-c17d-001",
    event_id: str = "evt-c17d-log",
) -> LogEntry:
    return LogEntry(
        event_id=event_id,
        timestamp=timestamp,
        context_id=context_id,
        module="C15",
        event_type="workflow.execution.end",
        action="workflow execution end",
        source="n8n",
        entity=LogEntity(
            user_id="user-42",
            product_key="product.demo",
            workflow_id="workflow.demo",
            request_id=context_id,
        ),
        status="success",
        latency_ms=15,
        request={"trace_id": trace_id, "workflow_id": "workflow.demo"},
        response={"ok": True},
        metadata=LogMetadata(retry_count=1),
        tags=("c17b", "module:execution"),
    )


def _trace(
    *,
    timestamp: datetime = BASE_TIME,
    context_id: str = "ctx-c17d-001",
    trace_id: str = "trace-c17d-001",
) -> ExecutionTrace:
    return ExecutionTrace(
        trace_id=trace_id,
        context_id=context_id,
        root_event_id="evt-c17d-trace-root",
        chain=(
            ExecutionTraceStep(
                step_id="step.db.write",
                step_index=0,
                module="DB",
                action="write_success_failure",
                input={"product_key": "product.demo", "user_id": "user-42"},
                output={"stored": True},
                status="success",
                latency_ms=3,
                timestamp=timestamp,
            ),
        ),
        final_status="success",
        total_latency_ms=3,
    )


def test_c17d_design_models_cover_required_outputs() -> None:
    architecture = get_storage_architecture_design()
    data_model = get_storage_data_model_design()
    adapter = get_storage_adapter_interface_design()
    backend = get_storage_backend_design()
    indexing = get_storage_indexing_strategy()
    retention = get_storage_retention_policy()
    write_path = get_storage_write_path_design()
    flow = get_hot_warm_cold_data_flow()
    migration = get_c17c_to_c17d_storage_migration_strategy()
    query = get_query_performance_strategy()
    completion = get_storage_layer_completion_status()

    assert [tier.tier_id for tier in architecture.tiers] == [
        "L1_hot",
        "L2_warm",
        "L3_cold",
    ]
    assert architecture.tiers[0].age_window == "0-7 days"
    assert architecture.tiers[1].age_window == "7-90 days"
    assert architecture.tiers[2].compression_required is True

    assert {entity.entity_type for entity in data_model.entities} == {
        "LogEntry",
        "ExecutionTrace",
        "EventRaw",
    }
    assert {
        "write_log(log)",
        "write_trace(trace)",
        "query_by_context_id(context_id)",
        "query_by_trace_id(trace_id)",
        "query_by_time_range(time_range)",
        "archive_to_cold_storage()",
    }.issubset(set(adapter.method_names))
    assert backend.postgresql_is_primary_storage is True
    assert backend.redis_is_hot_cache is True
    assert backend.object_storage_is_cold_archive is True

    assert indexing.primary_index.fields == ("context_id",)
    assert indexing.secondary_indexes[0].fields == ("trace_id",)
    assert indexing.search_index.fields == ("module", "event_type")
    assert indexing.time_series_index.fields == ("timestamp",)
    assert set(indexing.required_index_fields) == {
        "context_id",
        "trace_id",
        "event_id",
        "product_key",
        "user_id",
        "module",
        "timestamp",
        "status",
    }
    assert retention.hot_retention_days == 7
    assert retention.warm_retention_days == 90
    assert retention.cold_retention_years == (1, 3)
    assert write_path.ordered_path == (
        "C17A Event",
        "C17B LogEntry",
        "C17C ExecutionTrace",
        "C17D Storage Layer",
    )
    assert "TTL job" in flow.warm_flow[0]
    assert migration.c17c_modified is False
    assert migration.database_migration_executed is True
    assert migration.execution_replay_implemented is False
    assert query.primary_index == "context_id"
    assert completion.completion_status == "complete"


def test_c17d_projects_log_trace_and_raw_event_records() -> None:
    log_record = storage_record_from_log_entry(_log_entry(), now=BASE_TIME)
    trace_record = storage_record_from_execution_trace(
        _trace(timestamp=BASE_TIME - timedelta(days=30)),
        now=BASE_TIME,
    )
    raw_record = storage_record_from_event_raw(
        AuditEvent(
            event_id="evt-c17a-raw",
            timestamp=BASE_TIME - timedelta(days=100),
            event_type="api.response.completed",
            module="C15",
            action="POST /webhook",
            context_id="ctx-c17d-001",
            user_id="user-42",
            product_key="product.demo",
            workflow_id="workflow.demo",
            source="backend",
            status="failed",
            payload={"trace_id": "trace-c17d-001", "api_key": "unsafe"},
        ),
        now=BASE_TIME,
    )

    assert log_record.entity_type == "LogEntry"
    assert log_record.tier == "L1_hot"
    assert log_record.backend_targets == ("postgresql", "redis")
    assert log_record.trace_id == "trace-c17d-001"
    assert log_record.product_key == "product.demo"

    assert trace_record.entity_type == "ExecutionTrace"
    assert trace_record.tier == "L2_warm"
    assert trace_record.event_type == "execution.trace"
    assert trace_record.payload["modules"] == ["DB"]
    assert trace_record.user_id == "user-42"

    assert raw_record.entity_type == "EventRaw"
    assert raw_record.tier == "L3_cold"
    assert raw_record.compressed is True
    assert raw_record.payload["payload"]["api_key"] == "[redacted]"


def test_c17d_in_memory_adapter_queries_by_required_indexes() -> None:
    adapter = InMemoryStorageAdapter(now=BASE_TIME)

    log_result = adapter.write_log(_log_entry())
    trace_result = adapter.write_trace(_trace(timestamp=BASE_TIME - timedelta(days=10)))
    raw_result = adapter.write_event_raw(
        EventRaw(
            event_id="evt-c17d-raw",
            timestamp=BASE_TIME - timedelta(days=100),
            context_id="ctx-c17d-001",
            trace_id="trace-c17d-001",
            product_key="product.demo",
            user_id="user-42",
            module="C15",
            event_type="callback.received",
            action="callback received",
            source="webhook",
            status="success",
        )
    )

    assert log_result.indexed_fields == (
        "context_id",
        "trace_id",
        "event_id",
        "product_key",
        "user_id",
        "module",
        "timestamp",
        "status",
    )
    assert trace_result.tier == "L2_warm"
    assert raw_result.tier == "L3_cold"

    by_context = adapter.query_by_context_id("ctx-c17d-001")
    by_trace = adapter.query_by_trace_id("trace-c17d-001")
    by_time = adapter.query_by_time_range(
        StorageTimeRange(
            start_at=BASE_TIME - timedelta(days=20),
            end_at=BASE_TIME + timedelta(minutes=1),
        )
    )

    assert by_context.total_count == 3
    assert by_context.indexes_used == ("idx_c17d_context_id",)
    assert by_trace.total_count == 3
    assert by_trace.indexes_used == ("idx_c17d_trace_id",)
    assert by_time.total_count == 2
    assert by_time.indexes_used == ("idx_c17d_timestamp",)
    assert {record.entity_type for record in by_time.records} == {
        "LogEntry",
        "ExecutionTrace",
    }


def test_c17d_archive_to_cold_storage_updates_records_without_external_io() -> None:
    adapter = InMemoryStorageAdapter(now=BASE_TIME)
    adapter.write_log(_log_entry(timestamp=BASE_TIME - timedelta(days=30)))

    assert adapter.records[0].tier == "L2_warm"

    archive = adapter.archive_to_cold_storage(before=BASE_TIME - timedelta(days=7))

    assert archive.candidate_count == 1
    assert archive.archived_count == 1
    assert archive.archive_object_keys[0].endswith(".jsonl.gz")
    assert adapter.records[0].tier == "L3_cold"
    assert adapter.records[0].compressed is True
    assert adapter.records[0].backend_targets == ("s3_object_storage", "postgresql")


def test_c17d_validates_tiers_time_ranges_and_write_inputs() -> None:
    assert resolve_storage_tier(BASE_TIME, now=BASE_TIME) == "L1_hot"
    assert (
        resolve_storage_tier(BASE_TIME - timedelta(days=30), now=BASE_TIME)
        == "L2_warm"
    )
    assert (
        resolve_storage_tier(BASE_TIME - timedelta(days=120), now=BASE_TIME)
        == "L3_cold"
    )

    adapter = InMemoryStorageAdapter(now=BASE_TIME)
    raw_event = AuditEvent(
        event_type="unit.test",
        module="system",
        action="unit.test",
        context_id="ctx-unit",
        source="backend",
        status="success",
    )
    with pytest.raises(TypeError, match="LogEntry"):
        adapter.write_log(raw_event)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        StorageTimeRange(
            start_at=BASE_TIME,
            end_at=BASE_TIME - timedelta(seconds=1),
        )
