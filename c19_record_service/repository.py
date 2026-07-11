"""Transactional record store implementation.

This module deliberately emits no log records containing chat content.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .cursors import CursorCodec, InvalidCursorError
from .models import (
    ChatRecord,
    ConversationSequence,
    ParticipantPosition,
    RecordIdempotencyLedger,
    RecordMutationAudit,
    UserEventSequence,
    UserRecordEvent,
)
from .schemas import (
    CombinedPositionResponse,
    DeleteRecordsRequest,
    MutationResultResponse,
    PositionAdvanceRequest,
    ReceiptPositionResponse,
    RecordAppendRequest,
    RecordPageResponse,
    RecordResponse,
    ResumePositionResponse,
    RetentionRequest,
    UnreadPositionResponse,
    UserEventPageResponse,
    UserEventResponse,
    UserEventTailResponse,
)


class RecordStoreError(RuntimeError):
    pass


class IdempotencyConflictError(RecordStoreError):
    pass


class DeletedIdempotencyKeyError(RecordStoreError):
    pass


class RecordStoreInvariantError(RecordStoreError):
    pass


class PositionBeyondConversationError(RecordStoreError):
    pass


class UnsupportedContentError(RecordStoreError):
    pass


@dataclass(frozen=True, slots=True)
class AppendResult:
    record: RecordResponse
    replayed: bool


def utcnow() -> datetime:
    return datetime.now(UTC)


def _dialect_insert(session: Session, table: type[object]):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgres_insert(table)
    if dialect == "sqlite":
        return sqlite_insert(table)
    return None


def _next_sequence(
    session: Session,
    *,
    model: type[ConversationSequence] | type[UserEventSequence],
    key_name: str,
    key_value: str,
    now: datetime,
) -> int:
    insert_statement = _dialect_insert(session, model)
    table = model.__table__
    if insert_statement is not None:
        statement = insert_statement.values(
            **{key_name: key_value, "last_sequence": 1, "updated_at": now}
        )
        statement = statement.on_conflict_do_update(
            index_elements=[getattr(table.c, key_name)],
            set_={
                "last_sequence": table.c.last_sequence + 1,
                "updated_at": now,
            },
        ).returning(table.c.last_sequence)
        return int(session.execute(statement).scalar_one())

    row = session.execute(
        select(model)
        .where(getattr(model, key_name) == key_value)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = model(**{key_name: key_value, "last_sequence": 1, "updated_at": now})
        session.add(row)
        session.flush()
        return 1
    row.last_sequence += 1
    row.updated_at = now
    session.flush()
    return row.last_sequence


def _record_response(record: ChatRecord, *, status: str = "sent") -> RecordResponse:
    return RecordResponse(
        record_id=record.id,
        client_message_id=record.client_message_id,
        conversation_id=record.conversation_id,
        sequence=record.sequence,
        sender_user_id=record.sender_user_id,
        recipient_user_ids=list(record.recipient_user_ids),
        content_type=record.content_type,
        content=record.content,
        status=status,
        created_at=record.created_at,
        persisted_at=record.persisted_at,
        sender_org_id=record.sender_org_id,
        recipient_org_ids=list(record.recipient_org_ids),
        metadata=dict(record.record_metadata),
    )


def _intent_sha256(request: RecordAppendRequest) -> str:
    """Hash only immutable user intent; never persist or log the canonical body."""

    canonical = json.dumps(
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
    return hashlib.sha256(canonical).hexdigest()


def _record_status(session: Session, record: ChatRecord) -> str:
    recipients = {
        recipient
        for recipient in record.recipient_user_ids
        if recipient != record.sender_user_id
    }
    if not recipients:
        return "sent"
    positions = {
        row.user_id: row
        for row in session.execute(
            select(ParticipantPosition).where(
                ParticipantPosition.conversation_id == record.conversation_id,
                ParticipantPosition.user_id.in_(recipients),
            )
        ).scalars()
    }
    if all(
        positions.get(recipient) is not None
        and positions[recipient].read_through_sequence >= record.sequence
        for recipient in recipients
    ):
        return "read"
    if all(
        positions.get(recipient) is not None
        and positions[recipient].delivered_through_sequence >= record.sequence
        for recipient in recipients
    ):
        return "delivered"
    return "sent"


def _claim_idempotency_key(
    session: Session,
    request: RecordAppendRequest,
    *,
    intent_sha256: str,
    now: datetime,
) -> bool:
    insert_statement = _dialect_insert(session, RecordIdempotencyLedger)
    values = {
        "sender_user_id": request.sender_user_id,
        "client_message_id": request.client_message_id,
        "intent_sha256": intent_sha256,
        "conversation_id": request.conversation_id,
        "record_id": None,
        "sequence": None,
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    if insert_statement is not None:
        statement = (
            insert_statement.values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    RecordIdempotencyLedger.__table__.c.sender_user_id,
                    RecordIdempotencyLedger.__table__.c.client_message_id,
                ]
            )
            .returning(RecordIdempotencyLedger.__table__.c.sender_user_id)
        )
        return session.execute(statement).scalar_one_or_none() is not None

    existing = session.execute(
        select(RecordIdempotencyLedger)
        .where(
            RecordIdempotencyLedger.sender_user_id == request.sender_user_id,
            RecordIdempotencyLedger.client_message_id
            == request.client_message_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        return False
    session.add(RecordIdempotencyLedger(**values))
    session.flush()
    return True


def _idempotency_key_lock_statement(
    sender_user_id: str, client_message_id: str
):
    return (
        select(RecordIdempotencyLedger)
        .where(
            RecordIdempotencyLedger.sender_user_id == sender_user_id,
            RecordIdempotencyLedger.client_message_id == client_message_id,
        )
        .with_for_update()
    )


def _record_ledgers_lock_statement(record_ids: list[str]):
    return (
        select(RecordIdempotencyLedger)
        .where(RecordIdempotencyLedger.record_id.in_(record_ids))
        .order_by(
            RecordIdempotencyLedger.sender_user_id,
            RecordIdempotencyLedger.client_message_id,
        )
        .with_for_update()
    )


def _resolve_idempotent_replay(
    session: Session,
    request: RecordAppendRequest,
    *,
    intent_sha256: str,
) -> AppendResult:
    ledger = session.execute(
        _idempotency_key_lock_statement(
            request.sender_user_id, request.client_message_id
        )
    ).scalar_one_or_none()
    if ledger is None:
        raise RecordStoreInvariantError("idempotency ledger claim disappeared")
    if ledger.status == "deleted":
        raise DeletedIdempotencyKeyError("message was permanently deleted")
    if ledger.intent_sha256 != intent_sha256:
        raise IdempotencyConflictError("idempotency key was reused")
    if ledger.status != "active" or ledger.record_id is None:
        raise RecordStoreInvariantError("active idempotency ledger is incomplete")
    record = session.get(ChatRecord, ledger.record_id)
    if record is None:
        raise RecordStoreInvariantError("active idempotency record is missing")
    return AppendResult(
        _record_response(record, status=_record_status(session, record)),
        True,
    )


def _validate_content(request: RecordAppendRequest, max_message_chars: int) -> None:
    if not request.content or not request.content.strip():
        raise UnsupportedContentError("message content cannot be empty")
    if len(request.content) > max_message_chars:
        raise UnsupportedContentError("message content exceeds configured limit")
    if request.content_type != "emoji":
        return
    if len(request.content) > 64:
        raise UnsupportedContentError("emoji message exceeds 64 code points")
    emoji_like = False
    for character in request.content:
        codepoint = ord(character)
        category = unicodedata.category(character)
        allowed_joiner = codepoint in {0x200D, 0xFE0E, 0xFE0F, 0x20E3}
        allowed_keycap = character in "#*0123456789"
        if character.isspace() or (
            category.startswith("C") and not allowed_joiner
        ):
            raise UnsupportedContentError("emoji content contains unsupported text")
        if not (
            category.startswith(("S", "M", "P"))
            or allowed_joiner
            or allowed_keycap
        ):
            raise UnsupportedContentError("emoji content contains unsupported text")
        if (
            codepoint >= 0x1F000
            or 0x2300 <= codepoint <= 0x27FF
            or codepoint in {0x00A9, 0x00AE, 0x2122, 0x20E3}
        ):
            emoji_like = True
    if not emoji_like:
        raise UnsupportedContentError("emoji content must contain an emoji")


def append_record(
    session: Session,
    request: RecordAppendRequest,
    *,
    max_message_chars: int,
) -> AppendResult:
    persisted_at = utcnow()
    intent_sha256 = _intent_sha256(request)
    claimed = _claim_idempotency_key(
        session,
        request,
        intent_sha256=intent_sha256,
        now=persisted_at,
    )
    if not claimed:
        return _resolve_idempotent_replay(
            session, request, intent_sha256=intent_sha256
        )
    try:
        _validate_content(request, max_message_chars)
        sequence = _next_sequence(
            session,
            model=ConversationSequence,
            key_name="conversation_id",
            key_value=request.conversation_id,
            now=persisted_at,
        )
        record = ChatRecord(
            id=str(uuid.uuid4()),
            client_message_id=request.client_message_id,
            conversation_id=request.conversation_id,
            sequence=sequence,
            sender_user_id=request.sender_user_id,
            recipient_user_ids=list(request.recipient_user_ids),
            content_type=request.content_type,
            content=request.content,
            sender_org_id=request.sender_org_id,
            recipient_org_ids=list(request.recipient_org_ids),
            record_metadata=dict(request.metadata),
            created_at=request.created_at,
            persisted_at=persisted_at,
        )
        session.add(record)
        session.flush()
        ledger = session.get(
            RecordIdempotencyLedger,
            (request.sender_user_id, request.client_message_id),
        )
        if ledger is None:
            raise RecordStoreInvariantError("idempotency ledger claim disappeared")
        ledger.record_id = record.id
        ledger.sequence = sequence
        ledger.updated_at = persisted_at
        audience = sorted({request.sender_user_id, *request.recipient_user_ids})
        for user_id in audience:
            event_sequence = _next_sequence(
                session,
                model=UserEventSequence,
                key_name="user_id",
                key_value=user_id,
                now=persisted_at,
            )
            session.add(
                UserRecordEvent(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    event_sequence=event_sequence,
                    conversation_id=request.conversation_id,
                    record_id=record.id,
                    record_sequence=sequence,
                    created_at=persisted_at,
                )
            )
        session.commit()
        return AppendResult(_record_response(record), False)
    except UnsupportedContentError:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        try:
            return _resolve_idempotent_replay(
                session, request, intent_sha256=intent_sha256
            )
        except RecordStoreInvariantError:
            raise RecordStoreInvariantError(
                "append transaction integrity failure"
            ) from None


def list_records(
    session: Session,
    *,
    conversation_id: str,
    user_id: str,
    limit: int,
    cursor: str | None,
    codec: CursorCodec,
) -> RecordPageResponse:
    scope = f"{conversation_id}:{user_id}"
    decoded = (
        codec.decode(
            cursor,
            kinds=("records_older", "records_after"),
            scope=scope,
        )
        if cursor
        else None
    )
    query = (
        select(ChatRecord)
        .join(UserRecordEvent, UserRecordEvent.record_id == ChatRecord.id)
        .where(
            UserRecordEvent.user_id == user_id,
            ChatRecord.conversation_id == conversation_id,
        )
    )
    if decoded is not None and decoded.kind == "records_after":
        query = query.where(ChatRecord.sequence > decoded.position).order_by(
            ChatRecord.sequence.asc()
        )
        descending = False
    else:
        if decoded is not None:
            query = query.where(ChatRecord.sequence < decoded.position)
        query = query.order_by(ChatRecord.sequence.desc())
        descending = True
    rows = list(session.execute(query.limit(limit + 1)).scalars())
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    if descending:
        page_rows.reverse()
    next_cursor = (
        codec.encode(
            kind=(
                "records_older"
                if descending
                else "records_after"
            ),
            scope=scope,
            position=(page_rows[0].sequence if descending else page_rows[-1].sequence),
        )
        if has_more and page_rows
        else None
    )
    has_access = session.execute(
        select(UserRecordEvent.id).where(
            UserRecordEvent.user_id == user_id,
            UserRecordEvent.conversation_id == conversation_id,
        ).limit(1)
    ).scalar_one_or_none()
    latest = (
        session.get(ConversationSequence, conversation_id).last_sequence
        if has_access and session.get(ConversationSequence, conversation_id)
        else 0
    )
    recipient_ids = {
        recipient
        for record in page_rows
        for recipient in record.recipient_user_ids
        if recipient != record.sender_user_id
    }
    positions = {
        row.user_id: row
        for row in session.execute(
            select(ParticipantPosition).where(
                ParticipantPosition.conversation_id == conversation_id,
                ParticipantPosition.user_id.in_(recipient_ids),
            )
        ).scalars()
    } if recipient_ids else {}

    def aggregate_status(record: ChatRecord) -> str:
        recipients = {
            recipient
            for recipient in record.recipient_user_ids
            if recipient != record.sender_user_id
        }
        if not recipients:
            return "sent"
        if all(
            positions.get(recipient) is not None
            and positions[recipient].read_through_sequence >= record.sequence
            for recipient in recipients
        ):
            return "read"
        if all(
            positions.get(recipient) is not None
            and positions[recipient].delivered_through_sequence >= record.sequence
            for recipient in recipients
        ):
            return "delivered"
        return "sent"

    return RecordPageResponse(
        records=[
            _record_response(row, status=aggregate_status(row)) for row in page_rows
        ],
        next_cursor=next_cursor,
        latest_sequence=latest,
    )


def _latest_sequence(session: Session, conversation_id: str) -> int:
    row = session.get(ConversationSequence, conversation_id)
    return row.last_sequence if row is not None else 0


def _greatest(session: Session, left, right):
    if session.get_bind().dialect.name == "sqlite":
        return func.max(left, right)
    return func.greatest(left, right)


def advance_position(
    session: Session,
    *,
    conversation_id: str,
    request: PositionAdvanceRequest,
    position_type: str,
) -> ReceiptPositionResponse:
    latest = _latest_sequence(session, conversation_id)
    if request.through_sequence > latest:
        raise PositionBeyondConversationError(
            "position cannot advance beyond the latest sequence"
        )
    insert_statement = _dialect_insert(session, ParticipantPosition)
    now = request.occurred_at
    table = ParticipantPosition.__table__
    if insert_statement is not None:
        if position_type == "delivery":
            insert_values = {
                "conversation_id": conversation_id,
                "user_id": request.user_id,
                "delivered_through_sequence": request.through_sequence,
                "read_through_sequence": 0,
                "updated_at": now,
            }
            advanced = (
                insert_statement.excluded.delivered_through_sequence
                > table.c.delivered_through_sequence
            )
            update_values = {
                "delivered_through_sequence": _greatest(
                    session,
                    table.c.delivered_through_sequence,
                    insert_statement.excluded.delivered_through_sequence,
                ),
                "updated_at": case(
                    (advanced, insert_statement.excluded.updated_at),
                    else_=table.c.updated_at,
                ),
            }
        else:
            insert_values = {
                "conversation_id": conversation_id,
                "user_id": request.user_id,
                "delivered_through_sequence": request.through_sequence,
                "read_through_sequence": request.through_sequence,
                "updated_at": now,
            }
            advanced = (
                insert_statement.excluded.read_through_sequence
                > table.c.read_through_sequence
            )
            update_values = {
                "delivered_through_sequence": _greatest(
                    session,
                    table.c.delivered_through_sequence,
                    insert_statement.excluded.read_through_sequence,
                ),
                "read_through_sequence": _greatest(
                    session,
                    table.c.read_through_sequence,
                    insert_statement.excluded.read_through_sequence,
                ),
                "updated_at": case(
                    (advanced, insert_statement.excluded.updated_at),
                    else_=table.c.updated_at,
                ),
            }
        statement = (
            insert_statement.values(**insert_values)
            .on_conflict_do_update(
                index_elements=[table.c.conversation_id, table.c.user_id],
                set_=update_values,
            )
            .returning(
                table.c.conversation_id,
                table.c.user_id,
                table.c.delivered_through_sequence,
                table.c.read_through_sequence,
                table.c.updated_at,
            )
        )
        row = session.execute(statement).one()
    else:
        position = session.execute(
            select(ParticipantPosition)
            .where(
                ParticipantPosition.conversation_id == conversation_id,
                ParticipantPosition.user_id == request.user_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if position is None:
            position = ParticipantPosition(
                conversation_id=conversation_id,
                user_id=request.user_id,
                delivered_through_sequence=request.through_sequence,
                read_through_sequence=(
                    request.through_sequence if position_type == "read" else 0
                ),
                updated_at=now,
            )
            session.add(position)
        elif position_type == "delivery" and (
            request.through_sequence > position.delivered_through_sequence
        ):
            position.delivered_through_sequence = request.through_sequence
            position.updated_at = now
        elif position_type == "read" and (
            request.through_sequence > position.read_through_sequence
        ):
            position.read_through_sequence = request.through_sequence
            position.delivered_through_sequence = max(
                position.delivered_through_sequence, request.through_sequence
            )
            position.updated_at = now
        session.flush()
        row = (
            position.conversation_id,
            position.user_id,
            position.delivered_through_sequence,
            position.read_through_sequence,
            position.updated_at,
        )
    session.commit()
    return ReceiptPositionResponse(
        conversation_id=row[0],
        user_id=row[1],
        delivered_through_sequence=row[2],
        read_through_sequence=row[3],
        updated_at=row[4],
    )


def unread_position(
    session: Session, *, conversation_id: str, user_id: str
) -> UnreadPositionResponse:
    position = session.get(ParticipantPosition, (conversation_id, user_id))
    read_through = position.read_through_sequence if position else 0
    count, first = session.execute(
        select(func.count(UserRecordEvent.id), func.min(UserRecordEvent.record_sequence))
        .join(ChatRecord, ChatRecord.id == UserRecordEvent.record_id)
        .where(
            UserRecordEvent.user_id == user_id,
            UserRecordEvent.conversation_id == conversation_id,
            UserRecordEvent.record_sequence > read_through,
            ChatRecord.sender_user_id != user_id,
        )
    ).one()
    return UnreadPositionResponse(
        conversation_id=conversation_id,
        user_id=user_id,
        unread_count=int(count),
        first_unread_sequence=int(first) if first is not None else None,
        latest_sequence=_latest_sequence(session, conversation_id),
    )


def resume_position(
    session: Session,
    *,
    conversation_id: str,
    user_id: str,
    codec: CursorCodec,
) -> ResumePositionResponse:
    position = session.get(ParticipantPosition, (conversation_id, user_id))
    delivered = position.delivered_through_sequence if position else 0
    read = position.read_through_sequence if position else 0
    latest = _latest_sequence(session, conversation_id)
    return ResumePositionResponse(
        conversation_id=conversation_id,
        user_id=user_id,
        resume_cursor=(
            codec.encode(
                kind="records_after",
                scope=f"{conversation_id}:{user_id}",
                position=delivered,
            )
            if latest > delivered
            else None
        ),
        delivered_through_sequence=delivered,
        read_through_sequence=read,
        latest_sequence=latest,
    )


def combined_position(
    session: Session,
    *,
    conversation_id: str,
    user_id: str,
    codec: CursorCodec,
) -> CombinedPositionResponse:
    return CombinedPositionResponse(
        unread=unread_position(
            session, conversation_id=conversation_id, user_id=user_id
        ),
        resume=resume_position(
            session,
            conversation_id=conversation_id,
            user_id=user_id,
            codec=codec,
        ),
    )


def list_user_events(
    session: Session,
    *,
    user_id: str,
    limit: int,
    cursor: str | None,
    codec: CursorCodec,
) -> UserEventPageResponse:
    position = (
        codec.decode(cursor, kinds=("events",), scope=user_id).position
        if cursor
        else 0
    )
    rows = list(
        session.execute(
            select(UserRecordEvent)
            .join(ChatRecord, ChatRecord.id == UserRecordEvent.record_id)
            .where(
                UserRecordEvent.user_id == user_id,
                UserRecordEvent.event_sequence > position,
            )
            .order_by(UserRecordEvent.event_sequence.asc())
            .limit(limit + 1)
        ).scalars()
    )
    page_rows = rows[:limit]
    counter = session.get(UserEventSequence, user_id)
    return UserEventPageResponse(
        events=[
            UserEventResponse(
                event_id=row.id,
                user_id=row.user_id,
                conversation_id=row.conversation_id,
                record_id=row.record_id,
                record_sequence=row.record_sequence,
                event_sequence=row.event_sequence,
                created_at=row.created_at,
            )
            for row in page_rows
        ],
        next_cursor=codec.encode(
            kind="events",
            scope=user_id,
            position=(page_rows[-1].event_sequence if page_rows else position),
        ),
        latest_event_sequence=counter.last_sequence if counter else 0,
    )


def get_user_event_tail(
    session: Session,
    *,
    user_id: str,
    codec: CursorCodec,
) -> UserEventTailResponse:
    counter = session.get(UserEventSequence, user_id)
    latest = counter.last_sequence if counter else 0
    return UserEventTailResponse(
        cursor=codec.encode(kind="events", scope=user_id, position=latest),
        latest_event_sequence=latest,
    )


def _delete_record_ids(
    session: Session, record_ids: list[str], *, deleted_at: datetime
) -> int:
    if not record_ids:
        return 0
    ledgers = list(
        session.execute(_record_ledgers_lock_statement(record_ids)).scalars()
    )
    for ledger in ledgers:
        ledger.status = "deleted"
        ledger.record_id = None
        ledger.intent_sha256 = None
        ledger.updated_at = deleted_at
        ledger.deleted_at = deleted_at
    # Session autoflush is disabled. Persist tombstones while the ledger locks
    # are held and before ON DELETE can clear the record reference itself.
    session.flush()
    session.execute(
        delete(UserRecordEvent).where(UserRecordEvent.record_id.in_(record_ids))
    )
    result = session.execute(delete(ChatRecord).where(ChatRecord.id.in_(record_ids)))
    return int(result.rowcount or 0)


def delete_records(
    session: Session, request: DeleteRecordsRequest
) -> MutationResultResponse:
    ids = list(
        session.execute(
            select(ChatRecord.id).where(
                ChatRecord.conversation_id == request.conversation_id,
                ChatRecord.id.in_(request.record_ids),
            )
        ).scalars()
    )
    completed = utcnow()
    affected = _delete_record_ids(session, ids, deleted_at=completed)
    session.add(
        RecordMutationAudit(
            id=str(uuid.uuid4()),
            operation="explicit_delete",
            conversation_id=request.conversation_id,
            requested_by_user_id=request.requested_by_user_id,
            reason=request.reason,
            requested_at=request.requested_at,
            delete_before=None,
            target_record_ids=list(request.record_ids),
            maximum_records=len(request.record_ids),
            affected_count=affected,
            completed_at=completed,
        )
    )
    session.commit()
    return MutationResultResponse(affected_count=affected, completed_at=completed)


def apply_retention(
    session: Session, request: RetentionRequest
) -> MutationResultResponse:
    query = select(ChatRecord.id).where(ChatRecord.created_at < request.delete_before)
    if request.conversation_id is not None:
        query = query.where(ChatRecord.conversation_id == request.conversation_id)
    query = query.order_by(ChatRecord.created_at.asc(), ChatRecord.id.asc())
    if request.maximum_records is not None:
        query = query.limit(request.maximum_records)
    ids = list(session.execute(query).scalars())
    completed = utcnow()
    affected = _delete_record_ids(session, ids, deleted_at=completed)
    session.add(
        RecordMutationAudit(
            id=str(uuid.uuid4()),
            operation="retention",
            conversation_id=request.conversation_id,
            requested_by_user_id=request.requested_by_user_id,
            reason=request.reason,
            requested_at=request.requested_at,
            delete_before=request.delete_before,
            target_record_ids=[],
            maximum_records=request.maximum_records,
            affected_count=affected,
            completed_at=completed,
        )
    )
    session.commit()
    return MutationResultResponse(affected_count=affected, completed_at=completed)


__all__ = [
    "AppendResult",
    "DeletedIdempotencyKeyError",
    "IdempotencyConflictError",
    "InvalidCursorError",
    "PositionBeyondConversationError",
    "RecordStoreInvariantError",
    "UnsupportedContentError",
    "advance_position",
    "append_record",
    "apply_retention",
    "combined_position",
    "delete_records",
    "get_user_event_tail",
    "list_records",
    "list_user_events",
    "resume_position",
    "unread_position",
]
