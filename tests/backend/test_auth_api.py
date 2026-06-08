import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.security import (
    decode_access_token,
    hash_password,
)
from backend.app.db.session import SessionLocal
from backend.app.models.operation_log import OperationLog
from backend.app.models.user import User

USERNAME = "api_owner"
PASSWORD = "example-only-api-owner-password"
TEST_AUTH_SECRET = "f08-test-signing-value-not-for-production-use"


def create_test_owner(*, is_active: bool = True) -> int:
    with SessionLocal() as db:
        owner = User(
            username=USERNAME,
            password_hash=hash_password(PASSWORD),
            role="owner",
            is_active=is_active,
        )
        db.add(owner)
        db.commit()
        return owner.id


def login(client: TestClient) -> dict:
    response = client.post(
        "/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


def test_login_returns_token_updates_user_and_writes_audit_log(
    auth_client: TestClient,
) -> None:
    owner_id = create_test_owner()

    payload = login(auth_client)

    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["user"]["id"] == owner_id
    assert payload["user"]["username"] == USERNAME
    assert payload["user"]["role"] == "owner"
    assert payload["user"]["is_active"] is True
    assert "password_hash" not in json.dumps(payload)

    token_payload = decode_access_token(
        payload["access_token"],
        TEST_AUTH_SECRET,
    )
    assert token_payload["sub"] == str(owner_id)
    assert token_payload["role"] == "owner"
    assert "exp" in token_payload

    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        operation_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "auth.login",
                OperationLog.result == "success",
            )
        )

    assert owner is not None
    assert owner.last_login_at is not None
    assert operation_log is not None
    assert operation_log.actor_id == str(owner_id)


def test_login_failure_is_uniform_and_audited_without_secrets(
    auth_client: TestClient,
) -> None:
    owner_id = create_test_owner()
    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        assert owner is not None
        stored_hash = owner.password_hash

    wrong_password = "example-only-wrong-password"
    wrong_password_response = auth_client.post(
        "/auth/login",
        json={"username": USERNAME, "password": wrong_password},
    )
    unknown_user_response = auth_client.post(
        "/auth/login",
        json={"username": "unknown_owner", "password": wrong_password},
    )

    assert wrong_password_response.status_code == 401
    assert unknown_user_response.status_code == 401
    assert wrong_password_response.json() == unknown_user_response.json()

    with SessionLocal() as db:
        operation_logs = list(
            db.scalars(
                select(OperationLog)
                .where(
                    OperationLog.action == "auth.login",
                    OperationLog.result == "failure",
                )
                .order_by(OperationLog.id)
            )
        )

    assert len(operation_logs) == 2
    serialized_logs = json.dumps(
        [operation_log.details for operation_log in operation_logs],
        sort_keys=True,
    )
    assert wrong_password not in serialized_logs
    assert PASSWORD not in serialized_logs
    assert stored_hash not in serialized_logs
    assert "password_hash" not in serialized_logs


def test_inactive_user_cannot_login(auth_client: TestClient) -> None:
    create_test_owner(is_active=False)

    response = auth_client.post(
        "/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


def test_auth_me_returns_current_user(auth_client: TestClient) -> None:
    owner_id = create_test_owner()
    access_token = login(auth_client)["access_token"]

    response = auth_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == owner_id
    assert response.json()["username"] == USERNAME
    assert "password_hash" not in response.json()


def test_logout_requires_token_and_writes_audit_log(
    auth_client: TestClient,
) -> None:
    owner_id = create_test_owner()
    access_token = login(auth_client)["access_token"]

    response = auth_client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Logged out."}

    with SessionLocal() as db:
        operation_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "auth.logout"
            )
        )

    assert operation_log is not None
    assert operation_log.actor_id == str(owner_id)
    assert operation_log.result == "success"


def test_auth_register_does_not_exist(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/auth/register",
        json={"username": "blocked", "password": "not-used"},
    )

    assert response.status_code == 404
