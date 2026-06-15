from fastapi import APIRouter, Depends, Query

from ...models.user import User
from ...schemas.module_allocation import (
    ModuleAllocationAssignmentModel,
    ModuleAllocationBudgetSystem,
    ModuleAllocationCategoryModel,
    ModuleAllocationCompletionStatus,
    ModuleAllocationEnforcementRules,
    ModuleAllocationIntegrationFlow,
    ModuleAllocationRegistryResponse,
    ModuleAllocationRequestValidationResult,
    ModuleAllocationValidationResult,
)
from ...services.module_allocation_system import (
    build_module_allocation_budget_system,
    build_module_allocation_validation_result,
    get_module_allocation_assignment_model,
    get_module_allocation_category_model,
    get_module_allocation_completion_status,
    get_module_allocation_enforcement_rules,
    get_module_allocation_integration_flow,
    list_module_allocation_registry,
    validate_module_allocation_request,
)
from ..deps import require_rbac

router = APIRouter(
    prefix="/module-allocations",
    tags=["module-allocations"],
)


@router.get("/registry", response_model=ModuleAllocationRegistryResponse)
def module_allocation_registry(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationRegistryResponse:
    del user
    return list_module_allocation_registry()


@router.get("/assignment-model", response_model=ModuleAllocationAssignmentModel)
def module_allocation_assignment_model(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationAssignmentModel:
    del user
    return get_module_allocation_assignment_model()


@router.get("/categories", response_model=ModuleAllocationCategoryModel)
def module_allocation_categories(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationCategoryModel:
    del user
    return get_module_allocation_category_model()


@router.get("/budget-system", response_model=ModuleAllocationBudgetSystem)
def module_allocation_budget_system(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationBudgetSystem:
    del user
    return build_module_allocation_budget_system()


@router.get("/enforcement", response_model=ModuleAllocationEnforcementRules)
def module_allocation_enforcement(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationEnforcementRules:
    del user
    return get_module_allocation_enforcement_rules()


@router.get("/integration-flow", response_model=ModuleAllocationIntegrationFlow)
def module_allocation_integration_flow(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationIntegrationFlow:
    del user
    return get_module_allocation_integration_flow()


@router.get("/validation", response_model=ModuleAllocationValidationResult)
def module_allocation_validation(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationValidationResult:
    del user
    return build_module_allocation_validation_result()


@router.get(
    "/request-validation",
    response_model=ModuleAllocationRequestValidationResult,
)
def module_allocation_request_validation(
    module_id: str = Query(..., min_length=1, max_length=180),
    capability: str = Query(..., min_length=1, max_length=180),
    key: str = Query(..., min_length=1, max_length=180),
    requested_model_id: str = Query(..., min_length=1, max_length=180),
    requested_units: int = Query(..., ge=0),
    current_window_units: int = Query(0, ge=0),
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationRequestValidationResult:
    del user
    return validate_module_allocation_request(
        module_id=module_id,
        capability=capability,
        key=key,
        requested_model_id=requested_model_id,
        requested_units=requested_units,
        current_window_units=current_window_units,
    )


@router.get(
    "/completion-status",
    response_model=ModuleAllocationCompletionStatus,
)
def module_allocation_completion_status(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleAllocationCompletionStatus:
    del user
    return get_module_allocation_completion_status()
