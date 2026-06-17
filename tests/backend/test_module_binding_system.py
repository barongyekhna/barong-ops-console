from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.user import User
from backend.app.schemas.module_binding import (
    GLOBAL_MODULE_BOUND_ORG,
    MODULE_BINDING_DATA_STRUCTURE,
    ModuleBindRequest,
    ModuleBinding,
    get_module_binding_api_design,
    get_module_binding_c18_integration,
    get_module_binding_completion_status,
    get_module_binding_data_structure_design,
    get_module_binding_mode_model,
    get_module_binding_permission_model,
    get_module_visibility_algorithm,
)
from backend.app.services.module_binding_service import (
    ModuleBindingPermissionDeniedError,
    bind_module_to_org,
    get_module_binding_for_actor,
    get_visible_module_ids,
    get_visible_modules,
    list_org_visible_modules_for_actor,
    reset_module_binding_registry,
)


def _user(*, user_id: int, role: str) -> User:
    return User(
        id=user_id,
        username=f"c18d_user_{user_id}",
        password_hash="test-only-password-hash",
        role=role,
        is_active=True,
    )


def _membership(*, user_id: int, org_id: str, role: str) -> OrgMembershipRecord:
    return OrgMembershipRecord(
        membership_id="mem_" + uuid4().hex,
        user_id=str(user_id),
        org_id=org_id,
        role=role,
        status="active",
    )


@pytest.fixture(autouse=True)
def c18d_registry() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    reset_module_binding_registry()
    yield
    reset_module_binding_registry()


@pytest.fixture
def c18d_memberships() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        db.execute(delete(OrgMembershipRecord))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(OrgMembershipRecord))
        db.commit()


def test_c18d_module_binding_schema_and_mode_rules() -> None:
    single = ModuleBinding(
        module_id="K-series",
        bound_orgs=["org_1"],
        mode="single",
    )
    multi = ModuleBinding(
        module_id="seo-engine",
        bound_orgs=["org_1", "org_2"],
        mode="multi",
    )
    global_binding = ModuleBinding(
        module_id="product-knowledge",
        bound_orgs=[GLOBAL_MODULE_BOUND_ORG],
        mode="global",
    )

    assert single.module_id == "K-series"
    assert single.bound_orgs == ["org_1"]
    assert multi.bound_orgs == ["org_1", "org_2"]
    assert global_binding.bound_orgs == ["ALL"]
    assert global_binding.enabled is True

    with pytest.raises(ValidationError):
        ModuleBinding(
            module_id="K series",
            bound_orgs=["org_1"],
            mode="single",
        )

    with pytest.raises(ValidationError):
        ModuleBinding(
            module_id="K-series",
            bound_orgs=["org_1", "org_2"],
            mode="single",
        )

    with pytest.raises(ValidationError):
        ModuleBinding(
            module_id="K-series",
            bound_orgs=["ALL"],
            mode="multi",
        )


def test_c18d_design_outputs_match_required_contract() -> None:
    data_structure = get_module_binding_data_structure_design()
    mode_model = get_module_binding_mode_model()
    algorithm = get_module_visibility_algorithm()
    api_design = get_module_binding_api_design()
    permissions = get_module_binding_permission_model()
    integration = get_module_binding_c18_integration()
    completion = get_module_binding_completion_status()

    assert data_structure.primary_key == "id"
    assert data_structure.module_id_unique is False
    assert data_structure.org_id_module_id_pair_is_unique is True
    assert data_structure.bound_orgs_type == "derived_from_rows"
    assert data_structure.allowed_modes == ("single", "multi", "global")
    assert data_structure.migration_executed is True
    assert data_structure.grants_data_access is False
    assert "org_id: str" in MODULE_BINDING_DATA_STRUCTURE

    assert {rule.mode for rule in mode_model.rules} == {
        "single",
        "multi",
        "global",
    }
    assert all(rule.cross_org_data_access_allowed is False for rule in mode_model.rules)
    assert algorithm.expression == (
        'enabled AND (mode == "global" OR user_org_id in bound_orgs)'
    )
    assert algorithm.grants_data_access is False

    routes = {(endpoint.method, endpoint.path) for endpoint in api_design.endpoints}
    assert routes == {
        ("POST", "/module/bind"),
        ("GET", "/module/{module_id}/bindings"),
        ("GET", "/org/{org_id}/modules"),
    }
    assert permissions.owner_can_bind_any_module is True
    assert permissions.org_admin_can_modify_bindings is False
    assert permissions.member_can_view_visible_modules is True
    assert integration.all_data_access_requires_c18c_org_id_filter is True
    assert integration.module_visibility_equals_data_access is False
    assert completion.cross_org_data_logic_added is False


def test_c18d_visibility_algorithm_for_single_multi_and_global() -> None:
    owner = _user(user_id=1, role="owner")
    bind_module_to_org(
        ModuleBindRequest(module_id="K-series", org_id="org_1", mode="single"),
        actor=owner,
    )
    bind_module_to_org(
        ModuleBindRequest(module_id="C-series", org_id="org_1", mode="multi"),
        actor=owner,
    )
    bind_module_to_org(
        ModuleBindRequest(module_id="C-series", org_id="org_2", mode="multi"),
        actor=owner,
    )
    bind_module_to_org(
        ModuleBindRequest(module_id="attendance", org_id="org_1", mode="global"),
        actor=owner,
    )

    assert get_visible_module_ids("org_1") == [
        "K-series",
        "C-series",
        "attendance",
    ]
    assert get_visible_module_ids("org_2") == ["C-series", "attendance"]
    assert get_visible_module_ids("org_3") == ["attendance"]

    org_2_bindings = get_visible_modules("org_2")
    assert {binding.module_id for binding in org_2_bindings} == {
        "C-series",
        "attendance",
    }


def test_c18d_non_owner_views_require_active_c18c_membership(
    c18d_memberships: None,
) -> None:
    owner = _user(user_id=10, role="owner")
    admin = _user(user_id=11, role="operator")
    member = _user(user_id=12, role="viewer")
    outsider = _user(user_id=13, role="viewer")

    bind_module_to_org(
        ModuleBindRequest(module_id="seo-engine", org_id="org_1", mode="multi"),
        actor=owner,
    )
    bind_module_to_org(
        ModuleBindRequest(module_id="seo-engine", org_id="org_2", mode="multi"),
        actor=owner,
    )
    bind_module_to_org(
        ModuleBindRequest(module_id="product-knowledge", org_id="org_1", mode="global"),
        actor=owner,
    )

    with SessionLocal() as db:
        db.add(_membership(user_id=11, org_id="org_1", role="admin"))
        db.add(_membership(user_id=12, org_id="org_2", role="member"))
        db.commit()

        admin_binding = get_module_binding_for_actor(
            db,
            module_id="seo-engine",
            actor=admin,
        )
        member_modules = list_org_visible_modules_for_actor(
            db,
            org_id="org_2",
            actor=member,
        )

        assert admin_binding.bound_orgs == ["org_1"]
        assert member_modules.visible_modules == [
            "seo-engine",
            "product-knowledge",
        ]
        assert member_modules.data_access_granted is False
        assert member_modules.c18c_org_id_isolation_required is True

        with pytest.raises(ModuleBindingPermissionDeniedError):
            list_org_visible_modules_for_actor(db, org_id="org_1", actor=outsider)

        with pytest.raises(ModuleBindingPermissionDeniedError):
            list_org_visible_modules_for_actor(db, org_id="org_1", actor=owner)

        with pytest.raises(ModuleBindingPermissionDeniedError):
            get_module_binding_for_actor(
                db,
                module_id="seo-engine",
                actor=owner,
            )

        with pytest.raises(ModuleBindingPermissionDeniedError):
            get_module_binding_for_actor(
                db,
                module_id="product-knowledge",
                actor=outsider,
            )


def test_c18d_api_routes_are_registered() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/module" in route.path or route.path.endswith("/modules")
    }

    assert ("/api/app/module/bind", ("POST",)) in routes
    assert ("/api/app/module/{module_id}/bindings", ("GET",)) in routes
    assert ("/api/app/org/{org_id}/modules", ("GET",)) in routes
