import json

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.api.deps import require_permission
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models.permission import UserPermissionAssignment
from backend.app.models.user import User
from backend.app.services.permission_service import (
    grant_permission,
    upsert_permission_registry,
    upsert_role_default_permission,
)

TEST_PASSWORD = "example-only-permission-api-password"
TEST_ROUTE_PREFIX = "/__test-permissions"

permission_test_router = APIRouter(
    prefix=TEST_ROUTE_PREFIX,
    tags=["permission-tests"],
)


@permission_test_router.get("/api/app/users-manage")
def permissions_test_users_manage(
    user: User = Depends(require_permission("users.manage")),
) -> dict[str, int]:
    return {"user_id": user.id}


@permission_test_router.get("/api/app/artifacts-read-global")
def permissions_test_artifacts_read_global(
    user: User = Depends(require_permission("artifacts.read")),
) -> dict[str, int]:
    return {"user_id": user.id}


@permission_test_router.get("/api/app/artifacts-read-company-independent-site")
def permissions_test_artifacts_read_company_independent_site(
    user: User = Depends(
        require_permission(
            "artifacts.read",
            scope_type="company",
            scope_key="independent_site",
        )
    ),
) -> dict[str, int]:
    return {"user_id": user.id}


@permission_test_router.get("/api/app/permissions-manage-global")
def permissions_test_permissions_manage_global(
    user: User = Depends(require_permission("permissions.manage")),
) -> dict[str, int]:
    return {"user_id": user.id}


@permission_test_router.get("/api/app/permissions-manage-company-independent-site")
def permissions_test_permissions_manage_company_independent_site(
    user: User = Depends(
        require_permission(
            "permissions.manage",
            scope_type="company",
            scope_key="independent_site",
        )
    ),
) -> dict[str, int]:
    return {"user_id": user.id}


def include_test_router_once() -> None:
    route_path = f"{TEST_ROUTE_PREFIX}/users-manage"
    if any(getattr(route, "path", None) == route_path for route in app.routes):
        return
    app.include_router(permission_test_router)


include_test_router_once()


def create_permission_api_user(
    *,
    username: str,
    role: str,
    password: str = TEST_PASSWORD,
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


def login_token(
    client: TestClient,
    *,
    username: str,
    password: str = TEST_PASSWORD,
) -> str:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    session_id = response.cookies.get("barong_ops_session")
    assert session_id
    return session_id


def auth_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"barong_ops_session={token}"}


def seed_permission_registry() -> None:
    with SessionLocal() as db:
        upsert_permission_registry(db)


def grant_test_permission(
    *,
    user_id: int,
    permission_key: str,
    scope_type: str = "global",
    scope_key: str = "*",
) -> None:
    with SessionLocal() as db:
        upsert_permission_registry(db)
        grant_permission(
            db,
            user_id=user_id,
            permission_key=permission_key,
            scope_type=scope_type,
            scope_key=scope_key,
            reason="C05C test assignment.",
        )


def test_require_permission_owner_passes_without_assignment(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    owner_id = create_permission_api_user(
        username="c05c_owner_dependency",
        role="owner",
    )
    token = login_token(auth_client, username="c05c_owner_dependency")

    response = auth_client.get(
        f"{TEST_ROUTE_PREFIX}/users-manage",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": owner_id}
    with SessionLocal() as db:
        assignments = list(
            db.scalars(
                select(UserPermissionAssignment).where(
                    UserPermissionAssignment.user_id == owner_id
                )
            )
        )
    assert assignments == []


def test_require_permission_non_owner_without_assignment_fails(
    auth_client: TestClient,
) -> None:
    create_permission_api_user(
        username="c05c_operator_no_permission",
        role="operator",
    )
    token = login_token(auth_client, username="c05c_operator_no_permission")

    response = auth_client.get(
        f"{TEST_ROUTE_PREFIX}/users-manage",
        headers=auth_headers(token),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing permission: users.manage"


def test_require_permission_assignment_allows_non_owner(
    auth_client: TestClient,
) -> None:
    user_id = create_permission_api_user(
        username="c05c_operator_artifacts_read",
        role="operator",
    )
    grant_test_permission(user_id=user_id, permission_key="artifacts.read")
    token = login_token(auth_client, username="c05c_operator_artifacts_read")

    response = auth_client.get(
        f"{TEST_ROUTE_PREFIX}/artifacts-read-global",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": user_id}


def test_require_permission_scope_does_not_promote_to_global(
    auth_client: TestClient,
) -> None:
    user_id = create_permission_api_user(
        username="c05c_operator_scoped_artifacts_read",
        role="operator",
    )
    grant_test_permission(
        user_id=user_id,
        permission_key="artifacts.read",
        scope_type="company",
        scope_key="independent_site",
    )
    token = login_token(auth_client, username="c05c_operator_scoped_artifacts_read")

    global_response = auth_client.get(
        f"{TEST_ROUTE_PREFIX}/artifacts-read-global",
        headers=auth_headers(token),
    )
    scoped_response = auth_client.get(
        f"{TEST_ROUTE_PREFIX}/artifacts-read-company-independent-site",
        headers=auth_headers(token),
    )

    assert global_response.status_code == 403
    assert global_response.json()["detail"] == "Missing permission: artifacts.read"
    assert scoped_response.status_code == 200


def test_super_admin_requires_explicit_assignment(
    auth_client: TestClient,
) -> None:
    user_id = create_permission_api_user(
        username="c05c_super_admin",
        role="super_admin",
    )
    seed_permission_registry()
    token = login_token(auth_client, username="c05c_super_admin")

    missing_global = auth_client.get(
        f"{TEST_ROUTE_PREFIX}/permissions-manage-global",
        headers=auth_headers(token),
    )

    grant_test_permission(
        user_id=user_id,
        permission_key="permissions.manage",
        scope_type="company",
        scope_key="independent_site",
    )
    allowed_scoped = auth_client.get(
        f"{TEST_ROUTE_PREFIX}/permissions-manage-company-independent-site",
        headers=auth_headers(token),
    )
    still_missing_global = auth_client.get(
        f"{TEST_ROUTE_PREFIX}/permissions-manage-global",
        headers=auth_headers(token),
    )

    assert missing_global.status_code == 403
    assert allowed_scoped.status_code == 200
    assert still_missing_global.status_code == 403


def test_auth_me_returns_basic_identity_without_permission_payload(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    create_permission_api_user(
        username="c05c_owner_auth_me",
        role="owner",
    )
    token = login_token(auth_client, username="c05c_owner_auth_me")

    response = auth_client.get("/api/public/auth/me", headers=auth_headers(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == "owner"
    assert "permissions" not in payload
    assert "password_hash" not in json.dumps(payload, sort_keys=True)


def test_auth_me_omits_explicit_assignments_for_non_owner(
    auth_client: TestClient,
) -> None:
    user_id = create_permission_api_user(
        username="c05c_viewer_auth_me",
        role="viewer",
    )
    grant_test_permission(user_id=user_id, permission_key="artifacts.read")
    grant_test_permission(user_id=user_id, permission_key="reviews.read")
    with SessionLocal() as db:
        upsert_role_default_permission(
            db,
            role="viewer",
            permission_key="permissions.manage",
        )
    token = login_token(auth_client, username="c05c_viewer_auth_me")

    response = auth_client.get("/api/public/auth/me", headers=auth_headers(token))

    assert response.status_code == 200
    assert response.json()["id"] == user_id
    assert "permissions" not in response.json()
    assert "password_hash" not in json.dumps(response.json(), sort_keys=True)


def test_auth_me_omits_role_default_permissions(
    auth_client: TestClient,
) -> None:
    create_permission_api_user(
        username="c05c_viewer_role_default_only",
        role="viewer",
    )
    with SessionLocal() as db:
        upsert_permission_registry(db)
        upsert_role_default_permission(
            db,
            role="viewer",
            permission_key="artifacts.read",
        )
    token = login_token(auth_client, username="c05c_viewer_role_default_only")

    response = auth_client.get("/api/public/auth/me", headers=auth_headers(token))

    assert response.status_code == 200
    assert "permissions" not in response.json()


def test_permissions_me_returns_current_user_effective_permissions(
    auth_client: TestClient,
) -> None:
    user_id = create_permission_api_user(
        username="c05c_operator_permissions_me",
        role="operator",
    )
    grant_test_permission(user_id=user_id, permission_key="artifacts.read")
    token = login_token(auth_client, username="c05c_operator_permissions_me")

    response = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == user_id
    assert payload["role"] == "operator"
    assert payload["permissions"]["is_owner_full_access"] is False
    assert payload["permissions"]["permission_keys"] == ["artifacts.read"]


def test_permissions_me_returns_owner_platform_scoped_permissions(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    owner_id = create_permission_api_user(
        username="c05c_owner_permissions_me",
        role="owner",
    )
    token = login_token(auth_client, username="c05c_owner_permissions_me")

    response = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == owner_id
    assert response.json()["permissions"]["is_owner_full_access"] is False
    permission_keys = response.json()["permissions"]["permission_keys"]
    assert "*" not in permission_keys
    assert "permissions.read" in permission_keys
    assert "artifacts.read" not in permission_keys


def test_permissions_registry_requires_permissions_read_or_owner(
    auth_client: TestClient,
    monkeypatch,
) -> None:
    seed_permission_registry()
    owner_id = create_permission_api_user(
        username="c05c_owner_registry",
        role="owner",
    )
    viewer_id = create_permission_api_user(
        username="c05c_viewer_registry",
        role="viewer",
    )
    reader_id = create_permission_api_user(
        username="c05c_reader_registry",
        role="operator",
    )
    grant_test_permission(
        user_id=reader_id,
        permission_key="permissions.read",
    )

    owner_token = login_token(auth_client, username="c05c_owner_registry")
    viewer_token = login_token(auth_client, username="c05c_viewer_registry")
    reader_token = login_token(auth_client, username="c05c_reader_registry")

    owner_response = auth_client.get(
        "/api/app/permissions/registry",
        headers=auth_headers(owner_token),
    )
    forbidden_response = auth_client.get(
        "/api/app/permissions/registry",
        headers=auth_headers(viewer_token),
    )
    reader_response = auth_client.get(
        "/api/app/permissions/registry",
        headers=auth_headers(reader_token),
    )

    assert owner_response.status_code == 200
    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["detail"] == (
        "Missing permission: permissions.read"
    )
    assert reader_response.status_code == 200
    assert owner_response.json()["count"] == reader_response.json()["count"]
    permission_keys = {
        item["permission_key"] for item in reader_response.json()["items"]
    }
    assert {"users.manage", "permissions.read", "artifacts.read"}.issubset(
        permission_keys
    )
    categories_by_key = {
        item["permission_key"]: item["category"]
        for item in reader_response.json()["items"]
    }
    assert categories_by_key["artifacts.read"] == "feature"
    assert categories_by_key["permissions.read"] == "control_plane"
    assert owner_id != viewer_id

    def fail_registry_read(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("controlled permission registry failure")

    monkeypatch.setattr(
        "backend.app.api.routes.permissions.list_enabled_permissions",
        fail_registry_read,
    )
    fallback_response = auth_client.get(
        "/api/app/permissions/registry",
        headers=auth_headers(owner_token),
    )

    assert fallback_response.status_code == 200
    fallback_payload = fallback_response.json()
    assert fallback_payload["degraded"] is True
    assert fallback_payload["source"] == "snapshot"
    assert {"users.manage", "permissions.read", "artifacts.read"}.issubset(
        {item["permission_key"] for item in fallback_payload["items"]}
    )
