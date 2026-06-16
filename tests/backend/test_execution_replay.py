from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.schemas.execution_replay import ReplayExecutionOutcome
from backend.app.schemas.execution_trace import ExecutionTrace, ExecutionTraceStep
from backend.app.schemas.structured_logs import LogEntity, LogEntry, LogMetadata
from backend.app.services.execution_replay import (
    ExecutionReplayEngine,
    ReplayAnalyzer,
    debug_trace,
    get_debug_step_execution_model,
    get_divergence_detection_logic,
    get_dry_run_simulation_model,
    get_execution_replay_completion_status,
    get_execution_replay_schema_definition,
    get_full_replay_execution_flow,
    get_replay_api_design,
    get_replay_engine_design,
    get_replay_storage_integration_design,
    replay_by_context_id,
    replay_by_trace_id,
    replay_step,
)
from backend.app.services.storage_layer import InMemoryStorageAdapter


BASE_TIME = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


def _trace() -> ExecutionTrace:
    steps = (
        ExecutionTraceStep(
            step_id="step.c14.capability",
            step_index=0,
            module="C14",
            action="capability_selection_result",
            input={"capability": "reasoning"},
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
            input={"workflow_id": "workflow.demo"},
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
            input={"provider": "GPT", "prompt": "classify"},
            output={"tokens": 42, "label": "ok"},
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
            input={"table": "future_execution_replays"},
            output={"stored": True},
            status="success",
            latency_ms=15,
            timestamp=BASE_TIME + timedelta(milliseconds=60),
            dependency_step_id="step.ai.call",
        ),
    )
    return ExecutionTrace(
        trace_id="trace-c17f-001",
        context_id="ctx-c17f-001",
        root_event_id="evt-root-c17f",
        chain=steps,
        final_status="success",
        total_latency_ms=80,
    )


def _log_snapshot() -> LogEntry:
    return LogEntry(
        event_id="evt-c17f-ai-response",
        timestamp=BASE_TIME,
        context_id="ctx-c17f-001",
        module="C14",
        event_type="ai.response.receive",
        action="response_receive",
        source="ai",
        entity=LogEntity(
            user_id="user-42",
            product_key="product.demo",
            workflow_id="workflow.demo",
            request_id="ctx-c17f-001",
        ),
        status="success",
        latency_ms=25,
        request={"trace_id": "trace-c17f-001", "step_id": "step.ai.call"},
        response={"tokens": 42, "label": "ok"},
        metadata=LogMetadata(retry_count=0),
        tags=("c17b", "module:capability"),
    )


def _adapter() -> InMemoryStorageAdapter:
    adapter = InMemoryStorageAdapter(now=BASE_TIME)
    adapter.write_trace(_trace())
    adapter.write_log(_log_snapshot())
    return adapter


class CountingExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_step(self, step, *, context_id, mode, snapshot):  # type: ignore[no-untyped-def]
        self.calls.append(step.step_id)
        output = dict(step.output)
        if step.step_id == "step.ai.call":
            output = {"tokens": 99, "label": "changed"}
        return ReplayExecutionOutcome(
            replay_output=output,
            status="success",
            latency_ms=step.latency_ms + 100,
        )


def test_c17f_design_models_cover_required_outputs() -> None:
    schema = get_execution_replay_schema_definition()
    engine = get_replay_engine_design()
    dry_run = get_dry_run_simulation_model()
    debug = get_debug_step_execution_model()
    full = get_full_replay_execution_flow()
    divergence = get_divergence_detection_logic()
    integration = get_replay_storage_integration_design()
    api = get_replay_api_design()
    completion = get_execution_replay_completion_status()

    assert schema.canonical_model == "ExecutionReplay"
    assert schema.fields == (
        "replay_id",
        "original_trace_id",
        "context_id",
        "mode",
        "steps",
        "replay_result",
    )
    assert schema.step_fields == (
        "step_id",
        "step_index",
        "original_action",
        "replay_input",
        "replay_output",
        "status",
        "simulated_latency_ms",
        "is_replayed",
    )
    assert schema.mode_values == ("dry_run", "debug", "full")
    assert engine.dry_run_short_circuits_real_execution is True
    assert dry_run.calls_real_ai is False
    assert dry_run.triggers_n8n_webhook is False
    assert dry_run.writes_database is False
    assert dry_run.modifies_filesystem is False
    assert debug.breakpoints == (
        "C14 capability selection",
        "C15 workflow execution",
        "AI call",
        "DB write",
    )
    assert full.same_context_id_enforced is True
    assert divergence.comparisons == (
        "original output vs replay output",
        "latency differences",
        "step order mismatch",
        "missing steps",
    )
    assert integration.reads == (
        "C17C ExecutionTrace",
        "C17D Storage Layer",
        "C17B LogEntry snapshots",
    )
    assert {
        "replay_by_trace_id(trace_id, mode)",
        "replay_by_context_id(context_id)",
        "replay_step(step_id)",
        "debug_trace(trace_id)",
    }.issubset(set(api.method_names))
    assert completion.completion_status == "complete"
    assert completion.c17b_modified is False
    assert completion.c17c_modified is False
    assert completion.c17d_modified is False
    assert completion.c17e_modified is False


def test_c17f_dry_run_reuses_stored_outputs_without_calling_executor() -> None:
    executor = CountingExecutor()
    engine = ExecutionReplayEngine(_adapter(), executor=executor)

    replay = engine.replay_by_trace_id("trace-c17f-001", "dry_run")
    ai_step = engine.replay_step("step.ai.call")

    assert executor.calls == []
    assert replay.mode == "dry_run"
    assert replay.original_trace_id == "trace-c17f-001"
    assert replay.context_id == "ctx-c17f-001"
    assert len(replay.steps) == 5
    assert all(step.status == "skipped" for step in replay.steps)
    assert all(step.is_replayed is True for step in replay.steps)
    assert replay.steps[3].replay_output == {"tokens": 42, "label": "ok"}
    assert ai_step.replay_output == {"tokens": 42, "label": "ok"}
    assert replay.replay_result.success is True
    assert replay.replay_result.divergence_detected is False


def test_c17f_debug_trace_exposes_pause_frames_and_snapshots() -> None:
    session = ExecutionReplayEngine(_adapter()).debug_trace("trace-c17f-001")

    assert session.mode == "debug"
    assert session.trace_id == "trace-c17f-001"
    assert session.replay.mode == "debug"
    paused = {frame.breakpoint for frame in session.frames if frame.paused}
    assert paused == {
        "C14 capability selection",
        "C15 workflow execution",
        "AI call",
        "DB write",
    }
    ai_frame = next(frame for frame in session.frames if frame.step_id == "step.ai.call")
    assert ai_frame.inspect_input == {"provider": "GPT", "prompt": "classify"}
    assert ai_frame.inspect_output == {"tokens": 42, "label": "ok"}


def test_c17f_full_replay_detects_output_and_latency_divergence() -> None:
    executor = CountingExecutor()
    engine = ExecutionReplayEngine(_adapter(), executor=executor)

    replay = engine.replay_by_trace_id(
        "trace-c17f-001",
        "full",
        context_id="ctx-c17f-001",
    )

    assert executor.calls == [
        "step.c14.capability",
        "step.c15.workflow",
        "step.n8n.node",
        "step.ai.call",
        "step.db.write",
    ]
    assert replay.mode == "full"
    assert replay.replay_result.success is True
    assert replay.replay_result.divergence_detected is True
    assert "step.ai.call:output_mismatch" in replay.replay_result.divergence_points
    assert any(
        point.startswith("step.ai.call:latency_divergence")
        for point in replay.replay_result.divergence_points
    )


def test_c17f_full_replay_enforces_original_context_id() -> None:
    engine = ExecutionReplayEngine(_adapter())

    with pytest.raises(ValueError, match="original context_id"):
        engine.replay_by_trace_id(
            "trace-c17f-001",
            "full",
            context_id="ctx-c17f-wrong",
        )


def test_c17f_function_api_reads_by_trace_context_step_and_debug() -> None:
    adapter = _adapter()

    by_trace = replay_by_trace_id(adapter, "trace-c17f-001", "dry_run")
    by_context = replay_by_context_id(adapter, "ctx-c17f-001")
    single_step = replay_step(adapter, "trace-c17f-001", "step.db.write")
    debug = debug_trace(adapter, "trace-c17f-001")

    assert by_trace.original_trace_id == "trace-c17f-001"
    assert by_context.context_id == "ctx-c17f-001"
    assert single_step.step_id == "step.db.write"
    assert single_step.replay_output == {"stored": True}
    assert debug.frames[0].paused is True


def test_c17f_replay_analyzer_detects_missing_steps() -> None:
    trace = _trace()
    replay = ExecutionReplayEngine(_adapter()).replay_by_trace_id(
        "trace-c17f-001",
        "dry_run",
    )
    partial = replay.model_copy(update={"steps": replay.steps[:-1]})

    result = ReplayAnalyzer().compare(trace, partial)

    assert result.success is False
    assert result.divergence_detected is True
    assert "missing_step:step.db.write" in result.divergence_points
    assert any(
        point.startswith("step_order_mismatch")
        for point in result.divergence_points
    )
