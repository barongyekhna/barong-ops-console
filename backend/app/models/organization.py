from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import json_type


class OrganizationRecord(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "length(org_id) = 36 AND org_id LIKE 'org_%'",
            name="organizations_org_id_format_valid",
        ),
        Index("ix_organizations_org_id", "org_id"),
        Index("ix_organizations_status", "status"),
    )

    org_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_type: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        server_default="active",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __init__(self, **kwargs: Any) -> None:
        if "name" not in kwargs and "org_name" in kwargs:
            kwargs["name"] = kwargs["org_name"]
        if "org_name" not in kwargs and "name" in kwargs:
            kwargs["org_name"] = kwargs["name"]
        super().__init__(**kwargs)
