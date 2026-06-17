from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.review import ReviewItem
from ..schemas.reviews import ReviewCreate, ReviewDecisionCreate
from .tenant import current_tenant_org_id, tenant_org_id_for_create

DECISION_STATUSES = {
    "approve_demo": "approved_demo",
    "reject_demo": "rejected_demo",
    "request_changes_demo": "changes_requested_demo",
}


def list_reviews(
    db: Session, *, limit: int, offset: int
) -> list[ReviewItem]:
    org_id = current_tenant_org_id()
    return list(
        db.scalars(
            select(ReviewItem)
            .where(ReviewItem.org_id == org_id)
            .order_by(ReviewItem.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_review(db: Session, review_id: str) -> ReviewItem | None:
    org_id = current_tenant_org_id()
    return db.scalar(
        select(ReviewItem).where(
            ReviewItem.review_id == review_id,
            ReviewItem.org_id == org_id,
        )
    )


def create_review(
    db: Session,
    *,
    payload: ReviewCreate,
    requested_by: int,
) -> ReviewItem:
    review = ReviewItem(
        org_id=tenant_org_id_for_create(),
        review_id=payload.review_id,
        job_id=payload.job_id,
        artifact_id=payload.artifact_id,
        review_type=payload.review_type,
        risk_level=payload.risk_level,
        status=payload.status,
        requested_by=requested_by,
        assigned_to=payload.assigned_to,
    )
    db.add(review)
    return review


def decide_review(
    db: Session,
    *,
    review: ReviewItem,
    payload: ReviewDecisionCreate,
    decided_by: int,
) -> ReviewItem:
    review.status = DECISION_STATUSES[payload.decision]
    review.decision = payload.decision
    review.comment = payload.comment
    review.decided_by = decided_by
    review.decided_at = datetime.now(timezone.utc)
    db.add(review)
    return review
