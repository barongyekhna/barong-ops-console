from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import FOUNDATION_ID_PATTERN, reject_sensitive_data


class ArtifactCreate(BaseModel):
    artifact_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    job_id: str = Field(min_length=1, max_length=128)
    module_key: str = Field(min_length=1, max_length=128)
    artifact_type: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    storage_provider: Literal[
        "metadata_only",
        "foundation_metadata",
        "demo_metadata",
    ] = "metadata_only"
    storage_ref: str = Field(
        default="foundation://metadata-only",
        min_length=1,
        max_length=1024,
    )
    content_hash: str | None = Field(default=None, max_length=255)
    schema_version: str = Field(
        default="0.1.0-demo",
        min_length=1,
        max_length=64,
    )
    version: str = Field(default="0.1.0-demo", min_length=1, max_length=64)
    status: Literal["registered_demo", "draft_demo"] = "registered_demo"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("storage_ref")
    @classmethod
    def validate_storage_ref(cls, value: str) -> str:
        if value.lower().startswith(
            ("http://", "https://", "s3://", "file://")
        ):
            raise ValueError(
                "Only non-network foundation/demo storage references are allowed."
            )
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: Any) -> Any:
        return reject_sensitive_data(value)


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: str = Field(exclude=True)
    artifact_id: str
    job_id: str
    module_key: str = Field(validation_alias="module_id")
    artifact_type: str
    name: str
    storage_provider: str
    storage_ref: str
    content_hash: str | None
    schema_version: str
    version: str
    status: str
    metadata: dict[str, Any] = Field(validation_alias="artifact_metadata")
    created_at: datetime
    updated_at: datetime
