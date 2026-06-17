from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ..schemas.execution_flow_gate import (
    ExecutionFlowGateDecision,
    ExecutionFlowGateIntegrationPoint,
)
from ..schemas.execution_router import (
    ExecutionModeAwareGateDecision,
    ExecutionRuntimeMode,
)
from .emergency_kill_switch import (
    EmergencyKillSwitchGate,
    GLOBAL_KILL_SWITCH_BLOCK_REASON,
)
from .external_dependency_governance import C14D_GATE
from .execution_provider_registry import get_execution_provider_contract
from .module_adapter_registry import get_adapter_contract
from .module_switch_runtime_gate import ModuleSwitchRuntimeGate


MISSING_VALUE = "missing"
BLOCKED_PROVIDER_STATUSES = frozenset(
    {
        "draft",
        "provider_pending",
        "provider_unavailable",
        "disabled",
        "deprecated",
    }
)
FUTURE_PROVIDER_TYPES = frozenset(
    {
        "local_backend_provider",
        "queue_provider",
        "webhook_provider",
        "scheduled_provider",
        "future_live_provider",
    }
)
RUNTIME_STATUSES = frozenset(
    {
        "accepted",
        "queued",
        "running",
        "succeeded",
        "retry_scheduled",
    }
)


class ExecutionFlowGateBlockedError(ValueError):
    def __init__(self, decision: ExecutionFlowGateDecision) -> None:
        self.decision = decision
        message = f"BLOCKED by C13E Execution Flow Gate: {decision.reason}"
        if decision.reason.startswith("module_switch_"):
            message = f"{message}; BLOCKED by Module Switch"
        super().__init__(message)


class ExecutionFlowGate:
    """C13E final execution entry gate.

    C13E does not execute work. It validates that a request can only continue
    through the sealed C08 -> C13E -> C12 -> C14D -> C09 -> C10 contract chain.
    """

    def __init__(
        self,
        *,
        module_switch_gate: ModuleSwitchRuntimeGate | None = None,
        kill_switch_gate: EmergencyKillSwitchGate | None = None,
    ) -> None:
        self._module_switch_gate = module_switch_gate
        self._kill_switch_gate = kill_switch_gate

    def check(
        self,
        execution_request: Any,
        *,
        integration_point: ExecutionFlowGateIntegrationPoint = (
            "c13e_execution_flow_gate"
        ),
    ) -> ExecutionFlowGateDecision:
        decision = self.decision(
            execution_request,
            integration_point=integration_point,
        )
        if decision.enforcement_result == "BLOCKED":
            raise ExecutionFlowGateBlockedError(decision)
        return decision

    def decision(
        self,
        execution_request: Any,
        *,
        integration_point: ExecutionFlowGateIntegrationPoint = (
            "c13e_execution_flow_gate"
        ),
    ) -> ExecutionFlowGateDecision:
        evaluated_at = datetime.now(UTC)
        request = _unwrap_execution_request(execution_request)
        identity = _request_identity(request)
        kill_switch_gate = self._kill_switch_gate or EmergencyKillSwitchGate()
        module_switch_gate = self._module_switch_gate or ModuleSwitchRuntimeGate()

        kill_switch_decision = kill_switch_gate.decision(
            integration_point="c13e_execution_flow_gate",
        )
        if kill_switch_decision.enforcement_result == "BLOCKED":
            return self._blocked(
                identity=identity,
                reason=GLOBAL_KILL_SWITCH_BLOCK_REASON,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                kill_switch_blocked=True,
                c08_allowed=False,
                c12_allowed=False,
                c14_allowed=False,
                c09_allowed=False,
                c10_allowed=False,
                c13_allowed=False,
            )

        missing_fields = [
            field_name
            for field_name, value in identity.items()
            if value == MISSING_VALUE
        ]
        if missing_fields:
            return self._blocked(
                identity=identity,
                reason="c13e_execution_request_invalid",
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=False,
                c12_allowed=False,
                c14_allowed=False,
                c09_allowed=False,
                c10_allowed=False,
                c13_allowed=False,
            )

        module_switch_decision = module_switch_gate.decision(
            identity["module_key"],
            integration_point="c13e_execution_flow_gate",
        )
        if module_switch_decision.enforcement_result == "BLOCKED":
            return self._blocked(
                identity=identity,
                reason=module_switch_decision.reason,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=False,
                c12_allowed=False,
                c14_allowed=False,
                c09_allowed=False,
                c10_allowed=False,
                c13_allowed=False,
            )

        downstream_decision = self._first_blocked_downstream_switch(
            identity,
            module_switch_gate=module_switch_gate,
        )
        if downstream_decision is not None:
            return self._blocked(
                identity=identity,
                reason=downstream_decision.reason,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=False,
                c12_allowed=False,
                c14_allowed=False,
                c09_allowed=False,
                c10_allowed=False,
                c13_allowed=False,
            )

        sandbox_envelope_reason = self._sandbox_envelope_block_reason(
            execution_request,
            request,
        )
        if sandbox_envelope_reason is not None:
            return self._blocked(
                identity=identity,
                reason=sandbox_envelope_reason,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=True,
                c12_allowed=True,
                c14_allowed=True,
                c09_allowed=True,
                c10_allowed=False,
                c13_allowed=True,
            )

        c08_reason = self._c08_block_reason(request, identity)
        if c08_reason is not None:
            return self._blocked(
                identity=identity,
                reason=c08_reason,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=False,
                c12_allowed=False,
                c14_allowed=False,
                c09_allowed=False,
                c10_allowed=False,
                c13_allowed=True,
            )

        c12_reason = self._c12_block_reason(request, identity)
        if c12_reason is not None:
            return self._blocked(
                identity=identity,
                reason=c12_reason,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=True,
                c12_allowed=False,
                c14_allowed=False,
                c09_allowed=False,
                c10_allowed=False,
                c13_allowed=True,
            )

        c14_reason = self._c14_block_reason(request)
        if c14_reason is not None:
            return self._blocked(
                identity=identity,
                reason=c14_reason,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=True,
                c12_allowed=True,
                c14_allowed=False,
                c09_allowed=False,
                c10_allowed=False,
                c13_allowed=True,
            )

        c09_reason = self._c09_block_reason(request, identity)
        if c09_reason is not None:
            return self._blocked(
                identity=identity,
                reason=c09_reason,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=True,
                c12_allowed=True,
                c14_allowed=True,
                c09_allowed=False,
                c10_allowed=False,
                c13_allowed=True,
            )

        c10_reason = self._c10_block_reason(request)
        if c10_reason is not None:
            return self._blocked(
                identity=identity,
                reason=c10_reason,
                evaluated_at=evaluated_at,
                integration_point=integration_point,
                c08_allowed=True,
                c12_allowed=True,
                c14_allowed=True,
                c09_allowed=True,
                c10_allowed=False,
                c13_allowed=True,
            )

        return ExecutionFlowGateDecision(
            integration_point=integration_point,
            enforcement_result="ALLOWED",
            reason="c13e_execution_flow_allowed",
            evaluated_at=evaluated_at,
            **identity,
            c08_allowed=True,
            c12_allowed=True,
            c14_allowed=True,
            c09_allowed=True,
            c10_allowed=True,
            c13_allowed=True,
            execution_chain_stopped=False,
            approval_request_allowed=True,
            execution_request_allowed=True,
            sandbox_entry_allowed=True,
        )

    def _first_blocked_downstream_switch(
        self,
        identity: dict[str, str],
        *,
        module_switch_gate: ModuleSwitchRuntimeGate,
    ):
        for integration_point in (
            "c12_approval_request",
            "c14_external_dependency_gate",
            "c09_execution_request",
            "c10_sandbox_entry",
        ):
            decision = module_switch_gate.decision(
                identity["module_key"],
                integration_point=integration_point,
            )
            if decision.enforcement_result == "BLOCKED":
                return decision
        return None

    def _sandbox_envelope_block_reason(
        self,
        original_request: Any,
        c09_request: Any,
    ) -> str | None:
        sandbox_request = _sandbox_request_envelope(original_request)
        if sandbox_request is None:
            return None
        for field_name in (
            "module_key",
            "adapter_key",
            "provider_key",
            "provider_type",
            "action_key",
            "risk_level",
        ):
            if _field(sandbox_request, field_name) != _field(c09_request, field_name):
                return "c10_sandbox_request_mismatch"
        if _field(sandbox_request, "source_trust_zone") != "c09_execution_provider":
            return "c10_sandbox_source_bypass"
        if _field(sandbox_request, "target_trust_zone") != "c10_sandbox":
            return "c10_sandbox_target_bypass"
        return None

    def _c08_block_reason(
        self,
        request: Any,
        identity: dict[str, str],
    ) -> str | None:
        adapter = get_adapter_contract(identity["adapter_key"])
        if adapter is None:
            return "c08_adapter_missing"
        if adapter.module_key != identity["module_key"]:
            return "c08_adapter_module_mismatch"

        action_contract = next(
            (
                contract
                for contract in adapter.action_contracts
                if contract.action_key == identity["action_key"]
            ),
            None,
        )
        if action_contract is None:
            return "c08_action_contract_missing"
        if action_contract.executable_before_c09:
            return "c08_execution_bypass"
        if action_contract.execution_type not in {"mock", "no_op"}:
            return "c08_unsafe_execution_type"
        if action_contract.required_permission != _field(
            request,
            "required_permission",
        ):
            return "c08_permission_mismatch"
        if action_contract.risk_level != _field(request, "risk_level"):
            return "c08_risk_level_mismatch"
        return None

    def _c09_block_reason(
        self,
        request: Any,
        identity: dict[str, str],
    ) -> str | None:
        provider = get_execution_provider_contract(identity["provider_key"])
        if provider is None:
            return "c09_provider_missing"
        if provider.module_key != identity["module_key"]:
            return "c09_provider_module_mismatch"
        if provider.adapter_key != identity["adapter_key"]:
            return "c09_provider_adapter_mismatch"
        if provider.action_key != identity["action_key"]:
            return "c09_provider_action_mismatch"
        if provider.provider_type != _field(request, "provider_type"):
            return "c09_provider_type_mismatch"
        if provider.required_permissions[:1] != [
            _field(request, "required_permission")
        ]:
            return "c09_provider_permission_mismatch"
        if provider.risk_level != _field(request, "risk_level"):
            return "c09_provider_risk_mismatch"
        if provider.provider_status in BLOCKED_PROVIDER_STATUSES:
            return "c09_provider_unavailable"
        if provider.provider_readiness == "live_ready":
            return "c09_live_provider_future_gated"
        if (
            provider.provider_type in FUTURE_PROVIDER_TYPES
            and provider.provider_readiness != "staging_ready"
        ):
            return "c09_future_provider_blocked"
        if provider.executable:
            return "c09_execution_bypass"
        if provider.live_provider_connected or provider.external_endpoint_declared:
            return "c09_external_provider_bypass"
        if provider.callback_policy.callback_supported:
            return "c09_callback_bypass"
        return None

    def _c12_block_reason(
        self,
        request: Any,
        identity: dict[str, str],
    ) -> str | None:
        adapter = get_adapter_contract(identity["adapter_key"])
        provider = get_execution_provider_contract(identity["provider_key"])
        action_contract = None
        if adapter is not None:
            action_contract = next(
                (
                    contract
                    for contract in adapter.action_contracts
                    if contract.action_key == identity["action_key"]
                ),
                None,
            )
        approval_required = (
            _field(request, "risk_level") in {"high", "critical"}
            or bool(provider and provider.requires_approval)
            or bool(provider and provider.approval_requirement.requires_approval)
            or bool(action_contract and action_contract.requires_approval)
        )
        approval_status = _field(request, "approval_status", "not_required")
        if approval_required and approval_status == "not_required":
            return "c12_approval_bypass"
        if approval_required:
            return "c12_approval_not_cleared"
        if approval_status != "not_required":
            return "c12_approval_not_cleared"
        return None

    def _c14_block_reason(self, request: Any) -> str | None:
        decision = C14D_GATE.decision(request)
        if decision.decision != "allow":
            return decision.reason
        return None

    def _c10_block_reason(self, request: Any) -> str | None:
        if _field(request, "status") in RUNTIME_STATUSES:
            return "c10_runtime_status_bypass"
        if (
            _field(request, "secret_binding_status", "not_required")
            != "not_required"
        ):
            return "c10_secret_binding_not_cleared"
        return None

    def _blocked(
        self,
        *,
        identity: dict[str, str],
        reason: str,
        evaluated_at: datetime,
        integration_point: ExecutionFlowGateIntegrationPoint,
        kill_switch_blocked: bool = False,
        c08_allowed: bool,
        c12_allowed: bool,
        c14_allowed: bool,
        c09_allowed: bool,
        c10_allowed: bool,
        c13_allowed: bool,
    ) -> ExecutionFlowGateDecision:
        return ExecutionFlowGateDecision(
            integration_point=integration_point,
            enforcement_result="BLOCKED",
            reason=reason,
            evaluated_at=evaluated_at,
            **identity,
            kill_switch_blocked=kill_switch_blocked,
            c08_allowed=c08_allowed,
            c12_allowed=c12_allowed,
            c14_allowed=c14_allowed,
            c09_allowed=c09_allowed,
            c10_allowed=c10_allowed,
            c13_allowed=c13_allowed,
            execution_chain_stopped=True,
            approval_request_allowed=False,
            execution_request_allowed=False,
            sandbox_entry_allowed=False,
        )


def _unwrap_execution_request(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("c09_execution_request", value)
    return getattr(value, "c09_execution_request", value)


def _sandbox_request_envelope(value: Any) -> Any | None:
    if isinstance(value, Mapping):
        return value if "c09_execution_request" in value else None
    return value if hasattr(value, "c09_execution_request") else None


def _field(value: Any, field_name: str, default: Any = MISSING_VALUE) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def _identity_value(value: Any) -> str:
    if value is None or value == "":
        return MISSING_VALUE
    return str(value)


def _request_identity(request: Any) -> dict[str, str]:
    return {
        "module_key": _identity_value(_field(request, "module_key")),
        "adapter_key": _identity_value(_field(request, "adapter_key")),
        "action_key": _identity_value(_field(request, "action_key")),
        "provider_key": _identity_value(_field(request, "provider_key")),
    }


C13E_GATE = ExecutionFlowGate()


class ExecutionModeAwareGate(ExecutionFlowGate):
    """C13 mode-aware execution gate used by ExecutionRouter.

    Legacy C13E request validation remains available through check/decision on
    ExecutionFlowGate. The new evaluate_mode method gates router-selected
    mock/staging/live execution modes with C18F, C05, org context, provider
    readiness, and module policy inputs.
    """

    def evaluate_mode(
        self,
        *,
        c18f_permission_decision: Any,
        c05_permission_result: Any,
        org_context: Any,
        provider_readiness: str,
        requested_mode: ExecutionRuntimeMode,
        selected_mode: ExecutionRuntimeMode | None,
        module_policy: str = "router_default",
    ) -> ExecutionModeAwareGateDecision:
        c18f_state = _permission_state(c18f_permission_decision)
        c05_state = _permission_state(c05_permission_result)
        if org_context is None:
            return self._mode_decision(
                decision="deny",
                reason="C18 org context is required before execution routing.",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                c18f_state=c18f_state,
                c05_state=c05_state,
                provider_readiness=provider_readiness,
                module_policy=module_policy,
                mode_allowed=False,
            )

        if c18f_state == "deny":
            return self._mode_decision(
                decision="deny",
                reason="C18F permission isolation denied execution routing.",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                c18f_state=c18f_state,
                c05_state=c05_state,
                provider_readiness=provider_readiness,
                module_policy=module_policy,
                mode_allowed=False,
            )
        if c05_state == "deny":
            return self._mode_decision(
                decision="deny",
                reason="C05 unified permission engine denied action permission.",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                c18f_state=c18f_state,
                c05_state=c05_state,
                provider_readiness=provider_readiness,
                module_policy=module_policy,
                mode_allowed=False,
            )
        if c18f_state == "partial" or c05_state == "partial":
            return self._mode_decision(
                decision="partial",
                reason="Permission evaluation returned partial scope coverage.",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                c18f_state=c18f_state,
                c05_state=c05_state,
                provider_readiness=provider_readiness,
                module_policy=module_policy,
                mode_allowed=False,
            )
        if selected_mode is None:
            return self._mode_decision(
                decision="deny",
                reason="ProviderResolver did not select a provider mode.",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                c18f_state=c18f_state,
                c05_state=c05_state,
                provider_readiness=provider_readiness,
                module_policy=module_policy,
                mode_allowed=False,
            )
        if requested_mode == "live" or provider_readiness == "live_ready":
            return self._mode_decision(
                decision="deny",
                reason="Live execution is future-gated and cannot dispatch.",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                c18f_state=c18f_state,
                c05_state=c05_state,
                provider_readiness=provider_readiness,
                module_policy=module_policy,
                mode_allowed=False,
            )
        if selected_mode == "staging" and provider_readiness != "staging_ready":
            return self._mode_decision(
                decision="deny",
                reason="Staging mode requires a staging_ready provider.",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                c18f_state=c18f_state,
                c05_state=c05_state,
                provider_readiness=provider_readiness,
                module_policy=module_policy,
                mode_allowed=False,
            )
        if selected_mode == "mock" and requested_mode == "staging":
            return self._mode_decision(
                decision="partial",
                reason="Staging provider was unavailable; mock fallback is allowed only as partial routing.",
                requested_mode=requested_mode,
                selected_mode=selected_mode,
                c18f_state=c18f_state,
                c05_state=c05_state,
                provider_readiness=provider_readiness,
                module_policy=module_policy,
                mode_allowed=True,
            )
        return self._mode_decision(
            decision="allow",
            reason="Execution mode allowed by C13 mode-aware gate.",
            requested_mode=requested_mode,
            selected_mode=selected_mode,
            c18f_state=c18f_state,
            c05_state=c05_state,
            provider_readiness=provider_readiness,
            module_policy=module_policy,
            mode_allowed=True,
        )

    def _mode_decision(
        self,
        *,
        decision: str,
        reason: str,
        requested_mode: ExecutionRuntimeMode,
        selected_mode: ExecutionRuntimeMode | None,
        c18f_state: str,
        c05_state: str,
        provider_readiness: str,
        module_policy: str,
        mode_allowed: bool,
    ) -> ExecutionModeAwareGateDecision:
        return ExecutionModeAwareGateDecision(
            decision=decision,
            reason=reason,
            execution_mode_requested=requested_mode,
            execution_mode_allowed=mode_allowed,
            execution_mode_selected=selected_mode,
            c18f_decision=c18f_state,
            c05_decision=c05_state,
            provider_readiness=provider_readiness,
            module_policy=module_policy,
        )


def _permission_state(value: Any) -> str:
    if value is None:
        return "deny"
    if isinstance(value, Mapping):
        if value.get("decision") in {"allow", "deny", "partial"}:
            return str(value["decision"])
        if value.get("allowed") is True:
            return "allow"
        if value.get("partial") is True:
            return "partial"
        return "deny"
    decision = getattr(value, "decision", None)
    if decision in {"allow", "deny", "partial"}:
        return str(decision)
    if getattr(value, "allowed", False) is True:
        return "allow"
    if getattr(value, "partial", False) is True:
        return "partial"
    return "deny"


MODE_AWARE_GATE = ExecutionModeAwareGate()
C13E_GATE = MODE_AWARE_GATE


def check_execution_flow_gate(
    execution_request: Any,
    *,
    integration_point: ExecutionFlowGateIntegrationPoint = (
        "c13e_execution_flow_gate"
    ),
) -> ExecutionFlowGateDecision:
    return C13E_GATE.check(
        execution_request,
        integration_point=integration_point,
    )


__all__ = [
    "C13E_GATE",
    "ExecutionFlowGate",
    "ExecutionFlowGateBlockedError",
    "check_execution_flow_gate",
]
