from backend.app.sandbox import (
    RUNTIME_LIFECYCLE_STEPS,
    RUNTIME_PIPELINE,
    SandboxRuntime,
)
from backend.app.schemas.execution_provider import ExecutionRequestContractV1


def execution_request(
    *,
    execution_id: str = "exec_c10f_demo_001",
    request_id: str = "req_c10f_demo_001",
) -> ExecutionRequestContractV1:
    return ExecutionRequestContractV1(
        execution_id=execution_id,
        request_id=request_id,
        module_key="business.products",
        adapter_key="business.products.placeholder.adapter",
        action_key="business.products.placeholder.prepare",
        actor_user_id=1001,
        target_scope={"product_ref": "demo-only"},
        input_payload={"redacted": True},
        sanitized_input_summary={"shape": "demo"},
        provider_key="core.no_op_provider",
        provider_type="no_op_provider",
        status="requested",
        risk_level="low",
        required_permission="products.read",
    )


def test_sandbox_runtime_finalizes_c10_chain_without_real_execution() -> None:
    response = SandboxRuntime().handle_execution_request(execution_request())

    assert response.stage == "c10f_runtime_finalization"
    assert response.runtime_mode == "disabled_execution"
    assert response.status == "mock_succeeded"
    assert response.next_stage_policy == "wait_for_c10g"
    assert response.pipeline == RUNTIME_PIPELINE
    assert [step.step_name for step in response.lifecycle.steps] == list(
        RUNTIME_LIFECYCLE_STEPS
    )
    assert response.execution_locked is True
    assert response.no_real_runtime_exists is True
    assert response.no_real_computation_execution is True
    assert response.runtime_created is False
    assert response.external_provider_called is False
    assert response.live_provider_called is False
    assert response.network_access_performed is False
    assert response.db_write_performed is False
    assert response.filesystem_access_performed is False
    assert response.production_mutated is False
    assert response.staging_mutated is False

    assert response.bridge_response.next_stage_policy == "wait_for_c10f"
    assert response.bridge_response.runtime_created is False
    assert response.sandbox_response.stage == "c10d_resource_control"
    assert response.sandbox_response.result.runtime_created is False
    assert response.sandbox_response.result.external_provider_called is False
    assert response.sandbox_response.result.db_mutated is False
    assert response.sandbox_response.result.filesystem_write_scope == "none"
    assert response.c09_result_contract is not None
    assert response.c09_result_contract.safe_result_only is True

    assert response.safety_lock.execution_locked is True
    assert response.safety_lock.safe is True
    assert response.safety_lock.lock_status == "locked_clean"
    assert response.safety_lock.no_side_effect_guarantee is True
    assert response.safety_lock.no_external_call is True
    assert response.safety_lock.no_real_computation_execution is True
    assert response.safety_lock.no_real_runtime_existence is True
    assert response.safety_lock.provider_access == "redacted"

    assert response.final_state.execution_capability == "mock_only"
    assert response.final_state.runtime_mode == "disabled_execution"
    assert response.final_state.isolation_status == "fully_isolated"
    assert response.final_state.provider_access == "redacted"
    assert response.final_state.execution_locked is True
    assert response.final_state.no_real_runtime_exists is True


def test_sandbox_runtime_final_safety_lock_detects_runtime_escape() -> None:
    runtime = SandboxRuntime()
    response = runtime.handle_execution_request(
        execution_request(
            execution_id="exec_c10f_demo_002",
            request_id="req_c10f_demo_002",
        )
    )
    unsafe_bridge_response = response.bridge_response.model_copy(
        update={"runtime_created": True}
    )

    safety_lock, complete_step = runtime.runtime_complete(unsafe_bridge_response)

    assert complete_step.status == "blocked"
    assert safety_lock.execution_locked is True
    assert safety_lock.safe is False
    assert safety_lock.lock_status == "locked_with_violation"
    assert {violation.code for violation in safety_lock.violations} == {
        "C10F_RUNTIME_CREATED"
    }
