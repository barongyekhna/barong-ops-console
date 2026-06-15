from fastapi import APIRouter, Depends, Query

from ...models.user import User
from ...schemas.module_workflow_binding import (
    ModuleWorkflowAccessControlSystem,
    ModuleWorkflowBindingCompletionStatus,
    ModuleWorkflowBindingDecision,
    ModuleWorkflowBindingModel,
    ModuleWorkflowBindingValidationResult,
    ModuleWorkflowEnforcementRules,
    ModuleWorkflowIsolationRules,
)
from ...services.module_workflow_binding_engine import (
    build_module_workflow_binding_model,
    build_module_workflow_binding_validation_result,
    evaluate_module_workflow_access,
    get_module_workflow_access_control_system,
    get_module_workflow_binding_completion_status,
    get_module_workflow_enforcement_rules,
    get_module_workflow_isolation_rules,
)
from ..deps import get_current_user

router = APIRouter(
    prefix="/module-workflow-bindings",
    tags=["module-workflow-bindings"],
)


@router.get("/model", response_model=ModuleWorkflowBindingModel)
def module_workflow_binding_model(
    user: User = Depends(get_current_user),
) -> ModuleWorkflowBindingModel:
    del user
    return build_module_workflow_binding_model()


@router.get("/enforcement", response_model=ModuleWorkflowEnforcementRules)
def module_workflow_binding_enforcement(
    user: User = Depends(get_current_user),
) -> ModuleWorkflowEnforcementRules:
    del user
    return get_module_workflow_enforcement_rules()


@router.get(
    "/access-control",
    response_model=ModuleWorkflowAccessControlSystem,
)
def module_workflow_binding_access_control(
    user: User = Depends(get_current_user),
) -> ModuleWorkflowAccessControlSystem:
    del user
    return get_module_workflow_access_control_system()


@router.get("/isolation-rules", response_model=ModuleWorkflowIsolationRules)
def module_workflow_binding_isolation_rules(
    user: User = Depends(get_current_user),
) -> ModuleWorkflowIsolationRules:
    del user
    return get_module_workflow_isolation_rules()


@router.get("/decision", response_model=ModuleWorkflowBindingDecision)
def module_workflow_binding_decision(
    module_id: str = Query(min_length=1, max_length=128),
    workflow_id: str = Query(min_length=1, max_length=180),
    user: User = Depends(get_current_user),
) -> ModuleWorkflowBindingDecision:
    del user
    return evaluate_module_workflow_access(
        module_id=module_id,
        workflow_id=workflow_id,
    )


@router.get(
    "/validation",
    response_model=ModuleWorkflowBindingValidationResult,
)
def module_workflow_binding_validation(
    user: User = Depends(get_current_user),
) -> ModuleWorkflowBindingValidationResult:
    del user
    return build_module_workflow_binding_validation_result()


@router.get(
    "/completion-status",
    response_model=ModuleWorkflowBindingCompletionStatus,
)
def module_workflow_binding_completion_status(
    user: User = Depends(get_current_user),
) -> ModuleWorkflowBindingCompletionStatus:
    del user
    return get_module_workflow_binding_completion_status()
