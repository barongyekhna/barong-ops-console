from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ModuleSwitchState = Literal["ON", "OFF", "DEPRECATED", "MAINTENANCE"]
ModuleSwitchRuntimeStatus = Literal["ON", "OFF"]
ModuleSwitchEnforcementResult = Literal["ALLOWED", "BLOCKED"]
ModuleSwitchParentOffBehavior = Literal["disable_child"]
ModuleSwitchPolicyMode = Literal["inherit", "override"]
ModuleSwitchPolicySource = Literal[
    "module",
    "group_default",
    "group_switch",
    "batch_switch",
    "dependency_cascade",
    "missing",
    "invalid",
]
ModuleSwitchIntegrationPoint = Literal[
    "c08_module_resolution",
    "c12_approval_request",
    "c09_execution_request",
    "c10_sandbox_entry",
]


SAFE_DISABLED_REASON_BLOCKED_MARKERS = (
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


def validate_module_switch_disabled_reason(
    *,
    state: str,
    enabled: bool,
    disabled_reason: str | None,
) -> None:
    if enabled != (state == "ON"):
        raise ValueError("Module switch enabled must match state ON.")
    if not enabled and not disabled_reason:
        raise ValueError("Disabled module switches require a safe reason.")
    if disabled_reason:
        lowered = disabled_reason.lower()
        if any(
            marker in lowered
            for marker in SAFE_DISABLED_REASON_BLOCKED_MARKERS
        ):
            raise ValueError("Module switch disabled_reason is not safe.")


class ModuleSwitchRegistryRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: str = Field(min_length=1, max_length=128)
    state: ModuleSwitchState
    enabled: bool
    disabled_reason: str | None = Field(default=None, max_length=255)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state_model(self) -> "ModuleSwitchRegistryRecord":
        validate_module_switch_disabled_reason(
            state=self.state,
            enabled=self.enabled,
            disabled_reason=self.disabled_reason,
        )
        return self


class ModuleSwitchDependencyRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_module_key: str = Field(min_length=1, max_length=128)
    child_module_key: str = Field(min_length=1, max_length=128)
    parent_off_behavior: ModuleSwitchParentOffBehavior = "disable_child"
    recursive: Literal[True] = True
    reason: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_dependency(self) -> "ModuleSwitchDependencyRule":
        if self.parent_module_key == self.child_module_key:
            raise ValueError("Module switch dependency cannot target itself.")
        return self


class ModuleSwitchGroupPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    group_key: str = Field(min_length=1, max_length=128)
    module_keys: tuple[str, ...] = Field(min_length=1)
    default_state: ModuleSwitchState = "ON"
    disabled_reason: str | None = Field(default=None, max_length=255)
    batch_control_supported: Literal[True] = True

    @model_validator(mode="after")
    def validate_group_policy(self) -> "ModuleSwitchGroupPolicy":
        if len(set(self.module_keys)) != len(self.module_keys):
            raise ValueError("Module switch group has duplicate module keys.")
        validate_module_switch_disabled_reason(
            state=self.default_state,
            enabled=self.default_state == "ON",
            disabled_reason=self.disabled_reason,
        )
        return self


class ModuleSwitchInheritancePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: str = Field(min_length=1, max_length=128)
    group_keys: tuple[str, ...] = Field(default_factory=tuple)
    policy_mode: ModuleSwitchPolicyMode = "inherit"
    parent_off_overrides_module: Literal[True] = True

    @model_validator(mode="after")
    def validate_inheritance_policy(self) -> "ModuleSwitchInheritancePolicy":
        if len(set(self.group_keys)) != len(self.group_keys):
            raise ValueError(
                "Module switch inheritance policy has duplicate groups."
            )
        return self


class ModuleSwitchGroupSwitchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    group_key: str = Field(min_length=1, max_length=128)
    state: ModuleSwitchState
    disabled_reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_group_switch(self) -> "ModuleSwitchGroupSwitchRequest":
        validate_module_switch_disabled_reason(
            state=self.state,
            enabled=self.state == "ON",
            disabled_reason=self.disabled_reason,
        )
        return self


class ModuleSwitchBatchSwitchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_keys: tuple[str, ...] = Field(min_length=1)
    state: ModuleSwitchState
    disabled_reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_batch_switch(self) -> "ModuleSwitchBatchSwitchRequest":
        if len(set(self.module_keys)) != len(self.module_keys):
            raise ValueError("Module switch batch has duplicate module keys.")
        validate_module_switch_disabled_reason(
            state=self.state,
            enabled=self.state == "ON",
            disabled_reason=self.disabled_reason,
        )
        return self


class ModuleSwitchPolicyEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: str = Field(min_length=1, max_length=128)
    state: ModuleSwitchState
    enabled: bool
    reason: str = Field(min_length=1, max_length=255)
    policy_source: ModuleSwitchPolicySource
    group_keys: tuple[str, ...] = Field(default_factory=tuple)
    inherited_from_group: str | None = Field(default=None, max_length=128)
    cascaded_from: tuple[str, ...] = Field(default_factory=tuple)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_policy_evaluation(self) -> "ModuleSwitchPolicyEvaluation":
        validate_module_switch_disabled_reason(
            state=self.state,
            enabled=self.enabled,
            disabled_reason=None if self.enabled else self.reason,
        )
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
