from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

EventModule = Literal[
    "C13",
    "C14",
    "C15",
    "C16",
    "C18D",
    "C18F",
    "C18G",
    "C18H",
    "C18I",
    "Pxx",
    "system",
]
EventSource = Literal["frontend", "backend", "n8n", "ai", "system"]
EventStatus = Literal["success", "failed", "pending"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)
    event_type: str
    module: EventModule
    action: str
    context_id: str
    user_id: str | None = None
    product_key: str | None = None
    workflow_id: str | None = None
    source: EventSource
    status: EventStatus
    latency_ms: float = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
