from typing import Any

from fastapi import APIRouter, Depends

from ...models.user import User
from ...schemas.execution_payload_standardization import (
    ExecutionPayloadCompletionStatus,
    ExecutionPayloadContextRules,
    ExecutionPayloadNormalizationEngineDesign,
    ExecutionPayloadNormalizationResult,
    ExecutionPayloadStandardizationModel,
    ExecutionPayloadWorkflowMappingIntegration,
)
from ...services.execution_payload_standardization import (
    get_context_standardization_rules,
    get_execution_payload_completion_status,
    get_normalization_engine_design,
    get_payload_standardization_model,
    get_workflow_mapping_integration,
    normalize_execution_payload_request,
)
from ..deps import get_current_user

router = APIRouter(
    prefix="/payload-standardization",
    tags=["payload-standardization"],
)


@router.post(
    "/normalize",
    response_model=ExecutionPayloadNormalizationResult,
)
def payload_standardization_normalize(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
) -> ExecutionPayloadNormalizationResult:
    del user
    return normalize_execution_payload_request(payload)


@router.get("/model", response_model=ExecutionPayloadStandardizationModel)
def payload_standardization_model(
    user: User = Depends(get_current_user),
) -> ExecutionPayloadStandardizationModel:
    del user
    return get_payload_standardization_model()


@router.get(
    "/normalization-engine",
    response_model=ExecutionPayloadNormalizationEngineDesign,
)
def payload_standardization_engine(
    user: User = Depends(get_current_user),
) -> ExecutionPayloadNormalizationEngineDesign:
    del user
    return get_normalization_engine_design()


@router.get("/context-rules", response_model=ExecutionPayloadContextRules)
def payload_standardization_context_rules(
    user: User = Depends(get_current_user),
) -> ExecutionPayloadContextRules:
    del user
    return get_context_standardization_rules()


@router.get(
    "/workflow-mapping",
    response_model=ExecutionPayloadWorkflowMappingIntegration,
)
def payload_standardization_workflow_mapping(
    user: User = Depends(get_current_user),
) -> ExecutionPayloadWorkflowMappingIntegration:
    del user
    return get_workflow_mapping_integration()


@router.get(
    "/completion-status",
    response_model=ExecutionPayloadCompletionStatus,
)
def payload_standardization_completion_status(
    user: User = Depends(get_current_user),
) -> ExecutionPayloadCompletionStatus:
    del user
    return get_execution_payload_completion_status()
