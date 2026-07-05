from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from .rw import _target_org_for_user, require_r_series_org
from r_system_v2.ra.framework import load_ra_framework_overview


router = APIRouter(prefix="/r/analysis", tags=["r-analysis"])


@router.get("/status")
def ra_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return _framework_payload(db, user)


@router.get("/framework")
def ra_framework(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return _framework_payload(db, user)


def _framework_payload(db: Session, user: User) -> dict[str, object]:
    target_org = _target_org_for_user(db, user)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-series modules are bound to the target organization only.",
        )
    with without_org_data_isolation():
        return load_ra_framework_overview(db, org_id=target_org.org_id)
