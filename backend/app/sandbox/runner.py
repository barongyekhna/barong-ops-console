from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..schemas.execution_provider import (
    ExecutionLifecycleStatus,
    ExecutionRequestContractV1,
    ExecutionResultContractV1,
)
from .context import SandboxContext, SandboxTrustBoundary
from .execution_context import (
    ExecutionContext,
    ExecutionContextFactory,
    ExecutionContextIsolationRules,
    ExecutionContextLifecycleSnapshot,
    ExecutionContextLifecycleStateMachine,
)
from .resource import (
    RESOURCE_CONTROL_STAGE,
    ResourceEnforcementReport,
    SandboxResourceEnforcer,
)
from .types import (
    SandboxBoundaryState,
    SandboxRequest,
    SandboxResponse,
    SandboxResult,
)

RUNNER_STAGE: Literal["c10b_mock_runner"] = "c10b_mock_runner"
RUNNER_MODE: Literal["deterministic_mock"] = "deterministic_mock"
MOCK_CAPABILITY = "mock_lifecycle_simulation"
DEFAULT_VISIBLE_TRUST_ZONES = [
    "user_action",
    "c08_module_adapter",
    "c09_execution_provider",
    "c10_sandbox",
]
SAFETY_GUARANTEES = [
    "No runtime process is created.",
    "No child process or container runtime is invoked.",
    "No external provider, callback, or network call is made.",
    "No database mutation, operation-log write, or audit-event write occurs.",
    "No filesystem write is performed by the runner.",
    (
        "Execution context memory, state, and log scopes are request-bound "
        "mock refs."
    ),
    "Resource controls are logical mock policies only.",
    "No real CPU enforcement is performed.",
    "No real memory control is performed.",
    "No OS-level resource control or OS interaction is performed.",
    "Network access remains denied.",
    "No external API access is performed.",
    "Raw input_payload keys and values are not echoed in the response.",
]
RunnerContext = SandboxContext | ExecutionContext


class SandboxMockLifecycleStep(BaseModel):
    step_index: int = Field(ge=0)
    status: ExecutionLifecycleStatus
    boundary_state: SandboxBoundaryState
    description: str = Field(min_length=1, max_length=240)
    runtime_created: Literal[False] = False
    external_provider_called: Literal[False] = False
    db_mutated: Literal[False] = False
    filesystem_written: Literal[False] = False


class SandboxMockExecutionFlow(BaseModel):
    flow_id: str = Field(min_length=1, max_length=128)
    runner_mode: Literal["deterministic_mock"] = RUNNER_MODE
    steps: list[SandboxMockLifecycleStep]
    terminal_status: ExecutionLifecycleStatus
    safe_result_only: Literal[True] = True
    deterministic: Literal[True] = True


class SandboxRunnerPolicyViolation(BaseModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=300)
    execution_status: ExecutionLifecycleStatus = "rejected"


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _shape(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {
            "type": "object",
            "key_count": len(value),
            "keys_redacted": True,
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "item_count": len(value),
            "item_types": sorted({type(item).__name__ for item in value}),
        }
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def _execution_request_from_raw(
    execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
) -> ExecutionRequestContractV1:
    if isinstance(execution_request, ExecutionRequestContractV1):
        return execution_request
    return ExecutionRequestContractV1.model_validate(execution_request)


def _sandbox_request_from_raw(
    sandbox_request: SandboxRequest | Mapping[str, Any],
) -> SandboxRequest:
    if isinstance(sandbox_request, SandboxRequest):
        return sandbox_request
    return SandboxRequest.model_validate(sandbox_request)


def _enforce_execution_flow_gate(
    execution_request: ExecutionRequestContractV1 | SandboxRequest | Mapping[str, Any],
) -> None:
    from ..services.execution_flow_gate import C13E_GATE

    C13E_GATE.check(
        execution_request,
        integration_point="c10_sandbox_entry",
    )


class SandboxRunner:
    """C10B mock-only execution runner.

    The runner simulates lifecycle transitions from C09 execution contracts.
    It never creates a runtime, calls an external provider, mutates the
    database, or writes artifacts.
    """

    def __init__(
        self,
        *,
        runner_key: str = "c10b.sandbox_runner.mock.v1",
        runner_version: str = "1.0.0",
        context_factory: ExecutionContextFactory | None = None,
        resource_enforcer: SandboxResourceEnforcer | None = None,
    ) -> None:
        self.runner_key = runner_key
        self.runner_version = runner_version
        self.context_factory = context_factory or ExecutionContextFactory()
        self.resource_enforcer = resource_enforcer or SandboxResourceEnforcer()

    def handle_execution_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        context: RunnerContext | None = None,
    ) -> SandboxResponse:
        request_contract = _execution_request_from_raw(execution_request)
        _enforce_execution_flow_gate(request_contract)
        execution_context = self._normalize_execution_context(
            context,
            request_contract,
        )
        sandbox_context = self._normalize_context(
            context,
            request_contract,
            execution_context=execution_context,
        )
        sandbox_request = self.build_sandbox_request(
            request_contract,
            context=sandbox_context,
            execution_context=execution_context,
        )
        return self.generate_execution_response(
            sandbox_request,
            context=sandbox_context,
            execution_context=execution_context,
        )

    def handle_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        context: RunnerContext | None = None,
    ) -> SandboxResponse:
        return self.handle_execution_request(
            execution_request,
            context=context,
        )

    def build_sandbox_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        context: RunnerContext | None = None,
        execution_context: ExecutionContext | None = None,
        requested_capabilities: list[str] | None = None,
    ) -> SandboxRequest:
        request_contract = _execution_request_from_raw(execution_request)
        _enforce_execution_flow_gate(request_contract)
        bound_execution_context = self._normalize_execution_context(
            execution_context or context,
            request_contract,
        )
        sandbox_context = self._normalize_context(
            context,
            request_contract,
            execution_context=bound_execution_context,
        )
        capabilities = list(requested_capabilities or [])
        if MOCK_CAPABILITY not in capabilities:
            capabilities.append(MOCK_CAPABILITY)
        request_id = request_contract.request_id or request_contract.execution_id
        sandbox_request_id = _stable_id(
            "sandbox_req",
            {
                "runner_key": self.runner_key,
                "request": request_contract.model_dump(mode="json"),
                "context_id": sandbox_context.context_id,
                "capabilities": capabilities,
            },
        )

        return SandboxRequest(
            request_id=request_id,
            sandbox_request_id=sandbox_request_id,
            context_id=bound_execution_context.context_id,
            execution_context_ref=bound_execution_context.execution_context_ref,
            scope_ref=bound_execution_context.scope_ref,
            memory_scope_ref=bound_execution_context.memory_scope.memory_scope_id,
            log_scope_ref=bound_execution_context.log_scope.log_scope_id,
            state_scope_ref=bound_execution_context.state_scope.state_scope_id,
            resource_policy_ref=bound_execution_context.resource_policy_ref,
            isolation_level=bound_execution_context.isolation_level,
            context_lifecycle_state=bound_execution_context.lifecycle_state,
            stage=RUNNER_STAGE,
            contract_mode="mock_only",
            c09_execution_request=request_contract,
            module_key=request_contract.module_key,
            adapter_key=request_contract.adapter_key,
            provider_key=request_contract.provider_key,
            provider_type=request_contract.provider_type,
            action_key=request_contract.action_key,
            actor_user_id=request_contract.actor_user_id,
            risk_level=request_contract.risk_level,
            requested_capabilities=capabilities,
            target_scope=request_contract.target_scope,
            sanitized_input_summary=self._safe_input_summary(request_contract),
            sandbox_scope_ref=bound_execution_context.sandbox_scope_ref,
        )

    def run(
        self,
        sandbox_request: SandboxRequest | Mapping[str, Any],
        *,
        context: RunnerContext | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> SandboxResponse:
        request_contract = _sandbox_request_from_raw(sandbox_request)
        _enforce_execution_flow_gate(request_contract)
        bound_execution_context = self._normalize_execution_context(
            execution_context or context,
            request_contract.c09_execution_request,
        )
        normalized_context = self._normalize_context(
            context,
            request_contract.c09_execution_request,
            execution_context=bound_execution_context,
        )
        normalized_request = self._normalize_sandbox_request(
            request_contract,
            context=normalized_context,
            execution_context=bound_execution_context,
        )
        return self.generate_execution_response(
            normalized_request,
            context=normalized_context,
            execution_context=bound_execution_context,
        )

    def generate_execution_response(
        self,
        sandbox_request: SandboxRequest | Mapping[str, Any],
        *,
        context: RunnerContext | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> SandboxResponse:
        request_contract = _sandbox_request_from_raw(sandbox_request)
        _enforce_execution_flow_gate(request_contract)
        bound_execution_context = self._normalize_execution_context(
            execution_context or context,
            request_contract.c09_execution_request,
        )
        sandbox_context = self._normalize_context(
            context,
            request_contract.c09_execution_request,
            execution_context=bound_execution_context,
        )
        normalized_request = self._normalize_sandbox_request(
            request_contract,
            context=sandbox_context,
            execution_context=bound_execution_context,
        )
        (
            sandbox_context,
            bound_execution_context,
            resource_report,
        ) = self.resource_enforcer.enforce_before_run(
            sandbox_request=normalized_request,
            sandbox_context=sandbox_context,
            execution_context=bound_execution_context,
        )
        normalized_request = self._normalize_sandbox_request(
            normalized_request,
            context=sandbox_context,
            execution_context=bound_execution_context,
        )
        violations = self._policy_violations(
            normalized_request,
            sandbox_context,
            bound_execution_context,
        )
        violations = [
            *self._resource_policy_violations(resource_report),
            *violations,
        ]
        final_execution_context, lifecycle_snapshot = self._mock_context_lifecycle(
            bound_execution_context,
            violations,
        )
        flow = self._mock_execution_flow(normalized_request, violations)
        blocked = bool(violations)
        result_status = "mock_blocked" if blocked else "mock_succeeded"
        boundary_state = (
            "mock_blocked_by_policy" if blocked else "mock_lifecycle_simulated"
        )
        error_code = violations[0].code if violations else None
        error_message_safe = (
            "Mock execution blocked by sandbox policy." if violations else None
        )
        result_summary = self._result_summary(
            normalized_request,
            sandbox_context,
            final_execution_context,
            lifecycle_snapshot,
            flow,
            violations,
            resource_report,
        )
        c09_result_contract = ExecutionResultContractV1(
            execution_id=final_execution_context.execution_id,
            provider_key=normalized_request.provider_key,
            status=flow.terminal_status,
            result_summary=result_summary,
            artifact_refs=[],
            error_code=error_code,
            error_message_safe=error_message_safe,
            operation_log_id=None,
            safe_result_only=True,
        )
        sandbox_result = SandboxResult(
            result_id=_stable_id(
                "sandbox_result",
                {
                    "sandbox_request_id": normalized_request.sandbox_request_id,
                    "flow_id": flow.flow_id,
                    "terminal_status": flow.terminal_status,
                    "violations": [
                        violation.model_dump(mode="json")
                        for violation in violations
                    ],
                },
            ),
            request_id=normalized_request.request_id,
            sandbox_request_id=normalized_request.sandbox_request_id,
            context_id=final_execution_context.context_id,
            execution_context_ref=final_execution_context.execution_context_ref,
            scope_ref=final_execution_context.scope_ref,
            memory_scope_ref=final_execution_context.memory_scope.memory_scope_id,
            log_scope_ref=final_execution_context.log_scope.log_scope_id,
            state_scope_ref=final_execution_context.state_scope.state_scope_id,
            resource_policy_ref=final_execution_context.resource_policy_ref,
            isolation_level=final_execution_context.isolation_level,
            context_lifecycle_state=final_execution_context.lifecycle_state,
            stage=RESOURCE_CONTROL_STAGE,
            status=result_status,
            execution_status=flow.terminal_status,
            boundary_state=boundary_state,
            result_summary=result_summary,
            artifact_refs=[],
            resource_violations=[
                violation
                for violation in resource_report.violations
                if violation.execution_blocked
            ],
            error_code=error_code,
            error_message_safe=error_message_safe,
            safe_result_only=True,
            runtime_created=False,
            external_provider_called=False,
            db_mutated=False,
            production_touched=False,
            staging_touched=False,
            filesystem_write_scope="none",
        )

        return SandboxResponse(
            response_id=_stable_id(
                "sandbox_resp",
                {
                    "result_id": sandbox_result.result_id,
                    "runner_key": self.runner_key,
                    "context_id": final_execution_context.context_id,
                },
            ),
            request_id=normalized_request.request_id,
            sandbox_request_id=normalized_request.sandbox_request_id,
            context_id=final_execution_context.context_id,
            execution_context_ref=final_execution_context.execution_context_ref,
            stage=RESOURCE_CONTROL_STAGE,
            contract_mode="mock_only",
            result=sandbox_result,
            execution_context=final_execution_context,
            resource_policy=resource_report.policy,
            c09_result_contract=c09_result_contract,
            safety_notes=list(SAFETY_GUARANTEES),
            next_stage_policy="wait_for_c10e",
        )

    def _normalize_execution_context(
        self,
        context: RunnerContext | None,
        execution_request: ExecutionRequestContractV1,
    ) -> ExecutionContext:
        if isinstance(context, ExecutionContext):
            return context
        return self.context_factory.create_context(execution_request)

    def _normalize_context(
        self,
        context: RunnerContext | None,
        execution_request: ExecutionRequestContractV1,
        *,
        execution_context: ExecutionContext,
    ) -> SandboxContext:
        if not isinstance(context, SandboxContext):
            return self._context_from_execution_request(
                execution_request,
                execution_context=execution_context,
            )

        request_summary = self._safe_input_summary(execution_request)
        metadata = {
            **context.request_metadata,
            "source_context_stage": context.stage,
            "source_context_id": context.context_id,
            "runner_key": self.runner_key,
            "runner_version": self.runner_version,
            "runner_mode": RUNNER_MODE,
            "c10c_stage": execution_context.stage,
            "c10c_context_id": execution_context.context_id,
            "scope_ref": execution_context.scope_ref,
            "memory_scope_ref": execution_context.memory_scope.memory_scope_id,
            "log_scope_ref": execution_context.log_scope.log_scope_id,
            "state_scope_ref": execution_context.state_scope.state_scope_id,
            "resource_policy_ref": execution_context.resource_policy_ref,
            "isolation_level": execution_context.isolation_level,
            "mock_only": True,
            "raw_input_payload_echoed": False,
        }
        visible_trust_zones = (
            context.visible_trust_zones or list(DEFAULT_VISIBLE_TRUST_ZONES)
        )
        return context.model_copy(
            update={
                "context_id": execution_context.context_id,
                "stage": RUNNER_STAGE,
                "runtime_execution_policy": "mock_simulation_only",
                "execution_context_ref": execution_context.execution_context_ref,
                "sandbox_scope_ref": execution_context.sandbox_scope_ref,
                "resource_policy_ref": (
                    execution_context.resource_policy_ref
                    or context.resource_policy_ref
                ),
                "resource_policy": (
                    execution_context.resource_policy or context.resource_policy
                ),
                "request_metadata": metadata,
                "sanitized_input_summary": request_summary,
                "visible_trust_zones": visible_trust_zones,
            },
        )

    def _context_from_execution_request(
        self,
        execution_request: ExecutionRequestContractV1,
        *,
        execution_context: ExecutionContext,
    ) -> SandboxContext:
        request_identity = self._request_identity(execution_request)
        boundary_key = _stable_id(
            "sandbox_boundary",
            {
                "runner_key": self.runner_key,
                "request_identity": request_identity,
                "context_id": execution_context.context_id,
            },
        )
        return SandboxContext(
            context_id=execution_context.context_id,
            stage=RUNNER_STAGE,
            module_key=execution_request.module_key,
            adapter_key=execution_request.adapter_key,
            provider_key=execution_request.provider_key,
            action_key=execution_request.action_key,
            actor_user_id=execution_request.actor_user_id,
            risk_level=execution_request.risk_level,
            trust_boundary=SandboxTrustBoundary(boundary_key=boundary_key),
            execution_context_ref=execution_context.execution_context_ref,
            sandbox_scope_ref=execution_context.sandbox_scope_ref,
            request_metadata={
                "runner_key": self.runner_key,
                "runner_version": self.runner_version,
                "runner_mode": RUNNER_MODE,
                "c10c_stage": execution_context.stage,
                "c10c_context_id": execution_context.context_id,
                "scope_ref": execution_context.scope_ref,
                "memory_scope_ref": execution_context.memory_scope.memory_scope_id,
                "log_scope_ref": execution_context.log_scope.log_scope_id,
                "state_scope_ref": execution_context.state_scope.state_scope_id,
                "isolation_level": execution_context.isolation_level,
                "mock_only": True,
                "source_execution_status": execution_request.status,
                "raw_input_payload_echoed": False,
            },
            sanitized_input_summary=self._safe_input_summary(execution_request),
            visible_trust_zones=list(DEFAULT_VISIBLE_TRUST_ZONES),
            runtime_execution_policy="mock_simulation_only",
        )

    def _normalize_sandbox_request(
        self,
        sandbox_request: SandboxRequest,
        *,
        context: SandboxContext,
        execution_context: ExecutionContext,
    ) -> SandboxRequest:
        capabilities = list(sandbox_request.requested_capabilities)
        if MOCK_CAPABILITY not in capabilities:
            capabilities.append(MOCK_CAPABILITY)
        return sandbox_request.model_copy(
            update={
                "context_id": execution_context.context_id,
                "execution_context_ref": execution_context.execution_context_ref,
                "scope_ref": execution_context.scope_ref,
                "memory_scope_ref": execution_context.memory_scope.memory_scope_id,
                "log_scope_ref": execution_context.log_scope.log_scope_id,
                "state_scope_ref": execution_context.state_scope.state_scope_id,
                "resource_policy_ref": execution_context.resource_policy_ref,
                "isolation_level": execution_context.isolation_level,
                "context_lifecycle_state": execution_context.lifecycle_state,
                "stage": context.stage,
                "contract_mode": "mock_only",
                "requested_capabilities": capabilities,
                "sanitized_input_summary": self._safe_input_summary(
                    sandbox_request.c09_execution_request
                ),
                "sandbox_scope_ref": execution_context.sandbox_scope_ref,
            },
        )

    def _policy_violations(
        self,
        sandbox_request: SandboxRequest,
        context: SandboxContext,
        execution_context: ExecutionContext,
    ) -> list[SandboxRunnerPolicyViolation]:
        violations: list[SandboxRunnerPolicyViolation] = []
        request = sandbox_request.c09_execution_request

        for field_name in [
            "module_key",
            "adapter_key",
            "provider_key",
            "action_key",
            "actor_user_id",
            "risk_level",
        ]:
            if (
                field_name == "actor_user_id"
                and getattr(context, field_name) is None
            ):
                continue
            if getattr(context, field_name) != getattr(sandbox_request, field_name):
                violations.append(
                    SandboxRunnerPolicyViolation(
                        code="C10B_CONTEXT_MISMATCH",
                        message=(
                            "Sandbox context does not match the execution "
                            f"request field: {field_name}."
                        ),
                    )
                )

        for isolation_violation in (
            self.context_factory.binding_violations(execution_context, request)
        ):
            violations.append(
                SandboxRunnerPolicyViolation(
                    code=isolation_violation.code,
                    message=isolation_violation.message,
                )
            )

        isolation_report = ExecutionContextIsolationRules.validate_context(
            execution_context
        )
        for isolation_violation in isolation_report.violations:
            violations.append(
                SandboxRunnerPolicyViolation(
                    code=isolation_violation.code,
                    message=isolation_violation.message,
                )
            )

        if execution_context.lifecycle_state != "created":
            violations.append(
                SandboxRunnerPolicyViolation(
                    code="C10C_CONTEXT_STATE_REUSE_BLOCKED",
                    message=(
                        "Execution context must start from created state for "
                        "each mock sandbox execution."
                    ),
                )
            )

        context_ref_checks = {
            "context_id": execution_context.context_id,
            "execution_context_ref": execution_context.execution_context_ref,
            "scope_ref": execution_context.scope_ref,
            "sandbox_scope_ref": execution_context.sandbox_scope_ref,
            "memory_scope_ref": execution_context.memory_scope.memory_scope_id,
            "log_scope_ref": execution_context.log_scope.log_scope_id,
            "state_scope_ref": execution_context.state_scope.state_scope_id,
            "resource_policy_ref": execution_context.resource_policy_ref,
            "isolation_level": execution_context.isolation_level,
        }
        for field_name, expected_value in context_ref_checks.items():
            if getattr(sandbox_request, field_name) != expected_value:
                violations.append(
                    SandboxRunnerPolicyViolation(
                        code="C10C_REQUEST_CONTEXT_MISMATCH",
                        message=(
                            "Sandbox request is not bound to execution context "
                            f"field: {field_name}."
                        ),
                    )
                )

        denied = set(sandbox_request.denied_capabilities)
        for capability in sorted(set(sandbox_request.requested_capabilities)):
            if capability in denied:
                violations.append(
                    SandboxRunnerPolicyViolation(
                        code="C10B_DENIED_CAPABILITY",
                        message=(
                            "Sandbox request asked for a denied capability: "
                            f"{capability}."
                        ),
                    )
                )

        if request.approval_status != "not_required":
            violations.append(
                SandboxRunnerPolicyViolation(
                    code="C10B_APPROVAL_BLOCKED",
                    message="Execution request is waiting for approval policy.",
                    execution_status="blocked_approval_required",
                )
            )

        if request.secret_binding_status != "not_required":
            violations.append(
                SandboxRunnerPolicyViolation(
                    code="C10B_SECRET_BLOCKED",
                    message="Execution request is waiting for secret rules.",
                )
            )

        return violations

    def _resource_policy_violations(
        self,
        resource_report: ResourceEnforcementReport,
    ) -> list[SandboxRunnerPolicyViolation]:
        return [
            SandboxRunnerPolicyViolation(
                code=f"C10D_{violation.violation_type.upper()}",
                message=violation.violation_reason,
            )
            for violation in resource_report.violations
            if violation.execution_blocked
        ]

    def _mock_context_lifecycle(
        self,
        execution_context: ExecutionContext,
        violations: list[SandboxRunnerPolicyViolation],
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        if violations:
            return ExecutionContextLifecycleStateMachine.run_mock_failure(
                execution_context
            )
        return ExecutionContextLifecycleStateMachine.run_mock_success(
            execution_context
        )

    def _mock_execution_flow(
        self,
        sandbox_request: SandboxRequest,
        violations: list[SandboxRunnerPolicyViolation],
    ) -> SandboxMockExecutionFlow:
        if violations:
            terminal_status = self._blocked_terminal_status(violations)
            steps = [
                SandboxMockLifecycleStep(
                    step_index=0,
                    status="requested",
                    boundary_state="contract_received",
                    description="C09 execution request contract received.",
                ),
                SandboxMockLifecycleStep(
                    step_index=1,
                    status=terminal_status,
                    boundary_state="mock_blocked_by_policy",
                    description=(
                        "Mock lifecycle stopped by sandbox resource or policy "
                        "validation before any runtime could be created."
                    ),
                ),
            ]
        else:
            terminal_status = "succeeded"
            steps = [
                SandboxMockLifecycleStep(
                    step_index=0,
                    status="requested",
                    boundary_state="contract_received",
                    description="C09 execution request contract received.",
                ),
                SandboxMockLifecycleStep(
                    step_index=1,
                    status="accepted",
                    boundary_state="mock_lifecycle_simulated",
                    description=(
                        "C10D resource policy validated in memory for mock "
                        "simulation."
                    ),
                ),
                SandboxMockLifecycleStep(
                    step_index=2,
                    status="running",
                    boundary_state="mock_lifecycle_simulated",
                    description="Lifecycle advanced in memory only.",
                ),
                SandboxMockLifecycleStep(
                    step_index=3,
                    status="succeeded",
                    boundary_state="mock_lifecycle_simulated",
                    description="Deterministic safe mock result generated.",
                ),
            ]

        return SandboxMockExecutionFlow(
            flow_id=_stable_id(
                "mock_flow",
                {
                    "sandbox_request_id": sandbox_request.sandbox_request_id,
                    "terminal_status": terminal_status,
                    "violations": [
                        violation.model_dump(mode="json")
                        for violation in violations
                    ],
                },
            ),
            steps=steps,
            terminal_status=terminal_status,
        )

    def _blocked_terminal_status(
        self,
        violations: list[SandboxRunnerPolicyViolation],
    ) -> ExecutionLifecycleStatus:
        if any(
            violation.execution_status == "blocked_approval_required"
            for violation in violations
        ):
            return "blocked_approval_required"
        return "rejected"

    def _result_summary(
        self,
        sandbox_request: SandboxRequest,
        context: SandboxContext,
        execution_context: ExecutionContext,
        lifecycle_snapshot: ExecutionContextLifecycleSnapshot,
        flow: SandboxMockExecutionFlow,
        violations: list[SandboxRunnerPolicyViolation],
        resource_report: ResourceEnforcementReport,
    ) -> dict[str, Any]:
        return {
            "runner_key": self.runner_key,
            "runner_version": self.runner_version,
            "runner_mode": RUNNER_MODE,
            "stage": RESOURCE_CONTROL_STAGE,
            "runner_stage": RUNNER_STAGE,
            "mock_only": True,
            "deterministic": True,
            "execution_lifecycle_simulated": True,
            "terminal_status": flow.terminal_status,
            "request_identity": self._request_identity(
                sandbox_request.c09_execution_request
            ),
            "context": {
                "context_id": context.context_id,
                "sandbox_scope_ref": context.sandbox_scope_ref,
                "resource_policy_ref": context.resource_policy_ref,
                "resource_control_stage": context.resource_control_stage,
                "runtime_execution_policy": context.runtime_execution_policy,
                "external_provider_policy": context.external_provider_policy,
                "db_mutation_policy": context.db_mutation_policy,
                "filesystem_write_policy": context.filesystem_write_policy,
                "network_policy": context.network_policy,
                "file_access_policy": context.file_access_policy,
            },
            "execution_context": {
                "context_id": execution_context.context_id,
                "execution_id": execution_context.execution_id,
                "module_key": execution_context.module_key,
                "adapter_key": execution_context.adapter_key,
                "action_key": execution_context.action_key,
                "actor_user_id": execution_context.actor_user_id,
                "scope_ref": execution_context.scope_ref,
                "sandbox_scope_ref": execution_context.sandbox_scope_ref,
                "execution_context_ref": execution_context.execution_context_ref,
                "isolation_level": execution_context.isolation_level,
                "memory_scope_ref": execution_context.memory_scope.memory_scope_id,
                "log_scope_ref": execution_context.log_scope.log_scope_id,
                "state_scope_ref": execution_context.state_scope.state_scope_id,
                "resource_policy_ref": execution_context.resource_policy_ref,
                "lifecycle_state": execution_context.lifecycle_state,
                "lifecycle_mock_only": execution_context.lifecycle_mock_only,
            },
            "resource_control": {
                "stage": resource_report.stage,
                "execution_blocked": resource_report.execution_blocked,
                "policy": resource_report.policy.model_dump(mode="json"),
                "control_model": (
                    resource_report.policy.control_model.model_dump(mode="json")
                ),
                "violations": [
                    violation.model_dump(mode="json")
                    for violation in resource_report.violations
                ],
                "mock_only": resource_report.mock_only,
                "deterministic": resource_report.deterministic,
                "cpu_os_enforced": resource_report.cpu_os_enforced,
                "memory_os_enforced": resource_report.memory_os_enforced,
                "os_interaction_performed": (
                    resource_report.os_interaction_performed
                ),
                "network_access_performed": (
                    resource_report.network_access_performed
                ),
                "external_api_called": resource_report.external_api_called,
            },
            "input_summary": sandbox_request.sanitized_input_summary,
            "lifecycle": [step.model_dump(mode="json") for step in flow.steps],
            "context_lifecycle": lifecycle_snapshot.model_dump(mode="json"),
            "policy_violations": [
                violation.model_dump(mode="json") for violation in violations
            ],
            "safety": {
                "runtime_created": False,
                "external_provider_called": False,
                "db_mutated": False,
                "production_touched": False,
                "staging_touched": False,
                "filesystem_written": False,
                "raw_input_payload_echoed": False,
                "shared_memory": False,
                "shared_execution_state": False,
                "shared_logs": False,
                "cross_context_mutation": False,
                "real_cpu_enforcement": False,
                "real_memory_control": False,
                "os_interaction": False,
                "network_access": False,
                "external_api_access": False,
            },
        }

    def _safe_input_summary(
        self,
        execution_request: ExecutionRequestContractV1,
    ) -> dict[str, Any]:
        return {
            "raw_input_payload_echoed": False,
            "input_payload_shape": _shape(execution_request.input_payload),
            "sanitized_input_summary_shape": _shape(
                execution_request.sanitized_input_summary
            ),
            "target_scope_shape": _shape(execution_request.target_scope),
            "idempotency_key_present": bool(execution_request.idempotency_key),
            "result_summary_present": execution_request.result_summary is not None,
        }

    def _request_identity(
        self,
        execution_request: ExecutionRequestContractV1,
    ) -> dict[str, Any]:
        return {
            "execution_id": execution_request.execution_id,
            "request_id": execution_request.request_id,
            "module_key": execution_request.module_key,
            "adapter_key": execution_request.adapter_key,
            "provider_key": execution_request.provider_key,
            "provider_type": execution_request.provider_type,
            "action_key": execution_request.action_key,
            "actor_user_id": execution_request.actor_user_id,
            "risk_level": execution_request.risk_level,
            "status": execution_request.status,
        }


def handle_execution_request(
    execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    *,
    context: RunnerContext | None = None,
) -> SandboxResponse:
    return SandboxRunner().handle_execution_request(
        execution_request,
        context=context,
    )


def deterministic_mock_execution_response(
    execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    *,
    context: RunnerContext | None = None,
) -> ExecutionResultContractV1:
    response = handle_execution_request(execution_request, context=context)
    if response.c09_result_contract is None:
        raise RuntimeError("C10B mock runner did not generate a result contract.")
    return response.c09_result_contract


__all__ = [
    "RUNNER_MODE",
    "RUNNER_STAGE",
    "SAFETY_GUARANTEES",
    "RunnerContext",
    "SandboxMockExecutionFlow",
    "SandboxMockLifecycleStep",
    "SandboxRunner",
    "SandboxRunnerPolicyViolation",
    "deterministic_mock_execution_response",
    "handle_execution_request",
]
