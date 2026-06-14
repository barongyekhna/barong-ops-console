from __future__ import annotations

import re
from typing import Any, get_args

import pytest

from backend.app.main import app
from backend.app.schemas.ai_execution_binding import (
    AIExecutionBindingRecord,
    AIExecutionBindingStatus,
    AIExecutionCapability,
)
from backend.app.services.ai_execution_binding_registry import (
    AI_BINDING_KEY_PATTERN,
    AI_MODEL_REF_PATTERN,
    ALLOWED_AI_EXECUTION_BINDING_STATUSES,
    ALLOWED_AI_EXECUTION_CAPABILITIES,
    build_ai_execution_binding_validation_result,
    build_ai_execution_flow_mapping,
    get_ai_execution_binding_rule_model,
    get_ai_execution_binding_ui_interaction_model,
    list_ai_execution_binding_registry,
    validate_ai_execution_binding_registry,
)


def c14x_a_binding(**updates: Any) -> dict[str, Any]:
    binding = {
        "key": "ai.binding.reasoning.primary",
        "model": "model.reasoning.primary_v1",
        "capability": "reasoning",
        "module": "business.products",
        "status": "active",
        "reason": "Explicit C14X-A route declaration for contract inspection only.",
    }
    binding.update(updates)
    return binding


def test_c14x_a_default_registry_is_empty_and_no_execute() -> None:
    registry = list_ai_execution_binding_registry()
    rules = get_ai_execution_binding_rule_model()
    validation = build_ai_execution_binding_validation_result()
    flow = build_ai_execution_flow_mapping()
    ui = get_ai_execution_binding_ui_interaction_model()

    assert registry.items == []
    assert registry.count == 0
    assert registry.active_count == 0
    assert validation.valid is True
    assert validation.binding_count == 0
    assert flow.routes == []
    assert flow.registry_executes_ai is False
    assert rules.binding_shape == ("key", "model", "capability", "module", "status")
    assert rules.key_to_model_fixed is True
    assert rules.model_to_capability_fixed is True
    assert rules.capability_to_module_fixed is True
    assert rules.automatic_model_selection_allowed is False
    assert rules.fallback_routing_allowed is False
    assert rules.implicit_execution_routing_allowed is False
    assert rules.binding_creation_policy == "explicit_only"
    assert rules.binding_update_policy == "manual_override_only"
    assert rules.binding_deletion_policy == "controlled_operation_only"
    assert rules.registry_executes_ai is False
    assert ui.allowed_methods == ("GET",)
    assert ui.create_update_delete_surface == "not_exposed_in_ui"


def test_c14x_a_explicit_binding_maps_fixed_one_to_one_route() -> None:
    raw = [c14x_a_binding()]

    registry = list_ai_execution_binding_registry(raw)
    flow = build_ai_execution_flow_mapping(raw)
    route = flow.routes[0]

    assert len(registry.items) == 1
    assert registry.items[0].key == "ai.binding.reasoning.primary"
    assert registry.items[0].model == "model.reasoning.primary_v1"
    assert registry.items[0].capability == "reasoning"
    assert registry.items[0].module == "business.products"
    assert registry.items[0].status == "active"
    assert route.routing_path == (
        "ai.binding.reasoning.primary",
        "model.reasoning.primary_v1",
        "reasoning",
        "business.products",
    )
    assert route.registry_only_defines_routing_path is True
    assert route.registry_executes_ai is False
    assert route.execution_allowed is False
    assert route.model_invocation_allowed is False
    assert route.external_api_call_allowed is False
    assert route.fallback_route_available is False


def test_c14x_a_binding_rules_reject_duplicate_one_to_one_dimensions() -> None:
    duplicate_key = [
        c14x_a_binding(),
        c14x_a_binding(
            key="ai.binding.reasoning.primary",
            model="model.writing.primary_v1",
            capability="writing",
            module="admin.users",
        ),
    ]
    duplicate_model = [
        c14x_a_binding(),
        c14x_a_binding(
            key="ai.binding.writing.primary",
            model="model.reasoning.primary_v1",
            capability="writing",
            module="admin.users",
        ),
    ]
    duplicate_capability = [
        c14x_a_binding(),
        c14x_a_binding(
            key="ai.binding.reasoning.secondary",
            model="model.reasoning.secondary_v1",
            capability="reasoning",
            module="admin.users",
        ),
    ]
    duplicate_module = [
        c14x_a_binding(),
        c14x_a_binding(
            key="ai.binding.writing.primary",
            model="model.writing.primary_v1",
            capability="writing",
            module="business.products",
        ),
    ]

    with pytest.raises(ValueError, match="Duplicate AI execution binding key"):
        validate_ai_execution_binding_registry(duplicate_key)
    with pytest.raises(ValueError, match="model binding violation"):
        validate_ai_execution_binding_registry(duplicate_model)
    with pytest.raises(ValueError, match="capability binding violation"):
        validate_ai_execution_binding_registry(duplicate_capability)
    with pytest.raises(ValueError, match="module binding violation"):
        validate_ai_execution_binding_registry(duplicate_module)


def test_c14x_a_binding_registry_rejects_auto_route_and_runtime_values() -> None:
    assert set(ALLOWED_AI_EXECUTION_CAPABILITIES) == set(
        get_args(AIExecutionCapability)
    )
    assert set(ALLOWED_AI_EXECUTION_BINDING_STATUSES) == set(
        get_args(AIExecutionBindingStatus)
    )
    assert AI_BINDING_KEY_PATTERN.fullmatch("ai.binding.reasoning.primary")
    assert AI_MODEL_REF_PATTERN.fullmatch("model.reasoning.primary_v1")

    unsafe = c14x_a_binding(model="https://provider.example/model")
    with pytest.raises(ValueError, match="model reference"):
        validate_ai_execution_binding_registry([unsafe])

    unregistered_module = c14x_a_binding(module="business.missing")
    with pytest.raises(ValueError, match="module is not registered"):
        validate_ai_execution_binding_registry([unregistered_module])

    implicit_route = c14x_a_binding(
        fallback_routing_allowed=True,
    )
    with pytest.raises(Exception):
        validate_ai_execution_binding_registry([implicit_route])

    extra_fallback = c14x_a_binding(fallback_model="model.other")
    with pytest.raises(Exception):
        validate_ai_execution_binding_registry([extra_fallback])

    validation = build_ai_execution_binding_validation_result([unsafe])
    assert validation.valid is False
    assert validation.no_runtime_execution is True
    assert validation.no_model_invocation is True
    assert validation.no_external_api_call is True


def test_c14x_a_schema_requires_safety_flags() -> None:
    binding = AIExecutionBindingRecord.model_validate(c14x_a_binding())

    assert binding.explicit_binding_required is True
    assert binding.one_to_one_binding_required is True
    assert binding.key_to_model_fixed is True
    assert binding.model_to_capability_fixed is True
    assert binding.capability_to_module_fixed is True
    assert binding.automatic_model_selection_allowed is False
    assert binding.fallback_routing_allowed is False
    assert binding.implicit_execution_routing_allowed is False
    assert binding.registry_executes_ai is False
    assert binding.runtime_execution_allowed is False
    assert binding.model_invocation_allowed is False
    assert binding.external_api_call_allowed is False
    assert binding.production_change_allowed is False


def test_c14x_a_router_exposes_only_read_contract_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/ai-execution-bindings")
    ]

    assert ("/ai-execution-bindings/registry", {"GET"}) in routes
    assert ("/ai-execution-bindings/rules", {"GET"}) in routes
    assert ("/ai-execution-bindings/execution-flow", {"GET"}) in routes
    assert ("/ai-execution-bindings/validation", {"GET"}) in routes
    assert ("/ai-execution-bindings/ui-interaction", {"GET"}) in routes
    assert ("/ai-execution-bindings/completion-status", {"GET"}) in routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke)\b", path)
        for path, _ in routes
    )
