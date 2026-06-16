from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ATTACHMENT_ID_PATTERN = re.compile(r"^att_[0-9a-f]{32}$")
MESSAGE_ID_PATTERN = re.compile(r"^msg_[0-9a-f]{32}$")


class AttachmentType(StrEnum):
    IMAGE = "image"
    FILE = "file"
    VIDEO = "video"
    AUDIO = "audio"


class AttachmentOperation(StrEnum):
    UPLOAD = "upload"
    FETCH_BY_MESSAGE = "fetch_by_message"


SUPPORTED_ATTACHMENT_EXTENSIONS: dict[AttachmentType, tuple[str, ...]] = {
    AttachmentType.IMAGE: ("jpg", "png", "webp", "gif"),
    AttachmentType.FILE: ("pdf", "doc", "xlsx", "zip"),
    AttachmentType.VIDEO: ("mp4", "mov"),
    AttachmentType.AUDIO: ("mp3", "wav"),
}

SUPPORTED_ATTACHMENT_MIME_TYPES: dict[AttachmentType, tuple[str, ...]] = {
    AttachmentType.IMAGE: ("image/jpeg", "image/png", "image/webp", "image/gif"),
    AttachmentType.FILE: (
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
    ),
    AttachmentType.VIDEO: ("video/mp4", "video/quicktime"),
    AttachmentType.AUDIO: ("audio/mpeg", "audio/wav", "audio/x-wav"),
}

SUPPORTED_ATTACHMENT_EXTENSION_MIME_TYPES: dict[str, tuple[str, ...]] = {
    "jpg": ("image/jpeg",),
    "png": ("image/png",),
    "webp": ("image/webp",),
    "gif": ("image/gif",),
    "pdf": ("application/pdf",),
    "doc": ("application/msword",),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "zip": ("application/zip",),
    "mp4": ("video/mp4",),
    "mov": ("video/quicktime",),
    "mp3": ("audio/mpeg",),
    "wav": ("audio/wav", "audio/x-wav"),
}


def generate_attachment_id() -> str:
    return "att_" + uuid4().hex


def _normalize_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _filename_extension(filename: str) -> str:
    if "." not in filename:
        raise ValueError("filename must include a supported extension.")
    extension = filename.rsplit(".", 1)[1].strip().lower()
    if not extension:
        raise ValueError("filename must include a supported extension.")
    return extension


class Attachment(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    attachment_id: str = Field(default_factory=generate_attachment_id)
    message_id: str = Field(min_length=1, max_length=64)
    type: AttachmentType
    url: str = Field(min_length=1, max_length=2048)
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0)
    mime_type: str = Field(min_length=1, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("attachment_id")
    @classmethod
    def validate_attachment_id(cls, value: str) -> str:
        normalized = value.strip()
        if not ATTACHMENT_ID_PATTERN.fullmatch(normalized):
            raise ValueError("attachment_id must be generated as att_ + uuid4().hex.")
        return normalized

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, value: str) -> str:
        normalized = value.strip()
        if not MESSAGE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("message_id must reference Message.message_id.")
        return normalized

    @field_validator("url", "filename", "mime_type")
    @classmethod
    def normalize_text_fields(cls, value: str, info) -> str:
        return _normalize_non_empty(value, field_name=info.field_name)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_attachment_constraints(self) -> "Attachment":
        normalized_url = self.url.lower()
        if normalized_url.startswith(("http://", "https://", "//")):
            raise ValueError("external attachment URLs are not allowed by default.")

        extension = _filename_extension(self.filename)
        allowed_extensions = SUPPORTED_ATTACHMENT_EXTENSIONS[self.type]
        if extension not in allowed_extensions:
            raise ValueError(
                f"{self.type.value} attachments support only: "
                + ", ".join(allowed_extensions)
                + "."
            )

        allowed_mime_types = SUPPORTED_ATTACHMENT_MIME_TYPES[self.type]
        normalized_mime_type = self.mime_type.lower()
        if normalized_mime_type not in allowed_mime_types:
            raise ValueError(
                f"{self.type.value} attachment mime_type must be one of: "
                + ", ".join(allowed_mime_types)
                + "."
            )

        extension_mime_types = SUPPORTED_ATTACHMENT_EXTENSION_MIME_TYPES[extension]
        if normalized_mime_type not in extension_mime_types:
            raise ValueError(
                f".{extension} attachment mime_type must be one of: "
                + ", ".join(extension_mime_types)
                + "."
            )

        return self


class AttachmentSchemaDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["c19g_attachment_schema_v1"] = "c19g_attachment_schema_v1"
    model_path: Literal["backend.app.schemas.attachment.Attachment"] = (
        "backend.app.schemas.attachment.Attachment"
    )
    fields: tuple[
        Literal["attachment_id"],
        Literal["message_id"],
        Literal["type"],
        Literal["url"],
        Literal["filename"],
        Literal["size"],
        Literal["mime_type"],
        Literal["created_at"],
    ] = (
        "attachment_id",
        "message_id",
        "type",
        "url",
        "filename",
        "size",
        "mime_type",
        "created_at",
    )
    attachment_id_pattern: Literal["att_ + uuid4().hex"] = "att_ + uuid4().hex"
    message_id_source: Literal["C19C Message.message_id"] = "C19C Message.message_id"
    url_external_access_by_default: Literal[False] = False
    org_scope_reserved_for_c18g: Literal[True] = True
    upload_logic_implemented: Literal[False] = False


class AttachmentFileTypeRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: AttachmentType
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]


class AttachmentSupportedFileTypes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rules: tuple[
        AttachmentFileTypeRule,
        AttachmentFileTypeRule,
        AttachmentFileTypeRule,
        AttachmentFileTypeRule,
    ] = (
        AttachmentFileTypeRule(
            type=AttachmentType.IMAGE,
            extensions=SUPPORTED_ATTACHMENT_EXTENSIONS[AttachmentType.IMAGE],
            mime_types=SUPPORTED_ATTACHMENT_MIME_TYPES[AttachmentType.IMAGE],
        ),
        AttachmentFileTypeRule(
            type=AttachmentType.FILE,
            extensions=SUPPORTED_ATTACHMENT_EXTENSIONS[AttachmentType.FILE],
            mime_types=SUPPORTED_ATTACHMENT_MIME_TYPES[AttachmentType.FILE],
        ),
        AttachmentFileTypeRule(
            type=AttachmentType.VIDEO,
            extensions=SUPPORTED_ATTACHMENT_EXTENSIONS[AttachmentType.VIDEO],
            mime_types=SUPPORTED_ATTACHMENT_MIME_TYPES[AttachmentType.VIDEO],
        ),
        AttachmentFileTypeRule(
            type=AttachmentType.AUDIO,
            extensions=SUPPORTED_ATTACHMENT_EXTENSIONS[AttachmentType.AUDIO],
            mime_types=SUPPORTED_ATTACHMENT_MIME_TYPES[AttachmentType.AUDIO],
        ),
    )
    strict_extension_validation: Literal[True] = True
    strict_mime_type_validation: Literal[True] = True


class MessageAttachmentExtensionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    extension_id: Literal["c19g_message_attachments_extension_v1"] = (
        "c19g_message_attachments_extension_v1"
    )
    c19c_message_field: Literal["attachments"] = "attachments"
    field_type: Literal["list[Attachment]"] = "list[Attachment]"
    can_be_empty: Literal[True] = True
    current_message_send_upload_allowed: Literal[False] = False
    c19f_controls_whether_upload_is_allowed: Literal[True] = True
    c19d_conversation_context_source: Literal["message_id -> conversation"] = (
        "message_id -> conversation"
    )
    upload_transfer_storage_logic_implemented: Literal[False] = False


class AttachmentDatabaseSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["c19g_attachments_table_v1"] = (
        "c19g_attachments_table_v1"
    )
    table_name: Literal["attachments"] = "attachments"
    primary_key: Literal["attachment_id"] = "attachment_id"
    columns: tuple[
        Literal["attachment_id"],
        Literal["message_id"],
        Literal["type"],
        Literal["url"],
        Literal["filename"],
        Literal["size"],
        Literal["mime_type"],
        Literal["created_at"],
    ] = (
        "attachment_id",
        "message_id",
        "type",
        "url",
        "filename",
        "size",
        "mime_type",
        "created_at",
    )
    required_indexes: tuple[Literal["message_id"], Literal["type"]] = (
        "message_id",
        "type",
    )
    org_scope_key_reserved: Literal["org_id"] = "org_id"
    migration_executed: Literal[False] = False


class AttachmentApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["GET", "POST"]
    path: str = Field(min_length=1, max_length=120)
    operation: AttachmentOperation
    placeholder_only: Literal[True] = True
    authenticated_internal_user_required: Literal[True] = True
    external_access_allowed: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class AttachmentApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19g_attachment_api_design_v1"] = (
        "c19g_attachment_api_design_v1"
    )
    endpoints: tuple[AttachmentApiEndpointDesign, AttachmentApiEndpointDesign] = (
        AttachmentApiEndpointDesign(
            method="POST",
            path="/attachments/upload",
            operation=AttachmentOperation.UPLOAD,
            notes="Future upload entry point; C19G defines no upload logic.",
        ),
        AttachmentApiEndpointDesign(
            method="GET",
            path="/attachments/{message_id}",
            operation=AttachmentOperation.FETCH_BY_MESSAGE,
            notes="Future message attachment lookup by C19C message_id.",
        ),
    )
    mounted_under_application_api_prefix: Literal[True] = True
    public_api_exposure_allowed: Literal[False] = False
    upload_logic_implemented: Literal[False] = False
    storage_logic_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False


class AttachmentPermissionRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c19g_attachment_permission_rules_v1"] = (
        "c19g_attachment_permission_rules_v1"
    )
    default_sendable_content: tuple[Literal["text"], Literal["emoji"]] = (
        "text",
        "emoji",
    )
    attachment_upload_requires_friend_status: Literal["accepted"] = "accepted"
    c19f_controls_attachment_allowed: Literal[True] = True
    c18g_controls_data_isolation: Literal[True] = True
    attachment_permission_is_separate_from_message_permission: Literal[True] = True
    upload_logic_implemented: Literal[False] = False


class AttachmentIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c19g_c19c_c19d_c19f_c18g_integration_v1"] = (
        "c19g_c19c_c19d_c19f_c18g_integration_v1"
    )
    c19c_message_system_source: Literal["Message.attachments"] = (
        "Message.attachments"
    )
    c19f_permission_source: Literal["friend_status accepted unlocks attachments"] = (
        "friend_status accepted unlocks attachments"
    )
    c19d_conversation_context_source: Literal["message_id resolves conversation"] = (
        "message_id resolves conversation"
    )
    c18g_data_isolation_source: Literal["org scoped storage boundary"] = (
        "org scoped storage boundary"
    )
    c18g_org_scope_key: Literal["org_id"] = "org_id"
    modifies_c19c_runtime_send_logic: Literal[False] = False
    modifies_c19f_permission_logic: Literal[False] = False
    modifies_c18g_runtime_enforcement: Literal[False] = False


class AttachmentSecurityBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boundary_id: Literal["c19g_attachment_security_boundary_v1"] = (
        "c19g_attachment_security_boundary_v1"
    )
    attachment_is_not_message_permission: Literal[True] = True
    attachment_is_not_org_permission: Literal[True] = True
    attachment_must_be_scoped_by_org_id: Literal[True] = True
    org_scope_key: Literal["org_id"] = "org_id"
    no_external_access_by_default: Literal[True] = True
    public_api_mount_allowed: Literal[False] = False
    authenticated_internal_user_required: Literal[True] = True
    c19f_friend_status_required_for_upload: Literal["accepted"] = "accepted"
    c18g_data_isolation_required_for_storage_access: Literal[True] = True
    storage_backend_implemented: Literal[False] = False


class AttachmentFutureExtensionArchitecture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    architecture_id: Literal["c19g_future_attachment_extensions_v1"] = (
        "c19g_future_attachment_extensions_v1"
    )
    image_compression_pipeline_reserved: Literal[True] = True
    video_transcoding_reserved: Literal[True] = True
    file_storage_backend_reserved: Literal[True] = True
    cdn_integration_reserved: Literal[True] = True
    virus_scanning_hook_reserved: Literal[True] = True
    image_compression_pipeline_implemented: Literal[False] = False
    video_transcoding_implemented: Literal[False] = False
    file_storage_backend_implemented: Literal[False] = False
    cdn_integration_implemented: Literal[False] = False
    virus_scanning_hook_implemented: Literal[False] = False


class AttachmentCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19G"] = "C19G"
    component: Literal["Attachment System Schema"] = "Attachment System Schema"
    completion_status: Literal["complete"] = "complete"
    attachment_schema_defined: Literal[True] = True
    supported_file_types_defined: Literal[True] = True
    message_attachment_extension_defined: Literal[True] = True
    database_schema_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    c19c_integrated: Literal[True] = True
    c19d_integrated: Literal[True] = True
    c19f_integrated: Literal[True] = True
    c18g_integrated: Literal[True] = True
    security_boundary_defined: Literal[True] = True
    upload_logic_implemented: Literal[False] = False
    storage_system_implemented: Literal[False] = False
    migration_executed: Literal[False] = False
    ui_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False


class AttachmentApiRuntimeNotice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19G"] = "C19G"
    schema_only: Literal[True] = True
    operation: AttachmentOperation
    detail: Literal[
        "C19G defines the attachment schema and placeholder API contract only."
    ] = "C19G defines the attachment schema and placeholder API contract only."
    upload_logic_implemented: Literal[False] = False
    storage_logic_implemented: Literal[False] = False
    persistence_implemented: Literal[False] = False


ATTACHMENT_SQL_SCHEMA = """
CREATE TABLE attachments (
    attachment_id TEXT PRIMARY KEY,
    message_id TEXT,
    type TEXT,
    url TEXT,
    filename TEXT,
    size INTEGER,
    mime_type TEXT,
    created_at TIMESTAMP
);

CREATE INDEX ix_attachments_message_id
    ON attachments (message_id);

CREATE INDEX ix_attachments_type
    ON attachments (type);
""".strip()


ATTACHMENT_DATA_FLOW_DIAGRAM = """
Future POST /attachments/upload
  -> authenticated internal user
  -> C19C Message.message_id exists
  -> C19D conversation context resolves message participants
  -> C19F requires friend_status accepted for attachment upload
  -> C18G applies org_id scoped storage boundary
  -> validate Attachment.type, filename extension, and mime_type
  -> reserved hooks: compression, transcoding, storage backend, CDN, virus scan
  -> Attachment metadata record
""".strip()


def get_attachment_schema_design() -> AttachmentSchemaDesign:
    return AttachmentSchemaDesign()


def get_supported_attachment_file_types() -> AttachmentSupportedFileTypes:
    return AttachmentSupportedFileTypes()


def get_message_attachment_extension_model() -> MessageAttachmentExtensionModel:
    return MessageAttachmentExtensionModel()


def get_attachment_database_schema() -> AttachmentDatabaseSchema:
    return AttachmentDatabaseSchema()


def get_attachment_api_design() -> AttachmentApiDesign:
    return AttachmentApiDesign()


def get_attachment_permission_rules() -> AttachmentPermissionRules:
    return AttachmentPermissionRules()


def get_attachment_integration_model() -> AttachmentIntegrationModel:
    return AttachmentIntegrationModel()


def get_attachment_security_boundary() -> AttachmentSecurityBoundary:
    return AttachmentSecurityBoundary()


def get_attachment_future_extension_architecture() -> (
    AttachmentFutureExtensionArchitecture
):
    return AttachmentFutureExtensionArchitecture()


def get_attachment_completion_status() -> AttachmentCompletionStatus:
    return AttachmentCompletionStatus()
