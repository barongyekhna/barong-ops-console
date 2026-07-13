from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.base import Base
from backend.app.models.c19 import (
    C19AffiliationRecord,
    C19ConversationMemberRecord,
    C19ConversationRecord,
    C19ConversationUserSettingRecord,
    C19ProfileRecord,
    C19UserBlockRecord,
)
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.c19 import conversation_service
from backend.app.modules.c19.conversation_router import router
from backend.app.modules.c19.conversation_schemas import (
    ConversationMemberInput,
    ConversationSettingsUpdateRequest,
    DirectConversationCreateRequest,
    GroupCreateRequest,
    GroupMembersAddRequest,
    GroupOwnerTransferRequest,
    GroupUpdateRequest,
)
from backend.app.modules.c19.conversation_service import (
    C19ConversationControlError,
    add_group_members,
    create_direct_conversation,
    create_group,
    delete_group,
    get_conversation_detail,
    get_settings,
    leave_group,
    list_conversations,
    remove_group_member,
    transfer_group_owner,
    update_group,
    update_settings,
)


pytestmark = pytest.mark.unit

ORG_ONE = "org_" + "1" * 32
ORG_TWO = "org_" + "2" * 32
ORG_THREE = "org_" + "3" * 32


@dataclass
class RuntimeHarness:
    engine: Engine
    session_factory: sessionmaker[Session]
    affiliations: dict[int, str]
    memberships: dict[int, str]
    audits: list[dict[str, Any]]


@pytest.fixture
def runtime_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> RuntimeHarness:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'c19-control.db'}")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        User.__table__,
        OrganizationRecord.__table__,
        OrgMembershipRecord.__table__,
        C19ProfileRecord.__table__,
        C19AffiliationRecord.__table__,
        C19UserBlockRecord.__table__,
        C19ConversationRecord.__table__,
        C19ConversationMemberRecord.__table__,
        C19ConversationUserSettingRecord.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    now = datetime.now(UTC)
    affiliations = {user_id: f"affiliation-{user_id}" for user_id in range(1, 7)}
    memberships = {user_id: f"membership-{user_id}" for user_id in range(1, 7)}
    with factory() as db:
        db.add_all(
            [
                OrganizationRecord(
                    org_id=ORG_ONE,
                    name="One",
                    org_type="company",
                    owner_user_id="1",
                    status="active",
                    metadata_json={},
                ),
                OrganizationRecord(
                    org_id=ORG_TWO,
                    name="Two",
                    org_type="company",
                    owner_user_id="3",
                    status="active",
                    metadata_json={},
                ),
            ]
        )
        users = [
            User(
                id=user_id,
                username=f"user-{user_id}",
                password_hash="not-used",
                role="member",
                organization_id=ORG_ONE if user_id <= 2 else ORG_TWO,
                must_change_password=False,
                is_active=True,
            )
            for user_id in range(1, 7)
        ]
        db.add_all(users)
        db.flush()
        db.add_all(
            [
                OrgMembershipRecord(
                    membership_id=memberships[user_id],
                    user_id=str(user_id),
                    org_id=ORG_ONE if user_id <= 2 else ORG_TWO,
                    role="member",
                    status="active",
                    joined_at=now,
                )
                for user_id in range(1, 7)
            ]
        )
        db.add_all(
            [
                C19ProfileRecord(
                    user_id=user_id,
                    display_name=f"User {user_id}",
                )
                for user_id in range(1, 7)
            ]
        )
        db.flush()
        db.add_all(
            [
                C19AffiliationRecord(
                    affiliation_id=affiliations[user_id],
                    user_id=user_id,
                    org_id=ORG_ONE if user_id <= 2 else ORG_TWO,
                    source_membership_id=memberships[user_id],
                    role="member",
                    status="active",
                    joined_at=now,
                )
                for user_id in range(1, 7)
            ]
        )
        db.commit()

    audits: list[dict[str, Any]] = []

    def _capture_audit(_: Session, **values: Any) -> None:
        audits.append(values)

    monkeypatch.setattr(conversation_service, "_write_audit", _capture_audit)
    harness = RuntimeHarness(
        engine=engine,
        session_factory=factory,
        affiliations=affiliations,
        memberships=memberships,
        audits=audits,
    )
    yield harness
    engine.dispose()


def _user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    assert user is not None
    return user


def _assert_error(
    expected_code: str,
    callable_: Any,
) -> C19ConversationControlError:
    with pytest.raises(C19ConversationControlError) as captured:
        callable_()
    assert captured.value.code == expected_code
    return captured.value


def test_router_and_dtos_expose_only_the_control_metadata_contract() -> None:
    route_contract = {
        (method, route.path)
        for route in router.routes
        for method in route.methods
    }
    assert route_contract == {
        ("GET", "/c19/conversations"),
        ("POST", "/c19/conversations/direct"),
        ("GET", "/c19/conversations/{conversation_id}"),
        ("GET", "/c19/conversations/{conversation_id}/settings"),
        ("PATCH", "/c19/conversations/{conversation_id}/settings"),
        ("POST", "/c19/groups"),
        ("PATCH", "/c19/groups/{conversation_id}"),
        ("POST", "/c19/groups/{conversation_id}/members"),
        ("DELETE", "/c19/groups/{conversation_id}/members/{user_id}"),
        ("POST", "/c19/groups/{conversation_id}/leave"),
        ("POST", "/c19/groups/{conversation_id}/transfer-owner"),
        ("DELETE", "/c19/groups/{conversation_id}"),
    }
    with pytest.raises(ValidationError):
        DirectConversationCreateRequest.model_validate(
            {"peer_user_id": 2, "actor_user_id": 1}
        )

    setting_fields = set(ConversationSettingsUpdateRequest.model_fields)
    assert setting_fields == {
        "is_pinned",
        "is_muted",
        "is_archived",
        "notification_level",
    }
    assert all("read" not in field_name for field_name in setting_fields)
    assert all(
        "read" not in column.name
        for column in C19ConversationUserSettingRecord.__table__.columns
    )


def test_direct_conversation_is_unique_and_survives_new_sessions(
    runtime_harness: RuntimeHarness,
) -> None:
    factory = runtime_harness.session_factory
    with factory() as db:
        created = create_direct_conversation(
            db,
            payload=DirectConversationCreateRequest(peer_user_id=2),
            actor=_user(db, 1),
        )
        conversation_id = created.conversation_id
        assert created.type == "direct"
        assert {member.user_id for member in created.members} == {1, 2}

    with factory() as restarted_db:
        detail = get_conversation_detail(
            restarted_db,
            conversation_id=conversation_id,
            actor=_user(restarted_db, 2),
        )
        reverse = create_direct_conversation(
            restarted_db,
            payload=DirectConversationCreateRequest(peer_user_id=1),
            actor=_user(restarted_db, 2),
        )
        page = list_conversations(
            restarted_db,
            actor=_user(restarted_db, 2),
            limit=1,
            offset=0,
        )
        assert detail.conversation_id == conversation_id
        assert reverse.conversation_id == conversation_id
        assert page.count == 1
        assert [item.conversation_id for item in page.items] == [conversation_id]
        peer_card = page.items[0].direct_peer
        assert peer_card is not None
        assert peer_card.user_id == 1
        assert peer_card.display_name == "User 1"
        assert restarted_db.scalar(select(func.count(C19ConversationRecord.conversation_id))) == 1
        stored = restarted_db.get(C19ConversationRecord, conversation_id)
        assert stored is not None
        assert stored.direct_pair_key == "1:2"

    assert [audit["action"] for audit in runtime_harness.audits] == [
        "c19.conversation.direct.create"
    ]


def test_creation_keeps_blocks_and_treats_affiliation_as_explicit_optional_context(
    runtime_harness: RuntimeHarness,
) -> None:
    factory = runtime_harness.session_factory
    now = datetime.now(UTC)
    with factory() as db:
        db.add(
            C19UserBlockRecord(
                block_id="block-2-3",
                blocker_user_id=2,
                blocked_user_id=3,
                status="active",
                is_active=True,
                blocked_at=now,
                revoked_at=None,
            )
        )
        db.commit()
        blocked_group = _assert_error(
            "c19_relationship_access_denied",
            lambda: create_group(
                db,
                payload=GroupCreateRequest(
                    title="Blocked pair",
                    members=[
                        ConversationMemberInput(user_id=2),
                        ConversationMemberInput(user_id=3),
                    ],
                ),
                actor=_user(db, 1),
            ),
        )
        assert blocked_group.message == "Relationship access denied."

        db.add(
            C19UserBlockRecord(
                block_id="block-4-5",
                blocker_user_id=4,
                blocked_user_id=5,
                status="active",
                is_active=True,
                blocked_at=now,
                revoked_at=None,
            )
        )
        db.commit()
        for actor_id, peer_id in ((4, 5), (5, 4)):
            blocked_direct = _assert_error(
                "c19_relationship_access_denied",
                lambda actor_id=actor_id, peer_id=peer_id: create_direct_conversation(
                    db,
                    payload=DirectConversationCreateRequest(peer_user_id=peer_id),
                    actor=_user(db, actor_id),
                ),
            )
            assert blocked_direct.status_code == 403
            assert blocked_direct.message == "Relationship access denied."

        db.add(
            OrganizationRecord(
                org_id=ORG_THREE,
                name="Three",
                org_type="company",
                owner_user_id="1",
                status="active",
                metadata_json={},
            )
        )
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id="membership-1-secondary",
                user_id="1",
                org_id=ORG_THREE,
                role="member",
                status="active",
                joined_at=now,
            )
        )
        db.flush()
        db.add(
            C19AffiliationRecord(
                affiliation_id="affiliation-1-secondary",
                user_id=1,
                org_id=ORG_THREE,
                source_membership_id="membership-1-secondary",
                role="member",
                status="active",
                joined_at=now,
            )
        )
        db.commit()
        affiliation_free = create_direct_conversation(
            db,
            payload=DirectConversationCreateRequest(peer_user_id=6),
            actor=_user(db, 1),
        )
        assert all(
            member.affiliation_id is None and member.org_id is None
            for member in affiliation_free.members
        )
        direct = create_direct_conversation(
            db,
            payload=DirectConversationCreateRequest(
                peer_user_id=2,
                actor_affiliation_id=runtime_harness.affiliations[1],
                peer_affiliation_id=runtime_harness.affiliations[2],
            ),
            actor=_user(db, 1),
        )
        actor_member = next(member for member in direct.members if member.user_id == 1)
        assert actor_member.affiliation_id == runtime_harness.affiliations[1]


def test_group_lifecycle_enforces_participation_roles_and_owner_not_affiliation(
    runtime_harness: RuntimeHarness,
) -> None:
    factory = runtime_harness.session_factory
    with factory() as db:
        group = create_group(
            db,
            payload=GroupCreateRequest(
                title="Cross organization",
                members=[
                    ConversationMemberInput(user_id=2),
                    ConversationMemberInput(user_id=3),
                ],
            ),
            actor=_user(db, 1),
        )
        conversation_id = group.conversation_id
        assert {member.org_id for member in group.members} == {None}
        assert sum(
            member.role == "owner" and member.status == "active"
            for member in group.members
        ) == 1

        outsider_error = _assert_error(
            "c19_conversation_not_found",
            lambda: get_conversation_detail(
                db,
                conversation_id=conversation_id,
                actor=_user(db, 5),
            ),
        )
        assert outsider_error.status_code == 404
        _assert_error(
            "c19_group_access_denied",
            lambda: update_group(
                db,
                conversation_id=conversation_id,
                payload=GroupUpdateRequest(title="Unauthorized"),
                actor=_user(db, 2),
            ),
        )

        expanded = add_group_members(
            db,
            conversation_id=conversation_id,
            payload=GroupMembersAddRequest(
                members=[ConversationMemberInput(user_id=4)]
            ),
            actor=_user(db, 1),
        )
        assert {member.user_id for member in expanded.members if member.status == "active"} == {
            1,
            2,
            3,
            4,
        }

        target_membership = db.get(
            OrgMembershipRecord,
            runtime_harness.memberships[3],
        )
        assert target_membership is not None
        target_membership.status = "suspended"
        db.commit()
        still_a_member = get_conversation_detail(
            db,
            conversation_id=conversation_id,
            actor=_user(db, 3),
        )
        assert still_a_member.conversation_id == conversation_id
        target_membership = db.get(
            OrgMembershipRecord,
            runtime_harness.memberships[3],
        )
        assert target_membership is not None
        target_membership.status = "active"
        db.commit()

        transferred = transfer_group_owner(
            db,
            conversation_id=conversation_id,
            payload=GroupOwnerTransferRequest(new_owner_user_id=2),
            actor=_user(db, 1),
        )
        owners = [
            member
            for member in transferred.members
            if member.status == "active" and member.role == "owner"
        ]
        assert [member.user_id for member in owners] == [2]
        _assert_error(
            "c19_group_access_denied",
            lambda: delete_group(
                db,
                conversation_id=conversation_id,
                actor=_user(db, 1),
            ),
        )

        after_remove = remove_group_member(
            db,
            conversation_id=conversation_id,
            target_user_id=4,
            actor=_user(db, 2),
        )
        assert next(
            member for member in after_remove.members if member.user_id == 4
        ).status == "removed"
        leave_ack = leave_group(
            db,
            conversation_id=conversation_id,
            actor=_user(db, 3),
        )
        assert leave_ack.model_dump() == {
            "conversation_id": conversation_id,
            "member_status": "left",
            "conversation_status": "active",
        }
        closed = delete_group(
            db,
            conversation_id=conversation_id,
            actor=_user(db, 2),
        )
        assert closed.status == "closed"

    with factory() as restarted_db:
        stored = restarted_db.get(C19ConversationRecord, conversation_id)
        assert stored is not None and stored.status == "closed"
        active_count = restarted_db.scalar(
            select(func.count(C19ConversationMemberRecord.member_id)).where(
                C19ConversationMemberRecord.conversation_id == conversation_id,
                C19ConversationMemberRecord.status == "active",
            )
        )
        assert active_count == 0

    successful_actions = [audit["action"] for audit in runtime_harness.audits]
    assert successful_actions == [
        "c19.group.create",
        "c19.group.members.add",
        "c19.group.owner.transfer",
        "c19.group.member.remove",
        "c19.group.leave",
        "c19.group.delete",
    ]


def test_settings_persist_without_local_message_or_read_cursor_state(
    runtime_harness: RuntimeHarness,
) -> None:
    factory = runtime_harness.session_factory
    with factory() as db:
        direct = create_direct_conversation(
            db,
            payload=DirectConversationCreateRequest(peer_user_id=2),
            actor=_user(db, 1),
        )
        updated = update_settings(
            db,
            conversation_id=direct.conversation_id,
            payload=ConversationSettingsUpdateRequest(
                is_pinned=True,
                is_muted=True,
                is_archived=True,
                notification_level="mentions",
            ),
            actor=_user(db, 1),
        )
        assert updated.is_pinned is True

    with factory() as restarted_db:
        settings = get_settings(
            restarted_db,
            conversation_id=direct.conversation_id,
            actor=_user(restarted_db, 1),
        )
        assert settings.model_dump(exclude={"created_at", "updated_at"}) == {
            "conversation_id": direct.conversation_id,
            "user_id": 1,
            "is_pinned": True,
            "is_muted": True,
            "is_archived": True,
            "notification_level": "mentions",
        }
        table_names = set(Base.metadata.tables)
        assert "c19_messages" not in table_names
        assert "c19_message_attachments" not in table_names
        assert "c19_read_cursors" not in table_names

    assert [audit["action"] for audit in runtime_harness.audits] == [
        "c19.conversation.direct.create",
        "c19.conversation.settings.update",
    ]


def test_users_without_any_affiliation_can_create_direct_and_group_conversations(
    runtime_harness: RuntimeHarness,
) -> None:
    with runtime_harness.session_factory() as db:
        db.add_all(
            [
                User(
                    id=user_id,
                    username=f"native-c19-{user_id}",
                    password_hash="not-used",
                    role=role,
                    organization_id=None,
                    must_change_password=False,
                    is_active=True,
                )
                for user_id, role in ((7, "viewer"), (8, "unknown-role"))
            ]
        )
        db.flush()
        db.add_all(
            [
                C19ProfileRecord(user_id=user_id, display_name=f"Native {user_id}")
                for user_id in (7, 8)
            ]
        )
        db.commit()

        direct = create_direct_conversation(
            db,
            payload=DirectConversationCreateRequest(peer_user_id=8),
            actor=_user(db, 7),
        )
        assert {member.user_id for member in direct.members} == {7, 8}
        assert all(member.affiliation_id is None for member in direct.members)

        group = create_group(
            db,
            payload=GroupCreateRequest(
                title="Native C19",
                members=[
                    ConversationMemberInput(user_id=8),
                    ConversationMemberInput(user_id=1),
                ],
            ),
            actor=_user(db, 7),
        )
        assert {member.user_id for member in group.members} == {1, 7, 8}
        assert all(member.org_id is None for member in group.members)
