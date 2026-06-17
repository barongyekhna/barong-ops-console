from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.schemas.audit_query_engine import FilterCondition, FilterExpression
from backend.app.schemas.execution_trace import ExecutionTrace, ExecutionTraceStep
from backend.app.schemas.storage_layer import EventRaw, StorageTimeRange
from backend.app.schemas.structured_logs import LogEntity, LogEntry, LogMetadata
from backend.app.services.audit_query_engine import (
    AuditQueryEngine,
    get_audit_query_engine_completion_status,
    get_audit_query_engine_design,
    get_audit_query_index_usage_strategy,
    get_c17e_storage_integration_design,
    get_drill_down_execution_model_design,
    get_filter_system_logic_design,
    get_query_optimizer_design,
    get_query_result_schema_definition,
    get_search_logs_api_design,
)
from backend.app.services.storage_layer import InMemoryStorageAdapter


BASE_TIME = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


def _log_entry(
    *,
    event_id: str,
    context_id: str,
    trace_id: str,
    user_id: str,
    module: str = "C15",
    event_type: str = "workflow.execution.end",
    action: str = "workflow execution end",
    status: str = "success",
    latency_ms: float = 15,
    timestamp: datetime = BASE_TIME,
) -> LogEntry:
    module_tags = {
        "C13": "control",
        "C14": "capability",
        "C15": "execution",
        "C16": "security",
        "C17": "observability",
        "system": "infra",
    }
    return LogEntry(
        event_id=event_id,
        timestamp=timestamp,
        context_id=context_id,
        module=module,  # type: ignore[arg-type]
        event_type=event_type,
        action=action,
        source="n8n",
        entity=LogEntity(
            user_id=user_id,
            product_key="product.demo",
            workflow_id="workflow.demo",
            request_id=context_id,
        ),
        status=status,  # type: ignore[arg-type]
        latency_ms=latency_ms,
        request={"trace_id": trace_id, "workflow_id": "workflow.demo"},
        response={"ok": status == "success"},
        metadata=LogMetadata(retry_count=1),
        tags=("c17b", f"module:{module_tags[module]}"),
    )


def _trace() -> ExecutionTrace:
    steps = (
        ExecutionTraceStep(
            step_id="step.c14.capability",
            step_index=0,
            module="C14",
            action="capability_selection_result",
            input={"capability": "reasoning", "product_key": "product.demo"},
            output={"model": "model.reasoning.primary_v1"},
            status="success",
            latency_ms=12,
            timestamp=BASE_TIME,
        ),
        ExecutionTraceStep(
            step_id="step.c15.workflow",
            step_index=1,
            module="C15",
            action="workflow_trigger",
            input={"workflow_id": "workflow.demo", "user_id": "user-42"},
            output={"accepted": True},
            status="success",
            latency_ms=10,
            timestamp=BASE_TIME + timedelta(milliseconds=10),
            dependency_step_id="step.c14.capability",
        ),
        ExecutionTraceStep(
            step_id="step.n8n.node",
            step_index=2,
            module="n8n",
            action="node_execution_end",
            input={"node": "Classify"},
            output={"items": 1},
            status="success",
            latency_ms=18,
            timestamp=BASE_TIME + timedelta(milliseconds=20),
            dependency_step_id="step.c15.workflow",
        ),
        ExecutionTraceStep(
            step_id="step.ai.call",
            step_index=3,
            module="AI",
            action="response_receive",
            input={"provider": "GPT"},
            output={"tokens": 42},
            status="success",
            latency_ms=25,
            timestamp=BASE_TIME + timedelta(milliseconds=40),
            dependency_step_id="step.n8n.node",
        ),
        ExecutionTraceStep(
            step_id="step.db.write",
            step_index=4,
            module="DB",
            action="write_success_failure",
            input={"table": "future_execution_traces"},
            output={"stored": True},
            status="success",
            latency_ms=15,
            timestamp=BASE_TIME + timedelta(milliseconds=60),
            dependency_step_id="step.ai.call",
        ),
    )
    return ExecutionTrace(
        trace_id="trace-c17e-001",
        context_id="ctx-c17e-001",
        root_event_id="evt-root-c17e",
        chain=steps,
        final_status="success",
        total_latency_ms=80,
    )


def _engine() -> AuditQueryEngine:
    adapter = InMemoryStorageAdapter(now=BASE_TIME)
    adapter.write_log(
        _log_entry(
            event_id="evt-log-c15",
            context_id="ctx-c17e-001",
            trace_id="trace-c17e-001",
            user_id="user-42",
        )
    )
    adapter.write_log(
        _log_entry(
            event_id="evt-log-c14",
            context_id="ctx-c17e-002",
            trace_id="trace-c17e-002",
            user_id="user-99",
            module="C14",
            event_type="capability.selection.result",
            action="capability selection result",
            latency_ms=7,
        )
    )
    adapter.write_trace(_trace())
    adapter.write_event_raw(
        EventRaw(
            event_id="evt-raw-failed",
            timestamp=BASE_TIME,
            context_id="ctx-c17e-raw",
            trace_id="trace-c17e-raw",
            product_key="product.demo",
            user_id="user-42",
            module="C15",
            event_type="callback.received",
            action="callback received",
            source="webhook",
            status="failed",
        )
    )
    return AuditQueryEngine(adapter)


def test_c17e_design_models_cover_required_outputs() -> None:
    design = get_audit_query_engine_design()
    search = get_search_logs_api_design()
    filters = get_filter_system_logic_design()
    drill_down = get_drill_down_execution_model_design()
    indexes = get_audit_query_index_usage_strategy()
    optimizer = get_query_optimizer_design()
    result_schema = get_query_result_schema_definition()
    integration = get_c17e_storage_integration_design()
    completion = get_audit_query_engine_completion_status()

    assert design.supported_query_objects == (
        "LogEntry",
        "ExecutionTrace",
        "EventRaw",
        "StorageRecord",
    )
    assert search.filters == ("user_id", "module", "context_id", "event_type")
    assert filters.boolean_operators == ("AND", "OR", "NOT")
    assert drill_down.lookup_keys == ("context_id", "trace_id")
    assert indexes.required_indexes == (
        "idx_c17d_context_id",
        "idx_c17d_trace_id",
        "idx_c17d_module_event_type",
        "idx_c17d_timestamp",
        "idx_c17d_product_user_status",
    )
    assert optimizer.full_scan_avoidance is True
    assert result_schema.metadata_fields == ("query_type", "index_used", "cache_hit")
    assert integration.modifies_storage_layer is False
    assert completion.c17d_modified is False
    assert completion.database_migration_executed is True
    assert completion.ui_integrated is False


def test_c17e_search_logs_uses_c17d_indexes_and_returns_log_entries() -> None:
    engine = _engine()

    result = engine.search_logs(
        user_id="user-42",
        module="C15",
        context_id="ctx-c17e-001",
        event_type="workflow.execution.end",
    )
    cached = engine.search_logs(
        user_id="user-42",
        module="C15",
        context_id="ctx-c17e-001",
        event_type="workflow.execution.end",
    )
    by_module = engine.search_logs(module="C14")

    assert result.result_count == 1
    assert isinstance(result.data[0], LogEntry)
    assert result.data[0].event_id == "evt-log-c15"
    assert result.metadata.query_type == "search"
    assert result.metadata.index_used == ("idx_c17d_context_id",)
    assert result.metadata.cache_hit is False
    assert cached.metadata.cache_hit is True

    assert by_module.result_count == 1
    assert by_module.data[0].module == "C14"
    assert by_module.metadata.index_used == ("idx_c17d_module_event_type",)
    assert by_module.metadata.module_partition_pruning is True


def test_c17e_filter_system_supports_and_or_not_logic() -> None:
    engine = _engine()
    time_range = StorageTimeRange(
        start_at=BASE_TIME - timedelta(minutes=1),
        end_at=BASE_TIME + timedelta(minutes=1),
    )

    and_result = engine.filter_system(
        time_range=time_range,
        status="success",
        action="workflow",
        min_latency_ms=10,
        entity_types=("LogEntry",),
    )
    or_result = engine.filter_system(
        time_range=time_range,
        expression=FilterExpression(
            operator="OR",
            conditions=(
                FilterCondition(field="status", comparator="eq", value="failed"),
                FilterCondition(field="module", comparator="eq", value="AI"),
            ),
        ),
    )
    not_result = engine.filter_system(
        time_range=time_range,
        expression=FilterExpression(
            operator="NOT",
            conditions=(
                FilterCondition(field="status", comparator="eq", value="failed"),
            ),
        ),
    )

    assert and_result.result_count == 1
    assert and_result.data[0].event_id == "evt-log-c15"
    assert and_result.metadata.index_used == ("idx_c17d_timestamp",)
    assert and_result.metadata.time_first_filtering is True

    assert {item.context_id for item in or_result.data} == {
        "ctx-c17e-001",
        "ctx-c17e-raw",
    }
    assert all(item.status != "failed" for item in not_result.data)


def test_c17e_drill_down_returns_trace_breakdown_and_text_expansion() -> None:
    engine = _engine()

    result = engine.drill_down(trace_id="trace-c17e-001")

    assert result.result_count == 1
    assert isinstance(result.data[0], ExecutionTrace)
    assert [step.module for step in result.data[0].chain] == [
        "C14",
        "C15",
        "n8n",
        "AI",
        "DB",
    ]
    assert result.metadata.query_type == "drill_down"
    assert result.metadata.index_used == ("idx_c17d_trace_id",)

    drill_down = result.metadata.drill_down[0]
    assert drill_down.step_count == 5
    assert [step.module for step in drill_down.breakdown] == [
        "C14",
        "C15",
        "n8n",
        "AI",
        "DB",
    ]
    assert "C14 capability" in drill_down.text_tree
    assert "C15 workflow" in drill_down.text_tree
    assert "n8n nodes" in drill_down.text_tree
    assert "AI calls" in drill_down.text_tree
    assert "DB writes" in drill_down.text_tree
