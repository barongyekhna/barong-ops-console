from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import ValidationError

from ..core.capability_bindings import (
    CAPABILITY_BINDINGS_V1,
    MODULE_CAPABILITY_BINDINGS_V1,
)
from ..schemas.ai_execution_binding import (
    AIExecutionBindingRecord,
    AIExecutionCapability,
)
from ..schemas.capability_binding import (
    CapabilityBindingCompletionStatus,
    CapabilityBindingEnforcementStrategy,
    CapabilityBindingIntegrationModel,
    CapabilityBindingRecord,
    CapabilityBindingRequestValidationResult,
    CapabilityBindingValidationIssue,
    CapabilityBindingValidationResult,
    CapabilityModelMapping,
    CapabilityModelMappingResponse,
    CapabilityRoutePath,
    CapabilityRoutingModel,
    ModuleCapabilityBindingRecord,
    ModuleCapabilityBindingRulesResponse,
)
from ..schemas.model_lock import ModelLockRegistryRecord
from .ai_execution_binding_registry import (
    AI_BINDING_KEY_PATTERN,
    AI_MODEL_REF_PATTERN,
    ALLOWED_AI_EXECUTION_BINDING_STATUSES,
    ALLOWED_AI_EXECUTION_CAPABILITIES,
    SENSITIVE_AI_BINDING_MARKERS,
    validate_ai_execution_binding_registry,
)
from .model_lock_registry import validate_model_lock_registry
from .module_registry import MODULE_KEY_PATTERN, list_module_manifests


INVALID_REQUEST_CAPABILITY = "[invalid_capability]"
INVALID_REQUEST_KEY = "[invalid_key]"
INVALID_REQUEST_MODEL = "[invalid_model]"
INVALID_REQUEST_MODULE = "[invalid_module]"


def _capability_binding_from_raw(
    raw: CapabilityBindingRecord | Mapping[str, Any],
) -> CapabilityBindingRecord:
    if isinstance(raw, CapabilityBindingRecord):
        return raw
    return CapabilityBindingRecord.model_validate(raw)


def _module_capability_binding_from_raw(
    raw: ModuleCapabilityBindingRecord | Mapping[str, Any],
) -> ModuleCapabilityBindingRecord:
    if isinstance(raw, ModuleCapabilityBindingRecord):
        return raw
    return ModuleCapabilityBindingRecord.model_validate(raw)


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


def _validate_safe_values(binding_id: str, payload: Mapping[str, Any]) -> None:
    for value in _iter_string_values(payload):
        if _contains_sensitive_marker(value):
            raise ValueError(f"{binding_id} contains sensitive runtime data.")


def _validate_key(key: str) -> None:
    if not AI_BINDING_KEY_PATTERN.fullmatch(key):
        raise ValueError("Capability binding key is invalid.")
    if _contains_sensitive_marker(key):
        raise ValueError("Capability binding key contains a blocked marker.")


def _validate_model(model: str) -> None:
    if not AI_MODEL_REF_PATTERN.fullmatch(model):
        raise ValueError("Capability binding model is invalid.")
    if _contains_sensitive_marker(model):
        raise ValueError("Capability binding model contains a blocked marker.")


def _validate_module(module: str, module_keys: set[str]) -> None:
    if not MODULE_KEY_PATTERN.fullmatch(module):
        raise ValueError("Capability binding module is invalid.")
    if module not in module_keys:
        raise ValueError("Capability binding module is not registered.")
    if _contains_sensitive_marker(module):
        raise ValueError("Capability binding module contains a blocked marker.")


def _validate_capability(capability: str) -> None:
    if capability not in ALLOWED_AI_EXECUTION_CAPABILITIES:
        raise ValueError(f"Capability binding has invalid capability: {capability}")


def _validated_ai_bindings(
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> list[AIExecutionBindingRecord]:
    return validate_ai_execution_binding_registry(raw_bindings)


def _validated_model_locks(
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
    raw_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
) -> list[ModelLockRegistryRecord]:
    return validate_model_lock_registry(raw_locks, raw_bindings)


def validate_module_capability_bindings(
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
) -> list[ModuleCapabilityBindingRecord]:
    source = (
        raw_module_bindings
        if raw_module_bindings is not None
        else MODULE_CAPABILITY_BINDINGS_V1
    )
    bindings = [_module_capability_binding_from_raw(raw) for raw in source]
    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    seen_modules: set[str] = set()
    seen_capabilities: dict[str, str] = {}

    for binding in bindings:
        _validate_module(binding.module, module_keys)
        if binding.module in seen_modules:
            raise ValueError(
                f"Duplicate module capability binding: {binding.module}"
            )

        for capability in binding.allowed_capabilities:
            _validate_capability(capability)
            existing_module = seen_capabilities.get(capability)
            if existing_module is not None:
                raise ValueError(
                    "Capability drift violation: "
                    f"{capability} is allowed by both {existing_module} "
                    f"and {binding.module}."
                )
            seen_capabilities[capability] = binding.module

        seen_modules.add(binding.module)
        _validate_safe_values(binding.module, binding.model_dump(mode="json"))

    return bindings


def validate_capability_binding_engine(
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
) -> tuple[
    list[CapabilityBindingRecord],
    list[ModuleCapabilityBindingRecord],
    list[AIExecutionBindingRecord],
    list[ModelLockRegistryRecord],
]:
    source = (
        raw_capability_bindings
        if raw_capability_bindings is not None
        else CAPABILITY_BINDINGS_V1
    )
    capability_bindings = [
        _capability_binding_from_raw(raw) for raw in source
    ]
    module_bindings = validate_module_capability_bindings(raw_module_bindings)
    ai_bindings = _validated_ai_bindings(raw_ai_bindings)
    locks = _validated_model_locks(raw_locks, raw_ai_bindings)
    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    ai_binding_by_key = {binding.key: binding for binding in ai_bindings}
    lock_by_key = {lock.key_id: lock for lock in locks}
    module_binding_by_module = {
        binding.module: binding for binding in module_bindings
    }
    seen_keys: set[str] = set()
    seen_models: set[str] = set()
    seen_capabilities: set[str] = set()
    seen_modules: set[str] = set()

    for binding in capability_bindings:
        _validate_capability(binding.capability)
        _validate_key(binding.key)
        _validate_model(binding.model)
        _validate_module(binding.module, module_keys)
        if binding.status not in ALLOWED_AI_EXECUTION_BINDING_STATUSES:
            raise ValueError(f"{binding.key} has invalid status.")
        if binding.key in seen_keys:
            raise ValueError(f"Duplicate capability binding key: {binding.key}")
        if binding.model in seen_models:
            raise ValueError(
                f"Capability model binding drift violation: {binding.model}"
            )
        if binding.capability in seen_capabilities:
            raise ValueError(
                "Duplicate capability route binding: "
                f"{binding.capability}"
            )
        if binding.module in seen_modules:
            raise ValueError(
                f"Capability module binding drift violation: {binding.module}"
            )

        upstream_binding = ai_binding_by_key.get(binding.key)
        if upstream_binding is None:
            raise ValueError(
                f"{binding.key} is not registered in C14X-A bindings."
            )
        if upstream_binding.model != binding.model:
            raise ValueError(
                "C14X-A/C14X-C model mismatch: "
                f"{binding.key} binds {upstream_binding.model} upstream "
                f"but maps {binding.model} in C14X-C."
            )
        if upstream_binding.capability != binding.capability:
            raise ValueError(
                "C14X-A/C14X-C capability mismatch: "
                f"{binding.key} binds {upstream_binding.capability} "
                f"upstream but maps {binding.capability} in C14X-C."
            )
        if upstream_binding.module != binding.module:
            raise ValueError(
                "C14X-A/C14X-C module mismatch: "
                f"{binding.key} binds {upstream_binding.module} upstream "
                f"but maps {binding.module} in C14X-C."
            )
        if upstream_binding.status != binding.status:
            raise ValueError(
                "C14X-A/C14X-C status mismatch: "
                f"{binding.key} is {upstream_binding.status} upstream "
                f"but {binding.status} in C14X-C."
            )

        lock = lock_by_key.get(binding.key)
        if lock is None:
            raise ValueError(
                f"{binding.key} is missing a C14X-B model lock."
            )
        if lock.model_id != binding.model:
            raise ValueError(
                "C14X-B/C14X-C model lock mismatch: "
                f"{binding.key} locks {lock.model_id} but maps "
                f"{binding.model} in C14X-C."
            )

        module_binding = module_binding_by_module.get(binding.module)
        if module_binding is None or module_binding.status != "active":
            raise ValueError(
                f"{binding.module} is missing an active module capability binding."
            )
        if binding.capability not in module_binding.allowed_capabilities:
            raise ValueError(
                "Module capability binding does not allow capability: "
                f"{binding.module} -> {binding.capability}."
            )

        seen_keys.add(binding.key)
        seen_models.add(binding.model)
        seen_capabilities.add(binding.capability)
        seen_modules.add(binding.module)
        _validate_safe_values(binding.key, binding.model_dump(mode="json"))

    missing_capability_bindings = [
        binding.key for binding in ai_bindings if binding.key not in seen_keys
    ]
    if missing_capability_bindings:
        raise ValueError(
            "C14X-A binding missing C14X-C capability binding: "
            f"{', '.join(missing_capability_bindings)}"
        )

    for module_binding in module_bindings:
        if module_binding.status != "active":
            continue
        for capability in module_binding.allowed_capabilities:
            if capability not in seen_capabilities:
                raise ValueError(
                    "Module capability binding without explicit capability "
                    f"route: {module_binding.module} -> {capability}."
                )

    return capability_bindings, module_bindings, ai_bindings, locks


def build_capability_routing_model(
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
) -> CapabilityRoutingModel:
    capability_bindings, _, _, locks = validate_capability_binding_engine(
        raw_capability_bindings,
        raw_module_bindings,
        raw_ai_bindings,
        raw_locks,
    )
    lock_by_key = {lock.key_id: lock for lock in locks}
    routes = [
        CapabilityRoutePath(
            capability=binding.capability,
            key=binding.key,
            model=binding.model,
            module=binding.module,
            status=binding.status,
            c14x_b_locked_model_id=lock_by_key[binding.key].model_id,
            routing_path=(
                binding.capability,
                binding.key,
                binding.model,
                binding.module,
            ),
        )
        for binding in capability_bindings
    ]
    return CapabilityRoutingModel(
        routes=routes,
        count=len(routes),
        active_count=sum(1 for route in routes if route.status == "active"),
    )


def build_capability_model_mapping(
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
) -> CapabilityModelMappingResponse:
    capability_bindings, _, _, locks = validate_capability_binding_engine(
        raw_capability_bindings,
        raw_module_bindings,
        raw_ai_bindings,
        raw_locks,
    )
    lock_by_key = {lock.key_id: lock for lock in locks}
    items = [
        CapabilityModelMapping(
            capability=binding.capability,
            model=binding.model,
            key=binding.key,
            module=binding.module,
            locked_model_id=lock_by_key[binding.key].model_id,
            mapping_path=(
                binding.capability,
                binding.model,
                binding.key,
                binding.module,
            ),
        )
        for binding in capability_bindings
    ]
    return CapabilityModelMappingResponse(items=items, count=len(items))


def list_module_capability_binding_rules(
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
) -> ModuleCapabilityBindingRulesResponse:
    _, module_bindings, _, _ = validate_capability_binding_engine(
        raw_capability_bindings,
        raw_module_bindings,
        raw_ai_bindings,
        raw_locks,
    )
    return ModuleCapabilityBindingRulesResponse(
        items=module_bindings,
        count=len(module_bindings),
        active_count=sum(
            1 for binding in module_bindings if binding.status == "active"
        ),
    )


def get_capability_binding_enforcement_strategy() -> CapabilityBindingEnforcementStrategy:
    return CapabilityBindingEnforcementStrategy()


def _validation_issue(
    *,
    code: str,
    message: str,
    capability: AIExecutionCapability | None = None,
    key: str | None = None,
    model: str | None = None,
    module: str | None = None,
    severity: str = "error",
) -> CapabilityBindingValidationIssue:
    return CapabilityBindingValidationIssue(
        severity=severity,
        code=code,
        message=message,
        capability=capability,
        key=key,
        model=model,
        module=module,
    )


def build_capability_binding_validation_result(
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
) -> CapabilityBindingValidationResult:
    c14x_a_binding_count = 0
    c14x_b_lock_count = 0
    try:
        ai_bindings = _validated_ai_bindings(raw_ai_bindings)
        c14x_a_binding_count = len(ai_bindings)
        locks = _validated_model_locks(raw_locks, raw_ai_bindings)
        c14x_b_lock_count = len(locks)
        capability_bindings, module_bindings, _, _ = (
            validate_capability_binding_engine(
                raw_capability_bindings,
                raw_module_bindings,
                raw_ai_bindings,
                raw_locks,
            )
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return CapabilityBindingValidationResult(
            valid=False,
            issues=[
                _validation_issue(
                    code="c14x_c_capability_binding_invalid",
                    message=str(exc),
                )
            ],
            capability_binding_count=0,
            active_capability_binding_count=0,
            module_binding_count=0,
            active_module_binding_count=0,
            c14x_a_binding_count=c14x_a_binding_count,
            c14x_b_lock_count=c14x_b_lock_count,
            route_count=0,
        )

    return CapabilityBindingValidationResult(
        valid=True,
        issues=[],
        capability_binding_count=len(capability_bindings),
        active_capability_binding_count=sum(
            1 for binding in capability_bindings if binding.status == "active"
        ),
        module_binding_count=len(module_bindings),
        active_module_binding_count=sum(
            1 for binding in module_bindings if binding.status == "active"
        ),
        c14x_a_binding_count=len(ai_bindings),
        c14x_b_lock_count=len(locks),
        route_count=len(capability_bindings),
    )


def _safe_request_capability(capability: str) -> AIExecutionCapability | None:
    if capability not in ALLOWED_AI_EXECUTION_CAPABILITIES:
        return None
    if _contains_sensitive_marker(capability):
        return None
    return cast(AIExecutionCapability, capability)


def _safe_request_key(key: str) -> str | None:
    if not AI_BINDING_KEY_PATTERN.fullmatch(key):
        return None
    if _contains_sensitive_marker(key):
        return None
    return key


def _safe_request_model(model: str) -> str | None:
    if not AI_MODEL_REF_PATTERN.fullmatch(model):
        return None
    if _contains_sensitive_marker(model):
        return None
    return model


def _safe_request_module(module: str) -> str | None:
    if not MODULE_KEY_PATTERN.fullmatch(module):
        return None
    if _contains_sensitive_marker(module):
        return None
    return module


def _request_rejection(
    *,
    capability: str,
    key: str,
    requested_model_id: str,
    module: str,
    rejection_code: str,
    rejection_reason: str,
    bound_model_id: str | None = None,
    locked_model_id: str | None = None,
) -> CapabilityBindingRequestValidationResult:
    return CapabilityBindingRequestValidationResult(
        capability=capability,
        key=key,
        requested_model_id=requested_model_id,
        module=module,
        bound_model_id=bound_model_id,
        locked_model_id=locked_model_id,
        valid=False,
        capability_binding_validation_passed=False,
        module_capability_binding_passed=False,
        model_lock_validation_passed=False,
        execution_rejected=True,
        rejection_code=rejection_code,
        rejection_reason=rejection_reason,
    )


def validate_capability_binding_request(
    *,
    capability: str,
    key: str,
    requested_model_id: str,
    module: str,
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
) -> CapabilityBindingRequestValidationResult:
    safe_capability = _safe_request_capability(capability)
    safe_key = _safe_request_key(key)
    safe_requested_model_id = _safe_request_model(requested_model_id)
    safe_module = _safe_request_module(module)
    if (
        safe_capability is None
        or safe_key is None
        or safe_requested_model_id is None
        or safe_module is None
    ):
        return _request_rejection(
            capability=safe_capability or INVALID_REQUEST_CAPABILITY,
            key=safe_key or INVALID_REQUEST_KEY,
            requested_model_id=(
                safe_requested_model_id or INVALID_REQUEST_MODEL
            ),
            module=safe_module or INVALID_REQUEST_MODULE,
            rejection_code="c14x_c_capability_binding_request_invalid",
            rejection_reason=(
                "Execution rejected because the request capability, key, "
                "model, or module does not match the C14X-C identifier "
                "policy."
            ),
        )

    try:
        capability_bindings, module_bindings, _, locks = (
            validate_capability_binding_engine(
                raw_capability_bindings,
                raw_module_bindings,
                raw_ai_bindings,
                raw_locks,
            )
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return _request_rejection(
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            module=safe_module,
            rejection_code="c14x_c_capability_binding_registry_invalid",
            rejection_reason=(
                "Execution rejected because the C14X-C capability binding "
                f"engine is invalid: {exc}"
            ),
        )

    binding_by_capability = {
        binding.capability: binding for binding in capability_bindings
    }
    lock_by_key = {lock.key_id: lock for lock in locks}
    module_binding_by_module = {
        binding.module: binding for binding in module_bindings
    }
    binding = binding_by_capability.get(safe_capability)
    if binding is None:
        return _request_rejection(
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            module=safe_module,
            rejection_code="c14x_c_capability_binding_missing",
            rejection_reason=(
                "Execution rejected because no explicit capability binding "
                "exists; fallback capability routing is forbidden."
            ),
        )

    lock = lock_by_key.get(binding.key)
    locked_model_id = lock.model_id if lock is not None else None
    if binding.key != safe_key:
        return _request_rejection(
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            module=safe_module,
            bound_model_id=binding.model,
            locked_model_id=locked_model_id,
            rejection_code="c14x_c_capability_key_mismatch",
            rejection_reason=(
                "Execution rejected because requested key does not match "
                "the explicit capability binding; auto routing is forbidden."
            ),
        )

    if binding.module != safe_module:
        return _request_rejection(
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            module=safe_module,
            bound_model_id=binding.model,
            locked_model_id=locked_model_id,
            rejection_code="c14x_c_capability_module_mismatch",
            rejection_reason=(
                "Execution rejected because requested module does not match "
                "the explicit capability binding; implicit module access is "
                "forbidden."
            ),
        )

    if binding.model != safe_requested_model_id:
        return _request_rejection(
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            module=safe_module,
            bound_model_id=binding.model,
            locked_model_id=locked_model_id,
            rejection_code="c14x_c_capability_model_mismatch",
            rejection_reason=(
                "Execution rejected because requested model does not match "
                "the explicit capability binding and C14X-B model lock; "
                "model auto-switching is forbidden."
            ),
        )

    module_binding = module_binding_by_module.get(safe_module)
    if (
        module_binding is None
        or module_binding.status != "active"
        or safe_capability not in module_binding.allowed_capabilities
    ):
        return _request_rejection(
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            module=safe_module,
            bound_model_id=binding.model,
            locked_model_id=locked_model_id,
            rejection_code="c14x_c_module_capability_not_allowed",
            rejection_reason=(
                "Execution rejected because the module does not explicitly "
                "allow this capability."
            ),
        )

    return CapabilityBindingRequestValidationResult(
        capability=safe_capability,
        key=safe_key,
        requested_model_id=safe_requested_model_id,
        module=safe_module,
        bound_model_id=binding.model,
        locked_model_id=locked_model_id,
        valid=True,
        capability_binding_validation_passed=True,
        module_capability_binding_passed=True,
        model_lock_validation_passed=True,
        execution_rejected=False,
        rejection_code=None,
        rejection_reason=(
            "Capability binding validation passed. This does not grant "
            "runtime execution, model invocation, fallback routing, or "
            "external API access."
        ),
    )


def get_capability_binding_integration_model() -> CapabilityBindingIntegrationModel:
    return CapabilityBindingIntegrationModel()


def get_capability_binding_completion_status() -> CapabilityBindingCompletionStatus:
    return CapabilityBindingCompletionStatus(
        proceed_reason=(
            "C14X-C defines explicit capability routing, capability -> model "
            "mapping, module capability binding rules, and C14X-A/C14X-B "
            "integration without runtime execution."
        )
    )
