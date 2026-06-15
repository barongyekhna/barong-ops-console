from __future__ import annotations

import re
from typing import Any

import pytest

from backend.app.main import app
from backend.app.schemas.module_allocation import ModuleAllocationRecord
from backend.app.services.module_allocation_system import (
    MODULE_CATEGORY_CAPABILITIES,
    build_module_allocation_budget_system,
    build_module_allocation_validation_result,
    get_module_allocation_assignment_model,
    get_module_allocation_category_model,
    get_module_allocation_completion_status,
    get_module_allocation_enforcement_rules,
    get_module_allocation_integration_flow,
    list_module_allocation_registry,
    validate_module_allocation_registry,
    validate_module_allocation_request,
)


def c14x_d_budget(**updates: Any) -> dict[str, Any]:
    budget = {
        "capability": "reasoning",
        "max_units_per_request": 25,
        "max_units_per_window": 100,
        "window_seconds": 3600,
    }
    budget.update(updates)
    return budget


def c14x_d_allocation(**updates: Any) -> dict[str, Any]:
    allocation = {
        "module_id": "SEO",
        "allowed_capabilities": ("reasoning",),
        "bound_key": "ai.binding.reasoning.primary",
        "bound_model": "model.reasoning.primary_v1",
        "status": "active",
        "capability_budgets": (c14x_d_budget(),),
        "reason": "Explicit C14X-D module allocation for inspection only.",
    }
    allocation.update(updates)
    return allocation


def test_c14x_d_default_module_allocation_registry_is_empty_and_no_execute() -> None:
    registry = list_module_allocation_registry()
    assignment = get_module_allocation_assignment_model()
    categories = get_module_allocation_category_model()
    budgets = build_module_allocation_budget_system()
    enforcement = get_module_allocation_enforcement_rules()
    integration = get_module_allocation_integration_flow()
    validation = build_module_allocation_validation_result()
    completion = get_module_allocation_completion_status()

    assert registry.items == []
    assert registry.count == 0
    assert registry.active_count == 0
    assert registry.no_shared_capability_pool is True
    assert assignment.allocation_shape == (
        "module_id",
        "allowed_capabilities",
        "bound_key",
        "bound_model",
        "status",
        "capability_budgets",
    )
    assert categories.module_ids == ("K-series", "P-series", "SEO", "BS")
    assert {
        item.module_id: item.allowed_capabilities for item in categories.items
    } == MODULE_CATEGORY_CAPABILITIES
    assert budgets.items == []
    assert budgets.count == 0
    assert budgets.no_unlimited_ai_access is True
    assert validation.valid is True
    assert validation.allocation_count == 0
    assert validation.budget_count == 0
    assert enforcement.missing_allocation_behavior == "reject_without_fallback"
    assert enforcement.budget_exceeded_behavior == (
        "reject_without_unlimited_access"
    )
    assert integration.flow == (
        "Module",
        "C14X-D allocation check",
        "C14X-C routing",
        "C14X-B model lock",
        "C09 execution",
        "C10 sandbox",
    )
    assert integration.allocation_pass_grants_execution is False
    assert completion.can_proceed_to_c14x_e is True
    assert completion.no_runtime_execution is True
    assert completion.no_external_api_call is True


def test_c14x_d_explicit_module_allocation_binds_capability_key_model_and_budget() -> None:
    raw_allocations = [c14x_d_allocation()]

    registry = list_module_allocation_registry(raw_allocations)
    budgets = build_module_allocation_budget_system(raw_allocations)
    request_validation = validate_module_allocation_request(
        module_id="SEO",
        capability="reasoning",
        key="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.primary_v1",
        requested_units=10,
        current_window_units=20,
        raw_allocations=raw_allocations,
    )

    allocation = registry.items[0]
    budget = budgets.items[0]
    assert allocation.module_id == "SEO"
    assert allocation.allowed_capabilities == ("reasoning",)
    assert allocation.bound_key == "ai.binding.reasoning.primary"
    assert allocation.bound_model == "model.reasoning.primary_v1"
    assert allocation.status == "active"
    assert allocation.implicit_capability_access_allowed is False
    assert allocation.shared_capability_pool_allowed is False
    assert allocation.unlimited_ai_access_allowed is False
    assert budget.capability == "reasoning"
    assert budget.max_units_per_request == 25
    assert budget.max_units_per_window == 100
    assert budget.unlimited_access_allowed is False
    assert request_validation.valid is True
    assert request_validation.allocation_validation_passed is True
    assert request_validation.capability_assignment_passed is True
    assert request_validation.budget_validation_passed is True
    assert request_validation.budget_remaining_units == 70
    assert request_validation.execution_rejected is False
    assert request_validation.runtime_execution_allowed is False
    assert request_validation.model_invocation_allowed is False
    assert request_validation.external_api_call_allowed is False


def test_c14x_d_rejects_category_drift_shared_pool_and_missing_budget() -> None:
    with pytest.raises(ValueError, match="category capability violation"):
        validate_module_allocation_registry(
            [
                c14x_d_allocation(
                    module_id="P-series",
                    allowed_capabilities=("reasoning",),
                    capability_budgets=(c14x_d_budget(),),
                )
            ]
        )

    with pytest.raises(ValueError, match="Shared capability pool violation"):
        validate_module_allocation_registry(
            [
                c14x_d_allocation(),
                c14x_d_allocation(
                    module_id="K-series",
                    bound_key="ai.binding.k.reasoning",
                    bound_model="model.k.reasoning_v1",
                ),
            ]
        )

    with pytest.raises(ValueError, match="missing capability budget"):
        validate_module_allocation_registry(
            [
                c14x_d_allocation(
                    allowed_capabilities=("serp", "reasoning"),
                    capability_budgets=(c14x_d_budget(capability="reasoning"),),
                )
            ]
        )

    validation = build_module_allocation_validation_result(
        [
            c14x_d_allocation(
                module_id="P-series",
                allowed_capabilities=("reasoning",),
                capability_budgets=(c14x_d_budget(),),
            )
        ]
    )
    assert validation.valid is False
    assert validation.no_implicit_capability_access is True
    assert validation.no_shared_capability_pool is True
    assert validation.no_unlimited_ai_access is True


def test_c14x_d_request_validation_rejects_without_implicit_or_unlimited_access() -> None:
    raw_allocations = [c14x_d_allocation()]

    missing_capability = validate_module_allocation_request(
        module_id="SEO",
        capability="writing",
        key="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.primary_v1",
        requested_units=10,
        raw_allocations=raw_allocations,
    )
    key_mismatch = validate_module_allocation_request(
        module_id="SEO",
        capability="reasoning",
        key="ai.binding.reasoning.secondary",
        requested_model_id="model.reasoning.primary_v1",
        requested_units=10,
        raw_allocations=raw_allocations,
    )
    request_limit = validate_module_allocation_request(
        module_id="SEO",
        capability="reasoning",
        key="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.primary_v1",
        requested_units=30,
        raw_allocations=raw_allocations,
    )
    window_limit = validate_module_allocation_request(
        module_id="SEO",
        capability="reasoning",
        key="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.primary_v1",
        requested_units=20,
        current_window_units=90,
        raw_allocations=raw_allocations,
    )

    assert missing_capability.valid is False
    assert missing_capability.rejection_code == "c14x_d_capability_not_assigned"
    assert missing_capability.implicit_capability_access_blocked is True
    assert missing_capability.shared_capability_pool_blocked is True
    assert key_mismatch.valid is False
    assert key_mismatch.rejection_code == "c14x_d_bound_key_mismatch"
    assert request_limit.valid is False
    assert request_limit.rejection_code == "c14x_d_budget_request_limit_exceeded"
    assert request_limit.unlimited_ai_access_blocked is True
    assert window_limit.valid is False
    assert window_limit.rejection_code == "c14x_d_budget_window_exceeded"
    assert window_limit.budget_remaining_units == 10
    assert window_limit.fallback_capability_blocked is True


def test_c14x_d_schema_requires_strict_allocation_safety_flags() -> None:
    allocation = ModuleAllocationRecord.model_validate(c14x_d_allocation())
    budget = allocation.capability_budgets[0]

    assert allocation.explicit_assignment_required is True
    assert allocation.binding_must_be_explicit is True
    assert allocation.bound_key_required is True
    assert allocation.bound_model_required is True
    assert allocation.capability_budget_required is True
    assert allocation.module_to_capability_fixed is True
    assert allocation.implicit_capability_access_allowed is False
    assert allocation.shared_capability_pool_allowed is False
    assert allocation.cross_module_capability_access_allowed is False
    assert allocation.fallback_capability_allowed is False
    assert allocation.auto_routing_allowed is False
    assert allocation.unlimited_ai_access_allowed is False
    assert allocation.registry_executes_ai is False
    assert allocation.runtime_execution_allowed is False
    assert allocation.model_invocation_allowed is False
    assert allocation.external_api_call_allowed is False
    assert allocation.production_change_allowed is False
    assert allocation.staging_change_allowed is False
    assert budget.budget_enforced is True
    assert budget.usage_constraint_required is True
    assert budget.unlimited_access_allowed is False
    assert budget.runtime_metering_performed is False


def test_c14x_d_router_exposes_only_read_contract_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/module-allocations")
    ]

    assert ("/module-allocations/registry", {"GET"}) in routes
    assert ("/module-allocations/assignment-model", {"GET"}) in routes
    assert ("/module-allocations/categories", {"GET"}) in routes
    assert ("/module-allocations/budget-system", {"GET"}) in routes
    assert ("/module-allocations/enforcement", {"GET"}) in routes
    assert ("/module-allocations/integration-flow", {"GET"}) in routes
    assert ("/module-allocations/validation", {"GET"}) in routes
    assert ("/module-allocations/request-validation", {"GET"}) in routes
    assert ("/module-allocations/completion-status", {"GET"}) in routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke)\b", path)
        for path, _ in routes
    )
