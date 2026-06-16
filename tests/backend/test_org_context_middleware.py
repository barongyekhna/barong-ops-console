from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.app.core.security import hash_password
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal
from backend.app.db.session import engine
from backend.app.middleware.org_context import OrgContext, build_org_context
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.module_binding import GLOBAL_MODULE_BOUND_ORG, ModuleBinding
from backend.app.schemas.organization import generate_org_id
from backend.app.services import module_binding_service as c18d_binding
from backend.app.services.event_collector import (
    clear_event_buffer,
    get_event_buffer_snapshot,
)


@pytest.fixture(autouse=True)
def c18h_state() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    clear_event_buffer()
    c18d_binding.reset_module_binding_registry()
    yield
    clear_event_buffer()
    c18d_binding.reset_module_binding_registry()


def _set_c18d_bindings(*bindings: ModuleBinding) -> None:
    with c18d_binding._MODULE_BINDINGS_LOCK:
        c18d_binding._MODULE_BINDINGS.clear()
        for binding in bindings:
            c18d_binding._MODULE_BINDINGS[binding.module_id] = binding


def _create_user(
    *,
    username: str,
    password: str,
    role: str,
) -> User:
    with SessionLocal() as db:
        user = User(
            id=uuid4().int % 1_000_000_000_000,
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _login(client: TestClient, *, username: str, password: str) -> None:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def _add_membership(*, user_id: str, org_id: str, role: str) -> None:
    with SessionLocal() as db:
        db.add(
            OrgMembershipRecord(
                membership_id="mem_" + uuid4().hex,
                user_id=user_id,
                org_id=org_id,
                role=role,
                status="active",
            )
        )
        db.commit()


def _request_with_state(**state_values: object) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/app/module/K-series/bindings",
            "raw_path": b"/api/app/module/K-series/bindings",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
    for key, value in state_values.items():
        setattr(request.state, key, value)
    return request


def _create_plain_user(*, role: str) -> User:
    with SessionLocal() as db:
        user = User(
            id=uuid4().int % 1_000_000_000_000,
            username=f"c18h_plain_{uuid4().hex}",
            password_hash="test-only-password-hash",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def test_org_context_schema_matches_c18h_contract() -> None:
    context = OrgContext(
        user_id="101",
        org_id="org_1",
        role="admin",
        module_scope=["K-series", "global-module"],
        request_id=str(uuid4()),
    )

    assert context.user_id == "101"
    assert context.org_id == "org_1"
    assert context.role == "admin"
    assert context.module_scope == ["K-series", "global-module"]
    UUID(context.request_id)


def test_build_org_context_resolves_single_membership_and_module_scope() -> None:
    _set_c18d_bindings(
        ModuleBinding(module_id="K-series", bound_orgs=["org_1"], mode="single"),
        ModuleBinding(
            module_id="global-module",
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
    user = _create_plain_user(role="viewer")
    _add_membership(user_id=str(user.id), org_id="org_1", role="member")
    request_id = str(uuid4())

    with SessionLocal() as db:
        context, source = build_org_context(
            db,
            request=_request_with_state(),
            user=db.get(User, user.id),
            auth_session=SimpleNamespace(),
            request_id=request_id,
        )

    assert context == OrgContext(
        user_id=str(user.id),
        org_id="org_1",
        role="member",
        module_scope=["K-series", "global-module"],
        request_id=request_id,
    )
    assert source == "c18c_active_membership"


def test_build_org_context_prefers_server_side_active_org() -> None:
    user = _create_plain_user(role="viewer")
    _add_membership(user_id=str(user.id), org_id="org_1", role="member")
    _add_membership(user_id=str(user.id), org_id="org_2", role="admin")
    request_id = str(uuid4())

    with SessionLocal() as db:
        context, source = build_org_context(
            db,
            request=_request_with_state(jwt_claims={"active_org_id": "org_2"}),
            user=db.get(User, user.id),
            auth_session=SimpleNamespace(),
            request_id=request_id,
        )

    assert context is not None
    assert context.org_id == "org_2"
    assert context.role == "admin"
    assert context.request_id == request_id
    assert source == "session_or_jwt"


def test_build_org_context_falls_back_to_owner_org() -> None:
    user = _create_plain_user(role="owner")
    org_id = generate_org_id()
    request_id = str(uuid4())
    with SessionLocal() as db:
        db.add(
            OrganizationRecord(
                org_id=org_id,
                org_name="Owner Org",
                org_type="store",
                owner_user_id=str(user.id),
                status="active",
                metadata_json={},
            )
        )
        db.commit()

    with SessionLocal() as db:
        context, source = build_org_context(
            db,
            request=_request_with_state(),
            user=db.get(User, user.id),
            auth_session=SimpleNamespace(),
            request_id=request_id,
        )

    assert context is not None
    assert context.org_id == org_id
    assert context.role == "owner"
    assert context.request_id == request_id
    assert source == "fallback_owner_org"


def test_c18h_injects_org_context_for_c18f_and_c17(
    auth_client: TestClient,
) -> None:
    _set_c18d_bindings(
        ModuleBinding(module_id="K-series", bound_orgs=["org_1"], mode="single"),
        ModuleBinding(
            module_id="global-module",
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
    username = "c18h_member"
    password = "c18h-example-only-password"
    user = _create_user(username=username, password=password, role="viewer")
    _add_membership(user_id=str(user.id), org_id="org_1", role="member")
    _login(auth_client, username=username, password=password)

    response = auth_client.get(
        "/api/app/module/K-series/bindings",
        headers={"X-Request-ID": "frontend-supplied-request-id"},
    )

    assert response.status_code == 200
    assert response.json()["module_id"] == "K-series"
    request_id = response.headers["X-Request-ID"]
    assert request_id != "frontend-supplied-request-id"
    UUID(request_id)
    assert response.headers["X-Trace-ID"] == request_id

    events = get_event_buffer_snapshot()
    injected = next(event for event in events if event.event_type == "org_context.injected")
    assert injected.context_id == request_id
    assert injected.user_id == str(user.id)
    assert injected.payload["org_id"] == "org_1"
    assert injected.payload["role"] == "member"
    assert injected.payload["module_scope"] == ["K-series", "global-module"]
    assert injected.payload["resolution_source"] == "c18c_active_membership"

    permission_check = next(
        event for event in events if event.event_type == "permission_isolation.check"
    )
    assert permission_check.context_id == request_id
    assert permission_check.payload["org_id"] == "org_1"
    assert permission_check.payload["module_id"] == "K-series"

    api_response = [
        event for event in events if event.event_type == "api.response.completed"
    ][-1]
    assert api_response.context_id == request_id


def test_c18h_rejects_frontend_supplied_org_context(
    auth_client: TestClient,
) -> None:
    username = "c18h_reject_frontend_org"
    password = "c18h-example-only-password"
    user = _create_user(username=username, password=password, role="viewer")
    _add_membership(user_id=str(user.id), org_id="org_1", role="member")
    _login(auth_client, username=username, password=password)

    query_response = auth_client.get(
        "/api/app/module/K-series/bindings?org_id=org_2"
    )
    header_response = auth_client.get(
        "/api/app/module/K-series/bindings",
        headers={"X-Active-Org-ID": "org_2"},
    )

    assert query_response.status_code == 400
    assert header_response.status_code == 400
    assert query_response.json()["detail"] == (
        "org_id must come from the authenticated server context."
    )
    assert header_response.json()["detail"] == (
        "org_id must come from the authenticated server context."
    )


def test_c18h_falls_back_to_owner_org_without_membership(
    auth_client: TestClient,
) -> None:
    username = "c18h_owner"
    password = "c18h-example-only-password"
    user = _create_user(username=username, password=password, role="owner")
    org_id = generate_org_id()
    with SessionLocal() as db:
        db.add(
            OrganizationRecord(
                org_id=org_id,
                org_name="Owner Org",
                org_type="store",
                owner_user_id=str(user.id),
                status="active",
                metadata_json={},
            )
        )
        db.commit()
    _login(auth_client, username=username, password=password)

    response = auth_client.get("/api/app/operation-logs")

    assert response.status_code == 200
    injected = next(
        event
        for event in get_event_buffer_snapshot()
        if event.event_type == "org_context.injected"
    )
    assert injected.payload["org_id"] == org_id
    assert injected.payload["role"] == "owner"
    assert injected.payload["resolution_source"] == "fallback_owner_org"
