from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..schemas.event_collector import AuditEvent
from ..schemas.structured_logs import (
    ContextPropagationMapping,
    INDEXABLE_FIELDS,
    MODULE_TAG_MAP,
    LogEntry,
    LogEntrySchemaDefinition,
    LogEntity,
    LogMetadata,
    LogMigrationPlan,
    LogModule,
    LogNormalizerImplementationPlan,
    LogQueryModel,
    LogSource,
    LogStatus,
    LogTimeRange,
    LogStorageFormatDesign,
    ModuleTaggingTable,
    StructuredLogCompletionStatus,
    utc_now,
)
from .event_collector import normalize_context_id, sanitize_event_payload


LOG_MODULES: frozenset[str] = frozenset(MODULE_TAG_MAP)
LOG_SOURCES: frozenset[str] = frozenset(
    ("api", "n8n", "ai", "webhook", "system", "frontend", "backend")
)
STATUS_ALIASES: dict[str, LogStatus] = {
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

ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "user_id": ("user_id", "userId", "actor_id", "actorId"),
    "product_key": ("product_key", "productKey", "product", "sku"),
    "workflow_id": ("workflow_id", "workflowId", "workflow"),
    "request_id": ("request_id", "requestId", "trace_id", "traceId"),
}
CONTEXT_ALIASES: tuple[str, ...] = (
    "context_id",
    "contextId",
    "trace_id",
    "traceId",
    "correlation_id",
    "correlationId",
    "request_id",
    "requestId",
)
REQUEST_KEYS: frozenset[str] = frozenset(
    ("method", "path", "query_params", "headers", "body", "payload")
)
RESPONSE_KEYS: frozenset[str] = frozenset(
    ("status_code", "status", "result", "output", "error", "reason", "message")
)


def _raw_mapping(raw_event: AuditEvent | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw_event, AuditEvent):
        return raw_event.model_dump(mode="python")
    if isinstance(raw_event, Mapping):
        return dict(raw_event)
    raise TypeError("LogNormalizer input must be a C17A AuditEvent or mapping.")


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return sanitize_event_payload(dict(value))
    return {}


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


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
            return utc_now()
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return utc_now()


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


def _normalized_text(*values: Any) -> str:
    return " ".join(
        text.lower().replace("-", "_")
        for value in values
        if (text := _string_value(value)) is not None
    )


def _infer_module(
    *,
    raw_module: Any,
    event_type: str,
    action: str,
    source: str,
    payload: Mapping[str, Any],
) -> LogModule:
    module_text = _string_value(raw_module)
    if module_text in LOG_MODULES:
        return module_text  # type: ignore[return-value]

    text = _normalized_text(event_type, action, source, payload.get("module"))
    if any(marker in text for marker in ("structured_log", "audit", "observability")):
        return "C17"
    if any(
        marker in text
        for marker in (
            "module_switch",
            "emergency_kill_switch",
            "control_policy",
            "runtime_gate",
        )
    ):
        return "C13"
    if any(
        marker in text
        for marker in (
            "llm",
            "ai.",
            "ai_",
            "model_lock",
            "execution_prompt",
            "capability",
            "dependency",
            "allocation",
        )
    ):
        return "C14"
    if any(
        marker in text
        for marker in (
            "workflow",
            "n8n",
            "webhook",
            "callback",
            "payload_standardization",
            "result_normalization",
            "failure",
            "retry",
            "execution",
        )
    ):
        return "C15"
    if any(
        marker in text
        for marker in (
            "security",
            "auth",
            "rbac",
            "permission",
            "session",
            "control_plane",
        )
    ):
        return "C16"
    return "system"


def _normalize_source(*, raw_source: Any, event_type: str, action: str) -> LogSource:
    text = _normalized_text(event_type, action, raw_source)
    if event_type.startswith("api."):
        return "api"
    if "webhook" in text:
        return "webhook"

    source_text = _string_value(raw_source)
    if source_text in LOG_SOURCES:
        return source_text  # type: ignore[return-value]
    if "n8n" in text or "workflow" in text:
        return "n8n"
    if "ai" in text or "llm" in text:
        return "ai"
    return "system"


def _normalize_status(
    *,
    raw_status: Any,
    payload: Mapping[str, Any],
    response: Mapping[str, Any],
) -> LogStatus:
    text = _string_value(raw_status)
    if text is not None:
        normalized = text.lower().replace("-", "_").replace(" ", "_")
        if normalized in STATUS_ALIASES:
            return STATUS_ALIASES[normalized]

    status_code = response.get("status_code", payload.get("status_code"))
    try:
        if status_code is not None and int(status_code) >= 400:
            return "failed"
    except (TypeError, ValueError):
        pass
    if any(key in payload for key in ("error", "errors", "exception")):
        return "failed"
    return "pending"


def _extract_context_id(
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> str:
    candidate = _first_present((raw, payload, metadata), CONTEXT_ALIASES)
    return normalize_context_id(_string_value(candidate))


def _extract_entity(
    *,
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    context_id: str,
) -> LogEntity:
    values: dict[str, str | None] = {}
    for field_name, aliases in ENTITY_ALIASES.items():
        values[field_name] = _string_value(
            _first_present((raw, payload, metadata), aliases)
        )
    if values.get("request_id") is None:
        values["request_id"] = context_id
    return LogEntity(**values)


def _extract_metadata(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> LogMetadata:
    ip = _string_value(
        _first_present(
            (metadata, payload),
            ("ip", "client_ip", "client", "remote_addr", "remoteAddress"),
        )
    )
    user_agent = _string_value(
        _first_present((metadata, payload), ("user_agent", "userAgent"))
    )
    trace_depth = _nonnegative_int(
        _first_present((metadata, payload), ("trace_depth", "traceDepth"))
    )
    retry_count = _nonnegative_int(
        _first_present(
            (metadata, payload),
            ("retry_count", "retryCount", "attempt", "attempts"),
        )
    )
    return LogMetadata(
        ip=ip,
        user_agent=user_agent,
        trace_depth=trace_depth,
        retry_count=retry_count,
    )


def _status_code_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    response = {key: payload[key] for key in RESPONSE_KEYS if key in payload}
    return sanitize_event_payload(response)


def _request_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = {key: payload[key] for key in REQUEST_KEYS if key in payload}
    return sanitize_event_payload(request)


def _split_payload(
    *,
    event_type: str,
    status: LogStatus,
    payload: Mapping[str, Any],
    explicit_request: Mapping[str, Any],
    explicit_response: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _dict_value(explicit_request)
    response = _dict_value(explicit_response)

    payload_request = _dict_value(payload.get("request"))
    payload_response = _dict_value(payload.get("response"))
    if not request and payload_request:
        request = payload_request
    if not response and payload_response:
        response = payload_response

    event_text = event_type.lower()
    if event_type == "api.response.completed":
        if not request:
            request = _request_projection(payload)
        if not response:
            response = _status_code_response(payload)
        return request, response

    if not request and any(
        marker in event_text
        for marker in ("request", "received", "ingress", "trigger", "start")
    ):
        request = sanitize_event_payload(dict(payload))
    if not response and any(
        marker in event_text
        for marker in ("response", "completed", "egress", "callback", "end")
    ):
        response = sanitize_event_payload(dict(payload))

    if not request and not response and payload:
        if status == "pending":
            request = sanitize_event_payload(dict(payload))
        else:
            response = sanitize_event_payload(dict(payload))

    return request, response


def _generate_tags(
    *,
    context_id: str,
    module: LogModule,
    event_type: str,
    source: LogSource,
    status: LogStatus,
    entity: LogEntity,
) -> tuple[str, ...]:
    tags = [
        "c17b",
        f"context:{context_id}",
        f"module_code:{module}",
        f"module:{MODULE_TAG_MAP[module]}",
        f"source:{source}",
        f"status:{status}",
        f"event_type:{event_type}",
    ]
    if entity.user_id is not None:
        tags.append(f"user:{entity.user_id}")
    if entity.product_key is not None:
        tags.append(f"product:{entity.product_key}")
    if entity.workflow_id is not None:
        tags.append(f"workflow:{entity.workflow_id}")

    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if tag not in seen:
            deduped.append(tag)
            seen.add(tag)
    return tuple(deduped)


class LogNormalizer:
    def normalize(self, raw_event: AuditEvent | Mapping[str, Any]) -> LogEntry:
        raw = _raw_mapping(raw_event)
        payload = _dict_value(raw.get("payload"))
        metadata = _dict_value(raw.get("metadata"))
        event_type = _string_value(raw.get("event_type")) or "unknown.event"
        action = _string_value(raw.get("action")) or event_type
        source = _normalize_source(
            raw_source=raw.get("source"),
            event_type=event_type,
            action=action,
        )
        module = _infer_module(
            raw_module=raw.get("module"),
            event_type=event_type,
            action=action,
            source=source,
            payload=payload,
        )
        explicit_request = _dict_value(raw.get("request"))
        explicit_response = _dict_value(raw.get("response"))
        status = _normalize_status(
            raw_status=raw.get("status"),
            payload=payload,
            response=explicit_response,
        )
        request, response = _split_payload(
            event_type=event_type,
            status=status,
            payload=payload,
            explicit_request=explicit_request,
            explicit_response=explicit_response,
        )
        context_id = _extract_context_id(raw, payload, metadata)
        entity = _extract_entity(
            raw=raw,
            payload=payload,
            metadata=metadata,
            context_id=context_id,
        )
        log_metadata = _extract_metadata(payload, metadata)
        tags = _generate_tags(
            context_id=context_id,
            module=module,
            event_type=event_type,
            source=source,
            status=status,
            entity=entity,
        )

        return LogEntry(
            log_id=str(uuid4()),
            event_id=_string_value(raw.get("event_id")) or str(uuid4()),
            timestamp=_timestamp_value(raw.get("timestamp")),
            context_id=context_id,
            module=module,
            event_type=event_type,
            action=action,
            source=source,
            entity=entity,
            status=status,
            latency_ms=_nonnegative_float(raw.get("latency_ms")),
            request=request,
            response=response,
            metadata=log_metadata,
            tags=tags,
        )

    def normalize_many(
        self,
        raw_events: Sequence[AuditEvent | Mapping[str, Any]],
    ) -> list[LogEntry]:
        return [self.normalize(raw_event) for raw_event in raw_events]


DEFAULT_LOG_NORMALIZER = LogNormalizer()


def normalize_event_to_log_entry(raw_event: AuditEvent | Mapping[str, Any]) -> LogEntry:
    return DEFAULT_LOG_NORMALIZER.normalize(raw_event)


def normalize_events_to_log_entries(
    raw_events: Sequence[AuditEvent | Mapping[str, Any]],
) -> list[LogEntry]:
    return DEFAULT_LOG_NORMALIZER.normalize_many(raw_events)


def _require_log_entry(entry: LogEntry) -> LogEntry:
    if not isinstance(entry, LogEntry):
        raise TypeError(
            "C17B storage accepts only LogEntry; normalize C17A events first."
        )
    return entry


def log_entry_to_jsonl(entry: LogEntry) -> str:
    log_entry = _require_log_entry(entry)
    return (
        json.dumps(
            log_entry.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def log_entries_to_jsonl(entries: Sequence[LogEntry]) -> str:
    return "".join(log_entry_to_jsonl(entry) for entry in entries)


def log_entry_to_db_record(entry: LogEntry) -> dict[str, Any]:
    log_entry = _require_log_entry(entry)
    record = log_entry.model_dump(mode="json")
    record.update(
        {
            "module_tag": MODULE_TAG_MAP[log_entry.module],
            "user_id": log_entry.entity.user_id,
            "product_key": log_entry.entity.product_key,
            "workflow_id": log_entry.entity.workflow_id,
            "request_id": log_entry.entity.request_id,
            "indexable_fields": list(INDEXABLE_FIELDS),
        }
    )
    return record


def get_log_entry_schema_definition() -> LogEntrySchemaDefinition:
    return LogEntrySchemaDefinition()


def get_log_normalizer_implementation_plan() -> LogNormalizerImplementationPlan:
    return LogNormalizerImplementationPlan()


def get_context_propagation_mapping() -> ContextPropagationMapping:
    return ContextPropagationMapping()


def get_module_tagging_table() -> ModuleTaggingTable:
    return ModuleTaggingTable()


def get_log_storage_format_design() -> LogStorageFormatDesign:
    return LogStorageFormatDesign()


def get_log_query_model(
    *,
    by_context_id: str | None = None,
    by_module: LogModule | None = None,
    by_product_key: str | None = None,
    by_event_type: str | None = None,
    by_time_range: LogTimeRange | None = None,
    by_status: LogStatus | None = None,
) -> LogQueryModel:
    return LogQueryModel(
        by_context_id=by_context_id,
        by_module=by_module,
        by_product_key=by_product_key,
        by_event_type=by_event_type,
        by_time_range=by_time_range,
        by_status=by_status,
    )


def get_log_migration_plan() -> LogMigrationPlan:
    return LogMigrationPlan()


def get_structured_log_completion_status() -> StructuredLogCompletionStatus:
    return StructuredLogCompletionStatus()
