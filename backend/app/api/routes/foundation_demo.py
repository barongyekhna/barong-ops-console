from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.foundation_demo import FOUNDATION_DEMO_MODULE_KEY
from ...schemas.foundation_demo import (
    FoundationDemoLatestResponse,
    FoundationDemoRunResponse,
)
from ...services.foundation_demo_service import (
    FoundationDemoRunError,
    get_latest_foundation_demo,
    run_foundation_demo,
)
from ...services.module_execution_gate import (
    ModuleExecutionGateError,
    require_module_execution_ready,
)
from ..deps import get_audit_context, require_rbac

router = APIRouter(prefix="/foundation-demo", tags=["foundation-demo"])


@router.post(
    "/run",
    response_model=FoundationDemoRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def foundation_demo_run(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("C15", "execute")),
) -> FoundationDemoRunResponse:
    try:
        require_module_execution_ready(
            db,
            module_id=FOUNDATION_DEMO_MODULE_KEY,
            user=user,
            request=request,
        )
        result = run_foundation_demo(
            db,
            user=user,
            audit=get_audit_context(request),
        )
    except ModuleExecutionGateError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
            headers={"X-Barong-Error-Code": exc.code},
        ) from None
    except FoundationDemoRunError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Foundation demo run failed safely; no demo completion "
                "was recorded."
            ),
        ) from None
    return FoundationDemoRunResponse.model_validate(result)


@router.get("/latest", response_model=FoundationDemoLatestResponse)
def foundation_demo_latest(
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("C15", "execute")),
) -> FoundationDemoLatestResponse:
    del user
    result = get_latest_foundation_demo(db)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No foundation demo run has been recorded.",
        )
    return FoundationDemoLatestResponse.model_validate(result)
