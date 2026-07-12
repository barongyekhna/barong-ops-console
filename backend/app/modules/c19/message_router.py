"""Authenticated C19 message routes backed only by ChatRecordStore."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from time import monotonic
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...api.deps import get_audit_context, get_current_user
from ...core.config import get_settings
from ...core.session_cookies import get_session_id_from_request
from ...db.session import get_db, managed_read_session
from ...models.user import User
from ...services.auth_service import InvalidSessionError, validate_session
from .asset_store_provider import get_chat_asset_store
from .http_asset_store import (
    ChatAssetStoreAuthenticationError,
    ChatAssetStoreConflictError,
    ChatAssetStoreHttpError,
    ChatAssetStoreProtocolError,
    ChatAssetStoreRejectedError,
    ChatAssetStoreUnavailableError,
)
from .http_record_store import (
    ChatRecordStoreAuthenticationError,
    ChatRecordStoreConflictError,
    ChatRecordStoreHttpError,
    ChatRecordStoreProtocolError,
    ChatRecordStoreRejectedError,
    ChatRecordStoreUnavailableError,
)
from .message_schemas import (
    ChatPositionAdvanceRequest,
    ChatReceiptPositionRead,
    ChatRecordPageRead,
    ChatRecordRead,
    ChatResumePositionRead,
    ChatUnreadPositionRead,
    ChatUnreadSummaryRead,
    ChatUserEventPageRead,
    ChatUserEventTailRead,
    MessageCreateRequest,
)
from .message_service import (
    C19ChatAccessError,
    advance_message_position,
    get_resume,
    get_user_event_tail,
    get_unread,
    get_unread_summary,
    list_message_history,
    list_user_events,
    send_message,
)
from .record_store_provider import build_chat_record_store, get_chat_record_store
from .storage import C19StorageUnconfiguredError, ChatAssetStore, ChatRecordStore


router = APIRouter(prefix="/c19", tags=["c19-chat-records"])
ConversationIdPath = Annotated[str, Path(min_length=1, max_length=64)]
RecordStoreDependency = Annotated[ChatRecordStore, Depends(get_chat_record_store)]
AssetStoreDependency = Annotated[ChatAssetStore, Depends(get_chat_asset_store)]


def _raise_chat_error(db: Session, exc: Exception) -> NoReturn:
    db.rollback()
    if isinstance(exc, C19ChatAccessError):
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    if isinstance(exc, ChatRecordStoreConflictError):
        if exc.operation != "append_record":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "c19_message_position_conflict",
                    "message": "The requested message position is not available.",
                },
            ) from None
        raise HTTPException(
            status_code=409,
            detail={
                "code": "c19_message_idempotency_conflict",
                "message": "The client message ID is already used by another payload.",
            },
        ) from None
    if isinstance(exc, ChatAssetStoreConflictError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "c19_asset_binding_conflict",
                "message": "The asset is already bound to another message.",
            },
        ) from None
    if isinstance(exc, C19StorageUnconfiguredError):
        is_asset = exc.store_name == "chat_asset_store"
        raise HTTPException(
            status_code=503,
            detail={
                "code": (
                    "c19_asset_store_unavailable"
                    if is_asset
                    else "c19_record_store_unavailable"
                ),
                "message": (
                    "Chat asset storage is unavailable."
                    if is_asset
                    else "Chat record storage is unavailable."
                ),
            },
        ) from None
    if isinstance(
        exc,
        (ChatRecordStoreAuthenticationError, ChatRecordStoreUnavailableError),
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "c19_record_store_unavailable",
                "message": "Chat record storage is unavailable.",
            },
        ) from None
    if isinstance(
        exc,
        (ChatAssetStoreAuthenticationError, ChatAssetStoreUnavailableError),
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "c19_asset_store_unavailable",
                "message": "Chat asset storage is unavailable.",
            },
        ) from None
    if isinstance(exc, ChatAssetStoreRejectedError):
        status_code = 410 if exc.status_code == 410 else 422
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": (
                    "c19_asset_deleted"
                    if status_code == 410
                    else "c19_asset_unavailable"
                ),
                "message": "The selected asset is unavailable.",
            },
        ) from None
    if isinstance(exc, ChatRecordStoreRejectedError):
        if exc.status_code == 400 and exc.operation in {
            "list_records",
            "list_user_events",
        }:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "c19_invalid_cursor",
                    "message": "The chat cursor is invalid or expired.",
                },
            ) from None
        if exc.status_code == 422 and exc.operation == "append_record":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "c19_message_rejected",
                    "message": "The message was rejected by record storage.",
                },
            ) from None
        if exc.status_code == 410 and exc.operation == "append_record":
            raise HTTPException(
                status_code=410,
                detail={
                    "code": "c19_message_deleted",
                    "message": "The original message was deleted and cannot be replayed.",
                },
            ) from None
    if isinstance(exc, (ChatRecordStoreProtocolError, ChatRecordStoreRejectedError)):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "c19_record_store_invalid_response",
                "message": "Chat record storage returned an invalid response.",
            },
        ) from None
    if isinstance(exc, ChatAssetStoreProtocolError):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "c19_asset_store_invalid_response",
                "message": "Chat asset storage returned an invalid response.",
            },
        ) from None
    if isinstance(exc, ChatAssetStoreHttpError):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "c19_asset_store_error",
                "message": "Chat asset storage request failed.",
            },
        ) from None
    if isinstance(exc, ChatRecordStoreHttpError):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "c19_record_store_error",
                "message": "Chat record storage request failed.",
            },
        ) from None
    raise exc


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatRecordRead,
)
async def message_send_endpoint(
    payload: MessageCreateRequest,
    conversation_id: ConversationIdPath,
    store: RecordStoreDependency,
    asset_store: AssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatRecordRead:
    try:
        return await send_message(
            db,
            actor=actor,
            conversation_id=conversation_id,
            payload=payload,
            store=store,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_chat_error(db, exc)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ChatRecordPageRead,
)
async def message_history_endpoint(
    conversation_id: ConversationIdPath,
    store: RecordStoreDependency,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatRecordPageRead:
    try:
        return await list_message_history(
            db,
            actor=actor,
            conversation_id=conversation_id,
            limit=limit,
            cursor=cursor,
            store=store,
        )
    except Exception as exc:
        _raise_chat_error(db, exc)


@router.post(
    "/conversations/{conversation_id}/delivered",
    response_model=ChatReceiptPositionRead,
)
async def message_delivered_endpoint(
    payload: ChatPositionAdvanceRequest,
    conversation_id: ConversationIdPath,
    store: RecordStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatReceiptPositionRead:
    try:
        return await advance_message_position(
            db,
            actor=actor,
            conversation_id=conversation_id,
            through_sequence=payload.through_sequence,
            position="delivery",
            store=store,
        )
    except Exception as exc:
        _raise_chat_error(db, exc)


@router.post(
    "/conversations/{conversation_id}/read",
    response_model=ChatReceiptPositionRead,
)
async def message_read_endpoint(
    payload: ChatPositionAdvanceRequest,
    conversation_id: ConversationIdPath,
    store: RecordStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatReceiptPositionRead:
    try:
        return await advance_message_position(
            db,
            actor=actor,
            conversation_id=conversation_id,
            through_sequence=payload.through_sequence,
            position="read",
            store=store,
        )
    except Exception as exc:
        _raise_chat_error(db, exc)


@router.get(
    "/conversations/{conversation_id}/unread",
    response_model=ChatUnreadPositionRead,
)
async def message_unread_endpoint(
    conversation_id: ConversationIdPath,
    store: RecordStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatUnreadPositionRead:
    try:
        return await get_unread(
            db,
            actor=actor,
            conversation_id=conversation_id,
            store=store,
        )
    except Exception as exc:
        _raise_chat_error(db, exc)


@router.get("/unread", response_model=ChatUnreadSummaryRead)
async def global_unread_endpoint(
    store: RecordStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatUnreadSummaryRead:
    try:
        return await get_unread_summary(db, actor=actor, store=store)
    except Exception as exc:
        _raise_chat_error(db, exc)


@router.get(
    "/conversations/{conversation_id}/resume",
    response_model=ChatResumePositionRead,
)
async def message_resume_endpoint(
    conversation_id: ConversationIdPath,
    store: RecordStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatResumePositionRead:
    try:
        return await get_resume(
            db,
            actor=actor,
            conversation_id=conversation_id,
            store=store,
        )
    except Exception as exc:
        _raise_chat_error(db, exc)


async def _event_page_stream(
    *,
    request: Request,
    initial_page: ChatUserEventPageRead,
    limit: int,
    session_id: str,
    actor_user_id: int,
) -> AsyncIterator[str]:
    """Emit content-free durable event pages and close for session revalidation."""

    settings = get_settings()
    page = initial_page
    deadline = monotonic() + settings.c19_event_stream_lifetime_seconds
    first_page = True
    runtime_store = build_chat_record_store()
    try:
        yield "retry: 2000\n\n"
        while monotonic() < deadline:
            if await request.is_disconnected():
                return
            if first_page or page.events:
                yield f"data: {page.model_dump_json()}\n\n"
                first_page = False
            else:
                yield ": keep-alive\n\n"

            if page.next_cursor is None:
                return
            cursor = page.next_cursor
            if not page.events:
                await asyncio.sleep(settings.c19_record_event_poll_seconds)
            try:
                with managed_read_session() as live_db:
                    current_session = validate_session(
                        live_db,
                        session_id=session_id,
                        audit=get_audit_context(request),
                    )
                    if int(current_session.user.id) != actor_user_id:
                        return
                    page = await list_user_events(
                        live_db,
                        actor=current_session.user,
                        limit=limit,
                        cursor=cursor,
                        store=runtime_store,
                    )
            except InvalidSessionError:
                return
            except Exception:
                # A closed stream makes EventSource fall back to authenticated
                # HTTP recovery. Provider details and content never cross SSE.
                return
    finally:
        close = getattr(runtime_store, "aclose", None)
        if close is not None:
            await close()


@router.get("/events/tail", response_model=ChatUserEventTailRead)
async def user_event_tail_endpoint(
    store: RecordStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatUserEventTailRead:
    try:
        return await get_user_event_tail(db, actor=actor, store=store)
    except Exception as exc:
        _raise_chat_error(db, exc)


@router.get("/events", response_model=ChatUserEventPageRead)
async def user_events_endpoint(
    request: Request,
    store: RecordStoreDependency,
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatUserEventPageRead | StreamingResponse:
    try:
        page = await list_user_events(
            db,
            actor=actor,
            limit=limit,
            cursor=cursor,
            store=store,
        )
    except Exception as exc:
        _raise_chat_error(db, exc)

    if "text/event-stream" not in request.headers.get("accept", "").lower():
        return page
    settings = get_settings()
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return StreamingResponse(
        _event_page_stream(
            request=request,
            initial_page=page,
            limit=limit,
            session_id=session_id,
            actor_user_id=int(actor.id),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
