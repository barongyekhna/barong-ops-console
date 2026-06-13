"""C10 sandbox architecture and mock runner contracts.

C10A defines the sandbox boundary, isolation model, and contract schemas.
C10B adds a deterministic mock runner that simulates lifecycle responses
without creating an execution runtime or connecting to any external provider.
"""

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

__all__ = [
    "RUNNER_MODE",
    "RUNNER_STAGE",
    "SAFETY_GUARANTEES",
    "SandboxMockExecutionFlow",
    "SandboxMockLifecycleStep",
    "SandboxRunner",
    "SandboxRunnerPolicyViolation",
    "deterministic_mock_execution_response",
    "handle_execution_request",
]
