from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.app.main import app
from backend.app.schemas.execution_payload_standardization import (
    ExecutionPayloadMetadata,
    ExecutionPayloadStandardRequest,
)
from backend.app.services.execution_payload_standardization import (
    CONTEXT_ID_PATTERN,
    get_context_standardization_rules,
    get_execution_payload_completion_status,
    get_normalization_engine_design,
    get_payload_standardization_model,
    get_workflow_mapping_integration,
    normalize_execution_payload_request,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def c15c_workflow(**updates: Any) -> dict[str, Any]:
    workflow = {
        "workflow_id": "n8n.workflow.business.products.dispatch.v1",
        "module": "business.products",
        "trigger": "webhook",
        "status": "active",
        "n8n_webhook": (
            "n8n-webhook-ref://c15a/business.products/dispatch/v1"
        ),
        "version": "1.0.0",
        "created_at": "2026-06-15T00:00:00Z",
        "updated_at": "2026-06-15T00:00:00Z",
    }
    workflow.update(updates)
    return workflow


def c14x_a_binding(**updates: Any) -> dict[str, Any]:
    binding = {
        "key": "ai.binding.reasoning.primary",
        "model": "model.reasoning.primary_v1",
        "capability": "reasoning",
        "module": "business.products",
        "status": "active",
        "reason": "Explicit C14X-A route declaration for contract inspection.",
    }
    binding.update(updates)
    return binding


def c14x_b_lock(**updates: Any) -> dict[str, Any]:
    lock = {
        "key_id": "ai.binding.reasoning.primary",
        "model_id": "model.reasoning.primary_v1",
        "locked": True,
        "lock_timestamp": "2026-06-15T00:00:00Z",
        "lock_reason": "C14X-B immutable model lock for C14X-A binding.",
    }
    lock.update(updates)
    return lock


def c14x_c_capability_binding(**updates: Any) -> dict[str, Any]:
    binding = {
        "capability": "reasoning",
        "key": "ai.binding.reasoning.primary",
        "model": "model.reasoning.primary_v1",
        "module": "business.products",
        "status": "active",
        "reason": "Explicit C14X-C capability binding for inspection.",
    }
    binding.update(updates)
    return binding


def c14x_c_module_binding(**updates: Any) -> dict[str, Any]:
    binding = {
        "module": "business.products",
        "allowed_capabilities": ("reasoning",),
        "status": "active",
        "reason": "Explicit C14X-C module capability allow binding.",
    }
    binding.update(updates)
    return binding


def test_c15c_standard_model_engine_context_mapping_and_status() -> None:
    model = get_payload_standardization_model()
    engine = get_normalization_engine_design()
    context_rules = get_context_standardization_rules()
    workflow_mapping = get_workflow_mapping_integration()
    completion = get_execution_payload_completion_status()

    assert model.required_fields == (
        "module",
        "task",
        "context_id",
        "workflow_id",
        "execution",
        "payload",
        "timestamp",
    )
    assert model.execution_shape == ("capability", "model", "key_id")
    assert model.execution_metadata_caller_override_allowed is False
    assert engine.workflow_mapping_source == "C15A registry"
    assert engine.execution_metadata_source == "C14X capability binding engine"
    assert engine.runtime_execution_allowed is False
    assert context_rules.context_id_pattern == "^ctx\\.c15c\\.[0-9a-f]{16}$"
    assert context_rules.module_specific_context_format_allowed is False
    assert workflow_mapping.mapping_rule == "module -> active workflow_id"
    assert workflow_mapping.validate_workflow_exists is True
    assert workflow_mapping.invalid_mapping_behavior == "reject_without_fallback"
    assert completion.completion_status == "complete"
    assert completion.can_proceed_to_c15d is True
    assert completion.no_production_or_staging_change is True


def test_c15c_standard_request_schema_matches_required_shape() -> None:
    assert set(ExecutionPayloadStandardRequest.model_fields) == {
        "module",
        "task",
        "context_id",
        "workflow_id",
        "execution",
        "payload",
        "timestamp",
    }
    assert set(ExecutionPayloadMetadata.model_fields) == {
        "capability",
        "model",
        "key_id",
    }


def test_c15c_normalizes_module_request_with_c15a_and_c14x_metadata() -> None:
    result = normalize_execution_payload_request(
        {
            "module_key": "business.products",
            "action": "business.products.placeholder.prepare",
            "context": {"legacy_product_context": "product-42"},
            "payload": {"draft": {"title": "Static test"}},
            "timestamp": "2026-06-15T00:00:00Z",
        },
        raw_workflows=[c15c_workflow()],
        raw_ai_bindings=[c14x_a_binding()],
        raw_locks=[c14x_b_lock()],
        raw_capability_bindings=[c14x_c_capability_binding()],
        raw_module_bindings=[c14x_c_module_binding()],
    )

    assert result.normalization_status == "accepted"
    assert result.workflow_mapping_validated is True
    assert result.execution_metadata_attached is True
    assert result.context_standardized is True
    assert result.standardized_request_schema_valid is True
    assert result.standardized_request is not None
    assert result.standardized_request.module == "business.products"
    assert result.standardized_request.task == (
        "business.products.placeholder.prepare"
    )
    assert result.standardized_request.workflow_id == (
        "n8n.workflow.business.products.dispatch.v1"
    )
    assert CONTEXT_ID_PATTERN.fullmatch(result.standardized_request.context_id)
    assert result.standardized_request.execution.capability == "reasoning"
    assert result.standardized_request.execution.model == (
        "model.reasoning.primary_v1"
    )
    assert result.standardized_request.execution.key_id == (
        "ai.binding.reasoning.primary"
    )
    assert result.trace_chain is not None
    assert result.trace_chain.traceable_execution_chain is True
    assert result.runtime_execution_allowed is False
    assert result.n8n_dispatch_performed is False
    assert result.model_invocation_allowed is False
    assert result.external_api_call_allowed is False


def test_c15c_default_registry_rejects_missing_c14x_execution_metadata() -> None:
    result = normalize_execution_payload_request(
        {
            "module": "integration.n8n_test_bridge",
            "task": "integration.n8n_test_bridge.test_run.declare",
            "context_id": "n8n-test:legacy:1",
            "payload": {"mock_only": True},
            "timestamp": "2026-06-15T00:00:00Z",
        }
    )

    assert result.normalization_status == "rejected"
    assert "C14X" in result.reason
    assert result.workflow_mapping_validated is True
    assert result.workflow_id == (
        "n8n.workflow.integration.n8n_test_bridge.dispatch.v1"
    )
    assert result.execution_metadata_attached is False
    assert result.standardized_request is None
    assert result.context_id is not None
    assert CONTEXT_ID_PATTERN.fullmatch(result.context_id)
    assert result.runtime_execution_allowed is False


def test_c15c_rejects_invalid_workflow_mapping_and_caller_execution_metadata() -> None:
    wrong_workflow = c15c_workflow(
        workflow_id="n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
        module="integration.n8n_test_bridge",
        n8n_webhook=(
            "n8n-webhook-ref://c15a/integration.n8n_test_bridge/"
            "dispatch/v1"
        ),
    )
    invalid_mapping = normalize_execution_payload_request(
        {
            "module": "business.products",
            "task": "business.products.placeholder.prepare",
            "context_id": "products:legacy:1",
            "workflow_id": "n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
            "payload": {"draft": True},
            "timestamp": "2026-06-15T00:00:00Z",
        },
        raw_workflows=[c15c_workflow(), wrong_workflow],
    )
    caller_execution = normalize_execution_payload_request(
        {
            "module": "business.products",
            "task": "business.products.placeholder.prepare",
            "context_id": "products:legacy:1",
            "execution": {"model": "model.reasoning.primary_v1"},
            "payload": {"draft": True},
            "timestamp": "2026-06-15T00:00:00Z",
        },
        raw_workflows=[c15c_workflow()],
    )

    assert invalid_mapping.normalization_status == "rejected"
    assert invalid_mapping.c15a_registered is True
    assert invalid_mapping.c15a_bound_to_module is False
    assert invalid_mapping.workflow_mapping_validated is False
    assert invalid_mapping.standardized_request is None
    assert caller_execution.normalization_status == "rejected"
    assert "C14X" in caller_execution.reason
    assert caller_execution.workflow_mapping_validated is False


def test_c15c_router_exposes_only_standardization_and_normalization_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith(
            "/api/control-plane/payload-standardization"
        )
    ]

    assert ("/api/control-plane/payload-standardization/normalize", {"POST"}) in routes
    assert ("/api/control-plane/payload-standardization/model", {"GET"}) in routes
    assert ("/api/control-plane/payload-standardization/normalization-engine", {"GET"}) in routes
    assert ("/api/control-plane/payload-standardization/context-rules", {"GET"}) in routes
    assert ("/api/control-plane/payload-standardization/workflow-mapping", {"GET"}) in routes
    assert ("/api/control-plane/payload-standardization/completion-status", {"GET"}) in routes
    assert not any(
        methods & {"PUT", "PATCH", "DELETE"} for _, methods in routes
    )
    assert not any(
        methods & {"POST"} and path != "/api/control-plane/payload-standardization/normalize"
        for path, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke|n8n)\b", path)
        for path, _ in routes
    )


def test_c15c_implementation_has_no_runtime_http_client_or_gateway_dispatch() -> None:
    implementation_paths = (
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "api"
        / "routes"
        / "payload_standardization.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "services"
        / "execution_payload_standardization.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "schemas"
        / "execution_payload_standardization.py",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in implementation_paths
    ).lower()

    for marker in (
        "import httpx",
        "import requests",
        "urllib.request",
        "httpx.",
        "requests.",
        "build_webhook_gateway_decision",
        "webhook_gateway_ingress",
    ):
        assert marker not in source
