"""Owner-only control-plane endpoints for key health results."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...api.deps import require_owner
from ...db.session import get_db, rollback_open_transaction
from ...models.user import User
from .schemas import (
    KeyHealthRunsRead,
    KeyHealthRunTriggerRead,
    KeyHealthSummaryRead,
)
from .service import (
    KeyHealthRunInProgress,
    key_health_summary,
    list_key_health_runs,
    run_key_health_check,
)


router = APIRouter(prefix="/key-health", tags=["key-health"])


@router.get("/summary", response_model=KeyHealthSummaryRead)
def summary_endpoint(
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> KeyHealthSummaryRead:
    del owner
    return KeyHealthSummaryRead.model_validate(key_health_summary(db))


@router.get("/runs", response_model=KeyHealthRunsRead)
def runs_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> KeyHealthRunsRead:
    del owner
    items = list_key_health_runs(db, limit=limit)
    return KeyHealthRunsRead(items=items, count=len(items))


@router.post(
    "/run",
    response_model=KeyHealthRunTriggerRead,
    status_code=status.HTTP_200_OK,
)
def trigger_run_endpoint(
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> KeyHealthRunTriggerRead:
    del owner
    rollback_open_transaction(db)
    try:
        outcome = run_key_health_check(
            trigger="manual",
            scheduled_for=datetime.now(UTC),
        )
    except KeyHealthRunInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="key_health_run_in_progress",
        ) from exc
    return KeyHealthRunTriggerRead.model_validate(outcome, from_attributes=True)
