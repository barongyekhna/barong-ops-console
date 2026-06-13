"""C10 sandbox architecture and mock runner contracts.

C10A defines the sandbox boundary, isolation model, and contract schemas.
C10B adds a deterministic mock runner that simulates lifecycle responses
without creating an execution runtime or connecting to any external provider.
C10C adds isolated execution contexts, deterministic context factories, and
mock-only context lifecycle transitions.
C10D adds logical mock resource policies and resource violation handling without
OS-level enforcement.
"""

from .execution_context import (
    EXECUTION_CONTEXT_STAGE,
    ExecutionContext,
    ExecutionContextFactory,
    ExecutionContextIsolationGuarantees,
    ExecutionContextIsolationReport,
    ExecutionContextIsolationRules,
    ExecutionContextIsolationViolation,
    ExecutionContextLifecycleSnapshot,
    ExecutionContextLifecycleState,
    ExecutionContextLifecycleStateMachine,
    ExecutionContextLifecycleTransition,
    ExecutionContextLogScope,
    ExecutionContextMemoryScope,
    ExecutionContextStateScope,
    ExecutionIsolationLevel,
)
from .runner import (
    RUNNER_MODE,
    RUNNER_STAGE,
    SAFETY_GUARANTEES,
    SandboxMockExecutionFlow,
    SandboxMockLifecycleStep,
    SandboxRunner,
    SandboxRunnerPolicyViolation,
    deterministic_mock_execution_response,
    handle_execution_request,
)
from .resource import (
    RESOURCE_CONTROL_STAGE,
    ResourceControlModel,
    ResourceEnforcementReport,
    ResourcePolicy,
    ResourceViolation,
    SandboxResourceEnforcer,
)

__all__ = [
    "EXECUTION_CONTEXT_STAGE",
    "RESOURCE_CONTROL_STAGE",
    "RUNNER_MODE",
    "RUNNER_STAGE",
    "SAFETY_GUARANTEES",
    "ExecutionContext",
    "ExecutionContextFactory",
    "ExecutionContextIsolationGuarantees",
    "ExecutionContextIsolationReport",
    "ExecutionContextIsolationRules",
    "ExecutionContextIsolationViolation",
    "ExecutionContextLifecycleSnapshot",
    "ExecutionContextLifecycleState",
    "ExecutionContextLifecycleStateMachine",
    "ExecutionContextLifecycleTransition",
    "ExecutionContextLogScope",
    "ExecutionContextMemoryScope",
    "ExecutionContextStateScope",
    "ExecutionIsolationLevel",
    "ResourceControlModel",
    "ResourceEnforcementReport",
    "ResourcePolicy",
    "ResourceViolation",
    "SandboxMockExecutionFlow",
    "SandboxMockLifecycleStep",
    "SandboxResourceEnforcer",
    "SandboxRunner",
    "SandboxRunnerPolicyViolation",
    "deterministic_mock_execution_response",
    "handle_execution_request",
]
