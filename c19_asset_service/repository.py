"""Transactional metadata, ticket, binding, and lifecycle operations."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import AssetApiSettings
from .models import Asset, AssetAuditEvent, DatasetIdentity, TransferTicket
from .quota import reserved_asset_bytes_expression, retained_asset_predicate
from .schemas import (
    AssetScopeRequest,
    AssetSnapshot,
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


class AssetStoreError(RuntimeError):
    pass


class AssetNotFoundError(AssetStoreError):
    pass


class AssetConflictError(AssetStoreError):
    pass


class AssetTombstoneError(AssetStoreError):
    pass


class AssetStateError(AssetStoreError):
    pass


class AssetQuotaError(AssetStoreError):
    pass


class AssetValidationError(AssetStoreError):
    pass


class TransferUnauthorizedError(AssetStoreError):
    pass


class DatasetMismatchError(AssetStoreError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def _audit(
    session: Session,
    asset: Asset,
    event_type: str,
    *,
    actor_type: str,
    actor_id: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    now: datetime | None = None,
) -> None:
    session.add(
        AssetAuditEvent(
            event_id=str(uuid.uuid4()),
            asset_id=asset.asset_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            occurred_at=now or utcnow(),
        )
    )


def ensure_dataset_identity(session: Session, dataset_id: str) -> None:
    identity = session.get(DatasetIdentity, "primary")
    if identity is None:
        session.add(
            DatasetIdentity(
                singleton_key="primary",
                dataset_id=dataset_id,
                blob_format_revision=1,
                created_at=utcnow(),
            )
        )
        try:
            session.commit()
            return
        except IntegrityError:
            session.rollback()
            identity = session.get(DatasetIdentity, "primary")
    if identity is None or identity.dataset_id != dataset_id:
        raise DatasetMismatchError("asset dataset identity mismatch")


@dataclass(frozen=True, slots=True)
class _UploadSpec:
    client_asset_id: str
    owner_user_id: str
    usage: str
    scope_id: str
    kind: str
    filename: str
    media_type: str
    size_bytes: int
    sha256_hex: str
    requested_at: datetime


def _chat_upload_spec(request: UploadIntentRequest) -> _UploadSpec:
    return _UploadSpec(
        client_asset_id=request.client_asset_id,
        owner_user_id=request.owner_user_id,
        usage="chat_message",
        scope_id=request.conversation_id,
        kind=request.kind,
        filename=request.filename,
        media_type=request.media_type,
        size_bytes=request.size_bytes,
        sha256_hex=request.sha256_hex,
        requested_at=request.requested_at,
    )


def _moment_upload_spec(request: MomentUploadIntentRequest) -> _UploadSpec:
    return _UploadSpec(
        client_asset_id=request.client_asset_id,
        owner_user_id=request.owner_user_id,
        usage="moment_image",
        scope_id=request.scope_id,
        kind="image",
        filename=request.filename,
        media_type=request.media_type,
        size_bytes=request.size_bytes,
        sha256_hex=request.sha256_hex,
        requested_at=request.requested_at,
    )


def _intent_hash(spec: _UploadSpec) -> str:
    # Preserve the exact Stage 4 chat hash so a replay remains idempotent after
    # the provider-neutral schema migration.  Moment intents use a separately
    # tagged hash domain and therefore cannot collide with a chat intent.
    if spec.usage == "chat_message":
        intent = {
            "client_asset_id": spec.client_asset_id,
            "conversation_id": spec.scope_id,
            "filename": spec.filename,
            "kind": spec.kind,
            "media_type": spec.media_type,
            "owner_user_id": spec.owner_user_id,
            "sha256_hex": spec.sha256_hex,
            "size_bytes": spec.size_bytes,
        }
    else:
        intent = {
            "client_asset_id": spec.client_asset_id,
            "filename": spec.filename,
            "kind": spec.kind,
            "media_type": spec.media_type,
            "owner_user_id": spec.owner_user_id,
            "scope_id": spec.scope_id,
            "sha256_hex": spec.sha256_hex,
            "size_bytes": spec.size_bytes,
            "usage": spec.usage,
        }
    canonical = json.dumps(
        intent,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _ticket_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("ascii")).hexdigest()


def _new_ticket() -> str:
    # token_urlsafe(32) is a 256-bit, unpadded 43-character value.
    value = secrets.token_urlsafe(32)
    if len(value) != 43:  # defensive against implementation changes
        raise AssetStoreError("secure ticket generation failed")
    return value


def _new_object_key() -> str:
    value = uuid.uuid4().hex
    return f"{value[:2]}/{value[2:4]}/{value[4:]}"


def _dataset_quota_lock_statement():
    """Single production-PostgreSQL serialization point for new reservations."""

    return (
        select(DatasetIdentity)
        .where(DatasetIdentity.singleton_key == "primary")
        .with_for_update()
    )


def _asset_snapshot(asset: Asset) -> AssetSnapshot:
    if (
        asset.filename is None
        or asset.media_type is None
        or asset.declared_size_bytes is None
        or asset.declared_sha256_hex is None
    ):
        raise AssetTombstoneError("asset was permanently deleted")
    if asset.usage != "chat_message":
        raise AssetNotFoundError("chat asset not found")
    return AssetSnapshot(
        asset_id=asset.asset_id,
        client_asset_id=asset.client_asset_id,
        owner_user_id=asset.owner_user_id,
        conversation_id=asset.scope_id,
        kind=asset.kind,
        filename=asset.filename,
        media_type=asset.media_type,
        size_bytes=asset.actual_size_bytes or asset.declared_size_bytes,
        sha256_hex=asset.actual_sha256_hex or asset.declared_sha256_hex,
        version=asset.version,
        status=asset.status,
    )


def _moment_asset_snapshot(asset: Asset) -> MomentAssetSnapshot:
    if (
        asset.usage != "moment_image"
        or asset.kind != "image"
        or asset.filename is None
        or asset.media_type is None
        or asset.declared_size_bytes is None
        or asset.declared_sha256_hex is None
    ):
        if asset.status == "deleted":
            raise AssetTombstoneError("asset was permanently deleted")
        raise AssetNotFoundError("Moment asset not found")
    return MomentAssetSnapshot(
        asset_id=asset.asset_id,
        client_asset_id=asset.client_asset_id,
        owner_user_id=asset.owner_user_id,
        usage="moment_image",
        scope_id=asset.scope_id,
        kind="image",
        filename=asset.filename,
        media_type=asset.media_type,
        size_bytes=asset.actual_size_bytes or asset.declared_size_bytes,
        sha256_hex=asset.actual_sha256_hex or asset.declared_sha256_hex,
        version=asset.version,
        status=asset.status,
    )


def _snapshot_for_usage(asset: Asset) -> AssetSnapshot | MomentAssetSnapshot:
    return (
        _asset_snapshot(asset)
        if asset.usage == "chat_message"
        else _moment_asset_snapshot(asset)
    )


def _asset_by_scope(
    session: Session,
    asset_id: str,
    owner_user_id: str,
    usage: str,
    scope_id: str,
    *,
    for_update: bool = False,
) -> Asset:
    statement = select(Asset).where(
        Asset.asset_id == asset_id,
        Asset.owner_user_id == owner_user_id,
        Asset.usage == usage,
        Asset.scope_id == scope_id,
    )
    if for_update:
        statement = statement.with_for_update()
    asset = session.execute(statement).scalar_one_or_none()
    if asset is None:
        raise AssetNotFoundError("asset not found")
    if asset.status == "deleted":
        raise AssetTombstoneError("asset was permanently deleted")
    return asset


def _revoke_tickets(session: Session, asset_id: str, now: datetime) -> None:
    session.execute(
        update(TransferTicket)
        .where(
            TransferTicket.asset_id == asset_id,
            TransferTicket.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


def _issue_upload_ticket(
    session: Session, asset: Asset, settings: AssetApiSettings, now: datetime
) -> tuple[str, datetime]:
    ticket = _new_ticket()
    expires_at = now + timedelta(seconds=settings.upload_ticket_ttl_seconds)
    session.add(
        TransferTicket(
            ticket_id=str(uuid.uuid4()),
            ticket_sha256=_ticket_hash(ticket),
            asset_id=asset.asset_id,
            direction="upload",
            owner_user_id=asset.owner_user_id,
            reader_user_id=None,
            usage=asset.usage,
            scope_id=asset.scope_id,
            bound_resource_id=None,
            variant=None,
            disposition=None,
            asset_version=asset.version,
            max_uses=1,
            used_count=0,
            created_at=now,
            expires_at=expires_at,
            last_used_at=None,
            revoked_at=None,
        )
    )
    return ticket, expires_at


def _replay_upload_intent(
    session: Session,
    existing: Asset,
    spec: _UploadSpec,
    settings: AssetApiSettings,
    *,
    intent_sha: str,
    now: datetime,
) -> UploadIntentResponse | MomentUploadIntentResponse:
    if existing.status == "deleted":
        raise AssetTombstoneError("asset key was permanently deleted")
    if (
        existing.usage != spec.usage
        or existing.scope_id != spec.scope_id
        or existing.intent_sha256 != intent_sha
    ):
        raise AssetConflictError("asset idempotency conflict")
    ticket: str | None = None
    expires_at: datetime | None = None
    if existing.status == "expired":
        _revoke_tickets(session, existing.asset_id, now)
        existing.status = "pending_upload"
        existing.version += 1
        existing.incoming_object_key = _new_object_key()
        existing.failure_code = None
        existing.updated_at = now
        _audit(
            session,
            existing,
            "upload_reopened",
            actor_type="barong",
            actor_id=spec.owner_user_id,
            from_status="expired",
            to_status="pending_upload",
            now=now,
        )
    if existing.status == "pending_upload":
        # Raw tickets are intentionally unrecoverable from their stored hashes.
        # A replay receives a new short ticket; earlier unexpired tickets remain
        # valid so concurrent identical requests cannot invalidate each other.
        live_ticket_count = session.scalar(
            select(func.count())
            .select_from(TransferTicket)
            .where(
                TransferTicket.asset_id == existing.asset_id,
                TransferTicket.direction == "upload",
                TransferTicket.revoked_at.is_(None),
                TransferTicket.expires_at > now,
            )
        )
        if int(live_ticket_count or 0) >= settings.max_upload_tickets_per_asset:
            # Do not return success while invalidating an already returned raw
            # ticket. The caller can use one of its live tickets or retry after
            # the short TTL expires.
            raise AssetQuotaError("upload ticket quota exceeded")
        ticket, expires_at = _issue_upload_ticket(session, existing, settings, now)
    session.commit()
    if spec.usage == "chat_message":
        return UploadIntentResponse(
            asset=_asset_snapshot(existing),
            upload_ticket=ticket,
            expires_at=expires_at,
        )
    return MomentUploadIntentResponse(
        asset=_moment_asset_snapshot(existing),
        upload_ticket=ticket,
        expires_at=expires_at,
    )


def _create_upload_intent(
    session: Session,
    spec: _UploadSpec,
    settings: AssetApiSettings,
) -> UploadIntentResponse | MomentUploadIntentResponse:
    maximum = settings.image_max_bytes if spec.kind == "image" else settings.file_max_bytes
    if spec.size_bytes > maximum:
        raise AssetValidationError("asset exceeds configured limit")
    now = utcnow()
    if spec.requested_at > now + timedelta(minutes=5):
        raise AssetValidationError("invalid request timestamp")
    intent_sha = _intent_hash(spec)
    # Production PostgreSQL serializes every new reservation on this single
    # dataset row. The re-check after acquiring the lock preserves idempotent
    # replay semantics for a concurrent winner before evaluating quotas.
    identity = session.execute(_dataset_quota_lock_statement()).scalar_one_or_none()
    if identity is None or identity.dataset_id != settings.dataset_id:
        raise DatasetMismatchError("asset dataset identity mismatch")
    existing = session.execute(
        select(Asset)
        .where(
            Asset.owner_user_id == spec.owner_user_id,
            Asset.client_asset_id == spec.client_asset_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == "expired":
            pending_count = session.scalar(
                select(func.count())
                .select_from(Asset)
                .where(
                    Asset.owner_user_id == spec.owner_user_id,
                    Asset.status.in_(("pending_upload", "uploaded", "scanning")),
                )
            )
            if int(pending_count or 0) >= settings.max_pending_uploads_per_owner:
                raise AssetQuotaError("pending upload quota exceeded")
        return _replay_upload_intent(
            session,
            existing,
            spec,
            settings,
            intent_sha=intent_sha,
            now=now,
        )

    pending_count = session.scalar(
        select(func.count())
        .select_from(Asset)
        .where(
            Asset.owner_user_id == spec.owner_user_id,
            Asset.status.in_(("pending_upload", "uploaded", "scanning")),
        )
    )
    if int(pending_count or 0) >= settings.max_pending_uploads_per_owner:
        raise AssetQuotaError("pending upload quota exceeded")
    reserved_bytes = reserved_asset_bytes_expression(settings.thumbnail_max_bytes)
    retained = retained_asset_predicate()
    owner_files = int(
        session.scalar(
            select(func.count(Asset.asset_id)).where(
                Asset.owner_user_id == spec.owner_user_id, retained
            )
        )
        or 0
    )
    owner_bytes = int(
        session.scalar(
            select(func.coalesce(func.sum(reserved_bytes), 0)).where(
                Asset.owner_user_id == spec.owner_user_id, retained
            )
        )
        or 0
    )
    global_files = int(
        session.scalar(select(func.count(Asset.asset_id)).where(retained)) or 0
    )
    global_bytes = int(
        session.scalar(
            select(func.coalesce(func.sum(reserved_bytes), 0)).where(retained)
        )
        or 0
    )
    if owner_files >= settings.owner_reserved_file_limit:
        raise AssetQuotaError("owner reserved file quota exceeded")
    prospective_bytes = spec.size_bytes + (
        settings.thumbnail_max_bytes if spec.kind == "image" else 0
    )
    if owner_bytes + prospective_bytes > settings.owner_reserved_byte_limit:
        raise AssetQuotaError("owner reserved byte quota exceeded")
    if global_files >= settings.global_reserved_file_limit:
        raise AssetQuotaError("global reserved file quota exceeded")
    if global_bytes + prospective_bytes > settings.global_reserved_byte_limit:
        raise AssetQuotaError("global reserved byte quota exceeded")
    asset = Asset(
        asset_id=f"att_{uuid.uuid4().hex}",
        client_asset_id=spec.client_asset_id,
        owner_user_id=spec.owner_user_id,
        usage=spec.usage,
        scope_id=spec.scope_id,
        kind=spec.kind,
        intent_sha256=intent_sha,
        filename=spec.filename,
        media_type=spec.media_type,
        declared_size_bytes=spec.size_bytes,
        declared_sha256_hex=spec.sha256_hex,
        actual_size_bytes=None,
        actual_sha256_hex=None,
        incoming_object_key=_new_object_key(),
        active_object_key=None,
        quarantine_object_key=None,
        thumbnail_object_key=None,
        thumbnail_size_bytes=None,
        thumbnail_sha256_hex=None,
        thumbnail_media_type=None,
        status="pending_upload",
        version=1,
        binding_status="unbound",
        binding_client_id=None,
        bound_resource_id=None,
        requested_at=spec.requested_at,
        created_at=now,
        updated_at=now,
        uploaded_at=None,
        activated_at=None,
        prepared_at=None,
        committed_at=None,
        deleted_at=None,
        failure_code=None,
    )
    session.add(asset)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        winner = session.execute(
            select(Asset)
            .where(
                Asset.owner_user_id == spec.owner_user_id,
                Asset.client_asset_id == spec.client_asset_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if winner is None:
            raise AssetStoreError("concurrent asset claim could not be resolved")
        return _replay_upload_intent(
            session,
            winner,
            spec,
            settings,
            intent_sha=intent_sha,
            now=utcnow(),
        )
    ticket, expires_at = _issue_upload_ticket(session, asset, settings, now)
    _audit(
        session,
        asset,
        "upload_intent_created",
        actor_type="barong",
        actor_id=spec.owner_user_id,
        to_status="pending_upload",
        now=now,
    )
    session.commit()
    if spec.usage == "chat_message":
        return UploadIntentResponse(
            asset=_asset_snapshot(asset), upload_ticket=ticket, expires_at=expires_at
        )
    return MomentUploadIntentResponse(
        asset=_moment_asset_snapshot(asset),
        upload_ticket=ticket,
        expires_at=expires_at,
    )


def create_upload_intent(
    session: Session,
    request: UploadIntentRequest,
    settings: AssetApiSettings,
) -> UploadIntentResponse:
    result = _create_upload_intent(session, _chat_upload_spec(request), settings)
    if not isinstance(result, UploadIntentResponse):
        raise AssetStoreError("chat upload returned the wrong usage")
    return result


def create_moment_upload_intent(
    session: Session,
    request: MomentUploadIntentRequest,
    settings: AssetApiSettings,
) -> MomentUploadIntentResponse:
    result = _create_upload_intent(session, _moment_upload_spec(request), settings)
    if not isinstance(result, MomentUploadIntentResponse):
        raise AssetStoreError("Moment upload returned the wrong usage")
    return result


def get_asset(
    session: Session, asset_id: str, owner_user_id: str, conversation_id: str
) -> AssetSnapshot:
    return _asset_snapshot(
        _asset_by_scope(
            session,
            asset_id,
            owner_user_id,
            "chat_message",
            conversation_id,
        )
    )


def get_moment_asset(
    session: Session, asset_id: str, owner_user_id: str, scope_id: str
) -> MomentAssetSnapshot:
    return _moment_asset_snapshot(
        _asset_by_scope(
            session,
            asset_id,
            owner_user_id,
            "moment_image",
            scope_id,
        )
    )


def finalize_asset(
    session: Session, asset_id: str, request: AssetScopeRequest
) -> AssetSnapshot:
    # Finalize is deliberately a safe poll. Gateway completion and the worker own
    # the state transitions; Barong cannot promote bytes.
    return get_asset(
        session, asset_id, request.owner_user_id, request.conversation_id
    )


def finalize_moment_asset(
    session: Session, asset_id: str, request: MomentAssetScopeRequest
) -> MomentAssetSnapshot:
    return get_moment_asset(
        session, asset_id, request.owner_user_id, request.scope_id
    )


def _prepare_binding(
    session: Session,
    *,
    asset_id: str,
    owner_user_id: str,
    usage: str,
    scope_id: str,
    binding_client_id: str,
) -> Asset:
    asset = _asset_by_scope(
        session,
        asset_id,
        owner_user_id,
        usage,
        scope_id,
        for_update=True,
    )
    if asset.status != "active":
        raise AssetStateError("asset is not active")
    if asset.binding_status == "unbound":
        now = utcnow()
        asset.binding_status = "prepared"
        asset.binding_client_id = binding_client_id
        asset.prepared_at = now
        asset.updated_at = now
        _audit(
            session,
            asset,
            "binding_prepared",
            actor_type="barong",
            actor_id=owner_user_id,
            now=now,
        )
    elif asset.binding_client_id != binding_client_id:
        raise AssetConflictError("asset is already bound")
    session.commit()
    return asset


def prepare_binding(
    session: Session, asset_id: str, request: PrepareBindingRequest
) -> BindingResponse:
    asset = _prepare_binding(
        session,
        asset_id=asset_id,
        owner_user_id=request.owner_user_id,
        usage="chat_message",
        scope_id=request.conversation_id,
        binding_client_id=request.client_message_id,
    )
    return BindingResponse(asset=_asset_snapshot(asset), binding_status=asset.binding_status)


def prepare_moment_binding(
    session: Session, asset_id: str, request: MomentPrepareBindingRequest
) -> MomentBindingResponse:
    asset = _prepare_binding(
        session,
        asset_id=asset_id,
        owner_user_id=request.owner_user_id,
        usage="moment_image",
        scope_id=request.scope_id,
        binding_client_id=request.binding_client_id,
    )
    return MomentBindingResponse(
        asset=_moment_asset_snapshot(asset), binding_status=asset.binding_status
    )


def _commit_binding(
    session: Session,
    *,
    asset_id: str,
    owner_user_id: str,
    usage: str,
    scope_id: str,
    binding_client_id: str,
    bound_resource_id: str,
) -> Asset:
    if usage == "moment_image" and bound_resource_id != scope_id:
        raise AssetValidationError("Moment binding scope mismatch")
    asset = _asset_by_scope(
        session,
        asset_id,
        owner_user_id,
        usage,
        scope_id,
        for_update=True,
    )
    if asset.status != "active":
        raise AssetStateError("asset is not active")
    if asset.binding_status == "unbound":
        raise AssetStateError("binding was not prepared")
    if asset.binding_client_id != binding_client_id:
        raise AssetConflictError("binding intent conflict")
    if asset.binding_status == "committed":
        if asset.bound_resource_id != bound_resource_id:
            raise AssetConflictError("binding resource conflict")
        return asset
    now = utcnow()
    asset.binding_status = "committed"
    asset.bound_resource_id = bound_resource_id
    asset.committed_at = now
    asset.updated_at = now
    _audit(
        session,
        asset,
        "binding_committed",
        actor_type="barong",
        actor_id=owner_user_id,
        now=now,
    )
    session.commit()
    return asset


def commit_binding(
    session: Session, asset_id: str, request: CommitBindingRequest
) -> BindingResponse:
    asset = _commit_binding(
        session,
        asset_id=asset_id,
        owner_user_id=request.owner_user_id,
        usage="chat_message",
        scope_id=request.conversation_id,
        binding_client_id=request.client_message_id,
        bound_resource_id=request.record_id,
    )
    return BindingResponse(asset=_asset_snapshot(asset), binding_status="committed")


def commit_moment_binding(
    session: Session, asset_id: str, request: MomentCommitBindingRequest
) -> MomentBindingResponse:
    asset = _commit_binding(
        session,
        asset_id=asset_id,
        owner_user_id=request.owner_user_id,
        usage="moment_image",
        scope_id=request.scope_id,
        binding_client_id=request.binding_client_id,
        bound_resource_id=request.bound_resource_id,
    )
    return MomentBindingResponse(
        asset=_moment_asset_snapshot(asset), binding_status="committed"
    )


def _create_download_intent(
    session: Session,
    *,
    asset_id: str,
    owner_user_id: str,
    reader_user_id: str,
    usage: str,
    scope_id: str,
    bound_resource_id: str,
    variant: str,
    disposition: str,
    asset_version: int,
    settings: AssetApiSettings,
) -> DownloadIntentResponse:
    asset = _asset_by_scope(
        session,
        asset_id,
        owner_user_id,
        usage,
        scope_id,
        for_update=True,
    )
    if (
        asset.status != "active"
        or asset.binding_status != "committed"
        or asset.bound_resource_id != bound_resource_id
        or asset.version != asset_version
        or (usage == "moment_image" and bound_resource_id != scope_id)
    ):
        raise AssetStateError("asset is unavailable")
    if variant == "thumbnail":
        if asset.kind != "image" or asset.thumbnail_object_key is None:
            raise AssetStateError("asset variant is unavailable")
    now = utcnow()
    ticket = _new_ticket()
    expires_at = now + timedelta(seconds=settings.download_ticket_ttl_seconds)
    session.add(
        TransferTicket(
            ticket_id=str(uuid.uuid4()),
            ticket_sha256=_ticket_hash(ticket),
            asset_id=asset.asset_id,
            direction="download",
            owner_user_id=asset.owner_user_id,
            reader_user_id=reader_user_id,
            usage=asset.usage,
            scope_id=asset.scope_id,
            bound_resource_id=bound_resource_id,
            variant=variant,
            disposition=disposition,
            asset_version=asset.version,
            max_uses=settings.download_ticket_max_uses,
            used_count=0,
            created_at=now,
            expires_at=expires_at,
            last_used_at=None,
            revoked_at=None,
        )
    )
    _audit(
        session,
        asset,
        "download_ticket_issued",
        actor_type="barong",
        actor_id=reader_user_id,
        now=now,
    )
    session.commit()
    return DownloadIntentResponse(download_ticket=ticket, expires_at=expires_at)


def create_download_intent(
    session: Session,
    asset_id: str,
    request: DownloadIntentRequest,
    settings: AssetApiSettings,
) -> DownloadIntentResponse:
    return _create_download_intent(
        session,
        asset_id=asset_id,
        owner_user_id=request.owner_user_id,
        reader_user_id=request.reader_user_id,
        usage="chat_message",
        scope_id=request.conversation_id,
        bound_resource_id=request.record_id,
        variant=request.variant,
        disposition=request.disposition,
        asset_version=request.asset_version,
        settings=settings,
    )


def create_moment_download_intent(
    session: Session,
    asset_id: str,
    request: MomentDownloadIntentRequest,
    settings: AssetApiSettings,
) -> DownloadIntentResponse:
    return _create_download_intent(
        session,
        asset_id=asset_id,
        owner_user_id=request.owner_user_id,
        reader_user_id=request.reader_user_id,
        usage="moment_image",
        scope_id=request.scope_id,
        bound_resource_id=request.bound_resource_id,
        variant=request.variant,
        disposition=request.disposition,
        asset_version=request.asset_version,
        settings=settings,
    )


def _load_valid_ticket(
    session: Session,
    raw_ticket: str,
    direction: str,
    *,
    for_update: bool = False,
    now: datetime | None = None,
) -> tuple[TransferTicket, Asset]:
    current = now or utcnow()
    statement = select(TransferTicket).where(
        TransferTicket.ticket_sha256 == _ticket_hash(raw_ticket),
        TransferTicket.direction == direction,
    )
    if for_update:
        statement = statement.with_for_update()
    ticket = session.execute(statement).scalar_one_or_none()
    if (
        ticket is None
        or ticket.revoked_at is not None
        or ticket.expires_at <= current
        or ticket.used_count >= ticket.max_uses
    ):
        raise TransferUnauthorizedError("transfer is unavailable")
    asset = session.get(Asset, ticket.asset_id)
    if (
        asset is None
        or asset.version != ticket.asset_version
        or ticket.owner_user_id != asset.owner_user_id
        or ticket.usage != asset.usage
        or ticket.scope_id != asset.scope_id
    ):
        raise TransferUnauthorizedError("transfer is unavailable")
    if direction == "upload":
        if (
            ticket.reader_user_id is not None
            or ticket.bound_resource_id is not None
            or ticket.variant is not None
            or ticket.disposition is not None
            or asset.status != "pending_upload"
            or asset.incoming_object_key is None
        ):
            raise TransferUnauthorizedError("transfer is unavailable")
    elif (
        asset.status != "active"
        or asset.binding_status != "committed"
        or not ticket.reader_user_id
        or asset.bound_resource_id != ticket.bound_resource_id
        or (asset.usage == "moment_image" and asset.scope_id != ticket.bound_resource_id)
    ):
        raise TransferUnauthorizedError("transfer is unavailable")
    return ticket, asset


def _inspect_transfer_scope(
    session: Session, request: TransferInspectRequest
) -> tuple[TransferTicket, Asset]:
    if request.direction == "upload":
        now = utcnow()
        ticket = session.execute(
            select(TransferTicket).where(
                TransferTicket.ticket_sha256 == _ticket_hash(request.ticket),
                TransferTicket.direction == "upload",
            )
        ).scalar_one_or_none()
        if (
            ticket is None
            or ticket.expires_at <= now
            or ticket.used_count > 1
        ):
            raise TransferUnauthorizedError("transfer is unavailable")
        asset = session.get(Asset, ticket.asset_id)
        if (
            asset is None
            or asset.version != ticket.asset_version
            or ticket.owner_user_id != asset.owner_user_id
            or ticket.usage != asset.usage
            or ticket.scope_id != asset.scope_id
            or ticket.reader_user_id is not None
            or ticket.bound_resource_id is not None
            or ticket.variant is not None
            or ticket.disposition is not None
            or asset.status not in {"pending_upload", "uploaded", "scanning", "active"}
            or (ticket.revoked_at is not None and ticket.used_count == 0)
        ):
            raise TransferUnauthorizedError("transfer is unavailable")
    else:
        ticket, asset = _load_valid_ticket(session, request.ticket, "download")
    if request.direction == "upload" and request.method != "PUT":
        raise TransferUnauthorizedError("transfer is unavailable")
    if request.direction == "download" and request.method not in {"GET", "HEAD"}:
        raise TransferUnauthorizedError("transfer is unavailable")
    return ticket, asset


def inspect_transfer(
    session: Session, request: TransferInspectRequest
) -> TransferInspectResponse:
    """Legacy exact chat wire retained for rolling compatibility."""

    ticket, asset = _inspect_transfer_scope(session, request)
    if asset.usage != "chat_message":
        raise TransferUnauthorizedError("transfer is unavailable")
    return TransferInspectResponse(
        asset_id=asset.asset_id,
        owner_user_id=ticket.owner_user_id,
        reader_user_id=ticket.reader_user_id,
        conversation_id=ticket.scope_id,
        record_id=ticket.bound_resource_id,
        variant=ticket.variant,
        version=ticket.asset_version,
        expires_at=ticket.expires_at,
    )


def inspect_scoped_transfer(
    session: Session, request: TransferInspectRequest
) -> ScopedTransferInspectResponse:
    ticket, asset = _inspect_transfer_scope(session, request)
    return ScopedTransferInspectResponse(
        asset_id=asset.asset_id,
        owner_user_id=ticket.owner_user_id,
        reader_user_id=ticket.reader_user_id,
        usage=ticket.usage,
        scope_id=ticket.scope_id,
        bound_resource_id=ticket.bound_resource_id,
        variant=ticket.variant,
        version=ticket.asset_version,
        expires_at=ticket.expires_at,
    )


def authorize_gateway_upload(
    session: Session,
    request: GatewayUploadAuthorizeRequest,
    settings: AssetApiSettings,
) -> GatewayUploadAuthorizeResponse:
    now = utcnow()
    ticket = session.execute(
        select(TransferTicket)
        .where(
            TransferTicket.ticket_sha256 == _ticket_hash(request.ticket),
            TransferTicket.direction == "upload",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if ticket is None or ticket.expires_at <= now or ticket.used_count > 1:
        raise TransferUnauthorizedError("transfer is unavailable")
    asset = session.execute(
        select(Asset).where(Asset.asset_id == ticket.asset_id).with_for_update()
    ).scalar_one_or_none()
    if (
        asset is None
        or asset.version != ticket.asset_version
        or ticket.owner_user_id != asset.owner_user_id
        or ticket.usage != asset.usage
        or ticket.scope_id != asset.scope_id
        or ticket.reader_user_id is not None
        or ticket.bound_resource_id is not None
        or ticket.variant is not None
        or ticket.disposition is not None
    ):
        raise TransferUnauthorizedError("transfer is unavailable")
    expected = int(asset.declared_size_bytes or 0)
    maximum = settings.image_max_bytes if asset.kind == "image" else settings.file_max_bytes
    if asset.status in {"uploaded", "scanning", "active"} and ticket.used_count == 1:
        # A gateway may have durably stored and completed the bytes while the
        # control response was lost. Reporting completion makes PUT replay safe.
        return GatewayUploadAuthorizeResponse(
            asset_id=asset.asset_id,
            object_key=None,
            expected_size_bytes=expected,
            maximum_size_bytes=maximum,
            upload_state="completed",
        )
    if (
        asset.status != "pending_upload"
        or asset.incoming_object_key is None
        or (ticket.revoked_at is not None and ticket.used_count == 0)
    ):
        raise TransferUnauthorizedError("transfer is unavailable")
    if request.content_length is not None and (
        request.content_length != expected or request.content_length > maximum
    ):
        raise AssetValidationError("upload size is invalid")
    if ticket.used_count == 0:
        ticket.used_count = 1
        ticket.last_used_at = now
        _audit(
            session,
            asset,
            "upload_authorized",
            actor_type="gateway",
            now=now,
        )
        session.commit()
    return GatewayUploadAuthorizeResponse(
        asset_id=asset.asset_id,
        object_key=asset.incoming_object_key or "",
        expected_size_bytes=expected,
        maximum_size_bytes=maximum,
        upload_state="ready",
    )


def complete_gateway_upload(
    session: Session, request: GatewayUploadCompleteRequest
) -> AssetSnapshot | MomentAssetSnapshot:
    now = utcnow()
    ticket = session.execute(
        select(TransferTicket)
        .where(
            TransferTicket.ticket_sha256 == _ticket_hash(request.ticket),
            TransferTicket.direction == "upload",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if ticket is None or ticket.used_count != 1:
        raise TransferUnauthorizedError("transfer is unavailable")
    asset = session.execute(
        select(Asset).where(Asset.asset_id == ticket.asset_id).with_for_update()
    ).scalar_one_or_none()
    if (
        asset is None
        or asset.version != ticket.asset_version
        or ticket.owner_user_id != asset.owner_user_id
        or ticket.usage != asset.usage
        or ticket.scope_id != asset.scope_id
        or ticket.reader_user_id is not None
        or ticket.bound_resource_id is not None
        or ticket.variant is not None
        or ticket.disposition is not None
    ):
        raise TransferUnauthorizedError("transfer is unavailable")
    if asset.status in {"uploaded", "scanning", "active"}:
        if (
            asset.actual_size_bytes == request.size_bytes
            and asset.actual_sha256_hex == request.sha256_hex
        ):
            return _snapshot_for_usage(asset)
        raise TransferUnauthorizedError("transfer is unavailable")
    if asset.status != "pending_upload" or ticket.revoked_at is not None:
        raise TransferUnauthorizedError("transfer is unavailable")
    if (
        request.size_bytes != asset.declared_size_bytes
        or request.sha256_hex != asset.declared_sha256_hex
    ):
        asset.actual_size_bytes = request.size_bytes
        asset.actual_sha256_hex = request.sha256_hex
        asset.status = "rejected"
        asset.failure_code = "declared_digest_mismatch"
        asset.updated_at = now
        _revoke_tickets(session, asset.asset_id, now)
        _audit(
            session,
            asset,
            "upload_rejected",
            actor_type="gateway",
            from_status="pending_upload",
            to_status="rejected",
            now=now,
        )
        session.commit()
        raise AssetValidationError("uploaded bytes do not match intent")
    asset.actual_size_bytes = request.size_bytes
    asset.actual_sha256_hex = request.sha256_hex
    asset.status = "uploaded"
    asset.uploaded_at = now
    asset.updated_at = now
    _revoke_tickets(session, asset.asset_id, now)
    _audit(
        session,
        asset,
        "upload_completed",
        actor_type="gateway",
        from_status="pending_upload",
        to_status="uploaded",
        now=now,
    )
    session.commit()
    return _snapshot_for_usage(asset)


def authorize_gateway_download(
    session: Session, request: GatewayDownloadAuthorizeRequest
) -> GatewayDownloadAuthorizeResponse:
    now = utcnow()
    ticket, asset = _load_valid_ticket(
        session, request.ticket, "download", for_update=True, now=now
    )
    if ticket.variant == "thumbnail":
        object_key = asset.thumbnail_object_key
        size = asset.thumbnail_size_bytes
        digest = asset.thumbnail_sha256_hex
        media_type = asset.thumbnail_media_type
    else:
        object_key = asset.active_object_key
        size = asset.actual_size_bytes
        digest = asset.actual_sha256_hex
        media_type = asset.media_type
    if not object_key or not size or not digest or not media_type or not asset.filename:
        raise TransferUnauthorizedError("transfer is unavailable")
    ticket.used_count += 1
    ticket.last_used_at = now
    _audit(
        session,
        asset,
        "download_authorized",
        actor_type="gateway",
        actor_id=ticket.reader_user_id,
        now=now,
    )
    session.commit()
    return GatewayDownloadAuthorizeResponse(
        asset_id=asset.asset_id,
        object_key=object_key,
        filename=asset.filename,
        media_type=media_type,
        size_bytes=size,
        sha256_hex=digest,
        disposition=ticket.disposition or "attachment",
        variant=ticket.variant or "original",
    )


def quarantine_asset(
    session: Session, asset_id: str, request: LifecycleRequest
) -> LifecycleResponse:
    asset = session.execute(
        select(Asset).where(Asset.asset_id == asset_id).with_for_update()
    ).scalar_one_or_none()
    if asset is None:
        raise AssetNotFoundError("asset not found")
    if asset.status == "deleted":
        raise AssetTombstoneError("asset was permanently deleted")
    if asset.status == "delete_pending":
        raise AssetStateError("asset deletion is pending")
    if asset.status != "quarantined":
        now = utcnow()
        previous = asset.status
        asset.status = "quarantined"
        asset.failure_code = "manual_quarantine"
        asset.version += 1
        asset.updated_at = now
        _revoke_tickets(session, asset.asset_id, now)
        _audit(
            session,
            asset,
            "asset_quarantined",
            actor_type="barong",
            actor_id=request.requested_by_user_id,
            from_status=previous,
            to_status="quarantined",
            now=now,
        )
        session.commit()
    return LifecycleResponse(
        asset_id=asset.asset_id, status="quarantined", version=asset.version
    )


def delete_asset(
    session: Session, asset_id: str, request: LifecycleRequest
) -> LifecycleResponse:
    asset = session.execute(
        select(Asset).where(Asset.asset_id == asset_id).with_for_update()
    ).scalar_one_or_none()
    if asset is None:
        raise AssetNotFoundError("asset not found")
    if asset.status == "deleted":
        return LifecycleResponse(
            asset_id=asset.asset_id, status="deleted", version=asset.version
        )
    if asset.status != "delete_pending":
        now = utcnow()
        previous = asset.status
        asset.status = "delete_pending"
        asset.version += 1
        asset.updated_at = now
        _revoke_tickets(session, asset.asset_id, now)
        _audit(
            session,
            asset,
            "asset_delete_requested",
            actor_type="barong",
            actor_id=request.requested_by_user_id,
            from_status=previous,
            to_status="delete_pending",
            now=now,
        )
        session.commit()
    return LifecycleResponse(
        asset_id=asset.asset_id, status=asset.status, version=asset.version
    )


def prepare_chat_retention_deletion(
    session: Session,
    asset_id: str,
    request: ChatRetentionDeletionRequest,
) -> ChatRetentionPreparationResponse:
    """Durably prepare an exact binding without making bytes worker-eligible.

    A missing asset, wrong usage, scope, or bound record is deliberately a
    terminal protected result. The worker does not consume this preparation;
    only a later exact commit, after Record's reference fence authorization,
    can transition the asset to ``delete_pending``.
    """

    asset = session.execute(
        select(Asset).where(Asset.asset_id == asset_id).with_for_update()
    ).scalar_one_or_none()
    if (
        asset is None
        or asset.usage != "chat_message"
        or asset.scope_id != request.conversation_id
        or asset.binding_status != "committed"
        or asset.bound_resource_id != request.record_id
    ):
        return ChatRetentionPreparationResponse(
            asset_id=asset_id,
            disposition="protected",
            status="retained",
        )
    prepared = (
        asset.retention_operation_id,
        asset.retention_record_id,
        asset.retention_conversation_id,
    )
    expected = (request.operation_id, request.record_id, request.conversation_id)
    if asset.retention_operation_id is not None and prepared != expected:
        return ChatRetentionPreparationResponse(
            asset_id=asset.asset_id,
            disposition="protected",
            status="retained",
        )
    if asset.retention_operation_id is None:
        now = utcnow()
        asset.retention_operation_id = request.operation_id
        asset.retention_record_id = request.record_id
        asset.retention_conversation_id = request.conversation_id
        asset.retention_prepared_at = now
        _audit(
            session,
            asset,
            "retention_delete_prepared",
            actor_type="system",
            actor_id=request.operation_id,
            from_status=asset.status,
            to_status=asset.status,
            now=now,
        )
        session.commit()
    return ChatRetentionPreparationResponse(
        asset_id=asset.asset_id,
        disposition="accepted",
        status="prepared",
    )


def commit_chat_retention_deletion(
    session: Session,
    asset_id: str,
    request: ChatRetentionDeletionRequest,
) -> ChatRetentionDeletionResponse:
    """Commit a previously prepared exact binding to the worker queue."""

    asset = session.execute(
        select(Asset).where(Asset.asset_id == asset_id).with_for_update()
    ).scalar_one_or_none()
    if asset is None:
        raise AssetConflictError("retention preparation is missing")
    expected = (request.operation_id, request.record_id, request.conversation_id)
    prepared = (
        asset.retention_operation_id,
        asset.retention_record_id,
        asset.retention_conversation_id,
    )
    if (
        asset.usage != "chat_message"
        or asset.scope_id != request.conversation_id
        or asset.binding_status != "committed"
        or asset.bound_resource_id != request.record_id
        or prepared != expected
    ):
        raise AssetConflictError("retention preparation conflict")
    if asset.status == "deleted":
        return ChatRetentionDeletionResponse(
            asset_id=asset.asset_id,
            disposition="accepted",
            status="deleted",
        )
    if asset.status != "delete_pending":
        now = utcnow()
        previous = asset.status
        asset.status = "delete_pending"
        asset.version += 1
        asset.updated_at = now
        _revoke_tickets(session, asset.asset_id, now)
        _audit(
            session,
            asset,
            "retention_delete_requested",
            actor_type="system",
            actor_id=request.operation_id,
            from_status=previous,
            to_status="delete_pending",
            now=now,
        )
        session.commit()
    return ChatRetentionDeletionResponse(
        asset_id=asset.asset_id,
        disposition="accepted",
        status="delete_pending",
    )
