from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..schemas.execution_provider import (
    ExecutionLifecycleStatus,
    ExecutionRequestContractV1,
    ExecutionResultContractV1,
)
from .bridge import (
    BRIDGE_SAFETY_GUARANTEES,
    BRIDGE_STAGE,
    BridgeRequest,
    BridgeResponse,
    SandboxBridgeMode,
    SandboxExecutionBridge,
)
from .execution_context import ExecutionContext, ExecutionContextFactory
from .resource import SandboxResourceEnforcer
from .runner import RUNNER_MODE, RUNNER_STAGE, SAFETY_GUARANTEES, SandboxRunner
from .types import SandboxResponse


RUNTIME_STAGE: Literal["c10f_runtime_finalization"] = (
    "c10f_runtime_finalization"
)
RUNTIME_MODE: Literal["disabled_execution"] = "disabled_execution"
RUNTIME_EXECUTION_CAPABILITY: Literal["mock_only"] = "mock_only"
RUNTIME_PIPELINE = [
    "User Action",
    "C08 Module Adapter",
    "C09 Execution Provider",
    "C10 Sandbox Runtime",
    "Mock Result",
]
RUNTIME_LIFECYCLE_STEPS = [
    "runtime_start",
    "runtime_prepare",
    "runtime_execute",
    "runtime_complete",
    "runtime_finalize",
]
RUNTIME_SAFETY_GUARANTEES = [
    "C10F execution_locked defaults to true and cannot be disabled.",
    "SandboxRuntime orchestrates C10A-C10E contracts only.",
    "runtime_execute delegates only to the C10E mock bridge.",
    "No runtime process, subprocess, worker, shell, or container is created.",
    "No external provider, callback, webhook, queue, or network client is called.",
    "No production or staging environment is read or mutated.",
    "No database write, operation-log write, or audit-event write is performed.",
    "No filesystem write is performed.",
    "No real computation execution is available in C10F.",
    "Provider access remains redacted.",
]

RuntimeLifecycleStepName = Literal[
    "runtime_start",
    "runtime_prepare",
    "runtime_execute",
    "runtime_complete",
    "runtime_finalize",
]
RuntimeLifecycleStepStatus = Literal[
    "started",
    "prepared",
    "mock_executed",
    "completed",
    "blocked",
    "finalized",
]
RuntimeStatus = Literal["mock_succeeded", "mock_blocked"]


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _execution_request_from_raw(
    execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
) -> ExecutionRequestContractV1:
    if isinstance(execution_request, ExecutionRequestContractV1):
        return execution_request
    return ExecutionRequestContractV1.model_validate(execution_request)


class SandboxRuntimeLifecycleStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_index: int = Field(ge=0)
    step_name: RuntimeLifecycleStepName
    status: RuntimeLifecycleStepStatus
    stage: Literal["c10f_runtime_finalization"] = RUNTIME_STAGE
    description: str = Field(min_length=1, max_length=300)
    refs: dict[str, Any] = Field(default_factory=dict)
    execution_locked: Literal[True] = True
    mock_only: Literal[True] = True
    runtime_created: Literal[False] = False
    external_provider_called: Literal[False] = False
    live_provider_called: Literal[False] = False
    network_access_performed: Literal[False] = False
    db_write_performed: Literal[False] = False
    filesystem_write_performed: Literal[False] = False
    production_mutated: Literal[False] = False
    staging_mutated: Literal[False] = False
    real_computation_executed: Literal[False] = False


class SandboxRuntimeLifecycle(BaseModel):
    model_config = ConfigDict(frozen=True)

    lifecycle_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10f_runtime_finalization"] = RUNTIME_STAGE
    steps: tuple[SandboxRuntimeLifecycleStep, ...]
    terminal_step: Literal["runtime_finalize"] = "runtime_finalize"
    runtime_mode: Literal["disabled_execution"] = RUNTIME_MODE
    execution_locked: Literal[True] = True
    mock_only: Literal[True] = True
    no_real_runtime_exists: Literal[True] = True


class FinalSafetyLockViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=300)
    blocked: Literal[True] = True


class FinalSafetyLock(BaseModel):
    model_config = ConfigDict(frozen=True)

    lock_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10f_runtime_finalization"] = RUNTIME_STAGE
    execution_locked: Literal[True] = True
    lock_status: Literal["locked_clean", "locked_with_violation"]
    safe: bool
    violations: tuple[FinalSafetyLockViolation, ...] = Field(default_factory=tuple)
    no_side_effect_guarantee: Literal[True] = True
    no_external_call: Literal[True] = True
    no_real_computation_execution: Literal[True] = True
    no_real_runtime_existence: Literal[True] = True
    provider_access: Literal["redacted"] = "redacted"
    runtime_creation_allowed: Literal[False] = False
    external_provider_call_allowed: Literal[False] = False
    live_provider_call_allowed: Literal[False] = False
    network_access_allowed: Literal[False] = False
    db_write_allowed: Literal[False] = False
    filesystem_write_allowed: Literal[False] = False
    production_access_allowed: Literal[False] = False
    staging_access_allowed: Literal[False] = False
    subprocess_allowed: Literal[False] = False
    docker_allowed: Literal[False] = False


class SandboxFinalState(BaseModel):
    model_config = ConfigDict(frozen=True)

    final_state_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10f_runtime_finalization"] = RUNTIME_STAGE
    execution_capability: Literal["mock_only"] = RUNTIME_EXECUTION_CAPABILITY
    runtime_mode: Literal["disabled_execution"] = RUNTIME_MODE
    isolation_status: Literal["fully_isolated"] = "fully_isolated"
    provider_access: Literal["redacted"] = "redacted"
    final_lock_ref: str = Field(min_length=1, max_length=180)
    bridge_response_id: str | None = Field(default=None, max_length=180)
    sandbox_response_id: str | None = Field(default=None, max_length=180)
    execution_context_ref: str | None = Field(default=None, max_length=180)
    resource_policy_ref: str | None = Field(default=None, max_length=180)
    c10_chain: tuple[str, ...] = (
        "C10A Sandbox Architecture",
        "C10B Execution Runner (mock)",
        "C10C Execution Context System",
        "C10D Resource Control Layer",
        "C10E Sandbox Execution Bridge",
        "C10F Mock Sandbox Runtime Finalization",
    )
    execution_locked: Literal[True] = True
    no_side_effects: Literal[True] = True
    no_external_call: Literal[True] = True
    no_real_computation_execution: Literal[True] = True
    no_real_runtime_exists: Literal[True] = True
    production_touched: Literal[False] = False
    staging_touched: Literal[False] = False
    safe_result_only: Literal[True] = True
    seal_prepared: Literal[True] = True
    next_stage_policy: Literal["wait_for_c10g"] = "wait_for_c10g"


class SandboxRuntimeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: Literal["sandbox_runtime_response"] = "sandbox_runtime_response"
    runtime_response_id: str = Field(min_length=1, max_length=180)
    runtime_key: str = Field(min_length=1, max_length=180)
    runtime_version: str = Field(min_length=1, max_length=40)
    stage: Literal["c10f_runtime_finalization"] = RUNTIME_STAGE
    runtime_mode: Literal["disabled_execution"] = RUNTIME_MODE
    status: RuntimeStatus
    execution_status: ExecutionLifecycleStatus
    lifecycle: SandboxRuntimeLifecycle
    safety_lock: FinalSafetyLock
    final_state: SandboxFinalState
    bridge_response: BridgeResponse
    sandbox_response: SandboxResponse
    c09_result_contract: ExecutionResultContractV1 | None = None
    pipeline: list[str] = Field(default_factory=lambda: list(RUNTIME_PIPELINE))
    safety_notes: list[str] = Field(default_factory=list)
    safe_result_only: Literal[True] = True
    execution_locked: Literal[True] = True
    no_real_runtime_exists: Literal[True] = True
    no_real_computation_execution: Literal[True] = True
    runtime_created: Literal[False] = False
    external_provider_called: Literal[False] = False
    live_provider_called: Literal[False] = False
    network_access_performed: Literal[False] = False
    db_write_performed: Literal[False] = False
    filesystem_access_performed: Literal[False] = False
    production_mutated: Literal[False] = False
    staging_mutated: Literal[False] = False
    next_stage_policy: Literal["wait_for_c10g"] = "wait_for_c10g"


class SandboxRuntime:
    """C10F final wrapper for the complete mock-only sandbox runtime.

    The runtime is a finalization layer over C10A-C10E. It orchestrates the
    existing context, resource, runner, and bridge contracts while keeping
    execution permanently locked.
    """

    def __init__(
        self,
        *,
        runtime_key: str = "c10f.sandbox_runtime.mock_finalization.v1",
        runtime_version: str = "1.0.0",
        execution_locked: bool = True,
        context_factory: ExecutionContextFactory | None = None,
        resource_enforcer: SandboxResourceEnforcer | None = None,
        runner: SandboxRunner | None = None,
        bridge: SandboxExecutionBridge | None = None,
    ) -> None:
        if execution_locked is not True:
            raise ValueError("C10F SandboxRuntime cannot unlock execution.")

        self.runtime_key = runtime_key
        self.runtime_version = runtime_version
        self.execution_locked = True

        if bridge is not None:
            self.bridge = bridge
            self.context_factory = context_factory or bridge.context_factory
            self.runner = runner or bridge.runner
            self.resource_enforcer = (
                resource_enforcer or self.runner.resource_enforcer
            )
            return

        self.context_factory = context_factory or ExecutionContextFactory()
        self.resource_enforcer = resource_enforcer or SandboxResourceEnforcer()
        self.runner = runner or SandboxRunner(
            context_factory=self.context_factory,
            resource_enforcer=self.resource_enforcer,
        )
        self.bridge = SandboxExecutionBridge(
            context_factory=self.context_factory,
            runner=self.runner,
        )

    def handle_execution_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
        context: ExecutionContext | None = None,
    ) -> SandboxRuntimeResponse:
        request_contract = _execution_request_from_raw(execution_request)
        start_step = self.runtime_start(
            request_contract,
            bridge_mode=bridge_mode,
            context=context,
        )
        bridge_request, prepare_step = self.runtime_prepare(
            request_contract,
            bridge_mode=bridge_mode,
            context=context,
        )
        bridge_response, execute_step = self.runtime_execute(
            request_contract,
            bridge_mode=bridge_mode,
            context=bridge_request.execution_context,
        )
        safety_lock, complete_step = self.runtime_complete(bridge_response)
        return self.runtime_finalize(
            bridge_response,
            safety_lock=safety_lock,
            steps=(
                start_step,
                prepare_step,
                execute_step,
                complete_step,
            ),
        )

    def run(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
        context: ExecutionContext | None = None,
    ) -> SandboxRuntimeResponse:
        return self.handle_execution_request(
            execution_request,
            bridge_mode=bridge_mode,
            context=context,
        )

    def runtime_start(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
        context: ExecutionContext | None = None,
    ) -> SandboxRuntimeLifecycleStep:
        request_contract = _execution_request_from_raw(execution_request)
        refs = {
            **self._request_identity(request_contract),
            "bridge_mode": bridge_mode,
            "provided_context_id": context.context_id if context else None,
            "execution_locked": True,
        }
        return self._lifecycle_step(
            step_index=0,
            step_name="runtime_start",
            status="started",
            description=(
                "C10F runtime controller accepted the C09 contract with "
                "execution locked."
            ),
            refs=refs,
        )

    def runtime_prepare(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
        context: ExecutionContext | None = None,
    ) -> tuple[BridgeRequest, SandboxRuntimeLifecycleStep]:
        request_contract = _execution_request_from_raw(execution_request)
        bridge_request = self.bridge.build_bridge_request(
            request_contract,
            bridge_mode=bridge_mode,
            context=context,
        )
        step = self._lifecycle_step(
            step_index=1,
            step_name="runtime_prepare",
            status="prepared",
            description=(
                "C10F prepared C10C context, C10D resource-control "
                "delegation, and C10E bridge contracts without runtime "
                "creation."
            ),
            refs={
                "bridge_request_id": bridge_request.bridge_request_id,
                "context_id": bridge_request.execution_context.context_id,
                "execution_context_ref": (
                    bridge_request.execution_context.execution_context_ref
                ),
                "sandbox_request_id": (
                    bridge_request.sandbox_request.sandbox_request_id
                ),
                "bridge_stage": BRIDGE_STAGE,
            },
        )
        return bridge_request, step

    def runtime_execute(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
        context: ExecutionContext | None = None,
    ) -> tuple[BridgeResponse, SandboxRuntimeLifecycleStep]:
        request_contract = _execution_request_from_raw(execution_request)
        bridge_response = self.bridge.receive_execution_request(
            request_contract,
            bridge_mode=bridge_mode,
            context=context,
        )
        step = self._lifecycle_step(
            step_index=2,
            step_name="runtime_execute",
            status="mock_executed",
            description=(
                "C10F delegated to the C10E mock bridge and received a safe "
                "mock result only."
            ),
            refs={
                "bridge_response_id": bridge_response.bridge_response_id,
                "sandbox_response_id": (
                    bridge_response.sandbox_response.response_id
                ),
                "execution_status": bridge_response.execution_status,
                "bridge_status": bridge_response.status,
                "runner_stage": RUNNER_STAGE,
                "runner_mode": RUNNER_MODE,
            },
        )
        return bridge_response, step

    def runtime_complete(
        self,
        bridge_response: BridgeResponse,
    ) -> tuple[FinalSafetyLock, SandboxRuntimeLifecycleStep]:
        safety_lock = self.build_final_safety_lock(bridge_response)
        step = self._lifecycle_step(
            step_index=3,
            step_name="runtime_complete",
            status="completed" if safety_lock.safe else "blocked",
            description=(
                "C10F completed mock orchestration and applied the final "
                "safety lock."
            ),
            refs={
                "bridge_response_id": bridge_response.bridge_response_id,
                "sandbox_response_id": bridge_response.sandbox_response.response_id,
                "safety_lock_id": safety_lock.lock_id,
                "safety_lock_safe": safety_lock.safe,
            },
        )
        return safety_lock, step

    def runtime_finalize(
        self,
        bridge_response: BridgeResponse,
        *,
        safety_lock: FinalSafetyLock | None = None,
        steps: tuple[SandboxRuntimeLifecycleStep, ...] = (),
    ) -> SandboxRuntimeResponse:
        lock = safety_lock or self.build_final_safety_lock(bridge_response)
        final_state = self.build_final_state(
            bridge_response,
            safety_lock=lock,
        )
        finalize_step = self._lifecycle_step(
            step_index=len(steps),
            step_name="runtime_finalize",
            status="finalized",
            description=(
                "C10F finalized the sandbox runtime as disabled-execution "
                "mock-only state."
            ),
            refs={
                "final_state_id": final_state.final_state_id,
                "safety_lock_id": lock.lock_id,
                "next_stage_policy": final_state.next_stage_policy,
            },
        )
        lifecycle = self.build_lifecycle((*steps, finalize_step))
        status: RuntimeStatus = (
            "mock_succeeded"
            if lock.safe and bridge_response.status == "mock_succeeded"
            else "mock_blocked"
        )
        return SandboxRuntimeResponse(
            runtime_response_id=_stable_id(
                "runtime_resp",
                {
                    "runtime_key": self.runtime_key,
                    "bridge_response_id": bridge_response.bridge_response_id,
                    "sandbox_response_id": (
                        bridge_response.sandbox_response.response_id
                    ),
                    "safety_lock_id": lock.lock_id,
                    "final_state_id": final_state.final_state_id,
                    "status": status,
                },
            ),
            runtime_key=self.runtime_key,
            runtime_version=self.runtime_version,
            status=status,
            execution_status=bridge_response.execution_status,
            lifecycle=lifecycle,
            safety_lock=lock,
            final_state=final_state,
            bridge_response=bridge_response,
            sandbox_response=bridge_response.sandbox_response,
            c09_result_contract=bridge_response.c09_result_contract,
            safety_notes=[
                *RUNTIME_SAFETY_GUARANTEES,
                *BRIDGE_SAFETY_GUARANTEES,
                *SAFETY_GUARANTEES,
            ],
        )

    def build_lifecycle(
        self,
        steps: tuple[SandboxRuntimeLifecycleStep, ...],
    ) -> SandboxRuntimeLifecycle:
        return SandboxRuntimeLifecycle(
            lifecycle_id=_stable_id(
                "runtime_lifecycle",
                {
                    "runtime_key": self.runtime_key,
                    "steps": [step.model_dump(mode="json") for step in steps],
                },
            ),
            steps=steps,
        )

    def build_final_state(
        self,
        bridge_response: BridgeResponse,
        *,
        safety_lock: FinalSafetyLock,
    ) -> SandboxFinalState:
        sandbox_response = bridge_response.sandbox_response
        return SandboxFinalState(
            final_state_id=_stable_id(
                "sandbox_final_state",
                {
                    "runtime_key": self.runtime_key,
                    "bridge_response_id": bridge_response.bridge_response_id,
                    "sandbox_response_id": sandbox_response.response_id,
                    "safety_lock_id": safety_lock.lock_id,
                    "execution_status": bridge_response.execution_status,
                },
            ),
            final_lock_ref=safety_lock.lock_id,
            bridge_response_id=bridge_response.bridge_response_id,
            sandbox_response_id=sandbox_response.response_id,
            execution_context_ref=sandbox_response.execution_context_ref,
            resource_policy_ref=sandbox_response.result.resource_policy_ref,
        )

    def build_final_safety_lock(
        self,
        bridge_response: BridgeResponse,
    ) -> FinalSafetyLock:
        violations = self._safety_violations(bridge_response)
        safe = not violations
        return FinalSafetyLock(
            lock_id=_stable_id(
                "runtime_lock",
                {
                    "runtime_key": self.runtime_key,
                    "bridge_response_id": bridge_response.bridge_response_id,
                    "sandbox_response_id": (
                        bridge_response.sandbox_response.response_id
                    ),
                    "violations": [
                        violation.model_dump(mode="json")
                        for violation in violations
                    ],
                },
            ),
            lock_status="locked_clean" if safe else "locked_with_violation",
            safe=safe,
            violations=tuple(violations),
        )

    def _safety_violations(
        self,
        bridge_response: BridgeResponse,
    ) -> list[FinalSafetyLockViolation]:
        violations: list[FinalSafetyLockViolation] = []

        def add_violation(code: str, message: str) -> None:
            violations.append(
                FinalSafetyLockViolation(
                    code=code,
                    message=message,
                )
            )

        if bridge_response.next_stage_policy != "wait_for_c10f":
            add_violation(
                "C10F_BRIDGE_STAGE_MISMATCH",
                "C10F can finalize only a C10E bridge response.",
            )
        if bridge_response.safety_guard.safe is not True:
            add_violation(
                "C10F_BRIDGE_GUARD_UNSAFE",
                "C10E bridge safety guard reported violations.",
            )
        if bridge_response.runtime_created:
            add_violation(
                "C10F_RUNTIME_CREATED",
                "Bridge response reported runtime creation.",
            )
        if bridge_response.external_provider_called:
            add_violation(
                "C10F_EXTERNAL_PROVIDER_CALLED",
                "Bridge response reported external provider access.",
            )
        if bridge_response.live_provider_called:
            add_violation(
                "C10F_LIVE_PROVIDER_CALLED",
                "Bridge response reported a live provider call.",
            )
        if bridge_response.network_access_performed:
            add_violation(
                "C10F_NETWORK_ACCESS",
                "Bridge response reported network access.",
            )
        if bridge_response.db_write_performed:
            add_violation(
                "C10F_DB_WRITE",
                "Bridge response reported a database write.",
            )
        if bridge_response.filesystem_access_performed:
            add_violation(
                "C10F_FILESYSTEM_ACCESS",
                "Bridge response reported filesystem access.",
            )
        if bridge_response.production_mutated or bridge_response.staging_mutated:
            add_violation(
                "C10F_ENV_MUTATION",
                "Bridge response reported production or staging mutation.",
            )

        provider_response = bridge_response.provider_forward_response
        if provider_response.external_provider_called:
            add_violation(
                "C10F_PROVIDER_FORWARD_ESCAPED",
                "Provider mock interface reported external provider access.",
            )
        if provider_response.live_provider_called:
            add_violation(
                "C10F_PROVIDER_FORWARD_LIVE_CALL",
                "Provider mock interface reported a live provider call.",
            )
        if provider_response.network_access_performed:
            add_violation(
                "C10F_PROVIDER_FORWARD_NETWORK",
                "Provider mock interface reported network access.",
            )
        if provider_response.db_write_performed:
            add_violation(
                "C10F_PROVIDER_FORWARD_DB_WRITE",
                "Provider mock interface reported a database write.",
            )
        if provider_response.filesystem_access_performed:
            add_violation(
                "C10F_PROVIDER_FORWARD_FILESYSTEM",
                "Provider mock interface reported filesystem access.",
            )
        if provider_response.production_mutated or provider_response.staging_mutated:
            add_violation(
                "C10F_PROVIDER_FORWARD_ENV_MUTATION",
                "Provider mock interface reported environment mutation.",
            )

        sandbox_response = bridge_response.sandbox_response
        sandbox_result = sandbox_response.result
        if sandbox_result.runtime_created:
            add_violation(
                "C10F_RUNNER_RUNTIME_CREATED",
                "Sandbox runner reported runtime creation.",
            )
        if sandbox_result.external_provider_called:
            add_violation(
                "C10F_RUNNER_PROVIDER_CALLED",
                "Sandbox runner reported external provider access.",
            )
        if sandbox_result.db_mutated:
            add_violation(
                "C10F_RUNNER_DB_MUTATED",
                "Sandbox runner reported database mutation.",
            )
        if sandbox_result.production_touched or sandbox_result.staging_touched:
            add_violation(
                "C10F_RUNNER_ENV_TOUCHED",
                "Sandbox runner reported production or staging access.",
            )
        if sandbox_result.filesystem_write_scope != "none":
            add_violation(
                "C10F_RUNNER_FILESYSTEM_WRITE",
                "Sandbox runner reported filesystem writes.",
            )
        if sandbox_result.safe_result_only is not True:
            add_violation(
                "C10F_UNSAFE_SANDBOX_RESULT",
                "Sandbox runner result is not safe-result-only.",
            )

        if (
            sandbox_response.c09_result_contract is not None
            and sandbox_response.c09_result_contract.safe_result_only is not True
        ):
            add_violation(
                "C10F_UNSAFE_C09_RESULT",
                "C09 result contract is not safe-result-only.",
            )

        execution_context = sandbox_response.execution_context
        if execution_context is not None:
            if execution_context.runtime_execution_allowed:
                add_violation(
                    "C10F_CONTEXT_RUNTIME_ALLOWED",
                    "Execution context allows runtime execution.",
                )
            if execution_context.external_provider_call_allowed:
                add_violation(
                    "C10F_CONTEXT_PROVIDER_ALLOWED",
                    "Execution context allows external provider calls.",
                )
            if execution_context.db_mutation_allowed:
                add_violation(
                    "C10F_CONTEXT_DB_MUTATION_ALLOWED",
                    "Execution context allows database mutation.",
                )
            if execution_context.filesystem_write_allowed:
                add_violation(
                    "C10F_CONTEXT_FILESYSTEM_ALLOWED",
                    "Execution context allows filesystem writes.",
                )
            if (
                execution_context.production_access_allowed
                or execution_context.staging_access_allowed
            ):
                add_violation(
                    "C10F_CONTEXT_ENV_ALLOWED",
                    "Execution context allows production or staging access.",
                )

        resource_policy = sandbox_response.resource_policy
        if resource_policy is not None:
            if resource_policy.network_access_allowed:
                add_violation(
                    "C10F_RESOURCE_NETWORK_ALLOWED",
                    "Resource policy allows network access.",
                )
            if resource_policy.external_api_allowed:
                add_violation(
                    "C10F_RESOURCE_EXTERNAL_API_ALLOWED",
                    "Resource policy allows external API access.",
                )
            if resource_policy.os_interaction_allowed:
                add_violation(
                    "C10F_RESOURCE_OS_INTERACTION_ALLOWED",
                    "Resource policy allows OS interaction.",
                )
            if (
                resource_policy.cpu_os_enforced
                or resource_policy.memory_os_enforced
                or resource_policy.timeout_os_enforced
            ):
                add_violation(
                    "C10F_RESOURCE_OS_ENFORCEMENT",
                    "Resource policy reported OS-level enforcement.",
                )

        return violations

    def _lifecycle_step(
        self,
        *,
        step_index: int,
        step_name: RuntimeLifecycleStepName,
        status: RuntimeLifecycleStepStatus,
        description: str,
        refs: dict[str, Any],
    ) -> SandboxRuntimeLifecycleStep:
        return SandboxRuntimeLifecycleStep(
            step_index=step_index,
            step_name=step_name,
            status=status,
            description=description,
            refs={
                "runtime_key": self.runtime_key,
                "runtime_version": self.runtime_version,
                "runtime_mode": RUNTIME_MODE,
                "mock_only": True,
                **refs,
            },
        )

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


def finalize_sandbox_runtime(
    execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    *,
    bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
    context: ExecutionContext | None = None,
) -> SandboxRuntimeResponse:
    return SandboxRuntime().handle_execution_request(
        execution_request,
        bridge_mode=bridge_mode,
        context=context,
    )


__all__ = [
    "RUNTIME_EXECUTION_CAPABILITY",
    "RUNTIME_LIFECYCLE_STEPS",
    "RUNTIME_MODE",
    "RUNTIME_PIPELINE",
    "RUNTIME_SAFETY_GUARANTEES",
    "RUNTIME_STAGE",
    "FinalSafetyLock",
    "FinalSafetyLockViolation",
    "RuntimeLifecycleStepName",
    "RuntimeLifecycleStepStatus",
    "RuntimeStatus",
    "SandboxFinalState",
    "SandboxRuntime",
    "SandboxRuntimeLifecycle",
    "SandboxRuntimeLifecycleStep",
    "SandboxRuntimeResponse",
    "finalize_sandbox_runtime",
]
