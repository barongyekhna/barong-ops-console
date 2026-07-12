"""Transactional record store implementation.

This module deliberately emits no log records containing chat content.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .cursors import CursorCodec, InvalidCursorError
from .models import (
    ChatRecord,
    ConversationSequence,
    ParticipantPosition,
    MomentAssetReference,
    RecordAssetCoordination,
    RecordAssetDeletionOutbox,
    RecordAssetReference as RecordAssetReferenceModel,
    RecordIdempotencyLedger,
    RecordMutationAudit,
    RecordRetentionBatch,
    RecordRetentionOperation,
    UserEventSequence,
    UserRecordEvent,
)
from .schemas import (
    CombinedPositionResponse,
    AssetDeletionClaimRequest,
    AssetDeletionClaimResponse,
    AssetDeletionCompleteRequest,
    AssetDeletionCompleteResponse,
    AssetDeletionJob,
    AssetDeletionAuthorizeRequest,
    AssetDeletionAuthorizeResponse,
    DeleteRecordsRequest,
    MutationResultResponse,
    PositionAdvanceRequest,
    ReceiptPositionResponse,
    RecordAppendRequest,
    RecordAssetReference,
    RecordPageResponse,
    RecordResponse,
    ResumePositionResponse,
    RetentionRequest,
    RetentionBatchResponse,
    UnreadPositionResponse,
    UnreadSummaryResponse,
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


class RetentionOperationConflictError(RecordStoreError):
    pass


class AssetDeletionLeaseError(RecordStoreError):
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


def _lock_asset_coordination(
    session: Session, asset_ids: list[str], *, now: datetime | None = None
) -> None:
    """Create and lock permanent asset fences in deterministic ID order.

    All Record and Moment reference writers, reference deletion, and outbox
    authorization use this same transaction fence. PostgreSQL row locks close
    the absent-row/TOCTOU window; SQLite's conflict-aware insert plus write
    transaction is the test/development fallback.
    """

    ordered = sorted(set(asset_ids))
    if not ordered:
        return
    created_at = now or utcnow()
    insert_statement = _dialect_insert(session, RecordAssetCoordination)
    for asset_id in ordered:
        if insert_statement is not None:
            session.execute(
                insert_statement.values(
                    asset_id=asset_id, created_at=created_at
                ).on_conflict_do_nothing(
                    index_elements=[RecordAssetCoordination.__table__.c.asset_id]
                )
            )
        elif session.get(RecordAssetCoordination, asset_id) is None:
            session.add(
                RecordAssetCoordination(asset_id=asset_id, created_at=created_at)
            )
            session.flush()
    list(session.scalars(_asset_coordination_lock_statement(ordered)))


def _asset_coordination_lock_statement(asset_ids: list[str]):
    return (
        select(RecordAssetCoordination)
        .where(RecordAssetCoordination.asset_id.in_(sorted(set(asset_ids))))
        .order_by(RecordAssetCoordination.asset_id)
        .with_for_update()
    )


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


def _asset_response(reference: RecordAssetReferenceModel) -> RecordAssetReference:
    return RecordAssetReference(
        asset_id=reference.asset_id,
        client_asset_id=reference.client_asset_id,
        kind=reference.kind,
        filename=reference.filename,
        media_type=reference.media_type,
        size_bytes=reference.size_bytes,
        sha256_hex=reference.sha256_hex,
        version=reference.version,
        ordinal=reference.ordinal,
    )


def _asset_references_by_record(
    session: Session, record_ids: list[str]
) -> dict[str, list[RecordAssetReference]]:
    if not record_ids:
        return {}
    result: dict[str, list[RecordAssetReference]] = {}
    rows = session.execute(
        select(RecordAssetReferenceModel)
        .where(RecordAssetReferenceModel.record_id.in_(record_ids))
        .order_by(
            RecordAssetReferenceModel.record_id,
            RecordAssetReferenceModel.ordinal,
        )
    ).scalars()
    for row in rows:
        result.setdefault(row.record_id, []).append(_asset_response(row))
    return result


def _record_response(
    record: ChatRecord,
    *,
    status: str = "sent",
    assets: list[RecordAssetReference] | None = None,
) -> RecordResponse:
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
        assets=list(assets or []),
    )


def _intent_sha256(request: RecordAppendRequest) -> str:
    """Hash only immutable user intent; never persist or log the canonical body."""

    # This v1 object and JSON encoding are deliberately byte-for-byte identical
    # to the Stage 3 implementation. Existing text/emoji retries therefore keep
    # matching ledgers written before the asset schema existed.
    intent = {
        "client_message_id": request.client_message_id,
        "content": request.content,
        "content_type": request.content_type,
        "conversation_id": request.conversation_id,
        "sender_user_id": request.sender_user_id,
    }
    if request.assets:
        intent = {
            **intent,
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "client_asset_id": asset.client_asset_id,
                    "filename": asset.filename,
                    "kind": asset.kind,
                    "media_type": asset.media_type,
                    "ordinal": asset.ordinal,
                    "sha256_hex": asset.sha256_hex,
                    "size_bytes": asset.size_bytes,
                    "version": asset.version,
                }
                for asset in request.assets
            ],
            "intent_version": 2,
        }
    canonical = json.dumps(
        intent,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _intent_version(request: RecordAppendRequest) -> int:
    return 2 if request.assets else 1


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
    intent_version: int,
    now: datetime,
) -> bool:
    insert_statement = _dialect_insert(session, RecordIdempotencyLedger)
    values = {
        "sender_user_id": request.sender_user_id,
        "client_message_id": request.client_message_id,
        "intent_sha256": intent_sha256,
        "intent_version": intent_version,
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
    intent_version: int,
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
    if (
        ledger.intent_version != intent_version
        or ledger.intent_sha256 != intent_sha256
    ):
        raise IdempotencyConflictError("idempotency key was reused")
    if ledger.status != "active" or ledger.record_id is None:
        raise RecordStoreInvariantError("active idempotency ledger is incomplete")
    record = session.get(ChatRecord, ledger.record_id)
    if record is None:
        raise RecordStoreInvariantError("active idempotency record is missing")
    assets = _asset_references_by_record(session, [record.id]).get(record.id, [])
    return AppendResult(
        _record_response(
            record,
            status=_record_status(session, record),
            assets=assets,
        ),
        True,
    )


def _validate_content(request: RecordAppendRequest, max_message_chars: int) -> None:
    if request.content_type in {"image", "file"}:
        if len(request.assets) != 1 or request.assets[0].kind != request.content_type:
            raise UnsupportedContentError(
                "image and file records require one matching asset"
            )
        if len(request.content) > min(max_message_chars, 4_000):
            raise UnsupportedContentError("asset caption exceeds configured limit")
        return
    if request.assets:
        raise UnsupportedContentError("text and emoji records cannot contain assets")
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
    intent_version = _intent_version(request)
    claimed = _claim_idempotency_key(
        session,
        request,
        intent_sha256=intent_sha256,
        intent_version=intent_version,
        now=persisted_at,
    )
    if not claimed:
        return _resolve_idempotent_replay(
            session,
            request,
            intent_sha256=intent_sha256,
            intent_version=intent_version,
        )
    try:
        _validate_content(request, max_message_chars)
        if request.assets:
            _lock_asset_coordination(
                session,
                [asset.asset_id for asset in request.assets],
                now=persisted_at,
            )
            retired_asset = session.scalar(
                select(RecordAssetDeletionOutbox.asset_id)
                .where(
                    RecordAssetDeletionOutbox.asset_id.in_(
                        [asset.asset_id for asset in request.assets]
                    )
                )
                .limit(1)
            )
            if retired_asset is not None:
                raise RecordStoreInvariantError(
                    "asset identifier is already governed by retention"
                )
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
        for asset in request.assets:
            session.add(
                RecordAssetReferenceModel(
                    id=str(uuid.uuid4()),
                    record_id=record.id,
                    asset_id=asset.asset_id,
                    client_asset_id=asset.client_asset_id,
                    kind=asset.kind,
                    filename=asset.filename,
                    media_type=asset.media_type,
                    size_bytes=asset.size_bytes,
                    sha256_hex=asset.sha256_hex,
                    version=asset.version,
                    ordinal=asset.ordinal,
                )
            )
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
        return AppendResult(
            _record_response(record, assets=list(request.assets)),
            False,
        )
    except (UnsupportedContentError, RecordStoreInvariantError):
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        try:
            return _resolve_idempotent_replay(
                session,
                request,
                intent_sha256=intent_sha256,
                intent_version=intent_version,
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

    assets_by_record = _asset_references_by_record(
        session, [record.id for record in page_rows]
    )
    return RecordPageResponse(
        records=[
            _record_response(
                row,
                status=aggregate_status(row),
                assets=assets_by_record.get(row.id, []),
            )
            for row in page_rows
        ],
        next_cursor=next_cursor,
        latest_sequence=latest,
    )


def get_visible_record(
    session: Session,
    *,
    conversation_id: str,
    record_id: str,
    user_id: str,
) -> RecordResponse | None:
    """Return a record only when its immutable event audience includes the user."""

    record = session.execute(
        select(ChatRecord)
        .join(UserRecordEvent, UserRecordEvent.record_id == ChatRecord.id)
        .where(
            ChatRecord.id == record_id,
            ChatRecord.conversation_id == conversation_id,
            UserRecordEvent.user_id == user_id,
            UserRecordEvent.conversation_id == conversation_id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if record is None:
        return None
    assets = _asset_references_by_record(session, [record.id]).get(record.id, [])
    return _record_response(
        record,
        status=_record_status(session, record),
        assets=assets,
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
        select(
            func.count(UserRecordEvent.id),
            func.min(UserRecordEvent.record_sequence),
        )
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


def unread_summary(
    session: Session, *, user_id: str, conversation_ids: list[str]
) -> UnreadSummaryResponse:
    """Aggregate unread recipient events without loading record content.

    Barong supplies only conversations the caller may currently access.  The
    Record Service deliberately does not discover or widen that set.
    """

    if not conversation_ids:
        return UnreadSummaryResponse(
            total_unread_count=0,
            unread_conversation_count=0,
        )
    total, conversations = session.execute(
        select(
            func.count(UserRecordEvent.id),
            func.count(func.distinct(UserRecordEvent.conversation_id)),
        )
        .join(ChatRecord, ChatRecord.id == UserRecordEvent.record_id)
        .outerjoin(
            ParticipantPosition,
            and_(
                ParticipantPosition.conversation_id
                == UserRecordEvent.conversation_id,
                ParticipantPosition.user_id == user_id,
            ),
        )
        .where(
            UserRecordEvent.user_id == user_id,
            UserRecordEvent.conversation_id.in_(conversation_ids),
            ChatRecord.sender_user_id != user_id,
            UserRecordEvent.record_sequence
            > func.coalesce(ParticipantPosition.read_through_sequence, 0),
        )
    ).one()
    return UnreadSummaryResponse(
        total_unread_count=int(total or 0),
        unread_conversation_count=int(conversations or 0),
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
    session: Session,
    record_ids: list[str],
    *,
    deleted_at: datetime,
    retention_operation_id: str | None = None,
) -> tuple[int, int]:
    if not record_ids:
        return 0, 0
    asset_rows = session.execute(
        select(
            RecordAssetReferenceModel.asset_id,
            RecordAssetReferenceModel.record_id,
            ChatRecord.conversation_id,
        )
        .join(ChatRecord, ChatRecord.id == RecordAssetReferenceModel.record_id)
        .where(RecordAssetReferenceModel.record_id.in_(record_ids))
        .order_by(
            RecordAssetReferenceModel.record_id,
            RecordAssetReferenceModel.asset_id,
        )
    ).all()
    _lock_asset_coordination(
        session,
        [asset_id for asset_id, _record_id, _conversation_id in asset_rows],
        now=deleted_at,
    )
    outbox_insert = _dialect_insert(session, RecordAssetDeletionOutbox)
    inserted_outbox_count = 0
    for asset_id, record_id, conversation_id in asset_rows:
        values = {
            "id": str(uuid.uuid4()),
            "asset_id": asset_id,
            "record_id": record_id,
            "conversation_id": conversation_id,
            "retention_operation_id": retention_operation_id,
            "state": "pending",
            "attempt_count": 0,
            "created_at": deleted_at,
            "last_attempt_at": None,
            "lease_owner": None,
            "lease_until": None,
            "authorized_at": None,
            "outcome": None,
            "completed_at": None,
        }
        if outbox_insert is not None:
            inserted = session.execute(
                outbox_insert.values(**values)
                .on_conflict_do_nothing(
                    index_elements=[
                        RecordAssetDeletionOutbox.__table__.c.record_id,
                        RecordAssetDeletionOutbox.__table__.c.asset_id,
                    ]
                )
                .returning(RecordAssetDeletionOutbox.__table__.c.id)
            ).scalar_one_or_none()
            inserted_outbox_count += int(inserted is not None)
        else:
            existing = session.scalar(
                select(RecordAssetDeletionOutbox.id).where(
                    RecordAssetDeletionOutbox.record_id == record_id,
                    RecordAssetDeletionOutbox.asset_id == asset_id,
                )
            )
            if existing is None:
                session.add(RecordAssetDeletionOutbox(**values))
                inserted_outbox_count += 1
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
    return int(result.rowcount or 0), inserted_outbox_count


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
    affected, _enqueued = _delete_record_ids(session, ids, deleted_at=completed)
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


def _expected_retention_operation_id(request: RetentionRequest) -> str:
    evidence = {
        "approved_maximum_asset_jobs": request.approved_maximum_asset_jobs,
        "approved_maximum_records": request.approved_maximum_records,
        "conversation_id": request.conversation_id,
        "delete_before": request.delete_before.isoformat(),
        "reason": request.reason,
        "requested_by_user_id": request.requested_by_user_id,
    }
    digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"rtn_{digest}"


def apply_retention(
    session: Session, request: RetentionRequest
) -> RetentionBatchResponse:
    if request.operation_id != _expected_retention_operation_id(request):
        raise RetentionOperationConflictError("retention operation id mismatch")
    now = utcnow()
    insert_statement = _dialect_insert(session, RecordRetentionOperation)
    values = {
        "operation_id": request.operation_id,
        "requested_by_user_id": request.requested_by_user_id,
        "reason": request.reason,
        "delete_before": request.delete_before,
        "conversation_id": request.conversation_id,
        "approved_maximum_records": request.approved_maximum_records,
        "approved_maximum_asset_jobs": request.approved_maximum_asset_jobs,
        "affected_count": 0,
        "asset_jobs_enqueued_count": 0,
        "asset_jobs_completed_count": 0,
        "next_batch_ordinal": 0,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }
    if insert_statement is not None:
        session.execute(
            insert_statement.values(**values).on_conflict_do_nothing(
                index_elements=[RecordRetentionOperation.__table__.c.operation_id]
            )
        )
    elif session.get(RecordRetentionOperation, request.operation_id) is None:
        session.add(RecordRetentionOperation(**values))
        session.flush()

    operation = session.execute(
        select(RecordRetentionOperation)
        .where(RecordRetentionOperation.operation_id == request.operation_id)
        .with_for_update()
    ).scalar_one_or_none()
    if operation is None:
        raise RecordStoreInvariantError("retention operation claim disappeared")
    if (
        operation.requested_by_user_id != request.requested_by_user_id
        or operation.reason != request.reason
        or operation.delete_before != request.delete_before
        or operation.conversation_id != request.conversation_id
        or operation.approved_maximum_records
        != request.approved_maximum_records
        or operation.approved_maximum_asset_jobs
        != request.approved_maximum_asset_jobs
    ):
        raise RetentionOperationConflictError("retention policy conflict")

    replay = session.get(
        RecordRetentionBatch, (request.operation_id, request.batch_ordinal)
    )
    if replay is not None:
        if replay.maximum_records != request.maximum_records:
            raise RetentionOperationConflictError("retention batch size conflict")
        return RetentionBatchResponse(
            operation_id=replay.operation_id,
            batch_ordinal=replay.batch_ordinal,
            affected_count=replay.affected_count,
            cumulative_affected_count=replay.cumulative_affected_count,
            operation_complete=replay.operation_complete,
            completed_at=replay.completed_at,
        )
    if operation.completed_at is not None:
        raise RetentionOperationConflictError("retention operation is complete")
    if request.batch_ordinal != operation.next_batch_ordinal:
        raise RetentionOperationConflictError("retention batch ordinal conflict")
    remaining = operation.approved_maximum_records - operation.affected_count
    if request.maximum_records > remaining:
        raise RetentionOperationConflictError(
            "retention batch exceeds approved operation maximum"
        )
    query = select(ChatRecord.id).where(ChatRecord.created_at < request.delete_before)
    if request.conversation_id is not None:
        query = query.where(ChatRecord.conversation_id == request.conversation_id)
    query = query.order_by(ChatRecord.created_at.asc(), ChatRecord.id.asc())
    query = query.limit(request.maximum_records)
    candidate_ids = list(session.execute(query).scalars())
    remaining_asset_jobs = (
        operation.approved_maximum_asset_jobs
        - operation.asset_jobs_enqueued_count
    )
    asset_counts = {
        record_id: int(count)
        for record_id, count in session.execute(
            select(
                RecordAssetReferenceModel.record_id,
                func.count(RecordAssetReferenceModel.id),
            )
            .where(RecordAssetReferenceModel.record_id.in_(candidate_ids))
            .group_by(RecordAssetReferenceModel.record_id)
        ).all()
    }
    ids: list[str] = []
    enqueued_jobs = 0
    asset_budget_exhausted = False
    for record_id in candidate_ids:
        reference_count = asset_counts.get(record_id, 0)
        if enqueued_jobs + reference_count > remaining_asset_jobs:
            asset_budget_exhausted = True
            break
        ids.append(record_id)
        enqueued_jobs += reference_count
    completed = utcnow()
    affected, actually_enqueued_jobs = _delete_record_ids(
        session,
        ids,
        deleted_at=completed,
        retention_operation_id=request.operation_id,
    )
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
    cumulative = operation.affected_count + affected
    operation.affected_count = cumulative
    operation.asset_jobs_enqueued_count += actually_enqueued_jobs
    operation.next_batch_ordinal += 1
    operation.updated_at = completed
    operation_complete = (
        asset_budget_exhausted
        or operation.asset_jobs_enqueued_count
        >= operation.approved_maximum_asset_jobs
        or affected < request.maximum_records
        or cumulative >= operation.approved_maximum_records
    )
    if operation_complete:
        operation.completed_at = completed
    session.add(
        RecordRetentionBatch(
            operation_id=request.operation_id,
            batch_ordinal=request.batch_ordinal,
            maximum_records=request.maximum_records,
            affected_count=affected,
            cumulative_affected_count=cumulative,
            operation_complete=operation_complete,
            completed_at=completed,
        )
    )
    session.commit()
    return RetentionBatchResponse(
        operation_id=request.operation_id,
        batch_ordinal=request.batch_ordinal,
        affected_count=affected,
        cumulative_affected_count=cumulative,
        operation_complete=operation_complete,
        completed_at=completed,
    )


def claim_asset_deletions(
    session: Session, request: AssetDeletionClaimRequest
) -> AssetDeletionClaimResponse:
    now = utcnow()
    has_chat_reference = exists().where(
        RecordAssetReferenceModel.asset_id == RecordAssetDeletionOutbox.asset_id
    )
    has_moment_reference = exists().where(
        MomentAssetReference.asset_id == RecordAssetDeletionOutbox.asset_id
    )
    operation_scope = (
        RecordAssetDeletionOutbox.retention_operation_id
        == request.retention_operation_id
        if request.retention_operation_id is not None
        else True
    )
    blocked = int(
        session.scalar(
            select(func.count(RecordAssetDeletionOutbox.id)).where(
                RecordAssetDeletionOutbox.state == "pending",
                operation_scope,
                or_(has_chat_reference, has_moment_reference),
            )
        )
        or 0
    )
    active_state = RecordAssetDeletionOutbox.state.in_(("pending", "authorized"))
    leased = int(
        session.scalar(
            select(func.count(RecordAssetDeletionOutbox.id)).where(
                active_state,
                operation_scope,
                RecordAssetDeletionOutbox.lease_until > now,
                or_(
                    RecordAssetDeletionOutbox.state == "authorized",
                    and_(~has_chat_reference, ~has_moment_reference),
                ),
            )
        )
        or 0
    )
    eligible = int(
        session.scalar(
            select(func.count(RecordAssetDeletionOutbox.id)).where(
                active_state,
                operation_scope,
                or_(
                    RecordAssetDeletionOutbox.lease_until.is_(None),
                    RecordAssetDeletionOutbox.lease_until <= now,
                ),
                or_(
                    RecordAssetDeletionOutbox.state == "authorized",
                    and_(~has_chat_reference, ~has_moment_reference),
                ),
            )
        )
        or 0
    )
    jobs = list(
        session.scalars(
            select(RecordAssetDeletionOutbox)
            .where(
                active_state,
                operation_scope,
                or_(
                    RecordAssetDeletionOutbox.lease_until.is_(None),
                    RecordAssetDeletionOutbox.lease_until <= now,
                ),
                or_(
                    RecordAssetDeletionOutbox.state == "authorized",
                    and_(~has_chat_reference, ~has_moment_reference),
                ),
            )
            .order_by(
                RecordAssetDeletionOutbox.created_at,
                RecordAssetDeletionOutbox.id,
            )
            .limit(request.limit)
            .with_for_update(skip_locked=True)
        )
    )
    _lock_asset_coordination(
        session, [job.asset_id for job in jobs], now=now
    )
    deliverable: list[RecordAssetDeletionOutbox] = []
    for job in jobs:
        referenced = session.scalar(
            select(RecordAssetReferenceModel.id)
            .where(RecordAssetReferenceModel.asset_id == job.asset_id)
            .limit(1)
        ) or session.scalar(
            select(MomentAssetReference.id)
            .where(MomentAssetReference.asset_id == job.asset_id)
            .limit(1)
        )
        if referenced is not None:
            if job.state == "authorized":
                # Defensive corruption containment. A correctly fenced writer
                # cannot create this state, but delivery must still fail closed.
                job.state = "pending"
                job.authorized_at = None
                job.lease_owner = None
                job.lease_until = None
            continue
        deliverable.append(job)
    jobs = deliverable
    lease_until = now + timedelta(seconds=request.lease_seconds)
    for job in jobs:
        job.attempt_count += 1
        job.last_attempt_at = now
        job.lease_owner = request.worker_id
        job.lease_until = lease_until
    session.commit()
    return AssetDeletionClaimResponse(
        jobs=[
            AssetDeletionJob(
                job_id=job.id,
                asset_id=job.asset_id,
                record_id=job.record_id,
                conversation_id=job.conversation_id,
                phase="commit" if job.state == "authorized" else "prepare",
            )
            for job in jobs
        ],
        eligible_count=eligible,
        blocked_count=blocked,
        leased_count=leased,
    )


def authorize_asset_deletion(
    session: Session,
    *,
    job_id: str,
    request: AssetDeletionAuthorizeRequest,
) -> AssetDeletionAuthorizeResponse:
    now = utcnow()
    job = session.execute(
        select(RecordAssetDeletionOutbox)
        .where(RecordAssetDeletionOutbox.id == job_id)
        .with_for_update()
    ).scalar_one_or_none()
    if job is None:
        raise AssetDeletionLeaseError("asset deletion job not found")
    if job.state == "authorized":
        return AssetDeletionAuthorizeResponse(job_id=job.id, state="authorized")
    if job.state != "pending":
        raise AssetDeletionLeaseError("asset deletion authorization conflict")
    if (
        job.lease_owner != request.worker_id
        or job.lease_until is None
        or job.lease_until <= now
    ):
        raise AssetDeletionLeaseError("asset deletion lease is not active")
    _lock_asset_coordination(session, [job.asset_id], now=now)
    referenced = session.scalar(
        select(RecordAssetReferenceModel.id)
        .where(RecordAssetReferenceModel.asset_id == job.asset_id)
        .limit(1)
    ) or session.scalar(
        select(MomentAssetReference.id)
        .where(MomentAssetReference.asset_id == job.asset_id)
        .limit(1)
    )
    if referenced is not None:
        job.lease_owner = None
        job.lease_until = None
        session.commit()
        return AssetDeletionAuthorizeResponse(job_id=job.id, state="blocked")
    job.state = "authorized"
    job.authorized_at = now
    session.commit()
    return AssetDeletionAuthorizeResponse(job_id=job.id, state="authorized")


def complete_asset_deletion(
    session: Session,
    *,
    job_id: str,
    request: AssetDeletionCompleteRequest,
) -> AssetDeletionCompleteResponse:
    now = utcnow()
    job = session.execute(
        select(RecordAssetDeletionOutbox)
        .where(RecordAssetDeletionOutbox.id == job_id)
        .with_for_update()
    ).scalar_one_or_none()
    if job is None:
        raise AssetDeletionLeaseError("asset deletion job not found")
    expected_state = "completed" if request.outcome == "accepted" else "protected"
    if job.state in {"completed", "protected"}:
        if job.state != expected_state or job.outcome != request.outcome:
            raise AssetDeletionLeaseError("asset deletion outcome conflict")
        return AssetDeletionCompleteResponse(
            job_id=job.id, state=job.state, outcome=job.outcome
        )
    required_source_states = (
        {"authorized"} if request.outcome == "accepted" else {"pending", "authorized"}
    )
    if job.state not in required_source_states:
        raise AssetDeletionLeaseError("asset deletion phase conflict")
    if (
        job.lease_owner != request.worker_id
        or job.lease_until is None
        or job.lease_until <= now
    ):
        raise AssetDeletionLeaseError("asset deletion lease is not active")
    job.state = expected_state
    job.outcome = request.outcome
    job.completed_at = now
    job.lease_owner = None
    job.lease_until = None
    if job.retention_operation_id is not None:
        operation = session.execute(
            select(RecordRetentionOperation)
            .where(
                RecordRetentionOperation.operation_id
                == job.retention_operation_id
            )
            .with_for_update()
        ).scalar_one_or_none()
        if operation is None:
            raise RecordStoreInvariantError(
                "asset deletion retention operation is missing"
            )
        if (
            operation.asset_jobs_completed_count
            >= operation.asset_jobs_enqueued_count
        ):
            raise RecordStoreInvariantError(
                "asset deletion operation progress is inconsistent"
            )
        operation.asset_jobs_completed_count += 1
        operation.updated_at = now
    session.commit()
    return AssetDeletionCompleteResponse(
        job_id=job.id, state=job.state, outcome=job.outcome
    )


__all__ = [
    "AppendResult",
    "DeletedIdempotencyKeyError",
    "IdempotencyConflictError",
    "InvalidCursorError",
    "PositionBeyondConversationError",
    "RecordStoreInvariantError",
    "UnsupportedContentError",
    "AssetDeletionLeaseError",
    "RetentionOperationConflictError",
    "advance_position",
    "append_record",
    "apply_retention",
    "authorize_asset_deletion",
    "claim_asset_deletions",
    "complete_asset_deletion",
    "combined_position",
    "delete_records",
    "get_visible_record",
    "get_user_event_tail",
    "list_records",
    "list_user_events",
    "resume_position",
    "unread_position",
    "unread_summary",
]
