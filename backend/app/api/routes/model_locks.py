from fastapi import APIRouter, Depends, Query

from ...models.user import User
from ...schemas.model_lock import (
    ModelLockC14XAIntegration,
    ModelLockCompletionStatus,
    ModelLockEnforcementLogic,
    ModelLockRegistryResponse,
    ModelLockRegistryValidationResult,
    ModelLockRequestValidationResult,
    ModelLockRuleModel,
)
from ...services.model_lock_registry import (
    build_model_lock_validation_result,
    get_model_lock_c14x_a_integration,
    get_model_lock_completion_status,
    get_model_lock_enforcement_logic,
    get_model_lock_rule_model,
    list_model_lock_registry,
    validate_model_lock_request,
)
from ..deps import require_rbac

router = APIRouter(
    prefix="/model-locks",
    tags=["model-locks"],
)


@router.get("/registry", response_model=ModelLockRegistryResponse)
def model_lock_registry(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModelLockRegistryResponse:
    del user
    return list_model_lock_registry()


@router.get("/rules", response_model=ModelLockRuleModel)
def model_lock_rules(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModelLockRuleModel:
    del user
    return get_model_lock_rule_model()


@router.get("/enforcement", response_model=ModelLockEnforcementLogic)
def model_lock_enforcement(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModelLockEnforcementLogic:
    del user
    return get_model_lock_enforcement_logic()


@router.get("/validation", response_model=ModelLockRegistryValidationResult)
def model_lock_validation(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModelLockRegistryValidationResult:
    del user
    return build_model_lock_validation_result()


@router.get(
    "/request-validation",
    response_model=ModelLockRequestValidationResult,
)
def model_lock_request_validation(
    key_id: str = Query(..., min_length=1, max_length=180),
    requested_model_id: str = Query(..., min_length=1, max_length=180),
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModelLockRequestValidationResult:
    del user
    return validate_model_lock_request(
        key_id=key_id,
        requested_model_id=requested_model_id,
    )


@router.get("/integration", response_model=ModelLockC14XAIntegration)
def model_lock_integration(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModelLockC14XAIntegration:
    del user
    return get_model_lock_c14x_a_integration()


@router.get("/completion-status", response_model=ModelLockCompletionStatus)
def model_lock_completion_status(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> ModelLockCompletionStatus:
    del user
    return get_model_lock_completion_status()
