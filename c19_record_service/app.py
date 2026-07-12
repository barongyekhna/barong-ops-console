"""FastAPI application factory for the private C19 record service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import require_service_token
from .config import RecordServiceSettings
from .cursors import CursorCodec, InvalidCursorError
from .database import Base, DatabaseRuntime, get_session
from .repository import (
    DeletedIdempotencyKeyError,
    AssetDeletionLeaseError,
    IdempotencyConflictError,
    PositionBeyondConversationError,
    RecordStoreInvariantError,
    RetentionOperationConflictError,
    UnsupportedContentError,
    advance_position,
    append_record,
    apply_retention,
    authorize_asset_deletion,
    claim_asset_deletions,
    complete_asset_deletion,
    combined_position,
    delete_records,
    get_visible_record,
    get_user_event_tail,
    list_records,
    list_user_events,
    resume_position,
    unread_position,
    unread_summary,
)
from .moment_repository import (
    MomentConflictError,
    MomentGoneError,
    MomentNotFoundError,
    MomentStoreError,
    begin_moment_delete,
    complete_moment_delete,
    create_moment_comment,
    delete_moment_comment,
    get_moment,
    get_moment_draft,
    get_moment_event_tail,
    list_moment_comments,
    list_moment_events,
    list_moment_feed,
    list_moment_likes,
    mutate_moment_like,
    publish_moment,
    reserve_moment_draft,
)
from .moment_schemas import (
    MomentCommentCreateRequest,
    MomentCommentDeleteRequest,
    MomentCommentDeleteResponse,
    MomentCommentPageResponse,
    MomentContextQuery,
    MomentDeleteCompleteRequest,
    MomentDeleteRequest,
    MomentDeleteResponse,
    MomentDraftCreateRequest,
    MomentDraftQueryRequest,
    MomentDraftResponse,
    MomentEventPageResponse,
    MomentEventQuery,
    MomentEventTailResponse,
    MomentFeedQuery,
    MomentInteractionPageQuery,
    MomentLikeMutationRequest,
    MomentLikePageResponse,
    MomentLikeResponse,
    MomentPageResponse,
    MomentPublishRequest,
    MomentRead,
    MomentCommentRead,
)
from .operations import record_ops_snapshot
from .schemas import (
    AssetDeletionAuthorizeRequest,
    AssetDeletionAuthorizeResponse,
    AssetDeletionClaimRequest,
    AssetDeletionClaimResponse,
    AssetDeletionCompleteRequest,
    AssetDeletionCompleteResponse,
    CombinedPositionResponse,
    DeleteRecordsRequest,
    HealthResponse,
    MutationResultResponse,
    PositionAdvanceRequest,
    ReceiptPositionResponse,
    RecordAppendRequest,
    RecordPageResponse,
    RecordResponse,
    RecordOpsSnapshot,
    ResumePositionResponse,
    RetentionRequest,
    RetentionBatchResponse,
    UnreadPositionResponse,
    UnreadSummaryRequest,
    UnreadSummaryResponse,
    UserEventPageResponse,
    UserEventTailResponse,
)


def _cursor(request: Request) -> CursorCodec:
    return request.app.state.cursor_codec


def _translate_store_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidCursorError):
        return HTTPException(status_code=400, detail="invalid or expired cursor")
    if isinstance(exc, IdempotencyConflictError):
        return HTTPException(status_code=409, detail="idempotency key conflict")
    if isinstance(exc, DeletedIdempotencyKeyError):
        return HTTPException(status_code=410, detail="message was permanently deleted")
    if isinstance(exc, PositionBeyondConversationError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, UnsupportedContentError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, RecordStoreInvariantError):
        return HTTPException(status_code=503, detail="record store unavailable")
    if isinstance(exc, (RetentionOperationConflictError, AssetDeletionLeaseError)):
        return HTTPException(status_code=409, detail="retention operation conflict")
    if isinstance(exc, MomentNotFoundError):
        return HTTPException(status_code=404, detail="Moment not found")
    if isinstance(exc, MomentGoneError):
        return HTTPException(status_code=410, detail="Moment was deleted")
    if isinstance(exc, MomentConflictError):
        return HTTPException(status_code=409, detail="Moment operation conflict")
    if isinstance(exc, MomentStoreError):
        return HTTPException(status_code=503, detail="Moment store unavailable")
    return HTTPException(status_code=500, detail="record service operation failed")


def _build_v1_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        dependencies=[Depends(require_service_token)],
    )

    @router.post("/records", response_model=RecordResponse)
    def create_record(
        body: RecordAppendRequest,
        response: Response,
        request: Request,
        session: Session = Depends(get_session),
    ) -> RecordResponse:
        try:
            result = append_record(
                session,
                body,
                max_message_chars=request.app.state.settings.max_message_chars,
            )
        except (
            DeletedIdempotencyKeyError,
            IdempotencyConflictError,
            RecordStoreInvariantError,
            UnsupportedContentError,
        ) as exc:
            raise _translate_store_error(exc) from exc
        response.status_code = 200 if result.replayed else 201
        response.headers["Idempotent-Replay"] = (
            "true" if result.replayed else "false"
        )
        return result.record

    @router.get(
        "/conversations/{conversation_id}/records",
        response_model=RecordPageResponse,
    )
    def get_records(
        conversation_id: str,
        request: Request,
        user_id: str = Query(min_length=1, max_length=128),
        limit: int = Query(default=50, ge=1, le=200),
        cursor: str | None = Query(default=None, max_length=2048),
        session: Session = Depends(get_session),
    ) -> RecordPageResponse:
        try:
            return list_records(
                session,
                conversation_id=conversation_id,
                user_id=user_id,
                limit=limit,
                cursor=cursor,
                codec=_cursor(request),
            )
        except InvalidCursorError as exc:
            raise _translate_store_error(exc) from exc

    @router.get(
        "/conversations/{conversation_id}/records/{record_id}",
        response_model=RecordResponse,
    )
    def get_exact_record(
        conversation_id: str,
        record_id: str,
        user_id: str = Query(min_length=1, max_length=128),
        session: Session = Depends(get_session),
    ) -> RecordResponse:
        record = get_visible_record(
            session,
            conversation_id=conversation_id,
            record_id=record_id,
            user_id=user_id,
        )
        if record is None:
            # Deliberately collapse missing, wrong-conversation and invisible
            # records into the same response to avoid an existence oracle.
            raise HTTPException(status_code=404, detail="record not found")
        return record

    @router.get(
        "/users/{user_id}/events/tail",
        response_model=UserEventTailResponse,
    )
    def get_events_tail(
        user_id: str,
        request: Request,
        session: Session = Depends(get_session),
    ) -> UserEventTailResponse:
        return get_user_event_tail(
            session,
            user_id=user_id,
            codec=_cursor(request),
        )

    @router.post(
        "/conversations/{conversation_id}/delivery",
        response_model=ReceiptPositionResponse,
    )
    def post_delivery(
        conversation_id: str,
        body: PositionAdvanceRequest,
        session: Session = Depends(get_session),
    ) -> ReceiptPositionResponse:
        try:
            return advance_position(
                session,
                conversation_id=conversation_id,
                request=body,
                position_type="delivery",
            )
        except PositionBeyondConversationError as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/conversations/{conversation_id}/read",
        response_model=ReceiptPositionResponse,
    )
    def post_read(
        conversation_id: str,
        body: PositionAdvanceRequest,
        session: Session = Depends(get_session),
    ) -> ReceiptPositionResponse:
        try:
            return advance_position(
                session,
                conversation_id=conversation_id,
                request=body,
                position_type="read",
            )
        except PositionBeyondConversationError as exc:
            raise _translate_store_error(exc) from exc

    @router.get(
        "/conversations/{conversation_id}/unread",
        response_model=UnreadPositionResponse,
    )
    def get_unread(
        conversation_id: str,
        user_id: str = Query(min_length=1, max_length=128),
        session: Session = Depends(get_session),
    ) -> UnreadPositionResponse:
        return unread_position(
            session, conversation_id=conversation_id, user_id=user_id
        )

    @router.post(
        "/users/{user_id}/unread-summary",
        response_model=UnreadSummaryResponse,
    )
    def post_unread_summary(
        user_id: str,
        body: UnreadSummaryRequest,
        session: Session = Depends(get_session),
    ) -> UnreadSummaryResponse:
        return unread_summary(
            session,
            user_id=user_id,
            conversation_ids=body.conversation_ids,
        )

    @router.get(
        "/conversations/{conversation_id}/resume",
        response_model=ResumePositionResponse,
    )
    def get_resume(
        conversation_id: str,
        request: Request,
        user_id: str = Query(min_length=1, max_length=128),
        session: Session = Depends(get_session),
    ) -> ResumePositionResponse:
        return resume_position(
            session,
            conversation_id=conversation_id,
            user_id=user_id,
            codec=_cursor(request),
        )

    @router.get(
        "/conversations/{conversation_id}/positions/{user_id}",
        response_model=CombinedPositionResponse,
    )
    def get_positions(
        conversation_id: str,
        user_id: str,
        request: Request,
        session: Session = Depends(get_session),
    ) -> CombinedPositionResponse:
        return combined_position(
            session,
            conversation_id=conversation_id,
            user_id=user_id,
            codec=_cursor(request),
        )

    @router.get(
        "/users/{user_id}/events",
        response_model=UserEventPageResponse,
    )
    def get_user_events(
        user_id: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        cursor: str | None = Query(default=None, max_length=2048),
        session: Session = Depends(get_session),
    ) -> UserEventPageResponse:
        try:
            return list_user_events(
                session,
                user_id=user_id,
                limit=limit,
                cursor=cursor,
                codec=_cursor(request),
            )
        except InvalidCursorError as exc:
            raise _translate_store_error(exc) from exc

    @router.post("/records/delete", response_model=MutationResultResponse)
    def post_delete_records(
        body: DeleteRecordsRequest,
        session: Session = Depends(get_session),
    ) -> MutationResultResponse:
        return delete_records(session, body)

    @router.post("/retention/apply", response_model=RetentionBatchResponse)
    def post_apply_retention(
        body: RetentionRequest,
        session: Session = Depends(get_session),
    ) -> RetentionBatchResponse:
        try:
            return apply_retention(session, body)
        except (RetentionOperationConflictError, RecordStoreInvariantError) as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/retention/asset-deletions/claim",
        response_model=AssetDeletionClaimResponse,
    )
    def post_claim_asset_deletions(
        body: AssetDeletionClaimRequest,
        session: Session = Depends(get_session),
    ) -> AssetDeletionClaimResponse:
        return claim_asset_deletions(session, body)

    @router.post(
        "/retention/asset-deletions/{job_id}/authorize",
        response_model=AssetDeletionAuthorizeResponse,
    )
    def post_authorize_asset_deletion(
        job_id: str,
        body: AssetDeletionAuthorizeRequest,
        session: Session = Depends(get_session),
    ) -> AssetDeletionAuthorizeResponse:
        try:
            return authorize_asset_deletion(session, job_id=job_id, request=body)
        except AssetDeletionLeaseError as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/retention/asset-deletions/{job_id}/complete",
        response_model=AssetDeletionCompleteResponse,
    )
    def post_complete_asset_deletion(
        job_id: str,
        body: AssetDeletionCompleteRequest,
        session: Session = Depends(get_session),
    ) -> AssetDeletionCompleteResponse:
        try:
            return complete_asset_deletion(session, job_id=job_id, request=body)
        except AssetDeletionLeaseError as exc:
            raise _translate_store_error(exc) from exc

    @router.get("/ops/snapshot", response_model=RecordOpsSnapshot)
    def get_ops_snapshot(
        response: Response,
        session: Session = Depends(get_session),
    ) -> RecordOpsSnapshot:
        response.headers["Cache-Control"] = "no-store"
        return record_ops_snapshot(session)

    # Static Moment paths are registered before the dynamic moment-id paths so
    # values such as "feed" and "events" can never be interpreted as IDs.
    @router.post("/moments/feed/query", response_model=MomentPageResponse)
    def post_moment_feed_query(
        body: MomentFeedQuery,
        request: Request,
        session: Session = Depends(get_session),
    ) -> MomentPageResponse:
        try:
            return list_moment_feed(session, body, codec=_cursor(request))
        except (InvalidCursorError, MomentStoreError) as exc:
            raise _translate_store_error(exc) from exc

    @router.post("/moments/events/query", response_model=MomentEventPageResponse)
    def post_moment_events_query(
        body: MomentEventQuery,
        request: Request,
        session: Session = Depends(get_session),
    ) -> MomentEventPageResponse:
        try:
            return list_moment_events(session, body, codec=_cursor(request))
        except (InvalidCursorError, MomentStoreError) as exc:
            raise _translate_store_error(exc) from exc

    @router.post("/moments/events/tail", response_model=MomentEventTailResponse)
    def post_moment_events_tail(
        body: MomentContextQuery,
        request: Request,
        session: Session = Depends(get_session),
    ) -> MomentEventTailResponse:
        try:
            return get_moment_event_tail(session, body, codec=_cursor(request))
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    @router.post("/moments/drafts", response_model=MomentDraftResponse)
    def post_moment_draft(
        body: MomentDraftCreateRequest,
        session: Session = Depends(get_session),
    ) -> MomentDraftResponse:
        try:
            return reserve_moment_draft(session, body)
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/moments/{moment_id}/draft/query",
        response_model=MomentDraftResponse,
    )
    def post_moment_draft_query(
        moment_id: str,
        body: MomentDraftQueryRequest,
        session: Session = Depends(get_session),
    ) -> MomentDraftResponse:
        try:
            return get_moment_draft(
                session, moment_id=moment_id, request=body
            )
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/moments/{moment_id}/publish",
        response_model=MomentRead,
    )
    def post_moment_publish(
        moment_id: str,
        body: MomentPublishRequest,
        response: Response,
        session: Session = Depends(get_session),
    ) -> MomentRead:
        try:
            result = publish_moment(session, moment_id=moment_id, request=body)
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc
        response.status_code = 200 if result.replayed else 201
        response.headers["Idempotent-Replay"] = (
            "true" if result.replayed else "false"
        )
        return result.value  # type: ignore[return-value]

    @router.post("/moments/{moment_id}/query", response_model=MomentRead)
    def post_moment_query(
        moment_id: str,
        body: MomentContextQuery,
        session: Session = Depends(get_session),
    ) -> MomentRead:
        try:
            return get_moment(session, moment_id=moment_id, request=body)
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    @router.post("/moments/{moment_id}/likes", response_model=MomentLikeResponse)
    def post_moment_like(
        moment_id: str,
        body: MomentLikeMutationRequest,
        session: Session = Depends(get_session),
    ) -> MomentLikeResponse:
        try:
            return mutate_moment_like(
                session, moment_id=moment_id, request=body, liked=True
            )
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/moments/{moment_id}/likes/remove",
        response_model=MomentLikeResponse,
    )
    def post_moment_unlike(
        moment_id: str,
        body: MomentLikeMutationRequest,
        session: Session = Depends(get_session),
    ) -> MomentLikeResponse:
        try:
            return mutate_moment_like(
                session, moment_id=moment_id, request=body, liked=False
            )
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/moments/{moment_id}/likes/query",
        response_model=MomentLikePageResponse,
    )
    def post_moment_likes_query(
        moment_id: str,
        body: MomentInteractionPageQuery,
        request: Request,
        session: Session = Depends(get_session),
    ) -> MomentLikePageResponse:
        try:
            return list_moment_likes(
                session,
                moment_id=moment_id,
                request=body,
                codec=_cursor(request),
            )
        except (InvalidCursorError, MomentStoreError) as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/moments/{moment_id}/comments",
        response_model=MomentCommentRead,
    )
    def post_moment_comment(
        moment_id: str,
        body: MomentCommentCreateRequest,
        response: Response,
        session: Session = Depends(get_session),
    ) -> MomentCommentRead:
        try:
            result = create_moment_comment(
                session, moment_id=moment_id, request=body
            )
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc
        response.status_code = 200 if result.replayed else 201
        response.headers["Idempotent-Replay"] = (
            "true" if result.replayed else "false"
        )
        return result.value  # type: ignore[return-value]

    @router.post(
        "/moments/{moment_id}/comments/query",
        response_model=MomentCommentPageResponse,
    )
    def post_moment_comments_query(
        moment_id: str,
        body: MomentInteractionPageQuery,
        request: Request,
        session: Session = Depends(get_session),
    ) -> MomentCommentPageResponse:
        try:
            return list_moment_comments(
                session,
                moment_id=moment_id,
                request=body,
                codec=_cursor(request),
            )
        except (InvalidCursorError, MomentStoreError) as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/moments/{moment_id}/comments/{comment_id}/delete",
        response_model=MomentCommentDeleteResponse,
    )
    def post_moment_comment_delete(
        moment_id: str,
        comment_id: str,
        body: MomentCommentDeleteRequest,
        session: Session = Depends(get_session),
    ) -> MomentCommentDeleteResponse:
        try:
            return delete_moment_comment(
                session,
                moment_id=moment_id,
                comment_id=comment_id,
                request=body,
            )
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/moments/{moment_id}/delete",
        response_model=MomentDeleteResponse,
    )
    def post_moment_delete(
        moment_id: str,
        body: MomentDeleteRequest,
        session: Session = Depends(get_session),
    ) -> MomentDeleteResponse:
        try:
            return begin_moment_delete(
                session, moment_id=moment_id, request=body
            )
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    @router.post(
        "/moments/{moment_id}/delete/complete",
        response_model=MomentDeleteResponse,
    )
    def post_moment_delete_complete(
        moment_id: str,
        body: MomentDeleteCompleteRequest,
        session: Session = Depends(get_session),
    ) -> MomentDeleteResponse:
        try:
            return complete_moment_delete(
                session, moment_id=moment_id, request=body
            )
        except MomentStoreError as exc:
            raise _translate_store_error(exc) from exc

    return router


def create_app(
    settings: RecordServiceSettings,
    *,
    create_schema: bool = False,
) -> FastAPI:
    database = DatabaseRuntime.create(settings.database_url)
    if create_schema:
        Base.metadata.create_all(database.engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        yield
        database.dispose()

    application = FastAPI(
        title="C19 Record Service",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.database = database
    application.state.cursor_codec = CursorCodec(
        secret=settings.cursor_signing_secret,
        ttl_seconds=settings.cursor_ttl_seconds,
    )

    @application.exception_handler(SQLAlchemyError)
    async def sanitized_database_error(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=500,
            content={"detail": "record service database operation failed"},
        )

    @application.exception_handler(RequestValidationError)
    async def sanitized_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic's default response includes the rejected input value.  That
        # is useful for public metadata APIs but would reflect private Moment or
        # chat content.  Keep the stable 422 wire status and discard the body.
        del request, exc
        return JSONResponse(
            status_code=422,
            content={"detail": "record service request validation failed"},
        )

    @application.get("/healthz", response_model=HealthResponse)
    def health() -> HealthResponse:
        try:
            with database.session_factory() as session:
                session.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return HealthResponse(status="ok", service="c19-record-service")

    application.include_router(_build_v1_router())
    return application


def create_app_from_env() -> FastAPI:
    return create_app(RecordServiceSettings.from_environment())
