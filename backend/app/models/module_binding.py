from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin


class ModuleBindingRecord(PrimaryKeyMixin, Base):
    __tablename__ = "module_bindings"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "module_id",
            name="uq_module_bindings_org_id_module_id",
        ),
        Index("ix_module_bindings_org_id", "org_id"),
        Index("ix_module_bindings_org_id_status", "org_id", "status"),
        Index("ix_module_bindings_org_id_module_id", "org_id", "module_id"),
    )

    org_id: Mapped[str] = mapped_column(String(68), nullable=False)
    module_id: Mapped[str] = mapped_column(String(128), nullable=False)
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
