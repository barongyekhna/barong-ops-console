from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .execution_trace import ExecutionTrace
from .storage_layer import StorageRecordEnvelope
from .structured_logs import LogEntry


ReplayMode = Literal["dry_run", "debug", "full"]
ReplayStepStatus = Literal["success", "failed", "skipped"]
ReplayBreakpointKind = Literal[
    "C14 capability selection",
    "C15 workflow execution",
    "AI call",
    "DB write",
]

REPLAY_MODES: tuple[ReplayMode, ...] = ("dry_run", "debug", "full")
REPLAY_STEP_STATUSES: tuple[ReplayStepStatus, ...] = (
    "success",
    "failed",
    "skipped",
)
REPLAY_BREAKPOINTS: tuple[ReplayBreakpointKind, ...] = (
    "C14 capability selection",
    "C15 workflow execution",
    "AI call",
    "DB write",
)
EXECUTION_REPLAY_FIELDS: tuple[str, ...] = (
    "replay_id",
    "original_trace_id",
    "context_id",
    "mode",
    "steps",
    "replay_result",
)
REPLAY_STEP_FIELDS: tuple[str, ...] = (
    "step_id",
    "step_index",
    "original_action",
    "replay_input",
    "replay_output",
    "status",
    "simulated_latency_ms",
    "is_replayed",
)
REPLAY_RESULT_FIELDS: tuple[str, ...] = (
    "success",
    "divergence_detected",
    "divergence_points",
)
REPLAY_API_METHODS: tuple[str, ...] = (
    "replay_by_trace_id(trace_id, mode)",
    "replay_by_context_id(context_id)",
    "replay_step(step_id)",
    "debug_trace(trace_id)",
)


class ReplayStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=180)
    step_index: int = Field(ge=0)
    original_action: str = Field(min_length=1, max_length=240)
    replay_input: dict[str, Any] = Field(default_factory=dict)
    replay_output: dict[str, Any] = Field(default_factory=dict)
    status: ReplayStepStatus
    simulated_latency_ms: float = Field(ge=0)
    is_replayed: Literal[True] = True


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    divergence_detected: bool
    divergence_points: tuple[str, ...] = Field(default_factory=tuple)


class ExecutionReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replay_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    original_trace_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    mode: ReplayMode
    steps: tuple[ReplayStep, ...] = Field(default_factory=tuple)
    replay_result: ReplayResult

    @model_validator(mode="after")
    def validate_step_order(self) -> "ExecutionReplay":
        step_indexes = [step.step_index for step in self.steps]
        if step_indexes != sorted(step_indexes):
            raise ValueError("ExecutionReplay steps must be ordered by step_index.")
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("ExecutionReplay step_id values must be unique.")
        return self


class ReplayExecutionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replay_output: dict[str, Any] = Field(default_factory=dict)
    status: ReplayStepStatus
    latency_ms: float = Field(ge=0)


class ReplaySnapshotBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_trace: ExecutionTrace
    storage_records: tuple[StorageRecordEnvelope, ...] = Field(default_factory=tuple)
    log_snapshots: tuple[LogEntry, ...] = Field(default_factory=tuple)


class ReplayDebugFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=180)
    step_index: int = Field(ge=0)
    breakpoint: ReplayBreakpointKind | None = None
    paused: bool
    inspect_input: dict[str, Any] = Field(default_factory=dict)
    inspect_output: dict[str, Any] = Field(default_factory=dict)
    resume_token: str = Field(default_factory=lambda: str(uuid4()), min_length=1)


class ReplayDebugSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debug_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    trace_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    mode: Literal["debug"] = "debug"
    breakpoints: tuple[ReplayBreakpointKind, ...] = Field(default_factory=tuple)
    current_step_index: int = Field(default=0, ge=0)
    frames: tuple[ReplayDebugFrame, ...] = Field(default_factory=tuple)
    replay: ExecutionReplay


class ExecutionReplaySchemaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["c17f_execution_replay_schema_v1"] = (
        "c17f_execution_replay_schema_v1"
    )
    canonical_model: Literal["ExecutionReplay"] = "ExecutionReplay"
    fields: tuple[str, ...] = EXECUTION_REPLAY_FIELDS
    step_fields: tuple[str, ...] = REPLAY_STEP_FIELDS
    result_fields: tuple[str, ...] = REPLAY_RESULT_FIELDS
    mode_values: tuple[ReplayMode, ...] = REPLAY_MODES
    step_status_values: tuple[ReplayStepStatus, ...] = REPLAY_STEP_STATUSES
    is_replayed_required: Literal[True] = True
    production_runtime_changed: Literal[False] = False


class ReplayEngineDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: Literal["c17f_replay_engine_v1"] = "c17f_replay_engine_v1"
    component: Literal["Step Replay Engine"] = "Step Replay Engine"
    inputs: tuple[Literal["trace_id"], Literal["context_id"], Literal["mode"]] = (
        "trace_id",
        "context_id",
        "mode",
    )
    output_model: Literal["ExecutionReplay"] = "ExecutionReplay"
    responsibilities: tuple[str, ...] = (
        "Load the original C17C ExecutionTrace from C17D storage.",
        "Replay steps in ExecutionTrace.step_index order.",
        "Run dry-run, debug, or full replay through a controlled step executor.",
        "Build ExecutionReplay and pass it to ReplayAnalyzer.",
    )
    dry_run_short_circuits_real_execution: Literal[True] = True
    controlled_executor_required_for_full_mode: Literal[True] = True


class DryRunSimulationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: Literal["c17f_dry_run_simulation_v1"] = (
        "c17f_dry_run_simulation_v1"
    )
    blocked_targets: tuple[
        Literal["real AI providers"],
        Literal["n8n webhooks"],
        Literal["database writes"],
        Literal["filesystem writes"],
    ] = (
        "real AI providers",
        "n8n webhooks",
        "database writes",
        "filesystem writes",
    )
    output_sources: tuple[
        Literal["C17D stored response snapshots"],
        Literal["C17C original step output"],
        Literal["synthetic simulation fallback"],
    ] = (
        "C17D stored response snapshots",
        "C17C original step output",
        "synthetic simulation fallback",
    )
    calls_real_ai: Literal[False] = False
    triggers_n8n_webhook: Literal[False] = False
    writes_database: Literal[False] = False
    modifies_filesystem: Literal[False] = False


class DebugStepExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: Literal["c17f_debug_step_execution_v1"] = (
        "c17f_debug_step_execution_v1"
    )
    supports_step_by_step_pause: Literal[True] = True
    inspectable_snapshots: tuple[Literal["input"], Literal["output"]] = (
        "input",
        "output",
    )
    breakpoints: tuple[ReplayBreakpointKind, ...] = REPLAY_BREAKPOINTS
    resume_token_required: Literal[True] = True


class FullReplayExecutionFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_id: Literal["c17f_full_replay_flow_v1"] = "c17f_full_replay_flow_v1"
    ordered_flow: tuple[str, ...] = (
        "Load original ExecutionTrace and storage snapshots.",
        "Bind replay execution to the original context_id.",
        "Execute each step through a controlled sandbox executor.",
        "Capture replay input, output, status, and latency.",
        "Compare replay output with the original trace.",
    )
    controlled_execution_sandbox_required: Literal[True] = True
    same_context_id_enforced: Literal[True] = True
    production_runtime_changed: Literal[False] = False


class DivergenceDetectionLogic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logic_id: Literal["c17f_divergence_detection_v1"] = (
        "c17f_divergence_detection_v1"
    )
    comparisons: tuple[
        Literal["original output vs replay output"],
        Literal["latency differences"],
        Literal["step order mismatch"],
        Literal["missing steps"],
    ] = (
        "original output vs replay output",
        "latency differences",
        "step order mismatch",
        "missing steps",
    )
    output_model: Literal["ReplayResult"] = "ReplayResult"
    divergence_points_include_step_id: Literal[True] = True


class ReplayStorageIntegrationDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integration_id: Literal["c17f_storage_integration_v1"] = (
        "c17f_storage_integration_v1"
    )
    reads: tuple[
        Literal["C17C ExecutionTrace"],
        Literal["C17D Storage Layer"],
        Literal["C17B LogEntry snapshots"],
    ] = (
        "C17C ExecutionTrace",
        "C17D Storage Layer",
        "C17B LogEntry snapshots",
    )
    lookup_keys: tuple[Literal["trace_id"], Literal["context_id"]] = (
        "trace_id",
        "context_id",
    )
    writes_to_storage: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    c17d_modified: Literal[False] = False


class ReplayAPIDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_id: Literal["c17f_replay_api_v1"] = "c17f_replay_api_v1"
    method_names: tuple[str, ...] = REPLAY_API_METHODS
    default_mode: Literal["dry_run"] = "dry_run"
    returns: Literal["ExecutionReplay | ReplayStep | ReplayDebugSession"] = (
        "ExecutionReplay | ReplayStep | ReplayDebugSession"
    )
    ui_integrated: Literal[False] = False


class ExecutionReplayCompletionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["C17F"] = "C17F"
    component: Literal["Execution Replay System"] = "Execution Replay System"
    completion_status: Literal["complete"] = "complete"
    execution_replay_schema_defined: Literal[True] = True
    replay_engine_defined: Literal[True] = True
    dry_run_simulation_defined: Literal[True] = True
    debug_step_execution_defined: Literal[True] = True
    full_replay_flow_defined: Literal[True] = True
    divergence_detection_defined: Literal[True] = True
    storage_integration_defined: Literal[True] = True
    replay_api_defined: Literal[True] = True
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    c17d_modified: Literal[False] = False
    c17e_modified: Literal[False] = False
    production_runtime_changed: Literal[False] = False
    ui_integrated: Literal[False] = False
