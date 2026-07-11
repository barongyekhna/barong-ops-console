"""Authorization and orchestration for externally persisted C19 messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from .conversation_repository import (
    active_block_exists_across,
    get_conversation,
    get_conversation_member,
    list_authorized_affiliation_ids_for_users,
    list_authorized_affiliations,
    list_conversation_members,
)
from .message_schemas import (
    ChatReceiptPositionRead,
    ChatRecordPageRead,
    ChatRecordRead,
    ChatResumePositionRead,
    ChatUnreadPositionRead,
    ChatUserEventPageRead,
    ChatUserEventRead,
    ChatUserEventTailRead,
    MessageCreateRequest,
)
from .storage import (
    ChatPositionAdvanceDTO,
    ChatPositionQueryDTO,
    ChatReceiptPositionDTO,
    ChatRecordAppendDTO,
    ChatRecordDTO,
    ChatRecordPageDTO,
    ChatRecordQueryDTO,
    ChatRecordStore,
    ChatResumePositionDTO,
    ChatUnreadPositionDTO,
    ChatUserEventPageDTO,
    ChatUserEventQueryDTO,
)


class C19ChatAccessError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class AuthorizedConversation:
    conversation_id: str
    actor_user_id: int
    actor_org_id: str
    recipient_user_ids: tuple[int, ...]
    recipient_org_ids: tuple[str, ...]


def _deny_access() -> C19ChatAccessError:
    return C19ChatAccessError(
        code="c19_conversation_unavailable",
        message="Conversation is unavailable.",
        status_code=404,
    )


def _actor_user_id(actor: User) -> int:
    if not actor.is_active:
        raise C19ChatAccessError(
            code="c19_access_denied",
            message="C19 access denied.",
            status_code=403,
        )
    try:
        user_id = int(actor.id)
    except (TypeError, ValueError):
        raise C19ChatAccessError(
            code="c19_access_denied",
            message="C19 access denied.",
            status_code=403,
        ) from None
    if user_id <= 0:
        raise C19ChatAccessError(
            code="c19_access_denied",
            message="C19 access denied.",
            status_code=403,
        )
    return user_id


def _require_active_actor(db: Session, *, actor: User) -> int:
    actor_user_id = _actor_user_id(actor)
    with without_org_data_isolation():
        affiliations = list_authorized_affiliations(db, user_id=actor_user_id)
    if not affiliations:
        raise C19ChatAccessError(
            code="c19_access_denied",
            message="C19 access denied.",
            status_code=403,
        )
    return actor_user_id


def authorize_conversation(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    for_send: bool = False,
) -> AuthorizedConversation:
    """Authorize actor access and optionally resolve current send recipients."""

    actor_user_id = _actor_user_id(actor)
    with without_org_data_isolation():
        conversation = get_conversation(db, conversation_id=conversation_id)
        if conversation is None or conversation.status == "closed":
            raise _deny_access()
        actor_member = get_conversation_member(
            db,
            conversation_id=conversation_id,
            user_id=actor_user_id,
        )
        if actor_member is None or actor_member.status != "active":
            raise _deny_access()
        actor_affiliations = list_authorized_affiliations(
            db,
            user_id=actor_user_id,
        )
        if actor_member.affiliation_id not in {
            affiliation.affiliation_id for affiliation in actor_affiliations
        }:
            raise _deny_access()

        recipients = ()
        if for_send:
            active_members = list_conversation_members(
                db,
                conversation_id=conversation_id,
                active_only=True,
            )
            candidates = tuple(
                member
                for member in active_members
                if member.user_id != actor_user_id
            )
            authorized_affiliation_ids = list_authorized_affiliation_ids_for_users(
                db,
                user_ids={member.user_id for member in candidates},
            )
            recipients = tuple(
                member
                for member in candidates
                if member.affiliation_id in authorized_affiliation_ids
            )
            if conversation.conversation_type == "direct" and len(recipients) != 1:
                raise _deny_access()
            if not recipients:
                raise _deny_access()
            recipient_user_ids = {member.user_id for member in recipients}
            if active_block_exists_across(
                db,
                candidate_user_ids={actor_user_id},
                participant_user_ids=recipient_user_ids,
            ):
                raise _deny_access()

    return AuthorizedConversation(
        conversation_id=conversation_id,
        actor_user_id=actor_user_id,
        actor_org_id=actor_member.org_id_at_join,
        recipient_user_ids=tuple(member.user_id for member in recipients),
        recipient_org_ids=tuple(
            dict.fromkeys(member.org_id_at_join for member in recipients)
        ),
    )


def _record_read(record: ChatRecordDTO) -> ChatRecordRead:
    return ChatRecordRead(
        record_id=record.record_id,
        client_message_id=record.client_message_id,
        conversation_id=record.conversation_id,
        sequence=record.sequence,
        sender_user_id=record.sender_user_id,
        recipient_user_ids=list(record.recipient_user_ids),
        content_type=record.content_type,
        content=record.content,
        status=record.status,
        created_at=record.created_at,
        persisted_at=record.persisted_at,
        sender_org_id=record.sender_org_id,
        recipient_org_ids=list(record.recipient_org_ids),
        metadata=dict(record.metadata),
    )


def _record_page_read(page: ChatRecordPageDTO) -> ChatRecordPageRead:
    return ChatRecordPageRead(
        records=[_record_read(record) for record in page.records],
        next_cursor=page.next_cursor,
        latest_sequence=page.latest_sequence,
    )


def _receipt_read(position: ChatReceiptPositionDTO) -> ChatReceiptPositionRead:
    return ChatReceiptPositionRead(
        conversation_id=position.conversation_id,
        user_id=position.user_id,
        delivered_through_sequence=position.delivered_through_sequence,
        read_through_sequence=position.read_through_sequence,
        updated_at=position.updated_at,
    )


def _unread_read(position: ChatUnreadPositionDTO) -> ChatUnreadPositionRead:
    return ChatUnreadPositionRead(
        conversation_id=position.conversation_id,
        user_id=position.user_id,
        unread_count=position.unread_count,
        first_unread_sequence=position.first_unread_sequence,
        latest_sequence=position.latest_sequence,
    )


def _resume_read(position: ChatResumePositionDTO) -> ChatResumePositionRead:
    return ChatResumePositionRead(
        conversation_id=position.conversation_id,
        user_id=position.user_id,
        resume_cursor=position.resume_cursor,
        delivered_through_sequence=position.delivered_through_sequence,
        read_through_sequence=position.read_through_sequence,
        latest_sequence=position.latest_sequence,
    )


async def send_message(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    payload: MessageCreateRequest,
    store: ChatRecordStore,
) -> ChatRecordRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
        for_send=True,
    )
    db.rollback()  # Never hold a control-database transaction across HTTP I/O.
    command = ChatRecordAppendDTO(
        client_message_id=payload.client_message_id,
        conversation_id=conversation_id,
        sender_user_id=str(access.actor_user_id),
        recipient_user_ids=tuple(str(item) for item in access.recipient_user_ids),
        content_type=payload.content_type,
        content=payload.content,
        created_at=datetime.now(UTC),
        sender_org_id=access.actor_org_id,
        recipient_org_ids=access.recipient_org_ids,
    )
    record = await store.append_record(command)
    if (
        record.content_type != command.content_type
        or record.content != command.content
    ):
        from .http_record_store import ChatRecordStoreProtocolError

        raise ChatRecordStoreProtocolError(operation="append_record")
    return _record_read(record)


async def list_message_history(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    limit: int,
    cursor: str | None,
    store: ChatRecordStore,
) -> ChatRecordPageRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
    )
    db.rollback()
    page = await store.list_records(
        ChatRecordQueryDTO(
            conversation_id=conversation_id,
            user_id=str(access.actor_user_id),
            limit=limit,
            cursor=cursor,
        )
    )
    return _record_page_read(page)


async def advance_message_position(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    through_sequence: int,
    position: str,
    store: ChatRecordStore,
) -> ChatReceiptPositionRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
    )
    db.rollback()
    command = ChatPositionAdvanceDTO(
        conversation_id=conversation_id,
        user_id=str(access.actor_user_id),
        through_sequence=through_sequence,
        occurred_at=datetime.now(UTC),
    )
    if position == "delivery":
        result = await store.advance_delivery(command)
    elif position == "read":
        result = await store.advance_read(command)
    else:  # pragma: no cover - route/service invariant
        raise ValueError("Unsupported chat position.")
    return _receipt_read(result)


async def get_unread(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    store: ChatRecordStore,
) -> ChatUnreadPositionRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
    )
    db.rollback()
    result = await store.get_unread_position(
        ChatPositionQueryDTO(
            conversation_id=conversation_id,
            user_id=str(access.actor_user_id),
        )
    )
    return _unread_read(result)


async def get_resume(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    store: ChatRecordStore,
) -> ChatResumePositionRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
    )
    db.rollback()
    result = await store.get_resume_position(
        ChatPositionQueryDTO(
            conversation_id=conversation_id,
            user_id=str(access.actor_user_id),
        )
    )
    return _resume_read(result)


async def list_user_events(
    db: Session,
    *,
    actor: User,
    limit: int,
    cursor: str | None,
    store: ChatRecordStore,
) -> ChatUserEventPageRead:
    actor_user_id = _require_active_actor(db, actor=actor)
    db.rollback()
    page: ChatUserEventPageDTO = await store.list_user_events(
        ChatUserEventQueryDTO(
            user_id=str(actor_user_id),
            limit=limit,
            cursor=cursor,
        )
    )

    authorized: dict[str, bool] = {}
    visible: list[ChatUserEventRead] = []
    for event in page.events:
        allowed = authorized.get(event.conversation_id)
        if allowed is None:
            try:
                authorize_conversation(
                    db,
                    actor=actor,
                    conversation_id=event.conversation_id,
                )
                allowed = True
            except C19ChatAccessError:
                allowed = False
            authorized[event.conversation_id] = allowed
        if allowed:
            visible.append(
                ChatUserEventRead(
                    event_id=event.event_id,
                    user_id=event.user_id,
                    conversation_id=event.conversation_id,
                    record_id=event.record_id,
                    record_sequence=event.record_sequence,
                    event_sequence=event.event_sequence,
                    created_at=event.created_at,
                )
            )
    db.rollback()
    return ChatUserEventPageRead(
        events=visible,
        next_cursor=page.next_cursor,
        latest_event_sequence=page.latest_event_sequence,
    )


async def get_user_event_tail(
    db: Session,
    *,
    actor: User,
    store: ChatRecordStore,
) -> ChatUserEventTailRead:
    actor_user_id = _require_active_actor(db, actor=actor)
    db.rollback()
    tail = await store.get_user_event_tail(str(actor_user_id))
    if tail.user_id != str(actor_user_id):
        from .http_record_store import ChatRecordStoreProtocolError

        raise ChatRecordStoreProtocolError(operation="get_user_event_tail")
    return ChatUserEventTailRead(
        cursor=tail.cursor,
        latest_event_sequence=tail.latest_event_sequence,
    )


__all__ = [
    "AuthorizedConversation",
    "C19ChatAccessError",
    "advance_message_position",
    "authorize_conversation",
    "get_resume",
    "get_user_event_tail",
    "get_unread",
    "list_message_history",
    "list_user_events",
    "send_message",
]
