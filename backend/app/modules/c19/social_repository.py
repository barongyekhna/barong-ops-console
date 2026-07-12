"""Persistence helpers for C19 friendship and actor-owned block state."""

from __future__ import annotations

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from ...models.c19 import (
    C19FriendRequestRecord,
    C19ProfileRecord,
    C19RelationshipRecord,
    C19UserBlockRecord,
)
from ...models.user import User


def canonical_pair(user_a_id: int, user_b_id: int) -> tuple[int, int, str]:
    if user_a_id == user_b_id:
        raise ValueError("C19 social pair participants must be distinct.")
    low_id, high_id = sorted((user_a_id, user_b_id))
    return low_id, high_id, f"{low_id}:{high_id}"


def lock_user_pair(db: Session, *, user_a_id: int, user_b_id: int) -> None:
    """Serialize every cross-table write for one canonical user pair."""

    low_id, high_id, _ = canonical_pair(user_a_id, user_b_id)
    locked_ids = list(
        db.scalars(
            select(User.id)
            .where(User.id.in_((low_id, high_id)))
            .order_by(User.id)
            .with_for_update()
        )
    )
    if locked_ids != [low_id, high_id]:
        raise ValueError("C19 social pair user does not exist.")


def _active_user_exists(user_id_expression):
    return exists(
        select(User.id)
        .join(C19ProfileRecord, C19ProfileRecord.user_id == User.id)
        .where(
            User.id == user_id_expression,
            User.is_active.is_(True),
        )
    )


def get_friend_request_by_pair(
    db: Session,
    *,
    pair_key: str,
    for_update: bool = False,
) -> C19FriendRequestRecord | None:
    statement = select(C19FriendRequestRecord).where(
        C19FriendRequestRecord.pair_key == pair_key
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def get_friend_request_by_id(
    db: Session,
    *,
    request_id: str,
    for_update: bool = False,
) -> C19FriendRequestRecord | None:
    statement = select(C19FriendRequestRecord).where(
        C19FriendRequestRecord.request_id == request_id
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_friend_requests(
    db: Session,
    *,
    actor_user_id: int,
    direction: str,
    request_status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[C19FriendRequestRecord], int]:
    statement = select(C19FriendRequestRecord).where(
        or_(
            C19FriendRequestRecord.requester_user_id == actor_user_id,
            C19FriendRequestRecord.addressee_user_id == actor_user_id,
        ),
        _active_user_exists(C19FriendRequestRecord.requester_user_id),
        _active_user_exists(C19FriendRequestRecord.addressee_user_id),
    )
    if direction == "incoming":
        statement = statement.where(
            C19FriendRequestRecord.addressee_user_id == actor_user_id
        )
    elif direction == "outgoing":
        statement = statement.where(
            C19FriendRequestRecord.requester_user_id == actor_user_id
        )
    if request_status:
        statement = statement.where(
            C19FriendRequestRecord.status == request_status
        )

    total = int(
        db.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        or 0
    )
    rows = list(
        db.scalars(
            statement.order_by(
                C19FriendRequestRecord.created_at.desc(),
                C19FriendRequestRecord.request_id,
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, total


def get_relationship_by_pair(
    db: Session,
    *,
    pair_key: str,
    for_update: bool = False,
) -> C19RelationshipRecord | None:
    statement = select(C19RelationshipRecord).where(
        C19RelationshipRecord.pair_key == pair_key
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def has_active_block_between(
    db: Session,
    *,
    user_a_id: int,
    user_b_id: int,
) -> bool:
    return (
        db.scalar(
            select(C19UserBlockRecord.block_id)
            .where(
                C19UserBlockRecord.is_active.is_(True),
                or_(
                    and_(
                        C19UserBlockRecord.blocker_user_id == user_a_id,
                        C19UserBlockRecord.blocked_user_id == user_b_id,
                    ),
                    and_(
                        C19UserBlockRecord.blocker_user_id == user_b_id,
                        C19UserBlockRecord.blocked_user_id == user_a_id,
                    ),
                ),
            )
            .limit(1)
        )
        is not None
    )


def _no_active_block_for_pair(
    actor_user_id: int,
    target_user_id_expression,
):
    return ~exists(
        select(C19UserBlockRecord.block_id).where(
            C19UserBlockRecord.is_active.is_(True),
            or_(
                and_(
                    C19UserBlockRecord.blocker_user_id == actor_user_id,
                    C19UserBlockRecord.blocked_user_id
                    == target_user_id_expression,
                ),
                and_(
                    C19UserBlockRecord.blocker_user_id
                    == target_user_id_expression,
                    C19UserBlockRecord.blocked_user_id == actor_user_id,
                ),
            ),
        )
    )


def list_friend_relationships(
    db: Session,
    *,
    actor_user_id: int,
    limit: int,
    offset: int,
) -> tuple[list[tuple[C19RelationshipRecord, int]], int]:
    target_user_id = case(
        (
            C19RelationshipRecord.user_low_id == actor_user_id,
            C19RelationshipRecord.user_high_id,
        ),
        else_=C19RelationshipRecord.user_low_id,
    )
    statement = (
        select(C19RelationshipRecord, target_user_id.label("target_user_id"))
        .where(
            C19RelationshipRecord.status == "friends",
            or_(
                C19RelationshipRecord.user_low_id == actor_user_id,
                C19RelationshipRecord.user_high_id == actor_user_id,
            ),
            _active_user_exists(target_user_id),
            _no_active_block_for_pair(actor_user_id, target_user_id),
        )
        .order_by(
            C19RelationshipRecord.established_at.desc(),
            C19RelationshipRecord.relationship_id,
        )
    )
    total = int(
        db.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        or 0
    )
    rows = db.execute(statement.offset(offset).limit(limit)).all()
    return [(row[0], int(row.target_user_id)) for row in rows], total


def get_user_block(
    db: Session,
    *,
    blocker_user_id: int,
    blocked_user_id: int,
    for_update: bool = False,
) -> C19UserBlockRecord | None:
    statement = select(C19UserBlockRecord).where(
        C19UserBlockRecord.blocker_user_id == blocker_user_id,
        C19UserBlockRecord.blocked_user_id == blocked_user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_user_blocks(
    db: Session,
    *,
    blocker_user_id: int,
    limit: int,
    offset: int,
) -> tuple[list[C19UserBlockRecord], int]:
    statement = select(C19UserBlockRecord).where(
        C19UserBlockRecord.blocker_user_id == blocker_user_id,
        C19UserBlockRecord.is_active.is_(True),
        _active_user_exists(C19UserBlockRecord.blocked_user_id),
    )
    total = int(
        db.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        or 0
    )
    rows = list(
        db.scalars(
            statement.order_by(
                C19UserBlockRecord.blocked_at.desc(),
                C19UserBlockRecord.block_id,
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, total


__all__ = [
    "canonical_pair",
    "get_friend_request_by_id",
    "get_friend_request_by_pair",
    "get_relationship_by_pair",
    "get_user_block",
    "has_active_block_between",
    "list_friend_relationships",
    "list_friend_requests",
    "list_user_blocks",
    "lock_user_pair",
]
