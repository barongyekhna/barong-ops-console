from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.module_control import (
    ModuleControlCenterResponse,
    ModuleControlUpdateRequest,
    ModuleControlUpdateResponse,
)
from ...services.module_control_center import (
    ModuleControlError,
    build_module_control_center,
    update_module_control_state,
)
from ...services.data_isolation import without_org_data_isolation
from ..deps import require_owner

router = APIRouter(prefix="/module-control", tags=["module-control"])


@router.get("/center", response_model=ModuleControlCenterResponse)
def module_control_center(
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ModuleControlCenterResponse:
    del user
    with without_org_data_isolation():
        return build_module_control_center(db)


@router.patch(
    "/organizations/{org_id}/registry-entries/{module_id}",
    response_model=ModuleControlUpdateResponse,
)
def module_control_update(
    org_id: str,
    module_id: str,
    payload: ModuleControlUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
) -> ModuleControlUpdateResponse:
    try:
        with without_org_data_isolation():
            item = update_module_control_state(
                db,
                org_id=org_id,
                module_id=module_id,
                payload=payload,
                actor_user_id=str(user.id),
            )
    except ModuleControlError as exc:
        code = str(exc)
        if code == "organization_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found.",
            ) from exc
        if code == "module_not_registered":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Module not registered.",
            ) from exc
        raise
    return ModuleControlUpdateResponse(item=item)
