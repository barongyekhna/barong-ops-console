"""FastAPI control plane; this process never mounts object volumes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, Callable, TypeVar

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import require_gateway_token, require_service_token
from .config import AssetApiSettings
from .database import Base, DatabaseRuntime
from .operations import asset_ops_snapshot
from .repository import (
    AssetConflictError,
    AssetNotFoundError,
    AssetQuotaError,
    AssetStateError,
    AssetStoreError,
    AssetTombstoneError,
    AssetValidationError,
    DatasetMismatchError,
    TransferUnauthorizedError,
    authorize_gateway_download,
    authorize_gateway_upload,
    commit_binding,
    commit_moment_binding,
    complete_gateway_upload,
    create_download_intent,
    create_moment_download_intent,
    create_moment_upload_intent,
    create_upload_intent,
    delete_asset,
    ensure_dataset_identity,
    finalize_asset,
    finalize_moment_asset,
    get_asset,
    get_moment_asset,
    inspect_scoped_transfer,
    inspect_transfer,
    prepare_binding,
    prepare_moment_binding,
    quarantine_asset,
    commit_chat_retention_deletion,
    prepare_chat_retention_deletion,
)


from .schemas import (
    AssetScopeRequest,
    AssetSnapshot,
    AssetOpsSnapshot,
    BindingResponse,
    ChatRetentionDeletionRequest,
    ChatRetentionDeletionResponse,
    ChatRetentionPreparationResponse,
    CommitBindingRequest,
    DownloadIntentRequest,
    DownloadIntentResponse,
    GatewayDownloadAuthorizeRequest,
    GatewayDownloadAuthorizeResponse,
    GatewayUploadAuthorizeRequest,
    GatewayUploadAuthorizeResponse,
    GatewayUploadCompleteRequest,
    HealthResponse,
    LifecycleRequest,
    LifecycleResponse,
    MomentAssetScopeRequest,
    MomentAssetSnapshot,
    MomentBindingResponse,
    MomentCommitBindingRequest,
    MomentDownloadIntentRequest,
    MomentPrepareBindingRequest,
    MomentUploadIntentRequest,
    MomentUploadIntentResponse,
    PrepareBindingRequest,
    ScopedTransferInspectResponse,
    TransferInspectRequest,
    TransferInspectResponse,
    UploadIntentRequest,
    UploadIntentResponse,
)


ResultT = TypeVar("ResultT")


def _database_call_sync(
    database: DatabaseRuntime,
    operation: Callable[..., ResultT],
    args: tuple[Any, ...],
) -> ResultT:
    """Create, use, rollback, and close a Session on the same worker thread."""

    with database.session_factory() as session:
        try:
            return operation(session, *args)
        except Exception:
            session.rollback()
            raise


async def _database_call(
    request: Request,
    operation: Callable[..., ResultT],
    *args: Any,
) -> ResultT:
    future = request.app.state.database_executor.submit(
        partial(
            _database_call_sync,
            request.app.state.database,
            operation,
            args,
        )
    )
    try:
        # Polling also remains correct on runtimes where cross-thread event-loop
        # wakeups are delayed. The bounded control-plane query never runs on the
        # event-loop thread, and bytes bypass this process entirely.
        while not future.done():
            await asyncio.sleep(0.002)
        return future.result()
    except asyncio.CancelledError:
        future.cancel()
        raise


def _health_check(session: Session, dataset_id: str) -> None:
    session.execute(text("SELECT 1"))
    ensure_dataset_identity(session, dataset_id)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AssetNotFoundError):
        return HTTPException(status_code=404, detail="asset not found")
    if isinstance(exc, AssetTombstoneError):
        return HTTPException(status_code=410, detail="asset was permanently deleted")
    if isinstance(exc, AssetConflictError):
        return HTTPException(status_code=409, detail="asset operation conflict")
    if isinstance(exc, AssetStateError):
        return HTTPException(status_code=409, detail="asset is not available for this operation")
    if isinstance(exc, AssetQuotaError):
        return HTTPException(status_code=429, detail="asset quota exceeded")
    if isinstance(exc, AssetValidationError):
        return HTTPException(status_code=422, detail="asset validation failed")
    if isinstance(exc, TransferUnauthorizedError):
        # Deliberately indistinguishable from a random ticket.
        return HTTPException(status_code=404, detail="transfer not found")
    if isinstance(exc, DatasetMismatchError):
        return HTTPException(status_code=503, detail="asset dataset unavailable")
    if isinstance(exc, AssetStoreError):
        return HTTPException(status_code=503, detail="asset service unavailable")
    return HTTPException(status_code=500, detail="asset service operation failed")


def _v1_router() -> APIRouter:
    router = APIRouter(prefix="/v1", dependencies=[Depends(require_service_token)])

    @router.get("/ops/snapshot", response_model=AssetOpsSnapshot)
    async def get_ops_snapshot(
        request: Request, response: Response
    ) -> AssetOpsSnapshot:
        response.headers["Cache-Control"] = "no-store"
        try:
            return await _database_call(
                request,
                asset_ops_snapshot,
                request.app.state.settings.dataset_id,
                request.app.state.settings.thumbnail_max_bytes,
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post("/upload-intents", response_model=UploadIntentResponse, status_code=201)
    async def post_upload_intent(
        body: UploadIntentRequest,
        request: Request,
        response: Response,
    ) -> UploadIntentResponse:
        try:
            result = await _database_call(
                request, create_upload_intent, body, request.app.state.settings
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc
        response.status_code = 201 if result.asset.status == "pending_upload" else 200
        return result

    @router.post(
        "/moment-assets/upload-intents",
        response_model=MomentUploadIntentResponse,
        status_code=201,
    )
    async def post_moment_upload_intent(
        body: MomentUploadIntentRequest,
        request: Request,
        response: Response,
    ) -> MomentUploadIntentResponse:
        try:
            result = await _database_call(
                request,
                create_moment_upload_intent,
                body,
                request.app.state.settings,
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc
        response.status_code = 201 if result.asset.status == "pending_upload" else 200
        return result

    @router.get("/assets/{asset_id}", response_model=AssetSnapshot)
    async def read_asset(
        asset_id: str,
        request: Request,
        owner_user_id: str = Query(min_length=1, max_length=128),
        conversation_id: str = Query(min_length=1, max_length=128),
    ) -> AssetSnapshot:
        try:
            return await _database_call(
                request, get_asset, asset_id, owner_user_id, conversation_id
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.get("/moment-assets/{asset_id}", response_model=MomentAssetSnapshot)
    async def read_moment_asset(
        asset_id: str,
        request: Request,
        owner_user_id: str = Query(min_length=1, max_length=128),
        scope_id: str = Query(
            min_length=36,
            max_length=36,
            pattern=r"^mom_[0-9a-f]{32}$",
        ),
    ) -> MomentAssetSnapshot:
        try:
            return await _database_call(
                request, get_moment_asset, asset_id, owner_user_id, scope_id
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post("/assets/{asset_id}/finalize", response_model=AssetSnapshot)
    async def post_finalize(
        asset_id: str,
        body: AssetScopeRequest,
        request: Request,
    ) -> AssetSnapshot:
        try:
            return await _database_call(request, finalize_asset, asset_id, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/moment-assets/{asset_id}/finalize",
        response_model=MomentAssetSnapshot,
    )
    async def post_moment_finalize(
        asset_id: str,
        body: MomentAssetScopeRequest,
        request: Request,
    ) -> MomentAssetSnapshot:
        try:
            return await _database_call(
                request, finalize_moment_asset, asset_id, body
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post("/assets/{asset_id}/bindings/prepare", response_model=BindingResponse)
    async def post_prepare_binding(
        asset_id: str,
        body: PrepareBindingRequest,
        request: Request,
    ) -> BindingResponse:
        try:
            return await _database_call(request, prepare_binding, asset_id, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/moment-assets/{asset_id}/bindings/prepare",
        response_model=MomentBindingResponse,
    )
    async def post_prepare_moment_binding(
        asset_id: str,
        body: MomentPrepareBindingRequest,
        request: Request,
    ) -> MomentBindingResponse:
        try:
            return await _database_call(
                request, prepare_moment_binding, asset_id, body
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post("/assets/{asset_id}/bindings/commit", response_model=BindingResponse)
    async def post_commit_binding(
        asset_id: str,
        body: CommitBindingRequest,
        request: Request,
    ) -> BindingResponse:
        try:
            return await _database_call(request, commit_binding, asset_id, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/moment-assets/{asset_id}/bindings/commit",
        response_model=MomentBindingResponse,
    )
    async def post_commit_moment_binding(
        asset_id: str,
        body: MomentCommitBindingRequest,
        request: Request,
    ) -> MomentBindingResponse:
        try:
            return await _database_call(
                request, commit_moment_binding, asset_id, body
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/assets/{asset_id}/download-intents",
        response_model=DownloadIntentResponse,
        status_code=201,
    )
    async def post_download_intent(
        asset_id: str,
        body: DownloadIntentRequest,
        request: Request,
    ) -> DownloadIntentResponse:
        try:
            return await _database_call(
                request,
                create_download_intent,
                asset_id,
                body,
                request.app.state.settings,
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/moment-assets/{asset_id}/download-intents",
        response_model=DownloadIntentResponse,
        status_code=201,
    )
    async def post_moment_download_intent(
        asset_id: str,
        body: MomentDownloadIntentRequest,
        request: Request,
    ) -> DownloadIntentResponse:
        try:
            return await _database_call(
                request,
                create_moment_download_intent,
                asset_id,
                body,
                request.app.state.settings,
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post("/transfers/inspect", response_model=TransferInspectResponse)
    async def post_transfer_inspect(
        body: TransferInspectRequest,
        request: Request,
    ) -> TransferInspectResponse:
        try:
            return await _database_call(request, inspect_transfer, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post("/assets/{asset_id}/quarantine", response_model=LifecycleResponse)
    async def post_quarantine(
        asset_id: str,
        body: LifecycleRequest,
        request: Request,
    ) -> LifecycleResponse:
        try:
            return await _database_call(request, quarantine_asset, asset_id, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post("/assets/{asset_id}/delete", response_model=LifecycleResponse)
    async def post_delete(
        asset_id: str,
        body: LifecycleRequest,
        request: Request,
    ) -> LifecycleResponse:
        try:
            return await _database_call(request, delete_asset, asset_id, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/retention/chat-assets/{asset_id}/prepare",
        response_model=ChatRetentionPreparationResponse,
    )
    async def post_chat_retention_prepare(
        asset_id: str,
        body: ChatRetentionDeletionRequest,
        request: Request,
    ) -> ChatRetentionPreparationResponse:
        try:
            return await _database_call(
                request, prepare_chat_retention_deletion, asset_id, body
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/retention/chat-assets/{asset_id}/commit",
        response_model=ChatRetentionDeletionResponse,
    )
    async def post_chat_retention_commit(
        asset_id: str,
        body: ChatRetentionDeletionRequest,
        request: Request,
    ) -> ChatRetentionDeletionResponse:
        try:
            return await _database_call(
                request, commit_chat_retention_deletion, asset_id, body
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    return router


def _v2_router() -> APIRouter:
    router = APIRouter(prefix="/v2", dependencies=[Depends(require_service_token)])

    @router.post("/transfers/inspect", response_model=ScopedTransferInspectResponse)
    async def post_scoped_transfer_inspect(
        body: TransferInspectRequest,
        request: Request,
    ) -> ScopedTransferInspectResponse:
        try:
            return await _database_call(request, inspect_scoped_transfer, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    return router


def _internal_router() -> APIRouter:
    router = APIRouter(
        prefix="/internal", dependencies=[Depends(require_gateway_token)]
    )

    @router.post(
        "/uploads/authorize", response_model=GatewayUploadAuthorizeResponse
    )
    async def post_upload_authorize(
        body: GatewayUploadAuthorizeRequest,
        request: Request,
    ) -> GatewayUploadAuthorizeResponse:
        try:
            return await _database_call(
                request, authorize_gateway_upload, body, request.app.state.settings
            )
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/uploads/complete",
        response_model=AssetSnapshot | MomentAssetSnapshot,
    )
    async def post_upload_complete(
        body: GatewayUploadCompleteRequest,
        request: Request,
    ) -> AssetSnapshot | MomentAssetSnapshot:
        try:
            return await _database_call(request, complete_gateway_upload, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    @router.post(
        "/downloads/authorize", response_model=GatewayDownloadAuthorizeResponse
    )
    async def post_download_authorize(
        body: GatewayDownloadAuthorizeRequest,
        request: Request,
    ) -> GatewayDownloadAuthorizeResponse:
        try:
            return await _database_call(request, authorize_gateway_download, body)
        except AssetStoreError as exc:
            raise _translate_error(exc) from exc

    return router


def create_api_app(
    settings: AssetApiSettings, *, create_schema: bool = False
) -> FastAPI:
    database = DatabaseRuntime.create(settings.database_url)
    if create_schema:
        Base.metadata.create_all(database.engine)
    with database.session_factory() as session:
        ensure_dataset_identity(session, settings.dataset_id)
    database_executor = ThreadPoolExecutor(
        max_workers=settings.database_workers,
        thread_name_prefix="c19-asset-db",
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        yield
        database_executor.shutdown(wait=True, cancel_futures=True)
        database.dispose()

    app = FastAPI(
        title="C19 Asset Service",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.database_executor = database_executor

    @app.exception_handler(RequestValidationError)
    async def sanitized_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(status_code=422, content={"detail": "invalid request"})

    @app.exception_handler(SQLAlchemyError)
    async def sanitized_database_error(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=500,
            content={"detail": "asset service database operation failed"},
        )

    @app.get("/healthz", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        try:
            await _database_call(request, _health_check, settings.dataset_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="asset database unavailable") from exc
        return HealthResponse(
            status="ok", service="c19-asset-service", dataset_id=settings.dataset_id
        )

    app.include_router(_v1_router())
    app.include_router(_v2_router())
    app.include_router(_internal_router())
    return app


def create_api_app_from_env() -> FastAPI:
    return create_api_app(AssetApiSettings.from_environment())
