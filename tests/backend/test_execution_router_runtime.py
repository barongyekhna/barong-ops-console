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

    # The business.products placeholder contracts (core.no_op_provider /
    # future.queue_provider) were removed with the module; the resolver
    # contract is now exercised through the surviving admin.users providers.
    mock = resolver.resolve(
        module_id="admin.users",
        action="admin.users.read",
        requested_mode="mock",
    )
    staging = resolver.resolve(
        module_id="admin.users",
        action="admin.users.read",
        requested_mode="staging",
    )
    live = resolver.resolve(
        module_id="integration.n8n_test_bridge",
        action="integration.n8n_test_bridge.test_run.declare",
        requested_mode="live",
    )

    assert mock.provider.provider_key == "core.mock_provider"
    assert mock.selected_mode == "mock"
    assert staging.provider.provider_key == "future.local_backend_provider"
    assert staging.selected_mode == "staging"
    assert live.provider.provider_key == "future.live_provider"
    assert live.selected_mode == "live"


def test_execution_router_returns_staging_plan_without_external_dispatch() -> None:
    response = EXECUTION_ROUTER.receive_request(
        org_id=ORG_ID,
        module_id="admin.users",
        action="admin.users.read",
        payload={"execution_mode": "staging"},
        context=router_context("users.read"),
    )

    assert response.accepted is True
    assert response.dispatch_ready is True
    assert response.execution_plan.execution_mode == "staging"
    assert response.execution_plan.adapter_executes_logic is False
    assert response.selected_provider.provider_key == "future.local_backend_provider"
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


