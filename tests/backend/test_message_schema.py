from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from backend.app.main import app
from backend.app.schemas.message import (
    MESSAGE_DATA_FLOW_DIAGRAM,
    MESSAGE_SQL_SCHEMA,
    Conversation,
    Message,
    MessageBindingError,
    MessageContentType,
    MessageStatus,
    MessageStatusTransitionError,
    enforce_message_conversation_binding,
    enforce_message_status_transition,
    evaluate_message_conversation_binding,
    evaluate_message_status_transition,
    generate_conversation_id,
    generate_message_id,
    get_message_api_design,
    get_message_completion_status,
    get_message_content_restriction_rules,
    get_message_database_schema,
    get_message_integration_model,
    get_message_security_model,
    get_message_state_machine,
)


def test_c19c_message_schema_allows_only_text_and_emoji() -> None:
    conversation_id = generate_conversation_id()
    text_message = Message(
        message_id=generate_message_id(),
        from_user_id=" user-1 ",
        to_user_id=" user-2 ",
        conversation_id=conversation_id,
        content_type=MessageContentType.TEXT,
        content=" hello ",
    )
    emoji_message = Message(
        from_user_id="user-1",
        to_user_id="user-2",
        conversation_id=conversation_id,
        content_type=MessageContentType.EMOJI,
        content="👍",
    )

    assert text_message.from_user_id == "user-1"
    assert text_message.to_user_id == "user-2"
    assert text_message.content_type == "text"
    assert text_message.media_type == "text"
    assert text_message.attachments == []
    assert text_message.status == "sent"
    assert emoji_message.content_type == "emoji"
    assert emoji_message.media_type == "emoji"

    with pytest.raises(ValidationError):
        Message(
            from_user_id="user-1",
            to_user_id="user-2",
            conversation_id=conversation_id,
            content_type="voice",
            content="blocked",
        )

    with pytest.raises(ValidationError):
        Message(
            from_user_id="user-1",
            to_user_id="user-2",
            conversation_id=conversation_id,
            content_type="image",
            content="blocked",
        )

    with pytest.raises(ValidationError):
        Message(
            from_user_id="user-1",
            to_user_id="user-2",
            conversation_id=conversation_id,
            content_type="text",
            content="blocked",
            attachments=[{"file_id": "future-file"}],
        )

    with pytest.raises(ValidationError):
        Message(
            from_user_id="user-1",
            to_user_id="user-1",
            conversation_id=conversation_id,
            content_type="text",
            content="self-message denied",
        )


def test_c19c_conversation_binding_requires_legal_participants() -> None:
    conversation_id = generate_conversation_id()
    conversation = Conversation(
        conversation_id=conversation_id,
        participants=("user-1", "user-2"),
    )
    message = Message(
        from_user_id="user-1",
        to_user_id="user-2",
        conversation_id=conversation_id,
        content_type="text",
        content="hello",
    )

    allowed = enforce_message_conversation_binding(
        message=message,
        conversation=conversation,
    )
    assert allowed.allowed is True
    assert allowed.group_chat_logic_implemented is False

    wrong_conversation = Conversation(
        conversation_id=generate_conversation_id(),
        participants=("user-1", "user-2"),
    )
    mismatch = evaluate_message_conversation_binding(
        message=message,
        conversation=wrong_conversation,
    )
    assert mismatch.denied is True
    assert mismatch.denial_code == "c19c_conversation_id_mismatch"

    wrong_participants = Conversation(
        conversation_id=conversation_id,
        participants=("user-1", "user-3"),
    )
    participant_denied = evaluate_message_conversation_binding(
        message=message,
        conversation=wrong_participants,
    )
    assert participant_denied.denied is True
    assert participant_denied.denial_code == "c19c_message_participants_denied"

    with pytest.raises(MessageBindingError):
        enforce_message_conversation_binding(
            message=message,
            conversation=wrong_participants,
        )

    with pytest.raises(ValidationError):
        Conversation(
            conversation_id=conversation_id,
            participants=("user-1", "user-2", "user-3"),
        )


def test_c19c_message_state_machine_progresses_only_forward() -> None:
    delivered = enforce_message_status_transition(
        current_status=MessageStatus.SENT,
        target_status=MessageStatus.DELIVERED,
    )
    read = enforce_message_status_transition(
        current_status=MessageStatus.DELIVERED,
        target_status=MessageStatus.READ,
    )
    idempotent = evaluate_message_status_transition(
        current_status=MessageStatus.READ,
        target_status=MessageStatus.READ,
    )
    skipped = evaluate_message_status_transition(
        current_status=MessageStatus.SENT,
        target_status=MessageStatus.READ,
    )
    backwards = evaluate_message_status_transition(
        current_status=MessageStatus.READ,
        target_status=MessageStatus.DELIVERED,
    )

    assert delivered.allowed is True
    assert read.allowed is True
    assert idempotent.allowed is True
    assert skipped.denied is True
    assert skipped.denial_code == "c19c_invalid_message_status_transition"
    assert backwards.denied is True

    with pytest.raises(MessageStatusTransitionError):
        enforce_message_status_transition(
            current_status=MessageStatus.READ,
            target_status=MessageStatus.DELIVERED,
        )


def test_c19c_design_outputs_match_required_contract() -> None:
    restrictions = get_message_content_restriction_rules()
    state_machine = get_message_state_machine()
    database = get_message_database_schema()
    api = get_message_api_design()
    integration = get_message_integration_model()
    security = get_message_security_model()
    completion = get_message_completion_status()
    compact_sql = re.sub(r"\s+", " ", MESSAGE_SQL_SCHEMA)

    assert restrictions.allowed_content_types == ("text", "emoji")
    assert restrictions.unsupported_content_types == (
        "voice",
        "video",
        "file",
        "image",
    )
    assert restrictions.unsupported_content_type_rule == "DENY"
    assert restrictions.attachments_allowed is False

    assert state_machine.flow == ("sent", "delivered", "read")
    assert state_machine.backwards_transition_allowed is False
    assert state_machine.skip_transition_allowed is False

    assert database.table_name == "messages"
    assert database.primary_key == "message_id"
    assert database.required_indexes == (
        "conversation_id",
        "from_user_id",
        "to_user_id",
    )
    assert database.content_type_check_values == ("text", "emoji")
    assert database.status_check_values == ("sent", "delivered", "read")
    assert database.migration_executed is False
    assert "CREATE TABLE messages" in MESSAGE_SQL_SCHEMA
    assert "message_id TEXT PRIMARY KEY" in compact_sql
    assert "from_user_id TEXT" in compact_sql
    assert "to_user_id TEXT" in compact_sql
    assert "conversation_id TEXT" in compact_sql
    assert "content_type TEXT CHECK" in compact_sql
    assert "'text'" in compact_sql
    assert "'emoji'" in compact_sql
    assert "content TEXT" in compact_sql
    assert "status TEXT CHECK" in compact_sql
    assert "'sent'" in compact_sql
    assert "'delivered'" in compact_sql
    assert "'read'" in compact_sql
    assert "ix_messages_conversation_id" in compact_sql
    assert "ix_messages_from_user_id" in compact_sql
    assert "ix_messages_to_user_id" in compact_sql

    routes = {(endpoint.method, endpoint.path) for endpoint in api.endpoints}
    assert routes == {
        ("POST", "/messages/send"),
        ("GET", "/messages/{conversation_id}"),
        ("POST", "/messages/read"),
    }
    assert api.public_api_exposure_allowed is False
    assert api.websocket_implemented is False
    assert api.group_chat_implemented is False

    assert integration.c19a_contact_identity_source == "contact_identities"
    assert integration.c19b_contact_directory_source == "GlobalContactDirectory"
    assert integration.c18c_org_membership_source == "org_memberships"
    assert integration.modifies_c19a is False
    assert integration.modifies_c19b is False
    assert integration.modifies_c18_system is False

    assert security.internal_only is True
    assert security.external_api_exposure_allowed is False
    assert security.user_must_exist_in_c18c is True
    assert security.org_isolation_enforced_via_c18g_future_binding is True
    assert security.file_image_voice_video_allowed is False

    assert completion.message_schema_defined is True
    assert completion.conversation_binding_logic_defined is True
    assert completion.c19a_integrated is True
    assert completion.c19b_integrated is True
    assert completion.c18c_integrated is True
    assert completion.c18h_future_routing_reserved is True
    assert completion.migration_executed is False
    assert "C19A contact identity exists" in MESSAGE_DATA_FLOW_DIAGRAM
    assert "active C18C membership exists" in MESSAGE_DATA_FLOW_DIAGRAM


def test_c19c_message_runtime_remains_unmounted_until_record_store_exists() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/messages" in route.path
    }

    assert not any(path.startswith("/api/app/messages") for path, _ in routes)
    assert not any("/api/app/c19/messages" in path for path, _ in routes)
    assert not any(path.startswith("/api/public/messages") for path, _ in routes)
    assert not any(path.startswith("/api/control-plane/messages") for path, _ in routes)
