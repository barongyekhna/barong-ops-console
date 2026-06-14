"""C10 sandbox architecture and mock runner contracts.

C10A defines the sandbox boundary, isolation model, and contract schemas.
C10B adds a deterministic mock runner that simulates lifecycle responses
without creating an execution runtime or connecting to any external provider.
C10C adds isolated execution contexts, deterministic context factories, and
mock-only context lifecycle transitions.
C10D adds logical mock resource policies and resource violation handling without
OS-level enforcement.
C10E adds the mock-only bridge from C09 execution request contracts to the C10
sandbox runner and a C09 provider mock interface without live provider calls.
"""

from .bridge import (
    BRIDGE_FLOW,
    BRIDGE_SAFETY_GUARANTEES,
    BRIDGE_STAGE,
    PROVIDER_MOCK_INTERFACE_KEY,
    BridgeRequest,
    BridgeResponse,
    BridgeSafetyGuardReport,
    BridgeSafetyViolation,
    BridgeStatus,
    C09MockExecutionProviderInterface,
    C09MockProviderForwardRequest,
    C09MockProviderForwardResponse,
    ProviderForwardStatus,
    ProviderRequestMapping,
    SandboxBridgeMode,
    SandboxExecutionBridge,
    SandboxRequestMapping,
    bridge_execution_request,
)
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
    "BRIDGE_FLOW",
    "BRIDGE_SAFETY_GUARANTEES",
    "BRIDGE_STAGE",
    "EXECUTION_CONTEXT_STAGE",
    "PROVIDER_MOCK_INTERFACE_KEY",
    "RESOURCE_CONTROL_STAGE",
    "RUNNER_MODE",
    "RUNNER_STAGE",
    "SAFETY_GUARANTEES",
    "BridgeRequest",
    "BridgeResponse",
    "BridgeSafetyGuardReport",
    "BridgeSafetyViolation",
    "BridgeStatus",
    "C09MockExecutionProviderInterface",
    "C09MockProviderForwardRequest",
    "C09MockProviderForwardResponse",
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
    "ProviderForwardStatus",
    "ProviderRequestMapping",
    "SandboxBridgeMode",
    "SandboxMockExecutionFlow",
    "SandboxMockLifecycleStep",
    "SandboxExecutionBridge",
    "SandboxResourceEnforcer",
    "SandboxRequestMapping",
    "SandboxRunner",
    "SandboxRunnerPolicyViolation",
    "bridge_execution_request",
    "deterministic_mock_execution_response",
    "handle_execution_request",
]
