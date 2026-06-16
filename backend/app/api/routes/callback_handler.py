from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...db.session import get_db
from ...models.user import User
from ...schemas.callback_handler import (
    CallbackContextBinding,
    CallbackContextBindingModel,
    CallbackHandlerCompletionStatus,
    CallbackHandlerDesign,
    CallbackHandlerPayload,
    CallbackHandlerResult,
    CallbackModuleNotificationModel,
    CallbackResultStorageModel,
    CallbackResultStorageRecord,
    CallbackStatusManagementModel,
)
from ...schemas.execution_payload_standardization import (
    ExecutionPayloadStandardRequest,
)
from ...services.callback_handler import (
    CallbackContextBindingError,
    CallbackHandlerConfigurationError,
    CallbackHandlerReplayError,
    CallbackHandlerSignatureError,
    CallbackStatusTransitionError,
    bind_callback_context,
    get_callback_handler_completion_status,
    get_callback_handler_design,
    get_callback_result,
    get_context_binding_model,
    get_module_notification_model,
    get_result_storage_model,
    get_status_management_model,
    handle_callback,
)
from ...middleware.event_collector import set_request_context_id
from ...services.event_collector import emit_event
from ..deps import require_internal_rbac, require_rbac

router = APIRouter(
    prefix="/callback-handler",
    tags=["callback-handler"],
)


@router.post(
    "/receiver",
    response_model=CallbackHandlerResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def callback_handler_receiver(
    payload: dict[str, Any],
    request: Request,
    signature: str | None = Header(
        default=None,
        alias="X-Barong-Gateway-Signature",
    ),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> CallbackHandlerResult:
    try:
        callback_payload = CallbackHandlerPayload.model_validate(payload)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid C15D callback payload.",
        ) from None

    set_request_context_id(request, callback_payload.context_id)
    request.state.workflow_id = callback_payload.workflow_id
    emit_event(
        event_type="webhook.callback.ingress",
        module="C15",
        action="callback.receiver.ingress",
        source="n8n",
        status="pending",
        context_id=callback_payload.context_id,
        workflow_id=callback_payload.workflow_id,
        payload={
            "module": callback_payload.module,
            "workflow_id": callback_payload.workflow_id,
            "callback_status": callback_payload.status,
        },
    )
    require_internal_rbac("C15D")

    try:
        result = handle_callback(
            callback_payload,
            provided_signature=signature,
            settings=settings,
            db=db,
        )
    except CallbackHandlerConfigurationError as exc:
        emit_event(
            event_type="webhook.callback.egress",
            module="C15",
            action="callback.receiver.egress",
            source="n8n",
            status="failed",
            context_id=callback_payload.context_id,
            workflow_id=callback_payload.workflow_id,
            payload={"reason": "configuration_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
    except CallbackHandlerSignatureError:
        emit_event(
            event_type="webhook.callback.egress",
            module="C15",
            action="callback.receiver.egress",
            source="n8n",
            status="failed",
            context_id=callback_payload.context_id,
            workflow_id=callback_payload.workflow_id,
            payload={"reason": "signature_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid C15D callback signature.",
        ) from None
    except CallbackHandlerReplayError:
        emit_event(
            event_type="webhook.callback.egress",
            module="C15",
            action="callback.receiver.egress",
            source="n8n",
            status="failed",
            context_id=callback_payload.context_id,
            workflow_id=callback_payload.workflow_id,
            payload={"reason": "replay_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate C15D callback nonce or idempotency key.",
        ) from None
    except CallbackContextBindingError as exc:
        emit_event(
            event_type="webhook.callback.egress",
            module="C15",
            action="callback.receiver.egress",
            source="n8n",
            status="failed",
            context_id=callback_payload.context_id,
            workflow_id=callback_payload.workflow_id,
            payload={"reason": "context_binding_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    except CallbackStatusTransitionError as exc:
        emit_event(
            event_type="webhook.callback.egress",
            module="C15",
            action="callback.receiver.egress",
            source="n8n",
            status="failed",
            context_id=callback_payload.context_id,
            workflow_id=callback_payload.workflow_id,
            payload={"reason": "status_transition_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    emit_event(
        event_type="webhook.callback.egress",
        module="C15",
        action="callback.receiver.egress",
        source="n8n",
        status="success",
        context_id=callback_payload.context_id,
        workflow_id=callback_payload.workflow_id,
        payload={
            "processing_status": result.processing_status,
            "execution_status": result.status,
        },
    )
    return result


@router.post(
    "/context-bindings",
    response_model=CallbackContextBinding,
    status_code=status.HTTP_201_CREATED,
)
def callback_handler_bind_context(
    payload: dict[str, Any],
    user: User = Depends(require_rbac("C15D", "execute")),
) -> CallbackContextBinding:
    del user
    try:
        request = ExecutionPayloadStandardRequest.model_validate(payload)
        return bind_callback_context(request)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid C15C execution request for C15D context binding.",
        ) from None
    except CallbackContextBindingError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None


@router.get(
    "/results/{context_id}",
    response_model=CallbackResultStorageRecord,
)
def callback_handler_result(
    context_id: str,
    user: User = Depends(require_rbac("C15D", "execute")),
) -> CallbackResultStorageRecord:
    del user
    result = get_callback_result(context_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="C15D callback result was not found.",
        )
    return result


@router.get("/design", response_model=CallbackHandlerDesign)
def callback_handler_design(
    user: User = Depends(require_rbac("C15D", "execute")),
) -> CallbackHandlerDesign:
    del user
    return get_callback_handler_design()


@router.get("/context-binding", response_model=CallbackContextBindingModel)
def callback_handler_context_binding(
    user: User = Depends(require_rbac("C15D", "execute")),
) -> CallbackContextBindingModel:
    del user
    return get_context_binding_model()


@router.get("/status-management", response_model=CallbackStatusManagementModel)
def callback_handler_status_management(
    user: User = Depends(require_rbac("C15D", "execute")),
) -> CallbackStatusManagementModel:
    del user
    return get_status_management_model()


@router.get("/result-storage", response_model=CallbackResultStorageModel)
def callback_handler_result_storage(
    user: User = Depends(require_rbac("C15D", "execute")),
) -> CallbackResultStorageModel:
    del user
    return get_result_storage_model()


@router.get(
    "/module-notifications",
    response_model=CallbackModuleNotificationModel,
)
def callback_handler_module_notifications(
    user: User = Depends(require_rbac("C15D", "execute")),
) -> CallbackModuleNotificationModel:
    del user
    return get_module_notification_model()


@router.get(
    "/completion-status",
    response_model=CallbackHandlerCompletionStatus,
)
def callback_handler_completion_status(
    user: User = Depends(require_rbac("C15D", "execute")),
) -> CallbackHandlerCompletionStatus:
    del user
    return get_callback_handler_completion_status()
