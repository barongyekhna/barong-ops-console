from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from c19_record_service.cursors import InvalidCursorError
from c19_record_service.models import (
    Moment,
    MomentAssetReference as MomentAssetReferenceModel,
    MomentAudienceSnapshot,
    MomentComment,
    MomentLike,
    MomentUserEvent,
)
from c19_record_service.moment_repository import (
    MomentConflictError,
    MomentGoneError,
    MomentNotFoundError,
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
from c19_record_service.moment_schemas import (
    MomentAssetReference,
    MomentCommentCreateRequest,
    MomentCommentDeleteRequest,
    MomentContextQuery,
    MomentDeleteCompleteRequest,
    MomentDeleteRequest,
    MomentDraftCreateRequest,
    MomentDraftQueryRequest,
    MomentEventQuery,
    MomentFeedQuery,
    MomentInteractionPageQuery,
    MomentLikeMutationRequest,
    MomentPublishRequest,
    MomentViewerContext,
)


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def context(
    viewer: str,
    *,
    active: list[str] | None = None,
    orgs: list[str] | None = None,
    friends: list[str] | None = None,
    blocked: list[str] | None = None,
) -> MomentViewerContext:
    return MomentViewerContext(
        viewer_user_id=viewer,
        active_user_ids=active or ["user-1", "user-2", "user-3"],
        active_org_ids=orgs or [],
        friend_user_ids=friends or [],
        blocked_user_ids=blocked or [],
    )


def asset(number: int, *, ordinal: int = 0) -> MomentAssetReference:
    return MomentAssetReference(
        asset_id=f"att_{number:032x}",
        client_asset_id=f"moment-asset-{number}",
        kind="image",
        filename=f"moment-{number}.jpg",
        media_type="image/jpeg",
        size_bytes=1000 + number,
        sha256_hex=f"{number:064x}",
        version=1,
        ordinal=ordinal,
    )


def reserve(
    runtime,
    number: int,
    *,
    author: str = "user-1",
) -> str:
    with runtime.session_factory() as session:
        return reserve_moment_draft(
            session,
            MomentDraftCreateRequest(
                client_moment_id=f"client-moment-{number}",
                author_user_id=author,
            ),
        ).moment_id


def publish(
    runtime,
    number: int,
    *,
    visibility: str = "public",
    audience: list[str] | None = None,
    orgs: list[str] | None = None,
    images: list[MomentAssetReference] | None = None,
    content: str | None = None,
) -> tuple[str, MomentPublishRequest]:
    moment_id = reserve(runtime, number)
    request = MomentPublishRequest(
        author_user_id="user-1",
        author_org_id="org-1" if visibility == "org" else None,
        content=f"Moment {number}" if content is None else content,
        visibility=visibility,
        audience_user_ids=audience or ["user-1", "user-2"],
        audience_org_ids=orgs or (["org-1"] if visibility == "org" else []),
        assets=images or [],
    )
    with runtime.session_factory() as session:
        result = publish_moment(session, moment_id=moment_id, request=request)
        assert result.replayed is False
    return moment_id, request


def test_moment_schema_enforces_text_image_audience_and_context_boundaries() -> None:
    base = {
        "author_user_id": "user-1",
        "author_org_id": None,
        "content": "",
        "visibility": "public",
        "audience_user_ids": ["user-1"],
        "audience_org_ids": [],
        "assets": [],
    }
    with pytest.raises(ValidationError):
        MomentPublishRequest(**base)
    with pytest.raises(ValidationError):
        MomentPublishRequest(
            **{
                **base,
                "content": "valid",
                "visibility": "private",
                "audience_user_ids": ["user-1", "user-2"],
            }
        )
    with pytest.raises(ValidationError):
        MomentPublishRequest(
            **{
                **base,
                "content": "valid",
                "visibility": "org",
                "author_org_id": "wrong-org",
                "audience_org_ids": ["org-1"],
            }
        )
    with pytest.raises(ValidationError):
        MomentPublishRequest(
            **{
                **base,
                "assets": [asset(i, ordinal=i) for i in range(10)],
            }
        )
    with pytest.raises(ValidationError):
        context("user-1", friends=["user-2"], blocked=["user-2"])


def test_private_draft_reservation_publish_replay_and_tombstone(runtime) -> None:
    moment_id = reserve(runtime, 1)
    with runtime.session_factory() as session:
        replay = reserve_moment_draft(
            session,
            MomentDraftCreateRequest(
                client_moment_id="client-moment-1",
                author_user_id="user-1",
            ),
        )
        assert replay.moment_id == moment_id
        assert replay.state == "draft"
        assert get_moment_draft(
            session,
            moment_id=moment_id,
            request=MomentDraftQueryRequest(author_user_id="user-1"),
        ).state == "draft"
        with pytest.raises(MomentNotFoundError):
            get_moment_draft(
                session,
                moment_id=moment_id,
                request=MomentDraftQueryRequest(author_user_id="user-2"),
            )
        with pytest.raises(MomentConflictError):
            begin_moment_delete(
                session,
                moment_id=moment_id,
                request=MomentDeleteRequest(
                    context=context("user-1"),
                    requested_by_user_id="user-1",
                    requested_at=NOW,
                ),
            )

    request = MomentPublishRequest(
        author_user_id="user-1",
        content="published once",
        visibility="public",
        audience_user_ids=["user-1", "user-2"],
        audience_org_ids=[],
        assets=[asset(1)],
    )
    with runtime.session_factory() as session:
        first = publish_moment(session, moment_id=moment_id, request=request)
        second = publish_moment(
            session,
            moment_id=moment_id,
            request=request,
        )
        assert first.replayed is False
        assert second.replayed is True
        assert second.value.moment_id == moment_id
        assert get_moment_draft(
            session,
            moment_id=moment_id,
            request=MomentDraftQueryRequest(author_user_id="user-1"),
        ).state == "published"
        with pytest.raises(MomentConflictError):
            publish_moment(
                session,
                moment_id=moment_id,
                request=request.model_copy(update={"content": "different"}),
            )

    delete_request = MomentDeleteRequest(
        context=context("user-1"),
        requested_by_user_id="user-1",
        requested_at=NOW + timedelta(days=1),
    )
    with runtime.session_factory() as session:
        pending = begin_moment_delete(
            session, moment_id=moment_id, request=delete_request
        )
        assert pending.state == "delete_pending"
        assert [item.asset_id for item in pending.assets] == [asset(1).asset_id]
        assert get_moment_draft(
            session,
            moment_id=moment_id,
            request=MomentDraftQueryRequest(author_user_id="user-1"),
        ).state == "delete_pending"
        completed = complete_moment_delete(
            session,
            moment_id=moment_id,
            request=MomentDeleteCompleteRequest(
                requested_by_user_id="user-1",
                completed_at=NOW + timedelta(days=1, seconds=1),
            ),
        )
        assert completed.state == "deleted"
        assert get_moment_draft(
            session,
            moment_id=moment_id,
            request=MomentDraftQueryRequest(author_user_id="user-1"),
        ).state == "deleted"
        assert session.scalar(
            select(func.count(MomentAssetReferenceModel.id)).where(
                MomentAssetReferenceModel.moment_id == moment_id
            )
        ) == 0
        with pytest.raises(MomentGoneError):
            reserve_moment_draft(
                session,
                MomentDraftCreateRequest(
                    client_moment_id="client-moment-1",
                    author_user_id="user-1",
                ),
            )


@pytest.mark.parametrize(
    ("visibility", "orgs", "friends", "blocked", "visible"),
    (
        ("public", [], [], [], True),
        ("public", [], [], ["user-1"], False),
        ("org", ["org-1"], [], [], True),
        ("org", ["org-2"], [], [], False),
        ("friends", [], ["user-1"], [], True),
        ("friends", [], [], [], False),
        ("private", [], ["user-1"], [], False),
    ),
)
def test_exact_visibility_requires_snapshot_and_current_policy(
    runtime, visibility, orgs, friends, blocked, visible
) -> None:
    moment_id, _ = publish(
        runtime,
        10,
        visibility=visibility,
        orgs=["org-1"] if visibility == "org" else [],
        audience=(
            ["user-1"] if visibility == "private" else ["user-1", "user-2"]
        ),
    )
    request = MomentContextQuery(
        context=context(
            "user-2", orgs=orgs, friends=friends, blocked=blocked
        )
    )
    with runtime.session_factory() as session:
        if visible:
            assert get_moment(
                session, moment_id=moment_id, request=request
            ).moment_id == moment_id
        else:
            with pytest.raises(MomentNotFoundError):
                get_moment(session, moment_id=moment_id, request=request)


def test_publish_time_audience_is_a_ceiling_even_for_public_moments(runtime) -> None:
    moment_id, _ = publish(runtime, 20, audience=["user-1", "user-2"])
    with runtime.session_factory() as session:
        with pytest.raises(MomentNotFoundError):
            get_moment(
                session,
                moment_id=moment_id,
                request=MomentContextQuery(context=context("user-3")),
            )
        assert session.get(
            MomentAudienceSnapshot, (moment_id, "user-3")
        ) is None


def test_feed_is_stable_signed_and_bound_to_relationship_context(runtime, codec) -> None:
    first, _ = publish(runtime, 30)
    second, _ = publish(runtime, 31)
    viewer = context("user-2")
    with runtime.session_factory() as session:
        page = list_moment_feed(
            session,
            MomentFeedQuery(context=viewer, limit=1),
            codec=codec,
        )
        assert [item.moment_id for item in page.moments] == [second]
        assert page.next_cursor
        next_page = list_moment_feed(
            session,
            MomentFeedQuery(
                context=viewer, limit=1, cursor=page.next_cursor
            ),
            codec=codec,
        )
        assert [item.moment_id for item in next_page.moments] == [first]
        with pytest.raises(InvalidCursorError):
            list_moment_feed(
                session,
                MomentFeedQuery(
                    context=context("user-2", blocked=["user-3"]),
                    limit=1,
                    cursor=page.next_cursor,
                ),
                codec=codec,
            )
        with pytest.raises(InvalidCursorError):
            list_moment_feed(
                session,
                MomentFeedQuery(
                    context=viewer,
                    limit=1,
                    cursor=f"{page.next_cursor}x",
                ),
                codec=codec,
            )


def test_like_lifecycle_is_idempotent_and_lists_only_currently_visible_users(
    runtime, codec
) -> None:
    moment_id, _ = publish(runtime, 40)
    request = MomentLikeMutationRequest(
        context=context("user-2"),
        user_id="user-2",
        occurred_at=NOW,
    )
    with runtime.session_factory() as session:
        first = mutate_moment_like(
            session, moment_id=moment_id, request=request, liked=True
        )
        replay = mutate_moment_like(
            session, moment_id=moment_id, request=request, liked=True
        )
        assert (first.changed, replay.changed) == (True, False)
        assert replay.like_count == 1
        removed = mutate_moment_like(
            session,
            moment_id=moment_id,
            request=request.model_copy(update={"occurred_at": NOW + timedelta(seconds=1)}),
            liked=False,
        )
        replay_remove = mutate_moment_like(
            session,
            moment_id=moment_id,
            request=request,
            liked=False,
        )
        assert (removed.changed, replay_remove.changed) == (True, False)
        assert removed.like_count == 0
        reliked = mutate_moment_like(
            session,
            moment_id=moment_id,
            request=request.model_copy(update={"occurred_at": NOW + timedelta(seconds=2)}),
            liked=True,
        )
        assert reliked.like_count == 1
        page = list_moment_likes(
            session,
            moment_id=moment_id,
            request=MomentInteractionPageQuery(
                context=context("user-1"), limit=10
            ),
            codec=codec,
        )
        assert [item.user_id for item in page.items] == ["user-2"]
        hidden = list_moment_likes(
            session,
            moment_id=moment_id,
            request=MomentInteractionPageQuery(
                context=context("user-1", blocked=["user-2"]), limit=10
            ),
            codec=codec,
        )
        assert hidden.items == []
        assert hidden.count == 0
        assert session.get(Moment, moment_id).like_count == 1


def test_comment_idempotency_pagination_ownership_and_body_free_delete(
    runtime, codec
) -> None:
    moment_id, _ = publish(runtime, 50)
    viewer = context("user-2")
    first_request = MomentCommentCreateRequest(
        context=viewer,
        client_comment_id="client-comment-1",
        author_user_id="user-2",
        content="first comment",
    )
    with runtime.session_factory() as session:
        first = create_moment_comment(
            session, moment_id=moment_id, request=first_request
        )
        replay = create_moment_comment(
            session,
            moment_id=moment_id,
            request=first_request,
        )
        assert first.replayed is False
        assert replay.replayed is True
        assert replay.value.comment_id == first.value.comment_id
        with pytest.raises(MomentConflictError):
            create_moment_comment(
                session,
                moment_id=moment_id,
                request=first_request.model_copy(update={"content": "changed"}),
            )
        second = create_moment_comment(
            session,
            moment_id=moment_id,
            request=MomentCommentCreateRequest(
                context=viewer,
                client_comment_id="client-comment-2",
                author_user_id="user-2",
                content="second comment",
            ),
        )
        page = list_moment_comments(
            session,
            moment_id=moment_id,
            request=MomentInteractionPageQuery(context=viewer, limit=1),
            codec=codec,
        )
        assert [item.sequence for item in page.items] == [1]
        assert page.next_cursor
        page_two = list_moment_comments(
            session,
            moment_id=moment_id,
            request=MomentInteractionPageQuery(
                context=viewer, limit=1, cursor=page.next_cursor
            ),
            codec=codec,
        )
        assert [item.sequence for item in page_two.items] == [2]

        with pytest.raises(MomentNotFoundError):
            delete_moment_comment(
                session,
                moment_id=moment_id,
                comment_id=first.value.comment_id,
                request=MomentCommentDeleteRequest(
                    context=context("user-3"),
                    requested_by_user_id="user-3",
                    requested_at=NOW,
                ),
            )
        deleted = delete_moment_comment(
            session,
            moment_id=moment_id,
            comment_id=first.value.comment_id,
            request=MomentCommentDeleteRequest(
                context=context("user-1"),
                requested_by_user_id="user-1",
                requested_at=NOW + timedelta(seconds=2),
            ),
        )
        assert deleted.changed is True
        row = session.get(MomentComment, first.value.comment_id)
        assert row.status == "deleted"
        assert row.content is None
        assert row.intent_sha256 is None
        with pytest.raises(MomentGoneError):
            create_moment_comment(
                session, moment_id=moment_id, request=first_request
            )
        assert second.value.sequence == 2


def test_delete_pending_hides_immediately_clears_text_and_keeps_assets(runtime) -> None:
    moment_id, _ = publish(
        runtime,
        60,
        images=[asset(1), asset(2, ordinal=1)],
        content="sensitive Moment text",
    )
    with runtime.session_factory() as session:
        comment = create_moment_comment(
            session,
            moment_id=moment_id,
            request=MomentCommentCreateRequest(
                context=context("user-2"),
                client_comment_id="sensitive-comment",
                author_user_id="user-2",
                content="sensitive comment text",
            ),
        ).value
        pending = begin_moment_delete(
            session,
            moment_id=moment_id,
            request=MomentDeleteRequest(
                context=context("user-1"),
                requested_by_user_id="user-1",
                requested_at=NOW + timedelta(days=1),
            ),
        )
        assert pending.state == "delete_pending"
        assert len(pending.assets) == 2
        row = session.get(Moment, moment_id)
        assert row.content is None
        assert row.publish_intent_sha256 is None
        assert session.get(MomentComment, comment.comment_id).content is None
        assert session.scalar(
            select(func.count(MomentAssetReferenceModel.id)).where(
                MomentAssetReferenceModel.moment_id == moment_id
            )
        ) == 2
        with pytest.raises(MomentNotFoundError):
            get_moment(
                session,
                moment_id=moment_id,
                request=MomentContextQuery(context=context("user-1")),
            )
        replay = begin_moment_delete(
            session,
            moment_id=moment_id,
            request=MomentDeleteRequest(
                context=context("user-1"),
                requested_by_user_id="user-1",
                requested_at=NOW + timedelta(days=2),
            ),
        )
        assert replay.changed is False
        assert len(replay.assets) == 2


def test_moment_events_share_global_sequence_but_use_content_free_scoped_cursor(
    runtime, codec
) -> None:
    moment_id, _ = publish(runtime, 70)
    with runtime.session_factory() as session:
        mutate_moment_like(
            session,
            moment_id=moment_id,
            request=MomentLikeMutationRequest(
                context=context("user-2"),
                user_id="user-2",
                occurred_at=NOW,
            ),
            liked=True,
        )
        user_context = context("user-1")
        page = list_moment_events(
            session,
            MomentEventQuery(context=user_context, limit=10),
            codec=codec,
        )
        assert [event.event_type for event in page.events] == [
            "published",
            "liked",
        ]
        assert page.next_cursor
        serialized = page.model_dump_json()
        assert "Moment 70" not in serialized
        assert "filename" not in serialized
        assert "visibility" not in serialized
        tail = get_moment_event_tail(
            session, MomentContextQuery(context=user_context), codec=codec
        )
        assert tail.latest_event_sequence == page.latest_event_sequence
        with pytest.raises(InvalidCursorError):
            list_moment_events(
                session,
                MomentEventQuery(
                    context=context("user-1", blocked=["user-3"]),
                    cursor=page.next_cursor,
                ),
                codec=codec,
            )
        assert all(
            row.event_type.startswith("moment_")
            for row in session.scalars(select(MomentUserEvent))
        )


def test_deleted_events_recheck_current_friend_block_and_active_policy(
    runtime, codec
) -> None:
    moment_id, _ = publish(
        runtime,
        75,
        visibility="friends",
        audience=["user-1", "user-2"],
    )
    with runtime.session_factory() as session:
        begin_moment_delete(
            session,
            moment_id=moment_id,
            request=MomentDeleteRequest(
                context=context("user-1"),
                requested_by_user_id="user-1",
                requested_at=NOW + timedelta(days=1),
            ),
        )
        authorized = list_moment_events(
            session,
            MomentEventQuery(
                context=context("user-2", friends=["user-1"]), limit=20
            ),
            codec=codec,
        )
        assert [event.event_type for event in authorized.events] == ["deleted"]
        revoked = list_moment_events(
            session,
            MomentEventQuery(context=context("user-2"), limit=20),
            codec=codec,
        )
        assert revoked.events == []
        blocked = list_moment_events(
            session,
            MomentEventQuery(
                context=context("user-2", blocked=["user-1"]), limit=20
            ),
            codec=codec,
        )
        assert blocked.events == []
        inactive_author = list_moment_events(
            session,
            MomentEventQuery(
                context=context("user-2", active=["user-2", "user-3"]),
                limit=20,
            ),
            codec=codec,
        )
        assert inactive_author.events == []


def test_concurrent_duplicate_likes_never_duplicate_rows_or_counts(runtime) -> None:
    moment_id, _ = publish(runtime, 80)

    def like_once() -> bool:
        with runtime.session_factory() as session:
            return mutate_moment_like(
                session,
                moment_id=moment_id,
                request=MomentLikeMutationRequest(
                    context=context("user-2"),
                    user_id="user-2",
                    occurred_at=datetime.now(UTC),
                ),
                liked=True,
            ).changed

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(lambda _: like_once(), range(8)))
    assert sum(outcomes) == 1
    with runtime.session_factory() as session:
        assert session.scalar(select(func.count(MomentLike.user_id))) == 1
        assert session.get(Moment, moment_id).like_count == 1


def test_concurrent_publish_retries_collapse_to_one_publication(runtime) -> None:
    moment_id = reserve(runtime, 90)
    request = MomentPublishRequest(
        author_user_id="user-1",
        content="concurrent publication",
        visibility="public",
        audience_user_ids=["user-1", "user-2"],
        audience_org_ids=[],
        assets=[asset(9)],
    )

    def publish_once() -> tuple[str, bool]:
        with runtime.session_factory() as session:
            result = publish_moment(
                session, moment_id=moment_id, request=request
            )
            return result.value.moment_id, result.replayed

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: publish_once(), range(6)))
    assert {item[0] for item in results} == {moment_id}
    assert sum(not item[1] for item in results) == 1
    with runtime.session_factory() as session:
        assert session.scalar(select(func.count(Moment.id))) == 1
        assert session.scalar(
            select(func.count(MomentAssetReferenceModel.id))
        ) == 1
        assert session.scalar(
            select(func.count(MomentUserEvent.id)).where(
                MomentUserEvent.event_type == "moment_published"
            )
        ) == 2


def test_concurrent_distinct_comments_receive_unique_order_and_exact_counts(
    runtime,
) -> None:
    users = [f"user-{number}" for number in range(1, 10)]
    moment_id, _ = publish(runtime, 100, audience=users)

    def comment_once(number: int) -> int:
        author = f"user-{number}"
        with runtime.session_factory() as session:
            result = create_moment_comment(
                session,
                moment_id=moment_id,
                request=MomentCommentCreateRequest(
                    context=context(author, active=users),
                    client_comment_id=f"concurrent-comment-{number}",
                    author_user_id=author,
                    content=f"comment {number}",
                ),
            )
            assert result.replayed is False
            return result.value.sequence

    with ThreadPoolExecutor(max_workers=4) as executor:
        sequences = list(executor.map(comment_once, range(2, 10)))
    assert sorted(sequences) == list(range(1, 9))
    with runtime.session_factory() as session:
        assert session.scalar(select(func.count(MomentComment.id))) == 8
        assert session.get(Moment, moment_id).comment_count == 8
