from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable

import pytest

from backend.app.core.modules import MODULE_MANIFESTS_V1
from backend.app.core.permissions import BASE_PERMISSION_REGISTRY_SEED
from backend.app.modules.c19 import (
    C19StorageUnconfiguredError,
    ChatAssetBindingCommitCommandDTO,
    ChatAssetBindingPrepareCommandDTO,
    ChatAssetDeleteCommandDTO,
    ChatAssetDTO,
    ChatAssetDownloadRequestDTO,
    ChatAssetFinalizeCommandDTO,
    ChatAssetLookupDTO,
    ChatAssetQuarantineCommandDTO,
    ChatAssetStore,
    ChatAssetTransferInspectDTO,
    ChatAssetUploadHandleDTO,
    ChatAssetUploadMetadataDTO,
    ChatPositionAdvanceDTO,
    ChatPositionQueryDTO,
    ChatRecordAppendDTO,
    ChatRecordDeleteCommandDTO,
    ChatRecordQueryDTO,
    ChatRecordStore,
    ChatRetentionBatchCommandDTO,
    ChatUserEventQueryDTO,
    UnconfiguredChatAssetStore,
    UnconfiguredChatRecordStore,
    get_c19_storage_capabilities,
)
from backend.app.services.module_registry import validate_module_manifests
from backend.app.db.base import Base
from backend.app.modules.c19.http_asset_store import HttpChatAssetStore
from backend.app.modules.c19.http_record_store import HttpChatRecordStore
from backend.app.modules.c19.moment_storage import (
    MOMENT_ASSET_STORE_OPERATIONS,
    MOMENT_STORE_OPERATIONS,
    MomentAssetStore,
    MomentStore,
    UnconfiguredMomentAssetStore,
    UnconfiguredMomentStore,
)
from backend.app.modules.c19.moment_store_provider import (
    build_moment_asset_store,
    build_moment_store,
)


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
def test_c19_manifest_is_global_visible_and_permission_free() -> None:
    manifest = _communication_manifest()

    assert manifest.category == "core"
    assert manifest.status == "active"
    assert manifest.lifecycle == "production_released"
    assert manifest.route_namespace == "/c19"
    assert manifest.no_api is False
    assert manifest.api_namespace == "/c19"
    assert manifest.navigation.default_visible is True
    assert manifest.required_permissions == []
    assert manifest.allowed_scope_types == ["global"]
    assert manifest.unavailable_behavior == "show_unavailable"
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

    assert manifest.permission_manifest == []
    assert "communication.message.sent" in manifest.audit_log_actions
    assert "communication.moment.published" in manifest.audit_log_actions


@pytest.mark.unit
def test_c19_native_features_are_not_grantable_permissions() -> None:
    seed_by_key = {
        permission["permission_key"]: permission
        for permission in BASE_PERMISSION_REGISTRY_SEED
    }
    assert len(seed_by_key) == len(BASE_PERMISSION_REGISTRY_SEED)
    assert C19_PERMISSION_KEYS.isdisjoint(seed_by_key)


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
        "get_authorized_record",
        "list_records",
        "list_user_events",
        "get_user_event_tail",
        "advance_delivery",
        "advance_read",
        "get_unread_position",
        "get_unread_summary",
        "get_resume_position",
        "delete_records",
        "apply_retention_batch",
    }
    assert set(capabilities.asset_store.operations) == {
        "create_upload_intent",
        "get_asset",
        "finalize_upload",
        "prepare_binding",
        "commit_binding",
        "create_download_intent",
        "inspect_transfer",
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
    retention = ChatRetentionBatchCommandDTO(
        operation_id="rtn_" + "a" * 64,
        batch_ordinal=0,
        approved_maximum_records=10_000,
        approved_maximum_asset_jobs=10_000,
        requested_by_user_id="user_1",
        reason="test retention",
        requested_at=now,
        delete_before=now - timedelta(days=365),
        maximum_records=1_000,
    )

    assert store.capability.configured is False
    operations: tuple[tuple[str, Callable[[], Awaitable[object]]], ...] = (
        ("append_record", lambda: store.append_record(record)),
        (
            "get_authorized_record",
            lambda: store.get_authorized_record(
                conversation_id=record.conversation_id,
                record_id="record_test_1",
                user_id="user_1",
            ),
        ),
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
        (
            "apply_retention_batch",
            lambda: store.apply_retention_batch(retention),
        ),
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
        conversation_id="conv_test_1",
        kind="file",
        filename="evidence.txt",
        media_type="text/plain",
        size_bytes=42,
        sha256_hex="a" * 64,
        requested_at=now,
    )
    asset = ChatAssetDTO(
        asset_id="att_" + "1" * 32,
        client_asset_id=metadata.client_asset_id,
        owner_user_id=metadata.owner_user_id,
        conversation_id=metadata.conversation_id,
        kind=metadata.kind,
        filename=metadata.filename,
        media_type=metadata.media_type,
        size_bytes=metadata.size_bytes,
        sha256_hex=metadata.sha256_hex,
        version=1,
        status="pending_upload",
    )
    handle = ChatAssetUploadHandleDTO(
        asset=asset,
        opaque_ticket="a" * 43,
        expires_at=now + timedelta(minutes=5),
    )
    lookup = ChatAssetLookupDTO(
        asset_id=asset.asset_id,
        owner_user_id=metadata.owner_user_id,
        conversation_id=metadata.conversation_id,
    )
    finalize = ChatAssetFinalizeCommandDTO(
        asset_id=lookup.asset_id,
        owner_user_id=lookup.owner_user_id,
        conversation_id=lookup.conversation_id,
    )
    prepare = ChatAssetBindingPrepareCommandDTO(
        asset_id=lookup.asset_id,
        owner_user_id=lookup.owner_user_id,
        conversation_id=lookup.conversation_id,
        client_message_id="client_message_1",
    )
    commit = ChatAssetBindingCommitCommandDTO(
        asset_id=lookup.asset_id,
        owner_user_id=lookup.owner_user_id,
        conversation_id=lookup.conversation_id,
        client_message_id="client_message_1",
        record_id="record_1",
    )
    download = ChatAssetDownloadRequestDTO(
        asset_id=asset.asset_id,
        owner_user_id=metadata.owner_user_id,
        reader_user_id="user_2",
        conversation_id=metadata.conversation_id,
        record_id="record_1",
        variant="original",
        disposition="attachment",
        asset_version=1,
    )
    inspect = ChatAssetTransferInspectDTO(
        opaque_ticket="a" * 43,
        direction="upload",
        method="PUT",
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
    assert handle.opaque_handle == handle.opaque_ticket
    operations: tuple[tuple[str, Callable[[], Awaitable[object]]], ...] = (
        (
            "create_upload_intent",
            lambda: store.create_upload_intent(metadata),
        ),
        ("get_asset", lambda: store.get_asset(lookup)),
        ("finalize_upload", lambda: store.finalize_upload(finalize)),
        ("prepare_binding", lambda: store.prepare_binding(prepare)),
        ("commit_binding", lambda: store.commit_binding(commit)),
        (
            "create_download_intent",
            lambda: store.create_download_intent(download),
        ),
        ("inspect_transfer", lambda: store.inspect_transfer(inspect)),
        ("quarantine_asset", lambda: store.quarantine_asset(quarantine)),
        ("delete_asset", lambda: store.delete_asset(delete)),
    )
    for operation, call in operations:
        _assert_unconfigured(
            operation,
            call,
            store_name="chat_asset_store",
        )


@pytest.mark.unit
def test_moment_ports_are_protocol_exact_fail_closed_and_outside_barong_tables() -> None:
    moment_store: MomentStore = UnconfiguredMomentStore()  # type: ignore[assignment]
    asset_store: MomentAssetStore = UnconfiguredMomentAssetStore()  # type: ignore[assignment]

    assert isinstance(moment_store, MomentStore)
    assert isinstance(asset_store, MomentAssetStore)
    assert moment_store.capability.configured is False
    assert asset_store.capability.configured is False
    assert not any(
        table_name.startswith("c19_moment")
        for table_name in Base.metadata.tables
    )

    moment_calls: dict[str, Callable[[], Awaitable[object]]] = {
        operation: (lambda operation=operation: getattr(moment_store, operation)(None))
        for operation in MOMENT_STORE_OPERATIONS
        if operation != "get_moment_draft"
    }
    moment_calls["get_moment_draft"] = lambda: moment_store.get_moment_draft(
        moment_id="mom_" + "1" * 32,
        author_user_id="1",
    )
    assert set(moment_calls) == set(MOMENT_STORE_OPERATIONS)
    for operation, call in moment_calls.items():
        _assert_unconfigured(
            operation,
            call,
            store_name="chat_record_store",
        )
    asset_calls: dict[str, Callable[[], Awaitable[object]]] = {
        operation: (lambda operation=operation: getattr(asset_store, operation)(None))
        for operation in MOMENT_ASSET_STORE_OPERATIONS
        if operation != "inspect_scoped_transfer"
    }
    asset_calls["inspect_scoped_transfer"] = lambda: asset_store.inspect_scoped_transfer(
        opaque_ticket="a" * 43,
        direction="upload",
        method="PUT",
    )
    asset_calls["delete_asset"] = lambda: asset_store.delete_asset(None)
    assert set(asset_calls) == set(MOMENT_ASSET_STORE_OPERATIONS) | {"delete_asset"}
    for operation, call in asset_calls.items():
        _assert_unconfigured(
            operation,
            call,
            store_name="chat_asset_store",
        )


@pytest.mark.unit
def test_configured_moment_providers_implement_ports_and_describe_both_wires() -> None:
    record_store = build_moment_store(
        {
            "C19_RECORD_STORE_URL": "http://c19-record-api:8089",
            "C19_RECORD_STORE_TOKEN": "r" * 32,
        }
    )
    asset_store = build_moment_asset_store(
        {
            "C19_ASSET_STORE_URL": "http://c19-asset-api:8091",
            "C19_ASSET_STORE_TOKEN": "a" * 32,
        }
    )
    try:
        assert isinstance(record_store, HttpChatRecordStore)
        assert isinstance(record_store, MomentStore)
        assert set(MOMENT_STORE_OPERATIONS) <= set(record_store.capability.operations)
        assert "append_record" in record_store.capability.operations

        assert isinstance(asset_store, HttpChatAssetStore)
        assert isinstance(asset_store, MomentAssetStore)
        assert set(MOMENT_ASSET_STORE_OPERATIONS) <= set(
            asset_store.capability.operations
        )
        assert "create_upload_intent" in asset_store.capability.operations
        assert "delete_asset" in asset_store.capability.operations
    finally:
        asyncio.run(record_store.aclose())  # type: ignore[attr-defined]
        asyncio.run(asset_store.aclose())  # type: ignore[attr-defined]
