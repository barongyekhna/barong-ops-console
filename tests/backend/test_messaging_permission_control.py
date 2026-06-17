from __future__ import annotations

import re
from itertools import count
from uuid import uuid4

import pytest
from sqlalchemy import delete

from backend.app.api.routes.messages import check_permission_for_message
from backend.app.core.security import hash_password
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.auth_session import AuthSession
from backend.app.models.contact_identity import ContactIdentityRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.messaging_permission import (
    MESSAGING_PERMISSION_DATA_FLOW_DIAGRAM,
    MESSAGING_PERMISSION_SQL_SCHEMA,
    FriendActionRequest,
    FriendRequestCreateRequest,
    FriendStatus,
    MessagingPermission,
    MessagingPermissionCheckRequest,
    build_messaging_permission,
    evaluate_messaging_permission,
    get_messaging_feature_unlocking_rules,
    get_messaging_permission_api_design,
    get_messaging_permission_completion_status,
    get_messaging_permission_database_schema,
    get_messaging_permission_integration_model,
    get_messaging_permission_security_boundary,
)
from backend.app.models.module_binding import ModuleBindingRecord
from backend.app.schemas.module_binding import GLOBAL_MODULE_BOUND_ORG
from backend.app.schemas.org_membership import generate_membership_id
from backend.app.schemas.organization import generate_org_id
from backend.app.services import module_binding_service as c18d_binding
from backend.app.services.event_collector import DEFAULT_EVENT_EMITTER
from backend.app.services.messaging_permission import (
    accept_friend_request,
    can_send_message,
    create_friend_request,
    get_friend_status,
    reject_friend_request,
    reset_messaging_permission_state_for_tests,
)


_USER_ID_SEQUENCE = count(300_000)


class _RequestState:
    pass


class _FakeRequest:
    headers: dict[str, str] = {}
    client = None

    def __init__(self) -> None:
        self.state = _RequestState()


@pytest.fixture(autouse=True)
def c19f_state() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    c18d_binding.reset_module_binding_registry()
    reset_messaging_permission_state_for_tests()
    DEFAULT_EVENT_EMITTER.clear()
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(AuthSession))
        db.execute(delete(User))
        db.commit()
    yield
    c18d_binding.reset_module_binding_registry()
    reset_messaging_permission_state_for_tests()
    DEFAULT_EVENT_EMITTER.clear()
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(AuthSession))
        db.execute(delete(User))
        db.commit()


def _create_user(
    db,
    *,
    username: str | None = None,
    password: str = "test-only-password",
    role: str = "operator",
) -> User:
    user = User(
        id=next(_USER_ID_SEQUENCE),
        username=username or f"c19f_user_{uuid4().hex}",
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _create_org(db, *, owner: User, org_name: str) -> str:
    org_id = generate_org_id()
    db.add(
        OrganizationRecord(
            org_id=org_id,
            org_name=org_name,
            org_type="store",
            owner_user_id=str(owner.id),
            status="active",
            metadata_json={},
        )
    )
    db.flush()
    return org_id


def _create_membership(db, *, user: User, org_id: str, role: str = "member") -> None:
    db.add(
        OrgMembershipRecord(
            membership_id=generate_membership_id(),
            user_id=str(user.id),
            org_id=org_id,
            role=role,
            status="active",
        )
    )
    db.flush()


def _create_identity(db, *, user: User, org_id: str, org_name: str) -> None:
    db.add(
        ContactIdentityRecord(
            user_id=str(user.id),
            name=user.username,
            org_id=org_id,
            org_name=org_name,
            title="Operator",
            role="member",
        )
    )
    db.flush()


def _disable_c19e_boundary() -> None:
    with SessionLocal() as db:
        db.add(
            ModuleBindingRecord(
                org_id=GLOBAL_MODULE_BOUND_ORG,
                module_id="C19E",
                status="disabled",
            )
        )
        db.commit()


def test_c19f_schema_rules_and_design_outputs_match_contract() -> None:
    default_permission = MessagingPermission(
        user_id="user-1",
        target_user_id="user-2",
    )
    friend_permission = build_messaging_permission(
        user_id="user-1",
        target_user_id="user-2",
        friend_status=FriendStatus.ACCEPTED,
    )
    blocked_permission = build_messaging_permission(
        user_id="user-1",
        target_user_id="user-2",
        friend_status=FriendStatus.REJECTED,
    )
    advanced_denied = evaluate_messaging_permission(
        sender_user_id="user-1",
        receiver_user_id="user-2",
        content_type="image",
        same_org=True,
        friend_status="none",
    )
    text_allowed = evaluate_messaging_permission(
        sender_user_id="user-1",
        receiver_user_id="user-2",
        content_type="text",
        same_org=True,
        friend_status="pending",
    )

    assert default_permission.can_chat is True
    assert default_permission.friend_status == "none"
    assert default_permission.unlocked_features == ["text", "emoji"]
    assert friend_permission.unlocked_features == [
        "text",
        "emoji",
        "image",
        "file",
        "voice",
        "video",
    ]
    assert blocked_permission.can_chat is False
    assert blocked_permission.unlocked_features == []
    assert advanced_denied.denied is True
    assert advanced_denied.denial_code == "c19f_friend_required"
    assert text_allowed.allowed is True

    rules = get_messaging_feature_unlocking_rules()
    api = get_messaging_permission_api_design()
    database = get_messaging_permission_database_schema()
    integration = get_messaging_permission_integration_model()
    security = get_messaging_permission_security_boundary()
    completion = get_messaging_permission_completion_status()
    compact_sql = re.sub(r"\s+", " ", MESSAGING_PERMISSION_SQL_SCHEMA)

    assert rules.default_internal_can_chat is True
    assert rules.level_1_internal_features == ("text", "emoji")
    assert rules.level_2_friend_features == (
        "text",
        "emoji",
        "image",
        "file",
        "voice",
        "video",
    )
    assert rules.rejected_blocks_chat is True
    assert rules.owner_or_admin_bypass_allowed is False

    routes = {(endpoint.method, endpoint.path) for endpoint in api.endpoints}
    assert routes == {
        ("POST", "/friends/request"),
        ("POST", "/friends/accept"),
        ("POST", "/friends/reject"),
        ("GET", "/friends/list"),
        ("POST", "/messages/permission/check"),
    }
    assert api.public_api_exposure_allowed is False
    assert api.websocket_implemented is False
    assert api.migration_executed is False

    assert database.permission_table_name == "messaging_permissions"
    assert database.friend_request_table_name == "friend_requests"
    assert database.user_to_user_scope_unique is True
    assert database.migration_executed is False
    assert "CREATE TABLE messaging_permissions" in compact_sql
    assert "CREATE TABLE friend_requests" in compact_sql
    assert "friend_status TEXT CHECK" in compact_sql
    assert "'accepted'" in compact_sql
    assert "'rejected'" in compact_sql

    assert integration.c19a_identity_source == "contact_identities"
    assert integration.c19c_message_schema_source == (
        "MessageSendRequest and content_type"
    )
    assert integration.c19d_conversation_source == "conversation_service"
    assert integration.c19e_cross_org_gate_source == "can_communicate"
    assert integration.modifies_c19a_to_c19e is False

    assert security.permission_is_not_org_access is True
    assert security.permission_is_not_data_isolation is True
    assert security.c18g_still_applies is True
    assert security.no_friend_requirement_bypass is True
    assert security.cross_org_must_pass_c19e is True

    assert completion.completion_status == "complete"
    assert completion.ui_implemented is False
    assert completion.websocket_implemented is False
    assert completion.voice_video_implemented is False
    assert completion.migration_executed is False
    assert "same-org internal users default to can_chat=True" in (
        MESSAGING_PERMISSION_DATA_FLOW_DIAGRAM
    )
    assert "C18G data isolation remains separate" in (
        MESSAGING_PERMISSION_DATA_FLOW_DIAGRAM
    )


def test_c19f_default_internal_chat_and_friend_unlocking() -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19f_unlock_owner", role="owner")
        sender = _create_user(db, username="c19f_unlock_sender")
        receiver = _create_user(db, username="c19f_unlock_receiver")
        org_id = _create_org(db, owner=owner, org_name="Unlock Org")
        _create_membership(db, user=sender, org_id=org_id)
        _create_membership(db, user=receiver, org_id=org_id)
        _create_identity(db, user=sender, org_id=org_id, org_name="Unlock Org")
        _create_identity(db, user=receiver, org_id=org_id, org_name="Unlock Org")
        db.commit()

        text_decision = can_send_message(
            db,
            sender_user_id=str(sender.id),
            receiver_user_id=str(receiver.id),
            content_type="text",
            actor=sender,
        )
        image_denied = can_send_message(
            db,
            sender_user_id=str(sender.id),
            receiver_user_id=str(receiver.id),
            content_type="image",
            actor=sender,
        )
        friend_request = create_friend_request(
            db,
            payload=FriendRequestCreateRequest(to_user_id=str(receiver.id)),
            actor=sender,
        )
        voice_pending = can_send_message(
            db,
            sender_user_id=str(sender.id),
            receiver_user_id=str(receiver.id),
            content_type="voice",
            actor=sender,
        )
        accepted = accept_friend_request(
            payload=FriendActionRequest(from_user_id=str(sender.id)),
            actor=receiver,
        )
        video_allowed = can_send_message(
            db,
            sender_user_id=str(sender.id),
            receiver_user_id=str(receiver.id),
            content_type="video",
            actor=sender,
        )

    assert text_decision.allowed is True
    assert text_decision.permission.can_chat is True
    assert text_decision.permission.friend_status == "none"
    assert text_decision.permission.unlocked_features == ["text", "emoji"]
    assert image_denied.denied is True
    assert image_denied.denial_code == "c19f_friend_required"
    assert friend_request.status == "pending"
    assert voice_pending.denied is True
    assert voice_pending.permission.friend_status == "pending"
    assert accepted.status == "accepted"
    assert get_friend_status(
        user_id=str(sender.id),
        target_user_id=str(receiver.id),
    ) == FriendStatus.ACCEPTED
    assert video_allowed.allowed is True
    assert video_allowed.permission.unlocked_features == [
        "text",
        "emoji",
        "image",
        "file",
        "voice",
        "video",
    ]
    assert any(
        event.event_type == "comm.messaging_permission.check"
        and event.payload["content_type"] == "video"
        and event.payload["allowed"] is True
        for event in DEFAULT_EVENT_EMITTER.snapshot()
    )


def test_c19f_rejected_friend_request_blocks_chat() -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19f_reject_owner", role="owner")
        sender = _create_user(db, username="c19f_reject_sender")
        receiver = _create_user(db, username="c19f_reject_receiver")
        org_id = _create_org(db, owner=owner, org_name="Reject Org")
        _create_membership(db, user=sender, org_id=org_id)
        _create_membership(db, user=receiver, org_id=org_id)
        _create_identity(db, user=sender, org_id=org_id, org_name="Reject Org")
        _create_identity(db, user=receiver, org_id=org_id, org_name="Reject Org")
        db.commit()

        create_friend_request(
            db,
            payload=FriendRequestCreateRequest(to_user_id=str(receiver.id)),
            actor=sender,
        )
        rejected = reject_friend_request(
            payload=FriendActionRequest(from_user_id=str(sender.id)),
            actor=receiver,
        )
        decision = can_send_message(
            db,
            sender_user_id=str(sender.id),
            receiver_user_id=str(receiver.id),
            content_type="text",
            actor=sender,
        )

    assert rejected.status == "rejected"
    assert decision.denied is True
    assert decision.denial_code == "c19f_friend_rejected"
    assert decision.permission.can_chat is False
    assert decision.permission.unlocked_features == []


def test_c19f_cross_org_messages_must_pass_c19e_gate() -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19f_cross_owner", role="owner")
        sender = _create_user(db, username="c19f_cross_sender")
        receiver = _create_user(db, username="c19f_cross_receiver")
        org_a = _create_org(db, owner=owner, org_name="Cross Org A")
        org_b = _create_org(db, owner=owner, org_name="Cross Org B")
        _create_membership(db, user=sender, org_id=org_a)
        _create_membership(db, user=receiver, org_id=org_b)
        _create_identity(db, user=sender, org_id=org_a, org_name="Cross Org A")
        _create_identity(db, user=receiver, org_id=org_b, org_name="Cross Org B")
        db.commit()

        _disable_c19e_boundary()
        denied = can_send_message(
            db,
            sender_user_id=str(sender.id),
            receiver_user_id=str(receiver.id),
            content_type="text",
            actor=sender,
        )

        c18d_binding.reset_module_binding_registry()
        allowed = can_send_message(
            db,
            sender_user_id=str(sender.id),
            receiver_user_id=str(receiver.id),
            content_type="emoji",
            actor=sender,
        )

    assert denied.denied is True
    assert denied.denial_code == "c19f_c19e_gate_denied"
    assert denied.c19e_gate_checked is True
    assert denied.c19e_decision is not None
    assert denied.c19e_decision.denied is True
    assert denied.permission.can_chat is False

    assert allowed.allowed is True
    assert allowed.same_org is False
    assert allowed.c19e_gate_checked is True
    assert allowed.c19e_decision is not None
    assert allowed.c19e_decision.allowed is True
    assert allowed.permission.unlocked_features == ["text", "emoji"]


def test_c19f_routes_are_registered_as_internal_app_routes() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/friends" in route.path or "/messages/permission/check" in route.path
    }

    assert ("/api/app/friends/request", ("POST",)) in routes
    assert ("/api/app/friends/accept", ("POST",)) in routes
    assert ("/api/app/friends/reject", ("POST",)) in routes
    assert ("/api/app/friends/list", ("GET",)) in routes
    assert ("/api/app/messages/permission/check", ("POST",)) in routes
    assert not any(path.startswith("/api/public/friends") for path, _ in routes)
    assert not any(path.startswith("/api/control-plane/friends") for path, _ in routes)


def test_c19f_permission_check_route_returns_default_internal_features() -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19f_api_owner", role="owner")
        sender = _create_user(db, username="c19f_api_sender")
        receiver = _create_user(db, username="c19f_api_receiver")
        org_id = _create_org(db, owner=owner, org_name="API Org")
        _create_membership(db, user=sender, org_id=org_id)
        _create_membership(db, user=receiver, org_id=org_id)
        _create_identity(db, user=sender, org_id=org_id, org_name="API Org")
        _create_identity(db, user=receiver, org_id=org_id, org_name="API Org")
        db.commit()

        decision = check_permission_for_message(
            payload=MessagingPermissionCheckRequest(
                sender_user_id=str(sender.id),
                receiver_user_id=str(receiver.id),
                content_type="file",
            ),
            request=_FakeRequest(),
            db=db,
            actor=sender,
        )

    assert decision.allowed is False
    assert decision.denial_code == "c19f_friend_required"
    assert decision.permission.can_chat is True
    assert decision.permission.friend_status == "none"
    assert decision.permission.unlocked_features == ["text", "emoji"]
