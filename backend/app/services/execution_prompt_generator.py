from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import ValidationError

from ..schemas.ai_execution_binding import (
    AIExecutionBindingRecord,
    AIExecutionCapability,
)
from ..schemas.capability_binding import (
    CapabilityBindingRecord,
    ModuleCapabilityBindingRecord,
)
from ..schemas.execution_prompt import (
    AIExecutionPrompt,
    C09CompatibleExecutionPromptPayload,
    ExecutionPromptBindingInjection,
    ExecutionPromptBindingInjectionModel,
    ExecutionPromptCapabilityContext,
    ExecutionPromptCompletionStatus,
    ExecutionPromptContextAssemblyRules,
    ExecutionPromptGenerationResult,
    ExecutionPromptModelContext,
    ExecutionPromptModuleContext,
    ExecutionPromptSecurityConstraints,
    ExecutionPromptStructuredInputContext,
    ExecutionPromptTemplateEngineDesign,
    ExecutionPromptValidationIssue,
    ExecutionPromptValidationResult,
)
from ..schemas.model_lock import ModelLockRegistryRecord
from ..schemas.module_allocation import (
    ModuleAllocationModuleId,
    ModuleAllocationRecord,
)
from .ai_execution_binding_registry import (
    AI_BINDING_KEY_PATTERN,
    AI_MODEL_REF_PATTERN,
    ALLOWED_AI_EXECUTION_CAPABILITIES,
    SENSITIVE_AI_BINDING_MARKERS,
    validate_ai_execution_binding_registry,
)
from .capability_binding_engine import (
    INVALID_REQUEST_MODULE,
    validate_capability_binding_engine,
    validate_capability_binding_request,
)
from .model_lock_registry import (
    validate_model_lock_registry,
    validate_model_lock_request,
)
from .module_allocation_system import (
    ALLOWED_MODULE_ALLOCATION_IDS,
    validate_module_allocation_registry,
    validate_module_allocation_request,
)


SENSITIVE_PROMPT_CONTEXT_KEY_MARKERS = (
    "api_key",
    "authorization",
    "bearer",
    "credential",
    "password",
    "provider_url",
    "secret",
    "token",
    "webhook_url",
)


def get_execution_prompt_template_engine_design() -> ExecutionPromptTemplateEngineDesign:
    return ExecutionPromptTemplateEngineDesign()


def get_execution_prompt_binding_injection_model() -> ExecutionPromptBindingInjectionModel:
    return ExecutionPromptBindingInjectionModel()


def get_execution_prompt_security_constraints() -> ExecutionPromptSecurityConstraints:
    return ExecutionPromptSecurityConstraints()


def get_execution_prompt_context_assembly_rules() -> ExecutionPromptContextAssemblyRules:
    return ExecutionPromptContextAssemblyRules()


def _iter_string_values(value: Any):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_string_values(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _iter_string_values(item)


def _iter_mapping_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _iter_mapping_keys(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _iter_mapping_keys(item)


def _contains_sensitive_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SENSITIVE_AI_BINDING_MARKERS)


def _contains_sensitive_context_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        marker in lowered for marker in SENSITIVE_PROMPT_CONTEXT_KEY_MARKERS
    )


def _safe_context(context: Mapping[str, Any] | str | None) -> dict[str, Any]:
    if context is None:
        safe_context: dict[str, Any] = {}
    elif isinstance(context, str):
        safe_context = {"request_context": context}
    elif isinstance(context, Mapping):
        safe_context = dict(context)
    else:
        raise ValueError("Execution prompt context must be a mapping or string.")

    try:
        json.dumps(safe_context, sort_keys=True, ensure_ascii=True)
    except TypeError as exc:
        raise ValueError(
            "Execution prompt context must be JSON serializable."
        ) from exc

    for key in _iter_mapping_keys(safe_context):
        if _contains_sensitive_context_key(key):
            raise ValueError(
                "Execution prompt context contains sensitive runtime data."
            )

    for value in _iter_string_values(safe_context):
        if _contains_sensitive_marker(value):
            raise ValueError(
                "Execution prompt context contains sensitive runtime data."
            )

    return safe_context


def _safe_generation_inputs(
    *,
    module_id: str,
    capability: str,
    model: str,
    key: str,
) -> tuple[ModuleAllocationModuleId, AIExecutionCapability]:
    if module_id not in ALLOWED_MODULE_ALLOCATION_IDS:
        raise ValueError("Execution prompt module_id is invalid.")
    if capability not in ALLOWED_AI_EXECUTION_CAPABILITIES:
        raise ValueError("Execution prompt capability is invalid.")
    if not AI_MODEL_REF_PATTERN.fullmatch(model):
        raise ValueError("Execution prompt model is invalid.")
    if not AI_BINDING_KEY_PATTERN.fullmatch(key):
        raise ValueError("Execution prompt key is invalid.")
    if any(
        _contains_sensitive_marker(value)
        for value in (module_id, capability, model, key)
    ):
        raise ValueError("Execution prompt input contains a blocked marker.")
    return (
        cast(ModuleAllocationModuleId, module_id),
        cast(AIExecutionCapability, capability),
    )


def _validation_issue(
    *,
    code: str,
    message: str,
    severity: str = "error",
) -> ExecutionPromptValidationIssue:
    return ExecutionPromptValidationIssue(
        severity=severity,
        code=code,
        message=message,
    )


def _rejected_injection(
    *,
    key_binding: AIExecutionBindingRecord | None = None,
    model_lock: ModelLockRegistryRecord | None = None,
    capability_route: CapabilityBindingRecord | None = None,
    module_allocation: ModuleAllocationRecord | None = None,
    model_lock_validation: Any = None,
    capability_routing_validation: Any = None,
    module_allocation_validation: Any = None,
) -> ExecutionPromptBindingInjection:
    return ExecutionPromptBindingInjection(
        key_binding=key_binding,
        model_lock=model_lock,
        capability_route=capability_route,
        module_allocation=module_allocation,
        model_lock_validation=model_lock_validation,
        capability_routing_validation=capability_routing_validation,
        module_allocation_validation=module_allocation_validation,
        all_bindings_injected=False,
        exact_binding_match=False,
        active_binding_match=False,
        execution_rejected=True,
    )


def _reject_generation(
    *,
    code: str,
    reason: str,
    key_binding: AIExecutionBindingRecord | None = None,
    model_lock: ModelLockRegistryRecord | None = None,
    capability_route: CapabilityBindingRecord | None = None,
    module_allocation: ModuleAllocationRecord | None = None,
    model_lock_validation: Any = None,
    capability_routing_validation: Any = None,
    module_allocation_validation: Any = None,
) -> ExecutionPromptGenerationResult:
    return ExecutionPromptGenerationResult(
        generation_status="rejected",
        generation_allowed=False,
        rejection_code=code,
        rejection_reason=reason,
        binding_injection=_rejected_injection(
            key_binding=key_binding,
            model_lock=model_lock,
            capability_route=capability_route,
            module_allocation=module_allocation,
            model_lock_validation=model_lock_validation,
            capability_routing_validation=capability_routing_validation,
            module_allocation_validation=module_allocation_validation,
        ),
        issues=[
            _validation_issue(
                code=code,
                message=reason,
            )
        ],
    )


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _prompt_text(
    *,
    module_id: ModuleAllocationModuleId,
    capability: AIExecutionCapability,
    model: str,
    key: str,
    context: ExecutionPromptStructuredInputContext,
) -> str:
    context_json = json.dumps(
        context.input_context,
        sort_keys=True,
        ensure_ascii=True,
        indent=2,
    )
    return "\n".join(
        [
            "C14X-E AI Execution Prompt (contract-only)",
            "",
            "System boundary:",
            "- Generate a safe response plan from the supplied context only.",
            "- Do not perform runtime execution, model invocation, external API calls, production changes, staging changes, Docker, pytest, or git commit.",
            "- Do not request, reveal, infer, transform, or store secrets.",
            "",
            "Binding injection:",
            f"- C14X-A key binding: {key}",
            f"- C14X-B locked model: {context.model_context.locked_model_id}",
            f"- C14X-C capability route: {capability} -> {context.capability_context.module}",
            f"- C14X-D module allocation: {module_id}",
            "",
            "Assembled context:",
            f"- module_id: {module_id}",
            f"- routed_module: {context.module_context.routed_module}",
            f"- capability: {capability}",
            f"- model: {model}",
            f"- key: {key}",
            f"- budget_remaining_units: {context.module_context.budget_remaining_units}",
            f"- budget_window_seconds: {context.module_context.budget_window_seconds}",
            "",
            "Input context:",
            context_json,
            "",
            "Output contract:",
            "- Return only safe, non-secret, user-facing or operator-facing text.",
            "- Include no executable command, network request, credential, endpoint, token, or environment value.",
            "- Treat this prompt as draft payload content for inspection only; it is not a C09 execution request.",
        ]
    )


def _assembled_context(
    *,
    module_id: ModuleAllocationModuleId,
    capability: AIExecutionCapability,
    key: str,
    model: str,
    input_context: dict[str, Any],
    key_binding: AIExecutionBindingRecord,
    model_lock: ModelLockRegistryRecord,
    capability_route: CapabilityBindingRecord,
    module_allocation: ModuleAllocationRecord,
    module_allocation_validation: Any,
) -> ExecutionPromptStructuredInputContext:
    context_id = _stable_id(
        "c14x_e_context",
        {
            "module_id": module_id,
            "capability": capability,
            "key": key,
            "model": model,
            "input_context": input_context,
        },
    )
    return ExecutionPromptStructuredInputContext(
        context_id=context_id,
        module_context=ExecutionPromptModuleContext(
            module_id=module_id,
            routed_module=capability_route.module,
            allowed_capabilities=module_allocation.allowed_capabilities,
            bound_key=module_allocation.bound_key,
            bound_model=module_allocation.bound_model,
            allocation_status=module_allocation.status,
            requested_units=module_allocation_validation.requested_units,
            current_window_units=module_allocation_validation.current_window_units,
            budget_remaining_units=(
                module_allocation_validation.budget_remaining_units
            ),
            budget_window_seconds=(
                module_allocation_validation.budget_window_seconds
            ),
        ),
        capability_context=ExecutionPromptCapabilityContext(
            capability=capability,
            key=key_binding.key,
            model=key_binding.model,
            module=capability_route.module,
            status=capability_route.status,
            routing_path=(
                capability_route.capability,
                capability_route.key,
                capability_route.model,
                capability_route.module,
            ),
        ),
        model_context=ExecutionPromptModelContext(
            key_id=model_lock.key_id,
            requested_model_id=model,
            locked_model_id=model_lock.model_id,
            lock_timestamp=model_lock.lock_timestamp,
        ),
        security_constraints=get_execution_prompt_security_constraints(),
        input_context=input_context,
    )


def _c09_compatible_payload(
    *,
    payload_id: str,
    prompt: AIExecutionPrompt,
    context: ExecutionPromptStructuredInputContext,
) -> C09CompatibleExecutionPromptPayload:
    return C09CompatibleExecutionPromptPayload(
        payload_id=payload_id,
        module_key=context.capability_context.module,
        input_payload={
            "prompt_id": prompt.prompt_id,
            "prompt_text": prompt.prompt_text,
            "structured_input_context": context.model_dump(mode="json"),
        },
        sanitized_input_summary={
            "module_id": context.module_context.module_id,
            "module_key": context.capability_context.module,
            "capability": context.capability_context.capability,
            "key": context.capability_context.key,
            "model": context.capability_context.model,
            "locked_model_id": context.model_context.locked_model_id,
            "context_keys": sorted(context.input_context.keys()),
            "contract_only": True,
            "execution_requested": False,
        },
        not_submittable_reason=(
            "C14X-E builds an inspection-only prompt payload; C09 execution "
            "request creation, provider submission, model invocation, and "
            "runtime execution remain disabled."
        ),
    )


def build_execution_prompt_payload(
    *,
    module_id: str,
    capability: str,
    model: str,
    key: str,
    context: Mapping[str, Any] | str | None = None,
    requested_units: int = 1,
    current_window_units: int = 0,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]]
    | None = None,
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_capability_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_module_allocations: Sequence[ModuleAllocationRecord | Mapping[str, Any]]
    | None = None,
) -> ExecutionPromptGenerationResult:
    try:
        safe_module_id, safe_capability = _safe_generation_inputs(
            module_id=module_id,
            capability=capability,
            model=model,
            key=key,
        )
        safe_context = _safe_context(context)
    except ValueError as exc:
        return _reject_generation(
            code="c14x_e_prompt_input_invalid",
            reason=str(exc),
        )

    if requested_units <= 0 or current_window_units < 0:
        return _reject_generation(
            code="c14x_e_prompt_usage_invalid",
            reason=(
                "Execution prompt generation rejected because requested_units "
                "must be positive and current_window_units must be non-negative."
            ),
        )

    try:
        ai_bindings = validate_ai_execution_binding_registry(raw_ai_bindings)
        model_locks = validate_model_lock_registry(raw_locks, raw_ai_bindings)
        (
            capability_bindings,
            _module_capability_bindings,
            _validated_ai_bindings,
            _validated_model_locks,
        ) = validate_capability_binding_engine(
            raw_capability_bindings,
            raw_module_capability_bindings,
            raw_ai_bindings,
            raw_locks,
        )
        module_allocations = validate_module_allocation_registry(
            raw_module_allocations
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return _reject_generation(
            code="c14x_e_prompt_binding_registry_invalid",
            reason=(
                "Execution prompt generation rejected because an upstream "
                f"C14X binding registry is invalid: {exc}"
            ),
        )

    key_binding = next(
        (binding for binding in ai_bindings if binding.key == key),
        None,
    )
    if key_binding is None:
        return _reject_generation(
            code="c14x_e_key_binding_missing",
            reason=(
                "Execution prompt generation rejected because no exact "
                "C14X-A key binding exists; fallback binding is forbidden."
            ),
        )
    if key_binding.model != model or key_binding.capability != safe_capability:
        return _reject_generation(
            code="c14x_e_key_binding_mismatch",
            reason=(
                "Execution prompt generation rejected because the C14X-A "
                "key binding does not match the requested model and capability."
            ),
            key_binding=key_binding,
        )
    if key_binding.status != "active":
        return _reject_generation(
            code="c14x_e_key_binding_inactive",
            reason=(
                "Execution prompt generation rejected because the C14X-A "
                "key binding is not active."
            ),
            key_binding=key_binding,
        )

    model_lock_validation = validate_model_lock_request(
        key_id=key,
        requested_model_id=model,
        raw_locks=raw_locks,
        raw_bindings=raw_ai_bindings,
    )
    model_lock = next((lock for lock in model_locks if lock.key_id == key), None)
    if not model_lock_validation.valid or model_lock is None:
        return _reject_generation(
            code=model_lock_validation.rejection_code
            or "c14x_e_model_lock_invalid",
            reason=model_lock_validation.rejection_reason,
            key_binding=key_binding,
            model_lock=model_lock,
            model_lock_validation=model_lock_validation,
        )

    capability_route = next(
        (
            binding
            for binding in capability_bindings
            if binding.capability == safe_capability
        ),
        None,
    )
    capability_routing_validation = validate_capability_binding_request(
        capability=safe_capability,
        key=key,
        requested_model_id=model,
        module=capability_route.module
        if capability_route is not None
        else INVALID_REQUEST_MODULE,
        raw_capability_bindings=raw_capability_bindings,
        raw_module_bindings=raw_module_capability_bindings,
        raw_ai_bindings=raw_ai_bindings,
        raw_locks=raw_locks,
    )
    if (
        not capability_routing_validation.valid
        or capability_route is None
        or capability_route.status != "active"
    ):
        return _reject_generation(
            code=capability_routing_validation.rejection_code
            or "c14x_e_capability_route_inactive",
            reason=(
                capability_routing_validation.rejection_reason
                if not capability_routing_validation.valid
                else "Execution prompt generation rejected because the C14X-C capability route is not active."
            ),
            key_binding=key_binding,
            model_lock=model_lock,
            capability_route=capability_route,
            model_lock_validation=model_lock_validation,
            capability_routing_validation=capability_routing_validation,
        )

    module_allocation_validation = validate_module_allocation_request(
        module_id=safe_module_id,
        capability=safe_capability,
        key=key,
        requested_model_id=model,
        requested_units=requested_units,
        current_window_units=current_window_units,
        raw_allocations=raw_module_allocations,
    )
    module_allocation = next(
        (
            allocation
            for allocation in module_allocations
            if allocation.module_id == safe_module_id
        ),
        None,
    )
    if not module_allocation_validation.valid or module_allocation is None:
        return _reject_generation(
            code=module_allocation_validation.rejection_code
            or "c14x_e_module_allocation_invalid",
            reason=module_allocation_validation.rejection_reason,
            key_binding=key_binding,
            model_lock=model_lock,
            capability_route=capability_route,
            module_allocation=module_allocation,
            model_lock_validation=model_lock_validation,
            capability_routing_validation=capability_routing_validation,
            module_allocation_validation=module_allocation_validation,
        )

    structured_context = _assembled_context(
        module_id=safe_module_id,
        capability=safe_capability,
        key=key,
        model=model,
        input_context=safe_context,
        key_binding=key_binding,
        model_lock=model_lock,
        capability_route=capability_route,
        module_allocation=module_allocation,
        module_allocation_validation=module_allocation_validation,
    )
    prompt_id = _stable_id(
        "c14x_e_prompt",
        structured_context.model_dump(mode="json"),
    )
    prompt = AIExecutionPrompt(
        prompt_id=prompt_id,
        module_id=safe_module_id,
        capability=safe_capability,
        key=key,
        model=model,
        prompt_text=_prompt_text(
            module_id=safe_module_id,
            capability=safe_capability,
            model=model,
            key=key,
            context=structured_context,
        ),
    )
    payload_id = _stable_id(
        "c14x_e_payload",
        {
            "prompt_id": prompt.prompt_id,
            "context_id": structured_context.context_id,
            "module_key": structured_context.capability_context.module,
        },
    )
    c09_payload = _c09_compatible_payload(
        payload_id=payload_id,
        prompt=prompt,
        context=structured_context,
    )

    return ExecutionPromptGenerationResult(
        generation_status="generated",
        generation_allowed=True,
        rejection_code=None,
        rejection_reason=None,
        binding_injection=ExecutionPromptBindingInjection(
            key_binding=key_binding,
            model_lock=model_lock,
            capability_route=capability_route,
            module_allocation=module_allocation,
            model_lock_validation=model_lock_validation,
            capability_routing_validation=capability_routing_validation,
            module_allocation_validation=module_allocation_validation,
            all_bindings_injected=True,
            exact_binding_match=True,
            active_binding_match=True,
            execution_rejected=False,
        ),
        structured_input_context=structured_context,
        ai_execution_prompt=prompt,
        c09_compatible_payload=c09_payload,
        issues=[],
    )


def build_execution_prompt_validation_result() -> ExecutionPromptValidationResult:
    try:
        get_execution_prompt_template_engine_design()
        get_execution_prompt_binding_injection_model()
        get_execution_prompt_context_assembly_rules()
        get_execution_prompt_security_constraints()
    except (TypeError, ValueError, ValidationError) as exc:
        return ExecutionPromptValidationResult(
            valid=False,
            issues=[
                _validation_issue(
                    code="c14x_e_execution_prompt_invalid",
                    message=str(exc),
                )
            ],
        )

    return ExecutionPromptValidationResult(valid=True, issues=[])


def get_execution_prompt_completion_status() -> ExecutionPromptCompletionStatus:
    return ExecutionPromptCompletionStatus(
        proceed_reason=(
            "C14X-E defines a deterministic prompt template engine, binding "
            "injection from C14X-A/B/C/D, structured context assembly, and a "
            "C09-compatible draft payload while preserving the no-execute "
            "C14/C14X boundary."
        )
    )
