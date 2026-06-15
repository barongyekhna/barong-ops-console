from fastapi import APIRouter, Depends

from ...models.user import User
from ...schemas.ai_execution_binding import (
    AIExecutionBindingCompletionStatus,
    AIExecutionBindingRegistryResponse,
    AIExecutionBindingRuleModel,
    AIExecutionBindingUIInteractionModel,
    AIExecutionBindingValidationResult,
    AIExecutionFlowMapping,
)
from ...services.ai_execution_binding_registry import (
    build_ai_execution_binding_validation_result,
    build_ai_execution_flow_mapping,
    get_ai_execution_binding_completion_status,
    get_ai_execution_binding_rule_model,
    get_ai_execution_binding_ui_interaction_model,
    list_ai_execution_binding_registry,
)
from ..deps import require_rbac

router = APIRouter(
    prefix="/ai-execution-bindings",
    tags=["ai-execution-bindings"],
)


@router.get("/registry", response_model=AIExecutionBindingRegistryResponse)
def ai_execution_binding_registry(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> AIExecutionBindingRegistryResponse:
    del user
    return list_ai_execution_binding_registry()


@router.get("/rules", response_model=AIExecutionBindingRuleModel)
def ai_execution_binding_rules(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> AIExecutionBindingRuleModel:
    del user
    return get_ai_execution_binding_rule_model()


@router.get("/execution-flow", response_model=AIExecutionFlowMapping)
def ai_execution_binding_execution_flow(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> AIExecutionFlowMapping:
    del user
    return build_ai_execution_flow_mapping()


@router.get("/validation", response_model=AIExecutionBindingValidationResult)
def ai_execution_binding_validation(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> AIExecutionBindingValidationResult:
    del user
    return build_ai_execution_binding_validation_result()


@router.get(
    "/ui-interaction",
    response_model=AIExecutionBindingUIInteractionModel,
)
def ai_execution_binding_ui_interaction(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> AIExecutionBindingUIInteractionModel:
    del user
    return get_ai_execution_binding_ui_interaction_model()


@router.get(
    "/completion-status",
    response_model=AIExecutionBindingCompletionStatus,
)
def ai_execution_binding_completion_status(
    user: User = Depends(require_rbac("C14X", "admin")),
) -> AIExecutionBindingCompletionStatus:
    del user
    return get_ai_execution_binding_completion_status()
