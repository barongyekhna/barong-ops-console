from __future__ import annotations

from threading import RLock

from sqlalchemy.orm import Session

from ..models.user import User
from ..schemas.cross_org_communication import CrossOrgCheckRequest, CrossOrgDecision
from ..schemas.messaging_permission import (
    FriendActionRequest,
    FriendRequest,
    FriendRequestCreateRequest,
    FriendRequestStatus,
    FriendStatus,
    MessagingFeature,
    MessagingPermissionCheckRequest,
    MessagingPermissionDecision,
    build_messaging_permission,
    evaluate_messaging_permission,
)
from .auth_service import AuditContext
from .cross_org_communication import can_communicate
from .event_collector import emit_event


class MessagingPermissionError(ValueError):
    pass


class MessagingPermissionDeniedError(PermissionError):
    def __init__(self, decision: MessagingPermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class FriendRequestError(ValueError):
    pass


class FriendRequestDeniedError(PermissionError):
    pass


class FriendRequestNotFoundError(FriendRequestError):
    pass


class FriendRequestConflictError(FriendRequestError):
    pass


_FRIEND_REQUESTS: dict[tuple[str, str], FriendRequest] = {}
_FRIEND_REQUESTS_LOCK = RLock()


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _ensure_active_actor(actor: User) -> None:
    if not actor.is_active:
        raise FriendRequestDeniedError("Friend operations require active user.")


def _normalize_user_id(value: str | int, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise MessagingPermissionError(f"{field_name} must not be empty.")
    return normalized


def _request_sort_key(request: FriendRequest) -> tuple[str, str, str]:
    return (
        request.created_at.isoformat(),
        request.from_user_id,
        request.to_user_id,
    )


def _relationship_requests(
    *,
    user_id: str,
    target_user_id: str,
) -> tuple[FriendRequest | None, FriendRequest | None]:
    return (
        _FRIEND_REQUESTS.get((user_id, target_user_id)),
        _FRIEND_REQUESTS.get((target_user_id, user_id)),
    )


def _friend_status_from_requests(
    requests: tuple[FriendRequest | None, FriendRequest | None],
) -> FriendStatus:
    statuses = [request.status for request in requests if request is not None]
    if FriendRequestStatus.ACCEPTED in statuses:
        return FriendStatus.ACCEPTED
    if FriendRequestStatus.REJECTED in statuses:
        return FriendStatus.REJECTED
    if FriendRequestStatus.PENDING in statuses:
        return FriendStatus.PENDING
    return FriendStatus.NONE


def get_friend_status(
    *,
    user_id: str | int,
    target_user_id: str | int,
) -> FriendStatus:
    normalized_user_id = _normalize_user_id(user_id, field_name="user_id")
    normalized_target_user_id = _normalize_user_id(
        target_user_id,
        field_name="target_user_id",
    )
    with _FRIEND_REQUESTS_LOCK:
        return _friend_status_from_requests(
            _relationship_requests(
                user_id=normalized_user_id,
                target_user_id=normalized_target_user_id,
            )
        )


def _emit_friend_event(
    *,
    event_type: str,
    action: str,
    request: FriendRequest,
    actor: User,
    status: str = "success",
) -> None:
    emit_event(
        event_type=event_type,
        module="system",
        action=action,
        source="backend",
        status=status,
        user_id=_actor_user_id(actor),
        payload={
            "from_user_id": request.from_user_id,
            "to_user_id": request.to_user_id,
            "friend_status": request.status,
            "user_to_user_scoped": True,
            "migration_executed": False,
        },
    )


def _emit_permission_decision(
    *,
    decision: MessagingPermissionDecision,
    actor: User,
) -> None:
    emit_event(
        event_type="comm.messaging_permission.check",
        module="system",
        action="c19f.messaging_permission.check",
        source="backend",
        status="success" if decision.allowed else "failed",
        user_id=_actor_user_id(actor),
        payload={
            "sender_user_id": decision.sender_user_id,
            "receiver_user_id": decision.receiver_user_id,
            "content_type": decision.content_type,
            "friend_status": decision.permission.friend_status,
            "can_chat": decision.permission.can_chat,
            "unlocked_features": decision.permission.unlocked_features,
            "same_org": decision.same_org,
            "allowed": decision.allowed,
            "denial_code": decision.denial_code,
            "c19e_gate_checked": decision.c19e_gate_checked,
            "c19e_denial_code": (
                decision.c19e_decision.denial_code
                if decision.c19e_decision is not None
                else None
            ),
            "c18g_data_isolation_boundary_preserved": True,
            "media_payload_implemented": False,
        },
    )


def _build_c19e_denied_decision(
    *,
    payload: MessagingPermissionCheckRequest,
    communication_decision: CrossOrgDecision,
) -> MessagingPermissionDecision:
    permission = build_messaging_permission(
        user_id=payload.sender_user_id,
        target_user_id=payload.receiver_user_id,
        friend_status=FriendStatus.NONE,
        can_chat=False,
    )
    return MessagingPermissionDecision(
        sender_user_id=payload.sender_user_id,
        receiver_user_id=payload.receiver_user_id,
        content_type=payload.content_type,
        permission=permission,
        same_org=(not communication_decision.cross_org)
        if communication_decision.sender is not None
        and communication_decision.receiver is not None
        else None,
        allowed=False,
        denied=True,
        denial_code="c19f_c19e_gate_denied",
        reason="Messaging permission denied because C19E denied communication.",
        c19e_gate_checked=True,
        c19e_decision=communication_decision,
    )


def can_send_message(
    db: Session,
    *,
    sender_user_id: str | int,
    receiver_user_id: str | int,
    content_type: MessagingFeature | str,
    actor: User,
    audit: AuditContext | None = None,
) -> MessagingPermissionDecision:
    payload = MessagingPermissionCheckRequest(
        sender_user_id=str(sender_user_id),
        receiver_user_id=str(receiver_user_id),
        content_type=content_type,
    )
    communication_decision = can_communicate(
        db,
        payload=CrossOrgCheckRequest(
            sender_user_id=payload.sender_user_id,
            receiver_user_id=payload.receiver_user_id,
        ),
        actor=actor,
        audit=audit,
    )

    if communication_decision.denied:
        decision = _build_c19e_denied_decision(
            payload=payload,
            communication_decision=communication_decision,
        )
        _emit_permission_decision(decision=decision, actor=actor)
        return decision

    friend_status = get_friend_status(
        user_id=payload.sender_user_id,
        target_user_id=payload.receiver_user_id,
    )
    decision = evaluate_messaging_permission(
        sender_user_id=payload.sender_user_id,
        receiver_user_id=payload.receiver_user_id,
        content_type=payload.content_type,
        same_org=not communication_decision.cross_org,
        friend_status=friend_status,
        c19e_decision=communication_decision,
    )
    _emit_permission_decision(decision=decision, actor=actor)
    return decision


def check_message_permission(
    db: Session,
    *,
    payload: MessagingPermissionCheckRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> MessagingPermissionDecision:
    return can_send_message(
        db,
        sender_user_id=payload.sender_user_id,
        receiver_user_id=payload.receiver_user_id,
        content_type=payload.content_type,
        actor=actor,
        audit=audit,
    )


def _ensure_relationship_can_be_requested(
    *,
    from_user_id: str,
    to_user_id: str,
) -> None:
    if from_user_id == to_user_id:
        raise FriendRequestConflictError("Friend request users must be distinct.")

    status = _friend_status_from_requests(
        _relationship_requests(user_id=from_user_id, target_user_id=to_user_id)
    )
    if status == FriendStatus.ACCEPTED:
        raise FriendRequestConflictError("Friend relationship is already accepted.")
    if status == FriendStatus.REJECTED:
        raise FriendRequestConflictError(
            "Rejected friend relationship blocks new requests."
        )


def create_friend_request(
    db: Session,
    *,
    payload: FriendRequestCreateRequest,
    actor: User,
    audit: AuditContext | None = None,
) -> FriendRequest:
    _ensure_active_actor(actor)
    from_user_id = _actor_user_id(actor)
    to_user_id = payload.to_user_id

    communication_decision = can_communicate(
        db,
        payload=CrossOrgCheckRequest(
            sender_user_id=from_user_id,
            receiver_user_id=to_user_id,
        ),
        actor=actor,
        audit=audit,
    )
    if communication_decision.denied:
        raise FriendRequestDeniedError(
            "Friend request denied because C19E denied communication."
        )

    with _FRIEND_REQUESTS_LOCK:
        _ensure_relationship_can_be_requested(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
        )
        existing = _FRIEND_REQUESTS.get((from_user_id, to_user_id))
        if existing is not None:
            return existing

        reverse = _FRIEND_REQUESTS.get((to_user_id, from_user_id))
        if reverse is not None:
            return reverse

        request = FriendRequest(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            status=FriendRequestStatus.PENDING,
        )
        _FRIEND_REQUESTS[(from_user_id, to_user_id)] = request

    _emit_friend_event(
        event_type="comm.friend.request",
        action="c19f.friend.request",
        request=request,
        actor=actor,
    )
    return request


def accept_friend_request(
    *,
    payload: FriendActionRequest,
    actor: User,
) -> FriendRequest:
    _ensure_active_actor(actor)
    to_user_id = _actor_user_id(actor)
    from_user_id = payload.from_user_id

    with _FRIEND_REQUESTS_LOCK:
        existing = _FRIEND_REQUESTS.get((from_user_id, to_user_id))
        if existing is None:
            raise FriendRequestNotFoundError("Friend request not found.")
        if existing.status == FriendRequestStatus.REJECTED:
            raise FriendRequestConflictError(
                "Rejected friend request cannot be accepted."
            )
        if existing.status == FriendRequestStatus.ACCEPTED:
            accepted = existing
        else:
            accepted = FriendRequest(
                from_user_id=existing.from_user_id,
                to_user_id=existing.to_user_id,
                status=FriendRequestStatus.ACCEPTED,
                created_at=existing.created_at,
            )
            _FRIEND_REQUESTS[(from_user_id, to_user_id)] = accepted

    _emit_friend_event(
        event_type="comm.friend.accept",
        action="c19f.friend.accept",
        request=accepted,
        actor=actor,
    )
    return accepted


def reject_friend_request(
    *,
    payload: FriendActionRequest,
    actor: User,
) -> FriendRequest:
    _ensure_active_actor(actor)
    to_user_id = _actor_user_id(actor)
    from_user_id = payload.from_user_id

    with _FRIEND_REQUESTS_LOCK:
        existing = _FRIEND_REQUESTS.get((from_user_id, to_user_id))
        if existing is None:
            raise FriendRequestNotFoundError("Friend request not found.")
        if existing.status == FriendRequestStatus.ACCEPTED:
            raise FriendRequestConflictError(
                "Accepted friend request cannot be rejected."
            )
        if existing.status == FriendRequestStatus.REJECTED:
            rejected = existing
        else:
            rejected = FriendRequest(
                from_user_id=existing.from_user_id,
                to_user_id=existing.to_user_id,
                status=FriendRequestStatus.REJECTED,
                created_at=existing.created_at,
            )
            _FRIEND_REQUESTS[(from_user_id, to_user_id)] = rejected

    _emit_friend_event(
        event_type="comm.friend.reject",
        action="c19f.friend.reject",
        request=rejected,
        actor=actor,
    )
    return rejected


def list_friend_requests_for_actor(*, actor: User) -> list[FriendRequest]:
    _ensure_active_actor(actor)
    actor_user_id = _actor_user_id(actor)
    with _FRIEND_REQUESTS_LOCK:
        requests = [
            request
            for request in _FRIEND_REQUESTS.values()
            if actor_user_id in (request.from_user_id, request.to_user_id)
        ]
    return sorted(requests, key=_request_sort_key, reverse=True)


def reset_messaging_permission_state_for_tests() -> None:
    with _FRIEND_REQUESTS_LOCK:
        _FRIEND_REQUESTS.clear()


__all__ = [
    "FriendRequestConflictError",
    "FriendRequestDeniedError",
    "FriendRequestNotFoundError",
    "MessagingPermissionDeniedError",
    "accept_friend_request",
    "can_send_message",
    "check_message_permission",
    "create_friend_request",
    "get_friend_status",
    "list_friend_requests_for_actor",
    "reject_friend_request",
    "reset_messaging_permission_state_for_tests",
]
