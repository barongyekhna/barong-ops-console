from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.operation_logs import (
    get_operation_log,
    list_operation_logs,
)
from ...schemas.common import ListResponse
from ...schemas.operation_logs import OperationLogResponse
from ...services.foundation_service import not_found
from ..deps import require_rbac

router = APIRouter(prefix="/operation-logs", tags=["operation-logs"])


@router.get("", response_model=ListResponse[OperationLogResponse])
def operation_logs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None, pattern=r"^\d+$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> ListResponse[OperationLogResponse]:
    del user
    items = list_operation_logs(db, limit=limit, offset=offset, cursor=cursor)
    next_cursor = str(items[-1].id) if len(items) == limit else None
    return ListResponse(
        items=items,
        count=len(items),
        limit=limit,
        offset=offset,
        cursor=cursor,
        next_cursor=next_cursor,
    )


@router.get("/{operation_id}", response_model=OperationLogResponse)
def operation_log_detail(
    operation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> OperationLogResponse:
    del user
    operation_log = get_operation_log(db, operation_id)
    if operation_log is None:
        raise not_found("Operation log", operation_id)
    return OperationLogResponse.model_validate(operation_log)
