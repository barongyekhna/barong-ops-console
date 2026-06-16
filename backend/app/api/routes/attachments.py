from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, status

from ...models.user import User
from ...schemas.attachment import (
    AttachmentApiRuntimeNotice,
    AttachmentOperation,
)
from ..deps import get_current_user


router = APIRouter(prefix="/attachments", tags=["attachments"])
MessageIdPath = Annotated[str, Path(min_length=1, max_length=64)]


def _schema_only(operation: AttachmentOperation) -> NoReturn:
    notice = AttachmentApiRuntimeNotice(operation=operation)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=notice.model_dump(mode="json"),
    )


@router.post(
    "/upload",
    response_model=AttachmentApiRuntimeNotice,
    responses={
        status.HTTP_501_NOT_IMPLEMENTED: {
            "description": "C19G attachment upload placeholder only"
        },
    },
)
def upload_attachment(
    actor: User = Depends(get_current_user),
) -> AttachmentApiRuntimeNotice:
    del actor
    _schema_only(AttachmentOperation.UPLOAD)


@router.get(
    "/{message_id}",
    response_model=AttachmentApiRuntimeNotice,
    responses={
        status.HTTP_501_NOT_IMPLEMENTED: {
            "description": "C19G attachment lookup placeholder only"
        },
    },
)
def get_attachments(
    message_id: MessageIdPath,
    actor: User = Depends(get_current_user),
) -> AttachmentApiRuntimeNotice:
    del message_id, actor
    _schema_only(AttachmentOperation.FETCH_BY_MESSAGE)
