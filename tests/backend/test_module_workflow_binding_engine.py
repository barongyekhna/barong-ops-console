from __future__ import annotations

import re
from typing import Any

import pytest

from backend.app.main import app
from backend.app.schemas.module_workflow_binding import (
    ModuleWorkflowBindingRecord,
)
from backend.app.services.module_workflow_binding_engine import (
    build_module_workflow_binding_model,
    build_module_workflow_binding_validation_result,
    evaluate_module_workflow_access,
    get_module_workflow_access_control_system,
    get_module_workflow_binding_completion_status,
    get_module_workflow_enforcement_rules,
    get_module_workflow_isolation_rules,
    validate_module_workflow_binding_engine,
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


def test_c15f_default_binding_model_uses_c15a_registry_whitelist() -> None:
    model = build_module_workflow_binding_model()
    validation = build_module_workflow_binding_validation_result()
    enforcement = get_module_workflow_enforcement_rules()
    access_control = get_module_workflow_access_control_system()
    isolation = get_module_workflow_isolation_rules()
    completion = get_module_workflow_binding_completion_status()
    binding = next(
        item
        for item in model.items
        if item.module_id == "integration.n8n_test_bridge"
    )
    k_binding = next(
        item
        for item in model.items
        if item.module_id == "k.product_knowledge"
    )

    assert model.c15a_registry_required is True
    assert model.whitelist_only_access is True
    assert model.allowed_workflow_count == 4
    assert binding.module_id == "integration.n8n_test_bridge"
    assert binding.allowed_workflows == (
        "n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
    )
    assert binding.read_only_workflows == (
        "n8n.workflow.integration.n8n_test_bridge.legacy.v1",
    )
    assert binding.binding_status == "active"
    assert k_binding.binding_status == "active"
    assert k_binding.allowed_workflows == (
        "n8n.workflow.k.product_knowledge.to_gmc.v1",
        "n8n.workflow.k.product_knowledge.to_p_series.v1",
        "n8n.workflow.k.product_knowledge.to_seo.v1",
    )
    assert k_binding.read_only_workflows == ()
    assert binding.workflow_must_exist_in_c15a_registry is True
    assert binding.module_can_call_unlisted_workflow is False
    assert validation.valid is True
    assert validation.allowed_workflow_count == 4
    assert validation.c15a_registry_workflow_count == 5
    assert enforcement.unbound_workflow_behavior == "reject"
    assert enforcement.cross_module_workflow_behavior == "reject"
    assert access_control.module_can_access_only_allowed_workflows is True
    assert access_control.workflow_must_be_registered_in_c15a is True
    assert isolation.cross_module_workflow_call_allowed is False
    assert completion.completion_status == "complete"
    assert completion.can_proceed_to_c15g is True
    assert completion.no_runtime_execution is True


def test_c15f_enforcement_allows_only_active_whitelisted_workflows() -> None:
    allowed = evaluate_module_workflow_access(
        module_id="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
    )
    deprecated = evaluate_module_workflow_access(
        module_id="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.legacy.v1",
    )
    unregistered = evaluate_module_workflow_access(
        module_id="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.unknown.v1",
    )

    assert allowed.workflow_access_allowed is True
    assert allowed.binding_validation_passed is True
    assert allowed.execution_rejected is False
    assert allowed.hidden_webhook_reference_exposed is False
    assert allowed.runtime_execution_allowed is False
    assert deprecated.workflow_access_allowed is False
    assert deprecated.execution_rejected is True
    assert deprecated.rejection_code == "c15f_workflow_not_allowed_for_module"
    assert deprecated.workflow_registry_status == "deprecated"
    assert unregistered.workflow_access_allowed is False
    assert unregistered.rejection_code == "c15f_workflow_not_registered"
    assert unregistered.registered_in_c15a is False


def test_c15f_blocks_cross_module_workflow_calls() -> None:
    cross_module = evaluate_module_workflow_access(
        module_id="business.products",
        workflow_id="n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
    )

    assert cross_module.workflow_access_allowed is False
    assert cross_module.execution_rejected is True
    assert cross_module.isolation_violation is True
    assert cross_module.rejection_code == (
        "c15f_cross_module_workflow_call_blocked"
    )
    assert cross_module.workflow_owned_by_module is False
    assert cross_module.workflow_in_module_whitelist is False
    assert cross_module.runtime_execution_allowed is False


def test_c15f_custom_registry_keeps_module_workflows_isolated() -> None:
    raw_workflows = [
        c15a_workflow(),
        c15a_workflow(
            workflow_id="n8n.workflow.business.products.enrich.v1",
            module="business.products",
            n8n_webhook=(
                "n8n-webhook-ref://c15a/business.products/enrich/v1"
            ),
        ),
    ]

    bindings, workflows = validate_module_workflow_binding_engine(
        raw_workflows
    )
    model = build_module_workflow_binding_model(raw_workflows)
    product_access = evaluate_module_workflow_access(
        module_id="business.products",
        workflow_id="n8n.workflow.business.products.enrich.v1",
        raw_workflows=raw_workflows,
    )
    cross_access = evaluate_module_workflow_access(
        module_id="integration.n8n_test_bridge",
        workflow_id="n8n.workflow.business.products.enrich.v1",
        raw_workflows=raw_workflows,
    )
    product_binding = next(
        item for item in model.items if item.module_id == "business.products"
    )

    assert len(workflows) == 2
    assert product_binding.allowed_workflows == (
        "n8n.workflow.business.products.enrich.v1",
    )
    assert len([binding for binding in bindings if binding.allowed_workflows]) == 2
    assert product_access.workflow_access_allowed is True
    assert product_access.binding_validation_passed is True
    assert cross_access.workflow_access_allowed is False
    assert cross_access.isolation_violation is True
    assert cross_access.rejection_code == (
        "c15f_cross_module_workflow_call_blocked"
    )


def test_c15f_validation_reports_invalid_c15a_registry_source() -> None:
    invalid = [
        c15a_workflow(
            workflow_id="n8n.workflow.integration.n8n_test_bridge.bad.v1",
            module="missing.module",
            n8n_webhook=(
                "n8n-webhook-ref://c15a/integration.n8n_test_bridge/"
                "bad/v1"
            ),
        )
    ]
    validation = build_module_workflow_binding_validation_result(invalid)

    assert validation.valid is False
    assert validation.c15a_registry_required is True
    assert validation.no_runtime_execution is True
    assert validation.issues[0].code == "c15f_module_workflow_binding_invalid"

    with pytest.raises(ValueError, match="module is not registered"):
        validate_module_workflow_binding_engine(invalid)


def test_c15f_schema_requires_binding_safety_flags() -> None:
    binding = ModuleWorkflowBindingRecord(
        module_id="integration.n8n_test_bridge",
        allowed_workflows=(
            "n8n.workflow.integration.n8n_test_bridge.dispatch.v1",
        ),
        binding_status="active",
    )

    assert set(type(binding).model_fields) >= {
        "module_id",
        "allowed_workflows",
        "binding_status",
    }
    assert binding.explicit_binding_required is True
    assert binding.workflow_whitelist_required is True
    assert binding.workflow_must_exist_in_c15a_registry is True
    assert binding.module_can_call_unlisted_workflow is False
    assert binding.cross_module_workflow_call_allowed is False
    assert binding.hidden_webhook_reference_exposed is False
    assert binding.runtime_execution_allowed is False
    assert binding.external_api_call_allowed is False
    assert binding.production_change_allowed is False
    assert binding.staging_change_allowed is False


def test_c15f_router_exposes_only_read_contract_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith(
            "/api/control-plane/module-workflow-bindings"
        )
    ]

    assert ("/api/control-plane/module-workflow-bindings/model", {"GET"}) in routes
    assert ("/api/control-plane/module-workflow-bindings/enforcement", {"GET"}) in routes
    assert ("/api/control-plane/module-workflow-bindings/access-control", {"GET"}) in routes
    assert ("/api/control-plane/module-workflow-bindings/isolation-rules", {"GET"}) in routes
    assert ("/api/control-plane/module-workflow-bindings/decision", {"GET"}) in routes
    assert ("/api/control-plane/module-workflow-bindings/validation", {"GET"}) in routes
    assert ("/api/control-plane/module-workflow-bindings/completion-status", {"GET"}) in routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke)\b", path)
        for path, _ in routes
    )
