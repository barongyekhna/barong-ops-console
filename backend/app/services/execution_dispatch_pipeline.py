from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..schemas.execution_dispatch import ExecutionDispatchResult
from .execution_unlock_flow import EXECUTION_UNLOCK_FLOW
from .module_adapter_registry import list_adapter_contracts
from .module_workflow_binding_engine import evaluate_module_workflow_access
from .workflow_registry_system import evaluate_workflow_invocation


class ExecutionDispatchPipeline:
    """C15 workflow dispatch pipeline.

    C15A and C15F remain definition/validation layers. This pipeline is the
    only C15 boundary that may call ExecutionRouter, and it does not call a
    webhook or external provider directly.
    """

    def dispatch(
        self,
        *,
        org_id: str,
        module_id: str,
        workflow_id: str,
        payload: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> ExecutionDispatchResult:
        safe_payload = dict(payload or {})
        safe_context = dict(context or {})
        workflow_decision = evaluate_workflow_invocation(
            module=module_id,
            workflow_id=workflow_id,
        )
        whitelist_decision = evaluate_module_workflow_access(
            module_id=module_id,
            workflow_id=workflow_id,
        )
        if (
            not workflow_decision.execution_allowed
            or not whitelist_decision.binding_validation_passed
        ):
            return ExecutionDispatchResult(
                status="rejected",
                reason="C15A/C15F rejected workflow dispatch before routing.",
                c15a_workflow_match=workflow_decision,
                c15f_whitelist_check=whitelist_decision,
            )

        action = str(
            safe_payload.get("action")
            or safe_payload.get("action_key")
            or self._default_action_for_module(module_id)
        )
        unlock_response = EXECUTION_UNLOCK_FLOW.request_execution(
            org_id=org_id,
            module_id=module_id,
            action=action,
            payload=safe_payload,
            context={
                **safe_context,
                "workflow_id": workflow_id,
                "dispatch_source": "ExecutionDispatchPipeline",
            },
        )
        return ExecutionDispatchResult(
            status=(
                "accepted"
                if unlock_response.router_response is not None
                and unlock_response.router_response.accepted
                else "rejected"
            ),
            reason=(
                "C15 dispatch reached ExecutionUnlockFlow and provider router."
                if unlock_response.router_response is not None
                and unlock_response.router_response.accepted
                else unlock_response.reason
            ),
            c15a_workflow_match=workflow_decision,
            c15f_whitelist_check=whitelist_decision,
            unlock_response=unlock_response,
            router_response=unlock_response.router_response,
        )

    def _default_action_for_module(self, module_id: str) -> str:
        for adapter in list_adapter_contracts():
            if adapter.module_key != module_id:
                continue
            if adapter.action_contracts:
                return adapter.action_contracts[0].action_key
        raise ValueError("No C08 adapter action is available for module dispatch.")


EXECUTION_DISPATCH_PIPELINE = ExecutionDispatchPipeline()
