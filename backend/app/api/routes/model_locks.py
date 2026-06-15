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
from ..deps import get_current_user

router = APIRouter(
    prefix="/model-locks",
    tags=["model-locks"],
)


@router.get("/registry", response_model=ModelLockRegistryResponse)
def model_lock_registry(
    user: User = Depends(get_current_user),
) -> ModelLockRegistryResponse:
    del user
    return list_model_lock_registry()


@router.get("/rules", response_model=ModelLockRuleModel)
def model_lock_rules(
    user: User = Depends(get_current_user),
) -> ModelLockRuleModel:
    del user
    return get_model_lock_rule_model()


@router.get("/enforcement", response_model=ModelLockEnforcementLogic)
def model_lock_enforcement(
    user: User = Depends(get_current_user),
) -> ModelLockEnforcementLogic:
    del user
    return get_model_lock_enforcement_logic()


@router.get("/validation", response_model=ModelLockRegistryValidationResult)
def model_lock_validation(
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
) -> ModelLockRequestValidationResult:
    del user
    return validate_model_lock_request(
        key_id=key_id,
        requested_model_id=requested_model_id,
    )


@router.get("/integration", response_model=ModelLockC14XAIntegration)
def model_lock_integration(
    user: User = Depends(get_current_user),
) -> ModelLockC14XAIntegration:
    del user
    return get_model_lock_c14x_a_integration()


@router.get("/completion-status", response_model=ModelLockCompletionStatus)
def model_lock_completion_status(
    user: User = Depends(get_current_user),
) -> ModelLockCompletionStatus:
    del user
    return get_model_lock_completion_status()
