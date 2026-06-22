from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin, json_type


class ModuleControlStateRecord(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "module_control_states"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "module_id",
            name="uq_module_control_states_org_id_module_id",
        ),
        Index("ix_module_control_states_org_id_status", "org_id", "runtime_status"),
        Index("ix_module_control_states_module_id", "module_id"),
    )

    org_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    module_id: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    runtime_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    runtime_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_error_message: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
        default=dict,
        server_default="{}",
    )
