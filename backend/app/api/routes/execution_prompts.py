from fastapi import APIRouter, Depends, Query

from ...models.user import User
from ...schemas.execution_prompt import (
    ExecutionPromptBindingInjectionModel,
    ExecutionPromptCompletionStatus,
    ExecutionPromptContextAssemblyRules,
    ExecutionPromptGenerationResult,
    ExecutionPromptSecurityConstraints,
    ExecutionPromptTemplateEngineDesign,
    ExecutionPromptValidationResult,
)
from ...services.execution_prompt_generator import (
    build_execution_prompt_payload,
    build_execution_prompt_validation_result,
    get_execution_prompt_binding_injection_model,
    get_execution_prompt_completion_status,
    get_execution_prompt_context_assembly_rules,
    get_execution_prompt_security_constraints,
    get_execution_prompt_template_engine_design,
)
from ..deps import get_current_user

router = APIRouter(
    prefix="/execution-prompts",
    tags=["execution-prompts"],
)


@router.get("/template-engine", response_model=ExecutionPromptTemplateEngineDesign)
def execution_prompt_template_engine(
    user: User = Depends(get_current_user),
) -> ExecutionPromptTemplateEngineDesign:
    del user
    return get_execution_prompt_template_engine_design()


@router.get(
    "/binding-injection",
    response_model=ExecutionPromptBindingInjectionModel,
)
def execution_prompt_binding_injection(
    user: User = Depends(get_current_user),
) -> ExecutionPromptBindingInjectionModel:
    del user
    return get_execution_prompt_binding_injection_model()


@router.get(
    "/context-assembly",
    response_model=ExecutionPromptContextAssemblyRules,
)
def execution_prompt_context_assembly(
    user: User = Depends(get_current_user),
) -> ExecutionPromptContextAssemblyRules:
    del user
    return get_execution_prompt_context_assembly_rules()


@router.get(
    "/security-constraints",
    response_model=ExecutionPromptSecurityConstraints,
)
def execution_prompt_security_constraints(
    user: User = Depends(get_current_user),
) -> ExecutionPromptSecurityConstraints:
    del user
    return get_execution_prompt_security_constraints()


@router.get("/payload", response_model=ExecutionPromptGenerationResult)
def execution_prompt_payload(
    module_id: str = Query(..., min_length=1, max_length=180),
    capability: str = Query(..., min_length=1, max_length=180),
    model: str = Query(..., min_length=1, max_length=180),
    key: str = Query(..., min_length=1, max_length=180),
    context: str = Query("", max_length=5000),
    requested_units: int = Query(1, ge=1),
    current_window_units: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> ExecutionPromptGenerationResult:
    del user
    return build_execution_prompt_payload(
        module_id=module_id,
        capability=capability,
        model=model,
        key=key,
        context=context,
        requested_units=requested_units,
        current_window_units=current_window_units,
    )


@router.get("/validation", response_model=ExecutionPromptValidationResult)
def execution_prompt_validation(
    user: User = Depends(get_current_user),
) -> ExecutionPromptValidationResult:
    del user
    return build_execution_prompt_validation_result()


@router.get(
    "/completion-status",
    response_model=ExecutionPromptCompletionStatus,
)
def execution_prompt_completion_status(
    user: User = Depends(get_current_user),
) -> ExecutionPromptCompletionStatus:
    del user
    return get_execution_prompt_completion_status()
