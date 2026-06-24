import copy
import json
import re
from typing import Any, get_args

from fastapi.testclient import TestClient
import pytest

from backend.app.core.module_adapters import MODULE_ADAPTER_CONTRACTS_V1
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.schemas.module_adapter import (
    AdapterStatus,
    AdapterSurface,
    ModuleAdapterContractV1,
)
from backend.app.services.module_adapter_registry import (
    ADAPTER_KEY_PATTERN,
    ADAPTER_DEPENDENCY_KEY_PATTERN,
    ADAPTER_VERSION_PATTERN,
    NON_EXECUTABLE_ADAPTER_STATUSES,
    SENSITIVE_VALUE_MARKERS,
    build_adapter_access_state,
    list_adapter_contracts,
    validate_adapter_contracts,
)
from backend.app.services.module_registry import list_module_manifests
from backend.app.services.permission_service import (
    CurrentUserPermissionInfo,
    upsert_permission_registry,
    upsert_role_default_permission,
)

TEST_PASSWORD = "example-only-c08b-adapter-password"


def create_adapter_registry_user(
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


def owner_permission_info() -> CurrentUserPermissionInfo:
    return CurrentUserPermissionInfo(
        is_owner_full_access=True,
        permission_keys=["*"],
        assignments=[],
        scope_summary=[],
        is_platform_owner=True,
    )


def adapter_items_by_key(
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    return {
        str(item["adapter_key"]): item
        for item in payload["items"]  # type: ignore[index]
    }


def raw_adapter_by_key(adapter_key: str) -> dict[str, Any]:
    return copy.deepcopy(
        next(
            raw
            for raw in MODULE_ADAPTER_CONTRACTS_V1
            if raw["adapter_key"] == adapter_key
        )
    )


def string_values(value: Any):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from string_values(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from string_values(item)


def test_module_adapter_registry_api_requires_login_and_owner_can_read(
    auth_client: TestClient,
) -> None:
    unauth_registry = auth_client.get("/api/control-plane/module-adapters/registry")
    unauth_me = auth_client.get("/api/control-plane/module-adapters/me")
    create_adapter_registry_user(username="c08b_owner_api", role="owner")
    owner_token = login_token(auth_client, username="c08b_owner_api")

    registry = auth_client.get(
        "/api/control-plane/module-adapters/registry",
        headers=auth_headers(owner_token),
    )
    me = auth_client.get(
        "/api/control-plane/module-adapters/me",
        headers=auth_headers(owner_token),
    )

    assert unauth_registry.status_code == 401
    assert unauth_me.status_code == 401
    assert registry.status_code == 200
    assert me.status_code == 200
    registry_payload = registry.json()
    assert registry_payload["count"] == len(registry_payload["items"])
    adapter_keys = {item["adapter_key"] for item in registry_payload["items"]}
    assert {
        "core.dashboard.adapter",
        "admin.users.adapter",
        "admin.permissions.adapter",
        "k.product_knowledge.adapter",
        "business.products.placeholder.adapter",
        "integration.n8n_test_bridge.adapter",
    } == adapter_keys
    assert me.json()["is_owner_full_access"] is True

    for value in string_values(registry_payload):
        lowered = value.lower()
        assert "password" not in lowered
        assert "authorization" not in lowered
        assert "bearer " not in lowered
        assert "http://" not in lowered
        assert "https://" not in lowered
        assert ".env" not in lowered
        assert "webhook" not in lowered
        assert "provider_url" not in lowered


def test_static_adapter_registry_contract_rules() -> None:
    adapters = validate_adapter_contracts()
    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    allowed_statuses = frozenset(get_args(AdapterStatus))
    allowed_surfaces = frozenset(get_args(AdapterSurface))
    required_contract_fields = set(ModuleAdapterContractV1.model_fields)

    adapter_keys = [adapter.adapter_key for adapter in adapters]
    assert len(adapter_keys) == len(set(adapter_keys))
    assert {
        "core.dashboard.adapter",
        "admin.users.adapter",
        "admin.permissions.adapter",
        "k.product_knowledge.adapter",
        "business.products.placeholder.adapter",
        "integration.n8n_test_bridge.adapter",
    } == set(adapter_keys)

    for adapter in adapters:
        raw_adapter = next(
            raw
            for raw in MODULE_ADAPTER_CONTRACTS_V1
            if raw["adapter_key"] == adapter.adapter_key
        )
        assert required_contract_fields.issubset(set(raw_adapter))
        assert ADAPTER_KEY_PATTERN.fullmatch(adapter.adapter_key)
        assert ADAPTER_VERSION_PATTERN.fullmatch(adapter.adapter_version)
        assert adapter.adapter_status in allowed_statuses
        assert adapter.lifecycle in allowed_statuses
        assert adapter.module_key in module_keys
        assert set(adapter.supported_surfaces).issubset(allowed_surfaces)
        assert adapter.status_provider.live_provider_connected is False
        assert adapter.status_provider.secret_read_allowed is False
        assert adapter.health_provider.live_check_allowed is False
        assert adapter.health_provider.secret_read_allowed is False
        assert adapter.execution_requirements.executable_before_c09 is False
        assert adapter.sandbox_requirements.network_access_allowed is False
        assert adapter.sandbox_requirements.file_system_access_allowed is False

        manifest = next(
            manifest
            for manifest in list_module_manifests()
            if manifest.module_key == adapter.module_key
        )
        for route in adapter.route_bindings:
            assert route.module_key == adapter.module_key
            assert route.route_namespace == manifest.route_namespace
            assert route.path == manifest.route_namespace or route.path.startswith(
                f"{manifest.route_namespace.rstrip('/')}/"
            )
        for api in adapter.api_bindings:
            assert api.module_key == adapter.module_key
            if api.no_api:
                assert api.api_namespace == "no_api"
                assert api.path == "no_api"
                assert api.method == "NO_API"
            else:
                assert api.api_namespace == manifest.api_namespace
                assert api.path == manifest.api_namespace or api.path.startswith(
                    f"{manifest.api_namespace.rstrip('/')}/"
                )
        for nav in adapter.nav_bindings:
            assert nav.module_key == adapter.module_key
            assert nav.denied_behavior == manifest.denied_behavior

        action_keys = {action.action_key for action in adapter.actions}
        assert action_keys == {
            contract.action_key for contract in adapter.action_contracts
        }
        for action in adapter.actions:
            assert action.required_permission
            assert action.risk_level in {"low", "medium", "high", "critical"}
            assert action.operation_log_action
            assert action.executable_before_c09 is False
            if action.requires_execution_provider:
                assert adapter.execution_requirements.requires_execution_provider
        for contract in adapter.action_contracts:
            assert contract.required_permission
            assert contract.risk_level in {"low", "medium", "high", "critical"}
            assert contract.operation_log_action
            assert contract.executable_before_c09 is False
            if contract.requires_execution_provider:
                assert adapter.execution_requirements.requires_execution_provider
        for dependency in adapter.dependency_declarations:
            assert ADAPTER_DEPENDENCY_KEY_PATTERN.fullmatch(
                dependency.dependency_key
            )
            assert dependency.live_connection_allowed is False
            assert dependency.provider_status == "declared_only"


def test_adapter_contract_rejects_invalid_shapes_and_escapes() -> None:
    valid = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[0])

    with pytest.raises(ValueError, match="Duplicate adapter_key"):
        validate_adapter_contracts([valid, copy.deepcopy(valid)])

    for bad_key in [
        "Core.Dashboard.Adapter",
        "core-dashboard-adapter",
        "core",
    ]:
        invalid = copy.deepcopy(valid)
        invalid["adapter_key"] = bad_key
        with pytest.raises(ValueError):
            validate_adapter_contracts([invalid])

    invalid_version = copy.deepcopy(valid)
    invalid_version["adapter_version"] = "v1"
    with pytest.raises(ValueError, match="adapter_version"):
        validate_adapter_contracts([invalid_version])

    invalid_module = copy.deepcopy(valid)
    invalid_module["module_key"] = "business.missing"
    with pytest.raises(ValueError, match="module_key is not registered"):
        validate_adapter_contracts([invalid_module])

    route_escape = copy.deepcopy(valid)
    route_escape["route_bindings"][0]["path"] = "/api/app/users"
    with pytest.raises(ValueError, match="route escapes"):
        validate_adapter_contracts([route_escape])

    api_escape = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[1])
    api_escape["api_bindings"][0]["path"] = "/api/app/permissions/me"
    with pytest.raises(ValueError, match="api escapes"):
        validate_adapter_contracts([api_escape])

    nav_drift = copy.deepcopy(valid)
    nav_drift["nav_bindings"][0]["module_key"] = "admin.users"
    with pytest.raises(ValueError, match="nav module_key drift"):
        validate_adapter_contracts([nav_drift])

    action_drift = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[1])
    action_drift["actions"][0]["operation_log_action"] = "user.other"
    with pytest.raises(ValueError, match="operation log binding drift"):
        validate_adapter_contracts([action_drift])

    executable_action = raw_adapter_by_key("business.products.placeholder.adapter")
    executable_action["actions"][0]["executable_before_c09"] = True
    with pytest.raises(ValueError, match="action is executable"):
        validate_adapter_contracts([executable_action])

    execution_drift = raw_adapter_by_key("business.products.placeholder.adapter")
    execution_drift["execution_requirements"]["requires_execution_provider"] = False
    with pytest.raises(ValueError, match="execution action lacks requirement"):
        validate_adapter_contracts([execution_drift])

    dependency_sensitive = raw_adapter_by_key("integration.n8n_test_bridge.adapter")
    dependency_sensitive["dependency_declarations"][0][
        "safe_unavailable_message"
    ] = "https://example.invalid/hook"
    with pytest.raises(ValueError, match="dependency contains sensitive"):
        validate_adapter_contracts([dependency_sensitive])


def test_adapter_contract_rejects_c08d_runtime_regressions() -> None:
    missing_action_permission = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[1])
    del missing_action_permission["actions"][0]["required_permission"]
    with pytest.raises(Exception):
        validate_adapter_contracts([missing_action_permission])

    missing_contract_risk = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[1])
    del missing_contract_risk["action_contracts"][0]["risk_level"]
    with pytest.raises(Exception):
        validate_adapter_contracts([missing_contract_risk])

    missing_contract_operation_log = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[1])
    del missing_contract_operation_log["action_contracts"][0][
        "operation_log_action"
    ]
    with pytest.raises(Exception):
        validate_adapter_contracts([missing_contract_operation_log])

    approval_drift = raw_adapter_by_key("business.products.placeholder.adapter")
    approval_drift["actions"][0]["requires_approval"] = True
    with pytest.raises(ValueError, match="approval action lacks requirement"):
        validate_adapter_contracts([approval_drift])

    contract_execution_drift = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[1])
    contract_execution_drift["action_contracts"][0][
        "requires_execution_provider"
    ] = True
    with pytest.raises(ValueError, match="contract lacks execution requirement"):
        validate_adapter_contracts([contract_execution_drift])

    live_dependency = raw_adapter_by_key("integration.n8n_test_bridge.adapter")
    live_dependency["dependency_declarations"][0][
        "live_connection_allowed"
    ] = True
    with pytest.raises(ValueError, match="dependency declares live connection"):
        validate_adapter_contracts([live_dependency])

    connected_provider = raw_adapter_by_key("integration.n8n_test_bridge.adapter")
    connected_provider["dependency_declarations"][0][
        "provider_status"
    ] = "not_connected"
    with pytest.raises(ValueError, match="dependency must remain declared_only"):
        validate_adapter_contracts([connected_provider])

    live_status_provider = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[0])
    live_status_provider["status_provider"]["live_provider_connected"] = True
    with pytest.raises(ValueError, match="status provider is live"):
        validate_adapter_contracts([live_status_provider])

    live_health_provider = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[0])
    live_health_provider["health_provider"]["live_check_allowed"] = True
    with pytest.raises(ValueError, match="health provider is live"):
        validate_adapter_contracts([live_health_provider])

    formal_scope = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[0])
    formal_scope["scope_bindings"][0]["status"] = "declared"
    with pytest.raises(Exception):
        validate_adapter_contracts([formal_scope])

    sandbox_network = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[0])
    sandbox_network["sandbox_requirements"]["network_access_allowed"] = True
    with pytest.raises(ValueError, match="sandbox allows network"):
        validate_adapter_contracts([sandbox_network])


def test_adapter_contracts_are_versioned_serializable_and_traceable() -> None:
    adapters = list_adapter_contracts()
    manifests = {manifest.module_key: manifest for manifest in list_module_manifests()}
    blocked_runtime_fragments = (
        ".env.production",
        ".env.staging",
        "auth_token_secret",
        "owner_password",
        "postgres_password",
        "provider_url",
        "webhook_secret",
        "bearer ",
        "authorization",
        "http://",
        "https://",
        "ops.barongyekhna.com",
        "console_postgres",
        "live_connected",
        "production_url",
        "staging_url",
    )

    serialized = json.dumps(
        [adapter.model_dump(mode="json") for adapter in adapters],
        sort_keys=True,
    ).lower()
    for fragment in blocked_runtime_fragments:
        assert fragment not in serialized
    for value in string_values(
        [adapter.model_dump(mode="json") for adapter in adapters]
    ):
        assert "api_key" not in value.lower()

    for adapter in adapters:
        json.dumps(adapter.model_dump(mode="json"), sort_keys=True)
        manifest = manifests[adapter.module_key]
        manifest_permissions = {
            entry.permission_key for entry in manifest.permission_manifest
        }
        manifest_permissions.update(manifest.required_permissions)

        for data_contract in adapter.data_contracts:
            assert ADAPTER_VERSION_PATTERN.fullmatch(
                data_contract.contract_version
            )
            assert data_contract.contract_key.endswith(".v1")
            assert data_contract.module_key == adapter.module_key
            assert data_contract.owner_module == adapter.module_key
            assert data_contract.test_fixture_path is None
            assert data_contract.version_policy
            assert data_contract.breaking_change_policy

        for input_contract in adapter.input_contracts:
            assert input_contract.contract_key.endswith(".v1")
            assert input_contract.sensitive_fields == []
            assert input_contract.redaction_policy == "safe_fields_only"

        for output_contract in adapter.output_contracts:
            assert output_contract.contract_key.endswith(".v1")
            assert output_contract.sensitive_fields == []
            assert output_contract.redaction_policy == "safe_fields_only"

        for binding in adapter.permission_bindings:
            assert binding.module_key == adapter.module_key
            assert binding.permission_key in manifest_permissions
            assert binding.used_by
            assert binding.registry_status == "registered"

        for binding in adapter.scope_bindings:
            assert binding.status == "adapter_pending"
            assert binding.requires_c18_scope_adapter is True
            assert binding.fallback_before_c18

        for binding in adapter.feature_flag_bindings:
            assert binding.status == "declared_only"
            assert binding.switch_provider_state == "not_implemented_c08b"

        for contract in adapter.test_contracts:
            assert contract.required is True
            assert contract.test_key.startswith("c08")


def test_adapter_dependency_and_runtime_safety_metadata() -> None:
    adapters = list_adapter_contracts()
    serialized = json.dumps(
        [adapter.model_dump() for adapter in adapters],
        sort_keys=True,
    ).lower()

    assert "k01" not in serialized
    assert not re.search(
        r"\bp0[1-8]\b|p_series|product_page_automation",
        serialized,
    )
    assert "woocommerce" not in serialized
    assert "minio" not in serialized
    assert "filebrowser" not in serialized

    for value in string_values([adapter.model_dump() for adapter in adapters]):
        lowered = value.lower()
        assert "password" not in lowered
        assert "authorization" not in lowered
        assert "bearer " not in lowered
        assert "http://" not in lowered
        assert "https://" not in lowered
        assert ".env" not in lowered
        assert "webhook" not in lowered
        assert "provider_url" not in lowered

    for adapter in adapters:
        if adapter.adapter_status in NON_EXECUTABLE_ADAPTER_STATUSES:
            assert all(
                action.executable_before_c09 is False
                for action in adapter.actions
            )
            assert adapter.execution_requirements.executable_before_c09 is False
        for dependency in adapter.dependency_declarations:
            for marker in SENSITIVE_VALUE_MARKERS:
                assert marker not in dependency.dependency_key

    n8n_bridge = next(
        adapter
        for adapter in adapters
        if adapter.adapter_key == "integration.n8n_test_bridge.adapter"
    )
    k_adapter = next(
        adapter
        for adapter in adapters
        if adapter.adapter_key == "k.product_knowledge.adapter"
    )
    assert k_adapter.adapter_status == "production_ready"
    assert k_adapter.module_key == "k.product_knowledge"
    assert {
        dependency.dependency_key
        for dependency in k_adapter.dependency_declarations
    } == {"serp", "chatgpt", "claude_opus", "deepseek", "ai_provider", "n8n"}
    assert all(
        dependency.live_connection_allowed is False
        for dependency in k_adapter.dependency_declarations
    )
    assert n8n_bridge.adapter_status == "adapter_pending"
    assert n8n_bridge.dependency_declarations[0].dependency_key == "n8n"
    assert n8n_bridge.dependency_declarations[0].live_connection_allowed is False
    assert n8n_bridge.status_provider.live_provider_connected is False
    assert n8n_bridge.health_provider.live_check_allowed is False
    assert all(
        action.executable_before_c09 is False for action in n8n_bridge.actions
    )


def test_draft_deprecated_disabled_and_approval_actions_are_not_executable() -> None:
    for status, expected_state in [
        ("draft", "unavailable"),
        ("deprecated", "unavailable"),
        ("disabled", "disabled"),
    ]:
        raw = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[0])
        raw["adapter_status"] = status
        raw["lifecycle"] = status
        adapter = validate_adapter_contracts([raw])[0]
        access = build_adapter_access_state(adapter, owner_permission_info())

        assert access.adapter_access_state == expected_state
        assert access.unavailable is True
        assert access.available_actions == []
        assert access.unavailable_actions == []
        assert access.disabled_surfaces == adapter.supported_surfaces

    admin_users = next(
        adapter
        for adapter in list_adapter_contracts()
        if adapter.adapter_key == "admin.users.adapter"
    )
    access = build_adapter_access_state(admin_users, owner_permission_info())

    assert access.adapter_access_state == "available"
    assert access.requires_approval is True
    assert access.available_actions == []
    assert "admin.users.manage" in access.unavailable_actions
    assert any(
        contract.action_key == "admin.users.manage"
        and contract.requires_approval is True
        and contract.executable_before_c09 is False
        for contract in access.action_contracts
    )


def test_module_adapter_router_exposes_only_read_contract_apis(
    auth_client: TestClient,
) -> None:
    adapter_routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in auth_client.app.routes
        if str(getattr(route, "path", "")).startswith("/api/control-plane/module-adapters")
    ]

    assert ("/api/control-plane/module-adapters/registry", {"GET"}) in adapter_routes
    assert ("/api/control-plane/module-adapters/me", {"GET"}) in adapter_routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in adapter_routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|execution|run)\b", path)
        for path, _ in adapter_routes
    )


def test_owner_and_non_owner_adapter_access_states(
    auth_client: TestClient,
) -> None:
    create_adapter_registry_user(username="c08b_owner_access", role="owner")
    create_adapter_registry_user(username="c08b_viewer_access", role="viewer")
    owner_token = login_token(auth_client, username="c08b_owner_access")
    viewer_token = login_token(auth_client, username="c08b_viewer_access")

    owner_response = auth_client.get(
        "/api/control-plane/module-adapters/me",
        headers=auth_headers(owner_token),
    )
    viewer_response = auth_client.get(
        "/api/control-plane/module-adapters/me",
        headers=auth_headers(viewer_token),
    )

    assert owner_response.status_code == 200
    assert viewer_response.status_code == 200
    owner_items = adapter_items_by_key(owner_response.json())
    viewer_items = adapter_items_by_key(viewer_response.json())

    assert owner_items["admin.users.adapter"]["visible"] is True
    assert owner_items["admin.users.adapter"]["adapter_access_state"] == "available"
    assert owner_items["admin.permissions.adapter"]["visible"] is True
    assert owner_items["admin.permissions.adapter"]["adapter_access_state"] == (
        "available"
    )
    assert "action_panel" in owner_items["admin.users.adapter"][
        "disabled_surfaces"
    ]
    assert owner_items["admin.users.adapter"]["available_actions"] == []
    assert set(owner_items["admin.users.adapter"]["unavailable_actions"]) == {
        "admin.users.read",
        "admin.users.manage",
    }

    assert viewer_items["admin.users.adapter"]["hidden"] is True
    assert viewer_items["admin.users.adapter"]["adapter_access_state"] == "hidden"
    assert viewer_items["admin.users.adapter"]["supported_surfaces"] == []
    assert viewer_items["admin.users.adapter"]["action_contracts"] == []
    assert viewer_items["admin.permissions.adapter"]["hidden"] is True
    assert viewer_items["admin.permissions.adapter"]["adapter_access_state"] == (
        "hidden"
    )
    assert viewer_items["business.products.placeholder.adapter"]["visible"] is True
    assert viewer_items["business.products.placeholder.adapter"]["locked"] is True
    assert viewer_items["business.products.placeholder.adapter"][
        "adapter_access_state"
    ] == "locked"
    assert "products.read" in viewer_items["business.products.placeholder.adapter"][
        "missing_permissions"
    ]
    assert viewer_items["core.dashboard.adapter"]["adapter_access_state"] == (
        "available"
    )


def test_role_defaults_super_admin_and_pending_disabled_adapter_access(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    create_adapter_registry_user(
        username="c08b_viewer_role_default",
        role="viewer",
    )
    create_adapter_registry_user(
        username="c08b_super_admin_default",
        role="super_admin",
    )
    with SessionLocal() as db:
        upsert_role_default_permission(
            db,
            role="viewer",
            permission_key="modules.read",
        )
        upsert_role_default_permission(
            db,
            role="super_admin",
            permission_key="permissions.manage",
        )

    viewer_token = login_token(
        auth_client,
        username="c08b_viewer_role_default",
    )
    super_admin_token = login_token(
        auth_client,
        username="c08b_super_admin_default",
    )

    viewer_response = auth_client.get(
        "/api/control-plane/module-adapters/me",
        headers=auth_headers(viewer_token),
    )
    super_admin_response = auth_client.get(
        "/api/control-plane/module-adapters/me",
        headers=auth_headers(super_admin_token),
    )

    assert viewer_response.status_code == 200
    assert super_admin_response.status_code == 200
    viewer_items = adapter_items_by_key(viewer_response.json())
    super_admin_items = adapter_items_by_key(super_admin_response.json())
    assert viewer_items["business.products.placeholder.adapter"][
        "adapter_access_state"
    ] == "locked"
    assert viewer_items["integration.n8n_test_bridge.adapter"][
        "adapter_access_state"
    ] == "hidden"
    assert super_admin_items["admin.users.adapter"]["adapter_access_state"] == (
        "hidden"
    )
    assert super_admin_items["admin.permissions.adapter"][
        "adapter_access_state"
    ] == "hidden"

    pending_adapter = next(
        adapter
        for adapter in list_adapter_contracts()
        if adapter.adapter_key == "business.products.placeholder.adapter"
    )
    pending_access = build_adapter_access_state(
        pending_adapter,
        owner_permission_info(),
    )
    assert pending_access.adapter_access_state == "adapter_pending"
    assert pending_access.unavailable is True
    assert pending_access.available_actions == []
    assert pending_access.unavailable_actions == [
        "business.products.placeholder.prepare"
    ]
    assert pending_access.execution_provider_state == "adapter_pending"

    disabled_raw = copy.deepcopy(MODULE_ADAPTER_CONTRACTS_V1[0])
    disabled_raw["adapter_status"] = "disabled"
    disabled_raw["lifecycle"] = "disabled"
    disabled_adapter = validate_adapter_contracts([disabled_raw])[0]
    disabled_access = build_adapter_access_state(
        disabled_adapter,
        owner_permission_info(),
    )
    assert disabled_access.adapter_access_state == "disabled"
    assert disabled_access.unavailable is True
    assert disabled_access.available_actions == []


def test_execution_action_contracts_are_unavailable_before_c09() -> None:
    execution_raw = raw_adapter_by_key("business.products.placeholder.adapter")
    execution_raw["adapter_status"] = "contract_ready"
    execution_raw["lifecycle"] = "contract_ready"
    execution_adapter = validate_adapter_contracts([execution_raw])[0]

    access = build_adapter_access_state(
        execution_adapter,
        owner_permission_info(),
    )

    assert access.adapter_access_state == "unavailable"
    assert access.requires_execution_provider is True
    assert access.execution_provider_state == "required_not_implemented_c08b"
    assert access.available_actions == []
    assert access.unavailable_actions == [
        "business.products.placeholder.prepare"
    ]
    assert all(
        contract.executable_before_c09 is False
        for contract in access.action_contracts
    )


def test_c08b_regressions_modules_permissions_assignments_users_register(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    owner_id = create_adapter_registry_user(
        username="c08b_owner_regression",
        role="owner",
    )
    viewer_id = create_adapter_registry_user(
        username="c08b_viewer_regression",
        role="viewer",
    )
    owner_token = login_token(auth_client, username="c08b_owner_regression")
    viewer_token = login_token(auth_client, username="c08b_viewer_regression")

    modules_registry = auth_client.get(
        "/api/control-plane/modules/registry",
        headers=auth_headers(owner_token),
    )
    modules_me = auth_client.get(
        "/api/control-plane/modules/me",
        headers=auth_headers(viewer_token),
    )
    permissions_me_before = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(viewer_token),
    )
    viewer_users = auth_client.get("/api/app/users", headers=auth_headers(viewer_token))
    missing_register = auth_client.post(
        "/api/public/auth/register",
        json={"username": "blocked", "password": "blocked"},
    )
    grant_response = auth_client.post(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
        json={"permission_key": "artifacts.read", "reason": "C08B regression."},
    )
    assignments_response = auth_client.get(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
    )
    permissions_me_after = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(viewer_token),
    )

    assert modules_registry.status_code == 200
    assert modules_me.status_code == 200
    assert permissions_me_before.status_code == 200
    assert permissions_me_before.json()["permissions"]["permission_keys"] == []
    assert viewer_users.status_code == 403
    assert missing_register.status_code == 404
    assert grant_response.status_code == 201
    assert assignments_response.status_code == 200
    assert assignments_response.json()["user_id"] == viewer_id
    assert permissions_me_after.status_code == 200
    assert "artifacts.read" in permissions_me_after.json()["permissions"][
        "permission_keys"
    ]
    assert owner_id != viewer_id
