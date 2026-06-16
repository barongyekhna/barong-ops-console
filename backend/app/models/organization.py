from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import json_type


class OrganizationRecord(Base):
    __tablename__ = "organizations"

    org_id: Mapped[str] = mapped_column(String(40), primary_key=True)
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
