from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...db.session import get_db
from ...models.user import User
from ...schemas.failure_handling import (
    DeadLetterQueueArchitecture,
    DeadLetterQueueResponse,
    DeadLetterRecord,
    FailureHandlingCompletionStatus,
    FailureHandlingOutcome,
    FailureHandlingRequest,
    FallbackStrategy,
    ManualReplayRequest,
    RecoveryFlow,
    RecoveryPlan,
    RetrySystemDesign,
    TimeoutEvaluationRequest,
    TimeoutHandlingDecision,
    TimeoutHandlingModel,
)
from ...services.failure_handling import (
    FailureRecoveryError,
    evaluate_timeout,
    get_dead_letter_queue_architecture,
    get_dead_letter_record,
    get_failure_handling_completion_status,
    get_fallback_strategy,
    get_recovery_flow,
    get_retry_system_design,
    get_timeout_handling_model,
    handle_failure,
    list_dead_letter_records,
    manual_replay_context,
)
from ..deps import require_rbac

router = APIRouter(
    prefix="/failure-handling",
    tags=["failure-handling"],
)


@router.post("/failures", response_model=FailureHandlingOutcome)
def failure_handling_submit_failure(
    payload: dict[str, Any],
    user: User = Depends(require_rbac("C15H", "execute")),
) -> FailureHandlingOutcome:
    del user
    try:
        request = FailureHandlingRequest.model_validate(payload)
        return handle_failure(request)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid C15H failure handling payload.",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None


@router.post("/timeouts/evaluate", response_model=TimeoutHandlingDecision)
def failure_handling_evaluate_timeout(
    payload: dict[str, Any],
    user: User = Depends(require_rbac("C15H", "execute")),
) -> TimeoutHandlingDecision:
    del user
    try:
        request = TimeoutEvaluationRequest.model_validate(payload)
        return evaluate_timeout(request)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid C15H timeout evaluation payload.",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None


@router.get("/dlq", response_model=DeadLetterQueueResponse)
def failure_handling_dlq(
    user: User = Depends(require_rbac("C15H", "execute")),
) -> DeadLetterQueueResponse:
    del user
    return list_dead_letter_records()


@router.get("/dlq/{context_id}", response_model=DeadLetterRecord)
def failure_handling_dlq_record(
    context_id: str,
    user: User = Depends(require_rbac("C15H", "execute")),
) -> DeadLetterRecord:
    del user
    record = get_dead_letter_record(context_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="C15H DLQ record was not found.",
        )
    return record


@router.post("/recovery/replay", response_model=RecoveryPlan)
def failure_handling_manual_replay(
    payload: dict[str, Any],
    user: User = Depends(require_rbac("C15H", "execute")),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> RecoveryPlan:
    del user
    try:
        request = ManualReplayRequest.model_validate(payload)
        plan = manual_replay_context(request, settings=settings, db=db)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid C15H manual replay payload.",
        ) from None
    except FailureRecoveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None

    if plan.recovery_status == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=plan.model_dump(mode="json"),
        )
    return plan


@router.get("/retry-system-design", response_model=RetrySystemDesign)
def failure_handling_retry_system_design(
    user: User = Depends(require_rbac("C15H", "execute")),
) -> RetrySystemDesign:
    del user
    return get_retry_system_design()


@router.get("/timeout-handling", response_model=TimeoutHandlingModel)
def failure_handling_timeout_model(
    user: User = Depends(require_rbac("C15H", "execute")),
) -> TimeoutHandlingModel:
    del user
    return get_timeout_handling_model()


@router.get(
    "/dead-letter-queue",
    response_model=DeadLetterQueueArchitecture,
)
def failure_handling_dead_letter_queue(
    user: User = Depends(require_rbac("C15H", "execute")),
) -> DeadLetterQueueArchitecture:
    del user
    return get_dead_letter_queue_architecture()


@router.get("/fallback-strategy", response_model=FallbackStrategy)
def failure_handling_fallback_strategy(
    user: User = Depends(require_rbac("C15H", "execute")),
) -> FallbackStrategy:
    del user
    return get_fallback_strategy()


@router.get("/recovery-flow", response_model=RecoveryFlow)
def failure_handling_recovery_flow(
    user: User = Depends(require_rbac("C15H", "execute")),
) -> RecoveryFlow:
    del user
    return get_recovery_flow()


@router.get(
    "/completion-status",
    response_model=FailureHandlingCompletionStatus,
)
def failure_handling_completion_status(
    user: User = Depends(require_rbac("C15H", "execute")),
) -> FailureHandlingCompletionStatus:
    del user
    return get_failure_handling_completion_status()
