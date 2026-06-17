from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from backend.app.core.security import hash_password
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models.module_binding import ModuleBindingRecord
from backend.app.models.operation_log import OperationLog
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.shared_module import SharedModuleRecord
from backend.app.models.user import User
from backend.app.repositories.operation_logs import (
    create_operation_log,
    get_operation_log,
    list_operation_logs,
)
from backend.app.repositories.tenant import TenantIsolationError
from backend.app.schemas.module_binding import ModuleBindRequest
from backend.app.schemas.shared_module import SharedModuleCreateRequest
from backend.app.services.data_isolation import (
    OrgDataIsolationUserContext,
    org_data_isolation_context,
)
from backend.app.services.module_binding_service import (
    bind_module_to_org,
    get_visible_module_ids,
    reset_module_binding_registry,
)
from backend.app.services.permission_isolation import check_permission
from backend.app.services.shared_module_registry import (
    create_shared_module,
    reset_shared_module_registry,
)

ORG_A = "org_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
ORG_B = "org_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.fixture(autouse=True)
def c18_consistency_state() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    reset_shared_module_registry()
    reset_module_binding_registry()
    with SessionLocal() as db:
        db.execute(delete(OperationLog))
        db.execute(delete(SharedModuleRecord))
        db.execute(delete(ModuleBindingRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(User))
        db.commit()
    yield
    reset_shared_module_registry()
    reset_module_binding_registry()
    with SessionLocal() as db:
        db.execute(delete(OperationLog))
        db.execute(delete(SharedModuleRecord))
        db.execute(delete(ModuleBindingRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(User))
        db.commit()


def _context(org_id: str, *, role: str = "member") -> OrgDataIsolationUserContext:
    return OrgDataIsolationUserContext(
        org_id=org_id,
        user_id="101",
        role=role,
        source="test",
        strict=True,
    )


def _seed_orgs_and_users() -> tuple[User, User]:
    with SessionLocal() as db:
        owner = User(
            username=f"platform_owner_{uuid4().hex}",
            password_hash=hash_password("test-only-password"),
            role="owner",
            is_active=True,
        )
        member = User(
            username=f"member_{uuid4().hex}",
            password_hash=hash_password("test-only-password"),
            role="viewer",
            is_active=True,
        )
        db.add_all([owner, member])
        db.flush()
        db.add_all(
            [
                OrganizationRecord(
                    org_id=ORG_A,
                    org_name="Org A",
                    org_type="store",
                    owner_user_id=str(owner.id),
                    status="active",
                    metadata_json={},
                ),
                OrganizationRecord(
                    org_id=ORG_B,
                    org_name="Org B",
                    org_type="store",
                    owner_user_id=str(owner.id),
                    status="active",
                    metadata_json={},
                ),
                OrgMembershipRecord(
                    membership_id="mem_" + uuid4().hex,
                    user_id=str(owner.id),
                    org_id=ORG_A,
                    role="owner",
                    status="active",
                ),
                OrgMembershipRecord(
                    membership_id="mem_" + uuid4().hex,
                    user_id=str(member.id),
                    org_id=ORG_A,
                    role="member",
                    status="active",
                ),
            ]
        )
        db.commit()
        db.refresh(owner)
        db.refresh(member)
        return owner, member


def test_repository_enforces_org_filter_and_missing_context_denies() -> None:
    _seed_orgs_and_users()
    with SessionLocal() as db, org_data_isolation_context(_context(ORG_A)):
        log_a = create_operation_log(
            db,
            actor_type="user",
            actor_id="101",
            action="tenant.action.a",
            target_type="test",
            target_id="a",
            result="success",
        )
        db.commit()
        db.refresh(log_a)

    with SessionLocal() as db, org_data_isolation_context(_context(ORG_B)):
        create_operation_log(
            db,
            actor_type="user",
            actor_id="102",
            action="tenant.action.b",
            target_type="test",
            target_id="b",
            result="success",
        )
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(ORG_A)):
        logs = list_operation_logs(db, limit=50, offset=0)
        cross_org = get_operation_log(db, log_a.operation_id + "-missing")

    assert [log.action for log in logs] == ["tenant.action.a"]
    assert cross_org is None

    with SessionLocal() as db:
        with pytest.raises(TenantIsolationError):
            list_operation_logs(db, limit=50, offset=0)


def test_cross_org_get_denies_existing_record_from_other_org() -> None:
    _seed_orgs_and_users()
    with SessionLocal() as db, org_data_isolation_context(_context(ORG_A)):
        log = create_operation_log(
            db,
            actor_type="user",
            actor_id="101",
            action="tenant.secret",
            target_type="test",
            target_id="secret",
            result="success",
        )
        db.commit()
        db.refresh(log)
        operation_id = log.operation_id

    with SessionLocal() as db, org_data_isolation_context(_context(ORG_B)):
        assert get_operation_log(db, operation_id) is None


def test_platform_owner_role_does_not_bypass_org_membership_or_data_scope() -> None:
    owner, _ = _seed_orgs_and_users()
    with SessionLocal() as db:
        bind_module_to_org(
            ModuleBindRequest(module_id="K-series", org_id=ORG_A, mode="single"),
            actor=owner,
            db=db,
        )

    with SessionLocal() as db:
        org_a_decision = check_permission(
            db,
            owner.id,
            ORG_A,
            "K-series",
            "read",
        )
        org_b_decision = check_permission(
            db,
            owner.id,
            ORG_B,
            "K-series",
            "read",
        )

    assert org_a_decision.allowed is True
    assert org_a_decision.owner_override_applied is False
    assert org_b_decision.denial_code == "c18f_user_not_in_org"

    with SessionLocal() as db, org_data_isolation_context(_context(ORG_A, role="owner")):
        create_operation_log(
            db,
            actor_type="user",
            actor_id=str(owner.id),
            action="owner.org_a",
            target_type="test",
            target_id="a",
            result="success",
        )
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(ORG_B, role="owner")):
        create_operation_log(
            db,
            actor_type="user",
            actor_id=str(owner.id),
            action="owner.org_b",
            target_type="test",
            target_id="b",
            result="success",
        )
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(ORG_A, role="owner")):
        actions = list(db.scalars(select(OperationLog.action).order_by(OperationLog.id)))

    assert actions == ["owner.org_a"]


def test_module_binding_persists_across_sessions() -> None:
    owner, _ = _seed_orgs_and_users()
    with SessionLocal() as db:
        binding = bind_module_to_org(
            ModuleBindRequest(module_id="inventory", org_id=ORG_A, mode="single"),
            actor=owner,
            db=db,
        )

    assert binding.bound_orgs == [ORG_A]

    with SessionLocal() as db:
        rows = list(db.scalars(select(ModuleBindingRecord)))
    assert [(row.org_id, row.module_id, row.status) for row in rows] == [
        (ORG_A, "inventory", "enabled")
    ]
    assert get_visible_module_ids(ORG_A) == ["inventory"]


def test_shared_module_syncs_module_binding_in_one_db_transaction() -> None:
    owner, _ = _seed_orgs_and_users()
    with SessionLocal() as db:
        module = create_shared_module(
            SharedModuleCreateRequest(
                module_id="shared-inventory",
                mode="shared",
                allowed_orgs=[ORG_A, ORG_B],
            ),
            actor=owner,
            db=db,
        )

    assert module.allowed_orgs == [ORG_A, ORG_B]
    with SessionLocal() as db:
        shared_rows = list(
            db.scalars(
                select(SharedModuleRecord).order_by(SharedModuleRecord.target_org_id)
            )
        )
        binding_rows = list(
            db.scalars(
                select(ModuleBindingRecord).order_by(ModuleBindingRecord.org_id)
            )
        )

    assert [row.target_org_id for row in shared_rows] == [ORG_A, ORG_B]
    assert [row.org_id for row in binding_rows] == [ORG_A, ORG_B]
