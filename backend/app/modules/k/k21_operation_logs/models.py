"""K21-A operation log schema for K-series modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

KOperationEventType = Literal["K19", "K20", "K23", "K24"]
KOperationEntityType = Literal["keyword", "risk", "flag", "module"]
KOperationAction = Literal["create", "update", "delete", "toggle"]


class KOperationLog(BaseModel):
    """Immutable append-only operation log entry schema."""

    model_config = ConfigDict(frozen=True)

    # A1: Unique log identifier.
    log_id: str = Field(min_length=1)
    # A2: K-series module source.
    event_type: KOperationEventType
    # A3: Operation target entity type.
    entity_type: KOperationEntityType
    # A4: Operation target entity identifier.
    entity_id: str = Field(min_length=1)
    # A5: Operation action type.
    action: KOperationAction
    # A6: Snapshot before the operation.
    before_state: dict[str, Any] | None
    # A7: Snapshot after the operation.
    after_state: dict[str, Any] | None
    # A8: Operation timestamp.
    timestamp: datetime


__all__ = [
    "KOperationAction",
    "KOperationEntityType",
    "KOperationEventType",
    "KOperationLog",
]
