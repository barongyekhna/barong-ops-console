from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.module_binding import ModuleBindingRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.repositories import module_bindings as binding_repo
from backend.app.schemas.module_binding import GLOBAL_MODULE_BOUND_ORG, ModuleBinding
from backend.app.schemas.module_visibility import (
    get_module_visibility_algorithm,
    get_module_visibility_api_design,
    get_module_visibility_completion_status,
    get_module_visibility_data_flow,
    get_module_visibility_frontend_rules,
    get_module_visibility_security_boundary,
)
from backend.app.services import module_binding_service as c18d_binding
from backend.app.services.module_visibility_service import (
    ModuleVisibilityActiveOrgContextRequiredError,
    ModuleVisibilityMembershipRequiredError,
    get_visible_modules,
)


def _membership(
    *,
    user_id: int | str,
    org_id: str,
    role: str = "member",
    status: str = "active",
) -> OrgMembershipRecord:
    return OrgMembershipRecord(
        membership_id="mem_" + uuid4().hex,
        user_id=str(user_id),
        org_id=org_id,
        role=role,
        status=status,
    )


def _set_c18d_bindings(*bindings: ModuleBinding) -> None:
    with SessionLocal() as db:
        binding_repo.clear_module_bindings(db)
        for binding in bindings:
            for org_id in binding.bound_orgs:
                db.add(
                    ModuleBindingRecord(
                        org_id=org_id,
                        module_id=binding.module_id,
                        status="enabled" if binding.enabled else "disabled",
                        created_at=binding.created_at,
                        updated_at=binding.updated_at,
                    )
                )
        db.commit()


@pytest.fixture(autouse=True)
def c18e_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.module_visibility_service.emit_event",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.services.module_visibility_service.list_module_manifests",
        lambda: [
            SimpleNamespace(
                module_key="business.products",
                display_name="Products",
            ),
        ],
    )
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


def test_c18e_design_outputs_define_visibility_only_contract() -> None:
    algorithm = get_module_visibility_algorithm()
    api_design = get_module_visibility_api_design()
    data_flow = get_module_visibility_data_flow()
    frontend = get_module_visibility_frontend_rules()
    security = get_module_visibility_security_boundary()
    completion = get_module_visibility_completion_status()

    assert algorithm.expression == (
        'module.enabled == true AND (module.mode == "global" OR user.org_id in module.bound_orgs)'
    )
    assert algorithm.uses_c18c_org_membership is True
    assert algorithm.uses_c18d_module_binding is True
    assert algorithm.grants_data_access is False

    assert api_design.endpoint.path == "/org/{org_id}/visible-modules"
    assert api_design.endpoint.requires_active_c18c_membership is True
    assert api_design.endpoint.reads_c18d_module_bindings is True
    assert api_design.permission_system_implemented is False

    assert data_flow.org_switch_changes_visible_modules is True
    assert frontend.render_only_visible_modules is True
    assert frontend.direct_module_registry_calls_allowed is False
    assert frontend.bypass_org_filter_allowed is False
    assert security.visible_modules_equals_data_access_permission is False
    assert security.c18e_decides_data_access is False
    assert completion.migration_executed is True
    assert completion.ui_implemented is False


def test_c18e_get_visible_modules_filters_single_multi_global_and_disabled() -> None:
    _set_c18d_bindings(
        ModuleBinding(
            module_id="K-series",
            bound_orgs=["org_1"],
            mode="single",
        ),
        ModuleBinding(
            module_id="seo-engine",
            bound_orgs=["org_1", "org_2"],
            mode="multi",
        ),
        ModuleBinding(
            module_id="business.products",
            bound_orgs=[GLOBAL_MODULE_BOUND_ORG],
            mode="global",
        ),
        ModuleBinding(
            module_id="disabled-module",
            bound_orgs=["org_1"],
            mode="single",
            enabled=False,
        ),
    )

    with SessionLocal() as db:
        db.add(_membership(user_id=101, org_id="org_1", role="admin"))
        db.add(_membership(user_id=101, org_id="org_2", role="member"))
        db.commit()

        org_1 = get_visible_modules(db, user_id=101, active_org_id="org_1")
        org_2 = get_visible_modules(db, user_id=101, active_org_id="org_2")

    assert org_1.model_dump() == {
        "user_id": "101",
        "org_id": "org_1",
        "visible_modules": [
            {
                "module_id": "K-series",
                "module_name": "K-series",
                "mode": "single",
            },
            {
                "module_id": "seo-engine",
                "module_name": "seo-engine",
                "mode": "multi",
            },
            {
                "module_id": "business.products",
                "module_name": "Products",
                "mode": "global",
            },
        ],
    }
    assert org_2.model_dump() == {
        "user_id": "101",
        "org_id": "org_2",
        "visible_modules": [
            {
                "module_id": "seo-engine",
                "module_name": "seo-engine",
                "mode": "multi",
            },
            {
                "module_id": "business.products",
                "module_name": "Products",
                "mode": "global",
            },
        ],
    }


def test_c18e_multi_org_user_requires_active_org_context() -> None:
    with SessionLocal() as db:
        db.add(_membership(user_id=201, org_id="org_1"))
        db.add(_membership(user_id=201, org_id="org_2"))
        db.commit()

        with pytest.raises(ModuleVisibilityActiveOrgContextRequiredError):
            get_visible_modules(db, user_id=201)


def test_c18e_requested_org_must_be_active_c18c_membership() -> None:
    _set_c18d_bindings(
        ModuleBinding(
            module_id="business.products",
            bound_orgs=[GLOBAL_MODULE_BOUND_ORG],
            mode="global",
        )
    )

    with SessionLocal() as db:
        db.add(_membership(user_id=301, org_id="org_1", status="active"))
        db.add(_membership(user_id=301, org_id="org_2", status="suspended"))
        db.commit()

        with pytest.raises(ModuleVisibilityMembershipRequiredError):
            get_visible_modules(db, user_id=301, active_org_id="org_2")

        with pytest.raises(ModuleVisibilityMembershipRequiredError):
            get_visible_modules(db, user_id=999, active_org_id="org_1")


def test_c18e_api_route_is_registered() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if route.path.endswith("/visible-modules")
    }

    assert ("/api/app/org/{org_id}/visible-modules", ("GET",)) in routes
