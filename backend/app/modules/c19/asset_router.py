"""Authenticated C19 asset-control routes; no endpoint accepts file bytes."""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...db.session import get_db
from ...models.user import User
from .asset_schemas import (
    ASSET_ID_PATTERN,
    ChatAssetAccessIntentRead,
    ChatAssetAccessIntentRequest,
    ChatAssetRead,
    ChatAssetUploadIntentRead,
    ChatAssetUploadIntentRequest,
)
from .asset_service import (
    C19AssetAccessError,
    authorize_asset_transfer,
    create_asset_access_intent,
    create_asset_upload_intent,
    finalize_asset_upload,
    get_asset_status,
)
from .asset_store_provider import get_chat_asset_store
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
    ChatRecordStoreHttpError,
    ChatRecordStoreProtocolError,
    ChatRecordStoreRejectedError,
    ChatRecordStoreUnavailableError,
)
from .message_service import C19ChatAccessError
from .moment_storage import MomentAssetStore, MomentStore
from .moment_store_provider import get_moment_asset_store, get_moment_store
from .record_store_provider import get_chat_record_store
from .storage import C19StorageUnconfiguredError, ChatAssetStore, ChatRecordStore


router = APIRouter(prefix="/c19", tags=["c19-chat-assets"])
ConversationIdPath = Annotated[str, Path(min_length=1, max_length=64)]
RecordIdPath = Annotated[str, Path(min_length=1, max_length=128)]
AssetIdPath = Annotated[str, Path(pattern=ASSET_ID_PATTERN)]
AssetStoreDependency = Annotated[ChatAssetStore, Depends(get_chat_asset_store)]
RecordStoreDependency = Annotated[ChatRecordStore, Depends(get_chat_record_store)]
MomentStoreDependency = Annotated[MomentStore, Depends(get_moment_store)]
MomentAssetStoreDependency = Annotated[
    MomentAssetStore,
    Depends(get_moment_asset_store),
]


def _raise_asset_error(
    db: Session,
    exc: Exception,
    *,
    transfer: bool = False,
) -> NoReturn:
    db.rollback()
    if isinstance(exc, C19ChatAccessError):
        status_code = 403 if transfer else exc.status_code
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": "c19_asset_transfer_denied" if transfer else exc.code,
                "message": "Asset transfer denied." if transfer else exc.message,
            },
        ) from None
    if isinstance(exc, C19AssetAccessError):
        raise HTTPException(
            status_code=403 if transfer else exc.status_code,
            detail={
                "code": "c19_asset_transfer_denied" if transfer else exc.code,
                "message": "Asset transfer denied." if transfer else exc.message,
            },
        ) from None
    if isinstance(exc, ChatAssetStoreConflictError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "c19_asset_idempotency_conflict",
                "message": "The client asset ID is already used by another upload.",
            },
        ) from None
    if isinstance(exc, ChatAssetStoreQuotaError):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "c19_asset_quota_exceeded",
                "message": "The asset upload quota is currently exhausted.",
            },
        ) from None
    if isinstance(exc, (ChatAssetStoreRejectedError, ChatRecordStoreRejectedError)):
        if transfer:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "c19_asset_transfer_denied",
                    "message": "Asset transfer denied.",
                },
            ) from None
        status_code = exc.status_code or 422
        if status_code == 410:
            code = "c19_asset_deleted"
            message = "The asset is no longer available."
        elif status_code == 413:
            code = "c19_asset_too_large"
            message = "The asset exceeds the allowed size."
        elif status_code == 415:
            code = "c19_asset_type_unsupported"
            message = "The asset type is unsupported."
        elif status_code == 404:
            code = "c19_asset_unavailable"
            message = "Asset is unavailable."
        else:
            status_code = 422
            code = "c19_asset_rejected"
            message = "The asset request was rejected."
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message": message},
        ) from None
    if isinstance(
        exc,
        (
            C19StorageUnconfiguredError,
            ChatAssetStoreAuthenticationError,
            ChatAssetStoreUnavailableError,
            ChatRecordStoreAuthenticationError,
            ChatRecordStoreUnavailableError,
        ),
    ):
        if transfer:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "c19_asset_transfer_unavailable",
                    "message": "Asset transfer authorization is unavailable.",
                },
            ) from None
        raise HTTPException(
            status_code=503,
            detail={
                "code": "c19_asset_store_unavailable",
                "message": "Chat asset storage is unavailable.",
            },
        ) from None
    if isinstance(
        exc,
        (
            ChatAssetStoreProtocolError,
            ChatRecordStoreProtocolError,
        ),
    ):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "c19_asset_store_invalid_response",
                "message": "Chat asset storage returned an invalid response.",
            },
        ) from None
    if isinstance(exc, (ChatAssetStoreHttpError, ChatRecordStoreHttpError)):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "c19_asset_store_error",
                "message": "Chat asset storage request failed.",
            },
        ) from None
    raise exc


@router.post(
    "/conversations/{conversation_id}/assets/upload-intents",
    response_model=ChatAssetUploadIntentRead,
)
async def asset_upload_intent_endpoint(
    payload: ChatAssetUploadIntentRequest,
    conversation_id: ConversationIdPath,
    asset_store: AssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatAssetUploadIntentRead:
    try:
        return await create_asset_upload_intent(
            db,
            actor=actor,
            conversation_id=conversation_id,
            payload=payload,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_asset_error(db, exc)


@router.post(
    "/conversations/{conversation_id}/assets/{asset_id}/finalize",
    response_model=ChatAssetRead,
)
async def asset_finalize_endpoint(
    conversation_id: ConversationIdPath,
    asset_id: AssetIdPath,
    asset_store: AssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatAssetRead:
    try:
        return await finalize_asset_upload(
            db,
            actor=actor,
            conversation_id=conversation_id,
            asset_id=asset_id,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_asset_error(db, exc)


@router.get(
    "/conversations/{conversation_id}/assets/{asset_id}",
    response_model=ChatAssetRead,
)
async def asset_status_endpoint(
    conversation_id: ConversationIdPath,
    asset_id: AssetIdPath,
    asset_store: AssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatAssetRead:
    try:
        return await get_asset_status(
            db,
            actor=actor,
            conversation_id=conversation_id,
            asset_id=asset_id,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_asset_error(db, exc)


@router.post(
    (
        "/conversations/{conversation_id}/records/{record_id}"
        "/assets/{asset_id}/access-intents"
    ),
    response_model=ChatAssetAccessIntentRead,
)
async def asset_access_intent_endpoint(
    payload: ChatAssetAccessIntentRequest,
    conversation_id: ConversationIdPath,
    record_id: RecordIdPath,
    asset_id: AssetIdPath,
    record_store: RecordStoreDependency,
    asset_store: AssetStoreDependency,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatAssetAccessIntentRead:
    try:
        return await create_asset_access_intent(
            db,
            actor=actor,
            conversation_id=conversation_id,
            record_id=record_id,
            asset_id=asset_id,
            payload=payload,
            record_store=record_store,
            asset_store=asset_store,
        )
    except Exception as exc:
        _raise_asset_error(db, exc)


@router.get("/assets/transfers/authorize", status_code=204)
async def asset_transfer_authorize_endpoint(
    record_store: RecordStoreDependency,
    asset_store: AssetStoreDependency,
    moment_store: MomentStoreDependency,
    moment_asset_store: MomentAssetStoreDependency,
    transfer_uri: Annotated[
        str,
        Header(alias="X-C19-Transfer-URI"),
    ] = "",
    transfer_method: Annotated[
        str,
        Header(alias="X-C19-Transfer-Method"),
    ] = "",
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Response:
    try:
        await authorize_asset_transfer(
            db,
            actor=actor,
            transfer_uri=transfer_uri,
            transfer_method=transfer_method,
            record_store=record_store,
            asset_store=asset_store,
            moment_store=moment_store,
            moment_asset_store=moment_asset_store,
        )
        return Response(
            status_code=204,
            headers={"Cache-Control": "private, no-store"},
        )
    except Exception as exc:
        _raise_asset_error(db, exc, transfer=True)


__all__ = ["router"]
