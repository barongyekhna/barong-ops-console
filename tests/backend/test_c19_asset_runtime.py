from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.base import Base
from backend.app.models.c19 import (
    C19AffiliationRecord,
    C19ConversationMemberRecord,
    C19ConversationRecord,
    C19ProfileRecord,
    C19UserBlockRecord,
)
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.c19.asset_router import _raise_asset_error, router as asset_router
from backend.app.modules.c19.asset_schemas import (
    ChatAssetAccessIntentRequest,
    ChatAssetUploadIntentRequest,
)
from backend.app.modules.c19.asset_service import (
    C19AssetAccessError,
    authorize_asset_transfer,
    create_asset_access_intent,
    create_asset_upload_intent,
)
from backend.app.modules.c19.asset_store_provider import build_chat_asset_store
from backend.app.modules.c19.http_asset_store import (
    ChatAssetStoreAuthenticationError,
    ChatAssetStoreConflictError,
    ChatAssetStoreProtocolError,
    ChatAssetStoreQuotaError,
    ChatAssetStoreRejectedError,
    ChatAssetStoreUnavailableError,
    HttpChatAssetStore,
    HttpChatAssetStoreConfig,
)
from backend.app.modules.c19.http_record_store import ChatRecordStoreRejectedError
from backend.app.modules.c19.message_schemas import MessageCreateRequest
from backend.app.modules.c19.message_service import C19ChatAccessError, send_message
from backend.app.modules.c19.router import router as aggregate_router
from backend.app.modules.c19.storage import (
    CHAT_ASSET_STORE_OPERATIONS,
    ChatAssetBindingCommitCommandDTO,
    ChatAssetBindingPrepareCommandDTO,
    ChatAssetBindingResultDTO,
    ChatAssetDTO,
    ChatAssetDownloadIntentDTO,
    ChatAssetDownloadRequestDTO,
    ChatAssetFinalizeCommandDTO,
    ChatAssetLookupDTO,
    ChatAssetReferenceDTO,
    ChatAssetStore,
    ChatAssetTransferInspectDTO,
    ChatAssetTransferInspectionDTO,
    ChatAssetUploadHandleDTO,
    ChatAssetUploadMetadataDTO,
    ChatRecordAppendDTO,
    ChatRecordDTO,
    StorageCapabilityDescription,
    get_c19_storage_capabilities,
)


pytestmark = pytest.mark.unit

ORG_ONE = "org_" + "1" * 32
ORG_TWO = "org_" + "2" * 32
CONVERSATION_ID = "c19_asset_direct"
ASSET_ID = "att_" + "a" * 32
UPLOAD_TICKET = "u" * 43
DOWNLOAD_TICKET = "d" * 43


def _asset(*, status: str = "active") -> ChatAssetDTO:
    return ChatAssetDTO(
        asset_id=ASSET_ID,
        client_asset_id="browser-asset-1",
        owner_user_id="1",
        conversation_id=CONVERSATION_ID,
        kind="image",
        filename="proof.jpg",
        media_type="image/jpeg",
        size_bytes=1234,
        sha256_hex="b" * 64,
        version=1,
        status=status,  # type: ignore[arg-type]
    )


def _reference() -> ChatAssetReferenceDTO:
    asset = _asset()
    return ChatAssetReferenceDTO(
        asset_id=asset.asset_id,
        client_asset_id=asset.client_asset_id,
        kind=asset.kind,
        filename=asset.filename,
        media_type=asset.media_type,
        size_bytes=asset.size_bytes,
        sha256_hex=asset.sha256_hex,
        version=asset.version,
        ordinal=0,
    )


class FakeAssetStore:
    def __init__(self) -> None:
        self.asset = _asset()
        self.uploads: list[ChatAssetUploadMetadataDTO] = []
        self.lookups: list[ChatAssetLookupDTO] = []
        self.prepares: list[ChatAssetBindingPrepareCommandDTO] = []
        self.commits: list[ChatAssetBindingCommitCommandDTO] = []
        self.downloads: list[ChatAssetDownloadRequestDTO] = []
        self.inspections: list[ChatAssetTransferInspectDTO] = []
        self.fail_commit_once = False
        self.transfer: ChatAssetTransferInspectionDTO | None = None
        self.prepared_client_message_id: str | None = None
        self.committed_record_id: str | None = None

    @property
    def capability(self) -> StorageCapabilityDescription:
        return StorageCapabilityDescription(
            store_name="chat_asset_store",
            status="configured",
            configured=True,
            readable=True,
            writable=True,
            durable=True,
            external_io_enabled=True,
            operations=CHAT_ASSET_STORE_OPERATIONS,
            reason="fake",
        )

    async def create_upload_intent(
        self, metadata: ChatAssetUploadMetadataDTO
    ) -> ChatAssetUploadHandleDTO:
        self.uploads.append(metadata)
        pending = ChatAssetDTO(
            asset_id=self.asset.asset_id,
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
        return ChatAssetUploadHandleDTO(
            asset=pending,
            opaque_ticket=UPLOAD_TICKET,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
        )

    async def get_asset(self, query: ChatAssetLookupDTO) -> ChatAssetDTO:
        self.lookups.append(query)
        if (
            query.asset_id != self.asset.asset_id
            or query.owner_user_id != self.asset.owner_user_id
            or query.conversation_id != self.asset.conversation_id
        ):
            raise ChatAssetStoreRejectedError(operation="get_asset", status_code=404)
        return self.asset

    async def finalize_upload(
        self, command: ChatAssetFinalizeCommandDTO
    ) -> ChatAssetDTO:
        del command
        return self.asset

    async def prepare_binding(
        self, command: ChatAssetBindingPrepareCommandDTO
    ) -> ChatAssetBindingResultDTO:
        self.prepares.append(command)
        if self.prepared_client_message_id is None:
            self.prepared_client_message_id = command.client_message_id
        elif self.prepared_client_message_id != command.client_message_id:
            raise ChatAssetStoreConflictError(operation="prepare_binding")
        return ChatAssetBindingResultDTO(
            asset=self.asset,
            binding_status=(
                "committed" if self.committed_record_id is not None else "prepared"
            ),
        )

    async def commit_binding(
        self, command: ChatAssetBindingCommitCommandDTO
    ) -> ChatAssetBindingResultDTO:
        self.commits.append(command)
        if (
            self.prepared_client_message_id != command.client_message_id
            or (
                self.committed_record_id is not None
                and self.committed_record_id != command.record_id
            )
        ):
            raise ChatAssetStoreConflictError(operation="commit_binding")
        if self.fail_commit_once and len(self.commits) == 1:
            raise ChatAssetStoreUnavailableError(operation="commit_binding")
        self.committed_record_id = command.record_id
        return ChatAssetBindingResultDTO(asset=self.asset, binding_status="committed")

    async def create_download_intent(
        self, command: ChatAssetDownloadRequestDTO
    ) -> ChatAssetDownloadIntentDTO:
        self.downloads.append(command)
        return ChatAssetDownloadIntentDTO(
            opaque_ticket=DOWNLOAD_TICKET,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )

    async def inspect_transfer(
        self, command: ChatAssetTransferInspectDTO
    ) -> ChatAssetTransferInspectionDTO:
        self.inspections.append(command)
        if self.transfer is None:
            raise ChatAssetStoreRejectedError(
                operation="inspect_transfer", status_code=404
            )
        return self.transfer


class FakeRecordStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], ChatRecordDTO] = {}
        self.appends: list[ChatRecordAppendDTO] = []
        self.exact_queries: list[tuple[str, str, str]] = []

    async def append_record(self, command: ChatRecordAppendDTO) -> ChatRecordDTO:
        self.appends.append(command)
        key = (command.sender_user_id, command.client_message_id)
        existing = self.records.get(key)
        if existing is not None:
            return existing
        record = ChatRecordDTO(
            record_id=f"record-{len(self.records) + 1}",
            client_message_id=command.client_message_id,
            conversation_id=command.conversation_id,
            sequence=len(self.records) + 1,
            sender_user_id=command.sender_user_id,
            recipient_user_ids=command.recipient_user_ids,
            content_type=command.content_type,
            content=command.content,
            status="sent",
            created_at=command.created_at,
            persisted_at=datetime.now(UTC),
            sender_org_id=command.sender_org_id,
            recipient_org_ids=command.recipient_org_ids,
            metadata=command.metadata,
            assets=command.assets,
        )
        self.records[key] = record
        return record

    async def get_authorized_record(
        self,
        *,
        conversation_id: str,
        record_id: str,
        user_id: str,
    ) -> ChatRecordDTO:
        self.exact_queries.append((conversation_id, record_id, user_id))
        for record in self.records.values():
            if (
                record.conversation_id == conversation_id
                and record.record_id == record_id
                and (
                    record.sender_user_id == user_id
                    or user_id in record.recipient_user_ids
                )
            ):
                return record
        raise ChatRecordStoreRejectedError(
            operation="get_authorized_record", status_code=404
        )


@pytest.fixture
def runtime_db(tmp_path: Path) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'c19-assets.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            OrganizationRecord.__table__,
            OrgMembershipRecord.__table__,
            C19ProfileRecord.__table__,
            C19AffiliationRecord.__table__,
            C19UserBlockRecord.__table__,
            C19ConversationRecord.__table__,
            C19ConversationMemberRecord.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    now = datetime.now(UTC)
    with factory() as db:
        db.add_all(
            [
                OrganizationRecord(
                    org_id=ORG_ONE,
                    name="One",
                    org_type="company",
                    owner_user_id="1",
                    status="active",
                    metadata_json={},
                ),
                OrganizationRecord(
                    org_id=ORG_TWO,
                    name="Two",
                    org_type="company",
                    owner_user_id="2",
                    status="active",
                    metadata_json={},
                ),
            ]
        )
        db.add_all(
            [
                User(
                    id=user_id,
                    username=f"asset-user-{user_id}",
                    password_hash="unused",
                    role="admin" if user_id == 3 else "member",
                    organization_id=ORG_ONE if user_id == 1 else ORG_TWO,
                    must_change_password=False,
                    is_active=True,
                )
                for user_id in (1, 2, 3)
            ]
        )
        db.flush()
        for user_id in (1, 2, 3):
            org_id = ORG_ONE if user_id == 1 else ORG_TWO
            db.add(
                OrgMembershipRecord(
                    membership_id=f"asset-membership-{user_id}",
                    user_id=str(user_id),
                    org_id=org_id,
                    role="member",
                    status="active",
                    joined_at=now,
                )
            )
            db.add(C19ProfileRecord(user_id=user_id, display_name=f"User {user_id}"))
        db.add(
            OrgMembershipRecord(
                membership_id="asset-membership-1-secondary",
                user_id="1",
                org_id=ORG_TWO,
                role="member",
                status="active",
                joined_at=now,
            )
        )
        db.flush()
        for user_id in (1, 2, 3):
            org_id = ORG_ONE if user_id == 1 else ORG_TWO
            db.add(
                C19AffiliationRecord(
                    affiliation_id=f"asset-affiliation-{user_id}",
                    user_id=user_id,
                    org_id=org_id,
                    source_membership_id=f"asset-membership-{user_id}",
                    role="member",
                    status="active",
                    joined_at=now,
                )
            )
        # User 1 has another valid affiliation. Conversation authorization must
        # still use the affiliation explicitly captured by membership.
        db.add(
            C19AffiliationRecord(
                affiliation_id="asset-affiliation-1-secondary",
                user_id=1,
                org_id=ORG_TWO,
                source_membership_id="asset-membership-1-secondary",
                role="member",
                status="active",
                joined_at=now,
            )
        )
        db.flush()
        db.add(
            C19ConversationRecord(
                conversation_id=CONVERSATION_ID,
                conversation_type="direct",
                direct_pair_key="1:2",
                created_by_user_id=1,
                status="active",
            )
        )
        db.flush()
        db.add_all(
            [
                C19ConversationMemberRecord(
                    conversation_id=CONVERSATION_ID,
                    affiliation_id=f"asset-affiliation-{user_id}",
                    user_id=user_id,
                    org_id_at_join=ORG_ONE if user_id == 1 else ORG_TWO,
                    role="member",
                    status="active",
                    joined_at=now,
                )
                for user_id in (1, 2)
            ]
        )
        db.commit()
    yield engine, factory
    engine.dispose()


def _actor(db: Session, user_id: int) -> User:
    actor = db.get(User, user_id)
    assert actor is not None
    return actor


def _image_message() -> MessageCreateRequest:
    return MessageCreateRequest(
        client_message_id="browser-message-asset-1",
        content_type="image",
        content="",
        asset={"asset_id": ASSET_ID},
    )


def test_asset_public_schemas_enforce_filename_type_size_and_one_asset() -> None:
    valid = ChatAssetUploadIntentRequest(
        client_asset_id="browser-asset-1",
        kind="image",
        filename="商品证明.jpg",
        media_type="image/jpeg",
        size_bytes=1234,
        sha256_hex="b" * 64,
    )
    assert valid.filename == "商品证明.jpg"
    # Any non-executable file is admitted: known containers by their media
    # type, everything else as an opaque octet stream.
    for filename, media_type in (
        ("演示.mp4", "video/mp4"),
        ("报价.svg", "image/svg+xml"),
        ("图纸.dwg", "image/vnd.dwg"),
        ("无扩展名", "application/octet-stream"),
        ("模具.skp", "application/octet-stream"),
    ):
        admitted = ChatAssetUploadIntentRequest(
            client_asset_id="browser-asset-any",
            kind="file",
            filename=filename,
            media_type=media_type,
            size_bytes=200 * 1024 * 1024,
            sha256_hex="b" * 64,
        )
        assert admitted.media_type == media_type

    invalid_cases = (
        {"filename": "../proof.jpg"},
        {"filename": "safe.jpg\u202eevil.exe"},
        {"filename": "proof.svg", "media_type": "image/svg+xml"},
        {"filename": "setup.exe", "kind": "file", "media_type": "application/octet-stream"},
        {"filename": "proof.jpg", "kind": "file"},
        {"filename": "proof.jpg", "size_bytes": 32 * 1024 * 1024 + 1},
        {"filename": "demo.mp4", "kind": "file", "media_type": "video/mp4", "size_bytes": 200 * 1024 * 1024 + 1},
    )
    base = valid.model_dump()
    for updates in invalid_cases:
        with pytest.raises(ValidationError):
            ChatAssetUploadIntentRequest(**{**base, **updates})

    with pytest.raises(ValidationError):
        MessageCreateRequest(
            client_message_id="bad-text-asset",
            content_type="text",
            content="text",
            asset={"asset_id": ASSET_ID},
        )
    with pytest.raises(ValidationError):
        MessageCreateRequest(
            client_message_id="missing-image-asset",
            content_type="image",
            content="caption",
        )


def test_upload_derives_global_owner_and_conversation_across_organizations(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    payload = ChatAssetUploadIntentRequest(
        client_asset_id="browser-asset-1",
        kind="image",
        filename="proof.jpg",
        media_type="image/jpeg",
        size_bytes=1234,
        sha256_hex="b" * 64,
    )
    with factory() as db:
        result = asyncio.run(
            create_asset_upload_intent(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=payload,
                asset_store=asset_store,
            )
        )
    assert result.upload_locator == f"/api/backend/c19-assets/u/{UPLOAD_TICKET}"
    command = asset_store.uploads[0]
    assert command.owner_user_id == "1"
    assert command.conversation_id == CONVERSATION_ID
    assert not hasattr(command, "owner_org_id")


def test_admin_role_has_no_nonmember_asset_bypass(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    with factory() as db, pytest.raises(C19ChatAccessError):
        asyncio.run(
            create_asset_upload_intent(
                db,
                actor=_actor(db, 3),
                conversation_id=CONVERSATION_ID,
                payload=ChatAssetUploadIntentRequest(
                    client_asset_id="admin-cannot-bypass",
                    kind="image",
                    filename="proof.jpg",
                    media_type="image/jpeg",
                    size_bytes=1,
                    sha256_hex="b" * 64,
                ),
                asset_store=asset_store,
            )
        )
    assert asset_store.uploads == []


def test_active_upload_intent_replay_returns_state_without_a_new_ticket(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db

    class ActiveReplayStore(FakeAssetStore):
        async def create_upload_intent(
            self, metadata: ChatAssetUploadMetadataDTO
        ) -> ChatAssetUploadHandleDTO:
            self.uploads.append(metadata)
            return ChatAssetUploadHandleDTO(
                asset=self.asset,
                opaque_ticket=None,
                expires_at=None,
            )

    asset_store = ActiveReplayStore()
    with factory() as db:
        result = asyncio.run(
            create_asset_upload_intent(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=ChatAssetUploadIntentRequest(
                    client_asset_id="browser-asset-1",
                    kind="image",
                    filename="proof.jpg",
                    media_type="image/jpeg",
                    size_bytes=1234,
                    sha256_hex="b" * 64,
                ),
                asset_store=asset_store,
            )
        )
    assert result.asset.status == "active"
    assert result.upload_locator is result.expires_at is None


def test_asset_message_prepare_append_commit_and_replay_are_idempotent(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    record_store = FakeRecordStore()
    with factory() as db:
        first = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_image_message(),
                store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
        replay = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_image_message(),
                store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
    assert first.record_id == replay.record_id == "record-1"
    assert first.content == ""
    assert first.assets[0].asset_id == ASSET_ID
    assert len(record_store.records) == 1
    assert len(asset_store.prepares) == len(asset_store.commits) == 2
    assert asset_store.commits[-1].record_id == "record-1"
    assert record_store.appends[0].assets == (_reference(),)


def test_bind_crash_after_record_append_is_repaired_by_retry(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    asset_store.fail_commit_once = True
    record_store = FakeRecordStore()
    with factory() as db:
        with pytest.raises(ChatAssetStoreUnavailableError):
            asyncio.run(
                send_message(
                    db,
                    actor=_actor(db, 1),
                    conversation_id=CONVERSATION_ID,
                    payload=_image_message(),
                    store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )
        repaired = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_image_message(),
                store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
    assert repaired.record_id == "record-1"
    assert len(record_store.records) == 1
    assert [item.record_id for item in asset_store.commits] == ["record-1", "record-1"]


def test_access_intent_repairs_record_append_before_binding_commit(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    asset_store.fail_commit_once = True
    record_store = FakeRecordStore()
    with factory() as db:
        with pytest.raises(ChatAssetStoreUnavailableError):
            asyncio.run(
                send_message(
                    db,
                    actor=_actor(db, 1),
                    conversation_id=CONVERSATION_ID,
                    payload=_image_message(),
                    store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )
        persisted = next(iter(record_store.records.values()))

        # Simulate loss of every browser-memory retry value: the recipient knows
        # only the durable record and its immutable asset reference.
        intent = asyncio.run(
            create_asset_access_intent(
                db,
                actor=_actor(db, 2),
                conversation_id=CONVERSATION_ID,
                record_id=persisted.record_id,
                asset_id=ASSET_ID,
                payload=ChatAssetAccessIntentRequest(variant="thumbnail"),
                record_store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )

    assert intent.download_locator == f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}"
    assert len(record_store.records) == 1
    assert [command.client_message_id for command in asset_store.commits] == [
        persisted.client_message_id,
        persisted.client_message_id,
    ]
    assert [command.record_id for command in asset_store.commits] == [
        persisted.record_id,
        persisted.record_id,
    ]
    assert asset_store.committed_record_id == persisted.record_id
    assert len(asset_store.downloads) == 1


def test_access_intent_reconciliation_rejects_wrong_client_message_or_record(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    asset_store.fail_commit_once = True
    record_store = FakeRecordStore()
    with factory() as db:
        with pytest.raises(ChatAssetStoreUnavailableError):
            asyncio.run(
                send_message(
                    db,
                    actor=_actor(db, 1),
                    conversation_id=CONVERSATION_ID,
                    payload=_image_message(),
                    store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )
        persisted_key, persisted = next(iter(record_store.records.items()))
        record_store.records[persisted_key] = replace(
            persisted,
            client_message_id="client_msg_wrong",
        )
        with pytest.raises(C19AssetAccessError) as wrong_client:
            asyncio.run(
                create_asset_access_intent(
                    db,
                    actor=_actor(db, 2),
                    conversation_id=CONVERSATION_ID,
                    record_id=persisted.record_id,
                    asset_id=ASSET_ID,
                    payload=ChatAssetAccessIntentRequest(),
                    record_store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )
        assert wrong_client.value.status_code == 404
        with pytest.raises(HTTPException) as public_error:
            _raise_asset_error(db, wrong_client.value)
        assert public_error.value.status_code == 404
        assert public_error.value.detail == {
            "code": "c19_asset_unavailable",
            "message": "Asset is unavailable.",
        }
        assert asset_store.downloads == []

        record_store.records[persisted_key] = persisted
        repaired = asyncio.run(
            create_asset_access_intent(
                db,
                actor=_actor(db, 2),
                conversation_id=CONVERSATION_ID,
                record_id=persisted.record_id,
                asset_id=ASSET_ID,
                payload=ChatAssetAccessIntentRequest(),
                record_store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
        assert repaired.download_locator == f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}"
        asset_store.downloads.clear()

        wrong_record = replace(persisted, record_id="record-wrong")
        record_store.records[("duplicate", "record-wrong")] = wrong_record
        with pytest.raises(C19AssetAccessError) as wrong_record_error:
            asyncio.run(
                create_asset_access_intent(
                    db,
                    actor=_actor(db, 2),
                    conversation_id=CONVERSATION_ID,
                    record_id=wrong_record.record_id,
                    asset_id=ASSET_ID,
                    payload=ChatAssetAccessIntentRequest(),
                    record_store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )
        assert wrong_record_error.value.status_code == 404
    assert asset_store.downloads == []


def test_access_intent_requires_exact_record_audience_and_snapshot(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    record_store = FakeRecordStore()
    with factory() as db:
        sent = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_image_message(),
                store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
        intent = asyncio.run(
            create_asset_access_intent(
                db,
                actor=_actor(db, 2),
                conversation_id=CONVERSATION_ID,
                record_id=sent.record_id,
                asset_id=ASSET_ID,
                payload=ChatAssetAccessIntentRequest(variant="thumbnail"),
                record_store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
    assert intent.download_locator == f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}"
    assert record_store.exact_queries[-1] == (CONVERSATION_ID, "record-1", "2")
    command = asset_store.downloads[-1]
    assert command.owner_user_id == "1"
    assert command.reader_user_id == "2"
    assert command.variant == "thumbnail"
    assert command.disposition == "inline"


def test_later_member_cannot_read_prejoin_record(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    record_store = FakeRecordStore()
    with factory() as db:
        sent = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_image_message(),
                store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
        db.add(
            C19ConversationMemberRecord(
                conversation_id=CONVERSATION_ID,
                affiliation_id="asset-affiliation-3",
                user_id=3,
                org_id_at_join=ORG_TWO,
                role="member",
                status="active",
                joined_at=datetime.now(UTC),
            )
        )
        db.commit()
        with pytest.raises(ChatRecordStoreRejectedError) as captured:
            asyncio.run(
                create_asset_access_intent(
                    db,
                    actor=_actor(db, 3),
                    conversation_id=CONVERSATION_ID,
                    record_id=sent.record_id,
                    asset_id=ASSET_ID,
                    payload=ChatAssetAccessIntentRequest(),
                    record_store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )
    assert captured.value.status_code == 404
    assert asset_store.downloads == []


def test_transfer_authorization_accepts_only_exact_ticket_paths_and_actor(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    record_store = FakeRecordStore()
    asset_store.transfer = ChatAssetTransferInspectionDTO(
        asset_id=ASSET_ID,
        owner_user_id="1",
        reader_user_id=None,
        conversation_id=CONVERSATION_ID,
        record_id=None,
        variant=None,
        version=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    with factory() as db:
        approved = asyncio.run(
            authorize_asset_transfer(
                db,
                actor=_actor(db, 1),
                transfer_uri=f"/api/backend/c19-assets/u/{UPLOAD_TICKET}",
                transfer_method="PUT",
                record_store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
        assert approved.owner_user_id == "1"
        for uri, method in (
            (f"/api/c19-assets/u/{UPLOAD_TICKET}", "PUT"),
            (f"/api/backend/c19-assets/u/{UPLOAD_TICKET}?x=1", "PUT"),
            (f"/api/backend/c19-assets/u/{UPLOAD_TICKET}/extra", "PUT"),
            (f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}", "PUT"),
            (f"/api/backend/c19-assets/u/{UPLOAD_TICKET}", "put"),
        ):
            with pytest.raises(C19AssetAccessError):
                asyncio.run(
                    authorize_asset_transfer(
                        db,
                        actor=_actor(db, 1),
                        transfer_uri=uri,
                        transfer_method=method,
                        record_store=record_store,  # type: ignore[arg-type]
                        asset_store=asset_store,  # type: ignore[arg-type]
                    )
                )
    assert len(asset_store.inspections) == 1


def test_download_transfer_rechecks_membership_reader_and_record_visibility(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    record_store = FakeRecordStore()
    with factory() as db:
        sent = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_image_message(),
                store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
        asset_store.transfer = ChatAssetTransferInspectionDTO(
            asset_id=ASSET_ID,
            owner_user_id="1",
            reader_user_id="2",
            conversation_id=CONVERSATION_ID,
            record_id=sent.record_id,
            variant="thumbnail",
            version=1,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        asyncio.run(
            authorize_asset_transfer(
                db,
                actor=_actor(db, 2),
                transfer_uri=f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}",
                transfer_method="GET",
                record_store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
        member = next(
            item
            for item in db.query(C19ConversationMemberRecord).all()
            if item.user_id == 2
        )
        member.status = "left"
        member.left_at = datetime.now(UTC)
        db.commit()
        with pytest.raises(C19ChatAccessError):
            asyncio.run(
                authorize_asset_transfer(
                    db,
                    actor=_actor(db, 2),
                    transfer_uri=f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}",
                    transfer_method="HEAD",
                    record_store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )


def test_deleted_asset_and_revoked_transfer_ticket_fail_closed(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    asset_store = FakeAssetStore()
    record_store = FakeRecordStore()
    with factory() as db:
        sent = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_image_message(),
                store=record_store,  # type: ignore[arg-type]
                asset_store=asset_store,  # type: ignore[arg-type]
            )
        )
        asset_store.asset = _asset(status="deleted")
        with pytest.raises(C19AssetAccessError):
            asyncio.run(
                create_asset_access_intent(
                    db,
                    actor=_actor(db, 2),
                    conversation_id=CONVERSATION_ID,
                    record_id=sent.record_id,
                    asset_id=ASSET_ID,
                    payload=ChatAssetAccessIntentRequest(),
                    record_store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )
        assert asset_store.downloads == []

        # A deleted asset revokes its ticket in the Asset Service. Barong must
        # propagate that opaque rejection and never manufacture authorization.
        asset_store.transfer = None
        with pytest.raises(ChatAssetStoreRejectedError):
            asyncio.run(
                authorize_asset_transfer(
                    db,
                    actor=_actor(db, 2),
                    transfer_uri=f"/api/backend/c19-assets/d/{DOWNLOAD_TICKET}",
                    transfer_method="GET",
                    record_store=record_store,  # type: ignore[arg-type]
                    asset_store=asset_store,  # type: ignore[arg-type]
                )
            )


@pytest.mark.parametrize(
    "base_url",
    (
        "http://asset.example.com",
        "ftp://c19-asset-api",
        "https://user:pass@asset.example.com",
        "https://asset.example.com/path",
        "https://asset.example.com?token=bad",
        "http://c19-asset-api:invalid",
        "http://c19-asset-api:0",
    ),
)
def test_asset_http_config_rejects_unsafe_provider_urls(base_url: str) -> None:
    with pytest.raises(ValueError):
        HttpChatAssetStoreConfig(base_url=base_url, token="t" * 32)


def test_asset_http_config_allows_private_http_public_https_and_redacts_token() -> None:
    token = "secret-asset-token-that-is-long-enough"
    private = HttpChatAssetStoreConfig(
        base_url="http://c19-asset-api:8091", token=token
    )
    public = HttpChatAssetStoreConfig(
        base_url="https://assets-control.example.com", token=token
    )
    assert private.base_url.startswith("http://")
    assert public.base_url.startswith("https://")
    assert token not in repr(private)
    assert token not in repr(public)


def _asset_json(*, status: str = "active") -> dict[str, object]:
    asset = _asset(status=status)
    return {
        "asset_id": asset.asset_id,
        "client_asset_id": asset.client_asset_id,
        "owner_user_id": asset.owner_user_id,
        "conversation_id": asset.conversation_id,
        "kind": asset.kind,
        "filename": asset.filename,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "sha256_hex": asset.sha256_hex,
        "version": asset.version,
        "status": asset.status,
    }


def test_asset_http_adapter_matches_strict_control_contract() -> None:
    requests: list[httpx.Request] = []
    expires = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == "/v1/upload-intents":
            return httpx.Response(
                201,
                json={
                    "asset": {**_asset_json(status="pending_upload"), **{
                        "client_asset_id": body["client_asset_id"],
                    }},
                    "upload_ticket": UPLOAD_TICKET,
                    "expires_at": expires,
                },
            )
        if path.endswith("/bindings/prepare"):
            return httpx.Response(
                200, json={"asset": _asset_json(), "binding_status": "prepared"}
            )
        if path.endswith("/bindings/commit"):
            return httpx.Response(
                200, json={"asset": _asset_json(), "binding_status": "committed"}
            )
        if path.endswith("/download-intents"):
            return httpx.Response(
                201,
                json={"download_ticket": DOWNLOAD_TICKET, "expires_at": expires},
            )
        if path == "/v1/transfers/inspect":
            return httpx.Response(
                200,
                json={
                    "asset_id": ASSET_ID,
                    "owner_user_id": "1",
                    "reader_user_id": "2",
                    "conversation_id": CONVERSATION_ID,
                    "record_id": "record-1",
                    "variant": "thumbnail",
                    "version": 1,
                    "expires_at": expires,
                },
            )
        return httpx.Response(200, json=_asset_json())

    async def run() -> None:
        async with HttpChatAssetStore(
            HttpChatAssetStoreConfig(
                base_url="http://c19-asset-api:8091", token="t" * 32
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            upload = await store.create_upload_intent(
                ChatAssetUploadMetadataDTO(
                    client_asset_id="browser-asset-1",
                    owner_user_id="1",
                    conversation_id=CONVERSATION_ID,
                    kind="image",
                    filename="proof.jpg",
                    media_type="image/jpeg",
                    size_bytes=1234,
                    sha256_hex="b" * 64,
                    requested_at=datetime.now(UTC),
                )
            )
            assert upload.opaque_ticket == UPLOAD_TICKET
            await store.get_asset(
                ChatAssetLookupDTO(ASSET_ID, "1", CONVERSATION_ID)
            )
            await store.finalize_upload(
                ChatAssetFinalizeCommandDTO(ASSET_ID, "1", CONVERSATION_ID)
            )
            await store.prepare_binding(
                ChatAssetBindingPrepareCommandDTO(
                    ASSET_ID, "1", CONVERSATION_ID, "browser-message-asset-1"
                )
            )
            await store.commit_binding(
                ChatAssetBindingCommitCommandDTO(
                    ASSET_ID,
                    "1",
                    CONVERSATION_ID,
                    "browser-message-asset-1",
                    "record-1",
                )
            )
            await store.create_download_intent(
                ChatAssetDownloadRequestDTO(
                    ASSET_ID,
                    "1",
                    "2",
                    CONVERSATION_ID,
                    "record-1",
                    "thumbnail",
                    "inline",
                    1,
                )
            )
            inspected = await store.inspect_transfer(
                ChatAssetTransferInspectDTO(DOWNLOAD_TICKET, "download", "GET")
            )
            assert inspected.reader_user_id == "2"

    asyncio.run(run())
    assert all(
        request.headers["authorization"] == f"Bearer {'t' * 32}"
        for request in requests
    )
    assert requests[0].url == httpx.URL(
        "http://c19-asset-api:8091/v1/upload-intents"
    )
    assert all(ASSET_ID not in request.content.decode() for request in requests[:1])


def test_asset_http_adapter_rejects_extra_or_malformed_response_fields() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**_asset_json(), "object_key": "leak"})

    async def run() -> None:
        async with HttpChatAssetStore(
            HttpChatAssetStoreConfig(
                base_url="http://c19-asset-api:8091", token="t" * 32
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            with pytest.raises(ChatAssetStoreProtocolError):
                await store.get_asset(
                    ChatAssetLookupDTO(ASSET_ID, "1", CONVERSATION_ID)
                )

    asyncio.run(run())


def test_asset_http_adapter_accepts_safe_idempotent_replay_shapes() -> None:
    expires = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/upload-intents":
            return httpx.Response(
                200,
                json={
                    "asset": _asset_json(),
                    "upload_ticket": None,
                    "expires_at": None,
                },
            )
        return httpx.Response(
            200,
            json={"asset": _asset_json(), "binding_status": "committed"},
            headers={"Expires": expires},
        )

    async def run() -> None:
        async with HttpChatAssetStore(
            HttpChatAssetStoreConfig(
                base_url="http://c19-asset-api:8091", token="t" * 32
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            replay = await store.create_upload_intent(
                ChatAssetUploadMetadataDTO(
                    client_asset_id="browser-asset-1",
                    owner_user_id="1",
                    conversation_id=CONVERSATION_ID,
                    kind="image",
                    filename="proof.jpg",
                    media_type="image/jpeg",
                    size_bytes=1234,
                    sha256_hex="b" * 64,
                    requested_at=datetime.now(UTC),
                )
            )
            assert replay.opaque_ticket is replay.expires_at is None
            prepared_replay = await store.prepare_binding(
                ChatAssetBindingPrepareCommandDTO(
                    ASSET_ID,
                    "1",
                    CONVERSATION_ID,
                    "browser-message-asset-1",
                )
            )
            assert prepared_replay.binding_status == "committed"

    asyncio.run(run())


@pytest.mark.parametrize(
    ("status", "error_type"),
    (
        (401, ChatAssetStoreAuthenticationError),
        (409, ChatAssetStoreConflictError),
        (410, ChatAssetStoreRejectedError),
        (413, ChatAssetStoreRejectedError),
        (429, ChatAssetStoreQuotaError),
        (503, ChatAssetStoreUnavailableError),
    ),
)
def test_asset_http_adapter_has_stable_status_mapping(
    status: int,
    error_type: type[Exception],
) -> None:
    async def run() -> None:
        async with HttpChatAssetStore(
            HttpChatAssetStoreConfig(
                base_url="http://c19-asset-api:8091", token="t" * 32
            ),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, json={"detail": "never leak"})
            ),
        ) as store:
            with pytest.raises(error_type) as captured:
                await store.get_asset(
                    ChatAssetLookupDTO(ASSET_ID, "1", CONVERSATION_ID)
                )
            assert "never leak" not in str(captured.value)

    asyncio.run(run())


def test_asset_provider_and_capability_fail_closed_or_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert build_chat_asset_store({}).capability.configured is False
    assert build_chat_asset_store(
        {
            "C19_ASSET_STORE_URL": "http://public.example.com",
            "C19_ASSET_STORE_TOKEN": "t" * 32,
        }
    ).capability.configured is False
    configured = build_chat_asset_store(
        {
            "C19_ASSET_STORE_URL": "http://c19-asset-api:8091",
            "C19_ASSET_STORE_TOKEN": "t" * 32,
        }
    )
    assert configured.capability.configured is True
    assert isinstance(configured, ChatAssetStore)
    asyncio.run(configured.aclose())  # type: ignore[attr-defined]

    monkeypatch.setenv("C19_ASSET_STORE_URL", "http://c19-asset-api:8091")
    monkeypatch.setenv("C19_ASSET_STORE_TOKEN", "t" * 32)
    assert get_c19_storage_capabilities().asset_store.configured is True


def test_asset_routes_are_control_plane_only_and_registered() -> None:
    routes = {
        (method, route.path)
        for route in asset_router.routes
        for method in route.methods
    }
    assert routes == {
        (
            "POST",
            "/c19/conversations/{conversation_id}/assets/upload-intents",
        ),
        (
            "POST",
            "/c19/conversations/{conversation_id}/assets/{asset_id}/finalize",
        ),
        ("GET", "/c19/conversations/{conversation_id}/assets/{asset_id}"),
        (
            "POST",
            "/c19/conversations/{conversation_id}/records/{record_id}/assets/{asset_id}/access-intents",
        ),
        ("GET", "/c19/assets/transfers/authorize"),
    }
    aggregate = {
        (method, route.path)
        for route in aggregate_router.routes
        for method in route.methods
    }
    assert routes <= aggregate
    assert all("/api/backend/c19-assets/" not in path for _, path in aggregate)
