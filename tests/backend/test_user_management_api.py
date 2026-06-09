import json

from fastapi.testclient import TestClient
from sqlalchemy import select

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

    unauthenticated = auth_client.get("/users")
    forbidden = auth_client.get(
        "/users",
        headers={
            "Authorization": (
                f"Bearer {login_response.json()['access_token']}"
            )
        },
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403


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
