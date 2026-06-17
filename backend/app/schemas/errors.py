from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import FOUNDATION_ID_PATTERN, reject_sensitive_data


class SystemErrorCreate(BaseModel):
    error_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    error_code: str = Field(min_length=1, max_length=100)
    severity: Literal["info_demo", "warning_demo", "error_demo"] = (
        "error_demo"
    )
    status: Literal["open_demo", "acknowledged_demo"] = "open_demo"
    message: str = Field(min_length=1, max_length=2000)
    details: dict[str, Any] | None = None
    job_id: str | None = Field(default=None, max_length=128)
    module_key: str | None = Field(default=None, max_length=128)
    agent_key: str | None = Field(default=None, max_length=128)
    workflow_key: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)

    @field_validator("details")
    @classmethod
    def validate_details(cls, value: Any) -> Any:
        return reject_sensitive_data(value)

    @model_validator(mode="after")
    def validate_trace(self) -> "SystemErrorCreate":
        if not any(
            (
                self.job_id,
                self.module_key,
                self.agent_key,
                self.workflow_key,
                self.correlation_id,
            )
        ):
            raise ValueError(
                "An error requires a foundation source or correlation_id."
            )
        return self


class SystemErrorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: str = Field(exclude=True)
    error_id: str
    error_code: str
    severity: str
    status: str
    message: str
    details: dict[str, Any] | None
    job_id: str | None
    module_key: str | None = Field(validation_alias="module_id")
    agent_key: str | None = Field(validation_alias="agent_id")
    workflow_key: str | None = Field(validation_alias="workflow_id")
    correlation_id: str | None
    occurred_at: datetime
    acknowledged_by: int | None
    resolved_at: datetime | None
