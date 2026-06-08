from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin, json_type


class Artifact(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=False,
    )
    module_id: Mapped[str] = mapped_column(
        ForeignKey("module_registry.module_id"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
    )
