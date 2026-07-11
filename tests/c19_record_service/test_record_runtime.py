from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from c19_record_service.database import Base, DatabaseRuntime
from c19_record_service.models import (
    ChatRecord,
    RecordIdempotencyLedger,
    RecordMutationAudit,
    UserRecordEvent,
)
from c19_record_service.repository import (
    DeletedIdempotencyKeyError,
    IdempotencyConflictError,
    UnsupportedContentError,
    _idempotency_key_lock_statement,
    _record_ledgers_lock_statement,
    advance_position,
    append_record,
    apply_retention,
    delete_records,
    get_user_event_tail,
    list_records,
    list_user_events,
    resume_position,
    unread_position,
)
from c19_record_service.schemas import (
    DeleteRecordsRequest,
    PositionAdvanceRequest,
    RetentionRequest,
)

from helpers import make_record


def test_postgres_replay_and_delete_lock_the_same_ledger_rows() -> None:
    dialect = postgresql.dialect()
    replay_sql = str(
        _idempotency_key_lock_statement("user-1", "client-1").compile(
            dialect=dialect
        )
    ).upper()
    delete_sql = str(
        _record_ledgers_lock_statement(["record-1"]).compile(dialect=dialect)
    ).upper()
    assert "FOR UPDATE" in replay_sql
    assert "FOR UPDATE" in delete_sql
    assert "RECORD_IDEMPOTENCY_LEDGER" in replay_sql
    assert "RECORD_IDEMPOTENCY_LEDGER" in delete_sql


def test_idempotency_uses_user_intent_not_dynamic_member_snapshot(runtime) -> None:
    original = make_record(1, recipient_user_ids=["user-2"])
    with runtime.session_factory() as session:
        first = append_record(session, original, max_message_chars=1000)

    retry = original.model_copy(
        update={
            "recipient_user_ids": ["user-2", "user-3"],
            "recipient_org_ids": ["org-2", "org-3"],
            "created_at": original.created_at + timedelta(seconds=30),
            "metadata": {"membership_snapshot": "changed"},
        }
    )
    with runtime.session_factory() as session:
        replay = append_record(session, retry, max_message_chars=1000)
        assert replay.replayed is True
        assert replay.record.record_id == first.record.record_id
        assert replay.record.recipient_user_ids == ["user-2"]
        assert replay.record.created_at == original.created_at
        assert session.scalar(select(func.count(ChatRecord.id))) == 1
        assert session.scalar(select(func.count(UserRecordEvent.id))) == 2
        ledger = session.get(
            RecordIdempotencyLedger,
            (original.sender_user_id, original.client_message_id),
        )
        assert ledger is not None
        assert len(ledger.intent_sha256 or "") == 64
        assert original.content not in (ledger.intent_sha256 or "")

    conflicting = original.model_copy(update={"content": "changed intent"})
    with runtime.session_factory() as session:
        with pytest.raises(IdempotencyConflictError):
            append_record(session, conflicting, max_message_chars=1000)


def test_text_and_emoji_validation(runtime) -> None:
    with runtime.session_factory() as session:
        result = append_record(
            session,
            make_record(1, content="🙂", content_type="emoji"),
            max_message_chars=1000,
        )
        assert result.record.content_type == "emoji"

    with runtime.session_factory() as session:
        with pytest.raises(UnsupportedContentError):
            append_record(
                session,
                make_record(2, content="not emoji", content_type="emoji"),
                max_message_chars=1000,
            )
        with pytest.raises(UnsupportedContentError):
            append_record(
                session,
                make_record(3, content="x" * 1001),
                max_message_chars=1000,
            )


def test_concurrent_appends_allocate_gap_free_conversation_sequences(runtime) -> None:
    def persist(number: int) -> int:
        with runtime.session_factory() as session:
            return append_record(
                session, make_record(number), max_message_chars=1000
            ).record.sequence

    with ThreadPoolExecutor(max_workers=8) as executor:
        sequences = list(executor.map(persist, range(1, 25)))
    assert sorted(sequences) == list(range(1, 25))

    with runtime.session_factory() as session:
        stored = list(
            session.scalars(select(ChatRecord.sequence).order_by(ChatRecord.sequence))
        )
    assert stored == list(range(1, 25))


def test_concurrent_same_idempotency_key_fans_out_only_once(runtime) -> None:
    request = make_record(1)

    def persist(_: int) -> tuple[str, bool]:
        with runtime.session_factory() as session:
            result = append_record(session, request, max_message_chars=1000)
            return result.record.record_id, result.replayed

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(persist, range(8)))
    assert len({record_id for record_id, _ in results}) == 1
    assert sum(not replayed for _, replayed in results) == 1
    with runtime.session_factory() as session:
        assert session.scalar(select(func.count(ChatRecord.id))) == 1
        assert session.scalar(select(func.count(UserRecordEvent.id))) == 2


def test_history_starts_with_latest_page_and_uses_directional_cursors(
    runtime, codec
) -> None:
    for number in range(1, 8):
        with runtime.session_factory() as session:
            append_record(session, make_record(number), max_message_chars=1000)

    with runtime.session_factory() as session:
        latest = list_records(
            session,
            conversation_id="conversation-1",
            user_id="user-2",
            limit=3,
            cursor=None,
            codec=codec,
        )
    assert [record.sequence for record in latest.records] == [5, 6, 7]
    assert latest.next_cursor is not None

    with runtime.session_factory() as session:
        older = list_records(
            session,
            conversation_id="conversation-1",
            user_id="user-2",
            limit=3,
            cursor=latest.next_cursor,
            codec=codec,
        )
    assert [record.sequence for record in older.records] == [2, 3, 4]

    now = datetime.now(UTC)
    with runtime.session_factory() as session:
        advance_position(
            session,
            conversation_id="conversation-1",
            request=PositionAdvanceRequest(
                user_id="user-2", through_sequence=4, occurred_at=now
            ),
            position_type="delivery",
        )
    with runtime.session_factory() as session:
        resume = resume_position(
            session,
            conversation_id="conversation-1",
            user_id="user-2",
            codec=codec,
        )
        recovered = list_records(
            session,
            conversation_id="conversation-1",
            user_id="user-2",
            limit=2,
            cursor=resume.resume_cursor,
            codec=codec,
        )
    assert [record.sequence for record in recovered.records] == [5, 6]
    assert recovered.next_cursor is not None


def test_receipts_are_monotonic_status_is_aggregated_and_sender_is_not_unread(
    runtime, codec
) -> None:
    original = make_record(1, recipient_user_ids=["user-2", "user-3"])
    with runtime.session_factory() as session:
        append_record(
            session,
            original,
            max_message_chars=1000,
        )
    now = datetime.now(UTC)
    for user_id in ("user-2", "user-3"):
        with runtime.session_factory() as session:
            advance_position(
                session,
                conversation_id="conversation-1",
                request=PositionAdvanceRequest(
                    user_id=user_id, through_sequence=1, occurred_at=now
                ),
                position_type="delivery",
            )
    with runtime.session_factory() as session:
        page = list_records(
            session,
            conversation_id="conversation-1",
            user_id="user-1",
            limit=50,
            cursor=None,
            codec=codec,
        )
    assert page.records[0].status == "delivered"

    for user_id in ("user-2", "user-3"):
        with runtime.session_factory() as session:
            receipt = advance_position(
                session,
                conversation_id="conversation-1",
                request=PositionAdvanceRequest(
                    user_id=user_id,
                    through_sequence=1,
                    occurred_at=now + timedelta(seconds=1),
                ),
                position_type="read",
            )
            backwards = advance_position(
                session,
                conversation_id="conversation-1",
                request=PositionAdvanceRequest(
                    user_id=user_id,
                    through_sequence=0,
                    occurred_at=now + timedelta(seconds=2),
                ),
                position_type="read",
            )
            assert receipt.read_through_sequence == 1
            assert backwards.read_through_sequence == 1

    with runtime.session_factory() as session:
        page = list_records(
            session,
            conversation_id="conversation-1",
            user_id="user-1",
            limit=50,
            cursor=None,
            codec=codec,
        )
        sender_unread = unread_position(
            session, conversation_id="conversation-1", user_id="user-1"
        )
        recipient_unread = unread_position(
            session, conversation_id="conversation-1", user_id="user-2"
        )
    assert page.records[0].status == "read"
    assert sender_unread.unread_count == 0
    assert recipient_unread.unread_count == 0
    with runtime.session_factory() as session:
        replay = append_record(session, original, max_message_chars=1000)
    assert replay.replayed is True
    assert replay.record.status == "read"


def test_user_event_cursor_always_advances_and_empty_poll_does_not_replay(
    runtime, codec
) -> None:
    with runtime.session_factory() as session:
        empty = list_user_events(
            session, user_id="user-2", limit=50, cursor=None, codec=codec
        )
    assert empty.events == []
    assert empty.next_cursor

    with runtime.session_factory() as session:
        append_record(session, make_record(1), max_message_chars=1000)
        first = list_user_events(
            session,
            user_id="user-2",
            limit=50,
            cursor=empty.next_cursor,
            codec=codec,
        )
    assert [event.event_sequence for event in first.events] == [1]
    assert first.next_cursor

    with runtime.session_factory() as session:
        next_poll = list_user_events(
            session,
            user_id="user-2",
            limit=50,
            cursor=first.next_cursor,
            codec=codec,
        )
    assert next_poll.events == []
    assert next_poll.next_cursor


def test_user_event_tail_bootstraps_at_now_without_replaying_history(
    runtime, codec
) -> None:
    with runtime.session_factory() as session:
        append_record(session, make_record(1), max_message_chars=1000)
        tail = get_user_event_tail(session, user_id="user-2", codec=codec)
    assert tail.latest_event_sequence == 1
    assert tail.cursor

    with runtime.session_factory() as session:
        empty_at_tail = list_user_events(
            session,
            user_id="user-2",
            limit=50,
            cursor=tail.cursor,
            codec=codec,
        )
    assert empty_at_tail.events == []

    with runtime.session_factory() as session:
        append_record(session, make_record(2), max_message_chars=1000)
        new_events = list_user_events(
            session,
            user_id="user-2",
            limit=50,
            cursor=tail.cursor,
            codec=codec,
        )
    assert [event.event_sequence for event in new_events.events] == [2]


def test_explicit_delete_and_retention_remove_content_but_keep_audit(runtime) -> None:
    old = datetime.now(UTC) - timedelta(days=30)
    ids: list[str] = []
    for number in range(1, 4):
        with runtime.session_factory() as session:
            ids.append(
                append_record(
                    session,
                    make_record(number, created_at=old + timedelta(seconds=number)),
                    max_message_chars=1000,
                ).record.record_id
            )
    with runtime.session_factory() as session:
        deleted = delete_records(
            session,
            DeleteRecordsRequest(
                conversation_id="conversation-1",
                record_ids=[ids[0]],
                requested_by_user_id="operator-1",
                reason="privacy deletion request",
                requested_at=datetime.now(UTC),
            ),
        )
    assert deleted.affected_count == 1
    with runtime.session_factory() as session:
        with pytest.raises(DeletedIdempotencyKeyError):
            append_record(session, make_record(1), max_message_chars=1000)
        with pytest.raises(DeletedIdempotencyKeyError):
            append_record(
                session,
                make_record(1, content="different user intent"),
                max_message_chars=1000,
            )

    with runtime.session_factory() as session:
        retained = apply_retention(
            session,
            RetentionRequest(
                requested_by_user_id="operator-1",
                reason="approved retention policy",
                requested_at=datetime.now(UTC),
                delete_before=datetime.now(UTC) - timedelta(days=1),
                conversation_id="conversation-1",
                maximum_records=1,
            ),
        )
        assert retained.affected_count == 1
        assert session.scalar(select(func.count(ChatRecord.id))) == 1
        assert session.scalar(select(func.count(RecordMutationAudit.id))) == 2
        assert session.scalar(select(func.count(UserRecordEvent.id))) == 2
        ledgers = list(
            session.scalars(
                select(RecordIdempotencyLedger).order_by(
                    RecordIdempotencyLedger.client_message_id
                )
            )
        )
        assert [ledger.status for ledger in ledgers] == [
            "deleted",
            "deleted",
            "active",
        ]
        assert ledgers[0].record_id is None
        assert ledgers[0].sequence == 1
        assert ledgers[0].intent_sha256 is None

    with runtime.session_factory() as session:
        with pytest.raises(DeletedIdempotencyKeyError):
            append_record(session, make_record(2), max_message_chars=1000)


def test_delete_racing_safe_retries_never_resurrects_or_refans_out(runtime) -> None:
    original = make_record(1)
    with runtime.session_factory() as session:
        saved = append_record(session, original, max_message_chars=1000).record

    barrier = Barrier(9)

    def retry(_: int) -> str:
        barrier.wait()
        with runtime.session_factory() as session:
            try:
                result = append_record(session, original, max_message_chars=1000)
                return result.record.record_id
            except DeletedIdempotencyKeyError:
                return "deleted"

    def remove() -> int:
        barrier.wait()
        with runtime.session_factory() as session:
            return delete_records(
                session,
                DeleteRecordsRequest(
                    conversation_id="conversation-1",
                    record_ids=[saved.record_id],
                    requested_by_user_id="operator-1",
                    reason="concurrent privacy deletion",
                    requested_at=datetime.now(UTC),
                ),
            ).affected_count

    with ThreadPoolExecutor(max_workers=9) as executor:
        retry_futures = [executor.submit(retry, value) for value in range(8)]
        delete_future = executor.submit(remove)
        retry_results = [future.result() for future in retry_futures]
        assert delete_future.result() == 1

    assert set(retry_results) <= {saved.record_id, "deleted"}
    with runtime.session_factory() as session:
        with pytest.raises(DeletedIdempotencyKeyError):
            append_record(session, original, max_message_chars=1000)
        assert session.scalar(select(func.count(ChatRecord.id))) == 0
        assert session.scalar(select(func.count(UserRecordEvent.id))) == 0
        ledger = session.get(
            RecordIdempotencyLedger,
            (original.sender_user_id, original.client_message_id),
        )
        assert ledger is not None
        assert ledger.status == "deleted"
        assert ledger.record_id is None
        assert ledger.intent_sha256 is None


def test_records_survive_service_restart(database_path, codec) -> None:
    url = f"sqlite:///{database_path}"
    first_runtime = DatabaseRuntime.create(url)
    Base.metadata.create_all(first_runtime.engine)
    with first_runtime.session_factory() as session:
        saved = append_record(session, make_record(1), max_message_chars=1000).record
    first_runtime.dispose()

    restarted = DatabaseRuntime.create(url)
    try:
        with restarted.session_factory() as session:
            page = list_records(
                session,
                conversation_id="conversation-1",
                user_id="user-2",
                limit=50,
                cursor=None,
                codec=codec,
            )
        assert [record.record_id for record in page.records] == [saved.record_id]
    finally:
        restarted.dispose()
