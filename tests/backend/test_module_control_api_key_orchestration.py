import json

from fastapi.testclient import TestClient
import pytest

from backend.app.core.modules import MODULE_MANIFESTS_V1
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.services.api_key_orchestration import (
    ApiKeyIsolationError,
    resolve_module_api_key_for_injection,
)

pytestmark = pytest.mark.integration

TEST_PASSWORD = "example-only-module-control-password"
DEFAULT_ORG_ID = "org_11111111111111111111111111111111"
SECOND_ORG_ID = "org_22222222222222222222222222222222"


def create_user(*, username: str, role: str) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(TEST_PASSWORD),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def login(client: TestClient, *, username: str) -> None:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text


def test_module_control_center_requires_owner(auth_client: TestClient) -> None:
    create_user(username="module_control_viewer", role="viewer")
    login(auth_client, username="module_control_viewer")

    viewer_response = auth_client.get("/api/control-plane/module-control/center")
    assert viewer_response.status_code == 403


def test_module_control_center_auto_registers(owner_client: TestClient) -> None:
    response = owner_client.get("/api/control-plane/module-control/center")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["organization_count"] >= 1
    assert payload["module_count"] >= len(MODULE_MANIFESTS_V1)
    assert payload["auto_registered_count"] >= len(MODULE_MANIFESTS_V1)
    default_group = next(
        group
        for group in payload["organizations"]
        if group["org_id"] == DEFAULT_ORG_ID
    )
    assert all(item["org_id"] == DEFAULT_ORG_ID for item in default_group["modules"])
    assert {"module_id", "enabled", "runtime_status"}.issubset(
        default_group["modules"][0]
    )


def test_module_control_toggle_persists(owner_client: TestClient) -> None:
    disable = owner_client.patch(
        "/api/control-plane/module-control/organizations/"
        f"{DEFAULT_ORG_ID}/registry-entries/core.dashboard",
        json={"enabled": False},
    )
    assert disable.status_code == 200, disable.text
    disabled_item = disable.json()["item"]
    assert disabled_item["enabled"] is False
    assert disabled_item["runtime_status"] == "disabled"

    center = owner_client.get("/api/control-plane/module-control/center").json()
    default_group = next(
        group
        for group in center["organizations"]
        if group["org_id"] == DEFAULT_ORG_ID
    )
    dashboard = next(
        item for item in default_group["modules"] if item["module_id"] == "core.dashboard"
    )
    assert dashboard["enabled"] is False
    assert dashboard["runtime_status"] == "disabled"


def test_api_key_orchestration_is_owner_only(auth_client: TestClient) -> None:
    create_user(username="api_key_viewer", role="viewer")
    login(auth_client, username="api_key_viewer")

    viewer_response = auth_client.get("/api/control-plane/api-key-orchestration/keys")
    assert viewer_response.status_code == 403


def test_api_key_orchestration_never_exposes_key_material(
    owner_client: TestClient,
) -> None:
    created = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{DEFAULT_ORG_ID}/keys",
        json={
            "name": "openai",
            "url": "https://api.openai.example/v1",
            "key_value": "sk-example-module-control-secret",
        },
    )
    assert created.status_code == 201, created.text
    serialized = json.dumps(created.json(), sort_keys=True)
    assert "sk-example-module-control-secret" not in serialized
    assert "encrypted_key_value" not in serialized
    assert "key_fingerprint" not in serialized
    item = created.json()["item"]
    assert item["key_hash_prefix"]
    assert item["assigned_module_ids"] == []


def test_api_key_binding_enforces_org_isolation_and_backend_injection(
    owner_client: TestClient,
) -> None:
    owner_id = owner_client.get("/api/public/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(
            OrganizationRecord(
                org_id=SECOND_ORG_ID,
                org_name="Second Test Org",
                org_type="store",
                owner_user_id=str(owner_id),
                status="active",
                metadata_json={},
            )
        )
        db.commit()

    first_key = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{DEFAULT_ORG_ID}/keys",
        json={
            "name": "serper",
            "url": "https://serper.example",
            "key_value": "serper-secret-value",
        },
    ).json()["item"]
    second_key = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{SECOND_ORG_ID}/keys",
        json={
            "name": "deepseek",
            "url": "https://deepseek.example",
            "key_value": "deepseek-secret-value",
        },
    ).json()["item"]

    cross_org = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{DEFAULT_ORG_ID}/bindings",
        json={
            "module_id": "core.dashboard",
            "key_id": second_key["key_id"],
            "key_alias": "deepseek",
        },
    )
    assert cross_org.status_code == 403

    bound = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{DEFAULT_ORG_ID}/bindings",
        json={
            "module_id": "core.dashboard",
            "key_id": first_key["key_id"],
            "key_alias": "serper",
        },
    )
    assert bound.status_code == 201, bound.text

    with SessionLocal() as db:
        context = resolve_module_api_key_for_injection(
            db,
            org_id=DEFAULT_ORG_ID,
            module_id="core.dashboard",
            key_alias="serper",
        )
        assert context.header_name == "Authorization"
        assert context.header_value == "Bearer serper-secret-value"
        with pytest.raises(ApiKeyIsolationError):
            resolve_module_api_key_for_injection(
                db,
                org_id=DEFAULT_ORG_ID,
                module_id="core.dashboard",
                key_alias="deepseek",
            )
