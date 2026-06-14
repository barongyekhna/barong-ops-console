from __future__ import annotations

import pytest

from backend.app.sandbox import SandboxRuntime
from backend.app.sandbox.types import SandboxRequest
from backend.app.schemas.execution_provider import ExecutionRequestContractV1
from backend.app.services.emergency_kill_switch import set_global_kill_switch
from backend.app.services.execution_flow_gate import (
    C13E_GATE,
    ExecutionFlowGateBlockedError,
)


def execution_request(
    *,
    execution_id: str = "exec_c13e_demo_001",
    request_id: str = "req_c13e_demo_001",
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


def bypassed_request(**updates: object) -> ExecutionRequestContractV1:
    data = {
        "execution_id": "exec_c13e_bypass",
        "request_id": "req_c13e_bypass",
        "module_key": "business.products",
        "adapter_key": "business.products.placeholder.adapter",
        "action_key": "business.products.placeholder.prepare",
        "actor_user_id": 1001,
        "target_scope": {},
        "input_payload": {},
        "sanitized_input_summary": {},
        "provider_key": "core.no_op_provider",
        "provider_type": "no_op_provider",
        "status": "requested",
        "risk_level": "medium",
        "required_permission": "products.read",
        "approval_status": "not_required",
        "secret_binding_status": "not_required",
        "created_at": None,
        "accepted_at": None,
        "started_at": None,
        "finished_at": None,
        "cancelled_at": None,
        "timeout_at": None,
        "result_summary": None,
        "artifact_refs": [],
        "error_code": None,
        "error_message_safe": None,
        "operation_log_id": None,
    }
    data.update(updates)
    return ExecutionRequestContractV1.model_construct(**data)


def test_c13e_gate_allows_sealed_no_op_flow() -> None:
    decision = C13E_GATE.check(execution_request())

    assert decision.enforcement_result == "ALLOWED"
    assert decision.flow == (
        "C08 Module Adapter",
        "C13E Execution Flow Gate",
        "C12 Approval Gate",
        "C14 External Dependency Gate",
        "C09 Execution Provider",
        "C10 Sandbox",
    )
    assert decision.kill_switch_checked is True
    assert decision.c08_allowed is True
    assert decision.c12_allowed is True
    assert decision.c14_allowed is True
    assert decision.c09_allowed is True
    assert decision.c10_allowed is True
    assert decision.c09_execution_bypass_blocked is True
    assert decision.c10_sandbox_bypass_blocked is True
    assert decision.c12_approval_bypass_blocked is True
    assert decision.c14_external_dependency_bypass_blocked is True
    assert decision.c13_bypass_blocked is True
    assert decision.no_execution_leak is True
    assert decision.no_external_provider_call is True
    assert decision.no_runtime_execution is True
    assert decision.no_production_impact is True


def test_c13e_gate_blocks_global_kill_switch() -> None:
    set_global_kill_switch(
        global_kill_switch=True,
        actor_role="owner",
        actor_user_id=1,
    )
    try:
        with pytest.raises(
            ExecutionFlowGateBlockedError,
            match="global_kill_switch_enabled",
        ):
            C13E_GATE.check(bypassed_request())
    finally:
        set_global_kill_switch(
            global_kill_switch=False,
            actor_role="owner",
            actor_user_id=1,
        )


def test_c13e_gate_blocks_c12_approval_bypass() -> None:
    with pytest.raises(
        ExecutionFlowGateBlockedError,
        match="c12_approval_bypass",
    ):
        C13E_GATE.check(
            bypassed_request(
                module_key="admin.permissions",
                adapter_key="admin.permissions.adapter",
                action_key="admin.permissions.manage",
                provider_key="core.contract_only_provider",
                provider_type="contract_only_provider",
                risk_level="critical",
                required_permission="permissions.manage",
                approval_status="not_required",
            )
        )


def test_c13e_gate_blocks_c09_provider_mismatch_bypass() -> None:
    with pytest.raises(
        ExecutionFlowGateBlockedError,
        match="c09_provider_module_mismatch",
    ):
        C13E_GATE.check(
            bypassed_request(
                provider_key="core.mock_provider",
                provider_type="mock_provider",
            )
        )


def test_c13e_gate_blocks_c14_unknown_external_dependency() -> None:
    with pytest.raises(
        ExecutionFlowGateBlockedError,
        match="c14d_unknown_service_quarantined",
    ):
        C13E_GATE.check(
            bypassed_request(
                module_key="integration.n8n_test_bridge",
                adapter_key="integration.n8n_test_bridge.adapter",
                action_key="integration.n8n_test_bridge.test_run.declare",
                provider_key="future.live_provider",
                provider_type="future_live_provider",
                required_permission="jobs.create",
            )
        )


def test_c13e_gate_blocks_c10_sandbox_request_mismatch() -> None:
    with pytest.raises(
        ExecutionFlowGateBlockedError,
        match="c10_sandbox_request_mismatch",
    ):
        C13E_GATE.check(
            SandboxRequest.model_construct(
                c09_execution_request=bypassed_request(),
                module_key="admin.users",
                adapter_key="business.products.placeholder.adapter",
                provider_key="core.no_op_provider",
                provider_type="no_op_provider",
                action_key="business.products.placeholder.prepare",
                risk_level="medium",
                source_trust_zone="c09_execution_provider",
                target_trust_zone="c10_sandbox",
            ),
            integration_point="c10_sandbox_entry",
        )


def test_c13e_gate_blocks_direct_c10_runtime_bypass() -> None:
    with pytest.raises(
        ExecutionFlowGateBlockedError,
        match="module_switch_not_registered",
    ):
        SandboxRuntime().handle_execution_request(
            bypassed_request(
                module_key="business.missing",
                adapter_key="business.missing.adapter",
                action_key="business.missing.run",
            )
        )
