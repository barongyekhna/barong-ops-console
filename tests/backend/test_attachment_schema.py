from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from backend.app.main import app
from backend.app.schemas.attachment import (
    ATTACHMENT_DATA_FLOW_DIAGRAM,
    ATTACHMENT_SQL_SCHEMA,
    Attachment,
    get_attachment_api_design,
    get_attachment_completion_status,
    get_attachment_database_schema,
    get_attachment_future_extension_architecture,
    get_attachment_integration_model,
    get_attachment_permission_rules,
    get_attachment_schema_design,
    get_attachment_security_boundary,
    get_message_attachment_extension_model,
    get_supported_attachment_file_types,
)
from backend.app.schemas.message import (
    Message,
    MessageContentType,
    MessageSendRequest,
    generate_conversation_id,
    generate_message_id,
)


XLSX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _attachment(
    *,
    message_id: str,
    type: str = "image",
    filename: str = "receipt.jpg",
    mime_type: str = "image/jpeg",
) -> Attachment:
    return Attachment(
        message_id=message_id,
        type=type,
        url=f"/internal/attachments/{message_id}/{filename}",
        filename=filename,
        size=128,
        mime_type=mime_type,
    )


def test_c19g_attachment_schema_enforces_supported_file_types() -> None:
    message_id = generate_message_id()

    valid = (
        _attachment(
            message_id=message_id,
            type="image",
            filename="a.jpg",
            mime_type="image/jpeg",
        ),
        _attachment(
            message_id=message_id,
            type="image",
            filename="a.png",
            mime_type="image/png",
        ),
        _attachment(
            message_id=message_id,
            type="image",
            filename="a.webp",
            mime_type="image/webp",
        ),
        _attachment(
            message_id=message_id,
            type="image",
            filename="a.gif",
            mime_type="image/gif",
        ),
        _attachment(
            message_id=message_id,
            type="file",
            filename="a.pdf",
            mime_type="application/pdf",
        ),
        _attachment(
            message_id=message_id,
            type="file",
            filename="a.doc",
            mime_type="application/msword",
        ),
        _attachment(
            message_id=message_id,
            type="file",
            filename="a.xlsx",
            mime_type=XLSX_MIME_TYPE,
        ),
        _attachment(
            message_id=message_id,
            type="file",
            filename="a.zip",
            mime_type="application/zip",
        ),
        _attachment(
            message_id=message_id,
            type="video",
            filename="a.mp4",
            mime_type="video/mp4",
        ),
        _attachment(
            message_id=message_id,
            type="video",
            filename="a.mov",
            mime_type="video/quicktime",
        ),
        _attachment(
            message_id=message_id,
            type="audio",
            filename="a.mp3",
            mime_type="audio/mpeg",
        ),
        _attachment(
            message_id=message_id,
            type="audio",
            filename="a.wav",
            mime_type="audio/wav",
        ),
    )

    assert [attachment.type for attachment in valid] == [
        "image",
        "image",
        "image",
        "image",
        "file",
        "file",
        "file",
        "file",
        "video",
        "video",
        "audio",
        "audio",
    ]

    with pytest.raises(ValidationError):
        _attachment(
            message_id=message_id,
            type="image",
            filename="a.bmp",
            mime_type="image/bmp",
        )

    with pytest.raises(ValidationError):
        _attachment(
            message_id=message_id,
            type="file",
            filename="a.docx",
            mime_type=DOCX_MIME_TYPE,
        )

    with pytest.raises(ValidationError):
        _attachment(
            message_id=message_id,
            type="video",
            filename="a.avi",
            mime_type="video/x-msvideo",
        )

    with pytest.raises(ValidationError):
        _attachment(
            message_id=message_id,
            type="audio",
            filename="a.ogg",
            mime_type="audio/ogg",
        )

    with pytest.raises(ValidationError):
        _attachment(
            message_id=message_id,
            type="image",
            filename="a.jpg",
            mime_type="application/pdf",
        )

    with pytest.raises(ValidationError):
        _attachment(
            message_id=message_id,
            type="image",
            filename="a.jpg",
            mime_type="image/png",
        )

    with pytest.raises(ValidationError):
        _attachment(
            message_id=message_id,
            type="file",
            filename="a.pdf",
            mime_type="application/zip",
        )

    with pytest.raises(ValidationError):
        Attachment(
            message_id=message_id,
            type="image",
            url="https://cdn.example.test/a.jpg",
            filename="a.jpg",
            size=128,
            mime_type="image/jpeg",
        )


def test_c19g_message_attachment_extension_is_reserved_without_upload_logic() -> None:
    message_id = generate_message_id()
    conversation_id = generate_conversation_id()
    attachment = _attachment(message_id=message_id)

    message = Message(
        message_id=message_id,
        from_user_id="user-1",
        to_user_id="user-2",
        conversation_id=conversation_id,
        content_type=MessageContentType.TEXT,
        content="hello",
        attachments=[attachment],
    )

    assert message.attachments == [attachment]
    assert message.attachments[0].message_id == message.message_id

    with pytest.raises(ValidationError):
        MessageSendRequest(
            from_user_id="user-1",
            to_user_id="user-2",
            conversation_id=conversation_id,
            content_type=MessageContentType.TEXT,
            content="hello",
            attachments=[attachment],
        )


def test_c19g_design_outputs_match_attachment_contract() -> None:
    schema = get_attachment_schema_design()
    file_types = get_supported_attachment_file_types()
    extension = get_message_attachment_extension_model()
    database = get_attachment_database_schema()
    api = get_attachment_api_design()
    permissions = get_attachment_permission_rules()
    integration = get_attachment_integration_model()
    security = get_attachment_security_boundary()
    future = get_attachment_future_extension_architecture()
    completion = get_attachment_completion_status()
    compact_sql = re.sub(r"\s+", " ", ATTACHMENT_SQL_SCHEMA)

    assert schema.model_path == "backend.app.schemas.attachment.Attachment"
    assert schema.fields == (
        "attachment_id",
        "message_id",
        "type",
        "url",
        "filename",
        "size",
        "mime_type",
        "created_at",
    )
    assert schema.upload_logic_implemented is False

    rules_by_type = {rule.type: rule for rule in file_types.rules}
    assert rules_by_type["image"].extensions == ("jpg", "png", "webp", "gif")
    assert rules_by_type["file"].extensions == ("pdf", "doc", "xlsx", "zip")
    assert rules_by_type["video"].extensions == ("mp4", "mov")
    assert rules_by_type["audio"].extensions == ("mp3", "wav")
    assert file_types.strict_extension_validation is True
    assert file_types.strict_mime_type_validation is True

    assert extension.field_type == "list[Attachment]"
    assert extension.can_be_empty is True
    assert extension.current_message_send_upload_allowed is False
    assert extension.c19f_controls_whether_upload_is_allowed is True

    assert database.table_name == "attachments"
    assert database.primary_key == "attachment_id"
    assert database.required_indexes == ("message_id", "type")
    assert database.org_scope_key_reserved == "org_id"
    assert database.migration_executed is False
    assert "CREATE TABLE attachments" in ATTACHMENT_SQL_SCHEMA
    assert "attachment_id TEXT PRIMARY KEY" in compact_sql
    assert "message_id TEXT" in compact_sql
    assert "type TEXT" in compact_sql
    assert "url TEXT" in compact_sql
    assert "filename TEXT" in compact_sql
    assert "size INTEGER" in compact_sql
    assert "mime_type TEXT" in compact_sql
    assert "created_at TIMESTAMP" in compact_sql
    assert "ix_attachments_message_id" in compact_sql
    assert "ix_attachments_type" in compact_sql

    routes = {(endpoint.method, endpoint.path) for endpoint in api.endpoints}
    assert routes == {
        ("POST", "/attachments/upload"),
        ("GET", "/attachments/{message_id}"),
    }
    assert api.upload_logic_implemented is False
    assert api.storage_logic_implemented is False
    assert api.public_api_exposure_allowed is False

    assert permissions.default_sendable_content == ("text", "emoji")
    assert permissions.attachment_upload_requires_friend_status == "accepted"
    assert permissions.c19f_controls_attachment_allowed is True
    assert permissions.c18g_controls_data_isolation is True

    assert integration.c19c_message_system_source == "Message.attachments"
    assert integration.c19f_permission_source == (
        "friend_status accepted unlocks attachments"
    )
    assert integration.c19d_conversation_context_source == (
        "message_id resolves conversation"
    )
    assert integration.c18g_org_scope_key == "org_id"
    assert integration.modifies_c19f_permission_logic is False

    assert security.attachment_is_not_message_permission is True
    assert security.attachment_is_not_org_permission is True
    assert security.attachment_must_be_scoped_by_org_id is True
    assert security.no_external_access_by_default is True
    assert security.public_api_mount_allowed is False

    assert future.image_compression_pipeline_reserved is True
    assert future.video_transcoding_reserved is True
    assert future.file_storage_backend_reserved is True
    assert future.cdn_integration_reserved is True
    assert future.virus_scanning_hook_reserved is True
    assert future.image_compression_pipeline_implemented is False
    assert future.video_transcoding_implemented is False
    assert future.file_storage_backend_implemented is False
    assert future.cdn_integration_implemented is False
    assert future.virus_scanning_hook_implemented is False

    assert completion.stage == "C19G"
    assert completion.attachment_schema_defined is True
    assert completion.message_attachment_extension_defined is True
    assert completion.upload_logic_implemented is False
    assert completion.storage_system_implemented is False
    assert completion.migration_executed is False
    assert "C19F requires friend_status accepted" in ATTACHMENT_DATA_FLOW_DIAGRAM
    assert "C18G applies org_id scoped storage boundary" in ATTACHMENT_DATA_FLOW_DIAGRAM


def test_c19g_attachment_routes_are_registered_as_internal_app_routes() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/attachments" in route.path
    }

    assert ("/api/app/attachments/upload", ("POST",)) in routes
    assert ("/api/app/attachments/{message_id}", ("GET",)) in routes
    assert not any(path.startswith("/api/public/attachments") for path, _ in routes)
    assert not any(
        path.startswith("/api/control-plane/attachments") for path, _ in routes
    )
