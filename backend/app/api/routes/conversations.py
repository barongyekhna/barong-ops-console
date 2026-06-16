from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.conversation import (
    CONVERSATION_ID_PATTERN,
    Conversation,
    ConversationApiRuntimeNotice,
    ConversationCreateRequest,
    ConversationOperation,
)
from ...services.conversation_service import (
    ConversationAccessDeniedError,
    ConversationNotFoundError,
    ConversationParticipantNotFoundError,
    GroupConversationReservedError,
    create_or_get_conversation,
    get_conversation_for_actor,
    list_user_conversations_for_actor,
)
from ..deps import get_current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])
ConversationIdPath = Annotated[str, Path(min_length=1, max_length=64)]
UserIdPath = Annotated[str, Path(min_length=1, max_length=255)]


def _raise_conversation_error(
    exc: Exception,
    *,
    operation: ConversationOperation,
) -> NoReturn:
    if isinstance(exc, GroupConversationReservedError):
        notice = ConversationApiRuntimeNotice(
            operation=operation,
            detail="C19D defines the group conversation schema only; group logic is reserved.",
        )
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=notice.model_dump(mode="json"),
        ) from None

    if isinstance(exc, ConversationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        ) from None

    if isinstance(exc, ConversationParticipantNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation participant not found in contact directory.",
        ) from None

    if isinstance(exc, ConversationAccessDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation access denied.",
        ) from None

    raise exc


@router.post(
    "/create",
    response_model=Conversation,
    responses={
        status.HTTP_501_NOT_IMPLEMENTED: {"description": "Group chat reserved"},
    },
)
def create_conversation(
    payload: ConversationCreateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Conversation:
    try:
        return create_or_get_conversation(db, payload=payload, actor=actor)
    except Exception as exc:
        _raise_conversation_error(exc, operation=ConversationOperation.CREATE)


@router.get("/user/{user_id}", response_model=list[Conversation])
def list_user_conversations(
    user_id: UserIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[Conversation]:
    try:
        return list_user_conversations_for_actor(
            db,
            user_id=user_id,
            actor=actor,
        )
    except Exception as exc:
        _raise_conversation_error(exc, operation=ConversationOperation.LIST_BY_USER)


@router.get("/{conversation_id}", response_model=Conversation)
def get_conversation(
    conversation_id: ConversationIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Conversation:
    if CONVERSATION_ID_PATTERN.fullmatch(conversation_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    try:
        return get_conversation_for_actor(
            db,
            conversation_id=conversation_id,
            actor=actor,
        )
    except Exception as exc:
        _raise_conversation_error(exc, operation=ConversationOperation.GET)
