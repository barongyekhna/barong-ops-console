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
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_HARD_BYTES = 256 * 1024 * 1024

# Mirrors c19_asset_service/schemas.py; the asset service is authoritative and
# re-validates every declaration, this copy only gives users an early answer.
_IMAGE_MEDIA_BY_EXTENSION: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
_FILE_MEDIA_BY_EXTENSION: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".rtf": "application/rtf",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".md": "text/markdown",
    ".json": "application/json",
    ".xml": "application/xml",
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".3gp": "video/3gpp",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".amr": "audio/amr",
    ".wma": "audio/x-ms-wma",
    ".rar": "application/vnd.rar",
    ".7z": "application/x-7z-compressed",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".tgz": "application/gzip",
    ".bz2": "application/x-bzip2",
    ".xz": "application/x-xz",
    ".psd": "image/vnd.adobe.photoshop",
    ".ai": "application/postscript",
    ".svg": "image/svg+xml",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".dwg": "image/vnd.dwg",
    ".dxf": "image/vnd.dxf",
    ".step": "model/step",
    ".stp": "model/step",
    ".igs": "model/iges",
    ".iges": "model/iges",
    ".stl": "model/stl",
    ".obj": "model/obj",
}
OCTET_STREAM_MEDIA_TYPE = "application/octet-stream"
BLOCKED_EXTENSIONS = frozenset(
    {
        ".exe", ".dll", ".scr", ".com", ".bat", ".cmd", ".msi", ".msp",
        ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
        ".hta", ".lnk", ".jar", ".cpl", ".reg", ".sys", ".pif",
        ".app", ".dmg", ".apk", ".ipa", ".deb", ".rpm",
    }
)


def expected_media_type(kind: str, filename: str) -> str | None:
    """The single media type ``filename`` may declare for ``kind``; None if refused."""

    dot = filename.rfind(".")
    extension = filename[dot:].casefold() if dot >= 0 else ""
    if extension in BLOCKED_EXTENSIONS:
        return None
    if kind == "image":
        return _IMAGE_MEDIA_BY_EXTENSION.get(extension)
    if kind != "file" or extension in _IMAGE_MEDIA_BY_EXTENSION:
        return None
    return _FILE_MEDIA_BY_EXTENSION.get(extension, OCTET_STREAM_MEDIA_TYPE)


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
        expected = expected_media_type(self.kind, self.filename)
        if expected is None:
            raise ValueError("Asset filename type is not allowed in chat.")
        if expected != self.media_type:
            raise ValueError("Asset filename extension does not match its media type.")
        maximum = MAX_IMAGE_BYTES if self.kind == "image" else MAX_FILE_BYTES
        if self.size_bytes > maximum:
            raise ValueError("Asset exceeds the allowed size.")
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
