from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..schemas.execution_trace import (
    C17BToC17CMigrationPlan,
    CrossSystemTraceMapping,
    CrossSystemTraceStage,
    ExecutionFlowDiagram,
    ExecutionTrace,
    ExecutionTraceCompletionStatus,
    ExecutionTraceSchemaDefinition,
    ExecutionTraceStep,
    TRACE_INDEXABLE_FIELDS,
    TRACE_MODULES,
    TraceAggregatorDesign,
    TraceCompletenessIssue,
    TraceFinalStatus,
    TraceHookInjectionCatalog,
    TraceHookInjectionPoint,
    TraceLifecycleState,
    TraceModule,
    TraceStepEvent,
    TraceStepLifecycleDefinition,
    TraceStepStatus,
    TraceStorageFormatDesign,
)
from ..schemas.structured_logs import LogEntry
from .event_collector import normalize_context_id, sanitize_event_payload


TRACE_MODULE_SET: frozenset[str] = frozenset(TRACE_MODULES)
CANONICAL_ACTIONS: frozenset[str] = frozenset(
    (
        "frontend_request",
        "backend_api_entry",
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
    )
)
STATUS_ALIASES: dict[str, TraceStepStatus] = {
    "success": "success",
    "succeeded": "success",
    "complete": "success",
    "completed": "success",
    "ok": "success",
    "passed": "success",
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
    "errored": "failed",
    "denied": "failed",
    "rejected": "failed",
    "pending": "pending",
    "queued": "pending",
    "running": "pending",
    "in_progress": "pending",
    "processing": "pending",
    "received": "pending",
    "started": "pending",
}
CONTEXT_ALIASES: tuple[str, ...] = (
    "context_id",
    "contextId",
    "correlation_id",
    "correlationId",
    "request_id",
    "requestId",
)
TRACE_ALIASES: tuple[str, ...] = (
    "trace_id",
    "traceId",
    "trace",
)
ROOT_EVENT_ALIASES: tuple[str, ...] = (
    "root_event_id",
    "rootEventId",
    "root_id",
    "rootId",
)
STEP_ALIASES: tuple[str, ...] = (
    "step_id",
    "stepId",
    "execution_step_id",
    "executionStepId",
)
DEPENDENCY_ALIASES: tuple[str, ...] = (
    "dependency_step_id",
    "dependencyStepId",
    "depends_on_step_id",
    "dependsOnStepId",
    "parent_step_id",
    "parentStepId",
)


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _normalized_text(*values: Any) -> str:
    return " ".join(
        text.lower().replace("-", "_").replace(".", "_")
        for value in values
        if (text := _string_value(value)) is not None
    )


def _first_present(
    sources: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> Any:
    for source in sources:
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
    return None


def _timestamp_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(UTC)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return datetime.now(UTC)


def _nonnegative_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _nonnegative_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _snapshot_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    sanitized = sanitize_event_payload(value)
    if isinstance(sanitized, Mapping):
        return dict(sanitized)
    return {"value": sanitized}


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return sanitize_event_payload(dict(value))
    return {}


def _snapshot_from(
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> dict[str, Any]:
    for key in keys:
        if key in raw and raw[key] is not None:
            return _snapshot_value(raw[key])
        if key in payload and payload[key] is not None:
            return _snapshot_value(payload[key])
    return {}


def _error_value(
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, Any] | None:
    candidate = _first_present(
        (raw, payload, output),
        ("error", "errors", "exception", "failure", "reason"),
    )
    if candidate is None:
        return None
    sanitized = sanitize_event_payload(candidate)
    if isinstance(sanitized, Mapping):
        return dict(sanitized)
    return {"message": str(sanitized)}


def _normalize_status(
    *,
    raw_status: Any,
    payload: Mapping[str, Any],
    output: Mapping[str, Any],
    error: Mapping[str, Any] | None,
) -> TraceStepStatus:
    text = _string_value(raw_status)
    if text is not None:
        normalized = text.lower().replace("-", "_").replace(" ", "_")
        if normalized in STATUS_ALIASES:
            return STATUS_ALIASES[normalized]

    status_code = output.get("status_code", payload.get("status_code"))
    try:
        if status_code is not None and int(status_code) >= 400:
            return "failed"
    except (TypeError, ValueError):
        pass
    if error is not None or any(key in payload for key in ("error", "errors")):
        return "failed"
    return "pending"


def _infer_trace_module(
    *,
    raw_module: Any,
    event_type: str,
    action: str,
    source: str | None,
    payload: Mapping[str, Any],
) -> TraceModule:
    text = _normalized_text(
        event_type,
        action,
        source,
        raw_module,
        payload.get("module"),
        payload.get("storage_provider"),
    )
    source_text = _string_value(source)
    module_text = _string_value(raw_module)

    if source_text == "ai" or any(
        marker in text
        for marker in ("ai_llm", "llm", "prompt_send", "response_receive")
    ):
        return "AI"
    if source_text == "n8n" or "n8n" in text or "node_execution" in text:
        return "n8n"
    if any(
        marker in text
        for marker in (
            "db",
            "database",
            "storage",
            "filestorage",
            "file_write",
            "filebrowser",
            "minio",
            "write_start",
            "write_success_failure",
        )
    ):
        return "DB"
    if module_text in {"C14", "C15"}:
        return module_text  # type: ignore[return-value]
    if "capability" in text or "model_lock" in text:
        return "C14"
    if "workflow" in text or "webhook" in text or "callback" in text:
        return "C15"
    return "system"


def _normalize_action(event_type: str, raw_action: str) -> str:
    action_text = raw_action.strip()
    canonical = action_text.lower().replace("-", "_").replace(".", "_")
    if canonical in CANONICAL_ACTIONS:
        return canonical

    text = _normalized_text(event_type, raw_action)
    if "capability" in text and any(
        marker in text for marker in ("start", "select_start", "selection_start")
    ):
        return "capability_selection_start"
    if "capability" in text and any(
        marker in text for marker in ("result", "selected", "complete")
    ):
        return "capability_selection_result"
    if "workflow" in text and "trigger" in text:
        return "workflow_trigger"
    if "workflow" in text and "step" in text and "start" in text:
        return "workflow_step_start"
    if "workflow" in text and "step" in text and any(
        marker in text for marker in ("complete", "end", "result")
    ):
        return "workflow_step_complete"
    if ("n8n" in text or "node" in text) and any(
        marker in text for marker in ("start", "started")
    ):
        return "node_execution_start"
    if ("n8n" in text or "node" in text) and any(
        marker in text for marker in ("end", "complete", "completed")
    ):
        return "node_execution_end"
    if "workflow" in text and any(
        marker in text for marker in ("completion", "completed", "finished")
    ):
        return "workflow_completion"
    if any(marker in text for marker in ("ai", "llm", "prompt")) and any(
        marker in text for marker in ("request", "send", "sent")
    ):
        return "prompt_send"
    if any(marker in text for marker in ("ai", "llm", "response")) and any(
        marker in text for marker in ("response", "receive", "received")
    ):
        return "response_receive"
    if "write" in text and any(marker in text for marker in ("start", "pending")):
        return "write_start"
    if any(marker in text for marker in ("write", "file", "storage", "db")) and any(
        marker in text for marker in ("success", "failure", "failed", "complete")
    ):
        return "write_success_failure"
    return action_text or event_type


def _infer_lifecycle(
    *,
    raw_lifecycle: Any,
    event_type: str,
    action: str,
    status: TraceStepStatus,
) -> TraceLifecycleState:
    lifecycle = _string_value(raw_lifecycle)
    if lifecycle in {"start", "complete", "record"}:
        return lifecycle  # type: ignore[return-value]

    text = _normalized_text(event_type, action)
    if any(marker in text for marker in ("_start", "request", "prompt_send")):
        return "start"
    if any(
        marker in text
        for marker in (
            "_end",
            "complete",
            "completed",
            "response",
            "result",
            "write_success_failure",
        )
    ):
        return "complete"
    if status == "pending":
        return "start"
    return "record"


def _root_context(raw: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    metadata = _dict_value(raw.get("metadata"))
    candidate = _first_present((raw, payload, metadata), CONTEXT_ALIASES)
    return normalize_context_id(_string_value(candidate))


def _trace_id(
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
    context_id: str,
) -> str:
    metadata = _dict_value(raw.get("metadata"))
    candidate = _first_present((raw, payload, metadata), TRACE_ALIASES)
    return normalize_context_id(_string_value(candidate) or context_id)


def _root_event_id(
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
    trace_id: str,
) -> str:
    metadata = _dict_value(raw.get("metadata"))
    candidate = _first_present((raw, payload, metadata), ROOT_EVENT_ALIASES)
    return (
        _string_value(candidate)
        or _string_value(raw.get("event_id"))
        or _string_value(raw.get("log_id"))
        or trace_id
    )


def _step_id(raw: Mapping[str, Any], payload: Mapping[str, Any], action: str) -> str:
    metadata = _dict_value(raw.get("metadata"))
    candidate = _first_present((raw, payload, metadata), STEP_ALIASES)
    return (
        _string_value(candidate)
        or _string_value(raw.get("event_id"))
        or _string_value(raw.get("log_id"))
        or f"{action}:{uuid4()}"
    )


def _dependency_step_id(
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str | None:
    metadata = _dict_value(raw.get("metadata"))
    candidate = _first_present((raw, payload, metadata), DEPENDENCY_ALIASES)
    return _string_value(candidate)


def _retry_count(raw: Mapping[str, Any], payload: Mapping[str, Any]) -> int:
    metadata = _dict_value(raw.get("metadata"))
    candidate = _first_present(
        (raw, payload, metadata),
        ("retry_count", "retryCount", "attempt", "attempts"),
    )
    return _nonnegative_int(candidate)


def _raw_mapping(raw_event: TraceStepEvent | LogEntry | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw_event, TraceStepEvent):
        return raw_event.model_dump(mode="python")
    if isinstance(raw_event, LogEntry):
        return raw_event.model_dump(mode="python")
    if isinstance(raw_event, Mapping):
        return dict(raw_event)
    raise TypeError("C17C trace input must be TraceStepEvent, LogEntry, or mapping.")


def trace_step_event_from_mapping(raw_event: Mapping[str, Any]) -> TraceStepEvent:
    raw = _raw_mapping(raw_event)
    payload = _dict_value(raw.get("payload"))
    event_type = _string_value(raw.get("event_type")) or "trace.step"
    raw_action = _string_value(raw.get("action")) or event_type
    action = _normalize_action(event_type, raw_action)
    input_snapshot = _snapshot_from(
        raw,
        payload,
        ("input", "input_snapshot", "request", "prompt_input", "payload"),
    )
    output_snapshot = _snapshot_from(
        raw,
        payload,
        ("output", "output_snapshot", "response", "prompt_output", "result"),
    )
    error = _error_value(raw, payload, output_snapshot)
    status = _normalize_status(
        raw_status=raw.get("status"),
        payload=payload,
        output=output_snapshot,
        error=error,
    )
    lifecycle = _infer_lifecycle(
        raw_lifecycle=raw.get("lifecycle"),
        event_type=event_type,
        action=action,
        status=status,
    )
    if not input_snapshot and lifecycle in {"start", "record"}:
        input_snapshot = _snapshot_value(payload)
    if not output_snapshot and lifecycle == "complete":
        output_snapshot = _snapshot_value(payload)

    context_id = _root_context(raw, payload)
    trace_id = _trace_id(raw, payload, context_id)
    root_event_id = _root_event_id(raw, payload, trace_id)
    module = _infer_trace_module(
        raw_module=raw.get("module"),
        event_type=event_type,
        action=action,
        source=_string_value(raw.get("source")),
        payload=payload,
    )

    return TraceStepEvent(
        event_id=_string_value(raw.get("event_id")) or str(uuid4()),
        trace_id=trace_id,
        context_id=context_id,
        root_event_id=root_event_id,
        step_id=_step_id(raw, payload, action),
        step_index=(
            _nonnegative_int(raw["step_index"])
            if raw.get("step_index") is not None
            else None
        ),
        lifecycle=lifecycle,
        module=module,
        action=action,
        input=input_snapshot,
        output=output_snapshot,
        status=status,
        latency_ms=_nonnegative_float(raw.get("latency_ms")),
        timestamp=_timestamp_value(raw.get("timestamp")),
        error=error,
        retry_count=_retry_count(raw, payload),
        dependency_step_id=_dependency_step_id(raw, payload),
    )


def trace_step_event_from_log_entry(log_entry: LogEntry | Mapping[str, Any]) -> TraceStepEvent:
    raw = _raw_mapping(log_entry)
    raw.setdefault("payload", {})
    return trace_step_event_from_mapping(raw)


def normalize_trace_step_event(
    raw_event: TraceStepEvent | LogEntry | Mapping[str, Any],
) -> TraceStepEvent:
    if isinstance(raw_event, TraceStepEvent):
        return raw_event
    if isinstance(raw_event, LogEntry):
        return trace_step_event_from_log_entry(raw_event)
    return trace_step_event_from_mapping(raw_event)


def normalize_trace_step_events(
    raw_events: Sequence[TraceStepEvent | LogEntry | Mapping[str, Any]],
) -> list[TraceStepEvent]:
    return [normalize_trace_step_event(raw_event) for raw_event in raw_events]


def _event_order_key(item: tuple[int, TraceStepEvent]) -> tuple[int, int, datetime, int]:
    arrival_index, event = item
    if event.step_index is None:
        return (1, 10**9, event.timestamp, arrival_index)
    return (0, event.step_index, event.timestamp, arrival_index)


def _first_nonempty_mapping(events: Sequence[TraceStepEvent], field: str) -> dict[str, Any]:
    for event in events:
        value = getattr(event, field)
        if value:
            return dict(value)
    return {}


def _last_nonempty_mapping(events: Sequence[TraceStepEvent], field: str) -> dict[str, Any]:
    for event in reversed(events):
        value = getattr(event, field)
        if value:
            return dict(value)
    return {}


def _merged_status(events: Sequence[TraceStepEvent]) -> TraceStepStatus:
    if any(event.status == "failed" for event in events):
        return "failed"
    terminal = [
        event
        for event in events
        if event.status == "success" or event.lifecycle == "complete"
    ]
    if terminal and terminal[-1].status == "success":
        return "success"
    if all(event.status == "success" for event in events):
        return "success"
    return "pending"


def _merged_latency(events: Sequence[TraceStepEvent]) -> float:
    reported = [event.latency_ms for event in events if event.latency_ms > 0]
    if reported:
        return max(reported)

    starts = [event.timestamp for event in events if event.lifecycle == "start"]
    completes = [
        event.timestamp
        for event in events
        if event.lifecycle == "complete" or event.status in {"success", "failed"}
    ]
    if starts and completes:
        delta = max(completes) - min(starts)
        return max(delta.total_seconds() * 1000, 0)
    return 0


def _merged_error(events: Sequence[TraceStepEvent]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.error is not None:
            return dict(event.error)
    return None


def _merged_dependency(events: Sequence[TraceStepEvent]) -> str | None:
    for event in events:
        if event.dependency_step_id is not None:
            return event.dependency_step_id
    return None


def _detect_missing_steps(
    chain: Sequence[ExecutionTraceStep],
    required_actions: Sequence[str] | None = None,
) -> tuple[TraceCompletenessIssue, ...]:
    issues: list[TraceCompletenessIssue] = []
    step_ids = {step.step_id for step in chain}
    actions = {step.action for step in chain}

    for step in chain:
        if step.status == "pending":
            issues.append(
                TraceCompletenessIssue(
                    issue_type="missing_terminal_event",
                    step_id=step.step_id,
                    action=step.action,
                    module=step.module,
                    reason="Step is still pending and has no terminal output.",
                )
            )
        if (
            step.dependency_step_id is not None
            and step.dependency_step_id not in step_ids
        ):
            issues.append(
                TraceCompletenessIssue(
                    issue_type="missing_dependency_step",
                    step_id=step.step_id,
                    action=step.action,
                    module=step.module,
                    reason=(
                        "dependency_step_id does not reference a step in the "
                        "same ExecutionTrace."
                    ),
                )
            )

    for action in required_actions or ():
        if action not in actions:
            issues.append(
                TraceCompletenessIssue(
                    issue_type="missing_required_action",
                    action=action,
                    reason=f"Required trace action is absent: {action}.",
                )
            )

    return tuple(issues)


def _final_status(
    chain: Sequence[ExecutionTraceStep],
    issues: Sequence[TraceCompletenessIssue],
) -> TraceFinalStatus:
    if any(step.status == "failed" for step in chain):
        return "failed"
    if issues or any(step.status == "pending" for step in chain):
        return "partial"
    return "success"


class TraceAggregator:
    def __init__(
        self,
        *,
        required_actions: Sequence[str] | None = None,
    ) -> None:
        self._events: list[TraceStepEvent] = []
        self._required_actions = tuple(required_actions or ())

    def collect(
        self,
        event: TraceStepEvent | LogEntry | Mapping[str, Any],
    ) -> TraceStepEvent:
        step_event = normalize_trace_step_event(event)
        self._events.append(step_event)
        return step_event

    def collect_many(
        self,
        events: Sequence[TraceStepEvent | LogEntry | Mapping[str, Any]],
    ) -> list[TraceStepEvent]:
        return [self.collect(event) for event in events]

    def clear(self) -> None:
        self._events.clear()

    def merge(
        self,
        events: Sequence[TraceStepEvent | LogEntry | Mapping[str, Any]] | None = None,
    ) -> ExecutionTrace:
        trace_events = (
            normalize_trace_step_events(events)
            if events is not None
            else list(self._events)
        )
        if not trace_events:
            raise ValueError("TraceAggregator requires at least one step event.")

        trace_ids = {event.trace_id for event in trace_events}
        context_ids = {event.context_id for event in trace_events}
        if len(trace_ids) != 1:
            raise ValueError("TraceAggregator can merge only one trace_id at a time.")
        if len(context_ids) != 1:
            raise ValueError("TraceAggregator can merge only one context_id at a time.")

        ordered_events = [
            event for _, event in sorted(enumerate(trace_events), key=_event_order_key)
        ]
        grouped: dict[str, list[TraceStepEvent]] = {}
        step_order: list[str] = []
        for event in ordered_events:
            if event.step_id not in grouped:
                grouped[event.step_id] = []
                step_order.append(event.step_id)
            grouped[event.step_id].append(event)

        steps: list[ExecutionTraceStep] = []
        for step_index, step_id in enumerate(step_order):
            step_events = sorted(
                grouped[step_id],
                key=lambda event: (event.timestamp, event.event_id),
            )
            first_event = step_events[0]
            steps.append(
                ExecutionTraceStep(
                    step_id=step_id,
                    step_index=step_index,
                    module=first_event.module,
                    action=first_event.action,
                    input=_first_nonempty_mapping(step_events, "input"),
                    output=_last_nonempty_mapping(step_events, "output"),
                    status=_merged_status(step_events),
                    latency_ms=_merged_latency(step_events),
                    timestamp=min(event.timestamp for event in step_events),
                    error=_merged_error(step_events),
                    retry_count=max(event.retry_count for event in step_events),
                    dependency_step_id=_merged_dependency(step_events),
                )
            )

        issues = _detect_missing_steps(steps, self._required_actions)
        return ExecutionTrace(
            trace_id=trace_events[0].trace_id,
            context_id=trace_events[0].context_id,
            root_event_id=trace_events[0].root_event_id,
            chain=tuple(steps),
            final_status=_final_status(steps, issues),
            total_latency_ms=sum(step.latency_ms for step in steps),
        )

    def detect_missing_steps(
        self,
        trace: ExecutionTrace,
        *,
        required_actions: Sequence[str] | None = None,
    ) -> tuple[TraceCompletenessIssue, ...]:
        return _detect_missing_steps(
            trace.chain,
            required_actions if required_actions is not None else self._required_actions,
        )


DEFAULT_TRACE_AGGREGATOR = TraceAggregator()


def aggregate_execution_trace(
    events: Sequence[TraceStepEvent | LogEntry | Mapping[str, Any]],
    *,
    required_actions: Sequence[str] | None = None,
) -> ExecutionTrace:
    return TraceAggregator(required_actions=required_actions).merge(events)


def detect_missing_trace_steps(
    trace: ExecutionTrace,
    *,
    required_actions: Sequence[str] | None = None,
) -> tuple[TraceCompletenessIssue, ...]:
    return _detect_missing_steps(trace.chain, required_actions)


def _require_trace(trace: ExecutionTrace) -> ExecutionTrace:
    if not isinstance(trace, ExecutionTrace):
        raise TypeError("C17C storage accepts only ExecutionTrace.")
    return trace


def _require_step_event(event: TraceStepEvent) -> TraceStepEvent:
    if not isinstance(event, TraceStepEvent):
        raise TypeError("C17C step-event storage accepts only TraceStepEvent.")
    return event


def execution_trace_to_json(trace: ExecutionTrace) -> str:
    execution_trace = _require_trace(trace)
    return (
        json.dumps(
            execution_trace.model_dump(mode="json"),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def execution_trace_to_jsonl(trace: ExecutionTrace) -> str:
    execution_trace = _require_trace(trace)
    return (
        json.dumps(
            execution_trace.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def trace_step_event_to_jsonl(event: TraceStepEvent) -> str:
    step_event = _require_step_event(event)
    return (
        json.dumps(
            step_event.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def execution_trace_to_db_record(trace: ExecutionTrace) -> dict[str, Any]:
    execution_trace = _require_trace(trace)
    modules = sorted({step.module for step in execution_trace.chain})
    record = execution_trace.model_dump(mode="json")
    record.update(
        {
            "modules": modules,
            "step_count": len(execution_trace.chain),
            "indexable_fields": list(TRACE_INDEXABLE_FIELDS),
        }
    )
    return record


def trace_step_event_to_db_record(event: TraceStepEvent) -> dict[str, Any]:
    step_event = _require_step_event(event)
    record = step_event.model_dump(mode="json")
    record.update({"indexable_fields": list(TRACE_INDEXABLE_FIELDS)})
    return record


def get_execution_trace_schema_definition() -> ExecutionTraceSchemaDefinition:
    return ExecutionTraceSchemaDefinition()


def get_trace_hook_injection_points() -> TraceHookInjectionCatalog:
    return TraceHookInjectionCatalog(
        hooks=(
            TraceHookInjectionPoint(
                hook_id="c14.capability_selection.start",
                layer="C14",
                module="C14",
                action="capability_selection_start",
                lifecycle="start",
                captures_input_snapshot=True,
                captures_output_snapshot=False,
            ),
            TraceHookInjectionPoint(
                hook_id="c14.capability_selection.result",
                layer="C14",
                module="C14",
                action="capability_selection_result",
                lifecycle="complete",
                captures_input_snapshot=False,
                captures_output_snapshot=True,
            ),
            TraceHookInjectionPoint(
                hook_id="c15.workflow.trigger",
                layer="C15",
                module="C15",
                action="workflow_trigger",
                lifecycle="start",
                captures_input_snapshot=True,
                captures_output_snapshot=False,
            ),
            TraceHookInjectionPoint(
                hook_id="c15.workflow.step.start",
                layer="C15",
                module="C15",
                action="workflow_step_start",
                lifecycle="start",
                captures_input_snapshot=True,
                captures_output_snapshot=False,
            ),
            TraceHookInjectionPoint(
                hook_id="c15.workflow.step.complete",
                layer="C15",
                module="C15",
                action="workflow_step_complete",
                lifecycle="complete",
                captures_input_snapshot=False,
                captures_output_snapshot=True,
            ),
            TraceHookInjectionPoint(
                hook_id="n8n.node.execution.start",
                layer="n8n",
                module="n8n",
                action="node_execution_start",
                lifecycle="start",
                captures_input_snapshot=True,
                captures_output_snapshot=False,
            ),
            TraceHookInjectionPoint(
                hook_id="n8n.node.execution.end",
                layer="n8n",
                module="n8n",
                action="node_execution_end",
                lifecycle="complete",
                captures_input_snapshot=False,
                captures_output_snapshot=True,
            ),
            TraceHookInjectionPoint(
                hook_id="n8n.workflow.completion",
                layer="n8n",
                module="n8n",
                action="workflow_completion",
                lifecycle="complete",
                captures_input_snapshot=False,
                captures_output_snapshot=True,
            ),
            TraceHookInjectionPoint(
                hook_id="ai.prompt.send",
                layer="AI Layer",
                module="AI",
                action="prompt_send",
                lifecycle="start",
                captures_input_snapshot=True,
                captures_output_snapshot=False,
            ),
            TraceHookInjectionPoint(
                hook_id="ai.response.receive",
                layer="AI Layer",
                module="AI",
                action="response_receive",
                lifecycle="complete",
                captures_input_snapshot=False,
                captures_output_snapshot=True,
            ),
            TraceHookInjectionPoint(
                hook_id="db.write.start",
                layer="DB / Storage",
                module="DB",
                action="write_start",
                lifecycle="start",
                captures_input_snapshot=True,
                captures_output_snapshot=False,
            ),
            TraceHookInjectionPoint(
                hook_id="db.write.success_failure",
                layer="DB / Storage",
                module="DB",
                action="write_success_failure",
                lifecycle="complete",
                captures_input_snapshot=False,
                captures_output_snapshot=True,
            ),
        )
    )


def get_cross_system_trace_mapping() -> CrossSystemTraceMapping:
    return CrossSystemTraceMapping(
        stages=(
            CrossSystemTraceStage(
                stage_index=0,
                stage="frontend_request",
                trace_module="system",
                handoff_rule="Create or forward trace_id and context_id.",
            ),
            CrossSystemTraceStage(
                stage_index=1,
                stage="backend API (C13/C14/C16)",
                trace_module="system",
                handoff_rule=(
                    "Backend API keeps request identifiers on request state and "
                    "forwards them to C14/C15 decisions."
                ),
            ),
            CrossSystemTraceStage(
                stage_index=2,
                stage="execution engine (C15)",
                trace_module="C15",
                handoff_rule="C15 carries trace_id/context_id into workflow execution.",
            ),
            CrossSystemTraceStage(
                stage_index=3,
                stage="n8n workflow",
                trace_module="n8n",
                handoff_rule="n8n receives trace_id/context_id in workflow payload.",
            ),
            CrossSystemTraceStage(
                stage_index=4,
                stage="AI call (GPT / DeepSeek / 4sapi)",
                trace_module="AI",
                handoff_rule="AI calls include trace_id/context_id in call metadata.",
            ),
            CrossSystemTraceStage(
                stage_index=5,
                stage="DB / FileStorage",
                trace_module="DB",
                handoff_rule="Storage writes persist trace_id/context_id with output refs.",
            ),
        )
    )


def get_trace_step_lifecycle_definition() -> TraceStepLifecycleDefinition:
    return TraceStepLifecycleDefinition()


def get_trace_aggregator_design() -> TraceAggregatorDesign:
    return TraceAggregatorDesign()


def get_trace_storage_format_design() -> TraceStorageFormatDesign:
    return TraceStorageFormatDesign()


def get_execution_flow_diagram() -> ExecutionFlowDiagram:
    return ExecutionFlowDiagram()


def get_c17b_to_c17c_migration_plan() -> C17BToC17CMigrationPlan:
    return C17BToC17CMigrationPlan()


def get_execution_trace_completion_status() -> ExecutionTraceCompletionStatus:
    return ExecutionTraceCompletionStatus()
