from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import FOUNDATION_ID_PATTERN, reject_sensitive_data

RegistryStatus = Literal[
    "foundation",
    "demo",
    "draft_demo",
    "inactive_demo",
]


class RegistryCreateBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    responsibilities: list[Any] = Field(default_factory=list)
    non_responsibilities: list[Any] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[Any] = Field(default_factory=list)
    risk_level: str = Field(default="low", min_length=1, max_length=50)
    version: str = Field(default="0.1.0-demo", min_length=1, max_length=64)
    status: RegistryStatus = "foundation"
    dependencies: list[Any] = Field(default_factory=list)
    artifact_types: list[Any] = Field(default_factory=list)
    review_types: list[Any] = Field(default_factory=list)
    error_codes: list[Any] = Field(default_factory=list)
    healthcheck_config: dict[str, Any] = Field(default_factory=dict)
    rollback_policy: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "responsibilities",
        "non_responsibilities",
        "input_schema",
        "output_schema",
        "permissions",
        "dependencies",
        "artifact_types",
        "review_types",
        "error_codes",
        "healthcheck_config",
        "rollback_policy",
    )
    @classmethod
    def validate_structured_data(cls, value: Any) -> Any:
        return reject_sensitive_data(value)


class RegistryResponseBase(RegistryCreateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ModuleCreate(RegistryCreateBase):
    module_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    organization_id: str | None = Field(default=None, max_length=40)


class ModuleResponse(RegistryResponseBase):
    module_key: str = Field(validation_alias="module_id")
    display_name: str = Field(validation_alias="name")
    organization_id: str | None = None


class AgentCreate(RegistryCreateBase):
    agent_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    allowed_module_keys: list[str] = Field(default_factory=list)
    allowed_workflow_keys: list[str] = Field(default_factory=list)


class AgentResponse(RegistryResponseBase):
    agent_key: str = Field(validation_alias="agent_id")
    allowed_module_keys: list[str] = Field(
        validation_alias="allowed_module_ids"
    )
    allowed_workflow_keys: list[str] = Field(
        validation_alias="allowed_workflow_ids"
    )


class WorkflowCreate(RegistryCreateBase):
    workflow_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    engine: str = Field(default="metadata_only", min_length=1, max_length=50)
    endpoint_ref: str = Field(
        default="foundation://metadata-only",
        min_length=1,
        max_length=255,
    )
    callback_contract: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    retry_policy: dict[str, Any] = Field(default_factory=dict)

    @field_validator("endpoint_ref")
    @classmethod
    def validate_endpoint_ref(cls, value: str) -> str:
        normalized = value.lower()
        if (
            not normalized.startswith(("foundation://", "demo://"))
            or any(marker in value for marker in ("@", "?", "#"))
            or any(
                marker in normalized
                for marker in ("credential", "password", "secret", "token")
            )
        ):
            raise ValueError(
                "Only non-network foundation/demo endpoint references are allowed."
            )
        return value

    @field_validator("callback_contract", "retry_policy")
    @classmethod
    def validate_workflow_data(cls, value: Any) -> Any:
        return reject_sensitive_data(value)


class WorkflowResponse(RegistryResponseBase):
    workflow_key: str = Field(validation_alias="workflow_id")
    engine: str
    endpoint_ref: str
    callback_contract: dict[str, Any]
    timeout_seconds: int
    retry_policy: dict[str, Any]
