from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ExecutionFlowGateStage = Literal["c13e_execution_flow_gate"]
ExecutionFlowGateIntegrationPoint = Literal[
    "c13e_execution_flow_gate",
    "c09_execution_request",
    "c10_sandbox_entry",
]
ExecutionFlowGateResult = Literal["ALLOWED", "BLOCKED"]

FINAL_EXECUTION_FLOW: tuple[str, ...] = (
    "C08 Module Adapter",
    "C13E Execution Flow Gate",
    "C12 Approval Gate",
    "C09 Execution Provider",
    "C10 Sandbox",
)


class ExecutionFlowGateDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: ExecutionFlowGateStage = "c13e_execution_flow_gate"
    integration_point: ExecutionFlowGateIntegrationPoint = (
        "c13e_execution_flow_gate"
    )
    enforcement_result: ExecutionFlowGateResult
    reason: str = Field(min_length=1, max_length=255)
    evaluated_at: datetime
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    provider_key: str = Field(min_length=1, max_length=180)
    flow: tuple[str, ...] = FINAL_EXECUTION_FLOW
    kill_switch_checked: Literal[True] = True
    kill_switch_blocked: bool = False
    c08_checked: Literal[True] = True
    c12_checked: Literal[True] = True
    c09_checked: Literal[True] = True
    c10_checked: Literal[True] = True
    c13a_design_checked: Literal[True] = True
    c13b_runtime_gate_checked: Literal[True] = True
    c13c_policy_layer_checked: Literal[True] = True
    c13d_kill_switch_checked: Literal[True] = True
    c13e_final_gate_checked: Literal[True] = True
    c08_allowed: bool
    c12_allowed: bool
    c09_allowed: bool
    c10_allowed: bool
    c13_allowed: bool
    execution_chain_stopped: bool
    approval_request_allowed: bool
    execution_request_allowed: bool
    sandbox_entry_allowed: bool
    c09_execution_bypass_blocked: Literal[True] = True
    c10_sandbox_bypass_blocked: Literal[True] = True
    c12_approval_bypass_blocked: Literal[True] = True
    c13_bypass_blocked: Literal[True] = True
    no_execution_leak: Literal[True] = True
    no_external_provider_call: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_production_impact: Literal[True] = True
    external_provider_call_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_gate_decision(self) -> "ExecutionFlowGateDecision":
        blocked = self.enforcement_result == "BLOCKED"
        if blocked and not self.execution_chain_stopped:
            raise ValueError("Blocked C13E decisions must stop the chain.")
        if not blocked and self.execution_chain_stopped:
            raise ValueError("Allowed C13E decisions cannot stop the chain.")
        if self.kill_switch_blocked:
            if self.enforcement_result != "BLOCKED":
                raise ValueError("Kill switch must block C13E.")
            if any(
                (
                    self.c08_allowed,
                    self.c12_allowed,
                    self.c09_allowed,
                    self.c10_allowed,
                )
            ):
                raise ValueError("Kill switch must block all execution stages.")
        return self
