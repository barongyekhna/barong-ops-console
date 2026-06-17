from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import OrgScopedMixin, PrimaryKeyMixin, TimestampMixin


class ReviewItem(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint(
            "job_id IS NOT NULL OR artifact_id IS NOT NULL",
            name="has_review_subject",
        ),
        Index("ix_review_items_org_id_created_at", "org_id", "created_at"),
        Index("ix_review_items_org_id_status", "org_id", "status"),
    )

    review_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=True,
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.artifact_id"),
        nullable=True,
    )
    review_type: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    decision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
