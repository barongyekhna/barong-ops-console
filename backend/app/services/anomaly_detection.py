from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.observability import AnomalyEventRecord, EventStreamRecord
from ..schemas.anomaly_detection import (
    Alert,
    AlertEvidence,
    AlertSystemSchema,
    AnomalyClassificationSystem,
    AnomalyDetectionCompletionStatus,
    AnomalyDetectionEngineDesign,
    AnomalyDetectionResult,
    AnomalyFinding,
    AnomalyScore,
    AnomalyScoringModel,
    AnomalyType,
    BaselineModel,
    BaselineModelDesign,
    BaselineProfile,
    DetectionMode,
    DetectionPipelineFlow,
    IntegrationArchitecture,
    ReplayDiff,
    ScoreBreakdown,
    SeverityRules,
    severity_for_score,
)
from ..schemas.audit_query_engine import QueryResult
from ..schemas.execution_replay import ExecutionReplay
from ..schemas.execution_trace import EXECUTION_TRACE_FIELDS, ExecutionTrace
from ..schemas.storage_layer import EventRaw, StorageRecordEnvelope, StorageTimeRange
from ..schemas.structured_logs import (
    LOG_ENTRY_FIELDS,
    MODULE_TAG_MAP,
    LogEntity,
    LogEntry,
    LogMetadata,
)
from .storage_layer import (
    StorageAdapter,
    ensure_observability_tables,
    storage_record_from_event_stream_row,
)


NormalizedRecord = LogEntry | ExecutionTrace | EventRaw
AnomalyInput = NormalizedRecord | StorageRecordEnvelope | QueryResult

CONTROL_MODULES: set[str] = {"C13", "C14", "C15"}
EXPECTED_CHAIN_ORDER: tuple[str, ...] = ("C14", "C15", "n8n", "AI", "DB")
PROMPT_INJECTION_PATTERNS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous",
    "system prompt",
    "developer message",
    "jailbreak",
    "prompt injection",
    "bypass safety",
    "reveal hidden instructions",
    "exfiltrate",
)
UNAUTHORIZED_PATTERNS: tuple[str, ...] = (
    "unauthorized",
    "denied",
    "forbidden",
    "401",
    "403",
)
RBAC_PATTERNS: tuple[str, ...] = (
    "rbac",
    "permission",
    "privilege",
    "role",
    "bypass",
)
WEBHOOK_REPLAY_PATTERNS: tuple[str, ...] = (
    "replay",
    "nonce",
    "duplicate",
    "idempotency",
    "signature reuse",
)
VALID_LOG_SOURCES: set[str] = {
    "api",
    "n8n",
    "ai",
    "webhook",
    "system",
    "frontend",
    "backend",
}
INVALID_SESSION_PATTERNS: tuple[str, ...] = (
    "invalid session",
    "expired session",
    "invalid token",
    "expired token",
    "session mismatch",
    "token reuse",
)


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


def _record_timestamp(record: NormalizedRecord) -> datetime:
    if isinstance(record, (LogEntry, EventRaw)):
        return record.timestamp
    if record.chain:
        return min(step.timestamp for step in record.chain)
    return datetime.now(UTC)


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


def decode_storage_record(record: StorageRecordEnvelope) -> NormalizedRecord:
    payload = _payload(record)
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
        {field: payload[field] for field in EventRaw.model_fields if field in payload}
    )


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return " ".join(
            f"{key} {_flatten_text(item)}" for key, item in sorted(value.items())
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _contains_any(text: str, patterns: Sequence[str]) -> bool:
    normalized = text.lower()
    return any(pattern in normalized for pattern in patterns)


def _first_present(
    sources: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> str | None:
    for source in sources:
        for key in keys:
            value = _string_value(source.get(key))
            if value is not None:
                return value
    return None


def _log_sources(log: LogEntry) -> tuple[Mapping[str, Any], ...]:
    return (log.request, log.response)


def _event_sources(event: EventRaw) -> tuple[Mapping[str, Any], ...]:
    return (event.payload, event.metadata)


def _trace_sources(trace: ExecutionTrace) -> tuple[Mapping[str, Any], ...]:
    sources: list[Mapping[str, Any]] = []
    for step in trace.chain:
        sources.extend((step.input, step.output))
    return tuple(sources)


def _api_path(record: NormalizedRecord) -> str | None:
    keys = ("api_path", "path", "url_path", "route", "endpoint")
    if isinstance(record, LogEntry):
        return _first_present(_log_sources(record), keys)
    if isinstance(record, EventRaw):
        return _first_present(_event_sources(record), keys)
    return _first_present(_trace_sources(record), keys)


def _user_id(record: NormalizedRecord) -> str | None:
    if isinstance(record, LogEntry):
        return record.entity.user_id or _first_present(_log_sources(record), ("user_id",))
    if isinstance(record, EventRaw):
        return record.user_id or _first_present(_event_sources(record), ("user_id",))
    return _first_present(_trace_sources(record), ("user_id", "userId"))


def _workflow_id(record: NormalizedRecord) -> str | None:
    if isinstance(record, LogEntry):
        return record.entity.workflow_id or _first_present(
            _log_sources(record),
            ("workflow_id", "workflowId"),
        )
    if isinstance(record, EventRaw):
        return record.workflow_id or _first_present(
            _event_sources(record),
            ("workflow_id", "workflowId"),
        )
    return _first_present(_trace_sources(record), ("workflow_id", "workflowId"))


def _context_id(record: NormalizedRecord) -> str:
    return record.context_id


def _trace_id(record: NormalizedRecord) -> str | None:
    if isinstance(record, ExecutionTrace):
        return record.trace_id
    if isinstance(record, EventRaw):
        return record.trace_id
    return _first_present(_log_sources(record), ("trace_id", "traceId"))


def _module(record: NormalizedRecord) -> str:
    if isinstance(record, ExecutionTrace):
        if record.chain:
            return record.chain[0].module
        return "system"
    return record.module


def _module_sequence(trace: ExecutionTrace) -> tuple[str, ...]:
    return tuple(step.module for step in trace.chain)


def _action(record: NormalizedRecord) -> str:
    if isinstance(record, ExecutionTrace):
        return " -> ".join(step.action for step in record.chain) or "execution.trace"
    return record.action


def _status(record: NormalizedRecord) -> str:
    if isinstance(record, ExecutionTrace):
        return record.final_status
    return record.status


def _source(record: NormalizedRecord) -> str:
    if isinstance(record, ExecutionTrace):
        return "trace"
    return record.source


def _event_type(record: NormalizedRecord) -> str:
    if isinstance(record, ExecutionTrace):
        return "execution.trace"
    return record.event_type


def _event_raw_to_log_entry(event: EventRaw) -> LogEntry:
    module = event.module if event.module in MODULE_TAG_MAP else "system"
    source = event.source if event.source in VALID_LOG_SOURCES else "system"
    status = event.status if event.status in {"success", "failed", "pending"} else "pending"
    return LogEntry(
        event_id=event.event_id,
        timestamp=event.timestamp,
        context_id=event.context_id,
        module=module,  # type: ignore[arg-type]
        event_type=event.event_type,
        action=event.action,
        source=source,  # type: ignore[arg-type]
        entity=LogEntity(
            user_id=event.user_id,
            product_key=event.product_key,
            workflow_id=event.workflow_id,
            request_id=event.context_id,
        ),
        status=status,  # type: ignore[arg-type]
        request={
            **event.payload,
            "trace_id": event.trace_id,
        },
        response={},
        metadata=LogMetadata(
            retry_count=_retry_count(event),
        ),
        tags=("c17g:event_raw_projection", f"module:{MODULE_TAG_MAP[module]}"),
    )


def _evidence_for(record: NormalizedRecord) -> AlertEvidence:
    if isinstance(record, EventRaw):
        return _event_raw_to_log_entry(record)
    return record


def _evidence_tuple(records: Sequence[NormalizedRecord]) -> tuple[AlertEvidence, ...]:
    return tuple(_evidence_for(record) for record in records)


def _retry_count(record: NormalizedRecord) -> int:
    if isinstance(record, LogEntry):
        return record.metadata.retry_count
    if isinstance(record, ExecutionTrace):
        return sum(step.retry_count for step in record.chain)
    retry = _first_present(_event_sources(record), ("retry_count", "retryCount"))
    if retry is None:
        return 0
    try:
        return max(int(retry), 0)
    except ValueError:
        return 0


def _record_text(record: NormalizedRecord) -> str:
    if isinstance(record, LogEntry):
        return " ".join(
            (
                record.module,
                record.event_type,
                record.action,
                record.source,
                record.status,
                _flatten_text(record.request),
                _flatten_text(record.response),
                _flatten_text(record.metadata.model_dump(mode="python")),
                _flatten_text(record.tags),
            )
        )
    if isinstance(record, EventRaw):
        return " ".join(
            (
                record.module,
                record.event_type,
                record.action,
                record.source,
                record.status,
                _flatten_text(record.payload),
                _flatten_text(record.metadata),
            )
        )
    return " ".join(
        " ".join(
            (
                trace_step.module,
                trace_step.action,
                trace_step.status,
                _flatten_text(trace_step.input),
                _flatten_text(trace_step.output),
                _flatten_text(trace_step.error),
            )
        )
        for trace_step in record.chain
    )


def _record_status_failed(record: NormalizedRecord) -> bool:
    status = _status(record).lower()
    text = _record_text(record)
    return status == "failed" or _contains_any(text, UNAUTHORIZED_PATTERNS)


def _duration_minutes(records: Sequence[NormalizedRecord]) -> float:
    if not records:
        return 1
    timestamps = [_record_timestamp(record) for record in records]
    duration = (max(timestamps) - min(timestamps)).total_seconds() / 60
    return max(duration, 1)


def _window_records(
    records: Sequence[NormalizedRecord],
    *,
    window: timedelta,
) -> tuple[NormalizedRecord, ...]:
    if not records:
        return ()
    end_at = max(_record_timestamp(record) for record in records)
    start_at = end_at - window
    return tuple(record for record in records if _record_timestamp(record) >= start_at)


def _append_unique(target: list[str], value: str | None) -> None:
    if value is not None and value not in target:
        target.append(value)


def build_baseline_model(records: Iterable[AnomalyInput]) -> BaselineModel:
    normalized = tuple(_normalize_inputs(records))
    window_minutes = _duration_minutes(normalized)
    grouped_users: dict[str, list[NormalizedRecord]] = defaultdict(list)
    grouped_modules: dict[str, list[NormalizedRecord]] = defaultdict(list)
    grouped_workflows: dict[str, list[NormalizedRecord]] = defaultdict(list)
    grouped_contexts: dict[str, list[NormalizedRecord]] = defaultdict(list)

    for record in normalized:
        user_id = _user_id(record)
        workflow_id = _workflow_id(record)
        if user_id is not None:
            grouped_users[user_id].append(record)
        if workflow_id is not None:
            grouped_workflows[workflow_id].append(record)
        grouped_modules[_module(record)].append(record)
        grouped_contexts[_context_id(record)].append(record)

    return BaselineModel(
        users={
            entity_id: _profile_from_records(
                entity_id,
                "user",
                records,
                window_minutes=window_minutes,
            )
            for entity_id, records in grouped_users.items()
        },
        modules={
            entity_id: _profile_from_records(
                entity_id,
                "module",
                records,
                window_minutes=window_minutes,
            )
            for entity_id, records in grouped_modules.items()
        },
        workflows={
            entity_id: _profile_from_records(
                entity_id,
                "workflow",
                records,
                window_minutes=window_minutes,
            )
            for entity_id, records in grouped_workflows.items()
        },
        contexts={
            entity_id: _profile_from_records(
                entity_id,
                "context",
                records,
                window_minutes=window_minutes,
            )
            for entity_id, records in grouped_contexts.items()
        },
    )


def _profile_from_records(
    entity_id: str,
    scope: str,
    records: Sequence[NormalizedRecord],
    *,
    window_minutes: float,
) -> BaselineProfile:
    api_paths: list[str] = []
    workflows: list[str] = []
    modules: list[str] = []
    actions: list[str] = []
    sequences: list[tuple[str, ...]] = []
    retry_count = 0
    security_count = 0

    for record in records:
        _append_unique(api_paths, _api_path(record))
        _append_unique(workflows, _workflow_id(record))
        _append_unique(modules, _module(record))
        _append_unique(actions, _action(record))
        retry_count += _retry_count(record)
        if _looks_security_relevant(record):
            security_count += 1
        if isinstance(record, ExecutionTrace):
            sequence = _module_sequence(record)
            if sequence and sequence not in sequences:
                sequences.append(sequence)

    return BaselineProfile(
        entity_id=entity_id,
        scope=scope,  # type: ignore[arg-type]
        request_rate_per_minute=len(records) / window_minutes,
        context_rate_per_minute=len({_context_id(record) for record in records})
        / window_minutes,
        retry_rate_per_minute=retry_count / window_minutes,
        security_event_rate_per_minute=security_count / window_minutes,
        allowed_api_paths=tuple(api_paths),
        allowed_workflows=tuple(workflows),
        allowed_modules=tuple(modules),
        action_patterns=tuple(actions),
        module_sequence_patterns=tuple(sequences),
        sample_count=len(records),
    )


def _normalize_inputs(records: Iterable[AnomalyInput]) -> Iterable[NormalizedRecord]:
    for record in records:
        if isinstance(record, QueryResult):
            for item in record.data:
                yield item
        elif isinstance(record, StorageRecordEnvelope):
            yield decode_storage_record(record)
        elif isinstance(record, (LogEntry, ExecutionTrace, EventRaw)):
            yield record


def replay_diff_from_replay(replay: ExecutionReplay) -> ReplayDiff:
    divergence_points = replay.replay_result.divergence_points
    if divergence_points:
        summary = (
            "C17F replay divergence detected: "
            + ", ".join(divergence_points[:8])
        )
    else:
        summary = "C17F replay comparison matched the original trace."
    return ReplayDiff(
        replay_id=replay.replay_id,
        original_trace_id=replay.original_trace_id,
        context_id=replay.context_id,
        divergence_detected=replay.replay_result.divergence_detected,
        divergence_points=divergence_points,
        comparison_summary=summary,
    )


def _looks_security_relevant(record: NormalizedRecord) -> bool:
    text = _record_text(record).lower()
    return (
        _contains_any(text, UNAUTHORIZED_PATTERNS)
        or _contains_any(text, RBAC_PATTERNS)
        or _contains_any(text, WEBHOOK_REPLAY_PATTERNS)
        or _contains_any(text, INVALID_SESSION_PATTERNS)
        or _contains_any(text, PROMPT_INJECTION_PATTERNS)
    )


class AnomalyDetectionEngine:
    def __init__(
        self,
        storage: StorageAdapter | None = None,
        *,
        baseline_model: BaselineModel | None = None,
        rolling_window_seconds: int = 60,
        spike_threshold_multiplier: float = 3,
        minimum_rate_events: int = 5,
        minimum_retry_events: int = 3,
    ) -> None:
        self.storage = storage
        self.baseline_model = baseline_model or BaselineModel()
        self.rolling_window = timedelta(seconds=max(rolling_window_seconds, 1))
        self.spike_threshold_multiplier = max(spike_threshold_multiplier, 1)
        self.minimum_rate_events = max(minimum_rate_events, 1)
        self.minimum_retry_events = max(minimum_retry_events, 1)
        self._rolling_records: list[NormalizedRecord] = []

    def fit_baseline(self, records: Iterable[AnomalyInput]) -> BaselineModel:
        self.baseline_model = build_baseline_model(records)
        return self.baseline_model

    def analyze_log_stream(
        self,
        records: Iterable[AnomalyInput],
    ) -> AnomalyDetectionResult:
        current = tuple(_normalize_inputs(records))
        self._rolling_records.extend(current)
        self._prune_rolling_records()

        findings = [
            *self._detect_behavior(current, detection_mode="streaming"),
            *self._detect_security(current, detection_mode="streaming"),
            *self._detect_rate(tuple(self._rolling_records), detection_mode="streaming"),
        ]
        return self._result("streaming", findings, current, ())

    def analyze_trace_patterns(
        self,
        traces: Iterable[ExecutionTrace | StorageRecordEnvelope | QueryResult],
    ) -> AnomalyDetectionResult:
        records = tuple(
            record
            for record in _normalize_inputs(traces)
            if isinstance(record, ExecutionTrace)
        )
        findings = [
            *self._detect_behavior(records, detection_mode="batch"),
            *self._detect_security(records, detection_mode="batch"),
        ]
        return self._result("batch", findings, records, ())

    def analyze_rate_patterns(
        self,
        records: Iterable[AnomalyInput],
    ) -> AnomalyDetectionResult:
        normalized = tuple(_normalize_inputs(records))
        findings = self._detect_rate(normalized, detection_mode="batch")
        return self._result("batch", findings, normalized, ())

    def detect_security_violations(
        self,
        records: Iterable[AnomalyInput],
    ) -> AnomalyDetectionResult:
        normalized = tuple(_normalize_inputs(records))
        findings = self._detect_security(normalized, detection_mode="batch")
        return self._result("batch", findings, normalized, ())

    def analyze_replay_comparison(
        self,
        replay: ExecutionReplay | ReplayDiff,
    ) -> AnomalyDetectionResult:
        diff = replay if isinstance(replay, ReplayDiff) else replay_diff_from_replay(replay)
        findings = self._detect_replay_diff(diff)
        return self._result("replay", findings, (), (diff,))

    def analyze_batch(
        self,
        records: Iterable[AnomalyInput],
        *,
        replays: Iterable[ExecutionReplay | ReplayDiff] = (),
    ) -> AnomalyDetectionResult:
        normalized = tuple(_normalize_inputs(records))
        diffs = tuple(
            replay if isinstance(replay, ReplayDiff) else replay_diff_from_replay(replay)
            for replay in replays
        )
        findings = [
            *self._detect_behavior(normalized, detection_mode="batch"),
            *self._detect_rate(normalized, detection_mode="batch"),
            *self._detect_security(normalized, detection_mode="batch"),
        ]
        for diff in diffs:
            findings.extend(self._detect_replay_diff(diff))
        return self._result("batch", findings, normalized, diffs)

    def analyze_query_result(self, query_result: QueryResult) -> AnomalyDetectionResult:
        return self.analyze_batch((query_result,))

    def analyze_storage_window(
        self,
        time_range: StorageTimeRange,
        *,
        limit: int | None = None,
    ) -> AnomalyDetectionResult:
        if self.storage is None:
            raise ValueError("analyze_storage_window requires a C17D StorageAdapter.")
        result = self.storage.query_by_time_range(time_range, limit=limit)
        return self.analyze_batch(result.records)

    def _detect_behavior(
        self,
        records: Sequence[NormalizedRecord],
        *,
        detection_mode: DetectionMode,
    ) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        for record in records:
            findings.extend(
                self._detect_record_behavior(record, detection_mode=detection_mode)
            )
            if isinstance(record, ExecutionTrace):
                findings.extend(
                    self._detect_trace_behavior(record, detection_mode=detection_mode)
                )
        return findings

    def _detect_record_behavior(
        self,
        record: NormalizedRecord,
        *,
        detection_mode: DetectionMode,
    ) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        user_profile = self._profile("user", _user_id(record))
        context_profile = self._profile("context", _context_id(record))
        path = _api_path(record)
        workflow_id = _workflow_id(record)
        module = _module(record)
        action = _action(record)
        evidence: tuple[AlertEvidence, ...] = (_evidence_for(record),)

        if path is not None and self._not_allowed(
            path,
            user_profile,
            context_profile,
            field="allowed_api_paths",
        ):
            findings.append(
                self._finding(
                    anomaly_type="behavior",
                    entity_id=path,
                    entity_type="api",
                    rule_id="c17g.behavior.api_path",
                    behavior_score=64,
                    description=f"Non-normal API path observed: {path}.",
                    related_context_id=_context_id(record),
                    related_trace_id=_trace_id(record),
                    evidence=evidence,
                    detection_mode=detection_mode,
                )
            )

        if workflow_id is not None and self._not_allowed(
            workflow_id,
            user_profile,
            context_profile,
            field="allowed_workflows",
        ):
            findings.append(
                self._finding(
                    anomaly_type="behavior",
                    entity_id=workflow_id,
                    entity_type="workflow",
                    rule_id="c17g.behavior.workflow",
                    behavior_score=68,
                    description=f"Atypical workflow call observed: {workflow_id}.",
                    related_context_id=_context_id(record),
                    related_trace_id=_trace_id(record),
                    evidence=evidence,
                    detection_mode=detection_mode,
                )
            )

        if module in CONTROL_MODULES and self._not_allowed(
            module,
            user_profile,
            context_profile,
            field="allowed_modules",
        ):
            entity_id = _user_id(record) or _context_id(record)
            entity_type = "user" if _user_id(record) else "context"
            findings.append(
                self._finding(
                    anomaly_type="behavior",
                    entity_id=entity_id,
                    entity_type=entity_type,
                    rule_id="c17g.behavior.module_usage",
                    behavior_score=65,
                    description=f"Unexpected {module} module usage observed.",
                    related_context_id=_context_id(record),
                    related_trace_id=_trace_id(record),
                    evidence=evidence,
                    detection_mode=detection_mode,
                )
            )

        if module in CONTROL_MODULES and self._not_allowed(
            action,
            user_profile,
            context_profile,
            field="action_patterns",
        ):
            entity_id = _user_id(record) or _context_id(record)
            entity_type = "user" if _user_id(record) else "context"
            findings.append(
                self._finding(
                    anomaly_type="behavior",
                    entity_id=entity_id,
                    entity_type=entity_type,
                    rule_id="c17g.behavior.action_pattern",
                    behavior_score=48,
                    description=f"Non-baseline control action observed: {action}.",
                    related_context_id=_context_id(record),
                    related_trace_id=_trace_id(record),
                    evidence=evidence,
                    detection_mode=detection_mode,
                )
            )

        return findings

    def _detect_trace_behavior(
        self,
        trace: ExecutionTrace,
        *,
        detection_mode: DetectionMode,
    ) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        workflow_id = _workflow_id(trace)
        workflow_profile = self._profile("workflow", workflow_id)
        context_profile = self._profile("context", trace.context_id)
        sequence = _module_sequence(trace)
        evidence: tuple[AlertEvidence, ...] = (trace,)

        if sequence and self._sequence_not_allowed(
            sequence,
            workflow_profile,
            context_profile,
        ):
            findings.append(
                self._finding(
                    anomaly_type="behavior",
                    entity_id=workflow_id or trace.context_id,
                    entity_type="workflow" if workflow_id else "context",
                    rule_id="c17g.behavior.trace_sequence",
                    behavior_score=72,
                    description=(
                        "Unusual execution chain pattern observed: "
                        + " -> ".join(sequence)
                        + "."
                    ),
                    related_context_id=trace.context_id,
                    related_trace_id=trace.trace_id,
                    evidence=evidence,
                    detection_mode=detection_mode,
                )
            )

        missing_or_future_dependencies = self._trace_dependency_issues(trace)
        if missing_or_future_dependencies:
            findings.append(
                self._finding(
                    anomaly_type="behavior",
                    entity_id=trace.context_id,
                    entity_type="context",
                    rule_id="c17g.behavior.trace_dependency",
                    behavior_score=66,
                    description=(
                        "Trace dependency chain contains unexpected references: "
                        + ", ".join(missing_or_future_dependencies)
                        + "."
                    ),
                    related_context_id=trace.context_id,
                    related_trace_id=trace.trace_id,
                    evidence=evidence,
                    detection_mode=detection_mode,
                )
            )

        order_violation = self._chain_order_violation(sequence)
        if order_violation is not None:
            findings.append(
                self._finding(
                    anomaly_type="behavior",
                    entity_id=trace.context_id,
                    entity_type="context",
                    rule_id="c17g.behavior.trace_order",
                    behavior_score=61,
                    description=f"Unexpected execution chain order: {order_violation}.",
                    related_context_id=trace.context_id,
                    related_trace_id=trace.trace_id,
                    evidence=evidence,
                    detection_mode=detection_mode,
                )
            )

        return findings

    def _detect_rate(
        self,
        records: Sequence[NormalizedRecord],
        *,
        detection_mode: DetectionMode,
    ) -> list[AnomalyFinding]:
        if not records:
            return []

        windowed = _window_records(records, window=self.rolling_window)
        window_minutes = max(self.rolling_window.total_seconds() / 60, 1 / 60)
        findings: list[AnomalyFinding] = []
        by_user: dict[str, list[NormalizedRecord]] = defaultdict(list)
        by_context: dict[str, list[NormalizedRecord]] = defaultdict(list)
        by_workflow: dict[str, list[NormalizedRecord]] = defaultdict(list)

        for record in windowed:
            user_id = _user_id(record)
            workflow_id = _workflow_id(record)
            if user_id is not None:
                by_user[user_id].append(record)
            if workflow_id is not None:
                by_workflow[workflow_id].append(record)
            by_context[_context_id(record)].append(record)

        for user_id, grouped in by_user.items():
            baseline = self._profile("user", user_id)
            current_rate = len(grouped) / window_minutes
            baseline_rate = baseline.request_rate_per_minute if baseline else 0
            if self._is_rate_spike(current_rate, baseline_rate, len(grouped)):
                findings.append(
                    self._rate_finding(
                        entity_id=user_id,
                        entity_type="user",
                        rule_id="c17g.rate.user_high_frequency",
                        current_rate=current_rate,
                        baseline_rate=baseline_rate,
                        description_prefix=f"High-frequency user_id calls for {user_id}",
                        evidence=_evidence_tuple(grouped[:5]),
                        detection_mode=detection_mode,
                    )
                )

        for context_id, grouped in by_context.items():
            baseline = self._profile("context", context_id)
            current_rate = len(grouped) / window_minutes
            baseline_rate = baseline.context_rate_per_minute if baseline else 0
            if self._is_rate_spike(current_rate, baseline_rate, len(grouped)):
                findings.append(
                    self._rate_finding(
                        entity_id=context_id,
                        entity_type="context",
                        rule_id="c17g.rate.context_flood",
                        current_rate=current_rate,
                        baseline_rate=baseline_rate,
                        description_prefix=f"context_id flood for {context_id}",
                        evidence=_evidence_tuple(grouped[:5]),
                        detection_mode=detection_mode,
                    )
                )

        for workflow_id, grouped in by_workflow.items():
            retry_count = sum(_retry_count(record) for record in grouped)
            if retry_count < self.minimum_retry_events:
                continue
            baseline = self._profile("workflow", workflow_id)
            current_retry_rate = retry_count / window_minutes
            baseline_rate = baseline.retry_rate_per_minute if baseline else 0
            if self._is_rate_spike(
                current_retry_rate,
                baseline_rate,
                retry_count,
                minimum_count=self.minimum_retry_events,
            ):
                findings.append(
                    self._rate_finding(
                        entity_id=workflow_id,
                        entity_type="workflow",
                        rule_id="c17g.rate.workflow_retry_storm",
                        current_rate=current_retry_rate,
                        baseline_rate=baseline_rate,
                        description_prefix=(
                            f"C15H workflow retry storm for {workflow_id}"
                        ),
                        evidence=_evidence_tuple(grouped[:5]),
                        detection_mode=detection_mode,
                    )
                )

        return findings

    def _detect_security(
        self,
        records: Sequence[NormalizedRecord],
        *,
        detection_mode: DetectionMode,
    ) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        for record in records:
            text = _record_text(record).lower()
            evidence: tuple[AlertEvidence, ...] = (_evidence_for(record),)
            context_id = _context_id(record)
            trace_id = _trace_id(record)
            entity_id = _user_id(record) or context_id
            entity_type = "user" if _user_id(record) else "context"
            source = _source(record).lower()
            module = _module(record)

            if (
                ("control" in text or module in {"C13", "C16"})
                and _record_status_failed(record)
                and _contains_any(text, UNAUTHORIZED_PATTERNS)
            ):
                findings.append(
                    self._finding(
                        anomaly_type="security",
                        entity_id=entity_id,
                        entity_type=entity_type,
                        rule_id="c17g.security.control_plane_unauthorized",
                        security_score=84,
                        description=(
                            "Unauthorized control-plane access attempt detected."
                        ),
                        related_context_id=context_id,
                        related_trace_id=trace_id,
                        evidence=evidence,
                        detection_mode=detection_mode,
                    )
                )

            if (
                _contains_any(text, RBAC_PATTERNS)
                and _contains_any(text, UNAUTHORIZED_PATTERNS)
            ):
                findings.append(
                    self._finding(
                        anomaly_type="security",
                        entity_id=entity_id,
                        entity_type=entity_type,
                        rule_id="c17g.security.rbac_bypass",
                        security_score=88 if "bypass" in text else 80,
                        description="RBAC bypass or denied permission pattern detected.",
                        related_context_id=context_id,
                        related_trace_id=trace_id,
                        evidence=evidence,
                        detection_mode=detection_mode,
                    )
                )

            if (
                ("webhook" in source or "webhook" in text)
                and _contains_any(text, WEBHOOK_REPLAY_PATTERNS)
            ):
                findings.append(
                    self._finding(
                        anomaly_type="security",
                        entity_id=context_id,
                        entity_type="context",
                        rule_id="c17g.security.webhook_replay_abuse",
                        security_score=82,
                        description="Webhook replay abuse pattern detected.",
                        related_context_id=context_id,
                        related_trace_id=trace_id,
                        evidence=evidence,
                        detection_mode=detection_mode,
                    )
                )

            if _contains_any(text, INVALID_SESSION_PATTERNS) or (
                any(key in text for key in ("session", "token", "auth", "login"))
                and _contains_any(text, UNAUTHORIZED_PATTERNS)
            ):
                findings.append(
                    self._finding(
                        anomaly_type="security",
                        entity_id=entity_id,
                        entity_type=entity_type,
                        rule_id="c17g.security.invalid_session",
                        security_score=72,
                        description="Invalid session or token pattern detected.",
                        related_context_id=context_id,
                        related_trace_id=trace_id,
                        evidence=evidence,
                        detection_mode=detection_mode,
                    )
                )

            if self._prompt_injection_detected(record):
                findings.append(
                    self._finding(
                        anomaly_type="security",
                        entity_id=entity_id,
                        entity_type=entity_type,
                        rule_id="c17g.security.prompt_injection",
                        security_score=86,
                        description="Abnormal AI prompt injection pattern detected.",
                        related_context_id=context_id,
                        related_trace_id=trace_id,
                        evidence=evidence,
                        detection_mode=detection_mode,
                    )
                )

        return findings

    def _detect_replay_diff(self, diff: ReplayDiff) -> list[AnomalyFinding]:
        if not diff.divergence_detected:
            return []

        text = " ".join(diff.divergence_points).lower()
        behavior_score = 0.0
        rate_score = 0.0
        security_score = 0.0
        anomaly_type: AnomalyType = "behavior"
        rule_id = "c17g.replay.behavior_divergence"

        if any(
            marker in text
            for marker in (
                "output_mismatch",
                "missing_step",
                "unexpected_step",
                "step_order_mismatch",
                "status_mismatch",
            )
        ):
            behavior_score = min(88, 68 + len(diff.divergence_points) * 4)
        if "latency_divergence" in text:
            rate_score = min(82, 60 + text.count("latency_divergence") * 6)
            if rate_score > behavior_score:
                anomaly_type = "rate"
                rule_id = "c17g.replay.latency_divergence"
        if "context_id_mismatch" in text or "trace_id_mismatch" in text:
            security_score = 86
            anomaly_type = "security"
            rule_id = "c17g.replay.identity_mismatch"

        if max(behavior_score, rate_score, security_score) == 0:
            behavior_score = 62

        return [
            self._finding(
                anomaly_type=anomaly_type,
                entity_id=diff.context_id,
                entity_type="context",
                rule_id=rule_id,
                behavior_score=behavior_score,
                rate_score=rate_score,
                security_score=security_score,
                description=diff.comparison_summary,
                related_context_id=diff.context_id,
                related_trace_id=diff.original_trace_id,
                evidence=(diff,),
                detection_mode="replay",
            )
        ]

    def _prompt_injection_detected(self, record: NormalizedRecord) -> bool:
        if isinstance(record, ExecutionTrace):
            for step in record.chain:
                if step.module != "AI":
                    continue
                if _contains_any(_flatten_text(step.input), PROMPT_INJECTION_PATTERNS):
                    return True
                if _contains_any(_flatten_text(step.output), PROMPT_INJECTION_PATTERNS):
                    return True
            return False

        source = _source(record).lower()
        text = _record_text(record)
        return ("ai" in source or _module(record) in {"C14", "C15"}) and _contains_any(
            text,
            PROMPT_INJECTION_PATTERNS,
        )

    def _profile(
        self,
        scope: str,
        entity_id: str | None,
    ) -> BaselineProfile | None:
        if entity_id is None:
            return None
        if scope == "user":
            return self.baseline_model.users.get(entity_id)
        if scope == "module":
            return self.baseline_model.modules.get(entity_id)
        if scope == "workflow":
            return self.baseline_model.workflows.get(entity_id)
        if scope == "context":
            return self.baseline_model.contexts.get(entity_id)
        return None

    def _not_allowed(
        self,
        value: str,
        *profiles: BaselineProfile | None,
        field: str,
    ) -> bool:
        checked = False
        for profile in profiles:
            if profile is None:
                continue
            allowed = tuple(getattr(profile, field))
            if not allowed:
                continue
            checked = True
            if value in allowed:
                return False
        return checked

    def _sequence_not_allowed(
        self,
        sequence: tuple[str, ...],
        *profiles: BaselineProfile | None,
    ) -> bool:
        checked = False
        for profile in profiles:
            if profile is None or not profile.module_sequence_patterns:
                continue
            checked = True
            if sequence in profile.module_sequence_patterns:
                return False
        return checked

    def _trace_dependency_issues(self, trace: ExecutionTrace) -> tuple[str, ...]:
        seen: set[str] = set()
        issues: list[str] = []
        all_step_ids = {step.step_id for step in trace.chain}
        for step in trace.chain:
            dependency = step.dependency_step_id
            if dependency is not None and dependency not in all_step_ids:
                issues.append(f"{step.step_id}->missing:{dependency}")
            elif dependency is not None and dependency not in seen:
                issues.append(f"{step.step_id}->future:{dependency}")
            seen.add(step.step_id)
        return tuple(issues)

    def _chain_order_violation(self, sequence: tuple[str, ...]) -> str | None:
        order = {module: index for index, module in enumerate(EXPECTED_CHAIN_ORDER)}
        highest_seen = -1
        highest_module = ""
        for module in sequence:
            if module not in order:
                continue
            current = order[module]
            if current < highest_seen:
                return f"{module} appeared after {highest_module}"
            highest_seen = current
            highest_module = module
        return None

    def _is_rate_spike(
        self,
        current_rate: float,
        baseline_rate: float,
        count: int,
        *,
        minimum_count: int | None = None,
    ) -> bool:
        threshold_count = minimum_count or self.minimum_rate_events
        if count < threshold_count:
            return False
        effective_baseline = max(baseline_rate, 1)
        return current_rate >= effective_baseline * self.spike_threshold_multiplier

    def _rate_score(self, current_rate: float, baseline_rate: float) -> float:
        effective_baseline = max(baseline_rate, 1)
        ratio = current_rate / effective_baseline
        if ratio >= 10:
            return 92
        if ratio >= 6:
            return 82
        if ratio >= 3:
            return 66
        return 45

    def _rate_finding(
        self,
        *,
        entity_id: str,
        entity_type: str,
        rule_id: str,
        current_rate: float,
        baseline_rate: float,
        description_prefix: str,
        evidence: tuple[AlertEvidence, ...],
        detection_mode: DetectionMode,
    ) -> AnomalyFinding:
        score = self._rate_score(current_rate, baseline_rate)
        return self._finding(
            anomaly_type="rate",
            entity_id=entity_id,
            entity_type=entity_type,  # type: ignore[arg-type]
            rule_id=rule_id,
            rate_score=score,
            description=(
                f"{description_prefix}: current {current_rate:.2f}/min vs "
                f"baseline {baseline_rate:.2f}/min."
            ),
            related_context_id=(
                entity_id if entity_type == "context" else self._first_context(evidence)
            ),
            related_trace_id=self._first_trace(evidence),
            evidence=evidence,
            detection_mode=detection_mode,
        )

    def _finding(
        self,
        *,
        anomaly_type: AnomalyType,
        entity_id: str,
        entity_type: str,
        rule_id: str,
        description: str,
        related_context_id: str | None,
        related_trace_id: str | None,
        evidence: tuple[AlertEvidence, ...],
        detection_mode: DetectionMode,
        behavior_score: float = 0,
        rate_score: float = 0,
        security_score: float = 0,
    ) -> AnomalyFinding:
        total_score = min(max(behavior_score, rate_score, security_score), 100)
        severity = severity_for_score(total_score)
        score = AnomalyScore(
            entity_id=entity_id,
            entity_type=entity_type,  # type: ignore[arg-type]
            scores=ScoreBreakdown(
                behavior_score=behavior_score,
                rate_score=rate_score,
                security_score=security_score,
            ),
            total_score=total_score,
            severity=severity,
        )
        alert = Alert(
            anomaly_type=anomaly_type,
            severity=severity,
            related_context_id=related_context_id,
            related_trace_id=related_trace_id,
            description=description,
            evidence=evidence,
        )
        return AnomalyFinding(
            anomaly_type=anomaly_type,
            entity_id=entity_id,
            entity_type=entity_type,  # type: ignore[arg-type]
            rule_id=rule_id,
            score=score,
            alert=alert,
            detection_mode=detection_mode,
        )

    def _first_context(self, evidence: Sequence[AlertEvidence]) -> str | None:
        for item in evidence:
            if isinstance(item, ReplayDiff):
                return item.context_id
            if isinstance(item, (LogEntry, ExecutionTrace)):
                return item.context_id
        return None

    def _first_trace(self, evidence: Sequence[AlertEvidence]) -> str | None:
        for item in evidence:
            if isinstance(item, ReplayDiff):
                return item.original_trace_id
            if isinstance(item, ExecutionTrace):
                return item.trace_id
            if isinstance(item, LogEntry):
                return _trace_id(item)
        return None

    def _prune_rolling_records(self) -> None:
        if not self._rolling_records:
            return
        latest = max(_record_timestamp(record) for record in self._rolling_records)
        cutoff = latest - self.rolling_window
        self._rolling_records = [
            record
            for record in self._rolling_records
            if _record_timestamp(record) >= cutoff
        ]

    def _result(
        self,
        detection_mode: DetectionMode,
        findings: Sequence[AnomalyFinding],
        records: Sequence[NormalizedRecord],
        replay_diffs: Sequence[ReplayDiff],
    ) -> AnomalyDetectionResult:
        return AnomalyDetectionResult(
            detection_mode=detection_mode,
            scores=tuple(finding.score for finding in findings),
            alerts=tuple(finding.alert for finding in findings),
            findings=tuple(findings),
            analyzed_log_count=sum(
                isinstance(record, (LogEntry, EventRaw)) for record in records
            ),
            analyzed_trace_count=sum(
                isinstance(record, ExecutionTrace) for record in records
            ),
            analyzed_replay_diff_count=len(replay_diffs),
            baseline_model=self.baseline_model,
        )


class StreamAnomalyEngine:
    """Stream-based anomaly engine backed by event_streams and anomaly_events."""

    def __init__(
        self,
        *,
        db: Session | None = None,
        org_id: str | None = None,
        baseline_model: BaselineModel | None = None,
        window_seconds: int = 60,
        threshold_event_count: int = 5,
        spike_threshold_multiplier: float = 3,
    ) -> None:
        ensure_observability_tables()
        self._db = db
        self._org_id = org_id
        self.window = timedelta(seconds=max(window_seconds, 1))
        self.threshold_event_count = max(threshold_event_count, 1)
        self.detector = AnomalyDetectionEngine(
            baseline_model=baseline_model,
            rolling_window_seconds=max(window_seconds, 1),
            spike_threshold_multiplier=spike_threshold_multiplier,
            minimum_rate_events=max(threshold_event_count, 1),
        )

    def analyze_stream(
        self,
        *,
        time_range: StorageTimeRange | None = None,
        org_id: str | None = None,
        module_id: str | None = None,
        threshold_event_count: int | None = None,
        limit: int | None = None,
    ) -> AnomalyDetectionResult:
        rows = self._load_rows(
            time_range=time_range,
            org_id=org_id,
            module_id=module_id,
            limit=limit,
        )
        records = tuple(storage_record_from_event_stream_row(row) for row in rows)
        normalized = tuple(decode_storage_record(record) for record in records)
        base = self.detector.analyze_batch(normalized)
        threshold_findings = self._threshold_findings(
            rows,
            normalized,
            threshold=threshold_event_count or self.threshold_event_count,
        )
        findings = (*base.findings, *threshold_findings)
        result = self.detector._result("streaming", findings, normalized, ())
        self._persist_findings(result.findings, rows)
        return result

    def analyze_latest_window(
        self,
        *,
        org_id: str | None = None,
        module_id: str | None = None,
        limit: int | None = None,
    ) -> AnomalyDetectionResult:
        end_at = datetime.now(UTC)
        return self.analyze_stream(
            time_range=StorageTimeRange(start_at=end_at - self.window, end_at=end_at),
            org_id=org_id,
            module_id=module_id,
            limit=limit,
        )

    def persisted_events(
        self,
        *,
        org_id: str | None = None,
        module_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[AnomalyEventRecord, ...]:
        with self._session() as db:
            statement = select(AnomalyEventRecord)
            effective_org_id = org_id or self._org_id
            if effective_org_id is not None:
                statement = statement.where(AnomalyEventRecord.org_id == effective_org_id)
            if module_id is not None:
                statement = statement.where(AnomalyEventRecord.module_id == module_id)
            statement = statement.order_by(
                AnomalyEventRecord.timestamp.desc(),
                AnomalyEventRecord.id.desc(),
            )
            if limit is not None:
                statement = statement.limit(max(limit, 0))
            return tuple(db.scalars(statement))

    def _load_rows(
        self,
        *,
        time_range: StorageTimeRange | None,
        org_id: str | None,
        module_id: str | None,
        limit: int | None,
    ) -> tuple[EventStreamRecord, ...]:
        if time_range is None:
            end_at = datetime.now(UTC)
            time_range = StorageTimeRange(start_at=end_at - self.window, end_at=end_at)
        with self._session() as db:
            statement = select(EventStreamRecord)
            effective_org_id = org_id or self._org_id
            if effective_org_id is not None:
                statement = statement.where(EventStreamRecord.org_id == effective_org_id)
            if module_id is not None:
                statement = statement.where(EventStreamRecord.module_id == module_id)
            if time_range.start_at is not None:
                statement = statement.where(EventStreamRecord.timestamp >= time_range.start_at)
            if time_range.end_at is not None:
                statement = statement.where(EventStreamRecord.timestamp <= time_range.end_at)
            statement = statement.order_by(EventStreamRecord.timestamp.desc())
            if limit is not None:
                statement = statement.limit(max(limit, 0))
            return tuple(db.scalars(statement))

    def _threshold_findings(
        self,
        rows: Sequence[EventStreamRecord],
        records: Sequence[NormalizedRecord],
        *,
        threshold: int,
    ) -> tuple[AnomalyFinding, ...]:
        if not rows:
            return ()
        records_by_context = {record.context_id: record for record in records}
        grouped: dict[tuple[str, str], list[EventStreamRecord]] = defaultdict(list)
        for row in rows:
            grouped[(row.org_id, row.module_id)].append(row)

        findings: list[AnomalyFinding] = []
        for (org_id, module_id), grouped_rows in grouped.items():
            if len(grouped_rows) < threshold:
                continue
            evidence_records = tuple(
                records_by_context[row.context_id]
                for row in grouped_rows[:5]
                if row.context_id in records_by_context
            )
            findings.append(
                self.detector._finding(
                    anomaly_type="rate",
                    entity_id=f"{org_id}:{module_id}",
                    entity_type="context",
                    rule_id="c17g.stream.threshold.module_volume",
                    rate_score=min(95, 60 + len(grouped_rows) * 4),
                    description=(
                        f"Event stream threshold exceeded for org {org_id} "
                        f"module {module_id}: {len(grouped_rows)} events."
                    ),
                    related_context_id=grouped_rows[0].context_id,
                    related_trace_id=grouped_rows[0].trace_id,
                    evidence=_evidence_tuple(evidence_records),
                    detection_mode="streaming",
                )
            )
        return tuple(findings)

    def _persist_findings(
        self,
        findings: Sequence[AnomalyFinding],
        rows: Sequence[EventStreamRecord],
    ) -> None:
        if not findings:
            return
        row_by_context = {row.context_id: row for row in rows}
        fallback_org_id = self._org_id or "platform"
        with self._session() as db:
            for finding in findings:
                related_context_id = finding.alert.related_context_id
                source = (
                    row_by_context.get(related_context_id)
                    if related_context_id is not None
                    else None
                )
                db.add(
                    AnomalyEventRecord(
                        org_id=(source.org_id if source is not None else fallback_org_id),
                        anomaly_id=f"anomaly-{uuid4()}",
                        source_event_id=source.event_id if source is not None else None,
                        context_id=related_context_id,
                        trace_id=finding.alert.related_trace_id,
                        module_id=source.module_id if source is not None else "system",
                        anomaly_type=finding.anomaly_type,
                        severity=finding.score.severity,
                        rule_id=finding.rule_id,
                        entity_type=finding.entity_type,
                        entity_id=finding.entity_id,
                        status="open",
                        timestamp=(
                            source.timestamp
                            if source is not None
                            else datetime.now(UTC)
                        ),
                        threshold_value=float(self.threshold_event_count),
                        observed_value=finding.score.total_score,
                        window_seconds=int(self.window.total_seconds()),
                        event_count=len(rows),
                        score=finding.score.model_dump(mode="json"),
                        evidence=finding.alert.model_dump(mode="json"),
                    )
                )
            self._commit(db)

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


def get_anomaly_detection_engine_design() -> AnomalyDetectionEngineDesign:
    return AnomalyDetectionEngineDesign()


def get_anomaly_classification_system() -> AnomalyClassificationSystem:
    return AnomalyClassificationSystem()


def get_anomaly_scoring_model() -> AnomalyScoringModel:
    return AnomalyScoringModel()


def get_baseline_model_design() -> BaselineModelDesign:
    return BaselineModelDesign()


def get_alert_system_schema() -> AlertSystemSchema:
    return AlertSystemSchema()


def get_integration_architecture() -> IntegrationArchitecture:
    return IntegrationArchitecture()


def get_detection_pipeline_flow() -> DetectionPipelineFlow:
    return DetectionPipelineFlow()


def get_severity_rules() -> SeverityRules:
    return SeverityRules()


def get_anomaly_detection_completion_status() -> AnomalyDetectionCompletionStatus:
    return AnomalyDetectionCompletionStatus()
