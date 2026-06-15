import json
import re
from typing import Any, get_args

from fastapi.testclient import TestClient
import pytest

from backend.app.core.modules import MODULE_MANIFESTS_V1
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.schemas.module import (
    ModuleLifecycle,
    ModuleManifestV1,
)
from backend.app.services.module_registry import (
    ALLOWED_DENIED_BEHAVIORS,
    EXTERNAL_DEPENDENCY_KEY_PATTERN,
    ALLOWED_MODULE_CATEGORIES,
    ALLOWED_MODULE_STATUSES,
    MODULE_KEY_PATTERN,
    SENSITIVE_DEPENDENCY_MARKERS,
    build_module_access_state,
    list_module_manifests,
    validate_module_manifests,
)
from backend.app.services.permission_service import (
    CurrentUserPermissionInfo,
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
    session_id = response.cookies.get("barong_ops_session")
    assert session_id
    return session_id


def auth_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"barong_ops_session={token}"}


def seed_permission_registry() -> None:
    with SessionLocal() as db:
        upsert_permission_registry(db)


def access_items_by_key(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(item["module_key"]): item
        for item in payload["items"]  # type: ignore[index]
    }


def contract_manifest(
    *,
    module_key: str = "business.contract_test",
    category: str = "business",
    status: str = "enabled",
    lifecycle: str = "production_released",
    denied_behavior: str | None = None,
    route_namespace: str = "/contract-test",
    api_namespace: str = "no_api",
    no_api: bool = True,
    permission_key: str = "contract_test.read",
    external_dependencies: list[str] | None = None,
) -> dict[str, Any]:
    resolved_denied_behavior = denied_behavior or (
        "show_locked" if category == "business" else "hide_when_denied"
    )
    return {
        "module_key": module_key,
        "display_name": "Contract Test",
        "description": "C07D test-only module manifest fixture.",
        "category": category,
        "status": status,
        "lifecycle": lifecycle,
        "route_namespace": route_namespace,
        "api_namespace": api_namespace,
        "no_api": no_api,
        "navigation": {
            "group": "Contract",
            "label": "Contract Test",
            "icon": "Boxes",
            "order": 999,
            "default_visible": True,
            "owner_only": False,
        },
        "required_permissions": [permission_key],
        "permission_manifest": [
            {
                "permission_key": permission_key,
                "module_key": module_key,
                "category": category,
                "action": "read",
                "label": "Read contract test",
                "description": "Read C07D contract fixture metadata.",
                "risk_level": "low",
                "menu_policy": resolved_denied_behavior,
                "default_scope_type": "global",
                "allowed_scope_types": ["global", "module"],
                "high_risk_confirmation_required": False,
                "operation_log_required": False,
            }
        ],
        "denied_behavior": resolved_denied_behavior,
        "unavailable_behavior": "show_unavailable",
        "external_dependencies": external_dependencies or [],
        "execution_provider_required": False,
        "module_adapter_required": False,
        "sandbox_required": False,
        "feature_flag_key": None,
        "audit_log_actions": [],
        "operation_log_policy": {
            "read": "optional",
            "write": "required",
            "approve": "required",
            "release": "required",
        },
        "allowed_scope_types": ["global", "module"],
        "data_boundary": {
            "reads": [],
            "writes": [],
            "blocked_objects": [
                "server_local_config",
                "external_provider_config",
                "cross_module_writes",
            ],
        },
        "release_requirements": {
            "local_verify": True,
            "staging_acceptance": False,
            "production_archive": False,
            "required_checks": [],
        },
        "staging_acceptance_required": False,
        "production_release_required": False,
        "docs_path": "docs/C07_MODULE_ISOLATION_VERIFICATION.md",
    }


def owner_permission_info() -> CurrentUserPermissionInfo:
    return CurrentUserPermissionInfo(
        is_owner_full_access=True,
        permission_keys=["*"],
        assignments=[],
        scope_summary=[],
    )


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
    allowed_lifecycles = frozenset(get_args(ModuleLifecycle))
    required_manifest_fields = set(ModuleManifestV1.model_fields)

    assert len(module_keys) == len(set(module_keys))
    assert {"admin.users", "admin.permissions", "business.products"}.issubset(
        set(module_keys)
    )
    assert {
        "module_key",
        "display_name",
        "description",
        "category",
        "status",
        "lifecycle",
        "route_namespace",
        "api_namespace",
        "no_api",
        "navigation",
        "required_permissions",
        "permission_manifest",
        "denied_behavior",
        "unavailable_behavior",
        "external_dependencies",
        "execution_provider_required",
        "module_adapter_required",
        "sandbox_required",
        "feature_flag_key",
        "audit_log_actions",
        "operation_log_policy",
        "allowed_scope_types",
        "data_boundary",
        "release_requirements",
        "staging_acceptance_required",
        "production_release_required",
        "docs_path",
    }.issubset(required_manifest_fields)
    for manifest in manifests:
        raw_manifest = next(
            raw
            for raw in MODULE_MANIFESTS_V1
            if raw["module_key"] == manifest.module_key
        )
        assert required_manifest_fields.issubset(set(raw_manifest))
        assert MODULE_KEY_PATTERN.fullmatch(manifest.module_key)
        assert manifest.category in ALLOWED_MODULE_CATEGORIES
        assert manifest.status in ALLOWED_MODULE_STATUSES
        assert manifest.lifecycle in allowed_lifecycles
        assert manifest.denied_behavior in ALLOWED_DENIED_BEHAVIORS
        assert manifest.route_namespace.startswith("/")
        assert re.fullmatch(r"/[a-z0-9][a-z0-9_./-]*", manifest.route_namespace)
        assert manifest.api_namespace
        if manifest.no_api:
            assert manifest.api_namespace == "no_api"
        else:
            assert manifest.api_namespace.startswith("/")
        if manifest.category in {"admin", "system"}:
            assert manifest.denied_behavior == "hide_when_denied"
        if manifest.category == "business":
            assert manifest.denied_behavior == "show_locked"
        declared_permissions = {
            entry.permission_key for entry in manifest.permission_manifest
        }
        assert set(manifest.required_permissions).issubset(declared_permissions)
        for permission_key in declared_permissions:
            assert re.fullmatch(
                r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+",
                permission_key,
            )
            assert permission_key not in {
                "product",
                "task",
                "automation",
                "manage_all",
            }


def test_module_manifest_contract_rejects_invalid_shapes() -> None:
    valid = contract_manifest()

    with pytest.raises(ValueError, match="Duplicate module_key"):
        validate_module_manifests([valid, {**valid}])

    for bad_key in [
        "ContractTest",
        "business.ContractTest",
        "business-contract-test",
        "business",
    ]:
        with pytest.raises(Exception):
            validate_module_manifests([{**valid, "module_key": bad_key}])

    for field_name in [
        "display_name",
        "category",
        "status",
        "lifecycle",
        "route_namespace",
        "api_namespace",
        "navigation",
        "denied_behavior",
    ]:
        missing = {**valid}
        del missing[field_name]
        with pytest.raises(Exception):
            validate_module_manifests([missing])

    for key, value in [
        ("category", "planned"),
        ("status", "executable"),
        ("lifecycle", "live"),
        ("denied_behavior", "show_admin_anyway"),
    ]:
        with pytest.raises(Exception):
            validate_module_manifests([{**valid, key: value}])

    with pytest.raises(ValueError, match="Business modules must default"):
        validate_module_manifests(
            [contract_manifest(category="business", denied_behavior="hide_when_denied")]
        )
    with pytest.raises(ValueError, match="Admin/system modules must default"):
        validate_module_manifests(
            [
                contract_manifest(
                    category="admin",
                    denied_behavior="show_locked",
                    module_key="admin.contract_test",
                )
            ]
        )
    with pytest.raises(ValueError, match="route_namespace must start"):
        validate_module_manifests(
            [contract_manifest(route_namespace="contract-test")]
        )
    with pytest.raises(ValueError, match="no_api manifests must use"):
        validate_module_manifests(
            [contract_manifest(no_api=True, api_namespace="/contract-test")]
        )
    with pytest.raises(ValueError, match="api_namespace must start"):
        validate_module_manifests(
            [
                contract_manifest(
                    api_namespace="contract-test",
                    no_api=False,
                )
            ]
        )


def test_module_permission_manifest_rejects_drift_and_generic_keys() -> None:
    valid = contract_manifest()
    missing_required = {
        **valid,
        "required_permissions": ["contract_test.manage"],
    }
    mismatched_module = contract_manifest()
    mismatched_module["permission_manifest"][0]["module_key"] = "business.other"
    mismatched_category = contract_manifest()
    mismatched_category["permission_manifest"][0]["category"] = "admin"
    mismatched_menu_policy = contract_manifest()
    mismatched_menu_policy["permission_manifest"][0][
        "menu_policy"
    ] = "hide_when_denied"

    for invalid_manifest in [
        missing_required,
        mismatched_module,
        mismatched_category,
        mismatched_menu_policy,
    ]:
        with pytest.raises(ValueError):
            validate_module_manifests([invalid_manifest])

    for generic_permission_key in [
        "product",
        "task",
        "automation",
        "manage_all",
    ]:
        with pytest.raises(ValueError):
            validate_module_manifests(
                [
                    contract_manifest(
                        permission_key=generic_permission_key,
                    )
                ]
            )

    for generic_permission_key in [
        "product",
        "task",
        "automation",
        "manage_all",
    ]:
        assert all(
            generic_permission_key != entry.permission_key
            for manifest in list_module_manifests()
            for entry in manifest.permission_manifest
        )


def test_module_external_dependencies_reject_sensitive_or_live_values() -> None:
    for dependency in [
        "N8N",
        "n8n_url",
        "webhook_secret",
        "api_key",
        "https://example.invalid/hook",
        "woocommerce_password",
        "env",
    ]:
        with pytest.raises(ValueError):
            validate_module_manifests(
                [contract_manifest(external_dependencies=[dependency])]
            )


def test_module_registry_dependency_and_runtime_safety_metadata() -> None:
    manifests = list_module_manifests()
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
        "api_key",
        "bearer ",
        "authorization",
        "webhook_secret",
        "provider_url",
    )

    for manifest in manifests:
        for dependency in manifest.external_dependencies:
            lowered_dependency = dependency.lower()
            assert EXTERNAL_DEPENDENCY_KEY_PATTERN.fullmatch(lowered_dependency)
            for marker in SENSITIVE_DEPENDENCY_MARKERS:
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
    assert not re.search(
        r"\bp0[1-8]\b|p_series|product_page_automation|woocommerce",
        serialized,
    )

    n8n_bridge = next(
        manifest
        for manifest in manifests
        if manifest.module_key == "integration.n8n_test_bridge"
    )
    assert n8n_bridge.category == "integration"
    assert n8n_bridge.status == "adapter_pending"
    assert n8n_bridge.external_dependencies == ["n8n"]
    assert "test" in n8n_bridge.module_key
    assert "test" in n8n_bridge.description.lower()


def test_non_executable_statuses_never_return_executable_access() -> None:
    for status, expected_state in [
        ("planned", "planned"),
        ("adapter_pending", "adapter_pending"),
        ("unavailable", "unavailable"),
    ]:
        manifest = validate_module_manifests(
            [
                contract_manifest(
                    module_key=f"business.contract_{status}",
                    permission_key=f"contract_{status}.read",
                    route_namespace=f"/contract-{status}",
                    status=status,
                    lifecycle="designed",
                )
            ]
        )[0]
        access = build_module_access_state(manifest, owner_permission_info())

        assert access.visible is True
        assert access.unavailable is True
        assert access.executable is False
        assert access.access_state == expected_state


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
    for key, access in owner_items.items():
        if access["category"] in {"admin", "system"}:
            assert access["visible"] is True
            assert access["hidden"] is False
    assert viewer_items["admin.users"]["hidden"] is True
    assert viewer_items["admin.users"]["access_state"] == "hidden"
    assert viewer_items["admin.permissions"]["hidden"] is True
    assert viewer_items["admin.permissions"]["access_state"] == "hidden"
    for key, access in viewer_items.items():
        if access["category"] in {"admin", "system"}:
            assert access["visible"] is False
            assert access["access_state"] == "hidden"
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
