from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..schemas.execution_provider import ExecutionRequestContractV1


EXECUTION_CONTEXT_STAGE: Literal["c10c_execution_context"] = (
    "c10c_execution_context"
)
ExecutionContextLifecycleState = Literal[
    "created",
    "initialized",
    "running",
    "completed",
    "failed",
    "archived",
]
ExecutionIsolationLevel = Literal["strict_per_execution_request_mock"]


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


class ExecutionContextMemoryScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_scope_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=128)
    mode: Literal["mock_only"] = "mock_only"
    shared_memory_allowed: Literal[False] = False
    cross_context_read_allowed: Literal[False] = False
    cross_context_write_allowed: Literal[False] = False
    persisted: Literal[False] = False
    entries: tuple[dict[str, Any], ...] = Field(
        default_factory=tuple,
        max_length=0,
    )


class ExecutionContextLogScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    log_scope_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=128)
    mode: Literal["mock_only"] = "mock_only"
    shared_log_allowed: Literal[False] = False
    operation_log_write_allowed: Literal[False] = False
    audit_event_write_allowed: Literal[False] = False
    persisted: Literal[False] = False
    emitted_logs: tuple[dict[str, Any], ...] = Field(
        default_factory=tuple,
        max_length=0,
    )


class ExecutionContextStateScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    state_scope_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=128)
    mode: Literal["mock_only"] = "mock_only"
    shared_state_allowed: Literal[False] = False
    cross_context_mutation_allowed: Literal[False] = False
    persisted: Literal[False] = False


class ExecutionContextIsolationGuarantees(BaseModel):
    model_config = ConfigDict(frozen=True)

    no_shared_memory: Literal[True] = True
    no_shared_execution_state: Literal[True] = True
    no_shared_logs: Literal[True] = True
    no_cross_context_mutation: Literal[True] = True
    no_external_system_dependency: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_filesystem_write: Literal[True] = True
    no_db_mutation: Literal[True] = True
    no_production_or_staging_access: Literal[True] = True


class ExecutionContext(BaseModel):
    """C10C isolated execution context.

    The model is frozen and mock-only. Lifecycle changes are represented by
    copied models returned by the lifecycle state machine, not by in-place
    mutation.
    """

    model_config = ConfigDict(frozen=True)

    context_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    actor_user_id: int | None = None
    scope_ref: str = Field(min_length=1, max_length=180)
    sandbox_scope_ref: str = Field(min_length=1, max_length=180)
    execution_context_ref: str = Field(min_length=1, max_length=180)
    isolation_level: ExecutionIsolationLevel = "strict_per_execution_request_mock"
    memory_scope: ExecutionContextMemoryScope
    log_scope: ExecutionContextLogScope
    state_scope: ExecutionContextStateScope
    lifecycle_state: ExecutionContextLifecycleState = "created"
    stage: Literal["c10c_execution_context"] = EXECUTION_CONTEXT_STAGE
    factory_key: str = Field(min_length=1, max_length=180)
    lifecycle_mock_only: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_provider_call_allowed: Literal[False] = False
    db_mutation_allowed: Literal[False] = False
    filesystem_write_allowed: Literal[False] = False
    production_access_allowed: Literal[False] = False
    staging_access_allowed: Literal[False] = False
    isolation_guarantees: ExecutionContextIsolationGuarantees = Field(
        default_factory=ExecutionContextIsolationGuarantees
    )

    @model_validator(mode="after")
    def _validate_scope_binding(self) -> ExecutionContext:
        if self.memory_scope.context_id != self.context_id:
            raise ValueError("memory_scope must be bound to context_id.")
        if self.log_scope.context_id != self.context_id:
            raise ValueError("log_scope must be bound to context_id.")
        if self.state_scope.context_id != self.context_id:
            raise ValueError("state_scope must be bound to context_id.")
        return self


class ExecutionContextLifecycleTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    transition_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=128)
    sequence_index: int = Field(ge=0)
    from_state: ExecutionContextLifecycleState
    to_state: ExecutionContextLifecycleState
    reason: str = Field(min_length=1, max_length=240)
    mock_only: Literal[True] = True
    runtime_created: Literal[False] = False
    external_provider_called: Literal[False] = False
    db_mutated: Literal[False] = False
    filesystem_written: Literal[False] = False


class ExecutionContextLifecycleSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    context_id: str = Field(min_length=1, max_length=128)
    current_state: ExecutionContextLifecycleState
    transitions: tuple[ExecutionContextLifecycleTransition, ...] = Field(
        default_factory=tuple
    )
    allowed_next_states: tuple[ExecutionContextLifecycleState, ...] = Field(
        default_factory=tuple
    )
    terminal: bool = False
    mock_only: Literal[True] = True


class ExecutionContextLifecycleStateMachine:
    """Pure mock lifecycle transitions for C10C contexts."""

    allowed_transitions: ClassVar[
        dict[
            ExecutionContextLifecycleState,
            tuple[ExecutionContextLifecycleState, ...],
        ]
    ] = {
        "created": ("initialized",),
        "initialized": ("running", "failed"),
        "running": ("completed", "failed"),
        "completed": ("archived",),
        "failed": ("archived",),
        "archived": (),
    }

    terminal_states: ClassVar[set[ExecutionContextLifecycleState]] = {
        "completed",
        "failed",
        "archived",
    }

    @classmethod
    def snapshot(
        cls,
        context: ExecutionContext,
        *,
        transitions: tuple[ExecutionContextLifecycleTransition, ...] = (),
    ) -> ExecutionContextLifecycleSnapshot:
        return ExecutionContextLifecycleSnapshot(
            context_id=context.context_id,
            current_state=context.lifecycle_state,
            transitions=transitions,
            allowed_next_states=cls.allowed_transitions[context.lifecycle_state],
            terminal=context.lifecycle_state in cls.terminal_states,
        )

    @classmethod
    def transition(
        cls,
        context: ExecutionContext,
        to_state: ExecutionContextLifecycleState,
        *,
        reason: str,
        transitions: tuple[ExecutionContextLifecycleTransition, ...] = (),
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        allowed_next_states = cls.allowed_transitions[context.lifecycle_state]
        if to_state not in allowed_next_states:
            raise ValueError(
                "Invalid C10C lifecycle transition: "
                f"{context.lifecycle_state} -> {to_state}."
            )

        transition = ExecutionContextLifecycleTransition(
            transition_id=_stable_id(
                "ctx_transition",
                {
                    "context_id": context.context_id,
                    "sequence_index": len(transitions),
                    "from_state": context.lifecycle_state,
                    "to_state": to_state,
                    "reason": reason,
                },
            ),
            context_id=context.context_id,
            sequence_index=len(transitions),
            from_state=context.lifecycle_state,
            to_state=to_state,
            reason=reason,
        )
        updated = context.model_copy(update={"lifecycle_state": to_state})
        updated_transitions = (*transitions, transition)
        return updated, cls.snapshot(updated, transitions=updated_transitions)

    @classmethod
    def initialize(
        cls,
        context: ExecutionContext,
        *,
        transitions: tuple[ExecutionContextLifecycleTransition, ...] = (),
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        return cls.transition(
            context,
            "initialized",
            reason="Execution context initialized for mock sandbox binding.",
            transitions=transitions,
        )

    @classmethod
    def start(
        cls,
        context: ExecutionContext,
        *,
        transitions: tuple[ExecutionContextLifecycleTransition, ...] = (),
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        return cls.transition(
            context,
            "running",
            reason="Mock execution scope marked running without runtime creation.",
            transitions=transitions,
        )

    @classmethod
    def complete(
        cls,
        context: ExecutionContext,
        *,
        transitions: tuple[ExecutionContextLifecycleTransition, ...] = (),
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        return cls.transition(
            context,
            "completed",
            reason="Mock execution scope completed with safe result only.",
            transitions=transitions,
        )

    @classmethod
    def fail(
        cls,
        context: ExecutionContext,
        *,
        transitions: tuple[ExecutionContextLifecycleTransition, ...] = (),
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        return cls.transition(
            context,
            "failed",
            reason="Mock execution scope failed before any runtime execution.",
            transitions=transitions,
        )

    @classmethod
    def archive(
        cls,
        context: ExecutionContext,
        *,
        transitions: tuple[ExecutionContextLifecycleTransition, ...] = (),
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        return cls.transition(
            context,
            "archived",
            reason="Mock execution context archived without persistence.",
            transitions=transitions,
        )

    @classmethod
    def run_mock_success(
        cls,
        context: ExecutionContext,
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        initialized, snapshot = cls.initialize(context)
        running, snapshot = cls.start(
            initialized,
            transitions=snapshot.transitions,
        )
        return cls.complete(running, transitions=snapshot.transitions)

    @classmethod
    def run_mock_failure(
        cls,
        context: ExecutionContext,
    ) -> tuple[ExecutionContext, ExecutionContextLifecycleSnapshot]:
        initialized, snapshot = cls.initialize(context)
        return cls.fail(initialized, transitions=snapshot.transitions)


class ExecutionContextIsolationViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=300)
    context_id: str | None = Field(default=None, max_length=128)
    other_context_id: str | None = Field(default=None, max_length=128)


class ExecutionContextIsolationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    isolated: bool
    violations: tuple[ExecutionContextIsolationViolation, ...] = Field(
        default_factory=tuple
    )


class ExecutionContextIsolationRules:
    """Static isolation checks for C10C context models."""

    @classmethod
    def validate_context(
        cls,
        context: ExecutionContext,
    ) -> ExecutionContextIsolationReport:
        violations: list[ExecutionContextIsolationViolation] = []
        if context.memory_scope.context_id != context.context_id:
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_MEMORY_SCOPE_MISMATCH",
                    message="Memory scope is not bound to the execution context.",
                    context_id=context.context_id,
                )
            )
        if context.log_scope.context_id != context.context_id:
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_LOG_SCOPE_MISMATCH",
                    message="Log scope is not bound to the execution context.",
                    context_id=context.context_id,
                )
            )
        if context.state_scope.context_id != context.context_id:
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_STATE_SCOPE_MISMATCH",
                    message="State scope is not bound to the execution context.",
                    context_id=context.context_id,
                )
            )
        return ExecutionContextIsolationReport(
            isolated=not violations,
            violations=tuple(violations),
        )

    @classmethod
    def validate_context_pair(
        cls,
        left: ExecutionContext,
        right: ExecutionContext,
    ) -> ExecutionContextIsolationReport:
        violations: list[ExecutionContextIsolationViolation] = []
        if left.context_id == right.context_id:
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_CONTEXT_REUSE",
                    message="Execution contexts must not reuse context_id.",
                    context_id=left.context_id,
                    other_context_id=right.context_id,
                )
            )
        if left.memory_scope.memory_scope_id == right.memory_scope.memory_scope_id:
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_SHARED_MEMORY_SCOPE",
                    message="Execution contexts must not share memory scopes.",
                    context_id=left.context_id,
                    other_context_id=right.context_id,
                )
            )
        if left.log_scope.log_scope_id == right.log_scope.log_scope_id:
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_SHARED_LOG_SCOPE",
                    message="Execution contexts must not share log scopes.",
                    context_id=left.context_id,
                    other_context_id=right.context_id,
                )
            )
        if left.state_scope.state_scope_id == right.state_scope.state_scope_id:
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_SHARED_STATE_SCOPE",
                    message="Execution contexts must not share state scopes.",
                    context_id=left.context_id,
                    other_context_id=right.context_id,
                )
            )
        return ExecutionContextIsolationReport(
            isolated=not violations,
            violations=tuple(violations),
        )


class ExecutionContextFactory:
    """Deterministic factory for one isolated context per execution request."""

    def __init__(
        self,
        *,
        factory_key: str = "c10c.execution_context_factory.v1",
    ) -> None:
        self.factory_key = factory_key

    def create_context(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    ) -> ExecutionContext:
        request_contract = self._execution_request_from_raw(execution_request)
        execution_id = self.execution_id_for_request(request_contract)
        context_id = self.context_id_for_request(request_contract)
        scope_ref = _stable_id(
            "scope_ref",
            {
                "context_id": context_id,
                "execution_id": execution_id,
                "module_key": request_contract.module_key,
                "adapter_key": request_contract.adapter_key,
                "action_key": request_contract.action_key,
                "target_scope": request_contract.target_scope,
            },
        )
        sandbox_scope_ref = _stable_id(
            "sandbox_scope",
            {
                "context_id": context_id,
                "scope_ref": scope_ref,
                "module_key": request_contract.module_key,
                "adapter_key": request_contract.adapter_key,
            },
        )
        execution_context_ref = _stable_id(
            "execution_context_ref",
            {
                "context_id": context_id,
                "execution_id": execution_id,
            },
        )
        return ExecutionContext(
            context_id=context_id,
            execution_id=execution_id,
            module_key=request_contract.module_key,
            adapter_key=request_contract.adapter_key,
            action_key=request_contract.action_key,
            actor_user_id=request_contract.actor_user_id,
            scope_ref=scope_ref,
            sandbox_scope_ref=sandbox_scope_ref,
            execution_context_ref=execution_context_ref,
            memory_scope=ExecutionContextMemoryScope(
                memory_scope_id=_stable_id(
                    "memory_scope",
                    {
                        "context_id": context_id,
                        "execution_context_ref": execution_context_ref,
                    },
                ),
                context_id=context_id,
            ),
            log_scope=ExecutionContextLogScope(
                log_scope_id=_stable_id(
                    "log_scope",
                    {
                        "context_id": context_id,
                        "execution_context_ref": execution_context_ref,
                    },
                ),
                context_id=context_id,
            ),
            state_scope=ExecutionContextStateScope(
                state_scope_id=_stable_id(
                    "state_scope",
                    {
                        "context_id": context_id,
                        "execution_context_ref": execution_context_ref,
                    },
                ),
                context_id=context_id,
            ),
            factory_key=self.factory_key,
        )

    def binding_violations(
        self,
        context: ExecutionContext,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    ) -> tuple[ExecutionContextIsolationViolation, ...]:
        expected = self.create_context(execution_request)
        violations: list[ExecutionContextIsolationViolation] = []
        comparable_fields = (
            "context_id",
            "execution_id",
            "module_key",
            "adapter_key",
            "action_key",
            "actor_user_id",
            "scope_ref",
            "sandbox_scope_ref",
            "execution_context_ref",
            "isolation_level",
        )
        for field_name in comparable_fields:
            if getattr(context, field_name) != getattr(expected, field_name):
                violations.append(
                    ExecutionContextIsolationViolation(
                        code="C10C_CONTEXT_BINDING_MISMATCH",
                        message=(
                            "Execution context does not match the deterministic "
                            f"binding field: {field_name}."
                        ),
                        context_id=context.context_id,
                    )
                )

        if (
            context.memory_scope.memory_scope_id
            != expected.memory_scope.memory_scope_id
        ):
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_MEMORY_SCOPE_BINDING_MISMATCH",
                    message="Memory scope does not match deterministic binding.",
                    context_id=context.context_id,
                )
            )
        if context.log_scope.log_scope_id != expected.log_scope.log_scope_id:
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_LOG_SCOPE_BINDING_MISMATCH",
                    message="Log scope does not match deterministic binding.",
                    context_id=context.context_id,
                )
            )
        if (
            context.state_scope.state_scope_id
            != expected.state_scope.state_scope_id
        ):
            violations.append(
                ExecutionContextIsolationViolation(
                    code="C10C_STATE_SCOPE_BINDING_MISMATCH",
                    message="State scope does not match deterministic binding.",
                    context_id=context.context_id,
                )
            )
        return tuple(violations)

    def execution_id_for_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    ) -> str:
        request_contract = self._execution_request_from_raw(execution_request)
        if request_contract.execution_id:
            return request_contract.execution_id
        return _stable_id(
            "mock_exec",
            {
                "factory_key": self.factory_key,
                "request": request_contract.model_dump(mode="json"),
            },
        )

    def context_id_for_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    ) -> str:
        request_contract = self._execution_request_from_raw(execution_request)
        return _stable_id(
            "exec_ctx",
            {
                "factory_key": self.factory_key,
                "execution_id": self.execution_id_for_request(request_contract),
                "request": request_contract.model_dump(mode="json"),
            },
        )

    def _execution_request_from_raw(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    ) -> ExecutionRequestContractV1:
        if isinstance(execution_request, ExecutionRequestContractV1):
            return execution_request
        return ExecutionRequestContractV1.model_validate(execution_request)


__all__ = [
    "EXECUTION_CONTEXT_STAGE",
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
]
