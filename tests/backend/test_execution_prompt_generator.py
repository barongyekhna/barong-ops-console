from __future__ import annotations

import re
from typing import Any

from backend.app.main import app
from backend.app.schemas.execution_prompt import AIExecutionPrompt
from backend.app.services.execution_prompt_generator import (
    build_execution_prompt_payload,
    build_execution_prompt_validation_result,
    get_execution_prompt_binding_injection_model,
    get_execution_prompt_completion_status,
    get_execution_prompt_context_assembly_rules,
    get_execution_prompt_security_constraints,
    get_execution_prompt_template_engine_design,
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


def test_c14x_e_default_prompt_generator_is_contract_only_and_rejects_unbound_payload() -> None:
    template = get_execution_prompt_template_engine_design()
    injection = get_execution_prompt_binding_injection_model()
    assembly = get_execution_prompt_context_assembly_rules()
    security = get_execution_prompt_security_constraints()
    validation = build_execution_prompt_validation_result()
    completion = get_execution_prompt_completion_status()
    payload = build_execution_prompt_payload(
        module_id="SEO",
        capability="reasoning",
        model="model.reasoning.primary_v1",
        key="ai.binding.reasoning.primary",
        context={"task": "draft safe copy"},
    )

    assert template.required_inputs == (
        "module_id",
        "capability",
        "model",
        "key",
        "context",
    )
    assert template.render_policy == "deterministic_static_template_only"
    assert template.prompt_generation_executes_ai is False
    assert injection.injection_order == (
        "C14X-A key binding",
        "C14X-B model lock",
        "C14X-C capability routing",
        "C14X-D module allocation",
    )
    assert injection.fallback_binding_allowed is False
    assert assembly.required_context_blocks == (
        "module_context",
        "capability_context",
        "model_context",
        "security_constraints",
        "input_context",
    )
    assert security.raw_secret_allowed is False
    assert security.external_dependency_default_decision == "deny"
    assert validation.valid is True
    assert completion.c14x_system_fully_complete_answer == "YES"
    assert payload.generation_status == "rejected"
    assert payload.rejection_code == "c14x_e_key_binding_missing"
    assert payload.ai_execution_prompt is None
    assert payload.c09_compatible_payload is None
    assert payload.no_runtime_execution is True
    assert payload.no_model_invocation is True
    assert payload.no_external_api_call is True


def test_c14x_e_explicit_bindings_generate_prompt_context_and_c09_payload() -> None:
    result = build_execution_prompt_payload(
        module_id="SEO",
        capability="reasoning",
        model="model.reasoning.primary_v1",
        key="ai.binding.reasoning.primary",
        context={"task": "draft safe product review notes", "locale": "en"},
        requested_units=10,
        current_window_units=20,
        raw_ai_bindings=[c14x_a_binding()],
        raw_locks=[c14x_b_lock()],
        raw_capability_bindings=[c14x_c_capability_binding()],
        raw_module_capability_bindings=[c14x_c_module_binding()],
        raw_module_allocations=[c14x_d_allocation()],
    )

    assert result.generation_status == "generated"
    assert result.generation_allowed is True
    assert result.binding_injection.all_bindings_injected is True
    assert result.binding_injection.exact_binding_match is True
    assert result.binding_injection.active_binding_match is True
    assert result.binding_injection.execution_rejected is False
    assert result.binding_injection.key_binding is not None
    assert result.binding_injection.model_lock is not None
    assert result.binding_injection.capability_route is not None
    assert result.binding_injection.module_allocation is not None
    assert result.structured_input_context is not None
    assert result.ai_execution_prompt is not None
    assert result.c09_compatible_payload is not None

    context = result.structured_input_context
    prompt = result.ai_execution_prompt
    c09_payload = result.c09_compatible_payload
    assert context.module_context.module_id == "SEO"
    assert context.module_context.routed_module == "business.products"
    assert context.module_context.budget_remaining_units == 70
    assert context.capability_context.routing_path == (
        "reasoning",
        "ai.binding.reasoning.primary",
        "model.reasoning.primary_v1",
        "business.products",
    )
    assert context.model_context.locked_model_id == "model.reasoning.primary_v1"
    assert context.security_constraints.secret_in_prompt_allowed is False
    assert "C14X-E AI Execution Prompt" in prompt.prompt_text
    assert "C14X-A key binding: ai.binding.reasoning.primary" in prompt.prompt_text
    assert prompt.prompt_executes_ai is False
    assert prompt.runtime_execution_allowed is False
    assert c09_payload.module_key == "business.products"
    assert c09_payload.c09_contract_shape == (
        "ExecutionRequestContractV1_compatible_draft"
    )
    assert c09_payload.execution_requested is False
    assert c09_payload.can_submit_to_c09 is False
    assert c09_payload.creates_execution_request is False
    assert c09_payload.input_payload["prompt_id"] == prompt.prompt_id
    assert c09_payload.sanitized_input_summary["execution_requested"] is False
    assert c09_payload.no_runtime_execution is True
    assert c09_payload.no_external_api_call is True


def test_c14x_e_rejects_sensitive_context_and_binding_mismatch() -> None:
    unsafe = build_execution_prompt_payload(
        module_id="SEO",
        capability="reasoning",
        model="model.reasoning.primary_v1",
        key="ai.binding.reasoning.primary",
        context={"token": "token:secret"},
    )
    mismatch = build_execution_prompt_payload(
        module_id="SEO",
        capability="reasoning",
        model="model.reasoning.secondary_v1",
        key="ai.binding.reasoning.primary",
        context={"task": "safe"},
        raw_ai_bindings=[c14x_a_binding()],
        raw_locks=[c14x_b_lock()],
        raw_capability_bindings=[c14x_c_capability_binding()],
        raw_module_capability_bindings=[c14x_c_module_binding()],
        raw_module_allocations=[c14x_d_allocation()],
    )

    assert unsafe.generation_status == "rejected"
    assert unsafe.rejection_code == "c14x_e_prompt_input_invalid"
    assert unsafe.binding_injection.execution_rejected is True
    assert mismatch.generation_status == "rejected"
    assert mismatch.rejection_code == "c14x_e_key_binding_mismatch"
    assert mismatch.no_runtime_execution is True
    assert mismatch.no_external_api_call is True


def test_c14x_e_schema_requires_prompt_no_execute_flags() -> None:
    prompt = AIExecutionPrompt.model_validate(
        {
            "prompt_id": "c14x_e_prompt_example",
            "module_id": "SEO",
            "capability": "reasoning",
            "key": "ai.binding.reasoning.primary",
            "model": "model.reasoning.primary_v1",
            "prompt_text": "Safe prompt text.",
        }
    )

    assert prompt.prompt_is_contract_only is True
    assert prompt.prompt_executes_ai is False
    assert prompt.runtime_execution_allowed is False
    assert prompt.model_invocation_allowed is False
    assert prompt.external_api_call_allowed is False


def test_c14x_e_router_exposes_only_read_contract_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/api/control-plane/execution-prompts")
    ]

    assert ("/api/control-plane/execution-prompts/template-engine", {"GET"}) in routes
    assert ("/api/control-plane/execution-prompts/binding-injection", {"GET"}) in routes
    assert ("/api/control-plane/execution-prompts/context-assembly", {"GET"}) in routes
    assert ("/api/control-plane/execution-prompts/security-constraints", {"GET"}) in routes
    assert ("/api/control-plane/execution-prompts/payload", {"GET"}) in routes
    assert ("/api/control-plane/execution-prompts/validation", {"GET"}) in routes
    assert ("/api/control-plane/execution-prompts/completion-status", {"GET"}) in routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|run|sync|invoke|submit)\b", path)
        for path, _ in routes
    )
