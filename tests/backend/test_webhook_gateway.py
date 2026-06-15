from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.core.config import Settings, get_settings
from backend.app.main import app
from backend.app.schemas.webhook_gateway import WebhookGatewayRequest
from backend.app.services.webhook_gateway import (
    WebhookGatewaySignatureError,
    build_webhook_gateway_decision,
    get_webhook_gateway_completion_status,
    get_webhook_gateway_design,
    get_webhook_gateway_lookup_flow,
    get_webhook_gateway_payload_format,
    get_webhook_gateway_signature_model,
    sign_webhook_gateway_payload,
    verify_webhook_gateway_signature,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_GATEWAY_SECRET = "c15b-test-signing-value-not-for-production-use"


def gateway_settings() -> Settings:
    return Settings(
        webhook_gateway_signing_secret=SecretStr(TEST_GATEWAY_SECRET),
        webhook_gateway_signature_tolerance_seconds=300,
    )


def gateway_payload(**updates: object) -> WebhookGatewayRequest:
    data = {
        "module": "integration.n8n_test_bridge",
        "workflow_id": "n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
        "context_id": "ctx_c15b_demo_001",
        "payload": {
            "source": "barong_ops_console",
            "test_mode": True,
            "mock_only": True,
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    data.update(updates)
    return WebhookGatewayRequest.model_validate(data)


def signed_headers(payload: WebhookGatewayRequest) -> dict[str, str]:
    return {
        "X-Barong-Gateway-Signature": sign_webhook_gateway_payload(
            payload,
            secret=TEST_GATEWAY_SECRET,
        )
    }


def test_c15b_gateway_design_signature_payload_lookup_and_status() -> None:
    settings = gateway_settings()
    design = get_webhook_gateway_design()
    signature = get_webhook_gateway_signature_model(settings)
    payload_format = get_webhook_gateway_payload_format()
    lookup = get_webhook_gateway_lookup_flow()
    completion = get_webhook_gateway_completion_status()

    assert design.entrypoint == "POST /api/control-plane/webhook-gateway/ingress"
    assert design.route == (
        "requester",
        "C15B Webhook Gateway",
        "C15A Workflow Registry",
        "hidden n8n webhook reference",
        "n8n",
    )
    assert design.direct_n8n_access_allowed is False
    assert design.hardcoded_webhook_url_allowed is False
    assert design.runtime_execution_allowed is False
    assert signature.algorithm == "HMAC-SHA256"
    assert signature.invalid_signature_rejected is True
    assert signature.replay_window_seconds == 300
    assert payload_format.required_fields == (
        "module",
        "workflow_id",
        "context_id",
        "payload",
        "timestamp",
    )
    assert payload_format.payload_may_contain_credentials is False
    assert lookup.registry_source == "C15A registry"
    assert lookup.hardcoded_webhook_url_allowed is False
    assert lookup.no_runtime_execution is True
    assert completion.completion_status == "complete"
    assert completion.can_proceed_to_c15c is True
    assert completion.no_production_or_staging_change is True


def test_c15b_accepts_only_signed_active_c15a_workflow() -> None:
    settings = gateway_settings()
    payload = gateway_payload()
    signature = sign_webhook_gateway_payload(
        payload,
        secret=TEST_GATEWAY_SECRET,
    )

    verify_webhook_gateway_signature(
        payload,
        provided_signature=signature,
        settings=settings,
    )
    decision = build_webhook_gateway_decision(
        payload,
        provided_signature=signature,
        settings=settings,
    )

    assert decision.gateway_status == "accepted"
    assert decision.signature_validated is True
    assert decision.workflow_lookup_source == "C15A registry"
    assert decision.c15a_registered is True
    assert decision.c15a_bound_to_module is True
    assert decision.c15a_workflow_status == "active"
    assert decision.c15a_execution_allowed is True
    assert decision.hidden_webhook_reference_resolved is True
    assert decision.n8n_url_exposed is False
    assert decision.direct_workflow_call_allowed is False
    assert decision.gateway_bypass_allowed is False
    assert decision.n8n_dispatch_performed is False
    assert decision.runtime_execution_allowed is False
    serialized = decision.model_dump_json().lower()
    assert TEST_GATEWAY_SECRET not in serialized
    assert "n8n-webhook-ref://" not in serialized
    assert "http://" not in serialized
    assert "https://" not in serialized


@pytest.mark.parametrize(
    "provided_signature",
    [None, "wrong-signature"],
)
def test_c15b_rejects_unsigned_or_invalid_signature(
    provided_signature: str | None,
) -> None:
    with pytest.raises(WebhookGatewaySignatureError):
        verify_webhook_gateway_signature(
            gateway_payload(),
            provided_signature=provided_signature,
            settings=gateway_settings(),
        )


def test_c15b_rejects_stale_signed_payload() -> None:
    stale_payload = gateway_payload(
        timestamp=(datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    )
    signature = sign_webhook_gateway_payload(
        stale_payload,
        secret=TEST_GATEWAY_SECRET,
    )

    with pytest.raises(WebhookGatewaySignatureError, match="timestamp"):
        verify_webhook_gateway_signature(
            stale_payload,
            provided_signature=signature,
            settings=gateway_settings(),
        )


@pytest.mark.parametrize(
    "updates, expected_status",
    [
        (
            {
                "workflow_id": (
                    "n8n.workflow.integration.n8n_test_bridge.legacy.v1"
                )
            },
            "deprecated",
        ),
        (
            {
                "workflow_id": (
                    "n8n.workflow.integration.n8n_test_bridge.unknown.v1"
                )
            },
            "unregistered",
        ),
        ({"module": "business.products"}, "active"),
    ],
)
def test_c15b_blocks_non_active_or_unbound_registry_decisions(
    updates: dict[str, object],
    expected_status: str,
) -> None:
    payload = gateway_payload(**updates)
    signature = sign_webhook_gateway_payload(
        payload,
        secret=TEST_GATEWAY_SECRET,
    )

    decision = build_webhook_gateway_decision(
        payload,
        provided_signature=signature,
        settings=gateway_settings(),
    )

    assert decision.gateway_status == "rejected"
    assert decision.c15a_execution_allowed is False
    assert decision.c15a_workflow_status == expected_status
    assert decision.hidden_webhook_reference_resolved is False
    assert decision.n8n_url_exposed is False
    assert decision.direct_n8n_access_allowed is False
    assert decision.n8n_dispatch_performed is False


@pytest.mark.parametrize(
    "unsafe_payload",
    [
        {"webhook_url": "redacted"},
        {"nested": {"token": "redacted"}},
        {"target": "https://n8n.invalid/webhook/redacted"},
    ],
)
def test_c15b_standard_payload_rejects_direct_access_data(
    unsafe_payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        gateway_payload(payload=unsafe_payload)


def test_c15b_gateway_api_routes_and_signature_enforcement(
    owner_client: TestClient,
) -> None:
    settings = gateway_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        payload = gateway_payload()
        accepted = owner_client.post(
            "/api/control-plane/webhook-gateway/ingress",
            json=payload.model_dump(mode="json"),
            headers=signed_headers(payload),
        )
        invalid_signature = owner_client.post(
            "/api/control-plane/webhook-gateway/ingress",
            json=payload.model_dump(mode="json"),
            headers={"X-Barong-Gateway-Signature": "wrong"},
        )
        deprecated_payload = gateway_payload(
            workflow_id=(
                "n8n.workflow.integration.n8n_test_bridge.legacy.v1"
            )
        )
        rejected = owner_client.post(
            "/api/control-plane/webhook-gateway/ingress",
            json=deprecated_payload.model_dump(mode="json"),
            headers=signed_headers(deprecated_payload),
        )
        unsafe = owner_client.post(
            "/api/control-plane/webhook-gateway/ingress",
            json={
                **payload.model_dump(mode="json"),
                "payload": {
                    "target": "https://n8n.invalid/webhook/redacted"
                },
            },
            headers=signed_headers(payload),
        )

        assert accepted.status_code == 202
        accepted_payload = accepted.json()
        assert accepted_payload["gateway_status"] == "accepted"
        assert accepted_payload["runtime_execution_allowed"] is False
        assert accepted_payload["n8n_dispatch_performed"] is False
        assert invalid_signature.status_code == 401
        assert rejected.status_code == 403
        assert rejected.json()["detail"]["gateway_status"] == "rejected"
        assert unsafe.status_code == 422
        assert unsafe.json()["detail"] == "Invalid C15B webhook gateway payload."

        assert owner_client.get("/api/control-plane/webhook-gateway/design").status_code == 200
        assert (
            owner_client.get("/api/control-plane/webhook-gateway/signature-model").status_code
            == 200
        )
        assert (
            owner_client.get("/api/control-plane/webhook-gateway/payload-format").status_code
            == 200
        )
        assert (
            owner_client.get("/api/control-plane/webhook-gateway/workflow-lookup-flow").status_code
            == 200
        )
        assert (
            owner_client.get("/api/control-plane/webhook-gateway/completion-status").status_code
            == 200
        )

        serialized = json.dumps(
            {
                "accepted": accepted_payload,
                "rejected": rejected.json(),
                "unsafe": unsafe.json(),
            }
        ).lower()
        assert TEST_GATEWAY_SECRET not in serialized
        assert "n8n-webhook-ref://" not in serialized
        assert "http://" not in serialized
        assert "https://" not in serialized
    finally:
        app.dependency_overrides[get_settings] = lambda: test_settings


def test_c15b_gateway_router_exposes_no_direct_n8n_or_workflow_call() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/api/control-plane/webhook-gateway")
    ]

    assert ("/api/control-plane/webhook-gateway/ingress", {"POST"}) in routes
    assert ("/api/control-plane/webhook-gateway/design", {"GET"}) in routes
    assert ("/api/control-plane/webhook-gateway/signature-model", {"GET"}) in routes
    assert ("/api/control-plane/webhook-gateway/payload-format", {"GET"}) in routes
    assert ("/api/control-plane/webhook-gateway/workflow-lookup-flow", {"GET"}) in routes
    assert ("/api/control-plane/webhook-gateway/completion-status", {"GET"}) in routes
    assert not any(
        path.endswith("/n8n") or "/n8n/" in path for path, _ in routes
    )
    assert not any(
        "/api/control-plane/workflows/" in path and methods & {"POST", "PUT", "PATCH", "DELETE"}
        for path, methods in routes
    )


def test_c15b_gateway_implementation_has_no_http_runtime_client() -> None:
    implementation_paths = (
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "api"
        / "routes"
        / "webhook_gateway.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "services"
        / "webhook_gateway.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "schemas"
        / "webhook_gateway.py",
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
