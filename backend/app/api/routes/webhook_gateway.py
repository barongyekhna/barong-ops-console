from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...db.session import get_db
from ...models.user import User
from ...schemas.webhook_gateway import (
    WebhookGatewayCompletionStatus,
    WebhookGatewayDecision,
    WebhookGatewayDesign,
    WebhookGatewayLookupFlow,
    WebhookGatewayPayloadFormat,
    WebhookGatewayRequest,
    WebhookGatewaySignatureModel,
)
from ...services.webhook_gateway import (
    WebhookGatewayConfigurationError,
    WebhookGatewayReplayError,
    WebhookGatewaySignatureError,
    build_webhook_gateway_decision,
    get_webhook_gateway_completion_status,
    get_webhook_gateway_design,
    get_webhook_gateway_lookup_flow,
    get_webhook_gateway_payload_format,
    get_webhook_gateway_signature_model,
)
from ...middleware.event_collector import set_request_context_id
from ...services.event_collector import emit_event
from ..deps import require_internal_rbac, require_rbac

router = APIRouter(
    prefix="/webhook-gateway",
    tags=["webhook-gateway"],
)


@router.post(
    "/ingress",
    response_model=WebhookGatewayDecision,
    status_code=status.HTTP_202_ACCEPTED,
)
def webhook_gateway_ingress(
    payload: dict[str, Any],
    request: Request,
    signature: str | None = Header(
        default=None,
        alias="X-Barong-Gateway-Signature",
    ),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> WebhookGatewayDecision:
    try:
        gateway_payload = WebhookGatewayRequest.model_validate(payload)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid C15B webhook gateway payload.",
        ) from None

    set_request_context_id(request, gateway_payload.context_id)
    request.state.workflow_id = gateway_payload.workflow_id
    emit_event(
        event_type="webhook.gateway.ingress",
        module="C15",
        action="webhook.gateway.ingress",
        source="backend",
        status="pending",
        context_id=gateway_payload.context_id,
        workflow_id=gateway_payload.workflow_id,
        payload={
            "module": gateway_payload.module,
            "workflow_id": gateway_payload.workflow_id,
        },
    )
    require_internal_rbac("C15B")

    try:
        decision = build_webhook_gateway_decision(
            gateway_payload,
            provided_signature=signature,
            settings=settings,
            db=db,
        )
    except WebhookGatewayConfigurationError as exc:
        emit_event(
            event_type="webhook.gateway.egress",
            module="C15",
            action="webhook.gateway.egress",
            source="backend",
            status="failed",
            context_id=gateway_payload.context_id,
            workflow_id=gateway_payload.workflow_id,
            payload={"reason": "configuration_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
    except WebhookGatewaySignatureError:
        emit_event(
            event_type="webhook.gateway.egress",
            module="C15",
            action="webhook.gateway.egress",
            source="backend",
            status="failed",
            context_id=gateway_payload.context_id,
            workflow_id=gateway_payload.workflow_id,
            payload={"reason": "signature_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid C15B webhook gateway signature.",
        ) from None
    except WebhookGatewayReplayError:
        emit_event(
            event_type="webhook.gateway.egress",
            module="C15",
            action="webhook.gateway.egress",
            source="backend",
            status="failed",
            context_id=gateway_payload.context_id,
            workflow_id=gateway_payload.workflow_id,
            payload={"reason": "replay_error"},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate C15B webhook gateway nonce.",
        ) from None

    if decision.gateway_status == "rejected":
        emit_event(
            event_type="webhook.gateway.egress",
            module="C15",
            action="webhook.gateway.egress",
            source="backend",
            status="failed",
            context_id=decision.context_id,
            workflow_id=decision.workflow_id,
            payload={
                "module": decision.module,
                "gateway_status": decision.gateway_status,
                "reason": decision.reason,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=decision.model_dump(mode="json"),
        )
    emit_event(
        event_type="webhook.gateway.egress",
        module="C15",
        action="webhook.gateway.egress",
        source="backend",
        status="success",
        context_id=decision.context_id,
        workflow_id=decision.workflow_id,
        payload={
            "module": decision.module,
            "gateway_status": decision.gateway_status,
            "hidden_webhook_reference_resolved": (
                decision.hidden_webhook_reference_resolved
            ),
        },
    )
    return decision


@router.get("/design", response_model=WebhookGatewayDesign)
def webhook_gateway_design(
    user: User = Depends(require_rbac("C15B", "execute")),
) -> WebhookGatewayDesign:
    del user
    return get_webhook_gateway_design()


@router.get("/signature-model", response_model=WebhookGatewaySignatureModel)
def webhook_gateway_signature_model(
    user: User = Depends(require_rbac("C15B", "execute")),
    settings: Settings = Depends(get_settings),
) -> WebhookGatewaySignatureModel:
    del user
    return get_webhook_gateway_signature_model(settings)


@router.get("/payload-format", response_model=WebhookGatewayPayloadFormat)
def webhook_gateway_payload_format(
    user: User = Depends(require_rbac("C15B", "execute")),
) -> WebhookGatewayPayloadFormat:
    del user
    return get_webhook_gateway_payload_format()


@router.get("/workflow-lookup-flow", response_model=WebhookGatewayLookupFlow)
def webhook_gateway_workflow_lookup_flow(
    user: User = Depends(require_rbac("C15B", "execute")),
) -> WebhookGatewayLookupFlow:
    del user
    return get_webhook_gateway_lookup_flow()


@router.get(
    "/completion-status",
    response_model=WebhookGatewayCompletionStatus,
)
def webhook_gateway_completion_status(
    user: User = Depends(require_rbac("C15B", "execute")),
) -> WebhookGatewayCompletionStatus:
    del user
    return get_webhook_gateway_completion_status()
