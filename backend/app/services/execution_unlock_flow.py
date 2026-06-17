from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from ..schemas.live_gate import (
    ApprovalUnlockDecision,
    CanaryRouteDecision,
    ExecutionUnlockResponse,
    LiveAuditEnforcementResult,
    LiveExecutionMode,
)
from .c12_approval_unlock import C12ApprovalUnlockTokenController
from .canary_rollout import CanaryRolloutSystem
from .live_audit_enforcement import LiveAuditEnforcer
from .live_gating_controller import LiveGatingController
from .pre_live_validation import PreLiveValidationEngine


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


def _requested_mode(
    *,
    payload: Mapping[str, Any],
    context: Mapping[str, Any],
) -> LiveExecutionMode:
    candidate = (
        payload.get("execution_mode")
        or payload.get("mode")
        or context.get("execution_mode")
        or "mock"
    )
    return candidate if candidate in {"mock", "staging", "live"} else "mock"


def _string_value(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        candidate = str(value).strip()
        if candidate:
            return candidate
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    return str(value)


class ExecutionUnlockFlow:
    """Only execution entry that may route a request toward provider selection."""

    def request_execution(
        self,
        *,
        org_id: str,
        module_id: str,
        action: str,
        payload: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        db: Session | None = None,
    ) -> ExecutionUnlockResponse:
        safe_payload = dict(payload or {})
        safe_context = dict(context or {})
        requested_mode = _requested_mode(payload=safe_payload, context=safe_context)
        execution_id = _string_value(
            safe_payload.get("execution_id"),
            safe_context.get("execution_id"),
        )
        trace_id = _string_value(
            safe_payload.get("trace_id"),
            safe_context.get("trace_id"),
            safe_context.get("request_id"),
        )

        policy_allowed = self._policy_allowed(safe_context)
        approval = self._approval_decision(
            db=db,
            org_id=org_id,
            requested_mode=requested_mode,
            approval_id=_string_value(
                safe_payload.get("approval_id"),
                safe_context.get("approval_id"),
            ),
            execution_id=execution_id,
            unlock_token=_string_value(
                safe_payload.get("unlock_token"),
                safe_context.get("unlock_token"),
            ),
        )
        canary = CanaryRolloutSystem(db).route(
            org_id=org_id,
            module_id=module_id,
            requested_mode=requested_mode,
            execution_id=execution_id,
        )
        pre_live_passed = self._pre_live_passed(
            db=db,
            requested_mode=requested_mode,
            approval=approval,
            canary=canary,
        )
        live_gate = LiveGatingController(db).evaluate(
            org_id=org_id,
            module_id=module_id,
            requested_mode=requested_mode,
            approval=approval,
            canary=canary,
            pre_live_validation_passed=pre_live_passed,
        )
        audit = self._audit_result(
            db=db,
            org_id=org_id,
            module_id=module_id,
            action=action,
            requested_mode=requested_mode,
            trace_id=trace_id,
            execution_id=execution_id,
            gate_allowed=live_gate.allowed,
            payload=safe_payload,
            context=safe_context,
        )

        if not policy_allowed:
            return self._response(
                status="denied",
                reason="C18/C05 policy checks denied execution unlock.",
                policy_allowed=False,
                approval=approval,
                canary=canary,
                live_gate=live_gate,
                audit=audit,
            )
        if requested_mode == "live" and audit.status == "failed":
            return self._response(
                status="denied",
                reason=audit.reason,
                policy_allowed=True,
                approval=approval,
                canary=canary,
                live_gate=live_gate,
                audit=audit,
            )
        if live_gate.decision == "DENY":
            return self._response(
                status="denied",
                reason=live_gate.reason,
                policy_allowed=True,
                approval=approval,
                canary=canary,
                live_gate=live_gate,
                audit=audit,
            )

        effective_payload = {
            **safe_payload,
            "execution_mode": live_gate.execution_mode_effective,
            "execution_id": execution_id,
            "trace_id": trace_id,
        }
        router_response = self._provider_router(
            org_id=org_id,
            module_id=module_id,
            action=action,
            payload=effective_payload,
            context={
                **safe_context,
                "execution_entrypoint": "ExecutionUnlockFlow",
                "execution_id": execution_id,
                "trace_id": trace_id,
                "approval_unlock_decision": approval,
                "live_gate_decision": live_gate,
                "canary_decision": canary,
            },
        )
        status = "staging_only" if live_gate.decision == "STAGING_ONLY" else "accepted"
        return self._response(
            status=status,
            reason=(
                "Execution routed to staging by live gate."
                if status == "staging_only"
                else "Execution unlocked and routed to provider router."
            ),
            policy_allowed=True,
            approval=approval,
            canary=canary,
            live_gate=live_gate,
            audit=audit,
            router_response=router_response,
            provider_router_called=True,
        )

    def _approval_decision(
        self,
        *,
        db: Session | None,
        org_id: str,
        requested_mode: LiveExecutionMode,
        approval_id: str | None,
        execution_id: str | None,
        unlock_token: str | None,
    ) -> ApprovalUnlockDecision:
        if requested_mode != "live":
            return C12ApprovalUnlockTokenController.not_required(
                execution_id=execution_id
            )
        if db is None:
            return ApprovalUnlockDecision(
                decision="missing",
                approval_id=approval_id,
                execution_id=execution_id,
                unlock_id=None,
                unlock_token=None,
                status="missing",
                reason="Live execution requires DB-backed C12 unlock validation.",
            )
        return C12ApprovalUnlockTokenController(db).validate_unlock(
            org_id=org_id,
            approval_id=approval_id,
            execution_id=execution_id,
            unlock_token=unlock_token,
        )

    def _policy_allowed(self, context: Mapping[str, Any]) -> bool:
        c18f_decision = (
            context.get("c18f_permission_decision")
            or context.get("permission_decision")
            or context.get("c18f")
        )
        c05_decision = (
            context.get("c05_permission_result")
            or context.get("c05_permission_decision")
            or context.get("c05")
        )
        return (
            _decision_state(c18f_decision) == "allow"
            and _decision_state(c05_decision) == "allow"
        )

    def _pre_live_passed(
        self,
        *,
        db: Session | None,
        requested_mode: LiveExecutionMode,
        approval: ApprovalUnlockDecision,
        canary: CanaryRouteDecision,
    ) -> bool:
        if requested_mode != "live" or canary.routed_mode != "live":
            return True
        if not approval.unlocked or db is None:
            return False
        return PreLiveValidationEngine(db).run().passed

    def _audit_result(
        self,
        *,
        db: Session | None,
        org_id: str,
        module_id: str,
        action: str,
        requested_mode: LiveExecutionMode,
        trace_id: str | None,
        execution_id: str | None,
        gate_allowed: bool,
        payload: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> LiveAuditEnforcementResult:
        if requested_mode != "live":
            return LiveAuditEnforcer.skipped()
        return LiveAuditEnforcer(db).enforce(
            org_id=org_id,
            module_id=module_id,
            action=action,
            trace_id=trace_id,
            execution_id=execution_id,
            status="success" if gate_allowed else "failed",
            payload=_json_safe(dict(payload)),
            metadata={
                "context": _json_safe(dict(context)),
                "gate_allowed": gate_allowed,
            },
        )

    def _provider_router(
        self,
        *,
        org_id: str,
        module_id: str,
        action: str,
        payload: Mapping[str, Any],
        context: Mapping[str, Any],
    ):
        from .execution_router import EXECUTION_ROUTER

        return EXECUTION_ROUTER.receive_request(
            org_id=org_id,
            module_id=module_id,
            action=action,
            payload=payload,
            context=context,
        )

    def _response(
        self,
        *,
        status: str,
        reason: str,
        policy_allowed: bool,
        approval: ApprovalUnlockDecision,
        canary: CanaryRouteDecision,
        live_gate,
        audit: LiveAuditEnforcementResult,
        router_response=None,
        provider_router_called: bool = False,
    ) -> ExecutionUnlockResponse:
        return ExecutionUnlockResponse(
            status=status,  # type: ignore[arg-type]
            reason=reason,
            policy_allowed=policy_allowed,
            approval=approval,
            canary=canary,
            live_gate=live_gate,
            audit=audit,
            router_response=router_response,
            provider_router_called=provider_router_called,
        )


EXECUTION_UNLOCK_FLOW = ExecutionUnlockFlow()
