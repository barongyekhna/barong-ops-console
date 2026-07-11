from backend.app.sandbox import (
    BRIDGE_FLOW,
    ExecutionContextFactory,
    SandboxExecutionBridge,
)
from backend.app.schemas.execution_provider import ExecutionRequestContractV1


def execution_request(
    *,
    execution_id: str = "exec_c10e_demo_001",
    request_id: str = "req_c10e_demo_001",
) -> ExecutionRequestContractV1:
    return ExecutionRequestContractV1(
        execution_id=execution_id,
        request_id=request_id,
        module_key="k.product_knowledge",
        adapter_key="k.product_knowledge.placeholder.adapter",
        action_key="k.product_knowledge.placeholder.prepare",
        actor_user_id=1001,
        target_scope={"product_ref": "demo-only"},
        input_payload={"redacted": True},
        sanitized_input_summary={"shape": "demo"},
        provider_key="core.no_op_provider",
        provider_type="no_op_provider",
        status="requested",
        risk_level="medium",
        required_permission="products.read",
    )


def test_sandbox_execution_bridge_forwards_to_mock_provider_only() -> None:
    request = execution_request()
    context = ExecutionContextFactory().create_context(request)

    response = SandboxExecutionBridge().receive_execution_request(
        request,
        context=context,
    )

    assert response.stage == "c10e_execution_bridge"
    assert response.bridge_mode == "passthrough_mock_mode"
    assert response.status == "mock_succeeded"
    assert response.next_stage_policy == "wait_for_c10f"
    assert response.flow == BRIDGE_FLOW
    assert response.safety_guard.safe is True
    assert response.safety_guard.runtime_created is False
    assert response.safety_guard.external_provider_called is False
    assert response.safety_guard.filesystem_access_performed is False
    assert response.provider_forward_response.mock_interface_only is True
    assert response.provider_forward_response.external_provider_called is False
    assert response.provider_forward_response.live_provider_called is False
    assert response.provider_forward_response.filesystem_access_performed is False
    assert response.provider_request_mapping.schema_name == (
        "provider_request_mapping"
    )
    assert response.provider_request_mapping.live_provider_call_allowed is False
    assert (
        response.provider_request_mapping.raw_input_payload_forwarded_to_provider
        is False
    )
    assert response.provider_forward_request.raw_input_payload_included is False
    assert response.provider_forward_request.raw_input_payload_echoed is False
    assert response.sandbox_request_mapping.schema_name == (
        "sandbox_request_mapping"
    )
    assert response.sandbox_request_mapping.context_bound is True
    assert response.sandbox_request_mapping.filesystem_access_allowed is False
    assert response.sandbox_response.stage == "c10d_resource_control"
    assert response.sandbox_response.next_stage_policy == "wait_for_c10e"
    assert response.sandbox_response.result.runtime_created is False
    assert response.sandbox_response.result.external_provider_called is False
    assert response.sandbox_response.result.db_mutated is False
    assert response.sandbox_response.result.filesystem_write_scope == "none"
    assert response.c09_result_contract is not None
    assert response.c09_result_contract.safe_result_only is True


def test_sandbox_execution_bridge_modes_are_mock_only() -> None:
    bridge = SandboxExecutionBridge()

    for bridge_mode in [
        "passthrough_mock_mode",
        "dry_run_mode",
        "simulation_mode",
    ]:
        response = bridge.receive_execution_request(
            execution_request(
                execution_id=f"exec_c10e_{bridge_mode}",
                request_id=f"req_c10e_{bridge_mode}",
            ),
            bridge_mode=bridge_mode,
        )

        assert response.bridge_mode == bridge_mode
        assert response.safety_guard.safe is True
        assert response.runtime_created is False
        assert response.external_provider_called is False
        assert response.live_provider_called is False
        assert response.network_access_performed is False
        assert response.db_write_performed is False
        assert response.filesystem_access_performed is False
        assert response.production_mutated is False
        assert response.staging_mutated is False
        assert response.provider_request_mapping.mock_interface_only is True
        assert response.provider_forward_response.accepted is True
