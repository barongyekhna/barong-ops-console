from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.cli import bootstrap_owner as bootstrap_owner_module
from backend.app.db.base import Base
from backend.app.models.c19 import (
    C19AffiliationRecord,
    C19FriendRequestRecord,
    C19ProfileRecord,
    C19RelationshipRecord,
    C19UserBlockRecord,
)
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.c19 import social_service
from backend.app.modules.c19.identity_service import (
    C19ActorUnavailableError,
    get_profile,
    list_directory,
)
from backend.app.modules.c19.identity_social_router import FriendRequestIdPath, router
from backend.app.modules.c19.identity_sync_service import (
    sync_affiliation_from_membership,
)
from backend.app.modules.c19.social_schemas import (
    C19FriendRequestCreate,
    C19FriendRequestDirection,
)
from backend.app.modules.c19.social_service import (
    C19SocialConflictError,
    C19SocialInteractionUnavailableError,
    accept_friend_request,
    block_user,
    cancel_friend_request,
    create_friend_request,
    list_blocks,
    list_friend_requests,
    list_friends,
    remove_friend,
    unblock_user,
)
from backend.app.schemas.org_membership import (
    OrgMemberAddRequest,
    OrgMemberRemoveRequest,
)
from backend.app.schemas.organization import OrganizationCreate, OrganizationType
from backend.app.schemas.user import UserCreate
from backend.app.services import (
    org_membership_service,
    organization_lifecycle,
    user_management_service,
)
from backend.app.services.auth_service import AuditContext


pytestmark = pytest.mark.unit

AUDIT = AuditContext(
    request_id="c19-test-request",
    ip_address="127.0.0.1",
    user_agent="c19-tests",
)
C19_TEST_TABLES = (
    User.__table__,
    OrganizationRecord.__table__,
    OrgMembershipRecord.__table__,
    C19ProfileRecord.__table__,
    C19AffiliationRecord.__table__,
    C19FriendRequestRecord.__table__,
    C19RelationshipRecord.__table__,
    C19UserBlockRecord.__table__,
)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=list(C19_TEST_TABLES))
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def social_audit_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []

    def capture_audit(
        db: Session,
        *,
        actor: User,
        audit: AuditContext,
        action: str,
        target_type: str,
        target_id: str,
        details: dict[str, object],
    ) -> None:
        del db, audit
        events.append(
            {
                "actor_id": actor.id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "details": details,
            }
        )

    monkeypatch.setattr(social_service, "_write_social_audit", capture_audit)
    return events


def _user(
    db: Session,
    username: str,
    *,
    role: str = "operator",
    active: bool = True,
) -> User:
    user = User(
        username=username,
        password_hash="test-only-hash",
        role=role,
        job_title="Must not become a C19 affiliation field",
        is_active=active,
        must_change_password=False,
    )
    db.add(user)
    db.flush()
    return user


def _organization(
    db: Session,
    name: str,
    *,
    owner: User,
) -> OrganizationRecord:
    organization = OrganizationRecord(
        org_id="org_" + uuid4().hex,
        org_name=name,
        org_type="store",
        owner_user_id=str(owner.id),
        status="active",
        metadata_json={},
    )
    db.add(organization)
    db.flush()
    return organization


def _membership(
    db: Session,
    *,
    user: User,
    organization: OrganizationRecord,
    role: str = "member",
    status: str = "active",
) -> OrgMembershipRecord:
    membership = OrgMembershipRecord(
        membership_id="mem_" + uuid4().hex,
        user_id=str(user.id),
        org_id=organization.org_id,
        role=role,
        status=status,
        joined_at=datetime.now(UTC),
    )
    db.add(membership)
    db.flush()
    sync_affiliation_from_membership(
        db,
        membership=membership,
        user=user,
    )
    return membership


def _seed_people(db: Session) -> tuple[
    User,
    User,
    User,
    OrganizationRecord,
    OrganizationRecord,
]:
    actor = _user(db, "c19-actor")
    target = _user(db, "c19-target")
    third = _user(db, "c19-third")
    org_one = _organization(db, "Alpha Store", owner=actor)
    org_two = _organization(db, "Beta Factory", owner=actor)
    _membership(db, user=actor, organization=org_one, role="owner")
    _membership(db, user=target, organization=org_one)
    _membership(db, user=target, organization=org_two, role="admin")
    _membership(db, user=third, organization=org_two)
    db.commit()
    return actor, target, third, org_one, org_two


def test_router_contract_uses_fixed_paths_and_safe_query_names() -> None:
    methods_by_path: dict[str, set[str]] = {}
    for route in router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or ())
    assert methods_by_path == {
        "/c19/directory": {"GET"},
        "/c19/profiles/{user_id}": {"GET"},
        "/c19/friend-requests": {"GET", "POST"},
        "/c19/friend-requests/{request_id}/accept": {"POST"},
        "/c19/friend-requests/{request_id}/reject": {"POST"},
        "/c19/friend-requests/{request_id}/cancel": {"POST"},
        "/c19/friends": {"GET"},
        "/c19/friends/{user_id}": {"DELETE"},
        "/c19/blocks": {"GET"},
        "/c19/blocks/{user_id}": {"POST", "DELETE"},
    }
    directory_route = next(
        route for route in router.routes if route.path == "/c19/directory"
    )
    query_names = {field.alias for field in directory_route.dependant.query_params}
    assert {"search", "affiliation_org_id", "limit", "offset"} <= query_names
    assert "org_id" not in query_names
    assert "q" not in query_names

    for suffix in ("accept", "reject", "cancel"):
        route = next(
            route
            for route in router.routes
            if route.path.endswith(f"/{{request_id}}/{suffix}")
        )
        request_id = next(
            field
            for field in route.dependant.path_params
            if field.name == "request_id"
        )
        metadata = repr(request_id.field_info.metadata)
        assert "max_length=64" in metadata
        assert r"^c19frq_[0-9a-f]{32}$" in metadata

    request_id_adapter = TypeAdapter(FriendRequestIdPath)
    assert request_id_adapter.validate_python("c19frq_" + "a" * 32)
    for invalid in ("", "request-1", "c19frq_" + "z" * 32, "x" * 65):
        with pytest.raises(ValidationError):
            request_id_adapter.validate_python(invalid)


def test_directory_aggregates_all_affiliations_and_trusts_source_membership(
    db: Session,
) -> None:
    actor, target, _, org_one, org_two = _seed_people(db)

    directory = list_directory(
        db,
        actor=actor,
        search="target",
        affiliation_org_id=org_one.org_id,
        limit=1,
        offset=0,
    )
    assert directory.count == 1
    assert len(directory.items) == 1
    assert directory.items[0].user_id == target.id
    assert {item.org_id for item in directory.items[0].affiliations} == {
        org_one.org_id,
        org_two.org_id,
    }
    assert "primary_org_id" not in directory.items[0].model_dump()
    assert all(
        "title" not in affiliation.model_dump()
        for affiliation in directory.items[0].affiliations
    )

    source_membership = db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == str(target.id),
            OrgMembershipRecord.org_id == org_one.org_id,
        )
    )
    projection = db.scalar(
        select(C19AffiliationRecord).where(
            C19AffiliationRecord.user_id == target.id,
            C19AffiliationRecord.org_id == org_one.org_id,
        )
    )
    source_membership.status = "suspended"
    projection.status = "active"
    db.commit()

    drift_safe = list_directory(
        db,
        actor=actor,
        search="target",
        affiliation_org_id=org_one.org_id,
        limit=50,
        offset=0,
    )
    assert drift_safe.count == 0
    profile = get_profile(db, actor=actor, user_id=target.id)
    assert [item.org_id for item in profile.affiliations] == [org_two.org_id]

    actor_membership = db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == str(actor.id)
        )
    )
    actor_membership.status = "suspended"
    db.commit()
    with pytest.raises(C19ActorUnavailableError):
        list_directory(
            db,
            actor=actor,
            search=None,
            affiliation_org_id=None,
            limit=50,
            offset=0,
        )


def test_user_and_membership_lifecycle_sync_is_transactional(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        user_management_service,
        "_log_user_operation",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        org_membership_service,
        "_log_membership_operation",
        lambda *args, **kwargs: None,
    )
    owner = _user(db, "lifecycle-owner", role="owner")
    organization = _organization(db, "Lifecycle Org", owner=owner)
    _membership(db, user=owner, organization=organization, role="owner")
    db.commit()

    managed = user_management_service.create_managed_user(
        db,
        payload=UserCreate(
            username="managed-c19-user",
            role="operator",
            job_title="Designer must not be projected",
            organization_id=organization.org_id,
            is_active=True,
        ),
        actor=owner,
        audit=AUDIT,
    )
    assert db.get(C19ProfileRecord, managed.id).display_name == managed.username
    assert db.scalar(
        select(C19AffiliationRecord).where(
            C19AffiliationRecord.user_id == managed.id
        )
    ) is None

    org_membership_service.add_org_member(
        db,
        org_id=organization.org_id,
        payload=OrgMemberAddRequest(user_id=str(managed.id), role="member"),
        actor=owner,
        audit=AUDIT,
    )
    affiliation = db.scalar(
        select(C19AffiliationRecord).where(
            C19AffiliationRecord.user_id == managed.id,
            C19AffiliationRecord.org_id == organization.org_id,
        )
    )
    assert affiliation.status == "active"
    assert affiliation.role == "member"

    user_management_service.disable_managed_user(
        db,
        user_id=managed.id,
        actor=owner,
        audit=AUDIT,
    )
    assert affiliation.status == "suspended"
    user_management_service.enable_managed_user(
        db,
        user_id=managed.id,
        actor=owner,
        audit=AUDIT,
    )
    assert affiliation.status == "active"

    org_membership_service.remove_org_member(
        db,
        org_id=organization.org_id,
        payload=OrgMemberRemoveRequest(user_id=str(managed.id)),
        actor=owner,
        audit=AUDIT,
    )
    assert affiliation.status == "suspended"


def test_organization_creation_and_owner_bootstrap_sync_identity(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        organization_lifecycle,
        "_log_org_operation",
        lambda *args, **kwargs: None,
    )
    owner = _user(db, "organization-owner", role="owner")
    created = organization_lifecycle.create_organization(
        db,
        payload=OrganizationCreate(
            org_name="Created Org",
            org_type=OrganizationType.STORE,
            owner_user_id=str(owner.id),
        ),
        actor=owner,
        audit=AUDIT,
    )
    affiliation = db.scalar(
        select(C19AffiliationRecord).where(
            C19AffiliationRecord.user_id == owner.id,
            C19AffiliationRecord.org_id == created.org_id,
        )
    )
    assert affiliation is not None
    assert affiliation.role == "owner"
    assert affiliation.status == "active"

    # A direct bootstrap path has no organization yet, so only its profile is synced.
    for table in reversed(C19_TEST_TABLES):
        db.execute(table.delete())
    db.commit()
    db.expunge_all()
    monkeypatch.setattr(
        bootstrap_owner_module,
        "create_operation_log",
        lambda *args, **kwargs: None,
    )
    result = bootstrap_owner_module.bootstrap_owner(
        db,
        owner_username="bootstrap-c19-owner",
        owner_password="bootstrap-password-123",
    )
    assert result == "created"
    bootstrap_owner = db.scalar(select(User).where(User.role == "owner"))
    assert db.get(C19ProfileRecord, bootstrap_owner.id) is not None
    assert db.scalar(select(C19AffiliationRecord)) is None


def test_friendship_block_privacy_and_removed_accept_regression(
    db: Session,
    social_audit_events: list[dict[str, object]],
) -> None:
    actor, target, third, _, _ = _seed_people(db)
    private_message = "private friend request note"
    request = create_friend_request(
        db,
        actor=actor,
        payload=C19FriendRequestCreate(
            addressee_user_id=target.id,
            request_message=private_message,
        ),
        audit=AUDIT,
    )
    assert request.status == "pending"
    assert request.request_message == private_message
    assert private_message not in repr(social_audit_events)

    accepted = accept_friend_request(
        db,
        actor=target,
        request_id=request.request_id,
        audit=AUDIT,
    )
    assert accepted.status == "accepted"
    assert list_friends(db, actor=actor, limit=10, offset=0).count == 1

    removed = remove_friend(
        db,
        actor=actor,
        user_id=target.id,
        audit=AUDIT,
    )
    assert removed.changed is True
    with pytest.raises(
        C19SocialConflictError,
        match="requires a new friend request",
    ):
        accept_friend_request(
            db,
            actor=target,
            request_id=request.request_id,
            audit=AUDIT,
        )
    db.rollback()

    renewed = create_friend_request(
        db,
        actor=actor,
        payload=C19FriendRequestCreate(addressee_user_id=target.id),
        audit=AUDIT,
    )
    assert renewed.request_id == request.request_id
    assert renewed.status == "pending"
    accept_friend_request(
        db,
        actor=target,
        request_id=renewed.request_id,
        audit=AUDIT,
    )

    blocked = block_user(
        db,
        actor=actor,
        user_id=target.id,
        audit=AUDIT,
    )
    assert blocked.profile.user_id == target.id
    assert list_friends(db, actor=actor, limit=10, offset=0).count == 0
    assert list_blocks(db, actor=actor, limit=10, offset=0).count == 1
    assert list_blocks(db, actor=target, limit=10, offset=0).count == 0

    with pytest.raises(C19SocialInteractionUnavailableError) as exc_info:
        create_friend_request(
            db,
            actor=target,
            payload=C19FriendRequestCreate(addressee_user_id=actor.id),
            audit=AUDIT,
        )
    assert str(exc_info.value) == "Social interaction is unavailable."
    assert "block" not in str(exc_info.value).lower()
    db.rollback()

    assert unblock_user(
        db,
        actor=actor,
        user_id=target.id,
        audit=AUDIT,
    ).changed is True
    reverse = create_friend_request(
        db,
        actor=target,
        payload=C19FriendRequestCreate(addressee_user_id=actor.id),
        audit=AUDIT,
    )
    assert cancel_friend_request(
        db,
        actor=target,
        request_id=reverse.request_id,
        audit=AUDIT,
    ).status == "cancelled"

    create_friend_request(
        db,
        actor=actor,
        payload=C19FriendRequestCreate(addressee_user_id=third.id),
        audit=AUDIT,
    )
    page = list_friend_requests(
        db,
        actor=actor,
        direction=C19FriendRequestDirection.ALL,
        request_status=None,
        limit=1,
        offset=0,
    )
    assert page.count == 2
    assert len(page.items) == 1
