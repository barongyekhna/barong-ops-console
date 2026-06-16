from __future__ import annotations

from threading import RLock

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..models.contact_identity import ContactIdentityRecord
from ..models.org_membership import OrgMembershipRecord
from ..models.user import User
from ..schemas.conversation import (
    Conversation,
    ConversationCreateRequest,
    ConversationParticipantResolution,
    ConversationType,
    generate_direct_conversation_id,
)
from .data_isolation import without_org_data_isolation


class ConversationError(ValueError):
    pass


class ConversationNotFoundError(ConversationError):
    pass


class ConversationParticipantNotFoundError(ConversationError):
    pass


class ConversationAccessDeniedError(PermissionError):
    pass


class GroupConversationReservedError(NotImplementedError):
    pass


_DIRECT_CONVERSATION_REGISTRY: dict[str, Conversation] = {}
_REGISTRY_LOCK = RLock()


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _ensure_active_internal_actor(actor: User) -> None:
    if not actor.is_active:
        raise ConversationAccessDeniedError("Conversation access requires active user.")


def resolve_conversation_participant(
    db: Session,
    *,
    user_id: str,
) -> ConversationParticipantResolution:
    normalized_user_id = str(user_id).strip()
    if not normalized_user_id:
        raise ConversationParticipantNotFoundError(
            "Conversation participant is not in the contact directory."
        )

    statement = (
        select(ContactIdentityRecord, OrgMembershipRecord)
        .join(
            OrgMembershipRecord,
            and_(
                OrgMembershipRecord.user_id == ContactIdentityRecord.user_id,
                OrgMembershipRecord.org_id == ContactIdentityRecord.org_id,
                OrgMembershipRecord.status == "active",
            ),
        )
        .where(ContactIdentityRecord.user_id == normalized_user_id)
        .limit(1)
    )

    with without_org_data_isolation():
        row = db.execute(statement).first()

    if row is None:
        raise ConversationParticipantNotFoundError(
            "Conversation participant is not in the contact directory."
        )

    identity, membership = row
    return ConversationParticipantResolution(
        user_id=identity.user_id,
        org_id=membership.org_id,
    )


def _resolve_all_participants(
    db: Session,
    *,
    participants: list[str],
) -> tuple[ConversationParticipantResolution, ...]:
    return tuple(
        resolve_conversation_participant(db, user_id=participant)
        for participant in participants
    )


def create_or_get_conversation(
    db: Session,
    *,
    payload: ConversationCreateRequest,
    actor: User,
) -> Conversation:
    _ensure_active_internal_actor(actor)

    if payload.type == ConversationType.GROUP:
        raise GroupConversationReservedError("C19D reserves group chat schema only.")

    participants = list(payload.participants)
    actor_user_id = _actor_user_id(actor)
    if actor_user_id not in participants:
        raise ConversationAccessDeniedError(
            "Conversation actor must be one of the participants."
        )

    _resolve_all_participants(db, participants=participants)
    conversation_id = generate_direct_conversation_id(participants[0], participants[1])

    with _REGISTRY_LOCK:
        existing = _DIRECT_CONVERSATION_REGISTRY.get(conversation_id)
        if existing is not None:
            return existing

        conversation = Conversation(
            conversation_id=conversation_id,
            type=ConversationType.DIRECT,
            participants=participants,
        )
        _DIRECT_CONVERSATION_REGISTRY[conversation_id] = conversation
        return conversation


def get_conversation_for_actor(
    db: Session,
    *,
    conversation_id: str,
    actor: User,
) -> Conversation:
    _ensure_active_internal_actor(actor)

    with _REGISTRY_LOCK:
        conversation = _DIRECT_CONVERSATION_REGISTRY.get(conversation_id)

    if conversation is None:
        raise ConversationNotFoundError("Conversation not found.")

    actor_user_id = _actor_user_id(actor)
    if actor_user_id not in conversation.participants:
        raise ConversationAccessDeniedError(
            "Conversation actor must be one of the participants."
        )

    _resolve_all_participants(db, participants=conversation.participants)
    return conversation


def list_user_conversations_for_actor(
    db: Session,
    *,
    user_id: str,
    actor: User,
) -> list[Conversation]:
    _ensure_active_internal_actor(actor)

    normalized_user_id = str(user_id).strip()
    actor_user_id = _actor_user_id(actor)
    if normalized_user_id != actor_user_id:
        raise ConversationAccessDeniedError(
            "Conversation list can only be read by the target participant."
        )

    resolve_conversation_participant(db, user_id=normalized_user_id)

    with _REGISTRY_LOCK:
        candidates = [
            conversation
            for conversation in _DIRECT_CONVERSATION_REGISTRY.values()
            if normalized_user_id in conversation.participants
        ]

    conversations: list[Conversation] = []
    for conversation in candidates:
        try:
            _resolve_all_participants(db, participants=conversation.participants)
        except ConversationParticipantNotFoundError:
            continue
        conversations.append(conversation)

    return sorted(
        conversations,
        key=lambda conversation: (conversation.updated_at, conversation.conversation_id),
        reverse=True,
    )


def reset_conversation_registry_for_tests() -> None:
    with _REGISTRY_LOCK:
        _DIRECT_CONVERSATION_REGISTRY.clear()
