from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.result_normalization import (
    get_result_module_adapter_rules,
    get_result_normalization_completion_status,
    get_result_normalization_engine_design,
    get_result_schema_mapping_model,
    get_result_ui_output_structure,
    normalize_workflow_result,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def c15d_storage_result(**updates: Any) -> dict[str, Any]:
    result = {
        "context_id": "ctx.c15c.0123456789abcdef",
        "module": "k.product_knowledge",
        "workflow_id": "n8n.workflow.k.product_knowledge.dispatch.v1",
        "status": "success",
        "workflow_output": {
            "summary": "Product draft prepared.",
            "product": {
                "sku": "sku-001",
                "title": "Static C15E Product",
            },
        },
        "execution_metadata": {
            "execution_ref": "exec-static-001",
            "attempt": 1,
        },
    }
    result.update(updates)
    return result


def test_c15e_design_mapping_adapters_ui_and_completion() -> None:
    engine = get_result_normalization_engine_design()
    mapping = get_result_schema_mapping_model()
    adapters = get_result_module_adapter_rules()
    ui_output = get_result_ui_output_structure()
    completion = get_result_normalization_completion_status()

    assert engine.standard_output_fields == (
        "context_id",
        "module",
        "workflow_id",
        "status",
        "result",
        "metadata",
    )
    assert engine.flexible_json_parsing_supported is True
    assert engine.fallback_normalization_supported is True
    assert mapping.mapping_direction == (
        "workflow-specific -> standard result schema"
    )
    assert mapping.missing_mapping_behavior == "fallback_normalization"
    assert adapters.supported_module_families == ("K", "P", "SEO")
    assert adapters.output_structure_unified is True
    assert ui_output.frontend_can_consume_directly is True
    assert ui_output.raw_n8n_structure_exposed is False
    assert completion.completion_status == "complete"
    assert completion.can_proceed_to_c15f is True
    assert completion.external_api_call_allowed is False


def test_c15e_normalizes_c15d_storage_to_frontend_shape() -> None:
    normalized = normalize_workflow_result(c15d_storage_result())

    assert set(normalized.model_dump(mode="json")) == {
        "context_id",
        "module",
        "workflow_id",
        "status",
        "result",
        "metadata",
    }
    assert normalized.context_id == "ctx.c15c.0123456789abcdef"
    assert normalized.module == "k.product_knowledge"
    assert normalized.workflow_id == (
        "n8n.workflow.k.product_knowledge.dispatch.v1"
    )
    assert normalized.status == "success"
    assert normalized.metadata.module_family == "P"
    assert normalized.metadata.source_format == "c15d_storage"
    assert normalized.metadata.frontend_consumable is True
    assert normalized.metadata.source_metadata == {
        "execution_ref": "exec-static-001",
        "attempt": 1,
    }
    assert normalized.result["summary"] == "Product draft prepared."
    assert normalized.result["items"] == [
        {
            "sku": "sku-001",
            "title": "Static C15E Product",
        }
    ]
    assert normalized.result["data"]["product"]["sku"] == "sku-001"

    serialized = normalized.model_dump_json().lower()
    assert "workflow_output" not in serialized
    assert "execution_metadata" not in serialized
    assert "paireditem" not in serialized
    assert "binary" not in serialized
    assert "n8n-webhook-ref://" not in serialized
    assert "http://" not in serialized
    assert "https://" not in serialized


def test_c15e_applies_workflow_specific_schema_mapping() -> None:
    raw_output = {
        "wf": {
            "ctx": "ctx.c15c.abcdef0123456789",
            "module": "seo.audit",
            "id": "n8n.workflow.seo.audit.dispatch.v1",
        },
        "state": "completed",
        "payload": {
            "seo": {
                "title": "Search result cleanup",
                "keywords": ["technical seo", "indexing"],
                "recommendations": ["Refresh title tags"],
            }
        },
        "details": {"attempt": 2},
    }
    mapping = {
        "mapping_id": "seo.audit.result.v1",
        "workflow_id": "n8n.workflow.seo.audit.dispatch.v1",
        "module": "seo.audit",
        "field_paths": {
            "context_id": ["wf", "ctx"],
            "module": ["wf", "module"],
            "workflow_id": ["wf", "id"],
            "status": ["state"],
            "result": ["payload", "seo"],
            "metadata": ["details"],
        },
        "result_paths": {
            "title": ["payload", "seo", "title"],
            "keywords": ["payload", "seo", "keywords"],
            "recommendations": ["payload", "seo", "recommendations"],
        },
        "metadata_paths": {
            "attempt": ["details", "attempt"],
        },
    }

    normalized = normalize_workflow_result(
        {"raw_output": raw_output, "schema_mappings": [mapping]}
    )

    assert normalized.context_id == "ctx.c15c.abcdef0123456789"
    assert normalized.module == "seo.audit"
    assert normalized.status == "success"
    assert normalized.metadata.schema_mapping_id == "seo.audit.result.v1"
    assert normalized.metadata.source_schema == "workflow_specific"
    assert normalized.metadata.module_family == "SEO"
    assert normalized.metadata.source_metadata == {"attempt": 2}
    assert normalized.result["summary"] == "Search result cleanup"
    assert normalized.result["items"] == ["technical seo", "indexing"]
    assert normalized.result["data"]["recommendations"] == [
        "Refresh title tags"
    ]


def test_c15e_unwraps_n8n_items_without_exposing_raw_structure() -> None:
    normalized = normalize_workflow_result(
        {
            "context_id": "ctx.c15c.1111222233334444",
            "module": "k.research",
            "workflow_id": "n8n.workflow.k.research.dispatch.v1",
            "status": "success",
            "output": [
                {
                    "json": {
                        "answer": "Static knowledge result.",
                        "recommendations": ["Keep the summary concise."],
                    },
                    "pairedItem": {"item": 0},
                    "binary": {"ignored": True},
                }
            ],
        }
    )

    assert normalized.metadata.source_format == "n8n_items"
    assert normalized.metadata.module_family == "K"
    assert normalized.result["items"] == [
        {
            "answer": "Static knowledge result.",
            "recommendations": ["Keep the summary concise."],
        }
    ]
    serialized = normalized.model_dump_json().lower()
    assert "paireditem" not in serialized
    assert "binary" not in serialized
    assert '"json"' not in serialized


@pytest.mark.parametrize(
    "unsafe_output",
    [
        {"workflow_output": {"webhook_url": "redacted"}},
        {"workflow_output": {"target": "https://n8n.invalid/redacted"}},
        {"execution_metadata": {"token": "redacted"}},
    ],
)
def test_c15e_rejects_runtime_or_credential_result_data(
    unsafe_output: dict[str, Any],
) -> None:
    payload = c15d_storage_result()
    payload.update(unsafe_output)

    with pytest.raises(ValueError):
        normalize_workflow_result(payload)


def test_c15e_result_normalization_api_routes(
    owner_client: TestClient,
) -> None:
    response = owner_client.post(
        "/api/control-plane/result-normalization/normalize",
        json=c15d_storage_result(),
    )

    assert response.status_code == 200
    assert set(response.json()) == {
        "context_id",
        "module",
        "workflow_id",
        "status",
        "result",
        "metadata",
    }
    assert response.json()["metadata"]["raw_n8n_structure_exposed"] is False

    assert owner_client.get(
        "/api/control-plane/result-normalization/normalization-engine"
    ).status_code == 200
    assert owner_client.get(
        "/api/control-plane/result-normalization/schema-mapping"
    ).status_code == 200
    assert owner_client.get(
        "/api/control-plane/result-normalization/module-adapters"
    ).status_code == 200
    assert owner_client.get(
        "/api/control-plane/result-normalization/ui-output-structure"
    ).status_code == 200
    assert owner_client.get(
        "/api/control-plane/result-normalization/completion-status"
    ).status_code == 200

    serialized = json.dumps(response.json()).lower()
    assert "workflow_output" not in serialized
    assert "execution_metadata" not in serialized
    assert "n8n-webhook-ref://" not in serialized
    assert "http://" not in serialized
    assert "https://" not in serialized


def test_c15e_router_exposes_only_normalization_contract_paths() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith(
            "/api/control-plane/result-normalization"
        )
    ]

    assert ("/api/control-plane/result-normalization/normalize", {"POST"}) in routes
    assert ("/api/control-plane/result-normalization/normalization-engine", {"GET"}) in routes
    assert ("/api/control-plane/result-normalization/schema-mapping", {"GET"}) in routes
    assert ("/api/control-plane/result-normalization/module-adapters", {"GET"}) in routes
    assert ("/api/control-plane/result-normalization/ui-output-structure", {"GET"}) in routes
    assert ("/api/control-plane/result-normalization/completion-status", {"GET"}) in routes
    assert not any(methods & {"PUT", "PATCH", "DELETE"} for _, methods in routes)
    assert not any(
        methods & {"POST"} and path != "/api/control-plane/result-normalization/normalize"
        for path, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke|n8n)\b", path)
        for path, _ in routes
    )


def test_c15e_implementation_has_no_runtime_http_client_or_c15d_mutation() -> None:
    implementation_paths = (
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "api"
        / "routes"
        / "result_normalization.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "services"
        / "result_normalization.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "schemas"
        / "result_normalization.py",
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
        "handle_callback",
        "bind_callback_context",
        "update_execution_status",
        "webhook_gateway_ingress",
    ):
        assert marker not in source
