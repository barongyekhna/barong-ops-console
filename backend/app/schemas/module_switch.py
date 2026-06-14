from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ModuleSwitchState = Literal["ON", "OFF", "DEPRECATED", "MAINTENANCE"]
ModuleSwitchRuntimeStatus = Literal["ON", "OFF"]
ModuleSwitchEnforcementResult = Literal["ALLOWED", "BLOCKED"]
ModuleSwitchIntegrationPoint = Literal[
    "c08_module_resolution",
    "c12_approval_request",
    "c09_execution_request",
    "c10_sandbox_entry",
]


class ModuleSwitchRegistryRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: str = Field(min_length=1, max_length=128)
    state: ModuleSwitchState
    enabled: bool
    disabled_reason: str | None = Field(default=None, max_length=255)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state_model(self) -> "ModuleSwitchRegistryRecord":
        if self.enabled != (self.state == "ON"):
            raise ValueError("Module switch enabled must match state ON.")
        if not self.enabled and not self.disabled_reason:
            raise ValueError("Disabled module switches require a safe reason.")
        if self.disabled_reason:
            lowered = self.disabled_reason.lower()
            blocked_markers = (
                "authorization",
                "bearer ",
                "credential",
                "http://",
                "https://",
                "password",
                "provider_url",
                "secret",
                "token",
                "://",
                "=",
            )
            if any(marker in lowered for marker in blocked_markers):
                raise ValueError("Module switch disabled_reason is not safe.")
        return self


class ModuleSwitchRuntimeDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: str = Field(min_length=1, max_length=128)
    switch_status: ModuleSwitchRuntimeStatus
    enforcement_result: ModuleSwitchEnforcementResult
    state: str = Field(min_length=1, max_length=40)
    enabled: bool
    reason: str = Field(min_length=1, max_length=255)
    integration_point: ModuleSwitchIntegrationPoint | None = None
    evaluated_at: datetime
    execution_chain_stopped: bool
    approval_request_allowed: bool
    execution_request_allowed: bool
    sandbox_entry_allowed: bool
    external_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False

