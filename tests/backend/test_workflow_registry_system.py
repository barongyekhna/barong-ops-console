from __future__ import annotations

import re
from typing import Any, get_args

import pytest

from backend.app.main import app
from backend.app.schemas.workflow_registry import WorkflowRegistryStatus
from backend.app.services.workflow_registry_system import (
    ALLOWED_WORKFLOW_REGISTRY_STATUSES,
    HIDDEN_N8N_WEBHOOK_REF_PATTERN,
    WORKFLOW_ID_PATTERN,
    build_module_workflow_bindings,
    build_workflow_registry_validation_result,
    evaluate_workflow_invocation,
    get_workflow_registry_completion_status,
    get_workflow_registry_rules_model,
    get_workflow_status_management_model,
    get_workflow_system_flow_diagram,
    list_workflow_registry,
    validate_workflow_registry,
)


def c15a_workflow(**updates: Any) -> dict[str, Any]:
    workflow = {
        "workflow_id": "n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
        "module": "integration.n8n_test_bridge",
        "trigger": "webhook",
        "status": "active",
        "n8n_webhook": (
            "n8n-webhook-ref://c15a/integration.n8n_test_bridge/"
            "dispatch/v1"
        ),
        "version": "1.0.0",
        "created_at": "2026-06-15T00:00:00Z",
        "updated_at": "2026-06-15T00:00:00Z",
    }
    workflow.update(updates)
    return workflow


def test_c15a_default_registry_defines_hidden_workflow_bindings() -> None:
    registry = list_workflow_registry()
    bindings = build_module_workflow_bindings()
    validation = build_workflow_registry_validation_result()
    rules = get_workflow_registry_rules_model()
    flow = get_workflow_system_flow_diagram()
    completion = get_workflow_registry_completion_status()

    assert registry.count == 5
    assert registry.active_count == 4
    assert registry.registry_is_single_source_of_truth is True
    assert registry.real_n8n_webhook_address_exposed is False
    assert registry.registry_executes_workflow is False
    assert validation.valid is True
    assert validation.workflow_count == 5
    assert validation.module_binding_count == 2
    assert bindings.count == 2
    binding_by_module = {item.module: item for item in bindings.items}
    assert binding_by_module["integration.n8n_test_bridge"].workflow_count == 2
    assert binding_by_module["k.product_knowledge"].workflow_count == 3
    assert binding_by_module["k.product_knowledge"].active_workflow_ids == (
        "n8n.workflow.k.product_knowledge.to_p_series.v1",
        "n8n.workflow.k.product_knowledge.to_gmc.v1",
        "n8n.workflow.k.product_knowledge.to_seo.v1",
    )
    assert rules.unregistered_workflow_callable is False
    assert rules.explicit_module_binding_required is True
    assert rules.real_n8n_webhook_address_exposure_allowed is False
    assert flow.diagram == (
        "C15A workflow match -> C15F whitelist check -> "
        "ExecutionRouter -> Provider execution mode plan"
    )
    assert flow.registry_executes_workflow is False
    assert completion.completion_status == "complete"
    assert completion.can_proceed_to_c15b is True
    assert completion.no_n8n_execution is True


def test_c15a_model_and_patterns_match_required_registry_shape() -> None:
    workflow = validate_workflow_registry([c15a_workflow()])[0]

    assert set(ALLOWED_WORKFLOW_REGISTRY_STATUSES) == set(
        get_args(WorkflowRegistryStatus)
    )
    assert WORKFLOW_ID_PATTERN.fullmatch(workflow.workflow_id)
    assert HIDDEN_N8N_WEBHOOK_REF_PATTERN.fullmatch(workflow.n8n_webhook)
    assert set(type(workflow).model_fields) == {
        "workflow_id",
        "module",
        "trigger",
        "status",
        "n8n_webhook",
        "version",
        "created_at",
        "updated_at",
    }


def test_c15a_status_management_blocks_non_active_workflows() -> None:
    status_model = get_workflow_status_management_model()
    rules = {rule.status: rule for rule in status_model.rules}

    assert rules["active"].execution_allowed is True
    assert rules["active"].decision_mode == "executable"
    assert rules["inactive"].execution_allowed is False
    assert rules["inactive"].decision_mode == "blocked"
    assert rules["deprecated"].read_only is True
    assert rules["deprecated"].execution_allowed is False
    assert rules["error"].execution_allowed is False
    assert rules["error"].decision_mode == "blocked"

    raw = [
        c15a_workflow(),
        c15a_workflow(
            workflow_id="n8n.workflow.integration.n8n_test_bridge.inactive.v1",
            status="inactive",
            n8n_webhook=(
                "n8n-webhook-ref://c15a/integration.n8n_test_bridge/"
                "inactive/v1"
            ),
        ),
        c15a_workflow(
            workflow_id="n8n.workflow.integration.n8n_test_bridge.error.v1",
            status="error",
            n8n_webhook=(
                "n8n-webhook-ref://c15a/integration.n8n_test_bridge/"
                "error/v1"
            ),
        ),
    ]

    active = evaluate_workflow_invocation(
        module="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
        raw_workflows=raw,
    )
    inactive = evaluate_workflow_invocation(
        module="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.inactive.v1",
        raw_workflows=raw,
    )
    error = evaluate_workflow_invocation(
        module="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.error.v1",
        raw_workflows=raw,
    )

    assert active.execution_allowed is True
    assert active.hidden_webhook_ref is not None
    assert inactive.execution_allowed is False
    assert inactive.decision_mode == "blocked"
    assert error.execution_allowed is False
    assert error.decision_mode == "blocked"


def test_c15a_rejects_unregistered_and_unsafe_workflow_data() -> None:
    duplicate = [
        c15a_workflow(),
        c15a_workflow(
            n8n_webhook=(
                "n8n-webhook-ref://c15a/integration.n8n_test_bridge/"
                "duplicate/v1"
            )
        ),
    ]
    with pytest.raises(ValueError, match="Duplicate C15A workflow_id"):
        validate_workflow_registry(duplicate)

    unregistered_module = c15a_workflow(module="business.missing")
    with pytest.raises(ValueError, match="module is not registered"):
        validate_workflow_registry([unregistered_module])

    real_webhook = c15a_workflow(
        n8n_webhook="https://n8n.example/webhook/token"
    )
    with pytest.raises(ValueError, match="opaque n8n webhook reference"):
        validate_workflow_registry([real_webhook])

    validation = build_workflow_registry_validation_result([real_webhook])
    assert validation.valid is False
    assert validation.hidden_webhook_policy_enforced is True
    assert validation.no_n8n_execution is True
    assert validation.no_ai_model_trigger is True


def test_c15a_decision_requires_registration_and_explicit_module_binding() -> None:
    unknown = evaluate_workflow_invocation(
        module="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.unknown.v1",
    )
    wrong_module = evaluate_workflow_invocation(
        module="business.products",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
    )
    deprecated = evaluate_workflow_invocation(
        module="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.legacy.v1",
    )

    assert unknown.registered is False
    assert unknown.execution_allowed is False
    assert unknown.hidden_webhook_ref is None
    assert wrong_module.registered is True
    assert wrong_module.bound_to_module is False
    assert wrong_module.execution_allowed is False
    assert wrong_module.hidden_webhook_ref is None
    assert deprecated.bound_to_module is True
    assert deprecated.read_only is True
    assert deprecated.execution_allowed is False


def test_c15a_router_exposes_read_only_registry_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/api/control-plane/workflow-registry")
    ]

    assert ("/api/control-plane/workflow-registry/registry", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/workflows/{workflow_id}", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/module-bindings", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/modules/{module}/workflows", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/status-management", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/rules", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/decision", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/validation", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/system-flow", {"GET"}) in routes
    assert ("/api/control-plane/workflow-registry/completion-status", {"GET"}) in routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke)\b", path)
        for path, _ in routes
    )
