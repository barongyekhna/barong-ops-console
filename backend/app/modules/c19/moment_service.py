"""Barong authorization and cross-store orchestration for C19 Moments."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models.operation_log import OperationLog
from ...models.user import User
from ...repositories.operation_logs import create_operation_log
from ...services.auth_service import AuditContext
from ...services.data_isolation import without_org_data_isolation
from . import identity_repository, moment_repository
from .asset_schemas import ChatAssetRead, ChatAssetReferenceRead
from .identity_service import profile_summary_from_bundle
from .moment_policy import (
    C19MomentPolicyError,
    actor_user_id,
    build_viewer_context,
    resolve_publish_audience,
)
from .moment_schemas import (
    MomentAssetAccessIntentRead,
    MomentAssetAccessIntentRequest,
    MomentAssetUploadIntentRead,
    MomentAssetUploadIntentRequest,
    MomentAudienceOrganizationRead,
    MomentCommentCreateRequest,
    MomentCommentDeleteRead,
    MomentCommentPageRead,
    MomentCommentRead,
    MomentDeleteRead,
    MomentDraftCreateRequest,
    MomentDraftRead,
    MomentEventPageRead,
    MomentEventRead,
    MomentEventTailRead,
    MomentFeedPageRead,
    MomentLikeMutationRead,
    MomentLikePageRead,
    MomentLikeRead,
    MomentPublishRequest,
    MomentRead,
)
from .moment_storage import (
    MomentAssetBindingCommitDTO,
    MomentAssetBindingPrepareDTO,
    MomentAssetDTO,
    MomentAssetDownloadRequestDTO,
    MomentAssetFinalizeDTO,
    MomentAssetLookupDTO,
    MomentAssetStore,
    MomentAssetUploadMetadataDTO,
    MomentCommentCreateDTO,
    MomentCommentDeleteDTO,
    MomentCommentDTO,
    MomentCommentQueryDTO,
    MomentDTO,
    MomentDeleteCommandDTO,
    MomentDraftDTO,
    MomentDraftReserveDTO,
    MomentFeedQueryDTO,
    MomentLikeCommandDTO,
    MomentLikeDTO,
    MomentLikeQueryDTO,
    MomentPublishDTO,
    MomentQueryDTO,
    MomentStore,
    MomentUserEventQueryDTO,
)
from .storage import ChatAssetDeleteCommandDTO, ChatAssetReferenceDTO


class C19MomentAccessError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _moment_unavailable() -> C19MomentAccessError:
    return C19MomentAccessError(
        code="c19_moment_unavailable",
        message="Moment is unavailable.",
        status_code=404,
    )


def _asset_unavailable() -> C19MomentAccessError:
    return C19MomentAccessError(
        code="c19_asset_unavailable",
        message="Asset is unavailable.",
        status_code=404,
    )


def _idempotency_conflict() -> C19MomentAccessError:
    return C19MomentAccessError(
        code="c19_moment_idempotency_conflict",
        message="The Moment was already published with another payload.",
        status_code=409,
    )


def _write_audit(
    db: Session,
    *,
    actor_id: int,
    action: str,
    target_type: str,
    target_id: str,
    audit: AuditContext | None,
    details: dict[str, object] | None = None,
    deduplicate: bool = False,
) -> None:
    if deduplicate:
        with without_org_data_isolation():
            existing = db.scalar(
                select(OperationLog.id)
                .where(
                    OperationLog.actor_type == "user",
                    OperationLog.actor_id == str(actor_id),
                    OperationLog.action == action,
                    OperationLog.target_type == target_type,
                    OperationLog.target_id == target_id,
                    OperationLog.result == "success",
                )
                .limit(1)
            )
        if existing is not None:
            db.rollback()
            return
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(actor_id),
        action=action,
        target_type=target_type,
        target_id=target_id,
        result="success",
        request_id=audit.request_id if audit is not None else None,
        ip_address=audit.ip_address if audit is not None else None,
        user_agent=audit.user_agent if audit is not None else None,
        details=details,
    )
    db.commit()


def _draft_read(draft: MomentDraftDTO) -> MomentDraftRead:
    return MomentDraftRead(
        moment_id=draft.moment_id,
        client_moment_id=draft.client_moment_id,
        state=draft.state,
        created_at=draft.created_at,
        persisted_at=draft.persisted_at,
    )


def _validate_draft_owner(
    draft: MomentDraftDTO,
    *,
    moment_id: str,
    author_user_id: str,
    require_draft: bool,
) -> None:
    if (
        draft.moment_id != moment_id
        or draft.author_user_id != author_user_id
    ):
        from .http_record_store import ChatRecordStoreProtocolError

        raise ChatRecordStoreProtocolError(operation="get_moment_draft")
    if require_draft and draft.state != "draft":
        raise _moment_unavailable()
    if not require_draft and draft.state not in {"draft", "published"}:
        raise _moment_unavailable()


def _asset_read(asset: MomentAssetDTO) -> ChatAssetRead:
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


def _reference_read(reference: ChatAssetReferenceDTO) -> ChatAssetReferenceRead:
    return ChatAssetReferenceRead(
        asset_id=reference.asset_id,
        client_asset_id=reference.client_asset_id,
        kind=reference.kind,
        filename=reference.filename,
        media_type=reference.media_type,
        size_bytes=reference.size_bytes,
        sha256_hex=reference.sha256_hex,
        version=reference.version,
        ordinal=reference.ordinal,
    )


def _profile_bundles(db: Session, user_ids: set[str]):
    parsed: list[int] = []
    try:
        parsed = sorted({int(value) for value in user_ids})
    except (TypeError, ValueError):
        raise _moment_unavailable() from None
    if any(value <= 0 for value in parsed):
        raise _moment_unavailable()
    with without_org_data_isolation():
        return identity_repository.get_active_profile_bundles(
            db,
            user_ids=parsed,
        )


def _organization_reads(
    db: Session,
    *,
    org_ids: tuple[str, ...],
) -> list[MomentAudienceOrganizationRead]:
    with without_org_data_isolation():
        names = moment_repository.get_active_organization_names(
            db,
            org_ids=set(org_ids),
        )
    return [
        MomentAudienceOrganizationRead(
            org_id=org_id,
            org_name=names.get(org_id, "Unavailable organization"),
        )
        for org_id in org_ids
    ]


def _moment_read(
    db: Session,
    moment: MomentDTO,
    *,
    profile_bundles: dict[int, object] | None = None,
) -> MomentRead:
    if moment.state != "published" or moment.published_at is None:
        raise _moment_unavailable()
    try:
        author_id = int(moment.author_user_id)
    except (TypeError, ValueError):
        raise _moment_unavailable() from None
    bundles = profile_bundles or _profile_bundles(db, {moment.author_user_id})
    author_bundle = bundles.get(author_id)
    if author_bundle is None:
        raise _moment_unavailable()
    return MomentRead(
        moment_id=moment.moment_id,
        client_moment_id=moment.client_moment_id,
        author=profile_summary_from_bundle(author_bundle),  # type: ignore[arg-type]
        author_org_id=moment.author_org_id,
        visibility=moment.visibility,
        audience_organizations=_organization_reads(
            db,
            org_ids=moment.audience_org_ids,
        ),
        content=moment.content,
        state="published",
        created_at=moment.created_at,
        published_at=moment.published_at,
        assets=[_reference_read(item) for item in moment.assets],
        like_count=moment.like_count,
        comment_count=moment.comment_count,
        viewer_has_liked=moment.viewer_has_liked,
    )


def _validate_asset_reference(
    asset: MomentAssetDTO,
    reference: ChatAssetReferenceDTO,
    *,
    moment: MomentDTO,
) -> None:
    if (
        asset.status != "active"
        or asset.asset_id != reference.asset_id
        or asset.client_asset_id != reference.client_asset_id
        or asset.owner_user_id != moment.author_user_id
        or asset.moment_id != moment.moment_id
        or asset.kind != "image"
        or reference.kind != "image"
        or asset.filename != reference.filename
        or asset.media_type != reference.media_type
        or asset.size_bytes != reference.size_bytes
        or asset.sha256_hex != reference.sha256_hex
        or asset.version != reference.version
    ):
        raise _asset_unavailable()


async def create_moment_draft(
    db: Session,
    *,
    actor: User,
    payload: MomentDraftCreateRequest,
    store: MomentStore,
) -> MomentDraftRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    draft = await store.reserve_moment(
        MomentDraftReserveDTO(
            client_moment_id=payload.client_moment_id,
            author_user_id=context.viewer_user_id,
        )
    )
    if (
        draft.client_moment_id != payload.client_moment_id
        or draft.author_user_id != context.viewer_user_id
    ):
        from .http_record_store import ChatRecordStoreProtocolError

        raise ChatRecordStoreProtocolError(operation="reserve_moment")
    return _draft_read(draft)


async def create_moment_asset_upload_intent(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    payload: MomentAssetUploadIntentRequest,
    store: MomentStore,
    asset_store: MomentAssetStore,
) -> MomentAssetUploadIntentRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    draft = await store.get_moment_draft(
        moment_id=moment_id,
        author_user_id=context.viewer_user_id,
    )
    _validate_draft_owner(
        draft,
        moment_id=moment_id,
        author_user_id=context.viewer_user_id,
        require_draft=True,
    )
    result = await asset_store.create_moment_upload_intent(
        MomentAssetUploadMetadataDTO(
            client_asset_id=payload.client_asset_id,
            owner_user_id=context.viewer_user_id,
            moment_id=moment_id,
            filename=payload.filename,
            media_type=payload.media_type,
            size_bytes=payload.size_bytes,
            sha256_hex=payload.sha256_hex,
            requested_at=datetime.now(UTC),
        )
    )
    if (
        result.asset.owner_user_id != context.viewer_user_id
        or result.asset.moment_id != moment_id
        or result.asset.client_asset_id != payload.client_asset_id
        or result.asset.kind != "image"
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

        raise ChatAssetStoreProtocolError(
            operation="create_moment_upload_intent"
        )
    return MomentAssetUploadIntentRead(
        asset=_asset_read(result.asset),
        upload_locator=(
            None
            if result.opaque_ticket is None
            else f"/api/backend/c19-assets/u/{result.opaque_ticket}"
        ),
        expires_at=result.expires_at,
        moment_id=moment_id,
    )


async def get_moment_asset_status(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    asset_id: str,
    store: MomentStore,
    asset_store: MomentAssetStore,
) -> ChatAssetRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    draft = await store.get_moment_draft(
        moment_id=moment_id,
        author_user_id=context.viewer_user_id,
    )
    _validate_draft_owner(
        draft,
        moment_id=moment_id,
        author_user_id=context.viewer_user_id,
        require_draft=True,
    )
    asset = await asset_store.get_moment_asset(
        MomentAssetLookupDTO(
            asset_id=asset_id,
            owner_user_id=context.viewer_user_id,
            moment_id=moment_id,
        )
    )
    return _asset_read(asset)


async def finalize_moment_asset_upload(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    asset_id: str,
    store: MomentStore,
    asset_store: MomentAssetStore,
) -> ChatAssetRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    draft = await store.get_moment_draft(
        moment_id=moment_id,
        author_user_id=context.viewer_user_id,
    )
    _validate_draft_owner(
        draft,
        moment_id=moment_id,
        author_user_id=context.viewer_user_id,
        require_draft=True,
    )
    asset = await asset_store.finalize_moment_upload(
        MomentAssetFinalizeDTO(
            asset_id=asset_id,
            owner_user_id=context.viewer_user_id,
            moment_id=moment_id,
        )
    )
    return _asset_read(asset)


async def publish_moment(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    payload: MomentPublishRequest,
    store: MomentStore,
    asset_store: MomentAssetStore,
    audit: AuditContext | None = None,
) -> MomentRead:
    user_id = actor_user_id(actor)
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    draft = await store.get_moment_draft(
        moment_id=moment_id,
        author_user_id=str(user_id),
    )
    _validate_draft_owner(
        draft,
        moment_id=moment_id,
        author_user_id=str(user_id),
        require_draft=False,
    )

    # If Record committed but Barong lost the response or failed during Asset
    # commit, replay the immutable record and repair each binding.  Recomputing
    # a public/friend audience here would make relationship changes turn a safe
    # retry into a conflict or, worse, a broadened snapshot.
    if draft.state == "published":
        published = await store.get_moment(
            MomentQueryDTO(context=context, moment_id=moment_id)
        )
        if (
            published.author_user_id != str(user_id)
            or published.client_moment_id != draft.client_moment_id
            or published.visibility != payload.visibility
            or published.content != payload.content
            or [item.asset_id for item in published.assets] != payload.asset_ids
        ):
            raise _idempotency_conflict()
        for reference in published.assets:
            committed = await asset_store.commit_moment_binding(
                MomentAssetBindingCommitDTO(
                    asset_id=reference.asset_id,
                    owner_user_id=str(user_id),
                    moment_id=moment_id,
                    client_moment_id=draft.client_moment_id,
                )
            )
            _validate_asset_reference(
                committed.asset,
                reference,
                moment=published,
            )
        result = _moment_read(db, published)
        _write_audit(
            db,
            actor_id=user_id,
            action="c19.moment.publish",
            target_type="c19_moment",
            target_id=moment_id,
            audit=audit,
            details={
                "visibility": published.visibility,
                "asset_count": len(published.assets),
                "audience_org_count": len(published.audience_org_ids),
                "recovered": True,
            },
            deduplicate=True,
        )
        return result

    audience = resolve_publish_audience(
        db,
        actor=actor,
        visibility=payload.visibility,
        audience_affiliation_ids=payload.audience_affiliation_ids,
    )
    db.rollback()

    references: list[ChatAssetReferenceDTO] = []
    for ordinal, asset_id in enumerate(payload.asset_ids):
        prepared = await asset_store.prepare_moment_binding(
            MomentAssetBindingPrepareDTO(
                asset_id=asset_id,
                owner_user_id=str(user_id),
                moment_id=moment_id,
                client_moment_id=draft.client_moment_id,
            )
        )
        asset = prepared.asset
        if asset.status != "active" or asset.kind != "image":
            raise _asset_unavailable()
        references.append(
            ChatAssetReferenceDTO(
                asset_id=asset.asset_id,
                client_asset_id=asset.client_asset_id,
                kind="image",
                filename=asset.filename,
                media_type=asset.media_type,
                size_bytes=asset.size_bytes,
                sha256_hex=asset.sha256_hex,
                version=asset.version,
                ordinal=ordinal,
            )
        )

    published = await store.publish_moment(
        MomentPublishDTO(
            moment_id=moment_id,
            client_moment_id=draft.client_moment_id,
            author_user_id=str(user_id),
            author_org_id=audience.author_org_id,
            visibility=payload.visibility,
            audience_user_ids=audience.audience_user_ids,
            audience_org_ids=audience.audience_org_ids,
            content=payload.content,
            assets=tuple(references),
        )
    )
    for reference in references:
        committed = await asset_store.commit_moment_binding(
            MomentAssetBindingCommitDTO(
                asset_id=reference.asset_id,
                owner_user_id=str(user_id),
                moment_id=moment_id,
                client_moment_id=draft.client_moment_id,
            )
        )
        _validate_asset_reference(committed.asset, reference, moment=published)

    result = _moment_read(db, published)
    _write_audit(
        db,
        actor_id=user_id,
        action="c19.moment.publish",
        target_type="c19_moment",
        target_id=moment_id,
        audit=audit,
        details={
            "visibility": payload.visibility,
            "asset_count": len(references),
            "audience_org_count": len(audience.audience_org_ids),
        },
        deduplicate=True,
    )
    return result


async def get_moment(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    store: MomentStore,
) -> MomentRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    moment = await store.get_moment(
        MomentQueryDTO(context=context, moment_id=moment_id)
    )
    return _moment_read(db, moment)


async def list_moment_feed(
    db: Session,
    *,
    actor: User,
    limit: int,
    cursor: str | None,
    store: MomentStore,
) -> MomentFeedPageRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    page = await store.list_moment_feed(
        MomentFeedQueryDTO(context=context, limit=limit, cursor=cursor)
    )
    bundles = _profile_bundles(
        db,
        {moment.author_user_id for moment in page.moments},
    )
    moments: list[MomentRead] = []
    for moment in page.moments:
        try:
            moments.append(_moment_read(db, moment, profile_bundles=bundles))
        except C19MomentAccessError:
            # Current identity state changed after the authorization snapshot;
            # omission tightens the result and the opaque cursor still advances.
            continue
    return MomentFeedPageRead(
        moments=moments,
        next_cursor=page.next_cursor,
        latest_event_sequence=page.latest_event_sequence,
    )


async def set_moment_like(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    liked: bool,
    store: MomentStore,
    audit: AuditContext | None = None,
) -> MomentLikeMutationRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    result = await store.set_moment_like(
        MomentLikeCommandDTO(
            context=context,
            moment_id=moment_id,
            liked=liked,
            occurred_at=datetime.now(UTC),
        )
    )
    if result.user_id != context.viewer_user_id or result.liked != liked:
        from .http_record_store import ChatRecordStoreProtocolError

        raise ChatRecordStoreProtocolError(operation="set_moment_like")
    if result.changed:
        _write_audit(
            db,
            actor_id=int(context.viewer_user_id),
            action="c19.moment.like" if liked else "c19.moment.unlike",
            target_type="c19_moment",
            target_id=moment_id,
            audit=audit,
            details={"like_count": result.like_count},
        )
    return MomentLikeMutationRead(
        moment_id=result.moment_id,
        liked=result.liked,
        changed=result.changed,
        like_count=result.like_count,
        updated_at=result.updated_at,
    )


def _like_read(like: MomentLikeDTO, bundles: dict[int, object]) -> MomentLikeRead:
    try:
        bundle = bundles[int(like.user_id)]
    except (KeyError, TypeError, ValueError):
        raise _moment_unavailable() from None
    return MomentLikeRead(
        profile=profile_summary_from_bundle(bundle),  # type: ignore[arg-type]
        sequence=like.sequence,
        created_at=like.created_at,
    )


async def list_moment_likes(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    limit: int,
    cursor: str | None,
    store: MomentStore,
) -> MomentLikePageRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    page = await store.list_moment_likes(
        MomentLikeQueryDTO(
            context=context,
            moment_id=moment_id,
            limit=limit,
            cursor=cursor,
        )
    )
    bundles = _profile_bundles(db, {like.user_id for like in page.likes})
    likes: list[MomentLikeRead] = []
    for like in page.likes:
        try:
            likes.append(_like_read(like, bundles))
        except C19MomentAccessError:
            continue
    return MomentLikePageRead(likes=likes, next_cursor=page.next_cursor)


def _comment_read(
    comment: MomentCommentDTO,
    bundles: dict[int, object],
) -> MomentCommentRead:
    if comment.state != "active":
        raise _moment_unavailable()
    try:
        bundle = bundles[int(comment.author_user_id)]
    except (KeyError, TypeError, ValueError):
        raise _moment_unavailable() from None
    return MomentCommentRead(
        comment_id=comment.comment_id,
        client_comment_id=comment.client_comment_id,
        moment_id=comment.moment_id,
        author=profile_summary_from_bundle(bundle),  # type: ignore[arg-type]
        content=comment.content,
        state="active",
        sequence=comment.sequence,
        created_at=comment.created_at,
        persisted_at=comment.persisted_at,
    )


async def create_moment_comment(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    payload: MomentCommentCreateRequest,
    store: MomentStore,
    audit: AuditContext | None = None,
) -> MomentCommentRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    comment = await store.create_moment_comment(
        MomentCommentCreateDTO(
            context=context,
            moment_id=moment_id,
            client_comment_id=payload.client_comment_id,
            author_user_id=context.viewer_user_id,
            content=payload.content,
        )
    )
    bundles = _profile_bundles(db, {comment.author_user_id})
    result = _comment_read(comment, bundles)
    _write_audit(
        db,
        actor_id=int(context.viewer_user_id),
        action="c19.moment.comment.create",
        target_type="c19_moment_comment",
        target_id=comment.comment_id,
        audit=audit,
        details={"moment_id": moment_id, "sequence": comment.sequence},
        deduplicate=True,
    )
    return result


async def list_moment_comments(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    limit: int,
    cursor: str | None,
    store: MomentStore,
) -> MomentCommentPageRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    page = await store.list_moment_comments(
        MomentCommentQueryDTO(
            context=context,
            moment_id=moment_id,
            limit=limit,
            cursor=cursor,
        )
    )
    bundles = _profile_bundles(
        db,
        {comment.author_user_id for comment in page.comments},
    )
    comments: list[MomentCommentRead] = []
    for comment in page.comments:
        try:
            comments.append(_comment_read(comment, bundles))
        except C19MomentAccessError:
            continue
    return MomentCommentPageRead(
        comments=comments,
        next_cursor=page.next_cursor,
    )


async def delete_moment_comment(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    comment_id: str,
    store: MomentStore,
    audit: AuditContext | None = None,
) -> MomentCommentDeleteRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    result = await store.delete_moment_comment(
        MomentCommentDeleteDTO(
            context=context,
            moment_id=moment_id,
            comment_id=comment_id,
            requested_by_user_id=context.viewer_user_id,
            requested_at=datetime.now(UTC),
        )
    )
    _write_audit(
        db,
        actor_id=int(context.viewer_user_id),
        action="c19.moment.comment.delete",
        target_type="c19_moment_comment",
        target_id=comment_id,
        audit=audit,
        details={
            "moment_id": moment_id,
            "comment_count": result.comment_count,
        },
        deduplicate=True,
    )
    return MomentCommentDeleteRead(
        moment_id=result.moment_id,
        comment_id=result.comment_id,
        state="deleted",
        changed=result.changed,
        comment_count=result.comment_count,
        deleted_at=result.deleted_at,
    )


async def delete_moment(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    store: MomentStore,
    asset_store: MomentAssetStore,
    audit: AuditContext | None = None,
) -> MomentDeleteRead:
    user_id = actor_user_id(actor)
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    lifecycle = await store.get_moment_draft(
        moment_id=moment_id,
        author_user_id=str(user_id),
    )
    if (
        lifecycle.moment_id != moment_id
        or lifecycle.author_user_id != str(user_id)
        or lifecycle.state == "draft"
    ):
        raise _moment_unavailable()
    command = MomentDeleteCommandDTO(
        context=context,
        moment_id=moment_id,
        requested_by_user_id=str(user_id),
        requested_at=datetime.now(UTC),
    )
    pending = await store.begin_moment_delete(command)
    for reference in pending.assets:
        await asset_store.delete_asset(
            ChatAssetDeleteCommandDTO(
                asset_id=reference.asset_id,
                requested_by_user_id=str(user_id),
                reason="C19 Moment deleted by its author",
                requested_at=command.requested_at,
            )
        )
    completed = await store.complete_moment_delete(command)
    if completed.state != "deleted":
        from .http_record_store import ChatRecordStoreProtocolError

        raise ChatRecordStoreProtocolError(operation="complete_moment_delete")
    _write_audit(
        db,
        actor_id=user_id,
        action="c19.moment.delete",
        target_type="c19_moment",
        target_id=moment_id,
        audit=audit,
        details={"asset_count": len(pending.assets)},
        deduplicate=True,
    )
    return MomentDeleteRead(moment_id=moment_id, state="deleted")


def _find_moment_asset(
    moment: MomentDTO,
    *,
    asset_id: str,
) -> ChatAssetReferenceDTO:
    matches = tuple(item for item in moment.assets if item.asset_id == asset_id)
    if len(matches) != 1:
        raise _asset_unavailable()
    return matches[0]


async def create_moment_asset_access_intent(
    db: Session,
    *,
    actor: User,
    moment_id: str,
    asset_id: str,
    payload: MomentAssetAccessIntentRequest,
    store: MomentStore,
    asset_store: MomentAssetStore,
) -> MomentAssetAccessIntentRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    moment = await store.get_moment(
        MomentQueryDTO(context=context, moment_id=moment_id)
    )
    reference = _find_moment_asset(moment, asset_id=asset_id)
    asset = await asset_store.get_moment_asset(
        MomentAssetLookupDTO(
            asset_id=asset_id,
            owner_user_id=moment.author_user_id,
            moment_id=moment_id,
        )
    )
    _validate_asset_reference(asset, reference, moment=moment)

    from .http_asset_store import ChatAssetStoreConflictError

    try:
        committed = await asset_store.commit_moment_binding(
            MomentAssetBindingCommitDTO(
                asset_id=asset_id,
                owner_user_id=moment.author_user_id,
                moment_id=moment_id,
                client_moment_id=moment.client_moment_id,
            )
        )
    except ChatAssetStoreConflictError:
        raise _asset_unavailable() from None
    _validate_asset_reference(committed.asset, reference, moment=moment)
    disposition = "inline" if payload.variant == "thumbnail" else "attachment"
    intent = await asset_store.create_moment_download_intent(
        MomentAssetDownloadRequestDTO(
            asset_id=asset_id,
            owner_user_id=moment.author_user_id,
            reader_user_id=context.viewer_user_id,
            moment_id=moment_id,
            variant=payload.variant,
            disposition=disposition,
            asset_version=reference.version,
        )
    )
    if intent.expires_at <= datetime.now(UTC):
        from .http_asset_store import ChatAssetStoreProtocolError

        raise ChatAssetStoreProtocolError(
            operation="create_moment_download_intent"
        )
    return MomentAssetAccessIntentRead(
        download_locator=f"/api/backend/c19-assets/d/{intent.opaque_ticket}",
        expires_at=intent.expires_at,
    )


def _event_read(event) -> MomentEventRead:
    return MomentEventRead(
        event_id=event.event_id,
        event_sequence=event.event_sequence,
        event_type=event.event_type,
        moment_id=event.moment_id,
        actor_user_id=event.actor_user_id,
        comment_id=event.comment_id,
        created_at=event.created_at,
    )


async def list_moment_events(
    db: Session,
    *,
    actor: User,
    limit: int,
    cursor: str | None,
    store: MomentStore,
) -> MomentEventPageRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    page = await store.list_moment_events(
        MomentUserEventQueryDTO(context=context, limit=limit, cursor=cursor)
    )
    return MomentEventPageRead(
        events=[_event_read(event) for event in page.events],
        next_cursor=page.next_cursor,
        latest_event_sequence=page.latest_event_sequence,
    )


async def get_moment_event_tail(
    db: Session,
    *,
    actor: User,
    store: MomentStore,
) -> MomentEventTailRead:
    context = build_viewer_context(db, actor=actor)
    db.rollback()
    tail = await store.get_moment_event_tail(context)
    if tail.user_id != context.viewer_user_id:
        from .http_record_store import ChatRecordStoreProtocolError

        raise ChatRecordStoreProtocolError(operation="get_moment_event_tail")
    return MomentEventTailRead(
        cursor=tail.cursor,
        latest_event_sequence=tail.latest_event_sequence,
    )


__all__ = [
    "C19MomentAccessError",
    "C19MomentPolicyError",
    "create_moment_asset_access_intent",
    "create_moment_asset_upload_intent",
    "create_moment_comment",
    "create_moment_draft",
    "delete_moment",
    "delete_moment_comment",
    "finalize_moment_asset_upload",
    "get_moment",
    "get_moment_asset_status",
    "get_moment_event_tail",
    "list_moment_comments",
    "list_moment_events",
    "list_moment_feed",
    "list_moment_likes",
    "publish_moment",
    "set_moment_like",
]
