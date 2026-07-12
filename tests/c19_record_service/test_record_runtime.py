from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from c19_record_service.database import Base, DatabaseRuntime
from c19_record_service.models import (
    ChatRecord,
    RecordAssetReference as RecordAssetReferenceModel,
    RecordIdempotencyLedger,
    RecordMutationAudit,
    UserRecordEvent,
)
from c19_record_service.repository import (
    _idempotency_key_lock_statement,
    _intent_sha256,
    _expected_retention_operation_id,
    _record_ledgers_lock_statement,
    DeletedIdempotencyKeyError,
    IdempotencyConflictError,
    UnsupportedContentError,
    advance_position,
    append_record,
    apply_retention,
    delete_records,
    get_visible_record,
    get_user_event_tail,
    list_records,
    list_user_events,
    resume_position,
    unread_position,
    unread_summary,
)
from c19_record_service.operations import record_ops_snapshot
from c19_record_service.schemas import (
    DeleteRecordsRequest,
    PositionAdvanceRequest,
    RetentionRequest,
)

from helpers import make_asset, make_record


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


def test_asset_free_text_keeps_exact_stage3_v1_intent_digest(runtime) -> None:
    request = make_record(1, content="旧消息🙂")
    stage3_canonical = json.dumps(
        {
            "client_message_id": request.client_message_id,
            "content": request.content,
            "content_type": request.content_type,
            "conversation_id": request.conversation_id,
            "sender_user_id": request.sender_user_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    expected = hashlib.sha256(stage3_canonical).hexdigest()

    assert _intent_sha256(request) == expected
    with runtime.session_factory() as session:
        first = append_record(session, request, max_message_chars=1000)
        ledger = session.get(
            RecordIdempotencyLedger,
            (request.sender_user_id, request.client_message_id),
        )
        assert ledger is not None
        assert ledger.intent_version == 1
        assert ledger.intent_sha256 == expected

    retry = request.model_copy(
        update={
            "recipient_user_ids": ["user-2", "user-3"],
            "metadata": {"changed": "snapshot-only"},
        }
    )
    with runtime.session_factory() as session:
        replay = append_record(session, retry, max_message_chars=1000)
    assert replay.replayed is True
    assert replay.record.record_id == first.record.record_id
    assert replay.record.assets == []


def test_asset_snapshot_is_v2_idempotent_and_cannot_be_swapped(runtime) -> None:
    original = make_record(
        1,
        content="",
        content_type="image",
        assets=[make_asset(1)],
    )
    with runtime.session_factory() as session:
        first = append_record(session, original, max_message_chars=1000)
        ledger = session.get(
            RecordIdempotencyLedger,
            (original.sender_user_id, original.client_message_id),
        )
        assert ledger is not None
        assert ledger.intent_version == 2

    with runtime.session_factory() as session:
        replay = append_record(session, original, max_message_chars=1000)
    assert replay.replayed is True
    assert replay.record.record_id == first.record.record_id
    assert [asset.asset_id for asset in replay.record.assets] == [
        original.assets[0].asset_id
    ]

    changed_asset = original.model_copy(update={"assets": [make_asset(2)]})
    with runtime.session_factory() as session:
        with pytest.raises(IdempotencyConflictError):
            append_record(session, changed_asset, max_message_chars=1000)


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


def test_exact_visibility_uses_record_event_and_assets_return_in_ordinal_order(
    runtime,
) -> None:
    first_request = make_record(
        1,
        content="caption",
        content_type="image",
        recipient_user_ids=["user-2"],
        assets=[make_asset(1)],
    )
    with runtime.session_factory() as session:
        first = append_record(
            session, first_request, max_message_chars=1000
        ).record
        expansion_asset = make_asset(2, ordinal=1)
        session.add(
            RecordAssetReferenceModel(
                id="00000000-0000-0000-0000-000000000002",
                record_id=first.record_id,
                asset_id=expansion_asset.asset_id,
                client_asset_id=expansion_asset.client_asset_id,
                kind=expansion_asset.kind,
                filename=expansion_asset.filename,
                media_type=expansion_asset.media_type,
                size_bytes=expansion_asset.size_bytes,
                sha256_hex=expansion_asset.sha256_hex,
                version=expansion_asset.version,
                ordinal=expansion_asset.ordinal,
            )
        )
        session.commit()

    with runtime.session_factory() as session:
        visible = get_visible_record(
            session,
            conversation_id="conversation-1",
            record_id=first.record_id,
            user_id="user-2",
        )
        pre_join_hidden = get_visible_record(
            session,
            conversation_id="conversation-1",
            record_id=first.record_id,
            user_id="user-3",
        )
        wrong_conversation = get_visible_record(
            session,
            conversation_id="conversation-other",
            record_id=first.record_id,
            user_id="user-2",
        )
    assert visible is not None
    assert [asset.ordinal for asset in visible.assets] == [0, 1]
    assert [asset.asset_id for asset in visible.assets] == [
        make_asset(1).asset_id,
        make_asset(2).asset_id,
    ]
    assert pre_join_hidden is None
    assert wrong_conversation is None

    # A later record can include the newly joined user without retroactively
    # granting that user access to the first record.
    with runtime.session_factory() as session:
        later = append_record(
            session,
            make_record(2, recipient_user_ids=["user-2", "user-3"]),
            max_message_chars=1000,
        ).record
        assert (
            get_visible_record(
                session,
                conversation_id="conversation-1",
                record_id=later.record_id,
                user_id="user-3",
            )
            is not None
        )
        assert (
            get_visible_record(
                session,
                conversation_id="conversation-1",
                record_id=first.record_id,
                user_id="user-3",
            )
            is None
        )


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


def test_unread_summary_is_content_free_exact_and_scoped_to_supplied_conversations(
    runtime,
) -> None:
    with runtime.session_factory() as session:
        append_record(
            session,
            make_record(1, conversation_id="conversation-1"),
            max_message_chars=1000,
        )
        append_record(
            session,
            make_record(2, conversation_id="conversation-1"),
            max_message_chars=1000,
        )
        append_record(
            session,
            make_record(
                3,
                conversation_id="conversation-1",
                sender_user_id="user-2",
                recipient_user_ids=["user-1"],
            ),
            max_message_chars=1000,
        )
        append_record(
            session,
            make_record(
                4,
                conversation_id="conversation-2",
                sender_user_id="user-3",
                recipient_user_ids=["user-2"],
            ),
            max_message_chars=1000,
        )
        append_record(
            session,
            make_record(
                5,
                conversation_id="conversation-not-authorized",
                sender_user_id="user-3",
                recipient_user_ids=["user-2"],
            ),
            max_message_chars=1000,
        )
    with runtime.session_factory() as session:
        advance_position(
            session,
            conversation_id="conversation-1",
            request=PositionAdvanceRequest(
                user_id="user-2",
                through_sequence=1,
                occurred_at=datetime.now(UTC),
            ),
            position_type="read",
        )
    with runtime.session_factory() as session:
        all_authorized = unread_summary(
            session,
            user_id="user-2",
            conversation_ids=["conversation-1", "conversation-2"],
        )
        one_shard = unread_summary(
            session,
            user_id="user-2",
            conversation_ids=["conversation-1"],
        )
        empty = unread_summary(session, user_id="user-2", conversation_ids=[])

    assert all_authorized.model_dump() == {
        "total_unread_count": 2,
        "unread_conversation_count": 2,
    }
    assert one_shard.model_dump() == {
        "total_unread_count": 1,
        "unread_conversation_count": 1,
    }
    assert empty.model_dump() == {
        "total_unread_count": 0,
        "unread_conversation_count": 0,
    }


def test_record_ops_snapshot_contains_only_bounded_aggregate_state(runtime) -> None:
    secret = "must-never-appear-in-ops-snapshot"
    with runtime.session_factory() as session:
        append_record(
            session,
            make_record(91, content=secret),
            max_message_chars=1000,
        )
    with runtime.session_factory() as session:
        snapshot = record_ops_snapshot(session)
    payload = snapshot.model_dump_json()
    assert snapshot.chat_records == 1
    assert snapshot.chat_delivery_events == 2
    assert snapshot.moment_states == {
        "draft": 0,
        "published": 0,
        "delete_pending": 0,
        "deleted": 0,
    }
    assert secret not in payload
    for forbidden in ("user-1", "conversation-1", "client-91"):
        assert forbidden not in payload


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
        request = RetentionRequest(
            operation_id="rtn_" + "0" * 64,
            batch_ordinal=0,
            approved_maximum_records=1,
            approved_maximum_asset_jobs=1,
            requested_by_user_id="operator-1",
            reason="approved retention policy",
            requested_at=datetime.now(UTC),
            delete_before=datetime.now(UTC) - timedelta(days=1),
            conversation_id="conversation-1",
            maximum_records=1,
        )
        request.operation_id = _expected_retention_operation_id(request)
        retained = apply_retention(session, request)
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


def test_asset_references_cascade_on_delete_and_key_remains_410(runtime) -> None:
    original = make_record(
        1,
        content="invoice",
        content_type="file",
        assets=[make_asset(1, kind="file")],
    )
    with runtime.session_factory() as session:
        saved = append_record(session, original, max_message_chars=1000).record
        assert session.scalar(select(func.count(RecordAssetReferenceModel.id))) == 1

    with runtime.session_factory() as session:
        result = delete_records(
            session,
            DeleteRecordsRequest(
                conversation_id="conversation-1",
                record_ids=[saved.record_id],
                requested_by_user_id="operator-1",
                reason="asset privacy deletion",
                requested_at=datetime.now(UTC),
            ),
        )
        assert result.affected_count == 1
        assert session.scalar(select(func.count(RecordAssetReferenceModel.id))) == 0

    with runtime.session_factory() as session:
        with pytest.raises(DeletedIdempotencyKeyError):
            append_record(session, original, max_message_chars=1000)
        changed = original.model_copy(update={"assets": [make_asset(2, kind="file")]})
        with pytest.raises(DeletedIdempotencyKeyError):
            append_record(session, changed, max_message_chars=1000)


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
