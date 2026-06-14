import pytest

from backend.app.sandbox import (
    ExecutionContextFactory,
    ExecutionContextIsolationRules,
    ExecutionContextLifecycleStateMachine,
    SandboxRunner,
)
from backend.app.schemas.execution_provider import ExecutionRequestContractV1


def execution_request(
    *,
    execution_id: str = "exec_c10c_demo_001",
    request_id: str = "req_c10c_demo_001",
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
        risk_level="medium",
        required_permission="products.read",
    )


def test_execution_context_factory_is_deterministic_and_request_scoped() -> None:
    factory = ExecutionContextFactory()
    request = execution_request()

    first = factory.create_context(request)
    second = factory.create_context(request)
    other = factory.create_context(
        execution_request(
            execution_id="exec_c10c_demo_002",
            request_id="req_c10c_demo_002",
        )
    )

    assert first == second
    assert first.context_id != other.context_id
    assert first.memory_scope.memory_scope_id != other.memory_scope.memory_scope_id
    assert first.log_scope.log_scope_id != other.log_scope.log_scope_id
    assert first.state_scope.state_scope_id != other.state_scope.state_scope_id
    assert first.lifecycle_state == "created"
    assert first.runtime_execution_allowed is False
    assert first.external_provider_call_allowed is False
    assert first.db_mutation_allowed is False
    assert first.filesystem_write_allowed is False


def test_execution_context_lifecycle_is_mock_only() -> None:
    context = ExecutionContextFactory().create_context(execution_request())

    completed, completed_snapshot = (
        ExecutionContextLifecycleStateMachine.run_mock_success(context)
    )
    archived, archived_snapshot = ExecutionContextLifecycleStateMachine.archive(
        completed,
        transitions=completed_snapshot.transitions,
    )

    assert completed.lifecycle_state == "completed"
    assert archived.lifecycle_state == "archived"
    assert [step.to_state for step in archived_snapshot.transitions] == [
        "initialized",
        "running",
        "completed",
        "archived",
    ]
    assert all(
        step.runtime_created is False for step in archived_snapshot.transitions
    )
    assert all(
        step.external_provider_called is False
        for step in archived_snapshot.transitions
    )

    with pytest.raises(ValueError, match="Invalid C10C lifecycle transition"):
        ExecutionContextLifecycleStateMachine.complete(context)


def test_execution_context_isolation_rules_detect_scope_reuse() -> None:
    factory = ExecutionContextFactory()
    first = factory.create_context(execution_request())
    second = factory.create_context(
        execution_request(
            execution_id="exec_c10c_demo_003",
            request_id="req_c10c_demo_003",
        )
    )

    separate_report = ExecutionContextIsolationRules.validate_context_pair(
        first,
        second,
    )
    reused_report = ExecutionContextIsolationRules.validate_context_pair(
        first,
        first,
    )

    assert separate_report.isolated is True
    assert reused_report.isolated is False
    assert {violation.code for violation in reused_report.violations} == {
        "C10C_CONTEXT_REUSE",
        "C10C_SHARED_MEMORY_SCOPE",
        "C10C_SHARED_LOG_SCOPE",
        "C10C_SHARED_STATE_SCOPE",
    }


def test_sandbox_runner_binds_execution_context_without_real_execution() -> None:
    request = execution_request()
    context = ExecutionContextFactory().create_context(request)

    response = SandboxRunner().handle_execution_request(
        request,
        context=context,
    )

    assert response.context_id == context.context_id
    assert response.execution_context is not None
    assert response.execution_context.lifecycle_state == "completed"
    assert response.result.context_lifecycle_state == "completed"
    assert response.result.runtime_created is False
    assert response.result.external_provider_called is False
    assert response.result.db_mutated is False
    assert response.result.filesystem_write_scope == "none"
    assert response.stage == "c10d_resource_control"
    assert response.resource_policy is not None
    assert response.resource_policy.execution_id == context.execution_id
    assert response.resource_policy.context_id == context.context_id
    assert response.resource_policy.network_policy == "DENY_ALL"
    assert response.resource_policy.file_access_policy == "SANDBOX_ONLY"
    assert response.execution_context.resource_policy_ref == (
        response.resource_policy.policy_id
    )
    assert response.result.resource_policy_ref == response.resource_policy.policy_id
    assert response.result.resource_violations == []
    assert response.next_stage_policy == "wait_for_c10e"
    assert response.c09_result_contract is not None
    assert response.c09_result_contract.execution_id == context.execution_id
    assert response.result.result_summary["resource_control"]["mock_only"] is True
    assert (
        response.result.result_summary["safety"]["real_cpu_enforcement"] is False
    )
    assert response.result.result_summary["safety"]["network_access"] is False


def test_resource_enforcer_blocks_network_capability_without_real_execution() -> None:
    request = execution_request()
    runner = SandboxRunner()
    sandbox_request = runner.build_sandbox_request(
        request,
        requested_capabilities=["network_access"],
    )

    response = runner.run(sandbox_request)

    assert response.stage == "c10d_resource_control"
    assert response.result.status == "mock_blocked"
    assert response.result.execution_status == "rejected"
    assert response.result.runtime_created is False
    assert response.result.external_provider_called is False
    assert response.result.resource_violations
    assert {
        violation.violation_type
        for violation in response.result.resource_violations
    } == {"network_access_requested"}
    assert all(
        violation.execution_blocked is True
        for violation in response.result.resource_violations
    )
    assert response.resource_policy is not None
    assert response.resource_policy.network_access_allowed is False
    assert response.result.result_summary["resource_control"][
        "network_access_performed"
    ] is False
