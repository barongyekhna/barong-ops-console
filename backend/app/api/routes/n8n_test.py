from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...db.session import get_db
from ...models.user import User
from ...schemas.n8n_test import (
    N8nTestCallbackRequest,
    N8nTestCallbackResponse,
    N8nTestLatestResponse,
    N8nTestRunResponse,
)
from ...services.n8n_test_service import (
    N8nTestCallbackAuthenticationError,
    N8nTestCallbackJobError,
    get_latest_n8n_test,
    process_n8n_test_callback,
    run_n8n_test,
)
from ..deps import get_audit_context, require_internal_rbac, require_rbac

router = APIRouter(prefix="/n8n-test", tags=["n8n-test"])


@router.post(
    "/run",
    response_model=N8nTestRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def n8n_test_run(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("C15", "execute")),
    settings: Settings = Depends(get_settings),
) -> N8nTestRunResponse:
    result = run_n8n_test(
        db,
        user=user,
        audit=get_audit_context(request),
        settings=settings,
    )
    return N8nTestRunResponse.model_validate(result)


@router.post(
    "/callback",
    response_model=N8nTestCallbackResponse,
    name="n8n_test_callback",
)
def n8n_test_callback(
    payload: N8nTestCallbackRequest,
    request: Request,
    callback_secret: str | None = Header(
        default=None,
        alias="X-Barong-Callback-Secret",
    ),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> N8nTestCallbackResponse:
    require_internal_rbac("C15D")
    try:
        result = process_n8n_test_callback(
            db,
            payload=payload,
            provided_secret=callback_secret,
            settings=settings,
            audit=get_audit_context(request),
        )
    except N8nTestCallbackAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from None
    except N8nTestCallbackJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    return N8nTestCallbackResponse.model_validate(result)


@router.get("/latest", response_model=N8nTestLatestResponse)
def n8n_test_latest(
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("C15", "execute")),
) -> N8nTestLatestResponse:
    del user
    result = get_latest_n8n_test(db)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No n8n test bridge run has been recorded.",
        )
    return N8nTestLatestResponse.model_validate(result)
