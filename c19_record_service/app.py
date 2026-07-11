"""FastAPI application factory for the private C19 record service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
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
    IdempotencyConflictError,
    PositionBeyondConversationError,
    RecordStoreInvariantError,
    UnsupportedContentError,
    advance_position,
    append_record,
    apply_retention,
    combined_position,
    delete_records,
    get_user_event_tail,
    list_records,
    list_user_events,
    resume_position,
    unread_position,
)
from .schemas import (
    CombinedPositionResponse,
    DeleteRecordsRequest,
    HealthResponse,
    MutationResultResponse,
    PositionAdvanceRequest,
    ReceiptPositionResponse,
    RecordAppendRequest,
    RecordPageResponse,
    RecordResponse,
    ResumePositionResponse,
    RetentionRequest,
    UnreadPositionResponse,
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

    @router.post("/retention/apply", response_model=MutationResultResponse)
    def post_apply_retention(
        body: RetentionRequest,
        session: Session = Depends(get_session),
    ) -> MutationResultResponse:
        return apply_retention(session, body)

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
