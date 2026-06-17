from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


StorageTier = Literal["L1_hot", "L2_warm", "L3_cold"]
StorageBackend = Literal["postgresql", "redis", "s3_object_storage"]
StorageEntityType = Literal["LogEntry", "ExecutionTrace", "EventRaw"]
StorageStatus = Literal["success", "failed", "pending", "partial"]
StorageIndexKind = Literal["primary", "secondary", "search", "time_series"]

HOT_RETENTION_DAYS = 7
WARM_RETENTION_DAYS = 90
COLD_RETENTION_YEARS: tuple[int, int] = (1, 3)

STORAGE_INDEX_FIELDS: tuple[str, ...] = (
    "context_id",
    "trace_id",
    "event_id",
    "product_key",
    "user_id",
    "module",
    "timestamp",
    "status",
)
STORAGE_ADAPTER_METHODS: tuple[str, ...] = (
    "write_log(log)",
    "write_trace(trace)",
    "write_event_raw(raw_event)",
    "query_by_context_id(context_id)",
    "query_by_trace_id(trace_id)",
    "query_by_time_range(time_range)",
    "archive_to_cold_storage()",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class StorageTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime | None = None
    end_at: datetime | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_range(self) -> "StorageTimeRange":
        if self.start_at is not None and self.end_at is not None:
            if self.end_at < self.start_at:
                raise ValueError("Storage query end_at must be after start_at.")
        return self


class EventRaw(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    timestamp: datetime = Field(default_factory=utc_now)
    context_id: str = Field(min_length=1, max_length=180)
    trace_id: str | None = Field(default=None, min_length=1, max_length=180)
    product_key: str | None = Field(default=None, max_length=180)
    user_id: str | None = Field(default=None, max_length=180)
    workflow_id: str | None = Field(default=None, max_length=180)
    module: str = Field(min_length=1, max_length=180)
    event_type: str = Field(min_length=1, max_length=180)
    action: str = Field(min_length=1, max_length=240)
    source: str = Field(min_length=1, max_length=180)
    status: StorageStatus = "pending"
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def normalize_event_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def default_trace_id(self) -> "EventRaw":
        if self.trace_id is None:
            self.trace_id = self.context_id
        return self


class StorageTierDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier_id: StorageTier
    display_name: Literal["Hot Storage", "Warm Storage", "Cold Storage"]
    age_window: str = Field(min_length=1, max_length=180)
    purpose: str = Field(min_length=1, max_length=300)
    contents: tuple[str, ...]
    primary_backend: StorageBackend
    secondary_backend: StorageBackend | None = None
    compression_required: bool = False


class StorageArchitectureDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    architecture_id: Literal["c17d_storage_architecture_v1"] = (
        "c17d_storage_architecture_v1"
    )
    tiers: tuple[StorageTierDefinition, ...] = (
        StorageTierDefinition(
            tier_id="L1_hot",
            display_name="Hot Storage",
            age_window="0-7 days",
            purpose="Real-time query and fast trace debugging.",
            contents=("execution traces", "recent logs", "active context_id"),
            primary_backend="postgresql",
            secondary_backend="redis",
        ),
        StorageTierDefinition(
            tier_id="L2_warm",
            display_name="Warm Storage",
            age_window="7-90 days",
            purpose="Analysis, retrospective debugging, and statistics.",
            contents=(
                "structured logs",
                "aggregated traces",
                "module-level analytics",
            ),
            primary_backend="postgresql",
        ),
        StorageTierDefinition(
            tier_id="L3_cold",
            display_name="Cold Storage",
            age_window="90+ days",
            purpose="Compressed long-term archive and audit history.",
            contents=(
                "raw logs archive",
                "compressed execution traces",
                "audit history",
            ),
            primary_backend="s3_object_storage",
            secondary_backend="postgresql",
            compression_required=True,
        ),
    )
    long_term_storage_supported: Literal[True] = True
    high_speed_indexing_supported: Literal[True] = True
    layered_storage_strategy_defined: Literal[True] = True
    future_ready_database_design: Literal[True] = True


class StorageEntityModelDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: StorageEntityType
    source_stage: Literal["C17A", "C17B", "C17C"]
    canonical_input_model: str = Field(min_length=1, max_length=180)
    storage_record_model: str = Field(min_length=1, max_length=180)
    purpose: str = Field(min_length=1, max_length=300)
    required_index_fields: tuple[str, ...] = STORAGE_INDEX_FIELDS
    long_term_storage_supported: Literal[True] = True


class StorageDataModelDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: Literal["c17d_storage_data_models_v1"] = (
        "c17d_storage_data_models_v1"
    )
    entities: tuple[StorageEntityModelDefinition, ...] = (
        StorageEntityModelDefinition(
            entity_type="LogEntry",
            source_stage="C17B",
            canonical_input_model="backend.app.schemas.structured_logs.LogEntry",
            storage_record_model="StorageRecordEnvelope[LogEntry]",
            purpose="Indexable structured log records for query and analytics.",
        ),
        StorageEntityModelDefinition(
            entity_type="ExecutionTrace",
            source_stage="C17C",
            canonical_input_model="backend.app.schemas.execution_trace.ExecutionTrace",
            storage_record_model="StorageRecordEnvelope[ExecutionTrace]",
            purpose="Step-by-step execution chain with replay-ready metadata.",
        ),
        StorageEntityModelDefinition(
            entity_type="EventRaw",
            source_stage="C17A",
            canonical_input_model="backend.app.schemas.storage_layer.EventRaw",
            storage_record_model="StorageRecordEnvelope[EventRaw]",
            purpose="Original event stream fallback for deep debugging.",
        ),
    )
    log_entry_model_defined: Literal[True] = True
    execution_trace_model_defined: Literal[True] = True
    event_raw_model_defined: Literal[True] = True


class StorageIndexDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_name: str = Field(min_length=1, max_length=180)
    index_kind: StorageIndexKind
    fields: tuple[str, ...]
    target_entities: tuple[StorageEntityType, ...]
    backend_targets: tuple[StorageBackend, ...]
    purpose: str = Field(min_length=1, max_length=300)


class StorageIndexingStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: Literal["c17d_indexing_strategy_v1"] = (
        "c17d_indexing_strategy_v1"
    )
    primary_index: StorageIndexDefinition = StorageIndexDefinition(
        index_name="idx_c17d_context_id",
        index_kind="primary",
        fields=("context_id",),
        target_entities=("LogEntry", "ExecutionTrace", "EventRaw"),
        backend_targets=("postgresql", "redis"),
        purpose="Primary correlation lookup across logs, traces, and raw events.",
    )
    secondary_indexes: tuple[StorageIndexDefinition, ...] = (
        StorageIndexDefinition(
            index_name="idx_c17d_trace_id",
            index_kind="secondary",
            fields=("trace_id",),
            target_entities=("LogEntry", "ExecutionTrace", "EventRaw"),
            backend_targets=("postgresql", "redis"),
            purpose="Trace chain lookup and debug drill-down.",
        ),
        StorageIndexDefinition(
            index_name="idx_c17d_event_id",
            index_kind="secondary",
            fields=("event_id",),
            target_entities=("LogEntry", "ExecutionTrace", "EventRaw"),
            backend_targets=("postgresql",),
            purpose="Point lookup for exact event references.",
        ),
        StorageIndexDefinition(
            index_name="idx_c17d_product_user_status",
            index_kind="secondary",
            fields=("product_key", "user_id", "status"),
            target_entities=("LogEntry", "ExecutionTrace", "EventRaw"),
            backend_targets=("postgresql",),
            purpose="Operational filtering by product, user, and lifecycle state.",
        ),
    )
    search_index: StorageIndexDefinition = StorageIndexDefinition(
        index_name="idx_c17d_module_event_type",
        index_kind="search",
        fields=("module", "event_type"),
        target_entities=("LogEntry", "ExecutionTrace", "EventRaw"),
        backend_targets=("postgresql",),
        purpose="Search index for module-level event exploration.",
    )
    time_series_index: StorageIndexDefinition = StorageIndexDefinition(
        index_name="idx_c17d_timestamp",
        index_kind="time_series",
        fields=("timestamp",),
        target_entities=("LogEntry", "ExecutionTrace", "EventRaw"),
        backend_targets=("postgresql", "s3_object_storage"),
        purpose="Range scans, retention cutoffs, and archive batching.",
    )
    required_index_fields: tuple[str, ...] = STORAGE_INDEX_FIELDS


class StorageBackendTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: StorageBackend
    role: Literal["primary_store", "hot_cache", "cold_archive"]
    stores: tuple[StorageEntityType, ...]
    tier_coverage: tuple[StorageTier, ...]
    responsibility: str = Field(min_length=1, max_length=300)


class StorageBackendDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: Literal["c17d_backend_design_v1"] = "c17d_backend_design_v1"
    backends: tuple[StorageBackendTarget, ...] = (
        StorageBackendTarget(
            backend="postgresql",
            role="primary_store",
            stores=("LogEntry", "ExecutionTrace", "EventRaw"),
            tier_coverage=("L1_hot", "L2_warm"),
            responsibility="Durable relational store with indexed query paths.",
        ),
        StorageBackendTarget(
            backend="redis",
            role="hot_cache",
            stores=("LogEntry", "ExecutionTrace"),
            tier_coverage=("L1_hot",),
            responsibility="Short-lived cache for active context_id and trace debug.",
        ),
        StorageBackendTarget(
            backend="s3_object_storage",
            role="cold_archive",
            stores=("LogEntry", "ExecutionTrace", "EventRaw"),
            tier_coverage=("L3_cold",),
            responsibility="Compressed object batches for 1-3 year archive.",
        ),
    )
    postgresql_is_primary_storage: Literal[True] = True
    redis_is_hot_cache: Literal[True] = True
    object_storage_is_cold_archive: Literal[True] = True
    database_migration_executed: Literal[True] = True


class StorageAdapterInterfaceDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interface_id: Literal["c17d_storage_adapter_interface_v1"] = (
        "c17d_storage_adapter_interface_v1"
    )
    method_names: tuple[str, ...] = STORAGE_ADAPTER_METHODS
    supported_backends: tuple[StorageBackend, ...] = (
        "postgresql",
        "redis",
        "s3_object_storage",
    )
    input_models: tuple[StorageEntityType, ...] = (
        "LogEntry",
        "ExecutionTrace",
        "EventRaw",
    )
    api_behavior_changed: Literal[False] = False
    runtime_storage_connection_required: Literal[True] = True


class StorageRetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: Literal["c17d_retention_policy_v1"] = "c17d_retention_policy_v1"
    hot_retention_days: Literal[7] = HOT_RETENTION_DAYS
    warm_retention_days: Literal[90] = WARM_RETENTION_DAYS
    cold_retention_years: tuple[Literal[1], Literal[3]] = COLD_RETENTION_YEARS
    automatic_migration_rules: tuple[str, ...] = (
        "TTL migration job scans timestamp index for records older than 7 days.",
        "Batch archiving moves records older than 90 days into cold object storage.",
        "Compression step writes JSONL batches as compressed archive objects.",
        "PostgreSQL keeps archive metadata and query pointers for cold records.",
    )
    ttl_migration_job_defined: Literal[True] = True
    batch_archiving_defined: Literal[True] = True
    compression_step_defined: Literal[True] = True
    database_migration_executed: Literal[True] = True


class StorageWritePathDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: Literal["c17d_write_path_v1"] = "c17d_write_path_v1"
    ordered_path: tuple[
        Literal["C17A Event"],
        Literal["C17B LogEntry"],
        Literal["C17C ExecutionTrace"],
        Literal["C17D Storage Layer"],
    ] = (
        "C17A Event",
        "C17B LogEntry",
        "C17C ExecutionTrace",
        "C17D Storage Layer",
    )
    raw_event_fallback_supported: Literal[True] = True
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    api_behavior_changed: Literal[False] = False


class HotWarmColdDataFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_id: Literal["c17d_hot_warm_cold_flow_v1"] = (
        "c17d_hot_warm_cold_flow_v1"
    )
    hot_flow: tuple[str, ...] = (
        "Write recent LogEntry and ExecutionTrace records to PostgreSQL.",
        "Mirror active context_id and trace_id records into Redis cache.",
        "Serve real-time debug queries from context_id and trace_id indexes.",
    )
    warm_flow: tuple[str, ...] = (
        "TTL job moves records older than 7 days out of Redis hot cache.",
        "PostgreSQL keeps indexed structured logs and aggregated traces.",
        "Module-level analytics read warm partitions by timestamp and module.",
    )
    cold_flow: tuple[str, ...] = (
        "Batch archiver reads records older than 90 days by timestamp index.",
        "Records are serialized as JSONL batches and compressed.",
        "Compressed objects are stored in S3-compatible object storage.",
        "PostgreSQL retains archive metadata for cold query pointers.",
    )


class C17CToC17DStorageMigrationStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: Literal["c17c_to_c17d_storage_migration_v1"] = (
        "c17c_to_c17d_storage_migration_v1"
    )
    steps: tuple[str, ...] = (
        "Read C17C ExecutionTrace objects or JSONL records without changing C17C.",
        "Project trace_id, context_id, root_event_id, modules, timestamp, and status.",
        "Write projected records through StorageAdapter.write_trace().",
        "Keep C17B LogEntry writes on StorageAdapter.write_log().",
        "Store C17A EventRaw only as debugging fallback and cold archive input.",
        "Run backfill as an offline batch after schema migration is approved later.",
    )
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    database_migration_executed: Literal[True] = True
    api_behavior_changed: Literal[False] = False
    execution_replay_implemented: Literal[False] = False


class QueryPerformanceStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: Literal["c17d_query_performance_strategy_v1"] = (
        "c17d_query_performance_strategy_v1"
    )
    strategies: tuple[str, ...] = (
        "Use context_id as the primary lookup key for cross-entity correlation.",
        "Use trace_id secondary index for ExecutionTrace debug drill-down.",
        "Use module + event_type search index for operational filtering.",
        "Use timestamp time-series index for range queries and retention scans.",
        "Keep hot Redis keys aligned with PostgreSQL primary indexes.",
        "Partition warm PostgreSQL tables by timestamp when migrations are approved.",
        "Store cold archive object keys as metadata to avoid scanning object storage.",
    )
    primary_index: Literal["context_id"] = "context_id"
    secondary_index: Literal["trace_id"] = "trace_id"
    search_index: Literal["module + event_type"] = "module + event_type"
    time_series_index: Literal["timestamp"] = "timestamp"


class StorageRecordEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    entity_type: StorageEntityType
    tier: StorageTier
    backend_targets: tuple[StorageBackend, ...]
    context_id: str = Field(min_length=1, max_length=180)
    trace_id: str = Field(min_length=1, max_length=180)
    event_id: str = Field(min_length=1, max_length=180)
    product_key: str | None = Field(default=None, max_length=180)
    user_id: str | None = Field(default=None, max_length=180)
    module: str = Field(min_length=1, max_length=180)
    event_type: str = Field(min_length=1, max_length=180)
    timestamp: datetime = Field(default_factory=utc_now)
    status: StorageStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    compressed: bool = False
    archive_object_key: str | None = Field(default=None, max_length=500)

    @field_validator("timestamp")
    @classmethod
    def normalize_record_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class StorageWriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    entity_type: StorageEntityType
    tier: StorageTier
    backend_targets: tuple[StorageBackend, ...]
    context_id: str
    trace_id: str
    event_id: str
    indexed_fields: tuple[str, ...] = STORAGE_INDEX_FIELDS
    archive_object_key: str | None = None


class StorageQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: tuple[StorageRecordEnvelope, ...]
    total_count: int = Field(ge=0)
    searched_tiers: tuple[StorageTier, ...]
    indexes_used: tuple[str, ...]


class StorageArchiveResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_count: int = Field(ge=0)
    archived_count: int = Field(ge=0)
    target_backend: Literal["s3_object_storage"] = "s3_object_storage"
    compressed: Literal[True] = True
    archive_object_keys: tuple[str, ...] = Field(default_factory=tuple)


class StorageLayerCompletionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["C17D"] = "C17D"
    component: Literal["Storage Layer"] = "Storage Layer"
    completion_status: Literal["complete"] = "complete"
    storage_architecture_defined: Literal[True] = True
    data_models_defined: Literal[True] = True
    storage_adapter_interface_defined: Literal[True] = True
    indexing_strategy_defined: Literal[True] = True
    retention_policy_defined: Literal[True] = True
    hot_warm_cold_flow_defined: Literal[True] = True
    migration_strategy_defined: Literal[True] = True
    query_performance_strategy_defined: Literal[True] = True
    c17a_modified: Literal[False] = False
    c17b_modified: Literal[False] = False
    c17c_modified: Literal[False] = False
    database_migration_executed: Literal[True] = True
    api_behavior_changed: Literal[False] = False
