from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas.event_collector import AuditEvent
from backend.app.schemas.structured_logs import LogTimeRange, MODULE_TAG_MAP
from backend.app.services.structured_logs import (
    get_context_propagation_mapping,
    get_log_entry_schema_definition,
    get_log_migration_plan,
    get_log_normalizer_implementation_plan,
    get_log_query_model,
    get_log_storage_format_design,
    get_module_tagging_table,
    get_structured_log_completion_status,
    log_entry_to_db_record,
    log_entry_to_jsonl,
    normalize_event_to_log_entry,
)


def test_c17b_design_models_cover_required_outputs() -> None:
    schema = get_log_entry_schema_definition()
    plan = get_log_normalizer_implementation_plan()
    context_mapping = get_context_propagation_mapping()
    module_tags = get_module_tagging_table()
    storage = get_log_storage_format_design()
    query = get_log_query_model(
        by_context_id="ctx-c17b",
        by_module="C17",
        by_product_key="product.demo",
        by_event_type="audit.event.normalized",
        by_status="success",
    )
    migration = get_log_migration_plan()
    completion = get_structured_log_completion_status()

    assert schema.canonical_model == "LogEntry"
    assert schema.raw_event_storage_allowed is False
    assert set(schema.fields) == {
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
    }
    assert plan.responsibilities == (
        "schema enforcement",
        "missing field filling",
        "tag generation",
        "module inference",
        "status normalization",
    )
    assert context_mapping.root_rule == "context_id = request root trace id"
    assert context_mapping.propagation_path == (
        "frontend_request",
        "backend",
        "control-plane",
        "n8n",
        "AI",
        "storage",
    )
    assert module_tags.module_tags == MODULE_TAG_MAP
    assert storage.default_format == "JSONL"
    assert storage.indexable_fields == (
        "context_id",
        "timestamp",
        "module",
        "event_type",
        "product_key",
        "user_id",
    )
    assert query.by_context_id == "ctx-c17b"
    assert query.by_module == "C17"
    assert query.by_status == "success"
    assert migration.database_migration_executed is False
    assert migration.c17a_logic_modified is False
    assert completion.completion_status == "complete"


def test_c17b_normalizes_c17a_audit_event_to_log_entry() -> None:
    event = AuditEvent(
        event_id="evt-c17a-001",
        timestamp=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        event_type="api.response.completed",
        module="C15",
        action="POST /api/control-plane/webhook-gateway",
        context_id="ctx-root-trace",
        user_id="42",
        product_key="product.demo",
        workflow_id="workflow.demo",
        source="backend",
        status="success",
        latency_ms=12.5,
        payload={
            "method": "POST",
            "path": "/api/control-plane/webhook-gateway",
            "status_code": 200,
            "api_key": "unsafe-secret",
        },
        metadata={
            "client": "10.0.0.8",
            "user_agent": "pytest",
            "trace_depth": 4,
            "retry_count": 1,
        },
    )

    entry = normalize_event_to_log_entry(event)

    assert entry.log_id != event.event_id
    assert entry.event_id == "evt-c17a-001"
    assert entry.context_id == "ctx-root-trace"
    assert entry.module == "C15"
    assert entry.source == "api"
    assert entry.status == "success"
    assert entry.entity.user_id == "42"
    assert entry.entity.product_key == "product.demo"
    assert entry.entity.workflow_id == "workflow.demo"
    assert entry.entity.request_id == "ctx-root-trace"
    assert entry.request == {
        "method": "POST",
        "path": "/api/control-plane/webhook-gateway",
    }
    assert entry.response == {"status_code": 200}
    assert entry.metadata.ip == "10.0.0.8"
    assert entry.metadata.user_agent == "pytest"
    assert entry.metadata.trace_depth == 4
    assert entry.metadata.retry_count == 1
    assert "module:execution" in entry.tags
    assert "source:api" in entry.tags
    assert "status:success" in entry.tags

    jsonl = log_entry_to_jsonl(entry)
    serialized = json.loads(jsonl)
    assert serialized["context_id"] == "ctx-root-trace"
    assert "unsafe-secret" not in jsonl

    db_record = log_entry_to_db_record(entry)
    assert db_record["context_id"] == "ctx-root-trace"
    assert db_record["module_tag"] == "execution"
    assert db_record["product_key"] == "product.demo"
    assert db_record["user_id"] == "42"
    assert db_record["indexable_fields"] == [
        "context_id",
        "timestamp",
        "module",
        "event_type",
        "product_key",
        "user_id",
    ]


def test_c17b_fills_missing_fields_and_infers_module_source_and_status() -> None:
    raw_event = {
        "event_type": "webhook.gateway.ingress",
        "action": "gateway ingress",
        "source": "backend",
        "status": "queued",
        "latency_ms": -10,
        "payload": {
            "context_id": "ctx-webhook-root",
            "workflow_id": "workflow.webhook.demo",
            "product_key": "product.webhook",
            "request": {"body": {"ok": True}},
        },
        "metadata": {"attempt": 2},
    }

    entry = normalize_event_to_log_entry(raw_event)

    assert entry.event_id
    assert entry.context_id == "ctx-webhook-root"
    assert entry.module == "C15"
    assert entry.source == "webhook"
    assert entry.status == "pending"
    assert entry.latency_ms == 0
    assert entry.entity.workflow_id == "workflow.webhook.demo"
    assert entry.entity.product_key == "product.webhook"
    assert entry.entity.request_id == "ctx-webhook-root"
    assert entry.request == {"body": {"ok": True}}
    assert entry.metadata.retry_count == 2
    assert "module:execution" in entry.tags


def test_c17b_storage_rejects_raw_c17a_event() -> None:
    raw_event = AuditEvent(
        event_type="unit.test",
        module="system",
        action="unit.test",
        context_id="ctx-unit",
        source="backend",
        status="success",
    )

    with pytest.raises(TypeError, match="normalize C17A events first"):
        log_entry_to_jsonl(raw_event)  # type: ignore[arg-type]


def test_c17b_query_model_validates_time_range() -> None:
    time_range = LogTimeRange(
        start_at=datetime(2026, 6, 16, 10, 0),
        end_at=datetime(2026, 6, 16, 11, 0),
    )
    query = get_log_query_model(by_time_range=time_range, by_status="failed")

    assert query.by_time_range is not None
    assert query.by_time_range.start_at is not None
    assert query.by_time_range.start_at.tzinfo == UTC
    assert query.by_status == "failed"

    with pytest.raises(ValidationError):
        LogTimeRange(
            start_at=datetime(2026, 6, 16, 11, 0),
            end_at=datetime(2026, 6, 16, 10, 0),
        )
