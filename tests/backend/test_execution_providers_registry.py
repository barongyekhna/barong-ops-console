import copy
import json
import re
from typing import Any, get_args

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from backend.app.core.execution_providers import EXECUTION_PROVIDER_CONTRACTS_V1
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.artifact import Artifact
from backend.app.models.job import AutomationJob
from backend.app.models.operation_log import OperationLog
from backend.app.models.user import User
from backend.app.schemas.execution_provider import (
    ExecutionActionType,
    ExecutionLifecycleStatus,
    ExecutionMode,
    ExecutionProviderContractV1,
    ExecutionProviderStatus,
    ExecutionProviderType,
    ExecutionRequestContractV1,
    ExecutionResultContractV1,
    ExecutionStateContractV1,
)
from backend.app.services.execution_provider_registry import (
    ALLOWED_ACTION_TYPES,
    ALLOWED_EXECUTION_MODES,
    ALLOWED_PROVIDER_STATUSES,
    ALLOWED_PROVIDER_TYPES,
    FUTURE_PROVIDER_TYPES,
    NON_EXECUTABLE_PROVIDER_STATUSES,
    PROVIDER_KEY_PATTERN,
    PROVIDER_VERSION_PATTERN,
    SENSITIVE_RUNTIME_VALUE_MARKERS,
    build_execution_provider_access_state,
    list_execution_provider_contracts,
    validate_execution_provider_contracts,
)
from backend.app.services.module_adapter_registry import list_adapter_contracts
from backend.app.services.module_registry import list_module_manifests
from backend.app.services.permission_service import (
    CurrentUserPermissionInfo,
    upsert_permission_registry,
    upsert_role_default_permission,
)

TEST_PASSWORD = "example-only-c09b-provider-password"


def create_execution_provider_user(
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


def provider_items_by_key(
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    return {
        str(item["provider_key"]): item
        for item in payload["items"]  # type: ignore[index]
    }


def raw_provider_by_key(provider_key: str) -> dict[str, Any]:
    return copy.deepcopy(
        next(
            raw
            for raw in EXECUTION_PROVIDER_CONTRACTS_V1
            if raw["provider_key"] == provider_key
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


def table_count(model: type[object]) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_execution_provider_registry_api_requires_login_and_owner_can_read(
    auth_client: TestClient,
) -> None:
    unauth_registry = auth_client.get("/api/control-plane/execution-providers/registry")
    unauth_me = auth_client.get("/api/control-plane/execution-providers/me")
    create_execution_provider_user(username="c09b_owner_api", role="owner")
    owner_token = login_token(auth_client, username="c09b_owner_api")

    registry = auth_client.get(
        "/api/control-plane/execution-providers/registry",
        headers=auth_headers(owner_token),
    )
    me = auth_client.get(
        "/api/control-plane/execution-providers/me",
        headers=auth_headers(owner_token),
    )

    assert unauth_registry.status_code == 401
    assert unauth_me.status_code == 401
    assert registry.status_code == 200
    assert me.status_code == 200
    registry_payload = registry.json()
    assert registry_payload["count"] == len(registry_payload["items"])
    assert {
        "core.no_op_provider",
        "core.mock_provider",
        "core.contract_only_provider",
        "future.local_backend_provider",
        "future.queue_provider",
        "future.webhook_provider",
        "future.scheduled_provider",
        "future.live_provider",
    } == {item["provider_key"] for item in registry_payload["items"]}
    assert me.json()["is_owner_full_access"] is True

    serialized = json.dumps(registry_payload, sort_keys=True).lower()
    for fragment in [
        "password",
        "authorization",
        "bearer ",
        "http://",
        "https://",
        ".env",
        "provider_url",
        "webhook_url",
        "credential=",
        "token=",
    ]:
        assert fragment not in serialized


def test_static_execution_provider_registry_contract_rules() -> None:
    providers = validate_execution_provider_contracts()
    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    adapters = {adapter.adapter_key: adapter for adapter in list_adapter_contracts()}
    required_contract_fields = set(ExecutionProviderContractV1.model_fields)

    provider_keys = [provider.provider_key for provider in providers]
    assert len(provider_keys) == len(set(provider_keys))
    assert set(provider_keys) == {
        "k.product_knowledge.prompt.provider",
        "k.product_knowledge.serp.provider",
        "k.product_knowledge.ai_enrich.provider",
        "k.product_knowledge.risk_filter.provider",
        "core.no_op_provider",
        "core.mock_provider",
        "core.contract_only_provider",
        "future.local_backend_provider",
        "future.queue_provider",
        "future.webhook_provider",
        "future.scheduled_provider",
        "future.live_provider",
    }
    assert set(ALLOWED_PROVIDER_TYPES) == set(get_args(ExecutionProviderType))
    assert set(ALLOWED_PROVIDER_STATUSES) == set(get_args(ExecutionProviderStatus))
    assert set(ALLOWED_EXECUTION_MODES) == set(get_args(ExecutionMode))
    assert set(ALLOWED_ACTION_TYPES) == set(get_args(ExecutionActionType))

    for provider in providers:
        raw_provider = next(
            raw
            for raw in EXECUTION_PROVIDER_CONTRACTS_V1
            if raw["provider_key"] == provider.provider_key
        )
        assert required_contract_fields.issubset(set(raw_provider))
        assert PROVIDER_KEY_PATTERN.fullmatch(provider.provider_key)
        assert PROVIDER_VERSION_PATTERN.fullmatch(provider.provider_version)
        assert provider.provider_type in ALLOWED_PROVIDER_TYPES
        assert provider.provider_status in ALLOWED_PROVIDER_STATUSES
        assert provider.lifecycle in ALLOWED_PROVIDER_STATUSES
        assert set(provider.supported_execution_modes).issubset(
            ALLOWED_EXECUTION_MODES
        )
        assert set(provider.supported_action_types).issubset(ALLOWED_ACTION_TYPES)
        assert provider.module_key in module_keys
        assert provider.adapter_key in adapters
        assert adapters[provider.adapter_key].module_key == provider.module_key

        action_contract = next(
            contract
            for contract in adapters[provider.adapter_key].action_contracts
            if contract.action_key == provider.action_key
        )
        assert provider.required_permissions == [
            action_contract.required_permission
        ]
        assert provider.risk_level == action_contract.risk_level
        assert provider.operation_log_action == action_contract.operation_log_action
        assert (
            provider.operation_log_policy.operation_log_action
            == action_contract.operation_log_action
        )
        assert provider.requires_execution_provider == (
            action_contract.requires_execution_provider
        )
        assert provider.requires_approval == (
            action_contract.requires_approval
            or action_contract.risk_level in {"high", "critical"}
        )
        assert provider.executable is False
        if provider.can_request_execution:
            assert provider.provider_type in {
                "no_op_provider",
                "queue_provider",
                "webhook_provider",
            }
        assert provider.live_provider_connected is False
        assert provider.external_endpoint_declared is False
        assert provider.credential_declared is False
        assert provider.callback_policy.callback_supported is False
        assert provider.callback_policy.callback_connected_in_c09b is False
        assert provider.callback_policy.external_endpoint_declared is False
        assert provider.operation_log_policy.writes_operation_logs_in_c09b is False
        assert provider.audit_event_policy.writes_audit_events_in_c09b is False
        assert provider.artifact_policy.writes_artifacts_in_c09b is False
        assert provider.artifact_policy.local_path_allowed is False
        assert provider.artifact_policy.external_reference_allowed is False

        if provider.provider_type in FUTURE_PROVIDER_TYPES:
            assert provider.provider_status in {
                "provider_pending",
                "provider_unavailable",
                "staging_ready",
                "live_ready",
                "disabled",
                "deprecated",
                "draft",
            }
        if provider.provider_status in NON_EXECUTABLE_PROVIDER_STATUSES:
            assert provider.executable is False
            assert provider.can_request_execution is False
        if action_contract.requires_approval:
            assert provider.approval_requirement.blocks_execution_in_c09b is True
            assert provider.executable is False
        if action_contract.requires_execution_provider:
            assert provider.executable is False
            if provider.can_request_execution:
                assert provider.provider_type in {
                    "no_op_provider",
                    "queue_provider",
                    "webhook_provider",
                }
            assert (
                provider.provider_type == "no_op_provider"
                or provider.provider_type in {"queue_provider", "webhook_provider"}
                or provider.provider_status
                in {
                    "provider_pending",
                    "provider_unavailable",
                    "staging_ready",
                    "live_ready",
                    "disabled",
                }
            )
        if provider.secret_requirement.requires_secret:
            assert provider.secret_requirement.secret_value_declared is False
            assert provider.secret_requirement.provider_credential_declared is False
            assert provider.secret_requirement.secret_read_allowed is False
            assert provider.secret_requirement.rules_provider_state == "waiting_c14"

        json.dumps(provider.execution_request_schema.model_dump(mode="json"))
        json.dumps(provider.execution_result_schema.model_dump(mode="json"))
        json.dumps(provider.execution_state_schema.model_dump(mode="json"))


def test_c09d_execution_provider_rule_matrix_is_explicitly_no_execute() -> None:
    providers = {
        provider.provider_key: provider
        for provider in list_execution_provider_contracts()
    }
    expected_access = {
        "core.no_op_provider": (
            "visible",
            "router_selection_required",
            "execution_router_required",
        ),
        "core.mock_provider": (
            "blocked",
            "scope_adapter_pending",
            "waiting_c18_scope_adapter",
        ),
        "core.contract_only_provider": (
            "blocked",
            "blocked_approval_required",
            "waiting_c12_approval_gate",
        ),
        "future.local_backend_provider": (
            "visible",
            "router_selection_required",
            "execution_router_required",
        ),
        "future.queue_provider": (
            "visible",
            "router_selection_required",
            "execution_router_required",
        ),
        "future.webhook_provider": (
            "visible",
            "router_selection_required",
            "execution_router_required",
        ),
        "future.scheduled_provider": (
            "blocked",
            "blocked_approval_required",
            "waiting_c12_approval_gate",
        ),
        "future.live_provider": (
            "unavailable",
            "secret_rules_required",
            "waiting_c14_secret_rules",
        ),
        "k.product_knowledge.prompt.provider": (
            "blocked",
            "secret_rules_required",
            "waiting_c14_secret_rules",
        ),
        "k.product_knowledge.serp.provider": (
            "blocked",
            "secret_rules_required",
            "waiting_c14_secret_rules",
        ),
        "k.product_knowledge.ai_enrich.provider": (
            "blocked",
            "secret_rules_required",
            "waiting_c14_secret_rules",
        ),
        "k.product_knowledge.risk_filter.provider": (
            "blocked",
            "blocked_approval_required",
            "waiting_c12_approval_gate",
        ),
    }

    assert set(providers) == set(expected_access)

    for provider_key, (
        provider_access_state,
        block_reason,
        no_execute_reason,
    ) in expected_access.items():
        provider = providers[provider_key]
        access = build_execution_provider_access_state(
            provider,
            owner_permission_info(),
        )

        assert access.provider_access_state == provider_access_state
        assert access.block_reason == block_reason
        assert access.no_execute_reason == no_execute_reason
        assert access.blocked is (provider_key != "future.local_backend_provider")
        assert access.executable is False
        assert access.can_request_execution is False
        assert access.safe_status_message
        assert access.required_permission == provider.required_permissions[0]
        assert access.risk_level == provider.risk_level
        assert access.operation_log_action == provider.operation_log_action

    no_op = providers["core.no_op_provider"]
    assert no_op.requires_execution_provider is True
    assert no_op.approval_requirement.requires_approval is False
    assert no_op.secret_requirement.requires_secret is False
    assert no_op.scope_requirement.requires_scope is False

    approval = providers["core.contract_only_provider"]
    assert approval.requires_approval is True
    assert approval.approval_requirement.requires_approval is True
    assert approval.approval_requirement.approval_status == (
        "blocked_approval_required"
    )
    assert approval.approval_requirement.approval_provider_state == "waiting_c12"
    assert approval.approval_requirement.blocks_execution_in_c09b is True

    secret = providers["future.live_provider"]
    assert secret.secret_requirement.requires_secret is True
    assert secret.secret_requirement.secret_binding_status == (
        "secret_rules_required"
    )
    assert secret.secret_requirement.rules_provider_state == "waiting_c14"
    assert secret.secret_requirement.blocks_execution_in_c09b is True
    assert secret.secret_requirement.secret_value_declared is False
    assert secret.secret_requirement.provider_credential_declared is False
    assert secret.secret_requirement.secret_read_allowed is False
    assert secret.credential_declared is False

    scope = providers["core.mock_provider"]
    assert scope.scope_requirement.requires_scope is True
    assert scope.scope_requirement.scope_status == "scope_adapter_pending"
    assert scope.scope_requirement.allowed_scope_types == ["global", "module"]
    assert scope.scope_requirement.requires_c18_scope_adapter is True
    assert scope.scope_requirement.blocks_execution_in_c09b is True

    for provider in providers.values():
        assert provider.fallback_behavior.permission_missing == "blocked_permission"
        assert provider.fallback_behavior.approval_missing == (
            "blocked_approval_required_waiting_c12"
        )
        assert provider.fallback_behavior.secret_missing == (
            "secret_rules_required_waiting_c14"
        )
        assert provider.fallback_behavior.scope_missing == (
            "scope_adapter_pending_waiting_c18"
        )
        assert provider.idempotency_policy.enabled_in_c09b is False
        assert provider.retry_policy.enabled_in_c09b is False
        assert provider.timeout_policy.enabled_in_c09b is False
        assert provider.cancellation_policy.enabled_in_c09b is False
        assert provider.concurrency_policy.enabled_in_c09b is False
        assert provider.rate_limit_policy.enabled_in_c09b is False
        assert provider.operation_log_policy.write_policy == "declared_only"
        assert provider.operation_log_policy.writes_operation_logs_in_c09b is False
        assert provider.audit_event_policy.writes_audit_events_in_c09b is False


def test_execution_provider_contract_rejects_invalid_shapes_and_drifts() -> None:
    valid = raw_provider_by_key("core.no_op_provider")

    with pytest.raises(ValueError, match="Duplicate provider_key"):
        validate_execution_provider_contracts([valid, copy.deepcopy(valid)])

    for bad_key in [
        "Core.NoOp.Provider",
        "core-no-op-provider",
        "core",
    ]:
        invalid = copy.deepcopy(valid)
        invalid["provider_key"] = bad_key
        with pytest.raises(ValueError):
            validate_execution_provider_contracts([invalid])

    invalid_version = copy.deepcopy(valid)
    invalid_version["provider_version"] = "v1"
    with pytest.raises(ValueError, match="provider_version"):
        validate_execution_provider_contracts([invalid_version])

    invalid_type = copy.deepcopy(valid)
    invalid_type["provider_type"] = "live_provider"
    with pytest.raises(Exception):
        validate_execution_provider_contracts([invalid_type])

    invalid_status = copy.deepcopy(valid)
    invalid_status["provider_status"] = "available"
    with pytest.raises(Exception):
        validate_execution_provider_contracts([invalid_status])

    invalid_module = copy.deepcopy(valid)
    invalid_module["module_key"] = "business.missing"
    with pytest.raises(ValueError, match="module_key is not registered"):
        validate_execution_provider_contracts([invalid_module])

    invalid_adapter = copy.deepcopy(valid)
    invalid_adapter["adapter_key"] = "business.missing.adapter"
    with pytest.raises(ValueError, match="adapter_key is not registered"):
        validate_execution_provider_contracts([invalid_adapter])

    invalid_action = copy.deepcopy(valid)
    invalid_action["action_key"] = "k.product_knowledge.missing"
    with pytest.raises(ValueError, match="action_key is not in C08"):
        validate_execution_provider_contracts([invalid_action])

    permission_drift = copy.deepcopy(valid)
    permission_drift["required_permissions"] = ["artifacts.read"]
    with pytest.raises(ValueError, match="required_permission"):
        validate_execution_provider_contracts([permission_drift])

    risk_drift = copy.deepcopy(valid)
    risk_drift["risk_level"] = "low"
    with pytest.raises(ValueError, match="risk_level"):
        validate_execution_provider_contracts([risk_drift])

    log_drift = copy.deepcopy(valid)
    log_drift["operation_log_action"] = "k.product_knowledge.other"
    with pytest.raises(ValueError, match="operation_log_action"):
        validate_execution_provider_contracts([log_drift])

    approval_executable = raw_provider_by_key("core.contract_only_provider")
    approval_executable["executable"] = True
    with pytest.raises(ValueError, match="approval action is executable"):
        validate_execution_provider_contracts([approval_executable])

    execution_executable = raw_provider_by_key("future.live_provider")
    execution_executable["can_request_execution"] = True
    with pytest.raises(ValueError, match="live_ready cannot request execution"):
        validate_execution_provider_contracts([execution_executable])

    future_enabled = raw_provider_by_key("future.queue_provider")
    future_enabled["provider_status"] = "contract_ready"
    future_enabled["lifecycle"] = "contract_ready"
    with pytest.raises(ValueError, match="contract_ready can execute"):
        validate_execution_provider_contracts([future_enabled])

    secret_value = raw_provider_by_key("future.live_provider")
    secret_value["secret_requirement"]["secret_value_declared"] = True
    with pytest.raises(ValueError, match="secret value"):
        validate_execution_provider_contracts([secret_value])

    unsafe_value = copy.deepcopy(valid)
    unsafe_value["description"] = "http://example.invalid/provider"
    with pytest.raises(ValueError, match="unsafe runtime value"):
        validate_execution_provider_contracts([unsafe_value])


def test_c09d_contract_rejects_permission_approval_secret_and_live_regressions() -> None:
    invalid_permission = raw_provider_by_key("core.no_op_provider")
    invalid_permission["required_permissions"] = ["*"]
    with pytest.raises(ValueError, match="Permission key"):
        validate_execution_provider_contracts([invalid_permission])

    operation_policy_drift = raw_provider_by_key("core.no_op_provider")
    operation_policy_drift["operation_log_policy"]["operation_log_action"] = (
        "k.product_knowledge.placeholder.drift"
    )
    with pytest.raises(ValueError, match="operation_log_policy"):
        validate_execution_provider_contracts([operation_policy_drift])

    approval_not_blocking = raw_provider_by_key("core.contract_only_provider")
    approval_not_blocking["approval_requirement"][
        "blocks_execution_in_c09b"
    ] = False
    with pytest.raises(ValueError, match="approval policy"):
        validate_execution_provider_contracts([approval_not_blocking])

    high_risk_missing_approval = raw_provider_by_key("future.scheduled_provider")
    high_risk_missing_approval["requires_approval"] = False
    high_risk_missing_approval["approval_requirement"]["requires_approval"] = False
    high_risk_missing_approval["approval_requirement"][
        "blocks_execution_in_c09b"
    ] = False
    high_risk_missing_approval["approval_requirement"]["approval_status"] = (
        "not_required"
    )
    with pytest.raises(ValueError, match="approval requirement"):
        validate_execution_provider_contracts([high_risk_missing_approval])

    secret_not_waiting = raw_provider_by_key("future.live_provider")
    secret_not_waiting["secret_requirement"]["rules_provider_state"] = (
        "not_required"
    )
    with pytest.raises(ValueError, match="wait for C14"):
        validate_execution_provider_contracts([secret_not_waiting])

    secret_not_blocking = raw_provider_by_key("future.live_provider")
    secret_not_blocking["secret_requirement"]["blocks_execution_in_c09b"] = False
    with pytest.raises(ValueError, match="block C09B"):
        validate_execution_provider_contracts([secret_not_blocking])

    live_connected = raw_provider_by_key("core.no_op_provider")
    live_connected["live_provider_connected"] = True
    with pytest.raises(ValueError, match="live connected"):
        validate_execution_provider_contracts([live_connected])

    external_endpoint = raw_provider_by_key("core.no_op_provider")
    external_endpoint["external_endpoint_declared"] = True
    with pytest.raises(ValueError, match="external endpoint"):
        validate_execution_provider_contracts([external_endpoint])

    callback_connected = raw_provider_by_key("core.no_op_provider")
    callback_connected["callback_policy"]["callback_supported"] = True
    with pytest.raises(ValueError, match="callback support"):
        validate_execution_provider_contracts([callback_connected])

    artifact_path = raw_provider_by_key("core.no_op_provider")
    artifact_path["artifact_policy"]["local_path_allowed"] = True
    with pytest.raises(ValueError, match="local artifact path"):
        validate_execution_provider_contracts([artifact_path])

    operation_log_write = raw_provider_by_key("core.no_op_provider")
    operation_log_write["operation_log_policy"][
        "writes_operation_logs_in_c09b"
    ] = True
    with pytest.raises(ValueError, match="writes operation logs"):
        validate_execution_provider_contracts([operation_log_write])


def test_execution_request_result_state_contract_schemas_are_declared() -> None:
    request_fields = set(ExecutionRequestContractV1.model_fields)
    result_fields = set(ExecutionResultContractV1.model_fields)
    state_fields = set(ExecutionStateContractV1.model_fields)
    lifecycle_values = set(get_args(ExecutionLifecycleStatus))

    assert {
        "execution_id",
        "request_id",
        "idempotency_key",
        "module_key",
        "adapter_key",
        "action_key",
        "actor_user_id",
        "target_scope",
        "input_payload",
        "sanitized_input_summary",
        "provider_key",
        "provider_type",
        "status",
        "risk_level",
        "required_permission",
        "approval_status",
        "secret_binding_status",
        "created_at",
        "accepted_at",
        "started_at",
        "finished_at",
        "cancelled_at",
        "timeout_at",
        "result_summary",
        "artifact_refs",
        "error_code",
        "error_message_safe",
        "operation_log_id",
    }.issubset(request_fields)
    assert {
        "execution_id",
        "provider_key",
        "status",
        "result_summary",
        "artifact_refs",
        "error_code",
        "error_message_safe",
        "operation_log_id",
    }.issubset(result_fields)
    assert {
        "draft",
        "requested",
        "blocked_permission",
        "blocked_approval_required",
        "blocked_provider_unavailable",
        "accepted",
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
        "retry_scheduled",
        "skipped",
        "rejected",
        "archived",
    }.issubset(lifecycle_values)
    assert {
        "current_status",
        "allowed_statuses",
        "blocked_statuses",
        "terminal_statuses",
        "transition_policy",
        "executable_in_c09b",
    }.issubset(state_fields)

    for provider in list_execution_provider_contracts():
        assert set(provider.execution_request_schema.fields).issubset(
            request_fields
        )
        assert set(provider.execution_result_schema.fields).issubset(
            result_fields
        )
        assert set(provider.execution_state_schema.fields).issubset(state_fields)
        assert provider.execution_state_schema.persistence_policy == (
            "contract_only_no_persistence"
        )


def test_execution_provider_access_states_are_safe_for_owner_and_non_owner(
    auth_client: TestClient,
) -> None:
    create_execution_provider_user(username="c09b_owner_access", role="owner")
    create_execution_provider_user(username="c09b_viewer_access", role="viewer")
    owner_token = login_token(auth_client, username="c09b_owner_access")
    viewer_token = login_token(auth_client, username="c09b_viewer_access")

    owner_response = auth_client.get(
        "/api/control-plane/execution-providers/me",
        headers=auth_headers(owner_token),
    )
    viewer_response = auth_client.get(
        "/api/control-plane/execution-providers/me",
        headers=auth_headers(viewer_token),
    )

    assert owner_response.status_code == 200
    assert viewer_response.status_code == 200
    owner_items = provider_items_by_key(owner_response.json())
    viewer_items = provider_items_by_key(viewer_response.json())

    assert owner_items["core.mock_provider"]["visible"] is True
    assert owner_items["core.mock_provider"]["block_reason"] == (
        "scope_adapter_pending"
    )
    assert owner_items["core.mock_provider"]["scope_status"] == (
        "scope_adapter_pending"
    )
    assert owner_items["core.contract_only_provider"]["visible"] is True
    assert owner_items["core.contract_only_provider"]["requires_approval"] is True
    assert owner_items["core.contract_only_provider"]["approval_status"] == (
        "blocked_approval_required"
    )
    assert owner_items["core.contract_only_provider"]["block_reason"] == (
        "blocked_approval_required"
    )
    assert owner_items["future.live_provider"]["requires_secret"] is True
    assert owner_items["future.live_provider"]["secret_binding_status"] == (
        "secret_rules_required"
    )
    assert owner_items["future.live_provider"]["block_reason"] == (
        "secret_rules_required"
    )
    assert owner_items["core.no_op_provider"]["block_reason"] == (
        "execution_provider_required"
    )
    assert owner_items["future.queue_provider"]["provider_access_state"] == (
        "provider_pending"
    )
    assert owner_items["future.webhook_provider"]["provider_access_state"] == (
        "disabled"
    )

    for item in owner_items.values():
        assert item["executable"] is False
        assert item["can_request_execution"] is False

    assert viewer_items["core.mock_provider"]["hidden"] is True
    assert viewer_items["core.mock_provider"]["provider_access_state"] == "hidden"
    assert viewer_items["core.contract_only_provider"]["hidden"] is True
    assert viewer_items["core.contract_only_provider"]["provider_access_state"] == (
        "hidden"
    )
    assert viewer_items["future.local_backend_provider"]["hidden"] is True
    assert viewer_items["core.no_op_provider"]["visible"] is True
    assert viewer_items["core.no_op_provider"]["locked"] is True
    assert viewer_items["core.no_op_provider"]["provider_access_state"] == "locked"
    assert "products.read" in viewer_items["core.no_op_provider"][
        "missing_permissions"
    ]


def test_role_defaults_viewer_locked_super_admin_sees_provider_metadata_without_execution(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    create_execution_provider_user(
        username="c09b_viewer_role_default",
        role="viewer",
    )
    create_execution_provider_user(
        username="c09b_super_admin_default",
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
        username="c09b_viewer_role_default",
    )
    super_admin_token = login_token(
        auth_client,
        username="c09b_super_admin_default",
    )

    viewer_response = auth_client.get(
        "/api/control-plane/execution-providers/me",
        headers=auth_headers(viewer_token),
    )
    super_admin_response = auth_client.get(
        "/api/control-plane/execution-providers/me",
        headers=auth_headers(super_admin_token),
    )

    assert viewer_response.status_code == 200
    assert super_admin_response.status_code == 200
    viewer_items = provider_items_by_key(viewer_response.json())
    super_admin_items = provider_items_by_key(super_admin_response.json())
    assert viewer_items["core.no_op_provider"]["provider_access_state"] == (
        "locked"
    )
    assert "products.read" in viewer_items["core.no_op_provider"][
        "missing_permissions"
    ]
    assert viewer_items["future.live_provider"]["provider_access_state"] == (
        "hidden"
    )
    assert super_admin_items["core.contract_only_provider"]["visible"] is True
    assert super_admin_items["core.contract_only_provider"]["hidden"] is False
    assert super_admin_items["core.contract_only_provider"][
        "provider_access_state"
    ] in {"blocked", "unavailable"}
    assert super_admin_items["core.contract_only_provider"][
        "can_request_execution"
    ] is False
    assert super_admin_items["future.local_backend_provider"]["visible"] is True
    assert super_admin_items["future.local_backend_provider"]["hidden"] is False
    assert super_admin_items["future.local_backend_provider"][
        "provider_access_state"
    ] != "hidden"
    assert super_admin_items["future.local_backend_provider"][
        "can_request_execution"
    ] is False

    contract_only = next(
        provider
        for provider in list_execution_provider_contracts()
        if provider.provider_key == "core.contract_only_provider"
    )
    access = build_execution_provider_access_state(
        contract_only,
        owner_permission_info(),
    )
    assert access.visible is True
    assert access.executable is False
    assert access.can_request_execution is False
    assert access.block_reason == "blocked_approval_required"
    assert access.no_execute_reason == "waiting_c12_approval_gate"


def test_execution_provider_router_exposes_only_read_contract_apis(
    auth_client: TestClient,
) -> None:
    provider_routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in auth_client.app.routes
        if str(getattr(route, "path", "")).startswith("/api/control-plane/execution-providers")
    ]

    assert ("/api/control-plane/execution-providers/registry", {"GET"}) in provider_routes
    assert ("/api/control-plane/execution-providers/me", {"GET"}) in provider_routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in provider_routes
    )
    assert not any(
        re.search(
            r"/(?:actions?|execute|execution|run|submit)\b",
            str(path).removeprefix("/api/control-plane/execution-providers"),
        )
        for path, _ in provider_routes
    )

    for path in [
        "/api/control-plane/execution-providers/registry",
        "/api/control-plane/execution-providers/me",
        "/api/control-plane/execution-providers/run",
        "/api/control-plane/execution-providers/execute",
        "/api/control-plane/execution-providers/core.no_op_provider/run",
        "/executions",
    ]:
        response = auth_client.post(path, json={"blocked": True})
        assert response.status_code in {404, 405}


def test_execution_provider_read_only_calls_do_not_write_logs_tasks_or_artifacts(
    auth_client: TestClient,
) -> None:
    create_execution_provider_user(username="c09b_owner_no_writes", role="owner")
    owner_token = login_token(auth_client, username="c09b_owner_no_writes")
    headers = auth_headers(owner_token)
    before_logs = table_count(OperationLog)
    before_jobs = table_count(AutomationJob)
    before_artifacts = table_count(Artifact)

    registry = auth_client.get("/api/control-plane/execution-providers/registry", headers=headers)
    me = auth_client.get("/api/control-plane/execution-providers/me", headers=headers)

    assert registry.status_code == 200
    assert me.status_code == 200
    assert table_count(OperationLog) == before_logs
    assert table_count(AutomationJob) == before_jobs
    assert table_count(Artifact) == before_artifacts


def test_c09b_regressions_c08_c07_c05_c06_users_and_register(
    auth_client: TestClient,
) -> None:
    seed_permission_registry()
    owner_id = create_execution_provider_user(
        username="c09b_owner_regression",
        role="owner",
    )
    viewer_id = create_execution_provider_user(
        username="c09b_viewer_regression",
        role="viewer",
    )
    owner_token = login_token(auth_client, username="c09b_owner_regression")
    viewer_token = login_token(auth_client, username="c09b_viewer_regression")
    owner_headers = auth_headers(owner_token)
    viewer_headers = auth_headers(viewer_token)

    assert auth_client.get(
        "/api/control-plane/module-adapters/registry",
        headers=owner_headers,
    ).status_code == 200
    assert auth_client.get(
        "/api/control-plane/module-adapters/me",
        headers=viewer_headers,
    ).status_code == 200
    assert auth_client.get(
        "/api/control-plane/modules/registry",
        headers=owner_headers,
    ).status_code == 200
    assert auth_client.get(
        "/api/control-plane/modules/me",
        headers=viewer_headers,
    ).status_code == 200

    permissions_me_before = auth_client.get(
        "/api/app/permissions/me",
        headers=viewer_headers,
    )
    grant_response = auth_client.post(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=owner_headers,
        json={"permission_key": "artifacts.read", "reason": "C09B regression."},
    )
    assignments_response = auth_client.get(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=owner_headers,
    )
    permissions_me_after = auth_client.get(
        "/api/app/permissions/me",
        headers=viewer_headers,
    )
    viewer_users = auth_client.get("/api/app/users", headers=viewer_headers)
    missing_register = auth_client.post(
        "/api/public/auth/register",
        json={"username": "blocked", "password": "blocked"},
    )

    assert permissions_me_before.status_code == 200
    assert permissions_me_before.json()["permissions"]["permission_keys"] == []
    assert grant_response.status_code == 201
    assert assignments_response.status_code == 200
    assert assignments_response.json()["user_id"] == viewer_id
    assert permissions_me_after.status_code == 200
    assert "artifacts.read" in permissions_me_after.json()["permissions"][
        "permission_keys"
    ]
    assert viewer_users.status_code == 403
    assert missing_register.status_code == 404
    assert owner_id != viewer_id


def test_execution_provider_registry_does_not_expose_runtime_values() -> None:
    providers = list_execution_provider_contracts()
    serialized = json.dumps(
        [provider.model_dump(mode="json") for provider in providers],
        sort_keys=True,
    ).lower()
    for fragment in [
        ".env.production",
        ".env.staging",
        "auth_token_secret",
        "owner_password",
        "postgres_password",
        "provider_url",
        "webhook_url",
        "webhook_secret",
        "bearer ",
        "authorization",
        "http://",
        "https://",
        "ops.barongyekhna.com",
        "console_postgres",
        "production_url",
        "staging_url",
    ]:
        assert fragment not in serialized

    for value in string_values(
        [provider.model_dump(mode="json") for provider in providers]
    ):
        lowered = value.lower()
        for marker in SENSITIVE_RUNTIME_VALUE_MARKERS:
            assert marker not in lowered
        assert "api_key" not in lowered

    assert all(provider.executable is False for provider in providers)
    assert all(
        build_execution_provider_access_state(
            provider,
            owner_permission_info(),
        ).can_request_execution
        is False
        for provider in providers
    )
