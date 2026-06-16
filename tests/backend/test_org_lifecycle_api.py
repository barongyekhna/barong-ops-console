import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal, engine
from backend.app.models.operation_log import OperationLog
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.schemas.organization import ORG_ID_PATTERN


OPERATOR_PASSWORD = "example-only-org-operator-password"


@pytest.fixture
def org_table(clean_auth_tables: None):
    OrganizationRecord.__table__.create(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        db.execute(delete(OrganizationRecord))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(OrganizationRecord))
        db.commit()


def _current_user_id(client: TestClient) -> str:
    response = client.get("/api/public/auth/me")
    assert response.status_code == 200
    return str(response.json()["id"])


def _create_user(
    *,
    username: str,
    password: str,
    role: str = "operator",
) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def _login(client: TestClient, *, username: str, password: str) -> str:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    session_id = response.cookies.get("barong_ops_session")
    assert session_id
    return session_id


def _cookie(session_id: str) -> dict[str, str]:
    return {"Cookie": f"barong_ops_session={session_id}"}


def _create_org(client: TestClient, *, owner_user_id: str) -> dict:
    response = client.post(
        "/api/app/org/create",
        json={
            "org_name": "Barong Store",
            "org_type": "store",
            "owner_user_id": owner_user_id,
            "metadata": {
                "industry": "commerce",
                "country": "US",
                "timezone": "UTC",
                "settings": {"allow_ai": True},
                "custom": {"tier": "pilot"},
            },
        },
    )
    assert response.status_code == 201
    return response.json()


def test_c18b_owner_controls_full_org_lifecycle(
    org_table: None,
    owner_client: TestClient,
) -> None:
    owner_user_id = _current_user_id(owner_client)
    created = _create_org(owner_client, owner_user_id=owner_user_id)

    assert ORG_ID_PATTERN.fullmatch(created["org_id"])
    assert created["status"] == "active"
    assert created["owner_user_id"] == owner_user_id

    updated = owner_client.patch(
        f"/api/app/org/{created['org_id']}",
        json={
            "org_name": "Warehouse North",
            "org_type": "warehouse",
            "metadata": {"industry": "logistics", "timezone": "UTC"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["org_name"] == "Warehouse North"
    assert updated.json()["org_type"] == "warehouse"
    assert updated.json()["status"] == "active"

    suspended = owner_client.post(f"/api/app/org/{created['org_id']}/suspend")
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"

    activated = owner_client.post(f"/api/app/org/{created['org_id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    deleted = owner_client.delete(f"/api/app/org/{created['org_id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    reactivate_deleted = owner_client.post(
        f"/api/app/org/{created['org_id']}/activate"
    )
    assert reactivate_deleted.status_code == 409

    with SessionLocal() as db:
        stored = db.get(OrganizationRecord, created["org_id"])
        logs = list(
            db.scalars(
                select(OperationLog)
                .where(OperationLog.target_type == "organization")
                .order_by(OperationLog.id)
            )
        )

    assert stored is not None
    assert stored.status == "deleted"
    assert {log.action for log in logs} >= {
        "org.create",
        "org.update",
        "org.suspend",
        "org.activate",
        "org.delete",
    }
    assert any(
        log.action == "org.activate"
        and log.result == "failure"
        and log.error_code == "invalid_status_transition"
        for log in logs
    )


def test_c18b_non_owner_is_denied_for_all_lifecycle_operations(
    org_table: None,
    owner_client: TestClient,
) -> None:
    owner_user_id = _current_user_id(owner_client)
    created = _create_org(owner_client, owner_user_id=owner_user_id)

    operator_id = _create_user(
        username="org_lifecycle_operator",
        password=OPERATOR_PASSWORD,
    )
    owner_client.cookies.clear()
    operator_session = _login(
        owner_client,
        username="org_lifecycle_operator",
        password=OPERATOR_PASSWORD,
    )

    forbidden_create = owner_client.post(
        "/api/app/org/create",
        json={
            "org_name": "Blocked",
            "org_type": "store",
            "owner_user_id": owner_user_id,
        },
        headers=_cookie(operator_session),
    )
    forbidden_update = owner_client.patch(
        f"/api/app/org/{created['org_id']}",
        json={"org_name": "Blocked Update"},
        headers=_cookie(operator_session),
    )
    forbidden_suspend = owner_client.post(
        f"/api/app/org/{created['org_id']}/suspend",
        headers=_cookie(operator_session),
    )
    forbidden_activate = owner_client.post(
        f"/api/app/org/{created['org_id']}/activate",
        headers=_cookie(operator_session),
    )
    forbidden_delete = owner_client.delete(
        f"/api/app/org/{created['org_id']}",
        headers=_cookie(operator_session),
    )

    assert operator_id != int(owner_user_id)
    assert forbidden_create.status_code == 403
    assert forbidden_update.status_code == 403
    assert forbidden_suspend.status_code == 403
    assert forbidden_activate.status_code == 403
    assert forbidden_delete.status_code == 403

    with SessionLocal() as db:
        stored = db.get(OrganizationRecord, created["org_id"])
        failure_logs = list(
            db.scalars(
                select(OperationLog).where(
                    OperationLog.target_type == "organization",
                    OperationLog.result == "failure",
                    OperationLog.error_code == "owner_only_denied",
                )
            )
        )

    assert stored is not None
    assert stored.status == "active"
    assert stored.org_name == "Barong Store"
    assert len(failure_logs) >= 5


def test_c18b_update_rejects_status_owner_and_org_id_mutation(
    org_table: None,
    owner_client: TestClient,
) -> None:
    owner_user_id = _current_user_id(owner_client)
    created = _create_org(owner_client, owner_user_id=owner_user_id)

    status_update = owner_client.patch(
        f"/api/app/org/{created['org_id']}",
        json={"status": "deleted"},
    )
    owner_update = owner_client.patch(
        f"/api/app/org/{created['org_id']}",
        json={"owner_user_id": "999999"},
    )
    org_id_update = owner_client.patch(
        f"/api/app/org/{created['org_id']}",
        json={"org_id": "org_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    )

    assert status_update.status_code == 422
    assert owner_update.status_code == 422
    assert org_id_update.status_code == 422

    with SessionLocal() as db:
        stored = db.get(OrganizationRecord, created["org_id"])

    assert stored is not None
    assert stored.owner_user_id == owner_user_id
    assert stored.status == "active"
    assert stored.org_name == "Barong Store"
    assert "password" not in json.dumps(created, sort_keys=True).lower()
