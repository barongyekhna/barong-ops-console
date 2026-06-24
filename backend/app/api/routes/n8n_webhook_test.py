from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...db.session import get_db
from ...models.user import User
from ...schemas.n8n_webhook_test import (
    N8N_WEBHOOK_TEST_MODULE_KEY,
    N8nWebhookTestRunRequest,
    N8nWebhookTestRunResponse,
)
from ...services.module_execution_gate import (
    ModuleExecutionGateError,
    require_module_execution_ready,
)
from ...services.n8n_webhook_test_service import (
    N8nWebhookTestError,
    run_n8n_webhook_test,
)
from ..deps import get_audit_context, require_rbac

router = APIRouter(prefix="/n8n-webhook-test", tags=["n8n-webhook-test"])


@router.post(
    "/run",
    response_model=N8nWebhookTestRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def n8n_webhook_test_run(
    payload: N8nWebhookTestRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("C15", "execute")),
    settings: Settings = Depends(get_settings),
) -> N8nWebhookTestRunResponse:
    try:
        execution_context = require_module_execution_ready(
            db,
            module_id=N8N_WEBHOOK_TEST_MODULE_KEY,
            user=user,
            request=request,
            explicit_org_id=payload.org_id,
            key_requirements={"webhook": payload.key_alias},
        )
        return run_n8n_webhook_test(
            db,
            user=user,
            payload=payload,
            audit=get_audit_context(request),
            settings=settings,
            execution_context=execution_context,
        )
    except ModuleExecutionGateError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
            headers={"X-Barong-Error-Code": exc.code},
        ) from None
    except N8nWebhookTestError as exc:
        operation_log_id = str(exc.args[1]) if len(exc.args) > 1 else None
        detail = {
            "code": exc.error_code,
            "message": str(exc.args[0]) if exc.args else str(exc),
            "operation_log_id": operation_log_id,
        }
        if len(exc.args) > 2 and isinstance(exc.args[2], dict):
            detail["result"] = exc.args[2]
        raise HTTPException(
            status_code=exc.status_code,
            detail=detail,
            headers={"X-Barong-Error-Code": exc.error_code},
        ) from None
