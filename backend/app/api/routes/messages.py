from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, status

from ...models.user import User
from ...schemas.message import (
    MessageApiRuntimeNotice,
    MessageOperation,
    MessageReadRequest,
    MessageSendRequest,
)
from ..deps import get_current_user

router = APIRouter(prefix="/messages", tags=["messages"])
ConversationIdPath = Annotated[str, Path(min_length=1, max_length=64)]


def _schema_only(operation: MessageOperation) -> NoReturn:
    notice = MessageApiRuntimeNotice(operation=operation)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=notice.model_dump(mode="json"),
    )


@router.post(
    "/send",
    response_model=MessageApiRuntimeNotice,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"description": "C19C schema only"}},
)
def send_message(
    payload: MessageSendRequest,
    actor: User = Depends(get_current_user),
) -> MessageApiRuntimeNotice:
    del payload, actor
    _schema_only(MessageOperation.SEND)


@router.get(
    "/{conversation_id}",
    response_model=MessageApiRuntimeNotice,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"description": "C19C schema only"}},
)
def get_messages(
    conversation_id: ConversationIdPath,
    actor: User = Depends(get_current_user),
) -> MessageApiRuntimeNotice:
    del conversation_id, actor
    _schema_only(MessageOperation.FETCH_BY_CONVERSATION)


@router.post(
    "/read",
    response_model=MessageApiRuntimeNotice,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"description": "C19C schema only"}},
)
def mark_messages_read(
    payload: MessageReadRequest,
    actor: User = Depends(get_current_user),
) -> MessageApiRuntimeNotice:
    del payload, actor
    _schema_only(MessageOperation.MARK_READ)
