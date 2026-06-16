from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.auth_session import AuthSession
from backend.app.models.contact_identity import ContactIdentityRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.conversation import ConversationCreateRequest
from backend.app.schemas.cross_org_communication import (
    CROSS_ORG_SYSTEM_BEHAVIOR_DIAGRAM,
    CrossOrgCheckRequest,
    get_cross_org_api_design,
    get_cross_org_communication_completion_status,
    get_cross_org_communication_logic,
    get_cross_org_conversation_rules,
    get_cross_org_integration_model,
    get_cross_org_message_flow_rules,
    get_cross_org_security_boundary,
    get_default_cross_org_policy,
)
from backend.app.schemas.message import MessageSendRequest
from backend.app.schemas.module_binding import GLOBAL_MODULE_BOUND_ORG, ModuleBinding
from backend.app.schemas.org_membership import generate_membership_id
from backend.app.schemas.organization import generate_org_id
from backend.app.services import module_binding_service as c18d_binding
from backend.app.services.conversation_service import (
    create_or_get_conversation,
    reset_conversation_registry_for_tests,
)
from backend.app.services.cross_org_communication import (
    can_communicate,
    send_message_after_cross_org_check,
)
from backend.app.services.event_collector import DEFAULT_EVENT_EMITTER


@pytest.fixture(autouse=True)
def c19e_state() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    c18d_binding.reset_module_binding_registry()
    reset_conversation_registry_for_tests()
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
    reset_conversation_registry_for_tests()
    DEFAULT_EVENT_EMITTER.clear()
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(AuthSession))
        db.execute(delete(User))
        db.commit()


def _create_user(db, *, username: str | None = None, role: str = "operator") -> User:
    user = User(
        username=username or f"c19e_user_{uuid4().hex}",
        password_hash="test-only-password-hash",
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
    with c18d_binding._MODULE_BINDINGS_LOCK:
        c18d_binding._MODULE_BINDINGS["C19E"] = ModuleBinding(
            module_id="C19E",
            bound_orgs=[GLOBAL_MODULE_BOUND_ORG],
            mode="global",
            enabled=False,
        )


def test_c19e_design_outputs_match_required_contract() -> None:
    policy = get_default_cross_org_policy()
    logic = get_cross_org_communication_logic()
    conversation_rules = get_cross_org_conversation_rules()
    flow_rules = get_cross_org_message_flow_rules()
    api = get_cross_org_api_design()
    security = get_cross_org_security_boundary()
    integration = get_cross_org_integration_model()
    completion = get_cross_org_communication_completion_status()

    assert policy.mode == "open"
    assert policy.rules.allow_cross_org_chat is True
    assert policy.rules.require_permission is True
    assert policy.rules.require_mutual_approval is False

    assert logic.same_org_rule == "sender.org_id == receiver.org_id -> ALLOW"
    assert logic.c18f_module_id == "C19E"
    assert logic.c18f_action == "read"

    assert conversation_rules.c19d_direct_conversation_can_cross_org is True
    assert conversation_rules.required_marker == (
        "conversation.cross_org = True when orgs differ"
    )
    assert conversation_rules.modifies_c19d_schema is False

    assert flow_rules.sender_org_id_recorded is True
    assert flow_rules.receiver_org_id_recorded is True
    assert flow_rules.c18g_data_isolation_enforced is True
    assert flow_rules.c17_trace_records_cross_org_behavior is True
    assert flow_rules.persistence_migration_executed is False

    routes = {(endpoint.method, endpoint.path) for endpoint in api.endpoints}
    assert routes == {
        ("POST", "/comm/cross-org/check"),
        ("POST", "/messages/send"),
    }
    assert api.public_api_exposure_allowed is False
    assert api.websocket_implemented is False

    assert security.no_org_bypass is True
    assert security.cross_org_requires_c18f is True
    assert security.data_scoped_by_c18g is True
    assert security.identity_verified_by_c19a is True
    assert security.sender_must_match_authenticated_actor is True
    assert security.modifies_c18_system is False
    assert security.modifies_c19a_to_c19d is False

    assert integration.c18c_org_membership_source == "org_memberships"
    assert integration.c18f_permission_source == "permission_isolation.check_permission"
    assert integration.c18g_data_isolation_source == (
        "OrgDataIsolation middleware/session hooks"
    )
    assert integration.c19a_identity_source == "contact_identities"
    assert integration.c19d_conversation_source == "conversation_service"

    assert completion.completion_status == "complete"
    assert completion.ui_implemented is False
    assert completion.websocket_implemented is False
    assert completion.group_chat_implemented is False
    assert completion.migration_executed is False

    assert "CrossOrgPolicy(mode=open by default)" in CROSS_ORG_SYSTEM_BEHAVIOR_DIAGRAM
    assert "conversation.cross_org=True" in CROSS_ORG_SYSTEM_BEHAVIOR_DIAGRAM


def test_c19e_allows_same_org_without_c18f_permission() -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19e_same_owner", role="owner")
        sender = _create_user(db, username="c19e_same_sender")
        receiver = _create_user(db, username="c19e_same_receiver")
        org_id = _create_org(db, owner=owner, org_name="Same Org")
        _create_membership(db, user=sender, org_id=org_id)
        _create_membership(db, user=receiver, org_id=org_id)
        _create_identity(db, user=sender, org_id=org_id, org_name="Same Org")
        _create_identity(db, user=receiver, org_id=org_id, org_name="Same Org")
        db.commit()

        decision = can_communicate(
            db,
            payload=CrossOrgCheckRequest(
                sender_user_id=str(sender.id),
                receiver_user_id=str(receiver.id),
            ),
            actor=sender,
        )

    assert decision.allowed is True
    assert decision.cross_org is False
    assert decision.c18f_permission_checked is False
    assert decision.sender is not None
    assert decision.sender.org_id == org_id
    assert any(
        event.event_type == "comm.cross_org.check"
        and event.payload["allowed"] is True
        for event in DEFAULT_EVENT_EMITTER.snapshot()
    )


def test_c19e_cross_org_open_policy_requires_c18f() -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19e_cross_owner", role="owner")
        sender = _create_user(db, username="c19e_cross_sender")
        receiver = _create_user(db, username="c19e_cross_receiver")
        org_a = _create_org(db, owner=owner, org_name="Org A")
        org_b = _create_org(db, owner=owner, org_name="Org B")
        _create_membership(db, user=sender, org_id=org_a)
        _create_membership(db, user=receiver, org_id=org_b)
        _create_identity(db, user=sender, org_id=org_a, org_name="Org A")
        _create_identity(db, user=receiver, org_id=org_b, org_name="Org B")
        db.commit()

        _disable_c19e_boundary()
        denied = can_communicate(
            db,
            payload=CrossOrgCheckRequest(
                sender_user_id=str(sender.id),
                receiver_user_id=str(receiver.id),
            ),
            actor=sender,
        )

        c18d_binding.reset_module_binding_registry()
        allowed = can_communicate(
            db,
            payload=CrossOrgCheckRequest(
                sender_user_id=str(sender.id),
                receiver_user_id=str(receiver.id),
            ),
            actor=sender,
        )

    assert denied.denied is True
    assert denied.denial_code == "c19e_c18f_permission_denied"
    assert denied.c18f_permission_checked is True
    assert denied.c18f_permission_decision is not None
    assert denied.c18f_permission_decision.denied is True

    assert allowed.allowed is True
    assert allowed.cross_org is True
    assert allowed.c18f_permission_checked is True
    assert allowed.c18f_permission_decision is not None
    assert allowed.c18f_permission_decision.allowed is True
    assert allowed.sender is not None
    assert allowed.receiver is not None
    assert allowed.sender.org_id == org_a
    assert allowed.receiver.org_id == org_b
    assert allowed.c18g_scope.sender_org_id == org_a
    assert allowed.c18g_scope.receiver_org_id == org_b


def test_c19e_rejects_sender_actor_mismatch_without_org_probe() -> None:
    with SessionLocal() as db:
        actor = _create_user(db, username="c19e_actor")
        other = _create_user(db, username="c19e_other")
        receiver = _create_user(db, username="c19e_receiver")
        db.commit()

        decision = can_communicate(
            db,
            payload=CrossOrgCheckRequest(
                sender_user_id=str(other.id),
                receiver_user_id=str(receiver.id),
            ),
            actor=actor,
        )

    assert decision.denied is True
    assert decision.denial_code == "c19e_sender_must_match_actor"
    assert decision.c19a_identity_checked is False
    assert decision.c18c_membership_checked is False


def test_c19e_message_send_marks_cross_org_conversation_and_records_orgs() -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19e_send_owner", role="owner")
        sender = _create_user(db, username="c19e_send_sender")
        receiver = _create_user(db, username="c19e_send_receiver")
        org_a = _create_org(db, owner=owner, org_name="Send Org A")
        org_b = _create_org(db, owner=owner, org_name="Send Org B")
        _create_membership(db, user=sender, org_id=org_a)
        _create_membership(db, user=receiver, org_id=org_b)
        _create_identity(db, user=sender, org_id=org_a, org_name="Send Org A")
        _create_identity(db, user=receiver, org_id=org_b, org_name="Send Org B")
        db.commit()

        conversation = create_or_get_conversation(
            db,
            payload=ConversationCreateRequest(
                participants=[str(sender.id), str(receiver.id)],
            ),
            actor=sender,
        )
        decision = send_message_after_cross_org_check(
            db,
            payload=MessageSendRequest(
                from_user_id=str(sender.id),
                to_user_id=str(receiver.id),
                conversation_id=conversation.conversation_id,
                content_type="text",
                content="hello across orgs",
            ),
            actor=sender,
        )

    assert decision.allowed is True
    assert decision.communication_decision.cross_org is True
    assert decision.conversation is not None
    assert decision.conversation.cross_org is True
    assert decision.conversation.conversation_cross_org_field == (
        "conversation.cross_org"
    )
    assert decision.conversation.conversation_cross_org_value is True
    assert decision.message is not None
    assert decision.message.sender_org_id == org_a
    assert decision.message.receiver_org_id == org_b
    assert decision.message.cross_org is True
    assert decision.message.persistence_implemented is False
    assert any(
        event.event_type == "comm.message.send"
        and event.payload["cross_org"] is True
        for event in DEFAULT_EVENT_EMITTER.snapshot()
    )


def test_c19e_routes_are_registered_as_internal_app_routes() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/cross-org" in route.path or "/messages/send" in route.path
    }

    assert ("/api/app/comm/cross-org/check", ("POST",)) in routes
    assert ("/api/app/messages/send", ("POST",)) in routes
    assert not any(path.startswith("/api/public/comm") for path, _ in routes)
    assert not any(path.startswith("/api/control-plane/comm") for path, _ in routes)
