from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class OperationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
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
