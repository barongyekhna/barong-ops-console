"""Durable C19 friendship and private block application services."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...models.c19 import (
    C19FriendRequestRecord,
    C19RelationshipRecord,
    C19UserBlockRecord,
)
from ...models.user import User
from ...repositories.operation_logs import create_operation_log
from ...services.auth_service import AuditContext
from ...services.data_isolation import without_org_data_isolation
from . import identity_repository, social_repository
from .identity_repository import C19ProfileBundle
from .identity_service import (
    C19ProfileNotFoundError,
    profile_read_from_bundle,
    profile_summary_from_bundle,
    require_active_c19_actor,
)
from .social_schemas import (
    C19BlockPage,
    C19BlockRead,
    C19FriendPage,
    C19FriendRead,
    C19FriendRequestCreate,
    C19FriendRequestDirection,
    C19FriendRequestPage,
    C19FriendRequestRead,
    C19FriendRequestStatus,
    C19UserChangeRead,
)


class C19SocialError(ValueError):
    pass


class C19SocialNotFoundError(C19SocialError):
    pass


class C19SocialConflictError(C19SocialError):
    pass


class C19SocialSelfTargetError(C19SocialError):
    pass


class C19SocialInteractionUnavailableError(C19SocialConflictError):
    """Generic denial that never reveals which participant owns a block."""


def _now() -> datetime:
    return datetime.now(UTC)


def _write_social_audit(
    db: Session,
    *,
    actor: User,
    audit: AuditContext,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, object],
) -> None:
    # Callers pass identifiers and lifecycle state only. Display metadata,
    # profile bios, friend-request messages, and block-owner inference are banned.
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(actor.id),
        action=action,
        target_type=target_type,
        target_id=target_id,
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details=details,
    )


def _require_target_bundle(
    db: Session,
    *,
    user_id: int,
) -> C19ProfileBundle:
    bundle = identity_repository.get_active_profile_bundle(db, user_id=user_id)
    if bundle is None:
        raise C19ProfileNotFoundError("C19 profile not found.")
    return bundle


def _profile_bundles(
    db: Session,
    *,
    user_ids: list[int],
) -> dict[int, C19ProfileBundle]:
    return identity_repository.get_active_profile_bundles(
        db,
        user_ids=list(dict.fromkeys(user_ids)),
    )


def _friend_request_read(
    request: C19FriendRequestRecord,
    *,
    bundles: dict[int, C19ProfileBundle],
) -> C19FriendRequestRead:
    requester = bundles.get(request.requester_user_id)
    addressee = bundles.get(request.addressee_user_id)
    if requester is None or addressee is None:
        raise C19SocialNotFoundError("Friend request is unavailable.")
    return C19FriendRequestRead(
        request_id=request.request_id,
        requester=profile_summary_from_bundle(requester),
        addressee=profile_summary_from_bundle(addressee),
        status=request.status,
        request_message=request.request_message,
        responded_at=request.responded_at,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


def _ensure_distinct(actor_user_id: int, target_user_id: int) -> None:
    if actor_user_id == target_user_id:
        raise C19SocialSelfTargetError("A user cannot target themselves.")


def _ensure_pair_interaction_available(
    db: Session,
    *,
    user_a_id: int,
    user_b_id: int,
) -> None:
    if social_repository.has_active_block_between(
        db,
        user_a_id=user_a_id,
        user_b_id=user_b_id,
    ):
        raise C19SocialInteractionUnavailableError(
            "Social interaction is unavailable."
        )


def list_friend_requests(
    db: Session,
    *,
    actor: User,
    direction: C19FriendRequestDirection,
    request_status: C19FriendRequestStatus | None,
    limit: int,
    offset: int,
) -> C19FriendRequestPage:
    require_active_c19_actor(db, actor=actor)
    with without_org_data_isolation():
        records, total = social_repository.list_friend_requests(
            db,
            actor_user_id=actor.id,
            direction=direction.value,
            request_status=request_status.value if request_status else None,
            limit=limit,
            offset=offset,
        )
        bundles = _profile_bundles(
            db,
            user_ids=[
                user_id
                for record in records
                for user_id in (
                    record.requester_user_id,
                    record.addressee_user_id,
                )
            ],
        )
        items = [
            _friend_request_read(record, bundles=bundles) for record in records
        ]
    return C19FriendRequestPage(
        items=items,
        count=total,
        limit=limit,
        offset=offset,
    )


def create_friend_request(
    db: Session,
    *,
    actor: User,
    payload: C19FriendRequestCreate,
    audit: AuditContext,
) -> C19FriendRequestRead:
    require_active_c19_actor(db, actor=actor)
    target_user_id = payload.addressee_user_id
    _ensure_distinct(actor.id, target_user_id)
    low_id, high_id, pair_key = social_repository.canonical_pair(
        actor.id,
        target_user_id,
    )

    with without_org_data_isolation():
        actor_bundle = _require_target_bundle(db, user_id=actor.id)
        target_bundle = _require_target_bundle(db, user_id=target_user_id)
        social_repository.lock_user_pair(
            db,
            user_a_id=actor.id,
            user_b_id=target_user_id,
        )
        _ensure_pair_interaction_available(
            db,
            user_a_id=actor.id,
            user_b_id=target_user_id,
        )
        request = social_repository.get_friend_request_by_pair(
            db,
            pair_key=pair_key,
            for_update=True,
        )
        relationship = social_repository.get_relationship_by_pair(
            db,
            pair_key=pair_key,
            for_update=True,
        )
        if relationship is not None and relationship.status == "friends":
            raise C19SocialConflictError("Users are already friends.")

        if request is not None and request.status == "pending":
            if request.requester_user_id != actor.id:
                raise C19SocialConflictError("A friend request is already pending.")
        elif request is None:
            candidate = C19FriendRequestRecord(
                pair_key=pair_key,
                requester_user_id=actor.id,
                addressee_user_id=target_user_id,
                status="pending",
                request_message=payload.request_message,
            )
            try:
                with db.begin_nested():
                    db.add(candidate)
                    db.flush()
                request = candidate
            except IntegrityError:
                request = social_repository.get_friend_request_by_pair(
                    db,
                    pair_key=pair_key,
                    for_update=True,
                )
                if request is None:
                    raise C19SocialConflictError(
                        "Friend request could not be created."
                    ) from None
                if request.status == "pending" and (
                    request.requester_user_id != actor.id
                ):
                    raise C19SocialConflictError(
                        "A friend request is already pending."
                    ) from None
        else:
            request.requester_user_id = actor.id
            request.addressee_user_id = target_user_id
            request.status = "pending"
            request.request_message = payload.request_message
            request.responded_at = None

        db.flush()
        db.refresh(request)
        response = _friend_request_read(
            request,
            bundles={
                actor.id: actor_bundle,
                target_user_id: target_bundle,
            },
        )
        _write_social_audit(
            db,
            actor=actor,
            audit=audit,
            action="c19.friend_request.create",
            target_type="c19_friend_request",
            target_id=request.request_id,
            details={
                "target_user_id": target_user_id,
                "pair_low_user_id": low_id,
                "pair_high_user_id": high_id,
                "status": request.status,
            },
        )
        db.commit()
    return response


def _get_actor_request(
    db: Session,
    *,
    request_id: str,
    actor_user_id: int,
    expected_side: str,
    for_update: bool = True,
) -> C19FriendRequestRecord:
    request = social_repository.get_friend_request_by_id(
        db,
        request_id=request_id,
        for_update=for_update,
    )
    expected_user_id = (
        request.addressee_user_id
        if request is not None and expected_side == "addressee"
        else request.requester_user_id
        if request is not None
        else None
    )
    if request is None or expected_user_id != actor_user_id:
        raise C19SocialNotFoundError("Friend request not found.")
    return request


def _request_response_bundles(
    db: Session,
    request: C19FriendRequestRecord,
) -> dict[int, C19ProfileBundle]:
    bundles = _profile_bundles(
        db,
        user_ids=[request.requester_user_id, request.addressee_user_id],
    )
    if len(bundles) != 2:
        raise C19SocialNotFoundError("Friend request is unavailable.")
    return bundles


def accept_friend_request(
    db: Session,
    *,
    actor: User,
    request_id: str,
    audit: AuditContext,
) -> C19FriendRequestRead:
    require_active_c19_actor(db, actor=actor)
    with without_org_data_isolation():
        request = _get_actor_request(
            db,
            request_id=request_id,
            actor_user_id=actor.id,
            expected_side="addressee",
            for_update=False,
        )
        social_repository.lock_user_pair(
            db,
            user_a_id=request.requester_user_id,
            user_b_id=request.addressee_user_id,
        )
        request = _get_actor_request(
            db,
            request_id=request_id,
            actor_user_id=actor.id,
            expected_side="addressee",
        )
        bundles = _request_response_bundles(db, request)
        _ensure_pair_interaction_available(
            db,
            user_a_id=request.requester_user_id,
            user_b_id=request.addressee_user_id,
        )
        if request.status not in {"pending", "accepted"}:
            raise C19SocialConflictError("Friend request is no longer pending.")

        low_id, high_id, pair_key = social_repository.canonical_pair(
            request.requester_user_id,
            request.addressee_user_id,
        )
        now = _now()
        relationship = social_repository.get_relationship_by_pair(
            db,
            pair_key=pair_key,
            for_update=True,
        )
        if request.status == "accepted":
            if relationship is None or relationship.status != "friends":
                raise C19SocialConflictError(
                    "A removed friendship requires a new friend request."
                )
        else:
            if relationship is None:
                candidate = C19RelationshipRecord(
                    pair_key=pair_key,
                    user_low_id=low_id,
                    user_high_id=high_id,
                    status="friends",
                    origin_request_id=request.request_id,
                    established_at=now,
                )
                try:
                    with db.begin_nested():
                        db.add(candidate)
                        db.flush()
                    relationship = candidate
                except IntegrityError:
                    relationship = social_repository.get_relationship_by_pair(
                        db,
                        pair_key=pair_key,
                        for_update=True,
                    )
                    if relationship is None:
                        raise C19SocialConflictError(
                            "Friend relationship could not be established."
                        ) from None
            if relationship.status != "friends":
                relationship.status = "friends"
                relationship.origin_request_id = request.request_id
                relationship.established_at = now
                relationship.ended_at = None
            request.status = "accepted"
            request.responded_at = now
        db.flush()
        db.refresh(request)
        response = _friend_request_read(request, bundles=bundles)
        _write_social_audit(
            db,
            actor=actor,
            audit=audit,
            action="c19.friend_request.accept",
            target_type="c19_friend_request",
            target_id=request.request_id,
            details={
                "requester_user_id": request.requester_user_id,
                "status": request.status,
                "relationship_id": relationship.relationship_id,
            },
        )
        db.commit()
    return response


def _close_friend_request(
    db: Session,
    *,
    actor: User,
    request_id: str,
    audit: AuditContext,
    action: str,
    expected_side: str,
    terminal_status: str,
) -> C19FriendRequestRead:
    require_active_c19_actor(db, actor=actor)
    with without_org_data_isolation():
        request = _get_actor_request(
            db,
            request_id=request_id,
            actor_user_id=actor.id,
            expected_side=expected_side,
            for_update=False,
        )
        social_repository.lock_user_pair(
            db,
            user_a_id=request.requester_user_id,
            user_b_id=request.addressee_user_id,
        )
        request = _get_actor_request(
            db,
            request_id=request_id,
            actor_user_id=actor.id,
            expected_side=expected_side,
        )
        bundles = _request_response_bundles(db, request)
        if request.status not in {"pending", terminal_status}:
            raise C19SocialConflictError("Friend request is no longer pending.")
        if request.status != terminal_status:
            request.status = terminal_status
            request.responded_at = _now()
        db.flush()
        db.refresh(request)
        response = _friend_request_read(request, bundles=bundles)
        _write_social_audit(
            db,
            actor=actor,
            audit=audit,
            action=action,
            target_type="c19_friend_request",
            target_id=request.request_id,
            details={"status": request.status},
        )
        db.commit()
    return response


def reject_friend_request(
    db: Session,
    *,
    actor: User,
    request_id: str,
    audit: AuditContext,
) -> C19FriendRequestRead:
    return _close_friend_request(
        db,
        actor=actor,
        request_id=request_id,
        audit=audit,
        action="c19.friend_request.reject",
        expected_side="addressee",
        terminal_status="rejected",
    )


def cancel_friend_request(
    db: Session,
    *,
    actor: User,
    request_id: str,
    audit: AuditContext,
) -> C19FriendRequestRead:
    return _close_friend_request(
        db,
        actor=actor,
        request_id=request_id,
        audit=audit,
        action="c19.friend_request.cancel",
        expected_side="requester",
        terminal_status="cancelled",
    )


def list_friends(
    db: Session,
    *,
    actor: User,
    limit: int,
    offset: int,
) -> C19FriendPage:
    require_active_c19_actor(db, actor=actor)
    with without_org_data_isolation():
        rows, total = social_repository.list_friend_relationships(
            db,
            actor_user_id=actor.id,
            limit=limit,
            offset=offset,
        )
        bundles = _profile_bundles(
            db,
            user_ids=[target_user_id for _, target_user_id in rows],
        )
        items = [
            C19FriendRead(
                relationship_id=relationship.relationship_id,
                profile=profile_read_from_bundle(bundles[target_user_id]),
                established_at=relationship.established_at,
            )
            for relationship, target_user_id in rows
            if target_user_id in bundles and relationship.established_at is not None
        ]
    return C19FriendPage(
        items=items,
        count=total,
        limit=limit,
        offset=offset,
    )


def remove_friend(
    db: Session,
    *,
    actor: User,
    user_id: int,
    audit: AuditContext,
) -> C19UserChangeRead:
    require_active_c19_actor(db, actor=actor)
    _ensure_distinct(actor.id, user_id)
    _, _, pair_key = social_repository.canonical_pair(actor.id, user_id)
    with without_org_data_isolation():
        social_repository.lock_user_pair(
            db,
            user_a_id=actor.id,
            user_b_id=user_id,
        )
        relationship = social_repository.get_relationship_by_pair(
            db,
            pair_key=pair_key,
            for_update=True,
        )
        changed = relationship is not None and relationship.status == "friends"
        if changed:
            relationship.status = "removed"
            relationship.ended_at = _now()
        _write_social_audit(
            db,
            actor=actor,
            audit=audit,
            action="c19.friend.remove",
            target_type="c19_relationship",
            target_id=relationship.relationship_id if relationship else pair_key,
            details={"target_user_id": user_id, "changed": changed},
        )
        db.commit()
    return C19UserChangeRead(user_id=user_id, changed=changed)


def list_blocks(
    db: Session,
    *,
    actor: User,
    limit: int,
    offset: int,
) -> C19BlockPage:
    require_active_c19_actor(db, actor=actor)
    with without_org_data_isolation():
        records, total = social_repository.list_user_blocks(
            db,
            blocker_user_id=actor.id,
            limit=limit,
            offset=offset,
        )
        bundles = _profile_bundles(
            db,
            user_ids=[record.blocked_user_id for record in records],
        )
        items = [
            C19BlockRead(
                block_id=record.block_id,
                profile=profile_read_from_bundle(bundles[record.blocked_user_id]),
                blocked_at=record.blocked_at,
            )
            for record in records
            if record.blocked_user_id in bundles
        ]
    return C19BlockPage(
        items=items,
        count=total,
        limit=limit,
        offset=offset,
    )


def block_user(
    db: Session,
    *,
    actor: User,
    user_id: int,
    audit: AuditContext,
) -> C19BlockRead:
    require_active_c19_actor(db, actor=actor)
    _ensure_distinct(actor.id, user_id)
    _, _, pair_key = social_repository.canonical_pair(actor.id, user_id)
    with without_org_data_isolation():
        target_bundle = _require_target_bundle(db, user_id=user_id)
        social_repository.lock_user_pair(
            db,
            user_a_id=actor.id,
            user_b_id=user_id,
        )
        block = social_repository.get_user_block(
            db,
            blocker_user_id=actor.id,
            blocked_user_id=user_id,
            for_update=True,
        )
        now = _now()
        if block is None:
            candidate = C19UserBlockRecord(
                blocker_user_id=actor.id,
                blocked_user_id=user_id,
                status="active",
                is_active=True,
                blocked_at=now,
            )
            try:
                with db.begin_nested():
                    db.add(candidate)
                    db.flush()
                block = candidate
            except IntegrityError:
                block = social_repository.get_user_block(
                    db,
                    blocker_user_id=actor.id,
                    blocked_user_id=user_id,
                    for_update=True,
                )
                if block is None:
                    raise C19SocialConflictError(
                        "Block state could not be created."
                    ) from None
        if not block.is_active:
            block.status = "active"
            block.is_active = True
            block.blocked_at = now
            block.revoked_at = None

        relationship = social_repository.get_relationship_by_pair(
            db,
            pair_key=pair_key,
            for_update=True,
        )
        if relationship is not None and relationship.status == "friends":
            relationship.status = "removed"
            relationship.ended_at = now
        request = social_repository.get_friend_request_by_pair(
            db,
            pair_key=pair_key,
            for_update=True,
        )
        if request is not None and request.status == "pending":
            request.status = "cancelled"
            request.responded_at = now

        db.flush()
        db.refresh(block)
        response = C19BlockRead(
            block_id=block.block_id,
            profile=profile_read_from_bundle(target_bundle),
            blocked_at=block.blocked_at,
        )
        _write_social_audit(
            db,
            actor=actor,
            audit=audit,
            action="c19.block.create",
            target_type="c19_user_block",
            target_id=block.block_id,
            details={"target_user_id": user_id, "status": "active"},
        )
        db.commit()
    return response


def unblock_user(
    db: Session,
    *,
    actor: User,
    user_id: int,
    audit: AuditContext,
) -> C19UserChangeRead:
    require_active_c19_actor(db, actor=actor)
    _ensure_distinct(actor.id, user_id)
    with without_org_data_isolation():
        social_repository.lock_user_pair(
            db,
            user_a_id=actor.id,
            user_b_id=user_id,
        )
        block = social_repository.get_user_block(
            db,
            blocker_user_id=actor.id,
            blocked_user_id=user_id,
            for_update=True,
        )
        changed = block is not None and block.is_active
        if changed:
            block.status = "revoked"
            block.is_active = False
            block.revoked_at = _now()
        _write_social_audit(
            db,
            actor=actor,
            audit=audit,
            action="c19.block.revoke",
            target_type="c19_user_block",
            target_id=block.block_id if block else f"{actor.id}:{user_id}",
            details={"target_user_id": user_id, "changed": changed},
        )
        db.commit()
    return C19UserChangeRead(user_id=user_id, changed=changed)


__all__ = [
    "C19SocialConflictError",
    "C19SocialError",
    "C19SocialInteractionUnavailableError",
    "C19SocialNotFoundError",
    "C19SocialSelfTargetError",
    "accept_friend_request",
    "block_user",
    "cancel_friend_request",
    "create_friend_request",
    "list_blocks",
    "list_friend_requests",
    "list_friends",
    "reject_friend_request",
    "remove_friend",
    "unblock_user",
]
