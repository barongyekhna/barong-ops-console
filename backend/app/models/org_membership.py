from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class OrgMembershipRecord(Base):
    __tablename__ = "org_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="org_memberships_role_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended')",
            name="org_memberships_status_valid",
        ),
        UniqueConstraint(
            "user_id",
            "org_id",
            name="uq_org_memberships_user_id_org_id",
        ),
        Index("ix_org_memberships_user_id_org_id", "user_id", "org_id"),
        Index("ix_org_memberships_org_id", "org_id"),
    )

    membership_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
