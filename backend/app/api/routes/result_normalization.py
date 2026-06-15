from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from ...models.user import User
from ...schemas.result_normalization import (
    NormalizedWorkflowResult,
    ResultModuleAdapterRules,
    ResultNormalizationCompletionStatus,
    ResultNormalizationEngineDesign,
    ResultSchemaMappingModel,
    ResultUIOutputStructure,
)
from ...services.result_normalization import (
    get_result_module_adapter_rules,
    get_result_normalization_completion_status,
    get_result_normalization_engine_design,
    get_result_schema_mapping_model,
    get_result_ui_output_structure,
    normalize_workflow_result,
)
from ..deps import require_rbac

router = APIRouter(
    prefix="/result-normalization",
    tags=["result-normalization"],
)


@router.post("/normalize", response_model=NormalizedWorkflowResult)
def result_normalization_normalize(
    payload: Any,
    user: User = Depends(require_rbac("C15E", "execute")),
) -> NormalizedWorkflowResult:
    del user
    try:
        return normalize_workflow_result(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None


@router.get(
    "/normalization-engine",
    response_model=ResultNormalizationEngineDesign,
)
def result_normalization_engine(
    user: User = Depends(require_rbac("C15E", "execute")),
) -> ResultNormalizationEngineDesign:
    del user
    return get_result_normalization_engine_design()


@router.get("/schema-mapping", response_model=ResultSchemaMappingModel)
def result_normalization_schema_mapping(
    user: User = Depends(require_rbac("C15E", "execute")),
) -> ResultSchemaMappingModel:
    del user
    return get_result_schema_mapping_model()


@router.get("/module-adapters", response_model=ResultModuleAdapterRules)
def result_normalization_module_adapters(
    user: User = Depends(require_rbac("C15E", "execute")),
) -> ResultModuleAdapterRules:
    del user
    return get_result_module_adapter_rules()


@router.get("/ui-output-structure", response_model=ResultUIOutputStructure)
def result_normalization_ui_output_structure(
    user: User = Depends(require_rbac("C15E", "execute")),
) -> ResultUIOutputStructure:
    del user
    return get_result_ui_output_structure()


@router.get(
    "/completion-status",
    response_model=ResultNormalizationCompletionStatus,
)
def result_normalization_completion_status(
    user: User = Depends(require_rbac("C15E", "execute")),
) -> ResultNormalizationCompletionStatus:
    del user
    return get_result_normalization_completion_status()
