from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .execution_trace import ExecutionTrace
from .storage_layer import EventRaw, StorageEntityType, StorageTier, StorageTimeRange
from .structured_logs import LogEntry, LogModule


QueryType = Literal["search", "filter", "drill_down"]
QueryBooleanOperator = Literal["AND", "OR", "NOT"]
FilterComparator = Literal["eq", "neq", "gt", "gte", "lt", "lte", "contains", "in"]
FilterField = Literal[
    "timestamp",
    "status",
    "latency_ms",
    "action",
    "module",
    "event_type",
    "user_id",
    "product_key",
    "context_id",
    "trace_id",
]
QueryData = LogEntry | ExecutionTrace | EventRaw

REQUIRED_C17E_INDEXES: tuple[str, ...] = (
    "idx_c17d_context_id",
    "idx_c17d_trace_id",
    "idx_c17d_module_event_type",
    "idx_c17d_timestamp",
    "idx_c17d_product_user_status",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class SearchLogsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1, max_length=180)
    module: LogModule | None = None
    context_id: str | None = Field(default=None, min_length=1, max_length=180)
    event_type: str | None = Field(default=None, min_length=1, max_length=180)
    product_key: str | None = Field(default=None, min_length=1, max_length=180)
    trace_id: str | None = Field(default=None, min_length=1, max_length=180)
    time_range: StorageTimeRange | None = None
    limit: int | None = Field(default=None, ge=0)


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: FilterField
    comparator: FilterComparator = "eq"
    value: Any


class FilterExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: QueryBooleanOperator = "AND"
    conditions: tuple[FilterCondition, ...] = Field(default_factory=tuple)
    children: tuple["FilterExpression", ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def require_predicate(self) -> "FilterExpression":
        if not self.conditions and not self.children:
            raise ValueError("FilterExpression requires at least one predicate.")
        return self


class FilterSystemQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_range: StorageTimeRange | None = None
    status: str | None = Field(default=None, min_length=1, max_length=80)
    min_latency_ms: float | None = Field(default=None, ge=0)
    max_latency_ms: float | None = Field(default=None, ge=0)
    action: str | None = Field(default=None, min_length=1, max_length=240)
    module: str | None = Field(default=None, min_length=1, max_length=180)
    context_id: str | None = Field(default=None, min_length=1, max_length=180)
    trace_id: str | None = Field(default=None, min_length=1, max_length=180)
    product_key: str | None = Field(default=None, min_length=1, max_length=180)
    user_id: str | None = Field(default=None, min_length=1, max_length=180)
    event_type: str | None = Field(default=None, min_length=1, max_length=180)
    operator: QueryBooleanOperator = "AND"
    expression: FilterExpression | None = None
    entity_types: tuple[StorageEntityType, ...] = (
        "LogEntry",
        "ExecutionTrace",
        "EventRaw",
    )
    limit: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_latency_range(self) -> "FilterSystemQuery":
        if (
            self.min_latency_ms is not None
            and self.max_latency_ms is not None
            and self.max_latency_ms < self.min_latency_ms
        ):
            raise ValueError("max_latency_ms must be greater than min_latency_ms.")
        return self


class DrillDownQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_id: str | None = Field(default=None, min_length=1, max_length=180)
    trace_id: str | None = Field(default=None, min_length=1, max_length=180)
    limit: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_lookup_key(self) -> "DrillDownQuery":
        if self.context_id is None and self.trace_id is None:
            raise ValueError("drill_down requires context_id or trace_id.")
        return self


class QueryOptimizationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    query_type: QueryType
    primary_index: str = Field(min_length=1, max_length=180)
    index_used: tuple[str, ...]
    post_filters: tuple[str, ...] = Field(default_factory=tuple)
    full_scan_avoided: bool = True
    time_first_filtering: bool = False
    module_partition_pruning: bool = False
    cache_key: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=500)


class DrillDownStepBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_index: int = Field(ge=0)
    step_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=180)
    action: str = Field(min_length=1, max_length=240)
    status: str = Field(min_length=1, max_length=80)
    latency_ms: float = Field(ge=0)
    timestamp: datetime
    dependency_step_id: str | None = Field(default=None, max_length=180)
    input_keys: tuple[str, ...] = Field(default_factory=tuple)
    output_keys: tuple[str, ...] = Field(default_factory=tuple)
    error_present: bool = False

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class DrillDownChainExpansion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(min_length=1, max_length=180)
    trace_id: str = Field(min_length=1, max_length=180)
    root_event_id: str = Field(min_length=1, max_length=180)
    root_event: str = Field(min_length=1, max_length=240)
    step_count: int = Field(ge=0)
    total_latency_ms: float = Field(ge=0)
    final_status: str = Field(min_length=1, max_length=80)
    breakdown: tuple[DrillDownStepBreakdown, ...] = Field(default_factory=tuple)
    text_tree: tuple[str, ...] = Field(default_factory=tuple)


class QueryMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_type: QueryType
    index_used: tuple[str, ...]
    cache_hit: bool
    optimizer_plan_id: str | None = None
    searched_tiers: tuple[StorageTier, ...] = Field(default_factory=tuple)
    candidate_count: int = Field(default=0, ge=0)
    post_filters: tuple[str, ...] = Field(default_factory=tuple)
    full_scan_avoided: bool = True
    time_first_filtering: bool = False
    module_partition_pruning: bool = False
    drill_down: tuple[DrillDownChainExpansion, ...] = Field(default_factory=tuple)


class QueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    result_count: int = Field(ge=0)
    execution_time_ms: float = Field(ge=0)
    data: tuple[QueryData, ...]
    metadata: QueryMetadata


class AuditQueryEngineDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: Literal["c17e_audit_query_engine_v1"] = (
        "c17e_audit_query_engine_v1"
    )
    component: Literal["Audit Query Engine"] = "Audit Query Engine"
    supported_query_objects: tuple[
        Literal["LogEntry"],
        Literal["ExecutionTrace"],
        Literal["EventRaw"],
        Literal["StorageRecord"],
    ] = ("LogEntry", "ExecutionTrace", "EventRaw", "StorageRecord")
    responsibilities: tuple[str, ...] = (
        "Search logs by user, module, context, and event type.",
        "Filter system records by time, status, latency, and action.",
        "Drill down execution chains by context_id or trace_id.",
        "Normalize all outputs into QueryResult.",
    )
    c17d_storage_adapter_required: Literal[True] = True
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    c17d_modified: Literal[False] = False
    database_migration_executed: Literal[True] = True
    ui_integrated: Literal[False] = False


class SearchLogsAPIDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_id: Literal["c17e_search_logs_api_v1"] = "c17e_search_logs_api_v1"
    method_name: Literal["search_logs"] = "search_logs"
    filters: tuple[
        Literal["user_id"],
        Literal["module"],
        Literal["context_id"],
        Literal["event_type"],
    ] = ("user_id", "module", "context_id", "event_type")
    returns: Literal["QueryResult[LogEntry]"] = "QueryResult[LogEntry]"
    combines_filters_with: Literal["AND"] = "AND"


class FilterSystemLogicDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logic_id: Literal["c17e_filter_system_logic_v1"] = (
        "c17e_filter_system_logic_v1"
    )
    fields: tuple[
        Literal["time_range"],
        Literal["status"],
        Literal["latency_ms"],
        Literal["action"],
    ] = ("time_range", "status", "latency_ms", "action")
    boolean_operators: tuple[QueryBooleanOperator, ...] = ("AND", "OR", "NOT")
    returns: Literal["QueryResult[LogEntry | ExecutionTrace | EventRaw]"] = (
        "QueryResult[LogEntry | ExecutionTrace | EventRaw]"
    )


class DrillDownExecutionModelDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: Literal["c17e_drill_down_execution_model_v1"] = (
        "c17e_drill_down_execution_model_v1"
    )
    lookup_keys: tuple[Literal["context_id"], Literal["trace_id"]] = (
        "context_id",
        "trace_id",
    )
    output_parts: tuple[
        Literal["complete ExecutionTrace"],
        Literal["step-by-step breakdown"],
        Literal["C14 -> C15 -> n8n -> AI -> DB text expansion"],
    ] = (
        "complete ExecutionTrace",
        "step-by-step breakdown",
        "C14 -> C15 -> n8n -> AI -> DB text expansion",
    )
    execution_replay_implemented: Literal[False] = False


class AuditQueryIndexUsageStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: Literal["c17e_index_usage_strategy_v1"] = (
        "c17e_index_usage_strategy_v1"
    )
    required_indexes: tuple[str, ...] = REQUIRED_C17E_INDEXES
    context_lookup_index: Literal["idx_c17d_context_id"] = "idx_c17d_context_id"
    trace_lookup_index: Literal["idx_c17d_trace_id"] = "idx_c17d_trace_id"
    module_event_type_index: Literal["idx_c17d_module_event_type"] = (
        "idx_c17d_module_event_type"
    )
    timestamp_index: Literal["idx_c17d_timestamp"] = "idx_c17d_timestamp"
    product_key_index: Literal["idx_c17d_product_user_status"] = (
        "idx_c17d_product_user_status"
    )
    cold_storage_scan_allowed: Literal[False] = False


class QueryOptimizerDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    optimizer_id: Literal["c17e_query_optimizer_v1"] = "c17e_query_optimizer_v1"
    capabilities: tuple[str, ...] = (
        "Automatically select the narrowest C17D index path.",
        "Avoid unrestricted full scans.",
        "Apply timestamp index first for broad filter queries.",
        "Prune module partitions before payload predicates.",
    )
    time_first_filtering: Literal[True] = True
    module_partition_pruning: Literal[True] = True
    full_scan_avoidance: Literal[True] = True


class QueryResultSchemaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["c17e_query_result_schema_v1"] = (
        "c17e_query_result_schema_v1"
    )
    fields: tuple[
        Literal["query_id"],
        Literal["result_count"],
        Literal["execution_time_ms"],
        Literal["data"],
        Literal["metadata"],
    ] = ("query_id", "result_count", "execution_time_ms", "data", "metadata")
    metadata_fields: tuple[
        Literal["query_type"],
        Literal["index_used"],
        Literal["cache_hit"],
    ] = ("query_type", "index_used", "cache_hit")
    data_union: tuple[
        Literal["LogEntry"],
        Literal["ExecutionTrace"],
        Literal["EventRaw"],
    ] = ("LogEntry", "ExecutionTrace", "EventRaw")


class C17EStorageIntegrationDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integration_id: Literal["c17e_c17d_storage_integration_v1"] = (
        "c17e_c17d_storage_integration_v1"
    )
    storage_adapter: Literal["C17D StorageAdapter"] = "C17D StorageAdapter"
    storage_tiers: tuple[Literal["L1_hot"], Literal["L2_warm"], Literal["L3_cold"]] = (
        "L1_hot",
        "L2_warm",
        "L3_cold",
    )
    index_system: tuple[str, ...] = REQUIRED_C17E_INDEXES
    writes_to_storage: Literal[False] = False
    modifies_storage_layer: Literal[False] = False


class AuditQueryEngineCompletionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["C17E"] = "C17E"
    component: Literal["Audit Query Engine"] = "Audit Query Engine"
    completion_status: Literal["complete"] = "complete"
    audit_query_engine_defined: Literal[True] = True
    search_logs_api_defined: Literal[True] = True
    filter_system_logic_defined: Literal[True] = True
    drill_down_execution_model_defined: Literal[True] = True
    index_usage_strategy_defined: Literal[True] = True
    query_optimizer_defined: Literal[True] = True
    query_result_schema_defined: Literal[True] = True
    c17d_storage_integration_defined: Literal[True] = True
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    c17d_modified: Literal[False] = False
    database_migration_executed: Literal[True] = True
    ui_integrated: Literal[False] = False


FilterExpression.model_rebuild()
