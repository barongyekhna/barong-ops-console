from __future__ import annotations

import re
from typing import Any

import pytest

from backend.app.main import app
from backend.app.schemas.model_lock import ModelLockRegistryRecord
from backend.app.services.model_lock_registry import (
    MODEL_LOCK_TIMESTAMP_PATTERN,
    build_model_lock_validation_result,
    get_model_lock_c14x_a_integration,
    get_model_lock_completion_status,
    get_model_lock_enforcement_logic,
    get_model_lock_rule_model,
    list_model_lock_registry,
    validate_model_lock_registry,
    validate_model_lock_request,
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


def test_c14x_b_default_model_lock_registry_is_empty_and_no_execute() -> None:
    registry = list_model_lock_registry()
    rules = get_model_lock_rule_model()
    enforcement = get_model_lock_enforcement_logic()
    validation = build_model_lock_validation_result()
    integration = get_model_lock_c14x_a_integration()
    completion = get_model_lock_completion_status()

    assert registry.items == []
    assert registry.count == 0
    assert registry.locked_count == 0
    assert validation.valid is True
    assert validation.lock_count == 0
    assert validation.c14x_a_binding_count == 0
    assert rules.registry_shape == (
        "key_id",
        "model_id",
        "locked",
        "lock_timestamp",
        "lock_reason",
    )
    assert rules.one_key_one_model_required is True
    assert rules.model_change_allowed is False
    assert rules.runtime_model_switching_allowed is False
    assert rules.fallback_model_selection_allowed is False
    assert rules.implicit_routing_override_allowed is False
    assert enforcement.missing_lock_behavior == "reject_without_fallback"
    assert enforcement.mismatch_behavior == "reject_execution"
    assert enforcement.runtime_model_switching_blocked is True
    assert integration.every_c14x_a_binding_requires_model_lock is True
    assert integration.orphan_model_lock_allowed is False
    assert completion.can_proceed_to_c14x_c is True


def test_c14x_b_explicit_model_lock_matches_c14x_a_binding() -> None:
    raw_bindings = [c14x_a_binding()]
    raw_locks = [c14x_b_lock()]

    registry = list_model_lock_registry(raw_locks, raw_bindings)
    validation = build_model_lock_validation_result(raw_locks, raw_bindings)
    request_validation = validate_model_lock_request(
        key_id="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.primary_v1",
        raw_locks=raw_locks,
        raw_bindings=raw_bindings,
    )

    assert len(registry.items) == 1
    assert registry.items[0].key_id == "ai.binding.reasoning.primary"
    assert registry.items[0].model_id == "model.reasoning.primary_v1"
    assert registry.items[0].locked is True
    assert validation.valid is True
    assert validation.lock_count == 1
    assert validation.c14x_a_binding_count == 1
    assert request_validation.valid is True
    assert request_validation.lock_validation_passed is True
    assert request_validation.execution_rejected is False
    assert request_validation.locked_model_id == "model.reasoning.primary_v1"
    assert request_validation.runtime_execution_allowed is False
    assert request_validation.model_invocation_allowed is False
    assert request_validation.external_api_call_allowed is False
    assert request_validation.no_production_change is True
    assert request_validation.no_staging_change is True


def test_c14x_b_rejects_runtime_model_switching_request() -> None:
    request_validation = validate_model_lock_request(
        key_id="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.secondary_v1",
        raw_locks=[c14x_b_lock()],
        raw_bindings=[c14x_a_binding()],
    )

    assert request_validation.valid is False
    assert request_validation.lock_validation_passed is False
    assert request_validation.execution_rejected is True
    assert request_validation.rejection_code == "c14x_b_model_lock_mismatch"
    assert request_validation.locked_model_id == "model.reasoning.primary_v1"
    assert request_validation.runtime_model_switching_blocked is True
    assert request_validation.fallback_model_selection_blocked is True
    assert request_validation.implicit_routing_override_blocked is True


def test_c14x_b_rejects_missing_lock_without_fallback() -> None:
    request_validation = validate_model_lock_request(
        key_id="ai.binding.reasoning.primary",
        requested_model_id="model.reasoning.primary_v1",
        raw_locks=[],
        raw_bindings=[],
    )

    assert request_validation.valid is False
    assert request_validation.execution_rejected is True
    assert request_validation.rejection_code == "c14x_b_model_lock_missing"
    assert request_validation.locked_model_id is None
    assert request_validation.fallback_model_selection_blocked is True


def test_c14x_b_registry_rejects_model_lock_drift() -> None:
    raw_bindings = [c14x_a_binding()]
    duplicate_key = [
        c14x_b_lock(),
        c14x_b_lock(model_id="model.reasoning.secondary_v1"),
    ]
    duplicate_model = [
        c14x_b_lock(),
        c14x_b_lock(
            key_id="ai.binding.writing.primary",
            model_id="model.reasoning.primary_v1",
        ),
    ]
    c14x_a_mismatch = [
        c14x_b_lock(model_id="model.reasoning.secondary_v1"),
    ]
    missing_lock = [
        c14x_a_binding(),
        c14x_a_binding(
            key="ai.binding.writing.primary",
            model="model.writing.primary_v1",
            capability="writing",
            module="admin.users",
        ),
    ]
    orphan_lock = [c14x_b_lock(key_id="ai.binding.writing.primary")]

    with pytest.raises(ValueError, match="immutability violation"):
        validate_model_lock_registry(duplicate_key, raw_bindings)
    with pytest.raises(ValueError, match="model lock reuse violation"):
        validate_model_lock_registry(duplicate_model, raw_bindings)
    with pytest.raises(ValueError, match="model lock mismatch"):
        validate_model_lock_registry(c14x_a_mismatch, raw_bindings)
    with pytest.raises(ValueError, match="missing C14X-B model lock"):
        validate_model_lock_registry([c14x_b_lock()], missing_lock)
    with pytest.raises(ValueError, match="not registered in C14X-A"):
        validate_model_lock_registry(orphan_lock, raw_bindings)


def test_c14x_b_schema_requires_immutable_safety_flags() -> None:
    lock = ModelLockRegistryRecord.model_validate(c14x_b_lock())

    assert MODEL_LOCK_TIMESTAMP_PATTERN.fullmatch(lock.lock_timestamp)
    assert lock.locked is True
    assert lock.one_key_one_model_required is True
    assert lock.model_change_allowed is False
    assert lock.runtime_model_switching_allowed is False
    assert lock.fallback_model_selection_allowed is False
    assert lock.implicit_routing_override_allowed is False
    assert lock.registry_executes_ai is False
    assert lock.runtime_execution_allowed is False
    assert lock.model_invocation_allowed is False
    assert lock.external_api_call_allowed is False
    assert lock.no_production_change is True
    assert lock.no_staging_change is True
    assert lock.production_change_allowed is False
    assert lock.staging_change_allowed is False


def test_c14x_b_router_exposes_only_read_contract_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/api/control-plane/model-locks")
    ]

    assert ("/api/control-plane/model-locks/registry", {"GET"}) in routes
    assert ("/api/control-plane/model-locks/rules", {"GET"}) in routes
    assert ("/api/control-plane/model-locks/enforcement", {"GET"}) in routes
    assert ("/api/control-plane/model-locks/validation", {"GET"}) in routes
    assert ("/api/control-plane/model-locks/request-validation", {"GET"}) in routes
    assert ("/api/control-plane/model-locks/integration", {"GET"}) in routes
    assert ("/api/control-plane/model-locks/completion-status", {"GET"}) in routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke)\b", path)
        for path, _ in routes
    )
