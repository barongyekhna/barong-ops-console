from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ModuleRuntimeStatus = Literal["active", "error", "disabled"]


class ModuleControlStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    org_id: str = Field(min_length=1, max_length=40)
    module_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    status: ModuleRuntimeStatus = "active"
    enabled: bool
    runtime_status: ModuleRuntimeStatus
    runtime_error_code: str | None = Field(default=None, max_length=128)
    runtime_error_message: str | None = Field(default=None, max_length=1000)
    last_error_at: datetime | None = None
    error: dict[str, str | datetime | None] = Field(default_factory=dict)
    updated_at: datetime

    @model_validator(mode="after")
    def sync_standard_fields(self) -> "ModuleControlStateRead":
        self.status = self.runtime_status
        self.error = {
            "code": self.runtime_error_code,
            "message": self.runtime_error_message,
            "timestamp": self.last_error_at,
        }
        return self


class ModuleControlOrgGroup(BaseModel):
    org_id: str = Field(min_length=1, max_length=40)
    org_name: str = Field(min_length=1, max_length=255)
    modules: list[ModuleControlStateRead]


class ModuleControlCenterResponse(BaseModel):
    organizations: list[ModuleControlOrgGroup]
    organization_count: int = Field(ge=0)
    module_count: int = Field(ge=0)
    auto_registered_count: int = Field(ge=0)
    cache_status: Literal["fresh", "stale", "partial"] = "fresh"
    generated_at: datetime | None = None


class ModuleControlUpdateRequest(BaseModel):
    enabled: bool
    runtime_error_code: str | None = Field(default=None, max_length=128)
    runtime_error_message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def normalize_error_fields(self) -> "ModuleControlUpdateRequest":
        if self.enabled:
            self.runtime_error_code = None
            self.runtime_error_message = None
            return self
        if self.runtime_error_code is not None:
            self.runtime_error_code = self.runtime_error_code.strip() or None
        if self.runtime_error_message is not None:
            self.runtime_error_message = self.runtime_error_message.strip() or None
        return self


class ModuleControlUpdateResponse(BaseModel):
    item: ModuleControlStateRead
