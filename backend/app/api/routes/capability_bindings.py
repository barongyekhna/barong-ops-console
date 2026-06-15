from fastapi import APIRouter, Depends, Query

from ...models.user import User
from ...schemas.capability_binding import (
    CapabilityBindingCompletionStatus,
    CapabilityBindingEnforcementStrategy,
    CapabilityBindingIntegrationModel,
    CapabilityBindingRequestValidationResult,
    CapabilityBindingValidationResult,
    CapabilityModelMappingResponse,
    CapabilityRoutingModel,
    ModuleCapabilityBindingRulesResponse,
)
from ...services.capability_binding_engine import (
    build_capability_binding_validation_result,
    build_capability_model_mapping,
    build_capability_routing_model,
    get_capability_binding_completion_status,
    get_capability_binding_enforcement_strategy,
    get_capability_binding_integration_model,
    list_module_capability_binding_rules,
    validate_capability_binding_request,
)
from ..deps import require_rbac

router = APIRouter(
    prefix="/capability-bindings",
    tags=["capability-bindings"],
)


@router.get("/routing-model", response_model=CapabilityRoutingModel)
def capability_binding_routing_model(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> CapabilityRoutingModel:
    del user
    return build_capability_routing_model()


@router.get("/model-mapping", response_model=CapabilityModelMappingResponse)
def capability_binding_model_mapping(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> CapabilityModelMappingResponse:
    del user
    return build_capability_model_mapping()


@router.get(
    "/module-bindings",
    response_model=ModuleCapabilityBindingRulesResponse,
)
def capability_binding_module_bindings(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModuleCapabilityBindingRulesResponse:
    del user
    return list_module_capability_binding_rules()


@router.get("/enforcement", response_model=CapabilityBindingEnforcementStrategy)
def capability_binding_enforcement(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> CapabilityBindingEnforcementStrategy:
    del user
    return get_capability_binding_enforcement_strategy()


@router.get("/validation", response_model=CapabilityBindingValidationResult)
def capability_binding_validation(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> CapabilityBindingValidationResult:
    del user
    return build_capability_binding_validation_result()


@router.get(
    "/request-validation",
    response_model=CapabilityBindingRequestValidationResult,
)
def capability_binding_request_validation(
    capability: str = Query(..., min_length=1, max_length=180),
    key: str = Query(..., min_length=1, max_length=180),
    requested_model_id: str = Query(..., min_length=1, max_length=180),
    module: str = Query(..., min_length=1, max_length=128),
    user: User = Depends(require_rbac("C14X", "admin")),
) -> CapabilityBindingRequestValidationResult:
    del user
    return validate_capability_binding_request(
        capability=capability,
        key=key,
        requested_model_id=requested_model_id,
        module=module,
    )


@router.get("/integration", response_model=CapabilityBindingIntegrationModel)
def capability_binding_integration(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> CapabilityBindingIntegrationModel:
    del user
    return get_capability_binding_integration_model()


@router.get(
    "/completion-status",
    response_model=CapabilityBindingCompletionStatus,
)
def capability_binding_completion_status(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> CapabilityBindingCompletionStatus:
    del user
    return get_capability_binding_completion_status()
