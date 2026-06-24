from fastapi.testclient import TestClient

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.user import User

PASSWORD = "example-only-control-plane-password"


def create_user(username: str, role: str) -> None:
    with SessionLocal() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(PASSWORD),
                role=role,
                is_active=True,
            )
        )
        db.commit()


def login(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200


def test_control_plane_requires_privileged_role(
    auth_client: TestClient,
) -> None:
    create_user("c16_viewer", "viewer")
    create_user("c16_super_admin", "super_admin")

    unauthenticated = auth_client.get(
        "/api/control-plane/ai-execution-bindings/registry"
    )
    assert unauthenticated.status_code == 401

    login(auth_client, "c16_viewer")
    viewer_response = auth_client.get(
        "/api/control-plane/ai-execution-bindings/registry"
    )
    assert viewer_response.status_code == 403

    auth_client.cookies.clear()
    login(auth_client, "c16_super_admin")
    super_admin_response = auth_client.get(
        "/api/control-plane/ai-execution-bindings/registry"
    )
    assert super_admin_response.status_code == 200


def test_control_plane_has_no_app_or_legacy_bypass(
    auth_client: TestClient,
) -> None:
    create_user("c16_owner", "owner")
    login(auth_client, "c16_owner")

    legacy_binding = auth_client.get("/ai-execution-bindings/registry")
    app_binding = auth_client.get("/api/app/ai-execution-bindings/registry")
    app_execution = auth_client.post("/api/app/n8n-test/run")
    public_execution = auth_client.post("/api/public/n8n-test/run")

    assert legacy_binding.status_code == 404
    assert app_binding.status_code == 404
    assert app_execution.status_code == 404
    assert public_execution.status_code == 404


def test_control_plane_unknown_routes_default_to_not_found_after_boundary(
    auth_client: TestClient,
) -> None:
    create_user("c16_owner_unknown", "owner")
    login(auth_client, "c16_owner_unknown")

    response = auth_client.get("/api/control-plane/not-registered")

    assert response.status_code == 404


def test_control_plane_system_role_no_longer_bypasses_boundary(
    auth_client: TestClient,
) -> None:
    create_user("c16_system", "system")
    login(auth_client, "c16_system")

    response = auth_client.get("/api/control-plane/not-registered")

    assert response.status_code == 403


def test_control_plane_operator_no_longer_bypasses_boundary(
    auth_client: TestClient,
) -> None:
    create_user("c16_operator", "operator")
    login(auth_client, "c16_operator")

    response = auth_client.get("/api/control-plane/not-registered")

    assert response.status_code == 403
