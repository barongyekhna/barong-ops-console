from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast, get_args

from pydantic import ValidationError

from ..core.module_allocations import MODULE_ALLOCATIONS_V1
from ..schemas.ai_execution_binding import AIExecutionCapability
from ..schemas.module_allocation import (
    ModuleAllocationAssignmentModel,
    ModuleAllocationBudgetItem,
    ModuleAllocationBudgetSystem,
    ModuleAllocationCategoryModel,
    ModuleAllocationCategoryRule,
    ModuleAllocationCompletionStatus,
    ModuleAllocationEnforcementRules,
    ModuleAllocationIntegrationFlow,
    ModuleAllocationModuleId,
    ModuleAllocationRecord,
    ModuleAllocationRegistryResponse,
    ModuleAllocationRequestValidationResult,
    ModuleAllocationValidationIssue,
    ModuleAllocationValidationResult,
    ModuleCapabilityBudget,
)
from .ai_execution_binding_registry import (
    AI_BINDING_KEY_PATTERN,
    AI_MODEL_REF_PATTERN,
    ALLOWED_AI_EXECUTION_BINDING_STATUSES,
    ALLOWED_AI_EXECUTION_CAPABILITIES,
    SENSITIVE_AI_BINDING_MARKERS,
)


MODULE_CATEGORY_CAPABILITIES: dict[ModuleAllocationModuleId, tuple[str, ...]] = {
    "K-series": ("writing", "reasoning"),
    "P-series": ("writing",),
    "SEO": ("serp", "reasoning"),
    "BS": ("serp", "reasoning", "writing", "embedding"),
}
ALLOWED_MODULE_ALLOCATION_IDS = frozenset(get_args(ModuleAllocationModuleId))
INVALID_REQUEST_MODULE_ID = "[invalid_module_id]"
INVALID_REQUEST_CAPABILITY = "[invalid_capability]"
INVALID_REQUEST_KEY = "[invalid_key]"
INVALID_REQUEST_MODEL = "[invalid_model]"


def _allocation_from_raw(
    raw: ModuleAllocationRecord | Mapping[str, Any],
) -> ModuleAllocationRecord:
    if isinstance(raw, ModuleAllocationRecord):
        return raw
    return ModuleAllocationRecord.model_validate(raw)


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


def _validate_safe_values(
    allocation_id: str,
    payload: Mapping[str, Any],
) -> None:
    for value in _iter_string_values(payload):
        if _contains_sensitive_marker(value):
            raise ValueError(f"{allocation_id} contains sensitive runtime data.")


def _validate_module_id(module_id: str) -> None:
    if module_id not in ALLOWED_MODULE_ALLOCATION_IDS:
        raise ValueError(f"Module allocation module_id is invalid: {module_id}")
    if _contains_sensitive_marker(module_id):
        raise ValueError("Module allocation module_id contains a blocked marker.")


def _validate_capability(capability: str) -> None:
    if capability not in ALLOWED_AI_EXECUTION_CAPABILITIES:
        raise ValueError(
            f"Module allocation has invalid capability: {capability}"
        )
    if _contains_sensitive_marker(capability):
        raise ValueError("Module allocation capability contains a blocked marker.")


def _validate_key(bound_key: str) -> None:
    if not AI_BINDING_KEY_PATTERN.fullmatch(bound_key):
        raise ValueError("Module allocation bound_key is invalid.")
    if _contains_sensitive_marker(bound_key):
        raise ValueError("Module allocation bound_key contains a blocked marker.")


def _validate_model(bound_model: str) -> None:
    if not AI_MODEL_REF_PATTERN.fullmatch(bound_model):
        raise ValueError("Module allocation bound_model is invalid.")
    if _contains_sensitive_marker(bound_model):
        raise ValueError(
            "Module allocation bound_model contains a blocked marker."
        )


def _validate_budget(
    allocation: ModuleAllocationRecord,
    budget: ModuleCapabilityBudget,
) -> None:
    if budget.capability not in allocation.allowed_capabilities:
        raise ValueError(
            "Module allocation budget references unassigned capability: "
            f"{allocation.module_id} -> {budget.capability}."
        )
    if budget.max_units_per_request > budget.max_units_per_window:
        raise ValueError(
            "Module allocation budget max_units_per_request cannot exceed "
            f"max_units_per_window for {allocation.module_id}."
        )


def _budget_by_capability(
    allocation: ModuleAllocationRecord,
) -> dict[AIExecutionCapability, ModuleCapabilityBudget]:
    budgets: dict[AIExecutionCapability, ModuleCapabilityBudget] = {}
    for budget in allocation.capability_budgets:
        if budget.capability in budgets:
            raise ValueError(
                "Duplicate module allocation capability budget: "
                f"{allocation.module_id} -> {budget.capability}."
            )
        _validate_budget(allocation, budget)
        budgets[budget.capability] = budget

    missing_budgets = [
        capability
        for capability in allocation.allowed_capabilities
        if capability not in budgets
    ]
    if missing_budgets:
        raise ValueError(
            "Module allocation missing capability budget: "
            f"{allocation.module_id} -> {', '.join(missing_budgets)}."
        )

    return budgets


def validate_module_allocation_registry(
    raw_allocations: Sequence[ModuleAllocationRecord | Mapping[str, Any]]
    | None = None,
) -> list[ModuleAllocationRecord]:
    source = raw_allocations if raw_allocations is not None else MODULE_ALLOCATIONS_V1
    allocations = [_allocation_from_raw(raw) for raw in source]
    seen_modules: set[str] = set()
    active_capability_owner: dict[str, str] = {}

    for allocation in allocations:
        _validate_module_id(allocation.module_id)
        _validate_key(allocation.bound_key)
        _validate_model(allocation.bound_model)
        if allocation.status not in ALLOWED_AI_EXECUTION_BINDING_STATUSES:
            raise ValueError(f"{allocation.module_id} has invalid status.")
        if allocation.module_id in seen_modules:
            raise ValueError(
                f"Duplicate module allocation: {allocation.module_id}"
            )

        allowed_by_category = set(MODULE_CATEGORY_CAPABILITIES[allocation.module_id])
        seen_capabilities: set[str] = set()
        for capability in allocation.allowed_capabilities:
            _validate_capability(capability)
            if capability in seen_capabilities:
                raise ValueError(
                    "Duplicate assigned capability in module allocation: "
                    f"{allocation.module_id} -> {capability}."
                )
            if capability not in allowed_by_category:
                raise ValueError(
                    "Module category capability violation: "
                    f"{allocation.module_id} cannot be assigned {capability}."
                )
            if allocation.status == "active":
                existing_module = active_capability_owner.get(capability)
                if existing_module is not None:
                    raise ValueError(
                        "Shared capability pool violation: "
                        f"{capability} is assigned to both {existing_module} "
                        f"and {allocation.module_id}."
                    )
                active_capability_owner[capability] = allocation.module_id
            seen_capabilities.add(capability)

        _budget_by_capability(allocation)
        seen_modules.add(allocation.module_id)
        _validate_safe_values(
            allocation.module_id,
            allocation.model_dump(mode="json"),
        )

    return allocations


def list_module_allocation_registry(
    raw_allocations: Sequence[ModuleAllocationRecord | Mapping[str, Any]]
    | None = None,
) -> ModuleAllocationRegistryResponse:
    allocations = validate_module_allocation_registry(raw_allocations)
    return ModuleAllocationRegistryResponse(
        items=allocations,
        count=len(allocations),
        active_count=sum(
            1 for allocation in allocations if allocation.status == "active"
        ),
    )


def get_module_allocation_assignment_model() -> ModuleAllocationAssignmentModel:
    return ModuleAllocationAssignmentModel()


def get_module_allocation_category_model() -> ModuleAllocationCategoryModel:
    items = [
        ModuleAllocationCategoryRule(
            module_id=cast(ModuleAllocationModuleId, module_id),
            allowed_capabilities=cast(
                tuple[AIExecutionCapability, ...],
                capabilities,
            ),
        )
        for module_id, capabilities in MODULE_CATEGORY_CAPABILITIES.items()
    ]
    return ModuleAllocationCategoryModel(items=items, count=len(items))


def build_module_allocation_budget_system(
    raw_allocations: Sequence[ModuleAllocationRecord | Mapping[str, Any]]
    | None = None,
) -> ModuleAllocationBudgetSystem:
    allocations = validate_module_allocation_registry(raw_allocations)
    items = [
        ModuleAllocationBudgetItem(
            module_id=allocation.module_id,
            capability=budget.capability,
            bound_key=allocation.bound_key,
            bound_model=allocation.bound_model,
            status=allocation.status,
            max_units_per_request=budget.max_units_per_request,
            max_units_per_window=budget.max_units_per_window,
            window_seconds=budget.window_seconds,
        )
        for allocation in allocations
        for budget in allocation.capability_budgets
    ]
    return ModuleAllocationBudgetSystem(items=items, count=len(items))


def get_module_allocation_enforcement_rules() -> ModuleAllocationEnforcementRules:
    return ModuleAllocationEnforcementRules()


def get_module_allocation_integration_flow() -> ModuleAllocationIntegrationFlow:
    return ModuleAllocationIntegrationFlow()


def _validation_issue(
    *,
    code: str,
    message: str,
    module_id: ModuleAllocationModuleId | None = None,
    capability: AIExecutionCapability | None = None,
    bound_key: str | None = None,
    bound_model: str | None = None,
    severity: str = "error",
) -> ModuleAllocationValidationIssue:
    return ModuleAllocationValidationIssue(
        severity=severity,
        code=code,
        message=message,
        module_id=module_id,
        capability=capability,
        bound_key=bound_key,
        bound_model=bound_model,
    )


def build_module_allocation_validation_result(
    raw_allocations: Sequence[ModuleAllocationRecord | Mapping[str, Any]]
    | None = None,
) -> ModuleAllocationValidationResult:
    try:
        allocations = validate_module_allocation_registry(raw_allocations)
    except (TypeError, ValueError, ValidationError) as exc:
        return ModuleAllocationValidationResult(
            valid=False,
            issues=[
                _validation_issue(
                    code="c14x_d_module_allocation_invalid",
                    message=str(exc),
                )
            ],
            allocation_count=0,
            active_allocation_count=0,
            budget_count=0,
        )

    return ModuleAllocationValidationResult(
        valid=True,
        issues=[],
        allocation_count=len(allocations),
        active_allocation_count=sum(
            1 for allocation in allocations if allocation.status == "active"
        ),
        budget_count=sum(
            len(allocation.capability_budgets) for allocation in allocations
        ),
    )


def _safe_request_module_id(module_id: str) -> ModuleAllocationModuleId | None:
    if module_id not in ALLOWED_MODULE_ALLOCATION_IDS:
        return None
    if _contains_sensitive_marker(module_id):
        return None
    return cast(ModuleAllocationModuleId, module_id)


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


def _request_rejection(
    *,
    module_id: str,
    capability: str,
    key: str,
    requested_model_id: str,
    requested_units: int,
    current_window_units: int,
    rejection_code: str,
    rejection_reason: str,
    bound_key: str | None = None,
    bound_model: str | None = None,
    budget_remaining_units: int | None = None,
    budget_window_seconds: int | None = None,
) -> ModuleAllocationRequestValidationResult:
    return ModuleAllocationRequestValidationResult(
        module_id=module_id,
        capability=capability,
        key=key,
        requested_model_id=requested_model_id,
        requested_units=max(requested_units, 0),
        current_window_units=max(current_window_units, 0),
        bound_key=bound_key,
        bound_model=bound_model,
        budget_remaining_units=budget_remaining_units,
        budget_window_seconds=budget_window_seconds,
        valid=False,
        allocation_validation_passed=False,
        capability_assignment_passed=False,
        budget_validation_passed=False,
        execution_rejected=True,
        rejection_code=rejection_code,
        rejection_reason=rejection_reason,
    )


def validate_module_allocation_request(
    *,
    module_id: str,
    capability: str,
    key: str,
    requested_model_id: str,
    requested_units: int,
    current_window_units: int = 0,
    raw_allocations: Sequence[ModuleAllocationRecord | Mapping[str, Any]]
    | None = None,
) -> ModuleAllocationRequestValidationResult:
    safe_module_id = _safe_request_module_id(module_id)
    safe_capability = _safe_request_capability(capability)
    safe_key = _safe_request_key(key)
    safe_requested_model_id = _safe_request_model(requested_model_id)
    if (
        safe_module_id is None
        or safe_capability is None
        or safe_key is None
        or safe_requested_model_id is None
        or requested_units < 0
        or current_window_units < 0
    ):
        return _request_rejection(
            module_id=safe_module_id or INVALID_REQUEST_MODULE_ID,
            capability=safe_capability or INVALID_REQUEST_CAPABILITY,
            key=safe_key or INVALID_REQUEST_KEY,
            requested_model_id=safe_requested_model_id or INVALID_REQUEST_MODEL,
            requested_units=requested_units,
            current_window_units=current_window_units,
            rejection_code="c14x_d_module_allocation_request_invalid",
            rejection_reason=(
                "Execution rejected because the request module, capability, "
                "key, model, or usage units do not match the C14X-D "
                "identifier and budget policy."
            ),
        )

    try:
        allocations = validate_module_allocation_registry(raw_allocations)
    except (TypeError, ValueError, ValidationError) as exc:
        return _request_rejection(
            module_id=safe_module_id,
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            requested_units=requested_units,
            current_window_units=current_window_units,
            rejection_code="c14x_d_module_allocation_registry_invalid",
            rejection_reason=(
                "Execution rejected because the C14X-D module allocation "
                f"registry is invalid: {exc}"
            ),
        )

    allocation_by_module = {
        allocation.module_id: allocation for allocation in allocations
    }
    allocation = allocation_by_module.get(safe_module_id)
    if allocation is None or allocation.status != "active":
        return _request_rejection(
            module_id=safe_module_id,
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            requested_units=requested_units,
            current_window_units=current_window_units,
            rejection_code="c14x_d_module_allocation_missing",
            rejection_reason=(
                "Execution rejected because no active explicit module "
                "allocation exists; implicit capability access is forbidden."
            ),
        )

    budget_by_capability = _budget_by_capability(allocation)
    if safe_capability not in allocation.allowed_capabilities:
        return _request_rejection(
            module_id=safe_module_id,
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            requested_units=requested_units,
            current_window_units=current_window_units,
            bound_key=allocation.bound_key,
            bound_model=allocation.bound_model,
            rejection_code="c14x_d_capability_not_assigned",
            rejection_reason=(
                "Execution rejected because the capability is not explicitly "
                "assigned to this module; shared capability pools are "
                "forbidden."
            ),
        )

    if allocation.bound_key != safe_key:
        return _request_rejection(
            module_id=safe_module_id,
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            requested_units=requested_units,
            current_window_units=current_window_units,
            bound_key=allocation.bound_key,
            bound_model=allocation.bound_model,
            rejection_code="c14x_d_bound_key_mismatch",
            rejection_reason=(
                "Execution rejected because requested key does not match the "
                "explicit module allocation binding."
            ),
        )

    if allocation.bound_model != safe_requested_model_id:
        return _request_rejection(
            module_id=safe_module_id,
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            requested_units=requested_units,
            current_window_units=current_window_units,
            bound_key=allocation.bound_key,
            bound_model=allocation.bound_model,
            rejection_code="c14x_d_bound_model_mismatch",
            rejection_reason=(
                "Execution rejected because requested model does not match "
                "the explicit module allocation binding."
            ),
        )

    budget = budget_by_capability[safe_capability]
    remaining_units = max(
        budget.max_units_per_window - current_window_units,
        0,
    )
    if requested_units > budget.max_units_per_request:
        return _request_rejection(
            module_id=safe_module_id,
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            requested_units=requested_units,
            current_window_units=current_window_units,
            bound_key=allocation.bound_key,
            bound_model=allocation.bound_model,
            budget_remaining_units=remaining_units,
            budget_window_seconds=budget.window_seconds,
            rejection_code="c14x_d_budget_request_limit_exceeded",
            rejection_reason=(
                "Execution rejected because requested usage exceeds the "
                "module capability per-request budget."
            ),
        )
    if requested_units > remaining_units:
        return _request_rejection(
            module_id=safe_module_id,
            capability=safe_capability,
            key=safe_key,
            requested_model_id=safe_requested_model_id,
            requested_units=requested_units,
            current_window_units=current_window_units,
            bound_key=allocation.bound_key,
            bound_model=allocation.bound_model,
            budget_remaining_units=remaining_units,
            budget_window_seconds=budget.window_seconds,
            rejection_code="c14x_d_budget_window_exceeded",
            rejection_reason=(
                "Execution rejected because requested usage exceeds the "
                "module capability window budget; unlimited AI access is "
                "forbidden."
            ),
        )

    return ModuleAllocationRequestValidationResult(
        module_id=safe_module_id,
        capability=safe_capability,
        key=safe_key,
        requested_model_id=safe_requested_model_id,
        requested_units=requested_units,
        current_window_units=current_window_units,
        bound_key=allocation.bound_key,
        bound_model=allocation.bound_model,
        budget_remaining_units=remaining_units - requested_units,
        budget_window_seconds=budget.window_seconds,
        valid=True,
        allocation_validation_passed=True,
        capability_assignment_passed=True,
        budget_validation_passed=True,
        execution_rejected=False,
        rejection_code=None,
        rejection_reason=(
            "Module allocation validation passed. This does not grant runtime "
            "execution, model invocation, external API access, or unlimited "
            "AI access; the request must continue to C14X-C routing and "
            "C14X-B model lock validation."
        ),
    )


def get_module_allocation_completion_status() -> ModuleAllocationCompletionStatus:
    return ModuleAllocationCompletionStatus(
        proceed_reason=(
            "C14X-D defines explicit module allocation, capability assignment "
            "rules, module category limits, finite capability budgets, "
            "enforcement rules, and the Module -> C14X-D -> C14X-C -> "
            "C14X-B -> C09 -> C10 integration flow without runtime execution."
        )
    )
