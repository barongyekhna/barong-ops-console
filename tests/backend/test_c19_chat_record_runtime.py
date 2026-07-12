from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
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
from backend.app.modules.c19.http_record_store import (
    ChatRecordStoreConflictError,
    ChatRecordStoreProtocolError,
    ChatRecordStoreRejectedError,
    HttpChatRecordStore,
    HttpChatRecordStoreConfig,
)
from backend.app.modules.c19.message_router import (
    _raise_chat_error,
    router,
    user_events_endpoint,
)
from backend.app.modules.c19.message_schemas import MessageCreateRequest
from backend.app.modules.c19.message_service import (
    C19ChatAccessError,
    advance_message_position,
    get_resume,
    get_user_event_tail,
    get_unread,
    get_unread_summary,
    list_message_history,
    list_user_events,
    send_message,
)
from backend.app.modules.c19.record_store_provider import build_chat_record_store
from backend.app.modules.c19.router import router as aggregate_c19_router
from backend.app.modules.c19.storage import (
    CHAT_RECORD_STORE_OPERATIONS,
    C19StorageUnconfiguredError,
    ChatPositionAdvanceDTO,
    ChatPositionQueryDTO,
    ChatReceiptPositionDTO,
    ChatRecordAppendDTO,
    ChatRecordDTO,
    ChatRecordDeleteCommandDTO,
    ChatRecordMutationResultDTO,
    ChatRecordPageDTO,
    ChatRecordQueryDTO,
    ChatResumePositionDTO,
    ChatRetentionBatchCommandDTO,
    ChatRetentionBatchResultDTO,
    ChatUnreadPositionDTO,
    ChatUnreadSummaryDTO,
    ChatUnreadSummaryQueryDTO,
    ChatUserEventDTO,
    ChatUserEventPageDTO,
    ChatUserEventQueryDTO,
    ChatUserEventTailDTO,
    StorageCapabilityDescription,
    get_c19_storage_capabilities,
)


pytestmark = pytest.mark.unit

ORG_ONE = "org_" + "1" * 32
ORG_TWO = "org_" + "2" * 32
CONVERSATION_ID = "c19_direct_test"


class FakeExternalRecordStore:
    """Test double for external persistence; it never receives a DB session."""

    def __init__(self) -> None:
        self.append_attempts: list[ChatRecordAppendDTO] = []
        self.records: dict[tuple[str, str], tuple[ChatRecordAppendDTO, ChatRecordDTO]] = {}
        self.unread_summary_queries: list[ChatUnreadSummaryQueryDTO] = []

    @property
    def capability(self) -> StorageCapabilityDescription:
        return StorageCapabilityDescription(
            store_name="chat_record_store",
            status="configured",
            configured=True,
            readable=True,
            writable=True,
            durable=True,
            external_io_enabled=True,
            operations=CHAT_RECORD_STORE_OPERATIONS,
            reason="fake external store",
        )

    @staticmethod
    def _semantic(command: ChatRecordAppendDTO) -> tuple[object, ...]:
        return (
            command.conversation_id,
            command.sender_user_id,
            command.content_type,
            command.content,
            command.metadata,
            command.assets,
        )

    async def append_record(self, record: ChatRecordAppendDTO) -> ChatRecordDTO:
        self.append_attempts.append(record)
        key = (record.sender_user_id, record.client_message_id)
        existing = self.records.get(key)
        if existing is not None:
            assert self._semantic(existing[0]) == self._semantic(record)
            return existing[1]
        persisted = ChatRecordDTO(
            record_id=f"record-{len(self.records) + 1}",
            client_message_id=record.client_message_id,
            conversation_id=record.conversation_id,
            sequence=len(self.records) + 1,
            sender_user_id=record.sender_user_id,
            recipient_user_ids=record.recipient_user_ids,
            content_type=record.content_type,
            content=record.content,
            status="sent",
            created_at=record.created_at,
            persisted_at=datetime.now(UTC),
            sender_org_id=record.sender_org_id,
            recipient_org_ids=record.recipient_org_ids,
            metadata=record.metadata,
            assets=record.assets,
        )
        self.records[key] = (record, persisted)
        return persisted

    async def get_authorized_record(
        self,
        *,
        conversation_id: str,
        record_id: str,
        user_id: str,
    ) -> ChatRecordDTO:
        for _, record in self.records.values():
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
            operation="get_authorized_record",
            status_code=404,
        )

    async def list_records(self, query: ChatRecordQueryDTO) -> ChatRecordPageDTO:
        records = tuple(
            item[1]
            for item in self.records.values()
            if item[1].conversation_id == query.conversation_id
        )
        return ChatRecordPageDTO(
            records=records[: query.limit],
            next_cursor=None,
            latest_sequence=max((item.sequence for item in records), default=0),
        )

    async def list_user_events(
        self,
        query: ChatUserEventQueryDTO,
    ) -> ChatUserEventPageDTO:
        now = datetime.now(UTC)
        return ChatUserEventPageDTO(
            events=(
                ChatUserEventDTO(
                    event_id="event-1",
                    user_id=query.user_id,
                    conversation_id=CONVERSATION_ID,
                    record_id="record-1",
                    record_sequence=1,
                    event_sequence=1,
                    created_at=now,
                ),
                ChatUserEventDTO(
                    event_id="event-hidden",
                    user_id=query.user_id,
                    conversation_id="not-a-current-conversation",
                    record_id="record-hidden",
                    record_sequence=1,
                    event_sequence=2,
                    created_at=now,
                ),
            ),
            next_cursor="opaque-next",
            latest_event_sequence=2,
        )

    async def get_user_event_tail(self, user_id: str) -> ChatUserEventTailDTO:
        return ChatUserEventTailDTO(
            user_id=user_id,
            cursor="opaque-tail",
            latest_event_sequence=2,
        )

    async def advance_delivery(
        self,
        command: ChatPositionAdvanceDTO,
    ) -> ChatReceiptPositionDTO:
        return ChatReceiptPositionDTO(
            conversation_id=command.conversation_id,
            user_id=command.user_id,
            delivered_through_sequence=command.through_sequence,
            read_through_sequence=0,
            updated_at=command.occurred_at,
        )

    async def advance_read(
        self,
        command: ChatPositionAdvanceDTO,
    ) -> ChatReceiptPositionDTO:
        return ChatReceiptPositionDTO(
            conversation_id=command.conversation_id,
            user_id=command.user_id,
            delivered_through_sequence=command.through_sequence,
            read_through_sequence=command.through_sequence,
            updated_at=command.occurred_at,
        )

    async def get_unread_position(
        self,
        query: ChatPositionQueryDTO,
    ) -> ChatUnreadPositionDTO:
        return ChatUnreadPositionDTO(
            conversation_id=query.conversation_id,
            user_id=query.user_id,
            unread_count=1,
            first_unread_sequence=1,
            latest_sequence=1,
        )

    async def get_unread_summary(
        self,
        query: ChatUnreadSummaryQueryDTO,
    ) -> ChatUnreadSummaryDTO:
        self.unread_summary_queries.append(query)
        return ChatUnreadSummaryDTO(
            total_unread_count=len(query.conversation_ids) * 2,
            unread_conversation_count=len(query.conversation_ids),
        )

    async def get_resume_position(
        self,
        query: ChatPositionQueryDTO,
    ) -> ChatResumePositionDTO:
        return ChatResumePositionDTO(
            conversation_id=query.conversation_id,
            user_id=query.user_id,
            resume_cursor="opaque-resume",
            delivered_through_sequence=0,
            read_through_sequence=0,
            latest_sequence=1,
        )

    async def delete_records(
        self,
        command: ChatRecordDeleteCommandDTO,
    ) -> ChatRecordMutationResultDTO:
        del command
        return ChatRecordMutationResultDTO(0, datetime.now(UTC))

    async def apply_retention_batch(
        self,
        command: ChatRetentionBatchCommandDTO,
    ) -> ChatRetentionBatchResultDTO:
        del command
        return ChatRetentionBatchResultDTO(
            operation_id="rtn_" + "a" * 64,
            batch_ordinal=0,
            affected_count=0,
            cumulative_affected_count=0,
            operation_complete=True,
            completed_at=datetime.now(UTC),
        )


@pytest.fixture
def runtime_db(tmp_path: Path) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'c19-chat.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        User.__table__,
        OrganizationRecord.__table__,
        OrgMembershipRecord.__table__,
        C19ProfileRecord.__table__,
        C19AffiliationRecord.__table__,
        C19UserBlockRecord.__table__,
        C19ConversationRecord.__table__,
        C19ConversationMemberRecord.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
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
                    username=f"user-{user_id}",
                    password_hash="unused",
                    role="member",
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
                    membership_id=f"membership-{user_id}",
                    user_id=str(user_id),
                    org_id=org_id,
                    role="member",
                    status="active",
                    joined_at=now,
                )
            )
            db.add(C19ProfileRecord(user_id=user_id, display_name=f"User {user_id}"))
        db.flush()
        for user_id in (1, 2, 3):
            org_id = ORG_ONE if user_id == 1 else ORG_TWO
            db.add(
                C19AffiliationRecord(
                    affiliation_id=f"affiliation-{user_id}",
                    user_id=user_id,
                    org_id=org_id,
                    source_membership_id=f"membership-{user_id}",
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
                    affiliation_id=f"affiliation-{user_id}",
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


def _message() -> MessageCreateRequest:
    return MessageCreateRequest(
        client_message_id="web-client-message-1",
        content_type="text",
        content="external only",
    )


def test_router_contract_and_metadata_have_no_local_message_storage() -> None:
    routes = {
        (method, route.path)
        for route in router.routes
        for method in route.methods
    }
    assert routes == {
        ("POST", "/c19/conversations/{conversation_id}/messages"),
        ("GET", "/c19/conversations/{conversation_id}/messages"),
        ("POST", "/c19/conversations/{conversation_id}/delivered"),
        ("POST", "/c19/conversations/{conversation_id}/read"),
        ("GET", "/c19/conversations/{conversation_id}/unread"),
        ("GET", "/c19/conversations/{conversation_id}/resume"),
        ("GET", "/c19/unread"),
        ("GET", "/c19/events"),
        ("GET", "/c19/events/tail"),
    }
    aggregate_routes = {
        (method, route.path)
        for route in aggregate_c19_router.routes
        for method in route.methods
    }
    assert routes <= aggregate_routes
    local_tables = set(Base.metadata.tables)
    assert {
        "c19_messages",
        "c19_message_records",
        "c19_read_cursors",
        "c19_user_events",
    }.isdisjoint(local_tables)


def test_send_is_store_backed_idempotent_and_derives_recipients(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    store = FakeExternalRecordStore()
    with factory() as db:
        first = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_message(),
                store=store,
            )
        )
        second = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_message(),
                store=store,
            )
        )

    assert first.record_id == second.record_id == "record-1"
    assert len(store.append_attempts) == 2
    assert len(store.records) == 1
    sent = store.append_attempts[0]
    assert sent.sender_user_id == "1"
    assert sent.recipient_user_ids == ("2",)
    assert sent.sender_org_id == ORG_ONE
    assert sent.recipient_org_ids == (ORG_TWO,)


def test_affiliation_free_members_can_send_and_receive_messages(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    store = FakeExternalRecordStore()
    conversation_id = "c19_direct_native_users"
    now = datetime.now(UTC)
    with factory() as db:
        db.add_all(
            [
                User(
                    id=user_id,
                    username=f"native-chat-{user_id}",
                    password_hash="unused",
                    role=role,
                    organization_id=None,
                    must_change_password=False,
                    is_active=True,
                )
                for user_id, role in ((4, "viewer"), (5, "custom-role"))
            ]
        )
        db.flush()
        db.add_all(
            [
                C19ProfileRecord(user_id=user_id, display_name=f"Native {user_id}")
                for user_id in (4, 5)
            ]
        )
        db.flush()
        db.add(
            C19ConversationRecord(
                conversation_id=conversation_id,
                conversation_type="direct",
                direct_pair_key="4:5",
                created_by_user_id=4,
                status="active",
            )
        )
        db.flush()
        db.add_all(
            [
                C19ConversationMemberRecord(
                    conversation_id=conversation_id,
                    affiliation_id=None,
                    user_id=user_id,
                    org_id_at_join=None,
                    role="member",
                    status="active",
                    joined_at=now,
                )
                for user_id in (4, 5)
            ]
        )
        db.commit()

        sent = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 4),
                conversation_id=conversation_id,
                payload=_message().model_copy(
                    update={"client_message_id": "native-message-1"}
                ),
                store=store,
            )
        )

    assert sent.sender_user_id == "4"
    assert sent.recipient_user_ids == ["5"]
    assert sent.sender_org_id is None
    assert sent.recipient_org_ids == []


def test_unconfigured_store_and_access_denials_never_fake_success(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    fake = FakeExternalRecordStore()
    unconfigured = build_chat_record_store({})
    with factory() as db:
        with pytest.raises(C19StorageUnconfiguredError):
            asyncio.run(
                send_message(
                    db,
                    actor=_actor(db, 1),
                    conversation_id=CONVERSATION_ID,
                    payload=_message(),
                    store=unconfigured,
                )
            )

        with pytest.raises(C19ChatAccessError):
            asyncio.run(
                send_message(
                    db,
                    actor=_actor(db, 3),
                    conversation_id=CONVERSATION_ID,
                    payload=_message(),
                    store=fake,
                )
            )
        db.rollback()

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
                send_message(
                    db,
                    actor=_actor(db, 2),
                    conversation_id=CONVERSATION_ID,
                    payload=_message(),
                    store=fake,
                )
            )

        db.rollback()
        member.status = "active"
        member.left_at = None
        db.add(
            C19UserBlockRecord(
                block_id="block-2-1",
                blocker_user_id=2,
                blocked_user_id=1,
                status="active",
                is_active=True,
                blocked_at=datetime.now(UTC),
                revoked_at=None,
            )
        )
        db.commit()
        with pytest.raises(C19ChatAccessError):
            asyncio.run(
                send_message(
                    db,
                    actor=_actor(db, 1),
                    conversation_id=CONVERSATION_ID,
                    payload=_message(),
                    store=fake,
                )
            )

        db.rollback()
        block = db.get(C19UserBlockRecord, "block-2-1")
        assert block is not None
        db.delete(block)
        conversation = db.get(C19ConversationRecord, CONVERSATION_ID)
        assert conversation is not None
        conversation.status = "closed"
        db.commit()
        with pytest.raises(C19ChatAccessError):
            asyncio.run(
                send_message(
                    db,
                    actor=_actor(db, 1),
                    conversation_id=CONVERSATION_ID,
                    payload=_message(),
                    store=fake,
                )
            )

    assert fake.append_attempts == []


def test_idempotent_group_replay_keeps_first_recipient_snapshot(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    group_id = "c19_group_test"
    store = FakeExternalRecordStore()
    now = datetime.now(UTC)
    with factory() as db:
        db.add(
            C19ConversationRecord(
                conversation_id=group_id,
                conversation_type="group",
                direct_pair_key=None,
                title="Replay group",
                created_by_user_id=1,
                status="active",
            )
        )
        db.flush()
        db.add_all(
            [
                C19ConversationMemberRecord(
                    conversation_id=group_id,
                    affiliation_id=f"affiliation-{user_id}",
                    user_id=user_id,
                    org_id_at_join=ORG_ONE if user_id == 1 else ORG_TWO,
                    role="owner" if user_id == 1 else "member",
                    status="active",
                    joined_at=now,
                )
                for user_id in (1, 2, 3)
            ]
        )
        db.commit()
        first = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=group_id,
                payload=_message(),
                store=store,
            )
        )
        third_membership = db.get(OrgMembershipRecord, "membership-3")
        assert third_membership is not None
        third_membership.status = "suspended"
        db.commit()
        replay = asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=group_id,
                payload=_message(),
                store=store,
            )
        )

    assert first.record_id == replay.record_id
    assert first.recipient_user_ids == replay.recipient_user_ids == ["2", "3"]
    assert first.recipient_org_ids == [ORG_TWO]
    assert store.append_attempts[0].recipient_org_ids == (ORG_TWO,)
    assert store.append_attempts[1].recipient_user_ids == ("2", "3")


def test_actor_keeps_history_when_peer_becomes_inactive_but_new_send_is_denied(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    store = FakeExternalRecordStore()
    with factory() as db:
        asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_message(),
                store=store,
            )
        )
        peer = db.get(User, 2)
        assert peer is not None
        peer.is_active = False
        db.commit()

        history = asyncio.run(
            list_message_history(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                limit=50,
                cursor=None,
                store=store,
            )
        )
        assert [record.record_id for record in history.records] == ["record-1"]

        with pytest.raises(C19ChatAccessError):
            asyncio.run(
                send_message(
                    db,
                    actor=_actor(db, 1),
                    conversation_id=CONVERSATION_ID,
                    payload=_message().model_copy(
                        update={"client_message_id": "web-client-message-2"}
                    ),
                    store=store,
                )
            )


def test_history_positions_and_events_are_scoped_to_current_member(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    store = FakeExternalRecordStore()
    with factory() as db:
        asyncio.run(
            send_message(
                db,
                actor=_actor(db, 1),
                conversation_id=CONVERSATION_ID,
                payload=_message(),
                store=store,
            )
        )
        history = asyncio.run(
            list_message_history(
                db,
                actor=_actor(db, 2),
                conversation_id=CONVERSATION_ID,
                limit=50,
                cursor=None,
                store=store,
            )
        )
        delivered = asyncio.run(
            advance_message_position(
                db,
                actor=_actor(db, 2),
                conversation_id=CONVERSATION_ID,
                through_sequence=1,
                position="delivery",
                store=store,
            )
        )
        read = asyncio.run(
            advance_message_position(
                db,
                actor=_actor(db, 2),
                conversation_id=CONVERSATION_ID,
                through_sequence=1,
                position="read",
                store=store,
            )
        )
        unread = asyncio.run(
            get_unread(
                db,
                actor=_actor(db, 2),
                conversation_id=CONVERSATION_ID,
                store=store,
            )
        )
        resume = asyncio.run(
            get_resume(
                db,
                actor=_actor(db, 2),
                conversation_id=CONVERSATION_ID,
                store=store,
            )
        )
        events = asyncio.run(
            list_user_events(
                db,
                actor=_actor(db, 2),
                limit=100,
                cursor=None,
                store=store,
            )
        )
        event_tail = asyncio.run(
            get_user_event_tail(
                db,
                actor=_actor(db, 2),
                store=store,
            )
        )

    assert [item.record_id for item in history.records] == ["record-1"]
    assert delivered.user_id == read.user_id == "2"
    assert unread.unread_count == 1
    assert resume.resume_cursor == "opaque-resume"
    assert [item.event_id for item in events.events] == ["event-1"]
    assert events.next_cursor == "opaque-next"
    assert event_tail.cursor == "opaque-tail"
    assert event_tail.latest_event_sequence == 2


def test_global_unread_uses_only_the_complete_active_membership_set(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    member_store = FakeExternalRecordStore()
    outsider_store = FakeExternalRecordStore()
    with factory() as db:
        member_summary = asyncio.run(
            get_unread_summary(db, actor=_actor(db, 1), store=member_store)
        )
        outsider_summary = asyncio.run(
            get_unread_summary(db, actor=_actor(db, 3), store=outsider_store)
        )

    assert member_summary.model_dump() == {
        "total_unread_count": 2,
        "unread_conversation_count": 1,
    }
    assert member_store.unread_summary_queries[0].conversation_ids == (
        CONVERSATION_ID,
    )
    assert outsider_summary.model_dump() == {
        "total_unread_count": 0,
        "unread_conversation_count": 0,
    }
    assert outsider_store.unread_summary_queries == []


def test_global_unread_chunks_every_membership_without_truncation(
    runtime_db: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = runtime_db
    store = FakeExternalRecordStore()
    conversation_ids = tuple(f"conversation-{index:04d}" for index in range(2501))
    monkeypatch.setattr(
        "backend.app.modules.c19.message_service.list_active_conversation_ids",
        lambda _db, *, user_id: conversation_ids if user_id == 1 else (),
    )

    with factory() as db:
        summary = asyncio.run(
            get_unread_summary(db, actor=_actor(db, 1), store=store)
        )

    assert summary.total_unread_count == 5002
    assert summary.unread_conversation_count == 2501
    assert [
        len(query.conversation_ids) for query in store.unread_summary_queries
    ] == [1000, 1000, 501]
    assert all(query.user_id == "1" for query in store.unread_summary_queries)


def test_event_endpoint_negotiates_content_free_sse_pages(
    runtime_db: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = runtime_db
    store = FakeExternalRecordStore()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/app/c19/events",
            "raw_path": b"/api/app/c19/events",
            "query_string": b"",
            "headers": [
                (b"accept", b"text/event-stream"),
                (b"x-session-token", b"test-sse-session"),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 443),
        },
        receive,
    )

    async def run(db: Session) -> tuple[StreamingResponse, str, str, str]:
        response = await user_events_endpoint(
            request=request,
            store=store,
            limit=100,
            cursor=None,
            db=db,
            actor=_actor(db, 2),
        )
        assert isinstance(response, StreamingResponse)
        iterator = response.body_iterator
        retry = await anext(iterator)
        first_page = await anext(iterator)
        second_page = await anext(iterator)
        await iterator.aclose()
        return response, retry, first_page, second_page

    with factory() as db:
        @contextmanager
        def live_session():
            yield db

        monkeypatch.setattr(
            "backend.app.modules.c19.message_router.build_chat_record_store",
            lambda: store,
        )
        monkeypatch.setattr(
            "backend.app.modules.c19.message_router.managed_read_session",
            live_session,
        )
        monkeypatch.setattr(
            "backend.app.modules.c19.message_router.validate_session",
            lambda *_args, **_kwargs: SimpleNamespace(user=_actor(db, 2)),
        )
        response, retry, event_page, next_event_page = asyncio.run(run(db))

    assert retry == "retry: 2000\n\n"
    assert event_page.startswith("data: ")
    payload = json.loads(event_page.removeprefix("data: ").strip())
    assert [event["event_id"] for event in payload["events"]] == ["event-1"]
    assert payload["next_cursor"] == "opaque-next"
    assert "content" not in event_page
    assert next_event_page.startswith("data: ")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


def test_http_adapter_matches_record_service_contract_and_redacts_token() -> None:
    token = "super-secret-record-token-at-least-32-bytes"
    requested: list[httpx.Request] = []
    now = datetime.now(UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                **body,
                "record_id": "record-http-1",
                "sequence": 1,
                "status": "sent",
                "persisted_at": now.isoformat(),
            },
        )

    config = HttpChatRecordStoreConfig(
        base_url="http://c19_record_service:8090",
        token=token,
        timeout_seconds=3,
    )
    assert token not in repr(config)
    command = ChatRecordAppendDTO(
        client_message_id="client-http-1",
        conversation_id=CONVERSATION_ID,
        sender_user_id="1",
        recipient_user_ids=("2",),
        content_type="text",
        content="not local",
        created_at=now,
        sender_org_id=ORG_ONE,
        recipient_org_ids=(ORG_TWO,),
    )

    async def run() -> ChatRecordDTO:
        async with HttpChatRecordStore(
            config,
            transport=httpx.MockTransport(handler),
        ) as store:
            return await store.append_record(command)

    result = asyncio.run(run())
    assert result.record_id == "record-http-1"
    assert requested[0].url == httpx.URL(
        "http://c19_record_service:8090/v1/records"
    )
    assert requested[0].headers["authorization"] == f"Bearer {token}"
    assert token not in str(result)


def test_http_adapter_reads_body_free_user_event_tail() -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(
            200,
            json={"cursor": "signed-tail", "latest_event_sequence": 42},
        )

    async def run() -> ChatUserEventTailDTO:
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-service:8090",
                token="t" * 32,
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            return await store.get_user_event_tail("2")

    result = asyncio.run(run())

    assert result == ChatUserEventTailDTO(
        user_id="2",
        cursor="signed-tail",
        latest_event_sequence=42,
    )
    assert requested[0].url == httpx.URL(
        "http://c19-record-service:8090/v1/users/2/events/tail"
    )


def test_http_adapter_uses_exact_content_free_unread_summary_wire() -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        assert json.loads(request.content) == {
            "conversation_ids": ["conversation-a", "conversation-b"]
        }
        return httpx.Response(
            200,
            json={
                "total_unread_count": 9,
                "unread_conversation_count": 2,
            },
        )

    async def run() -> ChatUnreadSummaryDTO:
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-service:8090",
                token="t" * 32,
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            return await store.get_unread_summary(
                ChatUnreadSummaryQueryDTO(
                    user_id="7",
                    conversation_ids=("conversation-a", "conversation-b"),
                )
            )

    result = asyncio.run(run())

    assert result == ChatUnreadSummaryDTO(
        total_unread_count=9,
        unread_conversation_count=2,
    )
    assert requested[0].method == "POST"
    assert requested[0].url == httpx.URL(
        "http://c19-record-service:8090/v1/users/7/unread-summary"
    )


def test_http_adapter_rejects_unread_summary_response_shape_drift() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total_unread_count": 1,
                "unread_conversation_count": 1,
                "content": "must-not-cross-boundary",
            },
        )

    async def run() -> None:
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-service:8090",
                token="t" * 32,
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            with pytest.raises(ChatRecordStoreProtocolError) as captured:
                await store.get_unread_summary(
                    ChatUnreadSummaryQueryDTO(
                        user_id="7",
                        conversation_ids=("conversation-a",),
                    )
                )
            assert captured.value.operation == "get_unread_summary"
            assert "must-not-cross-boundary" not in str(captured.value)

    asyncio.run(run())


def test_http_adapter_rejects_history_record_for_nonparticipant_user() -> None:
    now = datetime.now(UTC).isoformat()

    def record(
        *,
        sequence: int,
        sender_user_id: str,
        recipient_user_ids: list[str],
    ) -> dict[str, object]:
        return {
            "record_id": f"record-{sequence}",
            "client_message_id": f"client-{sequence}",
            "conversation_id": CONVERSATION_ID,
            "sequence": sequence,
            "sender_user_id": sender_user_id,
            "recipient_user_ids": recipient_user_ids,
            "content_type": "text",
            "content": "provider-controlled-content",
            "status": "sent",
            "created_at": now,
            "persisted_at": now,
            "sender_org_id": ORG_ONE,
            "recipient_org_ids": [ORG_TWO],
            "metadata": {},
        }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "records": [
                    record(
                        sequence=1,
                        sender_user_id="1",
                        recipient_user_ids=["2"],
                    ),
                    record(
                        sequence=2,
                        sender_user_id="3",
                        recipient_user_ids=["4"],
                    ),
                ],
                "next_cursor": None,
                "latest_sequence": 2,
            },
        )

    async def run() -> None:
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-service:8090",
                token="t" * 32,
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            with pytest.raises(ChatRecordStoreProtocolError) as captured:
                await store.list_records(
                    ChatRecordQueryDTO(
                        conversation_id=CONVERSATION_ID,
                        user_id="2",
                    )
                )
            assert captured.value.code == "c19_record_store_invalid_response"
            assert captured.value.operation == "list_records"
            assert "provider-controlled-content" not in str(captured.value)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("operation", "delivered", "read"),
    (
        ("delivery", 7, 0),
        ("read", 8, 7),
        ("delivery", 8, 9),
    ),
)
def test_http_adapter_rejects_nonmonotonic_advance_response(
    operation: str,
    delivered: int,
    read: int,
) -> None:
    now = datetime.now(UTC)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "conversation_id": CONVERSATION_ID,
                "user_id": "2",
                "delivered_through_sequence": delivered,
                "read_through_sequence": read,
                "updated_at": now.isoformat(),
            },
        )

    async def run() -> None:
        command = ChatPositionAdvanceDTO(
            conversation_id=CONVERSATION_ID,
            user_id="2",
            through_sequence=8,
            occurred_at=now,
        )
        async with HttpChatRecordStore(
            HttpChatRecordStoreConfig(
                base_url="http://c19-record-service:8090",
                token="t" * 32,
            ),
            transport=httpx.MockTransport(handler),
        ) as store:
            with pytest.raises(ChatRecordStoreProtocolError) as captured:
                if operation == "delivery":
                    await store.advance_delivery(command)
                else:
                    await store.advance_read(command)
            assert captured.value.code == "c19_record_store_invalid_response"
            assert captured.value.operation == f"advance_{operation}"

    asyncio.run(run())


def test_http_config_and_route_error_semantics_are_stable(
    runtime_db: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = runtime_db
    with pytest.raises(ValueError):
        HttpChatRecordStoreConfig(
            base_url="http://c19_record_service:8090",
            token="x" * 31,
        )
    with pytest.raises(ValueError):
        HttpChatRecordStoreConfig(
            base_url="http://records.example.com",
            token="x" * 32,
        )
    assert HttpChatRecordStoreConfig(
        base_url="https://records.example.com",
        token="x" * 32,
    ).base_url == "https://records.example.com"

    cases = (
        (
            ChatRecordStoreRejectedError(
                operation="list_records",
                status_code=400,
            ),
            400,
            "c19_invalid_cursor",
        ),
        (
            ChatRecordStoreRejectedError(
                operation="append_record",
                status_code=422,
            ),
            422,
            "c19_message_rejected",
        ),
        (
            ChatRecordStoreRejectedError(
                operation="append_record",
                status_code=410,
            ),
            410,
            "c19_message_deleted",
        ),
        (
            ChatRecordStoreConflictError(
                operation="append_record",
                status_code=409,
            ),
            409,
            "c19_message_idempotency_conflict",
        ),
        (
            ChatRecordStoreConflictError(
                operation="advance_read",
                status_code=409,
            ),
            409,
            "c19_message_position_conflict",
        ),
    )
    with factory() as db:
        for error, status_code, code in cases:
            with pytest.raises(HTTPException) as captured:
                _raise_chat_error(db, error)
            assert captured.value.status_code == status_code
            assert captured.value.detail["code"] == code


def test_capabilities_reflect_valid_environment_without_external_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "C19_RECORD_STORE_URL",
        "http://c19_record_service:8090",
    )
    monkeypatch.setenv("C19_RECORD_STORE_TOKEN", "t" * 32)
    monkeypatch.setenv("C19_RECORD_STORE_TIMEOUT_SECONDS", "5")

    capabilities = get_c19_storage_capabilities()

    assert capabilities.record_store.status == "configured"
    assert capabilities.record_store.external_io_enabled is True
    assert capabilities.asset_store.status == "unconfigured"
