from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ..schemas.execution_router import (
    ExecutionOrgContextSnapshot,
    ExecutionPermissionSnapshot,
    ExecutionPlan,
    ExecutionRouterResponse,
    ExecutionRouterValidationResult,
    ExecutionRuntimeMode,
)
from .execution_flow_gate import MODE_AWARE_GATE
from .module_adapter_registry import get_adapter_contract
from .provider_resolver import ProviderResolver


class ExecutionRouterError(ValueError):
    pass


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _field(value: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def _decision_state(value: Any) -> str:
    if value is None:
        return "deny"
    decision = _field(value, "decision")
    if decision in {"allow", "deny", "partial"}:
        return str(decision)
    if _field(value, "allowed") is True:
        return "allow"
    if _field(value, "partial") is True:
        return "partial"
    return "deny"


def _permission_snapshot(source: str, value: Any) -> ExecutionPermissionSnapshot:
    return ExecutionPermissionSnapshot(
        source=source,
        decision=_decision_state(value),
        reason=str(_field(value, "reason", "Permission decision unavailable.")),
        denial_code=_field(value, "denial_code"),
        permission_key=_field(value, "permission_key"),
    )


def _requested_mode(
    *,
    payload: Mapping[str, Any],
    context: Mapping[str, Any],
) -> ExecutionRuntimeMode:
    candidate = (
        payload.get("execution_mode")
        or payload.get("mode")
        or context.get("execution_mode")
        or "mock"
    )
    return candidate if candidate in {"mock", "staging", "live"} else "mock"


def _org_context_snapshot(
    *,
    org_id: str,
    context: Mapping[str, Any],
) -> ExecutionOrgContextSnapshot | None:
    org_context = context.get("org_context")
    if org_context is None and org_id:
        return ExecutionOrgContextSnapshot(
            org_id=org_id,
            user_id=str(context["user_id"]) if context.get("user_id") else None,
            role=str(context["role"]) if context.get("role") else None,
            request_id=(
                str(context["request_id"]) if context.get("request_id") else None
            ),
            c18h_context_applied=bool(context.get("c18h_context_applied", False)),
        )
    if org_context is None:
        return None
    resolved_org_id = str(_field(org_context, "org_id", org_id))
    if not resolved_org_id:
        return None
    return ExecutionOrgContextSnapshot(
        org_id=resolved_org_id,
        user_id=(
            str(_field(org_context, "user_id"))
            if _field(org_context, "user_id") is not None
            else None
        ),
        role=(
            str(_field(org_context, "role"))
            if _field(org_context, "role") is not None
            else None
        ),
        request_id=(
            str(_field(org_context, "request_id"))
            if _field(org_context, "request_id") is not None
            else None
        ),
        c18h_context_applied=True,
    )


class ExecutionRouter:
    """Unified C08-C15 execution router.

    Adapters and workflow dispatchers call this boundary to build a validated
    execution plan. The router does not perform live external calls.
    """

    def __init__(
        self,
        *,
        provider_resolver: ProviderResolver | None = None,
    ) -> None:
        self.provider_resolver = provider_resolver or ProviderResolver()

    def receive_request(
        self,
        *,
        org_id: str,
        module_id: str,
        action: str,
        payload: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> ExecutionRouterResponse:
        safe_payload = dict(payload or {})
        safe_context = dict(context or {})
        mode = _requested_mode(payload=safe_payload, context=safe_context)
        adapter = get_adapter_contract(str(safe_context.get("adapter_key") or ""))
        if adapter is None:
            adapter = next(
                (
                    candidate
                    for candidate in self._adapters_for_module(module_id)
                    if any(
                        contract.action_key == action
                        for contract in candidate.action_contracts
                    )
                ),
                None,
            )

        errors: list[str] = []
        warnings: list[str] = []
        action_contract = None
        if adapter is None:
            errors.append("C08 adapter contract was not found for module/action.")
            adapter_key = "missing.adapter"
            risk_level = "medium"
            required_permission = "missing.permission"
            module_policy = "adapter_missing"
        else:
            adapter_key = adapter.adapter_key
            module_policy = adapter.adapter_status
            if adapter.module_key != module_id:
                errors.append("C08 adapter module_id does not match request.")
            action_contract = next(
                (
                    contract
                    for contract in adapter.action_contracts
                    if contract.action_key == action
                ),
                None,
            )
            if action_contract is None:
                errors.append("C08 action contract was not found.")
                risk_level = "medium"
                required_permission = "missing.permission"
            else:
                risk_level = action_contract.risk_level
                required_permission = action_contract.required_permission
                if action_contract.executable_before_c09:
                    errors.append("C08 adapter action attempted to execute directly.")
                if action_contract.execution_type not in {"mock", "no_op"}:
                    warnings.append("C08 action execution_type is routed, not executed.")
            if adapter.adapter_status in {"draft", "disabled", "deprecated"}:
                errors.append(f"C08 adapter status blocks routing: {adapter.adapter_status}.")
            elif adapter.adapter_status == "adapter_pending":
                warnings.append("C08 adapter is pending; router can build a plan only.")

        resolution = self.provider_resolver.resolve(
            module_id=module_id,
            action=action,
            requested_mode=mode,
        )
        if resolution.provider is None:
            errors.append(resolution.reason)
            provider_readiness = "mock"
        else:
            provider_readiness = resolution.provider.provider_readiness

        org_snapshot = _org_context_snapshot(org_id=org_id, context=safe_context)
        c18f_decision = (
            safe_context.get("c18f_permission_decision")
            or safe_context.get("permission_decision")
            or safe_context.get("c18f")
        )
        c05_decision = (
            safe_context.get("c05_permission_result")
            or safe_context.get("c05_permission_decision")
            or safe_context.get("c05")
        )
        if org_snapshot is None or not org_snapshot.c18h_context_applied:
            errors.append("C18H org context was not supplied to ExecutionRouter.")
        if c18f_decision is None:
            errors.append("C18F permission decision was not supplied to ExecutionRouter.")
        if c05_decision is None:
            errors.append("C05 permission result was not supplied to ExecutionRouter.")

        gate_decision = MODE_AWARE_GATE.evaluate_mode(
            c18f_permission_decision=c18f_decision,
            c05_permission_result=c05_decision,
            org_context=org_snapshot,
            provider_readiness=provider_readiness,
            requested_mode=mode,
            selected_mode=resolution.selected_mode,
            module_policy=module_policy,
        )
        validation = ExecutionRouterValidationResult(
            status="valid" if not errors else "invalid",
            valid=not errors,
            errors=errors,
            warnings=warnings,
            c08_adapter_validated=adapter is not None and action_contract is not None,
            c05_permission_engine_checked=c05_decision is not None,
            c18f_permission_isolation_checked=c18f_decision is not None,
        )
        plan = ExecutionPlan(
            plan_id=_stable_id(
                "execution_plan",
                {
                    "org_id": org_id,
                    "module_id": module_id,
                    "adapter_key": adapter_key,
                    "action": action,
                    "mode": gate_decision.execution_mode_selected or mode,
                    "provider_key": (
                        resolution.provider.provider_key
                        if resolution.provider is not None
                        else None
                    ),
                },
            ),
            org_id=org_id,
            module_id=module_id,
            adapter_key=adapter_key,
            action=action,
            execution_mode=gate_decision.execution_mode_selected or mode,
            risk_level=risk_level,
            required_permission=required_permission,
            created_at=datetime.now(UTC),
        )
        accepted = validation.valid and gate_decision.execution_mode_allowed
        return ExecutionRouterResponse(
            accepted=accepted,
            execution_plan=plan,
            selected_provider=resolution.selection,
            gate_decision=gate_decision,
            validation_result=validation,
            context=org_snapshot,
            permission_decisions=(
                _permission_snapshot("C18F", c18f_decision),
                _permission_snapshot("C05", c05_decision),
            ),
            dispatch_ready=accepted and gate_decision.decision == "allow",
        )

    def _adapters_for_module(self, module_id: str):
        from .module_adapter_registry import list_adapter_contracts

        return [
            adapter
            for adapter in list_adapter_contracts()
            if adapter.module_key == module_id
        ]


EXECUTION_ROUTER = ExecutionRouter()
