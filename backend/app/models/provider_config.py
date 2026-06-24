from typing import Any

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin, json_type


class ProviderConfigRecord(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_config"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "module_id",
            "provider",
            name="uq_provider_config_org_module_provider",
        ),
        Index("ix_provider_config_org_module", "org_id", "module_id"),
        Index("ix_provider_config_provider_status", "provider", "status"),
    )

    org_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    module_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_key_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
        default=dict,
        server_default="{}",
    )
