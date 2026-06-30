"""FastAPI router for the R-series V3 commerce selector."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ....api.deps import get_current_user
from ....core.roles import is_owner_role, is_super_admin_role
from ....db.session import get_db
from ....models.organization import OrganizationRecord
from ....models.user import User
from ....services.permission_service import resolve_current_user_permission_info
from r_series.runtime.commerce_v3 import RCommerceV3Engine, RCommerceV3Error

from .constants import (
    PERMISSION_EXECUTE,
    PERMISSION_READ,
    PERMISSION_REVIEW,
    TARGET_ORGANIZATION_ID,
    TARGET_ORGANIZATION_NAME,
)
from .schemas import (
    RCommerceReportResponse,
    RCommerceReviewRequest,
    RCommerceReviewResponse,
    RCommerceRunRequest,
    RCommerceRunResponse,
    RCommerceSkillResponse,
)


router = APIRouter(prefix="/r", tags=["r-commerce"])


@lru_cache(maxsize=1)
def commerce_engine() -> RCommerceV3Engine:
    return RCommerceV3Engine()


def _request_org_id(request: Request, user: User) -> str | None:
    org_context = getattr(request.state, "org_context", None)
    value = getattr(org_context, "org_id", None)
    if value is None:
        value = getattr(request.state, "org_id", None)
    if value is None:
        value = user.organization_id
    if value is None:
        return None
    org_id = str(value).strip()
    return org_id or None


def _ensure_locked_organization(request: Request, db: Session, user: User) -> None:
    org_id = _request_org_id(request, user)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"R commerce requires organization context: {TARGET_ORGANIZATION_NAME}.",
        )
    if org_id == TARGET_ORGANIZATION_ID:
        return
    organization = db.get(OrganizationRecord, org_id)
    if (
        organization is None
        or organization.status == "deleted"
        or organization.org_name.strip() != TARGET_ORGANIZATION_NAME
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"R commerce is locked to {TARGET_ORGANIZATION_NAME}.",
        )


def _require_r_permission(permission_key: str):
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        _ensure_locked_organization(request, db, user)
        if is_owner_role(user.role) or is_super_admin_role(user.role):
            return user
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed_keys = {permission_key}
        if permission_key in {PERMISSION_EXECUTE, PERMISSION_REVIEW}:
            allowed_keys.add(PERMISSION_READ)
        if (
            permissions.is_owner_full_access
            or allowed_keys.intersection(permissions.permission_keys)
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_key}",
        )

    return dependency


@router.get("/commerce/skills", response_model=RCommerceSkillResponse)
def commerce_skills(
    user: User = Depends(_require_r_permission(PERMISSION_READ)),
) -> RCommerceSkillResponse:
    _ = user
    return RCommerceSkillResponse.model_validate(commerce_engine().skill_status())


@router.get("/commerce/report", response_model=RCommerceReportResponse)
def commerce_report(
    user: User = Depends(_require_r_permission(PERMISSION_READ)),
) -> RCommerceReportResponse:
    _ = user
    return RCommerceReportResponse(report=commerce_engine().latest_report())


@router.post("/commerce/run", response_model=RCommerceRunResponse)
def run_commerce_task(
    payload: RCommerceRunRequest,
    user: User = Depends(_require_r_permission(PERMISSION_EXECUTE)),
) -> RCommerceRunResponse:
    _ = user
    try:
        task_payload = payload.model_dump(mode="python")
        task_payload["organization_id"] = TARGET_ORGANIZATION_ID
        report = commerce_engine().run_task(task_payload)
    except RCommerceV3Error as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return RCommerceRunResponse.model_validate(report)


@router.post("/commerce/review", response_model=RCommerceReviewResponse)
def review_commerce_product(
    payload: RCommerceReviewRequest,
    user: User = Depends(_require_r_permission(PERMISSION_REVIEW)),
) -> RCommerceReviewResponse:
    reviewer = str(user.id) if user.id is not None else user.username
    try:
        result = commerce_engine().review_product(
            action=payload.action,
            product=payload.product.model_dump(mode="python"),
            reviewer=reviewer,
        )
    except RCommerceV3Error as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return RCommerceReviewResponse.model_validate(result)
