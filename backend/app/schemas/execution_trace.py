from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TraceModule = Literal["C14", "C15", "n8n", "AI", "DB", "system"]
TraceStepStatus = Literal["success", "failed", "pending"]
TraceFinalStatus = Literal["success", "failed", "partial"]
TraceLifecycleState = Literal["start", "complete", "record"]
TraceCompletenessIssueType = Literal[
    "missing_terminal_event",
    "missing_dependency_step",
    "missing_required_action",
]

TRACE_MODULES: tuple[TraceModule, ...] = (
    "C14",
    "C15",
    "n8n",
    "AI",
    "DB",
    "system",
)
TRACE_STEP_STATUSES: tuple[TraceStepStatus, ...] = (
    "success",
    "failed",
    "pending",
)
TRACE_FINAL_STATUSES: tuple[TraceFinalStatus, ...] = (
    "success",
    "failed",
    "partial",
)
EXECUTION_TRACE_FIELDS: tuple[str, ...] = (
    "trace_id",
    "context_id",
    "root_event_id",
    "chain",
    "final_status",
    "total_latency_ms",
)
TRACE_STEP_FIELDS: tuple[str, ...] = (
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
TRACE_INDEXABLE_FIELDS: tuple[str, ...] = (
    "trace_id",
    "context_id",
    "root_event_id",
    "module",
    "final_status",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ExecutionTraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=180)
    step_index: int = Field(ge=0)
    module: TraceModule
    action: str = Field(min_length=1, max_length=240)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    status: TraceStepStatus
    latency_ms: float = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=utc_now)
    error: dict[str, Any] | None = None
    retry_count: int = Field(default=0, ge=0)
    dependency_step_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=180,
    )

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ExecutionTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    root_event_id: str = Field(min_length=1, max_length=180)
    chain: tuple[ExecutionTraceStep, ...] = Field(default_factory=tuple)
    final_status: TraceFinalStatus
    total_latency_ms: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_chain_order(self) -> "ExecutionTrace":
        step_ids = [step.step_id for step in self.chain]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("ExecutionTrace chain step_id values must be unique.")
        step_indexes = [step.step_index for step in self.chain]
        if step_indexes != sorted(step_indexes):
            raise ValueError("ExecutionTrace chain must be ordered by step_index.")
        if step_indexes and step_indexes != list(range(len(step_indexes))):
            raise ValueError("ExecutionTrace step_index values must be contiguous.")
        return self


class TraceStepEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    trace_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    root_event_id: str = Field(min_length=1, max_length=180)
    step_id: str = Field(min_length=1, max_length=180)
    step_index: int | None = Field(default=None, ge=0)
    lifecycle: TraceLifecycleState = "record"
    module: TraceModule
    action: str = Field(min_length=1, max_length=240)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    status: TraceStepStatus = "pending"
    latency_ms: float = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=utc_now)
    error: dict[str, Any] | None = None
    retry_count: int = Field(default=0, ge=0)
    dependency_step_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=180,
    )

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class TraceCompletenessIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_type: TraceCompletenessIssueType
    step_id: str | None = Field(default=None, max_length=180)
    action: str | None = Field(default=None, max_length=240)
    module: TraceModule | None = None
    reason: str = Field(min_length=1, max_length=500)


class ExecutionTraceSchemaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["c17c_execution_trace_schema_v1"] = (
        "c17c_execution_trace_schema_v1"
    )
    canonical_model: Literal["ExecutionTrace"] = "ExecutionTrace"
    fields: tuple[str, ...] = EXECUTION_TRACE_FIELDS
    chain_step_fields: tuple[str, ...] = TRACE_STEP_FIELDS
    module_values: tuple[TraceModule, ...] = TRACE_MODULES
    step_status_values: tuple[TraceStepStatus, ...] = TRACE_STEP_STATUSES
    final_status_values: tuple[TraceFinalStatus, ...] = TRACE_FINAL_STATUSES
    replay_ready: Literal[True] = True
    business_logic_changed: Literal[False] = False
    api_contract_changed: Literal[False] = False
    database_migration_executed: Literal[False] = False


class TraceHookInjectionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_id: str = Field(min_length=1, max_length=180)
    layer: Literal["C14", "C15", "n8n", "AI Layer", "DB / Storage"]
    module: TraceModule
    action: str = Field(min_length=1, max_length=240)
    lifecycle: TraceLifecycleState
    captures_input_snapshot: bool
    captures_output_snapshot: bool
    captures_latency_ms: Literal[True] = True
    captures_error: Literal[True] = True
    captures_retry_count: Literal[True] = True
    captures_dependency_step_reference: Literal[True] = True
    shares_trace_id_and_context_id: Literal[True] = True


class TraceHookInjectionCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: Literal["c17c_trace_hook_injection_points_v1"] = (
        "c17c_trace_hook_injection_points_v1"
    )
    hooks: tuple[TraceHookInjectionPoint, ...]
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    api_contract_changed: Literal[False] = False
    n8n_runtime_changed: Literal[False] = False


class CrossSystemTraceStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_index: int = Field(ge=0)
    stage: Literal[
        "frontend_request",
        "backend API (C13/C14/C16)",
        "execution engine (C15)",
        "n8n workflow",
        "AI call (GPT / DeepSeek / 4sapi)",
        "DB / FileStorage",
    ]
    trace_module: TraceModule
    shared_identifiers: tuple[Literal["trace_id"], Literal["context_id"]] = (
        "trace_id",
        "context_id",
    )
    handoff_rule: str = Field(min_length=1, max_length=500)


class CrossSystemTraceMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_id: Literal["c17c_cross_system_trace_mapping_v1"] = (
        "c17c_cross_system_trace_mapping_v1"
    )
    stages: tuple[CrossSystemTraceStage, ...]
    trace_id_rule: Literal["created at request ingress and propagated unchanged"] = (
        "created at request ingress and propagated unchanged"
    )
    context_id_rule: Literal["business execution context propagated unchanged"] = (
        "business execution context propagated unchanged"
    )


class TraceStepLifecycleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_id: Literal["c17c_step_lifecycle_v1"] = "c17c_step_lifecycle_v1"
    states: tuple[TraceLifecycleState, ...] = ("start", "complete", "record")
    required_step_fields: tuple[str, ...] = TRACE_STEP_FIELDS
    start_rule: Literal[
        "start events capture input snapshot and mark the step pending"
    ] = "start events capture input snapshot and mark the step pending"
    complete_rule: Literal[
        "complete events capture output snapshot, final status, latency, and error"
    ] = (
        "complete events capture output snapshot, final status, latency, and error"
    )
    record_rule: Literal[
        "record events represent atomic one-shot steps with input and output"
    ] = "record events represent atomic one-shot steps with input and output"
    dependency_rule: Literal[
        "dependency_step_id references a previous step_id in the same trace"
    ] = "dependency_step_id references a previous step_id in the same trace"
    replay_rule: Literal[
        "replay sorts steps by step_index and replays input/output snapshots"
    ] = "replay sorts steps by step_index and replays input/output snapshots"


class TraceAggregatorDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: Literal["c17c_trace_aggregator_v1"] = (
        "c17c_trace_aggregator_v1"
    )
    responsibilities: tuple[
        Literal["collect step events"],
        Literal["merge into ExecutionTrace"],
        Literal["maintain ordering"],
        Literal["compute latency"],
        Literal["detect missing steps"],
    ] = (
        "collect step events",
        "merge into ExecutionTrace",
        "maintain ordering",
        "compute latency",
        "detect missing steps",
    )
    ordering_rule: Literal[
        "explicit step_index first, then timestamp, then arrival order"
    ] = "explicit step_index first, then timestamp, then arrival order"
    latency_rule: Literal[
        "use reported latency_ms, or derive from paired start/complete timestamps"
    ] = "use reported latency_ms, or derive from paired start/complete timestamps"
    missing_step_detection: tuple[
        Literal["pending step without complete event"],
        Literal["dependency_step_id not found in chain"],
        Literal["required action absent from trace"],
    ] = (
        "pending step without complete event",
        "dependency_step_id not found in chain",
        "required action absent from trace",
    )


class TraceStorageFormatDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: Literal["c17c_trace_storage_format_v1"] = (
        "c17c_trace_storage_format_v1"
    )
    supported_formats: tuple[
        Literal["JSON debug"],
        Literal["JSONL stream"],
        Literal["future DB table"],
    ] = ("JSON debug", "JSONL stream", "future DB table")
    default_stream_format: Literal["JSONL"] = "JSONL"
    json_debug_model: Literal["ExecutionTrace"] = "ExecutionTrace"
    jsonl_stream_models: tuple[
        Literal["TraceStepEvent"],
        Literal["ExecutionTrace"],
    ] = ("TraceStepEvent", "ExecutionTrace")
    future_db_table_ready: Literal[True] = True
    indexable_fields: tuple[str, ...] = TRACE_INDEXABLE_FIELDS
    database_migration_executed: Literal[False] = False


class ExecutionFlowDiagram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagram_id: Literal["c17c_execution_flow_diagram_v1"] = (
        "c17c_execution_flow_diagram_v1"
    )
    lines: tuple[str, ...] = (
        "frontend_request [trace_id, context_id]",
        "  -> backend API (C13/C14/C16) [trace_id, context_id]",
        "  -> C14 capability selection [trace_id, context_id]",
        "  -> C15 workflow execution [trace_id, context_id]",
        "  -> n8n workflow/node execution [trace_id, context_id]",
        "  -> AI call: GPT / DeepSeek / 4sapi [trace_id, context_id]",
        "  -> DB / FileStorage write [trace_id, context_id]",
        "  -> ExecutionTrace JSON/JSONL [replay-ready]",
    )


class C17BToC17CMigrationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: Literal["c17b_logs_to_c17c_traces_v1"] = (
        "c17b_logs_to_c17c_traces_v1"
    )
    steps: tuple[str, ...] = (
        "Read C17B LogEntry JSONL or normalized LogEntry objects without changing C17B.",
        "Group entries by trace_id when present, otherwise by context_id.",
        "Map LogEntry.event_id to root_event_id for the first entry in the group.",
        "Map LogEntry.request to TraceStepEvent.input and LogEntry.response to output.",
        "Map LogEntry.latency_ms and metadata.retry_count to the step lifecycle fields.",
        "Infer C17C module values as C14, C15, n8n, AI, DB, or system.",
        "Aggregate TraceStepEvent records into ordered ExecutionTrace records.",
        "Write C17C JSON debug or JSONL stream records; keep future DB output table-ready only.",
    )
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    business_logic_changed: Literal[False] = False
    api_contract_changed: Literal[False] = False
    database_migration_executed: Literal[False] = False
    n8n_runtime_changed: Literal[False] = False


class ExecutionTraceCompletionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["C17C"] = "C17C"
    component: Literal["Execution Trace System"] = "Execution Trace System"
    completion_status: Literal["complete"] = "complete"
    execution_trace_schema_defined: Literal[True] = True
    trace_hook_injection_points_defined: Literal[True] = True
    cross_system_trace_mapping_defined: Literal[True] = True
    step_lifecycle_defined: Literal[True] = True
    trace_aggregator_defined: Literal[True] = True
    json_jsonl_storage_defined: Literal[True] = True
    migration_plan_defined: Literal[True] = True
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    business_logic_changed: Literal[False] = False
    api_contract_changed: Literal[False] = False
    database_migration_executed: Literal[False] = False
    n8n_runtime_changed: Literal[False] = False
