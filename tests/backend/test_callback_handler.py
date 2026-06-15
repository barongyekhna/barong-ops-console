from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.core.config import Settings, get_settings
from backend.app.main import app
from backend.app.schemas.callback_handler import CallbackHandlerPayload
from backend.app.schemas.execution_payload_standardization import (
    ExecutionPayloadStandardRequest,
)
from backend.app.services.callback_handler import (
    CallbackContextBindingError,
    CallbackExecutionStore,
    CallbackHandlerSignatureError,
    CallbackStatusTransitionError,
    bind_callback_context,
    get_callback_handler_completion_status,
    get_callback_handler_design,
    get_context_binding_model,
    get_module_notification_model,
    get_result_storage_model,
    get_status_management_model,
    handle_callback,
    reset_callback_execution_store,
    sign_callback_payload,
    verify_callback_signature,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_CALLBACK_SECRET = "c15d-test-signing-value-not-for-production-use"


def callback_settings() -> Settings:
    return Settings(
        webhook_gateway_signing_secret=SecretStr(TEST_CALLBACK_SECRET),
        webhook_gateway_signature_tolerance_seconds=300,
    )


def c15c_request(**updates: object) -> ExecutionPayloadStandardRequest:
    data = {
        "module": "business.products",
        "task": "business.products.placeholder.prepare",
        "context_id": "ctx.c15c.0123456789abcdef",
        "workflow_id": "n8n.workflow.business.products.dispatch.v1",
        "execution": {
            "capability": "reasoning",
            "model": "model.reasoning.primary_v1",
            "key_id": "ai.binding.reasoning.primary",
        },
        "payload": {"draft": {"title": "Static callback test"}},
        "timestamp": "2026-06-15T00:00:00Z",
    }
    data.update(updates)
    return ExecutionPayloadStandardRequest.model_validate(data)


def callback_payload(**updates: object) -> CallbackHandlerPayload:
    data = {
        "module": "business.products",
        "workflow_id": "n8n.workflow.business.products.dispatch.v1",
        "context_id": "ctx.c15c.0123456789abcdef",
        "status": "success",
        "output": {"summary": "stored local result"},
        "execution_metadata": {
            "n8n_execution_id": "exec-static-001",
            "attempt": 1,
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    data.update(updates)
    return CallbackHandlerPayload.model_validate(data)


def signed_headers(payload: CallbackHandlerPayload) -> dict[str, str]:
    return {
        "X-Barong-Gateway-Signature": sign_callback_payload(
            payload,
            secret=TEST_CALLBACK_SECRET,
        )
    }


def test_c15d_design_context_status_storage_notification_and_completion() -> None:
    design = get_callback_handler_design()
    binding = get_context_binding_model()
    status_model = get_status_management_model()
    storage = get_result_storage_model()
    notification = get_module_notification_model()
    completion = get_callback_handler_completion_status()

    assert design.entrypoint == "POST /api/control-plane/callback-handler/receiver"
    assert design.signature_source == "C15B HMAC-SHA256 verification model"
    assert design.no_execution_trigger is True
    assert binding.lookup_key == "context_id"
    assert binding.context_id_pattern == "^ctx\\.c15c\\.[0-9a-f]{16}$"
    assert binding.bound_request_type == "C15C ExecutionPayloadStandardRequest"
    assert status_model.allowed_statuses == (
        "pending",
        "running",
        "success",
        "failed",
    )
    assert status_model.allowed_transitions["pending"] == (
        "pending",
        "running",
        "success",
        "failed",
    )
    assert storage.stored_fields == (
        "workflow_output",
        "execution_metadata",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "callbacks_received",
    )
    assert notification.supported_module_families == ("K", "P", "SEO")
    assert notification.external_module_call_performed is False
    assert completion.completion_status == "complete"
    assert completion.can_proceed_to_c15e is True
    assert completion.no_external_api_call is True


def test_c15d_binds_c15c_context_and_stores_signed_callback_result() -> None:
    store = CallbackExecutionStore()
    request = c15c_request()
    binding = bind_callback_context(request, store=store)
    payload = callback_payload()
    signature = sign_callback_payload(payload, secret=TEST_CALLBACK_SECRET)

    verify_callback_signature(
        payload,
        provided_signature=signature,
        settings=callback_settings(),
    )
    result = handle_callback(
        payload,
        provided_signature=signature,
        settings=callback_settings(),
        store=store,
    )

    assert binding.context_id == request.context_id
    assert binding.status == "pending"
    assert result.processing_status == "accepted"
    assert result.signature_validated is True
    assert result.context_bound_to_c15c_request is True
    assert result.status == "success"
    assert result.stored_result.status == "success"
    assert result.stored_result.workflow_output == {
        "summary": "stored local result"
    }
    assert result.stored_result.execution_metadata["n8n_execution_id"] == (
        "exec-static-001"
    )
    assert result.stored_result.started_at is not None
    assert result.stored_result.completed_at is not None
    assert result.module_notification.module_family == "P"
    assert result.module_notification.standardized_result.standardized_result is True
    assert result.module_notification.external_module_call_performed is False
    assert result.runtime_execution_allowed is False
    assert result.n8n_dispatch_performed is False
    serialized = result.model_dump_json().lower()
    assert TEST_CALLBACK_SECRET not in serialized
    assert "n8n-webhook-ref://" not in serialized
    assert "http://" not in serialized
    assert "https://" not in serialized


def test_c15d_rejects_invalid_signature_stale_signature_and_unknown_context() -> None:
    store = CallbackExecutionStore()
    payload = callback_payload()
    signature = sign_callback_payload(payload, secret=TEST_CALLBACK_SECRET)

    with pytest.raises(CallbackHandlerSignatureError):
        verify_callback_signature(
            payload,
            provided_signature="wrong",
            settings=callback_settings(),
        )

    stale_payload = callback_payload(
        timestamp=(datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    )
    stale_signature = sign_callback_payload(
        stale_payload,
        secret=TEST_CALLBACK_SECRET,
    )
    with pytest.raises(CallbackHandlerSignatureError, match="timestamp"):
        verify_callback_signature(
            stale_payload,
            provided_signature=stale_signature,
            settings=callback_settings(),
        )

    with pytest.raises(CallbackContextBindingError):
        handle_callback(
            payload,
            provided_signature=signature,
            settings=callback_settings(),
            store=store,
        )


def test_c15d_status_manager_allows_safe_progression_and_rejects_regression() -> None:
    store = CallbackExecutionStore()
    bind_callback_context(c15c_request(), store=store)
    running = callback_payload(status="running", output={})
    success = callback_payload(status="success")
    failed_after_success = callback_payload(status="failed")

    running_result = handle_callback(
        running,
        provided_signature=sign_callback_payload(
            running,
            secret=TEST_CALLBACK_SECRET,
        ),
        settings=callback_settings(),
        store=store,
    )
    success_result = handle_callback(
        success,
        provided_signature=sign_callback_payload(
            success,
            secret=TEST_CALLBACK_SECRET,
        ),
        settings=callback_settings(),
        store=store,
    )

    assert running_result.status == "running"
    assert success_result.status == "success"
    assert success_result.stored_result.callbacks_received == 2
    with pytest.raises(CallbackStatusTransitionError):
        handle_callback(
            failed_after_success,
            provided_signature=sign_callback_payload(
                failed_after_success,
                secret=TEST_CALLBACK_SECRET,
            ),
            settings=callback_settings(),
            store=store,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"output": {"webhook_url": "redacted"}},
        {"execution_metadata": {"token": "redacted"}},
        {"output": {"target": "https://n8n.invalid/webhook/redacted"}},
    ],
)
def test_c15d_rejects_callback_payload_runtime_or_credential_data(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        callback_payload(**updates)


def test_c15d_callback_handler_api_routes(
    owner_client: TestClient,
) -> None:
    reset_callback_execution_store()
    settings = callback_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        request = c15c_request()
        bind_response = owner_client.post(
            "/api/control-plane/callback-handler/context-bindings",
            json=request.model_dump(mode="json"),
        )
        payload = callback_payload()
        accepted = owner_client.post(
            "/api/control-plane/callback-handler/receiver",
            json=payload.model_dump(mode="json"),
            headers=signed_headers(payload),
        )
        invalid_signature = owner_client.post(
            "/api/control-plane/callback-handler/receiver",
            json=payload.model_dump(mode="json"),
            headers={"X-Barong-Gateway-Signature": "wrong"},
        )
        unknown = callback_payload(context_id="ctx.c15c.ffffffffffffffff")
        unknown_response = owner_client.post(
            "/api/control-plane/callback-handler/receiver",
            json=unknown.model_dump(mode="json"),
            headers=signed_headers(unknown),
        )
        stored = owner_client.get(
            "/api/control-plane/callback-handler/results/ctx.c15c.0123456789abcdef"
        )

        assert bind_response.status_code == 201
        assert bind_response.json()["context_id"] == request.context_id
        assert accepted.status_code == 202
        assert accepted.json()["status"] == "success"
        assert accepted.json()["module_notification"]["module_family"] == "P"
        assert invalid_signature.status_code == 401
        assert unknown_response.status_code == 404
        assert stored.status_code == 200
        assert stored.json()["status"] == "success"

        assert owner_client.get("/api/control-plane/callback-handler/design").status_code == 200
        assert (
            owner_client.get("/api/control-plane/callback-handler/context-binding").status_code
            == 200
        )
        assert (
            owner_client.get("/api/control-plane/callback-handler/status-management").status_code
            == 200
        )
        assert (
            owner_client.get("/api/control-plane/callback-handler/result-storage").status_code
            == 200
        )
        assert (
            owner_client.get("/api/control-plane/callback-handler/module-notifications").status_code
            == 200
        )
        assert (
            owner_client.get("/api/control-plane/callback-handler/completion-status").status_code
            == 200
        )

        serialized = json.dumps(
            {
                "accepted": accepted.json(),
                "stored": stored.json(),
                "invalid_signature": invalid_signature.json(),
            }
        ).lower()
        assert TEST_CALLBACK_SECRET not in serialized
        assert "n8n-webhook-ref://" not in serialized
        assert "http://" not in serialized
        assert "https://" not in serialized
    finally:
        reset_callback_execution_store()
        app.dependency_overrides[get_settings] = lambda: test_settings


def test_c15d_router_exposes_no_execution_trigger_or_direct_n8n_call() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/api/control-plane/callback-handler")
    ]

    assert ("/api/control-plane/callback-handler/receiver", {"POST"}) in routes
    assert ("/api/control-plane/callback-handler/context-bindings", {"POST"}) in routes
    assert ("/api/control-plane/callback-handler/design", {"GET"}) in routes
    assert ("/api/control-plane/callback-handler/context-binding", {"GET"}) in routes
    assert ("/api/control-plane/callback-handler/status-management", {"GET"}) in routes
    assert ("/api/control-plane/callback-handler/result-storage", {"GET"}) in routes
    assert ("/api/control-plane/callback-handler/module-notifications", {"GET"}) in routes
    assert ("/api/control-plane/callback-handler/completion-status", {"GET"}) in routes
    assert not any(methods & {"PUT", "PATCH", "DELETE"} for _, methods in routes)
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke|n8n)\b", path)
        for path, _ in routes
    )


def test_c15d_implementation_has_no_http_runtime_client() -> None:
    implementation_paths = (
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "api"
        / "routes"
        / "callback_handler.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "services"
        / "callback_handler.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "schemas"
        / "callback_handler.py",
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
    ):
        assert marker not in source
