from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from pydantic import ValidationError

from ..core.ai_execution_bindings import AI_EXECUTION_BINDINGS_V1
from ..schemas.ai_execution_binding import (
    AIExecutionBindingCompletionStatus,
    AIExecutionBindingRecord,
    AIExecutionBindingRegistryResponse,
    AIExecutionBindingRuleModel,
    AIExecutionBindingStatus,
    AIExecutionBindingUIInteractionModel,
    AIExecutionBindingValidationIssue,
    AIExecutionBindingValidationResult,
    AIExecutionCapability,
    AIExecutionFlowMapping,
    AIExecutionRoutePath,
)
from .module_registry import MODULE_KEY_PATTERN, list_module_manifests


AI_BINDING_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)+$"
)
AI_MODEL_REF_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
)
ALLOWED_AI_EXECUTION_CAPABILITIES = frozenset(get_args(AIExecutionCapability))
ALLOWED_AI_EXECUTION_BINDING_STATUSES = frozenset(
    get_args(AIExecutionBindingStatus)
)
SENSITIVE_AI_BINDING_MARKERS = (
    ".env",
    "api_key",
    "authorization",
    "bearer ",
    "credential",
    "credential=",
    "credential:",
    "http://",
    "https://",
    "password",
    "provider_url",
    "token=",
    "token:",
    "webhook_url",
    "://",
    "=",
)


def _binding_from_raw(
    raw: AIExecutionBindingRecord | Mapping[str, Any],
) -> AIExecutionBindingRecord:
    if isinstance(raw, AIExecutionBindingRecord):
        return raw
    return AIExecutionBindingRecord.model_validate(raw)


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


def _contains_sensitive_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SENSITIVE_AI_BINDING_MARKERS)


def _validate_safe_values(binding_key: str, payload: Mapping[str, Any]) -> None:
    for value in _iter_string_values(payload):
        if _contains_sensitive_marker(value):
            raise ValueError(f"{binding_key} contains sensitive runtime data.")


def _validate_binding_key(binding_key: str) -> None:
    if not AI_BINDING_KEY_PATTERN.fullmatch(binding_key):
        raise ValueError("AI execution binding key is invalid.")
    if _contains_sensitive_marker(binding_key):
        raise ValueError("AI execution binding key contains a blocked marker.")


def _validate_model_ref(model: str) -> None:
    if not AI_MODEL_REF_PATTERN.fullmatch(model):
        raise ValueError("AI execution binding model reference is invalid.")
    if _contains_sensitive_marker(model):
        raise ValueError("AI execution binding model contains a blocked marker.")


def _validate_module(module: str, module_keys: set[str]) -> None:
    if not MODULE_KEY_PATTERN.fullmatch(module):
        raise ValueError("AI execution binding module is invalid.")
    if module not in module_keys:
        raise ValueError("AI execution binding module is not registered.")


def validate_ai_execution_binding_registry(
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> list[AIExecutionBindingRecord]:
    source = raw_bindings if raw_bindings is not None else AI_EXECUTION_BINDINGS_V1
    bindings = [_binding_from_raw(raw) for raw in source]
    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    seen_keys: set[str] = set()
    seen_models: set[str] = set()
    seen_capabilities: set[str] = set()
    seen_modules: set[str] = set()

    for binding in bindings:
        _validate_binding_key(binding.key)
        _validate_model_ref(binding.model)
        _validate_module(binding.module, module_keys)
        if binding.capability not in ALLOWED_AI_EXECUTION_CAPABILITIES:
            raise ValueError(f"{binding.key} has invalid capability.")
        if binding.status not in ALLOWED_AI_EXECUTION_BINDING_STATUSES:
            raise ValueError(f"{binding.key} has invalid status.")
        if binding.key in seen_keys:
            raise ValueError(f"Duplicate AI execution binding key: {binding.key}")
        if binding.model in seen_models:
            raise ValueError(
                f"1:1 AI execution model binding violation: {binding.model}"
            )
        if binding.capability in seen_capabilities:
            raise ValueError(
                "1:1 AI execution capability binding violation: "
                f"{binding.capability}"
            )
        if binding.module in seen_modules:
            raise ValueError(
                f"1:1 AI execution module binding violation: {binding.module}"
            )

        seen_keys.add(binding.key)
        seen_models.add(binding.model)
        seen_capabilities.add(binding.capability)
        seen_modules.add(binding.module)
        _validate_safe_values(binding.key, binding.model_dump(mode="json"))

    return bindings


def list_ai_execution_binding_registry(
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> AIExecutionBindingRegistryResponse:
    bindings = validate_ai_execution_binding_registry(raw_bindings)
    return AIExecutionBindingRegistryResponse(
        items=bindings,
        count=len(bindings),
        active_count=sum(1 for binding in bindings if binding.status == "active"),
    )


def get_ai_execution_binding_rule_model() -> AIExecutionBindingRuleModel:
    return AIExecutionBindingRuleModel()


def _validation_issue(
    *,
    code: str,
    message: str,
    key: str | None = None,
    model: str | None = None,
    capability: AIExecutionCapability | None = None,
    module: str | None = None,
    severity: str = "error",
) -> AIExecutionBindingValidationIssue:
    return AIExecutionBindingValidationIssue(
        severity=severity,
        code=code,
        message=message,
        key=key,
        model=model,
        capability=capability,
        module=module,
    )


def build_ai_execution_binding_validation_result(
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> AIExecutionBindingValidationResult:
    try:
        bindings = validate_ai_execution_binding_registry(raw_bindings)
    except (TypeError, ValueError, ValidationError) as exc:
        return AIExecutionBindingValidationResult(
            valid=False,
            issues=[
                _validation_issue(
                    code="c14x_a_ai_execution_binding_invalid",
                    message=str(exc),
                )
            ],
            binding_count=0,
            active_binding_count=0,
            route_count=0,
        )

    return AIExecutionBindingValidationResult(
        valid=True,
        issues=[],
        binding_count=len(bindings),
        active_binding_count=sum(
            1 for binding in bindings if binding.status == "active"
        ),
        route_count=len(bindings),
    )


def build_ai_execution_flow_mapping(
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> AIExecutionFlowMapping:
    bindings = validate_ai_execution_binding_registry(raw_bindings)
    routes = [
        AIExecutionRoutePath(
            key=binding.key,
            model=binding.model,
            capability=binding.capability,
            module=binding.module,
            status=binding.status,
            routing_path=(
                binding.key,
                binding.model,
                binding.capability,
                binding.module,
            ),
        )
        for binding in bindings
    ]
    return AIExecutionFlowMapping(routes=routes, count=len(routes))


def get_ai_execution_binding_by_key(
    key: str,
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> AIExecutionBindingRecord | None:
    for binding in validate_ai_execution_binding_registry(raw_bindings):
        if binding.key == key:
            return binding
    return None


def get_ai_execution_binding_ui_interaction_model() -> AIExecutionBindingUIInteractionModel:
    return AIExecutionBindingUIInteractionModel()


def get_ai_execution_binding_completion_status() -> AIExecutionBindingCompletionStatus:
    return AIExecutionBindingCompletionStatus(
        proceed_reason=(
            "C14X-A defines a read-only AI execution binding registry and "
            "fixed routing-path rules without runtime execution."
        )
    )
