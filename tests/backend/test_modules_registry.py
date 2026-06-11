import json

from fastapi.testclient import TestClient

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.services.module_registry import (
    ALLOWED_DENIED_BEHAVIORS,
    ALLOWED_EXTERNAL_DEPENDENCIES,
    ALLOWED_MODULE_CATEGORIES,
    ALLOWED_MODULE_STATUSES,
    list_module_manifests,
    validate_module_manifests,
)
from backend.app.services.permission_service import (
    upsert_permission_registry,
    upsert_role_default_permission,
)

TEST_PASSWORD = "example-only-c07b-module-password"


def create_module_registry_user(
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
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def seed_permission_registry() -> None:
    with SessionLocal() as db:
        upsert_permission_registry(db)


def access_items_by_key(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(item["module_key"]): item
        for item in payload["items"]  # type: ignore[index]
    }


def test_modules_registry_api_requires_login_and_owner_can_read(
    auth_client: TestClient,
) -> None:
    unauth_registry = auth_client.get("/modules/registry")
    unauth_me = auth_client.get("/modules/me")
    create_module_registry_user(username="c07b_owner_api", role="owner")
    owner_token = login_token(auth_client, username="c07b_owner_api")

    registry = auth_client.get(
        "/modules/registry",
        headers=auth_headers(owner_token),
    )
    me = auth_client.get("/modules/me", headers=auth_headers(owner_token))

    assert unauth_registry.status_code == 401
    assert unauth_me.status_code == 401
    assert registry.status_code == 200
    assert me.status_code == 200
    registry_payload = registry.json()
    assert registry_payload["count"] == len(registry_payload["items"])
    module_keys = {item["module_key"] for item in registry_payload["items"]}
    assert {"admin.users", "admin.permissions", "core.dashboard"}.issubset(
        module_keys
    )
    assert "password_hash" not in json.dumps(registry_payload, sort_keys=True)
    assert me.json()["is_owner_full_access"] is True


def test_static_module_registry_validation_rules() -> None:
    manifests = validate_module_manifests()
    module_keys = [manifest.module_key for manifest in manifests]

    assert len(module_keys) == len(set(module_keys))
    assert {"admin.users", "admin.permissions", "business.products"}.issubset(
        set(module_keys)
    )
    for manifest in manifests:
        assert manifest.category in ALLOWED_MODULE_CATEGORIES
        assert manifest.status in ALLOWED_MODULE_STATUSES
        assert manifest.denied_behavior in ALLOWED_DENIED_BEHAVIORS
        assert manifest.route_namespace
        assert manifest.api_namespace
        assert manifest.no_api or manifest.api_namespace.startswith("/")
        if manifest.category in {"admin", "system"}:
            assert manifest.denied_behavior == "hide_when_denied"
        if manifest.category == "business":
            assert manifest.denied_behavior == "show_locked"
        declared_permissions = {
            entry.permission_key for entry in manifest.permission_manifest
        }
        assert set(manifest.required_permissions).issubset(declared_permissions)


def test_module_registry_dependency_and_runtime_safety_metadata() -> None:
    manifests = list_module_manifests()
    dependency_markers = (
        "secret",
        "token",
        "password",
        "credential",
        "authorization",
        "api_key",
        "env",
        "url",
        "http",
        "://",
        "=",
    )
    blocked_runtime_fragments = (
        ".env.production",
        ".env.staging",
        "auth_token_secret",
        "owner_password",
        "postgres_password",
        "n8n_test_webhook_url",
        "n8n_test_callback_secret",
        "ops.barongyekhna.com",
        "console_postgres",
        "https://",
        "http://",
    )

    for manifest in manifests:
        for dependency in manifest.external_dependencies:
            lowered_dependency = dependency.lower()
            assert lowered_dependency in ALLOWED_EXTERNAL_DEPENDENCIES
            for marker in dependency_markers:
                assert marker not in lowered_dependency

    serialized = json.dumps(
        [manifest.model_dump() for manifest in manifests],
        sort_keys=True,
    ).lower()
    for fragment in blocked_runtime_fragments:
        assert fragment not in serialized

    k01_modules = [
        manifest
        for manifest in manifests
        if manifest.module_key.startswith("k01")
        or "product_knowledge" in manifest.module_key
    ]
    assert k01_modules == []


def test_owner_and_non_owner_module_access_states(
    auth_client: TestClient,
) -> None:
    create_module_registry_user(username="c07b_owner_access", role="owner")
    create_module_registry_user(username="c07b_viewer_access", role="viewer")
    owner_token = login_token(auth_client, username="c07b_owner_access")
    viewer_token = login_token(auth_client, username="c07b_viewer_access")

    owner_response = auth_client.get(
        "/modules/me",
        headers=auth_headers(owner_token),
    )
    viewer_response = auth_client.get(
        "/modules/me",
        headers=auth_headers(viewer_token),
    )

    assert owner_response.status_code == 200
    assert viewer_response.status_code == 200
    owner_items = access_items_by_key(owner_response.json())
    viewer_items = access_items_by_key(viewer_response.json())

    assert owner_items["admin.users"]["visible"] is True
    assert owner_items["admin.users"]["access_state"] == "available"
    assert owner_items["admin.permissions"]["visible"] is True
    assert owner_items["admin.permissions"]["access_state"] == "available"
    assert viewer_items["admin.users"]["hidden"] is True
    assert viewer_items["admin.users"]["access_state"] == "hidden"
    assert viewer_items["admin.permissions"]["hidden"] is True
    assert viewer_items["admin.permissions"]["access_state"] == "hidden"
    assert viewer_items["business.jobs"]["visible"] is True
    assert viewer_items["business.jobs"]["locked"] is True
    assert viewer_items["business.jobs"]["access_state"] == "locked"
    assert "jobs.read" in viewer_items["business.jobs"]["missing_permissions"]
    assert viewer_items["core.dashboard"]["access_state"] == "available"


def test_planned_adapter_pending_and_unavailable_modules_are_not_executable(
    auth_client: TestClient,
) -> None:
    create_module_registry_user(username="c07b_owner_nonexec", role="owner")
    owner_token = login_token(auth_client, username="c07b_owner_nonexec")

    response = auth_client.get("/modules/me", headers=auth_headers(owner_token))

    assert response.status_code == 200
    items = access_items_by_key(response.json())
    assert items["business.products"]["status"] == "planned"
    assert items["business.products"]["access_state"] == "planned"
    assert items["business.products"]["executable"] is False
    assert items["admin.settings"]["status"] == "planned"
    assert items["admin.settings"]["access_state"] == "planned"
    assert items["admin.settings"]["executable"] is False
    assert items["integration.n8n_test_bridge"]["status"] == "adapter_pending"
    assert items["integration.n8n_test_bridge"]["access_state"] == (
        "adapter_pending"
    )
    assert items["integration.n8n_test_bridge"]["executable"] is False


def test_role_defaults_and_super_admin_do_not_grant_module_access(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    create_module_registry_user(
        username="c07b_viewer_role_default",
        role="viewer",
    )
    create_module_registry_user(
        username="c07b_super_admin_default",
        role="super_admin",
    )
    with SessionLocal() as db:
        upsert_role_default_permission(
            db,
            role="viewer",
            permission_key="jobs.read",
        )
    viewer_token = login_token(
        auth_client,
        username="c07b_viewer_role_default",
    )
    super_admin_token = login_token(
        auth_client,
        username="c07b_super_admin_default",
    )

    viewer_response = auth_client.get(
        "/modules/me",
        headers=auth_headers(viewer_token),
    )
    super_admin_response = auth_client.get(
        "/modules/me",
        headers=auth_headers(super_admin_token),
    )

    assert viewer_response.status_code == 200
    assert super_admin_response.status_code == 200
    viewer_items = access_items_by_key(viewer_response.json())
    super_admin_items = access_items_by_key(super_admin_response.json())
    assert viewer_items["business.jobs"]["access_state"] == "locked"
    assert super_admin_items["admin.users"]["access_state"] == "hidden"
    assert super_admin_items["admin.permissions"]["access_state"] == "hidden"
    assert super_admin_items["admin.modules"]["access_state"] == "hidden"


def test_c07b_regressions_users_register_assignments_and_permissions_me(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    owner_id = create_module_registry_user(
        username="c07b_owner_regression",
        role="owner",
    )
    viewer_id = create_module_registry_user(
        username="c07b_viewer_regression",
        role="viewer",
    )
    owner_token = login_token(auth_client, username="c07b_owner_regression")
    viewer_token = login_token(auth_client, username="c07b_viewer_regression")

    viewer_users = auth_client.get("/users", headers=auth_headers(viewer_token))
    missing_register = auth_client.post(
        "/auth/register",
        json={"username": "blocked", "password": "blocked"},
    )
    grant_response = auth_client.post(
        f"/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
        json={"permission_key": "jobs.read", "reason": "C07B regression."},
    )
    assignments_response = auth_client.get(
        f"/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
    )
    permissions_me = auth_client.get(
        "/permissions/me",
        headers=auth_headers(viewer_token),
    )
    modules_me = auth_client.get(
        "/modules/me",
        headers=auth_headers(viewer_token),
    )

    assert viewer_users.status_code == 403
    assert missing_register.status_code == 404
    assert grant_response.status_code == 201
    assert assignments_response.status_code == 200
    assert assignments_response.json()["user_id"] == viewer_id
    assert permissions_me.status_code == 200
    assert "jobs.read" in permissions_me.json()["permissions"]["permission_keys"]
    assert modules_me.status_code == 200
    assert access_items_by_key(modules_me.json())["business.jobs"][
        "access_state"
    ] == "available"
    assert owner_id != viewer_id
