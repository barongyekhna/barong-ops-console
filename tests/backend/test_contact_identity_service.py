from __future__ import annotations

import pytest
from sqlalchemy import delete

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.contact_identity import ContactIdentityRecord
from backend.app.models.operation_log import OperationLog
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.contact_identity import (
    ContactIdentityHireInput,
    ContactIdentityUpdate,
)
from backend.app.schemas.org_membership import generate_membership_id
from backend.app.schemas.organization import generate_org_id
from backend.app.services.auth_service import AuditContext
from backend.app.services.contact_identity_service import (
    ContactIdentityMembershipRequiredError,
    ContactIdentityPermissionDeniedError,
    create_contact_identity,
    update_contact_identity,
)


@pytest.fixture
def contact_identity_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.contact_identity_service.create_operation_log",
        lambda *args, **kwargs: None,
    )
    Base.metadata.create_all(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(OperationLog))
        db.execute(delete(User))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(OperationLog))
        db.execute(delete(User))
        db.commit()


def _audit() -> AuditContext:
    return AuditContext(request_id="c19a-test", ip_address=None, user_agent=None)


def _create_user(db, *, username: str, role: str = "operator") -> User:
    user = User(
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
) -> OrgMembershipRecord:
    membership = OrgMembershipRecord(
        membership_id=generate_membership_id(),
        user_id=str(user.id),
        org_id=org_id,
        role=role,
        status="active",
    )
    db.add(membership)
    db.flush()
    return membership


def _create_identity(
    db,
    *,
    user: User,
    org_id: str,
    org_name: str,
    role: str,
    title: str = "Associate",
) -> ContactIdentityRecord:
    identity = ContactIdentityRecord(
        user_id=str(user.id),
        name=user.username,
        org_id=org_id,
        org_name=org_name,
        title=title,
        role=role,
    )
    db.add(identity)
    db.flush()
    return identity


def test_legacy_c19a_contact_routes_are_retired() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/contacts" in route.path or "/c19/profiles" in route.path
    }

    assert ("/api/app/c19/profiles/{user_id}", ("GET",)) in routes
    assert not any(path.startswith("/api/app/contacts") for path, _ in routes)


def test_c19a_create_contact_identity_snapshots_hire_time_org(
    contact_identity_tables: None,
) -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19a_owner", role="owner")
        admin = _create_user(db, username="c19a_admin")
        org_id = _create_org(db, owner=owner, org_name="Original Org Name")
        _create_membership(db, user=admin, org_id=org_id, role="admin")
        db.commit()

        identity = create_contact_identity(
            db,
            user=admin,
            payload=ContactIdentityHireInput(
                name=" Alice Admin ",
                org_id=org_id,
                title=" Operations Lead ",
            ),
            actor=owner,
            audit=_audit(),
        )

        assert identity.user_id == str(admin.id)
        assert identity.name == "Alice Admin"
        assert identity.org_id == org_id
        assert identity.org_name == "Original Org Name"
        assert identity.title == "Operations Lead"
        assert identity.role == "org_admin"
        assert identity.immutable_fields == ["name", "org_name", "title"]

        stored = db.get(ContactIdentityRecord, str(admin.id))
        assert stored is not None
        assert stored.org_name == "Original Org Name"


def test_c19a_create_requires_active_c18c_membership(
    contact_identity_tables: None,
) -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19a_no_membership_owner", role="owner")
        user = _create_user(db, username="c19a_no_membership_user")
        org_id = _create_org(db, owner=owner, org_name="Membership Required")
        db.commit()

        with pytest.raises(ContactIdentityMembershipRequiredError):
            create_contact_identity(
                db,
                user=user,
                payload=ContactIdentityHireInput(
                    name="No Membership",
                    org_id=org_id,
                    title="Analyst",
                ),
                actor=owner,
                audit=_audit(),
            )


def test_c19a_update_contact_identity_enforces_owner_admin_member_rules(
    contact_identity_tables: None,
) -> None:
    with SessionLocal() as db:
        global_owner = _create_user(db, username="c19a_global_owner", role="owner")
        org_admin = _create_user(db, username="c19a_org_admin")
        member_a = _create_user(db, username="c19a_member_a")
        member_b = _create_user(db, username="c19a_member_b")
        target_owner = _create_user(db, username="c19a_target_owner")

        org_a = _create_org(db, owner=target_owner, org_name="Org A")
        org_b = _create_org(db, owner=global_owner, org_name="Org B")
        _create_membership(db, user=org_admin, org_id=org_a, role="admin")
        _create_membership(db, user=member_a, org_id=org_a, role="member")
        _create_membership(db, user=member_b, org_id=org_b, role="member")
        _create_membership(db, user=target_owner, org_id=org_a, role="owner")

        _create_identity(
            db,
            user=org_admin,
            org_id=org_a,
            org_name="Org A",
            role="org_admin",
            title="Org Admin",
        )
        _create_identity(
            db,
            user=member_a,
            org_id=org_a,
            org_name="Org A",
            role="member",
            title="Member A",
        )
        _create_identity(
            db,
            user=member_b,
            org_id=org_b,
            org_name="Org B",
            role="member",
            title="Member B",
        )
        _create_identity(
            db,
            user=target_owner,
            org_id=org_a,
            org_name="Org A",
            role="owner",
            title="Org Owner",
        )
        db.commit()

        owner_updated = update_contact_identity(
            db,
            user_id=str(member_b.id),
            payload=ContactIdentityUpdate(name="Owner Cross Org Update"),
            actor=global_owner,
            audit=_audit(),
        )
        assert owner_updated.name == "Owner Cross Org Update"

        admin_updated = update_contact_identity(
            db,
            user_id=str(member_a.id),
            payload=ContactIdentityUpdate(title="Same Org Director"),
            actor=org_admin,
            audit=_audit(),
        )
        assert admin_updated.title == "Same Org Director"

        with pytest.raises(ContactIdentityPermissionDeniedError):
            update_contact_identity(
                db,
                user_id=str(member_b.id),
                payload=ContactIdentityUpdate(title="Cross Org Attempt"),
                actor=org_admin,
                audit=_audit(),
            )

        with pytest.raises(ContactIdentityPermissionDeniedError):
            update_contact_identity(
                db,
                user_id=str(member_a.id),
                payload=ContactIdentityUpdate(title="Self Service Attempt"),
                actor=member_a,
                audit=_audit(),
            )

        with pytest.raises(ContactIdentityPermissionDeniedError):
            update_contact_identity(
                db,
                user_id=str(target_owner.id),
                payload=ContactIdentityUpdate(name="Owner Rename Attempt"),
                actor=org_admin,
                audit=_audit(),
            )
