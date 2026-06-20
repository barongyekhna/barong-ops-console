from backend.app.sandbox import StagingSandbox
from backend.app.services.execution_dispatch_pipeline import EXECUTION_DISPATCH_PIPELINE
from backend.app.services.execution_provider_registry import (
    list_execution_provider_contracts,
)
from backend.app.services.execution_router import EXECUTION_ROUTER
from backend.app.services.provider_resolver import ProviderResolver


ORG_ID = "org_11111111111111111111111111111111"


def router_context(permission_key: str = "products.read") -> dict[str, object]:
    return {
        "org_context": {
            "org_id": ORG_ID,
            "user_id": "1",
            "role": "owner",
            "request_id": "req_router_test",
        },
        "c18h_context_applied": True,
        "c18f_permission_decision": {
            "decision": "allow",
            "reason": "router test C18F allow",
        },
        "c05_permission_result": {
            "decision": "allow",
            "reason": "router test C05 allow",
            "permission_key": permission_key,
        },
    }


def test_provider_resolver_selects_mock_staging_and_future_live_metadata() -> None:
    resolver = ProviderResolver(list_execution_provider_contracts())

    mock = resolver.resolve(
        module_id="business.products",
        action="business.products.placeholder.prepare",
        requested_mode="mock",
    )
    staging = resolver.resolve(
        module_id="business.products",
        action="business.products.placeholder.prepare",
        requested_mode="staging",
    )
    live = resolver.resolve(
        module_id="integration.n8n_test_bridge",
        action="integration.n8n_test_bridge.test_run.declare",
        requested_mode="live",
    )

    assert mock.provider.provider_key == "core.no_op_provider"
    assert mock.selected_mode == "mock"
    assert staging.provider.provider_key == "future.queue_provider"
    assert staging.selected_mode == "staging"
    assert live.provider.provider_key == "future.live_provider"
    assert live.selected_mode == "live"


def test_execution_router_returns_staging_plan_without_external_dispatch() -> None:
    response = EXECUTION_ROUTER.receive_request(
        org_id=ORG_ID,
        module_id="business.products",
        action="business.products.placeholder.prepare",
        payload={"execution_mode": "staging"},
        context=router_context(),
    )

    assert response.accepted is True
    assert response.dispatch_ready is True
    assert response.execution_plan.execution_mode == "staging"
    assert response.execution_plan.adapter_executes_logic is False
    assert response.selected_provider.provider_key == "future.queue_provider"
    assert response.gate_decision.decision == "allow"
    assert response.production_external_call_performed is False
    assert response.live_provider_dispatched is False


def test_execution_router_future_live_is_selected_but_gated() -> None:
    response = EXECUTION_ROUTER.receive_request(
        org_id=ORG_ID,
        module_id="integration.n8n_test_bridge",
        action="integration.n8n_test_bridge.test_run.declare",
        payload={"execution_mode": "live"},
        context=router_context("modules.read"),
    )

    assert response.accepted is False
    assert response.selected_provider.provider_key == "future.live_provider"
    assert response.gate_decision.decision == "deny"
    assert response.gate_decision.live_execution_allowed is False
    assert response.live_provider_dispatched is False


def test_staging_sandbox_prepares_isolated_context_only() -> None:
    response = EXECUTION_ROUTER.receive_request(
        org_id=ORG_ID,
        module_id="business.products",
        action="business.products.placeholder.prepare",
        payload={"execution_mode": "staging"},
        context=router_context(),
    )
    staging = StagingSandbox().prepare(response, payload={"title": "redacted"})

    assert staging.status == "prepared"
    assert staging.execution_dispatched is False
    assert staging.external_call_performed is False
    assert staging.production_db_access_performed is False
    assert staging.request.policy.production_db_access_allowed is False
    assert staging.request.policy.audit_logging_required is True
    assert staging.request.policy.c17_integration_ready is True


def test_c15_dispatch_pipeline_runs_c15a_c15f_then_router() -> None:
    result = EXECUTION_DISPATCH_PIPELINE.dispatch(
        org_id=ORG_ID,
        module_id="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
        payload={
            "execution_mode": "staging",
            "action": "integration.n8n_test_bridge.test_run.declare",
        },
        context=router_context("modules.read"),
    )

    assert result.status == "accepted"
    assert result.c15a_workflow_match.execution_allowed is True
    assert result.c15f_whitelist_check.binding_validation_passed is True
    assert result.router_response.selected_provider.provider_key == (
        "future.webhook_provider"
    )
    assert result.workflow_registry_executes is False
    assert result.webhook_direct_execution_allowed is False
