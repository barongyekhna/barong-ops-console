import json
import time

from fastapi.testclient import TestClient
import pytest

from backend.app.core.modules import MODULE_MANIFESTS_V1
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app import main as app_main
from backend.app.middleware import data_isolation as data_isolation_middleware
from backend.app.middleware import org_context as org_context_middleware
from backend.app.models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.provider_config import ProviderConfigRecord
from backend.app.models.user import User
from backend.app.services.api_key_orchestration import (
    ApiKeyIsolationError,
    K_SERIES_MODULE_ID,
    K_SERIES_ORGANIZATION_NAME,
    K_SERIES_PROVIDER_ALIASES,
    reevaluate_k_series_api_keys,
    resolve_module_api_key_for_injection,
)
from backend.app.services.rw_keepa_ingestion import (
    resolve_keepa_context_for_asin_ingestion,
)
from backend.app.services import module_control_cache_service
from tests.fixtures.organization_fixtures import (
    DEFAULT_TEST_ORG_DB_ID,
)

pytestmark = pytest.mark.integration

TEST_PASSWORD = "example-only-module-control-password"
DEFAULT_ORG_ID = DEFAULT_TEST_ORG_DB_ID
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


def test_module_control_center_scopes_non_owner_view(auth_client: TestClient) -> None:
    create_user(username="module_control_viewer", role="viewer")
    login(auth_client, username="module_control_viewer")

    viewer_response = auth_client.get("/api/control-plane/module-control/center")
    assert viewer_response.status_code == 200
    payload = viewer_response.json()
    assert payload["organization_count"] == 0
    assert payload["module_count"] == 0
    assert payload["organizations"] == []


def test_module_control_center_auto_registers(owner_client: TestClient) -> None:
    response = owner_client.get(
        "/api/control-plane/module-control/center?force_refresh=1"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["cache_status"] in {"fresh", "stale"}
    assert payload["organization_count"] >= 1
    assert payload["module_count"] >= len(MODULE_MANIFESTS_V1) - 1
    assert payload["auto_registered_count"] >= len(MODULE_MANIFESTS_V1) - 1
    default_group = next(
        group
        for group in payload["organizations"]
        if group["org_id"] == DEFAULT_ORG_ID
    )
    assert all(item["org_id"] == DEFAULT_ORG_ID for item in default_group["modules"])
    assert {"module_id", "enabled", "runtime_status"}.issubset(
        default_group["modules"][0]
    )
    k_module = next(
        item
        for item in default_group["modules"]
        if item["module_id"] == "k.product_knowledge"
    )
    assert k_module["enabled"] is True
    assert k_module["runtime_status"] == "active"
    module_by_id = {item["module_id"]: item for item in default_group["modules"]}
    assert "i.image_system" in module_by_id
    assert module_by_id["r.warehouse"]["enabled"] is True
    assert module_by_id["r.warehouse"]["runtime_status"] == "active"
    assert module_by_id["r.analysis"]["enabled"] is False
    assert module_by_id["r.analysis"]["runtime_status"] == "disabled"


def test_module_control_scopes_i_series_to_target_organization(
    owner_client: TestClient,
) -> None:
    owner_id = owner_client.get("/api/public/auth/me").json()["id"]
    target_org_id = DEFAULT_ORG_ID
    other_org_id = "org_44444444444444444444444444444444"
    with SessionLocal() as db:
        db.add(
            OrganizationRecord(
                org_id=other_org_id,
                org_name="涌龙麟（吉林）电子产品制造有限公司",
                org_type="store",
                owner_user_id=str(owner_id),
                status="active",
                metadata_json={},
            )
        )
        db.commit()

    response = owner_client.get(
        "/api/control-plane/module-control/center?force_refresh=1"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    target_group = next(
        group
        for group in payload["organizations"]
        if group["org_id"] == target_org_id
    )
    other_group = next(
        group
        for group in payload["organizations"]
        if group["org_id"] == other_org_id
    )

    assert any(
        item["module_id"] == "i.image_system"
        for item in target_group["modules"]
    )
    assert all(
        item["module_id"] != "i.image_system"
        for item in other_group["modules"]
    )

    blocked = owner_client.patch(
        "/api/control-plane/module-control/organizations/"
        f"{other_org_id}/registry-entries/i.image_system",
        json={"enabled": False},
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "module_not_available_for_organization"


def test_module_control_center_uses_cached_snapshot(
    owner_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = owner_client.get(
        "/api/control-plane/module-control/center?force_refresh=1"
    )
    assert response.status_code == 200, response.text

    def fail_live_rebuild(*args, **kwargs):
        raise AssertionError("module control center rebuilt instead of using cache")

    monkeypatch.setattr(
        module_control_cache_service,
        "build_module_control_center",
        fail_live_rebuild,
    )

    cached_response = owner_client.get("/api/control-plane/module-control/center")
    assert cached_response.status_code == 200, cached_response.text
    cached_payload = cached_response.json()
    assert cached_payload["cache_status"] == "fresh"
    assert cached_payload["organization_count"] >= 1


def test_module_control_center_uses_lightweight_middleware_boundary(
    owner_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warm_response = owner_client.get(
        "/api/control-plane/module-control/center?force_refresh=1"
    )
    assert warm_response.status_code == 200, warm_response.text

    def fail_full_chain(*args, **kwargs):
        raise AssertionError("full middleware pipeline should not run for center")

    monkeypatch.setattr(app_main, "validate_session", fail_full_chain)
    if hasattr(org_context_middleware, "validate_session"):
        monkeypatch.setattr(
            org_context_middleware,
            "validate_session",
            fail_full_chain,
        )
    monkeypatch.setattr(org_context_middleware, "build_org_context", fail_full_chain)
    monkeypatch.setattr(
        data_isolation_middleware,
        "_c05b_schema_without_c18_data_isolation",
        fail_full_chain,
    )

    response = owner_client.get("/api/control-plane/module-control/center")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["cache_status"] in {"fresh", "stale"}
    assert payload["organization_count"] >= 1


def test_module_control_cache_miss_returns_partial_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_control_cache_service.reset_module_control_center_cache_for_tests()

    def slow_refresh():
        time.sleep(0.05)
        raise RuntimeError("slow backend aggregation")

    monkeypatch.setattr(
        module_control_cache_service,
        "_refresh_snapshot",
        slow_refresh,
    )
    module_control_cache_service.start_module_control_cache_worker()

    started = time.perf_counter()
    response = module_control_cache_service.get_module_control_center_cached(
        max_wait_seconds=0.001,
    )
    elapsed = time.perf_counter() - started

    assert response.cache_status == "partial"
    assert response.organization_count == 0
    assert elapsed < 0.03
    module_control_cache_service.stop_module_control_cache_worker()
    module_control_cache_service.reset_module_control_center_cache_for_tests()


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
    assert item["status"] == "active"
    assert item["runtime_state"] == "enabled"
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
    disabled_first_key = owner_client.patch(
        "/api/control-plane/api-key-orchestration/keys/"
        f"{first_key['key_id']}",
        json={"status": "disabled"},
    )
    assert disabled_first_key.status_code == 200, disabled_first_key.text
    assert disabled_first_key.json()["item"]["status"] == "disabled"
    assert disabled_first_key.json()["item"]["runtime_state"] == "disabled"
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
    keys_after_bind = owner_client.get(
        "/api/control-plane/api-key-orchestration/keys"
    )
    rebound_key = next(
        item
        for item in keys_after_bind.json()["items"]
        if item["key_id"] == first_key["key_id"]
    )
    assert rebound_key["status"] == "active"
    assert rebound_key["runtime_state"] == "enabled"
    assert "core.dashboard" in rebound_key["assigned_module_ids"]

    for alias in ("serp", "chatgpt", "claude_opus"):
        key = owner_client.post(
            "/api/control-plane/api-key-orchestration/organizations/"
            f"{DEFAULT_ORG_ID}/keys",
            json={
                "name": f"k-{alias}",
                "url": f"https://{alias}.example",
                "key_value": f"k-{alias}-secret-value",
            },
        ).json()["item"]
        k_binding = owner_client.post(
            "/api/control-plane/api-key-orchestration/organizations/"
            f"{DEFAULT_ORG_ID}/bindings",
            json={
                "module_id": "k.product_knowledge",
                "key_id": key["key_id"],
                "key_alias": alias,
            },
        )
        assert k_binding.status_code == 201, k_binding.text

    bindings = owner_client.get(
        "/api/control-plane/api-key-orchestration/bindings"
    )
    assert bindings.status_code == 200, bindings.text
    k_aliases = {
        item["key_alias"]
        for item in bindings.json()["items"]
        if item["module_id"] == "k.product_knowledge"
    }
    assert {"serp", "chatgpt", "claude_opus"}.issubset(k_aliases)

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


def test_keepa_key_type_binds_to_r_warehouse_ingestion(
    owner_client: TestClient,
) -> None:
    target_org_id = DEFAULT_ORG_ID

    key_types = owner_client.get(
        "/api/control-plane/api-key-orchestration/key-types"
    )
    assert key_types.status_code == 200, key_types.text
    keepa_type = next(
        item for item in key_types.json()["items"] if item["type"] == "keepa"
    )
    assert keepa_type == {
        "type": "keepa",
        "name": "Keepa API",
        "description": "Amazon ASIN market intelligence API",
        "provider": "keepa",
        "auth_type": "api_key",
        "enabled": True,
        "scope": ["R-W"],
        "validation_endpoint": "https://api.keepa.com/token?key={key}",
        "default_url": "https://api.keepa.com",
    }

    created = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{target_org_id}/keys",
        json={
            "name": "Keepa API",
            "url": "https://api.keepa.com",
            "key_value": "keepa-test-secret",
            "key_type": "keepa",
        },
    )
    assert created.status_code == 201, created.text
    created_item = created.json()["item"]
    assert created_item["key_type"] == "keepa"
    assert created_item["provider"] == "keepa"
    assert created_item["auth_type"] == "api_key"
    assert created_item["scope"] == ["R-W"]
    assert (
        created_item["validation_endpoint"]
        == "https://api.keepa.com/token?key={key}"
    )

    bound = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{target_org_id}/bindings",
        json={
            "module_id": "r.warehouse",
            "key_id": created_item["key_id"],
            "key_alias": "default",
        },
    )
    assert bound.status_code == 201, bound.text
    binding_item = bound.json()["item"]
    assert binding_item["module_id"] == "r.warehouse"
    assert binding_item["key_alias"] == "keepa"
    assert binding_item["key_type"] == "keepa"
    assert binding_item["provider"] == "keepa"

    blocked_scope = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{target_org_id}/bindings",
        json={
            "module_id": "core.dashboard",
            "key_id": created_item["key_id"],
            "key_alias": "keepa",
        },
    )
    assert blocked_scope.status_code == 400
    assert blocked_scope.json()["detail"] == "api_key_scope_mismatch"

    with SessionLocal() as db:
        context = resolve_keepa_context_for_asin_ingestion(
            db,
            org_id=target_org_id,
        )
        assert context.module_id == "r.warehouse"
        assert context.key_alias == "keepa"
        assert context.adapter == "KeepaAdapter"
        assert context.provider == "keepa"
        assert context.auth_type == "api_key"
        assert context.token_check_url.endswith("/token?key=keepa-test-secret")

        provider_config = db.query(ProviderConfigRecord).filter(
            ProviderConfigRecord.org_id == target_org_id,
            ProviderConfigRecord.module_id == "r.warehouse",
            ProviderConfigRecord.provider == "keepa",
            ProviderConfigRecord.status == "active",
        ).one()
        assert provider_config.source_key_id == created_item["key_id"]
        assert provider_config.metadata_json["adapter"] == "KeepaAdapter"

    rw_status = owner_client.get("/api/app/rw/status")
    assert rw_status.status_code == 200, rw_status.text
    rw_payload = rw_status.json()
    assert rw_payload["keepa_key_bound"] is True
    assert rw_payload["ingestion_service_ready"] is True
    assert rw_payload["adapter"] == "KeepaAdapter"


def test_k_series_key_reevaluation_activates_target_org_runtime(
    owner_client: TestClient,
) -> None:
    target_org_id = DEFAULT_ORG_ID

    for alias in K_SERIES_PROVIDER_ALIASES:
        created = owner_client.post(
            "/api/control-plane/api-key-orchestration/organizations/"
            f"{DEFAULT_ORG_ID}/keys",
            json={
                "name": f"k-series-{alias}",
                "url": f"https://{alias}.example",
                "key_value": f"k-series-{alias}-secret-value",
            },
        )
        assert created.status_code == 201, created.text
        disabled = owner_client.patch(
            "/api/control-plane/api-key-orchestration/keys/"
            f"{created.json()['item']['key_id']}",
            json={"status": "disabled"},
        )
        assert disabled.status_code == 200, disabled.text

    with SessionLocal() as db:
        result = reevaluate_k_series_api_keys(
            db,
            actor_user_id="test_k_series_key_reevaluation",
        )
        db.commit()

    assert result["organization"] == K_SERIES_ORGANIZATION_NAME
    assert result["org_id"] == target_org_id
    assert result["required_aliases_available"] == {
        alias: True for alias in K_SERIES_PROVIDER_ALIASES
    }

    with SessionLocal() as db:
        keys = list(
            db.query(ApiKeyRecord).filter(ApiKeyRecord.org_id == target_org_id)
        )
        assert {key.metadata_json["key_alias"] for key in keys} == set(
            K_SERIES_PROVIDER_ALIASES
        )
        assert all(key.status == "active" for key in keys)
        assert all(
            key.metadata_json.get("runtime_state") == "enabled"
            for key in keys
        )
        bindings = list(
            db.query(ApiKeyModuleBindingRecord).filter(
                ApiKeyModuleBindingRecord.org_id == target_org_id,
                ApiKeyModuleBindingRecord.module_id == K_SERIES_MODULE_ID,
                ApiKeyModuleBindingRecord.status == "active",
            )
        )
        assert {binding.key_alias for binding in bindings} == set(
            K_SERIES_PROVIDER_ALIASES
        )
        provider_configs = list(
            db.query(ProviderConfigRecord).filter(
                ProviderConfigRecord.org_id == target_org_id,
                ProviderConfigRecord.module_id == K_SERIES_MODULE_ID,
                ProviderConfigRecord.status == "active",
            )
        )
        assert {config.provider for config in provider_configs} == {
            "serp",
            "chatgpt",
            "claude",
            "deepseek",
        }
