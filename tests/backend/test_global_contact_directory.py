from __future__ import annotations

import pytest
from sqlalchemy import delete

from backend.app.core.security import hash_password
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.contact_identity import ContactIdentityRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.global_contact import (
    ALPHABET_GROUPS,
    GLOBAL_CONTACT_DATA_FLOW_DIAGRAM,
    GlobalContact,
    GlobalContactDirectory,
    empty_global_contact_directory,
    get_global_contact_api_design,
    get_global_contact_completion_status,
    get_global_contact_directory_algorithm,
    get_global_contact_integration_model,
    get_global_contact_security_model,
    get_sort_key,
)
from backend.app.schemas.org_membership import generate_membership_id
from backend.app.schemas.organization import generate_org_id
from backend.app.services.global_contact_directory import (
    GlobalContactDirectoryAccessDeniedError,
    build_global_directory,
)


@pytest.fixture
def global_contact_tables() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(User))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(ContactIdentityRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(User))
        db.commit()


def _create_user(
    db,
    *,
    username: str,
    role: str = "operator",
    password: str = "test-only-password",
) -> User:
    user = User(
        username=username,
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
    name: str,
    org_id: str,
    org_name: str,
    title: str,
    role: str = "member",
) -> None:
    db.add(
        ContactIdentityRecord(
            user_id=str(user.id),
            name=name,
            org_id=org_id,
            org_name=org_name,
            title=title,
            role=role,
        )
    )
    db.flush()


def test_c19b_global_contact_schema_and_design_contract() -> None:
    org_id = generate_org_id()
    contact = GlobalContact(
        user_id=" user-1 ",
        display_name=" Alice Ops ",
        org_id=org_id,
        org_name=" Barong Store ",
        title=" Operations Lead ",
        role=" org_admin ",
        sort_key=" a ",
    )

    assert contact.user_id == "user-1"
    assert contact.display_name == "Alice Ops"
    assert contact.sort_key == "A"
    assert get_sort_key("alice") == "A"
    assert get_sort_key(" Bob") == "B"
    assert get_sort_key("张三") == "Z"
    assert get_sort_key("李四") == "L"
    assert get_sort_key("3 Ops") == "#"
    assert get_sort_key("@system") == "#"

    directory = GlobalContactDirectory(root=empty_global_contact_directory())
    assert list(directory.root) == list(ALPHABET_GROUPS)

    algorithm = get_global_contact_directory_algorithm()
    api_design = get_global_contact_api_design()
    integration = get_global_contact_integration_model()
    security = get_global_contact_security_model()
    completion = get_global_contact_completion_status()

    assert "fetch all ContactIdentity records" in algorithm.steps
    assert api_design.endpoints[0].path == "/contacts/directory"
    assert api_design.endpoints[0].external_access_allowed is False
    assert integration.c19a_identity_source == "contact_identities"
    assert integration.c18c_membership_source == "org_memberships"
    assert integration.modifies_c19a is False
    assert integration.modifies_c18_system is False
    assert security.cross_org_visibility_allowed_for_internal_users is True
    assert security.external_access_allowed is False
    assert completion.global_contact_schema_defined is True
    assert completion.migration_executed is False
    assert "read C19A contact_identities" in GLOBAL_CONTACT_DATA_FLOW_DIAGRAM
    assert "join C18C org_memberships" in GLOBAL_CONTACT_DATA_FLOW_DIAGRAM


def test_c19b_build_global_directory_groups_cross_org_contacts(
    global_contact_tables: None,
) -> None:
    with SessionLocal() as db:
        owner = _create_user(db, username="c19b_owner", role="owner")
        actor = _create_user(db, username="c19b_actor")
        alice = _create_user(db, username="c19b_alice")
        zhang = _create_user(db, username="c19b_zhang")
        numeric = _create_user(db, username="c19b_numeric")
        suspended = _create_user(db, username="c19b_suspended")

        org_a = _create_org(db, owner=owner, org_name="Alpha Org Current")
        org_b = _create_org(db, owner=owner, org_name="Beta Org Current")
        _create_membership(db, user=actor, org_id=org_a, role="member")
        _create_membership(db, user=alice, org_id=org_a, role="admin")
        _create_membership(db, user=zhang, org_id=org_b, role="member")
        _create_membership(db, user=numeric, org_id=org_b, role="member")
        _create_membership(
            db,
            user=suspended,
            org_id=org_a,
            role="member",
            status="suspended",
        )
        _create_identity(
            db,
            user=alice,
            name="Alice Ops",
            org_id=org_a,
            org_name="Old Alpha Org Snapshot",
            title="Operations Lead",
            role="member",
        )
        _create_identity(
            db,
            user=zhang,
            name="张三",
            org_id=org_b,
            org_name="Old Beta Org Snapshot",
            title="Warehouse Lead",
        )
        _create_identity(
            db,
            user=numeric,
            name="3 Bot",
            org_id=org_b,
            org_name="Old Beta Org Snapshot",
            title="Automation Agent",
        )
        _create_identity(
            db,
            user=suspended,
            name="Bob Suspended",
            org_id=org_a,
            org_name="Old Alpha Org Snapshot",
            title="Inactive",
        )
        db.commit()

        directory = build_global_directory(db, actor=actor)

    assert list(directory) == list(ALPHABET_GROUPS)
    assert [contact.display_name for contact in directory["A"]] == ["Alice Ops"]
    assert directory["A"][0].org_name == "Alpha Org Current"
    assert directory["A"][0].role == "org_admin"
    assert [contact.display_name for contact in directory["Z"]] == ["张三"]
    assert [contact.display_name for contact in directory["#"]] == ["3 Bot"]
    all_names = {
        contact.display_name
        for contacts in directory.values()
        for contact in contacts
    }
    assert "Bob Suspended" not in all_names


def test_c19b_build_global_directory_requires_internal_c18_user(
    global_contact_tables: None,
) -> None:
    with SessionLocal() as db:
        outsider = _create_user(db, username="c19b_outsider", role="viewer")
        db.commit()

        with pytest.raises(GlobalContactDirectoryAccessDeniedError):
            build_global_directory(db, actor=outsider)


def test_c19b_directory_uses_the_durable_c19_namespace() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/contacts" in route.path or "/c19/directory" in route.path
    }

    assert ("/api/app/c19/directory", ("GET",)) in routes
    assert not any(path.startswith("/api/app/contacts") for path, _ in routes)


def test_legacy_c19b_directory_api_is_not_a_shadow_runtime() -> None:
    assert not any(
        route.path == "/api/app/contacts/directory" for route in app.routes
    )
