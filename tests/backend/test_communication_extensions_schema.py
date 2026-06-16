from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.main import app
from backend.app.schemas.communication_extensions import (
    COMMUNICATION_EXTENSIONS_BOUNDARY_SUMMARY,
    CommunicationExtensions,
    GroupChat,
    Moment,
    VideoCall,
    VoiceCall,
    get_communication_extension_api_placeholders,
    get_communication_extension_completion_status,
    get_communication_extension_expansion_roadmap,
    get_communication_extension_integration_strategy,
    get_communication_extension_schema_design,
    get_communication_extension_security_boundary,
)


def _created_at() -> datetime:
    return datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_c19h_future_communication_schemas_match_required_shapes() -> None:
    voice_call = VoiceCall(
        call_id="call-voice-1",
        from_user_id="user-1",
        to_user_id="user-2",
        status="initiated",
        duration=0,
        created_at=_created_at(),
    )
    video_call = VideoCall(
        call_id="call-video-1",
        participants=["user-1", "user-2"],
        status="active",
        resolution="1080p",
        created_at=_created_at(),
    )
    group_chat = GroupChat(
        group_id="group-1",
        name="Operations",
        owner_id="user-1",
        members=["user-1", "user-2", "user-3"],
        created_at=_created_at(),
    )
    moment = Moment(
        moment_id="moment-1",
        user_id="user-1",
        content="Shift handoff posted.",
        attachments=[],
        visibility="org",
        created_at=_created_at(),
    )
    extensions = CommunicationExtensions(
        voice_call=voice_call,
        video_call=video_call,
        group_chat=group_chat,
        moments=moment,
    )
    dumped = extensions.model_dump(mode="json")

    assert dumped["voice_call"] == {
        "call_id": "call-voice-1",
        "from_user_id": "user-1",
        "to_user_id": "user-2",
        "status": "initiated",
        "duration": 0,
        "created_at": "2026-01-01T00:00:00Z",
    }
    assert dumped["video_call"]["participants"] == ["user-1", "user-2"]
    assert dumped["video_call"]["status"] == "active"
    assert dumped["video_call"]["resolution"] == "1080p"
    assert dumped["group_chat"]["members"] == ["user-1", "user-2", "user-3"]
    assert dumped["moments"]["attachments"] == []
    assert dumped["moments"]["visibility"] == "org"


def test_c19h_future_communication_schema_rejects_unsupported_values() -> None:
    with pytest.raises(ValidationError):
        VoiceCall(
            call_id="call-voice-1",
            from_user_id="user-1",
            to_user_id="user-2",
            status="active",
            duration=0,
            created_at=_created_at(),
        )

    with pytest.raises(ValidationError):
        VoiceCall(
            call_id="call-voice-1",
            from_user_id="user-1",
            to_user_id="user-2",
            status="ended",
            duration=-1,
            created_at=_created_at(),
        )

    with pytest.raises(ValidationError):
        VideoCall(
            call_id="call-video-1",
            participants=["user-1", "user-2"],
            status="ringing",
            resolution="1080p",
            created_at=_created_at(),
        )

    with pytest.raises(ValidationError):
        VideoCall(
            call_id="call-video-1",
            participants=["user-1", "user-2"],
            status="initiated",
            resolution="4k",
            created_at=_created_at(),
        )

    with pytest.raises(ValidationError):
        GroupChat(
            group_id="group-1",
            name="Operations",
            owner_id="user-1",
            members=[],
            created_at=_created_at(),
        )

    with pytest.raises(ValidationError):
        Moment(
            moment_id="moment-1",
            user_id="user-1",
            content="Shift handoff posted.",
            attachments=[],
            visibility="friends",
            created_at=_created_at(),
        )


def test_c19h_design_outputs_cover_all_required_contract_sections() -> None:
    schema = get_communication_extension_schema_design()
    api = get_communication_extension_api_placeholders()
    integration = get_communication_extension_integration_strategy()
    security = get_communication_extension_security_boundary()
    roadmap = get_communication_extension_expansion_roadmap()
    completion = get_communication_extension_completion_status()

    assert schema.voice_call_fields == (
        "call_id",
        "from_user_id",
        "to_user_id",
        "status",
        "duration",
        "created_at",
    )
    assert schema.voice_call_status_values == ("initiated", "ringing", "ended")
    assert schema.video_call_fields == (
        "call_id",
        "participants",
        "status",
        "resolution",
        "created_at",
    )
    assert schema.video_call_status_values == ("initiated", "active", "ended")
    assert schema.video_call_resolution_values == ("720p", "1080p", "future")
    assert schema.group_chat_fields == (
        "group_id",
        "name",
        "owner_id",
        "members",
        "created_at",
    )
    assert schema.moment_fields == (
        "moment_id",
        "user_id",
        "content",
        "attachments",
        "visibility",
        "created_at",
    )
    assert schema.moment_visibility_values == ("public", "org", "private")
    assert schema.moment_attachment_source == "C19G Attachment"
    assert schema.unified_model_fields == (
        "voice_call",
        "video_call",
        "group_chat",
        "moments",
    )
    assert schema.schema_only is True
    assert schema.runtime_logic_implemented is False

    routes = {(endpoint.method, endpoint.path) for endpoint in api.endpoints}
    assert routes == {
        ("POST", "/communication-extensions/voice-calls/initiate"),
        ("GET", "/communication-extensions/voice-calls/{call_id}"),
        ("POST", "/communication-extensions/video-calls/initiate"),
        ("GET", "/communication-extensions/video-calls/{call_id}"),
        ("POST", "/communication-extensions/group-chats"),
        ("GET", "/communication-extensions/group-chats/{group_id}"),
        ("POST", "/communication-extensions/moments"),
        ("GET", "/communication-extensions/moments/feed"),
    }
    assert all(endpoint.placeholder_only is True for endpoint in api.endpoints)
    assert all(endpoint.route_registered is False for endpoint in api.endpoints)
    assert all(endpoint.feature_enabled is False for endpoint in api.endpoints)
    assert all(endpoint.execution_allowed is False for endpoint in api.endpoints)
    assert api.mounted_under_application_api_prefix_reserved is True
    assert api.mounted_now is False
    assert api.websocket_implemented is False
    assert api.streaming_implemented is False

    assert integration.c19c_message_system_extension == (
        "future message references only; C19C remains unchanged"
    )
    assert integration.c19d_conversation_expansion == (
        "future direct/group conversation hooks only; C19D remains unchanged"
    )
    assert integration.c19f_permission_gating_future_hooks == (
        "future feature gating must run before any advanced capability is enabled"
    )
    assert integration.c18g_data_isolation_enforcement == (
        "all future storage and query paths must be org_id scoped through C18G"
    )
    assert integration.c18g_org_scope_key == "org_id"
    assert integration.modifies_c19c is False
    assert integration.modifies_c19d is False
    assert integration.modifies_c19f is False
    assert integration.modifies_c18g is False
    assert integration.runtime_integration_enabled is False

    assert security.schema_only is True
    assert security.all_features_disabled is True
    assert security.voice_call_enabled is False
    assert security.video_call_enabled is False
    assert security.group_chat_enabled is False
    assert security.moments_enabled is False
    assert security.execution_allowed is False
    assert security.websocket_implemented is False
    assert security.streaming_implemented is False
    assert security.realtime_signaling_implemented is False
    assert security.media_transport_implemented is False
    assert security.frontend_integration_implemented is False
    assert security.database_migration_executed is False
    assert security.c18g_data_isolation_required is True
    assert security.frontend_supplied_org_id_trusted is False

    assert [item.feature for item in roadmap.items] == [
        "voice_call",
        "video_call",
        "group_chat",
        "moments",
    ]
    assert [item.order for item in roadmap.items] == [1, 2, 3, 4]
    assert all(item.status == "reserved" for item in roadmap.items)
    assert all(
        item.implementation_allowed_in_c19h is False for item in roadmap.items
    )
    assert roadmap.implementation_status == "schema_reserved_only"

    assert completion.stage == "C19H"
    assert completion.voice_call_schema_defined is True
    assert completion.video_call_schema_defined is True
    assert completion.group_chat_schema_defined is True
    assert completion.moment_schema_defined is True
    assert completion.unified_model_defined is True
    assert completion.future_api_placeholders_defined is True
    assert completion.integration_strategy_defined is True
    assert completion.security_boundary_defined is True
    assert completion.expansion_roadmap_defined is True
    assert completion.all_features_disabled is True
    assert completion.runtime_execution_implemented is False
    assert completion.websocket_implemented is False
    assert completion.streaming_implemented is False
    assert completion.media_transport_implemented is False
    assert completion.frontend_implemented is False
    assert completion.migration_executed is False
    assert completion.c19a_to_c19g_modified is False
    assert completion.c18g_isolation_required is True
    assert "Future API placeholders are not mounted" in (
        COMMUNICATION_EXTENSIONS_BOUNDARY_SUMMARY
    )
    assert "C18G org_id scoped isolation is mandatory" in (
        COMMUNICATION_EXTENSIONS_BOUNDARY_SUMMARY
    )


def test_c19h_does_not_register_runtime_routes() -> None:
    routes = [
        route.path
        for route in app.routes
        if "/communication-extensions" in route.path
    ]

    assert routes == []
