"""Public metadata-only schemas for C19 image and file assets."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from pathlib import PurePath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ASSET_ID_PATTERN = r"^att_[0-9a-f]{32}$"
CLIENT_ASSET_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_HARD_BYTES = 64 * 1024 * 1024

_MEDIA_EXTENSIONS: dict[str, frozenset[str]] = {
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/png": frozenset({".png"}),
    "image/webp": frozenset({".webp"}),
    "image/gif": frozenset({".gif"}),
    "application/pdf": frozenset({".pdf"}),
    "text/plain": frozenset({".txt"}),
    "text/csv": frozenset({".csv"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset(
        {".docx"}
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset(
        {".xlsx"}
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": frozenset(
        {".pptx"}
    ),
    "application/zip": frozenset({".zip"}),
}
_IMAGE_MEDIA_TYPES = frozenset(key for key in _MEDIA_EXTENSIONS if key.startswith("image/"))
_BIDI_CONTROLS = frozenset(
    chr(value)
    for value in (
        0x061C,
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
    )
)


class ChatAssetUploadIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_asset_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=CLIENT_ASSET_ID_PATTERN,
    )
    kind: Literal["image", "file"]
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=1, le=MAX_HARD_BYTES)
    sha256_hex: str = Field(pattern=SHA256_PATTERN)

    @field_validator("filename")
    @classmethod
    def normalize_safe_display_filename(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        if (
            normalized != normalized.strip()
            or normalized in {".", ".."}
            or "/" in normalized
            or "\\" in normalized
            or PurePath(normalized).name != normalized
            or any(
                unicodedata.category(character).startswith("C")
                or character in _BIDI_CONTROLS
                for character in normalized
            )
        ):
            raise ValueError("Asset filename is invalid.")
        return normalized

    @model_validator(mode="after")
    def enforce_supported_type_size_and_extension(self) -> Self:
        extensions = _MEDIA_EXTENSIONS.get(self.media_type)
        if extensions is None:
            raise ValueError("Asset media type is unsupported.")
        is_image = self.media_type in _IMAGE_MEDIA_TYPES
        if (self.kind == "image") != is_image:
            raise ValueError("Asset kind and media type do not match.")
        maximum = MAX_IMAGE_BYTES if is_image else MAX_FILE_BYTES
        if self.size_bytes > maximum:
            raise ValueError("Asset exceeds the allowed size.")
        lower_name = self.filename.casefold()
        if not any(lower_name.endswith(extension) for extension in extensions):
            raise ValueError("Asset filename extension does not match its media type.")
        return self


class ChatAssetRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    client_asset_id: str
    kind: Literal["image", "file"]
    filename: str
    media_type: str
    size_bytes: int = Field(ge=1, le=MAX_HARD_BYTES)
    sha256_hex: str = Field(pattern=SHA256_PATTERN)
    version: int = Field(ge=1)
    status: Literal[
        "pending_upload",
        "uploaded",
        "scanning",
        "active",
        "rejected",
        "quarantined",
        "delete_pending",
        "deleted",
        "expired",
    ]


class ChatAssetUploadIntentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: ChatAssetRead
    upload_locator: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^/api/backend/c19-assets/u/[A-Za-z0-9_-]{43}$",
    )
    expires_at: datetime | None

    @model_validator(mode="after")
    def require_locator_expiry_pair(self) -> Self:
        if (self.upload_locator is None) != (self.expires_at is None):
            raise ValueError("Upload locator and expiry must be returned together.")
        return self


class ChatAssetAccessIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant: Literal["original", "thumbnail"] = "original"


class ChatAssetAccessIntentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    download_locator: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^/api/backend/c19-assets/d/[A-Za-z0-9_-]{43}$",
    )
    expires_at: datetime


class ChatAssetReferenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    client_asset_id: str
    kind: Literal["image", "file"]
    filename: str
    media_type: str
    size_bytes: int = Field(ge=1, le=MAX_HARD_BYTES)
    sha256_hex: str = Field(pattern=SHA256_PATTERN)
    version: int = Field(ge=1)
    ordinal: int = Field(ge=0)


__all__ = [
    "ASSET_ID_PATTERN",
    "ChatAssetAccessIntentRead",
    "ChatAssetAccessIntentRequest",
    "ChatAssetRead",
    "ChatAssetReferenceRead",
    "ChatAssetUploadIntentRead",
    "ChatAssetUploadIntentRequest",
]
