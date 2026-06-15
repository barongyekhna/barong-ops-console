from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

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
from ...schemas.reviews import (
    ReviewCreate,
    ReviewDecisionCreate,
    ReviewResponse,
)
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    invalid_reference,
    not_found,
)
from ..deps import get_audit_context, require_rbac

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("", response_model=ListResponse[ReviewResponse])
def reviews(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "read")),
) -> ListResponse[ReviewResponse]:
    del user
    items = list_reviews(db, limit=limit, offset=offset)
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
