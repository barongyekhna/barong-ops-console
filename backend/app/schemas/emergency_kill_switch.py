from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EmergencyKillSwitchIntegrationPoint = Literal[
    "c08_module_resolution",
    "c09_execution_request",
    "c10_sandbox_entry",
    "c12_approval_request",
    "c13b_runtime_gate",
    "c13c_policy_engine",
]
EmergencyKillSwitchResult = Literal["ALLOWED", "BLOCKED"]


class EmergencyKillSwitchState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    global_kill_switch: bool
    updated_at: datetime
    updated_by_user_id: int | None = Field(default=None, gt=0)
    updated_by_role: str | None = Field(default=None, max_length=80)


class EmergencyKillSwitchDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    global_kill_switch: bool
    enforcement_result: EmergencyKillSwitchResult
    reason: str = Field(min_length=1, max_length=160)
    integration_point: EmergencyKillSwitchIntegrationPoint | None = None
    evaluated_at: datetime
    execution_chain_stopped: bool
    c08_blocked: bool
    c09_blocked: bool
    c10_blocked: bool
    c12_blocked: bool
    c13b_blocked: bool
    c13c_blocked: bool
    module_switches_ignored: bool

    @model_validator(mode="after")
    def validate_decision(self) -> "EmergencyKillSwitchDecision":
        if self.global_kill_switch:
            if self.enforcement_result != "BLOCKED":
                raise ValueError("Enabled kill switch must block.")
            if not all(
                (
                    self.execution_chain_stopped,
                    self.c08_blocked,
                    self.c09_blocked,
                    self.c10_blocked,
                    self.c12_blocked,
                    self.c13b_blocked,
                    self.c13c_blocked,
                    self.module_switches_ignored,
                )
            ):
                raise ValueError("Enabled kill switch must block all paths.")
        elif self.enforcement_result != "ALLOWED":
            raise ValueError("Disabled kill switch must allow normal gates.")
        return self

