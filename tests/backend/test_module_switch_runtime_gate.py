from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.core.module_switches import MODULE_SWITCH_REGISTRY_V1
from backend.app.schemas.approval import ApprovalRequestCreate
from backend.app.schemas.execution_provider import ExecutionRequestContractV1
from backend.app.schemas.module_switch import ModuleSwitchRegistryRecord
from backend.app.sandbox.types import SandboxRequest
from backend.app.services.module_registry import list_module_manifests
from backend.app.services.module_switch_runtime_gate import (
    ModuleSwitchRuntimeBlockedError,
    ModuleSwitchRuntimeGate,
)


UPDATED_AT = datetime(2026, 6, 14, tzinfo=UTC)


def off_switch(module_key: str = "admin.users") -> dict[str, object]:
    return {
        "module_key": module_key,
        "state": "OFF",
        "enabled": False,
        "disabled_reason": "Disabled by C13B runtime gate test.",
        "updated_at": UPDATED_AT,
    }


def execution_request(
    *,
    module_key: str = "admin.users",
) -> ExecutionRequestContractV1:
    return ExecutionRequestContractV1(
        execution_id="exec_c13b_001",
        request_id="req_c13b_001",
        module_key=module_key,
        adapter_key="admin.users.adapter",
        action_key="admin.users.read",
        actor_user_id=1001,
        target_scope={"module": module_key},
        input_payload={"redacted": True},
        sanitized_input_summary={"shape": "demo"},
        provider_key="core.mock_provider",
        provider_type="mock_provider",
        status="requested",
        risk_level="medium",
        required_permission="users.read",
    )


def test_module_switch_runtime_gate_all_registered_modules_are_explicit() -> None:
    registry_keys = {record["module_key"] for record in MODULE_SWITCH_REGISTRY_V1}
    module_keys = {manifest.module_key for manifest in list_module_manifests()}

    assert registry_keys == module_keys
    for raw_record in MODULE_SWITCH_REGISTRY_V1:
        record = ModuleSwitchRegistryRecord.model_validate(raw_record)
        assert record.state == "ON"
        assert record.enabled is True
        assert record.disabled_reason is None


def test_module_switch_runtime_gate_check_allows_on_modules() -> None:
    gate = ModuleSwitchRuntimeGate()
    decision = gate.enforce_before_c12_approval_request("admin.users")

    assert gate.check("admin.users") == "ON"
    assert decision.switch_status == "ON"
    assert decision.enforcement_result == "ALLOWED"
    assert decision.approval_request_allowed is True
    assert decision.execution_request_allowed is True
    assert decision.sandbox_entry_allowed is True
    assert decision.external_call_allowed is False
    assert decision.production_change_allowed is False


def test_module_switch_runtime_gate_blocks_off_modules() -> None:
    gate = ModuleSwitchRuntimeGate(registry=[off_switch()])
    decision = gate.decision(
        "admin.users",
        integration_point="c09_execution_request",
    )

    assert gate.check("admin.users") == "OFF"
    assert decision.switch_status == "OFF"
    assert decision.enforcement_result == "BLOCKED"
    assert decision.reason == "module_switch_off"
    assert decision.execution_chain_stopped is True
    assert decision.approval_request_allowed is False
    assert decision.execution_request_allowed is False
    assert decision.sandbox_entry_allowed is False

    with pytest.raises(ModuleSwitchRuntimeBlockedError, match="BLOCKED"):
        gate.enforce_before_c09_execution_request("admin.users")


def test_module_switch_runtime_gate_fail_closes_missing_or_invalid_records() -> None:
    missing = ModuleSwitchRuntimeGate().decision("business.missing")
    invalid = ModuleSwitchRuntimeGate(
        registry=[
            {
                "module_key": "admin.users",
                "state": "BROKEN",
                "enabled": True,
                "updated_at": UPDATED_AT,
            }
        ]
    ).decision("admin.users")

    assert missing.switch_status == "OFF"
    assert missing.reason == "module_switch_not_registered"
    assert invalid.switch_status == "OFF"
    assert invalid.reason == "module_switch_invalid_state"


def test_c12_approval_request_is_blocked_before_persistence() -> None:
    with pytest.raises(ValidationError, match="BLOCKED by Module Switch"):
        ApprovalRequestCreate(
            approval_id="approval-c13b-blocked",
            execution_id="execution-c13b-blocked",
            module_key="business.missing",
            adapter_key="business.missing.adapter",
            action_key="business.missing.run",
            risk_level="high",
            execution_type="real",
            reason="This request must be blocked before C12 persistence.",
        )


def test_c09_execution_request_is_blocked_before_contract_generation() -> None:
    with pytest.raises(ValidationError, match="BLOCKED by Module Switch"):
        execution_request(module_key="business.missing")


def test_c10_sandbox_entry_is_blocked_before_sandbox_request() -> None:
    request = ExecutionRequestContractV1.model_construct(
        execution_id="exec_c13b_bypass",
        request_id="req_c13b_bypass",
        module_key="business.missing",
        adapter_key="business.missing.adapter",
        action_key="business.missing.run",
        actor_user_id=1001,
        target_scope={},
        input_payload={},
        sanitized_input_summary={},
        provider_key="core.mock_provider",
        provider_type="mock_provider",
        status="requested",
        risk_level="medium",
        required_permission="users.read",
        approval_status="not_required",
        secret_binding_status="not_required",
        created_at=None,
        accepted_at=None,
        started_at=None,
        finished_at=None,
        cancelled_at=None,
        timeout_at=None,
        result_summary=None,
        artifact_refs=[],
        error_code=None,
        error_message_safe=None,
        operation_log_id=None,
    )

    with pytest.raises(ValidationError, match="BLOCKED by Module Switch"):
        SandboxRequest(
            c09_execution_request=request,
            module_key="business.missing",
            adapter_key="business.missing.adapter",
            provider_key="core.mock_provider",
            provider_type="mock_provider",
            action_key="business.missing.run",
            risk_level="medium",
        )

