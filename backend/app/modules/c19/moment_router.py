"""Authenticated public routes for the C19 Moments feature."""

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
from .asset_schemas import ASSET_ID_PATTERN, ChatAssetRead
from .http_asset_store import (
    ChatAssetStoreAuthenticationError,
    ChatAssetStoreConflictError,
    ChatAssetStoreHttpError,
    ChatAssetStoreProtocolError,
    ChatAssetStoreQuotaError,
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
from .moment_policy import C19MomentPolicyError
from .moment_schemas import (
    COMMENT_ID_PATTERN,
    MOMENT_ID_PATTERN,
    MomentAssetAccessIntentRead,
    MomentAssetAccessIntentRequest,
    MomentAssetUploadIntentRead,
    MomentAssetUploadIntentRequest,
    MomentCommentCreateRequest,
    MomentCommentDeleteRead,
    MomentCommentPageRead,
    MomentCommentRead,
    MomentDeleteRead,
    MomentDraftCreateRequest,
    MomentDraftRead,
    MomentEventPageRead,
    MomentEventTailRead,
    MomentFeedPageRead,
    MomentLikeMutationRead,
    MomentLikePageRead,
    MomentPublishRequest,
    MomentRead,
)
from .moment_service import (
    C19MomentAccessError,
    create_moment_asset_access_intent,
    create_moment_asset_upload_intent,
    create_moment_comment,
    create_moment_draft,
    delete_moment,
    delete_moment_comment,
    finalize_moment_asset_upload,
    get_moment,
    get_moment_asset_status,
    get_moment_event_tail,
    list_moment_comments,
    list_moment_events,
    list_moment_feed,
    list_moment_likes,
    publish_moment,
    set_moment_like,
)
from .moment_storage import MomentAssetStore, MomentStore
from .moment_store_provider import (
    build_moment_store,
    get_moment_asset_store,
    get_moment_store,
)
from .storage import C19StorageUnconfiguredError


router = APIRouter(prefix="/c19/moments", tags=["c19-moments"])
MomentIdPath = Annotated[str, Path(pattern=MOMENT_ID_PATTERN)]
CommentIdPath = Annotated[str, Path(pattern=COMMENT_ID_PATTERN)]
AssetIdPath = Annotated[str, Path(pattern=ASSET_ID_PATTERN)]
MomentStoreDependency = Annotated[MomentStore, Depends(get_moment_store)]
MomentAssetStoreDependency = Annotated[
    MomentAssetStore,
    Depends(get_moment_asset_store),
]


def _raise_moment_error(db: Session, exc: Exception) -> NoReturn:
    db.rollback()
    if isinstance(exc, (C19MomentAccessError, C19MomentPolicyError)):
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    if isinstance(exc, ChatRecordStoreConflictError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "c19_moment_idempotency_conflict",
                "message": "The client identifier is already used by another payload.",
            },
        ) from None
    if isinstance(exc, ChatAssetStoreConflictError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "c19_asset_binding_conflict",
                "message": "The image is already bound to another Moment.",
            },
        ) from None
    if isinstance(exc, ChatAssetStoreQuotaError):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "c19_asset_quota_exceeded",
                "message": "The image upload quota is currently exhausted.",
            },
        ) from None
    if isinstance(exc, ChatRecordStoreRejectedError):
        if exc.status_code == 400 and exc.operation in {
            "list_moment_feed",
            "list_moment_likes",
            "list_moment_comments",
            "list_moment_events",
        }:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "c19_invalid_cursor",
                    "message": "The Moment cursor is invalid or expired.",
                },
            ) from None
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "c19_moment_unavailable",
                    "message": "Moment is unavailable.",
                },
            ) from None
        if exc.status_code == 410:
            raise HTTPException(
                status_code=410,
                detail={
                    "code": "c19_moment_deleted",
                    "message": "The Moment is no longer available.",
                },
            ) from None
        if exc.status_code == 422:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "c19_moment_rejected",
                    "message": "The Moment request was rejected.",
                },
            ) from None
    if isinstance(exc, ChatAssetStoreRejectedError):
        if exc.status_code == 413:
            status_code, code, message = (
                413,
                "c19_asset_too_large",
                "The image exceeds the allowed size.",
            )
        elif exc.status_code == 415:
            status_code, code, message = (
                415,
                "c19_asset_type_unsupported",
                "The image type is unsupported.",
            )
        elif exc.status_code == 410:
            status_code, code, message = (
                410,
                "c19_asset_deleted",
                "The image is no longer available.",
            )
        else:
            status_code, code, message = (
                404 if exc.status_code == 404 else 422,
                "c19_asset_unavailable",
                "Asset is unavailable.",
            )
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message": message},
        ) from None
    if isinstance(
        exc,
        (
            C19StorageUnconfiguredError,
            ChatRecordStoreAuthenticationError,
            ChatRecordStoreUnavailableError,
            ChatAssetStoreAuthenticationError,
            ChatAssetStoreUnavailableError,
        ),
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "c19_moment_store_unavailable",
                "message": "Moment storage is unavailable.",
            },
        ) from None
    if isinstance(
        exc,
        (ChatRecordStoreProtocolError, ChatAssetStoreProtocolError),
    ):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "c19_moment_store_invalid_response",
                "message": "Moment storage returned an invalid response.",
            },
        ) from None
    if isinstance(exc, (ChatRecordStoreHttpError, ChatAssetStoreHttpError)):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "c19_moment_store_error",
                "message": "Moment storage request failed.",
            },
        ) from None
    raise exc


@router.post("/drafts", response_model=MomentDraftRead)
async def moment_draft_create_endpoint(
    payload: MomentDraftCreateRequest,
    store: MomentStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentDraftRead:
    try:
        return await create_moment_draft(
            db,
            actor=actor,
            payload=payload,
            store=store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.get("/feed", response_model=MomentFeedPageRead)
async def moment_feed_endpoint(
    store: MomentStoreDependency,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentFeedPageRead:
    try:
        return await list_moment_feed(
            db,
            actor=actor,
            limit=limit,
            cursor=cursor,
            store=store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


async def _moment_event_page_stream(
    *,
    request: Request,
    initial_page: MomentEventPageRead,
    limit: int,
    session_id: str,
    actor_user_id: int,
) -> AsyncIterator[str]:
    settings = get_settings()
    page = initial_page
    deadline = monotonic() + settings.c19_event_stream_lifetime_seconds
    first_page = True
    runtime_store = build_moment_store()
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
                    page = await list_moment_events(
                        live_db,
                        actor=current_session.user,
                        limit=limit,
                        cursor=cursor,
                        store=runtime_store,
                    )
            except InvalidSessionError:
                return
            except Exception:
                return
    finally:
        close = getattr(runtime_store, "aclose", None)
        if close is not None:
            await close()


@router.get("/events/tail", response_model=MomentEventTailRead)
async def moment_event_tail_endpoint(
    store: MomentStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentEventTailRead:
    try:
        return await get_moment_event_tail(db, actor=actor, store=store)
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.get("/events", response_model=MomentEventPageRead)
async def moment_events_endpoint(
    request: Request,
    store: MomentStoreDependency,
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentEventPageRead | StreamingResponse:
    try:
        page = await list_moment_events(
            db,
            actor=actor,
            limit=limit,
            cursor=cursor,
            store=store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)
    if "text/event-stream" not in request.headers.get("accept", "").lower():
        return page
    settings = get_settings()
    session_id = get_session_id_from_request(request, settings=settings)
    if session_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return StreamingResponse(
        _moment_event_page_stream(
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


@router.post(
    "/{moment_id}/assets/upload-intents",
    response_model=MomentAssetUploadIntentRead,
)
async def moment_asset_upload_intent_endpoint(
    payload: MomentAssetUploadIntentRequest,
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    asset_store: MomentAssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentAssetUploadIntentRead:
    try:
        return await create_moment_asset_upload_intent(
            db,
            actor=actor,
            moment_id=moment_id,
            payload=payload,
            store=store,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.get("/{moment_id}/assets/{asset_id}", response_model=ChatAssetRead)
async def moment_asset_status_endpoint(
    moment_id: MomentIdPath,
    asset_id: AssetIdPath,
    store: MomentStoreDependency,
    asset_store: MomentAssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatAssetRead:
    try:
        return await get_moment_asset_status(
            db,
            actor=actor,
            moment_id=moment_id,
            asset_id=asset_id,
            store=store,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.post("/{moment_id}/assets/{asset_id}/finalize", response_model=ChatAssetRead)
async def moment_asset_finalize_endpoint(
    moment_id: MomentIdPath,
    asset_id: AssetIdPath,
    store: MomentStoreDependency,
    asset_store: MomentAssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatAssetRead:
    try:
        return await finalize_moment_asset_upload(
            db,
            actor=actor,
            moment_id=moment_id,
            asset_id=asset_id,
            store=store,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.post(
    "/{moment_id}/assets/{asset_id}/access-intents",
    response_model=MomentAssetAccessIntentRead,
)
async def moment_asset_access_intent_endpoint(
    payload: MomentAssetAccessIntentRequest,
    moment_id: MomentIdPath,
    asset_id: AssetIdPath,
    store: MomentStoreDependency,
    asset_store: MomentAssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentAssetAccessIntentRead:
    try:
        return await create_moment_asset_access_intent(
            db,
            actor=actor,
            moment_id=moment_id,
            asset_id=asset_id,
            payload=payload,
            store=store,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.post("/{moment_id}/publish", response_model=MomentRead)
async def moment_publish_endpoint(
    payload: MomentPublishRequest,
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    asset_store: MomentAssetStoreDependency,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentRead:
    try:
        return await publish_moment(
            db,
            actor=actor,
            moment_id=moment_id,
            payload=payload,
            store=store,
            asset_store=asset_store,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.put("/{moment_id}/like", response_model=MomentLikeMutationRead)
async def moment_like_endpoint(
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentLikeMutationRead:
    try:
        return await set_moment_like(
            db,
            actor=actor,
            moment_id=moment_id,
            liked=True,
            store=store,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.delete("/{moment_id}/like", response_model=MomentLikeMutationRead)
async def moment_unlike_endpoint(
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentLikeMutationRead:
    try:
        return await set_moment_like(
            db,
            actor=actor,
            moment_id=moment_id,
            liked=False,
            store=store,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.get("/{moment_id}/likes", response_model=MomentLikePageRead)
async def moment_likes_endpoint(
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentLikePageRead:
    try:
        return await list_moment_likes(
            db,
            actor=actor,
            moment_id=moment_id,
            limit=limit,
            cursor=cursor,
            store=store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.post("/{moment_id}/comments", response_model=MomentCommentRead)
async def moment_comment_create_endpoint(
    payload: MomentCommentCreateRequest,
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentCommentRead:
    try:
        return await create_moment_comment(
            db,
            actor=actor,
            moment_id=moment_id,
            payload=payload,
            store=store,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.get("/{moment_id}/comments", response_model=MomentCommentPageRead)
async def moment_comments_endpoint(
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentCommentPageRead:
    try:
        return await list_moment_comments(
            db,
            actor=actor,
            moment_id=moment_id,
            limit=limit,
            cursor=cursor,
            store=store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.delete(
    "/{moment_id}/comments/{comment_id}",
    response_model=MomentCommentDeleteRead,
)
async def moment_comment_delete_endpoint(
    moment_id: MomentIdPath,
    comment_id: CommentIdPath,
    store: MomentStoreDependency,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentCommentDeleteRead:
    try:
        return await delete_moment_comment(
            db,
            actor=actor,
            moment_id=moment_id,
            comment_id=comment_id,
            store=store,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.get("/{moment_id}", response_model=MomentRead)
async def moment_detail_endpoint(
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentRead:
    try:
        return await get_moment(
            db,
            actor=actor,
            moment_id=moment_id,
            store=store,
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


@router.delete("/{moment_id}", response_model=MomentDeleteRead)
async def moment_delete_endpoint(
    moment_id: MomentIdPath,
    store: MomentStoreDependency,
    asset_store: MomentAssetStoreDependency,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> MomentDeleteRead:
    try:
        return await delete_moment(
            db,
            actor=actor,
            moment_id=moment_id,
            store=store,
            asset_store=asset_store,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_moment_error(db, exc)


__all__ = ["router"]
