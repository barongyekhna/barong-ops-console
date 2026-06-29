"""Pydantic DTOs for the I-series image system API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .constants import MAX_GENERATION_COUNT, SOURCE_EDIT, SOURCE_GENERATE

SourceType = Literal["generate", "edit"]
OriginContext = Literal["i_direct", "k_handoff"]


class PromptTransformRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    style_config: dict[str, Any] = Field(default_factory=dict)
    source_type: SourceType = SOURCE_GENERATE


class PromptTransformResponse(BaseModel):
    image_prompt_enhanced: str
    provider: str
    skill_version: str


class ImageCandidate(BaseModel):
    candidate_id: str
    source_type: SourceType
    status: Literal["GENERATED"] = "GENERATED"
    image_base64: str
    mime_type: str
    width: int
    height: int
    file_size: int
    content_sha256: str
    image_prompt_enhanced: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    style_config: dict[str, Any] = Field(default_factory=dict)
    aspect_ratio: str = Field(default="1:1", min_length=3, max_length=16)
    generation_count: int = Field(default=1, ge=1, le=MAX_GENERATION_COUNT)
    product_id: UUID | None = None
    variant_id: UUID | None = None
    origin_context: OriginContext = "i_direct"

    @model_validator(mode="after")
    def normalize_context(self) -> "ImageGenerationRequest":
        if self.origin_context == "k_handoff" and self.product_id is None:
            raise ValueError("K handoff generation requires product_id.")
        self.aspect_ratio = self.aspect_ratio.strip()
        return self


class ImageGenerationResponse(BaseModel):
    event_id: UUID
    source_type: Literal["generate"] = "generate"
    image_prompt_enhanced: str
    lifecycle: list[str]
    candidates: list[ImageCandidate]
    prompt_provider: str


class ImageEditResponse(BaseModel):
    event_id: UUID
    source_type: Literal["edit"] = "edit"
    image_prompt_enhanced: str
    lifecycle: list[str]
    reference_image_count: int
    candidates: list[ImageCandidate]
    prompt_provider: str
    temp_reference_images_persisted: bool = False


class ImageSaveItem(BaseModel):
    image_base64: str = Field(min_length=1)
    mime_type: str = Field(default="image/png", max_length=100)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    content_sha256: str | None = Field(default=None, max_length=64)
    candidate_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("image_base64")
    @classmethod
    def reject_empty_base64(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("image_base64 is required.")
        return stripped


class MediaLibrarySaveRequest(BaseModel):
    source_type: SourceType
    prompt_original: str | None = Field(default=None, max_length=8000)
    image_prompt_enhanced: str = Field(min_length=1, max_length=12000)
    style_config: dict[str, Any] = Field(default_factory=dict)
    aspect_ratio: str | None = Field(default=None, max_length=16)
    product_id: UUID | None = None
    variant_id: UUID | None = None
    origin_context: OriginContext = "i_direct"
    images: list[ImageSaveItem] = Field(min_length=1, max_length=MAX_GENERATION_COUNT)

    @model_validator(mode="after")
    def disallow_k_handoff_media_library_save(self) -> "MediaLibrarySaveRequest":
        if self.origin_context == "k_handoff":
            raise ValueError("K handoff outputs must be saved through K API.")
        return self


class MediaAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    image_id: str
    product_id: UUID | None
    variant_id: UUID | None
    source_type: str
    origin_context: str
    status: str
    media_bucket: str
    prompt_original: str | None
    image_prompt_enhanced: str
    aspect_ratio: str | None
    filename: str
    object_key: str
    file_url: str
    thumbnail_url: str
    preview_url: str
    mime_type: str
    width: int | None
    height: int | None
    file_size: int
    content_sha256: str
    metadata_json: dict[str, Any] | list[Any] | None
    created_at: datetime
    updated_at: datetime


class MediaLibraryListResponse(BaseModel):
    items: list[MediaAssetRead]
    count: int
    limit: int
    offset: int


class MediaLibrarySaveResponse(BaseModel):
    items: list[MediaAssetRead]
    count: int


class DeleteMediaResponse(BaseModel):
    status: Literal["removed"] = "removed"
    image_id: str
    asset_id: UUID


class KImageSaveItem(ImageSaveItem):
    pass


class KProductImageSaveRequest(BaseModel):
    variant_id: UUID
    images: list[KImageSaveItem] = Field(min_length=1, max_length=MAX_GENERATION_COUNT)
    source_type: SourceType
    prompt_original: str | None = Field(default=None, max_length=8000)
    image_prompt_enhanced: str = Field(min_length=1, max_length=12000)
    style_config: dict[str, Any] = Field(default_factory=dict)
    aspect_ratio: str | None = Field(default=None, max_length=16)
    event_id: UUID | None = None


class KProductImageSaveResponse(BaseModel):
    status: Literal["saved"] = "saved"
    product_id: UUID
    variant_id: UUID
    variant_sku: str
    asset_ids: list[UUID]
    submitted: bool
    submit_status: str
    message: str | None = None
