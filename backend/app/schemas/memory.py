from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import FOUNDATION_ID_PATTERN, reject_sensitive_data


class MemoryEventCreate(BaseModel):
    memory_event_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    event_type: str = Field(min_length=1, max_length=100)
    subject_type: str = Field(min_length=1, max_length=100)
    subject_id: str = Field(min_length=1, max_length=128)
    job_id: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = Field(
        default="0.1.0-demo",
        min_length=1,
        max_length=64,
    )
    importance: Literal["low_demo", "normal_demo", "high_demo"] = "normal_demo"

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: Any) -> Any:
        return reject_sensitive_data(value)


class MemoryEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: str = Field(exclude=True)
    memory_event_id: str
    event_type: str
    subject_type: str
    subject_id: str
    job_id: str | None
    payload: dict[str, Any]
    schema_version: str
    importance: str
    created_by_type: str
    created_by_id: str
    created_at: datetime


class ContextPacketCreate(BaseModel):
    context_packet_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    source_job_id: str = Field(min_length=1, max_length=128)
    source_module_key: str = Field(min_length=1, max_length=128)
    target_module_key: str | None = Field(default=None, max_length=128)
    target_agent_key: str | None = Field(default=None, max_length=128)
    schema_version: str = Field(
        default="0.1.0-demo",
        min_length=1,
        max_length=64,
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[Any] = Field(default_factory=list)
    access_scope: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime

    @field_validator("payload", "artifact_refs", "access_scope")
    @classmethod
    def validate_structured_data(cls, value: Any) -> Any:
        return reject_sensitive_data(value)

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_target(self) -> "ContextPacketCreate":
        if self.target_module_key is None and self.target_agent_key is None:
            raise ValueError(
                "A context packet requires a target module or agent."
            )
        return self


class ContextPacketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: str = Field(exclude=True)
    context_packet_id: str
    source_job_id: str
    source_module_key: str = Field(validation_alias="source_module_id")
    target_module_key: str | None = Field(
        validation_alias="target_module_id"
    )
    target_agent_key: str | None = Field(validation_alias="target_agent_id")
    schema_version: str
    payload: dict[str, Any]
    artifact_refs: list[Any]
    access_scope: dict[str, Any]
    expires_at: datetime
    created_at: datetime


class MemorySummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: str = Field(exclude=True)
    summary_id: str = Field(validation_alias="memory_summary_id")
    subject_type: str
    subject_id: str
    summary: str
    source_event_ids: list[Any]
    schema_version: str
    version: str
    valid_from: datetime
    valid_until: datetime | None
    created_at: datetime
