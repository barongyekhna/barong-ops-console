from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .execution_trace import ExecutionTrace
from .structured_logs import LogEntry


AnomalyType = Literal["behavior", "rate", "security"]
AnomalyEntityType = Literal["user", "api", "workflow", "context"]
AnomalySeverity = Literal["low", "medium", "high", "critical"]
DetectionMode = Literal["streaming", "batch", "replay"]
BaselineScope = Literal["user", "module", "workflow", "context"]

ANOMALY_ENGINE_METHODS: tuple[str, ...] = (
    "analyze_log_stream()",
    "analyze_trace_patterns()",
    "analyze_rate_patterns()",
    "detect_security_violations()",
)
ANOMALY_INPUT_SOURCES: tuple[str, ...] = (
    "C17A Event Logs",
    "C17B Structured Logs",
    "C17C Execution Traces",
    "C17D Storage Layer",
    "C17E Query Results",
    "C17F Replay Comparisons",
)
ANOMALY_SCORE_FIELDS: tuple[str, ...] = (
    "entity_id",
    "entity_type",
    "scores",
    "total_score",
    "severity",
)
ALERT_FIELDS: tuple[str, ...] = (
    "alert_id",
    "anomaly_type",
    "severity",
    "related_context_id",
    "related_trace_id",
    "description",
    "evidence",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def severity_for_score(score: float) -> AnomalySeverity:
    if score < 30:
        return "low"
    if score < 60:
        return "medium"
    if score < 80:
        return "high"
    return "critical"


class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    behavior_score: float = Field(default=0, ge=0, le=100)
    rate_score: float = Field(default=0, ge=0, le=100)
    security_score: float = Field(default=0, ge=0, le=100)


class AnomalyScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1, max_length=240)
    entity_type: AnomalyEntityType
    scores: ScoreBreakdown
    total_score: float = Field(ge=0, le=100)
    severity: AnomalySeverity

    @model_validator(mode="after")
    def validate_severity_band(self) -> "AnomalyScore":
        expected = severity_for_score(self.total_score)
        if self.severity != expected:
            raise ValueError("AnomalyScore severity must match total_score.")
        return self


class ReplayDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replay_id: str = Field(min_length=1, max_length=240)
    original_trace_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    divergence_detected: bool
    divergence_points: tuple[str, ...] = Field(default_factory=tuple)
    comparison_summary: str = Field(min_length=1, max_length=800)


AlertEvidence = LogEntry | ExecutionTrace | ReplayDiff


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_id: str = Field(default_factory=lambda: f"alert-{uuid4()}", min_length=1)
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    related_context_id: str | None = Field(default=None, max_length=180)
    related_trace_id: str | None = Field(default=None, max_length=180)
    description: str = Field(min_length=1, max_length=1000)
    evidence: tuple[AlertEvidence, ...] = Field(default_factory=tuple)


class BaselineProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1, max_length=240)
    scope: BaselineScope
    request_rate_per_minute: float = Field(default=0, ge=0)
    context_rate_per_minute: float = Field(default=0, ge=0)
    retry_rate_per_minute: float = Field(default=0, ge=0)
    security_event_rate_per_minute: float = Field(default=0, ge=0)
    allowed_api_paths: tuple[str, ...] = Field(default_factory=tuple)
    allowed_workflows: tuple[str, ...] = Field(default_factory=tuple)
    allowed_modules: tuple[str, ...] = Field(default_factory=tuple)
    action_patterns: tuple[str, ...] = Field(default_factory=tuple)
    module_sequence_patterns: tuple[tuple[str, ...], ...] = Field(
        default_factory=tuple
    )
    sample_count: int = Field(default=0, ge=0)

    @field_validator(
        "allowed_api_paths",
        "allowed_workflows",
        "allowed_modules",
        "action_patterns",
    )
    @classmethod
    def reject_empty_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("BaselineProfile collections cannot contain blanks.")
        return tuple(dict.fromkeys(value))


class BaselineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: dict[str, BaselineProfile] = Field(default_factory=dict)
    modules: dict[str, BaselineProfile] = Field(default_factory=dict)
    workflows: dict[str, BaselineProfile] = Field(default_factory=dict)
    contexts: dict[str, BaselineProfile] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class AnomalyFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(default_factory=lambda: f"finding-{uuid4()}", min_length=1)
    anomaly_type: AnomalyType
    entity_id: str = Field(min_length=1, max_length=240)
    entity_type: AnomalyEntityType
    rule_id: str = Field(min_length=1, max_length=180)
    score: AnomalyScore
    alert: Alert
    detection_mode: DetectionMode


class AnomalyDetectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(default_factory=lambda: f"anomaly-{uuid4()}", min_length=1)
    detection_mode: DetectionMode
    scores: tuple[AnomalyScore, ...] = Field(default_factory=tuple)
    alerts: tuple[Alert, ...] = Field(default_factory=tuple)
    findings: tuple[AnomalyFinding, ...] = Field(default_factory=tuple)
    analyzed_log_count: int = Field(default=0, ge=0)
    analyzed_trace_count: int = Field(default=0, ge=0)
    analyzed_replay_diff_count: int = Field(default=0, ge=0)
    baseline_model: BaselineModel = Field(default_factory=BaselineModel)


class AnomalyDetectionEngineDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: Literal["c17g_anomaly_detection_engine_v1"] = (
        "c17g_anomaly_detection_engine_v1"
    )
    component: Literal["Anomaly Detection Engine"] = "Anomaly Detection Engine"
    methods: tuple[str, ...] = ANOMALY_ENGINE_METHODS
    input_sources: tuple[str, ...] = ANOMALY_INPUT_SOURCES
    responsibilities: tuple[str, ...] = (
        "Detect behavior anomalies from logs, traces, and replay diffs.",
        "Detect rate anomalies with rolling windows and baseline comparison.",
        "Detect security anomalies from control-plane, RBAC, webhook, session, and AI signals.",
        "Emit AnomalyScore and Alert records without changing production runtime.",
    )
    streaming_detection_supported: Literal[True] = True
    batch_detection_supported: Literal[True] = True
    replay_based_detection_supported: Literal[True] = True
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    c17d_modified: Literal[False] = False
    c17e_modified: Literal[False] = False
    c17f_modified: Literal[False] = False
    production_runtime_changed: Literal[False] = False
    api_contract_changed: Literal[False] = False
    database_migration_executed: Literal[False] = False
    ui_integrated: Literal[False] = False


class AnomalyCategoryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anomaly_type: AnomalyType
    detects: tuple[str, ...]
    primary_inputs: tuple[str, ...]
    scoring_component: Literal[
        "behavior_score",
        "rate_score",
        "security_score",
    ]


class AnomalyClassificationSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification_id: Literal["c17g_anomaly_classification_v1"] = (
        "c17g_anomaly_classification_v1"
    )
    categories: tuple[AnomalyCategoryDefinition, ...] = (
        AnomalyCategoryDefinition(
            anomaly_type="behavior",
            detects=(
                "non-normal API call paths",
                "atypical workflow calls",
                "unexpected C13/C14/C15 module usage",
                "unusual execution chain patterns",
            ),
            primary_inputs=(
                "C17B Structured Logs",
                "C17C Execution Traces",
                "C17F Replay Comparisons",
            ),
            scoring_component="behavior_score",
        ),
        AnomalyCategoryDefinition(
            anomaly_type="rate",
            detects=(
                "burst traffic",
                "high-frequency user_id calls",
                "context_id flood",
                "C15H workflow retry storm",
            ),
            primary_inputs=(
                "C17A Event Logs",
                "C17B Structured Logs",
                "C17D Storage Layer",
                "C17E Query Results",
            ),
            scoring_component="rate_score",
        ),
        AnomalyCategoryDefinition(
            anomaly_type="security",
            detects=(
                "unauthorized control-plane access attempts",
                "RBAC bypass attempts",
                "webhook replay abuse",
                "invalid session patterns",
                "abnormal AI prompt injection patterns",
            ),
            primary_inputs=(
                "C17A Event Logs",
                "C17B Structured Logs",
                "C17C Execution Traces",
            ),
            scoring_component="security_score",
        ),
    )


class AnomalyScoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: Literal["c17g_anomaly_scoring_v1"] = "c17g_anomaly_scoring_v1"
    score_schema_fields: tuple[str, ...] = ANOMALY_SCORE_FIELDS
    component_scores: tuple[
        Literal["behavior_score"],
        Literal["rate_score"],
        Literal["security_score"],
    ] = ("behavior_score", "rate_score", "security_score")
    total_score_rule: Literal[
        "total_score = max(behavior_score, rate_score, security_score)"
    ] = "total_score = max(behavior_score, rate_score, security_score)"
    score_min: Literal[0] = 0
    score_max: Literal[100] = 100


class BaselineModelDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: Literal["c17g_baseline_model_v1"] = "c17g_baseline_model_v1"
    baseline_scopes: tuple[BaselineScope, ...] = (
        "user",
        "module",
        "workflow",
        "context",
    )
    baseline_fields: tuple[str, ...] = (
        "request_rate_per_minute",
        "context_rate_per_minute",
        "retry_rate_per_minute",
        "security_event_rate_per_minute",
        "allowed_api_paths",
        "allowed_workflows",
        "allowed_modules",
        "action_patterns",
        "module_sequence_patterns",
    )
    deviation_rule: Literal["deviation = current - baseline"] = (
        "deviation = current - baseline"
    )
    rolling_window_analysis_supported: Literal[True] = True


class AlertSystemSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["c17g_alert_schema_v1"] = "c17g_alert_schema_v1"
    fields: tuple[str, ...] = ALERT_FIELDS
    evidence_models: tuple[
        Literal["LogEntry"],
        Literal["ExecutionTrace"],
        Literal["ReplayDiff"],
    ] = ("LogEntry", "ExecutionTrace", "ReplayDiff")
    emitted_by_detection_engine: Literal[True] = True
    writes_to_database: Literal[False] = False
    changes_api_contract: Literal[False] = False


class IntegrationArchitecture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    architecture_id: Literal["c17g_integration_architecture_v1"] = (
        "c17g_integration_architecture_v1"
    )
    reads_from: tuple[str, ...] = ANOMALY_INPUT_SOURCES
    c17c_execution_trace_usage: Literal["behavior analysis"] = "behavior analysis"
    c17d_storage_layer_usage: Literal["data source"] = "data source"
    c17e_query_engine_usage: Literal["filter support"] = "filter support"
    c17f_replay_system_usage: Literal["diff-based anomaly detection"] = (
        "diff-based anomaly detection"
    )
    writes_to_upstream_stages: Literal[False] = False


class DetectionPipelineFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_id: Literal["c17g_detection_pipeline_v1"] = "c17g_detection_pipeline_v1"
    ordered_flow: tuple[str, ...] = (
        "Ingest C17A/C17B/C17C records from C17D or C17E query results.",
        "Normalize records into logs, traces, and replay diffs.",
        "Load per user/module/workflow/context baselines.",
        "Run behavior, rate, and security detectors.",
        "Compute AnomalyScore and severity.",
        "Emit Alert with evidence and correlation identifiers.",
    )
    streaming_path: tuple[str, ...] = (
        "append event to rolling window",
        "compare current window rate to baseline",
        "emit alert immediately when thresholds are crossed",
    )
    batch_path: tuple[str, ...] = (
        "read historical slice",
        "group by entity",
        "compare against stored baseline",
        "return deterministic result bundle",
    )
    replay_path: tuple[str, ...] = (
        "read C17F replay comparison",
        "convert divergence points to ReplayDiff",
        "score behavior/security/rate anomalies",
    )


class SeverityBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: AnomalySeverity
    min_score: int = Field(ge=0, le=100)
    max_score: int = Field(ge=0, le=100)


class SeverityRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules_id: Literal["c17g_severity_rules_v1"] = "c17g_severity_rules_v1"
    bands: tuple[SeverityBand, ...] = (
        SeverityBand(severity="low", min_score=0, max_score=30),
        SeverityBand(severity="medium", min_score=30, max_score=60),
        SeverityBand(severity="high", min_score=60, max_score=80),
        SeverityBand(severity="critical", min_score=80, max_score=100),
    )
    boundary_rule: Literal[
        "30 is medium, 60 is high, and 80 is critical"
    ] = "30 is medium, 60 is high, and 80 is critical"


class AnomalyDetectionCompletionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["C17G"] = "C17G"
    component: Literal["Anomaly Detection Layer"] = "Anomaly Detection Layer"
    completion_status: Literal["complete"] = "complete"
    anomaly_detection_engine_defined: Literal[True] = True
    anomaly_classification_defined: Literal[True] = True
    scoring_model_defined: Literal[True] = True
    baseline_model_defined: Literal[True] = True
    alert_system_schema_defined: Literal[True] = True
    integration_architecture_defined: Literal[True] = True
    detection_pipeline_flow_defined: Literal[True] = True
    severity_rules_defined: Literal[True] = True
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    c17d_modified: Literal[False] = False
    c17e_modified: Literal[False] = False
    c17f_modified: Literal[False] = False
    production_runtime_changed: Literal[False] = False
    api_contract_changed: Literal[False] = False
    database_migration_executed: Literal[False] = False
    ui_integrated: Literal[False] = False
