from datetime import date
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...db.compatibility import column_exists
from ...db.session import get_db
from ...models.user import User
from ...repositories.artifacts import get_artifact
from ...repositories.jobs import get_job
from ...repositories.reviews import (
    create_review,
    decide_review,
    get_review,
    list_reviews,
)
from ...repositories.users import get_user_by_id
from ...schemas.common import ListResponse
from ...schemas.module import ModuleManifestRead, ModuleRegistryResponse
from ...schemas.reviews import (
    ReviewAuditAction,
    ReviewAuditEmployee,
    ReviewAuditOrganization,
    ReviewCreate,
    ReviewDecisionCreate,
    ReviewResponse,
)
from ...services.review_audit import (
    DEFAULT_REVIEW_AUDIT_LIMIT,
    MAX_REVIEW_AUDIT_LIMIT,
    ReviewAuditFilters,
    ReviewAuditScope,
    list_review_audit_actions,
    list_review_audit_employees,
    list_review_audit_organizations,
)
from ...services.module_registry import list_module_manifests
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    invalid_reference,
    not_found,
)
from ..deps import get_audit_context, get_current_user, require_rbac

router = APIRouter(prefix="/reviews", tags=["reviews"])
logger = logging.getLogger(__name__)


def _normalized_role(user: User) -> str:
    return user.role.strip().lower()


def _review_scope(request: Request, user: User) -> ReviewAuditScope:
    role = _normalized_role(user)
    if role == "owner":
        return ReviewAuditScope(
            role=role,
            current_org_id=getattr(request.state, "org_id", None),
            is_owner=True,
        )
    if role == "super_admin":
        current_org_id = getattr(request.state, "org_id", None) or user.organization_id
        if current_org_id is None or not str(current_org_id).strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization context is required.",
            )
        return ReviewAuditScope(
            role=role,
            current_org_id=str(current_org_id).strip(),
            is_owner=False,
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Review audit access requires owner or super admin role.",
    )


def _review_filters(
    *,
    organization_id: str | None,
    employee: str | None,
    employee_id: int | None,
    module: str | None,
    start_date: date | None,
    end_date: date | None,
) -> ReviewAuditFilters:
    return ReviewAuditFilters(
        organization_id=organization_id.strip() if organization_id else None,
        employee=employee.strip() if employee else None,
        employee_id=employee_id,
        module=module.strip() if module else None,
        start_date=start_date,
        end_date=end_date,
    )


def _empty_list(limit: int, offset: int):
    return ListResponse(
        items=[],
        count=0,
        limit=limit,
        offset=offset,
        degraded=True,
        source="fallback",
    )


def _ensure_org_visible(scope: ReviewAuditScope, organization_id: str) -> None:
    if scope.is_owner:
        return
    if organization_id != scope.current_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Review audit data is limited to your organization.",
        )


@router.get("", response_model=ListResponse[ReviewResponse])
def reviews(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "read")),
) -> ListResponse[ReviewResponse]:
    del user
    if not column_exists(db, "review_items", "org_id"):
        return _empty_list(limit, offset)
    try:
        items = list_reviews(db, limit=limit, offset=offset)
    except Exception as exc:
        if isinstance(exc, SQLAlchemyError):
            db.rollback()
        logger.warning("review list fallback returned empty data: %s", exc)
        return _empty_list(limit, offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/module-registry", response_model=ModuleRegistryResponse)
def review_audit_module_registry(
    request: Request,
    user: User = Depends(get_current_user),
) -> ModuleRegistryResponse:
    _review_scope(request, user)
    try:
        manifests = list_module_manifests()
    except Exception as exc:
        logger.warning("review audit module registry fallback: %s", exc)
        return ModuleRegistryResponse(
            items=[],
            count=0,
            degraded=True,
            source="fallback",
        )
    items = [
        ModuleManifestRead.model_validate(manifest.model_dump())
        for manifest in manifests
    ]
    return ModuleRegistryResponse(items=items, count=len(items))


@router.get("/organizations", response_model=ListResponse[ReviewAuditOrganization])
def review_audit_organizations(
    request: Request,
    organization_id: str | None = Query(default=None, max_length=40),
    employee: str | None = Query(default=None, max_length=255),
    employee_id: int | None = Query(default=None, gt=0),
    review_module: str | None = Query(
        default=None,
        alias="review_module",
        max_length=128,
    ),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(
        default=DEFAULT_REVIEW_AUDIT_LIMIT,
        ge=1,
        le=MAX_REVIEW_AUDIT_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListResponse[ReviewAuditOrganization]:
    scope = _review_scope(request, user)
    filters = _review_filters(
        organization_id=organization_id,
        employee=employee,
        employee_id=employee_id,
        module=review_module,
        start_date=start_date,
        end_date=end_date,
    )
    try:
        items = list_review_audit_organizations(
            db,
            scope=scope,
            filters=filters,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        if isinstance(exc, SQLAlchemyError):
            db.rollback()
        logger.warning("review audit organization list fallback: %s", exc)
        return _empty_list(limit, offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get(
    "/organizations/{organization_id}/users",
    response_model=ListResponse[ReviewAuditEmployee],
)
def review_audit_users(
    organization_id: str,
    request: Request,
    employee: str | None = Query(default=None, max_length=255),
    employee_id: int | None = Query(default=None, gt=0),
    review_module: str | None = Query(
        default=None,
        alias="review_module",
        max_length=128,
    ),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(
        default=DEFAULT_REVIEW_AUDIT_LIMIT,
        ge=1,
        le=MAX_REVIEW_AUDIT_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListResponse[ReviewAuditEmployee]:
    scope = _review_scope(request, user)
    _ensure_org_visible(scope, organization_id)
    filters = _review_filters(
        organization_id=None,
        employee=employee,
        employee_id=employee_id,
        module=review_module,
        start_date=start_date,
        end_date=end_date,
    )
    try:
        items = list_review_audit_employees(
            db,
            scope=scope,
            organization_id=organization_id,
            filters=filters,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        if isinstance(exc, SQLAlchemyError):
            db.rollback()
        logger.warning("review audit employee list fallback: %s", exc)
        return _empty_list(limit, offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get(
    "/organizations/{organization_id}/users/{user_id}/actions",
    response_model=ListResponse[ReviewAuditAction],
)
def review_audit_actions(
    organization_id: str,
    user_id: int,
    request: Request,
    review_module: str | None = Query(
        default=None,
        alias="review_module",
        max_length=128,
    ),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(
        default=DEFAULT_REVIEW_AUDIT_LIMIT,
        ge=1,
        le=MAX_REVIEW_AUDIT_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListResponse[ReviewAuditAction]:
    scope = _review_scope(request, user)
    _ensure_org_visible(scope, organization_id)
    filters = _review_filters(
        organization_id=None,
        employee=None,
        employee_id=None,
        module=review_module,
        start_date=start_date,
        end_date=end_date,
    )
    try:
        items = list_review_audit_actions(
            db,
            scope=scope,
            organization_id=organization_id,
            user_id=user_id,
            filters=filters,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        if isinstance(exc, SQLAlchemyError):
            db.rollback()
        logger.warning("review audit action list fallback: %s", exc)
        return _empty_list(limit, offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/{review_id}", response_model=ReviewResponse)
def review_detail(
    review_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "read")),
) -> ReviewResponse:
    del user
    review = get_review(db, review_id)
    if review is None:
        raise not_found("Review", review_id)
    return ReviewResponse.model_validate(review)


@router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def review_create(
    payload: ReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "write")),
) -> ReviewResponse:
    if get_review(db, payload.review_id) is not None:
        raise conflict("Review", payload.review_id)
    if payload.job_id and get_job(db, payload.job_id) is None:
        raise invalid_reference("Review job_id is not registered.")
    if payload.artifact_id and get_artifact(db, payload.artifact_id) is None:
        raise invalid_reference("Review artifact_id is not registered.")
    if payload.assigned_to and get_user_by_id(db, payload.assigned_to) is None:
        raise invalid_reference("Review assigned_to user does not exist.")
    review = create_review(db, payload=payload, requested_by=user.id)
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="review.create_demo",
        target_type="review",
        target_id=payload.review_id,
        job_id=payload.job_id,
        details={"status": payload.status},
    )
    db.refresh(review)
    return ReviewResponse.model_validate(review)


@router.post("/{review_id}/decision", response_model=ReviewResponse)
def review_decision(
    review_id: str,
    payload: ReviewDecisionCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> ReviewResponse:
    review = get_review(db, review_id)
    if review is None:
        raise not_found("Review", review_id)
    if review.decision is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Review '{review_id}' already has a demo decision.",
        )
    decide_review(db, review=review, payload=payload, decided_by=user.id)
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="review.decision_demo",
        target_type="review",
        target_id=review_id,
        job_id=review.job_id,
        details={
            "decision": payload.decision,
            "downstream_triggered": False,
        },
    )
    db.refresh(review)
    return ReviewResponse.model_validate(review)
