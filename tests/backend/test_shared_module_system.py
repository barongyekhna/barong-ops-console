from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.user import User
from backend.app.schemas.module_binding import GLOBAL_MODULE_BOUND_ORG
from backend.app.schemas.shared_module import (
    SHARED_MODULE_DATA_STRUCTURE,
    SharedModule,
    SharedModuleCreateRequest,
    SharedModuleUpdateOrgsRequest,
    get_shared_module_api_design,
    get_shared_module_availability_logic,
    get_shared_module_c18_integration,
    get_shared_module_completion_status,
    get_shared_module_data_isolation_proof,
    get_shared_module_execution_flow,
    get_shared_module_mode_definition,
    get_shared_module_security_boundary,
)
from backend.app.services import module_binding_service as c18d_binding
from backend.app.services.shared_module_registry import (
    SharedModuleOrgContextRequiredError,
    create_shared_module,
    execute_module,
    is_module_available,
    list_org_shared_modules_for_actor,
    reset_shared_module_registry,
    update_shared_module_orgs,
)


def _user(*, user_id: int, role: str) -> User:
    return User(
        id=user_id,
        username=f"c18i_user_{user_id}",
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
def c18i_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.shared_module_registry.emit_event",
        lambda **kwargs: None,
    )
    Base.metadata.create_all(bind=engine, checkfirst=True)
    reset_shared_module_registry()
    c18d_binding.reset_module_binding_registry()
    with SessionLocal() as db:
        db.execute(delete(OrgMembershipRecord))
        db.commit()
    yield
    reset_shared_module_registry()
    c18d_binding.reset_module_binding_registry()
    with SessionLocal() as db:
        db.execute(delete(OrgMembershipRecord))
        db.commit()


def test_c18i_shared_module_schema_and_mode_rules() -> None:
    single = SharedModule(
        module_id="attendance",
        mode="single",
        allowed_orgs=["org_1"],
    )
    multi = SharedModule(
        module_id="attendance.multi",
        mode="multi",
        allowed_orgs=["org_1", "org_2"],
    )
    global_module = SharedModule(
        module_id="attendance-global",
        mode="global",
        allowed_orgs=["ALL"],
    )
    shared = SharedModule(
        module_id="attendance_shared",
        mode="shared",
        allowed_orgs=["org_1", "org_2"],
    )

    assert single.allowed_orgs == ["org_1"]
    assert multi.allowed_orgs == ["org_1", "org_2"]
    assert global_module.allowed_orgs == ["ALL"]
    assert shared.mode == "shared"
    assert shared.enabled is True

    with pytest.raises(ValidationError):
        SharedModule(module_id="bad module", mode="shared", allowed_orgs=["org_1"])

    with pytest.raises(ValidationError):
        SharedModule(
            module_id="attendance",
            mode="single",
            allowed_orgs=["org_1", "org_2"],
        )

    with pytest.raises(ValidationError):
        SharedModule(module_id="attendance", mode="shared", allowed_orgs=["ALL"])


def test_c18i_design_outputs_match_required_contract() -> None:
    modes = get_shared_module_mode_definition()
    availability = get_shared_module_availability_logic()
    execution = get_shared_module_execution_flow()
    api_design = get_shared_module_api_design()
    security = get_shared_module_security_boundary()
    integration = get_shared_module_c18_integration()
    proof = get_shared_module_data_isolation_proof()
    completion = get_shared_module_completion_status()

    assert {rule.mode for rule in modes.rules} == {
        "single",
        "multi",
        "global",
        "shared",
    }
    assert availability.function_name == "is_module_available"
    assert availability.grants_data_access is False
    assert execution.shared_module_equals_shared_data is False
    assert execution.runtime_state_shared is False
    assert {
        (endpoint.method, endpoint.path)
        for endpoint in api_design.endpoints
    } == {
        ("POST", "/module/shared/create"),
        ("POST", "/module/shared/update-orgs"),
        ("GET", "/module/shared/list"),
        ("GET", "/org/{org_id}/shared-modules"),
    }
    assert security.module_logic_can_be_shared is True
    assert security.cross_org_data_access_allowed is False
    assert integration.c18c_org_membership_required is True
    assert integration.shared_mode_maps_to_c18d_multi_binding is True
    assert integration.c18a_to_c18h_files_modified is False
    assert proof.registry_stores_business_data is False
    assert proof.c18g_rejects_cross_org_writes is True
    assert completion.migration_executed is False
    assert completion.cross_org_data_logic_added is False
    assert "mode: single | multi | global | shared" in SHARED_MODULE_DATA_STRUCTURE


def test_c18i_availability_logic_for_single_multi_global_shared_disabled() -> None:
    single = SharedModule(
        module_id="single-attendance",
        mode="single",
        allowed_orgs=["org_1"],
    )
    multi = SharedModule(
        module_id="multi-attendance",
        mode="multi",
        allowed_orgs=["org_1", "org_2"],
    )
    global_module = SharedModule(
        module_id="global-attendance",
        mode="global",
        allowed_orgs=["ALL"],
    )
    shared = SharedModule(
        module_id="shared-attendance",
        mode="shared",
        allowed_orgs=["org_2", "org_3"],
    )
    disabled = SharedModule(
        module_id="disabled-attendance",
        mode="shared",
        allowed_orgs=["org_1"],
        enabled=False,
    )

    assert is_module_available("org_1", single) is True
    assert is_module_available("org_2", single) is False
    assert is_module_available("org_2", multi) is True
    assert is_module_available("org_3", multi) is False
    assert is_module_available("org_any", global_module) is True
    assert is_module_available("org_3", shared) is True
    assert is_module_available("org_4", shared) is False
    assert is_module_available("org_1", disabled) is False


def test_c18i_create_update_shared_module_syncs_c18d_binding() -> None:
    owner = _user(user_id=1, role="owner")

    module = create_shared_module(
        SharedModuleCreateRequest(
            module_id="attendance",
            mode="shared",
            allowed_orgs=["org_1", "org_2"],
        ),
        actor=owner,
    )

    assert module.mode == "shared"
    assert c18d_binding.get_visible_module_ids("org_1") == ["attendance"]
    assert c18d_binding.get_visible_module_ids("org_2") == ["attendance"]
    assert c18d_binding.get_visible_module_ids("org_3") == []
    c18d_shared_binding = c18d_binding.get_module_binding("attendance")
    assert c18d_shared_binding.mode == "multi"
    assert c18d_shared_binding.bound_orgs == ["org_1", "org_2"]

    updated = update_shared_module_orgs(
        SharedModuleUpdateOrgsRequest(
            module_id="attendance",
            allowed_orgs=["org_1", "org_2", "org_3"],
        ),
        actor=owner,
    )

    assert updated.allowed_orgs == ["org_1", "org_2", "org_3"]
    assert c18d_binding.get_visible_module_ids("org_3") == ["attendance"]


def test_c18i_global_module_syncs_c18d_global_binding() -> None:
    owner = _user(user_id=2, role="owner")

    create_shared_module(
        SharedModuleCreateRequest(
            module_id="attendance-global",
            mode="global",
            allowed_orgs=["ALL"],
        ),
        actor=owner,
    )

    binding = c18d_binding.get_module_binding("attendance-global")
    assert binding.mode == "global"
    assert binding.bound_orgs == [GLOBAL_MODULE_BOUND_ORG]
    assert c18d_binding.get_visible_module_ids("org_any") == ["attendance-global"]


def test_c18i_org_query_uses_c18c_membership_and_grants_no_data_access() -> None:
    owner = _user(user_id=10, role="owner")
    admin = _user(user_id=11, role="operator")
    outsider = _user(user_id=12, role="viewer")

    create_shared_module(
        SharedModuleCreateRequest(
            module_id="attendance",
            mode="shared",
            allowed_orgs=["org_1", "org_2"],
        ),
        actor=owner,
    )
    create_shared_module(
        SharedModuleCreateRequest(
            module_id="payroll",
            mode="single",
            allowed_orgs=["org_2"],
        ),
        actor=owner,
    )

    with SessionLocal() as db:
        db.add(_membership(user_id=11, org_id="org_1", role="admin"))
        db.commit()

        response = list_org_shared_modules_for_actor(
            db,
            org_id="org_1",
            actor=admin,
        )

        assert [module.module_id for module in response.available_modules] == [
            "attendance"
        ]
        assert response.module_logic_shared is True
        assert response.shared_module_equals_shared_data is False
        assert response.data_access_granted is False
        assert response.c18g_data_isolation_required is True
        assert response.runtime_state_shared is False

        with pytest.raises(PermissionError):
            list_org_shared_modules_for_actor(db, org_id="org_1", actor=outsider)


def test_c18i_execution_flow_requires_c18h_org_context_and_denies_unavailable() -> None:
    owner = _user(user_id=20, role="owner")
    create_shared_module(
        SharedModuleCreateRequest(
            module_id="attendance",
            mode="shared",
            allowed_orgs=["org_1", "org_2"],
        ),
        actor=owner,
    )

    with pytest.raises(SharedModuleOrgContextRequiredError):
        execute_module(SimpleNamespace(id=21), "attendance")

    denied = execute_module(SimpleNamespace(id=22, org_id="org_3"), "attendance")
    allowed = execute_module(SimpleNamespace(id=23, org_id="org_2"), "attendance")

    assert denied.allowed is False
    assert denied.denied is True
    assert denied.c18g_data_isolation_required is True
    assert denied.runtime_state_shared is False
    assert allowed.allowed is True
    assert allowed.denied is False
    assert allowed.data_access_granted_by_registry is False


def test_c18i_api_routes_are_registered() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if "/shared" in route.path
    }

    assert ("/api/app/module/shared/create", ("POST",)) in routes
    assert ("/api/app/module/shared/update-orgs", ("POST",)) in routes
    assert ("/api/app/module/shared/list", ("GET",)) in routes
    assert ("/api/app/org/{org_id}/shared-modules", ("GET",)) in routes
