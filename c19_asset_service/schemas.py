"""Strict JSON contracts for the Asset control and gateway boundaries."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$")]
AssetId = Annotated[str, Field(pattern=r"^att_[0-9a-f]{32}$")]
MomentId = Annotated[str, Field(pattern=r"^mom_[0-9a-f]{32}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Ticket = Annotated[str, Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]{43}$")]
ObjectKey = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[0-9a-f/.-]+$")]


IMAGE_MEDIA_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
FILE_MEDIA_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
}
FORBIDDEN_BIDI = {chr(codepoint) for codepoint in range(0x202A, 0x202F)} | {
    chr(codepoint) for codepoint in range(0x2066, 0x206A)
}


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(UTC)


def normalize_filename(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    if not value or len(value) > 255 or value in {".", ".."}:
        raise ValueError("invalid display filename")
    if value != value.strip() or "/" in value or "\\" in value:
        raise ValueError("invalid display filename")
    if any(
        unicodedata.category(character).startswith("C")
        or character in FORBIDDEN_BIDI
        for character in value
    ):
        raise ValueError("invalid display filename")
    return value


class UploadIntentRequest(ContractModel):
    client_asset_id: Identifier
    owner_user_id: Identifier
    conversation_id: Identifier
    kind: Literal["image", "file"]
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0, le=64 * 1024 * 1024)
    sha256_hex: Sha256Hex
    requested_at: datetime

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return normalize_filename(value)

    @field_validator("media_type")
    @classmethod
    def validate_media_type(cls, value: str) -> str:
        if value != value.lower() or ";" in value or value != value.strip():
            raise ValueError("invalid declared media type")
        return value

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return utc_datetime(value)

    @model_validator(mode="after")
    def validate_kind_extension_and_media(self) -> "UploadIntentRequest":
        dot = self.filename.rfind(".")
        extension = self.filename[dot:].lower() if dot >= 0 else ""
        allowed = IMAGE_MEDIA_BY_EXTENSION if self.kind == "image" else FILE_MEDIA_BY_EXTENSION
        if allowed.get(extension) != self.media_type:
            raise ValueError("filename, kind, and media type do not match")
        return self


class MomentUploadIntentRequest(ContractModel):
    """Moment-image intent scoped to a server-reserved private draft ID."""

    client_asset_id: Identifier
    owner_user_id: Identifier
    scope_id: MomentId
    kind: Literal["image"]
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0, le=64 * 1024 * 1024)
    sha256_hex: Sha256Hex
    requested_at: datetime

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return normalize_filename(value)

    @field_validator("media_type")
    @classmethod
    def validate_media_type(cls, value: str) -> str:
        if value != value.lower() or ";" in value or value != value.strip():
            raise ValueError("invalid declared media type")
        return value

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return utc_datetime(value)

    @model_validator(mode="after")
    def validate_image_extension_and_media(self) -> "MomentUploadIntentRequest":
        dot = self.filename.rfind(".")
        extension = self.filename[dot:].lower() if dot >= 0 else ""
        if IMAGE_MEDIA_BY_EXTENSION.get(extension) != self.media_type:
            raise ValueError("filename and image media type do not match")
        return self


class AssetSnapshot(ContractModel):
    asset_id: AssetId
    client_asset_id: Identifier
    owner_user_id: Identifier
    conversation_id: Identifier
    kind: Literal["image", "file"]
    filename: str
    media_type: str
    size_bytes: int
    sha256_hex: Sha256Hex
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


class MomentAssetSnapshot(ContractModel):
    asset_id: AssetId
    client_asset_id: Identifier
    owner_user_id: Identifier
    usage: Literal["moment_image"]
    scope_id: MomentId
    kind: Literal["image"]
    filename: str = Field(min_length=1, max_length=255)
    media_type: Literal["image/jpeg", "image/png", "image/webp", "image/gif"]
    size_bytes: int = Field(gt=0, le=64 * 1024 * 1024)
    sha256_hex: Sha256Hex
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

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return normalize_filename(value)


class UploadIntentResponse(ContractModel):
    asset: AssetSnapshot
    upload_ticket: Ticket | None
    expires_at: datetime | None


class MomentUploadIntentResponse(ContractModel):
    asset: MomentAssetSnapshot
    upload_ticket: Ticket | None
    expires_at: datetime | None


class AssetScopeRequest(ContractModel):
    owner_user_id: Identifier
    conversation_id: Identifier


class PrepareBindingRequest(AssetScopeRequest):
    client_message_id: Identifier


class CommitBindingRequest(PrepareBindingRequest):
    record_id: Identifier


class BindingResponse(ContractModel):
    asset: AssetSnapshot
    binding_status: Literal["prepared", "committed"]


class MomentAssetScopeRequest(ContractModel):
    owner_user_id: Identifier
    scope_id: MomentId


class MomentPrepareBindingRequest(MomentAssetScopeRequest):
    binding_client_id: Identifier


class MomentCommitBindingRequest(MomentPrepareBindingRequest):
    bound_resource_id: MomentId

    @model_validator(mode="after")
    def validate_bound_resource(self) -> "MomentCommitBindingRequest":
        if self.bound_resource_id != self.scope_id:
            raise ValueError("Moment binding must target its reserved scope")
        return self


class MomentBindingResponse(ContractModel):
    asset: MomentAssetSnapshot
    binding_status: Literal["prepared", "committed"]


class DownloadIntentRequest(ContractModel):
    owner_user_id: Identifier
    reader_user_id: Identifier
    conversation_id: Identifier
    record_id: Identifier
    variant: Literal["original", "thumbnail"]
    disposition: Literal["attachment", "inline"]
    asset_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_disposition(self) -> "DownloadIntentRequest":
        if self.variant == "original" and self.disposition != "attachment":
            raise ValueError("original assets must be attachments")
        if self.variant == "thumbnail" and self.disposition != "inline":
            raise ValueError("thumbnails must be inline")
        return self


class MomentDownloadIntentRequest(ContractModel):
    owner_user_id: Identifier
    reader_user_id: Identifier
    scope_id: MomentId
    bound_resource_id: MomentId
    variant: Literal["original", "thumbnail"]
    disposition: Literal["attachment", "inline"]
    asset_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_scope_and_disposition(self) -> "MomentDownloadIntentRequest":
        if self.bound_resource_id != self.scope_id:
            raise ValueError("Moment binding must target its reserved scope")
        if self.variant == "original" and self.disposition != "attachment":
            raise ValueError("original assets must be attachments")
        if self.variant == "thumbnail" and self.disposition != "inline":
            raise ValueError("thumbnails must be inline")
        return self


class DownloadIntentResponse(ContractModel):
    download_ticket: Ticket
    expires_at: datetime


class TransferInspectRequest(ContractModel):
    ticket: Ticket
    direction: Literal["upload", "download"]
    method: Literal["PUT", "GET", "HEAD"]

    @model_validator(mode="after")
    def validate_method(self) -> "TransferInspectRequest":
        if self.direction == "upload" and self.method != "PUT":
            raise ValueError("invalid upload method")
        if self.direction == "download" and self.method not in {"GET", "HEAD"}:
            raise ValueError("invalid download method")
        return self


class TransferInspectResponse(ContractModel):
    asset_id: AssetId
    owner_user_id: Identifier
    reader_user_id: Identifier | None
    conversation_id: Identifier
    record_id: Identifier | None
    variant: Literal["original", "thumbnail"] | None
    version: int = Field(ge=1)
    expires_at: datetime


class ScopedTransferInspectResponse(ContractModel):
    """V2 tagged transfer scope used for both chat and Moment assets."""

    asset_id: AssetId
    owner_user_id: Identifier
    reader_user_id: Identifier | None
    usage: Literal["chat_message", "moment_image"]
    scope_id: Identifier
    bound_resource_id: Identifier | None
    variant: Literal["original", "thumbnail"] | None
    version: int = Field(ge=1)
    expires_at: datetime

    @model_validator(mode="after")
    def validate_tagged_scope(self) -> "ScopedTransferInspectResponse":
        is_upload = self.reader_user_id is None
        if is_upload:
            if self.bound_resource_id is not None or self.variant is not None:
                raise ValueError("upload inspection contains download scope")
        elif self.bound_resource_id is None or self.variant is None:
            raise ValueError("download inspection is missing bound scope")
        if self.usage == "moment_image":
            if re.fullmatch(r"mom_[0-9a-f]{32}", self.scope_id) is None:
                raise ValueError("invalid Moment scope")
            if (
                self.bound_resource_id is not None
                and self.bound_resource_id != self.scope_id
            ):
                raise ValueError("Moment bound resource differs from scope")
        return self


class GatewayUploadAuthorizeRequest(ContractModel):
    ticket: Ticket
    method: Literal["PUT"]
    content_length: int | None = Field(default=None, ge=0, le=64 * 1024 * 1024)


class GatewayUploadAuthorizeResponse(ContractModel):
    asset_id: AssetId
    object_key: ObjectKey | None
    expected_size_bytes: int
    maximum_size_bytes: int
    upload_state: Literal["ready", "completed"]


class GatewayUploadCompleteRequest(ContractModel):
    ticket: Ticket
    size_bytes: int = Field(gt=0, le=64 * 1024 * 1024)
    sha256_hex: Sha256Hex


class GatewayDownloadAuthorizeRequest(ContractModel):
    ticket: Ticket
    method: Literal["GET", "HEAD"]


class GatewayDownloadAuthorizeResponse(ContractModel):
    asset_id: AssetId
    object_key: ObjectKey
    filename: str
    media_type: str
    size_bytes: int = Field(gt=0)
    sha256_hex: Sha256Hex
    disposition: Literal["attachment", "inline"]
    variant: Literal["original", "thumbnail"]


class LifecycleRequest(ContractModel):
    requested_by_user_id: Identifier
    reason: str = Field(min_length=1, max_length=256)
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return utc_datetime(value)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("invalid reason")
        return value


class LifecycleResponse(ContractModel):
    asset_id: AssetId
    status: Literal["quarantined", "delete_pending", "deleted"]
    version: int = Field(ge=1)


class ChatRetentionDeletionRequest(ContractModel):
    """Exact, content-free Record outbox handoff for one committed chat asset."""

    operation_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    record_id: str = Field(min_length=1, max_length=36)
    conversation_id: Identifier
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return utc_datetime(value)


class ChatRetentionDeletionResponse(ContractModel):
    asset_id: AssetId
    disposition: Literal["accepted", "protected"]
    status: Literal["delete_pending", "deleted", "retained"]


class ChatRetentionPreparationResponse(ContractModel):
    asset_id: AssetId
    disposition: Literal["accepted", "protected"]
    status: Literal["prepared", "retained"]


class HealthResponse(ContractModel):
    status: Literal["ok"]
    service: Literal["c19-asset-service"]
    dataset_id: str


class AssetOpsSnapshot(ContractModel):
    """Private aggregate telemetry with no filenames, IDs, tokens, or locators."""

    status: Literal["ok"]
    service: Literal["c19-asset-service"]
    dataset_id: str = Field(min_length=1, max_length=128)
    generated_at: datetime
    asset_states: dict[str, int]
    asset_usages: dict[str, int]
    active_object_bytes: int = Field(ge=0)
    reserved_asset_files: int = Field(ge=0)
    reserved_asset_bytes: int = Field(ge=0)
    active_transfer_tickets: int = Field(ge=0)
    expired_transfer_tickets: int = Field(ge=0)
    audit_events: int = Field(ge=0)
    retention_prepared_count: int = Field(ge=0)
    oldest_retention_prepared_age_seconds: int | None = Field(default=None, ge=0)
    oldest_pending_upload_age_seconds: int | None = Field(default=None, ge=0)
    oldest_uploaded_age_seconds: int | None = Field(default=None, ge=0)
    oldest_scanning_age_seconds: int | None = Field(default=None, ge=0)
    oldest_delete_pending_age_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_exact_dimensions(self) -> "AssetOpsSnapshot":
        if set(self.asset_states) != {
            "pending_upload",
            "uploaded",
            "scanning",
            "active",
            "rejected",
            "quarantined",
            "delete_pending",
            "deleted",
            "expired",
        }:
            raise ValueError("asset state telemetry is incomplete")
        if set(self.asset_usages) != {"chat_message", "moment_image"}:
            raise ValueError("asset usage telemetry is incomplete")
        if any(count < 0 for count in (*self.asset_states.values(), *self.asset_usages.values())):
            raise ValueError("asset telemetry is invalid")
        return self
