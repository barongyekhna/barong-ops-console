from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.app.core.security import hash_password
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.user import User
from backend.app.schemas.module_binding import GLOBAL_MODULE_BOUND_ORG, ModuleBinding
from backend.app.schemas.permission import (
    Permission,
    PermissionAction,
    PermissionRole,
    get_permission_api_middleware_design,
    get_permission_c18_integration,
    get_permission_granularity_model,
    get_permission_isolation_completion_status,
    get_permission_module_isolation_rules,
    get_permission_org_isolation_rules,
    get_permission_owner_override_logic,
    get_permission_security_boundary,
)
from backend.app.services import module_binding_service as c18d_binding
from backend.app.services.permission_isolation import check_permission


@pytest.fixture(autouse=True)
def c18f_state() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    c18d_binding.reset_module_binding_registry()
    with SessionLocal() as db:
        db.execute(delete(OrgMembershipRecord))
        db.commit()
    yield
    c18d_binding.reset_module_binding_registry()
    with SessionLocal() as db:
        db.execute(delete(OrgMembershipRecord))
        db.commit()


def _create_user(db, *, role: str, username: str | None = None) -> User:
    user = User(
        username=username or f"c18f_{role}_{uuid4().hex}",
        password_hash=hash_password("c18f-example-only-password"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _add_membership(
    db,
    *,
    user: User,
    org_id: str,
    role: str,
    status: str = "active",
) -> None:
    db.add(
        OrgMembershipRecord(
            membership_id="mem_" + uuid4().hex,
            user_id=str(user.id),
            org_id=org_id,
            role=role,
            status=status,
        )
    )


def _set_c18d_bindings(*bindings: ModuleBinding) -> None:
    with c18d_binding._MODULE_BINDINGS_LOCK:
        c18d_binding._MODULE_BINDINGS.clear()
        for binding in bindings:
            c18d_binding._MODULE_BINDINGS[binding.module_id] = binding


def test_c18f_design_outputs_define_required_permission_boundary() -> None:
    permission = Permission(
        user_id=" user-1 ",
        org_id=" org_1 ",
        module_id="K-series",
        actions=[
            PermissionAction.READ,
            PermissionAction.READ,
            PermissionAction.WRITE,
        ],
        role=PermissionRole.ADMIN,
    )
    org_rules = get_permission_org_isolation_rules()
    module_rules = get_permission_module_isolation_rules()
    owner_override = get_permission_owner_override_logic()
    granularity = get_permission_granularity_model()
    middleware = get_permission_api_middleware_design()
    integration = get_permission_c18_integration()
    boundary = get_permission_security_boundary()
    completion = get_permission_isolation_completion_status()

    assert permission.model_dump(mode="json") == {
        "user_id": "user-1",
        "org_id": "org_1",
        "module_id": "K-series",
        "actions": ["read", "write"],
        "role": "admin",
    }
    assert org_rules.active_c18c_membership_required is True
    assert org_rules.cross_org_permission_inheritance_allowed is False
    assert module_rules.c18d_binding_required is True
    assert module_rules.module_visibility_is_not_execution_permission is True
    assert owner_override.owner_bypasses_permission_check is True
    assert granularity.k_series_actions == ("read", "write", "execute")
    assert granularity.c_series_actions == ("admin",)
    assert granularity.p_series_actions == ("write",)
    assert "workflow_execution_c15" in middleware.intercepts
    assert "ai_execution_c14" in middleware.intercepts
    assert "logs_access_c17" in middleware.intercepts
    assert integration.uses_c18c_org_membership is True
    assert integration.uses_c18d_module_binding is True
    assert integration.c18e_grants_permission is False
    assert boundary.permission_equals_visibility is False
    assert boundary.permission_equals_data_access is False
    assert boundary.storage_changes_added is False
    assert completion.migration_executed is False
    assert completion.ui_implemented is False


def test_c18f_check_permission_enforces_owner_org_module_and_action_rules() -> None:
    _set_c18d_bindings(
        ModuleBinding(
            module_id="K-series",
            bound_orgs=["org_1"],
            mode="single",
        ),
        ModuleBinding(
            module_id="C-series",
            bound_orgs=["org_1"],
            mode="single",
        ),
        ModuleBinding(
            module_id="P-series",
            bound_orgs=["org_1"],
            mode="single",
        ),
        ModuleBinding(
            module_id="global-module",
            bound_orgs=[GLOBAL_MODULE_BOUND_ORG],
            mode="global",
        ),
    )

    with SessionLocal() as db:
        owner = _create_user(db, role="owner")
        admin = _create_user(db, role="operator")
        member = _create_user(db, role="viewer")
        org_owner = _create_user(db, role="operator")
        _add_membership(db, user=admin, org_id="org_1", role="admin")
        _add_membership(db, user=admin, org_id="org_2", role="admin", status="suspended")
        _add_membership(db, user=member, org_id="org_1", role="member")
        _add_membership(db, user=org_owner, org_id="org_1", role="owner")
        db.commit()

        owner_decision = check_permission(
            db,
            owner.id,
            "org_any",
            "unbound-module",
            "delete",
        )
        admin_write = check_permission(db, admin.id, "org_1", "K-series", "write")
        admin_admin = check_permission(db, admin.id, "org_1", "K-series", "admin")
        member_read = check_permission(db, member.id, "org_1", "K-series", "read")
        member_write = check_permission(db, member.id, "org_1", "K-series", "write")
        cross_org = check_permission(db, admin.id, "org_2", "K-series", "read")
        unbound = check_permission(db, admin.id, "org_1", "unbound-module", "read")
        c_series_read = check_permission(db, org_owner.id, "org_1", "C-series", "read")
        c_series_admin = check_permission(
            db,
            org_owner.id,
            "org_1",
            "C-series",
            "admin",
        )
        p_series_read = check_permission(db, admin.id, "org_1", "P-series", "read")
        p_series_write = check_permission(db, admin.id, "org_1", "P-series", "write")
        global_read = check_permission(db, member.id, "org_1", "global-module", "read")

    assert owner_decision.allowed is True
    assert owner_decision.owner_override_applied is True
    assert owner_decision.c18c_org_membership_checked is False
    assert owner_decision.c18d_module_binding_checked is False

    assert admin_write.allowed is True
    assert admin_write.permission is not None
    assert admin_write.permission.actions == [
        PermissionAction.READ,
        PermissionAction.WRITE,
        PermissionAction.EXECUTE,
    ]
    assert admin_admin.denial_code == "c18f_role_action_denied"
    assert member_read.allowed is True
    assert member_write.denial_code == "c18f_role_action_denied"
    assert cross_org.denial_code == "c18f_user_not_in_org"
    assert unbound.denial_code == "c18f_module_not_bound_to_org"
    assert c_series_read.denial_code == "c18f_module_action_denied"
    assert c_series_admin.allowed is True
    assert c_series_admin.permission is not None
    assert c_series_admin.permission.actions == [PermissionAction.ADMIN]
    assert p_series_read.denial_code == "c18f_module_action_denied"
    assert p_series_write.allowed is True
    assert p_series_write.permission is not None
    assert p_series_write.permission.actions == [PermissionAction.WRITE]
    assert global_read.allowed is True


def test_c18f_api_middleware_uses_injected_org_context_and_rejects_frontend_org(
    auth_client: TestClient,
) -> None:
    _set_c18d_bindings(
        ModuleBinding(
            module_id="K-series",
            bound_orgs=["org_1"],
            mode="single",
        )
    )
    username = f"c18f_member_{uuid4().hex}"
    password = "c18f-example-only-password"
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role="viewer",
            is_active=True,
        )
        db.add(user)
        db.flush()
        _add_membership(db, user=user, org_id="org_1", role="member")
        db.commit()

    login = auth_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200

    allowed = auth_client.get("/api/app/module/K-series/bindings")
    denied = auth_client.get("/api/app/module/K-series/bindings?org_id=org_2")

    assert allowed.status_code == 200
    assert allowed.json()["module_id"] == "K-series"
    assert denied.status_code == 400
    assert denied.json()["detail"] == (
        "org_id must come from the authenticated server context."
    )
