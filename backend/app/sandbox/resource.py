from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RESOURCE_CONTROL_STAGE: Literal["c10d_resource_control"] = (
    "c10d_resource_control"
)
DEFAULT_CPU_QUOTA = 100
DEFAULT_MEMORY_QUOTA = 256
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_NETWORK_POLICY: Literal["DENY_ALL"] = "DENY_ALL"
DEFAULT_FILE_ACCESS_POLICY: Literal["SANDBOX_ONLY"] = "SANDBOX_ONLY"

NetworkPolicy = Literal["DENY_ALL"]
FileAccessPolicy = Literal["SANDBOX_ONLY"]
ResourceViolationType = Literal[
    "policy_binding_mismatch",
    "cpu_quota_invalid",
    "memory_quota_invalid",
    "timeout_invalid",
    "network_access_requested",
    "filesystem_scope_violation",
    "external_api_requested",
    "os_enforcement_requested",
    "context_policy_mismatch",
]


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


class ResourceControlModel(BaseModel):
    """Logical C10D resource controls.

    These fields describe mock resource limits only. They are never translated
    into process, cgroup, container, kernel, or filesystem controls.
    """

    model_config = ConfigDict(frozen=True)

    cpu_limit: int = Field(default=DEFAULT_CPU_QUOTA, ge=1)
    memory_limit: int = Field(default=DEFAULT_MEMORY_QUOTA, ge=1)
    timeout_limit: int = Field(default=DEFAULT_TIMEOUT_MS, ge=1)
    network_access: Literal["DENIED"] = "DENIED"
    filesystem_access_scope: Literal["SANDBOX_ONLY"] = "SANDBOX_ONLY"
    mode: Literal["mock_only"] = "mock_only"
    cpu_enforcement: Literal["logical_only"] = "logical_only"
    memory_enforcement: Literal["logical_only"] = "logical_only"
    timeout_enforcement: Literal["logical_only"] = "logical_only"
    os_enforcement_enabled: Literal[False] = False
    external_api_allowed: Literal[False] = False


class ResourcePolicy(BaseModel):
    """Bound mock resource policy for one execution context."""

    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(min_length=1, max_length=180)
    execution_id: str = Field(min_length=1, max_length=128)
    context_id: str = Field(min_length=1, max_length=128)
    cpu_quota: int = Field(default=DEFAULT_CPU_QUOTA, ge=1)
    memory_quota: int = Field(default=DEFAULT_MEMORY_QUOTA, ge=1)
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, ge=1)
    network_policy: NetworkPolicy = DEFAULT_NETWORK_POLICY
    file_access_policy: FileAccessPolicy = DEFAULT_FILE_ACCESS_POLICY
    control_model: ResourceControlModel = Field(default_factory=ResourceControlModel)
    stage: Literal["c10d_resource_control"] = RESOURCE_CONTROL_STAGE
    mock_only: Literal[True] = True
    cpu_os_enforced: Literal[False] = False
    memory_os_enforced: Literal[False] = False
    timeout_os_enforced: Literal[False] = False
    network_access_allowed: Literal[False] = False
    external_api_allowed: Literal[False] = False
    filesystem_access_scope: Literal["SANDBOX_ONLY"] = "SANDBOX_ONLY"
    os_interaction_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_control_model_binding(self) -> ResourcePolicy:
        if self.control_model.cpu_limit != self.cpu_quota:
            raise ValueError("control_model.cpu_limit must match cpu_quota.")
        if self.control_model.memory_limit != self.memory_quota:
            raise ValueError("control_model.memory_limit must match memory_quota.")
        if self.control_model.timeout_limit != self.timeout_ms:
            raise ValueError("control_model.timeout_limit must match timeout_ms.")
        return self


class ResourceViolation(BaseModel):
    """C10D resource violation model."""

    model_config = ConfigDict(frozen=True)

    violation_type: ResourceViolationType
    violation_reason: str = Field(min_length=1, max_length=400)
    execution_blocked: bool = True
    execution_id: str | None = Field(default=None, max_length=128)
    context_id: str | None = Field(default=None, max_length=128)
    resource_policy_ref: str | None = Field(default=None, max_length=180)


class ResourceEnforcementReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy: ResourcePolicy
    violations: tuple[ResourceViolation, ...] = Field(default_factory=tuple)
    execution_blocked: bool = False
    stage: Literal["c10d_resource_control"] = RESOURCE_CONTROL_STAGE
    mock_only: Literal[True] = True
    deterministic: Literal[True] = True
    cpu_os_enforced: Literal[False] = False
    memory_os_enforced: Literal[False] = False
    os_interaction_performed: Literal[False] = False
    network_access_performed: Literal[False] = False
    external_api_called: Literal[False] = False


class SandboxResourceEnforcer:
    """Mock-only resource enforcer for C10D.

    The enforcer validates logical policy data and returns copied context
    models with policy references attached. It does not inspect or control
    real host resources.
    """

    def __init__(
        self,
        *,
        enforcer_key: str = "c10d.resource_enforcer.mock.v1",
        cpu_quota: int = DEFAULT_CPU_QUOTA,
        memory_quota: int = DEFAULT_MEMORY_QUOTA,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self.enforcer_key = enforcer_key
        self.cpu_quota = cpu_quota
        self.memory_quota = memory_quota
        self.timeout_ms = timeout_ms

    def build_policy(
        self,
        *,
        execution_id: str,
        context_id: str,
    ) -> ResourcePolicy:
        control_model = ResourceControlModel(
            cpu_limit=self.cpu_quota,
            memory_limit=self.memory_quota,
            timeout_limit=self.timeout_ms,
        )
        return ResourcePolicy(
            policy_id=_stable_id(
                "resource_policy",
                {
                    "enforcer_key": self.enforcer_key,
                    "execution_id": execution_id,
                    "context_id": context_id,
                    "cpu_quota": self.cpu_quota,
                    "memory_quota": self.memory_quota,
                    "timeout_ms": self.timeout_ms,
                    "network_policy": DEFAULT_NETWORK_POLICY,
                    "file_access_policy": DEFAULT_FILE_ACCESS_POLICY,
                },
            ),
            execution_id=execution_id,
            context_id=context_id,
            cpu_quota=self.cpu_quota,
            memory_quota=self.memory_quota,
            timeout_ms=self.timeout_ms,
            control_model=control_model,
        )

    def enforce_before_run(
        self,
        *,
        sandbox_request: Any,
        sandbox_context: Any,
        execution_context: Any,
    ) -> tuple[Any, Any, ResourceEnforcementReport]:
        policy = self._select_policy(sandbox_context, execution_context)
        if policy is None:
            policy = self.build_policy(
                execution_id=execution_context.execution_id,
                context_id=execution_context.context_id,
            )

        violations = self._validate_policy(
            policy=policy,
            sandbox_request=sandbox_request,
            sandbox_context=sandbox_context,
            execution_context=execution_context,
        )
        bound_execution_context = self.attach_policy_to_execution_context(
            execution_context,
            policy=policy,
        )
        bound_sandbox_context = self.attach_policy_to_sandbox_context(
            sandbox_context,
            policy=policy,
        )
        report = ResourceEnforcementReport(
            policy=policy,
            violations=tuple(violations),
            execution_blocked=any(
                violation.execution_blocked for violation in violations
            ),
        )
        return bound_sandbox_context, bound_execution_context, report

    def attach_policy_to_execution_context(
        self,
        execution_context: Any,
        *,
        policy: ResourcePolicy,
    ) -> Any:
        return execution_context.model_copy(
            update={
                "resource_policy_ref": policy.policy_id,
                "resource_policy": policy,
            }
        )

    def attach_policy_to_sandbox_context(
        self,
        sandbox_context: Any,
        *,
        policy: ResourcePolicy,
    ) -> Any:
        return sandbox_context.model_copy(
            update={
                "stage": RESOURCE_CONTROL_STAGE,
                "resource_policy_ref": policy.policy_id,
                "resource_policy": policy,
                "resource_control_stage": RESOURCE_CONTROL_STAGE,
                "network_policy": policy.network_policy,
                "file_access_policy": policy.file_access_policy,
            }
        )

    def _select_policy(
        self,
        sandbox_context: Any,
        execution_context: Any,
    ) -> ResourcePolicy | None:
        execution_policy = getattr(execution_context, "resource_policy", None)
        context_policy = getattr(sandbox_context, "resource_policy", None)
        if isinstance(execution_policy, ResourcePolicy):
            return execution_policy
        if isinstance(context_policy, ResourcePolicy):
            return context_policy
        return None

    def _validate_policy(
        self,
        *,
        policy: ResourcePolicy,
        sandbox_request: Any,
        sandbox_context: Any,
        execution_context: Any,
    ) -> list[ResourceViolation]:
        violations: list[ResourceViolation] = []
        execution_id = getattr(execution_context, "execution_id", None)
        context_id = getattr(execution_context, "context_id", None)

        def add_violation(
            violation_type: ResourceViolationType,
            violation_reason: str,
        ) -> None:
            violations.append(
                ResourceViolation(
                    violation_type=violation_type,
                    violation_reason=violation_reason,
                    execution_blocked=True,
                    execution_id=execution_id,
                    context_id=context_id,
                    resource_policy_ref=policy.policy_id,
                )
            )

        if policy.execution_id != execution_id:
            add_violation(
                "policy_binding_mismatch",
                "ResourcePolicy execution_id is not bound to the execution context.",
            )
        if policy.context_id != context_id:
            add_violation(
                "policy_binding_mismatch",
                "ResourcePolicy context_id is not bound to the execution context.",
            )
        if getattr(sandbox_request, "context_id", None) != context_id:
            add_violation(
                "policy_binding_mismatch",
                "Sandbox request context_id is not bound to the execution context.",
            )

        self._validate_existing_ref(
            holder=sandbox_context,
            holder_name="Sandbox context",
            policy=policy,
            add_violation=add_violation,
        )
        self._validate_existing_ref(
            holder=execution_context,
            holder_name="Execution context",
            policy=policy,
            add_violation=add_violation,
        )

        if policy.cpu_quota <= 0 or policy.cpu_quota > self.cpu_quota:
            add_violation(
                "cpu_quota_invalid",
                "CPU quota exceeds the logical mock resource policy.",
            )
        if policy.memory_quota <= 0 or policy.memory_quota > self.memory_quota:
            add_violation(
                "memory_quota_invalid",
                "Memory quota exceeds the logical mock resource policy.",
            )
        if policy.timeout_ms <= 0 or policy.timeout_ms > self.timeout_ms:
            add_violation(
                "timeout_invalid",
                "Timeout exceeds the logical mock resource policy.",
            )

        if policy.network_policy != DEFAULT_NETWORK_POLICY:
            add_violation(
                "network_access_requested",
                "Network access must remain DENY_ALL in C10D.",
            )
        if policy.network_access_allowed is not False:
            add_violation(
                "network_access_requested",
                "ResourcePolicy cannot allow network access.",
            )
        if policy.file_access_policy != DEFAULT_FILE_ACCESS_POLICY:
            add_violation(
                "filesystem_scope_violation",
                "File access must remain SANDBOX_ONLY in C10D.",
            )
        if policy.filesystem_access_scope != DEFAULT_FILE_ACCESS_POLICY:
            add_violation(
                "filesystem_scope_violation",
                "Filesystem access scope must remain SANDBOX_ONLY.",
            )
        if policy.external_api_allowed is not False:
            add_violation(
                "external_api_requested",
                "External API access is not allowed by C10D.",
            )
        if (
            policy.cpu_os_enforced
            or policy.memory_os_enforced
            or policy.timeout_os_enforced
            or policy.os_interaction_allowed
            or policy.control_model.os_enforcement_enabled
        ):
            add_violation(
                "os_enforcement_requested",
                "C10D allows only mock logical enforcement, not OS enforcement.",
            )

        if getattr(sandbox_context, "external_provider_policy", "denied") != "denied":
            add_violation(
                "external_api_requested",
                "Sandbox context external provider policy must remain denied.",
            )
        if (
            getattr(sandbox_context, "filesystem_write_policy", "sandbox_scope_only")
            != "sandbox_scope_only"
        ):
            add_violation(
                "filesystem_scope_violation",
                "Sandbox context filesystem writes must remain sandbox scoped.",
            )

        requested_capabilities = set(
            getattr(sandbox_request, "requested_capabilities", ())
        )
        if requested_capabilities.intersection(
            {"network_access", "network", "external_provider_call"}
        ):
            add_violation(
                "network_access_requested",
                "Sandbox request asked for network or provider access.",
            )
        if requested_capabilities.intersection(
            {"external_api", "external_api_call", "external_provider"}
        ):
            add_violation(
                "external_api_requested",
                "Sandbox request asked for external API access.",
            )
        if requested_capabilities.intersection(
            {
                "filesystem_write_outside_sandbox",
                "filesystem_unrestricted",
                "host_filesystem_access",
            }
        ):
            add_violation(
                "filesystem_scope_violation",
                "Sandbox request asked for filesystem access outside the sandbox.",
            )

        return violations

    def _validate_existing_ref(
        self,
        *,
        holder: Any,
        holder_name: str,
        policy: ResourcePolicy,
        add_violation: Any,
    ) -> None:
        existing_ref = getattr(holder, "resource_policy_ref", None)
        if existing_ref is not None and existing_ref != policy.policy_id:
            add_violation(
                "context_policy_mismatch",
                f"{holder_name} already references a different resource policy.",
            )


__all__ = [
    "DEFAULT_CPU_QUOTA",
    "DEFAULT_FILE_ACCESS_POLICY",
    "DEFAULT_MEMORY_QUOTA",
    "DEFAULT_NETWORK_POLICY",
    "DEFAULT_TIMEOUT_MS",
    "RESOURCE_CONTROL_STAGE",
    "FileAccessPolicy",
    "NetworkPolicy",
    "ResourceControlModel",
    "ResourceEnforcementReport",
    "ResourcePolicy",
    "ResourceViolation",
    "ResourceViolationType",
    "SandboxResourceEnforcer",
]
