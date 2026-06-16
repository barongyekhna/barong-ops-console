from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Protocol
from uuid import uuid4

from ..schemas.execution_replay import (
    REPLAY_BREAKPOINTS,
    DebugStepExecutionModel,
    DivergenceDetectionLogic,
    DryRunSimulationModel,
    ExecutionReplay,
    ExecutionReplayCompletionStatus,
    ExecutionReplaySchemaDefinition,
    FullReplayExecutionFlow,
    ReplayAPIDesign,
    ReplayBreakpointKind,
    ReplayDebugFrame,
    ReplayDebugSession,
    ReplayEngineDesign,
    ReplayExecutionOutcome,
    ReplayMode,
    ReplayResult,
    ReplaySnapshotBundle,
    ReplayStep,
    ReplayStepStatus,
    ReplayStorageIntegrationDesign,
)
from ..schemas.execution_trace import (
    EXECUTION_TRACE_FIELDS,
    ExecutionTrace,
    ExecutionTraceStep,
)
from ..schemas.storage_layer import StorageRecordEnvelope
from ..schemas.structured_logs import LOG_ENTRY_FIELDS, LogEntry
from .event_collector import normalize_context_id
from .storage_layer import StorageAdapter


OUTPUT_MATCH_KEYS: tuple[str, ...] = (
    "step_id",
    "stepId",
    "execution_step_id",
    "executionStepId",
)


class StepReplayExecutor(Protocol):
    def execute_step(
        self,
        step: ExecutionTraceStep,
        *,
        context_id: str,
        mode: ReplayMode,
        snapshot: ReplaySnapshotBundle,
    ) -> ReplayExecutionOutcome:
        ...


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _payload(record: StorageRecordEnvelope) -> Mapping[str, Any]:
    if isinstance(record.payload, Mapping):
        return record.payload
    return {}


def _dict_copy(value: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(value))


def _json_fingerprint(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=True, sort_keys=True)


def _decode_trace_record(record: StorageRecordEnvelope) -> ExecutionTrace:
    payload = _payload(record)
    return ExecutionTrace.model_validate(
        {field: payload[field] for field in EXECUTION_TRACE_FIELDS if field in payload}
    )


def _decode_log_record(record: StorageRecordEnvelope) -> LogEntry:
    payload = _payload(record)
    return LogEntry.model_validate(
        {field: payload[field] for field in LOG_ENTRY_FIELDS if field in payload}
    )


def _status_from_trace_step(step: ExecutionTraceStep) -> ReplayStepStatus:
    if step.status == "failed":
        return "failed"
    return "success"


def _matches_log_step(log: LogEntry, step: ExecutionTraceStep) -> bool:
    for source in (log.request, log.response):
        for key in OUTPUT_MATCH_KEYS:
            if _string_value(source.get(key)) == step.step_id:
                return True
    if log.action == step.action or log.event_type == step.action:
        return True
    normalized_action = log.action.lower().replace(" ", "_").replace("-", "_")
    return normalized_action == step.action.lower()


def _breakpoint_for_step(
    step: ExecutionTraceStep,
) -> ReplayBreakpointKind | None:
    action = step.action.lower()
    if step.module == "C14" and "capability" in action:
        return "C14 capability selection"
    if step.module == "C15" and ("workflow" in action or "trigger" in action):
        return "C15 workflow execution"
    if step.module == "AI":
        return "AI call"
    if step.module == "DB":
        return "DB write"
    return None


def _latency_diverged(
    original_latency_ms: float,
    replay_latency_ms: float,
    *,
    tolerance_ms: float,
    tolerance_ratio: float,
) -> bool:
    delta = abs(original_latency_ms - replay_latency_ms)
    allowed = max(tolerance_ms, original_latency_ms * tolerance_ratio)
    return delta > allowed


class ReplayStorageReader:
    def __init__(self, storage: StorageAdapter) -> None:
        self.storage = storage

    def load_by_trace_id(self, trace_id: str) -> ReplaySnapshotBundle:
        normalized = normalize_context_id(trace_id)
        result = self.storage.query_by_trace_id(normalized)
        return self._bundle_from_records(
            result.records,
            expected_trace_id=normalized,
            expected_context_id=None,
        )

    def load_by_context_id(self, context_id: str) -> ReplaySnapshotBundle:
        normalized = normalize_context_id(context_id)
        result = self.storage.query_by_context_id(normalized)
        return self._bundle_from_records(
            result.records,
            expected_trace_id=None,
            expected_context_id=normalized,
        )

    def _bundle_from_records(
        self,
        records: Sequence[StorageRecordEnvelope],
        *,
        expected_trace_id: str | None,
        expected_context_id: str | None,
    ) -> ReplaySnapshotBundle:
        trace_candidates: list[ExecutionTrace] = []
        logs: list[LogEntry] = []

        for record in records:
            if record.entity_type == "ExecutionTrace":
                trace = _decode_trace_record(record)
                if expected_trace_id is not None and trace.trace_id != expected_trace_id:
                    continue
                if (
                    expected_context_id is not None
                    and trace.context_id != expected_context_id
                ):
                    continue
                trace_candidates.append(trace)
            elif record.entity_type == "LogEntry":
                logs.append(_decode_log_record(record))

        if not trace_candidates:
            lookup = expected_trace_id or expected_context_id or "unknown"
            raise ValueError(f"C17F replay requires a C17C ExecutionTrace for {lookup}.")

        return ReplaySnapshotBundle(
            original_trace=trace_candidates[0],
            storage_records=tuple(records),
            log_snapshots=tuple(logs),
        )


class SnapshotStepExecutor:
    """Controlled executor that replays from captured snapshots only."""

    def execute_step(
        self,
        step: ExecutionTraceStep,
        *,
        context_id: str,
        mode: ReplayMode,
        snapshot: ReplaySnapshotBundle,
    ) -> ReplayExecutionOutcome:
        return ReplayExecutionOutcome(
            replay_output=_dict_copy(
                stored_output_for_step(snapshot, step) or step.output
            ),
            status=_status_from_trace_step(step),
            latency_ms=step.latency_ms,
        )


class ReplayAnalyzer:
    def __init__(
        self,
        *,
        latency_tolerance_ms: float = 50,
        latency_tolerance_ratio: float = 0.2,
    ) -> None:
        self.latency_tolerance_ms = latency_tolerance_ms
        self.latency_tolerance_ratio = latency_tolerance_ratio

    def compare(
        self,
        original_trace: ExecutionTrace,
        replay: ExecutionReplay,
    ) -> ReplayResult:
        divergence_points: list[str] = []
        replay_failed = any(step.status == "failed" for step in replay.steps)

        if replay.original_trace_id != original_trace.trace_id:
            divergence_points.append(
                "trace_id_mismatch: "
                f"original={original_trace.trace_id} replay={replay.original_trace_id}"
            )
        if replay.context_id != original_trace.context_id:
            divergence_points.append(
                "context_id_mismatch: "
                f"original={original_trace.context_id} replay={replay.context_id}"
            )

        original_order = tuple(step.step_id for step in original_trace.chain)
        replay_order = tuple(step.step_id for step in replay.steps)
        if original_order != replay_order:
            divergence_points.append(
                "step_order_mismatch: "
                f"original={list(original_order)} replay={list(replay_order)}"
            )

        replay_by_step_id = {step.step_id: step for step in replay.steps}
        original_by_step_id = {step.step_id: step for step in original_trace.chain}

        for original_step in original_trace.chain:
            replay_step = replay_by_step_id.get(original_step.step_id)
            if replay_step is None:
                divergence_points.append(f"missing_step:{original_step.step_id}")
                continue

            if (
                _json_fingerprint(original_step.output)
                != _json_fingerprint(replay_step.replay_output)
            ):
                divergence_points.append(f"{original_step.step_id}:output_mismatch")

            if _latency_diverged(
                original_step.latency_ms,
                replay_step.simulated_latency_ms,
                tolerance_ms=self.latency_tolerance_ms,
                tolerance_ratio=self.latency_tolerance_ratio,
            ):
                divergence_points.append(
                    f"{original_step.step_id}:latency_divergence:"
                    f"original={original_step.latency_ms}:"
                    f"replay={replay_step.simulated_latency_ms}"
                )

            if (
                replay.mode != "dry_run"
                and replay_step.status != "skipped"
                and _status_from_trace_step(original_step) != replay_step.status
            ):
                divergence_points.append(f"{original_step.step_id}:status_mismatch")

        for replay_step in replay.steps:
            if replay_step.step_id not in original_by_step_id:
                divergence_points.append(f"unexpected_step:{replay_step.step_id}")

        return ReplayResult(
            success=not replay_failed
            and not any(point.startswith("missing_step:") for point in divergence_points),
            divergence_detected=bool(divergence_points),
            divergence_points=tuple(divergence_points),
        )


def stored_output_for_step(
    snapshot: ReplaySnapshotBundle,
    step: ExecutionTraceStep,
) -> dict[str, Any] | None:
    for record in snapshot.storage_records:
        if record.entity_type != "ExecutionTrace":
            continue
        trace = _decode_trace_record(record)
        for stored_step in trace.chain:
            if stored_step.step_id == step.step_id and stored_step.output:
                return _dict_copy(stored_step.output)

    for log in snapshot.log_snapshots:
        if _matches_log_step(log, step) and log.response:
            return _dict_copy(log.response)

    if step.output:
        return _dict_copy(step.output)
    return None


def simulate_dry_run_output(
    snapshot: ReplaySnapshotBundle,
    step: ExecutionTraceStep,
) -> dict[str, Any]:
    stored_output = stored_output_for_step(snapshot, step)
    if stored_output is not None:
        return stored_output
    return {
        "simulated": True,
        "source": "c17f_dry_run",
        "step_id": step.step_id,
        "original_action": step.action,
    }


class ExecutionReplayEngine:
    def __init__(
        self,
        storage: StorageAdapter,
        *,
        executor: StepReplayExecutor | None = None,
        analyzer: ReplayAnalyzer | None = None,
    ) -> None:
        self.reader = ReplayStorageReader(storage)
        self.executor = executor or SnapshotStepExecutor()
        self.analyzer = analyzer or ReplayAnalyzer()
        self._active_snapshot: ReplaySnapshotBundle | None = None
        self._active_mode: ReplayMode = "dry_run"

    def replay_by_trace_id(
        self,
        trace_id: str,
        mode: ReplayMode = "dry_run",
        *,
        context_id: str | None = None,
        breakpoints: Sequence[ReplayBreakpointKind] | None = None,
    ) -> ExecutionReplay:
        snapshot = self.reader.load_by_trace_id(trace_id)
        self._validate_context(snapshot.original_trace, context_id)
        return self._replay_snapshot(snapshot, mode=mode, breakpoints=breakpoints)

    def replay_by_context_id(
        self,
        context_id: str,
        mode: ReplayMode = "dry_run",
        *,
        breakpoints: Sequence[ReplayBreakpointKind] | None = None,
    ) -> ExecutionReplay:
        snapshot = self.reader.load_by_context_id(context_id)
        self._validate_context(snapshot.original_trace, context_id)
        return self._replay_snapshot(snapshot, mode=mode, breakpoints=breakpoints)

    def replay_step(
        self,
        step_id: str,
        mode: ReplayMode | None = None,
    ) -> ReplayStep:
        if self._active_snapshot is None:
            raise ValueError("replay_step requires replay_by_trace_id first.")
        trace = self._active_snapshot.original_trace
        for step in trace.chain:
            if step.step_id == step_id:
                return self._replay_step(
                    step,
                    snapshot=self._active_snapshot,
                    mode=mode or self._active_mode,
                )
        raise ValueError(f"Unknown replay step_id: {step_id}.")

    def debug_trace(
        self,
        trace_id: str,
        *,
        breakpoints: Sequence[ReplayBreakpointKind] | None = None,
    ) -> ReplayDebugSession:
        active_breakpoints = tuple(breakpoints or REPLAY_BREAKPOINTS)
        replay = self.replay_by_trace_id(
            trace_id,
            mode="debug",
            breakpoints=active_breakpoints,
        )
        return self._debug_session(replay, active_breakpoints)

    def _replay_snapshot(
        self,
        snapshot: ReplaySnapshotBundle,
        *,
        mode: ReplayMode,
        breakpoints: Sequence[ReplayBreakpointKind] | None,
    ) -> ExecutionReplay:
        steps = tuple(
            self._replay_step(step, snapshot=snapshot, mode=mode)
            for step in snapshot.original_trace.chain
        )
        initial = ExecutionReplay(
            replay_id=f"replay-{uuid4()}",
            original_trace_id=snapshot.original_trace.trace_id,
            context_id=snapshot.original_trace.context_id,
            mode=mode,
            steps=steps,
            replay_result=ReplayResult(
                success=True,
                divergence_detected=False,
                divergence_points=(),
            ),
        )
        replay = initial.model_copy(
            update={
                "replay_result": self.analyzer.compare(snapshot.original_trace, initial)
            }
        )
        self._active_snapshot = snapshot
        self._active_mode = mode
        return replay

    def _replay_step(
        self,
        step: ExecutionTraceStep,
        *,
        snapshot: ReplaySnapshotBundle,
        mode: ReplayMode,
    ) -> ReplayStep:
        if mode == "dry_run":
            return ReplayStep(
                step_id=step.step_id,
                step_index=step.step_index,
                original_action=step.action,
                replay_input=_dict_copy(step.input),
                replay_output=simulate_dry_run_output(snapshot, step),
                status="skipped",
                simulated_latency_ms=step.latency_ms,
                is_replayed=True,
            )

        outcome = self.executor.execute_step(
            step,
            context_id=snapshot.original_trace.context_id,
            mode=mode,
            snapshot=snapshot,
        )
        return ReplayStep(
            step_id=step.step_id,
            step_index=step.step_index,
            original_action=step.action,
            replay_input=_dict_copy(step.input),
            replay_output=_dict_copy(outcome.replay_output),
            status=outcome.status,
            simulated_latency_ms=outcome.latency_ms,
            is_replayed=True,
        )

    def _debug_session(
        self,
        replay: ExecutionReplay,
        breakpoints: Sequence[ReplayBreakpointKind],
    ) -> ReplayDebugSession:
        active_breakpoints = tuple(breakpoints)
        frames = []
        for replay_step in replay.steps:
            trace_step = self._trace_step_for_replay_step(replay_step)
            breakpoint = _breakpoint_for_step(trace_step) if trace_step else None
            paused = breakpoint in active_breakpoints if breakpoint is not None else False
            frames.append(
                ReplayDebugFrame(
                    step_id=replay_step.step_id,
                    step_index=replay_step.step_index,
                    breakpoint=breakpoint,
                    paused=paused,
                    inspect_input=_dict_copy(replay_step.replay_input),
                    inspect_output=_dict_copy(replay_step.replay_output),
                )
            )
        return ReplayDebugSession(
            trace_id=replay.original_trace_id,
            context_id=replay.context_id,
            breakpoints=active_breakpoints,
            current_step_index=0,
            frames=tuple(frames),
            replay=replay,
        )

    def _trace_step_for_replay_step(
        self,
        replay_step: ReplayStep,
    ) -> ExecutionTraceStep | None:
        if self._active_snapshot is None:
            return None
        for step in self._active_snapshot.original_trace.chain:
            if step.step_id == replay_step.step_id:
                return step
        return None

    def _validate_context(
        self,
        trace: ExecutionTrace,
        context_id: str | None,
    ) -> None:
        if context_id is not None and trace.context_id != normalize_context_id(context_id):
            raise ValueError(
                "C17F full replay must enforce the original context_id: "
                f"{trace.context_id}."
            )


def replay_by_trace_id(
    storage: StorageAdapter,
    trace_id: str,
    mode: ReplayMode = "dry_run",
) -> ExecutionReplay:
    return ExecutionReplayEngine(storage).replay_by_trace_id(trace_id, mode)


def replay_by_context_id(
    storage: StorageAdapter,
    context_id: str,
    mode: ReplayMode = "dry_run",
) -> ExecutionReplay:
    return ExecutionReplayEngine(storage).replay_by_context_id(context_id, mode)


def replay_step(
    storage: StorageAdapter,
    trace_id: str,
    step_id: str,
    mode: ReplayMode = "dry_run",
) -> ReplayStep:
    engine = ExecutionReplayEngine(storage)
    engine.replay_by_trace_id(trace_id, mode)
    return engine.replay_step(step_id, mode)


def debug_trace(storage: StorageAdapter, trace_id: str) -> ReplayDebugSession:
    return ExecutionReplayEngine(storage).debug_trace(trace_id)


def get_execution_replay_schema_definition() -> ExecutionReplaySchemaDefinition:
    return ExecutionReplaySchemaDefinition()


def get_replay_engine_design() -> ReplayEngineDesign:
    return ReplayEngineDesign()


def get_dry_run_simulation_model() -> DryRunSimulationModel:
    return DryRunSimulationModel()


def get_debug_step_execution_model() -> DebugStepExecutionModel:
    return DebugStepExecutionModel()


def get_full_replay_execution_flow() -> FullReplayExecutionFlow:
    return FullReplayExecutionFlow()


def get_divergence_detection_logic() -> DivergenceDetectionLogic:
    return DivergenceDetectionLogic()


def get_replay_storage_integration_design() -> ReplayStorageIntegrationDesign:
    return ReplayStorageIntegrationDesign()


def get_replay_api_design() -> ReplayAPIDesign:
    return ReplayAPIDesign()


def get_execution_replay_completion_status() -> ExecutionReplayCompletionStatus:
    return ExecutionReplayCompletionStatus()
