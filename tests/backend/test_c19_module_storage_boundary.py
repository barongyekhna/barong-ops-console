from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable

import pytest

from backend.app.core.modules import MODULE_MANIFESTS_V1
from backend.app.core.permissions import BASE_PERMISSION_REGISTRY_SEED
from backend.app.modules.c19 import (
    C19StorageUnconfiguredError,
    ChatAssetDeleteCommandDTO,
    ChatAssetDTO,
    ChatAssetQuarantineCommandDTO,
    ChatAssetStore,
    ChatAssetUploadHandleDTO,
    ChatAssetUploadMetadataDTO,
    ChatPositionAdvanceDTO,
    ChatPositionQueryDTO,
    ChatRecordAppendDTO,
    ChatRecordDeleteCommandDTO,
    ChatRecordQueryDTO,
    ChatRecordStore,
    ChatRetentionCommandDTO,
    ChatUserEventQueryDTO,
    UnconfiguredChatAssetStore,
    UnconfiguredChatRecordStore,
    get_c19_storage_capabilities,
)
from backend.app.services.module_registry import validate_module_manifests


C19_PERMISSION_KEYS = {
    "c19.directory.read",
    "c19.conversations.read",
    "c19.messages.send",
    "c19.friends.manage",
    "c19.groups.create",
    "c19.groups.manage",
    "c19.moments.read",
    "c19.moments.publish",
    "c19.attachments.upload",
    "c19.moderation.manage",
}


def _communication_manifest():
    raw_manifest = next(
        raw
        for raw in MODULE_MANIFESTS_V1
        if raw["module_key"] == "communication.im"
    )
    return validate_module_manifests([raw_manifest])[0]


def _assert_unconfigured(
    operation: str,
    call: Callable[[], Awaitable[object]],
    *,
    store_name: str,
) -> None:
    with pytest.raises(C19StorageUnconfiguredError) as exc_info:
        asyncio.run(call())

    assert exc_info.value.store_name == store_name
    assert exc_info.value.operation == operation
    assert "unconfigured" in str(exc_info.value)
    assert "blocked (fail-closed)" in str(exc_info.value)


@pytest.mark.unit
def test_c19_manifest_is_global_planned_and_metadata_only() -> None:
    manifest = _communication_manifest()

    assert manifest.category == "core"
    assert manifest.status == "planned"
    assert manifest.lifecycle == "designed"
    assert manifest.route_namespace == "/c19"
    assert manifest.no_api is False
    assert manifest.api_namespace == "/c19"
    assert manifest.required_permissions == ["c19.directory.read"]
    assert manifest.allowed_scope_types == ["global"]
    assert manifest.unavailable_behavior == "planned"
    assert manifest.module_adapter_required is True
    assert set(manifest.external_dependencies) == {
        "chat_record_store",
        "chat_asset_store",
    }

    expected_control_tables = {
        "c19_profiles",
        "c19_affiliations",
        "c19_friend_requests",
        "c19_relationships",
        "c19_user_blocks",
        "c19_conversations",
        "c19_conversation_members",
        "c19_conversation_user_settings",
    }
    assert set(manifest.data_boundary.reads) == expected_control_tables
    assert set(manifest.data_boundary.writes) == expected_control_tables
    assert {
        "external_chat_content",
        "external_chat_assets",
        "external_chat_storage_configuration",
    }.issubset(set(manifest.data_boundary.blocked_objects))

    permission_entries = {
        entry.permission_key: entry for entry in manifest.permission_manifest
    }
    assert set(permission_entries) == C19_PERMISSION_KEYS
    assert all(
        entry.allowed_scope_types == ["global"]
        for entry in permission_entries.values()
    )
    assert permission_entries["c19.moderation.manage"].risk_level == "critical"
    assert (
        permission_entries[
            "c19.moderation.manage"
        ].high_risk_confirmation_required
        is True
    )


@pytest.mark.unit
def test_c19_permissions_are_seeded_without_manifest_drift() -> None:
    seed_by_key = {
        permission["permission_key"]: permission
        for permission in BASE_PERMISSION_REGISTRY_SEED
    }
    assert len(seed_by_key) == len(BASE_PERMISSION_REGISTRY_SEED)
    assert C19_PERMISSION_KEYS.issubset(seed_by_key)

    manifest = _communication_manifest()
    for entry in manifest.permission_manifest:
        seeded = seed_by_key[entry.permission_key]
        assert seeded["module_key"] == "communication.im"
        assert seeded["category"] == entry.category
        assert seeded["action"] == entry.action
        assert seeded["risk_level"] == entry.risk_level
        assert seeded["menu_policy"] == entry.menu_policy
        assert seeded["label"] == entry.label
        assert seeded["description"] == entry.description


@pytest.mark.unit
def test_unconfigured_storage_capabilities_are_explicit_and_non_executable() -> None:
    capabilities = get_c19_storage_capabilities()

    for capability in (capabilities.record_store, capabilities.asset_store):
        assert capability.status == "unconfigured"
        assert capability.configured is False
        assert capability.readable is False
        assert capability.writable is False
        assert capability.durable is False
        assert capability.external_io_enabled is False
        assert "No vetted C19" in capability.reason

    assert set(capabilities.record_store.operations) == {
        "append_record",
        "list_records",
        "list_user_events",
        "get_user_event_tail",
        "advance_delivery",
        "advance_read",
        "get_unread_position",
        "get_resume_position",
        "delete_records",
        "apply_retention",
    }
    assert set(capabilities.asset_store.operations) == {
        "create_upload_intent",
        "finalize_upload",
        "create_download_intent",
        "quarantine_asset",
        "delete_asset",
    }


@pytest.mark.unit
def test_unconfigured_chat_record_store_fails_closed_for_every_operation() -> None:
    store: ChatRecordStore = UnconfiguredChatRecordStore()
    now = datetime.now(UTC)
    record = ChatRecordAppendDTO(
        client_message_id="client_msg_test_1",
        conversation_id="conv_test_1",
        sender_user_id="user_1",
        recipient_user_ids=("user_2",),
        content_type="text",
        content="must never be persisted by the unconfigured store",
        created_at=now,
    )
    query = ChatRecordQueryDTO(
        conversation_id=record.conversation_id,
        user_id="user_1",
    )
    advance = ChatPositionAdvanceDTO(
        conversation_id=record.conversation_id,
        user_id="user_1",
        through_sequence=1,
        occurred_at=now,
    )
    position_query = ChatPositionQueryDTO(
        conversation_id=record.conversation_id,
        user_id="user_1",
    )
    event_query = ChatUserEventQueryDTO(user_id="user_1")
    delete = ChatRecordDeleteCommandDTO(
        conversation_id=record.conversation_id,
        record_ids=("msg_test_1",),
        requested_by_user_id="user_1",
        reason="test deletion",
        requested_at=now,
    )
    retention = ChatRetentionCommandDTO(
        requested_by_user_id="user_1",
        reason="test retention",
        requested_at=now,
        delete_before=now - timedelta(days=365),
    )

    assert store.capability.configured is False
    operations: tuple[tuple[str, Callable[[], Awaitable[object]]], ...] = (
        ("append_record", lambda: store.append_record(record)),
        ("list_records", lambda: store.list_records(query)),
        ("list_user_events", lambda: store.list_user_events(event_query)),
        ("get_user_event_tail", lambda: store.get_user_event_tail("user_1")),
        ("advance_delivery", lambda: store.advance_delivery(advance)),
        ("advance_read", lambda: store.advance_read(advance)),
        (
            "get_unread_position",
            lambda: store.get_unread_position(position_query),
        ),
        (
            "get_resume_position",
            lambda: store.get_resume_position(position_query),
        ),
        ("delete_records", lambda: store.delete_records(delete)),
        ("apply_retention", lambda: store.apply_retention(retention)),
    )
    for operation, call in operations:
        _assert_unconfigured(
            operation,
            call,
            store_name="chat_record_store",
        )


@pytest.mark.unit
def test_unconfigured_chat_asset_store_fails_closed_for_every_operation() -> None:
    store: ChatAssetStore = UnconfiguredChatAssetStore()
    now = datetime.now(UTC)
    metadata = ChatAssetUploadMetadataDTO(
        client_asset_id="client_asset_test_1",
        owner_user_id="user_1",
        filename="evidence.txt",
        media_type="text/plain",
        size_bytes=42,
        sha256_hex="a" * 64,
        requested_at=now,
        conversation_id="conv_test_1",
        message_id="msg_test_1",
    )
    handle = ChatAssetUploadHandleDTO(
        opaque_handle="opaque-test-handle",
        expires_at=now + timedelta(minutes=5),
    )
    quarantine = ChatAssetQuarantineCommandDTO(
        asset_id="asset_test_1",
        requested_by_user_id="user_1",
        reason="test quarantine",
        requested_at=now,
    )
    delete = ChatAssetDeleteCommandDTO(
        asset_id="asset_test_1",
        requested_by_user_id="user_1",
        reason="test deletion",
        requested_at=now,
    )

    assert store.capability.configured is False
    assert "content" not in ChatAssetDTO.__dataclass_fields__
    assert "content" not in ChatAssetUploadMetadataDTO.__dataclass_fields__
    operations: tuple[tuple[str, Callable[[], Awaitable[object]]], ...] = (
        (
            "create_upload_intent",
            lambda: store.create_upload_intent(metadata),
        ),
        ("finalize_upload", lambda: store.finalize_upload(handle)),
        (
            "create_download_intent",
            lambda: store.create_download_intent("asset_test_1"),
        ),
        ("quarantine_asset", lambda: store.quarantine_asset(quarantine)),
        ("delete_asset", lambda: store.delete_asset(delete)),
    )
    for operation, call in operations:
        _assert_unconfigured(
            operation,
            call,
            store_name="chat_asset_store",
        )
