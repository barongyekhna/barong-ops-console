from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .attachment import Attachment


class VoiceCallStatus(StrEnum):
    INITIATED = "initiated"
    RINGING = "ringing"
    ENDED = "ended"


class VideoCallStatus(StrEnum):
    INITIATED = "initiated"
    ACTIVE = "active"
    ENDED = "ended"


class VideoCallResolution(StrEnum):
    P720 = "720p"
    P1080 = "1080p"
    FUTURE = "future"


class MomentVisibility(StrEnum):
    PUBLIC = "public"
    ORG = "org"
    PRIVATE = "private"


class CommunicationExtensionFeature(StrEnum):
    VOICE_CALL = "voice_call"
    VIDEO_CALL = "video_call"
    GROUP_CHAT = "group_chat"
    MOMENTS = "moments"


class CommunicationExtensionOperation(StrEnum):
    INITIATE_VOICE_CALL = "initiate_voice_call"
    GET_VOICE_CALL = "get_voice_call"
    INITIATE_VIDEO_CALL = "initiate_video_call"
    GET_VIDEO_CALL = "get_video_call"
    CREATE_GROUP_CHAT = "create_group_chat"
    GET_GROUP_CHAT = "get_group_chat"
    CREATE_MOMENT = "create_moment"
    GET_MOMENT_FEED = "get_moment_feed"


class VoiceCall(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    call_id: str = Field(min_length=1, max_length=64)
    from_user_id: str = Field(min_length=1, max_length=255)
    to_user_id: str = Field(min_length=1, max_length=255)
    status: VoiceCallStatus
    duration: int = Field(ge=0)
    created_at: datetime


class VideoCall(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    call_id: str = Field(min_length=1, max_length=64)
    participants: list[str] = Field(min_length=1, max_length=200)
    status: VideoCallStatus
    resolution: VideoCallResolution
    created_at: datetime


class GroupChat(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    group_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    owner_id: str = Field(min_length=1, max_length=255)
    members: list[str] = Field(min_length=1, max_length=500)
    created_at: datetime


class Moment(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    moment_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=4000)
    attachments: list[Attachment]
    visibility: MomentVisibility
    created_at: datetime


class CommunicationExtensions(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    voice_call: VoiceCall
    video_call: VideoCall
    group_chat: GroupChat
    moments: Moment


class CommunicationExtensionSchemaDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["c19h_communication_extensions_schema_v1"] = (
        "c19h_communication_extensions_schema_v1"
    )
    voice_call_model_path: Literal[
        "backend.app.schemas.communication_extensions.VoiceCall"
    ] = "backend.app.schemas.communication_extensions.VoiceCall"
    video_call_model_path: Literal[
        "backend.app.schemas.communication_extensions.VideoCall"
    ] = "backend.app.schemas.communication_extensions.VideoCall"
    group_chat_model_path: Literal[
        "backend.app.schemas.communication_extensions.GroupChat"
    ] = "backend.app.schemas.communication_extensions.GroupChat"
    moment_model_path: Literal[
        "backend.app.schemas.communication_extensions.Moment"
    ] = "backend.app.schemas.communication_extensions.Moment"
    unified_model_path: Literal[
        "backend.app.schemas.communication_extensions.CommunicationExtensions"
    ] = "backend.app.schemas.communication_extensions.CommunicationExtensions"
    voice_call_fields: tuple[
        Literal["call_id"],
        Literal["from_user_id"],
        Literal["to_user_id"],
        Literal["status"],
        Literal["duration"],
        Literal["created_at"],
    ] = (
        "call_id",
        "from_user_id",
        "to_user_id",
        "status",
        "duration",
        "created_at",
    )
    voice_call_status_values: tuple[
        Literal["initiated"],
        Literal["ringing"],
        Literal["ended"],
    ] = ("initiated", "ringing", "ended")
    video_call_fields: tuple[
        Literal["call_id"],
        Literal["participants"],
        Literal["status"],
        Literal["resolution"],
        Literal["created_at"],
    ] = (
        "call_id",
        "participants",
        "status",
        "resolution",
        "created_at",
    )
    video_call_status_values: tuple[
        Literal["initiated"],
        Literal["active"],
        Literal["ended"],
    ] = ("initiated", "active", "ended")
    video_call_resolution_values: tuple[
        Literal["720p"],
        Literal["1080p"],
        Literal["future"],
    ] = ("720p", "1080p", "future")
    group_chat_fields: tuple[
        Literal["group_id"],
        Literal["name"],
        Literal["owner_id"],
        Literal["members"],
        Literal["created_at"],
    ] = ("group_id", "name", "owner_id", "members", "created_at")
    moment_fields: tuple[
        Literal["moment_id"],
        Literal["user_id"],
        Literal["content"],
        Literal["attachments"],
        Literal["visibility"],
        Literal["created_at"],
    ] = (
        "moment_id",
        "user_id",
        "content",
        "attachments",
        "visibility",
        "created_at",
    )
    moment_visibility_values: tuple[
        Literal["public"],
        Literal["org"],
        Literal["private"],
    ] = ("public", "org", "private")
    moment_attachment_source: Literal["C19G Attachment"] = "C19G Attachment"
    unified_model_fields: tuple[
        Literal["voice_call"],
        Literal["video_call"],
        Literal["group_chat"],
        Literal["moments"],
    ] = ("voice_call", "video_call", "group_chat", "moments")
    schema_only: Literal[True] = True
    runtime_logic_implemented: Literal[False] = False


class CommunicationExtensionApiEndpointPlaceholder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["GET", "POST"]
    path: str = Field(min_length=1, max_length=180)
    feature: CommunicationExtensionFeature
    operation: CommunicationExtensionOperation
    placeholder_only: Literal[True] = True
    route_registered: Literal[False] = False
    feature_enabled: Literal[False] = False
    execution_allowed: Literal[False] = False
    websocket_or_streaming_allowed: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class CommunicationExtensionApiPlaceholders(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19h_future_api_placeholders_v1"] = (
        "c19h_future_api_placeholders_v1"
    )
    endpoints: tuple[
        CommunicationExtensionApiEndpointPlaceholder,
        CommunicationExtensionApiEndpointPlaceholder,
        CommunicationExtensionApiEndpointPlaceholder,
        CommunicationExtensionApiEndpointPlaceholder,
        CommunicationExtensionApiEndpointPlaceholder,
        CommunicationExtensionApiEndpointPlaceholder,
        CommunicationExtensionApiEndpointPlaceholder,
        CommunicationExtensionApiEndpointPlaceholder,
    ] = (
        CommunicationExtensionApiEndpointPlaceholder(
            method="POST",
            path="/communication-extensions/voice-calls/initiate",
            feature=CommunicationExtensionFeature.VOICE_CALL,
            operation=CommunicationExtensionOperation.INITIATE_VOICE_CALL,
            notes="Future voice call entry point; C19H defines no call logic.",
        ),
        CommunicationExtensionApiEndpointPlaceholder(
            method="GET",
            path="/communication-extensions/voice-calls/{call_id}",
            feature=CommunicationExtensionFeature.VOICE_CALL,
            operation=CommunicationExtensionOperation.GET_VOICE_CALL,
            notes="Future voice call lookup; C19H registers no route.",
        ),
        CommunicationExtensionApiEndpointPlaceholder(
            method="POST",
            path="/communication-extensions/video-calls/initiate",
            feature=CommunicationExtensionFeature.VIDEO_CALL,
            operation=CommunicationExtensionOperation.INITIATE_VIDEO_CALL,
            notes="Future video call entry point; C19H defines no media logic.",
        ),
        CommunicationExtensionApiEndpointPlaceholder(
            method="GET",
            path="/communication-extensions/video-calls/{call_id}",
            feature=CommunicationExtensionFeature.VIDEO_CALL,
            operation=CommunicationExtensionOperation.GET_VIDEO_CALL,
            notes="Future video call lookup; C19H registers no route.",
        ),
        CommunicationExtensionApiEndpointPlaceholder(
            method="POST",
            path="/communication-extensions/group-chats",
            feature=CommunicationExtensionFeature.GROUP_CHAT,
            operation=CommunicationExtensionOperation.CREATE_GROUP_CHAT,
            notes="Future group chat creation; C19H defines schema only.",
        ),
        CommunicationExtensionApiEndpointPlaceholder(
            method="GET",
            path="/communication-extensions/group-chats/{group_id}",
            feature=CommunicationExtensionFeature.GROUP_CHAT,
            operation=CommunicationExtensionOperation.GET_GROUP_CHAT,
            notes="Future group chat lookup; C19H registers no route.",
        ),
        CommunicationExtensionApiEndpointPlaceholder(
            method="POST",
            path="/communication-extensions/moments",
            feature=CommunicationExtensionFeature.MOMENTS,
            operation=CommunicationExtensionOperation.CREATE_MOMENT,
            notes="Future moment publishing; C19H defines no feed logic.",
        ),
        CommunicationExtensionApiEndpointPlaceholder(
            method="GET",
            path="/communication-extensions/moments/feed",
            feature=CommunicationExtensionFeature.MOMENTS,
            operation=CommunicationExtensionOperation.GET_MOMENT_FEED,
            notes="Future moment feed lookup; C19H registers no route.",
        ),
    )
    mounted_under_application_api_prefix_reserved: Literal[True] = True
    mounted_now: Literal[False] = False
    public_api_exposure_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    websocket_implemented: Literal[False] = False
    streaming_implemented: Literal[False] = False


class CommunicationExtensionIntegrationStrategy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c19h_c19c_c19d_c19f_c18g_strategy_v1"] = (
        "c19h_c19c_c19d_c19f_c18g_strategy_v1"
    )
    c19c_message_system_extension: Literal[
        "future message references only; C19C remains unchanged"
    ] = "future message references only; C19C remains unchanged"
    c19d_conversation_expansion: Literal[
        "future direct/group conversation hooks only; C19D remains unchanged"
    ] = "future direct/group conversation hooks only; C19D remains unchanged"
    c19f_permission_gating_future_hooks: Literal[
        "future feature gating must run before any advanced capability is enabled"
    ] = "future feature gating must run before any advanced capability is enabled"
    c18g_data_isolation_enforcement: Literal[
        "all future storage and query paths must be org_id scoped through C18G"
    ] = "all future storage and query paths must be org_id scoped through C18G"
    c18g_org_scope_key: Literal["org_id"] = "org_id"
    modifies_c19c: Literal[False] = False
    modifies_c19d: Literal[False] = False
    modifies_c19f: Literal[False] = False
    modifies_c18g: Literal[False] = False
    runtime_integration_enabled: Literal[False] = False


class CommunicationExtensionSecurityBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boundary_id: Literal["c19h_security_boundary_v1"] = (
        "c19h_security_boundary_v1"
    )
    schema_only: Literal[True] = True
    all_features_disabled: Literal[True] = True
    voice_call_enabled: Literal[False] = False
    video_call_enabled: Literal[False] = False
    group_chat_enabled: Literal[False] = False
    moments_enabled: Literal[False] = False
    execution_allowed: Literal[False] = False
    websocket_implemented: Literal[False] = False
    streaming_implemented: Literal[False] = False
    realtime_signaling_implemented: Literal[False] = False
    media_transport_implemented: Literal[False] = False
    frontend_integration_implemented: Literal[False] = False
    database_migration_executed: Literal[False] = False
    c18g_data_isolation_required: Literal[True] = True
    c18g_org_scope_key: Literal["org_id"] = "org_id"
    frontend_supplied_org_id_trusted: Literal[False] = False
    public_api_exposure_allowed: Literal[False] = False


class CommunicationExtensionRoadmapItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order: int = Field(ge=1)
    feature: CommunicationExtensionFeature
    reserved_hook: str = Field(min_length=1, max_length=255)
    required_prior_gate: str = Field(min_length=1, max_length=255)
    status: Literal["reserved"] = "reserved"
    implementation_allowed_in_c19h: Literal[False] = False


class CommunicationExtensionExpansionRoadmap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    roadmap_id: Literal["c19h_expansion_roadmap_v1"] = (
        "c19h_expansion_roadmap_v1"
    )
    items: tuple[
        CommunicationExtensionRoadmapItem,
        CommunicationExtensionRoadmapItem,
        CommunicationExtensionRoadmapItem,
        CommunicationExtensionRoadmapItem,
    ] = (
        CommunicationExtensionRoadmapItem(
            order=1,
            feature=CommunicationExtensionFeature.VOICE_CALL,
            reserved_hook="voice call signaling contract",
            required_prior_gate="C19F feature gating plus C18G org scope",
        ),
        CommunicationExtensionRoadmapItem(
            order=2,
            feature=CommunicationExtensionFeature.VIDEO_CALL,
            reserved_hook="video call session and resolution contract",
            required_prior_gate="C19F feature gating plus C18G org scope",
        ),
        CommunicationExtensionRoadmapItem(
            order=3,
            feature=CommunicationExtensionFeature.GROUP_CHAT,
            reserved_hook="group conversation participant contract",
            required_prior_gate="C19D conversation expansion plus C18G org scope",
        ),
        CommunicationExtensionRoadmapItem(
            order=4,
            feature=CommunicationExtensionFeature.MOMENTS,
            reserved_hook="moment publication and visibility contract",
            required_prior_gate="C19F visibility gate plus C18G org scope",
        ),
    )
    implementation_status: Literal["schema_reserved_only"] = "schema_reserved_only"
    next_stage_must_not_reuse_c19h_as_runtime: Literal[True] = True


class CommunicationExtensionCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19H"] = "C19H"
    component: Literal["Future Communication Extensions"] = (
        "Future Communication Extensions"
    )
    completion_status: Literal["complete"] = "complete"
    voice_call_schema_defined: Literal[True] = True
    video_call_schema_defined: Literal[True] = True
    group_chat_schema_defined: Literal[True] = True
    moment_schema_defined: Literal[True] = True
    unified_model_defined: Literal[True] = True
    future_api_placeholders_defined: Literal[True] = True
    integration_strategy_defined: Literal[True] = True
    security_boundary_defined: Literal[True] = True
    expansion_roadmap_defined: Literal[True] = True
    all_features_disabled: Literal[True] = True
    runtime_execution_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False
    streaming_implemented: Literal[False] = False
    media_transport_implemented: Literal[False] = False
    frontend_implemented: Literal[False] = False
    migration_executed: Literal[False] = False
    c19a_to_c19g_modified: Literal[False] = False
    c18g_isolation_required: Literal[True] = True


COMMUNICATION_EXTENSIONS_BOUNDARY_SUMMARY = """
C19H defines future IM advanced capability schemas only.
  -> VoiceCall, VideoCall, GroupChat, and Moment are schema contracts.
  -> CommunicationExtensions is the unified reserved interface model.
  -> Future API placeholders are not mounted and cannot execute.
  -> C19C, C19D, C19F, and C18G are integration references only.
  -> C18G org_id scoped isolation is mandatory for any future persistence path.
  -> No websocket, streaming, realtime signaling, media transport, frontend, or migration.
""".strip()


def get_communication_extension_schema_design() -> (
    CommunicationExtensionSchemaDesign
):
    return CommunicationExtensionSchemaDesign()


def get_communication_extension_api_placeholders() -> (
    CommunicationExtensionApiPlaceholders
):
    return CommunicationExtensionApiPlaceholders()


def get_communication_extension_integration_strategy() -> (
    CommunicationExtensionIntegrationStrategy
):
    return CommunicationExtensionIntegrationStrategy()


def get_communication_extension_security_boundary() -> (
    CommunicationExtensionSecurityBoundary
):
    return CommunicationExtensionSecurityBoundary()


def get_communication_extension_expansion_roadmap() -> (
    CommunicationExtensionExpansionRoadmap
):
    return CommunicationExtensionExpansionRoadmap()


def get_communication_extension_completion_status() -> (
    CommunicationExtensionCompletionStatus
):
    return CommunicationExtensionCompletionStatus()
