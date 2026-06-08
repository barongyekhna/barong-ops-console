from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import FOUNDATION_ID_PATTERN, reject_sensitive_data

JobCreateStatus = Literal["pending", "draft"]
JobSafeStatus = Literal[
    "pending",
    "running",
    "waiting_review",
    "failed",
    "cancelled",
    "completed_demo",
]


class JobCreate(BaseModel):
    job_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    module_key: str = Field(min_length=1, max_length=128)
    agent_key: str | None = Field(default=None, max_length=128)
    workflow_key: str | None = Field(default=None, max_length=128)
    parent_job_id: str | None = Field(default=None, max_length=128)
    status: JobCreateStatus = "pending"
    risk_level: str = Field(default="low", min_length=1, max_length=50)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    input_schema_version: str = Field(
        default="0.1.0-demo",
        min_length=1,
        max_length=64,
    )
    idempotency_key: str | None = Field(default=None, max_length=255)
    correlation_id: str | None = Field(default=None, max_length=128)

    @field_validator("input_payload")
    @classmethod
    def validate_input_payload(cls, value: Any) -> Any:
        return reject_sensitive_data(value)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    module_key: str = Field(validation_alias="module_id")
    agent_key: str | None = Field(validation_alias="agent_id")
    workflow_key: str | None = Field(validation_alias="workflow_id")
    parent_job_id: str | None
    requested_by_user_id: int | None
    status: str
    risk_level: str
    input_payload: dict[str, Any]
    input_schema_version: str
    idempotency_key: str | None
    correlation_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    to_status: JobSafeStatus | None = None
    details: dict[str, Any] | None = None

    @field_validator("details")
    @classmethod
    def validate_details(cls, value: Any) -> Any:
        return reject_sensitive_data(value)

    @model_validator(mode="after")
    def validate_status_change(self) -> "JobEventCreate":
        if self.event_type == "status_change" and self.to_status is None:
            raise ValueError("status_change events require to_status.")
        if self.event_type != "status_change" and self.to_status is not None:
            raise ValueError("to_status is only allowed for status_change events.")
        return self


class JobEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_type: str
    actor_id: str
    details: dict[str, Any] | None
    created_at: datetime
