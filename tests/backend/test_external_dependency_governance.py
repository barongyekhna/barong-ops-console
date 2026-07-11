from __future__ import annotations

import copy
import json
from typing import Any, get_args

from fastapi.testclient import TestClient
import pytest

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.schemas.execution_provider import ExecutionRequestContractV1
from backend.app.schemas.external_dependency import (
    ExternalPolicyDecisionValue,
    ExternalService,
    ExternalServiceStatus,
    ExternalServiceType,
    ExternalTrustLevel,
)
from backend.app.services.external_dependency_governance import (
    ALLOWED_EXTERNAL_SERVICE_STATUSES,
    ALLOWED_EXTERNAL_SERVICE_TYPES,
    ALLOWED_EXTERNAL_TRUST_LEVELS,
    C14D_GATE,
    EXTERNAL_SERVICE_ID_PATTERN,
    ExternalDependencyGateBlockedError,
    SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS,
    build_dependency_binding_decisions,
    build_registration_proposal,
    decide_external_dependency_policy,
    evaluate_external_service_trust,
    list_external_services,
    list_registration_proposals,
    validate_external_dependency_policies,
    validate_external_service_registry,
)

TEST_PASSWORD = "example-only-c14d-external-dependency-password"


def create_external_dependency_user(
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


def registered_service(**updates: Any) -> dict[str, Any]:
    service = {
        "service_id": "dynamic.ai_service",
        "service_type": "ai_api",
        "status": "active",
        "trust_level": "high",
        "metadata": {
            "registration_source": "c14d_contract_test",
            "owner_module": "k.product_knowledge",
        },
    }
    service.update(updates)
    return service


def allow_policy(**updates: Any) -> dict[str, Any]:
    policy = {
        "policy_id": "k.product_knowledge.dynamic_ai.allow",
        "description": "Allow a dynamically registered AI service for one action.",
        "module": "k.product_knowledge",
        "action": "k.product_knowledge.placeholder.prepare",
        "service_id": "dynamic.ai_service",
        "service_type": None,
        "min_trust_level": "medium",
        "decision": "allow",
        "requires_c12_approval": False,
        "enabled": True,
    }
    policy.update(updates)
    return policy


def no_op_request() -> ExecutionRequestContractV1:
    # admin.users declares no external dependency, so the C14D gate must
    # allow this request without consulting the service registry.
    return ExecutionRequestContractV1(
        execution_id="exec_c14d_no_external",
        request_id="req_c14d_no_external",
        module_key="admin.users",
        adapter_key="admin.users.adapter",
        action_key="admin.users.read",
        actor_user_id=1001,
        provider_key="core.mock_provider",
        provider_type="mock_provider",
        status="requested",
        risk_level="medium",
        required_permission="users.read",
    )


def n8n_request() -> ExecutionRequestContractV1:
    data = {
        "execution_id": "exec_c14d_unknown_external",
        "request_id": "req_c14d_unknown_external",
        "module_key": "integration.n8n_test_bridge",
        "adapter_key": "integration.n8n_test_bridge.adapter",
        "action_key": "integration.n8n_test_bridge.test_run.declare",
        "actor_user_id": 1001,
        "target_scope": {},
        "input_payload": {},
        "sanitized_input_summary": {},
        "provider_key": "future.live_provider",
        "provider_type": "future_live_provider",
        "status": "requested",
        "risk_level": "medium",
        "required_permission": "modules.read",
        "approval_status": "not_required",
        "secret_binding_status": "not_required",
        "artifact_refs": [],
    }
    return ExecutionRequestContractV1.model_construct(**data)


def test_c14d_read_only_registry_api_requires_login(
    auth_client: TestClient,
) -> None:
    unauth_registry = auth_client.get("/api/control-plane/external-dependencies/registry")
    unauth_proposals = auth_client.get("/api/control-plane/external-dependencies/proposals")
    unauth_bindings = auth_client.get("/api/control-plane/external-dependencies/bindings")
    create_external_dependency_user(username="c14d_owner_api", role="owner")
    owner_token = login_token(auth_client, username="c14d_owner_api")

    registry = auth_client.get(
        "/api/control-plane/external-dependencies/registry",
        headers=auth_headers(owner_token),
    )
    proposals = auth_client.get(
        "/api/control-plane/external-dependencies/proposals",
        headers=auth_headers(owner_token),
    )
    bindings = auth_client.get(
        "/api/control-plane/external-dependencies/bindings",
        headers=auth_headers(owner_token),
    )

    assert unauth_registry.status_code == 401
    assert unauth_proposals.status_code == 401
    assert unauth_bindings.status_code == 401
    assert registry.status_code == 200
    assert proposals.status_code == 200
    assert bindings.status_code == 200
    assert registry.json()["items"] == []
    assert proposals.json()["count"] >= 1
    assert bindings.json()["count"] >= 1

    serialized = json.dumps(
        {
            "registry": registry.json(),
            "proposals": proposals.json(),
            "bindings": bindings.json(),
        },
        sort_keys=True,
    ).lower()
    for marker in SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS:
        if marker == "secret":
            continue
        assert marker not in serialized


def test_c14d_external_service_registry_lists_declared_services_only() -> None:
    # Since 2026-06 the registry deliberately seeds the declared production
    # services; every entry must validate and stay within the declared set.
    services = list_external_services()
    assert {service.service_id for service in services} == {
        "serp",
        "deepseek",
        "chatgpt",
        "claude_opus",
        "ai_provider",
        "n8n",
        "woocommerce",
        "keepa",
        "alibaba1688",
        "rainforest",
        "serper",
        "google_ads",
        "chat_record_store",
        "chat_asset_store",
    }
    assert all(service.status == "active" for service in services)
    assert set(ALLOWED_EXTERNAL_SERVICE_TYPES) == set(get_args(ExternalServiceType))
    assert set(ALLOWED_EXTERNAL_SERVICE_STATUSES) == set(
        get_args(ExternalServiceStatus)
    )
    assert set(ALLOWED_EXTERNAL_TRUST_LEVELS) == set(get_args(ExternalTrustLevel))

    dynamic_services = validate_external_service_registry(
        [
            registered_service(service_id="dynamic.ai_service"),
            registered_service(
                service_id="new.payment_gateway",
                service_type="payment",
                status="pending",
                trust_level="low",
            ),
        ]
    )
    assert {service.service_id for service in dynamic_services} == {
        "dynamic.ai_service",
        "new.payment_gateway",
    }
    assert all(
        EXTERNAL_SERVICE_ID_PATTERN.fullmatch(service.service_id)
        for service in dynamic_services
    )

    duplicate = registered_service()
    with pytest.raises(ValueError, match="Duplicate external service_id"):
        validate_external_service_registry([duplicate, copy.deepcopy(duplicate)])

    unsafe = registered_service(service_id="https://provider.example")
    with pytest.raises(ValueError, match="service id"):
        validate_external_service_registry([unsafe])

    secret_metadata = registered_service(metadata={"token": "example-only"})
    with pytest.raises(ValueError, match="sensitive runtime data"):
        validate_external_service_registry([secret_metadata])


def test_c14d_trust_evaluation_uses_history_risk_violations_and_approvals() -> None:
    trusted = ExternalService.model_validate(registered_service())
    degraded = ExternalService.model_validate(
        registered_service(status="pending", trust_level="low")
    )

    trusted_eval = evaluate_external_service_trust(
        trusted,
        context={
            "risk_level": "low",
            "module_sensitivity": "low",
            "total_calls": 20,
            "successful_calls": 20,
            "approval_requests": 3,
            "approved_requests": 3,
            "past_violations": 0,
        },
    )
    degraded_eval = evaluate_external_service_trust(
        degraded,
        context={
            "risk_level": "critical",
            "module_sensitivity": "critical",
            "total_calls": 10,
            "successful_calls": 2,
            "approval_requests": 5,
            "approved_requests": 1,
            "approval_rejections": 3,
            "past_violations": 2,
        },
    )

    assert trusted_eval.dynamic_trust_score > degraded_eval.dynamic_trust_score
    assert trusted_eval.access_recommendation in {"allow", "restrict"}
    assert degraded_eval.access_recommendation in {"restrict", "quarantine"}
    assert trusted_eval.factors["usage_history"]["successful_calls"] == 20
    assert degraded_eval.factors["past_violations"] == 2


def test_c14d_policy_engine_defaults_deny_and_allows_only_explicit_policy() -> None:
    services = [registered_service()]
    decision_without_policy = decide_external_dependency_policy(
        service_id="dynamic.ai_service",
        module="k.product_knowledge",
        action="k.product_knowledge.placeholder.prepare",
        context={"risk_level": "medium"},
        raw_services=services,
        raw_policies=[],
    )
    decision_with_policy = decide_external_dependency_policy(
        service_id="dynamic.ai_service",
        module="k.product_knowledge",
        action="k.product_knowledge.placeholder.prepare",
        context={"risk_level": "low", "module_sensitivity": "low"},
        raw_services=services,
        raw_policies=[allow_policy()],
    )
    decision_high_risk = decide_external_dependency_policy(
        service_id="dynamic.ai_service",
        module="k.product_knowledge",
        action="k.product_knowledge.placeholder.prepare",
        context={"risk_level": "critical", "module_sensitivity": "critical"},
        raw_services=services,
        raw_policies=[allow_policy()],
    )

    assert decision_without_policy.decision == "deny"
    assert decision_without_policy.reason == "c14d_default_deny_no_explicit_policy"
    assert decision_without_policy.default_deny_applied is True
    assert decision_with_policy.decision == "allow"
    assert decision_with_policy.explicit_policy_matched is True
    assert decision_high_risk.decision == "require_approval"
    assert decision_high_risk.c12_approval_required is True


def test_c14d_unknown_service_quarantines_and_generates_registration_proposal() -> None:
    decision = decide_external_dependency_policy(
        service_id="unknown.automation_service",
        module="integration.n8n_test_bridge",
        action="integration.n8n_test_bridge.test_run.declare",
        context={"risk_level": "medium"},
        raw_services=[],
        raw_policies=[],
    )
    proposal = build_registration_proposal(
        service_id="unknown.automation_service",
        source_module="integration.n8n_test_bridge",
        source_adapter="integration.n8n_test_bridge.adapter",
        source_action="integration.n8n_test_bridge.test_run.declare",
    )

    assert decision.decision == "quarantine"
    assert decision.registration_required is True
    assert decision.quarantine_required is True
    assert proposal.status == "quarantined"
    assert proposal.ui_surface == "c14_external_provider_control_panel"
    assert proposal.no_direct_execution_allowed is True


def test_c14d_dependency_bindings_require_declared_intent_and_policy() -> None:
    # With the registry emptied, declared intent without registration must
    # quarantine fail-closed.
    bindings = build_dependency_binding_decisions(raw_services=[], raw_policies=[])
    n8n_binding = next(
        binding
        for binding in bindings
        if binding.adapter == "integration.n8n_test_bridge.adapter"
    )

    assert n8n_binding.dependency_intent_declared is True
    assert n8n_binding.service_id == "n8n"
    assert n8n_binding.service_registered is False
    assert n8n_binding.binding_status == "quarantined"
    assert n8n_binding.policy_decision.decision == "quarantine"

    # Against the live registry every adapter-declared dependency is
    # registered, so no pending registration proposals may remain.
    assert list_registration_proposals() == []


def test_c14d_gate_allows_no_external_dependency_and_blocks_unknown_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = C14D_GATE.check(no_op_request())

    assert allowed.decision == "allow"
    assert allowed.reason == "c14d_no_external_dependency_declared"

    # Simulate the unknown-service condition by emptying the registry: the
    # n8n bridge's declared dependency then has no registration and the gate
    # must quarantine fail-closed.
    import backend.app.core.external_dependencies as external_dependencies_core
    import backend.app.services.external_dependency_governance as governance

    monkeypatch.setattr(
        external_dependencies_core, "EXTERNAL_SERVICE_REGISTRY_V1", ()
    )
    monkeypatch.setattr(governance, "EXTERNAL_SERVICE_REGISTRY_V1", ())

    with pytest.raises(
        ExternalDependencyGateBlockedError,
        match="c14d_unknown_service_quarantined",
    ):
        C14D_GATE.check(n8n_request())


def test_c14d_policy_contract_rejects_unsafe_policy_values() -> None:
    with pytest.raises(ValueError, match="select service_id or service_type"):
        validate_external_dependency_policies(
            [
                {
                    **allow_policy(),
                    "service_id": None,
                    "service_type": None,
                }
            ]
        )
    with pytest.raises(ValueError, match="sensitive"):
        validate_external_dependency_policies(
            [
                {
                    **allow_policy(),
                    "description": "contains token marker",
                }
            ]
        )
    assert set(get_args(ExternalPolicyDecisionValue)) == {
        "allow",
        "deny",
        "quarantine",
        "require_approval",
    }
