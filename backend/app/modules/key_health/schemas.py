"""API response schemas for the key health console."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KeyBindingRead(BaseModel):
    module_id: str
    key_alias: str


class KeyHealthItemRead(BaseModel):
    key_id: str
    key_name: str
    key_hash_prefix: str
    key_type: str
    adapter: str | None = None
    status: str
    reason_code: str
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    consecutive_failures: int
    details: dict[str, Any] = Field(default_factory=dict)
    bindings: list[KeyBindingRead] = Field(default_factory=list)


class KeyHealthCountsRead(BaseModel):
    total: int
    healthy: int
    warning: int
    failed: int
    never_checked: int


class KeyHealthRunRead(BaseModel):
    id: int
    scheduled_for: datetime
    trigger: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    total_count: int
    healthy_count: int
    warning_count: int
    failed_count: int
    error_code: str | None = None


class KeyHealthSummaryRead(BaseModel):
    generated_at: datetime
    interval_minutes: int
    latest_run: KeyHealthRunRead | None = None
    counts: KeyHealthCountsRead
    items: list[KeyHealthItemRead]


class KeyHealthRunsRead(BaseModel):
    items: list[KeyHealthRunRead]
    count: int


class KeyHealthRunTriggerRead(BaseModel):
    run_id: int
    created: bool
    status: str
    total_count: int
    healthy_count: int
    warning_count: int
    failed_count: int
