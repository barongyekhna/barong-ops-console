from __future__ import annotations

from itertools import count

import pytest
from sqlalchemy import delete, select

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.operation_log import OperationLog
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.org_membership import (
    OrgMemberAddRequest,
    OrgMemberRemoveRequest,
)
from backend.app.schemas.organization import generate_org_id
from backend.app.services.auth_service import AuditContext
from backend.app.services.org_membership_service import (
    OrgMembershipPermissionDeniedError,
    OrgOwnerMembershipImmutableError,
    add_org_member,
    list_org_members,
    remove_org_member,
)

USER_ID_COUNTER = count(1)


@pytest.fixture
def membership_tables(monkeypatch):
    monkeypatch.setattr(
        "backend.app.services.org_membership_service.create_operation_log",
        lambda *args, **kwargs: None,
    )
    Base.metadata.create_all(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(OperationLog))
        db.execute(delete(User))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(OperationLog))
        db.execute(delete(User))
        db.commit()


def _audit() -> AuditContext:
    return AuditContext(request_id="c18c-test", ip_address=None, user_agent=None)


def _create_user(db, *, username: str, role: str = "operator") -> User:
    user = User(
        id=next(USER_ID_COUNTER),
        username=username,
        password_hash="test-only-password-hash",
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _create_org(db, *, owner: User, org_name: str = "Barong Store") -> str:
    org_id = generate_org_id()
    db.add(
        OrganizationRecord(
            org_id=org_id,
            org_name=org_name,
            org_type="store",
            owner_user_id=str(owner.id),
            status="active",
            metadata_json={"industry": "commerce"},
        )
    )
    db.flush()
    return org_id


def test_c18c_membership_api_routes_are_registered() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/members" in route.path
    }

    assert ("/api/app/org/{org_id}/members/add", ("POST",)) in routes
    assert ("/api/app/org/{org_id}/members/remove", ("POST",)) in routes
    assert ("/api/app/org/{org_id}/members", ("GET",)) in routes


def test_c18c_owner_admin_member_management_permissions(
    membership_tables: None,
) -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c18c_owner", role="owner")
        admin = _create_user(db, username="c18c_admin")
        member = _create_user(db, username="c18c_member")
        extra_member = _create_user(db, username="c18c_extra_member")
        outsider = _create_user(db, username="c18c_outsider")
        org_id = _create_org(db, owner=owner)
        db.commit()

        initial = list_org_members(db, org_id=org_id, actor=owner, audit=_audit())
        assert [(item.user_id, item.role) for item in initial] == [
            (str(owner.id), "owner")
        ]

        added_admin = add_org_member(
            db,
            org_id=org_id,
            payload=OrgMemberAddRequest(user_id=str(admin.id), role="admin"),
            actor=owner,
            audit=_audit(),
        )
        added_member = add_org_member(
            db,
            org_id=org_id,
            payload=OrgMemberAddRequest(user_id=str(member.id), role="member"),
            actor=owner,
            audit=_audit(),
        )
        assert added_admin.role == "admin"
        assert added_member.role == "member"

        admin_added_member = add_org_member(
            db,
            org_id=org_id,
            payload=OrgMemberAddRequest(user_id=str(extra_member.id), role="member"),
            actor=admin,
            audit=_audit(),
        )
        assert admin_added_member.role == "member"

        with pytest.raises(OrgMembershipPermissionDeniedError):
            add_org_member(
                db,
                org_id=org_id,
                payload=OrgMemberAddRequest(user_id=str(extra_member.id), role="admin"),
                actor=member,
                audit=_audit(),
            )

        with pytest.raises(OrgMembershipPermissionDeniedError):
            list_org_members(db, org_id=org_id, actor=outsider, audit=_audit())

        visible_to_member = list_org_members(
            db,
            org_id=org_id,
            actor=member,
            audit=_audit(),
        )
        assert {item.user_id for item in visible_to_member} == {
            str(owner.id),
            str(admin.id),
            str(member.id),
            str(extra_member.id),
        }


def test_c18c_same_user_can_have_different_roles_in_different_orgs(
    membership_tables: None,
) -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c18c_multi_owner", role="owner")
        shared_user = _create_user(db, username="c18c_multi_org_user")
        org_1 = _create_org(db, owner=owner, org_name="Barong Store One")
        org_2 = _create_org(db, owner=owner, org_name="Barong Store Two")
        db.commit()

        add_org_member(
            db,
            org_id=org_1,
            payload=OrgMemberAddRequest(user_id=str(shared_user.id), role="admin"),
            actor=owner,
            audit=_audit(),
        )
        add_org_member(
            db,
            org_id=org_2,
            payload=OrgMemberAddRequest(user_id=str(shared_user.id), role="member"),
            actor=owner,
            audit=_audit(),
        )

        memberships = list(
            db.scalars(
                select(OrgMembershipRecord).where(
                    OrgMembershipRecord.user_id == str(shared_user.id)
                )
            )
        )
        role_by_org = {membership.org_id: membership.role for membership in memberships}
        assert role_by_org[org_1] == "admin"
        assert role_by_org[org_2] == "member"

        org_1_members = list_org_members(db, org_id=org_1, actor=owner, audit=_audit())
        org_2_members = list_org_members(db, org_id=org_2, actor=owner, audit=_audit())
        assert all(member.org_id == org_1 for member in org_1_members)
        assert all(member.org_id == org_2 for member in org_2_members)
        assert {
            member.role for member in org_1_members if member.user_id == str(shared_user.id)
        } == {"admin"}
        assert {
            member.role for member in org_2_members if member.user_id == str(shared_user.id)
        } == {"member"}


def test_c18c_remove_suspends_member_and_keeps_owner_immutable(
    membership_tables: None,
) -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c18c_remove_owner", role="owner")
        admin = _create_user(db, username="c18c_remove_admin")
        member = _create_user(db, username="c18c_remove_member")
        org_id = _create_org(db, owner=owner)
        db.commit()

        add_org_member(
            db,
            org_id=org_id,
            payload=OrgMemberAddRequest(user_id=str(admin.id), role="admin"),
            actor=owner,
            audit=_audit(),
        )
        add_org_member(
            db,
            org_id=org_id,
            payload=OrgMemberAddRequest(user_id=str(member.id), role="member"),
            actor=owner,
            audit=_audit(),
        )

        removed = remove_org_member(
            db,
            org_id=org_id,
            payload=OrgMemberRemoveRequest(user_id=str(member.id)),
            actor=admin,
            audit=_audit(),
        )
        assert removed.status == "suspended"

        visible_after_remove = list_org_members(
            db,
            org_id=org_id,
            actor=admin,
            audit=_audit(),
        )
        assert str(member.id) not in {item.user_id for item in visible_after_remove}

        with pytest.raises(OrgMembershipPermissionDeniedError):
            list_org_members(db, org_id=org_id, actor=member, audit=_audit())

        with pytest.raises(OrgOwnerMembershipImmutableError):
            remove_org_member(
                db,
                org_id=org_id,
                payload=OrgMemberRemoveRequest(user_id=str(owner.id)),
                actor=admin,
                audit=_audit(),
            )
