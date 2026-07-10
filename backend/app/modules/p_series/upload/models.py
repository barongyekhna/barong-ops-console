"""P 上架台账 model。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import PrimaryKeyMixin, TimestampMixin


class PUploadJob(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "p_upload_jobs"

    job_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    product_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="woocommerce"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    external_product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
