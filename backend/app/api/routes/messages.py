from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.cross_org_communication import CrossOrgMessageSendDecision
from ...schemas.message import (
    MessageApiRuntimeNotice,
    MessageOperation,
    MessageReadRequest,
    MessageSendRequest,
)
from ...services.conversation_service import (
    ConversationAccessDeniedError,
    ConversationNotFoundError,
    ConversationParticipantNotFoundError,
)
from ...services.cross_org_communication import send_message_after_cross_org_check
from ..deps import get_audit_context, get_current_user

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
    response_model=CrossOrgMessageSendDecision,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "C19E communication denied"},
        status.HTTP_404_NOT_FOUND: {"description": "Conversation not found"},
    },
)
def send_message(
    payload: MessageSendRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CrossOrgMessageSendDecision:
    try:
        decision = send_message_after_cross_org_check(
            db,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except ConversationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        ) from None
    except ConversationParticipantNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation participant not found in contact directory.",
        ) from None
    except ConversationAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation access denied.",
        ) from None

    if decision.denied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=decision.model_dump(mode="json"),
        )
    return decision


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
