import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.roles import (
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
from backend.app.schemas.user import DEFAULT_INITIAL_PASSWORD, USER_MANAGEMENT_ROLES

VIEWER_USERNAME = "managed_viewer"
VIEWER_PASSWORD = "example-only-viewer-password"
RESET_PASSWORD = "example-only-reset-password"
OWNER_ROLE_PASSWORD = "example-only-owner-role-password"
DEFAULT_ORG_ID = "org_11111111111111111111111111111111"


def create_db_user(
    *,
    username: str,
    password: str,
    role: str = "viewer",
    is_active: bool = True,
    organization_id: str | None = None,
    job_title: str | None = None,
) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
            organization_id=organization_id,
            job_title=job_title,
        )
        db.add(user)
        db.commit()
        return user.id


def create_user_via_api(
    client: TestClient,
    *,
    username: str = VIEWER_USERNAME,
    role: str = "viewer",
    organization_id: str | None = DEFAULT_ORG_ID,
    job_title: str | None = "Operations Associate",
    is_active: bool = True,
) -> dict:
    payload = {
        "username": username,
        "role": role,
        "job_title": job_title,
        "organization_id": organization_id,
        "is_active": is_active,
    }
    if role == "owner":
        payload["organization_id"] = None
        payload["job_title"] = None
    response = client.post(
        "/api/app/users",
        json=payload,
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
        "/api/public/auth/login",
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
    unauthenticated = auth_client.get("/api/app/users")
    forbidden = auth_client.get(
        "/api/app/users",
        headers={"Cookie": f"barong_ops_session={session_id}"},
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403

    unauthenticated_roles = auth_client.get("/api/app/users/roles")
    forbidden_roles = auth_client.get(
        "/api/app/users/roles",
        headers={"Cookie": f"barong_ops_session={session_id}"},
    )

    assert unauthenticated_roles.status_code == 401
    assert forbidden_roles.status_code == 403


@pytest.mark.parametrize(
    ("role", "expected_must_change_password"),
    [
        (ROLE_OWNER, False),
        (ROLE_SUPER_ADMIN, True),
        (ROLE_OPERATOR, True),
        (ROLE_VIEWER, True),
        (ROLE_REVIEWER, True),
    ],
)
def test_login_password_reset_policy_only_owner_bypasses_reset(
    auth_client: TestClient,
    role: str,
    expected_must_change_password: bool,
) -> None:
    username = f"reset_policy_{role}"
    password = "example-only-reset-policy-password"
    create_db_user(username=username, password=password, role=role)

    login_response = auth_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )

    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["require_password_change"] is expected_must_change_password
    assert payload["user"]["must_change_password"] is expected_must_change_password

    me_response = auth_client.get("/api/public/auth/me")
    assert me_response.status_code == 200
    assert (
        me_response.json()["must_change_password"]
        is expected_must_change_password
    )


@pytest.mark.parametrize(
    "role",
    [ROLE_OWNER, ROLE_SUPER_ADMIN, ROLE_VIEWER, ROLE_OPERATOR, ROLE_REVIEWER],
)
def test_owner_creates_user_management_roles(
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
    ["admin", ROLE_MODULE_ADMIN, ROLE_BOT_AGENT],
)
def test_owner_cannot_create_roles_outside_user_management_policy(
    owner_client: TestClient,
    role: str,
) -> None:
    response = owner_client.post(
        "/api/app/users",
        json={
            "username": f"blocked_{role}",
            "password": OWNER_ROLE_PASSWORD,
            "role": role,
            "organization_id": DEFAULT_ORG_ID,
        },
    )

    assert response.status_code == 422


def test_owner_reads_user_role_catalog(owner_client: TestClient) -> None:
    response = owner_client.get("/api/app/users/roles")

    assert response.status_code == 200
    payload = response.json()
    assert [role["name"] for role in payload["assignable_roles"]] == list(
        USER_MANAGEMENT_ROLES
    )
    assert [role["name"] for role in payload["standard_roles"]] == list(
        STANDARD_ROLES
    )

    assignable_by_name = {
        role["name"]: role["assignable"] for role in payload["standard_roles"]
    }
    for role in USER_MANAGEMENT_ROLES:
        assert assignable_by_name[role] is True
    for role in set(UNASSIGNABLE_USER_ROLES) - set(USER_MANAGEMENT_ROLES):
        assert assignable_by_name[role] is False


def test_owner_creates_user_and_rejects_invalid_create_requests(
    owner_client: TestClient,
) -> None:
    created = create_user_via_api(owner_client, role="operator")

    assert created["username"] == VIEWER_USERNAME
    assert created["role"] == "operator"
    assert created["job_title"] == "Operations Associate"
    assert created["organization_id"] == DEFAULT_ORG_ID
    assert created["must_change_password"] is True
    assert created["is_active"] is True
    assert_no_password_hash(created)

    with SessionLocal() as db:
        stored_user = db.get(User, created["id"])
        create_log = db.scalar(
            select(OperationLog).where(OperationLog.action == "user.create")
        )

    assert stored_user is not None
    assert stored_user.password_hash != VIEWER_PASSWORD
    assert verify_password(DEFAULT_INITIAL_PASSWORD, stored_user.password_hash)
    assert stored_user.must_change_password is True
    assert create_log is not None
    assert create_log.actor_type == "user"
    assert create_log.target_id == str(created["id"])

    duplicate = owner_client.post(
        "/api/app/users",
        json={
            "username": VIEWER_USERNAME,
            "password": "example-only-duplicate-password",
            "role": "viewer",
            "organization_id": DEFAULT_ORG_ID,
        },
    )
    missing_org = owner_client.post(
        "/api/app/users",
        json={
            "username": "missing_org_user",
            "role": "viewer",
        },
    )
    invalid_role = owner_client.post(
        "/api/app/users",
        json={
            "username": "invalid_role_user",
            "role": "admin",
            "organization_id": DEFAULT_ORG_ID,
        },
    )

    assert duplicate.status_code == 409
    assert missing_org.status_code == 422
    assert invalid_role.status_code == 422


def test_owner_creates_users_with_owner_only_password_reset_bypass(
    owner_client: TestClient,
) -> None:
    owner = create_user_via_api(
        owner_client,
        username="managed_owner_reset_bypass",
        role=ROLE_OWNER,
    )
    super_admin = create_user_via_api(
        owner_client,
        username="managed_super_admin_reset_required",
        role=ROLE_SUPER_ADMIN,
    )
    viewer = create_user_via_api(
        owner_client,
        username="managed_viewer_reset_required",
        role=ROLE_VIEWER,
    )
    operator = create_user_via_api(
        owner_client,
        username="managed_operator_reset_required",
        role=ROLE_OPERATOR,
    )
    reviewer = create_user_via_api(
        owner_client,
        username="managed_reviewer_reset_required",
        role=ROLE_REVIEWER,
    )

    assert owner["must_change_password"] is False
    assert super_admin["must_change_password"] is True
    assert viewer["must_change_password"] is True
    assert operator["must_change_password"] is True
    assert reviewer["must_change_password"] is True

    with SessionLocal() as db:
        stored_owner = db.get(User, owner["id"])
        stored_super_admin = db.get(User, super_admin["id"])
        stored_viewer = db.get(User, viewer["id"])
        stored_operator = db.get(User, operator["id"])
        stored_reviewer = db.get(User, reviewer["id"])

    assert stored_owner is not None
    assert stored_super_admin is not None
    assert stored_viewer is not None
    assert stored_operator is not None
    assert stored_reviewer is not None
    assert stored_owner.must_change_password is False
    assert stored_super_admin.must_change_password is True
    assert stored_viewer.must_change_password is True
    assert stored_operator.must_change_password is True
    assert stored_reviewer.must_change_password is True

    converted_owner = owner_client.patch(
        f"/api/app/users/{owner['id']}",
        json={"role": ROLE_SUPER_ADMIN},
    )
    assert converted_owner.status_code == 200
    assert converted_owner.json()["role"] == ROLE_SUPER_ADMIN
    assert converted_owner.json()["must_change_password"] is True

    with SessionLocal() as db:
        stored_converted_owner = db.get(User, owner["id"])

    assert stored_converted_owner is not None
    assert stored_converted_owner.role == ROLE_SUPER_ADMIN
    assert stored_converted_owner.must_change_password is True


def test_auth_register_remains_absent(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/public/auth/register",
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

    listed = owner_client.get("/api/app/users")
    detail = owner_client.get(f"/api/app/users/{created['id']}")

    assert listed.status_code == 200
    assert detail.status_code == 200
    assert_no_password_hash(listed.json())
    assert_no_password_hash(detail.json())
    assert VIEWER_PASSWORD not in json.dumps(listed.json())
    assert VIEWER_PASSWORD not in json.dumps(detail.json())


def test_user_list_role_filter_returns_super_admins(
    owner_client: TestClient,
) -> None:
    create_user_via_api(
        owner_client,
        username="managed_super_admin_filter",
        role=ROLE_SUPER_ADMIN,
    )
    create_user_via_api(
        owner_client,
        username="managed_viewer_filter",
        role=ROLE_VIEWER,
    )

    response = owner_client.get("/api/app/users?role=super_admin&limit=100")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert [item["username"] for item in payload["items"]] == [
        "managed_super_admin_filter"
    ]


def test_user_list_falls_back_to_snapshot_on_live_read_failure(
    owner_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = create_user_via_api(
        owner_client,
        username="managed_snapshot_user",
        role=ROLE_VIEWER,
    )
    first = owner_client.get("/api/app/users")
    assert first.status_code == 200

    def fail_list_users(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("controlled user list failure")

    monkeypatch.setattr("backend.app.api.routes.users.list_users", fail_list_users)
    second = owner_client.get("/api/app/users")

    assert second.status_code == 200
    payload = second.json()
    assert payload["degraded"] is True
    assert payload["source"] == "snapshot"
    assert created["username"] in {item["username"] for item in payload["items"]}


def test_user_list_organization_filter_respects_owner_and_super_admin_scope(
    auth_client: TestClient,
    owner_client: TestClient,
) -> None:
    org_a = DEFAULT_ORG_ID
    org_b = "org_22222222222222222222222222222222"
    super_admin_password = "example-only-super-admin-filter-password"
    create_db_user(
        username="filter_super_admin",
        password=super_admin_password,
        role=ROLE_SUPER_ADMIN,
        organization_id=org_a,
        job_title="Org A Admin",
    )
    create_db_user(
        username="filter_org_a_viewer",
        password="example-only-org-a-viewer-password",
        role=ROLE_VIEWER,
        organization_id=org_a,
        job_title="Org A Viewer",
    )
    org_b_viewer_id = create_db_user(
        username="filter_org_b_viewer",
        password="example-only-org-b-viewer-password",
        role=ROLE_VIEWER,
        organization_id=org_b,
        job_title="Org B Viewer",
    )

    owner_filtered = owner_client.get(f"/api/app/users?organization_id={org_b}")
    login_response = auth_client.post(
        "/api/public/auth/login",
        json={
            "username": "filter_super_admin",
            "password": super_admin_password,
        },
    )
    assert login_response.status_code == 200
    session_id = login_response.cookies.get("barong_ops_session")
    assert session_id
    super_admin_headers = {"Cookie": f"barong_ops_session={session_id}"}
    super_admin_list = auth_client.get(
        "/api/app/users",
        headers=super_admin_headers,
    )
    super_admin_cross_org = auth_client.get(
        f"/api/app/users?organization_id={org_b}",
        headers=super_admin_headers,
    )
    super_admin_cross_org_detail = auth_client.get(
        f"/api/app/users/{org_b_viewer_id}",
        headers=super_admin_headers,
    )

    assert owner_filtered.status_code == 200
    assert {item["username"] for item in owner_filtered.json()["items"]} == {
        "filter_org_b_viewer",
    }
    assert super_admin_list.status_code == 200
    listed_by_username = {
        item["username"]: item for item in super_admin_list.json()["items"]
    }
    assert {
        "filter_super_admin",
        "filter_org_a_viewer",
        "filter_org_b_viewer",
    }.issubset(listed_by_username)
    assert listed_by_username["filter_super_admin"]["organization_id"] == org_a
    assert listed_by_username["filter_super_admin"]["organization"] == org_a
    assert listed_by_username["filter_super_admin"]["role"] == ROLE_SUPER_ADMIN
    assert listed_by_username["filter_super_admin"]["job_title"] == "Org A Admin"
    assert listed_by_username["filter_org_b_viewer"]["organization_id"] == org_b
    assert listed_by_username["filter_org_b_viewer"]["organization"] == org_b
    assert listed_by_username["filter_org_b_viewer"]["role"] == ROLE_VIEWER
    assert listed_by_username["filter_org_b_viewer"]["job_title"] == "Org B Viewer"
    assert super_admin_cross_org.status_code == 200
    assert {item["username"] for item in super_admin_cross_org.json()["items"]} == {
        "filter_org_b_viewer",
    }
    assert super_admin_cross_org_detail.status_code == 200
    assert super_admin_cross_org_detail.json()["organization_id"] == org_b
    assert super_admin_cross_org_detail.json()["organization"] == org_b


def test_user_detail_not_found_returns_404(owner_client: TestClient) -> None:
    response = owner_client.get("/api/app/users/999999")

    assert response.status_code == 404


def test_owner_updates_disables_enables_and_resets_user_password(
    owner_client: TestClient,
) -> None:
    created = create_user_via_api(owner_client)
    user_id = created["id"]

    updated = owner_client.patch(
        f"/api/app/users/{user_id}",
        json={"role": "reviewer", "is_active": True},
    )
    patch_to_viewer = owner_client.patch(
        f"/api/app/users/{user_id}",
        json={"role": " Viewer "},
    )
    patch_to_operator = owner_client.patch(
        f"/api/app/users/{user_id}",
        json={"role": ROLE_OPERATOR},
    )
    patch_to_reviewer = owner_client.patch(
        f"/api/app/users/{user_id}",
        json={"role": ROLE_REVIEWER},
    )
    disabled = owner_client.post(f"/api/app/users/{user_id}/disable")
    disabled_login = owner_client.post(
        "/api/public/auth/login",
        json={"username": VIEWER_USERNAME, "password": DEFAULT_INITIAL_PASSWORD},
    )
    enabled = owner_client.post(f"/api/app/users/{user_id}/enable")
    old_login_before_reset = owner_client.post(
        "/api/public/auth/login",
        json={"username": VIEWER_USERNAME, "password": DEFAULT_INITIAL_PASSWORD},
    )
    reset = owner_client.post(
        f"/api/app/users/{user_id}/reset-password",
        json={"new_password": RESET_PASSWORD},
    )
    old_login_after_reset = owner_client.post(
        "/api/public/auth/login",
        json={"username": VIEWER_USERNAME, "password": DEFAULT_INITIAL_PASSWORD},
    )
    new_login_after_reset = owner_client.post(
        "/api/public/auth/login",
        json={"username": VIEWER_USERNAME, "password": RESET_PASSWORD},
    )

    owner_id = owner_client.get("/api/public/auth/me").json()["id"]
    self_disable = owner_client.post(f"/api/app/users/{owner_id}/disable")
    self_reset = owner_client.post(
        f"/api/app/users/{owner_id}/reset-password",
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
    ["admin", ROLE_MODULE_ADMIN, ROLE_BOT_AGENT],
)
def test_owner_cannot_update_user_to_roles_outside_user_management_policy(
    owner_client: TestClient,
    role: str,
) -> None:
    created = create_user_via_api(owner_client)

    response = owner_client.patch(
        f"/api/app/users/{created['id']}",
        json={"role": role},
    )

    assert response.status_code == 422
