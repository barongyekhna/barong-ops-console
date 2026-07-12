"""Transactional Stage 5 Moment persistence and visibility enforcement.

No function in this module logs or persists Moment/comment text outside the
content tables.  Barong supplies current social-policy facts; the immutable
publish-time audience remains an additional, fail-closed ceiling here.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .cursors import CursorCodec
from .models import (
    Moment,
    MomentAssetReference as MomentAssetReferenceModel,
    RecordAssetDeletionOutbox,
    MomentAudienceSnapshot,
    MomentComment,
    MomentFeedSequence,
    MomentLike,
    MomentUserEvent,
    UserEventSequence,
)
from .repository import _lock_asset_coordination
from .moment_schemas import (
    MomentAssetReference,
    MomentCommentCreateRequest,
    MomentCommentDeleteRequest,
    MomentCommentDeleteResponse,
    MomentCommentPageResponse,
    MomentCommentRead,
    MomentContextQuery,
    MomentDeleteCompleteRequest,
    MomentDeleteRequest,
    MomentDeleteResponse,
    MomentDraftCreateRequest,
    MomentDraftQueryRequest,
    MomentDraftResponse,
    MomentEventPageResponse,
    MomentEventQuery,
    MomentEventRead,
    MomentEventTailResponse,
    MomentFeedQuery,
    MomentInteractionPageQuery,
    MomentLikeMutationRequest,
    MomentLikePageResponse,
    MomentLikeRead,
    MomentLikeResponse,
    MomentPageResponse,
    MomentPublishRequest,
    MomentRead,
    MomentViewerContext,
)
from .repository import _dialect_insert, _next_sequence, utcnow


class MomentStoreError(RuntimeError):
    pass


class MomentNotFoundError(MomentStoreError):
    """Uniform missing/invisible/wrong-owner result."""


class MomentConflictError(MomentStoreError):
    pass


class MomentGoneError(MomentStoreError):
    pass


_POLICY_SCAN_BATCH = 200
_POLICY_SCAN_LIMIT = 2_000


@dataclass(frozen=True, slots=True)
class MomentMutationResult:
    value: MomentRead | MomentCommentRead
    replayed: bool


def _new_moment_id() -> str:
    return f"mom_{uuid.uuid4().hex}"


def _new_comment_id() -> str:
    return f"cmt_{uuid.uuid4().hex}"


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def relationship_context_sha256(context: MomentViewerContext) -> str:
    """Bind every cursor to the exact current-policy facts used to mint it."""

    return _canonical_hash(
        {
            "active_org_ids": sorted(context.active_org_ids),
            "active_user_ids": sorted(context.active_user_ids),
            "blocked_user_ids": sorted(context.blocked_user_ids),
            "friend_user_ids": sorted(context.friend_user_ids),
            "viewer_user_id": context.viewer_user_id,
        }
    )


def _cursor_scope(
    kind: str,
    context: MomentViewerContext,
    *,
    moment_id: str | None = None,
) -> str:
    resource = f":{moment_id}" if moment_id is not None else ""
    return (
        f"{kind}:{context.viewer_user_id}{resource}:"
        f"{relationship_context_sha256(context)}"
    )


def _next_feed_sequence(session: Session, *, now: datetime) -> int:
    insert_statement = _dialect_insert(session, MomentFeedSequence)
    table = MomentFeedSequence.__table__
    if insert_statement is not None:
        statement = (
            insert_statement.values(
                singleton_key="primary", last_sequence=1, updated_at=now
            )
            .on_conflict_do_update(
                index_elements=[table.c.singleton_key],
                set_={
                    "last_sequence": table.c.last_sequence + 1,
                    "updated_at": now,
                },
            )
            .returning(table.c.last_sequence)
        )
        return int(session.execute(statement).scalar_one())

    row = session.execute(
        select(MomentFeedSequence)
        .where(MomentFeedSequence.singleton_key == "primary")
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = MomentFeedSequence(
            singleton_key="primary", last_sequence=1, updated_at=now
        )
        session.add(row)
        session.flush()
        return 1
    row.last_sequence += 1
    row.updated_at = now
    session.flush()
    return row.last_sequence


def _asset_response(row: MomentAssetReferenceModel) -> MomentAssetReference:
    return MomentAssetReference(
        asset_id=row.asset_id,
        client_asset_id=row.client_asset_id,
        kind="image",
        filename=row.filename,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        sha256_hex=row.sha256_hex,
        version=row.version,
        ordinal=row.ordinal,
    )


def _assets_for_moment(
    session: Session, moment_id: str
) -> list[MomentAssetReference]:
    return [
        _asset_response(row)
        for row in session.scalars(
            select(MomentAssetReferenceModel)
            .where(MomentAssetReferenceModel.moment_id == moment_id)
            .order_by(MomentAssetReferenceModel.ordinal)
        )
    ]


def _has_audience_snapshot(
    session: Session, *, moment_id: str, user_id: str
) -> bool:
    return (
        session.get(MomentAudienceSnapshot, (moment_id, user_id)) is not None
    )


def _is_current_policy_visible(
    session: Session,
    moment: Moment,
    context: MomentViewerContext,
) -> bool:
    viewer = context.viewer_user_id
    active_users = set(context.active_user_ids)
    if (
        viewer not in active_users
        or moment.author_user_id not in active_users
        or not _has_audience_snapshot(
            session, moment_id=moment.id, user_id=viewer
        )
    ):
        return False
    if viewer == moment.author_user_id:
        return True
    if moment.author_user_id in context.blocked_user_ids:
        return False
    if moment.visibility == "public":
        return True
    if moment.visibility == "private":
        return False
    if moment.visibility == "friends":
        return moment.author_user_id in context.friend_user_ids
    return bool(set(moment.audience_org_ids) & set(context.active_org_ids))


def _is_visible(
    session: Session,
    moment: Moment,
    context: MomentViewerContext,
) -> bool:
    return moment.state == "published" and _is_current_policy_visible(
        session, moment, context
    )


def _locked_moment(session: Session, moment_id: str) -> Moment | None:
    return session.execute(
        select(Moment).where(Moment.id == moment_id).with_for_update()
    ).scalar_one_or_none()


def _require_visible_moment(
    session: Session,
    *,
    moment_id: str,
    context: MomentViewerContext,
    for_update: bool = False,
) -> Moment:
    moment = (
        _locked_moment(session, moment_id)
        if for_update
        else session.get(Moment, moment_id)
    )
    if moment is None or not _is_visible(session, moment, context):
        raise MomentNotFoundError("Moment not found")
    return moment


def _visible_like_count(
    session: Session, moment_id: str, context: MomentViewerContext
) -> int:
    allowed = set(context.active_user_ids) - set(context.blocked_user_ids)
    if not allowed:
        return 0
    return int(
        session.scalar(
            select(func.count())
            .select_from(MomentLike)
            .where(
                MomentLike.moment_id == moment_id,
                MomentLike.status == "active",
                MomentLike.user_id.in_(allowed),
            )
        )
        or 0
    )


def _visible_comment_count(
    session: Session, moment_id: str, context: MomentViewerContext
) -> int:
    allowed = set(context.active_user_ids) - set(context.blocked_user_ids)
    if not allowed:
        return 0
    return int(
        session.scalar(
            select(func.count())
            .select_from(MomentComment)
            .where(
                MomentComment.moment_id == moment_id,
                MomentComment.status == "active",
                MomentComment.author_user_id.in_(allowed),
            )
        )
        or 0
    )


def _moment_response(
    session: Session,
    moment: Moment,
    context: MomentViewerContext,
) -> MomentRead:
    if moment.published_at is None or moment.content is None:
        raise MomentStoreError("published Moment is incomplete")
    viewer_like = session.get(MomentLike, (moment.id, context.viewer_user_id))
    return MomentRead(
        moment_id=moment.id,
        client_moment_id=moment.client_moment_id,
        author_user_id=moment.author_user_id,
        author_org_id=moment.author_org_id,
        visibility=moment.visibility,
        audience_org_ids=list(moment.audience_org_ids),
        content=moment.content,
        state="published",
        created_at=moment.created_at,
        published_at=moment.published_at,
        assets=_assets_for_moment(session, moment.id),
        like_count=_visible_like_count(session, moment.id, context),
        comment_count=_visible_comment_count(session, moment.id, context),
        viewer_has_liked=(
            viewer_like is not None and viewer_like.status == "active"
        ),
    )


def _draft_response(moment: Moment) -> MomentDraftResponse:
    return MomentDraftResponse(
        moment_id=moment.id,
        client_moment_id=moment.client_moment_id,
        author_user_id=moment.author_user_id,
        state=moment.state,
        created_at=moment.created_at,
        persisted_at=moment.persisted_at,
    )


def _emit_events(
    session: Session,
    *,
    recipient_user_ids: set[str] | list[str],
    event_type: str,
    moment_id: str,
    actor_user_id: str,
    comment_id: str | None,
    created_at: datetime,
) -> None:
    for user_id in sorted(set(recipient_user_ids)):
        sequence = _next_sequence(
            session,
            model=UserEventSequence,
            key_name="user_id",
            key_value=user_id,
            now=created_at,
        )
        session.add(
            MomentUserEvent(
                id=str(uuid.uuid4()),
                user_id=user_id,
                event_sequence=sequence,
                event_type=event_type,
                moment_id=moment_id,
                actor_user_id=actor_user_id,
                comment_id=comment_id,
                created_at=created_at,
            )
        )


def reserve_moment_draft(
    session: Session, request: MomentDraftCreateRequest
) -> MomentDraftResponse:
    existing = session.execute(
        select(Moment)
        .where(
            Moment.author_user_id == request.author_user_id,
            Moment.client_moment_id == request.client_moment_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        if existing.state in {"delete_pending", "deleted"}:
            raise MomentGoneError("Moment idempotency key was deleted")
        return _draft_response(existing)
    now = utcnow()
    candidate = Moment(
        id=_new_moment_id(),
        client_moment_id=request.client_moment_id,
        author_user_id=request.author_user_id,
        author_org_id=None,
        state="draft",
        visibility="private",
        audience_org_ids=[],
        content=None,
        feed_sequence=None,
        like_count=0,
        comment_count=0,
        last_like_sequence=0,
        last_comment_sequence=0,
        publish_intent_sha256=None,
        publish_intent_version=1,
        created_at=now,
        persisted_at=now,
        updated_at=now,
        published_at=None,
        delete_pending_at=None,
        deleted_at=None,
    )
    try:
        session.add(candidate)
        session.commit()
        return _draft_response(candidate)
    except IntegrityError:
        session.rollback()
        existing = session.execute(
            select(Moment)
            .where(
                Moment.author_user_id == request.author_user_id,
                Moment.client_moment_id == request.client_moment_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if existing is None:
            raise MomentStoreError("Moment draft reservation failed") from None
        if existing.state in {"delete_pending", "deleted"}:
            raise MomentGoneError("Moment idempotency key was deleted") from None
        return _draft_response(existing)


def get_moment_draft(
    session: Session,
    *,
    moment_id: str,
    request: MomentDraftQueryRequest,
) -> MomentDraftResponse:
    """Owner lifecycle lookup supporting cross-store crash recovery.

    Barong applies the operation-specific state gate.  Returning pending/deleted
    tombstones lets an interrupted Asset cleanup resume without making content
    visible or weakening owner matching.
    """

    moment = session.get(Moment, moment_id)
    if (
        moment is None
        or moment.author_user_id != request.author_user_id
    ):
        raise MomentNotFoundError("Moment draft not found")
    return _draft_response(moment)


def _publish_intent(request: MomentPublishRequest) -> str:
    return _canonical_hash(
        {
            "assets": [asset.model_dump(mode="json") for asset in request.assets],
            "audience_org_ids": sorted(request.audience_org_ids),
            "audience_user_ids": sorted(request.audience_user_ids),
            "author_org_id": request.author_org_id,
            "author_user_id": request.author_user_id,
            "content": request.content,
            "intent_version": 1,
            "visibility": request.visibility,
        }
    )


def publish_moment(
    session: Session,
    *,
    moment_id: str,
    request: MomentPublishRequest,
) -> MomentMutationResult:
    moment = _locked_moment(session, moment_id)
    if moment is None or moment.author_user_id != request.author_user_id:
        raise MomentNotFoundError("Moment not found")
    if moment.state in {"delete_pending", "deleted"}:
        raise MomentGoneError("Moment was deleted")
    intent_sha256 = _publish_intent(request)
    author_context = MomentViewerContext(
        viewer_user_id=request.author_user_id,
        active_user_ids=list(request.audience_user_ids),
        active_org_ids=list(request.audience_org_ids),
        friend_user_ids=[],
        blocked_user_ids=[],
    )
    if moment.state == "published":
        if moment.publish_intent_sha256 != intent_sha256:
            raise MomentConflictError("Moment publish idempotency conflict")
        return MomentMutationResult(
            _moment_response(session, moment, author_context), True
        )
    if request.assets:
        _lock_asset_coordination(
            session,
            [asset.asset_id for asset in request.assets],
            now=utcnow(),
        )
        retired_asset = session.scalar(
            select(RecordAssetDeletionOutbox.asset_id)
            .where(
                RecordAssetDeletionOutbox.asset_id.in_(
                    [asset.asset_id for asset in request.assets]
                )
            )
            .limit(1)
        )
        if retired_asset is not None:
            raise MomentConflictError("Moment asset is governed by retention")

    now = utcnow()
    moment.author_org_id = request.author_org_id
    moment.state = "published"
    moment.visibility = request.visibility
    moment.audience_org_ids = sorted(request.audience_org_ids)
    moment.content = request.content
    moment.feed_sequence = _next_feed_sequence(session, now=now)
    moment.publish_intent_sha256 = intent_sha256
    moment.updated_at = now
    # Publication time belongs to the authority and is intentionally absent
    # from the retry payload/hash.  A lost response can therefore replay the
    # exact business intent without manufacturing a new timestamp conflict.
    moment.published_at = now
    session.add(moment)
    for user_id in sorted(request.audience_user_ids):
        session.add(
            MomentAudienceSnapshot(
                moment_id=moment.id,
                user_id=user_id,
                created_at=now,
            )
        )
    for asset in request.assets:
        session.add(
            MomentAssetReferenceModel(
                id=str(uuid.uuid4()),
                moment_id=moment.id,
                asset_id=asset.asset_id,
                client_asset_id=asset.client_asset_id,
                kind="image",
                filename=asset.filename,
                media_type=asset.media_type,
                size_bytes=asset.size_bytes,
                sha256_hex=asset.sha256_hex,
                version=asset.version,
                ordinal=asset.ordinal,
            )
        )
    _emit_events(
        session,
        recipient_user_ids=set(request.audience_user_ids),
        event_type="moment_published",
        moment_id=moment.id,
        actor_user_id=request.author_user_id,
        comment_id=None,
        created_at=now,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.get(Moment, moment_id)
        if (
            existing is not None
            and existing.state == "published"
            and existing.publish_intent_sha256 == intent_sha256
        ):
            return MomentMutationResult(
                _moment_response(session, existing, author_context), True
            )
        raise MomentConflictError("Moment publish conflict") from exc
    return MomentMutationResult(
        _moment_response(session, moment, author_context), False
    )


def get_moment(
    session: Session,
    *,
    moment_id: str,
    request: MomentContextQuery,
) -> MomentRead:
    moment = _require_visible_moment(
        session, moment_id=moment_id, context=request.context
    )
    return _moment_response(session, moment, request.context)


def list_moment_feed(
    session: Session,
    request: MomentFeedQuery,
    *,
    codec: CursorCodec,
) -> MomentPageResponse:
    context = request.context
    scope = _cursor_scope("feed", context)
    position = (
        codec.decode(
            request.cursor, kinds=("moment_feed",), scope=scope
        ).position
        if request.cursor
        else None
    )
    visible: list[Moment] = []
    scan_position = position
    scanned = 0
    exhausted = False
    while len(visible) <= request.limit and scanned < _POLICY_SCAN_LIMIT:
        batch_size = min(_POLICY_SCAN_BATCH, _POLICY_SCAN_LIMIT - scanned)
        query = (
            select(Moment)
            .join(
                MomentAudienceSnapshot,
                MomentAudienceSnapshot.moment_id == Moment.id,
            )
            .where(
                MomentAudienceSnapshot.user_id == context.viewer_user_id,
                Moment.state == "published",
            )
            .order_by(Moment.feed_sequence.desc())
            .limit(batch_size)
        )
        if scan_position is not None:
            query = query.where(Moment.feed_sequence < scan_position)
        candidates = list(session.scalars(query))
        if not candidates:
            exhausted = True
            break
        scanned += len(candidates)
        scan_position = int(candidates[-1].feed_sequence or 0)
        visible.extend(
            moment
            for moment in candidates
            if _is_visible(session, moment, context)
        )
        if len(candidates) < batch_size:
            exhausted = True
            break
    page_rows = visible[: request.limit]
    next_position: int | None = None
    if len(visible) > request.limit and page_rows:
        next_position = int(page_rows[-1].feed_sequence or 0)
    elif not exhausted and scan_position is not None:
        # A bounded scan may legitimately return a short page when most
        # candidates fail current policy.  Advance past everything inspected.
        next_position = scan_position
    next_cursor = (
        codec.encode(kind="moment_feed", scope=scope, position=next_position)
        if next_position is not None
        else None
    )
    counter = session.get(UserEventSequence, context.viewer_user_id)
    return MomentPageResponse(
        moments=[_moment_response(session, row, context) for row in page_rows],
        next_cursor=next_cursor,
        latest_event_sequence=counter.last_sequence if counter else 0,
    )


def mutate_moment_like(
    session: Session,
    *,
    moment_id: str,
    request: MomentLikeMutationRequest,
    liked: bool,
) -> MomentLikeResponse:
    moment = _require_visible_moment(
        session,
        moment_id=moment_id,
        context=request.context,
        for_update=True,
    )
    now = request.occurred_at
    changed = False
    row = session.get(MomentLike, (moment_id, request.user_id))
    attempted_like_transition = liked and (row is None or row.status != "active")
    if attempted_like_transition:
        # The conditional pair write is the transition claim.  PostgreSQL also
        # holds the parent FOR UPDATE lock; the SQL claim keeps SQLite tests and
        # any future weaker-locking dialect idempotent under duplicate retries.
        sequence = session.execute(
            update(Moment)
            .where(Moment.id == moment_id, Moment.state == "published")
            .values(
                last_like_sequence=Moment.last_like_sequence + 1,
                updated_at=now,
            )
            .returning(Moment.last_like_sequence)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if sequence is None:
            session.rollback()
            raise MomentNotFoundError("Moment not found")
        if row is None:
            insert_statement = _dialect_insert(session, MomentLike)
            if insert_statement is not None:
                claimed = session.execute(
                    insert_statement.values(
                        moment_id=moment_id,
                        user_id=request.user_id,
                        status="active",
                        sequence=sequence,
                        created_at=now,
                        updated_at=now,
                        removed_at=None,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            MomentLike.__table__.c.moment_id,
                            MomentLike.__table__.c.user_id,
                        ]
                    )
                    .returning(MomentLike.__table__.c.user_id)
                ).scalar_one_or_none()
                changed = claimed is not None
            else:
                session.add(
                    MomentLike(
                        moment_id=moment_id,
                        user_id=request.user_id,
                        status="active",
                        sequence=sequence,
                        created_at=now,
                        updated_at=now,
                        removed_at=None,
                    )
                )
                session.flush()
                changed = True
        else:
            changed = (
                session.execute(
                    update(MomentLike)
                    .where(
                        MomentLike.moment_id == moment_id,
                        MomentLike.user_id == request.user_id,
                        MomentLike.status == "removed",
                    )
                    .values(
                        status="active",
                        sequence=sequence,
                        updated_at=now,
                        removed_at=None,
                    )
                    .returning(MomentLike.user_id)
                    .execution_options(synchronize_session=False)
                ).scalar_one_or_none()
                is not None
            )
    elif not liked:
        changed = (
            session.execute(
                update(MomentLike)
                .where(
                    MomentLike.moment_id == moment_id,
                    MomentLike.user_id == request.user_id,
                    MomentLike.status == "active",
                )
                .values(status="removed", updated_at=now, removed_at=now)
                .returning(MomentLike.user_id)
                .execution_options(synchronize_session=False)
            ).scalar_one_or_none()
            is not None
        )

    if attempted_like_transition and not changed:
        # A concurrent request won the same pair transition.  Roll back the
        # speculative sequence allocation so an idempotent retry changes no
        # hidden counters/timestamps and emits no event.
        session.rollback()
        moment = session.get(Moment, moment_id)
        if moment is None or not _is_visible(session, moment, request.context):
            raise MomentNotFoundError("Moment not found")
        current_like = session.get(MomentLike, (moment_id, request.user_id))
        return MomentLikeResponse(
            moment_id=moment.id,
            user_id=request.user_id,
            liked=True,
            changed=False,
            like_count=_visible_like_count(session, moment.id, request.context),
            updated_at=(
                current_like.updated_at
                if current_like is not None
                else moment.updated_at
            ),
        )

    if changed:
        session.execute(
            update(Moment)
            .where(Moment.id == moment_id, Moment.state == "published")
            .values(
                like_count=(
                    Moment.like_count + 1 if liked else Moment.like_count - 1
                ),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        _emit_events(
            session,
            recipient_user_ids={moment.author_user_id},
            event_type="moment_liked" if liked else "moment_unliked",
            moment_id=moment.id,
            actor_user_id=request.user_id,
            comment_id=None,
            created_at=now,
        )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise MomentConflictError("Moment like conflict") from exc
    session.refresh(moment)
    current_like = session.execute(
        select(MomentLike)
        .where(
            MomentLike.moment_id == moment_id,
            MomentLike.user_id == request.user_id,
        )
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    return MomentLikeResponse(
        moment_id=moment.id,
        user_id=request.user_id,
        liked=liked,
        changed=changed,
        like_count=_visible_like_count(session, moment.id, request.context),
        updated_at=current_like.updated_at if current_like is not None else moment.updated_at,
    )


def list_moment_likes(
    session: Session,
    *,
    moment_id: str,
    request: MomentInteractionPageQuery,
    codec: CursorCodec,
) -> MomentLikePageResponse:
    _require_visible_moment(
        session, moment_id=moment_id, context=request.context
    )
    scope = _cursor_scope("likes", request.context, moment_id=moment_id)
    position = (
        codec.decode(
            request.cursor, kinds=("moment_likes",), scope=scope
        ).position
        if request.cursor
        else None
    )
    allowed = set(request.context.active_user_ids) - set(
        request.context.blocked_user_ids
    )
    query = select(MomentLike).where(
        MomentLike.moment_id == moment_id,
        MomentLike.status == "active",
        MomentLike.user_id.in_(allowed),
    )
    if position is not None:
        query = query.where(MomentLike.sequence < position)
    rows = list(
        session.scalars(query.order_by(MomentLike.sequence.desc()).limit(request.limit + 1))
    )
    page_rows = rows[: request.limit]
    return MomentLikePageResponse(
        items=[
            MomentLikeRead(
                user_id=row.user_id,
                sequence=row.sequence,
                liked_at=row.updated_at,
            )
            for row in page_rows
        ],
        count=_visible_like_count(session, moment_id, request.context),
        next_cursor=(
            codec.encode(
                kind="moment_likes",
                scope=scope,
                position=page_rows[-1].sequence,
            )
            if len(rows) > request.limit and page_rows
            else None
        ),
    )


def _comment_intent(
    moment_id: str, request: MomentCommentCreateRequest
) -> str:
    return _canonical_hash(
        {
            "author_user_id": request.author_user_id,
            "client_comment_id": request.client_comment_id,
            "content": request.content,
            "moment_id": moment_id,
        }
    )


def _comment_response(comment: MomentComment) -> MomentCommentRead:
    if comment.status != "active" or comment.content is None:
        raise MomentGoneError("Moment comment was deleted")
    return MomentCommentRead(
        comment_id=comment.id,
        client_comment_id=comment.client_comment_id,
        moment_id=comment.moment_id,
        author_user_id=comment.author_user_id,
        content=comment.content,
        state="active",
        sequence=comment.sequence,
        created_at=comment.created_at,
        persisted_at=comment.persisted_at,
    )


def create_moment_comment(
    session: Session,
    *,
    moment_id: str,
    request: MomentCommentCreateRequest,
) -> MomentMutationResult:
    moment = _require_visible_moment(
        session,
        moment_id=moment_id,
        context=request.context,
        for_update=True,
    )
    intent_sha256 = _comment_intent(moment_id, request)
    existing = session.execute(
        select(MomentComment)
        .where(
            MomentComment.author_user_id == request.author_user_id,
            MomentComment.client_comment_id == request.client_comment_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == "deleted":
            raise MomentGoneError("Moment comment idempotency key was deleted")
        if (
            existing.moment_id != moment_id
            or existing.intent_sha256 != intent_sha256
        ):
            raise MomentConflictError("Moment comment idempotency conflict")
        return MomentMutationResult(_comment_response(existing), True)

    now = utcnow()
    sequence = session.execute(
        update(Moment)
        .where(Moment.id == moment_id, Moment.state == "published")
        .values(
            last_comment_sequence=Moment.last_comment_sequence + 1,
            updated_at=now,
        )
        .returning(Moment.last_comment_sequence)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if sequence is None:
        session.rollback()
        raise MomentNotFoundError("Moment not found")
    comment_id = _new_comment_id()
    values = {
        "id": comment_id,
        "client_comment_id": request.client_comment_id,
        "moment_id": moment_id,
        "author_user_id": request.author_user_id,
        "content": request.content,
        "intent_sha256": intent_sha256,
        "status": "active",
        "sequence": sequence,
        "created_at": now,
        "persisted_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    insert_statement = _dialect_insert(session, MomentComment)
    if insert_statement is not None:
        claimed_id = session.execute(
            insert_statement.values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    MomentComment.__table__.c.author_user_id,
                    MomentComment.__table__.c.client_comment_id,
                ]
            )
            .returning(MomentComment.__table__.c.id)
        ).scalar_one_or_none()
        if claimed_id is None:
            session.rollback()
            existing = session.execute(
                select(MomentComment).where(
                    MomentComment.author_user_id == request.author_user_id,
                    MomentComment.client_comment_id == request.client_comment_id,
                )
            ).scalar_one_or_none()
            if existing is None:
                raise MomentStoreError("Moment comment claim disappeared")
            if existing.status == "deleted":
                raise MomentGoneError(
                    "Moment comment idempotency key was deleted"
                )
            if (
                existing.moment_id != moment_id
                or existing.intent_sha256 != intent_sha256
            ):
                raise MomentConflictError("Moment comment idempotency conflict")
            return MomentMutationResult(_comment_response(existing), True)
    else:
        session.add(MomentComment(**values))
        session.flush()
    session.execute(
        update(Moment)
        .where(Moment.id == moment_id, Moment.state == "published")
        .values(comment_count=Moment.comment_count + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    _emit_events(
        session,
        recipient_user_ids={moment.author_user_id},
        event_type="moment_commented",
        moment_id=moment.id,
        actor_user_id=request.author_user_id,
        comment_id=comment_id,
        created_at=now,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.execute(
            select(MomentComment).where(
                MomentComment.author_user_id == request.author_user_id,
                MomentComment.client_comment_id == request.client_comment_id,
            )
        ).scalar_one_or_none()
        if (
            existing is not None
            and existing.status == "active"
            and existing.moment_id == moment_id
            and existing.intent_sha256 == intent_sha256
        ):
            return MomentMutationResult(_comment_response(existing), True)
        raise MomentConflictError("Moment comment conflict") from exc
    comment = session.get(MomentComment, comment_id)
    if comment is None:
        raise MomentStoreError("Moment comment disappeared after commit")
    return MomentMutationResult(_comment_response(comment), False)


def list_moment_comments(
    session: Session,
    *,
    moment_id: str,
    request: MomentInteractionPageQuery,
    codec: CursorCodec,
) -> MomentCommentPageResponse:
    _require_visible_moment(
        session, moment_id=moment_id, context=request.context
    )
    scope = _cursor_scope("comments", request.context, moment_id=moment_id)
    position = (
        codec.decode(
            request.cursor, kinds=("moment_comments",), scope=scope
        ).position
        if request.cursor
        else 0
    )
    allowed = set(request.context.active_user_ids) - set(
        request.context.blocked_user_ids
    )
    rows = list(
        session.scalars(
            select(MomentComment)
            .where(
                MomentComment.moment_id == moment_id,
                MomentComment.status == "active",
                MomentComment.author_user_id.in_(allowed),
                MomentComment.sequence > position,
            )
            .order_by(MomentComment.sequence.asc())
            .limit(request.limit + 1)
        )
    )
    page_rows = rows[: request.limit]
    return MomentCommentPageResponse(
        items=[_comment_response(row) for row in page_rows],
        count=_visible_comment_count(session, moment_id, request.context),
        next_cursor=(
            codec.encode(
                kind="moment_comments",
                scope=scope,
                position=page_rows[-1].sequence,
            )
            if len(rows) > request.limit and page_rows
            else None
        ),
    )


def delete_moment_comment(
    session: Session,
    *,
    moment_id: str,
    comment_id: str,
    request: MomentCommentDeleteRequest,
) -> MomentCommentDeleteResponse:
    moment = _locked_moment(session, moment_id)
    comment = session.get(MomentComment, comment_id)
    actor = request.requested_by_user_id
    if (
        moment is None
        or comment is None
        or comment.moment_id != moment_id
        or actor not in {moment.author_user_id, comment.author_user_id}
    ):
        raise MomentNotFoundError("Moment comment not found")
    deleted_at = comment.deleted_at or request.requested_at
    changed = (
        session.execute(
            update(MomentComment)
            .where(
                MomentComment.id == comment_id,
                MomentComment.moment_id == moment_id,
                MomentComment.status == "active",
            )
            .values(
                status="deleted",
                content=None,
                intent_sha256=None,
                updated_at=request.requested_at,
                deleted_at=request.requested_at,
            )
            .returning(MomentComment.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        is not None
    )
    if changed:
        session.execute(
            update(Moment)
            .where(Moment.id == moment_id)
            .values(
                comment_count=Moment.comment_count - 1,
                updated_at=request.requested_at,
            )
            .execution_options(synchronize_session=False)
        )
        _emit_events(
            session,
            recipient_user_ids={moment.author_user_id, comment.author_user_id},
            event_type="moment_comment_deleted",
            moment_id=moment.id,
            actor_user_id=actor,
            comment_id=comment.id,
            created_at=request.requested_at,
        )
        session.commit()
        session.refresh(moment)
    else:
        # A concurrent winner may have changed the row after this session read
        # it but before the conditional transition claim executed.
        session.refresh(comment)
        deleted_at = comment.deleted_at or deleted_at
    return MomentCommentDeleteResponse(
        moment_id=moment_id,
        comment_id=comment_id,
        changed=changed,
        comment_count=_visible_comment_count(session, moment_id, request.context),
        deleted_at=deleted_at,
    )


def begin_moment_delete(
    session: Session,
    *,
    moment_id: str,
    request: MomentDeleteRequest,
) -> MomentDeleteResponse:
    moment = _locked_moment(session, moment_id)
    if moment is None or moment.author_user_id != request.requested_by_user_id:
        raise MomentNotFoundError("Moment not found")
    if moment.state == "draft":
        raise MomentConflictError("Unpublished Moment cannot enter deletion")
    assets = _assets_for_moment(session, moment_id)
    if moment.state == "deleted":
        return MomentDeleteResponse(
            moment_id=moment.id,
            state="deleted",
            changed=False,
            assets=[],
            updated_at=moment.updated_at,
        )
    if moment.state == "delete_pending":
        return MomentDeleteResponse(
            moment_id=moment.id,
            state="delete_pending",
            changed=False,
            assets=assets,
            updated_at=moment.updated_at,
        )

    audience = set(
        session.scalars(
            select(MomentAudienceSnapshot.user_id).where(
                MomentAudienceSnapshot.moment_id == moment_id
            )
        )
    ) or {moment.author_user_id}
    moment.state = "delete_pending"
    moment.content = None
    moment.publish_intent_sha256 = None
    moment.delete_pending_at = request.requested_at
    moment.updated_at = request.requested_at
    active_comments = list(
        session.scalars(
            select(MomentComment).where(
                MomentComment.moment_id == moment_id,
                MomentComment.status == "active",
            )
        )
    )
    for comment in active_comments:
        comment.status = "deleted"
        comment.content = None
        comment.intent_sha256 = None
        comment.updated_at = request.requested_at
        comment.deleted_at = request.requested_at
        session.add(comment)
    moment.comment_count = 0
    session.add(moment)
    # Persist the hidden/content-free state before allocating events.  Besides
    # making the deletion event truthful, this closes the write window on
    # dialects where SELECT FOR UPDATE is weaker than PostgreSQL's semantics.
    session.flush()
    _emit_events(
        session,
        recipient_user_ids=audience,
        event_type="moment_deleted",
        moment_id=moment.id,
        actor_user_id=request.requested_by_user_id,
        comment_id=None,
        created_at=request.requested_at,
    )
    session.commit()
    return MomentDeleteResponse(
        moment_id=moment.id,
        state="delete_pending",
        changed=True,
        assets=assets,
        updated_at=moment.updated_at,
    )


def complete_moment_delete(
    session: Session,
    *,
    moment_id: str,
    request: MomentDeleteCompleteRequest,
) -> MomentDeleteResponse:
    moment = _locked_moment(session, moment_id)
    if moment is None or moment.author_user_id != request.requested_by_user_id:
        raise MomentNotFoundError("Moment not found")
    if moment.state == "deleted":
        return MomentDeleteResponse(
            moment_id=moment.id,
            state="deleted",
            changed=False,
            assets=[],
            updated_at=moment.updated_at,
        )
    if moment.state != "delete_pending":
        raise MomentConflictError("Moment deletion has not been prepared")
    session.execute(
        delete(MomentAssetReferenceModel).where(
            MomentAssetReferenceModel.moment_id == moment_id
        )
    )
    moment.state = "deleted"
    moment.deleted_at = request.completed_at
    moment.updated_at = request.completed_at
    session.add(moment)
    session.commit()
    return MomentDeleteResponse(
        moment_id=moment.id,
        state="deleted",
        changed=True,
        assets=[],
        updated_at=moment.updated_at,
    )


def _event_visible(
    session: Session,
    event: MomentUserEvent,
    context: MomentViewerContext,
) -> bool:
    if event.user_id != context.viewer_user_id:
        return False
    active = set(context.active_user_ids)
    if context.viewer_user_id not in active:
        return False
    moment = session.get(Moment, event.moment_id)
    if moment is None:
        return False
    if event.event_type == "moment_deleted":
        # Tombstones carry no body, but even their IDs remain subject to the
        # same current friends/org/block/account policy as live content.
        return _is_current_policy_visible(session, moment, context)
    if not _is_visible(session, moment, context):
        return False
    return (
        event.actor_user_id == context.viewer_user_id
        or (
            event.actor_user_id in active
            and event.actor_user_id not in context.blocked_user_ids
        )
    )


def list_moment_events(
    session: Session,
    request: MomentEventQuery,
    *,
    codec: CursorCodec,
) -> MomentEventPageResponse:
    context = request.context
    scope = _cursor_scope("events", context)
    position = (
        codec.decode(
            request.cursor, kinds=("moment_events",), scope=scope
        ).position
        if request.cursor
        else 0
    )
    visible: list[MomentUserEvent] = []
    scan_position = position
    scanned = 0
    exhausted = False
    while len(visible) <= request.limit and scanned < _POLICY_SCAN_LIMIT:
        batch_size = min(_POLICY_SCAN_BATCH, _POLICY_SCAN_LIMIT - scanned)
        rows = list(
            session.scalars(
                select(MomentUserEvent)
                .where(
                    MomentUserEvent.user_id == context.viewer_user_id,
                    MomentUserEvent.event_sequence > scan_position,
                )
                .order_by(MomentUserEvent.event_sequence.asc())
                .limit(batch_size)
            )
        )
        if not rows:
            exhausted = True
            break
        scanned += len(rows)
        scan_position = rows[-1].event_sequence
        visible.extend(
            row for row in rows if _event_visible(session, row, context)
        )
        if len(rows) < batch_size:
            exhausted = True
            break
    page_rows = visible[: request.limit]
    counter = session.get(UserEventSequence, context.viewer_user_id)
    latest = counter.last_sequence if counter else 0
    if len(visible) > request.limit and page_rows:
        cursor_position = page_rows[-1].event_sequence
    elif not exhausted:
        cursor_position = scan_position
    else:
        # Shared chat/Moment event allocation may leave gaps in this table.
        # Advancing to the global tail is safe after every Moment row was scanned.
        cursor_position = latest
    return MomentEventPageResponse(
        events=[
            MomentEventRead(
                event_id=row.id,
                event_sequence=row.event_sequence,
                event_type=row.event_type.removeprefix("moment_"),
                moment_id=row.moment_id,
                actor_user_id=row.actor_user_id,
                comment_id=row.comment_id,
                created_at=row.created_at,
            )
            for row in page_rows
        ],
        next_cursor=codec.encode(
            kind="moment_events", scope=scope, position=cursor_position
        ),
        latest_event_sequence=latest,
    )


def get_moment_event_tail(
    session: Session,
    request: MomentContextQuery,
    *,
    codec: CursorCodec,
) -> MomentEventTailResponse:
    context = request.context
    counter = session.get(UserEventSequence, context.viewer_user_id)
    latest = counter.last_sequence if counter else 0
    return MomentEventTailResponse(
        cursor=codec.encode(
            kind="moment_events",
            scope=_cursor_scope("events", context),
            position=latest,
        ),
        latest_event_sequence=latest,
    )


__all__ = [
    "MomentConflictError",
    "MomentGoneError",
    "MomentMutationResult",
    "MomentNotFoundError",
    "MomentStoreError",
    "begin_moment_delete",
    "complete_moment_delete",
    "create_moment_comment",
    "delete_moment_comment",
    "get_moment",
    "get_moment_draft",
    "get_moment_event_tail",
    "list_moment_comments",
    "list_moment_events",
    "list_moment_feed",
    "list_moment_likes",
    "mutate_moment_like",
    "publish_moment",
    "relationship_context_sha256",
    "reserve_moment_draft",
]
