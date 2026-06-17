from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin


class SharedModuleRecord(PrimaryKeyMixin, Base):
    __tablename__ = "shared_modules"
    __table_args__ = (
        UniqueConstraint(
            "source_org_id",
            "target_org_id",
            "module_id",
            name="uq_shared_modules_source_target_module",
        ),
        Index("ix_shared_modules_source_org_id", "source_org_id"),
        Index("ix_shared_modules_target_org_id", "target_org_id"),
        Index("ix_shared_modules_target_org_id_module_id", "target_org_id", "module_id"),
        Index("ix_shared_modules_module_id", "module_id"),
        Index("ix_shared_modules_status", "status"),
        Index("ix_shared_modules_created_at", "created_at"),
    )

    source_org_id: Mapped[str] = mapped_column(String(68), nullable=False)
    target_org_id: Mapped[str] = mapped_column(String(68), nullable=False)
    module_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="enabled",
        server_default="enabled",
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
