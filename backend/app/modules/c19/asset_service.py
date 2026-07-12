"""Authorization and metadata orchestration for C19 image/file assets."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ...models.user import User
from .asset_schemas import (
    ChatAssetAccessIntentRead,
    ChatAssetAccessIntentRequest,
    ChatAssetRead,
    ChatAssetUploadIntentRead,
    ChatAssetUploadIntentRequest,
)
from .message_service import authorize_conversation
from .moment_policy import build_viewer_context
from .moment_storage import (
    MomentAssetStore,
    MomentQueryDTO,
    MomentStore,
    ScopedAssetTransferInspectionDTO,
)
from .storage import (
    ChatAssetBindingCommitCommandDTO,
    ChatAssetDTO,
    ChatAssetDownloadRequestDTO,
    ChatAssetFinalizeCommandDTO,
    ChatAssetLookupDTO,
    ChatAssetReferenceDTO,
    ChatAssetStore,
    ChatAssetTransferInspectDTO,
    ChatAssetTransferInspectionDTO,
    ChatAssetUploadMetadataDTO,
    ChatRecordDTO,
    ChatRecordStore,
)


_TRANSFER_URI_RE = re.compile(
    r"^/api/backend/c19-assets/(?P<direction>[ud])/(?P<ticket>[A-Za-z0-9_-]{43})$"
)


class C19AssetAccessError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _asset_unavailable(*, transfer: bool = False) -> C19AssetAccessError:
    return C19AssetAccessError(
        code="c19_asset_transfer_denied" if transfer else "c19_asset_unavailable",
        message="Asset transfer denied." if transfer else "Asset is unavailable.",
        status_code=403 if transfer else 404,
    )


def _asset_read(asset: ChatAssetDTO) -> ChatAssetRead:
    return ChatAssetRead(
        asset_id=asset.asset_id,
        client_asset_id=asset.client_asset_id,
        kind=asset.kind,
        filename=asset.filename,
        media_type=asset.media_type,
        size_bytes=asset.size_bytes,
        sha256_hex=asset.sha256_hex,
        version=asset.version,
        status=asset.status,
    )


def _find_record_asset(
    record: ChatRecordDTO,
    *,
    asset_id: str,
) -> ChatAssetReferenceDTO:
    matches = tuple(asset for asset in record.assets if asset.asset_id == asset_id)
    if len(matches) != 1:
        raise _asset_unavailable()
    return matches[0]


def _validate_active_snapshot(
    asset: ChatAssetDTO,
    reference: ChatAssetReferenceDTO,
    *,
    record: ChatRecordDTO,
) -> None:
    if (
        asset.status != "active"
        or asset.asset_id != reference.asset_id
        or asset.client_asset_id != reference.client_asset_id
        or asset.owner_user_id != record.sender_user_id
        or asset.conversation_id != record.conversation_id
        or asset.kind != reference.kind
        or asset.filename != reference.filename
        or asset.media_type != reference.media_type
        or asset.size_bytes != reference.size_bytes
        or asset.sha256_hex != reference.sha256_hex
        or asset.version != reference.version
    ):
        raise _asset_unavailable()


async def create_asset_upload_intent(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    payload: ChatAssetUploadIntentRequest,
    asset_store: ChatAssetStore,
) -> ChatAssetUploadIntentRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
        for_send=True,
    )
    db.rollback()
    result = await asset_store.create_upload_intent(
        ChatAssetUploadMetadataDTO(
            client_asset_id=payload.client_asset_id,
            owner_user_id=str(access.actor_user_id),
            conversation_id=conversation_id,
            kind=payload.kind,
            filename=payload.filename,
            media_type=payload.media_type,
            size_bytes=payload.size_bytes,
            sha256_hex=payload.sha256_hex,
            requested_at=datetime.now(UTC),
        )
    )
    if (
        result.asset.owner_user_id != str(access.actor_user_id)
        or result.asset.conversation_id != conversation_id
        or result.asset.client_asset_id != payload.client_asset_id
        or result.asset.kind != payload.kind
        or result.asset.filename != payload.filename
        or result.asset.media_type != payload.media_type
        or result.asset.size_bytes != payload.size_bytes
        or result.asset.sha256_hex != payload.sha256_hex
        or ((result.opaque_ticket is None) != (result.expires_at is None))
        or (
            result.asset.status == "pending_upload"
            and result.opaque_ticket is None
        )
        or (
            result.asset.status != "pending_upload"
            and result.opaque_ticket is not None
        )
        or (
            result.expires_at is not None
            and result.expires_at <= datetime.now(UTC)
        )
    ):
        from .http_asset_store import ChatAssetStoreProtocolError

        raise ChatAssetStoreProtocolError(operation="create_upload_intent")
    return ChatAssetUploadIntentRead(
        asset=_asset_read(result.asset),
        upload_locator=(
            None
            if result.opaque_ticket is None
            else f"/api/backend/c19-assets/u/{result.opaque_ticket}"
        ),
        expires_at=result.expires_at,
    )


async def get_asset_status(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    asset_id: str,
    asset_store: ChatAssetStore,
) -> ChatAssetRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
        for_send=True,
    )
    db.rollback()
    asset = await asset_store.get_asset(
        ChatAssetLookupDTO(
            asset_id=asset_id,
            owner_user_id=str(access.actor_user_id),
            conversation_id=conversation_id,
        )
    )
    return _asset_read(asset)


async def finalize_asset_upload(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    asset_id: str,
    asset_store: ChatAssetStore,
) -> ChatAssetRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
        for_send=True,
    )
    db.rollback()
    asset = await asset_store.finalize_upload(
        ChatAssetFinalizeCommandDTO(
            asset_id=asset_id,
            owner_user_id=str(access.actor_user_id),
            conversation_id=conversation_id,
        )
    )
    return _asset_read(asset)


async def create_asset_access_intent(
    db: Session,
    *,
    actor: User,
    conversation_id: str,
    record_id: str,
    asset_id: str,
    payload: ChatAssetAccessIntentRequest,
    record_store: ChatRecordStore,
    asset_store: ChatAssetStore,
) -> ChatAssetAccessIntentRead:
    access = authorize_conversation(
        db,
        actor=actor,
        conversation_id=conversation_id,
    )
    db.rollback()
    user_id = str(access.actor_user_id)
    record = await record_store.get_authorized_record(
        conversation_id=conversation_id,
        record_id=record_id,
        user_id=user_id,
    )
    reference = _find_record_asset(record, asset_id=asset_id)
    if payload.variant == "thumbnail" and reference.kind != "image":
        raise _asset_unavailable()
    asset = await asset_store.get_asset(
        ChatAssetLookupDTO(
            asset_id=asset_id,
            owner_user_id=record.sender_user_id,
            conversation_id=conversation_id,
        )
    )
    _validate_active_snapshot(asset, reference, record=record)

    # The record is the authority for the durable asset reference. If Barong
    # crashed after appending that record but before committing the prepared
    # Asset Service binding, an authorized first read must be able to repair the
    # split transaction without relying on browser-memory retry state. The
    # Asset Service accepts this only for the original prepared
    # client_message_id and makes an already matching commit idempotent.
    from .http_asset_store import ChatAssetStoreConflictError

    try:
        committed = await asset_store.commit_binding(
            ChatAssetBindingCommitCommandDTO(
                asset_id=asset_id,
                owner_user_id=record.sender_user_id,
                conversation_id=conversation_id,
                client_message_id=record.client_message_id,
                record_id=record.record_id,
            )
        )
    except ChatAssetStoreConflictError:
        # A mismatching prepared client-message or committed record is an opaque
        # unavailable asset, not a public upload-idempotency oracle.
        raise _asset_unavailable() from None
    if committed.binding_status != "committed":
        from .http_asset_store import ChatAssetStoreProtocolError

        raise ChatAssetStoreProtocolError(operation="commit_binding")
    _validate_active_snapshot(committed.asset, reference, record=record)

    disposition = (
        "inline"
        if payload.variant == "thumbnail" and reference.kind == "image"
        else "attachment"
    )
    result = await asset_store.create_download_intent(
        ChatAssetDownloadRequestDTO(
            asset_id=asset_id,
            owner_user_id=record.sender_user_id,
            reader_user_id=user_id,
            conversation_id=conversation_id,
            record_id=record_id,
            variant=payload.variant,
            disposition=disposition,
            asset_version=reference.version,
        )
    )
    if result.expires_at <= datetime.now(UTC):
        from .http_asset_store import ChatAssetStoreProtocolError

        raise ChatAssetStoreProtocolError(operation="create_download_intent")
    return ChatAssetAccessIntentRead(
        download_locator=f"/api/backend/c19-assets/d/{result.opaque_ticket}",
        expires_at=result.expires_at,
    )


def _parse_transfer_headers(
    *,
    transfer_uri: str,
    transfer_method: str,
) -> ChatAssetTransferInspectDTO:
    match = _TRANSFER_URI_RE.fullmatch(transfer_uri)
    if match is None:
        raise _asset_unavailable(transfer=True)
    direction = "upload" if match.group("direction") == "u" else "download"
    method = transfer_method.upper()
    if transfer_method != method or (
        (direction == "upload" and method != "PUT")
        or (direction == "download" and method not in {"GET", "HEAD"})
    ):
        raise _asset_unavailable(transfer=True)
    return ChatAssetTransferInspectDTO(
        opaque_ticket=match.group("ticket"),
        direction=direction,
        method=method,  # type: ignore[arg-type]
    )


async def authorize_asset_transfer(
    db: Session,
    *,
    actor: User,
    transfer_uri: str,
    transfer_method: str,
    record_store: ChatRecordStore,
    asset_store: ChatAssetStore,
    moment_store: MomentStore | None = None,
    moment_asset_store: MomentAssetStore | None = None,
) -> ChatAssetTransferInspectionDTO | ScopedAssetTransferInspectionDTO:
    command = _parse_transfer_headers(
        transfer_uri=transfer_uri,
        transfer_method=transfer_method,
    )
    # Keep the legacy branch for isolated Stage 4 callers and tests.  The
    # application route always supplies the scoped v2 port after Stage 5.
    if moment_asset_store is None:
        inspection = await asset_store.inspect_transfer(command)
        if inspection.expires_at <= datetime.now(UTC):
            raise _asset_unavailable(transfer=True)

        if command.direction == "upload":
            access = authorize_conversation(
                db,
                actor=actor,
                conversation_id=inspection.conversation_id,
                for_send=True,
            )
            db.rollback()
            if (
                str(access.actor_user_id) != inspection.owner_user_id
                or inspection.reader_user_id is not None
                or inspection.record_id is not None
                or inspection.variant is not None
            ):
                raise _asset_unavailable(transfer=True)
            return inspection

        access = authorize_conversation(
            db,
            actor=actor,
            conversation_id=inspection.conversation_id,
        )
        db.rollback()
        user_id = str(access.actor_user_id)
        if (
            inspection.reader_user_id != user_id
            or inspection.record_id is None
            or inspection.variant is None
        ):
            raise _asset_unavailable(transfer=True)
        record = await record_store.get_authorized_record(
            conversation_id=inspection.conversation_id,
            record_id=inspection.record_id,
            user_id=user_id,
        )
        reference = _find_record_asset(record, asset_id=inspection.asset_id)
        if (
            record.sender_user_id != inspection.owner_user_id
            or reference.version != inspection.version
            or (inspection.variant == "thumbnail" and reference.kind != "image")
        ):
            raise _asset_unavailable(transfer=True)
        return inspection

    inspection = await moment_asset_store.inspect_scoped_transfer(
        opaque_ticket=command.opaque_ticket,
        direction=command.direction,
        method=command.method,
    )
    if inspection.expires_at <= datetime.now(UTC):
        raise _asset_unavailable(transfer=True)

    if inspection.usage == "chat_message" and command.direction == "upload":
        access = authorize_conversation(
            db,
            actor=actor,
            conversation_id=inspection.scope_id,
            for_send=True,
        )
        db.rollback()
        if (
            str(access.actor_user_id) != inspection.owner_user_id
            or inspection.reader_user_id is not None
            or inspection.bound_resource_id is not None
            or inspection.variant is not None
        ):
            raise _asset_unavailable(transfer=True)
        return inspection

    if inspection.usage == "chat_message":
        access = authorize_conversation(
            db,
            actor=actor,
            conversation_id=inspection.scope_id,
        )
        db.rollback()
        user_id = str(access.actor_user_id)
        if (
            command.direction != "download"
            or inspection.reader_user_id != user_id
            or inspection.bound_resource_id is None
            or inspection.variant is None
        ):
            raise _asset_unavailable(transfer=True)
        record = await record_store.get_authorized_record(
            conversation_id=inspection.scope_id,
            record_id=inspection.bound_resource_id,
            user_id=user_id,
        )
        reference = _find_record_asset(record, asset_id=inspection.asset_id)
        if (
            record.sender_user_id != inspection.owner_user_id
            or reference.version != inspection.version
            or (inspection.variant == "thumbnail" and reference.kind != "image")
        ):
            raise _asset_unavailable(transfer=True)
        return inspection

    if moment_store is None:
        raise _asset_unavailable(transfer=True)
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    if command.direction == "upload":
        if (
            context.viewer_user_id != inspection.owner_user_id
            or inspection.reader_user_id is not None
            or inspection.bound_resource_id is not None
            or inspection.variant is not None
        ):
            raise _asset_unavailable(transfer=True)
        draft = await moment_store.get_moment_draft(
            moment_id=inspection.scope_id,
            author_user_id=context.viewer_user_id,
        )
        if (
            draft.moment_id != inspection.scope_id
            or draft.author_user_id != context.viewer_user_id
            or draft.state != "draft"
        ):
            raise _asset_unavailable(transfer=True)
        return inspection

    if (
        command.direction != "download"
        or inspection.reader_user_id != context.viewer_user_id
        or inspection.bound_resource_id != inspection.scope_id
        or inspection.variant is None
    ):
        raise _asset_unavailable(transfer=True)
    moment = await moment_store.get_moment(
        MomentQueryDTO(context=context, moment_id=inspection.scope_id)
    )
    matches = tuple(
        reference
        for reference in moment.assets
        if reference.asset_id == inspection.asset_id
    )
    if (
        len(matches) != 1
        or moment.author_user_id != inspection.owner_user_id
        or matches[0].version != inspection.version
        or matches[0].kind != "image"
    ):
        raise _asset_unavailable(transfer=True)
    return inspection


__all__ = [
    "C19AssetAccessError",
    "authorize_asset_transfer",
    "create_asset_access_intent",
    "create_asset_upload_intent",
    "finalize_asset_upload",
    "get_asset_status",
]
