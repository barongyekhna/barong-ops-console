import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.roles import (
    ASSIGNABLE_USER_ROLES,
    ROLE_BOT_AGENT,
    ROLE_MODULE_ADMIN,
    ROLE_OPERATOR,
    ROLE_OWNER,
    ROLE_REVIEWER,
    ROLE_SUPER_ADMIN,
    ROLE_VIEWER,
    STANDARD_ROLES,
    UNASSIGNABLE_USER_ROLES,
)
from backend.app.core.security import hash_password, verify_password
from backend.app.db.session import SessionLocal
from backend.app.models.operation_log import OperationLog
from backend.app.models.user import User

VIEWER_USERNAME = "managed_viewer"
VIEWER_PASSWORD = "example-only-viewer-password"
RESET_PASSWORD = "example-only-reset-password"
OWNER_ROLE_PASSWORD = "example-only-owner-role-password"


def create_db_user(
    *,
    username: str,
    password: str,
    role: str = "viewer",
    is_active: bool = True,
) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user.id


def create_user_via_api(
    client: TestClient,
    *,
    username: str = VIEWER_USERNAME,
    password: str = VIEWER_PASSWORD,
    role: str = "viewer",
    is_active: bool = True,
) -> dict:
    response = client.post(
        "/users",
        json={
            "username": username,
            "password": password,
            "role": role,
            "is_active": is_active,
        },
    )
    assert response.status_code == 201
    return response.json()


def assert_no_password_hash(payload: object) -> None:
    assert "password_hash" not in json.dumps(payload, sort_keys=True)


def test_users_requires_owner_auth(
    auth_client: TestClient,
) -> None:
    user_id = create_db_user(
        username="managed_operator",
        password="example-only-operator-password",
        role="operator",
    )
    login_response = auth_client.post(
        "/auth/login",
        json={
            "username": "managed_operator",
            "password": "example-only-operator-password",
        },
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["id"] == user_id
    session_id = login_response.cookies.get("barong_ops_session")
    assert session_id

    auth_client.cookies.clear()
    unauthenticated = auth_client.get("/users")
    forbidden = auth_client.get(
        "/users",
        headers={"Cookie": f"barong_ops_session={session_id}"},
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403

    unauthenticated_roles = auth_client.get("/users/roles")
    forbidden_roles = auth_client.get(
        "/users/roles",
        headers={"Cookie": f"barong_ops_session={session_id}"},
    )

    assert unauthenticated_roles.status_code == 401
    assert forbidden_roles.status_code == 403


@pytest.mark.parametrize(
    "role",
    [ROLE_VIEWER, ROLE_OPERATOR, ROLE_REVIEWER],
)
def test_owner_creates_assignable_user_roles(
    owner_client: TestClient,
    role: str,
) -> None:
    created = create_user_via_api(
        owner_client,
        username=f"managed_{role}",
        role=role,
    )

    assert created["role"] == role


@pytest.mark.parametrize(
    "role",
    [ROLE_OWNER, ROLE_SUPER_ADMIN, ROLE_MODULE_ADMIN, ROLE_BOT_AGENT],
)
def test_owner_cannot_create_unassignable_user_roles(
    owner_client: TestClient,
    role: str,
) -> None:
    response = owner_client.post(
        "/users",
        json={
            "username": f"blocked_{role}",
            "password": OWNER_ROLE_PASSWORD,
            "role": role,
        },
    )

    assert response.status_code == 422


def test_owner_reads_user_role_catalog(owner_client: TestClient) -> None:
    response = owner_client.get("/users/roles")

    assert response.status_code == 200
    payload = response.json()
    assert [role["name"] for role in payload["assignable_roles"]] == list(
        ASSIGNABLE_USER_ROLES
    )
    assert [role["name"] for role in payload["standard_roles"]] == list(
        STANDARD_ROLES
    )

    assignable_by_name = {
        role["name"]: role["assignable"] for role in payload["standard_roles"]
    }
    for role in ASSIGNABLE_USER_ROLES:
        assert assignable_by_name[role] is True
    for role in UNASSIGNABLE_USER_ROLES:
        assert assignable_by_name[role] is False


def test_owner_creates_user_and_rejects_invalid_create_requests(
    owner_client: TestClient,
) -> None:
    created = create_user_via_api(owner_client, role="operator")

    assert created["username"] == VIEWER_USERNAME
    assert created["role"] == "operator"
    assert created["is_active"] is True
    assert_no_password_hash(created)

    with SessionLocal() as db:
        stored_user = db.get(User, created["id"])
        create_log = db.scalar(
            select(OperationLog).where(OperationLog.action == "user.create")
        )

    assert stored_user is not None
    assert stored_user.password_hash != VIEWER_PASSWORD
    assert verify_password(VIEWER_PASSWORD, stored_user.password_hash)
    assert create_log is not None
    assert create_log.actor_type == "user"
    assert create_log.target_id == str(created["id"])

    duplicate = owner_client.post(
        "/users",
        json={
            "username": VIEWER_USERNAME,
            "password": "example-only-duplicate-password",
            "role": "viewer",
        },
    )
    owner_role = owner_client.post(
        "/users",
        json={
            "username": "blocked_owner_role",
            "password": OWNER_ROLE_PASSWORD,
            "role": "owner",
        },
    )
    weak_password = owner_client.post(
        "/users",
        json={
            "username": "weak_password_user",
            "password": "short",
            "role": "viewer",
        },
    )

    assert duplicate.status_code == 409
    assert owner_role.status_code == 422
    assert weak_password.status_code == 422


def test_auth_register_remains_absent(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/auth/register",
        json={
            "username": "blocked_register",
            "password": "example-only-register-password",
        },
    )

    assert response.status_code == 404


def test_user_list_and_detail_exclude_password_hash(
    owner_client: TestClient,
) -> None:
    created = create_user_via_api(owner_client)

    listed = owner_client.get("/users")
    detail = owner_client.get(f"/users/{created['id']}")

    assert listed.status_code == 200
    assert detail.status_code == 200
    assert_no_password_hash(listed.json())
    assert_no_password_hash(detail.json())
    assert VIEWER_PASSWORD not in json.dumps(listed.json())
    assert VIEWER_PASSWORD not in json.dumps(detail.json())


def test_user_detail_not_found_returns_404(owner_client: TestClient) -> None:
    response = owner_client.get("/users/999999")

    assert response.status_code == 404


def test_owner_updates_disables_enables_and_resets_user_password(
    owner_client: TestClient,
) -> None:
    created = create_user_via_api(owner_client)
    user_id = created["id"]

    updated = owner_client.patch(
        f"/users/{user_id}",
        json={"role": "reviewer", "is_active": True},
    )
    patch_to_viewer = owner_client.patch(
        f"/users/{user_id}",
        json={"role": " Viewer "},
    )
    patch_to_operator = owner_client.patch(
        f"/users/{user_id}",
        json={"role": ROLE_OPERATOR},
    )
    patch_to_reviewer = owner_client.patch(
        f"/users/{user_id}",
        json={"role": ROLE_REVIEWER},
    )
    disabled = owner_client.post(f"/users/{user_id}/disable")
    disabled_login = owner_client.post(
        "/auth/login",
        json={"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD},
    )
    enabled = owner_client.post(f"/users/{user_id}/enable")
    old_login_before_reset = owner_client.post(
        "/auth/login",
        json={"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD},
    )
    reset = owner_client.post(
        f"/users/{user_id}/reset-password",
        json={"new_password": RESET_PASSWORD},
    )
    old_login_after_reset = owner_client.post(
        "/auth/login",
        json={"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD},
    )
    new_login_after_reset = owner_client.post(
        "/auth/login",
        json={"username": VIEWER_USERNAME, "password": RESET_PASSWORD},
    )

    owner_id = owner_client.get("/auth/me").json()["id"]
    self_disable = owner_client.post(f"/users/{owner_id}/disable")
    self_reset = owner_client.post(
        f"/users/{owner_id}/reset-password",
        json={"new_password": "example-only-owner-reset-password"},
    )

    assert updated.status_code == 200
    assert updated.json()["role"] == "reviewer"
    assert patch_to_viewer.status_code == 200
    assert patch_to_viewer.json()["role"] == ROLE_VIEWER
    assert patch_to_operator.status_code == 200
    assert patch_to_operator.json()["role"] == ROLE_OPERATOR
    assert patch_to_reviewer.status_code == 200
    assert patch_to_reviewer.json()["role"] == ROLE_REVIEWER
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert disabled_login.status_code == 401
    assert enabled.status_code == 200
    assert enabled.json()["is_active"] is True
    assert old_login_before_reset.status_code == 200
    assert reset.status_code == 200
    assert_no_password_hash(reset.json())
    assert old_login_after_reset.status_code == 401
    assert new_login_after_reset.status_code == 200
    assert self_disable.status_code == 400
    assert self_reset.status_code == 400

    with SessionLocal() as db:
        operation_logs = list(
            db.scalars(
                select(OperationLog)
                .where(OperationLog.action.like("user.%"))
                .order_by(OperationLog.id)
            )
        )

    actions = {operation_log.action for operation_log in operation_logs}
    assert {
        "user.create",
        "user.update",
        "user.disable",
        "user.enable",
        "user.reset_password",
    }.issubset(actions)

    serialized_logs = json.dumps(
        [operation_log.details for operation_log in operation_logs],
        sort_keys=True,
    )
    assert VIEWER_PASSWORD not in serialized_logs
    assert RESET_PASSWORD not in serialized_logs
    assert "password_hash" not in serialized_logs


@pytest.mark.parametrize(
    "role",
    [ROLE_OWNER, ROLE_SUPER_ADMIN, ROLE_MODULE_ADMIN, ROLE_BOT_AGENT],
)
def test_owner_cannot_update_user_to_unassignable_roles(
    owner_client: TestClient,
    role: str,
) -> None:
    created = create_user_via_api(owner_client)

    response = owner_client.patch(
        f"/users/{created['id']}",
        json={"role": role},
    )

    assert response.status_code == 422
