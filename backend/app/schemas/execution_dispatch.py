from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .execution_router import ExecutionRouterResponse
from .live_gate import ExecutionUnlockResponse
from .module_workflow_binding import ModuleWorkflowBindingDecision
from .workflow_registry import WorkflowInvocationDecision


ExecutionDispatchStatus = Literal["accepted", "rejected"]


class ExecutionDispatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_id: str = Field(min_length=1, max_length=68)
    module_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class ExecutionDispatchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pipeline: Literal["ExecutionDispatchPipeline"] = "ExecutionDispatchPipeline"
    status: ExecutionDispatchStatus
    reason: str = Field(min_length=1, max_length=700)
    c15a_workflow_match: WorkflowInvocationDecision
    c15f_whitelist_check: ModuleWorkflowBindingDecision
    unlock_response: ExecutionUnlockResponse | None = None
    router_response: ExecutionRouterResponse | None = None
    flow: tuple[str, ...] = (
        "C15A workflow match",
        "C15F whitelist check",
        "ExecutionRouter",
        "Provider execution mode plan",
    )
    workflow_registry_executes: Literal[False] = False
    webhook_direct_execution_allowed: Literal[False] = False
    live_provider_dispatched: Literal[False] = False
    production_external_call_performed: Literal[False] = False
