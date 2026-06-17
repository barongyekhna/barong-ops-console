from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import sanitize_runtime_address_data


class OperationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: str = Field(exclude=True)
    operation_id: str
    actor_type: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    job_id: str | None
    result: str
    error_code: str | None
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    details: dict[str, Any] | None
    created_at: datetime

    @field_validator("details")
    @classmethod
    def sanitize_details(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        sanitized = sanitize_runtime_address_data(value)
        return sanitized if isinstance(sanitized, dict) else {}
