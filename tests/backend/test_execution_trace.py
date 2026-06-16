from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.schemas.execution_trace import TraceStepEvent
from backend.app.schemas.structured_logs import LogEntity, LogEntry, LogMetadata
from backend.app.services.execution_trace import (
    TraceAggregator,
    aggregate_execution_trace,
    detect_missing_trace_steps,
    execution_trace_to_db_record,
    execution_trace_to_json,
    execution_trace_to_jsonl,
    get_c17b_to_c17c_migration_plan,
    get_cross_system_trace_mapping,
    get_execution_flow_diagram,
    get_execution_trace_completion_status,
    get_execution_trace_schema_definition,
    get_trace_aggregator_design,
    get_trace_hook_injection_points,
    get_trace_step_lifecycle_definition,
    get_trace_storage_format_design,
    trace_step_event_from_log_entry,
    trace_step_event_to_jsonl,
)


def test_c17c_design_models_cover_required_outputs() -> None:
    schema = get_execution_trace_schema_definition()
    hooks = get_trace_hook_injection_points()
    mapping = get_cross_system_trace_mapping()
    lifecycle = get_trace_step_lifecycle_definition()
    aggregator = get_trace_aggregator_design()
    storage = get_trace_storage_format_design()
    diagram = get_execution_flow_diagram()
    migration = get_c17b_to_c17c_migration_plan()
    completion = get_execution_trace_completion_status()

    assert schema.canonical_model == "ExecutionTrace"
    assert schema.fields == (
        "trace_id",
        "context_id",
        "root_event_id",
        "chain",
        "final_status",
        "total_latency_ms",
    )
    assert schema.chain_step_fields == (
        "step_id",
        "step_index",
        "module",
        "action",
        "input",
        "output",
        "status",
        "latency_ms",
        "timestamp",
        "error",
        "retry_count",
        "dependency_step_id",
    )
    assert schema.module_values == ("C14", "C15", "n8n", "AI", "DB", "system")

    hook_actions = {hook.action for hook in hooks.hooks}
    assert {
        "capability_selection_start",
        "capability_selection_result",
        "workflow_trigger",
        "workflow_step_start",
        "workflow_step_complete",
        "node_execution_start",
        "node_execution_end",
        "workflow_completion",
        "prompt_send",
        "response_receive",
        "write_start",
        "write_success_failure",
    }.issubset(hook_actions)
    assert all(hook.shares_trace_id_and_context_id for hook in hooks.hooks)

    assert [stage.stage for stage in mapping.stages] == [
        "frontend_request",
        "backend API (C13/C14/C16)",
        "execution engine (C15)",
        "n8n workflow",
        "AI call (GPT / DeepSeek / 4sapi)",
        "DB / FileStorage",
    ]
    assert lifecycle.dependency_rule == (
        "dependency_step_id references a previous step_id in the same trace"
    )
    assert aggregator.responsibilities == (
        "collect step events",
        "merge into ExecutionTrace",
        "maintain ordering",
        "compute latency",
        "detect missing steps",
    )
    assert storage.supported_formats == (
        "JSON debug",
        "JSONL stream",
        "future DB table",
    )
    assert storage.indexable_fields == (
        "trace_id",
        "context_id",
        "root_event_id",
        "module",
        "final_status",
    )
    assert "frontend_request" in diagram.lines[0]
    assert migration.c17a_modified is False
    assert migration.c17b_modified is False
    assert migration.database_migration_executed is False
    assert completion.completion_status == "complete"


def _event(
    *,
    step_id: str,
    step_index: int | None,
    lifecycle: str,
    module: str,
    action: str,
    status: str,
    timestamp: datetime,
    input_snapshot: dict | None = None,
    output_snapshot: dict | None = None,
    latency_ms: float = 0,
    dependency_step_id: str | None = None,
    retry_count: int = 0,
    error: dict | None = None,
) -> TraceStepEvent:
    return TraceStepEvent(
        trace_id="trace-c17c-001",
        context_id="ctx-c17c-001",
        root_event_id="evt-root-001",
        step_id=step_id,
        step_index=step_index,
        lifecycle=lifecycle,  # type: ignore[arg-type]
        module=module,  # type: ignore[arg-type]
        action=action,
        input=input_snapshot or {},
        output=output_snapshot or {},
        status=status,  # type: ignore[arg-type]
        latency_ms=latency_ms,
        timestamp=timestamp,
        retry_count=retry_count,
        dependency_step_id=dependency_step_id,
        error=error,
    )


def test_c17c_aggregator_merges_step_events_into_execution_trace() -> None:
    base = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    events = [
        _event(
            step_id="step.c14.capability",
            step_index=0,
            lifecycle="start",
            module="C14",
            action="capability_selection_start",
            status="pending",
            timestamp=base,
            input_snapshot={"capability": "reasoning"},
        ),
        _event(
            step_id="step.c14.capability",
            step_index=0,
            lifecycle="complete",
            module="C14",
            action="capability_selection_result",
            status="success",
            timestamp=base + timedelta(milliseconds=12),
            output_snapshot={"model": "model.reasoning.primary_v1"},
            latency_ms=12,
        ),
        _event(
            step_id="step.c15.workflow",
            step_index=1,
            lifecycle="complete",
            module="C15",
            action="workflow_trigger",
            status="success",
            timestamp=base + timedelta(milliseconds=20),
            input_snapshot={"workflow_id": "workflow.demo"},
            output_snapshot={"triggered": True},
            latency_ms=8,
            dependency_step_id="step.c14.capability",
        ),
        _event(
            step_id="step.n8n.node",
            step_index=2,
            lifecycle="start",
            module="n8n",
            action="node_execution_start",
            status="pending",
            timestamp=base + timedelta(milliseconds=30),
            input_snapshot={"node": "Classify"},
            dependency_step_id="step.c15.workflow",
        ),
        _event(
            step_id="step.n8n.node",
            step_index=2,
            lifecycle="complete",
            module="n8n",
            action="node_execution_end",
            status="success",
            timestamp=base + timedelta(milliseconds=55),
            output_snapshot={"items": 1},
            latency_ms=25,
            retry_count=1,
        ),
        _event(
            step_id="step.ai.call",
            step_index=3,
            lifecycle="complete",
            module="AI",
            action="response_receive",
            status="success",
            timestamp=base + timedelta(milliseconds=80),
            input_snapshot={"provider": "GPT"},
            output_snapshot={"tokens": 42},
            latency_ms=25,
            dependency_step_id="step.n8n.node",
        ),
        _event(
            step_id="step.db.write",
            step_index=4,
            lifecycle="complete",
            module="DB",
            action="write_success_failure",
            status="success",
            timestamp=base + timedelta(milliseconds=90),
            input_snapshot={"table": "future_execution_traces"},
            output_snapshot={"stored": True},
            latency_ms=10,
            dependency_step_id="step.ai.call",
        ),
    ]

    trace = aggregate_execution_trace(events)

    assert trace.trace_id == "trace-c17c-001"
    assert trace.context_id == "ctx-c17c-001"
    assert trace.root_event_id == "evt-root-001"
    assert trace.final_status == "success"
    assert [step.step_index for step in trace.chain] == [0, 1, 2, 3, 4]
    assert [step.module for step in trace.chain] == ["C14", "C15", "n8n", "AI", "DB"]
    assert trace.chain[0].input == {"capability": "reasoning"}
    assert trace.chain[0].output == {"model": "model.reasoning.primary_v1"}
    assert trace.chain[2].retry_count == 1
    assert trace.total_latency_ms == 80
    assert detect_missing_trace_steps(trace) == ()


def test_c17c_detects_missing_terminal_and_dependency_steps() -> None:
    base = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    aggregator = TraceAggregator(required_actions=("workflow_completion",))
    aggregator.collect(
        _event(
            step_id="step.pending",
            step_index=0,
            lifecycle="start",
            module="n8n",
            action="node_execution_start",
            status="pending",
            timestamp=base,
            input_snapshot={"node": "Pending"},
            dependency_step_id="missing.parent",
        )
    )

    trace = aggregator.merge()
    issues = aggregator.detect_missing_steps(trace)

    assert trace.final_status == "partial"
    assert {issue.issue_type for issue in issues} == {
        "missing_terminal_event",
        "missing_dependency_step",
        "missing_required_action",
    }


def test_c17c_storage_outputs_json_jsonl_and_db_ready_records() -> None:
    trace = aggregate_execution_trace(
        [
            _event(
                step_id="step.db.write",
                step_index=0,
                lifecycle="complete",
                module="DB",
                action="write_success_failure",
                status="success",
                timestamp=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
                input_snapshot={"object_key": "trace/demo.json"},
                output_snapshot={"stored": True},
                latency_ms=3,
            )
        ]
    )

    debug_json = execution_trace_to_json(trace)
    jsonl = execution_trace_to_jsonl(trace)
    step_jsonl = trace_step_event_to_jsonl(
        _event(
            step_id="step.db.write",
            step_index=0,
            lifecycle="complete",
            module="DB",
            action="write_success_failure",
            status="success",
            timestamp=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        )
    )
    db_record = execution_trace_to_db_record(trace)

    assert json.loads(debug_json)["trace_id"] == "trace-c17c-001"
    assert json.loads(jsonl)["final_status"] == "success"
    assert json.loads(step_jsonl)["step_id"] == "step.db.write"
    assert db_record["trace_id"] == "trace-c17c-001"
    assert db_record["modules"] == ["DB"]
    assert db_record["step_count"] == 1
    assert db_record["indexable_fields"] == [
        "trace_id",
        "context_id",
        "root_event_id",
        "module",
        "final_status",
    ]


def test_c17c_migrates_c17b_log_entry_to_trace_step_event() -> None:
    log_entry = LogEntry(
        event_id="evt-c17b-n8n-end",
        timestamp=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        context_id="ctx-c17b-root",
        module="C15",
        event_type="n8n.node.execution.end",
        action="n8n node execution end",
        source="n8n",
        entity=LogEntity(workflow_id="workflow.demo", request_id="ctx-c17b-root"),
        status="success",
        latency_ms=25,
        request={"node": "Classify"},
        response={"items": 1},
        metadata=LogMetadata(retry_count=2),
        tags=("c17b", "module:execution"),
    )

    step_event = trace_step_event_from_log_entry(log_entry)
    trace = aggregate_execution_trace([step_event])

    assert step_event.trace_id == "ctx-c17b-root"
    assert step_event.context_id == "ctx-c17b-root"
    assert step_event.root_event_id == "evt-c17b-n8n-end"
    assert step_event.module == "n8n"
    assert step_event.action == "node_execution_end"
    assert step_event.lifecycle == "complete"
    assert step_event.input == {"node": "Classify"}
    assert step_event.output == {"items": 1}
    assert step_event.retry_count == 2
    assert trace.final_status == "success"


def test_c17c_storage_rejects_non_trace_objects() -> None:
    with pytest.raises(TypeError, match="ExecutionTrace"):
        execution_trace_to_json({"trace_id": "raw"})  # type: ignore[arg-type]
