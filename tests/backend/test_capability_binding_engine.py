from __future__ import annotations

import re
from typing import Any

import pytest

from backend.app.main import app
from backend.app.schemas.capability_binding import (
    CapabilityBindingRecord,
    ModuleCapabilityBindingRecord,
)
from backend.app.services.capability_binding_engine import (
    build_capability_binding_validation_result,
    build_capability_model_mapping,
    build_capability_routing_model,
    get_capability_binding_completion_status,
    get_capability_binding_enforcement_strategy,
    get_capability_binding_integration_model,
    list_module_capability_binding_rules,
    validate_capability_binding_engine,
    validate_capability_binding_request,
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


def c14x_b_lock(**updates: Any) -> dict[str, Any]:
    lock = {
        "key_id": "ai.binding.reasoning.primary",
        "model_id": "model.reasoning.primary_v1",
        "locked": True,
        "lock_timestamp": "2026-06-15T00:00:00Z",
        "lock_reason": "C14X-B immutable model lock for C14X-A binding.",
    }
    lock.update(updates)
    return lock


def c14x_c_capability_binding(**updates: Any) -> dict[str, Any]:
    binding = {
        "capability": "reasoning",
        "key": "ai.binding.reasoning.primary",
        "model": "model.reasoning.primary_v1",
        "module": "business.products",
        "status": "active",
        "reason": "Explicit C14X-C capability binding for inspection only.",
    }
    binding.update(updates)
    return binding


def c14x_c_module_binding(**updates: Any) -> dict[str, Any]:
    binding = {
        "module": "business.products",
        "allowed_capabilities": ("reasoning",),
        "status": "active",
        "reason": "Explicit C14X-C module capability allow binding.",
    }
    binding.update(updates)
    return binding


def test_c14x_c_default_capability_binding_engine_is_empty_and_no_execute() -> None:
    routing = build_capability_routing_model()
    mapping = build_capability_model_mapping()
    module_rules = list_module_capability_binding_rules()
    enforcement = get_capability_binding_enforcement_strategy()
    validation = build_capability_binding_validation_result()
    integration = get_capability_binding_integration_model()
    completion = get_capability_binding_completion_status()

    assert routing.supported_capabilities == (
        "serp",
        "reasoning",
        "writing",
        "embedding",
    )
    assert routing.routes == []
    assert routing.count == 0
    assert routing.active_count == 0
    assert routing.unbound_capability_behavior == "reject_without_fallback"
    assert mapping.items == []
    assert mapping.count == 0
    assert mapping.unbound_capability_behavior == "reject_without_fallback"
    assert module_rules.items == []
    assert module_rules.count == 0
    assert validation.valid is True
    assert validation.capability_binding_count == 0
    assert validation.module_binding_count == 0
    assert validation.c14x_a_binding_count == 0
    assert validation.c14x_b_lock_count == 0
    assert enforcement.missing_capability_behavior == "reject_without_fallback"
    assert enforcement.model_mismatch_behavior == "reject_without_model_switch"
    assert enforcement.module_binding_missing_behavior == (
        "reject_without_implicit_access"
    )
    assert integration.every_c14x_a_binding_requires_capability_binding is True
    assert integration.every_capability_binding_requires_c14x_b_model_lock is True
    assert completion.can_proceed_to_c14x_d is True
    assert completion.no_runtime_execution is True
    assert completion.no_external_api_call is True


def test_c14x_c_explicit_capability_route_maps_to_locked_model_and_module() -> None:
    raw_ai_bindings = [c14x_a_binding()]
    raw_locks = [c14x_b_lock()]
    raw_capability_bindings = [c14x_c_capability_binding()]
    raw_module_bindings = [c14x_c_module_binding()]

    capability_bindings, module_bindings, ai_bindings, locks = (
        validate_capability_binding_engine(
            raw_capability_bindings,
            raw_module_bindings,
            raw_ai_bindings,
            raw_locks,
        )
    )
    routing = build_capability_routing_model(
        raw_capability_bindings,
        raw_module_bindings,
        raw_ai_bindings,
        raw_locks,
    )
    mapping = build_capability_model_mapping(
        raw_capability_bindings,
        raw_module_bindings,
        raw_ai_bindings,
        raw_locks,
    )
    route = routing.routes[0]
    model_mapping = mapping.items[0]

    assert len(capability_bindings) == 1
    assert len(module_bindings) == 1
    assert len(ai_bindings) == 1
    assert len(locks) == 1
    assert route.routing_path == (
        "reasoning",
        "ai.binding.reasoning.primary",
        "model.reasoning.primary_v1",
        "business.products",
    )
    assert route.c14x_b_locked_model_id == "model.reasoning.primary_v1"
    assert route.model_lock_respected is True
    assert route.capability_auto_switch_allowed is False
    assert route.auto_routing_allowed is False
    assert route.fallback_capability_allowed is False
    assert route.execution_allowed is False
    assert model_mapping.mapping_path == (
        "reasoning",
        "model.reasoning.primary_v1",
        "ai.binding.reasoning.primary",
        "business.products",
    )
    assert model_mapping.locked_model_id == "model.reasoning.primary_v1"
    assert model_mapping.runtime_execution_allowed is False


def test_c14x_c_rejects_capability_model_and_module_drift() -> None:
    raw_ai_bindings = [c14x_a_binding()]
    raw_locks = [c14x_b_lock()]
    raw_module_bindings = [c14x_c_module_binding()]

    with pytest.raises(ValueError, match="C14X-A/C14X-C model mismatch"):
        validate_capability_binding_engine(
            [
                c14x_c_capability_binding(
                    model="model.reasoning.secondary_v1"
                )
            ],
            raw_module_bindings,
            raw_ai_bindings,
            raw_locks,
        )

    with pytest.raises(ValueError, match="missing an active module"):
        validate_capability_binding_engine(
            [c14x_c_capability_binding()],
            [],
            raw_ai_bindings,
            raw_locks,
        )

    with pytest.raises(ValueError, match="does not allow capability"):
        validate_capability_binding_engine(
            [c14x_c_capability_binding()],
            [c14x_c_module_binding(allowed_capabilities=("writing",))],
            raw_ai_bindings,
            raw_locks,
        )

    with pytest.raises(ValueError, match="missing C14X-C capability binding"):
        validate_capability_binding_engine(
            [],
            [],
            raw_ai_bindings,
            raw_locks,
        )

    with pytest.raises(ValueError, match="without explicit capability route"):
        validate_capability_binding_engine(
            [],
            [c14x_c_module_binding()],
            [],
            [],
        )

    with pytest.raises(ValueError, match="Capability drift violation"):
        validate_capability_binding_engine(
            [],
            [
                c14x_c_module_binding(),
                c14x_c_module_binding(module="admin.users"),
            ],
            [],
            [],
        )


def test_c14x_c_request_validation_rejects_without_fallback() -> None:
    raw_ai_bindings = [c14x_a_binding()]
    raw_locks = [c14x_b_lock()]
    raw_capability_bindings = [c14x_c_capability_binding()]
    raw_module_bindings = [c14x_c_module_binding()]

    valid_request = validate_capability_binding_request(
        capability="reasoning",
        key="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.primary_v1",
        module="business.products",
        raw_capability_bindings=raw_capability_bindings,
        raw_module_bindings=raw_module_bindings,
        raw_ai_bindings=raw_ai_bindings,
        raw_locks=raw_locks,
    )
    model_mismatch = validate_capability_binding_request(
        capability="reasoning",
        key="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.secondary_v1",
        module="business.products",
        raw_capability_bindings=raw_capability_bindings,
        raw_module_bindings=raw_module_bindings,
        raw_ai_bindings=raw_ai_bindings,
        raw_locks=raw_locks,
    )
    missing_capability = validate_capability_binding_request(
        capability="writing",
        key="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.primary_v1",
        module="business.products",
        raw_capability_bindings=raw_capability_bindings,
        raw_module_bindings=raw_module_bindings,
        raw_ai_bindings=raw_ai_bindings,
        raw_locks=raw_locks,
    )

    assert valid_request.valid is True
    assert valid_request.capability_binding_validation_passed is True
    assert valid_request.module_capability_binding_passed is True
    assert valid_request.model_lock_validation_passed is True
    assert valid_request.execution_rejected is False
    assert valid_request.runtime_execution_allowed is False
    assert valid_request.model_invocation_allowed is False
    assert valid_request.external_api_call_allowed is False
    assert model_mismatch.valid is False
    assert model_mismatch.execution_rejected is True
    assert model_mismatch.rejection_code == "c14x_c_capability_model_mismatch"
    assert model_mismatch.fallback_model_selection_blocked is True
    assert model_mismatch.runtime_model_switching_blocked is True
    assert missing_capability.valid is False
    assert missing_capability.rejection_code == "c14x_c_capability_binding_missing"
    assert missing_capability.fallback_capability_blocked is True
    assert missing_capability.auto_routing_blocked is True


def test_c14x_c_schema_requires_strict_safety_flags() -> None:
    capability_binding = CapabilityBindingRecord.model_validate(
        c14x_c_capability_binding()
    )
    module_binding = ModuleCapabilityBindingRecord.model_validate(
        c14x_c_module_binding()
    )

    assert capability_binding.explicit_binding_required is True
    assert capability_binding.c14x_a_binding_required is True
    assert capability_binding.c14x_b_model_lock_required is True
    assert capability_binding.module_capability_binding_required is True
    assert capability_binding.capability_to_model_fixed is True
    assert capability_binding.model_lock_respected is True
    assert capability_binding.capability_auto_switch_allowed is False
    assert capability_binding.auto_routing_allowed is False
    assert capability_binding.fallback_capability_allowed is False
    assert capability_binding.implicit_capability_access_allowed is False
    assert capability_binding.registry_executes_ai is False
    assert capability_binding.runtime_execution_allowed is False
    assert capability_binding.model_invocation_allowed is False
    assert capability_binding.external_api_call_allowed is False
    assert module_binding.strict_enforcement_required is True
    assert module_binding.implicit_capability_access_allowed is False
    assert module_binding.cross_module_capability_access_allowed is False
    assert module_binding.fallback_capability_allowed is False
    assert module_binding.auto_routing_allowed is False
    assert module_binding.runtime_execution_allowed is False


def test_c14x_c_router_exposes_only_read_contract_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/capability-bindings")
    ]

    assert ("/capability-bindings/routing-model", {"GET"}) in routes
    assert ("/capability-bindings/model-mapping", {"GET"}) in routes
    assert ("/capability-bindings/module-bindings", {"GET"}) in routes
    assert ("/capability-bindings/enforcement", {"GET"}) in routes
    assert ("/capability-bindings/validation", {"GET"}) in routes
    assert ("/capability-bindings/request-validation", {"GET"}) in routes
    assert ("/capability-bindings/integration", {"GET"}) in routes
    assert ("/capability-bindings/completion-status", {"GET"}) in routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke)\b", path)
        for path, _ in routes
    )
