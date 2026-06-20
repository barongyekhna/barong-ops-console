from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.core.module_switches import MODULE_SWITCH_REGISTRY_V1
from backend.app.schemas.approval import ApprovalRequestCreate
from backend.app.schemas.execution_provider import ExecutionRequestContractV1
from backend.app.schemas.module_switch import ModuleSwitchRegistryRecord
from backend.app.sandbox.types import SandboxRequest
from backend.app.services.emergency_kill_switch import (
    EmergencyKillSwitchBlockedError,
    EmergencyKillSwitchPermissionError,
    set_global_kill_switch,
)
from backend.app.services.module_registry import list_module_manifests
from backend.app.services.module_switch_policy_engine import (
    ModuleSwitchPolicyEngine,
    build_effective_module_switch_registry,
)
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


def on_switch(module_key: str = "admin.users") -> dict[str, object]:
    return {
        "module_key": module_key,
        "state": "ON",
        "enabled": True,
        "disabled_reason": None,
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
    effective_keys = {
        record.module_key for record in build_effective_module_switch_registry()
    }

    assert registry_keys == module_keys
    assert effective_keys == module_keys
    for raw_record in MODULE_SWITCH_REGISTRY_V1:
        record = ModuleSwitchRegistryRecord.model_validate(raw_record)
        assert record.state == "ON"
        assert record.enabled is True
        assert record.disabled_reason is None


def test_module_switch_policy_engine_applies_recursive_cascade() -> None:
    engine = ModuleSwitchPolicyEngine(
        registry=[
            off_switch("admin.users"),
            on_switch("admin.permissions"),
            on_switch("admin.settings"),
        ],
        dependency_rules=[
            {
                "parent_module_key": "admin.users",
                "child_module_key": "admin.permissions",
                "reason": "Permission management depends on users.",
            },
            {
                "parent_module_key": "admin.permissions",
                "child_module_key": "admin.settings",
                "reason": "Settings depend on permissions.",
            },
        ],
        group_policies=[],
        inheritance_policies=[],
    )

    decisions = {
        decision.module_key: decision for decision in engine.evaluate()
    }

    assert decisions["admin.permissions"].state == "OFF"
    assert decisions["admin.permissions"].policy_source == "dependency_cascade"
    assert decisions["admin.permissions"].cascaded_from == ("admin.users",)
    assert decisions["admin.settings"].state == "OFF"
    assert decisions["admin.settings"].policy_source == "dependency_cascade"
    assert decisions["admin.settings"].cascaded_from == ("admin.permissions",)

    batch_on_decisions = {
        decision.module_key: decision
        for decision in engine.evaluate(
            batch_switches=[
                {
                    "module_keys": ("admin.permissions",),
                    "state": "ON",
                    "disabled_reason": None,
                }
            ]
        )
    }

    assert batch_on_decisions["admin.permissions"].state == "OFF"
    assert (
        batch_on_decisions["admin.permissions"].policy_source
        == "dependency_cascade"
    )


def test_module_switch_policy_engine_group_switch_batches_members() -> None:
    engine = ModuleSwitchPolicyEngine(
        registry=[
            on_switch("business.reviews"),
            on_switch("business.artifacts"),
        ],
        dependency_rules=[],
        group_policies=[
            {
                "group_key": "business.ops",
                "module_keys": ("business.reviews", "business.artifacts"),
                "default_state": "ON",
                "disabled_reason": None,
                "batch_control_supported": True,
            }
        ],
        inheritance_policies=[],
    )

    decisions = {
        decision.module_key: decision
        for decision in engine.evaluate(
            group_switches=[
                {
                    "group_key": "business.ops",
                    "state": "OFF",
                    "disabled_reason": "Disabled by group switch test.",
                }
            ]
        )
    }

    assert decisions["business.reviews"].state == "OFF"
    assert decisions["business.reviews"].policy_source == "group_switch"
    assert decisions["business.reviews"].group_keys == ("business.ops",)
    assert decisions["business.artifacts"].state == "OFF"
    assert decisions["business.artifacts"].policy_source == "group_switch"


def test_module_switch_policy_engine_inheritance_override_vs_inherit() -> None:
    engine = ModuleSwitchPolicyEngine(
        registry=[
            on_switch("admin.users"),
            on_switch("admin.permissions"),
        ],
        dependency_rules=[],
        group_policies=[
            {
                "group_key": "admin.core",
                "module_keys": ("admin.users", "admin.permissions"),
                "default_state": "OFF",
                "disabled_reason": "Disabled by inherited group policy.",
                "batch_control_supported": True,
            }
        ],
        inheritance_policies=[
            {
                "module_key": "admin.users",
                "group_keys": ("admin.core",),
                "policy_mode": "inherit",
                "parent_off_overrides_module": True,
            },
            {
                "module_key": "admin.permissions",
                "group_keys": ("admin.core",),
                "policy_mode": "override",
                "parent_off_overrides_module": True,
            },
        ],
    )

    decisions = {
        decision.module_key: decision for decision in engine.evaluate()
    }

    assert decisions["admin.users"].state == "OFF"
    assert decisions["admin.users"].policy_source == "group_default"
    assert decisions["admin.users"].inherited_from_group == "admin.core"
    assert decisions["admin.permissions"].state == "ON"
    assert decisions["admin.permissions"].policy_source == "module"


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


def test_c13d_global_kill_switch_ignores_on_module_switches() -> None:
    gate = ModuleSwitchRuntimeGate(
        registry=[on_switch("admin.users")],
        global_kill_switch=True,
    )
    decision = gate.decision(
        "admin.users",
        integration_point="c09_execution_request",
    )

    assert gate.check("admin.users") == "OFF"
    assert decision.switch_status == "OFF"
    assert decision.enforcement_result == "BLOCKED"
    assert decision.state == "GLOBAL_KILL_SWITCH"
    assert decision.reason == "global_kill_switch_enabled"
    assert decision.execution_chain_stopped is True
    assert decision.approval_request_allowed is False
    assert decision.execution_request_allowed is False
    assert decision.sandbox_entry_allowed is False

    with pytest.raises(
        ModuleSwitchRuntimeBlockedError,
        match="global_kill_switch_enabled",
    ):
        gate.enforce_before_c09_execution_request("admin.users")


def test_c13d_global_kill_switch_toggle_requires_system_owner() -> None:
    with pytest.raises(
        EmergencyKillSwitchPermissionError,
        match="system_owner_required",
    ):
        set_global_kill_switch(
            global_kill_switch=True,
            actor_role="viewer",
            actor_user_id=1001,
        )


def test_c13d_global_kill_switch_blocks_c13c_policy_engine() -> None:
    set_global_kill_switch(
        global_kill_switch=True,
        actor_role="owner",
        actor_user_id=1,
    )
    try:
        with pytest.raises(
            EmergencyKillSwitchBlockedError,
            match="global_kill_switch_enabled",
        ):
            ModuleSwitchPolicyEngine().evaluate()
    finally:
        set_global_kill_switch(
            global_kill_switch=False,
            actor_role="owner",
            actor_user_id=1,
        )


def test_c13d_global_kill_switch_blocks_c12_c09_and_c10() -> None:
    set_global_kill_switch(
        global_kill_switch=True,
        actor_role="owner",
        actor_user_id=1,
    )
    try:
        with pytest.raises(ValidationError, match="global_kill_switch_enabled"):
            ApprovalRequestCreate(
                approval_id="approval-c13d-blocked",
                execution_id="execution-c13d-blocked",
                module_key="admin.users",
                adapter_key="admin.users.adapter",
                action_key="admin.users.read",
                risk_level="high",
                execution_type="real",
                reason="This request must be blocked by C13D.",
            )

        with pytest.raises(ValidationError, match="global_kill_switch_enabled"):
            execution_request(module_key="admin.users")

        request = ExecutionRequestContractV1.model_construct(
            execution_id="exec_c13d_bypass",
            request_id="req_c13d_bypass",
            module_key="admin.users",
            adapter_key="admin.users.adapter",
            action_key="admin.users.read",
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

        with pytest.raises(ValidationError, match="global_kill_switch_enabled"):
            SandboxRequest(
                c09_execution_request=request,
                module_key="admin.users",
                adapter_key="admin.users.adapter",
                provider_key="core.mock_provider",
                provider_type="mock_provider",
                action_key="admin.users.read",
                risk_level="medium",
            )
    finally:
        set_global_kill_switch(
            global_kill_switch=False,
            actor_role="owner",
            actor_user_id=1,
        )


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
