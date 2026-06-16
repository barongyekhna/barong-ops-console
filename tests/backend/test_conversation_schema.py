from __future__ import annotations

from itertools import count
import re

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete

from backend.app.api.routes.conversations import (
    create_conversation as route_create_conversation,
    get_conversation as route_get_conversation,
    list_user_conversations as route_list_user_conversations,
)
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.contact_identity import ContactIdentityRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.conversation import (
    CONVERSATION_DATA_FLOW_DIAGRAM,
    CONVERSATION_SQL_SCHEMA,
    Conversation,
    ConversationCreateRequest,
    generate_direct_conversation_id,
    get_conversation_api_design,
    get_conversation_completion_status,
    get_conversation_database_schema,
    get_conversation_integration_model,
    get_conversation_security_model,
    get_conversation_uniqueness_strategy,
    get_direct_conversation_generation_logic,
    get_group_conversation_reserved_design,
)
from backend.app.schemas.message import Message
from backend.app.schemas.org_membership import generate_membership_id
from backend.app.schemas.organization import generate_org_id
from backend.app.services.conversation_service import (
    ConversationAccessDeniedError,
    ConversationParticipantNotFoundError,
    GroupConversationReservedError,
    create_or_get_conversation,
    list_user_conversations_for_actor,
    reset_conversation_registry_for_tests,
)


_USER_ID_SEQUENCE = count(100_000)


@pytest.fixture
def conversation_tables() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    reset_conversation_registry_for_tests()
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(User))
        db.commit()
    yield
    reset_conversation_registry_for_tests()
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(User))
        db.commit()


def _create_user(db, *, username: str, role: str = "operator") -> User:
    user = User(
        id=next(_USER_ID_SEQUENCE),
        username=username,
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


def _create_membership(
    db,
    *,
    user: User,
    org_id: str,
    role: str,
    status: str = "active",
) -> None:
    db.add(
        OrgMembershipRecord(
            membership_id=generate_membership_id(),
            user_id=str(user.id),
            org_id=org_id,
            role=role,
            status=status,
        )
    )
    db.flush()


def _create_identity(
    db,
    *,
    user: User,
    org_id: str,
    org_name: str,
    title: str,
    role: str = "member",
) -> None:
    db.add(
        ContactIdentityRecord(
            user_id=str(user.id),
            name=user.username,
            org_id=org_id,
            org_name=org_name,
            title=title,
            role=role,
        )
    )
    db.flush()


def test_c19d_direct_conversation_id_is_stable_for_sorted_pair() -> None:
    conversation_id = generate_direct_conversation_id("user-b", "user-a")
    reversed_id = generate_direct_conversation_id(" user-a ", " user-b ")

    assert conversation_id == reversed_id
    assert re.fullmatch(r"conv_[0-9a-f]{32}", conversation_id)

    conversation = Conversation(
        type="direct",
        participants=[" user-b ", " user-a "],
    )

    assert conversation.conversation_id == conversation_id
    assert conversation.type == "direct"
    assert conversation.participants == ["user-a", "user-b"]

    with pytest.raises(ValidationError):
        Conversation(
            type="direct",
            participants=["user-a", "user-b", "user-c"],
        )

    with pytest.raises(ValidationError):
        Conversation(
            conversation_id="conv_" + ("0" * 32),
            type="direct",
            participants=["user-a", "user-b"],
        )


def test_c19d_group_conversation_is_schema_only_reserved() -> None:
    request = ConversationCreateRequest(
        type="group",
        participants=["user-a", "user-b", "user-c"],
    )
    conversation = Conversation(
        type="group",
        participants=request.participants,
    )
    reserved = get_group_conversation_reserved_design()

    assert conversation.type == "group"
    assert len(conversation.participants) == 3
    assert reserved.schema_validation_defined is True
    assert reserved.creation_logic_implemented is False
    assert reserved.api_expansion_implemented is False
    assert reserved.websocket_implemented is False

    with pytest.raises(ValidationError):
        ConversationCreateRequest(type="group", participants=["user-a", "user-b"])


def test_c19d_design_outputs_match_required_contract() -> None:
    generation = get_direct_conversation_generation_logic()
    uniqueness = get_conversation_uniqueness_strategy()
    database = get_conversation_database_schema()
    api = get_conversation_api_design()
    integration = get_conversation_integration_model()
    security = get_conversation_security_model()
    completion = get_conversation_completion_status()

    assert generation.same_pair_reuses_same_conversation is True
    assert generation.participant_order_changes_id is False
    assert generation.group_generation_logic_implemented is False

    assert uniqueness.direct_conversation_id_is_deterministic is True
    assert uniqueness.direct_pair_duplicate_creation_allowed is False
    assert uniqueness.persistence_unique_key == "conversation_id"
    assert uniqueness.current_runtime_storage == (
        "process registry; no migration executed"
    )

    compact_sql = re.sub(r"\s+", " ", CONVERSATION_SQL_SCHEMA)
    assert database.table_name == "conversations"
    assert database.primary_key == "conversation_id"
    assert database.type_check_values == ("direct", "group")
    assert database.direct_conversation_id_is_unique is True
    assert database.group_logic_implemented is False
    assert database.migration_executed is False
    assert "CREATE TABLE conversations" in CONVERSATION_SQL_SCHEMA
    assert "conversation_id TEXT PRIMARY KEY" in compact_sql
    assert "type TEXT CHECK" in compact_sql
    assert "'direct'" in compact_sql
    assert "'group'" in compact_sql
    assert "participants TEXT" in compact_sql

    routes = {(endpoint.method, endpoint.path) for endpoint in api.endpoints}
    assert routes == {
        ("POST", "/conversations/create"),
        ("GET", "/conversations/{conversation_id}"),
        ("GET", "/conversations/user/{user_id}"),
    }
    assert api.public_api_exposure_allowed is False
    assert api.websocket_implemented is False
    assert api.group_api_expansion_implemented is False
    assert api.migration_executed is False

    assert integration.c19a_identity_validation_source == "contact_identities"
    assert integration.c19b_contact_resolution_source == "GlobalContactDirectory"
    assert integration.c19c_message_binding_rule == (
        "Message.conversation_id must reference Conversation.conversation_id"
    )
    assert integration.c18c_org_membership_source == "org_memberships"
    assert integration.modifies_c19a is False
    assert integration.modifies_c19b is False
    assert integration.modifies_c19c is False
    assert integration.modifies_c18_system is False

    assert security.internal_only is True
    assert security.participants_must_exist_in_c19b_directory is True
    assert security.participants_must_have_c19a_identity is True
    assert security.participants_must_have_active_c18c_membership is True
    assert security.cross_org_leakage_allowed is False

    assert completion.conversation_schema_defined is True
    assert completion.direct_generation_logic_defined is True
    assert completion.uniqueness_strategy_defined is True
    assert completion.database_schema_defined is True
    assert completion.c19b_contact_resolution_integrated is True
    assert completion.c19c_message_binding_integrated is True
    assert completion.group_chat_implemented is False
    assert completion.migration_executed is False

    assert "C19A contact identity exists" in CONVERSATION_DATA_FLOW_DIAGRAM
    assert "C19B contact directory resolves" in CONVERSATION_DATA_FLOW_DIAGRAM
    assert "active C18C membership exists" in CONVERSATION_DATA_FLOW_DIAGRAM
    assert "C19C messages must bind" in CONVERSATION_DATA_FLOW_DIAGRAM


def test_c19d_conversation_id_can_bind_c19c_message() -> None:
    conversation = Conversation(type="direct", participants=["user-a", "user-b"])
    message = Message(
        from_user_id="user-a",
        to_user_id="user-b",
        conversation_id=conversation.conversation_id,
        content_type="text",
        content="hello",
    )

    assert message.conversation_id == conversation.conversation_id


def test_c19d_service_enforces_actor_participant_and_contact_membership_rules(
    conversation_tables: None,
) -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19d_service_owner", role="owner")
        actor = _create_user(db, username="c19d_service_actor")
        peer = _create_user(db, username="c19d_service_peer")
        outsider = _create_user(db, username="c19d_service_outsider")
        suspended = _create_user(db, username="c19d_service_suspended")
        org_id = _create_org(db, owner=owner, org_name="Conversation Service Org")
        _create_membership(db, user=actor, org_id=org_id, role="member")
        _create_membership(db, user=peer, org_id=org_id, role="member")
        _create_membership(db, user=suspended, org_id=org_id, role="member", status="suspended")
        _create_identity(
            db,
            user=actor,
            org_id=org_id,
            org_name="Conversation Service Org",
            title="Dispatcher",
        )
        _create_identity(
            db,
            user=peer,
            org_id=org_id,
            org_name="Conversation Service Org",
            title="Operator",
        )
        _create_identity(
            db,
            user=suspended,
            org_id=org_id,
            org_name="Conversation Service Org",
            title="Suspended Operator",
        )
        db.commit()

        conversation = create_or_get_conversation(
            db,
            payload=ConversationCreateRequest(
                participants=[str(actor.id), str(peer.id)],
            ),
            actor=actor,
        )
        reused = create_or_get_conversation(
            db,
            payload=ConversationCreateRequest(
                participants=[str(peer.id), str(actor.id)],
            ),
            actor=actor,
        )

        assert reused.conversation_id == conversation.conversation_id

        with pytest.raises(ConversationAccessDeniedError):
            create_or_get_conversation(
                db,
                payload=ConversationCreateRequest(
                    participants=[str(actor.id), str(peer.id)],
                ),
                actor=outsider,
            )

        with pytest.raises(ConversationParticipantNotFoundError):
            create_or_get_conversation(
                db,
                payload=ConversationCreateRequest(
                    participants=[str(actor.id), str(outsider.id)],
                ),
                actor=actor,
            )

        with pytest.raises(ConversationParticipantNotFoundError):
            create_or_get_conversation(
                db,
                payload=ConversationCreateRequest(
                    participants=[str(actor.id), str(suspended.id)],
                ),
                actor=actor,
            )

        with pytest.raises(ConversationAccessDeniedError):
            list_user_conversations_for_actor(
                db,
                user_id=str(peer.id),
                actor=actor,
            )

        with pytest.raises(GroupConversationReservedError):
            create_or_get_conversation(
                db,
                payload=ConversationCreateRequest(
                    type="group",
                    participants=[str(actor.id), str(peer.id), str(outsider.id)],
                ),
                actor=actor,
            )


def test_c19d_conversation_api_routes_create_reuse_list_and_reserve_group(
    conversation_tables: None,
) -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19d_api_owner", role="owner")
        actor = _create_user(db, username="c19d_api_actor")
        peer = _create_user(db, username="c19d_api_peer")
        org_id = _create_org(db, owner=owner, org_name="Conversation API Org")
        _create_membership(db, user=actor, org_id=org_id, role="member")
        _create_membership(db, user=peer, org_id=org_id, role="member")
        _create_identity(
            db,
            user=actor,
            org_id=org_id,
            org_name="Conversation API Org",
            title="Dispatcher",
        )
        _create_identity(
            db,
            user=peer,
            org_id=org_id,
            org_name="Conversation API Org",
            title="Operator",
        )
        db.commit()
        actor_user_id = str(actor.id)
        peer_user_id = str(peer.id)

        first = route_create_conversation(
            ConversationCreateRequest(
                participants=[peer_user_id, actor_user_id],
            ),
            db=db,
            actor=actor,
        )
        second = route_create_conversation(
            ConversationCreateRequest(
                participants=[actor_user_id, peer_user_id],
            ),
            db=db,
            actor=actor,
        )
        conversation_id = generate_direct_conversation_id(
            actor_user_id,
            peer_user_id,
        )
        detail = route_get_conversation(conversation_id, db=db, actor=actor)
        user_list = route_list_user_conversations(
            actor_user_id,
            db=db,
            actor=actor,
        )
        with pytest.raises(HTTPException) as group_error:
            route_create_conversation(
                ConversationCreateRequest(
                    type="group",
                    participants=[actor_user_id, peer_user_id, "user-c"],
                ),
                db=db,
                actor=actor,
            )

    assert first.conversation_id == conversation_id
    assert second.conversation_id == conversation_id
    assert first.participants == sorted([actor_user_id, peer_user_id])
    assert detail.conversation_id == conversation_id
    assert [item.conversation_id for item in user_list] == [conversation_id]
    assert group_error.value.status_code == 501
    assert group_error.value.detail["group_chat_implemented"] is False


def test_c19d_conversation_routes_are_registered_as_internal_app_routes() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/conversations" in route.path
    }

    assert ("/api/app/conversations/create", ("POST",)) in routes
    assert ("/api/app/conversations/{conversation_id}", ("GET",)) in routes
    assert ("/api/app/conversations/user/{user_id}", ("GET",)) in routes
    assert not any(
        path.startswith("/api/public/conversations") for path, _ in routes
    )
    assert not any(
        path.startswith("/api/control-plane/conversations") for path, _ in routes
    )
