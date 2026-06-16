from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LogModule = Literal["C13", "C14", "C15", "C16", "C17", "system"]
LogModuleTag = Literal[
    "control",
    "capability",
    "execution",
    "security",
    "observability",
    "infra",
]
LogSource = Literal[
    "api",
    "n8n",
    "ai",
    "webhook",
    "system",
    "frontend",
    "backend",
]
LogStatus = Literal["success", "failed", "pending"]
LogStorageFormat = Literal["jsonl", "future_db"]
IndexableLogField = Literal[
    "context_id",
    "timestamp",
    "module",
    "event_type",
    "product_key",
    "user_id",
]

MODULE_TAG_MAP: dict[LogModule, LogModuleTag] = {
    "C13": "control",
    "C14": "capability",
    "C15": "execution",
    "C16": "security",
    "C17": "observability",
    "system": "infra",
}
INDEXABLE_FIELDS: tuple[IndexableLogField, ...] = (
    "context_id",
    "timestamp",
    "module",
    "event_type",
    "product_key",
    "user_id",
)
LOG_ENTRY_FIELDS: tuple[str, ...] = (
    "log_id",
    "event_id",
    "timestamp",
    "context_id",
    "module",
    "event_type",
    "action",
    "source",
    "entity",
    "status",
    "latency_ms",
    "request",
    "response",
    "metadata",
    "tags",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class LogEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = None
    product_key: str | None = None
    workflow_id: str | None = None
    request_id: str | None = None


class LogMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ip: str | None = None
    user_agent: str | None = None
    trace_depth: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)


class LogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    event_id: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=utc_now)
    context_id: str = Field(min_length=1, max_length=180)
    module: LogModule
    event_type: str = Field(min_length=1, max_length=180)
    action: str = Field(min_length=1, max_length=240)
    source: LogSource
    entity: LogEntity
    status: LogStatus
    latency_ms: float = Field(default=0, ge=0)
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    metadata: LogMetadata = Field(default_factory=LogMetadata)
    tags: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not tag.strip() for tag in value):
            raise ValueError("LogEntry tags cannot contain empty values.")
        return value

    @model_validator(mode="after")
    def require_module_tag(self) -> "LogEntry":
        expected_tag = f"module:{MODULE_TAG_MAP[self.module]}"
        if expected_tag not in self.tags:
            raise ValueError("LogEntry tags must include the standardized module tag.")
        return self


class LogTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime | None = None
    end_at: datetime | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_range_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_time_range(self) -> "LogTimeRange":
        if self.start_at is not None and self.end_at is not None:
            if self.end_at < self.start_at:
                raise ValueError("Log query end_at must be after start_at.")
        return self


class LogQueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_model_id: Literal["c17b_log_query_model_v1"] = (
        "c17b_log_query_model_v1"
    )
    by_context_id: str | None = Field(default=None, min_length=1, max_length=180)
    by_module: LogModule | None = None
    by_product_key: str | None = Field(default=None, min_length=1, max_length=180)
    by_event_type: str | None = Field(default=None, min_length=1, max_length=180)
    by_time_range: LogTimeRange | None = None
    by_status: LogStatus | None = None
    indexable_fields: tuple[IndexableLogField, ...] = INDEXABLE_FIELDS
    default_storage_format: Literal["jsonl"] = "jsonl"
    future_db_ingestion_ready: Literal[True] = True


class LogEntrySchemaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["c17b_log_entry_schema_v1"] = "c17b_log_entry_schema_v1"
    canonical_model: Literal["LogEntry"] = "LogEntry"
    fields: tuple[str, ...] = LOG_ENTRY_FIELDS
    module_values: tuple[LogModule, ...] = (
        "C13",
        "C14",
        "C15",
        "C16",
        "C17",
        "system",
    )
    source_values: tuple[LogSource, ...] = (
        "api",
        "n8n",
        "ai",
        "webhook",
        "system",
        "frontend",
        "backend",
    )
    status_values: tuple[LogStatus, ...] = ("success", "failed", "pending")
    entity_fields: tuple[
        Literal["user_id"],
        Literal["product_key"],
        Literal["workflow_id"],
        Literal["request_id"],
    ] = ("user_id", "product_key", "workflow_id", "request_id")
    metadata_fields: tuple[
        Literal["ip"],
        Literal["user_agent"],
        Literal["trace_depth"],
        Literal["retry_count"],
    ] = ("ip", "user_agent", "trace_depth", "retry_count")
    raw_event_storage_allowed: Literal[False] = False


class LogNormalizerImplementationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: Literal["c17b_log_normalizer_v1"] = "c17b_log_normalizer_v1"
    input_model: Literal["C17A AuditEvent | Mapping"] = "C17A AuditEvent | Mapping"
    output_model: Literal["LogEntry"] = "LogEntry"
    responsibilities: tuple[
        Literal["schema enforcement"],
        Literal["missing field filling"],
        Literal["tag generation"],
        Literal["module inference"],
        Literal["status normalization"],
    ] = (
        "schema enforcement",
        "missing field filling",
        "tag generation",
        "module inference",
        "status normalization",
    )
    raw_event_storage_allowed: Literal[False] = False
    c17a_logic_modified: Literal[False] = False
    hook_system_modified: Literal[False] = False
    api_behavior_changed: Literal[False] = False


class ContextPropagationMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_id: Literal["c17b_context_propagation_v1"] = (
        "c17b_context_propagation_v1"
    )
    root_rule: Literal["context_id = request root trace id"] = (
        "context_id = request root trace id"
    )
    propagation_path: tuple[
        Literal["frontend_request"],
        Literal["backend"],
        Literal["control-plane"],
        Literal["n8n"],
        Literal["AI"],
        Literal["storage"],
    ] = (
        "frontend_request",
        "backend",
        "control-plane",
        "n8n",
        "AI",
        "storage",
    )
    inherited_by_all_log_entries: Literal[True] = True
    ai_n8n_webhook_consistency_required: Literal[True] = True


class ModuleTaggingTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: Literal["c17b_module_tagging_v1"] = "c17b_module_tagging_v1"
    module_tags: dict[LogModule, LogModuleTag] = Field(
        default_factory=lambda: dict(MODULE_TAG_MAP)
    )
    tag_location: Literal["LogEntry.tags"] = "LogEntry.tags"
    module_code_preserved_for_indexing: Literal[True] = True


class LogStorageFormatDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: Literal["c17b_storage_format_v1"] = "c17b_storage_format_v1"
    default_format: Literal["JSONL"] = "JSONL"
    supported_formats: tuple[Literal["JSONL"], Literal["future DB ingestion"]] = (
        "JSONL",
        "future DB ingestion",
    )
    indexable_fields: tuple[IndexableLogField, ...] = INDEXABLE_FIELDS
    raw_event_storage_allowed: Literal[False] = False


class LogMigrationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: Literal["c17a_to_c17b_structured_log_migration_v1"] = (
        "c17a_to_c17b_structured_log_migration_v1"
    )
    steps: tuple[str, ...] = (
        "Read C17A AuditEvent records from the existing collector buffer or "
        "structured logger stream.",
        "Normalize each raw event with LogNormalizer before any C17B storage write.",
        "Write only LogEntry JSONL records as the default storage artifact.",
        "Expose flattened index fields for future DB ingestion without executing "
        "a database migration.",
        "Backfill historical raw event files by streaming line by line through LogNormalizer.",
        "Reject direct raw event storage in C17B storage helpers.",
    )
    database_migration_executed: Literal[False] = False
    c17a_logic_modified: Literal[False] = False
    hook_system_modified: Literal[False] = False
    api_behavior_changed: Literal[False] = False
    new_business_logic_introduced: Literal[False] = False


class StructuredLogCompletionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["C17B"] = "C17B"
    component: Literal["Structured Log Schema"] = "Structured Log Schema"
    completion_status: Literal["complete"] = "complete"
    log_entry_schema_defined: Literal[True] = True
    log_normalizer_defined: Literal[True] = True
    context_id_propagation_mapping_defined: Literal[True] = True
    module_tagging_table_defined: Literal[True] = True
    jsonl_storage_format_defined: Literal[True] = True
    query_model_defined: Literal[True] = True
    migration_plan_defined: Literal[True] = True
    raw_event_storage_allowed: Literal[False] = False
