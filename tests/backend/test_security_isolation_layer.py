from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.core.config import Settings
from backend.app.schemas.operation_logs import OperationLogResponse
from backend.app.schemas.webhook_gateway import WebhookGatewayRequest
from backend.app.services.security_isolation import (
    get_gateway_enforcement_model,
    get_security_firewall_rules,
    get_security_isolation_architecture,
    get_security_isolation_completion_status,
    get_webhook_hiding_mechanism,
    has_security_isolation_leak,
    sanitize_security_isolation_payload,
)
from backend.app.services.webhook_gateway import (
    build_webhook_gateway_decision,
    sign_webhook_gateway_payload,
)

TEST_GATEWAY_SECRET = "c15g-test-signing-value-not-for-production-use"


def gateway_settings() -> Settings:
    return Settings(
        webhook_gateway_signing_secret=SecretStr(TEST_GATEWAY_SECRET),
        webhook_gateway_signature_tolerance_seconds=300,
    )


def gateway_payload(**updates: object) -> WebhookGatewayRequest:
    data = {
        "module": "integration.n8n_test_bridge",
        "workflow_id": "n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
        "context_id": "ctx_c15g_demo_001",
        "payload": {"source": "barong_ops_console", "mock_only": True},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    data.update(updates)
    return WebhookGatewayRequest.model_validate(data)


def test_c15g_architecture_firewall_hiding_gateway_and_completion() -> None:
    architecture = get_security_isolation_architecture()
    firewall = get_security_firewall_rules()
    hiding = get_webhook_hiding_mechanism()
    gateway = get_gateway_enforcement_model()
    completion = get_security_isolation_completion_status()

    assert architecture.only_n8n_entrypoint == "C15B Webhook Gateway"
    assert architecture.frontend_can_access_n8n_url is False
    assert architecture.module_can_access_n8n_url is False
    assert "/webhook" in firewall.blocked_direct_paths
    assert "/api/backend/n8n/*" in firewall.blocked_direct_paths
    assert firewall.direct_webhook_access_blocked is True
    assert firewall.unauthorized_http_access_blocked is True
    assert hiding.real_n8n_url_in_response_allowed is False
    assert hiding.hidden_webhook_ref_in_gateway_response_allowed is False
    assert hiding.webhook_url_in_logs_allowed is False
    assert gateway.c15b_only_entrypoint_to_n8n is True
    assert gateway.c15f_binding_required_before_gateway_accept is True
    assert completion.completion_status == "complete"
    assert completion.can_proceed_to_c15h is True
    assert completion.no_runtime_execution is True
    assert completion.no_external_api_change is True


def test_c15g_backend_firewall_blocks_direct_webhook_and_n8n_paths(
    owner_client: TestClient,
) -> None:
    for method, path in (
        ("get", "/webhook"),
        ("post", "/webhook/direct"),
        ("get", "/n8n"),
        ("post", "/n8n/webhook"),
    ):
        response = getattr(owner_client, method)(path)
        assert response.status_code == 403
        assert response.json()["detail"].startswith(
            "C15G security isolation blocks"
        )


def test_c15g_gateway_enforces_c15f_before_hidden_ref_resolution() -> None:
    payload = gateway_payload(module="business.products")
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
    assert decision.reason.startswith("C15G gateway enforcement rejected")
    assert decision.c15a_registered is True
    assert decision.c15a_bound_to_module is False
    assert decision.c15a_execution_allowed is False
    assert decision.hidden_webhook_reference_resolved is False
    assert decision.n8n_url_exposed is False
    assert decision.gateway_bypass_allowed is False
    serialized = decision.model_dump_json().lower()
    assert "n8n-webhook-ref://" not in serialized
    assert "http://" not in serialized
    assert "https://" not in serialized


def test_c15g_sanitizes_runtime_urls_from_log_response_details() -> None:
    unsafe_details = {
        "webhook_url": "https://n8n.invalid/webhook/redacted",
        "webhook_triggered": False,
        "nested": {
            "target": "n8n-webhook-ref://c15a/demo/dispatch/v1",
            "safe": "kept",
        },
    }
    sanitized = sanitize_security_isolation_payload(unsafe_details)
    response = OperationLogResponse(
        id=1,
        operation_id="op_c15g_demo",
        actor_type="system",
        actor_id="c15g",
        action="c15g.sanitize",
        target_type="operation_log",
        target_id="op_c15g_demo",
        job_id=None,
        result="success",
        error_code=None,
        request_id=None,
        ip_address=None,
        user_agent=None,
        details=unsafe_details,
        created_at=datetime.now(UTC),
    )

    assert has_security_isolation_leak(unsafe_details) is True
    assert has_security_isolation_leak(sanitized) is False
    assert "webhook_url" not in sanitized
    assert sanitized["webhook_triggered"] is False
    serialized = json.dumps(response.model_dump(mode="json")).lower()
    assert "https://n8n.invalid" not in serialized
    assert "n8n-webhook-ref://" not in serialized
